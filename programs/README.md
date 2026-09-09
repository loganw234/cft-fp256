# programs/ - the library of named programs

Orbit-sequencer programs as FILES. The text form, the assembler and
the runner are docs/PROGRAMS.md; the encoding is docs/SEQUENCER.md,
including its "Revision 2 (2026-09-08)" and "Revision 3 (2026-09-08,
evening)" sections.

    programs/
      README.md            this index
      MANIFEST             sha256 of every built image (committed)
      <name>.cfta          the sources
      <name>.<tag>.bank    a bank file for a BANK_EXT program
      out/<name>.cftp      the built images (gitignored)
      build.py check.py    what `make programs` and `make
                           programs-check` run

    make programs         assemble every source with cft-asm, write
                          out/ and MANIFEST
    make programs-check   re-assemble with python/cft_golden/asm.py,
                          compare byte for byte, round-trip through
                          the disassembler, cross-check generated
                          revision-2 and revision-3 corpora in both
                          languages, and run every check below

On Windows, one line:

    PATH="/c/msys64/mingw64/bin:$PATH" make programs-check \
        CC=gcc OS=Windows_NT PYTHON=python \
        TMP='C:/Users/logan/AppData/Local/Temp' \
        TEMP='C:/Users/logan/AppData/Local/Temp'

**A program earns a row by having a check.** Not by being interesting,
and not by assembling: by having something that runs it and compares
the result against the model, a tool's own chain, or a definition. The
check is the last column, and a row whose check cannot run today says
so in the open.

## The index

| program | format | insns | consts | deposits | needs | what it computes | its check |
|---|---|---|---|---|---|---|---|
| `div-fp32` | fp32 | 43 | 6 | 3 | - | the composed divide's on-chip core: seed, 2 Newton steps, the truncating Markstein finish, two branchless restore passes, the exact residual and the midpoint probe | byte-identical to `seqprogs.div_program(fp32)`, and 48 correctly-rounded divides end to end through `positive-run` |
| `div-fp64` | fp64 | 45 | 6 | 3 | - | as above, 3 Newton steps | as above |
| `div-fp128` | fp128 | 47 | 6 | 3 | - | as above, 4 Newton steps | as above |
| `div-fp256` | fp256 | 49 | 6 | 3 | - | as above, 5 Newton steps | as above |
| `sqrt-fp32` | fp32 | 51 | 9 | 3 | - | the composed square root's core: seed, Newton, the half-ulp finish, two restore passes, the exact residual and `d2` | byte-identical to `seqprogs.sqrt_program(fp32)`, and 48 correctly-rounded square roots through `positive-run` |
| `sqrt-fp64` | fp64 | 54 | 9 | 3 | - | as above | as above |
| `sqrt-fp128` | fp128 | 57 | 9 | 3 | - | as above | as above |
| `sqrt-fp256` | fp256 | 60 | 9 | 3 | - | as above | as above |
| `collatz-fp256` | fp256 | 27 | 9 | 4 | - | 1024 Collatz steps with parity read off the encoding and a per-element exactness witness; deposits n, steps, peak, escaped | its nine constants against their derivation from the format, and 64 trajectories against `cft-collatz`'s own records - steps and peak exactly |
| `zoom-scan-fp256` | fp256 | 9 | 1 | 1 | - | 51 iterations of the guarded real-axis map `z <- z^2 + c`, the nucleus scan | 32 real points bit-identical to `seq.py`'s executor running the same image |
| `lowbias32-fp32` | fp32 | 10 | 4 | 1 | `IMUL` | docs/ATLAS.md's draw hash over the index ramp | 4,096 draws against the hash's definition, and the run must signal nothing |
| `horner-bank-fp64` | fp64 | 26 | 24 | 1 | `kx`, `BANK_PTR` | a degree-23 Horner polynomial whose coefficients are the RUN's data | the image carries no constant section (240 = 32 + 8 x 26 bytes); two different banks against a softfloat Horner; and the bank path itself when the library has one |
| `spill-ref-fp64` | fp64 | 82 | 2 | 1 | - | forty terms `x^(k+1)` combined as `acc = fma(acc, 1/2, t_k)`, each consumed the instant it is produced | 64 lanes against a softfloat model of the same recurrence, through `positive-run` |
| `spill-fp64` | fp64 | 161 | 2 | 1 | `SCRATCH` | the same arithmetic with all forty terms live at once, eight of them past the thirty-two registers and all forty in the scratch through `stl`/`ldl` | forty `stl` and forty `ldl` over slots 0..39; then the same deposits as `spill-ref-fp64` and the same model, when the library has the codes |
| `conv-fp64` | fp64 | 19 | 6 | 14 | `SCRATCH` | a sixteen-sample local array written and read under loop counters through `stx`/`ldx`, and a three-tap convolution over it | the six constants against their derivation and no static slot at all; then 24 lanes x 14 outputs against a softfloat three-tap convolution |
| `resume-fp64` | fp64 | 11 | 3 | 16 | `SCRATCH`, `SCRATCH_IO` | eight steps of `v <- 1.5v + 0.25` with a step count, entered and left through the per-run scratch block | `scratch_io` 0x00020002 behind `flags` bit 1; then two runs whose deposits are the two halves of a single sixteen-step run's |
| `horner-wide-fp64` | fp64 | 302 | 300 | 1 | `kx`, `BANK_PTR`, `KX9` | a degree-299 Horner over a 300-entry external bank - 44 coefficients past the 256 a byte of `imm` reaches | 44 ninth index bits in `imm[30:28]`, the bank file against `C[k] = (-1)^k/(k+1)`; then 16 points against a softfloat Horner |

