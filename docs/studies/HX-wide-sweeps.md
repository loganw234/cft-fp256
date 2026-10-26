# Study HX: exhaustive-type sweeps at fp64, fp128 and fp256

STATUS: a design study, 2026-10-26. Parcel HX of the math library round, written while M2 is on hold.
**Nothing here is built.** No soak mode, catalog entry, driver rule or report line changed; the card ran one
probe of about 100 seconds, which the lead ran (section 5.1). This file, the scratch under `docs/studies/hx/`,
its row in docs/README.md (with the index's counts and docs/VERIFICATION.md's count of indexed documents, which
the docs check holds) and one VALIDATION entry are the only changes the study made.

**Logan, verbatim, 2026-10-26 about 07:30:** "Would we be able to run the same sweep on higher precision to
gain anything? Obviously it wouldnt be an exhaustive sweep as the fp32 was capable of, but could we sweep the
same and compare against the fp32 to test? Mostly just looking for more of the exhaustive type work without
having to commit to the multi year runs". **Later that morning:** "Go ahead with the study, hold off on M2 for
now".

docs/studies/SWP-A-coverage.md is this study's nearest model and its vocabulary: the levels **L1** (exhaustive
over a stated space), **hard** (constructed cases at a rounding boundary) and **L2** (class level, PLAUSIBLE),
and Logan's answers to its questions (Q7: "Class level and hard case to begin, others are long term goals";
Q8: the host FPU and libm stay the sweep's oracle; Q4: coverage "Per tree"), READ in docs/VALIDATION.md.

Every figure is one of five kinds, and says which:
- **READ**: from this tree at 78d5b526 or from the round's records, with the file named;
- **MEASURED**: from a run of one of the study's instruments (section 10), with its output kept beside it;
  the desktop's runs were niced, one at a time, in WSL cft2204 unless named otherwise, and the card's one run
  was the lead's, on amd-arc-box, of the probe this study wrote;
- **COMPUTED**: arithmetic on read or measured numbers, shown or done by a named script;
- **ESTIMATE**: mine, with its basis;
- **BELIEVED**: mine, unverified.

## Contents

0. In brief
1. The question, and why now
2. What the tile computes at the wide formats, and what has been swept
3. The spaces
4. The oracles
5. The cost
6. The build
7. The plan
8. Questions for Logan, each with a recommendation
9. What this study does not establish
10. The instruments and their runs

---

## 0. In brief

**Yes: there is exhaustive-type work at the wide formats that finishes in about a week of nights.** Its first phase
is about 133 tile-hours (COMPUTED from rates the card MEASURED today), against 311 tile-hours the sweep gives
exhaustive items in two weeks (COMPUTED from nightly-1024's record). It matters more than its size: the tile's two
fp128 lanes and its fp256 unit are their own instances of the FMA pipe (READ, docs/ARCHITECTURE.md), and none of
the 155.9 billion encodings swept so far reached them (2).

**The lead's four hypotheses:**
1. **The ladder: AMENDED.** By exhaustion at toy precisions, with exact arithmetic, the narrowed wide result equals
   the narrow one for the product and quotient from p' = 2p, the sum from 2p + 1 and the square root from 2p + 2,
   under all five attributes, the subnormal and overflow ranges included; one bit less fails under RNE and RMM,
   while the directed attributes hold at every width (MEASURED, `hx_ladder.py`). At p = 24 on python/hardcases.py's
   hardest cases the same thresholds hold exactly: the quotient
   fails at 47 and holds from 48, the root fails at 49 and holds from 50 (MEASURED). Every IEEE rung clears them.
   The flags need the right rule: the narrowing's own flags suffice for quotient and root; the sum needs the wide
   call's inexact OR-ed in (4.1). **It fails for the FMA** under RNE and RMM at every rung, fp256 included (one
   fp32 triple shows it, MEASURED), and for integer-to-float through a format narrower than the integer. For
   roundToIntegral and scaleB it is an exact identity, so a full-precision check for free. **Its power is as the
   lead said, sharper**: an error of 2^j wide ulps is seen with probability 2^(j - (p' - p)) a case (MEASURED at toy
   size), so over all 2^32 inputs it sees an error only in the top 56 bits of fp128's 113 or fp256's 237. The other
   limit is half right: the slice's inputs have zero low bits, but the programs' roots and quotients come out
   full-width (105 to 113 significant bits at fp128, 218 to 237 at fp256, MEASURED), so the wide multiplier and
   rounding unit are exercised; what the zero bits starve is the input's own path and, for division, the short
   remainder that decides the rounding, which the windows and the hard cases cover.
2. **Full precision: HELD.** For division and square root the card is the bottleneck by five to twelve times: 1.06 to
   1.98 us an element a tile (MEASURED) against about 0.09 to 0.39 us of MPFR on a box core (ESTIMATE from READ
   figures), so one core a tile carries the oracle. For the FMA, mul and add MPFR is the bottleneck, at 1 to 3.3 box
   cores a tile (ESTIMATE): it needs threads of its own, a phase-2 build item. Cheap independent checks exist:
   exact identities, the constructions themselves, and a residual check for root and quotient (MEASURED in Python);
   gcc's `__float128` agrees with MPFR for add, sub, mul, div and fma but its `sqrtq` is wrong in a quarter of RNE
   cases on this desktop's libquadmath (MEASURED), so it is an oracle only per tested build.
3. **Other finite spaces: HELD, with one addition.** Hard cases at fp128 and fp256 cost minutes an attribute and
   the tree's generator builds and verifies them at p = 113 (every family) and p = 237 (every family but F1, whose
   64-bit draw stops at p = 132; MEASURED); class items cost minutes; windows hours. Hard cases are the most valuable
   per card-hour (BELIEVED, ranked in 5.4). Added: the fp32 slice exercises only exact paths for product, near sums,
   rint's integer and scaleB; and **the FMA, add and mul have no sweep item at any format** (3.6).
