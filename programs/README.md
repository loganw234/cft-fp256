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
| `divfull-fp32` | fp32 | 210 | 42 | 2 | `kx`, `REGS32`, `BANK_PTR` | the WHOLE divide: class off the encoding, the specials by `select` in `softfloat.div`'s order, subnormals scaled by 2^p, the `div-fp32` core, then `round_pack` in integer instructions; deposits the correctly rounded quotient and its five flags. The rounding mode is the bank's last five words | byte-identical to `divfull.div_full_program(fp32)` (the image libcft carries in `host/src/divfull_images.h`), and 64 raw lanes - specials included - through `positive-run --bank`, both deposits against `softfloat.div` |
| `divfull-fp64` | fp64 | 212 | 42 | 2 | as above | as above, the `div-fp64` core | as above |
| `divfull-fp128` | fp128 | 214 | 42 | 2 | as above | as above, the `div-fp128` core | as above |
| `divfull-fp256` | fp256 | 216 | 42 | 2 | as above | as above, the `div-fp256` core | as above |
| `sqrtfull-fp32` | fp32 | 186 | 49 | 2 | `kx`, `REGS32`, `BANK_PTR` | the WHOLE square root: class off the encoding, the specials in `softfloat.sqrt`'s order (`+-0` as itself, any other negative invalid), a subnormal scaled by an even power, an odd exponent doubled into [2, 4), the `sqrt-fp32` core, then `round_pack`; deposits the root and its flags | byte-identical to `divfull.sqrt_full_program(fp32)`, and 64 raw lanes through `positive-run --bank` against `softfloat.sqrt` |
| `sqrtfull-fp64` | fp64 | 189 | 49 | 2 | as above | as above, the `sqrt-fp64` core | as above |
| `sqrtfull-fp128` | fp128 | 192 | 49 | 2 | as above | as above, the `sqrt-fp128` core | as above |
| `sqrtfull-fp256` | fp256 | 195 | 49 | 2 | as above | as above, the `sqrt-fp256` core | as above |
| `normalabs-fp32` | fp32 | 9 | 5 | 1 | - | the normal-only mask: `\|x\|` where x is normal (either sign), `+0` for zero, subnormal, infinity and NaN - read off the encoding with integer instructions so it signals nothing; the half of cft-rebound's convergence test a program can carry today (docs/ROADMAP.md, workload ask 7) | byte-identical to `seqprogs.normal_abs_program(fp32)`, and 64 raw lanes of every class in both signs through `positive-run` against `softfloat`'s class, no flag raised |
| `normalabs-fp64` | fp64 | 9 | 5 | 1 | - | as above | as above |
| `normalabs-fp128` | fp128 | 9 | 5 | 1 | - | as above | as above |
| `normalabs-fp256` | fp256 | 9 | 5 | 1 | - | as above | as above |
| `collatz-fp256` | fp256 | 27 | 9 | 4 | - | 1024 Collatz steps with parity read off the encoding and a per-element exactness witness; deposits n, steps, peak, escaped | its nine constants against their derivation from the format, and 64 trajectories against `cft-collatz`'s own records - steps and peak exactly |
| `zoom-scan-fp256` | fp256 | 9 | 1 | 1 | - | 51 iterations of the guarded real-axis map `z <- z^2 + c`, the nucleus scan | 32 real points bit-identical to `seq.py`'s executor running the same image |
| `lowbias32-fp32` | fp32 | 10 | 4 | 1 | `IMUL` | docs/ATLAS.md's draw hash over the index ramp | 4,096 draws against the hash's definition, and the run must signal nothing |
| `horner-bank-fp64` | fp64 | 26 | 24 | 1 | `kx`, `BANK_PTR` | a degree-23 Horner polynomial whose coefficients are the RUN's data | the image carries no constant section (240 = 32 + 8 x 26 bytes); two different banks against a softfloat Horner; and the bank path itself, which the library has carried since ABI 0.9 |
| `spill-ref-fp64` | fp64 | 82 | 2 | 1 | - | forty terms `x^(k+1)` combined as `acc = fma(acc, 1/2, t_k)`, each consumed the instant it is produced | 64 lanes against a softfloat model of the same recurrence, through `positive-run` |
| `spill-fp64` | fp64 | 161 | 2 | 1 | `SCRATCH` | the same arithmetic with all forty terms live at once, eight of them past the thirty-two registers and all forty in the scratch through `stl`/`ldl` | forty `stl` and forty `ldl` over slots 0..39; then the same deposits as `spill-ref-fp64` and the same model, which the library has carried since ABI 0.10 |
| `conv-fp64` | fp64 | 19 | 6 | 14 | `SCRATCH` | a sixteen-sample local array written and read under loop counters through `stx`/`ldx`, and a three-tap convolution over it | the six constants against their derivation and no static slot at all; then 24 lanes x 14 outputs against a softfloat three-tap convolution |
| `resume-fp64` | fp64 | 11 | 3 | 16 | `SCRATCH`, `SCRATCH_IO` | eight steps of `v <- 1.5v + 0.25` with a step count, entered and left through the per-run scratch block | `scratch_io` 0x00020002 behind `flags` bit 1; then two runs whose deposits are the two halves of a single sixteen-step run's |
| `horner-wide-fp64` | fp64 | 302 | 300 | 1 | `kx`, `BANK_PTR`, `KX9` | a degree-299 Horner over a 300-entry external bank - 44 coefficients past the 256 a byte of `imm` reaches | 44 ninth index bits in `imm[30:28]`, the bank file against `C[k] = (-1)^k/(k+1)`; then 16 points against a softfloat Horner |
| `lorenz63-rk4-fp64` | fp64 | 62 | 7 | 0 | `REGS32`, `BANK_PTR`, `SCRATCH`, `SCRATCH_IO` | a segment of 100 classic Runge-Kutta steps of Lorenz 1963, the state in and out through the scratch, the parameters as the bank; 53 ALU instructions a step and no control code but the loop's ENDREP | gen_odes.py's output byte for byte (the source with CRLF line ends, written to disk and read back through the same reader, refused); each bank slot against the definition of the name the source gives it (RHO and BETA transposed in the bank, RHO an ulp off, and their two `.const` lines transposed in the source, refused); its numbers against literals in check.py rather than gen_odes.py's constants (each moved one on, and the generator's step count edited and regenerated, refused), and this row's, this page's, the source's and the generator's docstring's statements of them and of the system and scheme against the image (a number moved one on in each, refused); the census, and the golden executor's own count of a step - 54, the ENDREP included; the library's executor, the golden model's and check.py's mirror of the program's rounding order bit for bit over 8 lanes (an operand swap refused); the first two steps from 4 states against textbook Runge-Kutta in exact rationals, within a rounding bound derived from the precision (z' = x y + beta z, stage 4 at h/2 and the 3/8 rule, each a SHARED error - written by the generator and carried by the mirror, which the mirror arm passes - refused); the mirror at 300 digits within round-off (a changed weight refused); two segments chained are one, every lane bit for bit (the second entered with the original state refused) |
| `lorenz63-rk4-fp256` | fp256 | 62 | 7 | 0 | as above | as above | as above |
| `lorenz96-rk4-fp64` | fp64 | 1,455 | 5 | 0 | `BANK_PTR`, `SCRATCH`, `SCRATCH_IO` | 20 Runge-Kutta steps of Lorenz 1996 on a ring of 40: every stage vector in the scratch (200 slots), a four-register window round the ring; 760 ALU instructions, 692 scratch accesses and the loop's ENDREP a step | as above, over 4 lanes, the textbook arm from 2 states, and the executor counting 1,453 a step; the bank's controls transpose H2 and H6 and move F an ulp, the pinned numbers' change the ring to 36 and halve the step count, and x_(i+1) where x_(i-1) belongs takes the z sign's place among the shared errors |
| `lorenz96-rk4-fp256` | fp256 | 1,455 | 5 | 0 | as above | as above | as above |
| `henonheiles-lf-fp64` | fp64 | 23 | 5 | 0 | `BANK_PTR`, `SCRATCH`, `SCRATCH_IO` | 100 Stormer-Verlet steps of Henon-Heiles, drift-kick-drift; 12 ALU instructions a step | as `lorenz63-rk4`, with the textbook step Stormer-Verlet's and its force differentiated out of the potential; the shared errors are the x force with its sign flipped and kick-drift-kick, the bank's controls ONE and TWO transposed and H an ulp off, the 300-digit arm's a half kick, and the resume arm's also a program with its kick Kahan-compensated from step to step, which the textbook arm passes and only the resume arm can refuse |
| `henonheiles-lf-fp256` | fp256 | 23 | 5 | 0 | as above | as above | as above |

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

**`divfull-*` and `sqrtfull-*`** (2026-09-14) are
`python/cft_golden/divfull.py` as text: the same cores with the prep
and the finish moved INTO the instruction stream, so the operands go
in raw and the correctly rounded result and its five flags come out as
two deposits - nothing per element on the host. cft-rebound measured
the split route at 1.6 us an element at binary128 on the card, and
these were written to remove the host's share of it (docs/ROADMAP.md,
workload ask 8); measured the same afternoon, that share was 0.3 us and
the 167 extra instructions cost more, so libcft keeps the split route
by default and takes these on `CFT_DIVSQRT_FULL=1` - their value is the
contract's bits inside a resident program, not a faster call. They
are BANK_EXT so that one image a format serves every rounding
attribute: the bank's last five words are the mode as 0/1, and libcft
builds the bank from the fixed words `python/gen_divfull.py` writes
into `host/src/divfull_images.h` beside these same images - the row's
byte-equality check and the library's generated header are therefore
held to one another through the model. The run arm hands `positive-run`
raw lanes that include every special and compares both deposits.

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

