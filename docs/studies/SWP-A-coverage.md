# SWP-A: wider sweep coverage for the card's native-oracle soaks

**Date:** 2026-10-19. **Parcel:** SC, the research half of Logan's two-part request (EX, running beside it,
builds the exhaustive modes for the 32-bit spaces). **Status:** a design study. Nothing here is built; the
instruments in `docs/studies/swp-a/` measure or compute the claims and nothing under `host/`, `hw/`, `rtl/`,
`python/` or `programs/` changed. **Basis:** the card's 60-hour stress run, run id `card-stress-1016`,
2026-10-16 18:58 to 2026-10-19 08:01 on amd-arc-box, from its own final record (`metrics.jsonl`,
7,982,931 bytes, SHA-256 `e7989f88efded691ea7461e921840d8de5d449e069980f6ba92e6a8f87e007cc`; not in the
repository because of its size, held in the lead's scratchpad). The 06:55 report and the lead's rates file
that the brief names are kept beside the instruments as a cross-check, and agree with the final record
(section 2.1).

**Marks.** Every figure is one of: **MEASURED** (a run of mine, named), **READ** (a file or a page, named),
**COMPUTED** (arithmetic on those), **BELIEVED** (mine, unverified). A table's caption gives the mark of its
figures when it is the same throughout. A claim of the form "proved" is always qualified: PROVED *for the
golden model at a tiny format, by exhaustion*, or PLAUSIBLE *for the tile*, which no test here reaches.

## 0. The answer in a page

The weekend ran 3,287 sweep slices, 3,038 of them random and 249 exhaustive, with no disagreement
(MEASURED, section 2.1). It covered every encoding of 14 fp32 items and gave each of 53 of the 54 others 1.2 to
1.5 x 10^10 counts of banded random input (a count is the unit of section 2.2; rem64 got 1.8 x 10^9). This study asks what a card could be asked to cover instead, and how that could be made
to add up from weekend to weekend and from device to device. The findings, in the order they matter:

1. **The lead's finding is right, and it is worse in one way.** A run in a new output directory restarts every
   random item at slice 0 with the same seeds, and every exhaustive item at encoding 0: MEASURED on the real
   driver (section 2.4). At least about 96 per cent of a rerun's random draws would be repeats, and 98.8 per cent
   of the final run's random count sat in slices of the probe or cap size that a rerun reproduces
   (MEASURED, COMPUTED). Separately, both tools set `rng_state = seed | 1` while adjacent items' base seeds differ
   by one, so **96.2 per cent of the run's random slices started from a state another item's slice also started
   from**, and 88.6 billion operand counts were seen again by a second rounding mode of the same operation
   (36.9 to 37.3 per cent of conv64to32, div32, div64 and sqrt64) (MEASURED). Each such case is still a new
   (operand, mode) test, so the loss is modest and the fix is a line (section 2.4).
2. **Half the sweep did not touch the tile.** 33 of the 68 items are libcft host code (conversions, logB, next,
   class, remainder): the device argument is "context" (READ, `host/include/cft.h`, `host/src/clause5.c`), the
   software backend runs them at 0.79 to 1.91 times the card run's rate (MEASURED), and **52.5 per cent of the run's
   sweep job-seconds went to them** (COMPUTED). Their full sweeps need CPUs, not cards (sections 2.3, 6.2).
3. **A sampler cannot reach the cases that matter most at 64 bits, and they can be built.** The class "quotient
   closest to a rounding boundary" has probability about 3 x 10^-16 a draw at fp64: a weekend's 1.45 x 10^10 draws
   expect 4.3 x 10^-6 of them (COMPUTED). One modular inverse a divisor constructs them (MEASURED, 37 to 41 per
   cent of odd divisors, exact), the golden model agrees with an independent exact arbiter on them, and the repository's
   own known failure family (a = 1, b = 1 - ulp) is one. A planted division with 40 guard bits fails on 25.5 per
   cent of the constructed set and on none of 272,007 sampler draws (section 4.2).
4. **Proved reductions shrink some spaces by 10^3 to 10^5 and do nothing for others.** Sign, directed-mode and scale
   symmetries (PROVED for the golden model at e4m3 by exhaustion, with the argument for p = 24 and 53 written out) take
   fp32 division from 3.0 x 10^5 quad-years to 22.3, square root at fp64 from 3.8 x 10^5 to 141, and remainder at fp32
   from 3.2 x 10^5 to 333; fp64 division and remainder stay out of reach (10^19 and 5 x 10^21 years). A second level,
   by classes of the dropped bits, takes the conversions and rounding to a few hundred thousand cases, **PLAUSIBLE** for
   the tile and untested there (section 4.3).
5. **An enumeration by keyed permutation gives exact counts, resume, shards and merge.** A Feistel network on 2w bits,
   six rounds, is a bijection (checked over all 2^32 inputs at w = 16), passes its quality tests from three rounds up,
   costs 14 to 19 ns a 64-bit case and 21 to 25 ns at 128 bits on one core (six runs), and a second implementation reproduces its
   vectors (section 4.5). The store it enables is a set of immutable records whose coverage is a pure function of
   the set; the merge laws hold on 3,000 random scenarios, and a differing batch among 4,096 is localised in at most
   13 hash comparisons (MEASURED on a model, section 5).
6. **The long road.** Full sweeps of the 64-bit spaces are 10^4 to 10^6 quad-years raw (COMPUTED, section 6.1), which is
   not a number of devices a project fields in a decade (2,600 to 153,000 workers for the 64-bit unary and fp32-pair spaces, 462,000 for
   scaleb64's directed list; the fp64-pair spaces are beyond any count), but the reduced spaces of section 4.3
   are within a fleet's reach for three of them (fp32 division, fp64 square root and fp32 remainder: 3, 15 and 34 quads for a decade, section 6.4), and a contributed result can be trusted exactly as far as its
   provenance and a replay allow (section 6.6).

The plan is ranked in section 7; the questions Logan must answer are at its end.

## 1. The question

**Logan, verbatim (2026-10-19):** "Go ahead and dispatch a sonnet parcel for the exhaustive modes, as well as one to
research potential options for more comprehensive sweep coverage, not necessarily 100% but potentially more thorough
edge case testing or methods to slowly accumulate the coverage over time, its impossible today but in the future
perhaps multiple devices could work toward actually doing a full sweep, though obviously a long term goal."

Three things are asked: more thorough edge-case testing where a full sweep is out of reach (which cases matter most,
and how to reach them on purpose); coverage that accumulates, so a weekend adds to the last; and the long road by which
many devices might sweep a 64-bit space, with what a contributed result would need to be trusted. The exhaustive modes
for the 32-bit operand spaces are EX's, and are not discussed beyond what they leave.

## 2. The facts, checked

### 2.1 The run

All MEASURED, by `swp-a/stress_records.py` on the final record, with six tampered copies of the record each caught at
the check written for them (`stress_records_controls.out`).

| | |
|---|---|
| records | 5,108 (67 cycles, 4,086 legs: 4,032 pass, 54 skipped by name, none failed; 865 telemetry) |
| end | the deadline, 2026-10-19 08:01:13, exit 0, 74 s past it; 219,550 s on the card (99.9% of the wall span) |
| sweep slices | 3,287, all pass: 3,038 random, 249 exhaustive; quad 2,948, single 163, deep 176 |
| cases | 1,296,186,685,863 random; 60,129,542,440 exhaustive (14 items x 2^32, plus 8 edge cases in each of the 37 nextup32 and nextdown32 slices: 296) |
| disagreements | none: 0 value mismatches, 0 flag mismatches |
| random slice sizes | 63 at the 2^20 probe, 2,880 at the 2^28 cap, 95 other: 98.8% of the random count is in probe or cap slices |

The brief's figures (14 and 54 items, 3,223 slices) are the 06:55 report's; the run went on 65 minutes and did 64 slices
more. `sweep_cost.py` checks that the lead's rates file never exceeds the final record on any item, that the 06:55 report
never does, and that the lead's 178 medians over rows with five or more slices agree with the derivation from the raw
slices to within 0.59%: the lead's definition (the median over slices of count, or cases for the exhaustive items, per
second of the slice's own job time) is confirmed, and his two extremes are reproduced (class64 over 2^64 on one quad
6,584 years against his "about 6,600"; rem32 317,491 against "about 320,000").

### 2.2 What one "count" is

The rates in the stress record are `sweep.count` a second, and `count` is not one thing. READ in
`host/tools/clause5_soak.c` and `divsqrt_soak.c`, then MEASURED on the real tools (software backend,
`swp-a/tool_probe.sh`, every check held; a control copy passes and five one-line defects in scratch copies are each
caught at their check, `tool_probe_plants.out`):

| operation | one count is | cases a count | MEASURED (count 4,096 unless noted) |
|---|---|---|---|
| class, logB, nextUp, nextDown, conv32to64, conv64to32, rint, sqrt | an operand | 1 | 4,096 cases |
| div, rem | a pair | 1 | 4,096 |
| cvtto32, cvtto64 | an operand, checked against 4 integer targets | the in-range pairs only | 9,385 and 8,367 (ratio 2.29, 2.04) |
| cvtfrom32, cvtfrom64 | a lane, converted 4 times (i32, u32, i64, u64, a fresh random value each) | 4 | 16,384 |
| scaleb32, scaleb64 | an operand against one exponent: a check | 1; operands = count / 17 or / 27 | count 1 gives 17 cases; 4,096 gives 69,632; 69,632 gives 69,632 |
| the 14 exhaustive items | an encoding of [lo, hi) | 1, and +8 for nextup32 and nextdown32 | hi - lo, +8 |

This is the coordinator's correction, confirmed on the tools: scaleb's 14.28 M/s is checks a second, so the full sweep of
2^32 operands against the 17 directed exponents is 85.3 minutes on one quad for four attributes (21 minutes each), and
against the wide range 46.5 hours (11.6 hours each), as EX's brief says it has to be; "minutes each" holds for the other
32-bit spaces (`sweep_cost.out`, Table 2).

### 2.3 Tile items and host items

`host/include/cft.h` (READ, lines 1378 to 1398) and `host/src/clause5.c` (READ, lines 11 to 35) split the clause-5
operations in two. **Composed** (rint, scaleB, the signaling comparisons) and division and square root issue
`cft_run` passes: on a device they run on the tile. **Host** (convertFormat, the integer conversions, logB, nextUp,
nextDown, class, totalOrder and **remainder**) "contain NO floating-point arithmetic at all": round_pack and bit surgery
on the encoding, "bit-identical on every backend by construction", the device argument "context" and "not a participant".
Remainder walks the exponent gap a quotient bit at a time (up to emax - emin + p - 2 steps: 275 at fp32, 2,096 at
fp64, COMPUTED), which is why its rate is 0.46 and 0.061 M/s and why rem64's 16 microseconds a case is a host loop, not a
tile (a quarter of the pairs are aimed at the longest gaps, `rem_pair64`, READ). Scaleb's host path (exponents below the
smallest subnormal power: fp32's -150 and -1000 of 17, fp64's -1075 and -2200 of 27) is READ in `clause5.c`.

By that rule **35 of the 68 items run on the tile** (10 exhaustive: sqrt32 and rint32 under five attributes; 25 random:
div32, div64, sqrt64, rint64, scaleb32, scaleb64) and **33 are host code** (4 exhaustive: nextup32, nextdown32, logb32,
class32; 29 random). Two measurements support the split from the other side:

- **MEASURED** (`sw_rates.sh`, `sw_rates_compare.py`; one core of an i5-12400F in WSL, niced, one short run a job): for the
  16 host jobs the software backend's rate divided by the card run's per-job median lies in [0.79, 1.91], median 1.23, as it
  should if the card is only opened; for the 8 tile jobs it is 0.06 to 0.46 (the card is 2.2 to 16 times faster: div32
  0.077, div64 0.063, sqrt32 0.094, sqrt64 0.069, rint32 0.457, rint64 0.306, scaleb32 0.129, scaleb64 0.275). The two bands
  were set wide, after I had seen the raw software rates and before I computed the ratios; the script's docstring says so,
  and tampered inputs are caught.
- **COMPUTED** (`sweep_cost.py` Table 5): tile items took 177,245 job-seconds (47.5%) of the run's sweep time and host items
  195,834 (52.5%): on the quad 53.3%, on the single 31.0%, on the deep 51.7%.

So 33 items' "card evidence" is evidence about libcft on the box's CPU. That is not worthless (it is the same
oracle comparison the 2026-09-01 software campaign made, 40.7 billion cases, READ in `docs/VALIDATION.md`) but it is
neither card evidence nor card-bound: their coverage can come from any number of CPUs.

### 2.4 The seed finding, and what it turned out to hide

**The lead's claim (READ in `hw/card_stress_lib.py` and `hw/card_stress.py`, then MEASURED):** a random item's n-th slice uses
seed `base_seed + 7919 n` (`Item.seed_for`, `card_stress_lib.py` line 481); n is rebuilt from the run's own `metrics.jsonl` only
(`Driver.load_state`, `card_stress.py` lines 989 to 1029; the wave planner takes `self.seed_n.get(it.name, 0)`, line 1144); a new `--out` has no
metrics file, so every item restarts at n = 0; `main` refuses an existing metrics file without `--resume`, and the
default `--out` is a new `~/card-stress-out/<stamp>-<commit>` (`card_stress.py` lines 1711 to 1715, 1905). **Confirmed.**

