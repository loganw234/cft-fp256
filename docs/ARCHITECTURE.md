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
                            |  start/done/cfg; MODE[15] names the run's owner
              +-------------+--------------+
              |                            |
    +-------------------+           +-----------+
    | cft_engine_stream |           |  cft_seq  |  on-chip programs,
    +-------------------+           +-----------+  index-addressed deposits
     m_axi_a/b/c/d (AXI4-256)        m_axi_a/d - the same two masters,
     beat FSM, A/B/C reads,          handed over by MODE[15]
     D write, reduction accumulator
              |                            |
              +-------------+--------------+
                            |
        one per-issue request: valid, op, rnd, prec, a, b, c
                            |
                      +-----------+
                      | cft_lanes |  ONE array per tile, owned by cft_krnl
                      +-----------+
                            |
                    256-bit beat, one per element group
                            |
        +-----------+------------+-------------+-------------+
        | 8x (8,23) | 4x (11,52) | 2x (15,112) | 1x (19,236) |
        | fp32 bank | fp64 bank  | fp128 bank  | fp256 unit  |
        +-----------+------------+-------------+-------------+
              each lane: cft_opmux -> cft_fpfma_pipe
              optional, all off by default: FUSE_MUL / FUSE_NORM /
              FUSE_ALIGN - one shared multiplier or shift ladder in
              place of the per-lane ones
