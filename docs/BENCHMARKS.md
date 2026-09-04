# Benchmarks: the software tier, measured

This file holds the project's measured performance numbers. Today that
means the SOFTWARE tier only - libcft's software backend against the
libraries a prospective user could already run - because those are the
only performance numbers that can currently be measured honestly:

- There is no card in the machine yet, so there are no hardware
  numbers. When there are, they get measured under docs/CARDDAY.md's
  gate 6 ("Throughput. Now, and not before, measure.") and recorded
  here. Until then this repo publishes no projected hardware
  throughput next to measured software throughput; the projection
  lives in docs/SCALING.md and is labelled as one. As of 2026-09-02
  that projection is no longer a bound calculated from the beat
  geometry - `make cycles` measures cycles per beat on the RTL itself
  (1.250 marginal, 36 fixed, every rung) - but cycles x period is
  still a prediction, and it stays on that side of the line.
- Emulation produces no throughput numbers at all. hw_emu is an RTL
  simulation running many orders of magnitude below fabric speed; its
  wall clock measures the simulator. (Its cycle counts are real, and
  cycles x period is a prediction - but a prediction still belongs on
  the other side of the measured/projected line.)

Correctness is a different file: docs/VALIDATION.md owns the oracle
campaigns. The agreement column below is a harness check, not a
validation claim.

## Provenance

Measured 2026-09-01, single-threaded, on a quiet machine:

| what | value |
|---|---|
| CPU | Intel Core i5-12400F (Alder Lake, 6 P-cores; base 2.5 GHz, single-core turbo ~4.4 GHz) |
| environment | the repo's own sim container (docker/Dockerfile.sim: Ubuntu 24.04, gcc 13.3.0), pinned to one core with `taskset -c` |
| libcft | `-O2`, plain C99, the software backend (`cft_open(NULL, ...)`) |
| MPFR / GMP | 4.2.2 / 6.3.0, the pinned oracle prefix from verify/build-mpfr-oracle.sh; both upstream test suites ran green on this machine before use |
| __float128 | gcc 13.3.0's libgcc soft-float + libquadmath (`fmaq`, `sqrtq`) |
| cpu-hw | the CPU's own float/double, `-O2 -fno-math-errno`, glibc `fma`/`fmaf` |
| mpmath | 1.4.1, pure-Python backend, CPython 3.12 |

Tools: host/tools/cft_bench.c (internal), host/tools/cft_bench_peers.c
(cross-library; its header defines every row), host/tools/bench_mpmath.py
(Python context). Reproduce with:

    bash verify/build-mpfr-oracle.sh       # once; PREFIX=... to relocate
    make -C host cft-bench
    make -C host cft-bench-peers CFLAGS="-O2 -I$PREFIX/include" \
                                 LDLIBS="-L$PREFIX/lib"
    ./host/cft-bench
    ./host/cft-bench-peers
    python3 host/tools/bench_mpmath.py

Operands are seeded and identical on every run and every platform:
normal numbers, full random significand, exponent within +/-8 of the
bias - the fast-path cost of a realistic element (the generator and
the reasoning are in cft_bench.c). Every measurement auto-repeats to
at least 0.35 s. Cells still wobble a few percent between runs; read
the ratios, not the third digit.

## Width inside the library

`cft-bench`, software backend, ns per element:

| op | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| fma | 255.8 | 234.7 | 285.5 | 400.7 |
| mul | 196.2 | 197.4 | 240.6 | 355.3 |
| add | 250.3 | 259.0 | 477.4 | 469.6 |
| abs | 26.1 | 34.7 | 56.7 | 100.2 |

The number worth staring at is the FMA column read downward: **fp256
costs 1.6x fp32** for eight times the width. The software backend's
per-element price is almost entirely the structural path - decode,
align, normalise, round, one function call's worth of dispatch - and
almost none of it is limb arithmetic. Width is nearly free in this
implementation; that is a property of writing the softfloat as one
parameterized path rather than four tuned ones, and it is the same
property the RTL has (one parameterized core serving all four rungs).

## Against the peers

`cft-bench-peers`, ns per element, round-to-nearest-even. Every
non-libcft row also states agreement: for this operand stream, every
implementation below produced **bit-identical results to libcft on
every element** - 4096/4096, all ops, all formats, including glibc's
`fma`/`fmaf` and libquadmath's `fmaq`. A row's timing is therefore a
timing of the same work. (`mpfr` = matched precision, MPFR's own
default exponent range; `mpfr+754` = MPFR emulating the binary format
per its manual's recipe - exponent range narrowed, `mpfr_check_range`
+ `mpfr_subnormalize` on every result. libcft is timed through its
batch calls, the peers through per-element calls, because that is how
each is actually used; call shape is part of the price.)

