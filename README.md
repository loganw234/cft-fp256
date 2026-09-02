# cft-fp256

The Coordinated Fusion Compute Tile: a deterministic, dynamically
scalable IEEE 754-2019 math coprocessor - fp256 at the top of the
ladder, fracturing down to 8x fp32 lanes - built on the AMD/Xilinx
Alveo U50C (VU35P, 8 GB HBM2) through the open Vitis RTL kernel flow.

**The product is a contract, not a chip**: same inputs, same op, same
bits - on this tile, on the pure-Python golden model, and on any other
implementation that claims conformance. docs/DETERMINISM.md states the
contract clause-by-clause against IEEE Std 754-2019; `vectors/` makes
it scoreable.

The adoption story is two tiers with one contract. A software library
anyone can run on anything - the proven case is atlas-engine's pinned
GLSL det library, one hash across NVIDIA, AMD, and Intel GPUs - and
this hardware for heavy compute: identical bits, more speed, and
precision up to fp256 when the problem needs it (deep-zoom orbits,
reference oracles, interval arithmetic to come). The entry point stays
a simple library; the tile only makes it faster.

## What exists today

| piece | state |
|---|---|
| `python/cft_golden` | exact fp32/fp64/fp128/fp256, 25 opcodes (arithmetic, sign, min/max, predicates, integer/bitwise, and reductions with an index-fixed tree) under all five 754 rounding attributes, plus the full clause-5 contract function set (div/sqrt, roundToIntegral, every conversion, scaleB/logB, nextUp/nextDown, class, totalOrder, signaling compares, remainder) and the orbit sequencer's execution model; dependency-free; **pytest green** against native binary64, `math.fma`, mpmath, math.remainder/nextafter/ldexp, an exact-rational rounding reference, and hand-computed 754 anchors |
| `rtl/` | the v1 15-stage pipelined FMA core (one parameterized source serving all four rungs: 8x fp32 / 4x fp64 / 2x fp128 / 1x fp256 per 256-bit beat), operand steering, ap_ctrl_hs CSR block with CAPS discovery, streaming engine with one AXI master per operand stream and pipelined address phases, a streaming reduction accumulator, the orbit sequencer (`cft_seq`: on-chip programs over the existing opcodes behind MODE[15], benched bit-exact against `seq.py`; hw_emu pending), and **one ALU array per tile** (`cft_lanes`, owned by `cft_krnl`): the streaming engine and the sequencer each present a per-issue request and MODE[15] - already the AXI owner-select - says whose reaches the array, with no arbitration because they never run at once. The sequencer's private second copy is gone, and out of context at 135 MHz that is 288,764 -> 162,482 LUT a tile, 139,404 after the sequencer's control diet. The optional fused ladders live in the array too (`FUSE_MUL`/`FUSE_NORM`/`FUSE_ALIGN`, **all default off**): the 2026-08-31 campaign's `FUSE_NORM`/`FUSE_ALIGN` stay equivalence-proven step by step and are worth 15,805 LUT here (139,404 -> 123,599), but they leave only +0.097 ns of out-of-context slack at 135 MHz against ladders-off's +0.307, and a shell build is what settled that a thin out-of-context margin is not a margin. BRAM-backed stream FIFOs, Vitis kernel top; the v0 behavioural core stays as the readable reference; **Yosys-clean** (CI-enforced portability) |
| `tb/` | cocotb: streamed unit benches for all four widths + full-kernel AXI end-to-end via cocotbext-axi, every result and flag bit checked against the golden model - **green** across `make sim`'s 17 targets / 50 tests, including the reduction accumulator, full-kernel reductions, the divide/sqrt seed opcodes (85,264 comparisons), trimmed-build precision refusal, bus-fault injection, and the sequencer's unit and full-kernel benches against seq.py (Icarus 12, cocotb 1.9.2, in the `docker/` container). Two more targets sit beside the aggregate rather than in it, `krnlfused` and `krnlplain`, which run the full kernel with the fused ladders on and off and hold both to the same bits - the ladders are a resource trade, not a numeric one. Beside it, `formal/`: machine-checked proofs - the stream FIFO unbounded, the seed special-cases complete, and the simpleops area rewrite proven equivalent over all 2^104 inputs |
| `hw/` | kernel.xml (== the CSR map), package_xo script, HBM link.cfg, the era-matched `rebuild-2022.sh` pipeline, `gen_layouts.py` + `layouts/` (every tile mix the U50 could carry, derived - docs/LAYOUTS.md) - **packaging and hw_emu gates MET** (bit-exact vs golden through real XRT), hw bitstreams built (docs/BRINGUP.md records each gate honestly) |
| `host/` | **libcft** - ~5,200 lines of C99 across `src/`, no dependencies, no build step for callers: one ABI reachable from Fortran, Julia, Python, Rust, C and C++. The software backend replays 392,000 conformance cases and agrees with the golden model on 216,000 differential cases; `cft_div`/`cft_sqrt` compose the tile's seed opcodes into correctly-rounded division and square root, proven against **23.9 billion cases of the host CPU's own IEEE hardware and 999,000 cases of GNU MPFR** (docs/VALIDATION.md); as of 2026-09-01 the **rest of clause 5** ships too - roundToIntegral, every conversion, scaleB/logB, nextUp/nextDown, class, totalOrder, signaling compares, exact remainder - composed or host-exact, zero new RTL, held identical to the model over 112,372 per-element checks; an XRT backend drives up to 64 compute units and has been exercised against a **four-tile hw_emu image with no card present**. Reductions add the tree-aware multi-tile split, so a sum over four tiles returns what one tile returns. The C and Python examples print identical checksums on Linux/glibc and Windows/msvcrt - as do Fortran, Rust, Julia, Go, C# and R (docs/COMPATIBILITY.md). **Validate the contract in your browser, nothing installed: https://loganw234.github.io/cft-fp256/** - the software backend compiled to WebAssembly, replaying the published vectors |
| `vectors/` | deterministic conformance-set emitter (JSONL, seeded) |

