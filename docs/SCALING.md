# Scaling

What gets harder as tile count rises, what does not, and where the
shape of the machine has to change. Numbers here are measured on the
U50 unless marked otherwise; the derivations are in the commit history
and the figures come from differencing routed builds.

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
| 8 | one bitstream, bigger part | LUTs, HBM pseudo-channels |
| 16-64 | many devices, or the chiplet ring | control plane, interconnect |

The break between 8 and 16 is not gradual. Below it you are placing
more compute units in one dynamic region; above it you are building a
different machine.

### What caps a monolithic tile at about eight

**HBM pseudo-channels, and the four-master engine made this tighter.**
The U50 exposes 32. Each tile now has four AXI masters - one per
operand stream plus the writer - and one pseudo-channel per master is
sufficient (about 9.9 GB/s available against a master's ~3.3 GB/s
demand at 130 MHz and 1.25 cycles/beat). Four per tile against 32 is a
**hard wall at eight tiles**. Raw bandwidth would not bind until
roughly 23 tiles, so this is an interface limit, not a throughput one.

**LUTs.** Shell 123,897 fixed; 119,543 per tile. Four tiles is 69.15%
of the device and the practical routing limit is around 85%, so the
U50 holds four comfortably and five uncomfortably. A VU47P or VU9P
roughly doubles that.

Those two numbers now sit close together, which is the useful summary:
on this generation, area and pseudo-channels run out at about the same
place, and it is around eight.

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

**2. Per-CU AXI plumbing.** 24k LUT per tile - 20% of a tile, as much
as the entire fp128 bank. Linear per tile, but the shell crossbar
behind it grows with port count and goes superlinear eventually. The
four-master change probably made this worse: out-of-context synthesis
went from 95.5k LUT (single master, 100 MHz) to 124.6k (four masters,
145 MHz), and not all of that gap is the tighter clock.

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
- **DSPs.** 17.67% at four tiles. Not a constraint on this part and it
  will not become one.
- **Determinism.** Invariant by construction, as above.

## The orchestrator

Needed at **8-16 tiles**, triggered by control-plane cost rather than
by anything in the data path. Its job:

- take one logical operation and fan it across N tiles
- aggregate ap_done and the sticky FLAGS/STATUS words in hardware
- report once
- optionally hold a work queue so tiles pull rather than being pushed,
  which the determinism property above makes safe

**Most of this is already being designed.** The orbit sequencer
(docs/SEQUENCER.md, v2) is a micro-sequencer running programs on-chip
with deposition addressed by index, and its three determinism
properties are already argued and tested. Adding a fan-out dimension to
it is a smaller step than designing an orchestrator from nothing, and
the P1/P2/P3 arguments carry over. Treat orchestrator and sequencer as
one component.

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
  failed 57 correct cases and taught us to weaken the test.

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
- **The orchestrator itself.** Design the interface when the sequencer
  RTL is designed; build it when a device needs it. Speculating on the
  fan-out mechanism before first light is how it gets built for the
  wrong bottleneck.
