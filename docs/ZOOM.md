# The deep-zoom explorer

`host/tools/zoom.c`, built by `make -C host zoom`, computes a
Mandelbrot **reference orbit**

    z_{k+1} = z_k^2 + c

at binary256 and renders a batch of pixels around `c` by
**perturbation**

    d_{k+1} = 2 z_k d_k + d_k^2 + Dc

at binary64. Both halves go through libcft, so the frame is the
contract's arithmetic end to end. `host/tests/zoom_check.py` scores it
against `python/cft_golden` bit for bit and against mpmath at 300
digits; `make -C host zoomtest` runs that.

This is the project's own mission field - atlas-engine's deep zoom -
written as a benchmark FOR the contract rather than adapted to it, and
it says three things a microbenchmark cannot:

1. **The wide format buys DEPTH, and the depth is measurable.** At this
   zoom one pixel is 3.11e-61 wide. binary256 holds the centre to
   exactly 0 pixels of error; binary64's nearest neighbour is
   **9.38e30 pixels** away, and every one of the 4,096 pixels comes out
   different. That is not a worse image. It is a different one.
2. **The reference orbit is where determinism stops being a slogan.**
   The map is chaotic and every pixel in the frame is computed FROM the
   orbit, so two machines that disagree in one ulp at iteration 1,000
   disagree about the whole picture by iteration 3,000. "Bit-identical
   reference orbit" is the entire reproducibility claim of a deep-zoom
   renderer, and here it is tested four ways rather than asserted.
3. **A flag is not a certificate.** Unlike the Collatz explorer, where
   `inexact` is a per-element detector, here everything rounds and
   `inexact` says nothing. The binary64 run makes the point sharply: its
   reference orbit raises **no flags at all** - every operation in it is
   exact - and it is completely wrong.

---

## The centre, derived rather than transcribed

A deep zoom needs a centre whose orbit stays bounded for a very long
time. On the boundary of the set that is impossible in finite
precision: boundary dynamics are repelling, so any rounded orbit drifts
off and escapes. What works - and what every deep-zoom renderer
actually uses - is the **nucleus of a tiny hyperbolic component**,
where `z_p = 0` exactly, the cycle is superattracting, and a rounded
orbit is pulled back onto it instead of away from it.

Rather than copy a published location, the tool finds one, in the
library's own arithmetic. Three facts make the search cheap:

- **The tip is self-similar with ratio 4.** Near `c = -2` the structure
  repeats at every scale `4^-p`, and the period-`p` nucleus nearest the
  tip sits at about `14.80 * 4^-p`.
- **Every real `c` in [-2, 1/4] has a bounded critical orbit** - that is
  what `M` intersected with the real axis IS - so on this segment
  `z_p(c)` is a continuous real function with no escape to work around,
  and a **sign change of `z_p` brackets a nucleus**. No Newton, no
  derivative, no seed.
- **Every candidate is exact.** A grid point is `-2 + (i/8) * 4^-p` with
  `i` a small integer: its highest bit is `2^1` and its lowest is
  `2^(-3-2p)`, so it needs exactly `2p + 5` significand bits. The tool
  computes that bound from the format's measured `p` and refuses a
  period the format cannot hold, because an inexact candidate would
  make the sign of `z_p` a question about the grid rather than about
  the set.

So: evaluate `z_p` over 320 candidates - one lane per candidate, one
library call - take the first sign change, and bisect until the
interval is one ulp wide, keeping the endpoint whose `|z_p|` is
smaller. At `p = 51` (the default) that is 320 lanes for the scan and
130 bisection steps - the bracket starts `2^-105` wide and one ulp near
`|c| = 2` is `2^-235` - roughly 85 ms in total, and it lands on

    -1.9999999999999999999999999999970803456017437624325096395786848\
     5567954185763041022613779833013185032264663712978841176727500959\
     0453547545803090715481980010350457271998795753993561781326475525\
     17296533902690924833223107270896434783935546875

which is `-2 + 2.9196544e-30`, exactly, as a 237-bit binary256 number
whose decimal runs to 240 digits. `host/tests/zoom_check.py` re-derives
the same bits with the golden model and then asks mpmath at 300 digits
whether it is really a nucleus:

    |z_51(c)| = 1.61181e-42, and one ulp of c amplified through
    51 steps is about 4.59177e-41

