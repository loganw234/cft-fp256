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

- **cft_fpfma_pipe** - the parameterized 16-stage FMA core (v1):
  staged significand multiplier (24-bit chunk columns + four
  registered tree levels), coarse/fine alignment with the sticky
  marker, split-carry add, per-64 LZC normalize, a single rounding
  under the operation's own 754 attribute
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
- **cft_simpleops** - the operations that are not arithmetic: `abs`,
  `negate`, `copySign` (754 5.5.1) and the four min/max forms (9.6).
  A sign bit and a magnitude comparison, computed combinationally.
  Its answer reaches the output through the pipe's precomputed-result
  sideband - the same path infinities and NaNs already take - so it
  arrives at exactly the arithmetic latency with no delay line of its
  own, and one bypassed operation can be in flight beside a computed
  one on every cycle.
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
| 0x10 | MODE | RW | [7:0] op (see the opcode table below); [11:8] precision: 0 fp32x8, 1 fp64x4, 2 fp128x2, 3 fp256 - issue only precisions set in CAPS; [14:12] rounding attribute, RISC-V frm encoding: 0 rne, 1 rtz, 2 rdn, 3 rup, 4 rmm (5-7 reserved, behave as rne; ignored by the non-arithmetic opcodes); [31:15] reserved, write 0 |
| 0x18 | N    | RW | element count, 64-bit |
| 0x20 | A_PTR | RW | 64-bit HBM byte address |
| 0x28 | B_PTR | RW | 64-bit |
| 0x30 | C_PTR | RW | 64-bit |
| 0x38 | D_PTR | RW | 64-bit |
| 0x40 | FLAGS | RO | sticky {inexact,underflow,overflow,divzero,invalid} of the last run; cleared at ap_start |
| 0x44 | MAGIC | RO | 0x43465430 "CFT0" |
| 0x48 | VERSION | RO | 0x00000410 (v0.4.1: opcode-group discovery in CAPS) |
| 0x4C | CAPS | RO | what this bitstream implements. [3:0] precision bitmask, bit p = MODE precision p (full tile 0xF). [15:8] opcode-group bitmask: 8 arithmetic, 9 sign, 10 min/max, 11 predicate+select, 12 integer, 13 reduction, 14 divide/sqrt, 15 conversion (the last three reserved and currently clear). Groups rather than a bit per opcode, because opcodes arrive in groups and a 256-bit register is one nobody keeps current |
| 0x50 | STATUS | RO | sticky bus faults of the last run, cleared at ap_start: [0] a read response was not OKAY, [1] a write response was not OKAY, [2] a read burst delivered the wrong beat count. **Non-zero means the D buffer must not be trusted** |

### Opcodes (MODE[7:0])

| code | op | group | notes |
|---|---|---|---|
| 0 | `fma` | arithmetic | `a*b + c`, one rounding |
| 1 | `add` | arithmetic | steered: `b := 1.0` |
| 2 | `sub` | arithmetic | steered: `b := 1.0`, `c` sign-flipped |
| 3 | `mul` | arithmetic | steered: `c := signed zero` |
| 4 | `abs` | sign | quiet; preserves NaN payloads |
| 5 | `neg` | sign | quiet |
| 6 | `copysign` | sign | magnitude of `a`, sign of `b` |
| 7 | `min` | min/max | NaN propagates; `min(+0,-0)` is -0 |
| 8 | `max` | min/max | |
| 9 | `minnum` | min/max | returns the number when one operand is NaN |
| 10 | `maxnum` | min/max | |
| 11 | `select` | data | `c` non-zero ? `a` : `b`; moves NaNs intact |
| 12 | `cmplt` | predicate | yields 1.0 or +0.0 |
| 13 | `cmple` | predicate | |
| 14 | `cmpeq` | predicate | |
| 16 | `iand` | integer | the encoding as a W-bit unsigned word |
| 17 | `ior` | integer | |
| 18 | `ixor` | integer | |
| 19 | `iadd` | integer | wraps mod 2^W |
| 20 | `isub` | integer | |
| 21 | `ishl` | integer | count from `b` mod W |
| 22 | `ishr` | integer | logical, never arithmetic |
| 23 | `icmplt` | integer | unsigned; yields 1.0 or +0.0 |

