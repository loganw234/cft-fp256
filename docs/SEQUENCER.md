# The orbit sequencer

*The sections below describe **revision 6** (2026-09-15): revision 3's
thirty-two registers a lane, **256-slot per-lane scratch memory** with a
per-run block that fills it and empties it, **16,384 instructions** a
tile and **512-entry constant bank**; revision 4's **R8**, an indexed
scratch access at or past the depth REPORTED rather than reduced;
revision 5's per-lane costs (R9-R15: no register-file wipe, operand
streams on demand, the drains at a beat a cycle, overlapped issue,
three beats in flight, forwarding); and revision 6's **R16** - an input
block fetched through an index table, one round trip a gathered
element - and **R17** - a per-run lane mask, one beat read a block. The
sections at the end of this file are the record of revisions 2 through
6 and the reasoning behind each change; everything before them has been
updated to describe the model as it now is. VERSION 0xA00, CAPS[7:4]
and CAPS2[10:0].*

*Revision 7 (2026-09-29) changes what a program COSTS and nothing a
program can observe: **R18**, the control codes that walk the block's
beats go through the issue pipe one beat a cycle and wait only for what
they read; **R19**, a beat with no active lane is not issued and a
stream beat no lane can read is not loaded. It is simulated and benched
against the model, and it is on silicon: the U50's revision-7 single
(rev7b, built from 9fc9c0d, 135 MHz) agreed with the model on the card
on 2026-09-29, and its quad (q135b, built from cf97a50, 135 MHz) passed
its card legs on 2026-09-30 (docs/VALIDATION.md). Its section is the
last in this file, and R12 to R15 carry notes where it changed them.*

*Revision 6 is on silicon. The round-2 single tile (VERSION 0xA00,
built from 5b7aa19 at 135 MHz) ran its programs, gathers, masks and
reductions on the U50 on 2026-09-15 - after two HOST defects the card
found, neither in this RTL (docs/VALIDATION.md, "round 2's card day,
second half"); the quad closed at 135 MHz on its second implementation
and ran green on four tiles on 2026-09-16. Every pair since the
revision-4 pair (`~/cardday-rev4`, 2026-09-13) carries R8 and CAPS2[6];
the pair before round 2, `~/cardday-seq6`, is VERSION 0x900 and
publishes neither CAPS2[9] nor [10], which is what the card day's first
half used to show that the ABI 0.14 library refuses the round's
features BY NAME on an older tile. That is the rule throughout: a tile
older than a feature reads its CAPS2 bit as zero and declines to run
rather than computing something else - under the reserved-bit rule that
has guarded `flags` since revision 2 and MODE's upper half since
revision 4 - and libcft refuses earlier and by name
(`CFT_ERR_UNSUPPORTED`) rather than letting the tile say it with
STATUS[3] after the crossing.*

STATUS: design, golden model, software implementation, kernel
integration - and, as of 2026-09-01, **the RTL core itself, benched
bit-exact against the model**. `python/cft_golden/seq.py` is the
definition of correct; `host/src/program.c` is libcft's executor and
agrees with it over a shared fuzz corpus (`make libcft-seq`);
`rtl/cft_seq.sv`, computing on the kernel's ONE `cft_lanes` array (shared
with the streaming engine since 2026-09-01 - see below), is the
hardware, and `tb/test_seq_core.py` holds it to seq.py the way the
FMA core is held to softfloat.py: 9/9 suites green - deposits,
counts, flags and STATUS compared exactly, across all four formats,
single-instruction programs through nested-loop escape maps, ragged
block edges, a 62-program fuzz corpus, and the refusal matrix with
zero write traffic on every refusal - plus `tb/test_krnl_seq.py`
driving the whole kernel through the CSR exactly as XRT will.
Remaining distance on the evening of 2026-09-01: hw_emu through the
real XRT stack, a bitstream, silicon. hw_emu was met at fp32 the next
day (the status note under the gates paragraph below); a bitstream
carrying a program and silicon were still open as this was written, and
BOTH were met the following week - see the dated status note a hundred
lines down, which is the current one. The RTL was pulled
forward from v2 deliberately: an open core fed by DDR or
PCIe-to-host-RAM cannot afford a memory pass per step, so the
sequencer stops being a throughput refinement there and becomes the
architecture.

What exists around it as of 2026-09-01: `cft_seq` is instantiated in
`cft_krnl` as a peer of `cft_engine_stream`, sharing the A and D
masters *and the tile's one `cft_lanes` array* under a `MODE[15]`
select registered at the accepted start - and, since the bank fix of
2026-09-02 (40149b1), the B and C masters too, each read steered to
the master that owns its buffer; the CSR map carries
`PROG_PTR` and `CNT_PTR` at 0x54 and 0x5C, `BANK_PTR` at 0x64 since
revision 2, and since revision 3 the read-only `CAPS2` at 0x6C with
`SCRATCH_IN_PTR` at 0x70 and `SCRATCH_OUT_PTR` at 0x78 (VERSION 0x800,
CAPS bit 15 for the sequencer and [7:4] for its features, CAPS2[5:0]
for the scratch), and `hw/kernel.xml` carries the matching
arguments 6 through 10 - `prog`, `bank` and `scratch_in` on `m_axi_a`
because they are read, `cnt` and `scratch_out` on `m_axi_d` because
they are written;
`cft_program_run` dispatches to the device when the program was loaded
on one, through `cftx_program_run` on a single compute unit;
and `tb/test_krnl_seq.py` scores a full-kernel run against `seq.py` on
deposits, counts, FLAGS and STATUS. The plumbing is therefore testable
ahead of the core, which is the point of writing the contract down
first.

The core is green - `tb/test_seq_core.py` scores its fetch, execute and
drain body against `seq.py` directly, **35/35 suites** at revision 6
(2026-09-15), 17/17 when revision 3 added five (the four scratch codes,
the block in and out, the header refusals, and a scratch fuzz), where
indexed constants made it 10 on 2026-09-07 and revision 2 made it 12 -
and both sequencer targets, `krnlseq` and `seq_core`, are in `make sim`,
folded in on the day the core passed, which was the only day the claim
would mean anything. On the revision-3 tree (2026-09-08) the whole set
held: seq_core 17/17, krnlseq 1/1, krnl 2/2, reduce 3/3, reduceacc 5/5,
krnlfused 2/2, krnlplain 2/2, quarter 1/1, faults 5/5, the golden
model's own pytest cases, `make yosys-lint` clean, and the Verilator
width gate clean. The last of those is not decoration: it is
fatal-on-width here, and it caught seven implicit-width sites in
`cft_seq.sv` that Icarus and yosys both passed.

The one v1 deviation from the shape below is gone. The first RTL gave
the sequencer a PRIVATE copy of the lane array (`cft_seq_lanes`, the
same per-lane recipe instantiated a second time, without the fused
ladders) because the engine's array was woven through the streaming
datapath and the tree was staged for card day. Out-of-context
synthesis then put the sequencer-era tile at 288,764 LUT against
98,310 - the copy was 124,057 of it - and the quad build asked for
1.32M LUTs of an 871k part. So the array was extracted into
`rtl/cft_lanes.sv`, ONE instance per tile that `cft_krnl` owns and
both engines drive through a per-issue request (valid, opcode,
attribute, precision, three operands) under the same `MODE[15]`
select that already chose the AXI owner. No arbitration - the two
never run at once - and P1 became a fact about the netlist rather than
a claim about two copies of the same source.

Two consequences, recorded because neither was in the plan. Once the
second array stopped dominating, the sequencer's OWN address arithmetic
was the kernel's critical path - it multiplied by `esz` and
`max_deposits`, and those mapped to a DSP cascade - so the multiplies
became shifts (every one of them is by a power of two) and the variable
part-selects into the packed lane-state and deposit-count vectors
became loops over constant indices. `cft_seq` went 15 DSP48 to **0**,
49,657 to **26,586** LUT in-kernel, and its worst path -0.065 ns to
**+4.268 ns**, with the benches identical to the picosecond, which is
the proof that no cycle moved. And sharing the operand bus put the
reduction accumulator's combinational output through `cft_simpleops`,
whose result `cft_fpfma_pipe` latches unconditionally - a path that did
not exist while the accumulator fed a private array directly, and worth
**-0.577 ns in the shell**. One register on the accumulator's operands,
with `cft_reduce_acc`'s `ADD_LATENCY` raised to `LATENCY + 1` so the
destination level still arrives with its sum, fixes it; it is not a
numeric change, because the tree shape and the order of every add are
fixed by element index and never by timing. Sharing a datapath shares
everything attached to it, and an area argument does not surface that.

Where the tile landed, out of context (Vivado 2022.2, xcu50, 135 MHz):
**139,404 LUT at +0.307 ns**, against 288,764 for the private-array
tile and 98,310 for the pre-sequencer one. The fused ladders
(`FUSE_NORM`/`FUSE_ALIGN`) reach 123,599 but leave only +0.097 ns, and
the single tile linked at 135 MHz with them on is the build that
returned -0.577; they default OFF, and stay proven bit-exact (`make
krnlfused` and `krnlplain` cover both defaults) and parameterised for a
slower clock or the smaller open-core part. **Out-of-context synthesis
is not shell timing** - that build is what this project paid to learn
it, and docs/ROADMAP.md carries the full accounting.

Where the hardware gates stand, 2026-09-01 evening. A fresh `hw_emu`
image built from this commit **is executing the design**: a reduction
ran to completion through the real XRT stack with the correct flags.
But no sequencer program has been through it, and two of that gate's
stages did not start at all, with `Can't parse message of type
"xclCopyBufferHost2Device_response"` and `Failed to connect to device
process` - the stale-emulation-state startup race that
`hw/run-device-test.sh`'s own header documents at length, not a design
fault; those stages are being re-run with settling delays. **So the
emulation gate is not met on this design.** A single tile and a quad
are building at 135 MHz from this commit with the ladders off and the
result is not known yet, so there is no closed bitstream for the
sequencer tile either - and there is still no card in the machine.
docs/BRINGUP.md is the gate record.

*Both halves of that sentence were answered. The builds returned the
same day: single +0.618, quad +0.143, both at 135 MHz from 9f73107
(docs/VALIDATION.md, 2026-09-02). The card arrived on 2026-09-08 and
ran them.*

*Status 2026-09-02, from docs/VALIDATION.md's entry "the sequencer
passes on a device": the bank fix (40149b1) put every sequencer
program through hw_emu on the real XRT stack at fp32 - 28 checks, 0
failed, every program shape - before the 90-minute emulation cap
stopped the run in fp64. The emulation gate is met for the sequencer
at fp32; fp64 and above are unrun there, not failed; and there is
still no card. The paragraph above is kept as the record of the
morning that found the bug.*

*Status 2026-09-08: programs in all four formats went through the real
XRT stack on a four-tile hw_emu image - `device-test -s -n 24`, 98
checks, 0 failed - which lifts the fp32-only qualification; and the
card ran the sequencer the same week, most visibly in card day's soak,
where the zoom reference orbit deposited one checkpoint hash on one
tile, on four and in software.*

So a program can be written and run today, on any machine, with no
card. What the hardware adds is speed and the on-chip iteration that
makes the whole thing worth building.

## Why this exists, and why it is a multi-tile problem

The elementwise engine reads three operands and writes one result per
element. At fp32 that is 16 bytes of traffic for one fused
multiply-add: **0.125 flops per byte.** No arrangement of compute
fixes that number, because it is a property of the dataflow rather
than of the hardware. The tile is memory-bound and always will be for
elementwise work.

This is exactly why more compute units do not, by themselves, make the
card faster. Four tiles sharing one HBM stack are four tiles waiting
on the same bandwidth. Multi-CU is only worth building if there is
something for the extra tiles to *do* between memory accesses.

A sequencer is that something. Load a point once, iterate a program on
it K times on-chip, deposit what matters, move on. Arithmetic
intensity rises by roughly K, and at K ~ 30 the design stops being
memory-bound and starts being compute-bound - which is the regime
where a second, third and fourth tile are worth their area. It is also
the condition for a 130 nm chiplet to make any sense at all, where the
off-die link is slower than HBM by more than an order of magnitude.

So the sequencer and multi-tile are one piece of work. Neither is
worth much without the other.

## What it must not cost

The contract does not bend. Same program, same inputs, same attribute
-> same bits, on one tile or four, in simulation or on silicon. Three
properties carry that, and each is stated here as something to test
rather than something to believe:

**P1. The ALU is the existing pipeline.** The sequencer introduces no
arithmetic. Its opcodes are the same 8-bit space `MODE[7:0]` already
carries, executed by the same `cft_fpfma_pipe` and `cft_simpleops` that
the 1,068,915-case conformance set and the differential already cover. A
sequencer program is a schedule over verified operations, so the
numerics need no new verification surface - only the scheduling does.
Since the array was extracted this is structural rather than
argumentative: there is one `cft_lanes` per tile and both engines drive
it, so "the same pipeline" is a property of the netlist that a second
copy cannot quietly drift away from.

*A note on `IMUL`, added 2026-09-07.* Opcode 30 is a new operation, and
P1 says the sequencer introduces none. It does not: `IMUL` is an
opcode in the shared `cft_lanes` array, computed in `cft_simpleops`
beside the rest of the integer group, and `cft_engine_stream` can issue
it as readily as `cft_seq` can. That is the same category as the seed
opcodes 26 and 27, and P1's subject is the *sequencer* introducing
arithmetic of its own, which is still nothing. What it does cost is a
verification surface the golden model owns first, exactly like every
other opcode: `softfloat.py`'s `imul()`, the differential, the bench.
Its definition - the low 32 bits of the product of the operands' low
32 bits, zero-extended to the format width - is 32-bit and not W-bit
because its caller is a 32-bit hash whose value must agree with a GPU
computing it on a `uint`; `docs/ATLAS.md` is where that requirement
comes from and `host/include/cft.h` states the operation.

**P2. Deposition is addressed by index, never by arrival.** Lane *i*
writes its *d*-th deposit to

    base + (i * max_deposits + d) * element_bytes

No slot is reachable from two indices, so two tiles cannot race for
one. This is why deposition is bounded rather than appended: an append
order is an arrival order, and an arrival order is a race.

That much is structural. But the address also contains *d*, the lane's
own deposit count - and *d* depends on the shared program counter,
which depends on the early exit, which is a **cross-lane** condition.
So **P2 is a corollary of P3, not an independent property.** If the
early exit were observable, splitting lanes across tiles would change
their deposit counts and therefore their addresses, and the collision-
free arithmetic above would be laying different answers into different
places very tidily. The two are fuzzed together for that reason.

**P3. The early exit is invisible.** A loop stops as soon as no lane
is active. That must change how long the run takes and nothing else -
if it could change a result, the sequencer would be a machine whose
output depended on how fast its inputs converged. Three rules make the
invisibility provable rather than probable:

- every register write, every deposit, **every scratch store and
  load** and **every exception flag** is masked by the lane's active
  bit, so an all-inactive loop body is a no-op by construction. The
  scratch is the newest reason this rule has to be stated as "every
  write" rather than enumerated: a store that escaped the mask would
  be invisible in the deposits and visible in the scratch-out block,
  which is the shape of divergence that is hardest to notice;
- `ACTALL`, the only instruction that can reactivate a lane, is
  illegal inside a loop body;
- `HALT` is illegal inside a loop body too.

The third rule is the one that is easy to miss, and a review found it
missing. `HALT` is the only instruction whose effect is not per-lane,
so the active mask cannot gate it: with every lane inactive, skipping
the loop continues the program while entering it stops the program.
Those differ in deposits, in flags, and in the final register file -
and in deposit counts, which drags P2 down with P3. A fuzz over 40,000
valid programs found divergence *only* ever through that instruction,
and none at all once it is refused.

The loader rejects both, so a program that could observe the
optimisation cannot reach a device.

`test_seq.py` checks the property rather than the argument: 400 random
valid programs run twice with the optimisation forced on and off, whole
machine state compared, plus a negative control that removes the
`HALT` rule and confirms the fuzz then *does* find divergence. A rule
nobody can show the need for is a rule that gets deleted later.

## The shape of a program

A program is data: a header, a constant bank, an instruction stream.
The host DMAs it into on-chip memory through the existing AXI master
and can read it back, so what executed can be attested rather than
assumed - the same reason a bitstream carries a hash.

    struct header {
        u32 magic;          // "CFTP"
        u32 version;
        u32 n_insns;
        u32 n_consts;
        u32 max_deposits;   // per lane; also the output buffer's shape
        u32 precision;      // the PREC_CODE ladder; a program is
                            // compiled for one format, because its
                            // constants are format-width values
        u32 flags;          // bit 0 BANK_EXT, bit 1 SCRATCH_IO,
                            // bit 2 SCRATCH_STRICT (revision 4);
                            // [31:3] reserved, zero
        u32 scratch_io;     // [15:0] n_scratch_in, [31:16]
                            // n_scratch_out, each <= SCRATCH_D;
                            // meaningful only under flags.SCRATCH_IO,
                            // and zero without it
    };

Then `n_consts` format-width constants, then `n_insns` 64-bit
instructions - unless `flags.BANK_EXT` is set, in which case the image
carries NO constant section and is exactly `32 + 8 * n_insns` bytes,
with the constants arriving per run through `BANK_PTR` (R3 below).
`n_consts` still says how many the program addresses either way.

Both of the header's last two words are checked, and a set bit the
tile does not implement is refused in either. That is newer than it
looks: `flags` was `reserved[0]` and the 0x600 tile checked neither
word, which is exactly why `BANK_EXT` needs a CAPS bit rather than
only a header flag - an older tile would read the flag as a reserved
word it never looks at, and then read constants out of an image that
has none. The revision-2 tile's refusal of a non-zero SECOND word is
in turn what guards `SCRATCH_IO`, which is what that word became.

Each lane owns **32 registers** of format width, **`SCRATCH_D` scratch
slots** of format width - 256 on every tile before revision 7 and on
the open-core builds, 2,048 on the U50's revision-7 images - and one
**active** bit. The registers are the working
set and the scratch is where a live set larger than thirty-two spills,
where a small local array lives, and where the host may hand state in
and take it out (R4 and R5 below). The constant bank is separate and
read-only: constants are shared across lanes, so putting them in the
register file would multiply their cost by the lane count for no
benefit. On a chiplet that distinction is most of the area argument.

**The inputs are the streams that already exist** - and, since
revision 3, a fourth that is optional. A lane starts with
`r0`, `r1` and `r2` loaded from the same three operand streams the
elementwise engine already reads, `r3..r31` at `+0`, and every scratch
slot at `+0` except the first `n_scratch_in` under `flags.SCRATCH_IO`,
which come from `SCRATCH_IN_PTR`. The three streams needed no new
input path in the hardware, no new CSR, and
no new host concept - the seed point, its parameter and whatever else
the map needs arrive exactly the way `a`, `b` and `c` always have. The
scratch block DOES add a path, and that is what it is for: three
values is a state a program can be entered at, and thirty is not.
The output widens the same way - from one element per lane to
`max_deposits`, plus `n_scratch_out` slots a lane where the program
asks for them, which is what lets a run be resumed by the next one.

**Flags are masked by the active bit, not just writes.** This looks
like an implementation detail and is not: if only the register writes
were masked, a lane that had already dropped out would keep computing
on its stale registers and pushing `invalid` into the run's sticky
word. The flags would then depend on how many lanes were still
running, which is a result that depends on convergence - precisely
what the contract forbids. An inactive lane contributes nothing at
all.

**Padding lanes start inactive.** The engine reads whole beats, so a
caller's `n` is rounded up and the tail lanes hold whatever padding
the library wrote. For an elementwise operation that is harmless -
zero operands are quiet for every opcode, which is checked - but a
sequencer program is arbitrary, and **no padding value can be relied
on to stay quiet through thirty iterations of an unknown map.**
Padding lanes would push exceptions into the sticky word, deposit into
slots past the caller's buffer, and hold `any(active)` true so the
early exit never fires at all.

So a lane whose index is at or beyond `n` starts inactive. The
hardware knows both numbers, the mask costs one comparator, and the
whole class of problem goes away. This is a real difference from
`cft_run`, where padding is genuinely free.

The scratch block follows the same rule from the other side: a padding
lane **receives nothing and writes nothing**. Both buffers are
`n * count` elements, so the tile's stream simply ends before a
padding lane's slots would begin - the tail of the caller's buffer is
the caller's, exactly as it is for deposits and counts.

## Execution model, and why the lane block has a floor

The ALU is `cft_fpfma_pipe`: **16 stages, fixed latency, no stall path
and no ready signal** (15 until the leading-zero cone became its own
stage on 2026-09-07; `LATENCY` is the parameter and the number below
is written in terms of it). A sequencer that issued one instruction and
waited for its result would bubble LATENCY-1 cycles out of every
LATENCY - which
would cost more than the arithmetic intensity the sequencer exists to
buy, and the whole design would be pointless.

The fix is not a bypass network. It is that **lanes are independent**,
so one instruction issued across a block of lanes is that many
independent operations, and they fill the pipe on their own.

The engine already instantiates one ALU per lane per beat - eight at
fp32, one at fp256 - and issues one beat per cycle. So to keep the
pipeline full the sequencer must hold

    LATENCY beats  =  LATENCY * lanes_per_beat  lanes

on-chip, and issue one instruction across all of them before it needs
the first result. A dependent chain then costs `LATENCY + LATENCY`
cycles per instruction with every ALU busy, instead of `LATENCY` with
all but one idle - and since revision 5's overlap (R12 to R15), about
`LATENCY + 1` on a single-pass tile.

The pleasing part is that this makes the register file
**precision-independent**. A beat is 32 bytes whatever the format, so

    register file  =  32 registers * LATENCY beats * 32 bytes

