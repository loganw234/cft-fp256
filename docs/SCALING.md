# Scaling

What gets harder as tile count rises, what does not, and where the
shape of the machine has to change. Numbers here are measured on the
U50 unless marked otherwise, and the derivations are in the commit
history. The older figures come from differencing routed builds; the
2026-09-01 tile figures are **out-of-context synthesis**, which is a
weaker thing and is marked as such wherever it is used - this project
has one recent, expensive demonstration that OOC slack does not survive
the shell.

The target ladder is powers of two - **1, 2, 4, 8, 16, 32, 64** - with
one tile a first-class configuration rather than a degenerate case.
Which of those are buildable today is a separate question from which
the contract must hold for, and they get different answers below.

## The property that does not degrade

**Determinism constrains which INDEX is computed, never which TILE
computes it.**

The contract is that element i of the output depends on element i of
the inputs and nothing else. Which physical tile evaluated it cannot
enter the answer, the flags OR is commutative, and the writer emits in
index order regardless of arrival order. So all of the following are
bit-safe and stay bit-safe at any tile count:

- uneven work distribution
- work stealing and dynamic load balancing
- out-of-order completion
- tiles of differing speed, or a tile that stalls

This is worth stating early because the usual reason a deterministic
system cannot load-balance does not apply here. Scheduling freedom is
available; what limits scale is the control plane, not the contract.

Reductions tighten it by exactly one notch and no more. The tree shape
is fixed by index, so a partial result is reusable only if its range is
exactly a node of the canonical tree - but **which tile evaluates that
node is still free**. `cft_golden.reduce.canonical_ranges()` produces
the nodes; `combine()` folds them. Tested to 64 parts.

## The ladder, and where it breaks

| tiles | shape | limited by |
|---|---|---|
| 1-4 | one bitstream, one device | **shipping today** |
| 8 | one bitstream, bigger part | **LUTs first** - the sequencer-era tile caps this part at four - then HBM pseudo-channels |
| 16-64 | many devices, or the chiplet ring | control plane, interconnect |

The break between 8 and 16 is not gradual. Below it you are placing
more compute units in one dynamic region; above it you are building a
different machine.

The middle row used to read "LUTs, HBM pseudo-channels" as a pair that
bound at about the same place. They no longer do: the sequencer put
about 40% onto the tile even after its array was shared and its control
logic cut (98,310 -> 139,404), so on this device area runs out at four
where the pseudo-channels would have lasted to eight. The next section
shows the arithmetic.

### What caps a monolithic tile - and as of 2026-09-01 it is area

**HBM pseudo-channels, and the four-master engine made this tighter.**
The U50 exposes 32. Each tile now has four AXI masters - one per
operand stream plus the writer - and one pseudo-channel per master is
sufficient (about 9.9 GB/s available against a master's ~3.3 GB/s
demand at 130 MHz and 1.25 cycles/beat). Four per tile against 32 is a
**hard wall at eight tiles**. Raw bandwidth would not bind until
roughly 23 tiles, so this is an interface limit, not a throughput one.

*As of 2026-08-31 the mapping matches this analysis: hw/link.cfg and
hw/link_quad.cfg place each master on exactly one pseudo-channel. That
was done for ORDERING (same-ID responses in issue order by
construction, not by trusting the HBM switch across destinations), and
the wall it implies is now the wall the configs actually have. The
cost is a 256 MB cap per argument buffer per tile, which libcft does
not capacity-split - an oversized run fails loudly at allocation.*

**LUTs, and the orbit sequencer moved this wall a long way in.** Shell
123,897 fixed, device 871,680 by the datasheet (870,720 by the routed
report's Available column, the figure hw/gen_layouts.py budgets
against), practical routing limit around 85%.

The history first, because the conclusion below used to be drawn from
it. The tile was 119,543 in the shipped pre-sharing configuration, and
the 2026-08-31 size campaign brought the kernel to **98,310 out of
context with FUSE_NORM/FUSE_ALIGN on and the BRAM FIFOs**. Four
pre-sharing tiles are 69.15% of the device, so the U50 held four
comfortably; at the campaign figure six were ~81%, and "six to eight"
was the answer.

**None of those tiles had a sequencer in them.** `cft_seq` landed on
2026-09-01, and it arrived with a private second copy of the ALU array
that took the tile to 288,764 LUT - a quad of which asked for
**1,316,831 LUT of the 871,680 the part has** and died in placement
(`VPL UTLZ-1`, LUT-as-logic over-utilised). Extracting the array into
one shared `cft_lanes` and putting the sequencer's control logic on a
diet gets it back to **139,404 LUT out of context at 135 MHz** with the
fused ladders off, which is what the current builds carry, or 123,599
with them on. Against the fixed shell, the same arithmetic this
section has always done:

