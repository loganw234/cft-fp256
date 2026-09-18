# Benchmarks: measured, in software and on the card

This file holds the project's measured performance numbers: libcft's
software backend against the libraries a prospective user could
already run, and - since 2026-09-08 - the Alveo U50 itself.

- The hardware numbers were measured under docs/CARDDAY.md's step 6
  ("Throughput. Now, and not before, measure."), on the day the first
  card came up, and they measure `cft_run`: the path a first port
  gets, which stages every operand across PCIe on each call. That is
  the honest default and it is bus-bound, as the section below shows.
  The pipeline's own rate was measured the next morning, 2026-09-09,
  with `cft-resident` - device-resident buffers filled once and the
  kernel run on them back to back - and "The engine, measured" below
  says what it is and what bounds it now. The projection in
  docs/SCALING.md (`make cycles` measures 1.250 cycles per beat
  marginal and 36 fixed on the RTL; cycles x period is the
  prediction) stays labelled as a projection, and the measured
  number is where it meets HBM: 2.25 cycles a beat, for a reason
  that section names.
- Emulation produces no throughput numbers at all. hw_emu is an RTL
  simulation running many orders of magnitude below fabric speed; its
  wall clock measures the simulator. (Its cycle counts are real, and
  cycles x period is a prediction - but a prediction still belongs on
  the other side of the measured/projected line.)

Correctness is a different file: docs/VALIDATION.md owns the oracle
campaigns. The agreement column below is a harness check, not a
validation claim.

## Provenance

Measured 2026-09-01, single-threaded, on a quiet machine:

| what | value |
|---|---|
| CPU | Intel Core i5-12400F (Alder Lake, 6 P-cores; base 2.5 GHz, single-core turbo ~4.4 GHz) |
| environment | the repo's own sim container (docker/Dockerfile.sim: Ubuntu 24.04, gcc 13.3.0), pinned to one core with `taskset -c` |
| libcft | `-O2`, plain C99, the software backend (`cft_open(NULL, ...)`) |
| MPFR / GMP | 4.2.2 / 6.3.0, the pinned oracle prefix from verify/build-mpfr-oracle.sh; both upstream test suites ran green on this machine before use |
| __float128 | gcc 13.3.0's libgcc soft-float + libquadmath (`fmaq`, `sqrtq`) |
| cpu-hw | the CPU's own float/double, `-O2 -fno-math-errno`, glibc `fma`/`fmaf` |
| mpmath | 1.4.1, pure-Python backend, CPython 3.12 |

Tools: host/tools/cft_bench.c (internal), host/tools/cft_bench_peers.c
(cross-library; its header defines every row), host/tools/bench_mpmath.py
(Python context). Reproduce with:

    bash verify/build-mpfr-oracle.sh       # once; PREFIX=... to relocate
    make -C host cft-bench
    make -C host cft-bench-peers CFLAGS="-O2 -I$PREFIX/include" \
                                 LDLIBS="-L$PREFIX/lib"
    ./host/cft-bench
    ./host/cft-bench-peers
    python3 host/tools/bench_mpmath.py

Operands are seeded and identical on every run and every platform:
normal numbers, full random significand, exponent within +/-8 of the
bias - the fast-path cost of a realistic element (the generator and
the reasoning are in cft_bench.c). Every measurement auto-repeats to
at least 0.35 s. Cells still wobble a few percent between runs; read
the ratios, not the third digit.

## The card, measured (2026-09-08)

Provenance: amd-arc-box (Gigabyte GA-X99-UD4, Xeon E5-2697 v4,
Ubuntu 24.04, kernel 6.8.0-139, XRT 2.19.194, shell
`xilinx_u50_gen3x16_xdma_base_5`, Gen3 x16 at full width); the
card-day pair from ed752dd at 135 MHz (single sha256 3870fc43...,
quad 496f8ac0...); `cft-bench -n 1048576 -t 1 --csv`, the software
backend single-threaded on the same box first, then each image. The
day's correctness record is docs/VALIDATION.md's card-day entry: the
same images matched every published case, 1,071,635 through one tile
and through four, before any of this was measured.

`fma`, one million elements a call, elements per second:

| format | software, one thread | single tile | four tiles |
|---|---|---|---|
| fp32 | 3.76 M (266 ns) | **141.8 M** (7.05 ns), 38x | **175.2 M** (5.71 ns), 47x |
| fp64 | 3.24 M (309 ns) | **81.4 M** (12.3 ns), 25x | **75.5 M** (13.2 ns), 23x |
| fp128 | 2.52 M (396 ns) | **40.3 M** (24.8 ns), 16x | **38.1 M** (26.3 ns), 15x |
| fp256 | 1.74 M (575 ns) | **20.0 M** (50.0 ns), 11.5x | **25.9 M** (38.6 ns), 15x |

