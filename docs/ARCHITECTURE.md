# Architecture

The Coordinated Fusion Tile (CFT): a fusedMultiplyAdd-centric compute
tile whose precision scales along the IEEE binary interchange ladder -
one datapath architecture serving all four interchange rungs (8x fp32,
4x fp64, 2x fp128, 1x fp256 per beat), with the true fractured array
(one physical multiplier serving every mode) on the roadmap. Target
platform: AMD/Xilinx Alveo U50/U50C (VU35P, 8 GB HBM2), Vitis RTL
kernel flow, XRT host runtime.

## Block structure

```
                     s_axi_control (AXI4-Lite)
                            |
                       +---------+
                       | cft_csr |  ap_ctrl_hs + args + FLAGS/MAGIC/VERSION/CAPS
                       +---------+
                            |  start/done/cfg
                       +------------+
   m00_axi (AXI4-256) <-> cft_engine |  beat FSM, A/B/C reads, D write
                       +------------+
                            |
                    256-bit beat, one per element group
                            |
        +----------+----------+-----------+-----------+
        | 8x (8,23) | 4x (11,52) | 2x (15,112) | 1x (19,236) |
        |  fp32 bank |  fp64 bank |  fp128 bank |  fp256 unit |
        +-----------+-----------+------------+------------+
              each lane: cft_opmux -> cft_fpfma_pipe
```

- **cft_fpfma_pipe** - the parameterized 15-stage FMA core (v1):
  staged significand multiplier (24-bit chunk columns + four
  registered tree levels), coarse/fine alignment with the sticky
  marker, split-carry add, per-64 LZC normalize, single RNE rounding
  with after-rounding tininess, pack, flags. Fixed latency, no
  stalls; ordering is structural. The stage map and the marker/sticky
  safety argument are in the header comment.
- **cft_fpfma** - the v0 single-cloud behavioural core, kept as the
  readable reference: it is the RTL written to be read line-by-line
  against `python/cft_golden/softfloat.py`. Not instantiated in the
  kernel.
- **cft_opmux** - operand steering: ADD/SUB/MUL are the FMA core with
  steered operands (b:=1.0, c sign-flip, signed-zero c). The table
  lives in three places that must move together: this module,
  `softfloat.steer`, and this document.
- **cft_csr** - AXI4-Lite slave, Vitis ap_ctrl_hs protocol, argument
  registers, and the read-only FLAGS/MAGIC/VERSION/CAPS block.
- **cft_engine_stream** - the v1 streaming sequencer the kernel
  instantiates: burst reads into three per-stream FIFOs (arbitrated
  a > b > c, one AR outstanding, 4KB-safe), one beat issued per cycle
  into the bank MODE selects whenever operands and result space
  exist, collection through a latency-matched delay line into a D
  FIFO, index-order burst writes out. Read, compute and write overlap
  across beats; issue and write order stay total, so determinism is
  untouched. All four banks share the one delay line because every
  `cft_fpfma_pipe` instance has the same structural depth regardless
  of width.
- **cft_engine** - the naive one-beat-at-a-time reference engine
  (read A, read B, read C, compute, write, advance - ~40 cycles per
  beat). Not instantiated; kept as the readable spec the streamer is
  scored against, the same role cft_fpfma plays for the pipe.

## Datapath geometry

The tile's compute width is the **beat: 256 bits** - 8 fp32, 4 fp64,
2 fp128 lanes or 1 fp256 operand, and also the native width of an HBM
pseudo-channel, so no width converter sits between the kernel and
memory (in fabric or in emulation - a 512-bit master demonstrably
lost write payloads through the 2022-era platform's emulation
converter models; see BRINGUP.md). This is the shape the fractured
array keeps: one physical array computing any rung per beat instead
of four separate banks, precision still selected per run.

Elements per beat: fp32 -> 8, fp64 -> 4, fp128 -> 2, fp256 -> 1.

Bank trims: `cft_krnl` takes `EN_FP64/EN_FP128/EN_FP256` parameters
(default all on) so constrained targets - the open-core conformance
nodes in ROADMAP.md - can drop banks they cannot fit. What remains
is advertised in CAPS and is bit-identical to the full tile on the
rungs it carries; the beat stays 256 bits regardless.

## CSR map (== hw/kernel.xml == cft_csr.sv)

| offset | reg | access | contents |
|---|---|---|---|
| 0x00 | CTRL | RW | [0] ap_start [1] ap_done (clear-on-read) [2] ap_idle [3] ap_ready |
| 0x04 | GIER | RW | storage only; no interrupt exported in v0 |
| 0x08 | IER  | RW | storage only |
| 0x0C | ISR  | RO | 0 |
| 0x10 | MODE | RW | [3:0] op: 0 fma, 1 add, 2 sub, 3 mul; [7:4] precision: 0 fp32x8, 1 fp64x4, 2 fp128x2, 3 fp256 (issue only precisions set in CAPS); [31:8] reserved, write 0 (a rounding-mode field will land here) |
| 0x18 | N    | RW | element count, 64-bit |
| 0x20 | A_PTR | RW | 64-bit HBM byte address |
| 0x28 | B_PTR | RW | 64-bit |
| 0x30 | C_PTR | RW | 64-bit |
| 0x38 | D_PTR | RW | 64-bit |
| 0x40 | FLAGS | RO | sticky {inexact,underflow,overflow,divzero,invalid} of the last run; cleared at ap_start |
| 0x44 | MAGIC | RO | 0x43465430 "CFT0" |
| 0x48 | VERSION | RO | 0x00000200 (v0.2.0: fp64/fp128 rungs + CAPS) |
| 0x4C | CAPS | RO | [3:0] precision bitmask, bit p = MODE precision p implemented; full tile reads 0xF |

