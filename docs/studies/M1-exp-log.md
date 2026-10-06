# Study M1: the correctly rounded exp and log family, designed

STATUS: a design study, 2026-10-05. Parcel M1 of the step-6 round,
phase 1 (docs/ROADMAP.md, "Step 6: the math library, revision 8 and
programs past one tile (plan of record, 2026-10-02)", part 5, "M1, exp
and log"). **Nothing here is built.** No routine is in the golden model,
cftc is unchanged, and the language still refuses `exp(x)` as
`transcendental`. The design goes to the lead, and through the lead to
Logan, before phase 2 builds it. This file, the model under
`docs/studies/m1/` and this file's row in docs/README.md are the only
changes the study made.

**Revised the same day,** after verifier-VM1 checked the first version
(5b6de0d; the round's ledger, `verifier-VM1.md`). That check found one
defect: log1p's r = x path ran its polynomial past the bound's rho, and
four fp256 lanes came out wrong and unmarked. The model is repaired
(section 2.3), the defect is listed as number 8 (section 3.6), and every
figure that moved is restated. The repair's own measurements found one
thing more: at fp64 the log family keeps less than the planners' two
bits where its terms cancel (3.2, 3.3), which changes question 1's
recommendation for fp64.

Every statement is one of five kinds, and says which:
- **READ**: from this tree at d4cf250, with the file named;
- **MEASURED**: from a run of the study's model (section 11), on the
  desktop, niced, one process at a time, with its load stated. From
  11:05 the desktop was 88% to 100% busy with Logan's own use, and every
  run after the lead's note on it stopped itself before ten minutes. The
  revision's runs, 16:33 to 17:22, started at loads from 2% to 96%, each
  stated in the ledger;
- **COMPUTED**: arithmetic on read or measured numbers, shown;
- **ESTIMATE**: mine, and said so;
- **PROPOSED**: this design. Every name, constant and order below is a
  proposal for the lead and Logan, not a decision.

## Contents

0. In brief
1. What M1 works with
2. The algorithms
3. The error bound and the in-lane test
4. The specials and the flags
5. The cost
6. The language and the compiler
7. The derivative rules
8. How it will be held
9. Questions for the lead, each with a recommendation
10. What phase 2 builds, in order
11. The model

---

## 0. In brief

- **What.** Six routines, exp, expm1, exp2, log, log1p and log2, at fp32,
  fp64, fp128 and fp256 under each of the five attributes. Each is a
  fragment in C4's shape (`python/cft_golden/routines.py`): straight-line
  SSA, raw-word bank slots, the routine's own internal attributes. It is
  inlined where its node stands, runs quiet and raises exactly the flags
  transcend.py gives (R24). Where its own test cannot decide the last
  bit, it sets bit 7 of the raised word. PROPOSED.
- **How** (PROPOSED; MEASURED in the model):
  - a table-driven reduction: exp by n ln2/8, exp2 by n/8, log by a
    reciprocal from RECIP_SEED;
  - an eight-entry table read by a SELECT tree: bank words only, no
    scratch slot and no LDX;
  - a Taylor polynomial whose head is a double word and whose tail is a
    single word. The double words use TwoProd by FMA, Fast2Sum where the
    exponents are ordered and TwoSum elsewhere. No augadd: the quad is
    built without R21, so one image serves every target;
  - one rounding under the program's attribute from a double word V;
  - an in-lane test that rounds both ends of V's error interval and marks
    the lane where they differ.
- **The guard.** The bound is 2^-(p+G) relative, with G = 46. A random
  argument is marked with probability 2^(0.53-G) a call, 2^-45.5 at
  G = 46. That law is MEASURED with the bound inflated to G = 6: 1.7% to
  2.8% marked against 2.2% to 2.3% predicted, over 12 runs of 2,000.
  Question 1 now recommends G = 44 at fp64, where 46 leaves less than
  two bits of slack in places (below).
- **Held, in the model, against transcend.py** (MEASURED):
  - fp64, fp128 and fp256, six functions, five attributes, over the
    transcend pools (367, 350 and 512 arguments): 0 wrong unmarked lanes;
  - 60,000 random fp64 lane-calls: 0 wrong;
  - on seq.py itself, as stand-alone programs through C4's own harness:
    all 90 configurations (six functions, three formats, five
    attributes, run by verifier-VM1), 0 mismatches; log1p's 15 again
    after the repair, 0.
  - **The pools are not the whole test.** The first model's log1p ran its
    r = x path out to |x| = 2^-4, past the bound's rho. Verifier-VM1
    built four fp256 arguments there that it answered wrong and
    unmarked, in 10 lane-attribute pairs, and the pools hold none of
    them. The repair ends that path at 15/256, under rho, for no extra
    instruction (section 2.3). The four lanes now mark wherever they
    were wrong.
  Marks fall on structured windows of arguments next to an exact case,
  around x = c 2^-e and 1 + c ulp. The windows grow with p - G. Section
  3.5 counts them.
- **The cost** (MEASURED; fragment bodies, plus 3 for QUIET, ENDQUIET and
  RAISE when inlined): exp 178-181 instructions at fp64 and 198-201 at
  fp256; log 193 and 238; log1p, the dearest, 227-229 and 272-274.
  - Bank words: 63 to 122 a function, 140 to 208 for all six together.
  - Scratch slots: none. Live values: at most 24 (34 in the fp32
    triple-word exp).
  - The surveyor's guesses (READ, ROADMAP part 5) were 150 at fp64 and
    750 at fp256, with a 32-entry table and about 100 bank constants.
    The head of the polynomial is set by G and not by p, so fp256 costs
    about 10% to 25% more than fp64 rather than five times as much.
- **fp32 is the dear format.** A double word at p = 24 floors at about
  2^-44.7, which caps G near 18, so the plan's triple word is needed. A
  triple-word exp is MEASURED at 413 instructions at G = 46 and 382 at
  G = 40. Section 2.5 and question 2.
- **fp64 is the thin format at G = 46.** The bound holds wherever it was
  measured, at every format. But at fp64 two regions of the log family
  keep less than the planners' two bits (MEASURED, 20,000 arguments
  each):
  - log1p for x from -1/8 to -15/256: 2^-1.8 under the bound;
  - log2 for x from 0.875 to 0.94: 2^-2.2 under.
  Both are cancellation. The double word's floor is set by the terms
  being summed, and there they are up to 22 times the result. A coarse
  count, letting every rounding take that factor, does not show the
  bound at G = 46 there, and shows it at G = 44, just. G = 44 at fp64
  keeps at least 2.6 bits in every region measured, for 0 to 7
  instructions fewer (3.2, 3.3, question 1).
- **Two findings for the lead:**
  - transcend.py's exp2 of the exact tie emin - p returns +0 under rmm,
    where 754's roundTiesToAway gives the smallest subnormal (question 5);
  - the tangent rules of exp2 and log2 need ln 2 as a constant. This
    design writes it as the exact rational value of ln 2 rounded once, so
    a constant stays an exact rational (question 6).
- **The model found seven of its own defects** before this design
  settled, and verifier-VM1 found an eighth; section 3.6 lists them.
  Four were invisible to the pools: they passed defect 1 with an error
  of 2^-64 present, and hold no argument of defect 8. That decides how
  phase 2 must be held (section 8). The pools are not the test of a
  bound. The test is the error measured against an independent
  reference, at each path's own worst points.

## 1. What M1 works with

### 1.1 The plan, and what binds it

READ, docs/ROADMAP.md, step 6, part 5:
- the golden definition is `cft_golden/transcend.py` for every
  function, and each routine is held on seq.py against it over the
  existing pools, through `program.c`, and then on the card;
- M1 is exp, expm1, exp2, log, log1p and log2, "Double-word in the
  program's format, using augmented addition; at fp32, triple-word";
- "An in-lane test of whether the last bit is decided. A lane that is not
  is marked through R8F's raise and replayed, as certificate version 2's
  design says";
- the surveyor's estimates, "nothing measured": about 100 bank constants
  at fp64 with a 32-entry table, and about 150 instructions a call at
  fp64 and 750 at fp256;
- each function gains an L3 derivative rule.

What binds that plan since it was written (READ):
- **No augadd.** Revision 8's question 9 and probe L (ROADMAP, "Revision
  8", the Approval; SEQUENCER.md, R21) measured R21's lanes at +10,595
  LUTs a tile, so the quad is built without R21. Question 9's recommended
  branch, which Logan approved, writes M1 with TwoSum on every target
  until every image carries R21: one image, the same bytes, on every
  target. This design uses no augadd anywhere. Where the exponents of
  the two terms are provably ordered it uses Fast2Sum (3 instructions);
  elsewhere it uses TwoSum (6). SEQUENCER.md's table prices a
  compensated step at 8 against augadd's 3.
- **The rounding rule.** Logan's rule (the brief; SEQUENCER.md's revision
  8 preamble quotes it) puts IEEE 754 first. Correctly rounded exp,
  expm1, exp2, log, log1p and log2 are among IEEE 754-2019's recommended
  operations, clause 9.2, table 9.1 (transcend.py's docstring).
- **The order** (ROADMAP, "The order"): M1 follows C4 and R8L, and both
  are built.

### 1.2 What a tile gives a routine

READ (softfloat.py, seq.py, SEQUENCER.md, routines.py, cftc):
- **Arithmetic:**
  - FMA, ADD, SUB and MUL, each with its own rounding attribute in the
    instruction;
  - the integer group on the whole W-bit encoding: IAND, IOR, IXOR,
    IADD, ISUB, ISHL, ISHR (logical) and ICMPLT (unsigned);
  - the quiet compares CMPLT, CMPLE and CMPEQ, which answer 1.0 or +0.0;
  - SELECT, c ? a : b on c's magnitude;
  - ABS and NEG;
  - RECIP_SEED, about 8.5 bits of 1/m from a 512-entry table.
- **What there is not:** no branch, no call, and no float-integer
  conversion. The bank is 512 constants, addressed only by the
  instruction's immediate. So a table read at a computed index is a
  SELECT tree over bank words, or an LDX from a copy in each lane's
  scratch.
- **R24, flag control:**
  - QUIET and ENDQUIET bracket a region whose flags reach neither FLAGS
    nor R23's byte;
  - RAISE ORs a register's bits [4:0] into both;
  - RAISE also marks the lane where bit 7 is set: R23's [7] and
    STATUS[6]. A region never silences a mark.
  A routine runs QUIET, its body, ENDQUIET, then RAISE of its flag word,
  exactly as C4's do (`python/cftc/inline.py`).
- **C4's machinery,** which M1 reuses whole (READ):
  - Fragments derive mechanically from a golden program.
  - The specialisation rules live in `routines.simplify`.
  - The inliner hash-conses a routine's instructions across instances.
  - A word is a bank slot of its own kind, one slot for each distinct
    bit pattern.
  - The internal check holds each image to its fragments.
  - Revision 7's targets refuse an image with a routine,
    `target-feature`.
  - The call loop takes a step past 32,768 instructions.

### 1.3 The definition

READ, `python/cft_golden/transcend.py`, the exp and log families:
- **The exact cases are decided exactly:** exp(+-0) = 1; expm1(+-0) and
  log1p(+-0) are the operand; exp2 of an integer; log(1) = +0; log2 of a
  power of two.
- **Three families are decided by the side of a representable neighbour,**
  never by a working precision:
  - exp and exp2 of |x| < 2^-(p+3);
  - expm1 and log1p of |x| < 2^-(p+2);
  - expm1 of an x whose e^x is below 2^-(p+3).
- **Screens** at low precision answer what provably overflows or
  underflows.
- **Everything else goes through a Ziv loop** on mpmath's interval
  context, from 2p + 40 bits up to min(8p + 128, 832). It accepts a
  rounding only when both ends of the enclosure give the same bits AND
  the same flags.
- **What the stage holds:** host/tests/transcend_check.py holds libcft's
  evaluator to it over `unary_pool` (64 random encodings at fp32 and
  fp64, 16 at fp128 and fp256, beside the named families), as does the
  vector set's `vectors.transcend_unary_pool`.

The routine must give transcend.py's bits and flags on every lane it
does not mark. Nothing in the routine is "close": an unmarked lane is
right by the test of section 3.1, or it is a defect.

## 2. The algorithms

### 2.1 One shape for six routines

PROPOSED. Every routine is one fragment of seven parts, all of them run
on every lane, since there is no branch:

1. **classify** the operand from its encoding: NaN, signalling, infinity,
   zero, sign, and the screens' comparisons (8 to 12 instructions);
2. **reduce** it to a small r, exactly or as an exact double word;
3. **look up** the table by a SELECT tree over three bits of an integer
   the reduction already holds (17 instructions for two words);
4. **evaluate** a polynomial: a single-word Horner tail by FMA, then K
   double-word Horner steps;
5. **reconstruct** a double word V in a scaled domain;
6. **round once** under the program's attribute, and **test**
   (section 3.1);
7. **select** the special lanes' answers over the main path's, lowest
   priority first, as divfull does. The flag word is built the same way,
   from constant words, so its possible values are a finite set
   (section 4).

The internal arithmetic is RNE. The routine's own attributes are RTZ for
round-to-odd, RDN and RUP for the test's bounds, and the program's
attribute for the final roundings. C4's `routines.invariants` admits only
RNE and RTZ, and phase 2 widens it (section 6).

### 2.2 exp, exp2 and expm1

PROPOSED; every step MEASURED in the model (section 3.3).

**Reduction.** N = 8.
- **exp and expm1:** n = round(x 8/ln2) by the magic-number FMA
  t = fma(x, RN(8/ln2), M), with M = 1.5 * 2^(p-1). t's encoding is
  M's plus n, so j = n mod 8 is t's three low bits, and 2^k's exponent
  field is arithmetic on t. Then r = x - n ln2/8 by Cody-Waite in three
  words:
  - C1 holds p - nb bits, so n C1 is exact. nb is the width of |n|: 14
    bits at fp64, 22 at fp256 (COMPUTED from the screens).
  - x - n C1 is exact by Sterbenz.
  - n C2 is exact as MUL plus FMA, and TwoSum adds it.
  - n C3 is rounded into the low word.
  So r = r_h + r_l, with an error near 2^-110 absolute at fp64 (COMPUTED,
  section 3.2). 14 instructions.
- **exp2:** n = round(8x) exactly, the same way; r' = x - n/8 is exact,
  by Sterbenz; r = r' ln2 is a double word by TwoProd against a two-word
  ln2. 7 instructions. r' = 0 together with j = 0 is the exact case, x an
  integer.

**Table.** T_j = 2^(j/8) as two words, rounded from mpmath at 3,000 bits:
14 SELECTs over j's three bits, 17 instructions with the bit tests.
T_0 = 1 exactly.

**Polynomial.** Y(r) = (e^r - 1)/r = sum r^i/(i+1)!, Taylor:
- the coefficients are exact rationals rounded once; Taylor rather than
  minimax, because its remainder is a rigorous one-line bound;
- |r_h| <= rho = (1/2 + 2^-30) ln2/8 = 2^-4.53;
- the tail runs from degree D down to K by FMA;
- K double-word steps (8 instructions each: MUL, two FMAs, Fast2Sum
  against the coefficient, two adds) take it down to the constant term;
- Fast2Sum is valid there because |r y_(i+1)| is at most rho/(i+2) of
  c_i, under 1/40, at every step (COMPUTED).

K and D come from the bound (section 3.2): K = 7 for exp and exp2, and 8
for expm1, whose n = 0 lanes are bounded relative to Z. D is 13, 20 and
33 at fp64, fp128 and fp256.

**Z = e^r - 1.** Z = r_h Y(r_h) + r_l e^(r_h), with e^(r_h) as
1 + Z_h. The first model carried r_l through Y(r_h) and was off by
r_l r_h / 2 (section 3.6, defect 1).

**Reconstruction.** V = T (1 + Z) as a double word, normalised by
Fast2Sum (13 instructions). For expm1, V' = T (1 + Z) - 2^-k in the same
scaled domain: (T_h - 2^-k) by TwoSum, with 2^-k taken as 0 beyond
k = p + G + 2, where it is below the bound. Then the same Fast2Sum
holds, since |T_h - 2^-k| >= |T Z| in every case (COMPUTED from the
table's values).

**The final rounding** (section 3.1 gives the test):
- **k > emin** (the result cannot be subnormal): R = rnd(V_h + V_l) is
  the precision-p rounding of the scaled value, and the result is
  R 2^k1 2^k2, with k1 = floor(k/2) and k2 = k - k1, so both factors are
  normal for every k the screens let through. The first product is
  exact. The second rounds once, so an overflow gets 754's response for
  the attribute.
- **k <= emin** (the result may be subnormal): rounding V at precision p
  and then scaling would round twice, and so would rounding V_h alone,
  since V_l breaks the subnormal grid's ties. The fixed grid is
  u = 2^(emin - p + 1 - k) in the scaled domain.
  - Add C = 2^(emin - k) (2^-4 when k = emin), so the binade of C + V
    has ulp u.
  - Split by Fast2Sum, and add V_l's share after rounding it to odd at
    precision p. At k = emin, C = 2^-4 is smaller than V_h, so this
    Fast2Sum's ordering fails by design. The split is exact all the
    same, because C is a power of two and a multiple of ulp(V_h): for
    V_h in [1, 2), C + V_h stays under 2 and is representable; for V_h
    in [0.5, 1) it is a multiple of 2^-p, and its rounding leaves
    Z0 - C and V_h - (Z0 - C) exact. COMPUTED; verifier-VM1 checked the
    identity on every lane it ran.
  - Round once under the program's attribute, and subtract C.
  Round-to-odd is innocuous here because its ulp is finer than u/4. The
  result, a multiple of u, scales to the subnormal grid exactly. This
  costs 21 instructions on every lane (exp and exp2 only: expm1 is never
  subnormal off its tiny path).
- **Flags:**
  - inexact on every main-path lane;
  - underflow where k < emin, or where k = emin and R < 1: 754's
    tininess after rounding, which R decides;
  - overflow where the result is +inf under rne, rmm and rup, or where
    R 2^k >= 2^(emax+1) under rtz and rdn, by one MUL under rup.

### 2.3 log, log2 and log1p

PROPOSED; MEASURED in the model.

**Reduction:**
- x = 2^E m with m in [1, 2), a subnormal x first scaled by 2^p, exactly.
- C = round(16 RECIP_SEED(m)) by the magic-number FMA, which COMPUTED
  over all 512 seed cells takes exactly the values 8 to 16. C = 8 wraps:
  m' = m/2, C = 16, k = E + 1.
- c = C/16, by one FMA on t, exact.
- r = m' c - 1 is ONE FMA and exact. m' c is an integer times
  2^-(p+3), and |r| < 2^-4.08 keeps that integer under p bits (COMPUTED;
  the wrapped case is Sterbenz).
- max |r| = 0.0590820 = 2^-4.081 exactly, at C = 9, over all 512 seed
  cells, the same at every format (COMPUTED, `rmax.py`).

**Table.** log(16/C) as two words for C = 9 to 16, indexed by C mod 8.
C = 16 gives 0, so x near 1 takes j = 0 and k = 0, and log x = log1p(r)
with r = x - 1 exact. There is no cancellation at 1.

**Polynomial.** Y(r) = log1p(r)/r = sum (-1)^i r^i/(i+1), with the same
tail and head, K = 12, and D = 23, 38 and 68. The exact coefficients
1, 1/2, 1/4 and 1/8 save an add each.

**The sum.** log x = k ln2 + L_j + r Y. ln2 needs three words: the first
two of p - nk bits each, so k ln2_h and k ln2_m are exact, and the third
of p bits. nk is the width of |k|: 11 bits at fp64, 19 at fp256. Two
words, the first model's choice, were short by 2^3 (section 3.6,
defect 2).
- Fast2Sum adds k ln2_h and L_j: |k ln2| >= |L_j| wherever k != 0, and
  the sum is exact where k = 0.
- TwoSum adds the polynomial: the exponents can tie at C = 15.
- Fast2Sum adds k ln2_m.
- The rest goes into the low word.
22 instructions.

**log2** = k + (L_j + r Y)/ln2: the bracket is a double word, multiplied
by a two-word 1/ln2, then Fast2Sum against the exact k. The exact case is
r = 0, which happens only at C = 16, so x is a power of two. The table is
the natural logarithm's, so log, log2 and log1p share their words.

**log1p.** u = 1 + x by TwoSum; the core then runs on u_h.
- u_l enters as r_l = u_l 2^-k c, corrected by r_l/(1 + r).
- 1/(1 + r) takes three Newton steps from 1 - r: 2^-8, 2^-16, 2^-32,
  2^-64, and then the last step's rounding, u.
- 2^-k is taken as 0 past k = p + G + 2, where u_l moves the result by
  less than the bound. The first model built 2^-k there and returned a
  NaN at max_normal (section 3.6, defect 5).
- **|x| < 15/256 skips the reduction:** r = x, with k = 0 and C = 16.
  - Some threshold is needed: for small x the reduction's sum cancels
    down to x, and the correction, relative to a result near 2^-50,
    would need more than its 2^-64.
  - The threshold must not pass rho, since the polynomial's K and D are
    planned for |r| <= rho. 15/256 = 2^-4.093 is under rho = 2^-4.08,
    so one rho, K and D serve both paths.
  - The first model's threshold was 2^-4, past rho. At fp256 its
    truncation there reached 2^0.93 times the bound (section 3.6,
    defect 8).
  - The band [15/256, 2^-4) now takes the reduction: C = 15 for x > 0;
    for x < 0, k = -1 with C = 9, or the wrap. |r| stays inside
    rmax.py's 0.0590820.
  - Verifier-VM1's other repair holds too, for one FMA more: keep 2^-4
    and plan log1p's D from rho = 2^-4 (MEASURED, 3.3).
The low word costs 25 instructions, and log1p's total is 34 to 36 more
than log's. The threshold is a bank word of its own; 2^-4 had shared
the reduction's word 1/16.

**The final rounding.** A log-family result is always normal and never
overflows, so R = rnd(V_h + V_l) is the answer, and inexact is its only
flag off the special paths.

### 2.4 The working precision, and why the head does not grow with p

COMPUTED from section 3.2's terms. The error a Horner value carries in a
single word is about u |y_i|, and it reaches V scaled by r^(i+1):
- **The double-word head** must cover every i with
  rho^(i+1) |c_i| > 2^-G. That depends on G and rho, and not on p:
  K = 7 for exp at every format, and 12 for the log family.
- **The single-word tail's length** is set by truncation,
  rho^(D+2)/(D+2)! under 2^-(p+G): degree 13 at fp64 and 33 at fp256 for
  exp.
  Each further degree is one FMA.

So fp256 pays 20 more FMAs than fp64 for exp and 45 for log, and nothing
else (MEASURED, section 5.1). The plan's "double-word" is right in kind,
but a double word holds 2p bits and the design uses p + G of them, so
nothing past the head pays for double words. The double word's own floor
is about 10u^2 (COMPUTED from the roundings counted in section 3.2), so
G can reach 47 at fp64 before triple words are needed, and well past 60
at fp128 and fp256 (MEASURED, `alts.py`).

That floor is relative to the terms being summed, and it reaches V
amplified where the terms cancel:
- in the log family at k = -1 with C = 9 (x from about 0.875 to 0.94,
  and log1p's x from -1/8 to -15/256), where k ln2 and L_j nearly
  cancel;
- in log1p near its reduction path's lower end, where u_l is relative
  to 1 + x, not to the result.
At fp64 that costs G = 46 its two bits of slack there (3.2, 3.3,
question 1). At fp128 and fp256 the amplified floor is still more than
50 bits under the bound.

### 2.5 fp32

The plan's choice is triple-word. MEASURED and COMPUTED:
- **A double word is not enough.** Its floor at p = 24 is about
  10u^2 = 2^-44.7, so the largest G is about 18: a mark rate near
  2^-17.5 a call, one in 185,000.
- **A triple-word exp holds** (`m1exp32.py`): ln2/8 in five words (three
  of 13 bits), the table in three words, four triple-word head steps,
  three double-word steps, a triple-word reconstruction, and the final
  rounding through round-to-odd of the low words. Its first version was
  0 wrong over the fp32 pools under all five attributes, at 405-408
  instructions, 72-73 words and 31-32 live values (MEASURED). The final
  version, after the three fixes below, is 413 instructions with 34 live
  at G = 46. It is MEASURED 0 wrong on 600 random arguments and against
  its bound; its run over the pools was cut short by the desktop's load,
  and goes to phase 2.
- **Its bound took three fixes,** each a term that is negligible at fp64
  and 2^-57 to 2^-64 at fp32 (section 3.6, defect 7):
  - e^(r0) needs Z(r0)'s second word;
  - e^(r1+r2) - 1 needs its square term;
  - that term carries e^(r0).
- **After them,** against mpmath on 600 random arguments (MEASURED):
  - at G = 46 the worst error is 2^-0.04 times the bound, the edge: the
    reduction's third-level sum, about 2^-70, is now the binding term,
    and a two-word sum there is the fix (about 8 instructions, ESTIMATE);
  - at G = 40 it is 2^-6.0 (382 instructions);
  - at G = 32 it is 2^-8.3 (344).
- **The other five at fp32,** ESTIMATE: about twice their fp64 cost, by
  the same structure. log's r stays exact in one word, which saves the
  reduction's triple word, so log should land nearer 1.8 times.
- **The model is generic** (expansions summed by TwoSum chains), so a
  hand-tuned fp32 routine should be cheaper. By how much is not
  measured.

So fp32 costs about twice fp64 for the same G. Question 2 asks which G.
The recommendation is G = 40 at fp32: a mark rate of 2^-39.5 a call, and
the bound MEASURED with 2^-6 to spare. An exhaustive sweep of fp32's
2^32 inputs, a box job, would then count the marks exactly.

### 2.6 The parameters, format by format

COMPUTED (`consts_report.py`), at G = 46:

| | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| exp overflow screen, x >= | 88.72284 | 709.78271289 | 11356.523406 | 181704.37450 |
| exp underflow screen, x <= | -103.97208 | -745.13321910 | -11433.462743 | -181867.26409 |
| exp2 screens | >= 128, <= -150 | >= 1024, <= -1075 | >= 16384, <= -16495 | >= 262144, <= -262379 |
| expm1 to -1 by side, x <= | -18.0218 | -38.1231 | -79.7119 | -165.662 |
| width of n, of k | 11, 8 | 14, 11 | 18, 15 | 22, 19 |
| exp, exp2: K, D | triple-word (2.5) | 7, 13 | 7, 20 | 7, 33 |
| expm1: K, D | | 8, 13 | 8, 20 | 8, 33 |
| log family: K, D | | 12, 23 | 12, 38 | 12, 68 |

The screens are one-sided and exact on the encoding:
- x >= the overflow screen gives e^x > 2^(emax+1), which overflows under
  every attribute;
- x <= the underflow screen gives e^x < 2^(emin-p), half the smallest
  subnormal.
Between each screen and the true threshold, the main path decides,
including every attribute's own overflow point. The pools hold those
points: n ln2 at emax, emax + 1, emin, emin - man_w and their
neighbours.

## 3. The error bound and the in-lane test

### 3.1 The test

PROPOSED. V = V_h + V_l is the scaled result, with a bound B, relative,
on its distance from the true value. Bv = 2^-(p+G) |V_h| is an exact
product by a power of two. Then:

    lo_dn = RD(V_l - Bv)     lo_up = RU(V_l + Bv)
    R1 = rnd(V_h + lo_dn)    R2 = rnd(V_h + lo_up)    mark = R1 XOR R2

- rnd is the program's attribute; RD and RU are the routine's own.
- Every rounding is monotone, and the true value lies in
  [V - Bv, V + Bv], which is inside [V_h + lo_dn, V_h + lo_up]. So the
  true value's rounding lies between R1 and R2. Where they are equal, it
  IS R1.
- So are its flags. Overflow and tininess after rounding are both
  functions of the precision-p rounding of the scaled value (section
  2.2), which R1 = R2 fixes.
- The cost is six instructions and one more for Bv. The mark is
  IXOR(R1, R2) used as a SELECT condition, and costs two more to OR 0x80
  into the flag word.
- The guess R = rnd(V_h + V_l) is computed separately, one instruction,
  so that a marked lane's value is the routine's best guess and the
  certificate's `changed` (CERTIFICATES.md, version 2) counts real
  misses.

**The fixed-grid path** (exp and exp2, k <= emin) adds its own test. Its
boundaries are on the precision-p grid, so the true value can straddle
one only where z, V_h's offset from the grid, IS a boundary (+-u/2 for
rne and rmm, 0 for the directed three) and |V_l| <= Bv. The lane is
marked there too. The tininess threshold at k = emin is a precision-p
boundary, so the main test above, which runs on every lane, covers it.

**Where the test is not consulted:**
- the exact cases, which carry no mark and no inexact;
- the specials and the screens;
- the tiny arguments of exp and exp2. transcend.py decides those by
  side, and the routine's R is that side. Its bound is relative to V,
  not to |V - 1|, so the test would mark them needlessly: 69 to 70 of
  the 367 fp64 pool lanes under the directed attributes, MEASURED before
  the gate.

### 3.2 The bound, written out

COMPUTED (`bound_terms.py`). u = 2^-p; rho is the reduction's bound on
|r|; K and D are as in 2.6.

**exp and exp2,** relative to V:

    B_V <= 2u rho^(K+1)/(K+1)!               single-word tail, through r^(K+1)
         + rho^(D+2)/(D+2)! (1 + rho)        Y's truncation, through r
         + 10 u^2                            the head (about 3u^2), Z's
                                             products (2u^2 rho), the
                                             reconstruction (about 5u^2),
                                             T's representation (2u^2)
         + 2u 2^-(p+4.5)                     the reduction (r's low word)

| | 2u rho^(K+1)/(K+1)! | truncation | 10u^2 | reduction | total | bound 2^-(p+46) |
|---|---|---|---|---|---|---|
| fp64 | 2^-103.5 | 2^-108.1 | 2^-102.7 | 2^-109.5 | 2^-102.0 | 2^-99 |
| fp128 | 2^-163.5 | 2^-169.5 | 2^-222.7 | 2^-229.5 | 2^-163.5 | 2^-159 |
| fp256 | 2^-287.5 | 2^-291.4 | 2^-470.7 | 2^-477.5 | 2^-287.4 | 2^-283 |

expm1's n = 0 lanes are bounded relative to Z, which drops one factor
rho from the tail. That is why K = 8 there (total 2^-102.0, 2^-164.6 and
2^-286.7).

expm1 has one term more, which the formula above and the planner both
leave out: the clamp. 2^-k is dropped for k > p + G + 2, which moves V'
by at most 2^-(p+G+3) against |V'| >= 0.95: 2^-2.9 of the bound.
- Where the truncation's worst r meets the first clamped k, the sum
  could reach 2^-1.4 of the bound. It is MEASURED at 2^-2.9 (3.3).
- Moving the clamp to k > p + G + 4 costs nothing, since only a
  compare's constant changes, and takes the term to 2^-4.9. Phase 2's
  choice.

Every error-free step is exact, the fixed grid's Fast2Sum included,
whose ordering fails at k = emin (2.2).

**The log family,** relative to V:

    B_V <= 2u rho^K/(K+1)                    single-word tail
         + rho^(D+1)/((D+2)(1 - rho))        truncation
         + 12 u^2 A                          head, product, the sum's five
                                             roundings, the table
         [log1p, reduction path: + about 3.5 u^2 / |V|, the low word]

**rho, path by path.** The reduction path's |r| is at most 0.0590820
(rmax.py, exact over the 512 seed cells). log1p's r = x path has
|r| = |x| < 15/256 = 0.0586. Both are under rho = 0.0592, so one K and D
serve the family. The first model's r = x path reached 2^-4, where the
truncation is (1/16)^69/(70 (15/16)) = 2^-282.0 at fp256, past the
bound's 2^-283 (defect 8). So the bound test of section 8 must find each
path's own largest |r|, not only the seed cells'.

**A, the cancellation factor,** is (|k ln2| + |L_j| + |r Y|)/|V|. The
12u^2 is counted against the terms, so it reaches V multiplied by A.
- A is about 1 almost everywhere.
- It reaches about 22 where k = -1 and C = 9: x from about 0.875 to 0.94
  for log and log2, and log1p's x from -1/8 to -15/256. There k ln2 and
  L_j nearly cancel.
- A coarse count lets every one of those roundings take the full
  factor. At fp64 it gives about 2^-97.9 in all, which does not show
  the bound at G = 46 (2^-99). With G = 44's shorter head it gives
  2^-97.7, and 2^-97.5 with log1p's low word added: under the bound at
  G = 44 (2^-97).

**log1p's low word,** on the reduction path, adds terms of about u^2
absolute each:
- y's rounding, |r_l| u;
- the correction's own rounding;
- the square term it leaves out, (r_l/(1 + r))^2/2;
- the two single-word sums that carry it.
- In all they come to about 3.5u^2, over |V| >= log1p(15/256) = 0.0569:
  2^-(2p - 5.95), which is 2^-100.05 at fp64.
- For x > 0 (k = 0, C = 15, A about 1.3) the worst-case sum is then
  2^-0.8 of the bound. For x < 0, A dominates.
- The first version wrote only y's term, |r_l| (2^-64 + u)/|V|.

**The totals where A = 1.** At fp64: tail 2^-104.6 with K = 12,
truncation 2^-102.4 at D = 23, and 12u^2 = 2^-102.4: about 2^-101.3,
against 2^-99. At fp128 2^-164.6, 2^-164.3 and 2^-222.4, about 2^-163.5
against 2^-159. At fp256 2^-288.6, 2^-287.4 and 2^-470.4, about
2^-286.9 against 2^-283. At fp128 and fp256, A and the low word move
nothing: 12u^2 times 22 is 2^-218 and 2^-466.

The planners choose the smallest K and D whose estimated total is two
bits under 2^-(p+G). At one bit, fp128 took D = 19 and 37, and the
placed points of 3.3 came to 2^-1.5 under the bound, as the estimate
said. One FMA more there gives about nine bits, since each degree
divides the truncation by about rho/(D+3).

The planners count neither A nor the low word. At fp128 and fp256 that
changes nothing. At fp64 it is why G = 46 keeps under two bits in the
cancellation cells: MEASURED, 2^-1.8 (log1p) and 2^-2.2 (log2) (3.3).

Phase 2 owes this a proof term by term, and section 8 says what holds
it. The constants 10, 12 and 3.5 are counted from the model's
instruction sequence, not proved. At fp64 and G = 46, that proof must
count, rounding by rounding, which terms each rounding scales with. At
G = 44 the coarse count already suffices.

### 3.3 Measured against it

MEASURED. Each figure is the worst |V - true| / Bv over the lanes whose
answer is the main path's; "true" is mpmath at 4p + 200 bits. Every lane
also compared with transcend.py agreed or was marked, except the first
model's four lanes of defect 8.

| | random arguments | placed at each path's largest \|r\| | weighted (verifier-VM1, amd-arc-box) |
|---|---|---|---|
| fp64 exp, exp2, expm1 | 2^-6.2, 2^-6.1, 2^-4.9 (2,000 each, x 5 attributes) | 2^-5.7, 2^-5.6, 2^-4.6 | 2^-5.4, 2^-5.2, 2^-3.0 (100,000 each) |
| fp64 log, log2, log1p | 2^-3.3, 2^-3.1, 2^-3.1 | 2^-3.6, 2^-3.8, 2^-2.8 | 2^-3.2, 2^-2.5, see (*) |
| fp128 exp, exp2, expm1 | 2^-6.6, 2^-6.8, 2^-10.9 (400) | 2^-6.3, 2^-6.5, 2^-6.0 | 2^-6.1, 2^-6.1, 2^-3.0 (60,000 each) |
| fp128 log, log2, log1p | 2^-19.0, 2^-19.0, 2^-7.2 (400, at D = 39) | 2^-5.3, 2^-5.3, 2^-5.3 | 2^-5.0, 2^-5.0, see (*) |
| fp256 exp, exp2, expm1 | 2^-6.1, 2^-6.8, 2^-8.5 (300) | 2^-5.9, 2^-5.8, 2^-3.9 | 2^-5.8, 2^-5.8, 2^-3.8 (60,000 each) |
| fp256 log, log2, log1p | 2^-26.3, 2^-26.3, 2^-26.2 (200) | 2^-4.9, 2^-4.9, 2^-4.9 | 2^-4.6, 2^-4.7, see (*) |
| fp32 exp, triple-word | G = 46: 2^-0.04; G = 40: 2^-6.0; G = 32: 2^-8.3 (600) | | G = 46: 2^+0.89, which fails; G = 43: 2^-2.1; G = 40: 2^-4.7 (30,000 to 150,000) |

(*) VM1's log1p figures measured the first model, at its r = x path's
end, which is defect 8: 2^-1.55 at fp64, 2^-2.18 at fp128 and 2^+0.93
at fp256.

The fp64 random rows are the 60,000-lane run again, at the final
parameters, with `in_main` taking the model's own screens. The first
version cited a run with the log family still at D = 24, and its filter
skipped the last unit at each end of the exp family's range.

**Placed** (`worstcase.py`, revised) means each path's own largest |r|:
- the exp family: x next to (n +- 1/2) ln2/8 and (2n +- 1)/16;
- log and log2: m at the ends of the first and last C = 9 seed cells,
  times 2^k;
- log1p: those cells as x = m 2^k - 1, also with the low word of 1 + x
  at its largest, together with the r = x path's end (|x| just under
  15/256) and the reduction path's lower end.

The first version placed no log1p point on the r = x path, which is how
defect 8 went unseen there, and built each exp-family point twice.
log1p's placed column fell from 2^-6.1, 2^-8.7 and 2^-8.3 to 2^-2.8,
2^-5.3 and 2^-4.9: the new points are the worse ones, as they should be.
Random arguments at fp256 show a margin of 2^-26 only because the
truncation goes as (r/rho)^69 and random arguments rarely sit at rho.
Placed, the margin is 2^-2.8 to 2^-6.5. The bound binds where it should.

**log1p's two paths at their ends** (`repair.py`): the worst over both
signs, for the first model, verifier-VM1's repair (2^-4 with D + 1) and
this model's (15/256 with D). Random arguments with every bit random,
3,000, 2,000 and 800 a region and sign at fp64, fp128 and fp256, plus
fixed points at each end.

| | the r = x path's end, \|x\| in [0.054, 15/256) | the band [15/256, 2^-4) | [2^-4, 2^-3), the reduction path |
|---|---|---|---|
| fp64: first, VM1's, this | 2^-3.7, 2^-5.6, 2^-3.7 | 2^-1.6, 2^-4.5, 2^-1.9 | 2^-2.0, 2^-2.0, 2^-2.0 |
| fp128 | 2^-5.2, 2^-6.5, 2^-5.2 | 2^-2.2, 2^-5.8, 2^-5.0 | 2^-7.7, 2^-8.1, 2^-7.7 |
| fp256 | 2^-5.1, 2^-6.7, 2^-5.1 | 2^+0.93, 2^-2.9, 2^-4.8 | 2^-8.5, 2^-8.5, 2^-8.5 |

- Verifier-VM1's four fp256 lanes, all five attributes, against
  transcend.py: the first model is wrong and unmarked in 10
  lane-attribute pairs. Under either repair those 10 are marked, with
  the guess right, and the other 10 are equal.
- Where truncation binds, at fp256, this repair keeps 2^-4.8 against
  2^-2.9, for no instruction. At fp128 VM1's keeps 0.8 bit more.
- At fp64 both are set by the reduction path, which neither changes:
  2^-1.9 and 2^-2.0.

**fp64's thin regions, and G = 44** (`g44.py`: 1,500 random arguments a
region, every lane against transcend.py under rne, 0 wrong, 0 marked;
the planners at G = 44 give exp K 7 D 12, expm1 K 8 D 13 and the log
family K 11 D 23):

