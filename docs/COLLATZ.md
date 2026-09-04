# The Collatz explorer

`host/tools/collatz.c`, built by `make -C host collatz`, iterates

    n  ->  n / 2      when n is even
    n  ->  3n + 1     when n is odd

from a starting value until it reaches 1, and reports the stopping
time and the peak. `host/tests/collatz_check.py` scores it against a
Python big-integer oracle; `make -C host collatztest` runs that.

It is a toy. It is here because it is a benchmark designed FOR this
contract rather than adapted to it, and because it says three things
that are hard to say with a microbenchmark:

1. **Exactness is a result, not a hope.** Below 2^237 the binary256
   values *are* the integers, so a stopping time this prints is a
   theorem. Above it, the library raises `inexact`, and the tool stops
   trusting that element and says where.
2. **The whole iteration fits the orbit sequencer.** Nineteen
   instructions, nine constants, one `REPEAT`, two `SETACT`s and four
   `DEPOSIT`s - the second real customer for `docs/SEQUENCER.md`'s
   design after `cft_div`, and the first one that is not the library
   accelerating itself.
3. **Determinism is checkable end to end.** A range, a batch size and
   an engine go in; a hash chain comes out, and it does not depend on
   the batch size, on the engine, on the format (where the format is
   wide enough), or on whether the run was interrupted.

---

## The exactness argument

### Why every operation is exact below 2^p

binary256 has p = 237 significand bits, so **every integer in
[0, 2^237] is exactly representable** and no integer in
(2^237, 2^238) is unless it is even. The tool does not take p from a
table: it measures it, by asking the library for the smallest k such
that `2^k + 1` raises `inexact`. The same code therefore runs at
p = 24, 53, 113 and 237 with no format-specific constant anywhere, and
the bias it needs for the parity test follows from p and the format
width.

The iteration uses exactly three arithmetic operations:

| step | operation | why it is exact |
|---|---|---|
| halving | `q = n * 0.5` (`CFT_MUL`) | multiplying by a power of two only decrements the exponent. n >= 1 always, so there is no subnormal edge and no underflow. Exact for **every** n, at every magnitude. |
| tripling | `y = fma(n, 3, 1)` (`CFT_FMA`) | one fused multiply-add, so the exact value 3n+1 is rounded **once** or not at all. Exact iff 3n+1 fits p significant bits. |
| counting | `cnt = cnt + 1` (`CFT_ADD`) | exact while the stopping time is below 2^p, which it is by a margin of about 2^220. |

Everything else in the step - the comparisons, the conditional move,
the min, the max and the five integer opcodes - performs no rounding
at all and can raise no flag. **So the only operation in the whole
tool that can raise `inexact` is the tripling FMA**, and only when
3n+1 does not fit.

That is worth stating precisely, because it is what makes the flag
usable as a detector rather than as a smell:

> Over any call, `flags & CFT_FLAG_INEXACT` is set **if and only if**
> at least one live element's `3n+1` was not representable.

### The two edges that are easy to get wrong

**"Above 2^p everything has left exactness" is false.** For odd n,
3n+1 is even, and an even integer one bit wider than the format still
fits. A trajectory routinely climbs past 2^p, halves back down, and
every step of it is exact. Testing `value > 2^p` as the escape
condition would abandon a correct proof, and would have mis-classified
all 9,999 starting values below 10,000 at binary32, where not one of
them escapes even though many peak above 2^24. The first starting
value that actually escapes at p = 24 is **26623**.

**Above 2^p every representable value is even**, because ulp is at
least 2. The parity test below has to say so explicitly; without it a
value above 2^p reads as odd, takes a tripling that cannot be exact,
and the trajectory is abandoned several steps too early. This was a real
bug in the first version of the tool, caught by the boundary set in
the cross-check: 2^237 - 3 stopped after 1 exact step where it should
manage 8.

### The per-element witness

`cft_run` and `cft_program_run` report the **union** of the exception
flags over a whole call, which is what 754 asks for and what
`docs/HOSTAPI.md` documents. It is also not enough on its own: a
verification needs to know *which* element left exact arithmetic and
*at which step*, and a union over 4,096 elements and 1,024 iterations
cannot say.

