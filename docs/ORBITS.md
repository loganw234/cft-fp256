# The orbit integrator

`host/tools/orbits.c`, built by `make -C host orbits`, integrates
gravitational few-body systems with symplectic schemes where every
arithmetic step is the library's, at any of the four formats, over an
ensemble of copies of the same system perturbed by an exact number of
ulps. `host/tests/orbits_check.py` scores it against a 300-digit
mpmath oracle; `make -C host orbitstest` runs that.

The tool itself needs nothing but libcft. The check needs **mpmath**,
its one dependency - and on Windows a bare `python` inside a make
recipe is often not the interpreter on your shell's PATH, so pass one
in the way `verify/run.sh` does:

```
make -C host orbits
make -C host orbitstest PYTHON=/c/path/to/python.exe
```

It exists because this workload has two error sources that behave
completely differently, and separating them is the only way either
becomes a number.

> **TRUNCATION** is a property of the METHOD. Stormer-Verlet is second
> order, so its energy error is O(h^2) and - because the scheme is
> symplectic - it oscillates with the orbit instead of growing. It is
> the same number in every arithmetic.
>
> **ROUNDOFF** is a property of the ARITHMETIC. It has no reason to
> cancel, so it accumulates: the energy random-walks and the phase
> drifts secularly. In binary64 that drift buries the method's own
> error over a long integration, and from then on the run is measuring
> the floating-point format rather than the physics.

Three things this says that a microbenchmark cannot:

1. **The two errors come apart, and both are measured.** The energy
   drift over 2000 Kepler periods is `7.94534e-4` at binary64 and
   `7.94534e-4` at binary256 - identical to every digit printed,
   because it is the method's. The angular-momentum drift over the
   same run is `9.00177e-69` at binary256 and `1.44687e-13` at
   binary64, a factor of `1.61e55` - because it is the arithmetic's
   and nothing else, **both schemes conserving angular momentum
   exactly**. One run, two numbers, one format-blind and one
   format-determined.
2. **fp256 puts the roundoff floor more than 60 orders of magnitude
   below the truncation error** - `5.5e64` for leapfrog and `8.7e61`
   for Yoshida on the check's own runs - which is the condition a
   step-size study needs and binary64 does not have.
3. **The sequencer could not hold this workload, and the reason was
   precise.** Two independent obstacles, each fatal on its own, and
   both of them were facts about the program model rather than about
   this tool when it was written. Revision 3's scratch block
   (2026-09-08) answered the first, and since 2026-09-25 `--engine
   segments` uses it: the outer solar system runs as programs, resumes
   from a checkpoint either engine wrote, and is not bounded by the
   tile's deposit budget. The second - a correctly rounded divide and
   square root inside the loop - is still open. Both are written out
   in full below.

---

## The two measurements, defined

Let `S_fmt(t)` be the tool's state at time `t` in a format, `S_300(t)`
the state produced by running **the same discrete scheme** at 300
digits from the **same starting encodings** and the **same derived
constants**, and `S_exact(t)` the true solution.

    roundoff(fmt)  =  || S_fmt(t)  - S_300(t)   ||  /  || S_300(t) ||
    truncation     =  || S_300(t)  - S_exact(t) ||  /  || S_exact(t) ||

"The same constants" is not a detail. `h` is `fl(2*pi/S)`, the drift
scale is `fl(fl(w*h) * 0.5)`, `G` is `fl(k*k)`; an oracle that used
the exact real numbers instead would be charging the constants'
rounding to the integration and the first line would stop meaning
roundoff. So `--dump-setup` prints every derived constant as an exact
decimal and the oracle integrates with those - the same reason a
program image can be read back to attest what executed.

For the Kepler problem `S_exact` is available in closed form through
Kepler's equation, so both lines are computable. For the outer solar
system only the first is, which is exactly the case the 300-digit
oracle exists for.

### The angular-momentum certificate

Total angular momentum is conserved **exactly** by both schemes, in
exact arithmetic, for both problems:

- a drift moves `q_i` along `v_i`, so it adds `m_i c (v_i x v_i) = 0`;
- a kick adds `sum_i m_i q_i x dv_i = sum_{i/=j} m_i g_ij (q_i x q_j)`,
  and `m_i g_ij = h G m_i m_j / r^3` is symmetric in `i` and `j`, so
  the `(i, j)` and `(j, i)` terms cancel. That symmetry is Newton's
  third law, written in the arithmetic.

So the angular-momentum drift the tool reports has **no truncation
component at all**. It is a direct measurement of the accumulated
roundoff, it needs no oracle to interpret, and it is a gate rather
than a diagnostic - `orbits_check.py` bounds it by
`steps^2 * 2^-p * 10^6` for both problems and both schemes.

The energy drift is the complementary number: it is dominated by
truncation, and the two formats agree on it to every digit printed.

---

## The two problems

### `--problem kepler`

A test particle around a unit point mass at the origin, in the plane.
`mu = 1`, semi-major axis `a = 1`, eccentricity `e = 3/4`. The initial
condition is Hairer, Lubich and Wanner, *Geometric Numerical
Integration: Structure-Preserving Algorithms for Ordinary Differential
Equations*, 2nd edition (Springer, 2006), section I.2.2:

    q = (1 - e, 0)          v = (0, sqrt((1 + e)/(1 - e)))

with `H = -1/2`, `L = sqrt(1 - e^2)` and period `T = 2*pi`.

`e = 3/4` rather than 0.7 because it is **dyadic**: `1 - e = 1/4` and
`1 + e = 7/4` are exact in every format, so the only initial value
that needs rounding is the speed `sqrt(7)`, and that one is delivered
by `cft_sqrt`, correctly rounded. The check script recovers `a` and
`e` from the stored bits and confirms they are `1` and `3/4` to within
`5e-71`.

The two zeros in that initial condition are not a convenience. They are
the only reason this tool's program engine can run this problem at all -
see "The step, and where it runs".

### `--problem outer`

