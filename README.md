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
| `python/cft_golden` | exact fp32/fp64/fp128/fp256 fma/add/sub/mul + flags, dependency-free; **16 pytest gates green** against native binary64, `math.fma`, mpmath, and hand-computed 754 anchors |
| `rtl/` | the v1 15-stage pipelined FMA core (one parameterized source serving all four rungs: 8x fp32 / 4x fp64 / 2x fp128 / 1x fp256 per 256-bit beat), operand steering, ap_ctrl_hs CSR block with CAPS discovery, vector engine, Vitis kernel top; the v0 behavioural core stays as the readable reference; **Yosys-clean** (CI-enforced portability) |
| `tb/` | cocotb: streamed unit benches for all four widths + full-kernel AXI end-to-end via cocotbext-axi, every result and flag bit checked against the golden model - **green**: 4000 fp32 + 4000 fp64 + 2100 fp128 + 1300 fp256 vectors and 12 kernel runs bit-exact (Icarus 12, cocotb 1.9.2, in the `docker/` container) |
| `hw/` | kernel.xml (== the CSR map), package_xo script, HBM link.cfg, the era-matched `rebuild-2022.sh` pipeline - **packaging and hw_emu gates MET** (bit-exact vs golden through real XRT), hw bitstreams built (docs/BRINGUP.md records each gate honestly) |
| `host/` | pyxrt example that runs a vector op and verifies it against the golden model |
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
python3 host/examples/vector_fma.py build/cft_hw.xclbin --format fp256 --op fma --n 512
```

## Layout

```
python/cft_golden/   the definition of correct: exact softfloat + vector gen
python/tests/        golden proven against native f64, math.fma, mpmath, 754 anchors
rtl/                 cft_fpfma (core) / _pipe / cft_opmux / cft_csr / cft_engine / cft_krnl
tb/                  cocotb benches + Makefiles (SIM=icarus default, verilator alt)
hw/                  kernel.xml, package_kernel.tcl, link.cfg
host/examples/       pyxrt host, verifies against the golden model
vectors/             conformance-set emitter (JSONL)
docker/              the simulation container CI and dev boxes share
docs/                DETERMINISM (the contract), ARCHITECTURE, ROADMAP, BRINGUP
CAPABILITIES.md      what the tile can and cannot do, with the gaps named
```

**Start with [CAPABILITIES.md](CAPABILITIES.md)** if you want to know
whether this is useful to you. It is deliberately unflattering: four
of the six arithmetic operations IEEE 754 requires, none of the
comparison or conversion operations, and no way to express a sequence
on-chip. What it does do, it does bit-exactly.

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