`mul` and `add` sit within two percent of `fma` on the device at every
format, and `abs` within one: the arithmetic is not what sets the
time. Read the bench's `mb_per_s` column instead - every device row,
every format, both tile counts, lands between 2.3 and 3.3 GB/s of
staged traffic. That is the PCIe round trip of `cft_run`: three
operand buffers in and one result out, per call, through XRT's
host-memory staging. Against it the tile's own work is small - a
million fp256 elements is about 9 ms of pipeline at 108 M beats/s, and
the measured call takes 50 - so four tiles cannot show: they finish
the same bus transfer with the same bus. The speed-ups above are real
and they are the bus's, which is exactly what the bench's header said
they would be.

The revision-3 pair, measured the same way the next night, lands in
the same band - its numbers within the run-to-run spread of a
bus-bound measurement, the single's taken beside a Vivado route on
the same host - which is what a change confined to the sequencer
must do to the elementwise path (docs/VALIDATION.md, the revision-3
integrator's entry has the rows; the revision-2 pair was never
benched).

What the design rate looks like when the bus is taken out of the
measurement is the next section, measured the morning after the
revision-3 pair was built.

**The soak, the same day**, is the measurement that matters for the
contract rather than for speed: on each image, five repetitions of the
full device-test matrix agreed with the first; the published sets ran
a second time, all matching; and the sequencer's reference orbit to
2,000 iterations, deposited 32 steps a call, produced one checkpoint
hash in ten runs on one tile, ten on four, and one on the software
backend - the same bytes everywhere, which is the claim.

## The engine, measured (2026-09-09)

`host/tools/cft_resident.cpp` (`make -C host XRT=1 cft-resident`, which
builds `host/cft-resident`; XRT-only,
C++ because XRT's API is) takes the bus out: each compute unit's four
buffers are filled once, then the kernel runs on them back to back
and only the runs are timed. It is not only a stopwatch. Every unit
gets the same operands, and after the timed runs the result is held
to the software backend, to every other unit and to one more run,
with STATUS read back - so the rate comes with the correctness check
the staged numbers could not make, at the rate where the engine's
flow control and its four masters are doing what a cocotb memory
model only stood in for. Provenance: the revision-3 pair from main
99d2700 (single `f9a48201...`, quad `af26a699...`), amd-arc-box, the
morning after they were built; every row's status clean, every row's
bytes identical on every unit, on repeat and in software, the flags
the same word (inexact) on both sides.

`fma`, one million elements a run, twenty timed runs after a warm-up;
`add` and `mul` within half a percent of every row:

| format | one tile, resident | four tiles at once | one tile, staged (card day) | software, one thread |
|---|---|---|---|---|
| fp32 | **462.6 M/s** (2.16 ns) | **1,833.9 M/s** (0.545 ns) | 141.8 M/s | 3.76 M/s |
| fp64 | **235.1 M/s** (4.25 ns) | **937.2 M/s** (1.07 ns) | 81.4 M/s | 3.24 M/s |
| fp128 | **118.7 M/s** (8.43 ns) | **474.0 M/s** (2.11 ns) | 40.3 M/s | 2.52 M/s |
| fp256 | **59.6 M/s** (16.8 ns) | **238.4 M/s** (4.20 ns) | 20.0 M/s | 1.74 M/s |

Three things the table says. **The engine is format-blind**: one
tile moves 57.8 to 59.7 million beats a second whatever the width,
7.4 to 7.6 GB/s over its four streams, so a wider format costs
exactly its width and nothing more, which is what a beat-wide
datapath promises and the staged numbers could not show. **Four
tiles are four times one**: 29.3 to 30.5 GB/s in all, each unit at
the rate it has alone and byte-identical to the others, because
hw/link_quad.cfg gives each its own HBM group; nothing shared is in
the way at four, and docs/SCALING.md's crossbar question starts
above that. And **the bus was hiding a factor of three**: resident
against staged is 3.0x to 3.3x at every format, and 123x to 34x one
core of the host.

**What bounds it now is not the pipeline.** `make cycles` measures
1.250 cycles a beat marginal on the RTL, which at 135 MHz is 108 M
beats a second; the card sustains 59 to 60, which is 2.25 cycles a
beat, at every format and at n = 65,536 and n = 4,194,304 alike (the
small size shows a fixed cost of about 35 microseconds a run and
nothing else). A ceiling flat across format and size, well under
both the masters' own limit (135 M beats a second each at the kernel
clock) and the channels' (docs/SCALING.md), is the signature of a
read path bounded by latency: the streaming engine keeps only so
many bytes in flight per stream, and against the real controller's
round trip, that many bytes a round trip IS the rate. The cocotb
model answered faster than HBM does - exactly the disagreement
docs/CARDDAY.md's step 6 said a real controller was entitled to. The
remedy is a deeper read-ahead in `cft_engine_stream`, more
outstanding bursts per master, and it is an RTL item with a measured
target: 108 M beats a second, 1.8x what the card does today.