So each step computes a per-element witness with one extra FMA:

    y   = fma(n,  3, 1)        the step
    res = fma(n, -3, y)        the residual, y - 3n
    exact  <=>  res == 1

`res` is the integer `1 + (y - (3n+1))`, and the rounding error
`y - (3n+1)` is at most `ulp(y)/2` in magnitude, so `|res| <= 1 +
ulp(y)/2`. For every `y` below 2^(2p-2) that is representable, the
second FMA therefore rounds nothing, raises nothing, and returns the
residual exactly. `res == 1` is then a *decision*, per element, about
whether the first FMA was exact.

The witness has a domain, so the tool checks it: after every call it
verifies that no element's peak has reached 2^(2p-4), and stops with an
error if one has. Reaching that at binary256 would take about 230
consecutive lucky alignments above 2^237; the check costs one
comparison per element per call and turns an argument into a gate.

**The tool asserts the biconditional on every single call.** If the
flag is raised and no witness failed, or a witness failed and the flag
is clear, it prints what disagreed and exits 3. That assertion is the
reason the flag is load-bearing here rather than decorative, and it is
what the negative control below breaks. It is checked per call over
the union, which makes it necessary and not sufficient - see control B.

Beside it, the tool uses ABI 0.7's status word (754-2019 7.1) as a
second, free cross-check. Measuring p deliberately raises `inexact`;
the tool lowers the word once with `cft_lower_flags` when setup is
done - 7.1's "lowered only at the user's request" - and never touches
it again. The report prints the word beside the union of the calls'
`flags_out`, and they must agree, because nothing else in the tool
rounds anything:

```
  flags seen    0x10
  status word   0x10 (agrees with the union above)
```

### What the tool does with an element that leaves exactness

The step order is deliberate:

    ...compute y and the witness...
    SETACT ex          <- an element whose step was inexact drops out HERE
    n    = odd ? y : q <- masked, so it keeps its last EXACT value
    cnt  = cnt + 1     <- masked, so it counts only exact steps
    peak = max(peak, n)

so an element that leaves exactness keeps the last value it provably
held, the count of steps that were provably exact, and the largest
value it provably reached. It is recorded as `esc`, it is never
counted as verified, and its stopping time is never reported as a
stopping time. What it contributes to the run's statistics is its
peak, which is an exactly computed number whatever happened next.

---

## Parity, and the three ways to get it

Parity is the only part of the iteration that is not obviously an
opcode. Three routes were considered and two rejected:

| route | correct? | why not |
|---|---|---|
| `q = n*0.5`; floor by the magic constant `(q + 2^(p-1)) - 2^(p-1)`; `even <=> q == floor(q)` | yes | **raises `inexact` on every odd element**, because q is then a half-integer and the sum is not representable. It would flood the very flag the tool uses as its detector, and no amount of flag saving and restoring recovers a per-element answer. |
| `cft_rint(exact = 0)`, which never signals | yes | it is a **composed** operation - a host-side sequence around `cft_run`, per `docs/HOSTAPI.md` - and composed operations are not in the sequencer's opcode set. A step built on it could never become an on-chip program. This is the precise obstacle, and it is the only one this workload met. |
| the integer opcodes on the encoding | yes | chosen |

For a positive floating-point integer `n = 2^E * (1 + f)` the
coefficient of 2^0 in the significand is fraction bit `(p-1-E)`, so

    odd(n)  <=>  ( bits(n) >> ((p-1) + bias - biased_exp(n)) ) & 1

and the shift amount is computed from `n`'s own encoding by `ISHR` and
`ISUB`. Five quiet integer opcodes, no rounding, no flags, all of them
in the sequencer's set.

Two edges make this right rather than lucky:

- **E = 0.** The shift is `p-1`, which reaches the low bit of the
  biased exponent field. That bit is the low bit of the bias, and
  every IEEE binary bias is `2^(w-1) - 1`, which is odd. The only
  integer with E = 0 is 1, and 1 is odd. The two agree.
