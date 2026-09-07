# Design study B: the array, the beat, and how many tiles a part can hold

*A design study, 2026-09-06. Nothing here is built, and nothing here
should be built on this document's word. The job is to widen the option
space and price each option honestly enough that someone can choose.*

Scope: the **array and its parallelism** - lane structure, beat width,
how banks and rungs compose, what a tile costs *around* its arithmetic
(interconnect, CSR, FIFOs, AXI), how many tiles fit a part, and how
tiles combine. Three sibling studies own the arithmetic datapath, the
timing and physical implementation, and the contract/system level; where
an idea below belongs to one of them it says so and stops.

Every number is labelled **measured** (this repo's own runs, with the
source named), **derived** (arithmetic on measured numbers, shown), or
**estimate** (a guess with its arithmetic shown and an error bar).

---

## 0. The one picture: where the array's cycles and the tile's LUTs go

Two decompositions decide everything in this study.

**Where the LUTs are.** From `hw/synth_attrib.tcl` with hierarchy
preserved (eb8ef2a, 2026-09-02, docs/LAYOUTS.md):

| part of a tile | LUT | share |
|---|---|---|
| fp32 / fp64 / fp128 / fp256 banks | 26,592 + 25,304 + 27,492 + 35,333 = **114,721** | 87.3% |
| lane steering | ~800 | 0.6% |
| sequencer | 8,565 | 6.5% |
| engine (FIFOs + reduction accumulator inside) | 5,352 | 4.1% |
| CSR | 576 | 0.4% |
| unattributed | 1,372 | 1.0% |
| **whole tile** | **131,386** | |

So **87.9% of a tile is the array** and 12.1% is everything else. There
is almost nothing left inside the kernel boundary to attack that is not
arithmetic - which is why this study's leverage is mostly *outside* the
tile, and inside the array's *schedule*.

Outside the tile, from differencing routed builds (docs/SCALING.md,
`hw/gen_layouts.py`):

* shell + 1 CU = **123,897 LUT** (measured)
* quad fixed cost = **161,775 LUT** (measured, differenced from the
  failed private-array quad link)
* each further CU = (161,775 - 123,897) / 3 = **12,626 LUT** (derived)
* each further AXI master = 37,878 / 12 = **3,157 LUT** (derived: three
  extra CUs are twelve extra masters)

On the modelled quad, the not-arithmetic total is
`161,775 + 4 x (131,386 - 115,521) = 225,235` of `687,319` LUT -
**32.8% of a quad is not arithmetic** (derived). That is the budget this
study is actually competing for.

**Where the array's cycles go.** The array accepts one beat per cycle by
construction. The three things that drive it reach:

| driver | beats/cycle into the array | source |
|---|---|---|
| elementwise stream | **0.80** (1.250 cycles/beat) | measured, `make cycles`, docs/SCALING.md |
| sequencer program | **0.50** (issue `LATENCY`, drain `LATENCY`) | docs/SEQUENCER.md, "Execution model" |
| fp32 reduction | **0.087** (11.462 cycles/beat, and only lane 0 of 8) | measured, `make cycles`; `cft_engine_stream.sv` L933/L982 |

The reduction number is the striking one, and the RTL says so in its own
comment: *"Lanes 1..7 are computing nothing meaningful while a reduction
runs"*, and *"In reduction mode the elementwise path is idle: the only
work the banks do is the accumulator's adds, issued through lane 0."*
At fp32 that is one lane of eight, at a duty of 1/1.43 - **8.7% of the
array's capability, on the operation the atlas det library issues most.**

Every idea below is either about the 32.8% of a quad that is not
arithmetic, or about the gap between 0.80/0.50/0.087 and 1.00.

---

## 1. Ranked ideas, best first by expected value

Ranking is `(resource moved) x (confidence) / (cost to prove)`.

| # | idea | moves | prize | cost to prove | already recorded? |
|---|---|---|---|---|---|
| 1 | Re-measure `FUSE_NORM`/`FUSE_ALIGN` on the current tree, retimed | LUT | 15,805/tile; possibly the **fifth U50 tile at zero throughput cost** | 2 builds | verdict recorded, **on a stale tree** |
| 2 | Beat-local reduction tree (use the 7 idle lanes) | cycles | **~3.3x on fp32 `sum`**, ~2.7x fp64 | 1 bench + 1 OOC run | no |
| 3 | Pass period keyed on op, not just precision | cycles | full rate for every non-multiply opcode at any `MUL_PASSES` | 1 bench | no |
| 4 | Decompose the 12,626 LUT/CU before trying to beat it | LUT | 0-8,000/CU, and settles "law or artefact" | **0 builds** (read an existing report) | claimed, never decomposed |
| 5 | Concurrent engine + sequencer (two issue ports, one array) | cycles | fills the sequencer's **50%** array idle | arbiter + bench + CSR/host work | no |
| 6 | `MUL_PASSES` + ladders as the doctrine-legal fifth tile | LUT | 5 tiles keeping fp256 on every tile | 1 build | levers recorded separately, never composed on U50 |
| 7 | Multi-beat wide elements (decouple `BEAT_BITS` from format width) | LUT, GB/s | an fp256-capable tile on a **K7-160T** (~74k LUT est.) | RTL + bench | guard exists, refuses it |
| 8 | `STREAMS` parameter: fewer masters for wide-rung/sequencer tiles | LUT, HBM PC | 9,471 LUT + 3 PC per tile | 1 build | no |
| 9 | 512-bit beat (two fp256 lanes) | LUT/throughput, HBM PC | ~7.2% LUT and half the PCs per unit compute | RTL + bench + converter risk | guard exists, refuses it |
| 10 | Ring node vs a second AXI master | analysis | ring node ~= **half an AXI master** | analysis only | doctrine asserts the ring, never prices a node |

### 1. Re-measure the fused ladders on the current tree, retimed

**Mechanism.** `FUSE_NORM` and `FUSE_ALIGN` replace the thirty per-lane
alignment and normalise shifters with two segmented 720-bit ladders.
They are already built, already equivalence-proven per lane and through
the whole kernel (`make krnlfused` / `make krnlplain`), and already
worth a measured **15,805 LUT** (139,404 -> 123,599 OOC).

They are off because of one measurement: a single tile linked at
135 MHz with them on **missed at -0.577 ns, 776 failing endpoints**
(2026-09-01).

**Why that verdict is stale, with the arithmetic.** From
docs/ARCHITECTURE.md's own ladder:

| tree | LUT | OOC WNS @135 |
|---|---|---|
| shared array + sequencer diet | 139,404 | +0.307 |
| + fused ladders on | 123,599 | +0.097 |
| + seed ROM as case tables (eb8ef2a), **retimed** | 129,708 | +2.126 |
| + round stage precomputed (9f73107), **retimed** | 123,420 | **+2.222** |

The ladders-on row was measured **against the 139,404 tree, without
retiming, and while the seed ROM's DSP index-multiply was still on every
routed critical path** - a path since removed, and whose removal is
worth 1.8 ns of OOC slack on its own. Three things have changed since
that verdict: retiming, the case-table ROM, and the S12 round-stage
precompute. Nobody has run `FUSE_NORM=1 FUSE_ALIGN=1` on the resulting
tree.

