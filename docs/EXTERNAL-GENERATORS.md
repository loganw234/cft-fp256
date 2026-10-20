# Three outside test sources against libcft

Berkeley **TestFloat 3e** (with SoftFloat 3e), **UCBTEST** and **IBM's FPgen test vectors** are put to work
against libcft's software backend, each with its own expected results. Logan, 2026-10-20: "The more independent
generators the better", and "Go with all three outside generators if possible, more coverage isn't a bad thing
even to have". Parcel XG built the drivers and ran them; this is the manual and the record. **None of the outside
files is in this repository** (the IBM vectors carry no licence, and the other two carry notices that ask to travel
with every copy), and no run here touched a card: every driver reads `CFT_SOAK_ARTIFACT` as the soak tools do, so
the same commands run on a device later.

The host FPU and libm stay the only *sweep* oracle (Logan's answer to question 8 of the sweep study); these suites
bring expected results of their own and are independent checks beside the sweep. Every disagreement is arbitrated
by `python/cft_golden`, the authority. Marks: MEASURED is a run of this parcel, READ a file or page, COMPUTED
arithmetic on those.

## 1. The sources, and their licences as read from their files

| source | what it is | licence, as its files state it | used here |
|---|---|---|---|
| **TestFloat 3e**, **SoftFloat 3e** (J. R. Hauser, 2018-01-20) | `testfloat_gen` writes cases, `testfloat_ver` judges results against SoftFloat; its own documents say it is weak at the hard division and square-root cases | `COPYING.txt` in each archive: Berkeley's three conditions (keep the notice in source, reproduce it in binary distributions, no use of the University's name to endorse), copyright The Regents of the University of California 2011-2018, applying to the release and to each source file | built from its own makefiles in a directory of the caller's; nothing is compiled into our code, the contact is text |
| **UCBTEST** (students of W. Kahan, with Sun Microsystems; its README is dated 1995-03-08) | `ucbdivtest`, `ucbsqrtest`, `ucbmultest`: cases built by Kahan's number-theoretic methods so that the true quotient, root or product lies exactly on, or a hair off, the midpoint of two neighbouring numbers of the format; hex vectors in `ucblib/` | the README says most of the source is not public domain and asks that each file's own notice be observed. Read: **Sun 1988-1994** on 82 files (`ucbtest/` div.c, sqr.c, mul.c, lib.c; three DOS variants; all 75 `ucblib/*.input`): download, copy, use, fix and distribute, provided nothing is sold beyond media costs, every copy carries the notice and the other embedded notices, and distribution obeys U.S. export law; **Sun 1993** (4 DOS files): use, copy, modify and distribute freely with the notice kept; **BeEF**, the elementary-function tester: 14 files carry the line 'Copyright 1/5/95 Zhishun Alex Liu' (12 in `ucbeef/`, and `ucbtest/beef.c` and `findpi.c`); 18 files carry the marker '(BeEF)' and 19 the word BeEF (17 in `ucbeef/`, 2 in `ucbtest/`; case-sensitive); and `ucbeef/README` forbids redistribution without the author's written permission; `ucbeef/distd.c` Kahan 1995; `ucbeef/randm.c` the Regents 1983, BSD-style with an advertising clause; `pi.c` and `pi.F` Kahan 1989; counts (MEASURED, reading the archive in place): 426 files, 408 text and 18 binary (a NUL byte); the word 'copyright', in any case, is in 106 text files (104 notices as listed and two README paragraphs about notices) and in 9 binaries, DOS executables that hold the compiler's own string, Borland C++ - Copyright 1994 Borland Intl.; 302 text files do not hold the word, nor do the other 9 binaries (project files); no UCBTEST notice is established for any binary | `div.c`, `sqr.c`, `mul.c` (Sun 1988-1994), `init.c` and the three mains (no notice), compiled unchanged; ten `ucblib` arithmetic vector files read. **Not used:** BeEF (elementary functions, and redistribution is forbidden), `lib.c`, `pi`, `par`, `findpi`, the other 65 vector files |
| **IBM FPgen vectors**, binary models v1.02 (a GitHub mirror; IBM's own pages are gone) | seven `.fptest` files, one coverage model each, in the syntax `syntax.txt` describes: Vicinity-Of-Rounding-Boundaries, Corner-Rounding, Rounding, Sticky-Bit-Calculation, Underflow, Overflow, Divide-Trailing-Zeros | line 2 of every `.fptest` names IBM Corp. 2005 as the copyright holder; none of the eight files holds the word licence, permission or redistribute (MEASURED, by counting them), and the mirror has no licence file (READ by parcel HC, in the manifest). **Local testing only; never committed or redistributed** | read as data (`python3 -I`) and run; nothing copied |

## 2. Fetch, build, run

```
python3 python/fetch_external.py DIR            # the eleven files, hash-checked; never in a test, a stage or CI
python3 python/fetch_external.py --verify DIR   # files already there against the table (reads local files only)
```

The table in that script is the lead's manifest of 2026-10-20 (MEASURED: `--compare-manifest` finds it equal and
`--verify` finds all eleven files equal). A file whose size or sha256 differs is named, refused and not written; a
directory that is not empty is refused; `CI`, `GITHUB_ACTIONS` and `PYTEST_CURRENT_TEST` stop it.

