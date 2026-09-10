# Programs as files: the assembler, the library, the runner

*Contract of the 2026-09-08 round and of its evening round, with both
rounds' own results folded in. Sections marked **BUILT** are what
exists; the contract text is kept wherever it still describes the
thing. docs/SEQUENCER.md defines the program model this serves;
revision 2 of it (five-bit registers, 4,096 instructions, the per-run
constant bank) is assumed throughout, and revision 3 (a per-lane
scratch memory, 16,384 instructions, a 512-entry bank) is the last
section.*

A program has always been data - a header, a constant bank, an
instruction stream - that the host loads with one call and runs with
another, on any backend, with the same bits. What it has not been is a
FILE a person writes. Every program so far was emitted by code: the
model's `encode`, the JavaScript `programImage`, the C the tools carry.
This document adds the three things that turn "write an emitter" into
"drop a file in a folder": a text form with an assembler and
disassembler, a library of named programs with a manifest, and a
runner that takes an image and data in and deposits and a hash out.

**Where it stands.** All three are built and green on the software
backend. `programs/` holds seventeen programs with a check each, `make
programs-check` runs them and generated revision-2 and revision-3
corpora in about twelve seconds. The `BANK_EXT` run path landed with
the host half of the afternoon round and passes; revision 3's own
arithmetic - the four scratch codes, the per-run scratch block and the
ninth constant-index bit - reached `seq.py` and libcft with the
evening round, so the four checks that said SKIP and named what they
waited on now run. docs/VALIDATION.md's two 2026-09-08 entries are the
run records.

## The text form, `.cfta`   **BUILT**

One instruction a line. `;` starts a comment. Names are
case-insensitive; numbers are decimal or `0x` hex; blank lines are
nothing.

    ; newton step for 1/x, one iteration per REPEAT, fp64
    .format   fp64            ; fp32 | fp64 | fp128 | fp256 - required, first
    .deposits 2               ; max_deposits a lane - required
    .const    TWO = 2.0       ; a decimal is correctly rounded into the format
    .const    MASK = 0x7FF0000000000000   ; 0x gives the raw bits, format width
    .reg      y = r3          ; an alias; r0..r2 are the streams a, b, c
    .reg      e = r4

    recip_seed y, r0          ; unary: rd, ra
    repeat 4
      neg   e, r0
      fma   e, e, y, TWO      ; rd, ra, rb, rc - e = 2 - b*y, a constant
      mul   y, y, e           ;   NAME as an operand sets ka/kb/kc, and kx
    endrep                    ;   when any index is >= 16
    deposit y
    halt

(That program is `test_a_hand_written_source_runs_in_the_model` in
`python/tests/test_asm.py`, and it really does produce 1, 0.5, 0.25
and 2 from 1, 2, 4 and 0.5. An example in a specification that has
never been run is a specification of something else.)

Directives:

| directive | meaning |
|---|---|
| `.format F` | the program's precision; required, must come first |
| `.deposits N` | `max_deposits` a lane; required |
| `.bank external` | `flags.BANK_EXT`: the image carries no constants; `.const` lines then declare NAMES and ORDER only, and every run supplies the values |
| `.const NAME = value` | the next constant slot (see the literals below) |
| `.const NAME` | the same, under `.bank external`, where there is no value to give |
| `.reg NAME = rN` | a register alias, `r0..r31` |
| `.slot NAME = N` | a scratch-slot alias, in the same namespace |
| `.scratch N` | the scratch depth the program assumes; 256 by default, a power of two, and a static slot at or past it is refused |
| `.scratch in N` / `.scratch out M` | the per-run scratch block: the header's `scratch_io` word and `flags.SCRATCH_IO` |

A constant literal is one of three things, and the character that
decides is a `p`, which is not a hexadecimal digit:

| form | meaning |
|---|---|
| `2.0`, `-0.0`, `1e-320`, `inf`, `-inf`, `nan` | 754-2019 5.12.2's decimal sequence, correctly rounded into the format under roundTiesToEven - `chars.from_decimal` in the model, `cft_from_decimal_char` in the tool |
| `0x1p237`, `-0x1.8p-3` | 5.12.3's hexadecimal-significand sequence, with the binary exponent the grammar requires. **Added by this round**, and not decoration: at fp128 and fp256 a power of two is otherwise a 64-digit raw word or a 70-digit decimal, and both are transcription hazards where `0x1p237` is a derivation |
| `0x7ff0000000000000` | the RAW ENCODING, at the format's width, zero-extended from however many digits are written. A leading `-` is refused: the word carries its own sign bit |

