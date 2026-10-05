# R8S: instruction streaming

A design study, 2026-10-02, parcel S8 of the step-6 round. Revision 8
reads the program from card memory instead of holding it on chip
(docs/ROADMAP.md, "Step 6 ... (plan of record, 2026-10-02)", R8S). This
study designs the fetch, prices it, and outlines the RTL plan, which goes
to Logan before any RTL work. Nothing in it is built. Every file and line
number is the tree at 1acc73a. (Since 2026-10-03 the fetch unit is
built, alone, and no tile carries it yet: section 13 records it as
built, with the interface round 2 wires and every departure from
sections 2 and 3.)

How each number is marked:
- **measured**: read from a Vivado report or a card run, or run for this
  study, named where it is used;
- **computed**: arithmetic on the RTL's parameters or on measured numbers,
  shown;
- **estimate**: mine, and said so.

The scratch scripts this study ran, and their outputs, are in the round's
ledger (`Data/runs/2026-10-02-step6-round/ledger/S8.md`, gitignored).

## Why

Logan's plan, verbatim: "R8S, instruction streaming. The program is read
from card memory through a prefetch, not held on-chip, so the instruction
ceiling goes. The image format and the certificate are unchanged, and the
compiler needs only a target that names the larger capacity." The
capacity needs a field past CAPS[23:20]'s 2^15, in CAPS2.

Nine of the eleven hard workloads that missed the card exceed the 32,768
instructions (Data/runs/2026-10-01-hard-workloads/results/README.md).
With no branch and no call, the fetch is predictable apart from REPEAT's
backward jump.

## The design in brief

- **Where.** The tile's A master, the one the image already sits behind.
  The port carries nothing while a block executes, so the fetch has it to
  itself then, and gives it back before the next block's setup reads.
- **The fetch.** The on-chip instruction memory stays, shrunk from 32,768
  words to a 4,096-word store that holds one contiguous range of the
  program. Past the range, instructions stream through a 512-word FIFO
  filled by a read engine with four 8-beat bursts in flight. A realigner
  takes 8-byte instructions out of 32-byte beats at a 4-byte granule.
- **Loops.** The store holds the program's first 4,096 instructions; a
  REPEAT whose body starts past them moves the store to that body, which
  is then replayed from chip. A jump into the store costs nothing; a jump
  out of it costs one redirect, about 180 to 292 cycles (estimate).
- **Stalls.** Zero a step for every image cftc emits today. Each is a
  prologue of one load a pinned value, then `repeat S`, the step,
  `endrep`, the pinned values' stores and `halt`. cftc pins at most 25
  values, so a body starts by pc 26 and is always on chip. In the tree the
  bodies start at pc 1 to 7 (measured), and the hard workloads pin
  nothing, so theirs start at pc 1. A program of at most 4,096
  instructions is entirely on chip and runs in exactly today's cycles.
- **Cost.** 9 RAMB36 a tile against the IMEM's 64: 55 freed, 220 on the
  quad (computed). About 1,000 LUTs a tile (estimate). The fetch path
  loses the deep block-RAM cascade that two single-tile builds named among
  their worst paths.
- **Interface.** CAPS2[20:16], a new five-bit log2 of the instruction
  capacity: 24 on the U50 (2^24 instructions, a 128 MB image). CAPS[23:20]
  stays 15, so a revision-7 host sees 32,768 and refuses by name what it
  cannot send. cft_csr's `caps2` input widens from 16 bits to 32.
- **The deep build.** A quad with streaming and 4,096 scratch slots needs
  516 of 640 UltraRAMs and about 62% of the block RAM: possible by count.
  Whether it closes 135 MHz only a probe build can say.

## 1. Where the instructions come from

### Today

- The host stages the image in the tile's A bank. At a run's start
  `S_IMG_PARSE` reads it through the sequencer's one read port, with one
  burst of up to 64 beats in flight (rtl/cft_seq.sv:358, :2844-2864). It
  takes one action a cycle, peeling an 8-byte instruction or absorbing a
  32-byte beat, and copies every instruction into `imem` (:3103-3225).
  That is 1.25 cycles an instruction plus a round trip a burst (computed).