**fp32** (cpu-hw = the CPU's own `float`):

| op | libcft | mpfr | mpfr+754 | cpu-hw |
|---|---|---|---|---|
| add | 282.2 | 14.6 | 20.9 | 0.32 |
| mul | 199.9 | 8.1 | 16.4 | 0.29 |
| fma | 241.5 | 32.8 | 36.7 | 0.84 |
| div | 3789.7 | 12.7 | 19.4 | 0.72 |
| sqrt | 4420.5 | 12.1 | 23.3 | 0.82 |

**fp64** (cpu-hw = `double`):

| op | libcft | mpfr | mpfr+754 | cpu-hw |
|---|---|---|---|---|
| add | 309.8 | 16.0 | 22.2 | 0.53 |
| mul | 206.1 | 8.5 | 16.3 | 0.39 |
| fma | 316.3 | 36.3 | 37.7 | 0.97 |
| div | 4468.0 | 12.4 | 19.0 | 1.08 |
| sqrt | 5638.2 | 15.8 | 23.3 | 1.70 |

**fp128** (quadmath = gcc `__float128`):

| op | libcft | mpfr | mpfr+754 | quadmath |
|---|---|---|---|---|
| add | 344.9 | 15.6 | 21.6 | 15.6 |
| mul | 243.5 | 13.7 | 21.1 | 15.4 |
| fma | 394.5 | 55.8 | 62.9 | 811.3 |
| div | 6678.4 | 25.1 | 32.5 | 21.9 |
| sqrt | 8018.5 | 34.9 | 38.4 | 465.8 |

**fp256** (no other implementation of binary256 to hand):

| op | libcft | mpfr | mpfr+754 |
|---|---|---|---|
| add | 488.3 | 25.4 | 29.9 |
| mul | 332.5 | 36.1 | 39.2 |
| fma | 448.3 | 65.0 | 71.0 |
| div | 11563.1 | 85.3 | 86.4 |
| sqrt | 12704.3 | 140.2 | 139.7 |

Python context, from bench_mpmath.py (mpmath 1.4.1, pure-Python
backend; no shared operand stream, no bit-agreement check - comparable
in shape, not rigor; mpmath has no fma):

| op | fp32-equiv | fp64-equiv | fp128-equiv | fp256-equiv |
|---|---|---|---|---|
| add | 1559 | 2265 | 1479 | 1630 |
| mul | 1444 | 1666 | 1465 | 1579 |
| div | 1592 | 1696 | 1843 | 2162 |
| sqrt | 2545 | 2853 | 3189 | 4160 |

## Workloads designed for the contract

The tables above adapt other libraries' benchmarks to this one. The
five tools below were written the other way round, on 2026-09-04, each
for a property the contract has and a conventional float library does
not: exact integers to 2^237 with the inexact flag as the proof, five
rounding attributes per instruction, correctly rounded results that
are the same bits on every host, and a sequencer that runs the inner
loop as a program. Each is a resumable C tool in `host/tools/` with a
Python oracle in `host/tests/`, a design note in `docs/`, and an entry
in docs/VALIDATION.md; each runs at fp64 beside fp256 and says what
fp64 loses, or that it loses nothing; each measures the software
backend today and takes `--artifact` for a device later. The numbers
are one thread on the Windows desktop, software backend, and they are
measurements of a slow backend, not a promise.

| tool | the workload | what the contract supplies | software backend, fp256 | fp64 beside it |
|---|---|---|---|---|
| `cft-collatz` (docs/COLLATZ.md) | Collatz trajectories, sweep and deep | exact integers below 2^237, the inexact flag as the certificate, the sequencer's escape loop | 587,571 steps/s as a program, 277,210 as a host loop; 10^6 starting values verified in 231 s with 123 library calls | the same chain at fp64 and fp128; fp32 loses 87 of 100,000 to exactness. 2^237 - 1315 verified in 2,437 exact steps |
| `cft-enclose` (docs/ENCLOSE.md) | rigorous enclosures: a series, dot products, interval Horner | roundDown and roundUp per instruction, the reductions' fixed tree, bit-identical bounds | 1,821 enclosures/s; interval Horner 48,502/s as a program against 34,505 as a loop | 14 of 15 ill-conditioned fp64 enclosures straddle zero, 0 of 15 at fp256; on well-conditioned kernels fp64 is fine at 6.4x the rate |
| `cft-mersenne` (docs/MERSENNE.md) | Lucas-Lehmer over the known Mersenne primes | fp256 as an exact 59-bit-limb multiplier, dot reductions as exact convolutions, flags as the certificate | 270,377,166 limb products for the thirteen exponents through 11213 in 212 s, flags clean; 2^19937 - 1 verified across three resumed runs | fp64 needs 22-29x the limb products and 7-13x the wall time for the same exponent; every rung returns the same residue chain |
| `cft-orbits` (docs/ORBITS.md) | symplectic few-body integration, Kepler and the outer solar system | correctly rounded arithmetic, bit-identical ensembles | 95,263 element-steps/s for the Kepler leapfrog as a program (284 library calls where the loop needs 295,195); 12,077 for the Yoshida scheme with correctly rounded 1/r^3; the outer solar system 3,136 | energy drift identical at every format - the method: 7.9e-4 leapfrog, 2.0e-5 Yoshida over 2,000 periods - while angular-momentum drift, the arithmetic, is 9.0e-69 at fp256 against 1.4e-13 at fp64, 2^184 apart |
| `cft-zoom` (docs/ZOOM.md) | a deep-zoom Mandelbrot reference orbit with fp64 perturbation | a bit-identical fp256 reference orbit as a sequencer escape loop | 174,462 reference iterations/s as a program (98 calls per 100,000 iterations), 162,374 as a loop; 399,782 fp64 pixel-iterations/s with an identical pixel chain at every batch size | at a 3.1e-61 pixel the fp64 reference is 9.4e30 pixels off and wrong from iteration 1 while raising no flag; all 4,096 pixels differ; fp256 addresses pixels to 1e-71 against fp64's 1e-15 |

Three of the five asked the sequencer for something it does not have,
and the asks are recorded in their design notes rather than worked
around silently: a fourth input stream and an optional per-element
flag output (Collatz); more than sixteen addressable constants, since
operand fields are four bits (enclose); a lane shift and an in-program
cross-lane reduction, which would put a whole carry chain and a
convolution on-chip (Mersenne). Composed operations and reductions
cannot be called from inside a program, which is why the enclosure
tool's series and dot kernels, and the Mersenne convolution, run as
host-issued calls around program passes.

All five also run in the browser (docs/DEMOS.md): a second committed
page on the module the conformance page embeds, each panel a port of
the tool's loop engine with elements batched, and each panel's chain
matched to the C tool's for the same configuration - 13 chains over 11
configurations on 2026-09-04. Browser rates came out at 0.8 to 1.4
times the native loop engines wherever a call carries a batch (zoom
pixels 343,381 against 346,414 pixel-iterations/s, Mersenne 473,911
against 646,661 limb products/s, orbits 22,645 against 24,922
element-steps/s); a single-lane Collatz trajectory is the outlier at
a quarter of native, which is the wasm boundary and nothing else.
Those are measurements of the same slow tier, made in a browser, and
the page says so.

## Reading the numbers

**MPFR is 7-25x faster than libcft's software backend on the
single-rounding ops, and 90-300x on division and square root.** Both
gaps are real and neither is mysterious. MPFR is thirty years of
CPU-tuned limb assembly (the prefix build configures GMP for the exact
microarchitecture) with native algorithms for every operation; libcft
is portable C99 with no per-CPU code, whose `cft_div`/`cft_sqrt`
deliberately take the composed route - a fixed sequence of ~25-30
opcode passes, documented in host/include/cft.h - because that is the
sequence the TILE executes, and the software backend's job is to be
the tile's bit-exact reference on any machine, not to race MPFR on
this one. The div/sqrt multiple is almost exactly the pass count times
the per-pass price, which is the composition working as specified.

**The one place the comparison inverts: fp128 fused multiply-add.**
libcft's fma (394 ns) is 2.1x faster than libquadmath's `fmaq`
(811 ns) - the common x86 route to binary128 pays more for a correctly
rounded fma than this repo's whole softfloat path costs, while
`__float128` add/mul (compiler-emitted libgcc calls) beat libcft by
~20x. If your fp128 workload is fma-shaped - and the tile's entire
architecture is a bet that the interesting ones are - the "slow
portable library" is already the faster soft option on stock gcc.

**The emulation tax on MPFR is visible and small: 4-8 ns.** That is
what `mpfr_check_range` + `mpfr_subnormalize` add per call. What it
does not buy from MPFR: binary interchange encodings, NaN payloads,
signaling NaNs, or this contract's flag definitions. mpfr+754 is the
closest MPFR gets to a binary-format drop-in, and the remaining
distance is semantic, not performance.

**Silicon is 300-5000x below every soft path.** The cpu-hw rows are
the CPU doing fp32/fp64 in hardware; even MPFR pays 15-45x against
them. That differential is the whole argument for the tile: above
binary64 there is no silicon in a CPU to fall back to, so every
fp128/fp256 user today is paying soft-float prices - and the tile's
job is to move those two rungs to the hardware side of that gap, with
bits identical to what the software tier already produced.

**The Python tier is its own decade.** mpmath at any precision costs
more than libcft at fp256, and ~40-60x MPFR. That is the audience
bindings/cftmpfr exists for: same Python, contract bits, and a path
down to the C prices above (and eventually the card) without leaving
the language.

**What these numbers do not cover:** subnormal-heavy or
special-heavy streams (every soft path here slows down on them, each
differently - the operand generator's header says why fast-path
normals are the published case), rounding modes other than RNE,
multi-threading (everything above is one core), and the flag/status
plumbing cost of a real caller. And nothing here is the tile:
hardware rows land in this file when a card produces them, measured,
under docs/CARDDAY.md gate 6.
