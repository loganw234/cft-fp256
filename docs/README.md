# The documents, by what you open them for

Thirty-seven files, 48,501 lines. Flat in one directory they look like one
undifferentiated pile; they are not, and the split is close to even:

- **16,346 lines you consult while working** — the three under *Start here*,
  the contract, and the reference you call into;
- **5,538 lines of tool manual**, one per shipped program;
- **1,743 lines of operations**, read when you are about to do something to
  hardware;
- **24,874 lines of record and argument** — the ledger, the roadmap and the
  design studies. The history of how a decision was reached, worth keeping,
  and not what you open to get something done.

Half is therefore history. That is deliberate, and it is also why a
flat listing of thirty-seven names feels heavier than the work actually is.

This index exists because the README links eight of these and nothing linked
the other twenty-seven. Nothing has moved: a file's path is part of its
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
| [INTEGRATION.md](INTEGRATION.md) | 253 | Choosing a path: which surface to use for which job. The shortest route from "I have a workload" to "I know what to call." |
| [VERIFICATION.md](VERIFICATION.md) | 347 | Every gate, what it proves, how long it really takes. Twelve tiers, forty runner stages. |
| [COMPLIANCE.md](COMPLIANCE.md) | 172 | IEEE 754-2019 clause by clause: what is implemented, what is refused, and where each is proven. |

## The contract

What the project promises. Change one of these and you have changed the
product, not the implementation.

| document | lines | what it is for |
|---|---|---|
| [DETERMINISM.md](DETERMINISM.md) | 1,439 | The determinism contract itself — the argument the whole project rests on, including the unassigned-opcode hazard and every time it has fired. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 1,155 | The tile: register map, MODE and CAPS words, the rule for when VERSION moves. |
| [SEQUENCER.md](SEQUENCER.md) | 1,901 | The orbit sequencer and the program model. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | 786 | One section per ABI step, with a per-surface table. Read before assuming a call exists on a given surface. |
| [LAYOUTS.md](LAYOUTS.md) | 188 | Every xclbin layout the U50 could carry - tile mixes and their clocks - derived by `hw/gen_layouts.py`, never typed. |

## Reference you call into

| document | lines | what it is for |
|---|---|---|
| [HOSTAPI.md](HOSTAPI.md) | 2,580 | The host API, function by function. The largest reference here and the one most often wanted. |
| [TRANSCENDENTALS.md](TRANSCENDENTALS.md) | 1,667 | The thirty-nine correctly-rounded transcendentals, by ABI phase, with the evidence for each. |
| [REMOTE.md](REMOTE.md) | 1,387 | The remote backend: a tile behind a socket, the frame protocol and the WebSocket path. |
| [PROGRAMS.md](PROGRAMS.md) | 475 | Programs as files: the assembler, the program library, the runner. |
| [EMBEDDED.md](EMBEDDED.md) | 675 | libcft on microcontrollers, and the profiles the embedded gate runs. |
| [PLATFORMS.md](PLATFORMS.md) | 2,913 | Every platform the library has been built and run on, with dates and results. |
| [SCALING.md](SCALING.md) | 408 | What more tiles buy, and what they do not. |

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
| [BENCHMARKS.md](BENCHMARKS.md) | 628 | what all of the above measure, in software and on the card |

## Operations — doing a thing to hardware

| document | lines | what it is for |
|---|---|---|
| [BITSTREAM-BUILDS.md](BITSTREAM-BUILDS.md) | 240 | Building a bitstream, and the five traps — three of which exit 0, and one that looks like a design failure. `hw/build-pair.sh` is this document as an executable. |
| [CARDDAY.md](CARDDAY.md) | 735 | Card day: the runbook as it was actually run, the staged pairs, and the forensics kept when build trees are reclaimed. |
| [BRINGUP.md](BRINGUP.md) | 768 | Hardware bring-up, and the gates CI's green tick does not cover. |

## The record

Kept because the project's claim is that failures stay in the record. Not
reading material for a working session.

| document | lines | what it is for |
|---|---|---|
| [VALIDATION.md](VALIDATION.md) | 14,069 | The validation ledger, append-only. Every run, including the ones that failed and the mistakes that produced them. A figure here is a fact about the run on its date and is never edited to match a later one. |
| [ROADMAP.md](ROADMAP.md) | 3,227 | What is built, what is next, and what was decided against. |
| [ROUND2.md](ROUND2.md) | 1082 | The plan for the gather, the scatter, the lane mask and the broadcast as one parcel round, with its outcome at the top: the seam the lead lands first, a brief per parcel, the verifiers, the ledger, the merge order. |
| [NOVEL.md](NOVEL.md) | 557 | Results for which no prior description was found, with the standard of evidence stated first. |
| [ATLAS.md](ATLAS.md) | 362 | The atlas-engine integration, assessed before any of it was done. |
| [FUNDING.md](FUNDING.md) | 44 | Funding landscape. |

## The design studies

Four rounds of "should we build it this way", with the measurements that
settled each, one of "how far would it stretch", and one
reading of the open toolchain's router. History of reasoning,
not current reference — but the place to look before reopening one of these
questions.

| document | lines | question it settled |
|---|---|---|
| [studies/OPT-A-datapath.md](studies/OPT-A-datapath.md) | 919 | the arithmetic datapath |
| [studies/OPT-B-array.md](studies/OPT-B-array.md) | 1,017 | the array, the beat, and how many tiles a part holds |
| [studies/OPT-C-timing.md](studies/OPT-C-timing.md) | 1,151 | timing, and what the physical tools will and will not give |
| [studies/OPT-D-contract.md](studies/OPT-D-contract.md) | 1,048 | the contract and the system above the RTL |
| [studies/EXT-A-wide-ladder.md](studies/EXT-A-wide-ladder.md) | 1,146 | how far the ladder extends above binary256, what an MPFR-shaped tile is worth on an FPGA and on an ASIC, and what counting in MPFR cores leaves out; its instruments and their captured runs are in `studies/ext-a/` |
| [studies/TOOL-A-dense-router.md](studies/TOOL-A-dense-router.md) | 252 | why openXC7's router does not converge on the tile, what to change in it and in what order, and why a fork of it (loganw234/nextpnr-xilinx, `dense`) starts at the pinned 0.9.6 |

---

Three more live outside `docs/`: [../CONFORMANCE.md](../CONFORMANCE.md) is
the contract as a profile an independent implementation is scored against,
[../CAPABILITIES.md](../CAPABILITIES.md) is what a given build can do, and
[../CLAUDE.md](../CLAUDE.md) is the short list of things that have already
cost hours.
