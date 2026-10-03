# Verification: what each gate proves, and how long it really takes

This is the map of everything that checks this project, in the order
the evidence stacks up, with the wall time each layer costs measured on
real runs rather than guessed. docs/VALIDATION.md is the dated record
of what ran and what it found; `verify/run.sh` is the runner that
executes most of it in one command; this page is the explanation of
what "green" means at each layer and what you are signing up for when
you start one.

**Read the durations first.** The two simulation suites run for an
hour or more each on a busy box, several other gates for twenty to
fifty minutes, and every one of them stretches when the box is shared:
the numbers in the right-hand column were taken on the same day the
left-hand ones were, with two simulation suites, a formal run and a
Vivado implementation sharing twelve cores. A gate that seems to have
hung has usually just not finished - with two exceptions worth
knowing: a formal task that does not close never finishes, and the
gate's seven-minute norm is the number to hold a run against; and a
bench whose simulated time crawls while the simulator burns a core
may be a simulator cost rather than a slow test - the board kernel
under Icarus is the known case, four hours to reach 57 of its 71
operations and then a near standstill, where Verilator finishes the
bench in 16 s after an eleven-minute compile - and the way to tell
is to watch the simulated time, not the wall clock.
Nothing here is a quick unit test.

## The layers, and what each one proves

The project's claim is that four IEEE 754-2019 binary formats compute
bit-identically everywhere: in the golden model, in the C library, in
the RTL, in the bindings, and on a device. The gates are arranged so
that each layer is held to the one above it and the model is the only
authority:

1. **The golden model** (`python/cft_golden`, `make golden`). Pure
   Python, exact arithmetic, the definition of correct. Its pytest suite
   checks the model against its own invariants and against mpmath and
   MPFR where they can arbitrate. Nothing below re-litigates a value it
   has decided. The language (`cft_golden.lang`, docs/LANGUAGE.md) is
   defined here too, and its compiler, `python/cftc`, is held to the
   language's reference interpreter by the `lang` stage, and its
   run-time division and square root, compiled as routines, by the
   `lang-routines` stage: every image it writes runs on seq.py against
   `lang.run`, bit for bit, FLAGS included, on many lanes at several
   step counts. The `tangent` stage
   does the same for systems carrying the variational equations, their
   tangent vectors included, and holds the tangent to an exact
   derivative and Lorenz-63's largest Lyapunov exponent.
2. **The conformance vectors** (`make vectors`). The model writes 168
   sets, 1,068,915 cases, every format under every rounding attribute,
   with the expected result and the expected flags per case. These are
   the fixed points every other implementation replays. A generation
   that finishes writes their `SHA256SUMS` beside them, last, and the
   runner replays no `vectors/out` whose record is missing, leaves out a
   set the profile names, or does not hold under `sha256sum -c`: it
   regenerates the directory, and fails by name if it cannot
   (`verify/README.md`). Until 2026-09-29 the runner took any non-empty
   `vectors/out` for the census, and `cft-selftest` passes on the five
   sets a crashed generation left.
3. **The C library** (`host/`, `make -C host test`). Contract tests
   (`api-test`), the partition invariants (`reduce-parts`), then the
   whole vector set replayed twice - one element at a time for exact
   flags, then as arrays so a device backend's partitioning cannot hide
   a divergence - and a C-versus-Python identity check through ctypes.
   The model-versus-C stages of the runner (`selfcheck`, `divsqrt`,
   `clause5`, `character`, `transcend`, `augmented`, `status96`,
   `formatof`, `diff`, `seq`, `programs`, `reduce`) then sweep the entry
   points the vectors do not reach: composed divide and square root,
   the conversions, the thirty-nine transcendentals, the augmented
   operations, the status word, the cross-format arithmetic, the
   alignment boundary, the sequencer's fuzzed programs, the program
   library's rows, the reductions. The `audit` stage holds the C
   auditor, `cft-audit`, to the golden one: the same refusal by name,
   code and location, or the same verdict, on every parse call
   `python/tests/test_cert.py` and `python/tests/test_cert2.py` make and
   on 244 of test_cert.py's 283 audit calls and 139 of test_cert2.py's
   147, on cft-segrun's certificates and on the golden corpus, version
   2's cases among it since its C half (2026-10-02; the golden auditor
   handed no source, as the tool is). The other audit calls pass
   arguments no file or option spells, and are counted and named by
   reason (docs/CERTIFICATES.md, "The audit tool").
   One stage in this layer holds the library to something this project
   did not compute (`photograph`): atlas-engine's deterministic camera
   around a plate as a sequencer program, each pass's deposit buffer
   held to the SHA-256 an NVIDIA GPU wrote while rendering the same
   frame from pinned GLSL. Every other stage here compares the C with
   the golden model, and a defect the two shared would pass them all;
   this one would not. Negative controls, run on 2026-09-18: with the
   library's multiply forced to round toward zero all four passes
   differ; a fixture with one bit flipped is named as damaged and
   nothing runs.
4. **The RTL, in simulation** (`tb/`, `make sim` in the `cft-sim`
   image). Twenty-six cocotb targets hold the hardware to the model, and
   since 2026-09-12 the target's exit code reports whether they passed:
   `tb/check_results.py` reads every `results.xml` the run wrote and fails
   on a recorded failure, a missing file or an unparseable one. cocotb
   cannot set an exit code itself — its makefile says so and checks only
   that the file exists — so until that date this tier could report
   success with any number of its benches red, and three real RTL failures
   were reported as a pass. The files checked are derived from the bench
   list rather than written beside it, so a bench cannot be run and left
   unchecked. The benches:
   the four rung benches replay 111,278 cases the golden model generates for them (`vectors.testset`, at smaller budgets than the published sets) through
   `cft_fpfma_pipe` bit for bit, flags included; the kernel is driven
   through its CSR and AXI interfaces, by the streaming engine and by
   the sequencer; the shared normalise and alignment ladders are held
   against the private shifters they replaced; the reduction
   accumulator, the fault paths, the seed opcodes and the three trims -
   the quarter tile; the full beat with binary256 left out, the shape
   cft-rebound ships; and binary64 with binary128 and neither end, the
   shape it asked for - have benches of their own. `make simmc MC=10`
   runs the same suite with the multiplier iterated ten ways, plus the
   `board` configuration (ten passes and both ladders on) that the
   open-core Kintex-7 tile would ship as - thirteen multi-cycle targets
   and the board's four, grouped as `board`, the third tier's own census.
   The board has had four since 2026-09-29, when revision 7's ODE case
   left boardseq for boardseqode.
5. **The RTL, elaborated** (`make yosys-lint`). Every RTL file through
   Yosys: no latches, no width surprises, no construct the open flow
   cannot take.
6. **The formal proofs** (`formal/run.sh` in the `cft-formal` image).
   Property proofs over *all* traffic for the modules whose
   correctness is a control argument: the FIFO's contract, unbounded;
   the seed opcode's routing over every input; the integer group
   against a frozen reference; the leading-zero cone against the
   priority form it replaced, complete at every window width; and the
   multi-cycle multiplier's exactness at the real 24-bit chunk for
   every pass geometry the tile builds, as two lemmas per geometry plus
   the whole claim as one property where a solver will take it. A
   negative control - a deliberately broken property - must be refuted
   every run, and every task's solved model is counted for assertion
   cells so a proof cannot pass empty. formal/README.md has the table.
7. **The bindings and the other languages** (`node`, `wasm`, `cpp`,
   `bindings`, `lang-*` stages). The same vectors through `cft.hpp` at
   C++17 and C++20, through the wasm module in node, through the
   committed conformance page without a browser, through the Python
   drop-in against gmpy2's IEEE emulation, and one example per language
   diffed against the C example's bits (Fortran's, which prints no
   checksum, is built and run).
8. **The workloads and the demos** (`workloads`, `demos` stages, and
   `make -C host <tool>test`). The five contract workloads - Collatz,
   interval enclosure, Mersenne, orbits, deep zoom - each against an
   independent oracle (big integers, mpmath, a 300-digit integration)
   and each proving its own determinism properties: same bits at every
   batch size, from either engine, interrupted and resumed - and
   cft-orbits killed mid-run on either engine and resumed by the other,
   its records byte for byte (since 2026-09-25). Then the
   browser demos' compute core reproducing the C tools' chains over the
   module the page embeds.
9. **The network** (`remote` stage, `make -C host remotetest` and
   `wstest`). The remote backend held to the contract on loopback:
   refusals, device-test against the remote handle, a bounded replay
   identical local and remote, one workload chain both ways, the
   round-trip counts, the negative control; then the same frames over
   WebSocket from node, compared with the local module and the
   published answers. docs/REMOTE.md.
10. **The parsers that face untrusted bytes** (`host/fuzz/`, opt-in).
    Coverage-guided fuzzing of the server's frame decoder, the client's
    reply parser, the program loader against the golden model's own
    validator, and the five tools' checkpoint readers, under address
    and undefined-behaviour sanitizers; every fix carries a checked-in
    reproducer that `make -C host fuzz-repro` replays. host/fuzz/README.md.
11. **The third oracle** (`mpfr` stage). GNU MPFR in IEEE emulation
    against every rung and mode the library has, values and flags -
    the only external oracle that reaches binary128 and binary256, and
    the only one at all for the transcendentals. Since 2026-09-30 the
    same stage then holds the transcendental evaluator's own error
    claims, exactly (`host/tests/mp_err_check.c`): every rule
    `host/src/mpfloat.c` derives, in GMP on operands built field by
    field, and against MPFR the count each constant carries and the
    logarithm's conversion of an argument's error, with controls that
    must fail - the rules as they were before that day, a comparison
    made on the stored value alone, a constant's count cut to one unit,
    and the logarithm without its argument's error. `transcend.c`'s own
    allowances, such as a truncated series' tail, are not among them.