**`lorenz63-rk4-*`, `lorenz96-rk4-*` and `henonheiles-lf-*`**
(2026-09-25) are `gen_odes.py`'s output, and the first programs in the
library written as SEGMENTS: the state enters through the scratch block
and leaves it, the step and the parameters are the run's bank, nothing
is deposited, and a run of any length is the same image with its one
`REPEAT` changed - which is how the check proves that two chained runs
are one run of twice the steps. They are the references an equations-in
ensemble solver is measured against (docs/VALIDATION.md, that date), and
they were written to find out what such programs cost before anything is
built to emit them: three state values or four fit the registers and a
step is all arithmetic; forty do not, and nearly half of Lorenz-96's
instruction stream is scratch traffic, which is the census the next
program-model revision is priced on. The generator is the one definition
of each instruction stream, so the check compares the committed source
with it byte for byte and runs the generator's own `--check`.

The ARITHMETIC is held twice, and the two are not the same claim. A
mirror in `check.py` repeats the program's rounding order, so the
library, the golden model and it agree bit for bit - but it is a second
transcription by the same hand, and an equation or a stage written wrong
in both places passes it. The TEXTBOOK arm shares no transcription with
either: each vector field in its textbook form, classic Runge-Kutta from
its Butcher tableau through a generic stepper, Stormer-Verlet with the
Henon-Heiles force differentiated out of the potential by dual numbers -
in exact rationals, one step at a time from the state the program itself
began that step with. The tolerance is gamma_k a = k u a / (1 - k u),
with the format's unit roundoff u = 2^-p, k the most roundings any term
of the step can pass through and a the step evaluated over absolute
values, both computed alongside the exact step, so nothing in it is
chosen. Its negative controls are wrong programs the generator itself
writes behind a test-only switch, each carried by the mirror too behind
a switch of its own: SHARED errors, the shape that once passed the whole
gate, which the mirror arm passes bit for bit and the textbook arm must
refuse - so an arm re-pointed at the mirror goes red. Among them is the
3/8-rule Runge-Kutta, which has exactly classic Runge-Kutta's linear
behaviour, so that only a nonlinear state tells the two apart; from the
arm's states it landed at least 3 x 10^7 times outside the bound at fp64
and 9 x 10^62 at fp256 (2026-09-25), and the gate prints each ratio. The
arm's code is held apart from the mirror's, the generator's and the
executors' in `check.py` itself: following every name its verdict uses
through the file, no path may reach any of them, by name or as an
attribute, and no definition may serve both the verdict and them,
whatever it is called - a helper shared under a new name once passed a
wrong Lorenz-63 through the whole gate. Both rules read `check.py` only:
a helper in another module, a name built at run time or a copy of the
mirror's code passes them. The bank is held the same way round: the
value in each slot against the definition of the name the SOURCE gives
that slot, so the parameters cannot be transposed inside the generator's
bank list, or the source's `.const` lines moved, without a failure. The
300-digit arm needs mpmath; without it its claim and its control each
say SKIP and why. The textbook arm needs only the standard library.

