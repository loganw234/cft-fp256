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
   sets, 1,071,635 cases, every format under every rounding attribute,
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
4. **The RTL, in simulation** (`tb/`, `make sim` in the `cft-sim`
   image). Twenty-one cocotb targets hold the hardware to the model:
   the four rung benches replay 111,278 published vectors through
   `cft_fpfma_pipe` bit for bit, flags included; the kernel is driven
   through its CSR and AXI interfaces, by the streaming engine and by
   the sequencer; the shared normalise and alignment ladders are held
   against the private shifters they replaced; the reduction
   accumulator, the fault paths, the quarter-tile trim and the seed
   opcodes have benches of their own. `make simmc MC=10` runs the same
   suite with the multiplier iterated ten ways, plus the `board`
   configuration (ten passes and both ladders on) that the open-core
   Kintex-7 tile would ship as - thirteen multi-cycle targets and four
   board targets, the third tier's own census.
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
   diffed against the C example's bits.
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
**skipped by name with the reason**, never silently passed; a negative
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
| `golden` (pytest, 2,075 tests since the assembler's 49 joined on 2026-09-08) | 4 to 7 min at four workers; 6.6 serial | 8 to 13 min | |
| `vectors` (`make vectors`, 168 sets) | 5 min | 7 to 8.5 min | |
| `libcft` / `make -C host test` (build + the 1,071,635-case replay) | 7.5 min | 8.5 to 11 min | |
| `sim` (21 cocotb targets, `cft-sim` image) | 10 min at the runner's job count; about 40 min serial | **55 min at four jobs** | 3 min at twelve jobs on a 36-core box; almost all compilation |
| `simmc MC=10` (13 multi-cycle + 4 board targets) | not measured quiet | about 50 min at four jobs for sixteen of the seventeen | the seventeenth, the engine-driven board kernel, **does not finish under Icarus** in this configuration: 2.5 ns of simulated time a second through the small operations and about 0.03 ns a second inside the 1,104-element stream, 57 of 71 operations after four hours, on the tree before the cone change and after it alike; under Verilator, which its target selects, the bench is **16 s of simulation after an eleven-minute compile** (44,920 ns, both tests, parameters applied - until the evening of 2026-09-07 a Verilator build received none of a target's parameters and simulated the default, docs/VALIDATION.md) |
| `lint` (Yosys, every RTL file) | 1 min | 1.5 to 2 min | |
| `make programs-check` (the .cfta library: both assemblers, twelve images, a check each, a generated revision-2 corpus) | 5 to 20 s | | not a runner stage yet; `make programs` rebuilds the manifest it checks, so the two are separate on purpose |
| `hw/run-device-test.sh` under hw_emu (xsim, the desktop's WSL, 2026-09-07/08) | link: one tile 4 min, four tiles 6 min | every kernel invocation 1 to 3 min whatever its element count | `-s -n 24` on four tiles **333 min** (98 checks); `-q -n 8` on one tile passed fp32's 50 checks in 221 min and was stopped; `-r` is days. Not an evening check until device-test has an emulation budget |
| `formal` (31 tasks + the negative control) | **7 min** on the merged tree with the box otherwise idle (420 s of solver time; 14 min in an earlier run beside other work) | the same gate ran for **more than two and a half hours** earlier that day and had to be stopped - not load, but an IMUL equivalence task that had been left in the list and does not close; parked, the gate was back to 7 min | the fp256 fold lemma alone is 2 to 4 min; the old four-proof gate was 29 s, which is the number older notes quote |
| `character` | 2.6 min | 5 min | |
| `transcend` | 12.6 min | **52 min** | the thirty-nine functions twice, the second pass through the escalation path |
| `bindings` (cftmpfr vs gmpy2) | 2.4 min | 8 min | |
| `cpp` (C++17 and C++20, each a full replay) | 25 min | not measured loaded | |
| `node` (unit tests + `conformance.mjs`) | 5 min + 17 min | | |
| `wasm` (`verify.mjs`, the page without a browser) | 11 min | 30 min | 1,071,635 cases, then 831,635 through the wrappers |
| `mpfr` | 8 min | | |
| `soak-quick` | 1.6 min | | |
| the workload checks (`collatztest` ... `zoomtest`) | 1 to 3 min each | 1 to 3 min each | |
| `remote` (`make -C host remotetest`) | | 10 to 12 min | the bounded replay is most of it |
| `wstest` | | 2 min | |
| the fuzz lane (`make -C host fuzz-run`) | 30 min per target by design | | `FUZZ_SECONDS`; the sanitizers need the `cft-sim` image, MSYS gcc has none |
| a wasm module rebuild (`bindings/wasm/build.sh`) | 5 min | | in the pinned emscripten image |
| OOC synthesis, one kernel (`hw/mc_sweep.sh ... synth`) | 10 to 32 min | | U50 647 to 1,905 s; K325T 626 to 1,272 s; A200T and Z020 6 to 12 min |
| OOC implementation, one kernel (`... impl`) | 24 min to 1 h 46 | | K325T 1,429 to 2,608 s including its synthesis; U50 2,591 s quiet, 6,351 s under load |
| a shell link, one tile | about 1 h 50 | | 12 GB |
| a shell link, four tiles | 3 to 4 h | | 25 to 30 GB of the build box's 46; one at a time or the placer is killed and it looks like a design failure |

The budgets in `verify/run.sh` are cuts of that table: `quick` is the
model-versus-C stages, the bindings, the language legs, the soak spot
check, the workloads, the demos and the remote backend - about twenty
minutes after a host build; `gate` adds the golden suite, the vectors,
the library replay, the transcendentals, MPFR, the C++ replay, lint and
formal - **about two hours quiet and four loaded on this host**, most
of it `cpp`, `transcend` and `formal`; `full` adds the simulation
suite, node, wasm and the staged images, which is the census. The
runner writes a `.ok` per stage and `--resume` reruns only what has
none, so an interrupted run loses at most the stage it was in.

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
- the library replay prints `168 sets, 1071635 cases, all matching`
  and `api-test: all contract checks passed`; the remote gate ends with
  `remote_check: every check passed`; each workload check ends with its
  `... CHECK OK` line and a comparison count; `verify.mjs` ends with
  the case count and `library matches the vectors exactly`;
  `verify_demos.mjs` with `VERDICT: the browser's compute core produced
  the C tools' chains`.
- the runner ends with a census block shaped for docs/VALIDATION.md,
  listing every stage as PASS, FAIL or SKIP with the skip's reason.

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