Instructions:

- an ALU mnemonic is the opcode's `cft_op_name` (`fma`, `add`, `sub`,
  `mul`, `abs`, `neg`, `copysign`, `min`, `max`, `minnum`, `maxnum`,
  `select`, `cmplt`, `cmple`, `cmpeq`, `iand`, `ior`, `ixor`, `iadd`,
  `isub`, `ishl`, `ishr`, `icmplt`, `imul`, `recip_seed`,
  `rsqrt_seed`) followed by `rd` and **the operands the opcode READS**,
  in `ra, rb, rc` field order. That is three for `fma` and `select`,
  two for the binaries, one for the unaries - and two for `add` and
  `sub`, which read `a` and `c` and not `b`, because the pipeline
  steers `b` to 1 itself. `sum`, `dot`, `sumsq` and `sumabs` have
  names in the shared opcode table and are NOT accepted: they are
  reductions `cft_reduce` issues, the sequencer's ALU does not
  implement them, and `opNN` below is how an image carrying one is
  still readable back.
- **all three fields may be written explicitly instead**, in `ra, rb,
  rc` order, when a field the opcode ignores is not zero. The loader
  tolerates that (a unary `abs` with a non-zero `rb` has always
  loaded), so the text form has to be able to say it or a readback
  could not be re-assembled. The disassembler uses the short form when
  the unread fields are zero and the long one when they are not.
- `opNN` (`op24`, `op200`) names an opcode this ISA does not, and
  takes all three fields. It exists for the readback and not for
  writing programs.
- a rounding suffix selects the attribute: `.rne` (the default),
  `.rtz`, `.rdn`, `.rup`, `.rmm`.
- an operand is a register (`r7`), an alias, or a constant name. A
  constant name sets that operand's `k` bit; if any constant index in
  the instruction is 16 or more, the instruction is emitted in the
  `kx` form (indices in `imm`), else in the plain form. **`.kx`**
  forces the indexed form anyway - docs/SEQUENCER.md deliberately does
  not refuse a `kx` instruction whose indices are all below sixteen,
  so the text form must be able to spell one.
- control: `repeat N` / `endrep` (nesting to four), `deposit rA`,
  `setact rA`, `actall`, `halt`, and revision 3's `stl rA, SLOT`,
  `ldl rD, SLOT`, `stx rA, rB`, `ldx rD, rB`. The assembler enforces
  the loader's structural rules (balanced loops, `halt` and `actall`
  at the top level, `repeat 0` refused, the 2^40 worst-case bound, a
  static slot inside the declared depth) so a file that assembles is a
  file that loads.

