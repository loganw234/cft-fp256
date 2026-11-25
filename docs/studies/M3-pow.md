# Study M3: the correctly rounded pow, powr, pown, rootn and compound, designed

STATUS: a design study, 2026-11-19. Parcel M3S of the math library round
(docs/ROADMAP.md, "The math library: experiment E1, then M1's build and
M2 to M4 (plan of record, 2026-10-12)", its paragraph "M2, M3 and M4").
Logan, 2026-11-19, answering the lead's recommendation to start M3's study
once M4 was pushed: "Go ahead once M4 is pushed". **Nothing here is
built.** No routine of the pow family is in the golden generator, cftc is
unchanged, and the language still refuses `pow(x, y)` as `transcendental`.
The design goes to the lead, and through the lead to Logan, before M3's
build. This file, the model under `docs/studies/m3/`, this file's row in
docs/README.md with the counts it and docs/VERIFICATION.md state, and its
VALIDATION entry are the only changes the study made.

**2026-11-23, parcel M3G1 (M3's build, wave 1): the core, pow and powr are
built** in `python/cft_golden/mathlib.py` (the section "pow and powr"), at
fp64, fp128 and fp256, under all five attributes: `pow_core`, `plan_pow`,
`build_pow_core`, `POW_NAMES`, `POW_LIVE_CAP`, `POW_PLANTS` (23) and
`check_pow_constants` (`--check --only pow`). The construction is section
2's model (`docs/studies/m3/m3pow.py`) ported instruction for instruction and
in its order, and is held to it at the 30 configurations (VALIDATION, the
entry of the same date). pown, rootn and compound are parcel M3G2's; fp32,
the triple word, parcel M3F1's; the budget, the rate law, the families and
the exact-case rule against golden's own, parcel M3G3's; cftc, the language
and the card, later parcels'. What differs from this study, in the order a
reader of its section 2 would meet it:
- the study's "the sum is exactly sign |X|^Y" is, in the code, V = V_h + V_l =
  sign |X|^Y 2^-s in the scaled domain (s = floor(n/8), n the value of the
  probe `nf`), the two multiplications by 2^k1 and 2^k2 coming after V; the
  bound Bv is relative to |V_h|, as the study has it;
- `pow_core` takes `up` as a ref or as a function that makes it, called where
  the rule beside 1 is built, so that the body is emitted in the model's
  order; the front end for pown and rootn may pass either;
- `log_short`, one of the study's three budget plants, is in the table: the
  direct bound sees it at fp128 and fp256 over the region `rhoedge` (3.6, item
  8), and not at fp64, where B1 and B2 carry the shortfall;
- the names are public attributes of mathlib and are not in `__all__`:
  test_mathlib_inv_asin.py:142 pins `tuple(__all__)` to M4G1's base (the
  lead's word, 2026-11-23);
- three statements of the study about the tree hold and are noted: "mathlib's
  `evaluate` already takes a tuple" is M4G1's change and holds; "pow and powr
  are the second and third routines of two inputs" holds after atan2; and
  section 6's "MATH holds the thirteen" is the language's, untouched here.

**A note of 2026-11-23, at parcel M3G2** (pown, rootn and compound built in
the golden generator on M3G1's core; the study's text stays as written). What
is built, and where it differs from the study:

- n is a constant of the fragment and the key is `(name, fmt, rnd, n)`;
  `mathlib.pow_n(name, n)` checks it (an int that is not a bool, in int64's
  range; `rootn(x, 0)` refused by name). Their builders are a table of their
  own, `_POW_N_BUILDERS`, not `_POW_BUILDERS` (which stays pow and powr, so
  the harness's `FUNCS` stays two: the lead's approval of 2026-11-23). Their
  one input is x; two n are two fragments with one `op`.
- n = 0 and n = 1 are the small fragments (family "small": 6 instructions, 9
  for compound(x, 0), 25 to 26 for compound(x, 1)); a plant at them is refused
  by name. The study's model fell through to the core there.
- Equal to the model (`docs/studies/m3/m3pow.py` `build_any`) at 570
  configurations (the three functions, fp64, fp128 and fp256, five attributes,
  19 n at fp64 and 10 at the others, from 0 to 2^63 - 1 and -2^63, 2^53 + 1,
  2^54 + 3, 2^60 + 5): by dag digest of the design-order fragment and of the
  scheduled one, by the emitted instruction order (words by their bits), live,
  instruction counts and instructions by phase. The one difference, 315 of
  the 570: the model's Build holds the word `SIGN_BIT` (the sign mask) in every
  build, and this port holds it only where it is read (pown and rootn at an odd
  n, and rootn's plant), so its bank has one word fewer there; no instruction
  reads it.
- `compound` takes the log1p reduction on x through `_pow_logarithm` (the
  low word's block, the correction subtracted in phase Z, SMALL's selects);
  its constants are log1p's with 1/ln 2's two words added to the dictionary
  (the generator makes no `IL2H` for log1p), so the plant `il2h_ulp` acts on it
  there too. `ex` carries `u_l = 0` for compound; rootn's V = 1 where `ex`.
- At fp64 and |n| above 2^53, Y is a double word (n_h, n_l), first used in a
  fragment here; the Fraction `ybound` (`YB2`) first ran in a routine here. At
  fp64 n_l is nonzero only above 2^53; the region `nlow` holds lanes there,
  `n_low_dropped` is red in it. At n = 2^63 - 1 no lane of x beside 1 keeps
  |n log2 x| under T_f at fp64 (kmax 0), so that n has no in-range lane.
- A region none of whose lanes reaches the main path prints NOT MEASURED (the
  study's `int63` at fp64 for pown, and the others a run finds); it is outside
  the pass count. pown and rootn exclude |x| = 1 from the main path.
- The plants `exact_rule_no_tl` (shape alone) and `side_rule_off` (shape and
  constants) are red in no check of lanes for these three: at x = 2^E, L = E exactly so t_l is 0 (the
  rule's test never decides), and t_h cannot underflow with n an integer (the
  first design's corner is pow's y).

**A note of 2026-11-23, at parcel M3G3** (the first-order budget, the mark-rate law, the structured families and the exact-case rule for pow, powr, pown, rootn and compound; the study's text stays as written). What is built, and where it differs from the study:

- **The budget** (`python/tests/mathlib_pow_budget.py`, the model's `budget.py` on the tree's Build, a subclass of M4G4's `InvAnalyzer` and `InvBudget`). It equals the model's digits at the model's lanes at 19 of 19 cells (rounding instructions, M, capacities, bound and residual to four figures, and the lane list by digest): `pow-budget --set reference`. The harness's `region` and `region_n` give the model's lanes at the same seed at all 19. The fixed grid is read as "final" through a light proxy of the build, so that the memoised Build is not mutated (the model set `meta["fn"]` on it); a test shows it equal before and after. The tree's Build has no instruction labels (the model's are its own): the logarithm's sum is found as the phase-"recon" instructions that `Lh` and `Ll` read, 16 at every format, which is the model's "log-sum".
- **The desktop set** (`pow-budget --set desktop`, every region of the harness, 120 lanes at fp64 and 40 above, seed 1, rne: MEASURED, tree d4c1a292): fp64 50 cells measured and 2 NOT MEASURED (pow's hugey and pown's int63), 234.3 s; fp128 45 and 2 (pow's and powr's hugey), 101.1 s; fp256 45 and 2 (the same), 80.5 s and 164.3 s; every cell under 1 Bv, 0 findings. The largest cell figure of each function (a budget's bound, or with its residual: a sampled figure at its own lanes, not the study's box figures at 10,000): fp64 compound 0.194 (zone1000), pow 0.1178 (zone), pown 0.1107 (zone1000), powr 0.1158 (rhoedge), rootn 0.02934 (int-neg); fp128 0.00337 (compound zone188000), 0.002807, 0.003357, 0.001354, 0.0005537; fp256 0.006233 (compound and pown at zone2990000), 0.004048, 0.003044, 0.002496; powr has no study figure beyond fp64's wide (0.01215), so these are this build's own. A region whose every V is exactly f (fp256's `tinyy`, as in the study's own output) is measured with a bound of 0 and says so.
- **Budget plants**: `bound_tight` and `zone_bound_off` are in `mathlib._POW_BUDGET_PLANTS`, not in `POW_PLANTS` (28 keys, as the other parcels' tests read it); they act at fp64 and are refused by name at fp128 and fp256. `bound_tight` is red in the budget (pow `edge` 2.78 Bv at 120 lanes) and ALSO in the direct bound (`edge` at 120 lanes, seeds 1 and 2: 2^+0.63 and 2^+0.42, not at 48 points of seed 11; `near1` at all three seeds). `zone_bound_off` is red in the budget at compound's `zone1000` by the analytic leg (below) and in the direct bound at no cell or seed measured: pow's `edge`, `near1` and `wide` at seeds 1 and 2 (120 lanes) and 11 (48 points), the largest 2^-5.46 (`near1`, seed 2); and VM3G3's seed 7 (120 lanes, fp64 rne, log2 of |V - f| / Bv, control / `bound_tight` / `zone_bound_off`): compound `zone1000` -4.32 / +1.89 / -1.68, pow `zone` -4.53 / +4.75 / -1.81, pow `near1` -5.78 / +1.07 / -5.78, pow `edge` -7.07 / +0.59 / -6.49: under 1 everywhere, and nearest to it (2^-1.68) in the zone. `bound_tight` is red in the direct bound at the cells and seeds named above and at seed 7's four (the figures it was seen at are those, not a list of the only ones).
- **`zone_bound_off` on the desktop** (MEASURED): the sampled bound is 1.015 at compound `zone1000`, 120 lanes, seed 1 (a margin of 1.5 %), and 0.745, 0.831, 0.761, 0.864 at seeds 2 to 5; 1.085, 0.970, 0.862, 1.090, 0.864 at 300 lanes; under 0.75 at 60 lanes. So the sampled bound is red at some seeds and not at others. **The analytic leg** (the study's 3.2, `zonebound.py`, ported with the build's own B1 and B2) is 1.62 to 1.75 at every seed and lane count run for compound, 1.05 to 1.07 for pown `zone12000` and pow `zone`, and **not red at pown `zone1000`** (0.968 to 0.981: 0.898 for the sum and the sampled rest). With the build's own B1 the bound for the five roundings is 0.1455 Bv, not the study's 0.171 (which leaves |L| B1 out); compound's nine by the reduction's cells are 0.231.
- **The mark-rate law** (`mathlib_pow_rate.py`): each lane's own p from the build's probes, the exact Bernoulli tail, no cell judged with a lane at the cap. The port reproduces the study's cells exactly (`mathlib_pow_rate.model_cell`): the study's z values are the Poisson form. Beside them, the statistic the marks obey: fp64 rne 436 of 600 marked, 456.6 predicted, Poisson z -0.96 and **Bernoulli z -3.00, with 312 of the 600 lanes at p = 1**; rtz 309, 320.3, -0.63 and -1.19 (68 at the cap); fp128 rne 202, 216.3, -0.97 and -1.95; rtz 109, 108.2, +0.08 and +0.10; fp256 rne 153, 145.3, +0.64 and +1.30; rtz 75, 72.6, +0.28 and +0.35. The study's fp64 cell is not a rare event (a mean p of 0.76), the cap's lanes carry no variance, and the Bernoulli z is the larger. **The cells as measured** (`pow-rate`, the rule's inflation, tree d4c1a292): 42 cells judged (pow and powr at `wide`, pown, rootn and compound at `int` and `int-neg`, three formats, rne and rtz), none with a lane at the cap, the largest p under 1/2, 0 findings; 6 cells NOT MEASURED (compound at fp64 expects 14.7 and 15.9 marks at 600 lanes, and at fp256's `int-neg` 29.0 at 200; at 3,000 lanes the four fp64 compound cells are judged, 71 to 74 marked of 64.9 to 70.2 expected). The smallest two-sided tail of the 46 is compound fp256 rne `int`, 51 marked of 35.2 expected, z +3.33, tail 0.00168: not a finding at the run's level (alpha 0.001 over the run's statistics), noted. No study baseline exists for powr or the n-keyed functions. At the rule's shifts the double word gives pow's z +0.03 (rne) and -0.59 (rtz) at fp64: the law holds there. The open fp32 over-prediction of about 9 % (M3X) is not explained here.
- **The families and the committed list** (`mathlib_pow_family.py`): the theory (`status`: gated, decided, must, clear, either, over golden's own classes and the distance in units of the lane's own Bv), ten generators (intpow, root2k, pow2, near1, dominant, edges, smallint, hard3p, twop, tie) and the committed list `POW_FAMILY[fn][fmt][attribute]` (174 entries over 30 classes, a literal of 277 lines, GENERATED and held to a fresh generation, each entry carrying a digest of its lane list). The list is keyed by the two classes (rtz, rdn and rup are one; rne and rmm the other): a departure from the brief's per-attribute literal that keeps it under 450 lines. At fp64 pow under rne the families are 1,027 lanes: 355 must be marked (all are), 297 clear, 3 either, 138 decided, 234 gated; every unmarked lane is right and no mark is off the list. The study's census is reproduced at fp64 exactly (the port draws with the same `random.Random(seed * 7919 + width)` calls): every class count and every marked count of the eight families, 0 wrong unmarked, 0 marks off the list, `off_rule` 0. The harness's structured rows (pow, powr and the n-keyed at the n list, three formats, five attributes) agree with the theory: no committed lane is wrong.
- **The fifth reader of the plant names.** The brief named four assertions that read the plant tables; `test_mathlib_pow_n.py::test_plants_the_pow_front_owns_are_refused_on_the_three_by_name` was a fifth: its loop over the two budget plants expected 'unknown plant' for pown. The lead approved the departure: the loop now asserts, for pown, rootn and compound, that the two plants are accepted at fp64 and refused by name at fp128 and fp256.
- **What this brief got wrong, and the theory's departures.** d is in units of the lane's OWN Bv, not of the nominal 2^-(p+G) |f|: at fp64 Bv is |V| (2^-97 + |t| B1 + |Y k| B2), up to 193 times the nominal at |t| of 1,024 (pow(max, -1)), so a lane at 5 nominal bounds from a boundary is inside its own. Under rne and rmm the boundaries are the midpoints AND the floats (the "may be exact" test). The beside-1 gate (|t| under 2^-(p+3)) decides its lanes whatever their d. A subnormal result is also judged in the scaled domain's p-bit cell (pow(max, -1) marks under rne because V sits on a p-bit midpoint of the scaled cell). An exact lane with a power-of-two base is decided under every attribute (the tie pow(2, emin - p)). The study's census `off_rule` of hard3p, 60, is the 12 lanes of y = +1 times five attributes: y = 1 is one of Logan's cheap exact cases, decided in the lane (x itself), so the port EXCLUDES those lanes from `off_rule` (the port's `_y_is_one` (python/tests/mathlib_pow_family.py), and the exact-case check skips them); a leg of their own holds them (`check_y_one`: y = 1, n = 1 and n = 0, both signs of x, unmarked and equal to transcend.py under every attribute).

M4's study (docs/studies/M4-invtrig.md) is its nearest model of form,
section for section, and M1's design (docs/studies/M1-exp-log.md) is its
foundation: pow is built from M1's logarithm and M1's exponential. Where
this study departs from an inherited decision it says so.

Every statement is one of five kinds, and says which:
- **READ**: from this tree at c3c39c87, with the file named;
- **MEASURED**: from a run of the study's model (section 11), on the
  desktop, unniced (a niced run starved under the morning's load), one
  process at a time but for eight probes of under a minute that the
  ledger names, each run's output kept beside the model as `*.out.txt`;
  the runs, their times and the desktop's load are in the round's ledger
  (`ledger/M3S.md`), which is outside the tree;
- **COMPUTED**: arithmetic on read or measured numbers, shown;
- **ESTIMATE**: mine, and said so;
- **PROPOSED**: this design. Every name, constant and order below is a
  proposal for the lead and Logan, not a decision.

**What is different about this model.** M1's, M2's and M4's models each
carried their own builder. Since M1's build, the tree's
`python/cft_golden/mathlib.py` holds a builder (`Build`) and M1's verified
exp2 and log2 in pieces (`_log_reduce`, `_table`, `_scale`, the constants
of `_log_constants` and `_dw_constants`, `plan_log`, `plan_exp`). The pow
core is those pieces put together with what is new, so the model
(`m3pow.py`) imports them and edits none of them, and its fragments are
`routines.Fragment`s that the tree's scheduler orders and that
`routines.program` runs on seq.py. Its budget is the tree's
(`python/tests/mathlib_inv_budget.py`, M4G4's port), taken by subclass.
Nothing in the tree imports the model.

**A note of 2026-11-23, at parcel M3X** (fp32's pow and powr built in the model; the study's text stays as written). 2.8's ESTIMATE is measured: pow at fp32 as a triple word at G = 40 is **925 instructions** under rne (the estimate was 800 to 1,150) with **32 values live** scheduled, reaching r31 (the estimate 28 to 34), and powr 903 and 29; the budget bound of every region of pow is under 1 Bv at the sketch's own B1 = 2^-66 and B2 = 2^-67, worst 0.198 Bv, margin 2.33 bits, and the pools are 0 wrong unmarked on the model and on seq.py. Question 5's option (b), the double word at fp32, builds in the model up to G = 16, not the 12 this section computes (527 instructions, 117 marked of pow's 794 pool lanes against the triple word's 57). All five of the build's conditions hold, so the measurement recommends the triple word; the choice is Logan's. The entry is docs/VALIDATION.md's of 2026-11-23, "M3X"; the model is `docs/studies/m3/pw32*.py` with its outputs.

**A note of 2026-11-23, at parcel M3F1** (fp32's pow and powr built in the golden generator; the study's text stays as written). Logan chose the triple word on 2026-11-23, and `python/cft_golden/mathlib.py`'s section "fp32: the triple word, pow and powr" builds it as M3X's model (`docs/studies/m3/pw32.py`) measured it: G = 40, GL = 48, the logarithm's plan (7, 6, 17) and the exponential's (3, 4, 9), B1 = 2^-66 and B2 = 2^-67, twelve static proofs that raise a ValueError naming the proof, the round-to-odd final rounding and test, the exact power of two, the rule beside 1, the fixed grid and the screens. The port equals the model by dag digest (the Build and the scheduled fragment) and by emitted order at all ten configurations, with the model's instruction counts (pow 925, 920, 921, 921, 925, powr 903, 897, 897, 897, 903), 32 and 29 values live scheduled, highest registers r31 and r28, and on every lane of the two pools (794 and 823) at the five attributes in result, flag word, V0, V1, V2, R, R1, R2 and Bv: the marks are the model's 57, 55, 55, 55, 57 and 34, 33, 33, 33, 34. **What differs from 2.8 and from the model, each by name:** the front ends call M3G1's classification, integrality and special rows (the model called m3pow.py's copies of them: the same instructions) and the build is not a subclass of the model's `PBuild` but a private `_PowTwBuild` with the same labels; the Build's words are roles (so that the constants' check holds every word of the fragment to account), and powr's Build bank therefore lacks the one word the model's holds and never reads, 0x80000000; the bound's `b1_dropped` is not a plant here, because the direct error stays under the weakened Bv over the regions the model's budget sees it in (near1, edge, zone and negint, sampled; the first-order budget of `pw32_budget.py`, which is not ported, alone sees it); fp32 has no budget in this build, as M4F1's atan had none, so the `bound` check is the direct error |V - f| / Bv by mpmath, and the model's measured margin carries over because the port equals the model. The model's law over-predicting pow's marks by about 9 % is still not explained, and nothing here says the law holds at fp32. The registers are the cost Logan accepted: the allocator has the 29 registers r3 to r31 beside a call, and M4C's first-spill rule, 30 less the cap, gives -2 for pow, whose callers spill at once, and +1 for powr; cftc's allocator is not run here. pown, rootn and compound at fp32 are parcel M3F2's, refused by name. The entry is docs/VALIDATION.md's of 2026-11-23, "M3F1".

**A note of 2026-11-23, at parcel M3P** (program.c parity for the pow family, section 8 item 9; the study's text stays as written). Item 9 is done: `host/tests/seq_check.py`'s routine corpus has a fourth part, "pow", which runs the 195 fragments of parcels M3G1 and M3G2 at fp64, fp128 and fp256 (pow and powr; pown, rootn and compound at n = 0, 1, 3 and -2^63, rootn's 0 refused by name) in both shapes through libcft beside the golden model, 390 programs and 20,419 lanes at the gate's command, 0 mismatches. pow and powr lanes are pairs (x, y) with y in stream b on both sides; pown, rootn and compound lanes are x with n a constant of the fragment. fp32 is named in the part's summary line and is no SKIP: the triple word's pow and powr are built (parcel M3F1) and join with pown, rootn and compound at parcel M3F2. Nothing in program.c changed; the programs name constant indices of 128 and up, which no program of the routine corpus's other three parts does (the fuzz corpora address them, in random programs) (the largest 131, 159 and 204 at fp64, fp128 and fp256), and no opcode that the other three parts do not. The figures, the plants and their formats are docs/VALIDATION.md's entry of 2026-11-23, "M3P".

**A note of 2026-11-24, at parcel M3L** (the language at 1.4; the study's text stays as written). Section 6's nodes, folds and refusals, section 7's rules and section 8 item 10's proof are built in the language (python/cft_golden/lang, docs/LANGUAGE.md), with five differences from the text. (1) Section 6's "a run-time pow(8, RN(1/3)) is not 2" holds in some cells only (MEASURED, four formats, five attributes, y = RN(1/3), the one lane): it is 2 under rne, rtz, rdn and rmm and not 2 under rup at fp32, where RN(1/3) lies above 1/3, and 2 under rne, rup and rmm and not 2 under rtz and rdn at fp64, fp128 and fp256, where it lies below 1/3; with y the constant 1/3 rounded under the program's own attribute it is 2 under rne and rmm and not 2 under rtz, rdn and rup at every format. The exact constant pow(8, 1/3) = 2 stands. (2) Section 7's pow rule reads `log(a)`, and the log of a constant other than 1 is irrational, so a folded log would refuse the tangent of `pow(2, x)`: the rule's log is a node that is never folded (a written tangent equation reads it back as the same node), and `pow(1, x)`'s is the node of the const 1, not 0. At a = 0 the discarded arm of the select still raises its flags (divideByZero from log(0), invalid from 0 times -inf): the tangent's value is the study's, its flags are not nothing. (3) A power whose exact numerator or denominator would need more than 2^22 bits is `constant-range` even where its value is in range (`pown(1 + 1e-30, 9223372036854775807)`, refused `constant-range` by a run; n = 2^63 is outside int64 and `integer-operand`): the table's "constant-range past 2^+-2^20" is not the only way to it. (4) Section 8 item 10's rewrite `a * 1` doctored as `a + 0` differs at -0 under rne, rtz, rup and rmm and agrees under rdn (measured at four formats); the proof uses those attributes. (5) The eight rewrites equal their nodes bit for bit and flag for flag on every lane of a pool of 78 at each of the four formats under the five attributes, the three's rewritten n at fp32 included (python/tests/test_lang_pow.py); the figures and the plants are docs/VALIDATION.md's entry of 2026-11-24, "M3L".

**A note of 2026-11-24, at parcel M3C** (cftc's output version 9; the study's text stays as written). Section 6's cftc and the rewrites, section 5.2 to 5.4's caps and section 7's reference are built in the compiler (python/cftc, python/cft_golden/routines.py, docs/LANGUAGE.md's compiler spans), with five differences from the text. (1) The measured caps are the ones the plan gave (pow 30, powr 23, 22, 22, pown 21, rootn 19, compound 22; pow 32 and powr 29 at fp32), and the first value spilled beside a call comes at 30 less the fragment's live count: 0 for pow at fp64 to fp256 (one slot, from k = 0) and -2 at fp32 (3 slots), 7, 8, 8 and +1 for powr, 9 (pown at n = -2^63; 10 at fp128 and fp256 for n = 3, whose fragment keeps 20), 11 and 8, measured at every k from 0 to 20. (2) pow at fp32, cap 32, compiles inline, passes the internal check and runs as the golden function; a looped batch of pow is declined where its body needs more than the allocator's 29 registers (fp32 under every attribute; fp64 to fp256 under rne and rmm; powr at fp32), as atan2's is. (3) The rewrites are applied at the IR, before the lowering, in the step and in a tangent section (the rule's pown(v, 2) is v * v in the compiled bytes), and equal the node's value on every lane of the pool at every format where the node compiles, fp32 included for the three's rewritten n. (4) The reference is the study's falling body with the names alt, v and m (h is the step's name), parameters g = 5/4, H = 8, k = 1/16 and c = 1/32, round rdn, at fp64 and fp256; its lanes mark none; only the rules of pow and pown are held by it, so powr's, rootn's and compound's rules move no committed byte. (5) A tangent section's own log of a constant base compiles as any log. The figures and the plants are docs/VALIDATION.md's entry of 2026-11-24, "M3C".

**A note of 2026-11-24, at parcel M3XN** (pown, rootn and compound at fp32 built and measured in the model, `docs/studies/m3/pw32n.py`; the study's text stays as written). 2.6's "two words are exact for |n| < 2^48" holds for n and not for 1/n: rootn's 1/n at two words is red in the budget (28,700 Bv at n = 3, 361 Bv at n = 17, over 1) and at three words green (0.061 and 0.055 Bv), and n of up to three words is exact for every int64 (the second word is never rounded past 2^48 in this design). 2.8's triple word for the three, which the study called PROPOSED and not modelled, is built: **pown 865 to 891 instructions, rootn 871 to 892, compound 918 to 932** under rne at the twelve n measured (the three attributes' counts are in the entry), **28, 27 and 28 values live** scheduled (the highest register r27, r26 and r27, so a caller has 2, 3 and 2 values beside a call), B1 = 2^-66 and B2 = 2^-67 hold at first try (worst region bound 0.209, 0.092 and 0.331 Bv; compound is the function that needs both, over 1 Bv when either is tightened to 2^-70 or 2^-71), and the pools are 0 wrong unmarked on the model and on seq.py. Conditions (a) to (d) and (f) hold at every n measured; (e), the budget, is measured only at the n where a region has a lane (pown n = 3, -3, 17, 1000, 2^24 + 1; rootn those and 2^31 - 1; compound every n measured but 2, -2 and 2^62 + 2^37 + 1) and NOT MEASURED at the others, which only the pools (0 wrong unmarked) cover; the measurement recommends the triple word for pown, rootn and compound too; question 5's choice is Logan's. For pown every lane but x = +-1 is screened past |n| about 1.77e9 for n > 0 and about 1.50e9 for n < 0 (COMPUTED, found by the model's own screens); compound is the function that keeps main-path lanes at every n (x about t ln 2 / n). The budget leaves out the lanes with |t0| < 2^-27 (a named limit: it does not bound them). The entry is docs/VALIDATION.md's of 2026-11-24, "M3XN".

**A note of 2026-11-24, at the lead's box run of parcel M3XN's model** (the study's text stays as written). `pw32n_box.sh` at 1d0a1015 on amd-arc-box, 12,000 lanes a region (docs/VALIDATION.md, the lead's entry for wave 4's merge): pown's and rootn's measured regions are all under 1 Bv (worst 0.296 and 0.159). **compound's first-order budget is over 1 at n = 1000**: int1000 1.377 Bv and zone1000 1.0075 Bv, against measured direct errors of 0.148 and 0.092 Bv. Its two largest terms are the logarithm's, which n multiplies: log-sum (capacity 0.63 Bv) and the low word of 1 + x (log-lowword, capacity 0.53 Bv, the largest observed, 0.37): 2.8's fp32 meets the cancelling zone that fp64 met, found again only by volume (M3XN's 300 lanes read 0.331 there). Logan's answer, "Split it (Recommended)": fp32's pown and rootn are built as the triple word (parcel M3F2); compound waits for a model follow-up on its low word, checked at volume.

**A note of 2026-11-25, at parcel M3XN2** (compound at fp32 in the model, `docs/studies/m3/pw32c.py`; the study's text stays as written). 2.8's compound at fp32, the triple word of M3XN, was OVER 1 Bv at n = 1000 (1.377296 at the box's 12,000 lanes) in its two logarithm terms, log-sum and log-lowword; the follow-up attributes both to instructions (five plain-sum adds of level 2 for log-sum, six instructions of rho's low word for log-lowword, capacities 0.613 and 0.528 at int1000), scans n (the unfixed model is over 1 Bv at six int cells, n = 200, 300, 500, 1000, -300 and -1000, at the box; log-lowword's block has lanes only for |n| below 1570 (x > 0, n > 0), 1745 (x < 0, n > 0), 1850 (x > 0, n < 0) and 1481 (x < 0, n < 0), the screens' -152 < t < 129 over |x| >= 15/256), and builds two fixes in the model: fixA (compensated level-2 sums, the cross term, an exact correction, rho^3/3: 1,015 to 1,036 instructions, cap 28) and fixB (fixA with rho_l's exact products: 1,056 to 1,077 instructions, cap 32, no value beside a call), int1000 0.611 and 0.374 Bv at the desktop's 2,000 lanes. The box's volume figures of the fixes and Logan's choice among four options are in docs/VALIDATION.md, the entry for parcel M3XN2.

**A note of 2026-11-25, at the lead's fix of wave 4's box gate** (a second defect in the oracle; the study's text stays as written). 1.3's "The oracle's known defect" names mpfr_compound_si's. A second was found by the box gate of wave 4: mpfr_rootn_si returns an exact +-1 for rootn(+-2^E, n) when E >= 1 and |n| is huge. At fp32, as the lead measured it, that is every |n| from about 2^33 E up (E = 1 from 2^33, E = 127 from 2^40), which takes in n = -2^63, the routine sweep's seventh n. host/tools/mpfr_tfn.h computes those cases with a Ziv loop of its own, `tfn_rootn_pow2` (TRANSCENDENTALS.md, "The oracle's own defect"; VALIDATION.md, 2026-11-25), so the sweep's oracle for rootn at that n is not mpfr_rootn_si alone. The model, which uses no MPFR, is unchanged.

## Contents

0. In brief
1. What M3 works with
2. The algorithms
3. The error bound and the in-lane test
4. The specials and the flags
5. The cost
6. The language and the compiler
7. The derivative rules
8. How it will be held
9. Questions for Logan, each with a recommendation
10. What M3's build builds, in order
11. The model

---

## 0. In brief

- **What.** pow, powr, pown, rootn and compound at fp32, fp64, fp128 and
  fp256 under each of the five attributes, each a fragment in C4's shape,
  quiet, raising exactly transcend.py's flags, and setting bit 7 of the
  raised word where its own test cannot decide the last bit. PROPOSED, and
  measured in a Python model built on the tree's `mathlib.Build` and M1's
  built pieces, op by op through softfloat.compute, on seq.py as programs,
  and against transcend.py and mpmath; fp32's triple word is designed and
  ESTIMATED, not modelled (2.8).
- **The set, one core, the order** (2.1, question 1): all five, as front
  ends of ONE core, sign 2^t with t = Y log2|X|: X is x, or 1 + x as an
  exact double word for compound; Y is y, or the constant n in one or two
  words, or 1/n in two. The logarithm is M1's log2 planned finer, the
  exponential M1's exp2 with a double-word argument. Order: pow and powr,
  then pown, then rootn and compound. cft-debris's request (pow) is the
  first item.
- **The logarithm's precision** (2.2): t's integer part runs to the
  format's exponent range, so L needs about log2 T_f more bits than p + G:
  8, 11, 15 and 19 at fp32 to fp256 (COMPUTED). The double word holds them
  at fp128 and fp256 (G = 46, uniform); **at fp64 it cannot** (107 bits
  against 106), and the bound grows with |t| and with the reduction's k:
  Bv = |V_h| (2^-97 + |t_h| 2^-100 + |Y_h k| 2^-101), G from 43.8 at
  |t| = 1 to 36.9 at the top of the range where k = 0, at most 0.63 bits
  less where |k| >= 1 outside the cancelling zone. B1 was set by the
  budget after two tries (3.6, item 6); the |Y k| term is send-back 1's
  fix for the reduction's cancelling zone, |x| in [1/2, 241/256), where
  k = -1 and log2 m' cancel to L = -0.0871 and the logarithm's error is
  absolute (3.2, 3.6 item 9; question 3).
- **The sign and the integer operand** (2.5, 2.6): y's integrality and
  parity in-lane from the encoding in four bands up to 2^262143 (ADD, SUB,
  CMPEQ, IAND, ICMPLT, SELECT); n a constant of the program, its words in
  the bank (int64 exact in one word at fp128 and fp256, two at fp64; at fp32
  two words, the screens answering past 2^31).
- **The exact cases** (2.7, 3.5): a power-of-two x at an integer t, y = 1,
  and n = 0 and 1 are decided in-lane, exactly; every other exact case
  marks (under rne and rmm by a new "may be exact" test, without which an
  exact result is answered with the inexact flag, unmarked and wrong);
  midpoints mark under rne and rmm. cftc rewrites pow(a, 2), pow(a, 1),
  pow(a, -1) and pown's and rootn's like into a * a, a * 1 and 1 / a,
  bit and flag equal on every lane measured (6).
- **The cost** (5): pow 434, 489 and 540 instructions at fp64, fp128 and
  fp256 (powr 21 fewer, pown, rootn and compound 375 to 520), 125 to 202
  bank words, no scratch; pow keeps 30 values live, the round's largest, its
  special rows' conditions living across the main path; two pow calls on
  one x share the logarithm (40 to 47 % of a call).
- **Held in the model** (3.2, 3.3, 4; MEASURED): the pools of all five functions
  (the vector sets' and the stage's, about 800 lanes for pow and powr and
  4,000 for each integer function) under the five attributes at fp64,
  fp128 and fp256: 0 wrong unmarked lanes; on seq.py, pow's and powr's pools
  and the integer functions' at six n, at fp64, fp128 and fp256, 0 wrong
  and 0 lanes differing from the model; every region of 3.3 (both
  operands over their whole ranges and every corner the brief lists, 40 to
  400 lanes a region) 0 wrong after the fixes below; section 4's rows 0
  wrong at the three formats; the first-order budget under 1 Bv in every
  region sampled on the desktop (sampled figures: 120 lanes a region at
  fp64, 40 at fp128 and fp256; fp64's largest 0.194 Bv, compound(x, 1000)
  in the cancelling zone; fp128's under 0.0034 and fp256's under 0.0063),
  and at the box's 10,000 lanes (MEASURED by the lead, `box-sb1/`) every
  fp64 region of the fix under 1 Bv too, its largest compound(x, 1000)'s
  `int1000` at 0.374 (1.42 bits), above the desktop's sampled largest, and
  fp128's and fp256's at most 0.0036 and 0.0072; and in the cancelling
  zone, where the box found the design before
  send-back 1 past 1 Bv (1.052, compound(x, 1000) at 10,000 lanes), the
  budget's dominant part bounded on every lane: the logarithm's sum at
  most 0.171 Bv, 0.231 for compound (COMPUTED, 3.2); the mark-rate law
  within one sigma; the census's families with every power-of-two exact
  case decided and every other exact case marked but y = 1's, 0 wrong;
  eighteen lane and mark plants red in 21 named cases at fp64 and at fp256,
  two budget plants red in their regions and a third, `zone_bound_off`,
  red on the desktop at compound's `zone1000` (1.015 Bv) and, as the
  design it reproduces, at `int1000` on the box (1.052), a nineteenth lane
  plant shown redundant by design.
- **The model found eight things wrong in itself** (3.6), three of them
  design defects that every pool passed and only a region placed by the
  operands' own ranges reached: a tiny y (t_h underflowing) answered by V's
  rounding instead of by the side of 1; y's integrality wrong for |y| in
  [2^(p-2), 2^(p-1)); and a negative result rounding to zero answered +0.
  All three fixed, all three plants. And a plant green on every region
  showed a corner no region reached, the logarithm's weakest point, now the
  region `rhoedge`. Send-back 1 found a ninth at the box's volume: fp64's
  bound not shown sound in the reduction's cancelling zone, fixed by the
  |Y k| term (3.6, item 9). No defect in transcend.py was found.
- **Not done here** (the known limits): fp32 is not modelled (2.8); the
  budgets are the desktop's, 120 lanes a region at fp64 and 40 at fp128 and
  fp256, and bound their own samples (the larger samples are the box's:
  `box_m3s.sh`'s and, for the fixed design, `box_m3s_sb1.sh`'s, 10,000
  lanes a region, `box-sb1/`; those too are samples, and the box's fp64
  largest, 0.374, is above the desktop's 0.194); fp64's margin in the
  cancelling zone rests on the analytic bound of its dominant part and on
  sampled budgets of the rest; the language, the compiler and the
  derivative rules of sections 6 and 7 are designed, not run, but for the
  rewrites' equality; the integer-operand functions run on seq.py at six
  values of n, not every n of the pools; the queue logs' "rc" field is
  not the runs' status (11), so the runs are held by their outputs'
  completeness instead (`complete.py`).
- **Eleven questions for Logan** (section 9), each with a recommendation.

## 1. What M3 works with

### 1.1 The plan, and what binds it

READ, docs/ROADMAP.md, the math library's plan of record: "Each starts as
a design study like M1's: golden-first, measured in a model, its questions
to Logan before its build. Each function gains an L3 rule." "M3, the pow
family: its structured cases need 2p to 3p bits." "M3 comes last, as step
6's plan has it." M1, M2 and M4 are built and closed (the same section,
READ); M3 is the last of the round's builds.

Which functions are "the pow family" is settled nowhere. The roadmap's
"Noted 2026-11-06" list, item 9, says "BELIEVED: pow, pown, powr, compound
and rootn; its study will say" (READ). Section 2.1 says: all five, as
front ends of one core, in the order of section 10.

What binds it (READ: Logan's answers on M1's study, 2026-10-12, on M2's,
2026-10-14, and on M4's, 2026-10-23; and the code):
- **G:** `GUARD = {"fp32": 40, "fp64": 44, "fp128": 46, "fp256": 46}`
  (mathlib.py). This design keeps them, and at fp64 states where the double
  word cannot hold G = 44 (2.2): the one departure, with question 3.
- **fp32:** the triple word at G = 40, as every built fp32 routine is.
  M4's answer 3: it "has no budget, so the evidence for its bound is the
  box's samples and an exhaustive sweep of fp32's 2^32 arguments a
  function". A two-operand pow cannot be swept exhaustively (2.8, 3.3).
- **The in-lane test and the mark:** M1's test (M1's 3.1), bit 7 of the
  raised word (`seq.RAISE_MARK`, `1 << 7`) where the test cannot decide the
  last bit, quiet otherwise, raising exactly transcend.py's flags. This
  design adds one condition to it under rne and rmm (3.1).
- **The structured families keep their marks,** the windows' centres
  listed in the build's tests (M2's answer 7, M4's answer 7).
- **Constant arguments:** fold the exact cases, refuse every other constant
  by name (M1's question 8, M2's answer 8, M4's answer 8).
- **Live caps** per function and format (M4's answer 9); `LIVE_CAP` in
  routines.py holds today's.
- **The generator** in mathlib.py (M4's answer 11).
- **Versions:** M4's build stepped cftc's output version to 8
  (`python/cftc/__init__.py`, `VERSION = 8`) and the language to 1.3
  (docs/LANGUAGE.md, its opening). M3 proposes 9 and 1.4 (6).
- **No augmented addition:** the quad has no R21 (revision 8's question
  9), so every error-free sum is a TwoSum (6 instructions) or, where the
  exponents are provably ordered, a Fast2Sum (3).
- **The rounding rule:** IEEE 754 first, then RISC-V, then what fits
  current systems (Logan, 2026-09-29). All five are 754-2019's recommended
  operations (9.2, table 9.1), and transcend.py follows 9.2.1's rows for
  all five, two of them decided for the standard against MPFR: powr(+1,
  qNaN) is a quiet NaN, and compound(x, 0) below -1 is invalid (ROADMAP,
  "Table 9.1, completed").

**Who asks for it** (READ, ROADMAP, "Noted 2026-11-13", request 4):
cft-debris asked for "pow as a routine, or powr and pown"; by its own
reading the JB2008 atmosphere model makes about 225 pow calls an
evaluation, and NRLMSISE-00 needs pow too. A workload that exists, weighed
in 2.1 and in question 1, not the design's authority.

### 1.2 What a tile gives a routine

READ (`python/cft_golden/seq.py`, `softfloat.py`, `routines.py`,
docs/SEQUENCER.md), as M1's, M2's and M4's 1.2 list it:
- **32 registers** (`seq.NREG`), a bank of 512 constants (`KADDR_KX`),
  LDX and STX on scratch, no branch and no call: a routine is straight-line
  code that chooses with SELECT;
- **SELECT tests its condition's magnitude** (softfloat.select: "not +0
  and not -0"); a comparison gives 1.0 or +0; ICMPLT compares the encodings
  as unsigned integers; ISHL and ISHR take their count modulo the width;
- **RECIP_SEED and RSQRT_SEED** give 8.5 bits and flush a subnormal operand
  to infinity, so M1's logarithm scales a subnormal x by 2^p first (its
  `_log_reduce`, reused unchanged);
- **RAISE with the mark:** the routine runs QUIET, its body, ENDQUIET, then
  RAISE of a flag word whose bits [4:0] are the operation's flags and bit 7
  the mark (mathlib.py's docstring);
- **routines.program and routines.run take one or two inputs** (r0 and
  r1), so pow and powr run on seq.py as x in r0 and y in r1, x first as C
  and transcend.py have it;
- **a lane holds format values.** There is no integer lane type: pown's,
  compound's and rootn's int64 operand is the design's to carry (2.6).

### 1.3 The definition

READ, `python/cft_golden/transcend.py` at c3c39c87, by name:
- **`pow`** (two operands, x then y): its specials are C's. pow(x, +-0) is
  1 for every x, a quiet NaN included; pow(+1, y) is 1 for every y, a quiet
  NaN included; pow(-1, +-inf) is 1; an infinite y next (so pow(+-0, -inf)
  is +inf with no flag); a zero x: divideByZero for y < 0, the sign of an
  odd y kept; an infinite x; a negative finite x with a non-integer y is
  invalid; a signalling NaN in either operand raises invalid in every row
  (the function's first test). Then the exact cases, the screen, the rule
  beside 1, the Ziv loop.
- **`powr`**: exp(y log x), so a negative x is invalid for every y (a
  quiet NaN y included: "x < 0 outranks even a quiet NaN exponent"),
  powr(+-0, +-0), powr(+inf, +-0) and powr(+1, +-inf) are invalid,
  powr(+-0, y < 0) is +inf with divideByZero (silent at -inf), powr(+1,
  qNaN) and powr(qNaN, 0) are quiet NaNs.
- **`pown`** (x and an integer n): pown(x, 0) is 1 for every x but a
  signalling NaN; the zeros and infinities as pow's rows with n's parity.
- **`compound`** (x and an integer n): (1 + x)^n on [-1, +inf]. 1 + x is
  formed exactly, on the encoding (`_exact_one_plus`), never in the format,
  so compound(x, 1) is the exact 1 + x rounded once; for a small x
  (`_vexp(u) < -2`) the enclosure uses log1p of x; compound(x, 0) is 1 for
  x >= -1 or a quiet NaN and invalid below -1; compound(-1, n) is +inf with
  divideByZero for n < 0 and +0 for n > 0; and **the dominant operand**:
  for x >= 0 with vexp(x) >= p + 2 + bits(|n|), when x^n is an exact dyadic
  its side settles the answer (`_round_dyadic_side`).
- **`rootn`** (x and an integer n): x^(1/n). rootn(x, 0) is invalid for
  every x, a quiet NaN included; rootn(x, 1) is x, exactly; rootn(-0, 2)
  is +0 where squareRoot(-0) is -0 (the even-n row); x < 0 with an even n
  is invalid, -inf included.
- **The exact cases are decided exactly**, not by enclosure:
  `_pow_dyadic` (pow and powr, with `_exact_2k_root`), `_pown_dyadic` (pown,
  and compound on the exact 1 + x), `_rootn_dyadic` (rootn). Each returns an
  exact (m, e) when the value is a dyadic rational whose odd part fits
  p + 1 bits, and None otherwise, "a PROOF, not a shrug" (its docstring): the
  value is then neither a grid point nor a midpoint. A midpoint is an exact
  case that no precision decides by enclosure; the routine must decide it
  exactly or mark it.
- **The shared machinery:** `_screen_exponent`, the overflow or underflow
  response when the result's base-two logarithm is provably outside the
  format, with a unit of slack past each threshold (emax + 2 and
  emin - man_w - 2), so the tie at half the smallest subnormal is never
  decided there; **the rule beside 1**: when |y log|x|| is below 2^-(p+3)
  the answer is 1's neighbour on the side the operands give (n log|x| for
  pown, n log(1 + x) for compound, log|x|/n for rootn); and the Ziv loop
  for everything else.

**The integer operand** is an int64 an element in the library (ROADMAP,
"Table 9.1, completed", "Closed: the integer operand", READ), and
transcend.compute takes it as a Python int.

**The oracle's known defect** (READ, the same section): mpfr_compound_si is
off by one ulp for a negative n when 1 + x is not representable at the
working precision. The model uses no MPFR: its references are transcend.py
and mpmath at 4p + 200 bits (`m3core.true_value`, compound's 1 + x formed
exactly as a Fraction first).

The routine must equal transcend.py in bits and flags on every lane it
does not mark.

## 2. The algorithms

### 2.1 The set, one core, five front ends

PROPOSED: all five functions, on ONE core,

    result = sign 2^t,    t = Y log2|X|,

carried in double words at fp64, fp128 and fp256 (triple words at fp32,
2.8), and five front ends that differ only in what X and Y are, in the
sign, and in the special rows:

| function | X | Y | sign | specials (section 4) |
|---|---|---|---|---|
| pow | x | y, an input | negative where x < 0 and y is an odd integer (2.5) | C's table |
| powr | x | y, an input | never | powr's table, x < 0 invalid |
| pown | x | n, a constant in one word (fp128, fp256) or two (fp32, fp64) whose sum is n exactly (2.6) | x's where n is odd | pown's rows |
| rootn | x | 1/n in two words | x's where n is odd | rootn's rows, x < 0 invalid for even n |
| compound | 1 + x, the exact double word TwoSum(1, x) | n, as pown's | never | compound's rows |

**The core** (MEASURED in the model at fp64, fp128 and fp256 under all
five attributes; `m3pow.build`):
1. **L = log2|X| as a double word**, M1's log2 at fp64 to fp256: x = 2^E m
   (a subnormal scaled by 2^p), C = round(16 RECIP_SEED(m)) by the
   magic-number FMA, r = m' c - 1 EXACT by one FMA, L_j = log(16/C) in two
   words read by a SELECT tree, Y(r) = log1p(r)/r by a single-word tail and
   K double-word steps, r Y as a double word, F = L_j + r Y, F (1/ln 2) in
   two words, and k + that: mathlib's `_log_reduce`, `_table` and the
   `_build_log_dw` sum, at the larger guard GL of 2.2. compound's X = 1 + x
   enters through M1's log1p reduction: the low word u_l of TwoSum(1, x)
   moves r by r_l = u_l 2^-k c, corrected by 1/(1 + r) from Newton steps,
   and |x| < 15/256 skips the reduction (r = x, k = 0).
2. **t = Y L as a double word** (2.3): t_h0 = RN(Y_h L_h); its error exact
   by one FMA; Y_h L_l and Y_l L_h by two more; one Fast2Sum.
3. **2^t**, M1's exp2 with a double-word argument (2.4): n = round(8 t_h)
   by the magic-number FMA, r' = t_h - n/8 EXACT, r' + t_l by Fast2Sum,
   r = r' ln 2 in two words (one FMA more than exp2's), M1's table of
   2^(j/8), polynomial, reconstruction V = T (1 + Z) = V_h + V_l, the scale
   2^k1 2^k2, the fixed grid for a result that may be subnormal, and the
   in-lane test.
4. **The sign** applied to V_h and V_l before the final rounding (IXOR
   with a sign word: exact), so that every attribute rounds the signed
   value; the fixed grid's offset carries the same sign.
5. **The exact power of two decided in-lane** (2.7), the rule beside 1
   (2.7, 3.1), the screens on t_h0 (2.4), the specials.

**Why one core.** Each of the five is exp2(Y log2 X) on its main path
(transcend.py's enclosures are iv.power for pow, powr and pown,
iv.exp(n log1p x) or iv.power of the exact 1 + x for compound, and
iv.exp(log x / n) for rootn but at n = +-1 and +-2: READ). What separates them is cheap: where X and Y
come from, the sign, and the rows of section 4. A second core would buy
nothing that the five cannot share: the logarithm is 37 % of pow's
instructions at fp64 and the exponential 28 % (5.1, MEASURED by part), and
both are the same code in all five.

**The special paths weighed against the core** (the brief's three; the
figures are 5.1's, MEASURED, and ESTIMATE where said):
- **pown by multiplication** for a small |n|: x^n as a double word by
  repeated TwoProd, with its own bound. For n = 2 the double word is exact
  (x^2 = TwoProd(x, x)), so pown(x, 2) is MUL(x, x) under the program's
  attribute, bit for bit and flag for flag, with no routine at all: a
  compiler rewrite (6). For n = 3 and 4, a double-word product carries
  about 2p - 3 bits and its exact cases are exact in it, so it would decide
  more of the exact family than the core does (3.5); ESTIMATE 25 to 45
  instructions and a bound of its own to prove, against pown's 373 to 493
  on the core (5.1, MEASURED). Not proposed for the first build: it is a second algorithm
  with a second bound for a family the core already answers (by marking
  its exact cases), and the compiler rewrite takes the one n (2) that
  programs write most (question 4).
- **rootn by Newton** from RSQRT_SEED or RECIP_SEED for a small n:
  rootn(x, -1) is C4's division 1/x, a compiler rewrite (6); rootn(x, 2)
  is C4's square root but at -0 (rootn(-0, 2) is +0 where sqrt(-0) is -0,
  MEASURED in 6), so it is not a rewrite as it stands (a SELECT after C4's
  root would make it one, ESTIMATE 2 instructions; not proposed, the core
  answers it). rootn(x, 3) by Newton from a seed would need a cube-root seed (the
  tile has none: a reciprocal seed and two Newton steps for 1/x^(1/3),
  ESTIMATE 30 to 50 instructions) and an exactness rule for perfect cubes;
  not proposed.
- **compound by M1's log1p for a small x:** this is the design: compound's
  logarithm IS M1's log1p reduction, with 1 + x's low word carried, and its
  |x| < 15/256 path is log1p's r = x path.

So the core answers every n and every y; the compiler takes the few
constant exponents whose answer is an existing operation, bit and flag
equal (6, question 4); and each function keeps one fragment shape.

**The order** (PROPOSED, question 1): pow and powr first (one fragment
shape, two tables of specials; cft-debris's request names pow), then pown
(the core with n's words, the parity a constant), then rootn (1/n's words,
the even-n domain) and compound (the log1p front, the dominant operand)
together. Section 10 lists the build's items.

### 2.2 The logarithm's precision

An absolute error d in t moves 2^t by a relative ln 2 d, and t = Y L, so a
relative error eps of L gives ln 2 |t| eps. The main path answers
t in (emin - p - 2, emax + 2) (the screens take the rest, 2.4), so for the
bound 2^-(p+G) the logarithm needs about p + G + log2 T_f bits, T_f the
largest |t| (COMPUTED, `bits.py`, `bits.out.txt`):

| format | p | G | T_f | log2 T_f | bits L needs (p + G + log2 T_f) | the double word | M1's plan_log reaches GL | GL planned | B1 |
|---|---|---|---|---|---|---|---|---|---|
| fp32 | 24 | 40 | 152 | 7.25 | 71.25 | 48 (the triple word 72) | - | - (2.8) | - |
| fp64 | 53 | 44 | 1,077 | 10.07 | 107.07 | 106 | 47 | 47 | 2^-100 |
| fp128 | 113 | 46 | 16,497 | 14.01 | 173.01 | 226 | 107 | 63 | 0 |
| fp256 | 237 | 46 | 262,381 | 18.00 | 301.00 | 474 | past 166 | 67 | 0 |

So the logarithm needs 8, 11, 15 and 19 bits past p + G (log2 T_f rounded
up, COMPUTED), and:
- **at fp128 and fp256 the double word holds them with room:** M1's log2
  planned at GL = G + extra + 2 (63 and 67) is M1's own code with a longer
  polynomial (K 16 and D 42 at fp128, K 17 and D 73 at fp256, against
  log2's 12/38 and 12/68 at G = 46), and the bound is M1's, Bv =
  2^-(p+G) |V_h|, uniform over the whole range (3.2 holds it by budget);
- **at fp64 it does not.** 107 bits are past the double word's 106, and
  M1's plan_log stops at GL = 47 (its floor, 12 u^2). With GL = 47 the
  logarithm's own error is about 2^-104 relative where it does not
  cancel, and far more where it does: M1's reduction takes m' in
  [0.94, 1.88), so an x in [1/2, 241/256) is k = -1 with log2 m' up to
  0.913 (241/256 is the reduction's own boundary, MEASURED by bisection on
  the model's k, `zonebound.out.txt`), and k + log2 m' cancels by up to
  3.5 bits, to L = -0.0871 at the top: the **cancelling zone**. The sum's
  roundings stay at log2 m''s scale, about 2^-106 absolute, whatever L is
  (3.2's analytic bound). PROPOSED: the bound grows with |t| and with the
  reduction's k,

      Bv = |V_h| (2^-(p+G) + |t_h| B1 + |Y_h k| B2),
      B1 = 2^-(2p-6) = 2^-100,   B2 = 2^-(2p-5) = 2^-101,

  rounded upward: against a uniform bound, |t_h| B1 is 1 instruction (an
  FMA; its fabs of t_h is the beside-1 test's, shared) and |Y_h k| B2 2
  more (a fabs of k and an FMA; pow and powr one MUL more for |y k|, the
  integer functions' |n| B2 being a word), made beside the product so
  that w, not t_h, lives across the exponential (MEASURED against the
  plant `bound_tight`, the uniform bound, under rne: pow 434 against 430,
  powr 413 against 409, pown(x, 3) 386 against 383, rootn(x, 3) 387
  against 384, compound(x, 3) 410 against 407; send-back 3). Where k = 0, G
  is 43.8 at |t| = 1, 43.0 at |t| = 8 (results
  in [2^-8, 2^8]), 40.8 at |t| = 64, and 36.9 at the top, |t| = 1,077
  (COMPUTED, `bits.out.txt`); where |k| >= 1 outside the cancelling zone
  the |Y k| term adds at most 55 % to Bv (G at most 0.63 bits less,
  COMPUTED: there |L| >= 0.913 |k|, so |Y k| B2 <= 0.548 |t| B1); at the
  zone's top it multiplies Bv by up to 6.7 (|Y k| B2 = 5.74 |t| B1 there),
  which is what its sum's absolute error needs. B1 was 2^-103 first (0.72
  Bv in the region `negint`, `first-b1/budget.fp64-pow-negint.out.txt`)
  and 2^-102 second, which was past 1 Bv for pown(x, 1000) (1.063 Bv,
  `second-b1/budget.fp64-pown-int1000.out.txt`); 2^-100 held every region
  at the desktop's 120 lanes, and the box's larger samples then found the
  cancelling zone past 1 Bv for compound(x, 1000) (send-back 1; 3.6, item
  9), which the |Y k| term answers. That is the departure from G = 44 at
  fp64, and
  question 3 puts it with its alternative, a triple-word logarithm at fp64
  (ESTIMATE: about 2.2 times the logarithm's instructions, the ratio of
  M1's built fp32 triple-word log2, 391 instructions, to its fp64
  double-word log2, 180: MEASURED, `tw32_ref.out.txt`), for the 7 bits at
  the top of the range (36.9 against 44).

**How much of M1's log2 it reuses:** all of it but the final rounding and
the test (MEASURED, by construction: m3pow.py calls `_log_reduce` and
`_table` and repeats `_build_log_dw`'s sum line for line, at GL), and for
compound M1's log1p reduction and low word (the same, the Newton steps four
at fp128 and fp256 where log1p takes three, since compound's logarithm is
planned 17 and 21 bits finer: COMPUTED, 2^-64 relative left by three steps
against the 2^-(p+GL) needed).

### 2.3 The product t = Y L

PROPOSED, exact where it can be:
- t_h0 = RN(Y_h L_h), and Y_h L_h - t_h0 EXACTLY by FMA(Y_h, -L_h, t_h0)
  (TwoProd's residual), for any Y_h: an input y of up to 2^emax at fp64 is
  a format value, and the product's residual is exact while t_h0 is finite;
- Y_h L_l and, where Y has a low word, Y_l L_h, by two more FMAs into the
  same residual (each rounded once, at 2^-2p of |t|);
- (t_h, t_l) = Fast2Sum(t_h0, residual): ordered, the residual being under
  an ulp of t_h0 or t_h0 = 0 (only for a special lane).

The product's rounding contributes 2^-2p |t| or so, which is under 2^-(p+G)
at fp128 and fp256 by 2^60 and more (COMPUTED from 2.2's table); at fp64 it
is part of B1. MEASURED by the budget (3.2): the `product` part's capacity
is at most 0.017 Bv in fp64's pow regions (`budget.fp64-pow-*.out.txt`),
the logarithm's sum's up to 0.125 (the region `redb`).

**When the product overflows** (y and log2|x| both large: pow(max, max)),
t_h0 is +-inf; its residual FMA gives a NaN downstream, and the screens read
t_h0, not t_h, so the lane is the overflow or underflow response (MEASURED:
the pools' max x max lanes, 0 wrong, section 4's "overflowing" row).

### 2.4 2^t, the screens and the edges

PROPOSED, M1's exp2 (mathlib's `_build_dw`, fn "exp2") with t a double
word:
- **n = round(8 t_h)** by FMA(t_h, 8, MAGIC), exact on the main path
  (|8 t_h| < 2^22 against 2^(p-1)); **r' = t_h - n/8** by one FMA, exact
  (|r'| <= 1/16 and a multiple of t_h's ulp, as exp2's x - n/8 is);
  **(r'_h, r'_l) = Fast2Sum(r', t_l)**, ordered: r' is a nonzero multiple
  of t_h's ulp or 0, and |t_l| is under half that ulp;
- **r = r' ln 2** in two words: r'_h ln2_h by TwoProd, r'_h ln2_l and
  r'_l ln2_h by FMA into the residual (one FMA more than exp2, whose r' has
  no low word);
- **the rest is exp2's** unchanged: the table 2^(j/8) in two words by the
  SELECT tree over n's low bits, the polynomial planned at GE = G + 2, Z,
  V = T (1 + Z), the scale words 2^k1 and 2^k2 from n's encoding
  (`_scale`), the fixed grid (`_fixed_grid`'s design: V_h split at the
  subnormal grid's offset, the rest added after rounding to odd, rounded
  under the attribute, the offset taken off), and the one final rounding
  FIN = (W 2^k1) 2^k2.

**The screens** (PROPOSED): on t_h0, overflow where t_h0 >= emax + 2 and
underflow where t_h0 <= emin - p - 2, answered by the attribute's overflow
response (OVFB, signed) and underflow response (a quarter of the smallest
subnormal rounded, signed), as transcend.py's `_screen_exponent` answers
with its unit of slack. Between the screens the main path rounds every
result itself: k up to emax + 1 scales to the overflow response through
FIN's rounding, and k down to emin - p - 2 rounds on the fixed grid. So
**the tie at half the smallest subnormal is the main path's**, never a
screen's, as transcend.py keeps it out of its screen; pow(2, emin - p) is an
exact case the in-lane rule decides (2.7; section 4's row of overflowing
and underflowing results holds 2^(emin-p-1), 2^(emin-p) and 2^(emin-p+1),
all decided, MEASURED). One screen threshold, emax + 2
and emin - p - 2, is used alike by the routine, the regions of 3.3 and the
plants (`screen_low`, 8): the brief's must-have, one range edge per format.

**Overflow's flag** (PROPOSED, a change from exp2's): CMPEQ(MUL(|Y1|, S2,
RUP), INF) at every attribute. exp2 tests FIN = +inf under rne, rmm and rup
and the RUP product only under rtz and rdn; with a signed result, rup's
negative overflow answers -max, not -inf, so the RUP product of the
magnitude is the one test that holds for both signs.

### 2.5 The sign, and y's integrality, in-lane

pow's result is negative exactly when x < 0 and y is an odd integer
(transcend.pow, READ). y is a format value; at fp256 it may be an even
integer of up to 2^262143. PROPOSED, in-lane, 15 instructions
(`_integrality`), four bands of |y| by three ICMPLTs of its encoding:
- **|y| < 2^(p-2):** yi = |y| + MAGIC (RNE), MAGIC = 1.5 2^(p-1). The sum
  stays below 2^p, so its ulp is 1 and it rounds |y| to an integer, exactly
  when |y| is one: **y is an integer iff yi - MAGIC = |y|** (SUB, CMPEQ);
  MAGIC's value 3 2^(p-2) is even, so **the low bit of yi's encoding is the
  integer's parity** (IAND with 1);
- **2^(p-2) <= |y| < 2^(p-1):** the ulp is 1/2, so the encoding's bit 0 is
  the halves (y is an integer iff it is clear) and bit 1 the units (the
  parity);
- **2^(p-1) <= |y| < 2^p:** every y is an integer and bit 0 is its parity;
- **|y| >= 2^p:** every y is an even integer, up to the largest finite.

So "y is an integer" is ADD, SUB, CMPEQ and IAND, and "y is odd" is IAND,
ICMPLT and SELECT, at every format, on the encoding. The first design took
MAGIC's band up to 2^(p-1), where y + MAGIC passes 2^p and loses the units
bit: wrong and unmarked for x < 0 and |y| in [2^(p-2), 2^(p-1)), a band the
pools never reach (3.6, item 2; the plant `integrality_wide`). MEASURED
since: section 4's rows across all four bands, the regions `negint` and
`hugey` (3.3). The sign word is SELECT(SIGN, 0, x < 0
and odd), and IXOR applies it to V_h, V_l and the fixed grid's offset.
pown and rootn with an odd n take the sign word as IAND(x, SIGN): n is a
constant, its parity the build's.

### 2.6 The integer operand

**How n reaches a lane** (PROPOSED, question 2): as a CONSTANT of the
program. The language takes pown's, compound's and rootn's n as an integer
constant (a literal or a `const`), checked to lie in int64's range, and
cftc builds the fragment for that n: n's words in the bank, n's parity and
sign in the fragment's specials. A lane holds format values only, so a
run-time integer would need a new kind of lane value; none of the
requests asks for one, and it is question 2's alternative.

**What an int64 n means at each format** (COMPUTED, `m3pow.int_words`):
- **fp128 and fp256:** every int64 is a format value (64 < p), one word.
- **fp64:** two words whose sum is n exactly, n_h = RN(n) and n - n_h, for
  every int64 (|n - RN(n)| <= 2^10 < 2^53).
- **fp32:** two words are exact for |n| < 2^48. Past |n| = 2^31 every lane
  but |x| = 1 is screened: the least |log2|x|| for x != 1 is
  log2(1/(1 - 2^-24)) = 2^-23.47, so |t| >= 2^31 x 2^-23.47 = 185 > 152
  (COMPUTED), and |x| = 1 is a power of two, decided exactly (2.7), its sign
  n's parity, a constant. So at fp32 the second word is rounded past 2^48
  and no answer moves (ESTIMATE until fp32's triple word is modelled: 2.8).
- **int64's extremes:** n = -2^63 is one word at fp64 (a power of two),
  2^63 - 1 is 2^63 - 1 (two words); at fp64 every lane of them but |x| = 1
  is screened (|t| >= 2^63 x 2^-52.47 = 2^10.53 > 1,077, COMPUTED), and the
  model's region `int63` finds no main-path lane (3.3, MEASURED). Their
  parity and sign are the build's constants: pown(-1, 2^63 - 1) is -1 and
  pown(-1, -2^63) is +1 (section 4, MEASURED).

**rootn's 1/n** is not a format value for most n: two words, RN(1/n) and
RN of the rest (a relative 2^-2p), and t = (1/n) L. **compound's 1 + x** is
TwoSum(1, x), exact; its low word enters the logarithm (2.1, step 1).

### 2.7 The exact cases in-lane, and the mark for the rest

A result that is exactly representable must come out with no inexact flag;
a midpoint must be decided exactly or marked. The core's V is within Bv of
the exact value but not equal to it, so:
- under rtz, rdn and rup a representable exact value is a rounding
  boundary, V straddles it, and M1's test marks the lane (MEASURED: the
  pools' exact lanes mark under the directed attributes, 3.5);
- under rne and rmm it is not a boundary: M1's test would DECIDE the lane,
  with the right value and the WRONG flag (inexact). PROPOSED: under rne
  and rmm the test also marks a lane whose interval [V - Bv, V + Bv] holds
  a grid point: g1 = RUP(V_h + (V_l - Bv)) <= g2 = RDN(V_h + (V_l + Bv))
  (two ADDs, a CMPLE, a SELECT), and in the fixed grid, zr = 0 with the
  rest within Bv. MEASURED: without it (the plant `exact_unmarked`)
  pow(3, 2) under rne is 9 with inexact, unmarked and wrong (8).
- **midpoints** mark under rne and rmm (their boundary) and are decided
  under the directed attributes, where a midpoint is no boundary and the
  inexact flag is right.

**What the routine decides in-lane exactly** (PROPOSED, MEASURED in 3.5):
1. **x a power of two with t an integer** (the reduction's r = 0, and
   r' = 0, t_l = 0 and j = 0): then V = 1 exactly, the scaled result is the
   exact 2^t, the mark is cleared, and the flag word is 0 where 2^t is
   representable (k from emin - p + 1 to emax) and the main path's
   (underflow or overflow with inexact) where it is not. This is every exact
   case of a power-of-two x (transcend's `_pow_dyadic` with M = 1: E y an
   integer), and so 2^n, 0.5^n, 4^0.5, 8^(2/3) as a format y cannot be, and
   pow(2, emin - p), the tie at half the smallest subnormal, rounded on the
   fixed grid from an exact V (8 instructions). For rootn the rule leaves out
   t_l = 0: 1/n's two words make t = E/n + E delta with delta about 2^-2p,
   and a t_h that is an integer then proves E/n is that integer (were E/n
   not one, it would be at least 1/|n| from the integer t_h, while t_h is
   within about |t_h| 2^-p of t and |t_h| <= T_f/|n|: T_f 2^-p would have to
   reach 1, and T_f < 2^p at every format: COMPUTED), so V is set to 1
   exactly (2 SELECTs; MEASURED: rootn's powers of two in the census's
   smallint family are decided, 3.5). For pow the t_l = 0
   condition is needed: y E = k + f with t_h = k and t_l = f != 0 is not an
   exact case (the plant `exact_rule_no_tl` makes it wrong, 8).
2. **y = 1:** pow(x, 1) and powr(x, 1) are x itself for every x that is not
   a NaN (CMPEQ and 2 SELECTs). Without it every pow(x, 1) is an exact case
   and marks.
3. **n = 0 and n = 1** of pown, compound and rootn are fragments of their
   own, of 6 to 26 instructions (`build_small`, 5.1): pown(x, 0) and compound(x,
   0) are 1 (invalid below -1 for compound, a signalling NaN invalid);
   pown(x, 1) and rootn(x, 1) are x; compound(x, 1) is ADD(1, x) under the
   attribute, its inexact flag from TwoSum's exact error, x = -1 answered +0
   (3.6); rootn(x, 0) is refused by the compiler (6).

**What is marked** (PROPOSED): every other exact case, the integer y with
a short odd part of x (3^2, 10^3, 1.5^3), y = Y/2^k with x a perfect 2^k-th
power (9^0.5, 4^1.5), and their midpoints under rne and rmm. 3.5 counts
them and question 4 puts the trade: marking costs a replay a lane, deciding
them in-lane costs an exact power in multiple words (ESTIMATE 30 to 60
instructions for n up to 4, and no bounded rule for a run-time y), and the
compiler's rewrites of pow(a, 2), pow(a, 1) and pow(a, -1) take the common
ones out of the routine altogether.

### 2.8 fp32

PROPOSED, the inherited triple word at G = 40, and NOT modelled here (a
known limit of the study, said in 0 and 3.3). What it needs:
- L to p + G + 8 = 72 bits (2.2), which is the triple word's 3p with no
  room for its own roundings: the same position as fp64's double word, so
  the same law, Bv = |V_h| (2^-(p+G) + |t_h| B1 + |Y_h k| B2) with B1
  about 2^-(3p-6) = 2^-66 and B2 about 2^-(3p-5) (ESTIMATE, fp64's rule at
  three words), G about 38.4 at |t| = 8 and 34.7 at |t| = 152 where k = 0
  (COMPUTED from those);
- M1's fp32 log2 and exp2 are built as triple words: 391 and 368 to 373
  instructions, 77 and 72 words, 17 and 20 values live (MEASURED,
  `tw32_ref.out.txt`). The fp32 pow core ESTIMATE: their sum less the two
  final roundings and tests (about 30) plus the product and the two-word
  r' (about 20) and the specials (about 60), or fp64's 434 (5.1) times
  the 2.1 to 2.7 that fp32's triple word cost against fp64's double word
  in the earlier designs (M1's exp 382 against 178, READ in the ROADMAP's
  E1 paragraph; M2's sin 939 against 406, the ROADMAP's M2X paragraph and
  docs/README.md's row of M2's study; M4's atan 472 against 176, M4's
  study): **about 800 to 1,150 instructions**, and **28 to 34
  values live** (M1's fp32 log2 and exp2 keep 17 and 20, and pow's
  special conditions add about 8 at every format, 5.2), at the edge of the
  32 registers where M4's fp32 atan2 keeps 31: to be measured first in the
  build (question 5);
- its evidence (M4's answer 3, "the box's samples and an exhaustive sweep
  of fp32's 2^32 arguments a function"): a two-operand pow cannot be swept,
  2^64 pairs. PROPOSED, by atan2's precedent ("Partial is acceptable",
  Logan, 2026-11-06): pow and powr at every y for a fixed list of x, and
  every x for a fixed list of y (question 5 names both lists); pown,
  compound and rootn are one-operand at a fixed n, so every x for a list of
  n (0, +-1, +-2, +-3, 17, int64's extremes) is exhaustive for each n.

### 2.9 Out of scope: hypot and rSqrt; exp10, exp10m1, log10, log2p1, log10p1

PROPOSED, a paragraph each, for question 11:
- **exp10 and exp10m1** are the core with X = 10 and Y = x: t = x log2 10
  with log2 10 in three words (a constant, no logarithm at all), then the
  exponential: ESTIMATE the exp2 half plus the product, about 230
  instructions at fp64; exp10m1 needs expm1's subtraction of 2^-k as well
  (about 250). Their exact cases (exp10 of a non-negative integer whose 5^k
  fits p bits) are the integer-y family of a constant base.
- **log10, log2p1 and log10p1** are the core's logarithm alone: L =
  log2|X| (X = x or 1 + x) times a constant (log10 2 in two words, or 1),
  with M1's final rounding and test: ESTIMATE about 200 to 240 instructions
  at fp64, M1's log2 and log1p plus one double-word product; their exact
  cases (log10 of 10^k; log2p1 where 1 + x is a power of two) are rules of
  the kind 2.7 decides.
- **rSqrt** is rootn(x, -2): the core answers it (MEASURED as rootn with
  n = -2 in the pools), or C4's square root and division composed with a
  rounding of their own (not bit-equal: two roundings); a dedicated Newton
  from RSQRT_SEED with an exact residual, as C4's root, ESTIMATE 40 to 60
  instructions.
- **hypot** is not a power: sqrt(x^2 + y^2) as a double word and C4's root
  with a residual; ESTIMATE 60 to 90 instructions, its dominant-operand rule
  and exact cases transcend.py's `_hypot_dyadic`.

Whether a build takes any of them is question 11.

## 3. The error bound and the in-lane test

### 3.1 The test

PROPOSED, M1's test (M1's 3.1, READ in mathlib.py's `_build_dw`) on the
signed V = V_h + V_l, with three additions:
- **The test itself:** R = rnd(V_h + V_l), R1 = rnd(V_h + RDN(V_l - Bv)),
  R2 = rnd(V_h + RUP(V_l + Bv)), and the lane is marked where R1 != R2
  (IXOR of the encodings): the interval [V - Bv, V + Bv] holds a rounding
  boundary of the attribute, so the last bit is not decided.
- **The bound,** Bv = 2^-(p+G) |V_h| at fp128 and fp256 (exact: a power of
  two times |V_h|), and Bv = |V_h| RUP(2^-(p+G) + |t_h| B1 + |Y_h k| B2)
  rounded upward at fp64 (2.2): the first addition.
- **"May be exact," under rne and rmm only:** marked also where the interval
  holds a GRID POINT, g1 = RUP(V_h + RDN(V_l - Bv)) <= g2 = RDN(V_h +
  RUP(V_l + Bv)), and in the fixed grid where zr = 0 with |V_l| <= Bv: the
  second addition (2.7). Under rtz, rdn and rup a grid point is already the
  attribute's boundary.
- **The decided cases that clear the mark** (the third): the exact power of
  two (2.7), whose V is exact, and the rule beside 1: where |t_h| <
  2^-(p+3) the answer is 1's neighbour on the side the operands' signs give,
  as transcend.py's rule answers (READ), not V's rounding (3.6, item 1).
- **The fixed grid's test** (M1's) for a result that may be subnormal: V
  straddles a boundary only where zr is one (u/2 under rne and rmm, 0
  under the directed three) and |V_l| <= Bv. In this design it is
  redundant: every boundary of the subnormal grid is a grid point at
  precision p in the scaled domain (its spacing is at least 2^(-p+2) of V
  there), so the main test marks it under the directed attributes and the
  "may be exact" test under rne and rmm (MEASURED: the plant that removes
  it is equal to the control, 8). Kept in the model, M1's form; the build
  may drop it (question 6).

A marked lane's value is the routine's best guess, rnd(V_h + V_l) (or the
fixed grid's), and the caller replays the lane with the definition.

### 3.2 The bound, budgeted

**The method** (MEASURED tool, READ method): verifier-VM1b's first-order
budget as the tree ports it for the inverse functions
(`python/tests/mathlib_inv_budget.py`, M4G4's), taken by subclass
(`budget.PowAnalyzer`), on this model's Build: for each lane the original
run, a twin in exact arithmetic with the data frozen (the seeds' outputs,
the magic-number sums that pick n and C, every integer instruction's and
comparison's sources before V), each rounding's error delta_i and its
sensitivity s_i = dV/dv_i by a reverse sweep from V = V_h + V_l, the true
value by mpmath at 6p + 300 bits scaled by 2^-k (V lives in the scaled
domain). Over a region: M, the method's own error (the polynomials'
truncation, the constants, the reduction), at its largest; each
rounding's largest CAPACITY |s_i| ulp(v_i)/2; the bound their sum, in units
of each lane's own Bv; the RESIDUAL, what first order leaves out, measured
beside it. The tool's one change for this design: the fixed grid is read
as after V (3.6, item 4).

**Over two operands** (the brief's must-have, M4's lesson): the regions of
3.3 place the lanes by t and by both operands' ranges, so a region is a
corner of the (x, y) plane, and every region of pow at fp64 is budgeted;
pown, rootn and compound are budgeted at the n of each region (one
fragment an n).

| format | function | region (n) | main-path lanes | M max | capacities | bound (bits of margin) | measured worst | residual |
|---|---|---|---|---|---|---|---|---|
| fp64 | compound | int (3) | 119 of 120 | 0.0003 | 0.0193 | 0.0196 (5.67) | 0.0047 | 9.5e-06 |
| fp64 | compound | int1000 (1000) | 120 of 120 | 0.0035 | 0.0426 | 0.0461 (4.44) | 0.0054 | 1.2e-05 |
| fp64 | compound | zone1000 (1000) | 120 of 120 | 0.0103 | 0.1838 | 0.1940 (2.37) | 0.0471 | 4.0e-06 |
| fp64 | compound | zone12000 (12000) | 119 of 120 | 0.0104 | 0.1306 | 0.1410 (2.83) | 0.0386 | 1.4e-07 |
| fp64 | pow | edge | 120 of 120 | 0.0010 | 0.0136 | 0.0146 (6.09) | 0.0080 | 2.1e-07 |
| fp64 | pow | hugey | 0 of 120 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 0.0e+00 |
| fp64 | pow | near1 | 117 of 120 | 0.0006 | 0.0567 | 0.0573 (4.13) | 0.0133 | 1.9e-06 |
| fp64 | pow | negedge | 120 of 120 | 0.0029 | 0.0646 | 0.0675 (3.89) | 0.0145 | 2.7e-07 |
| fp64 | pow | negint | 116 of 120 | 0.0042 | 0.0995 | 0.1037 (3.27) | 0.0173 | 6.4e-06 |
| fp64 | pow | redb | 120 of 120 | 0.0028 | 0.0691 | 0.0719 (3.80) | 0.0137 | 2.1e-05 |
| fp64 | pow | rhoedge | 113 of 120 | 0.0057 | 0.1100 | 0.1158 (3.11) | 0.0308 | 1.2e-05 |
| fp64 | pow | small | 120 of 120 | 0.0000 | 0.0011 | 0.0011 (9.78) | 0.0010 | 9.6e-06 |
| fp64 | pow | sub | 113 of 120 | 0.0002 | 0.0155 | 0.0157 (5.99) | 0.0075 | 2.4e-06 |
| fp64 | pow | tinyy | 120 of 120 | 0.0000 | 0.0000 | 0.0000 (19.00) | 0.0000 | 3.6e-25 |
| fp64 | pow | wide | 117 of 120 | 0.0001 | 0.0121 | 0.0121 (6.36) | 0.0063 | 1.1e-06 |
| fp64 | pow | zone | 116 of 120 | 0.0060 | 0.1119 | 0.1178 (3.09) | 0.0378 | 1.8e-06 |
| fp64 | pown | int (3) | 117 of 120 | 0.0002 | 0.0151 | 0.0154 (6.03) | 0.0051 | 1.1e-06 |
| fp64 | pown | int-neg (-3) | 117 of 120 | 0.0002 | 0.0152 | 0.0155 (6.02) | 0.0117 | 2.3e-06 |
| fp64 | pown | int1000 (1000) | 117 of 120 | 0.0060 | 0.1001 | 0.1061 (3.24) | 0.0241 | 5.6e-06 |
| fp64 | pown | int17 (17) | 117 of 120 | 0.0019 | 0.0474 | 0.0492 (4.34) | 0.0129 | 3.8e-06 |
| fp64 | pown | int31 (2147483647) | 117 of 120 | 0.0006 | 0.0568 | 0.0574 (4.12) | 0.0227 | 4.8e-06 |
| fp64 | pown | int63 (-9223372036854775808) | 0 of 120 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 0.0e+00 |
| fp64 | pown | zone1000 (1000) | 120 of 120 | 0.0059 | 0.1048 | 0.1107 (3.18) | 0.0364 | 1.2e-06 |
| fp64 | pown | zone12000 (12000) | 119 of 120 | 0.0060 | 0.0908 | 0.0968 (3.37) | 0.0402 | 2.5e-07 |
| fp64 | powr | wide | 117 of 120 | 0.0001 | 0.0121 | 0.0121 (6.36) | 0.0063 | 1.1e-06 |
| fp64 | rootn | int (3) | 120 of 120 | 0.0018 | 0.0274 | 0.0292 (5.10) | 0.0097 | 1.4e-05 |
| fp64 | rootn | int17 (17) | 120 of 120 | 0.0004 | 0.0208 | 0.0211 (5.56) | 0.0092 | 2.5e-05 |
| fp128 | compound | int (3) | 40 of 40 | 0.0005 | 0.0001 | 0.0006 (10.73) | 0.0006 | 1.1e-22 |
| fp128 | compound | zone188000 (188000) | 40 of 40 | 0.0027 | 0.0006 | 0.0034 (8.21) | 0.0031 | 8.2e-23 |
| fp128 | pow | edge | 40 of 40 | 0.0006 | 0.0001 | 0.0007 (10.45) | 0.0007 | 1.7e-22 |
| fp128 | pow | hugey | 0 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 0.0e+00 |
| fp128 | pow | near1 | 40 of 40 | 0.0003 | 0.0001 | 0.0004 (11.41) | 0.0003 | 1.4e-22 |
| fp128 | pow | negint | 40 of 40 | 0.0005 | 0.0001 | 0.0006 (10.72) | 0.0005 | 9.4e-23 |
| fp128 | pow | redb | 40 of 40 | 0.0007 | 0.0001 | 0.0007 (10.39) | 0.0007 | 2.2e-22 |
| fp128 | pow | rhoedge | 40 of 40 | 0.0009 | 0.0004 | 0.0013 (9.54) | 0.0011 | 1.6e-22 |
| fp128 | pow | small | 40 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 4.3e-25 |
| fp128 | pow | sub | 40 of 40 | 0.0003 | 0.0001 | 0.0004 (11.41) | 0.0003 | 2.5e-22 |
| fp128 | pow | tinyy | 40 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 1.6e-154 |
| fp128 | pow | wide | 40 of 40 | 0.0006 | 0.0001 | 0.0006 (10.65) | 0.0005 | 1.3e-22 |
| fp128 | pow | zone | 40 of 40 | 0.0023 | 0.0005 | 0.0028 (8.48) | 0.0025 | 1.9e-22 |
| fp128 | pown | int (3) | 40 of 40 | 0.0006 | 0.0001 | 0.0007 (10.47) | 0.0006 | 6.7e-23 |
| fp128 | pown | zone188000 (188000) | 40 of 40 | 0.0027 | 0.0006 | 0.0034 (8.22) | 0.0030 | 1.1e-22 |
| fp128 | rootn | int (3) | 40 of 40 | 0.0005 | 0.0001 | 0.0005 (10.89) | 0.0005 | 2.5e-22 |
| fp256 | compound | int (3) | 40 of 40 | 0.0000 | 0.0000 | 0.0000 (16.32) | 0.0000 | 2.6e-60 |
| fp256 | compound | zone2990000 (2990000) | 38 of 40 | 0.0056 | 0.0006 | 0.0062 (7.33) | 0.0060 | 5.0e-60 |
| fp256 | pow | edge | 40 of 40 | 0.0017 | 0.0001 | 0.0018 (9.14) | 0.0017 | 5.0e-60 |
| fp256 | pow | hugey | 0 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 0.0e+00 |
| fp256 | pow | near1 | 40 of 40 | 0.0012 | 0.0001 | 0.0012 (9.66) | 0.0012 | 1.2e-59 |
| fp256 | pow | negint | 40 of 40 | 0.0021 | 0.0001 | 0.0022 (8.84) | 0.0022 | 6.8e-60 |
| fp256 | pow | redb | 40 of 40 | 0.0030 | 0.0001 | 0.0030 (8.36) | 0.0030 | 3.9e-60 |
| fp256 | pow | rhoedge | 40 of 40 | 0.0021 | 0.0003 | 0.0023 (8.74) | 0.0021 | 6.0e-60 |
| fp256 | pow | small | 40 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 6.2e-61 |
| fp256 | pow | sub | 40 of 40 | 0.0025 | 0.0001 | 0.0025 (8.63) | 0.0024 | 8.1e-60 |
| fp256 | pow | tinyy | 40 of 40 | 0.0000 | 0.0000 | 0.0000 (-) | 0.0000 | 0.0e+00 |
| fp256 | pow | wide | 40 of 40 | 0.0008 | 0.0001 | 0.0008 (10.27) | 0.0007 | 5.7e-60 |
| fp256 | pow | zone | 40 of 40 | 0.0035 | 0.0005 | 0.0040 (7.95) | 0.0032 | 7.4e-60 |
| fp256 | pown | int (3) | 40 of 40 | 0.0012 | 0.0001 | 0.0012 (9.66) | 0.0011 | 5.0e-60 |
| fp256 | pown | zone2990000 (2990000) | 39 of 40 | 0.0056 | 0.0006 | 0.0062 (7.33) | 0.0060 | 1.2e-59 |
| fp256 | rootn | int (3) | 40 of 40 | 0.0019 | 0.0001 | 0.0020 (8.98) | 0.0019 | 6.8e-60 |

**What it says** (MEASURED above; the desktop's samples, 120 lanes a
region at fp64 and 40 at fp128 and fp256, the cancelling zone's regions
among them): every region sampled is under 1 Bv. At fp64 the largest is
compound's `zone1000`, 0.194 Bv (2.37 bits of margin), then its
`zone12000`, 0.141, pow's `zone` and `rhoedge`, 0.118 and 0.116, and
pown's `zone1000` and `int1000`, 0.111 and 0.106; the logarithm's sum is
the largest part of each. The rest are at 0.0011 to 0.104. **At fp128 and
fp256 the bound is uniform,
2^-(p+G) |V_h|, and every region is under 0.0034 Bv at fp128 and 0.0063 at
fp256** (7.3 bits of margin and more), the cancelling zone at the largest
n on the main path included (`zone188000` 0.0034 and `zone2990000` 0.0062):
the double word holds the logarithm with room (2.2), the sum's capacity
there is 0, and the largest part is the method's own error M (the
polynomials planned at GL and GE): the capacities are 0.0001 to 0.0006 Bv,
and each region's measured worst is within 0.0004 of its M. The residual,
what first order leaves out, is under 4 x 10^-5 Bv everywhere, so the
first-order figures are the figures. **The regions `hugey` and `int63`
have no main-path lane:** every lane there is screened, |t| past the range
(2.6), so they test the screens and the sign (3.3), not the bound.
**The region `rhoedge`** (x where L is the polynomial alone at |r| near
rho, 3.3) is the one where GL is what holds the bound at fp128 and fp256:
0.0013 and 0.0023 Bv with GL as planned, and 124 Bv at fp128 with the
logarithm planned at G (the plant `log_short`).

**These are sampled figures** (send-back 1): each capacity is a maximum
over the lanes sampled, so a sampled budget is a lower bound on its
region's, and a region whose worst lanes are rare says little at 120
lanes. In the design before send-back 1 (no |Y k| term), the desktop's 120
lanes said 0.317 Bv for pown(x, 1000) (1.66 bits, "the least margin"),
0.201 for pow's `rhoedge` and 0.021 to 0.104 for the regions where |t| is
large (`no-b2/`); the box's said 0.802 and 1.052 for compound(x, 1000) at
2,000 and 10,000 lanes, 0.547 for pown(x, 1000) at 10,000, and 0.586, 0.477
and 0.419 for pow's `negint`, `rhoedge` and `redb` at 2,000 (MEASURED by the
lead on amd-arc-box, `box-1119/`). Each of those is the cancelling zone's
(3.6, item 9), which the sampled regions reached a few lanes at a time.
**The fixed design at the box's volume** (MEASURED on amd-arc-box, the
lead's run of `box_m3s_sb1.sh` at b4698a80, 14:45 to 15:51, every job rc
0, `box-sb1/`; bound + residual, 10,000 lanes, seed 3): fp64, compound's
`int1000`
0.374 and `zone12000` 0.183, pown's `int1000` 0.156 and `zone12000`
0.143, pow's `negint`, `redb`, `rhoedge` and `zone` 0.180, 0.133, 0.146
and 0.187, every one under 1 Bv. The largest, compound's `int1000` at
0.374 (1.42 bits of margin), is above the desktop's sampled largest
(0.194, `zone1000`): its log-sum is 0.157, under the cell-by-cell bound,
and its low word's and polynomial's parts are 0.104 and 0.079 (the zone
regions' at 2,000 lanes: 0.021 and 0.050); which lanes set them is not
traced here. The plant at the box's volume:
`int1000` 1.052 Bv, red, the design before's figure exactly; `zone12000`
at 20,000 lanes 0.943, under 1. fp128 at most 0.0036 (pow's `zone`) and
fp256 0.0072 (compound's `zone2990000`), the log-sum's capacity 0 in
each: no growth there. fp64's regions at the first box run's sizes (the
zone's among them) and the census at 3,000 lanes a family: 0 wrong
unmarked. The desktop's view at 2,000 lanes, `zone-curve/`: compound's
`zone12000` 0.182 Bv, its plant 0.942.
The zone's top alone (`zone12000`, every lane's gh near 0.9) keeps the
plant under 1, where `int1000` passed it and so did `zone1000`, which
draws over the whole zone (1.015 Bv at 150 lanes, `n-scan/`): a
rounding's capacity counts on every lane once some lane of the region
makes it inexact, and the lanes whose gh is under 1/2 make the sum's last
subtraction (e - ngl, exact wherever S = k + gh is) inexact, so its
capacity on the top's lanes joins the sum there; the analytic bound below
counts it either way.
fp64's first two B1 are in `first-b1/` and `second-b1/` (3.6, item 6),
and its budgets before the |Y k| term in `no-b2/`.

**The bound beyond the sample: the logarithm's sum, analytically**
(COMPUTED, `zonebound.py`, `zonebound.out.txt`). The sum's five roundings
(m3pow.py's `log-sum`: fe + L_l; that less the polynomial's low part; F
(1/ln 2)'s two FMAs; e - ngl) each have capacity |dV/dv| ulp(v)/2, with
dV/dL = V ln 2 Y and dL/dv 1/ln 2 for the first two (natural-log units)
and 1 for the rest. On every lane whose k is -1 and |x| < 1, their
magnitudes are bounded by the words' (|F| < 0.64 and the table's L_j <=
ln(16/9), so fe, L_l and F (1/ln 2)'s residual are at most 2^-54; S = k +
gh is exact where gh >= 1/2, and below, Fast2Sum's error e is at most
ulp(S)/2 = 2^-54, which leaves e - ngl in the same binade: send-back 2,
VM3S's note), and their ulp/2 sum to at most U = 7.885 2^-106 in L. So:
- **in the design before send-back 1,** Bv/|V| = 2^-97 + n |L| 2^-100 for
  pown and compound (|t| = n |L|), and the sum's capacity at the zone's
  top, |L| = 0.0871, is at most ln 2 U n / (2^-97 + 0.0871 n 2^-100) =
  **0.0854 n / (8 + 0.0871 n) Bv**: 0.247 at n = 31, 0.898 at n = 1000,
  0.973 at n = 12,000, 0.980 as n grows. The top stays on the main path
  while 0.0871 n
  < 1,077, so the **worst n is about 12,000** (12,364 the last). The box's
  0.725 for compound(x, 1000) at 10,000 lanes was approaching its 0.898,
  and with the rest of the budget (M 0.064, the low word's 0.134 and the
  polynomial's 0.110 there) the bound passes 1. MEASURED, the scan of n in
  that design (the plant `zone_bound_off`, 150 lanes of the region
  `zone<N>` an n, `n-scan/`): the sum's sampled capacity compound 0.21 at n
  = 31, 0.43 at n = 100, 0.63 at n = 300, 0.75 at n = 1,000, 0.56 at n =
  3,000, 0.57 at n = 10,000, 0.46 at n = 12,000, 0.03 at n = 13,000; pown
  0.13 at n = 31, 0.26 at n = 100, 0.38 at n = 300, 0.46 at n = 1,000, 0.54
  at n = 3,000, 0.37 at n = 10,000, 0.46 at n = 12,000, 0.02 at n = 13,000
  (each a lower bound, 150 lanes): it rises from n = 31 to near its largest
  by n = 1,000 and stays there, in the samples' scatter, to n = 12,000; at
  13,000 no zone lane is on the main path;
- **with the |Y k| term,** Bv/|V| >= |Y k| 2^-101, so the sum's capacity
  is at most ln 2 U / 2^-101 = **0.171 Bv** on every such lane, whatever n
  and L; for compound, whose 1 + x's low word adds four roundings of the
  same scale (r_l = u_l 2^-k c, r_l (1 + r)^-1, the Newton steps for
  (1 + r)^-1, and the polynomial's low part less r_l's correction), at
  most **0.231 Bv**, taken cell by cell: each of the reduction's cells C =
  9 to 16 in the zone (found by bisection on the model's c = C/16) with
  its own c, F, r and least |L|, and Bv/|V| >= |Y| (|L| B1 + B2). The top
  cell, C = 9, is the largest (U = 12.5 2^-106, |L| >= 0.0871); the others
  are at most 0.175, and C = 16 (c = 1, the zone's bottom) 0.098, since
  its |L| is near 1. Over the whole zone with c <= 1 and the |L| B1 term
  left out, the same count gives 0.478 Bv, conservative because the
  largest c and the largest F do not meet (COMPUTED, `zonebound.out.txt`).
  The first count said 0.219 on c <= 9/16, which holds only in the top
  cell, and with the Newton steps' term near 0; send-back 2 found it.
  Where k = 1, or |k| >= 2, L does not cancel and |t| B1 carries the
  sum's error as it did.
The sampled figures these bound, the fixed design's sum's capacity in the
zone's regions: compound's `zone1000` 0.122, compound's `zone12000` 0.069,
pow's `zone` 0.074, pown's `zone1000` 0.073, pown's `zone12000` 0.056,
compound's `zone12000` at 2,000 lanes 0.088, pow's `zone` at 2,000 lanes
0.087 Bv, each under its bound (0.171). The rest of each zone budget (M, the
product, the
exponential) is sampled only: 0.024 Bv at most on the desktop.

### 3.3 Measured against it

**The pools against transcend.py** (`pools_run.py`; the vector sets' and
the stage's pools of 1.3, deduplicated; every attribute; a failure is an
unmarked lane that differs in bits or flags):

| format | function | lanes | marked (rne / rtz / rdn / rup / rmm) | refused | wrong unmarked |
|---|---|---|---|---|---|
| fp64 | pow | 794 | 129 / 108 / 108 / 108 / 129 | 0 | 0 |
| fp64 | powr | 823 | 100 / 79 / 79 / 79 / 100 | 0 | 0 |
| fp64 | pown | 4260 | 530 / 481 / 481 / 481 / 530 | 0 | 0 |
| fp64 | rootn | 4058 | 76 / 51 / 51 / 51 / 76 | 202 | 0 |
| fp64 | compound | 4260 | 316 / 284 / 284 / 284 / 316 | 0 | 0 |
| fp128 | pow | 746 | 146 / 125 / 125 / 125 / 146 | 0 | 0 |
| fp128 | powr | 775 | 115 / 94 / 94 / 94 / 115 | 0 | 0 |
| fp128 | pown | 4131 | 643 / 603 / 603 / 603 / 643 | 0 | 0 |
| fp128 | rootn | 3941 | 79 / 51 / 51 / 51 / 79 | 190 | 0 |
| fp128 | compound | 4131 | 423 / 384 / 384 / 384 / 423 | 0 | 0 |
| fp256 | pow | 746 | 152 / 131 / 131 / 131 / 152 | 0 | 0 |
| fp256 | powr | 775 | 120 / 99 / 99 / 99 / 120 | 0 | 0 |
| fp256 | pown | 3204 | 497 / 467 / 467 / 467 / 497 | 0 | 0 |
| fp256 | rootn | 3014 | 72 / 47 / 47 / 47 / 72 | 190 | 0 |
| fp256 | compound | 3204 | 322 / 297 / 297 / 297 / 322 | 0 | 0 |

**The regions** (`regions.py`, `regions_run.py`): both operands over their
whole ranges, by the corners the brief lists - x from the least subnormal
to the largest finite and near 1 (`wide`, `sub`, `near1`); y from the least
subnormal (`tinyy`) to past 2^p (`hugey`); the overflow and underflow edges
with both signs of the result (`edge`, `negedge`); t near the reduction's
boundaries, odd sixteenths and integers (`redb`); |t| tiny (`small`); a
negative x with odd and even integer y, |y| up to 2^(p+4) (`negint`); x in
[0.941, 0.965] with large |t|, where M1's reduction leaves L to the
polynomial alone at |r| near its rho, the logarithm's weakest point
(`rhoedge`, added after the plant `log_short` was green in every other
region: 3.6, item 8); |x| (1 + x for compound) in the reduction's
cancelling zone, [1/2, 241/256), mostly near its top, at the worst n
(`zone`, `zone1000`, `zone12000`, and at fp128 and fp256 `zone188000` and
`zone2990000`, the largest n whose zone top is on the main path: send-back
1, 3.6 item 9); and n at 3, -3, 17, 1000, 2^31 - 1 for the integer-operand
functions (`int`, `int-neg`, `int17`, `int1000`, `int31`) - every lane
against transcend.py under every attribute:

| format | function | region | lanes | marked (rne / rtz / rdn / rup / rmm) | wrong unmarked |
|---|---|---|---|---|---|
| fp64 | pow | wide | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | near1 | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | edge | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | redb | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | small | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | negint | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | sub | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | tinyy | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | hugey | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | negedge | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | rhoedge | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pow | zone | 400 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | wide | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | near1 | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | edge | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | redb | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | small | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | sub | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | tinyy | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | hugey | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | rhoedge | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | powr | zone | 200 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | int | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | int-neg | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | int17 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | int1000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | int31 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | zone1000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | pown | zone12000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | rootn | int | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | rootn | int-neg | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | rootn | int17 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | rootn | int1000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | rootn | int31 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | int | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | int-neg | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | int17 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | int1000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | int31 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | zone1000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp64 | compound | zone12000 | 150 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | wide | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | near1 | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | edge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | redb | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | small | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | negint | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | sub | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | tinyy | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | hugey | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | negedge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | rhoedge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pow | zone | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | wide | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | near1 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | edge | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | redb | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | small | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | sub | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | tinyy | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | hugey | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | rhoedge | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | powr | zone | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | pown | zone188000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | rootn | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | rootn | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | rootn | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | rootn | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | rootn | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp128 | compound | zone188000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | wide | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | near1 | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | edge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | redb | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | small | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | negint | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | sub | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | tinyy | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | hugey | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | negedge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | rhoedge | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pow | zone | 80 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | wide | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | near1 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | edge | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | redb | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | small | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | sub | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | tinyy | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | hugey | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | rhoedge | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | powr | zone | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | pown | zone2990000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | rootn | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | rootn | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | rootn | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | rootn | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | rootn | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | int | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | int-neg | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | int17 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | int1000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | int31 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |
| fp256 | compound | zone2990000 | 40 | 0 / 0 / 0 / 0 / 0 | 0 |

**n at int64's extremes** (MEASURED): the budget's region `int63` (pown at
n = -2^63, fp64) finds 0 main-path lanes of 120 tried
(`budget.fp64-pown-int63.out.txt`), as 2.6 computes: every x but +-1 is
screened there; the pools' and section 4's lanes at n = 2^63 - 1, -2^63,
2^62 and -2^62 - 1 are the specials and the screens, 0 wrong.

**On seq.py** (`onseq.py`; each fragment scheduled and run by
`routines.program` and `routines.run`, x in r0 and y in r1; the pools, the
integer functions at n in {2, -2, 3, 17, 2^63 - 1, -2^63}; each lane's
result and flag word against the model's own run and against
transcend.py):

| format | function | programs | lanes on seq.py (each attribute) | differing from the model | wrong unmarked | most live |
|---|---|---|---|---|---|---|
| fp64 | pow | 1 | 794 | 0 | 0 | 30 |
| fp64 | powr | 1 | 823 | 0 | 0 | 23 |
| fp64 | pown | 6 | 904 | 0 | 0 | 21 |
| fp64 | rootn | 6 | 904 | 0 | 0 | 19 |
| fp64 | compound | 6 | 904 | 0 | 0 | 22 |
| fp128 | pow | 1 | 746 | 0 | 0 | 30 |
| fp128 | powr | 1 | 775 | 0 | 0 | 22 |
| fp128 | pown | 6 | 870 | 0 | 0 | 21 |
| fp128 | rootn | 6 | 870 | 0 | 0 | 19 |
| fp128 | compound | 6 | 870 | 0 | 0 | 22 |
| fp256 | pow | 1 | 746 | 0 | 0 | 30 |
| fp256 | powr | 1 | 775 | 0 | 0 | 22 |
| fp256 | pown | 6 | 728 | 0 | 0 | 21 |
| fp256 | rootn | 6 | 728 | 0 | 0 | 19 |
| fp256 | compound | 6 | 728 | 0 | 0 | 22 |

So every fragment fits seq.py's 32 registers as `routines.program` places
it, pow's 30 values live included, and seq.py and the model agree lane for
lane (MEASURED, the table).

**Errors against mpmath** are the budget's measured worsts above (each
region's largest |V - f| / Bv, f by mpmath at 6p + 300 bits): the largest
is 0.0471 Bv at fp64 (compound's `zone1000`), 0.0031 at fp128 (compound's
`zone188000`) and 0.0060 at fp256 (`zone2990000`), each under its region's
bound, as the tool's own
soundness check requires, and each a lower bound on its region's worst.

### 3.4 How often a lane is marked

**The law** (PROPOSED, as M1's and M4's, lane by lane): a lane is marked
where its interval [V - Bv, V + Bv] holds a boundary of the attribute, so
with V's position in its ulp spread, the probability is 2 Bv / s, s the
boundaries' spacing at R: ulp(R) under rtz, rdn and rup (the grid points),
ulp(R)/2 under rne and rmm (the midpoints and, by the "may be exact" test,
the grid points too). With Bv = 2^-(p+G) |V| and s = ulp(R) = 2^(e-p+1)
for |V| in [2^e, 2^(e+1)), that is (COMPUTED)

    2 Bv / s = 2^-G sig(V) a call under rtz, rdn and rup,
               2^-(G-1) sig(V) under rne and rmm,

sig(V) the significand of V in [1, 2); the same formula for each of the
five, whose Bv has one form: 2^-44 to 2^-42.8 at fp64 under the
directed three for |t| up to 1 where k = 0, G being G(t) of 2.2 there
(36.9 at the top of the range, so up to 2^-35.9), and up to 0.63 bits
more where |k| >= 1 outside the cancelling zone and 2.75 at its top (the
|Y k| term, 2.2); 2^-46 to 2^-45 at fp128 and fp256.
**rne and rmm mark twice as often as the directed three:** the "may be
exact" test adds the grid points to the midpoints. The exact family and
the families of 3.5 come on top.

**Measured with the bound inflated** (`rate.py`, `rate.fp64-pow-wide.out.txt`:
G' = 8, the bound 2^36 times its own, 600 lanes of the region `wide`,
seed 3, the law's count summed lane by lane from each lane's own Bv and R):

| attribute | marked | the law | z |
|---|---|---|---|
| rne, rmm | 436 | 456.6 | -0.96 |
| rtz, rdn, rup | 309 | 320.3 | -0.63 |

The law holds within one sigma here, the |Y k| term in each lane's Bv
(the design before it: 363 against 388.4 and 208 against 221.7, z -1.29
and -0.92). At fp128 and fp256 G' = 8 leaves
too few marks to test (fp128: 4 against 3.4 and 3 against 1.7 in 300
lanes, `rate.fp128-pow-wide.out.txt`), so the law is also measured at
G' = 2 (`rate.fp*-pow-wide-g2.out.txt`):

| format | lanes | rne and rmm: marked, the law, z | rtz, rdn and rup: marked, the law, z |
|---|---|---|---|
| fp128 | 300 | 202, 216.3, -0.97 | 109, 108.2, +0.08 |
| fp256 | 200 | 153, 145.3, +0.64 | 75, 72.6, +0.28 |

(At G' = 2 fp64's lanes are near probability 1 under the law, 293 marks
against 299.7 in 300, so fp64's test is G' = 8's above.) The law holds
within one sigma at fp128 and fp256.

At the true G no
lane of pow's regions marked (3.3: 0 marks in 400 lanes x 11 regions x 5
attributes at fp64), as a rate near 2^-43 predicts.

### 3.5 The structured families

The plan of record says pow's structured cases "need 2p to 3p bits". Named
and counted here (`census.py`, every lane under the five attributes
against transcend.py, classed by transcend.py's own exactness test:
**rep** an exact representable value, **mid** a midpoint, **exo** an exact
value with no boundary, **irr** no exact value, **range** an exact value
past the format):

At fp64, 300 lanes a family (`census.fp64-*.out.txt`), every attribute,
0 wrong unmarked lanes in every family:

| family | lanes and classes | under rne and rmm | under rtz, rdn and rup |
|---|---|---|---|
| **intpow**: an integer y from 2 to (p + 1)/bits(M) + 2, x = +-M 2^E with M odd and short | rep 215, mid 6, irr 79 | rep: 169 marked, 46 decided (the powers of two); mid: all 6 marked; irr: all decided | rep: 169 marked, 46 decided; mid: all 6 decided (no boundary); irr: all decided |
| **root2k**: y = Y/2^k (k = 1 to 3), x a perfect 2^k-th power | rep 176, mid 1, irr 123 | rep: 119 marked, 57 decided (powers of two); mid: marked | rep: 119 marked, 57 decided; mid: decided |
| **pow2**: x = +-2^E over the whole range, y an integer, a short dyadic or a p-bit value | rep 73, range 69, irr 158 | all 300 decided, none marked | all 300 decided |
| **near1**: x = 1 +- k ulp, k < 9, y with t about golden's 2^-(p+3), both sides of it, pow and powr | irr 600 | all decided (the rule beside 1) | all decided |
| **dominant**: compound(x, n), x = M 2^e, M in {1, 3, 5, 7}, vexp(x) from p + 2 + bits(n) up, n in {2, 3, -1, -2, 5} | irr 300 | 188 marked, 112 decided | 188 marked, 112 decided |
| **edges**: x^y within half an ulp to 2 ulps of the largest finite or of the subnormal grid's least points | irr 300 | all decided | all decided |
| **smallint**: pown, rootn and compound at n = +-2, +-3 on short odd parts | rep 166, irr 134 | rep: 140 marked, 26 decided | rep: 140 marked, 26 decided |

**The family that needs 3p bits** (`census.fp64-hard3p.out.txt`, 400
lanes): x = 1 +- k ulp and y = +-(1 +- j ulp), k from 1 to 8 and j from 0
to 8, whose value sits within about u^3 of the grid point 1 -+ k u (the
pools' own comment, on pow(1 + u, -(1 + u)), bounds that family at 3p
bits: READ in vectors.py's `transcend_pow_pairs`): 388 of the 400 have no exact value and **all 388 mark under
rne and rmm, 337 under the directed three** (51 decided, their distance
from the grid point past the bound); the 12 exact ones (y = 1) are decided;
0 wrong. At fp128, 194 of 194 under rne and rmm and 162 under the directed
three (`census.fp128-hard3p.out.txt`, 200 lanes); at fp256 the same counts
(`census.fp256-hard3p.out.txt`). Only a precision of about 3p decides this family, so the routine
marks it, as the plan of record expected of pow's structured cases.

**The pools' marks, by class** (`poolmarks.py`, `poolmarks.fp64.out.txt`,
fp64, rne and rtz): pow marks 66 exact representable lanes and 63 (rne) or
42 (rtz) with no exact value; pown 267 and 8 midpoints and 255 or 214;
rootn 35 and 41 or 16; compound 222 and 4 midpoints and 90 or 62. The
marked lanes with no exact value are **the 2p family**: (1 +- k u)^n and
(1 +- k u)^(+-1 +- j u), which sit within about u^2 of the grid point
1 +- n k u; sqrt of 4^j (1 + u), within u^2 of 2^j (1 + u/2); 1/x for x one
ulp from a power of two; and pow(maxN, -1), whose value 2^-1024 (1 +
2^-53 + ...) is next to a grid point at precision p in the scaled domain
though the subnormal grid it rounds on is coarser (a conservative mark: the
main test runs at precision p). Each needs about 2p bits to decide, more
than G at every format, so each marks, every guess counted.

What the census says, family by family:
- **The exact cases mark, but the powers of two** (rep and mid, MEASURED
  above): 169 of intpow's 215, 119 of root2k's 176, 140 of smallint's
  166; every power-of-two exact case is decided in-lane (pow2: 73 of 73
  representable and 69 of 69 past the range, at every attribute: the
  brief's must-have, the in-lane exactness rule against golden's own rule
  on lanes that reach it), and no other exact representable lane is
  decided unmarked but y = 1's, x itself (2.7, item 2): the census's own
  count, 0 in every family but hard3p, whose 12 exact lanes are y = 1's
  (60 lane-attributes). Every marked exact case is a replay; its guess
  has the right value under rne and rmm and the inexact flag set (the
  "guess wrong" counts of the outputs).
- **The midpoints** mark under rne and rmm and are decided under the
  directed three, where a midpoint is no boundary (intpow's 6, root2k's 1).
- **Beside 1** nothing marks: the rule answers from the signs.
- **compound's dominant operand** marks where the correction (1 + 1/x)^n
  is under the bound, 188 of 300: transcend.py decides those by
  `_round_dyadic_side`; the routine marks them (deciding them would need
  to know x^n is exact, the exact family's question).
- **The edges** (x^y next to the largest finite or the subnormal grid)
  decide without a mark at this size: they are boundaries of the scaled
  domain like any other, and the rate law covers them.
- **What marking costs:** a replay of the lane on the host with the
  definition (transcend.py), one host evaluation a marked lane. A program
  whose lanes are small integers raised to small integer powers replays
  nearly every lane; a program of measured data almost none (the rate law,
  3.4). Question 4.

### 3.6 What the model found wrong in itself

Nine things, in the order found (the ledger has each with its time; the
ninth is send-back 1's):
1. **The first design was wrong and unmarked at a tiny y** (a design
   defect; MEASURED, then fixed). With y down to the least subnormal, t = y
   log2|x| underflows: for pow(1.2, minSub) at fp64, t_h rounds to 0, V is
   exactly 1, and under rup the routine answered 1 where transcend.py
   answers 1 + 2^-52; so did pow(1.2, -minSub) and pow(5/6, minSub) under
   rtz and rdn and pow(5/6, -minSub) under rup: 6 wrong of 30 lanes (x in
   {1.2, 5/6, 1.5}, both signs of minSub, five attributes), a scratch check
   recorded in the ledger; the committed evidence is the plant
   `side_rule_off`, which is the first design (8). The first design
   cleared the mark beside 1 and let V's own rounding answer, which is right
   only while t_h keeps t's sign. **No pool and no region of the first
   model reached it:** the pools pair minSub only with x whose |log2 x| is
   at least 0.5, where t_h rounds to a subnormal of the right sign, and the
   regions placed y by t. It is M4's lesson again (M4S's send-back 1: a
   corner outside every region). Fixed by answering the lane by
   transcend.py's own rule beside 1, from the operands' signs (2.7, 3.1;
   8 instructions); held by the region `tinyy` and the plant
   `side_rule_off` (8), which is the first design.
2. **y's integrality was wrong in one band** (a design defect; MEASURED by
   the region `negint`, then fixed): the first design read y's integrality
   and parity by MAGIC's rounding for every |y| < 2^(p-1), but y + MAGIC
   passes 2^p once |y| >= 2^(p-2), its ulp is 2 there, and the units bit is
   lost: an odd y was read as even (the result's sign lost) or an integer as
   not one (invalid). 25 wrong unmarked lanes of 400 x 5 at fp64, e.g.
   pow(-(1 + 0x389 ulp), 0x43285fac64090d34), an even y near 2^51.6,
   answered -2^994.2 (0xfe16479f8cc1a483) where transcend.py answers
   +2^994.2 (`regions_run.fp64-pow-first.out.txt`, the first design's run,
   kept beside the rerun). The pools reach no |y| in
   [2^(p-2), 2^(p-1)) with x < 0 (their integer y stop at 1000 and jump to
   2^p), and the first specials' rows had 2^p - 1, the next band. Fixed by
   a band of its own (2.5); the plant `integrality_wide` is the first
   design.
3. **compound(x, 1) answered -0 at x = -1 under rdn** (a defect of the
   n = 1 fragment; MEASURED in the first fp64 pool run, 1 lane). 1 + (-1)
   is -0 under roundTowardNegative; 9.2.1's row is +0. Fixed by the x = -1
   row in that fragment. The same fact rules out the compiler rewrite
   compound(a, 1) -> 1 + a (section 6).
4. **The budget froze V_l** (a defect of the tool's port; MEASURED, then
   fixed): the tree's inverse-function budget counts every phase but
   "final", "special" and "classify" as before V, and the fixed grid reads
   V_l with a CMPEQ (its round-to-odd), so V_l was frozen as data and the
   reverse sweep stopped there: a method error of 10^12 Bv on lanes whose
   measured error was 0.05 Bv. The inverse functions have no fixed grid;
   M1's budget of its six functions counts it after V. `budget.PowAnalyzer` reads the fixed grid
   as "final"; the residual (3.2) is the tell that it is right.
5. **A niced run starved** (a method finding; MEASURED): under the
   desktop's load a niced pool run printed nothing in 8 minutes where the
   same run unniced takes 35 s, as the round's memory notes for
   2026-10-28. The runs were made unniced, one at a time but for the eight
   short probes the ledger names.
6. **fp64's B1 was set twice by the budget** (a design figure; MEASURED):
   2^-103 first, from the double word's 2^-106 with room, left 0.48 bits in
   the region `negint` (0.719 Bv, `first-b1/`); 2^-102 was past 1 Bv for
   pown(x, 1000) (1.063 Bv, the log's sum alone 0.89, `second-b1/`). The
   cause, read from the budget's parts and the reduction: k + log2 m'
   cancels by up to 3.4 bits for x just below 1, and the sum's roundings
   stay relative to the larger term. 2^-100 is the value 3.2 holds; the
   re-centred reduction of question 3 (a') would remove the cancellation.
7. **A negative result rounding to zero came out +0** (a design defect;
   MEASURED by the region `negedge`, then fixed): on the fixed grid the
   offset is taken off by a subtraction, and Cu - Cu is +0 under every
   attribute but rdn, so pow(x < 0, odd y) whose value rounds to zero
   answered +0 with underflow where transcend.py answers -0: 506 wrong
   unmarked lanes of 400 x 5 at fp64, e.g. pow(-67.6, -177) under rne
   (`regions_run.fp64-pow-second.out.txt`, the run before the fix, kept).
   Fixed by IOR of the sign word into the fixed grid's result (one
   instruction where the sign can be negative); the plant
   `zero_sign_lost` is the first design (152 wrong of 600 in a scratch
   check, 0 after: the ledger).
8. **No region reached the logarithm's weakest point** (a gap in the
   model's regions; MEASURED by a plant, then fixed): the plant
   `log_short` (the logarithm planned at G, not GL) was green in the region
   `wide` at fp128 (0.0008 Bv), because a random x almost never lands where
   L is the polynomial's term alone with |r| near rho (x in [0.94, 0.97],
   M1's cell C = 16) and |t| is large. The region `rhoedge` puts it there:
   the plant is 124 Bv, the design 0.0013 at fp128 (0.0023 at fp256; at
   fp64 0.201 at the desktop's 120 lanes in the design before send-back 1,
   and 0.477 at the box's 2,000, `rhoedge` straddling the cancelling zone's
   top: item 9). A plant that could not fail on the regions given would
   have hidden a design whose GL was too small.
9. **fp64's bound was not shown sound in the reduction's cancelling zone**
   (a design defect; found by the lead's box runs at 2,000 and 10,000
   lanes, send-back 1; MEASURED there and on the desktop, then fixed). With
   Bv = |V_h| (2^-97 + |t_h| 2^-100), compound(x, 1000)'s first-order budget
   was 0.137 Bv at the desktop's 120 lanes, 0.802 at 2,000 and 1.052 at
   10,000 on amd-arc-box (`box-1119/`), its log-sum capacity 0.725 of it;
   pown(x, 1000)'s 0.547 at 10,000; pow's `negint`, `rhoedge` and `redb`
   0.586, 0.477 and 0.419 at 2,000. No wrong unmarked lane was seen (the
   box's worst 0.239 Bv; the desktop's, the plant on the zone at 2,000
   lanes, 0.353). Each of those budgets is the zone's: |x| (1 + x for
   compound) in
   [1/2, 241/256), where M1's reduction takes k = -1 and log2 m' up to
   0.913, so L cancels to -0.0871 and the sum's roundings, absolute at log2
   m''s scale, outgrow |t| B1 by up to 11.5 times for a large |Y| (3.2's
   analytic bound: 0.0854 n / (8 + 0.0871 n) Bv for the sum alone, 0.898
   at n = 1000). The desktop's regions drew x log-uniformly, so a 120-lane
   region held a few zone lanes and its capacities, maxima over the lanes,
   rarely met the zone's worst. The worst n is about 12,000, the largest
   whose zone top is still on the main path (3.2). Fixed by the term
   |Y_h k| B2 (2.2); held by the regions `zone` and `zone<N>` and the plant
   `zone_bound_off`, the design before (8); at the box's 10,000 lanes the
   fix holds every fp64 region under 1 Bv, compound's `int1000` the
   largest at 0.374, and the plant is red at `int1000`, 1.052 Bv (3.2,
   `box-sb1/`).

No defect in transcend.py was found: every lane compared equal where the
routine did not mark, and the nine above are the model's own. Four of them
(items 1, 2, 7 and 9) are design defects that every pool passed and that
only a region placed by the operands' own ranges reached, the fourth only
at the box's volume: the brief's warning, which M4's verifier proved on
M4's study, held here four times.

## 4. The specials and the flags

PROPOSED, each row a SELECT over the main path's answer, lowest priority
first, in the order transcend.py's tests run, reversed (READ). MEASURED,
`specials.py`: every row below, on the lanes named, at fp64, fp128 and
fp256 under all five attributes, against transcend.py in bits and flag
word; a row passes when no lane is wrong and unmarked, and its marks are
counted (they are the exact family's, below, none a special row's).

**pow** (highest priority last):
1. the main path's answer, its flags (inexact; underflow with inexact where
   tiny; overflow with inexact), the mark;
2. **the screens:** t_h0 >= emax + 2, the attribute's overflow response
   with the result's sign, overflow and inexact; t_h0 <= emin - p - 2, the
   underflow response (a quarter of the smallest subnormal, rounded, signed),
   underflow and inexact;
3. **y = 1:** x itself, no flag;
4. **x < 0 and y not an integer:** the quiet NaN, invalid;
5. **x = +-inf:** +inf for y > 0 and +0 for y < 0, negative where x = -inf
   and y is an odd integer; no flag;
6. **x = +-0:** for y < 0, +inf (-inf where x = -0 and y is odd) with
   divideByZero; for y > 0, +0 (-0 where x = -0 and y is odd); no flag;
7. **y = +-inf:** 1 where |x| = 1 (pow(-1, +-inf) = 1), +inf where |x| > 1
   and y = +inf or |x| < 1 and y = -inf, +0 otherwise; no flag (so
   pow(+-0, -inf) is +inf with no divideByZero, this row being above the
   zero row);
8. **a NaN in either operand:** the quiet NaN, no flag;
9. **y = +-0, or x = +1:** 1, no flag, even for a quiet NaN in the other;
10. **a signalling NaN in either:** the quiet NaN, invalid, in every row.

**powr:** the main path; the screens; y = 1; y = +-inf (+inf or +0 by |x|
and y's sign); y = +-0 (1); x = +1 (1, invalid for y = +-inf); x = +inf
(+0, +inf, invalid for y = +-0); x = +-0 (+0 for y > 0; +inf with
divideByZero for finite y < 0, silent at -inf; invalid for y = +-0); a NaN
(quiet, no flag); x < 0, -inf included, before a quiet NaN exponent
(invalid); a signalling NaN (invalid).

**pown, rootn and compound** (n a constant of the build): the zeros and
infinities by n's sign and parity (section 1.3's rows), rootn's x < 0 with
an even n invalid, compound's x = -1 (+inf with divideByZero for n < 0, +0
for n > 0), x < -1 invalid, x = +-0 (1), and n = 0 and 1 by the small
fragments (2.7).

**No clamp** (M2's |sin| < 1 had one): a result is never computed past its
format's range on the main path, since the screens take every t whose
result would be, and the scaling's one rounding answers the overflow
response itself between them; the rule beside 1 answers 1's neighbour from
constants. MEASURED, below.

| function | row (specials.py's name) | lanes | fp64: wrong, marked | fp128: wrong, marked | fp256: wrong, marked |
|---|---|---|---|---|---|
| pow | y = +-0 (pow: 1, even x = NaN; powr: finite x > 0) | 32 | 0, 0 | 0, 0 | 0, 0 |
| pow | x = +1 (pow: 1, even y = NaN; powr: finite y) | 15 | 0, 0 | 0, 0 | 0, 0 |
| pow | x = -1 and y = +-inf | 2 | 0, 0 | 0, 0 | 0, 0 |
| pow | a sNaN in either operand | 7 | 0, 0 | 0, 0 | 0, 0 |
| pow | a qNaN in either, no row above | 9 | 0, 0 | 0, 0 | 0, 0 |
| pow | x = +-0, y < 0 (odd, even, non-integer, -inf) | 12 | 0, 0 | 0, 0 | 0, 0 |
| pow | x = +-0, y > 0 | 14 | 0, 0 | 0, 0 | 0, 0 |
| pow | x = +-inf | 24 | 0, 0 | 0, 0 | 0, 0 |
| pow | y = +-inf, |x| < 1 and > 1 | 16 | 0, 0 | 0, 0 | 0, 0 |
| pow | x < 0 finite, y not an integer | 28 | 0, 0 | 0, 0 | 0, 0 |
| pow | x < 0, y odd integer (sign kept), across y's bands | 55 | 0, 34 | 0, 34 | 0, 34 |
| pow | x < 0, y even integer, y past 2^p | 30 | 0, 20 | 0, 20 | 0, 20 |
| pow | y = 1: x itself (exact) | 9 | 0, 0 | 0, 0 | 0, 0 |
| pow | subnormal operands | 5 | 0, 5 | 0, 5 | 0, 5 |
| pow | overflowing and underflowing results | 13 | 0, 0 | 0, 0 | 0, 0 |
| powr | y = +-0 (pow: 1, even x = NaN; powr: finite x > 0) | 32 | 0, 0 | 0, 0 | 0, 0 |
| powr | x = +1 (pow: 1, even y = NaN; powr: finite y) | 15 | 0, 0 | 0, 0 | 0, 0 |
| powr | x = -1 and y = +-inf | 2 | 0, 0 | 0, 0 | 0, 0 |
| powr | a sNaN in either operand | 7 | 0, 0 | 0, 0 | 0, 0 |
| powr | a qNaN in either, no row above | 9 | 0, 0 | 0, 0 | 0, 0 |
| powr | x = +-0, y < 0 (odd, even, non-integer, -inf) | 12 | 0, 0 | 0, 0 | 0, 0 |
| powr | x = +-0, y > 0 | 14 | 0, 0 | 0, 0 | 0, 0 |
| powr | x = +-inf | 24 | 0, 0 | 0, 0 | 0, 0 |
| powr | y = +-inf, |x| < 1 and > 1 | 16 | 0, 0 | 0, 0 | 0, 0 |
| powr | x < 0 finite, y not an integer | 28 | 0, 0 | 0, 0 | 0, 0 |
| powr | x < 0, y odd integer (sign kept), across y's bands | 55 | 0, 0 | 0, 0 | 0, 0 |
| powr | x < 0, y even integer, y past 2^p | 30 | 0, 0 | 0, 0 | 0, 0 |
| powr | y = 1: x itself (exact) | 9 | 0, 0 | 0, 0 | 0, 0 |
| powr | subnormal operands | 5 | 0, 5 | 0, 5 | 0, 5 |
| powr | overflowing and underflowing results | 13 | 0, 0 | 0, 0 | 0, 0 |
| powr | powr: x < 0 (every y, qNaN included) | 20 | 0, 0 | 0, 0 | 0, 0 |
| powr | powr: +-0 to +-0, +inf to +-0, +1 to +-inf | 8 | 0, 0 | 0, 0 | 0, 0 |
| pown | pown: x specials and neighbours of +-1, 0 and the range against n at 0, +-1, +-2, +-3, 4, +-17 and int64's extremes | 308 | 0, 166 | 0, 186 | 0, 260 |
| rootn | rootn: x specials and neighbours of +-1, 0 and the range against n at 0, +-1, +-2, +-3, 4, +-17 and int64's extremes | 308 | 0, 29, 110 refused | 0, 29, 110 refused | 0, 29, 110 refused |
| compound | compound: x specials and neighbours of +-1, 0 and the range against n at 0, +-1, +-2, +-3, 4, +-17 and int64's extremes | 308 | 0, 74 | 0, 94 | 0, 94 |

(Each count over the row's lanes under all five attributes, "marked" the
sum of the five; MEASURED, `specials.fp64.out.txt`, `specials.fp128.out.txt`
and `specials.fp256.out.txt`, the table made from them by `tables.py`;
pow's rows run for powr too, where powr's own table differs, and pow's
y's-bands rows mark only for pow, powr's x < 0 being invalid.) **0 wrong unmarked lanes at every format.** The
marks are the exact family's, not the special rows': pow(-3, 3) = -27,
pow(-1.375, 2) and the like in the integer rows; pown, rootn and compound
of 1 +- ulp at n = +-1 and +-2 and of +-3 (exact squares and cubes); the
"subnormal operands" row's one mark a configuration is (3 2^-53)^3 =
27 2^-159, an exact case, while its subnormal lanes (minSub to the 1/2, a
power of two decided in-lane; minSub to 1 + ulp and to -1) are decided.
Every fragment's flag word stays within the math library's set by C4's
walk (`routines.invariants` under `MATH_CONTRACT`, 5.1): no flag word
outside it, the mark only with inexact.

## 5. The cost

### 5.1 Measured

MEASURED (`costs.py`, `costs.fp64.out.txt`, `costs.fp128.out.txt`,
`costs.fp256.out.txt`): instructions of the scheduled fragment under rne,
rtz, rdn, rup and rmm; bank words (rne's); values live at once, scheduled
(the tree's `schedule_order`) and in the design's order. Every fragment
passes `routines.invariants` under the math library's contract
(`MATH_CONTRACT`, no live cap): well formed, its flag words within the
marked set, no instruction reading only the inputs, nothing left to
simplify, its attributes RNE, RTZ, RDN, RUP and the program's
(MEASURED, the same runs: no invariant printed).

| fragment | fp64 | fp128 | fp256 | words (fp64 / fp128 / fp256) | most live, scheduled (design's order) |
|---|---|---|---|---|---|
| pow | 429 to 434 | 484 to 489 | 535 to 540 | 129 / 157 / 202 | 30 (39), 30 (40) |
| powr | 407 to 413 | 462 to 468 | 513 to 519 | 125 / 153 / 198 | 22 (36), 23 (37) |
| pown(x, 3) | 380 to 386 | 436 to 442 | 487 to 493 | 128 / 156 / 201 | 20 (29), 21 (30) |
| pown(x, -3) | 381 to 386 | 437 to 442 | 488 to 493 | 128 / 156 / 201 | 20 (29), 21 (30) |
| pown(x, 2) | 368 to 375 | 424 to 431 | 475 to 482 | 125 / 153 / 198 | 21 (27), 21 (28) |
| rootn(x, 3) | 381 to 387 | 437 to 443 | 488 to 494 | 127 / 155 / 200 | 19 (28), 19 (29) |
| rootn(x, 2) | 373 to 380 | 429 to 436 | 480 to 487 | 125 / 153 / 198 | 18 (27), 18 (28) |
| compound(x, 3) | 404 to 410 | 463 to 469 | 514 to 520 | 126 / 153 / 198 | 22 (29), 22 (30) |
| compound(x, -1) | 403 to 410 | 462 to 469 | 513 to 520 | 125 / 152 / 197 | 22 (29), 22 (30) |
| pown(x, 0) | 6 | 6 | 6 | 7 / 7 / 7 | 2 (2) |
| pown(x, 1) | 6 | 6 | 6 | 6 / 6 / 6 | 3 (3) |
| compound(x, 1) | 25 to 26 | 25 to 26 | 25 to 26 | 10 / 10 / 10 | 7 (7) |

(Instructions: the least and the most over the five attributes, rne and
rmm the most, the "may be exact" test's; the table made by `tables.py`
from the outputs.) **No scratch slot:** the fragments
are ALU instructions only (READ, m3pow.py builds through mathlib.Build,
which has no LDX or STX, and `routines.program` runs them with none, 3.3).
**By part,** pow at fp64 under rne
(MEASURED, the instrumented build's labels over the instructions the
fragment keeps): the logarithm 159 (reduction 19, table 17, polynomial
107, the sum 16), 37 %; the exponential 120 (reduction 11, table 17, scale
15, polynomial 64, reconstruction 13), 28 %; the product t = y L 11; the
test 17 (the bound's |t| and |Y k| terms among them), the fixed grid 26,
the scaling and flags 17, the exact power of two 10 and the rule beside 1
5 (75 in all, 17 %); the classification 14,
y's integrality and the sign 19, the specials 36 (69, 16 %). The
logarithm's polynomial is the largest single part: GL = 47 needs K = 12
double-word steps (M1's log2 at G = 44 has 11, READ in plan_log's
docstring), and 63 and 67 at fp128 and fp256 need 16 and 17.

**Against the routines it is built from** (MEASURED, `tw32_ref.out.txt`):
M1's log2 and exp2 under rne are 180 and 178 instructions at fp64, 202 and
186 at fp128, 232 and 199 at fp256, so 358, 388 and 431 together; pow
under rne is 434, 489 and 540, 76, 101 and 109 more (COMPUTED): the
logarithm planned finer, the product, two operands' classification, y's
integrality and the sign, the exact and beside-1 rules, pow's specials and
fp64's bound terms, less one final rounding and test.

### 5.2 Live values, and the proposed caps

pow keeps **30 values live** at fp64, fp128 and fp256 (rne and rmm; 28
under the directed three), where powr keeps 22 (23 at fp64, with send-back
1's |Y k| term) and the integer-operand functions 19 to 22 (MEASURED,
5.1). The eight more are
pow's: y's classification and integrality and the sign's conditions,
computed from x and y at the start and read by the specials at the end,
live across the whole main path in each of the scheduler's three orders.
30 of seq.py's 32 registers fit `routines.program`'s harness (MEASURED,
`onseq.py`, 3.3), but a compiled program has no register to spare beside a
pow call: M4C measured the first spill beside a call at 30 less the
routine's cap (11 other values beside atan2's 19, 5 beside fp32's 25: READ
in M4's study's note on M4C), which is 0 for pow's 30, so every value live
across a pow call spills (ESTIMATE, by that rule; cftc's allocator is not
run here).
`sched.py` measures a fourth order, depth-first from the result before
the flag word: at fp128 and fp256 it keeps 28 under rne and rmm, where the
scheduler's choice keeps 30, and 29 under the directed three, where it
keeps 28; at fp64, with the |Y k| term, 31 under every attribute, where
the choice keeps 30 and 28 (it kept 29 and 30 before the term) (MEASURED,
`sched.fp64.out.txt`, `sched.fp128.out.txt`, `sched.fp256.out.txt`). The
better of the two for each attribute would cap pow at 28 at fp128 and
fp256 and leave it at 30 at fp64: the conditions are read at both ends of
the fragment whatever the order, and the count is the design's, not the
scheduler's.

PROPOSED, `LIVE_CAP` rows at fp64, fp128 and fp256 (question 8): pow 30,
powr 23 at fp64 and 22 at fp128 and fp256, pown 21, rootn 19, compound
22; fp32's when it is measured (2.8).
pow's is the largest of the round's (M2's 26, M4's 19 at fp64, READ in
routines.py).

### 5.3 What C4's invariants need widened

Nothing beyond the thirteen's (MEASURED, 5.1: `routines.invariants` under
`MATH_CONTRACT` passes for every fragment of the table at every attribute,
the live cap aside). What is new is not an invariant but the routine
machinery's keys: the integer-operand fragments are keyed by n as well
(6), and pow and powr are the second and third routines of two inputs
after atan2.

### 5.4 What cftc's inliner can share

COMPUTED from the fragments by their dataflow keys (`share.py`; cftc's
inliner hash-conses on opcode, attribute and operands):

| pow(x, y) with ... | fp64: shared, together (apart) | fp128: shared, together (apart) | fp256: shared, together (apart) |
|---|---|---|---|
| pow(x, z), the same x | 173, 695 (868) | 217, 761 (978) | 255, 825 (1080) |
| pow(w, y), the same y | 29, 839 (868) | 29, 949 (978) | 29, 1051 (1080) |
| powr(x, y) | 329, 518 (847) | 384, 573 (957) | 435, 624 (1059) |
| pown(x, 3) | 170, 650 (820) | 214, 717 (931) | 252, 781 (1033) |
| rootn(x, 3) | 170, 651 (821) | 214, 718 (932) | 252, 782 (1034) |
| log2(x), M1's | 9, 605 (614) | 9, 682 (691) | 9, 763 (772) |
| log(x), M1's | 10, 610 (620) | 10, 687 (697) | 10, 768 (778) |
| exp2(x), M1's | 7, 605 (612) | 7, 668 (675) | 7, 732 (739) |
| pown(x, 5) against pown(x, 3) | 177, 595 (772) | 221, 663 (884) | 259, 727 (986) |

(MEASURED counts, `share.fp64.out.txt`, `share.fp128.out.txt` and
`share.fp256.out.txt`, the table made by `tables.py`; the last row is two
pown calls, pown(x, 5) beside pown(x, 3).) So **calls on the same x
share the logarithm** (173, 217 and 255 instructions at fp64, fp128 and
fp256, the reduction, the table and the polynomial: 40 to 47 % of pow),
pow and powr of the same operands share 329 to 435 instructions (76 to
81 % of pow), and two powers of one base cost 1.5 to 1.6 calls, not 2
(COMPUTED from the table). **They share almost nothing with M1's routines** in the same
program: the core's logarithm reduces |x| (pow's x may be negative) where
M1's log2 reduces x, so even the reductions differ by their first
operand, and the polynomials are planned at another guard (GL and GE
against M1's G). PROPOSED for the build: powr's and compound's front ends,
whose x is never negative on the main path, may reduce x itself; that
shares M1's log2 or log1p reduction and table with a program that calls
both (ESTIMATE about 40 instructions a pair; not measured).

## 6. The language and the compiler

PROPOSED, golden-first as M1's, M2's and M4's section 6, on the language
at 1.3 (docs/LANGUAGE.md) and `python/cft_golden/lang/check.py` (READ).

**What the language does today** (READ, check.py): `MATH` holds the
thirteen; `TRANSCENDENTAL` reserves pow, pown, powr and rootn (with hypot,
cbrt, rsqrt and others), so a call is refused `transcendental`, and of
constants `irrational-constant` ("has no exact rational value in general");
`compound` is in neither, so a program may name a value `compound` today;
`^` and `**` are refused as `power` ("write x * x for a square",
syntax.py's `_power`); exp2 of an integer constant folds, 2 to a
non-integer power is `irrational-constant`, a logarithm's pole is
`constant-division-by-zero`, and an exponent past 2^20 is `constant-range`
(`_fold_math`, `LIMIT_LOG2`).

**The nodes** (PROPOSED):
- `pow(a, b)` and `powr(a, b)`, two operands, **a first** (x then y), as C
  and transcend.py have it; atan2 was the first built-in of two operands.
- `pown(a, n)`, `rootn(a, n)` and `compound(a, n)`: **n an integer
  constant** (a literal or a `const` whose value is an integer) in int64's
  range (2.6, question 2). A non-integer constant, a value outside
  [-2^63, 2^63 - 1], or a run-time value is refused by a new name,
  `integer-operand`: "n must be an integer constant within int64: pown,
  rootn and compound take an integer, which a lane does not hold". rootn(a,
  0) is invalid for every a (transcend.rootn, READ) and is refused at
  compile time as `irrational-constant` with the sentence "not a real
  number: rootn of order 0 has no value" (the domain refusal the language
  already gives asin(2)).
- **`^` and `**` stay refused** as `power`, the sentence gaining "or
  pow(x, y)". An operator would need a precedence and an associativity
  that C does not have and Fortran and Python give differently, and it
  would not say which of pow, powr and pown it means.
- **`compound` becomes reserved** with the build, as every built-in is. A
  source naming a value `compound` would be refused from 1.4: MEASURED, no
  committed source does (no `*.cftl` file of the tree's 76 contains the
  word, `git ls-files` and a search), and LANGUAGE.md's promise that a
  source accepted at 1.3 is accepted at 1.4 needs that one exception
  stated (question 10).

**The folds and refusals for constant arguments** (PROPOSED, question 7),
in exact rationals as the language's constants are, consistent with exp2's
and the logarithms' rows:

| call of constants | folds to | refused |
|---|---|---|
| pow(c, d) | 1 at d = 0 (any c, 0 included) and at c = 1; 0 at c = 0, d > 0; c^d where c >= 0 is a rational's s-th power for d = r/s in lowest terms (pow(4, 1/2) = 2, pow(8, 2/3) = 4); c^d for c < 0 and an integer d | `constant-division-by-zero` at c = 0, d < 0 (+inf with divideByZero at run time); `irrational-constant` "not a real number" for c < 0 and d not an integer (a NaN with invalid at run time); `irrational-constant` where c^d is irrational (pow(2, 1/2)); `constant-range` past 2^+-2^20, as exp2's |n| > 2^20 |
| powr(c, d) | as pow for c > 0; 0 at c = 0, d > 0 | "not a real number" for c < 0 and for powr(0, 0), as at run time (invalid); `constant-division-by-zero` at c = 0, d < 0 |
| pown(c, n) | c^n, exactly (always rational); 1 at n = 0 | `constant-division-by-zero` at c = 0, n < 0; `constant-range` past 2^+-2^20 |
| rootn(c, n) | c^(1/n) where |c| is a perfect |n|-th power (numerator and denominator), the sign of c for an odd n; c at n = 1 | "not a real number" for c < 0 and an even n, and for n = 0; `constant-division-by-zero` at c = 0, n < 0; `irrational-constant` elsewhere |
| compound(c, n) | (1 + c)^n, exactly; 1 at n = 0 for c >= -1 | "not a real number" for c < -1; `constant-division-by-zero` at c = -1, n < 0 |

pow(2, d) folds exactly where exp2(d) does (at the integers, d = r/s with
s > 1 being irrational since 2 is no perfect power), so the two rows agree;
pow(c, d) for d = 1/3 folds pow(8, 1/3) = 2 as the language's exact
rational semantics give it, though a run-time pow(8, RN(1/3)) is not 2:
the constant expression is the exact one (question 7 names this).

**The rewrites of a constant exponent** (PROPOSED, question 4): where the
exponent is a constant and the answer is an existing operation BIT AND
FLAG equal on every lane, cftc writes the operation and no routine.
MEASURED (`rewrites.py`, every x of the pow and integer pools, five
attributes):

| constant exponent | rewrite | lanes differing from transcend.py (311 x values x 5 attributes, fp64) |
|---|---|---|
| pow(a, 2), pown(a, 2) | a * a | 0, 0 |
| pow(a, 1), pown(a, 1), rootn(a, 1) | a * 1 (MUL by one: a signalling NaN raises invalid as the routine's row does) | 0, 0, 0 |
| pow(a, -1), pown(a, -1), rootn(a, -1) | 1 / a, C4's division | 0, 0, 0 |
| rootn(a, 2) | sqrt(a): **not proposed** | 5: rootn(-0, 2) is +0, sqrt(-0) is -0, under each attribute |
| compound(a, 1) | 1 + a: **not proposed** | 416: among them every x < -1 of the pools (1 + a a number where compound is invalid) and x = -1 under rdn (1 + a is -0, compound +0) |
| pow(a, 0.5) | sqrt(a): **not proposed** | 10: pow(-0, 0.5) is +0 and pow(-inf, 0.5) is +inf, under each attribute |

The eight proposed rewrites take the two exponents programs write most
(2 and -1) and the identity out of the routine: pow(a, 2) is one MUL
where the routine is 434 to 540 instructions and marks every exact square
(3.5). They are exact because each is a single correctly rounded operation
of the same exact value: a^2 is x^2 rounded once, as pow(a, 2) is, and so
for 1/a. The three not proposed differ where the measurement says, the
signed zero, the infinity and compound's -1 under rdn (3.6, item 3), and
stay routines.

**cftc** (PROPOSED, question 10):
- `ROUTINES` gains pow and powr (two inputs, ("a", "b") = (x, y)) and
  pown, rootn and compound (one input, the fragment keyed by n as well:
  `routines.fragment(op, fmt, rnd, n)`), each with its `LIVE_CAP` row
  (5.2); the call loop takes a routine of two inputs already (atan2's, M4C);
- the targets: the fragments inline where the node stands, as the
  thirteen's do; the rewrites above before inlining; the output version
  steps 8 to 9 and the language 1.3 to 1.4, with the certificate corpus
  remade;
- what the inliner shares is 5.4's: two pow calls with the same x share
  the logarithm's instructions, and with the same y the classification of
  y; with M1's log2(x) and exp2 in the same program they share almost
  nothing (9 and 7 instructions), the core reducing |x| and planning its
  polynomials at another guard.

## 7. The derivative rules

PROPOSED (question 9). Each rule is written with the language's own
operations, so its every rounding is fixed by the text, as M1's, M2's and
M4's are:

| node | tangent rule | at the edges |
|---|---|---|
| pow(a, b) | `(b * pow(a, b - 1)) * da + select(a == 0, 0, pow(a, b) * log(a)) * db` | a = 0: the da term is b 0^(b-1): 0 for b > 1, da itself at b = 1 (pow(0, 0) = 1), an infinity for b < 1 but 0, where the derivative is infinite, and at b = 0 a NaN (0 times pow(0, -1) = +inf) where the derivative of the constant 1 is 0, the rule's one NaN where a derivative exists; the db term is 0 (0^b = 0 for every b > 0). a < 0 (b an integer): log(a) is a NaN, honestly, since pow of a negative base has no derivative in b; the term is dropped where b is a constant, the derivation's db being 0 |
| powr(a, b) | the same with powr | a < 0 is a NaN in the primal already |
| pown(a, n) | `n * pown(a, n - 1) * da`, n - 1 an exact integer constant | n = 0: the rule is 0; n = -2^63: n - 1 leaves int64, refused `integer-operand` in the derivative (the primal stands) |
| rootn(a, n) | `pown(rootn(a, n), 1 - n) * da / n` | a = 0, n > 1: pown(0, 1 - n) is +inf, the derivative's infinity; n = 1 is da; n = -2^63: 1 - n leaves int64, refused as pown's |
| compound(a, n) | `n * compound(a, n - 1) * da` | n = 0: the rule is 0 (compound(a, 0) is 1); a = -1 with n < 1, n != 0: compound(-1, n - 1) is +inf with divideByZero, the derivative's pole; n = -2^63 as pown's |

**The cost of the rules:** each reads a second call of the routine
(pow(a, b - 1) beside pow(a, b)), since the step graph gives a node one use
(M4SL's note 4, READ in M4's study). b * pow(a, b) / a would reuse the
primal and is a NaN at a = 0 where the derivative is 0 or finite; the
select form above is the honest one at the cost of a call (question 9).

**The reference system** (PROPOSED, for the check as the pendulum is M2's
and the phase follower M4's): a body falling through a power-law
atmosphere with drag, the shape of JB2008's and NRLMSISE-00's density laws
(cft-debris's request 4),

    h' = v
    v' = -g + k * pow(1 + h / H, -4.5) * v * abs(v)
    m' = -c * pown(v, 3)

with g, H, k and c constants: pow with a non-integer constant exponent and
a state-dependent base (pow's da rule), pown's rule in the third, at fp64
and fp256, rounding rdn as M4's reference, compiled and
committed with its bytes; the tangent's central-difference check at 2^-64
within 2^-100 as asin's (M4L's note 2), since the rules hold powers whose
central difference loses bits.

## 8. How it will be held

PROPOSED, for M3's build, M4's section 8 item for item; agents run the
quick tests and the long runs are the lead's.

1. **Each fragment on seq.py against transcend.py,** as a stand-alone
   program through `routines.program` and `routines.run` (pow and powr with
   x in r0 and y in r1), over the vector sets' pools
   (`vectors.transcend_pow_pairs`, `transcend_powr_pairs`,
   `transcend_int_pow_cases`) and the stage's (`transcend_check.pow_pairs`,
   `powr_pairs`, `int_pow_cases`), at every format and attribute: every
   unmarked lane equal in bits AND flag word, every marked lane replayed and
   its guess counted. MEASURED as a probe (`onseq.py`, 3.3).
2. **The corners the pools do not reach,** as committed sets: every region
   of 3.3 (`regions.py`: both operands over their whole ranges, x near 1
   with large y, y from the least subnormal (`tinyy`) and past 2^p
   (`hugey`), the overflow and underflow edges with both signs of the
   result (`edge`, `negedge`), t at the reduction's boundaries (`redb`), a
   negative x with odd and even integer y (`negint`), the logarithm's
   weakest point (`rhoedge`), the reduction's cancelling zone at the worst
   n (`zone`, `zone<N>`), n at int64's extremes), on the model and on
   seq.py; the first design's tiny-y lanes (3.6, item 1) among them by
   name.
3. **The bound, against an independent reference,** mpmath at 4p + 200
   bits, at each region's own worst points; |V - f| / Bv under 1, the
   margins stated by the budget (3.2), the sampled worst only as the lower
   bound it is. The budgets over larger samples are the lead's on
   amd-arc-box.
4. **The mark-rate law** with the bound inflated (3.4), by each lane's own
   2 Bv / s, every unmarked lane right and every marked guess counted.
5. **The structured families as committed lists** (3.5): the exact cases
   that mark, by family, with their neighbours (one ulp of x or y away,
   which must not mark); the exact powers of two that must NOT mark; the
   lanes beside 1 at golden's 2^-(p+3) and the routine's gate, both sides;
   compound's dominant operand at its threshold vexp(x) = p + 2 + bits(|n|)
   and one below; the tie at half the smallest subnormal. A mark in the
   pools off the lists fails the test (E1's rule).
6. **The exact-case rule against golden's own** (the brief's must-have, M4RR's
   lesson): over every lane where transcend.py's `_pow_dyadic`,
   `_pown_dyadic` or `_rootn_dyadic` returns a power of two, at every
   attribute, the in-lane rule must decide it (unmarked and right); over
   every lane where they return another dyadic, the lane must be marked or
   right, and right with the inexact flag clear where representable
   (census.py's classes, 3.5).
7. **The constants** re-derived with a `--check`: the logarithm's and the
   exponential's coefficients at GL and GE, 1/ln 2 and ln 2 in two words,
   the table words (M1's checks extended), B1, the screens' thresholds, the
   neighbours of 1 under each attribute, n's words and 1/n's.
8. **The 9.2.1 tables** row by row, both signs of every zero and infinity,
   at every format and attribute (`specials.py`'s rows, section 4).
9. **program.c bit for bit** through `host/tests/seq_check.py`'s routine
   corpus; no new C.
10. **The language's checks:** the lang-routines stage with sources using
    the five, the rewrites' equality (section 6) as a test over the pools,
    the tangent stage's rules, the committed reference (7), test_lang.py's
    refusal table (pow(-8, 1/2), pow(0, -1), rootn(x, 0), pown(x, 2.5),
    pown(x, 2^63)).
11. **The card later:** STATUS[6] and the lane byte on a structured
    argument (pow(3, 2) under rtz marks by design), and the acceptance
    set's case with the reference system.

**The plants,** each in a fresh fragment and each red in a named case
(`plants.py`, `budget.py` with a plant; MEASURED at fp64 and fp256 unless
the row says otherwise). A case is **lane** (the plant's answer is wrong
and unmarked where the control's is right or marked), **mark** (the
control decides the lane in-lane and the plant marks it: the test "these
lanes are decided" fails), or **budget** (the region's bound past 1 Bv with
the plant, under 1 without).

| plant | the fault | kind | the named case at fp64 (`plants.fp64.out.txt`, `budget.*`) | fp256 |
|---|---|---|---|---|
| exact_unmarked | the "may be exact" test removed | lane | pow(3, 2) rne: 9 with inexact, unmarked (transcend: 9, no flag); pow(10, 3) the same | red |
| exact_rule_off | the in-lane power-of-two rule removed | mark | pow(2, 10) rtz and pow(0.5, 3) rne marked, where the control decides them | red |
| exact_rule_no_tl | rootn's form of the rule (t_l not tested) on pow | lane | pow(2^1000, RN(3/1000)) rne: 8 with no flag (transcend: 8, inexact) | red |
| bound_loose | Bv 2^40 times too small | lane | pow(0x3ff80016dc000000, 2), a midpoint near 2.25, rne: decided on V's side, wrong | red |
| midpoint_unmarked | the fixed grid's midpoint test removed | redundant | equal to the control on pow(3 2^-215, 5), a subnormal midpoint: the "may be exact" test marks it (3.1); not counted | no lane |
| pow_zero_nan | pow(qNaN, +-0) answered NaN | lane | pow(qNaN, 0) rne: NaN (transcend: 1) | red |
| pow_one_nan | pow(1, qNaN) answered NaN | lane | pow(1, qNaN) rne: NaN (transcend: 1) | red |
| sign_even | y's parity read from bit 1 | lane | pow(RN(-1.1), 2) rne: -1.21 (transcend: +1.21) | red |
| sign_odd_lost | an odd y's sign dropped | lane | pow(RN(-1.1), 3) rne: +1.331 (transcend: -1.331) | red |
| zero_sign_lost | the first design: a negative zero result answered +0 (3.6, 7) | lane | pow(-2^-4, 269) rne: +0 (transcend: -0, underflow) | red |
| integrality_wide | the first design: MAGIC's band to 2^(p-1) (3.6, 2) | lane | pow(-(1 + ulp), 2^51 + 1) rne: NaN, invalid (transcend: -1.65..) | red |
| powr_neg_ok | powr's x < 0 row removed | lane | powr(-2, 0.5) rne: 1.414.. (transcend: NaN, invalid) | red |
| powr_zero_zero | powr(+-0, +-0) answered 1 | lane | powr(0, 0) rne: 1 (transcend: NaN, invalid) | red |
| rootn_m0_neg | rootn(-0, 2) answered -0, squareRoot's row | lane | rootn(-0, 2) rne: -0 (transcend: +0) | red |
| compound_onep_rounded | 1 + x rounded before the logarithm, its low word dropped | lane | compound(RN(0.1), 3) rne: two ulps off | red |
| near_one_gate_off | the gate beside 1 removed | mark | pow(1 + ulp, 2^-60) rtz marked, where the control decides it | red |
| side_rule_off | the first design beside 1: V's rounding (3.6, 1) | lane | pow(1.2, minSub) rup: 1 (transcend: 1 + 2^-52); pow(5/6, minSub) rtz: 1 | red |
| screen_low | the overflow screen at emax + 1, not emax + 2 | lane | pow(21, 0x406d244c78367a0d), t_h0 = 1024 exactly, rne: +inf with overflow (transcend: 0x7feffffffffffecd, inexact) | red |
| mark_silenced | the mark never set | lane | pow(3, 2) rtz: 9 - ulp, unmarked (transcend: 9) | red |
| bound_tight | fp64's |t| and |Y k| terms dropped (a uniform 2^-97) | budget | the region `edge`: 2.78 Bv (`budget.fp64-pow-edge-bound_tight.out.txt`) | - |
| zone_bound_off | the design before send-back 1: fp64's |Y k| term dropped (3.6, 9) | budget | compound's region `int1000` at 10,000 lanes, seed 3: past 1 Bv at the box's volume as the design it reproduces (1.052 Bv, `box-1119/`; the plant's 2,000-lane run equals that design's box run, 0.802349 Bv against the box's 0.802349, `zone-curve/`); its own 10,000-lane run on the box, 1.052026 Bv (`box-sb1/`); red on the desktop at compound's `zone1000`, 1.015 Bv at 150 lanes (`n-scan/`), and under 1 at `zone12000` (0.753 at 120 lanes, 0.942 at 2,000) | - |
| log_short | the logarithm planned at G, not GL | budget | fp128's region `rhoedge`: 124 Bv (2^6.96), the control 0.0013 (`budget.fp128-pow-rhoedge-log_short.out.txt`); not red in `wide` (0.0008), where the table term carries L | - |

The brief's ten: an exact case left to the enclosure (exact_unmarked); a
midpoint (bound_loose; near 1 no bound below the ulp of V_l can leave a
midpoint unmarked, since V's own error is below the test's resolution
there, so its lane is near 2.25: the first search, near 1, found none);
pow(x, +-0) and pow(1, y) with a quiet NaN (pow_zero_nan, pow_one_nan); a
negative base's sign at an odd and an even y (sign_odd_lost, sign_even);
powr's invalid rows (powr_neg_ok, powr_zero_zero); rootn(-0, 2)
(rootn_m0_neg); compound's exact 1 + x (compound_onep_rounded); the rule
beside 1 (side_rule_off, near_one_gate_off); an overflow edge (screen_low);
the mark (mark_silenced, and bound_loose). The control is red in nothing:
every named case is right or marked without the plant. midpoint_unmarked
cannot be red in this design and is shown as such, not counted. In all:
eighteen lane and mark plants, red in their 21 named cases at fp64 and at
fp256 (`plants.fp256.out.txt`: 21 of 21; the subnormal midpoint lane of
midpoint_unmarked has no fp256 counterpart), and three budget plants:
bound_tight and log_short red in their regions on the desktop, and
zone_bound_off red on the desktop at compound's `zone1000` (1.015 Bv at
150 lanes, `n-scan/`) and at the box's volume as the design it
reproduces (1.052 Bv at `int1000`, 10,000 lanes); at the zone's top alone
(`zone12000`) it stays under 1 at 2,000 lanes.

## 9. Questions for Logan, each with a recommendation

Each with the options weighed and a recommendation; the figures are the
sections' named.

1. **The set, the core and the order.** Which of the five does M3 build,
   on how many cores, in what order?
   - (a) **All five on one core, in the order pow and powr, then pown,
     then rootn and compound (Recommended).** One fragment shape; the
     logarithm and the exponential are M1's code; the five differ in their
     front ends and their tables (2.1). cft-debris's request names pow
     first, and powr comes with it at no new arithmetic.
   - (b) pow, powr and pown only (cft-debris's "pow as a routine, or powr
     and pown"), rootn and compound later: the same core, two front ends
     fewer to hold.
   - (c) pow alone first.
2. **The integer operand.** How does pown's, rootn's and compound's n reach
   a lane?
   - (a) **A constant of the program only, checked in int64's range, a
     non-integer or run-time n refused `integer-operand` (Recommended):**
     the fragment is built for that n, its words in the bank (one word at
     fp128 and fp256, two at fp32 and fp64), its parity and sign the
     build's, rootn's 1/n in two words (2.6). Its cost: one or two bank
     words an n, a fragment an n (cftc keys the routine by n), and nothing
     in-lane; pown(x, 3) is 386 instructions at fp64 against pow's 434
     (5.1, MEASURED). No lane type changes.
   - (b) A run-time integer, carried as one or two format words a lane and
     its parity found in-lane as y's is (2.5): about pow's cost (the
     integrality's 15 instructions, an input of two words at fp32 and fp64,
     ESTIMATE about 440 instructions at fp64), and a new kind of lane value
     in the language, the host and the certificate, for no request that
     exists.
3. **G at fp64** (re-asked after send-back 1, with its evidence). The
   double word cannot hold G = 44 for every t: the logarithm needs 107
   bits where the double word holds 106 (2.2), and in the reduction's
   cancelling zone (|x| in [1/2, 241/256), k = -1) its error is absolute,
   about 2^-106 at log2 m''s scale, while L falls to -0.0871. The design
   the study first recommended, Bv = |V_h| (2^-97 + |t_h| 2^-100), held
   every region at the desktop's 120 lanes and failed its own method at
   the box's 10,000: compound(x, 1000) 1.052 Bv (3.2, 3.6 item 9), and
   its sum's capacity there is bounded only by 0.0854 n / (8 + 0.0871 n)
   Bv, 0.97 at the worst n (COMPUTED, 3.2).
   - (a) **The bound grows with |t| and with the reduction's k, Bv =
     |V_h| (2^-97 + |t_h| 2^-100 + |Y_h k| 2^-101) (Recommended):** G is
     43.8 at |t| = 1, 43.0 at |t| = 8, 40.8 at |t| = 64 and 36.9 at the
     top of the range where k = 0, at most 0.63 bits less where |k| >= 1
     outside the zone, and up to 2.75 bits less at the zone's top (Bv 6.7
     times the first design's there). Its cost, against a uniform bound:
     3 instructions for pown, rootn and compound and 4 for pow and powr,
     of which the |Y k| term is 2 and 3 and |t_h| B1 1, its fabs shared
     with the beside-1 test (MEASURED under rne: pow 434 and powr 413
     against the uniform bound's 430 and 409, the plant `bound_tight`, and
     the first design's 431 and 410; pown(x, 3) 386 against 383 and 384;
     5.1); and two bank words; marks unchanged where k = 0 and at most 1.55
     times the first design's elsewhere outside the zone (3.4). Its
     evidence: the sum's capacity bounded on every lane whose k is -1, at
     most 0.171 Bv, 0.231 for compound (COMPUTED by the reduction's cells,
     3.2), and the sampled
     budgets of the rest (fp64's largest 0.194 Bv, compound's `zone1000`,
     on the desktop's 120 lanes; at the box's 10,000 lanes 0.374,
     compound's `int1000`, 1.42 bits of margin, and the plant red there at
     1.052: MEASURED by the lead, `box-sb1/`).
   - (a') The re-centred reduction (m' in [1/sqrt 2, sqrt 2), a table of
     other cells): no cancelling zone (at most 1 bit), so no |Y k| term,
     and B1 about 2^-103, G 39.8 at the top (ESTIMATE): fewer marks than
     (a) at large |t|; its cost a reduction and a table of its own beside
     M1's (ESTIMATE 10 to 20 instructions and 8 to 16 bank words, and their
     check), and the sharing with M1's log2 that is already small (5.4).
   - (a'') No |Y k| term and B1 raised until the zone's top holds, about
     2^-97.3: the |Y k| term's 2 instructions fewer than (a), 3 for pow and
     powr, and 6.7 times (a)'s mark rate
     at large |t| on every lane, k = 0 included (COMPUTED from 2.2's
     ratios).
   - (b) A triple-word logarithm at fp64, G = 44 everywhere: ESTIMATE about
     2.2 times the logarithm's instructions (2.2), about 220 more a call
     (pow about 650 at fp64), and the triple word's live values.
   - (c) A uniform G at fp64: to hold the zone's top it would have to be
     about 35 (the sum's absolute error, 7.9 2^-106 in L, times |Y| up to
     12,364 and ln 2, at a quarter of Bv: COMPUTED), 3 instructions fewer
     than (a), 4 for pow and powr, and about 500 times its mark rate where
     |t| is small.
   - (d) B1 per function or per |n|: does not reach the cause, the
     reduction's k, which pow with a large y meets as pown and compound do;
     per |n| it would raise the bound for every x of a large n, the zone's
     and the rest.
4. **The exact family.** Practical programs hit x^2, x^3, x^0.5, x^1.5,
   2^y and 10^n constantly (3.5's census).
   - (a) **Decide in-lane only what is cheap and exact - a power-of-two x at
     an integer t, y = 1, n = 0 and 1 - mark every other exact case, and
     have cftc rewrite a constant exponent of 2, 1 and -1 into a * a,
     a * 1 and 1 / a, which equal transcend.py in bits and flags on every
     lane measured (Recommended).**
   - (b) Also an exact power by multiplication for small constant n (3 and
     4): about 30 to 60 instructions more for those n, a second algorithm
     with its own bound (2.1).
   - (c) Mark every exact case, the powers of two included: the simplest,
     and 2^n and 0.5^n would replay.
5. **fp32.** The inherited triple word at G = 40 (2.8):
   - (a) **Build it after fp64 to fp256, measured first as M2X measured
     M2's, its bound by Bv = |V_h| (2^-64 + |t_h| B1) as fp64's, and its
     evidence the box's samples and partial sweeps on the card: pow and
     powr every y at the nine x {0.5, 1 - 2^-24, 1 + 2^-23, 1.5, 2, 3, 10,
     2^-126, maxN} and every x at the nine y {-2, -1, -0.5, 0.5, 1.5, 2, 3,
     2^-20, 2^20}; pown, rootn and compound every x at n in {+-2, +-3, 17,
     2^31 - 1, -2^63} (Recommended).** As atan2's "Partial is acceptable".
   - (b) The double word at fp32 with a smaller G (M2's and M4's measured
     fallback was G = 18): cheaper, a mark rate near 2^-17.
6. **The "may be exact" test under rne and rmm** (2.7, 3.1): six
   instructions under those two attributes (two ADDs, a CMPLE and a SELECT
   in the main test, a CMPEQ and a SELECT in the fixed grid), without which
   an exact representable result is answered with the inexact flag,
   unmarked and wrong (the plant `exact_unmarked`). It also makes the fixed
   grid's own test redundant (8, the plant `midpoint_unmarked`), which the
   build may drop.
   - (a) **Keep it in-lane (Recommended).**
   - (b) No alternative keeps the flags right short of deciding every exact
     case in-lane (question 4 (b)).
7. **Constant arguments.** The folds and refusals of section 6's table:
   every exact case folds (pow(4, 1/2) = 2, pown(c, n) always,
   compound(c, n) always), every other constant is refused by name with
   the existing rows' words (`irrational-constant`, its "not a real number"
   form, `constant-division-by-zero`, `constant-range`), and pow(8, 1/3)
   folds to 2 as the language's exact constants give it.
   - (a) **As section 6 states it (Recommended).**
   - (b) Refuse pow of two constants whose exponent is not a format value
     (1/3), so that no fold gives what the run time could not.
8. **Live caps per function and format** (5.2): the measured values as
   each function's `LIVE_CAP` row (M4's answer 9 for the four).
   - (a) **The measured caps, as M4's (Recommended).**
   - (b) Reorder for fewer live values first: the fragments are about 2.4
     times exp2's, and a reorder by hand found M2's 26 at fp64.
9. **The derivative rules** of section 7, with the select form at a = 0
   and the falling body in a power-law atmosphere as the reference:
   - (a) **As section 7 (Recommended),** each rule reading a second call of
     the routine (pow(a, b - 1)); its one NaN where a derivative exists,
     a = 0 at b = 0, stated with the rule (a select on b = 0 would answer
     it, two operations more a node, ESTIMATE).
   - (b) b * pow(a, b) / a, one call fewer, a NaN at a = 0 where the
     derivative is 0 or finite.
10. **Versions:** cftc's output version 8 to 9 and the language 1.3 to
    1.4, `compound` reserved from 1.4 (no committed source uses the name,
    MEASURED), unless M3's build lands with another that steps them.
    - (a) **As stated (Recommended).**
11. **Out of scope** (2.9): exp10, exp10m1, log10, log2p1, log10p1, rSqrt
    and hypot. The core gives exp10 and exp10m1 for about 230 and 250
    instructions and the logarithms for about 200 to 240 (ESTIMATE).
    - (a) **Not in M3's build; a parcel of their own after it, if a
      workload asks (Recommended),** as M4's question 13 left the
      Pi-variants.
    - (b) exp10 and log10 in M3's build, on the core.

## 10. What M3's build builds, in order

PROPOSED, as M1's, M2's and M4's section 10, each item a parcel or a
part of one, each with its section 8 checks and the lead's gates:
1. **The core with pow and powr** in mathlib.py at fp64, fp128 and fp256
   under all five attributes, ported from `m3pow.py` (the model's fragments
   the reference, equal by dag digest): the logarithm at GL, the product,
   the exponential with a double-word argument, the sign, the in-lane
   power-of-two rule, y = 1, the "may be exact" test, the screens, both
   tables of specials, the plants of section 8, a `--check` of the new
   constants (GL's and GE's coefficients, B1 and B2, the screens' words),
   and the cancelling zone's regions among the committed sets.
2. **pown, rootn and compound** on the same core, their n-keyed fragments
   and the n = 0 and n = 1 fragments, the int64 words.
3. **fp32's triple word** (2.8), measured before it is built, as M2X
   measured M2's: the bound law at 3p, the live values against the 32
   registers, the partial sweeps' lists.
4. **program.c parity** through `host/tests/seq_check.py`'s routine corpus,
   two inputs for pow and powr as atan2's; no new C.
5. **The language at 1.4,** golden-first: the five nodes, n's constant
   rule and `integer-operand`, the folds and refusals of section 6,
   `compound` reserved, the rewrites, the derivative rules, the reference
   system, LANGUAGE.md.
6. **cftc's output version 9:** ROUTINES, the n-keyed fragments, the
   LIVE_CAP rows, the rewrites before inlining, the certificate corpus
   remade.
7. **The stages' legs:** lang-routines and tangent with the five, marked
   lanes replayed (the exact family marks by design: the legs' rule for
   "demanded" marks takes 3.5's list).
8. **The card, the lead's:** STATUS[6] and the lane byte on a structured
   argument of each function (pow(3, 2) under rtz marks by design), the
   revision-8 set's case with the reference system.
9. **fp32's sweeps on the card** (question 5's lists), as items of the
   nightly catalog.

## 11. The model

`docs/studies/m3/`, scratch beside the study as m1/, m2/ and m4/ are: not
the tree's code, and nothing in the tree imports it. Python 3.12 with
mpmath 1.3.0 on the desktop. Every fragment is built on the tree's
`mathlib.Build` and evaluated op by op through `softfloat.compute`
(`Build.run`), and the scheduled fragment runs on seq.py through
`routines.program` and `routines.run`.

| file | what it is | its outputs |
|---|---|---|
| `m3core.py` | paths, encodings, transcend.py's call, the true value at 4p + 200 bits (mpf values read through `_mpf_`; `to_man_exp` is not called) | |
| `m3pow.py` | **the design**: `plan` (G, GL, GE, B1) and `plan_b2` (B2, send-back 1), the one core `build` on `mathlib.Build`, the five front ends, the specials, `build_small` (n = 0 and 1), the plants (`PLANTS`) | |
| `m3harness.py` | the pools (the vector sets' and the stage's, deduplicated) and the comparison against transcend.py | |
| `pools_run.py` | every pool lane, model against transcend.py | `pools_run.*.out.txt` |
| `regions.py`, `regions_run.py` | the placed regions of 3.3, the cancelling zone's (`zone`, `zone<N>`) and `int<N>` among them, and their run against transcend.py | `regions_run.*.out.txt` (`-first`, `-second`: the first designs') |
| `onseq.py` | the scheduled fragments as programs on seq.py, against the model and transcend.py | `onseq.*.out.txt` |
| `specials.py` | section 4's rows | `specials.*.out.txt` |
| `budget.py` | the first-order budget (the tree's `mathlib_inv_budget.InvAnalyzer` by subclass) | `budget.*.out.txt`; `first-b1/`, `second-b1/`: fp64's earlier B1; `no-b2/`: fp64's before send-back 1's |Y k| term; `zone-curve/`: the zone at 2,000 lanes |
| `zonebound.py` | the cancelling zone's top by bisection on k, and the analytic bound of the logarithm's sum (3.2, send-back 1) | `zonebound.out.txt` |
| `rate.py` | the mark-rate law, bound inflated | `rate.*.out.txt` |
| `census.py` | the structured families | `census.*.out.txt` |
| `poolmarks.py` | the pools' marked lanes by class | `poolmarks.fp64.out.txt` |
| `plants.py` | the lane and mark plants of section 8 | `plants.*.out.txt` |
| `costs.py`, `sched.py`, `share.py` | 5.1, 5.2, 5.4 | `costs.*`, `sched.*`, `share.*.out.txt` |
| `rewrites.py` | section 6's rewrites against transcend.py | `rewrites.fp64.out.txt` |
| `bits.py`, `tw32_ref.py` | 2.2's table; M1's built fragments' sizes | `bits.out.txt`, `tw32_ref.out.txt` |
| `tables.py` | the study's tables, made from the outputs | |
| `complete.py` | that every captured run completed: no traceback, and its script's closing line (below) | `complete.out.txt` |
| `queue1.sh` to `queue5.sh` | the desktop's runs in order, one at a time (4 and 5: send-back 1's) | `queue1.log` to `queue5.log` (the first three's "rc": below) |
| `box_m3s.sh` | the larger samples, for the lead on amd-arc-box | the lead's (`box-1119/` holds three of them) |
| `box_m3s_sb1.sh` | send-back 1's larger samples: the fix and its plant at volume, the regions and the census at the box's sizes, fp128 and fp256 at their worst regions | the lead's run at b4698a80, `box-sb1/` |
| `box-sb1/` | that run's 37 outputs, copied in (MEASURED by the lead; `complete.py box-sb1` over them: 0 flagged, `complete.box-sb1.out.txt`) | |
| `box-1119/` | the lead's box outputs the study cites, copied in (MEASURED by the lead at d2bd90fa's model code, which the design before the |Y k| term is) | |

The model is 22 Python files and 7 shell scripts, 3,749 lines (COUNTED,
`wc -l` over `*.py` and `*.sh` at the study's commit), with 211 captured
outputs (`*.out.txt`; `first-b1/`, `second-b1/`, `no-b2/`, `zone-curve/`
and `n-scan/` among them), the lead's 53 box outputs in `box-1119/` (16)
and `box-sb1/` (37), and the five queue logs: 298 files in all.

**The first three queue logs' "rc" is not the runs' status** (found after
the study's first commit, in a review of the scripts): their wrapper read
`$?` inside the same `echo` as `$(date ...)`, which sets it, so every end
line says rc 0 whatever its run did (MEASURED on this desktop's sh: a
failing command logged through that form reads rc 0). The three scripts
now read it on its own line (MEASURED: failing commands then log rc 2 and
3), and their logs are kept as made, for their times; `queue4.sh` and
`queue5.sh` were written so, and their logs' rc is the run's: 0 for every
run but queue5's last, `complete.py`, rc 1, which had found one of its own
controls unflagged (its new pass check's pattern for the specials' rows
held a backspace where `\b` was meant); fixed, and rerun by hand for the
committed `complete.out.txt`. The runs are held by `complete.py`
(MEASURED, `complete.out.txt`): each of the 209 outputs it reads (all but
its own; not `box-1119/`) holds no traceback (the queues sent each run's
stderr into its output, and the runs made by hand were read as they ran),
closes with its own script's last line, or, for `poolmarks` and
`rewrites`, all its rows, and, since send-back 1 (VM3S's note 4: finished
is not passed), counts 0 wrong unmarked lanes and 0 lanes of seq.py
differing from the model wherever it counts them, the first designs' two
runs kept as evidence excepted; since send-back 2, no budget is at or past
1 Bv (its BOUND or its bound + residual) unless it is meant to be: run
with one of the model's budget plants, which budget.py names on its first
line (`PLANT bound_tight:`, `log_short`, `zone_bound_off`), or the earlier
design kept in `second-b1/` (1.063 Bv), named by its path; and no plants
output is short of all red. 29 of 29 controls (real outputs cut short,
emptied, given a traceback, a nonzero count, a BOUND or a bound +
residual past 1, a PLANT line of no budget plant, or 17 of 21 red, in
memory) are flagged, and the two first designs' runs and the two budgets
meant to be past 1 Bv (bound_tight's 2.78 and `second-b1/`'s) pass as
kept; and no queue run reached its
900 s timeout (the longest took 502 s, by the logs' own times). The box
scripts' last lines are no status either: `box_m3s_sb1.sh` ends by running
`complete.py OUTDIR` and exits with xargs's status, 0 only if every job's
was.

To rerun a figure: `python -B <script> <args>` from `docs/studies/m3/`, the
arguments as the queue scripts give them (the first line of each output
names its run).