| fp64 | G = 46 | G = 44 |
|---|---|---|
| exp, exp2, x next to (n +- 1/2) ln2/8 or /8 | 2^-5.4, 2^-5.5 | 2^-2.6, 2^-2.6 |
| expm1 near the 2^-k clamp; near n = 0 | 2^-2.94; 2^-4.6 | 2^-2.95; 2^-6.6 |
| log, log2 on x in [0.93, 0.945] (k = -1, C = 9) | 2^-3.1, 2^-2.1 | 2^-4.0, 2^-3.7 |
| log, log2 on x in [1.75, 1.9] | 2^-5.9, 2^-5.4 | 2^-7.1, 2^-7.2 |
| log1p on [15/256, 2^-4), x > 0 and x < 0 | 2^-1.9, 2^-2.3 | 2^-3.9, 2^-3.8 |
| log1p on [2^-4, 2^-3), x > 0 and x < 0 | 2^-2.4, 2^-2.3 | 2^-4.4, 2^-4.3 |
| instructions, rne: exp, exp2, expm1, log, log2, log1p | 181, 179, 175, 193, 187, 227 | 180, 178, 175, 186, 180, 220 |

At G = 46, larger samples of the two thin regions (`cancel.py`, 20,000
each): log1p on [-1/8, -15/256) 2^-1.81, log2 on [0.875, 0.9414) 2^-2.20.
`log1p_floor.py` (3,000 a region) splits log1p's error there by part.
For x > 0 on the band:
- y's rounding, 2^-3.0;
- the correction's rounding, 2^-3.9;
- its missing square term, 2^-4.0;
- the rest, 2^-2.6.
For x < 0 the rest, the cancelling sum, leads (2^-2.2).

