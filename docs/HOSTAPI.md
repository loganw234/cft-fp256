# The host API

`host/include/cft.h` is the contract between this project and the
people using it. The header was published before the implementation,
deliberately - an ABI is far cheaper to argue with before anything
depends on it than after.

**Both backends are implemented** in `host/src/`: the software
backend (C99, no dependencies, no configure step, no generated
bindings) and the XRT device backend (`backend_xrt.cpp`, compiled in
with `XRT=1`, driving up to 64 compute units with the tree-aware
reduction split). `make -C host` builds a static library, a shared
library, and the tools below; without `XRT=1`, `cft_open()` with an
artifact path reports `CFT_ERR_NO_DEVICE`. Nothing above the API
changed when the device backend landed - which was the point of
having written the API first.

## The shape of the thing

One call does the work:

```c
cft_run(dev, CFT_FMA, CFT_FP256, CFT_RNE, a, b, c, d, n, &flags, NULL);
```

with one sibling for the case that call cannot express, where the
output is one element rather than n:

```c
cft_reduce(dev, CFT_SUM, CFT_FP256, CFT_RNE, a, NULL, d, n, &flags, NULL);
```

and one call decides what "dev" means:

```c
cft_open(NULL,             0, &dev);   /* software - runs anywhere */
cft_open("cft_hw.xclbin",  0, &dev);   /* the tile */
```

Those two backends return **byte-identical output buffers and
identical flags**. That is the whole product expressed as a function
signature: adopt the library with no hardware, add the card later, and
nothing above the API changes except how long the call takes.

## Why a C ABI rather than a Python package

The fields that need reproducible arithmetic do not write their
numerics in one language, and several of them do not write it in
Python at all.

| language | how it calls this | glue needed |
|---|---|---|
| Fortran | `iso_c_binding` | none - direct |
| Julia | `ccall` | none |
| Python | `ctypes` / `cffi` | none; no build step, no pyxrt |
| Rust | `extern "C"` / bindgen | none |
| C | include `cft.h` | none |
| C++ | include `cft.hpp`, header-only over `cft.h` (RAII, typed byte encodings, span batches, context-bound operators) | none |
| MATLAB, R, Go, C#, Java | each has a standard C FFI | a thin shim |

Fortran matters more here than its reputation suggests: an enormous
amount of working numerical code is Fortran, it is where
reproducibility complaints actually originate, and `iso_c_binding`
makes this header callable without a wrapper generator.

The deeper reason is that **a port must be a shim, never a
reimplementation.** Semantics reimplemented per language is exactly
how "identical bits" quietly stops being true - and it stops being
true silently, in the edge cases, months later. One implementation
behind one ABI keeps the guarantee checkable.

It also closes a hole we already have: pyxrt exposes no way to read a
kernel's status registers in either XRT version this project has
tested (2.14 and 2.19), so `FLAGS` and `STATUS` are unreadable from
Python. XRT's C++ API does expose them, so the device backend will
close that hole as a side effect rather than as a special effort - a
Python caller reaching the card through `libcft` gets flags that a
Python caller reaching it through pyxrt cannot.

## What the library absorbs so callers never see it

Every one of these is a place the hardware contract is sharper than a
user should have to care about. All of them are now built and
exercised against a four-tile hw_emu image; the *(device backend)*
tags are kept because they say which properties are the device's
rather than the software backend's, which is still useful when reading
a failure.

- **Beat padding** *(device backend)*. The tile works in whole 256-bit
  beats. `cft_run` takes an arbitrary `n`, pads the tail internally,
  and makes sure padding contributes nothing to the flags. The
  software backend has no beats, so `n` is already arbitrary there.
- **Multi-tile partitioning** *(device backend)*. A four-CU bitstream
  has four sets of FLAGS and STATUS registers. The library splits the
  work, ORs the sticky words, and reports one result. Callers never
  learn tiles exist; `cft_get_caps` reports the count for the curious.
  This is what drives `hw/link_quad.cfg`, and it now scales to 64 -
  see docs/SCALING.md.

  **A reduction splits differently, and that difference is the whole
  determinism argument.** An elementwise op can be cut anywhere,
  because element i does not care which tile produced it. A reduction
  can only be cut at canonical NODES of its tree, or the answer
  changes - so the library computes the node boundaries, hands one
  range to each tile, and folds the partials with the same tree. A sum
  over four tiles returns exactly what one tile returns, bit for bit.
- **Buffer staging** *(device backend)*. `cft_run` takes host pointers
  and does the device round trip itself. `cft_alloc` exists for when
  that round trip is the bottleneck; today it is a plain allocation
  and the sync calls are no-ops, which is what keeps code written that
  way portable rather than dual-path.
- **A per-run size ceiling** *(device backend, 2026-08-31)*. Each
  master owns exactly one HBM pseudo-channel (hw/link.cfg - done for
  response ordering, see there), so each argument buffer is capped at
  that channel's **256 MB per tile**: 64M fp32 elements, 8M fp256, per
  tile per run. The library does NOT split by capacity - slice.h
  divides by tile count only - so an oversized run fails loudly at
  buffer allocation rather than being quietly serialised. Callers with
  more data than that split across runs; if a real workload makes that
  painful, the fix is capacity splitting in `cft_plan_slices`, not
  widening the channel group back.
- **Bus faults** *(device backend)*. A bad pointer or a fabric error
  becomes `CFT_ERR_BUS_FAULT`, distinct from a wrong answer, because
  "the memory never delivered this" and "the arithmetic is wrong" want
  different responses. The software backend cannot produce one.

## The device backend

`host/src/backend_xrt.cpp` implements all four of those bullets. It is
the only C++ in the library, because XRT's API is C++, and it exports
nothing but the C functions in `src/backend.h` - so the library still
builds with no dependencies at all when XRT is absent, which is the
whole reason the software backend exists.

    make -C host XRT=1

