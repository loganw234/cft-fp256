# Choosing a path: what to use when

One contract - the same bits, everywhere - reached through several
paths, and the paths differ only in where the time goes. This page is
the decision guide for a port: which call to use, when to move to the
next one, and what to expect at each step, in the card's own measured
numbers (docs/BENCHMARKS.md is the provenance; the API is
docs/HOSTAPI.md). Nothing here changes an answer. Every path below
returns the bits the golden model returns, which is the only reason
the choice can be made on speed alone.

## Building the library you are choosing a path in

Two build facts decide which of the paths below you can reach at all,
and both are easy to miss because neither produces an error where the
mistake is made. `make -C host` builds a **static** library, a
**shared** library (`libcft.so` / `libcft.dylib` / `cft.dll`) and the
tools; either is a complete library for the software and remote paths,
and the shared one is what a `ctypes` or `ccall` caller loads. But:

- **A default build has no device backend.** `XRT=1` compiles it in
  (`XRT_ROOT` defaults to `/opt/xilinx/xrt`); without it, `cft_open`
  on an artifact path returns `CFT_ERR_NO_DEVICE` rather than failing
  to build, so a port can be finished and correct and never touch the
  card.
- **An XRT build changes what linking against `libcft.a` costs.**
  `-L$(XRT_ROOT)/lib -lxrt_coreutil -lstdc++ -lpthread -luuid`, or the
  link ends in undefined references to `xrt::bo`. And the archive is
  not position-independent, so it cannot be linked into a shared
  object of your own - link the shared library this same `make` built.

docs/HOSTAPI.md, "The device backend", has both in full.

## The paths, and what bounds each

| path | the call | what moves per call | what bounds it | one tile, fp64 fma, measured |
|---|---|---|---|---|
| **Staged** | `cft_run` on host pointers | three operands in, one result out, across PCIe, every call | the bus: 2.3 to 3.3 GB/s of staged traffic | 76 to 89 M elements/s |
| **Resident** | `cft_run` on `cft_alloc` buffers, published once | nothing, after the first use | the engine's read path: 107 M beats/s a tile since the read-ahead | 413 M elements/s |
| **Programs** | `cft_program_run_ex` on an image | the per-sample inputs and the deposits; the bank and the scratch block if the program declares them | the instruction rate per lane block; the link hardly figures | hundreds of instructions per element on the tile |
| **Reductions** | `cft_reduce` | the array in, one element out | the bus in, nothing out; the tree order is fixed, so four tiles return one tile's bits | as staged for the input |
| **Remote** | `cft_open("cft://host:port")`, `ws://` from a browser | every operand as bytes over the socket, every call | the socket; no resident copies on the far side | the network's number |
| **Software** | `cft_open(NULL)`, or the WebAssembly module | nothing | one core | 3.2 M elements/s |

Two facts shape everything below. The engine is **format-blind**: a
tile moves about 107 million beats a second whatever the width, so a
wider format costs exactly its width. And the staged path is
**bus-bound at every format and tile count**, which is why four tiles
barely move a staged number and quadruple a resident one.

## When to move from one path to the next

**Start staged.** `cft_run` on ordinary pointers is the port a first
afternoon gets and it is correct on every backend. Batch calls to a
million elements or more; the library's per-call cost is a few tens of
microseconds and a run of a million fp64 elements is two and a half
milliseconds on the engine, so short calls are mostly overhead.

**Go resident when the operands outlive one call.** The signs: the
same arrays run through more than one operation; a result feeds the
next call; an iteration updates arrays in place. Four lines change
(docs/HOSTAPI.md, "Device-resident buffers"): `cft_alloc` instead of
`malloc`, fill through `cft_buffer_data`, `cft_buffer_to_device` once,
`cft_buffer_from_device` before reading a result. On the software and
remote backends those four are an allocation and two no-ops, so the
program stays one program. What you get is the engine's rate - three
to five times the staged one on a single tile, and four times that on
four tiles - and a result buffer that stays on the device for the next
call. `cft_get_caps` says whether a device does this
(`buffers_resident`), and `cft_buffer_get_info` says what happened to
one buffer if a number looks wrong.