Revision 2 is in the text form with no syntax of its own, which is the
point of the encoding's design: `r16..r31` are just registers and the
assembler puts their fifth bits in `imm[27:24]`; `.bank external` is
the header's `flags` bit. Most of revision 3 is the same: a constant
name whose index is 256 or more is written exactly like any other, and
the assembler picks the plain form below sixteen, the indexed form
from sixteen, and the ninth bit in `imm[30:28]` from 256. Only the
scratch needed syntax, because it is a new addressable thing.
`cft-asm -i` names the features an image needs (`kx`, `REGS32`,
`BANK_PTR`, `KX9`, `IMUL`, `SCRATCH`, `SCRATCH_IO` - CAPS bit order,
then CAPS2's) so a caller learns what to ask `cft_get_caps` for.

The assembler emits the image the loader wants, exactly: header,
constants, instructions, nothing trailing. The disassembler produces
this text from any valid image, with generated names (`k0`, `k1`, ...)
where the image has none, and `assemble(disassemble(image)) == image`
byte for byte on every program in the corpus - that round trip is a
test, because a readback that cannot be re-assembled is not an
attestation.

Two implementations, held to identical output on the library and on
the corpus:

- `python/cft_golden/asm.py` - the reference: `assemble(text) ->
  bytes`, `disassemble(image) -> str`, and an `Image` that validates
  itself against the revision-3 loader's rules. It carries its OWN
  encoder rather than reusing `seq.py`'s, because `seq.py` reaches a
  revision at a time on its own lane; `python/tests/test_asm.py` pins
  the two together on the overlap - the same words from `seq.encode`,
  and images that load into `seq.Program` and run identically in
  `seq.run` - and gates the three tests that execute a revision-3
  program on a behavioural probe, so they turn themselves on when the
  model lands rather than being switched on by hand.
- `host/tools/cft-asm.c` - the tool: `cft-asm in.cfta -o out.cftp`,
  `cft-asm -d image.cftp` to disassemble, `cft-asm -i image.cftp` to
  print the header (format, counts, flags, features, the image's
  SHA-256). It links libcft for `cft_op_name`, the format table and
  the two character conversions, and for nothing else - in particular
  not `cft_program_load`, because an assembler that could only emit
  images this tree's loader already accepts could not write a
  revision-2 program at all.

The two are held to each other by `make programs-check`, on every
source in `programs/`, on a disassemble/re-assemble round trip of the
images `seqprogs.py` generates, and on two generated corpora. The
**revision-2 corpus** is a hundred-odd programs using five-bit
register fields, an external bank, `kx` chosen and forced, all four
formats and trip counts that set `imm[27:24]`; the **revision-3
corpus** adds the four scratch codes, static slots on both sides of
255 behind a declared depth, indexed slots, per-run scratch blocks and
nine-bit constant indices on each of `ra`, `rb` and `rc`. Both exist
because `seq.random_program` is revision 1 and a library row is
written by a person: without them the round trip would be a round trip
over revision 1 with extra steps, and each stage asserts what it
reached rather than assuming it.

**One thing neither carries: an arity table from libcft.** Which
operand FIELDS an opcode reads is not in `cft_op_name`, in
`cft_supports`, or anywhere else a tool can ask, so each
implementation states it once - `OP_FIELDS` in the model, `OPS[]` in
the tool - and takes the NAMES from its own library's table. That the
two agree is what the byte-for-byte check proves.

## The library, `programs/`   **BUILT**

    programs/
      README.md          the index: one row per program - name, format,
                         instructions, constants, deposits, features it
                         needs (kx, REGS32, BANK_PTR, IMUL), what it
                         computes, which tool or entry checks it
      MANIFEST           sha256 of every built image, written by `make
                         programs`, checked by `make programs-check`
      <name>.cfta        the sources
      <name>.<tag>.bank  a bank file for a BANK_EXT program
      out/<name>.cftp    the built images (gitignored)
      build.py check.py  what the two make targets run

A program earns a row by having a check: something that runs it and
compares against the model or a tool's own chain. Seventeen so far -
`programs/README.md` is the index and the argument; in brief:

| family | rows | its check |
|---|---|---|
| `div-<fmt>`, `sqrt-<fmt>` | 8 | byte-identical to the image `seqprogs.py` generates, and 48 correctly-rounded divides or square roots each end to end through `positive-run` with the host's own prep and finish either side |
| `collatz-fp256` | 1 | its nine constants against their derivation from the format, and 64 trajectories against `cft-collatz`'s own records - steps and peak exactly |
| `zoom-scan-fp256` | 1 | 32 real points bit-identical to `seq.py`'s executor running the same image |
| `lowbias32-fp32` | 1 | 4,096 draws over the index ramp against docs/ATLAS.md's hash, and the run must signal nothing |
| `horner-bank-fp64` | 1 | the `BANK_EXT` worked example: two different banks against a softfloat Horner, and the two must disagree |
| `spill-fp64`, `spill-ref-fp64` | 2 | the same forty-term arithmetic with and without a spill through `stl`/`ldl`; the reference against a softfloat model, and then the two against each other |
| `conv-fp64` | 1 | a three-tap convolution over a local array addressed by loop counters through `stx`/`ldx`, against a softfloat model |
| `resume-fp64` | 1 | two runs carrying state out and back in through `.scratch out` / `.scratch in`, against a single run of twice the length |
| `horner-wide-fp64` | 1 | a degree-299 Horner over a 300-entry external bank - the ninth constant-index bit - against a softfloat Horner |

*A note on the naming.* The contract called for
`divsqrt-<format>.cfta`. A `.cfta` file is one program and
`seqprogs.py` generates two per format, so the library has
`div-<format>` and `sqrt-<format>` - eight files rather than four.

*A note on the demo kernels.* The contract said "as far as each tool's
program is a fixed image rather than one generated per run", and
reading the four tools answered it: only `cft-collatz`'s step and
`cft-zoom`'s nucleus scan are fixed images (given a trip count and a
period, both at the tools' own defaults). `cft-zoom`'s reference orbit
carries the run's centre, `cft-orbits`' step carries the timestep and
the system, and `cft-enclose`'s Horner carries the polynomial itself.
`programs/README.md` has the table and says why, rather than forcing
three programs into a shape they are not in. The third of those is
exactly the shape `BANK_EXT` exists for, which is what
`horner-bank-fp64` demonstrates.

`make programs` assembles every `.cfta` with `cft-asm`, writes `out/`
and `MANIFEST`; `make programs-check` re-assembles with the Python
reference, compares byte for byte, disassembles with both and
re-assembles, and runs every row's check. On Windows:

    PATH="/c/msys64/mingw64/bin:$PATH" make programs-check \
        CC=gcc OS=Windows_NT PYTHON=python \
        TMP='C:/Users/logan/AppData/Local/Temp' \
        TEMP='C:/Users/logan/AppData/Local/Temp'

## The runner, `host/tools/positive-run`   **BUILT**

docs/ATLAS.md's step 3, built on the pattern of the workload tools:

    positive-run <image.cftp> (--iota n | --a A [--b B] [--c C])
                 [--bank bank.bin] [--out deposits.bin]
                 [--scratch-in in.bin] [--scratch-out out.bin]
                 [--device sw|<xclbin>] [--capabilities]

- the image comes from a file; `--iota n` fills stream `a` with the
  element index as a format-width integer bit pattern (`0, 1, 2, ...`)
  and leaves `b` and `c` at `+0` - the index ramp the atlas plates
  take; `--a/--b/--c` read raw format-width streams from files
- `--bank` supplies a `BANK_EXT` program's constants, raw
  format-width values, `n_consts` of them exactly
- `--scratch-in` / `--scratch-out` are revision 3's per-run scratch
  block: raw format-width values, LANE-MAJOR and dense, exactly
  `n * n_scratch_in` (or `n_scratch_out`) elements, checked against
  the image's own header before the library sees either. Each gets its
  SHA-256 on its own line, because what a resumable program entered
  with is as much part of what ran as its image. `--scratch-in` is
  REQUIRED where the header declares one, for the reason `--bank` is;
  `--scratch-out` is a place to write, like `--out`, so it is optional
  and the buffer is allocated and hashed either way
- out: the per-lane deposit counts (a summary line and, with `--out`,
  the raw deposit buffer), the sticky flags and bus status, the
  program digest (`cft_program_digest`: SHA-256 of image and bank),
  and the SHA-256 of the deposit buffer - the one line a plate's
  attestation needs
- `--capabilities` says which paths THIS BINARY carries, and exits.
  Added by the afternoon round for the bank path and extended by the
  evening one: `bank-path`, `digest`, `kx9`, `scratch`, `scratch-io`
  and which of `cft_program_run` / `cft_program_run_bank` /
  `cft_program_run_ex` the binary actually holds. A check script has
  to be able to ASK rather than infer a missing feature from a failure

The runner is the same binary on the software backend, in emulation
and on the card, which is what lets a plate's hash be compared across
all three.

**The `#ifdef`, and why the digest has a fallback.** `BANK_EXT` needs
`cft_program_run_bank`, which arrives with the host half of this
round; without the macro the tool still builds, still runs every
ordinary image, and refuses a `BANK_EXT` one BY NAME rather than
running something else. `cft_program_digest` rides the same macro and
falls back to a local SHA-256 over the image bytes followed by the
bank bytes - which is what the library computes - so the digest a
plate carries does not depend on which half of the tree the runner was
built against. The header line says which of the two produced it.

A run reads, in full:

    image         programs/out/lowbias32-fp32.cftp
    format        fp32
    instructions  10
    constants     4
    deposits      1 a lane
    elements      8  (index ramp)
    device        software
    counts        min 1, max 1, total 8
    flags         0x00000000  clean
    status        0x00000000
    digest        89a66e7e3901918d...  program and bank (computed here:
                                        this build has no cft_program_digest)
    sha256        6290bc41ab11a777b152c69115d5050d3b10ea5968cacd306f79420417d53ffe  deposit buffer


## Revision 3 in the text form, the library and the runner   **BUILT**

*Contract of the 2026-09-08 evening round, with the round's results
folded in; docs/SEQUENCER.md's "Revision 3" is the hardware side.*

### The four scratch codes in the text form

    stl rA, SLOT      scratch[SLOT] := rA
    ldl rD, SLOT      rD := scratch[SLOT]
    stx rA, rB        scratch[rB mod SCRATCH_D] := rA
    ldx rD, rB        rD := scratch[rB mod SCRATCH_D]

`SLOT` is a decimal or `0x` number, or a name declared with
`.slot NAME = N` - an alias, like `.reg`, and in the SAME
case-insensitive namespace, so a slot cannot be spelled the same as
the register it holds. That is deliberate and it bit the round's own
first draft of `resume-fp64.cfta`, whose slots are now `STATE_V` and
`STATE_N`.

The encoding rule for all four is one sentence, and both
implementations state it as a table rather than as a condition per
code: the register fields the code names, plus `imm[23:0]` on the two
static forms, and every other field zero - the other register fields,
their high bits in `imm[27:24]`, `rnd`, `ka`/`kb`/`kc`, `kx` and the
rest of `imm`. Neither a load nor a store is arithmetic, so there is
no rounding attribute and no constant operand on any of them; and none
of the four names `rc`, so `imm[27]` is unread on all four.

`.scratch N` declares the depth the program assumes - a power of two,
256 by default, at most 2^24 because a static slot is `imm[23:0]` -
and a static slot at or past it is refused by name. `.scratch in N`
and `.scratch out M` set the header's `scratch_io` word (`[15:0]` in,
`[31:16]` out) and `flags` bit 1. All three must precede the
instructions: a depth that changed halfway would make the slot bound
depend on where a line sits.