**MEASURED on the driver itself** (`swp-a/seed_replay.sh`: `hw/card_stress.py --dry-run --quick`, stand-in tools, no card, three
invocations; `seed_replay_check.py`, whose control moves a seed by one and must report "not a replay"): run A (a fresh
directory) and run B (another fresh directory) both serve `div32-rne` at `seed_n` 0, seed 1,353,449,473 (0x50AC0001), and every
exhaustive item from `lo` 0; run C (`--resume` on A) serves `div32-rne` at `seed_n` 1, seed 1,353,457,392 (= the first + 7,919),
and `sqrt32-rne` from 786,432 (where A's slices ended), `nextup32` from 262,144. The three runs' sweep legs are tabulated in
`seed_replay.out`.

**How much of a rerun repeats.** The tool restarts its stream from the seed at every slice, so a shorter slice is a prefix of a
longer one with the same seed (MEASURED: two slices of 5,000 and 8,000 on a shared state, `seed_audit.py`). 98.8% of the final
run's random count was in slices of the probe size (2^20) or the cap (2^28), whose length a rerun reproduces at the same n
unless the probe lands on a different n (`stress_records.py`, MEASURED); so a rerun repeats at least about 96% of the random
draws (COMPUTED: the 63 probe slices displaced, each costing a whole cap slice of 2^28 = 2.7 x 10^8 counts, 2.2% of the 7.8 x 10^11 total, and the 95 other
slices, 1.2%, not repeating at all), and in practice nearly all of them (BELIEVED).
The standalone scripts repeat too: `hw/run-soak.sh` and `hw/run-c5-soak.sh` use fixed seeds "so reruns reproduce" (READ), and
the driver's slice 0 uses the scripts' own seeds, so it overlaps the 2026-09-01 software campaign's job for the same item
(RANDN 200 M or 30 M cases) as a prefix.

**Three refinements** the claim needs:

- **Exhaustive coverage is per item, not per image** (MEASURED, `stress_records.py` section 4): the intervals tile [0, 2^32)
  exactly in all 14 items, but the single image served 0.02 to 6.27% of an item and the deep 0.00 to 6.25% (one capped slice, usually),
  the quad 87.5 to 99.98%. No image but the quad has swept any exhaustive item; "covered" means "covered by some image".
- **The `| 1` collision** (MEASURED and COMPUTED). Both tools do `rng_state = seed | 1`, and items in the catalog get consecutive
  base seeds (0x50AC0000 + s, 0xC5000000 + s), so at the same n the item with even `base + s + 7919 n` and its neighbour s + 1 start
  from one state, on half the n. `stress_records.py` finds, in the 3,038 slices of the final record: 1,577 distinct starting states,
  1,461 shared by two or more items, 2,922 slices (96.2%) sharing one; the formula alone predicts exactly the 52 colliding item pairs and
  their 28 or 29 shared slices each (check passes; a planted collision it does not predict is caught). 339 of the shared states join slices
  of one operation under different rounding modes (conv64to32 168 slices, div32 170, div64 170, sqrt64 170): 88,619,352,064 operand counts
  were seen again by a second mode, 36.9 to 37.3% of each of those four operations' count. The other 1,122 join different operations, whose
  generators consume the draws differently: correlated, not duplicates. `seed_audit.py` shows the schedule as it ran collides on 2,962 of 3,078
  (item, n) slices, the same seeds without `| 1` on none, and two candidate schedules on none (section 5.2). I judge the effect small
  (BELIEVED): each (operand, mode) test is new, and a defect that does not depend on the mode is found about 37% less often per case in four of
  54 items.
- **The draw order is the compiler's.** `banded32` and `banded64` contain `e = bands[rng() % 7] + (rng() % 3)`: two `rng()` calls in one C
  expression, whose order the language leaves unspecified. `seed_audit.py`'s port, held to the real tools' printed operands (18 streams, 288 lanes,
  every one reproduced; a control with one shift changed reproduces none), says the tool drew `bands[rng() % 7]` first, and `eval_order.sh`
  built the same source with gcc 11 and gcc 12 at -O0, -O1, -O2 and -O3: all seven drew it first (MEASURED). So a seed gave the same
  operands under every build I could make, and a replay on another compiler is BELIEVED safe but not guaranteed; the fix is two statements.

A caution on method: the real tools' operands were read off their own sabotage control (`CFT_SOAK_SABOTAGE=1` prints the operands of the lanes it
names). A lane whose result is a NaN prints nothing (a NaN with a flipped bit still agrees as a class), so the printed "lane" numbers are ordinals of
the non-NaN lanes; the first version of the port matched 6 of 18 streams until it modelled that.

### 2.5 The oracle

The soaks compare libcft with the host CPU's own SSE division and square root, and glibc's trunc, floor, ceil, round, roundeven, nextafter, logb,
scalbn, remainder and llrint families (READ, headers of both tools), not with the golden model or MPFR: an independent lineage, which is its value,
and limited to fp32 and fp64 (the wide formats have MPFR parity in `host/tools/mpfr_check.c` instead, section 3.4). NaN payloads compare as a
class (the contract canonicalises); convertToInteger compares in-range lanes only (out-of-range C conversion is undefined behaviour); RMM has no
fenv mode, so division under RMM and the scaleb and conversion families under RMM are left to the model and MPFR (READ). The oracle is cheap:
MEASURED (`host_only_rate.sh`, a scratch copy of the divsqrt tool whose library call is the native computation, one core of this desktop) generating
operands, one native oracle pass, one native pass standing in for the library and the compare run at 40.6 M/s (div32), 35.0 (div64) and 79.1 (sqrt64):
24.6 to 28.6 ns a case for the divides against the card's 500 to 650 ns. An upper bound, since two native passes are charged: **the host side is at most
about 5% of a tile job's time on this CPU** (the box's CPU is not in the record; BELIEVED under 10%).

## 3. What the repository already covers, and what it leaves

### 3.1 The golden model's own tests

`python/tests` (35 test files and 7 helper modules) is the first line, run by the gates workflow's golden job (`python -m pytest python/tests -q`, READ in
`.github/workflows/gates.yml`) against arbiters that share no code with the model: CPython's binary64, `math.fma`, mpmath, GNU MPFR through gmpy2, and
hand-written IEEE 754 anchors (`test_softfloat.py`, whose own header says the third arbiter is "where FMA implementations actually die"). The
clause-5 operations have three arbiters (`test_clause5.py`); `test_tiny_formats.py` sweeps every 8-bit-format operation, every attribute and
every pair exhaustively; the composed division and square-root sequences are held bit for bit to `softfloat` over a pool carrying the named hard families
(`test_sequences.py`, `test_divfull.py`). The transcendentals have four arbiters including MPFR parity (`test_transcend.py`).

The history in one docstring is the study's best single piece of evidence (READ, `python/tests/test_sequences.py`): the failures the composed div and sqrt had
were found by "this matrix while the sequences were being built, which is the reason the pool and the modes are exhaustive rather than sampled: the
failures cluster in single families that sampling misses": a = 1, b = 1 - ulp (the exact-tie divisor family that broke the Markstein finish), quotients
crossing the [2, 4) binade, negative divisors, sqrt(1 + ulp) and sqrt(min_normal + ulp) under RMM, sqrt(max_subnormal). Section 4.2 shows the first of them
is a closest-approach case.

### 3.2 The conformance vectors and the selftest

`make vectors` writes 168 sets and **1,072,415** cases (READ: `docs/DETERMINISM.md`, `docs/COMPATIBILITY.md`; the stress run's selftest leg replayed 16,086,225 cases over its 15 passing quad runs, which is exactly 1,072,415 a run:
READ in `swp-a/stress-final-report.txt`) from `python/cft_golden/vectors.py`, whose generator is itself a small coverage model for FMA:
six strategies (raw uniform bits; exponents clustered at the subnormal boundary; at the overflow boundary; an alignment sweep of c's exponent across 2p + 8 either
side of the product's; near-total cancellation c = -(a b rounded); signed zeros and exact ties) over a directed operand set (every special, every boundary,
min-normal + 1 ulp, 1 + 1 ulp, all-ones mantissa, 2.0, 3.0). The selftest replays them on the card every third visit of an image.

### 3.3 The soaks' directed lists and banded generators

Everything the random jobs add to uniform bits (READ in `clause5_soak.c` and `divsqrt_soak.c`): one operand in four gets its exponent forced into
{0, 1, 2, 3, 4, 127, 128, 129, 252, 253, 254, 255} (fp32) or the fp64 analogue (COMPUTED from `bands[]` + {0, 1, 2}: e.g. 3 of 21 band draws
land on 2047, 1 of 21 on 0); `scaleb` runs each operand against 17 (fp32) or 27 (fp64) directed exponents; `nextup`/`nextdown` run 8 edge cases first; cvtto draws a
quarter of its operands at powers of two 2^23 to 2^64 jittered 3 either side; cvtfrom one in eight at 2^k + (-2..2); rem aims a quarter of its pairs at the longest
exponent gaps. What is **not** there, COMPUTED from the generators: no mantissa bands (the fraction field is uniform, so P(fraction = 0) = 2^-52 an fp64 operand:
1.45 x 10^10 draws expect 3 x 10^-6 powers of two as operands, no 1.0, no division by a power of two), no relational pair (a = b is 2^-64; an exactly
representable quotient about 4 x 10^-15 at fp64, COMPUTED as the sum of 1/o over the odd parts o of the divisor significand divided by 2^52), no near-boundary quotient (section 4.2). At fp32 all of these are reachable by volume (P(fraction = 0) = 2^-23: about
1,700 hits a draw count of 1.45 x 10^10); at fp64 none is.

### 3.4 MPFR parity at every rung

