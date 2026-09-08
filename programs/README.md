# programs/ - the library of named programs

Orbit-sequencer programs as FILES. The text form, the assembler and
the runner are docs/PROGRAMS.md; the encoding is docs/SEQUENCER.md,
including its "Revision 2 (2026-09-08)" section.

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
                          the disassembler, and run every check below

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

`needs` is what a device must publish in `CAPS` before the image will
load: `kx` is CAPS[4], `REGS32` CAPS[5], `BANK_PTR` CAPS[6], `IMUL`
CAPS[28]. `cft-asm -i` prints the same list for any image.

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

**`horner-bank-fp64`** is the `BANK_EXT` worked example. One image,
many polynomials: the image is 240 bytes of pure schedule and the
twenty-four coefficients arrive per run in
`horner-bank-fp64.exp.bank` (the truncated exponential series,
1/(23-k)!) or `horner-bank-fp64.ramp.bank` (1, 2, ..., 24). Its check
runs both and compares against a softfloat Horner, and asserts that
two different banks give two different answers - a check that passed
because it compared against a constant would be no check at all.

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
- **A `REGS32` program.** Five-bit register fields are in both
  assemblers and in `python/tests/test_asm.py`, which builds programs
  that name `r16..r31` and checks the encoding, the refusals and the
  round trip. There is no library ROW for one because nothing can
  execute it yet: `seq.py`'s `NREG` is 16 and so is libcft's executor.
  A row whose check is "it assembles" would be a row pretending to be
  a check.
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

and, to earn a row, a check in `check.py` and a line in the table.