`z_51` would be exactly 0 at the true nucleus; 1.6e-42 is what one ulp
of `c` becomes after 51 steps of a map whose derivative is about 4 per
step. So the tool's `c` is the nearest binary256 value to a period-51
nucleus, which is the most any binary256 number can be. mpmath then
confirms the orbit is **bounded for 100,000 iterations**.

`--centre RE,IM` overrides all of this with a location of your own, and
refuses one the format cannot hold exactly.

### Why this centre is a fair test and not a stacked deck

At binary64 this centre rounds to **exactly -2.0**, and the resulting
"reference" orbit is `0, -2, 2, 2, 2, ...` - not merely inaccurate but a
different parameter's orbit. That looks like a trick until you write
down the general rule: at any zoom whose pixels are 10^-61 wide, a
format discards everything below its own half-ulp at `|c|`, which is
2.2e-16 at binary64. Whether the discarded part happens to leave a
famous number or an ordinary one changes nothing about the conclusion.
`docs/ZOOM.md`'s numbers are quoted for this centre; the argument is
about the format.

---

## The step, instruction by instruction

`--engine program` (the default) compiles the iteration into one
orbit-sequencer program (`docs/SEQUENCER.md`) and runs
`--steps-per-call` iterations of it per library call. `r0` and `r1`
arrive from the `a` and `b` streams as `cft_program_run` defines;
`r2..r15` start at `+0`; `cr`, `ci` and `4` are the constant bank.

```
  REPEAT  K                          ; K = --steps-per-call

  MUL     r3 <- r0 * r0              ; zr^2
  MUL     r4 <- r1 * r1              ; zi^2
  ADD     r5 <- r3 + r4              ; |z_k|^2
  CMPLE   r6 <- r5 <= 4              ; still bounded?
  SETACT  r6                         ;   an escaped lane drops out HERE
  ADD     r7 <- r0 + r0              ; 2 zr, exact
  SUB     r8 <- r3 - r4              ; zr^2 - zi^2
  FMA     r1 <- r7 * r1 + ci         ; zi'  (reads the OLD r1)
  ADD     r0 <- r8 + cr              ; zr'
  DEPOSIT r0                         ; the orbit IS the deposits
  DEPOSIT r1

  ENDREP
  ACTALL
  HALT
```

Fifteen instructions in the image, eleven in the loop body, of which
**eight are arithmetic**: two multiplies, three adds, a subtract, a
fused multiply-add and one comparison. Three constants. `max_deposits`
is `2K`, because a reference orbit deposits every iteration - that is
what makes it an orbit rather than an escape time.

The escape test runs on `z_k` **before** the step, so a lane that has
passed `|z|^2 > 4` deposits nothing more and the deposit count says
exactly how far it got. `cft_program_run`'s `counts` is therefore the
iteration count, and the host needs no separate counter.

### Why this runs as a program

Every one of those instructions is an elementwise opcode the sequencer
already carries, so the whole thing fits with no additions. This is
the shape `docs/SEQUENCER.md` was designed around, named there in its
own words - *"Load a point once, iterate a program on it K times
on-chip, deposit what matters"* - and this is the workload it is
describing. Three things follow:

- **The deposits are the result.** Every iteration writes two values,
  addressed by lane and deposit index (P2), so the whole orbit comes
  back from one call. `--steps-per-call 1024` turns a 100,000-iteration
  reference into **98 library calls**; the host loop issues 800,000.
- **Convergence masking is free.** `SETACT` is the escape condition, and
  an inactive lane writes nothing, deposits nothing and raises no flag.
- **The last chunk gets its own image.** A program is compiled for its
  trip count, so rather than run the full count and discard the
  overrun, the tool rebuilds the program once for the final partial
  chunk. That is not tidiness: the flag word is a union over the call,
  so a call that computed iterations the host discards would report
  flags for work that is not in the result.

`--engine loop` issues the identical eight operations as eight
`cft_run` passes over one element per iteration and exists to be
compared against. The two must agree bit for bit, and the cross-check
holds them to that over every orbit point.

**With one lane there are no masking opcodes to buy.** The Collatz
explorer's host loop needed four extra opcodes to imitate `SETACT`
across a batch; here the batch is one element, so the host loop simply
stops. That is why the two engines issue the same eight operations and
why the program's advantage on the software backend is small (below):
what the sequencer saves is per-call dispatch amortised over LANES, and
a reference orbit has one lane.