| tiles | ladders off (139,404) | ladders on (123,599) |
|---|---|---|
| 4 | 557,616 + 123,897 = 681,513, **78%** | 494,396 + 123,897 = 618,293, **71%** |
| 5 | 697,020 + 123,897 = 820,917, **94%** | 617,995 + 123,897 = 741,892, **85%** |

**So the area wall is four.** Five does not route in either
configuration - one is 9 points past the practical limit and the other
is sitting on it - where the pre-sequencer tile reached six. The
interface wall at eight is no longer the binding one; area is, and by
a comfortable margin.

Two cautions on that table. It uses the SINGLE-tile shell for every
row, which is what ROADMAP.md's five-tile sizing does, and it
understates a quad: differencing the failed pre-refactor quad link
(1,316,831 asked against 4 x 288,764 = 1,155,056 in the kernels) puts
the quad's own fixed cost near 161,775 LUT, sixteen masters' worth of
crossbar rather than four. Carry that instead and a quad is 719,391
(82.5%) with the ladders off and 656,171 (75.3%) with them on, which is
where ROADMAP.md's and `rtl/cft_krnl.sv`'s ~80% / ~75% come from. And
all of it is **out of context**: a single tile linked at 135 MHz with
the ladders on missed timing at -0.577 ns where OOC had read +0.097, so
these are area figures and nothing more. A single and a quad are
building at 135 MHz with the ladders off as this is written; neither
result is known.

*Known now (2026-09-02):* the single closed (+0.045, with or without
retiming); the quad missed 135 twice (-0.113, -0.141). Since then the
tile lost 16k LUT out of context without touching the ladders - the
seed ROM as case tables (129,708) and the round stage's arithmetic
moved up a stage (123,420) - which is within 200 LUT of the
ladders-on figure with none of its slack cost. Re-run the arithmetic
above with the quad's own fixed cost and a fifth tile is still over
the line: 5 x 123,420 + 174,401 of shell for five CUs = 791,521,
90.9%. Four remains the wall. docs/LAYOUTS.md now derives every mix
the part could carry from measured bank costs, narrow tiles included.

*And later that evening the quad closed too: 9f73107 at 135 MHz,
kernel WNS +0.143 with 0 failing endpoints, the single at +0.618 -
docs/CARDDAY.md's primary pair.*

### What one tile retires, in cycles (measured 2026-09-02)

Until now every throughput figure here was calculated from the beat
geometry. `make cycles` (tb/test_krnl_cycles.py) measures it instead, on
the same `cft_krnl` the bitstream carries, by counting `run_busy` high
to low. It times TWO sizes per rung - 64 and 512 beats - and fits a
line, because a single size cannot tell a per-beat cost from a fixed
one: at 128 beats every rung reported the same 196 cycles, which looks
like 1.53 cycles/beat and is really about 36 cycles of fill and drain
plus a bit over one cycle a beat.

| rung | op | cyc @64 | cyc @512 | marginal cyc/beat | fixed | at 135 MHz |
|---|---|---|---|---|---|---|
| fp32 | fma | 116 | 676 | **1.250** | 36 | 864.0 Me/s |
| fp64 | fma | 116 | 676 | **1.250** | 36 | 432.0 Me/s |
| fp128 | fma | 116 | 676 | **1.250** | 36 | 216.0 Me/s |
| fp256 | fma | 116 | 676 | **1.250** | 36 | 108.0 Me/s |
| fp32 | sum | 923 | 6058 | **11.462** | 189 | 94.2 Me/s |

**The rung does not change the cycle count, which is the design working
as intended.** One 256-bit beat is the unit of work at every precision -
eight fp32 lanes or one fp256 - so the identical column is the fracture
paying off, and the element rate divides by the lane count rather than
the cycle cost rising.

**1.250, not 1.000, and the honest reading is that this is not purely
the datapath.** The compute pipe accepts a beat every cycle by
construction. What the bench measures is the whole kernel against
cocotbext-axi's `AxiRam`, so the extra quarter-cycle is the streaming
engine plus that memory model's response pattern - burst turnaround, AR
pipelining, page-boundary splits - and `AxiRam` is not HBM. Read 1.250
as an upper bound on cycles per beat under a plausible memory, not as a
property of the arithmetic, and note that hw_emu cannot settle it either
(its own banner warns that global memory and interconnect are
approximate models). The card settles it, under docs/CARDDAY.md gate 6.

