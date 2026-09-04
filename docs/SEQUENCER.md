# The orbit sequencer

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
carrying a program and silicon are still open. The RTL was pulled
forward from v2 deliberately: an open core fed by DDR or
PCIe-to-host-RAM cannot afford a memory pass per step, so the
sequencer stops being a throughput refinement there and becomes the
architecture.

What exists around it as of 2026-09-01: `cft_seq` is instantiated in
`cft_krnl` as a peer of `cft_engine_stream`, sharing the A and D
masters *and the tile's one `cft_lanes` array* under a `MODE[15]`
select registered at the accepted start; the CSR map carries
`PROG_PTR` and `CNT_PTR` at 0x54 and 0x5C (VERSION 0x600, CAPS bit 15)
and `hw/kernel.xml` carries the matching arguments 6 and 7;
`cft_program_run` dispatches to the device when the program was loaded
on one, through `cftx_program_run` on a single compute unit;
and `tb/test_krnl_seq.py` scores a full-kernel run against `seq.py` on
deposits, counts, FLAGS and STATUS. The plumbing is therefore testable
ahead of the core, which is the point of writing the contract down
first.

The core is green - `tb/test_seq_core.py` scores its fetch, execute
and drain body against `seq.py` directly, 9/9 suites - and both
sequencer targets, `krnlseq` and `seq_core`, are in `make sim`, folded
in on the day the core passed, which was the only day the claim would
mean anything. On this tree the whole set holds: seq_core 9/9, krnlseq
1/1, krnl 2/2, reduce 3/3, reduceacc 5/5, krnlfused 2/2, krnlplain 2/2,
quarter 1/1, faults 4/4, the golden model's own 370 pytest cases, `make
yosys-lint` clean, and the Verilator width gate clean. The last of
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

*Status 2026-09-02, from docs/VALIDATION.md's entry "the sequencer
passes on a device": the bank fix (40149b1) put every sequencer
program through hw_emu on the real XRT stack at fp32 - 28 checks, 0
failed, every program shape - before the 90-minute emulation cap
stopped the run in fp64. The emulation gate is met for the sequencer
at fp32; fp64 and above are unrun there, not failed; and there is
still no card. The paragraph above is kept as the record of the
morning that found the bug.*

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

- every register write, every deposit **and every exception flag** is
  masked by the lane's active bit, so an all-inactive loop body is a
  no-op by construction;
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
        u32 reserved[2];
    };

Then `n_consts` format-width constants, then `n_insns` 64-bit
instructions.

Each lane owns **16 registers** of format width and one **active**
bit. The constant bank is separate and read-only: constants are shared
across lanes, so putting them in the register file would multiply
their cost by the lane count for no benefit. On a chiplet that
distinction is most of the area argument.

**The inputs are the streams that already exist.** A lane starts with
`r0`, `r1` and `r2` loaded from the same three operand streams the
elementwise engine already reads, and `r3..r15` at `+0`. So a
sequencer run needs no new input path in the hardware, no new CSR, and
no new host concept - the seed point, its parameter and whatever else
the map needs arrive exactly the way `a`, `b` and `c` always have.
Only the output widens, from one element per lane to `max_deposits`.

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

## Execution model, and why the lane block has a floor

The ALU is `cft_fpfma_pipe`: **15 stages, fixed latency, no stall path
and no ready signal.** A sequencer that issued one instruction and
waited for its result would bubble 14 cycles out of every 15 - which
would cost more than the arithmetic intensity the sequencer exists to
buy, and the whole design would be pointless.

The fix is not a bypass network. It is that **lanes are independent**,
so one instruction issued across a block of lanes is that many
independent operations, and they fill the pipe on their own.

The engine already instantiates one ALU per lane per beat - eight at
fp32, one at fp256 - and issues one beat per cycle. So to keep a
15-stage pipeline full the sequencer must hold

    LATENCY beats  =  LATENCY * lanes_per_beat  lanes

on-chip, and issue one instruction across all of them before it needs
the first result. A dependent chain then costs `LATENCY + LATENCY`
cycles per instruction with every ALU busy, instead of `LATENCY` with
all but one idle.

The pleasing part is that this makes the register file
**precision-independent**. A beat is 32 bytes whatever the format, so

    register file  =  16 registers * LATENCY beats * 32 bytes  =  7.5 KiB

at fp32, fp64, fp128 and fp256 alike - 120 fp32 lanes or 15 fp256
lanes, the same silicon. The deposit buffer scales the same way:

    deposit buffer  =  max_deposits * LATENCY beats * 32 bytes

so it passes the register file at `max_deposits > 16` and dominates
from there, which is the regime an orbit actually wants. The earlier
claim that the deposit buffer simply dominates was written before the
lane-block floor was worked out; both numbers are the design, and
trading pipeline depth against deposit depth is the axis a chiplet
turns.

Two consequences worth stating now, because they constrain the RTL:

- **`n` below `L` cannot fill the pipe.** At fp256 that means fewer
  than 16 elements runs at pipeline speed rather than throughput
  speed. It is correct, just slow, and the library should not pretend
  otherwise.
- **The early exit may fire late, and that is free.** `any(active)` is
  a cross-lane reduction over a mask that the last `SETACT` writes 15
  cycles after it issues, so testing it exactly at the loop back-edge
  would cost a drain every iteration. It does not have to be exact:
  firing an iteration or two late is *still invisible*, because those
  iterations are no-ops by P3. The hardware can use whatever mask it
  has to hand.

## Instruction encoding

One 64-bit little-endian word.

| bits | field | meaning |
|---|---|---|
| 7:0 | `op` | ALU opcode when `ctrl=0`, control code when `ctrl=1` |
| 11:8 | `rd` | destination register |
| 15:12 | `ra` | source A |
| 19:16 | `rb` | source B |
| 23:20 | `rc` | source C |
| 26:24 | `rnd` | 754 rounding attribute for this instruction |
| 27 | `ka` | source A names the constant bank, not a register |
| 28 | `kb` | as `ka`, for source B |
| 29 | `kc` | as `ka`, for source C |
| 30 | — | reserved, must be zero |
| 31 | `ctrl` | this is a control instruction |
| 63:32 | `imm` | immediate, control instructions only |

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

`SETACT` narrows and never widens. Lanes drop out as they converge and
stay out, which is what an escape-time iteration wants and what makes
the early exit meaningful. Widening is `ACTALL`'s job alone, and it is
confined to the top level so that P3 holds.

Loops nest four deep, and `HALT` and `ACTALL` are legal only at the
top level.

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
- a constant index outside the bank, a reserved bit, a reserved header
  word, or trailing bytes after the instruction stream
- **any field an instruction does not read being non-zero.** An ALU
  instruction has no immediate; `DEPOSIT` reads only `ra`. Leaving
  those free would mean one operation had many encodings, and then a
  readback hash is not a hash of the program - which is the whole
  point of being able to read the program back. It also keeps the
  natural RTL honest, since a shared operand-fetch mux would otherwise
  see a stray `ka` on a `DEPOSIT` and index a constant bank that may
  be empty.

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

Three structures, sized in the section above:

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
