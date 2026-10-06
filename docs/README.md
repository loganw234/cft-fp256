# The documents, by what you open them for

Forty-two files, 72,017 lines. Flat in one directory they look like one
undifferentiated pile; they are not, and the split is close to even:

- **27,330 lines you consult while working** — the three under *Start here*,
  the contract, and the reference you call into;
- **6,675 lines of tool manual**, one per shipped program;
- **2,015 lines of operations**, read when you are about to do something to
  hardware;
- **35,997 lines of record and argument** — the ledger, the roadmap and the
  design studies. The history of how a decision was reached, worth keeping,
  and not what you open to get something done.

Half is therefore history. That is deliberate, and it is also why a
flat listing of forty-two names feels heavier than the work actually is.

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
| [VERIFICATION.md](VERIFICATION.md) | 578 | Every gate, what it proves, how long it really takes. Twelve tiers, fifty-one runner stages. |
| [COMPLIANCE.md](COMPLIANCE.md) | 172 | IEEE 754-2019 clause by clause: what is implemented, what is refused, and where each is proven. |

## The contract

What the project promises. Change one of these and you have changed the
product, not the implementation.

| document | lines | what it is for |
|---|---|---|
| [DETERMINISM.md](DETERMINISM.md) | 1,442 | The determinism contract itself — the argument the whole project rests on, including the unassigned-opcode hazard and every time it has fired. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 1,176 | The tile: register map, MODE and CAPS words, the rule for when VERSION moves. |
| [SEQUENCER.md](SEQUENCER.md) | 4,011 | The orbit sequencer and the program model. |
| [LANGUAGE.md](LANGUAGE.md) | 2,375 | The language for dynamical systems: the grammar, the semantics (literal evaluation, exact constants rounded once, one attribute a program), the integrators written in it, time (t in the state, a step counter, forcing by a rotation, each measured), the step graph, the reference interpreter that is the definition of correct for every compiled image, the intention-out, the variational equations (tangent vectors and the rule that differentiates each operation), and every refusal by name. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | 1,044 | One section per ABI step, with a per-surface table. Read before assuming a call exists on a given surface. |
| [LAYOUTS.md](LAYOUTS.md) | 191 | Every xclbin layout the U50 could carry - tile mixes and their clocks - derived by `hw/gen_layouts.py`, never typed. |
| [CERTIFICATES.md](CERTIFICATES.md) | 4,539 | The certificate, versions 1 and 2. Version 1: what a run was and how accurate it is, keyed or open, and the audit that re-runs its segments. Version 2: what the run means - each segment's per-lane flags, every lane a routine marked replayed by the program's definition, the source it was compiled from or is defined by and a wider-source run of it, the profile and language its bits are claimed under, provenance with its privacy defaults, and a detached Ed25519 signature for either version. Complete enough to write a reader and an auditor of either from the page. And the segment runner, `cft-segrun`, that writes either version from the library, version 2 by default, its accuracy entries included; the audit tool, `cft-audit`, that audits both versions in C - version 1 with the same exact arithmetic, and version 2 with Ed25519 and SHA-512 of its own, every step that needs no source; and the golden certificates in `certificates/` that hold the writers to committed bytes, version 2's cases and thirty controls among them. |

## Reference you call into

| document | lines | what it is for |
|---|---|---|
| [HOSTAPI.md](HOSTAPI.md) | 3,679 | The host API, function by function. The largest reference here and the one most often wanted. |
| [TRANSCENDENTALS.md](TRANSCENDENTALS.md) | 1,737 | The thirty-nine correctly-rounded transcendentals, by ABI phase, with the evidence for each. |
| [REMOTE.md](REMOTE.md) | 1,433 | The remote backend: a tile behind a socket, the frame protocol and the WebSocket path. |
| [PROGRAMS.md](PROGRAMS.md) | 640 | Programs as files: the assembler, the program library, the runner. |
| [EMBEDDED.md](EMBEDDED.md) | 709 | libcft on microcontrollers, and the profiles the embedded gate runs. |
| [PLATFORMS.md](PLATFORMS.md) | 2,928 | Which FPGA to buy, borrow or rent next, measured against the tile this project builds; every figure carries a source and every price the date it was seen. |
| [SCALING.md](SCALING.md) | 423 | What more tiles buy, and what they do not. |

## The tools, one document each

Each documents a shipped program under `host/tools/`, including the
exactness argument for what it computes. Open the one whose tool you are
running.

| document | lines | tool |
|---|---|---|
| [ZOOM.md](ZOOM.md) | 856 | `cft-zoom` — deep-zoom Mandelbrot reference orbits |
| [ORBITS.md](ORBITS.md) | 2,050 | `cft-orbits` — symplectic few-body integration, and its certified runs |
| [MERSENNE.md](MERSENNE.md) | 882 | `cft-mersenne` — Lucas-Lehmer |
| [ENCLOSE.md](ENCLOSE.md) | 845 | `cft-enclose` — directed-rounding interval enclosure |
| [COLLATZ.md](COLLATZ.md) | 648 | `cft-collatz` — Collatz trajectories |
| [DEMOS.md](DEMOS.md) | 763 | the same five workloads in one browser tab, on the conformance wasm module |
| [BENCHMARKS.md](BENCHMARKS.md) | 631 | what all of the above measure, in software and on the card |