### What the program model could NOT do, precisely

**The perturbation cannot be a sequencer program, and the obstacle is
exact.** The step

    d_{k+1} = 2 z_k d_k + d_k^2 + Dc

needs six live values per step: four per-lane and persistent (`dr`,
`di`, `Dcr`, `Dci`) and two that change EVERY ITERATION and are the
same for every lane (`zr_k`, `zi_k`). The program model provides:

- three input streams, which initialise `r0`, `r1`, `r2` once per call;
- fifteen further registers, which persist across a `REPEAT` - so the
  four per-lane values are fine;
- a constant bank fixed at load time and **addressed by the 4-bit
  register field, so at most 16 constants** - which is not enough to
  unroll more than a handful of iterations' worth of `z_k`.

There is no operand source that advances with the loop counter. So the
one thing this workload needs that the ISA cannot express is **a
per-iteration broadcast**: an operand that steps through a vector as
the loop iterates, shared by every lane. Two shapes would do it, and
either is a small change:

- a fourth stream read by index `iteration` rather than `lane` - call
  it the *sequence* stream - so `2 zr_k` and `2 zi_k` arrive the way
  `a`, `b` and `c` already do; or
- a constant bank addressable by the loop counter, which is the same
  thing with the vector in instruction memory.

That is the observation for the sequencer's designers, and it is not a
small one for this domain: perturbation rendering is the reason a
deep-zoom engine wants a sequencer at all, and it is the one part of
the workload the sequencer cannot currently run.

Three smaller notes from the same direction:

- **A reference orbit is ONE lane.** `docs/SEQUENCER.md`'s lane-block
  floor says `n` below `LATENCY * lanes_per_beat` runs at pipeline
  speed rather than throughput speed - 16 lanes at binary256. A single
  reference orbit would use one fifteenth of a tile. The domain's own
  answer is to run many references at once, which is exactly what
  multi-reference rendering does and exactly the batch a sequencer
  likes; a tile rendering a frame would carry 16 or 64 references, not
  one.
- **Depositing every iteration is the regime where the deposit buffer
  dominates.** `docs/SEQUENCER.md` puts the crossover at
  `max_deposits > 16`; this program's `max_deposits` is `2K` = 2,048 at
  the default. An orbit sequencer's flagship customer is therefore the
  case that makes the deposit buffer, not the register file, the area
  question - which is what that document predicted and is worth having
  a real number for.
- **A running per-lane minimum is expressible and was nearly free** - one
  `MIN` into a register seeded from the third stream - and the only
  thing that stopped this tool using it is that the magnitude the loop
  computes is `|z_k|^2`, which is exactly zero at `k = 0`. A minimum
  over "iterations after the first" needs either a separate first call
  or a predicate the ISA has no room for.

---

## Exactness, rounding, and what the flags can say

**Nothing here is exact.** `z^2 + c` rounds twice per component per
iteration by construction, so:

> `CFT_FLAG_INEXACT` is **EXPECTED** on essentially every call and
> carries no information about whether the orbit is right.

That is the opposite of the other workload on this contract, and it
changes what the tool can assert. What it does assert, on every call:

| what | kind | how |
|---|---|---|
| `inexact` | EXPECTED | ignored as evidence; reported |
| `invalid`, `divideByZero`, `overflow`, `underflow` | **CERTIFICATE** | none can occur while `\|z\| <= 2` and `\|d\|` stays bounded; the tool checks the flag word after every call and exits 3 if one appears |
| the escape test | **CERTIFICATE** | it is a COMPARISON, so it rounds nothing and signals nothing; the host-loop engine issues it on its own and checks that its flag word is exactly 0 |
| the orbit itself | **CERTIFICATE** | bit identity with `python/cft_golden`, every point |
| the two engines | **CERTIFICATE** | bit identity between the program and the host loop |

The tool prints two unions, because they say different things: `orbit
flags` is what the reference orbit raised, and `flags seen` adds the
minimum-magnitude pass, the pixel batch and the conversions. Beside
them it prints ABI 0.7's status word (754-2019 7.1), lowered once when
setup is done - measuring `p` and deriving the centre both raise
inexact deliberately - and never touched again, so it must agree with
the union.