**Go to a program when there is arithmetic per element to spend.** If
each element takes tens of operations - an iteration, a polynomial, a
formula with a dozen terms - the sequencer runs them on the tile and
the link carries the inputs once and the deposits out. The break-even
is a few instructions per element on PCIe and it rises with the link
(the table below); the workloads this tile was built for sit
hundreds to thousands of instructions per element above it. Programs
are files (docs/PROGRAMS.md): a text form, an assembler, a runner, a
library with a check per program. Parameters that change per run ride
as a bank; state that must survive a call rides through the scratch
block, in and out (docs/SEQUENCER.md, R3 and R5).

**Reduce on the card when the answer is small.** `cft_reduce` returns
one element from an array over a tree whose order is fixed by the
element index, so the sum over four tiles is the sum over one, bit for
bit. The array crosses the bus once (or not at all, resident); the
answer is one element.

**Go remote when the card is elsewhere.** A Linux box holds the card
and the client is Windows, a browser or another machine: `cft-serve`
puts a device behind a socket and `cft_open` takes its address
(docs/REMOTE.md). Everything crosses as bytes, every call, and there
are no resident copies on the far side - so this is the path for
programs and for latency-tolerant batches, not for the streaming
rate.

**Use the software backend for everything that is not speed.** It is
the same bits; it is what the card is checked against; it runs in a
browser. Develop, test and verify there, then point `cft_open` at an
artifact.

## When the link is the wall

Every host link is slower than the engine, and the gap decides the
path. The engine wants about 13.5 GB/s a tile on resident data (four
streams at 107 M beats a second); the staged path on the U50's PCIe
Gen3 x16 delivers 2.3 to 3.3 GB/s through XRT's staging. The boards
docs/ROADMAP.md considers for the open-core port carry less:

| link | practical rate | the engine's appetite over it | break-even, fp64 instructions per element |
|---|---|---|---|
| PCIe Gen3 x16, staged through XRT (the U50 today) | 2.3 to 3.3 GB/s | 4 to 6x | about 4 |
| PCIe Gen2 x8 (a Kintex-7 carrier) | about 2.5 GB/s | about 5x | about 5 |
| 10 GbE (the carrier's SFP) | about 1.1 GB/s | about 12x | about 12 |
| gigabit Ethernet | about 0.1 GB/s | about 120x | about 120 |
| USB through an FT2232 (the conformance node) | 8 MB/s | about 1,700x | about 1,700 |

The break-even is the instruction count at which the tile's time per
element equals the link's: an fp64 element moved in and out is 32
bytes, the engine does an fp64 element-operation in about 2.4
nanoseconds (415 M elements a second on one tile), and the rest is
division. Below the break-even the link dominates and the answer is
resident data if the operands repeat, or accepting the bus if they do
not; above it a program on the tile wins whatever the link, and the
margin is the ratio. The atlas positives run hundreds of instructions
per sample at their shortest and the orbit and Collatz workloads tens
of thousands, so on a 10 GbE carrier the link disappears by one to two
orders of magnitude, and even the USB conformance node is adequate for
orbit-class programs. What no link improves is a plain elementwise
stream of fresh data: that is bus-bound on every board, the U50 mildest
among them, and the design's answer on a slow link is a program, not a
faster stream.

## When your own gather is the wall, which happens before the link does

**One part of this has an answer since 2026-09-12, and it is worth saying
which part.** If what you are broadcasting is ONE value over a batch - a
reference point against every pixel, a carry base, a coefficient - that is
not a gather and never was, and `cft_run_ex` with
`cft_elem_args.scalar_mask` now reads it once instead of making you fill
an array with copies. A stride of zero needs no index and no address
arithmetic, which is why it was the cheap one.

Everything below still stands. A genuine gather needs an index per
element, and a scatter needs that plus an ordering rule - a scatter-add
whose indices collide has an order, and this contract requires order fixed
by index rather than by arrival. Stride-0 is not a step toward either; it
is the case that turned out not to need them.


Everything above assumes a call's operands are already contiguous. When
they are not - when a step gathers scattered elements, computes, and
scatters the answer back - the cost that decides your rate is **the
number of calls, not the number of elements**, and that is a wall a
caller can hit at one tile with the link entirely idle.

The software backend charges per ELEMENT. A device charges per CALL:
the control-plane round trip is fixed, so a call of eight elements and
a call of eight thousand cost nearly the same. A pattern that is free
on the software backend can therefore dominate on a tile, and the
profile will not look like the bus.

Measured on an N-body integrator (IAS15, binary256, through the
program engine) whose force is computed over particle PAIRS and then
scattered back onto particles as one vector add per partner:

      share of wall clock in the scatter    software      card
      8 bodies                                  3.6%     20.9%
      32 bodies                                 6.3%     42.2%
      64 bodies                                 6.7%     36.0%

Six percent on a CPU and forty on the tile, for the same arithmetic.
At 64 bodies the scatter is 63 separate vector adds of 192 elements
each per force evaluation; the CPU sees 12,096 elements and shrugs,
the tile sees 63 round trips. Removing that cost - the same work
issued as one device-side scatter rather than 63 calls - would take
that workload from 1.99x the CPU to about 3.1x, so it is worth more
than every other optimisation tried on it. Two others were tried and
measured first: skipping a convergence test that accounted for 13 to
19 percent of all calls bought 4 to 9 percent, and the host memory
copies in the same routine were a red herring, being host work charged
equally to both sides.

**What to do about it.** Restructure so the scattered step is one call
rather than many: accumulate into a contiguous buffer and issue a
single wide operation, even if that means computing values you discard.
On a device, arithmetic on elements you do not need is usually cheaper
than a second call. Where the pattern cannot be flattened, that is the
honest limit of the current API, and it is a known gap rather than a
mystery - the device has no scatter-add and no gather primitive today.

**How to tell this is what you have.** Divide your wall clock by your
call count. If the quotient is flat as you widen the problem, you are
paying per call and the fix is fewer, wider calls. If it falls, you are
paying per element and the fix is a faster path (resident, programs).

## The numbers, in one place

`fma`, one million elements a call, elements per second, measured on
the Alveo U50 at 135 MHz (docs/BENCHMARKS.md has the dates, images and
provenance for each column):

| format | software, one core | staged, one tile | resident, one tile (revision 3) | resident, one tile (read-ahead) | resident, four tiles (revision 3) | resident, four tiles (read-ahead) |
|---|---|---|---|---|---|---|
| fp32 | 3.76 M | 141.8 to 165.6 M | 462.6 M | 804.7 M | 1,833.9 M | 3,219.6 M |
| fp64 | 3.24 M | 81.4 to 89.2 M | 235.1 M | 415.9 M | 937.2 M | 1,664.3 M |
| fp128 | 2.52 M | 40.3 to 44.2 M | 118.7 M | 211.5 M | 474.0 M | 845.5 M |
| fp256 | 1.74 M | 20.0 to 22.0 M | 59.6 M | 106.8 M | 238.4 M | 427.3 M |

Through the library rather than the standalone tool, the resident
column is within 1.5 percent on one tile and two to fifteen percent
under on four. A resident run carries a fixed cost of about 35
microseconds, so the rate above is reached at a hundred thousand
elements and up.

## Before running anything

Ask, do not guess. `cft_get_caps` publishes what a device enforces:
the formats and opcode groups, the sequencer's capacities (deposit
slots a lane, instructions, constants, scratch slots), its feature
bits, and whether buffers can be resident. `cft_supports` answers for
one operation and format. `cft_program_load` refuses an image that
needs what a device lacks, by name, before the register map is
touched. A tool that reads the capabilities sizes its work to fit; a
tool that does not discovers the limits as a status bit on card day.

## What this page does not promise

- The remote backend has no resident path; a client that needs the
  engine's streaming rate sits on the card's host.
- The bank and the scratch block of a program run are per-run data
  and travel with the run; they are small by design.
- Both four-tile columns above are measured: the revision-3 quad on
  2026-09-08 into 09-09 and the read-ahead quad on 2026-09-09, each
  unit at the single tile's rate (docs/BENCHMARKS.md).
- Every rate on this page is a bus-bound or engine-bound number on one
  card, one shell and one clock; the open-core boards have their own
  clocks and their own links, and docs/SCALING.md is where the
  projections live, labelled as projections.