**What it costs and saves.** Saves 15,805 LUT/tile (measured). Costs the
ladder's own path, `s10_mag_reg -> normseg/cs_r_reg[592]`, 25 levels
(measured). Honest caveat in the other direction: that path is an
*absolute* delay, not a delta - it was 7.310 ns unretimed, and if it is
unchanged the ladders-on tree still lands near +0.097 at 135 MHz. But
the current tree's own worst path starts at the same register
(`s10_mag`), so the two are competing on the same ground and retiming
has never been applied to the ladder version.

**Which resource it moves.** LUTs, the binding one. On the U50, five
tiles under docs/SCALING.md's own flattened arithmetic:

```
5 x 107,615 + 174,401 = 712,476 LUT = 81.8% of 870,720   (fits)
```
against SCALING's ladders-off `5 x 123,420 + 174,401 = 791,501 = 90.9%`
(does not). `107,615 = 123,420 - 15,805` (derived; assumes the ladders'
absolute saving is unchanged by the seed-ROM and round-stage work, which
touched neither shifter).

Under docs/LAYOUTS.md's conservative hierarchy-preserved accounting the
same five tiles are `5 x 115,581 + 174,401 = 752,306 = 86.4%` - **over
the 85% line.** The two accountings disagree about the fifth tile by
exactly the 6.5% flatten-vs-hierarchy gap docs/PLATFORMS.md names. That
disagreement cannot be resolved by more arithmetic; it is a build.

**What would have to be proven, and by which gate.** Nothing new
numerically - `make krnlfused` / `make krnlplain` already hold the whole
kernel to bit identity with the ladders on and off, and the per-lane
equivalence campaign is done. The open gate is **timing in the shell**:
a single and a quad at 135 MHz with `FUSE_NORM=1 FUSE_ALIGN=1
RETIMING=1`, judged on kernel WNS with 0 failing endpoints, exactly as
9f73107 was judged.

**Doctrine.** None. The ladders are a per-build parameter and the
sharing doctrine's own result.

### 2. Beat-local reduction tree: use the seven idle lanes

**Mechanism.** `cft_reduce_acc` is a binary-counter stack fed one
element per issue through lane 0. At fp32 that leaves seven lanes idle
and costs a measured **11.462 cycles/beat** against elementwise's 1.250.

The eight elements of an aligned beat can be reduced *among themselves*
in three rounds on the lanes that are already there, and the result is
**bit-identical to `stream_reduce` by construction**:

> After `m` elements have arrived, level `j` of the stack is occupied
> iff bit `j` of `m` is set. At a beat boundary `m = 8k`, so bits 0, 1
> and 2 are clear and **levels 0, 1 and 2 are empty**. Therefore the
> next eight elements combine only with each other, producing exactly
> `((v0+v1)+(v2+v3))+((v4+v5)+(v6+v7))` at level 3 before any collision
> with a lower index can occur. That is the balanced 3-level tree over
> the beat, and the operand order (lower index first) matches the
> stack's.

So the beat-local tree is not an approximation of the canonical tree; it
*is* the canonical tree restricted to an aligned beat. The condition is
checkable in one comparator (`8 | m`), and a ragged tail falls back to
the existing serial path unchanged.

**What it costs and saves.** Round 1 issues 4 adds (lanes 0-3), round 2
issues 2, round 3 issues 1: **3 issues per beat instead of 8**, and
rounds from different beats pipeline freely. Steady state ~3 cycles/beat
against the measured 11.462 - a **3.8x**, call it **3.3x** after the
partial's insertion into the surviving stack (estimate; the 3-cycle
figure is derived, the 3.3x adds an allowance for the stack's own
absorption at 1 partial per 3 cycles against its measured capacity of 1
per 1.43).

Per rung: fp32 3 rounds (~3.3x), fp64 2 rounds (~2.7x), fp128 1 round
(~1.9x), fp256 1 lane (no change - and fp256 reductions already cost
~1.43 cycles/beat, so nothing is lost).

Area: a fixed 3-pattern shuffle on the array's `a` and `c` operand
busses (2 x 256 bits x ~2 LUT/bit for a 3:1 = ~1,000 LUT), a 2-bit round
counter and a 256-bit staging register. **Estimate 1,500-2,500 LUT,
under 2% of a tile**, for 3.3x on the operation SCALING calls "a
different shape and costs like one".

**Which resource it moves.** Cycles, on the one operation running 9x
slower per beat than elementwise. Also HBM: a reduction currently reads
one beat per 11.5 cycles, so it under-uses its master by 9x; at 3
cycles/beat it starts to use the port it already owns.

**What would have to be proven, and by which gate.** A cocotb bench
against `python/cft_golden/reduce.py`'s `stream_reduce` at every rung,
every rounding attribute, and specifically at `n` that is and is not a
multiple of the lane count - plus the multi-tile property
(`reduce_check.py`, `reduce-parts`) re-run, because the alignment
argument must hold on a *tile's local* range, not only on `[0, n)`.
`canonical_ranges` gives each tile a node, and the tree over a node
splits at the largest power of two, so a tile's local index 0 is
beat-aligned - but that is exactly the kind of reasoning that wants a
test with 199 known-divergent cases behind it. A negative control
(force the tree at a non-aligned boundary) must fail.

**Doctrine.** None - it lands squarely inside what the contract calls
**free**: *"Free: the schedule. Adds may be issued in any order and be
in flight together"* (docs/DETERMINISM.md). The *pairing* is untouched;
this changes only which cycle each pair issues on.

### 3. Pass period keyed on the opcode, not just the precision

**Mechanism.** `cft_lanes` derives the pipeline-enable period from
`prec` alone (`ph_last`, `rtl/cft_lanes.sv`). But at `MUL_PASSES > 1`
the passes exist only to iterate the significand multiplier, and
**most opcodes do not multiply**: `add` and `sub` are steered FMAs with
`b := 1.0`, and the whole sign / min-max / predicate / integer /
seed group bypasses the arithmetic entirely through the pipe's
precomputed-result sideband. Only `fma` and `mul` need the passes.

The elementwise engine snapshots `op` at start (`op_r`), so for an
elementwise run the period could be `NP(prec)` when `op` is `fma`/`mul`
and `1` otherwise. The sequencer mixes opcodes within a run and keeps
the conservative period.

**What it costs and saves.** Costs: one extra term in a
2-input mux on `ph_last`, plus a guard so `cft_seq` cannot select it -
call it under 100 LUT (estimate). Saves: at `MUL_PASSES=10` and fp256,
`add`, `sub`, `copysign`, all four min/max, all three predicates,
`select`, all eight integer ops and both seeds go from **1/10 rate back
to full rate**. And the reduction, whose adds are `fma(x, 1.0, y)`
through lane 0, goes from 10 pass-cycles per add back to 1 - which
matters because a reduction is already the slowest thing the tile does.

The honest limit: this tile is FMA-centric and `fma`/`mul` are the
dominant ops, so the prize is the reduction path and the twenty-odd
non-multiply opcodes, not the headline throughput.

**Which resource it moves.** Cycles, at `MUL_PASSES > 1` only. It costs
nothing at the shipping default.

**What would have to be proven.** Bit identity is structural - the
pacing is an enable, and docs/ARCHITECTURE.md already argues that "in
enabled-edge terms the pipe is exactly the single-pass pipe". The
existing multi-cycle bench family (`make simmc`, 13 targets) re-run with
the op-keyed period, plus the `krnl` suite at `MUL_PASSES=10` for every
opcode group, is the gate. A negative control: force the short period on
an `fma` run and watch it fail.

**Doctrine.** None. It makes `MUL_PASSES` cheaper without changing what
it is.

