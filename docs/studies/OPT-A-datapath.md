# OPT-A: the arithmetic datapath

A design study of `cft_fpfma_pipe` and the structures around it - the
multiplier, the aligner, the split adder, the normaliser and the round
stage. **Nothing here is built.** Every number is either quoted from
this repository's own measurements or derived from them with the
arithmetic shown; where I guess, the guess is labelled `estimate` and
the derivation is beside it.

Scope: the datapath itself. Where an idea's payoff or its cost lands in
the array, in placement, or in the host contract, I say so and hand it
over rather than pricing it. The three neighbouring studies own those.

Nothing in here may change a result bit. Every proposal below is either
(a) bit-identical by construction, the way `MUL_PASSES` is, or (b)
bit-identical by an equivalence gate of the shape this project already
runs - `tb_mulshare` / `tb_normshare` / `tb_mulcycle` compare two
configurations against each other, `tb_simpleops` compares a rewrite
against a frozen reference, the four unit benches and `krnl` compare
against `python/cft_golden`, and `formal/` proves what a SAT solver can
reach. An idea with no such gate is not on the list.

---

## 1. The yardstick, derived

Everything below is priced against these, all from the repository.

### 1.1 What a lane is

From `rtl/cft_fpfma_pipe.sv`: `P = MAN_W + 1`, `SH = P + 4`,
`VW = 2P + SH + 1 = 3P + 5`, `GW = VW + 1 = 3P + 6`, `AW = GW + 1 =
3P + 7`, `NW = GW`, `ALN_W = GW - 1 = 3P + 5`, and the multiplier is
`ceil(P/24)` chunk columns of `P x 24`.

| rung | P | chunks | `AW` (adder) | `NW` (normalise) | `ALN_W` (align) | round window `P+2` | LUT/lane | DSP/lane |
|---|---|---|---|---|---|---|---|---|
| fp32 | 24 | 1 | 79 | 78 | 77 | 26 | 2,580 | 2 |
| fp64 | 53 | 3 | 166 | 165 | 164 | 55 | 5,100 | 9 |
| fp128 | 113 | 5 | 346 | 345 | 344 | 115 | 11,670 | 35 |
| fp256 | 237 | 10 | 718 | 717 | 716 | 239 | 31,831 | 140 |
| **aggregate over 15 lanes** | | | **2,706** | **2,691** | **2,676** | **897** | **96,211** | **262** |

(LUT/lane and DSP/lane are ROADMAP's `report_utilization -hierarchical`
run of 2026-08-30.)

### 1.2 The DSP model is exact, and it predicts

Dividing DSP/lane by chunk count gives the cost of one `P x 24` column:
**2 / 3 / 7 / 14** DSP at the four rungs. Both measured tile totals fall
out exactly:

```
MUL_PASSES=1   8*1*2 + 4*3*3 + 2*5*7 + 1*10*14 = 16 + 36 + 70 + 140 = 262   (measured 262)
MUL_PASSES=10  8*1*2 + 4*1*3 + 2*1*7 + 1* 1*14 = 16 + 12 + 14 +  14 =  56   (measured  56)
```

So DSP is fully predictable from `(rung, columns built)`, and any
proposal below can be priced on that axis without a synthesis run. LUT
cannot be predicted this way and I do not pretend otherwise.

### 1.3 Where the LUTs are

The ablation of 2026-08-31 (base 117,530 LUT) froze the four variable
shift amounts:

| tree | LUT | vs base | share | per stage-bit |
|---|---|---|---|---|
| alignment frozen | 95,228 | -22,302 | 19.0% | 22,302 / (2,676 x 10) = **0.833** |
| normalise frozen | 101,997 | -15,533 | 13.2% | 15,533 / (2,691 x 10) = **0.577** |
| both frozen | 79,742 | -37,788 | **32.2%** | |

**A third of the kernel is barrel shifter**, and the aligner costs 44%
more per stage-bit than the normaliser (each divided by its own
aggregate width x ten levels). Two things are inside that gap
and the ablation cannot separate them: the aligner is bidirectional
(every stage bit gains a third source), and the aligner carries a
*second* full-width ladder that the normaliser does not - the sticky
thermometer `~(onesv << amt)` in the S7 comb block. Idea 3 lives in that
gap and its prize is bounded by it: somewhere in `[0, 6,769]` LUT.

### 1.4 Where the width comes from, and whether it can be attacked

`AW = 3P + 7` is not slack. The brief asks whether the width itself can
be attacked, so here is the derivation and the answer.

Two operands meet on one grid: the anchor (larger exponent) is placed at
a *constant* offset `SH = P + 4`, and the other is shifted to meet it.

- product anchors: `big = mp << SH` occupies `[P+4, 3P+3]`; the addend
  (P bits) shifted left by at most `SH` occupies at most `[0, 2P+3]`.
- addend anchors: `big = mc << SH` occupies `[P+4, 2P+3]`; the product
  (2P bits) shifted left by at most `SH` occupies at most `[0, 3P+3]`.

Union `3P+4` bits, `+1` for the add's carry gives `ALN_W = 3P+5`, `+1`
for the appended marker gives `GW = 3P+6`, `+1` for the magnitude's
carry out gives `AW = 3P+7`.

Is `SH = P+4` of headroom really needed? Yes, and the binding case is
cancellation. The product is `2^(ep+2P)`-ish and the addend
`2^(ec+P)`-ish, so they are comparable - and therefore can cancel to
nothing - when `dd = |ep-ec| ~ P`. In that configuration the addend's
LSB sits P bits *below* the product's LSB and every one of those bits
can survive the cancellation. The window has to span from the top of the
product to the bottom of the addend: `2P + P = 3P`. **The width is a
theorem, and the only structural escape from it is the two-path
(near/far) FMA, which ROADMAP has already priced at ~1.5x adder and
shifter area and rejected** - and at 32.2% of the kernel in shifters,
1.5x is not survivable.

I checked one weaker escape and it also fails. `n7_smlv`'s top `P+5`
bits are provably zero *before* the shift, so in the right-shift
direction the adder's top `P+5` bits degenerate to an increment - but
the direction is dynamic and the left-shift case fills them, so nothing
is statically removable.

**So the width stays and the leverage is elsewhere: the cost per bit
(ideas 3, 5, 6), the number of levels over that width (ideas 2, 6), and
the number of copies of the structure (idea 1).** That last one is where
almost all of the money is.

---

## 2. The ranked list

Ordered by expected value = size of the prize x my confidence it lands.
Effort is a separate column, because the ordering is not the same one:
**4, 5, 6 and 7 are hours each and together are the best value per day
on the page** (-1,700 to -2,100 LUT and 0.7-1.5 ns), while 1 is the
biggest prize and a multi-week campaign.