### What the flag cannot tell you, in one measurement

    ./cft-zoom --format fp64 --ref-iters 100000 --no-pixels

    orbit flags   0x00  (inexact is expected; anything else stops the run)
    status word   0x00 (agrees with the union above)

The binary64 reference orbit raises **nothing**. Its centre rounded to
exactly -2, so the orbit is `0, -2, 2, 2, 2, ...`, and every operation
in it is exact: `(-2)^2 = 4`, `4 - 2 = 2`, `2^2 = 4`, for a hundred
thousand iterations. A perfectly exact computation of the wrong
problem. No exception flag in IEEE 754 can report that, and none
should - the flags describe the operations, and the operations were
faultless.

Two smaller observations in the same vein. At binary256 the FIRST
iteration is also exact (`z_0 = 0` makes every product and sum exact,
and `z_1 = c`), so `--ref-iters 1` reports `orbit flags 0x00`; rounding
starts at the second iteration, where `c^2 + c` needs 474 bits.
And the minimum-magnitude pass squares the orbit, so a run's total
union is `0x10` even when its orbit's is `0x00`.

---

## The pixel batch

Every pixel offset is an **exact odd multiple of a power of two**: the
view radius is `2^-E`, the grid is `W` pixels across with `W` a power
of two (the tool refuses anything else), so

    Dc_x = (2*ix + 1 - W) * 2^(-E-log2 W)

has at most 12 significant bits and is exact in binary64 and in
binary256 alike. The grid contributes no rounding of its own, which is
what lets the fp64 and fp256 frames be compared pixel for pixel.

The reference is rounded once into binary64 with `cft_convert` - which
is what the technique asks for, since the product `2 z_k d` needs the
reference only to binary64's own relative accuracy - and each iteration
is 23 elementwise operations over the live pixels: nine for the step
(four fused multiply-adds for the real part, three for the imaginary,
one exact doubling and one negate - the negate is how `- di^2` becomes
an FMA rather than a multiply and a subtract), four to form
`|Z_{k+1} + d|^2`, and ten for the two tests and the masked commit. Survivors are compacted to the front every 32
iterations; an element's trajectory depends on its own values and
nothing else, so where it sits in the array cannot change what it
computes - the same reason the sequencer may compact lanes.

### The glitch criterion, and why a good reference gets zero

Pauldelbrot's test marks a pixel whose perturbed value has cancelled
against the reference:

    |Z_k + d_k|^2  <  tol^2 * |Z_k|^2

