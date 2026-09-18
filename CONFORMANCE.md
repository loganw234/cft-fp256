# The cft-fp256 conformance profile

**Profile 1, 2026-09-16.** This document is the contract as a
specification: what an implementation must produce to be called
cft-fp256 conforming, what it may choose freely, and the files and
hashes that "conforming" is scored against. It is written so that an
implementation can be built and proven without this repository's RTL
or library - a different chip, a different process, a different
language - and still be interchangeable with them bit for bit. The
reasoning behind every rule is in `docs/DETERMINISM.md`; this file
states the rules.

## Two levels, and they are not the same thing

**Level A - IEEE 754-2019 in radix 2.** `docs/COMPLIANCE.md` is the
clause-by-clause map: binary32, binary64 and binary128 as arithmetic
and interchange formats, binary256 as a further one, every clause-5
operation, every clause-9 recommended operation for binary formats,
all five rounding-direction attributes, the status word of 7.1.

**Level B - the cft-fp256 profile.** Level A, plus every choice the
standard leaves to the implementation fixed to one answer, plus
operations the standard does not define. The relationship runs one
way:

> An implementation conforming to the cft-fp256 profile conforms to
> IEEE 754-2019 in radix 2 for the operations the profile covers. The
> converse does not hold: a 754-conforming implementation that makes a
> different legal choice on any item in the table below is NOT
> cft-fp256 conforming, and a 754 implementation has no answer for the
> operations 754 does not define.

| the profile is... | on what |
|---|---|
| **stricter than 754** | the reduction tree and its empty and single-element cases; tininess detected after rounding; the canonical quiet NaN as every NaN result of a computational operation; which operand a selection passes through and that it signals nothing; the sign of every exact zero; the flags of the scaled products; the reserved rounding encodings; the flags of composed operations (division, square root, the transcendentals) exactly as 754 asks of a correctly rounded operation, with no relaxation |
| **additional to 754** | the seed opcodes, the integer opcodes, `select`, the comparisons as opcodes, `maxall`, the segmented reductions, the program model (deposits, counts, the constant bank, the scratch, the index tables, the lane mask), the status word of a device, the memory layouts |
| **silent on 754** | the decimal formats; clause 8's alternate exception handling; NaN payload propagation through arithmetic (6.2.3, a recommendation, deliberately not followed); extended and extendable precisions |

Each row's items are normative below. "Normative" means: an
implementation that produces a different bit or a different flag on
any of them is not conforming, whatever the standard would allow.

## What a conforming implementation must produce

Every item names the document that holds its detail and the definition
that settles it. **`python/cft_golden` is the definition.** Where prose
and the golden model disagree, the model is right and the prose is a
bug to fix.

### 1. Formats and encodings

- binary32, binary64, binary128 and binary256 with 754-2019's
  parameters (3.4, 3.6: binary256 has p = 237 and emax = 262143).
- Observable buffers are dense arrays of interchange encodings,
  little-endian, element *i* at byte offset `i * width / 8`. A
  per-lane block (the scratch preload and the scratch-out block) is
  lane-major: lane *i*'s slot *s* at element `i * slots + s`. An index
  table is one unsigned 32-bit integer per element, little-endian.
  (`docs/HOSTAPI.md`, "Device-resident buffers" and "ABI 0.14";
  `docs/ARCHITECTURE.md`, the layout rules.)
- An implementation's internal representation, beat width and pipeline
  are its own. Only the buffers are contract.

### 2. Rounding attributes

Five, selected per operation, and exactly five: roundTiesToEven (the
default and what "the contract" means unless a run says otherwise),
roundTowardZero, roundTowardNegative, roundTowardPositive,
roundTiesToAway. The three-bit encoding is RISC-V's `frm`: 0, 1, 2, 3,
4. The encodings 5 to 7 are reserved and an implementation must not let
a caller depend on them - the golden model refuses them; a device may
treat them as roundTiesToEven, and a library must refuse before a
device sees one. roundTiesTowardZero (9.5) is not an attribute: it
exists only inside the augmented operations, which take no attribute.
(`docs/DETERMINISM.md`, "Rounding".)

### 3. The opcodes