**What a port gets, since ABI 0.11 the same day.** `cft_alloc` is
real on the XRT backend now (docs/HOSTAPI.md, "Device-resident
buffers"): allocate, fill through `cft_buffer_data`, call
`cft_buffer_to_device` once, run as many times as you like, call
`cft_buffer_from_device` before reading a result - the same four calls
that are an allocation and two no-ops on the software and remote
backends, so there is no second code path. `cft-bench --resident`
measures exactly that through `cft_run`, on the revision-3 pair,
`fma`, one million elements a call:

| format | one tile, `cft_run` staged | one tile, `cft_run` resident | one tile, the standalone tool | four tiles resident | four tiles, the tool |
|---|---|---|---|---|---|
| fp32 | 141.6 M/s | **453.7 M/s** | 460.4 M/s | **1,570 M/s** | 1,844 M/s |
| fp64 | 76.4 M/s | **233.0 M/s** | 234.5 M/s | **898 M/s** | 937 M/s |
| fp128 | 38.0 M/s | **118.3 M/s** | 118.5 M/s | **466 M/s** | 474 M/s |
| fp256 | 19.1 M/s | **59.6 M/s** | 59.6 M/s | **234 M/s** | 238 M/s |

The library is within 1.5 percent of the tool on one tile and two to
fifteen percent under it on four, the gap being its per-call
bookkeeping across four tiles at the shortest runs; `device-test -b`
holds every byte and flag of the resident path to the staged one on
the card (4,363 checks, both images). Staged stays the default a
first port gets, and it is the honest one for a call whose operands
change every time.

**The read-ahead, measured the same morning.** A pair built from the
deeper read-ahead (docs/ARCHITECTURE.md, the engine's in-flight depth;
docs/VALIDATION.md's read-ahead entries) moves the ceiling: one tile
sustains **100.6 to 106.8 M beats a second** - 804.7 / 415.9 / 211.5 /
106.8 M fma elements a second at fp32/64/128/256, 12.9 to 13.7 GB/s -
against 59 before it, 1.8x, and 84 to 89 percent of the 120 the model
predicted; through `cft-bench --resident` 785.3 / 412.6 / 210.1 /
106.7. The staged path rose about fifteen percent with it (165.6 /
89.2 / 44.2 / 22.0), the writer no longer waiting on every write
response. What remains between 107 and the pipeline's 120 rises with
the format where revision 3's ceiling was flat, which names a
per-beat cost rather than latency; the latency bench's next
refinement is a bandwidth-limited slave. Four tiles at once: 3,219.6
/ 1,664.3 / 845.5 / 427.3 M fma elements a second, 51 to 55 GB/s,
each unit at the single's rate. **Power**, from the card's own
rails: 14.9 W with an image loaded and the tiles idle, 18.5 W with
one tile streaming fp256, 34.8 W with four - about 3.5 W of core
power a tile at full rate, on a 75 W card; the read-ahead pair's
entry in docs/VALIDATION.md has the rails and the per-joule
arithmetic.

## Width inside the library

`cft-bench`, software backend, ns per element:

| op | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| fma | 255.8 | 234.7 | 285.5 | 400.7 |
| mul | 196.2 | 197.4 | 240.6 | 355.3 |
| add | 250.3 | 259.0 | 477.4 | 469.6 |
| abs | 26.1 | 34.7 | 56.7 | 100.2 |

The number worth staring at is the FMA column read downward: **fp256
costs 1.6x fp32** for eight times the width. The software backend's
per-element price is almost entirely the structural path - decode,
align, normalise, round, one function call's worth of dispatch - and
almost none of it is limb arithmetic. Width is nearly free in this
implementation; that is a property of writing the softfloat as one
parameterized path rather than four tuned ones, and it is the same
property the RTL has (one parameterized core serving all four rungs).

## Against the peers

`cft-bench-peers`, ns per element, round-to-nearest-even. Every
non-libcft row also states agreement: for this operand stream, every
implementation below produced **bit-identical results to libcft on
every element** - 4096/4096, all ops, all formats, including glibc's
`fma`/`fmaf` and libquadmath's `fmaq`. A row's timing is therefore a
timing of the same work. (`mpfr` = matched precision, MPFR's own
default exponent range; `mpfr+754` = MPFR emulating the binary format
per its manual's recipe - exponent range narrowed, `mpfr_check_range`
+ `mpfr_subnormalize` on every result. libcft is timed through its
batch calls, the peers through per-element calls, because that is how
each is actually used; call shape is part of the price.)

**fp32** (cpu-hw = the CPU's own `float`):

| op | libcft | mpfr | mpfr+754 | cpu-hw |
|---|---|---|---|---|
| add | 282.2 | 14.6 | 20.9 | 0.32 |
| mul | 199.9 | 8.1 | 16.4 | 0.29 |
| fma | 241.5 | 32.8 | 36.7 | 0.84 |
| div | 3789.7 | 12.7 | 19.4 | 0.72 |
| sqrt | 4420.5 | 12.1 | 23.3 | 0.82 |

**fp64** (cpu-hw = `double`):

| op | libcft | mpfr | mpfr+754 | cpu-hw |
|---|---|---|---|---|
| add | 309.8 | 16.0 | 22.2 | 0.53 |
| mul | 206.1 | 8.5 | 16.3 | 0.39 |
| fma | 316.3 | 36.3 | 37.7 | 0.97 |
| div | 4468.0 | 12.4 | 19.0 | 1.08 |
| sqrt | 5638.2 | 15.8 | 23.3 | 1.70 |

**fp128** (quadmath = gcc `__float128`):

| op | libcft | mpfr | mpfr+754 | quadmath |
|---|---|---|---|---|
| add | 344.9 | 15.6 | 21.6 | 15.6 |
| mul | 243.5 | 13.7 | 21.1 | 15.4 |
| fma | 394.5 | 55.8 | 62.9 | 811.3 |
| div | 6678.4 | 25.1 | 32.5 | 21.9 |
| sqrt | 8018.5 | 34.9 | 38.4 | 465.8 |

**fp256** (no other implementation of binary256 to hand):

| op | libcft | mpfr | mpfr+754 |
|---|---|---|---|
| add | 488.3 | 25.4 | 29.9 |
| mul | 332.5 | 36.1 | 39.2 |
| fma | 448.3 | 65.0 | 71.0 |
| div | 11563.1 | 85.3 | 86.4 |
| sqrt | 12704.3 | 140.2 | 139.7 |

Python context, from bench_mpmath.py (mpmath 1.4.1, pure-Python
backend; no shared operand stream, no bit-agreement check - comparable
in shape, not rigor; mpmath has no fma):

| op | fp32-equiv | fp64-equiv | fp128-equiv | fp256-equiv |
|---|---|---|---|---|
| add | 1559 | 2265 | 1479 | 1630 |
| mul | 1444 | 1666 | 1465 | 1579 |
| div | 1592 | 1696 | 1843 | 2162 |
| sqrt | 2545 | 2853 | 3189 | 4160 |

## Across problem size, and on a second architecture (2026-09-13)

The tables above are one element count on one machine, which answers
"how fast" and not "from what size, on whose hardware". This run
answers both: `hw/bench-sweep.sh` over the device and the softfloat
backend, and `cft-bench-peers` over a ladder of powers of four from 1
to 4,194,304, on **x86-64** (amd-arc-box, U50 at 135 MHz) and on an
**M2 Pro MacBook Pro**. 14,715 rows, 988 crossings.

The peers ladder uses powers of four and the device sweep powers of
two, so the two meet on the powers of four; a crossing is only ever
computed at an element count present in both. Each format is reported
at the largest such point it has - binary256 stops at 1,048,576
because a deposit window outgrows its HBM group before the others do.

**Multiply, ns per element, at the top of each format's shared ladder:**

| format | n | best software, x86-64 | best software, arm64 | 1 tile resident | 4 tiles resident | 1 tile over PCIe |
|---|---|---|---|---|---|---|
| fp32 | 4,194,304 | `cpu-hw` 0.72 | `cpu-hw` 0.16 | 1.185 | 0.322 | 5.74 |
| fp64 | 4,194,304 | `cpu-hw` 2.10 | `cpu-hw` 0.33 | 2.342 | 0.609 | 11.77 |
| fp128 | 4,194,304 | `quadmath` 20.79 | `mpfr` 12.85 | 4.657 | 1.187 | 22.63 |
| fp256 | 1,048,576 | `mpfr` 51.38 | `mpfr` 37.21 | 9.361 | 2.438 | 44.80 |

**libcft's own softfloat is not in that table on purpose.** It defines
the contract; MPFR beats it by 6-19x on add/mul/fma and by 94-316x on
div/sqrt (measured, n=65,536, all four formats), so a speedup measured
against it is a statement about our reference implementation rather
than about the card. It is still plotted, faint, in the README charts.

Four things this run establishes that the single-point tables could
not:

**1. The tile is beat-limited, and the measurement says so.** One
element costs it exactly the format's width in beats: 1.185, 2.342,
4.657, 9.361 ns is a doubling per rung, off exact by 1.18%, 0.58% and
0.50%. Software does not double - it climbs far more slowly - which is
the whole reason the answer inverts between binary64 and binary128
rather than anywhere else.

**2. `__float128` has a 39x cliff on fma.** `quadmath` multiplies in
20.8 ns and fuses in **817 ns**, flat at every n from 1 to 4,194,304 -
10 to 19 times slower than MPFR's fma, which is not a cache effect but
a soft routine. A binary128 program that reaches for `fmaq` is paying
forty multiplies for it. (The 811.3 ns in the table above, measured
independently at n=4096, is the same number.)

**3. Apple Silicon has no binary128 at all.** `cft-bench-peers` emits
15 rows a point there against x86-64's 20: `__float128` is absent, and
`long double` is 64-bit. At binary128 MPFR is not the best alternative
on that machine - it is the only one.

**4. The CPU's own FPU falls off a cache cliff and the card does
not.** `cpu-hw` at fp64 holds between 0.49 and 0.88 ns a element from
n=64 all the way to n=1,048,576, then jumps to **2.10 ns at
n=4,194,304** - a 2.4x step in one rung, where 32 MB of doubles stops
fitting L3. The tile streams from HBM at a fixed rate and is flat
across the same range. So the margin four tiles hold at fp64 is partly
the host's memory system, not arithmetic, and it would shrink on a
machine with more cache.

The crossings themselves, with the bracket each was interpolated from,
are in `docs/bench/tipping-points.json`. Raw sweeps and peer runs
for both machines are beside it, and `python/readme_charts.py`
regenerates the two README charts from exactly those files.

## Round 2 on the card (2026-09-15)

The parcel round that built the gather, the lane mask and the beat-wide
accumulator (docs/ROUND2.md) was measured on the round-2 single tile
the night it landed, with the tools that measure it checked into
`host/tools/` so the numbers regenerate: `gathertime.py` (the gravity
accumulate as one indexed program run against the dense calls it
replaces, checked against a host fold first) and the seq6 day's
`segtime.py` (a thousand segmented reductions in one call against a
thousand calls). Every figure is a median of five, and the full tables
with the two host defects the day found are docs/VALIDATION.md's
"round 2's card day, second half".

| what | one run | the calls it replaces | ratio |
|---|---|---|---|
| gather, 64 bodies fp64 (192 lanes, rows of 63) | 4.052 ms, 335 ns a gathered element | 63 dense calls | x3.25 |
| gather, 128 bodies fp64 (384 lanes, rows of 127) | 15.588 ms, 320 ns an element | 127 calls, 26.729 ms | x1.71 |
| gather, 128 bodies fp32 / fp128 | 15.113 / 16.464 ms, 310 / 338 ns | 24.725 / 24.894 ms | x1.64 / x1.51 |
| the same run, every third lane masked | x1.013 of the unmasked run at every format | one beat read a block | |
| `cft_reduce_seg` sum, fp64, 1,000 segments of 192 | 2,351 us | 1,000 calls, 91,108 us | x38.8 |
| the same at fp128 / fp32 | 3,863 / 1,739 us | 86,042 / 84,410 us | x22.3 / x48.5 |
| the same at 64 segments, fp64 | 220.5 us | 5,808 us | x26.3 |

**Four tiles, resident, on the same pair** (2026-09-16, `cft-resident`
fma, ten timed reps; docs/VALIDATION.md "saturating the pair" has the
library-path and reduction tables beside it):

| n | fp32 | fp64 | fp128 | fp256 | beats/s a unit |
|---|---|---|---|---|---|
| 1M, one tile | 812 M/s | 417 M/s | 212 M/s | 107 M/s | 101-107 M |
| 1M, four tiles | 3,187 M/s | 1,665 M/s | 846 M/s | 427 M/s | 100-107 M |
| 16M, one tile | 859 M/s | 431 M/s | 216 M/s | no channel | 107-108 M |
| 16M, four tiles | 3,432 M/s | 1,722 M/s | 863 M/s | no channel | 107-108 M |

Four times one at every format and size, 55 GB/s over sixteen streams;
each unit moves the read-ahead pair's 107 M beats a second, twice the
revision-3 rate the engine table above records. Through the library
(`cft-bench --resident`) the four-tile cost is a fixed cost a call: a
fifth of the rate at a million fp32 elements, under three percent at
sixteen million, under five percent at fp256 from a million up.

Two readings the ratios carry. A gathered element costs one HBM round
trip whatever the format - 310 to 340 ns - because the sequencer keeps
one burst in flight, so the gather's win over dense calls is the call
count and the host gathers removed, not bandwidth; and the mask buys
bytes and flags, never compute, at about one percent of a run. The
segmented reduction's ratio is the per-call round trip against a
per-segment flush, which is why it grows with the segment count.

### A real workload's programs on the pair (atlas-engine, 2026-09-17)

The first programs from outside this project to run on revision-6
silicon: atlas-engine's shape functions lowered to sequencer programs,
binary32, timed through libcft with the run alone on the clock and
every deposit buffer checked (their `docs/CFT-SILICON.md`; the handoff
is recorded in docs/VALIDATION.md, 2026-09-18). One tile; the quad ran
every one of them at the single's rate to the hundredth, because a
program run is one tile's.

| program | instructions | per lane | lanes a second |
|---|---|---|---|
| `psf` | 185 | 0.27 us | 3.75 M |
| `hopf` | 638 | 0.72 us | 1.39 M |
| `mand` | 1,111 | 3.00 us | 334 k |
| `jong` | 737 | 3.96 us | 252 k |
| `starfield` | 5,475 | 5.85 us | 171 k |
| `throughput`, 2,183 scratch accesses | 14,801 | 24.98 us | 40 k |
| `stdmap` | 912 | 95.4 us | 10.5 k |
| `nested` | 1,401 | 171 us | 5.8 k |
| `threebody`, one loop of 2,560 trips | 2,029 | 3,286 us | 304 |

And what one instruction costs by kind, from five programs that differ
only in the pair inside one `repeat 1024` (16,384 lanes; per lane for
the whole program):

| 1,024 trips of | one tile | software, one core |
|---|---|---|
| one arithmetic instruction | 1.24 us | 14.77 us |
| two arithmetic instructions | 2.24 us | 29.23 us |
| `stl` and `ldl`, one slot | 8.18 us | 16.08 us |
| `stx` and `ldx` | 8.41 us | 23.34 us |
| one arithmetic and a `setact` | 5.38 us | 24.76 us |

So an arithmetic instruction is 0.98 ns a lane on the tile and every
control code about 4 ns - the drain docs/SEQUENCER.md R12 describes -
while on a host a scratch access is the CHEAP instruction. The tile is
twelve to thirteen times one core on arithmetic and two to three times
on a spill, and a program's shape decides which it sees.

**A compiler that knows the prices** (atlas-engine, 2026-09-18, the
same tile and the same input streams). Their lowering now charges a
scratch access or a `SETACT` four arithmetic instructions when it
chooses, coalesces a loop's copy-backs and hoists every per-run value
into the bank. The deposits are unchanged, bit for bit, and the
programs are shorter and faster:

| program | instructions | per lane | against the first lowering |
|---|---|---|---|
| `psf` | 185 to 118 | 0.27 to 0.20 us | x1.34 |
| `hopf` | 638 to 526 | 0.72 to 0.61 us | x1.19 |
| `mand` | 1,111 to 832 | 3.00 to 2.59 us | x1.16 |
| `jong` | 737 to 508 | 3.97 to 3.70 us | x1.07 |
| `starfield` | 5,475 to 4,483 | 5.86 to 4.72 us | x1.24 |
| `throughput` | 14,801 to 11,356 | 24.98 to 15.42 us | x1.62 |
| `stdmap` | 912 to 733 | 95.45 to 81.35 us | x1.17 |
| `nested` | 1,401 to 1,055 | 171.4 to 147.2 us | x1.16 |
| `threebody` | 2,029 to 1,754 | 3,286 to 2,617 us | x1.26 |
| `rule30`, 4,096 lanes | 4,720 to 3,671 | 9,438 to 5,103 us | x1.85 |

That is what R12's drain is worth to a workload that can route around
it, from the software side alone; docs/ROADMAP.md's revision-7 item is
the same saving taken in the tile, for every workload.

**The photograph** (the same day): the darkroom's camera around a
plate, 1,048,576 samples a pass, five deposits a lane.

| | `hopf`, 1,081 instructions | `mand`, 1,272 with an early-exit loop |
|---|---|---|
| the U50's tile, a pass | 1.21 s, 1.15 us a lane | 3.17 s, 3.02 us a lane |
| this library on one desktop core, a pass | 88 s | 137 s |
| the GPU that made the record | the render call returned in 7 ms; reading back every sample's record took 0.60 s | 2 ms; 0.46 s |

Every one of them produced the same bytes. The tile is forty to seventy
times one core here and a GPU is far faster than either at binary32 -
which was never the tile's case: its case is the same guarantee at
binary128 and binary256, where a GPU has no answer at all.

### Reductions on resident memory, after the zeros stopped (2026-09-18)

Until this date both XRT reduction paths uploaded two operand-sized
buffers of zeros on every call, and every reduction time recorded
before it includes that. `host/tools/segsat.py`, one `cft_reduce_seg`
over resident operands, median of five, every result exact;
"before" is the same library with `CFT_XRT_REDUCE_BC=zero`:

| shape | one tile, before | one tile | four tiles, before | four tiles |
|---|---|---|---|---|
| fp64, one whole-array sum, 4M elements | 24.4 ms | **10.5 ms**, 401 M/s | 16.7 ms | **2.8 ms**, 1,516 M/s |
| fp32, one whole-array sum, 4M elements | 10.8 ms | **5.3 ms**, 789 M/s | 8.0 ms | **1.5 ms**, 2,875 M/s |
| fp64, segments of 192, about 8M elements | 95.5 ms | **58.6 ms** | 50.5 ms | **14.9 ms** |
| fp64, segments of 192, about 1M elements | 10.2 ms | **7.5 ms** | 5.4 ms | **2.0 ms** |
| fp256, segments of 192, about 1M elements | 39.9 ms | **23.5 ms** | 21.1 ms | **6.1 ms** |

A whole-array sum now runs at about 100 M beats a second a tile, the
engine's own rate, and four tiles are 3.6 to 3.8 times one. What is
left in the segmented rows is the tile's per-segment flush, about a
hundred cycles a segment.

## Workloads designed for the contract

The tables above adapt other libraries' benchmarks to this one. The
five tools below were written the other way round, on 2026-09-04, each
for a property the contract has and a conventional float library does
not: exact integers to 2^237 with the inexact flag as the proof, five
rounding attributes per instruction, correctly rounded results that
are the same bits on every host, and a sequencer that runs the inner
loop as a program. Each is a resumable C tool in `host/tools/` with a
Python oracle in `host/tests/`, a design note in `docs/`, and an entry
in docs/VALIDATION.md; each runs at fp64 beside fp256 and says what
fp64 loses, or that it loses nothing; each measures the software
backend today and takes `--artifact` for a device later. The numbers
are one thread on the Windows desktop, software backend, and they are
measurements of a slow backend, not a promise.

| tool | the workload | what the contract supplies | software backend, fp256 | fp64 beside it |
|---|---|---|---|---|
| `cft-collatz` (docs/COLLATZ.md) | Collatz trajectories, sweep and deep | exact integers below 2^237, the inexact flag as the certificate, the sequencer's escape loop | 587,571 steps/s as a program, 277,210 as a host loop; 10^6 starting values verified in 231 s with 123 library calls | the same chain at fp64 and fp128; fp32 loses 87 of 100,000 to exactness. 2^237 - 1315 verified in 2,437 exact steps |
| `cft-enclose` (docs/ENCLOSE.md) | rigorous enclosures: a series, dot products, interval Horner | roundDown and roundUp per instruction, the reductions' fixed tree, bit-identical bounds | 1,821 enclosures/s; interval Horner 48,502/s as a program against 34,505 as a loop | 14 of 15 ill-conditioned fp64 enclosures straddle zero, 0 of 15 at fp256; on well-conditioned kernels fp64 is fine at 6.4x the rate |
| `cft-mersenne` (docs/MERSENNE.md) | Lucas-Lehmer over the known Mersenne primes | fp256 as an exact 59-bit-limb multiplier, dot reductions as exact convolutions, flags as the certificate | 270,377,166 limb products for the thirteen exponents through 11213 in 212 s, flags clean; 2^19937 - 1 verified across three resumed runs | fp64 needs 22-29x the limb products and 7-13x the wall time for the same exponent; every rung returns the same residue chain |
| `cft-orbits` (docs/ORBITS.md) | symplectic few-body integration, Kepler and the outer solar system | correctly rounded arithmetic, bit-identical ensembles | 95,263 element-steps/s for the Kepler leapfrog as a program (284 library calls where the loop needs 295,195); 12,077 for the Yoshida scheme with correctly rounded 1/r^3; the outer solar system 3,136 | energy drift identical at every format - the method: 7.9e-4 leapfrog, 2.0e-5 Yoshida over 2,000 periods - while angular-momentum drift, the arithmetic, is 9.0e-69 at fp256 against 1.4e-13 at fp64, 2^184 apart |
| `cft-zoom` (docs/ZOOM.md) | a deep-zoom Mandelbrot reference orbit with fp64 perturbation | a bit-identical fp256 reference orbit as a sequencer escape loop | 174,462 reference iterations/s as a program (98 calls per 100,000 iterations on the software backend; 3,125 at a tile's 64-deposit cap), 162,374 as a loop; 399,782 fp64 pixel-iterations/s with an identical pixel chain at every batch size | at a 3.1e-61 pixel the fp64 reference is 9.4e30 pixels off and wrong from iteration 1 while raising no flag; all 4,096 pixels differ; fp256 addresses pixels to 1e-71 against fp64's 1e-15 |

Three of the five asked the sequencer for something it does not have,
and the asks are recorded in their design notes rather than worked
around silently: a fourth input stream and an optional per-element
flag output (Collatz); more than sixteen addressable constants, since
operand fields are four bits (enclose); a lane shift and an in-program
cross-lane reduction, which would put a whole carry chain and a
convolution on-chip (Mersenne). Composed operations and reductions
cannot be called from inside a program, which is why the enclosure
tool's series and dot kernels, and the Mersenne convolution, run as
host-issued calls around program passes.

All five also run in the browser (docs/DEMOS.md): a second committed
page on the module the conformance page embeds, each panel a port of
the tool's loop engine with elements batched, and each panel's chain
matched to the C tool's for the same configuration - 13 chains over 11
configurations on 2026-09-04. Browser rates came out at 0.8 to 1.4
times the native loop engines wherever a call carries a batch (zoom
pixels 343,381 against 346,414 pixel-iterations/s, Mersenne 473,911
against 646,661 limb products/s, orbits 22,645 against 24,922
element-steps/s); a single-lane Collatz trajectory is the outlier at
a quarter of native, which is the wasm boundary and nothing else.
Those are measurements of the same slow tier, made in a browser, and
the page says so.

## Reading the numbers

**MPFR is 7-25x faster than libcft's software backend on the
single-rounding ops, and 90-300x on division and square root.** Both
gaps are real and neither is mysterious. MPFR is thirty years of
CPU-tuned limb assembly (the prefix build configures GMP for the exact
microarchitecture) with native algorithms for every operation; libcft
is portable C99 with no per-CPU code, whose `cft_div`/`cft_sqrt`
deliberately take the composed route - a fixed sequence of ~25-30
opcode passes, documented in host/include/cft.h - because that is the
sequence the TILE executes, and the software backend's job is to be
the tile's bit-exact reference on any machine, not to race MPFR on
this one. The div/sqrt multiple is almost exactly the pass count times
the per-pass price, which is the composition working as specified.

**The one place the comparison inverts: fp128 fused multiply-add.**
libcft's fma (394 ns) is 2.1x faster than libquadmath's `fmaq`
(811 ns) - the common x86 route to binary128 pays more for a correctly
rounded fma than this repo's whole softfloat path costs, while
`__float128` add/mul (compiler-emitted libgcc calls) beat libcft by
~20x. If your fp128 workload is fma-shaped - and the tile's entire
architecture is a bet that the interesting ones are - the "slow
portable library" is already the faster soft option on stock gcc.

**The emulation tax on MPFR is visible and small: 4-8 ns.** That is
what `mpfr_check_range` + `mpfr_subnormalize` add per call. What it
does not buy from MPFR: binary interchange encodings, NaN payloads,
signaling NaNs, or this contract's flag definitions. mpfr+754 is the
closest MPFR gets to a binary-format drop-in, and the remaining
distance is semantic, not performance.

**Silicon is 300-5000x below every soft path.** The cpu-hw rows are
the CPU doing fp32/fp64 in hardware; even MPFR pays 15-45x against
them. That differential is the whole argument for the tile: above
binary64 there is no silicon in a CPU to fall back to, so every
fp128/fp256 user today is paying soft-float prices - and the tile's
job is to move those two rungs to the hardware side of that gap, with
bits identical to what the software tier already produced.

**The Python tier is its own decade.** mpmath at any precision costs
more than libcft at fp256, and ~40-60x MPFR. That is the audience
bindings/python/cftmpfr exists for: same Python, contract bits, and a path
down to the C prices above (and eventually the card) without leaving
the language.

**What these numbers do not cover:** subnormal-heavy or
special-heavy streams (every soft path here slows down on them, each
differently - the operand generator's header says why fast-path
normals are the published case), rounding modes other than RNE,
multi-threading (everything above is one core), and the flag/status
plumbing cost of a real caller. And nothing here is the tile:
hardware rows land in this file when a card produces them, measured,
under docs/CARDDAY.md gate 6.