Losing `b` bits to that cancellation means a ratio of `2^-b`, so the
tolerance is a number of BITS rather than a decimal: `--glitch-bits`,
defaulting to `p/4` with `p` measured from the pixel format - 13 bits
at binary64. (The literature's usual 1e-3 is 10 bits.)

At the nucleus the default frame reports **zero glitches**, and that is
the correct answer rather than a broken test: the nucleus is the
closest-to-zero orbit in the view, so no pixel's orbit can pass nearer
the origin than the reference does, and the criterion cannot fire. It
is precisely why deep-zoom renderers pick nuclei. `--ref-offset N`
moves the reference N pixels off the nucleus - which is what a renderer
that chose its reference carelessly does - and the criterion turns on
smoothly:

| reference offset, pixels | escaped | glitched | interior | escape iterations |
|---|---|---|---|---|
| 0 | 1004 | **0** | 20 | 307..2149 |
| 2 | 980 | 44 | 0 | 307..539 |
| 4 | 932 | 92 | 0 | 307..435 |
| 8 | 798 | 226 | 0 | 307..383 |
| 16 | 460 | 564 | 0 | 307..355 |
| 24 | 50 | 974 | 0 | 307..333 |
| 40 | 0 | **1024** | 0 | - |

(32 x 32 pixels at `--zoom-exp 196`, 6,000-iteration reference, 4,000
iteration cap.) The cross-check reproduces the offset case pixel for
pixel with the golden model, glitch verdicts included, so the criterion
is live code and not decoration.

---

## The checkpoint format

A line-oriented ASCII file with LF endings, written to `<path>.tmp`,
flushed, closed and then **renamed over** the target
(`MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` on Windows, `rename()`
elsewhere), so a reader never sees a half-written one.

It carries every number that describes a **result** and nothing that
describes the **machine** - which is what lets runs with different trip
counts, different engines and different batch sizes end on
byte-identical files.

```
cft-zoom-checkpoint 1
format fp256
centre -1.9999999...e+0 0        the centre, exact decimal, both parts
refiters 100000                  the length this run is for
k 43521                          iterations resolved
escapedat 0                      or the iteration |z|^2 passed 4
chain 8cf49c0b...                SHA-256 chain over the orbit so far
orbit 43521
z -1.9999999...e+0 0             ...one line per iteration, in order
z 1.9999999...e+0 0
...
end
```

Values are produced by `cft_to_decimal_char` with `digits = 0` -
5.12.2's exact conversion - and read back by `cft_from_decimal_char`,
which refuses anything the format cannot hold exactly. What the library
writes, the library reads back, so a checkpoint round trip cannot lose
a bit.

The **hash chain** is

    chain_0     = 32 zero bytes
    chain_(k+1) = SHA-256( chain_k || record_k || "\n" )

over records in **iteration order**, where a record is
`<k> <re> <im>`. `--orbit PATH` writes exactly those lines, so the
chain can be recomputed by anything; that file is truncated at the
start of each run and is not resume-aware, because the checkpoint's
chain is the thing that spans an interruption. A second chain, over
`<index> <iterations> esc|glitch|interior` in **pixel-index order**, is
what makes the pixel batch's determinism checkable; index order rather
than completion order is the whole of it, because pixels finish in
whatever order their trajectories allow.

SHA-256's eight initial words and sixty-four round constants are
**derived** in the tool from the square and cube roots of the first 64
primes, by integer binary search in 128-bit arithmetic, rather than
typed in - this repository's standing rule about constants. The
cross-check recomputes the chain with Python's `hashlib`, which is what
proves the derivation right.

Two honest notes about the shape. The file is **O(the orbit)**: 245
bytes a point, so 24.5 MB at 100,000 iterations, and writing one costs
more than computing the orbit does - 1.31 s against 0.54 s.
Checkpointing is opt-in for that reason. And the **pixel phase does not checkpoint** - it is one batch of
independent elements, like the Collatz explorer's deep mode; its
determinism property is batch-size independence rather than resume, and
it is tested as such.

The minimum `|z_k|^2` is deliberately NOT in the checkpoint, because it
is a function of the orbit that is already there. It is also not
computed per iteration: doing that cost four single-element library
calls per orbit point - half as much work again as the eight the step
needs, and 400,000 calls where the sequencer had got the count down to
98. It is now three whole-array passes and a `MIN` tournament after the
run, about `2*log2(n) + 4` calls for any `n`. **A per-iteration
host-side statistic quietly undoes exactly what the sequencer is for**,
and that is worth writing down because it is easy to add one without
noticing.

---

## Determinism, and how it is tested

The claim in the tool's header is:

> The same centre produces a bit-identical reference orbit and a
> bit-identical frame whatever the engine, the trip count, the batch
> size, the host or the backend.

`host/tests/zoom_check.py` tests it rather than asserting it:

| property | how |
|---|---|
| the orbit | every point against `python/cft_golden`'s own binary256 semantics, in both engines, at two trip counts - and again at a COMPLEX centre |
| the centre | re-derived bit for bit with the golden model, and confirmed a nucleus by mpmath at 300 digits |
| engines | the sequencer program and the host `cft_run` loop must produce byte-identical orbits AND byte-identical checkpoints |
| trip count | 1024 and 63 over the same range must end on byte-identical checkpoints |
| batch size | 3 and 4096 must derive the same centre and the same checkpoint; 7, 64 and 4096 must give byte-identical pixel records |
| interruption | a run stopped every five passes and resumed, at a different trip count, must end on the same checkpoint - byte for byte - as one that was never stopped |
| the pixels | every escape iteration and verdict against the golden model's own binary64 semantics, at three centres including the glitching one |
| the chains | recomputed with `hashlib` |
| refusals | a width that is not a power of two, a centre the format cannot hold exactly, an unknown option |

The interrupt leg stops every five engine calls at `--steps-per-call
37`, so a stop lands in the middle of the orbit rather than on a
convenient boundary, and it resumes at a different trip count from the
run it is compared against.

The gate on this tree:

    11212 comparisons, 0 failures
    ZOOM CHECK OK - the tool, the golden model and mpmath agree

about 14 seconds. mpmath is optional - the golden-model half of the
check needs nothing but Python - and when it is missing the script
prints a SKIP naming the four rows it is not running, and its summary
line says

    ZOOM CHECK OK against the golden model - but mpmath was MISSING,
    so nothing here checked the domain

rather than the usual one. That is the repository's own rule applied to
this gate: a log that quietly checked nothing must not read as a pass.
It is here because writing the negative controls found exactly that -
the control script had put a different interpreter first on PATH, and
four rows vanished without a word.

---

## The binary64-versus-binary256 result

This is the measurement the workload exists for, and it has three
independent parts.

### 1. Can the format hold the centre at all?

Derived from the format parameters, not tabulated: a centre near
`|c| = 2` is held to half an ulp, `2^(1-p)`.

| format | half an ulp at \|c\| = 2 | deepest pixel it can address |
|---|---|---|
| binary64 | 2.22e-16 | about 1e-15 |
| binary256 | 9.06e-72 | about 1e-71 |

**Fifty-six decades of zoom depth.** Everything below is a consequence
of that line.

At this frame's pixel scale of 3.11e-61, measured rather than argued -
the tool computes `|c_fmt - c_fp256| / pixel` exactly and prints it:

| reference format | centre error, in pixels |
|---|---|
| binary256 | **0** |
| binary128 | 1.78e+26 |
| binary64 | 9.38e+30 |
| binary32 | 9.38e+30 |

binary32 and binary64 agree because both round this centre to exactly
-2; they return the same orbit chain for the same reason.

### 2. Reference validity length

`host/tests/zoom_check.py` runs the orbit at 300 digits in mpmath and
asks when each format's reference first differs from it. Two criteria,
because they answer different questions:

**The absolute criterion** - the first `k` at which
`|z_k^fmt - z_k^300|` exceeds a given scale - is the one the workload
names, and this is what it gives over 600 iterations at this centre:

| scale | 1e-10 | 1e-20 | 1e-30 | 1e-40 | 1e-50 | 1e-60 | 1e-70 |
|---|---|---|---|---|---|---|---|
| binary256 | never | never | never | never | 38 | 21 | 4 |
| binary64 | 34 | 18 | 1 | 1 | 1 | 1 | 1 |

**The relative criterion is the one that governs the image**, and it is
worth being clear about why. The reference error and a pixel's own
offset obey the SAME linearised recurrence, `x_{k+1} = 2 z_k x_k`, so
they amplify together and their ratio is what matters, not either
one's absolute size. Measured against a real pixel's true deviation at
300 digits:

| reference format | first k at which the reference error exceeds a pixel's own deviation |
|---|---|
| binary256 | **never**, in 600 iterations |
| binary64 | **1** - before a single pixel has moved |

So the honest statement of the absolute table is that it measures the
Lyapunov exponent of the map (about 4 per iteration near the tip)
rather than the usability of the reference. The number that decides
whether the frame is right is the ratio, and it is fixed at iteration
zero by whether the format can hold the centre.

### 3. The frame itself

    ./cft-zoom --pixels frame256.txt
    ./cft-zoom --format fp64 --compare-pixels frame256.txt

| | binary256 reference | binary64 reference |
|---|---|---|
| centre | -1.99999...875 (240 digits) | exactly -2 |
| orbit flags | 0x10 | **0x00** |
| smallest \|z\|^2 | 8.45e-87 at k = 51 | 4.0 at k = 1 |
| escaped | 4,010 | 4,096 |
| interior | 86 | 0 |
| escape iterations | **307..3227** | **74..107** |
| pixels differing from the binary256 frame | - | **4096 of 4096** |
| pixel chain | `d4c3fce95f476184...` | `014e9fb971e3c3c2...` |

Every pixel is different, the escape-time range does not overlap, and
the binary64 frame has no interior at all. `--pgm PATH` writes the
escape map as a 4,109-byte PGM if you want to look at them.

---

## Measured throughput

Software backend, single thread, on DESKTOP-T33SK86 (Windows 11,
MINGW64, `gcc -O2`), 2026-09-04. This is a shared box: the same
measurement taken while other work was running came back about 25%
lower across the board, so every row here is a **median of five**, and
the spread within a set of five is about +-10%. Treat the ratios as the
result and the absolute numbers as an order of magnitude. The command
for one row is

```
./cft-zoom --format fp256 --engine program --ref-iters 100000 \
           --no-pixels --csv
```

with `--format` and `--engine` varied.

| format | engine | reference iterations/s | elementwise ops/s |
|---|---|---|---|
| fp256 | program | 174,462 | 1,395,696 |
| fp256 | loop | 162,374 | 1,298,992 |
| fp128 | program | 275,562 | 2,204,496 |
| fp128 | loop | 237,276 | 1,898,208 |
| fp64 | program | 450,980 | 3,607,840 |
| fp64 | loop | 387,555 | 3,100,440 |
| fp32 | program | 493,293 | 3,946,344 |
| fp32 | loop | 465,075 | 3,720,600 |

Eight arithmetic operations an iteration, so the ops column is the
iterations column times eight exactly - the tail-program rule above is
what makes that exact rather than approximate. The pixel batch, 64 x 64
pixels at `--zoom-exp 196`, is **399,782 pixel-iterations/s** (median of
five), or about 9.2 million binary64 elementwise operations a second at
23 operations a pixel-iteration. Batch 64 through 16,384 land between
375,000 and 411,000, rising slightly with the batch as the per-call
overhead is amortised, and every one of them returns the identical
pixel chain `d4c3fce95f476184...`, which is the property that actually
matters.

Three things in those numbers are worth more than the numbers:

- **The sequencer route is only 1.06x to 1.16x faster than the host
  loop here**, where the Collatz explorer saw 1.5x to 2.1x. The reason
  is structural and worth stating: a reference orbit is ONE lane, so
  the program saves per-call dispatch on a call that was doing one
  element's work anyway. What the sequencer buys is dispatch amortised
  over lanes and, on a device, a memory round trip per step - neither
  of which a single-lane orbit on a software backend can show. The 98
  library calls against 800,000 is the honest way to state its
  contribution here.
- **The pixel half is 6.6x faster per operation than the reference
  half**, because it is 4,096 elements a call instead of one - and it
  is a narrower format. That asymmetry is the whole shape of
  perturbation rendering: one expensive sequential orbit, then an
  embarrassingly parallel frame.
- **fp256 is 2.6x slower than fp64 per iteration** - not 4x, not 10x -
  which is the same shape `docs/BENCHMARKS.md` reports for the
  elementwise operations.

The headline frame:

```
./cft-zoom --pixels frame256.txt --pgm frame.pgm
```

| | |
|---|---|
| reference | 100,000 iterations at fp256, 0.54 s, **98 library calls** |
| smallest \|z\|^2 | 8.45406e-87 at k = 51 |
| pixels | 4,010 escaped, 0 glitched, 86 interior, escape iterations 307..3227 |
| pixel work | 1,862,720 pixel-iterations at fp64, 4.6 s |
| orbit flags | 0x10 (inexact only) |
| orbit chain | `8cf49c0b2cdcf6bf899ba7fbc763aa5ee82449807578052f20934cc365afc3e4` |
| pixel chain | `d4c3fce95f476184f5fe065f8266643821d7af473ddc87fee6bcc12bd3059e7a` |

### What a device run would change

The same binary, given an `--artifact` path, opens the tile instead of
the software backend and issues the identical program. What changes:

- **Not the bits.** The chains would be identical, and that is the point
  of the exercise. Both engines would still have to agree with each
  other and with the software backend.
- **The reference orbit would run at pipeline speed, not throughput
  speed.** One lane at binary256 is one fifteenth of the tile's issue
  rate (`docs/SEQUENCER.md`'s lane-block floor). A tile rendering a
  frame should carry 16 or 64 references at once - which is what
  multi-reference deep-zoom rendering does anyway, and what turns this
  workload into the sequencer's best case rather than its worst.
- **The arithmetic intensity is already right.** Each reference point is
  loaded once and deposited 2,048 times per call at the default trip
  count; `docs/SEQUENCER.md` puts the memory-bound crossover at K ~ 30.
- **The pixel half would not use the sequencer at all**, for the reason
  in "What the program model could NOT do" above. It would run as
  `cft_run` batches over 4,096 elements, which is the elementwise
  engine's own best case.
- **What would not be measured honestly.** Numbers from `hw_emu` are RTL
  simulation seconds and mean nothing as hardware performance;
  `docs/BRINGUP.md` owns those gates. No device number is quoted here
  because no device has run this.

---

## The negative controls

Three deliberate faults, each rebuilt and run through
`make -C host zoomtest`, then restored.

### A: the complex step, sabotaged in BOTH engines

`SUB r8 <- r3 - r4` became `ADD`, in the program and in the host loop,
so `zr^2 - zi^2` is computed as `zr^2 + zi^2`. Both engines are wrong
identically.

**Twenty-five of the check's twenty-six rows stay green.** The engines
agree with each other. The checkpoints match across trip counts,
batch sizes and engines. The resume test passes. The chain matches
hashlib. Every pixel of the deep frame matches the golden model. The
binary64 comparison still reports 4096 of 4096. mpmath still agrees
that the centre is a nucleus and that the binary256 reference never
drifts past a pixel's own deviation.

One row fails:

```
  FAIL: the complex-centre orbit differs from the golden model
```

The reason is the point of the control: **the derived centre is real**,
so `zi` is exactly `+0` for the whole orbit, and `zr^2 - 0` and
`zr^2 + 0` are the same value. A whole branch of the arithmetic is
invisible to the default frame. The cross-check carries a complex
centre (`-0.125, 0.75`) for exactly this reason, and it is the only
thing that sees the bug - not the engines agreeing, not the
checkpoints, not the chain, not the deep frame's pixels.

That gap was found by writing this control, and the complex-centre row
was added because of it.

### B: the reference rounded into binary64 the wrong way

`cft_convert(..., CFT_RNE, ...)` became `CFT_RTZ` for both components
of the reference. The reference orbit itself is untouched.

Twenty-five rows green again - the orbit, both engines, all four
checkpoint properties, the chain, the refusals, the binary64
comparison, both mpmath rows. One row fails:

```
  FAIL: the reference 12 pixels off the nucleus, pixel 2:
        tool says (176, 'esc'), the golden model says (175, 'esc')
```

One iteration, on one pixel, out of 4,096 comparisons. Only the
**pixel** oracle sees it, because it is the only gate that knows what
the perturbation should have computed. Note also what it demonstrates
about the layering: the pixel oracle takes the tool's OWN reference
orbit as its input, so it certifies the perturbation given the
reference, and the orbit check certifies the reference. Neither covers
the other, and both are needed.

### C: one engine only

`ADD r0 <- r8 + cr` in the program became `ADD r0 <- r0 + cr`, so the
sequencer program iterates `z <- z + c` while the host loop still
iterates `z <- z^2 + c`.

Eight rows fail, immediately and loudly:

```
  FAIL: fp256 orbit, program engine: 2 points, model has 2000
  FAIL: the two engines produce different orbits
  FAIL: the complex-centre orbit differs from the golden model
  FAIL: the two engines end on different checkpoints
  FAIL: the resumed run did not finish
  FAIL: moving the reference 12 pixels off the nucleus produced no glitches
  FAIL: only 0 of 1024 pixels differ
  FAIL: the binary256 reference drifted at k = 2
```

This is the control the INTERNAL gates catch: the engine cross-check
and the checkpoint comparison both fire without any oracle at all. It
is here to show that those gates are live, because controls A and B
show what they cannot do.

### What the oracle catches that the internal checks cannot

Stated plainly, because it is the lesson of A and B:

> The engine cross-check, the checkpoint comparisons and the chain
> prove that the tool computes the SAME thing every time. They cannot
> prove it computes the RIGHT thing, and two engines built from one
> understanding are wrong together. Only an independent definition of
> correct catches that - `python/cft_golden` for the arithmetic, mpmath
> for the domain - and only over inputs that exercise the branch in
> question, which is why control A needed a complex centre and control
> B needed a per-pixel oracle.

`git checkout host/tools/zoom.c`, `make -C host zoom`, and
`make -C host zoomtest` is green again: **11,212 comparisons, 0
failures.**

---

## What this does not do

- **It is not a renderer.** No colouring, no anti-aliasing, no series
  approximation, no automatic re-referencing of glitched pixels. It
  MARKS glitched pixels, which is the part that belongs to the
  numerics; choosing a new reference for them is a renderer's job.
- **It renders one frame from one reference.** Real deep-zoom engines
  carry several references and assign pixels to the nearest good one.
  That is the multi-lane shape the sequencer wants, and it is the
  obvious next workload.
- **The perturbation does not run on the sequencer**, for the reason
  given above, and that gap is reported rather than worked around.
- **The reference is a single lane**, so on a device it would run at
  pipeline speed. See "What a device run would change".
- **No device has run it.** Everything above is the software backend.
