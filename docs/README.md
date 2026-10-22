# The documents, by what you open them for

Fifty files, 87,543 lines. Flat in one directory they look like one
undifferentiated pile; they are not, and the split is close to even:

- **28,186 lines you consult while working** — the three under *Start here*,
  the contract, and the reference you call into;
- **7,894 lines of tool manual**, one per shipped program;
- **3,426 lines of operations**, read when you are about to do something to
  hardware;
- **48,037 lines of record and argument** — the ledger, the roadmap and the
  design studies. The history of how a decision was reached, worth keeping,
  and not what you open to get something done.

Half is therefore history. That is deliberate, and it is also why a
flat listing of fifty names feels heavier than the work actually is.

This index exists because the README linked eight of the thirty-four there
were and nothing linked the other twenty-six. Nothing has moved: a file's
path is part of its identity here, quoted from source comments, commit
messages and the ledger, and relocating thirty files to tidy a directory
listing would break those references to solve a problem an index solves for
free.

**If you changed something and want to know whether it still holds**, the
answer is not in here — it is `make verify-quick`, and
[VERIFICATION.md](VERIFICATION.md) is the map of what each stage proves.

---

## Start here

| document | lines | what it is for |
|---|---|---|
| [INTEGRATION.md](INTEGRATION.md) | 253 | Choosing a path: which surface to use for which job. The shortest route from "I have a workload" to "I know what to call." |
| [VERIFICATION.md](VERIFICATION.md) | 640 | Every gate, what it proves, how long it really takes. Twelve tiers, fifty-three runner stages. |
| [COMPLIANCE.md](COMPLIANCE.md) | 172 | IEEE 754-2019 clause by clause: what is implemented, what is refused, and where each is proven. |

## The contract

What the project promises. Change one of these and you have changed the
product, not the implementation.

| document | lines | what it is for |
|---|---|---|
| [DETERMINISM.md](DETERMINISM.md) | 1,462 | The determinism contract itself — the argument the whole project rests on, including the unassigned-opcode hazard and every time it has fired. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 1,187 | The tile: register map, MODE and CAPS words, the rule for when VERSION moves. |
| [SEQUENCER.md](SEQUENCER.md) | 4,055 | The orbit sequencer and the program model. |
| [LANGUAGE.md](LANGUAGE.md) | 2,767 | The language for dynamical systems: the grammar, the semantics (literal evaluation, exact constants rounded once, one attribute a program), the integrators written in it, time (t in the state, a step counter, forcing by a rotation, each measured), the step graph, the reference interpreter that is the definition of correct for every compiled image, the intention-out, the variational equations (tangent vectors and the rule that differentiates each operation), the math library's exp, expm1, exp2, log, log1p and log2 since the language's 1.1, and every refusal by name. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | 1,075 | One section per ABI step, with a per-surface table. Read before assuming a call exists on a given surface. |
| [LAYOUTS.md](LAYOUTS.md) | 193 | Every xclbin layout the U50 could carry - tile mixes and their clocks - derived by `hw/gen_layouts.py`, never typed. |
| [CERTIFICATES.md](CERTIFICATES.md) | 4,650 | The certificate, versions 1 and 2. Version 1: what a run was and how accurate it is, keyed or open, and the audit that re-runs its segments. Version 2: what the run means - each segment's per-lane flags, every lane a routine marked replayed by the program's definition, the source it was compiled from or is defined by and a wider-source run of it, the profile and language its bits are claimed under, provenance with its privacy defaults, and a detached Ed25519 signature for either version. Complete enough to write a reader and an auditor of either from the page. And the segment runner, `cft-segrun`, that writes either version from the library, version 2 by default, its accuracy entries included; the audit tool, `cft-audit`, that audits both versions in C - version 1 with the same exact arithmetic, and version 2 with Ed25519 and SHA-512 of its own, every step that needs no source; and the golden certificates in `certificates/` that hold the writers to committed bytes, version 2's cases and thirty controls among them. |

## Reference you call into

| document | lines | what it is for |
|---|---|---|
| [HOSTAPI.md](HOSTAPI.md) | 3,774 | The host API, function by function. The largest reference here and the one most often wanted. |
| [TRANSCENDENTALS.md](TRANSCENDENTALS.md) | 1,811 | The thirty-nine correctly-rounded transcendentals, by ABI phase, with the evidence for each, and the six of them that also run on the tile. |
| [REMOTE.md](REMOTE.md) | 1,433 | The remote backend: a tile behind a socket, the frame protocol and the WebSocket path. |
| [PROGRAMS.md](PROGRAMS.md) | 653 | Programs as files: the assembler, the program library, the runner. |
| [EMBEDDED.md](EMBEDDED.md) | 709 | libcft on microcontrollers, and the profiles the embedded gate runs. |
| [PLATFORMS.md](PLATFORMS.md) | 2,928 | Which FPGA to buy, borrow or rent next, measured against the tile this project builds; every figure carries a source and every price the date it was seen. |
| [SCALING.md](SCALING.md) | 424 | What more tiles buy, and what they do not. |