The outer solar system - Sun (carrying the inner planets' mass),
Jupiter, Saturn, Uranus, Neptune - in heliocentric coordinates, AU and
days, from the same book's section I.2.3. The Sun starts at rest at
the origin, so the barycentre drifts; that is the published setup and
both invariants are conserved regardless.

The gravitational constant is **not** transcribed: `G` in
AU^3 day^-2 Msun^-1 is `k^2`, the square of the IAU 1976 Gaussian
gravitational constant `k = 0.01720209895`, and the tool squares it
with one `CFT_MUL`. The positions, velocities and masses **are**
transcribed, because they are measurements and there is nothing to
derive them from. So `orbits_check.py` validates the table against the
sky instead: each planet's osculating semi-major axis and period,
recovered from its own `(r, v)` and the two-body formula, against the
published sidereal periods.

```
        Jupiter  a =  5.20261 AU, osculating period   11.861 yr (published  11.862, 0.01%)
        Saturn   a =  9.54018 AU, osculating period   29.463 yr (published  29.457, 0.02%)
        Uranus   a = 19.26840 AU, osculating period   84.580 yr (published  84.021, 0.66%)
        Neptune  a = 30.20788 AU, osculating period  166.026 yr (published 164.790, 0.75%)
```

A mistyped digit moves one of those by percent. This is what the
repository's "derive constants, never transcribe them" rule turns into
when the constant genuinely cannot be derived.

---

## The schemes

`--scheme leapfrog` is Stormer-Verlet in drift-kick-drift form, one
force evaluation per step:

    q += (h/2) v ;   v += h a(q) ;   q += (h/2) v

`--scheme yoshida4` is Yoshida's fourth-order composition of it,

    S4(h) = S2(w1 h) . S2(w0 h) . S2(w1 h)
    w1 = 1/(2 - 2^(1/3))        w0 = -2^(1/3)/(2 - 2^(1/3))

with `2^(1/3)` delivered by `cft_rootn` - 754-2019 9.2's correctly
rounded `rootn` - and `w0`, `w1` composed from it by `cft_div` and
`cft_run`. Derived, never typed; `w0 + 2 w1 = 1` follows.

**The adjacent drifts of neighbouring substeps are deliberately not
merged.** Merging them is the standard optimisation and it is a
different sequence of roundings; the sequence of roundings is what
this contract is about, so the tool pays three force evaluations and
six drifts per fourth-order step and says so.

The orders come out of the tool's own output rather than out of this
file. Over one period at binary256, halving `h` cuts the error from
the closed form by

| scheme | error at 1024 steps/period | at 2048 | ratio | order |
|---|---|---|---|---|
| leapfrog | `1.212e-2` | `3.035e-3` | **3.99** | 2 |
| yoshida4 | `7.618e-5` | `4.775e-6` | **15.96** | 4 |

---

## 1/r^3, and the two routes

Every kick needs `G m / r^3` for every pair. `r^2` is one `CFT_MUL`
and `ndim - 1` `CFT_FMA`s. What happens next is `--rsqrt`:

**`--rsqrt exact`** (the default)

    s = cft_sqrt(r2)          correctly rounded
    w = r2 * s                one rounding      (= r^3)
    g = cft_div(K, w)         correctly rounded

Three roundings for the whole factor, two of them from correctly
rounded composed operations. `cft_sqrt` and `cft_div` are the
library's own compositions of the tile's seed opcodes and its FMA
(docs/HOSTAPI.md, `python/cft_golden/sequences.py`), so every rounding
in them belongs to the contract and the reader can bound the error
from IEEE 754-2019 rather than from this file.

**`--rsqrt newton`**

    y = CFT_RSQRT_SEED(r2)
    n times:  w = r2*y ;  e = fma(w, y, -1) ;  z = y*(-1/2) ;  y = fma(z, e, y)
    g = K * y^3

A fixed, published refinement from the tile's own seed opcode. **Not**
correctly rounded - it is a documented composition with a few ulps of
its own - but every instruction in it is an ALU opcode, which is what
makes it expressible on-chip and is the only reason it exists.

The pass count is derived, in integers, and conservative at every
step. `CFT_RSQRT_SEED`'s stated relative error is below `2^-8.5`, so
the seed is good to at least **eight** bits - the weaker integer bound
deliberately, so nothing needs an irrational constant. A Newton pass
takes relative error `e` to `1.5 e^2 + O(e^3)`, and
`1.5 (2^-b)^2 < 2^-(2b-1)`, so a pass at least doubles the correct
bits and loses at most one. Iterating `b -> 2b - 1` from 8 until it
passes `p + 2` gives

| format | p | passes | bits after |
|---|---|---|---|
| fp32 | 24 | 2 | 29 |
| fp64 | 53 | 3 | 57 |
| fp128 | 113 | 5 | 225 |
| fp256 | 237 | 6 | 449 |

**Correct rounding costs 2.2x here and is still the default.** At
binary256 the exact route runs at 35,233 element-steps/s against the
Newton route's 79,150 (measured below). The factor is a factor and not
an order, and only one of the two routes has an error a reader can
bound from the standard.

---

## The step, and where it runs

### As a sequencer program

Under `--engine program` the **whole integration** compiles into one
orbit-sequencer program (docs/SEQUENCER.md) and runs as one
`cft_program_run` call per batch. The loop body, per substep, is

```
  DEPOSIT r0 ; DEPOSIT r2 ; DEPOSIT r3 ; DEPOSIT r1   ; sample 0
  REPEAT  nsamples
    REPEAT  stride
      FMA  r0 <- hd*r3 + r0            ; drift q0
      FMA  r2 <- hd*r1 + r2            ; drift q1
      MUL  r6 <- r2 * r2
      FMA  r4 <- r0*r0 + r6            ; r^2
      RSQRT_SEED r5 <- r4
      n x { MUL r6 <- r4*r5 ; FMA r7 <- r6*r5 + (-1)
            MUL r8 <- r5*(-1/2) ; FMA r5 <- r8*r7 + r5 }
      MUL  r6 <- r5 * r5
      MUL  r6 <- r6 * r5               ; 1/r^3
      MUL  r9 <- r6 * mg               ; -(w h mu)/r^3
      FMA  r3 <- r9*r0 + r3            ; kick v0
      FMA  r1 <- r9*r2 + r1            ; kick v1
      FMA  r0 <- hd*r3 + r0            ; drift q0
      FMA  r2 <- hd*r1 + r2            ; drift q1
    ENDREP
    DEPOSIT r0 ; DEPOSIT r2 ; DEPOSIT r3 ; DEPOSIT r1
  ENDREP
  HALT
```

`12 + 4n` ALU instructions per substep - **36 at binary256** - two
constants per substep plus two shared (`nk = 2 + 2 * nsub` in
`host/tools/orbits.c`), and `4 (nsamples + 1)` deposit
slots per lane. The register map is

    r0 = q0  (the a stream)      r4 = r^2     r7 = e
    r1 = v1  (the b stream)      r5 = y       r8 = z
    r2 = q1  (the c stream: +0)  r6 = w       r9 = g
    r3 = v0  (starts at +0)

and it is **forced**, which is the whole point of the next section.

### The two things that stop it, and what they ask for

`--engine program` refuses `--problem outer`, refuses `--rsqrt exact`
and refuses `--resume`. All three refusals are one of two facts about
the program model as it stood when this tool was written. Since
revision 3 (2026-09-08) the first is answered by the scratch block,
and `--engine segments` (below) is the engine that uses it; `--engine
program` itself is kept as it was, for the reason that section gives.
The second still cannot be worked around by writing the program
differently, and both program engines refuse `--rsqrt exact` by name.

**(1) Three input streams against 2d state values.**
`cft_program_run` initialises `r0`, `r1` and `r2` from `a`, `b` and
`c`; `r3..r31` start at `+0`, normatively. A Hamiltonian system with
`d` degrees of freedom has `2d` state values per lane, and

    planar Kepler          2d = 4
    outer solar system     2d = 30

So, without revision 3's scratch block, **a program can be entered only
at a state with at most three non-zero components.** The Kepler initial condition has exactly two -
`q = (1-e, 0)`, `v = (0, v0)` - and the two components that must be
zero can be put in registers that start at `+0` (`r2` by passing
`c = NULL`, `r3` because `r3..r31` always do). Step 0 is therefore
reachable and **no later step is**, which is why the program engine
runs the whole integration in one call, cannot resume into the middle
of one, and cannot exist at all for the outer solar system. It is also
why the ensemble perturbation is confined to `q0` and `v1`: those are
the two components a stream can carry.

`docs/COLLATZ.md` recorded the same limit more gently - that workload
needed four pieces of state and "only fits because the fourth is an
output that always starts at +0". This one shows the limit binding.
**A fourth input stream, or a "load `r3..` from the deposit buffer"
mode, would make every 2-degree-of-freedom system resumable and every
3-degree-of-freedom one expressible.** Thirty-two registers are
already far more than a 6-value state needs, and since revision 3
(2026-09-08) the scratch block is that loading; `--engine segments`
uses it.

**(2) A correctly rounded divide or square root cannot sit inside this loop.**
`python/cft_golden/seqprogs.py` is the library's own in-program
`cft_div`/`cft_sqrt`, and its docstring states the partition: **host**
prep (operand classification, the exact prenormalise/centre surgery),
**program** core (seed, Newton, the truncating Markstein finish, the
restore passes), **host** finish (`round_pack`, the contract's single
rounding authority). The core alone occupies `r0..r12` of the
thirty-two registers a lane owns.

So the composed route cannot be inlined into a larger program's loop
body: it needs the host between its halves. The whole-program route
that has existed since 2026-09-14 (`python/cft_golden/divfull.py`,
opt-in in libcft behind `CFT_DIVSQRT_FULL=1`) does not, but it is a
WHOLE program - operands from the streams, the result and its flags as
deposits, registers up to `r31` and its own constants - and the ISA has
no call. Room is not the obstacle any more: under `--engine segments`
the orbit state lives in the scratch block between the instructions
that use it. The splice is: putting one inside another program's loop
body needs a fragment inliner that relocates its registers and
constants and turns its deposits into moves, and nothing in the tree
does that yet. `--rsqrt exact` is therefore a loop-engine route, and
`--rsqrt newton` exists so that all three engines have a step they can
run - which they then have to run bit for bit.

The obvious way round (2) - leave `1/r^3` as a host-side composed call
*between* program passes, so that each pass is drift-and-`r^2` or
kick-and-drift - died on (1): a pass that resumed at the force
evaluation needed four inputs, because every point inside a leapfrog
step has all four state values live. Segments remove that objection -
a pass can now be entered at any state - so the split would work
today, at the price of two program runs and three library calls a
substep, which is the call-bound shape the program model exists to
avoid. It is not built.

**What the sequencer would need to run this workload as one program:**
a way to load more than three registers (revision 3's scratch block,
which `--engine segments` uses), and either a callable composed
operation or an in-program correctly rounded divide that can be
spliced into a loop body. Neither is proposed here as an ISA change;
both are what this workload found.

### As resumable segments (`--engine segments`, 2026-09-25)

`--engine segments` is the program engine rebuilt on the scratch
block. One lane is one ensemble member, and its scratch holds the
member's whole state in `2 * ncomp` slots - slot `c` is `q_c` and slot
`ncomp + c` is `v_c`, the checkpoint's order - which
`cft_program_run_ex` preloads before the run and reads back after it
(docs/SEQUENCER.md R5). A run is therefore a **segment**: `k` steps
from whatever state the tool holds. Nothing is deposited.

The tool drives segments from the loop engine's own control loop - one
segment to the next sample boundary, or to the `--stop-after-steps`
point when that comes first - so the checkpoints, the records and the
chain are the loop engine's by construction. A segment is shorter than
that when one of two limits says so, and where segments end reaches no
result:

- **the loader's.** An image whose worst case could execute more than
  2^40 instructions is refused (docs/SEQUENCER.md, "What the loader
  refuses"), and a trip count is 32 bits. The tool multiplies its own
  image out the way the loader does and runs a longer interval as
  several segments, each at most that long.
- **the checkpoint's.** While `--checkpoint` is being written, a segment
  is sized to END when the next checkpoint is due: the largest power of
  two of steps that fits the time left before then, at the rate the
  previous segment ran. The first segment of a run is one step, which
  measures the rate. A checkpoint is written at the first segment end
  after an interval has passed - so at a steady rate within a step of
  the interval, which is where the loop engine, reading the clock after
  every step, writes its own. An interval is therefore covered by a few
  segments of decreasing powers of two (a binary decomposition of it,
  at most `log2` of its steps plus one), the same few from one interval
  to the next. The image for a length is built and loaded once: the
  engine keeps the last eight it used (a program handle carries its own
  image and every run takes it from there, so several may be live; a
  remote device's server keeps one, and reloads it when the lengths
  alternate).
  With one kept (c8a7d97, 2026-09-25), every segment inside a sample
  interval rebuilt and reloaded its image - 32 loads for 32 runs in the
  gate's steady-clock run, 58 for 58 in a real-clock one (verifier-V6);
  with eight, that steady-clock run loads 5, and a real-clock outer
  yoshida4 run of 55 segments here loaded 8. The report says `N runs
  of M images` (and the CSV, `seg_loads`).

  Two earlier sizings were wrong. Before 2026-09-25 one segment was a
  whole sample interval, and an interruption lost all of it. Earlier on
  2026-09-25 a segment was sized to fit a WHOLE interval at the last
  rate: it ran half to all of one, so the interval had usually passed
  only after the second, and checkpoints came about two intervals
  apart: 1.87 to 1.94 s at `--checkpoint-interval 1`, where the loop
  engine wrote them 1.01 to 1.03 s apart (verifier-V1, 2026-09-25).

  `--checkpoint-interval 0` asks for a checkpoint after every step, and
  so makes every segment one step: a program run per step per batch
  chunk. That costs about what the loop engine costs at 0, some 25
  times a run of whole sample intervals on the software backend, and
  changes no result. Kepler, fp256, 6 members, 6,000 steps sampled every
  1,000, on this desktop on 2026-09-25: 7.49 s and 6,000 runs, against
  0.31 s and 6 runs with no checkpoint and 0.32 s and 7 runs at the
  default interval (the first one step); the loop engine at 0, 6.74 s;
  one chain throughout. The times move with the machine's load:
  verifier-V6, the same afternoon, measured 12.9 to 14.4 s for segments
  at 0 and 12.7 to 13.0 s for the loop engine, the same run counts and
  chain; verifier-V1 measured 11.9 s against 0.42 s on the sizing before
  this one. `--checkpoint-interval` takes a number of seconds, 0 or
  more, and nothing else: until 2026-09-25 "nan" was read as a clock
  that never came due (one-step segments, no checkpoint until the end,
  on both engines), "abc" as 0 and "1s" as 1.

What that buys is everything (1) forbade:

- the outer solar system runs as programs, thirty values a lane;
- a run resumes from a checkpoint either engine wrote, mid sample
  interval;
- any number of samples: a segment deposits nothing, so the tile's 64
  deposit slots bound nothing;
- any sample interval, however long.

The program loads every `q_c` into register `c` on entry and stores it
back on exit. The velocities stay in their slots and are loaded,
updated and stored where the kick touches them, because thirty values
and the kick's temporaries do not fit thirty-two registers together:

    r0 .. r(ncomp-1)   q, one register per component (at most 15)
    r16, r17, r18      d, a pair's separation (outer)
    r19 x = r^2   r20 y   r21 w   r22 e   r23 z   r24 g   r25 t1
    r26                the velocity component being updated

The arithmetic is the loop engine's, instruction for instruction and
operand for operand. The loads and stores are not arithmetic (R4: no
rounding, no flags), so where a value lives cannot reach a result.

**The census**, at binary256 (six Newton passes), read off the image by
the tool and derived independently by the check from the program's
structure:

| problem, scheme | instructions | constants | ALU a lane-step | control codes a lane-step | scratch slots |
|---|---|---|---|---|---|
| kepler, leapfrog | 51 | 4 | 36 | 8 | 4 |
| kepler, yoshida4 | 139 | 8 | 108 | 24 | 4 |
| outer, leapfrog | 633 | 14 | 450 | 150 | 30 |
| outer, yoshida4 | 1,833 | 36 | 1,350 | 450 | 30 |

A quarter of the outer solar system's instruction stream is scratch
traffic. docs/ROADMAP.md ("Control codes do not join the instruction
overlap", atlas-engine's measurement of 2026-09-17) put a control code
at about four arithmetic instructions (0.98 against 3.9 ns); in the
load-then-use pattern this body is made of, the U50 single tile at
145 MHz measured a scratch access between two arithmetic instructions
at about five - 5.2 at binary64, 5.1 at binary256 (docs/VALIDATION.md,
2026-09-25). The outer yoshida4 image carries 36 constants and
addresses 30 of them, the highest at index 34, so it uses the indexed
(`kx`) form.

**What holds it**, in `host/tests/orbits_check.py`'s section [6b]:

- byte-identical checkpoints and records against the host loop on both
  problems and both schemes at binary256, and on one configuration at
  each of binary32, binary64 and binary128 - the Newton pass count is
  the format's, so a pass-count error shows nowhere else - where the
  operation count the census implies must also equal the loop engine's
  own count, a second statement of the census that shares none of its
  derivation;
- the lengths real runs use, not only the short segments above: the
  tool's default kepler run (binary256, a segment a period, 1,024
  steps), one 100,000-step sample interval at binary64 run as two
  segments, the first step (which times the rate) and 99,999 - past
  2^16 steps, where a trip count kept to 16 bits would wrap - and each
  binary256 configuration with its intervals split at a loader limit
  lowered to 13 steps (`CFT_ORBITS_SEGMENT_LIMIT`, below), since the
  real limit is hours of work away; each against the host loop byte
  for byte, the run count showing the segments were that long, or
  split that way;
- the same bytes after `--stop-after-steps` 1, 13, 95, 96 and 97 - 95
  to 97 straddle a sample boundary - with each checkpoint at the step
  asked for;
- batch 8, 3, 1 and 10^12 byte-identical;
- the outer solar system stopped every 37 steps and resumed by segments
  alone, and by the two engines in turn, ending on the uninterrupted
  loop engine's bytes;
- where checkpoints fall: under a steady clock
  (`CFT_ORBITS_VIRTUAL_CLOCK`, below), segments write theirs at exactly
  the host loop's steps - one interval apart - with sample intervals
  of ten checkpoint intervals, of 1.27 and of 0.1, in at most eight
  segments an interval and one more a sample, and fewer images than
  runs - with no sample boundary between, exactly one image a length -
  and each ends on the host loop's last checkpoint byte for byte. The
  1.27 regime needs more images than the cache keeps (17 loads for 43
  runs, eight slots), so it evicts, and an image run for the wrong
  length ends elsewhere, where checkpoints fall or not (a slot that
  kept its old key over a new image was caught before only where a
  real-clock run happened to meet it: verifier-V6's V6E);
- on the real clock, a run with a 30,000-step sample interval and
  `--checkpoint-interval 1`, watched until its first checkpoint appears
  (a minute at most, however busy the machine), holds a step part way
  through the interval;
- a killed run's records, on both engines, each resumed by the other:
  killed as its first checkpoint appears, with the file exactly as long
  as the checkpoint says, and killed once the file has grown 8 KB past
  it, ahead of the checkpoint and usually in half a line - each must
  finish on the uninterrupted run's checkpoint and records, byte for
  byte; and, laid out exactly rather than by a kill, a file ahead of its
  checkpoint resumes to the same bytes, while one cut a byte short, one
  with a byte changed, a LONGER file whose first `recbytes` bytes are
  wrong (the whole run's with a byte changed before `recbytes`, a CRLF
  copy, another run's), none at all, a version-1 checkpoint and one
  without `recbytes` are each refused by name with both files left as
  they were ("The checkpoint format", below); so is the right file that
  this process may not read - held open by another process with no
  sharing on Windows, its read permission taken away on POSIX (not as
  root, which no permission stops: there the case prints `SKIP`) -
  named for that, not for being short, and resumed once it can be
  read; a checkpoint is the same file with `--records` and without, and
  a relay that never passes `--records` ends on the checkpoint of the
  run that did;
- `--records` and `--checkpoint` naming one file, refused by name and
  before a byte of either is cut: the same path, and the checkpoint's
  `.tmp`, as written - with nothing created; the checkpoint under
  another spelling, and its `.tmp` under another spelling, with a
  checkpoint already there left as it was; and on `--resume`;
- the order a checkpoint and its records reach the disk: a run that
  ends as a kill would the instant its first, or its fourth, checkpoint
  is renamed into place (`CFT_ORBITS_DIE_AFTER_CHECKPOINT`, below -
  both checkpoints with records waiting in the stdio buffer) leaves the
  records file exactly as long as that checkpoint says, and the other
  engine resumes it to the uninterrupted run - a kill could land there
  only by chance;
- records that are not a file: `--resume --records` naming a pipe, a
  FIFO or a device is refused by name at once, the checkpoint
  untouched - on Windows a named pipe and NUL, on POSIX a FIFO,
  `/dev/stdout` into a pipe and `/dev/null`, each given 60 s so that a
  regression reads as a failure rather than a gate that never ends -
  and a fresh run into a pipe, a named pipe on Windows and a FIFO on
  POSIX, with a checkpoint every step, streams the run's records;
- a pipe the system calls an empty file: under `CFT_ORBITS_SHARE_FIFO`
  (below) the records file says it holds 0 bytes, whatever is written
  to it, and refuses to be cut - what the WSL share makes of a Linux
  FIFO seen from Windows, which the gate does not open (it hung the
  share on 2026-09-25). A fresh run without `--checkpoint` must write
  its records into it as into any file (bc00d8d refused it: the file
  was cut before a record was written, and the cut failed); with a
  checkpoint every step it must stop by name at the first, the refusal
  naming both what the file may be and claiming neither, and write no
  checkpoint;
- a records file the system will not cut - on Windows one another
  process has mapped, on Linux a memfd sealed against shrinking: a
  fresh run is refused by name, the step, the file and the system's
  own reason given, and the file left as it was;
- with no instrument set, a run says nothing on stderr and its clock is
  the wall's: the same 1,024 steps at 1 member and at 16 report times
  at least 4 apart (about 15 measured), where a clock that counted steps
  would report one number for both, logging or not, and each inside its
  process's lifetime - timed with `perf_counter`, the clock the tool
  reads, because Python's `monotonic()` ticks 15.6 ms on Windows and
  measured with it the check failed 12 of 280 times on a correct tool
  (verifier-V6; 8 of 280 here, and 0 of the same 280 with
  `perf_counter`). The 1-member time is the least of three runs: a
  busy moment only lengthens a run, and one 1-member run of 0.175 s
  against about 0.015 s failed the ratio once in about 340 evaluations
  (verifier-V6). The real loader limit by default is held by the
  100,000-step leg's run count and by `=overlong`;
- the image cache keyed by the whole segment length: a run whose two
  segments are 1 and 65,537 steps - one length in any key cut to 16 bits
  or fewer - runs two images and ends on the host loop's bytes. A key
  cut to 8 bits passed every other leg while a real run's 257-step
  segment ran the 1-step image (verifier-V6's V6G);
- a checkpoint renamed while another process polls it with `stat()` as
  fast as it can: the run finishes on the unpolled run's checkpoint
  ("The checkpoint format", below);
- how long that rename is retried: the checkpoint held open, as a reader
  holds it, while a run renames it after every step - for 0.5 s, which
  the run must outlast and end on the unheld run's bytes, and for 5 s,
  which on Windows must end the run by name 1 to 5 s into the hold
  (1.50 to 1.54 s in over a hundred held runs, at the desktop's own
  load) and leave it resumable, by the other engine, to the unheld
  run's checkpoint and records. The 0.5 s hold asks of the gate itself
  that it let go within about 1 s of the tool's first refused rename,
  or the run gives up first; that is stated, not measured - the machine
  is not loaded to try it. A POSIX rename over an open file is not
  refused, and there both holds must leave the run untroubled;
- a second writer: 1 MiB appended to the records by another process as
  a run's first checkpoint appears must stop the run by name at its
  next one - the file is then longer than the records it counted - and
  the checkpoint it leaves must resume, on the other engine, to the
  uninterrupted run's checkpoint and records, the stranger's bytes cut
  away. With the check removed the run finished, exit 0, on a file that
  was not its records (verifier-V6);
- a sample interval longer than the longest segment the loader takes
  is run as several segments rather than being refused, each run's
  first segment at exactly that limit: the 2^40-instruction ceiling for
  outer/yoshida4, where one step more is refused by the loader, and the
  2^32-1 trip count for kepler/leapfrog, where one step more is refused
  by this tool's own trip-count check;
- the census above against the program's structure;
- `python/cft_golden` on the image the tool writes (`--segment-dump
  DIR`): its executor returns the library's scratch-out exactly, and
  its assembler reads the image back to the same bytes with no
  instruction marked `.kx`. The round trip alone would pass any legal
  choice of the indexed form - the disassembler writes a `kx` the
  assembler would not have chosen as `.kx`, and the assembler honours
  it - so it is the absence of the marker that holds the tool to the
  assembler's rule (docs/PROGRAMS.md): indexed exactly where a constant
  index is 16 or more.

The controls, each run every time and each required to fail.
`CFT_ORBITS_NEGATIVE_CONTROL` makes the tool wrong in one named way:

- `transpose` packs `v_0` and `v_1` into each other's slots - the
  lane-major transposition bug the comparisons exist to catch - and
  the engine comparison (kepler, leapfrog), the outer yoshida4 run
  split at 13 steps, the relay, the default kepler run and the
  100,000-step interval each fail under it;
- `late-stop` runs a segment one step past `--stop-after-steps`, and
  the stop comparison fails at 13, 95 and 97 - at 1 the run's first
  segment is one step anyway, and 96 is a sample boundary, which ends a
  segment of its own accord. What catches a late stop is the clause
  that each checkpoint is at the step asked for, which the stop
  comparison carries beside the bytes;
- `uncapped` restores the sizing before 2026-09-25, a segment a sample
  interval: under the steady clock segments then checkpoint elsewhere
  than the host loop, and on the real clock the run has written no
  checkpoint in three times as long as the real one took (and at least
  3 s);
- `append` resumes as the tool did before 2026-09-25, appending to
  `--records` without checking or cutting it, and the resumed records
  then differ from the uninterrupted run's - after each kill that left
  the file ahead of its checkpoint, and on the file laid out exactly;
- `flush-late` hands the records to the system just after the
  checkpoint that counts them is renamed into place instead of before,
  and a run that ends at that rename then leaves the file BEHIND the
  checkpoint (0 of 427 bytes, 1,143 of 1,858), which the resume must
  refuse;
- `overlong` takes the loader's limit one step too long, and both runs
  at the limit are then refused at once;
- `zero-r2` zeroes every `r^2` in the image, and the run must end on
  the flag certificate (exit 3), so a segment whose flags were dropped
  cannot pass.

Beside them, the golden executor on the image with one bit of one
constant changed must disagree with the library's scratch-out, and a
reserved bit set in the image must be refused by both the golden loader
and the disassembler.

Eleven checks carry no control of their own. The census was watched
failing under two planted miscounts (docs/VALIDATION.md, 2026-09-25);
the batch comparison's chunk boundary is crossed, with the transpose
control, by the engine comparison at batch 3 of 5; the three narrower
formats were watched failing under a Newton pass count fixed at
binary256's (the same entry), and binary64 carries the transpose
control in the 100,000-step leg. The relay without `--records`, the run
with no instrument set, the image cache's key, the rename under a
`stat()` poll and the rename held open (Windows), the second writer,
the fresh run into a pipe, and the fresh run into a file that says it
holds 0 bytes were watched failing under planted defects of their own
(below). The refusals are their own kind: each is a case that must be
refused by name, which a tool that accepted it would fail.

Every leg above but one was also watched failing under a planted
defect of its own, each built into a copy of this tool and run through
the whole gate, on 2026-09-25 (each one's run is in the round's ledger,
`Data/runs/2026-09-25-ode-round/ledger/`, gitignored; docs/VALIDATION.md
summarizes them): a
stale image, a transposed or misread operand, a Newton pass count, a
late stop, a dropped flag word, buffers sized by the batch, the
loader's limit a step long and its 32-bit cap removed, the time cap
off; a trip count kept to 16 bits, a segment over 128 steps one step
short, the loader-limit split a step behind, segments sized to a whole
interval, to two and to four, the rate never measured, an encoder that
chooses `kx` for every constant; and, for the records, a resume that
does not check, cut or hash-check the file, records not handed over
before a checkpoint, and the stream miscounted or counted only when
written. After verifier-V6 (the same day) also: the records handed over
after the rename instead of before, the prefix hash checked only for a
file exactly `recbytes` long, the test clock left on, `recbytes` lost on
a resume without `--records`, a pipe read on resume (which hangs, and
the leg's 60 s turns into a failure), one image cached instead of
eight, the rename not retried (on Windows), and "nan" read as an
interval. And after verifier-V6's second report: the cache keyed on 8
bits of the length, and on 16; the rename retried for about 60 ms, for
0.5 s, and without end (Windows); a file that cannot be opened named as
missing; `--records` and `--checkpoint` as one file not checked, and
checked only as written. And after its third: the retry's deadline at
60 ms, at 0.75 s, at 6 s, and none (Windows); the records file cut
before it is asked which file it is, and never cut; the one-file check
without its strings, without the `.tmp`'s identity, and asked of the
path before the open (which takes a named pipe's one instance); an
evicted cache slot that keeps its old key over a new image; and the
length check at a checkpoint removed. And after its fourth: a file that
says it is empty cut all the same (bc00d8d's), the refusal for a file
that says 0 bytes put back to its old words, `CFT_ORBITS_SHARE_FIFO`
inert and its value unchecked, and a failed cut and a failed open
named as before ("cannot write the records file"). The exception is
the golden comparison's executor half. It runs the golden executor and
the library on the same image by design, so what it can see is a
library that runs an image differently from the reference; a wrong
image is the engine comparisons' to catch, and no planted defect of
this tool has been seen to fail it.

Two planted defects pass the gate. The length bound on a resume's
read removed: on a regular file the read then finds the same shortness
and refuses it the same way. What the bound is for is a file that says
it is shorter than it reads - a Linux FIFO seen through the WSL share,
where without the bound the resume read the FIFO and waited for ever
(30 s bound), and on Linux a file like `/proc/self/status`, which says
0 bytes and reads about 1,100: refused as holding 0 bytes, unread, and
without the bound read through (both measured by hand). Windows offers
the gate no such file, and a check only Linux could make would print
`SKIP` in every Windows gate run, so it stays measured by hand. And
d56ecbe's retry, sixty tries rather than a deadline: on a desktop at
its ordinary load both give up about 1.5 s into a hold, and the
difference - how far a busy scheduler stretches the retry - shows only
while something else holds the CPU, which the gate does not arrange
(the machine is not loaded on purpose). The code holds it: the retry
ends on success, on an error it does not retry, or on the clock - on no
count.

**Four test instruments** make reachable what otherwise is not. Unlike
the controls, which make the tool wrong, they change only what the tool
meets - a lower loader limit, a steady clock, a kill at an instant, a
file as the WSL share presents a FIFO - and the checks that use them
hold what it does then. Each is off unless set (a leg holds that too),
refused by name when malformed or set where it does not apply, and
announced on stderr:

- `CFT_ORBITS_SEGMENT_LIMIT=N` (segments): the loader is taken to accept
  at most N steps a segment, so the split its real limit makes - at
  2^32-1 steps or 2^40 instructions - is reached in seconds;
- `CFT_ORBITS_VIRTUAL_CLOCK=S` (loop and segments): the clock the tool
  reads advances S seconds for every step and for nothing else, and
  each checkpoint is logged on stderr as it is written - a perfectly
  steady rate, so where checkpoints fall is a fact the check predicts
  rather than a measurement of the machine's load. The run's own
  report then gives that clock's time and throughput, not the wall's;
- `CFT_ORBITS_DIE_AFTER_CHECKPOINT=N` (loop and segments): the process
  ends as a kill would - exit 9, no buffered output flushed - the
  moment its N-th checkpoint is renamed into place: one line to stderr
  saying so, and nothing else the run does comes after the rename. On
  Windows that is TerminateProcess: `_exit()` goes through ExitProcess,
  and msvcrt flushes every stream as it unloads, which a kill does not
  (measured: under `flush-late` the records still reached the file);
- `CFT_ORBITS_SHARE_FIFO=1` (any engine, with `--records`): the records
  file is taken to be what the WSL share makes of a Linux FIFO seen
  from Windows - a regular file that says it holds 0 bytes, however
  much is written to it, and refuses to be cut (Windows error 87, "the
  parameter is incorrect", as the share gives it; EINVAL on POSIX). The
  records still go into the real file. The share's own FIFOs cannot be
  a gate's: an open of one that finds no peer leaves a thread of the
  distro's 9P server blocked, and enough of them hung the share on
  2026-09-25 ("Limits of those refusals", below).

**What it does not do.** `--rsqrt exact`, for the reason in (2): it is
refused by name. And `--engine program` stays exactly as it was: the
browser demos rebuild its image instruction for instruction and
`bindings/wasm/verify_demos.mjs` records that image's digest as taken
from this tool (docs/DEMOS.md), so the new engine is an addition rather
than a replacement.

### As a host loop

`--engine loop` issues the same step as `cft_run` / `cft_sqrt` /
`cft_div` passes over the ensemble. It runs both problems, both
schemes and both routes, and it is the reference the program engine is
held to. Per element-step:

| problem, route | elementwise issues per substep | composed div/sqrt |
|---|---|---|
| kepler, exact | 9 | 2 |
| kepler, newton | 36 (at p = 237) | 0 |
| outer, exact | **15 per body pair** + 30 for the two drifts | **2 per body pair** |
| outer, newton | **42 per body pair** (at p = 237) + 30 | 0 |

with 10 pairs for five bodies, and one substep for `--scheme
leapfrog`, three for `--scheme yoshida4`. So the outer solar system at
`--rsqrt exact` costs 180 elementwise issues and 20 composed
operations per element-step, and 300 years at a 10-day step over 8
members is 10,957 x 8 x 200 = 1.75e7 library element-operations plus
the per-sample invariants - which is what the measured 148,146 calls
for the 730-step run corresponds to.

Under `--problem kepler --rsqrt newton` the two engines produce
byte-identical records, byte-identical checkpoints and the same chain.
What the program buys on the software backend, where there is no bus
to save, is **1.20x** and, more to the point, **284 library calls
instead of 295,195** for the same 8,192 steps over 16 members. On a
device that ratio is the whole argument of docs/SEQUENCER.md.

One caveat travels with that row onto a device. The program deposits
four values a sample, for the whole run in one call, and a tile holds
64 deposit slots a lane, which the tool reads from
`cft_caps.max_deposits` rather than from a literal since 2026-09-07
(docs/SEQUENCER.md) - so a run there records at most 15 samples. `--periods 16` sampled once a period, which is
both the default and the benchmark's setting, is 16 samples and is
refused by name; `--sample-every 1024` or `--periods 15` fits, and
the bits of every recorded sample are the same either way.

---

## Flags: which are expected, which are certificates

**Nothing here is exact.** Every drift, every kick, every refinement
pass rounds, so `CFT_FLAG_INEXACT` is EXPECTED on essentially every
call and carries no information at all. Saying so is the point: a tool
that treated inexact as a fault on this workload would be lying about
it, and one that never mentioned flags would be hiding the four that
do mean something.

The certificates are the other four, and each of them has a physical
meaning here:

| flag | what it would mean |
|---|---|
| `INVALID` | a NaN reached the arithmetic |
| `DIVBYZERO` | `r` reached zero - a collision |
| `OVERFLOW` | the integration went unstable |
| `UNDERFLOW` | a value fell into the subnormals, which for state of order 1 (Kepler) or 1e-3..1e2 (outer) cannot happen while the integration is sane |

Every call's `flags_out` is read and every one of those four stops the
run with exit 3, naming the operation. They cost nothing, because the
library computes them anyway.

**Where the Newton route's certificate is thinner.** `--rsqrt newton`
starts from the reciprocal-square-root seed, which is quiet by design
(`python/cft_golden/softfloat.py`, `rsqrt_seed`: the INVALID for a
negative operand belongs to the contract-level square root, not to its
scaffolding). A NEGATIVE `r^2` - fault B2 below - therefore becomes a
quiet NaN that the multiplies and fused multiply-adds after it carry
without raising anything, and the run finishes with exit 0 and a NaN
state on every engine that takes that route; `--engine segments` takes
no other. The run's own report then shows `dH=nan`, and of the gates
the 300-digit agreement and the energy drift fail on it, while the
angular-momentum certificate does not (a NaN state conserves
everything, B1). A ZERO `r^2` is still caught: the seed returns +inf,
the first Newton multiply meets zero times infinity and raises INVALID
- the planted fault the segments gate uses (`zero-r2`, [6b]).

Beside them the tool uses ABI 0.7's status word (754-2019 7.1) as a
second, free cross-check. Building the constants and the initial
condition deliberately rounds; the tool lowers the word once with
`cft_lower_flags` when setup is done - 7.1's "lowered only at the
user's request" - and never touches it again. The report prints the
word beside the union of the calls' `flags_out`, and they must agree:

```
  flags seen    0x10  (inexact is EXPECTED here and means nothing;
                 the other four are certificates and are checked on every call)
  status word   0x10 (agrees with the union above)
```

The certificates that are **not** flags are the ones that carry the
result: the angular-momentum bound above, agreement with the
300-digit run, and bit identity between engines and across batch
sizes.

---

## The checkpoint format

A line-oriented ASCII file with LF endings, written to `<path>.tmp`,
flushed, closed and then **renamed over** the target
(`MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` on Windows, `rename()`
elsewhere), so a reader never sees a half-written one.

It carries every number that describes a **result** and nothing that
describes the **machine**: no batch size, no engine, no timing. That
is the whole design rule and it is what lets two runs with different
batch sizes end on byte-identical files.

```
cft-orbits-checkpoint 2
format fp256
problem kepler                the run's identity - a checkpoint from a
scheme leapfrog               different problem, scheme, format, route,
rsqrt exact                   ensemble size, step count, sample interval
members 8                     or step size is REFUSED, not adapted
spread 1
bodies 1
dims 2
h 6.13592315...e-3            the step size, exactly
steps 192
stride 96
samples 2
at 37 0                       steps done, samples emitted
chain 3f0e...                 SHA-256 chain over the records so far
recbytes 6857                 the bytes of those records, as --records writes them
state 0 <q...> <v...>         one line per ensemble member, exact decimal
state 1 ...
inv 0 <H0> <dHmax> <L0> <dLmax>     the invariants and their extremes
inv 1 ...
end
```

Every value is an exact decimal from `cft_to_decimal_char` with
`digits = 0` - 5.12.2's exact conversion - and is read back by
`cft_from_decimal_char`, which the tool requires to be exact. What the
library writes, the library reads back, so a checkpoint round trip
cannot lose a bit.

**Version 2** (2026-09-25) added `recbytes`, the length of the record
stream the chain covers: the bytes `--records` has written by then. It
is counted whether or not `--records` is open, so a run with it and a
run without end on the same file - an option is not a result, and the
gate checks it. A version-1 file is refused by its first line, as any
other version is, and so is a version-2 file without `recbytes`.
Holding a version-1 checkpoint of a run you want to finish: finish it
with a build from before this change (4ecaf24 or earlier, whose
checkpoints are version 1), or start the run again with this one. The
old build's resume appends to `--records` as it always did, so if that
run was ever killed, its records file is not to be trusted past the
kill - its checkpoint and its chain are.

**Version 3** (2026-09-30) is a certified run's, and only a certified
run writes it: version 2's lines, then the certificate so far, then a
`sum` line over the whole file ("Certified runs", below). Every other
run's checkpoint is version 2, byte for byte as it was. A resume with
`--cert` requires version 3, and one without refuses it, each saying
which version it met.

The checkpoint is **step-granular, not sample-granular**: the ensemble
state is complete after every step, so a timed checkpoint may fall
between any two of them and `--resume` picks up part way through a
sample interval. That is what makes an interruption cost about one
`--checkpoint-interval` of work however coarse the sampling is. The
loop engine reads the clock after every step, so it writes a checkpoint
at the step an interval has passed. `--engine segments` can only write
one between segments, so it sizes each segment to end when the next
checkpoint is due, at the rate the one before it ran ("As resumable
segments" above): at a steady rate it writes its checkpoints at the
loop engine's steps, which the gate holds step for step under a steady
test clock. "About" is still the honest word on a real clock: a
segment that runs slower than the one before it overruns the interval
by the difference.

**Records after an interruption.** Records go through stdio and a
checkpoint is written between samples, so a killed run leaves the
records file out of step with the checkpoint on disk. Before 2026-09-25
nothing reconciled the two: the file could be behind the checkpoint
(records it accounted for still in the stdio buffer) or ahead of it
(records written since), usually ending in half a line, and `--resume`
appended from the checkpoint's sample - so the resumed file was not
the run's and no longer hashed to its chain, on either engine
(verifier-V1: 7 kills of 7). Now:

- every record written so far is handed to the system, and the file's
  length checked against `recbytes`, **before** the checkpoint that
  counts them is written - so a kill leaves the file at or ahead of the
  checkpoint on disk, never behind it;
- `--resume` with `--records` requires the file's first `recbytes`
  bytes to hash to the checkpoint's `chain`, cuts away everything after
  them, and then appends - so a killed and resumed run's records are the
  uninterrupted run's, byte for byte, on either engine;
- a file shorter than `recbytes`, one whose first `recbytes` bytes do
  not hash to the chain - however long it is - or none at all, is
  refused by name, and neither file is touched: it is not this run's
  records - resume with the file the run wrote, or without `--records`.
  The length is the one the open file gives, taken before a byte is
  read, and nothing past it is read;
- a file that cannot be opened to be read back - held open with no
  sharing or locked by another process, or unreadable to this one - is
  refused as that, with the reason the system gives, not as short
  (c8a7d97 and 589cbc1 said "holds 0 bytes ... cut short" of the right
  records locked by another process: verifier-V6); nothing is changed,
  and the resume goes through once the file can be read;
- so is a `--records` path that is not a regular file - a pipe, a
  FIFO, a device, a directory - before anything is read or written: a
  resume reads the records back and cuts them, which a stream cannot
  do. c8a7d97 (2026-09-25) read it, and on a pipe nothing wrote it
  waited for ever with no message (verifier-V6: `--records >(gzip >
  part2.gz)`, `/dev/stdout` into a pipe, a FIFO; on Windows a named
  pipe, killed after 20 s here). Resume into a regular file and pass it
  on from there. POSIX asks `stat()`, which does not open a FIFO; Windows'
  `_stat64` calls NUL, CON and a named pipe regular files, so the path
  is opened and its type asked, which for a named pipe connects to an
  instance and hangs up - a server sees a client come and go. A fresh
  run into a pipe streams its records: a named pipe or a FIFO, with
  `--checkpoint` or without; a Linux FIFO seen from Windows through the
  WSL share without it - with it, only until the first checkpoint that
  counts a record, where the run is stopped by name ("A fresh run into
  a FIFO through the share", below).
- a fresh run's records file is opened for writing, and cut to nothing
  unless it says it is empty already. One the system will not open, or
  will not cut, is refused by name with the step and the system's own
  reason - "could not open the records file ... (The system cannot
  find the path specified, Windows error 3)", "could not empty the
  records file ... (The requested operation cannot be performed on a
  file with a user-mapped section open, Windows error 1224)" - and
  left as it was; bc00d8d said only "cannot write the records file"
  (verifier-V6). A hidden file (Windows), which `"wb"`'s CREATE_ALWAYS
  refuses and which d56ecbe so could not write, is written like any
  other (verifier-V6, and measured here: the run's records). The file's
  own report of its size is trusted: on a filesystem that reported a
  non-empty file as empty, a fresh run without `--checkpoint` would
  leave the old tail after its records and exit 0. None has been found -
  on this desktop, through the WSL share or in WSL (verifier-V6,
  2026-09-28).
- `--records` and `--checkpoint` naming one file are refused by name at
  the start, fresh or resumed, before a byte of either file is cut: the
  same path, or the checkpoint's `.tmp`, as written, before anything is
  opened; and one file under two spellings, told by the file's own
  identity (its volume and index on Windows, its device and inode on
  POSIX). On `--resume` that is asked of the path once it is known to be
  a regular file. On a fresh run it is asked of the records file itself,
  opened for writing but not yet cut, which is cut only once it is
  known to be neither the checkpoint nor its `.tmp` - the path is
  never opened a second time to ask, since on Windows that opens it, and
  for a named pipe a fresh run writes into, an open is a connection
  (above). So a checkpoint already there is left as it was, under every
  spelling tried (measured, Windows: `dir\.\name`, upper case, a
  relative path, a hard link; Linux: `dir/./name`, a relative path, a
  hard link, a symlink). d56ecbe opened it as `"wb"` opens it, cut
  first and asked after, so its refusal came after the checkpoint was
  emptied (a 1,224-byte checkpoint left at 0, on both; verifier-V6 too).
  The one trace a refusal can leave: a spelling of a file that is not
  there yet is created by the open before it can be told apart, and is
  left empty - nothing is lost. Before the refusal existed at all, the
  checkpoint was written beside its path and renamed over it at every
  interval, so on POSIX the records went on into an unlinked file and
  were lost with exit 0, and on Windows the run died 1.7 s in blaming
  "another process" (verifier-V6; pre-existing).

**Limits of those refusals.** A Linux FIFO or device seen from Windows
through the WSL share (`\\wsl.localhost\...`) is not seen as one: the
share gives Windows an empty regular file. `/dev/null`, and a FIFO a
writer holds open, are refused at once as holding 0 bytes, before a
byte is read (0.01 to 0.02 s: a silent writer holding it open, one
waiting to open it, one sending the right records - each twice, on a
share restarted clean). 589cbc1 read such a FIFO: with a silent writer
it waited for ever (verifier-V6; here killed after 30 s), with one
sending the right records it failed after 10.04 s ("could not cut").
A FIFO no writer holds open - a reader waiting on it, as `>(gzip)`
leaves one, or nothing at all - costs the share's own 10 s before the
open fails ("could not be opened ... Invalid argument", 10.01 to 10.03
s). None of these changes a file, and the checkpoint is left as it
was. They do change the share: an open of a FIFO through it that finds
no peer leaves a thread of the distro's 9P server blocked, opening the
FIFO (measured: one thread in `wait_for_partner` after each writerless
case, none once the FIFO was opened from Linux). The FIFO opened from
the Linux side, for reading and writing at once (`exec 3<>fifo`), sets
the thread free; the FIFO deleted first leaves it blocked for good, and
enough such threads hang the share for every Windows process until the
distro restarts (verifier-V6, 2026-09-25: twelve, five of them from the
FIFO tests behind this section, whose FIFOs were deleted unopened). So
whoever tests a FIFO through the share opens it from Linux, both ways,
before deleting it, and then counts the server's blocked threads.

**A fresh run into a FIFO through the share.** A run started on Windows
with `--records` naming a Linux FIFO through the share, a Linux reader
waiting on it, streams its records to the reader: Windows is told the
FIFO is an empty regular file, and a file that says it is empty is not
cut. bc00d8d cut it all the same, the share refused the cut ("the
parameter is incorrect", Windows error 87), and the run was refused at
once as "cannot write the records file", where d56ecbe had streamed
(verifier-V6, 2026-09-26; measured again here: the reader got 0 of the
run's 11,798 bytes, exit 2 - now all 11,798, exit 0). With
`--checkpoint` the share's length stays 0 however much is written, so
the length check before the first checkpoint that counts a record
stops the run, exit 2, with no checkpoint written: "the records file
says it holds 0 bytes, where 11798 have been written to it: something
else cut it, or it is a pipe the system presents as an empty file (the
WSL share presents a Linux FIFO so), which has no length to hold a
checkpoint to - with --checkpoint, --records must name a file". In a
run shorter than its interval that checkpoint is the last, and the
reader has had every record first (measured, at the default interval);
with one every step it is the first, 427 bytes in. The tool cannot
tell such a pipe from a file something else cut, and the words claim
neither - d56ecbe's, "something else wrote to it or cut it", was a
guess there. The gate reaches all this through `CFT_ORBITS_SHARE_FIFO`
(above), never through the share; the share itself was measured by
hand, under the discipline above (a Linux reader waiting, each FIFO
opened `O_RDWR` from Linux before it was deleted, the server's blocked
threads counted - none, throughout).

The length check at each checkpoint catches a flush left out and a
record miscounted. Of two processes writing the same file it stops only
the one that LAGS - the file is as long as the leader has written - and
the one ahead finishes, exit 0, unaware (verifier-V6: 3 of 3); the
gate holds the first half (a second writer, above). It does not catch
a file another process cuts short: the next flush writes past the cut,
leaving a hole of zeros exactly as long as the count says
(verifier-V6). A failed write is `ferror()`'s to catch, before the
length is looked at.

On Windows another process that holds the checkpoint open for a
moment (a virus scanner, a sync agent, anything that `stat()`s it)
makes the rename over it fail - with ERROR_ACCESS_DENIED, as measured
for a `stat()`-style open and for readers (verifier-V6); a sharing
violation is retried the same way. Until 2026-09-25 that ended the run
("the checkpoint could not be renamed into place": verifier-V6, 8 runs
of 8 under a tight `os.stat` poll, and here 6 of 6 within about 200
`stat` calls). The rename is now retried - ten times at once, then 20
ms apart - until 1.5 s have passed on the clock since it first failed,
and then the run gives up by name, leaving the last checkpoint and a
resumable run. A held run gave up 1.50 to 1.54 s into the hold (over
a hundred held runs in the gate, at the desktop's own load). The bound
is the clock, not a count: d56ecbe tried sixty times - ten, then fifty
20 ms sleeps - which took as long as the scheduler made each sleep:
1.55 to 1.57 s on a quiet desktop (verifier-V6), but with a game
holding the CPU at 100% as late as 4.88 s, and once not within a 5 s
hold at all (verifier-V6, 2026-09-25). On the clock a busy scheduler
adds one more sleep past the deadline - stretched as it stretches that
one - and one more try, where it stretched all sixty. A run
checkpointing after every step (1,500 steps), polled by a Python thread
as fast as it can (11,000 to 18,000 `stat` calls), finished 6 of 6 on
the unpolled run's checkpoint, in 1.7 to 2.5 s against 1.5 to 1.9 s
unpolled.

What that covers is the process ending - killed, crashed, stopped. A
machine that loses power can lose what the operating system had not yet
written to the disk; nothing here asks it to (no `fsync`).

### The hash chain

    chain_0     = 32 zero bytes
    chain_(i+1) = SHA-256( chain_i || record_i || "\n" )

over records in **(sample, member) order**, where a record is

    <sample> <step> <member> <q...> <v...> <H> <L...>

with every value an exact decimal. That order is fixed by construction
and never by the schedule, which is what makes the chain independent
of the batch size, of the engine and of where a run was interrupted.
`--records PATH` writes exactly those lines, so anything can recompute
the chain; `orbits_check.py` does, with `hashlib`.

SHA-256's eight initial words and sixty-four round constants are
**derived** in `host/src/sha256.c` - the library's one copy since
2026-09-08, lifted from `host/tools/collatz.c` - from the square and
cube roots of the first 64 primes by integer binary search in 128-bit
arithmetic, rather than typed in. The `hashlib` comparison is what
proves the derivation right.

---

## Certified runs

Since 2026-09-30 a run on the Newton route can be certified: it writes a
version-1 certificate ([CERTIFICATES.md](CERTIFICATES.md)), a statement
of what ran that an auditor checks by re-running its segments on an
implementation the producer does not control. It is the certificate
plan's step 6 ([ROADMAP.md](ROADMAP.md), "Segments, certificates and
the audit tool").

```
./cft-orbits --problem kepler --format fp64 --members 4 --periods 2 \
             --steps-per-period 64 --sample-every 16 \
             --engine segments --rsqrt newton \
             --cert run.cert --cert-states run.states --cert-open
```

`--cert-salt SALT` in place of `--cert-open` makes it keyed: every hash
an HMAC under a file of exactly 32 random bytes ("Keyed or open").

**What the certificate says.** One run, `main`:
- its image is the one `seg_build` makes for the STRIDE. The tool builds
  and loads it before anything runs, whatever lengths the engine then
  runs. Its constants ride in it and it takes no bank, so its
  `program-image` and `program-digest` are one digest;
- `lanes` is `--members`, lane i member i; `steps` is the stride; the
  three streams are +0; `parameters 0`;
- a segment for each sample interval: the hashes of the states it
  started and ended on, its flag word and its STATUS;
- `accuracy 0`, or with `--cert-accuracy angular-momentum-drift` the
  angular momentum's drift, exact ("Accuracy", below);
- its identity lines are the library's, as `cft-segrun` writes them. The
  certificate's encoding is `host/tools/cert_write.h`, taken from
  cft-segrun's own.
A STATE is the lane-major scratch block the image reads: member m's
slots in order, slot c `q_c` and slot `ncomp + c` `v_c`, each element
format-width and little-endian. `--cert-states DIR` is a directory the
run makes new. It holds the image, `run-0.cftp`, and every boundary's
state, `run-0-boundary-<b>.bin`, written as the run reaches it -
boundary 0 is setup's ensemble, the records' sample 0. They are the
files `cft-audit --states` and `cert.audit` take:

```
cft-audit --cert run.cert --states run.states --run 0 --image run.states/run-0.cftp
```

**One interval, one segment.** The engine runs an interval as one or
more shorter segments - the loader's limit and the checkpoint clock cut
it ("As resumable segments") - each in batch chunks. An audit re-runs
it whole, one run of the stride's image over every lane. The two agree
bit for bit, flag word and STATUS included, because:
- a step hands the next nothing but the scratch block and the `q`
  registers, which the image loads from and stores to their own slots,
  and a load or a store rounds nothing and raises nothing;
- the image for k steps differs from the stride's in its trip count
  alone;
- a batch chunk is a block of lanes, which the page already takes as the
  dense run exactly ("The chain"): end states in lane order, flag words
  and STATUS OR'd.
So an interval's word is the OR of every run and chunk inside it,
apart from `FLAGS_SEEN`, which the invariants' host calls reach too.
Measured before it was built (the steps-5-and-6 round's ledger, S3,
2026-09-30):
- the disassembly of four images: no register a stream sets is read
  before the program writes it, and the only registers a step hands the
  next are the `q`s;
- images for two lengths differ in one byte, the trip count;
- in the golden model, nine cuts of two strides end on the whole
  interval, every piece raising 16;
- the traced engine, cut by a lowered loader limit and by the steady
  clock, at batch 1 to 4: `cert.run_segment` of the stride's image, from
  each of the engine's boundaries, ended on the next with the engine's
  OR'd word, in all 12 intervals of 7 configurations.

**Stream a.** An ordinary segments run hands `q_0` as stream a, which
the first `LDL` overwrites, since `cft_run_args`' `a` may not be NULL. A
certified run hands a +0 buffer, so that its stream lines state what
ran. Nothing a run computes can differ: no image reads r0, r1 or r2
before writing it. The gate holds a certified run's records to an
ordinary run's, byte for byte.

**Flags and STATUS.** Each is what the library reported: the word is
preset to all ones and held to having been written (`device`) and to
the five sticky flags (`malformed`), as cft-segrun holds it. A certified
run still stops at any flag but inexact (exit 3, "Flags") and at any
STATUS bit, and it needs a device that reads its flags (`device`). So
every segment line of an orbits certificate says `flags 16 status 0`.
The records do not change: no chain moves, and the browser demos' four
orbits chains stand.

**When it is written.** When the run completes, and not before. Every
interval is a whole stride - the tool rounds a run's steps down to whole
strides - and a certificate exists for no other run. So a stop inside an
interval is an interruption, not a short interval, and is not refused:
`--stop-after-steps`, `--stop-after-samples`, a kill, or the flag
certificate each leave no certificate. The run, resumed to its end,
writes the uninterrupted run's bytes. A stop without `--checkpoint` IS
refused (`usage`): that run could never be resumed to write one. The
certificate is written to `CERT.tmp`, which is created before DIR, as
cft-segrun creates its certificate before its states. It is then moved
to CERT without replacing anything, so it is whole or absent, and never
over a file.

**The checkpoint, version 3.** A certified run's checkpoint is version
2's lines, then the certificate so far, then `end` and a `sum`:

```
cft-orbits-checkpoint 3
format fp64                         ... version 2's lines, as they are ...
inv 3 ...
cert mode open                      the certificate's lines from `mode`
cert build-id commit=...            to `segments S`, each prefixed `cert `
...
cert segments 8
cert entries none                   or angular-momentum-drift: what it was started to write
cert boundary 0 <hash>              the initial state's hash
cert segment 0 start <h> end <h> flags 16 status 0     one per closed interval
cert segment 1 start <h> end <h> flags 16 status 0
cert interval flags 16 status 0     the interval in progress, so far
end
sum <hex>                           SHA-256 of every byte before this line
```

The interval's flags so far must travel with it. A stop at an
interval's last step leaves the interval unclosed (the checkpoint says
`at 16 0`), and the resumed process closes it without running a step,
so the whole word is the checkpoint's. A resume that dropped it would
write 0 there, and the negative control `drop-flags` does exactly that.
The reader is strict, where version 2's is as lenient as it was:
- the sum first, so a file cut or changed anywhere is refused before a
  line is read;
- then every line once, in its order, each value in its one spelling;
- version 2's lines held to the run as version 2's reader holds them,
  and to what it only skipped (`spread`, `bodies`, `dims`, `samples`);
- every certificate line through `segments` held to the one this process
  writes;
- the segments' continuity;
- every flag word and STATUS to one this tool could have written (flags
  0 or 16, STATUS 0), since a run stops at any other;
- the interval in progress to no word where it has run no step;
- at a sample boundary, the state lines to that boundary's hash.
Any departure is a sentence and exit 2, as every checkpoint refusal
before it was. A resume refuses the salt, the build and device, and the
states by name (below), and it replaces a boundary file past its
checkpoint's last boundary: one the process before it wrote and was
stopped before a checkpoint counted. A sum proves the bytes are the
writer's, not who the writer was. A checkpoint written to pass it can
hand a resume a state the run never reached mid interval, or move its
step within the interval, and the certificate that follows fails its own
audit (`segment-end`). The fuzz lane measures that (below).

**Refused by name.** Each prints `cft-orbits: refused <name>: <why>`
and exits with the name's code. The page's names where the page has one
for the defect, and cft-segrun's where it has the same condition:

| what | name | exit |
|---|---|---|
| `--cert` with `--engine loop`, the default, or `--engine program`: host calls, or one whole program that deposits | `engine` | 64 |
| `--cert` with `--rsqrt exact`, the default: its divide and square root are host calls between runs, so an interval is no image | `rsqrt-exact` | 64 |
| `--cert-accuracy step-halving`: a half-step run halves the bank's h-slots, and this image carries its constants (the page's `aux-h-slots`) | `step-halving` | 64 |
| `--cert-accuracy wider`: the constants are derived in each format and the Newton passes change with it, so the image one format wider is not this one's widened (the page's `aux-image`; measured, Kepler fp128's image is 47 instructions to fp64's 39, and its two h-constants are not fp64's widened) | `wider` | 64 |
| `--cert-accuracy energy-drift`: the energy goes through 1/r, and version 1 carries a drift only of a polynomial ([CERTIFICATES.md](CERTIFICATES.md), "What version 1 does not do") | `energy-drift` | 64 |
| a stride past the loader's limits: a trip count past 2^32 - 1, or the image past 2^40 instructions, which the loader itself refuses, with its sentence | `program-image` | 4 |
| the options' shape: `--cert` without `--cert-states` or without one salt choice, a certified option without `--cert`, one given twice, a stop without `--checkpoint`, a salt file that cannot be read | `usage` | 64 |
| a salt that is not 32 bytes | `salt-length` | 4 |
| a device that cannot read the sticky flags; a flag word the library left unwritten; a digest that fails | `device` | 69 |
| a flag word past the five sticky flags | `malformed` | 2 |
| an accuracy entry's value, or any value computed on the way, past the width rule | `width` | 3 |
| an accuracy entry that needs a state value that is not finite: a NaN state, which the Newton route can reach without a flag ("Flags") | `accuracy-finite` | 7 |
| `--cert-accuracy` in a build whose bigint is narrower than an exact value needs | `build-width` | 78 |
| memory the certificate needs, found before anything is made | `memory` | 71 |
| CERT there already; a fresh run's DIR there already, or a resumed run's missing; `CERT.tmp` or a file in DIR that cannot be written | `output` | 73 |
| a resume: a keyed run handed `--cert-open`, an open one a salt, or another salt | `salt-missing`, `salt-unexpected`, `salt-commitment` | 4 |
| a resume on another build or device than the certificate names - both identities in the sentence | `identity` | 78 |
| a resume whose DIR does not hold this run's image, or its boundaries so far | `image-digest`, `state-missing`, `state-shape`, `state-hash` | 4 |

`width` has the page's 3, which the flag certificate's exit shares; the
name tells them apart. No name has 9, the kill instrument's. Every
refusal before the run leaves nothing made. One during it, or at its
end, leaves DIR as far as it got and writes no certificate. A resume's
changes nothing of the run's: its checkpoint, its states and its records
are as they were.

**Accuracy.** `--cert-accuracy angular-momentum-drift` asks for the one
entry version 1 can carry for an orbits run. A step-halving or wider
estimate needs an auxiliary run version 1 can relate to this one, and
neither can be one (the table). The energy is not a polynomial in the
state. The angular momentum is, `L = sum over bodies of m_b (q_b x
v_b)`, so its drift is carried exactly as a version-1 `drift` entry
(the lead's decision D6, 2026-09-30):
- one entry for each component, labelled `angular-momentum-x`, `-y` and
  `-z` for the outer system and `angular-momentum-z` alone for the planar
  Kepler problem. Each is a `measurement`, uses run 0, is `scope
  max-lanes` (the most over the members of `|L(final) - L(initial)|`) and
  has its value `exact`;
- component k's terms, body by body: `m_b q_(k+1) v_(k+2)`, then
  `-m_b q_(k+2) v_(k+1)`, the indices mod 3 and the slots the state's.
  Each coefficient is the exact value of the mass the run computed with,
  or 1 for Kepler's test particle, whose L the tool reports as
  `q0 v1 - q1 v0`. So the quantity is the one `invariants()` sums, in
  exact arithmetic;
- its drift is "the angular-momentum certificate" above: both schemes
  conserve L exactly, so what moves it is the arithmetic alone.
Each value is computed by `host/tools/cert_exact.h`, the arithmetic
cft-segrun and cft-audit compute every entry with, from boundary 0 and
the final boundary read back from DIR and held to their hashes. Every
value on the way is held to the width rule and refused `width` by name
past it. On the gate's configurations it was computed, not estimated:
- Kepler fp64: 1.223e-15, a 60-bit numerator over a 110-bit denominator,
  and no value on the way wider than 110 bits;
- the outer system fp256: 1.637e-76, 5.260e-76 and 1.993e-75, numerators
  of 488 to 490 bits over denominators of 739 to 741, and no value on the
  way wider than 741 bits. That is 282 bits inside the rule's 1,023.
The checkpoint says which entries the run was started to write (`cert
entries`), and a resume that asks for others is refused with a sentence:
a certificate states one set.

**What it proves, and what it does not.** An audit proves each interval
it re-runs: from its certified start state, the stride's image ends on
the certified end state with the certified word and STATUS
([CERTIFICATES.md](CERTIFICATES.md), "What an audit proves"). It does
not prove the exact route, which has no image: certifying it needs an
orbit integrator in the golden model, which is not planned. It proves
nothing about the records' invariants or the 300-digit oracle's
comparisons; those are this page's other gates. A certificate made on
the software backend was made by libcft, so there only the golden
auditor is independent of it. No card has certified a run: that is the
lead's leg, later.

**Its gate** is `orbits_check.py`'s section [8], in the `workloads`
stage; `make -C host orbitstest` builds `cft-audit` for it. It certifies
two runs, each keyed (the page's example salt) and open, each with the
angular momentum's drift entries:
- Kepler fp64 leapfrog: 4 members, 8 intervals of 16 steps;
- the outer system fp256 yoshida4: 3 members, 4 intervals of 9 steps -
  its image indexes constants past 15 (`kx`).
For each:
- the golden reader accepts it strictly;
- the golden writer, running every interval WHOLE with `seq.run` from
  boundary 0, and deriving every entry itself (`cert.derive`), writes
  the same bytes. It takes each term from the problem's structure and
  each mass from `--dump-setup`'s exact decimal, never from the
  certificate;
- every boundary file is its chain's state and its sample's records;
- every segment says `flags 16 status 0`;
- both auditors accept it with the same verdict, line for line: in full
  from DIR, in full from boundary 0 alone, and sampled;
- each entry is a `measurement` labelled by its component, and the width
  of every value on the way to it is computed, and reported, within the
  rule ("Accuracy", above).
A run without `--cert-accuracy` writes `accuracy 0`, the golden writer's
bytes, and both auditors accept it. Under `CFT_ORBITS_CERT_PLANT=width`
(the first term's coefficient times 2^-1000), the run is refused `width`
at "term 0's product", as the golden writer refuses the same entry.
The same bytes then come from runs cut at a loader limit of 5 (4 for the
outer system), by checkpoints under the steady clock, and at batch 1, 2
and 3. They come from relays stopped every 37 steps (mid interval), 16
(every interval's last step, unclosed) and 13 (the outer system,
keyed); from a run killed as its third checkpoint appeared; and from a
resume of the final checkpoint with the certificate removed. A certified
run's records are an ordinary run's. Each control is refused by name
by both auditors, with the same code and location:
- an interval's end state changed: `segment-end`;
- a flag word changed: `segment-flags`;
- an interval dropped: `continuity`;
- `=transpose`'s own certificate, whose states are certified in the
  layout the image reads: `segment-end` at segment 0;
- a resume under `=drop-flags` after a stop at an interval's last step:
  not the uninterrupted certificate, and `segment-flags`.
Every refusal above is made, by name and exit code, with nothing made
or changed. Four are reachable only through `CFT_ORBITS_CERT_PLANT`, a
test instrument as `CFT_SEGRUN_PLANT` is: `flags-unreadable`,
`flags-unwritten`, `flags-wide` and `width`; [7b] holds its malformed
values, and its being set where it does not apply. Another build's
identity, with the sum made again, is `identity`. Ten checkpoint cases
are refused with their sentences, exit 2:
- version 2 with `--cert`, and version 3 without;
- a byte changed, and the file cut;
- with the sum made again: a line repeated, a flag word out of range,
  one this tool would have stopped at, and a STATUS bit;
- a run started with the entries resumed without them, and one started
  without resumed with them.
Measured on the desktop, niced (2026-09-30): [8] is 91 checks in 17 s.
The whole of `orbits_check.py` is 214 checks, 0 failures, in 65 s, where
it was 119 in 38 s before. An ordinary run's checkpoints, records, chain
line and segment dump are be3eb72's, byte for byte.

**The fuzz lane.** `host/fuzz/fuzz_ckpt.py` seeds two entries,
`orbits-cert` (open) and `orbits-cert-keyed` (with the angular
momentum's drift entry), from a certified run's version-3 checkpoint,
made fresh each session with its states directory.
Its mutator knows the block, and makes the sum again over three
mutations in four, so that the strict reader behind the sum is what it
reaches. An accepted resume runs to its end, and its certificate must be
the uninterrupted run's. One that differs is held to the golden audit,
and is a finding, a silent wrong resume, unless the audit refuses it by
name.

Measured on 2026-09-30 in the lane's cft-sim image (gcc 13, address and
undefined-behaviour sanitisers), capped at 2 CPUs and niced: 60 s an
entry, 678 resumes, 5.6 a second.
- 631 were refused by name: 541 by the reader's sentences, then 24
  `salt-unexpected`, 21 `identity`, 20 `salt-missing`, 12
  `program-digest`, 11 `image-digest` and 2 `salt-commitment`.
- 16 were accepted and wrote the uninterrupted certificate.
- 31 were accepted and wrote another. Each came from a checkpoint whose
  sum the mutator had made again, and the golden audit refused every one
  by name: 30 `segment-end` (a mid-interval state, or the step, moved)
  and 1 `segment-flags` (a word of 16 made 0).
- None crashed, hung, tripped a sanitiser or resumed silently wrong.
A shorter unsanitised run on the desktop, before that one, found that
the reader accepted words the tool could never write. It accepted 19
checkpoints with a STATUS bit, and 8 changed flag words, some of them
impossible ones; the audit refused each. The reader now refuses a flag
but inexact, and any STATUS bit, itself, and the gate holds both.

Again once the checkpoint carried `cert entries` and the keyed seed its
entry, the same way (2026-09-30): 566 resumes, 4.7 a second.
- 522 were refused by name: 441 by the reader's sentences, then 29
  `salt-missing`, 19 `identity`, 17 `salt-unexpected`, 8
  `program-digest`, 5 `image-digest` and 3 `salt-commitment`.
- 15 were accepted with the uninterrupted certificate, its entry among
  them.
- 29 were accepted with another, each refused by the golden audit by
  name, `segment-end`.
- Nothing else.

---

## Determinism, and how it is tested

The claim is:

> The same problem, scheme, format, route, ensemble and step count
> produce bit-identical results and a bit-identical checkpoint
> whatever the batch size, the engine, the host or the backend.

It rests on the ensemble advancing in **lockstep**: one library call
per operation per step per batch chunk, so `--batch` is purely how
many ensemble members ride in one call. Nothing reduces across
members - `cft_reduce`'s tree runs over ELEMENTS, and an element here
is an ensemble member, so every sum over bodies is an explicit
elementwise `CFT_ADD` in a fixed index order. Deposits are addressed
by element index (docs/SEQUENCER.md P2), so a program chunk writes the
same bytes wherever it sits.

`host/tests/orbits_check.py` tests it rather than asserting it:

| property | how |
|---|---|
| results, roundoff | each format's run against its own 300-digit twin - `5.500e-68` at fp256 and `1.050e-12` at fp64 over 2,048 steps - and the ratio, `1.91e55`, against `2^(237-53) = 2.45e55` |
| results, truncation | the tool's fp256 run against the closed form at two step sizes, recovering both schemes' orders |
| the invariants | `H0` and `L0` against 300-digit values from the same starting bits; the angular-momentum drift against a `steps^2 2^-p 10^6` bound for both problems and both schemes |
| the transcribed table | osculating elements against published sidereal periods |
| the chain | recomputed with `hashlib` |
| batch size | 8, 3 and 1 over the same ensemble must end on byte-identical checkpoints, and a run with `--records` on the same checkpoint as one without |
| engines | the whole integration as one sequencer program and the host `cft_run` loop must produce byte-identical records AND checkpoints |
| segments | `--engine segments` against the host loop on both problems and both schemes at binary256 and on one configuration at each other format, operation counts included, and at the segment lengths real runs use (1,024 steps; 1 + 99,999; intervals split at a lowered loader limit); five stop points; its own batch sizes, 10^12 included; the outer solar system resumed in 37-step pieces by segments alone and by the two engines in turn; where its checkpoints fall and the checkpoint it ends on, against the host loop's under a steady clock, and a real run's first checkpoint part way through a long interval; the image cache keyed by the whole length; its checkpoint's rename under a `stat()` poll and held open, and how long that rename is retried; intervals past one segment's limits run; its census against the program's structure; the golden model's executor and assembler on its image; the flag certificate on a planted fault; and a control on each comparison but the census, the batch sizes and the three narrower formats, which must fail ("As resumable segments" names them) |
| interruption | a run stopped every 37 steps - which does not divide the 96-step sample interval, so most stops land mid-interval - and resumed at a different batch size must end on the same checkpoint and the same records, byte for byte, as one that was never stopped; and runs KILLED, on both engines - at their first checkpoint, and with their records ahead of it - and each resumed by the other engine, must end on the uninterrupted run's checkpoint and records too, with a control that resumes without cutting the records back and must fail; runs ended the instant a checkpoint is in place leave the records exactly that long, with a control that hands them over after the rename and must fail; a run whose records another process appends to is stopped by name at its next checkpoint and resumed to the uninterrupted run; a run into a file that says it holds nothing, whatever is written (as the WSL share presents a Linux FIFO), writes its records without a checkpoint and is stopped by name at its first with one; a relay without `--records` ends on the same checkpoint |
| refusals | the three things `--engine program` must refuse, the four `--engine segments` must, the negative controls and test instruments set where they do not apply or to a malformed value, `--checkpoint-interval` values that are not a number of seconds, the records files and records paths (pipes, devices, a file another process holds) `--resume` must refuse, `--records` and `--checkpoint` as one file, and a records file that cannot be opened or emptied, each with its reason and in bounded time |
| certificates | section [8]: two certified runs, keyed and open, each held to the golden writer, to its records and to both auditors; the same bytes however the run was cut, batched, relayed or killed; five controls, each refused by name by both auditors; every refusal of the certified path by name and exit code ("Certified runs") |

---

## Measured throughput

Software backend, single thread, on DESKTOP-T33SK86 (Windows 11,
MINGW64, `gcc -O2`), 2026-09-04, box otherwise busy with other work.
The command for one row is

```
./cft-orbits --problem kepler --members 16 --periods 16 \
             --steps-per-period 512 --scheme leapfrog --rsqrt exact \
             --format fp256 --engine loop --batch 16 --csv --quiet
```

with `--scheme`, `--rsqrt`, `--format` and `--engine` varied. Every
row covers the same 8,192 steps over 16 ensemble members.

| scheme | 1/r^3 | format | engine | seconds | steps/s | element-steps/s | library calls |
|---|---|---|---|---|---|---|---|
| leapfrog | exact | fp256 | loop | 3.720 | 2,202 | 35,233 | 90,395 |
| leapfrog | exact | fp128 | loop | 2.224 | 3,684 | 58,940 | 90,395 |
| leapfrog | exact | fp64 | loop | 1.570 | 5,218 | 83,487 | 90,395 |
| leapfrog | exact | fp32 | loop | 1.253 | 6,540 | 104,632 | 90,395 |
| leapfrog | newton | fp256 | loop | 1.656 | 4,947 | 79,150 | 295,195 |
| leapfrog | newton | fp256 | **program** | 1.376 | 5,954 | 95,263 | **284** |
| leapfrog | newton | fp64 | loop | 0.586 | 13,988 | 223,807 | 196,891 |
| leapfrog | newton | fp64 | **program** | 0.552 | 14,832 | 237,305 | **284** |
| yoshida4 | exact | fp256 | loop | 10.853 | 755 | 12,077 | 270,619 |
| yoshida4 | exact | fp64 | loop | 4.711 | 1,739 | 27,823 | 270,619 |

and for the outer solar system, 8 members, 20 years at a 10-day step
(730 steps):

| scheme | 1/r^3 | format | seconds | steps/s | element-steps/s | library calls |
|---|---|---|---|---|---|---|
| leapfrog | exact | fp256 | 1.837 | 392 | 3,136 | 148,146 |
| leapfrog | exact | fp64 | 0.919 | 783 | 6,265 | 148,146 |
| leapfrog | newton | fp256 | 1.047 | 688 | 5,503 | 328,146 |
| yoshida4 | exact | fp256 | 5.845 | 123 | 985 | 436,146 |

Four things in those tables are worth more than the numbers.

- **binary256 costs 2.4x binary64 on this workload**, not the 30x a
  significand-width argument would predict, and binary32 is only 3x
  faster than binary256. docs/BENCHMARKS.md measures 1.6x from fp32 to
  fp256 on a bare FMA and explains why - the software backend's
  per-element price is the structural path rather than limb
  arithmetic. The gap is wider here than there because the step is not
  a bare FMA: `cft_sqrt` and `cft_div` are Newton iterations whose
  pass count *does* grow with p, so a workload built on them widens
  the ladder from 1.6x to 3x. That is the honest shape of it.
- **Correct rounding costs 2.2x.** `cft_sqrt` plus `cft_div` against
  the seed-plus-Newton route, at binary256, for the same kernel.
- **The program engine's contribution is the call count, not the
  clock.** 1.20x faster, and 284 library calls instead of 295,195 -
  three orders of magnitude - for the same arithmetic. On the software
  backend the saving is dispatch and buffer walking; on a device it is
  the memory system, and docs/SEQUENCER.md's argument is that the
  second saving is the one that matters.
- **Throughput is nearly flat in the batch size.** The batch sweep
  below is a factor of 1.55 across a 64x range of `--batch`, and the
  program engine is flat to 8%.

Batch sweep, 64 members, 4 periods at 512 steps a period, binary256:

| `--batch` | loop, element-steps/s | loop, calls | program, element-steps/s | program, calls |
|---|---|---|---|---|
| 1 | 23,247 | 1,446,848 | 89,468 | 5,120 |
| 4 | 32,422 | 361,712 | 91,639 | 1,280 |
| 16 | 34,725 | 90,428 | 96,661 | 320 |
| 64 | 36,157 | 22,607 | 95,117 | 80 |

---

## The fp64-versus-fp256 result

Same host and date. These are the runs the workload exists for.

### The Kepler orbit, 2000 periods

```
./cft-orbits --problem kepler --members 4 --periods 2000 \
             --steps-per-period 512 --scheme SCHEME --format FORMAT \
             --csv --quiet
```

1,024,000 steps of an `e = 3/4` orbit, four ensemble members, sampled
once per period.

| scheme | format | energy drift | angular-momentum drift | seconds |
|---|---|---|---|---|
| leapfrog | fp256 | `7.94534e-4` | `9.00177e-69` | 133.6 |
| leapfrog | fp64 | `7.94534e-4` | `1.44687e-13` | 64.0 |
| yoshida4 | fp256 | `2.04280e-5` | `6.91390e-69` | 399.9 |
| yoshida4 | fp64 | `2.04280e-5` | `2.20051e-13` | 204.8 |

Read the columns separately, because they are different quantities.

**The energy column is the method.** It is identical at binary64 and
binary256 to every digit printed, twice over, and it changes by 38.9x
between the two schemes. That is a truncation error, doing exactly
what a truncation error does: it depends on the scheme and not at all
on the arithmetic.

**The angular-momentum column is the arithmetic.** It changes by less
than 30% between the two schemes - `9.00e-69` against `6.91e-69` - and
by a factor of `1.61e55` (leapfrog) and `3.18e55` (yoshida4) between
the two formats. `2^(237-53)` is `2.45e55`. That is a roundoff floor,
doing exactly what a roundoff floor does: it depends on the format and
barely at all on the scheme.

**The same floor sits under two different truncation errors**, which
is the whole point of carrying two schemes.

The sizes are deliberate. At `--rsqrt exact` the Kepler step costs 9
elementwise issues and 2 composed operations per element-step per
substep, so leapfrog over 1,024,000 steps and 4 members is
`1.024e6 x 4 x 11 = 4.5e7` library element-operations and Yoshida
three times that; the outer solar system over 300 years and 8 members
is `1.75e7`. All four sit inside the `1e7`-to-`1e8` band that keeps a
binary256 run on this backend to a few minutes, and the tool prints
both counts (`elementwise` and `composed`) so the arithmetic can be
checked against the clock.

### The floor across the whole ladder

64 periods, 512 steps a period, four members, leapfrog:

| format | p | energy drift | angular-momentum drift | dL ratio to the next rung |
|---|---|---|---|---|
| fp32 | 24 | `7.89642e-4` | `1.34269e-5` | |
| fp64 | 53 | `7.92692e-4` | `4.49838e-14` | `2.99e8` (`2^29` = `5.4e8`) |
| fp128 | 113 | `7.92692e-4` | `2.02365e-32` | `2.22e18` (`2^60` = `1.2e18`) |
| fp256 | 237 | `7.92692e-4` | `7.87227e-70` | `2.57e37` (`2^124` = `2.1e37`) |

Four rungs, and the angular-momentum drift tracks `2^-p` across all of
them to within a factor of two. **binary32 is the rung where the two
columns stop being independent**: its energy drift is `7.89642e-4`
where every wider format says `7.92692e-4`, because at `p = 24` the
roundoff has grown into the truncation measurement and the run has
started measuring the format instead of the method. That crossover is
the thing this workload exists to locate, and it is 2^213 further away
at binary256 than at binary32.

### The outer solar system

```
./cft-orbits --problem outer --members 8 --years 300 --days 10 \
             --scheme SCHEME --format FORMAT --csv --quiet
```

10,957 steps, five bodies, eight ensemble members.

| scheme | format | energy drift | angular-momentum drift | seconds |
|---|---|---|---|---|
| leapfrog | fp256 | `4.02616e-6` | `4.44569e-70` | 30.1 |
| leapfrog | fp64 | `4.02616e-6` | `1.70779e-14` | 15.8 |
| yoshida4 | fp256 | `2.52287e-9` | `1.12624e-69` | 89.0 |
| yoshida4 | fp64 | `2.52287e-9` | `2.45873e-14` | 41.0 |

The same shape: energy identical across formats and 1,596x apart
across schemes; angular momentum `3.84e55` and `2.18e55` apart across
formats and within 3x across schemes.

Ten times longer, at 3000 years (109,575 steps, two members,
leapfrog): `dH = 4.25056e-6` at both formats, `dL = 2.00550e-69` at
binary256 and `4.16652e-14` at binary64. The energy error has barely
moved - it is bounded, because the scheme is symplectic - while the
roundoff has grown by 4.5x at binary256 and 2.4x at binary64 for ten
times the steps. That is the sub-linear growth of a random walk, and
it is the reason the two columns eventually cross.

### What binary64's roundoff is worth as a perturbation

The ensemble calibrates it. Member 1 starts one ulp of `q0` away from
member 0 and nothing else differs, so its separation from member 0
measures how a known perturbation grows; the 300-digit twin measures
the format's roundoff over the same run. Dividing gives the roundoff
as an equivalent error in the initial condition.

Over 16 periods (8,192 steps), leapfrog:

| format | 1 ulp of `q0` | grows by | roundoff, absolute | = ulps of its OWN initial condition |
|---|---|---|---|---|
| fp256 | `2.2639e-72` | `75,729` | `2.0432e-67` | **1.19** |
| fp64 | `5.5511e-17` | `9.8625e5` | `1.1719e-11` | **0.21** |

and over 64 periods (32,768 steps), `0.090` and `0.20`.

So **in each format the accumulated roundoff of a symplectic
integration is worth an O(1) number of that format's own ulps of
initial condition.** The formats do not differ in how badly they
accumulate; they differ in how big an ulp is. Choosing the format is
choosing how wrong the initial condition effectively was - `2^-238` of
`q0` at binary256, `2^-54` at binary64 - and in absolute terms that is
`2.04e-67` against `1.17e-11`, a factor of `5.7e55`.

Two honest caveats on that table. The growth factor is measured at a
sample point, so it varies over the orbit by an order of magnitude
(the 64-period row's growth is 12x the 16-period row's); and the two
formats' growth factors differ (`7.6e4` against `9.9e5`) because
binary64's own roundoff has already moved its trajectory to a
different orbital phase. The measured `fp64/fp256` ratio is therefore
`5.7e55` and `1.0e56` on those two runs rather than exactly `2.45e55`.
Neither caveat touches the conclusion, and both are why the
angular-momentum column above is the cleaner number.

### The chains

Reproducing these is the bit-exactness gate, and it is the only gate
that sees a change in the ORDER of the roundings (negative control C
below). One run per line:

```
./cft-orbits --problem kepler --scheme SCHEME --format FORMAT \
             --members 8 --periods 16 --steps-per-period 512 --csv --quiet
./cft-orbits --problem outer --format fp256 --members 8 --years 20 \
             --days 10 --csv --quiet
```

| run | chain |
|---|---|
| kepler, leapfrog, fp256 | `ef6e079c09b2b8d17a9238e89a0581d81f001d5c02c0ccd778258167dfc48e6f` |
| kepler, leapfrog, fp64 | `82dd457fb1ca804f365d4856c8c764e00febe7fe6d994559eb1e97450c4824e1` |
| kepler, yoshida4, fp256 | `0103e457dc0346e7c7c797b1d753d950455d053f147ffa7188c571a6647eb9be` |
| kepler, yoshida4, fp64 | `c2e5431d192b530ed40c0aaad955106f2ecd4e475cd15633dc549ad8f42bbf09` |
| outer, leapfrog, fp256 | `7155e2c17b3d9af653cb6210f1da844a45a62fcc7f2e89d0f69ca419d422cf52` |

Unlike `docs/COLLATZ.md`'s, these chains are **not** the same across
formats, and they never can be: nothing in this workload is exact, so
each format's trajectory is its own. What is the same across formats
is the *structure* - the record order, the sample count, the
determinism - and what is the same across batch sizes, engines and
interruptions is the chain itself.

---

## The negative control

Three deliberate faults, each rebuilt and run through
`make -C host orbitstest`. They are chosen to be caught by three
*different* gates, and the third one is caught by only one.

`orbits_check.py` scored 26 checks in 8 groups when these were run
(2026-09-04; it has grown since, and [6b]'s own planted defects are in
"As resumable segments"); the tables below say which of them fired.

### A: Newton's third law broken

In `kick_outer`, `R->c_mhm[sub][i]` became `R->c_mhm[sub][j]`, so body
*j* is accelerated in proportion to its own mass rather than body
*i*'s. `m_i g_ij` stops being symmetric. One token.

| gate | result |
|---|---|
| [4b] the angular-momentum certificate, outer, both schemes | **FAIL** - `2.05411e-3` against a `2.35e-60` bound |
| [4] the 300-digit oracle, outer | **FAIL** - fp256 deviates `2.756e-01` against a `9.389e-62` ceiling |
| [4] fp64 against fp256, outer | **FAIL** - both deviate by `2.756e-01`; when the physics is wrong the format stops mattering |
| everything else - all 5 Kepler rows, the exception flags, the chain, batch-size independence, engine identity, resume, the refusals | pass |

The tool's own summary reads `dH = 1.67409e+0`, `dL = 2.05411e-3`,
`flags = 0x10` - the flag word is completely clean, because a wrong
mass is arithmetic that rounds exactly as correctly as the right one.
This is the case for the angular-momentum bound being a GATE with a
number rather than a line in a report, and for having an independent
oracle at all.

### B: the exception-flag certificate removed

Two changes, and the pair is the point.

**B2, the fault:** in `kepler_r2`, `CFT_FMA` became `CFT_SUB`. Since
`CFT_SUB` is `d = a - c`, `r^2` becomes `q0 - q1^2` instead of
`q0^2 + q1^2` - a plausible slip, and one that goes negative as soon
as the particle swings round.

With the certificate gate in place, at every format, the tool never
finishes a single sample:

```
cft-orbits: cft_sqrt raised 0x01 - this workload can only ever raise inexact,
so invalid, divide-by-zero, overflow or underflow means the integration or the
tool is wrong (docs/ORBITS.md, "Flags")
```

exit 3, naming the operation and the flag, at the step it happened.

**B1, the sabotage of the flag handling:** `note_flags` stops treating
the four certificate flags as fatal. Now the same run *completes*:

```
fp32   dH=nan dL=0 flags=0x11 chain=f2507cac4e86ba02
fp64   dH=nan dL=0 flags=0x11 chain=f51642bc25546b7d
fp256  dH=nan dL=0 flags=0x11 chain=d44c92c006a1512f
```

exit 0, a chain, and `dL = 0` - **the angular-momentum certificate
reports perfect conservation**, because a NaN state conserves
everything. What remains:

| gate | result |
|---|---|
| [1] the roundoff floor, both formats and the ratio | **FAIL** (`nan`) |
| [2] both schemes' orders | **FAIL** (`nan`) |
| [3] the energy drift across formats, the angular-momentum ratio | **FAIL** |
| [6] the sequencer program against the host loop | **FAIL** - the fault is in the loop engine's `kepler_r2` and not in the program image, so the two engines part company |
| **[4b] the angular-momentum certificate** | **passes, reporting `0`** |
| [4] the outer solar system, [5] the chain, [6] batch and resume, [7] the refusals | pass |

So the honest statement about the certificate flags is:

> They are the only gate that fires *before* a wrong answer exists.
> Every other gate here scores a number the tool has already produced;
> the flag word stops the run at the operation. And they are the only
> gate a NaN cannot satisfy: `dL = 0` looks like perfect conservation
> and `chain = f2507c...` looks like any other chain.

It is also worth recording what did **not** happen. A sweep of 18
deliberately under-resolved configurations - three formats, six step
sizes from 3 to 12 steps per orbit, 3,000 periods each - raised
nothing but `INEXACT`. The certificate gate never fires on a healthy
integration, or even on a badly wrong one; it fires on arithmetic that
has left the domain. That is what a certificate should do, and it is
why it needed a deliberate fault to demonstrate.

### C: the ORDER of the roundings reversed

In `kepler_r2`, `r^2 = q1*q1` then `fma(q0, q0, ...)` became
`q0*q0` then `fma(q1, q1, ...)`. Mathematically identical.
Numerically a different sequence of roundings, by about an ulp a step.

**Exactly one of the 26 checks fires:**

| gate | result |
|---|---|
| [6] the sequencer program against the host loop | **FAIL** - the program image still computes the stated order |
| [1] the roundoff floor | passes: `1.946e-68` against the unsabotaged `2.372e-68`, both far under the ceiling |
| [2] the orders, [3] the invariants, [4] and [4b], [5] the chain, [6] batch and resume, [7] the refusals | pass |

**The 300-digit oracle cannot see this and never could.** It computes
`r^2` correctly; so does the tool, to within a rounding, in either
order. What changed is a bit, and only a bit-exact reference can score
a bit. Here that reference was the other engine. Had the fault been
applied to *both* engines, nothing in the check would have caught it -
and the published chains above would be the only witness:

```
kepler, leapfrog, fp256   ef6e079c...  ->  eb166896...
kepler, leapfrog, fp64    82dd457f...  ->  cca676b9...
kepler, yoshida4, fp256   0103e457...  ->  e65fd276...
outer,  leapfrog, fp256   7155e2c1...  ->  7155e2c1...   (unchanged: the
                                                          fault is Kepler's)
```

That is the plainest statement of what an oracle can and cannot do for
a workload where nothing is exact:

> The oracle is the authority on the DOMAIN and it bounds the answer.
> It cannot bound the bits, because two different roundings of the
> same real number are both correct answers to the domain's question.
> Bit-exactness needs a bit-exact reference - a second engine, a
> second backend, or a published chain - and this repository's
> contract is precisely the claim that those three agree.

`git checkout host/tools/orbits.c`, `make -C host orbits`, and
`make -C host orbitstest` is green again: **26 checks, 0 failures.**

---

## What a device run would change

The same binary, given an `--artifact` path, opens the tile instead of
the software backend and issues the identical calls. What changes:

- **Not the bits.** The chain would be identical, and that is the
  point of the exercise. `--engine program` and `--engine loop` would
  still have to agree with each other and with the software backend.
- **The arithmetic intensity, for the Kepler program only.** 284 calls
  for 8,192 steps over 16 members is one load and one deposit stream
  for the whole integration - sampled coarsely enough to fit the
  tile's 64 deposit slots a lane, which the benchmark's once-a-period
  sampling of 16 periods does not (15 samples is the most one call
  records there, and the tool refuses more by name); docs/SEQUENCER.md's K ~ 30 threshold is
  passed by three orders of magnitude. The loop engine, and therefore
  the entire outer-solar-system workload, stays at one round trip per
  operation and would be memory-bound exactly as that document
  predicts. This workload is thus a clean example of the difference
  the sequencer makes and of the case where it cannot be applied.
- **The lane count.** A tile issues one beat per cycle - one fp256
  lane - and the pipeline is 16 stages deep with no stall path, so an
  ensemble below 16 members runs at pipeline speed rather than
  throughput speed. `--members 16` clears that; `--members 4`, used
  for the long drift runs here because they are about drift rather
  than about throughput, would not.
- **What would not be measured honestly.** Numbers from `hw_emu` are
  RTL simulation seconds and mean nothing as hardware performance;
  docs/BRINGUP.md owns those gates. No device number is quoted here
  because no device has run this.

---

## What this does not do

- **It is not an ephemeris.** The outer solar system here is five
  point masses with the inner planets folded into the Sun, no
  relativity, no oblateness, no Pluto, and a fixed step. It reproduces
  the reference integration in the textbook it is taken from, which is
  what it is for.
- **It does not adapt the step.** A fixed step is what makes the
  scheme symplectic and what makes the roundoff measurement mean
  something; an adaptive step would be a better integrator and a worse
  experiment.
- **The Lyapunov rate it measures is polynomial, not exponential.**
  The Kepler problem is integrable and the outer solar system's
  Lyapunov time is millions of years, so over these integrations
  neighbouring trajectories separate like a power of `t` rather than
  exponentially. The ensemble still calibrates the growth, and the
  calibration is what converts binary64's roundoff into an equivalent
  perturbation - but nobody should read "Lyapunov" here as chaos.
- **No device has run it.** Everything above is the software backend.