at fp32, fp64, fp128 and fp256 alike - at today's `LATENCY` of 16,
128 fp32 lanes or 16 fp256 lanes, the same silicon
(`rtl/cft_seq.sv`'s `BLK_LANES = NBEATS * WORDS`). At today's `LATENCY` of 16 that is **16
KiB**; it was 8 with sixteen registers, and 7.5 before `LATENCY` went
15 -> 16 on 2026-09-07, which is where the 7.5 KiB in older notes and
in the revision-2 contract's own summary comes from. Work it out from
the line above rather than quoting a number, because two of the three
factors have moved. What the doubling actually cost in silicon is
measured in docs/VALIDATION.md's 2026-09-08 entry rather than
estimated here. The deposit buffer scales the same way:

    deposit buffer  =  max_deposits * LATENCY beats * 32 bytes

so it passes the register file at `max_deposits > 32` and dominates
from there, which is the regime an orbit actually wants. The earlier
claim that the deposit buffer simply dominates was written before the
lane-block floor was worked out; both numbers are the design, and
trading pipeline depth against deposit depth is the axis a chiplet
turns. The tile builds it at its cap, `MAXD` - 32 KiB at the 64 of the
round-2 and open-core images, 512 KiB at the 1,024 of the U50's
revision-7 ones.

Revision 3's scratch is the same arithmetic with a much larger first
factor:

    scratch  =  SCRATCH_D slots * LATENCY beats * 32 bytes

which at 256 and 16 is **128 KiB a tile**, eight times the register
file and the largest of the three on the round-2 parameters - and the
same size, to the byte, as the instruction memory R6 grew, which is not
one of the three because it is per tile rather than per lane. At the
U50's revision-7 depth of 2,048 it is **1 MiB a tile**, 4 MiB on the
quad. It is precision-independent for the reason the other two are,
and it is the number a smaller part turns down first: `SCRATCH_D` is a
build parameter, the tile publishes its log2 in `CAPS2[3:0]`, and a
program that needs more than a device has is refused where it was
built.

Two consequences worth stating now, because they constrain the RTL:

- **`n` below `L` cannot fill the pipe.** At fp256 that means fewer
  than 16 elements runs at pipeline speed rather than throughput
  speed. It is correct, just slow, and the library should not pretend
  otherwise.
- **The early exit may fire late, and that is free.** `any(active)` is
  a cross-lane reduction over a mask that the last `SETACT` writes
  LATENCY cycles after it issues, so testing it exactly at the loop back-edge
  would cost a drain every iteration. It does not have to be exact:
  firing an iteration or two late is *still invisible*, because those
  iterations are no-ops by P3. The hardware can use whatever mask it
  has to hand.

## Instruction encoding

One 64-bit little-endian word.

| bits | field | meaning |
|---|---|---|
| 7:0 | `op` | ALU opcode when `ctrl=0`, control code when `ctrl=1` |
| 11:8 | `rd` | destination register, low four bits |
| 15:12 | `ra` | source A, low four bits |
| 19:16 | `rb` | source B, low four bits |
| 23:20 | `rc` | source C, low four bits |
| 26:24 | `rnd` | 754 rounding attribute for this instruction |
| 27 | `ka` | source A names the constant bank, not a register |
| 28 | `kb` | as `ka`, for source B |
| 29 | `kc` | as `ka`, for source C |
| 30 | `kx` | the constant indices come from `imm`, not from the operand fields |
| 31 | `ctrl` | this is a control instruction |
| 55:32 | `imm[23:0]` | the three constant indices under `kx`; the SLOT on `STL`/`LDL`; part of the trip count on `REPEAT`; the post-step in `imm[11:0]` on `STX`/`LDX` (revision 8, proposed: R22); zero otherwise |
| 56 | `imm[24]` | `rd[4]`, the fifth bit of the destination register |
| 57 | `imm[25]` | `ra[4]` |
| 58 | `imm[26]` | `rb[4]` |
| 59 | `imm[27]` | `rc[4]` |
| 60 | `imm[28]` | under `kx`, the ninth bit of `ka`'s constant index |
| 61 | `imm[29]` | as above, for `kb` |
| 62 | `imm[30]` | as above, for `kc` |
| 63 | `imm[31]` | reserved, must be zero |

A register field is **five bits**: the low four in the operand field
above and the fifth in `imm[27:24]`, which is R1 below. `REPEAT` is the
one instruction that reads `imm` as a whole - its trip count - and it
names no register, so all thirty-two bits are the trip count there and
nothing in `imm[27:24]` is a register's high bit.

### Indexed constants (`kx`), 2026-09-07

An operand's index is four bits wide, so `ka`/`kb`/`kc` on their own
reach **sixteen** constants whatever `n_consts` says. That was the wall
`docs/ENCLOSE.md` hit - an interval coefficient costs two constants, so
a polynomial was chunked eight coefficients at a time - and the one
`docs/ATLAS.md` counts eleven of the sixteen slots gone to `P[8]`,
`uT`, `TAU` and `PI` before a single coefficient.

Bit 30 was reserved and must-be-zero, and `imm` is thirty-two bits that
an ALU instruction had no use for. **When `kx` is set the constant
indices for the three operands come from `imm[7:0]`, `imm[15:8]` and
`imm[23:16]`**, so the addressable bank was **256** - which was
`KMEM_D`, the capacity `cft_seq`'s header check already permitted and
only its storage and operand mux fell short of.

Revision 3 adds a **ninth bit to each index**, at `imm[28]`, `imm[29]`
and `imm[30]` for `ka`, `kb` and `kc` respectively - the same
construction as the fifth register bits one nibble down - so the bank
is **512** and `KMEM_D` is 512 with it. A ninth bit is read only under
`kx` for an operand whose `k` flag is set; set anywhere else it is an
unread field and the program is refused. `imm[31]` stays
reserved-must-be-zero, which is the cheap version guard for whatever
comes after this and leaves room for a counter-indexed form without
disturbing either.

An operand whose `k` bit is CLEAR still names a register through its
own four-bit field, exactly as before, so `kx` widens the constant
addressing and touches nothing else. The arithmetic is untouched, the
header is untouched, and no entry point changes signature: a program
is data.

**The version guard is the reserved-bit rule.** A loader that predates
`kx` reads bit 30 as reserved-must-be-zero and refuses the program -
which is exactly the behaviour a compatibility rule is for, and the
reason this feature needs no program-header VERSION bump. What it DOES
need is a CAPS bit, because an old BITSTREAM has no such rule: its
operand mux would ignore bit 30 and read the four-bit field. Since the
same day CAPS[4] publishes it - the feature nibble's wide-constant-index
bit, `cft_caps.seq_features` bit 0 - and CAPS[28] publishes `IMUL`
(bit 4 of the same word); `cft_program_load` refuses an image that uses
either on a device that does not publish it, naming the instruction,
so a host never has to guess and `host/tools/enclose.c` falls back to
its chunked shape where the loader says no. Revision 3's ninth index
bit takes CAPS[7] on exactly the same argument one step further out: a
revision-2 tile reads eight index bits and would address constant 5
where the program meant 261. No VERSION step for any of them: VERSION
guards the register map, and features are announced in CAPS
(rtl/cft_csr.sv).

The per-instruction rounding attribute is not an indulgence. The
pipeline already carries the attribute alongside each operation rather
than latching it per run - that is what makes one pass able to produce
both interval bounds - and a sequencer that could not change attribute
between instructions would throw that away.

There is deliberately **no unconditional-write flag.** It would have
cost one bit and broken P3: an instruction that writes regardless of
the active mask makes an all-inactive loop body observable, and the
early exit stops being free. A program that wants an unconditional
write can `ACTALL` outside the loop.

### Control codes

| code | name | effect |
|---|---|---|
| 0 | `HALT` | end the program |
| 1 | `REPEAT imm` | begin a bounded loop of `imm` iterations |
| 2 | `ENDREP` | close the innermost loop |
| 3 | `DEPOSIT ra` | append register `ra` to this lane's output |
| 4 | `SETACT ra` | `active := active AND (ra != 0)` |
| 5 | `ACTALL` | `active := true`; illegal inside a loop |
| 6 | `STL ra, imm[23:0]` | `scratch[imm] := ra` |
| 7 | `LDL rd, imm[23:0]` | `rd := scratch[imm]` |
| 8 | `STX ra, rb` | `scratch[rb mod SCRATCH_D] := ra` |
| 9 | `LDX rd, rb` | `rd := scratch[rb mod SCRATCH_D]` |

Codes 6 to 9 are revision 3's per-lane scratch (R4). A store is a
register write for P3's purposes - masked by the lane's active bit, so
an all-inactive loop body stays a no-op - and a load writes `rd`, so it
is masked the same way; neither is legal-only-at-top-level, because
neither can be observed through the early exit. Neither is arithmetic
either: no rounding attribute, no flags, and P1 holds as it did for
`IMUL`. The indexed forms take the slot from the low
`log2(SCRATCH_D)` bits of `rb`'s bit pattern read as an unsigned
integer, **reduced modulo the depth**; the model does the same, so the
reduction is part of the contract rather than an accident. A slot at
or past `SCRATCH_D` in `STL`/`LDL` is refused by the loader by name,
as a constant index past the bank is - the instruction says which slot,
so the answer is knowable before the run; an indexed access is not
refused, because `rb` is data and refusing it would be refusing a
program for a value it might compute. Slots start at `+0` for every
lane at the start of a run, except where R5 preloads them.

`SETACT` narrows and never widens. Lanes drop out as they converge and
stay out, which is what an escape-time iteration wants and what makes
the early exit meaningful. Widening is `ACTALL`'s job alone, and it is
confined to the top level so that P3 holds.

Loops nest four deep, and `HALT` and `ACTALL` are legal only at the
top level.

**A tile also has four capacities the contract does not fix.** They
are build parameters of `cft_seq`, set where rtl/cft_krnl.sv
instantiates it, and not part of the program model: **`MAXD`
deposit slots a lane**, `IMEM_D` instructions, `KMEM_D` constants and
**`SCRATCH_D` scratch slots a lane**. Since revision 7 (2026-09-29)
three of them are `cft_krnl`'s own parameters - `SEQ_MAXD`,
`SEQ_IMEM_D`, `SEQ_SCRATCH_D` - so that each BUILD says what it has,
the way `BURST_LOG2` and the rest do: their defaults are the U50's and
a smaller part names its own.

| capacity | U50, revision 7 | round-2 images and open-core builds | history |
|---|---|---|---|
| `MAXD` | 1,024 | 64 | 64 from the first tile to revision 6 |
| `IMEM_D` | 32,768 | 16,384 | 1,024, then 4,096 at revision 2, 16,384 at revision 3 |
| `KMEM_D` | 512 | 512 | 256 until revision 3; not a build's to set (below) |
| `SCRATCH_D` | 2,048 | 256 | new at revision 3 |

The open-core configurations in the tree pin the right-hand column:
`tb/Makefile`'s `OPEN_CAPS_GENERICS` (the board benches and the quarter
tile) and hw/openxc7's board synthesis and harness. A header that asks
for more than any of them - including a scratch count past the depth -
is refused by the tile at the header, before the constants and
instructions stream in, in the same check that refuses a precision the
tile was not configured for. Each is a power of two no larger than
2^15, because each is published as a four-bit log2 (below), and
`cft_seq` refuses to elaborate any other.