### 4. Decompose the 12,626 LUT/CU before trying to beat it

**Mechanism.** The per-CU interconnect cost is measured (12,626 LUT/CU,
3,157 LUT/master) but never *decomposed*. A 256-bit AXI4 master arriving
at the U50 shell pays, per port: a DFX decoupler, one or more register
slices / protocol converters, and a SmartConnect switch port with
arbitration and address decode.

The last one is the interesting one, because **`hw/link.cfg` and
`hw/link_quad.cfg` pin every master to exactly one HBM pseudo-channel**
- there is nothing to arbitrate and nothing to decode beyond a range
check. A full switch port for a 1:1 mapping is paying for a
generality the connectivity spec has already given away.

**What it costs and saves.** Costs nothing to find out: the routed quad
(`full_util_placed.rpt`, the same report `hw/gen_layouts.py` takes
`LUT_DEVICE = 870_720` from) has the per-instance utilisation of the
shell's interconnect and decoupler hierarchy in it already. **This is a
report-reading exercise, not a build.**

Estimate of the prize, shown as arithmetic and clearly labelled: of
3,157 LUT/master, call ~400 the decoupler and ~800 the register
slices - both genuinely required by a DFX shell - leaving
**~1,900/master, or ~7,600/CU, that a 1:1 mapping should not need**.
On a quad that is ~30,400 LUT, about a quarter of a tile
(estimate, +/- 50%; the split between "law" and "artefact" is exactly
what the report settles).

**Which resource it moves.** LUTs outside the kernel - the 32.8% of a
quad that is not arithmetic.

**Answering the question directly: is the 161,775 a law?** Partly.
`123,897` of it is shell + 1 CU and is the price of the XDMA platform -
a law for as long as the Vitis flow is the flow, and *not* a law for a
shell-less bring-up (docs/PLATFORMS.md §1). The `37,878` increment is
twelve masters of crossbar, and **the part of it that is arbitration for
a mapping with nothing to arbitrate is an artefact.** How much, only the
report says.

**What would have to be proven.** Reading the report is not a proof of
anything, it is a measurement. Acting on it - replacing the generated
SmartConnect with per-master register slices through
`compiler.userPostSysLinkOverlayTcl` - would need the whole gate stack
re-run against the resulting image (hw_emu bit-exactness, then card),
because it changes the memory path and nothing else in this repo is
allowed to change the memory path without the D-buffer comparison.

**Doctrine.** None, but note this is the *one* cross-tile share the
doctrine's own argument does not forbid: interconnect is transport, not
compute, so it is not "four-of-a-kind because it is computing four
things at once".

### 5. Concurrent engine and sequencer: two issue ports on one array

**Mechanism.** The tile already has two issuers behind one CSR, and
`MODE[15]` makes them **mutually exclusive** - a static mux with "no
arbitration, because the two never run at once". That exclusivity is a
design choice, not a requirement. A sequencer run leaves the array idle
for `LATENCY` of every `2 x LATENCY` cycles (**50%**, docs/SEQUENCER.md);
an elementwise run reaches 0.80 beats/cycle. Letting both run
concurrently, with a fixed-priority or round-robin arbiter, fills the
sequencer's half-idle array with streaming work.

**What it costs and saves.**

* Cost, in the array: one arbiter, a **1-bit owner tag on the 15-stage
  collection delay line** (15 FF), and a second flags accumulator (5
  FF + an OR tree). Under 200 LUT (estimate). The pipe already carries
  `op` and `rnd` per issue - *"which is what lets adjacent sequencer
  instructions round differently"* - so two runs with different opcodes
  and different rounding attributes can already be in flight together.
* Cost, in the CSR and the host: two run contexts, two `ap_start` /
  `ap_done` pairs, a VERSION bump that **grows** the register map. This
  is not `ap_ctrl_hs` any more, and libcft would drive the CU as an
  `xrt::ip` rather than an `xrt::kernel`. **That half belongs to study
  D**, and it is the expensive half.
* Save: up to 0.5 beats/cycle of array time during every sequencer run,
  which is the regime the third tier is built for (program-heavy
  workloads, docs/ROADMAP.md step 3).

**The hard constraint, and it is real:** `prec` selects the live bank
and is stable per run. Two concurrent runs must **share a precision**.
That is not as restrictive as it sounds - libcft already partitions one
logical operation at one precision across every tile - but it is a
constraint the CSR must enforce (refuse the second start if its
precision differs from the run in flight), and the refusal machinery for
exactly this shape already exists (`STATUS[3]`, `prec_ok`).

**Which resource it moves.** Cycles. It buys no LUTs and costs few.

**What would have to be proven, and by which gate.** A cocotb bench that
runs an elementwise stream and a sequencer program **concurrently**, with
an adversarial arbiter (grant patterns driven from a seeded generator),
asserting that both results are bit-identical to the golden model and to
the same two runs executed serially, and that each run's FLAGS word is
its own. This is the "determinism must not depend on issue cadence"
clause getting its first hardware test with two *masters of ceremony*
rather than one. A negative control: let the arbiter starve one issuer
past its FIFO depth and confirm it stalls rather than dropping a beat.

