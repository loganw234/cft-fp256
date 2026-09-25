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
   has decided.
2. **The conformance vectors** (`make vectors`). The model writes 168
   sets, 1,068,915 cases, every format under every rounding attribute,
   with the expected result and the expected flags per case. These are
   the fixed points every other implementation replays.
3. **The C library** (`host/`, `make -C host test`). Contract tests
   (`api-test`), the partition invariants (`reduce-parts`), then the
   whole vector set replayed twice - one element at a time for exact
   flags, then as arrays so a device backend's partitioning cannot hide
   a divergence - and a C-versus-Python identity check through ctypes.
   The model-versus-C stages of the runner (`selfcheck`, `divsqrt`,
   `clause5`, `character`, `transcend`, `augmented`, `status96`,
   `formatof`, `diff`, `seq`, `reduce`) then sweep the entry points the
   vectors do not reach: composed divide and square root, the
   conversions, the thirty-nine transcendentals, the augmented
   operations, the status word, the cross-format arithmetic, the
   alignment boundary, the sequencer's fuzzed programs, the reductions.
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
   image). Twenty-five cocotb targets hold the hardware to the model, and
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
   and four board targets, the third tier's own census.
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
   batch size, from either engine, interrupted and resumed. Then the
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
    the only one at all for the transcendentals.