- **E > p-1.** The shift would go negative and wrap. Two more opcodes
  (`CMPLT` against 2^p, then `MIN`) force the answer to "even", which
  is what every representable value at or above 2^p is.

---

## The step, instruction by instruction

The program is what `build_program()` emits; this is its body, one
Collatz step per iteration. `r0..r2` arrive from the `a`, `b` and `c`
streams as `cft_program_run` defines, and `r3..r15` start at +0.

```
  REPEAT  K                          ; K = --steps-per-call

  CMPLT   r9  <- 1 < r0              ; not finished?
  SETACT  r9                         ;   an element at 1 drops out here
  MUL     r3  <- r0 * 0.5            ; q, exact
  ISHR    r4  <- r0 >> (p-1)         ; the biased exponent
  ISUB    r4  <- ((p-1)+bias) - r4   ; the shift, (p-1) - E
  ISHR    r4  <- r0 >> r4
  IAND    r4  <- r4 & 1              ; the units bit of the significand
  ICMPLT  r5  <- 0 <u r4             ; odd?
  CMPLT   r4  <- r0 < 2^p            ; ...and below 2^p, or it is even
  MIN     r5  <- r5 min r4
  SELECT  r6  <- odd ? r0 : 1.0      ; neutralise the odd branch
  FMA     r7  <- r6*3 + 1            ; the ONLY op that can round
  FMA     r8  <- r6*(-3) + r7        ; the residual
  CMPEQ   r8  <- r8 == 1.0           ; the witness
  SELECT  r10 <- exact ? 0.0 : 1.0   ; the escape flag
  SETACT  r8                         ;   an inexact element drops out here
  SELECT  r0 <- odd ? r7 : r3        ; commit
  ADD     r1 <- r1 + 1.0
  MAX     r2 <- r2 max r0

  ENDREP
  ACTALL
  DEPOSIT r0                         ; final n
  DEPOSIT r1                         ; stopping time
  DEPOSIT r2                         ; peak
  DEPOSIT r10                        ; escaped?
  HALT
```

Nineteen instructions in the loop body, twenty-seven in the image, six
format-width constants and three integer bit patterns, `max_deposits`
= 4 - a program image of 536 bytes at binary256. The loader's rules
are all satisfied without effort: `ACTALL` and `HALT` are at the top
level, the loop is balanced, every field an instruction does not read
is zero, and the worst-case instruction count is `20K + 7`, far below
2^40 for any usable K.

**The `SELECT` on line 11 is not decoration.** Without it the tripling
would be computed for every element including the even ones, and an
even element near 2^p would raise `inexact` for a branch it never
takes - which would break the biconditional above and cost about 1.6
bits of the exactness range for no reason.

### Why this runs as a program rather than as a host loop

Every one of those nineteen instructions is an elementwise opcode the
sequencer already carries, so the whole thing fits with no additions -
which is the same claim `docs/SEQUENCER.md` makes for `cft_div`,
tested here on a workload the ISA was not designed around. What the
sequencer contributes is not just fewer round trips:

- **Convergence masking is free.** `SETACT` narrows the active set; an
  inactive lane writes nothing, deposits nothing and - the part that
  matters here - **raises no flag**. The host loop has to buy that
  behaviour: the program's two `SETACT`s become six masking opcodes in
  the host loop - `MIN` the live mask into the parity so a finished
  element cannot reach the tripling with its own value, then `SELECT`
  the commit of n, the step count and the escape flag through it. That
  is the 19-versus-23 difference between the two engines, and it is
  there because a finished element that kept feeding the tripling
  would push `inexact` into the run for ever.
- **The early exit is exactly this workload's shape.** Stopping times
  vary from 0 to several hundred inside one batch, and P3 says the
  early exit changes how long the run takes and nothing else.
- **Deposition is what the results are.** Four values per lane,
  addressed by element index, is precisely `DEPOSIT`'s job, and it is
  what lets the host resume a batch: the deposits of one call are the
  `a`, `b`, `c` streams of the next.

