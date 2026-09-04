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
3. **The sequencer cannot hold this workload, and the reason is
   precise.** Two independent obstacles, each fatal on its own, and
   both of them are facts about the program model rather than about
   this tool. That observation is the deliverable for the sequencer's
   designers; it is written out in full below.

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

The two zeros in that initial condition are not a convenience. They
are the only reason the sequencer can run this problem at all - see
"Where the step runs".

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

`12 + 4n` ALU instructions per substep - **36 at binary256** - four
constants per substep plus two shared, and `4 (nsamples + 1)` deposit
slots per lane. The register map is

    r0 = q0  (the a stream)      r4 = r^2     r7 = e
    r1 = v1  (the b stream)      r5 = y       r8 = z
    r2 = q1  (the c stream: +0)  r6 = w       r9 = g
    r3 = v0  (starts at +0)

and it is **forced**, which is the whole point of the next section.

### The two things that stop it, and what they ask for

`--engine program` refuses `--problem outer`, refuses `--rsqrt exact`
and refuses `--resume`. All three refusals are one of two facts about
the program model. Neither is a gap in this tool and neither can be
worked around by writing the program differently.

**(1) Three input streams against 2d state values.**
`cft_program_run` initialises `r0`, `r1` and `r2` from `a`, `b` and
`c`; `r3..r15` start at `+0`, normatively. A Hamiltonian system with
`d` degrees of freedom has `2d` state values per lane, and

    planar Kepler          2d = 4
    outer solar system     2d = 30

So **a program can be entered only at a state with at most three
non-zero components.** The Kepler initial condition has exactly two -
`q = (1-e, 0)`, `v = (0, v0)` - and the two components that must be
zero can be put in registers that start at `+0` (`r2` by passing
`c = NULL`, `r3` because `r3..r15` always do). Step 0 is therefore
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
3-degree-of-freedom one expressible.** Sixteen registers is already
enough for a 6-value state; only the loading is missing.

**(2) Correctly rounded divide and square root are not programs.**
`python/cft_golden/seqprogs.py` is the library's own in-program
`cft_div`/`cft_sqrt`, and its docstring states the partition: **host**
prep (operand classification, the exact prenormalise/centre surgery),
**program** core (seed, Newton, the truncating Markstein finish, the
restore passes), **host** finish (`round_pack`, the contract's single
rounding authority). The core alone occupies `r0..r12` of the sixteen
registers.

So the composed route cannot be inlined into a larger program's loop
body: it needs the host between its halves, and it would not leave
room for the orbit state even if it did not. `--rsqrt exact` is
therefore a loop-engine route, and `--rsqrt newton` exists so that the
two engines have a step they can **both** run - which they then have
to run bit for bit.

The obvious way round (2) - leave `1/r^3` as a host-side composed call
*between* program passes, so that each pass is drift-and-`r^2` or
kick-and-drift - dies on (1) instead: a pass that resumed at the force
evaluation would need four inputs, because every point inside a
leapfrog step has all four state values live. The two obstacles are
independent and either is fatal alone.

**What the sequencer would need to run this workload as one program:**
a way to load more than three registers, and either a callable
composed operation or an in-program correctly-rounded divide. Neither
is proposed here as a change; both are what this workload found.

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
cft-orbits-checkpoint 1
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

The checkpoint is **step-granular, not sample-granular**: the ensemble
state is complete after every step, so a timed checkpoint may fall
between any two of them and `--resume` picks up part way through a
sample interval. That is what makes an interruption cost at most one
`--checkpoint-interval` of work however coarse the sampling is.

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
**derived** in the tool from the square and cube roots of the first 64
primes by integer binary search in 128-bit arithmetic, exactly as
`host/tools/collatz.c` derives them, rather than typed in. The
`hashlib` comparison is what proves the derivation right.

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
| batch size | 8, 3 and 1 over the same ensemble must end on byte-identical checkpoints |
| engines | the whole integration as one sequencer program and the host `cft_run` loop must produce byte-identical records AND checkpoints |
| interruption | a run stopped every 37 steps - which does not divide the 96-step sample interval, so most stops land mid-interval - and resumed at a different batch size must end on the same checkpoint and the same records, byte for byte, as one that was never stopped |
| refusals | the three things `--engine program` must refuse, each with its reason |

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
  significand-width argument would predict. The software backend's
  cost is dominated by softfloat's per-operation bookkeeping, which is
  the same shape docs/BENCHMARKS.md reports for the elementwise
  operations. binary32 is only 3x faster than binary256.
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

`orbits_check.py` scores 26 checks in 8 groups; the tables below say
which of them fired.

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
  for the whole integration; docs/SEQUENCER.md's K ~ 30 threshold is
  passed by three orders of magnitude. The loop engine, and therefore
  the entire outer-solar-system workload, stays at one round trip per
  operation and would be memory-bound exactly as that document
  predicts. This workload is thus a clean example of the difference
  the sequencer makes and of the case where it cannot be applied.
- **The lane count.** A tile issues one beat per cycle - one fp256
  lane - and the pipeline is 15 stages deep with no stall path, so an
  ensemble below 15 members runs at pipeline speed rather than
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
