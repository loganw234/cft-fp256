# Round 2: the gather, the scatter, the lane mask and the broadcast (plan, 2026-09-15)

The four asks cft-rebound's `docs/HARDWARE.md` still carries after ask 7
landed, planned as one parcel round in the sense of
`../../ParcelRound/METHOD.md`: a seam the lead lands first, parcels an
agent each, a verifier where reading cannot settle it, a ledger outside
every worktree, and merges one at a time with the suite after each.
Written by the lead before any parcel exists, from both repositories
read rather than remembered; every path named here was checked to exist
on 2026-09-15 against `b963663` (cft-fp256) and `039e3c3` (cft-rebound).

## What changed since the list was written - read this first

Four asks were deferred to this round: **1** the device-side scatter,
**4** the device-side gather, **5** a per-run lane mask, **6** a
scalar-broadcast operand. Reading both sides of the seam changes the
round in three ways, and each is a finding about the plan rather than
about the code.

**Ask 6 is delivered and was never marked.** ABI 0.12 shipped
`cft_run_ex` with `cft_elem_args.scalar_mask` on 2026-09-12, behind
CAPS2[7] (`CFT_SEQ_FEAT_SCALAR`), and the requester's own document says
so: *"cft-fp256 shipped exactly this in ABI 0.12 ... the ask is delivered
and unadopted"* (`cft-rebound/docs/HARDWARE.md`, the ensemble section).
`docs/ROADMAP.md`'s entry for ask 6 has no DONE mark, which is how it
reached this round's list. P0 marks it. Nothing is built for it; the
adoption is cft-rebound's, in the other agent's tree, and not ours to
touch.

**Asks 1 and 4 are one mechanism.** The requester's scatter is not a
scatter-add by index. `build_scatter()` in `cft-rebound/src/ias15_cft.c`
(line 665) gives every particle a ROW of pair references in REBOUND's
partner order, and `gravity_body()` (line 762) accumulates with

    a = 0
    for t in 0 .. scat_max-1:
        addend[3p+c] = contribution[side][c][l]      # a host gather, by table
        a = a + addend                               # one vector add per row slot