No physical card yet (it is in the mail). The claim made so far is
narrower and checkable: the RTL is bit-exact against a golden model
that is itself proven against implementations sharing no code with
it, through the same interfaces XRT drives on silicon.

## Quickstart

Golden model self-tests (any Python 3.10+; mpmath optional but
recommended):

```bash
pip install pytest mpmath
make golden
```

RTL simulation - identical locally and in CI, via the container
(Docker Desktop on Windows works; native `make sim` needs Icarus):

```bash
make docker-image
make sim-docker
```

Or everything at once - the standardized verification run (model,
vectors, RTL suite, yosys, formal proofs, library gates, oracle spot
checks), resumable and logged, ending in a census block:

```bash
make verify
```

Conformance vectors:

```bash
make vectors
```

Hardware (needs Vitis/Vivado + XRT on a Linux box; see docs/BRINGUP.md
before running these):

```bash
make xo                                  # package rtl/ -> build/cft_krnl.xo
make xclbin TARGET=hw_emu                # emulation link
make xclbin PLATFORM=$(xbutil-reported)  # hardware link
```

The host library, which needs none of that:

```bash
make libcft            # C99, no dependencies
make libcft-test       # contract tests, 392k-case replay, C vs Python
make libcft-diff       # against the golden model, boundary-targeted
make libcft-docker     # the same tests on a second platform
```

And against a device, in emulation or on a card - the same command
either way, because the artifact's name selects the environment:

```bash
make -C host XRT=1 device-test
bash hw/run-device-test.sh cardday/quad/cft_hw.xclbin -n 4096
```

## Layout

```
python/cft_golden/   the definition of correct: exact softfloat + vector gen
python/tests/        golden proven against native f64, math.fma, mpmath, 754 anchors
rtl/                 cft_fpfma (core) / _pipe / cft_opmux, gathered into the
                     one per-tile array cft_lanes; cft_csr / cft_engine_stream /
                     cft_seq / cft_krnl
tb/                  cocotb benches + Makefiles (SIM=icarus default, verilator alt)
hw/                  kernel.xml, package_kernel.tcl, link.cfg
host/include/cft.h   the C ABI: the contract between this and its users
host/src/            libcft - software backend, XRT backend, conformance
host/tests/          contract tests, device-vs-software, differential
host/examples/       the same program in C, Python (ctypes), Fortran, Julia,
                     Rust, Go, C# and R - byte-identical checksums everywhere;
                     the full language/drop-in matrix with per-row
                     verification status is docs/COMPATIBILITY.md
bindings/            cftmpfr (the Python MPFR drop-in) and the WASM build
                     behind the browser conformance page
formal/              the property proofs (make formal): FIFO, seeds,
                     simpleops equivalence, plus the negative control
verify/              the standardized verification runner (make verify):
                     every gate, one resumable logged run, census output
vectors/             conformance-set emitter (JSONL)
docker/              the simulation container CI and dev boxes share
docs/                DETERMINISM (the contract), ARCHITECTURE, HOSTAPI,
                     SEQUENCER, SCALING, ROADMAP, BRINGUP, CARDDAY,
                     BENCHMARKS (the software tier measured against
                     MPFR, __float128 and the CPU itself),
                     NOVEL (results with no prior description found)
CAPABILITIES.md      what the tile can and cannot do, with the gaps named
```

**Start with [CAPABILITIES.md](CAPABILITIES.md)** if you want to know
whether this is useful to you. It stays deliberately unflattering:
IEEE 754-2019 clause 5 is now covered on the binary side - the six
required arithmetic operations (division and square root composed
from the tile's own seed opcodes and FMA), reductions with a
contractual tree, and the full completion set from roundToIntegral to
exact remainder - but the character-sequence conversions are still
absent, and no sequence has been expressed on a device yet: the orbit
sequencer is RTL now, holding bit-exact to `seq.py` through the
kernel's one ALU array in simulation, with hw_emu and silicon still
ahead of it. What it does do, it does bit-exactly, and the file names
every gap that remains.

## Design rules the repo is built around

- **One definition of correct.** The golden model is integer-exact
  Python with zero dependencies; RTL, host, and vectors are all scored
  against it, never against each other.
- **The contract outranks the implementation.** rtl/cft_opmux.sv,
  `softfloat.steer`, kernel.xml, and the CSR map each exist in exactly
  one other place (docs), and changes move together.
- **Claims stay measurable.** CI's green tick covers the golden gates
  and simulation; it does not cover synthesis, timing, or silicon -
  docs/BRINGUP.md owns those gates and says what "done" means for
  each.
- **Everything open.** Apache-2.0; the toolchain path is the standard
  Vitis RTL kernel flow (`package_xo` + `v++`), host is pyxrt, and
  verification is cocotb + cocotbext-axi + mpmath - all open source.

## Where this is going

docs/ROADMAP.md, in one line each: v0.x puts this bitstream on the
card and reproduces the vectors; v1 builds the true fractured array
(one DSP array serving 1x256 / 2x128 / 4x64 / 8x32), bursts, more CUs,
directed rounding; v2 adds the orbit/walk micro-sequencer with
hardware-guaranteed deposition order, the atlas parity column, and the
high-precision oracle role.

## License

Apache-2.0 (see LICENSE, NOTICE). Dependencies: cocotb (BSD-3),
cocotbext-axi (MIT), mpmath (BSD), pytest (MIT), XRT/pyxrt
(Apache-2.0) - all permissive, per the project's ground rule.