**Doctrine.** Brushes the CSR's one-run-at-a-time contract, which is a
study-D question. It does *not* brush the sharing doctrine: this is the
same free axis the doctrine already blessed ("a whole redundant COPY of
the datapath removed, on the free axis"), used the other way round.

### The variant, priced: two *symmetric* elementwise front-ends

The brief asks whether two tiles that cannot both fit could be one tile
with two issue ports. With a second `cft_engine_stream` instead of the
sequencer as the second issuer:

```
one tile          131,386 LUT +  4 masters -> 0.80 beats/cycle
dual front-end    131,386 + 5,352 (engine) + 576 (CSR) + ~500 (arbiter)
                = 137,814 LUT +  8 masters -> 1.00 beats/cycle (array cap)
```

Charging everything **above a shared shell + 1 CU base** (123,897 LUT,
which exists either way), at the measured 12,626 LUT/CU and 3,157
LUT/master:

| | LUT above the base | beats/cycle | LUT per beat/cycle |
|---|---|---|---|
| two full tiles (2 CUs, 8 masters) | 2x131,386 + 12,626 = **275,398** | 1.60 | 172,124 |
| one dual-front-end tile (1 CU, 8 masters) | 137,814 + 4x3,157 = **150,442** | 1.00 | **150,442** |

**12.6% better area per unit throughput** (derived), and - the point -
it reaches 1.00 beats/cycle, which **no single front-end can**, because
0.80 is a memory-latency artefact and a second stream hides it. Each
front-end only has to sustain 0.5 beats/cycle against its own capacity
of 0.8, so the second one can have half the FIFO depth and
`AR_DEPTH=2`, making it cheaper than the first.

Where it wins: a part that holds one tile and not two. On a Kintex-7
325T the dual front-end is `98,929 + 6,428 = 105,357 LUT` = **51.7% of
the device** against a full tile's 48.5% - **+25% throughput for +6.5%
area, where a second tile is 97% of the part and impossible.**

Where it does not win: a board whose memory cannot feed 1.00 beats/cycle
(a 64-bit DDR3 K325T is at 12.8 GB/s peak against a 12.8 GB/s demand at
100 MHz), and the U50, where four dual front-ends would need all 32
pseudo-channels and land at ~87.7% of the device for +25%.

**And the doctrine's objection is correct and now priced.** Sharing does
create a serialisation point: the array saturates at 1.00 where two
independent front-ends want 1.60. That is a 37.5% throughput loss for a
47% area saving - which is a *good* trade only on a part where the
second tile does not exist.

### 6. `MUL_PASSES` + fused ladders: the doctrine-legal fifth tile

**Mechanism.** Compose the two levers, which docs/ROADMAP.md step 3 did
on 7-series fabric but nobody has done on the U50.

**Arithmetic.** Measured U50 OOC synthesis (`hw/mc_sweep.sh`):
`MUL_PASSES=1` 123,214 LUT; `=2` 120,391; `=10` 115,310. Measured ladder
saving: 15,805 LUT. The ladders act on the aligner and normaliser, which
`MUL_PASSES` does not touch, so the saving should be additive
(cross-check: on 7-series at 10 passes the ladders were worth 17,211,
and 7-series shifters are dearer - consistent).

| config | tile LUT (flattened) | 5 tiles + 174,401 shell | of 870,720 |
|---|---|---|---|
| shipping (1 pass, ladders off) | 123,420 measured | 791,521 | 90.9% - no |
| ladders on | 107,615 derived | 712,476 | 81.8% - fits |
| 2 passes + ladders | 104,586 estimate | 697,331 | 80.1% - fits |
| 10 passes + ladders | 99,505 estimate | 671,926 | **77.2%** - fits |

Six tiles need `(740,112 - 187,027) / 6 = 92,181 LUT` per tile
(derived): **7.9% short even with both levers on.** Five is the ceiling.

**And here is the finding that should stop anyone reaching for
`MUL_PASSES` to buy tiles.** At `MUL_PASSES=N` the tile costs
0.94x-0.98x the area and the wide rungs lose `N`x the rate. To break
even you would need `N` times the tiles from a 2-6% area saving.
**`MUL_PASSES` is never a throughput-per-area win on any part.** It is a
*fit* lever ("does a tile fit at all") and a **DSP** lever, and
docs/ARCHITECTURE.md's reading of the sweep says exactly this from the
other side. The one exception is **fp32, which keeps full rate at every
pass count** - so:

* `u50-5xfp256-mc2` (5 tiles, `MUL_PASSES=2`, ladders on): fp32
  3,456 -> **4,320 Me/s (+25%)**; fp64 1,728 -> 1,080; fp128 864 -> 540;
  fp256 432 -> 270 (all -37.5%). 20 of 32 pseudo-channels, 760 of 5,952
  DSPs.
* `u50-5xfp256-mc10`: fp32 +25%; fp64 -58%; fp128 -75%; fp256 **-87.5%**.

Both are **fully doctrine-legal**: every tile is still fp256-capable,
CAPS still reads 0xF, precision is still a runtime choice, no rung is
trimmed. That is a first - **every existing five-plus-tile row in
docs/LAYOUTS.md buys its extra tiles by giving up fp256 capability on
them.** These do not.

Whether the trade is *wanted* is a different question, and the README's
own answer is no: "Raw fp32 and fp64 throughput... nothing here tries to
[match]". So rank this **behind** idea 1, which buys the fifth tile with
no throughput cost at all.

**What would have to be proven.** Bit identity is already gated - 13
multi-cycle targets, 31 tests at ten passes, the shipping suite re-run
at 21 and 60, and a dropped-carry negative control that fails 6 of 7.
The formal proof of the pass accumulation does **not** close and is
parked with its reason. So the open gate is a **link at 135 MHz with
both parameters on**, judged on kernel WNS, plus `hw/gen_layouts.py`
gaining the two parameters so the catalogue row is derived rather than
typed.

### 7. Multi-beat wide elements: decouple `BEAT_BITS` from format width

*This is one of the two genuinely unusual ideas; see §3 for the full
argument. Summary here for ranking.*

Today `BEAT_BITS < 256` **drops the wide rungs**, which makes every
narrow-beat tile a doctrine violation. `MUL_PASSES` built the pacing
machinery (`in_ready`, the pipeline enable, both issuers gating on it)
that a multi-beat element needs. Assembling one fp256 element from two
128-bit beats costs staging registers and a beat counter, not a new
datapath.

Estimated 7-series cost of a 128-bit-beat, fp256-capable tile:
**~74,500 LUT (+/- 20%)** against the measured 98,929. That turns the
Kintex-7 **160T** (101,400 LUT) from docs/PLATFORMS.md's "122% no" into
~73.5% of the device, and halves the tile's memory demand to ~6.9 GB/s -
which is the number that actually matches a 64-bit DDR3 board.

But the throughput arithmetic is unkind and must be said: 74,500 LUT for
half the work is **46% worse per unit throughput** than 98,929 for all
of it, because the fp256 bank does not halve and the ~15,300 LUT
remainder does not either. **A narrow beat is a "does it fit" lever, not
an efficiency lever - and `MUL_PASSES` dominates it on the axis they
share.** Which answers the brief's question directly: no, a narrower
beat is *not* a better trade than it looks now that `MUL_PASSES` exists.
It is a worse one, everywhere except at the bottom of the part list.

### 8. A `STREAMS` parameter: fewer masters where four are not needed

**Mechanism.** Four masters exist because a shared port cost 4.4
cycles/beat (measured) against the split port's 1.25. But:

* `cft_seq` already uses only two (A and D). "Four masters for a machine
  that reads one array slowly would buy nothing and cost three HBM
  pseudo-channel groups" - `rtl/cft_krnl.sv`'s own header.
* At `MUL_PASSES=10` in fp256 mode a tile retires one beat per 10 cycles,
  so its whole demand is `4 x 0.3456 = 1.38 GB/s` (derived from
  docs/PLATFORMS.md's per-master 3.456 GB/s) - **one master serves it
  with 75% headroom.**

So a `STREAMS` parameter (4 / 2 / 1) would save **3,157 LUT of crossbar
per dropped master** (derived) plus its in-kernel AR/FIFO logic, and one
HBM pseudo-channel each.

**Arithmetic.** A 1-master wide-rung tile: `9,471 LUT` of crossbar and
3 PCs saved per tile; the pseudo-channel wall moves from **8 tiles to
32**. But by idea 6's rule, buying tiles with passes loses, so the wall
moving is a fact without a customer on the U50 today. Its customer is a
**DDR4 card** - the U200/U250 are memory-bound at ~5 tiles against an
area wall of 5-7 (docs/PLATFORMS.md), and a wide-rung tile that needs
one master instead of four is exactly the shape that unbinds them.

**Which resource it moves.** LUTs outside the kernel, HBM/DDR ports,
and it makes the open-core target simpler - `cft_krnl.sv` already
observes that "on a single-port memory... tie the three masters
together, ignore the select, and the address alone reaches the buffer.
That is the cheaper structure and the one the open-core targets want."

**Proof.** The existing `krnl` suite at `STREAMS=1` (the engine's
determinism argument is about the single issue point, not the port
count, so nothing numeric moves), plus `make cycles` to record the new
cycles/beat honestly per rung.

### 9. A 512-bit beat

*The second genuinely unusual idea; see §3.*

### 10. What a ring node costs, against a second AXI master

**Estimate, and no ring RTL exists in this repo**, so every line is a
guess with its reasoning attached. A deterministic ring node on 7-series
GTX / UltraScale GTY:

| block | LUT | why |
|---|---|---|
| GTX/GTY transceiver | **0** | hard block; 8b/10b, comma detect, elastic buffer and clock correction are all inside it |
| framing (SOF/EOF, length) | ~300 | |
| CRC-32 over 32 bits/cycle | ~300 | |
| credit-based flow control | ~200 | |
| async FIFO to `ap_clk` | ~200 + 1-2 BRAM | |
| ring forward/consume decode | ~300 | |
| **total** | **~1,300 (+/- 50%)** | plus 1-2 transceivers, 1-2 BRAM |

Against a second AXI master's **3,157 LUT** of measured shell crossbar
(before its in-kernel channel logic).

**So a ring node costs roughly half an AXI master, and spends a resource
the design currently uses none of.** The PZ-K7325T-SOM carries 16 GTX
pairs; the tile uses zero. What is expensive about the ring is not the
node - it is the protocol (deterministic ordering across nodes), the
orchestrator, and the software, none of which exist. **The doctrine's
"scale out over a ring" is cheap in fabric and expensive in design, and
this study can only price the cheap half.**

---

## 2. Is this already recorded? The doctrine's rejections, re-checked

docs/ROADMAP.md's sharing doctrine rejects several obvious moves *with
measurements*. `MUL_PASSES` did not exist when it was written. Here is
each verdict, whether it still holds, and whether the new lever changes
it.

| move | recorded verdict | measurement behind it | does it still hold? |
|---|---|---|---|
| **Share anything across tiles (datapath)** | rejected: tiles exist to run in parallel; anything shared becomes a serialisation point | argument, plus `cft_csr` at 624 LUT being the only genuinely duplicated non-datapath block | **Holds, and idea 5 prices it.** A shared array saturates at 1.00 beats/cycle where two front-ends want 1.60: 37.5% of the throughput for 47% of the area. The doctrine is right that it serialises; what it did not do was price it, and priced, it is a good trade only where the second tile cannot exist. |
| **Share `cft_csr`** | rejected: the Vitis CU model gives every CU its own AXI4-Lite; 4 x 624 is 0.5% of a quad | measured | **Holds unchanged.** |
| **Fractured multiplier (`FUSE_MUL` / `cft_mulfrac`)** | rejected: measured 262 -> 259 DSP and **+693 LUT** | measured, with WNS +0.959 -> -0.181 | **Superseded, and this is the one verdict `MUL_PASSES` overturns.** Both attack the significand multiplier. `cft_mulfrac` spent 693 LUT to save 3 DSPs (1.1%); `MUL_PASSES=10` saves 206 DSPs (79%) *and* 7,904 LUT (6.4%). They are already mutually exclusive by elaboration guard (`cft_lanes: FUSE_MUL and MUL_PASSES > 1 do not compose`). **Recommendation: treat `FUSE_MUL` as dead RTL kept for the granule-grid experiment only**, and say so where it is documented, because a reader today can reasonably think it is the multiplier lever. |
| **The granule grid** (cut multiplier *width*, not column count) | unbuilt; noted as "the version that would pay" | none | **Still unbuilt, and its prize shrank.** ROADMAP already records this: "the granule grid's remaining prize is throughput per DSP at the narrow rungs, not tile area." Agreed - and per §0 the tile is 87.9% array but the *multiplier* is DSPs, so a LUT-bound part does not care. |
| **Share the aligner / normaliser (`FUSE_NORM`, `FUSE_ALIGN`)** | accepted numerically (-15,805 LUT, bit-exact), rejected on timing | OOC +0.307 -> +0.097; shell link **-0.577 ns / 776 endpoints** | **The numeric verdict holds; the timing verdict is stale.** See idea 1: it was taken on the 139,404 tree, un-retimed, with the seed-ROM DSP path still present. `MUL_PASSES` does not change the timing - but it changes the *composition*, and on 7-series the two together are what put a tile on a K325T at 48.5%. |
| **Trimmed / heterogeneous tiles for area** | rejected 2026-08-30: precision must stay a runtime choice | measured (an fp32+fp64 tile is 45% smaller; nine fit where four full tiles do) | **Holds - and `MUL_PASSES` is now the doctrine-legal substitute.** It buys area without trimming a rung: every tile stays fp256-capable, CAPS still reads 0xF. Idea 6 is the first five-tile U50 layout that keeps the homogeneity mark. |
| **Freed area becoming more fp32 lanes** | rejected: "Lane count is pinned by the 256-bit beat... freed area cannot become more fp32 lanes. It becomes more tiles." | structural | **Holds**, and idea 9 is the only thing that changes it: a wider beat is the one way to add lanes, and it adds them to every rung at once. |
| **A narrower beat** (`BEAT_BITS`) | exists and is tested (`tb_krnl_quarter`), but "narrowing the beat means dropping the wide rungs" | guard, measured quarter tile | **Holds as written, and idea 7 removes the premise.** The guard's justification - "a format wider than the beat would need multi-beat elements and an assembly buffer" - was written before the array could stall. It can now. |
| **A wider beat (`BEAT_BITS > 256`)** | refused: "the fp256 bank is a single instance rather than a loop and would silently compute only the low element" | elaboration guard | **This is a coding limitation, not a law**, and idea 9 says what it would be worth. |
| **A shared divide/sqrt unit across tiles** | rejected for streamed arrays (the FMA array out-throughputs an SRT recurrence 4x), *accepted in principle* for the sequencer's dependent chains at low duty | derived, ~25-30 FMA passes vs ~125 SRT cycles | **Both halves hold, and `MUL_PASSES` sharpens the first.** At `MUL_PASSES=10` the composed fp256 divide costs 28 passes x 10 pass-cycles = ~280 cycles, against a 237-bit SRT unit's ~125. **On a multi-cycle tile the composed route loses**, and the standing verdict inverts. Worth recording, because the third tier is exactly where multi-cycle tiles live. Idea 3 partially rescues it: only the multiplies in the sequence pay the passes. |
| **A shared crossbar / thinner AXI plumbing** | *not recorded at all* - SCALING names the 24k figure as a scaling hazard and stops | measured (24k pre-four-master; 12,626/CU and 161,775 quad fixed in the four-master era) | **Open.** Ideas 4 and 8. This is the largest un-attacked block in the design: 32.8% of a quad is not arithmetic. |

One correction worth making explicit, because two figures for the same
thing appear in the repo: docs/SCALING.md's **24k LUT per-CU AXI
plumbing** is a **pre-four-master** number (it was written 2026-08-30
alongside "the four-master change probably made this worse"). The
four-master era's own measurements are **123,897 for shell + 1 CU** and
**12,626 per further CU**. Both can be true: the first CU pays for the
switch fabric and each further one pays for its ports. Quote 12,626 and
3,157 for anything incremental; quote 24k only for the historical claim.

---

## 3. Two genuinely unusual ideas (and three more, labelled speculative)

### 3a. Multi-beat wide elements: `BEAT_BITS` stops meaning "format width"

**The premise this removes.** `cft_krnl` guards
`BEAT_BITS < format width` because "a format wider than the beat would
need multi-beat elements and an assembly buffer". True when written. But
on 2026-09-06 `MUL_PASSES` gave the array a pipeline enable, gave both
issuers an `in_ready` to gate on, and gave the reduction accumulator a
`clk_en` that counts accepted edges rather than wall cycles. **The
machinery for "the array is not ready this cycle" now exists and is
gated by 13 cocotb targets.** A multi-beat element is that same
machinery with a beat counter in front of it.

**The mechanism.** At `BEAT_BITS = 128`, three read streams deliver 128
bits per beat. An fp256 element is assembled from two consecutive beats
into a 256-bit staging register per operand; the array is held for one
cycle while beat 1 arrives; the result is disassembled into two write
beats. The engine's beat FSM already counts beats and already knows
`beats_total` from `n` and the precision shift (`beat_sh_r`), so the
change is a per-rung `BEATS_PER_ELEM` in the same place `epb`
(elements-per-beat) lives today.

**What it costs.**

* Staging: 3 read operands x 256 bits + 1 write x 256 = 1,024 FF, plus
  the muxes to fill them. ~1,500 LUT (estimate).
* Engine FSM: a sub-beat counter and an `epb`/`bpe` split. ~300 LUT.
* Nothing in the arithmetic. The lanes see full-width operands exactly
  as they do today.

**What it saves,** on 7-series fabric with the ladders on and
`MUL_PASSES=10` (the measured 98,929 LUT tile), halving the fp32, fp64
and fp128 lane counts while fp256 stays at one lane:

```
shared ladders (do NOT shrink - one 720-bit ladder either way)  ~20,400
fixed remainder (sequencer, engine, CSR, steering)              ~16,800
per-lane logic, remainder                                       ~61,700
  split by bank share (23.2 / 22.1 / 24.0 / 30.8%):
    fp32  14,300 -> 7,150   fp64  13,600 -> 6,800
    fp128 14,800 -> 7,400   fp256 19,000 -> 19,000  (unchanged)
  saving                                                        ~21,400
remainder partly beat-width-scaled                              ~3,000
  ---------------------------------------------------------------------
  tile                                          98,929 - 24,400 = ~74,500
```

**Estimate, +/- 20%**, and the two structural facts in it are the
important ones: **the fp256 bank does not shrink** and **the shared
ladder does not shrink**, because both are sized by the widest format,
not by the beat.

**What it changes on the part list.**

| part | LUT | full tile 98,929 | half-beat ~74,500 |
|---|---|---|---|
| XC7K325T | 203,800 | 48.5% | 36.6% (two = 73.1%, **and two fit**) |
| XC7K160T | 101,400 | **122% - no** (PLATFORMS) | **73.5% - fits** |
| XC7A200T | 134,600 | 73.5% | 55.3% |
| XC7A100T | 63,400 | 156% - no | 118% - still no |

**And memory.** A 128-bit beat halves the tile's demand from 13.82 GB/s
to ~6.9 GB/s (derived), which is what makes a 64-bit DDR3 board
comfortable rather than exactly saturated. On the third tier's own
terms - "Drop the bandwidth, because the sequencer already did" - this
is the lever that matches the memory those boards have.

**The honest verdict, and it is negative for big parts.** 74,500 LUT for
half the work is **46% worse per unit throughput** than 98,929 for all
of it. Narrowing the beat is a fit lever only. **Where it earns its
place is that it is the ONLY lever that keeps fp256 capability on a part
that cannot hold a 256-bit-beat tile** - which is precisely the
homogeneity doctrine's requirement, and which today's `BEAT_BITS` guard
makes impossible by construction.

**What would have to be proven.** `tb_krnl_quarter` already runs a
narrow-beat kernel against the golden model; the new bench is the same
shape with the wide rungs enabled - every rung, every attribute, at `n`
that straddles element and beat boundaries, plus the fault-injection
bench (a bus fault mid-element must not produce half an element) and
`make cycles` to record the real rate. The formal gate has nothing to
say here; the risk is in the engine FSM, not the arithmetic.

### 3b. A 512-bit beat: two fp256 lanes, and half the per-CU overhead

**The premise this removes.** `BEAT_BITS > 256` is refused *because the
fp256 bank is written as a single instance rather than a `generate`
loop*. That is a coding limitation with a guard in front of it, and the
guard's comment says so.

**Why it is worth removing.** Doubling the beat doubles every bank -
2x area for 2x throughput, which is a wash on the arithmetic - but it
does **not** double:

* the fixed ~15,300 LUT remainder (CSR, sequencer control, engine FSM);
* the **per-CU crossbar increment of 12,626 LUT**, because it is four
  masters either way;
* the **four HBM pseudo-channels**, because it is four masters either
  way (at double width).

Counting everything above a shared shell + 1 CU base:

```
two 256-bit tiles   2 x 131,386 (tiles) + 12,626 (2nd CU) = 275,398 LUT,  8 PC
one 512-bit tile    2 x 114,721 (banks, doubled)
                    + ~26,000 (remainder, partly doubled, estimate)
                    + 0       (still one CU, still four masters)
                                                          = 255,442 LUT,  4 PC
```

**~19,956 LUT saved (7.2%) and half the pseudo-channels, for the same
compute** (estimate; the remainder scaling is the soft number). And the
pseudo-channel halving is the interesting half: the U50's hard wall is
32 PCs / 4 masters = 8 tiles, and a 512-bit-beat tile is *two tiles of
compute on four masters*, so **the interface wall doubles in effective
compute, from 8 tile-equivalents to 16.**

**The blocker, named.** 256 bits is the native HBM pseudo-channel width,
and docs/ARCHITECTURE.md records that "a 512-bit master demonstrably
lost write payloads through the 2022-era platform's emulation converter
models". That is an *emulation model* failure, not a silicon one - but
this project's gate stack runs through hw_emu before it runs on a card,
so a 512-bit master would have to be proven on the card first and in
emulation never, which inverts the order every other change here has
been proven in. **That is a serious process objection, and it is why
this ranks tenth rather than third.**

An alternative that dodges it entirely: keep the masters at 256 bits and
make the *compute* beat 512 by pairing two memory beats - which is idea
3a's assembly buffer running the other direction, and reuses the same
staging hardware.

**Contract impact: none.** Element `i` still depends on element `i`. The
reduction accumulator's beat-local tree (idea 2) gains a fourth round.
`canonical_ranges` is unaffected - it is over element indices, not
beats.

### 3c. Speculative: the array's idle pass-phase cycles cannot be used

Worth writing down as a **negative result**, because it is the first
thing anyone will propose about `MUL_PASSES`.

At `MUL_PASSES=N` the array is enabled 1 cycle in `N` at the wide rungs.
It looks like `N-1` free issue slots. It is not:

* `cft_lanes` holds **every stage register in the array** for `N-1` of
  every `N` cycles, not just the multiplier's. So the idle cycles are
  idle in all 15 stages.
* Letting the non-multiplier stages run every cycle would make the
  multiplier a 1-deep bottleneck feeding a full-rate tail: throughput is
  still `1/N`.
* Interleaving `N` independent operations through one column set needs
  `N` copies of the pipeline state - `N x 528` bits in `cft_mulpass`'s
  accumulator alone, and `N` copies of the aligner, normaliser and round
  stage, which is most of a lane. **That is `MUL_PASSES=1` with extra
  steps.**
* Running a *different precision* in the idle cycles needs two live
  banks, which is the exclusivity the whole sharing argument rests on.

**Conclusion: the pass-phase holes are structurally unusable.** The
only recoverable idleness in this design is the *scheduling* kind - the
0.20 the memory system loses, the 0.50 a sequencer run loses, and the
0.91 an fp32 reduction loses - and ideas 2 and 5 are the two that reach
it.

### 3d. Speculative: `MUL_PASSES` is a bandwidth lever, and nobody has said so

The pass count divides the wide rungs' memory demand by the same factor
it divides their rate. Derived from docs/PLATFORMS.md's per-master
3.456 GB/s at 135 MHz:

| config | fp256 tile demand | fp32 tile demand |
|---|---|---|
| `MUL_PASSES=1` | 13.82 GB/s | 13.82 GB/s |
| `MUL_PASSES=10` | **1.38 GB/s** | 13.82 GB/s (unchanged) |

Three consequences the docs do not draw:

1. **A wide-rung multi-cycle tile needs one master, not four** (idea 8):
   9,471 LUT and 3 pseudo-channels per tile.
2. **The DDR4 cards stop being memory-bound.** A U250 is 5.57 tiles at
   77 GB/s and 7 tiles by area (docs/PLATFORMS.md); at
   `MUL_PASSES=10` the wide-rung demand is 1.38 GB/s/tile, so **memory
   stops binding entirely and the area wall at 7 is the only one left**.
   That is the first argument this repo has for a U200/U250 that is not
   "more LUTs".
3. **The third tier's boards work in program mode and not in stream
   mode.** A 64-bit DDR3 K325T at 100 MHz has ~12.8 GB/s peak against a
   full-rate tile's ~10.2 GB/s (derived at 100 MHz) - fine for one tile,
   impossible for two. In sequencer mode ("hundreds of instructions per
   sample against a few words of I/O") it does not bind at all. **So the
   third tier's memory story is: one streaming tile, or as many
   program-mode tiles as fit.**

### 3e. Speculative: what the 161,775 would be without the Vitis shell

Not evaluable here (no build, no report), but the shape of the answer:
of `123,897` (shell + 1 CU), UG1120's floorplan leaves 167,680 LUT
outside the dynamic region for the static region - PCIe/XDMA, HBM
controllers, clocking, DFX infrastructure. A shell-less bring-up
(docs/PLATFORMS.md §1, "Shell-less bring-up, and why it might be the
point") replaces all of it with a DIY XDMA, which for three linear
streams and one writer is a far smaller thing than a general-purpose
platform - but it is also months of engineering and the loss of `v++`,
`xbutil`, XRT and every gate this repo runs through them. **The cost is
not LUTs, it is the flow**, and that is a study-D judgement.

The measurable half is idea 4, and it costs zero builds.

---

## 4. The fit table you would put in front of a buyer

Two accountings, because docs/PLATFORMS.md is explicit that mixing them
is how a board gets bought on a wrong number:

* **Budget (A), bare part**: `device_LUT x 0.85`, tile charged at its
  flattened figure, **platform wrapper not counted** - so every bare-part
  row is an upper bound.
* **Budget (B), Alveo shell card**: per-SLR dynamic LUT at 85%, each CU
  charged `tile(hierarchy-preserved) + 12,626`.

Tile figures used. Measured are in **bold**; the rest are derived or
estimated as shown.

| configuration | UltraScale+ (flattened) | 7-series (measured on the real parts) |
|---|---|---|
| shipping: 1 pass, ladders off | **123,420** | ~126,400 (est: 109,225 + 17,211) |
| + fused ladders | 107,615 (derived) | **109,225** (1 pass, ladders on) |
| 10 passes, ladders off | **115,310** (OOC synth) | ~116,100 (est) |
| 10 passes + ladders | 99,505 (derived) | **98,929** |
| half-beat (128), fp256 kept, 10 passes + ladders | ~75,000 (est +/-20%; 99,505 less the same 24.7%) | **~74,500** (est +/-20%) |
| dual front-end, 10 passes + ladders | 105,933 (derived: +6,428) | 105,357 (derived) |

### The U50, the card the project owns

`n` tiles = `n x tile + 123,897 + 12,626 x (n-1)`, against 870,720 LUT,
practical ceiling 85% = 740,112. The model is calibrated at **2.0%
optimistic** (it predicts 687,319 for a quad that placed at 701,664), so
add ~2 points to every figure before believing it.

| layout | tile LUT | model LUT | of device | verdict | fp256 on every tile? |
|---|---|---|---|---|---|
| **4x, shipping** (built) | 123,420 | 655,455 | 75.3% (routed **80.6%**) | **built** | yes |
| 5x, shipping | 123,420 | 791,501 | 90.9% | no | yes |
| **5x, ladders on** | 107,615 | 712,476 | **81.8%** | **fits (flattened); 86.4% under the conservative accounting - a build decides** | **yes** |
| 5x, 2 passes + ladders | 104,586 | 697,331 | 80.1% | fits | yes, at -37.5% wide rate |
| 5x, 10 passes + ladders | 99,505 | 671,926 | 77.2% | fits | yes, at -87.5% fp256 rate |
| 6x, 10 passes + ladders | 99,505 | 784,057 | 90.0% | no (needs <= 92,181/tile) | - |
| 8x (the HBM wall) | - | - | - | needs <= 65,979/tile: **out of reach** | - |

(`docs/SCALING.md` writes the fifth-tile sum as 791,521; the addition is
791,501. Same verdict, and flagged because this repo's rule is to derive
constants rather than transcribe them.)

HBM: 4 PC/tile, 32 available - 5 tiles is 20, so **area binds and the
interface does not**, at every row above. DSP at 5 tiles: 1,310 (1 pass,
at the mc_sweep-measured 262/tile) or 280 (10 passes, at 56/tile) of
5,952 - never a constraint, exactly as docs/SCALING.md says.

**Headline: the fifth U50 tile is a timing question, not an area
question.** Every route to it exists; the cheapest one costs no
throughput at all and its only obstacle is a measurement taken on a tree
that no longer exists.

### The shell cards, budget (B)

Unchanged from docs/PLATFORMS.md's own arithmetic except for the memory
column, which idea 3d moves:

| card | area wall | memory wall, 1 pass | memory wall, 10 passes | binding |
|---|---|---|---|---|
| U50 | 4 (5 with ladders) | 22.9 | 229 | **area** |
| U55C / U280 | 6 | 33.3 | 333 | **area** |
| U250 | 7 | **5.57** | **55.7** | memory at 1 pass, **area at 7** at 10 |
| U200 | 5 | 5.57 | 55.7 | both ~5 at 1 pass, **area at 5** at 10 |

The U250 row is the new one: a DDR4 card is memory-bound at ~5 tiles
today and **area-bound at 7 with a multi-cycle wide rung**, which is a
40% increase in the tile count of the "monolithic licensed step-up"
docs/ROADMAP.md's scale-out doctrine names. At the cost of wide-rung
rate, so it is a layout rather than a default.

### The bare parts, budget (A)

85% of device, wrapper not counted. Measured 7-series tile figures.

| part | LUT | 85% budget | shipping-equivalent | 10 passes + ladders (98,929) | half-beat (~74,500) | best answer |
|---|---|---|---|---|---|---|
| XC7K480T | 298,600 | 253,810 | 2 at 99.6% of budget | **2 at 78.0%** | 3 at 88.1% | **2 full tiles** |
| XC7VX485T | 303,600 | 258,060 | 2 at 98.0% | **2 at 76.7%** | 3 at 86.6% | **2 full tiles** |
| XC7K420T | 260,600 | 221,510 | 2 - no | 2 at 89.3% - tight | 2 at 67.3% | 2, tight |
| XC7K410T | 254,200 | 216,070 | 2 - no | 2 at 91.6% - tight | 2 at 69.0% | 2, tight (and absent from openXC7's db) |
| **XC7K325T** | 203,800 | 173,230 | 1 at 73.0% | **1 at 57.1%** | **2 at 86.0%** - tight | **1 full tile, or 1 dual-front-end at 60.8% for +25%** |
| XC7K160T | 101,400 | 86,190 | **no tile at all** | **no** (114.8%) | **1 at 86.4%** | **half-beat is the only fp256-capable answer** |
| XC7A200T | 134,600 | 114,410 | 1 at 110% - no | **1 at 86.5%** - tight | 1 at 65.1% | 1, at ~57 MHz (-1 grade) |
| XC7A100T | 63,400 | 53,890 | no | no (183%) | no (138%) | fp32-max tile only; fp256 unreachable at any beat width |
| XC7A35T | 20,800 | 17,680 | no | no | no | quarter tile, no fp256 |
| XCKU5P (KCU116) | 216,960 | 184,416 | 1 at 66.9% | 1 at 54.0% (US+ figures) | 2 at 81.3% | 1 tile, memory-starved ~30% by the 32-bit DDR4 |

**Three headlines for a buyer.**

1. **A Kintex-7 325T at ~$100-$1,154 holds a full, contract-compliant,
   fp256-capable tile at 48.5% of the device and about 103 MHz**
   (measured, -2 grade, synthesis) - and a **dual-front-end** tile at
   51.7% for 25% more throughput, where a second tile is 97% of the part
   and impossible.
2. **The Kintex-7 160T becomes reachable** - PLATFORMS says "122% no"
   and a half-beat fp256-capable tile puts it at ~73.5% (estimate). That
   is the cheapest part in the survey that could carry the whole ladder.
3. **The U50 quad is not the ceiling.** Five tiles is 81.8% by SCALING's
   own arithmetic with a parameter that is already built and already
   proven bit-exact; the only thing between here and there is one timing
   run.

---

## 5. What I would build first, with one week

**Re-measure the fused ladders on the current tree, and if they close,
link a five-tile image.** Idea 1, and it is chosen over everything else
because it is the only item on the list that is *entirely already built*
- the RTL exists, the equivalence gates exist and are green
(`make krnlfused` / `make krnlplain`), and the parameter is per-build.
The whole week is builds and reading reports.

| day | what | why |
|---|---|---|
| 1 | `make krnlfused` + `make krnlplain` on the current tree; `yosys-lint`; the 18-target suite | re-establish bit identity on 9f73107's tree before spending a build hour |
| 1 | OOC synth+impl, `FUSE_NORM=1 FUSE_ALIGN=1 RETIMING=1`, 135 MHz | the cheap proxy; record **path delay, not slack** |
| 2-3 | **single-tile link**, ladders on, retimed, 135 MHz | the number that decides it. OOC has been wrong by 0.88 ns in this design's history |
| 3-5 | **quad link**, same settings, one at a time (the build box is 46 GB and a quad place wants 25-30) | four instances pay ~0.115 ns more per path than one; a single closing does not imply a quad |
| 5-7 | if the quad closes: generate a **five-CU link config** (`hw/gen_layouts.py` extends to any power of two; five needs the generator taught a non-power-of-two count) and link it | this is the actual prize |

**The measurement that decides whether it worked**, in order of
authority:

1. **Quad kernel WNS at 135 MHz with 0 failing endpoints**, on
   `clk_out1_ulp_clk_wiz_0` - not the global WNS, which is a shell
   transceiver path identical in every build on this platform. The
   comparison is against 9f73107's ladders-off quad at **+0.143**.
   Anything above 0 with 0 failing endpoints is a pass; anything that
   needs a clock reduction is *also* a pass for correctness (determinism
   is clock-independent by construction) but a different product.
2. **Routed LUT of the five-CU link against 740,112.** The flattened and
   hierarchy-preserved accountings disagree by 6.5% about whether five
   fits; the routed number is the arbiter, and it also **recalibrates
   `hw/gen_layouts.py`'s 2% optimism** for every future row.
3. **`make krnlfused` still green**, and `make cycles` on the ladders-on
   tile - because the ladder is on the operand path and the reduction
   accumulator's operands were already registered once to fix exactly
   this kind of coupling.

**Why not idea 2 (the reduction tree) first, when it is a 3.3x?**
Because it is new RTL in the collection path, and this repo's own
history says the expensive failures come from new logic on the operand
bus (the `s0_byp_d` unconditional latch, -0.577 ns). Idea 1 is a
parameter flip on proven RTL and it either closes or it does not.
Idea 2 is the right *second* week, and its first hour should be
`hw/synth_attrib.tcl` on the shuffle alone.

---

## 6. What I could not evaluate

* **Anything requiring a synthesis or implementation run.** The host is
  busy; the brief forbids it. So every "estimate" in this document is an
  estimate for that reason and not for a better one. Specifically
  unmeasured: the fused ladders on the current tree, `MUL_PASSES` +
  ladders composed on the U50, any five-CU link, and every half-beat and
  512-bit figure.
* **The decomposition of the 12,626 LUT/CU** (idea 4). It needs the
  routed quad's hierarchical utilisation report, and **no `.rpt` files
  are committed to this repository** - I checked. The number is
  therefore a measured total with an un-measured composition, and my
  "~1,900/master is arbitration a 1:1 mapping does not need" is a guess
  from AXI SmartConnect structure, not from this design.
* **Whether the ladder path is still 7.310 ns.** That is the single
  number idea 1 turns on, and it is one OOC run away. I can say the
  measurement is stale; I cannot say which way.
* **7-series implementation, at any pass count.** docs/ARCHITECTURE.md
  already flags this: the K325T's -0.066 ns is *synthesis* slack on a
  fabric where routing usually decides. Every 7-series fit in §4 is an
  area fit on synthesis numbers, and 7-series carry structure (42 CARRY4
  where UltraScale+ uses 21 CARRY8) makes them optimistic.
* **The half-beat tile's real cost.** My ~74,500 rests on splitting the
  measured 98,929 into "shared ladder / fixed remainder / per-lane", and
  only the *bank* split (26,592 / 25,304 / 27,492 / 35,333) is measured.
  The other two lines are apportioned. An ablation run of the kind that
  produced the 22,302 / 15,533 shifter figures would settle it in one
  batch.
* **The ring, entirely.** No ring RTL, no protocol, no transceiver
  bring-up exists in this repo. My ~1,300 LUT/node is block-level
  guesswork from what a GTX/GTY hard block already contains. The claim I
  will stand behind is the *comparison* (a node is cheaper than an AXI
  master and spends transceivers the design does not use), not the
  number.
* **Whether a second run context is reachable through XRT.** Idea 5's
  expensive half is a CSR and host-library question - `ap_ctrl_hs` is
  one run per CU, and docs/ARCHITECTURE.md already records that pyxrt
  cannot even *read* the status CSRs. Study D's ground.
* **Anything about the arithmetic datapath itself.** The aligner, the
  normaliser, the round stage, the multiplier's internal structure and
  the granule grid all belong to study A. Where this document touches
  them (the ladders, `MUL_PASSES`) it uses their measured kernel-level
  numbers and does not reason about their interiors.
* **Placement and congestion.** Every LUT figure here is a count. The
  quad's own history says congestion, not logic depth, is what four
  instances add ("the same design pays ~0.115 ns more per path at four
  instances than at one"), and a five-CU floorplan on a two-SLR part is
  a physical-implementation question - study C's ground, and the one
  most likely to make the fifth tile fail for a reason no arithmetic in
  §4 can see.