Multi-tile is the substance of it. A four-CU bitstream is not four
times one CU from the host's side: each CU's AXI master is wired to
its own group of HBM pseudo-channels, so a buffer allocated for tile 1
is not reachable by tile 2. There is no "the input array" to share.
Each tile gets its own buffers in its own memory group holding its own
slice, and `cft_run` still takes one pointer per operand.

Two things about it are worth stating because they are unusual:

**A failed run poisons the handle.** If a launch or a wait throws,
compute units are still running - XRT's run destructor frees a command
slot, it does not stop a CU, and this RTL has no abort. `cft_csr.sv`
gates the start pulse on `!busy` and answers every write with BRESP
OKAY, so a start issued to a busy CU is dropped *silently*, and the
next poll of CTRL sees the previous run's done bit and reports
success. A caller who retried would receive the aborted attempt's
output. There is no way to make the device safe again from inside the
library, so every later call on that handle refuses until it is closed
and reopened.

**It refuses to open a device whose status registers it cannot read.**
`FLAGS` carries the IEEE exceptions, which are half of what this
library promises to reproduce, and `STATUS` carries the bus faults,
which are how a caller learns its results were computed on bits the
memory system never delivered. Without them every run would return
`CFT_OK` with unverifiable data, and `CAPS` would have to be guessed -
which on a trimmed bitstream means issuing a precision it does not
carry and receiving a buffer of zeros with clean flags. A library
whose product is exception-exact reproducibility cannot run in that
mode, so it says so and stops.

### How it is tested without a card

`host/tests/device_test.c` opens the device backend and the software
backend at once, feeds them identical data, and compares - bits and
flags, every supported format, opcode and attribute. Anything that
differs is a device-path bug by definition, because the software
backend is the one replayed against the golden model.

    bash hw/run-device-test.sh cardday/quad_emu/cft_hw_emu.xclbin 64

It runs against a **hw_emu image with no card present**, which is the
point: four-CU partitioning gets exercised, and its bugs found, before
any hardware exists. Beyond agreement it checks partition invariance -
one call over n against a sequence of calls over slices of it, which
is what the library does internally across tiles - at sizes chosen to
straddle beat and tile boundaries (1, 2, 3, 7, 8, 9, 31, 32, 33, 37).

The same binary is what to run on the card. Only the xclbin changes.

## What is not there yet

- **Card validation.** Everything above has been exercised in
  emulation. Nothing has touched silicon.

## Reductions, and why they are a second entry point

`cft_reduce` landed in VERSION 0x500. It is separate from `cft_run`
rather than another opcode through it, and the reason is a promise
`cft_run` makes: element i of the output depends on element i of the
inputs. A reduction cannot keep that promise - it returns ONE element
however large n is - so issuing `CFT_SUM` through `cft_run` is
`CFT_ERR_INVALID_ARGUMENT` rather than a plausible-looking array.

The tree shape is part of the contract, not an implementation detail:
each node splits so its left child is the largest power of two
strictly below the range, evaluated with the caller's rounding
attribute at every node. Never a sequential accumulation, never
reassociated, never padded. That is what lets two conforming
implementations agree bit for bit, and what lets four tiles agree with
one. `python/cft_golden/reduce.py` is the definition.

Two consequences that surprise people, so they are written into the
header: n = 0 gives +0.0 and raises nothing, and n = 1 gives a[0]
verbatim - one leaf means zero additions, so not even a signalling NaN
is quieted.

`CFT_DOT` is advertised and is not separate hardware. The contract
makes `dot(a,b) == sum(mul(a,b))` exact, flags included, so the
library issues an elementwise MUL and then a SUM. The alternative was
a multiply pass sharing the accumulator's pipe with tagged results and
arbitration between muls and adds - the most schedule-sensitive logic
in the engine, for one saved round trip. The composition property went
into the contract partly so this choice would exist.

That choice paid twice: `CFT_SUMSQ` and `CFT_SUMABS` are the same
composition over a different leaf, and the other three of clause 9.4 -
the scaled products, which return a pair - are named host entry points.
See "The rest of clause 9.4's reductions" below.

## Division and square root: composed, not opcodes

`cft_div` and `cft_sqrt` landed with CAPS opcode-group bit 14. They
are correctly rounded per 754-2019 5.4.1 in the caller's attribute,
with the full flag set - and they are not opcodes, because the tile's
divide hardware is deliberately two small seed tables
(`CFT_RECIP_SEED`/`CFT_RSQRT_SEED`, exposed through `cft_run` like any
opcode) and the FMA it already had. The library composes them:
prenormalise, centre, seed, Newton, a truncating Markstein finish
driven to floor by a restore step, the guard MEASURED from an exact
residual, one rounding.

The composition is the same fixed sequence on every backend. Floating
steps are `cft_run` calls - on a device they run on the tile - and
the integer bookkeeping between them (classify, the ulp steps, the
final pack) is exact host arithmetic, the same division of labour the
reduction fold draws. `python/cft_golden/sequences.py` is the
sequence's specification, held bit-identical to the contract `div`
and `sqrt` by its own test matrix; `host/tests/divsqrt_check.py`
re-proves the C port over the same operand families, flags compared
per element.

Flags follow the per-run granularity rule: every step is its own run,
so the scaffolding's flags are discarded, and what the caller sees is
derived the way the contract derives it - invalid and divideByZero
from operand classes, inexact/underflow/overflow from the single real
rounding. A device whose bitstream predates the seed group answers
`CFT_ERR_UNSUPPORTED` rather than running a sequence it cannot start.

The cost is honest: roughly 25-30 elementwise passes per call. That
is the price of correct rounding built from an FMA - on any
implementation of this route - and it buys the property the project
exists for: the same bits from the laptop and the card.

## The clause-5 completion set (ABI 0.2)