Thirty-one opcodes, each defined by the golden model, each taking the
attribute above where it rounds. Opcode 15 and every number above 31
are unassigned: they return the canonical quiet NaN with **invalid**
raised, in hardware and in the model alike, so that a caller issuing
one learns it now rather than under a later assignment.

| group | opcodes | definition |
|---|---|---|
| arithmetic | 0 `fma`, 1 `add`, 2 `sub`, 3 `mul` | 754 5.4.1, single rounding; `fma` is fused |
| sign | 4 `abs`, 5 `neg`, 6 `copysign` | 754 5.5.1: the encoding is changed and nothing signals, a signaling NaN included |
| min/max | 7 `min`, 8 `max`, 9 `minnum`, 10 `maxnum` | 754-2019 9.6: `min`/`max` are minimum/maximum (a NaN operand gives the canonical quiet NaN, a signaling NaN raises invalid), `minnum`/`maxnum` are minimumNumber/maximumNumber (the number wins over a NaN, quiet or signaling, and a signaling one raises invalid without being converted); -0 orders below +0 in all four, so `min(+0, -0)` is -0 and `max(+0, -0)` is +0 |
| predicate, select | 11 `select`, 12 `cmplt`, 13 `cmple`, 14 `cmpeq` | the quiet predicates of 5.11 - they signal only on a signaling NaN and an unordered pair makes every one false - with results exactly 1.0 or +0.0 in the format; `select` is `d = c != 0 ? a : b` and moves the chosen operand through intact, payload and all, signalling nothing |
| integer | 16 `iand`, 17 `ior`, 18 `ixor`, 19 `iadd`, 20 `isub`, 21 `ishl`, 22 `ishr`, 23 `icmplt`, 30 `imul` | on the encodings as unsigned integers of the format's width, `imul` the low 32 bits of an unsigned 32 x 32 product at every format; none of them rounds, consults the attribute or can be inexact, and none raises a flag |
| reduction | 24 `sum`, 25 `dot`, 28 `sumsq`, 29 `sumabs`, 31 `maxall` | section 5 below |
| seeds | 26 `recip_seed`, 27 `rsqrt_seed` | the exact bit patterns the golden model tabulates; relative error below 2^-8.5 is a property, the bits are the contract |

(`docs/ARCHITECTURE.md`, the opcode table; `docs/DETERMINISM.md`,
"Operations" and "The non-arithmetic operations".)

### 4. The library operations

Every operation of 754 clause 5 and clause 9 for binary formats, as
`docs/COMPLIANCE.md` lists them, defined by the golden model and
correctly rounded where 754 asks it: division and square root (composed
from the seeds and `fma`, correctly rounded with the flags of 5.4.1);
the thirty-nine functions of table 9.1; the augmented operations; the
conversions of 5.4 and the character conversions of 5.12 at every digit
count; the magnitude forms of 9.6; the payload operations of 9.7;
roundToIntegral, remainder, scaleB/logB, nextUp/nextDown,
classification, totalOrder, the signaling comparisons, the cross-format
arithmetic and comparison. A conforming implementation provides every
one of them for every format it claims, and the composition in
`host/src` is one way to do it, not the only way: what is scored is the
bits and the flags.

### 5. The fixed choices

- **NaN.** Any NaN in, one canonical quiet NaN out of every
  computational operation: sign 0, exponent all ones, quiet bit set,
  payload zero. A signaling NaN operand raises invalid. `abs`, `neg`,
  `copysign`, `select`, the character conversions and the 9.7 payload
  operations pass patterns through intact and signal nothing.
- **Tininess** is detected after rounding (7.5 allows either).
- **The sign of an exact zero** follows 6.3 exactly, including the two
  rules usually missed: an exactly zero sum of unlike-signed operands is
  +0 in every attribute except roundTowardNegative, where it is -0;
  like-signed zeros keep their sign; a zero product carries the XOR of
  the operand signs; an `fma` that is zero because of rounding takes
  the sign of the exact result.