12. **Hardware, out of the runner.** The native-oracle soaks
    (`hw/run-soak.sh`), hardware emulation, the on-card runs
    (`hw/run-device-test.sh`), and the out-of-context and shell timing
    builds (`hw/mc_sweep.sh`, the link flow) are machine- and
    schedule-bound and keep their own drivers and their own entries in
    docs/VALIDATION.md. They are where "read the path delay, not the
    slack" applies (docs/BRINGUP.md).

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
| `golden` (pytest, 2,260 tests since 2026-09-24, when four parse cases that only ever skipped were dropped; 2,264 from revision 3's model and assembler cases on 2026-09-08 evening; 2,075 before it) | 2.6 min at four workers | 8 to 13 min | on the desktop 3 skip by their own conditions (two need the Arduino loopback binary, one `math.fma`, Python 3.13+), and the runner now counts them; one revision-3 assembler test ran for the first time on the merged tree and had its expectation corrected |
| `vectors` (`vectors/gen_vectors.py` at the generator's default counts, not `make vectors`' smaller ones; 168 sets) | 5 min | 7 to 8.5 min | |
| `libcft` / `make -C host test` (build + the replay: 1,068,915 cases on `make vectors`' sets, about 1.2 million at the runner's generator counts), then `make -C host profiles-check` | 7.5 min | 8.5 to 11 min | the census was 1,071,635 until 2026-09-12, when opcode 31 became `maxall`: a reduction has no elementwise case to inherit, so 4,000 `reserved31` cases left and 1,280 maxall cases arrived. A document recording an earlier RUN still says 1,071,635 and is right to. `profiles-check` joined the stage on 2026-09-24 (about 3 min serial on the desktop, loaded): the library's fifteen sources compiled at the default, at the three reduced profiles `docs/EMBEDDED.md`'s loopback builds (`CFT_TINY`, `CFT_TINY` at fp128, the 32-bit boards') and at every `cft_config.h` switch alone, 19 in all, with implicit-function-declaration, array-bounds and aggressive-loop-optimizations as errors; and the four combinations `cft_config.h` refuses (`CFT_MAX_FORMAT` 2, 1 or 0, or `CFT_BN_LIMBS=18`, without `CFT_NO_TRANSCEND`) held to failing in every source with the refusal's own words. No runner stage had compiled any of them. From 2026-09-14 until that day `divsqrt.c` did not compile with gcc 14 or later at `CFT_NO_PROGRAM`, and so not at either `CFT_TINY` profile; and the first compile of each switch alone found `CFT_MAX_FORMAT` below 3 with the transcendentals writing past a `cft_bn` on the stack, which is now refused |
| `make -C host reducetest` (`reduce_check.py --trials 1500`: the tree, the scaling, the bits and the flags against the model) | 2 to 3 min | | listed here from 2026-09-12, having been absent from a page that calls itself the map of everything - found by asking which docs the round had made stale rather than by a gate. 13,516 reductions over four formats and all seven of clause 9.4 plus `maxall`, whose two sides are deliberately DIFFERENT SHAPES: the model folds left, the library halves. Comparing them is what tests 754-2019 `maximum`'s associativity instead of assuming it |
| `sim` (25 cocotb targets, `cft-sim` image) | 10 min at the runner's job count; about 40 min serial | **55 min at four jobs** | 3 min at twelve jobs on a 36-core box; almost all compilation |
| `simmc MC=10` (13 multi-cycle + 4 board targets) | not measured quiet | about 50 min at four jobs for sixteen of the seventeen | the seventeenth, the engine-driven board kernel, **does not finish under Icarus** in this configuration: 2.5 ns of simulated time a second through the small operations and about 0.03 ns a second inside the 1,104-element stream, 57 of 71 operations after four hours, on the tree before the cone change and after it alike; under Verilator, which its target selects, the bench is **16 s of simulation after an eleven-minute compile** (44,920 ns, both tests, parameters applied - until the evening of 2026-09-07 a Verilator build received none of a target's parameters and simulated the default, docs/VALIDATION.md) |
| `lint` (Yosys, every RTL file) | 1 min | 1.5 to 2 min | |
| `make programs-check` (the .cfta library: both assemblers, twenty-nine images (seventeen when timed), a check each, generated revision-2 and revision-3 corpora) | 10 to 60 s | | not a runner stage yet; `make programs` rebuilds the manifest it checks, so the two are separate on purpose; four of the checks waited on the revision-3 model and host by name (SKIP, not PASS) until both merged on 2026-09-08 |
| on the card: `hw/run-device-test.sh <xclbin> -q -n 8`, `-n 4096`, `-r` (docs/CARDDAY.md steps 2-3) | seconds each | | measured 2026-09-08 on the U50: 4 to 8 s, 2 s, 1 s |
| on the card: `cft-selftest vectors/out <xclbin>`, the published sets through the tile (step 4) | **about 10 min an image** | 11 min beside a Vivado run | one element a call for exact flags, so latency-bound; the same 584-642 s on one tile and on four |
| on the card: the soak (five matrices, the sets again, ten orbit checkpoints per image; step 7) | about 20 min an image | | a tool that talks to the card must be built with `XRT=1`, or it says "no such device" |
| on the card: `cft-resident <xclbin> --op all` (the engine's own rate, with software, cross-unit and repeat checks; step 6) | 20 to 40 s an image | | `make -C host XRT=1 cft-resident`; four units at once on the quad |
| on the card: `device-test <xclbin> -b -n 4096` and `cft-bench <xclbin> --resident` (the library's resident path held to the staged one, then measured) | 1 s and 25 s an image | | since ABI 0.11; `-b` also runs on the software backend in the runner's `selfcheck` stage |
| `hw/run-device-test.sh` under hw_emu (xsim, the desktop's WSL, 2026-09-07/08) | link: one tile 4 min, four tiles 6 min | every kernel invocation 1 to 3 min whatever its element count | `-s -n 24` on four tiles **333 min** (98 checks); `-q -n 8` on one tile passed fp32's 50 checks in 221 min and was stopped; `-r` is days. Not an evening check until device-test has an emulation budget. Since 2026-09-18 the scratch leg's strict section adds two invocations a format, and the 32,769-lane program leg is skipped BY NAME when `XCL_EMULATION_MODE` is set |
| `formal` (30 proofs plus the negative control; the gate's own verdict line counts all 31 as tasks) | **7 min** on the merged tree with the box otherwise idle (420 s of solver time; 14 min in an earlier run beside other work) | the same gate ran for **more than two and a half hours** earlier that day and had to be stopped - not load, but an IMUL equivalence task that had been left in the list and does not close; parked, the gate was back to 7 min | the fp256 fold lemma alone is 2 to 4 min; the old four-proof gate was 29 s, which is the number older notes quote |
| `character` | 2.6 min | 5 min | |
| `transcend` | 12.6 min | **52 min** | the thirty-nine functions twice, the second pass through the escalation path |
| `bindings` (cftmpfr vs gmpy2) | 2.4 min | 8 min | |
| `cpp` (C++17 and C++20, each a full replay) | 25 min | not measured loaded | |
| `node` (unit tests + `conformance.mjs`) | 5 min + 17 min | | |
| `wasm` (`verify.mjs`, the page without a browser) | 11 min | 30 min | 1,068,915 cases through the page's bytes on `make vectors`' sets (about 1.2 million at the runner's generator counts), then 832,915 over 148 sets through the wrappers. The module must be REBUILT when an opcode is assigned, not merely revisioned: this lane replays the sets, so one predating opcode 31 failed 20 of 148 - all twenty reduce sets, each at its first `maxall` case |
| `mpfr` | 8 min | | |
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
`docs`, `generated`, `buildargs` and `sweepjudge` checks, the
model-versus-C stages, the GPU's photograph, the bindings, the language
legs, the soak spot check, the workloads, the demos and the remote
backend - about twenty minutes after a host build; `gate` adds the golden
suite, the vectors, the library replay, the transcendentals, MPFR, the
C++ replay, lint and formal - **about two hours quiet and four loaded on
this host**, most of it `cpp`, `transcend` and `formal`; `full` adds the
simulation suites (`sim`, `simmc`), node, wasm and the staged images,
which is the census. The runner writes a `.ok` per stage and `--resume`
reruns only what has none, so an interrupted run loses at most the stage
it was in. There is **no cache across runs**: a run id is a timestamp
plus the commit, so a fresh invocation re-runs everything and `--resume`
is the only thing that skips work. (cft-rebound is the sibling repo with
a content-addressed gate cache and a warm five-second check; this runner
does not have one.)

`bash verify/run.sh --list` prints all forty stages with a marker
against the ones the given `--budget` or `--only` would actually run, so
the list cannot imply a budget covers more than it does. The stage names
are derived from the `stage` calls themselves rather than kept in a second
list - they were kept by hand in three places once, and two of the copies
drifted.

The `docs` stage is the cheapest of them and exists for the same reason:
`docs/README.md` indexes the thirty-seven documents, and
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
fifth, `python/gen_divfull.py`, joined on 2026-09-14). **Nothing invoked
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
55-minute `sim` above was four jobs beside a Vivado.

## What each verdict line looks like

So that a log can be read without the harness:

- cocotb prints one `** TESTS=n PASS=n FAIL=0 SKIP=0` block per
  target; the runner's `sim` stage is green only when every target's
  results file says FAIL=0 and none is missing.
- the formal gate prints one `PASS  <sby> <task>` line per task and
  ends with `FORMAL GATE: PASS (n of n, negative control refuted)`; a
  task whose solved model carried fewer checks than the gate expects
  prints `VACUOUS` and fails.
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