Everything clause 5 still asked for after div/sqrt landed on
2026-09-01, in one additive ABI bump: `cft_rint`, `cft_scaleb`,
`cft_cmp_sig`, `cft_convert`, `cft_cvt_from_/to_{i32,u32,i64,u64}`,
`cft_logb`, `cft_next_up`/`_down`, `cft_class`, `cft_total_order`
(`_mag`), `cft_rem`. The full semantics live in cft.h's own doc
comments and docs/DETERMINISM.md; what belongs HERE is the design
split, because it explains every signature:

**Three are composed**, exactly as cft_div is. `cft_rint` is the
magic-constant addition - `(x + copysign(2^(p-1), x)) -
copysign(2^(p-1), x)` under the caller's attribute, two adds whose
rounding at integer weight IS the operation - with host bookkeeping
substituting the already-integral, infinite and NaN lanes and
synthesising the contract flags (the named variants signal nothing;
only `Exact` reports inexact). `cft_scaleb` multiplies by the exact
float `2^n` whenever it exists, so the multiply's own flags are the
contract flags; above emax it stages in chunks whose saturation is
proven consistent, and beyond the subnormal floor - where no exact
factor exists and uniform staging would round twice - it packs each
lane once on the host instead. `cft_cmp_sig` takes the quiet
predicate's value from the tile and synthesises invalid-for-any-NaN.
`python/cft_golden/sequences.py` specifies the first two routes and
holds them bit-identical to the contract.

**The rest are host operations**, and the reason is worth stating
plainly: they contain no floating-point arithmetic AT ALL. A format
conversion is one `round_pack` of an exactly-known value; nextUp is
an increment on the encoding; totalOrder is an unsigned compare of a
key transform; remainder is exact integer reduction. There is nothing
for a device to accelerate, so no backend pass is issued and the
device argument is context. They are bit-identical across backends by
construction rather than by testing - and tested anyway.

Two contract choices a porter must not miss: `cft_cvt_to_*` pins the
invalid-case delivered values (which 754 leaves open) to RISC-V's
FCVT table, and `cft_class` pins its ten values to RISC-V's fclass
bit indices - both because this project already speaks RISC-V for
rounding encodings and tininess, and one table beats two.

`cft_rem` is the one entry point with a cost note: the C walks the
exponent gap a quotient bit at a time in p-bit integer work (the
model does one unbounded divmod; `clause5_check.py` holds the two
identical, true full-gap fp256 case included - "true" because a
power-of-two divisor exits the walk early, which is exactly how the
first version of that directed case fooled itself). Typical calls
are a handful of steps; the walk tops out at emax - emin + p - 2,
~524.5k steps at fp256 - about ten milliseconds on the host, PER
adversarial lane, so an array full of such pairs pays it per
element.

## The phase-1 transcendentals (ABI 0.3)

`cft_exp`, `cft_expm1`, `cft_exp2`, `cft_log`, `cft_log1p`, `cft_log2`,
`cft_log10`, `cft_pow` and `cft_hypot`, added 2026-09-02 in one
additive bump. **Correctly rounded** at every format under every
attribute, with IEEE 754-2019 clause 9.2.1's special values and the
contract's exact flags - not "accurate to an ulp", not "faithful".

That distinction is the reason they are here at all. A correctly
rounded result is defined by the mathematics, so every correct
implementation returns the same bits and this library's answer can be
scored against any of them - which is what the whole project is for. An
*accurate* exponential is a different thing: two of them disagree in
the last bit on a percentage of inputs, neither can be scored, and
"the same bits everywhere" quietly stops being true in exactly the
places nobody looks. A determinism contract that stopped at the
arithmetic and shipped an approximate `exp` would have a hole in it the
size of every application that uses one.

**They are HOST operations, and that is a design decision with a
reason.** No `cft_run` pass is issued, so there is no bus word and no
`bus_out` argument, and the device argument is context - the same shape
the clause-5 operations take when they contain no floating-point
arithmetic. But the reason is different, and worth stating because it
is what a phase-2 optimisation would have to work around:

`cft_div` composes from the tile's opcodes because division has an
exactly measurable residual. Given a candidate quotient q, `a - q*b` is
one fused multiply away and is EXACT, so its sign says which side of
the rounding boundary the true quotient falls on. `exp` has no such
residual. Nothing an FMA can compute tells you which side of a boundary
`e^x` lies on; only more precision does, and more precision means a
multiprecision evaluator, which is integer work. A tile-assisted fast
path for the narrow formats is a plausible later optimisation - the
tile's FMA could carry a polynomial, with the host deciding only the
cases it cannot - but it would have to reproduce these bits exactly,
which makes it an optimisation and not a different answer.

The signatures follow the clause-5 host operations exactly:

```c
cft_exp  (dev, fmt, rnd, a,    d, n, &flags);
cft_pow  (dev, fmt, rnd, a, b, d, n, &flags);
cft_hypot(dev, fmt, rnd, a, b, d, n, &flags);
```

`d` may alias `a` or `b`; `n` is arbitrary; `b` is not optional for the
two binary functions. A batch is one C call and the flag word is the OR
across it, as everywhere else.

**inexact is raised for every result except the exact ones, and those
are decided by exact arithmetic rather than by a tolerance**: exp and
expm1 only at zero, log and log1p only at 1 and 0, exp2 at an integer
argument, log2 at a power of two, log10 at a power of ten the format
represents, pow when the true value is a dyadic rational, hypot when
x^2 + y^2 is a perfect square. `hypot(3, 4)` is 5 and raises nothing at
all, which is the observable difference between a correctly rounded
implementation and an accurate one.

**If an input cannot be shown correctly rounded, the call returns
`CFT_ERR_INTERNAL`** rather than a plausible number. The library
evaluates at a working precision and raises it until both ends of an
enclosure round the same way; the cap on that escalation is sized so
that no input the formats can express should reach it, and reaching it
is a refusal. docs/TRANSCENDENTALS.md carries the arithmetic behind
that sizing, the exact-case decision procedures, the error bounds and
the Table Maker's Dilemma stated honestly.

