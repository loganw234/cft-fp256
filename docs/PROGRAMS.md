# Programs as files: the assembler, the library, the runner

*Contract of the 2026-09-08 round. The sections marked "built" are
filled in by the round; everything else here is what the round builds
against. docs/SEQUENCER.md defines the program model this serves;
revision 2 of it (five-bit registers, 4,096 instructions, the per-run
constant bank) is assumed throughout.*

A program has always been data - a header, a constant bank, an
instruction stream - that the host loads with one call and runs with
another, on any backend, with the same bits. What it has not been is a
FILE a person writes. Every program so far was emitted by code: the
model's `encode`, the JavaScript `programImage`, the C the tools carry.
This document adds the three things that turn "write an emitter" into
"drop a file in a folder": a text form with an assembler and
disassembler, a library of named programs with a manifest, and a
runner that takes an image and data in and deposits and a hash out.

## The text form, `.cfta`

One instruction a line. `;` starts a comment. Names are
case-insensitive; numbers are decimal or `0x` hex; blank lines are
nothing.

    ; newton step for 1/x, one iteration per REPEAT, fp64
    .format   fp64            ; fp32 | fp64 | fp128 | fp256 - required, first
    .deposits 4               ; max_deposits a lane - required
    .const    TWO = 2.0       ; a decimal is correctly rounded into the format
    .const    MASK = 0x7FF0000000000000   ; 0x gives the raw bits, format width
    .reg      x  = r3         ; an alias; r0..r2 are the streams a, b, c
    .reg      y  = r4

    recip_seed y, r0          ; unary: rd, ra
    repeat 4
      fma   x, y, r0, TWO     ; rd, ra, rb, rc - a constant NAME as an operand
      mul   y, y, x           ;   sets ka/kb/kc, and kx when any index is >= 16
    endrep
    deposit y
    halt

Directives:

| directive | meaning |
|---|---|
| `.format F` | the program's precision; required, must come first |
| `.deposits N` | `max_deposits` a lane; required |
| `.bank external` | `flags.BANK_EXT`: the image carries no constants; `.const` lines then declare NAMES and ORDER only, and every run supplies the values |
| `.const NAME = value` | the next constant slot; a decimal literal is rounded into the format (round-to-nearest-even, the model's `round_pack`), `0x` is the raw encoding, `inf`, `-inf`, `nan` and `-0.0` spell what they say |
| `.reg NAME = rN` | a register alias, `r0..r31` |

Instructions:

- an ALU mnemonic is the opcode's `cft_op_name` (`fma`, `add`, `sub`,
  `mul`, `abs`, `neg`, `copysign`, `min`, `max`, `minnum`, `maxnum`,
  `select`, `cmplt`, `cmple`, `cmpeq`, `iand`, `ior`, `ixor`, `iadd`,
  `isub`, `ishl`, `ishr`, `icmplt`, `imul`, `recip_seed`,
  `rsqrt_seed`, ...) followed by `rd` and the operands the opcode
  reads - three for a ternary, two for a binary, one for a unary - in
  the order `ra, rb, rc`. Unread fields are emitted as zero, which is
  what the loader requires.
- a rounding suffix selects the attribute: `.rne` (the default),
  `.rtz`, `.rdn`, `.rup`, `.rmm`.
- an operand is a register (`r7`), an alias, or a constant name. A
  constant name sets that operand's `k` bit; if any constant index in
  the instruction is 16 or more, the instruction is emitted in the
  `kx` form (indices in `imm`), else in the plain form.
- control: `repeat N` / `endrep` (nesting to four), `deposit rA`,
  `setact rA`, `actall`, `halt`. The assembler enforces the loader's
  structural rules (balanced loops, `halt` and `actall` at the top
  level, `repeat 0` refused, the 2^40 worst-case bound) so a file
  that assembles is a file that loads.

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
  bytes`, `disassemble(image) -> str`. It is checked against
  `seq.encode`/`seq.decode` and against the model's executor.
- `host/tools/cft-asm.c` - the tool: `cft-asm in.cfta -o out.cftp`,
  `cft-asm -d image.cftp` to disassemble, `cft-asm -i image.cftp` to
  print the header (format, counts, flags, the image's SHA-256).

## The library, `programs/`

    programs/
      README.md          the index: one row per program - name, format,
                         instructions, constants, deposits, features it
                         needs (kx, REGS32, BANK_PTR), what it computes,
                         which tool or entry checks it
      MANIFEST           sha256 of every built image, written by `make
                         programs`, checked by `make programs-check`
      <name>.cfta        the sources
      out/<name>.cftp    the built images (gitignored)

A program earns a row by having a check: something that runs it and
compares against the model or a tool's own chain. The first entries
the round writes:

- `divsqrt-<format>.cfta` (from `seqprogs.py`): the library's own
  composed divide and square root as text - and the test that the
  assembled image equals the one the library generates, byte for
  byte, which is the assembler's strongest single check.
- the demo tools' kernels (`collatz`, `orbits`, `zoom`, `enclose`),
  as far as each tool's program is a fixed image rather than one
  generated per run; each with the tool as its check.
- one `BANK_EXT` example whose constants are the run's data, with a
  bank file beside it, as the runner's worked example.

`make programs` assembles every `.cfta` with `cft-asm`, writes
`out/` and `MANIFEST`; `make programs-check` re-assembles with the
Python reference, compares byte for byte, and runs every row's check.

## The runner, `host/tools/positive-run`

docs/ATLAS.md's step 3, built on the pattern of the workload tools:

    positive-run <image.cftp> (--iota n | --a A [--b B] [--c C])
                 [--bank bank.bin] [--out deposits.bin] [--device sw|<xclbin>]

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

The runner is the same binary on the software backend, in emulation
and on the card, which is what lets a plate's hash be compared across
all three.