Each row's numbers - the state size, the steps a segment, the census,
the image's size - are literals in `check.py`, not the generator's
constants, and this index's rows and paragraph, each source's own
comments and the generator's docstring are held to the image, with their
names for the system and the scheme: a ring or a segment changed in
`gen_odes.py` and regenerated fails until each of them says it.
`check.py`'s `_ODE_PROSE` lists the phrases read; the rest of those
texts' words are not. Resumption's control on every row is the second
segment entered with the original state, which watches the plumbing;
Henon-Heiles adds a program whose kick is Kahan-compensated from step to
step - right at every step, so the textbook arm passes it, but carrying
what no segment boundary carries. Its chained run differs from its long
one by one ulp in one or two lanes, so the check compares every lane,
bit for bit - and a change to the lanes, the steps or the states can
take that difference away (with 4 lanes at fp64 no lane differs). Then
the gate asks the golden executor: if its own runs still differ, the
resume arm is blind; if not, it says the control has lost its
difference.

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

## What waited on another half of the round, and no longer does

The first two entries below were written while the halves of the
2026-09-08 round were landing separately. Both have landed; the
paragraphs are kept because the SHAPE of the answer - a capability the
tool reports, a check that says SKIP and names what it waited on, never
a quiet pass - is the part worth keeping.