`--engine loop` issues the same step as twenty-three `cft_run` passes
per iteration and exists to be compared against. The two must agree
bit for bit, and the cross-check holds them to that over every
starting value it tries, in both directions of the exactness
boundary. It is also what a device without `MODE[15]` would run.

**One thing the program model could not do**, recorded because it is
the kind of observation the sequencer's designers can act on: a
program has three input streams (`a`, `b`, `c` into `r0`, `r1`, `r2`)
and no way to initialise any other register. This workload needs four
pieces of per-element state to resume mid-trajectory - n, the step
count, the peak, and whether it escaped - and it only fits because the
fourth is an output that always starts at +0. A workload needing four
*inputs* would have to split into two programs or pack two values into
one element. A fourth stream, or a "load `r3..` from the deposit
buffer" mode, would remove that.

**And one thing that would remove the witness entirely**: an optional
per-element flag output on `cft_run` and `cft_program_run`. The union
is the right default and the right 754 answer, but a per-element
byte - one bit per exception - would let a caller attribute a flag
without recomputing the operation, and the extra FMA in the loop above
is the price of not having it. It would cost bandwidth, which is
exactly why it should be optional, and it is not proposed as a change
to the ABI here.

---

## The checkpoint format

A line-oriented ASCII file with LF endings, written to `<path>.tmp`,
flushed, closed and then **renamed over** the target
(`MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` on Windows, `rename()`
elsewhere), so a reader never sees a half-written one.

It carries every number that describes a **result** and nothing that
describes the **machine**. That is the whole design rule, and it is
what lets two runs with different batch sizes, different trip counts
and different engines end on byte-identical files.

```
cft-collatz-checkpoint 1
format fp256                  the format the run is in
mode sweep
lo 1                          the range, as decimal integers
hi 1000001                    or "-" for an unbounded sweep
cursor 466945                 the next starting value not yet begun
resolved 466944
verified 466944
escaped 0
steps 57664685                total exact Collatz steps performed
maxsteps 448 410011           longest stopping time, and its n
maxpeak 24648077896 270271    largest exact peak, and its n
firstescape - -               the first n to leave exactness, and where
chain 490af274...             SHA-256 chain over the records so far
batchrecords 8192             the batch in progress
done 12 9 16 1 ok             ...one line per element of it, either a
pending                       ...finished record or a placeholder
inflight 37                   elements still running
run 466900 91 12 8734 4231    ...start, n, steps, peak, record slot
end
```

Values are decimal integers throughout, produced by
`cft_to_decimal_char` with `digits = 0` - 5.12.2's exact conversion -
and read back by `cft_from_decimal_char`, which refuses anything the
format cannot hold exactly. What the library writes, the library reads
back, so a checkpoint round trip cannot lose a bit.

The **hash chain** is

    chain_0     = 32 zero bytes
    chain_(i+1) = SHA-256( chain_i || record_i || "\n" )

over records in **starting-value order**, not completion order, where
a record is

    <n0> <steps> <peak> <final> ok|esc

Order is what makes it batch-size independent: elements finish in
whatever order their trajectories allow, so a chain over completion
order would be a chain over the schedule. `--records PATH` writes
exactly those lines, so the chain can be recomputed by anything. That
file is truncated at the start of each run and is not resume-aware -
the checkpoint's chain is the thing that spans an interruption.

A checkpoint is complete state, so a run killed outright resumes from
the last one and re-does at most one `--checkpoint-interval` of work,
landing on the same final chain. What the cross-check exercises is a
clean stop at an arbitrary pass, which leaves exactly the file an
interval-triggered write would have left at that moment.

SHA-256's eight initial words and sixty-four round constants are
**derived** in the tool from the square and cube roots of the first 64
primes, by integer binary search in 128-bit arithmetic, rather than
typed in - this repository's standing rule about constants. The
cross-check recomputes the chain with Python's `hashlib`, which is
what proves the derivation right.

---

## Determinism, and how it is tested

The claim in the tool's header is:

> The same starting range produces bit-identical results and a
> bit-identical checkpoint whatever the batch size, the engine, the
> host or the backend.

