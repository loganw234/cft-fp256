# The host API

`host/include/cft.h` is the contract between this project and the
people using it. The header was published before the implementation,
deliberately - an ABI is far cheaper to argue with before anything
depends on it than after.

**The software backend is now implemented**, in `host/src/`: about
1,700 lines of C99 in four files, with no dependencies, no configure
step and no generated bindings. `make -C host` builds a static library, a shared
library, and the tools below. The device backend is not built yet, so
`cft_open()` with an artifact path reports `CFT_ERR_NO_DEVICE`;
nothing above the API changes when it lands, which is the point of
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
| C, C++ | include the header | none |
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