**TestFloat.** Unzip each archive into its own new directory, run `make` in `SoftFloat-3e/build/Linux-x86_64-GCC`
and then in `TestFloat-3e/build/Linux-x86_64-GCC` with `SOFTFLOAT_DIR` given on the make line (4 s, no edit).
Then `make -C host libcft.a cft-tf-subject` and

```
python3 -I python/external_tf.py run --tf TFDIR --subject SUBJECT --out OUT --level 1|2 [--wide] [--limit N]
python3 -I python/external_tf.py arbitrate --out OUT --by-file   # every reported case against the golden model
```

where SUBJECT is the built `cft-tf-subject`. The subject (`host/tools/tf_subject.c`) sits in the pipe
`testfloat_gen | cft-tf-subject | testfloat_ver`, one libcft call a case (flags are per call), and writes the line
`testfloat_ver` reads. It is a pipe and not a libcft subject linked into the all-in-one `testfloat`: nothing of
TestFloat is compiled into our tool, the same binary takes a device, and `testfloat_ver` is the judge. Its glue
(ADD and SUB read operands a and c; TestFloat's flag bits run the other way; `le` and `lt` are the signaling
comparisons) is held to the golden model by `make -C host tf-subject-test`. `CFT_TF_ORACLE=host` makes the same
subject compute on the host CPU instead (six functions, binary32 and binary64, four modes; the rest refused by
name), and `arbitrate --host` names the classes for it. `CFT_SOAK_SABOTAGE=1|2` (and `..._EVERY=N`) is its negative
control: a sabotaged subject still exits 0, and it is `testfloat_ver` that reports the wrong lines and exits 1.

The mulAdd prefix is `--level 2 --only _mulAdd --limit 134217728`. The strict probes are `run --level 1
--max-errors 0` with `--ver-flags=-checkInvInts --only _to_ui32,_to_ui64,_to_i32,_to_i64`, with `--tininess before`,
and with `--ver-flags=-checkNaNs --skip _mulAdd` (and again `--only _mulAdd --limit 600000`); the last two are
arbitrated with `--nan-bits`. Binary128 is `--wide`; the host CPU is `CFT_TF_ORACLE=host` in `run`'s environment.

**UCBTEST.** `host/tools/ucb_run.sh UCBDIR host BUILDDIR NTESTS` compiles UCBTEST's sources, unchanged, with
`host/tools/ucb_hooks.c`, which supplies from libcft the `testdivd_`, `testsqrtd_`, `testmuld_` family (UCBTEST keeps
the arithmetic it tests in those functions, for a platform to supply), and runs the six programs; UCBTEST's own
judge decides. `CFT_UCB_HOSTCHECK` also computes each call on the host CPU, and `CFT_UCB_DUMP` writes the operands
for `ucb_run.sh --replay`, which sends them through `testfloat_ver`. The ten vector files:
`python3 -I python/external_ucblib.py --dir UCBDIR/ucblib --subject SUBJECT`.

**IBM.** `python3 -I python/external_ibm.py --dir DIR --subject SUBJECT`. The tests of all our code are
`python -m pytest python/tests/test_external_gens.py` (cases written here, none from the outside, part of the
`golden` stage) and `make -C host tf-subject-test`.

## 3. What each covered