Verifier-VM1's weighted sampler could not see the low word's terms: its
reduction-path log1p arguments were x = u - 1, exact, so u_l = 0. At
G = 44 every fp64 region measured keeps at least 2.6 bits. There the
exp family's planners take one degree off D, so the exp rows sit at the
two-bit target instead of above it.

### 3.4 How often a lane is marked

COMPUTED, then MEASURED.
- **The law.** A random argument's true value lies uniformly within a
  rounding cell. It is marked when within Bv of a boundary: one boundary
  an ulp under every attribute (midpoints for rne and rmm, grid points
  for the directed three). So P = 2 Bv/ulp, averaged over the binade:
  2^-G times 1/ln2 = 2^(0.53-G).
- **Measured,** with the bound inflated to 2^-(p+6), so that marks are
  common enough to count (`m1rate.py`; 2,000 uniform arguments, six
  functions, rne and rtz):

  | | exp | exp2 | expm1 | log | log2 | log1p |
  |---|---|---|---|---|---|---|
  | rne marked | 2.10% | 1.80% | 1.70% | 2.30% | 2.50% | 2.30% |
  | rtz marked | 2.60% | 1.90% | 2.80% | 2.40% | 2.05% | 2.45% |
  | predicted | 2.24% | 2.27% | 2.30% | 2.21% | 2.34% | 2.25% |

  With a count near 45, sigma is about 0.3%; every cell sits within two
  sigma. Every marked guess was right, and no unmarked lane was wrong.
  Verifier-VM1 ran the same at fp128 and fp256: 1.65% to 2.8% marked
  against 2.2% to 2.35% predicted, the worst cell 1.9 sigma.