12. **Hardware, out of the runner.** The native-oracle soaks
    (`hw/run-soak.sh`), hardware emulation, the on-card runs
    (`hw/run-device-test.sh`), and the out-of-context and shell timing
    builds (`hw/mc_sweep.sh`, the link flow) are machine- and
    schedule-bound and keep their own drivers and their own entries in
    docs/VALIDATION.md. They are where "read the path delay, not the
    slack" applies (docs/BRINGUP.md).

The `estimates` stage (gate budget) and the `estimates-full` stage (the
full census only) hold a study's numbers rather than a layer. They re-make
docs/studies/ACC-A-estimates.md, two of its cases and then the whole of
it, and hold every scored section they print line for line to its
committed runs. The run's header (the mpmath version, TAU and the level
caps) is printed and not held, by design, since another mpmath version
prints another (verifier-W2). The loading section is held to the committed lines of the cases
asked for (every case, without `--cases`). There a
certificate's step-halving estimate is scored against a converged
reference, and its wider estimate against check.py's 300-digit arm. They
run on the golden side, in Python with mpmath, from the golden corpus's
committed states. `estimates` runs no C; `estimates-full` builds and runs
cft-segrun for the study's sweep.

The `acceptance` stage (gate budget) and the `acceptance-far` stage (the
full census only) hold a set rather than a layer: everything that runs on
the card today, each entry one run fixed in `programs/acceptance.json`
with the state hash expected at every segment boundary, and the hard
workloads' programs against the one-step vectors the other model's own
evaluator wrote (programs/workloads/README.md). On the software backend
they hold libcft, the compiler and the interpreter to those; with
`--device <xclbin>` the same driver is the admission test for a new card,
which passes when every digest is the set's, cft-audit accepts every
certificate in full and the golden checks accept it. A
card's run is layer 12's, out of the runner: the lead's.

Three rules hold across all of it. A gate whose tool is absent is
**skipped by name with the reason**, never silently passed, and so is a
check skipped inside a stage that passed - when its script reports the
skip in a form the runner reads: a line whose first word is `SKIP` or
`SKIPPED`, or the conformance replay's `skipped, ... on this device`. A
skip reported any other way, lower case or mid-line, still passes
unnamed; verify/README.md lists the forms known. A negative
control that stops failing fails the run; and a number in a test that
copies a number in the RTL is a defect, which is why the CAPS test
parses the kernel's parameters instead of restating them.

## How long each one takes

Measured, not estimated. "Quiet" is the Windows desktop (12 cores, 64
GB) with nothing else running, from the runner's own per-stage log of
the 2026-09-04 census (`verify/state/20260904-035237-d4fe397/report.jsonl`);
"loaded" is the same host on 2026-09-07 carrying two other
simulation suites, a formal run and a Vivado implementation at once.
The WSL distro on the same machine runs the replay stages in seconds
where MSYS takes minutes - process spawning and file I/O, not the
suite - so a Linux host lands nearer the quiet column or below it.