**TestFloat** (software backend; tininess after rounding, which is what libcft detects - READ in
`docs/DETERMINISM.md`, "Tininess is detected after rounding", and in `round_pack` of
`python/cft_golden/softfloat.py` - and also TestFloat's own default, passed as `-tininessafter`). Binary32 and
binary64: add, sub, mul, mulAdd, div, sqrt, rem, roundToInt (with and without `-exact`), eq, le, lt and their
signaling and quiet kin, `f32_to_f64`, `f64_to_f32`, the eight integer-to-float and eight float-to-integer
conversions (with and without `-exact`); every function that rounds in all five modes both libraries share
(near_even, near_maxMag, minMag, min, max).

| run | pipelines | cases | reported | note |
|---|---|---|---|---|
| level 1, binary32 and binary64, all | 212 | 63,940,800 | 360 | mulAdd is 6,133,248 cases a mode, 61,332,480 of the cases |
| level 2, everything but mulAdd | 202 | 1,293,593,600 | 0 | 7,496,192 cases a binary32 binary operation, 40,284,288 a binary64 one; division is 10 of the pipelines and 238,902,400 of the cases |
| level 2, **mulAdd, a prefix** | 10 | 1,342,177,280 | 2,920 | the first 134,217,728 lines of the stream, per mode and format |
| level 2, in all | 212 | 2,635,770,880 | 2,920 | every pipeline of level 1 again |
| level 1, **binary128** (beyond the brief's fp32 and fp64) | 103 | 31,985,232 | 190 | TestFloat's `f128_` functions against libcft's fp128; mulAdd is 30,666,240 of the cases |
| level 1, **the host CPU** as the subject (`CFT_TF_ORACLE=host`) | 48 | 50,558,304 | 288 | add, sub, mul, mulAdd, div, sqrt, binary32 and binary64, the four modes x86 has |

**Level 2 is not complete for mulAdd.** Its stream is 2 x 1936^3 = 14,512,627,712 cases a mode at binary32 and
2 x 4488^3 = 180,795,884,544 at binary64 (COMPUTED from the loop bounds in `genCases_f32.c` and `genCases_f64.c`).
What ran is the first 134,217,728 lines of each mode's stream: 0.92% of the binary32 stream and 0.074% of the
binary64 one. Those lines alternate a random triple with a structured one (READ in `genCases_f32.c`), and the
structured half runs a outer, b middle, c inner, so it holds only the first values of a (MEASURED from the
generator's output). At binary32 they are 0x00000000 and the powers of two 0x00000001 to 0x00008000, each against all
3,748,096 b-and-c pairs, and 3,391,232 pairs of the 18th, 0x00010000; at binary64 the first three, 0x0, 0x1 and 0x2,
each against 20,142,144 pairs, and 6,682,432 pairs of the fourth, 0x4. The prefix ran at 1.4 M cases a second through
the whole pipe (948 s for the ten prefixes, MEASURED), so the five modes of the whole stream would take about 14 hours
at binary32 and 7 days at binary64 at that rate (COMPUTED); the generator alone writes 2.7 M lines a second at
binary32 and 1.7 M at binary64 (MEASURED: 30,000,000 lines beside the running chain).
Software division runs 65 K cases a second at binary32 and 52 K at binary64 at one case a call (MEASURED: 105.9 to
115.9 s for each of the five binary32 modes, 7,496,192 cases; 762.6 to 886.0 s for each of the five binary64 modes,
40,284,288 cases; niced, at the desktop's natural load). I had estimated about 2 minutes a binary64 mode; the
binary32 rate said about 10, five times the guess, and the runs took 12.7 to 14.8 minutes.

**The host CPU as a subject** (the brief's "host oracle where it applies"): with `CFT_TF_ORACLE=host` the same
subject computes on the machine's own hardware (SSE for + - * / and square root, libm's `fmaf` and `fma` for mulAdd;
a 12th Gen Intel i5-12400F with FMA, glibc 2.35) and every other function is refused by name. MEASURED: it agrees with
SoftFloat, bits and flags (a NaN's payload apart), on every level-1 case of add, sub, mul, div and sqrt, and on
mulAdd everywhere but the 0 x infinity + quiet-NaN row, where it returns the addend itself and raises no invalid
(libcft returns the canonical NaN and raises no invalid either); on IBM's vectors it has libcft's 20 disagreements; on
UCBTEST's ten vector files none.

**Strict probes** (level 1, beyond the brief; three of TestFloat's switches that check what its default leaves loose,
every error line arbitrated by the golden model, 0 libcft defects):

- `-checkInvInts`, the 80 float-to-integer pipelines (54,720 cases), holds the integer delivered with invalid raised:
  13,412 differ, all libcft = golden. libcft delivers the contract's RISC-V values (the maximum for a NaN and a
  positive overflow, the minimum for a negative overflow, unsigned 0 for a negative below zero; READ in
  `docs/DETERMINISM.md`, convertToInteger), SoftFloat's 8086-SSE the x86 indefinite integer (the most negative for
  signed, all ones for unsigned; READ in its `specialize.h`).
- `-tininessbefore` against libcft's tininess after rounding, all 212 pipelines (63,940,800 cases): 8,471 differ, all
  libcft = golden. 360 are the fused multiply-add row; the other 8,111 differ in the underflow flag alone (f32_mul 72,
  f64_mul 72, f32_mulAdd 3,667, f64_mulAdd 4,279, f64_to_f32 21), none in add, sub, div, sqrt, rem, roundToInt or
  the other conversions.
- `-checkNaNs`, the NaN's sign and payload: 202 pipelines, everything but mulAdd (2,608,320 cases), 138,962 differ;
  mulAdd, the first 600,000 lines of each mode and format (10 pipelines, 6,000,000 cases), 531,685 differ. All
  libcft = golden and in the NaN's bits alone (the contract canonicalises NaNs, READ in `docs/DETERMINISM.md`;
  SoftFloat propagates an operand's payload or returns the x86 default NaN, which is negative), except 85 of the
  mulAdd lines, which are the fused multiply-add row and also differ in invalid.

**UCBTEST** (`NTESTS` 5,000,000, software backend, 8.5 min): `ucbdivtest` single 8,467,262 cases and double
8,465,347; `ucbsqrtest` 1,768,546 and 1,768,269; `ucbmultest` 82,796,202 and 83,000,539 calls (2,796,202 and
3,000,539 exactly-halfway cases and 5,000,000 nearly-halfway cases). All six pass; the host CPU's own division, root
and product, computed beside every call, agree on bits and flags (0 and 0 mismatches); the same operands through
`testfloat_ver` (the replay) give the same counts and 0 errors. With `CFT_UCB_SABOTAGE=1` the three double programs
fail by their own verdict line. The ten arithmetic **vector files**: 11,687 vectors, + - * / and square root, single
and double, nearest and the three directed attributes, flags included: 0 disagreements (28 of them are cases on
which the two detections of tininess flag differently; in all 28 the vector's checked flags equal both predictions,
so the vector cannot tell the two apart). UCBTEST's division and
square-root cases are for round to nearest, and the multiplication run wrote operands under no other attribute.

**IBM**: 6,798 case lines in seven files, **all binary32**; + - * *+ / and square root; the rounding words `>`, `<`,
`0` and `=0`. The mirror's other binary-model files are binary32 as well (the lead counted their case lines through
`gh`: Basic-Types-Inputs 26,166, -Intermediate 214, Input-Special-Significand 1,190, Hamming-Distance 273,
Compare-Different-Input-Field-Relations 317, Divide-Divide-By-Zero-Exception 32), so **IBM's binary64 leg is empty**;
binary64 is covered by TestFloat and UCBTEST.

## 4. Every disagreement, classified

| class | cases | what it is |
|---|---|---|
| **fused multiply-add, product 0 x infinity, quiet-NaN addend** | level 1: 39 a mode at binary32 (195), 33 a mode at binary64 (165). Level 2 prefix: 176 a mode (880) and 408 a mode (2,040). Binary128, level 1: 38 a mode (190) | libcft returns the canonical qNaN with no invalid flag; SoftFloat raises invalid (READ in `s_mulAddF32.c`) and TestFloat expects it (its documents, section 6.3). Each case was read back to bits and checked three ways: libcft equals the golden model in bits and flags, SoftFloat differs from it by the sign of the NaN and the invalid flag only, and the operands are the row (one factor zero, the other infinite, the addend a NaN with its quiet bit set); none failed any. The host CPU's own fused multiply-add, run as a subject (above), also returns the addend with no invalid: the hardware's flags are libcft's and the contract's, not SoftFloat's. A **convention difference**, not a defect: RISC-V requires invalid here, and its note says 754-2008 allows but does not demand it (READ by the lead, riscv-isa-manual `f-st-ext.adoc` lines 319-326; 754 itself was not read here). The contract's NaN-first rule is the same in `host/src/softfloat.c`, `rtl/cft_fpfma.sv` and `rtl/cft_fpfma_pipe.sv` (READ by the lead), so the tile cannot disagree with golden on this row. `docs/DETERMINISM.md`'s NaN section does not say which of its two sentences wins here: an unstated precedence. Logan decides |
| **IBM, underflow flag where libcft raises none** | 20 of 5,293 comparable (10 `*`, 10 `*+`) | the vector's flags equal what tininess detected **before** rounding gives; libcft detects it **after**. Each was checked: the value agrees, only the underflow bit differs, the before-rounding prediction (exact rational arithmetic, golden's inexact bit) equals the vector's flags, and the result is the smallest normal number; and these are all the cases on which the two detections differ among the 5,293 (IBM sides with "before" in 20 and with "after" in 0) |
| **IBM, trap taken** | 1,505 of 6,798 (505 overflow, 1,000 underflow) | IEEE 754-1985's trapped results (exponent wrapped); libcft's flags are sticky data, never traps. Not compared: every one has its untrapped twin (same operands and rounding) in the same file, among the 5,293 |
| **float-to-integer, the integer delivered with invalid raised** (the `-checkInvInts` probe only) | 13,412 of 54,720 | libcft delivers the contract's RISC-V values and SoftFloat's 8086-SSE the x86 indefinite integer (section 3); TestFloat's default does not look. A **convention difference**, pinned by `docs/DETERMINISM.md` |
| **tininess before rounding** (the `-tininessbefore` probe) | 8,111 of 63,940,800 | the underflow flag alone, in mul, mulAdd and f64_to_f32; the same difference as IBM's 20. The contract detects tininess after rounding. A **convention difference** |
| **NaN sign and payload** (the `-checkNaNs` probe only) | 138,962 of 2,608,320, and 531,685 of the 6,000,000 mulAdd lines | the contract canonicalises NaNs, SoftFloat propagates a payload or returns the negative x86 default NaN. A **convention difference**; TestFloat's default does not look. 85 of the mulAdd lines are also the fused multiply-add row |
| UCBTEST generators and vectors | 0 | no disagreement |
| libcft defects | **0** | |

## 5. Which oracle judged what

| judge | what it decided |
|---|---|
| `testfloat_ver` (SoftFloat 3e, specialization 8086-SSE) | the TestFloat pipelines and the replay of UCBTEST's cases; SoftFloat itself checked in this build against TestFloat's slowfloat by `testsoftfloat -level 1` over the 46 functions the pipelines use: 281 combinations of function, rounding mode (the five and round to odd) and tininess setting, 150,759,744 tests, 0 errors |
| UCBTEST's own arithmetic (exact integers, Kahan's constructions) | `ucbdivtest`, `ucbsqrtest`, `ucbmultest` |
| the host CPU's own hardware (`CFT_UCB_HOSTCHECK`; and as a subject, `CFT_TF_ORACLE=host`) | every call of the six UCB programs, bits and flags: 0 and 0; and the CPU itself judged by `testfloat_ver` and by IBM's vectors, beside libcft (above) |
| the vectors' own expected values | IBM's files and UCBTEST's ten, with the arbitration of section 4 |
| `python/cft_golden` | every disagreement: libcft = golden against an outside value is a convention or an outside error; a golden that agrees with the outside value against libcft would be a defect |