`host/tools/mpfr_check.c` is "the first independent [oracle] that reaches every rung": fp128 and fp256 against GNU MPFR, with directed specials always and exponent-banded
randoms, the transcendentals included (for which it is the only oracle, libm being neither correctly rounded nor reproducible). Its recorded runs are 100,736 cases (the
2026-09-01 clean-host run) and 238,328 (mingw's MPFR) (READ, `docs/VALIDATION.md`): a different campaign from the soaks, covering the formats the soaks cannot.

### 3.5 What `formal/` proves, so a sweep need not

`formal/README.md` (READ): proofs for the control-logic modules, "the golden model remains the authority on values - nothing in this directory re-litigates numerics":
`cft_fifo` (unbounded: count consistency, ordering, integrity), `cft_seedop` (special-case routing, every input), `cft_simpleops` (bit-exact to the frozen reference
over all 2^104 inputs except three opcodes), `cft_mulpass` (the multi-pass multiplier's column fold exact at the real 24-bit chunk for all seven geometries), `cft_lzcone` at
four widths, `cft_ifetch` (unbounded: no word past n or after a fault, every word the image's, the 18-cycle bound). Not proved, in its own list: other parameterizations,
`cft_ifetch` at the U50's sizes, IMUL's value, seed values (that is `test_seeds.py`, exhaustively at 8/23), BRAM collisions. **No proof covers the datapath's values:
division, square root, the rounding unit, conversions.** The sweep and the sequences' tests are all that stand behind those, which is why this study's sweeps matter.

### 3.6 Who covers which kind of defect

(BELIEVED, a judgement from sections 3.1 to 3.5 and 4; "random" means the stress run's banded draws.)

| defect class | golden tests | vectors/selftest | random soak | directed lists | MPFR | formal | what would add |
|---|---|---|---|---|---|---|---|
| affects at least 10^-9 of the sampled distribution | yes | some | yes | - | - | - | - |
| affects 10^-10 to 10^-13 | named families only | no | yes after several weekends | no | no | no | accumulation, strata |
| closest-approach / tie / exact-quotient cases at fp64 | named families | no | never (4.3 x 10^-6 a weekend) | no | wide formats | no | constructed lists |
| a stuck bit in a zero-detect, class, sticky tree | no | no | by volume only at fp32 | no | no | no | class representatives with walking ones |
| control-logic hazard over all traffic | benches | no | no | no | no | yes | - |
| image, bitstream, driver, thermal, bus | no | selftest | yes (60 h, 0 failures) | no | no | no | the stress run itself |
| algebraic slip in a composed sequence | named families | yes | at fp32 | no | partly | no | tiny-format exhaustion of the same program |

## 4. A survey of methods, and what each finds here

Each subsection gives the source, what it would find that the stress run does not, and then its fit to this repository. Sources
are numbered [n] and listed with their verification status in section 10. Costs are COMPUTED from the measured rates where a
rate applies; a quad is four tiles, a worker one soak process (a tile for tile items, a core for host items).

### 4.1 Coverage models for floating-point test generation

**IBM's FPgen** [1, 2, 3] is the field's reference: a test generator in which a *coverage model* is a set of verification tasks,
each a constraint on the operands, intermediates and result of one instruction, and a constraint solver builds a random test for
each task (READ: the IBM publication page for [1]: FPgen - A test generation framework for datapath floating-point verification,
Aharoni, Asaf, Fournier, Koifman, Nagel, HLDVT 2003). Its simplest model crosses the ten major operand types of every operand
(plus and minus NaN, infinity, zero, denormal, normal) (IBM report H-0140 [2], from a search summary: the IBM server refused the
fetch, BELIEVED); its solvers handle ranges on inputs and result, fully for add and subtract and partially for multiply and
divide ([3], from a search summary of the abstract, BELIEVED). **What it finds that the stress run does not:** cases defined by
*relations* (an exponent difference, cancellation depth, the round and sticky bits of the exact result, a result at a rounding
boundary or a range edge), because the generator is aimed at a result property rather than at operand classes. The banded generator
implements only the operand-class part, and only for exponents.

**Berkeley TestFloat** [4] (READ, `testfloat_gen.html`, `TestFloat-general.html`): a level 1 (default) and a level 2 ("many more
test cases ... with better coverage"), a per-type minimum count for `-n`, a seed that fixes the sequence, all five rounding modes and
the five flags; its own document describes its cases as simple patterns mixed with weighted random inputs, aimed at carry chains
and rounding, says it is not remarkably good at difficult rounding cases for division and square root, makes no attempt to find
bugs specific to SRT dividers such as the Pentium's, and that passing in no way guarantees a bug-free implementation (section 4, "What
TestFloat Does"). So TestFloat is the *same shape* as the banded campaign at larger volume, not a source of the missing classes:
useful as a second independent test-vector set (Berkeley SoftFloat's lineage is independent of this project's), not as the answer.

**Conformance suites.** IeeeCC754 [5] (Verdonk, Cuyt, Verschaeren, ACM TOMS 27(1), 2001; part I, basic operations, square root and remainder, READ from a text extraction of its PDF;
part II, conversions, known only from a search listing) is built so one set of vectors, written in a precision- and range-independent syntax, tests any precision and range: the idea
of section 4.3's tiny-format exhaustion, taken to a test suite. About half of its vectors generalise older hardware test sets (Coonen's and UCBTEST's); the other half test exact
rounding systematically for every combination of round and sticky bits that can occur, with the hard-to-round cases singled out, and the paper tabulates operand shapes by the round and
sticky bits of the exact result (its Tables I to V, for addition and multiplication): the class-level idea of section 4.3's second level, already published as a vector set. For division and
square root it states that an exact halfway result cannot occur (its Lemmas 1 and 2), notes that a slight fumble in a square-root algorithm's last rounding can be too rare for random
testing to expose, and takes its hard cases from Coonen's power-series family and UCBsqrttest's output (section 4.2 builds the same cases by construction). UCBTEST [6] (netlib `fp/ucbtest`, which per Oracle's numerical computation guide contains Paranoia, Liu's
elementary function tests, IEEE test vectors, and programs based on number-theoretic methods of W. Kahan that generate hard cases for
correctly rounded multiplication, division and square root; READ in a search result of that guide) is the nearest existing source of
exactly the cases of section 4.2. **BELIEVED but not checked**: that its generators run on a modern host and what their licence is;
nothing was downloaded.

| | |
|---|---|
| **would find** | result-directed cells the banded generator cannot name; an independent vector set (TestFloat, IeeeCC754); Kahan's hard cases for div and sqrt (UCBTEST) |
| **cost** | cells x cases a cell: a division model of 10 x 10 operand classes x about 30 exponent-difference classes x 6 round-and-result classes is 18,000 cells; a few hundred cases each is 5.4 x 10^6 cases, 0.7 s of quad time at div32's measured 8.1 M/s a quad (COMPUTED); TestFloat level 2 is minutes on a CPU (BELIEVED) |
| **lives in** | the soak tools as a new enumerated mode (section 5.2), or a generator beside `python/cft_golden/vectors.py` |
| **needs built** | the cell definitions and a constructor for each (4.2 gives division's and square root's); a reader for TestFloat's line format |

### 4.2 Hard cases

**The mathematics for division and square root.** A quotient of two p-bit significands cannot lie exactly on a rounding midpoint
(and neither can a root). Verdonk, Cuyt and Verschaeren [5] state it as their Lemma 1 for division, for quotients not below the smallest normal number, and Lemma 2 for square root (READ);
Dutton, Anand, Enenkel and Mueller [7] (arXiv:2404.00387, 2024) prove it for reciprocal, division and square root (READ in the abstract, which does not say whether subnormal results are
excepted). The condition of [5] is the one this study's G3 finds: on every pair of e4m3, RMM and RNE differ on 264 of 65,536 pairs, all with an exact quotient below the smallest
normal (the grid there is coarser, so a midpoint of it can be a quotient), none above, and never for square root (MEASURED,
`symmetry_check.out`). Because the numerator N = mx 2^p - c my of a quotient's distance to a midpoint (c the odd integer nearest mx 2^p / my; the docstring of
`swp-a/hardcase_div.py` derives it) is a nonzero integer, the closest possible approach is |N| = 1: a distance of 1/(my 2^p), about 2^-2p, 2^-(p+1) of an ulp. For an odd divisor
one modular inverse builds the dividend: mx = +-(2^p)^-1 mod my, shifted into range. MEASURED (`hardcase_div.py`):

- the construction succeeds for 37.3 to 40.5% of odd divisors per target and sign at p = 24, 53 and 113 (the prediction 2 ln 2 - 1 = 38.6%), and
  |N| = 1 is verified in exact integers on every one built (twelve counts of 3,000 divisors each, none wrong);
- the golden model's division equals an *independent* exact arbiter (Fractions and the decision rule written from the definitions) on 1,500 + 1,500 + 600
  closest-approach cases at p = 24, 53, 113, under all five attributes, bits and flags (the arbiter's RNE and the model's RTZ do differ on the near-midpoint
  cases, so the comparison can see); and the same construction at a representable boundary (N' = mx 2^(p-1) - j my) builds the cases that test directed rounding and the
  inexact flag;
- the campaign's own sampler (the port of the soak's generator, held to the real tool in `seed_audit.py`) reaches a least rho = |N|/my of 2.3 x 10^-6 in 358,161 fp32
  draws and 8.9 x 10^-7 in 362,061 fp64 draws, the 1/draws that uniform draws predict; the least possible is 7.9 x 10^-8 (fp32) and 1.5 x 10^-16 (fp64). A weekend
  item's 1.45 x 10^10 draws expect **2,304 closest-approach hits at fp32 and 4.3 x 10^-6 at fp64** (COMPUTED): at fp32 the class is reached by volume, at fp64 it is not
  reached at all;
- the repository's failure family a = 1, b = 1 - ulp (the exact-tie divisor family that broke the Markstein finish) has |N| = 1 at both formats: it is a closest-approach
  case, found in the repository by structure and invisible to sampling at fp64;
- **square root** by the same argument, scanned exhaustively at fp32: the input nearest the square of each of the 8,388,608 midpoints is at a distance d 2^-2p with d an
  integer, d = 1 for exactly **two** midpoints (the least an odd square allows) and 7, 9, 15, 17, 23 for the next; one of the two is sqrt(1 + ulp), the family the repository
  found failing under RMM; the golden model equals an exact integer arbiter on those inputs under all five attributes (MEASURED, `hardcase_div.out` H6);
- a **planted defect** only the constructed set finds: a division that computes the quotient to g = 40 extra bits and rounds ties-to-even on those bits, ignoring the remainder,
  fails on 606 of 2,374 constructed fp64 pairs (25.5%) and on none of 272,007 sampler draws; a stress-run-sized item expects 6.6 x 10^-3 failures, so the defect would pass the
  weekend; with g = 80 the same method is correct on every constructed pair (the set does not simply fail everything).

The classical example of this class is Intel's FDIV bug: five entries of a divider's lookup table were omitted (Pratt [9], READ in the Springer abstract), and the divisors at risk are those with
six consecutive ones in bit positions 5 to 10 (Edelman [8], the abstract as a search result quoted it), at a rate Pratt [9] puts at one error per 40 billion random single-precision divisions
(the same abstract); a 1.45 x 10^10-draw item at that rate would see 0.36 times. The class is defined by a bit pattern of the divisor, so a generator aimed at the pattern reaches it at once and a sampler
only at that rate. The tile's own tables are `cft_seedop`'s reciprocal and reciprocal-root
seeds, whose accuracy is exhausted at fp32 by `python/tests/test_seeds.py` and whose special-case routing is proved in `formal/`.

**The theorems that make the algorithm right, and so where a slip shows.** Markstein's result [10] (IBM J. Res. Dev. 34(1), 1990, as Harrison's slides [11] state it, from a search summary of them, BELIEVED: a
quotient estimate within one ulp and a correctly rounded reciprocal, two fused multiply-adds, the correctly rounded quotient in any attribute, with an exception when the
divisor's significand is all ones) is the premise of the tile's composed division (READ: `python/tests/test_sequences.py` names a "Markstein finish" that the a = 1, b = 1 - ulp family broke); the
closest-approach cases are the inputs where a finish step that is correct *except* at a boundary shows itself.

**Conversions** need no search: the hard cases are the dropped-bit patterns (all zero; one below half; exactly half; one above; all ones) at every rounding position, which include
every subnormal-result strip. At fp64 to fp32 a draw lands on an exact tie with probability 2^-29, so a weekend item meets about 27; in the strip where the result is subnormal by s places the tie
needs 29 + s dropped bits and an exponent in a window of one of 2,047, so ties in the subnormal strips are essentially never reached (COMPUTED order: 1.45 x 10^10 x 2^-30 x 1/2048 = 6.6 x 10^-3
for s = 1).

**The elementary functions, which the math library round's routines also face.** Correct rounding of exp, log, sin, cos and tan has its own hard cases, the Table Maker's Dilemma:
the inputs whose exact result lies closest to a rounding boundary. Lefèvre and Muller [12] (ARITH-15, 2001, pages 111 to 118, READ in the author's list) searched them for the main
functions in double precision and offered them "to easily test" correctly rounded libraries (the abstract, from a search summary); the method has been generalised (Stehlé, Lefèvre,
Zimmermann [13], ARITH-16 2003 and IEEE TC 54(3), 2005) to a sublinear search by lattice reduction, used for years by the CORE-MATH project [14] (ARITH 2022): in 2023 one binade of sin (the top one) took
847 hours of real time on a cluster of 64-core Xeons, about six core-years by the paper's reckoning, and found 1,038 cases with at least 43 identical bits after the round bit. The result that matters here is **new in 2026**:
Lefèvre, Ly and Zimmermann [15] (ARITH 2026, READ in the paper's text) replaced the sublinear search with a *brute-force linear* one that costs a few cycles an input (its critical loop is three
additions modulo 2^64 and a test, by a table of differences), a full binade of sin or cos in under 4 hours on a 512-core node with SIMD, and report the binary64 Table Maker's Dilemma "fully solved for the most common
univariate" functions, sin, cos and tan included; the full set of their hard-to-round cases is stated to be in the CORE-MATH test suite, as the files sin.wc, cos.wc and tan.wc (not downloaded). Their paper also recalls an FPGA
design for the exponential (de Dinechin, Muller, Pasca, Plesco [16], ASAP 2011) estimated at 125 hours a binade at 100 cores of 100 MHz, which never worked: **an exhaustive 2^64-input
FPGA search for a function has been proposed before**, and a recurrence of three additions modulo 2^64 an input is a regular fixed-point kernel, which a purpose-built image would run better
than this card's floating-point tile (BELIEVED, not designed here). Zimmermann and co-authors [17] test the accuracy of libm functions exhaustively at binary32 and by a
black-box search above (title and listing READ; the method statement is from a search summary of an earlier version, BELIEVED).

*Fit to the math round.* `docs/studies/M1-exp-log.md` and `M2-trig.md` design routines that **mark** a lane whose true value lies within the bound Bv of a rounding boundary and replay it
by the definition, with a mark rate 2^(0.53 - G) a call (READ): 2^-45.5 at the design's G = 46 for fp64, and 2^-43.5 at the G = 44 that M1's Question 1 now recommends there. A random
sweep of 1.45 x 10^10 calls expects 1.45 x 10^10 x 2^-45.5 = **2.9 x 10^-4 marked lanes** at G = 46 and 1.2 x 10^-3 at G = 44 (COMPUTED): the mark-and-replay path would never run in a
random weekend. The published binary64 worst cases (results within about 2^-(p + 43) of a rounding boundary or closer, the figure of [15]) are the lanes a bound of that size marks, so they
are the corpus that exercises the path on the tile; whether a given G marks a given case is a comparison of the bound with the case's distance, not worked out here (BELIEVED). For sin, cos and
tan the paper says where the set is (above); for exp and log the set of [12] is the older one, and I did not look for where it is kept. The authors argue [15] that the obstacle to requiring correct rounding of
these functions in the next revision of IEEE 754 (due in 2029) is now gone, which bears on the project's rule that new operations follow 754 first. At fp128
and fp256 no worst-case tables are known to me, and the repository's own argument stays the heuristic counting argument (2^-83 expected inputs near the cap at fp256 for pow) plus the
structured families it found (READ, `docs/TRANSCENDENTALS.md`; the Table Maker's Dilemma "has no proof for these functions at these precisions").

| | |
|---|---|
| **would find** | closest-approach and exact-quotient classes for div and sqrt (probability about 10^-16 a draw at fp64); ties in subnormal strips; the mark-and-replay path of the math routines |
| **cost** | 10^6 constructed pairs per (format, target, sign) is 0.16 s on one quad at div64's 6.2 M/s a quad (COMPUTED); a published table of a function is minutes |
| **lives in** | a generator tool (the instrument is about 150 lines); the corpus beside `python/cft_golden/vectors.py`; the ledger counts hits per cell (5.3) |
| **needs built** | the generator for div and sqrt (the construction above), conversions' dropped-bit patterns, scaleb's strips, the corpus loader; permission to download the published tables |

### 4.3 Reductions by symmetry and equivalence

The sizes of the spaces are mostly redundancy. What follows states each reduction, whether it is proved, and what edge it leaves. Throughout, "proved" is for the **golden model**, by an
argument written here and by exhaustion on tiny formats of the same family in `swp-a/symmetry_check.py` (e4m3 and e5m6; the model accepts any exponent and fraction width); the
**tile's** RTL is not covered by any of it (section 8).

**Sign and attribute.** (a) Negating an operand mirrors the attribute (rdn and rup swap; rne, rtz and rmm stay): division, roundToIntegral, scaleB and convertFormat, every encoding or
pair of e4m3 and every attribute, bits and flags: 0 violations (the control with rne and rmm swapped has 88,448). (b) For a positive result rdn equals rtz, for a negative one rup does (every
pair: 0 violations; the control that folds the other directed mode has 43,960). So the sixteen (attribute, operand-sign) combinations of a division are three *magnitude functions*: nearest,
truncate, away from zero. (c) RMM equals RNE for square root on every e4m3 input (and on 3,000 random fp32 and 3,000 fp64 operands), and for division except where the exact quotient is below
the smallest normal ([5], [7], section 4.2): the nearest function is one function outside the subnormal strip. These are proved for the model by the definitions of the rounding directions
(RD(-x) = -RU(x), and the rest), and the no-midpoint theorem for (c). Edge: the rtl's *decode of the five mode codes* and *sign handling* are separate logic; cover each code and each
sign combination on the classes where they differ, a handful of cases.

**Scale.** Rounding to p bits commutes with multiplication by 2^k when the exact value before and after has exponent in [emin, emax], because the rounding position is a function of the
exponent alone and ulp(2^k y) = 2^k ulp(y). Hence: division of a scaled pair equals the scaled quotient **iff the exact quotients of both pairs lie in [2^emin, 2^emax)**; square root of a 4^k
scaled input equals the scaled root **always** (a root of a positive finite is normal, subnormal operands included); remainder of operands scaled by the same 2^k equals the scaled remainder
**always** (the remainder is exact). MEASURED on e4m3, every finite nonzero pair and k in [-8, 8]: 1,517,120 scaled pairs with both quotients in the core, **0 violations** in each of rne, rtz,
rdn and rup; 317,680 of 403,712 pairs whose scaled quotient leaves the core give a different result (the edge strips are real); sqrt 2,625 checks, 0 violations, including subnormals; rem 519,044
checks, 0 violations. The instrument's first version defined the core by the *rounded* result and found 4,744 violations: a quotient just below 2^emin can round up into the normal range,
having been rounded on the coarse grid, so the core must be defined by the exact quotient. The edge is therefore exactly the **strips**: the quotient's exponent below emin by s places
(s = 1 .. p + 1, p + 1 strips, each its own rounding position) and the overflow strip; every (significand pair, strip) key is reached by e4m3's pairs: 448 keys, the bound (p + 3) 4^(p-1) exactly.

**Rounding structure (classes).** The result of convertFormat and roundToIntegral is a function of the sign, the rounding position, the kept bits and the class of the dropped bits (zero, below
half, half, above half), through the kept lsb and the carry: a decision rule written here from the definitions (`decide`) equals the model on every finite source encoding of e5m6 to e4m3
(14,290 case-attribute pairs, 0 differ) and of e5m6 roundToIntegral (19,830, 0 differ); the rule that forgets ties-to-even differs on 120 and 64. The decision needs only 224 classes
(sign, exponent, class) plus the lsb against 4,096 source encodings at that size. Proved for the model by the definition of the directed and nearest roundings; the **tile** is
PLAUSIBLY structured the same way, which is the assumption of the second level below.

**What remains** (COMPUTED in `symmetry_check.py` G6; one quad; L0 is the raw sweep of the soak's attributes):

| space | runs | L0 (log2 cases) | L1 value level (log2) | L0/L1 | L1 on one quad | how L1 is counted |
|---|---|---|---|---|---|---|
| div32 | tile | 66.0 | 52.3 | 1.3 x 10^4 | **22.3 years** | 3 magnitude functions x (core + p + 2 strips) x 4^(p-1): 3 x 27 x 2^46 |
| div64 | tile | 130.0 | 111.4 | 4.0 x 10^5 | 1.8 x 10^19 years | the same, p = 53 |
| sqrt64 | tile | 66.0 | 54.6 | 2.7 x 10^3 | **141 years** | 3 x 2^p (mantissa x exponent parity; subnormals normalise into it) |
| rint64 | tile | 66.3 | 59.3 | 1.3 x 10^2 | 2,890 years | 3 x p x 2^(p-1): magnitudes in [1/2, 2^(p-1)) |
| conv64to32 | host | 66.0 | 58.3 | 2.0 x 10^2 | 464 years (a core each) | 3 x (core + 25 strips + overflow) x 2^(p-1) |
| cvtto64 | host | 66.3 | 60.6 | 53 | 5,660 years (a core each) | 2 x 65 binades x 2^52 x 3 |
| rem32 | host | 64.0 | 54.1 | 9.5 x 10^2 | **333 years** (a core each) | 4^(p-1) x 275 exponent gaps |
| rem64 | host | 128.0 | 115.0 | 8.0 x 10^3 | 5.5 x 10^21 years | 4^52 x 2,096 |
| scaleb64, wide | tile | 78.0 | 59.4 | 4.1 x 10^5 | 435 years | 3 x (core + strips) x 2^(p-1): results in range are exact and trivial |

The strips' count is an *upper bound* (each strip counted at the core's full size) that e4m3 attains; at p = 24 and 53 it rests on the argument. **Only fp32 division, remainder and
fp64 square root come within a fleet's reach by value-level reduction** (section 6.4). The cost of a reduction is what the lemmas leave: the strips, the mode decode, the sign logic, the
subnormal-operand *normalization* paths (a path the value-level argument folds into the core but the tile takes through a shifter: the leading-zero classes, p - 1 of them, are structural, not
value-level).

**The second level, by classes (PLAUSIBLE).** If the tile's rounding unit depends on the dropped bits only through guard and a sticky tree, on the kept bits only through the lsb and the
carry, and on the exponent only through a rebias and range checks, then a *representative of every class plus a walking-ones set over the dropped and kept bits* covers it: for conv64to32,
281 exponents x 4 classes x (lsb 2 x all-ones 2 + 52 walking bits) x 2 signs x 3 magnitude functions = **377,664 cases, 0.06 s on one core** at conv64to32's measured 6.2 M/s, against 464 core-years at the
value level (COMPUTED). The same shape serves rint, scaleb's strips, cvtto and cvtfrom, class, logB and next (a few hundred thousand cases each, seconds). What the assumption excludes is a defect
that depends on a *combination of dropped bits beyond the walking set* (a carry-chain defect keyed by a specific pattern longer than the walk); a stuck-at-style fault is covered, a pattern-dependent
timing fault is not (BELIEVED: static timing analysis covers the second by construction at the corners it was closed at, which the stress run's +0.003 ns and the clock sweep to 175 MHz bear on).
The assumption is a claim about RTL and is what `formal/` could prove at small width (section 4.7).

| | |
|---|---|
| **would find** | at the value level every defect of the reduced function (fp32 division in full, fp64 sqrt in full, fp32 remainder in full); at the class level every structural defect of the rounding unit in seconds |
| **cost** | the L1 column above; L2 about 10^5 to 10^6 cases an operation (seconds) |
| **lives in** | the soak tools' enumerated mode over a reduced index space (5.2), with the strips and classes as strata |
| **needs built** | the rank/unrank maps for each reduced space; for L2 a representative generator per op; the proofs' write-up in the contract's documents if the project wants "swept in full" to name its level |

### 4.4 Stratified and low-discrepancy sampling

Latin hypercube sampling (McKay, Beckman, Conover [18], Technometrics 21(2), 1979) divides each input into equal-probability strata and draws once from each, which reduces the
variance of estimators of a mean; Sobol' sequences [19] (1967) and their better constructions (Joe and Kuo [20], SIAM J. Sci. Comput. 30(5), 2008) fill a cube more evenly than random
points; the combinatorial-testing line (Kuhn, Wallace, Gallo [21], IEEE TSE 30(6), 2004, and NIST SP 800-142 [22]) argues that most failures need only a few conditions at once, so every t-way
combination of parameters is nearly as good as exhaustive. **What they would find here:** little beyond what random draws already find, by arithmetic. Their advantage is for smooth integrands in
few dimensions; a bit-pattern defect has no smoothness. And at the stress run's volume random draws already cover every t-bit pattern on every set of t positions of an operand for t up to about 27
(COMPUTED, `sweep_cost.out` Table 7: the coupon-collector union bound needs 2^t (t ln 2 + ln C(64, t) + 3) draws for a probability of 0.95, 8.5 x 10^9 at t = 27 and 1.7 x 10^10 at t = 28 against 1.45 x 10^10). The classes the banded sampler
cannot reach are not low-order interactions among bits: they are *long-range* conditions (a 29-bit pattern, an all-ones 52-bit field, a relation between two operands) which the construction of 4.2
and the strata of 5.2 reach and covering arrays of small strength do not. The one idea worth taking is **stratification as a minimum count**: each cell of a coverage model gets a floor of draws
regardless of its sampling probability, which is what a ledger by stratum (5.3) records.

| | |
|---|---|
| **would find** | a little at the margin (BELIEVED); not the long-range classes |
| **cost** | negligible |
| **lives in** | not recommended as a separate mechanism; strata with floors are section 5.2 |
| **needs built** | nothing beyond the strata |

### 4.5 Non-repeating enumeration

A permutation of the case space, numbered by index, gives exact counts and a range of indices that is a resumable, shardable unit. Four ways to make one:

- **A keyed Feistel network** (Luby and Rackoff [23], SIAM J. Comput. 17(2), 1988: a pseudorandom permutation from round functions; and a bijection whatever the round function is, because
  it is inverted by running the rounds backwards). For a range that is not a power of four, **cycle walking** (Black and Rogaway [24], CT-RSA 2002: apply the permutation again until the result lands
  in range) gives a bijection on [0, N) at an expected 4^w / N calls.
- **A full-period linear congruential generator** (Hull and Dobell [25], SIAM Review 4(3), 1962; READ in the Wikipedia reference list and the page's statement of the conditions: for a modulus 2^64 the
  increment odd and the multiplier 1 mod 4). It visits every value once and can jump ahead in O(log n) steps (Brown [26], Trans. Am. Nucl. Soc. 71, 1994), but the low bits have short periods (bit j has
  period 2^(j+1): the lowest alternates), which are precisely the bits that decide rounding and sticky; it needs an output permutation, and then it is no simpler than the Feistel network.
- **A counter-based generator** (Salmon, Moraes, Dror, Shaw [27], SC11: Philox and Threefry, stateless keyed functions of a counter, at least 2^64 streams of period 2^128 or more that pass BigCrush, by the abstract as
  a search summary reports it): the library route; heavier than a 64-bit bijection needs to be.
- **The soak's xorshift stream today** (`rng_state = seed | 1`): no exact count, sequential only (a slice cannot resume inside itself), a probable but unproved disjointness of slices (BELIEVED: the birthday
  estimate for 55 streams of 7 x 10^8 draws on a 2^64 cycle is about 10^-7), and the two caveats of 2.4.

MEASURED (`swp-a/perm_check.c`, `.py`, `.sh`, WSL, gcc 11.4, one core of an i5-12400F; the full capture is `perm_check.c.out` and `perm_check.out`):

- **Bijectivity by exhaustion.** A balanced Feistel network on 2w bits (round (L, R) to (R, L xor F(R, k_j)), F a multiply-xorshift finalizer, round keys from splitmix64): at w = 4, 8 and 12 every output
  is distinct for 1 to 6 rounds (bitmaps of the outputs over 2^8, 2^16, 2^24 inputs); and the left-inverse test, inverse(perm(i)) = i for every i of a finite domain, which proves injectivity and so
  bijectivity, was run over **all 2^32 inputs at w = 16 in 140.8 s with 0 failures** (147.6 s in the first capture), and over 2^28 at w = 14. A planted round that reads the wrong half collides (2,363,750 distinct of 16,777,216) and
  fails the round trip on 65,533 of 65,536.
- **Quality**, perm(i) for i = 0 .. 2^22 - 1 at 64 bits, as z-scores (bit balance, a 64 x 64 avalanche matrix over 20,000 inputs, the top 12 bits' histogram, serial correlation): **one and two rounds fail** (avalanche
  z = 141), **three, four, six and eight pass** (largest z 4.47). The thresholds are mine, heuristic, and are not BigCrush.
- **Cycle walking** onto N = 3,000,000 inside 4^11: every output in range, all 3,000,000 distinct, 1.3981 calls an index against 4^11/N = 1.398; a planted clamp instead of walking loses 853,791 cases.
- **Accounting and shards**: the first K indices give exactly K distinct cases for K = 1, 100, 10^6, 8 x 10^6, 2^24; the index ranges [0, 10^6) and [10^6, 3 x 10^6) give disjoint case sets; two ranges that overlap by
  100,000 indices share exactly 100,000 cases.
- **Speed**, this core, six runs (the full run's and five more of the speed section alone, `perm_check.speed.out`; the desktop at its natural load, niced): a 64-bit permutation at six rounds takes **14.0 to 19.4 ns** (the full run's 16.2; 9.1 to 12.8 at four rounds, 21.5 to 30.9 at eight), and **21.0 to 24.9 ns** at 128 bits. A second implementation written separately in Python reproduces
  all 128 vectors the C program printed (64-bit, 46-bit, 128-bit and cycle-walking vectors), and with one key bit changed or one round fewer reproduces none (a control), and passes its own round-trip and small-width
  exhaustion checks.

The cost against a case: 14 to 19 ns is 2.8 to 3.9% of div32's 500 ns tile case, and the 128-bit permutation of a div64 pair, 21 to 25 ns, is 3.2 to 3.8% of its 650 ns; it is about half to two thirds of the 30 ns a case of the cheapest host item
(class32 sequentially), but that item has no reason to be sampled (the class level of 4.3 gives it in seconds, and EX sweeps its 2^32 exhaustively). The permutation parallelises trivially (stateless).

| | |
|---|---|
| **would find** | nothing new by itself; it makes every other method's coverage *countable, resumable, shardable and mergeable* |
| **cost** | 14 to 19 ns a 64-bit index, 21 to 25 ns at 128 bits, one core (MEASURED, six runs) |
| **lives in** | `host/tools/clause5_soak.c` and `divsqrt_soak.c` as an `enum <lo> <hi> <key>` mode beside `<count> <seed>` (EX adds exhaustive modes in the same files), and `hw/card_stress_lib.py`'s `Item` |
| **needs built** | the permutation (a 40-line C function; the instrument is the reference), the rank/unrank map of each space, the new mode and its parser |

### 4.6 Distributed computing with verification

**BOINC** (Anderson [28], GRID 2004; a platform for public-resource computing) and the sabotage-tolerance work behind it (Sarmenta [29], FGCS 18(4), 2002) frame the problem: a volunteer's result is
believed only because of **redundancy** (majority voting: work done at least twice, so at best 50% efficiency), **spot-checking** (a task whose answer the manager knows, sent without being recognised; a wrong
answer blacklists the worker and invalidates what depended on it, READ on Sarmenta's project page) and **credibility** estimated from a worker's history. Golle and Mironov [30] (CT-RSA 2001) treat
the economic version, a participant paid for work who might claim credit without doing it. Their "ringers" idea, which is commonly attributed to that paper, **was not confirmed by anything I could read** and is not
relied on here. For the log that carries the results, **hash trees** (Merkle [31], CRYPTO '87) give a short digest of a long record, **audit paths** that prove one leaf belongs to it, and **consistency proofs**
that a later tree extends an earlier one, as RFC 6962 [32] (Certificate Transparency, 2013) specifies for certificate logs and Crosby and Wallach [33] (USENIX Security 2009) for tamper-evident logging with
logarithmic proofs.

**What this project has that BOINC projects usually do not.** The contract makes the result of element i independent of which tile computed it (`docs/SCALING.md`: "determinism constrains which INDEX is computed, never
which TILE computes it", READ), so two devices' digests of the same slice must be equal *bit for bit*; the classic difficulty of volunteer floating-point computing, results that legitimately differ across hardware, is
absent by construction (BELIEVED: the general BOINC experience, not checked here). And the golden model is the authority: **a disagreement is a triple (operands, device value, oracle value) that anyone can recheck in
microseconds on the golden model**, so a *failure* self-certifies. It is the *pass* that cannot be certified by looking at it. Section 6.6 draws the consequences.

| | |
|---|---|
| **would find** | not defects: it makes accumulated coverage believable across owners |
| **cost** | a digest per slice: `openssl speed` on this core gives SHA-256 at 1.73 to 1.77 GB/s on 8 KB blocks and 1.80 to 1.81 GB/s on 16 KB (MEASURED, two runs, `sha_speed.out`), so 16 bytes of output and flags a case cost about 9 ns, 1.8% of div32's 500 ns tile case and 1.4% of div64's 650 ns (COMPUTED); a re-check rate r multiplies card time by 1 + r |
| **lives in** | the soak tools (a per-batch digest of the outputs and flags), the record format (5.3), a verifier script |
| **needs built** | the digest in the tools, the signed record, the fold and the verifier |

### 4.7 Formal methods as a complement

What a proof covers that no sweep can: **all inputs of the proved width and unbounded time**. `formal/` shows it: `cft_fifo` and `cft_ifetch` are proved for unbounded time and all traffic, `cft_simpleops` equal to
its reference over 2^104 inputs in two seconds, `cft_mulpass` exact at the real chunk for all seven geometries (section 3.5); a sweep of any of those would sample a vanishing part. What a sweep covers that these
proofs do not: the **values** of the datapath, the bitstream as built, timing, the card, the host and the bus. At Intel and AMD formal verification of arithmetic datapaths is established: Kaivola et al. [34]
(CAV 2009, pages 414 to 429) report formal verification as the *primary* validation vehicle for the Core i7's execution cluster with coverage-driven testing dropped, and state that arithmetic datapaths were already
verified formally at Intel; Russinoff [35] (LMS J. Comput. Math. 1, 1998) proved in ACL2 that the AMD-K7's multiplication, division and square root conform to IEEE 754; Harrison [11] (TPHOLs 2000) proved Intel's
IA-64 division algorithms in HOL Light. The Handbook of Floating-Point Arithmetic [36] has a chapter on formal verification (BELIEVED from its table of contents, from a search listing).

For this repository the complement that fits is narrow and cheap, not a datapath proof: (a) **prove the reduction lemmas on the RTL's rounding unit at small width**, a combinational miter of the unit against the decision rule of section 4.3 (the style `equiv.sby` closed over 2^104 inputs in two seconds): that turns the
second level's PLAUSIBLE into PROVED at the unit's width parameters, and the argument that nothing in the unit branches on the width values is the one `formal/README.md` already makes and marks "an argument, not a proof";
(b) an **algorithm-level proof of the div and sqrt cores' final correction** in the style of [10, 11, 35], which sampling can never establish at fp64 and whose premises the closest-approach cases exercise; (c) leave timing and
image faults to the stress runs. The proofs cannot see a wrong image, a stale build, a bus fault or thermal behaviour, which is what the 60-hour run did exercise.

| | |
|---|---|
| **would find** | structural RTL defects in the rounding unit for all inputs at small width; an incorrect final correction of div/sqrt at all widths |
| **cost** | days of harness work (BELIEVED, from `equiv.sby`'s two seconds and `mulpass_real`'s hours at the hard geometries); no card time |
| **lives in** | `formal/` (the pinned container) |
| **needs built** | the reference unit, the miters, the negative controls `formal/README.md` requires of every proof |

## 5. Accumulating coverage: a design

Nothing in this section is built. It is a design whose parts were each held to an instrument: the enumeration (4.5), the merge laws and the re-check descent (`swp-a/merge_law.py`), the seed arithmetic
(`seed_audit.py`), the constructed classes (`hardcase_div.py`).

### 5.1 What accumulates, and what is the wrong thing to count

"Fraction of the space covered" is the wrong metric for a 2^64 space: a whole weekend on one item adds 10^-7 to 10^-6 of it (`sweep_cost.out`, Table 4: class64 1.06 x 10^-6, div32 9.6 x 10^-8, sqrt64 7.2 x 10^-8; COMPUTED)
and the fraction reaches 1 after 10^6 to 5 x 10^7 weekends. Three quantities do accumulate meaningfully:

1. **The detection floor**: the smallest share of the sampled distribution a defect can occupy and still be hit with probability 0.95 is 3 / N for N independent draws (1 - e^-3 = 0.95). One weekend item
   (N = 1.45 x 10^10) gives 2.1 x 10^-10; 13 independent weekends 1.6 x 10^-11; 52, 4.0 x 10^-12 (COMPUTED, `sweep_cost.out` Table 3; rem64, with 1.76 x 10^9 draws, 1.7 x 10^-9, 1.3 x 10^-10 and 3.3 x 10^-11 for 1, 13 and 52 weekends).
   **Under the stress run's seeds the floor does not move from one weekend to the next**: a rerun repeats the draws (2.4). With fresh seeds it improves as 1/W; with an enumeration it improves as 1/W
   *and* the count of distinct cases is exact.
2. **Strata**: the cells of a coverage model (4.1), each with a floor of hits. The class-level spaces of 4.3 are a few hundred thousand cases and complete in seconds, so their coverage is "all of it" in the first
   weekend and every later weekend is a re-verification on a new build.
3. **Exact coverage of the reduced spaces** (4.3): the fraction of a space of 5 x 10^15 to 10^17 cases that does reach 1, over many weekends and many devices. A whole card on the whole weekend needs **3,209 weekends** for div32's L1
   space, 20,235 for sqrt64's, 47,873 for rem32's (COMPUTED, `symmetry_check.out`): one card never finishes any of them; the ledger exists so that many cards' weekends add.

### 5.2 Campaign, stratum and enumeration

A **campaign** is the unit a coverage claim is about, named by a hash of its canonical description: `cid = SHA-256(canonical JSON { operation, attribute, stratum definition and its version, enumeration (kind, width, rounds, key),
oracle kind, the unit of a count, the rule for expected cases })`. Change any of it and the campaign is a new one: **coverage never merges across a change of definition**.

A **stratum** is an enumerable set of cases with its own index space [0, N) and a `unrank(stratum, j)` giving the operands: the *core* significand pairs of a division (4^(p-1) by index arithmetic), a *subnormal-result strip* (s = 1 .. p + 1),
the *overflow strip*, the *closest-approach list* (index = divisor index x target x sign, constructed by 4.2), the *dropped-bit class lists* of a conversion, the *special and boundary operand cross-product* of `vectors.py`, a *relational
list* (a = b, a = 2^k b, exact quotients, b = 1 +- k ulp), and the *uniform stratum* (every encoding). For a space of N not a power of four, the index is mapped by the keyed Feistel permutation with cycle walking (4.5): `operands(stratum, i) =
unrank(stratum, perm_key(i))`. For the 32-bit exhaustive modes EX is building, the enumeration is the identity: the existing exhaustive items are *already* campaigns of this shape (`[lo, hi)` over the encodings; the driver's `intervals`
are the fold of their records, below), which is the continuity the design wants.

The soak tools would gain a mode `<op> enum <lo> <hi> <attr> <key> <stratum>` beside `<count> <seed>` (EX adds exhaustive modes in the same two files; the random modes stay as they are so the stress run's records still parse). The driver's
`Item.seed_for(n)` is replaced for the enumerated items by the store's next interval. **A stopgap that needs no ledger**: make `seed_for` collision-free (`(item index << 40) | (n << 1) | 1`, or the keyed mixer, both of which `seed_audit.py` shows
collision-free at n < 57 for the 54 items) and start n at the previous runs' highest n + 1, read from the earlier output directories; that fixes the `| 1` collision and the rerun repeat for the random items in a few lines.

### 5.3 The record

One record is one finished slice, immutable, a JSON object in canonical form (sorted keys, no spaces). Its id is the SHA-256 of its canonical bytes without the signature; the signature is over the id.

```
{ "v": 1, "cid": "<64 hex>", "stratum": "core", "lo": 0, "hi": 268435456,
  "cases": 268435456, "vm": 0, "fm": 0, "skipped": 0,
  "digest": { "alg": "sha256-merkle-4096", "root": "<64 hex>", "batches": 65536 },
  "subject": { "rtl": "<git tree hash of rtl/>", "xclbin": "<sha256>", "tile": 2, "abi": "0.18" },
  "tool": { "build_id": "<the tool's build id>", "commit": "<sha>", "cc": "gcc 11.4", "flags": "<hash>" },
  "oracle": { "kind": "host-fpu+glibc", "libm": "glibc 2.39", "cpu": "<model>", "probes": { "scalbn": "RELIABLE", "castflags": "RELIABLE", "cvtfrom": "RELIABLE" } },
  "control": { "sabotage_detected": true },
  "run": { "id": "card-stress-1016", "device": "<pseudonym>", "start": "...", "end": "...", "rate": 1.99e6 },
  "sig": { "alg": "ed25519", "key": "<hex>", "sig": "<hex>" } }
```

1,223 bytes with the fields filled to the lengths the design gives them (MEASURED, `merge_law.out` section R): a weekend of 3,287 slices is 4 MB, a decade of weekly weekends 2 GB from one device; the store is not a size problem for one device (a fleet multiplies it by its size, and a digest a record and not a hash a case is what keeps it small). **Why each field is there** is section 6.6's argument. The fields the stress driver's `leg` record already carries
(the item, the range or seed, counts, image SHA-256, tile, times, the log) are a subset. A **disagreement** is a separate record kind: (cid, index, operands, device value and flags, oracle value and flags), the unit that self-certifies.

### 5.4 The store and the fold

A store is a **set** of records, in any medium (a directory of files, a JSON-lines file, a USB stick). Merging two stores is the union by record id. **Coverage is a pure function of the set**: for each (cid, subject class), the union of the index
intervals of the records that are *consistent* (cases equal the rule's expected count for `[lo, hi)`: `hi - lo`, or `+ 8` for nextup32 and nextdown32, a rule the driver already enforces) and *clean* (no mismatch); a record that finds a mismatch
is not coverage, it is a finding. The fold also returns each interval's **multiplicity** (how many records, and from how many owners, cover it).

MEASURED on an executable model (`swp-a/merge_law.py`, 3,000 random scenarios of three stores of forty records over two campaigns and two subject classes, 80% good, 10% with a wrong case count, 10% with mismatches; every law
also has a planted wrong version that the same test catches):

| law | result |
|---|---|
| L1 merge order and grouping do not change coverage | 0 violations |
| L2 duplicate records do not change coverage | 0 |
| L3 coverage by interval union equals an independent bitmap of the same records | 0 |
| L4 adding a record never reduces coverage | 0 |
| L5 a record with a wrong case count, or that found a mismatch, is not coverage | 0 |
| L6 records of one subject class never count for another | 0 |
| L7 coverage never exceeds the space, though the cases run may (ten devices on one slice: 10 N run, N covered) | 0; the plant that sums lengths gives coverage above N |
| the plant that ignores the subject class credits half the space to a build that ran nothing | caught |

A **subject class** is what the coverage is evidence about. The default proposed: the git tree hash of `rtl/` together with the arithmetic-relevant generics, so that every image built from the same RTL (the single, the quad and the deep share the
tile's arithmetic) counts for the same class, and a rebuilt bitstream with unchanged RTL does not reset coverage while a changed RTL does. Whether the three images are one class is a decision for Logan (question 4), because the stress run
served the single and the deep almost nothing of any exhaustive item (2.4). The same design applies to the **software backend** as a subject (the library's identity) and to the **host CPU** as the subject of the 33 host items.

### 5.5 Resume, shards, and who runs what

A device asks the store for the lowest uncovered interval of a stratum at or after its cursor; with D devices the **static partition** (device d takes chunks of 2^28 indices with chunk number congruent to d modulo D) needs no coordinator and is
collision-free, and a coordinator or a shared store can hand out intervals; **leases are optional because duplicates are harmless** (L2). A slice that does not finish writes no record and is simply uncovered: the driver's existing policy (a
slice that timed out or lost the device is run again, a slice that fails twice is quarantined and recorded) carries over unchanged. The run's own `metrics.jsonl` stays as it is, the append-only record of the run; the ledger is the cross-run, cross-device
file beside it. Because the enumeration is stateless, a device resumes after a crash, an image reload or a week by reading the store: **nothing is kept in the driver's memory that the store does not hold** (the stress driver already rebuilds
its state from `metrics.jsonl` alone, a property this keeps).

### 5.6 Re-checking a slice

- **Replay is exact**: `(cid, lo, hi)` gives identical operands on any backend and any host (the stream's dependence on the compiler's draw order, 2.4, disappears with the permutation, whose C and Python implementations agree on 128 vectors).
- **Which slices**: deterministic from the store, so anyone can recompute the plan: every record whose id hash satisfies `hash mod round(1/r) == 0` (a re-check rate r, say 5%), every record whose tool build or subject is new, and the records
  adjacent to any finding.
- **How**: run the slice on the software backend (`libcft`, whose agreement with the golden model the existing gates hold) or on a second device, and compare the **digest**: a Merkle root over the per-batch SHA-256 of the outputs and flags of
  the tool's 4,096-case batches. Equal roots are a confirmation (a second record for the interval, from another device or owner, multiplicity 2). A difference is **localised by descent**: comparing nodes from the roots down finds the first
  differing batch in at most 13 hash comparisons among 4,096 batches (MEASURED, worst of 300 trials, against a scan of 4,096), and one batch (4,096 cases) is rerun lane by lane to name the operands, which then go to the golden model for
  arbitration.
- **What it costs**: a replay on the software backend runs at the card run's own rate for the host items (0.79 to 1.91 times it, MEASURED) and at 0.06 to 0.46 of it for the tile items (the card is 2.2 to 16 times faster), so a 5% re-check of one
  div32 item's weekend (7.2 x 10^8 of its 1.45 x 10^10 cases) on the software backend at its measured 0.155 M/s is 4,700 s, **1.3 hours of one core an item a weekend** (COMPUTED from `sw_rates.out`, BELIEVED as a planning figure); a host item's 5% costs a twentieth of its own run.

### 5.7 Growth on the card's weekly time

COMPUTED from the final record's rates; "a weekend" is 219,550 s on the card (the final run's). "As run" is the family's cases summed over its attributes and the three images (`sweep_cost.out`, Table 6); "a whole weekend could add" puts all of
the weekend on the one item, with four tiles, at its quad rate (Table 4).

| space | what a weekend adds, as run | what a whole weekend could add | weekends of one whole card to finish the reduced space (L1) | what the strata add |
|---|---|---|---|---|
| div32, all four attributes | 6.0 x 10^10 cases of 7.4 x 10^19 (L0) | 1.78 x 10^12 | 3,209 | closest approach reached by volume (2,304 hits); the constructed list adds the rest |
| div64 | 5.9 x 10^10 of 1.4 x 10^39 | 1.35 x 10^12 | none (10^19 years) | closest approach, exact quotients, subnormal ties: constructed |
| sqrt64 | 6.0 x 10^10 of 7.4 x 10^19 | 1.34 x 10^12 | 20,235 | sqrt(1 + ulp)-class inputs: constructed |
| rem32 (host) | 1.2 x 10^10 | 4.0 x 10^11 | 47,873 | longest exponent gaps; CPUs, not the card |
| conv64to32 (host) | 5.9 x 10^10 | 5.5 x 10^12 | 66,731 | the 377,664-case class list: 0.06 s |
| rint64 | 7.4 x 10^10 | 1.7 x 10^12 | 414,877 | class list: seconds |

So **a weekend of the whole card moves no 2^64 space measurably; what accumulates is the floor (1/W), and what completes is the class level and, with fleets, the reduced spaces**. Under a ledger the weekly time is spent where it adds: the strata first (minutes), then enumerated L1 chunks
rotated across the tile items; and **the host items off the card**, which gives the tile items about twice their sweep time (the run's sweep waves, about 31 hours of the 61 on the assumption of four jobs at once on the quad, put 53% of their job-seconds on host items, 2.3; COMPUTED).

### 5.8 What the stress run's coverage becomes

Its exhaustive items are in the ledger's native form already (an identity enumeration over [0, 2^32), intervals, the exact-count rule, the image and tile in the record): the 249 exhaustive slices import as records, with the caveat that
the driver recorded the image SHA-256 and the tile but not the RTL tree hash or the oracle's probes, so the subject class and oracle fields would be filled from the run's `run_start` record (the commit f0693b2, the three image hashes). Its random slices are *streams*, not
intervals; they import as legacy `stream` records `(item, seed, count)` that never merge with an enumeration's and that count only toward the floor of their own distribution: 1.3 x 10^12 cases, as run.

## 6. The long-term full sweep

### 6.1 Device-years for each space at the measured rates

COMPUTED (`sweep_cost.out` Table 2): the sum over the family's attributes of space / (the per-job median rate of its item on the quad), one quad of four workers, a Julian year. A worker is a **tile** for the tile items and a **CPU core** for the host items,
so for a host item the "quad" column is four cores. The unit of each space is the unit of its rate (2.2): scaleb's spaces are in checks.

| space (unit) | runs | attributes | one quad | workers for a decade | for a year | for a month |
|---|---|---|---|---|---|---|
| class64 (fp64 encodings) | host | 1 | 6,584 years | 2,634 | 26,336 | 316,028 |
| nextup64 | host | 1 | 1.17 x 10^4 | 4,676 | 46,760 | 561,113 |
| nextdown64 | host | 1 | 1.57 x 10^4 | 6,266 | 62,652 | 751,817 |
| logb64 | host | 1 | 2.28 x 10^4 | 9,130 | 91,294 | 1.10 x 10^6 |
| conv64to32 | host | 4 | 1.0 x 10^5 | 40,143 | 401,428 | 4.8 x 10^6 |
| cvtto64 (fp64 operands x 4 targets) | host | 5 | 2.88 x 10^5 | 115,241 | 1.15 x 10^6 | 1.38 x 10^7 |
| cvtfrom32, i64 and u64 sources (2^64 lanes) | host | 4 | 3.03 x 10^5 | 121,303 | 1.21 x 10^6 | 1.46 x 10^7 |
| cvtfrom64, i64 and u64 sources | host | 4 | 3.10 x 10^5 | 123,923 | 1.24 x 10^6 | 1.49 x 10^7 |
| div32 (fp32 pairs, 2^64) | tile | 4 | 3.02 x 10^5 | 120,803 | 1.21 x 10^6 | 1.45 x 10^7 |
| rem32 (fp32 pairs) | host | 1 | 3.17 x 10^5 | 126,997 | 1.27 x 10^6 | 1.52 x 10^7 |
| sqrt64 | tile | 4 | 3.81 x 10^5 | 152,557 | 1.53 x 10^6 | 1.83 x 10^7 |
| rint64 | tile | 5 | 3.83 x 10^5 | 153,140 | 1.53 x 10^6 | 1.84 x 10^7 |
| scaleb64, 27 directed exponents (2^64 x 27 checks) | tile | 4 | 1.16 x 10^6 | 462,052 | 4.62 x 10^6 | 5.54 x 10^7 |
| scaleb64, 4,198 wide exponents | tile | 4 | 1.8 x 10^8 | 7.18 x 10^7 | 7.18 x 10^8 | 8.62 x 10^9 |
| div64 (fp64 pairs, 2^128) | tile | 4 | 7.18 x 10^24 | 2.87 x 10^24 | 2.87 x 10^25 | 3.44 x 10^26 |
| rem64 (fp64 pairs) | host | 1 | 4.41 x 10^25 | 1.76 x 10^25 | 1.76 x 10^26 | 2.12 x 10^27 |

The brief's range, the lead's estimates (class64 about 6,600 years to rem32 about 320,000) is reproduced; the 128-bit spaces come to 7.2 x 10^24 years (div64) and 4.4 x 10^25 (rem64), a little above his "about 10^24 to 10^25". The scaleb64 wide range of 4,198 exponents is derived by the argument of `sweep_cost.py`'s
`scaleb_wide`: for n at or above emax - emin_subnormal + 1 = 2,098 every nonzero finite operand overflows and for n at or below -(emax + 2 - emin_subnormal) = -2,099 every one lands below half the smallest subnormal, so the delivered value depends on sign and attribute only
(the same argument gives EX's [-278, +277] = 556 at fp32; COMPUTED, and for fp32 equal to EX's BELIEVED figure). **No number of devices a project could field moves any of these into a decade except by the reductions of 4.3**; the reduced spaces and their device counts are in 6.4.

### 6.2 What bounds each item's rate

The measurements tell some of it. By family (COMPUTED from the records unless marked):

| family | bound | evidence |
|---|---|---|
| **host** (class, logB, next, conversions, remainder) | the soak process's CPU core: operand generation, the library's host code, the native oracle, the compare | MEASURED: the software backend on one core runs at 0.79 to 1.91 times the card run's rate for all 16 host jobs (the device is only opened); rem: the host's quotient-bit walk, up to 2,096 steps a pair at fp64, with a quarter of the pairs aimed at the longest gaps (READ), which is why rem64 runs at 0.061 M/s, 16 microseconds a case (several hundred steps on average at tens of nanoseconds a step: BELIEVED); the cheapest items are a 30 to 50 ns loop (class32 and class64: 30 and 27 ns a case on the software backend, MEASURED) |
| **tile: division, square root** | the tile's instruction issue, with slack; not the host | COMPUTED: if the whole-divide program runs one instruction a beat at 108 M beats a second (docs/VALIDATION.md, 2026-09-08) on 8 fp32 or 4 fp64 lanes (docs/ARCHITECTURE.md), a tile does 4.11 (div32), 2.04 (div64), 4.65 (sqrt32) and 2.29 (sqrt64) M/s from the programs' 210, 212, 186 and 189 instructions (MEASURED by `tile_counts.py`, `len(Program.insns)`); the measured 2.02, 1.54, 1.95 and 1.52 (rne, quad) are **49%, 75%, 42% and 67%** of that (`tile_counts.out` T3), and no measured rate of any attribute exceeds its bound. The host side is at most about 5% of a job (MEASURED upper bound, 2.5). BELIEVED: the model's instruction timing, and that the on-chip route is the one taken |
| **tile: rint, scaleb** | the per-call path of composed passes, not the arithmetic | rint is 4 passes a call (copysign, add, subtract, copysign: READ, `clause5.c` lines 320 to 327; MEASURED by `tile_counts.py`, 4 for every one of 200 operands) and the soak makes two calls an operand (`clause5_soak.c` lines 399 to 402 and 431 to 434, exact = 0 and 1), so 8 passes an operand; scaleb takes 0 to 3 multiplies a check, 19 passes for the 17 directed exponents at fp32 and 29 for the 27 at fp64 (`tile_counts.out` T2). At 4,096 elements a pass (`CFT_CHUNK`, READ in `cft_config.h`) the beat bound is 108 M rint32 operands/s a tile (8 lanes x 108 M beats / 8 passes), against 2.1 measured, **2% of it** (rint64 and scaleb64 about 4%): the other 98% of a job is call, staging and host (COMPUTED from the measured rates, `tile_counts.out` T5: about 240 microseconds a pass for rint32 and 250 for scaleb32, whose job includes the host's 17 oracle loops, against 4.7 microseconds of tile time for 4,096 fp32 elements; rint64 and scaleb64 about 260 and 280 against 9.5). BELIEVED |

Three more facts bound the *kind* of bound. The four tiles' medians agree (max/min across the four tiles: median 1.02, widest 1.18, MEASURED), so jobs on different tiles do not interfere much; a tile in the quad runs at 0.90 to 0.98 of the single image's rate for division
and scaleb32 (the single ran alone; `tile_counts.out` T4 compares 16 items, 0.90 to 1.25, scaleb64's single-image medians on four slices each swinging between 11.0 and 14.5 M/s), so four at once cost a tile at most about 10% (MEASURED; the cause is not known) and
**no shared resource (the bus, the box's 36 threads) is the main limit yet**. But
on the quad rint32 moves about 0.8 GB/s and scaleb32 0.8, rint64 1.5 and scaleb64 1.4 (4 tiles x passes x three words an element, COMPUTED, `tile_counts.out` T5; two words read and one written is BELIEVED): a quarter to a third of the 2.3 to 3.3 GB/s staged-traffic wall measured in 2026-09 (READ, `docs/VALIDATION.md`)
at fp32 and about half to two thirds at fp64, so **the call-bound composed items would meet the bus wall within a factor of about 3 to 4 (fp32) or 1.5 to 2.3 (fp64) of their present rate if the call path were cheapened** (BELIEVED), which is the reason a sweep image keeping the cases on the device matters. Each job is one serial process: generate, oracle, stage, run, wait, read back, compare, with **no overlap between the host and the device**. What the measurements **cannot** tell is the split between the tile's arithmetic and the call path for div and sqrt
(the two models of 6.2 fit within a factor of two of the data), and the experiment that decides it is cheap and needs the card: rebuild both soak tools with `BATCH` 4x larger and 4x smaller (a compile-time constant, `#define BATCH 4096`) and run one slice a tile op: a rate that scales with BATCH is call-bound, one that does not is tile-bound. It is not in this parcel (the card is not mine).

### 6.3 What would move the rates

COMPUTED where a number is given, BELIEVED otherwise; the factors multiply only if the bounds are separable, which 6.2 says they are not.

- **For the host items, cores and loops, not cards.** The box has 36 threads and the sweep used 4 (11%); running the 33 host items as CPU jobs raises their throughput by up to 9 times on the same machine (36 / 4), and no card is opened. A purpose-built loop would beat the soak's 30 to 50 ns a case (class64: 27 ns at the software backend's whole-loop 37 M/s, MEASURED) by a large factor,
  BELIEVED 10 to 50 times with SIMD; the class-level and L1 reductions are then the way to use it.
- **For the tile items, tiles.** `docs/PLATFORMS.md` (READ, with its dates) prices candidates by tiles a part holds: the U50 holds 4 (built); a used U200 5 (at $1,150 to $1,373, 2026-09-05), a used U250 7 by area and about 5 by bandwidth, a BittWare CVP-13 8 (budget A). Tile count scales a sweep linearly (the property `docs/SCALING.md` states: which tile computes an index cannot enter the answer).
  The clock: the single tile closed 175 MHz and the conformance set agreed on the card (`docs/VALIDATION.md`, 2026-09-24, READ), against the quad's 135: +30% (BELIEVED for a quad that closes there).
- **For div and sqrt, the program and the pipeline.** If the model of 6.2 is right, at most 1.3 to 2.4 times is left between today's rates and the instruction-issue bound (75% at div64: little; 42 to 49% at fp32); a shorter correctly rounded program or more lanes moves the bound itself.
- **For rint and scaleb, bigger batches.** If the call path is 98% of a job, a batch large enough that the tile's time matters could raise them until the staged-traffic wall, about 3 to 4 times at fp32 and 1.5 to 2 at fp64 (BELIEVED); the experiment above decides.
- **A sweep image.** The permutation is a handful of multiply-xorshift rounds, a few DSPs and LUTs per tile, and a digest is a hash core: with **the enumeration and the digest in the fabric** the host exchanges only (lo, hi) and a root a slice, nothing per case crosses the bus, and the oracle (the host FPU, the only independent one) is run separately, on CPUs, against the same indices, with the digests compared. That makes the tile the only bound for the tile
  items, at most about 2 to 2.4 times today's rate for fp32 and 1.3 to 1.5 times for fp64 by the arithmetic above (`tile_counts.out` T3), BELIEVED, and it moves the host-side work (the oracle's 5% of a job) off the card's critical path; it is the design to consider **after** the ledger and the reductions, not before.

**Taken together no lever moves a raw 64-bit sweep into reach**: they multiply to perhaps 10^2 to 10^3 against raw spaces of 10^4 to 10^6 quad-years. They do matter for the reduced spaces of 6.4.

### 6.4 How many devices make a full sweep take a decade, a year, a month

For the **reduced** spaces of 4.3 (COMPUTED, `symmetry_check.out`; a quad is four tiles for the tile items and four cores for the host items; "weekends" is whole-card weekends of 219,550 s):

| reduced space | level | one quad | quads for a decade | for a year | for a month | weekends of one card |
|---|---|---|---|---|---|---|
| div32, 4 attributes | L1 | 22.3 years | **3** | 23 | 268 | 3,209 |
| sqrt64 | L1 | 141 | 15 | 141 | 1,690 | 20,235 |
| rem32 (host) | L1 | 333 | 34 | 334 | 3,997 | 47,873 |
| scaleb64, wide range | L1 | 435 | 44 | 435 | 5,218 | 62,501 |
| conv64to32 (host) | L1 | 464 | 47 | 465 | 5,572 | 66,731 |
| rint64 | L1 | 2,890 | 289 | 2,887 | 34,637 | 414,877 |
| cvtto64 (host) | L1 | 5,660 | 567 | 5,661 | 67,928 | 813,642 |
| div64, rem64 | L1 | 10^19, 5 x 10^21 | none | none | none | none |
| every class-level sweep (L2) | L2 | seconds to minutes | one tile | one tile | one tile | well under one |

**A fleet of 3 quads would finish fp32 division's reduced space (core and strips, all four attributes) in a decade, 23 in a year**; fp64 square root needs 15 for a decade; remainder at fp32 (host) 34 groups of four cores for a decade, which is 136 cores and no card at all. The fp64 two-operand
spaces have no reduction that helps: **their coverage is hard cases, classes and the detection floor, not a sweep**, which is the point of 4.2 and 4.3.

### 6.5 What would be swept, then

A project that wanted a defensible statement "swept in full" could mean, in order of cost: (i) the 32-bit operand spaces, exhaustively (EX; minutes to hours each; 46.5 hours for the wide scaleb32); (ii) every **class** of every operation at every format (L2; seconds to minutes; PLAUSIBLE until the rounding unit is proved against the decision rule); (iii) every constructed hard case of division
and square root at fp64 and fp128 for a stated list of targets (minutes); (iv) **fp32 division, remainder and fp64 square root at the value level** (L1; 3, 15 and 34 quads for a decade, 23, 141 and 334 for a year; PROVED for the golden model, PLAUSIBLE for the tile where the strips and the sign and subnormal-operand logic are covered by their own strata); (v) the rest is statistics with a stated
floor. Each claim should name its level. That naming is question 5.

### 6.6 What a contributed result must carry to be trusted

**The project's rule is that the golden model is the authority.** Everything below is that rule applied to a result produced elsewhere.

*An asymmetry shapes the design.* A **failure** carries its own proof: (operands, device value, oracle value) is rechecked on the golden model in microseconds by anyone, and a failure that does not recheck is the contributor's host, not the tile. A **pass** proves nothing by itself: it is a claim that a device ran a slice and agreed, and the damage of a false one is
a *false hole in the coverage*, not a false defect. So the whole trust problem is: **how far can a claimed pass be believed, and what does a larger claim need?** There are three populations, and the project is in the first: (a) its own devices, honest and accidentally faulty (a flipped bit in a host's memory, a stale build, the wrong image, a dying card); (b) vetted collaborators; (c) anonymous
volunteers, where a contributor who gains by claiming credit may fabricate. (The Alveo U50 is not a volunteer's machine; the Kintex-7 port, whose tile figures `docs/PLATFORMS.md` carries, is the route to cheap devices, and it is why (c) is not idle.)

**What a record must carry** (5.3), and what each field buys:

| field | what it lets a verifier do |
|---|---|
| `cid`, `stratum`, `lo`, `hi` | replay the slice exactly on any backend; place it in the fold |
| `cases` and the counts, with the rule | refuse a slice whose count is not the rule's (the driver already does) |
| `digest` (Merkle root of the per-batch SHA-256 of outputs and flags) | confirm against a second device or the software backend by equality; localise a difference in about 2 log2 n hash comparisons; it is the one field that lets a re-check be a comparison and not a full second claim |
| `subject` (RTL tree hash, xclbin SHA-256, tile, ABI) | say what the coverage is about; refuse a build not on the allow-list of known-good hashes (the manifests' SHA-256s) |
| `tool` (build id, commit, compiler, flags hash) | refuse a tool that is not the reproducible build of a named commit |
| `oracle` (kind, libm, CPU, the probes' verdicts) | the instrument's identity: the oracle is the host FPU and libm, not the golden model, and its probes (RELIABLE or degraded) change what was compared |
| `control` (the sabotage control detected its planted flip on this build, this session) | the harness could fail at the time (the project's rule for every harness) |
| `run` (a device pseudonym, times, the rate) | plausibility (a rate above the measured maximum for that op and tile count, 1.5 times, is refused), and credibility accrual |
| `sig` (Ed25519 over the record id) | attribution; the repository already has Ed25519 and SHA-512 in Python (`python/cft_golden/ed25519.py`) and in C (`cft-audit`), and the certificate format's detached signature (`docs/CERTIFICATES.md`) is the same device |

**What the verifier does**, in order: check the record's form, signature, key and the allow-lists; check the rate's plausibility; **replay a sample on the software backend** (selected by the record-id hash, 5% to 10%; a tile item's replay is slower than the card's run by 2 to 16 times, a host item's costs the same as the run); **arbitrate every disagreement by the golden model**, which decides whether the finding is the
device, the oracle (a libm quirk), or the contributor; **plant known-fault slices** (a honeypot is a slice whose sabotage control is keyed by a secret: the tool flips the result of a keyed lane, an honest run reports exactly that mismatch, a run that reports a pass over it is a fabrication; the soaks' `CFT_SOAK_SABOTAGE` is this mechanism with the key fixed at lane 0, and Sarmenta's spotter task [29] is its published relative);
and for a slice that decides a release claim require **two owners**' equal digests. Spot-checking at a re-check rate r catches a fraction f of fabricated slices with probability 1 - delta if k >= ln(delta) / ln(1 - f) slices are re-run: 458 for f = 1%, delta = 1% (COMPUTED); but a *coverage* claim is about every slice, not a fraction of them, so for population (c) the right design is a quorum, at twice the device time, with the spot-checks as the defence against collusion.

**What a record can never prove**: that a specific physical device computed it (nothing on the U50 attests; BELIEVED), or that a malicious contributor did not run the golden model in software, slowly, and report the card's identity (a rate above the measured maximum refuses the fast fabrications; a slow honest-looking one costs the fabricator more than running the card). The honest statement of a contributed coverage is therefore **"covered by K independent owners, each of whom the verifier replayed or
quorumed"**, not "verified", and the record's multiplicity is where that K lives.

## 7. Recommendations, ranked and phased

Ranked by what they find for what they cost; effort is mine (BELIEVED), card time COMPUTED. A recommendation is a proposal to Logan and the lead: **nothing here has been built or changed**.

| rank | do | finds | card time | effort | evidence |
|---|---|---|---|---|---|
| 1 | **Take the 33 host items off the card**: run them as CPU jobs on the box's idle threads (the soak tools without `CFT_SOAK_ARTIFACT`), beside the card's sweep; give the card's sweep time to the 35 tile items | nothing new by itself; the tile items get about twice their sweep time and the host items up to 9 times their throughput; EX's exhaustive host modes (conv32to64 3 min, cvtto32 2 s a slice per core) run anywhere | negative | hours (the lead's schedule) | 2.3, 6.2, 6.3 |
| 2 | **Make the seeds collision-free and let n continue across runs** (a stopgap): the seed `(item << 40) + 2n + 1` (schedule A of `seed_audit.py`, which writes the same number with shifts and an or), or the keyed mixer, and start n at the highest n of earlier output directories + 1 | a rerun stops repeating (about 96% of draws today), the floor improves as 1/W; four operations lose their 37% repeated operand counts | none | hours, in `hw/card_stress_lib.py` and the tools' parsers | 2.4, 5.2 |
| 3 | **The BATCH experiment**: rebuild the soak tools with `BATCH` 4x larger and smaller, one slice a tile op | tells whether rint, scaleb, div and sqrt are call-bound (rint and scaleb up to about 1.5 to 4 times from a constant, until the bus wall) or tile-bound | about one card-hour | an hour's work | 6.2 |
| 4 | **Constructed hard-case lists as directed sweep items** for div and sqrt (closest approach to a midpoint and to a representable number, exact quotients, ties in the subnormal strip, b = 1 +- k ulp, powers of two), conversions' dropped-bit patterns, scaleb's strips | the classes with probability near 10^-16 a draw at fp64 (a weekend expects 4.3 x 10^-6 of them) which the repository's own failure history shows are where slips live | 10^6 pairs per (format, target, sign) is 0.16 s on a quad | days (the instrument is the prototype) | 3.1, 4.2 |
| 5 | **Class-level sweeps (L2)** for every unary and conversion operation: a representative per class plus a walking-ones set | structural defects of the rounding unit, completely, if the tile has the structure of 4.3; conv64to32's list is 377,664 cases, 0.06 s | seconds | days a family, plus the structural argument | 4.3, G5 |
| 6 | **The coverage ledger**: records, the fold, `next_uncovered`, the keyed-permutation enumeration for enumerated strata, per-batch digests in the tools | nothing itself; it is what makes 7 to 9 add up across weekends and devices | none | weeks (the tools' `enum` mode and digest, the driver, the report, tests) | 5, 4.5 |
| 7 | **Rotate enumerated L1 chunks** of the tile items (div32 core and strips first) through the weekly schedule | all defects of the reduced function, over 3,209 whole-card weekends for div32: so only with more than one device | the weekly sweep share | days once 6 exists | 5.7, 6.4 |
| 8 | **The published binary64 hard-to-round tables as the math routines' corpus** once exp, log, sin, cos, tan run on the card | the mark-and-replay path (2.9 x 10^-4 marked lanes a random weekend at G = 46, 1.2 x 10^-3 at G = 44) | minutes | days, plus permission to download | 4.2 |
| 9 | **Prove the rounding unit against the decision rule at small width** in `formal/` | turns L2's PLAUSIBLE into PROVED at the unit's parameters | none | days to weeks | 4.3, 4.7 |
| 10 | **Second owner, signing, replay verifier, honeypots, quorum** | makes a contributed coverage believable | 1 + r | weeks to months, only when a second owner exists | 6.6 |
| 11 | **A sweep image** (the enumeration and digest in the fabric) | moves the tile items to the tile's own bound (about 2 to 2.4 times at fp32, 1.3 to 1.5 times at fp64), frees the host | a build | months; after 6 and 7 | 6.3 |

**Phases.**

- **Phase 0, before the next weekend (hours).** Ranks 1 and 2, and rank 3 as a one-card-hour slot: they cost almost nothing and change what the next weekend is worth.
- **Phase 1, the month.** Ranks 4 and 5 (the hard-case and class generators, each a seconds-to-minutes item in the existing driver as a new `Item` kind), and a review of the ledger design with Logan's answers to questions 4 to 6.
- **Phase 2, the quarter.** Rank 6 (the enumerated mode and digests in the tools, the ledger in the driver and the report), rank 7 for div32 and sqrt64, rank 8 as the math routines reach the card, rank 9 for the rounding unit.
- **Phase 3, the year.** Rank 10 when a second owner or a second device exists; the fleet decision of questions 7; rank 11 evaluated against the BATCH result.
- **Phase 4, long term.** Fleets for the reduced spaces that justify them (6.4), and the project's statements of "swept in full" at a named level (6.5).

**Questions Logan must answer**

1. **Host items** (2.3, 6.2). The 33 libcft host-code items do not use the tile. Do they leave the card's weekend, and may the lead run them as CPU jobs on the box's idle threads (at `nice -n 10`) beside it? (Recommended: yes.)
2. **Seeds** (2.4). Approve the stopgap fix of `seed_for` and the continuation of n across runs (rank 2), or go straight to the enumerated mode? (Recommended: the stopgap now, the enumeration with the ledger.) Does a build-order-independent draw (two statements for the banded exponent) go in the tools with it?
3. **Hard cases** (4.2). Approve a generator for the hard-case and class lists, and say where it lives: inside the soak tools as new modes, or as its own tool. May it adopt UCBTEST's number-theoretic generators or the published binary64 tables (each needs a licence check and a download I did not make)?
4. **What coverage is about** (5.4). Per image, or per RTL tree and generics (the single, quad and deep as one class)? The stress run served the single and deep images 0 to 6% of any exhaustive item; if coverage is per image, they need their own sweep share. (Recommended: per RTL tree, with the three images reported separately.)
5. **Naming "swept in full"** (6.5). May a claim of full coverage be made at the value level (L1, PROVED for the model, PLAUSIBLE for the tile) and the class level (L2, PLAUSIBLE), provided each statement names its level and what the tile's structure is assumed to be?
6. **Who contributes** (6.6). Only the project's own devices for now, or vetted collaborators too? Is an Ed25519 key per owner acceptable, and may records carry a pseudonymous device id?
7. **A fleet** (6.4). Is fp32 division's reduced sweep (3 quads for a decade, 23 for a year) a goal, or is the class-level and hard-case plan the target for 64-bit-and-below spaces? The same for sqrt64 (15 quads for a decade).
8. **The oracle** (2.5, 6.6). Keep the host FPU and libm as the only sweep oracle, with the golden model and the software backend only for re-checks and arbitration? (Recommended: yes; it is the independent one.)
9. **The card** (6.2). May the lead spend one card-hour on the BATCH experiment? It decides whether the call path or the tile is the limit for four of the eight tile families.
10. **Order against the math round** (4.2). The hard-case corpus for the math routines needs the routines on the card first; does the math round come before ranks 6 to 9?

## 8. What this study does not establish

1. **Tiny-format exhaustion proves the lemmas for e4m3 and e5m6 only.** For p = 24 and 53 the sign, mode and scale reductions rest on the arguments written in 4.3 (the definitions of the rounding directions; rounding position a function of the exponent alone; the no-midpoint lemmas of [5] and [7]) and, for the mirror lemma only, on samples at fp32, fp64 and fp128 (0 violations in 6,000). The scale lemma and the class structure were not sampled at the real formats.
2. **The L1 strip counts are an upper bound**, attained at e4m3 (448 keys, the bound exactly); at p = 24 and 53 they rest on the argument.
3. **L2 assumes a structure of the tile's rounding unit that nothing here tests**; `formal/` could (4.7).
4. **The software-against-card ratios** compare an i5-12400F desktop with a box CPU not in the record, one short run a job; their bands were set after the raw rates were seen (the script says so).
5. **The bound of the tile items is undecided**: the two models fit within a factor of two (6.2). The on-chip-program route for div and sqrt is BELIEVED (cft.h says the choice is automatic), the instruction timing of the 108 M beats a second model is BELIEVED, and the BATCH experiment is not run.
6. **The permutation's quality tests are z-score heuristics**, not BigCrush; its speed is one core of one CPU; the finalizer constants are those of the MurmurHash3 family (BELIEVED provenance), and what is measured is their quality.
7. **The seed-collision effect is judged small, not measured against a defect** (BELIEVED), and the draw-order test covers gcc 11 and 12 at -O0 to -O3 only.
8. **Hard cases are built and verified for division at p = 24, 53 and 113, and for square root by an exhaustive scan at fp32 only**; fp64 square root's construction is argued from the structure of odd squares, conversions' and scaleb's lists are argued, not built.
9. **Several sources were cited from search summaries or listings** (section 10 marks each); the ARITH 2026 paper and part I of [5] were read from text extractions of their PDFs, not rendered, so a table or a formula in them may have been read badly.
10. **The final `metrics.jsonl` is not in the repository** (8 MB); `stress_records.py` reproduces its tables only with the lead's copy (SHA-256 above). The derived `stress-final-item-rates.txt` and the copied `stress-final-report.txt` are in `docs/studies/swp-a/`.
11. **The soaks cover fp32 and fp64 against the host FPU**; fp128 and fp256 have MPFR parity (3.4) and the repository's tests. The methods here extend to them (the constructed division cases are verified at p = 113); a sweep of them is out of the question.
12. **The record format and the store are a design**; the merge laws are checked on a model, not on an implementation.
13. **A weekend's arithmetic takes the stress run's per-job rates as given**; a different image, clock or batch changes them, and EX's new modes in the same two files may change what `count` means for the items they touch. The units are those of 0b77387.

## 9. The instruments and their captured runs

All are in `docs/studies/swp-a/`, with their captured output beside them. They read or build nothing under `host/`, `hw/`, `rtl/`, `python/` or `programs/` (the driver's and the golden model's libraries are imported read-only; the host tools are built in a scratch copy in WSL cft2204, Ubuntu 22.04, gcc 11.4, glibc 2.35,
Python 3.10; every Python script gives byte-identical output under Windows Python 3.12 and under that Python 3.10, compared with cmp on 2026-10-19 (`seed_replay_check.py` on the run directories of the Windows capture); the shell scripts, `perm_check.c` and `sha_speed.sh` need WSL). Every script that checks anything exits nonzero if a CHECK fails and has controls or plants that must go red (`sha_speed.sh` only measures). The times are those of the final pass on the desktop.

| script | measures | capture | run |
|---|---|---|---|
| `tool_probe.sh`, `tool_probe_plants.sh` | what a count is per operation; the operand stream is a function of (op, seed) and not the attribute; the seed's low bit forced to 1 (the collision of 2.4); five planted defects each caught | `tool_probe.out`, `tool_probe_plants.out` | `bash tool_probe.sh DIR` (7 s); `bash tool_probe_plants.sh HOSTDIR WORK` (2 min) |
| `seed_replay.sh`, `seed_replay_check.py` | the real driver's dry run, three invocations: a new `--out` replays, `--resume` continues | `seed_replay.out` | `bash seed_replay.sh WORK PYTHON` (4 to 8 min: 49 to 164 s an invocation, by the desktop's load) |
| `stress_records.py` | the final record: totals, the derived rates, the seed schedule as run, coverage by image, tiles; six tampered records caught | `stress_records.out`, `stress_records_controls.out`, `stress-final-item-rates.txt` | `python stress_records.py METRICS --report stress-final-report.txt --write-rates stress-final-item-rates.txt` (under 1 s; `--controls` 4 s) |
| `sweep_cost.py` | the full-sweep cost of every space; the units; the two quoted extremes reproduced; the per-family totals of the run; the union bound of 4.4; seven mutated inputs caught | `sweep_cost.out`, `sweep_cost_controls.out` | `python sweep_cost.py` (under 1 s; `--controls` 1 s) |
| `seed_audit.py`, `eval_order.sh` | the port of the tools' generator held to the real tools (288 lanes); the draw order on seven builds; the schedule's collisions and two collision-free candidates | `seed_audit.out`, `eval_order.out` | `python seed_audit.py` (under 1 s); `bash eval_order.sh HOSTDIR WORK` (14 s) |
| `perm_check.c`, `.py`, `.sh` | the Feistel permutation: bijectivity by exhaustion to 2^32, quality by rounds, cycle walking, accounting, speed, 128 vectors reproduced in Python | `perm_check.c.out`, `perm_check.out`, `perm_check.speed.out` | `bash perm_check.sh python3` (about 3.5 min) |
| `symmetry_check.py` | the reductions on the golden model by exhaustion on e4m3 and e5m6; the reduced sizes and device counts | `symmetry_check.out` | `python symmetry_check.py` (1.5 min) |
| `hardcase_div.py` | closest-approach division and square root: construction, the exact arbiter, the sampler's reach, the repository's failure families, a planted defect | `hardcase_div.out` | `python hardcase_div.py` (27 s) |
| `merge_law.py` | the store's laws on a model; Merkle localisation | `merge_law.out` | `python merge_law.py` (8 s) |
| `sha_speed.sh` | SHA-256 throughput of one core (the digest's cost, 4.6) | `sha_speed.out` | `bash sha_speed.sh` (40 s) |
| `tile_counts.py` | the whole-divide and whole-square-root programs' instruction counts; the passes of the composed routes (rint 4 a call, scaleb 19 and 29 over the directed lists); the issue-bound model against the measured rates; the quad against the single image | `tile_counts.out` | `python tile_counts.py` (under 1 s) |
| `sw_rates.sh`, `sw_rates_compare.py`, `host_only_rate.sh` | the software backend's rate per job against the card's; the host side alone | `sw_rates.out`, `sw_rates_compare.out`, `sw_rates_compare_controls.out`, `host_only_rate.out` | `bash sw_rates.sh DIR` (2 min); `python sw_rates_compare.py`; `bash host_only_rate.sh HOSTDIR WORK` |

The inputs are the stress run's files: `stress-final-report.txt` (a copy of the final report), `stress-final-item-rates.txt` (derived from the final `metrics.jsonl` by `stress_records.py`), and the lead's `stress-item-rates.txt` and `stress-report-0655.txt` (unchanged, the cross-check).

## 10. Sources

Verification status is stated for each: **READ** means I read the page or file named; the others were taken from a search result, a listing or a citing paper, and the entry says so. Quotation is limited to a few words.

1. M. Aharoni, S. Asaf, L. Fournier, A. Koifman, R. Nagel, "FPgen - A test generation framework for datapath floating-point verification", HLDVT 2003, published 12 November 2003. https://www.research.ibm.com/publications/fpgen-a-test-generation-framework-for-datapath-floating-point-verification (READ: title, authors, venue, date, abstract).
2. L. Fournier, S. Asaf, "FPgen - A Deep-Knowledge Test-Generator for Floating Point Verification", IBM Research Report H-0140, 2002. https://dominoweb.draco.res.ibm.com/reports/H-0140.pdf (NOT READ: the server refused the connection; title, authors and the "All IEEE Types" model from a search summary).
3. A. Ziv, M. Aharoni, S. Asaf, "Solving range constraints for binary floating-point instructions", 16th IEEE Symposium on Computer Arithmetic (ARITH-16), 2003. https://research.ibm.com/publications/solving-range-constraints-for-binary-floating-point-instructions (title and venue from the IBM listing; abstract from a search summary of a copy; the IBM listing's author line reads "Abraham Ziv, Merav Aharoni, et al.").
4. J. R. Hauser, Berkeley TestFloat Release 3e: https://jhauser.us/arithmetic/TestFloat-3/doc/testfloat_gen.html and https://jhauser.us/arithmetic/TestFloat-3/doc/TestFloat-general.html (READ: levels, options, section 4 "What TestFloat Does").
5. B. Verdonk, A. Cuyt, D. Verschaeren, "A precision- and range-independent tool for testing floating-point arithmetic I: basic operations, square root, and remainder", ACM Trans. Math. Softw. 27(1):92-118, 2001, and "... II: conversions", 27(1):119-140. https://medialibrary.uantwerpen.be/oldcontent/container2652/files/papers/Ve_Cu_ea_pre_01.pdf (part I: READ, the text extracted from the PDF the fetcher saved, by the same stdlib-only script as for [15]; part II, conversions: not read, the citation and the scope from search listings).
6. UCBTEST, W. Kahan and colleagues, UC Berkeley: http://www.netlib.org/fp/ucbtest.tgz; its contents from Oracle's Numerical Computation Guide, appendix F: https://docs.oracle.com/cd/E19059-01/stud.10/819-0499/ncg_references.html (from a search result of that guide; the archive was not opened).
7. L. M. Dutton, C. K. Anand, R. Enenkel, S. M. Mueller, "Inexactness and Correction of Floating-Point Reciprocal, Division and Square Root", arXiv:2404.00387, 30 March 2024. https://arxiv.org/abs/2404.00387 (READ: the abstract).
8. A. Edelman, "The Mathematics of the Pentium Division Bug", SIAM Review 39(1):54-67, 1997, doi 10.1137/S0036144595293959. https://epubs.siam.org/doi/10.1137/S0036144595293959 (from a search result quoting the abstract; the page is paywalled and was not opened).
9. V. Pratt, "Anatomy of the Pentium Bug", TAPSOFT '95, Springer, 1995. https://www.springerprofessional.de/en/anatomy-of-the-pentium-bug/13614178 (READ: the abstract).
10. P. W. Markstein, "Computation of elementary functions on the IBM RISC System/6000 processor", IBM J. Res. Dev. 34(1):111-119, 1990 (the citation from DBLP via a search; the theorem as stated in [11]; the paper itself not read).
11. J. Harrison, "Formal verification of IA-64 division algorithms", TPHOLs 2000, LNCS 1869, pp. 234-251, with the slides https://www.cl.cam.ac.uk/~jrh13/slides/tphols-15aug00/slides.pdf (the paper's record from Harrison's publication page as a search returned it; the statement of Markstein's theorem from a search summary of the slides, which were not fetched).
12. V. Lefèvre, J.-M. Muller, "Worst cases for correct rounding of the elementary functions in double precision", Proc. 15th IEEE Symposium on Computer Arithmetic, pp. 111-118, Vail, Colorado, 2001. https://www.vinc17.net/research/papers/arith15.pdf (READ: venue, pages and year in the author's list https://www.vinc17.net/research/publi.html; the abstract's remark from a search summary).
13. D. Stehle, V. Lefevre, P. Zimmermann, "Worst cases and lattice reduction", ARITH-16, pp. 142-147, 2003, and "Searching worst cases of a one-variable function using lattice reduction", IEEE Trans. Computers 54(3):340-346, 2005. https://www.vinc17.net/research/papers/ieeetc2005-wclr.pdf (READ: venues, pages and years in the author's list).
14. A. Sibidanov, P. Zimmermann, S. Glondu, "The CORE-MATH Project", ARITH 2022. https://hal.inria.fr/hal-03721525 (READ: the entry on Zimmermann's papers page, https://members.loria.fr/PZimmermann/papers/; the HAL page refused the fetcher).
15. V. Lefevre, T. Ly, P. Zimmermann, "Computing hard-to-round cases of sin, cos, tan in double precision", ARITH 2026 (an extended version is listed by the third author). https://www.arith2026.org/papers/Computing%20hard-to-round%20cases%20of%20sin_2C%20cos_2C%20tan%20in%20double%20precisio.pdf (READ: the text, extracted from the PDF by a stdlib-only script run in isolated mode).
16. F. de Dinechin, J.-M. Muller, B. Pasca, A. Plesco, "An FPGA architecture for solving the Table Maker's Dilemma", ASAP 2011, pp. 187-194, doi 10.1109/ASAP.2011.6043267. https://hal-ens-lyon.archives-ouvertes.fr/ensl-00640063 (from a search result; its 125-hours-a-binade estimate as [15] recalls it).
17. B. Gladman, V. Innocente, J. Mather, P. Zimmermann (with K. Ozaki in the 2026 version), "Accuracy of Mathematical Functions in Single, Double, Extended Double and Quadruple Precision", HAL hal-03141101, versions 2021 to 2026. https://members.loria.fr/PZimmermann/papers/accuracy.pdf (READ: the listing on Zimmermann's papers page; the method statement, exhaustive at binary32 and a black-box search above, from a search summary of an earlier version, because the HAL pages refused the fetcher).
18. M. D. McKay, R. J. Beckman, W. J. Conover, "A comparison of three methods for selecting values of input variables in the analysis of output from a computer code", Technometrics 21(2):239-245, 1979, doi 10.2307/1268522 (from search results; a reprint at https://www.asc.ohio-state.edu/statistics/comp_exp/jour.club/McKayConoverBeckman.pdf was not opened).
19. I. M. Sobol', "On the distribution of points in a cube and the approximate evaluation of integrals", USSR Comput. Math. Math. Phys. 7(4):86-112, 1967, doi 10.1016/0041-5553(67)90144-9 (from search results, Math-Net.ru).
20. S. Joe, F. Y. Kuo, "Constructing Sobol' sequences with better two-dimensional projections", SIAM J. Sci. Comput. 30(5):2635-2654, 2008, doi 10.1137/070709359 (from search results).
21. D. R. Kuhn, D. R. Wallace, A. M. Gallo, "Software fault interactions and implications for software testing", IEEE Trans. Software Engineering 30(6):418-421, 2004, doi 10.1109/TSE.2004.24 (from a NIST record in search results).
22. D. R. Kuhn, R. N. Kacker, Y. Lei, "Practical Combinatorial Testing", NIST Special Publication 800-142, October 2010, doi 10.6028/NIST.SP.800-142 (from search results; the PDF at nvlpubs.nist.gov was not opened).
23. M. Luby, C. Rackoff, "How to construct pseudorandom permutations from pseudorandom functions", SIAM J. Comput. 17(2):373-386, 1988, doi 10.1137/0217022 (from search results).
24. J. Black, P. Rogaway, "Ciphers with arbitrary finite domains", CT-RSA 2002, Springer LNCS 2271, 2002 (the volume from Springer's listing of the proceedings; the authors' own page gives a different number, 1872, which I take to be an error; pages 114-130 from citing lists, not confirmed); ePrint 2001/012, https://eprint.iacr.org/2001/012 (abstract and bibliographic data from search results; cycle walking as secondary sources describe it).
25. T. E. Hull, A. R. Dobell, "Random number generators", SIAM Review 4(3):230-254, 1962 (READ: the entry and the statement of the three conditions on the Wikipedia article "Linear congruential generator", https://en.wikipedia.org/wiki/Linear_congruential_generator).
26. F. B. Brown, "Random number generation with arbitrary strides", Trans. Am. Nucl. Soc. 71:202-203, 1994. https://www.osti.gov/biblio/89100 (from search results: the OSTI abstract).
27. J. K. Salmon, M. A. Moraes, R. O. Dror, D. E. Shaw, "Parallel random numbers: as easy as 1, 2, 3", SC11, 2011. https://sc11.supercomputing.org/schedule/event_detail.php-evid=pap274.html (from a search summary of the SC11 page).
28. D. P. Anderson, "BOINC: A System for Public-Resource Computing and Storage", 5th IEEE/ACM International Workshop on Grid Computing, 2004 (from search results, a mirror PDF; listings disagree on the pages, none is given here).
29. L. F. G. Sarmenta, "Sabotage-tolerance mechanisms for volunteer computing systems", Future Generation Computer Systems 18(4):561-572, 2002 (the venue and pages from a citing paper's reference list; READ: the spotter-task, blacklisting and voting descriptions on the project page https://groups.csail.mit.edu/cag/bayanihan/papers/fgcs/html/node11.html, which is an early version of the work).
30. P. Golle, I. Mironov, "Uncheatable distributed computations", Topics in Cryptology - CT-RSA 2001, pp. 425-440 (READ: the entry on https://crypto.stanford.edu/~mironov/research.html; its content not read, and "ringers" is not attributed to it here).
31. R. C. Merkle, "A digital signature based on a conventional encryption function", CRYPTO '87, LNCS 293:369-378, 1988, doi 10.1007/3-540-48184-2_32 (from search results).
32. B. Laurie, A. Langley, E. Kasper, "Certificate Transparency", RFC 6962, June 2013. https://www.rfc-editor.org/rfc/rfc6962 (from search results quoting its text on Merkle trees, audit paths and consistency proofs).
33. S. A. Crosby, D. S. Wallach, "Efficient data structures for tamper-evident logging", 18th USENIX Security Symposium, 2009. https://www.usenix.org/conference/usenixsecurity09/technical-sessions/presentation/efficient-data-structures-tamper-evident (from search results).
34. R. Kaivola, R. Ghughal, N. Narasimhan, A. Telfer, J. Whittemore, S. Pandav, A. Slobodova, C. Taylor, V. A. Frolov, E. Reeber, A. Naik, "Replacing testing with formal verification in Intel Core i7 processor execution engine validation", CAV 2009, pp. 414-429 (from search results, the Springer listing).
35. D. M. Russinoff, "A mechanically checked proof of IEEE compliance of the floating point multiplication, division and square root algorithms of the AMD-K7 processor", LMS J. Comput. Math. 1:148-200, 1998, doi 10.1112/S1461157000000176 (from search results).
36. J.-M. Muller (coordinator), N. Brunie, F. de Dinechin, C.-P. Jeannerod, M. Joldes, V. Lefevre, G. Melquiond, N. Revol, S. Torres, "Handbook of Floating-Point Arithmetic", 2nd edition, Birkhauser, 2018, doi 10.1007/978-3-319-76526-6 (from search listings; no chapter read).

Repository documents relied on, all READ: `CLAUDE.md`; `hw/card_stress.py`, `hw/card_stress_lib.py`, `hw/run-soak.sh`, `hw/run-c5-soak.sh`; `host/tools/divsqrt_soak.c`, `host/tools/clause5_soak.c`, `host/tools/mpfr_check.c`; `host/include/cft.h`, `host/include/cft_config.h`, `host/src/clause5.c`; `docs/CARDDAY.md` ("The long run"), `docs/VALIDATION.md`, `docs/SCALING.md`, `docs/PLATFORMS.md`, `docs/ARCHITECTURE.md`, `docs/TRANSCENDENTALS.md`, `docs/studies/M1-exp-log.md`, `docs/studies/M2-trig.md`; `formal/README.md`; `.github/workflows/gates.yml`; `python/cft_golden/softfloat.py`, `formats.py`, `vectors.py`, `sequences.py`, `divfull.py`; `python/tests/test_softfloat.py`, `test_sequences.py`.