**Either half declares the block, a count of zero included.** The flag
says the word is MEANINGFUL, so a program that carries nothing in and
something out says exactly that, and the disassembler can write back
what it read.

**The depth is not in the image**, because `SCRATCH_D` is a build
parameter of the tile published in `CAPS2[3:0]`. So a readback INFERS
it - the smallest power of two, at least the default 256, that covers
every static slot and both scratch-I/O counts - and both
implementations infer the same number, which the disassembler writes
back as `.scratch N` when it is not the default. A reader that simply
defaulted to 256 would refuse a perfectly legal program written for a
512-slot tile, which is a readback that is not a readback.

### The ninth constant-index bit

A constant name whose index is 256 or more is emitted under `kx` with
the ninth bit in `imm[28]`, `imm[29]` or `imm[30]` for `ka`, `kb` and
`kc`; the bank addresses 512 and a 513th constant is refused. The
SOURCE says nothing about any of it: the assembler picks the plain
form below sixteen, the indexed form from sixteen and the ninth bit
from 256, exactly as it always chose between the plain and indexed
forms. `imm[31]` stays reserved-must-be-zero - it is the cheap version
guard for whatever comes after revision 3 - and a ninth bit set where
it is not read (without `kx`, or on an operand that names a register)
is an unread field and the program is refused, which is the same rule
the register high bits have carried since revision 2.