It rests on the same three things the sequencer's contract does. No
reduction crosses elements; a deposit's address derives from the
element index alone (P2), so where a lane sits in the array cannot
change what it computes; and the early exit changes only how long a
run takes (P3). The host is allowed to compact the live set after
every call for exactly that reason, and does.

`host/tests/collatz_check.py` tests it rather than asserting it:

| property | how |
|---|---|
| results | every record against a Python big-integer oracle that models the stopping rule exactly - including *which* step exactness ran out on - at fp256, fp64 and fp32, over ordinary starts and over starts sitting on the boundary |
| engines | the sequencer program and the host `cft_run` loop must produce byte-identical records, and must land on the same checkpoint |
| formats | where a trajectory stays inside binary64's exact range, fp64, fp128 and fp256 must produce identical records - and they produce identical **chains**, which is the ladder's one contract seen from the outside |
| batch size | 64, 1000 and 4096 over the same range must end on byte-identical checkpoints |
| interruption | a run stopped every few passes and resumed, at a *different* batch size and trip count, must end on the same checkpoint - byte for byte - as one that was never stopped |
| the chain | recomputed with `hashlib` |
| refusals | a starting value the format cannot hold exactly is refused, not rounded |

The interrupt test deliberately uses `--steps-per-call 7` so that a
stop lands in the *middle* of a batch, with elements part way through
their trajectories: a resume that only ever restarted on a batch
boundary would be testing the cursor and nothing else. The run it
reports checks that most of its interruptions did catch live elements.

---

## Measured throughput

Software backend, single thread, on DESKTOP-T33SK86 (Windows 11,
MINGW64, `gcc -O2`), 2026-09-04. The command for one row is

```
./cft-collatz --format fp256 --engine program --batch 4096 \
              --from 1 --to 100001 --csv
```

with `--format` and `--engine` varied. Every row covers the same
10,753,840 Collatz steps except where noted.

| format | engine | batch | steps/s | elements/s | seconds |
|---|---|---|---|---|---|
| fp256 | program | 4096 | 587,571 | 5,464 | 18.30 |
| fp256 | loop | 4096 | 277,210 | 3,022 | 6.62 (20,000 starts) |
| fp128 | program | 4096 | 779,357 | 7,247 | 13.80 |
| fp128 | loop | 4096 | 418,520 | 4,562 | 4.38 (20,000 starts) |
| fp64 | program | 4096 | 886,386 | 8,243 | 12.13 |
| fp64 | loop | 4096 | 585,119 | 5,441 | 18.38 |
| fp32 | program | 4096 | 878,145 | 8,178 | 12.23 |

Three things in that table are worth more than the numbers:

- **The sequencer route is 1.5x to 2.1x faster than the host loop on
  the software backend**, where there is no bus and no round trip to
  save. What it saves is the per-call dispatch, the format steering
  and the buffer walk that `cft_run` performs 23 times per step; the
  program does the same arithmetic inside one call. On a device the
  gap is the memory system's, and much larger.
- **fp256 is only 1.5x slower than fp64 here.** The per-element cost
  on the software backend is dominated by softfloat's bookkeeping
  rather than by significand width, which is the same shape
  `docs/BENCHMARKS.md` reports for the elementwise operations.
- **Throughput is flat in the batch size and the trip count.** Batches
  of 256 to 16,384 and trip counts of 128 to 8,192 all land between
  565,000 and 600,000 steps/s at fp256 - the per-call overhead has
  already been engineered away by the sequencer, which is what the
  design said it would do.

The 100,000-value sweep finds a longest stopping time of **350 steps
at n = 77031** and a largest exact peak of **1,570,824,736 at
n = 77671**, both of which are the published values, and the fp256,
fp128 and fp64 runs return the **same chain**,
`cca55ca957433144ebed4047a2beba65d6d53d125c64b70813ba4b37e287f7ae`.
binary32 does not: 87 of those 100,000 starting values leave exact
arithmetic at p = 24, and the tool says so instead of returning a
number that looks the same.

### The sweep that was run

```
./cft-collatz --format fp256 --engine program --batch 8192 \
              --from 1 --to 1000001 --checkpoint run.ckpt \
              --checkpoint-interval 30
```