## Host contract

- Buffers 32-byte aligned (XRT BOs are), elements little-endian,
  arrays dense.
- **N must be a whole number of beats**: a multiple of 8 for fp32, 4
  for fp64, 2 for fp128; any N for fp256. The engine processes whole
  beats only; hosts pad the tail (any padding values are computed and
  written to D's padding region - harmless, and their flags DO join
  the sticky OR, so pad with zeros, not junk, when flags matter).
- Read CAPS once at open: bit p set means MODE precision p is
  implemented in this bitstream. The full Alveo tile reads 0xF;
  trimmed open-core tiles clear what they dropped. Issuing a
  non-advertised precision is undefined (no arithmetic hazard - the
  run completes - but D's contents are meaningless).
- Operand semantics per op: FMA uses A,B,C; ADD/SUB use A,C (B
  ignored); MUL uses A,B (C ignored). D = op result. SUB computes
  A - C.
- One run per ap_start; poll CTRL for ap_done (XRT does this
  natively); read FLAGS before the next start if you want them.

## AXI behaviour (v1 streamer)

Single ID, INCR bursts up to 16 beats (512 B), never crossing a 4KB
boundary, full write strobes. One AR outstanding at a time, streams
arbitrated a > b > c into 32-beat FIFOs; writes drain the result
FIFO in full bursts (the tail is always fully buffered, so short
final bursts need no special case). Read, compute and write overlap:
steady state costs 4 transfers per beat on the one shared 256-bit
port (3 reads + 1 write), so the engine is port-bound at ~5
cycles/beat with burst-amortized latency - versus ~40 for the naive
reference engine. At 100 MHz that is ~20M beats/s: ~160M fp32 FMA/s,
~20M fp256 FMA/s, per tile.

The remaining engine knobs - multiple outstanding ARs, per-stream
HBM pseudo-channels, multiple CUs - are roadmap items; none change
numerics. The naive engine remains in rtl/ as the auditable
reference for the same CSR contract.

## Timing (v1 core, measured OOC on xcu50)

The 15-stage core closes ~232 MHz fp32 / ~148 MHz fp256 out of
context (fp64/fp128 land between; QoR numbers recorded in
ROADMAP.md). Kernel clock for full-platform builds: ~100 MHz via
`hw/rebuild-2022.sh KERNEL_FREQ=` - conservative margin under the
shell, raised as the QoR chase (DSP column splits, round-stage
balance) lands. A reduced clock changes nothing about results -
determinism is clock-independent by construction. The v0 behavioural
core (one combinational cloud, ~65/14 MHz) remains in rtl/ as the
readable reference.

## The fractured array (v1 sketch, why this scales)

A 237x237-bit significand multiplier decomposes into a grid of
sub-multipliers. Choose the granule at the fp32 significand (24x24);
the full array is a 10x10 granule grid (240x240) with mode-gated
cross-granule partial products:

- fp32 mode: 8 granules run independently, cross-terms gated off, 8
  results per half-beat.
- fp64 mode: 2x2 granule clusters fuse (48>=53? no - fp64 needs 53
  bits: 3x3 granules = 72x72 covers it; the exact tiling is the v1
  design work, including whether DSP48E2 27x18 tiling beats a uniform
  24x24 granule on this fabric), 4 results.
- fp256 mode: the whole array plus the accumulation tree, 1 result.

The alignment/normalize/round tail is shared, with lane-sliced flag
and exception plumbing. VU35P carries 5952 DSP48E2 slices; a full
uniform 237x237 product costs ~140 DSPs unfractured (10x14 tiling of
27x17 unsigned use), so the array is affordable and Karatsuba can cut
it further at the cost of the clean fracture geometry - a measured
trade for v1, not a guess to make now.

## HBM

`hw/link.cfg` maps the single master to HBM[0:3] (one pseudo-channel
group). The U50 HBM subsystem exposes 32 pseudo-channels; scaling
plans (multiple CUs, per-CU PC groups, the RAMA IP for scatter
workloads) belong to the orbit-engine milestone, which is when access
patterns stop being three linear streams.

## Platform notes

Default platform: `xilinx_u50_gen3x16_xdma_5_202210_1` (override
`PLATFORM=` on make). The U50C ships against U50C-specific platforms
in some XRT generations - `xbutil examine` names what the card
actually runs, and docs/BRINGUP.md walks through checking before the
first link.
