# cft-fp256

**A math coprocessor that gets the same answer everywhere.**

It does IEEE 754 arithmetic at four precisions - 32, 64, 128 and 256
bits - and guarantees that the same inputs give the same bits whether
the work runs on a laptop CPU, in a browser tab, on a microcontroller,
or on the FPGA card it was designed for.

That guarantee is the product. The hardware only makes it faster.

Formally it is the Coordinated Fusion Compute Tile, built for the
AMD/Xilinx Alveo U50C through the open Vitis RTL kernel flow, and
everything here is Apache-2.0.

## Try it without installing anything

**<https://loganw234.github.io/cft-fp256/>**

That page is this project's software compiled to WebAssembly. It replays
the published conformance vectors in front of you, and its calculator
reaches every operation: all four precisions, all five rounding modes,
the thirty-nine transcendental functions, the character conversions.
Drop a vector file on it and it scores itself.

A second page,
[demos.html](https://loganw234.github.io/cft-fp256/demos.html), runs five
real workloads in the browser, each one's checksum chain matched against
the command-line tool's.

## Why this exists

Floating-point arithmetic is permitted to differ between machines, and
it does. Two GPUs from different vendors, or the same source through a
different compiler, can disagree in the last bits and then diverge. For
anything iterative - orbital mechanics, deep-zoom fractal geometry,
reproducible science - that ends the run.

The usual answer is to require agreement only within a tolerance. This
project takes the other route: define one exact result for every
operation, score every implementation against it, and make runs
reproducible bit for bit.

Exactness buys things a tolerance cannot. You can cache a result and
trust it later. You can replay a computation and get an identical trace.
You can compare two machines with `diff`.

The proven case is [atlas-engine](https://github.com/loganw234/atlas-engine)'s
geometry library, which produces **one hash across NVIDIA, AMD and Intel
GPUs**.

## What it is not for

Raw fp32 and fp64 throughput. Every CPU and GPU on the market serves
those formats at clocks and lane counts an FPGA fabric will not match,
and nothing here pretends otherwise. They are carried because they are
rungs of the same ladder as 128 and 256, and carrying the whole ladder
is what lets one contract cover all of it.

The tile earns its place at the precisions commodity hardware does not
offer, and on the guarantee that the answer does not move.

## Where it runs, and how fast

The same library, the same bits, on four very different machines. Rates
are for binary256, the widest and slowest format; binary32 runs roughly
eight times faster on every row.

| where | what it is | binary256 throughput |
|---|---|---|
| a browser, or any CPU | the software library, no dependencies | 1.7 million elements a second |
| a microcontroller | the same C, on an ESP32-S3 over a serial line | a few hundred cases a second |
| the FPGA card, one tile | the same work, with the bus out of the way | 107 million elements a second |
| the FPGA card, four tiles | four times over | 427 million, at about 35 watts |

The microcontroller row is not a stunt. That part replayed **508,000
published conformance cases** - every binary32 and binary64 family,
complete - and disagreed with the reference on none of them. It is the
same library the card runs, compiled small.

## What is built and working

| piece | what it is |
|---|---|
| `python/cft_golden` | The definition of correct. Exact, dependency-free Python: 30 opcodes, all five rounding modes, the complete IEEE clause 5 function set, and all thirty-nine transcendentals correctly rounded. Everything else is scored against this, never against each other. |
| `rtl/` | The tile. A 16-stage pipelined fused-multiply-add core that splits one 256-bit lane into 2x fp128, 4x fp64 or 8x fp32, plus operand steering, a streaming engine, a reduction accumulator and an on-chip program sequencer. Yosys-clean, portability enforced in CI. |
| `tb/` and `formal/` | 21 simulation targets checking every result and every flag against the golden model, and 31 machine-checked proofs with a negative control. |
| `host/` | **libcft**: about 19,900 lines of C99, no dependencies, no build step for callers. One ABI reachable from C, C++, Python, Rust, Julia, Go, C#, R and Fortran, with software, FPGA and remote backends behind identical calls. |
| `bindings/` | The WebAssembly build behind the pages above, a Node package, and a Python drop-in for the MPFR pattern. |
| `hw/` | Vitis packaging, HBM layout and the build pipeline. Bitstreams built and run on silicon. |
| `vectors/` | The conformance sets: 1,071,635 cases, deterministic and seeded. |

Each of these has a document in `docs/` carrying the detail, the dates
and the measurements.

## How the claims are checked

The rule is that a number in a document has a run behind it, and the
runs that failed stay in the record. The load-bearing ones:

- **The card reproduced every published case on silicon**, through one
  tile and through four. `docs/CARDDAY.md` is the runbook as it was
  actually run; `docs/VALIDATION.md` is the running record.
- **Division and square root** are held against 23.9 billion cases of
  the host CPU's own IEEE hardware, and 999,000 cases of GNU MPFR.
- **The transcendentals** are held against MPFR over 739,234 cases, with
  zero value and zero flag mismatches.
- **The same program in nine languages** prints byte-identical
  checksums, each on the platform and date `docs/COMPATIBILITY.md`
  records.
- **CI's green tick does not cover synthesis, timing or silicon.**
  `docs/BRINGUP.md` owns those gates and defines "done" for each;
  `docs/VERIFICATION.md` maps every gate, what it proves, and how long
  it really takes.

## Quickstart

The golden model's self-tests (any Python 3.10+, mpmath optional but
recommended):

```bash
pip install pytest mpmath
make golden
```

The host library, which needs no FPGA toolchain at all:

```bash
make libcft            # C99, no dependencies
make libcft-test       # contract tests, the published sets replayed, C vs Python
make libcft-diff       # against the golden model, boundary-targeted
```

RTL simulation, identical locally and in CI through the container:

```bash
make docker-image
make sim-docker
```

Everything at once - model, vectors, RTL suite, yosys, formal proofs,
library gates, oracle spot checks - resumable and logged:

```bash
make verify
```

Hardware needs Vitis/Vivado and XRT on a Linux box. Read
`docs/BRINGUP.md` first:

```bash
make xo                                  # package rtl/ -> build/cft_krnl.xo
make xclbin TARGET=hw_emu                # emulation link
make xclbin PLATFORM=$(xbutil-reported)  # hardware link
```

Against a device, in emulation or on a card. The same command either
way, because the artifact's name selects the environment:

```bash
make -C host XRT=1 device-test
bash hw/run-device-test.sh cardday/quad/cft_hw.xclbin -n 4096
```

## Layout

```
python/cft_golden/   the definition of correct: exact softfloat + vector gen
python/tests/        golden proven against native f64, math.fma, mpmath, 754 anchors
rtl/                 the FMA core, the per-tile lane array, the CSR block,
                     the streaming engine, the sequencer, the kernel top
tb/                  cocotb benches + Makefiles (SIM=icarus default, verilator alt)
formal/              the property proofs (make formal): 31 tasks + a negative control
hw/                  kernel.xml, packaging, link.cfg, out-of-context timing builds
host/include/cft.h   the C ABI: the contract between this and its users
host/src/            libcft - software, XRT and remote backends, conformance
host/tests/          contract tests, device-vs-software, differential
host/fuzz/           the four parsers that face untrusted bytes, fuzzed (opt-in)
host/tools/          the workload tools, the assembler, the image runner
host/examples/       the same program in nine languages, byte-identical checksums
bindings/            the WASM build, the Node package, the Python MPFR drop-in
verify/              the standardized verification runner (make verify)
vectors/             conformance-set emitter (JSONL)
programs/            the program library: sources, a check per program, a manifest
docker/              the simulation container CI and dev boxes share
docs/                one file per subject; see below
```

In `docs/`, start with **DETERMINISM** (the contract itself),
**ARCHITECTURE** (how the tile works), **HOSTAPI** (how to call it) and
**INTEGRATION** (which path to use, and where each one's wall is).
**VERIFICATION** maps every gate and its real cost; **VALIDATION** is the
running record of what was run and what it said, with failures kept
beside passes. **EMBEDDED** covers the microcontroller row above,
**REMOTE** the tile behind a socket, and **BENCHMARKS** the measured
throughput and what bounds each number.

## Design rules the repo is built around

- **One definition of correct.** The golden model is integer-exact
  Python with zero dependencies. RTL, host and vectors are all scored
  against it, never against each other.
- **The contract outranks the implementation.** Each shared definition
  exists in exactly one other place, and changes move together.
- **Claims stay measurable.** A number has a run behind it, and a
  hypothesis that turned out wrong stays in the record with the
  measurement that killed it.
- **Everything open.** Apache-2.0, the standard Vitis flow, and a
  verification stack of cocotb, mpmath and pytest - all permissive.

## Where this is going

`docs/ROADMAP.md` has the detail. In short: the card is up and
reproducing the vectors; the next tier is the same tile on an open
Kintex-7 board, where one tile fits in 46% of a 325T; and the roadmap
now also carries what the first outside workload asked the library for,
ranked by measurement rather than by guess.

## Built on it

**[cft-rebound](https://github.com/loganw234/cft-rebound)** is the first
application here that is somebody else's algorithm rather than this
project's own: [REBOUND](https://github.com/hannorein/rebound)'s IAS15,
a fifteenth-order adaptive N-body integrator used in real
orbital-dynamics research, with every floating-point operation routed
through libcft. The same integration then runs at binary64, binary128
and binary256, and on the tile.

It is a separate repository under GPL-3.0, because REBOUND is GPL-3.0
and Apache-2.0 combines into that licence but not the reverse.

What it has shown so far:

- **At binary64 the port is REBOUND's own IAS15, bit for bit.** That
  equivalence is the correctness gate, and it holds across long runs and
  the awkward paths - rejected steps, iteration caps.
- **On the card, every comparison against the software backend produced
  an identical record.** Not only the trajectories: the adaptive
  corrector took the same number of passes, which a single differing bit
  would have moved.
- **binary128 is worth having; binary256 mostly is not, for this
  integrator.** IAS15 was designed to sit at the binary64 round-off
  floor, and moving to binary128 recovers about four orders of magnitude
  of accuracy at once. Going further to binary256 changes nothing on the
  same test, because the method's own truncation error dominates by
  then. That is a negative result, measured and kept.
- **The tile overtakes one CPU core between 8 and 32 bodies** and
  saturates around 2.7 to 2.9 times it. Below that it is slower, by up
  to 4.6 times on a two-body problem, because the engine's width is its
  whole advantage and a small system leaves it idle.

It also sent work back the other way: what that integrator needs and the
library does not have is recorded in `docs/ROADMAP.md`, ranked by
measurement, and the general lesson about irregular access patterns is
in `docs/INTEGRATION.md`.

The port is in active development and its own `docs/VALIDATION.md`
carries the numbers, the dates and the failures.

## Neighbours

The workload this tile exists to serve is
[atlas-engine](https://github.com/loganw234/atlas-engine), and the plates
it evaluates are the
[PrettyCloud](https://github.com/loganw234/PrettyCloud) atlas at
prettycloud.io. `docs/ATLAS.md` assesses what the backend swap needs; its
first step is done, with that library emitting as sequencer programs
bit-identical to the pinned GLSL over 4,096-point sweeps.

The camera whose census this README cites as its proven case is
atlas-darkroom, which is private, and it labels the citation from its own
side: one of the operator's projects vouching for another is worth
exactly what the census behind it is worth, and nothing more.

## License

Apache-2.0 (see LICENSE, NOTICE). Dependencies: cocotb (BSD-3),
cocotbext-axi (MIT), mpmath (BSD), pytest (MIT), XRT/pyxrt (Apache-2.0)
- all permissive, per the project's ground rule.