- **At G = 46:** 2^-45.5, about 2.0 x 10^-14 a call. For example, 64
  lanes, 10 calls a step and 10^6 steps make 6.4 x 10^8 calls, and an
  expected 1.3 x 10^-5 marks a run. At G = 44, four times that.
- **Over the transcend pools** (MEASURED, 90 runs at fp64, fp128 and
  fp256): no random lane marked. The marks were the structured lanes of
  section 3.5, at most one a function, format and attribute: exp(+-2^-p)
  under every attribute, expm1(-2^-p) and log1p(2^-p) under rne and rmm,
  and log(1 + ulp) under the directed three. exp2 and log2 marked none.
- **Over 60,000 random fp64 lane-calls:** none, but for log's sampler,
  which draws 1 + c 2^-52 on purpose.

### 3.5 The structured families

Some arguments sit next to an exact case: x near c 2^-e for exp, expm1
and log1p near 0, or x near 1 + c ulp for log. Their true value then
lies closer to a rounding boundary than the bound can resolve. An
example is exp(2^-53) = 1 + 2^-53 + 2^-107 + ..., which is 2^-107 above
a midpoint. The routine marks them; a replay decides them.

MEASURED (`census.py`): 240 arguments +-c 2^-e, with c <= 16 and e from
p - 10 to p + 3, and 32 arguments 1 +- c ulp. fp64 is this study's run;
fp128 and fp256 are verifier-VM1's run of the same script.