`needs` is what a device must publish before the image will load:
`kx` is CAPS[4], `REGS32` CAPS[5], `BANK_PTR` CAPS[6], `KX9` CAPS[7],
`IMUL` CAPS[28], and revision 3's two are in CAPS2 - `SCRATCH` at
CAPS2[4] and `SCRATCH_IO` at CAPS2[5]. `cft-asm -i` prints the same
list for any image, in that order.

## The families, and where they came from

**`div-*` and `sqrt-*`** are `python/cft_golden/seqprogs.py` as text.
They are the library's own composed divide and square root - the
sequencer's first customer - and their check is byte equality with the
image the model generates. That is the assembler's strongest single
test: forty to sixty instructions of a real correctly-rounded
algorithm, with conditionals as CMPLT/SELECT and ulp steps as
IADD/ISUB on the encoding, and every bit of every word has to land
where the model puts it. The functional arm runs the host's own
`div_prep` / `div_finish` around the image so that the row proves a
DIVIDE and not merely a byte string.

**`collatz-fp256`** and **`zoom-scan-fp256`** are the demo tools'
kernels, at each tool's own defaults. Which of the four tools have a
kernel that is a fixed image at all is the question the round had to
answer by reading them, and the answer is two:

| tool | its program | fixed? |
|---|---|---|
| `cft-collatz` | the whole step | **yes**, once `--steps-per-call` is fixed. Every constant is derived from the format and nothing else varies per run, so `collatz-fp256.cfta` at the default 1024 IS the image the tool loads. |
| `cft-zoom` | the nucleus scan | **yes**, at a given `--period`: its only constant is 4. |
| `cft-zoom` | the reference orbit | no - two of its three constants are the run's centre `cr` and `ci`, so the image is built per run. |
| `cft-orbits` | the symplectic step | no - the constants are `h*d` and `-G*m` per substep, derived from the timestep and the system, and the instruction count depends on `--substeps`, `--samples` and `--stride`. |
| `cft-enclose` | the interval Horner | no - the constants ARE the polynomial's interval coefficients. This is the shape that asked for the constant bank in the first place, and `horner-bank-fp64` below is what the answer looks like. |

A tool that builds per run is not a gap in the library; it is a
program whose data changes, which is exactly what `BANK_EXT` is for
and what the last row demonstrates.

**`lowbias32-fp32`** is docs/ATLAS.md's draw hash, the one caller
`IMUL` exists for, over the index ramp `positive-run --iota` lays
down. It is the smallest complete example of the whole path: a file, a
ramp, a deposit buffer and a hash - and it is the row that proves
`--iota` means the integer BIT PATTERN and not the float.

**`spill-fp64`** and **`spill-ref-fp64`** are one experiment in two
files. Both compute forty terms `t_k = x^(k+1)` and combine them as
`acc = t_0` then `acc = fma(acc, 1/2, t_k)` for k = 1..39 - the same
forty `mul`s and thirty-nine `fma`s, with the same operands, in the
same order. The difference is WHEN each term is consumed. `spill-fp64`
computes all forty first, so that between the phases forty values are
live at once in a machine that has thirty-two registers, and eight of
them have nowhere to be but the scratch; it writes all forty with
`stl` and reads them back with `ldl`. `spill-ref-fp64` consumes each
term the instant it is produced, so no two are ever live, and it needs
no scratch at all.

They must deposit the same bits, because a floating-point operation is
a function of its operands and neither program reorders one. What
differs between the files is eighty scratch accesses on one side and a
single exact `copysign` on the other, and neither of those is
arithmetic. The reference row runs TODAY and is held to a softfloat
model; that is the point of having it as a row rather than as a string
inside `check.py` - when the scratch lands, the spilling program is
compared against something already known good.

**`conv-fp64`** is the indexed form's reason for existing. `stx` and
`ldx` take the slot from the low `log2(SCRATCH_D)` bits of a
register's BIT PATTERN, read as an unsigned integer, which is where an
emitter keeps its loop counters - so one `stx` inside a `repeat`
reaches sixteen slots because the counter moves, where one `stl` would
reach the same slot sixteen times. A register starts a run at `+0`,
whose encoding IS the integer zero, so the counters need no
initialiser; `iadd` on a raw `0x...01` is how they move. It is the one
row with no static slot at all, and `cft-asm -i` says so.