| # | idea | moves | expected | confidence | effort | recorded already? |
|---|---|---|---|---|---|---|
| 1 | **Serve the narrow rungs from the fp256 pipe, one rounding** | LUT, DSP | **-38% (keep fp32) / -58% (all)**, DSP 262 -> 30 / 14 | medium-high | weeks | **no** |
| 2 | **One shift, not two**: fold the round window into the normalise ladder | LUT, FF, path | -3,780 LUT (3.1%), -582 FF | high | days | **no** |
| 3 | **The sticky rides the ladder** | LUT | -3,050 LUT (2.5%) `estimate`, bounded `[0, 6,769]` | medium | days | **no** |
| 4 | Derive `csh` from the LZC's chunk index; narrow the S11 exponent arithmetic | path | 0.5-1.0 ns on the #1 path, ~0 LUT | high | hours | **yes** - ROADMAP 2026-09-02, "Recorded, not done" |
| 5 | Trim the aligner's dead ladder levels | LUT | -800 to -1,200 LUT (0.7-1.0%) | high | hours | no |
| 6 | Delete `bitlen_p1`; precompute both exponent candidates | LUT, path | -900 LUT, an add off S13->S14 | high | hours | no |
| 7 | Rebalance the split-carry adder's split point | path | 0.2-0.5 ns on S9->S10, 0 LUT | medium | one localparam | no |
| 8 | Leading-zero anticipator at S9 | path (costs LUT) | -1.0 to -1.5 ns for +4,000-5,400 LUT | medium | weeks | partly - named inside the "deeper pipeline" option |
| 9 | Time-multiplex the two shared ladders into one (multi-cycle only) | LUT | -5,000 to -7,000 LUT, costs fp32 rate | medium | weeks | no |
| 10 | Narrow the exponent sideband | FF | -2,400 FF | high | hours | no |
| 11 | Fold the coarse alignment into the chunk-column weighting | LUT | speculative | low | weeks | no |
| 12 | Emit the exact residual: clause 9.5 as a second output | capability | not an area idea | low | weeks | no |
| 13 | Two adders instead of three | LUT | -1,350 LUT, highest risk in the design | low | weeks | no |
| - | pre-normalise subnormals at S1 | - | **+9,570 LUT** - rejected with arithmetic below | - | - | no |
| - | Karatsuba / Booth on the significand | - | trades the abundant resource for the scarce one - rejected | - | - | partly (entry 6) |

Section 3 is one subsection per idea. Section 4 is the
already-tried/already-rejected column in full.

---

## 3. The ideas

### 3.1 Serve the narrow rungs from the fp256 pipe, with a single rounding

**Status: new. This is the one that matters.**

**The claim the brief starts from.** "Rungs do not nest - an fp128 pipe
cannot serve fp32 without double rounding, so each rung is built beside
the others." That is true of a pipe that *rounds to fp128 and then to
fp32*. It is not true of this pipe, because **this pipe does not round
until S13, and everything before S13 is exact.**

**The mechanism.** `cft_fpfma_pipe` computes, in S2..S12, the exact
value of `a*b + c` as a `3P+6`-bit window plus one residue bit
(`s10_mag[0]` -> `s12_stk`) meaning "and something nonzero below". S13
is the only rounding site in the RTL - `docs/DETERMINISM.md` says so
explicitly, and it is why the contract is auditable. So a P=237
datapath, handed fp32 operands widened into it, holds the *exact* fp32
FMA result at S12, and rounding it once against fp32's descriptor is a
single correct rounding. There is no intermediate to double-round
through.

`docs/DETERMINISM.md` 5.4.1 already carries both halves of the lemma
this needs: narrow source into wide destination "rounds nothing - the
interchange ladder nests in significand bits and in exponent range
both", and the failure mode to avoid is exactly "form an fp256 result
and convert it down", for which
`python/cft_golden/formatof.py::double_rounding_witness()` already
constructs eighteen counterexamples. **Those eighteen are the negative
control this idea ships with**: a build that accidentally rounds twice
fails them, and a build that rounds once passes.

**What changes in the RTL.** Less than it sounds.

- S2..S12 do not change at all. They are format-independent integer
  arithmetic on a wider grid.
- S1 unpack: `EXP_W`/`MAN_W` become runtime - four field positions, a
  4:1 mux on ~19 bits per operand plus the sign bit. `estimate` ~200
  LUT.
- S12/S13: `EMIN`, `EMAX`, `BIAS`, `P_fmt` become runtime constants
  (4:1 muxes on ~8 small quantities, `estimate` ~200 LUT). The window
  extraction is *structurally unchanged*: today `delta = P - K` ranges
  over `0..P-1` and `ywin` is the top `P+1` bits; with a runtime format
  it is `delta = PMAX - K` over `0..PMAX` and `ywin` the top `PMAX+1`
  bits. Bit `i` of `kept` is `s12_norm[NW-K+i]` either way. **The
  existing shifter's range already covers it.**
- S14 pack: one 4:1 mux over the 256-bit output word for the four field
  layouts, `estimate` ~512 LUT.
- `cft_simpleops` at W=256 with a runtime format: `iadd`/`isub` mod
  `2^W` is truncation of a 256-bit add on zero-extended operands;
  `ishr`/`icmplt`/the magnitude compares are correct on zero-extended
  operands as written; `ishl`'s count is `b mod W` (a runtime mask) and
  the sign bit's position is a 4:1 select. `estimate` +500 LUT on the
  one instance, against 22,418 for fifteen.
- `cft_lanes` serialises the beat into the one pipe and reassembles the
  result beat. **The engine and the sequencer need no change at all**:
  both already gate issue, the result-capture delay line and the
  accumulator's schedule on `lane_ready` (`cft_engine_stream.sv` lines
  989/1005/1015, `cft_seq.sv` line 454), because `MUL_PASSES` put that
  seam there in 2026-09-06. Presenting `in_ready` low for 7 of 8 cycles
  at fp32 is exactly the pacing that already exists.
- `cft_mulpass`'s pass counter counts to `ceil(P_fmt/24)` rather than
  `ceil(PMAX/24)`, because `mb` is zero above `P_fmt`. Runtime, one
  compare.

**Is the exactness argument airtight?** Two places in the pipe reason
about `P` rather than merely being sized by it, and both have to be
re-derived on the wide grid. I did both.

*The far case.* `far` fires when `dd - SH >= 2P+2`. On the wide grid
that is `dd >= 717`, which fp64 and fp128 operands can reach and fp32
cannot. `far` means "the small operand is entirely below the round
window, sticky only", and the marker it sets is format-independent, so
it is correct on any grid.