`KMEM_D` stays a localparam at 512: a deeper bank needs index bits the
instruction format does not have (docs/ROADMAP.md, "The program
limits").

`SCRATCH_D` is the one of the four that is NOT purely a capacity: the
indexed forms `STX`/`LDX` reduce `rb` modulo it, so a tile with a
different depth would compute different answers rather than merely
accept larger programs. That is why it must be a power of two, and why
the model and the library take it as a parameter rather than fixing
it: `seq.run(..., scratch_depth=)` (256 by default, so every run is the
run it always was) is the authority for a tile of any depth, and a
libcft software handle computes at the depth it publishes - 256, or the
depth it was opened at with `cft_open_ex` (revision 7, below). A strict
image (R8) is the portable one: a strict run that reports nothing
computes the same answer at every depth deep enough for it.

A fifth number is not a memory depth at all but the reach of the
instruction's own operand field: the `ka`/`kb`/`kc` bits redirect
four-bit fields at the constant bank, so until 2026-09-07 **a program
addressed sixteen constants** whatever `n_consts` said, on the tile
and in the library alike, and host/tools/enclose.c chunked its Horner
kernel around it. `kx` (below) closed that gap the same day: with it
set the indices come from the immediate, and revision 3's ninth bit
took the reach to the whole 512-entry bank. `cft_caps.max_consts` says
which of the three a device is.

**A host asks rather than guesses.** Since 2026-09-07 the tile
publishes all of them in `CAPS` (0x4C) as log2 - bits 19:16, 23:20 and
27:24, with 7:4 the feature nibble (`kx` at [4], `REGS32` at [5],
`BANK_PTR` at [6] since revision 2, `KX9` at [7] since revision 3) -
and in **`CAPS2` (0x6C)**, whose `[3:0]` is log2 `SCRATCH_D` with `[4]`
saying a scratch exists at all and `[5]` that its per-run block does.
`cft_get_caps` carries them into `cft_caps.max_deposits`,
`max_insns`, `max_consts`, `max_scratch` and `seq_features`. **Every
backend publishes what it enforces and enforces what it publishes**,
and `cft_program_load` refuses an
image past the device's own caps with a message naming the cap and
both numbers, so a program that will not fit is refused where it was
built rather than by the tile with a status bit. The numbers differ
between backends and that is the point: the software backend accepts
2^20 deposit slots a lane, because it models the program model and
not one tile, so "it ran on software" still does not mean "it fits a
tile" - what has changed is that a tool can now find out in one call.
The scratch depth is the exception, because it is part of what a
program means: a software handle's is 256 - a tile's before revision 7
- unless it was opened at another with `cft_open_ex`, and a comparison
against a device opens its reference at the device's `max_scratch`.
Zero in a field means the device did not say (only a remote server
older than the fields), and an unknown cap is enforced against
nothing. The nibble at CAPS[7:4] is now FULL; the next sequencer
feature takes a bit of CAPS2, which is what that register exists for.

Programs that deposit once an iteration feel the deposit budget
first: `cft-zoom` deposits two values a trip, so its default of 1,024
trips a call needs 2,048 deposit slots a lane; on a device that holds
fewer it takes `--steps-per-call` from `cap / 2` - 32 on a 64-slot tile,
512 on the U50's revision-7 one - and refuses a value the user typed
whose two deposits a trip do not fit;
`cft-orbits` deposits four a sample for a whole run in one call, so its
sample count is bounded at `cap / 4 - 1` on a tile - 15 at 64, 255 at
1,024 - and it refuses by name because unlike a trip count the sample
count changes what is recorded.

### What the loader refuses

A program that reaches a device has been checked for all of this, so
the hardware does not have to be:

- unbalanced or over-deep loops; `ACTALL` or `HALT` inside one
- `REPEAT 0` - the doc says *`imm` iterations*, so zero must mean
  zero, and an implementation that ran the body once instead would be
  a silent divergence. (The executor treats it as a skip anyway, so
  that the model and the obvious RTL agree even about a program
  neither should accept.)
- a **worst-case instruction count** above 2^40. Trip counts being
  immediates makes a program finite; it does not make it bounded. Four
  nested `REPEAT 0xffffffff` fit in 104 bytes and describe 3.4e38
  iterations, which terminates in the same sense the heat death of the
  universe does. The loader multiplies the nest out and refuses.
- a header whose **`n_consts` is above 512**, the deepest bank nine
  index bits under `kx` address (since 2026-10-01: the model's loader,
  then `cft_program_load` on every device, as `CFT_ERR_UNSUPPORTED`).
  A tile refuses such an image too, at its header check, but only
  after the image has crossed, with `STATUS[3]` and no explanation. At
  or below 512 a header may still declare more constants than its
  instructions name - but a tile built before revision 3, whose bank
  is 256, refuses 257 to 512 itself, after crossing: a known limit,
  since no such tile is in use.
- a constant index outside the bank, a **scratch slot at or past
  `SCRATCH_D` in a `STL` or `LDL`**, a reserved bit, a set bit in the
  header's `flags[31:3]`, a non-zero `scratch_io` word without
  `flags.SCRATCH_IO`, a scratch count past `SCRATCH_D` with it, or
  trailing bytes after the instruction stream. A `BANK_EXT` image is
  exactly `32 + 8 * n_insns` bytes and a self-contained one exactly
  `32 + n_consts * element_bytes + 8 * n_insns`, so "trailing bytes"
  means the same thing for both. An INDEXED scratch access is never
  refused for its slot, because `rb` is data and the loader cannot see
  it. What an out-of-range index DOES depends on the header: without
  `flags.SCRATCH_STRICT` the contract reduces it modulo the depth,
  which is what every image built before revision 4 means and so what
  the model must keep computing for them; with the flag (revision 4's
  R8) the access is suppressed and `STATUS[5]` is raised instead.
  Neither is a refusal. The refusal is at LOAD, and only when the
  device cannot honour the flag at all.
- a **missing, wrong-size or unwanted bank**: a `BANK_EXT` program run
  without one, or with a number of values that is not `n_consts`, or a
  self-contained program handed one. Two sources for a constant is one
  source too many, and a run whose constants nobody agreed on is the
  failure the whole feature exists to make impossible. The **scratch
  block** carries the same three refusals in the same shape: a
  `SCRATCH_IO` program run without the block it declares, one whose
  block is not `n * n_scratch_in` values, or a program that declares
  none handed one.
- a program that names a register above 15, or uses `kx` or `IMUL`, or
  is `BANK_EXT`, or uses the scratch, or declares scratch I/O, or names
  a constant at or past 256, on a device whose CAPS or CAPS2 does not
  publish that feature - by name, naming the instruction, before the
  register map is touched. An old tile has no rule that would refuse any
  of them: its operand mux reads the low four bits of a register field
  or the low eight of a constant index, its FETCH reads constants out of
  an image that may have none, its integer group answers opcode 30 with
  the unassigned-opcode result, and it decodes an unknown control code as
  `HALT`.
- **any field an instruction does not read being non-zero.** An ALU
  instruction has no immediate; `DEPOSIT` reads only `ra`. Leaving
  those free would mean one operation had many encodings, and then a
  readback hash is not a hash of the program - which is the whole
  point of being able to read the program back. It also keeps the
  natural RTL honest, since a shared operand-fetch mux would otherwise
  see a stray `ka` on a `DEPOSIT` and index a constant bank that may
  be empty.

  `kx` is four more applications of that same rule, not a new one:
  under `kx` an operand whose `k` bit is set takes its index from
  `imm`, so its four-bit field is not read and must be zero; an
  operand whose `k` bit is clear names a register, so its byte of
  `imm` is not read and must be zero - and, since revision 3, so is
  its NINTH index bit, which is read only under `kx` for an operand
  whose `k` flag is set; `imm[31]` is read by nothing;
  and `kx` itself selects nothing when no operand names a constant, so
  that combination is refused too - it is a second spelling of an
  ordinary three-register instruction. `kx` on a control instruction
  is refused for the same reason `ka` on a `DEPOSIT` is.

  The five-bit register fields are four more applications of it again.
  `imm[27:24]` are the fifth bits of `rd`, `ra`, `rb` and `rc`, so: an
  operand whose `k` bit is set names a CONSTANT and its register high
  bit is read by nothing (under `kx` too, where the index is a byte of
  `imm` and the high bit is not part of it); a control instruction
  reads at most `ra`, so `DEPOSIT` and `SETACT` may set `imm[25]` and
  nothing else in that nibble, and `HALT`, `ENDREP` and `ACTALL` may
  set no part of `imm` at all. `REPEAT` is the one exception and is not
  really one: it reads `imm` in full as its trip count and names no
  register, so there is no field there for a high bit to belong to -
  which is also why `REPEAT 0xffffffff`, the program the worst-case
  bound above exists for, is still a legal encoding and still runs
  identically on a revision-1 tile.

  Revision 3's four scratch codes are four more applications again,
  and they are the reason the rule is worth stating as a rule rather
  than as a list. `STL` reads `ra` and `imm[23:0]`, so `imm[25]` may
  be set and nothing else may; `LDL` writes `rd` and reads
  `imm[23:0]`, so `imm[24]` may; `STX` reads `ra` and `rb` and `LDX`
  writes `rd` and reads `rb`, so those two may set their own two high
  bits and must leave `imm[23:0]` at zero, because their slot comes
  from a register and the immediate is read by nothing - `imm[23:12]`
  since revision 8's proposed R22 made `imm[11:0]` their post-step. On
  all four, every remaining register field, `rnd`, `ka`/`kb`/`kc` and
  `kx` must be zero.

  One redundancy is deliberately NOT refused: a `kx` instruction whose
  indices all happen to be below sixteen is a second spelling of a
  plain `k` instruction, and it loads. The rule is about fields the
  encoding does not read, not about which of two legal encodings a
  compiler chose - the same latitude a unary `ABS` with a non-zero
  `rb` has always had.

## Deposition, and the buffer that bounds it

`max_deposits` is declared in the header and fixes the output shape at
`n * max_deposits` elements. A lane whose deposits exceed it drops the
excess and raises a sticky **deposit-overflow** bit in `STATUS` - bit
**4** - not in `FLAGS`: the five IEEE flags mean what 754 says they
mean, and "your buffer was too small" is not one of them. (This bit
lived at 3 until 2026-09-01, when the trimmed-build precision refusal
took STATUS[3] in the RTL; the sequencer's bit moved while it had
never crossed a device boundary, which is the last moment moving it
cost nothing.)

**A slot a lane never wrote reads as `+0`, and that is normative.** It
has to be: a run whose untouched slots kept whatever the host buffer
happened to contain would not be bit-exact, and two machines would
disagree about memory neither of them computed. So the device writes
every slot in the window, whether or not the lane deposited into it.

Because `+0` is also a perfectly good thing to deposit, the count is
not recoverable from the buffer, and `cft_program_run` returns the
per-lane deposit counts alongside it.

Dropping rather than growing is deliberate. A buffer that grew would
make the output length depend on the data, and an output length that
depends on the data is a result that cannot be compared against
another machine's without knowing how far it got. Truncation is
visible, bounded, and reported.

This is also the number that dominates area on a chiplet. Deposits
have to be buffered on-chip before they reach memory, and that buffer
is `lanes * max_deposits * element_bytes` of SRAM, which at fp256 and
any generous deposit budget is larger than the arithmetic it serves.
Trading compute width for deposit depth is the real design axis there,
and it is why `BEAT_BITS` is already a parameter and why the quarter
tile exists.

## What the RTL looks like

Written down before the implementation, while the analysis above was
fresh, so it started from a settled shape rather than re-deriving one -
and left standing here because the shape held. v1 deviated from it in
exactly one place, the ALU array, and was charged 124,057 LUT for the
deviation before coming back to it; the paragraphs at the top of this
file are that history.

`cft_seq` is a peer of `cft_engine_stream`, not a replacement: it
shares the same AXI master and the same CSR block, and a MODE bit
selects which one owns a run. The ALU array is the same array - the
same `cft_opmux` / `cft_simpleops` / `cft_fpfma_pipe` per lane per
beat - because P1 says the sequencer introduces no arithmetic, and
sharing the instances is how that stops being a promise and becomes a
fact about the netlist.

One thing the shape did not say, and silicon-adjacent evidence did
(2026-09-02): the sequencer's three operand buffers live in three
different memories on a banked device. `link.cfg` binds each of the
tile's masters to its own HBM pseudo-channel, for ordering; a read
of buffer B through master A therefore reaches a bank that does not
hold it, and the first hw_emu run failed every program with a bus
fault. `cft_seq` now names the buffer each read belongs to
(`m_rd_sel`) and `cft_krnl` steers the request at the master that
owns that bank; the bench that proves it gives each master a private
store and refuses the old routing by name. Note for other memory
systems: on a board where all masters reach one DDR or one PCIe
window, the steering is a no-op and any master would do - the fix
costs nothing there and is required here.

Four structures, sized in the section above:

- **Register file**, organised beat-wide rather than lane-wise:
  `regs[reg][beat]` is one 256-bit word, so a whole beat's worth of
  one register is a single read. Three reads per cycle (a, b, c) means
  three read ports, which is a dual-port BRAM plus one mirrored copy -
  a familiar shape, and the reason the file is indexed this way rather
  than by lane.
- **Instruction memory**, written through the AXI master before the
  run and readable back for attestation.
- **Deposit buffer**, written by lane index, drained to memory in
  index order.
- **Scratch** (revision 3), addressed `{slot, beat}` exactly as the
  register file is addressed `{reg, beat}`, with one write port and
  one read port because that is all four codes need. One thing it
  takes from the deposit buffer rather than the register file: each
  32-bit word bank carries its OWN address, because `STX` and `LDX`
  take the slot from `rb` and the lanes of one beat hold divergent
  `rb` values. A shared address would make an indexed access
  lane-serial; independent banks make divergent addresses free, which
  is the same argument that gives the deposit buffer per-bank write
  addresses for divergent deposit counts.

  The scratch is wiped to `+0` per lane block, as the register file
  was until revision 5 (it carries a valid bit per entry now and reads
  `+0` where nothing has written) - but only as far as the program can reach into it: every slot if
  the program indexes, otherwise the highest static slot it names and
  the slots the scratch-out drain will read. Wiping all of it every
  block would cost `SCRATCH_D * NBEATS` cycles - 4,096 at 256 slots,
  eight times the register file's - whether or not the program owns a
  slot, and a program that names none must cost nothing for a memory it
  never touches. Until revision 7 a program that INDEXED paid the whole
  of it every block, and at the U50's revision-7 depth of 2,048 that
  would have been 32,768 cycles, eight times as much. Since revision 7
  the wipe also stops at the highest slot anything has written since
  the last one (a dirty mark a word bank), so an indexing program pays
  for what it wrote - one that stays below slot 256 costs the same at
  2,048 slots as at 256 (revision 7, below).

The control began as an issue/drain state machine, and the counts fell
out of the sizing: issue `LATENCY` beats of one instruction back to
back, then drain `LATENCY` cycles while the results retire and write
back, then advance the program counter. Every ALU was busy during
issue, so a dependent chain cost `2 * LATENCY` cycles per instruction
rather than `LATENCY` with one ALU busy - a factor of `lanes_per_beat *
LATENCY` more work per cycle than the naive schedule. Since revision 5
(R12 to R15 below) the instructions overlap: the next issues while this
one retires, so an independent instruction costs its beats and, on a
single-pass tile, a dependent one about `LATENCY + 1`. Until revision 7
a control code that read the file, moved the mask or ended the block
still waited for the results to land; since R18 the codes that walk the
beats go through the same pipe and wait only for a result they read,
and only what ends the block waits for everything.

Two things the state machine does not need, both because the early
exit is allowed to be late (P3): the `any(active)` reduction can use
the mask as it stood an iteration ago, and the loop back-edge needs no
pipeline drain to evaluate it.

## What the host sees

`cft_run` is unchanged. A new call sits beside it rather than
replacing it, exactly as `docs/HOSTAPI.md` said it would:

    cft_status cft_program_load(cft_device *dev, const void *program,
                                size_t bytes, cft_program **out);
    cft_status cft_program_run(cft_program *prog,
                               const void *a, const void *b,
                               const void *c,
                               void *deposits, uint32_t *counts,
                               size_t n,
                               uint32_t *flags, uint32_t *bus);

Three input streams, not one: `r0`, `r1` and `r2` load from `a`, `b`
and `c`, exactly as `cft_run` reads them, which is what lets a
sequencer run reuse the engine's existing input path. `counts` is the
per-lane deposit count, and it is an output rather than a convenience
because `+0` is both a legal deposit and the defined value of an
untouched slot.

Two more entry points sit beside it rather than replacing it, one per
revision: `cft_program_run_bank` for a `BANK_EXT` program's constants
(R3), and `cft_program_run_ex`, which takes a `cft_run_args` struct
carrying everything a run can carry - the streams, the bank, the two
scratch blocks, the outputs (R5's ABI 0.10), and since ABI 0.14 the
index tables and the lane mask (R16, R17). The struct exists so the
positional signatures stop growing by an argument a round; the older two
remain as wrappers that fill it, and a program that declares scratch I/O
refuses both by name and takes `run_ex`. The model's `run(prog, a, b, c,
bank=None, scratch_in=None)`, with `idx_a`, `idx_b`, `idx_c`,
`idx_scratch_in` and `lane_mask` keywords since revision 6, is the same
shape, and returns the scratch-out block beside the deposits.

Partitioning across tiles, beat padding and flag accumulation stay the
library's problem, and stay invisible. Because deposit addresses
derive from the global element index (P2), the library can hand tile
*t* a contiguous index range and its own slice of the deposit buffer
with no further coordination.

## The first customer

The library itself (2026-09-01): `cft_div` and `cft_sqrt` issue their
whole composed sequence as one program on any device that can run one
- seed, Newton, the truncating Markstein finish, the restore passes
as branchless CMPLT/SELECT with IADD/ISUB ulp steps - instead of
~25-30 elementwise round trips. python/cft_golden/seqprogs.py is the
program's specification (mirroring sequences.py the way sequences.py
mirrors softfloat.py), divsqrt.c's program route is the C port, and
the matrix holds all three bit-identical, flags included. It is a
useful existence proof of the design's claim: a real correctly-rounded
algorithm - conditionals, encoding surgery and all - fits the
six-control-code ISA with no additions: the quotient in 43 to 49
instructions and six constants, and the root in 51 to 60 instructions
and nine, fp32 to fp256 (programs/div-*.cfta and sqrt-*.cfta).

## What the workloads asked of the program model (2026-09-04)

Five workloads were written against the contract after the first
customer (docs/BENCHMARKS.md, "Workloads designed for the contract"),
each told to run its inner step as a program where the model could hold
it and to say precisely what stopped it where it could not. Four of the
five stopped somewhere, and the asks below are theirs, recorded here
because this is where the next revision of the model will be designed.
None was built then - two are now, marked below; all five tools keep a
host loop that is bit for bit the program's equal, so nothing waits on
them.

- **More input streams, or a way to load registers from the deposit
  buffer** (Collatz, orbits). **BUILT, revision 3**, as R5's scratch
  block: the host preloads the first `n_scratch_in` slots of every
  lane before the run and reads the first `n_scratch_out` back after
  it, so a program is entered at any state it can spell and a run that
  writes its state out can be resumed by a run that reads it in. The
  ask as written was for more streams; what it needed was somewhere
  per-lane to put them, which is what the scratch is.
  *The original ask, for the record:* `cft_program_run` initialises
  `r0..r2` and the rest start at +0, so a program could be entered
  only at a state with three non-zero components. The Collatz step
  fits because its fourth value is an output that starts at +0; a
  planar Kepler orbit fit at step 0 only, so the whole integration was
  one call that could not resume; the outer solar system's thirty
  values could not enter a program at all.
- **An optional per-element flag output** (Collatz). `flags_out` is a
  union over the call, so a program that spans many iterations and
  elements cannot say which element left exactness; the Collatz tool
  proves exactness per element with a witness FMA instead, and its
  negative control B shows the union check is necessary and not
  sufficient.
- **More than sixteen addressable constants** (enclose). **BUILT,
  2026-09-07**, as `kx` above: `imm`'s low three bytes carry the three
  constant indices and the bank reached 256; revision 3's ninth bit at
  `imm[30:28]` took it to 512. The interval Horner is one
  program to degree 127 where it was sixteen chunks, its arithmetic
  intensity goes from 6.6 to 102.6 operations per element moved, and
  the chain it prints is unchanged at every format - which is the gate
  the feature had to pass, since indexed constants reorder nothing and
  re-associate nothing. docs/ENCLOSE.md carries the measurement.
- **A per-iteration broadcast** (zoom). The perturbed pixel step needs
  two values that change every iteration and are shared by every
  lane - the reference orbit's point - and there is no operand source
  shared by every lane that advances with the loop counter: a fourth
  stream read by iteration index, or a constant bank the counter can
  address.
- **A lane shift and an in-program cross-lane reduction** (Mersenne).
  A carry chain reads a neighbour and a convolution sums across lanes;
  a lane has thirty-two private registers and 256 private scratch
  slots and no path to another lane (it had sixteen registers when the
  ask was written; revision 2 widened the file, revision 3 added the
  scratch, and neither added the path - lane *i*'s slot *s* is
  reachable by lane *i* alone, which is what keeps P2 true of the
  scratch as it is of the deposit buffer). A read
  of register r of lane i-1 would put the whole carry propagation
  on-chip as one REPEAT with SETACT on "still carrying"; a reduction
  would put the convolution there too. A partial workaround exists
  without hardware: two input streams on the same array at different
  offsets let a lane see its neighbour's input.
- **A callable composed operation** (orbits, enclose). `cft_div` and
  `cft_sqrt` are programs themselves - partitioned host-prep,
  program-core, host-finish on the default route, where the core alone
  uses thirteen registers, and whole on the opt-in divfull route
  (2026-09-14, `CFT_DIVSQRT_FULL=1`), which uses registers up to
  `r31` - so neither can be inlined into another program's loop body; any kernel that needs correct rounding inside its loop leaves
  the program for it. The same is true of `cft_reduce`, whose tree is
  not in the ISA.

Two facts to keep beside the list. The magic-constant floor - add 2^(p-1)
and subtract it - is exact but raises inexact on every non-integer
operand, which is why the Collatz tool reads parity off the encoding
with the integer opcodes and why the Mersenne tool uses the constant
only as a whole-number gate; and the program engine's margin over the
host loop on the software backend is 1.06 to 2.1 times, set by how
much of the step the program holds, which is a statement about a slow
backend and not about the tile.

## Revision 2 (2026-09-08): thirty-two registers, 4,096 instructions, a per-run constant bank

Three changes, each one of docs/ATLAS.md's requests from the det
library's port, each announced in CAPS and refused by name where a
device lacks it. The card-day images (VERSION 0x600, ed752dd) predate
all three and are unaffected: the host runs them exactly as before and
every tool keeps the fallback it has. This section is the CONTRACT the
2026-09-08 round is built against; the sections above describe the
model as it was, and the round updates them to match.

### R1. Five-bit register fields

*Feature bit CAPS[5] = `cft_caps.seq_features` bit 1 =
`CFT_SEQ_FEAT_REGS32 0x02u`.*

Each lane owns **32 registers**. A register field is five bits: the
low four stay in the operand fields where they are, and the fifth bit
of each lives in `imm[27:24]`, which every ALU form reserves today:

| bit | meaning |
|---|---|
| `imm[24]` | `rd[4]` |
| `imm[25]` | `ra[4]` |
| `imm[26]` | `rb[4]` |
| `imm[27]` | `rc[4]` |

`imm[31:28]` stays reserved-must-be-zero. The reserved-field rule
applies unchanged and settles every corner: an operand whose `k` bit
is set names a constant, so its high bit is not read and must be zero
(under `kx` too - the constant index is the byte of `imm`, the
register high bit is not read); a control instruction reads at most
`ra` (`DEPOSIT`, `SETACT`), so on those two only `imm[25]` may be set;
`HALT`, `ENDREP` and `ACTALL` carry no `imm` at all; and `REPEAT`'s
`imm` is its trip count, read whole, so there these bits are
trip-count bits and not register bits - the rule binds instructions
that name a register, which is how the model, the library and the
assembler all read it, and how `REPEAT 0xffffffff` stays loadable for
the worst-case bound to refuse. `r16..r31` start at `+0` like `r3..r15`;
`r0..r2` still load from the streams. Nothing else in the encoding
moves.

Old loaders refuse any set bit in `imm[31:24]` (the `kx` reserved
mask), which is the version guard. A new loader refuses a program that
names a register above 15 on a device whose CAPS[5] is clear, naming
the instruction and the register, because an old tile's operand mux
would read the low four bits and silently address the wrong register -
the same reasoning that made `kx` need a CAPS bit.

RTL: `RF_D = 32 * NBEATS`, the register-file addresses widen by one
bit, the file doubles from 7.5 to 15 KiB a tile. The round MEASURES
that out of context (LUT, BRAM, timing at 135 MHz on the U50 part and
at the K325T's 100 and 120) and records it beside the change; if the
file cannot double at the card's clock the entry says so and the init
block of docs/ATLAS.md becomes the escape hatch. Nothing is shrunk to
make it fit. Model: `NREG = 32`, `encode`, `decode`, `run` and the
refusals.

### R2. Four thousand and ninety-six instructions

*No feature bit: CAPS[23:20] already publishes log2 IMEM_D, and reads
12.*

rtl/cft_krnl.sv sets `SEQ_IMEM_D` 1024 -> 4096; `PCW` becomes 12; the
header check and the worst-case instruction-count rule are unchanged.
Hosts learn `max_insns = 4096` from CAPS and nothing in the library
changes but its tests' expectations. Cost: 32 KB of instruction memory
a tile where it was 8, in block RAM.

### R3. The constant bank as per-run data

*Feature bit CAPS[6] = `cft_caps.seq_features` bit 2 =
`CFT_SEQ_FEAT_BANK_PTR 0x04u`.*

The header's `reserved[0]` (bytes 24..27) becomes **`flags`**. Bit 0
is **`BANK_EXT`**: the image carries NO constant section, `n_consts`
still says how many constants the program addresses, and every run
supplies exactly that many format-width values in a **bank** buffer.
`flags[31:1]` and `reserved[1]` stay reserved-must-be-zero. An image
with `BANK_EXT` set is therefore header, then `n_insns` instructions:
`bytes == 32 + 8 * n_insns`. One image per positive, loaded once, with
the levers, the clock and the pass riding as data.

**Register map: `BANK_PTR` at 0x64 (low) and 0x68 (high)**, kernel
argument id 8, name `bank`, on `m_axi_a` - it rides the A master as the
image does, and the two never overlap in time. The map grew, so
**VERSION 0x600 -> 0x700**; the host accepts {0x410, 0x500, 0x600,
0x700}. hw/kernel.xml gains the argument; hw/link.cfg and
hw/link_quad.cfg need nothing, since no master is added.

**The tile.** FETCH reads the header as today; with `flags.BANK_EXT`
set it reads the `n_consts` constants from `BANK_PTR` (dense,
format-width, exactly as the image's constant section is laid out)
and the instructions from `cfg_prog + 32`; otherwise from the image as
today. A set flag bit the tile does not know, or a non-zero
`reserved[1]`, refuses at the header (STATUS[3]) - the revision-2 tile
checks both words, which the 0x600 tile does not. That omission is why
CAPS[6] is the only guard that protects an old bitstream: its FETCH
would read constants from an image that has none. So
`cft_program_load` refuses a `BANK_EXT` image on any device whose
CAPS[6] is clear, by name, before the map is ever touched.

**Host API (ABI 0.9).** Beside `cft_program_run`, not replacing it:

    cft_status cft_program_run_bank(cft_program *prog,
                                    const void *bank, size_t bank_bytes,
                                    const void *a, const void *b,
                                    const void *c,
                                    void *deposits, uint32_t *counts,
                                    size_t n,
                                    uint32_t *flags_out, uint32_t *bus_out);

`bank_bytes` must equal `n_consts` times the format's element size. A
`BANK_EXT` program refuses `cft_program_run` (CFT_ERR_INVALID_ARGUMENT,
the message naming `cft_program_run_bank`); a program that carries its
own constants refuses a non-NULL bank. `cft_program_info` gains
`uint32_t flags`, struct_size-gated. The attestation the request
asked for:

    cft_status cft_program_digest(cft_program *prog,
                                  const void *bank, size_t bank_bytes,
                                  uint8_t out[32]);

SHA-256 over the image bytes followed by the bank bytes (the image
alone when there is no bank), so what ran is one hash of image and
data together. The library therefore carries a SHA-256; the tools
have one each today and share this one afterwards.

The software backend's executor takes the bank per run. The remote
backend's protocol gains the run-with-bank message, versioned so an
older server refuses it by name (docs/REMOTE.md). The XRT backend
writes `BANK_PTR`, passes the bank as argument 8, and sends an image
whose constant section is absent. The model's `Program` gains
`flags`, and `run(prog, a, b, c, bank=None)` takes the bank.

### CAPS after revision 2

| bits | meaning |
|---|---|
| [4] | `kx`, indexed constants |
| [5] | `REGS32`, five-bit register fields |
| [6] | `BANK_PTR`, the per-run constant bank |
| [7] | reserved |
| [23:20] | log2 IMEM_D, now 12 |
| [28] | `IMUL` |

`cft_caps.seq_features`: bit 0 `kx`, bit 1 `REGS32`, bit 2 `BANK_PTR`,
bit 4 `IMUL`.

### What revision 2 does not do

No `CALL`, no init block, no counter-indexed constant, no lane shift:
those stay on docs/ATLAS.md's list with the measurements that will
decide them. The wider per-sample input block is withdrawn by its
requester - with `IMUL` in, every per-sample value is integer
arithmetic in-lane over the index ramp.

## Revision 3 (2026-09-08, evening): a per-lane scratch memory, 16,384 instructions, a 512-entry bank

The second round of atlas-engine's asks (that repository's
docs/CFT-GAPS.md: thirty positives over thirty-two registers, six over
4,096 words, two over 256 constants, each measured over the scheduled
programs), plus what the round adds so the same seams are not reopened
next week. This section is the CONTRACT the 2026-09-08 evening round
builds against; the sections above describe revision 2 and are
updated by the round to match. Every feature is announced and refused
by name where absent. The revision-2 images of this afternoon predate
all of it and are unaffected.

*Built the same evening. What the tile's half cost, measured out of
context on the U50 at 135 MHz: +4,050 LUT (+3.4%), +28.5 block RAM
tiles, +7 UltraRAMs, and **0.000 ns** of timing - the worst path is
the streaming engine's FIFO into the FMA input register at +1.196 ns,
the same one, to the picosecond and to the pin, that was worst at
revisions 1 and 2. docs/VALIDATION.md's entry of that evening carries
the table, where the eight UltraRAMs went, and the one place the
contract left a choice.*

### R4. A per-lane scratch memory: load and store by slot

*Build parameter `SCRATCH_D = 256` slots a lane, a power of two,
published in `CAPS2[3:0]` as log2 with `CAPS2[4]` set; `cft_caps`
gains `max_scratch` (slots a lane, 0 = none or unknown); feature
`CFT_SEQ_FEAT_SCRATCH 0x100u` in `cft_caps.seq_features`.*

Storage is organised like the register file - `SCRATCH_D * NBEATS`
beats of `BEAT_BITS`, 128 KiB a tile at 256 - one write port and one
read port, and it is the lane's: lane i's slot s is reachable by lane
i alone. Four control codes (`ctrl = 1`):

| code | name | effect |
|---|---|---|
| 6 | `STL ra, imm[23:0]` | `scratch[imm] := ra` |
| 7 | `LDL rd, imm[23:0]` | `rd := scratch[imm]` |
| 8 | `STX ra, rb` | `scratch[rb mod SCRATCH_D] := ra` |
| 9 | `LDX rd, rb` | `rd := scratch[rb mod SCRATCH_D]` |

A store is a register write for P3's purposes - masked by the lane's
active bit, so an all-inactive loop body stays a no-op - and a load
writes `rd`, so it is masked the same way. Neither is arithmetic:
no rounding attribute, no flags, P1 holds as it did for `IMUL`. The
indexed form takes the slot from the low `log2(SCRATCH_D)` bits of
`rb`'s bit pattern, an unsigned integer where the atlas emitter keeps
its loop counters, reduced modulo the depth - the model does the same,
so the reduction is part of the contract rather than an accident.

The reserved-field rule settles the encoding: `STL` reads `ra` (its
high bit at `imm[25]` may be set) and `imm[23:0]`; `LDL` writes `rd`
(`imm[24]`) and reads `imm[23:0]`; `STX` reads `ra` and `rb`
(`imm[25]`, `imm[26]`), `LDX` writes `rd` and reads `rb` (`imm[24]`,
`imm[26]`), and for those two `imm[23:0]` must be zero; every other
field - the remaining register fields, `rnd`, `ka/kb/kc`, `kx` - must
be zero on all four. A slot at or past `SCRATCH_D` in `STL`/`LDL` is
refused by the loader by name, as a constant index past the bank is;
an indexed access is not refused, it is reduced. Slots start at `+0`
for every lane at the start of a run, except where R5 preloads them.
`seq.py` gets the four codes, `SCRATCH_D`, and the refusals; the C
executor the same; the RTL the memory, the two ports, and the four
codes in its decode and write-back, with the same latency discipline
as a register.

### R5. The scratch as a per-run block, in and out

*`CAPS2[5]` = `CFT_SEQ_FEAT_SCRATCH_IO 0x200u`.*

Two older asks - the init block (enter a program with more than three
loaded registers) and orbits' and Collatz's "load registers from a
per-lane block" - are one mechanism once the scratch exists: the host
may preload the first slots of every lane from a buffer before the run
and read the first slots back after it.

The header's `reserved[1]` (bytes 28..31) becomes **`scratch_io`**:
`[15:0] = n_scratch_in`, `[31:16] = n_scratch_out`, each at most
`SCRATCH_D`, meaningful only when **`flags` bit 1, `SCRATCH_IO`**, is
set (with the bit clear the word must be zero, as before). A
revision-2 tile refuses a non-zero `reserved[1]` at the header, which
is the guard; the loader refuses `SCRATCH_IO` on a device without
`CAPS2[5]` by name before that.

The buffers are lane-major and dense: lane i's slot s of the scratch-in
buffer is element `i * n_scratch_in + s`, format-width, `n *
n_scratch_in` elements in all; the scratch-out buffer likewise with
`n_scratch_out`. Padding lanes (index at or past n) receive nothing and
write nothing. The tile reads the scratch-in block for each lane block
after the image and the bank and before the first instruction, and
writes the scratch-out block for each lane block after its last
deposit; a run whose program declares no scratch I/O touches neither
buffer and neither pointer.

**Register map: `CAPS2` at 0x6C (read-only), `SCRATCH_IN_PTR` at
0x70/0x74 and `SCRATCH_OUT_PTR` at 0x78/0x7C** - address indices
10'h01B through 10'h01F, following BANK_PTR at 10'h019/10'h01A.
Kernel arguments: id 9 `scratch_in` on `m_axi_a` (it rides the A master
as the image and the bank do, in its own phase), id 10 `scratch_out` on
`m_axi_d` beside the deposits and counts. The map grew twice, so
**VERSION 0x700 -> 0x800**; the host accepts {0x410, 0x500, 0x600,
0x700, 0x800}, and binds the two scratch buffers on every 0x800 run
(a minimum one-beat buffer when the program declares none), as it
binds the bank.

`CAPS2`: `[3:0]` log2 `SCRATCH_D`, `[4]` scratch present, `[5]`
scratch I/O present, `[7:6]` reserved, `[31:8]` reserved for the
capacities and features that come next. `cft_caps.seq_features` bits
`11:8` mirror `CAPS2[7:4]`.

### R6. Sixteen thousand three hundred and eighty-four instructions

*No feature bit: `CAPS[23:20]` publishes log2 IMEM_D and reads 14.*

`SEQ_IMEM_D` 4096 -> 16384, `PCW` 14, 128 KB of instruction memory a
tile - four UltraRAMs on the U50 part, block RAM on the open-core
part. The header check and the worst-case bound are unchanged; hosts
learn the depth from CAPS and nothing in the library changes but its
tests' expectations.

### R7. A ninth constant-index bit: the bank to 512

*Feature bit CAPS[7], the feature nibble's last, = `cft_caps.seq_features`
bit 3 = `CFT_SEQ_FEAT_KX9 0x08u`.*

Under `kx`, `imm[28]`, `imm[29]` and `imm[30]` are the ninth bits of
the three constant indices - `ka`'s, `kb`'s and `kc`'s respectively -
the same construction as the fifth register bits in `imm[27:24]`, and
`KMEM_D` becomes 512 (16 KiB at beat width), which `CAPS[27:24]`
publishes as 9. A ninth bit is read only under `kx` for an operand
whose `k` flag is set; set anywhere else it is an unread field and the
program is refused. `imm[31]` STAYS reserved-must-be-zero: it is the
cheap version guard for whatever comes after this, and the largest
positive in the corpus needs 464 of the 512. Old loaders refuse the
set bits by the reserved rule; the loader refuses an index at or past
256 on a device whose CAPS[7] is clear, by name, because a revision-2
tile's operand mux would read eight bits and address the wrong
constant. `SEQ_ADDR_CONSTS` 512.

### Host API (ABI 0.10)

One entry point that takes everything a run can carry, so the
positional signatures stop growing by an argument a round:

    typedef struct cft_run_args {
        size_t      struct_size;          /* in: sizeof(cft_run_args) */
        const void *a, *b, *c;            /* the streams; b and c may be NULL */
        size_t      n;
        const void *bank;        size_t bank_bytes;         /* BANK_EXT programs */
        const void *scratch_in;  size_t scratch_in_bytes;   /* n * n_scratch_in * esz, or NULL */
        void       *scratch_out; size_t scratch_out_bytes;  /* n * n_scratch_out * esz, or NULL */
        void       *deposits;    uint32_t *counts;
        uint32_t   *flags_out;   uint32_t *bus_out;
    } cft_run_args;

    cft_status cft_program_run_ex(cft_program *prog, const cft_run_args *args);

`cft_program_run` and `cft_program_run_bank` remain, as wrappers that
fill the struct; a program that declares scratch I/O refuses both by
name and takes `run_ex`, and a program that declares none refuses a
non-NULL scratch buffer. Byte counts must match exactly. `cft_caps`
gains `max_scratch`; `cft_program_info` gains `n_scratch_in`,
`n_scratch_out` and `scratch_used` (one past the highest static slot,
or `SCRATCH_D` when the program uses `STX`/`LDX`), all behind
`struct_size`. The digest is unchanged - image then bank - and the
scratch-in block is run data the runner hashes on its own line. The
remote protocol gains `PROG_RUN_EX` (0x0024) carrying the struct's
buffers, refused by name by an older server; the software executor
takes the block per run; the XRT backend writes the two pointers and
passes arguments 9 and 10.

### What revision 3 does not do

`CALL` (41,435 words across the corpus, deciding no fit at 16,384),
the active mask scoped to a loop (six positives' inner loops, bounds
6 to 32), a per-lane flag output, and a counter-indexed constant: all
stay on docs/ATLAS.md's list with the measurements that will decide
them.


## Revision 4 (2026-09-11): an out-of-range scratch index is reported

One change, and a small one to describe: a program may ask to be told
when an indexed scratch access falls outside the memory it was given.
It exists because the depth is a BUILD PARAMETER, which makes a
correct-looking program silently portable in the wrong way.

This section is the CONTRACT; the sections above describe it. Unlike
revisions 2 and 3, it carries no build-cost note, and the reason changed:
when this was written the tile half had not been built, and since the
revision-4 pair (2026-09-13, from f636cf3) it has never been built ALONE
- that pair carried R8 and the scalar route together, and its entry in
docs/VALIDATION.md prices the pair (+0.210 ns kernel-side on the single,
+0.022 on the quad, the thinnest margin in the lineage) and not the
feature. A number for R8 by itself would have to be measured; none has
been, so none is given.

### R8. `SCRATCH_STRICT`: the index that is not there

*Header `flags` bit 2, `CFT_PROG_FLAG_SCRATCH_STRICT`. Device feature
CAPS2[6], `CFT_SEQ_FEAT_SCRATCH_STRICT`. Reports `STATUS[5]`,
`CFT_STATUS_SCRATCH_RANGE`. Assembler directive `.scratch strict`.*

`STX` and `LDX` take their slot from `rb`'s bit pattern read as an
unsigned integer - the register where the atlas emitter keeps its loop
counters. Since revision 3 that index has been reduced modulo
`SCRATCH_D`, and the reduction is part of the contract rather than an
accident: it is defined, it is the same in the model and in every
executor, and an out-of-range index has never been a refusal.

The cost of that is portability of the quiet kind. `SCRATCH_D` is a
build parameter. A program that walks 300 slots on a 256-slot tile does
not fail there; it wraps, computes a wrong answer, and returns it. Move
the same program to a 512-slot tile and it computes a different wrong
answer, or a right one. Nothing in the run says which happened.

With `flags.SCRATCH_STRICT` set, an index at or past the depth raises
`STATUS[5]`, the access is suppressed, and `LDX` reads **+0** - what an
untouched slot reads back as, never a stale register, which would make
the result depend on what the lane happened to be holding. The run
continues. That is deliberately the shape a deposit past `max_deposits`
already has: what fit is correct and reproducible, and the report says
what was lost. `STATUS[5]` is not an IEEE flag, for the same reason
`STATUS[4]` is not - the five in `FLAGS` mean what 754 says they mean,
and "the slot you asked for is not there" is not one of them.

With the bit CLEAR the modulo stands, unchanged and undated, so every
image built before revision 4 keeps its meaning exactly.

**Why a header flag and not a mode.** The program is the thing that
knows whether its indices are supposed to be in range. A run-time switch
would make the same image mean two things, and the reason the flag can
be added at all without a VERSION step is that `flags` has been
must-be-zero above its defined bits since revision 2 - so a tile that
has never heard of R8 throws the image back at the header rather than
running it with the old meaning. That guard is what makes an
announced-and-refused feature cheap, and it is the third time it has
paid for itself.

**Detecting it is the work, not branching on it.** Both executors read
the slot from the low `log2(SCRATCH_D)` bits of `rb`, so before this
flag existed neither could SEE an out-of-range index - every index was
in range by construction. `libcft` now tests `cft_bn_bitlen(rb) >
SEQ_SCRATCH_LOG2`, which is exact at any register width because the
depth is published as a log2 and is therefore a power of two.

`rtl/cft_seq.sv` does the same, and has since 2026-09-11: `lane_oor_fn`
ORs the index bits above `$clog2(SCRATCH_D)` across every word a lane
owns, which is exact for the same reason and is not a wider comparator.
Suppression is per BANK while detection is per POSITION, through the
mapping `scr_addr_fn` already uses.

### What revision 4 does not do

*It is on silicon, which this paragraph denied until 2026-09-18.* The
revision-4 pair (2026-09-13) and every pair since publish CAPS2[6] and
load a strict image; an image older than that pair reads the bit as
zero and turns a strict image away by name. What a card had been ASKED
until 2026-09-17 was only that a strict image loads. That day
atlas-engine ran an index past the depth on the round-2 pair: the
deposits were right, the tile's own register read STATUS = 0x20 under
`CFT_XRT_TRACE`, and libcft handed the caller 0 - the XRT backend
reduced STATUS to bit 4 on the way out. Fixed on 2026-09-18, and
`device-test`'s scratch leg now runs the index past the depth on
whatever device it is given and reads the word back (section 2b; with
the report dropped it fails once a format and the deposits still pass,
which is exactly what the card had shown).

It does not change what a program without the flag computes, anywhere:
the modulo is untouched, and that is what every image built before
revision 4 means.

And it does not make the depth portable. A program that needs 300 slots
still needs a tile with 300 slots. What it makes is the difference
between having them and not having them *audible*, which is the part
that was missing.


## Revision 5 (2026-09-14): the per-lane costs

Measured on the card the same afternoon (docs/VALIDATION.md, "the
sequencer is the wall"): with resident operands, a program that only
HALTS cost 0.07 / 0.11 / 0.18 us per lane at fp32 / fp64 / fp128, each
deposit about 40 ns a lane more, and each instruction ~2.2 cycles a
beat - so a fifty-instruction pass over 8,192 fp64 lanes ran at about
2.9 M lane-passes a second a tile against the 107 M/s the elementwise
engine gives the same silicon. Nothing in a program's arithmetic was
the cost; the machine around it was. Revision 5 is five changes to
`rtl/cft_seq.sv` and no change to anything a program, a host or a
bitstream's caller can observe: the same deposits, counts, flags and
addresses, P2's layout untouched, no new CAPS bit because there is
nothing new to advertise - only that every block costs less. The model
(`seq.py`) runs one instruction at a time to completion and is the
definition; the machine now runs them overlapped and must agree with
it bit for bit, which is what the benches below check.

### R9. No register-file wipe: a valid bit per entry

`S_ZERO` wiped the whole file every block - RF_D = 32 x NBEATS = 512
cycles, sixteen cycles a lane at fp128 - so that r3..r31 read `+0`. Now
one valid bit per `{reg, beat}` entry says whether the entry has been
written THIS block; the bits clear in the one cycle of `S_BLK_SETUP`.
A read of an unwritten entry answers `+0`. The FIRST write to an entry
writes every lane slice - the result where the lane's enable is on,
`+0` where it is off - and later writes mask per lane as before. That
is exactly `seq.py`'s state: a lane's register is `+0` until the lane
writes it while active, a masked write leaves it alone, and the only
slice a first write zeroes belongs to a lane that has never written the
register this block, whose value is `+0`. 512 flops and three 512:1
selects, in place of 512 cycles a block.

### R10. Operand streams on demand

All three streams were loaded every block. The image parser, on its way
past each instruction, notes which of r0..r2 the program names as a
REGISTER operand - a field with its `k` flag clear, under `kx` or not,
and the control codes that read one (DEPOSIT, SETACT, STL, STX read
`ra`; STX, LDX read `rb`) - and the block load skips the rest. Since
2026-09-15 "names" means READS: the opcode's operand use decides
(`op_reads` in the RTL, held to the model's own steering by
`tb/test_seq_core.py` for all 256 opcodes), so an ADD's defaulted `rb`
field costs nothing. Until then the rule over-approximated on purpose -
a unary opcode's unread field still counted, which only ever loaded
more - and R16 turned "more" into the whole table plus a round trip per
entry for a stream nothing read (found by round 2's V1). A program that
reads r0 alone (a square root, the normal-only mask) loads one stream
instead of three.

*Since revision 7 (R19)* a stream that IS read loads only the beats a
lane the caller has sits in - from the first to the last, one burst -
and nothing for a block whose lanes are all masked.

### R11. The drains, one element and one beat a cycle

The deposit drain spent three states an element (address, bank read,
pack). It is a pipeline: one element a cycle through the deposit banks'
two-cycle read, the tag - lane, slot, where in the beat it lands,
whether it closes the beat, whether it is the block's last - riding
beside the data, a completed beat handed to the write channel the cycle
it completes, and the whole pipeline held while the channel cannot take
it (the held address keeps the banks' output where it was, so nothing
in flight is lost). The count drain packed one count a cycle; a count
is four bytes whatever the format, so it packs a beat of eight lanes'
counts a cycle.

One slip on the way, and the unit bench's RAM caught it: the pipeline
can present a beat in the same cycle the previous one is accepted, and
`WLAST` was taken from the burst count BEFORE that acceptance - the
last beat of a burst went out without it. The old drains had the same
form and never reached a send in an acceptance cycle. Every send now
takes its `WLAST`, and its right to go at all, from the count the
master is about to have.

A second slip, found the same evening by R14's bench and recorded in
docs/VALIDATION.md: the pipeline held its address and its tags while
the channel could not take a beat, and this section's first draft said
the held address kept the banks' output where it was. The held address
is the NEXT element's, and the banks' read register, sampling every
cycle, moved on to that element's data while stage 2 still held the
stalled element's tag - so a stalled element went out with its
successor's data. It needs a drain longer than a burst and a beat
completing as the next burst is not yet open, which the suite never
did at a width that lands on the gap. The read register now holds with
the stall. 0843b62 and 6e1c418 carry the slip; no image built from them
should be trusted past one burst of deposits.

### R12. Instructions overlap: the next one issues while this one retires

An instruction cost its beats plus LATENCY plus fetch - about 38 cycles
at sixteen beats - because the machine waited for the last result of
one instruction to land before fetching the next, and the ALU pipe
stood empty for the whole of that wait. Now the destinations of up to
two ALU instructions are queued (`q_rd0` retiring, `q_rd1` behind it):
an instruction's last beat enters the array, its destination is queued,
and the NEXT instruction is fetched and decoded while the results land
- the retire path runs in every state, writing the head's beats as the
array delivers them and popping the head after its last. In-order, so a
write after a write lands in order; a later instruction writing a
register an earlier one READ is safe because the earlier one's reads
all left the file before its last beat issued. Every control code that
reads the file (DEPOSIT, SETACT, the scratch ops), moves the mask
(SETACT, ACTALL) or ends the block (HALT, the implicit halt) waits for
the queue to empty first; REPEAT and ENDREP read only the mask, which
no result moves, and do not.

*What that wait costs, measured on the card* (atlas-engine, 2026-09-17,
the round-2 pair; five fp32 programs that differ only in the pair of
instructions inside one `repeat 1024`, 16,384 lanes, the run alone on
the clock, every deposit buffer matching the model): an arithmetic
instruction **0.98 ns a lane** - about one cycle a beat at 135 MHz,
which is what R12 to R15 were built to reach - and a static scratch
store or load **3.9 ns**, an indexed one **4.0 ns**, a `SETACT`
**4.0 ns**: about four cycles a beat for every control code measured,
whatever it does. A `SETACT` that reads a register nothing near it
writes costs what an `STL`/`LDL` pair on one register costs, so the
cost is the drain this paragraph describes and not the memory. On the
software backend the order is reversed - a scratch access is half an
arithmetic instruction - so a program tuned on a host is tuned the
wrong way for a tile. What it is worth to a workload that spills:
atlas-engine's `throughput` makes 2,183 scratch accesses among its
14,801 instructions a lane, about two fifths of its instruction time at
these prices. Letting a control code join the overlap when nothing in
the queue writes what it reads is a revision-7 item in
docs/ROADMAP.md's debts, beside beat skipping.

*Revision 7 (R18) changed both halves of this section.* The wait is
gone: a control code that walks the beats waits only for a queued
result it reads, a beat at a time, and the loads are queued producers
themselves. And the inference above - "so the cost is the drain ...
and not the memory" - was half of it. The STL/LDL pair ran in a loop
with no arithmetic in it, so it had no drain to wait for: its four
cycles a beat were the states each code walked the block in, three
cycles a beat for a store, a deposit or a SETACT and five for a load.
The SETACT row had both, the drain behind the arithmetic beside it and
its own three a beat. R18 below prices each.

### R13. The one hazard, a beat at a time

Read-after-write is the hazard that remains: an instruction that reads
the destination now retiring. It could wait for the whole retire - and
did, for a day - which put every link of a dependent chain back at
beats + LATENCY, and every real program is a dependent chain. But
results land in beat order, one a step, and the issue reads operands in
beat order, one a step, two beats ahead of the array: beat b of the
dependent instruction needs only beat b of the retiring one to have
landed. So the wait moved from decode to the issue itself. The
instruction issues; at the cycle beat b's address would go on the bus,
if it reads the retiring destination (`iss_dep`) and that destination's
beat b has not landed (`wb_bt <= bt`), the issue machine and the file's
read registers hold a cycle (`raw_hold`) and try again - never the
array's standing request, which the array takes as usual, so nothing
fires twice and nothing in the two-ahead pipe is lost. "Landed" is
enough: the write is in the bank by the end of that cycle, and the
address put on the bus is read at the end of the next unheld cycle at
the earliest. At NBEATS 16 against LATENCY 16 a full block never
holds - the fetch and decode between two instructions are already one
cycle longer than the pipe needs - so a dependent instruction costs
exactly what an independent one costs: its beats, two cycles of read
lead and three of fetch and decode, 21 at sixteen beats. A block
shorter than the pipe (a run's last) holds for the difference, and a
multi-pass tile (`MUL_PASSES` > 1) steps its issue and its results on
the same enable, so the argument holds there unchanged.

The bench for it is `the_whole_divide_and_root` in `tb/test_seq_core.py`:
divfull's programs - some two hundred and ten instructions of dense
register reuse, the same register written and read three instructions
apart, written twice in a row, read by a SELECT the previous
instruction wrote, a masked lane beside an active one in every beat -
over a block boundary, in two rounding attributes, fp32/64/128, against
the model's one-at-a-time executor.

*Since revision 7* this "landed" rule is also the one two control-code
operands wait under: a SETACT's `ra` and an indexed code's `rb` (R18),
which F reads straight from the bank rather than through R15's
forwarding.



### R14. The beats never stop: fetch under the issue, three in flight

R12 and R13 left 21 cycles an instruction at sixteen beats: the beats,
a two-cycle read lead, and three cycles of fetch and decode between one
instruction's last fire and the next one's first address, during which
the array took nothing. The issue is now a three-stage pipe that runs
every cycle whatever state the machine is in: A puts a beat's three
register addresses on the file's bus (the state machine, in
`S_ALU_ISSUE`), B is the file's read, F fires the beat into the array
with the data on the bus and the constants the address stage's indices
fetched a stage ago (captured with the beat, read under the pipe's
hold - the first version read the bank from the instruction register
every clock, which the multi-pass tile caught the same evening). Each
stage carries the context of the instruction its beat belongs to -
opcode, rounding attribute, which operands are constants - because A
can be addressing one instruction's first beat while F fires the
previous one's last. The next instruction is read from the instruction
memory under this one's issue (the memory's one read register carries
`pc + 1` while an instruction issues and `pc` otherwise; fetch and the
skip take their word from the same register a cycle after presenting
the address) and, if it is arithmetic and the queue has room, admitted
the cycle after this one's last address. An instruction costs its
beats: sixteen cycles a block, one a beat, the floor of a one-beat-a-
cycle array.

Up to three instructions are then in flight - retiring, in the array,
being addressed - with their destinations queued from admission until
their last beat lands. Each operand of an admitted instruction that
names a register records the youngest queued producer of it as a
position from the head, which every pop moves down; the per-beat wait
of R13 becomes "hold A unless that producer is the head and its beat
has landed". The hold is on A alone. B and F drain what A already
addressed, and they must: with a block shorter than the pipe, the beat
A is waiting on can still be in F, and the first attempt - which froze
the whole pipe - waited for a landing it was itself preventing. Four
benches hung on two-beat blocks and said so.

What a dependent link costs now: the producer's beat fires from F,
lands LATENCY + 1 cycles later (the request is registered), is in the
bank the cycle after, is read the cycle after that and fires two cycles
on - 20 cycles behind the beat that produced it, so a dependent chain
costs 20 a link against 21 before. That is a data dependence through
the register file, not the machine; forwarding a landing beat straight
to F, from the array's output, from the write in flight or from the
write that landed as B sampled, would close it to 17, and is the next
step if the card says dependent chains are what remains.

The bench for it, `the_pipe_at_every_block_length` in
`tb/test_seq_core.py`: one program with every hazard shape - a chain,
a read of two producers at once, a write after a write, a write after a
read, constants at an instruction boundary, three independent
instructions then one that reads all three, a loop on itself, a mask
change mid-program, a register nothing wrote - at one, two, three,
five, nine and sixteen beats and ragged between, across a block
boundary, fp32/64/128, against the model.

*What revision 7 changed here* (R18). The state is `S_ISSUE` now, and
it addresses every instruction that walks the beats, not arithmetic
alone: DEPOSIT, SETACT and the four scratch codes are admitted the way
arithmetic is, and the continuation takes any of them. "Up to three in
flight" still holds, but it counts the instructions that WRITE a
register - arithmetic and, since R18, the two loads, which fire their
value into the array and retire through the queue; DEPOSIT, SETACT and
the stores act at F and take no queue slot. Every register operand of an
admitted instruction, a control code's included, records its youngest
queued producer the same way. An LDX adds two stages of its own (G and
H, R18) and the rule that keeps every other beat two steps behind it.


### R15. Forwarding: a dependent beat takes its operand as it lands

After R14 an independent instruction cost its sixteen beats and a
dependent one twenty: the producer's beat fires from F as a registered
request, lands LATENCY + 1 cycles later, is written the cycle after,
read the cycle after that, and fires two cycles on - four cycles of
register file between a landing and the fire that needed it. On a
single-pass tile the array accepts every cycle, so its validity line
can be shadowed exactly in the sequencer (`fs`, LATENCY bits: the top
is `al_ov`, the next lands next cycle, the one below the cycle after),
and a dependent beat's address goes on the bus as soon as the
producer's beat will have landed BY THE TIME F FIRES - two cycles on -
rather than once it is in the bank. F then takes the operand from
wherever it is: the array's output if it lands that cycle, the write in
flight if it landed the cycle before, or the write that landed as B
sampled, kept a cycle for the purpose; each merged word by word over
what B read, which is what the bank holds for the words the write does
not touch and `+0` where the entry was unwritten. Younger source first,
because the same address can appear in two of them only as one
instruction's write of it behind another's. A multi-pass tile keeps
R14's rule and reads only the bank (`FWD = MUL_PASSES == 1`).

| program | fp32, 128 lanes | fp64, 64 lanes | fp128, 32 lanes |
|---|---|---|---|
| twenty IANDs, one deposit | 607 -> 607 | 527 -> 527 | 487 -> 487 |
| twenty dependent FMAs, one deposit | 701 -> 653 | 621 -> 573 | 581 -> 533 |

Per instruction: 16 independent as before; a dependent one about 18
- (653 - 18 - 297) / 19 = 17.8 - which is LATENCY + 1 - the fire is a registered request and the landing
is what it waits for - so a dependent chain now costs what the array's
depth costs and nothing more.

*Since revision 7* a control code's DATA operand is forwarded the same
way - the value a DEPOSIT, an STL or an STX moves - and the shadow
beside `fs` carries more than validity: the row of active lanes each
request fired with, which is what the retire now writes and forwards
under (R18).

### What it measures

`make seqcycles` (`tb/probe_seq_cycles.py`, a diagnostic beside
`seqprobe`, not part of `make sim`): cycles per block through the unit
bench's harness, four blocks, model RAM (so HBM latency is not in these;
every cycle the state machine spends is). Five columns: before
revision 5, after R9-R11 (0843b62), after R12-R13 (6e1c418), after R14
(9891cfe), after R15.

| program | fp32, 128 lanes | fp64, 64 lanes | fp128, 32 lanes |
|---|---|---|---|
| halt only, no deposit | 729 / 61 / 61 / 61 / 61 | 657 / 45 / 45 / 45 / 45 | 621 / 37 / 37 / 37 / 37 |
| one IAND, one deposit | 1,219 / 299 / 297 / 297 / 297 | 955 / 219 / 217 / 217 / 217 | 823 / 179 / 177 / 177 / 177 |
| one IAND, four deposits | 2,573 / 837 / 835 / 835 / 835 | 1,733 / 565 / 563 / 563 / 563 | 1,313 / 429 / 427 / 427 / 427 |
| twenty IANDs, one deposit | 1,947 / 1,027 / 702 / 607 / 607 | 1,683 / 947 / 622 / 527 / 527 | 1,551 / 907 / 582 / 487 / 487 |
| twenty dependent FMAs, one deposit | - / 1,005 / 720 / 701 / 653 | - / 925 / 640 / 621 / 573 | - / 885 / 600 / 581 / 533 |

Per instruction, from the twenty-IAND row: 38 cycles before R12, 21
after, 16 after R14. The dependent row sits 18 cycles above the IAND
row at every format, and that is the r1 stream the FMA reads and the
IAND does not (sixteen beats and two of setup), not a wait: after R13,
(720 - 18 - 297) / 19 is the same 21 as the IAND's; after R14 it is
20 against the IAND's 16, the data dependence through the file; after
R15 it is about 18, LATENCY + 1 and a cycle at the first beat. Per
lane, one deposit: 9.5 -> 2.3 cycles at fp32, 14.9 -> 3.4 at fp64,
25.7 -> 5.6 at fp128.

Benches: `seq_core` 20/20 (the divide case and the every-block-length
case new), `krnlseq`, `seqbanks` and `faults` under Verilator and again
under Icarus; `yosys-lint` clean. The four-change commit is 0843b62,
the overlap 6e1c418, the streaming issue and the drain's read-register
hold the commit after it.

## Revision 6 (2026-09-15): indexed inputs, and a lane mask declared

The parcel round that follows ask 7 (docs/ROUND2.md) adds two things
to the program model, and this section is their CONTRACT, written at
the seam before either is built so that the parcel building each and
the parcel verifying it read one text. The software backend is the
definition and the model its authority, as everywhere here.

### R16. An input block fetched through an index table (P1, built 2026-09-15)

For a stream with a table, `A[i] = idx[i] == CFT_IDX_NONE ? +0 :
a[idx[i]]` for `i` in `[0, n)`, and the run proceeds exactly as a dense
run over `A`. For the scratch block, `S[i * k + s] = idx[i * k + s] ==
CFT_IDX_NONE ? +0 : pool[idx[i * k + s]]` with `k = n_scratch_in`,
lane-major as the block is. An index at or past the source's declared
length (`idx_*_src`) is refused before the run starts, on every backend,
by name and by value: a device must never read past a buffer for a
caller. `+0` is the format's positive zero encoding. There is no new
rounding rule and nothing for the model to define beyond these two
lines - the answer is what the dense run over the gathered block gives.
On the tile: four pointer registers (0x88..0xA0, kernel arguments
12..15), MODE[22:19] saying which blocks are indexed, CAPS2[9] saying
the bits are honoured; the sequencer reads a table's beats through the A
master and then one element per entry through the master that owns its
buffer, packs the elements into beats, and the register file never
learns the difference.

**What it is on the tile.** Four states in `rtl/cft_seq.sv`, entered in
place of `S_LD_GO`'s dense load for a stream and in place of the
scratch preload for the block. The two passes INTERLEAVE on the one
read channel the module has: a beat of the table - eight `u32` entries
at every format, because a table holds indices and not elements - then
one single-beat read per entry at that element's own beat, then the
next table beat. What comes back reaches the same two destinations the
dense loads use and by the same two paths: packed into a register-file
beat as `S_LD_STREAM` writes one, or written a slot at a time into the
scratch as `S_SIN_PARSE` writes one. `CFT_IDX_NONE` writes `+0` and
issues no read at all, and a stream no instruction reads is skipped
with its table by R10's `rd_need`.

The block's table starts at ENTRY `blk_base` (or `blk_base *
n_scratch_in`), which is four bytes an entry and NOT the dense
stream's `in_off`: that offset is scaled by the element size, and using
it would read a plausible neighbour's element at every format above
fp32. `tb/test_seq_core.py` asserts the gather's reads against the
table - one burst per table beat at the block's own entry offset, one
per non-sentinel entry at that element's beat, in order - so a slip of
one entry is an ADDRESS in the failure and not a number that looks
almost right.

**What it costs.** The read side carries ONE burst in flight
(`rd_burst_left`), so gathered elements do not overlap: on the card a
gathered element is one HBM round trip, where a dense beat of `lpb`
elements is a fraction of one. Through the unit bench's model RAM,
which answers in the cycle it is asked, what is left is the state
machine's own cost, and `make seqcycles` prints it beside the dense
table (four blocks, one IAND and one deposit, an identity table so the
two runs' answers are identical):

| | lanes | dense | gathered | reads dense / gathered |
|---|---|---|---|---|
| fp32  | 512 | 1,189 cyc (2.32/lane) | 3,425 cyc (6.69/lane) | 6 / 578 |
| fp64  | 256 |   869 cyc (3.39/lane) | 1,953 cyc (7.63/lane) | 6 / 290 |
| fp128 | 128 |   709 cyc (5.54/lane) | 1,217 cyc (9.51/lane) | 6 / 146 |
| fp256 |  64 |   629 cyc (9.83/lane) |   849 cyc (13.27/lane) | 6 / 74 |

About four cycles a gathered element at every format, which is the
table peel, the address, the return and the pack; the read count is
exactly the elements plus `ceil(blk_n / 8)` table beats a block, and
the bench derives both from the table rather than from this paragraph.
The dense numbers in "What it measures" above are unchanged by this
revision, which is the other half of the same probe.

Making a gathered element cost less than a round trip means more than
one read in flight, which the module's single-burst read side does not
do for anything - the image, the bank, the scratch preload and the
dense streams included. That is a change to the read side rather than
to the gather, and it is not in this revision.

### R17. A per-run lane mask (P3, built 2026-09-15)

Lane `i` with bit `i` of the mask clear runs no instruction. Its
deposit slots, its count and its scratch-out slots are NOT written - the
buffers hold what the caller put there, on the host and in a device
copy alike; the normative "+0 for an untouched slot" of the deposition
section applies to the lanes the run owns, and a masked lane is not one
of them. It contributes no flag, it is inactive for the early exit from
its first cycle, and it cannot raise deposit overflow. `ACTALL`
reactivates every lane THE CALLER HAS, and a masked lane is not one the
caller has. A run whose every lane is masked completes with nothing
written and nothing raised. All ones is bit-identical to no mask. On
the tile: MASK_PTR at 0xA8 (argument 16), MODE[23], CAPS2[10]; the
block's opening active mask is `blk_act & mask` and the three drains
skip a masked lane's elements.

**The MODE guard is one rule for every bit above 15.** A MODE bit the
BUILD cannot honour is refused at the CSR with STATUS[3] - the guard on
the reserved half of MODE, narrowed as each feature lands: MODE[18:16]
under CAPS2[7], MODE[22:19] under CAPS2[9], MODE[23] under CAPS2[10].
A bit the RUN'S KIND does not read is ignored: the scalar operand
(MODE[18:16]) on a program run, the lane mask (MODE[23]) on an
elementwise run. No library call produces either shape - `cft_run_args`
has no scalar field and `cft_elem_args` no mask - so only a raw
register write reaches it, and a run-kind refusal would be a new
sentence in this contract that had to refuse the scalar bits on program
runs too, on tiles already shipped. The rule is the build's, not the
run's (P3's question, 2026-09-15).

**What it is on the tile.** Two states in `rtl/cft_seq.sv`, between the
block setup and the wipe, and three write strobes. A mask bit is a LANE
at every format - it is the one ABI 0.14 field whose units are not
elements - so a 256-bit beat holds 256 consecutive lanes' bits, a block
is at most `NBEATS << 3` = 128 lanes, and `blk_base` is a multiple of
the block: a block's bits therefore never straddle a beat, and the
fetch is ONE single-beat read a block at every precision, at
`mask + ((blk_base >> 8) << 5)` with the block's bits at bit
`blk_base[7:0]` inside it. What comes back is ANDed into `blk_act` -
the lanes the caller has - so the block's opening `active` and `ACTALL`
read one expression and cannot drift apart, which is what makes
"`ACTALL` reactivates every lane the caller has" and "a masked lane is
not one the caller has" the same sentence in the hardware.

Everything else follows from the active bit, which already gates the
register writes, the deposits and the FLAG contributions per lane
(`wb_flags_or` ORs `lane_flags` under `wb_act`, which was the active
mask as it stood at the edge the result returned, and since revision
7's R18 is the row the beat FIRED with). The three DRAINS are the
exception and are the only new arithmetic: they are deliberately not
masked by the active bit - a lane that converged early still has
deposits and scratch worth carrying - so each is masked by the
CALLER's bit instead, as a WRITE STROBE. The element keeps its
position in the stream, because the deposit window is
`n * max_deposits` whatever the mask says, and loses its strobe; the
caller's bytes stay.

**What it costs, and what it does not save.** `make seqcycles` prints
it beside the dense and gathered tables (four blocks, one IAND and one
deposit - the same program in all three columns):

| | lanes | dense | half masked | all masked | reads |
|---|---|---|---|---|---|
| fp32  | 512 | 1,189 cyc | 1,205 | 1,205 | 6 -> 10 |
| fp64  | 256 |   869 cyc |   885 |   885 | 6 -> 10 |
| fp128 | 128 |   709 cyc |   725 |   725 | 6 -> 10 |
| fp256 |  64 |   629 cyc |   645 |   645 | 6 -> 10 |

**Four cycles and one read a block, and the same four whether half the
lanes are masked or all of them.** The block setup alone - a bare HALT,
no deposit, nothing to hide behind - shows the same figure: 60.8 ->
64.8 cycles a block at fp32, 44.8 -> 48.8 at fp64, 36.8 -> 40.8 at
fp128, 32.8 -> 36.8 at fp256.

That "all masked costs what half masked costs" is the important half,
and it is a statement about this machine's shape rather than about this
implementation: **the sequencer issues per BEAT, not per lane.** The
issue loop walks a block's `nb_blk` beats whatever the active mask
holds, and the active bit decides what is WRITTEN rather than what is
computed - the same reason a lane that drops out at `SETACT` costs its
block exactly what a lane that does not costs it. So a lane mask on
this tile buys the BYTES (a masked lane's outputs are the caller's),
the FLAGS (it contributes none) and, through `any(active)`, the EARLY
EXIT: a block whose every lane is masked leaves its loops at the first
test, which is the one shape where a mask is a large saving. It does
not buy back an idle lane's arithmetic, because an idle lane's
arithmetic was never separately paid for.

Making it buy that means skipping a beat with no active lane in the
ISSUE pipe, and skipping a beat nobody reads in the stream loads. Both
are changes to the machinery R14/R15 and R10 settled, neither is in
this revision, and the numbers above are what says whether they would
be worth making.

*Revision 7's R19 made both*: a beat with no active lane is no longer
issued, and a stream beat no lane the caller has sits in is no longer
loaded, so a mask that empties whole beats - and a SETACT that does -
now buys their compute too. Its section at the end of this file has the
numbers; the table above is its before-side.

On the card the fetch is one HBM round trip a block rather than the
four cycles model RAM charges (the read side carries ONE burst at a
time - R16's last paragraph), and the saving is unchanged, so the
card's number is this table plus a round trip a block.

### What revision 6 is at the seam

The registers, the version (0xA00), the MODE bits under the existing
guard, the two CAPS2 bits at zero, the struct fields and the feature
bits in `cft.h`, the model's signature, and a refusal by name on every
backend for every new field. The parcels replace the refusals; the
lead's seam tests hold the two together once both exist.


## Revision 7 (2026-09-29): the control codes in the pipe, and the beats no lane needs

Two changes to `rtl/cft_seq.sv`, parcel P1 of the revision-7 round
(docs/ROADMAP.md, "Revision 7"), and no change to anything a program, a
host or a bitstream's caller can observe: the same deposits, counts,
flags, STATUS and scratch-out as the round-2 images and the model, the
same CAPS, no new bit - only fewer cycles. The model still runs one
instruction at a time to completion and is the definition; the machine
runs them overlapped and is held to it bit for bit by the benches below.
Revision 7's third item, the program limits raised per build, is a
capacity rather than a cost and is recorded with the capacities.

### R18. The control codes join the overlap

**What it cost before.** Until this revision every control code that
read the file, moved the mask or ended the block waited for the queue of
results to empty (R12), and then walked the block's beats in states of
its own: DEPOSIT, SETACT and a store three cycles a beat, a load five.
The card priced the whole at about four cycles a beat (R12's note), and
the ODE census at 5.1 to 5.2 arithmetic instructions a scratch access
(docs/VALIDATION.md, steps 0 and 1a). It was both costs: a code after
arithmetic waited LATENCY and a few cycles for the drain, and every code
then walked sixteen beats at three or five.

**The rule, per code.** The six codes that walk the beats are admitted
into R14's pipe exactly as arithmetic is - A addresses a beat, B reads
it, F uses it, one beat a cycle - and each waits, a beat at a time, only
for a QUEUED producer of a register it reads (R13 to R15's `dep_v` and
`dep_pos`, gated by the code's own read set rather than by `ka`/`kb`/`kc`,
which a control code may not set):

| code | reads | writes | at F | its wait |
|---|---|---|---|---|
| `DEPOSIT ra` | `ra` | the deposit banks, its beat's counts | acts | `ra`, forwarded |
| `SETACT ra` | `ra` | its beat's row of `active` | acts | `ra`, landed |
| `STL ra, slot` | `ra` | the scratch | acts | `ra`, forwarded |
| `STX ra, rb` | `ra`, `rb` | the scratch | acts | `ra` forwarded, `rb` landed |
| `LDL rd, slot` | - | `rd` | writes, or fires | a queue slot |
| `LDX rd, rb` | `rb` | `rd` | addresses; writes or fires at H | `rb` landed; a queue slot |

- **Forwarded or landed.** A DATA operand - the value a DEPOSIT, an STL
  or an STX moves - is forwarded at F as an ALU operand is (R15). The two
  operands that feed deeper logic wait under R14's rule instead, "the
  producer's beat has landed", and are read straight from the bank: a
  SETACT's `ra`, which the magnitude test turns into `active`, and an
  indexed code's `rb`, which becomes the scratch address. Both paths
  are then the ones the old states had, with no forwarding mux in front,
  at the three cycles forwarding saves on a dependent link.
- **The loads are producers.** `LDL` and `LDX` write a register, so they
  take a queue slot at admission; the queue is in order, so a write after
  a write lands in order, and a later instruction that reads `rd` waits
  on the load per beat like on any producer. The value reaches the file
  through the one retire path there is: the load FIRES it into the array
  as IOR(v, v), the integer group's bitwise OR, which gives v back bit
  for bit at every format and raises no flag (`softfloat.ior`,
  `cft_simpleops`, held to each other at every format by the four pipe
  benches, whose `SIMPLE_OPS` include it). That is
  a schedule over a verified operation, not arithmetic of the
  sequencer's own (P1), and the retire takes no flag from a load in any
  case (below).
- **An LDL** knows its slot at A, so A puts the scratch's read address
  out with the file's, and the value is there at F. **An LDX** takes its
  slot from `rb`, which reaches the bus only at F: F forms the per-bank
  address (and R8's suppression), a stage G reads the scratch, and a
  stage H fires the value - two steps after a beat addressed with it
  would fire. So a beat that is NOT an LDX waits at A while an LDX beat
  is in B or F: two bubbles after an LDX, none before one, none between
  two. That keeps every fire in program order and gives the scratch's
  read address one owner a cycle.
- **A store, then a load of the same slot.** A store's bank write lands
  at the end of step A+3; an LDL reads at A+1 of its own, an LDX at A+3
  of a later A. So an LDL waits at A while a store beat is in B or F,
  whatever the slots and whatever the beats - which means at every block
  length: at sixteen beats a store straight before a load still costs two
  cycles (verifier-R4 measured ten such adjacencies at twenty cycles a
  block beside the same program with an IAND where the store is, and
  `store_then_load_costs_what_the_sentence_says` holds that as an upper
  bound). Only a store and a load of the SAME beat can meet - the scratch
  is addressed {slot, beat} - so a rule that compared the beats would bind
  only on a block of one or two beats, or across skipped beats: a possible
  gain, not built. An LDX needs no such wait, and a store after a load
  needs none: the load has read.

**Fast loads: the send-back (2026-09-29).** A load's value first went
into the file only through the array, as above. At sixteen beats the
pipelining hides the array's sixteen stages; at ONE beat nothing does,
and verifier-R4 measured a program that uses a loaded value at once
running slower there than on f681dee's tile, whose LDL wrote the file
itself in five cycles - and, on a multi-pass tile, where the array takes
a beat every pass period, loads and their users slower at every block
length, up to twice as slow at fp256. So a load is now FAST when, at its
admission, every queued writer ahead of it is a fast load too (an empty
queue included):

- It keeps its queue slot, so everything that reads its register tracks
  it exactly as any producer; but its value never enters the array. The
  retire's own write port writes it into the file at F (an LDL) or H (an
  LDX), under the row the beat fires with - the row the array path fires
  with - the head's reach `wb_bt` moves as a landing moves it, and the
  slot pops at the block's last beat. A load raises no flag either way.
- The port is free: every writer ahead of a fast load is fast and writes
  in program order, one beat a step, popping before the next one's first
  write; every writer behind it fires after its last F (an LDX's last H,
  which the gap guarantees) and lands LATENCY + 1 later. So no array
  result lands while a fast load writes, a fast load is the head whenever
  it writes, and writes to its register stay in program order - RAW, WAW
  and WAR as for any producer.
- Its reader waits for exactly its write, by R14's "landed" rule, on
  every port (the write moves `wb_bt`); forwarding's look-ahead has no
  landing to look at. The scratch rules do not move: a fast LDL still
  reads the scratch between A and F, a fast LDX at G, so the gap and the
  store-then-LDL wait are what they were.
- A load that cannot be fast rides the array, as above, on a single-pass
  tile - a full block hides the depth, and waiting would give the gain
  back. On a MULTI-PASS tile it waits at decode until it can be fast
  (every array writer ahead of it has landed): there a load through the
  array costs sixteen pass periods to issue and sixteen more for its user
  to wait, where f681dee's load waited for the same drain and then took
  five cycles a beat. After the wait it takes one.

Measured by `loads_cost_no_more_than_before` (Verilator, the unit
bench's capacities): verifier-R4's seven load-heavy programs at one, two
and three beats of lanes and at four whole blocks, every format - 112
rows at each MUL_PASSES - and, since, three more (below). Cycles from
start to done, f681dee's tile -> e610b78's (R18 and R19, before the
send-back) -> now:

| program | size | MUL_PASSES 1 | MUL_PASSES 10 |
|---|---|---|---|
| ten times: LDL, DEPOSIT of it | fp32, one beat | 294 -> 336 -> 234 | 294 -> 366 -> 234 |
| ten times: LDL, DEPOSIT of it | fp256, one beat | 224 -> 266 -> 164 | 224 -> 1,783 -> 164 |
| ten STL/LDL pairs on one register | fp32, one beat | 373 -> 431 -> 311 | 373 -> 461 -> 311 |
| eight times: LDL, FMA of it, STL of that | fp32, one beat | 620 -> 632 -> 619 | 620 -> 680 -> 545 |
| eight times: LDL, FMA of it, STL of that | fp256, one beat | 613 -> 625 -> 612 | 1,780 -> 3,053 -> 1,698 |
| twenty LDLs, DEPOSIT of the last | fp256, four blocks | 8,312 -> 2,832 -> 2,820 | 8,312 -> 14,916 -> 2,820 |
| twenty LDXs, DEPOSIT of the last | fp256, four blocks | 23,488 -> 18,016 -> 18,004 | 23,488 -> 30,081 -> 18,004 |
| eight times: LDL, FMA of it, STL of that | fp256, four blocks | 7,005 -> 3,121 -> 3,113 | 15,969 -> 17,117 -> 12,291 |

At MUL_PASSES 1, e610b78 was slower than f681dee on 12 of R4's 112 rows -
three programs at one beat, at every format - and at MUL_PASSES 10 on 74:
fp128 and fp256 at every size, fp64 at one to three beats, fp32 at one and
two. Now none is, at either: every row is faster than f681dee's. The
closest is the census chain at one beat on the single-pass tile, 620 ->
619; at MUL_PASSES 10 every one of the 112 is at least 60 cycles under.
The bench holds every row it runs to f681dee's cycles at either
MUL_PASSES. It runs every size but four blocks at fp32 and fp64, where
e610b78 was faster than f681dee already and which cost most of its time;
those rows are measured, and recorded in its table. e610b78's own rows
are red against it at both MUL_PASSES (12 and 74, every one at a size it
runs).

R4's seven programs are fixed by fast loads alone: with the multi-pass
policy planted out - a load that cannot be fast rides the array on a
multi-pass tile too - not one of their rows is slower than f681dee's.
None of them has a load straight behind an array writer still in
flight: every load finds the queue holding only loads, or, in the
census chain, its store has already waited for the FMA. The hold's
last three programs are that shape - eight times an FMA nothing reads
and a load behind it, then a deposit of the load, or an FMA of it - and
there, at MUL_PASSES 10, riding the array is slower than f681dee's
wait-then-load at fp256 over four blocks: 15,724 -> 16,682 cycles with
an LDL, 31,681 -> 32,611 with an LDX. The policy makes them 12,523 and
28,483, so it stays, held by those rows; with it planted out the bench
is red on them. It is not the faster choice everywhere: behind an FMA
of the loaded value at fp128 over four blocks riding costs 9,105 and
the policy 9,427, both under f681dee's 11,862. At MUL_PASSES 10 and one
beat, at fp64, fp128 and fp256 - the rungs whose pass period is more
than one - the policy is under f681dee's on all nine rows: by 43 to 87
cycles on eight, and by 3 on the LDL and its deposit at fp256 (1,645
against 1,648), less than that rung's pass period of 10. Riding is
under f681dee's by 40 to 91 cycles at fp64 and fp128, and within two
cycles of it, either way, at fp256 (1,650, 5,621 and 1,884 against
1,648, 5,621 and 1,886). Neither is always the faster of the two: the
policy is faster by 40 to 85 cycles on three rows (the LDX at fp128
and fp256, the LDL and an FMA of it at fp256), riding by 23 and 35 on
two (the LDL and its deposit at fp64 and fp128), and the other four
differ by 5 cycles or less. (Until verifier-R4 measured them, this
said that at one beat the three were within a pass period of each
other; one row of the nine is.) On the single-pass tile the same three
programs ride the array and are well under f681dee at every size (fp32,
one beat, the LDL and its deposit: 541 -> 439).

**The pass phase: a multi-pass tile's cycle counts are exact to a pass
period, not to a cycle.** The array's enable counts wall cycles from the
reset (`ph` in `rtl/cft_lanes.sv`), so a run starts at whatever phase of
the pass period the runs before it left, and a count with arithmetic in
it moves with that phase by up to a period less one - measured: f681dee's
census chain at fp256 cost 1,937 cycles in one run of the hold and 1,945
in another, with nothing else changed but the runs before it. So a hold
that compares a count with a before-side measured in another run must
allow that much at MUL_PASSES above 1, and
`loads_cost_no_more_than_before` does (up to nine cycles at fp256, none
at fp32, whose period is one); the older holds' ceilings sit hundreds of
cycles clear of their counts. On the single-pass tile a count is exact
and repeats to the cycle (98 of 98 rows, run twice).

On the single-pass tile a load behind an array writer still rides the
array, which a full block hides and a short one does not. fp32's census
chain costs 619, 638 and 659 cycles at one, two and three beats there,
and 545, 564 and 585 on the multi-pass tile - single-pass at fp32 too,
but it forwards nothing, so each store waits for its FMA to land and the
next load goes fast. At four blocks riding wins, 3,673 against 3,713. A
single-pass tile that waited on a short block would take those cycles: a
possible gain, not taken, since no row is slower than f681dee's without
it.

**The mask, and when it is sampled.** The active bit decides what a
result WRITES, and until this revision the retire read it when the
result came back (`row_act_fn(active, wb_bt)`) - right only because no
code could move the mask before the queue had emptied. A SETACT now
narrows the mask at F while earlier results are still in the array, so
the row is taken when a beat FIRES: it rides beside the request
(`al_row`) and down a shadow of the array's validity line (`fr`, beside
`fs`, shifting on the array's own enable, so it is exact on every tile),
and the retire writes, forwards and ORs flags under it. A second shadow
bit (`fq`) is off for a load, so "a load raises no flag" does not rest
on IOR's. `ACTALL` widens the mask, so it waits for the PIPE to empty -
every earlier beat has taken its row - and not for the queue. REPEAT and
ENDREP wait for nothing, as before: the mask they test can be stale only
on the wide side (a SETACT still narrowing it), which runs one more
iteration with every lane inactive - a no-op by P3, which is what the
early exit was always allowed.

**What ends the block** - HALT, an unknown code, an unmatched ENDREP,
the implicit halt, a skip past the end - waits in `S_DRAIN_SETUP` for
the queue AND the pipe: every result landed, every deposit and store
written, before a drain reads them. Before, HALT, an unknown code and
the implicit halt waited for the queue, and an unmatched ENDREP and a
skip past the end went straight on - only an image that bypassed the
loader reaches either of those two.

**What it costs now.** `make seqcycles`, four blocks, cycles a block,
before (f681dee's tile, run on c183e84) and after (1268bc9):

| program | fp32, 128 lanes | fp64, 64 lanes | fp128, 32 lanes |
|---|---|---|---|
| twenty IANDs (the reference) | 607 -> 557 | 527 -> 477 | 487 -> 437 |
| twenty STLs, independent | 1,598 -> 865 | 1,518 -> 785 | 1,478 -> 745 |
| twenty LDLs, independent | 2,220 -> 850 | 2,140 -> 770 | 2,100 -> 730 |
| ten STL/LDL pairs on one register | 1,740 -> 717 | 1,660 -> 637 | 1,620 -> 597 |
| ten STX/LDX pairs | 5,712 -> 4,680 | 5,632 -> 4,600 | 5,592 -> 4,560 |
| twenty SETACTs | 1,287 -> 554 | 1,207 -> 474 | 1,167 -> 434 |
| ten IAND, SETACT pairs | 1,155 -> 572 | 1,075 -> 492 | 1,035 -> 452 |
| ten IANDs, each stored | 1,288 -> 715 | 1,208 -> 635 | 1,168 -> 595 |
| ten LDLs, each used | 1,590 -> 716 | 1,510 -> 636 | 1,470 -> 596 |
| sixteen DEPOSITs | 2,951 -> 2,393 | 1,911 -> 1,353 | 1,397 -> 839 |
| HALT alone | 61 -> 61 | 45 -> 45 | 37 -> 37 |

The first nine programs each end in one deposit, and each gains about 50
cycles a block from that alone - the deposit no longer waits for the
drain and walks its beats at one a cycle, which is why the twenty-IAND
reference moves too. Twenty stores cost what twenty IANDs cost once the
per-block wipe of the twenty slots they name (320 cycles, the same
before and after) is taken out; so do twenty loads and twenty SETACTs.
A static scratch access is about one cycle a beat where it was about
four. The STX/LDX row is mostly the whole-depth wipe an indexing program
pays (4,096 cycles a block at 256 slots), which neither item touches.
Nothing got slower: every row of the table, and every row of R16's and
R17's, is at or below its before-side. The send-back's fast loads, below,
then took a little more from the four rows with a load in them, the same
at each format: twenty LDLs 3 cycles a block (850 -> 847 at fp32), the
STL/LDL pairs 10 (717 -> 707), the STX/LDX pairs 1 (4,680 -> 4,679) and
the used LDLs 1 (716 -> 715); every other row is 1268bc9's to the cycle
(`make seqcycles` at 7f1d56b's RTL).

**Held, and on the real programs.** `control_codes_hold_their_overlap`
in `tb/test_seq_core.py` runs two control-code-heavy programs at fp32
over four blocks, scores them against the model, and fails if either
costs its ceiling or more: 24 independent codes (a store, a load and a
SETACT, eight times) cost 2,011 cycles a block on f681dee's tile and 898
now, against a ceiling of 1,400; eight times a load, an FMA of what it
loaded and a store of what the FMA made - the census's pattern, every
code waiting on the one before it - cost 1,891 before and 918 now (928
on the multi-pass tile, which forwards nothing; 920 and 960 until the
send-back's fast loads, below), against the same ceiling. The bench is
red on f681dee's tile, which is what a hold is for.

`krnl_ode_programs` in `tb/test_krnl_seq.py` runs `programs/gen_odes.py`'s
three programs through the whole kernel with their committed banks,
their segments cut to a few steps, bit-exact against the model on each
of the three trees; cycles from start to done, f681dee's tile -> R18's (4b790b4, before
R19 and before the send-back's fast loads below) -> revision 7 as merged
(R18, R19 and the fast loads; the round's final tree 9fc9c0d, measured
on amd-arc-box, 2026-09-29):

| program, steps | fp64, 64 lanes | fp64, 5 lanes | fp256, 16 lanes | fp256, 3 lanes |
|---|---|---|---|---|
| Lorenz-96, 2 at fp64 and 1 at fp256 | 156,589 -> 67,318 -> 67,305 | 47,948 -> 39,485 -> 39,433 | 78,992 -> 34,363 -> 34,350 | 30,359 -> 23,235 -> 23,196 |
| Lorenz-63, 10 and 4 | 10,521 -> 10,196 -> 10,196 | 5,243 -> 5,191 -> 5,178 | 4,593 -> 4,281 -> 4,281 | 2,487 -> 2,422 -> 2,409 |
| Henon-Heiles, 10 and 4 | 4,099 -> 3,670 -> 3,670 | 1,915 -> 1,863 -> 1,837 | 2,071 -> 1,642 -> 1,642 | 1,083 -> 992 -> 979 |

Lorenz-96, 692 scratch accesses in a 1,452-instruction step, runs 2.3
times as fast in a full block at either format. In a block of two or
three beats it gains a quarter: there every instruction waits out the
array's depth for the one before it, which neither the old machine nor
this one could hide. The other two programs deposit nothing and touch
the scratch only on the way in and out of the segment, and gain what
those few accesses cost. These are simulated cycles with model RAM; the
card's round trips are the lead's to measure.

**The benches.** In `tb/test_seq_core.py`, all against the model:
`control_codes_at_every_block_length` (one program with every shape
above - a code reading a destination in flight and one reading nothing
queued, a store then a load of the same slot, a load into a register a
queued FMA writes in both orders, a store reading a register the next
instruction overwrites, indexed codes with a computed index and with a
loaded one, two LDXs back to back, a loop that loads, stores and
narrows, the mask moving while an FMA is in flight, SETACT reading a
loaded register, ACTALL - at one, two, three, five, nine and sixteen
beats and ragged, across a block boundary, fp32/64/128, modulo and
strict); `mask_moves_while_results_are_in_flight`, the smallest program
that says when the bit is sampled; `halt_right_after_arithmetic`, HALT
and the implicit halt behind an FMA, a store and a deposit;
`control_code_fuzz_at_short_blocks`, programs of mostly control codes
over four registers and four slots; `loads_carry_every_bit_pattern`,
every encoding a pass-through could get wrong - both zeros, both
infinities, quiet and signalling NaNs of both signs with payloads,
subnormals, the largest finite - stored and loaded through all four
scratch codes at one beat, sixteen and ragged, at every format, in a
program with no arithmetic, so FLAGS must be the model's zero; and
`control_codes_hold_their_overlap`, the hold. Since the send-back, too:
`fast_loads_at_every_block_length` (every shape a fast load meets - first
in the block, back to back in all four orders of LDL and LDX, read at
once by every kind of reader, a load into a register a queued FMA
writes, a loop that loads what it stores, strict past the depth, the
mask narrowing while a fast load writes); `loads_cost_no_more_than_before`
and `store_then_load_costs_what_the_sentence_says`, the holds above; and
four cases from verifier-R4's shapes, each for a fault R4 planted that
every case before it passed - `an_index_a_queued_instruction_writes`
(an LDX whose index an IADD, a fast LDL or an LDX still in flight
writes, at one to three instructions' distance),
`the_mask_is_taken_at_fire_not_at_issue` (a SETACT that drops lanes
and, straight after it, codes whose dropped lanes would raise a flag,
report a strict index or take a load's write - it binds where the next
code is addressed by continuation within two steps of the SETACT's
beat: a block of two beats, or a long block whose lane mask leaves one
or two beats alive), and `actall_waits_for_an_ldx_in_g_and_h` (R4's own
test_r4b: ACTALL straight after an LDX, fast and not, whose dropped
lanes load a value they do not hold).
In `tb/test_krnl_seq.py`,
`krnl_ode_programs` runs the three ODE programs of `programs/gen_odes.py`
through the whole kernel at a full block and a short one, fp64 and
fp256. `the_whole_divide_and_root` and `the_pipe_at_every_block_length`
run unchanged. The shapes, the mask case and the bit patterns run on the
multi-pass tile too (`seq_coremc`, MC=10), where no operand is
forwarded and the array takes a beat every three to ten cycles.

**Timing, which only a bitstream measures.** What R18 adds is registered
and shallow - the row a request fires with is a 16:1 select of flops into
a register, the shadow a shift register, the retire's write enables now
come from a register where they came from a select, and an LDX's two
stages are registers - with three additions to paths that were already
long: the issue stage's hold gains the two scratch rules (ANDs of
registered bits, ORed in), the per-beat wait gains a 2:1 select between
its two rules, and the request into the array gained two sources. The
last is written so the forwarded operand still enters at the final 2:1
level, as it did before; the other two are named in the round's ledger
for the build.

**The plants**, each in a fresh copy of the tree and each red for its
reason - two the round asked for and four for this item's own rules:

- DEPOSIT's wait removed (it no longer waits for the producer of `ra`):
  red in all five cases it was run against, as deposits that differ
  from the model ("fp32 control codes, modulo, n=8: 66/128 deposit slots
  differ").
- The mask taken at RETIRE again: red in the dedicated case ("FMA in
  flight under a SETACT, n=8: 8/16 deposit slots differ"), the pipe case
  and the fuzz. It passed the every-shape program, which never looked at
  a dropped lane's result after an ACTALL; that program now deposits
  one, and is red under it too ("fp32 control codes, modulo, n=8: 2/152
  deposit slots differ").
- No LDX gap: red in the fuzz as a HANG, two fires in one step losing a
  request and the queue slot it would have released ("no `done` within
  19696 cycles"). The every-shape program only ever put a beat that
  DEPENDED on an LDX behind one; it now has an independent one, and is
  red under it too, as a hang at fp32, n=9.
- No store-then-LDL wait: red at the one-beat block ("n=8: 1/128 deposit
  slots differ") and in the fuzz.
- SETACT on forwarding's look-ahead while still reading the bank: red in
  three cases, among them a FLAGS word the model does not have (0b00001
  against 0b11001: the wrong lanes kept running).
- ACTALL not waiting for the pipe: red in four of five, as deposits that
  differ.

verifier-R4 planted seven more in e610b78's sequencer, and the lead ran
them against every bench (verifier-R4.md 09:18:53). Two were red in
these cases already (an STX's index wait dropped; R19's live vector
stale on the narrow side), and one can show in no answer (a load's flag
enable left on: IOR raises no flag, above). Four passed every case here
and were caught only by R4's own; each now has the case above that sees
it, run on this revision's RTL with R4's edit ported (every anchor
unchanged; the mask plant gains one edit, the fast write taking the
carried row too, or it would not test the fast path):

- An LDX's index dropped from its read set: red, "fp32 index in flight,
  n=8: 40/64 deposit slots differ from the model".
- The mask sampled at issue and carried down, not taken at fire: red,
  "fp32 an FMA straight after the drop, n=16: FLAGS 0b10001, model says
  0b10000".
- ACTALL not waiting for an LDX's G and H (the pipe's idle forgetting
  them): red, "fp32 ACTALL after an LDX, n=8: 4/8 deposit slots differ
  from the model". R4's first case for it stayed green because its
  dropped lanes indexed past the depth under SCRATCH_STRICT, so the
  wrong write wrote the +0 they held; test_r4b loads a value they do
  not hold. A fast LDX writes at H under the same row, so the answer
  is the same with fast loads.

### R19. A beat no lane needs is neither issued nor loaded

**What it cost before.** The sequencer issued every beat of a block and
let the active bit decide what was written, so a lane mask bought the
bytes, the flags and the early exit and no compute: R17's table, where
a run with every lane masked cost what a run with half of them masked
cost, four cycles and one read a block above the dense run. The same
was true of a lane a SETACT had dropped - an escape-time map whose lanes
had converged paid for them to the end of the loop.

**The rule.** The A stage walks the beats that have an active lane and
jumps the rest: at each step it reads which beats of the block have a
live lane in `active` (a registered copy, a cycle behind), issues the
current beat if it has one, and moves to the next beat that has one.
The mask A reads can only be
WIDER than the one the beat would fire under - a SETACT still in the
pipe narrows it, and ACTALL, the one code that widens it, waits for the
pipe to empty (R18) - so a beat skipped at A is dead at F too, and a
beat issued that has died by F is masked there as it always was.
Nothing observable moves: a beat with no active lane writes nothing,
deposits nothing and raises nothing.

**What the retire needs.** The retire counted beats (`wb_bt`) and wrote
the n-th result to beat n; with beats skipped, a result carries the beat
it FIRED from, down the shadow beside the row (`ft`), and the retire
writes, forwards and pops by that. An instruction that writes a
register always issues the block's LAST beat, live or not - it fires
under an empty row, writes nothing, and waits for no producer, since
what it reads is never written anywhere - because its queue slot is
released by the result on that beat; an instruction every lane had left
would otherwise hold its slot for ever. `wb_bt` now means "the head's
next beat not yet landed or skipped", which is what the per-beat wait
reads.

**The look-ahead, by tag (the send-back, 2026-09-29).** Forwarding lets a
dependent beat be addressed two cycles before its producer's beat lands
(R15). That reach was `wb_bt` plus the NUMBER of results landing within
two cycles - exact while a producer's beats land one after another, and
short of the mark once beats are skipped: a producer whose first issued
beat is 3 or later, or whose issued beats have a gap, lands a beat the
count cannot reach, so the dependent beat waited for the landing itself.
Safe, and two cycles a link: on a latency-bound chain whose low beats a
mask empties, verifier-R4 measured R19 about ten per cent slower than
f681dee and than R18, whose idle beats sat under the array's latency for
free. The reach is now by TAG - the highest beat + 1 among the results
landing within two cycles, or `wb_bt` if that is more - formed a cycle
ahead from the shadow and registered, so the path into the wait is a
6-bit maximum where it was a 6-bit add. While a producer's beats land one
after another the two readings are the same number, so no dense row
moves; with beats skipped, the tag reaches any beat. A landing in the
window that is not the head's is a younger instruction's, and then every
beat of the head's has landed or is landing, so the maximum only says
yes when yes is right.

Measured by `masked_chains_cost_no_more_than_before` (Verilator, the
single-pass tile, where forwarding exists): verifier-R4's chains of
dependent FMAs and nothing else but HALT, sixty links and twenty, under
six masks, at every format - 48 rows. Cycles from start to done over
four blocks, fp32, sixty links:

| mask | f681dee | R18 (1c82d4c) | e610b78 | now |
|---|---|---|---|---|
| every lane kept | 4,741 | 4,737 | 4,737 | 4,737 |
| every other lane | 4,741 | 4,737 | 4,737 | 4,737 |
| the high half masked | 4,741 | 4,737 | 4,529 | 4,529 |
| the low half masked | 4,741 | 4,737 | 5,233 | 4,525 |
| the low quarter masked | 4,741 | 4,737 | 5,281 | 4,573 |
| the last lane only | 4,741 | 4,737 | 5,149 | 4,441 |
| twenty links and a DEPOSIT, the low half masked | 2,620 | 2,416 | 2,520 | 2,280 |

e610b78 was slower than f681dee, and than R18, on 26 of the 48 rows: the
three masks that leave a block's first issued beat at 3 or later, at every
format and both lengths, and at fp256, a lane a beat, every other lane,
whose issued beats have gaps. Now no row is above R18's or f681dee's,
and the fourteen dense rows - every lane kept, and every other lane below
fp256, where no beat empties - are R18's to the cycle. The bench holds
the 48 to f681dee's cycles; the chain that ends in a DEPOSIT is logged
beside them. With the count-based reach planted back it is red on the
same 26 rows (the plants, below).

The same reach moved three of the probe's masked rows (`make seqcycles`
at 7f1d56b's RTL; every other row is f349ca6's to the cycle), each the
same at every format: in R19's table below, the low half of each block
masked 4 cycles (1,649 -> 1,645 at fp32) and all but one lane a block 12
(1,409 -> 1,397); and R17's half-masked fp256 row, 409 -> 405 against a
dense 421. Each ends in a deposit of an IAND whose issued beats start at
3 or later or have gaps: beats the count could not reach.

**The loads.** A dense stream load reads from the first beat a lane the
CALLER HAS sits in to the last, one burst, and nothing when there is
none: a beat outside them holds no lane that can ever be active (ACTALL
reactivates the caller's lanes and nothing else), so no issued beat that
writes anything reads it. A masked beat between two live ones is still
read - a second burst is a second round trip, which would cost more than
it saves. The gathered streams (R16) and the scratch preload are
unchanged.

**What it costs now.** `make seqcycles`, four blocks, cycles for the
run, twenty IANDs and a deposit (and, last row, twenty STLs), before
(R18, 1c82d4c) and after (R19, f349ca6):

| program, mask | fp32, 128 lanes a block | fp64, 64 | fp128, 32 | fp256, 16 |
|---|---|---|---|---|
| twenty IANDs, dense | 2,229 -> 2,229 | 1,909 -> 1,909 | 1,749 -> 1,749 | 1,669 -> 1,669 |
| ...every other lane masked | 2,245 -> 2,245 | 1,925 -> 1,925 | 1,765 -> 1,765 | 1,685 -> 1,141 |
| ...the low half of each block masked | 2,245 -> 1,649 | 1,925 -> 1,329 | 1,765 -> 1,169 | 1,685 -> 1,089 |
| ...all but one lane a block masked | 2,245 -> 1,409 | 1,925 -> 1,089 | 1,765 -> 929 | 1,685 -> 849 |
| ...every lane masked | 2,245 -> 1,385 | 1,925 -> 1,065 | 1,765 -> 905 | 1,685 -> 825 |
| twenty STLs, every lane masked | 3,477 -> 2,389 | 3,157 -> 2,069 | 2,997 -> 1,909 | 2,917 -> 1,829 |

A dense run costs what it did, and so does a mask that leaves a live
lane in every beat - every other lane, below fp256 - because there is no
beat to skip. A beat the mask empties costs nothing to issue: the low
half of each block masked saves half of every instruction's beats, and
at fp256, a lane a beat, every other lane is every other beat. What is
left of an all-masked run is the block's own machinery - its setup and
the mask's read - about four cycles for each instruction, about seven for
an arithmetic one, and the drains, which R17 made keep a masked lane's
place and lose its strobe. (This sentence said "one cycle for each
instruction that writes a register, one bubble for each that does not"
until verifier-R4 measured it: 7.0 cycles an arithmetic instruction and
4.3 a store, fp32, every lane masked. An instruction whose only issued
step is its first cannot take the next one by continuation, so each pays
the fetch and decode; an arithmetic instruction's forced last beat still
crosses the array, and the queue's three slots cover twelve of the
array's seventeen cycles.) The
stream reads fall from ten to six, the mask's four and the image's two.
R17's own table moves the same way: one IAND and a deposit, every lane
masked, 997 -> 865 cycles at fp32 and 437 -> 305 at fp256, where half
masked is now 409 against a dense 421. Every other row of the probe -
the dense table, R16's, R18's - is unchanged to the cycle.

**Held.** `masked_beats_hold_their_saving` in `tb/test_seq_core.py`
runs twenty IANDs and a deposit at fp32 over four blocks, answers held
to the model, and fails if the low half of each block masked costs 485
cycles a block or more, or every lane masked 450 or more: on this bench
R18's tile costs 559.0 for both (verifier-R4 measured it; the 561.25
this paragraph gave was the probe's figure, for the probe's program),
and R19's costs 409.0 and 344.0 (410.0 until the send-back's look-ahead
by tag, above).

**The benches.** In `tb/test_seq_core.py`, against the model:
`masked_beats_at_every_block_length` (masks that empty whole beats - the
low half of each block, the high half, all but the last lane, all but
the first, every lane, random sets of whole beats - over the pipe
program, R18's control-code program and R17's own, at every format,
from one beat to several blocks); `converged_beats_are_skipped` (the
escape map with its seeds grouped by beat, so whole beats CONVERGE at
different iterations and the SETACT-cleared bit is what the issue
reads); `a_beat_no_lane_has_is_not_loaded` (the stream reads asserted
as ADDRESSES - one burst a block from the first live beat to the last,
none for a block with none); `beats_revived_by_actall_are_read_at_once`
(verifier-R4's shape: a producer - an FMA, an LDL, an index and an LDX -
that skips the beats a SETACT emptied, ACTALL, and its readers straight
after, which must issue the revived beats); and the hold. Every R18 case
runs on top, unchanged, and the multi-pass tile runs both items' cases.

**The plants**, each in a fresh copy of the tree and each red for its
reason:

- A skipped beat still counted - the retire writes the n-th result of an
  instruction to its n-th beat again, not to the beat it fired from: red
  in all five cases it was run against, as answers that differ ("escape
  map, whole beats converging, n=128: 280/1024 deposit slots differ").
- A writer's last beat not forced: red in all five, as HANGS - an
  instruction every lane had left fires nothing and never leaves the
  queue. The control-code program hangs at one beat without a mask,
  once a SETACT has emptied the beat.
- The dense load back to the whole block: red only where it must be, in
  the read-traffic case ("stream a read [(65536, 16), (66048, 16)], and
  the mask says [(65792, 8), (66304, 8)]"); a load of a beat no lane can
  read is a cost and not an answer, and every answer case passes under
  it.
- verifier-R4's live vector three cycles late: it passed every case
  here, `converged_beats_are_skipped` among them, whose ACTALL is never
  straight before a reader. Red in
  `beats_revived_by_actall_are_read_at_once`: "fp32 an FMA and an LDL
  skip, ACTALL, their readers at once, low half, n=8: 32/32 deposit
  slots differ from the model".
- The look-ahead by count again, in place of the tag (the send-back):
  red in `masked_chains_cost_no_more_than_before`, "26 of 48 masked
  chains cost more than on f681dee's tile, the first: fp32 60 links,
  low half masked: 5233 against 4741" - e610b78's figures, to the
  cycle.

**Timing.** The live vector and the load's bounds are registered. What
R19 adds to the issue stage's paths is a 16:1 select of a register (the
current beat's live bit, into the hold and the pipe's valid) and a
16-bit priority encoder (the next live beat, into `bt` and the
admission) - both on paths the R18 note above already names as long.
verifier-R4 read the paths revision 7 grew, from the RTL, and ranked
them by risk; they are the list the next bitstream's routed report is
read against:

1. The admission: the instruction memory's read data, the writer
   decode, the priority encoder, `bt` - about two levels of logic before
   R19 and nine to eleven after. The lead's out-of-context run of the
   merged tree at the U50's capacities names it u_seq's worst path,
   instruction memory to `bt`, eighteen levels with the block-RAM
   cascade, +1.885 ns at 135 MHz (before the send-back).
2. `rd_hold`, into the queue's and the dependencies' registers: about
   three more levels, at high fanout.
3. The forwarded `op_a` now also drives the scratch's write data and
   the deposit buffer's (`scr_wdata`, `db_wdata`): two more 256-bit
   register sets on its load.
4. The scratch's read into the array: measured in the same run, +4.280
   ns.

The send-back adds, read from the RTL and not synthesised:

- The file's write data gains a fourth source, the loaded value - the
  scratch's read register, through a 2:1 a word - and its write address
  and enables a 2:1 each, the enables between two row selects of
  registers. Shorter than the array's own path into the same registers.
- The pop becomes the OR of the array's and a fast write's, the latter a
  6-bit compare of the beat with the block's last; through the pop, the
  queue's room and the admission (item 1), which also gains an AND over
  at most two registered queue flags (`all_fast`). On a multi-pass tile
  that AND also gates the admission of a load (the policy); on the
  single-pass tile the gate is a constant and folds away.
- The per-beat wait's reach (`wb_soon`, into `rd_hold`, item 2): a 6-bit
  maximum of `wb_bt` and a register (`win_q`) where it was a 6-bit add
  of `wb_bt` and a two-bit count. The window behind the register is
  three 6-bit increments and a three-way maximum, off every other
  path.

## Revision 7, the program limits per build (2026-09-29)

Revision 7's third item (docs/ROADMAP.md, "Revision 7: step 4's RTL
revision"). Logan, 2026-09-28: size the program limits "as large as we
can, ideally adjustable as the other parameters are, so the U50 can
benefit from its higher resources than an open core design can reach".
Its first two items, R18 and R19, change cycles and nothing else; this
one changes room, and - for one kind of image, below - one number a
program can observe.

### What moved

`SEQ_MAXD`, `SEQ_IMEM_D` and `SEQ_SCRATCH_D` are `cft_krnl`'s
parameters, declared with the others at the top of rtl/cft_krnl.sv,
whose defaults are the U50's and the only place its numbers are
written down - `MAXD` 1,024, `IMEM_D` 32,768, `SCRATCH_D` 2,048 - and a
build overrides them the way it overrides any parameter
(`CFT_GENERICS` at packaging, `-P` in a bench, `chparam` in Yosys).
The open-core configurations keep 64, 16,384 and 256, and say so:
tb/Makefile's `OPEN_CAPS_GENERICS` (the board benches and the quarter
tile, handed to the simulator and to the benches' expectations from one
list) and hw/openxc7's board synthesis and harness. `KMEM_D` stays a
localparam at 512.

No feature bit and no VERSION step: a host learns each from the field
it already reads. `CAPS[19:16]` reads 10, `CAPS[23:20]` 15 - the last
value its four bits hold, so the next instruction capacity is a CAPS
change - and `CAPS2[3:0]` 11. `cft_seq` refuses to elaborate a capacity
that is not a power of two or is past 2^15, because each field is a
four-bit log2 and `$clog2` is the ceiling: any other value would be
published as a larger capacity than the tile has.

### Two pure capacities, and one that is not

`IMEM_D` and `MAXD` are pure capacities: a program either fits and gets
the answers it got on a smaller tile, or is refused at the header -
`n_insns` past `IMEM_D` and `max_deposits` past `MAXD`, STATUS[3],
nothing written. tb/test_krnl_seq.py holds both at the kernel's own
values: a program of exactly `IMEM_D` instructions, one of one more,
`max_deposits` at `MAXD` and at one more.

`SCRATCH_D` is not purely one. A NON-strict `STX`/`LDX` reduces its
index modulo the depth (R4), so an image that indexes past 256 wraps at
2,048 on the U50 and at 256 everywhere else, and computes other
answers; a STRICT one (R8) reports the index past the depth and is
portable - a strict run that reports nothing computes the same at every
depth deep enough for it. Every other program - one that indexes below
256, or names only static slots below 256 - computes exactly what it
did. So the depth is a parameter of everything that stands for a tile:
- the golden model: `seq.run(..., scratch_depth=)`, 256 by default, and
  `Program`, `from_bytes`, `stl` and `ldl` validate against a declared
  depth, 256 by default; `run()` refuses by name a program whose static
  slots or scratch-I/O counts exceed its depth;
- libcft's software backend: a handle computes at the depth it
  publishes in `cft_caps.max_scratch` - 256 from `cft_open`, any power
  of two up to 32,768 from `cft_open_ex` (docs/HOSTAPI.md);
- every comparison against a device takes the device's depth:
  device-test opens its reference at the device's `max_scratch`,
  segrun_check.py's golden writer runs at the depth its expected CAPS2
  names, and the certificate audit re-runs at the depth a certificate's
  `device-caps` names (docs/CERTIFICATES.md);
- programs/check.py takes no device - it compares the model with the
  software backend - and runs `deepwalk-fp64` and
  `deepwalk-strict-fp64`, a thousand slots walked through a loop
  counter, on both at 2,048 and at 256 (verifier-R5, 2026-09-29: this
  list once counted it among the comparisons against a device).

### What it costs

The memories, estimated from the geometry and not synthesised here -
the bitstream measures them:

| memory | round-2 | U50, revision 7 | a tile, in UltraRAM | a tile, in block RAM |
|---|---|---|---|---|
| deposit buffer, `MAXD * NBEATS * 32 B` | 32 KiB | 512 KiB | 32 URAM (four-deep cascades) | 128 RAMB36 |
| instruction memory, `IMEM_D * 8 B` | 128 KB | 256 KB | - | 64 RAMB36 |
| scratch, `SCRATCH_D * NBEATS * 32 B` | 128 KiB | 1 MiB | 64 URAM (standalone 4K sub-arrays, below) | 256 RAMB36 |

Revision 3's build put the scratch's 4,096-deep banks in one URAM each
and moved a four-deep URAM cascade (the instruction memory at 16,384)
into block RAM "due to insufficient pipeline registers". In block RAM a
2,048-slot scratch does not fit the quad (about 1,657 tiles of 1,344);
in UltraRAM it does, with the deposit buffer, at about 388 of 640. So
the scratch is not left to inference: at more than 256 slots each bank
is built from 4,096 x 32 sub-arrays - revision 3's shape, one URAM
apiece, pinned there by `(* ram_style = "ultra" *)` - and read through
one 8:1 mux selected by the slot's high bits, registered with the read
and held with it while the issue pipe holds (R18's rule for the read
register, so a held load keeps its own sub-array). A wipe wider than one
sub-array is written to all eight at once (below, "The widest wipe").
Chosen over the attribute on a 32K-deep array for timing at 135 MHz: an
eight-deep cascade puts up to seven cascade hops between a URAM's output
and the fabric, where standalone URAMs put one LUT mux (believed, from
the part's usual figures; the synthesis measures it). The read takes the
same cycle and every simulator sees the same bits; at 256 slots a bank
is one such array and nothing changed. Where Vivado puts the deposit
buffer and the instruction memory (block RAM, bit-sliced, is expected)
is the first number the revision-7 build should read.

In cycles, measured on `cft_seq` in simulation (fp32, four blocks of
128 lanes, model RAM answering at once), before the fix below. Both
tables here were measured before R18 and R19 joined the tree, which
move what an instruction costs, so their absolute numbers move with
them; what the benches assert - the wipe's difference exact, and an
indexing block within a small constant of its static twin at either
depth - does not.

| program | `MAXD` 64, `SCRATCH_D` 256 | `MAXD` 1,024, `SCRATCH_D` 2,048 |
|---|---|---|
| `halt` alone | 60.8 cycles a block | 64.8 |
| one `ldx` (it indexes) | 4,249.0 | 32,921.0 |
| one `ldl` of slot 3 | 199.0 | 199.0 |

- **The block setup's floor**, the first row. S_ZERO forms
  `blk_n * max_deposits` one multiplier bit a cycle over `CW + 1` steps,
  `CW = clog2(MAXD + 1)`: 8 cycles at 64 and 12 at 1,024, four cycles a
  block on every program run through the kernel. It is the cost of the
  larger `MAXD` and it stands: under 1% of a typical block (the lead,
  2026-09-29).
- **An indexing program's wipe**, the second row. A program that uses
  `STX`/`LDX` can reach every slot, so every block wiped all
  `SCRATCH_D * NBEATS` of them: 4,096 cycles at 256, 32,768 at 2,048 -
  a cycle regression for every indexing program, the side project's
  Cauchy products among them, which the revision's contract does not
  allow. So the wipe now follows what was written (below).
- A static program wipes as far as its own highest slot: the third row,
  the same at both.

### The wipe follows what was written

Each of the scratch's word banks keeps a DIRTY HIGH-WATER MARK, and the
invariant is that in bank b every slot at or above `scr_hwm[b]` holds
+0, every beat. The marks OBSERVE the scratch memory's one write port
(`scr_we`, `scr_waddr`), whoever drives it - a store, the scratch-in
preload, the gather - and ignore the wipe's own writes: a write at slot
s raises its bank's mark to s + 1 if it was below. A block wipes as far
as the highest mark and never further than the old rule asked, so every
slot it can observe reads +0 - below the bound because it was wiped,
above it because nothing has written it since it last was. When the
wipe covers a bank's mark the bank is clean; a static program's shorter
wipe leaves the rest marked. The marks start at `SCRATCH_D` at reset,
so the first block wipes what it can observe, and persist across runs,
so a run's first block wipes what the last run left.

A block's wipe is therefore what the previous block wrote: an indexing
program that writes below slot 256 costs the same at 2,048 slots as at
256 - less than either did, since both wiped the whole depth - and a
program that really uses a thousand slots pays at most one sub-array's
worth (below, "The widest wipe"). The wipe is never longer than the old
rule's. Measured after the marks and before the broadcast, the same way
as the table above:

| program | `MAXD` 64, `SCRATCH_D` 256 | `MAXD` 1,024, `SCRATCH_D` 2,048 |
|---|---|---|
| `halt` alone | 60.8 cycles a block | 64.8 |
| one `ldx`, a run's first four blocks after a reset | 1,183.8 | 8,354.8 |
| one `ldl` of slot 3 | 144.0 | 148.0 |
| `stx` through indices below 32, marks set by a run before | 651.0 | 651.0 |
| the same through indices below 8 | 267.0 | 267.0 |
| `stl` at slot 31, its static twin | 633.0 | 633.0 |

- The `ldx` row is a reset's price, paid once: the marks start all
  dirty, so the first block wipes the whole depth - 4,249 and 32,921
  cycles - and the three after it, which nothing wrote, wipe nothing
  (162 and 166). At 2,048 that first block was a regression against
  f681dee, where every indexing block cost 4,249 (verifier-R5); the
  broadcast removed it, and it is 4,249 at both depths now (below).
- The `ldl` row is cheaper than before, 144.0 against 199.0: it names
  four slots and writes none, and once they are clean there is nothing
  to wipe, so S_ZERO takes its floor.
- The `stx` rows are the steady state, the same at both depths. Below 32
  and below 8 differ by exactly 24 slots' wipe, 384 cycles; below 32
  costs its static twin plus 18, which is `STX`'s own cost against
  `STL`'s and not the wipe's - the same 18 on the unchanged RTL, 4,235.0
  less its 4,096-cycle wipe against 633.0 less its 512. Before the marks
  the first `stx` row was that 4,235.0 at 256 slots, and by the same
  arithmetic 32,907 at 2,048.

It keeps every answer, and is held so: tb/test_seq_core.py's
`scratch_blocks_see_only_their_own_writes` (blocks and runs that write
different ranges, and reads of slots a lane never wrote, which must be
+0, against the model, which has no blocks), and
`scratch_wipe_costs_what_was_written` (the three `stx` and `stl` rows
above, asserted: below 32 and below 8 must differ by exactly 384 cycles,
and below 32 must cost its static twin within four slots' wipe, at 256
slots and at 2,048). Each was red for its reason in a copy of the tree
with a fault planted: a mark one slot short (a block read the last
block's top slot, and the next one its slot 3 - 144 of 384 deposits
wrong); a partial wipe that cleaned every mark (run B read run A's
slots after a static run between them - 128 of 128); and the RTL
before the marks (below 32 and below 8 both 4,235.0 cycles a block,
slots 8 to 31 costing nothing because every block wiped all 256).

### The widest wipe is broadcast

The marks start all dirty at a reset - nothing says what the memory held
before one - so the first indexing block after a reset wiped the whole
depth: 32,921 cycles at 2,048 slots, where every indexing block at 256
had cost 4,249; and the same after any run that wrote up to the top
(verifier-R5; the second send-back). A bank at more than 256 slots is
eight standalone sub-arrays sharing one local address, so when a block
must wipe more than one sub-array's slots, S_ZERO writes +0 at local
address a in ALL of them at once, for a in [0, 4,096): 4,096 cycles
clear the whole memory at any depth, and every mark is cleaned after it
(the clean's bound is `SCRATCH_D`). No block's wipe is ever longer than
4,096 cycles at `NBEATS` 16 - the widest wipe revision 3 made - so the
first block after a reset costs what every indexing block cost at 256:

| one block of 128 fp32 lanes | `MAXD` 64, `SCRATCH_D` 256 | `MAXD` 1,024, `SCRATCH_D` 2,048 |
|---|---|---|
| `ldl` of slot 255 after a reset (a 256-slot wipe) | 4,249 cycles | 4,249 |
| `ldx` after a reset (every mark dirty) | 4,267 | 4,267 |
| `ldx` after a store at the top slot | 4,267 | 4,267 |
| verifier-R5's row: block 0 of the first four-block `ldx` run after a reset | 4,249.0 | 4,249.0 (32,921 before) |

The `ldx` rows are the `ldl` row plus `LDX`'s own 18. MAXD's +4 is not
in them: S_ZERO's floor lies under the wipe. Every answer stands: the
broadcast writes a superset of what the targeted wipe wrote, and after
it the whole memory is +0, which is what the cleaned marks say; only the
wipe's own writes are broadcast (`scr_wipe_q`), and nothing else writes
the scratch while S_ZERO runs. It costs one term on each sub-array's
write enable. Weighed and not taken: a background clean while the tile
is idle (a start right after a reset would still pay up to the whole
depth, and it adds a second writer on the port), and marks kept across
`ap_rst_n` from a memory zeroed at configuration (true of block RAM,
believed of UltraRAM, false on an ASIC).

### A block that can read none of its preload loads none

A scratch-in block that no instruction and no drain can read - the
program names no slot, indexes nothing and drains nothing, so the span
the wipe is sized by is 0 - is not loaded, dense or gathered: S_ZERO
does not wait for its product, and the block goes straight to its
operand streams. Revision 3 did this by accident at `n_scratch_in` 256,
where an empty wipe cut the product short (80 cycles, verifier-R5's
harness); the latent edge's wait below - and at `MAXD` 1,024 the longer
floor alone - made such a block load in full, 36,947 cycles at 256
slots and 36,950 at 2,048. Now it is the rule, for
every count: [halt] with an unread 256-slot block costs what [halt]
alone costs - 78 cycles at 256 slots and 82 at 2,048 by this bench's
count, dense and gathered - and not one read lands in the block, its pool or its table. The same
block with slot 255 read still loads whole: 41,300 cycles at both, as at
f681dee. No preloaded value could reach an output of such a block, and
the skipped block writes nothing, so the marks stand.

A NAMED COST, not a regression: a block that reads SOME of a longer
preload - `n_scratch_in` 256 and an `ldl` of slot 3 - still loads all of
it, where four slots a lane would do. The block is lane-major, so a
lane's readable slots are a prefix of its `n_scratch_in` elements and
the rest lie between that prefix and the next lane's; skipping them
takes per-lane strided bursts on the read master, or a multi-element
skip in the peel window. f681dee loaded such a block whole as well.

### One latent edge, closed on the way

S_ZERO's exit waits for the deposit product's `CW + 1` steps, for the
wipe, and - since revision 7 - for the two scratch-count products, which
are `SCRSW + 1` bits wide and so follow the depth. Before the dirty
marks, a block whose preload or drain anything could read also wiped at
least one slot, sixteen cycles at 16 beats, so the products had at least
fifteen steps and the wait mattered only for a count of 2^15. The marks
changed that: a block whose scratch is already clean wipes nothing, so
the window can be `CW + 1` steps - eight at `MAXD` 64, where a count of
256 is nine bits - and without the wait such a block would preload and
drain nothing (verifier-R5's plant p6). So on `cft_seq`'s defaults and
the open-core builds the wait is load-bearing at 256 slots; at `MAXD`
1,024 twelve steps cover every count to 4,095 and it costs nothing. A
block that can read no slot skips its preload (above) and does not wait.

### How it is held

Measured on 2026-09-29, under Verilator in the `cft-sim` image and on
the software backend (parcel P2's ledger has the runs):
- **the unit bench at both machines.** `seq_core` runs `cft_seq` at its
  own defaults (64, 1,024, 256) and `seq_coreu50` at the U50's, read out
  of rtl/cft_krnl.sv by tb/krnl_caps.py so the numbers exist once; every
  model call in the bench is at the DUT's depth. Beside the suite's
  cases, three of revision 7's own: an index of 9 + 256k, whose plain
  deposits and strict STATUS on the deeper build are asserted to differ
  from a 256-slot model's; and the wipe's two, above. And the second
  send-back's: `scratch_first_block_after_reset_costs_one_sub_array`
  (the table above, asserted: each `ldx` block within four slots' wipe
  of the `ldl` block), `scratch_broadcast_just_over_one_sub_array` (a
  need of 257 slots takes the broadcast and reads +0 at slots over the
  whole depth; a watch holds every broadcast's clean - bound
  `SCRATCH_D`, every mark 0 on the next edge - here and in the answer
  bench), `scratch_preload_nothing_reads_is_not_loaded` (the unread
  block costs what [halt] costs and is never read; the read one is
  loaded whole), and three that hold the marks' other writers and the
  wait: `scratch_preload_and_gather_raise_the_marks` (a preload and a
  gather, then an indexing read of a preloaded slot from another run,
  +0), `scratch_preload_read_with_the_marks_clean` (a 256-slot block in
  and out with the marks clean, whole; the whole depth at 2,048) and
  `scratch_marks_are_per_bank` (each word bank's mark alone keeps the
  next run's wipe, with a static partial wipe between); and
  `scratch_drain_is_the_preloads_only_reader` ([halt] with a block in
  and drained out, which must load whole - the drain is a reader the
  skip rule counts). Verifier-R5 planted the faults the last four hold
  (P2.md has each plant's red).
- **the kernel.** `krnl` holds CAPS and CAPS2 to the parameters at the
  U50's defaults; `krnlseq` holds `IMEM_D` full and one past it, `MAXD`
  at the cap and one past it, the scratch's top slot, and an index of
  5 + 256k plain and strict against the model at the tile's depth.
  `quarter` holds the open-core values it pins - `MAXD` and `IMEM_D`
  in CAPS, the scratch's 256 in CAPS2 - and the `board` targets
  (`simmc`) do the same for the board configuration.
- **the software backend and the model.** python/tests/test_seq.py's
  depth tests (the default is every run as it was; a plain index wraps
  at the run's depth; a strict one is reported past it; the static
  footprint is held to the run; static-only and clean strict runs are
  the same at every depth deep enough); device-test at 256 and at
  `--scratch-depth 2048`; programs/check.py's two `deepwalk` rows.
  device-test also runs a scratch block as deep as the device - 300
  slots in and out, in alone, out alone, and the whole depth - held to
  its own bytes, with one past the depth refused by name. It was added
  when verifier-R5 found libcft's loader refusing every block from 257
  to 2,048 slots on every handle, with no sentence: a test of the
  library's own 256-slot ceiling that ran whatever depth the device
  published (docs/HOSTAPI.md, `cft_open_ex`).

## Revision 8 (proposed, 2026-09-29; flag control and per-lane flags built golden-first 2026-10-02): an exact-residual add, a stepped index, flag control and per-lane flags

Three of the side project's asks (docs/ROADMAP.md, "What a side
project asks of step 4's revision", asks 3, 4 and 5), defined
golden-first beside revision 7 and counted for what they are worth.
Revision 7's tile has none of them in its RTL, and nothing here changes
what a program that runs today computes: each new form takes an
encoding every loader refuses today, and each sits behind a capability
bit of its own, refused BY NAME wherever it is not built.
`python/cft_golden/seq.py` is the definition, `host/src/program.c`
computes it on the software backend and `host/tests/seq_check.py` holds
the two together; a tile carries it only once an RTL revision builds it.

The step-6 round (docs/ROADMAP.md, "Step 6", R8F and R8L) adds a fourth
item and gives the third its last bit. A correctly rounded routine -
divfull today, the math library next - runs many instructions whose own
flags are scaffolding, and no opcode can raise divide-by-zero. Logan
chose, for FLAGS in routines, "Flag control in rev 8 (Recommended)", and
for this revision "Flag control, Per-lane flags (R23), TwoSum + stepped
scratch, Instruction streaming" (2026-10-02). So R24 is flag control: a
quiet region and a raise, so that a routine runs quiet and then raises
exactly the flags of the operation it implements. Its raise carries a
mark, which R23's bit [7] records: a lane whose last bit a routine could
not decide. Revision 8's RTL comes later, in one revision whose plan goes
to Logan first, so everything it needs of R23 and R24 is defined here
first. Instruction streaming has a design study of its own.

Each choice below took the first rung of Logan's rule (2026-09-29) that
had an answer - "adhere to IEEE 754 when an option, RISC V approaches if
nothing is in IEEE 754, and if neither state a way to handle it,
whatever approach aligns best with the current systems" - and says
which rung it was.

This section is the CONTRACT for R21 to R24, and all four are built
golden-first: `seq.py` defines them and the software backend computes
them, R21 and R22 at ABI 0.16 and R23 and R24 at ABI 0.17 (2026-10-02,
the step-6 round's R8). No tile carries any of them. What a tile would
need - R23's MODE bit, its pointer register, kernel argument and VERSION,
and each item's decode - is a proposal below, the RTL plan's to confirm.
R20 is left to revision 7's third item, the program limits, should it
take a number. All five text forms are in `asm.py` and, since
2026-10-02, in `host/tools/cft-asm.c`.

### R21. `augadd` and `augerr`: 754-2019's augmentedAddition, one result an instruction

*Control codes 10 and 11. Feature bit CAPS2[11] = `cft_caps.seq_features`
bit 15 = `CFT_SEQ_FEAT_AUGADD 0x8000u`. Assembler `augadd rD, rA, rB`
and `augerr rD, rA, rB`.*

| code | name | effect |
|---|---|---|
| 10 | `AUGADD rd, ra, rb` | `rd := r`, augmentedAddition(ra, rb)'s first result |
| 11 | `AUGERR rd, ra, rb` | `rd := e`, its second |

**The operation: rung 1, IEEE 754-2019 clause 9.5.** augmentedAddition(x,
y) is the pair r = roundTiesTowardZero(x + y) and e = x + y - r, with 9.5's
own rules for specials, signs of zero and exceptions. This library has
computed it on the host since the 0.6 step (`cft_augmented_add`), and
`python/cft_golden/augmented.py` is its definition: `seq.py` calls that
module's `augmented_add` and keeps one half, and `program.c` calls
`host/src/augmented.c`'s own lane function - one definition, reused, not
a second copy. So the tie rule is 9.5's, which none of the tile's five
attributes has: 1 + 1.5 ulp gives r = 1 + ulp, where ADD gives 1 + 2 ulp.

**Two instructions, one result each: rung 2.** 754 defines the pair and
not how an instruction set delivers it. RISC-V's answer for an operation
with two results is two single-destination instructions in a recommended
order an implementation may fuse ("M" extension v2.0, 11.1.2):
"DIV[U] rdq, rs1, rs2; REM[U] rdr, rs1, rs2" where "rdq cannot be the
same as rs1 or rs2", and "Microarchitectures can then fuse these into a
single divide operation" - MULH and MUL likewise, 11.1.1. DIV and REM
have this operation's shape: a rounded result and its exact remainder.
The recommended sequence here is

    augerr rE, rA, rB
    augadd rS, rA, rB          ; rE is neither rA nor rB

so the sum may overwrite its own operand: `augadd rA, rA, rB` is a
compensated step's x := x + y with the error already beside it, and no
temporary. Any order is legal and computes by the definition; the
recommended one is what a tile may fuse, and a fused pair must equal the
unfused pair bit for bit. It is also what this machine has (rung 3): one
register-file write port and one destination a queue entry (R12 to R15),
so an instruction with two destinations would retire in the write cycles
of two and save one instruction word.

**Control codes, not two ALU opcodes.** An unassigned ALU opcode is a
LEGAL program today with a defined answer - the canonical quiet NaN and
invalid, in a program and through `cft_run` alike (`host/include/cft.h`
names "15, and 32 upward") - and taking two would change those answers.
An unknown control code is refused by every loader, so codes 10 and 11
change nothing that runs, which is also RISC-V's practice: an extension
claims encodings that were illegal. They are arithmetic all the same,
and that is the one way they differ from the other control codes: they
compute and they raise flags, and a tile should compute them in the
array (below).

**Fields.** `ra` and `rb` are read and `rd` is written, five bits each
(imm[24], imm[25] and imm[26] their high bits). Every other field is
unread and must be zero, by the rule that has settled every field since
revision 2: `rc` and imm[27], imm[23:0], imm[31:28], `rnd` - 9.5 fixes the
rounding, so no attribute can be spelled (rung 1) - and `ka`, `kb`, `kc`
and `kx`, because no control code reads the bank (rung 3). A constant is
moved into a register once.

**Flags: rung 1.** Each of the two raises exactly the flags
augmentedAddition(ra, rb) raises under 9.5's default handling:
- invalid, for a signaling NaN operand or inf + (-inf), both halves then
  the canonical quiet NaN;
- overflow and inexact, when roundTiesTowardZero(x + y) overflows, both
  halves then that infinity;
- underflow WITHOUT inexact, when e is non-zero and below 2^emin in
  magnitude - the combination nothing else in this contract produces
  (docs/DETERMINISM.md's tininess section records the exception);
- nothing else: a rounded r raises no inexact.

FLAGS is the run's sticky OR, so the recommended pair raises exactly what
one augmentedAddition raises, fused or not.

**Every format the tile runs** - fp32, fp64, fp128 and fp256 - with the
one definition in the program's format. The residual is representable in
all four, which augmented.py proves and asserts; the C twin bounds its
alignment at 2p + 1 bits, 475 at fp256.

**A lane mask, and every inactive lane: nothing new.** A lane R17 masks,
a padding lane and a lane SETACT dropped run no instruction, so they write
no `rd` and raise no flag - P3's rule, which
`python/tests/test_seq_rev8.py` holds with a signaling NaN in each.

**What a tile would need** (revision 8's RTL: believed, not built). Both
codes go through the issue pipe into the array as an ALU instruction
does - one array pass and one register write each, under R13 to R15's
hazards and forwarding - rather than through the control path, and R10's
stream-need parse names their `ra` and `rb`. In the lanes, the adder's
rounding gains ties-toward-zero (a nearest mode whose tie goes down: round
up on guard AND sticky), and a second output selects e, the exact sum
less the rounded one; in the far case e is the smaller operand unchanged.
Every tile built so far reads CAPS2[11] as zero and would decode code 10
as HALT (`rtl/cft_seq.sv`'s `default` arm), so the loader refuses both
codes there by name, naming the instruction.

### R22. A post-step on `STX` and `LDX`

*imm[11:0] of STX (8) and LDX (9), a signed twelve-bit step. Feature bit
CAPS2[12] = `cft_caps.seq_features` bit 16 =
`CFT_SEQ_FEAT_SCRATCH_STEP 0x10000u`. Assembler `stx rA, rB, STEP` and
`ldx rD, rB, STEP`.*

| form | effect |
|---|---|
| `STX ra, rb, step` | `scratch[rb] := ra`, then `rb := rb + step` |
| `LDX rd, rb, step` | `rd := scratch[rb]`, then `rb := rb + step` - unless `rd` is `rb`, which keeps the loaded value |

`scratch[rb]` is R4's and R8's: rb's bit pattern reduced modulo the depth,
or reported under SCRATCH_STRICT.

**The encoding: bits no program may set today.** imm[23:0] of the indexed
pair has been read by nothing since revision 3 and must be zero, so every
STX and LDX a loader accepts has imm[11:0] = 0 - and a zero step is the
instruction exactly as it was, the same bytes and the same meaning.
imm[23:12] stays read by nothing. The assembler writes a step back only
when it is not zero, so an image from before this revision disassembles
as it did.

**Post, by a sign-extended twelve-bit immediate: rung 2.** 754 has nothing
to say about addresses, and ratified RISC-V has no auto-stepping address
either. The RISC-V ecosystem's is exactly this shape - OpenHW's CORE-V
XCVmem, the CV32E40P's post-incrementing loads and stores: "rD =
Mem32(rs1) rs1 += Sext(Imm[11:0])", the store likewise - and twelve bits
is RISC-V's I-type immediate. So the access uses the index as it stood, a
store stores `ra` as it stood (the index itself, when `ra` is `rb`), and
then the index steps - except where a load's destination is the index
register itself, below.

**Width and wrap: rung 3.** rb := (rb + step) modulo 2^W, W the format's
width: IADD's arithmetic on the encoding, which the software backend
computes with its own IADD, or ISUB by the magnitude - the same residue.
So the index register after any number of steps is a function of the
program alone, the same on a tile of any depth. A decrement past 0 gives
2^W - 1: without SCRATCH_STRICT the next access reduces it modulo the
depth, a ring; with it, the next access is suppressed and reports
STATUS[5]. A step is a register write, masked by the active bit as every
write is (P3): a masked, padding or dropped lane neither accesses nor
steps.

**Under SCRATCH_STRICT (R8)** the access is judged on the index as it
stood, exactly as today, and the step is never suppressed: R8 suppresses
an access and the step is not one. A strict run and a non-strict run
therefore leave `rb` the same and differ only in the accesses STATUS[5]
reports, which keeps R8's promise that a strict run reporting nothing
computes the same at every depth. A step that walks past the depth
reports nothing by itself; the first access past it does.

**`LDX rd, rb, step` with `rd` = `rb`: the loaded value wins and the step
is discarded - rung 2.** Both writes would land in one register, and
RISC-V's post-increment loads define which one does: "When same register
is used as address and destination (rD == rs1) for post-incremented loads,
loaded data has highest priority over incremented address when writing to
this same register" (CORE-V XCVmem, OpenHW's CV32E40P manual). So the
register holds what the load delivered - the slot's value, or under
SCRATCH_STRICT the +0 of a suppressed access - and `ldx rX, rX, s`
computes exactly what `ldx rX, rX, 0` does. It is a second spelling of
the unstepped load, and it loads: the step field is READ and a defined
priority discards its effect, which is the latitude a `kx` instruction
whose indices are all below sixteen has, not the refusal of a field
nothing reads. It still needs CAPS2[12], as every non-zero step does - the
bit is about the encoding. STX with `ra` = `rb` has one register write,
the step's, and keeps it. (Until the send-back of 2026-09-29 this form was
refused, a rung-3 choice taken while rung 2 had an answer.)

**What a tile would need** (believed, not built). A stepped STX writes one
register, rb, and a stepped LDX two, rd and then rb - one, when rd is rb;
the register file has one write port. In today's scratch states the port is idle in the cycle
the index is on the bus (`S_SCR_AD`), so a step could ride it there. Under
R18, where a load retires through the array's queue (P1's rule), the step
is a second producer and needs a write cycle a beat unless revision 8
gives it another path - which is what decides this item's worth, below.
Every tile built so far reads CAPS2[12] as zero and never reads imm on the
indexed pair, so it would access without stepping; the loader refuses a
non-zero step there by name.

### What each is worth, counted

`python/rev8_worth.py` writes the kernels the asks are for, each with and
without the new instructions, runs them through the model, holds every
variant bit for bit to a direct computation of the same arithmetic in the
same order and its instruction counts to `seq.run`'s own, and prices them
in the census's terms (docs/VALIDATION.md, 2026-09-25): an arithmetic
instruction 1, a scratch access s - 5.21 at fp64 and 5.08 at fp256 on the
card today, which R18 changes and P1 measures - a loop iteration's
ENDREP e, 1.78 at fp64 and 0.41 at fp256, and a post-step p. The census
cannot price p, because no tile has one: 0 if the step's write rides an
idle port cycle, 1 if it needs its own.

**A Taylor coefficient as a Cauchy product.** Every c_n = sum over j of
a_j b_(n-j), n = 0..N, the two series in the scratch, one lane, three
forms: looped with today's LDX and an IADD and an ISUB a term; looped
with the post-step; and unrolled with static LDL slots, which is today's
ISA too. REPEAT takes an immediate trip count, so both loops unroll the
outer n and loop over j. All three compute the same bits. Prices to the
unit:

| N (terms) | form | words | ALU | SCR | steps | loops | fp64, p = 0 | fp64, p = 1 | fp256, p = 0 | fp256, p = 1 |
|---|---|---|---|---|---|---|---|---|---|---|
| 30 (496) | looped | 342 | 1,581 | 1,023 | 0 | 496 | 7,796 | 7,796 | 6,980 | 6,980 |
| | stepped | 280 | 589 | 1,023 | 992 | 496 | 6,804 | 7,796 | 5,988 | 6,980 |
| | unrolled | 1,551 | 527 | 1,023 | 0 | 0 | 5,857 | 5,857 | 5,724 | 5,724 |
| 64 (2,145) | looped | 716 | 6,630 | 4,355 | 0 | 2,145 | 33,148 | 33,148 | 29,629 | 29,629 |
| | stepped | 586 | 2,340 | 4,355 | 4,290 | 2,145 | 28,858 | 33,148 | 25,339 | 29,629 |
| | unrolled | 6,566 | 2,210 | 4,355 | 0 | 0 | 24,900 | 24,900 | 24,333 | 24,333 |

Per term: looped 3 + 2s + e, stepped 1 + 2s + e + 2p, unrolled 1 + 2s.
What that says, and no more:
- The step saves exactly the two integer adds a term, 2 ALU, when its
  write is free (p = 0): 13.2% of a looped term at fp64 and 14.7% at
  fp256 at the census's s and e, and of a whole product, setup and stores
  included, 12.7% and 12.9% at fp64 (N = 30, 64) and 14.2% and 14.5% at
  fp256. It saves nothing when the step takes a write cycle of its own
  (p = 1), which is where one register-file write port puts it under R18
  unless revision 8 gives it another path.
- Those shares carry the census's own uncertainty. Its loop cost e is not
  resolved - one wall-clock run moves it anywhere from about 0.5 to 5.5 ns
  (the same entry's corrections, verifier-V2) - so a looped term's share
  is 12.0 to 14.6% at fp64 and 14.4 to 15.1% at fp256, and an order-30
  product's 11.7 to 14.1% at fp64. The census records s's own spread
  under the same noise too (4.7 to 5.7 at fp64); these figures take its
  central value. `python/rev8_worth.py` prints each.
- The unrolled form is the cheapest in time, because it has no loop:
  5,857 against the looped 7,796 and the stepped 6,804 at fp64, N = 30.
  It pays in words - O(N^2): 1,551 at N = 30 and 6,566 at N = 64 for one
  product, where the stepped loop takes 280 and 586.
- So what the step buys is a looped product at 2 ALU a term less than
  today's loop, in O(N) words. That is worth having where a program's
  unrolled products do not fit the instruction memory (16,384 words, or
  32,768 after revision 7's limits): three order-64 products take 19,698
  words unrolled.
- The ask's "about 3 slots" a term - two loads and an FMA - is the count;
  the time is 1 + 2s + e + 2p. Under R18 as P1 posted it before building
  (the round's ledger), an LDX leaves two bubbles behind it and an LDL
  none, which favours the unrolled static form further; P1's measurement
  says by how much.

**A compensated step.** K steps of x := x + h*f(x) with each addition's
rounding error carried into the next, on f(x) = x, so that the increment
is one FMA and the rest is compensation. The state lives in registers:

| form | words | instructions a step | unrolled by two | the error is exact |
|---|---|---|---|---|
| Fast2Sum (Kahan) | 10 | 5 | 4 | whenever x's exponent is at least y's (sufficient, not necessary); not always |
| TwoSum (Knuth) | 13 | 8 | 7 | whenever the sum does not overflow |
| `augerr` + `augadd` | 8 | 3 | 3 | whenever the sum does not overflow; 754-2019 9.5 then delivers (inf, inf) |

Each step also costs a loop iteration, e. The first two pay a copy (an
IOR) to keep x in one register in a REPEAT body, or unroll by two to
rename it; the pair works in place. So a compensated step is 3
instructions against TwoSum's 7 or 8 - 57 to 62% fewer -
and against Fast2Sum's 4 or 5 - 25 to 40% fewer - with its error exact
for every pair of operands whose sum does not overflow, as TwoSum's is,
where Fast2Sum's is guaranteed exact only
under a condition on them. None of it touches the scratch, so R18 does not move these
figures. The ask's "2 instructions instead of 4" counted one instruction
delivering both halves; on this tile that is two register writes a beat
either way (R21), so the pair's 3 is what a step costs. The three forms
do not compute the same bits - roundTiesTowardZero and roundTiesToEven
part at ties, and Fast2Sum's error can differ where its condition does
not hold - so a
program ported from an RNE TwoSum changes its bits at ties, and each form
is held to its own reference.

What the counts leave out: that the FMA chain is dependent (R13 to R15
price a dependent link at about LATENCY + 1 cycles on a single-pass
tile, which the census's average a does not see); the load-then-use
stall, which the census's s already folds in for its own pattern; the
loop setup and the stores of results, which are the same across a
kernel's forms; and anything a tile adds to build either item.

### R23. Per-lane sticky flags (designed 2026-09-29, revised 2026-10-02 for R24's mark; built golden-first 2026-10-02)

*MODE[24] asks for the block. Feature bit CAPS2[13] =
`cft_caps.seq_features` bit 17 = `CFT_SEQ_FEAT_LANE_FLAGS 0x20000u`. Host:
`cft_run_args.lane_flags` and `lane_flags_bytes`, ABI 0.17; the model's
`Result.lane_flags`.*

*Built golden-first on 2026-10-02 (the step-6 round's R8): the model,
the software backend at ABI 0.17 and the remote protocol. A tile carries
it from revision 8's RTL, and until then every device but the software
backend - and a remote handle over one - refuses the block by name. It
changed how a run reports, so it was written down before any code:
2026-09-29, and its mark on 2026-10-02.*

**The ask** (docs/ROADMAP.md, ask 5): invalid and overflow delivered with
each lane's outputs, so that a design sweep can drop the one variant that
diverged instead of rerunning the batch. Today FLAGS is the OR over the
whole run and over every tile that ran it, so a sweep learns that some
lane raised invalid and not which.

**Which rung.** 754's clause 7 defines what raises each of the five
status flags, and nothing here would change that; what the ask changes is
how many sets of flags a run keeps. RISC-V keeps one: its vector
floating-point instructions OR every active element's exceptions into
the one `fflags` word - "Inactive elements do not set FP exception flags"
(the "V" extension) - which is exactly FLAGS here. Neither has a flag
word per element, so the shape is rung 3's: the machine's existing
per-lane output, the counts.

**Which flags.** A byte a lane:

| bit | meaning |
|---|---|
| [4:0] | the five IEEE flags, in FLAGS's order, as this lane raised them outside every quiet region (R24) |
| [5] | this lane's deposit overflowed (the lane's share of STATUS[4]) |
| [6] | this lane's indexed access fell past the depth under SCRATCH_STRICT (STATUS[5]) |
| [7] | a `raise` marked this lane (R24; the lane's share of STATUS[6]) |

[7] was reserved and zero in this design until 2026-10-02, when the
step-6 plan gave it R24's mark. So [7:5] are STATUS[6:4] one place up,
lane by lane.

The ask names two flags; the other three, the two per-lane STATUS
conditions and the mark cost nothing more in the byte, and they keep three
identities every backend can check, over the lanes the run owns - every
lane below n, and of those the ones the mask keeps where there is one:
- the OR of their [4:0] IS the run's FLAGS;
- the OR of their [6:5] IS STATUS[5:4];
- the OR of their [7] IS STATUS[6].
Sticky, as FLAGS is: raised by the first operation that raises it, never
lowered within a run. A lane the run owns starts every run at zero.

The model's padding lanes are the one place the identities can part, and
only through a seam already recorded: seq.py's ACTALL wakes a lane past
`n_active`, which can then raise into FLAGS and owns no byte, where a
tile's ACTALL wakes only the lanes the caller has (`tb/test_seq_core.py`,
`actall_over_a_ragged_block`). A run a caller makes has no padding lane in
the model, and a tile wakes none.

**Delivered how.** An output block beside the counts, n bytes, lane i's
at byte i, asked for per run:
- the model: `Result.lane_flags`, n values, computed for every run
  whether or not a caller asks for them, as the counts are, and part of
  `Result.state()`, so that P3's fuzz sees them. A masked or padding lane's
  entry is 0: the model's arrays are fresh, R17's convention for its
  counts;
- the host, at ABI 0.17: two fields appended to `cft_run_args` -
  `lane_flags`, n bytes, and `lane_flags_bytes`, which must be exactly n -
  NULL and 0 for none. This design first asked for one field. The count
  is the 0.14 mask's rule: the mask and this block are both byte arrays a
  run's lanes size, (n + 7) / 8 bytes of bits against n bytes, and a
  caller that sized one by the other is refused rather than overrun.
  Refused by name, `CFT_ERR_INVALID_ARGUMENT`, before the run: a count
  with no buffer, and a buffer whose count is not n. Refused by name,
  `CFT_ERR_UNSUPPORTED`, on a device that does not publish
  `CFT_SEQ_FEAT_LANE_FLAGS`. The software backend publishes it. A remote
  handle publishes its server's bit, and unlike the mask, which a client
  compacts away, the block can only be made where the run is, so a remote
  handle refuses it where the server's word lacks the bit. The struct
  grows, so a caller built against 0.16 is refused at its old size, as an
  input struct always is (ABI 0.14 did the same);
- the remote protocol: PROG_RUN_EX's third word, `want_counts` until 0.17,
  becomes `want` - bit 0 the counts, as before, bit 1 this block, and any
  other bit refused by the server's decoder. The response appends `u8[n]`
  after the scratch-out block when bit 1 is set. A run that asks for the
  block travels as PROG_RUN_EX whatever its image's flags, since no other
  frame can carry the bit; a run that does not travels as it does today,
  so a server's per-opcode counts of every existing call are unchanged;
- a tile: MODE[24] asks for the block. It is the lowest bit of the range
  every tile since the scalar guard refuses at start with STATUS[3], so a
  revision-7 tile asked for one refuses the run rather than ignoring the
  ask, and libcft refuses first, by name. A pointer register and kernel
  argument beside `cnt`'s, on the D master because they are written:
  LFLAGS_PTR at 0xB0 as argument 17, which moves VERSION to 0xB00 as
  every appended register has. And CAPS2[13], under the rule every bit
  above MODE[15] has kept since R17. A run that does not ask writes
  nothing and costs nothing. The address, the argument and the VERSION
  are the RTL plan's to confirm;
- not packed into the counts' top byte, which is free today (a count is
  at most 2^20): the counts' values are the ABI, and every caller reading
  them would change.

**What a masked lane reads.** R17's rule for every output: a masked
lane's byte is NOT written - the caller keeps what it put there, as for
its count and its scratch-out. A padding lane is not the caller's and has
no byte: the block is n bytes. A lane SETACT dropped IS the caller's: its
byte is written, with what it raised while it was active - and, if ACTALL
revives it, with what it raises after, as FLAGS would be.

**Where a split run's blocks land.** A lane's byte is a function of its
own inputs and the program alone (P2), so nothing is merged: every byte
is written by the one executor that ran its lane, and FLAGS and STATUS
stay the OR over tiles.
- The software executor writes byte i for lane i, block by block.
- A remote handle scatters each chunk's bytes to the chunk's lanes, as
  it scatters the counts - a masked run's compacted lanes back to the
  lanes they came from.
- On a tile split, each tile writes its own lanes' bytes, from its own
  lane 0, into a buffer of its own, and the XRT backend copies each
  tile's block to that tile's first lane in the caller's buffer, as it
  collects the counts on the host (`host/src/device.c`): a byte a lane is
  never worth a device copy.
- A run split into segments yields a block a segment; a sweep's "did
  this variant ever raise invalid" is the OR over its segments, which is
  the caller's.

**What it costs** (believed, from the RTL's shape; not synthesised):
- flops: eight a lane of a block, 8 x 128 = 1,024 at fp32's 128 lanes -
  this design's seven and the mark. The retire path already holds each
  lane's flags (`lane_flags`) before `wb_flags_or` reduces them under the
  active row (R17), so the change is a register a lane where there is one
  OR today;
- the drain: one more stream after the counts, 32 lanes a beat, so at
  most four beats a block where the counts take sixteen; a write strobe a
  byte, since a block at fp256 is 16 lanes, half a beat;
- the host (built): a byte array in the software executor's block, the
  protocol bit, and device-test's lane-flags leg holding the three
  identities on whatever device publishes the bit.

**What it changes, which is why it is designed before it is built.** A
run's report grows from one FLAGS word to a byte a lane, and "OR over
lanes = FLAGS" becomes a check the audit can make. A version-1
certificate (docs/CERTIFICATES.md) records each segment's flag word and
STATUS, and has no line for a block. This design once said a certificate
would cover the block "as it covers the counts"; version 1 certifies no
counts, since a segment deposits nothing ("The chain" there). Certificate
version 2, designed beside this in the step-6 round, decides how the
block, and a marked lane's replay, are certified. docs/LANGUAGE.md's
"FLAGS belongs to the run, not to a lane" was restated when this was
built: the language's FLAGS is the run's OR over every lane, which the
block splits by lane and adds no verdict to.

**Until certificate version 2.** A run that asks for the block has an
output version 1 cannot cover, so until version 2 is built:
- `cft-segrun` never asks: it zeroes its `cft_run_args` and sets
  `struct_size`, so at ABI 0.17 its `lane_flags` is NULL and its count 0.
  It takes no option that would ask, and an option it does not take is
  refused `usage`, exit 64, as any is (docs/CERTIFICATES.md, "The segment
  runner"). `cft-audit`'s re-runs fill the struct the same way;
- the golden writer and the golden audit run `seq.run` and never read
  `Result.lane_flags`; a version-1 reader refuses any line a block would
  need, `unknown-line` (exit 2), wherever it stands;
- a segment whose run marked a lane is certified as its STATUS says.
  STATUS[6] is a bit of the 32-bit word version 1 records for every
  segment, and every audit re-derives it (`segment-status`). So version 1
  states that a lane was marked, not which, and records no replay; what it
  certifies of such a run is what it certifies of any, that these bits
  came from this program.

**What a program can do without it.** Deposit a health value a lane -
the state itself, checked on the host for a NaN or an infinity. That
catches an invalid or an overflow whose NaN or infinity survives to the
output; it misses one a MIN, a MAXNUM or a SELECT dropped on the way, and
it cannot see underflow or inexact at all. How much of the difference a
sweep needs is the side project's to measure.

**Not proposed:** lowering a lane's flags within a run (754 lowers a
flag only at the user's request, and a lane has no way to make one), and
a per-element block for the elementwise `cft_run`, which the ask does not
reach.

### R24. Flag control: a quiet region and a raise (designed and built golden-first 2026-10-02)

*Control codes 12, 13 and 14. Feature bit CAPS2[14] =
`cft_caps.seq_features` bit 18 = `CFT_SEQ_FEAT_FLAG_CONTROL 0x40000u`.
STATUS[6], `CFT_STATUS_MARKED`. Assembler `quiet`, `endquiet` and
`raise rA`.*

| code | name | effect |
|---|---|---|
| 12 | `QUIET` | open a quiet region |
| 13 | `ENDQUIET` | close the innermost quiet region |
| 14 | `RAISE ra` | for every active lane: OR `ra[4:0]` into FLAGS and (R23) the lane's byte, unless a region is open; and where `ra[7]` is set, mark the lane |

A routine runs quiet, then raises the flags of the operation it
implements:

    quiet
      ...              ; the routine: its result in rR, and in rF its
      ...              ; operation's flags, ORed with 0x80 where its own
      ...              ; test could not decide the last bit
    endquiet
    raise rF

**Why.** A routine's own flags are scaffolding. divfull's run raises
inexact for 6/3, where the division raises nothing, and inexact rather
than divide-by-zero for 1/0 (the step-6 round's survey of the earlier
deferrals measured both, at fp64 and fp256). libcft hides that by muting
the run and ORing in the flag word the image deposits
(`host/src/divsqrt.c`), which a routine inside another program cannot do.
And no opcode raises divide-by-zero at all: softfloat raises it in its
division and its logB, and neither is an opcode, so log(0) could not be
flagged however it was computed. The language's FLAGS is the OR of every
node's IEEE flags (docs/LANGUAGE.md) and its gate compares it bit for
bit, so a routine that is to be a node must raise exactly its
operation's.

**The region: rung 1, 754-2019 5.7.4.** 754's way to run code whose
flags must not stand is saveAllFlags before it and restoreFlags of every
flag after it, then raiseFlags for what the code's caller is to see. A
quiet region is that pair: QUIET is the save and ENDQUIET the restore.
Nothing in a run reads FLAGS or a lane's byte - no instruction tests a
flag; a run writes them and its caller reads them after it, as the
library's status word is written and never read back
(docs/DETERMINISM.md) - so the only effect of the pair that anyone can
see is that flags raised between the two do not stand after it, and
silencing them gives exactly that. It lowers nothing: a flag raised
before the region stands, which keeps 7.1's "Status flags shall be
lowered only at the user's request" as R23 keeps it.

Rung 1 also settles nesting. Nested save-and-restore pairs compose: the
outer restore discards whatever the inner pair let stand, the inner
pair's raise included. So regions nest, a region inside a region changes
nothing, and a `raise` inside a region is silenced. A routine can then be
copied whole into another routine's region and stay correct, with no
rewrite of its flag instructions.

**A bracket, not a saved word: rung 3, because rung 2's answer does not
fit.** RISC-V saves and restores the accrued flags through an integer
register (FRFLAGS and FSFLAGS on `fflags`, the "F" extension's
"Floating-Point Control and Status Register"), and that is the hart's one
word: its flags "indicate the exception conditions that have arisen on any
floating-point arithmetic instruction since the field was last reset by
software". Here that word is FLAGS - the "V" extension ORs every active
element's exceptions into the one `fflags`, "which is exactly FLAGS here"
(R23) - the OR over every lane of the run and every tile that ran it.
No lane holds it,
and a lane that read it would hold other lanes' flags: a register that
depends on the lanes beside it, which P2 forbids, and which a run split
across tiles would make differ by the split. A lane's own byte is R23's
rung-3 structure, not RISC-V's; reading it into a register would be a
path from retirement into the register file, a hazard on every beat in
flight, and flags a program could compute with, and writing one back
lowers a flag, which R23 declines. The machine already brackets a region
of one kind, the loop, with an open and a close; and libcft has this
construction one level up: a composed operation brackets its internal
passes with `cft_flags_mute`, "save-and-restore rather than a boolean, so
it nests", and only the outermost emit reaches the status word
(`host/src/softfloat.h`). R24 is that seam inside a program.

**What a region silences, and what it does not: rung 1.** Every source of
the five IEEE flags: an ALU instruction's, `augadd`'s and `augerr`'s
(R21), and a `raise`'s own [4:0]. They reach neither FLAGS nor (R23) the
lane's byte, so R23's first identity holds inside regions too. Nothing
else: 5.7.4 restores the status flags of 754's five exceptions and no
other state, and STATUS[4], STATUS[5] and the mark are not IEEE flags -
"your buffer was too small" is not one of them (the deposition section
above; R8 likewise). So a deposit that overflows, an access past the
depth under SCRATCH_STRICT and a mark are reported inside a region as
outside one. A region never hides a lost deposit, a suppressed access or
a lane its routine could not decide.

**The raise: rung 1 for what it does, rung 2 for its operand.**
raiseFlags(exceptionGroup) is 5.7.4's, and its group is "any subset of the
exceptions" (docs/HOSTAPI.md, the status word). So a raise ORs and never
clears, and any of the 32 subsets is legal, underflow without inexact
included (R21 raises that combination too). 754 does not say where an
instruction finds the group. RISC-V's answer is a register: Zicsr's CSRRS,
"The initial value in integer register rs1 is treated as a bit mask that
specifies bit positions to be set in the CSR" ("CSR Instructions"), which
`csrs fflags, rs1` applies to the flags. Here each active lane applies its
own register, as the V extension accrues each element's exceptions into
the one word, and under R23 into its own byte as well.

**Which bits it reads: rung 3.** The register's bit pattern, as STX reads
an index:
- bits [4:0] are the five flags in FLAGS's order: invalid 1,
  divide-by-zero 2, overflow 4, underflow 8, inexact 16. That is
  `cft_exception`'s order, the FLAGS register's, a certificate's and that
  of the flag word divfull deposits. RISC-V's `fflags` holds them the
  other way round, NX at bit 0 and NV at bit 4 (the "F" extension's
  diagram of `fcsr`), and a routine here computes its word in this
  contract's order;
- bit [7] is the mark, where R23's byte has it, so the register's low
  byte reads as a lane's byte;
- bits [6:5] are read by nothing, nor is any bit from 8 up. Deposit
  overflow and a strict fault are the machine's reports about itself,
  and no program may claim one.
No value is refused for those bits: the register is data, which is why
an indexed slot is never refused.

**The mark: rung 3.** Neither 754 nor RISC-V has one. Where a raise's
`ra[7]` is set, the lane is marked: R23's bit [7] for the lane, and
STATUS[6], `CFT_STATUS_MARKED`, for the run. STATUS[6] is the first bit no
tile and no backend claims: `rtl/cft_csr.sv` read STATUS as six bits
padded with zeros until revision 8's seam (2026-10-02), which widened it
to seven with [6] wired to cft_seq's err[5], zero until R24 is built. A
marked lane's outputs are still written - its
deposits, its count and its scratch-out are what the program computed, the
same on every machine - and the mark says that the routine's own test found
its last bit undecided, so the lane is to be replayed before its answer is
used. Where it is replayed, and how the replay is recorded, are
certificate version 2's design and the math library's (docs/ROADMAP.md,
M1). A run with any lane marked says so in STATUS whether or not it asked
for R23's block. A region never silences a mark: a mark lost keeps an
undecided last bit as though it were decided, and a mark kept costs at
most a replay.

**Inactive lanes: nothing new.** A lane R17 masks, a padding lane and a
lane SETACT dropped run no instruction, so a `raise` raises nothing for
them and marks none: P3's rule for every flag. QUIET and ENDQUIET are not
per lane: a region is a property of an instruction's place in the
program, the same in every lane. None of the three computes a value, so
P1 holds as it does for the scratch codes.

**Where it is legal: rung 3.** At the top level and at any loop depth,
nesting properly with loops: a region opened in a loop body closes in
that body, and one opened outside a loop closes outside it. Regions nest
four deep, as loops do. Then whether an instruction is quiet depends on
where it stands and on nothing a run computes, so the early exit cannot
see a region (P3): a skipped body's brackets balance, and an inactive
lane raises nothing either way. That is why neither code needs the
top-level rule ACTALL and HALT have.

**A program that halts or ends inside a region is refused: rung 1.** A
region is a save and its restore, and a program that stops between them
has run a save with no restore. Two faithful readings then disagree: in
754's, the flags raised since the save stand, because nothing restored
them; on this machine, they never reached FLAGS. The loader refuses
rather than choose, as it refuses `REPEAT 0` rather than let the model
and a tile disagree about it.

**The loader refuses, by name:**
- an ENDQUIET with no region open;
- a bracket closed out of turn: an ENDQUIET whose innermost open bracket
  is a loop, or an ENDREP whose innermost is a region;
- a fifth nested region;
- a HALT inside a region, and a program that ends with one open;
- every field the three do not read. QUIET and ENDQUIET read none:
  every field and all of `imm` are zero, as for HALT, ENDREP and ACTALL.
  RAISE reads `ra` alone: `imm[25]`, its fifth bit, and nothing else of
  `imm`, with `rd`, `rb`, `rc`, `rnd`, the `k` flags and `kx` zero, as
  for SETACT. No control code reads the bank (R21), so a constant raise
  is a constant moved into a register once.

**Every loader refused these codes until 2026-10-02.** 12, 13 and 14
were unknown control codes to `seq.py`, `host/src/program.c`, `asm.py`
and `host/tools/cft-asm.c`, so no image any of them accepted before then
contains one, and taking them changed nothing that runs: R21's argument
for codes 10 and 11. Code 15 is the first unknown code now. A tile
decodes an unknown code as HALT (`rtl/cft_seq.sv`'s `default` arm), so
every tile built so far would end the run where a region opens. So
libcft refuses an image holding any of the three, on a device without
CAPS2[14], at `cft_program_load`, by name, naming the instruction, as it
refuses R21's codes; a remote handle publishes its server's bit. cftc's
revision-7 targets - `u50-rev7`, `u50-rev7-quad`, `u50-round2` and
`open-core`, whose feature word is revision 6's, 0x7f1f - refuse an
image that needs it as `target-feature`, and its software targets
publish it. The software backend computes R23 and R24 and publishes both
bits, so a software handle's `seq_features` is 0x7ff1f at ABI 0.17,
where it was 0x1ff1f at 0.16.

**The text form.** `quiet`, `endquiet` and `raise rA`, in `asm.py` and
`host/tools/cft-asm.c` alike; the disassembler indents a region's body as
it indents a loop's. cft-asm took R21's and R22's forms in the same step:
`augadd rD, rA, rB`, `augerr rD, rA, rB`, and the optional signed step of
`stx rA, rB, STEP` and `ldx rD, rB, STEP` - one optional sign, then
decimal or `0x` hex, written back only when it is not zero, as `asm.py`
writes it. `programs/check.py` holds the two assemblers byte for byte,
on every source in `programs/` and on generated corpora of each
revision's forms. Its revision-8 corpus reaches all five forms and says
so from the images; its revision-8 arm holds 46 sources and 10 images to
the contract's verdict, the same bytes or the same reason in both; and
its numeric arm holds `stx`'s and `ldx`'s steps at and past their bounds.
`python/tests/test_asm.py`, `python/tests/test_seq_rev8.py` and
`python/tests/test_seq_rev8_flags.py` hold `asm.py` to the model.

**Where it is held** (R23 with it). `python/tests/test_seq_rev8_flags.py`:
the model's regions, raises, marks, bytes and identities, the loader's
refusals, and divfull wrapped in a region raising exactly the division's
flags lane by lane. `host/tests/seq_check.py`'s flag-control corpus:
`program.c` against `seq.py`, FLAGS, STATUS and every lane's byte, masked
and not, strict and not, and its refusals by their words; and, against a
fake server whose HELLO publishes a revision-7 tile's word, each code and
the block refused by name. api-test: the shapes, the old struct size, the
published bits, the refusals, a raise's FLAGS and STATUS[6] and the
block's identities. remote-test: the `want` word, an unknown bit refused,
and the block's round trip. device-test: a raise image loads where the
bit is published and is refused naming RAISE where it is not, and the
lane-flags leg on any device. `host/tests/segrun_check.py`'s `markstep`:
STATUS[6] from the software backend into every certificate's segment
lines, audited, and through a server. cftc: `python/tests/test_cftc.py`.
On a card, where no tile publishes CAPS2[13] or [14], each says what it
refuses by name and what it does not compare.

**What a tile would need** (revision 8's RTL: believed, not built).
- Decode for codes 12 to 14, which the default arm takes as HALT today.
- A quiet depth of three bits, counted by QUIET and ENDQUIET as they are
  decoded, in program order, as REPEAT and ENDREP keep the loop stack.
  Neither walks a beat (R18).
- A quiet tag on every beat that fires, captured as its active row is
  (`wb_act`, the row a beat FIRED with since R18), which gates that
  beat's term in `wb_flags_or`. The tag is the beat's and not the
  region's state at retirement: under R12 to R15's overlap a region's
  edge must not move a beat already in the pipe.
- RAISE through the issue pipe as SETACT goes (R18), waiting only for
  `ra`. Its lanes' `ra[4:0]` join `wb_flags_or` under the fired row and
  the tag, and `ra[7]` sets the mark under the row, tag or not. It writes
  no register.
- STATUS[6]: `eng_err` widened from six bits to seven, and read as
  `{25'b0, eng_err}`. CAPS2[14].
- On the host, the XRT backend maps CAPS2[11] to [14] onto
  `seq_features` bits 15 to 18 behind the VERSION that carries them -
  which it does from revision 8's seam (2026-10-02), behind 0xB00, in
  `host/src/caps_decode.h`; until then it mapped CAPS2[10:4] bit by bit,
  and no higher bit (`host/src/backend_xrt.cpp`). Its `ST_REPORTS` passes bit 6 already:
  0x30 until 2026-10-02, when CV2's reading of the certificate path made
  it 0x70, so a tile that sets STATUS[6] does not lose the mark - and a
  card certificate with it - on the way out, as a tile's STATUS[5] was
  dropped until 2026-09-18 (R8, "What revision 4 does not do"). No tile
  sets the bit today, so on revision 7 the change changes nothing.

**Not proposed.**
- Two codes, with the raise closing the region. It saves one word a
  routine (`quiet ... raise rF`), and makes one instruction mean two
  things by where it stands: a `raise` inside a region would close it
  and one outside would not. The plan of record describes R8F as "Two
  instructions: a quiet region ... and a raise" (docs/ROADMAP.md, "Step
  6"); a region is one construct with an open and a close, as a loop is,
  and three codes keep each instruction to one meaning.
- A region by count (`quiet N`, the next N words): one code fewer, and a
  count a hand-written program has to keep right.
- A quiet bit on every instruction: it would spend `imm[31]`, the
  encoding's last reserved bit and its version guard (kx, above).
- Saving and restoring the flags through a register, RISC-V's shape:
  above.
- A raise from an immediate, CSRRSI's shape: a constant raise is a
  constant in a register, and the mark makes the group six bits where
  CSRRSI's immediate is five.
- Lowering a flag inside a run, which R23 declines: a region lowers
  nothing.

### Revision 8 in the tile (the step-6 round's round 2, from 2026-10-05)

The RTL plan of record (docs/ROADMAP.md, "Revision 8: step 6's RTL
revision") builds revision 8 in `rtl/cft_seq.sv` one item at a time, in
the plan's order. Each line below says what a tile carries once that
item's commit is in it; a bitstream carries it only once one is built
from such a tree.

- **The abort** (built 2026-10-05). A sequencer read burst of the wrong
  length ends the run, the engine's rule since 2026-08-30: from the
  fault on no new burst is issued, read or write; a write burst already
  committed delivers its beats; every read in flight lands, a long burst
  drained to its RLAST; and done comes with STATUS[2]. A read fault on
  the header beat, or on a beat holding any byte of an instruction, ends
  the run the same way with STATUS[0], so no word the memory did not
  vouch for decides what runs. A read fault on data - the constants, the
  bank, the scratch-in, a stream, the mask, a table - completes the run
  as it always did, STATUS[0] saying its outputs are not to be trusted.
  Until then a short burst left the sequencer waiting for ever, and a
  long one handed its extra beat to a later read. `rtl/cft_seq.sv`'s
  contract, item 5, and `S_ABORT`; `tb/test_seq_core.py`'s four `abort_`
  cases (a short and a long burst on every multi-beat read, a long one
  on every single-beat read, a read fault on the header, on an
  instruction and on data, each followed by a clean run on the same
  instance) and `tb/test_krnl_faults.py`'s two sequencer cases through
  the kernel.
- **The fetch's hooks** (built 2026-10-05). `rtl/cft_ifetch.sv` (round
  1's unit, unchanged) replaces the instruction memory: its store holds
  the program's first `IMEM_D` instructions (4,096 on the U50, where the
  memory held 32,768), and past it a program streams from the image
  through the A master, up to `STREAM_D` instructions (2^24 on the U50,
  CAPS2[20:16] = 24; CAPS[23:20] stays 15). The parse hands the unit every
  instruction; the fetch states, the skip and the issue's continuation ask
  it for the word they need next, a cycle ahead as they addressed the
  memory, and wait while a streamed word is on its way; a REPEAT whose
  body starts outside the store moves the store to it; the block's end
  quiesces it, and `S_WAIT_B` waits for it to be idle. Its faults end the
  run through the abort, STATUS[0] or STATUS[2]. The read port is the
  fetch's from a block's first request to its idle, and opens only with
  the main read engine drained. A program of at most `IMEM_D`
  instructions reads nothing during a block and runs in exactly the
  cycles it did (`make seqcycles`' 72 rows the same before and after);
  past the store, a loop pass costs what it costs resident at read
  latencies 0, 125 and 256 (`make seqcyclesstr`). `pc` and the skip's
  depth are a bit wider than log2 of the capacity, the header refuses
  past the capacity, and the open-core configurations build no stream
  (`SEQ_STREAM_D` equal to the store). Held in `tb/test_seq_core.py` at
  `seq_core` (no stream), `seq_coreu50` (past 4,096) and `seq_corestr`,
  which joined `make sim`: a 64-word store and a 2^16 capacity, so nearly
  every program there streams, at those three latencies; and through the
  kernel, `tb/test_krnl_seq.py`'s image of 32,769 instructions and the
  capacity plus one refused at the header.