230.703 s, 2026-09-04, same host:

| | |
|---|---|
| resolved | 1,000,000 starting values |
| verified | 1,000,000 - every operation exact |
| left exact arithmetic | 0 |
| longest stopping time | **524 steps, at n = 837799** |
| largest exact peak | **56,991,483,520, at n = 704511** |
| Collatz steps | 131,434,424 |
| library calls | 123 |
| flags seen | 0x00 |
| throughput | 569,713 steps/s, 4,334.6 elements/s |
| chain | `966d0d7d23e92751490063609810b55577611e01e14da54822a3993e5db6e08f` |

Both extremes are the published values for that range. **123 library
calls for a million trajectories** is the sequencer's contribution
stated as a number: 131 million Collatz steps, and the host got
involved 123 times.

### Deep mode: as far as exactness allows

`--mode deep` takes a named set of starting values (or a range) and
follows each as far as every operation stays exact. Two values just
below 2^237 make the point:

```
./cft-collatz --mode deep --batch 8 --values \
  220855883097298041197912187592864814478435487109452369765200775161576157,\
  220855883097298041197912187592864814478435487109452369765200775161577469
```

```
220855883097298041197912187592864814478435487109452369765200775161576157
    2437 steps  peak 662567649291894123593736562778594443435306461328357109295602325484728472
220855883097298041197912187592864814478435487109452369765200775161577469
       8 steps  peak 662567649291894123593736562778594443435306461328357109295602325484732408
                                                LEFT EXACT ARITHMETIC
```

The first is **2^237 - 1315**, a 72-digit starting value whose entire
trajectory - 2,437 steps, over a peak of 6.6e71, which is above
2^238 - is computed without a single rounding. Its stopping time is a
theorem, from a start 2^173 times beyond what an int64 can hold and
2^184 beyond binary64's exact range. It is in the cross-check's
boundary set for that reason.

The second is 2^237 - 3, which manages eight exact steps and then
meets a `3n+1` that binary256 cannot hold. The tool says so, stops the
element, keeps the last value it provably held, and never counts it as
verified. `flags seen 0x10` on that run is `CFT_FLAG_INEXACT`, and it
is there because exactly one element needed it to be.

Deep mode does not checkpoint; the resumable cursor is the sweep's.

### What a device run would change

The same binary, given an `--artifact` path, opens the tile instead of
the software backend and issues the identical program. What changes:

- **Not the bits.** The chain would be identical, and that is the
  point of the exercise. `--engine program` and `--engine loop` would
  still have to agree with each other and with the software backend.
- **The arithmetic intensity.** `docs/SEQUENCER.md` argues that a
  sequencer stops being memory-bound around K ~ 30 iterations per
  load; this workload's default K is 1,024, and a whole batch of
  trajectories usually finishes inside one call. Each element is
  loaded once and deposited once for hundreds of steps of work, which
  is the regime the multi-tile design exists for.
- **The lane count.** A tile issues one beat per cycle - eight fp32
  lanes or one fp256 lane - and the pipeline is 15 stages deep with no
  stall path, so a batch below `15 * lanes_per_beat` runs at pipeline
  speed rather than throughput speed. `--batch 4096` is comfortably
  above that at every format.
- **What would not be measured honestly.** Numbers from `hw_emu` are
  RTL simulation seconds and mean nothing as hardware performance;
  `docs/BRINGUP.md` owns those gates. No device number is quoted here
  because no device has run this.

---

## The negative control

Two deliberate faults, each rebuilt and run through
`make -C host collatztest`.

### A: the parity clamp removed

The two opcodes that force "even" above 2^p (`CMPLT` against 2^p, then
`MIN`) were deleted from `build_program` and from the host loop, so
that the parity shift wraps for E > p-1 and a large value reads as
odd. This is not a hypothetical: it is the bug the first version of
the tool actually had.

Nothing below 2^p changes, so every ordinary sweep stays green - 2,000
values at fp256 in both engines, 2,000 at fp64, 3,000 in the fp32
window, the chain, the batch-size property and the resume property all
pass. Four rows fail, all of them boundary sets, and the first one
reads:

```
  ok    fp256 sweep 1..2000, sequencer program: 2000 starting values match
  ok    fp64 sweep 1..2000, sequencer program: 2000 starting values match
  FAIL: fp256 boundary set, sequencer program: got
        '2208558830972980411979121875928648144784354871094523697652007751615\
         77469 1 66256764929189412359373656277859444343530646132835710929560\
         2325484732408 6625676492918941235937365627785944434353064613283571\
         09295602325484732408 esc',
        oracle says '...469 8 ...408 18634715136334522226073840828147968721\
         6179942248600436989388154042580991 esc'
```

Eight exact steps become one. The trajectory climbs past 2^237, the
wrapped shift reads the resulting value as odd, it takes a tripling
that cannot be exact, and it is abandoned seven steps early with the
wrong final value. **The flag/witness assertion does not fire, and
correctly so**: the FMA really was inexact and the tool really did
detect it - what was wrong is that the element should never have taken
that branch at all. Both engines fail identically, so "the engines
agree" still passes too. Only the oracle knows.

That is the case for having an independent oracle rather than only
internal consistency checks, and it is not a hypothetical case: this
control is the bug the tool actually shipped with for an hour.

### B: the exactness witness weakened

`CMPEQ(res, 1.0)` was changed to `CMPLE(0.0, res)` in both engines, so
the witness answers "exact" for any non-negative residual - which is
true for most of the ways a tripling can round, since the residual is
`1 + delta` and `delta` is usually `+1` or `-1`.

Both nets caught it, and they caught it differently, which is the
useful part:

```
FAIL: fp256 boundary set, host cft_run loop: the tool refused to finish -
      cft-collatz: the INEXACT flag (1) and the per-element exactness
      witness (0 escapes) disagree - one of the tool, the library, or the
      argument in docs/COLLATZ.md is wrong

FAIL: fp256 boundary set, sequencer program: got
      '2208558830972980411979121875928648144784354871094523697652007751615774\
       71 245 6625676492918941235937365627785944434353064613283571092956023254\
       84732416 1 ok',
      oracle says '... 0 ... esc'
```

The **host loop** aborted with exit 3 on its very first step: it
checks the biconditional once per Collatz step, so the one element
whose tripling rounded was the only thing in the call and the union
could not be satisfied by anyone else. The **sequencer program** did
not abort, because it checks once per call of up to 1,024 iterations
over 23 elements, and some *other* element in that batch produced a
negative residual, set its escape flag, and satisfied the union. Its
2^237 - 1 then sailed on with a rounded value and reported a
245-step "verified" trajectory that does not exist - and the
big-integer **oracle** caught that.

So the honest statement about the assertion is:

> The flag/witness biconditional is checked per CALL, over the union.
> It is necessary and not sufficient: the coarser the call, the more
> a partly-broken witness can hide behind another element's correct
> detection. It is a cheap continuous gate, not a substitute for the
> oracle - and the two together caught this control in two different
> places.

`git checkout host/tools/collatz.c`, `make -C host collatz`, and
`make -C host collatztest` is green again: **18,107 comparisons, 0
failures.**

---

## What this does not do

- **It does not verify the Collatz conjecture.** The published
  verification is past 2^68 by exhaustive search with enormous
  amounts of hardware and sieving; this reaches 2^237 per *value* and
  a few hundred thousand values per hour on one thread. What it
  demonstrates is exactness at a width no integer type offers, and a
  workload whose stopping condition is a floating-point exception
  flag.
- **It has no sieve and no shortcut.** No `3n+1` fused with the
  following halving, no residue-class filtering, no memoisation of
  already-seen tails. Every one of those would make it faster and none
  of them would make it a better test of the contract, which is what
  it is for. `--engine loop` exists for the same reason: to be the
  slower thing that must agree.
- **Deep mode does not checkpoint.** It takes an explicit `--values`
  list, or a range, runs one batch and reports each trajectory. The
  resumable cursor is the sweep's.
- **No device has run it.** Everything above is the software backend.
