# The documents, by what you open them for

Thirty-four files, 40,870 lines. Flat in one directory they look like one
undifferentiated pile; they are not, and the split is close to even:

- **15,140 lines you consult while working** — the three under *Start here*,
  the contract, and the reference you call into;
- **5,317 lines of tool manual**, one per shipped program;
- **1,499 lines of operations**, read when you are about to do something to
  hardware;
- **18,914 lines of record and argument** — the ledger, the roadmap and the
  design studies. The history of how a decision was reached, worth keeping,
  and not what you open to get something done.

Nearly half is therefore history. That is deliberate, and it is also why a
flat listing of thirty-four names feels heavier than the work actually is.

This index exists because the README links eight of these and nothing linked
the other twenty-six. Nothing has moved: a file's path is part of its
identity here, quoted from source comments, commit messages and the ledger,
and relocating thirty files to tidy a directory listing would break those
references to solve a problem an index solves for free.

**If you changed something and want to know whether it still holds**, the
answer is not in here — it is `make verify-quick`, and
[VERIFICATION.md](VERIFICATION.md) is the map of what each stage proves.

---

## Start here

| document | lines | what it is for |
|---|---|---|
| [INTEGRATION.md](INTEGRATION.md) | 241 | Choosing a path: which surface to use for which job. The shortest route from "I have a workload" to "I know what to call." |
| [VERIFICATION.md](VERIFICATION.md) | 270 | Every gate, what it proves, how long it really takes. Twelve tiers, thirty-seven runner stages. |
| [COMPLIANCE.md](COMPLIANCE.md) | 172 | IEEE 754-2019 clause by clause: what is implemented, what is refused, and where each is proven. |

## The contract

What the project promises. Change one of these and you have changed the
product, not the implementation.

| document | lines | what it is for |
|---|---|---|
| [DETERMINISM.md](DETERMINISM.md) | 1,424 | The determinism contract itself — the argument the whole project rests on, including the unassigned-opcode hazard and every time it has fired. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 1,114 | The tile: register map, MODE and CAPS words, the rule for when VERSION moves. |
| [SEQUENCER.md](SEQUENCER.md) | 1,408 | The orbit sequencer and the program model. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | 646 | One section per ABI step, with a per-surface table. Read before assuming a call exists on a given surface. |
| [LAYOUTS.md](LAYOUTS.md) | 176 | How values sit in memory: beats, lanes, element order. |

## Reference you call into

| document | lines | what it is for |
|---|---|---|
| [HOSTAPI.md](HOSTAPI.md) | 2,259 | The host API, function by function. The largest reference here and the one most often wanted. |
| [TRANSCENDENTALS.md](TRANSCENDENTALS.md) | 1,667 | The thirty-nine correctly-rounded transcendentals, by ABI phase, with the evidence for each. |
| [REMOTE.md](REMOTE.md) | 1,353 | The remote backend: a tile behind a socket, the frame protocol and the WebSocket path. |
| [PROGRAMS.md](PROGRAMS.md) | 472 | Programs as files: the assembler, the program library, the runner. |
| [EMBEDDED.md](EMBEDDED.md) | 675 | libcft on microcontrollers, and the profiles the embedded gate runs. |
| [PLATFORMS.md](PLATFORMS.md) | 2,879 | Every platform the library has been built and run on, with dates and results. |
| [SCALING.md](SCALING.md) | 384 | What more tiles buy, and what they do not. |

## The tools, one document each

Each documents a shipped program under `host/tools/`, including the
exactness argument for what it computes. Open the one whose tool you are
running.

| document | lines | tool |
|---|---|---|
| [ZOOM.md](ZOOM.md) | 845 | `cft-zoom` — deep-zoom Mandelbrot reference orbits |
| [ORBITS.md](ORBITS.md) | 954 | `cft-orbits` — symplectic few-body integration |
| [MERSENNE.md](MERSENNE.md) | 876 | `cft-mersenne` — Lucas-Lehmer |
| [ENCLOSE.md](ENCLOSE.md) | 844 | `cft-enclose` — directed-rounding interval enclosure |
| [COLLATZ.md](COLLATZ.md) | 647 | `cft-collatz` — Collatz trajectories |
| [DEMOS.md](DEMOS.md) | 744 | the same five workloads in one browser tab, on the conformance wasm module |
| [BENCHMARKS.md](BENCHMARKS.md) | 407 | what all of the above measure, in software and on the card |

## Operations — doing a thing to hardware

| document | lines | what it is for |
|---|---|---|
| [BITSTREAM-BUILDS.md](BITSTREAM-BUILDS.md) | 176 | Building a bitstream, and the four traps — three of which exit 0. `hw/build-pair.sh` is this document as an executable. |
| [CARDDAY.md](CARDDAY.md) | 562 | Card day: the runbook as it was actually run, the staged pairs, and the forensics kept when build trees are reclaimed. |
| [BRINGUP.md](BRINGUP.md) | 761 | Hardware bring-up, and the gates CI's green tick does not cover. |

## The record

Kept because the project's claim is that failures stay in the record. Not
reading material for a working session.

| document | lines | what it is for |
|---|---|---|
| [VALIDATION.md](VALIDATION.md) | 11,136 | The validation ledger, append-only. Every run, including the ones that failed and the mistakes that produced them. A figure here is a fact about the run on its date and is never edited to match a later one. |
| [ROADMAP.md](ROADMAP.md) | 2,684 | What is built, what is next, and what was decided against. |
| [NOVEL.md](NOVEL.md) | 553 | Results for which no prior description was found, with the standard of evidence stated first. |
| [ATLAS.md](ATLAS.md) | 362 | The atlas-engine integration, assessed before any of it was done. |
| [FUNDING.md](FUNDING.md) | 44 | Funding landscape. |

## The design studies

Four rounds of "should we build it this way", with the measurements that
settled each. History of reasoning, not current reference — but the place to
look before reopening one of these questions.

| document | lines | question it settled |
|---|---|---|
| [studies/OPT-A-datapath.md](studies/OPT-A-datapath.md) | 919 | the arithmetic datapath |
| [studies/OPT-B-array.md](studies/OPT-B-array.md) | 1,017 | the array, the beat, and how many tiles a part holds |
| [studies/OPT-C-timing.md](studies/OPT-C-timing.md) | 1,151 | timing, and what the physical tools will and will not give |
| [studies/OPT-D-contract.md](studies/OPT-D-contract.md) | 1,048 | the contract and the system above the RTL |

---

Two more live outside `docs/`: [../CAPABILITIES.md](../CAPABILITIES.md) is
what a given build can do, and [../CLAUDE.md](../CLAUDE.md) is the short
list of things that have already cost hours.