**The fixed 36 cycles is the number the sequencer argument needs.** A
run pays it once, so it is invisible across 512 beats and dominant
across four. That is exactly why a short dependent chain issued as
thirty separate elementwise runs is overhead-bound, and why
docs/SEQUENCER.md wants the chain expressed as one program instead: the
same arithmetic, one fixed cost rather than thirty.

**The reduction is a different shape and costs like one.** 11.462
cycles a beat against 1.250 is the accumulator's serialised carries -
a level's result feeds the next, so the adder's latency is exposed
rather than hidden - and 189 cycles of fixed cost is the tree walk at
the end. It is the price of the contract's index-fixed ordering, which
is what makes a sum over four tiles equal a sum over one.

## What scales badly, in order of when it bites

**1. Control-plane round trips. This is the one that forces an
orchestrator.**

Every run costs roughly fifteen AXI-Lite transactions per compute
unit: MODE, N, four 64-bit pointers as eight 32-bit writes, ap_start,
poll ap_done, read FLAGS and STATUS. At four tiles that is about sixty
transactions and invisible. At sixty-four it is around 960, each of
order a microsecond, so **about a millisecond of pure control overhead
per run before any arithmetic happens**. Nothing about the data plane
is wrong at that point; the host simply cannot issue work fast enough
to keep the tiles busy.

**2. Per-CU AXI plumbing.** 24k LUT per tile - 20% of the pre-sequencer
tile, ~17% of the 139,404-LUT one, and either way as much as the entire
fp128 bank. Linear per tile, but the shell crossbar behind it grows
with port count and goes superlinear eventually. The four-master change
probably made this worse: out-of-context synthesis went from 95.5k LUT
(single master, 100 MHz) to 124.6k (four masters, 145 MHz), and not all
of that gap is the tighter clock. The quad gives the crossbar claim a
number: differencing the failed quad link above leaves ~161,775 LUT
outside the four kernels against the single tile's 123,897 shell, so
sixteen masters cost about 38k more of it than four do.

**3. Host-side reduction combine and flag aggregation.** Both O(tiles)
per call today. Fine at four, silly at sixty-four, and both want to be
hardware trees.

**4. Buffer staging.** `cft_run` stages operands into per-tile
buffers, so a call touches O(tiles) allocations and O(tiles) PCIe
transfers. Device-resident buffers (`cft_alloc`) already avoid the
per-call copy; at high tile counts they stop being an optimisation and
become the only workable path.

## What scales fine

- **Arithmetic.** Elementwise work is embarrassingly parallel and each
  tile is independent.
- **HBM bandwidth.** ~13.3 GB/s per tile against 316 GB/s available.
- **DSPs.** 292 per tile with the ladders off, 277 with them on, so
  four tiles are 1,168 or 1,108 of the part's 5,952 - **19.6% or
  18.6%**, up from 17.67% before the sequencer. Not a constraint on
  this part and it will not become one; `cft_seq` contributes none of
  them at all since its address arithmetic came off the DSP columns
  (15 -> 0), which is why area moved and this barely did.
- **Determinism.** Invariant by construction, as above.

## The orchestrator

Needed at **8-16 tiles**, triggered by control-plane cost rather than
by anything in the data path. Its job:

- take one logical operation and fan it across N tiles
- aggregate ap_done and the sticky FLAGS/STATUS words in hardware
- report once
- optionally hold a work queue so tiles pull rather than being pushed,
  which the determinism property above makes safe

**Most of this is already built.** The orbit sequencer
(docs/SEQUENCER.md) is a micro-sequencer running programs on-chip with
deposition addressed by index, and it is RTL now - `rtl/cft_seq.sv`,
benched bit-exact against `python/cft_golden/seq.py` and through
hw_emu at fp32 on the real XRT stack (2026-09-02), with fp64 and
wider, a bitstream and silicon still ahead of it. Its three determinism properties are argued
and tested, and P1 - "the sequencer introduces no arithmetic, only a
schedule" - stopped being an argument on 2026-09-01, when the private
second lane array went away: there is one `cft_lanes` per tile and the
sequencer issues into it, so P1 is a fact about the netlist. Adding a
fan-out dimension is a smaller step than designing an orchestrator from
nothing, and the P1/P2/P3 arguments carry over. Treat orchestrator and
sequencer as one component.