Two contract choices a porter must not miss. `pow(+-0, -inf)` is +inf
and signals NOTHING - it is the |x| < 1 row, and the divideByZero is
the pole at a FINITE negative exponent rather than the limit. And a
signaling NaN is not covered by 9.2.1's "even a quiet NaN" rows, so
`pow(sNaN, 0)` raises invalid and delivers the canonical quiet NaN
where C returns 1; that deviation is deliberate and documented rather
than accidental.

The vectors carry them: `<fmt>-transcend[-<rnd>].jsonl`, twenty new
sets in the published directory, replayed by `cft_conformance` like
everything else. They are separate files because these are library
entry points rather than opcodes - a case names a FUNCTION, and there
is no opcode field to put that in - which also means a consumer that
predates ABI 0.3 reads exactly the files it always read.

## The phase-2 trigonometrics (ABI 0.4)

`cft_sinpi`, `cft_cospi`, `cft_tanpi`, `cft_asin`, `cft_acos`,
`cft_atan`, `cft_atan2`, `cft_asinpi`, `cft_acospi`, `cft_atanpi` and
`cft_atan2pi`, added 2026-09-03 in one additive bump. **Correctly
rounded** at every format under every attribute, with clause 9.2.1's
special values and exact flags, on exactly the terms the nine above
are.

**What these eleven have in common is what they do NOT need.** The
phase-1 note said the rest of clause 9 wanted an argument reduction
against pi carried to hundreds of thousands of bits at fp256. These are
the functions that want no such thing:

- `sinPi`'s reduction is `x mod 2`, and every operand is a dyadic
  rational, so that reduction is a MASK on the encoding and is exact at
  every magnitude. `sinPi` of the largest finite binary256 is a zero
  decided by integer arithmetic.
- The inverse functions take an argument in [-1, 1] or a ratio, so
  there is nothing to reduce; pi enters only as a factor of the answer.

`sin`, `cos` and `tan` of a RADIAN argument are a different problem and
are not here.

The signatures follow the nine exactly, and `atan2` takes y first as C
does:

```c
cft_sinpi  (dev, fmt, rnd, a,    d, n, &flags);
cft_atan2  (dev, fmt, rnd, y, x, d, n, &flags);
cft_atan2pi(dev, fmt, rnd, y, x, d, n, &flags);
```

**The exact cases are a much larger table than phase 1's, and every one
of them raises nothing.** Niven's theorem bounds the forward set:
`sin(pi r)` is rational for a rational r only at 0, +-1/2 and +-1, and
a dyadic r cannot reach +-1/2, so `sinPi` and `cosPi` are exact exactly
at the half-integers and `tanPi` exactly at the quarter-integers (with
the half-integers a pole). Hermite-Lindemann bounds the inverse set:
`asin`, `atan` and `atan2` of a nonzero dyadic rational are
transcendental, so they are exact only where the answer is a zero, and
`acos` only at `acos(1)`. The Pi-forms get Niven's larger table -
`asinPi(+-1) = +-1/2`, `acosPi(+-0) = 1/2`, `acosPi(-1) = 1`,
`atanPi(+-1) = +-1/4`, `atanPi(+-inf) = +-1/2`, and `atan2Pi` exact on
every axis and every diagonal. `asinPi(1/2)` is exactly 1/6, which is
rational but NOT dyadic, so it is inexact and still decidable - the
distinction is the whole reason the enumeration is finite.

Rows a porter should not have to infer, each confirmed against MPFR
4.2.2 before it was written down:

- `sinPi` of an integer is a zero with the sign of the ARGUMENT, not of
  `(-1)^n`: `sinPi(1) = +0`, `sinPi(-1) = -0`.
- `cosPi(n + 1/2) = +0` for every n and both signs, because cosPi is
  even and that zero has no sign to carry.
- `tanPi` is `sinPi/cosPi` in every respect, signs included, so
  `tanPi(1) = -0`. At a half-integer it is `+-infinity` with
  **divideByZero** - 7.3's rule for an exact infinity from finite
  operands.
- **`tanPi` cannot overflow at any format here.** A representable
  argument is at least `2^-p` from a pole, so `|tanPi| < 2^p`, far
  inside emax at all four rungs. Overflow cannot occur anywhere in this
  set; underflow can, and comes through the same `round_pack` as
  everything else.
- `sinPi`, `cosPi` and `tanPi` of an infinity are invalid - there is no
  limit there - and `asin`/`acos` and their Pi forms are invalid for
  `|x| > 1`.
- **`atan2(+-0, -0) = +-pi` and `atan2Pi(+-0, -0) = +-1`**: a minus
  zero denominator names the negative real axis. It is the row
  implementations most often miss, and the Pi form is EXACT where the
  radian form is an inexact rounding of pi - which is, in one line, why
  atan2Pi exists as a separate function.
- A quiet NaN does NOT outrank atan2's table the way it outranks pow's.

The vectors carry them in the same `<fmt>-transcend[-<rnd>].jsonl`
files, which now name twenty functions rather than nine. A consumer
built against ABI 0.3 and handed a 0.4 set fails on the NAME of a
function it does not know, which is the refusal it should give.

## The phase-3 radian trigonometry and the hyperbolics (ABI 0.5)

`cft_sin`, `cft_cos`, `cft_tan`, `cft_sinh`, `cft_cosh`, `cft_tanh`,
`cft_asinh`, `cft_acosh` and `cft_atanh`, added 2026-09-03 in one
additive bump. **Correctly rounded** at every format under every
attribute, with clause 9.2.1's special values and exact flags, on
exactly the terms the twenty above are. `sin`, `cos` and `tan` take
their argument in RADIANS; `cft_sinpi` and friends are the same
functions of a half-turn and are a different, cheaper problem.

