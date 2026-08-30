# The host API

`host/include/cft.h` is the contract between this project and the
people using it. The header is written; the implementation follows.
Publishing the shape first is deliberate - an ABI is far cheaper to
argue with before anything depends on it than after.

## The shape of the thing

One call does the work:

```c
cft_run(dev, CFT_FMA, CFT_FP256, CFT_RNE, a, b, c, d, n, &flags, NULL);
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
tested (2.14 and 2.19), so `FLAGS` and `STATUS` are currently
unreadable from Python. XRT's C++ API does expose them. The C library
fixes that as a side effect rather than as a special effort.

## What the library absorbs so callers never see it

Every one of these is a place the hardware contract is sharper than a
user should have to care about:

- **Beat padding.** The tile works in whole 256-bit beats. `cft_run`
  takes an arbitrary `n`, pads the tail internally, and makes sure
  padding contributes nothing to the flags.
- **Multi-tile partitioning.** A four-CU bitstream has four sets of
  FLAGS and STATUS registers. The library splits the work, ORs the
  sticky words, and reports one result. Callers never learn tiles
  exist; `cft_get_caps` reports the count for the curious.
- **Buffer staging.** `cft_run` takes host pointers and does the
  device round trip itself. `cft_alloc` exists for when that round
  trip is the bottleneck, and degrades to plain allocation on the
  software backend so the code stays portable.
- **Bus faults.** A bad pointer or a fabric error becomes
  `CFT_ERR_BUS_FAULT`, distinct from a wrong answer, because
  "the memory never delivered this" and "the arithmetic is wrong" want
  different responses.

## What is deliberately not in the first version

- **Reductions** (`dot`, `sum`). They change the output shape and the
  determinism argument - the tree order must be fixed by element index
  - so they get their own entry point rather than an overloaded
  `cft_run`.
- **Programs.** When the on-chip sequencer lands, a `cft_program`
  family sits beside `cft_run` rather than replacing it. `cft_run` was
  designed knowing this is coming.
- **Asynchronous submission.** Everything blocks today. A future
  `cft_run_async` returning a handle is additive.

New capability gets new functions. That keeps `cft_run` positional and
FFI-friendly rather than hiding behind an extensible descriptor struct
that every binding then has to lay out by hand.

## Verifying a port

`cft_conformance()` replays `vectors/*.jsonl` through whichever backend
is open and reports the first disagreement.

This is the acceptance test for a new language binding, a new backend,
a new device generation, or somebody else's independent
implementation. The guarantee at the top of this document is not
something to take on trust - it is machine-checkable, and the vectors
have existed since before the hardware did.

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