## Operations — doing a thing to hardware

| document | lines | what it is for |
|---|---|---|
| [BITSTREAM-BUILDS.md](BITSTREAM-BUILDS.md) | 263 | Building a bitstream, and the five traps — three of which exit 0, and two that look like a design failure. `hw/build-pair.sh` is this document as an executable. |
| [CARDDAY.md](CARDDAY.md) | 972 | Card day: the runbook as it was actually run, the staged pairs, and the forensics kept when build trees are reclaimed. |
| [BRINGUP.md](BRINGUP.md) | 780 | Hardware bring-up, and the gates CI's green tick does not cover. |

## The record

Kept because the project's claim is that failures stay in the record. Not
reading material for a working session.

| document | lines | what it is for |
|---|---|---|
| [VALIDATION.md](VALIDATION.md) | 18,201 | The validation ledger, append-only. Every run, including the ones that failed and the mistakes that produced them. A figure here is a fact about the run on its date and is never edited to match a later one. |
| [ROADMAP.md](ROADMAP.md) | 5,778 | What is built, what is next, and what was decided against. |
| [ROUND2.md](ROUND2.md) | 1,082 | The plan for the gather, the scatter, the lane mask and the broadcast as one parcel round, with its outcome at the top: the seam the lead lands first, a brief per parcel, the verifiers, the ledger, the merge order. |
| [NOVEL.md](NOVEL.md) | 561 | Results for which no prior description was found, with the standard of evidence stated first. |
| [ATLAS.md](ATLAS.md) | 367 | The atlas-engine integration, assessed before any of it was done. |
| [FUNDING.md](FUNDING.md) | 44 | Funding landscape. |

## The design studies

Four rounds of "should we build it this way", with the measurements that
settled each, one of "how far would it stretch", one
reading of the open toolchain's router, one measurement of how well
a certificate's estimates indicate, one design written before its RTL,
for Logan to approve, and one design of the certificate's version 2.
History of reasoning,
not current reference — but the place to look before reopening one of these
questions.

| document | lines | question it settled |
|---|---|---|
| [studies/OPT-A-datapath.md](studies/OPT-A-datapath.md) | 919 | the arithmetic datapath |
| [studies/OPT-B-array.md](studies/OPT-B-array.md) | 1,018 | the array, the beat, and how many tiles a part holds |
| [studies/OPT-C-timing.md](studies/OPT-C-timing.md) | 1,151 | timing, and what the physical tools will and will not give |
| [studies/OPT-D-contract.md](studies/OPT-D-contract.md) | 1,061 | the contract and the system above the RTL |
| [studies/EXT-A-wide-ladder.md](studies/EXT-A-wide-ladder.md) | 1,146 | how far the ladder extends above binary256, what an MPFR-shaped tile is worth on an FPGA and on an ASIC, and what counting in MPFR cores leaves out; its instruments and their captured runs are in `studies/ext-a/` |
| [studies/TOOL-A-dense-router.md](studies/TOOL-A-dense-router.md) | 253 | why openXC7's router does not converge on the tile, what to change in it and in what order, and why a fork of it (loganw234/nextpnr-xilinx, `dense`) starts at the pinned 0.9.6 |
| [studies/ACC-A-estimates.md](studies/ACC-A-estimates.md) | 685 | how well a certificate's two estimates indicate the errors they estimate: step-halving against a converged reference, the scheme at h/2^k, and wider against check.py's 300-digit arm, on every ODE case of the golden corpus and as h shrinks; the time shift the bank's rounded h/6 puts in the result, which neither estimate sees; its instrument is `programs/estimates.py`, and its captured runs are in `studies/acc-a/` |
| [studies/R8S-streaming.md](studies/R8S-streaming.md) | 1,368 | the design of revision 8's instruction streaming, approved with revision 8's RTL plan on 2026-10-02: the fetch through the A master during a block, a 4,096-word store with a prefetched stream past it, loops replayed from the store, what a late fetch costs a step on the hard workloads, the block RAM it frees and the timing path it shortens, the CAPS2 field for the capacity, the deep build beside it, the verification, and the RTL plan's outline; and, since 2026-10-03, the fetch unit as built (rtl/cft_ifetch.sv, alone): the interface round 2 wires, where it departs from the design, its proof at two sizes, its bench, S8's nine plants and verifier-VRD1's tenth |
| [studies/CERT-V2.md](studies/CERT-V2.md) | 2,363 | a design for certificate format version 2, approved by Logan on 2026-10-02 and built golden-first the same day (CERTIFICATES.md, "Version 2"; its C half next): the per-lane flags, a marked lane replayed by the golden model and checked against it under the definition the certificate names, a wider run compiled from the named source (measured to see the constants' rounding that version 1's wider run cannot), and the scientific provenance surveyed from ISO/IEC 17025, W3C PROV, SLSA, RO-Crate and reproducibility certificates, field by field: carried or not, checked or reported, and its cost in privacy |

---

Three more live outside `docs/`: [../CONFORMANCE.md](../CONFORMANCE.md) is
the contract as a profile an independent implementation is scored against,
[../CAPABILITIES.md](../CAPABILITIES.md) is what a given build can do, and
[../CLAUDE.md](../CLAUDE.md) is the short list of things that have already
cost hours.