### `cft-asm -i`, after revision 3

    format        fp64
    instructions  11
    constants     3
    deposits      16
    scratch       highest static slot 1, not indexed
    scratch-io    in 2, out 2
    flags         0x00000002  SCRATCH_IO
    bytes         144
    features      SCRATCH SCRATCH_IO
    sha256        a9a0bd34d04d9bce1bcec9b950eb459df1bc42c20c6cd3769887c40e2e37e1e1

Two lines are new. `scratch` is `-` when the program never touches the
memory, and otherwise reports the highest STATIC slot and whether the
program indexes at all - one past the highest static slot is what
`cft_program_info` calls `scratch_used`, and an indexing program uses
the whole depth by construction. `scratch-io` is `-` or the two
counts. The feature list gains `KX9`, `SCRATCH` and `SCRATCH_IO`, in
CAPS bit order followed by CAPS2's: `kx` [4], `REGS32` [5],
`BANK_PTR` [6], `KX9` [7], `IMUL` [28], then `SCRATCH` CAPS2[4] and
`SCRATCH_IO` CAPS2[5]. The depth is deliberately NOT reported, because
it is not a property of the image.

### The library's five new rows

| program | what it is for |
|---|---|
| `spill-fp64` | forty terms live at once in a machine with thirty-two registers, all forty through `stl`/`ldl` |
| `spill-ref-fp64` | the same forty `mul`s and thirty-nine `fma`s, same operands, same order, each term consumed the instant it is produced - so nothing is ever spilled |
| `conv-fp64` | sixteen samples written under a loop counter with `stx` and read back with `ldx` for a three-tap convolution: the indexed form's reason for existing |
| `resume-fp64` | eight steps of an iteration entered and left through the per-run block, carrying an iterate AND an integer step count |
| `horner-wide-fp64` | a degree-299 Horner over a 300-entry external bank, forty-four coefficients past the 256 a byte of `imm` reaches |