| gate | quiet | loaded | notes |
|---|---|---|---|
| `golden` (pytest, 3,104 tests since parcel R8's merge on 2026-10-02, when `python/tests/test_seq_rev8_flags.py`'s 60 and two in `test_cftc.py` joined - 3,101 passed with the 3 skips below at 7ccc441 on amd-arc-box, 599 s; 3,042 from earlier that day, when parcel L4's tests and T1's `python/tests/test_lang_time.py` joined - 3,039 passed with the 3 skips below at e737aea on amd-arc-box, 593 s; 2,946 from earlier that day, when the language round's part two brought `python/tests/test_lang_tangent.py` and `test_lang_readback.py` - 2,943 passed with the 3 skips below at a5ffac7 on amd-arc-box, 601 s, and at 67eb0a6, 550 s; 2,800 tests from 2026-10-01, when the language round's part one brought `python/tests/test_lang.py`, `test_lang_refs.py` and `test_cftc.py`, the assemblers' character and number rules and the bank-depth refusal - 2,791 passed with the 3 skips below at 30ee0fd on amd-arc-box, 527 s, before the close's six; 2,432 from 2026-09-29, when revision 8's golden-first model brought `python/tests/test_seq_rev8.py`'s 81 and the program limits eight more - six in `test_seq.py`, one each in `test_asm.py` and `test_cert.py` - 2,429 passing on the desktop with the 3 skips below; 2,343 from 2026-09-28, when P1c brought `python/tests/test_cert.py` to 83 certificate tests; 2,325 from the lead's notes on P1b (65), 2,322 from P1b's 62 and 2,303 from the first 43, the same day; 2,260 from 2026-09-24, when four parse cases that only ever skipped were dropped; 2,264 from revision 3's model and assembler cases on 2026-09-08 evening; 2,075 before it) | 2.6 min at four workers | 8 to 13 min | on the desktop 3 skip by their own conditions (two need the Arduino loopback binary, one `math.fma`, Python 3.13+), and the runner now counts them; one revision-3 assembler test ran for the first time on the merged tree and had its expectation corrected. Since CV2B (2026-10-02) it holds certificate format version 2 (docs/CERTIFICATES.md, "Version 2"): `python/tests/test_cert2.py`, 102 tests, a control by name for every version-2 refusal at its line or its step - version 1's census on version 2's grammar, every encoding's other spellings, the signature and keyring, a key of small order wherever a key is read, sources recompiled by cftc, the wider-source relation, the blocks, every replay check, the definition re-run and `definition-differs`, the routine rule's W1 and W2 - with the page's version-2 example and test vectors held byte for byte; and `python/tests/test_ed25519.py`, 37 tests, Ed25519 held to RFC 8032 section 7.1's five vectors, every refusal of its sections 5.1.3 and 5.1.7, the cofactored equation, and vectors another implementation is held to: the eight keys of small order refused, six encodings of no point, three S at or above L. test_cert.py's two version controls moved from `version` to `line-missing` under `cft-certificate 2`. Measured on the desktop, niced, at 3 to 5 %: test_cert2.py and test_ed25519.py 114 passed in 23 s before the two page tests, which pass; test_cert.py 103 passed in 35 s (both at 82fa7e6; after verifier-VCV2B's findings, 139 and 103) |
| `vectors` (`vectors/gen_vectors.py` at the generator's default counts, not `make vectors`' smaller ones; 168 sets) | 5 min | 7 to 8.5 min | |
| `libcft` / `make -C host test` (build + the replay: 1,068,915 cases on `make vectors`' sets, about 1.2 million at the runner's generator counts), then `make -C host profiles-check` | 7.5 min | 8.5 to 11 min | the census was 1,071,635 until 2026-09-12, when opcode 31 became `maxall`: a reduction has no elementwise case to inherit, so 4,000 `reserved31` cases left and 1,280 maxall cases arrived. A document recording an earlier RUN still says 1,071,635 and is right to. `profiles-check` joined the stage on 2026-09-24 (about 3 min serial on the desktop, loaded): the library's sources (fifteen then; sixteen since `src/build_id.c`, 2026-09-28) compiled at the default, at the three reduced profiles `docs/EMBEDDED.md`'s loopback builds (`CFT_TINY`, `CFT_TINY` at fp128, the 32-bit boards'), at `CFT_MAX_FORMAT=2 CFT_BN_LIMBS=64`, and at every `cft_config.h` switch alone (the `CFT_NO_` ones read out of the header, not copied), 20 in all, with implicit-function-declaration, array-bounds and aggressive-loop-optimizations as errors; and five builds `cft_config.h` refuses - the transcendentals in a `cft_bn` below 64 limbs, reached by `CFT_MAX_FORMAT` 2, 1 or 0 alone or by `CFT_BN_LIMBS` 18 or 63 - held to failing in every source with the refusal's own words. No runner stage had compiled any of them. From 2026-09-14 until that day `divsqrt.c` did not compile with gcc 14 or later at `CFT_NO_PROGRAM`, and so not at either `CFT_TINY` profile; and the first compile of each switch alone found `CFT_MAX_FORMAT` below 3 with the transcendentals writing past a `cft_bn` on the stack, which is now refused by the width it narrowed. Since 2026-09-28 `make test` also runs `buildidtest` - the build id (`cft_build_id`) regenerated in scratch repositories of its own, 29 checks among them a git that warns on status or on either rev-parse call (the id must be `unknown`) and a linked worktree, 37 s on the desktop at 51% load with another parcel building beside it - and hands api-test the tree's id, so a stale api-test fails |
| `make -C host reducetest` (`reduce_check.py --trials 1500`: the tree, the scaling, the bits and the flags against the model) | 2 to 3 min | | listed here from 2026-09-12, having been absent from a page that calls itself the map of everything - found by asking which docs the round had made stale rather than by a gate. 13,516 reductions over four formats and all seven of clause 9.4 plus `maxall`, whose two sides are deliberately DIFFERENT SHAPES: the model folds left, the library halves. Comparing them is what tests 754-2019 `maximum`'s associativity instead of assuming it |
| `sim` (26 cocotb targets since 2026-09-29, when `seq_coreu50` joined; `cft-sim` image) | not measured quiet since the suite grew | **1 h 40 min at six jobs on amd-arc-box** (5,968 s, 3197dc6, 2026-09-29, beside simmc and a card session); 2 h 47 min (10,010 s) at the runner's one job on the desktop at revision 7's first merge (9ff114e) | almost all of it is the sequencer's unit bench, 63 cases since revision 7: seq_core 5,713 s and seq_coreu50 5,094 s of test time in that run, and krnlseq 1,747 s. Until 2026-09-29 this row gave 10 min at the runner's job count, about 40 min serial, 55 min at four jobs and 3 min at twelve jobs on a 36-core box, all measured on 2026-09-07, when the suite held 21 of today's 26 benches |
| `simmc MC=10` (13 multi-cycle + 4 board targets since 2026-09-29, plus the `board` group) | not measured quiet | **1 h 16 min at four jobs on amd-arc-box**, all of them (4,584 s on c720ca9's tree, 2026-09-29, beside a bitstream build): seq_coremc 4,480 s and boardseq 3,272 s of test time, boardseqode 754 s after its Verilator compile. It was about 50 min at four jobs before revision 7, without the engine-driven board kernel | two board benches run under Verilator by default, because Icarus does not finish them in this configuration. Revision 7's ODE case (boardseqode) ran at 0.53 ns of simulated time a second, about 60 days (docs/VALIDATION.md, 2026-09-29). The engine-driven board kernel (boardkrnl) **does not finish under Icarus** either: 2.5 ns of simulated time a second through the small operations and about 0.03 ns a second inside the 1,104-element stream, 57 of 71 operations after four hours, on the tree before the cone change and after it alike; under Verilator, which its target selects, the bench is **16 s of simulation after an eleven-minute compile** (44,920 ns, both tests, parameters applied - until the evening of 2026-09-07 a Verilator build received none of a target's parameters and simulated the default, docs/VALIDATION.md) |
| `lint` (Yosys, every RTL file) | 1 min | 1.5 to 2 min | |
| `programs` / `make programs-check` (the .cfta library: both assemblers, thirty-seven images since 2026-09-29 (thirty-five from 2026-09-25, seventeen when first timed), a check each, generated revision-2 and revision-3 corpora; since 2026-10-01 long lines, sources with lines of 1,022 to 5,000 bytes assembled by both to the same bytes, with a control that cuts them where cft-asm's old 1,024-byte reader did, and every numeric field at and past its bounds, both assemblers giving the same bytes or refusing for the same reason; since 2026-10-02 revision 8's five forms in both - a generated corpus of 160 programs that asserts what it reached, 46 sources and 10 images each held to the contract's verdict, and the post-step's bounds in the numeric arm; the MANIFEST held one for one to the sources and `gen_odes.py --check` run inside it; the three ODE rows' textbook arm in exact rationals - with a shared-error control for each of the generator's mutants and a tripwire of two rules, no forbidden name reached from its verdict and no check.py definition reached from both it and the implementations, over a census of every name the file binds at module level - their bank read by the source's names, N and the step counts pinned with a per-number control, the prose held to the images, a resume control on Henon-Heiles, and their 300-digit arm); and since 2026-09-28 `make -C host segruntest`, cft-segrun's certificates held byte for byte to the golden writer (docs/CERTIFICATES.md, "The segment runner"); and since 2026-09-29 `make -C host corpustest`, the golden certificates, a committed corpus that both writers must make again byte for byte, audited (docs/CERTIFICATES.md, "Golden certificates") | about 95 s since the golden certificates' gate joined it (the lead's figure; alone on the desktop, niced, segruntest took 55 to 60 s and corpustest 23 to 32 s, 2026-09-29); about 70 s since the segment runner's gate joined it (10 to 60 s before); 17 s through the runner at 15be186 (234 checks), 18 s at 7901584 (275) and at d2ed6a6 (284), 19 to 20 s at 29ee82a (331: verifier-V5's front door and the lead's, 2026-09-28); 66 s at 7f02d6a, 42 s of it the segment runner's gate (P3's runner, the desktop at about half load, 2026-09-28); 72 s at 4eed552, 47 s of it the segment runner's gate (verifier-C7, the desktop at 0 to 4 %), and 313 s in P3b's front door there with the desktop near 90 % | | a runner stage, quick budget, since 2026-09-25 - before that it ran only by hand, so a library row was gated only when someone remembered; the stage was watched failing (one MANIFEST digest altered: `programs FAIL`, the row named), and the ODE check on verifier-S0b's shared-error mutants E1-E8 and a resume fed the wrong state (F0b, verified by V3), then on each gate limit V3 found (F0c, 7901584; verifier-V5 reproduced 21 of its 27 runs red for their stated reasons) and on V5's notes (d2ed6a6: a helper shared by the two arms is now named by the shared-definition rule). Without mpmath the stage names all 12 checks it does not run, the six 300-digit claims and their controls. Held since (F0c's 98d7b05, 59e5c28 and 29ee82a, verified by V5 each time): a textbook arm made generic (N7) and definitions in top-level blocks (N6a-c); the mirror's helper handed through conditionals, containers, tables and their aliases, registries, a class's attribute and a wrapper's first argument (M1-M5, X3, E1-E3, E18, E19); a census of every module-level binding (B3b). What still passes is named in check.py's comment above the rules - code outside the file, a name built at run time, a copy of the mirror's code, a class the calling function defines, and more (verifier-V5, 2026-09-28). Needs mpmath only for the 300-digit arm, which it skips by name - the stage runs without it. `make programs` rebuilds the manifest it checks, so the two are separate on purpose; four of the checks waited on the revision-3 model and host by name (SKIP, not PASS) until both merged on 2026-09-08. The segment runner's gate (host/tests/segrun_check.py, 2026-09-28) certifies the three ODE rows at fp64 and fp256, each with a half-step run and at fp64 a wider fp128 one, a small program whose segments raise flags 20, 0, 1, 0, 20 and STATUS 48, 48, 0, 48, 48 - which no ODE segment does - and since 2026-10-02 `markstep`, whose STATUS 64, 64, 64, 0, 0 is revision 8's mark, held into every certificate's segment lines, and, since P3b, lorenz63 at fp64 once more with its half-step run entered from a state of its own, keyed and open on the software backend. The golden reader accepts each certificate, the golden writer, handed each certificate's identity lines, writes the same bytes from the initial states, every boundary file is the golden chain's, and the golden audit accepts each in full and sampled - the one whose half-step run starts from its own state it refuses `aux-start`. It also holds the page's test vectors and an HMAC written from RFC 2104, every refusal an input or the instrument can cause, by its name and code (the golden writer's name beside it where it has one), each whose command line has an `--out` of its own again with a file already there that must come through byte for byte (43 of the 53 cases; the rest have none to keep), lorenz63, flagstep and markstep through a loopback cft-serve stopped by its PID, what a run beside the main run costs in memory (peak commit on Windows, the least `ulimit -v` on Linux: two half-step runs beside the main run may cost their inputs and one state, where 4eed552 held every run's working set at once - verifier-C7's regression), and on Linux that the trial before anything is made costs the runs nothing, to the page, against the tool with the trial's allocations skipped (eb2d1ae's trial cost small shapes up to 40 KiB - verifier-C7's second finding; on Windows, where identical runs' peak commit differs by up to 16 KiB, a SKIP line names it NOT TESTED, which the runner counts as an inner skip). Its own part was 41 to 42 s on the desktop, 293 checks at 99f1b43; since P3b's second send-back it is 391 checks on Linux, 41 to 43 s in WSL, and 389 and one SKIP on the desktop, 39 to 41 s (2026-09-29); verifier-C7 measured 4eed552's 380 at 45 to 52 s at 0 to 4 % CPU. It was watched failing for its plants in a copy of the tree, P3b's new cases too (the round's ledger, P3.md). Since 2026-09-29 it also holds `--scratch-depth` (its section 11: a program whose answer depends on the depth, certified at 256 and at 2,048 and audited there, and the option's refusals). That is 458 checks and one SKIP on the desktop, 55 to 60 s; on Linux 460, by arithmetic, not yet run. The golden certificates' gate (`certificates/corpus.py check`) holds every committed file by SHA-256, with none unlisted, and every image against its source. It makes each case again with the golden writer, byte for byte, and with cft-segrun, byte for byte but for build-id, the accuracy block before step 5 and the hash line. It holds every boundary file, the golden audit's expected verdict in full and sampled, and the page's example: 156 checks, 23 to 32 s on the desktop, the slowest with it at about 77 % from other work. Both gates were watched failing for their plants in a fresh worktree (the audit round's ledger, P2.md). One plant moved an encoding in both writers at once: segruntest stayed green, and the corpus refused all twelve cases by name. Since CV2B (2026-10-02) the corpus holds certificate format version 2 too, the golden writer's until version 2's C half: seven cases the golden writer makes again byte for byte - every block, replay and raw file with them, and `signed-fp64`'s signature by the test key - each audited in full and sampled with what the manifest hands it (sources, blocks, a signature and keyring, a superseded certificate, a definition re-run, the initial state regenerated); thirty controls, one for each version-2 refusal a committed case can carry, each its case's certificate with its edit made again and refused by its name; `markstep-fp64` the page's version-2 example; and a NOTE naming the seven a C writer must reproduce. That is 288 checks in 28 and 32 s on the desktop, niced, at 4 to 10 %; without the tool, version 1's twelve remakes skipped by name, 239 checks in 27 to 29 s at 2 to 6 % |
| `lang` (`programs/lang_check.py --group core`: the language's compiler, `python/cftc`, held to the language's reference interpreter, `lang.run` - the core group of its legs since 2026-10-02's split) | not measured quiet | **138 s** run directly on the desktop, niced, at 2 to 5% load (220 checks, nothing skipped, after the split; verifier-VC4 measured 128 s at 0 to 19%); **969 s** through the runner on the desktop, niced (the split's tree on 370e0b2: 220 checks, nothing skipped), with it in use: a game in the foreground, at times taking it to 99% CPU, and two other agents' Python runs beside it - its references leg took 537 s, against 51 s run directly at 3 to 5% load; before the split, when the stage ran every leg, **276 s** through the runner on amd-arc-box at 370e0b2 (2026-10-02, the lead's run), past quick's three minutes - 296 s run directly on the desktop at 370e0b2 with it 3 to 5% busy, 147 s of that the routines' legs; 129 s through the runner on amd-arc-box, niced (e737aea, 2026-10-02: 189 checks, nothing skipped, parcel L4's leg among them); 132 s at a5ffac7 (185 checks, nothing skipped; 137 s at 67eb0a6); earlier **113 s** through the runner on the desktop, niced, with it in use (d50ccb0, 2026-10-01: 183 checks, nothing skipped, the driver 110 s of it, the let-heavy maps 18 s of that and the bank leg, the values past the digit limit with it, 10 s); 113 s at a28ce9d (174 checks) and 121 s at e1d828c on the same checks, the desktop's variance; 96 s at 442bd3f (158 checks), before the let-heavy leg joined; 60 and 66 s in two runs that morning whose python was MSYS2's own, the prefix put on the whole run by mistake, where the runner puts it on make alone; building cft-segrun and cft-audit from a clean host/ took 12 s | a runner stage, quick budget, since 2026-10-01 (the language round's L2; the lead's rule: quick at about three minutes or less). Every image the compiler writes runs on seq.py against `lang.run`, bit for bit with FLAGS, on many lanes and at 1, 2, 5 and the image's own steps (the image's REPEAT patched, as programs/check.py's `_patch_trip` does), because a wrong semantics can hide on one lane at the final step (L1's finding, docs/LANGUAGE.md). Its legs: the three references at fp32, fp64, fp128 and fp256 (35 lanes, 9 for Lorenz-96, three of them there to overflow, to hold a signalling NaN and to hold subnormals: the first two asserted to raise overflow and invalid at every format, the third to raise underflow for Lorenz-63 and Henon-Heiles at every format; Lorenz-96's raises inexact alone at F = 8, where a subnormal state is lost in a result near F - FLAGS 0x10, asserted at every format - and underflows at F = 0, which it runs in the bank leg) and Lorenz-63 and Henon-Heiles under every attribute; nine written shapes (every built-in once, an empty step, swaps and rotations pinned and homed, outputs that are a param and a lane param, the fold in a flow and in a map, sharing) and 48 generated systems at every format L1 takes them, on 11 lanes; 120 let-heavy homed maps and verifier-VL2's reproducer (two homed outputs due at one position), on 9 lanes; the references beside gen_odes.py's images, the compiled banks the classic banks byte for byte at fp64 and fp256 and the hand-written image on its classic bank equal to the compiled one at every checkpoint, their costs printed and pinned; the halved bank against `lang.run` at h/2, every param's slot at a random value against it on those encodings, `--param` values read as the language reads a default (0.1 at fp128 and an fp32 double-rounding case among them, which a binary64 route gets wrong), values past Python's 4,300-digit limit, which the language reads and holds (a const of 1e-5000 and an h of 1e-4400 at fp256, a param's and a lane param's 5,000-digit defaults, a 5,000-digit run value), each compiled, its exact values read back from the manifest and its image run against `lang.run`, and one segment of 2S against two of S; cft-segrun's certificates of each compiled reference at fp64 and fp256 - Kepler's, Störmer-Verlet with two divisions and a root a step (parcel C4), among them - and of a generated system with lane params (a main run, a half-step run on the halved bank, a step-halving estimate), each accepted by the golden reader, by the golden audit in full and sampled and by cft-audit in full and sampled, the golden verdict line for line; and (parcel C4, the leg that holds its C half: leg E's `wider_routine_controls`) version 1's wider run refused for an image holding a routine - cft-segrun refuses to write a wider run of Kepler's image, `aux-image` (exit 5, nothing made), and cft-audit refuses the certificate the instrument `CFT_SEGRUN_PLANT=wider-routine` makes of it, `aux-image` at run 1, while the same construction on Lorenz-63, which holds no routine, is written and accepted, so the rule alone refuses (the golden writer's and audit's half is certificate version 2's parcel's); two processes under PYTHONHASHSEED 0 and 4242 writing the same bytes, and those the bytes `programs/systems/compiled/` holds - the eight references' 64 files (`programs/lang_check.py --write` remakes them) - and cftc's output version the record's last (`programs/systems/cftc-outputs.txt`, version 4 since C4's call loop), the record's check caught on five plants in memory; every refusal of the compiler's seven by name, and the language's `bank-capacity`, which it raises for the routines' words, a routine image's `target-feature` on revision 7's targets among them; twelve plants in a copy of the package - five of the lowering's (a dropped node, a swapped fma operand that changes the sum, a register reused while live, a wrong h-scaled slot, a fold into RN(-c) where -RN(c) belongs), four of the routines' (a raise dropped, a raise inside its quiet region, a region dropped, a routine reading another word) and three of the call loop's, its constant lowered in the copy (the index not stepped past a record, a call's raise dropped, a loop a call short) - each stopped by the compiler's internal check and, with the check off, red on seq.py with its failing lanes and first failing step counted; and the core tally (leg I), every operation the compiler carries as one instruction, attribute, format, integrator and shape nonzero, from the core legs alone; and (parcel D2, 2026-10-01) every source the language accepts reading back: 160 maps that read h at random - forms that scale with h, that fold away, that are nonlinear - chains at the parser's 100, primal and with tangents (negations used as multiplicands, nested calls under every integrator, an unnamed product's and a min chain's tangent, a compound constant), and chains of lets past where Python's recursion limit once stopped them (rk4 from 81 lets, stormer-verlet from 123, with `tangent v` from 65 and 98, euler and map with it from 198, a chain through a call, chains to 1,500 lets) and a cycle of 600, each compiled with its canonical form read back or refused by the name its source decides, `unused` at the step line, `too-deep` naming its depth or `cycle`, and never an internal error - the leg's maps and parser-limit chains, run against 80abee5, stop the compiler at exit 70 on 53 maps whose every use of h folds away and on 6 parser-limit chains, and its let chains on 2 more - 61 in all, and 94 against 3fa0319 (verifier-VI2, measured) - which no leg above generated. The routines' own legs - every flag of div and sqrt through the interpreter, generated sources that divide or take a root compiled and held, the routines on their full pools, the call loop - are the `lang-routines` stage's (the next row) since 2026-10-02's split; from L4 until C4 the first of them refused each such source `runtime-routine` at its first line holding one, on every target, a name that went with C4. Without cft-segrun or cft-audit it names the certificate leg it cannot run with a SKIP line, which the runner counts as an inner skip. Before it landed, a corner probe and its generated corpus found three allocator defects, and verifier-VL2's let-heavy maps a fourth, which the let-heavy leg now holds (7 of its 121 cases fail without that fix); none reached an image - three were stopped by the allocator's own invariant (an InternalError, a value owed and nowhere), one, a rotation's, by the internal check (the round's ledger, L2.md). Verifier-VL2's re-check found the compiler's own graph reader and manifest stopping at Python's 4,300-digit limit, where the language does not - a bare ValueError, exit 1, no image wrong - which the four values past the limit now hold (all four fail without that fix). Not in the stage, a known limit: compile time grows faster than the step, roughly with its square for a wide one, and with its shape - 58 s for a 16,796-node ring of the Lorenz-96 kind on the desktop, and 97.4 s for verifier-VL2's 8-component map of about that size, which spills 3,063 values (`python/cftc`'s docstring) |
| `lang-routines` (`programs/lang_check.py --group routines`: the language's run-time division and square root compiled as routines, parcel C4 - the routines group of its legs) | not measured quiet | **120 s** run directly on the desktop at 0 to 19% load (verifier-VC4: 37 checks, nothing skipped); **669 s** through the runner on the desktop, niced (370e0b2's tree with the split: 37 checks, nothing skipped), with it in use: the same game, the desktop 82 to 93% busy at the start, and three other Python processes beside it - leg K took 350 s and L 249 s, against 104 s and 29 s run directly at 3 to 5% load; run directly at 370e0b2 before the split its three legs took 147 s of the whole check's 296 s with the desktop 3 to 5% busy (leg K 104 s, K2 14 s, L 29 s), and 675 s as a group with a game in the foreground (K 543 s, K2 49 s, L 83 s) | a runner stage, gate budget, since 2026-10-02 (parcel C4; the lead's split, when these legs took `lang` to 276 s through the runner on amd-arc-box, past quick's three minutes). Its legs: (K) every flag of div and sqrt through the interpreter at every format; Kepler's reference at fp32, fp64, fp128 and fp256 and at fp64 under the four other attributes, on lanes that overflow, hold a signalling NaN, hold subnormals and hold zeros, against `lang.run` at 1, 2, 5 and 10 steps, FLAGS included, its costs pinned at fp64 (545 instructions, 525 ALU, 29 registers, a 40-slot bank); 40 generated sources that divide or take a root - in equations and lets, with and without tangent vectors, under every integrator, format and attribute - each read back through its canonical form, compiled for sw, sw:4096 and sw:32768 to one image and run on seq.py against `lang.run` at 1, 2 and 5 steps, states, tangents and FLAGS (FLAGS 0x1f over the 40), each refused `target-feature`, naming FLAG_CONTROL (CAPS2[14]), on each of revision 7's targets (160 refusals), three of them through the command line too (exit 0 on sw with the text's regions, exit 3 on u50-rev7-quad, nothing written), and each one's canonical form with its written-out step and tangent lines moved above its equations compiling to the same image, never an internal error; (K2) the 40 routines of `python/cft_golden/routines.py` - division and root, four formats, five attributes - each run as a program on seq.py against softfloat over test_divfull's pools whole, 41,450 lanes, bits and each lane's own flag word; (L) the call loop: eight bodies under rk4 at fp64, whose step with its 224 routines inlined passes the compiler's constant, 32,768 instructions, compiled with its largest batch (the 56 divisions of 1 in rk4's first two evaluations) looped alone - 31,342 instructions written, 41,957 run, 243 scratch slots, inside sw's 256 - and run on seq.py against `lang.run` at 1 and 2 steps on 7 lanes, FLAGS included; Kepler under rk4 at fp64 and fp256 with the constant lowered, every batch looped and the largest alone, on 10 lanes at 1, 2 and 5 steps; the fp64 image with every batch looped certified through cft-segrun on libcft's software backend (a main run and a half-step run) and accepted by the golden reader, the golden audit and cft-audit, in full and sampled, line for line; and (I2) the routines' tally, from these legs alone: div and sqrt each compiled and run at every format and under every attribute and integrator (50 and 33 images), the five flags raised by those runs, and 11 call loops of 88 calls run, of both routines. The routines' and the call loop's plants are the `lang` stage's (seven of its twelve). Without cft-segrun or cft-audit it names the certificate it cannot make with a SKIP line, which the runner counts as an inner skip |
| `tangent` (`programs/tangent_check.py`: the language's variational equations, docs/LANGUAGE.md, "The variational equations") | not measured quiet | **209 s** through the runner on amd-arc-box, niced (e737aea, 2026-10-02: 130 checks, nothing skipped, parcel L4's leg L among them); 217 s at a5ffac7 (116 checks, nothing skipped; 209 s at 67eb0a6); earlier **346 s** through the runner on the desktop, niced, with it in use (lang-l3 at 9713a8b with the stage, 2026-10-01: 115 checks - 116 since the placed ties and zeros, 200 s run directly with the desktop at about 4% - nothing skipped, the driver 326 s of it, the relink of cft-segrun and cft-audit with it); 196 s for the same 115 run directly six minutes before: the desktop's load, every leg slower by about the same factor; a third run, on the committed stage (baa8c20), was stopped unfinished after 13 minutes with another process holding the desktop at 100% CPU, its corpus leg 211 s and its Lyapunov leg 200 s, ten times their pace alone | a runner stage, gate budget, since 2026-10-01 (the language round's L3; the lead's decision). A system that declares `tangent v` carries its step's derivative along tangent vectors, and every image the compiler writes for one runs on seq.py against `lang.run`, bit for bit with FLAGS, states and tangents, at 1, 2, 5 and the image's own steps. Its legs: (A) Lorenz-63 and Henon-Heiles with one tangent vector at fp32, fp64, fp128 and fp256, Lorenz-96 at fp64 and fp256, Lorenz-63 with two vectors and under the four other attributes, on lanes that include the primal's three special lanes and three whose tangents hold a signalling NaN, a -0 and a subnormal, and the largest finite with alternating signs - the first asserted to raise invalid and the last overflow, in FLAGS and not in the primal's flags; (B) the `lang` stage's nine written shapes given a tangent, eight of the stage's own (time in the state; three placed on ties and zeros - the min family at a tie, abs and copysign's two sources at a zero, and both inside expressions under rk4 - each run with two more lanes whose third component is their first; one side of a min or a select identically zero, every activity pattern of fma, lets and a lane param under stormer-verlet with two vectors, a map with h), Lorenz-63's tangent written out in full (its canonical form) and 24 generated systems, one in five with two vectors, at every format L1 takes them: 154 compilations on 9 lanes, 11 for the placed shapes; (C) on each system of A and B, the primal unchanged - its states and primal flags those of the system without its tangent, and the graph's primal lines the version-1 graph's, byte for byte, or by value where a rule added 0, 1, -1 or 2 to the constant table; (D) the tangent sections evaluated exactly against the stage's own dual numbers in exact rationals: 464 points on 76 systems, 232 of them placed (112 with one component set equal to another, 120 with one set to zero), and 24 on the three placed shapes, at x = z with the tangents of x and z different, where a tie given its second operand's tangent, or a zero's sign taken as -, is asserted to give another answer. Before verifier-VL3's send-back the leg's ties and zeros had equal or zero tangents - min(x, x), abs(y - y) - and two planted conventions, a tie taking the second operand's tangent and abs at zero giving -da, passed it; on this one each is red, at 5 and 3 of the 464 points and 18 of the 24 (the plants kept out of the tree: the round's ledger, L3.md); (E) Lorenz-63's largest Lyapunov exponent: `programs/systems/lorenz63-rk4-tangent-fp64.cftl` compiled at 10,000 steps a segment and run through cft-segrun on libcft's software backend one invocation a segment, 8 lanes from rational starts over the attractor's box, a transient of one segment (t = 100) with the tangent zero, then the tangent (1, 0, 0) for 10 segments (t = 1,000), scaled between segments on the host by an exact power of two; it must be within 0.01 of the figure 0.9056, and is 0.9020 (lanes 0.8946 to 0.9130). The run length and tolerance were set from a measurement made first: 16 lanes at t = 1,000 gave 0.9051, one lane's standard deviation 0.0054 and 4-lane means from 0.9014 to 0.9088; at t = 200 the one-lane deviation was 0.0141. The scaling is held exact - two renormalised segments are one unrenormalised segment of 20,000 steps, the tangent times 2^-K bit for bit - and cft-segrun's segment is seq.py's scratch-out byte for byte; (F) the exponent again at fp256 from one certified chain of 40 segments of 2,500 steps on 4 lanes with no renormalisation (the tangent grows by about e^906, inside binary256's range), read from the certified final state: 0.9047, within 0.02; the golden reader, a sample by the golden audit and cft-audit in full and sampled accept the chain, the golden verdict line for line; (G) cft-segrun's certificates of the four compiled variational references (a main run, a half-step run on the halved bank, a step-halving estimate), each accepted by the golden reader, the golden audit in full and sampled and cft-audit in full and sampled; (H) two processes under PYTHONHASHSEED 0 and 4242 writing the same bytes, those the bytes `programs/systems/compiled-tangent/` holds (`programs/tangent_check.py --write` remakes them), and the `lang` stage's 64 committed files still the compiler's (48 until parcel C4's Kepler references, 2026-10-02), their graphs version 1; (I) refusals by name: `tangent-mismatch`, `tangent-scope`, `scratch-capacity` (Lorenz-96 with one tangent vector at N = 99 on the software backend, 257 slots; N = 98 fits at 255, and N = 99 is accepted on u50-rev7), `program-capacity`, `lane-shape` and (L4) `runtime-routine` for a quotient and a root with two tangent vectors on every built-in target and on sw:4096 and sw:32768, and the command line's exit 3 for a tangent written in part; (J) plants: three wrong derivations (a wrong product rule, fma's third tangent dropped, a tangent reading the wrong primal value), red on D, at 44, 14 and 28 points out of 76, and on the exponent, 4 lanes at t = 200 (NaN, 2.6819 and -0.4316, against 0.8987 unplanted); the same rule rounded otherwise, green on D as docs/LANGUAGE.md says it must be, and red on the committed graphs, all four moved; four in a copy of the compiler, red on seq.py on every one of its 16 lanes - a tangent node dropped from the image, which the internal check stops, and three in the IR's reading of the graph (a tangent reading the wrong primal node, the tangent's outputs rotated, one vector reading another's inputs), which the internal check accepts, since it holds the image to the lowering, so that seq.py against the interpreter is the only net for them; (K) a coverage tally: every operation the rules write, all seven activity patterns of fma's operands, every format, attribute and integrator, one vector and two, and the four flags raised; (L) (parcel L4, 2026-10-02) the quotient's and the root's rules, golden-only since the compiler refuses both until parcel C4: four written shapes and 24 generated systems that divide or take a root, with tangent vectors, 27 of them held (one generated source is refused by the language, `h-nonlinear`, as a writer's would be) - 93 points exactly against the stage's own dual numbers (the quotient by the quotient rule, the root as the exact evaluation takes it) and 65 against a central difference at 2^-64 in exact rationals, no miss; the primal unchanged in each; the rules at their specials bit for bit; and three plants, the root without its 2 and the quotient's wrong sign red on both checks, a right root derivative written through r·r = a green on the difference and red on the exact check. Without cft-segrun or cft-audit it names the legs it cannot run with a SKIP line, which the runner counts as an inner skip |
| `acceptance` (`programs/acceptance.py --legs set,oracle`: the acceptance set - everything that runs on the card today, each entry one run fixed in `programs/acceptance.json` - and the hard workloads' own oracle) | not measured quiet | **481 s** through the runner on amd-arc-box, niced (7ccc441, 2026-10-02: the set's 20 entries and the oracle's 21 programs, 249 checks, nothing skipped); 484 s at e737aea and 481 s at 1acc73a; earlier **375 s** run directly on the desktop, niced, with it in use (2026-10-02, 249 checks, nothing skipped): compiling the ten workloads about 240 s of it, the oracle leg 61 s, the interpreter's 53 s of it; making the set with `--write` took 312 s | a runner stage, gate budget, since 2026-10-02 (the step-6 round's parcel A1; the lead's choice of budget, which put the four oracle images past the card in `acceptance-far`). THE SET: the six compiled references and the four variational ones, their committed files in `programs/systems/compiled/` and `programs/systems/compiled-tangent/`, and the ten hard workloads that fit u50-rev7-quad (programs/workloads/README.md), compiled here for it from the pack's sources, each image and bank held byte for byte to the set's SHA-256. Each entry is one run of 4 segments - the references at their images' own 100 or 20 steps a segment, the workloads at 8 (phi4, FPUT) or 2 (the reservoir, Kuramoto-Sivashinsky, Riccati) - on one block a tile of the quad, 256 lanes at fp64 and 64 at fp256: the workloads on their own three initial conditions as lanes 0 to 2, held equal to the pack's vectors' requests, and on copies of them perturbed exactly - lane k from 3 on is lane k mod 3 with (k // 3) x 2^-30 added to its first value, every value rounded once, and every lane distinct (the lead's hard_card.py); the references on full-significand values drawn from SHAKE-256 in each system's box, no random module, with a lane that overflows, one holding a signalling NaN and one holding subnormals on tiles 1 to 3 and, for the variational ones, three special tangents beside them. Through cft-segrun on libcft's software backend at `--scratch-depth 2048`, the card's, it holds: the initial state to the set's SHA-256; every boundary's open state hash, and every segment's flags and STATUS, to the set's; the certificate's own lines and boundary files to what ran; cft-audit accepting each certificate in full; the golden audit re-running segment 3 of the six entries whose segment seq.py re-runs in about ten seconds or less (lorenz63 at fp64 and fp256, lorenz96 at fp256, henonheiles at both, lorenz63-tangent at fp256), with cft-audit handed the same choice printing its verdict line for line; and a golden spot check on every entry, its last segment re-run on seq.py for its first three lanes, the first lane of each other tile and its special lanes, each equal to its certified end. Its controls, on the first entry's own certificate and states: a boundary hash, a flag word, a parameter and an initial-state digest planted in its record, a bit flipped in boundary 2's file, caught by the file check, cft-audit (`state-hash`, exit 4) and the golden audit (`state-hash`), and a bit flipped in lane 0 of the last boundary's state, caught by the spot check. THE ORACLE: the pack's one-step vectors, from the other model's own exact evaluator, held against `lang.run` on all 21 programs, the extended ones included, and against the ten card images on seq.py (the set's compilations, their REPEAT set to 1): states, FLAGS and each lane's FLAGS alone, with the pack's digests and each vector's format layout, and two controls planted in a copy of a vector. With `--device <xclbin>` the same driver is a card's admission test, which a card passes when every digest is the set's, cft-audit accepts every certificate in full and the golden checks accept it: the lead's run. `--golden all` re-runs every segment of every entry on seq.py: 2,281 s on amd-arc-box (61f8b66, 2026-10-02, A1's branch before its last two fixes: all 20 entries, 188 checks), the lead's run; about 45 minutes on the desktop, estimated from seq.py's measured cost a segment and not run there. `programs/acceptance.py --write` remakes the record on the software backend alone, and writes it only when every entry is made and every check passes. Without cft-segrun or cft-audit it refuses to start, by name |
| `acceptance-far` (`programs/acceptance.py --legs far`: the hard workloads' own oracle on the four images past the card) | not measured quiet | **289 s** for two of the four, run directly on the desktop, niced (2026-10-02): Gray-Scott wide compiled in 85 s and Lorenz-tangent wide in 200 s, each image equal to its vector, the two controls caught; Gray-Scott hard compiled in 127 s in an earlier probe, its image equal to its vector; Lorenz-tangent hard not run here, believed about its wide twin's 200 s; so about ten minutes for the four, believed; through the runner, the lead's | a runner stage in no budget, so the full census only, since 2026-10-02 (the lead's choice: about ten minutes here, nearly all compiling, and the box runs the gate at about half this desktop's pace). Gray-Scott and Lorenz-tangent, hard and wide, each compiled for sw:32768 at one step and run on seq.py, its states, FLAGS and each lane's FLAGS equal to the pack's one-step vector, with the pack's digests, the format layout and two controls. Python alone. The pack's own runner verified the same four on amd-arc-box at 80abee5 (docs/VALIDATION.md, 2026-10-02) |
| `audit` / `make -C host audittest` (host/tests/audit_check.py: `cft-audit` held to `cert.audit`, the same refusal by name, exit code and location, or both ACCEPTED with the same verdict lines; docs/CERTIFICATES.md, "The audit tool") | not measured quiet | **460 s** on the desktop, niced, with it 43 % busy from other work (17,865 checks, 0 failed, 0 skipped, at parcel CV2CA's c8acc93, 2026-10-03): 149 s of it test_cert.py shadowed (94 s the tool's 6,509 runs) and 175 s test_cert2.py shadowed (146 s the tool's 10,915); **445 s** at b886236 in verifier-VCV2CA's run, at 7 % load (17,865 checks, 0 failed). Before version 2's C half, **219 s** on a day the desktop was in use (6,799 checks at ca1327f, 2026-09-29, the corpus read from P2's tree at 679c64d): 109 s of it test_cert.py shadowed, 67 s of that the tool's 6,505 runs. 209 s (6,781 checks) at b10047d, before the second narrow build; 216 s (6,742) before verifier-A1's first send-back | a runner stage, gate budget, since 2026-09-29. The lead placed it there: its first measure, 236 s, would have taken `programs` past five minutes. Seven sections: (1) the tool's own usage, `--sample` (with its `memory` past what a map can be sized for) and a drawn seed, and since version 2's C half (parcel CV2CA, 2026-10-02) version 2's usage refusals, cft.h's `CFT_PROFILE_*` and `CFT_LANGUAGE_*` held to python/cft_golden/profile.py and lang/version.py - the lead's choice of where those macros are held - with the tool's writer's list of variables and its generators held to cert2.py's, and (1d) thirteen version-2 controls no test_cert2.py call hands the tool as it is handed them: `definition-differs` inside each re-derivation a source-free audit reaches past step 4 (a segment line's flags and block, a replay line's raw end and its absence, the wider-source relation), audits accepted under a definition that does not cover the certificate's, a signature file whose key encodes no point and one naming another certificate, the wider-source relation's lanes and steps, and blocks past segment 9; (2) test_cert.py and test_cert2.py shadowed, every top-level parse call handed to the tool too, and every audit call whose arguments files and options can carry (244 calls in test_cert.py, where it makes 283, and 139 in test_cert2.py, where it makes 147; the others are counted and named by reason), a version-2 audit call held to the golden auditor handed no source and not asked to regenerate, as the tool is (83 and 6 of them); (3) cft-segrun's certificates of segrun_check's programs; (4) the golden corpus, its 37 version-2 cases and controls handed to the tool too since CV2CA, as corpus.py hands the golden auditor its inputs but the source and the regeneration, each also from every committed state and, where replays are, choosing the segments with none, where the tool accepts - measured at b886236, 20 keep the manifest's verdict so, and of the other 17, each given one verdict by both auditors, 8 are refused `source-missing` and 3 `state-missing` before the check the case is for, 3 `aux-source` and 1 `aux-image` at run 1, and 2 accepted, v2-source-format and v2-source-shape, whose defects only the source shows (the stage prints each by name); (5) two narrow builds at `CFT_MAX_FORMAT=2`, at its own bigint and at `CFT_BN_LIMBS=64`: `build-width`, `build-format` wherever a format above the ceiling would reach the library, and what each audits in full; (6) the tool's numerics against Python's integers through a probe build; (7) since CV2CA, the tool's Ed25519 and SHA-512 (tools/ed25519.h, tools/sha512.h) through the same probe build, against every vector python/tests/test_ed25519.py carries, each answer the golden model's, and SHA-512's published examples and every length across its padding against hashlib (3,129 operations). It needs pytest, and a C compiler for (5), (6) and (7). Its census of plants, host/tests/audit_plants.py over the gate's recorded cases, took 157 s on ca1327f's tools/audit.c: 167 sites, 148 red, 12 green and 7 unreached, each named in docs/CERTIFICATES.md; since CV2CA it also reports version 2's names, each one's sites as reached or not and each name with no site (a check that needs a source or a regeneration, which cft-audit does not take) with why - not yet run on version 2's sites |
| `estimates` (`programs/estimates.py certified --cases lorenz63-rk4-fp64,lorenz96-rk4-fp64 --against docs/studies/acc-a/certified.out.txt`; docs/studies/ACC-A-estimates.md) | not measured quiet | **50 s and 51 s** through the runner on the desktop, niced: two clean runs at cc4f6c4, verifier-W2's with the desktop 2% busy at its start and the author's (38 checks, 2026-09-30); 72 s under the repository's `.venv` (mpmath 1.4.1 in pure Python), not through the runner | a runner stage, gate budget, since 2026-09-30 (the lead's decision). It re-makes every lane of both cases: the step-halving estimate against the converged reference (check.py's 300-digit arm with the bank's h-slots halved until two levels agree to 1e-6 of the method error; K = 6 here), the wider estimate against the arm itself, odefun's cross-check and the time shift. Each case's section is held line for line to the committed run, apart from `time` lines. The first difference fails the stage, naming the file, the section and the committed line, with both lines. Every committed section of the two cases it is asked for must be printed. Each case must be scored, which its printed lines must show: its max-lanes estimate held to cert.derive. Without `--against`, a heading alone passed that end check until the second send-back (verifier-W2's headonly); the stage, which passes `--against`, failed it at every commit. "Scored" means the step-halving estimate scored at the last boundary: a section cut after that table passes the end check, and `--against` fails it (verifier-W2's tailcut). The loading section is held line for line to the two cases' committed lines. `--cases` refuses by name, before any scoring, a case the corpus lacks or does not score, and an empty name inside a list (a leading, trailing or doubled comma). `--cases ""` reads as no `--cases`, and scores every case. Since CV2B (2026-10-02) it reads the corpus's version-1 cases alone, so version 2's are neither scored nor listed, and `--cases` naming one is refused by name. It runs no C, because the certified states are the corpus's committed files: python and mpmath only, and without mpmath it is skipped by name. mpmath 1.3.0 on gmpy and 1.4.1 in pure Python print the same sections (measured 2026-09-30). Watched failing in a fresh copy of the tree, one committed number changed (lorenz63-rk4-fp64's lane-0 ratio at its last boundary, 0.9525064 to 0.9525065): `estimates FAIL 28s`, the section and its line 104 named. Until 35ec784 a run that scored fewer of the named cases than asked, down to none, passed: verifier-W2's code plants P3a (lorenz96 loaded but never scored, `estimates ok 27s`) and P3b (the case list emptied after loading, `estimates ok 0s`). At 35ec784, through the runner in a fresh copy: P3a `estimates FAIL 34s`, P3b `estimates FAIL 0s`, each naming the committed section that was not printed (the round's ledger, S2.md) |
| `estimates-full` (`programs/estimates.py all`, its `--tool` the cft-segrun the stage builds, `--against` both of docs/studies/acc-a/'s committed runs) | not measured quiet | **9 to 14 min** on the desktop, niced, from its two halves (2026-09-30): 355 s + 206 s in the committed runs, made one at a time without the runner; 441 s + 406 s in verifier-W2's runs of the same two halves, the desktop 5% busy just before the certified half and 1% just before the sweep half (38% a few minutes before either). The whole stage, one process with its own cft-segrun build, is not yet run through the runner | a runner stage in no budget, so only the full census runs it (the lead's decision, 2026-09-30). It re-makes the whole study: every ODE case of the golden corpus scored at every boundary, and the sweep, whose one-lane certificates cft-segrun (built here first) makes at every level and the golden audit samples. Both are held to their committed runs as `estimates` is. It needs a C compiler and mpmath, and is skipped by name without either. Watched failing in a fresh copy of the tree for one committed number changed (lorenz63-rk4-fp64's lane-0 wider estimate, 1.75873e-15 to 1.75874e-15): its command, run by hand as the lead asked, failed in 26 s at the first section, naming the section and its line 116. The sweep sections' comparison was watched failing for one number changed in sweep.out.txt, in `sweep --cases lorenz96-rk4-fp64`, and passing unplanted. At 35ec784 its command, by hand, fails verifier-W2's P3b (the case list emptied after loading) in 1 s, naming the first committed section not printed; until then it passed it, rc 0 (the round's ledger, S2.md). Its first run through the runner is the lead's, at the merge |
| on the card: `hw/run-device-test.sh <xclbin> -q -n 8`, `-n 4096`, `-r` (docs/CARDDAY.md steps 2-3) | seconds each | | measured 2026-09-08 on the U50: 4 to 8 s, 2 s, 1 s |
| on the card: `cft-selftest vectors/out <xclbin>`, the published sets through the tile (step 4) | **about 10 min an image** | 11 min beside a Vivado run; 12.8 min (766 s, the runner's 1,224,915 cases) on revision 7's single beside two Icarus stage runs, 2026-09-29 | one element a call for exact flags, so latency-bound; the same 584-642 s on one tile and on four |
| on the card: the soak (five matrices, the sets again, ten orbit checkpoints per image; step 7) | about 20 min an image | | a tool that talks to the card must be built with `XRT=1`, or it says "no such device" |
| on the card: `cft-resident <xclbin> --op all` (the engine's own rate, with software, cross-unit and repeat checks; step 6) | 20 to 40 s an image | | `make -C host XRT=1 cft-resident`; four units at once on the quad |
| on the card: `device-test <xclbin> -b -n 4096` and `cft-bench <xclbin> --resident` (the library's resident path held to the staged one, then measured) | 1 s and 25 s an image | | since ABI 0.11; `-b` also runs on the software backend in the runner's `selfcheck` stage |
| `hw/run-device-test.sh` under hw_emu (xsim, the desktop's WSL, 2026-09-07/08) | link: one tile 4 min, four tiles 6 min | every kernel invocation 1 to 3 min whatever its element count | `-s -n 24` on four tiles **333 min** (98 checks); `-q -n 8` on one tile passed fp32's 50 checks in 221 min and was stopped; `-r` is days. Not an evening check until device-test has an emulation budget. Since 2026-09-18 the scratch leg's strict section adds two invocations a format, and the 32,769-lane program leg is skipped BY NAME when `XCL_EMULATION_MODE` is set |
| `formal` (30 proofs plus the negative control; the gate's own verdict line counts all 31 as tasks) | **7 min** on the merged tree with the box otherwise idle (420 s of solver time; 14 min in an earlier run beside other work) | the same gate ran for **more than two and a half hours** earlier that day and had to be stopped - not load, but an IMUL equivalence task that had been left in the list and does not close; parked, the gate was back to 7 min | the fp256 fold lemma alone is 2 to 4 min; the old four-proof gate was 29 s, which is the number older notes quote |
| `character` | 2.6 min | 5 min | |
| `transcend` | 12.6 min | **52 min** | the thirty-nine functions twice, the second pass through the escalation path |
| `bindings` (cftmpfr vs gmpy2) | 2.4 min | 8 min | |
| `cpp` (C++17 and C++20, each a full replay) | 25 min | not measured loaded | |
| `node` (unit tests, `program_test.mjs` + `conformance.mjs`) | 5 min + 17 min | | |
| `wasm` (`verify.mjs`, the page without a browser) | 11 min | 30 min | the page's own embedded sample first, 4,015 cases over 20 sets replayed as its section 2 does (the build's `negative_control.html` fails there by name, `verify.mjs --page`); then 1,068,915 cases through the page's bytes on `make vectors`' sets (about 1.2 million at the runner's generator counts), then 832,915 over 148 sets through the wrappers. The module must be REBUILT when an opcode is assigned, not merely revisioned: this lane replays the sets, so one predating opcode 31 failed 20 of 148 - all twenty reduce sets, each at its first `maxall` case |
| `mpfr` | 8 min, and about half a minute more for `mp-err-check` (28 s on the desktop, 2026-09-30) | | since 2026-09-30 the stage ends with `host/tests/mp_err_check.c`: every error rule `host/src/mpfloat.c` derives held to its claim exactly, each verdict computed in GMP - W = 6 exhaustively (every significand pair, alignment and sign pair against fourteen counts from zero past 2^W to infinity), a fixed-seed sample to 928 bits, and verifier-W4's scaled-down clamp end to end - and, against MPFR's directed roundings, the count `cft_mp_const` gives all six constants at every W from 2 to 928, and `transcend.c`'s conversion of an argument's error into its logarithm's (`mp_log_of_mp`, through a probe build of `transcend.c` that only this tool compiles) over 8,000 arguments: 16,814,033 results, 28 s on the desktop niced. `transcend.c`'s own allowances (a truncated series' tail, `mp_bump`) are not held by it. Its controls must fail and do: the old rules' counts fail the same verdicts on 847,605 operands, a comparison made on the stored value alone on 568,676, a constant's count cut to one unit on 1,567, and the logarithm without its argument's error on 695. Built against the library as it was before the count had an exponent (aeb3f5e) with `-DMP_ERR_CHECK_BASE`, which leaves the MPFR legs out, it fails on 3,969,901 results out of 10,334,817, W4's case among them, and its transcription of the old rules equals that library on every operand compared. GMP and MPFR come with the stage's own probe; `mp-err-check --full` is the long sweep, not in the stage |
| `soak-quick` | 1.6 min | | |
| `photograph` (a GPU's record, four passes of 1,048,576 samples side by side) | 1.7 min | | 101 s a pass on one core with four running, 88 s alone; 1.2 s a pass on the U50's tile (atlas-engine, 2026-09-18). The expected hashes are an NVIDIA GPU's, not the model's |
| the workload checks (`collatztest` ... `zoomtest`) | 1 to 3 min each | 1 to 3 min each | |
| `remote` (`make -C host remotetest`) | | 10 to 12 min | the bounded replay is most of it |
| `wstest` | | 2 min | |
| `embedded` (`make embedded`) | 18 to 19 min | | the vendored-copy check, four loopback profiles built, the published sets replayed through each (1,068,915 cases twice, 271,776 and 195,248 for the two `CFT_TINY` profiles), the corruption control, and fifteen board compiles through `arduino-cli`. Needs the AVR, ESP32 and RP2040 cores installed; skips the compiles with a note if `arduino-cli` is absent |
| a board census (`serial_replay.py --port COMn`) | 1 h+ per board | | not a gate and not in the runner: it needs a part plugged in. About 200 to 550 cases a second on an ESP32-S3 depending on format and operation, so the full 1,068,915 is hours. Use `--sets` and `--limit` for anything routine |
| the fuzz lane (`make -C host fuzz-run`) | 1 min per target at the default; 30 min in the 2026-09-07 campaign | | `FUZZ_SECONDS`; the sanitizers need the `cft-sim` image, MSYS gcc has none |
| a wasm module rebuild (`bindings/wasm/build.sh`) | 5 min | | in the pinned emscripten image |
| OOC synthesis, one kernel (`hw/mc_sweep.sh ... synth`) | 10 to 32 min | | U50 647 to 1,905 s; K325T 626 to 1,272 s; A200T and Z020 6 to 12 min |
| OOC implementation, one kernel (`... impl`) | 24 min to 1 h 46 | | K325T 1,429 to 2,608 s including its synthesis; U50 2,591 s quiet, 6,351 s under load |
| a shell link, one tile | about 1 h 50 | | 15 GB at implementation's peak - 15,021 and 15,262 MB in the rev4 and round2 singles' `runme.log` (read 2026-09-23); older notes, and the first `hw/sweep_freq.sh`, say 12 |
| a shell link, four tiles | 3 to 4 h | | 25 to 30 GB of the build box's 46; one at a time or the placer is killed and it looks like a design failure |

The budgets in `verify/run.sh` are cuts of that table: `quick` is the
`docs`, `generated`, `buildargs`, `sweepjudge`, `innerskips` and
`ensurevectors` checks, the
model-versus-C stages, the language's compiler (`lang`, about two
and a half minutes run directly on a quiet desktop since its routines'
legs left it on 2026-10-02), the GPU's photograph, the bindings, the language
legs, the soak spot check, the workloads, the demos and the remote
backend - about twenty minutes after a host build; `gate` adds the golden
suite, the vectors, the library replay, the transcendentals, MPFR, the
C++ replay, lint, formal, the C auditor's gate (`audit`, about four
minutes since 2026-09-29), two cases of the estimates study
(`estimates`, under a minute since 2026-09-30), the compiler's
routines (`lang-routines`, about two and a half minutes run directly on a
quiet desktop since 2026-10-02), the language's variational equations (`tangent`, three to six minutes since
2026-10-01, far longer on a busy desktop) and the acceptance set
(`acceptance`, about six minutes since 2026-10-02) - **about two hours quiet
and four loaded on this host**, most of it `cpp`, `transcend` and
`formal`; `full` adds the simulation suites (`sim`, `simmc`), node, wasm,
the staged images, the whole estimates study (`estimates-full`, 9 to
14 minutes) and the hard workloads' oracle on the four images past the
card (`acceptance-far`, about ten minutes), which is the census. The runner writes a `.ok` per stage and `--resume`
reruns only what has none, so an interrupted run loses at most the stage
it was in. There is **no cache across runs**: a run id is a timestamp
plus the commit, so a fresh invocation re-runs everything and `--resume`
is the only thing that skips work. (cft-rebound is the sibling repo with
a content-addressed gate cache and a warm five-second check; this runner
does not have one.)

`bash verify/run.sh --list` prints all fifty-one stages with a marker
against the ones the given `--budget` or `--only` would actually run, so
the list cannot imply a budget covers more than it does. The stage names
are derived from the `stage` calls themselves rather than kept in a second
list - they were kept by hand in three places once, and two of the copies
drifted.

The `docs` stage is the cheapest of them and exists for the same reason:
`docs/README.md` indexes the forty-two documents, and
`python/check_docs_index.py` refuses a broken link, a document missing
from the index, or a stated line count that no longer matches the file.
Since 2026-09-24 it holds every tracked document, not only the index:
every relative link resolves, every repository path quoted in backticks
exists (a path in another repository carries its name,
`cft-rebound/docs/...`; the record documents and the products of a build
are exempt, each exemption re-derived from the file that justifies it),
and the counts the front-door files state - stages, benches, proofs, this
page's twelve tiers, the index's own totals - are derived, bold or not.
The sweep that added this found `README.md`'s at-a-glance table a stage
short, in bold, where the old patterns could not see it. Every run plants
a fault for each check in a scratch copy and requires it to be caught by
name, so the stage cannot pass without having just watched itself fail.

`generated` is the same idea aimed at code rather than prose. Four
scripts in the tree own a committed artifact and each already had a
`--check` mode that exits 1 when the file on disk differs from a fresh
generation - `hw/gen_layouts.py`, `host/tools/gen_2opi.py`,
`host/tools/gen_mp_consts.py` and `bindings/node/make_seq_corpus.py` (a
fifth, `python/gen_divfull.py`, joined on 2026-09-14, and a sixth,
`bindings/arduino/sync.py`, on 2026-09-30: the Arduino library's
vendored copy of host/, which no stage had checked until then, as
verifier-F4 of the fixes round found). **Nothing invoked
any of them**, and by 2026-09-13 two had drifted: the five
`hw/layouts/*.cfg` carried a superseded WNS note in a commented-out clock
line, and `bindings/node/seq_corpus.jsonl` had been stale since the `kx`
corruption kinds landed - so the wasm harness replayed a 192-case corpus
containing none of them, and passed. A file whose header says "GENERATED
by X; edit the table there, not this file" and which nothing checks is a
comment rather than a guarantee; this stage is what makes the comment
true. `make_seq_corpus.py` needs a built libcft, which the stage builds
itself wherever a C compiler is (the Makefile's shared-library target:
`make -C host cft.dll`, `libcft.so` or `libcft.dylib`). Only on a host
with neither a compiler nor a built library is it skipped by name, and
that skip is an inner skip: the runner names it under the stage's row
and on its `VERDICT:` line, and `--require-all` fails it. Staleness is
recognised from the generator's own message, and any other nonzero
`--check` fails the stage rather than reading as a skip.

`buildargs` is the third of that family and the only one that tests a
build without building. `hw/rebuild-2022.sh` assembles the v++ link line
in shell variables, and an inner loop once reused the name that held
`--clock.freqHz`, so setting `VPP_PROPS` **erased the clock constraint
while the build still reported success** - the failure CLAUDE.md warns
about, two hours to reach and visible only in a timing report. The script
credited "the stub-v++ argv test" with catching it from the day it was
fixed; that test did not exist until 2026-09-13.
`hw/test-rebuild-argv.sh` is it: stub `v++` and `vivado` on `PATH`, the
REAL script run with `VPP_PROPS` set (an empty `VPP_PROPS` is exactly the
case the bug never broke), and the argv v++ was handed read back - for
the single and the quad link configs, checking the frequency and that the
constraint names every compute unit. Its negative control puts the defect
back into a copy of the script and requires the check to catch it, the
same rule `formal/` keeps. Since 2026-09-14 it also holds the generics
plumbing: `CFT_GENERICS` must reach the `vivado` invocation's
environment and be recorded in the manifest, and - the control - when
the stubbed wrapper read-back reports a requested generic at its RTL
default, `rebuild-2022.sh` must stop before `v++` is ever invoked,
because a `.xo` that silently packaged the full tile is the two-hour
mistake `hw/verify_xo.tcl` exists to catch in twenty minutes.

It is **skipped by name on any host with Vitis installed**, and that is a
refusal rather than an oversight: `rebuild-2022.sh` sources
`$root/Vitis/2022.2/settings64.sh` before it looks for `v++`, which
prepends the real toolchain - measured on amd-arc-box, where a stub first
on `PATH` became `/data/Xilinx/Vitis/2022.2/bin/v++` after the source. The
stub would lose and a two-hour link would start on a build host. So the
stage runs where Vitis is absent, which includes CI.

`innerskips` and `ensurevectors` hold the runner itself, with its two
own tests, which no stage ran until 2026-09-30. A stage table widened
by one commit broke `verify/test-inner-skips.sh`, which matches the
inner-skip rows exactly, and only a verifier running it by hand saw
it (verifier-W2, the steps 5 and 6 round). `innerskips` needs bash
alone (about a minute); `ensurevectors` runs the vector generator at
small counts, so it needs python with mpmath (about a minute).

`sweepjudge` holds a frequency sweep's verdicts without a build. A point
of `hw/sweep_freq.sh` is CLOSED when the kernel clock's own WNS - read by
name from the last timing summary the flow wrote, the manifest held to
the summary it names - is not negative, MISSED when it is, and NONE when
there is no such number or the records disagree. The script's first
version (2026-08-29) read the whole-design WNS: on the builds it left on
amd-arc-box its own summary says 0.036 and 0.055 ns at 115 and 145 MHz,
where the kernel clock had +0.409 and +0.084. `hw/test-sweep-judge.sh`
holds thirteen synthetic builds in Vivado's report layout to their
verdicts - the shell's +0.055 above a kernel miss, an image staged with a
negative WNS, a post-route phys_opt that moved the number after the
routed summary was written, manifests that no longer agree with their
summaries - and puts each of the two defects back into a copy of the
script, where the case written for it must catch the copy. It needs no
Vivado and no card, so it is never skipped: 0.7 s on amd-arc-box, about a
minute under Git Bash.

Two things are always true of the wall time. **Vivado runs one at a
time** on a shared host - the queue scripts this project uses check
`tasklist` for another `vivado.exe` before launching, because two
implementations at once are slower than two in sequence and a quad
placement alongside anything else exhausts the memory. And the
container suites parallelise cleanly (`SIM_JOBS`, `-j`), but four jobs
on a box that is also placing a design gain little over one; the
55-minute `sim` this table gave until 2026-09-29 was four jobs beside a Vivado.

## What each verdict line looks like

So that a log can be read without the harness:

- cocotb prints one `** TESTS=n PASS=n FAIL=0 SKIP=0` block per
  target; the runner's `sim` stage is green only when every target's
  results file says FAIL=0 and none is missing.
- the formal gate prints one `PASS  <sby> <task>` line per task and
  ends with `FORMAL GATE: PASS (n of n, negative control refuted)`; a
  task whose solved model carried fewer checks than the gate expects
  prints `VACUOUS` and fails.
- before it replays `vectors/out`, every runner stage that does
  (`libcft`, `cpp`, `node`, `wasm` and `remote`'s WebSocket leg) prints
  `ensure_vectors: vectors/out/SHA256SUMS names all 168 sets
  vectors/SHA256SUMS names, and all 168 it names hold`, or says by name
  why the directory is not whole and regenerates it; the `vectors` stage
  ends with the same words after `vectors:`.
- the library replay prints `168 sets, 1068915 cases, all matching` after
  `make vectors` (1224915 in the runner's `libcft` stage) and
  `api-test: all contract checks passed`; the remote gate ends with
  `remote_check: every check passed`; each workload check ends with its
  `... CHECK OK` line and a comparison count; `verify.mjs` ends with the
  case count and `library matches the vectors exactly`, then the
  wrappers' count, and `VERIFY OK`; `verify_demos.mjs` with `VERDICT: the
  browser's compute core produced the C tools' chains`.
- the runner ends with a census block shaped for docs/VALIDATION.md,
  after a line per stage (ok, FAIL, or SKIP with the skip's reason) and a
  `VERDICT:` line. An ok stage whose log has lines whose first word is
  `SKIP` or `SKIPPED` - checks inside it that did not run, pytest's `-rs`
  lines among them - or the conformance replay's
  `<set>: ... skipped, ... on this device` carries `+ n inner skip(s)`
  with each line beneath it; the `VERDICT:` line, the census and
  `report.jsonl` count them by stage, the census names them, and
  `--require-all` fails them (verify/README.md).

## Running one thing

    make golden                                  # the model
    make vectors                                 # the sets
    make -C host test                            # the library and the replay
    make -C host seqtest enclosetest zoomtest    # a model-vs-C stage, a workload
    make -C host remotetest wstest               # the network
    bash formal/run.sh                           # the proofs (re-execs in cft-formal)
    docker run --rm -v "$PWD:/work" -w /work/tb cft-sim make -j4 sim
    docker run --rm -v "$PWD:/work" -w /work/tb cft-sim make -j4 MC=10 simmc
    docker run --rm -v "$PWD:/work" -w /work    cft-sim make yosys-lint
    bash verify/run.sh --budget gate             # the runner, one cut
    bash verify/run.sh --only sim,formal         # the runner, by name

On Windows the host builds want the mingw64 compiler on PATH and the
`TMP`, `TEMP` and `OS=Windows_NT` make variables (the Makefile header
says why), and Docker from Git Bash wants `MSYS_NO_PATHCONV=1` or
`MSYS2_ARG_CONV_EXCL='*'` so the container paths survive. A checkout
shared with WSL can hold the other platform's objects; `make -C host
clean` first, which the runner's `libcft` stage does itself.

## Where the record lives

docs/VALIDATION.md, dated entries, newest last: what ran, on which
tree, what it printed, what was not run and why. An entry that claims
a gate quotes the gate's own verdict line; an entry that could not run
one says so rather than leaving the reader to assume.