**What these needed that the twenty did not.** One thing, and only
the first three need it: `x mod (pi/2)` for an argument as large as
2^262143. That is a Payne-Hanek reduction against a stored 2/pi of
270,336 bits (`host/src/mp_2opi.h`, generated, never transcribed,
derived twice), and the cancellation it has to survive is a
MEASUREMENT rather than a theorem - the irrationality measure of pi is
far too weak to bound it at this exponent range. The reduction
measures the cancellation from the bits it has and widens its window
until the working precision is covered; past what the stored constant
covers it REFUSES with `CFT_ERR_INTERNAL`, as everything else in this
contract does rather than return a plausible number.
docs/TRANSCENDENTALS.md has the design, the error bound and the
measured cancellation per format. The six hyperbolics need no
reduction and no new constant: they are exp and log in different
clothes, in the cancellation-free forms phase 1 already justifies.

The signatures follow the twenty exactly - unary, host operations, no
bus word:

```c
cft_sin  (dev, fmt, rnd, a, d, n, &flags);
cft_atanh(dev, fmt, rnd, a, d, n, &flags);
```

**The exact cases are the zeros, and that is a theorem.**
Hermite-Lindemann: `e^z` is transcendental for every nonzero algebraic
z; `sin(x) = a` algebraic makes `e^(ix)` a root of `z^2 - 2iaz - 1`,
and `sinh(x) = a` makes `e^x` a root of `z^2 - 2az - 1`, so both force
x = 0. So sin, tan, sinh, tanh, asinh and atanh are exact only at +-0,
cos and cosh only at 0 (giving 1), acosh only at 1 (giving +0) - and
every other result is inexact. There is no half-integer table here the
way there is for sinPi: an odd multiple of pi/2 is irrational, so no
representable argument is a zero of cos or a pole of tan.

Rows a porter should not have to infer, each confirmed against MPFR
4.2.2 before it was written down:

- sin, cos and tan of an INFINITY are invalid: no limit exists.
- `tanh(+-inf) = +-1` EXACTLY, raising nothing - a limit that happens
  to be representable.
- `atanh(+-1) = +-infinity` with **divideByZero**, 7.3's rule for an
  exact infinity from finite operands; `|x| > 1` is invalid,
  infinities included.
- `acosh(x)` for any x below 1 is invalid - zeros, every negative
  value, and -infinity. `acosh(+inf)` is +infinity.
- sinh and cosh OVERFLOW for a large argument, through round_pack, so
  roundTowardZero delivers maxfinite. tan can overflow too, near a
  pole - how close a representable argument comes to one is measured,
  not bounded; sin, cos, tanh, asinh, acosh and atanh cannot.
- UNDERFLOW happens for sin, tan, sinh, asinh, atanh and tanh of a
  tiny argument and follows clause 7 through the same round_pack.
- A signaling NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.

The vectors carry them in the same `<fmt>-transcend[-<rnd>].jsonl`
files, which now name twenty-nine functions: 242,915
transcendental cases of 478,915 at `make vectors`'
arguments. A consumer built against ABI 0.4 and handed a 0.5 set fails
on the NAME of a function it does not know, which is the refusal it
should give.

## The augmented arithmetic operations (754-2019 clause 9.5)

`cft_augmented_add`, `cft_augmented_sub` and `cft_augmented_mul`,
added 2026-09-03 as part of the 0.6 step. They are unlike everything
above them in two visible ways, and both are the standard's doing
rather than this library's.

**They return a PAIR.** Each writes two arrays: `r`, the operation
rounded, and `e`, the error that rounding made. Together they carry
the exact result the format cannot hold.

```c
cft_augmented_add(dev, fmt, a, b, r, e, n, &flags);
cft_augmented_mul(dev, fmt, a, b, r, e, n, &flags);
```

That is the primitive under compensated summation, exactly rounded dot
products, and double-double arithmetic. Every one of those is written
today out of TwoSum and Dekker splitting - sequences of ordinary
operations that reconstruct the residual by hand, correctly only under
assumptions about association, contraction and intermediate precision
that a compiler is free to break and routinely does. Here it is a
library call with a standard behind it and a vector set scoring it.

**They take NO rounding attribute.** 9.5 fixes the rounding itself:

> This standard specifies a single rounding direction to be used in the
> operations in this subclause, defined as roundTiesTowardZero: the
> floating-point number nearest to the infinitely precise result shall
> be delivered; if the two nearest floating-point numbers bracketing an
> unrepresentable infinitely precise result are equally near, the one
> with smaller magnitude shall be delivered.

That direction is not one of clause 4.3's five attributes, and this
library does not add a sixth attribute for it. There is no `cft_round`
parameter in the signature because there is nothing to pass. Inside,
`round_pack` learns it as an internal rounding DIRECTION
(`CFT_SF_RTTZ`, value 16 - outside the three-bit MODE field the five
attributes encode into), reachable from `host/src/augmented.c` and from
nowhere a caller can steer; the API layer's own attribute range check
is 0..4 and always was.

The tie rule differs from roundTiesToEven **only at an exact midpoint,
and only where the lower neighbour's last bit is odd**. An
implementation that quietly used roundTiesToEven would pass every test
that did not aim at exactly that case, so the vector pools aim at it at
every binade edge the format has.

**HOST operations**, like the clause-5 set and the transcendentals: no
`cft_run` pass is issued, no bus word is produced, `dev` is context. A
tile-composed route - a TwoSum, or an FMA residual for the product -
is a plausible later fast path and would have to reproduce these bits
exactly; it is not what runs today, and the rounding is a reason as
well as the arithmetic, since the tile's five attributes do not include
this one.

`r` and `e` must be different buffers - two writes to one buffer have
no well-defined ordering, so that call is `CFT_ERR_INVALID_ARGUMENT`
rather than a plausible answer. Either may alias `a` or `b`: each
element is read before either output is written.

### The rows a porter should not have to infer

- **Any NaN operand gives the canonical quiet NaN as BOTH results**
  ("propagates a NaN as both results"), invalid raised only for a
  signaling one. An invalid operation - `inf + (-inf)` for the sum,
  `inf * 0` for the product - "produces the same quiet NaN for both
  outputs" with invalid raised.
