# The orbit sequencer

STATUS: design and golden model. The RTL follows, and is verified
against `python/cft_golden/seq.py` exactly as the FMA core was
verified against `softfloat.py`.

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
so one instruction issued across a block of L lanes is L independent
operations, and they fill the pipe on their own:

    L >= LATENCY

is the design's central sizing constraint. Sixteen is the practical
number. At fp32 a beat is 8 lanes, so L=16 is two beats; at fp256 a
beat is one lane, so L=16 is sixteen beats held on-chip at once. A
dependent chain then runs at one instruction per L cycles with the
pipeline full, rather than one per 15 with it empty.

That constraint, not the deposit depth alone, sets the on-chip memory:

| structure | size | fp256, L=16 |
|---|---|---|
| register file | `L * 16 * element_bytes` | 8 KiB |
| deposit buffer | `L * max_deposits * element_bytes` | 32 KiB at `max_deposits=64` |

So the deposit buffer dominates once `max_deposits > 16`, which is the
regime an orbit actually wants - but *only* then, and the earlier claim
that it simply dominates was written before the lane-block floor was
worked out. On a 130 nm chiplet both numbers are the design, and
trading L against `max_deposits` is the axis.

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
excess and raises a sticky **deposit-overflow** bit in `STATUS`, not
in `FLAGS`: the five IEEE flags mean what 754 says they mean, and
"your buffer was too small" is not one of them. (`STATUS` bits 0..2
are the engine's bus faults today and `cft_csr.sv` hardwires the rest
to zero, so bit 3 needs a path out before this can be reported at
all - a small RTL change, listed here so it is not forgotten.)

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