| | fp64: rne, rmm | fp64: rtz, rdn, rup | fp128, fp256: rne, rmm | fp128, fp256: rtz, rdn, rup | guesses wrong |
|---|---|---|---|---|---|
| exp | 16 of 240 | 23 of 240 | 16 of 240 | 184 of 240 | 1 (rne) |
| expm1 | 4 | 9 | 16 | 127 | 1 at fp64 (rne) |
| log1p | 4 | 7 | 16 | 127 | 0 |
| log | 3 of 32 | 7 of 32 | 3 of 32 | 9 of 32 | 0 |
| exp2, log2 | 0 | 0 | 0 | 0 | 0 |

- **Which arguments mark.** Near 0, exp(x) = 1 + x + x^2/2 + .... Where
  1 + x is a rounding boundary, the true value sits x^2/2 from it, and
  the lane marks while that is inside the bound, about 2^-(p+G).
  - For x = c 2^-e that means 2e + 1 - 2 log2 c > p + G. So the
    exponents that mark run from about (p + G)/2 up to p: 3 of them at
    fp64, 33 at fp128 and 95 at fp256.
  - The census's 14 exponents cut that off. At fp256 the whole census
    window marks under the directed three.
- **Each is the centre of a window.** A neighbour x + j ulp(x) moves the
  true value by about j ulp(x), and it marks too while the sum stays
  inside the bound. The window is 2Bv wide.
  - MEASURED by verifier-VM1 at fp64: around x = 2^-53, 192 of 601
    neighbours mark under rne (j from -127 to 64); around 3 2^-53, 64;
    expm1 around -2^-53, 128; log1p around 2^-53, 128; log under rtz
    around 1, 7.
  - At fp256 a window holds about 2^190 arguments.
  - The replay is right either way: 0 wrong unmarked.
- exp2 and log2 have no such family: their ln2 factor breaks the
  structure.
- So the family is not a few dozen arguments a format: it grows with
  p - G.
  - Phase 2 can list the windows' centres (section 8).
  - LANGUAGE.md should state the rule: a lane is replayed where its true
    value lies within the bound of a rounding boundary, which next to an
    exact case holds for whole windows of arguments.