- a left fold in a fixed order over GATHERED elements, one call per row
slot, with a particle whose row has run out contributing +0 (their own
argument for why that is exact stands: the running sum starts at +0 and
cannot become -0 under any attribute, so x + (+0) is x). On the tile
that is a program over lanes whose scratch block was filled THROUGH AN
INDEX TABLE: `LDL r4, s; ADD r3, r3, r4` for each slot, one deposit of
r3 - r3 starts at +0 and names no stream, so none of the three is
loaded (the first draft of this sketch accumulated into r0, which IS
the a stream; P1 caught it on 2026-09-15). And step 2 of their resident design - pair lane l needs
`x[i_l]` and `x[j_l]` from the predictor's deposits - is the same
mechanism on the streams. So the device-side primitive both asks need is
**an input block fetched through an index table**: the three streams
and the scratch-in block of a program run, each optionally indexed, with
one index value meaning +0. One CAPS bit, four pointer registers, one
definition in the software backend that is a single line. The call
count for gravity's accumulate at 64 bodies goes from 63 vector adds and
63 host gathers per force evaluation to ONE program run, and their
measured per-call cost on the card is 108 us (`HARDWARE.md`, "Measured,
later the same day"), which is what that number is worth.

**Ask 5 is worth at most two percent of a step today, by the requester's
own table.** `pc_lane_efficiency` is 0.77 to 0.92 (8 to 23% of program
lanes idle), and program runs are at most 10.5% of a card step and 1% at
256 bodies (the same table). The mask removes idle lanes' compute and
bytes INSIDE program runs, so its ceiling is 0.23 x 0.105 of the wall.
Their to-do item 4 ("a mixed ensemble to price idle lanes ... decides
whether the lane-mask ask is worth its library change") has not been
run. It is planned here as the smallest parcel, last in the merge order,
with an honest number attached; whether to dispatch it is Logan's call
and the plan says so where it is decided.

**Corrected 2026-09-15 12:51 (P3's measurement, the ledger).** The
ceiling above priced two things the mask would remove from a program
run: idle lanes' BYTES and idle lanes' COMPUTE. The bytes half is real
and P3 delivers it (a masked lane's deposit slots, count and scratch-out
slots are the caller's bytes, it contributes no flag, and an all-masked
block leaves its loops at the first test). The compute half is not
there to remove: the sequencer issues per BEAT, and a block's active
mask decides what is written, not what is computed - a lane that drops
out at `SETACT` has cost its block the same since revision 1. Measured
with `make seqcycles` at P3's tip, four blocks: half-masked and
all-masked cost the same, dense plus one single-beat read a block (four
cycles at every format; fp32 1,189 -> 1,205 over four blocks; block
setup 60.8 -> 64.8 a block), and dense is unchanged. Skipping a beat
with no active lane in the issue pipe and in the stream loads would buy
the compute; that is R14/R15 and R10, which two parcels just landed in,
and it is a revision-7 item recorded in docs/ROADMAP.md with these
numbers as the before-side - not this round's. The requester's item 4
gets its tile-side answer from this: zero, so their ensemble
measurement prices the host side alone.

And one thing not on the list that yesterday's measurement put there:
the tile's reduction accumulator streams ONE element a cycle, which is
why `cft_reduce_seg` on the card returned the contract's bits but was
not faster than a host loop (docs/VALIDATION.md, the seq6 entry). A
beat-wide accumulator has no ABI, no contract change, its own bench and
its own cycle probe, and shares no file with the three parcels above. It
is offered as an optional fourth parcel because it is separable, not
because it was asked for.

## The shape of the round

    P0   the seam: ABI 0.14 declared and refused everywhere, VERSION 0xA00,
         the five registers, the kernel arguments, the XRT plumbing that
         passes them on every launch, ask 6 marked         - the lead, first
    P1   indexed inputs for a program run                  - wave 1, long pole
    P4   the beat-wide accumulator (optional)              - wave 1, disjoint
    V1   verifier on P1
    P2   indexed operands for cft_run_ex, composed over P1 - wave 2
    P3   the lane mask                                     - wave 2
    V3   verifier on P3
    lead seam tests at each merge, the suite after each, the bindings and
         the docs sweep, one image on the box, the card day

Wave 2 waits for P1's merge because P2 composes over P1's mechanism and
P3 shares `rtl/cft_seq.sv`, `python/cft_golden/seq.py` and
`host/src/program.c` with it - METHOD.md section 8: hold a parcel that
shares a file intimately with another until the first lands.

## P0 - the seam, and the lead's

Everything three or more parcels would otherwise touch. Behaviour
preserving by construction: every new field, flag and register is
REFUSED BY NAME on every backend and every bit is zero on every tile, so
the suite is the same suite on both sides of it. Lands and is pushed
before any parcel is dispatched; every worktree branches from it.

### ABI 0.14, `host/include/cft.h`

```c
#define CFT_SEQ_FEAT_INDEXED   0x2000u  /* CAPS2[9]:  a program run's input
                                           blocks may be fetched through index
                                           tables (P1) */
#define CFT_SEQ_FEAT_LANE_MASK 0x4000u  /* CAPS2[10]: a program run honours a
                                           host lane mask (P3) */
#define CFT_IDX_NONE 0xFFFFFFFFu        /* the index that reads as +0 */

typedef struct cft_run_args {
    /* ... every existing field, unchanged ... */
    const uint32_t *idx_a, *idx_b, *idx_c;   /* n indices each, or NULL: dense */
    size_t idx_a_src, idx_b_src, idx_c_src;  /* elements the indexed source holds */
    const uint32_t *idx_scratch_in;          /* n * n_scratch_in, lane-major, or NULL */
    size_t idx_scratch_src;                  /* elements the scratch pool holds */
    const uint8_t *lane_mask;                /* (n + 7) / 8 bytes, bit i = lane i, or NULL */
    size_t lane_mask_bytes;                  /* exactly that, or refused */
} cft_run_args;

typedef struct cft_elem_args {
    /* ... every existing field, unchanged ... */
    const uint32_t *idx_a, *idx_b, *idx_c;
    size_t idx_a_src, idx_b_src, idx_c_src;
} cft_elem_args;
```

Both are INPUT structs with the size handshake that refuses an
unrecognised size, so a caller built against 0.13 is refused, by the
sentence that already exists, rather than run with its fields ignored.
`CFT_ABI_VERSION_MINOR` goes to 14 with the history paragraph extended
as every step's is; the WebAssembly module is rebuilt with it
(`bindings/wasm/build.sh`) because `verify.mjs` holds the module's ABI
to the macro, and the remote protocol refuses a frame whose ABI word
differs at all.

**What P0 does with the fields: refuse.** `cft_program_run_ex` and
`cft_run_ex` refuse any non-NULL index table or lane mask with
`CFT_ERR_UNSUPPORTED` and a sentence naming the field and the parcel
that builds it, on every backend, before any backend is called. An
index table on an operand that is also scalar, or an `idx_*_src` of
zero beside a table, or `lane_mask_bytes` not equal to `(n + 7) / 8`,
are `CFT_ERR_INVALID_ARGUMENT` - the shape rules are the lead's and are
final; the parcels replace the refusals with implementations and never
loosen a shape rule.

### The backend seam, `host/src/backend.h`

`cft_seq_run_io` gains the index tables, their source lengths and the
mask, so `cftx_program_run`'s signature does not grow (the struct exists
for exactly this reason - its own comment says so). `cftx_run` gains
nothing: P2's device route is a program (below), and its software and
remote routes gather in `device.c` before the backend is reached.
`CFT_ROLE_IA, IB, IC, ISI, MASK` are appended to the role enum;
`CFT_ROLE_COUNT` is derived, as it is now, and `bind_clear` and every
per-role array follow it.

### The register map, `rtl/cft_csr.sv`, `hw/kernel.xml`, VERSION 0xA00

Five 64-bit registers, appended, each a kernel argument, each read by
the sequencer through `m_axi_a` as the image, the bank and the scratch
block are (so `hw/link.cfg` is unchanged and they land in HBM[0]):

    0x88  IDX_A_PTR    arg 12   n u32 entries, beat-padded
    0x90  IDX_B_PTR    arg 13
    0x98  IDX_C_PTR    arg 14
    0xA0  IDX_SI_PTR   arg 15   n * n_scratch_in u32 entries, lane-major
    0xA8  MASK_PTR     arg 16   (n + 7) / 8 bytes, beat-padded

Four index registers rather than one concatenated table because the
tables must BIND as `a`, `b`, `c` and `scratch_in` bind: a run split
across tiles hands each tile its lane range of every table, and a
resident buffer's slice is an offset, which a concatenation cannot give
four of. That is the argument scratch_in and scratch_out made for their
own registers and it is the same argument here.

MODE gains five bits under the existing reserved-bits guard:

    [19] a indexed   [20] b indexed   [21] c indexed
    [22] scratch_in indexed           [23] lane mask present

P0 changes nothing about the guard: a set bit among MODE[31:19] is
refused at start with STATUS[3] and no memory is touched, which is
already the behaviour and is the negative control every parcel inherits
- a tile whose CAPS2 bit is clear refuses the MODE bit rather than
ignoring it. `CAPS2[9]` and `CAPS2[10]` stay zero in P0
(`rtl/cft_krnl.sv`, the `caps2` concatenation); P1 and P3 each set their
own bit in the commit that makes the bit true.

VERSION 0x900 -> 0xA00, for the reason every bump before it had: the
registers exist, so a host that wrote them to a 0x900 tile would write
into a decode default. One bump for the round. The bench assertions in
`tb/test_krnl.py`, `tb/test_krnl_quarter.py`, `tb/test_krnl_reduce.py`
and `tb/test_krnl_seq.py` move with it; `docs/ARCHITECTURE.md`'s CSR
map gains the five rows and the MODE bits.

### The XRT plumbing, `host/src/backend_xrt.cpp`

`KNOWN_VERSIONS` gains 0xA00; `ARG_IDX_A .. ARG_MASK` are 12..16; `Tile`
gains five `xrt::bo` members with caps, and `ensure_one` creates each
one beat long before ANY launch on a >= 0xA00 device - the program
launches and the two reduction launches alike - and every `tile.k(...)`
on such a device passes all seventeen arguments. This is the lesson of
2026-09-14 written into the seam: XRT's start sends the whole argument
register image, and a declared argument the launch does not set goes
out as zero. P1 and P3 bind their real buffers into these slots and
touch no launch site.

### The rest of P0

- `python/cft_golden/seq.py`: `run(...)` accepts `idx_a`, `idx_b`,
  `idx_c`, `idx_scratch_in`, `lane_mask` keyword arguments and raises
  `NotImplementedError` naming the parcel for each. The model is the
  authority and the parcels write the definitions; P0 fixes the
  signature so two parcels do not each invent one.
- `host/tests/api_test.c`: the refusals above, each by name, on the
  software backend, and the size handshake with the grown structs.
- `docs/ROADMAP.md`: ask 6 marked done as of 2026-09-12 with the
  requester's own sentence; asks 1, 4 and 5 gain a paragraph pointing
  here.
- `docs/COMPATIBILITY.md`: the 0.14 section, every surface "refused by
  name" until its parcel lands.
- `docs/SEQUENCER.md`: a revision 6 heading with the contract section
  below, marked "P0: declared; P1/P3: built".
- Proof it preserved behaviour: `verify/run.sh` quick on both sides of
  the commit, `make sim` and `make simmc` on the box, `make yosys-lint`,
  the loopback remote suite. Read the logs.

## The contract each parcel builds to

The software backend is the definition and the model is its authority,
as everywhere in this repository. These paragraphs are what P1 and P3
put into `seq.py`'s `run()` and `program.c`'s executor, and what every
other backend is held to.

**An indexed input block (P1).** For a stream with a table,
`A[i] = idx[i] == CFT_IDX_NONE ? +0 : a[idx[i]]` for `i` in `[0, n)`,
and the run proceeds exactly as a dense run over `A`. For the scratch
block, `S[i * k + s] = idx[i * k + s] == CFT_IDX_NONE ? +0 :
pool[idx[i * k + s]]` with `k = n_scratch_in`, lane-major as the block
is now. An index at or past `idx_*_src` is refused before the run
starts, on every backend, by name and by value - the device must never
read past a buffer for a caller. `+0` is the format's positive zero
encoding. There is no new rounding rule and nothing for the model to
define beyond these two lines: the answer is what the dense run over the
gathered block gives.

**A lane mask (P3).** Lane `i` with bit `i` clear runs no instruction.
Its deposit slots, its count and its scratch-out slots are NOT written -
the buffers hold what the caller put there, on the host and in a device
copy alike; the normative "+0 for an untouched slot" applies to the
lanes the run owns and a masked lane is not one of them. It contributes
no flag, it is inactive for the early exit from its first cycle, and it
cannot raise deposit overflow. A run whose every lane is masked completes
with nothing written and nothing raised. All-ones is bit-identical to no
mask.

**The accumulator (P4).** No contract change: the pairing
`python/cft_golden/reduce.py`'s `stream_reduce` defines is the pairing,
every bit and every flag as today, at every `n`, every `seg` and every
attribute. What changes is cycles.

## P1 - indexed inputs for a program run

You are parcel **P1** in `cft-fp256` (a git worktree of
`C:\Users\logan\source\repos\cft-fp256`, branched from `main` at the P0
commit `fd9ec1e` (P0), or any later commit of `main` that contains it - `git merge-base --is-ancestor fd9ec1e HEAD` says so). **Check you are on
that commit and in that repository** - `git log --oneline -1` and
`git remote -v` (it must say `loganw234/cft-fp256`) - and if either is
wrong, say so in the ledger's `urgent/` and stop.

This is a deterministic floating-point tile whose whole product is that
every backend returns the same bits and the same flags as the golden
model, `python/cft_golden`, for every call. The benches under `tb/` hold
the RTL to the model, `host/tests/seq_check.py` holds the C executor to
the model, `host/tests/device_test.c` holds a device to the software
backend. Bit identity is not one property among several; it is the one
that makes the rest worth having.

### Start here

1. This document, all of it, then this section again.
2. `../../ParcelRound/METHOD.md` sections 1, 3, 4 and 5 - what the
   ledger is for and what a negative control has to be.
3. `docs/SEQUENCER.md`: "Execution model", "Deposition", revision 3's
   R4 and R5 (the scratch and its block), revision 5's R10 (streams on
   demand) and R11 (the drains). The block is what you are filling; R10
   is the path you are teaching to fetch by index.
4. `rtl/cft_seq.sv`: the states `S_SIN_GO`, `S_SIN_PARSE` (the scratch
   preload), `S_LD_GO`, `S_LD_STREAM` and `rd_need` (the on-demand
   stream loads), and the assembler `as_fill / as_strb / as_data` the
   drains use to pack elements into beats - yours is the same machine in
   reverse. The read master is muxed in `rtl/cft_krnl.sv` (`seq_rd_sel`,
   `seq_araddr`, around line 600): every read the sequencer makes goes
   through `m_axi_a`, and so do yours.
5. `python/cft_golden/seq.py`'s `run()` (line 979) and the C executor
   in `host/src/program.c` (`seq_block`, line 1084, and the block loop
   after `seq_program_run`) - the two definitions you are extending, in
   that order.
6. `host/src/device.c`: `bind_role` (line 256, the registry's binding
   path) and its six calls for a program run (around line 544) - where
   your four tables join the registry beside the scratch block's; then
   `host/src/backend_xrt.cpp`: `ensure_one`, `buf_bind` into `ob[r]`
   (around line 1556), the staging that follows it, and the program
   launch around line 1640, where P0 passes `tile.ia .. tile.mk` as
   one-beat stand-ins in slots 12..16.
7. What the ask is for: `cft-rebound/src/ias15_cft.c` lines 620-700
   (`build_scatter`) and 762-810 (`gravity_body`), read-only, in
   another agent's repository. Do not edit anything there.

### The ledger

`C:\Users\logan\source\repos\cft-round2-ledger\`. Read every file there
before you start, again before you design anything touching a file this
brief calls shared, and again before you write your report. Append to
`P1.md` only. Its README says what clears the bar. **Stamp every entry
with the output of `date` at the moment of writing** - on 2026-09-15
every author guessed the time and the guesses drifted up to ninety
minutes, so commit times had to serve as the record.

**Before anything else, arm a persistent watcher on
`C:\Users\logan\source\repos\cft-round2-ledger\urgent\`** with the loop
in the README, inline, not from a script file. If you notice the watch
has died, re-arm it and do a full read. If you spawn a subagent, say so
in the ledger when you dispatch it, and do not finish while it runs.

### Your job

Make the four index tables real, end to end: the RTL fetches a stream
or the scratch block through its table when the MODE bit is set, sets
CAPS2[9], and refuses the bit on a build without the feature; the model
and the C executor implement the contract paragraph above; the XRT
backend binds the tables into the slots P0 passes; every gate that
holds those four things to each other covers the indexed case; and the
seq6-style measurement script for the card is written, though not run -
there is no card day inside a parcel.

### What reading the tree already turned up - verify it, do not trust it

- The sequencer reads every input through one master. `S_LD_STREAM`
  loads a stream a beat at a time into the lane block's register slice
  on demand (R10, `rd_need`); the scratch preload reads
  `blk_n * n_scratch_in` elements in one burst pass and parses them
  lane-major (`S_SIN_PARSE`). An indexed load has to read the table's
  beats (dense, from the table register plus the block's offset), then
  issue ONE single-beat read per element at `base + (idx * esz) & ~31`,
  select the element's bytes at `(idx * esz) & 31` on return, and pack
  elements into beats before the register write - because the register
  file takes beats. `CFT_IDX_NONE` writes +0 and issues no read.
- Reads on one AXI ID return in order (`hw/link.cfg` says why that is
  true by construction), so no reorder buffer: the returns match the
  table's order.
- Throughput is bounded by outstanding reads and HBM latency, not by
  the bus. **Corrected by P1 (2026-09-15):** the sequencer's read side
  issues ONE burst at a time (`rd_burst_left == 0` gates the AR), for
  the image and the dense streams too, so a gathered element is a whole
  round trip and there is no divisor - about four cycles an element on
  model RAM at every format, and an HBM round trip each on the card.
  Making that cheaper is a change to the read side, not to the gather,
  and is a roadmap item for after the round, priced on the card first.
- **A finding you should confirm before relying on it.** `rd_need`
  marks a stream as needed only when an instruction reads it, so an
  indexed stream nobody reads should issue no reads at all - the same
  saving R10 gives dense streams. If that holds, the table for an
  unread stream is never touched either; check it against the source.
- **The trap that would be a silent wrong answer.** The block's lane
  range. A run is executed in blocks of `BLK_LANES`, and a table entry
  is indexed by the GLOBAL lane, so the table beats for block `b` start
  at entry `blk_base`, which is not beat-aligned at every format when
  `n` is not a multiple of the block. Read the table from the right
  entry, not the right beat, and put a case in the bench where `n` is
  a block and a half at fp32 and at fp256, with distinct index values
  in every lane, so a one-beat slip shows as the wrong element and not
  as a plausible neighbour.
- The C executor processes lanes in blocks of 64 and the model runs the
  whole array; `seq_check.py`'s third claim is that blocking is
  invisible. Your tables must be sliced the same way.

### Files you own

- `rtl/cft_seq.sv` - the load and preload states and whatever fetcher
  you add; **not** the block setup, the active mask, the drains or the
  issue pipe, which P3 will edit after you land and which R14/R15 just
  settled.
- A new `rtl/cft_gather.sv` if you want the fetcher its own module (and
  then its own bench, `tb/test_gather.py`, added to `SIM_BENCHES` in
  `tb/Makefile`).
- `rtl/cft_krnl.sv` - only the `caps2` bit [9] (from `FEAT_INDEXED`),
  the wiring of the two CSR ports below, and, if you need it, the
  read-master mux for a second read source; nothing else in that file.
- `rtl/cft_csr.sv` - exactly three things, mirroring `feat_scalar`:
  `input logic feat_indexed`; `output logic [3:0] cfg_indexed =
  mode_q[22:19]` (the sequencer has to see which streams are indexed,
  and the CSR exports nothing for those bits at the seam); and the
  reserved-bits guard `cfg_mode_bad` narrowed to `mode_q[31:23]` with
  `(|mode_q[22:19] && !feat_indexed)` added. MODE[23] stays refused on
  every build - it is P3's. Nothing else in the file. (Decided
  2026-09-15 on P1's escalation: the seam's own comment in the CSR
  said the parcels change it, and this list said the opposite.)
- `python/cft_golden/seq.py` - `run()`'s indexed arguments and a
  `gather()` helper; nothing about the ISA.
- `python/tests/test_seq.py` - your cases.
- `host/src/program.c` - the executor's block loop where streams and
  the scratch preload are loaded; nothing in the loader or the ISA
  decode.
- `host/src/device.c` - the refusals P0 left in `seq_check_round2`
  (in `program.c`, below) are replaced there; here you own the four
  `bind_role` calls for `CFT_ROLE_IA .. CFT_ROLE_ISI` beside the scratch
  block's two (around line 555) and the sizes they bind; nothing in
  `cft_run_ex` (P2's).
- `host/src/program.c` - `seq_check_round2`'s index-table arms become
  the bounds checks (an index at or past its source, by name and by
  value), and the executor's block loop gathers; the lane-mask arms
  stay as P0 left them (P3's).
- `host/src/backend_xrt.cpp` - inside `cftx_program_run` only: the four
  tables staged into `tile.ia .. tile.isi` when not resident and taken
  from `ob[CFT_ROLE_IA ..]` when they are, exactly as `scratch_in`
  is, and the five operands at the end of the launch's argument list
  changed from the stand-ins to the resolved pointers. Not the
  reduction paths, not `ensure_one` itself, not the version list.
- `tb/test_seq_core.py`, `tb/test_krnl_seq.py`: your cases.
- `host/tests/seq_check.py`: a fourth corpus with tables, from its own
  seed so the three existing corpora draw what they always drew.
- `host/tests/device_test.c`: one leg, beside `compare_seq`.
- A measurement script for the card, `tb/probe_gather_card.py` or
  under `host/tools/`, that runs the gravity-accumulate shape (P pairs
  x 6 contributions gathered into 3N lanes' scratch, the fold program,
  one deposit) against the software backend and prints time per element
  and the call count it replaces. Not run in this parcel.

### Files you must NOT touch

- `host/include/cft.h`, `host/src/backend.h`, `hw/kernel.xml` - **the
  lead's**, landed in P0; and `rtl/cft_csr.sv` beyond the three items
  above. If a declaration is wrong, say so in the ledger, do not fix it.
- `rtl/cft_engine_stream.sv`, `rtl/cft_reduce_acc.sv` - **P4** is
  editing them now.
- `host/src/backend_remote.c`, `host/src/remote.h`, `host/tools/cft-serve.c`
  - **P2** owns the remote route for indexed operands; the program
  run's remote route stays "refused by name" from P0 until the lead
  decides otherwise (it is client-side gather, and it is small, but it
  is not yours).
- `bindings/`, `CAPABILITIES.md`, `README.md`, `docs/README.md`,
  `docs/VALIDATION.md`, `docs/ROADMAP.md`, `docs/COMPATIBILITY.md` -
  **integrator-only**. Report what they should say.
- Anything under `C:\Users\logan\source\repos\cft-rebound` or any other
  repository.

Expected small edits outside your files, and only these: the CAPS2 bit
in `rtl/cft_krnl.sv`; the section "Revision 6, R16: indexed inputs" in
`docs/SEQUENCER.md` where P0 left the heading; the row for your bench
in `tb/Makefile` if you add one; the argument documentation of
`cft_run_args` in `docs/HOSTAPI.md` under the 0.14 heading P0 left.

### Building and testing on this host

The model: `python -m pytest python/tests/test_seq.py -q` (the Miniconda
`python` on PATH; install nothing).

The host library, from Git Bash, every trap accounted for:

```bash
rm -f host/src/*.o host/src/*.lo host/libcft.a
PATH="/c/msys64/mingw64/bin:$PATH" make -C host CC=gcc OS=Windows_NT \
  TMP='C:/Users/logan/AppData/Local/Temp' TEMP='C:/Users/logan/AppData/Local/Temp' \
  all device-test.exe
python host/tests/seq_check.py --trials 200
host/device-test.exe -q -n 64        # software against software, the leg included
```

The benches, in the Docker image already present on this machine, one
target at a time (`seq_core`, `krnlseq`, `seqbanks`, `faults`, then
`seq_coremc` and `krnlseqmc` - the multi-pass census `make sim` does not
run and which found a real defect on 2026-09-14):

```bash
MOUNT=$(pwd -W); MSYS_NO_PATHCONV=1 docker run --rm -v "$MOUNT:/work" -w /work/tb cft-sim make seq_core SIM=verilator
MSYS_NO_PATHCONV=1 docker run --rm -v "$MOUNT:/work" -w /work/tb cft-sim python3 check_results.py sim_build/seq_core/results.xml
MOUNT=$(pwd -W); MSYS_NO_PATHCONV=1 docker run --rm -v "$MOUNT:/work" -w /work cft-sim make yosys-lint
```

**Every single bench target runs `tb/check_results.py` over its own
results and exits non-zero when a test fails** - since `2318281`
(2026-09-15). Before that a target exited 0 with `TESTS=3 PASS=0
FAIL=3` (P4 measured it with a broken pairing; cocotb cannot set an
exit code), which is why the second `docker run` above exists; it is
now redundant and harmless. Your report still carries the checker's
line (`PASS: 1 bench(es), no failures recorded`, or the `TESTS=` line),
not the exit code; the multi-pass targets append the pass count to
their build directory (`sim_build/seq_coremc10`). Background anything
over a minute and read its log; a background shell holding a sequence
of `docker run`s can be reaped while its container runs on, so run
targets one at a time and check `docker ps` before reading a truncated
log as a failure (P1, 2026-09-15). Build only inside your own worktree.
The full `make sim` and the image build are the lead's, on the build
box; you never touch the box or the card.

### Working rules this repository learned the hard way

- **The Bash tool mangles backslashes and tabs in long heredocs.** Write
  a patch script with the Write tool and run it; the scratchpad has
  thirty of them from the last two days as the pattern.
- **Never kill a process by image name, and never `docker kill` a
  list.** On 2026-09-15 a parcel's `docker kill $(docker ps -q ...)`
  killed a sibling's census containers mid-run. The command is
  `docker ps --no-trunc` (the mount path in the command line says whose
  the container is - yours is your worktree), then `docker kill <one
  container ID>` whose command line is yours. For processes, your own
  PIDs only; a `pgrep -f` inline self-matches the asking shell, so
  check from a script file or with the `[b]racket` trick.
- **Bench every shape a mechanism changes with.** Twenty-three green
  benches missed a drain slip and a two-beat deadlock on 2026-09-14; one
  case sweeping block length and burst boundary found both in minutes.
  Your sweep is `n` across every block length at every format with
  distinct indices in every lane, the table's beats straddling a burst
  boundary, and the read count asserted against the number of non-NONE
  entries.
- **A gate that cannot fail is not a gate.** The negative control here
  is three-fold, and each half must be shown to fail: (a) the identity
  table (`idx[i] = i`) must be bit-identical to the dense run, AND a
  permuted table must differ from it and equal the model; (b) a table
  with `CFT_IDX_NONE` in it must produce +0 in exactly those lanes and
  issue exactly that many fewer reads; (c) on a build with the CAPS2 bit
  forced clear, MODE[22:19] set must be refused with STATUS[3] and no
  read issued - and with the bit set, accepted. Build each, run it,
  confirm the failing half fails, delete the artifact, and put both
  outputs in your report.
- **Derive counts, do not transcribe them.** The number of reads, beats
  and results your benches expect come from the table and the format,
  computed in the bench, never typed.

### Do not

- push, merge, rebase, or commit to `main`. Commit inside your worktree
  only; the lead merges.
- change the dense path's cycle counts. `make seqcycles` (`tb/
  probe_seq_cycles.py`) prints the five-column table in
  `docs/SEQUENCER.md`'s "What it measures"; every dense number must be
  unchanged, and your report carries the table.
- weaken any assertion, loosen any refusal, or "fix" anything outside
  scope - report it instead.

### Report

What you changed file by file; the gate output as actual lines
(`seq_core`, `krnlseq`, `seq_coremc`, `krnlseqmc`, lint, `test_seq.py`,
`seq_check.py`, `device-test`); the three controls with their measured
numbers; the cycle probe's dense table unchanged and the gathered cost
beside it; the card script's dry-run output on the software backend;
and **anything you found that this brief got wrong**. If you had to
cross a boundary, say so and why - that is expected; doing it silently
is not. If the approach is unworkable, stop and report that rather than
inventing a different design.

## P2 - indexed operands for `cft_run_ex`, composed over P1

Dispatched after P1 is merged; its base is that merge commit. Same
repository, ledger, working rules, host build and do-nots as P1 -
read P1's section for them, they are not repeated.

### What wave 1 learned that binds you (added 2026-09-15 11:40, before dispatch)

- **Your base is `main` at `5c0c655` or the docs-only commits after it** (P1 merged 2026-09-15 11:37; your dispatch names the exact tip).
  `git rev-parse HEAD` before anything; if your worktree is not there,
  stop and put it in `urgent/` rather than working on the wrong tree.
  Your ledger file is `P2.md`; create it, append only, `date` stamps.
- **The opcode read rule.** `op_reads` in `rtl/cft_seq.sv` (grep for
  it) decides which streams an instruction fetches: FMA and SELECT read
  a, b and c; ADD and SUB read a and c; MUL, COPYSIGN, MIN, MAX, MINNUM,
  MAXNUM, the compares and the integer ops read a and b; ABS and NEG
  read a. The elementwise API has the same shape already (`cft.h`:
  "unused operands (b for ADD, c for MUL) may be NULL"), so the
  composition maps a to r0, b to r1, c to r2 with no remapping. What is
  yours to decide is a table on an operand the opcode does not read
  (`idx_b` on an ADD): refuse it by name, or ignore it as the dense path
  ignores the operand - write the rule down and test it, and the
  software backend's gather must never touch a NULL source for an
  unread operand. P1's original defect was a read decision made from an
  operand field instead of the opcode (a defaulted rb fetched stream a:
  the whole gather for nothing, V1's finding); make no per-operand
  decision on the host that the opcode already makes.
- **P1's remote route is yours to replace, in three places, together.**
  (i) `host/src/device.c`, the remote-open block that masks
  `CFT_SEQ_FEAT_INDEXED` off a remote handle (`dev->seq.features &=
  ~CFT_SEQ_FEAT_INDEXED`, with the comment that names you); (ii)
  `host/src/device.c`, the refusal by name in `cft_backend_program_run`'s
  remote branch ("an indexed input block needs CFT_SEQ_FEAT_INDEXED,
  which this device does not publish"); (iii) `host/tests/remote_test.c`,
  the three checks that the client's capability word omits INDEXED
  while the server's HELLO carries it (grep `CFT_SEQ_FEAT_INDEXED`).
  This extends your ownership by exactly those regions of the
  program-run path: the client-side gather for `cft_program_run_ex`
  over remote - the tables gathered into dense temporaries on the
  client, a dense program run sent, the deposits landing dense as they
  already do - and nothing else in that path. Once the route carries
  tables a remote handle publishes the bit its server publishes, and
  `remote_test.c`'s `identity_tests` gains the indexed program case
  beside the `reduce_seg` block (identity table equal to dense, permuted
  table equal to the software backend). The server side (`cft-serve.c`,
  `remote.h`) is unchanged: no new opcode.
- **MODE[22] without a scratch input is P1's follow-up**, in flight on
  P1's branch (the sequencer ignores `idx_scratch_in` when the program
  declares no scratch input; it is being turned into a refusal). Your
  composition declares no scratch block and passes no scratch table, so
  nothing to do - only do not rely on the bit either way.
- **The lead's seam test after you** runs the composed `cft_run_ex`
  against `cft_program_run_ex` with the same tables on the same device;
  keep the composition in one helper the device-test leg goes through,
  so the seam test can name it.
- Everything in P1's "Building and testing" and "Working rules" is
  current as amended above: every bench target runs its checker; the
  process rule is a command; `date` on ledger entries.

### Your job

`cft_elem_args.idx_a / idx_b / idx_c` become real on every backend,
without new RTL: on an XRT device the library composes an indexed
elementwise run as a THREE-INSTRUCTION PROGRAM over P1's mechanism -
`op rd=r3 ra=r0 rb=r1 rc=r2; DEPOSIT r3; HALT`, `max_deposits = 1`, the
three streams indexed as the caller's tables say, one deposit per lane
landing dense in `d` - and on the software backend it gathers and calls
the dense path, which is the definition; the remote backend gathers on
the client and sends a dense `RUN`, the call portable and the saving
not, exactly as `scalar_mask` does today (`device.c`, the paragraph
above `cft_run_ex`). The sequencer's ALU is the engine's pipe with the
same rounding, and every elementwise opcode is an ALU opcode (the op
field is the same byte), so the bits are the dense run's by
construction; your gate is that they are, on all three backends, for
every opcode group the device carries, every attribute and every
format.

### What reading the tree already turned up - verify it

- The sequencer route needs a device with the sequencer AND
  `CFT_SEQ_FEAT_INDEXED`; without either it refuses by name and never
  loops. Which refusal fires first is a decision; write it down.
- A scalar operand and an indexed one on the same operand is refused by
  P0's shape rule; a scalar `b` beside an indexed `a` is legal and must
  work (the program's `r1` from one element... it does not: the
  sequencer has no stride-0 stream). **That is the trap.** Either the
  composition expands the scalar into the program's constant bank
  (`ka`, one constant, zero bytes per lane) or it is refused by name.
  Choose the bank and say why in the report; a silent n-element
  expansion on the host is the thing the scalar mask exists to avoid.
- The flags of a program run are the sticky OR over active lanes; the
  elementwise run's are the OR over elements. Same set, same bits;
  check it, do not assume it.
- `d` may alias `a`, `b` or `c` in `cft_run_ex`. A program's deposit
  window is a separate buffer role. Aliasing with an indexed source is
  a read-after-write hazard through the gather; say what the rule is
  (refuse aliasing when a table is present is acceptable) and test the
  rule.

### Files you own

`host/src/device.c` - `cft_run_ex` and whatever composition helper you
add; **nothing** in `cft_program_run_ex`'s path or the reduction paths.
`host/src/backend_remote.c` - the client-side gather before `cftr_run`;
nothing in the frames (`remote.h` and `cft-serve.c` are unchanged: no
new opcode, and if you find you need one, that is a report, not an
edit). `host/tests/device_test.c` - one leg beside `compare`.
`host/tests/remote_test.c` - the indexed case in `identity_tests`.
`bindings/wasm/wasm_api.c` - a `cftw_run_ex` export as a pure
pass-through of `cft_run_ex` (the scalar mask and the three tables),
safe on its own because nothing `cwrap`s it until the lead's rebuild.
**Corrected 2026-09-15 11:58 (P2's finding):** this brief said
`cftw_run_ex` and an elementwise `runEx` "grow the six arguments"; they
do not exist - ABI 0.12's `cft_run_ex` was never bound in wasm or node,
and `Program.runEx` in `bindings/node/core.mjs` is the PROGRAM run. The
JavaScript half (`bindings/node/lib.mjs`'s eager `cwrap` table,
`core.mjs`, `test.mjs`) is the lead's, in the same commit as the module
rebuild, because a `cwrap` of an export the shipped module lacks throws
at import and takes every node gate with it. The wasm rebuild is the
lead's (say in your report that it is due). `docs/HOSTAPI.md` - the
`cft_run_ex` paragraph under the 0.14 heading P0 left.

Not yours: `rtl/`, `python/cft_golden/seq.py`, `host/src/program.c`
(P3 is in them), `cft.h`, `backend.h`.

### The negative control

Identity tables bit-identical to the dense `cft_run` over the same
operands at every opcode in the sample and every attribute, AND a
permuted table different from dense and equal to the software backend's
indexed answer, AND the refusal by name on a device without the bit
with no round trip made (the server's STATS counters unchanged, as
`remote_test.c` already checks for the segmented reduction's shape
refusals). Run, confirm each failing half fails, report both outputs.

## P3 - the lane mask

Dispatched after P1 is merged; base is that merge. Same repository,
ledger, rules and build as P1. **Read the value statement at the top of
this document before you start**: this parcel is worth at most about
two percent of the requester's step today, and the point of building it
small and last is to keep it small. If the RTL wants to grow past the
block setup and the three drains, stop and report.

### What wave 1 learned that binds you (added 2026-09-15 11:40, before dispatch)

- **Your base is `main` at `5c0c655` or the docs-only commits after it** (P1 merged 2026-09-15 11:37; your dispatch names the exact tip).
  `git rev-parse HEAD` before anything; if your worktree is not there,
  stop and put it in `urgent/`. Your ledger file is `P3.md`; create it,
  append only, `date` stamps.
- **What P1 left in `rtl/cft_csr.sv`, which your three items mirror:**
  `input logic feat_indexed`; `assign cfg_indexed = mode_q[22:19];`;
  and the guard `(mode_q[31:23] != 9'b0) || (|mode_q[22:19] &&
  !feat_indexed) || ...` (around lines 371, 480 and 497 at 5c0c655).
  Yours: `feat_lane_mask`; `assign cfg_mask_en = mode_q[23];`; the
  guard narrowed to `(mode_q[31:24] != 8'b0)` with `(mode_q[23] &&
  !feat_lane_mask)` beside the indexed term. `mask_q` at `10'h02B` and
  `cfg_mask` (MASK_PTR 0xA8) are P0's and already there; `FEAT_LANE_MASK`
  in `rtl/cft_krnl.sv` already feeds `caps2[10]` - check what P0 set it
  to and whether `cft_krnl` wires a `feat_lane_mask` port to the CSR the
  way P1 wired `feat_indexed`.
- **A parameter below `cft_krnl` cannot be set from the command line**
  (V4, 2026-09-15): `tb/cocotb.mk` errors out on any `KRNL_PARAMS`
  naming a module other than `TOPLEVEL`. If your CAPS2[10]-clear
  control wants a build switch, it is a parameter OF `cft_krnl` (the way
  `EN_WIDE` is now threaded on the P4 staging branch); the other way,
  which V1 and P1 used for CAPS2[9], is a copy of the tree under the
  scratchpad with the localparam edited, run, and deleted. Either is
  acceptable; say which.
- **Lane flags are qualified by their own strobe** (P4's defect at
  6b5582e, fixed at 778dabf): the array's lane-flag and lane-data
  vectors are not self-qualifying - a reader that ORs lane flags must
  qualify each lane by the return strobe of the instruction that
  produced them, on its own delay line, or it reads a previous run's
  flags. For you: the sticky OR must exclude a masked lane at the edge
  its result would have returned, by the active bit as it stands THEN,
  not by the mask sampled at block setup. Two cases, both required: a
  run whose only overflowing lane is masked reports clear flags; and an
  unmasked program that overflows in lane k, followed by a masked run
  with lane k masked and nothing overflowing, reports clear flags.
- **The read side has one burst in flight** (P1's measurement): every
  sequencer read is a whole round trip, and the mask fetch at block
  setup is one more read per block (at fp256 a beat is one lane, so a
  block's 64 mask bits are eight bytes: one beat). Measure block setup
  dense against masked in the cycle probe at each format and put it in
  the report; the two-percent ceiling assumes that fetch is one burst.
- **P1's follow-up is in flight on P1's branch** and merges beside you:
  the MODE[22]-without-scratch refusal (the program header check in
  `rtl/cft_seq.sv`, and the model's and the C executor's matching
  refusal), a `seq_core` case for it, a device-test `-b` indexed leg in
  `host/tests/device_test.c`, and a comment in `tb/probe_seq_cycles.py`.
  Stay out of those regions: your `cft_seq.sv` work is `S_BLK_SETUP`,
  `blk_act_fn`, `ACTALL`, the drains and the mask fetch; your test
  additions are new functions and cases, never edits to existing
  indexed ones.
- `python/cft_golden/seq.py`'s `run()` already takes `lane_mask` (P0
  made it raise; check what P1 left) and `host/src/program.c`'s
  `seq_check_round2` still refuses the lane-mask arm by name (P0): both
  are yours to make real.
- Everything in P1's "Building and testing" and "Working rules" is
  current as amended above: every bench target runs its checker; the
  process rule is a command; `date` on ledger entries.

### Your job

A masked lane costs no beat it can avoid and writes no byte: the
contract paragraph above, on every backend. RTL: the block's opening
active mask is `blk_act & mask_bits` instead of `blk_act`
(`rtl/cft_seq.sv`, `S_BLK_SETUP`'s `active <= blk_act`, line 2243, and
`ACTALL`, which reactivates every lane THE CALLER HAS - a masked lane
is not one the caller has, so `ACTALL` must not revive it; find both
places, they were written to be one function, `blk_act_fn`); the mask
beats read from `MASK_PTR` at block setup; the deposit drain, the count
drain and the scratch-out drain skip masked lanes' elements - and the
scratch-out drain is the one that today says in its own comment "it is
NOT masked by the active bit", which is correct for a lane that
converged and wrong for a lane that was never in the run. Model and C
executor: `lane_mask` generalises `n_active` (a prefix) to a bitmap.
XRT: the mask binds as `CFT_ROLE_MASK`; a run split across tiles hands
each tile its lane range of the mask, and a slice does not start on a
byte boundary at every format (`host/src/slice.h` divides in beats; at
fp256 a beat is one lane), so the backend REPACKS the slice's bits from
bit `off` rather than pointing into the caller's bytes. Say in the
report what the repack costs and where the buffer lives.

### What reading the tree already turned up - verify it

- Padding lanes (index at or past `n` in the last block) are already
  inactive by `blk_act_fn` and write nothing; the masked lane is that
  mechanism applied to a lane below `n`. If the drains already skip
  padding lanes by construction, they may skip masked ones the same
  way; check whether they skip by lane count or by active bit, because
  the two differ exactly here.
- The deposit COUNT for a masked lane is not written either; the
  caller's `counts` array keeps its value. `device_test.c` fills
  outputs with a pattern before a run in several legs - use the same
  discipline so an unwritten slot shows as the pattern.
- **The trap.** The early exit `any(active)` is evaluated from the mask
  the hardware has to hand (docs/SEQUENCER.md, "The early exit may fire
  late, and that is free"). A block whose only ACTIVE lanes are masked
  ones must exit its loops immediately, not run the trip count to the
  end; and a block with no active lane at all must still run the drains
  for... nothing, and then finish. Both are cases.

### Files you own

`rtl/cft_seq.sv` - `S_BLK_SETUP`, `blk_act_fn`, `ACTALL`'s use of it,
the three drains' lane selection, and the mask fetch you add; nothing
in the load/preload states P1 just landed or the issue pipe.
`rtl/cft_krnl.sv` - `caps2` bit [10] (from `FEAT_LANE_MASK`) and the
wiring of the two CSR ports below. `rtl/cft_csr.sv` - exactly the
mirror of P1's three items, in the file P1 leaves: `input logic
feat_lane_mask`; `output logic cfg_mask_en = mode_q[23]`; the guard
narrowed to `mode_q[31:24]` with `(mode_q[23] && !feat_lane_mask)`
added. Nothing else in the file. `python/cft_golden/seq.py` -
`lane_mask` in `run()`. `host/src/program.c` - the block loop's
`active[]` initialisation and the three output writes.
`host/src/program.c` - `seq_check_round2`'s lane-mask arm, the refusal
replaced by the shape check that already precedes it. `host/src/device.c`
- the `bind_role` call for `CFT_ROLE_MASK` beside the scratch block's.
`host/src/backend_xrt.cpp` - inside `cftx_program_run`: the mask's
staging or binding, the per-tile repack, and the last operand of the
launch. `host/src/backend_remote.c` -
the client-side route: run unmasked on the server and copy back only
active lanes' outputs (bit-identical to a masked run by P3's own
contract, since a masked lane's output is by definition the caller's
bytes; say in the report why the server-side lanes' extra compute
cannot change an active lane's bits). Tests: `tb/test_seq_core.py`,
`tb/test_krnl_seq.py`, `python/tests/test_seq.py`, `seq_check.py` (a
masked corpus), `device_test.c` (one leg).

Not yours: `cft.h`, `backend.h`, `kernel.xml`, `cft_csr.sv` beyond the
three items above, the bindings, the docs the lead keeps.

### The negative control

All-ones mask bit-identical to no mask (deposits, counts, scratch_out,
flags, status), AND a mask with holes leaves exactly the masked lanes'
bytes at the pre-run pattern while the active lanes equal the unmasked
run's, AND the flags of a run whose only overflowing lane is masked are
clear. Then the RTL control: with CAPS2[10] forced clear, MODE[23] set
is refused with STATUS[3]. Build, run, confirm the failing halves fail,
delete, report both outputs. And a measurement: the cycle probe with
half the lanes masked at each format, dense against masked, in the
report - that is the number the requester's item 4 wants.

## P4 - the beat-wide accumulator (optional, wave 1)

Same repository, ledger, rules and build as P1; base is P0. No ABI, no
contract change, no new register. Every bench target you run is
followed by `check_results.py` over its results, as P1's build section
says - the single-target exit code is not a verdict, which is P4's own
finding of 2026-09-15.

### Your job

`rtl/cft_reduce_acc.sv` consumes one element a cycle; the engine's
serialiser (`rtl/cft_engine_stream.sv`, `ser_*`, around line 1030)
unpacks each beat for it. Make the tile reduce a beat a cycle at every
format WITH THE PAIRING UNCHANGED. The tree is a binary counter over
element index (the module's own header explains why it is that tree),
so the sub-tree over an aligned group of `2^k` consecutive elements is
fixed: at fp32 a beat's eight elements are four level-0 adds, two
level-1 adds and one level-2 add, and the group's single partial enters
the counter at level 3. Those levels are dependent, but beats are
independent, and the engine has `epb` ALUs a beat: one beat-op a cycle
can carry level 0 of beat `t` in four lanes, level 1 of beat `t - L` in
two, level 2 of beat `t - 2L` in one and the counter's own carry add in
the eighth - 4 + 2 + 1 + 1 at fp32, 2 + 1 + 1 at fp64, 1 + 1 at fp128,
and fp256 is one element a beat already. Groups that are not aligned
and not full - the last beat of a segment, or every beat when `seg` is
not a multiple of `epb` - fall back to the serialiser, and the seam
between the two is where the pairing can go wrong: an element must
enter the counter at the level its INDEX gives it, whichever path it
came by.

### What reading the tree already turned up - verify it

- `cft_reduce_acc`'s `in_data` is `W = BEAT_BITS` wide already (the
  element right-aligned); the counter, the deferred carries and the
  `ADD_LATENCY` delay line are the parts you keep. What you add sits in
  front of it and shares the adder issue port.
- The array's acceptance strobe `arr_rdy` is the accumulator's `clk_en`;
  the pipe counts its depth in accepted edges. Your level-1 and level-2
  issues are further beat-ops through the same pipe and count the same
  way.
- `seg_clear`, `seg_open`, `acc_take`, `red_last` (added 2026-09-14) are
  how a segment boundary restarts the counter. A boundary inside a beat
  must send that beat's elements down the serial path.
- `tb/test_reduce_acc.py` holds the module alone; `tb/test_krnl_reduce.py`
  holds the whole kernel at sizes that straddle beat boundaries in both
  directions at every precision, and since 2026-09-14 per segment
  (`sum_segmented`, `maxall_on_the_tile`). Both must pass untouched
  before you add cases, and both must still pass untouched after.
- The cycle probe is `tb/test_krnl_cycles.py` (`make cycles`, with
  `RD_LATENCY`/`WR_LATENCY` for the card's round trip). It is
  deliberately not asserted tightly; your report carries its
  before/after at every format and at `seg` = 3, 8, 192 and whole.

### Files you own

`rtl/cft_reduce_acc.sv`; `rtl/cft_engine_stream.sv` - the serialiser
and the accumulator instance and their glue, **nothing** in the read
masters, the writer or the CSR-facing ports; `tb/test_reduce_acc.py`,
`tb/test_krnl_reduce.py`, `tb/test_krnl_cycles.py` - cases added, none
changed. Not yours: everything else; in particular `rtl/cft_seq.sv`
(P1) and the CSR.

### The negative control

Every `n` in `test_krnl_reduce.py`'s lists and every `seg` bit-identical
to the model before and after, at all four formats and five attributes,
with the beat path PROVABLY TAKEN: a counter of beats reduced by the
wide path, read by the bench, must be nonzero where the sizes allow and
zero where they do not - and a build with the wide path forced off must
give the same bits at the cycle count the probe prints today. Show the
control failing by breaking one pairing in the wide path (swap two
lanes) and watching `test_krnl_reduce.py` name the size, then restore
it. Report both outputs and the cycle table.

## The verifiers

Two, from `../../ParcelRound/templates/verifier.md`, each after its
parcel reports and before it merges; both must not fix anything, and
"found nothing" is an acceptable answer that will not be held against
them. Each watches only `lead.md` and `urgent/` in the ledger.

Every bench a verifier runs is the target AND `tb/check_results.py`
over its results.xml - a single target's exit code is not a verdict
(P4's finding, 2026-09-15) - and a parcel report that quotes exit codes
where it should quote the checker is itself a finding.

**V1, on P1.** Attack list: (1) the block-offset trap in the section
above, by building a case the parcel did not; (2) the read count
against the non-NONE entries, measured in the bench, not read from the
report; (3) the dense cycle table unchanged, by re-running
`make seqcycles` from a clean build and diffing against
`docs/SEQUENCER.md`'s table; (4) the C executor's blocking with tables
that straddle a block of 64; (5) the refusal on a device without the
bit, by forcing CAPS2[9] clear in a COPY of the RTL under the
scratchpad and running `krnlseq`; (6) scope, `git diff --stat` against
the ownership list; (7) every sentence added to a comment; (8) what
else.

**V3, on P3.** Attack list: (1) the scratch-out drain really skips
masked lanes and really does not skip converged ones - two cases,
measured by bytes; (2) `ACTALL` and the mask; (3) the early exit with
only masked lanes active in a block; (4) the XRT repack at fp256 with a
slice starting at lane 3 of a byte - by reading the code and building
the case in the software leg; (5) the flags; (6) scope; (7) comments;
(8) what else.

**V2, on P2** (added 2026-09-15; the method's criterion - a parcel that
crosses a seam gets a verifier - says yes, as it did for P4). Attack
list: (1) the scalar-beside-indexed trap, a scalar `b` beside an
indexed `a` on every backend, bits against the model; (2) the aliasing
rule, by building the aliased case; (3) the flags, an overflow in a
gathered lane only; (4) the remote route: the server's STATS counters
on a refusal, and the byte count of the RUN the client sends for a
gathered call; (5) which refusal fires first on a device without the
sequencer and on one without the bit; (6) the composed program's shape
(three instructions, `max_deposits` 1) against `cft_program_run_ex`
with the same tables - the lead's seam test, run early; (7) a table on
an operand the opcode does not read; (8) scope; (9) comments; (10)
what else.

## The ledger

`C:\Users\logan\source\repos\cft-round2-ledger\` - outside every
worktree, in no repository, with the README from
`../../ParcelRound/templates/ledger.md` and an `urgent/` directory,
created by the lead at dispatch and seeded with: the P0 SHA; the fact
that the Docker sim image exists on this machine and the box is not
theirs; the Windows host build line; the multi-pass census rule; and
the two things from 2026-09-14 that any parcel touching the sequencer
must know (the retire gate: the array is shared with the engine and
only a program's own results retire; the constants ride the pipe with
the beat). One file per author, append only. Thrown away at the end of
the round after the lead folds anything durable into
`docs/VALIDATION.md` and the memory directory.

The lead watches the whole directory. Parcels watch `urgent/`.

## What the lead keeps

- **P0**, and every file P0 names as the lead's.
- **The seam tests**, written at each merge: after P1, a program with an
  indexed scratch block followed by a segmented reduction over its
  deposits on the same tile (`tb/probe_reduce_then_prog.py` extended -
  the shared-array hand-off is where 2026-09-14's hang lived); after
  P3, an indexed AND masked run against the model; after P2, the
  composed `cft_run_ex` against `cft_program_run_ex` with the same
  tables on the same device.
- **Every merge, serially, the full suite after each on the box
  (`make sim`, `make simmc`, lint, `verify/run.sh` quick, the loopback
  remote suite), the log read.** Never a merge while a suite runs.
- **The image**: one build on the box at the end of wave 2
  (`KERNEL_FREQ=135000000`, never the script's 10 MHz; the box build
  script from the seq6 day), then the card day: `device-test` with the
  new legs, the P1 script at the gravity shape, P3's half-masked probe,
  P4's segmented timing against the seq6 entry's table.
- **The bindings and the docs sweep**: the wasm rebuild, with the
  elementwise `runEx` bound in JavaScript for the first time (P2's
  finding, 2026-09-15: it never was), the Arduino
  vendor copy (`bindings/arduino/sync.py`), `CAPABILITIES.md` rows,
  `docs/COMPATIBILITY.md`'s 0.14 table, `docs/VALIDATION.md`, the
  README counts (`python/check_docs_index.py`), `docs/ROADMAP.md`'s
  entries for asks 1, 4 and 5 with the card's numbers.
- The word to cft-rebound's agent when the image is on the card and the
  entry points exist: their adoption is theirs.

## Sequencing and budget

- Wave 1: P1 and P4 in parallel (disjoint files), V1 when P1 reports.
  P1 is the long pole: RTL, model, executor, XRT, four gates and a card
  script. Expect it to correct this brief.
- Merge P4 first if it arrives first (its suite run is the reduction
  benches and the cycle probe); merge P1 after V1.
- Wave 2: P2 and P3 in parallel from the P1 merge (`5c0c655`), V2 and
  V3 when each reports. P2 shares no file with P3.
- The suite after each merge is the constraint, not the merging: budget
  about an hour a merge on the box, four merges.
- Then the image and the card day, which is a day.

## Decisions this plan leaves to Logan

1. **Dispatch P3 at all this round**, given the two-percent ceiling and
   the requester's own "price it first"? The plan carries it; the
   default here is to build it, because it is small and because their
   item 4 cannot be run without it.
2. **Dispatch P4**, which nobody asked for and which is the only item
   that makes ask 7 fast?
3. **The ABI shape in P0** - four index registers rather than one, the
   `CFT_IDX_NONE` sentinel, the mask's "not written" rule - is the
   lead's proposal and is final once P0 lands; anything to change is
   cheaper to change now.
