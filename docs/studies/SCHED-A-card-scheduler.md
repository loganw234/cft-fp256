# SCHED-A: a card scheduler for the U50 and the cards after it

**Date:** 2026-10-21. **Parcel:** SD, a design study (Sonnet 5.5; a verifier follows). **Status:** nothing here is built. The five
instruments in `docs/studies/sched-a/` read local copies and call the driver's own functions on synthetic input, and nothing under
`host/`, `hw/`, `rtl/`, `python/`, `programs/` or `tb/` changed. **Basis:** the tree at 0b7c959 (main after the coverage wave); two
local copies of a driver run's `metrics.jsonl`, the 60-hour run of 2026-10-16 to 19 (5,108 records, 7,982,931 bytes, SHA-256
e7989f88efded691ea7461e921840d8de5d449e069980f6ba92e6a8f87e007cc) and the overnight run of 2026-10-19 to 20 (751 records,
1,431,954 bytes, SHA-256 cd0aec75c8fa9abbb7bbaaa0eca09bbdf2eb43e0257d77fd539e62f7199f578b), which the lead holds and which are
not in the repository; and the lead's box scripts, read in place and named here by file name only. The card and amd-arc-box were
not touched and nothing was measured on them: every figure about the box is a figure from a record.

**Marks.** Every figure is one of: **MEASURED** (a run of mine, named: an instrument in `docs/studies/sched-a/`, or `git` and
`wc` on this tree), **READ** (a file or a record, named, including a figure the lead measured and wrote down), **COMPUTED**
(arithmetic on those), **BELIEVED** (mine, unverified). A
table's caption gives the mark of its figures when it is the same throughout. A design choice is a proposal, not a fact, and
carries no mark; the claim that it will work is BELIEVED until a parcel's tests say otherwise.

## 0. The answer in a page

Logan asked for one scheduler per machine that owns the card's time: it runs the nightly window (18:00 to 08:00) on whatever the
sweep has not reached, stages program runs, keeps metrics on the card and its performance, replaces the lead's ad-hoc box
scripts, and can later manage several cards. This study checks what exists, weighs the options and recommends a first version.
In the order they matter:

1. **The driver is already the window runner; what is missing is everything above one run.** `hw/card_stress.py` (2,532 lines,
   with its library 1,023, report 1,570, stand-in 378 and test 3,629; MEASURED, `wc -l`) has the legs and the parsers that fail
   loudly, a guard that names other card users by what they run and leaves out its own family, a stop that comes after the leg running, a recovery ladder, resume from
   its own record, a CPU pool for the host items, a build step that asserts XRT, and telemetry (section 2.1). It has no queue, no
   start time (only a deadline), no second kind of job, nothing that chooses its work from earlier runs except the random seeds,
   and it is one card by construction (section 2.1, "What it does not do").
2. **The lead's scripts are one skeleton written seventeen times.** MEASURED (`script_census.py`): 17 scripts and 744 non-blank
   lines; 16 clone from a bundle and assert HEAD, 15 assert a clean status, 15 grep the clone for a string of each change, 7
   assert the rtl/ tree, 6 build with `XRT=1` and check `ldd`. Nine of them use the card, and each guards in its own way: eight
   with a `pgrep -fc` of a pattern (seven different patterns among them), one on the stress run's status file and a hard-coded PID.
3. **The two guards disagree, and the scripts' is the weaker.** MEASURED (`guard_probe.py`, on the driver's own functions): the
   nightly's pattern misses four card users the driver names (an idle `cft-serve --artifact`, `xbutil program`, `device-test` and
   `acceptance.py` on an image) and counts two processes that use no card (the asker's own shell, whose command text holds the
   pattern, and a gate run). The self-match is not new: the record has it on 2026-09-18, and the lead met it again on 2026-10-20.
4. **The nightly keeps its coverage in a shell variable and a directory name.** READ: three scripts carry the same list of 22
   `--sweep-items`, and the one run directory `card-stress-1019` is resumed each night after the first. That works until the list empties:
   with every named item complete the card's waves are empty (event `sweep_empty`) and the cycles are battery only, unless
   someone edits the script. And the resume is blind to trees in its planner while the report is not: night 2 ran at 0b7c959,
   whose rtl/ tree is the images' but whose host/ tree is a third one (MEASURED: `git rev-parse`; section 2.6).
5. **The finite part of "wherever it hasn't reached yet" closes within about a week.** At the pace the files show (0.84 to 1.24
   points of its space an hour for each of the four unfinished items, COMPUTED) and the pace the lead read on the second night
   (1.10, READ), the four `scaleb32-wide` items finish between the mornings of 2026-10-26 and 2026-10-29 (BELIEVED). After that
   the work "not reached" is the new finite items the driver is about to gain (parcel DR3), the random items, the host items on
   each new host/ tree, and everything again on a new rtl/ tree (6 to 9 nights, COMPUTED).
6. **Preemption is cheap because the driver stops at leg boundaries.** A request to stop waits, for a request arriving at a random
   instant of a run, 3.5 minutes on average and 8.7 at the 95th percentile (the overnight run; 2.5 and 8.0 in the 60-hour run),
   the longest leg being about 11 minutes, and 36.5 minutes once, the first visit's `acceptance-rev8` leg (BELIEVED a compile; COMPUTED
   from 543 and 4,086 legs, `latency.py`). A staged run can therefore outrank the sweep.
7. **The record's volume is no obstacle; the box's disk is.** A night's `metrics.jsonl` is 1.6 to 1.8 MB and a year of nights 590
   to 670 MB, three fifths to two thirds of it telemetry that a compact record would hold in a twenty-fourth of the bytes (COMPUTED,
   `volumes.py`); a year of whole run directories, logs included, is about 2.2 GB by the one `du` the lead took (READ, COMPUTED); and
   `/data` was 93 per cent used with 18 GB free on 2026-10-20 (READ), mostly files that are not this project's runs.
8. **"Scheduler" is taken, and several cards need more than a scheduler.** docs/ROADMAP.md and docs/HOSTAPI.md use the word for the
   library's tile scheduler (placing a run's waves on the tiles of one handle). This study calls its subject the card scheduler.
   Several cards also need a device selector that does not exist: `cft_open` takes an index, the soak tools pass 0 (READ,
   `divsqrt_soak.c:1013` and `clause5_soak.c:2940`), and the driver's `--card` names the card for telemetry only.

**Recommended v1 (section 5):** one Python process per machine, standard library only, launched by the lead (no unit and no
crontab until Logan says), that holds one lock, one file queue and one worker per card (one card in v1, card ids everywhere).
Its jobs are of two kinds. A **window** job runs the unchanged driver as a subprocess, between the window's start and its end,
resuming the run directory its commit's trees call for and focusing it on the finite items still unfinished there. A **staged**
job is a chain of named steps (the driver's legs, a soak slice, `make vectors`, the driver's own dry tests), each judged by the
driver's parsers and never by an exit status alone. Every job clones a full SHA and asserts it (HEAD, a clean status, the rtl/
tree, a string from each change), builds with `XRT=1` and checks `ldd`, finds other card users by the driver's own rule, and
ends in a record whose last word is a name. A staged job outranks the sweep, which is stopped at a safe point and resumed. The
records stay `metrics.jsonl`-shaped, so the report, the figures and the signed-record exporter read them unchanged. **Deferred:**
several cards, a coverage ledger beyond one fold, served sessions, load shedding, signed submissions, a network listener. **It
replaces first** `box_nightly.sh`, then `box_resume_stress.sh`, then the card-leg scripts. **The first questions** (section 7): the
name and layer (1), whether the box may fetch a pushed commit itself (9), what the window does when the finite items are done (6),
and whether a staged run may preempt the sweep (5).

## 1. The question

**Logan, verbatim (2026-10-21):** "Every night from 6pm-8am we can run the card on wherever it hasnt reached yet, perhaps a parcel
for setting up a 'scheduler' which could be utilized in the future as well for staging program runs etc while retaining metrics
about the card and performance, rather than having to rely on scripts as we have so far. Could be beneficial if more cards ever
exist in the future, allowing 1 scheduler to manage many cards on a machine for user simplicity." And, on starting this study: "Go
ahead and start the design study now since its not specific to any prior steps".

**What "scheduler" must mean here.** One program per machine that owns card time, and:

- runs the nightly window (18:00 to 08:00) on whatever the sweep has not reached;
- stages program runs: workloads, acceptance sets, the lead's card checks, a parcel's card leg;
- keeps metrics on the card and on its performance, as records;
- replaces the lead's ad-hoc scripts, by doing what each does every time and recording it;
- can grow to several cards on one machine.

**The word.** docs/ROADMAP.md ("Programs across tiles: a partitioner and a scheduler (plan of record, 2026-09-18)") and
docs/HOSTAPI.md use "scheduler" for the library's: one core, `run_job` in `host/src/backend_xrt.cpp`, that places the waves of one
handle's runs on its tiles (READ). It lives inside a process and knows nothing of other processes. This study's scheduler is one
layer up: it decides which process holds the card, when, with which image and code, and what is written down. Four layers, then:
the card and its XRT; the library's tile scheduler inside a handle; the card scheduler (this study); and the stress driver, which is
one kind of job for it. The bare word below means the card scheduler.

**What it is not.** It is not a second driver: the legs, the parsers, the sweep catalog and the recovery ladder are the driver's and
stay there. It is not a place that runs a stranger's code or answers a network: Logan's answer to the sweep study's sixth question
was "At the moment only my device, though built to support a signing key would be good" (docs/VALIDATION.md, the coverage wave's
record). And it is not a source of verdicts of its own: what a leg proved is what its tool printed, parsed by the parser written for
it.

## 2. What exists today, checked

### 2.1 The stress driver

The driver is `hw/card-stress.sh`, a 43-line wrapper that sources XRT's `setup.sh`, picks a python and `exec`s `hw/card_stress.py`
(READ). Its library `hw/card_stress_lib.py`, its report `hw/card_stress_report.py` and its stand-in `hw/card_stress_standin.py` are
imported by the driver, the report, the test `hw/test_card_stress.py` and `hw/sweep_record.py`, "so the three cannot disagree about
what a record means" (the library's own docstring). Sizes MEASURED, `wc -l` at 0b7c959: 2,532, 1,023, 1,570, 378, 3,629 and 735 lines.
It has 49 command-line options, two of them hidden (MEASURED, `grep -c`). What it does, each READ in the file named:

| capability | what it does | where |
|---|---|---|
| **the legs** | twelve battery legs, run on each image visited: `api-test`, `dt-i` (the image's identity, held to the file's SHA-256 and tile count), `dt-q8`, `dt-full`, `dt-r`, `dt-b`, `card-segrun`, `seq-check`, `acceptance`, `acceptance-rev8`, `resident`, `selftest` (every third visit); each has a timeout of 300 to 3,600 s | `card_stress.py` `BATTERY`, `DEFAULT_TIMEOUTS`, `leg_cmd` |
| **the parsers** | a verdict is one whole line, anchored; a missing, doubled or contradicted line (including an exit status that disagrees) is a `parse_error` leg whose log is kept whole; a count is a captured group or absent, never 0; each pattern quotes the `printf` it matches and the test finds its wording in the tool's source | `card_stress_lib.py` `parse_*`, `_one`, `_rc_agrees` |
| **the sweep** | a catalog of 90 items (36 exhaustive over 2^32 encodings, 54 random), 43 of them tile items and 47 host items; slices sized from the measured rate (a probe of 2^20, then the rate times 600 s, whole 2^20 steps, at most 2^28 on the card and 2^36 on the pool); the card's waves run one job a tile; coverage is rebuilt from `metrics.jsonl` alone; an exhaustive slice that fails to finish twice is moved past (quarantined) | `sweep_items`, `plan_wave`, `sweep_coverage`, `Item` |
| **the seeds** | a random slice's seed is `(item index << 40) \| (n << 1) \| 1`, distinct for every (item, n), and `--earlier-runs DIR[,DIR...]` starts each item's n above every named run's; the directories are named, never searched for | `Item.seed_for`, `earlier_runs` |
| **coverage per tree** | `run_start` records `tree.rtl`, `tree.host_src`, `tree.cc` and their dirty flags; the report counts a tile item per rtl/ tree and a host item per host/ tree and compiler, the three images beneath; `--also DIR` adds other runs to that section | `tree_facts`, `card_stress_report.py` `_trees` |
| **the guard** | before the start (refuses, exit 2) and before every leg and wave (waits up to `--guard-wait-max`, 4 h) it looks for a process that uses the card: a program that opens an image, `acceptance.py`, `seq_check.py`, `cft-segrun` or `cft-audit` with a `--device` that is not software, a soak with `CFT_SOAK_ARTIFACT` in its environment, `xbutil` or `xrt-smi` running `program`, `reset`, `validate`, `advanced`, `configure` or `dump`; its own process, its descendants and its ancestors are excluded; `verify/run.sh` is allowed and recorded as `beside`; it detects, never kills | `card_user`, `find_card_users`, `guard` |
| **telemetry** | every 300 s and between legs: `xrt-smi` or `xbutil examine -d 0000:02:00.1 -r electrical`, `thermal`, `mechanical`, as JSON where it will and as text otherwise, with the host's load, memory and the free disk of the run directory and `/data`; a sample with no values is recorded as such with its raw text; samples are taken one at a time | `take_sample`, `host_sample` |
| **the records** | `metrics.jsonl` is append-only, one whole line a record, a lock around the write, an fsync, a torn tail repaired on resume; record types `run_start`, `build`, `cycle_start`, `leg`, `telemetry`, `cycle_end`, `event`, `run_end`; `status.txt` is rewritten after every leg and at least once a minute while a leg runs; `report.txt` after every cycle (a 120 s limit); `driver.log`, `settings.json`, `STOPPED.txt` | `append_record`, `write_status`, `refresh_report` |
| **stop and the ladder** | the stop file `$OUT/STOP`, SIGINT or SIGTERM, the deadline, the disk floor (5 GB on the run directory and `/data`) and a moved tree (`git rev-parse HEAD` against the start's) are looked at between legs and waves, never in the middle of one; a failing leg keeps its log and the run goes on; a card that does not answer waits 120 s and retries once, from the second consecutive failure opens another image and comes back, and at six in a row stops with `STOPPED.txt` and the card idle | `should_stop`, `recover`, `after_result` |
| **resume** | `--resume --out DIR` rebuilds the cycle counter, the rotation, the sweep's intervals, the seeds, the rates and the quarantine from the file; exit 2 if the file exists and `--resume` was not given; a new `--until` is required each time | `load_state`, `parse_args` |
| **the host pool** | `--host-workers` (default 8) CPU-only soak processes beside the whole run, `nice -n 10`, with `CFT_SOAK_ARTIFACT` and `CFT_XRT_TILES` removed from their environment, their slices recorded under the image name `cpu`; a log that names a DEVICE is refused and stops the pool | `pool_start`, `run_host_slice` |
| **the build step** | the commit and the clean tree; a string from each of four files; `make -C host XRT=1 XRT_ROOT=... all device-test api-test remote-test divsqrt-soak clause5-soak`; each tool's `ldd` for `xrt_coreutil`; the tree's build id against `cft-segrun --build-id`; each image against its `SHA256SUMS` and the hash it was given | `build_and_check`, `build_tools` |
| **the dry run** | `--dry-run` replaces every command with `hw/card_stress_standin.py`, which prints the tools' real verdict lines and fails, hangs, loses the device or disagrees on a schedule | `Driver.standin`, `card_stress_standin.py` |

**How it is tested.** `hw/test-card-stress.sh` has parsers on real logs, the legs' command lines, the driver as a process against
the stand-in (normal, failing, timing out, deaf, no device, card lost, stop file, deadline, rotation, disk floor, guard, sweep,
telemetry, build, signal, torn tail, disabled items, pool, seeds, trees, report), and a plants stage that puts a defect back into
a copy of the code and requires the scenario written for it to fail at its own check (READ, the script's header and the test's
docstring). The lead's run in a fresh clone on the box on 2026-10-20 gave "card-stress test: 584 checks, 0 failed, 0 skipped" in
456 s without plants (READ, the lead's ledger); the whole suite with plants is about 22.5 minutes under WSL (READ, the script's
header) and 658 checks in the gate's run of 2026-10-20 (READ, docs/VALIDATION.md, the coverage wave's record). **A suite of this size
is the cost of changing the driver**, and it is why section 4.1 does not grow the driver into the scheduler.

**What it does not do.** Each of the following is READ in the code named, and the brief's list is confirmed:

- **A queue.** One invocation is one run. A second invocation is refused at its start when the guard sees a card user at that
  instant (exit 2, the suite's `guard` group); it is never queued.
- **Several campaigns.** One run has one catalog (`sweep_items()`), narrowed by `--sweep-items`, and one output directory.
- **Time windows.** `--until` is a deadline; there is no start time. The lead's nightly script sleeps until the start itself.
- **More than one card.** `IMAGES` holds default paths under `$HOME/cardday-rev8{q,a,d}`; the soak tools and `device-test` call
  `cft_open(artifact, 0, ...)`; `--card` (default `0000:02:00.1`) is used for telemetry and nothing else.
- **A lock.** The guard reads the command lines, and a soak's environment, of the processes alive at the instant it asks. Between two
  legs, and during the build step, nothing of the driver's holds the card, so a second driver started then passes the guard
  (BELIEVED, from `card_user` and `find_card_users`; not run, since it needs two real drivers on a card). XRT's exclusive
  compute-unit access then makes the loser's next open fail, which the driver reads as `no_device`, counts toward its streak and,
  from the second failure in a row, answers by loading another image (READ: `INFRA_PATTERNS` and `recover`). The window it leaves
  is small, since a run's legs and waves cover 99.90 to 99.92 per cent of its span (MEASURED, `latency.out`), but it is open in the
  build step at the start of a run and in the ladder's pauses. Ownership by a lock, not by looking, is a requirement (R3).
- **A service.** A run ends at its deadline. It ignores SIGHUP so that a closed terminal does not end it, and that is all.
- **A coverage view across runs, for planning.** `--earlier-runs` carries the random items' n and nothing else; an exhaustive
  item "still restarts at encoding 0 in a new `--out`" (docs/CARDDAY.md and docs/VALIDATION.md, DR2's known limits). The report's
  `--also` adds runs to a per-tree table for reading, and the planner does not use it.

### 2.2 The lead's box scripts

The lead's scripts for amd-arc-box are in the lead's scratchpad, read-only for this study. `script_census.py` read all 17 (16 named
`box_*.sh` and `copy_wave9.sh`) and counted what each does; the capture is `sched-a/script_census.out`. They fall into three
groups by their headers (READ): **nine use the card** (`box_nightly.sh`, `box_resume_stress.sh` and `box_overnight.sh` run the
driver; `box_smoke.sh`, `box_chunk_card.sh`, `box_rint_ab.sh`, `box_ma_card.sh`, `box_batch.sh` and `box_chunk.sh` run a parcel's
card leg, an A/B or the pass-size experiment), **seven do not** (the gates `box_wave7_gate.sh`, `box_wave8_gate.sh` and
`box_wave9_gate.sh`; the narrow runs `box_wave8_tip.sh` and `box_wave9_tip.sh`; `box_ms_stages.sh`; `box_br_ab.sh`), and
`copy_wave9.sh` copies records.

| what the script does (mentions or does, MEASURED) | scripts of 17 |
|---|---|
| keeps a dated summary with `say()` and ends it `=== done` | 16 |
| refuses to start when its output already exists | 17 |
| clones from a bundle (`git clone -q $W/bundles/...`) | 16 |
| asserts HEAD | 16 |
| asserts a clean status (`status --porcelain`) | 15 |
| greps the clone for a string of each change | 15 |
| asserts the rtl/ tree hash | 7 |
| builds with `XRT=1` | 6 |
| checks `ldd` for xrt | 6 |
| sources XRT's environment | 6 |
| runs its work niced | 15 |
| records a sha256 | 7 |
| guards with `pgrep -f` on a pattern | 9 (8 distinct patterns, 7 among the card scripts) |
| guards on the stress run's `status.txt` and a PID | 1 (`box_ma_card.sh`) |
| waits for a start time | 1 (`box_nightly.sh`) |

**What they do every time** (the brief's list, READ in the scripts): clone a pushed commit from a bundle under `/data/m1e1/bundles`;
assert HEAD, a clean status, the rtl/ tree hash `44b963dd6ba2fcf99e002c5face5ca94aad4515c` and a string only the new commit has;
build with `XRT=1` and check `ldd`; refuse if another card process is alive; run; write a dated summary ending `=== done`; and then
the lead copies the logs to the desktop with the box's sha256s beside them (`copy_wave9.sh`: an `ssh -n` `sha256sum` on the box, an
`scp` of each file, then `sha256sum -c` on the copies). Two details the scripts carry that nothing else does: the order of
`box_nightly.sh`'s steps is a constraint (`make vectors`, then the driver's dry tests in a clone nothing has built, then the smoke,
which builds, then the long run), and `box_resume_stress.sh` and `box_nightly.sh` hold the **same list of 22 items** and the **same
directory** `/data/card-stress-1019`.

**Their recorded traps** (READ, the lead's ledger, `docs/VALIDATION.md` and the lead's memory notes; each is a failure that proved
nothing or refused for the wrong reason):

- **A `pgrep -f` guard matches its own launching shell.** The record has it on 2026-09-18 ("after the inline form matched its own
  command line twice more today", docs/VALIDATION.md, the card half), on 2026-10-20 when `box_rint_ab.sh`'s first launch refused
  itself with "2 card process(es) alive", and again at 19:30 that evening ("the shell itself ... `pgrep -af` alone listed
  nothing", the lead's ledger).
- **A test that copies the checkout fails in a built clone.** `hw/test-card-stress.sh`'s `buildreal` group copies host/ and hw/ into
  a scratch repository and commits them; in the gate's clone, which the gate had built, it took 28 ignored products, the build
  rewrote them, and two checks failed (READ, the lead's A/B: 9255ab8 built 2 failed, fresh 7 of 7 passed; the coverage
  wave's closing record, "The box"). The lesson is an ordering rule a scheduler's step registry must carry.
- **ssh and stdin.** `tar cf - x | ssh box 'tar xf -' < /dev/null` sends nothing, "because the redirect replaces the pipe" (the
  lead's note on running stages on the box); `box_smoke.sh` and `box_rint_ab.sh` close stdin on their card jobs (`< /dev/null`) and
  `copy_wave9.sh` uses `ssh -n`.
- **`git bundle create <file> <branch>` makes no HEAD.** A clone of it needs `-b <branch>` or a checkout of the SHA (the lead's
  ledger, 2026-10-20; verifier VDR2's first clone was empty).

**Their niceness.** 15 of the 17 run their work at `nice -n 10` (MEASURED, the census), the gates included (`box_wave9_gate.sh` runs
`nice -n 10 bash verify/run.sh --budget gate`, READ), which is the niceness of the driver's legs and of the host pool. A gate beside a
window therefore competes with them at equal priority, whereas docs/CARDDAY.md's account of the pool assumes the box's other runs
outrank it: "at `nice` 0 they outrank every job here" (READ). The load the card run itself puts on the box is a median of 2.9 to 3.2
(section 2.3), so there is room; the point for the scheduler is to record the load beside every job and to assume no order.

**Tonight's window is one of them.** At 07:35:21 on 2026-10-21 the lead launched `box_nightly.sh` detached with `0b7c959
stress-0b7c959.bundle 1021 "2026-10-21 18:00" "2026-10-22 08:00"`; it sleeps 624 minutes in the script, then runs the preamble and
the driver (READ, the lead's ledger). That is the scheduler's first job, written by hand.

### 2.3 The card and the machine

All READ in the file named unless marked. `docs/CARDDAY.md` and `docs/VALIDATION.md` hold the rest.

| fact | value | where |
|---|---|---|
| the machine | `amd-arc-box`, Xeon E5-2697 v4, 36 threads, two NVMe disks, Ubuntu 24.04; key-authenticated ssh as `logan` | `CLAUDE.md`, `docs/BRINGUP.md` lab map |
| its memory | 48,061 total and at least 44,369 available throughout the overnight run, in the records' `mem_total_mb` and `mem_avail_mb` (`/proc/meminfo` divided by 1024, so MiB; MEASURED, `volumes.out`); `CLAUDE.md` says 46 GB | the telemetry records |
| its load beside the card run | load1 median 2.88 and maximum 5.75 over 176 samples (overnight run); median 3.22 and maximum 6.74 over 865 (60-hour run) (MEASURED, `volumes.out`) | the telemetry records |
| its disk | `/data`: 205G of 234G in use, 93 per cent used and 18 G free on 2026-10-20 (the lead's `df` readings: the percentage and the free figure are `df`'s, which leaves out blocks reserved for root, BELIEVED); the biggest tenants are `/data/Xilinx` 107G, `dense-archive` 23G, `step6` 13G and `rev7-quad` 11G, "none of them this round's" | the lead's ledger, 2026-10-20 13:0x |
| the card | one Alveo U50 (this project's custom active-cooled unit), `02:00.0`, whose user function is `0000:02:00.1`; shell `xilinx_u50_gen3x16_xdma_base_5`; XRT 2.19.194; images are built by Vitis 2022.2 | `CLAUDE.md`, `docs/BRINGUP.md` |
| its images | revision 8's three, in `$HOME/cardday-rev8{q,a,d}/`: **quad** (4 tiles) 51,714,554 bytes, SHA-256 4f9921a2...; **single** (1 tile) 40,076,366, 0639248e...; **deep** (1 tile) 47,197,081, bbf08fb3... | the overnight run's `build` record, and `hw/card_stress.py` `IMAGES` |
| loading an image | `cft_open` loads the xclbin through XRT (`xrt::device(index)` then `load_xclbin`); there is no separate program step; loading the image already there is a no-op; the first pass of a run that opens it carries the load: 5 s and 9 s, for the single and the quad in the entry's order | `host/src/backend_xrt.cpp`, `docs/HOSTAPI.md`, `docs/VALIDATION.md` (2026-09-18, the card half) |
| exclusivity | each compute unit is opened exclusive, so a device on the quad is the quad and no second process can hold a tile a first one has | `docs/VALIDATION.md` (the stress driver's entry), `docs/REMOTE.md` |
| what an abandoned run does | the tile "cannot be stopped": it runs on after XRT aborts the command, and later runs on that tile are reported complete early, in any process, until the image is reloaded; the cure is to load another image and then this one (loading the same image again "cures nothing"); the library refuses by name at the next open | `docs/HOSTAPI.md`, "A tile a run was abandoned on (2026-09-25)" |
| the sensors | `xrt-smi` or `xbutil examine -d 0000:02:00.1 -r electrical` (and `thermal`, `mechanical`): FPGA 29 to 39 C and 15.5 to 22.7 W over the overnight run | `hw/card_stress.py`; `docs/VALIDATION.md`, the coverage wave's record |
| the clock | the box ran at UTC-7 on 2026-10-19 (the record's epoch 1792463807.507 is local 19:36:47); the zone's name and its daylight-saving rule are not recorded | `docs/SWEEP-RECORDS.md`, MEASURED there on that record |
| what cannot run there | hw_emu (glibc 2.39's libm carries `.relr.dyn`, which Vivado 2022.2's binutils cannot read): it belongs to `cft2204` | `CLAUDE.md` |

Two consequences carry through the study. The card is switched by opening an image, so "which image the card holds" is a fact the
scheduler keeps by recording every open, and a reload is five to nine seconds, so grouping jobs by image saves little and
mixing them costs little. And an abandoned run poisons a tile until a reload, so the scheduler must never stop a card process
in the middle of a leg: it asks the driver to stop (section 2.1) and waits.

### 2.4 The remote backend, and where it and a scheduler would meet

`docs/REMOTE.md` (READ). A client reaches the tile today in one of two ways: `cft_open` of the image's file, in the process that does
the work (what every card leg and soak does), or `cft_open("cft://host:port", ...)` to a `cft-serve` that opened the image.
`cft-serve [--port N] [--bind ADDR] [--artifact PATH] [--max-conns N] [--pid-file PATH] ...` fronts a device over TCP, binding
`127.0.0.1:7754` unless told otherwise, with **no authentication and no encryption** ("a transport, not a security boundary"). It serves up to 32 connections, one request at a time in arrival order. It opens a library device for a
connection at its first HELLO and not at accept, because "a device on a card holds every compute unit it spans, exclusively": on
2026-09-09 a probe left connected held the read-ahead quad for seventeen minutes and every real client was told the artifact
was not a tile. A client that vanishes after its HELLO releases its tile after about a minute (keepalive: probe after 30 s, every 10 s,
three times).

Where it and the scheduler meet, and where they collide:

- **They want the same compute units.** While any client has said HELLO the card is claimed, and `cft-serve` has no queue: a
  second HELLO to a held card fails with the misleading "not a tile". The scheduler is the admission control in front of the
  card; a served session is therefore a job of its own (deferred past v1), started by the scheduler with `--bind 127.0.0.1`,
  `--max-conns` and `--pid-file`, with a deadline, and stopped by its PID.
- **The driver's guard names an idle server as a card user.** MEASURED (`guard_probe.py`, the driver's own `card_user`): `cft-serve
  --artifact IMAGE` is "an xclbin argument" whether or not a client is connected, and the same server on the software backend is
  not. A resident `cft-serve --artifact` on the box would therefore refuse the driver's start (exit 2), or stall a run at its next
  guard check for up to four hours and then stop it (`guard_timeout`; READ, `guard`). Rule: no `cft-serve --artifact` stays resident
  on a managed card.
- **The transport has no identity.** Any local process may connect. If a served session is ever offered, "only Logan's device" is a
  property of where it binds and who can reach the box, not of the protocol.
- **A remote client is not a card job.** `cft://host:port` names a device that is a remote process; the scheduler's card jobs open an
  image by its file, and a client of a served session is one connection to a server the scheduler started.

### 2.5 What reads the driver's output today

The output of a run is a directory: `metrics.jsonl` is the record and everything else is derived from it or about it (`status.txt`,
`report.txt`, `driver.log`, `settings.json`, `STOPPED.txt`, `logs/`). Five things read it, and the scheduler must leave each of
them working:

- **The report**, `hw/card_stress_report.py RUN_DIR [--json FILE] [--also DIR]...`: header, totals, a row per (image, leg), telemetry,
  failures, the sweep's coverage and, since 2026-10-20, coverage by tree; the driver runs it after every cycle with a 120 s limit.
  DR2 measured it at 0.49 s on the 8 MB file (READ). If it is linear in the file (BELIEVED), a single file the size of a year of
  nights (about 0.6 to 0.7 GB, section 2.7) would take near 40 s, and a file of about 2 GB would pass its limit (COMPUTED, at the
  desktop's speed): rotation of the run directory is a requirement for a year, not for a month.
- **`python/figure_extracts.py stress`**: reduces one run's `metrics.jsonl` and `report.txt` to `docs/figures/stress.json`, with the
  raw file's SHA-256 and the command that remakes it; three figures (`stress-timeline`, `stress-telemetry`, `stress-sweep`) read the
  extract (READ, `python/project_figures.py`). It imports the driver's library and report. DR2 found that a `cpu` sweep leg would
  count in its `activity_at` as "sweep, host items only" beside the card; parcel DR3 fixes it.
- **`hw/sweep_record.py export | sign | verify`**: reads a run directory or file and writes canonical, optionally signed records of its
  finished slices; it refuses a dry run, requires a passing `build` record since the `run_start`, and ignores record types it does not
  know (READ, `docs/SWEEP-RECORDS.md`). Its records do not carry the rtl/ tree (the run did not record it before 2026-10-20).
- **The driver itself**, on `--resume` and `--earlier-runs`.
- **The lead's scripts**, by text: `tail -1 driver.log` ("card-stress ends: deadline (exit 0); the card is left idle ..."), the
  suite's "card-stress test: N checks, F failed" line, and `status.txt` (READ, the scripts).

The principle that follows: **a window's output stays a driver run directory, and a staged job's output is `metrics.jsonl`-shaped**
(legs in the driver's leg schema), so that these readers apply to it without change, and the scheduler adds its own record beside
them and never inside them. And one thing to avoid: scraping the driver's log text. `run_end` in the record gives the reason and the
exit; `STOPPED.txt` gives the cause of a policy stop; the exit status alone is not enough (exit 1 is both "`--quick` had a failing
leg" and a `SystemExit` message, READ in `card_stress.py` `run` and `load_earlier`).

### 2.6 The coverage ledger the sweep study planned, and the part a nightly needs

`docs/studies/SWP-A-coverage.md` (READ) plans, in its section 5 and as rank 6 ("weeks"), a store of immutable records whose coverage
is a pure function of the set: campaigns named by a hash of their description, strata with their own index spaces, a keyed
permutation to enumerate the 64-bit spaces without repeats, a digest per batch, a fold with merge laws L1 to L9 (each shown on a
planted wrong fold), and shards for several devices. Logan placed rank 6 after the math round (the brief; the lead's note of his answer
to question 10). Parcel SG built the record and its signature (`hw/sweep_record.py`, version 1); DR2 built the key the study's
question 4 asked for (coverage per tree); nothing builds the fold.

**What a nightly window needs of it is much smaller**, and it is a query: *which finite items of the tree this commit is on are not
complete, and where does each one's first gap lie?* The pieces:

1. **A key**: (item, subject class), the class being the rtl/ tree hash for a tile item and the host/ tree hash with the compiler's
   version line for a host item, as the report keys them. A run before 2026-10-20 recorded its commit and no tree hashes; the commit gives them (`git
   rev-parse <commit>:rtl`), a derived fact to be recorded as derived. MEASURED (`coverage_state.py`): the 60-hour run (f0693b2)
   and the overnight run (881bbcb) both stand on rtl 44b963dd...
2. **A fold**: the union of the finished intervals of every run of one class, by the driver's own `merge_intervals` and `first_gap`;
   held in `coverage_state.py` to an independent merge, and each check shown able to fail.
3. **A rule for findings**: a slice that found a mismatch is a record, never coverage (the study's rule); the driver counts it served
   so as not to redo it, which is right for planning, so the fold keeps *clean* and *with findings* apart and an item with a finding
   is never "complete" without saying so.
4. **A focus list**: the driver rotates fairly (fewest slices served per unit of weight, exhaustive 3 to random 1), so a plain run
   would starve the unfinished finite items behind 54 random items that have served nothing in a new directory. Priority is today
   the lead's `--sweep-items` list; the scheduler computes the list from the fold: the unfinished finite items of the class, tile
   items for the card and host items for the pool, or no list when none is unfinished.
5. **A directory rule**: which run directory a window resumes. Because the planner counts the whole file's coverage whatever the
   trees, the rule must put one tile class in one directory, and a host class change needs the planner's help (below).

**What the lead's resume does today, MEASURED (`coverage_state.py`, `git rev-parse`)**:

| | the 60-hour run (f0693b2) | night 1 (881bbcb) | tonight and night 2 (0b7c959) |
|---|---|---|---|
| rtl/ tree | 44b963dd | 44b963dd | 44b963dd |
| host/ tree | 8a138d18 | 276ed15a | 4d9905f8 |
| exhaustive items its file served | 14 (10 tile, 4 host) | 22 (8 tile, 14 host) | night 1's file, resumed |
| host items complete in the file | 4 of 18 | 14 of 18 | no host slice ran (BELIEVED, from the code): the 14 the file names are complete, and the other 4 are not on its list |
| tile items complete in the file | 10 of 18 | 4 of 18 (the four others served, `scaleb32-wide`, at 5.566 to 6.079 per cent) | the four wide items running |

Folded by rtl/ class (`coverage_state.py`), the two files make 14 of the 18 tile items complete and leave the four wide ones.
host/ changed in 15 of the 88 commits between 881bbcb and 0b7c959 and the library's own source did not: `host/src` and
`host/include` are byte-identical at all three commits (the same tree hashes, 60685ae4... and 6b0dc232..., and no commit between
the last two touched them; MEASURED, `coverage_state.out`); what changed is the Makefile, the soak tools (the new modes and the
draw-order fix) and the tests. The driver's `tree_changed` event compares only the rtl/ tree (READ, `run`), and
its planner counts the whole file's coverage, so the resumed run has no host item to run for the new host class (READ, `pick_item` and
`pool_start`; that no host slice ran on night 2 is BELIEVED, since its own record is not in a local copy), while the report, over
the same file, shows that class with only what ran after. The cost of doing as the report's key says is
small: all 18 host exhaustive items again are 4.3 core-hours, about 0.5 hours on eight workers (COMPUTED from card-run rates of host
code; the pool's own rates are unmeasured). **So the planner should be class-aware, and that is one small driver parcel** (DR4,
section 6), and until it exists the scheduler can only record the gap, by name, in `status` ("host class changed: 18 host exhaustive
items not re-run on this host/ tree").

What the rest of rank 6 adds (campaign hashes, strata, the enumeration, digests, the signed set and its multiplicity, replay) is for
accumulation across owners and for the 2^64 spaces. The existing exhaustive items are already "an identity enumeration over
[0, 2^32)" (the study, 5.8), so none of it is needed for the window; and the seam is clean: the planner asks `unfinished(class)`, answered
today from the runs' own records and later from the ledger's fold with no change to the scheduler.

**The finite part ends soon** (`coverage_state.py`, COMPUTED unless marked). Of the 18 tile exhaustive items 14 are complete on
rtl 44b963dd across the two files; the four `scaleb32-wide` items stood at 5.566, 5.591, 5.762 and 6.079 per cent after night 1 and
run at 25,596 to 26,277 encodings a second a job (MEASURED). The four shared the card with 18 others until 11.9 hours
into the 12.4 and so give no clean pace; from the slot-seconds the file's waves held (91 waves of four jobs, 6.67 h, and 14 of one,
1.29 h; the legs ran 70 per cent of the slot-seconds the waves held, a wave waiting for its slowest job) the four items alone would
gain 0.84 points of their space an hour, and 1.24 if every slot of every wave were busy. On the second night the lead read 14.233 to
14.746 per cent at 03:48 (READ, the lead's ledger), that is 8.667 points in the 7.85 hours since the resume, **1.10 an hour**, inside
that range. At 1.10 an hour and a 14-hour night less its 27 minutes of preamble, about 15 points a night, they complete during the
night that ends on the morning of 2026-10-27, and between the mornings of 2026-10-26 and 2026-10-29 at the range's ends (BELIEVED:
from about 19 per cent on the morning of the 21st, COMPUTED as the lead's reading plus 4.2 more hours at 1.10).
Then, with the list as scripted, the card's waves are empty. After that the finite work is whatever the driver gains (DR3: 13
hard-case items and the class items), the host items per host/ tree (0.5 hours of the pool), and, if rtl/ changes, all 18 tile items
again: 194 slot-hours, 94.5 per cent of them `scaleb32-wide`, which is 6.1 to 8.8 nights (a night holding 31.6 slot-hours with every
slot busy and 22.0 at the file's use of them). Question 6 asks what the window does in the gaps.

### 2.7 Data volumes

MEASURED, `volumes.out`, by `volumes.py` on the two local copies. `box/overnight-1019/` and `box/wave9/`, the directories the lead
copies a batch's records into, hold no `metrics.jsonl` and no `logs/`: the first is 5 files and 28,807 bytes (the overnight run's
report 23,464 B, its summary, the launching script and the sums), the second 61 files and 223,805 bytes for a whole day of gate,
narrow run, card checks, A/B and suites (the largest file 18,687 B). So the copies of `metrics.jsonl` the lead keeps elsewhere are the
ones read. The first three rows and the counts and sizes in the next two are MEASURED; the shares and everything below them are
COMPUTED from them.

| | overnight run (881bbcb) | 60-hour run (f0693b2) |
|---|---|---|
| file, records, span | 1,431,954 B, 751, 12.395 h | 7,982,931 B, 5,108, 61.047 h |
| telemetry | 176 records, 5,446 B each, 66.9% of the bytes | 865, 5,448 B, 59.0% |
| legs | 543, 850 B each, 32.2% | 4,086, 790 B, 40.4% |
| everything else (cycles, build, events) | 0.8% | 0.6% |
| bytes an hour | 115,522 | 130,766 |
| a 14-hour night (the window) | 1.62 MB | 1.83 MB |
| 365 such nights | 590 MB, of it telemetry 395 MB | 668 MB, of it telemetry 394 MB |
| a compact telemetry record (the six values `figure_extracts.py` reads, plus load and memory) | 227 B, 24.0 times smaller | the same |
| `/data` free, first and last sample | 18.60 and 18.60 GB (minimum 18.45) | 20.69 and 20.04 GB (-0.65, other writers) |

Three facts the table cannot give, and where each stands. **The logs**: the records name each leg's log (`log`, `log_kept`: 533
gzipped and 10 none in night 1) and not its size, and no local copy holds a `logs/` directory. The one measurement is the lead's:
`du -sh` of the 60-hour run's directory read 24 MB with 3,766 files in `logs/`, at 62 cycles and 57.0 hours (READ, the lead's ledger,
2026-10-19 03:59), which is 5.9 MB a 14-hour night and about 2.2 GB for 365 (COMPUTED from that one reading, BELIEVED for the same
mix). The host pool adds one log a slice, and its volume is unmeasured. **The clones**: a built clone is about 70 MB (READ, the
lead's ledger: scratch clones "about 70 MB each", the pass-size clones 71 to 74 MB), so seven nights' clones are about 0.5 GB (COMPUTED).
**The disk is the box's, not the project's**: the 60-hour run's `/data` fell 0.65 GB while its own directory held about 24 MB, and
`/data` is 93 per cent full of other things. The driver's floor of 5 GB free on `/data` is the only guard, and a year of run
directories at the lead's one reading (about 2.2 GB, metrics included) is 12 per cent of what is free now (COMPUTED).

### 2.8 What a preemption costs

MEASURED, `latency.out`, by `latency.py`: from each run's own leg intervals, with a sweep wave being the sweep legs of a cycle whose
intervals overlap (105 waves in the overnight run and 1,076 in the 60-hour run, each count equal to the sum of 1/jobs over the legs,
the wave size each leg records) and the wait for a request at a uniformly random instant being the time to the end of the activity
it falls in. 99.92 and 99.90 per cent of the span is inside an activity.

| wait for a safe point | overnight run | 60-hour run |
|---|---|---|
| mean | 212.4 s (3.5 min) | 151.7 s (2.5 min) |
| 50th, 90th percentile | 179.3 s, 464.0 s | 99.2 s, 366.4 s |
| 95th, 99th percentile | 524.2 s (8.7 min), 595.9 s (9.9 min) | 481.2 s (8.0 min), 631.0 s (10.5 min) |
| more than 300 s, more than 600 s | 28.6%, 0.9% | 15.3%, 1.4% |
| the longest activities | selftest 659.4 s (11.0 min), a wave 615.4 s | `acceptance-rev8` on the quad, cycle 1, 2,188.6 s (36.5 min) against a median of 349.2 s in its other 43 visits (the first visit compiles the eight workloads: BELIEVED the cause, from docs/CARDDAY.md), selftest 685.8 s |

A seeded Monte Carlo of the same definition agrees with the exact figures (212.4 against 212.4 s; 525.0 against 524.2 s at the 95th
percentile), and two planted slips, a wrong mean and a wrong grouping of waves, are each caught. **The host pool adds about a minute
(`--kill-after`, 60 s) after the last card leg** (READ, `pool_end`: a slice in flight is given that grace, then terminated by PID and
recorded as `host_job_abandoned`, which is not a slice and is served again), and a resumed driver costs its start (the tree facts, a
`make` that finds nothing to do, ten `ldd`s, the build id and three probes of the soak tool, three image hashes, a telemetry sample;
its measured size is not in any local copy: the overnight file holds one `run_start`, and the resumed one is on the box). **So a staged
job waits on average 3.5 minutes for the sweep to reach a safe point, and more than 10 minutes in about 1 request in 100** (the longest
leg is 11 minutes; the one longer, the first visit's `acceptance-rev8` leg of 36.5 minutes, holds 0.45 per cent of the 60-hour run's
instants for more than 20 minutes), **and a window loses that wait and the driver's restart each time it is preempted.** A job that
cannot accept the wait declares `preempt: never` and runs when the card is free.

## 3. Requirements

From Logan's words, the project's discipline (`CLAUDE.md`) and the records above. Each has the test a parcel can write.

| | requirement | from | a test that can fail |
|---|---|---|---|
| R1 | **Provenance.** Every job names the commit it ran and asserts it: the full SHA, HEAD equal to it, a clean status, the rtl/ tree, a string only that commit has; the build id the tools carry equals the tree's; the image's SHA-256 equals its `SHA256SUMS` and the registry's; the scheduler's own commit is recorded | `CLAUDE.md` "Before believing a remote build"; the 17 scripts | a clone one commit behind, a dirty clone, a stale tree whose HEAD is right, a wrong image: each refused by its name |
| R2 | **Honest records.** Every refusal is by name, every record is a fact, nothing passes silently: a step whose parser finds no verdict is `parse_error`, a skipped step is `skipped` with its reason, a dry run is never recorded as a card run | `CLAUDE.md` "The discipline that matters most here"; the driver's parsers | a log with its verdict line removed, doubled or contradicted by the exit status |
| R3 | **One owner per card.** A lock, not a look: one scheduler per machine, one job at a time per card, a guard (the driver's) as the second line against processes that do not take the lock; a person using the card takes a `hold` | section 2.1 "A lock"; `guard_probe.out` | a second scheduler refused; a second job on a busy card refused; a card user the lock does not know, caught by the guard |
| R4 | **Safe stops, and a resume.** A card process is never ended in the middle of a leg; a preempted window resumes to the same deadline; a restart finds what was running and says so; after an unclean end the first job reloads the image | `docs/HOSTAPI.md`; the driver's stop; section 2.8 | a stop requested mid-leg ends after the leg; a killed scheduler leaves a running job that the next start records as interrupted and does not re-run blindly |
| R5 | **Coexistence.** The box also runs the lead's gates and builds: a gate (CPU only) may run beside a window, a link of 25 to 30 GB may too, the gates and the pool both at `nice -n 10` today (section 2.2), and the scheduler records the load beside every job | `CLAUDE.md` "One heavy link at a time"; the driver's `beside` | a gate beside a window is recorded, not refused; the window's jobs are niced, and the load at the start and end of every job is in its record |
| R6 | **Windows.** The nightly window runs 18:00 to 08:00 box-local, daylight saving included; a staged run at any hour runs when the card is free, with its own deadline | Logan, 2026-10-21 | a window across midnight; a night 15 hours long; a job whose estimate exceeds the window refused `window-too-short` |
| R7 | **More cards.** A card has an id, a queue and a state; a job names a card or any; the scheduler's records carry the card everywhere, though v1 holds one | Logan, 2026-10-21 | a spec naming an unknown card refused; the record of a job has its card |
| R8 | **Coverage.** The window chooses its work from what its tree has not covered (section 2.6) and says why; a finding is a record, never coverage | Logan, 2026-10-21; `docs/studies/SWP-A-coverage.md` | the focus list changes when a slice is removed from the fold; a finding keeps its item unfinished |
| R9 | **Metrics on the card and on performance.** Per job and per window: what ran, how long, the outcome, rates by (op, image, tiles), sensors, the host's load; also when idle | Logan, 2026-10-21 | a window's summary equals the report's figures for the same file |
| R10 | **Replace the scripts, by parity first.** `box_nightly.sh`'s every line has a counterpart, and the scheduler's first night is checked against the script's record of the same kind | Logan, 2026-10-21 | a table of the script's lines against the scheduler's records (section 5.3) |
| R11 | **No persistent configuration without Logan's word.** No unit, no crontab; the scheduler is a process the lead launches until he says otherwise | the brief; the lead's note | nothing in the scheduler writes outside its own state root and the clones it made |
| R12 | **Only Logan's device submits.** The box user, over ssh; no network listener; a spec field reserved for a signature later | Logan's answer to question 6 | the scheduler opens no socket in v1 |
| R13 | **Tested as the driver is.** Against the driver's stand-in and its dry run, with a plant for each check and each plant red at its own check | `hw/test_card_stress.py`; `hw/test-sweep-judge.sh`'s standard | the plants (section 6) |
| R14 | **Bounded on disk.** A floor under which it starts nothing, a retention that deletes only what it created, by exact path | the box at 93 per cent | a full disk refuses `disk-floor`; the retention removes nothing it did not make |

## 4. Options, weighed

### 4.1 Architecture

Four shapes: the brief's three, and the one the facts of section 2 point to. The criteria are the requirements that separate them:
who owns the card between jobs (R3, R9), whether a staged run can arrive at 15:00 (R6), several cards (R7), exposure of verified
code to change (R13), whether it needs persistent configuration (R11), and the size of what must be right before the first night.

- **A: a long-running service per machine, a worker per card.** One process, one queue, one worker thread or process per card,
  state on disk so that it can die at any moment.
- **B: a timer-launched runner per window.** Cron or a systemd timer starts a program at 18:00 that runs one window and exits;
  a second path starts a staged run.
- **C: the driver grown into the scheduler.** `card_stress.py` takes a queue file, windows and cards.
- **D: a scheduler around the unchanged driver.** A's loop and queue; the driver is one kind of job, started as a subprocess with its
  documented flags and read through its documented files (section 2.5); a second kind of job runs named steps itself.

| | A service | B timer runner | C grown driver | D around the driver |
|---|---|---|---|---|
| owns the card between jobs, and samples it idle | yes | no: only while it runs | only while a run lives | yes |
| takes a staged run at 15:00 | yes | no: a second launcher and a lock between the two | polls a queue file inside a run that may be asleep in a guard wait of up to 4 h | yes |
| several cards | a worker each | a runner each | no: one `self.images`, one `--card`, one guard, process-global signals | a worker each |
| exposure of verified code | none (new code) | none | all: 2,532 lines under a suite of 584 checks and about 70 plants, 22.5 minutes with them | none in v1 (small driver parcels later) |
| persistent configuration | none if the lead launches it | a timer is a unit or a crontab | none | none if the lead launches it |
| what must be right before a first night | the most | the least | much (every added concern edits guarded code) | the most of the new code, none of the old |
| failure domain | one process owns everything; state on disk | a process a window: the cleanest | the run's | one process owns everything; the driver is its own |

**B** is the lead's nightly script with cron for a clock: it does not receive a staged run, does not sample the idle card, and cannot
grow to cards without becoming a loop over them, which is A. **C** is the cheapest to start and the most expensive to keep. The
driver's model is one run, one deadline, one directory, one card; its guard assumes it is the only owner; every concern added to it edits
code that the plants guard, and Logan's rule (only a regression or a wrong answer sends work back) makes the design that leaves
verified code alone the one that cannot be sent back for it. **A** and **D** are one design with and without the driver inside;
**D** is A that does not re-write the legs, the parsers, the sweep, the recovery ladder or the report. What D costs: a second
program; a contract with the driver (flags in, files out, below); and process helpers the driver keeps as methods of `Driver`
(`spawn`, `await_proc`, `kill_group`, `wrap` and `guard` are methods of `Driver`, and most read its state: `self.a`, `self.children`,
`self.hard`; READ), which the scheduler's own steps must re-state in about a hundred lines with their own plants until a later parcel
factors them out. **Recommended: D.**

**The contract with the driver, stated** so that a parcel can test it: the scheduler passes `--until`, `--out`, `--resume` where it
resumes, `--earlier-runs` for every other directory of the class, `--sweep-items` from the fold, `--rev8-images`, and the flags of the
job spec; it reads `metrics.jsonl` (`run_end`: reason and exit; `leg` records), `status.txt` (state, now), `STOPPED.txt` and the
exit status; it stops the driver by creating `$OUT/STOP` and waiting. It sends the driver no second signal in v1: the driver's first
SIGTERM or SIGINT is a stop after the leg running, and "send it again to terminate the leg" (READ, `install_signals`), which ends a
card leg in the middle and may poison its tile. The driver's legs and slices are in sessions of their own (`start_new_session`, READ,
`spawn`), so a signal to the driver does not reach them. A driver that ended with no `run_end` is `no_run_end`, never `pass`.

### 4.2 The job model

A job is a file: a JSON spec, validated whole before anything runs, with a unique id; a record of what happened to it; and an outcome
that is a name. Three shapes were weighed. **(a) A spec per script**, free-form shell: today's, with no parse, no verdict and a
summary file as the only record. **(b) Typed jobs of named steps**: a step is one of the driver's legs, a soak slice, `make vectors`,
the driver's dry tests or a quick driver run, each with its command template and the parser the driver already has (or one small new
one), so that a verdict is read from a printed line. **(c) A graph engine** with arbitrary dependencies, retries and fan-out: more
than one card and a handful of jobs a day need. **Recommended: (b)**, with `needs` as a chain only (a job that needs another
starts after that one ended `pass`; a failed need ends it `blocked`), and a free-form `argv` step refused by name (`step-unknown`)
unless the configuration allows it, in which case its verdict is `rc_only`, a word that every record and every `status` line carries.

The spec's fields (a design; `v` 1; a field it does not know is refused `spec-form`): `kind` (`window` or `staged`), `name`, `card`
(an id or `any`), `code` (`commit`, `source`, `assert`), `image` (a registry name; a window uses the three by the driver's weights),
`when` (`window` name, or `not_before` and `deadline` as epochs; none for "as soon as the card is free"), `priority`, `preempt`
(`safe-point` or `never`), `needs`, `estimate_s`, and `steps` (staged) or `driver` (window: `sweep_items` as `auto` or names, `resume`
as `auto` or a directory, `flags`). `owner` is filled from the operating-system user, and `signature` is reserved. Two illustrations,
**designs and not output**:

```json
{"v": 1, "kind": "window", "name": "nightly", "card": "u50-0",
 "code": {"commit": "<40 hex>", "source": "bundle:stress-0b7c959.bundle",
          "assert": {"clean": true, "rtl_tree": "44b963dd6ba2fcf99e002c5face5ca94aad4515c",
                     "content": [["hw/card_stress.py", "check_tree_in_dry_run", 1]]}},
 "when": {"window": "nightly"}, "priority": 10, "preempt": "safe-point",
 "preflight": ["vectors", "drytests", "driver-quick"],
 "driver": {"sweep_items": "auto", "resume": "auto", "flags": ["--host-workers", "8"]}}
```

```json
{"v": 1, "kind": "staged", "name": "ma card leg", "card": "u50-0", "image": "quad",
 "code": {"commit": "<40 hex>", "source": "bundle:m1-card.bundle",
          "assert": {"clean": true, "content": [["programs/acceptance.py", "^REV8_ROUTINES = ", 1]]}},
 "build": ["cft-segrun", "cft-audit", "libcft.so"], "priority": 50, "preempt": "never", "estimate_s": 900,
 "steps": [{"type": "acceptance-rev8", "only": ["lotkavolterra-rk4-tangent-fp64"], "target": "u50-rev8-quad"}]}
```

The second is `box_ma_card.sh` (58 lines) as a spec. **Priority and the window**: a higher number outranks a lower; a staged
job defaults to 50 and a window to 10, so a staged run outranks the sweep; ties go by submission time. A window job's deadline is the
window's end, and the driver's `--until` is that end in box-local time. **Preemption** is by the driver's stop (section 2.8): a
higher-priority job that arrives while a `safe-point` job runs causes `STOP`; the scheduler waits for the driver's `run_end`,
records `preempted` with the time it waited, runs the new job, and resumes the window at the same deadline. A `never` job is not
preempted. **Refusals, by name**, each a record and each shown by `status` (the table is section 5.4).

### 4.3 The code to run

A job names a full commit and a source. Three sources were weighed: **a bundle** the lead puts in a directory (today); **a fetch**
of the SHA from the remote (the repository is public, READ with `gh repo view`, and a fetch by SHA needs no credential, but whether the box
can reach github.com is not in any record, and I may not look); **a copied working tree**, rejected because it has no identity.
Recommended: the first two behind one `source` field, always as a clone checked out at `--detach <sha>` and asserted: the SHA as
typed is 40 hex and equals `git rev-parse` (the lead's rule: never a SHA from memory, which was refused twice), a clean status, the
rtl/ tree hash when the spec gives one, a count of each string the spec names, and every named ancestor an ancestor. A bundle made by
`git bundle create <file> <branch>` has no HEAD (the lead's ledger), so the clone is `-b <branch>` and the SHA checked out. A commit
that is not on the remote is allowed only with `allow_unpushed: true`, recorded in the job (the parcel card legs and the gates run on
unpushed commits: READ, the wave-9 gate at 9255ab8 before the push).

**Builds, and whether they are cached.** The driver's build step runs inside every driver run, `make -C host XRT=1 XRT_ROOT=...` for
six named targets and ten `ldd` checks, and on a clone already built it took **0 s** (READ in the overnight run's `build` record: its
`make` step says "rc 0 in 0 s", the smoke having built the clone before). So the cache is the **clone directory, one per full SHA**, kept seven days and removed by its exact path
(about 70 MB each, section 2.7); no second cache is needed. A staged job lists the targets it needs (`box_ma_card.sh` built three) and the
scheduler asserts `ldd` for each and records the build id. Variants (`SOAK_CHUNK=n soak-chunk`, DR3's `--sweep-chunk`) have
distinct product names in the same clone (READ, CK's entry). Two rules from the record: **`make vectors` first, the dry tests in a clone
nothing has built** (the `buildreal` trap), so a step `drytests` is refused `clone-built` when the clone holds ignored products the
scheduler did not make in this job; and **`XRT=1` is never defaulted**: a build without it is refused `xrt-not-linked` by the `ldd`
check, which is how `no such device` was once read as a broken environment (`CLAUDE.md`). The revision-8 compile cache
(`--rev8-images`, a directory of compiled images and banks) is held to the record's digests by `acceptance.py` itself (READ), so it
needs no key of the scheduler's.

### 4.4 Cards

- **Discovery.** v1 lists cards in its configuration (an id, the user function's address, the platform, the images allowed) and
  checks each at start with `xbutil|xrt-smi examine -d ADDRESS`, as the driver's advisory step does; one that does not answer is
  `unavailable`, named, and does not stop the scheduler. Reading the list of cards out of `xbutil examine` is deferred: the driver
  treats even this call as advisory because "xrt-smi 2.19's device-info parser has died on this card before" (READ, `build_tools`
  and docs/VALIDATION.md, 2026-09-08), and the format of the list is in no local record.
- **Queues.** A job names a card or `any`; a worker takes the highest-priority eligible job (its window open, its needs `pass`, its
  image on a card whose platform builds it); `status` shows each card's queue.
- **Images.** The registry holds, per image: name, path, SHA-256, tiles, target and platform (what `IMAGES` holds today, with the
  SHA256SUMS check). The scheduler keeps the image the card last opened, from its own records; a different image is a *reload* it
  records (five to nine seconds, section 2.3), and after an unclean end the next job on the card starts with the driver's own cure,
  `dt-i` on another image and then on the wanted one (two legs of 6.4 s mean and 10.5 s maximum, loads included, so 13 to 21 s,
  COMPUTED from `latency.out`), recorded as a `recovery` step.
- **Health.** A card is `ready`, `busy`, `held` (a person), `suspect` (a job ended `no_device` or `timeout`: the next job is preceded
  by the recovery) or `quarantined`. Inside a window the driver's ladder runs (retry after 120 s, a reload from the second failure,
  a stop at six in a row); the scheduler quarantines on the driver's `card_lost` stop, or after two consecutive jobs ending
  `no_device` or `timeout`. A quarantined card is released by `cft-sched card release ID --verify`, which runs `dt-i` on each image
  it holds and releases only if each passes; the release is a record with who and why. No job is sent to a quarantined card.
- **What several cards need that does not exist.** `cft_open(artifact, index, ...)` selects a device and the soak tools,
  `device-test` and the rest pass 0 (READ), so a second card is unreachable from the existing tools until they take a device selector
  (an environment variable or an option), which is a change to the tools and not to the scheduler; and a second card running one
  item's slices needs a share of its interval (the study's static partition: chunk number modulo D) that the driver does not accept
  (no `--lo`/`--hi`). Both belong to a later parcel (S6), and both are why v1 builds card ids into every record and claims no more.

### 4.5 Coverage

| | what it is | cost | does it answer "wherever it hasn't reached yet" |
|---|---|---|---|
| (a) **none** | the lead's list and directory name in a script | nothing | by hand, and the list empties in about a week (section 2.6) |
| (b) **a fold of the runs' own records and a focus list** | a derived extract per run (intervals by item and class, from `metrics.jsonl`, with its sources' SHA-256 and the command that remakes it), the union by (item, class), the finding rule, the focus list, the directory rule | S4: 1,200 to 2,000 lines (BELIEVED) | yes, for the finite items, per tree |
| (c) **rank 6 now** | the campaign, strata, enumeration, digests and the signed fold | weeks (the study) | yes, and for the 64-bit spaces; most of it for accumulation Logan placed after the math round |
| (d) **SQLite** | an index in a database | small | the same as (b), with a second truth to keep honest |

**Recommended: (b)**, with the seam of section 2.6: the planner asks `unfinished(class)`. The extract is the pattern of
`python/figure_extracts.py` (an extract is not trusted because it is stored; `verify` remakes it and compares bytes), so a stale or
edited one is found by name. Two things (b) needs outside the scheduler: the **class-aware planner in the driver** (DR4), so that
`--resume` counts a host item's coverage by the host/ tree and a tile item's by the rtl/ tree, as the report does; and, until it
exists, `status` names the gap ("host class changed: N items not re-run").

### 4.6 The metrics store

**(a) Append-only JSONL**, as the driver's: a record is a fact on its date, readable by the report, the figures and the exporter,
rotated by directory. **(b) SQLite**: queries by item, tree, image and time, writers and readers in one file, and a second truth
whose rows must be rebuilt from the records anyway. **(c) Both**: the JSONL is the record, a database is a derived index that can be
deleted and rebuilt. Recommended: **JSONL, with derived extracts**; add (c) the day a reader needs a query the extracts cannot answer,
and not before: at a year of records (0.6 to 0.7 GB) a rebuild is a linear parse of about the report's speed, near 40 s (COMPUTED from
DR2's 0.49 s on 8 MB, BELIEVED linear).

What is kept (R9), each as records in the job's directory: the job's events (`code`, `build`, `image`, `step`, `preempted`,
`resumed`, `end` with its outcome); every step's leg record in the driver's leg schema (counts from the parser, `rate`, the image's
SHA-256, the log); the host's load and free disk at the start and end; for a window, the report's `--json` summary and the derived
coverage extract. For the card between jobs, a **compact sample every 15 minutes** (the six values the figures read, the load and
the memory: 227 B, COMPUTED) beside the driver's own 5,446 B sample every 5 minutes: 96 a day is 21.8 KB a day and 8.0 MB a year
(COMPUTED), against 570 MB a year for the full record at the driver's cadence; the idle sampler stops while a job holds the card
(the driver samples then, and asks "one question at a time"). The project's figures read one run's file by design (`figure_extracts.py
stress` is a committed reduction with the raw file's SHA-256); a figure of many nights is a new extract, and v1 does not build one.
**Performance** is the leg records' rates and durations by (op, image,
tiles, commit) with the host's load beside each: the lead's own readings (the rate of `scaleb64`, which was bimodal across identical
runs, and the default `rint32`, which took 25 to 35 s for one slice; docs/VALIDATION.md, the pass-size experiment) say these are distributions, so `report` gives a median and a spread over a stated count of nights and says "drifted"
only against that spread; v1 records and reports, and takes no action on drift. **Retention against the disk:** clones seven days;
passing legs' logs (already gzipped) a configurable age; records never; a record of every deletion batch with its paths; the floor
refuses new jobs; `metrics.jsonl` is rotated by directory, a new one when the tile class changes or the file passes a size, so that
the report's 120-second refresh stays far inside its limit (section 2.5).

### 4.7 The interface

**A file queue** (`queue/<id>.json`, written by a temporary file and a rename; the worker claims by renaming into `running/`, which
is atomic on one filesystem; `cancel` and `hold` are records and control files beside, as the driver's `STOP` is), **a local socket**
(request and answer, a status that never reads a file, and a listener that R12 says v1 does not open), or **SQLite as the queue**
(transactions, a second truth, and WAL files in a directory several processes touch). Recommended: **the file queue**. `submit`,
`list`, `status` and `report` need no running scheduler, so a submit never fails because the service is down; the idiom is the
lead's own (`touch $OUT/STOP`). The verbs of v1: `run` (the service, launched by the lead), `submit FILE`, `list`, `status [ID]`,
`cancel ID [--force]`, `report ID`, `hold CARD [--for DURATION]` and `release CARD`, `card status|release ID --verify`, and `verify`
(remake an extract and compare). `status` prints, per card, its state, the job on it, the window, the last sample and its queue, and
the refusals since the last look, each by name. **Who may submit:** the box user, over ssh with a key; the state root and its queue are
mode 0700; no socket in v1. Logan's answer was "At the moment only my device, though built to support a signing key would be good"; the spec
reserves `signature`, and the verifier of it is not built (question 10). The lead is the only agent that touches the box, so the lead
submits.

### 4.8 Deployment on the box

Units and crontabs are persistent configuration, which is Logan's decision (R11). **A process the lead launches** (`setsid nohup`, as
tonight's script is: PID 217808): nothing persists; a reboot or a power loss leaves no scheduler until someone notices, which `status` and a
`missed-window` record at the next start make visible, naming the gap from the last heartbeat. **A systemd user unit** with
`loginctl enable-linger` restarts it after a reboot; **cron `@reboot` with `flock`** does the same with less. Both are an install on the box
that a parcel can write and may not run. Recommended: **the lead launches it for v1**, a unit file is written in the operator's page and
not installed, and Logan decides after two clean weeks (question 4). One scheduler per machine is enforced by `flock` on a lock file
the service holds for its life (auto-released when it dies, unlike a pid file), and the card's lock is held by the process tree of the job
(below), not by the scheduler.

### 4.9 Failure

| failure | what the scheduler sees | what it does | what it records |
|---|---|---|---|
| the card stops answering mid-window | the driver's ladder, then exit 3 with `STOPPED.txt` reason `card_lost` | quarantines the card; the job ends `card_lost` | the driver's records, and the card's state change with its cause |
| a leg hangs | the driver's `timeout --kill-after` (300 to 3,600 s a leg); a staged step's own | the driver or the step ends it and records `timeout` | the leg as `timeout`, the log whole |
| the driver is silent | a live PID and a `status.txt` older than an hour (it has silent phases: a guard wait up to 4 h, a build up to 40 min) | warns in `status`; never kills by itself, because a killed leg poisons a tile | a `silent` warning with the age |
| a reboot or a power loss | on the next start, a `running/` job whose PID is gone | marks it `interrupted: host restart`, the card `suspect` (the next job reloads), and a `missed-window` if a window passed | the interrupted job, the card's state, the gap |
| the scheduler dies | the driver, which ignores SIGHUP and has its own session, keeps running | a restarted scheduler adopts it (the PID file and the driver's argv, never a pattern) or finds `run_end` | `adopted` or `no_run_end` |
| the disk fills | the free space at the start of each job (the driver's own floor of 5 GB inside a window, exit 3 `disk_floor`) | refuses `disk-floor`; deletes only what it made, by exact path, at the retention's age | the refusal, and every deletion batch |
| a record cannot be written | an `OSError` on append | stops the job at the next safe point: nothing runs unrecorded | `record-write-failed` where it can still be written |
| the clock moves | a window computed from the zone with `zoneinfo`; deadlines are epochs; durations are monotonic | a night of 15 or 13 hours is a night of that length; a step of the clock never extends a deadline by more than itself | the window's start and end as epochs |
| a second card user appears | the card lock is held by the job's process tree; the guard sees the user | waits as the driver does (`card-busy-foreign` after the wait's limit); never kills | `guard_wait`, `guard_clear` |

**The card lock lives in the job's process tree**: the scheduler starts a window as `flock CARDLOCK driver ...`, so the lock is held by a
process that lasts exactly as long as the card's user, and it survives the scheduler's death (a restarted scheduler cannot take the card
until the driver ends, and can adopt the run); for a staged step the scheduler holds the lock itself for the step. A person who wants the card takes
`cft-sched hold`, which takes the same lock. (`flock(1)` is util-linux, BELIEVED present on the box's Ubuntu 24.04.)

## 5. The recommendation: v1

### 5.1 What it is

One Python program, standard library only (the driver's rule is Python 3.10 or later, WSL's is 3.10 and `tomllib` is 3.11+, so the configuration is JSON), in `hw/sched/`
beside the driver whose library it imports for the parsers and the coverage arithmetic, with `hw/test_sched.py` and `hw/test-sched.sh`
shaped like the driver's, and an operator's page `docs/SCHEDULER.md`. State lives in a root outside every checkout (for example
`/data/cft-sched/`, where the driver already puts its runs; a checkout would make the tree untracked and change the build id
`hw/card-segrun.sh` asserts). Layout:

```
<root>/config.json        cards, the image registry, the windows and their zone, the floors, the retention (read at start)
<root>/lock               held by the service for its life
<root>/queue/ID.json      submitted specs
<root>/running/ID/        the job while it runs: spec, job.jsonl, the PID, STOP
<root>/jobs/ID/           the job after: spec.json, job.jsonl, the driver's run directory or the steps' legs, SHA256SUMS
<root>/cards/CARD/        card.jsonl (state changes, compact idle samples), CARDLOCK
<root>/clones/SHA/        the clone cache
<root>/extracts/          derived: coverage by run, window summaries, each with its sources' SHA-256 and its remake command
```

**What it reuses of the driver, and how** (the brief asks how; each row is a choice, and the contract of section 4.1 is what a window job rests on):

| the driver's piece | in a window job | in a staged job |
|---|---|---|
| the legs and the soak slice | run by the driver, unchanged | the same commands as named steps: the registry holds the driver's command templates, and a test holds each equal to `leg_cmd`'s |
| the parsers | the driver's own | imported from the scheduler's checkout (`card_stress_lib.parse_*`); a tool whose output moved is a `parse_error`, never a pass |
| the guard | the driver's own, behind the card lock | `card_user` and `find_card_users` imported, with the lock |
| telemetry | the driver's, every 300 s | the scheduler samples before and after a job, and every 15 minutes when idle, with the same `examine` call |
| the metrics schema | the driver's `metrics.jsonl` | the legs in the driver's leg schema, in the job's own file |
| the recovery ladder | the driver's, inside the run | the scheduler's `recovery` step (`dt-i` on another image, then this one) and its quarantine across jobs |
| the build step | the driver's, inside every run | the scheduler's `code` and `build` stage, the same targets, `ldd` and build id |
| the stand-in and the dry run | `--dry-run` | wraps each step, as `Driver.standin` does |
| the report | the driver's after each cycle, and `--json` for the summary | the report on a staged job's file |

### 5.2 A night

Timed from the lead's own preamble (READ, the two summaries) and the driver's runs (MEASURED, `latency.out`, `volumes.out`):

| step | what | time |
|---|---|---|
| 18:00 | the window opens; the window job is claimed; the commit is cloned and asserted (seconds, BELIEVED); the tools are built by the first driver run in the clone, the smoke, and a later `make` on that clone takes 0 s (READ) | seconds, then inside the smoke |
| preflight | `make vectors` and `sha256sum -c` 126 to 128 s; the driver's dry tests 290 s (481 checks) and 456 s (584); the driver's `--quick` smoke on the card 958 to 1,047 s | 1,376 and 1,629 s in the two nights recorded: 2.7 and 3.2 per cent of 14 hours (COMPUTED) |
| ~18:25 | the driver resumes the class's run directory with `--until 08:00` and the focus list | 13 h 35 m |
| 08:00 | the deadline; the driver ends 31 s (night 1) and 74 s (the 60-hour run) after it (READ, the reports); the card is idle; the scheduler refreshes the report, writes the extracts and the sums | about a minute |
| any hour | a staged job arrives: `STOP`, a wait of 3.5 minutes on average and 8.7 at the 95th percentile (section 2.8), the job, the resume | the job, and the driver's restart |

### 5.3 What it replaces first, line by line

`box_nightly.sh`, 56 lines, because it is what the lead launches every evening and because Logan's words describe it:

| the script | the scheduler |
|---|---|
| arguments: SHA, bundle, tag, start, until | `code.commit`, `code.source`, the job's `name`, the window |
| `W`, `SRC`, `OUT`, `SMOKE`, the summary file | the state root, `clones/SHA`, the directory the class rule picks, `jobs/ID` |
| `ITEMS=` the 22 names, in three scripts | the focus list, from the fold |
| `say`, `done_`, "=== done" | `job.jsonl` and the end record, whose last word is the outcome |
| refuse if the outputs exist; parse START and UNTIL | the refusals `job-exists`, `spec-form`, `window-bad` |
| `sleep $(( ts - now ))` | the window's calendar, in the box's zone |
| `$OUT/metrics.jsonl` must exist; `STOP` must not | the directory rule; the refusal `stop-file-present` |
| `pgrep -fc 'card_stress.py\|...'` | the card lock and the driver's guard |
| clone, `checkout --detach`, HEAD, status, rtl, two greps | the `code` stage |
| `make vectors`, `sha256sum -c` | the step `vectors` |
| the dry tests, the known flakes tolerated by name | the step `drytests`, with the allow-list in the spec |
| the `--quick` smoke | the step `driver-quick` |
| the long run, `done_ $rc` | the window's driver, its outcome from `run_end` |

Then `box_resume_stress.sh` and `box_overnight.sh` (the same job with another commit), then the card-leg scripts as staged specs
(`box_ma_card.sh`, `box_chunk_card.sh`, `box_smoke.sh`, `box_rint_ab.sh`, the pass-size runs), then, last and optionally, the gates
(`box_wave9_gate.sh`: 184 minutes, CPU only, no card) as staged jobs that name no card, for sequencing and records alone. `copy_wave9.sh`
becomes the sums the scheduler writes at a job's end (the desktop still pulls, with `scp`, and checks them).

### 5.4 Refusals, by name

Every refusal is a record `{"type": "refused", "name": ..., "why": ...}` and a line in `status`; a job is never dropped without one.
The names, each with what raises it (a design; the plants of section 6 hold each to its check): `spec-form` (not JSON, a field
missing, unknown or the wrong type), `spec-version`, `job-exists`; `commit-not-full`, `commit-missing`, `commit-unpushed` (not on the
remote, without `allow_unpushed`), `head-mismatch`, `tree-dirty`, `rtl-mismatch`, `content-missing` (a string not found the stated
number of times), `ancestor-missing`; `clone-built` (the dry tests in a built clone), `build-failed`, `xrt-not-linked`,
`build-id-mismatch`; `image-unknown`, `image-digest` (the file's SHA-256 against the registry and the `SHA256SUMS`), `image-tiles`,
`image-platform`; `card-unknown`, `card-unavailable`, `card-quarantined`, `card-held`, `card-busy-foreign`; `window-closed`,
`window-bad`, `window-too-short` (the estimate exceeds the window), `deadline-passed`; `step-unknown`, `parser-unknown`,
`no-verdict`, `rc-only` (a verdict that is only an exit status, labelled so everywhere); `disk-floor`, `record-write-failed`;
`lock-held` (a second scheduler), `queue-corrupt`, `stop-file-present`, `dry-run-as-card` (a stand-in's output offered as a card's).

### 5.5 What is deferred

Several cards (S6, with the device selector and the partition); a served session as a job; load shedding (lowering `--host-workers`
when the box is busy: recorded, not acted on); a coverage ledger beyond one fold (rank 6, after the math round); signed submissions;
any listener; discovery of cards by parsing `xbutil`; a unit or a crontab; automatic action on performance drift; notifications (it
sends nothing to anyone: the lead reads `status`); factoring the driver's process helpers out for both programs.

## 6. A build plan

Parcels in order, each with a BELIEVED size in changed lines (tests and plants included), what it is tested with, and what it touches.
The last wave's parcels went past their ceilings by about 1.2 to 10 times (READ, docs/VALIDATION.md, the coverage wave's record: "Most
went past their briefs' size ceilings"), so each brief should carry a ceiling and a time box, as the lead's own note on scope says.
This study's build is not on the math round's path (Logan: "since its not specific to any prior steps"), but DR4 and S4 touch
`hw/card_stress*.py`, which DR3 is about to change, so they follow DR3's merge.

| parcel | what it builds | size (BELIEVED) | after |
|---|---|---|---|
| **S1, the core** | the spec (v1; an unknown field refused), the refusals' table, the state root and its configuration, the file queue (atomic submit, claim by rename, cancel), the service's lock and the card's lock, `job.jsonl` and the end record whose last word is an outcome, the CLI's `submit`, `list`, `status`, `cancel`, `hold`, `release`; a fake runner | 1,200 to 1,800 | none |
| **S2, the runner** | the clone and its assertions from a bundle or the remote, the build with the `ldd` and build-id checks, the image registry and its digest check, the guard (the driver's own `card_user` and `find_card_users`, imported), `run_step` (niced, under `timeout --kill-after`, a process group stopped by PID), the step registry (the driver's legs, a soak slice, `vectors`, `drytests`, `driver-quick`) with the driver's parsers and the two small new ones, `rc_only` labelled | 1,500 to 2,200 | S1 |
| **S3, the windows** | the calendar (a zone, daylight saving), the window job (the driver under `flock`), the preflight chain, preemption by `STOP` and the resume at the same deadline, the silent-driver warning, restart recovery (adoption, `interrupted`, `missed-window`), the card's states and its quarantine, the reload after an unclean end | 1,500 to 2,500 | S2 |
| **DR4, the driver** | `--resume` counts a tile item's coverage by the rtl/ tree and a host item's by the host/ tree and compiler, as the report does; `tree_changed` also for host/; nothing else of the driver changes | 300 to 600 | DR3 merged |
| **S4, metrics and coverage** | the derived extracts and `verify`, the fold by (item, class), the finding rule, the focus list, the directory rule, the idle sampler, retention, the window summary from `report --json`, `report` | 1,200 to 2,000 | S3 and DR4 |
| **S5, the switch** | `docs/SCHEDULER.md`, the mapping of section 5.3 made true, the unit file written and not installed; the lead's runs below | docs 300 to 500 | S4 |
| **S6, several cards** | a device selector in the tools and the library, per-card workers, discovery, an interval share for two cards on one item | 800 to 1,500 | a second card |

S1 through S4 and DR4 sum to 5,700 to 9,100 lines (COMPUTED from the ranges), against 9,132 lines for the driver, library, report,
stand-in and test together (MEASURED, section 2.1). A Sonnet author's first pass took 54 to 193 minutes in the last wave and a Haiku
verifier's 14 to 54 (READ, the same record), which puts each of S1 to S4 at two to four hours of author time and one to two verifier
passes (BELIEVED), about two weeks of calendar if they run in sequence with the lead's gates between (BELIEVED). S1 and DR4 touch different
files and can run together.

**How each is tested**, as the driver is: a suite `hw/test-sched.sh` of groups (`spec`, `queue`, `locks`, `code`, `build`, `steps`,
`guard`, `window`, `preempt`, `restart`, `cards`, `extracts`, `fold`, `retention`, then `plants`), run on both interpreters, Windows
(no `nice`, `timeout` or `flock`: those groups skipped by name) and WSL (all of them), niced, one heavy process at a time. **The card is
never involved**: a step's command is wrapped by the driver's stand-in exactly as `Driver.standin` wraps it (it prints the tools' real
verdict lines and fails, hangs, loses the device or disagrees on a schedule), a window runs `card_stress.py --dry-run`, which is the
driver's own dry run against its stand-in, and a clone is made from a scratch repository, as `scn_pool_tree` does. **Plants**: a defect
put back into a copy of the scheduler, whose scenario must fail at its own check, and the lessons of DR2 apply (read the plants' output
for "applies ... found 0 times" and "caught by nothing"). The plants, by parcel:

| parcel | the defect planted, each to be caught at the check written for it |
|---|---|
| S1 | a second service allowed; a claim that two workers can win; an unknown field accepted; a refused job that leaves no record; a job id reused; the card lock not held for the job |
| S2 | HEAD not asserted; a dirty status not asserted; a string's count ignored; the rtl/ tree not compared; the `ldd` check dropped; the build id not compared; the image digest not compared; the guard blind to an idle `cft-serve`; the guard counting its own shell; a parser that passes a log with no verdict; the exit status ignored; the dry tests allowed in a built clone; a stand-in's output recorded as a card's; a timeout not enforced; a process stopped by pattern and not by PID |
| S3 | the window's end not enforced; a preemption that ends a leg instead of asking the driver to stop; a resume that serves covered slices again; a stale `running` job taken for a live one after a restart; the first job after an unclean end skipping the reload; a night's length taken as 14 hours on the changed-clock night; a `never` job preempted; a card that is lost and not quarantined; a cancel that does not stop the driver |
| DR4 | a host slice of another host/ tree counted; a tile slice of another rtl/ tree counted; `tree_changed` blind to host/ |
| S4 | an extract used without its sources' SHA-256 being checked; the fold joining two tile classes; a finding counted as coverage; a complete item in the focus list; the retention deleting a path it did not make; the idle sampler running during a job; the disk floor ignored; a window summary that disagrees with the report |

**What touches the card: only the lead's runs, and none before the suite is green on both interpreters.** In order: the suite on the box
in a fresh clone before anything is built (no card: the stand-in); a card smoke through the scheduler, a window job whose driver is `--quick`
(the driver's own smoke took 958 s and 1,047 s on the two nights recorded); one night with `box_nightly.sh` not launched, the
scheduler's record put beside the script's record of the night before; one staged job by day, the pass-size card check of
`box_chunk_card.sh` (713 s, 35 records, READ) as a spec, compared record for record with its run of 2026-10-20; and, for S6 only, the
lead's read-only `xbutil examine` on the box to show the list's format. Parcels and verifiers never run any of them, and never touch
amd-arc-box.

## 7. Questions for Logan

Each with the study's recommendation and what the answer changes.

1. **The name and the layer.** Call it the card scheduler, the command `cft-sched`, the code `hw/sched/`, and call the library's
   `run_job` "the tile scheduler" in new text (section 1). *Recommended: yes.* It changes names only, and ends the collision with
   the ROADMAP's plan of record.
2. **The architecture.** A scheduler process around the unchanged driver (4.1's D) over a timer-launched runner (B) or the driver
   grown into the scheduler (C). *Recommended: D.* It changes whether the driver's 2,532 lines, its 584 checks and its plants stay
   untouched in v1 (D) or are edited for a queue, windows and cards (C), and whether staged runs and idle metrics exist at all (B has neither).
3. **The scope of v1.** One card, the nightly window and staged runs, card ids in every record; several cards, a coverage ledger beyond
   one fold, served sessions, load shedding and signed submissions deferred (section 5.5). *Recommended: yes.* It decides that
   S6 is not built until a second card exists.
4. **Deployment.** The lead launches the scheduler for v1 as it launches tonight's script, with no unit and no crontab (persistent
   configuration is yours). May a systemd user unit with linger, or cron `@reboot` with `flock`, be installed after two clean weeks?
   *Recommended: lead-launched now, ask again then.* It changes whether a reboot costs a night (visible in `status` and a
   `missed-window` record, but a night all the same) and whether anything persists on the box.
5. **Priority.** May a staged run outrank the nightly sweep and stop it at a safe point (a wait of 3.5 minutes on average, 8.7 at the 95th
   percentile and about 11 at the longest leg, and 36.5 minutes the one time, a first visit's `acceptance-rev8`), the window resuming at
   the same deadline? Or does the window win and a staged run wait for 08:00? And may a person using the card by hand take `cft-sched hold` and not
   start tools beside the scheduler? *Recommended: a staged run outranks, a job that cannot wait says `preempt: never`, and a person
   takes `hold`.* It changes what the lead can do by night, and costs the window the wait and the driver's restart each time.
6. **When the finite items are done.** About 2026-10-27 the four `scaleb32-wide` items finish (BELIEVED, section 2.6) and the scripted list
   empties. What does the window do then: the battery cycles and the random items with new draws (the detection floor improves as 1 over the
   number of independent weekends, the sweep study's 5.1), the battery only, or nothing? And are new finite items (parcel DR3's) taken as they appear in the
   catalog? *Recommended: the battery and the random items, new finite items first as they appear, and everything again on a new rtl/ tree
   (6 to 9 nights).* It changes the planner's fallback, and whether the card idles most nights from the end of the month.
7. **How much of the preamble, each night.** `make vectors`, the driver's dry tests and a `--quick` smoke take 23 to 27 minutes, 2.7 to 3.2
   per cent of the window. Keep all of it every night, or the vectors and the dry tests only when the commit changed and the smoke every
   night as the card's health check? *Recommended: the second* (it saves 416 to 584 s a night when nothing changed, COMPUTED from
   126 to 128 s and 290 to 456 s). It changes the window's length by 3 per cent at most.
8. **Coverage, and what a host item is evidence about.** Build the minimal fold and focus list (S4) and the class-aware planner in the driver (DR4)
   after DR3, and leave the rest of rank 6 until after the math round, as decided? And key a host item by the whole host/ tree and the
   compiler, as the report does (15 commits changed host/ and none changed the library in the 24 hours between 881bbcb and 0b7c959;
   re-covering the 18 host exhaustive items costs about 0.5 hours of the pool), or by the library's own source and the soak tool? *Recommended: yes to the first; keep the coarse key
   for now and change it if it churns, since it is cheap.* It decides DR4's key, how much CPU a host/ commit costs, and what "complete"
   means for a host item.
9. **The code the box runs.** May the box fetch a pushed commit by its SHA from the public remote (it needs outbound access and no
   credential; whether it has the access is not in any record, and the lead can check), or stay on bundles the lead puts in a directory?
   And may a job run an unpushed commit when it says `allow_unpushed`, recorded in the job? *Recommended: both sources behind one field, and
   unpushed allowed and recorded* (the gates and the parcels' card legs run on unpushed commits today). It changes the lead's launch
   step and the refusal `commit-unpushed`.
10. **Who submits, and signing.** Only the box user over ssh, no listener (recommended). Reserve a `signature` field in the spec and
    build no verifier now, or sign every submission from the start with the key format the signed records already use? *Recommended:
    reserve the field; build the verifier when a second owner exists* (the sweep study's rank 10). It changes whether a key sits on the
    box and whether any socket is ever opened.
11. **Retention, the disk and idle sampling.** The box's `/data` is 93 per cent full and a year of run directories is about 2.2 GB. May the
    scheduler delete, by exact path and with a record of each batch, only its own clones after seven days and passing legs' logs after 180
    days, and keep every record? Should the driver's 5 GB floor rise? Who frees `/data/Xilinx` and the other large tenants? And, when
    idle, a compact sample every 15 minutes (8 MB a year) or none? *Recommended: yes to the retention, a 15-minute compact sample, the
    floor left until a week of its use is read, and the large tenants yours.* It changes the retention's configuration and the idle
    record's size.
12. **Several cards.** Is a second card expected soon enough that the device selector in the tools and library (S6) should come before DR4
    and S4? And may the lead run a read-only `xbutil examine` on the box to show the format of the device list (agents may not)?
    *Recommended: after, unless a card is on its way, and yes to the probe.* It changes S6's place in the order and whether discovery is
    read or configured.
13. **A finding.** When a slice finds a mismatch, the driver records it with its operands and goes on. May the window do the same, with
    `status` marking the epoch "needs review" and the item never "complete", or should it pause until the lead has looked? *Recommended: go
    on, and mark it.* It changes the outcome name `done-with-findings` and whether the card runs after a finding.

## 8. What this study does not establish

1. **Nothing ran on the box or the card.** Every figure about them is from a record. The second night's records (to 08:00 on 2026-10-21)
   are on the box and in no local copy; the driver's restart cost on a resume, and the box's outbound access, `flock(1)`, the zone's name and its daylight-saving rule are unrecorded.
2. **The finite campaign's end is a projection.** It rests on one file's slot-seconds and the lead's two readings of the second night, and
   assumes the pace holds (BELIEVED). The two paces differ by about 30 per cent (0.84 from the first night's slot-seconds, 1.10 read on the second),
   which the first night's waves explain in part: they mixed fast and slow items and idled slots (the legs ran 70 per cent of the slot-seconds the waves held).
3. **The waits for a safe point** are from two runs of the driver before the host pool and before the new finite items; the class items run
   lane by lane (about 2.5 minutes an attribute for `rint64-class` on one tile, DR3's brief) and will change the waves' lengths.
4. **The guard is not a lock** is read from the code; no two drivers were run. The scripts' guard is compared with the driver's on twelve
   synthetic command lines and a synthetic table, not on the box.
5. **The log volume rests on one `du`** (24 MB at 57 hours, the lead's), the host pool's logs and its rates are unmeasured (the 18 host
   items' 4.3 core-hours is at card-run rates of host code), and the disk series is `/data`'s, where other writers dominate.
6. **The script census counts patterns in text** ("mentions or does"); which scripts use the card is read from their headers, not run.
7. **The design is a design.** The claims that it will work, its sizes and its times are BELIEVED; the refusal names and the plants are
   proposals a parcel may improve; the specs shown are illustrations and no record of a run.
8. **Version skew.** The scheduler imports the parsers of its own checkout while a job's tools come from the job's commit; a tool whose
   output changed is a `parse_error`, loudly, and never a pass, but the window's own report is read from the job's clone to avoid the same
   skew. A parser from the job's clone is the alternative (a later parcel).
9. **Several cards** rest on `cft_open`'s index and the tools' constant 0 (READ); whether XRT keeps its device indices stable across a reboot
   is not known (BELIEVED not guaranteed).
10. **Performance drift** has two runs to look at and no baseline; the scheduler records and reports, and this study sets no threshold.

## 9. The instruments and their captured runs

All in `docs/studies/sched-a/`, each with its capture beside it. They read local copies or call the driver's own functions on synthetic
input, change and build nothing under `host/`, `hw/`, `rtl/`, `python/` or `programs/`, print no path, exit nonzero if a check fails, and
carry controls that must go red (the `CONTROL` lines). Every script runs as `python -B -I SCRIPT ARGS`; the inputs are the two
`metrics.jsonl` files named in the header (a `LABEL=FILE` argument each), and for `script_census.py` the lead's directory of box scripts.

| script | measures | capture | run |
|---|---|---|---|
| `volumes.py` | a run's file by record type, per hour, per 14-hour night and per year; the compact telemetry record; the free disk and the host's load and memory as the driver sampled them; three damaged copies each turn a check red | `volumes.out` | `volumes.py LABEL=FILE ... --controls` (0.3 s) |
| `latency.py` | the wait of a stop request for the end of the leg or wave running, exact and by a seeded Monte Carlo; waves held to the sum of 1/jobs; a wrong mean and a wrong grouping each caught | `latency.out` | `latency.py LABEL=FILE ... --controls` (11 s) |
| `guard_probe.py` | the driver's `card_user` and `find_card_users` on twelve command lines and a table of processes, against the lead's `pgrep -fc` pattern, which fails six of the twelve | `guard_probe.out` | `guard_probe.py --controls` (0.2 s) |
| `script_census.py` | what each of the lead's 17 scripts does, as columns, and the distinct guard patterns; a pattern that cannot match and a renamed `pgrep` are caught | `script_census.out` | `script_census.py DIR --controls` (0.1 s) |
| `coverage_state.py` | each exhaustive item's coverage and first gap by the driver's `sweep_coverage` and `first_gap`; the trees derived with `git rev-parse`; the fold by class; the pace and the nights; the cost of covering the tile and host items again; the union held to an independent merge, a removed slice and a wrong sum caught | `coverage_state.out` | `coverage_state.py LABEL=FILE ... --controls` (0.4 s; needs `git` and this repository) |

## 10. What was read

All READ: `CLAUDE.md`; `hw/card-stress.sh`, `hw/card_stress.py` (whole), `hw/card_stress_lib.py` (whole), `hw/card_stress_report.py` (its
docstring, `_sweep`, `_tree_class`, `_trees`, `_uptime`'s head), `hw/card_stress_standin.py` (its docstring), `hw/test_card_stress.py` (its
docstring and function list), `hw/test-card-stress.sh`, `hw/sweep_record.py` (its docstring and refusals); `docs/CARDDAY.md` ("The long run" and
its subsections, "The build trees"), `docs/REMOTE.md` (the scope, the server), `docs/HOSTAPI.md` ("A tile a run was abandoned on"),
`docs/BRINGUP.md` (the lab map, the shell), `docs/SWEEP-RECORDS.md`, `verify/run.sh` (its header), `docs/ROADMAP.md`
(the word "scheduler"), `docs/VALIDATION.md` (the entries of SG, DR2, CK and the coverage wave's closing record, the card half of 2026-09-18, the
stress driver's entry, the pass-size experiment), `docs/studies/SWP-A-coverage.md` (whole); `python/figure_extracts.py` and
`python/project_figures.py` (the stress extract and its figures); `programs/acceptance.py` (the `--images` cache); `host/src/backend_xrt.cpp`
(the device open and its environment variables) and `host/tools/divsqrt_soak.c`, `host/tools/clause5_soak.c` (`cft_open(art, 0, ...)`); the lead's
box scripts `box_nightly.sh`, `box_resume_stress.sh`, `box_wave9_gate.sh`, `box_chunk_card.sh`, `box_rint_ab.sh`, `copy_wave9.sh`,
`box_overnight.sh`, `box_ma_card.sh` and `box_smoke.sh` (whole) and the headers of the other eight; the lead's ledger (the lines named) and the lead's
notes on the box and on the nightly window; the brief of parcel DR3. MEASURED here: `wc -l` and `grep -c` on the tree at 0b7c959,
`git rev-parse` of the trees named, `gh repo view`, and the five instruments.