- **An infinite r gives that infinity as both results.** From an
  infinite OPERAND it signals nothing; from overflow it signals
  overflow and inexact.
- **The overflow threshold is a midpoint, and landing ON it is
  silent.** 9.5: a magnitude "greater than b^emax x (b - 1/2 b^(1-p))
  shall round to infinity with no change in sign", and one "equal to
  b^emax x (b - 1/2 b^(1-p)) shall round to b^emax x (b - b^(1-p))".
  At binary32 that midpoint is `maxfinite + 2^103`: it delivers
  maxfinite and raises **nothing**, because inexact is signalled "only
  when roundTiesTowardZero(x + y) overflows". One ulp higher overflows
  to an infinity in both outputs. Note that overflow here always
  delivers an infinity, in both directions - "roundTiesTowardZero
  carries all overflows to infinity with the sign of the intermediate
  result" - unlike roundTowardZero, which never does.
- **UNDERFLOW is a statement about the ERROR TERM.** It is raised when
  e is "non-zero and lies strictly between +-b^emin". Since e is exact,
  that is **underflow without inexact** - the one place in this
  contract where those two part company, and the one flag combination
  no other operation here can produce. A subnormal `r` with an exactly
  representable residual raises nothing at all: "the operation's
  subnormal and zero results are exact".
- **The sign of a zero e is r's sign**, when the residual is exactly
  zero: `augmentedAddition(-3, 0)` is `(-3, -0)`. r's own zero sign is
  6.3's - `+0` for an exact cancellation (roundTiesTowardZero is not
  roundTowardNegative), the operands' sign for like-signed zeros, the
  XOR of the signs for a product. A residual that is non-zero and
  merely ROUNDS to zero keeps the sign of the exact residual instead,
  by 6.3's rule for a result "that is zero because of rounding".
- **e is always representable for the sum and the difference.** Both
  operands are integer multiples of the format's smallest quantum, so
  the exact sum is one too; the residual is at most half an ulp of r,
  which needs at most p significant bits on a grid the format has. 9.5
  gives augmentedAddition no non-representable case at all, and the
  model and the library both ASSERT it rather than trusting it - the
  model raises, the library returns `CFT_ERR_INTERNAL`.
- **`cft_augmented_mul` has the one exception 9.5 names**: a product
  residual with "non-zero digits ... strictly between
  +-b^(emin-p+1)". It delivers that residual ROUNDED the same way, with
  underflow and inexact raised. That is the only case in which
  `r + e` is not exactly `x op y`, and the only case in which either
  operation raises inexact without overflowing.

### How they are scored

`python/cft_golden/augmented.py` defines every bit and flag. The
vectors get a third schema and a third family of files -
`<fmt>-augmented.jsonl`, one per format, with `"r"` and `"e"` per case
and **no `"rnd"` field**, whose absence is normative: there is no
attribute to record. `cft_conformance` replays them the same two ways
as everything else, one element at a time for exact flags and then as
arrays for the batch loop.

`host/tests/augmented_check.py` is the C-against-model sweep, and it
checks one thing the vectors cannot: the pair identity `r + e == x op
y`, in exact Python integers, **on the library's own output**, over the
whole pool with the two documented exclusions named rather than
tolerated. `host/tools/mpfr_check.c` arbitrates the values against
MPFR - which has no roundTiesTowardZero, so the harness takes the exact
value from MPFR at a precision that provably holds it, proves it did
by requiring a zero ternary, and applies 9.5's tie rule itself; the
banner above `check_augmented` says exactly which half of that is an
independent oracle and which is a restatement.

## The rest of clause 9.4's reductions (part of the 0.6 step)

`cft_reduce` shipped with two of the seven reductions 754-2019 9.4 asks
a language to define. The other five landed 2026-09-03:
**sumSquare, sumAbs, scaledProd, scaledProdSum and scaledProdDiff.**
docs/DETERMINISM.md holds the contract - the tree, the scaling rule,
the exception rules; what belongs HERE is the API shape and why it is
that shape, because the five did not all arrive through the same door.

**Two are new `cft_reduce` opcodes, and they are COMPOSITIONS.**
`CFT_SUMSQ` (28) and `CFT_SUMABS` (29) append to the enum after the
divide/sqrt seeds. Neither is separate hardware and neither needs to
be, for exactly the reason `CFT_DOT` is not: they are the same tree
over a different leaf, so the library issues

    CFT_SUMSQ  ->  cft_reduce(CFT_DOT, a, a)
    CFT_SUMABS ->  cft_run(CFT_ABS, a), then cft_reduce(CFT_SUM)

and the device and software backends agree by construction rather than
by testing. The cost is one scratch buffer for sumAbs - the same trade
`CFT_DOT` already makes for its multiply pass - and one dot for
sumSquare, which costs nothing extra at all.

9.4's one divergent row is applied above both backends, and lazily.
The standard puts an infinity ahead of a NaN for these two, where sum
and dot put NaN first, so a vector holding both returns `+inf`. That
cannot come out of a tree, so the library overrides it - but only after
checking, because no term of either operation is negative, that the
tree's answer is a NaN at all. The scan for an infinity therefore runs
only on a vector that produced one, instead of on every call, which on
a device backend is the host reading the whole input array.

`cft_supports()` accounts for the composition: `CFT_SUMSQ` also needs
the arithmetic group and `CFT_SUMABS` the sign group, so asking about
the opcode itself is the right question and a device missing one says
`CFT_ERR_UNSUPPORTED` before the sequence starts.

**Three are named host entry points**, because they return a PAIR:

```c
cft_scaled_prod     (dev, fmt, rnd, a,    pr, &scale, n, &flags);
cft_scaled_prod_sum (dev, fmt, rnd, a, b, pr, &scale, n, &flags);
cft_scaled_prod_diff(dev, fmt, rnd, a, b, pr, &scale, n, &flags);
```

