# Programs as files: the assembler, the library, the runner

*Contract of the 2026-09-08 round, with the round's own results
folded in. Sections marked **BUILT** are what exists; the contract
text is kept wherever it still describes the thing.
docs/SEQUENCER.md defines the program model this serves; revision 2 of
it (five-bit registers, 4,096 instructions, the per-run constant bank)
is assumed throughout.*

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
backend. `programs/` holds twelve programs with a check each, `make
programs-check` runs them in about a second, and the one thing it
cannot do yet is the `BANK_EXT` run path, which needs
`cft_program_run_bank` from the host half of the same round; it says
SKIP and runs the equivalent constant-carrying image in the meantime.
docs/VALIDATION.md's 2026-09-08 entry is the run record.

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
  `setact rA`, `actall`, `halt`. The assembler enforces the loader's
  structural rules (balanced loops, `halt` and `actall` at the top
  level, `repeat 0` refused, the 2^40 worst-case bound) so a file
  that assembles is a file that loads.

Revision 2 is in the text form with no syntax of its own, which is the
point of the encoding's design: `r16..r31` are just registers and the
assembler puts their fifth bits in `imm[27:24]`; `.bank external` is
the header's `flags` bit. `cft-asm -i` names the features an image
needs (`kx`, `REGS32`, `BANK_PTR`, `IMUL`) so a caller learns what to
ask `cft_get_caps` for.

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
  itself against the revision-2 loader's rules. It carries its OWN
  encoder rather than reusing `seq.py`'s, because `seq.py` is
  revision 1 while another lane widens it; `python/tests/test_asm.py`
  pins the two together on the overlap - the same words from
  `seq.encode`, and images that load into `seq.Program` and run
  identically in `seq.run`.
- `host/tools/cft-asm.c` - the tool: `cft-asm in.cfta -o out.cftp`,
  `cft-asm -d image.cftp` to disassemble, `cft-asm -i image.cftp` to
  print the header (format, counts, flags, features, the image's
  SHA-256). It links libcft for `cft_op_name`, the format table and
  the two character conversions, and for nothing else - in particular
  not `cft_program_load`, because an assembler that could only emit
  images this tree's loader already accepts could not write a
  revision-2 program at all.

The two are held to each other by `make programs-check`, on every
source in `programs/` and on a disassemble/re-assemble round trip of
the images `seqprogs.py` generates.

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
compares against the model or a tool's own chain. Twelve so far -
`programs/README.md` is the index and the argument; in brief:

| family | rows | its check |
|---|---|---|
| `div-<fmt>`, `sqrt-<fmt>` | 8 | byte-identical to the image `seqprogs.py` generates, and 48 correctly-rounded divides or square roots each end to end through `positive-run` with the host's own prep and finish either side |
| `collatz-fp256` | 1 | its nine constants against their derivation from the format, and 64 trajectories against `cft-collatz`'s own records - steps and peak exactly |
| `zoom-scan-fp256` | 1 | 32 real points bit-identical to `seq.py`'s executor running the same image |
| `lowbias32-fp32` | 1 | 4,096 draws over the index ramp against docs/ATLAS.md's hash, and the run must signal nothing |
| `horner-bank-fp64` | 1 | the `BANK_EXT` worked example: two different banks against a softfloat Horner, and the two must disagree |

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
                 [--bank bank.bin] [--out deposits.bin] [--device sw|<xclbin>]
                 [--capabilities]

- the image comes from a file; `--iota n` fills stream `a` with the
  element index as a format-width integer bit pattern (`0, 1, 2, ...`)
  and leaves `b` and `c` at `+0` - the index ramp the atlas plates
  take; `--a/--b/--c` read raw format-width streams from files
- `--bank` supplies a `BANK_EXT` program's constants, raw
  format-width values, `n_consts` of them exactly
- out: the per-lane deposit counts (a summary line and, with `--out`,
  the raw deposit buffer), the sticky flags and bus status, the
  program digest (`cft_program_digest`: SHA-256 of image and bank),
  and the SHA-256 of the deposit buffer - the one line a plate's
  attestation needs
- `--capabilities` says which paths THIS BINARY carries, and exits.
  Added by the round: the bank path is compiled under
  `CFT_SEQ_FEAT_BANK_PTR`, so a check script has to be able to ask
  rather than infer it from a failure

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
