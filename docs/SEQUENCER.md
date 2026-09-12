# The orbit sequencer

*The sections below describe **revision 4** (2026-09-11): revision 3's
thirty-two registers a lane, **256-slot per-lane scratch memory** with a
per-run block that fills it and empties it, **16,384 instructions** a
tile and **512-entry constant bank**, plus **R8** - a program may ask
that an indexed scratch access at or past the depth be REPORTED rather
than reduced modulo it. The three sections at the end of this file are
the record of revisions 2, 3 and 4 and the reasoning behind each change;
everything before them has been updated to describe the model as it now
is. VERSION 0x800, CAPS[7:4] and CAPS2.*

*Revision 4 is complete through the RTL as of 2026-09-11: the golden
model, libcft's executor, both assemblers and `rtl/cft_seq.sv` carry R8,
and `cft_krnl` publishes CAPS2[6]. What has NOT happened is a bitstream -
every image on a card today predates the feature, reads CAPS2[6] as
zero, and refuses a strict image at its header check under the
reserved-bit rule that has guarded `flags` since revision 2. That is not
a divergence: such a tile declines to run rather than computing
something else, and libcft refuses the image earlier and by name
(`CFT_ERR_UNSUPPORTED`) rather than letting the header check say it with
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
select registered at the accepted start; the CSR map carries
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

The core is green - `tb/test_seq_core.py` scores its fetch, execute
and drain body against `seq.py` directly, **17/17 suites** since
revision 3 added five (the four scratch codes, the block in and out,
the header refusals, and a scratch fuzz), where indexed constants
made it 10 on 2026-09-07 and revision 2 made it 12 - and both
sequencer targets,
`krnlseq` and `seq_core`, are in `make sim`, folded in on the day the
core passed, which was the only day the claim would mean anything. On
this tree the whole set holds: seq_core 17/17, krnlseq 1/1, krnl 2/2,
reduce 3/3, reduceacc 5/5, krnlfused 2/2, krnlplain 2/2, quarter 1/1,
faults 5/5, the golden model's own pytest cases, `make yosys-lint`
clean, and the Verilator width gate clean. The last of
those is not decoration: it is fatal-on-width here, and it caught seven
implicit-width sites in `cft_seq.sv` that Icarus and yosys both
passed.

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
carries, executed by the same `cft_fpfma_pipe` and `cft_simpleops`
that 441,000 conformance and differential cases already cover. A
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

Each lane owns **32 registers** of format width, **256 scratch slots**
of format width, and one **active** bit. The registers are the working
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
all but one idle.

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
turns.

Revision 3's scratch is the same arithmetic with a much larger first
factor:

    scratch  =  SCRATCH_D slots * LATENCY beats * 32 bytes

which at 256 and 16 is **128 KiB a tile**, eight times the register
file and the largest of the three on today's parameters - and the same
size, to the byte, as the instruction memory R6 grew, which is not one
of the three because it is per tile rather than per lane. It is
precision-independent for the reason the other two are, and it is the
number a smaller part turns down first: `SCRATCH_D` is a build
parameter, the tile publishes its log2 in `CAPS2[3:0]`, and a program
that needs more than a device has is refused where it was built.

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
| 55:32 | `imm[23:0]` | the three constant indices under `kx`; the SLOT on `STL`/`LDL`; part of the trip count on `REPEAT`; zero otherwise |
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
instantiates it, and not part of the program model: **`MAXD = 64`
deposit slots a lane**, `IMEM_D = 16384` instructions (4096 at
revision 2, 1024 before it, which is what the card-day images hold),
`KMEM_D = 512` constants (256 until revision 3), and **`SCRATCH_D =
256` scratch slots a lane**, new at revision 3. A header that asks for
more than any of them - including a scratch count past the depth - is
refused by the tile at the header, before the constants and
instructions stream in, in the same check that refuses a precision
the tile was not configured for.

`SCRATCH_D` is the one of the four that is NOT purely a capacity: the
indexed forms `STX`/`LDX` reduce `rb` modulo it, so a tile with a
different depth would compute different answers rather than merely
accept larger programs. That is why the model fixes it too, and why
it must be a power of two.

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
Zero in a field means the device did not say (only a remote server
older than the fields), and an unknown cap is enforced against
nothing. The nibble at CAPS[7:4] is now FULL; the next sequencer
feature takes a bit of CAPS2, which is what that register exists for.