A pair does not fit through `cft_reduce`, which delivers one element.
Three names rather than one call with a `kind` argument, and the reason
is the same one docs/DETERMINISM.md's reassignment hazard records:
these issue no device pass, so a `kind` enum would be a second opcode
space living beside `cft_op` with none of an opcode's meaning and all
of its stale-number risk. The arities differ too - one vector, then
two - so three functions check at compile time what one would check at
run time. Every other pair-free host operation in the header is named
this way (`cft_div`, `cft_pow`, `cft_atan2`), and these follow it.

`scale` is an `int64_t` out-parameter; neither it nor `pr` may be NULL.
`pr` receives ONE element. **These are HOST operations** - no `cft_run`
pass, no bus word, `dev` is context - for the plainest possible reason:
there is no tile accumulator for a scaled product. The accumulator
streams ADDs. So there is nothing here for a device to carry, and the
results are bit-identical across backends by construction, the same
shape the transcendentals take.

The cost note is short. `cft_scaled_prod` allocates nothing at all -
its factors are the caller's own array - and the other two allocate one
scratch buffer of `n` elements for the rounded leaf sums. Every node is
one multiply and an exact binade extraction, so a scaled product is
about the price of a dot.

**The vectors carry all seven**, in a THIRD set type:
`<fmt>-reduce[-<rnd>].jsonl`, 448 cases and 9,513 elements per file,
20 files. It had to be a new type - a reduction's operand is a whole
vector whose length is part of the case, and both existing schemas are
one line per case with a fixed number of single-element operands. The
scaled products' cases carry `pr` and `sf` where the others carry `d`,
because a set that recorded only the significand would score half the
operation. Before this the published sets carried no reductions at all,
not even `sum`.

## What is deliberately not in the first version

- **Asynchronous submission.** Everything blocks today. A future
  `cft_run_async` returning a handle is additive.

New capability gets new functions. That keeps `cft_run` positional and
FFI-friendly rather than hiding behind an extensible descriptor struct
that every binding then has to lay out by hand.

## The one place the C is not a transliteration

Everything in `host/src/softfloat.c` follows
`python/cft_golden/softfloat.py` line for line, on purpose, so the two
can be read side by side and a divergence shows up as a structural
difference rather than as a subtle one. There is exactly one exception,
and it is worth stating plainly because it is where a bug would hide.

The model computes the fused multiply-add's sum **exactly**: it shifts
both terms to a common exponent and adds, in unbounded integers. For
fp256 that alignment can span the entire exponent range - the product
of two large normals against the smallest subnormal addend is about
790,000 bits wide. Correct, and unusable: a hundred kilobytes of
shifting per element.

So `libcft` bounds the alignment. When the two terms' leading bits are
more than `2p+4` apart, the smaller one lies entirely below the
larger's last bit and cannot influence anything except a sticky bit, so
it becomes one. When they are closer than that, the intermediate is
provably narrow - at most about `5p+3` bits, 1188 for fp256 - and the
sum is computed exactly, as the model does. The derivation, including
why `2p+4` and not something smaller, is written out in the comment
above `sf_fma()`.

That argument is checked rather than trusted, three ways:

- `host/tests/diff_check.py` builds operand triples whose exponent
  separation lands **on and around the cutoff**, in both directions,
  and compares against the model at every precision under every
  rounding attribute. Random operands essentially never land near that
  line, and never land beyond it with the addend dominating, so those
  cases have to be constructed deliberately.
- `--coverage` on the same script reports which path the cases
  actually took. A boundary test that never reaches the boundary passes
  for the wrong reason, and passing for the wrong reason is
  indistinguishable from passing until the day it matters.
- Every width bound is enforced at runtime. The bignum operations
  return an overflow indication rather than truncating, and
  `cft_run()` turns one into `CFT_ERR_INTERNAL`. If the derivation
  above were wrong, the library would refuse to answer rather than
  answer incorrectly.

## Verifying a port

`cft_conformance()` replays the vector sets under `vectors/out`
through whichever backend is open and reports the first disagreement.
`cft-selftest` is that function with a `main()` around it.

This is the acceptance test for a new language binding, a new backend,
a new device generation, or somebody else's independent
implementation. The guarantee at the top of this document is not
something to take on trust - it is machine-checkable, and the vectors
have existed since before the hardware did.

On success it reports what it checked, not just that it passed: a run
that quietly skipped every set would otherwise be indistinguishable
from a clean one.

## What has actually been run

    make vectors            # 20 sets: 4 formats x 5 rounding attributes
    make libcft             # build
    make libcft-test        # contract tests, replay, C-vs-Python
    make libcft-diff        # against the golden model, boundary-targeted
    make libcft-docker      # the same tests on a second platform

As of the commit that added the library, on x86-64 Windows with GCC
16.1 (MinGW, msvcrt):

| check | cases | result |
|---|---|---|
| `cft_conformance` replay | 228,000 | every case, bits and flags |
| differential vs the golden model | 213,000 | every case, bits and flags |
| contract tests (`api-test`) | every check | pass |
| C example vs Python example | 4 checksums | identical |

Reductions were added later and are checked the same two ways - the
tree against the golden model, and the multi-tile split against the
whole-array answer:

| check | cases | result |
|---|---|---|
| `reduce_check.py`, libcft vs the golden model | 7,640 reductions across 4 formats | tree, bits and flags agree |
| `reduce-parts`, every canonical partition vs the whole | 4,060 partitions (4 formats x 29 sizes x 7 part counts x 5 attributes) | every partition reproduces the whole |