- **The `BANK_EXT` path itself.** `cft_program_run_bank` and
  `cft_program_digest` arrived with the host half of that round, at
  ABI 0.9 (`cft.h`). While they were missing, `positive-run
  --capabilities` said `bank-path absent`, the check ran the
  *equivalent constant-carrying image* - the same instruction stream
  with the bank spliced in as an ordinary constant section, which is
  the same computation by the definition of the flag - and printed
  SKIP for the arm it could not run. Today the tool prints `bank-path
  present`, that arm runs, and it additionally requires the two to
  agree bit for bit. Nothing about this was ever silent.
- **Revision 3's execution arms.** The four scratch rows above
  assemble, disassemble, round-trip and cross-check, and their static
  arms - constants against their derivation, headers against what the
  sources declare, the ninth index bits against the contract - all
  PASS. They could not RUN until `stl`/`ldl`/`stx`/`ldx`, the header's
  `scratch_io` word and the ninth constant-index bit reached `seq.py`
  and libcft, which is why `positive-run --capabilities` reported

      kx9           absent   (cft.h defines no CFT_SEQ_FEAT_KX9)
      scratch       absent   (cft.h defines no CFT_SEQ_FEAT_SCRATCH)
      scratch-io    absent   (cft.h defines no CFT_SEQ_FEAT_SCRATCH_IO)

  and `check.py` printed four SKIPs naming what each waited on. All
  three landed: `seq.py` carries `STL, LDL, STX, LDX`,
  `FLAG_SCRATCH_IO`, `SCRATCH_D` and `KX9_SHIFT`, and `cft.h` defines
  all three macros, so those lines read `present` and the four SKIPs
  are gone. The mechanism stays - a tool that lacks a feature refuses
  such an image BY NAME rather than running something else.
- **A program per positive.** docs/ATLAS.md's sixty-eight maps are step
  3 of that document and belong to `atlas-engine/core/emit-cft.mjs`;
  this library is the shape they are emitted into - that emitter target
  landed on 2026-09-08.

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