- **The reductions** (opcodes 24, 25, 28, 29, 31 and `cft_reduce_seg`):
  a fixed tree in which each node splits so that its left child is the
  largest power of two strictly below the range, evaluated with the
  caller's attribute at every node; never a sequential accumulation,
  never reassociated, never padded. n = 0 gives +0 and raises nothing
  for `sum`, `dot`, `sumsq` and `sumabs`, and **-infinity** for
  `maxall`; n = 1 returns the element verbatim with no flag, a signaling
  NaN included. `dot(a, b)` is `sum(mul(a, b))` exactly, flags included.
  A segmented reduction is the same tree over each slice of `seg`
  elements, `n / seg` results, and is defined by that identity. The
  scaled products of 9.4, their signs, flags and empty-vector values,
  are fixed in `docs/DETERMINISM.md`, "The rest of clause 9.4's
  reductions". (`python/cft_golden/reduce.py`.)
- **Partitioning** across tiles, threads or machines is free provided
  the tree order holds: four tiles must return what one returns, flags
  included.

### 6. The program model

A program is an image - header, constant bank, instruction stream -
whose meaning is defined by `python/cft_golden/seq.py` and whose text
form is defined by the assembler in `python/cft_golden/asm.py`
(`docs/SEQUENCER.md`, "The shape of a program"; `docs/PROGRAMS.md`).
A conforming implementation runs an image bit for bit as the model
does, or refuses it by name before running anything. The normative
points a reader most often needs:

- **Deposits.** Each lane's deposit window is `max_deposits` slots; a
  slot no lane wrote reads +0 in the format, for the lanes the run
  owns; the per-lane count is an output. A lane depositing past its
  window sets the overflow status bit and writes nothing past it.
- **The scratch.** Per lane, `SCRATCH_D` slots. An indexed access at or
  past the depth is reduced modulo the depth, unless the image asks
  for `SCRATCH_STRICT`, in which case it is reported in status and
  nothing is written. A per-run block may fill the first
  `n_scratch_in` slots of every lane and hand back the first
  `n_scratch_out`.
- **The constant bank** is per-run data when the header says so, and
  an image's digest covers the image and the bank.
- **Index tables.** With a table on a stream, element *i* of that
  stream is `source[idx[i]]`; `CFT_IDX_NONE` (0xFFFFFFFF) is +0 in the
  format and no read; an entry at or past the source's declared length
  is refused before any element is read. The scratch preload's table is
  lane-major like the block it fills. A gathered run computes exactly
  what the dense run over the gathered inputs computes.
- **The lane mask.** One bit per lane, bit *i* lane *i*, set for a
  lane that runs. A masked lane runs no instruction; its deposit slots,
  its count and its scratch-out slots hold what the caller put there;
  it contributes no flag and no status bit; `ACTALL` does not revive it;
  an all-ones mask is bit-identical to no mask; a run whose every lane
  is masked completes with nothing written and flags of zero.
- **Refusal, not approximation.** An image that needs a capacity or a
  feature the implementation lacks is refused by name before it runs;
  a run mode the implementation cannot honour is refused; a mode bit
  the run's kind does not read is ignored. Nothing is ever computed
  "as well as possible".

### 7. Flags and status

The five exceptions of 754 clause 7 are reported per run as sticky
flags, raised by the operations that raise them and lowered only by
the caller. A library's status word is on its handle, raised by every
operation and lowered only by the caller, with the six operations of
5.7.4 over it (`docs/DETERMINISM.md`, "The status word"). A device's
status word reports a refused run, a memory fault and a deposit
overflow as distinct bits, and a refused run touches no memory.

## What an implementation may choose freely

Clock frequency and pipeline depth; the number of tiles, threads or
machines and how work is partitioned among them (the tree order
holding); the process technology; the backend - software, FPGA, ASIC,
or a tile behind a socket; the language and the calling convention;
internal layouts, beat widths and burst sizes; the capacities it
announces (deposit slots, instructions, constants, scratch depth),
provided an image exceeding them is refused by name. **Determinism is
clock-independent**: a slower conforming implementation is a complete
one, and two conforming implementations of any speed agree on every
bit.

## The conformance test

Conformance is scored, not read.

