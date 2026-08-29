# Architecture

The Coordinated Fusion Tile (CFT): a fusedMultiplyAdd-centric compute
tile whose precision scales along the IEEE binary interchange ladder -
one datapath architecture serving 8x fp32 lanes today and 1x fp256 at
the top, with fp64/fp128 rungs and a true fractured array on the
roadmap. Target platform: AMD/Xilinx Alveo U50/U50C (VU35P, 8 GB
HBM2), Vitis RTL kernel flow, XRT host runtime.

## v0 block structure

```
                     s_axi_control (AXI4-Lite)
                            |
                       +---------+
                       | cft_csr |  ap_ctrl_hs + args + FLAGS/MAGIC/VERSION
                       +---------+
                            |  start/done/cfg
                       +------------+
   m00_axi (AXI4-512) <-> cft_engine |  beat FSM, A/B/C reads, D write
                       +------------+
                          |       |
                 256-bit half-beats, 2 per beat
                          |       |
              +-----------+       +------------+
              | 8x cft_opmux+fpfma |  | 1x cft_opmux+fpfma |
              |    (8,23) lanes    |  |     (19,236)       |
              +--------------------+  +--------------------+
```

- **cft_fpfma** - the parameterized FMA core. One combinational
  datapath implementing unpack, exact product, grid alignment with a
  sticky marker, sign-magnitude add, normalize, single RNE rounding,
  after-rounding tininess, pack, flags. Written to be read line-by-line
  against `python/cft_golden/softfloat.py`; the grid/marker safety
  argument is in the header comment.
- **cft_fpfma_pipe** - fixed-latency wrapper (LATENCY=3 in v0): input
  register, core, output registers. No stalls; ordering is structural.
- **cft_opmux** - operand steering: ADD/SUB/MUL are the FMA core with
  steered operands (b:=1.0, c sign-flip, signed-zero c). The table
  lives in three places that must move together: this module,
  `softfloat.steer`, and this document.
- **cft_csr** - AXI4-Lite slave, Vitis ap_ctrl_hs protocol, argument
  registers, and the read-only FLAGS/MAGIC/VERSION block.
- **cft_engine** - the v0 sequencer: per 512-bit beat, read A, B, C,
  push two 256-bit half-beats through the selected bank, collect
  through a latency-matched tag delay line, write D, advance.

## Datapath geometry

The tile's compute width is a **half-beat: 256 bits** - 8 fp32 lanes
or 1 fp256 operand. An AXI beat (512 bits) is two half-beats,
processed back-to-back. This is the shape the fractured array keeps in
v1: one physical array that computes 1x fp256, 2x fp128, 4x fp64, or
8x fp32 per half-beat, precision selected per run.

Elements per beat: fp32 -> 16, fp256 -> 2.

## CSR map (== hw/kernel.xml == cft_csr.sv)

| offset | reg | access | contents |
|---|---|---|---|
| 0x00 | CTRL | RW | [0] ap_start [1] ap_done (clear-on-read) [2] ap_idle [3] ap_ready |
| 0x04 | GIER | RW | storage only; no interrupt exported in v0 |
| 0x08 | IER  | RW | storage only |
| 0x0C | ISR  | RO | 0 |
| 0x10 | MODE | RW | [3:0] op: 0 fma, 1 add, 2 sub, 3 mul; [7:4] precision: 0 fp32x8, 3 fp256 (1=fp64, 2=fp128 reserved); [31:8] reserved, write 0 (a rounding-mode field will land here) |
| 0x18 | N    | RW | element count, 64-bit |
| 0x20 | A_PTR | RW | 64-bit HBM byte address |
| 0x28 | B_PTR | RW | 64-bit |
| 0x30 | C_PTR | RW | 64-bit |
| 0x38 | D_PTR | RW | 64-bit |
| 0x40 | FLAGS | RO | sticky {inexact,underflow,overflow,divzero,invalid} of the last run; cleared at ap_start |
| 0x44 | MAGIC | RO | 0x43465430 "CFT0" |
| 0x48 | VERSION | RO | 0x00000100 |

## Host contract

- Buffers 64-byte aligned (XRT BOs are), elements little-endian,
  arrays dense.
- **N must be a whole number of beats**: a multiple of 16 for fp32, 2
  for fp256. v0 processes whole beats only; hosts pad the tail (any
  padding values are computed and written to D's padding region -
  harmless, and their flags DO join the sticky OR, so pad with zeros,
  not junk, when flags matter).
- Operand semantics per op: FMA uses A,B,C; ADD/SUB use A,C (B
  ignored); MUL uses A,B (C ignored). D = op result. SUB computes
  A - C.
- One run per ap_start; poll CTRL for ap_done (XRT does this
  natively); read FLAGS before the next start if you want them.

## AXI behaviour (v0, deliberately naive)

Single ID, single outstanding transaction, ARLEN/AWLEN=0 (one 64-byte
beat per burst), INCR, full write strobes. Per beat the engine costs
three read round-trips, ~LATENCY+2 compute cycles, and one write
round-trip - correctness and auditability first. The v1 engine adds
long bursts, outstanding transactions, and stream-overlapped compute
behind the same CSR contract; numerics do not change when it does.

Throughput honesty: v0 at, say, 100 MHz with ~40-cycle beats is on the
order of tens of MB/s per stream - a bring-up vehicle, not a product.
The architecture's headroom is the point: 8 lanes x 300 MHz is 2.4
GFMA/s fp32 per tile once the engine stops being polite, and tiles
replicate as CUs.

## Timing expectation (v0)

The behavioural core is one deep combinational cloud; it will not
close 300 MHz. Bring-up strategy: reduced kernel clock first (v++
`--kernel_frequency` / `--clock` options), which changes nothing about
results - determinism is clock-independent by construction. The v1
core pipelines the product array, alignment, add, LZC, and round into
separate stages behind the same `cft_fpfma_pipe` ports.

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
