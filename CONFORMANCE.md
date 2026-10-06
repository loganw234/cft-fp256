# The cft-fp256 conformance profile

**Profile 3, 2026-10-05** (profile 2 was 2026-10-02 and profile 1
2026-09-16; "Versioning" says why each stepped). This document is the
contract as a specification: what
an implementation must produce to be called cft-fp256 conforming, what
it may choose freely, and the files and hashes that "conforming" is
scored against. It is written so that an implementation can be built
and proven without this repository's RTL or library - a different
chip, a different process, a different language - and still be
interchangeable with them bit for bit. The reasoning behind every rule
is in `docs/DETERMINISM.md`; this file states the rules.

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
- **The reductions** (opcodes 24, 25, 28, 29 and `cft_reduce_seg` over
  them; `maxall`, 31, is exactly associative and commutative, flags
  included, so its order is free and every order gives the model's
  bits): a fixed tree in which each node splits so that its left child
  is the largest power of two strictly below the range, evaluated with
  the caller's attribute at every node; never a sequential accumulation,
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

1. **The vector sets.** `vectors/gen_vectors.py`, run as the Makefile's
   `vectors` target runs it (`--formats fp32 fp64 fp128 fp256 --rounding
   rne rtz rdn rup rmm --directed 3000 --random 4000 --simple 200`, the
   generator's default seed), writes 168 JSON-lines files under
   `vectors/out/`: for each format, the opcode sets at each attribute,
   the transcendental sets, the character-conversion sets, the formatOf
   sets to every format (its own included), the reduction sets, the
   augmented set and the magnitude set - **1,068,915 cases at profiles
   1, 2 and 3**, each line one case with its inputs, its expected result
   and its expected flags. `vectors/SHA256SUMS` lists the SHA-256 of each set,
   and the generator writes LF line endings on every platform so those
   hashes mean one thing everywhere. A generation that finishes also
   writes its own `SHA256SUMS` beside the sets, last, in the same form
   with the names relative to that directory: `sha256sum -c SHA256SUMS`
   there checks that every set is whole, and a comparison with
   `vectors/SHA256SUMS` says whether it is the profile's. A replayer
   that walks the directory takes the `.jsonl` files.
2. **The score.** Every case's result and flags must match exactly. The
   replayers in this repository are `cft-selftest` (from
   `host/tools/cft_selftest.c`; any backend, a device included),
   `bindings/wasm/verify.mjs` (the module), `cpp-api-test` (the C++
   header), `host/tools/serial_replay.py` (a board, over a wire) and the
   Node package's `conformance.mjs`; an independent implementation needs
   its own replayer, which is a loop over the lines.
3. **The identity protocol.** The example in each of eight languages
   (docs/COMPATIBILITY.md; the Fortran example, a ninth, prints decimals
   and is not in the checksum diff) drives the same vectors through the library
   and prints one FNV-1a checksum line per format over the raw output
   encodings:

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

- **The profile versions the bits and the program model.** Profile *N*
  is identified by the generator's parameters and the SHA-256 of each of
  its sets as `vectors/SHA256SUMS` records them, together with the
  golden model that produced them, whose program model (section 6:
  `seq.py`, its loader included) it versions too. The golden model
  states its number in `python/cft_golden/profile.py`, and a version-2
  certificate names it on its `profile` line (`docs/CERTIFICATES.md`,
  "The definition").
- **The rule.** Any change to what an accepted image computes, or to
  whether an image loads, steps it.
  - **A major step** is a change to any recorded bit or flag, or to an
    accepted image's result, flags, STATUS or acceptance: an image that
    loaded and is refused, or one whose run moves by a bit.
  - **A minor step** is an addition that changes no recorded case and no
    accepted image: a new operation or a new set, or an encoding every
    loader refused only because it was unclaimed, now taken (3.1, 3.2,
    ...). An implementation of profile 3 remains conforming to profile 3.
  - Each step has a note here and an entry in `docs/VALIDATION.md`
    saying what changed and why. Never a quiet refresh: a document
    recording a run against an earlier profile is right about that run,
    and stays.
- **The record.** Its record, the golden corpus plus load cases at each
  loader rule's edge and at each header field's encoding extremes, is a
  backstop, not the rule.
  - The golden corpus (`certificates/MANIFEST`: every case's images,
    initial states and boundary states) is held by a gate today, by
    digest. The `programs` stage's corpus check holds every file to its
    SHA-256, has the golden writer make every certificate again and has
    cft-segrun make each one marked for both writers, so a change that
    moves one of its bits fails by name.
  - The vector sets are held by name. The runner's `vectors` stage
    holds each of the 168 sets `vectors/SHA256SUMS` names to a set of
    that name in the generation, and each set to the digest the
    generation recorded itself; a set the generation adds beyond the 168
    is not refused. The replays hold libcft to the model's sets case by
    case, so in the gate budget and the full census a change to one of
    the two fails by set and line (a `verify-quick` or `--only` run may
    replay an older generation, as `verify/README.md` says). The digests are held by
    `vectors/SHA256SUMS` alone, and by a regeneration by hand at the
    profile's parameters, compared with it line for line: `make
    vectors`, then
    `sed 's#  #  out/#' vectors/out/SHA256SUMS | diff vectors/SHA256SUMS -`.
    Profile 3 was checked so (2026-10-05).
  - **A known limit: no gate compares a set's digest with
    `vectors/SHA256SUMS`.** The runner generates at the generator's
    default counts (`--directed 4000 --random 6000 --simple 400`, where
    the profile's are 3000, 4000 and 200), so its twenty opcode sets are
    not the profile's bytes, and it reads the record for names only. A
    change that moves a recorded bit or case - to the model and libcft
    together, or to the generator alone - therefore passes the gate
    budget at the vector sets. The full census's `node` and `wasm` stages
    replay the sets through the committed WebAssembly module too, so a
    change to the model and libcft fails there until the module is
    rebuilt with it, and then passes. From then on, and for a change to
    the generator alone throughout, only the comparison above shows it. It is not closed now: closing it changes
    `verify/run.sh`, which would need a gate run of its own
    (2026-10-05).
  - The load cases are not built yet. For each of the loader's rules
    they would hold an image at its edge, accepted, and one past it,
    refused by name; for each header field, acceptance at its encoding's
    extremes. The extremes are what would have caught ee78152 (below):
    the corpus's images carry at most 8 constants (measured
    2026-10-02).
  - A change the record does not reach steps the profile by the rule
    alone, at its committer's word, as every step did before 2026-10-02.
- **The tree is at profile 3** (2026-10-05), a major step: recorded
  bits moved.
  - **exp2 at x = emin - p.** Its exact value 2^(emin - p) is half the
    smallest subnormal, the tie between +0 and it, which IEEE 754's
    roundTiesToAway (rmm) rounds to the subnormal. The model rounded it
    as a quarter of the subnormal and gave +0: `transcend.py`'s integer
    branch sent every power below the subnormal's, the tie among them,
    to its underflow witness. It now sends the tie to `round_pack`, as
    the exact branches of pow, pown, powr and compound always did, and
    libcft's `transcend.c` does the same. Under rne, rtz, rdn and rup
    the answer was already 754's. Step 6's design study M1 found it (its
    question 5), verifier-VM1 confirmed it, and Logan decided the fix on
    2026-10-05.
  - **Four recorded cases moved, one a format:** exp2 under rmm at
    x = -150, -1075, -16495 and -262379, one line of each
    `fpN-transcend-rmm.jsonl`. The result +0 became the smallest
    subnormal; the flags are 0x18 (underflow, inexact) before and
    after. The other 1,068,911 cases are profile 2's: 164 of the 168
    sets keep their bytes, and `vectors/SHA256SUMS` moved by four
    lines.
  - **A certificate made at profile 2: the rule above, unchanged.**
    Logan (2026-10-05): no certificate exists outside this tree, so
    deprecating profile 2 outright was open, if simpler than carrying
    the bug. Keeping the rule is simpler: it needs no new refusal name,
    no rule and no code. An auditor at profile 3 does not cover
    profile 2, so it re-derives under profile 3:
    - where every re-derivation passes, it accepts, and its verdict
      says its definition does not cover the certificate's;
    - where one fails, it refuses `definition-differs`, never blaming
      the certificate.

    Nothing keeps profile 2's exp2: no auditor, writer or library
    computes it. No profile-2 certificate's bits can depend on the
    change either. A certificate's runs are the program model's, which
    has no transcendental, and its sources are the language's, which
    refuses exp2 by name. The golden corpus's 37 version-2
    certificates were made again at profile 3. Only their `profile`
    and `hash` lines moved, and the seven `supersedes` lines that name
    one of them.
- **Profile 2** (2026-10-02). Profile 1 was 2026-09-16's
  vector sets and model. The rule above took effect with certificate
  format version 2, the first thing that names a profile (Logan's
  decision on `docs/studies/CERT-V2.md`'s question 6, 2026-10-02). Under
  it, the model's changes since 2026-09-16 (`seq.py`'s history) are:
  - **ee78152 (2026-10-01) is a major step.** seq.py's loader began
    refusing images whose header declares more than 512 constants (513,
    600 and 70,000 among them), which the model of 2026-09-16 loaded and
    ran. The old rule kept the number at 1, since no vector moved, so
    an auditor after ee78152 would have covered a certificate made
    before it and refused such an image `program-image`, blaming an
    honest certificate.
  - **Revision 8's forms are minor steps:** augadd and augerr (codes 10
    and 11), the stepped STX and LDX, and quiet, endquiet and raise
    (codes 12 to 14). Every loader before them refused those encodings,
    and every image it accepted computes the same bits.
  - **Revision 7's scratch depth as a run's parameter is a minor step:**
    a run at the default, 256, computes what it computed before, and
    another depth is a choice no run could make before (2026-09-29).
  - Nothing named a profile between them, so they are one major step,
    2. The vector sets did not move: profile 2's 1,068,915 cases are
    profile 1's, and `vectors/SHA256SUMS` is unchanged.
- **The C ABI is a different number.** `CFT_ABI_VERSION` (0.14 when
  profile 1 was set, 0.17 at profile 2, 0.18 at profile 3) versions the
  calling surface of one implementation, not the bits; a device's
  `VERSION` register versions one register map. Neither changes the
  profile, and the profile does not change with them: profile 3 left the
  ABI at 0.18, since no call gained or lost a meaning its definition in
  `cft.h` did not already give it (docs/COMPATIBILITY.md).

### The language's version

The language (`docs/LANGUAGE.md`) has a version of its own since
2026-10-02, beside the profile: a version-2 certificate whose runs name
a source states it on its `language` line.
- **Its home** is `python/cft_golden/lang/version.py`, in the golden
  model beside the language's definition: its checker and its reference
  interpreter, `lang.run`, the definition of correct for every compiled
  image.
- **It started at 1** with certificate format version 2, the first thing
  that names it. The majors the language would have taken before then,
  about four from L1 by verifier-VCV2's count (the step-size-sign
  refusal, D2's `unused` and `too-deep`, and `tangent` reserved), are
  before its count.
- **Its rule is the profile's.** A major step whenever an accepted source
  is refused, or computes another thing: a new keyword an old source used
  as a name, a refusal added, a node's golden function changed. A minor
  step for an addition that changes no accepted source: a function, an
  integrator or a statement the language refused before only because it
  did not have it.
- **What it decides.** An auditor compares a certificate's `profile` and
  `language` with its own. Where its own do not cover the certificate's
  (each major equal, and its minor at least the certificate's), a
  failed re-derivation is refused `definition-differs`, the auditor's
  limit, rather than blamed on the certificate (`docs/CERTIFICATES.md`,
  "The definition").

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