1. **The vector sets.** `vectors/gen_vectors.py`, run as the
   Makefile's `vectors` target runs it (`--formats fp32 fp64 fp128
   fp256 --rounding rne rtz rdn rup rmm --directed 3000 --random 4000
   --simple 200`, the generator's default seed), writes 168 JSON-lines
   files under `vectors/out/`: for each format, the opcode sets at each
   attribute, the transcendental sets, the character-conversion sets,
   the formatOf sets to each other format, the reduction sets, the
   augmented set and the magnitude set - **1,068,915 cases at profile
   1**, each line one case with its inputs, its expected result and its
   expected flags. `vectors/SHA256SUMS` lists the SHA-256 of each set,
   and the generator writes LF line endings on every platform so those
   hashes mean one thing everywhere.
2. **The score.** Every case's result and flags must match exactly.
   The replayers in this repository are `cft-selftest` (from
   `host/tools/cft_selftest.c`; any backend, a device included), `bindings/wasm/verify.mjs` (the
   module), the Python package's test suite and the Node package's
   `conformance.mjs`; an independent implementation needs its own
   replayer, which is a loop over the lines.
3. **The identity protocol.** Every binding and language example drives
   the same vectors through the library and prints one FNV-1a checksum
   line per format over the raw output encodings:

       fp32   0x9af9d3973816adcf
       fp64   0x04110a4c30c6df4d
       fp128  0xb815aa4a3a3eb024
       fp256  0x0eea048c14040a4e

   The same four lines from any implementation, on any platform, are
   the whole compatibility test (`docs/COMPATIBILITY.md`).
4. **A device.** `host/tests/device_test.c` compares a device against
   the software backend bit for bit across the elementwise operations,
   the reductions, the programs, the tables and the mask, and the
   replay of the sets on the device is the same score as on a host.
5. **The independent oracle.** GNU MPFR arbitrates every operation it
   can reach, at the format's precision and the caller's attribute
   (`host/tools/mpfr_check.c`), which is how the model itself is held
   to something outside this project. A second outside reference
   covers what MPFR cannot, a whole program: a GPU's own record of a
   real binary32 workload, a million samples a pass, which the library
   and a tile both reproduce bit for bit (`host/tests/photograph`, the
   runner's `photograph` stage). It is evidence about this
   implementation, not part of the profile's score.
   `docs/VALIDATION.md` carries every run.

## Versioning

- **The profile version is the vectors.** Profile *N* is identified by
  the generator's parameters and the SHA-256 of each of its sets as
  `vectors/SHA256SUMS` records them, together with the golden model
  that produced them. Profile 1 is 2026-09-16.
- **A change to any recorded bit or flag is a new profile number**, with
  a note here and an entry in `docs/VALIDATION.md` saying which cases
  changed and why. Never a quiet refresh: a document recording a run
  against an earlier profile is right about that run, and stays.
- **An addition is a minor step**: a new operation or a new set that
  changes no recorded case extends the profile (1.1, 1.2, ...); an
  implementation of profile 1 remains conforming to profile 1.
- **The C ABI is a different number.** `CFT_ABI_VERSION` (0.14 at
  profile 1) versions the calling surface of one implementation, not
  the bits; a device's `VERSION` register versions one register map.
  Neither changes the profile, and the profile does not change with
  them.

## The documents this rests on

| for | read |
|---|---|
| the reasoning behind every fixed choice, and the clause locator | `docs/DETERMINISM.md` |
| the IEEE 754-2019 clause map (Level A) | `docs/COMPLIANCE.md` |
| the definition | `python/cft_golden` (`softfloat.py`, `reduce.py`, `seq.py`, `asm.py`, `chars.py`, the transcendental modules) |
| the program model and its revisions | `docs/SEQUENCER.md`, `docs/PROGRAMS.md` |
| one implementation's calling surface | `docs/HOSTAPI.md`, `host/include/cft.h` |
| one implementation's register map and layouts | `docs/ARCHITECTURE.md` |
| the identity protocol and every surface's status | `docs/COMPATIBILITY.md` |
| what this implementation can do today | `CAPABILITIES.md` |
| every run, including the failed ones | `docs/VALIDATION.md` |

## Using the name

The profile carries this repository's name and its licence
(Apache-2.0). An implementation that passes the test above for the
formats it claims may say it conforms to the cft-fp256 profile, naming
the profile number and the formats. An implementation that passes for
some operations and not others may say which; it may not say
"conforming" for the whole.