Programs that deposit once an iteration feel the deposit budget
first: `cft-zoom` deposits two values a trip and takes
`--steps-per-call` from `cap / 2` when the device's cap is smaller
than its default of 1,024 - 32 on today's tile - and refuses a value
the user typed that does not fit; `cft-orbits` deposits four a sample
for a whole run in one call, so its sample count is bounded at 15 on
a tile, and it refuses by name because unlike a trip count the sample
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
- a program that names a register above 15, or uses `kx`, or is
  `BANK_EXT`, or uses the scratch, or declares scratch I/O, or names a
  constant at or past 256, on a device whose CAPS or CAPS2 does not
  publish that feature - by name, naming the instruction, before the
  register map is touched. An old tile has no rule that would refuse
  any of them: its operand mux reads the low four bits of a register
  field or the low eight of a constant index, its FETCH reads
  constants out of an image that may have none, and it decodes an
  unknown control code as `HALT`.
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
  from a register and the immediate is read by nothing. On all four,
  every remaining register field, `rnd`, `ka`/`kb`/`kc` and `kx` must
  be zero.

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
  is - but only as far as the program can reach into it: every slot if
  the program indexes, otherwise the highest static slot it names and
  the slots the scratch-out drain will read. Wiping all of it every
  block would cost `SCRATCH_D * NBEATS` cycles - 4,096 at today's
  parameters, eight times the register file's - whether or not the
  program owns a slot, and a program that names none must cost nothing
  for a memory it never touches.

The control is an issue/drain state machine, and the counts fall out
of the sizing: issue `LATENCY` beats of one instruction back to back,
then drain `LATENCY` cycles while the results retire and write back,
then advance the program counter. Every ALU is busy during issue, so a
dependent chain costs `2 * LATENCY` cycles per instruction rather than
`LATENCY` with one ALU busy - a factor of `lanes_per_beat * LATENCY`
more work per cycle than the naive schedule.

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
scratch blocks, the outputs (R5's ABI 0.10). The struct exists so the
positional signatures stop growing by an argument a round; the older
two remain as wrappers that fill it, and a program that declares
scratch I/O refuses both by name and takes `run_ex`. The model's
`run(prog, a, b, c, bank=None, scratch_in=None)` is the same shape,
and returns the scratch-out block beside the deposits.

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
six-control-code ISA with no additions, in under fifty instructions
and six constants.

## What the workloads asked of the program model (2026-09-04)

Five workloads were written against the contract after the first
customer (docs/BENCHMARKS.md, "Workloads designed for the contract"),
each told to run its inner step as a program where the model could
hold it and to say precisely what stopped it where it could not. Four
of the five stopped somewhere, and the asks below are theirs, recorded
here because this is where the next revision of the model will be
designed. None is built; all five tools keep a host loop that is bit
for bit the program's equal, so nothing waits on them.

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
  two values that change every iteration and are shared by every lane
  - the reference orbit's point - and there is no operand source that
  advances with the loop counter: a fourth stream read by iteration
  index, or a constant bank the counter can address.
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
  `cft_sqrt` are programs themselves, partitioned host-prep,
  program-core, host-finish, and the core alone uses thirteen
  registers, so they cannot be inlined into another program's loop
  body; any kernel that needs correct rounding inside its loop leaves
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
revisions 2 and 3, it carries no build-cost note, because the tile half
has not been built. Saying anything else in this position would read as
a measurement.

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
depth is published as a log2 and is therefore a power of two. A tile
will need the same: an OR-reduction of the index bits above
`$clog2(SCRATCH_D)`, not a wider comparator.

### What revision 4 does not do

It has not been built. The RTL is written and simulated - 18/18 and 1/1
under Verilator and again under Icarus, `yosys-lint` clean, and the
directed case fails when the flag is disconnected - but no bitstream
carries it, so every card in service reads CAPS2[6] as zero and turns a
strict image away.

It does not change what a program without the flag computes, anywhere:
the modulo is untouched, and that is what every image built before
revision 4 means.

And it does not make the depth portable. A program that needs 300 slots
still needs a tile with 300 slots. What it makes is the difference
between having them and not having them *audible*, which is the part
that was missing.