## The tools, one document each

Each documents a shipped program under `host/tools/` (and, in EXPORT.md,
`python/project_packager.py`, and in SWEEP-RECORDS.md `hw/sweep_record.py`),
including the exactness argument for what it computes. Open the one whose
tool you are running.

| document | lines | tool |
|---|---|---|
| [ZOOM.md](ZOOM.md) | 856 | `cft-zoom` — deep-zoom Mandelbrot reference orbits |
| [ORBITS.md](ORBITS.md) | 2,070 | `cft-orbits` — symplectic few-body integration, and its certified runs |
| [MERSENNE.md](MERSENNE.md) | 882 | `cft-mersenne` — Lucas-Lehmer |
| [ENCLOSE.md](ENCLOSE.md) | 845 | `cft-enclose` — directed-rounding interval enclosure |
| [COLLATZ.md](COLLATZ.md) | 648 | `cft-collatz` — Collatz trajectories |
| [DEMOS.md](DEMOS.md) | 763 | the same five workloads in one browser tab, on the conformance wasm module |
| [BENCHMARKS.md](BENCHMARKS.md) | 631 | what all of the above measure, in software and on the card |
| [EXPORT.md](EXPORT.md) | 380 | `python/project_packager.py` — the dated status archive: every figure as SVG and PNG with its sidecar and caption, a status document made by script, the light documents, and a manifest of where each file came from; how to make one, check one, and what it refuses |
| [SWEEP-RECORDS.md](SWEEP-RECORDS.md) | 630 | `hw/sweep_record.py` — the card stress run's finished sweep slices as signed records: export, sign and verify; the record's version 1 field by field and what the run does not let it carry (no RTL tree hash, no digest), version 2 (the host pool's slices: a host build for the subject, the version rule and why version 1 stays as it was, what a host record does not say of its machine), the campaign record and the driver's own counting rule held to it, the device pseudonym, the signing domain a certificate's signature cannot pass, the key (made with `cft_sign.py`, kept outside every repository, refused inside one), every refusal by name, a finding told from coverage, what a signature proves and what it does not, and what the driver calls and what it costs |
| [EXTERNAL-GENERATORS.md](EXTERNAL-GENERATORS.md) | 189 | `host/tools/tf_subject.c` and the drivers beside it: Berkeley TestFloat 3e (with SoftFloat 3e), UCBTEST and IBM's FPgen vectors put to work against libcft, none of them in the repository - the licences as their files state them, how to fetch, build and run each, what each covered, every disagreement classified (the fused multiply-add of 0 x infinity and a quiet NaN; IBM's tininess before rounding), and which oracle judged what |

## Operations — doing a thing to hardware

| document | lines | what it is for |
|---|---|---|
| [BITSTREAM-BUILDS.md](BITSTREAM-BUILDS.md) | 357 | Building a bitstream, and the five traps — three of which exit 0, and two that look like a design failure. `hw/build-pair.sh` is this document as an executable. |
| [CARDDAY.md](CARDDAY.md) | 2,282 | Card day: the runbook as it was actually run, the staged pairs, the long run (`hw/card-stress.sh`: how to start, stop and read it), and the forensics kept when build trees are reclaimed. |
| [BRINGUP.md](BRINGUP.md) | 787 | Hardware bring-up, and the gates CI's green tick does not cover. |

## The record

Kept because the project's claim is that failures stay in the record. Not
reading material for a working session.