*The bare epsilon* (S11's comment: "Change SH or the far-alignment
threshold and this is the argument to re-derive" - so, re-derived).
An empty window with a surviving residue needs simultaneous
(a) near-total cancellation and (b) a right shift, `dd > SH`.
Cancellation needs the two aligned MSBs to coincide:
`SH + bl_big - 1 = bl_small - 1 - (dd - SH)`, i.e.
`dd = bl_small - bl_big`. With `dd > SH = PMAX + 4 = 241`,
`bl_big >= 1` and `bl_small <= 2*P_fmt`, that needs
`2*P_fmt > 241`, i.e. `P_fmt > 120`. **Only fp256 satisfies it**
(fp128's `2P = 226 < 241`, fp64's 106, fp32's 48). So on the wide grid a
narrow-format empty window is an exact zero and the epsilon case is
exactly the one the shipping fp256 lane already handles. The argument
holds *a fortiori*, which is the direction one wants, but it is a
derivation and wants a directed test at each rung near the far
threshold before anyone believes it.

**What it costs, with the arithmetic.** From `docs/LAYOUTS.md`'s bank
table (hierarchy preserved, eb8ef2a): full tile 131,386; banks
fp32 26,592 / fp64 25,304 / fp128 27,492 / fp256 35,333 = 114,721; what
does not shrink with the rungs ~15,300 (sequencer 8,565, engine 5,352,
CSR 576, steering ~800). Check: 114,721 + 15,300 = 130,021, within 1%
of 131,386.

| variant | banks built | LUT (hier.) | vs 131,386 | DSP @1 pass | DSP @10 passes | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|---|---|---|---|---|
| today | all four | 131,386 | - | 262 | 56 | 1x | 1x | 1x | 1x |
| **A2** | fp32 + fp256 | 61,925 + 15,300 + ~3,150 = **~80,400** | **-38.8%** | 156 | **30** | **1x** | 1/4 | 1/2 | 1x |
| **A3** | fp256 only | 35,333 + 15,300 + ~4,500 = **~55,100** | **-58.0%** | 140 | **14** | 1/8 | 1/4 | 1/2 | 1x |

The `~3,150` / `~4,500` are the serialiser, the runtime-format muxes and
the extra seed ROMs, itemised above; all `estimate`.

Applying those ratios to the flattened, shipping figure of 123,420:
**A2 ~75,500 LUT, A3 ~51,800 LUT.** On a Kintex-7 325T, whose measured
tile at ten passes with the ladders on is 98,929 LUT (48.5%) and whose
ten-pass ladders-off figure is ~116,000 by the Zynq proxy ratio: **A2
~71,000 LUT = 35% of the device, A3 ~49,000 = 24%.** Two A2 tiles fit a
K325T at ~70%. Three A3 tiles fit at ~72%.

**Read the throughput column, because it is the whole price.** fp256 is
*unchanged* - the fp256 bank is the one that survives. fp128 halves.
fp32 is untouched in A2 and drops 8x in A3. So:

- A2 costs the two middle rungs and keeps the position `MUL_PASSES` was
  designed around ("fp32 never slows down", `docs/ATLAS.md`'s workload).
- A3 gives that position up and buys another 25,000 LUT for it.
- **Two A2 tiles fit where one tile fits today, at twice the fp256 and
  fp128 throughput** - which is the axis `README.md` says the project
  exists for ("the tile's reason to exist is the precision commodity
  hardware does not offer"). That framing belongs to the array study;
  I raise it because it is the payoff.

**Doctrine.** This does *not* trim rungs: every tile stays fp256-capable
and every rung stays bit-exact and runtime-selectable, so
`docs/SCALING.md`'s homogeneous-tile decision holds and CAPS still reads
0xF. What it changes is *rate*, which "is nowhere in the contract; bits
are all of it" - the same argument that licensed `MUL_PASSES`. It does
contradict two soft positions: `MUL_PASSES`' "fp32 keeps full rate" (A3
only), and `docs/LAYOUTS.md`'s fp32-heavy layouts, which become
pointless if a tile's fp32 rate is 1/8. Both are product-tier choices,
not contract clauses - but the study should not pretend they are free.

**It also subsumes `FUSE_NORM` / `FUSE_ALIGN`, and that is the cleanest
way to see why it is big.** The fused ladders exist to collapse a 2,706-
bit aggregate into 718 - a 3.77x geometric collapse that delivers only
1.97x, because segmentation costs 1.6x per stage-bit (0.46 -> 0.73). A2
and A3 reach the same 718 by *deletion* at 1.0x per stage-bit, and take
the multiplier, `cft_simpleops`, `cft_opmux` and `cft_seedop` with them.
So the ladders should be **off** in this configuration (with one or two
banks their own collapse ratio is 1.86x or 1.0x, at a 1.6x penalty -
they lose), and the +0.097-vs-+0.307 ns slack objection that keeps them
off on Alveo disappears with them.

**What must be proven, and by which gate.**

1. `tb/test_fpfma_fp32.py`, `_fp64`, `_fp128`, `_fp256` re-pointed at one
   runtime-format P=237 pipe: every result and flag bit against
   `python/cft_golden`. This is the primary gate and it is the same one
   the four banks pass today.
2. The eighteen `double_rounding_witness()` cases as a **negative
   control**: an intentionally-wrong build that rounds to fp256 first
   must fail them. A gate that cannot fail is not a gate
   (`tb_simpleops`' argument).
3. Directed tests at each rung around the far threshold and the
   empty-window case, because 3.1's two re-derivations are the only
   places where the argument is mine rather than the code's.
4. `make krnl` / `krnlseq` / `reduce` / `quarter` unchanged - the engine
   and sequencer interfaces do not move, so a regression there means the
   pacing is wrong, not the arithmetic.
5. Formal: the round stage is a bounded combinational block over a
   `PMAX+2`-bit window, which is the shape a SAT solver does *well* at
   (unlike `formal/mulpass_real.sby`, the same claim at the real 24-bit
   chunk, which does not close and is parked out of `formal/run.sh`). "The
   runtime-format round stage at format f equals the f-parameterised
   round stage" is provable at each of the four f, at reduced `PMAX` by
   the `CFT_MUL_MCH_FORMAL` precedent.

**Risk, honestly.** S13/S14 is the most safety-critical logic in the
project and this touches it. Against that: the change to S13 is
*narrower* than the 2026-09-02 precompute already made, S2..S12 are
untouched, and the negative control already exists in the golden model.

### 3.2 One shift, not two: fold the round window into the normalise ladder

**Status: new.**

**The observation.** The pipe performs two variable shifts in series on
the same value: S11/S12 normalise left by `lsh = NW-1-msb`, then S13
shifts the top `P+1` bits right by `delta = P - K` to build the clamped
round window. Their composition is a single shift, and its amount is
*independent of the leading-zero count*:

```
lsh - delta = (NW-1-msb) - (EMIN - enorm)          [subnormal case, K < P]
            = (NW-1-msb) - EMIN + (g + msb)
            = (NW-1) + g - EMIN                     <- msb cancels
```

Write `R = (NW-1) + g - EMIN`. In the normal case `delta = 0` so the
shift is `lsh`; and `enorm >= EMIN  <=>  lsh <= R`. Therefore

> **the combined shift is `min(lsh, R)`, where `R` is a function of `g`
> alone and is available at S6 - five stages before it is used.**

That is the whole idea: normalise *to the round window* in one pass,
instead of normalising fully and then shifting back down.

**What it deletes.** The S13 right shifter and everything feeding it:

| rung | delta range | levels | width `P+2` | lanes | stage-bits |
|---|---|---|---|---|---|
| fp32 | 0..23 | 5 | 26 | 8 | 1,040 |
| fp64 | 0..52 | 6 | 55 | 4 | 1,320 |
| fp128 | 0..112 | 7 | 115 | 2 | 1,610 |
| fp256 | 0..236 | 8 | 239 | 1 | 1,912 |
| | | | | | **5,882** |

At the normaliser's measured 0.577 LUT/stage-bit: **3,394 LUT**. Plus
`s12_ymask`, a `P+2`-bit thermometer per lane (897 aggregate bits,
`estimate` ~1 LUT/bit = 897 LUT) and its 897 flip-flops.

**What it adds.** A `min()` on the S11 shift amount (10 bits x 15 lanes,
`estimate` 60 LUT, one extra level on the S10->S11 path), the `R`
register (21 bits x 15 = 315 FF), and one fixed-position 2:1 mux for the
tininess extraction (below): 897 bits x 0.5 = `estimate` 450 LUT.

**Net: -3,780 LUT (3.1% of 123,420) and -582 FF**, with `ywin`, `zwin`,
`s12_delta` and `s12_ymask` gone from S13 and the sticky reduced to the
form it already has (`|s12_norm[NW-P-2:0] | s12_stk`).

**The one wrinkle, and its fix.** S13 computes the round twice: once on
the clamped window for the answer, and once on the *as-if-unbounded*
window (`kept_u`/`guard_u`/`sticky_u`) for tininess-after-rounding. With
the folded shift, `s12_norm` is the clamped normalisation, so `kept_u`
is not directly available. But `s13_tiny = carry_u ? tiny1 : tiny0`, and
`tiny0 = (enorm < EMIN)`, `tiny1 = (enorm+1 < EMIN)` differ **only when
`enorm == EMIN-1`, i.e. only when `delta == 1`.** At `delta >= 2` both
are true and `carry_u` cannot matter; at `delta == 0` the clamped and
unbounded windows coincide. So the unbounded window is needed at exactly
one shift distance, where it is a *fixed* extraction one bit down - a
2:1 mux, not a shifter. That is the 450 LUT added above.

**Interaction.** It composes with `FUSE_NORM` unchanged: the shared
ladder's amount simply becomes `min(lsh, R)`. It composes with idea 1
(the runtime-format `R` is `(NW-1) + g - EMIN_fmt`, a 4:1 mux on
`EMIN`). It supersedes nothing - the 2026-09-02 precompute that
introduced the `delta` shifter took a 10-level `NW`-wide shift down to an
8-level `P+2`-wide one for -6,288 LUT; this removes what remains.

**Gate.** The 111,278-vector RTL suite (`make sim`), which is what the
2026-09-02 restructure of the same stage was held to, plus a frozen
reference wrapper in the `tb/wrappers/cft_simpleops_ref.sv` style so the
two forms are compared to each other over every rung and attribute -
including the reserved encodings and the K<=0 branch, which the model
has no opinion about. Negative control: break the `delta == 1` case and
the tininess flag must diverge.

### 3.3 The sticky rides the ladder

**Status: new.**

**The observation.** The aligner computes its sticky as

```systemverilog
n7_marker = |(smlv0 & ~(onesv << amt));
```

a `3P+5`-bit thermometer mask generated from a 10-bit amount, ANDed with
the pre-shift operand and OR-reduced. That is a *second* full-width
structure beside the data shifter, and - this is the part that matters -
**`FUSE_ALIGN` deliberately does not share it.** The module header says
so: "What deliberately does NOT travel: the sticky... it is computed in
the lane and delayed two cycles beside the shift." So with both ladders
on, 2,676 bits of per-lane mask logic survive in all fifteen lanes,
un-collapsed.

**The mechanism.** A right-shifting barrel shifter already knows which
bits it drops. At level *k* the bits leaving are the low `2^k` of the
current value, so

```
sticky |= amount[k] & |value_k[2^k-1 : 0]
```

accumulated across the levels, is the same predicate ("anything below
`amt` was set") with no mask, no wide AND, and no wide OR-tree. In the
shared ladder it becomes a per-slot drop-OR chain and one sticky bit per
lane comes out beside the value, which also removes the reason the
sticky had to stay in-lane.

**Arithmetic.** Removed: the thermometer at `estimate` 1 LUT/bit over
2,676 aggregate bits = 2,676, plus the fused AND/OR-reduce at
`estimate` 0.33 LUT/bit = 883. Total `estimate` **3,559 LUT**.
Added: the drop-ORs, whose total input width per lane is
`sum_k 2^k` bounded by the amount's range - fp32 127 (x8), fp64 127
(x4), fp128 255 (x2), fp256 511 (x1) = 2,545 bit-inputs, at ~0.2 LUT per
input for 6-input OR trees = `estimate` **510 LUT**, plus one flip-flop
per lane for the partial sticky across the S7/S8 boundary.

**Net: `estimate` -3,050 LUT (2.5%)** - and with `FUSE_ALIGN` on it is
proportionally larger, because it is most of what is left.

**The honest caveat.** I cannot tell from the repository whether Vivado
already folds the constant-vector shift into a cheap comparator chain.
The bound is section 1.3's gap: alignment ablates 6,769 LUT above
normalise, and that gap holds *both* the bidirectionality and the mask.
If bidirectionality alone accounts for the gap - 0.577 x 1.44 = 0.831
against the measured 0.833 - then the mask is nearly free and this idea
is worth almost nothing. A third source per stage bit plausibly costs
that much, so this is not a remote possibility. **The measurement that
decides it is a targeted ablation: freeze `amt` in the mask expression
only, leave the data shift live, difference one OOC synthesis.** That is
one build, and it should be run before any RTL is written.

**Gate.** `tb_fpfma_*` at all four rungs with directed sticky cases (the
existing benches already drive the far case, the right-shift case and
the empty-window case); plus a formal proof, which this one is well
shaped for: "incremental drop-OR == `|(v & ~(ones << amt))`" is a pure
combinational identity over a parameterisable width and bit-blasts
easily at 16 or 24 bits, with induction on the level count.

### 3.4 Derive `csh` from the chunk index; narrow the S11 exponent maths

**Status: ALREADY RECORDED.** ROADMAP 2026-09-02: "the coarse granule
count is `(NW-1-msb) >> 6` - a subtraction the shift select waits on -
and the chunk index that produced msb already knows the granule to
within one; deriving csh from the chunk index and a compare would take
the CARRY8s off that head the same way. **Recorded, not done.**"

I list it anyway because by expected value per hour it is the best thing
on the page, and because I can add the closed form, which the entry does
not carry.

`n11_msb = chunk*64 + (63 - cl)` and `lsh = NW-1-msb`, so with
`NW-1 = 716` at fp256:

```
lsh = 716 - 64*chunk - 63 + cl = 64*(10 - chunk) + (13 + cl)
```

`cl` is in `0..63`, so `13 + cl` is in `13..76` and

```
csh = (10 - chunk) + ((13 + cl) >= 64)          4-bit subtract + 1 compare
fsh = (13 + cl) & 63                            7-bit add, truncated
```

The constant `13` is `((NW-1-63) mod 64)` and the `10` is
`((NW-1-63) div 64)`, both localparams per rung. **This replaces a
32-bit `int` subtraction with a 7-bit add and a 4-bit subtract on the
head of the design's number-one critical path.** The K325T's worst path
is `s10_mag_reg -> normseg/cs_r_reg`, 20 levels of which **seven are
CARRY4** - and 7 CARRY4 is 28 bits of ripple, which is exactly the
32-bit `lsh_full = NW - 1 - n11_msb` plus `chunk*64 + (63-cl)`. Removing
~22 bits of that is `estimate` **5-6 CARRY4 levels, 0.5-1.0 ns** on a
9.698 ns path - i.e. 103 MHz toward 115-125 MHz on the part the third
tier is aimed at - for approximately zero LUTs.

**Gate.** The full suite; the transformation is an integer identity and
a formal equivalence over `chunk`/`cl` is trivial. Effort: hours.

### 3.5 Trim the aligner's dead ladder levels

**Status: new.**

The shared ladder is `NST = 10` levels unconditionally, and `csh` is
declared `[3:0]` in both `cft_fpfma_pipe`'s port and `cft_normseg`'s
pitch. But the aligner's amounts are bounded by construction:

- right: `-lshift < 2P + 2 = 476`, so `csh <= 7` and **amount bit 9 is
  never set**;
- left: `lshift <= SH = 241`, so **amount bits 8 and 9 are never set**.

So in the `BIDIR` align instance, level 9 is entirely dead and level 8 is
right-only. Removing them: `estimate` 720 bits x 1.5 levels x 0.73
LUT/stage-bit = **~790 LUT** in the shared aligner. In the private
aligners the coarse shift is `n7_smlv >> (s6_csh * 64)` where `s6_csh` is
an `int`, so the width Vivado builds for depends on its range analysis;
declaring `s6_csh` as `logic [2:0]` makes it unambiguous and is worth
`estimate` 2,676 bits x 1 level x 0.46 = **~1,230 LUT**.

Call it **-800 to -1,200 LUT (0.7-1.0%)** depending on configuration.
The normaliser gets nothing from this - its `lsh` reaches 716 and needs
all ten levels.

**Gate.** `tb_normshare` already sweeps every legal shift at every rung
(2,977 comparisons); it must be extended to assert the *illegal* ones
never occur, which is an assertion in the pipe rather than a bench
change. Effort: hours. Risk: the bound is a derivation, so the assertion
is the safety net and must be a hard `$error`, not a warning.

### 3.6 Delete `bitlen_p1`, and precompute both exponent candidates

**Status: new.**

S14 runs a `P+1`-bit priority encoder per lane (`bitlen_p1`) to get `bl`,
then `e_res = q + bl - 1`. Aggregate width `8*25 + 4*54 + 2*114 + 238 =
882` bits, `estimate` ~1.2 LUT/bit = ~1,060 LUT, on the last stage's
path.

It is not needed. In the `K == P` branch, `kept[P-1] = s12_norm[NW-1]`,
which is 1 by definition of normalisation (the `s12_zero` case is split
out above), so `bl` is `P` or `P+1` and is named by `kr[P]`. In the
`K < P` branch `q = EMIN - (P-1)` exactly, so `bl < P` implies
`e_res < EMIN` and the subnormal packing - which reads `kr[MAN_W-1:0]`
directly and never uses `bl`. So:

```
bl == P+1  <=>  kr[P]
bl == P    <=>  !kr[P] && kr[P-1]
otherwise  ->   the subnormal pack, e_res unused
```

Two bit tests and a 2:1 mux between `q + P - 1` and `q + P`, both of
which can be **computed at S12 where `q` already is**, removing an
addition from S13->S14 as well. `estimate` **-900 LUT (0.7%)**.

**Gate.** The suite, plus the frozen-reference comparison; the
transformation rests on the invariant `K == P => kept[P-1]`, which is
*not* true for arbitrary S13 inputs, so a whole-domain formal
equivalence of S13/S14 would correctly fail. The honest gate is
therefore bench equivalence over the reachable stream plus a stated
(and asserted) invariant - say so rather than claiming a proof the
shape does not admit.

### 3.7 Rebalance the split-carry adder's split point

**Status: new. One localparam.**

```systemverilog
localparam int CHW = AW / 2;
localparam int HHW = AW - CHW;
```

S9 does three `CHW`-bit adds; S10 does three `HHW`-bit adds **plus** the
3:1 magnitude select and the sign logic. The two halves are given equal
width and unequal work. ROADMAP prices "the 359-bit split-add halves" at
2.5-3.4 ns, i.e. within the 4-5 ns per-stage floor - close enough to
matter. Moving the split down (`CHW ~ 0.55 * AW`) trades carry length
from the loaded half to the empty one at **zero area cost**.

This is the same mistake-shape `cft_normseg`'s `SPLIT` parameter already
documents from the other side ("Balancing the LEVEL COUNTS is therefore
the wrong instinct... the balance point sits well below five"), and the
answer there was to make it a parameter and sweep it. Do the same:
`ADD_SPLIT_NUM/DEN`, default 1/2 so nothing moves, and one sweep of
three values.

`estimate` **0.2-0.5 ns on S9->S10, 0 LUT.** Not today's worst path, but
it is the second family and it is free.

**Gate.** Bit-identity is structural - the split is an implementation of
the same add - and the suite confirms it. Effort: one parameter, one
sweep.

### 3.8 Leading-zero anticipator at S9

**Status: partly recorded** (named as one clause of the "~2x deeper,
rebalanced pipeline" option, which is priced at days of work and gated
on card day).

The S10->S11 path is: `s10_mag` register -> chunk-nonzero scan ->
priority -> `lzc64` -> `lsh` -> slot mux -> ladder level 1 -> register.
An LZA computes the leading-zero position from the *operands* in
parallel with the subtract, so S11 starts from a registered amount and
the path becomes slot mux + ladder only.

Cost: an `AW`-bit prediction string (`T`/`G`/`Z` plus the shift-by-one
combine), `estimate` 1.5-2 LUT/bit over 2,706 aggregate bits =
**+4,000 to +5,400 LUT (3.3-4.4%)**, plus the standard 1-bit correction
shift, which folds into ladder level 0 (already present). It does not
remove the existing LZC - `enorm` still needs `msb` - so this is area
spent purely on the clock.

**Only worth it where the clock is the product.** On the U50 the quad
closes at +0.018 and area is the binding constraint, so this is a bad
trade. On a Kintex-7 325T at -0.066 ns against a 100 MHz ask, +4% area
for `estimate` 1.0-1.5 ns is +25-35% clock, and it is a good one. **Do
idea 4 first**: if the CARRY4s come off the head for free, the LZA's
remaining prize may not justify 4% of the device.

**Gate.** Bench equivalence of `LZA + correction` against `LZC(result)`
over the whole stream, and a formal proof at reduced width - this one
closes, because it is an adder and a priority encoder rather than a
multiplier.

### 3.9 Time-multiplex the two shared ladders into one

**Status: new.**

With `MUL_PASSES > 1` the array is held for `NP - 1` of every `NP`
cycles: at ten passes, nine wall cycles in ten, every stage register in
every lane is frozen and only `cft_mulpass` runs. The two shared
720-bit ladders - align at S7->S8 and normalise at S11->S12 - each need
two of those cycles. **One physical bidirectional ladder can serve
both**, used twice per enabled interval on different wall cycles, each
use latched into its own destination register. The operations they serve
are different (levels 7 and 11 of the pipe), but that does not matter:
the ladder is combinational plus registers, and the phase counter
already exists.

Saving: one 720-bit `BIDIR` ladder. Measured, a left-only shared ladder
is 5,269 LUT standalone; `BIDIR` adds a third source per stage bit,
`estimate` 1.3-1.5x, so `estimate` **-5,000 to -7,000 LUT** net of the
input multiplexing (a 2:1 over 720 bits plus the amount select,
`estimate` +600 LUT).

**The catch is fp32.** At `MUL_PASSES=10` fp32 is `NP=1` - no idle cycle
- so the time-multiplex would force fp32 to a two-cycle beat. That
contradicts the design position the parameter was built around. And the
saving is largely subsumed by idea 1, which removes the reason to have
two ladders rather than sharing one. Listed because it is a real and
unrecorded degree of freedom in the multi-cycle configuration, ranked
low because idea 1 dominates it.

### 3.10 Narrow the exponent sideband

**Status: new. Tidy-up.**

`pb_ep[2:6]` and `pb_ec[2:6]` carry two 32-bit `int`s through five
stages in every lane: `2 * 32 * 5 * 15 = 4,800 FF`. Only three
quantities are read at S6: `bp = (ep >= ec)`, `dd = |ep - ec|` and
`g = max(ep,ec) - SH`. All three are computable at S1, and `dd` only
needs to be exact up to `2P+2 = 476` (beyond that it is `far`), so the
sideband can carry `{bp, dd_sat[9:0], g[20:0]}` = 32 bits:
`32 * 5 * 15 = 2,400 FF`. **-2,400 FF**, LUT roughly neutral (the
compare and two subtracts move from S6 to S1, neither on a reported
path). 21 bits holds `g` because fp256's exponents reach
`+-(262143 + 236 + 241)`.

Flip-flops are not the binding resource anywhere (57,638 of 1.7M on the
U50; 43,365 of 407,600 = 10.6% on the K325T), which is why this is
ranked where it is. It is on the list because it is free and because it
makes S6 shorter.

### 3.11 Fold the coarse alignment into the chunk-column weighting

**Status: new. Speculative.**

The alignment distance is a function of the exponent fields and is
therefore known at **S1** - five stages before the aligner prep at S6
consumes it, and six before the shift itself. And
the multiplier already assembles the product from 24-bit chunk columns
at compounding shifts; the multi-cycle accumulator additionally shifts
its result out in `K = COLS*24`-bit steps. So a *chunk-granular* share
of the alignment (a multiple of 24) could in principle be applied by
changing where each pass's sum lands, leaving the aligner only a `0..23`
fine shift - **5 ladder levels instead of 10** in the case where the
product is the shifted operand.

Why it is speculative rather than ranked: it only covers the
"addend anchors" case (in the other case the *addend* is shifted and the
multiplier is not involved), the accumulator's shift-out structure is
built on a fixed `K`-step invariant that a variable offset would break,
and the coarse mux would move to the tree's `2P+48`-bit width where it
may cost as much as the ladder levels it saves. It is here because "is
the chunk-column decomposition the right one at all" deserves a real
answer, and this is the only version of "yes, and it could do more" I
could construct that does not lose bits.

### 3.12 Emit the exact residual: clause 9.5 as a second output

**Status: new. A capability idea, not an area idea; hand-off to the
contract study.**

The pipe holds the *exact* `a*b+c` at S12 and throws away everything
below the round window. Clause 9.5's `augmentedAddition` and
`augmentedMultiplication` want exactly that discarded part - the
rounding error - as a second result, and libcft composes them in
software today (140,088 augmented pairs checked). A second pack of the
residual would make them tile opcodes with **no new arithmetic**.

The cost is not zero: the residual needs its own normalisation to be
packed as a float, which is a second ladder, and that is the expensive
structure. A cheaper shape - emit the residual as an unnormalised window
plus its exponent and let the host pack it - is nearly free but is an
ABI question. Both belong to the contract/system study; recorded here
because it is a property of *this* datapath that the exact value already
exists and is currently discarded.

### 3.13 Two adders instead of three (not recommended)

S9/S10 race three `AW`-bit results: `sum`, `big-sml`, `sml-big`. The
last two are complements of each other, so one could be dropped by going
two's-complement and complementing after normalisation - using the
identity `(~t + 1) << s = (~t << s) + 2^s`, where the added `1` at
position `s` propagates only through the leading ones.

Aggregate adder width `3 * 2,706 = 8,118` bits (`AW` per lane) at
`estimate` 0.5 LUT/bit = ~4,059 LUT; removing a third is `estimate`
**-1,350 LUT (1.1%)**, less the correction logic. **1.1% is not worth
restructuring the sign-magnitude selection that every rounding and every
flag depends on**, and
the end-around correction is precisely the kind of subtlety that
produces a wrong answer with clean flags. Listed so the option space is
complete and so nobody has to re-derive it.

### 3.14 Rejected with arithmetic

**Pre-normalise subnormal significands at S1.** Tempting, because
unnormalised significands are what make the datapath's dynamic range
uniform and prevent any bound on the normalise distance. Cost: three
LZC-plus-shift blocks per lane at the *significand* width, `estimate`
`3 * (8*24 + 4*53 + 2*113 + 237) = 3 * 867 = 2,601` bits x 8 levels x
0.46 = **+9,570 LUT**. Buys nothing on the window width (section 1.4:
`3P` is a theorem about cancellation, not about normalisation), and
invalidates S11's bare-epsilon argument. **Rejected.**

**Karatsuba on the 237x237 product.** Three ~119-bit multiplies instead
of four quarters: `estimate` -25% DSP, +LUT for the three add/subtract
recombinations. After `MUL_PASSES` the tile is at 56 DSP and the DSP
axis is gone; this spends the scarce resource to save the abundant one,
which is `cft_mulfrac`'s exact failure (NOVEL.md entry 6). **Rejected.**

**Booth recoding.** Same argument; the columns are DSP-mapped and Booth
is a LUT-domain optimisation. **Rejected** (and measured, entry 6).

---

## 4. Already recorded, already tried, or already rejected

The brief asks for this column explicitly. These are the things a fresh
reader would propose, with what happened and whether the reason still
holds.

| proposal | what happened | does the reason still hold? |
|---|---|---|
| **Share the multiplier across banks (`FUSE_MUL` / `cft_mulfrac`)** | Built, proven bit-identical by `tb_mulshare`, measured **262 -> 259 DSP and +693 LUT**. Ten slots of 237x27 cost what four banks of right-sized multipliers cost, because a wide cascade is less DSP-efficient per bit-product (246 vs 372). | **Yes, and more so.** `MUL_PASSES=10` took DSP to 56; there is now nothing left to collapse. Off, and should stay off. |
| **Share the normalise and align ladders (`FUSE_NORM` / `FUSE_ALIGN`)** | Built, equivalence-proven, **-15,805 LUT** (139,404 -> 123,599), but +0.097 ns OOC slack against ladders-off's +0.307, and a shell build settled it. | **Yes on Alveo**, where a thin OOC margin does not survive the shell. **No on 7-series**, where they are the lever (-14.8%) and are already on. And **idea 1 subsumes them**: deletion reaches 718 bits at 1.0x per stage-bit where segmentation reaches it at 1.6x. |
| **Rewrite `cft_simpleops`** | Done, **-11,557 LUT**, 453,424-comparison equivalence, two negative controls. Wide muxes price by *source* count, not opcode count. | Done. The lesson (group opcodes by the shape of the answer) is what makes idea 1's runtime-format `simpleops` cheap. |
| **The granule grid** (tile 237x237 into 24x24 granules with gated cross-terms) | Named in ARCHITECTURE and ROADMAP, **unbuilt**. ROADMAP 2026-09-06: its "remaining prize is throughput per DSP at the narrow rungs, not tile area". | **Its prize is gone.** DSP is 56. And under idea 1 it still does not help, because the bottleneck of a one-bank tile is the align/normalise/round tail, not the multiplier - a granule grid could produce eight fp32 products a cycle into a tail that can round one. |
| **Near/far two-path FMA** | Rejected: cuts latency, costs ~1.5x adder and shifter area, leaves the per-stage floor alone. | **Yes.** At 32.2% of the kernel in shifters, 1.5x is fatal. Section 1.4 confirms the width it would attack is a theorem, so the *only* thing near/far buys here is latency, which is not in the contract. |
| **Carry-save / redundant forms** | Rejected: they beat a slow carry-propagate adder and this fabric's carry chains are fast. | **Yes.** Confirmed from the other side by the K325T path being 7 CARRY4 of 20 levels - carry is not where the time goes. |
| **A ~2x deeper, rebalanced pipeline (LATENCY 24-28)** | Recorded, worth 1.3-1.5x, "days of work on the one file the contract rests on", gated on card day. One attempt to add a single stage failed correctly: the pipe is a *synchronised multi-path* structure and delaying the product alone pairs it with the wrong control word. | **Yes**, and ideas 2/4/5/6/7 are the subset of it that can be taken without re-balancing every path at once. |
| **DSP MREG/PREG, retiming** | Measured: `-retiming` is +1.374 ns OOC for 141 LUT, but the quad got *worse* (-0.113 -> -0.141) because at 98% CLB occupancy the loss is wire. The DSP on the critical path turned out to be the seed ROM's index multiply, now a case table. | Recorded; belongs to the timing/physical study, not this one. |
| **Derive `csh` from the chunk index** | Recorded 2026-09-02, "Recorded, not done". | Still open, and it is idea 4 - with the closed form supplied. |
| **`MUL_PASSES`** | Done 2026-09-06. DSP -79%, LUT -6.4%. The reading: the tile's LUTs are the aligner and the normaliser; its multiplier is DSPs. | Done. Idea 1 is the same argument applied one level up: if the tile's LUTs are the aligner and the normaliser, and their aggregate is 3.77x their widest instance, then *building only the widest instance* is the biggest LUT lever available. |
| **Heterogeneous tiles at their own clocks** | Recorded; no core RTL, all host and link work. | Not a datapath idea; hand-off. |

---

## 5. The two (and a half) that are genuinely new

Flagged for the integrator, since three studies will overlap on the rest.

1. **Idea 1 - the narrow rungs served from the fp256 pipe with a single
   rounding.** The repository's standing position is that the rungs do
   not nest. They do not nest *if you round at the wide format*; they
   nest perfectly if you do not, because S13 is the only rounding site
   and everything upstream of it is exact. That turns a 3.77x geometric
   ratio the fused ladders can only realise at 1.97x into an outright
   deletion, and takes 262 DSPs to 30 or 14 with it. The price is
   narrow-rung *rate*, which the contract does not mention. `estimate`
   -38% to -58% of the tile.
2. **Idea 2 - one shift, not two.** `lsh - delta = (NW-1) + g - EMIN`,
   independent of the leading-zero count, so the normalise shift and the
   round-window shift are one shift whose amount is `min(lsh, R)` with
   `R` available five stages early. Deletes the S13 shifter, `ywin`,
   `zwin`, `delta` and `ymask`. `estimate` -3.1% and -582 FF.
2b. **Idea 3 - the sticky rides the ladder.** The aligner carries a
   second full-width ladder for a thermometer mask, and it is precisely
   the piece `FUSE_ALIGN` was written *not* to share. A right shifter
   already knows the bits it drops. `estimate` -2.5%, honestly bounded
   in `[0, 6,769]` LUT and settled by one ablation.

---

## 6. What I would build first, in one week

**Build the runtime-format round stage and prove idea 1 at the bench,
before writing a line of the serial array.**

The whole of idea 1 rests on one claim - *the value at S12 is exact and
format-independent, so a single rounding at the destination format is
correct* - and that claim can be tested in a week with no array work, no
engine work and one Vivado run.

**Days 1-3, RTL.** Add `FMT_RUNTIME` to `cft_fpfma_pipe`: `EXP_W`/`MAN_W`
become a 2-bit `fmt` input consumed at S1 (field extraction), S12
(`EMIN`, `P_fmt`, `K`, `q`, tininess) and S14 (pack, `EMAX`, overflow
disposal). Nothing between S2 and S12 is touched. Default `FMT_RUNTIME=0`
keeps every existing instantiation bit-identical, which is the seam
`EXT_MUL`, `EXT_NORM`, `EXT_ALIGN` and `MUL_PASSES` all used.

**Days 3-5, the gate.** Point `tb/test_fpfma_fp32.py`, `_fp64` and
`_fp128` at a single `P=237, FMT_RUNTIME=1` pipe with `fmt` set per test,
and run them unchanged - they already check every result and every flag
bit against `python/cft_golden`. Add directed cases at each rung around
the far threshold (`dd` near 717) and the empty-window case, because
those are the two places where section 3.1's correctness argument is a
derivation of mine rather than the code's.

**Day 5, the negative control.** A second build that deliberately rounds
to fp256 at S13 and then to the destination, run against the eighteen
`double_rounding_witness()` cases already in
`python/cft_golden/formatof.py`. It must **fail**. A gate that cannot
fail is not a gate.

**Days 6-7, the price.** One OOC synthesis of `cft_lanes` at 135 MHz on
`xcu50-fsvh2104-2-e` in the A2 shape - eight fp32 lanes plus one
runtime-format fp256 lane, ladders off - differenced against the same
script on the tip. One build, not a sweep.

**What decides whether it worked**, in order:

1. **All four rung benches green on one pipe**, and the eighteen
   witnesses red on the wrong build. If this fails, the idea is dead and
   the failure names the reason.
2. **The A2 LUT count.** The estimate is ~80,400 hierarchy-preserved
   against 131,386. If it lands above ~100,000 the runtime-format
   muxing is costing more than the banks it replaced, and A2 is not
   worth the risk to S13. (`cft_simpleops` is the precedent in both
   directions: an unflattened estimate is an upper bound, and only a
   before/after under shipping settings says what a change is worth.)
3. **The S10->S11 path must not move.** The runtime format enters S1,
   S12 and S14; if it appears on S10->S11 in the timing report,
   something was wired to the wrong stage.

If all three land, the array and engine work (serialising the beat,
which the `lane_ready` seam already supports) is a separate week and
belongs to the array study. If (1) fails, ideas 2, 4, 5, 6 and 7 are
still there and together are `estimate` -5,680 LUT (-4.6%) and -0.7 to
-1.5 ns for about a week of work between them.

---

## 7. What I could not evaluate

Stated plainly, because the numbers above are only as good as this list.

- **I ran no synthesis and no simulation.** The host is busy and four
  agents starting Vivado would be antisocial. **Every figure marked
  `estimate` is derived from this repository's measured tables, not
  measured.** The ones not marked `estimate` are quoted.
- **Per-bit costs are borrowed across contexts.** 0.46 LUT/stage-bit
  (private) and 0.73 (shared) come from `hw/synth_shiftcmp.tcl` at
  `-flatten_hierarchy none`; 0.833 and 0.577 come from a whole-kernel
  ablation. The project's own warning applies: `cft_simpleops` measured
  22,418 unflattened and delivered 11,557 flattened. **Treat every LUT
  estimate here as an upper bound on the prize, by roughly 2x in the
  worst case.**
- **I cannot separate the aligner's bidirectionality from its sticky
  mask.** Idea 3's prize is bounded by the 6,769-LUT gap between the two
  ablations and could be near zero. The deciding ablation is named in
  3.3 and has not been run.
- **Nothing here is a routing or congestion estimate.** These are logic
  counts. The project's own record - OOC +0.307 becoming shell -0.577, a
  0.88 ns swing - says logic and slack are different currencies, and
  that the quad sits at 98% CLB occupancy where the loss is wire.
- **There is no post-route number on 7-series fabric at any pass
  count**, so every 7-series claim (idea 4's clock, idea 1's device
  fractions, idea 8's conditional) rides on synthesis estimates whose
  slack is already -0.066 ns.
- **I did not read `cft_seq`'s issue logic in full.** I verified it takes
  `lane_ready` (line 454) and that `cft_krnl` wires both drivers to
  `arr_rdy`, which is what makes idea 1's pacing cheap. Whether a
  program's two-ahead issue and deposit bookkeeping survive an
  eight-cycle fp32 beat is a sequencer question I did not settle.
- **I did not price the host-side consequences of idea 1** - a tile whose
  fp32 rate is 1/8 changes what `docs/LAYOUTS.md`'s fp32-heavy layouts
  are for, and whether CAPS should advertise a rate at all. That is the
  contract/system study's ground.
- **Whether Vivado already folds the constant-vector shift in the sticky
  mask, and whether it already prunes the aligner's dead ladder levels**
  (ideas 3 and 5). Both are "does the tool already do this" questions and
  both are one synthesis run each.
- **The formal gate's reach on ideas 1 and 8.** I claim the round stage
  and the LZA are SAT-friendly where `formal/mulpass_real.sby` is not,
  on the grounds that neither contains a multiplier. That is a
  prediction, not a result.