```

- **cft_fpfma_pipe** - the parameterized 15-stage FMA core (v1):
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
  `negate`, `copySign` (754 5.5.1), the four opcode forms of min/max
  (9.6; the magnitude four are host operations, docs/HOSTAPI.md), the
  quiet predicates + `select`, and the integer/bitwise group. A sign
  bit, one magnitude comparison and one shifter, computed
  combinationally - and proven bit-identical to its pre-rewrite self
  over all 2^104 inputs by the formal gate. Beside it, **cft_seedop**
  answers the divide/sqrt seed opcodes (26/27) from two model-derived
  ROMs.
  Its answer reaches the output through the pipe's precomputed-result
  sideband - the same path infinities and NaNs already take - so it
  arrives at exactly the arithmetic latency with no delay line of its
  own, and one bypassed operation can be in flight beside a computed
  one on every cycle.
- **cft_lanes** - the tile's **one** beat-wide ALU array: eight fp32 /
  four fp64 / two fp128 lanes or one fp256 unit, each lane the recipe
  above (`cft_opmux` into `cft_fpfma_pipe`, with `cft_simpleops` and
  `cft_seedop` merged through the pipe's bypass sideband), plus the
  optional fused ladders, which live here because they are properties
  of the array rather than of whoever drives it. `cft_krnl` owns the
  single instance. `cft_engine_stream` and `cft_seq` each present a
  per-issue request - valid, opcode, rounding attribute, precision,
  three operands - and MODE[15], registered at start, selects whose
  request reaches the array. **No arbitration is needed, because the
  two never run at once**, so the sharing is a static mux and costs one
  mux level between registered operands and the array's steering.
  Both drivers carry an `OWN_LANES` parameter, default 1 so their unit
  benches still elaborate a private array; `cft_krnl` passes 0.

  Until 2026-09-01 the sequencer had a private second copy of the
  array (`cft_seq_lanes`, a documented v1 deviation). It was benched
  and it worked; what it had never been was priced at the kernel. The
  configuration table below is what that cost, and it is why this
  module exists - "the sequencer introduces no arithmetic, only a
  schedule" is now a statement about the netlist rather than a claim
  about two copies of the same source.
- **cft_seq** - the orbit sequencer: on-chip programs over the
  existing opcodes, entered by MODE[15], reading its image from
  PROG_PTR and writing per-lane deposits and counts. It borrows the A
  and D masters from the streaming engine and issues into the same
  `cft_lanes`. docs/SEQUENCER.md is the design and
  `python/cft_golden/seq.py` the definition of correct; benched
  bit-exact against it, hw_emu and silicon still ahead.
- **cft_csr** - AXI4-Lite slave, Vitis ap_ctrl_hs protocol, argument
  registers, and the read-only FLAGS/MAGIC/VERSION/CAPS block.
- **cft_engine_stream** - the v1 streaming sequencer the kernel
  instantiates: burst reads into three per-stream FIFOs (arbitrated
  a > b > c, one AR outstanding, 4KB-safe), one beat issued per cycle
  to `cft_lanes` at the precision MODE selects, whenever operands and
  result space exist, collection through a latency-matched delay line
  into a D FIFO, index-order burst writes out. Read, compute and write
  overlap across beats; issue and write order stay total, so
  determinism is untouched. All four banks share the one delay line
  because every `cft_fpfma_pipe` instance has the same structural
  depth regardless of width. `cft_reduce_acc`, the streaming reduction
  accumulator, hangs off the same issue point: its adds ride the
  shared request as `fma(x, 1.0, y)` through lane 0, with its operands
  **registered** on the way in and `ADD_LATENCY` set to `LATENCY + 1`
  to match. That register is not tidiness - see the timing section.
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

### Geometry parameters

`cft_krnl` takes `EN_FP64/EN_FP128/EN_FP256` to drop rungs and
`BEAT_BITS` to narrow the beat itself. What remains is advertised in
CAPS and is bit-identical to the full tile on the rungs it carries.

**Lane counts are not independent parameters.** A beat holds
`BEAT_BITS/width` elements of each format, so the beat width sets all
four at once: 256 gives 8/4/2/1, and 64 gives 2/1/-/-. That is the
honest shape - the beat is simultaneously the compute width and the
memory width, and they cannot disagree without the width converter
this design exists to avoid.

A format wider than the beat would need multi-beat elements and an
assembly buffer, so the guards refuse it: narrowing the beat means
dropping the wide rungs with it. Both directions are bounded -
`BEAT_BITS > 256` is refused too, because the fp256 bank is a single
instance rather than a loop and would silently compute only the low
element.

| configuration | beat | lanes (32/64/128/256) | LUT | for |
|---|---|---|---|---|
| full tile | 256 | 8 / 4 / 2 / 1 | **139,404 OOC** (292 DSP); 123,599 with the fused ladders on (277 DSP) | Alveo; 256 is the HBM pseudo-channel width |
| half tile | 128 | 4 / 2 / 1 / - | ~44k estimated, **pre-sequencer** | see ROADMAP's open-core sizing |
| quarter tile | 64 | 2 / 1 / - / - | ~20k estimated, **pre-sequencer** | an Alchitry Au conformance node; a chiplet trading lanes for deposition buffer |

The full-tile figure moved after this table was written: 129,708 with
the seed ROM as case tables and **123,420** with the round stage
precomputed (9f73107, retimed) - the Timing section below has the ladder.

Both full-tile numbers are measured out of context, Vivado 2022.2,
xcu50-fsvh2104-2-e, 135 MHz, on the tile as it now stands: one
`cft_lanes` array, and the sequencer in it. Per module, with the
ladders off: `u_lanes` 105,379, `u_seq` 26,586, `u_engine` 6,053,
`u_csr` 818.

**Both trimmed rows are estimates that predate `cft_seq`**, and they
are left marked rather than rescaled, because `cft_krnl` instantiates
the sequencer unconditionally - a quarter tile carries one, and no
measurement of that build exists here. The full-tile row is the one to
reason from until someone synthesises the others.

The two full-tile numbers are the same RTL: FUSE_NORM and FUSE_ALIGN
(cft_krnl parameters, **default off**) replace the thirty per-lane
alignment and normalise shifters with two segmented 720-bit ladders,
equivalence-proven per lane in the 2026-08-31 campaign (-18.6k LUT
against the pre-sequencer tile, 116,932 -> 98,310; docs/ROADMAP.md
carries that table) and now through the whole kernel by `make
krnlfused` / `make krnlplain`. In the tile that exists they are worth
139,404 - 123,599 = **15,805 LUT**, and they are off anyway: out of
context they leave +0.097 ns of slack against ladders-off's +0.307,
and a shell build at 135 MHz is what settled it. Sharing stays
per-build - the Alveo image declines it, an area-bound open build
takes it - and `hw/package_kernel.tcl` strips user parameters, so a
bitstream carries whatever the RTL default is and nothing else.
All three ladders self-gate on the full-tile geometry, so a quarter
tile ignores them either way.

**The width is a real constraint, not a preference, and the sequencer
tightened it.** A full tile was 139,404 LUT and 292 DSPs with the
ladders off when this was written, 123,599 and 277 with them on; the
ladders-off tile has since come down to 123,420 (the Timing section). ROADMAP.md's part-by-part
arithmetic has its anchor at a measured 138,083-LUT tile, which it
records as 103% of an Artix-7 200T - so the 200T is about 134,000
LUTs, the shipping ladders-off tile at 139,404 is over it, and the
ladders-on tile at 123,599 is about 92% of it. That is the case the
ladders were kept parameterised for: not Alveo, where they cost
timing, but the part where footprint is the whole objective. The DSP
count still wants a Kintex either way. This is why BEAT_BITS exists and
why it is tested rather than declared.

The quarter tile is not hypothetical - `tb/test_krnl_quarter.py` runs
it against the same golden model, so the parameter is proven rather
than declared. A parameter nothing instantiates is a parameter that
does not work yet.

## CSR map (== hw/kernel.xml == cft_csr.sv)

| offset | reg | access | contents |
|---|---|---|---|
| 0x00 | CTRL | RW | [0] ap_start [1] ap_done (clear-on-read) [2] ap_idle [3] ap_ready |
| 0x04 | GIER | RW | storage only; no interrupt exported in v0 |
| 0x08 | IER  | RW | storage only |
| 0x0C | ISR  | RO | 0 |
| 0x10 | MODE | RW | [7:0] op (see the opcode table below); [11:8] precision: 0 fp32x8, 1 fp64x4, 2 fp128x2, 3 fp256 - issue only precisions set in CAPS; [14:12] rounding attribute, RISC-V frm encoding: 0 rne, 1 rtz, 2 rdn, 3 rup, 4 rmm (5-7 reserved, behave as rne; ignored by the non-arithmetic opcodes); **[15] SEQUENCER RUN** - this run belongs to `cft_seq` and the op field is ignored, because the program says what to compute and carries a rounding attribute on every instruction. Precision still applies and is still refused the same way: a program is compiled for one format (its constants are format-width values), so a rung the build lacks is exactly as unrunnable here as it is for an elementwise op. CAPS[15] says whether there is a sequencer at all; [31:16] reserved, write 0 |
| 0x18 | N    | RW | element count, 64-bit |
| 0x20 | A_PTR | RW | 64-bit HBM byte address |
| 0x28 | B_PTR | RW | 64-bit |
| 0x30 | C_PTR | RW | 64-bit |
| 0x38 | D_PTR | RW | 64-bit. On a sequencer run this is the DEPOSIT buffer, `n * max_deposits` elements rather than `n` |
| 0x40 | FLAGS | RO | sticky {inexact,underflow,overflow,divzero,invalid} of the last run; cleared at an ACCEPTED ap_start - a refused start (STATUS[3]) leaves them untouched, because a refusal is not a run |
| 0x44 | MAGIC | RO | 0x43465430 "CFT0" |
| 0x48 | VERSION | RO | 0x00000600. **Guards the REGISTER MAP, not the feature set** - a host accepts a SET of known versions and lets CAPS decide what an image can do. One accepted value would orphan a still-good bitstream every time a feature landed, which nearly happened when reductions bumped 0x410 to 0x500 and the card-day images were already built at 0x410. 0x600 is the first bump that GREW the map rather than only adding a capability: PROG_PTR and CNT_PTR exist at 0x54 and 0x5C, and two kernel arguments exist that did not. The older versions stay accepted because their registers are still read correctly; what they cannot do is run a program, and libcft refuses that outright rather than binding an eight-argument call to a six-argument xclbin |
| 0x4C | CAPS | RO | what this bitstream implements. [3:0] precision bitmask, bit p = MODE precision p (full tile 0xF). [15:8] opcode-group bitmask: 8 arithmetic, 9 sign, 10 min/max, 11 predicate+select, 12 integer, 13 reduction, 14 divide/sqrt, 15 sequencer (13 set from VERSION 0x500 onward, 14 with the seed opcodes, 15 from 0x600). **Bit 15 read "conversion - reserved" until 0x600.** The conversions landed as library entry points - `cft_convert`, the integer forms, the rest of clause 5 - composed from opcodes that already exist, so the group will never take a MODE opcode and the bit was never going to be spent on it. A group bit nothing can ever set is a reserved bit; the sequencer is a real thing a host must ask about before it writes PROG_PTR, so it takes the bit. **Bit 15 means MODE[15] reaches a `cft_seq`,** and nothing about which programs it will accept - the on-chip instruction, constant and deposit capacities are the tile's, and a program past them is refused at run time with STATUS[3]. **Bit 13 means opcode 24 only.** The group nominally covers 24 and 25, but `dot` (25) is a host-side composition of `mul` then `sum` - the kernel treats 25 as a reserved opcode and answers with canonical qNaN and invalid raised. A host that reads bit 13 and issues 25 to the tile directly gets that, not a dot product; libcft never does, because `cft_reduce` decomposes it. **Bit 14 means opcodes 26 and 27** - `recip_seed`/`rsqrt_seed`, the quiet table lookups the composed divide and square root start from. The full operations are not single opcodes at all: they are FMA sequences the host library issues (python/cft_golden/sequences.py is the specification), and bit 14 is what tells it the starting points exist in this bitstream. Groups rather than a bit per opcode, because opcodes arrive in groups and a 256-bit register is one nobody keeps current |
| 0x50 | STATUS | RO | sticky faults of the last run, cleared at an accepted ap_start: [0] a read response was not OKAY, [1] a write response was not OKAY, [2] a read burst delivered the wrong beat count, [3] the run was REFUSED, [4] DEPOSIT OVERFLOW on a sequencer run. **[3] covers two refusals with one answer.** Either MODE selected a precision this build does not implement (or a code above 3), in which case neither engine started and no memory was touched at all; or a sequencer run's program image failed the tile's own header check - bad magic, a format that is not MODE's, more instructions, constants or deposit slots than the tile holds. The second kind may have READ the image before refusing it, but it wrote nothing and computed nothing, and a host's response to both is the same: the run did not happen and the output buffer holds what it held. `ap_done` still asserts either way, so a refusal costs a register read rather than a timeout, and FLAGS is left at the previous run's value because a refusal is not a run. CAPS[3:0] says in advance which precisions exist and CAPS[15] whether there is a sequencer; the refusal is what a host that did not ask gets instead of plausible garbage. **[4] is a report, not a fault** - a lane deposited past the program's `max_deposits`, the excess was dropped, and what fit is correct and reproducible. It is deliberately not an IEEE flag: the five in FLAGS mean what 754 says they mean and "your buffer was too small" is not one of them. It moved here from bit 3 on 2026-09-01, when the precision refusal took that position in silicon-bound RTL and the sequencer's bit had still never crossed a device boundary. **Bits [2:0] non-zero mean the D buffer must not be trusted.** [0] and [1] do not disturb the run - the beat still arrives, so it completes and STATUS is read after. [2] does: withheld beats starve compute, so the engine ABANDONS the run rather than waiting - no new bursts, any committed write burst finished (with stale data if the FIFO ran dry, since AXI4 A3.4.1 permits no way to withdraw it), outstanding reads allowed to land, then `ap_done`. A protocol violation ends as a prompt fault instead of a hang; a slave that stops answering altogether is indistinguishable from a slow one and still belongs to the host's timeout |
| 0x54 | PROG_PTR | RW | 64-bit HBM byte address of the program image - header, constant bank, instruction stream, exactly as `cft_program_load` validated it (docs/SEQUENCER.md). 32-byte aligned. Read by the sequencer at start; ignored when MODE[15] is clear |
| 0x5C | CNT_PTR | RW | 64-bit HBM byte address of the per-lane deposit counts, `n` uint32s, 4-byte aligned. An output rather than a convenience: `+0` is both a legal deposit and the defined value of a slot no lane wrote, so the count cannot be recovered from the deposit buffer |

The last two sit **above** the read-only block rather than beside the
other pointers, and that is not tidiness losing to history. `A_PTR`
through `D_PTR` are `hw/kernel.xml` argument ids 2 to 5, and an id is a
position in every host's kernel call - moving them to open a gap would
silently rebind every existing binary's operands to the wrong ports.
Appending is the only change a shipped argument list can take, so the
sequencer's pointers are ids 6 and 7 at the first free offsets.

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
| 24 | `sum` | reduction | one element out, over the contractual tree (`cft_reduce`, VERSION 0x500) |
| 25 | `dot` | reduction | not separate hardware: the host issues `mul` then `sum`, exact by the contract |
| 26 | `recip_seed` | seed | ~1/a, the divide starting point; quiet, no flags |
| 27 | `rsqrt_seed` | seed | ~1/sqrt(a), the square-root starting point; quiet, no flags |
| 28 | `sumsq` | reduction | sum of round(a[i]*a[i]) over the tree (ABI 0.6) |
| 29 | `sumabs` | reduction | sum of \|a[i]\| over the tree (ABI 0.6) |

Opcode 15 and everything from 30 up are unassigned, and return
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
- **A SEQUENCER run (MODE[15]) takes N differently.** N is the
  caller's real element count, not a padded one: a lane whose index is
  at or beyond it starts INACTIVE, deposits nothing and gets no count,
  so the tail of the deposit and count buffers is untouched. The
  buffers still have to hold whole beats, because the masters move
  whole beats - the arithmetic simply never reaches the padding. This
  is a real difference from `cft_run`, where a zero-filled tail is
  harmless because every opcode is quiet on zeros; a program is
  arbitrary, and no padding value stays quiet through thirty
  iterations of an unknown map (docs/SEQUENCER.md).
- Read CAPS once at open: bit p set means MODE precision p is
  implemented in this bitstream. The full Alveo tile reads 0xF;
  trimmed open-core tiles clear what they dropped. Issuing a
  non-advertised precision is undefined (no arithmetic hazard - the
  run completes - but D's contents are meaningless). Bit 15 says
  whether MODE[15] reaches a sequencer at all; without it, PROG_PTR
  and CNT_PTR may not exist either, and VERSION is what says so.
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
  next run as soon as ap_done is observed. **MODE[15] is part of the
  snapshot** and has to be: it selects which engine owns the shared A
  and D masters, so reading it live would let a mid-run write hand
  them over partway through a burst - a corrupted run and an AXI
  protocol violation together.

## AXI behaviour (v1 streamer)

**Four masters, one per stream.** `m_axi_a`, `m_axi_b` and `m_axi_c`
are read-only; `m_axi_d` is write-only. Vivado infers the direction
from the channels present, so the interconnect never builds a write
path for an operand stream - four half-duplex masters cost less than
one full-duplex master would suggest.

Single ID per master, INCR bursts up to 16 beats (512 B), never
crossing a 4KB boundary, full write strobes. Up to `AR_DEPTH` (4)
bursts in flight per stream into 128-beat FIFOs; writes drain the
result FIFO in full bursts (the tail is always fully buffered, so
short final bursts need no special case).

Both of those are the same fix. The design used to share one 256-bit
port between three operand reads and one result write, and steady
state costs 4 transfers per beat while a port retires one per cycle:
~4.4 cycles/beat measured, however fast the arithmetic ran. The
arithmetic pipe accepts a beat every cycle. Splitting the port is what
lets it - but a dedicated port alone is not enough, because with a
single outstanding AR the reader waits out the full memory latency
after every RLAST, and a 16-beat burst followed by a ~60-cycle bubble
is ~4.8 cycles/beat, which is where it started. Pipelining the ARs is
what converts four ports into four times the throughput.

**Measured: 1.25 cycles/beat, against the shared port's ~4.4.** That
is a 3.5x, and it is a simulation number taken against cocotbext-axi's
memory model - which is cooperative in exactly the way a real HBM
controller is not obliged to be, so it is a ceiling rather than a
promise. What it does settle is that the port was the bottleneck and
splitting it removed that bottleneck; where the number lands on
silicon is a card-day measurement, and CARDDAY.md step 6 is where it
gets taken.

FIFO space is reserved at AR time, not at R time. Two bursts in flight
can together exceed the free space each looked at separately, and the
overflow would corrupt operands rather than stall - so a per-stream
`reserved` count tracks beats promised by in-flight ARs, and every
free-space test subtracts it. That reservation is also what makes
RREADY safe to tie high: the engine never asks for a beat it has
nowhere to put.

hw/link.cfg gives each master its own HBM pseudo-channel group, and
the quad gives all sixteen their own. Four masters sharing one group
would relocate the bottleneck rather than remove it.

**Determinism is untouched, and the reason is worth stating because
"four memory ports" sounds like it should matter.** It does not. The
contract rests on the single compute issue point, which pops all three
operand FIFOs together in index order, and on the single writer, which
emits in index order. Neither changed. The streams may now run ahead of
each other in the memory system by arbitrary amounts; compute still
consumes beat i of all three before beat i+1 of any. Flags remain an
order-free OR.

The naive engine remains in rtl/ as the auditable reference for the
same CSR contract.

## Timing (v1, measured)

The 15-stage core closes ~232 MHz fp32 / ~148 MHz fp256 **out of
context** (fp64/fp128 land between; QoR numbers recorded in
ROADMAP.md).

**In the shell, which is the number that matters, the ceiling is
~141 MHz and it has moved.** The critical path is the round stage -
the 237-bit attribute-directed increment, S12 into S13 - and it is
about two-thirds routing, so it is a placement problem as much as a
logic one.

*2026-09-02, a correction and two results.* The DSP chain on every
routed critical path was never the significand multiplier: it was the
seed ROM's index multiply, `SEED_P[i*18 +: 18]` built as a DSP48 and
a 9216-bit shifter (docs/ROADMAP.md, "The DSP on the critical path
was never the multiplier"). Retiming closes a single at 135 MHz at
+0.045 - exactly what the same tree closes without it - and does not
close a quad (-0.141 against -0.113 unretimed): both leave placement
at +0.055 and lose the margin in routing, which is wire. The ROM is a
case table now and the round stage's arithmetic sits in S12; what is
left at the head of the list is S10->S11, the LZC-fed coarse
normalise. The quad from that tree is the open question.

| commit | ask | routed WNS | implied path delay |
|---|---|---|---|
| 1cab0c3 (sweep) | 145 MHz | **+0.055** closes | 6.842 ns |
| 1cab0c3 (sweep) | 175 MHz | -0.562 fails | 6.276 ns |
| 53bbba7 (2026-08-29) | 145 MHz | **-0.165** fails | 7.062 ns |
| 53bbba7 | 130 MHz | **+0.055** closes | 7.637 ns |
| a5cce4e, round-stage restructured | 145 MHz | **+0.055** closes | 6.842 ns |

The design lost about 0.22 ns between those two points, and the work
in between is the reason: the integer and bitwise group added eight
opcodes and widened `MODE`'s opcode field from four bits to a byte,
and the unassigned-opcode handling, CAPS discovery and elaboration
guards each added a little more. None of it touched the round stage,
but all of it added logic and congestion to a path that is two-thirds
wire.

So **145 MHz closed for the design that was measured, not for the
design that exists**, and a sweep result ages as soon as the RTL
changes.

**And then it closed again.** The round stage now selects between
`kept` and `kept+1` rather than adding the round bit to it, which
takes a 238-bit ripple carry off the end of the path and hides it
behind the guard/sticky reduction that was already running. Same
latency, same stage count, same arithmetic - the 111,278-vector RTL
suite agrees bit for bit - and the 0.22 ns comes back exactly: 145 MHz
goes from -0.165 to +0.055.

That is worth reading twice, because the last time this design was
restructured for timing (the S11 split) the out-of-context proxy
promised 2% and the shell delivered a regression. The difference is
not that the reasoning was better; it is that this was measured in the
shell before being believed.

Two cautions, both learned the expensive way and written up in
ROADMAP.md. Read the **path delay, not the slack**: Vivado stops
optimising once the asked clock is met, so a passing run understates
what the design can do and only a failing run reveals the ceiling.
And **do not predict shell timing from an out-of-context core run** -
on the one occasion the two were compared directly, the OOC proxy
reported a 2% improvement for a change that was a regression in the
shell.

### The shared array's own path (2026-09-01)

Everything above was measured on a tile with one driver and no
sequencer in it. The restructuring that gave the tile one `cft_lanes`
array between two drivers was measured out of context at 135 MHz,
Vivado 2022.2, xcu50-fsvh2104-2-e:

| tile configuration | LUT | WNS (OOC) |
|---|---|---|
| private arrays (before this work) | 288,764 | -0.065 ns |
| one shared array, ladders off | 162,482 | -0.065 ns |
| + the sequencer's control diet | 139,404 | **+0.307 ns** |
| + fused ladders on | 123,599 | +0.097 ns |
| + seed ROM as case tables (eb8ef2a), retimed | 129,708 | +2.126 ns |
| + round stage precomputed in S12, window narrowed (9f73107), retimed | **123,420** | +2.222 ns |

Then a single tile was linked at 135 MHz with the ladders on, and it
**missed: WNS -0.577 ns, 776 failing endpoints.** The worst path was
not the ladder the build existed to test:

    u_engine/u_reduce/dly_lvl_reg[14][0]
      -> u_lanes/g_lane32[0].u_fma/s0_byp_d_reg[15]
    25 levels, through a DSP cascade

That is the restructuring's own regression, and it is the reason the
reduction accumulator's operands are registered. While the accumulator
fed lane 0 of the engine's *private* array, its operands went straight
to the pipe's `a`/`c` ports - past `cft_opmux` (a passthrough for FMA
anyway) and past `cft_simpleops` entirely. Merging both drivers onto
one operand bus put the accumulator's combinational output onto the bus
that also feeds `cft_simpleops`, and `cft_fpfma_pipe` latches that
block's result into `s0_byp_d` **unconditionally, with no clock
enable** - so every reduction operand had to cross the accumulator's
level decode, its memory read and the whole simpleops mux tree inside
one cycle, whether or not the bypass was selected. One register on the
operands makes the reduce path structurally the elementwise path that
already closes; `ADD_LATENCY` is `LATENCY + 1` so the destination level
still arrives with its sum. Not a numeric change - the tree shape and
the order of every add are fixed by element index, never by timing.

**Two things this file has been asserting for months now have a number
on them.** +0.307 out of context became -0.577 in the shell: a 0.88 ns
swing, in the direction the caution above names, because OOC places the
kernel alone and the shell places it as one compute unit among many.
And sharing a datapath means sharing everything attached to it - the
area win was real, -126k LUT, but the operand bus carried the
accumulator into a combinational block it had never touched, which is
not a coupling an area argument surfaces.

**FUSE_NORM/FUSE_ALIGN are therefore off.** They fit better (123,599
against 139,404, about 75% of the device against 80% for a quad) but
leave +0.097 ns OOC where off leaves +0.307, and this build is the
evidence that a thin OOC margin does not survive the shell. Five points
of device area is not worth a bitstream that does not close.

**Status (2026-09-02).** Ladders off, 135 MHz, in the shell: the
single closes at +0.045 with retiming and at +0.045 without it, and
at +0.050 at 130; the quad has not closed at 135 - -0.113 without
retiming, -0.141 with it - and its worst paths are named in
docs/ROADMAP.md. The tree with the case-table ROM and the S12
precompute is building as a quad on two hosts at 135 with 130 queued
behind; until one of those returns an image, the closed quads are
the 130 MHz pairs already staged for card day. Nothing here claims
silicon.

A reduced clock changes nothing about results - determinism is
clock-independent by construction. The v0 behavioural core (one
combinational cloud, ~65/14 MHz) remains in rtl/ as the readable
reference.

### The leading-zero cone became its own stage (2026-09-07)

`docs/studies/OPT-C-timing.md` took the 2026-09-06 routed fp256 path
apart segment by segment and found that **76% of it was working out how
far to shift**: of 11.550 ns on a Kintex-7 410T at an 80 MHz ask,
8.77 ns was the chunk zero-scan, the priority encode, the chunk mux,
`lzc64` and the `NW-1-msb` subtract; 1.58 ns was the gather into
`cft_lanes`' mode mux; 1.20 ns was the ladder itself. All of it in one
cycle, between `s10_mag` and the S11 registers. Two changes against
that, in one commit, because neither is worth much alone.

**A register boundary inside the cone.** `LATENCY` is **16** edges now,
not 15, and the new S11 holds the cone's answer - the window, the total
shift, the msb, the empty flag - together with every parallel path
beside it: the sign, the exponent anchor, the residue rail and the whole
specials sideband. That last clause is the entire risk of the change,
and it is why the previous attempt to deepen this pipe produced
*garbage, not drift* (docs/ROADMAP.md). `cft_fpfma_pipe` is a
synchronised multi-path pipeline; a stage that delays one path and not
its neighbours hands every operation another one's control word.
Downstream the register names did not move - `s11_*` sits at level 12
now, `s14_*` at level 15 - and the rounding-attribute delay line needed
no edit at all, because its taps have always been written relative to
`DEPTH` rather than as literals.

**Balanced trees where the priority loops were.** The cone is
`cft_lzcone` now, a module at the foot of `rtl/cft_fpfma_pipe.sv`, and
both of its top-down scans - the twelve-chunk resolve and the 64-way
`lzc64` - are log-depth (valid, count) merges folded four wide
(`cft_lz4`). Two levels and three levels respectively, against the
thirteen the routed trace walked. The count comes out of the root
already, so the `NW-1-msb` subtract is gone rather than moved.

What did **not** change is the 64-bit chunk zero-detect, and that is the
interesting part. It was the one piece of the old cone Vivado already
mapped well - five CARRY4 for 0.484 ns and no routing - and it is also
what keeps the module cheap to SIMULATE, a 64-bit reduction being one
vector operation where a tree over the same bits is sixteen nodes. The
study's idea 7 proposes a single tree over the whole 717-bit window;
that version was built, proved bit-identical, and measured **about four
times slower through Icarus** on `tb_fpfma_fp256` (2026-09-07). A
generate pyramid with one continuous assignment per node - the obvious
way to write either - was **twenty-four times** slower on
`tb_fpfma_fp32`, because Icarus schedules each driver of a multiply
driven net as its own event. The whole cocotb matrix runs on Icarus, so
those are not cosmetic numbers. The shipping form keeps the wide cheap
reduction, puts the trees only where the scans were, and costs 1.4x on
the fp256 bench and nothing on fp32.

Bit identity here is proved, not argued. `formal/lzcone.sby` is a
combinational equivalence miter of `cft_lzcone` against
`formal/cft_lzcone_ref.sv` - the priority-loop form frozen at the moment
of the split - at all four window widths; both sides being
combinational, each BMC step is the whole input space at that rung
(2^78, 2^165, 2^345, 2^717). It is part of `formal/run.sh`'s gate.

`cft_seq`'s `NBEATS` did **not** have to move with the depth, and that
is worth recording because docs/ROADMAP.md predicted it would ("LATENCY
16 forces NBEATS to 32"). The parameter's old comment said `>= LATENCY +
1`; the relation is about keeping the pipe full, not about correctness,
because results retire in arrival order and both the issue state and the
drain state run the writeback path. What is structural is the register
file's address shape - the beat index is four bits - so `NBEATS` stays
16 and now carries an elaboration guard saying which of the two
constraints is real.

**What the tip measured, before the change.** Out of context on
`xcu50-fsvh2104-2-e` at a 160 MHz ask, `MUL_PASSES=1` with the ladders
off - the shipping configuration - commit 046adae:

| | tip, 2026-09-07 |
|---|---|
| synthesis WNS | +0.410 (period 6.250) |
| synthesis worst path | **`s10_mag_reg[652]` -> `g_norm_priv.s11_valw_reg[448]`, 25 levels, 5.821 ns** |
| routed WNS | +0.120 |
| routed worst path | `s13_kept_r_reg[11]` -> `d_reg[148]`, 20 levels, **6.111 ns** |
| routed worst 25, by family | 13 round->pack, 8 `u_engine` `op_r`->`w_cnt`, 4 the LZC cone (worst 6.068 ns) |
| routed LUT / FF / DSP / BRAM | 120,839 / 57,644 / 262 / 36 |

The synthesis line is the study's claim, confirmed on a part it was not
measured on: **the single worst path in the whole kernel, before
placement, is the leading-zero cone.** After routing the cone and the
round stage are within 0.04 ns of each other, which is what "the cone
stops being the critical path" has to be measured against - and the
`u_engine` control family sitting third at 160 MHz is the second wall
the study named, appearing in a U50 report for the first time.

The matching branch runs were still on the host's Vivado queue when
this was written; docs/VALIDATION.md's entry for the day says which
returned. Read the path delay, not the slack: both runs above met their
ask, and per docs/BRINGUP.md a passing run tells you the design met
what it was asked for and nothing about headroom.


## The multi-cycle rung (built 2026-09-06: rtl/cft_mulpass.sv)

`MUL_PASSES` on `cft_krnl` iterates the chunk-column multiplier instead
of laying every column side by side, so a tile costs a fraction of the
DSPs at a fraction of the wide rungs' throughput. It is step 3 of
docs/ROADMAP.md's third tier, and its measured result is not the one
that step assumed - see the reading at the end.

**The mechanism.** `cft_fpfma_pipe` decomposes a P x P significand
product into columns of P x 24, one per 24-bit chunk of the multiplier:
one column at fp32, three at fp64, five at fp128, ten at fp256. The
multi-cycle variant builds `ceil(chunks / MUL_PASSES)` of them and walks
the chunks over `NP = ceil(chunks / COLS)` passes, one pass a clock,
folding each pass's tree sum into an accumulator whose low bits shift
out as they become final. **The exact product is integer arithmetic and
no summation order of the same partial products changes an integer**,
so the product handed downstream is bit-identical by construction and
the aligner, normaliser and round stage never learn which array built
it. The geometry lives once, in `rtl/cft_mulgeom.svh`, included by the
four modules that must agree about it; a module that disagrees with the
pipe about the pass count is refused at elaboration rather than
mis-simulated.

**The pacing** is one pipeline enable. In the multi-cycle
configuration `cft_lanes` holds every stage register in the array for
`NP - 1` of every `NP` cycles at the live rung's pass count, so in
enabled-edge terms the pipe is exactly the single-pass pipe and the
delay lines that carry each operation's rounding attribute stay
aligned with it. Only `cft_mulpass` runs on the wall clock in between.
Both issuers - the streaming engine and the sequencer - see the same
enable, so determinism does not depend on the issue cadence: the same
program and the same stream give the same bits at every value of the
parameter, which is what the bench below asserts.

**Throughput per mode**, results per lane per cycle, derived from the
chunk counts above:

| MUL_PASSES | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| 1 (shipping) | 1 | 1 | 1 | 1 |
| 2 | 1 | 1/2 | 1/2 | 1/2 |
| 5 | 1 | 1/3 | 1/5 | 1/5 |
| 10 | 1 | 1/3 | 1/5 | 1/10 |

**fp32 never slows down**, at any value: one chunk is one column is one
pass. That is deliberate - the workload this tier serves is fp32
(docs/ATLAS.md) - and it is why the parameter is a cap on columns
rather than a fixed pass count.

**Measured**, out-of-context synthesis of `cft_krnl` on
`xcu50-fsvh2104-2-e` at a 135 MHz ask, Vivado 2026.1, one build at a
time (`hw/mc_sweep.sh`, summaries in its `summary.txt`):

| MUL_PASSES | LUT | FF | DSP | BRAM | implied path delay | levels |
|---|---|---|---|---|---|---|
| 1 | 123,214 | 57,638 | 262 | 36 | 5.821 ns | 25 |
| 2 | 120,391 | 58,419 | 152 | 36 | 5.585 ns | 23 |
| 5 | 116,158 | 53,598 | 70 | 36 | 5.585 ns | 23 |
| 10 | 115,310 | 53,146 | 56 | 36 | 5.585 ns | 23 |

These are synthesis estimates, comparable with each other and not with
the routed 123,420 of the timing section above - though the
`MUL_PASSES=1` row landing within 0.2% of it is a good sign that the
default is untouched. The critical path is the same one it has always
been, `s10_mag` into the fp256 normalise stage, and it gets slightly
shorter, not longer: the multiplier was never on it.

**The reading, and it is not what step 3 assumed.** Iterating the
multiplier ten ways cuts DSPs by **79%** (262 to 56) and LUTs by
**6.4%** (123,214 to 115,310). The tile's LUTs are in the aligner and
the normaliser, which are linear in format width and were already
shared; the multiplier is DSPs, which is exactly what the sharing
doctrine in docs/ROADMAP.md says - "linear in format width shares at
1x, quadratic does not" - and what `cft_mulfrac` measured from the
other side in 2026-08-30, saving no DSPs and costing LUTs.

So this parameter buys **DSP headroom, not LUT headroom**, and LUTs are
the constraint. On the parts docs/PLATFORMS.md priced, a tile's 262
DSPs would have been 31% of a Kintex-7 325T's 840 and 35% of an
Artix-7 200T's 740 - real but not blocking - and 56 DSPs make that axis
disappear entirely. The LUT axis does not move enough to change how
many tiles fit anywhere: one tile is 60.5% of a K325T's 203,800 LUTs at
`MUL_PASSES=1` and 56.6% at 10, and 91.5% against 85.7% of an
Artix-200T's 134,600, which still wants the fused ladders rather than
this. **The fit lever for a small part is `FUSE_NORM` and
`FUSE_ALIGN`** (which took the full tile from 139,404 to 123,599 in the
geometry table above); `MUL_PASSES` is what makes a DSP-poor part or a
many-tile die stop caring about the multiplier. The two compose, and
the sweep script takes both.

**On 7-series fabric, where the two levers have to be measured
together.** The Vivado 2026.1 install on this host carries only the
UltraScale+ and Versal families, and the 2022.2 install in the
`cft2204` distro carries Zynq-7000 but is licensed for Alveo devices
only - so the matrix's `xc7k325t` and `xc7a200t` cells are unrun. What
is free in every edition and present there is `xc7z020`, whose fabric
is Artix-7 class: CARRY4 and 6-input LUTs rather than UltraScale+'s
CARRY8, which is the difference that matters for a tile bound by its
aligner. The part is far too small to hold a tile - that is not what it
was run for - but the four cells on one fabric say what each lever
buys:

| MUL_PASSES | ladders | LUT | FF | DSP | implied delay |
|---|---|---|---|---|---|
| 1 | off | 135,865 | 59,147 | 220 (capped) | 16.157 ns |
| 1 | on | 120,282 | 49,395 | 220 (capped) | 16.327 ns |
| 10 | off | 116,498 | 53,193 | 56 | 16.428 ns |
| 10 | on | **99,287** | 43,329 | **56** | 17.140 ns |

**Read the two `MUL_PASSES=1` rows with their asterisk.** This part has
220 DSPs and a single-pass tile wants 262, so Vivado capped inference
at 100% and put the rest of the multiplier in fabric; those two LUT
figures are inflated by an unknown amount and cannot be quoted as a
tile's cost on a part with DSPs to spare. They are still the honest
answer to a different question - what a single-pass tile does to a
DSP-starved part - and the answer is that it stops being a multiplier
design at all.

The `MUL_PASSES=10` rows are clean at 56 of 220 DSPs, and between them
the fused ladders take **116,498 to 99,287 LUT, 14.8%** on this fabric,
against the 11.3% they took on the U50's (139,404 to 123,599 in the
geometry table above). So the levers compose: the
pass count empties the DSP columns, the ladders take the aligner and
normaliser, and **a full fp256-capable tile is 99,287 LUT and 56 DSP on
7-series fabric.** Against the parts docs/PLATFORMS.md priced, that is
**49% of a Kintex-7 325T** (203,800 LUT, 840 DSP) and **74% of an
Artix-7 200T** (134,600, 740) on the axis that constrains, with the DSP
axis at 7% and 8%. A tile fits both, which is what step 4 of the third
tier needed to know.

The timing is the other half of the trade and this part is honest about
it: 17.1 ns of implied path on a -1 Artix-class fabric is about 58 MHz,
against 5.6 ns and a 135 MHz close on the U50's -2 UltraScale+. Slower,
on anything, is a design position rather than a disappointment - but it
is the number, and the K325T's -2 grade would be the one to measure
before quoting a clock for a real board.

**The parts themselves, measured the same day** once the families
were installed and the licence-tier trap below was understood. Both at
`MUL_PASSES=10` with the ladders on, and at `1` with them on for the
comparison:

| part | LUT | of device | DSP | of device | implied delay | levels |
|---|---|---|---|---|---|---|
| xc7k325tffg900-2, 10 passes | 98,929 | **48.5%** | 56 | 6.7% | 9.698 ns | 24 |
| xc7k325tffg900-2, 1 pass | 109,225 | 53.6% | 262 | 31.2% | 9.956 ns | 25 |
| xc7a200tsbg484-1, 10 passes | 98,929 | **73.5%** | 56 | 7.6% | 17.422 ns | 23 |
| xc7a200tsbg484-1, 1 pass | 109,225 | 81.1% | 262 | 35.4% | 17.785 ns | 26 |

The LUT, flip-flop and DSP columns are identical between the two parts
at the same configuration, which is what one expects: same fabric
family, same mapping, and only the speed grade differs. So the two
rows that matter are the delays.

**The Kintex-7 325T is the surprise, and it is a good one.** At its -2
grade the tile's implied path is 9.698 ns against a 100 MHz ask, which
is a WNS of -0.066 ns - about 103 MHz of path, essentially the ask,
where the Zynq-7020 stand-in's -1 fabric had suggested 58. A full
fp256-capable tile at **48.5% of a K325T running near 100 MHz** is a
better answer than the third-tier plan assumed it would get, and it is
the part the survey already recommended for other reasons. The
Artix-7 200T is the slower half of the pair, 17.4 ns and about 57 MHz
at its -1 grade, with the tile at 73.5%.

**And on a part with DSPs to spare the pass count is a smaller lever
than the ladders**, exactly as the U50 rows said: with the ladders on
either way, ten passes take the K325T tile from 109,225 to 98,929 LUT,
9.4%, while taking 262 DSPs to 56. Two tiles do not fit a K325T on
LUTs (197,858 is 97% of the device before any interconnect), so the
pass count's prize on these parts is the DSP column and the headroom
around one tile, not a second tile.

**The licence-tier trap, recorded because it cost an afternoon.**
Vivado 2026.1 selects **one** licence tier at startup and then exposes
only that tier's devices. With an Alveo entitlement and a Basic
entitlement in the same `Xilinx.lic`, it announced "a valid Vivado
Design Suite ALVEO license has been detected" and reported that
`xc7k325tffg900-2` did not exist - `get_parts` returned 12 parts, all
Alveo - with every 7-series device file correctly installed on disk
and the Basic increment sitting in the same file. Splitting the
licence into an Alveo-only and a Basic-only copy and pointing
`XILINXD_LICENSE_FILE` at the Basic one turns 12 parts into 1,215,
including 212 Kintex-7 and 210 Artix-7. **A part Vivado says does not
exist may be a part your active tier does not cover.**

**Routed, 2026-09-07**, out of context in the `board` configuration
(ten passes, both ladders on), which settles what the synthesis slack
left open:

| part | grade | ask | routed WNS | verdict |
|---|---|---|---|---|
| xc7k325tffg900-2 | -2 | 100 MHz | **+0.096 ns** | closes; 95,695 LUT (47.0%), 56 DSP |
| xc7k325tffg676-1 | -1 | 80 MHz | -0.384 ns | misses; about 77 MHz |
| xc7k325tffg676-1 | -1 | 100 MHz | -2.782 ns | misses |
| xc7k410tfbg676-2 | -2 | 100 MHz | -0.957 ns | misses; ffg900 identical |
| xc7k410tfbg676-2 | -2 | 80 MHz | +0.607 ns | closes |

The -2 K325T carries the tile at 100 MHz, the synthesis estimate's
-0.066 ns becoming +0.096 routed, at 47.0% of the part rather than
48.5%. **The speed grade is the finding**: the same tile on a -1
misses 80 MHz, so the cheapest core board docs/PLATFORMS.md lists
(`xc7k325tffg676-1`) would run it near 77 MHz. The larger 410T is the
slower part at the same grade, and the whole 1.05 ns gap to the 325T
is route: docs/studies/OPT-C-timing.md found the two netlists
identical to a picosecond of logic delay, and 1.33x the fabric area
predicts 15.3% more wire against 13.5% measured. The package makes no
difference out of context. **Still not measured:** either part's
ceiling, which wants the frequency sweep that study specifies, and any
post-route figure under a shell rather than out of context.

## The fractured array (built 2026-08-30: rtl/cft_mulfrac.sv)

One physical partial-product array computing, per beat and by mode,
8x(24x24), 4x(53x53), 2x(113x113) or 1x(237x237). It replaces the
fifteen per-lane multipliers the four banks used to carry; Yosys counts
40 multiplier cells in cft_krnl before and 10 after.

The decomposition is NOT the granule grid this section used to sketch.
It is the chunk-column structure the pipelined core already had:
pp[k] = ma * mb[k*MCH +: MCH], one column per chunk. Slot demand per
mode is then lanes x ceil(P/MCH), and MCH alone decides how many
physical slots the array needs:

| MCH | fp32 | fp64 | fp128 | fp256 | slots |
|---|---|---|---|---|---|
| 24 | 8 | 12 | 10 | 10 | 12 |
| 27 | 8 | 8 | 10 | 9 | **10** |

The old sketch left "whether DSP48E2 27x18 tiling beats a uniform 24x24
granule" as v1 design work. It does, and for a reason the sketch did
not anticipate: 27 wins on SLOT COUNT before it wins on DSP mapping.
Ten slots of 237x27 is about what the fp256 bank alone already spent,
which is the whole economics of the thing - the array costs what the
widest rung costs and serves every rung.

**The reduction tree carries no shifts and no mode awareness.** The
obvious fractured tree sums within a lane and never across, which is
fiddly. It is also unnecessary: a P x P product is at most 2P bits and
lane L is placed at L*2P, so lanes occupy disjoint fields and no lane's
sum can carry into its neighbour - the value that would have to
overflow is a product that already fits exactly. Every slot is
therefore shifted into final position at S2, the tree becomes a plain
16-to-1 sum, and all mode-dependence collapses into one 4:1 mux per
slot on elaboration constants. That is what keeps the fracture cheap.

**The alignment/normalise/round tail is NOT shared**, contrary to the
sketch. Eight fp32 results need eight roundings, and fracturing a
717-bit normaliser and a 238-bit round increment into independent lanes
is a much harder problem than fracturing a multiplier - in the most
safety-critical logic in the design. So each lane keeps its own tail
and only the multiplier is shared. That caps the saving well below what
a full datapath fracture would give, and it is the right first step:
the tail is where the contract lives, and it is untouched.

Depth is 5 - products plus four tree levels - matching the multiplier
segment of cft_fpfma_pipe exactly, so sharing moves no other stage.
cft_fpfma_pipe's EXT_MUL parameter is the seam: at 0 a lane builds its
own multiplier as before, at 1 it hands its stage-1 significands out
and expects their product back five cycles later.

**Full tile only.** The array's geometry IS the 256-bit beat's. The
quarter tile (BEAT_BITS=64, fp32+fp64) has two and one lanes and does
not build the fp256 rung the array is sized for, so sharing there would
cost more than it saved. `USE_FUSED_MUL`, the localparam in
`cft_lanes` that gates it, requires `FUSE_MUL` **and** BEAT_BITS==256
**and** all three trim parameters; the other two ladders self-gate the
same way. Open-toolchain targets fall back to private multipliers with
no other change.

Verified by equivalence rather than by argument: tb_mulshare builds all
four banks twice from the same inputs on the same cycle, once private
and once shared, and asserts identical bits and flags. 480 beats across
four formats and five rounding attributes, 64 across eight precision
switches with the pipe draining, 160 of nothing but specials.

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