| document | lines | what it is for |
|---|---|---|
| [VALIDATION.md](VALIDATION.md) | 23,532 | The validation ledger, append-only. Every run, including the ones that failed and the mistakes that produced them. A figure here is a fact about the run on its date and is never edited to match a later one. |
| [FIGURES.md](FIGURES.md) | 474 | Fifteen figures of the project - its history, its gate, the card's clocks and its long stress run, the benchmarks, the math library's costs - drawn by script from the record's own data, light and dark, each with a sidecar of its numbers and the digests of its sources, and held to the numbers the README and other documents state. The page is written by `python/project_figures.py`, the `generated` stage's seventh generator, not by hand. |
| [ROADMAP.md](ROADMAP.md) | 6,578 | What is built, what is next, and what was decided against. |
| [ROUND2.md](ROUND2.md) | 1,082 | The plan for the gather, the scatter, the lane mask and the broadcast as one parcel round, with its outcome at the top: the seam the lead lands first, a brief per parcel, the verifiers, the ledger, the merge order. |
| [NOVEL.md](NOVEL.md) | 561 | Results for which no prior description was found, with the standard of evidence stated first. |
| [ATLAS.md](ATLAS.md) | 367 | The atlas-engine integration, assessed before any of it was done. |
| [FUNDING.md](FUNDING.md) | 44 | Funding landscape. |

## The design studies

Four rounds of "should we build it this way", with the measurements that
settled each, one of "how far would it stretch", one
reading of the open toolchain's router, one measurement of how well
a certificate's estimates indicate, one design written before its RTL,
for Logan to approve, one design of the certificate's version 2,
two designs of correctly rounded routines, exp and log, and sin,
cos and tan, each written before any of it is built, and one study of how the card's soak
sweeps could reach the cases a sampler does not, add up from weekend to weekend, and one day add
up across devices, and one design of a card scheduler. History of reasoning,
not current reference — but the place to look before reopening one of these
questions.