- Section 9, question 4, asks whether to keep these marks, or to pay for
  an exact path near 1 (exp's alone).

### 3.6 What the model found wrong in itself

MEASURED. Defects 1 to 7 were found in scratch before the first
version settled. Verifier-VM1's check of that version found defect 8.
Each is a plant for phase 2 (section 8).

1. **exp's Z** carried r_l through Y(r_h): an error of r_l r_h/2, about
   2^-64 at fp64. The pools passed it; the error against the bound found
   it (exp2 at 2^35 times the bound).
2. **ln2 in two words** in the log family's sum: k ln2 short by
   2^-(2p-2nk), up to 2^3 times the bound. Found by the same
   measurement.
3. **The measurement's own filter** dropped lanes above 2^10 times the
   bound as "screened". That hid defect 1 in exp until the filter became
   the main path's domain.
4. **A bound relative to Z** for exp's n = 0 lanes claimed 2^-152 where
   the double word around 1 carries 2^-106: exp(2^-53) was marked with
   a wrong guess. The bound became relative to V.
5. **log1p's 2^-k** was built for k = emax, giving a NaN at max_normal.
   The pools found it, and it is now clamped.
6. **exp2's exact test,** r' = 0 alone, took x = j/8 for an integer; it
   needs j = 0 too. The pools found it.
7. **fp32's three missing terms** (section 2.5): 2^12.7 times the bound,
   with the pools passing every version.
8. **log1p's r = x path past rho**, found by verifier-VM1. The path ran
   to |x| = 2^-4, while the polynomial was planned for
   |r| <= rho = 2^-4.08. At fp256 the truncation there is 2^0.93 times
   the bound.
   - VM1 built four fp256 lanes from it that came out wrong and
     unmarked, in 10 lane-attribute pairs. It held them three ways: the
     model, seq.py and mpmath, and again on amd-arc-box.
   - The pools hold no such argument, and the first placed set had no
     point on that path.
   - The threshold is now 15/256, under rho (2.3).

## 4. The specials and the flags

PROPOSED, and MEASURED equal to transcend.py, bits and flags, over the
pools at fp64, fp128 and fp256 under every attribute. The routine's
answer on each class follows. Rows are in the routine's order of
priority, highest first; "main" is sections 2.2 and 2.3.

**exp:**

| operand | result | flags |
|---|---|---|
| NaN | the canonical quiet NaN | invalid if signalling |
| +inf, -inf | +inf, +0 | none |
| +-0 | 1 | none (exact) |
| x >= the overflow screen | +inf (rne, rmm, rup); max_normal (rtz, rdn) | overflow, inexact |
| x <= the underflow screen | +0; the smallest subnormal under rup | underflow, inexact |
| |x| < 2^-(p+3) | 1 or its neighbour on x's side (main path, unmarked) | inexact |
| main | R 2^k, or the fixed grid's | inexact; + underflow where tiny after rounding; + overflow; + 0x80 where marked |

**exp2:** as exp, with the screens at x >= emax + 1 and x <= emin - p,
and integer x exact, with no flag, down to 2^(emin-man_w). The screen at
emin - p reproduces transcend.py's +0 under rmm for the exact tie
2^(emin-p) (question 5).

**expm1:**

| operand | result | flags |
|---|---|---|
| NaN | quiet NaN | invalid if signalling |
| +inf, -inf | +inf, -1 | none (-1 exact) |
| +-0 | the operand | none |
| x >= the overflow screen | as exp | overflow, inexact |
| x <= -(p+2) ln2 | -1 (rne, rmm, rdn); -(1 - 2^-p) (rtz, rup) | inexact |
| |x| < 2^-(p+2) | fma(x, x, x) under the attribute | inexact; + underflow where |x| < 2^emin, or x = -2^emin under rtz and rup |
| main | R 2^k | inexact; + overflow; + 0x80 |

**log and log2:**

| operand | result | flags |
|---|---|---|
| NaN | quiet NaN | invalid if signalling |
| +-0 | -inf | divideByZero |
| negative, -inf and -subnormal included | quiet NaN | invalid |
| +inf | +inf | none |
| 1 (log); 2^k (log2) | +0; k | none (exact) |
| main, subnormal x scaled by 2^p | R | inexact; + 0x80 |

**log1p:**

| operand | result | flags |
|---|---|---|
| NaN | quiet NaN | invalid if signalling |
| +-0 | the operand | none |
| -1 | -inf | divideByZero |
| below -1, -inf included | quiet NaN | invalid |
| +inf | +inf | none |
| |x| < 2^-(p+2) | fma(-x, x, x) under the attribute | inexact; + underflow where |x| < 2^emin, or x = +2^emin under rtz and rdn |
| main | R | inexact; + 0x80 |

**The flag word.** Its possible values are the set C4 proves for its
own, {0, invalid, divideByZero, inexact, overflow|inexact,
underflow|inexact}, together with inexact, overflow|inexact and
underflow|inexact each ORed with 0x80. It never has bits [6:5]. RAISE
reads [4:0] and [7], so it raises exactly the operation's IEEE flags and
marks where the test failed (SEQUENCER.md, R24). The tiny-argument
edges at +-2^emin are tininess after rounding under the attribute, as
transcend.py's witness rounding gives it. The pools hold
both signs of min_normal, max_subnormal and min_subnormal.

Verifier-VM1 MEASURED the words the fragments raise over 317 specials,
the pools and 6,000 random arguments, for all six functions under all
five attributes at fp64 and fp256. It saw only 0x0, 0x1, 0x2, 0x10,
0x14, 0x18 and 0x90, and never bits [6:5]. C4's `routines.flag_words`
cannot prove the set yet: its walk has no rule for the IOR that adds the
mark (section 6).

## 5. The cost

### 5.1 Measured

MEASURED (the fragment's instructions over the five attributes;
inlined, each call adds QUIET, ENDQUIET and RAISE, 3 more):

| | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| exp | 413 (G 46), 382 (G 40), rne | 178-181 | 185-188 | 198-201 |
| exp2 | about 2x fp64 (ESTIMATE) | 176-179 | 183-186 | 196-199 |
| expm1 | about 2x (ESTIMATE) | 175-178 | 182-185 | 195-198 |
| log | about 1.8x (ESTIMATE) | 193 | 208 | 238 |
| log2 | about 1.8x (ESTIMATE) | 187 | 202 | 232 |
| log1p | about 1.8x (ESTIMATE) | 227-229 | 242-244 | 272-274 |
| bank words, a function | 72-73 (exp) | 63-77 | 71-92 | 84-122 |
| bank words, all six | | 140-142 | 163-165 | 206-208 |
| ... with C4's div and sqrt | | 158-160 | 181-183 | 224-226 |
| most values live | 34 (exp) | 22-24 (exp family), 14-18 (log) | same | same |
| scratch slots | 0 | 0 | 0 | 0 |

The repair of defect 8 added one bank word to log1p, its threshold
15/256, and no instruction.

By part, MEASURED, rne:
- exp at fp64 (181): classify 10, reduce 14, lookup 17, scale factors
  15, tail 6, head 53, Z 5, reconstruction 13, final 15, fixed grid 21,
  specials 12;
- log at fp64 (193): classify 7, reduce 19, lookup 18, tail 11, head 91,
  r Y 3, sum 22, final 10, specials 12;
- log1p adds 25 for its low word.

At fp256 the tails grow to 26 (exp) and 56 (log) FMAs, and nothing else
grows. SELECT is the commonest instruction after the arithmetic: 39 of
exp's 181.

### 5.2 Against the surveyor's estimates

READ (ROADMAP part 5; the round's survey, part M) against MEASURED:

| | surveyor | this design |
|---|---|---|
| table | 32 entries | 8 entries, read by a SELECT tree |
| bank constants, fp64 | about 100 | 63-77 a function; 140-142 for all six |
| instructions a call, fp64 | about 150 | 175-229 |
| instructions a call, fp256 | about 750 | 195-274 |
| fp32 | triple-word | triple-word: about twice fp64 |

The fp256 figure moves furthest because a double word is needed only in
the head, whose length is set by G and not by p (section 2.4).

### 5.3 The alternatives

MEASURED and COMPUTED (`alts.py`; exp under rne, built and counted):

**The table's size, read by a SELECT tree** (instructions, with the
lookup's share in brackets):

| N | 4 | 8 | 16 | 32 |
|---|---|---|---|---|
| fp64 | 181 [8] | 181 [17] | 189 [34] | 221 [67] |
| fp256 | 203 [8] | 201 [17] | 208 [34] | 238 [67] |

**The table read from a copy in each lane's scratch by LDX** (COMPUTED:
the tree's instructions replaced by two IADDs, two LDXs and one more):

| N | 4 | 8 | 16 | 32 |
|---|---|---|---|---|
| fp64 | 178 | 169 | 160 | 159 |
| fp256 | 200 | 189 | 179 | 176 |
| slots a lane | 8 | 16 | 32 | 64 |

So a scratch copy saves 12 to 25 instructions a call (7% to 12%). Its
costs:
- 2N slots a lane for each table: 64 for exp's and log's at N = 16,
  against sw's default depth of 256;
- 2N stores a segment to fill the copy;
- an LDX's time: about five units against an ALU instruction's one, at
  the census's prices;
- compiler work: cftc would need a fixed table region in the lane, which
  its layout, the call loop and certificate version 2's `source-shape`
  rule would all have to learn.
The SELECT tree at N = 8 needs none of that. Question 3.

**The guard G** (instructions; mark rate 2^(0.53-G) a call):

| G | 36 | 40 | 46 | 47 | 48 | 52 | 60 |
|---|---|---|---|---|---|---|---|
| fp64 exp, log | 172, 170 | 173, 178 | 181, 193 | 181, 194 | past the floor | past the floor | past the floor |
| fp128 exp, log | 179, 185 | 180, 192 | 188, 208 | 188, 208 | 195, 208 | 195, 216 | 203, 232 |
| fp256 exp, log | 193, 215 | 193, 223 | 201, 238 | 201, 238 | 208, 239 | 208, 246 | 216, 262 |
| rate a call | 2^-35.5 | 2^-39.5 | 2^-45.5 | 2^-46.5 | 2^-47.5 | 2^-51.5 | 2^-59.5 |

Each 6 bits of G cost about 8 instructions for exp and 15 for log. At
fp64 the double word's floor (10u^2 = 2^-102.7), with the planners' two
bits of slack, stops the exp family's G at 47. In the log family's
cancellation cells the floor reaches the result amplified (3.2). At
fp64, G = 46 already keeps less than two bits there, and G = 44 costs
180 instructions for exp and 186 for log (`g44.py`, 3.3). Question 1.

**augadd, once every image carries R21** (COMPUTED from the fragments'
error-free additions). augerr and augadd split a sum exactly in 2
instructions, against TwoSum's 6 and Fast2Sum's 3. The fragments use:

| | exp | exp2 | expm1 | log | log2 | log1p |
|---|---|---|---|---|---|---|
| TwoSum | 1 | 0 | 2 | 1 | 0 | 2 |
| Fast2Sum | 9 | 9 | 10 | 15 | 15 | 15 |
| instructions saved | 13 | 9 | 18 | 19 | 15 | 23 |

That is 5% to 10% of a call. augadd rounds ties toward zero where the
fragment's ADD rounds to even, so the split's words differ while their
sum stays exact. The answers do not change; the image does, which is why
revision 8's question 9 writes TwoSum until every image carries R21.

**An exact path for the structured families near 1** (ESTIMATE). Keep
1 + Z as three words where n = 0, and round once through round-to-odd:
about 12 more instructions on every call of exp and exp2. expm1's,
log1p's and log's families (section 3.5) are inherent to a double word
and would need triple words near 0 or 1. Question 4.

### 5.4 What it does to a step

COMPUTED:
- **Inlined:** about 180 to 280 instructions a call (fp64 to fp256, log1p
  the dearest), so 32,768 instructions hold roughly 110 to 180 calls a
  step before C4's call loop takes over. The loop needs nothing new: a
  unary routine loops as sqrt does (`python/cftc/callloop.py`).
- **Time:** at the survey's figures of 1.85 ns a lane-instruction at fp64
  and 7.4 ns at fp256 (part M, 2.7, READ), an exp call is about 0.33 us a
  lane at fp64 and 1.5 us at fp256. The card ran 2.2% to 5.8% slower than
  the compiler's model (VALIDATION.md, READ).
- **Registers:** 22-24 values live in the exp family, and 18 in log1p.
  C4's fragments keep 16 or fewer, and `routines.LIVE_MAX` asserts 16.
  cftc's allocator spills around a routine as around any value, so this
  costs spills, not correctness. Phase 2 can reorder the fragment
  (question 12).

## 6. The language and the compiler

PROPOSED, in C4's and L4's pattern.

**The nodes.** `exp(a)`, `expm1(a)`, `exp2(a)`, `log(a)`, `log1p(a)`,
`log2(a)`, each with an operand that is not a constant:
- each becomes a node of the step graph, named as transcend.py names the
  function;
- its golden function is `transcend.exp` and its siblings, which return
  bits and flags;
- the interpreter's operation table gains six entries
  (`python/cft_golden/lang/interp.py`, `_ops`);
- the renderers, the canonical and mathematical forms and the
  intention-out's checks take them as L4's div and sqrt were taken;
- the step graph's operation list (`lang/graph.py`, OPS) gains six
  names. As with div and sqrt, a graph without them writes the same
  bytes, so no committed graph moves;
- `transcendental` stops being raised for these six. It stays for the
  other names of the reserved set: sin, cos, pow and the rest wait for
  M2 to M4.

**What stays refused, and what folds:**
- **A function of a constant** folds exactly where the value is rational:
  exp(0) = 1, expm1(0) = 0, exp2(n) = 2^n for an integer n, log(1) = 0,
  log1p(0) = 0, log2(2^k) = k. That is the rule `sqrt` of a square
  already follows (LANGUAGE.md, "Constants").
- Every other function of a constant is `irrational-constant`, its
  sentence saying why. By Lindemann-Weierstrass, e to a nonzero rational
  is irrational, and so is log of a positive rational other than 1; 2 to
  a non-integer rational is irrational; log2 of a rational is rational
  only at a power of two. The log of a negative constant has no real
  value, as `sqrt(-4)` has none.
- **log(0), log2(0) and log1p(-1) of constants** are 754's divideByZero
  cases. Two readings exist, and question 8 asks which:
  - `constant-division-by-zero`, its sentence naming the pole. This
    widens the name: LANGUAGE.md defines it as a constant divided by a
    constant zero.
  - `constant-infinity`, the value being an infinity. This widens that
    name too: LANGUAGE.md defines it as inf or infinity written as a
    constant.
- **A folded value** is rounded once like any constant: exp2(2000) at
  fp64 is `constant-overflow`, exp2(-2000) `constant-rounds-to-zero`.
  Until question 5's fix lands, the folded exp2(emin - p) and the
  run-time operation differ under rmm. The fold goes through round_pack
  and gives the smallest subnormal; the operation gives +0.
- **h:** a function of a constant that changes with h's size is
  `h-nonlinear`, as `sqrt(h)` is.

**cftc** (`python/cftc`):
- `ir.ROUTINES` grows from {div, sqrt} to the eight, and so does
  `routines.ROUTINES`, the arity map. Each new node is carried by its
  fragment from the golden generator (section 10), bound to the node's
  operand, QUIET to ENDQUIET, then RAISE.
- The words are bank slots of the routine kind, deduplicated by bit
  pattern: section 5.1's union counts.
- `bank-capacity` already names the case where routine words take the
  bank past 512.
- The internal check holds each instance to its fragment, as for C4's.
  But C4's `routines.invariants` fails these fragments four ways today
  (MEASURED by verifier-VM1, all 90). The first version named two.
  - **The flag word's values.** `flag_words` answers None, unknown, on
    all 90: its walk knows SELECT, a word and IAND with 0, and the mark
    is an IOR. An IOR rule, the set of pairwise ORs, proves section 4's
    set on every fragment VM1 tried. Then the set gains the three
    marked combinations.
  - **The internal attributes** gain RDN, RUP and the program's
    attribute (section 2.1).
  - **Live values:** the exp family's 22 to 24, and log1p's 18
    (question 12).
  - **Two instructions read only the routine's input:** expm1's tiny
    path `fma(x, x, x)` and log1p's `neg(x)`. inline.py's argument for
    keeping a routine's instructions apart from the program's own nodes
    relies on every instruction reading a word or another of its values
    (`python/cftc/inline.py`, line 30). One instruction each restores
    that: x IXOR the sign word for the negation, and x IOR the zero word
    for one operand of the fma. Question 12.

**Targets** (READ: `python/cftc/targets.py`; the brief, for
`cftc.targets.provisional`):
- revision 7's u50-rev7, u50-rev7-quad, u50-round2 and open-core refuse
  an image with these routines `target-feature`, as they refuse C4's, for
  lack of FLAG_CONTROL (CAPS2[14]);
- the software targets compile them, and so do revision 8's provisional
  targets, which publish FLAG_CONTROL. Revision 8's quad is built without
  R21, and the routines need none.

**Versions.**
- **cftc's output VERSION goes from 4 to 5:** "bumped with any change to
  the bytes cftc writes for some source" (cftc's docstring). The record
  in `programs/systems/cftc-outputs.txt` gains version 5. No committed
  compiled file moves, since no committed source uses these functions.
- **The certificate corpus's sourced cases** carry `compiler cftc 4 sw`.
  So the corpus is made again exactly as e45a2f7 made it at version 4:
  `python certificates/corpus.py make --keep-version-1`, with only the
  compiler lines, hashes and manifest digests moving.
- **The language's version takes a minor step,** 1.0 to 1.1
  (`lang/version.py`): functions it refused only for not having them,
  and no accepted source changed. The six names are already reserved.
  Reserving a new name such as `ln2` would be a major step instead
  (question 6).
- **CONFORMANCE.md's profile does not move** for M1: no image's
  computation or acceptance changes, since the routines are programs of
  existing instructions. Question 5's transcend.py fix, if taken, is a
  major profile step of its own.

**The interpreter now needs mpmath** for these nodes, because
transcend.py's enclosures do. So:
- the `lang` stage and the golden auditor, handed a source that uses
  them, need it;
- an auditor without mpmath refuses `definition-unavailable`, as
  certificate version 2 already names (CERT-V2.md, 7.6);
- transcend.py's cap stays the loud backstop it is
  (`ZivEscalation`).
The tangent stage's exact dual numbers cannot evaluate a transcendental.
Its fourth check needs, for these nodes, what L4 gave the square root: a
central difference in high precision (question 10).

**A marked lane in the language's own checks.** lang_check and
tangent_check compare a compiled image with lang.run lane by lane.
A lane whose byte carries [7] is replayed there by the definition, and
the image's guess is compared only as a guess. The structured families
make such lanes reachable on purpose, and section 8 uses them.

## 7. The derivative rules

PROPOSED, in LANGUAGE.md's form ("The rules"; "The quotient and the
root"). Each rule reads r, the routine's own result, by name where it has
one and written again where it has none, and the compiler shares it.
L is ln 2 rounded once at the program's format under its attribute
(question 6).

| operation | its tangent | where a tangent is zero | where it is not differentiable |
|---|---|---|---|
| `exp(a)` | `r * da` | zero | - |
| `expm1(a)` | `fma(r, da, da)` | zero | - |
| `exp2(a)` | `(L * r) * da` | zero | - |
| `log(a)` | `da / a`, or `select(r == r, da / a, r)` (question 7) | zero | a = +-0: da/+-0, an infinity with divideByZero or a NaN with invalid, the quotient's convention; below zero r is a NaN (question 7) |
| `log2(a)` | `da / (L * a)` | zero | as log |
| `log1p(a)` | `da / (1 + a)` | zero | a = -1 as log at 0; below -1 as log below 0 |

**Rounding order.**
- **exp:** one rounding, the product.
- **expm1:** `fma(r, da, da)` is (1 + r) da in one rounding, the exact
  derivative e^a da with r = e^a - 1.
- **exp2:** two roundings. L r is primal-only, shared across vectors as
  the quotient's -r is, so each vector pays one MUL.
- **log:** one rounding, the division, the same correctly rounded
  division as the operation `/`.
- **log2:** two roundings. L a is shared.
- **log1p:** two roundings. 1 + a is shared, and rounded: it is the
  textbook's form, so the rule is the derivative of what the program
  computes, as L3 asks.

**Cost** (C4's figures, READ: a division routine is 177 to 191
instructions): each vector adds 1 instruction a call of exp, expm1 or
exp2, and one division routine a call of log, log2 or log1p. A
tangent-carrying system with one log in its right-hand side pays about
190 instructions a vector a call.

**How it is held:**
- the rule table is held to the code, each rule rendered on a
  one-operation system;
- the fourth check uses a central difference in high precision, since
  dual numbers in exact rationals have no exp;
- a committed compiled variational reference holds the bytes.
  PROPOSED: the Lotka-Volterra system in logarithmic variables,
  d/dt u = alpha - beta exp(v) and d/dt v = delta exp(u) - gamma, under
  rk4 with a tangent vector. Its invariant,
  H = delta e^u - gamma u + beta e^v - alpha v, gives the run an exact
  quantity to watch.
A rule rounded otherwise, such as `da * (1/a)` for `da / a`, must then
move that reference's bytes, as L4's plants moved Kepler's.

## 8. How it will be held

PROPOSED, for phase 2. Agents run the quick tests; the long runs are the
lead's (Logan's rule, verbatim in the brief).

1. **Each fragment on seq.py against transcend.py,** as a stand-alone
   program through `routines.program` and `routines.run`:
   - the stage's pools and the vector sets' at every format and
     attribute;
   - every unmarked lane must equal transcend.py in bits AND flag word;
   - every marked lane is replayed by transcend.py, and its guess
     counted.
   MEASURED as a probe. This study ran 35 configurations of 36, with
   the log family then at D = 24 and 71, one and three FMAs longer than
   now. Verifier-VM1 then ran all 90 on the first version's final
   fragments. log1p's 15 ran again after the repair. 0 mismatches in
   every one.
2. **The bound, against an independent reference.** For each format and
   function:
   - random arguments in the main path, with every bit of the argument
     random, so that log1p's u_l is not 0. Verifier-VM1's weighted
     sampler built log1p's arguments as x = u - 1, exact, and so never
     exercised the low word (3.3);
   - **each path's own worst points**, not the seed cells' alone:
     - every path's largest |r|, including log1p's r = x path at its
       end, |x| just under 15/256;
     - the places where the floor reaches the result amplified: the
       k = -1, C = 9 cells, and log1p's reduction path at its lower end
       with u_l at its largest;
     - expm1's first clamped k;
   - |V - mpmath| / Bv must stay under 1.
   This is the test that caught defects 1, 2 and 7. It caught 8 once
   its points were placed on the r = x path, and it is how the fp64
   margins of 3.3 were found. The pools passed all four defects, so it
   is not optional. mpmath at 4p + 200 bits is independent of
   transcend.py's decision procedure; MPFR, where the `mpfr` stage has
   it, is more so.
3. **The mark-rate law,** with the bound inflated by a fixed factor: the
   marked fraction within its sigma of 2^(0.53-G'). Every unmarked lane
   right, and the marked guesses right.
4. **The structured families** as a committed list: section 3.5's
   window centres at every format, by attribute, each with a few
   neighbours inside and outside its window. These are the lanes the
   mark exists for, and they test it.
5. **The constants** re-derived by the generator with a --check, as
   gen_divfull's are: tables, ln2's words, the coefficients and the
   screens, each against mpmath at 3,000 bits, and RECIP_SEED's cells
   for log's C.
6. **program.c bit for bit:** each fragment's program through
   `host/tests/seq_check.py`'s corpora. No new C is needed, since the
   routines are programs of existing instructions.
7. **The language's checks:**
   - the `lang-routines` stage's legs K and L with generated sources
     using the six functions, under every integrator, format and
     attribute, run on seq.py against lang.run, marked lanes replayed;
   - the tangent stage's rules (section 7);
   - the committed reference, and test_lang.py's refusal table.
8. **The card later,** on revision 8's images, once built: the lane-flags
   block and STATUS[6] on a structured argument, and the acceptance set
   with a routine case added.

**The plants,** each in a fresh copy and each red in a named case:

| plant | what must go red |
|---|---|
| a wrong table entry (T_3's high word off by one ulp) | the pools; the constants' --check |
| a reduction off by one ulp (C1) | the pools; the bound (2) |
| the last-bit test made too loose (Bv 2^-40 smaller) | the structured list (4): exp(2^-53) unmarked with a wrong guess under rne; the inflated law (3) |
| a flag left loud (an instruction of the body outside QUIET) | the language checks' FLAGS; cftc's internal check |
| the mark silenced (0x80 never ORed) | the structured list; the inflated law |
| defect 1, r_l through Y | the bound (2), and only it |
| defect 2, ln2 in two words | the bound (2) |
| defect 8, log1p's r = x path back out to 2^-4 | the bound (2) at fp256's r = x end; verifier-VM1's four lanes |
| exp2's exact test without j = 0 | the pools (x = 1/8 and the like) |
| the tiny gate removed | the pools under the directed attributes (subnormal x marked) |
| fp32's square term dropped | the bound at fp32 |

## 9. Questions for the lead, each with a recommendation

1. **G, the guard, at fp64, fp128 and fp256.** G = 46 gives a mark rate
   of 2^-45.5 a call; each 6 bits more costs about 8 instructions for
   exp and 15 for log (5.3). There are two choices for fp64, both
   MEASURED (3.3):
   - **G = 46 everywhere,** the first version's choice. The bound holds
     wherever it was measured. At fp64 the thinnest margins are in the
     cancellation cells:
     - log1p, x from -1/8 to -15/256: 2^-1.8 (20,000 arguments);
     - log2, x from 0.875 to 0.94: 2^-2.2; verifier-VM1's 100,000
       weighted arguments gave log2 2^-2.5.
     There the planners' two-bit rule fails, and the coarse count of
     3.2 does not show the bound.
   - **G = 44 at fp64,** verifier-VM1's preference:
     - every fp64 region measured keeps at least 2.6 bits, and the
       coarse count shows the bound;
     - the mark rate is 2^-43.5 a call, four times 46's;
     - the planners take K = 11 for the log family and D = 12 for exp
       and exp2. That saves 7 instructions in each log routine and 1
       in exp and exp2.
   At fp128 and fp256 the cancellation moves nothing. The thinnest
   margin there is expm1's at its clamp, 2^-2.9 at every format (3.2),
   and the rest keep 2^-3.8 or more.
   Recommended: G = 44 at fp64, and 46 at fp128 and fp256. The rule
   that picks them is the planners' two bits, counted with A and with
   log1p's low word. A second G costs nothing: 2^-(p+G) is a bank word
   that differs by format anyway.
2. **fp32.** A double word caps G near 18, a rate of 2^-17.5, which is
   not rare. Triple words cost about twice fp64: exp takes 382
   instructions at G = 40 (2.5).
   - Verifier-VM1 MEASURED weighted arguments on amd-arc-box:
     - G = 40 holds with 2^-4.7 to spare, over 150,000;
     - G = 43 holds with 2^-2.1, over 60,000;
     - G = 46 FAILS: 2^+0.89 over 30,000, with 3,768 lanes above
       2^-1.5.
   - So G = 46 at fp32 needs the reduction's low sum as a double word
     (about 8 instructions, ESTIMATE, not built) and a new measurement.
   Recommended: triple-word at G = 40, a rate of 2^-39.5.
   - An exhaustive sweep of fp32's inputs would count the marks exactly.
     It cannot be this Python model: about 3 x 10^9 lane-calls on exp's
     main path, at about 3 ms each. It needs program.c or the card, in
     phase 2.
   - fp32's other five routines are not built, and their costs are
     estimates.
3. **The tables.** An eight-entry table read by a SELECT tree, in bank
   words, costs 12 to 25 instructions a call more than a copy in each
   lane's scratch read by LDX. The copy costs 2N slots a lane, a fill a
   segment and new compiler layout (5.3). Recommended: the SELECT tree,
   N = 8.
4. **The structured families** (3.5) mark and are replayed. They are
   windows, not points, and they grow with p - G: at fp128 and fp256,
   184 of the census's 240 exp arguments mark under the directed three,
   against 23 at fp64. Recommended: keep them.
   - List the windows' centres in phase 2's tests.
   - Have LANGUAGE.md state the rule, not "few bits": a lane is
     replayed where its true value lies within the bound of a rounding
     boundary, which next to an exact case holds for whole windows of
     arguments.
   - The exact path near 1 (about 12 instructions every call) is exp's
     alone, since exp2 has no family. It is the lever if a workload
     proves to hit the windows.
5. **transcend.py's exp2 at x = emin - p under rmm.** The exact value is
   the tie sigma/2 between 0 and the smallest subnormal sigma. 754's
   roundTiesToAway gives sigma; transcend.py gives +0, because every
   n < emin - man_w goes through `_round_underflowing`, a quarter of
   sigma. MEASURED at every format, one argument each: x = -150, -1075,
   -16495 and -262379, flags 0x18. test_exp2_past_the_ends asserts the
   +0 under every attribute.
   - It is the only such branch. pow, pown, powr, compound and rootn
     test `vexp < emin - man_w - 1`, which keeps the tie out
     (verifier-VM1, READ).
   - The routine reproduces whichever the golden model says, and the
     difference is one constant.
   Recommended: fix transcend.py, and transcend.c with it, to round the
   exact power at n = emin - p, as a parcel of its own before phase 2.
   - Under CONFORMANCE.md's rule it is a MAJOR profile step, since the
     vector pool holds the argument at every format.
   - What moves: the four rmm transcend vector sets and their lines in
     vectors/SHA256SUMS; profile.py's VERSION; CONFORMANCE.md's and
     VALIDATION.md's entries; the vendored copies sync.py holds;
     test_exp2_past_the_ends; and the certificate corpus's `profile`
     lines.
   - Until it lands, the language's folded exp2(-1075) and the run-time
     operation differ under rmm (section 6).
6. **ln 2 in exp2's and log2's tangent rules.** A constant is an exact
   rational, and ln 2 is not. Recommended: the rule's constant is the
   exact rational value of ln 2 correctly rounded once at the program's
   format under its attribute, which is transcend.log of 2. It goes in
   the graph's const table as that rational and prints in the canonical
   form as an exact hex literal, so it reads back. No new name, and the
   language's step stays minor. The alternative, a reserved name `ln2`
   (no committed source uses it, measured over the tree's 52 `.cftl`
   files), would be a major step.
7. **log's tangent where log is a NaN** (a < 0; log1p below -1).
   `da / a` gives a finite tangent there, the derivative of log|a|;
   `select(r == r, da / a, r)` gives the NaN, as sqrt's rule gives it
   through r (L4). Recommended: the select form. One compare is shared;
   one select a vector is negligible beside the division.
8. **Constants.** Recommended:
   - fold the six exact rational cases (section 6);
   - `irrational-constant` for every other function of a constant;
   - for log(0), log2(0) and log1p(-1) of constants, one of two
     readings, each widening a name LANGUAGE.md defines more narrowly:
     - `constant-division-by-zero` ("a constant divided by a constant
       zero"), its sentence naming the pole;
     - `constant-infinity` ("inf or infinity written as a constant").
     The first is recommended, since 754 calls these cases
     divideByZero and the operation raises that flag.
9. **cftc VERSION 5, the corpus remade as e45a2f7 did, and the language
   at 1.1.** Recommended, as C4 did.
10. **mpmath in the language's checks.** The interpreter needs it for
    these nodes, and the tangent stage's fourth check needs a central
    difference in high precision for them. Recommended: accept both. The
    golden stage already requires mpmath, and `definition-unavailable`
    already names an auditor without it.
11. **Where the generator lives.** Recommended: a new golden module,
    `python/cft_golden/mathlib.py`, beside routines.py. Its fragments
    are built, not read from a program as C4's are, and `routines.py`
    learns to hand them to cftc by name. Both `routines.ROUTINES`, the
    arity map, and `ir.ROUTINES` learn the six names.
12. **Live values, and C4's other invariants** (section 6). The exp
    family keeps 22 to 24 live and log1p 18, against C4's 16.
    Recommended: reorder in phase 2 and measure spills on a reference
    step. The exp family's count is structural, so expect to raise
    `routines.LIVE_MAX`; NREG is 32. For the other invariants that fail
    today:
    - give `flag_words` an IOR rule;
    - admit RDN, RUP and the program's attribute inside a routine;
    - spend one instruction each in expm1 and log1p, so that no
      instruction reads only the input.
    Relaxing inline.py's invariant instead is the alternative. It is not
    recommended: inline.py's argument for keeping a routine's
    instructions apart from the program's nodes rests on it.

## 10. What phase 2 builds, in order

PROPOSED, after the lead's review and Logan's answers:

1. **The golden generator** (`mathlib.py`): the six fragments at fp64,
   fp128 and fp256, and the triple-word fp32 variants, at every
   attribute, each at the G that question 1 decides for its format.
   - Every constant is derived and checked (--check).
   - Every fragment is held to its invariants: flag words, attributes,
     words, live values. Four of C4's invariants fail the model's
     fragments today, and section 6 says what each needs (question 12).
   - The planners count the cancellation factor A and log1p's low word
     (3.2).
   - The tests: section 8's items 1 to 5 and the plants, quick ones in
     the golden stage.
   - The exhaustive fp32 sweep, and the larger bound and rate samples,
     go to the lead for amd-arc-box.
2. **program.c parity:** the fragments' programs in seq_check's corpora.
3. **The language,** golden-first:
   - the six nodes, their golden functions and the interpreter;
   - the refusals and folds, and the renderers;
   - the L3 rules, with the central-difference check;
   - LANGUAGE.md's tables and test_lang*.py;
   - the language at 1.1.
4. **cftc:**
   - ROUTINES, the internal check's widened invariants, the targets'
     refusals, the call loop over unary routines;
   - VERSION 5, the outputs record, and the certificate corpus remade;
   - the Lotka-Volterra reference and its committed bytes.
5. **The stages' legs:** lang-routines and tangent, with marked lanes
   replayed; VERIFICATION.md's rows.
6. **The card,** after revision 8's images: STATUS[6] and the lane byte
   on a structured argument, and the acceptance set's routine case.

Question 5's transcend.py fix, if taken, goes first, as a parcel of its
own.

## 11. The model

Scratch made for this study, kept here as `ext-a/` keeps EXT-A's. It is
not the tree's code, and nothing imports it. Python with mpmath; run from
this directory with the repository's `python/` on the path, which
`m1core.py` arranges.

| file | what it is |
|---|---|
| `m1core.py` | the SSA builder in C4's Fragment shape, hash-consing and routines.simplify; the evaluator, through softfloat.compute as seq.py's ALU calls it |
| `m1const.py` | constants from exact rationals or mpmath at 3,000 bits, rounded once |
| `m1exp.py`, `m1log.py`, `m1exp32.py` | the routines (sections 2.2, 2.3, 2.5) |
| `m1harness.py` | the pools (transcend_check's, the vector sets', test_transcend's brute pool) and the comparison with transcend.py |
| `pools_run.py`, `pools_all.py`, `pools32.py` | the pools against transcend.py: one format (with a deadline), all three double-word formats, and the triple-word fp32 exp |
| `m1measure.py`, `worstcase.py`, `meas32.py` | the error against the bound: random and placed at each path's largest \|r\|, and fp32's at several G |
| `repair.py`, `log1p_floor.py`, `cancel.py`, `g44.py` | the revision's runs: log1p's two paths at their ends under the first model, VM1's repair and this one, with VM1's four lanes; log1p's reduction-path error by part; the cancellation cells at fp64; fp64 at G = 46 against G = 44 |
| `m1rate.py` | the mark-rate law with an inflated bound |
| `census.py` | the structured families |
| `alts.py`, `bound_terms.py`, `consts_report.py`, `rmax.py`, `words_union.py`, `final_counts.py` | the alternatives, the bound's terms, the screens, the reduction's max |r|, the bank's union, the final fragments' counts |
| `onseq.py` | the fragments as programs on seq.py through routines.run |
| `*.out.txt` | each run's output as captured, named for its script; the outputs from before a design change say which version they measured. `-first` marks a run of the first version, kept beside its revised run |

The runs and their loads are in the round's ledger,
`Data/runs/2026-10-02-step6-round/ledger/M1.md`.