For the chiplet endgame the orchestrator is not optional: there is no
shared HBM, the pseudo-channel wall is replaced by ring bandwidth, and
no host bus reaches thirty-two chiplets' CSRs at usable latency. It
wants to be replicated per carrier rather than centralised.

## Assigning work by precision

Two things worth separating, because the project's homogeneous-tile
decision (docs/ROADMAP.md) is precisely what keeps them separate:

- **Homogeneous capability.** Every tile can do fp256. Settled. It is
  what makes precision a runtime choice rather than a deployment one.
- **Heterogeneous current assignment.** Tile 1 running fp32 while tile
  3 runs fp256, concurrently.

The second is **already possible in hardware and always has been**:
each CU has its own CSR, so each can hold a different MODE and be
started independently. libcft does not expose it because `cft_run`
partitions one logical operation across every tile. That is an API gap,
not an architecture gap - and it is a scheduling decision rather than a
bitstream decision only because capability is homogeneous.

*2026-09-02: the bitstream decision now has a catalogue. docs/LAYOUTS.md
derives every tile mix the U50 could carry - the homogeneous quad,
then one fp256 anchor with the rest of the ladder filled at each lower
rung, then the same pattern a rung down - from measured costs, with a
mark on the layouts that keep fp256 capability. The homogeneous
decision above is what that mark records; the narrow layouts give it
up deliberately, for the clock the widest rung no longer sets.*

## Designing for 64 now: what that means in practice

The number that has to scale to 64 today is **the test matrix, not the
netlist**. Building a 64-CU bitstream is not possible on any current
target and would not be useful if it were. But the property that must
hold - same bits at any tile count - is provable in software right now,
with no hardware in existence, and it is impossible to retrofit once
the abstraction has leaked. Discovering a 64-tile disagreement after
the fact leaves nothing to bisect.

Done:

- `cft_plan_slices` partitioning checked at **every tile count from 1
  to 64**, across 27 sizes and 4 element widths, asserting both that
  slices tile the range and that the padding total - and therefore the
  flag word - never depends on the tile count.
- Reduction `canonical_ranges`/`combine` checked at **1, 2, 4, 8, 16,
  32, 64** parts, three ways: the model's own partitioner in
  `python/tests`, the C partitioner's fold property against the whole
  array in `reduce-parts` (6,294 partitions), and the C partitioner
  against the model itself in `reduce_check.py` (2,100 partitions).

  That third one was missing until 2026-08-30 and its absence had
  hidden something. The two partitioners **do not always agree**, and
  both are right: the C one stops splitting when another pass would
  exceed its 64-range output cap, so at n=280 with 64 parts it returns
  32 eight-wide nodes followed by 24 singletons - a mixed depth that
  equals `canonical_ranges(280, p)` for no `p` at all. It is still a
  valid canonical partition and still folds to the same bits. 199 of
  the 2,100 cases differ this way.

  So the cross-check asserts the PROPERTY rather than equality: every
  range is a node of the tree over `[0, n)`, the ranges tile `[0, n)`
  in order, and the count fits the cap. Demanding equality would have
  failed 199 correct cases and taught us to weaken the test.

  Also worth knowing before sizing anything: **the range count is not
  bounded by the part count.** Cutting the top levels yields one extra
  range whenever n is a power of two plus a remainder, so four tiles
  get five ranges at n = 5, 9, 17, 33, 65, and eight tiles exceed eight
  for 49 of the first thousand n. A caller with one buffer per tile
  must run them in waves and re-stage between waves; doing that wrong
  is a silent wrong answer, not an error.
- `MAX_TILES` in the XRT backend raised 16 -> 64. CU discovery is a
  loop over names and tiles are a vector, so the number costs nothing;
  a limit that binds before the hardware does is one discovered on card
  day.

Deliberately not done:

- **Link configurations beyond 8.** `hw/link_quad.cfg` is generated
  rather than typed, and the generator extends to any power of two, but
  16 CUs do not fit and 16 x 4 masters exceeds the pseudo-channel
  budget. Generate 1, 2, 4, 8 when a part can hold them.
- **The orchestrator itself.** The gate on this was "design the
  interface when the sequencer RTL is designed", and as of 2026-09-01
  that has happened - so the interface is now designable and nobody has
  designed it. Build it when a device needs one. Speculating on the
  fan-out mechanism before first light is still how it gets built for
  the wrong bottleneck, and the area arithmetic above is a reason to
  wait rather than a reason to hurry: four tiles is what fits, and four
  tiles is what the host already drives without an orchestrator.