**`resume-fp64`** is R5: the host preloads the first slots of every
lane before a run and reads them back after it, so a program can stop
and continue. It carries two values, the iterate and an integer step
count, and deposits both. The step count is what makes the check a
real claim: the iterate alone would resume correctly even if the block
lost everything else, whereas a block that dropped the count would
deposit steps 1..8 twice instead of 1..8 and then 9..16. The check
runs the program twice, feeding the second run the first run's
`--scratch-out` file, and compares against the same image with its
trip count doubled - an image TRANSFORM, so the longer run is
demonstrably the same program rather than a second source that might
have drifted.

**`horner-wide-fp64`** is R7 and R3 together. Three hundred
coefficients is past the 256 a byte of `imm` reaches under `kx`, so
the last forty-four ride the ninth index bit in `imm[30]`; and the
bank is external, so the image is 2,448 bytes of pure schedule with
the coefficients arriving per run in `horner-wide-fp64.recip.bank` -
`C[k] = (-1)^k / (k+1)`, each the library's own correctly-rounded
quotient rather than a decimal somebody typed, and checked against
that derivation. The source says nothing about `kx` or the ninth bit:
the assembler picks the plain form below sixteen, the indexed form
from sixteen and the ninth bit from 256, and `cft-asm -i` names KX9
among the features the image needs.

**`horner-bank-fp64`** is the `BANK_EXT` worked example. One image,
many polynomials: the image is 240 bytes of pure schedule and the
twenty-four coefficients arrive per run in
`horner-bank-fp64.exp.bank` (the truncated exponential series,
1/(23-k)!) or `horner-bank-fp64.ramp.bank` (1, 2, ..., 24). Its check
reads both from the tree - they are committed DATA, not something the
check writes and then compares against itself - holds each against the
derivation its name claims, runs both and compares against a softfloat
Horner, and asserts that two different banks give two different
answers. A check that passed because it compared against a constant
would be no check at all.

Twenty-four coefficients is past the sixteen a four-bit operand field
reaches, so the FMAs from `C16` on come out in the indexed (`kx`)
form. The assembler chooses that per instruction and the source says
nothing about it, which is the point.

## What is not here yet, and why

- **The `BANK_EXT` path itself.** `cft_program_run_bank` and
  `cft_program_digest` arrive with the host half of the 2026-09-08
  round. Until then `positive-run --capabilities` says `bank-path
  absent`, the check runs the *equivalent constant-carrying image* -
  the same instruction stream with the bank spliced in as an ordinary
  constant section, which is the same computation by the definition of
  the flag - and prints SKIP for the arm it could not run. The day the
  macro exists, that arm runs and additionally requires the two to
  agree bit for bit. Nothing about this is silent.
- **Revision 3's execution arms.** The four scratch rows above
  assemble, disassemble, round-trip and cross-check today, and their
  static arms - constants against their derivation, headers against
  what the sources declare, the ninth index bits against the contract
  - all PASS. What none of them can do yet is RUN: `stl`/`ldl`/`stx`/
  `ldx`, the header's `scratch_io` word and the ninth constant-index
  bit arrive in `seq.py` and in libcft with the other two halves of
  the same round. Until then `positive-run --capabilities` reports

      kx9           absent   (cft.h defines no CFT_SEQ_FEAT_KX9)
      scratch       absent   (cft.h defines no CFT_SEQ_FEAT_SCRATCH)
      scratch-io    absent   (cft.h defines no CFT_SEQ_FEAT_SCRATCH_IO)

  the tool refuses such an image BY NAME rather than running something
  else, and `check.py` prints four SKIPs that say which feature each
  waited on. `spill-ref-fp64` runs today and passes, which is why the
  spill row's reference is a committed program rather than a promise.
- **A program per positive.** docs/ATLAS.md's sixty-eight maps are
  step 3 of that document and belong to `core/emit-cft.mjs` in
  atlas-engine; this library is the shape they will be emitted into.

## Writing one

Read docs/PROGRAMS.md for the text form. In short:

    .format   fp64            ; required, first
    .deposits 2               ; required
    .const    TWO  = 2.0      ; decimal, correctly rounded into the format
    .const    BIG  = 0x1p200  ; a 5.12.3 hex-significand sequence
    .const    MASK = 0x7ff0000000000000   ; a raw encoding, format width
    .reg      x = r3          ; r0, r1, r2 are the a, b, c streams

    fma  x, r0, r1, TWO       ; the operands the opcode READS, in
    add  x, x, TWO            ;   ra, rb, rc field order - ADD reads a and c
    deposit x
    halt

Then

    host/cft-asm mine.cfta -o mine.cftp
    host/cft-asm -i mine.cftp          # header, features, sha256
    host/positive-run mine.cftp --iota 1024

A program that uses the scratch adds `.scratch N` (the depth it
assumes; 256 by default, and a static slot at or past it is refused),
`.slot NAME = N` for a named slot, and `stl`/`ldl` for a static one or
`stx`/`ldx` for one a register indexes. One that wants its state
carried in and out adds `.scratch in N` and `.scratch out M`, and runs
with `positive-run --scratch-in FILE --scratch-out FILE`.

and, to earn a row, a check in `check.py` and a line in the table.
