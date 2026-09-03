# verify/ - the standardized verification run

One command that exercises every gate this project has accumulated,
with per-stage logs, resumability, honest skip reporting, and a
census block for docs/VALIDATION.md at the end. `make verify` from
the repo root, or `bash verify/run.sh` with the flags below.

    bash verify/run.sh                # the standard set, in order
    bash verify/run.sh --list         # stage names and descriptions
    bash verify/run.sh --skip formal,soak-quick
    bash verify/run.sh --only golden,sim
    bash verify/run.sh --resume       # continue the most recent run
    bash verify/run.sh --fresh        # force a new run id
    bash verify/run.sh --require-all  # skips become failures
    SIM_JOBS=12 bash verify/run.sh    # the sim stage's targets, twelve at a time
    bash verify/run.sh --only cpp,node,wasm,lang-rust   # language legs, by name

## The stages

| stage | what it proves | needs |
|---|---|---|
| golden | the model's own invariants and oracles | python |
| vectors | the conformance sets regenerate from the model | python |
| sim | RTL == model across all cocotb targets | docker (usable, not merely present) |
| lint | every RTL file elaborates in Yosys, no latches | docker |
| formal | the FIFO/seedop/simpleops theorems + negative control | docker |
| libcft | C library contract + 392k-case conformance replay; cleans host/ first | cc, python |
| selfcheck | device-test harness can detect, full sw matrix | cc |
| divsqrt | composed div/sqrt + seeds vs model, per-element flags | cc, python |
| clause5 | the clause-5 completion set vs model | cc, python |
| diff | the alignment-boundary sweep vs the model | cc, python |
| seq | sequencer C-vs-model over fuzzed programs | cc, python |
| reduce | canonical reduction ranges vs the model | cc, python |
| bindings | the cftmpfr drop-in vs gmpy2's IEEE emulation | cc, python |
| cpp | `cft.hpp` vs `cft.h` at C++17 and C++20: every entry point, same bits and flags, plus the conformance replay through the wrapper | cc, g++ |
| lang-cpp, lang-rust, lang-julia, lang-go, lang-csharp, lang-r | that language's example vs the C example, same bits (`make -C host examples-lang`, one leg at a time) | cc + that toolchain |
| lang-fortran | the Fortran example builds and runs through iso_c_binding; it prints no checksum line | cc, gfortran |
| node | the Node binding: its unit tests, then the vectors through `cft_node.wasm` | node |
| wasm | the committed conformance page, verified without a browser | node |
| mpfr | GNU MPFR parity, every rung and mode (third oracle) | cc, python |
| soak-quick | native-oracle spot check + the sabotage control | cc |
| images | staged xclbins match their manifests (IMAGES=...) | xclbinutil |

The `cpp`, `lang-*`, `node` and `wasm` stages are the regression
harness for the languages: one named stage per binding or example,
SKIPped by name where the toolchain is absent and FAILed where the
bits differ, so a change to the library or to a binding says which
language it broke. `.github/workflows/gates.yml`'s `host` job runs
them on every push (ubuntu, `--require-all`, everything but Julia
and R); a full census runs them wherever the toolchains are, and
docs/COMPATIBILITY.md keeps the dated per-language rows.

Wall time for the standard set is dominated by `sim` when it runs
serially: ~40 min in the container, ~25 min under Verilator on a
36-core box, almost all of it compilation. The targets are
parallel-safe by construction - each writes its own sim_build/<name>
and results file - so `SIM_JOBS=n` hands make `-j n` (and `-k`, so
one failing target does not hide the others): the whole suite cold
at -j12 on that box is 3 min, warm under a minute (docs/VALIDATION.md
2026-09-02). Budget 1-2 GB a job under Verilator. Everything else
together is ~20-30 min.

Two things the runner learned on 2026-09-02, both now built in: the
libcft stage cleans `host/` before building it, because a checkout
shared between Windows and WSL can hold the other platform's objects
and the link errors that produces look like source defects; and
`need docker` asks whether docker works, because a WSL distro without
Docker Desktop's integration has a shim on PATH that only prints how
to enable it. A stage that cannot run is skipped by name, never
failed by accident.

## Resume semantics

Each run gets an id (timestamp to the second + commit, bumped on
collision) under `verify/state/`, and each stage leaves a
`.ok`/`.fail` marker beside its log. Interrupt anywhere; `--resume`
reruns only what lacks a `.ok`, and a stage that already passed stays
passed - `--skip` cannot re-verdict green work. Resuming across
COMMITS is refused: a report stitched from two trees certifies
nothing. `--fresh` starts over on purpose and contradicts `--resume`
loudly. Flags are PER-INVOCATION: a resume does not remember the
original run's `--only`/`--skip`, so restate them. `report.jsonl` is
an append-only event log across invocations of one run (resumes add
rows, including `ok-cached` entries); the census line counts executed
vs cached explicitly so a resumed report cannot pass as a full run.
Stage names in `--only`/`--skip` are validated against the known list
- a typo is a refusal, not a silent empty PASS.

## Skips are named, never silent

A stage whose tools are missing on this host reports SKIP with the
reason and the run can still PASS - a laptop without XRT is allowed
to verify everything else. `--require-all` inverts that for machines
that claim to be full verification hosts: there, a skip is a failure.
This is the knob a future open-core compliance run should set.

## What is deliberately not here

The multi-hour campaigns: the full native-oracle soak
(hw/run-soak.sh without QUICK), the RTL deep soak, hw_emu and on-card
device-test runs. They are machine- and schedule-bound, keep their
own drivers, and earn their own entries in docs/VALIDATION.md. This
runner is the recurring floor, not the ceiling.

## Bootstrapping the MPFR oracle

The `mpfr` stage needs libmpfr/libgmp. Package managers are the easy
route (mingw64 carries them as gcc dependencies; Debian wants
libmpfr-dev) - but a bench box often has neither packages nor sudo,
which is exactly where the third oracle was needed on 2026-09-01. So:

    bash verify/build-mpfr-oracle.sh

builds m4 (only if missing), GMP 6.3.0 and MPFR 4.2.2 from pinned,
SHA-256-verified GNU sources into `verify/_mpfr-prefix` (gitignored),
running the upstream test suites on the way (`CHECK=0` skips them).
Static libraries, no root, nothing outside the prefix. The `mpfr`
stage prefers this prefix over system packages when it exists,
because a version-pinned oracle is the same oracle on every host.

## The census

The report ends with a block shaped for docs/VALIDATION.md. Paste it
(or summarize a failure honestly) - the ledger is append-only and the
run id links back to the full per-stage logs under `verify/state/`.