## 6. Known limits

- mulAdd at level 2 is a prefix (above). The unary functions and the conversions have small level sets (binary32: 600
  cases at level 1 and 8,800 at level 2; binary64: 768 and 26,112); the soak tools cover those spaces exhaustively.
- Software backend only. The host-code operations (conversions, remainder) are bit-identical on every backend by
  construction, so nothing here is evidence about the tile or the card. The subject makes one libcft call a case
  (flags are per call); on a device that is a round trip a case, so level 2 is a software-backend plan.
- `make -C host tf-subject-test` is run by hand: no runner stage calls it (new stages were out of scope).
- Not covered: binary16, extended precision, TestFloat's round-to-odd (libcft has none), binary128 at level 2, fp256
  (outside TestFloat's formats).
- IBM: binary32 only; its trapped cases are not libcft's model; the three letters for underflow (u, v, w) are one flag
  here and only `u` occurs in these files.
- `external_tf.py run` exits 0 when errors are reported (its health rule accepts the verifier's status 1, a reported
  case being data for the arbitration) and `arbitrate` exits 0 even with FINDING lines, so neither is a gate: the
  counts and the classes are what is read.
- The UCBTEST-vector runner reuses the IBM runner's judge, so its class names say "IBM" where they mean the
  vector (the sabotage control's output, which holds LIBCFT DEFECT on purpose, reads so).