| document | lines | question it settled |
|---|---|---|
| [studies/OPT-A-datapath.md](studies/OPT-A-datapath.md) | 926 | the arithmetic datapath |
| [studies/OPT-B-array.md](studies/OPT-B-array.md) | 1,029 | the array, the beat, and how many tiles a part holds |
| [studies/OPT-C-timing.md](studies/OPT-C-timing.md) | 1,155 | timing, and what the physical tools will and will not give |
| [studies/OPT-D-contract.md](studies/OPT-D-contract.md) | 1,061 | the contract and the system above the RTL |
| [studies/EXT-A-wide-ladder.md](studies/EXT-A-wide-ladder.md) | 1,146 | how far the ladder extends above binary256, what an MPFR-shaped tile is worth on an FPGA and on an ASIC, and what counting in MPFR cores leaves out; its instruments and their captured runs are in `studies/ext-a/` |
| [studies/TOOL-A-dense-router.md](studies/TOOL-A-dense-router.md) | 253 | why openXC7's router does not converge on the tile, what to change in it and in what order, and why a fork of it (loganw234/nextpnr-xilinx, `dense`) starts at the pinned 0.9.6 |
| [studies/ACC-A-estimates.md](studies/ACC-A-estimates.md) | 685 | how well a certificate's two estimates indicate the errors they estimate: step-halving against a converged reference, the scheme at h/2^k, and wider against check.py's 300-digit arm, on every ODE case of the golden corpus and as h shrinks; the time shift the bank's rounded h/6 puts in the result, which neither estimate sees; its instrument is `programs/estimates.py`, and its captured runs are in `studies/acc-a/` |
| [studies/R8S-streaming.md](studies/R8S-streaming.md) | 1,369 | the design of revision 8's instruction streaming, approved with revision 8's RTL plan on 2026-10-02: the fetch through the A master during a block, a 4,096-word store with a prefetched stream past it, loops replayed from the store, what a late fetch costs a step on the hard workloads, the block RAM it frees and the timing path it shortens, the CAPS2 field for the capacity, the deep build beside it, the verification, and the RTL plan's outline; and, since 2026-10-03, the fetch unit as built (rtl/cft_ifetch.sv, alone): the interface round 2 wires, where it departs from the design, its proof at two sizes, its bench, S8's nine plants and verifier-VRD1's tenth |
| [studies/CERT-V2.md](studies/CERT-V2.md) | 2,363 | a design for certificate format version 2, approved by Logan on 2026-10-02 and built golden-first the same day (CERTIFICATES.md, "Version 2"; its C half built at ABI 0.18 on 2026-10-02 to 03): the per-lane flags, a marked lane replayed by the golden model and checked against it under the definition the certificate names, a wider run compiled from the named source (measured to see the constants' rounding that version 1's wider run cannot), and the scientific provenance surveyed from ISO/IEC 17025, W3C PROV, SLSA, RO-Crate and reproducibility certificates, field by field: carried or not, checked or reported, and its cost in privacy |
| [studies/M1-exp-log.md](studies/M1-exp-log.md) | 1,917 | a design for the correctly rounded exp, expm1, exp2, log, log1p and log2 as tile routines, step 6's M1 written before any of it was built (it has been since, 2026-10-13 to 2026-10-19, and the study carries dated notes): the reductions, an eight-entry table read by a SELECT tree, a polynomial with a double-word head and a single-word tail and no augadd, one rounding under the program's attribute, the in-lane test that marks an undecided lane, the bound written out and measured against mpmath, the mark rate's law, the specials and flags as transcend.py gives them, the cost against the surveyor's estimates and fp32's triple words, the language's nodes, refusals and derivative rules, and how phase 2 is to be held; revised the same day after verifier-VM1 found log1p's r = x path past the bound's rho, with fp64's margins stated by an error budget (thin in log1p's band and log2's cell at G = 46) and G = 44 proposed for fp64; verifier-VM1b's budget tool is committed in `studies/m1/vm1b/`; its model and captured runs are in `studies/m1/` |
| [studies/M2-trig.md](studies/M2-trig.md) | 1,560 | a design for the correctly rounded sin, cos and tan as tile routines, the math library round's M2 before any of it is built: one Payne-Hanek reduction for every lane, against 2/pi in bank words picked from the exponent by a SELECT shifter and carried exactly through the cancellation, with an audit of every instruction it calls exact; fp64's whole range and fp128's and fp256's to 2^1024, the range's cost measured; Taylor heads in double words, tan by its own quotient, and the clamp |sin x|, |cos x| < 1; the bound by verifier-VM1b's budget ported, the mark rate's law lane by lane, the structured families and their windows, the specials and flags as transcend.py gives them; the cost (sin 406, 382 and 389 instructions at fp64, fp128 and fp256, sin and cos of one argument 434, 411 and 418), fp32's double word at G = 18 and the triple word's estimate; the language's nodes, refusals and derivative rules, fourteen plants, and twelve questions for Logan; its model and captured runs are in `studies/m2/`, and its larger samples are handed to the lead (`studies/m2/box_m2s.sh`) |
| [studies/SWP-A-coverage.md](studies/SWP-A-coverage.md) | 959 | how the card's native-oracle soaks could cover more of what they sample, written after the 60-hour stress run of 2026-10-16 to 19: the lead's seed finding confirmed on the driver itself and refined (a rerun repeats at least about 96% of the random draws; both tools force the seed's low bit, so 96.2% of the run's random slices started from a state another item's slice also started from), which of the 68 sweep items use the tile (35) and which are libcft host code (33, and 52.5% of the sweep's job-seconds), a survey with what each method would find here and cost (FPgen's coverage models, TestFloat, IeeeCC754 and UCBTEST, hard cases and the Table Maker's Dilemma, reductions by symmetry, stratified sampling, enumeration by keyed permutation, BOINC-style verification, formal methods), the closest-approach cases of division and square root constructed and measured, the reductions proved on tiny formats and what they leave (fp32 division 22 quad-years instead of 3 x 10^5), a design for a store of immutable coverage records that merges across weekends and devices, device-years and rate bounds for every space, what a contributed result must carry to be trusted, a ranked plan and ten questions for Logan; its nineteen scripts and their captured runs are in `studies/swp-a/` |
| [studies/SCHED-A-card-scheduler.md](studies/SCHED-A-card-scheduler.md) | 976 | a design for one scheduler per machine that owns the card's time, written before any of it is built, at Logan's word of 2026-10-21 (the nightly window of 18:00 to 08:00 on whatever the sweep has not reached, staged program runs, metrics on the card and its performance, the lead's box scripts replaced, several cards later): what exists, checked (the stress driver and what it does not do, among them that its guard is not a lock; the lead's seventeen box scripts, whose guards are written nine ways and whose `pgrep` pattern misses four card users the driver names; the card, the box and the remote backend; what reads the driver's output; the part of the sweep study's coverage ledger a nightly needs, and that the nightly's resume is blind to trees in its planner), the data volumes (a night's record is 1.6 to 1.8 MB), what a preemption costs (3.5 minutes on average to a safe point, 8.7 at the 95th percentile), the requirements, the options for architecture, jobs, code, cards, coverage, the metrics store, the interface, deployment and failure, a recommended first version (a scheduler around the unchanged driver, launched by the lead, a file queue, refusals by name), a build plan in parcels with their plants, and thirteen questions for Logan; its five scripts and their captured runs are in `studies/sched-a/` |

---

Three more live outside `docs/`: [../CONFORMANCE.md](../CONFORMANCE.md) is
the contract as a profile an independent implementation is scored against,
[../CAPABILITIES.md](../CAPABILITIES.md) is what a given build can do, and
[../CLAUDE.md](../CLAUDE.md) is the short list of things that have already
cost hours.
