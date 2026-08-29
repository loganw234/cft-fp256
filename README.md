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

## What exists today (v0)

| piece | state |
|---|---|
| `python/cft_golden` | exact fp32/fp64/fp128/fp256 fma/add/sub/mul + flags, dependency-free; **16 pytest gates green** against native binary64, `math.fma`, mpmath, and hand-computed 754 anchors |
| `rtl/` | parameterized behavioural FMA core (one source for fp32 and fp256), operand steering, ap_ctrl_hs CSR block, v0 vector engine, Vitis kernel top |
| `tb/` | cocotb: streamed unit benches (fp32, fp256) + full-kernel AXI end-to-end via cocotbext-axi, every result and flag bit checked against the golden model - **green**: 4000 fp32 + 1300 fp256 vectors and 7 kernel runs bit-exact (Icarus 12, cocotb 1.9.2, in the `docker/` container) |
| `hw/` | kernel.xml (== the CSR map), package_xo script, HBM link.cfg - written to the documented flow, **not yet run against a live Vitis** (docs/BRINGUP.md gates that honestly) |
| `host/` | pyxrt example that runs a vector op and verifies it against the golden model |
| `vectors/` | deterministic conformance-set emitter (JSONL, seeded) |

Nothing here has met a physical card yet. The claim v0 makes is
narrower and checkable: the RTL is bit-exact against a golden model
that is itself proven against implementations sharing no code with it.

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
```

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