And the divide/sqrt era (2026-08-31 onward), same discipline, more
oracles - current numbers, with docs/VALIDATION.md as the ledger:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (regenerated sets incl. the seed opcodes) | 392,000 | every case, bits and flags |
| `divsqrt_check.py`, cft_div/cft_sqrt vs the model | 29,124 + a chunk-boundary batch | zero disagreements, per-element flags |
| `clause5_check.py`, the completion set vs the model | 112,372 (all entry points, 16 conversion pairs, chunk-crossing batches, the fp256 full-gap remainder) | zero disagreements, per-element flags |
| native-oracle soak vs the host CPU's IEEE hardware | 23.875 billion (exhaustive fp32 sqrt, all five attributes) | zero value or flag disagreements |
| MPFR parity, all four formats, all five attributes | 999,000 | zero disagreements |

And the transcendental era (2026-09-02), where MPFR is not the third
oracle but the only one - libm is neither correctly rounded nor
reproducible, so there is no CPU campaign to calibrate against even at
fp32:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (40 sets: 20 opcode, 20 transcendental) | 456,325 | every case, bits and flags |
| `transcend_check.py`, the nine vs the model | 77,315 | zero disagreements, per-element flags |
| the same, with the library forced to start below the precision it needs | 72,275 | identical through the escalation path |
| MPFR parity, the nine functions | 95,680 | zero value AND zero flag mismatches |
| `cft.hpp` vs `cft.h`, every entry point twice | 3,267 at C++17 and again at C++20 | identical encodings and flags |

And the clause-9.5 augmented operations (2026-09-03), where the oracle
question has its own answer - MPFR has no roundTiesTowardZero, so the
harness takes the exact value from MPFR and applies the tie rule
itself:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (44 sets: 20 opcode, 20 transcendental, 4 augmented) | 724,531, of which 89,616 augmented | every case, BOTH outputs and flags, replayed twice |
| `augmented_check.py`, the three vs the model | 149,112 comparisons at `--trials 400` | zero disagreements, per-element flags |
| the pair identity `r + e == x op y`, exact integers, on the library's output | 80,209 pairs | exact, plus 8,316 residuals delivered rounded per 9.5's one non-representable case |
| the FAR/NEAR alignment split, walked across its decision | 70,200 comparisons | C == model on every one |
| MPFR parity, the three operations | 21,492 (5,373 per format) | zero value AND zero flag mismatches |
| `cft.hpp` vs `cft.h`, every entry point twice | 4,311 at C++17 and again at C++20 | identical encodings and flags |

The second table is the one that matters for tiles. It is the software
statement of the property the hardware has to keep: cutting a
reduction into k canonical ranges and folding the partials gives the
same bits as not cutting it, for every k the library would ever
choose.

And the part that is actually the product. The same source built by
**GCC 13.3 on Ubuntu 24.04 against glibc**, running in the project's
own simulation container, prints:

    fp32   n=4096 rne  checksum 0x9af9d3973816adcf  flags 0x10
    fp64   n=4096 rne  checksum 0x04110a4c30c6df4d  flags 0x10
    fp128  n=4096 rne  checksum 0xb815aa4a3a3eb024  flags 0x10
    fp256  n=4096 rne  checksum 0x0eea048c14040a4e  flags 0x10

character for character what the Windows build prints. Two operating
systems, two C libraries, two compiler major versions, 16,384 fused
multiply-adds per line at four precisions - and one set of bits. That
is the claim this project exists to make, made on the cheapest
hardware in the building, with no card involved.

Running it on a second platform is also what found the two portability
bugs worth having: `make clean` removed only the current platform's
shared library, and the Python loader took the first library it found
rather than the one for the platform it was running on. Both are the
same mistake - assuming one machine - which is the mistake this
library is supposed to be immune to.

The differential run reached the far path 1,146 times at fp256 with
the product dominating and 885 times with the addend dominating,
roughly evenly split between like and unlike operand signs, and the
widest exact intermediate it produced was 952 bits against a container
sized for 2048. Those numbers come from `make -C host coverage`, so
they are re-derivable rather than remembered.

## Calling it from somewhere else

`host/examples/` has the same program three times:

- `vector_fma.c` - C, linked against the static library.
- `vector_fma_ctypes.py` - Python, via `ctypes.CDLL` and eight
  `argtypes` lines. No build step, no binding generator, no pyxrt.
- `vector_fma.f90` - Fortran, via `iso_c_binding`, verified with
  gfortran 13.3. A native `real(c_double)` array goes straight to
  `c_loc()` and is used in place: no conversion step, because the
  buffers are specified as dense little-endian interchange encodings
  rather than as a struct. That is the argument at the top of this
  document - that Fortran is the language this contract most needs to
  reach, and that reaching it should cost an interface block and
  nothing else - demonstrated rather than asserted. `make -C host
  fortran` runs it, and the simulation container carries gfortran so
  CI can too.

The C and Python versions print a checksum of the output buffer, and
`make libcft-test` diffs them. Identical output from two languages
through one library is the cross-language claim reduced to something
that either passes or fails.

## Weak links this exposes in the hardware contract

Writing the header surfaced two places where the device side was not
future-proof enough to sit behind a stable ABI. **Both are now
fixed** - which is the argument for writing a header before an
implementation: neither gap was visible until something had to be
promised to a caller.

1. **`CAPS` reported precisions but not operations.** A host could ask
   which formats a bitstream carried and not which opcodes it
   implemented - fine while every build has every op, actively wrong
   the moment one does not, and `cft_supports()` would have had to
   guess from the version number. CAPS[15:8] is now an opcode-group
   bitmask: arithmetic, sign, min/max, predicate, integer, with
   reserved bits for reduction, divide/sqrt and conversion. Groups
   rather than 256 individual bits, because opcodes arrive in groups
   and a bit per opcode is a register nobody keeps current.

2. **Unassigned opcodes silently did arithmetic.** Opcode 15 and
   everything from 24 up fell through to the FMA datapath with
   unsteered operands - deterministic, so the contract held, but the
   wrong failure: a host issuing an opcode its bitstream predates got
   a plausible number rather than an error. They now return the
   canonical quiet NaN with **invalid** raised, in hardware and in the
   golden model alike, which is what `CFT_ERR_UNSUPPORTED` reports
   against.