- On the way past each instruction the parse gathers three things the
  block setup needs before any instruction runs: the highest static
  scratch slot and whether the program indexes (the wipe's extent), and
  which of r0..r2 it reads (the stream loads) (:3150-3191).
- `pc` restarts at 0 at every lane block (:3391). The program runs once a
  block.

### The port, and what shares it

- Every sequencer read goes through one port. cft_krnl steers it to master
  A, B or C by `m_rd_sel`, which is registered with each burst
  (rtl/cft_krnl.sv:705-771). Tile t's master m is HBM[4t + m]
  (hw/link_quad.cfg).
- On master A: the image, the bank, stream a, the scratch-in block, the
  lane mask and the four index tables (cft_csr.sv:179-245; cft_seq.sv:2982,
  :3090, :3105, :3284, :3425). Streams b and c are on B and C.
- Every one of those reads happens at run start or at block setup. From a
  block's first `S_FETCH` to its `S_DRAIN_SETUP`, no state issues a read.
  So the stream shares master A with the operand stream a and the
  scratch-in in time, never at once.
- **The choice:** the fetch reads through master A. It owns the port from
  the block's first fetch until it is idle after the block ends, and
  `S_WAIT_B`, the block's last state, waits for that, so the next block's
  setup reads find the port free. cft_krnl's steering is unchanged: the
  select is 0 throughout a block.
- **Not a fifth master.** It would be a new kernel argument binding and
  more interconnect, on a part whose SLR0 is at 86.12% of its LUTs (q135b,
  measured), for a port that is idle anyway.

### The bandwidth

How fast the consumer takes instructions, read from the RTL. The
continuation that admits the next instruction needs `nxt_ok`, which is set
only the cycle after a non-final `S_ISSUE` step (cft_seq.sv:4174, :3790).
So an instruction with two or more issued steps can be followed at once,
and one with a single issued step pays `S_FETCH`, `S_FETCH2` and `S_DECODE`
(:3642-3654). SEQUENCER.md's R19 measured the same: "7.0 cycles an
arithmetic instruction and 4.3 a store, fp32, every lane masked".

| block | an instruction every | bytes a cycle | of the port's 32 |
|---|---|---|---|
| full, 16 beats | 16.99 to 17.51 cycles (the ten card workloads, measured) | 0.46 to 0.47 | 1.5% |
| two issued steps, independent instructions | 2 cycles (the RTL) | 4 | 12.5% |
| one issued step | 4 cycles (the RTL; R19 measured 4.3 for a store, 7.0 for arithmetic) | 2 or less | 6.3% or less |

So the brief's "up to one a cycle at a short block" is a bound the RTL
does not reach. The peak demand is half an instruction a cycle: 4 bytes,
an eighth of a beat.

What the port gives:
- 256 bits a cycle at 135 MHz, 4.32 GB/s (computed);
- on the card, the streaming engine sustained 100.6 to 106.8 M beats a
  second on one stream, 0.75 to 0.79 beats a cycle (docs/VALIDATION.md,
  2026-09-09, "the read-ahead pair on silicon").

The stream's peak need is a sixth of what one master has delivered on the
card.

### The round trip, and the prefetch's depth

- **The round trip is not measured directly, but it is bounded.** At
  `AR_DEPTH` 4 the engine kept 64 beats in flight on a stream, and the
  card gave 2.25 cycles a beat (VALIDATION.md, 2026-09-09, "the read-ahead
  the card asked for"). A stream cannot move more than its beats in flight
  per round trip, so the round trip was at most 64 x 2.25 = 144 cycles,
  1.07 us at 135 MHz (computed). That entry's fit is a read latency of 125
  plus 19 cycles of the engine's own, and cft_krnl.sv's comment says
  "about 146 cycles".
- **The design is sized for 256**, the margin the engine itself took.
- **Depth.** At half an instruction a cycle, a 256-cycle round trip needs
  128 instructions in flight: 32 beats, four bursts of eight. The FIFO
  holds 512, four times that. At a full block the same depth covers a
  round trip of over 2,000 cycles (computed).

## 2. The fetch unit

A new module, `rtl/cft_ifetch.sv`, between `cft_seq`'s consumer and its
read port. It has four parts.

1. **The store.** The on-chip instruction memory, kept and shrunk to
   `SEQ_IMEM_D` = 4,096 words of 64 bits: 8 RAMB36 side by side in the
   part's 4K x 9 shape, with no cascade (computed: 4,096 x 64 bits / 32
   Kbit). It holds one contiguous range of the program, [base, base +
   count), at index pc mod 4,096. The parse fills [0, min(n_insns, 4,096))
   at run start, exactly as it fills `imem` today.
2. **The stream.** A FIFO of 512 instructions, `cft_fifo` at 64 bits and
   depth 2^9 (one RAMB36 at 512 x 72), filled in program order from a
   position `spos` by its own read engine:
   - bursts of 8 beats (32 instructions);
   - at most four of the current position's bursts in flight, and up to
     eight counting bursts a redirect has abandoned;
   - one ID, in order, never across 4 KB (the engine's `burst_len` rule),
     never past n_insns;
   - a burst is issued only when the FIFO has room for it beside every
     burst already in flight.
3. **The realigner.** The instruction section starts at byte 32, or at 32
   + n_consts x esz without BANK_EXT. So it is 4-byte aligned, and not
   always 8-byte aligned: two images in the tree, normalabs-fp32 at byte
   52 and sqrt-fp32 at byte 68, are 4-byte aligned (measured, below). A
   288-bit window over two beats yields one instruction a cycle at a
   granule offset fixed for the run.
4. **The rules.** The unit decides them itself, from what the consumer
   asks for:
   - The consumer presents the address it needs next, as it presents it to
     `imem` today: pc + 1 in `S_ISSUE`, and pc in `S_FETCH`, `S_FETCH2` and
     the skip. A `want` bit marks those states, so that `S_DECODE`'s
     re-read of its own word asks for nothing. The word comes back the
     next cycle with `word_ok`, and the consumer says when it takes it.
   - **Hit and miss.** An address in the store's range is read from the
     store. Any other address is the stream's head.
   - **Where the stream stands.** While the consumer is inside the store's
     range, the stream stands at base + count, the first word past it.
     While the consumer is outside, the stream stands at the consumer's
     own address. A presented address that finds it anywhere else - a
     back-jump, a block's restart at pc 0, a sequential step into the
     range - makes the unit flush the FIFO, drop what is in flight and
     refetch from the right place. That is a **redirect**.
   - **Capture.** When a REPEAT enters a body whose first instruction is
     outside the store's range, the store is retargeted to that body: base
     = its pc, count = 0. Every word the consumer then takes from the
     stream at base + count is written into the store, until count reaches
     4,096. A body that fits is replayed from the store from its second
     pass; a longer one keeps its first 4,096 instructions there.
   - **Quiesce.** When the block ends (`S_DRAIN_SETUP`), the unit stops
     issuing, drops what comes back and then reports idle. `S_WAIT_B`
     (cft_seq.sv:4021-4027), the block's last state before the next
     block's setup reads, waits for idle beside the write responses. So the
     quiesce overlaps the drains, which use the write master alone.
   - **Faults.** A non-OKAY response, or a burst with the wrong beat count,
     raises STATUS[0] or [2] as every other read does. The unit delivers no
     word from that burst, and the consumer ends the block as HALT does.
     This is new behaviour: a faulted image parse is executed today.
     Recommended so that a word the memory did not vouch for is never
     executed - a garbage REPEAT count could run for ever - and the run
     still terminates with its STATUS saying why its outputs are not to be
     trusted.

**A program of at most 4,096 instructions** is held whole in the store.
Nothing streams, no read is issued during a block, and every cycle is
today's, so the benches' cycle holds stand for it. Every one of the 73
program files tracked in the tree is that size (measured, below).

### What R14 and R18 need from it

- **R14's fetch under the issue** needs the word at pc + 1 one cycle after
  its address, while the current instruction issues. The store gives it as
  `imem` does now. The stream gives it from the FIFO's head, which was
  prefetched.
- **When the word is not there yet,** `word_ok` is low. The continuation
  then falls to `S_FETCH`, as a one-step instruction's does today, and
  `S_FETCH2` and the skip wait. Nothing else in the issue pipe changes:
  its stages carry their instruction's fields, not its pc.
- **R18** admits every beat-walking control code by the same continuation,
  so it needs nothing more. ENDREP's back-jump is the one jump, and REPEAT
  the one capture point. ACTALL and HALT need nothing.
- **Optional.** The admission tests `32'(pc) + 32'd1 < h_ninsns` on every
  cycle (cft_seq.sv:1472). The unit never returns a word past n_insns, so
  `word_ok` can stand for that test and shorten the admission path.

### Widths

- **Today:** `pc` and `skip_depth` are `[PCW:0]`, one bit wider than
  log2 of the instruction memory (cft_seq.sv:1636-1637), and `lp_body` is
  `[PCW-1:0]` (:897). That is 16 and 15 bits at 32,768.
- **Why pc has the extra bit:** it must be able to equal n_insns, the
  implicit halt (:3646), and the header check admits n_insns equal to the
  capacity (:3041).
- **Streaming keeps the rule,** with PCW = log2 of the capacity, 24 at
  2^24:
  - `pc`, `spos` and the store's end (base + count) can equal n_insns, so
    they take PCW + 1 bits: 25 at 2^24. `pc` must, for the implicit halt,
    and `spos` stands at base + count, which reaches it.
  - The store's base takes PCW + 1 bits too. In an image that bypassed
    the loader, a REPEAT as the last word makes it n_insns.
  - `skip_depth` keeps its `[PCW:0]`, 25 bits, which holds any nesting
    count an image's words can make.
  - `lp_body` stays `[PCW-1:0]`, 24 bits. It holds a body's first
    instruction, and in any image the loader accepts that is below
    n_insns, because the body's ENDREP follows it.
- **With a 24-bit pc,** an image of exactly 2^24 instructions whose last
  word is not HALT would wrap pc to 0 after that word, and the block would
  restart for ever. Section 8 holds that case.
- **Growth:** the loop stack grows by 4 x 9 bits, and the rest by a few
  registers (computed).

## 3. Loops

### Re-fetched, held, or both

Both, by size and by where the body starts.

| loop body | first pass | later passes | each back-jump |
|---|---|---|---|
| inside the store's range | store | store | free |
| starts inside the range, runs past it (every image cftc emits that is larger than the store) | store, then stream | the same | free: the store covers the stream's refill (below) |
| starts past the range, fits the store | stream, captured | store | free |
| starts past the range, longer than the store | stream, first 4,096 captured | 4,096 from the store, the rest streamed | free once captured: the 4,096 cover the refill |

A redirect taken when the consumer jumps into the store is hidden when the
store has enough instructions ahead of the consumer to cover it: about 292
cycles at a 256-cycle round trip. At a full block that is 18 instructions
(computed: 292 / 16.5). At the model's one-beat rate for the hard workloads,
8.9 to 10.9 cycles an instruction (measured, below), it is 27 to 33
instructions. A cftc image's body starts by pc 26: pc 1 to 7 in the tree,
measured (section 4). So the store holds the body's first 4,070
instructions at least, or all of a shorter body.

### A body larger than the store

It costs nothing a pass, if its first 4,096 instructions are on chip
(table above). The stream refills from base + 4,096 while they run.
Measured on the six hard workloads compiled for this study (below): each
is `repeat S` at pc 0 with its body from pc 1, because none of them pins
a value. So Gray-Scott hard (34,721 instructions) runs pc 1 to 4,095 from
chip and 4,096 to 34,719 streamed, every step, with no wait. An image
that pins values opens with their loads, so its body starts later, by pc
26, and the same holds.

It costs one redirect a pass only when its start is no longer on chip: an
outer loop whose inner loop has since moved the store elsewhere (next).

### Nesting four deep

- The store follows the innermost loop that starts past it, because each
  such REPEAT retargets it, and the innermost loop is the one entered last
  and most often.
- An inner loop of up to 4,096 instructions is replayed from chip.
- When an inner loop has moved the store, its enclosing loop's back-jump
  is a miss: one redirect a pass of the enclosing loop. That loop's pass
  contains the whole inner loop, so its cost is at least the inner body's
  instructions times the passes. The redirect is a small part of it.
- When the enclosing loop re-enters the inner one, the inner body is still
  in the store (the image cannot change during a run), and it is not
  captured again.
- The loop stack itself is unchanged: four entries of `lp_body` and
  `lp_left` (cft_seq.sv:896-899), with `lp_body` widened to the capacity's
  width.

### The early exit and the skip

- **The early exit.** An ENDREP with no active lane falls through
  (cft_seq.sv:3688). Falling through is sequential, so the stream is
  already standing there. With the store replaying, the FIFO stood paused
  at the body's end + 1. No redirect, and no prediction to undo.
- **The skip.** A REPEAT with no trips or no active lane scans to its
  ENDREP at two cycles an instruction (:3716-3734). It reads sequentially
  from the store or the stream, as today, and costs only the scan.
- **No prediction.** The unit never guesses, so nothing has to be
  unwound. Only a jump to an address outside the store waits for the
  round trip.

## 4. Stalls

### What a late fetch costs

A redirect costs the round trip, plus up to 32 beats already in flight
ahead of the new request, plus about 4 cycles to issue, realign and pass
the FIFO's bypass:
- 180 cycles at a 144-cycle round trip;
- 292 at 256.

The 32 and the 4 are the design's figures (estimate). The consumer waits
in `S_FETCH2`, or at the continuation. The issue pipe drains meanwhile,
so results still land and nothing is lost.

| event | how often | its stall |
|---|---|---|
| jump into the store | each back-jump to a body start on chip; each block's restart while the head is on chip | none, while the store holds a redirect's worth of instructions ahead of the target |
| a loop captured | its first pass | none: the capture reads the stream in order |
| jump to an address outside the store | each pass of a loop whose start has left the store; each block restart after the store has moved | one redirect |
| the stream slower than the consumer | never, at the depth above | none |
| the block's end | each block | none while the drains outlast what is in flight: the quiesce overlaps them, and `S_WAIT_B` waits for the rest |
| the image scan at run start | each run | today's parse cost: 1.25 cycles an instruction plus a round trip a 64-beat burst |

### A step, for the ten card workloads and the misses

- **With this design: zero cycles a step for every one.**
  - A cftc image is a prologue of one load a pinned value, `repeat S`, the
    step, `endrep`, the pinned values' stores and `halt`
    (python/cftc/emit.py).
  - cftc pins a value only when the state, with or without the lane
    params, fits 25 of its 29 registers (python/cftc/regalloc.py,
    `pinnings`). So a body starts by pc 26, inside the store.
  - That leaves the body's first 4,070 instructions or more on chip,
    ahead of the streamed part: about 67,000 cycles at a full block,
    against a 292-cycle refill (computed: 4,070 x 16.5).
- **The recount** (measured over every tracked program file):
  - The six hard workloads compiled for this study pin nothing:
    `repeat 512` at pc 0, the body from pc 1.
  - The tree's ten cftc reference images are programs/systems/compiled and
    compiled-tangent, the acceptance set's references. Their prologues are
    0, 3, 4 or 6 loads, so their bodies start at pc 1 (Lorenz-96 and its
    tangent), 4 (Lorenz-63), 5 (Henon-Heiles) or 7 (the Lorenz-63
    tangent), at fp64 and fp256 alike.
  - The largest prologue of the 73 files is those 6 loads. No loop body in
    the tree starts past pc 7, so none starts past the store.
  - The misses other than Gray-Scott hard, which I did not compile, pin
    nothing by cftc's rule, as Gray-Scott hard does. Their state alone is
    202 to 5,712 values (the survey's T8), past the 25 registers pinning
    needs. That is computed from the rule, not measured on their images.
- **The table** says what one unhidden redirect a step would cost: the
  price of designing without the store, or of a program that defeats it.
- **The columns.** The card's cycles a step are the card's seconds a step
  times 135 MHz, as measured on revision 7's quad on 2026-10-01
  (Data/runs/2026-10-01-hard-workloads/results/card-main-80abee5/results.json).
  The model's are cftc's cost model, compiled for this study (measured,
  below). The two numbers in a column are for a round trip of 144 cycles
  and of 256.

| program | instructions a step | card cycles a step, hard / wide | model, 16 beats | model, one beat | a redirect a step, % of the card's step | % of the one-beat step |
|---|---|---|---|---|---|---|
| FPUT | 6,657 | 116,226 / 116,035 | 111,060 | 65,853 | 0.15 / 0.25 | 0.27 / 0.44 |
| phi4 | 4,558 | 79,786 / 78,398 | 75,443 | 45,578 | 0.23 / 0.37 | 0.39 / 0.64 |
| Kuramoto-Sivashinsky | 19,006 | 328,601 / 326,178 | 314,067 | 177,251 | 0.06 / 0.09 | 0.10 / 0.16 |
| reservoir | 17,904 | 307,433 / 304,097 | 297,592 | 194,898 | 0.06 / 0.10 | 0.09 / 0.15 |
| Riccati | 20,394 | 353,576 / 349,658 | 336,267 | 181,021 | 0.05 / 0.08 | 0.10 / 0.16 |

For the misses, a card step is estimated as the instructions times the
ten's measured 16.985 to 17.505 card cycles an instruction:

| miss | instructions a step | its limit | a card step (estimate) | a redirect a step |
|---|---|---|---|---|
| Gray-Scott hard / wide | 34,719 | instructions | 590,000 to 608,000 (the model: 573,486, measured) | 0.03% to 0.05% |
| Lorenz-tangent hard / wide | 59,383 | both | 1,009,000 to 1,039,000 | 0.02% to 0.03% |
| FPUT extended | 26,625 | slots | 452,000 to 466,000 | 0.04% to 0.06% |
| phi4 extended | 19,532 | slots | 332,000 to 342,000 | 0.05% to 0.09% |
| Kuramoto-Sivashinsky extended | 76,222 | instructions | 1,295,000 to 1,334,000 | 0.01% to 0.02% |
| reservoir extended | 71,478 | instructions | 1,214,000 to 1,251,000 | 0.01% to 0.02% |

The three larger extended programs (Gray-Scott, Riccati, Lorenz-tangent)
have no instruction count on the desktop; the survey counts 88,066 to
175,082 ALU operations a step for them. Their fractions are smaller still.

What it says:
- Even a design that redirected on every back-jump would cost the misses
  under a tenth of a percent a step, and the ten under 0.4% at a full
  block. The card is already 2.2% to 5.8% slower than the model.
- What a missing store would really cost is small programs over many
  blocks. A divide or root program is 43 to 60 instructions (measured,
  below). A block of one costs about 1,100 cycles (estimate: 50
  instructions at 16, and about 300 of setup and drains, which is what
  `make seqcycles` measures for one instruction and a deposit, SEQUENCER.md
  R15's table). A redirect at every block restart would add 180 to 292 of
  them, 16% to 27%. The store is what makes that zero.
- **Per run,** the image scan. For a program up to 32,768 instructions it
  is today's parse to the cycle. Past that, Kuramoto-Sivashinsky extended
  scans in 138,000 to 172,000 cycles (1.0 to 1.3 ms, computed), against a
  512-step segment of about 5 s (estimate, from its step above). A
  2^24-instruction image would scan in 0.23 to 0.28 s.

### Must schedule.py learn it?

- **Not for what cftc emits today.** Its images have no stall a step under
  this design, and the scan is per run. The card's ms a step is a
  difference of two runs, which cancels a per-run cost, and the model is
  per step.
- **It must learn it before C4.** C4's call loop (docs/ROADMAP.md, step 6,
  part 3) puts a REPEAT inside the step. Once that loop's body starts past
  the store, each step pays one redirect at its own back-jump, and each
  block one at its restart.
- **How:**
  - the target gains two numbers: the store's depth, and the redirect's
    cost as the card measures it (section 8);
  - `schedule.cycles` (python/cftc/schedule.py:205-229) walks the body
    under the store rule and adds a redirect for each miss;
  - the manifest reports the result;
  - the objective does not read it, because the order choice reads no
    capacity, so one image serves every target (python/cftc/__init__.py;
    LANGUAGE.md).
- **A separate gap, noticed in passing.** At one beat, `schedule.cycles`
  charges one cycle for an independent instruction. The RTL takes more:
  - about four for a one-step instruction that writes no register, which
    pays the fetch and decode (above);
  - about seven for an arithmetic one, because each writer holds one of
    the result queue's three slots until its result lands, so independent
    writers are queue-bound.

  R19 measured 4.3 cycles for a store and 7.0 for arithmetic with every
  lane masked (SEQUENCER.md). That is the compiler's secondary objective
  and one manifest column, not this design. It is read from the RTL and
  R19's figures, not measured on these programs, and it is raised as a
  question below.

## 5. The cost

### Block RAM

| memory | today, a tile | streaming, a tile | how it is counted |
|---|---|---|---|
| the instruction memory | 64 RAMB36 (32,768 x 64 bits) | 8 RAMB36 (4,096 x 64 bits) | computed: bits / 32 Kbit; SEQUENCER.md's table says 64 |
| the stream's FIFO | - | 1 RAMB36 (512 x 64 bits) | computed: the part's 512 x 72 shape |
| freed | | 55 a tile, 220 on the quad | computed |

- q135b uses 1,051.5 block-RAM tiles of 1,344 (78.24%): SLR0 541.5
  (80.58%), SLR1 510 (75.89%) (measured, the routed report).
- Freeing 220 leaves about 831.5, 61.9% (estimate).
- One caution. A tile's 217 block-RAM tiles are measured out of context
  (the revision-7 round's ledger), but no report on disk splits them by
  memory, and the geometry does not account for them exactly: revision 7
  measured 136.5 more tiles than f681dee's 80.5, where the geometry of the
  two memories it deepened adds 152 (the IMEM 16,384 to 32,768, +32; the
  deposit buffer at `MAXD` 64 to 1,024, +120; computed). So the 64 is the
  geometry. A hierarchical utilization report in the probe build is what
  confirms how much the IMEM really frees.

### LUTs

| part | LUTs (estimate) |
|---|---|
| read engine: address, burst length at 4 KB, counts, reservation, epoch drop | 200 to 300 |
| realigner: a 64-bit select over a 288-bit window | 150 |
| the FIFO's pointers and its bypass | 100 |
| the store's range, hit and capture | 60 |
| the port's owner select inside cft_seq | 80 |
| the consumer's waits, the widths to 25 and 24 bits, the header check | 100 to 200 |
| what the 32K IMEM's fabric logic gives back | 0 to -200 |
| a tile, net | about 1,000 (500 to 1,500) |

On the quad that is about 4,000 LUTs: 719,697 becomes about 723,700, 83.1%
of the part. SLR0, with two tiles, goes from 86.12% to about 86.6%. These
are estimates; the measured base is q135b's report. For scale, the
engine's read-ahead (AR_DEPTH 4 to 16, FIFO_LOG2 7 to 9) cost +637 LUTs out
of context (VALIDATION.md, 2026-09-09).

### Timing at 135 MHz

What the instruction memory has cost before:

| build | what it measured |
|---|---|
| ra-135single (2026-09-09) | the 16K IMEM, "a seven-deep block RAM cascade", -> al_b_reg, 8 levels: the single's worst path, +0.089 ns kernel WNS. "The one a register stage in the fetch path would buy back." (VALIDATION.md:9623, :9638-9643) |
| rev7a probe single (2026-09-29) | the 32K IMEM's cascade into its state register, +0.101 ns, beside the engine's FIFO into the fp256 FMA; kernel WNS +0.065 (VALIDATION.md:15943) |
| out of context, the merged revision 7 | u_seq's worst path, the IMEM's block-RAM cascade (7 RAMB36 in the path, 18 levels) to bt_reg, +1.885 ns (the revision-7 round's ledger) |
| q135b, the quad | +0.003 ns after post-route phys_opt, every option on (VALIDATION.md:16620-16623). The first attempt, q135, with default directives, missed by 0.457 ns. Its ten worst paths were all in one tile: u_seq's deposit counter decoded into a high-fanout enable, route-bound, and the engine's FIFO block RAM into the fp256 FMA. v++ had warned that "The available LUTs may not be sufficient" (the audit round's ledger) |

What streaming does to the fetch path:
- The admission reads its word from a 4K-deep store (one RAMB36 in the
  path, no cascade) or from the FIFO's head, through one 2:1 select.
  Today it reads through a block-RAM cascade with up to seven hops.
- The hops are what the path loses, and a single LUT level is what it
  gains, often absorbed into the admission's first LUT. How many
  nanoseconds that is, only a build says.
- The new logic is registered and shallow: counters, two 24-bit range
  compares into a registered hit, a fixed-offset realigner, and an owner
  select on registered port signals.
- A wider pc lengthens no admission path: the admission's test
  `32'(pc) + 32'd1 < h_ninsns` is 32 bits wide already, and it can still
  come off the path (section 2, optional). The store's address takes pc's
  low 12 bits; the range compare that uses all 24 is registered.

### Easier or harder to close than today's?

- **The fetch path: easier.** The family two singles named among their
  worst paths (ra-135single's worst; the rev7a probe's second) leaves the
  path.
- **Block RAM: easier.** 55 fewer RAMB36 a tile, and with them a 32K-deep
  address fan-out and its cascade columns.
- **LUTs: slightly harder.** About 1,000 more a tile, in a quad whose
  misses have been route-bound: q135's paths, and CLB sites at 99.73%
  occupied in SLR0 (measured).
- **On balance** I expect the streaming quad at today's capacities to be
  no harder to close than q135b (estimate). The deep build's doubled
  UltraRAM is the larger risk (section 7). Neither is known until a probe
  build is routed.

## 6. The interface

### CAPS2

- **CAPS2[20:16], new:** log2 of the instructions a program may have, on a
  tile that streams. 24 on the U50 (2^24 instructions, a 128 MB image).
  Zero on a tile that holds every instruction on chip, where CAPS[23:20]
  is the capacity.
- **Five bits, not four.** A four-bit log2 stops at 2^15, which is the
  very ceiling this removes. Five reach 2^31. The header's `n_insns` is a
  u32.
- **CAPS[23:20] on a streaming tile:** min(15, log2 of the capacity). So
  it reads 15, the most the field can say, and an old host never sizes
  past what the tile takes.
- **No feature bit.** A program does not use streaming. It is a capacity,
  and a streaming tile computes the same bits.
- **No VERSION step.** No register is added. Bits [31:21] stay reserved,
  zero.
- **R8's bits are untouched.** R21, R22 and R23 hold [11] to [13], and R8F
  (R8's R24) takes [14], leaving [15] free (R8's ledger, section 10).

### cft_csr and cft_krnl

- `cft_csr`: the `caps2` input widens from `[15:0]` to `[31:0]`
  (cft_csr.sv:351), and the read returns it whole where it pads today
  (`{16'b0, caps2}`, :723). The CAPS2 comment (:202-231) gains the field.
- `cft_krnl`: a new parameter `SEQ_STREAM_D`, the capacity. `SEQ_IMEM_D`
  becomes the store's depth. CAPS[23:20] is published from min(15,
  log2 `SEQ_STREAM_D`) (:656), and CAPS2[20:16] from log2 `SEQ_STREAM_D`
  when it exceeds `SEQ_IMEM_D`, else 0 (:599).
- **Streaming is a build's choice.** With `SEQ_STREAM_D` equal to
  `SEQ_IMEM_D`, the unit builds no stream and the tile is today's. The
  open-core configurations keep that: tb/Makefile's `OPEN_CAPS_GENERICS`
  and hw/openxc7 change nothing.

### The loader's n_insns checks

- **The tile.** `hdr_q[95:64] > IMEM_D` becomes `> STREAM_D`
  (cft_seq.sv:3041). The elaboration guards (:866-868, :883-888) take the
  store's depth as any power of two up to the capacity, and the capacity
  as a power of two up to 2^31.
- **libcft.** `cft_program_load`'s `n_insns > c.max_insns`
  (host/src/program.c:900) is unchanged; only where `max_insns` comes from
  changes.
- **The software backend and seq.py** already take any count: `max_insns`
  is 2^32 - 1 (program.c:95-117), and the model accepts an instruction
  count to the header field's 2^32 - 1 (python/cft_golden/seq.py:122-129).
  Nothing changes.

### The host's decode

`host/src/backend_xrt.cpp:2270` becomes:

```
const uint32_t big = (caps2 >> 16) & 0x1Fu;   /* CAPS2[20:16] */
seq->max_insns = big ? (1u << big) : 1u << ((caps >> 20) & 0xFu);
```

- `caps2` is read only where the map has the register (VERSION 0x800 on),
  and is 0 below it (:2075-2083).
- No ABI field moves: `cft_caps.max_insns` is a u32 already. The change
  rides revision 8's ABI step (0.17), which is R8L's.

### Old hosts, new tiles, and the reverse

| host | tile | what it reads | what happens |
|---|---|---|---|
| revision 7 (ABI 0.16) | streaming | CAPS[23:20] = 15; it never reads CAPS2[31:11] (:2239-2263) | max_insns 32,768. A larger image is refused at load by name ("instruction count ... instructions it can hold ... max_insns"); every image it can load runs, streamed past 4,096, to the same bits |
| revision 8 | revision 7 | CAPS2[20:16] = 0: the CSR pads CAPS2's top half today | max_insns from CAPS[23:20], 32,768, as now |
| revision 8 | a tile older than CAPS2 (VERSION below 0x800) | CAPS2 not read, so 0 | the same |
| revision 8 | streaming | CAPS2[20:16] = 24 | max_insns 16,777,216 |

### Everything else that reads a capacity

- **Certificates.** `device-caps` carries CAPS and CAPS2 raw, so it
  carries the capacity with no format change. The audit reads only
  CAPS2[3:0] and [4], for the depth (python/cft_golden/cert.py:1293-1322),
  and re-runs on seq.py or the software backend at any instruction count.
  A revision-7 auditor audits a revision-8 certificate unchanged.
- **The remote protocol.** HELLO carries `max_insns` as a u32, so a server
  fronting a streaming tile reports 2^24 with no protocol step.
- **cftc.** New targets, as the plan says ("The deep build's and the
  streaming build's cftc targets come with it"):
  - `u50-rev8` and `u50-rev8-quad`: `max_insns` 2^24 and revision 8's
    feature word;
  - the deep build's target, at its depth.
  python/cftc/targets.py's table and docstring gain them. Lowering is
  untouched.
- **The image.** The same bytes, header and all. One new sentence for
  HOSTAPI.md: the image buffer is read throughout the run, not only at its
  start, so it must not change between start and done. The library
  already stages it before the start and waits for done.

## 7. With the deep build

**A quad with streaming and 4,096 scratch slots, by the reports' numbers.**
- At 4,096 slots, a word bank is 65,536 entries: 16 sub-arrays of 4,096 x
  32, one UltraRAM each, as revision 7 builds them. That is 128 a tile
  against 64 (computed from cft_seq.sv:711-714).
- q135b's URAMs are 132 in SLR0 and 128 in SLR1. That reads as two tiles
  a SLR, with the shell's 4 in SLR0 (inferred from the counts; the report
  does not name tiles).

| resource | q135b (measured) | + streaming (estimate) | + 4,096 slots | the part |
|---|---|---|---|---|
| LUTs | 719,697 (82.66%) | about 723,700 (83.1%) | about 726,100 (83.4%) (estimate: +600 a tile for the 16:1 sub-array select) | 870,720 |
| SLR0 LUTs | 378,652 (86.12%) | about 86.6% | about 86.8% | |
| block-RAM tiles | 1,051.5 (78.24%) | about 831.5 (61.9%) | the same | 1,344 |
| URAM | 260 (40.63%) | 260 | 516 (80.63%) (computed) | 640 |
| URAM, SLR0 / SLR1 | 132 / 128 of 320 | the same | 260 / 256 (81.3% / 80.0%) (computed) | 320 a SLR |

**Possible by count.** Every resource fits. The tightest are SLR0's LUTs,
at about 86.8%, and SLR0's UltraRAMs, at 81%. Streaming's freed block RAM
is what keeps the block-RAM column from being a third tight one.

**8,192 slots.** That is 256 UltraRAMs a tile, 1,028 on a quad: it does
not fit (computed). A single (260) or a dual (516) holds it, as the plan
says.

**One option the RTL plan should test before choosing 8,192's shape** (a
design, not measured). Each 4,096 x 32 sub-array fills one UltraRAM288,
whose shape is 4,096 x 72 (the part's documentation). So 32 of every 72
bits are used.
- Two sub-arrays of one bank could share a URAM: one port writing with
  byte enables for one half, the other port reading, and the half chosen
  by the slot's next bit.
- The broadcast wipe writes both halves at once.
- That would hold 4,096 slots in today's 64 URAMs a tile, and 8,192 in
  128: 516 on the quad, which fits.
- It is a change to the scratch (`g_sub`, cft_seq.sv:739-772), not to
  streaming. Whether Vivado maps it to one URAM288 per pair is a synthesis
  question, cheap to ask out of context.

**What only a probe build can answer:**
1. Whether the quad with 516 URAMs and about 1,600 more LUTs a tile routes
   at 135 MHz. q135b closed with three picoseconds to spare and every
   option on. q135 missed on route-bound paths. SLR0's CLB sites are
   99.73% occupied.
2. Whether doubling a tile's URAMs spreads its scratch far enough from its
   lanes to matter. Out of context, the URAM paths have +4.280 ns
   (VALIDATION.md:15941), but that is not in a quad's context.
3. The fetch path's real slack, with the cascade gone. And whether Vivado
   keeps the store cascade-free: `cascade_height` pins it if not.
4. How much block RAM the IMEM really frees: the 217's split, from a
   hierarchical utilization report.
5. Whether the packed URAM above infers as designed.
6. And on the card, not the build: the redirect's real cost (section 8).

## 8. The verification

### Benches (cocotb; Verilator while iterating, Icarus for `make sim`)

- **Every existing bench, at the configurations it runs:**
  - `seq_core` (64 / 1,024 / 256, no stream);
  - `seq_coreu50` (streaming past 4,096, which its programs, all small,
    do not reach);
  - `seq_coremc` and `seq_coreu50mc`;
  - `krnlseq` and the kernel benches;
  - the open-core configurations, streaming off.
  All are bit for bit against the model. Programs within the store run in
  today's cycles, so every cycle hold stands as written. Two cases move,
  because they test the capacity: the refusal matrix's `IMEM_D + 1`
  (tb/test_seq_core.py:1403) and krnlseq's "IMEM full and one past it"
  (tb/test_krnl_seq.py:923-966) both read the capacity, `STREAM_D`, where
  they read `IMEM_D` (below).
- **A new configuration, `seq_corestr`:** `cft_seq` with a 64-word store
  and a 2^16 capacity. Nearly every program in `tb/test_seq_core.py` then
  streams, so the whole suite runs through the stream against the model.
  `SeqRam` (tb/test_seq_core.py:233) gains a read latency, the
  `CFT_RD_LATENCY` knob tb/busfx.py gives the kernel benches, at 0, 125
  and 256. It already takes four bursts in order. Cycle holds written for
  programs the store holds do not apply here; the new holds below do.
- **New cases in `tb/test_seq_core.py`,** each against seq.py:
  - `a_program_longer_than_the_old_imem`: 36,864 instructions, the old
    32,768 and a store's worth more, built as krnlseq's `prog_fills_imem`
    builds its image (tb/test_krnl_seq.py:652). The bulk is skipped at
    two cycles an instruction, so every word crosses the stream and an
    aliased or misaligned one lands the skip on the wrong ENDREP. The last
    four execute at addresses past 2^15. About 120,000 cycles (computed
    from that bench's own 107,000 at 32,768). Beside it, the capacity plus
    one is refused at the header with no instruction read: a header-only
    image, since a whole one would be 128 MB.
  - `a_program_of_exactly_the_capacity`: two images of exactly 65,536
    instructions at `seq_corestr`'s 2^16 capacity, in `prog_fills_imem`'s
    shape. (The U50's 2^24 is too long to simulate, and the RTL is the same
    at either.)
    - One ends in HALT.
    - The other's last word is a DEPOSIT, so the block ends by the
      implicit halt with `pc` equal to the capacity.
    - Both are held against the model. The second hangs, and fails by the
      bench's timeout, if `pc` is one bit short and wraps to 0 (section 2,
      Widths).
    - About 214,000 cycles each (computed from that bench's 107,000 at
      32,768).
  - `a_loop_body_longer_than_the_store`: at the 64-word store, a
    200-instruction body that starts inside the store and one that starts
    past it. The first is held to its store-resident twin's cycles a pass
    within a bound. The second is held to at most one redirect a pass.
  - `a_loop_that_fits_is_captured`: a body that starts past the store and
    fits it costs, from its second pass, what its resident twin costs.
  - `nesting_four_deep_streamed`: four REPEATs with bodies on both sides
    of the store's range, an early exit by SETACT at each depth, and a
    skip at each depth.
  - `block_restarts_after_a_retarget`: several blocks, pc 0 refetched.
  - `misaligned_instruction_sections`: self-contained fp32 images at every
    4-byte granule offset modulo 32 (two such images are in the tree),
    and BANK_EXT images.
  - `the_stream_across_4k`: an image placed so that naive bursts would
    cross 4 KB. SeqRam's `_check_burst` already refuses a crossing.
  - `fetch_quiesces_before_the_next_block`: SeqRam's AR log shows no fetch
    burst outstanding when a block's mask, scratch-in or stream reads
    issue.
- **`tb/test_krnl_faults.py`:** a non-OKAY response, and a short burst,
  during the stream. Each raises its STATUS bit, ends the block, writes
  nothing more of it, and the run terminates.
- **`tb/test_krnl.py`:** CAPS[23:20] = 15 and CAPS2[20:16] = 24 at the
  U50's defaults; 14 and 0 at the open-core values. `tb/krnl_caps.py`
  learns `SEQ_STREAM_D`.
- **`tb/test_krnl_seq.py`:** "`IMEM_D` full and one past it" becomes
  the same 36,864-instruction image loading and running through the
  kernel, with the capacity plus one refused at the header.
- **`make seqcycles`** (`tb/probe_seq_cycles.py`) gains rows for streamed
  programs at the 64-word store, so the price stays visible.
- **The plants,** each in a fresh copy of the tree and each red in a named
  case:
  1. the store's range one past its end;
  2. a redirect that keeps the FIFO's words;
  3. abandoned bursts' beats not dropped;
  4. the realigner one granule off in the 4-byte case;
  5. a retarget that keeps the old count;
  6. no quiesce (a fetch beat lands in the next block's stream load);
  7. a faulted word executed;
  8. CAPS2[20:16] published from the store's depth instead of the
     capacity;
  9. `pc` one bit short, `[PCW-1:0]`, red in
     `a_program_of_exactly_the_capacity` as a hang.

### Formal

- **None of today's proofs covers `cft_seq`** (formal/README.md).
  `fifo.sby` covers the stream's FIFO if it is a `cft_fifo` instance:
  proven at width 8 and depth 8, and argued at 64 x 512, as the engine's
  256-bit instances are.
- **A new proof, `formal/ifetch.sby`,** with `tb_ifetch_formal.sv`, proves
  the unit at small parameters, in `fifo.sby`'s manner: a 16-word image
  space, a 4-word store, an 8-word FIFO, a shadow memory. It covers every
  consumer sequence (wants, addresses, takes, REPEAT entries, quiesces)
  and every in-order slave timing:
  - a word the consumer takes is the image's word at the address it
    presented;
  - no read goes past n_insns or across 4 KB, and every ARLEN is honest;
  - after a quiesce, no read is issued, and idle is reached within a
    bound;
  - the FIFO never overruns its reservation.
- **Covers:** a redirect with bursts in flight, a straddling word, a
  capture that fills the store, an underrun, and an image of exactly the
  16 words, so that `spos` and the presented address reach n_insns
  itself.
- **Bookkeeping.** formal/run.sh gains the `run_proof` line, and the
  proof counts in docs/VERIFICATION.md and the root README move with it.
- **Lint.** `yosys-lint`, the open-toolchain gate, and Verilator's fatal
  warnings take the new module.

### What the card must show

1. **The acceptance set** (`programs/acceptance.py`): 20 of 20 on the
   streaming quad. Its references sit inside the store; its ten workloads
   (4,560 to 20,396 instructions) stream past it.
2. **The ten workloads' ms a step** against revision 7's quad on
   2026-10-01: equal within the run-to-run spread, which is the design's
   claim of no stall a step.
3. **The misses the build holds,** each bit for bit with the software
   backend at the device's depth, on the pack's three lanes and on every
   lane, as A1's driver holds the ten:
   - on the streaming quad: Gray-Scott hard and wide, Kuramoto-Sivashinsky
     and reservoir extended (instructions only; 1,066 to 1,562 slots);
   - with 4,096 slots as well: Lorenz-tangent hard and wide, FPUT and phi4
     extended.
4. **The redirect's cost.** A probe program whose loop body starts past
   the store and exceeds it, so it redirects once a pass, against the same
   body inside the store. The difference a pass is the redirect. It
   replaces this study's 180 to 292, and gives the cftc target its number.
5. **The capacity.**
   - card-identity reads the CAPS2 word with the field;
   - device-test loads and runs an image of 32,769 instructions;
   - `cft_program_load` refuses the capacity plus one by name, which needs
     no 128 MB image: it is the header's count that is refused.
6. **Certificates.** cft-segrun certifies a miss on the streaming quad,
   and both auditors accept it.

## 9. The RTL plan's outline

**File by file.**
- `rtl/cft_ifetch.sv`, new: the store, the stream's FIFO (a `cft_fifo`),
  the read engine, the realigner, the rules of section 2, and the fault
  and idle outputs. `spos` and the store's base and end take PCW + 1
  bits (section 2, Widths).
- `rtl/cft_seq.sv`:
  - instantiate the unit in place of `imem` (:473) and its read register
    (:1820-1829);
  - the parse writes the store's first 4,096 and scans the rest
    (:3149);
  - the header check against the capacity (:3041), and the elaboration
    guards (:866-888);
  - the widths of section 2: `pc` and `skip_depth` to PCW + 1 bits (25 at
    2^24) and `lp_body` to PCW (24), with PCW now log2 of the capacity;
  - `word_ok` into the continuation (:3790), `S_FETCH2` and `S_SKIP_D`;
  - REPEAT's capture strobe (:3672-3684);
  - `S_DRAIN_SETUP` raises the quiesce (:3803), and `S_WAIT_B` waits for
    the unit's idle (:4021-4027);
  - the port's owner select beside the main read engine (:2844-2864);
  - a fetch fault ends the block.
- `rtl/cft_krnl.sv`: `SEQ_STREAM_D`; CAPS[23:20] as min(15, its log2); the
  CAPS2 field; the 32-bit `caps2`. The master steering is unchanged.
- `rtl/cft_csr.sv`: `caps2` `[31:0]`, its read, the map's comment.
- `tb/`: as section 8 (Makefile's `SIM_BENCHES` gains `seq_corestr`;
  test_seq_core.py, test_krnl.py, test_krnl_seq.py, test_krnl_faults.py,
  krnl_caps.py, probe_seq_cycles.py).
- `formal/`: ifetch.sby, tb_ifetch_formal.sv, run.sh, README.md.
- `host/src/backend_xrt.cpp`: the decode (:2264-2272). `host/include/cft.h`:
  `max_insns`'s comment. `host/tests/device_test.c`: the capacity legs.
- `python/cftc/targets.py`: the targets. `python/cftc/schedule.py` and
  `manifest.py`: the redirect term, reported only (for C4).
- `docs/`:
  - SEQUENCER.md: a revision-8 section for streaming, numbered after R8's;
    the capacity table; "The shape of a program" and "What the RTL looks
    like", whose "readable back for attestation" no RTL implements today;
    "the next instruction capacity is a CAPS change", now CAPS2's;
  - ARCHITECTURE.md's CAPS2 table;
  - HOSTAPI.md (`max_insns`, and the image read throughout the run);
  - COMPATIBILITY.md, VERIFICATION.md, CAPABILITIES.md;
  - LAYOUTS.md and SCALING.md's resources, once a build measures them.

**The order.**
1. Logan approves this design, and the round's RTL plan carries it
   beside R8F, R8L, R21 and R22.
2. The documents first: SEQUENCER.md's section, the CAPS2 field, HOSTAPI's
   sentence. The golden model and the software backend need nothing,
   because they already take any count.
3. The bench's memory: SeqRam's read latency and outstanding bursts. Then
   the unit alone, under its formal proof and `seq_corestr`, before it
   touches the kernel.
4. `cft_seq`'s hooks, `cft_krnl` and `cft_csr`. Then every bench at every
   configuration, Verilator first, and the plants.
5. An out-of-context synthesis of the streaming tile at the U50's
   capacities: the LUT delta, the block-RAM split, the fetch path's slack.
   Then the packed-URAM probe, if 8,192 is still in question.
6. The lead's long runs: Icarus `make sim`, `simmc`, lint, formal, the
   gate budget on amd-arc-box.
7. Bitstreams on amd-arc-box, one at a time, at `KERNEL_FREQ=135000000`:
   the streaming quad, then the deep build.
8. The card legs of section 8, with the acceptance set as the admission
   test.

## 10. Where R8 meets the fetch

R8's design, as its ledger records it (phase 1, committed 59b19e6 on
s6-r8, the lead's go given): control codes 12 `QUIET`, 13 `ENDQUIET` and
14 `RAISE ra`; CAPS2[13] LANE_FLAGS and [14] FLAG_CONTROL; STATUS[6] the
mark; MODE[24] for the per-lane block; and, proposed for the RTL plan,
LFLAGS_PTR at 0xB0 on the D master with VERSION 0xA00 -> 0xB00. Where it
meets the fetch:
- **CAPS2.** R21, R22, R23 and R24 hold [11] to [14]. R8's ledger leaves
  [15] free and puts this field "past it, where S8 widens the port". The
  capacity takes [20:16], and `caps2` is widened once, for both.
- **STATUS.** The mark is bit 6. The fetch's faults reuse [0] and [2], and
  need no bit of their own.
- **The new control codes** (R24's three; R21's `augadd` and `augerr`)
  reach the decoder as words, like any other.
  - R24's regions nest properly with loops, in one bracket stack the loader
    checks, and a region open at a HALT or at the end is refused. So a
    region never spans a jump.
  - The tile's quiet depth is counted at decode, in program order, which
    the fetch delivers whatever its source.
  - A skipped body holds balanced regions, so the skip's scan still counts
    only REPEAT and ENDREP.
  - An early exit cannot leave a region open.
  - RAISE goes through the issue pipe, as SETACT does. The fetch needs
    nothing for any of them.
- **R8L's per-lane block** is written in the block's drains, on the write
  master, after the fetch has quiesced. VERSION moves for R8L's register,
  not for streaming. R8 has the XRT backend map CAPS2[11..14] behind the
  VERSION that carries them, because those bits mean registers. The
  capacity means none, so its decode needs no VERSION gate: an older tile
  reads it as zero.

## 11. Weighed and not taken

- **Keep the 32K IMEM and stream past it.** It frees no block RAM, and it
  keeps the cascade in the fetch path. It is the same RTL with the store's
  depth at 32,768: a build's choice, not a design.
- **A pure stream with no store.** That means a redirect at every block
  restart, which costs a small program over many blocks 16% to 27%
  (estimate, section 4), and a redirect at every back-jump.
- **An instruction cache with tags.** It puts a tag compare in the fetch
  path, thrashes on bodies past its size, and does nothing for these
  programs that the one-range store does not.
- **A predicting fetch,** whose engine follows REPEAT and ENDREP with its
  own loop stack. It would make even a jump out of the store free, but
  every early exit and skip becomes a mispredict to unwind, with a second
  loop stack to keep in step. The store gives the same for every program
  in sight. It remains a possible later gain.
- **A fifth master** (section 1).
- **The scan's results in the header** instead of a scan. That changes the
  image format, which the plan keeps. Conservative results with no scan
  past the store (load all three streams, wipe to the dirty marks) would
  keep every answer and cost cycles every block. The scan costs about a
  millisecond a run at the largest misses (section 4).

## 12. Questions for Logan

1. **The store's depth.** Recommended: 4,096. Every program in the tree
   is within it (the largest is 2,511 instructions) and so runs exactly as
   today; a C4 routine's body fits; it frees 55 RAMB36 a tile. 2,048 frees
   59, and the two Lorenz-96 tangent programs would stream past it. 32,768
   frees none.
2. **The capacity a U50 build publishes.** Recommended: 2^24 instructions,
   a 128 MB image, half of the tile's A pseudo-channel, whose other half
   holds stream a, the bank, the scratch-in and the tables. A build
   parameter, as the other capacities are.
3. **CAPS2[20:16] as a five-bit log2,** zero meaning CAPS[23:20] is the
   capacity, and CAPS[23:20] published as min(15, ...). Recommended.
4. **A fetch fault ends the block,** where a faulted image parse is
   executed today. Recommended, so that an unvouched word never runs.
   - The fetch's engine must also end a short burst rather than wait for
     its missing beats. The sequencer has no length-fault abort today: a
     short read burst on any of its reads leaves the burst counter above
     zero (cft_seq.sv:2849-2856), so the next read is never issued and the
     run never ends.
   - That hang is pre-existing (verifier-VS8). docs/CARDDAY.md:896-903's
     "A hang should no longer be how a bus fault presents" holds for the
     elementwise engine only.
   - The streaming fetch must not inherit it. The setup reads and the
     parse keep it, unless the RTL plan gives them the engine's abort as
     well.
5. **The deep build's shape.** Recommended: the streaming quad at 4,096
   slots, after an out-of-context probe. And an out-of-context probe of
   the packed scratch before choosing between a single or dual at 8,192
   and a packed quad at 8,192.
6. **An early streaming-only probe.** The unit and its hooks synthesized
   out of context as soon as they pass their benches, before the
   revision's other RTL, to read the fetch path's slack and the LUT delta.
   Recommended. The bitstreams wait for the whole revision, as planned.
7. **schedule.py's one-beat column.** At one beat it charges one cycle for
   an independent instruction. The RTL takes about four for one that
   writes no register, and about seven for arithmetic, which is held by
   the result queue's three slots (R19 measured 7.0; section 4).
   Recommended: a bench measures it, and cftc corrects it with C4's other
   cost-model work, which already changes the committed manifests.

## 13. The fetch unit as built (parcel RD1, 2026-10-03)

Round 1, item D1, of revision 8's RTL revision (docs/ROADMAP.md,
"Revision 8: step 6's RTL revision", part 5): the unit of section 2,
alone, under its own proof. cft_seq.sv is round 2's and is untouched;
nothing instantiates the unit yet. Numbers are marked as the rest of
this study marks them. The work, every run and every measurement are
in the round's ledger (`ledger/RD1.md`).

### What is in the tree

- **rtl/cft_ifetch.sv.** The store (STORE_D, the build's SEQ_IMEM_D,
  4,096 at the U50); the stream (a cft_fifo of 2^FIFO_LOG2 = 512 words,
  filled by the unit's own read engine on master A: bursts of 8 beats,
  4 live, 8 counting abandoned ones, one ID in order, never across 4 KB
  or past n_insns, a burst issued whole and only into reserved room);
  the realigner at 4-byte granules; the rules of section 2 (hit and
  miss, where the stream stands, the redirect, the capture, the
  retarget, the quiesce, the faults). STREAM_D equal to STORE_D builds
  no stream: no FIFO, no engine, no realigner, the port tied off, idle
  high. Parameters a build sets: STORE_D and STREAM_D; the others are
  this study's figures.
- **tb/test_ifetch.py**, `make -C tb ifetch`. A cycle-level model of
  cft_seq's fetch states drives the unit and decides its control flow
  from the words it is handed; a reference walk of each program, under
  the same seeded lane decisions, must visit the same addresses with
  the same words. SeqRam (tb/test_seq_core.py) gained the read latency
  section 8 asks for - pipelined, stamped at each burst's acceptance -
  an acceptance depth, and two fault hooks; at its defaults it is the
  slave it was. Not in SIM_BENCHES yet: joining moves the bench count
  CLAUDE.md states, which is the lead's to restate.
- **formal/ifetch.sby** with tb_ifetch_formal.sv, in formal/run.sh.
- **yosys-lint** reads the unit with the kernel (unused there until
  round 2) and elaborates it alone at both builds, with a no-latch
  check.

### The interface, for round 2

The module's header has it in full; in brief, cft_seq drives:

| port | cft_seq drives or reads | when |
|---|---|---|
| `init` | 1 | S_IDLE with `start`, before the parse's first instruction |
| `cfg_ibase` | `prog_q + 32 + (bank_ext_q ? 0 : h_nconsts << esz_sh)` | stable from the parse to the run's end |
| `cfg_n` | `h_ninsns[PCW:0]` (the header check has refused more than STREAM_D) | as cfg_ibase |
| `ld`, `ld_word` | S_IMG_PARSE's instruction arm, `pw[63:0]`, in `insn_i` order | every instruction; the unit keeps the first STORE_D, and the parse still scans all of them |
| `want`, `addr` | `(S_FETCH or S_FETCH2 or S_SKIP_F or S_SKIP_D or S_ISSUE) && !take`; `pc + 1` in S_ISSUE, `pc` otherwise | every cycle |
| `word`, `ok` | `cur <= word` where today `cur <= imem_q`; the skip reads `word` | a cycle after the want |
| `take` | S_FETCH2 and S_SKIP_D when `ok`; S_ISSUE's last unheld step when it continues | only with `ok` |
| `cap`, `cap_pc` | 1 and `pc + 1` when a REPEAT enters its body (S_DECODE, the branch that pushes the loop stack) | never with want or take |
| `quiesce` | S_DRAIN_SETUP (every cycle of it is harmless) | the block's end |
| `idle` | S_WAIT_B waits for it beside the write responses; the abort waits for it before done | |
| `fault_rd`, `fault_len` | OR into STATUS[0] and STATUS[2]; their OR is the abort's fetch fault | sticky to the next init |
| `m_rd_*` | muxed with the main read engine onto cft_seq's port: the fetch's AR while it is valid, R beats to the fetch while it is not idle, `m_rd_sel` 0 while the fetch owns the port | from a block's first want until idle after it ends |

What changes in the states:
- **want is low in a take cycle.** Each of the three consuming states
  presents the consumed word's own address in the cycle it consumes,
  and asking the stream for a word again after its pop is a jump to
  it (a redirect).
- **S_FETCH2 and S_SKIP_D wait while `ok` is low**, presenting the
  address again; S_ISSUE's continuation needs `ok`. With want low in a
  take cycle, `ok` means exactly "the word presented last cycle is
  here", so `nxt_ok` is redundant beside it, and `ok` is never high for
  an address at or past n_insns, so it stands for `32'(pc) + 32'd1 <
  h_ninsns` too (section 2, optional).
- **A fault leaves `ok` low for ever**, so a consumer waiting in
  S_FETCH2 waits until the abort ends the run: the abort must watch the
  fault bits from every state.

What round 2 also owes the unit (sections 2 and 9): `pc` and
`skip_depth` at PCW+1 bits of the capacity and `lp_body` at PCW; the
header check against STREAM_D; the elaboration guards; SEQ_STREAM_D in
cft_krnl.sv with CAPS and CAPS2 from it; and the main read engine's
issue held off while the fetch is not idle - the unit issues only
between a want and the next quiesce, init or fault, so S_WAIT_B waiting
for idle is the whole of it. And the converse, which that does not
give (verifier-VRD1): the main read engine DRAINED when the fetch's span
opens. "R beats belong to the fetch exactly while it is not idle" holds
only if no main-engine beat is still to come. A setup load stops at its
last expected beat, so a burst the memory made long would leave beats
on the R channel, and the fetch would take them as its own. So: no
fetch AR until every main-engine burst has seen its RLAST, or a long
one is refused and drained to it, as the engines' length rule does.

### Where it departs from, or settles, sections 2 and 3

1. **An address at or past n_insns asks for nothing.** No redirect, and
   `ok` stays low: the unit never returns a word past n_insns (section
   2 says so) and is not disturbed by the lookahead of the last
   instruction.
2. **A retarget also needs the body's first address below n_insns.**
   Without that, a REPEAT as an image's last word - only an image that
   bypassed the loader has one - would empty a no-stream build's store,
   and the next block's pc 0 would wait for a stream that is not built.
   With it, a no-stream build never retargets.
3. **A fault on any fetch burst ends delivery**, abandoned or live: the
   memory failed on a read of the image either way, and the bench
   holds a fault on a burst a quiesce abandoned.
4. **"The unit delivers no word from that burst"** is built as: no word
   from a beat that faulted (non-OKAY, an early RLAST, or no RLAST on
   the beat ARLEN named), and no word at all once a fault is seen. An
   earlier OKAY beat of the same burst may already have been handed
   over: each beat is vouched for by its own RRESP, and holding every
   burst until its last beat would cost every stream start a burst of
   latency. The plan's "a read fault on an instruction word ends the
   run" holds: the unit raises the bit and stops, and the abort ends
   the run.
5. **The realigner holds RREADY low while it empties a beat**: four
   cycles a beat, a word a cycle, against the consumer's peak of half a
   word a cycle (section 1). Abandoned beats, and every beat once a
   fault is seen, are taken at once.
6. **The reservation is in beats**: the FIFO's count, plus a beat for a
   realigner still emptying one, plus 4 instructions for every live
   beat in flight and in the burst, never past 512 - and the burst
   issued whole or not at all, the engine's full-burst rule.
7. **The per-burst beat counter saturates.** The proof found that a
   wrapping 9-bit counter lets a burst that never ends look short, or
   right, after an init clears its first flag (below).
8. **The burst's length check is the engine's rule**, beat by beat:
   short or long is flagged on the beat that shows it, and the burst is
   drained to its RLAST.
9. **`take` reaches no block-RAM pin** (after probe S1, 2026-10-05,
   whose worst routed path, +0.452 ns at 135 MHz out of context, was
   take into the FIFO's read address, with the store's read enable
   at +0.626 ns and the FIFO's rp beside them). A stream word taken
   leaves the FIFO a cycle later (`pop_q`), so the FIFO's read address
   and rp come from a register. No consumer sees the difference: `want`
   is low in a take cycle, so `ok` is low in the next, and the stream's
   term of `ok` is held low in that cycle anyway, for a consumer that
   wanted and took at once - which then waits a cycle rather than seeing
   the taken word again. The FIFO's count is one high in that cycle,
   which only makes the reservation more cautious. Its write enable is
   the realigner's word alone (a word written as a redirect clears the
   FIFO is cleared with it), the store reads every cycle (st_q is used
   only the cycle after a wanted one), and the launch selects the read
   engine's next address and beats left instead of gating its adders'
   operand (S1: launch through rd_ba's eight carry levels, +1.148 ns).
   Section 13's earlier note expected a skid register at a cycle of
   latency; the consumer's own spacing makes it free. The streaming
   cycle rows and the fetch's bench run in exactly the cycles they did.

### The proof

Every task is unbounded: k-induction proving all of a task's assertions
together, its claims and the helper invariants that make them
inductive, each of which is proven, not assumed. Two configurations
share the image format's byte geometry, 13-bit addresses and two-bit
granules: the default sizes - a 16-instruction capacity, a 4-word
store, an 8-word FIFO, bursts of 2 (2 live, 4 in all), as section 8
planned - and the wide sizes, added after verifier-VRD1 (below): the
FIFO at 32 words, four bursts, with LIVE_MAX at 2 below the four it
could take, and a 64-instruction capacity (measured, the cft-formal
image, one task at a time, 4 CPUs, the desktop at 0 to 26%; time is
sby's elapsed clock):

| task | sizes | the memory | proves | depth | time | checks |
|---|---|---|---|---|---|---|
| prove | default | free timing, RLAST, RRESP | never past n_insns or after a fault; faults raised by bad beats and only by them; every AR aligned, at most BURST beats, inside a 4 KB page and the section, held until taken; at most OUT_MAX outstanding; idle truthful; silence after a quiesce, init or fault; cft_fifo's caller contract; the three shapes below never reached | 3 | under 1 s | 30 (31 with departure 9's helper) |
| data_prove | default | honest, free timing | every word `ok` presents is the image's word at the address presented; a stream word is handed over two or more cycles after its beat lands | 3 | 8 s | 57 |
| deliver_prove | default | honest, prompt | a consumer waiting on one address is answered within 18 cycles | 19 | 181 s | 54 |
| ends_prove | default | prompt, faults free | idle within 14 cycles of a quiesce, an init or a fault | 15 | 3 s | 31 |
| cover | default | free | 14 shapes reached, at steps 3 to 14 - among them a stream word handed over exactly two cycles after its beat landed | 40 | 6 s | 14 |
| wide_prove | wide | free timing, RLAST, RRESP | prove's claims and helpers | 3 | under 1 s | 27 |
| wide_data_prove | wide | honest, free timing | data_prove's claims and helpers | 3 | 39 s | 54 |
| wide_cover | wide | free | the three shapes reached (steps 5 to 7), and the 32-word FIFO full (step 38) | 44 | 89 s | 4 |

**Why two sizes.** At the default sizes the FIFO holds exactly one
burst, so three shapes of the reservation cannot occur there: a whole
burst launching while the unit is not empty, more than BURST beats
owed to live bursts, and the launch's `live_n < LIVE_MAX` term deciding
anything. All three happen at the U50's sizes. verifier-VRD1 found them
missing. The default-size tasks now assert the three unreachable; at
the wide sizes all three occur, the claims are proven, and VRD1's plant
v13 is red (the plants, below). The bounded claims run at the default
sizes only. The three are the shapes found missing, not a proof that no
other is: tb/test_ifetch.py runs the unit at the U50's stream sizes and
is the net for any shape neither configuration reaches. Section 8
planned the default sizes alone; the wide ones are an addition.

data_prove's honest memory is enough because a word reaches `ok` at
least two cycles after its beat lands (`a_lat`, in data_prove; the
cover task reaches exactly two), a bad beat raises its bit the next
cycle, and `ok` is never high with a bit raised (both in prove). Up to
its bad beat a faulting memory's run is an honest one's, the word shown
in that beat's own cycle is from older beats, and from the next cycle
`ok` is low until an init drops everything. pdr, the FIFO proof's
engine, proved most control claims alone
in seconds but not three of them nor the data claim (measured; formal/
README.md has the figures), and on the way it found a real hole: the
beat counter of departure 7, at step 518. The invariants k-induction
needed were read off its counterexamples; none was a defect in the RTL.

Departure 9's late pop (2026-10-05) moved four of the helpers, by a
probe of `pop_q`. While it stands the FIFO holds one word more than the
stream, its head the taken word, so `d_fifo`, `d_pos` and the latency
helper read the stream's count, the FIFO's less the pending pop, and its
head a slot on from rp. One helper is new, `h_popq`: a pending pop's
word is still in the FIFO, of a stream that is on. Every task passed
again on the cft-formal image (measured, one task at a time, 4 CPUs):
prove 1 s (31 checks), data_prove 9 s (58), deliver_prove 174 s (55),
ends_prove 4 s (32), cover 8 s (14), wide_prove 4 s (28),
wide_data_prove 41 s (55), wide_cover 88 s (4), and fifo.sby's prove
and cover, cft_fifo unchanged. Removing `ok`'s guard on the pending pop
refutes data_prove's `a_word` (measured, a copy of the tree).

### The bench

13 cases, each at SeqRam read latencies 0, 125 and 256 - the
abandoned-burst case at 125 and 256 only: it plants its fault on a
burst the block's halt must find still in flight, which a memory
answering at once does not leave - with a 64-word store and a
4,096-word capacity: 13/13 under Verilator (57 s wall) and under Icarus
(69 s wall), the desktop idle (measured). What it measured, in the
model:
- **A program the store holds** reads nothing and never waits, at every
  latency: every cycle is today's.
- **A body that starts in the store and runs past it** (200
  instructions from pc 5) and **a body past the store longer than it**
  (200 past a 64-word store) wait no cycle at 125 or 256: the store's
  words cover the refill. Each back-jump into the store redirects once
  (counted: one burst at the store's end a pass).
- **A body past the store that fits it** is captured: the block's
  bursts are exactly one sequential stream. The next block's restart at
  pc 0, after the store moved, waits one round trip: latency plus about
  5 cycles. So does each enclosing back-jump that misses, nesting four
  deep.
- **The skip at a 256-cycle round trip** (a word every two cycles, the
  fastest consumer) waits 1,101 cycles over a 4,093-word scan, about
  13%; at 125, one cycle. Four bursts of eight in flight is section 1's
  sizing for half a word a cycle at 256, and the unit's own few cycles a
  round trip take it just past the edge. The card's bound is 144.
- **The quiesce:** a block that halts while the stream prefetches is
  idle 32, 129 and 258 cycles after its end at latencies 0, 125 and 256
  - the round trip of what was in flight - and no AR begins until the
  next block's first request.

### The plants

S8's nine (section 8), each in a fresh copy of commit d0c3fdf, each
red by name in the bench and in the proof (measured). Plants 6 to 9
name mechanisms that live partly in cft_seq.sv and cft_krnl.sv, round
2's files; each is planted as the unit's own share of the mechanism,
and round 2 plants the rest. "The claims alone" is a bounded check
from reset of the proof's claims with its helpers switched off
(`HELPERS = 0`), which names the claim a plant breaks; the gate's own
tasks name the helper it breaks first, or prove nothing (a helper no
longer inductive), and every plant fails at least one of them.

| plant | as planted in the unit | the bench | the claims alone |
|---|---|---|---|
| 1. the store's range one past its end | the hit test reads `addr <= send` | 8 of the 12 cases the bench then had red: "the unit handed ... for address 64, whose word is ... - a word the memory did not deliver there" | `a_word` (data_prove's own basecase too) |
| 2. a redirect that keeps the FIFO's words | the FIFO's clear is the quiesce's and the init's alone | 3 cases red, the body past the store, the body larger than the store, nesting: wrong words after a back-jump | `a_word`, step 7 |
| 3. abandoned bursts' beats not dropped | no burst is ever treated as abandoned | nesting four deep, in its first run - latency 0, 4,574 ns into the test: a wrong word at address 98 | `a_word`, step 7 |
| 4. the realigner one granule off in the 4-byte case | every granule offset read as even | every_granule_offset and section_across_4k: wrong words at the odd offsets | `a_word`, step 7 |
| 5. a retarget that keeps the old count | the retarget moves the range and keeps its count | 5 cases red: stale store words read as hits | `a_word`, step 4 |
| 6. no quiesce | the stream stops only at an init | quiesce_stops_the_stream: "an AR ... began while the fetch was quiesced". The first bench had no case for it - its one early halt also planted a fault, which stopped the stream first - and the case was written for this plant | `a_quiet`, step 4 |
| 7. a faulted word executed | `ok` not held low by the fault bits, and the realigner takes bad beats | the three fault cases: "ok high after a fault" | `a_fault_ends`, step 6 |
| 8. CAPS2 from the store's depth instead of the capacity | the unit built as if its capacity were the store's depth: no stream | a hang: "a block did not end within 77,440 cycles (state FETCH2, pc 64)" | `a_delivers`, step 20; the gate's tasks cannot attach their probes, there being no stream |
| 9. `pc` one bit short | the address the consumer presents read one bit short | only program_of_exactly_the_capacity, the implicit halt's image: "a word for address 4096, at or past n_insns = 4096" | `a_past_n`, step 3 |

The claims alone on the unit as built: the control claims pass to
depth 30 (341 s), the data claim through depth 14 before its steps
outgrow a short run (measured).

verifier-VRD1 planted a tenth, v13: the launch's `live_n < LIVE_MAX`
term removed. The bench catches it - the U50's 6-bit `live_b` wraps at
64, and a wrong word is handed over at address 453 at latency 0 - and
the proof's default sizes did not, because a one-burst FIFO never lets
the term decide. That is what the proof's wide sizes are for (above).
There the gate's `wide_prove` fails on `h_live`, a bounded check from
reset refutes `h_live` at step 8, and a directed search finds the FIFO
written while full - `a_fifo_full` broken - at step 43 (measured;
formal/README.md has the runs).

### Left for round 2 and for probe S

- cft_seq's hooks, as the interface above says, then the bench
  configuration `seq_corestr` (section 8) through the whole sequencer.
  Done in round 2: the hooks at cbce00a, and `seq_corestr` in `make sim`
  from the same commit. Two targets since 2026-10-05. Under Icarus the
  whole bench at three latencies could not finish inside its target's
  four hours: 35 of 94 cases in 3 h 02 min on amd-arc-box at six jobs
  (the lead's run at 2b84449). So S8's configuration whole is
  `seq_corestr_full`, in `make simmc` under Verilator, and `seq_corestr`,
  in `make sim`, runs the cases written for the fetch and
  `the_whole_divide_and_root` at a 4,096-word capacity (tb/Makefile).
  Section 8's "nearly every program then streams" was not so. Counted
  without a simulator (`tb/stream_census.py`: the bench's own programs,
  cocotb stubbed, each counted where the Bench budgets it; measured at
  S8's build on the split's tree), 13 of the bench's 98 cases run a
  program longer than the 64-word store, 66 runs of the 1,575 counted.
  Twenty cases stop early there, at their first check of a cycle count
  or a planted fault, so only their first runs are counted; none is
  longer than 11 instructions, but for the fetch's own, which stream.
  The other case that streams is `the_whole_divide_and_root`: twelve
  runs of up to 214 instructions.
- Probe S: whether Vivado keeps the store cascade-free
  (`cascade_height` pins it if not); the path from `take` - late, out
  of the admission - into the FIFO's read address (`rp + rd_en` into
  the block RAM), which a skid register would cut at a cycle of
  latency; the unit's LUTs and registers. Probe S1 (2026-10-05, the
  lead's, on amd-arc-box): the store was cascaded (now pinned), and the
  take path was the kernel's worst routed path, +0.452 ns - now
  departure 9, at no cycle of latency, for probe S3 to read. And two paths where the unit
  as built is not what section 5 expected (verifier-VRD1):
  - the redirect is combinational from `addr` through the range compare
    (25 bits at the U50) and the stand compare against `spos` into the
    FIFO's synchronous clear and the stream's next state, where section
    5 expected the logic registered. Registering it is a design change:
    the answer takes the FIFO's head with no address compare because
    the flush lands in the request's own edge;
  - `word` passes two 2:1 selects, not one: cft_fifo's own head bypass
    (its bypass register or its RAM's read register), then the store's
    read register or that head. Both inputs are registers either way.
- The bench joining SIM_BENCHES, with CLAUDE.md's count. Done in round
  2: `seq_corestr` joined at cbce00a, and CLAUDE.md's count was restated
  at the merge of round 1's lanes into round 2 (fba8f4c).

## Sources and measurements

- **Read, in the tree at 1acc73a:**
  - rtl/cft_seq.sv, rtl/cft_krnl.sv, rtl/cft_csr.sv, hw/link.cfg,
    hw/link_quad.cfg;
  - host/src/backend_xrt.cpp, host/src/program.c, host/include/cft.h;
  - python/cftc/targets.py, schedule.py, emit.py;
    python/cft_golden/seq.py and cert.py;
  - tb/test_seq_core.py and tb/Makefile;
  - formal/README.md;
  - docs/SEQUENCER.md, docs/ROADMAP.md, docs/VALIDATION.md and
    docs/BITSTREAM-BUILDS.md, at the places cited.
- **Read, outside the tree:**
  - q135b's routed utilization reports, impl_1_full_util_routed.rpt and
    impl_1_slr_util_routed.rpt (Vivado 2022.2, 2026-09-30), copied in
    `Data/runs/2026-10-02-step6-round/box/q135b-utilization/`;
  - the hard workloads' card results, `results.json` (2026-10-01);
  - the step-6 survey's part T;
  - the revision-7 round's ledger (OOC figures), the audit round's ledger
    (q135's paths) and R8's ledger (CAPS2, STATUS).
- **Measured for this study** (scratch scripts, niced, one at a time, the
  ledger has them):
  - **The tree's 73 program files:** every tracked `.cfta` (50, assembled
    in memory by asm.py) and `.cftp` (23), in programs/, certificates/
    and host/tests/. The largest is 2,511 instructions (the Lorenz-96
    tangent programs, as source and image); all are within 4,096, 69
    within 2,048 and 59 within 512. Every loop's body starts at pc 7 or
    earlier, nested one deep. Two instruction sections are 4-byte aligned:
    normalabs-fp32 (byte 52) and sqrt-fp32 (byte 68). The divide and root
    programs are 43 to 60 instructions.
  - **Six hard workloads compiled by cftc** (8 to 112 s each): FPUT, phi4,
    Kuramoto-Sivashinsky, reservoir and Riccati hard for `u50-rev7-quad`,
    and Gray-Scott hard for `sw:2048`. Each is `repeat 512` at pc 0, its
    body from pc 1, then `endrep` and `halt`, with no prologue: none of
    them pins a value. Their cost-model cycles are in section 4's tables.
  - **Every tracked file's prologue,** the words before its first REPEAT
    (after verifier-VS8). The ten cftc reference images open with 0, 3, 4
    or 6 loads and nothing else, so their bodies start at pc 1, 4, 5 or 7.
    The largest prologue of the 73 files is 6. No first body starts past
    pc 7.
- **Computed:**
  - a cftc prologue's bound, 25 loads, so a body by pc 26, from
    regalloc.py's pinning rule;
  - the widths, from cft_seq.sv's own rule for `pc`;
  - the round-trip bound, 144 cycles;
  - the bandwidth table;
  - the block-RAM and UltraRAM geometry;
  - the redirect's share of a step.
- **Estimates, each said where it is used:**
  - the redirect's 32-beat and 4-cycle parts;
  - the LUTs;
  - the misses' card steps;
  - the quad's projected utilization;
  - the cost of a pure stream to small programs.