Opcode 15 and everything from 24 up are unassigned, and return
the canonical quiet NaN with invalid raised - in hardware and in the
golden model alike. The field was four
bits until the integer group needed a fifteenth opcode; it is a byte
now so that divide, square root, conversions and the reductions have
somewhere to go without moving the precision and rounding fields again.

**There is no `cmpgt` or `cmpge`, and none is needed.** The engine
reads three independent pointers, so `a > b` is `cmplt` with the A and
B buffers swapped, for free. Only orderings unreachable by swapping
earn an opcode.

The predicates deliberately yield a float rather than a condition
code: the result has to live in the same arrays as everything else and
be consumable by `select`. Together, `cmp*` and `select` are branchless
conditional code, which is what the atlas det library needs from
hardware far more than it needs a transcendental.

## Host contract

- **Buffers must be 32-byte aligned** - one beat. This is the single
  normative statement of the requirement; XRT buffer objects are 4 KB
  aligned, so it costs a host nothing. The engine's burst sizing
  assumes it, and an unaligned pointer whose low 12 bits exceed 4064
  yields a zero-length burst and hangs the run rather than failing
  loudly, so do not treat it as advisory.
- Elements little-endian, arrays dense.
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
- **Operand semantics per op - read this before changing an
  opcode.** The convention is not uniform, because ADD and SUB are
  steered FMAs (`a*1 + c`) while everything else takes its operands
  in order. A host that lays out buffers for `add` and then switches
  to `min` reads the wrong array and gets plausible numbers.

  | op | reads | result |
  |---|---|---|
  | `fma` | A, B, C | `a*b + c` |
  | `add` | **A, C** (B ignored) | `a + c` |
  | `sub` | **A, C** (B ignored) | `a - c` |
  | `mul` | A, B (C ignored) | `a * b` |
  | `abs`, `neg` | A only | |
  | `copysign`, `min`, `max`, `minnum`, `maxnum` | A, B | |
  | `cmplt`, `cmple`, `cmpeq`, `icmplt` | A, B | 1.0 or +0.0 |
  | all other integer ops | A, B | |
  | `select` | A, B, C | `c != 0 ? a : b` |

- One run per ap_start; poll CTRL for ap_done (XRT does this
  natively); read FLAGS **and STATUS** before the next start - *if
  your host language can*. See the caveat below. A clean
  STATUS is what makes a bit-exactness claim mean anything: without
  it, a run that computed on data the memory system never delivered
  is indistinguishable from one that succeeded.
- **Known gap: pyxrt cannot read the status CSRs.** Checked on both
  XRT 2.14.354 (era emulation) and 2.19.194 (2025.1, what the card
  will run): `pyxrt.kernel` exposes only `group_id` and the CU access
  modes - no `read_register`, and there is no `pyxrt.ip` class. So
  FLAGS, STATUS and CAPS are reachable from the C++ API and from
  cocotb, but **not** from the Python host example. What that costs
  is diagnosis, not correctness: the D-buffer comparison against the
  golden model is the actual gate, and a bus fault corrupts D, so a
  fault still fails the run - it just fails as "wrong answer" rather
  than "the memory never delivered". Closing it properly means giving
  the kernel a small status output buffer so the sticky words come
  back through the AXI master like everything else, readable by any
  host language. Until then `vector_fma.py` prints a warning rather
  than pretending the check ran.
- **Argument registers must be left alone while a run is in flight.**
  The engine snapshots everything it needs at ap_start - op,
  precision, rounding attribute, N and all four pointers - so a
  mid-run write cannot corrupt the run in progress. That snapshot is
  the guarantee; the registers are still yours to reprogram for the
  next run as soon as ap_done is observed.

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

The 16-stage core closes ~232 MHz fp32 / ~148 MHz fp256 out of
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