The spill pair is one experiment in two files, and the reference is a
ROW rather than a string inside `check.py` because it runs TODAY and
passes against a softfloat model - so when the scratch lands, the
spilling program is compared against something already known good.
The two must deposit the same bits: a floating-point operation is a
function of its operands and neither program reorders one, so what
differs between the files is eighty scratch accesses on one side and a
single exact `copysign` on the other, and neither of those is
arithmetic.

`programs/README.md` carries the full rows and the argument for each.

### `positive-run --scratch-in` and `--scratch-out`

Raw format-width values, LANE-MAJOR and dense - lane i's slot s is
element `i * n_scratch_in + s` - exactly `n * n_scratch_in` elements,
checked against the image's own header before the library sees either.
Each is hashed on its own line:

    scratch-in    <sha256>  state0.bin, 512 bytes (32 lanes x 2)
    scratch-out   <sha256>  state1.bin, 512 bytes (32 lanes x 2)

The `digest` line is unchanged - image then bank, which is what
`cft_program_digest` returns - because a digest answers "which program
and which constants", and the block a run entered with is a third
thing that deserves its own number rather than being folded into that
one.

The run goes through `cft_program_run_ex` and `cft_run_args`, ABI
0.10's one entry point that takes everything a run can carry,
compiled under `CFT_SEQ_FEAT_SCRATCH_IO`.

### What waited on the other halves, and how it said so

`stl`/`ldl`/`stx`/`ldx`, the header's `scratch_io` word and the ninth
constant-index bit reached the assemblers, the library, `test_asm.py`
and a generated revision-3 corpus before `seq.py` and libcft carried
them, because each moves on its own lane. For that interval none of
them could RUN, and this is the machinery that said so - kept written
down, because the next revision will use it again. All three have
since landed (`seq.py`'s `STL, LDL, STX, LDX`, `SCRATCH_D` and
`KX9_SHIFT`; `cft.h`'s `CFT_SEQ_FEAT_KX9`, `_SCRATCH` and
`_SCRATCH_IO`), so every line below now reads the other way.

- `positive-run --capabilities` reported `kx9`, `scratch` and
  `scratch-io` as `absent`, naming the `cft.h` macro each was missing,
  and said which run path the binary actually held - today all three
  read `present`;
- the tool refuses such an image BY NAME - naming the feature and the
  section of the contract that carries it - rather than running
  something else or letting `cft_program_load` report an unknown
  control code;
- `programs/check.py` ran each new row's STATIC arm (constants
  against their derivation, headers against what the sources declare,
  the ninth index bits against the contract) and printed four SKIPs
  that each said which feature the execution arm waited on;
- `test_asm.py`'s three model-executing tests are gated on a
  BEHAVIOURAL probe - each assembles the smallest program that needs
  its feature and asks `seq.run` to run it - so they turned themselves
  on the day the model landed, with nothing to switch by hand.

This is the shape the round before used for the `BANK_EXT` path, which
landed the same way.