4. **The cost: AMENDED by measurement.** A 2^32 item takes 1.26 to 1.32 tile-hours an attribute at fp128 and 2.2
   to 2.4 at fp256 for division and root (COMPUTED from the probe's MEASURED rates); a quad runs four. Phase 1 is
   about a week with its weekend, not "a few weeks".

**The card's rates at the wide formats were not in any record, so the study wrote a probe and the lead ran it**
(5.1): division 1.586, 0.947 and 0.542 M elements a second a tile at fp64, fp128 and fp256; square root 1.458, 0.901
and 0.505; every result checked against the software backend; four tiles at once run at four tiles' rate.

**Recommended** (7, 8): phase 1 as ranked, the hard cases first; MPFR as the wide formats' oracle with the native
narrow result as a free second check; parcels HXa (the wide division and root soak) and HXc (the catalog) before M2
resumes; the FMA's items in phase 2. Nine questions for Logan are in section 8.

---

## 1. The question, and why now

On 2026-10-25 at 17:16 the nightly sweep covered the last of its 71 exhaustive items: 155,886,212,924
encodings or indices, 0 disagreements in 1,870 slices, 78,575,849,296 of them tile items and 77,310,363,628
host items (READ, the brief; nightly-1024's `status.txt` shows the same totals and "exhaustive ... (100.000 %)").
The catalog's other 54 items are random, and since 2026-10-26 the nights run them with new draws. Logan asks
for more work of the exhaustive kind: finite, finishing, each pass a claim, at the wider formats.

The lead's answer was four hypotheses (the brief, "What the lead answered him"). This study settles each:
1. **the ladder**: the 2^32 fp32 values, widened exactly, through the fp64, fp128 and fp256 operations, with
   the proven fp32 results as a free oracle by the classical double-rounding condition (p' >= 2p + 2);
2. **the stronger form**: each wide result checked at full precision, by the CPU's double at fp64 and by MPFR
   at fp128 and fp256;
3. **other finite spaces**: low-bit windows, hard cases and class-level items at fp128 and fp256, hard cases
   guessed the most valuable per card-hour;
4. **the cost**: a campaign of a few dozen items as "a few weeks of nights" (ESTIMATE, unchecked).

## 2. What the tile computes at the wide formats, and what has been swept

**The hardware is separate at each rung.** The tile's one ALU array is "eight fp32 / four fp64 / two fp128
lanes or one fp256 unit, each lane the recipe above (`cft_opmux` into `cft_fpfma_pipe`, with `cft_simpleops`
and `cft_seedop` merged through the pipe's bypass sideband)", the fp32, fp64 and fp128 banks and the fp256 unit
drawn side by side (READ, docs/ARCHITECTURE.md; `rtl/cft_lanes.sv` generates `g_bank128` as its own lanes). The
fractured multiplier that would serve every rung with one array (`cft_mulfrac`, ARCHITECTURE's "The fractured
array") is used only under `FUSE_MUL`, which is off by default (READ, `rtl/cft_krnl.sv`), and even there "the
alignment/normalise/round tail is NOT shared": "each lane keeps its own tail" (READ). The U50's images are built
with the default generics but revision 8's own (READ, docs/BITSTREAM-BUILDS.md; BELIEVED that none sets
`FUSE_MUL`). So the two fp128 lanes and the fp256 unit have their own alignment shifter, per-64 leading-zero
count, rounding increment and exponent logic, and their own multiplier columns (24-bit chunks, `MUL_PASSES=1`),
and **none of the 155.9 billion swept encodings reached them** (COMPUTED from the catalog,
`hw/card_stress_lib.py`'s `sweep_items()`: every tile item is an fp32 or fp64 operation). What the card has run at
fp128 and fp256 is the battery: the selftest's replay of
the published vectors (1,072,415 cases a replay at all four formats, 536,765 of them transcendental; READ,
docs/DETERMINISM.md and docs/COMPATIBILITY.md), the device-test matrices, the acceptance programs, the hard
workloads at fp256 (READ, docs/VALIDATION.md, 2026-10-01) and the probe of this study.

The operations, from CAPABILITIES.md's marks and the library's split (READ: CAPABILITIES.md; `host/src/clause5.c`
and `host/src/divsqrt.c` headers; `OP_REACH` in `hw/card_stress_lib.py`):

| operation | at fp64, fp128, fp256 | reach | swept today |
|---|---|---|---|
| FMA, add, sub, mul | one opcode each (add and mul steered through the FMA) | tile | **at no format** |
| division, square root | composed: one sequencer program a call (the program route), host prep and round_pack | tile | fp32 sqrt (L1), fp32 div (random, hard), fp64 (random, hard); **never fp128, fp256** |
| roundToIntegral, scaleB | composed: `cft_run` passes (rint 4 a call; scaleB 0 to 3 multiplies) | tile | fp32 (L1), fp64 (random, L2 class); **never fp128, fp256** |
| signaling comparisons | composed: the quiet predicate on the tile, invalid on the host | tile | no |
| abs, neg, copysign, select, compares, min/max, the two seeds | opcodes, the bypass path | tile | no; `cft_simpleops` is proved bit-exact over its inputs except three opcodes (READ, SWP-A 3.5) |
| sum, dot, maxall | the reduction tree | tile | no |
| conversions, integer conversions, remainder, logB, next, class, totalOrder, formatOf narrowing | library: bit surgery and `round_pack` on the host | host | fp32 and fp64 only |
| the 39 transcendentals | host, six of them also tile routines | host / tile | out of this study's scope (8, question 9) |

So the wide campaign's tile items are division, square root, roundToIntegral and scaleB at fp128 and fp256, and
the FMA family at every format; its host items are the wide conversions.

---

## 3. The spaces

Each space below is given with its size, what a pass proves at SWP-A's levels, what it misses, and what of the
datapath it exercises that the covered items (all fp32 and fp64) did not. Sizes are indices; "k" is the cases an
index makes; card time is section 5's.

### 3.1 The fp32 slice: every fp32 value, widened exactly

Widening is exact (CAPABILITIES.md: "widening exact and silent"), so the slice is 2^32 = 4,294,967,296 inputs at
every rung, and it is a space only for the **unary** operations. A binary operation's slice is 2^64 pairs, out
of reach (SWP-A 6.1: 3 x 10^5 quad-years for fp32 division); what a 2^32 space can hold of one is a partner
fixed or derived from the input. Operation by operation:

- **Square root (L1 over the slice).** The one slice operation whose wide result is never exact except on
  squares, so every rounding the program makes is real. The program refines a seed of 8.5 bits ("rel. error <
  2^-8.5 proven exhaustively", READ CAPABILITIES.md) by Newton steps that are FMAs at the format's precision, four
  at fp128 and five at fp256 against three at fp64 (READ, `_NEWTON` in `python/cft_golden/sequences.py` and the
  cores in `seqprogs.py`). Run on 400 fp32 values widened (MEASURED, `hx_iterates.py`, the tree's own program
  route in the golden model), the root it deposits carries 105 to 113 significant bits at fp128 (median 113) and
  228 to 237 at fp256 (median 236), and the exact residual r 92 to 113 and 219 to 237, from inputs of at most 24.
  **So the lead's second limit is half right** (hypothesis 1, amended): the inputs' low 89 (fp128) or 213
  (fp256) significand bits are zero, but the multiplier's low columns, the alignment and the rounding increment
  are exercised by the program's own full-width values. What the zero bits do starve is the input's own path: the
  prep's centring of a wide operand and every input pattern below the top 24 bits. Exponents: fp32's 277 binades
  (the 23 subnormal binades among them) become wide NORMAL numbers, so no wide subnormal input occurs, and a
  root is never subnormal or overflowing at any rung. **New against the covered items:** the fp128 lanes' and the
  fp256 unit's whole square-root program, under all five attributes, on every cell of the seed table (its index
  is the top 9 fraction bits and the exponent's parity: READ, `SEED_INDEX_BITS` in `softfloat.py`).
- **Reciprocal, 1/x (L1 over the slice).** The division program's 2^32 space: the quotient it deposits is
  full-width (98 to 113 significant bits at fp128, 218 to 237 at fp256; MEASURED, `hx_iterates.py`), but its exact
  remainder 1 - q x is as short as the divisor (1 to 24 bits), so for division the slice DOES starve the
  remainder and the midpoint probe that decide the rounding. Exact quotients occur wherever x is a power of two
  (2 x 277 of them). |1/x| lies in [2^-128, 2^149], so neither a wide subnormal nor an overflow occurs. Other
  fixed partners (x/3, x/(1 - 2^-24), 3/x) are slices of the same kind; 1/x is the one that needs no choice.
- **Product and sum of slice values: exact paths only.** A product of two fp32 values has at most 48
  significant bits, under fp64's 53, so at every wide rung it is exact; a sum is exact whenever the gap between
  the operands' leading exponents is at most p' - 25 (28, 88 and 212 binades, a carry included; fp32's leading
  exponents span -149 to 127, a gap of up to 276) (COMPUTED from the widths). An exact result never sets the
  sticky bit or increments, so **a slice of products or of near sums exercises only the exact path of the wide
  rounding unit**, and its oracle is the exact value itself. The square slice x * x costs 4 tile-minutes an
  attribute at fp128 (COMPUTED, 2^32 at the MEASURED 17.7 M/s): cheap, and of little value. An FMA of slice
  values is exact at a rung unless its terms span more than p' bits, which they can (a b's last bit reaches
  2^-298 and c's first 2^127), and there the ladder fails (4.1).
- **roundToIntegral (L1 over the slice): an exact identity.** The integer result of an fp32 x has at most 24 bits,
  so the wide result IS the fp32 result, widened: the native fp32 rint is a full-precision oracle (MEASURED by
  exhaustion at p = 4, `hx_ladder.py` part B: 1,215 input-attribute pairs, every result narrows exactly with no
  flag). It is worth more than it looks: the composed rint computes (x + m) - m with m = copysign(2^(p' - 1), x)
  under the caller's attribute (READ, `host/src/clause5.c`: "The magic constant C = 2^(p-1): the float whose ulp
  is 1"), so the wide ADDER rounds at the integer position for every non-integral x, with real guard and sticky
  bits.
- **scaleB with the directed exponents: exact, and nothing more.** Every fp32 value times 2^n for the 17 directed
  n stays inside the wide range, so the multiply is exact; the wide strips (the subnormal range, overflow) are
  never reached. The class items of 3.5 reach them; this slice adds nothing.
- **Conversions, logB, next, class, totalOrder (host).** Widening is a copy of fields and narrowing a widened value
  is the identity; the host items gain nothing from the slice.

**What any slice item misses** (all of them): inputs with nonzero low bits; the wide exponent range beyond fp32's
(2^-149 to 2^128 against fp128's 2^-16494 to 2^16384); wide subnormal and overflow results; and, for the
ladder's oracle, everything below the top bits of the wide result (4.1).

### 3.2 The fp64 slice at fp128 and fp256

Whole, 2^64 inputs: at the MEASURED fp128 square-root rate of 0.901 M/s a tile, 6.5 x 10^5 tile-years an
attribute (COMPUTED). Two sub-slices are worth their time; a third is not.

- **The fp64 hard cases, widened (hard).** div64-hard's 289,685,696 indices (READ, `HARD_SPACE`) and sqrt64-hard's
  4,456,448, run through fp128 and fp256 division and square root. Their exact results lie at the least distance
  an fp64 operand pair allows from an fp64 rounding boundary, so the ladder's narrowing to fp64 works at its
  thinnest margin there (4.1: at p = 24 the same construction fails the ladder one bit below the condition and
  passes from it), and MPFR checks the full width. Operands with 53-bit significands also reach further down the
  wide significand than fp32's 24 (53 of fp128's 113 bits; the low 60 are still zero). 1.5 tile-hours at fp128 and
  2.7 at fp256 for five attributes (COMPUTED, section 5).
- **The fp64 values with the low 32 fraction bits zero (L1, a stated 2^32 space).** The sign, the whole 11-bit
  exponent field (zeros and subnormals, normals, infinities and NaNs) and the top 20 fraction bits: 21-bit
  significands over fp64's 2,098 binades against fp32's 277 (COMPUTED), fp64's subnormals included (as wide
  normals). Through fp128 or fp256 square root and reciprocal it is the fp32 slice's statement over fp64's
  exponent range. Phase 2 (section 7).
- **Random fp64 operands at the wide formats** are a sampler, not this study's kind.

### 3.3 Low-bit windows

A window fixes the sign, the exponent and the high significand bits H and sweeps all 2^32 patterns L of the low
32: {H 2^32 + L}. **A pass proves L1 over the window.** It is the only space here whose INPUTS vary in the low half
of the wide significand: the operand's lowest 24-bit multiplier chunk column and 8 bits of the next (the U50's
multiplier is 24-bit chunk columns, `MUL_PASSES=1`; READ docs/ARCHITECTURE.md), the carries out of them, the
sticky over the low bits, the residual's exact cancellation against a full-width input, and the guard's
dependence on the input's last bits. It misses every pattern above bit 32 but the H chosen, so H is chosen for
carries and boundaries (BELIEVED, a judgement): all ones (1.111...1, a root or reciprocal next to a binade's top),
all zeros (1.000...0, next to a power of two), alternating (1.0101...), and one keyed random H; for the square root
under both exponent parities. 2.5 to 4.7 tile-hours a window for two attributes (COMPUTED, section 5).

### 3.4 Hard cases at fp128 and fp256

python/hardcases.py's families are written in terms of p: a new `Space` at p = 113 or 237 with the fp64 modes'
segment sizes gives (MEASURED, `hx_spaces.py` S2):

| space | indices | segments |
|---|---|---|
| div64-hard (as built, for scale) | 289,685,696 | F3a 212, F3b 16,364, F2 262,144, F1 4,194,304, F0A and F0D 8,388,608 each, F0K 268,435,456 |
| div128-hard | 289,931,696 | F3a 452, F3b 262,124, the rest as at fp64 |
| div256-hard | 293,864,352 | F3a 948, F3b 4,194,284, the rest as at fp64 |
| sqrt128-hard, sqrt256-hard | 4,456,448 each | S1 262,144, S0 4,194,304 |

A sample of every segment (all of the small ones, 300 of each large one) was built and **verified exactly** by
`hardcases.verify`, the module's builder-independent check, at both precisions (MEASURED: 2,100 indices at fp128,
7,392 cases, 12.0% of the sampled slots skipped; 1,800 at fp256, 6,212 cases, 13.7%; 600 a square-root space,
29.7% and 31.2% skipped, S1 never and S0 about three in five, as the fp64 space's S0 does: 2,710,696 of its
4,456,448 slots are skipped, READ `HARD_WHOLE`). **Every space was built with the tree's generator as it is**
(new `Space` objects from its own constructor, registered in the process's copy of its table, nothing in the
module changed), **except one family at fp256** (MEASURED): `build_f1` draws its odd parts from one 64-bit mix,
`mix64(...) >> (64 - (h - 1))` with h = (p - 1) // 2, which is a negative shift for p > 132 (`ValueError: negative
shift count` at p = 237; READ python/hardcases.py). F1 at p = 237 was therefore not built and not worked around:
its sample is absent from the 1,800 indices above, and its 4,194,304 indices are counted in the space's size as the
fp64 layout gives them. That is outside the module's stated domain (division at p = 24 and 53, square root at
53), so it is a build item (section 6), not a defect: the odd parts drawn from enough 64-bit words for p, and the
module refusing an unsupported p by name instead of failing on a shift. The F0 builder alone takes about 3.5 us
an index at both precisions in Python (MEASURED: 3.2 to 3.6 over two runs).

**What a pass proves: the hard level.** The quotient or root is at the least distance its operands allow from a
midpoint or a representable number (F0, S0), exact (F1), a tie in a subnormal strip (F3a: 113 and 237 strips
deep), a power of two across the whole wide exponent range (F3b, every strip and the overflow strip), or next
to 1 (F2, S1). **It exercises what no other space here does:** the program's finish and guard decision at the
boundary, and, through F3b and F3a, the wide format's own subnormal strips and overflow for division. It misses
the bulk: a defect away from the boundaries is found only by volume. The case for it per card-hour is SWP-A's
(4.2): a planted division with 40 guard bits failed on 25.5% of constructed fp64 pairs and on none of 272,007
sampler draws (READ).

### 3.5 Class level at fp128 and fp256

python/c5_class_enum.py's enumerators take the source format as a parameter; at the wide formats they give
(MEASURED, `hx_spaces.py` S1, whose check reproduces the three built fp64 spaces' sizes):

| space | reach | indices | k (a case a lane or target) | cases an attribute |
|---|---|---|---|---|
| rint, fp128 | tile | 137,344 | 2 | 274,688 |
| rint, fp256 | tile | 537,600 | 1 | 537,600 |
| scaleB, fp128 | tile | 317,448 | 2 | 634,896 |
| scaleB, fp256 | tile | 1,370,952 | 1 | 1,370,952 |
| convertFormat fp128 -> fp64 | host | 1,979,424 | 1 | 1,979,424 |
| convertFormat fp256 -> fp128 | host | 63,208,320 | 1 | 63,208,320 |
| fp128 -> 64-bit integers | host | 91,872 | 4 | 367,488 |
| fp256 -> 64-bit integers | host | 205,440 | 4 | 821,760 |
| 64-bit integers -> fp128, -> fp256 | host | 50,923 each | 1 | 50,923 |

(k for the wide tile modes is taken here as the format's lanes, 2 and 1 (READ, docs/ARCHITECTURE.md), where the
built fp64 modes' is 4: each operand is run in each lane, as `c5_class_enum.py`'s docstring explains.) **A pass
proves L2, PLAUSIBLE**, resting on the structural
assumption SWP-A 4.3 states. **New against the covered items:** the wide adder's rounding at every integer
position (rint), with walking ones over the kept and dropped bits; and **scaleB's 114 and 238 subnormal strips and
the overflow block, the only tile items in this study that reach the wide formats' subnormal range for a
multiply.** The narrowing conversion fp256 -> fp128 is large (fp128's exponents and subnormal strips make 32,882
structural positions, and 39 witnesses) and host code: the host pool's.

### 3.6 Better structure

- **Exponent boundaries and both edges** are F3b's (division) and scaleB's class strips and blocks; a square root
  never reaches either edge.
- **Carry chains:** the all-ones windows (3.3), S1's roots next to 1 and 4, and F2's divisors 1 +- k ulp.
- **The attribute's rounding boundaries:** F0's two targets (a midpoint, for the nearest attributes; a
  representable number, for the directed ones and inexact) and S0's midpoints; every hard and class item runs
  all five attributes, RMM included, since MPFR answers RMM (4.2) where the native oracle could not.
- **The FMA's own structure**: the alignment shift of c against a b, the cancellation depth, the rounding
  position after normalisation, signed zeros of an exact cancellation. No sweep item covers the FMA at ANY
  format; the published vectors' generator aims at most of these (an alignment sweep of c across 2p + 8 either
  side of the product, near-total cancellation, signed zeros and exact ties) at all four formats, and the selftest
  replays them on the card (READ, SWP-A 3.2). A class-level FMA enumeration over (shift, effective
  operation, cancellation depth, dropped class, sign, walking one) would be about 6 x 10^5 cases an attribute at
  fp128 and 2.7 x 10^6 at fp256 (ESTIMATE: 3p shifts x 2 x 4 x 2 x (4 + p)); it needs a new generator and an
  oracle off the card's critical path (4.2), so it is phase 2.
- **The tile's other operations at the wide formats** round nothing: abs, negate, copySign, select, the quiet
  compares and min/max take the bypass path, and `cft_simpleops` is proved bit-exact to its frozen reference
  over all 2^104 inputs but three opcodes (READ, SWP-A 3.5; at which width is not read here); the signaling
  compares are the quiet predicate plus the host's invalid; the two seeds sit inside every division and root
  program, whose fp32 slice reaches every cell. An fp32 slice through any of them is an exact identity at about
  4 tile-minutes an operation at fp128 and 6 to 7 at fp256 (ESTIMATE: the MEASURED elementwise rates of FMA, mul
  and add, 17 to 19 and 10 to 12 M/s), cheap and of little value; the reductions' tree is the contract's own shape,
  not a space (READ, `mpfr_check.c`'s
  header). None is in phase 1.

### 3.7 The spaces at a glance

| space | size an attribute | level | proves | misses | new datapath |
|---|---|---|---|---|---|
| fp32 slice, sqrt / recip | 2^32 | L1 (stated space) | every fp32 input, bits and flags | low input bits; wide range, strips | the wide lanes' whole division and root programs |
| fp32 slice, rint | 2^32 x 2 variants | L1, exact identity | the wide adder at the integer position | as above | the wide adder's rounding |
| fp32 slice, products and near sums | 2^32 (a derived partner) | L1, exact | the exact path only | every rounding | little |
| fp64 hard operands, widened | 2.9 x 10^8 (div), 4.5 x 10^6 (sqrt) | hard | the ladder at its thinnest; 53-bit inputs | the bulk | inputs with 53 significant bits |
| fp64, low 32 bits zero | 2^32 | L1 | 21-bit inputs over fp64's range | as the fp32 slice | fp64's exponent range |
| low-bit windows | 2^32 a window | L1 (the window) | every low pattern under H | every other H | the input's low half |
| hard, fp128 / fp256 | 2.9 x 10^8 (div), 4.5 x 10^6 (sqrt) | hard | the boundary decisions | the bulk | finish and guard; wide strips |
| class, fp128 / fp256 | 1.4 x 10^5 to 6.3 x 10^7 | L2, PLAUSIBLE | every class and walking one | patterns past the walk | rint's adder; scaleB's wide strips |

---

## 4. The oracles

### 4.1 The ladder, settled

**The check.** N has precision p, W precision p' > p and a wider exponent range. For each narrow input x (all
of them), compute op in W under attribute m, narrow the result to N under m, and compare with op in N under m:
the value, and the flags by one of three rules:
- **R1**, the narrowing conversion's own flags (with invalid and divideByZero, which the operand classes decide);
- **R2**, R1 OR the wide operation's inexact;
- **R3**, R2 with underflow recomputed: raised when the narrowed value is tiny after rounding at N and EITHER
  rounding was inexact. The narrowing alone cannot know that its exact input was itself a rounding.

**By exhaustion at toy precisions** (MEASURED, `hx_ladder.py`, 264 s; `hx_ladder.out`). N has four exponent
bits (emin -6, emax 7) and every encoding is an input: both zeros, every subnormal, every normal, both
infinities, a NaN; every pair for the binary operations (233,289 pairs at p = 5), every triple for the FMA
(571,787 at p = 3, emin -4, emax 4). W's range (emin -100, emax 100) holds every result of narrow inputs, as
every real rung's does (fp32's extreme product 2^-298 against fp64's emin -1022; COMPUTED). Exact arithmetic
only: integers, divmod and isqrt; one rounding routine for every format, after-rounding tininess, the 7.4
overflow table. The least p' from which the value ladder holds at every larger p' tried, under RNE and RMM:

| operation | p = 3 | p = 4 | p = 5 | p = 3..10 (sqrt) | the rule |
|---|---|---|---|---|---|
| product | 6 | 8 | 10 | | **2p** (the product is exact) |
| quotient | 6 | 8 | 10 | | **2p** |
| sum (every sign, so difference) | 7 | 9 | 11 | | **2p + 1** |
| square root | | | | 8, 10, 12, ..., 22 | **2p + 2**, and 2p + 1 fails |
| FMA | 12 (the toy range's span) | | | | **none short of exactness** |

Under RTZ, RDN and RUP the **value** holds at every p' tried for every operation, the FMA included: a directed
rounding to a finer grid and then to the coarser one in the same direction is the direct rounding (MEASURED, and
the reason is one line: RD_N(RD_W(x)) = RD_N(x) because RD_N(x) is itself a W number at or below x). These are
Figueroa's conditions for +, x, / and sqrt (BELIEVED: the literature's statement, recalled, not read here), and the
toy tables meet them exactly: at p' = 2p + 1 the square root fails on 7 inputs under RNE and 14 under RMM at every
p from 3 to 10, and on none at 2p + 2.

**At the real precision, on the hardest inputs** (MEASURED, part E): python/hardcases.py's closest-approach
quotients (F0, 8,999 cases at p = 24) and the inputs nearest the squares of midpoints (S0, 5,833 cases), through W:

| p' | 47 | 48 | 49 | 50 | 53 | 113 | 237 |
|---|---|---|---|---|---|---|---|
| quotient, mismatches (RNE + RMM) | 4,506 | 0 | 0 | 0 | 0 | 0 | 0 |
| square root | 3 | 3 | 3 | 0 | 0 | 0 | 0 |

So at p = 24 the quotient's condition is 2p and the root's 2p + 2, tight, and every IEEE rung clears it:
fp32 -> fp64 has 53 >= 50, fp64 -> fp128 113 >= 108, fp128 -> fp256 237 >= 228 (COMPUTED).

**The flags.** R3 holds wherever the value does at p' >= 2p + 2, for all four operations and all five attributes,
and for the directed attributes at every p' (MEASURED). R1 holds for the product, quotient and root at 2p + 2
(0 mismatches) and fails for the sum (10,228 to 35,268 mismatches over the five attributes at p = 3 to 5): a sum
that W rounds onto a narrow number is exact to the narrowing and inexact to N, so the soak must OR in the wide
call's inexact. Where the value holds, R2's only failures are on underflow below 2p (a directed product or
quotient that W rounds onto a narrow subnormal, BELIEVED the mechanism), and R3 repairs every one (MEASURED).
**At the IEEE rungs R1 suffices for the product, quotient and root**, so for them the narrowing's per-call flags
are the narrow operation's flags exactly.

**Where it fails, and why it cannot be repaired by width.**
- **FMA under RNE and RMM, at every rung** (MEASURED). a b can be an exact narrow midpoint and c smaller than half
  an ulp of W at a b; W then returns the midpoint and the narrowing breaks the tie the wrong way. One fp32
  triple does it at every rung: fma(97 x 2^40, 172961 x 2^36, 2^-149), where 97 x 172961 = 2^24 + 1; fp32 directly
  gives (2^24 + 2) 2^76, and through fp64, fp128 or fp256 the wide result is a b exactly and narrows to 2^100
  (`hx_fma_cex.py`). The directed attributes hold.
- **Integer -> float through a W narrower than the integer** (MEASURED, part B, the 32,767 integers of magnitude
  below 2^14, at p = 4): 240, 48 and 16 mismatches under each of RNE and RMM at p' = 10, 12 and 13, none at 14,
  none under the directed attributes. At the real formats: int64 -> fp32
  through fp64 fails (53 < 64); through fp128 it is exact.
- **roundToIntegral and scaleB** cannot fail: the wide result is exact (an integer of at most p bits; x 2^n inside
  W's range), so it narrows exactly (MEASURED, part B: 1,215 rint input-attribute pairs and 58,310 scaleB cases,
  n in [-24, 24]). For them the "ladder" is a full-precision identity: the wide result must EQUAL the narrow one.
- **A planted narrowing** that rounds RNE ties up is caught (2,976 mismatches on the sum at p = 4), and R1 on the
  sum loses inexact (21,924): the checks can fail (part D).

**What the ladder can and cannot detect.** A wrong wide result passes the narrowed comparison unless the error
moves it across a narrow rounding boundary. Injecting an error of 2^j wide ulps into every inexact wide result
(MEASURED, part C, at p' = 2p + 2) the fraction seen follows **2^(j - (p' - p))** within a factor of 1.9 for the
square root (p = 10) and below it for the quotient (p = 5, where the closest approach keeps every quotient more
than one wide ulp from a boundary, so j = 0 is never seen). At the real rungs against fp32 (COMPUTED from that law):

| rung | p' - p | a case sees a 2^j-ulp error | over all 2^32 inputs, an error on every case is seen if |
|---|---|---|---|
| fp64 | 29 | 2^(j - 29) | always: a last-bit error about 8 times |
| fp128 | 89 | 2^(j - 89) | j >= 57: only in the top 56 of 113 bits |
| fp256 | 213 | 2^(j - 213) | j >= 181: only in the top 56 of 237 bits |

So the lead's first limit holds and is sharper: over the whole slice the ladder sees a systematic error only if it
reaches the top 24 + 32 bits of the wide significand, and an error on a fraction f of the cases needs log2(1/f)
bits more. **What it can detect:** a wrong sign, exponent, special result or flag decided by the narrow value;
a large error in the significand; and at fp64, which is 29 bits from fp32, last-bit errors a few times over the
slice. **What it cannot:** any error in the low 57 bits of an fp128 result or the low 181 of an fp256 one; the
wide formats' own subnormal range, overflow and exponent range (narrow inputs never reach them: a product or
quotient of fp32 values lies between 2^-298 and 2^277 in magnitude); and the FMA under the nearest attributes.

### 4.2 MPFR at 113 and 237 bits

**The rates.** docs/BENCHMARKS.md's peer table is MPFR 4.2.2 on this desktop's core, emulating the binary format
by the manual's recipe ("mpfr+754"), ns an element (READ):

| | add | mul | fma | div | sqrt |
|---|---|---|---|---|---|
| fp128 | 21.6 | 21.1 | 62.9 | 32.5 | 38.4 |
| fp256 | 29.9 | 39.2 | 71.0 | 86.4 | 139.7 |

`host/tools/mpfr_check.c`, the oracle a soak would take, computes each case twice (the format's range, then
unbounded at the same precision, so that overflow and underflow "fall out of comparing the unbounded result against
the format's thresholds"), and builds RMM from a truncation to p + 1 bits (READ, its header): about twice the table
an attribute (ESTIMATE). amd-arc-box's Xeon core is slower than this desktop's, by about 1.4 on multiply (COMPUTED
from docs/studies/EXT-A-wide-ladder.md 1.5: the tile reads 5.5x the box's core and 4.0x this desktop's). gmpy2 on
the desktop (MEASURED, `hx_spaces.py` S3, MPFR 4.1.0, binary128 and binary256 contexts with subnormalize) gives
114 to 649 ns a call, the Python loop's overhead included: an upper bound only.

**Who bottlenecks** (COMPUTED: the card's MEASURED time an element a tile against twice the READ MPFR figure,
times 1.4 for the box):

| operation | card, ns an element a tile | MPFR on a box core, ESTIMATE | box cores a tile to keep up |
|---|---|---|---|
| fp128 div / sqrt | 1,056 / 1,110 | 91 / 108 | 0.09 / 0.10 |
| fp256 div / sqrt | 1,844 / 1,978 | 242 / 391 | 0.13 / 0.20 |
| fp128 fma / mul / add | 53 / 57 / 58 | 176 / 59 / 60 | 3.3 / 1.0 / 1.0 |
| fp256 fma / mul / add | 93 / 101 / 86 | 199 / 110 / 84 | 2.1 / 1.1 / 1.0 |

**For division and square root the card bottlenecks**: one core a tile carries the oracle with room, and the
soak's serial loop (generate, oracle, stage, run, compare: SWP-A 6.2) loses the oracle's 9 to 20% (ESTIMATE) unless
it runs the oracle beside the call. For the FMA, mul and add **the oracle bottlenecks**, at 1 to 3.3 cores a tile:
four tiles want 4 to 13 of the box's 36 threads, which the box has (the host pool takes 8; READ, nightly-1024's
report), but only if the oracle runs in threads of its own. That is a build item (section 6), needed for phase 2's
FMA items and not for phase 1.

### 4.3 The native CPU at fp64, and quadmath at fp128

At fp64 the CPU's double is the soaks' oracle already (SSE division and square root, correctly rounded under the
four native attributes, with flags; READ, `host/tools/divsqrt_soak.c`). For the fp32 slice at fp64 it is a
full-precision oracle at about a nanosecond (READ, BENCHMARKS: 1.08 ns div, 1.70 sqrt), with RMM for square root
riding the RNE oracle (no ties) and RMM for division left to MPFR.

At fp128 gcc's `__float128` is a second implementation of another lineage: add, mul and div at 15.4 to 21.9 ns,
square root 466 ns and fma 811 ns, bit-identical to libcft on the benchmark's 4,096 RNE elements in the sim
container, Ubuntu 24.04 and gcc 13.3 (READ, BENCHMARKS). **Measured here against MPFR** (`hx_quadmath.c`, WSL
cft2204, libquadmath 12.3.0 and gcc 11.4; 100,000 cases a cell, random normal operands and widened fp32 ones, each
of the four attributes set by fesetround): add, sub, mul and div (libgcc's soft-fp) and `fmaq` agree with MPFR in
all 40 cells, values and the inexact flag; **`sqrtq` is not correctly rounded under RNE**, 24,944 and 25,241 of
100,000 results one ulp off (the first: sqrtq(0x1.f8f202p-16) gives ...75c4p-8 where MPFR gives ...75c3p-8), and
agrees under RTZ, RDN and RUP (MEASURED; a planted one-bit flip in every 1,000th result is caught in all 48 cells).
So the oracle is a property of a build: this library's square root is not one, the sim container's agreed on its
4,096 elements, and the box's was not tested. A soak that used quadmath would pin the box's library and repeat this
test first (8, question 4). The tool's own timings (42 to 52 ns for add, mul and div, 184 for sqrtq, 745 for
`fmaq`) carry two more additions a call and are upper bounds only.

### 4.4 The golden model

python/cft_golden at fp128 and fp256, one call a case, on random normal operands: 6 to 23 us an operation
(MEASURED, S3, two runs 27 minutes apart: fp128 add 8.7 and 11.1, mul 8.3 and 20.0, fma 11.6 and 13.6, div 9.8 and
9.3, sqrt 6.9 and 22.7 us; fp256 add 9.6 and 8.1, mul 9.0 and 6.0, fma 7.1 and 11.1, div 12.3 and 11.5, sqrt 9.1
and 9.2; the desktop's load moved single figures by up to three times). A 2^32 item is then 7 to 27 core-hours, or
under an hour of the box's idle threads (COMPUTED, and the box's core and Python 3.12 differ from this desktop's:
ESTIMATE). So the model is fast enough to arbitrate every disagreement and
to re-check a whole slice item in the host pool, but it is the contract's own lineage; by SWP-A's Q8 ("Yes") it
stays the arbiter, not the oracle.

### 4.5 Cheap independent oracles

- **Exact identities**: rint and scaleB in range (the wide result equals the narrow one), products and near sums of
  slice values (the exact value), F1's exact quotients (the quotient by construction). No library needed.
- **Constructions**: an F0 case knows its side of the boundary (|N| = 1 and its sign, verified exactly as it is
  built: READ, divsqrt_soak.c), so the correctly rounded quotient is known without computing it; the same for S0.
  The hard case is its own oracle, as the brief says.
- **The residual check.** A claimed root y is the RNE root of x exactly when (2y - 1)^2 < 4x < (2y + 1)^2 in scaled
  integers; a quotient q is checked the same way through a - q b. Verifying is cheaper than computing and shares no
  code with MPFR or the model. MEASURED in Python (S3, two runs): 0.87 to 0.97 us a case at 113 bits and 1.11 to
  1.29 at 237, every correct root of 20,000 passing and every root one ulp high refused. In C it is a few limb
  multiplies (BELIEVED tens of ns).

---

## 5. The cost

### 5.1 The card's rates at fp64, fp128 and fp256

No record gave a card rate for division or square root at fp128 or fp256 (the nearest, cft-rebound's "1.70 us an
element" for the program route at binary128, was another image at n = 768; READ, `host/src/divsqrt.c`), so the
study wrote a probe (`hx_probe.c`) and the lead ran it on amd-arc-box at 11:17 (box time) on 2026-10-26: libcft at
49d7c3b7 (rtl 44b963dd and host a162f59b asserted, the trees of 78d5b526), the quad image 4f9921a2, one call of
4,096 elements at a time (the soaks' BATCH), RNE, each operation and format first checked against the software
backend, bytes and flags, then timed for 2 s. Every check was equal (MEASURED; `box-out/`). M elements a second:

| op | fp64 | fp128 | fp256 | four tiles at once, the quad's sum (fp64 / fp128 / fp256) |
|---|---|---|---|---|
| div | 1.586 | 0.947 | 0.542 | 6.38 / 3.93 / 2.20 |
| sqrt | 1.458 | 0.901 | 0.505 | 5.97 / 3.69 / 2.04 |
| rint | 4.793 | 3.629 | 1.808 | 20.4 / 13.0 / 8.11 |
| scaleb (n = 3) | 15.98 | 10.40 | 7.04 | 77.9 / 43.9 / 27.4 |
| fma | 22.66 | 18.84 | 10.70 | 88.9 / 72.4 / 45.9 |
| mul | 22.63 | 17.66 | 9.92 | 82.2 / 71.1 / 48.9 |
| add | 22.19 | 17.29 | 11.65 | 83.7 / 67.3 / 48.1 |

Read with three facts (all COMPUTED by `hx_cost.py` from the probe's files):
- **Four tiles at once are four tiles**: each tile ran at 0.87 to 1.41 times tile 1 alone, so the quad's rate is
  four tiles' for every row, as it was at the resident rates (READ, BENCHMARKS: "Four tiles are four times one").
- **Division and square root are tile time plus a fixed host cost.** t = h + L T64, L the elements a beat holds
  against fp64's (1, 2, 4), fitted on fp64 and fp128, gives h = 205 ns and T64 = 425 ns for division and h = 262 and
  T64 = 424 for the root, and predicts fp256 within +3.4% and -1.0%. So at fp256 the fit puts the tile at about
  nine tenths of a division's time (4 x 425 ns against h = 205); roundToIntegral (four elementwise passes) does not
  fit the model, being call-bound.
- **The soak runs at about 0.78 of the bare call**: div64-hard's sweep rate on the quad, 440,237 indices a second
  (READ, nightly-1024 `status.txt`) at 2.805 cases an index (COMPUTED from `HARD_WHOLE`), is 1.235 M cases a second
  against the probe's 1.586. The soak's own random div64, 4,194,304 cases in 3.63 s with its start (MEASURED, the
  lead's run), agrees: at least 1.16 M a second.

### 5.2 What a night gives the sweep

From nightly-1024's record (COMPUTED from its `metrics.jsonl`, the lead's copy, outside the tree): 401,752 s on
the card over six runs, sweep job-seconds quad 699,441, single 20,763, deep 18,874 (the host pool's 16,321 apart),
battery legs 176,699. **The sweep gets 1.84 tile-seconds a card-second.** A weekday night was 12.85 hours on the
card (the mean of the five, 12.09 to 13.33), so **23.6 sweep tile-hours**; a weekend window (Friday 18:00 to Monday
08:00, 61.4 hours on the card, ESTIMATE) gives **113**; two weeks (eight weekday nights and two weekends) **415**.
The driver weights exhaustive items 3 to 1 over random ones (READ, docs/CARDDAY.md, `--sweep-weights`), so while any
exhaustive item is uncovered the wide items would get about 311 of those 415.

### 5.3 Each item's card time

Tile-hours for every attribute listed (COMPUTED by `hx_cost.py`: indices x cases an index / the probe's rate of
tile 1 alone; the hard modes at 0.78 of the bare call as at fp64, the square-root hard modes at fp64's 0.24; the
class modes at the fp64 class modes' cases a second, ESTIMATE, since they run one call a case). Not counted: the
oracle in line, about +10% (4.2, ESTIMATE), and the slices' native ladder check, a nanosecond a case.

| item | level | indices | k | attributes | tile-hours |
|---|---|---|---|---|---|
| sqrt64-f32, recip64-f32 | L1 | 2^32 | 1 | 5 | 4.09, 3.76 |
| sqrt128-f32, recip128-f32 | L1 | 2^32 | 1 | 5 | 6.62, 6.30 |
| sqrt256-f32, recip256-f32 | L1 | 2^32 | 1 | 5 | 11.80, 11.00 |
| rint128-f32, rint256-f32 (both variants) | L1 | 2^32 | 2 | 5 | 3.29, 6.60 |
| div128-hard, div256-hard | hard | 289,931,696; 293,864,352 | 2.805 | 5 | 1.53, 2.71 |
| sqrt128-hard, sqrt256-hard | hard | 4,456,448 | 0.392 | 5 | 0.01, 0.02 |
| div64-hard at fp128, at fp256 | hard | 289,685,696 | 2.805 | 5 | 1.53, 2.67 |
| rint128-class, rint256-class | L2 | 137,344; 537,600 | 2; 1 | 5 | 0.40, 0.78 |
| scaleb128-class, scaleb256-class | L2 | 317,448; 1,370,952 | 2; 1 | 4 | 0.06, 0.13 |
| a low-bit window, sqrt at fp128, fp256 | L1 | 2^32 | 1 | 2 | 2.65, 4.72 |
| a low-bit window, reciprocal at fp128, fp256 | L1 | 2^32 | 1 | 2 | 2.52, 4.40 |
| sqrt128-f64top, sqrt256-f64top | L1 | 2^32 | 1 | 5 | 6.62, 11.80 |

The lead's guess (hypothesis 4) is **amended by measurement**: a 2^32 item at fp128 is 1.26 to 1.32 tile-hours an
attribute for division and root, and 2.2 to 2.4 at fp256; the hard and class items are minutes; the whole of phase 1
(section 7) is about 133 tile-hours, 7.5 weekday nights' worth at the exhaustive weight (a weekend is worth 4.8 of
them), so about one week with its weekend, not "a few weeks" (COMPUTED from 5.2 and 5.3). The fp64 slice whole
remains out (3.2).

### 5.4 The campaign, ranked by value per card-hour

The value column is a judgement (BELIEVED), argued in section 3; the hours are 5.3's.

| rank | items | tile-hours | why first |
|---|---|---|---|
| 1 | hard cases at fp128 and fp256: division (F3a to F0K) and square root (S1, S0), five attributes | 4.3 | every case at a rounding boundary or a strip; the class a sampler never reaches (SWP-A 4.2) |
| 2 | div64-hard's and sqrt64-hard's operands through fp128 and fp256 | 4.2 | the ladder at its thinnest margin, MPFR at full width, the first inputs with 53-bit significands |
| 3 | class: rint and scaleB at fp128 and fp256 | 1.4 | the wide adder's rounding at every position; scaleB's wide subnormal strips, which nothing else reaches |
| 4 | the fp32 slice: square root and reciprocal at fp128 and fp256 | 35.7 | a complete statement over 2^32 inputs at each wide lane set: every seed cell, the whole program |
| 5 | the fp32 slice: rint at fp128 and fp256 | 9.9 | the wide adder at the integer position, against an exact identity |
| 6 | the fp32 slice at fp64: square root and reciprocal | 7.9 | an L1 statement on fp64's lanes with the native oracle at full width |
| 7 | low-bit windows: four H, square root and reciprocal, fp128 and fp256, rne and rup | 57.2 | the input's low half, every pattern |

### 5.5 The host pool's share

The wide campaign's host items are the class items of the conversions (3.5): fp128 -> fp64 1,979,424 cases an
attribute, fp256 -> fp128 63,208,320, the integer targets 367,488 and 821,760, the integer sources 50,923 each. At
the fp64 class modes' CPU rates (READ, nightly-1024 `status.txt`: conv64to32-class@cpu 2.10 M/s, cvtto64-class@cpu
0.62 M/s, cvtfrom64-class@cpu 1.50 M/s), and with an MPFR oracle in place of the native one at perhaps half that
(ESTIMATE), the largest (fp256 -> fp128) is about a core-minute an attribute and all of them together a few
core-minutes for five attributes (COMPUTED from the ESTIMATE): the pool's 8 workers finish them inside any night.
The pool is also where the golden model could re-check a whole slice item, 7 to 27 core-hours each (4.4), if
Logan wants a second lineage on the card's claims (question 6).

---

## 6. The build

Within the driver's design as it stands: new work is new tool modes and new catalog items, each an exhaustive
`<lo> <hi> <attribute>` job with the ", E encodings, S skipped" verdict clause the coverage wave's modes print, so
the driver, its rates per `op@image`, its reach and the scheduler that wraps it
(docs/studies/SCHED-A-card-scheduler.md) need entries, not changes of design. Sizes are ESTIMATE, from the coverage
wave's parcels of the same
shape (HC, CL; READ, docs/VALIDATION.md).

| order | parcel | what | size (ESTIMATE) |
|---|---|---|---|
| 1 | HXa, the wide division and root soak | `host/tools/divsqrt_soak.c`: an MPFR oracle taken from `host/tools/mpfr_check.c`'s emulation (format range and unbounded, RMM by construction), linked as `mpfr-check` is (`-lmpfr -lgmp`; the box's pinned MPFR, READ docs/VALIDATION.md); 16- and 32-byte operands; modes `sqrt{64,128,256}-f32` and `recip{64,128,256}-f32` over 2^32 with the native narrow result as a second check (R1, 4.1); `div{128,256}-hard` and `sqrt{128,256}-hard` with GMP builders, F1's odd parts drawn from enough 64-bit words for p > 132 and python/hardcases.py refusing an unsupported p by name (3.4); the fp64 hard operands at fp128 and fp256; the four window modes, H by name; `hard-count` and `hard-dump` for every new space; python/hardcases.py given the wide spaces and held to the C tool line for line, as today | 1,000 to 1,400 lines of C, 150 of Python, a day or two |
| 2 | HXc, the catalog | `hw/card_stress_lib.py`: an `Item` a mode and attribute, `OP_REACH` (tile), `PER_ENCODING`, `HARD_SPACE` and `HARD_WHOLE` from `hard-count`, `level`; the soak's build line with MPFR; the dry run's stand-ins and `hw/test_card_stress.py`'s cases | 200 to 400 lines with tests, a day |
| 3 | HXb, the wide class modes | `host/tools/clause5_soak.c` and `python/c5_class_enum.py`: `rint{128,256}-class` and `scaleb{128,256}-class` (k = 2 and 1 lanes), the conversions' wide class modes (host), `rint{128,256}-f32` against the native fp32 rint (an exact identity), the MPFR oracle of `mpfr_check.c`'s clause-5 section; then its catalog entries | 700 to 1,000 lines of C, 100 of Python, a day or two |
| 4 | HXd, the report and the page | a format named in each item's line and the page's class per tree (Logan's Q4: "Per tree"); the wide items reported beside the 71 | 50 to 150 lines, half a day |
| later | HXe, phase 2's tools | the oracle beside the call (a thread or a second process per soak job) for the FMA, mul and add; a class-level FMA generator (3.6); the fp64 top-bits slices | ESTIMATE when phase 1 has run |

HXa and HXc together are what phase 1's first night needs (ranks 1, 2, 4 and 6 of 5.4); HXb brings ranks 3 and 5,
HXd the report. Every parcel keeps the soaks' sabotage control: a planted flip must still be caught in each new mode.

---

## 7. The plan

**Phase 1, about 133 tile-hours** (COMPUTED from 5.3 with the oracle's +10%, ESTIMATE): 120.5 tile-hours of items,
7.5 weekday nights' worth of the sweep at the exhaustive weight, so about one week with its weekend once HXa and
HXc are merged, and well inside two weeks of nights (311 tile-hours at that weight, 5.2):
1. the hard cases at fp128 and fp256, division and square root, five attributes (4.3 tile-hours);
2. div64-hard's and sqrt64-hard's operands through fp128 and fp256 (4.2);
3. the class items of rint and scaleB at fp128 and fp256 (1.4), and the wide conversions' class items in the host
   pool;
4. the fp32 slice through square root and reciprocal at fp128 and fp256, five attributes (35.7);
5. the fp32 slice through rint at fp128 and fp256 (9.9);
6. the fp32 slice through square root and reciprocal at fp64 (7.9);
7. sixteen low-bit windows: H all ones, all zeros, alternating and one keyed, for square root and reciprocal at
   fp128 and fp256, under rne and rup (57.2).

Each pass is a named claim at its level: L1 over the stated space for 4 to 7, hard for 1 and 2, L2 (PLAUSIBLE) for 3.

**Then** (phase 2, a few weeks, ESTIMATE): the fp64 top-bits slices (18.4 tile-hours for the square root, 17.3
for the reciprocal); more windows (H by family,
both exponent parities; 2.5 to 4.7 tile-hours each); the FMA class items once HXe exists (ESTIMATE a few
tile-hours); keyed F0 segments beyond 2^26 divisors if phase 1's hard items run clean. **Long term** stay where
SWP-A put them: the value-level (L1) reduced spaces of fp32 division and fp64 square root (3 and 15 quads for a
decade; READ, SWP-A 6.4), which nothing here brings closer.

---

## 8. Questions for Logan, each with a recommendation

1. **Phase 1** (7). The hard cases, the widened fp64 hard operands, the class items, the fp32 slice of square root,
   reciprocal and rint at the wide formats, and sixteen windows: about 133 tile-hours, a week of nights with its
   weekend, after parcels HXa and HXc. *Recommended: yes, as ranked.*
2. **The oracle at fp128 and fp256** (4.2). Neither the box's Xeon nor this desktop's CPU computes fp128 or fp256
   in hardware, so the host-FPU rule (SWP-A Q8) cannot reach them. MPFR, by `mpfr_check.c`'s emulation against the
   box's pinned 4.2.2, would be the wide
   items' oracle; the narrow native result a free second check on the slices (4.1, R1); a hard case its own
   oracle. *Recommended: yes; the golden model stays the arbiter of any disagreement.*
3. **Naming the claims** (3, 4.1). Each item's pass stated with its space and level, for example "fp128 square
   root: every fp32 input, widened, all five attributes, bits and flags (L1 over the fp32 slice)", and never as
   "fp128 square root swept". *Recommended: yes, as SWP-A's Q5 answer already asks of L1 and L2.*
4. **quadmath** (4.3). gcc's `__float128` is a second fp128 lineage at 15 to 22 ns for add, mul and div; on this
   desktop's library (12.3.0) add, sub, mul, div and `fmaq` agree with MPFR under all four attributes, values and
   inexact, and `sqrtq` is wrong in a quarter of RNE cases. *Recommended: HXa runs `hx_quadmath.c` against the box's
   pinned library; quadmath joins the oracles for the operations that pass, never by default, and phase 1 does
   not wait for it.*
5. **Share against the random items** (5.2). As exhaustive items, the wide items take the existing 3-to-1 weight,
   which finishes phase 1 in about a week. *Recommended: no change to the driver's weights.*
6. **A second lineage on the slices** (4.4, 5.5). The golden model could re-check a whole slice item in the host pool
   in 7 to 27 core-hours. *Recommended: not in phase 1: MPFR is the independent check, the model the arbiter.*
7. **The FMA** (3.6, 4.2). The FMA, add and mul have no sweep item at any format, and at the wide formats their
   oracle needs threads of its own. *Recommended: phase 2, with HXe.*
8. **Order against M2** (6). *Recommended: HXa and HXc before M2 resumes, since they are what the nights need; HXb
   and HXd beside M2.*
9. **The transcendentals** (out of the brief's scope). The six routines on the tile (exp, expm1, exp2, log, log1p,
   log2; READ, CAPABILITIES.md's note of 2026-10-21) have no sweep item, and an fp32 slice through each at fp128
   would be an exhaustive item of this kind, with MPFR, which rounds them correctly, as the oracle; the ladder
   cannot serve them, since a correctly rounded function value has no distance lemma and may lie within half a
   wide ulp of a narrow midpoint (the Table Maker's Dilemma; READ, SWP-A 4.2). I argue they do not belong in this
   campaign yet: their card rate is unmeasured, and the mark-and-replay path is better tested by hard cases than by
   a slice. *Recommended: a study of their own after M2's build.*

---

## 9. What this study does not establish

1. **The ladder is proved by exhaustion at toy precisions only** (p = 3 to 5 for the binary operations, 3 to 10 for
   the root, 3 for the FMA, with one toy exponent range) and checked at p = 24 on 14,832 constructed hard cases; at
   the real rungs it rests on those and on the classical conditions, which I recall and did not read (BELIEVED).
2. **The card rates are one probe of 2 s a row** on one image, random normal operands, RNE, n = 4,096. Other
   attributes, operands (subnormals, specials) or the other two images may differ; the soak's own rates at fp128 and
   fp256 are COMPUTED from the fp64 hard modes' efficiency (0.78 and 0.24), not measured.
3. **The class modes' wide rates are ESTIMATE**: one call a case, assumed to cost what it costs at fp64.
4. **MPFR's cost in a soak is ESTIMATE**: twice the READ per-operation figures, times 1.4 for the box's core; gmpy2's
   MEASURED figures carry Python's loop and bound it from above only.
5. **The night's capacity** comes from one record (nightly-1024, six runs); the weekend's 61.4 hours on the card is
   ESTIMATE; a change to the battery, the weights or the slice length moves it.
6. **The value ranking is a judgement** (BELIEVED). SWP-A's planted-defect measurement supports hard cases at fp64;
   nothing here plants a defect at fp128 or fp256.
7. **The hard-case families are carried to p = 113 and 237 unchanged.** Whether other families matter more at the wide
   formats (deeper strips, a keyed F0 beyond 2^26 divisors) is not studied; F1 cannot be built at p = 237 today (3.4).
8. **The full-width values** (3.1) are measured on the golden model's program route on 400 inputs a format, which
   the tile computes bit for bit by the contract; which multiplier columns they toggle in the RTL is not measured.
9. **quadmath** was measured on this desktop's library only (12.3.0, 100,000 cases a cell; overflow and underflow
   flags not compared), not on the box's; **the residual check in C** is not measured.
10. **Nothing was built**, and the probe is scratch: a soak mode written to the design of section 6 may run slower
    than the bare call by more than the fp64 hard modes do.

---

## 10. The instruments and their runs

All in `docs/studies/hx/`, each with its captured output beside it. They import the tree read only
(`python/hardcases.py`, `python/c5_class_enum.py`, `python/cft_golden`) and nothing in the tree imports them. The
Python ran in WSL cft2204 (Python 3.10.12, gmpy2 2.1.2, MPFR 4.1.0), niced, one at a time, except `hx_cost.py` and
`hx_fma_cex.py`, which need only the standard library and ran under the desktop's Python 3.12. Every script that
checks anything exits nonzero when a CHECK fails, and each has a control that must go red or a test that can fail.

| file | what | output | run |
|---|---|---|---|
| `hx_ladder.py` | the ladder by exhaustion (A), conversions, rint and scaleB (B), detection (C), controls (D), p = 24 on hardcases' F0 and S0 (E) | `hx_ladder.out` | `python3 hx_ladder.py TREE` (264 s) |
| `hx_fma_cex.py` | the FMA counterexample at fp64, fp128, fp256 | `hx_fma_cex.out` | `python hx_fma_cex.py` (under 1 s) |
| `hx_spaces.py` | the class spaces (S1), the hard spaces built and verified at p = 113 and 237 (S2), the oracles' speeds (S3) | `hx_spaces.out` (12:10), `hx_spaces.run1.out` (11:43, before its F1 check named the bound 132) | `python3 hx_spaces.py TREE` (10 s) |
| `hx_iterates.py` | the significant bits of the division and root programs' deposits on widened fp32 inputs | `hx_iterates.out` | `python3 hx_iterates.py TREE` (1 s) |
| `hx_probe.c`, `hx_probe_test.sh` | the card probe; its test on the software backend, with a sabotage control | `hx_probe_test.out` | `bash hx_probe_test.sh TREE WORK` (21 s, WSL) |
| `box_hx_probe.sh` | the lead's box run of the probe (a fresh clone, SHA and content asserted, sums) | `box-out/` | the lead, 2026-10-26 11:17 box time (about 2 min) |
| `hx_quadmath.c`, `hx_quadmath.sh` | gcc's `__float128` and libquadmath against MPFR, four attributes, values and inexact, with a sabotage control | `hx_quadmath.out` | `bash hx_quadmath.sh TREE WORK` (7 s, WSL) |
| `hx_cost.py` | the rates, the model, a night's capacity, each item's hours, phase 1 | `hx_cost.out` | `python hx_cost.py` (under 1 s) |

`box-out/` holds the box's outputs as the lead copied them (the summary, the five probe outputs, the two soak
outputs and the box's sums), so edited: the home directory in the image's path is written `$HOME`, so that no
personal path enters the tree, and nothing else is changed. The box's sums (`box-out/SHA256SUMS.box`, and
box/hx-probe/SHA256SUMS.box in the round's records) are of the originals, which those records keep with the
build log and the binary, neither committed here; the probe's source on the box is `hx_probe.c` itself (sha256
021737ce...).
