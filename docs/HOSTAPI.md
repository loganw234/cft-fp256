# The host API

`host/include/cft.h` is the contract between this project and the
people using it. The header was published before the implementation,
deliberately - an ABI is far cheaper to argue with before anything
depends on it than after.

**Both backends are implemented** in `host/src/`: the software
backend (C99, no dependencies, no configure step, no generated
bindings) and the XRT device backend (`backend_xrt.cpp`, compiled in
with `XRT=1`, driving up to 64 compute units with the tree-aware
reduction split). `make -C host` builds a static library, a shared
library, and the tools below; without `XRT=1`, `cft_open()` with an
artifact path reports `CFT_ERR_NO_DEVICE`. Nothing above the API
changed when the device backend landed - which was the point of
having written the API first.

## The shape of the thing

One call does the work:

```c
cft_run(dev, CFT_FMA, CFT_FP256, CFT_RNE, a, b, c, d, n, &flags, NULL);
```

with one sibling for the case that call cannot express, where the
output is one element rather than n:

```c
cft_reduce(dev, CFT_SUM, CFT_FP256, CFT_RNE, a, NULL, d, n, &flags, NULL);
```

and one call decides what "dev" means:

```c
cft_open(NULL,             0, &dev);   /* software - runs anywhere */
cft_open("cft_hw.xclbin",  0, &dev);   /* the tile */
```

Those two backends return **byte-identical output buffers and
identical flags**. That is the whole product expressed as a function
signature: adopt the library with no hardware, add the card later, and
nothing above the API changes except how long the call takes.

## Why a C ABI rather than a Python package

The fields that need reproducible arithmetic do not write their
numerics in one language, and several of them do not write it in
Python at all.

| language | how it calls this | glue needed |
|---|---|---|
| Fortran | `iso_c_binding` | none - direct |
| Julia | `ccall` | none |
| Python | `ctypes` / `cffi` | none; no build step, no pyxrt |
| Rust | `extern "C"` / bindgen | none |
| C | include `cft.h` | none |
| C++ | include `cft.hpp`, header-only over `cft.h` (RAII, typed byte encodings, span batches, context-bound operators) | none |
| MATLAB, R, Go, C#, Java | each has a standard C FFI | a thin shim |

Fortran matters more here than its reputation suggests: an enormous
amount of working numerical code is Fortran, it is where
reproducibility complaints actually originate, and `iso_c_binding`
makes this header callable without a wrapper generator.

The deeper reason is that **a port must be a shim, never a
reimplementation.** Semantics reimplemented per language is exactly
how "identical bits" quietly stops being true - and it stops being
true silently, in the edge cases, months later. One implementation
behind one ABI keeps the guarantee checkable.

It also closes a hole we already have: pyxrt exposes no way to read a
kernel's status registers in either XRT version this project has
tested (2.14 and 2.19), so `FLAGS` and `STATUS` are unreadable from
Python. XRT's C++ API does expose them, so the device backend does
close that hole as a side effect rather than as a special effort - a
Python caller reaching the card through `libcft` gets flags that a
Python caller reaching it through pyxrt cannot.

## What the library absorbs so callers never see it

Every one of these is a place the hardware contract is sharper than a
user should have to care about. All of them are now built and
exercised against a four-tile hw_emu image; the *(device backend)*
tags are kept because they say which properties are the device's
rather than the software backend's, which is still useful when reading
a failure.

- **Beat padding** *(device backend)*. The tile works in whole 256-bit
  beats. `cft_run` takes an arbitrary `n`, pads the tail internally,
  and makes sure padding contributes nothing to the flags. The
  software backend has no beats, so `n` is already arbitrary there.
- **Multi-tile partitioning** *(device backend)*. A four-CU bitstream
  has four sets of FLAGS and STATUS registers. The library splits the
  work, ORs the sticky words, and reports one result. Callers never
  learn tiles exist; `cft_get_caps` reports the count for the curious.
  This is what drives `hw/link_quad.cfg`, and it now scales to 64 -
  see docs/SCALING.md.

  **A reduction splits differently, and that difference is the whole
  determinism argument.** An elementwise op can be cut anywhere,
  because element i does not care which tile produced it. A reduction
  can only be cut at canonical NODES of its tree, or the answer
  changes - so the library computes the node boundaries, hands one
  range to each tile, and folds the partials with the same tree. A sum
  over four tiles returns exactly what one tile returns, bit for bit.

  **A program's lanes are cut too** (2026-09-25). One scheduler core
  (`run_job` in backend_xrt.cpp - docs/ROADMAP.md, "Programs across
  tiles", the plan of record's step 2) now places every kind of run: it
  owns the waves (at most one task a tile), the launch discipline
  (stage all, then start; wait on every started run; the handle finished
  after a failure while a unit may still run) and the sticky words, and
  each kind keeps its own cut. A program's lanes are cut at beat
  boundaries, every per-lane block goes with its lanes - the three
  streams, the deposit window, the counts, both scratch blocks, the
  index tables' rows - an indexed SOURCE, the image and the bank go to
  every tile whole, and the lane mask is repacked from each slice's
  first lane. Each tile is told its slice's lane count, so its early
  exit is its own lanes'; SEQUENCER.md's P3 (the early exit is
  invisible) is what makes the cut unobservable, and the card gate
  fuzzes the cut points and the tile order rather than assuming it
  (`CFT_XRT_PROGRAM_CUTS`, `CFT_XRT_TILE_ORDER`, docs/CARDDAY.md).
- **Buffer staging** *(device backend)*. `cft_run` takes host pointers
  and does the device round trip itself. `cft_alloc` exists for when
  that round trip is the bottleneck: allocate with it, fill through
  `cft_buffer_data`, publish with `cft_buffer_to_device`, and the
  library recognises its own pointers in `cft_run`, `cft_reduce` and
  `cft_program_run_ex` and does not stage those operands again. On a
  backend with no device memory - software, and a remote handle,
  whose buffers stay on the client - the same calls are a plain
  allocation and two no-ops, which is what keeps code written that
  way portable rather than dual-path. `cft_caps.buffers_resident`
  says which kind of device you have; `cft_buffer_get_info` says what
  actually happened to one buffer. **How it works, and what a port
  must do to get the rate, is the section below.**
- **A per-run size ceiling** *(device backend, 2026-08-31)*. Each
  master owns exactly one HBM pseudo-channel (hw/link.cfg - done for
  response ordering, see there), so each argument buffer is capped at
  that channel's **256 MB per tile**: 64M fp32 elements, 8M fp256, per
  tile per run. The library does NOT split by capacity - slice.h
  divides by tile count only - so an oversized run fails loudly at
  buffer allocation rather than being quietly serialised. Callers with
  more data than that split across runs; if a real workload makes that
  painful, the fix is capacity splitting in `cft_plan_slices`, not
  widening the channel group back.
- **Bus faults** *(device backend)*. A bad pointer or a fabric error
  becomes `CFT_ERR_BUS_FAULT`, distinct from a wrong answer, because
  "the memory never delivered this" and "the arithmetic is wrong" want
  different responses. The software backend cannot produce one.

## The device backend

`host/src/backend_xrt.cpp` implements all five of those bullets. It is
the only C++ in the library, because XRT's API is C++, and it exports
nothing but the C functions in `src/backend.h` - so the library still
builds with no dependencies at all when XRT is absent, which is the
whole reason the software backend exists.

    make -C host XRT=1                        # XRT under /opt/xilinx/xrt
    make -C host XRT=1 XRT_ROOT=/path/to/xrt  # if it lives elsewhere

**`XRT=1` is not the default, and a default build cannot open a card.**
`make -C host` on its own produces a software-and-remote-only library:
`cft_open()` with an artifact path returns `CFT_ERR_NO_DEVICE` and
`cft_open("cft://host:port")` still works, because the remote client is
plain sockets. That is deliberate - a library whose point is that it
compiles anywhere must not need a vendor runtime to compile - but it
means a caller who wants the card has to ask for it at build time, and
the symptom of forgetting is a device that reports it is not there
rather than a build error.

### Linking against an XRT-enabled `libcft.a`

An XRT build folds `src/backend_xrt.o` into the archive, and that
object needs XRT's runtime and the C++ one at the final link. A program
that links `libcft.a` must therefore add what `host/Makefile` adds
(`XRTLIBS`):

    -L$(XRT_ROOT)/lib -lxrt_coreutil -lstdc++ -lpthread -luuid

Without them the link fails with a page of undefined references to
`xrt::bo`, `xrt::device` and friends, which names neither the cause nor
the fix. A build without `XRT=1` needs none of it: the archive is C99
objects and nothing else, and that is the case the "no dependencies"
claim above is about.

**The static archive cannot go into a shared object.** `libcft.a`'s
objects are compiled without `-fPIC` (`%.o` in `host/Makefile`; only
the `%.lo` rule adds `$(PIC)`), and `backend_xrt.o` is C++ besides, so
linking the archive into a `.so` fails on relocations - the one seen
downstream is `R_X86_64_PC32 against symbol _ZSt7nothrow@@GLIBCXX_3.4`.
That is not a defect to work around: the shared library is already a
build product of the same `make`. `make -C host` builds **both**, from
two sets of objects - `libcft.a` from the `.o` files and
`libcft.so` / `libcft.dylib` / `cft.dll` from the PIC `.lo` files, with
`XRTLIBS` already on its link line. A caller who needs a shared object
links the shared library rather than repackaging the archive.

Multi-tile is the substance of it. A four-CU bitstream is not four
times one CU from the host's side: each CU's AXI master is wired to
its own group of HBM pseudo-channels, so a buffer allocated for tile 1
is not reachable by tile 2. There is no "the input array" to share.
Each tile gets its own buffers in its own memory group holding its own
slice, and `cft_run` still takes one pointer per operand.

Two things about it are worth stating because they are unusual:

**A failed run poisons the handle.** If a launch or a wait throws,
compute units are still running - XRT's run destructor frees a command
slot, it does not stop a CU, and this RTL has no abort. `cft_csr.sv`
gates the start pulse on `!busy` and answers every write with BRESP
OKAY, so a start issued to a busy CU is dropped *silently*, and the
next poll of CTRL sees the previous run's done bit and reports
success. A caller who retried would receive the aborted attempt's
output. There is no way to make the device safe again from inside the
library, so every later call on that handle refuses until it is closed
and reopened.

**It refuses to open a device whose status registers it cannot read.**
`FLAGS` carries the IEEE exceptions, which are half of what this
library promises to reproduce, and `STATUS` carries the bus faults,
which are how a caller learns its results were computed on bits the
memory system never delivered. Without them every run would return
`CFT_OK` with unverifiable data, and `CAPS` would have to be guessed -
which on a trimmed bitstream means issuing a precision it does not
carry and receiving a buffer of zeros with clean flags. A library
whose product is exception-exact reproducibility cannot run in that
mode, so it says so and stops.

### One process per tile: `CFT_XRT_TILES` (2026-09-25)

By default a device opens every tile the image declares, each with
exclusive access, and is one device of that many tiles. Work that is
many independent jobs wants the other shape: one process per compute
unit, so four jobs run on a quad at once, a small call is not
partitioned across tiles it does not need (round 2 measured a thousand
small segmented sums, issued one at a time, at 431 ms on the quad
against 91 ms on the single-tile image, docs/VALIDATION.md 2026-09-16),
and a timeout finishes one process's handle rather than every tile's
work - though the tile it happened on then wants a reload (below, "A
tile a run was abandoned on").

`CFT_XRT_TILES` names the tiles a process opens, as the 1-based
ordinals their compute units end in (`cft_krnl_1` is 1):

    CFT_XRT_TILES=2      tile 2 alone
    CFT_XRT_TILES=3,1    tiles 3 and 1, in that order, as a two-tile device

It **refuses rather than shrinks**, naming the tile each time: a
malformed list, and a tile the image does not declare, are
`CFT_ERR_INVALID_ARGUMENT` with a sentence - the selection is the
caller's (digits only, 1..64, no empty item, no duplicate, and an empty
variable is not "every tile"); two compute units ending in the same
number, a tile that will not open and one that opens without answering
MAGIC are `CFT_ERR_ARTIFACT`. The commonest reason a
declared tile will not open is that another process holds it. XRT 2.19
reports that as `failed to open cu context: Invalid argument`, and a
unit the image lacks as `No compute units matching` (both on the card),
so the sentence names the tile and says what XRT said. An XRT without
the listing API (2.14's build takes that path) cannot tell the two
apart for a selection, and the sentence says so rather than guessing -
which is why, on that path, a tile the image does not declare is
`CFT_ERR_ARTIFACT` and not `CFT_ERR_INVALID_ARGUMENT`: the backend only
knows it would not open (verifier-V4, 2026-09-25).
The status code is still the generic `CFT_ERR_ARTIFACT` ("artifact
missing, unreadable, or not a tile"), because the contract has no
"busy" status. That is a gap in the contract, not a detail; Logan's
word (2026-09-25) puts a busy status with per-tile failure, in the
plan of record's step 3.

**Without it, a held tile is skipped and the device is smaller.**
Measured on round 2's quad with tile 2 held by another process: the
default open succeeded with three tiles and passed device-test. Nothing
is wrong in the answers - partition invariance holds at any tile count -
but a caller who assumed four has three, and only `cft_get_caps`'s
`tiles` says so. On an XRT without the listing API the default open
probes `cft_krnl_1`, `cft_krnl_2`, ... and stops at the first that will
not open, so the same held tile 2 leaves ONE tile (verifier-V2's model
of that path, 2026-09-25; not seen on a card, whose XRT lists). A caller
that needs a particular shape names it.

On the card (docs/VALIDATION.md, 2026-09-25): each selection opened
as many tiles as it named and passed device-test's quick matrix (the
order written is kept - shown by verifier-V2's model, not the card); four
processes on tiles 1-4 at once all passed; four independent orbit
integrations, one per tile at once, each matched the software loop
engine byte for byte; tile 9, `1;2`, an empty value and a tile another
process held were each refused with their sentence, while tile 3 opened
beside the held tile 2. The parse is `host/src/tile_select.h`, held on
any machine by api-test with an atoi-style parse as its control.

### A tile a run was abandoned on (2026-09-25)

A run is abandoned when its wait outlives `CFT_TIMEOUT_MS` (the handle
is then finished, as above) or when its process ends mid-run. The tile
cannot be stopped - the kernel is `ap_ctrl_hs` - so it runs on after XRT
has aborted the command, and on the card that leaves XRT's scheduler
(ERT) reporting LATER runs on that tile complete early, in any process,
until the image is reloaded. Before this date those runs came back wrong
with `CFT_OK`: rule30 at 1,001 lanes on one tile in 0.38 s with every
lane wrong, where a healthy run takes 9.5 s, and on the quad the
program set's slowest slices with their last block unwritten
(docs/VALIDATION.md). A start that arrives while the tile is still
busy is dropped by the tile, and XRT then completes it with the
abandoned run's end.

The library now reads each tile's CTRL register - the completion
witness - when a handle opens the tile, and in the scheduler every run
goes through at the two moments no command of this handle is
outstanding on it, and refuses by name:

- **when a handle opens it**, a tile that is not idle is running a run
  abandoned there by a handle that is gone - access is exclusive, so no
  open handle can be running it; the run was left by a process that
  ended, or by a handle closed after a run failed in a way that can
  leave the tile running (a timeout, a thrown wait, an ERROR state, a
  completion refused because the tile was still busy after the whole
  wait, an unreadable CTRL), in this process or another (verifier-V9: the
  sentence blamed an ended process for both) -
  and its writes may land in the memory this handle's
  buffers would be given (on the card an abandoned run's output landed
  in a later process's buffers at the same addresses): the open is
  refused, `CFT_ERR_INTERNAL`, "tile N (...) is already running when
  this handle opens it", naming the cure - reload the image, or leave
  the tile out with `CFT_XRT_TILES` (2026-09-26, verifier-V8).
- **before a wave is staged**, a tile that is not idle is running work
  this process did not start, and nothing is staged or started:
  `CFT_ERR_INTERNAL`, "tile N (cft_krnl:{cft_krnl_M}) is running work
  this process did not start (CTRL 0x..., not idle)", naming the reload.
  Until 2026-09-26 the check came after staging, so a busy tile's copies
  filled by the refused wave stayed current with whatever the abandoned
  run wrote over them, and the sentence advised a retry
  (verifier-V8).
- **after XRT reports a run complete**, a tile still busy was completed
  early: the call waits until the tile is idle, for as long as a run may
  take (`CFT_TIMEOUT_MS`), collects nothing, and returns
  `CFT_ERR_INTERNAL`, "XRT reported ... complete while tile N (...) was
  still running it", naming the cure - reload the image: load another
  xclbin, then this one. When the tile went idle within the wait the
  sentence says each such tile "has since finished it", and no write of
  the run lands after the call returns; when it did NOT, the handle is
  finished as a timeout's is - the sentence says so - and the tile may
  still write its windows after the call returns. Loading the same
  image again is a no-op to XRT and cures nothing: on the card after
  the orphan of 2026-09-25, every load until the reload was logged by
  the driver as "xclbin is already downloaded", and the program set run
  through those loads was still wrong in the same lanes
  (docs/VALIDATION.md, 2026-09-28; the journal excerpt is
  `Data/runs/2026-09-25-ode-round/card-witness/journal-probe3-probe4.txt`,
  gitignored).

What the witness reads, and so what it can say, is CTRL's `ap_start`
and `ap_idle` as `rtl/cft_csr.sv` defines them; it was measured with
XRT 2.19 on the card. XRT 2.14 at run time and hardware emulation have
not been run with it.

The contract has no busy status yet; `CFT_ERR_BUSY` comes with per-tile
failure in the plan of record's step 3 (docs/ROADMAP.md). An output
check could not do this job: an early-completed run came back byte for
byte right on the card when an identical earlier run had left the same
bytes at the same addresses, while CTRL read busy at once. The witness
costs two register reads a tile a call. Measured on the quad with one
run each before and after (`cft-bench --resident`, fp32, its 23 ops):
the mean rose 6.2 us a call at 64 elements (+7%, every op slower) and
8.8 us at 4,096 (+10%, 20 of 23 slower). iadd alone moved +2.3 us and
-0.4 us, and run-to-run variance was not measured (docs/VALIDATION.md,
2026-09-28; verifier-V10 found the one-op figure this sentence used to
quote as if for all). The open's check is one read a tile at open. device-test holds the refusals on
every XRT device through `CFT_XRT_WITNESS` - `busy-open`, `busy-before`
and `busy-after`, the last held 50 ms and the refusal timed
(docs/CARDDAY.md); the defect itself is a card-day leg, because planting
it poisons the card for every process after the test.

### Device-resident buffers, and what a port must do to get the rate

**Which buffers can be resident.** The operand-shaped ones, and the
tables that index them: a `cft_run`'s three inputs and its output, and a
program run's three streams, its deposit window and - since 2026-09-12 -
its two scratch blocks, and its four index tables (ABI 0.14). Those all
grow with `n`, which is what makes a device copy worth keeping.

The rest of a program run is staged on every call, and the reasons are
structural rather than unfinished: the image and the constant bank do not
grow with `n` at all, the per-lane deposit counts are four bytes an
element whatever the format, and the lane mask is repacked for the
tile's own lanes on every launch. `cft_buffer_get_info` says what actually
happened to one buffer, and its `staged_why` says why, when a number
looks wrong.


The measured gap is the whole reason this exists. On the card at 135
MHz, through `cft_run` staging every operand on every call, one tile
does **141.8 / 81.4 / 40.3 / 20.0** M fma elements a second at
fp32/64/128/256. With the operands already on the device the same tile
does **462.6 / 235.1 / 118.7 / 59.6**, and four tiles do **1,833.9 /
937.2 / 474.0 / 238.4** (docs/BENCHMARKS.md). Everything below is the
machinery that lets `libcft` reach the second set, and none of it
changes an answer: the same call over the same bytes returns the same
bits and the same flags either way, which is what `device-test -b`
checks and what makes this an optimisation rather than a second
contract.

**What a port must do.** Four lines, and no second code path
(docs/INTEGRATION.md says when to take them, and when a program or a
reduction is the better path):

```c
cft_alloc(dev, bytes, &buf);                 /* instead of malloc  */
memcpy(cft_buffer_data(buf), src, bytes);    /* fill the mirror    */
cft_buffer_to_device(buf);                   /* publish it, once   */
/* ... many cft_run / cft_reduce calls on cft_buffer_data(buf) ... */
cft_buffer_from_device(out);                 /* collect the result */
```

That is the entire difference, and it is the difference `cft-bench
--resident` makes to its own numbers. On the software backend the same
four lines are an allocation and two no-ops, so the port stays one
program. Two rules complete it: **fill once, publish once, run many** -
a `cft_buffer_to_device` inside the loop asks for the transfer back -
and **read the output back before you read its memory**, because a run
that wrote a buffer leaves the device copy authoritative until
`cft_buffer_from_device`.

**Recognition** is a registry. `cft_alloc` records the buffer on its
device, and each of a call's operand pointers is resolved against that
list before dispatch: a pointer inside a live buffer becomes "this
buffer, at this byte offset", and anything else stays a plain pointer
and is staged. Interior pointers work, which is what lets a caller run
over a window of a larger allocation. The lookup is a linear scan
because the thing being counted is how many buffers one program holds
at once, and it lives in `host/src/device.c` rather than in the
backend, so it is C and testable without a card.

**A device copy is per (tile, role), not per buffer.** Each compute
unit's four AXI masters own one HBM pseudo-channel each
(`hw/link.cfg`, `hw/link_quad.cfg`), so memory reachable by tile 1's
`a` port is reachable by nothing else - not by tile 2's `a` port and
not by tile 1's `b` port. A buffer feeding a four-tile run as `a`
therefore has four copies, created lazily on first use as that role,
each in the group `kernel.group_id()` names for that argument. The
256 MB per-channel ceiling above applies to each of them: a buffer
larger than a channel simply is not made resident, and is staged in
slices exactly as a plain pointer is.

**Each copy holds that tile's window** - its slice of the run, padded
up to a whole 256-bit beat with zeros, which is byte for byte what
staging puts in a staging buffer. So the kernel argument is the copy
itself, at its own base address, and **no XRT sub-buffer is involved.**
That was a decision, and the alternative was measured before it was
rejected: a sub-buffer's offset must satisfy the device's base-address
alignment, which is **4096 bytes** on the XRT this project builds
against (`xrt_core::bo::alignment()`, XRT 2.14.354, measured on
cft2204), while `slice.h` cuts at 32-byte beats. Binding a window at
an offset the runtime is entitled to round is the one failure this
mechanism must not have; holding the cuts to 4096 instead would mean a
different partition for resident runs than for staged ones, which is
two answers where the contract promises one. Per-tile slice copies
avoid the question and cost less HBM as well, since each tile holds
its quarter rather than the whole array.

A copy is reused only when the window is the same one again - which is
the common case by construction, since the same call in a loop asks
for the same `n`, format and tile count - and nothing has changed the
mirror under that window since the copy was filled; otherwise it
refills, which costs exactly what staging costs and never more. **There
is no case in which residency is slower than the staged path it
replaces.** A change to the mirror stales only the copies over the
bytes it changed - a copy brought home, a result the library wrote on
the host (below) - so a buffer carved into windows (streams, a deposit
window, a program's counts) keeps the rest resident; only
`cft_buffer_to_device`, after which the caller may have written any of
it, stales every copy.

**Authority.** One mirror, several copies, and exactly one of them is
authoritative:

| after | authoritative | what a run reads |
|---|---|---|
| `cft_alloc`, `cft_buffer_to_device` | the host mirror | the mirror, copied into each window on first use |
| a run that wrote the buffer as `d` | the device copies that wrote | those copies; `cft_buffer_to_device` is refused until a read-back |
| `cft_buffer_from_device` | the host mirror again | the mirror |
| a run that FAILED once the device may have started it | nothing: the buffer is lost | nothing - refused by name until `cft_buffer_to_device` |

`cft_buffer_to_device` pushes nothing: every copy is marked stale and
refills at its next binding, for the window that binding needs. Pushing
eagerly would mean pushing the whole buffer into every tile's channel
and then pushing the right windows again at the first run.

**A publish over unread run results is refused** (Logan's rule,
2026-09-26). While a buffer holds a run's results nobody has read back,
`cft_buffer_to_device` returns `CFT_ERR_INVALID_ARGUMENT` with a
sentence and changes nothing. The library cannot tell whether the
caller wrote the mirror since the run - a store of the same bytes looks
like none, so no test of the contents can say - and each guess has
returned wrong bytes with `CFT_OK`: dropping the device's bytes lost the
results of a publish nobody wrote before (verifier-V7), and bringing
them home first put them over a caller's rewrite of the whole buffer
(verifier-V8). Read the buffer back first (which keeps the run's
results), then write and publish. The software backend has no device
copy to disagree with its mirror, and accepts every publish; a LOST
buffer's publish is accepted too, and drops what the device held.

**Breaking the read rule costs time, never correctness.** A buffer that
is device-authoritative and is fed in as an input is read back by the
library first, before the tile or the host layer can see the stale
mirror - so 9.4's infinity scan in `cft_reduce`, the software backend's
own loop, the entry points computed on the host (the transcendentals,
clause 5, the conversions, the augmented and formatOf arithmetic, the
payload and character operations and their strings, the scaled
products), a program's image at `cft_program_load` and its constant bank
at a run or a digest, an index table's bound check (`cft_run_ex`,
`cft_program_run_ex`), a scalar operand on `cft_run_ex`'s composed route,
and the next run all see the bytes the last run wrote. Until 2026-09-25
the entry points computed on the host read the stale mirror
(verifier-V7: `cft_exp` after a device ADD into the same buffer, 64 of 64
wrong with `CFT_OK`); until 2026-09-26 the image, the bank and the
strings did (verifier-V8); until 2026-09-27 the tables and that scalar
did - an out-of-range index a device run wrote was accepted, and a
scalar it wrote was taken from before (verifier-V9).

**The library's own writes keep the rule too.** An entry point that
writes a resident buffer's elements on the host - those above,
`cft_reduce`'s and `cft_reduce_seg`'s results, a program run's counts,
`cft_program_digest`'s digest, `cft_conformance`'s report, an output
whose binding was declined and staged - first brings home a run's bytes
over what it writes, and stales every device copy over it, so the next
run reads the new bytes. Until 2026-09-25 none did, and a run after such
a write read the bytes from before it, with `CFT_OK` (verifier-V7: nine
sequences, one to four tiles); the digest and the report were written
unannounced until 2026-09-27 (verifier-V9). `device-test -b`'s "stale
copies" holds every such entry point both ways - a run's bytes read on
the host, the host's bytes read by a run, and in place - against the
software backend, transcript for transcript, and holds the declined
outputs by running its sequences again with every output bind of a
fresh buffer declined (`CFT_XRT_BIND=decline-outputs`, a card
instrument; an output copy already live at the same window would be
reused, and a fresh buffer has none). Its "resident windows stay
resident" holds the other side: that a change to one window does not
refill another. **Out-parameters** - a flags word, a bus word, a
string's length, a bad index, `cft_conformance`'s count of cases - are
stores made FOR the caller, like any variable of the caller's: one that
lies in a resident buffer is the caller's own store into its mirror,
under the rules below. They are status words - most of them zeroed as
the call starts, and written as it ends when it runs, the device
backends' after the run; a call refused before it runs may leave them as
they were (verifier-V10) - so the library states the rule for them
rather than announce each one. An out-parameter must share no bytes
with any array the same call reads or writes: nothing checks it, and
what the call reads or leaves there then differs between backends
(verifier-V9: `bus_out` on an element of `cft_run`'s input read -2 on
the software backend and 479 on a device, `CFT_OK` both).

**Two stores the caller makes into a mirror.** One into a buffer a run
has written and nobody has read back: the publish after it is refused,
above, and `cft_buffer_from_device` then brings the run's bytes home over
the store, where on the software backend the store would stand - read a
buffer back before writing into it. And one with no
`cft_buffer_to_device` after it, which is the one thing the library
cannot see, because a plain store leaves no trace: the run then uses the
bytes the buffer last published, which is why the sync calls exist, and
`device-test -b`'s publish check is what proves publishing takes
effect.

**A lane mask reads the output it writes.** Under a lane mask a program
leaves a masked lane's deposit slots and scratch-out slots as they
were, so its resident deposit window and scratch-out block are made
current before the run, like an input: a device copy is kept only if it
already holds the newest bytes, and is otherwise filled from the mirror.
Until 2026-09-25 an output copy was never refreshed, and a masked lane
came back with whatever the device copy held - after an unmasked run and
a republish, the unmasked run's deposit in every masked lane (verifier-
V4). `device-test`'s "seq lane mask into resident outputs" holds both
shapes at every format.

**A failed run loses what it would have written.** A run that fails once
the device may have started it - a timeout, a fault the tile reported,
a run refused after it ran (the completion witness, above) - may have
written part of a resident window over bytes an earlier run left there
that never came home. Nothing can vouch for that buffer any more, so
`cft_buffer_from_device` on it, and any call that reads or writes its
elements - a run, an entry point computed on the host, a lane mask, a
bank, an image, an index table or a composed run's scalar read from it,
a digest or a report written into it - is refused with
`CFT_ERR_INTERNAL` and a
sentence, until `cft_buffer_to_device` publishes the mirror as the truth
again (which drops what the device held rather than bringing it home);
out-parameters are the caller's stores, above, and are not refused.
`cft_buffer_get_info` reports it with `device_authority` 0 and a
`staged_why` beginning "LOST:". Until 2026-09-25 the device copy kept
the earlier run's "written" mark and the failed run's bytes came back
with `CFT_OK` (verifier-V4). device-test plants the refusal with
`CFT_XRT_WITNESS=busy-after` over a window an earlier run left unflushed
and holds every one of those refusals, the report, and the recovery -
read back before anything runs over it, so a publish that kept the
failed run's bytes could not hide.

**What is not resident.** `cft_reduce`'s partials are the library's
own array; the composed reductions (`CFT_DOT`, `CFT_SUMSQ`,
`CFT_SUMABS`) pass through an internal scratch array, so those spend
one staged pass whatever their operands are; and
`cft_program_run_ex` binds `a`, `b`, `c`, `deposits`, the two
scratch blocks and the four index tables but stages the image, the
constant bank, the counts and the lane mask, none of which is
operand-shaped and two of which do not grow with `n` at all.

**Asking rather than assuming**, as everywhere else here:
`cft_caps.buffers_resident` says whether this device keeps device
copies, and `cft_buffer_get_info` says what one buffer actually got -
whether copies are live, whether a run has written it, and how many
operand bindings were served without a transfer against how many had
to copy, with the reason for the last copy in words. A residency
mechanism that quietly staged everything would return every right
answer and do nothing, so both the test leg and `cft-bench --resident`
print those counters beside their results rather than leaving a reader
to infer them from a rate.

### How it is tested without a card

`host/tests/device_test.c` opens the device backend and the software
backend at once, feeds them identical data, and compares - bits and
flags, every supported format, opcode and attribute. Anything that
differs is a device-path bug by definition, because the software
backend is the one replayed against the golden model.

    bash hw/run-device-test.sh cardday/quad_emu/cft_hw_emu.xclbin -n 64

It runs against a **hw_emu image with no card present**, which is the
point: four-CU partitioning gets exercised, and its bugs found, before
any hardware exists. Beyond agreement it checks partition invariance -
one call over n against a sequence of calls over slices of it, which
is what the library does internally across tiles - at sizes chosen to
straddle beat and tile boundaries (1, 2, 3, 7, 8, 9, 31, 32, 33, 37).

The same binary is what to run on the card. Only the xclbin changes.

`-b` is the device-resident leg: the same elementwise matrix and the
same reductions, run through `cft_alloc`'d operands, and every byte
and every flag compared against the same calls on plain host pointers
AND against the software backend. It adds four claims the pointer path
cannot make - back-to-back runs on resident operands do not drift, an
output buffer used as an input without being read back gives the run
that just happened rather than the one before it, `cft_buffer_to_device`
takes effect, and at least one binding on a device that reports
resident buffers was actually served without a transfer. It runs
against `sw` too, which is how the leg itself is proven able to fail
before an hour of emulation is spent on it:

    ./device-test sw -b -n 256          # the contract, no card
    bash hw/run-device-test.sh <image> -b -n 4096

## What has been on silicon, and what has not

Everything above was written and exercised in emulation first, and the
paragraph here used to say nothing had touched silicon. That stopped
being true on 2026-09-08 (docs/CARDDAY.md is the runbook, docs/VALIDATION.md
the record):

- **The device backend, on a card.** Both card-day images - one tile
  and four - replayed the published sets through this API on an Alveo
  U50: 168 sets, 1,071,635 cases, all matching, once through each,
  with `device-test`'s full matrix and its partition and reduction legs
  clean beside them.
- **Programs, on a card.** The sequencer's revisions 2 and 3 and the
  deeper read-ahead each got their own pair, built, verified and run
  (docs/CARDDAY.md's "Before the day" list carries the dates).
- **The resident buffer path, on a card.** `device-test -b` holds every
  byte and every flag of the `cft_alloc` path to the staged path on the
  card, and `cft-bench --resident` measures what it buys
  (docs/BENCHMARKS.md).

What has NOT been on silicon is the multi-card and multi-host case: the
determinism claim across two different devices in two different
machines still rests on one card, on emulation, and on the software
backend. docs/VALIDATION.md is where that gets recorded when it exists.

## Reductions, and why they are a second entry point

`cft_reduce` landed in VERSION 0x500. It is separate from `cft_run`
rather than another opcode through it, and the reason is a promise
`cft_run` makes: element i of the output depends on element i of the
inputs. A reduction cannot keep that promise - it returns ONE element
however large n is - so issuing `CFT_SUM` through `cft_run` is
`CFT_ERR_INVALID_ARGUMENT` rather than a plausible-looking array.

The tree shape is part of the contract, not an implementation detail:
each node splits so its left child is the largest power of two
strictly below the range, evaluated with the caller's rounding
attribute at every node. Never a sequential accumulation, never
reassociated, never padded. That is what lets two conforming
implementations agree bit for bit, and what lets four tiles agree with
one. `python/cft_golden/reduce.py` is the definition.

Two consequences that surprise people, so they are written into the
header: n = 0 gives +0.0 and raises nothing, and n = 1 gives a[0]
verbatim - one leaf means zero additions, so not even a signalling NaN
is quieted.

`CFT_DOT` is advertised and is not separate hardware. The contract
makes `dot(a,b) == sum(mul(a,b))` exact, flags included, so the
library issues an elementwise MUL and then a SUM. The alternative was
a multiply pass sharing the accumulator's pipe with tagged results and
arbitration between muls and adds - the most schedule-sensitive logic
in the engine, for one saved round trip. The composition property went
into the contract partly so this choice would exist.

That choice paid twice: `CFT_SUMSQ` and `CFT_SUMABS` are the same
composition over a different leaf, and the other three of clause 9.4 -
the scaled products, which return a pair - are named host entry points.
See "The rest of clause 9.4's reductions" below.

## Division and square root: composed, not opcodes

`cft_div` and `cft_sqrt` landed with CAPS opcode-group bit 14. They
are correctly rounded per 754-2019 5.4.1 in the caller's attribute,
with the full flag set - and they are not opcodes, because the tile's
divide hardware is deliberately two small seed tables
(`CFT_RECIP_SEED`/`CFT_RSQRT_SEED`, exposed through `cft_run` like any
opcode) and the FMA it already had. The library composes them:
prenormalise, centre, seed, Newton, a truncating Markstein finish
driven to floor by a restore step, the guard MEASURED from an exact
residual, one rounding.

The composition is the same fixed sequence on every backend. Floating
steps are `cft_run` calls - on a device they run on the tile - and
the integer bookkeeping between them (classify, the ulp steps, the
final pack) is exact host arithmetic, the same division of labour the
reduction fold draws. `python/cft_golden/sequences.py` is the
sequence's specification, held bit-identical to the contract `div`
and `sqrt` by its own test matrix; `host/tests/divsqrt_check.py`
re-proves the C port over the same operand families, flags compared
per element.

Flags follow the per-run granularity rule: every step is its own run,
so the scaffolding's flags are discarded, and what the caller sees is
derived the way the contract derives it - invalid and divideByZero
from operand classes, inexact/underflow/overflow from the single real
rounding. A device whose bitstream predates the seed group answers
`CFT_ERR_UNSUPPORTED` rather than running a sequence it cannot start.

The cost is honest: roughly 25-30 elementwise passes per call. That
is the price of correct rounding built from an FMA - on any
implementation of this route - and it buys the property the project
exists for: the same bits from the laptop and the card.

**On a device the passes are one program; since 2026-09-14 the WHOLE
operation can be.** The program route folds the passes into a
sequencer program with the classify/centre and the final rounding still
on the host (three deposits a lane, two host loops); cft-rebound
measured that shape at 1.6 us an element at binary128 on the card
against 4.3 ns for an FMA on the same tile. `python/cft_golden/divfull.py`
puts the prep and `round_pack` into the instruction stream too: the
raw operands go in, the correctly rounded result and its five flags
come out as two deposits, and libcft computes nothing per element - it
copies one deposit and ORs the other. One image a format (BANK_EXT: the
rounding mode is the run's data, the bank's last five words), generated
from the model into `host/src/divfull_images.h` by
`python/gen_divfull.py` and held to it by the `generated` gate; the same
images are `programs/divfull-*.cfta` and `sqrtfull-*.cfta` as text.

It is OPT-IN (`CFT_DIVSQRT_FULL=1`), because measured on the card the
same afternoon it is slower: 2.33 us an element against the older
route's 1.70 at binary128, n = 768. The host work it removes is about
0.3 us an element; the 167 instructions it adds cost 1.1 ms at 384
beats, because on this tile a sequencer instruction costs ~2.2 cycles
a beat and a program run carries a fixed cost per LANE of 0.07-0.18 us
before any instruction runs (docs/ROADMAP.md, workload ask 8, has the
breakdown). What the whole program buys is the contract's bits inside
a resident program, where the alternative is a round trip. With the
switch set, `cft_div` and `cft_sqrt` take it first on any
program-capable device and fall back by `CFT_ERR_UNSUPPORTED` - a tile
whose caps lack `BANK_PTR`, `REGS32` or `kx` refuses the image by name,
d untouched - to the older program route and then to the chunk route;
the software backend keeps the chunk route, which remains the
definition. The bits are the contract's on every route:
`host/tests/divsqrt_check.py` runs the same matrix over all three,
34,384 cases each, flags per element as well as per batch.

## The clause-5 completion set (ABI 0.2)

Everything clause 5 still asked for after div/sqrt landed on
2026-09-01, in one additive ABI bump: `cft_rint`, `cft_scaleb`,
`cft_cmp_sig`, `cft_convert`, `cft_cvt_from_/to_{i32,u32,i64,u64}`,
`cft_logb`, `cft_next_up`/`_down`, `cft_class`, `cft_total_order`
(`_mag`), `cft_rem`. The full semantics live in cft.h's own doc
comments and docs/DETERMINISM.md; what belongs HERE is the design
split, because it explains every signature:

**Three are composed**, exactly as cft_div is. `cft_rint` is the
magic-constant addition - `(x + copysign(2^(p-1), x)) -
copysign(2^(p-1), x)` under the caller's attribute, two adds whose
rounding at integer weight IS the operation - with host bookkeeping
substituting the already-integral, infinite and NaN lanes and
synthesising the contract flags (the named variants signal nothing;
only `Exact` reports inexact). `cft_scaleb` multiplies by the exact
float `2^n` whenever it exists, so the multiply's own flags are the
contract flags; above emax it stages in chunks whose saturation is
proven consistent, and beyond the subnormal floor - where no exact
factor exists and uniform staging would round twice - it packs each
lane once on the host instead. `cft_cmp_sig` takes the quiet
predicate's value from the tile and synthesises invalid-for-any-NaN.
`python/cft_golden/sequences.py` specifies the first two routes and
holds them bit-identical to the contract.

**The rest are host operations**, and the reason is worth stating
plainly: they contain no floating-point arithmetic AT ALL. A format
conversion is one `round_pack` of an exactly-known value; nextUp is
an increment on the encoding; totalOrder is an unsigned compare of a
key transform; remainder is exact integer reduction. There is nothing
for a device to accelerate, so no backend pass is issued and the
device argument is context. They are bit-identical across backends by
construction rather than by testing - and tested anyway.

Two contract choices a porter must not miss: `cft_cvt_to_*` pins the
invalid-case delivered values (which 754 leaves open) to RISC-V's
FCVT table, and `cft_class` pins its ten values to RISC-V's fclass
bit indices - both because this project already speaks RISC-V for
rounding encodings and tininess, and one table beats two.

`cft_rem` is the one entry point with a cost note: the C walks the
exponent gap a quotient bit at a time in p-bit integer work (the
model does one unbounded divmod; `clause5_check.py` holds the two
identical, true full-gap fp256 case included - "true" because a
power-of-two divisor exits the walk early, which is exactly how the
first version of that directed case fooled itself). Typical calls
are a handful of steps; the walk tops out at emax - emin + p - 2,
~524.5k steps at fp256 - about ten milliseconds on the host, PER
adversarial lane, so an array full of such pairs pays it per
element.

## The phase-1 transcendentals (ABI 0.3)

`cft_exp`, `cft_expm1`, `cft_exp2`, `cft_log`, `cft_log1p`, `cft_log2`,
`cft_log10`, `cft_pow` and `cft_hypot`, added 2026-09-02 in one
additive bump. **Correctly rounded** at every format under every
attribute, with IEEE 754-2019 clause 9.2.1's special values and the
contract's exact flags - not "accurate to an ulp", not "faithful".

That distinction is the reason they are here at all. A correctly
rounded result is defined by the mathematics, so every correct
implementation returns the same bits and this library's answer can be
scored against any of them - which is what the whole project is for. An
*accurate* exponential is a different thing: two of them disagree in
the last bit on a percentage of inputs, neither can be scored, and
"the same bits everywhere" quietly stops being true in exactly the
places nobody looks. A determinism contract that stopped at the
arithmetic and shipped an approximate `exp` would have a hole in it the
size of every application that uses one.

**They are HOST operations, and that is a design decision with a
reason.** No `cft_run` pass is issued, so there is no bus word and no
`bus_out` argument, and the device argument is context - the same shape
the clause-5 operations take when they contain no floating-point
arithmetic. But the reason is different, and worth stating because it
is what a phase-2 optimisation would have to work around:

`cft_div` composes from the tile's opcodes because division has an
exactly measurable residual. Given a candidate quotient q, `a - q*b` is
one fused multiply away and is EXACT, so its sign says which side of
the rounding boundary the true quotient falls on. `exp` has no such
residual. Nothing an FMA can compute tells you which side of a boundary
`e^x` lies on; only more precision does, and more precision means a
multiprecision evaluator, which is integer work. A tile-assisted fast
path for the narrow formats is a plausible later optimisation - the
tile's FMA could carry a polynomial, with the host deciding only the
cases it cannot - but it would have to reproduce these bits exactly,
which makes it an optimisation and not a different answer.

The signatures follow the clause-5 host operations exactly:

```c
cft_exp  (dev, fmt, rnd, a,    d, n, &flags);
cft_pow  (dev, fmt, rnd, a, b, d, n, &flags);
cft_hypot(dev, fmt, rnd, a, b, d, n, &flags);
```

`d` may alias `a` or `b`; `n` is arbitrary; `b` is not optional for the
two binary functions. A batch is one C call and the flag word is the OR
across it, as everywhere else.

**inexact is raised for every result except the exact ones, and those
are decided by exact arithmetic rather than by a tolerance**: exp and
expm1 only at zero, log and log1p only at 1 and 0, exp2 at an integer
argument, log2 at a power of two, log10 at a power of ten the format
represents, pow when the true value is a dyadic rational, hypot when
x^2 + y^2 is a perfect square. `hypot(3, 4)` is 5 and raises nothing at
all, which is the observable difference between a correctly rounded
implementation and an accurate one.

**If an input cannot be shown correctly rounded, the call returns
`CFT_ERR_INTERNAL`** rather than a plausible number. The library
evaluates at a working precision and raises it until both ends of an
enclosure round the same way; the cap on that escalation is sized so
that no input the formats can express should reach it, and reaching it
is a refusal. docs/TRANSCENDENTALS.md carries the arithmetic behind
that sizing, the exact-case decision procedures, the error bounds and
the Table Maker's Dilemma stated honestly.

Two contract choices a porter must not miss. `pow(+-0, -inf)` is +inf
and signals NOTHING - it is the |x| < 1 row, and the divideByZero is
the pole at a FINITE negative exponent rather than the limit. And a
signaling NaN is not covered by 9.2.1's "even a quiet NaN" rows, so
`pow(sNaN, 0)` raises invalid and delivers the canonical quiet NaN
where C returns 1; that deviation is deliberate and documented rather
than accidental.

The vectors carry them: `<fmt>-transcend[-<rnd>].jsonl`, twenty new
sets in the published directory, replayed by `cft_conformance` like
everything else. They are separate files because these are library
entry points rather than opcodes - a case names a FUNCTION, and there
is no opcode field to put that in - which also means a consumer that
predates ABI 0.3 reads exactly the files it always read.

## The phase-2 trigonometrics (ABI 0.4)

`cft_sinpi`, `cft_cospi`, `cft_tanpi`, `cft_asin`, `cft_acos`,
`cft_atan`, `cft_atan2`, `cft_asinpi`, `cft_acospi`, `cft_atanpi` and
`cft_atan2pi`, added 2026-09-03 in one additive bump. **Correctly
rounded** at every format under every attribute, with clause 9.2.1's
special values and exact flags, on exactly the terms the nine above
are.

**What these eleven have in common is what they do NOT need.** The
phase-1 note said the rest of clause 9 wanted an argument reduction
against pi carried to hundreds of thousands of bits at fp256. These are
the functions that want no such thing:

- `sinPi`'s reduction is `x mod 2`, and every operand is a dyadic
  rational, so that reduction is a MASK on the encoding and is exact at
  every magnitude. `sinPi` of the largest finite binary256 is a zero
  decided by integer arithmetic.
- The inverse functions take an argument in [-1, 1] or a ratio, so
  there is nothing to reduce; pi enters only as a factor of the answer.

`sin`, `cos` and `tan` of a RADIAN argument were a different problem
and arrived in phase 3, below.

The signatures follow the nine exactly, and `atan2` takes y first as C
does:

```c
cft_sinpi  (dev, fmt, rnd, a,    d, n, &flags);
cft_atan2  (dev, fmt, rnd, y, x, d, n, &flags);
cft_atan2pi(dev, fmt, rnd, y, x, d, n, &flags);
```

**The exact cases are a much larger table than phase 1's, and every one
of them raises nothing.** Niven's theorem bounds the forward set:
`sin(pi r)` is rational for a rational r only at 0, +-1/2 and +-1, and
a dyadic r cannot reach +-1/2, so `sinPi` and `cosPi` are exact exactly
at the half-integers and `tanPi` exactly at the quarter-integers (with
the half-integers a pole). Hermite-Lindemann bounds the inverse set:
`asin`, `atan` and `atan2` of a nonzero dyadic rational are
transcendental, so they are exact only where the answer is a zero, and
`acos` only at `acos(1)`. The Pi-forms get Niven's larger table -
`asinPi(+-1) = +-1/2`, `acosPi(+-0) = 1/2`, `acosPi(-1) = 1`,
`atanPi(+-1) = +-1/4`, `atanPi(+-inf) = +-1/2`, and `atan2Pi` exact on
every axis and every diagonal. `asinPi(1/2)` is exactly 1/6, which is
rational but NOT dyadic, so it is inexact and still decidable - the
distinction is the whole reason the enumeration is finite.

Rows a porter should not have to infer, each confirmed against MPFR
4.2.2 before it was written down:

- `sinPi` of an integer is a zero with the sign of the ARGUMENT, not of
  `(-1)^n`: `sinPi(1) = +0`, `sinPi(-1) = -0`.
- `cosPi(n + 1/2) = +0` for every n and both signs, because cosPi is
  even and that zero has no sign to carry.
- `tanPi` is `sinPi/cosPi` in every respect, signs included, so
  `tanPi(1) = -0`. At a half-integer it is `+-infinity` with
  **divideByZero** - 7.3's rule for an exact infinity from finite
  operands.
- **`tanPi` cannot overflow at any format here.** A representable
  argument is at least `2^-p` from a pole, so `|tanPi| < 2^p`, far
  inside emax at all four rungs. Overflow cannot occur anywhere in this
  set; underflow can, and comes through the same `round_pack` as
  everything else.
- `sinPi`, `cosPi` and `tanPi` of an infinity are invalid - there is no
  limit there - and `asin`/`acos` and their Pi forms are invalid for
  `|x| > 1`.
- **`atan2(+-0, -0) = +-pi` and `atan2Pi(+-0, -0) = +-1`**: a minus
  zero denominator names the negative real axis. It is the row
  implementations most often miss, and the Pi form is EXACT where the
  radian form is an inexact rounding of pi - which is, in one line, why
  atan2Pi exists as a separate function.
- A quiet NaN does NOT outrank atan2's table the way it outranks pow's.

The vectors carry them in the same `<fmt>-transcend[-<rnd>].jsonl`
files, which now name twenty functions rather than nine. A consumer
built against ABI 0.3 and handed a 0.4 set fails on the NAME of a
function it does not know, which is the refusal it should give.

## The phase-3 radian trigonometry and the hyperbolics (ABI 0.5)

`cft_sin`, `cft_cos`, `cft_tan`, `cft_sinh`, `cft_cosh`, `cft_tanh`,
`cft_asinh`, `cft_acosh` and `cft_atanh`, added 2026-09-03 in one
additive bump. **Correctly rounded** at every format under every
attribute, with clause 9.2.1's special values and exact flags, on
exactly the terms the twenty above are. `sin`, `cos` and `tan` take
their argument in RADIANS; `cft_sinpi` and friends are the same
functions of a half-turn and are a different, cheaper problem.

**What these needed that the twenty did not.** One thing, and only
the first three need it: `x mod (pi/2)` for an argument as large as
2^262143. That is a Payne-Hanek reduction against a stored 2/pi of
270,336 bits (`host/src/mp_2opi.h`, generated, never transcribed,
derived twice), and the cancellation it has to survive is a
MEASUREMENT rather than a theorem - the irrationality measure of pi is
far too weak to bound it at this exponent range. The reduction
measures the cancellation from the bits it has and widens its window
until the working precision is covered; past what the stored constant
covers it REFUSES with `CFT_ERR_INTERNAL`, as everything else in this
contract does rather than return a plausible number.
docs/TRANSCENDENTALS.md has the design, the error bound and the
measured cancellation per format. The six hyperbolics need no
reduction and no new constant: they are exp and log in different
clothes, in the cancellation-free forms phase 1 already justifies.

The signatures follow the twenty exactly - unary, host operations, no
bus word:

```c
cft_sin  (dev, fmt, rnd, a, d, n, &flags);
cft_atanh(dev, fmt, rnd, a, d, n, &flags);
```

**The exact cases are the zeros, and that is a theorem.**
Hermite-Lindemann: `e^z` is transcendental for every nonzero algebraic
z; `sin(x) = a` algebraic makes `e^(ix)` a root of `z^2 - 2iaz - 1`,
and `sinh(x) = a` makes `e^x` a root of `z^2 - 2az - 1`, so both force
x = 0. So sin, tan, sinh, tanh, asinh and atanh are exact only at +-0,
cos and cosh only at 0 (giving 1), acosh only at 1 (giving +0) - and
every other result is inexact. There is no half-integer table here the
way there is for sinPi: an odd multiple of pi/2 is irrational, so no
representable argument is a zero of cos or a pole of tan.

Rows a porter should not have to infer, each confirmed against MPFR
4.2.2 before it was written down:

- sin, cos and tan of an INFINITY are invalid: no limit exists.
- `tanh(+-inf) = +-1` EXACTLY, raising nothing - a limit that happens
  to be representable.
- `atanh(+-1) = +-infinity` with **divideByZero**, 7.3's rule for an
  exact infinity from finite operands; `|x| > 1` is invalid,
  infinities included.
- `acosh(x)` for any x below 1 is invalid - zeros, every negative
  value, and -infinity. `acosh(+inf)` is +infinity.
- sinh and cosh OVERFLOW for a large argument, through round_pack, so
  roundTowardZero delivers maxfinite. tan can overflow too, near a
  pole - how close a representable argument comes to one is measured,
  not bounded; sin, cos, tanh, asinh, acosh and atanh cannot.
- UNDERFLOW happens for sin, tan, sinh, asinh, atanh and tanh of a
  tiny argument and follows clause 7 through the same round_pack.
- A signaling NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.

The vectors carry them in the same `<fmt>-transcend[-<rnd>].jsonl`
files, which now name twenty-nine functions: 242,915
transcendental cases of 478,915 at `make vectors`'
arguments. A consumer built against ABI 0.4 and handed a 0.5 set fails
on the NAME of a function it does not know, which is the refusal it
should give.

## The augmented arithmetic operations (754-2019 clause 9.5)

`cft_augmented_add`, `cft_augmented_sub` and `cft_augmented_mul`,
added 2026-09-03 as part of the 0.6 step. They are unlike everything
above them in two visible ways, and both are the standard's doing
rather than this library's.

**They return a PAIR.** Each writes two arrays: `r`, the operation
rounded, and `e`, the error that rounding made. Together they carry
the exact result the format cannot hold.

```c
cft_augmented_add(dev, fmt, a, b, r, e, n, &flags);
cft_augmented_mul(dev, fmt, a, b, r, e, n, &flags);
```

That is the primitive under compensated summation, exactly rounded dot
products, and double-double arithmetic. Every one of those is written
today out of TwoSum and Dekker splitting - sequences of ordinary
operations that reconstruct the residual by hand, correctly only under
assumptions about association, contraction and intermediate precision
that a compiler is free to break and routinely does. Here it is a
library call with a standard behind it and a vector set scoring it.

**They take NO rounding attribute.** 9.5 fixes the rounding itself:

> This standard specifies a single rounding direction to be used in the
> operations in this subclause, defined as roundTiesTowardZero: the
> floating-point number nearest to the infinitely precise result shall
> be delivered; if the two nearest floating-point numbers bracketing an
> unrepresentable infinitely precise result are equally near, the one
> with smaller magnitude shall be delivered.

That direction is not one of clause 4.3's five attributes, and this
library does not add a sixth attribute for it. There is no `cft_round`
parameter in the signature because there is nothing to pass. Inside,
`round_pack` learns it as an internal rounding DIRECTION
(`CFT_SF_RTTZ`, value 16 - outside the three-bit MODE field the five
attributes encode into), reachable from `host/src/augmented.c` and from
nowhere a caller can steer; the API layer's own attribute range check
is 0..4 and always was.

The tie rule differs from roundTiesToEven **only at an exact midpoint,
and only where the lower neighbour's last bit is odd**. An
implementation that quietly used roundTiesToEven would pass every test
that did not aim at exactly that case, so the vector pools aim at it at
every binade edge the format has.

**HOST operations**, like the clause-5 set and the transcendentals: no
`cft_run` pass is issued, no bus word is produced, `dev` is context. A
tile-composed route - a TwoSum, or an FMA residual for the product -
is a plausible later fast path and would have to reproduce these bits
exactly; it is not what runs today, and the rounding is a reason as
well as the arithmetic, since the tile's five attributes do not include
this one.

`r` and `e` must be different buffers - two writes to one buffer have
no well-defined ordering, so that call is `CFT_ERR_INVALID_ARGUMENT`
rather than a plausible answer. Either may alias `a` or `b`: each
element is read before either output is written.

### The rows a porter should not have to infer

- **Any NaN operand gives the canonical quiet NaN as BOTH results**
  ("propagates a NaN as both results"), invalid raised only for a
  signaling one. An invalid operation - `inf + (-inf)` for the sum,
  `inf * 0` for the product - "produces the same quiet NaN for both
  outputs" with invalid raised.
- **An infinite r gives that infinity as both results.** From an
  infinite OPERAND it signals nothing; from overflow it signals
  overflow and inexact.
- **The overflow threshold is a midpoint, and landing ON it is
  silent.** 9.5: a magnitude "greater than b^emax x (b - 1/2 b^(1-p))
  shall round to infinity with no change in sign", and one "equal to
  b^emax x (b - 1/2 b^(1-p)) shall round to b^emax x (b - b^(1-p))".
  At binary32 that midpoint is `maxfinite + 2^103`: it delivers
  maxfinite and raises **nothing**, because inexact is signalled "only
  when roundTiesTowardZero(x + y) overflows". One ulp higher overflows
  to an infinity in both outputs. Note that overflow here always
  delivers an infinity, in both directions - "roundTiesTowardZero
  carries all overflows to infinity with the sign of the intermediate
  result" - unlike roundTowardZero, which never does.
- **UNDERFLOW is a statement about the ERROR TERM.** It is raised when
  e is "non-zero and lies strictly between +-b^emin". Since e is exact,
  that is **underflow without inexact** - the one place in this
  contract where those two part company, and the one flag combination
  no other operation here can produce. A subnormal `r` with an exactly
  representable residual raises nothing at all: "the operation's
  subnormal and zero results are exact".
- **The sign of a zero e is r's sign**, when the residual is exactly
  zero: `augmentedAddition(-3, 0)` is `(-3, -0)`. r's own zero sign is
  6.3's - `+0` for an exact cancellation (roundTiesTowardZero is not
  roundTowardNegative), the operands' sign for like-signed zeros, the
  XOR of the signs for a product. A residual that is non-zero and
  merely ROUNDS to zero keeps the sign of the exact residual instead,
  by 6.3's rule for a result "that is zero because of rounding".
- **e is always representable for the sum and the difference.** Both
  operands are integer multiples of the format's smallest quantum, so
  the exact sum is one too; the residual is at most half an ulp of r,
  which needs at most p significant bits on a grid the format has. 9.5
  gives augmentedAddition no non-representable case at all, and the
  model and the library both ASSERT it rather than trusting it - the
  model raises, the library returns `CFT_ERR_INTERNAL`.
- **`cft_augmented_mul` has the one exception 9.5 names**: a product
  residual with "non-zero digits ... strictly between
  +-b^(emin-p+1)". It delivers that residual ROUNDED the same way, with
  underflow and inexact raised. That is the only case in which
  `r + e` is not exactly `x op y`, and the only case in which either
  operation raises inexact without overflowing.

### How they are scored

`python/cft_golden/augmented.py` defines every bit and flag. The
vectors get a third schema and a third family of files -
`<fmt>-augmented.jsonl`, one per format, with `"r"` and `"e"` per case
and **no `"rnd"` field**, whose absence is normative: there is no
attribute to record. `cft_conformance` replays them the same two ways
as everything else, one element at a time for exact flags and then as
arrays for the batch loop.

`host/tests/augmented_check.py` is the C-against-model sweep, and it
checks one thing the vectors cannot: the pair identity `r + e == x op
y`, in exact Python integers, **on the library's own output**, over the
whole pool with the two documented exclusions named rather than
tolerated. `host/tools/mpfr_check.c` arbitrates the values against
MPFR - which has no roundTiesTowardZero, so the harness takes the exact
value from MPFR at a precision that provably holds it, proves it did
by requiring a zero ternary, and applies 9.5's tie rule itself; the
banner above `check_augmented` says exactly which half of that is an
independent oracle and which is a restatement.

## The rest of clause 9.4's reductions (part of the 0.6 step)

`cft_reduce` shipped with two of the seven reductions 754-2019 9.4 asks
a language to define. The other five landed 2026-09-03:
**sumSquare, sumAbs, scaledProd, scaledProdSum and scaledProdDiff.**
docs/DETERMINISM.md holds the contract - the tree, the scaling rule,
the exception rules; what belongs HERE is the API shape and why it is
that shape, because the five did not all arrive through the same door.

**Two are new `cft_reduce` opcodes, and they are COMPOSITIONS.**
`CFT_SUMSQ` (28) and `CFT_SUMABS` (29) append to the enum after the
divide/sqrt seeds. Neither is separate hardware and neither needs to
be, for exactly the reason `CFT_DOT` is not: they are the same tree
over a different leaf, so the library issues

    CFT_SUMSQ  ->  cft_reduce(CFT_DOT, a, a)
    CFT_SUMABS ->  cft_run(CFT_ABS, a), then cft_reduce(CFT_SUM)

and the device and software backends agree by construction rather than
by testing. The cost is one scratch buffer for sumAbs - the same trade
`CFT_DOT` already makes for its multiply pass - and one dot for
sumSquare, which costs nothing extra at all.

9.4's one divergent row is applied above both backends, and lazily.
The standard puts an infinity ahead of a NaN for these two, where sum
and dot put NaN first, so a vector holding both returns `+inf`. That
cannot come out of a tree, so the library overrides it - but only after
checking, because no term of either operation is negative, that the
tree's answer is a NaN at all. The scan for an infinity therefore runs
only on a vector that produced one, instead of on every call, which on
a device backend is the host reading the whole input array.

`cft_supports()` accounts for the composition: `CFT_SUMSQ` also needs
the arithmetic group and `CFT_SUMABS` the sign group, so asking about
the opcode itself is the right question and a device missing one says
`CFT_ERR_UNSUPPORTED` before the sequence starts.

### maxall (2026-09-12), the third composition and the only one with no tree

`CFT_MAXALL` (31) is a maximum over the array - 754-2019 9.6 `maximum`,
reduced. It is **not** one of 9.4's seven; it exists because a real
workload asked for it (`cft-rebound/docs/HARDWARE.md`: the convergence
test of an N-body integrator reads `3N x E` deposits per corrector pass,
and a maximum on the device keeps it there).

It is a composition like the two above, but not the same kind. Those are
the sum tree over a different leaf; a maximum cannot be written as a sum
at all. What makes it cheap is the opposite property:

    CFT_MAXALL  ->  ceil(log2 n) x cft_run(CFT_MAX, first half, second half)

**It has no tree contract, and that is the whole design.** 754-2019
`maximum` is exactly associative and commutative *including its flags*:
any NaN yields a canonical quiet NaN rather than a propagated payload,
`invalid` is raised exactly when some operand is signalling and every
element is an operand of one comparison whatever the shape, and
`max(+0, -0)` is `+0`, which is also the maximum among zeros. So every
shape agrees. Three consequences follow, and they are the reason this
reduction is simpler than the other four rather than harder:

- the halving above, a left fold, and the sum tree's own shape all
  return the same bits, so none of them had to be named the contract;
- four tiles fold their partials with a maximum, with nothing to get
  right twice - the failure mode docs/DETERMINISM.md describes for a
  sum's fold cannot arise;
- a hardware maxall, added later behind CAPS2[8] (2026-09-14), returns
  these same bits. The composition is therefore a complete answer and
  not a staging post.

The published sets score it: 1,280 cases across the reduction families,
and `host/tests/reduce_check.py` compares the library's halving against
the model's left fold, which TESTS the associativity above instead of
assuming it.

Two edges, both inherited and both already true of `CFT_SUM`: a single
element is returned verbatim with no flags, so maxall of one signalling
NaN is that pattern rather than a quiet one; and the rounding attribute
is accepted and unused, because a maximum selects an operand instead of
computing one.

The empty array is **-infinity** - the identity that loses to every
other value. 754 says nothing about an empty reduction, so this is
chosen, and chosen so that folding an empty range into a non-empty one
cannot change it. A `+0` there, the additive identity the other four
use, would win against every negative element.

`cft_supports()` answers for it through the reduction group and also the
**min/max** group, since that is what it composes from. And `cft_run`
refuses it, as it refuses every reduction: opcode 31 reaching a tile
would be decoded as elementwise - `cfg_is_reduce` is `(cfg_op ==
8'd24)` - and would write `n` elements where the caller sized one, which
is memory corruption rather than a wrong number - on every tile before
VERSION 0x900. Since it (2026-09-14, ABI 0.13) opcode 31 is a streaming
maximum behind CAPS2[8], so `cft_reduce(CFT_MAXALL)` is one pass on such
a tile; the software definition below is unchanged and `cft_run` still
refuses the opcode as it refuses every reduction. The composition
therefore sits above the backend dispatch, and no tile without CAPS2[8]
ever sees the opcode.

**Three are named host entry points**, because they return a PAIR:

```c
cft_scaled_prod     (dev, fmt, rnd, a,    pr, &scale, n, &flags);
cft_scaled_prod_sum (dev, fmt, rnd, a, b, pr, &scale, n, &flags);
cft_scaled_prod_diff(dev, fmt, rnd, a, b, pr, &scale, n, &flags);
```

A pair does not fit through `cft_reduce`, which delivers one element.
Three names rather than one call with a `kind` argument, and the reason
is the same one docs/DETERMINISM.md's reassignment hazard records:
these issue no device pass, so a `kind` enum would be a second opcode
space living beside `cft_op` with none of an opcode's meaning and all
of its stale-number risk. The arities differ too - one vector, then
two - so three functions check at compile time what one would check at
run time. Every other pair-free host operation in the header is named
this way (`cft_div`, `cft_pow`, `cft_atan2`), and these follow it.

`scale` is an `int64_t` out-parameter; neither it nor `pr` may be NULL.
`pr` receives ONE element. **These are HOST operations** - no `cft_run`
pass, no bus word, `dev` is context - for the plainest possible reason:
there is no tile accumulator for a scaled product. The accumulator
streams ADDs. So there is nothing here for a device to carry, and the
results are bit-identical across backends by construction, the same
shape the transcendentals take.

The cost note is short. `cft_scaled_prod` allocates nothing at all -
its factors are the caller's own array - and the other two allocate one
scratch buffer of `n` elements for the rounded leaf sums. Every node is
one multiply and an exact binade extraction, so a scaled product is
about the price of a dot.

**The vectors carry all seven**, in a THIRD set type:
`<fmt>-reduce[-<rnd>].jsonl`, 512 cases and 10,872 elements per file
(448 and 9,513 until maxall's 64 cases a file joined them on
2026-09-12), 20 files. It had to be a new type - a reduction's operand
is a whole vector whose length is part of the case, and both existing
schemas are one line per case with a fixed number of single-element
operands. The scaled products' cases carry `pr` and `sf` where the
others carry `d`, because a set that recorded only the significand would
score half the operation. Before this the published sets carried no
reductions at all, not even `sum`.

## The rest of table 9.1 (part of the 0.6 step)

`cft_exp2m1`, `cft_exp10`, `cft_exp10m1`, `cft_log2p1`, `cft_log10p1`,
`cft_rsqrt`, `cft_powr`, `cft_pown`, `cft_compound` and `cft_rootn`,
added 2026-09-03. **Correctly rounded** at every format under every
attribute, with clause 9.2.1's special values and exact flags, on
exactly the terms the twenty-nine above are. With these ten the library
implements every operation IEEE 754-2019 table 9.1 lists for the binary
formats.

**What these needed that the twenty-nine did not: nothing but
exactness.** No reduction, no constant beyond the ln 10 and log10 e
phase 1 generates, no new series. Each of the ten has a LARGER
exact-case table than the function it is built from, and each table is
proved closed in docs/TRANSCENDENTALS.md before the Ziv loop under it
is allowed to run - a true value on a rounding boundary being precisely
where that loop does not terminate. exp2m1 is exact at every integer
argument; exp10 and exp10m1 at the non-negative integers their format
can hold; log2p1 and log10p1 wherever 1 + x is a power of two or of
ten, with 1 + x formed EXACTLY on the encoding and never as a rounded
sum; rSqrt at the even powers of two; rootn wherever the odd
significand is a perfect |n|-th power and |n| divides the exponent.

Seven of the ten follow the shapes above:

```c
cft_exp2m1(dev, fmt, rnd, a, d, n, &flags);       /* unary */
cft_powr  (dev, fmt, rnd, a, b, d, n, &flags);    /* two encodings */
```

**The other three do not, and 9.2.1 is why.** `pown`, `compound` and
`rootn` read an INTEGER second operand - "n is a finite integral value
in integralFormat" - so they take an `int64_t` array beside the
encoding array rather than a second encoding that would have to be
interrogated about whether it is integral. That is the question `pow`
has to ask and the reason `pow` and `pown` are different functions at
all. The element count moves to `count`, which is the one place in this
header where those two names are not the same argument:

```c
const int64_t ns[3] = { 2, -3, 5 };
cft_pown(dev, CFT_FP64, CFT_RNE, a, ns, d, 3, &flags);
```

`n` is read PER ELEMENT and must not be NULL; a NULL is
`CFT_ERR_INVALID_ARGUMENT`, like the missing second operand of a binary
entry point.

Rows a porter should not have to infer, each confirmed against MPFR
4.2.2 before it was written down - and **three of them are rows where
this contract follows the standard and MPFR does not**:

- **`rSqrt(+-0)` is `+-infinity`** with divideByZero: the sign
  SURVIVES. `mpfr_rec_sqrt` returns +infinity for both zeros, which
  predates 754-2019's rSqrt row. `rSqrt(+inf)` is +0; `x < 0` is
  invalid. rSqrt can neither overflow nor underflow at any rung.
- **`powr` is not `pow`.** `powr(x, y)` for x < 0 is invalid for EVERY
  y, a NaN included; `powr(+-0, +-0)`, `powr(+inf, +-0)` and
  `powr(+1, +-inf)` are invalid; and `powr(qNaN, y)` is a quiet NaN
  where `pow(qNaN, 0)` is 1. **`powr(+1, qNaN)` is a quiet NaN** - the
  standard's row is "powr(+1, y) is 1 for FINITE y" and it lists
  `powr(x, qNaN)` for x >= 0 separately - where `mpfr_powr` returns 1.
  `powr(+-0, y)` is +infinity with divideByZero for a finite y < 0 and
  +infinity SILENTLY for y = -infinity, the same pole-versus-limit
  distinction pow's table makes.
- **`compound(x, 0)` for an x below -1 is invalid**, not 1: the row
  reads "compound(x, 0) is 1 for x >= -1 or quiet NaN", which makes
  that case rather than states it. `compound(qNaN, 0)` IS 1.
  `compound(-1, n)` is +infinity with divideByZero for n < 0 and +0 for
  n > 0; `compound(+-0, n)` is 1.
- `pown(x, 0)` is 1 for any x that is not a signaling NaN, an infinity
  and a quiet NaN included. `pown(+-0, n)` is `+-infinity` with
  divideByZero for an odd n < 0 and `+infinity` for an even one.
- **`rootn(x, 0)` is invalid for every x**, a quiet NaN included: zero
  is outside the domain. `rootn(x, 1)` is x, exactly and silently. A
  negative operand with an EVEN n is invalid. `rootn(x, 2)` is
  `cft_sqrt(x)` on every input except `x = -0`, where the standard's
  own NOTE says they differ: `rootn(-0, 2)` is +0 by the even-n row and
  `squareRoot(-0)` is -0.
- `log2p1(-1)` and `log10p1(-1)` are -infinity with **divideByZero**;
  an operand below -1 is invalid, -infinity included.
- A signaling NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.

The vectors carry them in the same `<fmt>-transcend[-<rnd>].jsonl`
files, which now name thirty-nine functions and carry one new field:
`"n"`, a SIGNED DECIMAL rather than an encoding, present only for the
three that read an integer exponent. A consumer that knows the names
but not that field fails on a missing key, which is the refusal it
should give.

`rSqrt` is host work like the other thirty-eight - the evaluator's own
square root and one division. The tile's RSQRT_SEED opcode is a
plausible later fast path for the narrow formats, exactly as one is for
exp; it would have to reproduce these bits exactly, which makes it an
optimisation rather than a different answer, and nothing here reads it.

## Character sequences and NaN payloads (part of the 0.6 step)

`cft_from_decimal_char`, `cft_to_decimal_char`, `cft_from_hex_char`,
`cft_to_hex_char`, `cft_format_decimal_digits`, `cft_get_payload`,
`cft_set_payload` and `cft_set_payload_signaling`, added 2026-09-03.
The last REQUIRED part of clause 5 this library lacked, and clause
9.7's three payload operations alongside it.

754-2019 5.12 opens with a **shall**: an implementation "shall provide
conversions between each supported binary format and external decimal
character sequences such that, under roundTiesToEven, conversion from
the supported format to external decimal character sequence and back
recovers the original floating-point representation". Until now this
library provided none of them, which meant every caller who reached it
from a text format - a config file, a CSV, a REPL - was reaching some
other library's rounding on the way in, and some other library's
opinion of "enough digits" on the way out. That is precisely the hole
this project exists to close, and it was open at the edge of the API.

**Correctly rounded in both directions, in the caller's attribute,
with exact flags - and the standard's H is UNBOUNDED here.** 5.12.2
lets an implementation cap the digit count it will round correctly at
some H >= M + 3, and NOTE 1 spells out what a capped implementation
then costs its users: "conversions of greater than H significant
digits might incur additional rounding of the order of 10^(M-H)".
This library incurs none of it, at any length, because the arithmetic
is exact: a decimal sequence's value is a RATIONAL, an encoding's
value is a dyadic rational, and both are held exactly in integers.

### The exactness argument, in one paragraph

A decimal sequence denotes `(-1)^s * D * 10^K` exactly - write it as
`num/den`, with `den` either 1 or `10^-K`. The binary window is ONE
integer division: with `q = bitlen(num) - bitlen(den) - (p + 3)`,
`m = floor(num / (den * 2^q))` lands with `p+3` or `p+4` bits and the
remainder says whether anything is left below it. The value is then
exactly `(m + eps) * 2^q` with `eps` in [0, 1), non-zero exactly when
the remainder is - which is `round_pack`'s own precondition. So the
rounding and every flag come from the library's single rounding
authority, on an exactly derived operand, at any length. The other
direction needs no rounding authority at all in the exact mode:
`m * 2^e` is `m * 5^-e * 10^e` for `e < 0` and `m << e` otherwise, both
integers, and their decimal digits ARE the answer.

`host/src/chars.c` carries its own growable natural number to do it,
and that is not a preference. `bigint.h` is FIXED at 2048 bits, which
is exactly right for what it was written for - softfloat.c bounds its
alignment and needs about 1200. Decimal conversion cannot be bounded
that way: the exact decimal of the smallest binary256 subnormal is
`5^262378 * 10^-262378`, about 183,000 significant digits and 609,000
bits, and reading that same sequence back needs `10^262378`, another
872,000. Those lengths come from the FORMAT, not from a design choice.

### The two shapes, and why they differ

The `from_` calls are BATCHES - an array of C strings in, a dense
array of encodings out, `n` arbitrary, the flag word the OR across it,
the same shape as every other entry point in the header. The `to_`
calls are PER ELEMENT, and have to be: an output sequence's length is
not known until the conversion has run, and it is wildly non-uniform -
three bytes for `inf`, about 183,000 for the exact decimal of the
smallest binary256 subnormal. No dense output array can hold that, and
a batch would need three parallel arrays (buffers, capacities,
lengths) that a caller could not size in advance anyway, so it would
degenerate into the per-element two-call protocol with extra ceremony.

Sizing is that protocol and `*len` is ALWAYS set - on success and on
refusal alike - to the bytes required including the NUL. Pass `cap = 0`
with `out = NULL` to ask, then call again. A buffer too small is
`CFT_ERR_INVALID_ARGUMENT` with `*len` set and NOTHING written: a
truncated number is a wrong answer that looks like a right one.

```c
size_t need = 0;
cft_to_decimal_char(dev, CFT_FP256, CFT_RNE, x, 0, NULL, 0, &need, &f);
char *s = malloc(need);
cft_to_decimal_char(dev, CFT_FP256, CFT_RNE, x, 0, s, need, &need, &f);
```

`digits == 0` is 5.12.2's EXACT conversion; `digits >= 1` is that many
significant digits correctly rounded, trailing zeros kept so a caller
who asked for H can count H. `cft_format_decimal_digits` returns
Pmin - 9, 17, 36 and 73 - derived from `1 + ceiling(p * log10 2)`
rather than tabulated, and that is the count at which the round trip is
guaranteed.

**The one cost note this set carries**, in the tradition of `cft_rem`'s:
the H-digit mode derives the FULL exact expansion and then rounds the
digit string, so writing a value near either end of fp128's or fp256's
exponent range costs the same whether a caller asks for 5 digits or for
all 183,000 - about 0.7 s for the widest fp256 case on the host these
numbers come from, against about 5 microseconds for pi at binary64
whether exact or at seventeen digits. Ordinary magnitudes are
microseconds; the extremes are the price of the format. That
keeps one code path and one correctness argument for both modes, which
is the trade this library makes everywhere; a second, shorter route for
small H would have to reproduce these digits exactly.

### The syntax accepted, and the refusal

```
decimal   sign? ( digit* "." digit* | digit+ )  ( [eE] sign? digit+ )?
hex       sign? "0" [xX] ( hexDigit* "." hexDigit* | hexDigit+ )
                         [pP] sign? digit+
either    sign? ( "inf" | "infinity" | "nan" | "snan" ) payload?
payload   "(" ( digit+ | "0" [xX] hexDigit+ ) ")"
```

At least one digit in the significand, the words case-insensitive, and
the hexadecimal form's binary exponent REQUIRED - 5.12.3's grammar
writes `{decExponent}`, not `{decExponent}?`. No leading or trailing
whitespace, no digit separators, no locale, no hexadecimal in the
decimal parser or decimal in the hexadecimal one. Anything else is
`CFT_ERR_INVALID_ARGUMENT` with nothing written, and `bad_index`
reports WHICH element of the batch was at fault - a caller reading a
file of numbers needs the line and not just the verdict. What this
library writes, this library reads back.

### Two contract choices a porter must not miss

**A signaling NaN is written `snan`, not `nan`, and no conversion here
raises invalid.** 6.2 exempts "the conversions described in 5.12" from
the rule that a signaling NaN signals invalid, and 5.12.1 offers two
spellings: write `snan`, or write `nan` and signal invalid. This
contract takes the first, because the second loses the distinction the
round trip is required to keep. NaNs carry their payload and their sign
through both directions - these are ENCODING operations, like
abs/negate/copySign/select, and docs/DETERMINISM.md's canonical-NaN
rule governs arithmetic.

**9.7's admissible payload set is the format's payload field**, bits
d2..d(p-1) of the trailing significand (6.2.1): `0 .. 2^(man_w-1) - 1`,
and `1` upward for the signaling form, because payload 0 with the quiet
bit clear is an INFINITY encoding rather than a NaN. The test is on the
VALUE, so `-0` passes it as the integer zero - 754 settles that `-0`
equals `0`, and every other value-based operation in this contract
reads it the same way. Anything outside the set gives `+0`, which is
9.7's own answer, and `getPayload` of a non-NaN is `-1`, which is also
9.7's. All three signal nothing, so none of them has a flags argument.

### What has been run

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (60 sets: 20 opcode, 20 transcendental, 20 character) | 648,731 at the generator's defaults, 492,731 at `make vectors`' | every case, bits, flags and refusals |
| `character_check.py`, both directions vs the model | 20,819 | zero disagreements, per-element flags |
| MPFR parity, the four conversions, five attributes, four rungs | 20,172 of 298,904 | zero value AND zero flag mismatches |
| `cft.hpp` vs `cft.h`, every entry point twice | 210,511 at C++17 and again at C++20 | identical encodings, flags and characters |
| `test_cftmpfr.py` | 640 | pass |

## The status word, the predicates, and 9.6's magnitude four (ABI 0.7)

Three things clause 5 asked of the library and one clause 9 recommends.
They arrived together because they share a seam.

### The status word (7.1, 5.7.4)

```c
#define CFT_FLAGS_ALL /* the five cft_exception bits, as one mask */

void     cft_lower_flags(cft_device *dev, uint32_t mask);
void     cft_raise_flags(cft_device *dev, uint32_t mask);
int      cft_test_flags(cft_device *dev, uint32_t mask);
uint32_t cft_save_all_flags(cft_device *dev);
void     cft_restore_flags(cft_device *dev, uint32_t saved, uint32_t mask);
int      cft_test_saved_flags(uint32_t saved, uint32_t mask);
```

`flags_out` is unchanged and still answers "what did THIS call raise".
The word answers the other question 7.1 asks - "what has been raised
since the caller last lowered anything" - and it is the caller who
lowers it, nobody else. A fresh device opens with every flag down.

Reading the six against 5.7.4, in case a porter is holding the
standard: `mask` is 5.7.4's exceptionGroup, "any subset of the
exceptions", so every one of the six takes one; `cft_test_flags` is
"whether ANY of the flags ... are raised" and so returns 1 or 0 rather
than the intersection, which a caller could mistake for a flag word;
`cft_restore_flags` RESTORES rather than ORs, so a flag inside the mask
that is low in `saved` comes back low - that is the only reading under
which `cft_restore_flags(dev, cft_save_all_flags(dev), CFT_FLAGS_ALL)`
is the identity 5.7.4 wants it to be, and it is the one an OR-only
implementation gets wrong while still passing a round-trip test;
`cft_test_saved_flags` takes no device, because 5.7.4 puts the saved
word in the first operand and there is nothing else involved.

A NULL device is accepted by all of them and behaves as a handle whose
word is permanently zero: the mutators do nothing and the tests answer
0. That matches `cft_close()` and `cft_buffer_free()`, which have
always tolerated NULL.

**Rows a porter should not have to infer.** All of these are tested,
and each of them is a way a plausible implementation goes wrong:

| situation | the word after |
|---|---|
| a call that raises nothing | exactly what it was - ORing zero is the identity |
| `cft_class`, `cft_total_order*`, the 9.7 payload three | unchanged; they are non-computational and have no flag word at all |
| `cft_div(1, 0)` | divideByZero alone. The Newton scaffolding is inexact on almost every step and contributes nothing |
| a batch call | one OR of every element's flags, in one step, the same word `flags_out` receives |
| `cft_reduce(CFT_SUMABS)` over a vector holding an infinity and a signalling NaN | 9.4's override REPLACES the tree's flags, and the word gets the override's, not both |
| two contexts (C++ or Python) over one device | one word between them, which is what 7.1 describes |

Internally every producing entry point ends with one call,
`cft_flags_emit(dev, acc, flags_out)`, and that is the only thing in
the library that can raise the word. A new entry point therefore costs
one line, and a composed one brackets its internal passes with
`cft_flags_mute` so that scaffolding never reaches the word. Both are
internal (`host/src/softfloat.h`); they are described here because the
next entry point somebody adds needs to know about exactly two of
them.

**The word never influences a result.** Nothing reads it back - not a
rounding, not a special case, not a branch - so determinism is exactly
what it was. See docs/DETERMINISM.md.

### The conformance predicates (5.7.1)

```c
int cft_is754version1985(void);   /* 0 */
int cft_is754version2008(void);   /* 0 */
int cft_is754version2019(void);   /* 1 */
```

Constants, no device, no format, safe before `cft_open`. What each
rests on is in `cft.h` and in docs/COMPLIANCE.md; the one that is
easily misread is 2008, which is false not because something is
missing but because 754-2008 required `minNum`/`maxNum`/`minNumMag`/
`maxNumMag` in its 5.3.1 and 2019 replaced them with 9.6's, whose
signaling-NaN rule differs. This library implements the 2019
semantics.

### 9.6's magnitude forms

```c
cft_status cft_min_mag   (cft_device *dev, cft_format fmt,
                          const void *a, const void *b, void *d,
                          size_t n, uint32_t *flags_out);
cft_status cft_max_mag   (...);   /* same signature */
cft_status cft_minnum_mag(...);
cft_status cft_maxnum_mag(...);
```

HOST entry points of the `nextUp` kind: no rounding argument, because
there is no rounding - 9.6 selects one of the operands rather than
computing a value. No opcode either, so they do not gate on the
device's opcode groups and are available on a bitstream that does not
carry the min/max group at all. `d` may alias `a` or `b`.

The definitions, the NaN rule each inherits, and the equal-magnitude
tie are in docs/DETERMINISM.md and quoted in `cft.h`. The two things a
caller most often wants stated plainly:

- `cft_min_mag(-3, +2)` is `+2`, where `CFT_MIN(-3, +2)` is `-3`. The
  magnitude decides and the sign has no vote.
- `cft_max_mag(+3, -3)` is `+3` and `cft_min_mag(+3, -3)` is `-3`,
  both orders of the operands, because equal magnitudes fall through
  to `maximum`/`minimum`. The same rule gives `-0` for the minima and
  `+0` for the maxima of the two zeros.

### How they are scored

| check | cases | result |
|---|---|---|
| `minmax_mag_check.py`: the four vs the golden model at all four formats - scalar, batch, every equal-magnitude pair, aliasing and refusals; plus the status word against 7.1's own sentences and the three predicates | 53,517 | zero disagreements |
| `python/tests/test_minmax_mag.py`: the model against an independent reading of the encoding, and against CPython's binary64 at fp64 | 94 | pass |
| `cft_conformance` replay of the four new `-minmaxmag` sets, one element at a time and then as arrays | 2,432 per format | every case, bits and flags |
| MPFR parity: `mpfr_cmpabs` for the magnitude ordering and `mpfr_min`/`mpfr_max` for the equal-magnitude tie, with 9.6's NaN rules restated | see docs/VALIDATION.md | zero value AND zero flag mismatches |
| `api_test.c`, `cpp_api_test.cpp`, `test_cftmpfr.py` | the C, C++ and Python surfaces | pass |

One line about the MPFR row, because it is the only place in this
package where an oracle and a restatement sit in the same function.
The ORACLE half is MPFR's and it is the whole numeric content:
`mpfr_cmpabs` decides `|x|` against `|y|` in MPFR's own arithmetic, and
`mpfr_min`/`mpfr_max` decide the equal-magnitude case - the MPFR manual
defines them exactly as 754 defines minimum and maximum on numbers,
signed zeros included. The RESTATEMENT half is the NaN handling, and it
has to be: MPFR has no signaling NaN, and `mpfr_min` implements only
the `...Number` NaN rule, so the plain forms' rule has no counterpart
to compare against. Those rows are two readings of 9.6 scored against
each other, not two oracles, and `host/tools/mpfr_check.c` says so at
the top of the block.
## The formatOf arithmetic across the formats (754-2019 5.4.1, the 0.7 step)

`cft_formatof_add`, `_sub`, `_mul`, `_div`, `_sqrt` and `_fma`: the six
arithmetic operations with the **operands in one binary format and the
result in another**, rounded once. Every arithmetic entry point above
this section takes one `cft_format` and uses it for the operands and
the result both; these take two.

```c
/* a and b are binary64 encodings; d receives binary32 ones. */
cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE, a, b, d, n,
                 &flags, &bus);
```

5.4.1 requires this for every ordered pair of supported arithmetic
formats, which is sixteen pairs on this ladder, so it is a conformance
item rather than a convenience - the first of the items
docs/COMPLIANCE.md listed at 0.6, closed here.

### Six entry points, not one dispatcher

The choice a reader will ask about. A dispatcher would need a first
argument naming the operation, and the only such namespace this library
has is `cft_op` - an OPCODE space that is on the wire, in the device's
opcode field, and in every published vector set. **Two of these six
have no opcode and never will**: division and square root are
compositions here, not tile instructions, so a dispatcher keyed on
`cft_op` could not express half the clause without inventing opcode
numbers for things the hardware does not do. The arities differ too -
one, two and three operands - so one signature would carry three
pointers whose meaning changed per operation. That is `cft_run`'s
shape, and it pays for it with the steering table, which exists only
because ADD, SUB, MUL and FMA really are one hardware opcode. These six
are not.

### Which direction does what, and why a caller should care

**Destination at least as wide as the source.** The operands are
widened exactly with `cft_convert` and the existing same-format
operation is issued. The ladder nests, so the widening rounds nothing
and the operation's own rounding is still the only one. The point of
going this way rather than computing on the host is that the arithmetic
still runs where it would have run: on a device backend the `cft_run` /
`cft_div` / `cft_sqrt` underneath is a tile pass, and `bus_out` carries
its fault word.

**Destination narrower.** The exact result is formed on the host and
rounded ONCE against the destination's descriptor, through the same
`cft_sf_round_pack` seam every other operation in this library rounds
through. No tile pass; `bus_out` reads 0.

### The rows a porter should not have to infer

- **Every exception belongs to the destination.** `2^100 * 2^100` is an
  unremarkable binary64 multiply and an overflow into binary32 -
  infinity under roundTiesToEven, the largest finite under
  roundTowardZero, `overflow | inexact` either way. `2^-150` is an
  ordinary binary64 normal and exactly half of binary32's least
  subnormal, so it is a tie between zero and that subnormal, and 7.5's
  underflow rises with inexact whichever side the attribute takes.
- **The wider destination has the wider range.** The square of
  binary32's least subnormal vanishes in binary32 and is an exact
  binary64 normal, `2^-298`.
- **Square root crosses ranges in both directions**, which the
  same-format square root cannot: the root of binary256's largest
  finite is about `2^131071`, far above binary32's emax, and the root of
  its least subnormal is about `2^-131189`, far below binary32's floor.
- **`x + 0` still rounds.** It is x exactly, but x is a source value and
  the destination may not hold it, so the single rounding still happens
  and still reports its flags. Returning the operand's encoding is right
  in the same-format case and wrong here.
- **Specials are built in the destination.** A signaling NaN operand
  raises invalid (6.2.1) and delivers the destination's canonical quiet
  NaN; `divideByZero`, `inf - inf` and `0/0` likewise deliver the
  destination's encodings.
- **`d` must not overlap `a`, `b` or `c`.** The elements change size, so
  an in-place call would overwrite operand i+1 while writing result i.
  That is `cft_convert`'s rule, for `cft_convert`'s reason, and it is
  not policed.
- **The same-format pairs are the operations that were already here**,
  bit for bit and flag for flag.

### Why division and square root are not double rounded

Because the shortcut gives the wrong answer, and this is worth stating
plainly since docs/COMPLIANCE.md proposed it at 0.6. Rounding in the
source format and converting down is innocuous for the basic operations
when the intermediate carries at least 2p + 2 bits - and 53 >= 2x24 + 2,
113 >= 2x53 + 2, 237 >= 2x113 + 2 all hold on this ladder. **The rule
does not apply**: its hypothesis is that the OPERANDS carry the
destination's precision, and here they carry the source's. A quotient
or a root of two wide values can sit as close as it likes to a narrow
midpoint, so the first rounding lands exactly on it, the second ties to
even, and the answer is one ulp low with the same flag word.

`python/cft_golden/formatof.py`'s `double_rounding_witness()` builds the
counterexample from the format descriptors for division, square root and
fused multiply-add on every one of the six narrowing pairs;
docs/DETERMINISM.md carries the constructions. A porter's first
temptation here is the composition, so the published sets carry all
eighteen witnesses and a port that took it fails on them by name.

### Comparison across formats (5.11) needs no entry point

Widen the narrower operand with `cft_convert` - exact - and use the
comparison you already have. A signaling NaN raises invalid on the way
through, exactly as it would have in the comparison, so the signal is
neither lost nor doubled. `python/cft_golden/formatof.py`'s `compare()`
states the composition and the C++ test exercises it.

### The other surfaces

`cft.hpp` puts the six on `cft::device` and adds free function
templates `cft::formatof_add<SF, DF>` and friends - free rather than
members of `basic_context<F>`, because a context is bound to one format
and these have two; the typed form makes a mismatched operand a compile
error. `cftmpfr` puts them on the DESTINATION `Context`
(`lo.formatof_add(x, y)`), which is MPFR's own shape - `mpfr_add(rop,
op1, op2, rnd)` already rounds into rop's precision whatever the
operands' is - with `batch.formatof_*` taking the source context
explicitly, since a bytes buffer carries no format of its own.

### How they are scored

| layer | what it settles |
|---|---|
| `python/tests/test_formatof.py` | the model against exact rationals rounded by a reference written from 4.3, square root by squaring rather than by rooting, the widening identity, bit-identity with the single-format functions, the destination's boundaries, and the eighteen witnesses (plus the FMA family against intermediates from 30 to 1000 bits) |
| `host/tests/formatof_check.py` | the C against the model over all sixteen ordered pairs, six operations, five attributes, per element and as arrays, plus the witnesses, the same-format alias against `cft_run`/`cft_div`/`cft_sqrt`, and the refusals |
| `host/tools/mpfr_check.c` | both against GNU MPFR, which is a FULL oracle here: 5.4.1's definition is a literal description of `mpfr_add` and friends with the operand variables at the source precision and the result variable at the destination's |
| `vectors/out/<sfmt>-to-<dfmt>-formatof[-<rnd>].jsonl` | anyone else's implementation, 80 sets |
| `host/tests/api_test.c`, `cpp_api_test.cpp`, `test_cftmpfr.py` | the refusals, the aliasing, and the rows an independent reading of 5.4.1 decides |

## What is deliberately not in the first version

- **Asynchronous submission.** Everything blocks today. A future
  `cft_run_async` returning a handle is additive.

New capability gets new functions. That keeps `cft_run` positional and
FFI-friendly rather than hiding behind an extensible descriptor struct
that every binding then has to lay out by hand.

## The one place the C is not a transliteration

Everything in `host/src/softfloat.c` follows
`python/cft_golden/softfloat.py` line for line, on purpose, so the two
can be read side by side and a divergence shows up as a structural
difference rather than as a subtle one. There is exactly one exception,
and it is worth stating plainly because it is where a bug would hide.

The model computes the fused multiply-add's sum **exactly**: it shifts
both terms to a common exponent and adds, in unbounded integers. For
fp256 that alignment can span the entire exponent range - the product
of two large normals against the smallest subnormal addend is about
790,000 bits wide. Correct, and unusable: a hundred kilobytes of
shifting per element.

So `libcft` bounds the alignment. When the two terms' leading bits are
more than `2p+4` apart, the smaller one lies entirely below the
larger's last bit and cannot influence anything except a sticky bit, so
it becomes one. When they are closer than that, the intermediate is
provably narrow - at most about `5p+3` bits, 1188 for fp256 - and the
sum is computed exactly, as the model does. The derivation, including
why `2p+4` and not something smaller, is written out in the comment
above `sf_fma()`.

That argument is checked rather than trusted, three ways:

- `host/tests/diff_check.py` builds operand triples whose exponent
  separation lands **on and around the cutoff**, in both directions,
  and compares against the model at every precision under every
  rounding attribute. Random operands essentially never land near that
  line, and never land beyond it with the addend dominating, so those
  cases have to be constructed deliberately.
- `--coverage` on the same script reports which path the cases
  actually took. A boundary test that never reaches the boundary passes
  for the wrong reason, and passing for the wrong reason is
  indistinguishable from passing until the day it matters.
- Every width bound is enforced at runtime. The bignum operations
  return an overflow indication rather than truncating, and
  `cft_run()` turns one into `CFT_ERR_INTERNAL`. If the derivation
  above were wrong, the library would refuse to answer rather than
  answer incorrectly.

## Verifying a port

`cft_conformance()` replays the vector sets under `vectors/out`
through whichever backend is open and reports the first disagreement.
`cft-selftest` is that function with a `main()` around it.

This is the acceptance test for a new language binding, a new backend,
a new device generation, or somebody else's independent
implementation. The guarantee at the top of this document is not
something to take on trust - it is machine-checkable, and the vectors
have existed since before the hardware did.

On success it reports what it checked, not just that it passed: a run
that quietly skipped every set would otherwise be indistinguishable
from a clean one.

## What has actually been run

    make vectors            # 20 sets: 4 formats x 5 rounding attributes
    make libcft             # build
    make libcft-test        # contract tests, replay, C-vs-Python
    make libcft-diff        # against the golden model, boundary-targeted
    make libcft-docker      # the same tests on a second platform

As of the commit that added the library, on x86-64 Windows with GCC
16.1 (MinGW, msvcrt):

| check | cases | result |
|---|---|---|
| `cft_conformance` replay | 228,000 | every case, bits and flags |
| differential vs the golden model | 213,000 | every case, bits and flags |
| contract tests (`api-test`) | every check | pass |
| C example vs Python example | 4 checksums | identical |

Reductions were added later and are checked the same two ways - the
tree against the golden model, and the multi-tile split against the
whole-array answer:

| check | cases | result |
|---|---|---|
| `reduce_check.py`, libcft vs the golden model | 7,640 reductions across 4 formats | tree, bits and flags agree |
| `reduce-parts`, every canonical partition vs the whole | 4,060 partitions (4 formats x 29 sizes x 7 part counts x 5 attributes) | every partition reproduces the whole |

And the divide/sqrt era (2026-08-31 onward), same discipline, more
oracles - numbers as first recorded (2026-08-31 and 2026-09-01), with
docs/VALIDATION.md as the ledger:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (regenerated sets incl. the seed opcodes) | 392,000 | every case, bits and flags |
| `divsqrt_check.py`, cft_div/cft_sqrt vs the model | 29,124 + a chunk-boundary batch | zero disagreements, per-element flags |
| `clause5_check.py`, the completion set vs the model | 112,372 (all entry points, 16 conversion pairs, chunk-crossing batches, the fp256 full-gap remainder) | zero disagreements, per-element flags |
| native-oracle soak vs the host CPU's IEEE hardware | 23.875 billion (exhaustive fp32 sqrt, all five attributes) | zero value or flag disagreements |
| MPFR parity, all four formats, all five attributes | 999,000 | zero disagreements |

And the transcendental era (2026-09-02), where MPFR is not the third
oracle but the only one - libm is neither correctly rounded nor
reproducible, so there is no CPU campaign to calibrate against even at
fp32:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (40 sets: 20 opcode, 20 transcendental) | 456,325 | every case, bits and flags |
| `transcend_check.py`, the nine vs the model | 77,315 | zero disagreements, per-element flags |
| the same, with the library forced to start below the precision it needs | 72,275 | identical through the escalation path |
| MPFR parity, the nine functions | 95,680 | zero value AND zero flag mismatches |
| `cft.hpp` vs `cft.h`, every entry point twice | 3,267 at C++17 and again at C++20 | identical encodings and flags |

And the clause-9.5 augmented operations (2026-09-03), where the oracle
question has its own answer - MPFR has no roundTiesTowardZero, so the
harness takes the exact value from MPFR and applies the tie rule
itself:

| check | cases | result |
|---|---|---|
| `cft_conformance` replay (44 sets: 20 opcode, 20 transcendental, 4 augmented) | 724,531, of which 89,616 augmented | every case, BOTH outputs and flags, replayed twice |
| `augmented_check.py`, the three vs the model | 149,112 comparisons at `--trials 400` | zero disagreements, per-element flags |
| the pair identity `r + e == x op y`, exact integers, on the library's output | 80,209 pairs | exact, plus 8,316 residuals delivered rounded per 9.5's one non-representable case |
| the FAR/NEAR alignment split, walked across its decision | 70,200 comparisons | C == model on every one |
| MPFR parity, the three operations | 21,492 (5,373 per format) | zero value AND zero flag mismatches |
| `cft.hpp` vs `cft.h`, every entry point twice | 4,311 at C++17 and again at C++20 | identical encodings and flags |

The second table is the one that matters for tiles. It is the software
statement of the property the hardware has to keep: cutting a
reduction into k canonical ranges and folding the partials gives the
same bits as not cutting it, for every k the library would ever
choose.

And the part that is actually the product. The same source built by
**GCC 13.3 on Ubuntu 24.04 against glibc**, running in the project's
own simulation container, prints:

    fp32   n=4096 rne  checksum 0x9af9d3973816adcf  flags 0x10
    fp64   n=4096 rne  checksum 0x04110a4c30c6df4d  flags 0x10
    fp128  n=4096 rne  checksum 0xb815aa4a3a3eb024  flags 0x10
    fp256  n=4096 rne  checksum 0x0eea048c14040a4e  flags 0x10

character for character what the Windows build prints. Two operating
systems, two C libraries, two compiler major versions, 16,384 fused
multiply-adds per line at four precisions - and one set of bits. That
is the claim this project exists to make, made on the cheapest
hardware in the building, with no card involved.

Running it on a second platform is also what found the two portability
bugs worth having: `make clean` removed only the current platform's
shared library, and the Python loader took the first library it found
rather than the one for the platform it was running on. Both are the
same mistake - assuming one machine - which is the mistake this
library is supposed to be immune to.

The differential run reached the far path 1,146 times at fp256 with
the product dominating and 885 times with the addend dominating,
roughly evenly split between like and unlike operand signs, and the
widest exact intermediate it produced was 952 bits against a container
sized for 2048. Those numbers come from `make -C host coverage`, so
they are re-derivable rather than remembered.

## Calling it from somewhere else

`host/examples/` has the same program in nine languages - C, C++,
Python, Fortran, Rust, Julia, Go, C# and R. Eight of them print the same
four checksum lines and the seven besides C are diffed against the C
example's bytes - Python by `make -C host test`, the other six by their
own `make -C host lang-*` leg; the Fortran example prints decimals
instead, so its `lang-fortran` leg builds and runs it through
`iso_c_binding` and compares nothing - its expected output sits in its
own header and is compared by eye rather than against the C bytes
(docs/COMPATIBILITY.md has the per-language platforms and dates). Three
of them carry the argument this document makes:

- `vector_fma.c` - C, linked against the static library.
- `vector_fma_ctypes.py` - Python, via `ctypes.CDLL` and seven
  `argtypes` lines. No build step, no binding generator, no pyxrt.
- `vector_fma.f90` - Fortran, via `iso_c_binding`, verified with
  gfortran 13.3. A native `real(c_double)` array goes straight to
  `c_loc()` and is used in place: no conversion step, because the
  buffers are specified as dense little-endian interchange encodings
  rather than as a struct. That is the argument at the top of this
  document - that Fortran is the language this contract most needs to
  reach, and that reaching it should cost an interface block and
  nothing else - demonstrated rather than asserted. `make -C host
  fortran` runs it, and the simulation container carries gfortran so
  CI can too.

The C and Python versions print a checksum of the output buffer, and
`make libcft-test` diffs them. Identical output from two languages
through one library is the cross-language claim reduced to something
that either passes or fails.

## Weak links this exposes in the hardware contract

Writing the header surfaced two places where the device side was not
future-proof enough to sit behind a stable ABI. **Both are now
fixed** - which is the argument for writing a header before an
implementation: neither gap was visible until something had to be
promised to a caller.

1. **`CAPS` reported precisions but not operations.** A host could ask
   which formats a bitstream carried and not which opcodes it
   implemented - fine while every build has every op, actively wrong the
   moment one does not, and `cft_supports()` would have had to guess
   from the version number. CAPS[15:8] is now an opcode-group bitmask:
   arithmetic, sign, min/max, predicate, integer, reduction, divide/sqrt
   and the sequencer, on bit 15, which was reserved for conversion. Groups
   rather than 256 individual bits, because opcodes arrive in groups and
   a bit per opcode is a register nobody keeps current.

2. **Unassigned opcodes silently did arithmetic.** Opcode 15 and
   everything from 24 up fell through to the FMA datapath with
   unsteered operands - deterministic, so the contract held, but the
   wrong failure: a host issuing an opcode its bitstream predates got
   a plausible number rather than an error. They now return the
   canonical quiet NaN with **invalid** raised, in hardware and in the
   golden model alike, which is what `CFT_ERR_UNSUPPORTED` reports
   against.

## What the workloads asked of the host API (2026-09-04)

The five workload tools (docs/BENCHMARKS.md) and their browser demos
(docs/DEMOS.md) surfaced three asks of this API, recorded rather than
built; docs/SEQUENCER.md holds the program-model ones.

1. **A per-element flag output on `cft_run` and `cft_program_run`**,
   optional, beside the union `flags_out` returns. The Collatz tool
   certifies exactness per element with a witness FMA because the
   union cannot say which element raised inexact; the ask would remove
   the witness and the cost of computing it.
2. ~~**A scalar (stride-0) operand for `cft_run`.**~~ **DONE,
   2026-09-12**, as `cft_run_ex` with `cft_elem_args.scalar_mask` -
   MODE[18:16] on the tile, behind CAPS2[7]. Every workload that applies
   one value to a batch - the zoom's reference point against every pixel,
   the Mersenne carry base, an interval coefficient - filled an array with
   copies first; in the demos that was 7,168 JavaScript stores per pixel
   iteration, and in C the same loop.

   This entry said it "would need the model and the tile to agree on it
   first", and that turned out to be half right. The TILE needed real work
   - one beat read instead of n, and element 0 replicated across the
   beat's lanes, since a beat is eight elements at fp32 and handing it to
   the array unchanged would give lane *i* element *i*. The MODEL needed
   nothing: a scalar operand computes exactly what an array of copies
   computes, the same `op()` on the same values, so there is no new
   rounding rule to define. What the contract needed was a sentence, and
   it is in cft.h beside the struct.

   The saving is NOT portable and the call is. On a tile the value crosses
   once; the software backend indexes element 0 (it saves the caller the
   copies, and there is no bus to save); the remote backend expands
   locally, because its frames chunk and element 0 would have to ride
   every chunk. `CFT_SEQ_FEAT_SCALAR` says which handles TAKE the call,
   not where it saves: a tile publishing CAPS2[7], the software backend
   (which publishes the bit since 2026-09-24 - it computed scalar
   operands with the bit clear before that), and a remote handle whatever
   its server's bit says, since the client expands. A tile without the
   bit refuses it by name. The saving is the bit AND a device backend.
3. **The program API in the wasm surface.** `cftw_*` carries every
   library operation but not `cft_program_load/run`, so the demos run
   the tools' loop engines; the program engines were measured native at
   1.3 to 2.1 times the loop on the panels that can be programs and
   nothing on the zoom's pixel phase. Wrapping them is small, and it is
   a module rebuild, so it waits for the next step that rebuilds the
   module anyway. **DONE** - the program calls at ABI 0.8 (2026-09-07)
   and the last missing elementwise one, `cft_run_ex`, at 0.14
   (2026-09-15): it had been unwrapped since 0.12, so neither a scalar
   operand nor an index table was reachable from JavaScript.
   `cftw_run_ex`, its entry point `Context.mapEx(op, {a, b, c, scalar,
   idxA, idxB, idxC})` and the rebuilt module landed in ONE commit,
   because `cwrap` of an export the module lacks returns `undefined`
   rather than throwing - a call table and a module that disagree give a
   package whose entry point silently does not exist. `lib.mjs`'
   `audit()` now CALLS `cftw_idx_none` at load and `verify.mjs` names
   both exports, so that disagreement fails at import and by name
   instead.

## The remote backend: a device behind a socket (2026-09-06)

Step 1 of docs/ROADMAP.md's third tier, and docs/PLATFORMS.md section
6's Windows answer. docs/REMOTE.md is the protocol and the measured
numbers; this section is the API's view of it.

```c
cft_open("cft://host:port", 0, &dev);     /* a remote device */
```

One additive spelling of `cft_open`'s artifact argument, and nothing
else in the ABI moved. The handle is a `cft_device` like any other:
`cft_get_caps` reports backend `remote` and the server's device for the
format mask, tile count, contract version and `flags_readable`;
`cft_supports` answers from those and from the server's opcode groups,
which the handshake carries and `cft_caps` has no field for; every entry
point takes the handle. What is different is where the arithmetic
happens, and the rule for that is the one `host/src/device.c` already
draws for the XRT backend: **only the calls that touch a device cross
the wire** - `cft_run`, `cft_reduce` for `CFT_SUM` and `CFT_DOT`,
`cft_reduce_seg` (ABI 0.13), and `cft_program_run` - and every host
operation runs in the caller's own process on the caller's own copy of
the library, which is bit-identical to the server's by contract. The
clause-5 host operations, the transcendentals, the character
conversions, the augmented operations, the scaled products, the
magnitude forms and `cft_convert` never make a round trip; the composed
operations (`cft_div`, `cft_sqrt`, `cft_rint`, `cft_scaleb`,
`cft_cmp_sig`, the formatOf widening route) issue their passes through
the backend and make one round trip per pass, or one per chunk on the
program route, which a remote device takes by default as a tile does.

**The status word stays on the handle.** A remote call returns its flag
word in the response and `device.c` ORs it in through `cft_flags_emit`,
the seam every backend uses, so the six operations of 5.7.4 cost no
round trip and a composed operation's internal passes are muted exactly
as they are locally. The server's device has a word too, since it is a
library device; nothing reads it and it dies with the connection.
**Buffers stay on the client** for the same reason they are host memory
on the software backend: `cft_run` copies from whatever pointers it is
given on every backend but XRT, whose `cft_alloc` buffers are
device-resident.

The server, `host/tools/cft-serve.c`, opens one library device per
connection - the software backend, or `--artifact` for a card on a
Linux box - binds to `127.0.0.1` unless told otherwise, multiplexes its
connections with `select()` and serves their requests one at a time,
and is stopped by its PID. No authentication, no encryption: a
transport, not a security boundary. The socket API is the operating
system's and adds no link flag anywhere; on Windows `ws2_32.dll` is
loaded at first use, so `libcft.a` links exactly as it did and the
Fortran, Go and Rust examples build unchanged. An emscripten build
compiles the backend to a stub that answers `CFT_ERR_NO_DEVICE`.

Outcomes a caller can see: a malformed URL is
`CFT_ERR_INVALID_ARGUMENT`; an unreachable server is
`CFT_ERR_NO_DEVICE` with the socket's reason in `cft_last_error()`; a
server built from a library with a different ABI version is
`CFT_ERR_UNSUPPORTED` (a mismatch is refused, not warned about); and a
corrupted, truncated or out-of-step frame poisons the handle so that
every later call is `CFT_ERR_INTERNAL` with "close it and open it
again" in `cft_last_error()` - the XRT backend's discipline for a
handle whose compute units may still be running. A receive that
outlasts `CFT_TIMEOUT_MS` (default twenty minutes) is
`CFT_ERR_TIMEOUT`.

How it is held to the contract: `host/tests/device_test.c` takes a
`cft://` URL as its artifact and holds the remote backend against the
software one over its full matrix, exactly as it holds the XRT one;
`host/tests/remote_test.c` speaks the frames badly on purpose and
checks each refusal, exercises the operations libcft's client never
issues, and reads the composed operations' round-trip counts from the
server's own counters; `host/tests/remote_check.py` owns a loopback
server's lifecycle (started, PID recorded, terminated by that PID) and
runs the replay and one workload chain both ways; and `verify/run.sh`'s
`remote` stage runs that in the quick budget. The full-set replay, the
five workloads' chains across a Windows-to-WSL boundary, and the rates
are in docs/REMOTE.md.

## The device's on-chip capacities, published (2026-09-07)

Item 3 of docs/studies/OPT-D-contract.md, and the defect its section
0.1 found: **the tile refused a program it could not hold, with a
status bit and no explanation, and no host could ask which tile it
had.** `rtl/cft_krnl.sv` instantiates the sequencer with 64 deposit
slots a lane and refuses a bigger header at its own header check;
`host/src/program.c` accepted 2^20; and `cft-zoom`'s default of
`--steps-per-call 1024` is 2,048 slots a lane - thirty-two times the
tile's - so the tool was green on every machine that has no card and
would have been refused by the first one that does.

`cft_caps` grows by four fields, which is what its `struct_size`
handshake exists for; a caller compiled against the older struct
passes the older size and never sees them.

    uint32_t max_deposits;   /* deposit slots a lane */
    uint32_t max_insns;      /* instructions in one image */
    uint32_t max_consts;     /* constants an instruction can ADDRESS */
    uint32_t seq_features;   /* CAPS[7:4] in bits 3:0, CAPS[31:28] in 7:4 */

**Zero means unknown, not zero capacity**, and nothing is enforced
against an unknown. One thing produces it: a remote server whose
`HELLO` caps block predates the fields (docs/REMOTE.md), and a device
whose `VERSION` predates them, which is every card-day 0x410 image.

`max_consts` is the number of constants an instruction can *address*,
not the `n_consts` a header may declare. The `ka`/`kb`/`kc` bits
redirect four-bit operand fields at the constant bank, so the answer was
16 on the tile and 16 here until 2026-09-07, when `kx`
(docs/SEQUENCER.md) gave an instruction 8-bit indices in its immediate:
it was 256 on both until revision 3's ninth bit (`CFT_SEQ_FEAT_KX9`)
made it 512, and `seq_features` says which a device is. Bit 0
(`CFT_SEQ_FEAT_WIDE_CONST`, from CAPS[4]) is `kx`; bit 4
(`CFT_ALU_EXT_IMUL`, from CAPS[28]) is opcode 30, `IMUL`. **A feature
bit that is clear is absent, not unknown**: `cft_program_load` refuses
an image that uses `kx` or `IMUL` on a device that does not publish
them, naming the instruction, and `cft_supports(dev, CFT_IMUL, fmt)`
answers no - so a card-day image that predates both is never handed a
program its operand mux would misread. Where the bit IS published -
a CAPS[28] tile, and the software backend - it answers yes, since
2026-09-24; before that it answered no on every device, because
`cft_sf_op_assigned` had left opcode 30 off the list `cft_supports`
consults first, and the CAPS[28] branch behind it never ran.

**Each backend reports what it enforces and enforces what it reports.**
The XRT backend decodes `CAPS[7:4]`, `CAPS[27:16]`, `CAPS[31:28]` and
`CAPS2`, three four-bit exponents and the feature bits, and does not
transcribe a 64 into C. The
remote backend takes them from the handshake. The software backend
reports its own - 2^20 deposit slots a lane, the header field's own
2^32-1 instructions, 512 addressable constants, and every feature bit
`cft.h` defines (`seq_features` 0x7f1f) - the capacities and the
sequencer's bits from `host/src/program.c`, which is the file that
enforces them, so the number a host is told and the number a program
is held to are one declaration. `CFT_SEQ_FEAT_SCALAR` and
`CFT_FEAT_REDUCE_SEG` come from `host/src/device.c` instead, for the
same reason: they are features of its elementwise path and of
`cft_reduce_seg`, which a `-DCFT_NO_PROGRAM` build keeps and
`program.c` does not, and the refusals that read them are there. Both
were computed but unpublished until 2026-09-24 (0x671f), so a caller
that asked first was told no by a handle that would have said yes.

**The software backend was not narrowed to the tile's 64**, and that
is a decision rather than an omission. It models the program model,
not one implementation of it; a smaller tile is meant to be a
conforming tile (docs/ROADMAP.md's third tier); and every recorded
workload chain - docs/REMOTE.md's table, `bindings/wasm/demos_chains.json` -
was produced through its accepted set, so narrowing it would change
what those hashes cover in order to make a statement a host can now
simply ask for. "It ran on software" therefore still does not mean
"it fits a tile". What changed is that finding out costs one call
instead of a card.

**`cft_program_load` refuses, not `cft_program_run`.** It already
takes the device, and already refuses a precision the device does not
carry; a program is built once and run many times, so a tool that
will not fit should learn before it stages operands; and a handle
that loaded and cannot run is a worse contract than a load that
failed. The status is `CFT_ERR_UNSUPPORTED` - the same answer as a
format the device lacks, for the same reason - and `cft_last_error()`
carries the cap, both numbers and the field that would have answered
in advance:

    this program's max_deposits is 2048; this device's is 64 (deposit
    slots a lane). Ask cft_get_caps - cft_caps.max_deposits - before
    building one: a device refuses an image past its capacities
    itself, with a status bit and no explanation

That message is the library's own, not a backend's: `cft_last_error()`
now has a third source, cleared the moment anything reaches a device
backend, so a refusal libcft made never goes on explaining someone
else's failure. The other way round it does not hold: a refusal that
adds no sentence (a bare argument error, `cft_conformance` over a
directory with no sets) clears nothing, and neither does every call that
succeeds; and in a process with two device backends, a remote handle's
older sentence comes before an XRT handle's newer one (verifier-V10). So
an older failure's sentence can outlive its call. Read
`cft_last_error()` straight after the call that failed, and take it as
detail for that call when it names it (verifier-V9 and the lead,
2026-09-28).

**Every `CFT_ERR_UNSUPPORTED` carries a sentence (2026-09-14)** - on
every profile but `CFT_TINY`, whose one-byte `CFT_ERRMSG_MAX` keeps
the status and drops every sentence (docs/EMBEDDED.md). It did
not: `cft_run`, `cft_reduce` and `cft_program_load` refused a format the
device lacked, or an opcode group it did not implement, with
`cft_last_error()` empty - or, worse, still holding the previous
failure's text. cft-rebound found this on its trimmed binary128 image
and worked around it at open (`cft-rebound/docs/BITSTREAM.md`, ask 3).
Now a format the device lacks says what it does carry:

    cft_run: this device carries fp32 fp64 fp128; fp256 is not among
    them. cft_supports(dev, op, fmt), or cft_get_caps -
    cft_caps.format_mask - says so before a run; a device refuses a
    precision it lacks itself, with STATUS[3] and no explanation

a format above the *build's* ceiling (`CFT_MAX_FORMAT` in
`cft_config.h`) says so and names the widest rung compiled in; an
opcode names its CAPS group and bit; and an entry point composed from
primitives - `cft_rint`, `cft_scaleb`, `cft_cmp_sig`, `cft_div`,
`cft_sqrt` - names the primitive it needed. `device-test` holds the
first two entry points to this on every image and reports NOT TESTED
on an image that carries all four formats, since there is then nothing
to refuse.

**The two workload tools size themselves from the answer.** `cft-zoom`
took `--steps-per-call` from a `#define TILE_MAX_DEPOSITS 64` copied
out of the RTL; it now reads `cft_caps.max_deposits`, and when the
device's budget is smaller than its default it uses `cap / 2` (two
deposits a trip) and says so on stderr, because the trip count changes
only how many calls a run takes and not what it computes. A value the
user typed is refused instead, naming the cap - running something
other than the command line says is how a measurement stops meaning
what it claims. `cft-orbits` refuses either way: its sample count is
part of what is recorded, so there is nothing to resize.

How it is held: `host/tests/device_test.c` gained "the caps a backend
reports are the caps it enforces" - a program at each cap loads and
one past it is refused - run against both handles, and through
`cft-serve` on loopback for the remote one; `host/tests/remote_test.c`
checks the caps block end to end and that the client enforces what the
block told it; `tb/test_krnl.py` parses `rtl/cft_krnl.sv`'s
localparams and checks the `CAPS` readback against them rather than
against a copied literal. What is NOT tested, and says so in its own
output rather than skipping quietly: an image past the software
backend's instruction cap, which would be 32 GiB, and a constant index
past 15, which does not fit the instruction's four-bit field.

*The last of those was closed on 2026-09-08. The probe wrote the
four-bit form, so it could not NAME an index past 15 and was checking
a cap of 256 at 16; it now writes the `kx` form where the device
publishes `kx`, and tests the cap at `max_consts - 1` - `k[255]` on the
software backend. The half that remains unrepresentable is a different
one, and still says so: an index past 256 does not fit the immediate's
byte.*

## Programs at ABI 0.9: registers, a bank, a digest (2026-09-08)

Revision 2 of docs/SEQUENCER.md, host side. Three features, two of
them behind a CAPS bit and each refused BY NAME where a device lacks
it. Nothing already written changes: every entry point keeps its
signature, every image built before this loads and runs exactly as it
did, and the card-day 0x410 images are untouched.

**Thirty-two registers a lane.** A register field is five bits: the
low four stay in the operand fields and the fifth of each lives in
`imm[27:24]` - `rd`, `ra`, `rb`, `rc` in that order - which every ALU
form reserved. `imm[31:28]` stays reserved-must-be-zero.
`CFT_SEQ_FEAT_REGS32` (bit 1 of `seq_features`, CAPS[5]) publishes it,
and a program naming a register above 15 on a device without it is
`CFT_ERR_UNSUPPORTED`, with the instruction, the register and the
register an old operand mux would have addressed instead:

    instruction 3 names r31 and this device has 16 registers a lane
    (CAPS[5] clear, cft_caps.seq_features bit 1 - CFT_SEQ_FEAT_REGS32);
    its operand mux would read the low four bits and address r15 instead

That is the same reasoning `kx` needed a CAPS bit for, and the same
shape of refusal: the reserved-bit rule protects a NEW host from an
OLD image, and a CAPS bit protects an OLD bitstream from a NEW one.

**The constant bank as per-run data.** The header's `reserved[0]` is
now `flags`. Bit 0 is `CFT_PROG_FLAG_BANK_EXT`: the image carries no
constant section at all - it is exactly `32 + 8 * n_insns` bytes -
`n_consts` still says how many constants the program addresses and
still bounds every index, and every run supplies exactly that many
format-width values. Every bit above the defined flags, and
`reserved[1]`, are `CFT_ERR_ARTIFACT` - which is the version guard for
every flag there will ever be: a bit this library cannot read is an
image it cannot read, and the honest answer to a sentence you cannot
parse is not to guess. At revision 2 that range was `flags[31:1]`,
since bit 0 was the only flag; revision 3 took bit 1 for `SCRATCH_IO`
and revision 4 bit 2 for `SCRATCH_STRICT`, so it is `flags[31:3]`
today. The RULE is what has not moved, and the numbering lives in
`python/cft_golden/seqflags.py` with `cft.h` gated against it. `CFT_SEQ_FEAT_BANK_PTR` (bit 2, CAPS[6]) publishes the feature,
and `cft_program_load` refuses a `BANK_EXT` image without it, before
the map is touched - a 0x600 tile's fetch would read `n_consts`
constants from an image that has none and then run whatever followed,
which is not a fault the tile can raise.

Two entry points, and each refuses the other's programs by name:

    cft_status cft_program_run_bank(cft_program *prog,
                                    const void *bank, size_t bank_bytes,
                                    const void *a, const void *b,
                                    const void *c,
                                    void *deposits, uint32_t *counts,
                                    size_t n,
                                    uint32_t *flags_out, uint32_t *bus_out);

`bank_bytes` must equal `n_consts` times the format's element size.
`cft_program_run` on a `BANK_EXT` program is
`CFT_ERR_INVALID_ARGUMENT` naming `cft_program_run_bank`; a non-NULL
bank on a program that carries its own constants is the same, naming
`cft_program_run`. A program has ONE source of constants, and a bank
that was silently ignored is two machines computing on different
numbers while agreeing about the image. A NULL bank of zero bytes on
an ordinary program is accepted and is exactly `cft_program_run`, so a
caller that always uses `run_bank` needs no branch.

`cft_program_info` gains `uint32_t flags`, struct-size-gated: a caller
built against the 0.8 header passes the 0.8 `struct_size` and the
field is not written past it - which `api-test` checks with a sentinel
rather than trusting.

**The digest.**

    cft_status cft_program_digest(cft_program *prog,
                                  const void *bank, size_t bank_bytes,
                                  uint8_t out[32]);

SHA-256 over the image bytes followed by the bank bytes, so what ran
is one hash of program and data together. It holds the bank to exactly
the rule the run does, including refusing a `BANK_EXT` program with no
bank: a digest over a bank the program could not have run names
nothing, and a program with two ways to be digested has no name at
all. For a program that carries its own constants the digest is the
hash of the image, which `cft_sha256` gives independently - and
`api-test` checks the two agree.

**The library therefore carries a SHA-256**, exported as `cft_sha256`
because every tool that attests a run wants the same hash over its own
outputs. There were four private copies in `host/tools` -
`collatz.c`, `enclose.c`, `mersenne.c`, `orbits.c`, all byte-identical
- and they now share `host/src/sha256.c`. Its round constants are
DERIVED, from the cube roots of the first sixty-four primes by integer
search, as the standing rule asks; FIPS 180-4's own two worked
examples in `api-test` are what prove the derivation landed on
SHA-256, and each tool's own check recomputes its whole chain with
Python's `hashlib`.

**What the loader refuses, as of revision 2.** Complete when it was
written and not since: revision 3 added `SCRATCH_IO`'s refusals and
revision 4 `SCRATCH_STRICT`'s, including the one this list could not
have anticipated - a strict image on a device that does not publish
CAPS2[6] is `CFT_ERR_UNSUPPORTED`, by name, rather than
`CFT_ERR_ARTIFACT`. docs/SEQUENCER.md carries the current list.
Everything it lists, plus: a set bit above the defined flags
(`flags[31:1]` when this was written, `flags[31:3]` now) or a
non-zero `reserved[1]` (`CFT_ERR_ARTIFACT`); a `BANK_EXT` image whose
length still includes a constant section (`CFT_ERR_ARTIFACT`, because
a program is exactly its header, its constants and its instructions);
`imm[31:28]` non-zero on an ALU instruction; the register high bit of
an operand whose `k` bit is set, under `kx` as well, since a constant
index is four bits or a byte of `imm` and never five; any bit but
`imm[25]` on a `DEPOSIT` or a `SETACT`; any bit of `imm` at all on a
`HALT`, an `ENDREP` or an `ACTALL`.

**One reading of the contract, recorded because it is a choice.**
`REPEAT` reads its whole immediate as the trip count and always has,
so the canonicity rule - "any field an instruction does not read being
non-zero" - reaches none of it, and `imm[27:24]` on a `REPEAT` is
count bits rather than register high bits. Constraining them would
refuse every trip count at or above 2^24, including the `repeat
0xffffffff` docs/SEQUENCER.md's own worst-case paragraph relies on
being loadable and refused by the 2^40 bound instead. The contract's
sentence "on the other four none" is read as being about the four
codes that do not read `imm`; `REPEAT` is the one that does.

**On the wire and on the tile.** The remote protocol gains
`PROG_RUN_BANK` (docs/REMOTE.md); the XRT backend accepts VERSION
`0x700`, writes `BANK_PTR` at 0x64/0x68 by passing the bank as kernel
argument 8 on the A master, and sends the image whole - a `BANK_EXT`
image has no constant section to strip, which is the same reason the
image is kept whole in the first place.

## Programs at ABI 0.10: a scratch, a block, and one entry point (2026-09-08)

Revision 3 of docs/SEQUENCER.md, host side. Three features, each
behind a CAPS bit and each refused BY NAME where a device lacks it,
and one entry point that stops the positional signatures growing.
Nothing already written changes: every call keeps its signature, every
image built before this loads and runs exactly as it did.

### `cft_run_args` and `cft_program_run_ex`

`cft_program_run` took nine arguments, `cft_program_run_bank` eleven,
and this round would have made it thirteen. So one entry point takes
everything a run can carry, and the two calls above are WRAPPERS that
fill the struct - the same executor, the same checks, the same
answers, so nothing that used them has to move and the three cannot
drift:

    typedef struct cft_run_args {
        size_t      struct_size;          /* in: sizeof(cft_run_args) */
        const void *a, *b, *c;            /* the streams; b and c may be NULL */
        size_t      n;
        const void *bank;        size_t bank_bytes;
        const void *scratch_in;  size_t scratch_in_bytes;
        void       *scratch_out; size_t scratch_out_bytes;
        void       *deposits;    uint32_t *counts;
        uint32_t   *flags_out;   uint32_t *bus_out;
    } cft_run_args;

    cft_status cft_program_run_ex(cft_program *prog, const cft_run_args *args);

**The size handshake runs the other way from `cft_caps`', and that is
the one thing a porter must not miss.** An OUTPUT struct is truncated
to what the caller can hold; truncating an INPUT would mean silently
ignoring a field a newer caller set, and a run that quietly dropped a
scratch buffer is precisely what every byte-count rule here exists to
prevent. So a `struct_size` this library does not recognise is
`CFT_ERR_INVALID_ARGUMENT` in BOTH directions, with a different
message for each - too short is a caller missing a field this call
reads, too long is a caller whose extra fields would be ignored.

**Byte counts must match exactly**, all three of them. A buffer that
is merely large enough would let the library and the caller disagree
about the shape of the block while both believed they agreed; and
because the scratch blocks are lane-major, a wrong `n_scratch_in`
overruns nothing at all - it silently gives every lane somebody else's
slots, which is the failure mode a length check is worth having for.

### The per-lane scratch (R4), and its per-run block (R5)

Four control codes reach a lane's own scratch memory: `STL ra, imm`
and `LDL rd, imm` by static slot, `STX ra, rb` and `LDX rd, rb` by a
slot taken from the low `log2(SCRATCH_D)` bits of `rb`'s BIT PATTERN,
**reduced modulo the depth** - the reduction is part of the contract
rather than an accident, so an indexed access is never out of range
and is never refused. A store is a register write for P3's purposes
and is masked by the active bit, so an all-inactive loop body stays a
no-op; a load writes `rd` and is masked the same way. Neither is
arithmetic: no rounding attribute, no flags.

`CFT_SEQ_FEAT_SCRATCH` (bit 8 of `seq_features`, CAPS2[4]) publishes
the memory and `cft_caps.max_scratch` its depth - 256 here and on the
tile when this was written; since revision 7 a tile's is its build's
(2,048 on the U50's revision-7 images) and a software handle's is 256
unless it was opened at another with `cft_open_ex` (below, "A software
handle at a tile's depth"). The two are asked SEPARATELY and follow
different rules: a clear feature bit is ABSENT, a zero capacity is
UNKNOWN.

The header's second reserved word becomes `scratch_io` -
`[15:0] = n_scratch_in`, `[31:16] = n_scratch_out` - meaningful only
under `CFT_PROG_FLAG_SCRATCH_IO` (bit 1 of `flags`), and zero without
it as the reserved word it was. Every run then preloads the first
`n_scratch_in` slots of every lane from `scratch_in` and reads the
first `n_scratch_out` back into `scratch_out`, both **lane-major and
dense**: lane *i*'s slot *s* is element `i * n_scratch_in + s`, the
whole block `n * n_scratch_in` elements. Padding lanes receive nothing
and write nothing. That is what makes a run RESUMABLE - the state that
came out is the state that goes back in - and what the init block and
the "load registers from a per-lane block" asks became once the
scratch existed.

`CFT_SEQ_FEAT_SCRATCH_IO` (bit 9, CAPS2[5]) publishes it. A program
that declares a block refuses `cft_program_run` and
`cft_program_run_bank` by name and takes `run_ex`; a program that
declares none refuses a non-NULL scratch buffer, for the reason a
program with its own constants refuses a bank.

`cft_program_info` gains `n_scratch_in`, `n_scratch_out` and
`scratch_used` - one past the highest STATIC slot any `STL` or `LDL`
names, or the device's whole depth when an indexed form is present,
because an `STX`'s slot is not known until the run. All three
struct-size-gated, as `flags` is.

### What a program run's `bus_out` carries

Two REPORTS on a run that returned `CFT_OK`, and neither invalidates
the output:

| bit | name | what happened |
|---|---|---|
| 4 | `CFT_STATUS_DEPOSIT_OVERFLOW` | a lane deposited more than `max_deposits`; the excess was dropped, what fit is correct |
| 5 | `CFT_STATUS_SCRATCH_RANGE` | a `SCRATCH_STRICT` image indexed the scratch at or past the device's depth; the store was suppressed, the load read +0, and the run went on (docs/SEQUENCER.md R8) |

Bits 0 to 2 are the engine's bus faults and arrive only with
`CFT_ERR_BUS_FAULT`; bit 3 is the trimmed-build precision refusal.
Every backend hands back both reports - the software backend, a tile
and the remote route. On a tile that was true of bit 4 only until
2026-09-18: the XRT backend dropped bit 5 on the way out, so a strict
image was computed correctly on a card and its caller was told
nothing, which is the one thing strict exists to prevent
(docs/VALIDATION.md, that date). A caller that relies on strict should
run against libcft at or after that commit.

### The ninth constant-index bit (R7)

Under `kx`, `imm[28]`, `imm[29]` and `imm[30]` are the ninth bits of
`ka`'s, `kb`'s and `kc`'s constant indices - the same construction as
the fifth register bits one nibble down - so the addressable bank is
**512**. `imm[31]` STAYS reserved-must-be-zero: it is the cheap
version guard for whatever comes after this. A ninth bit is read only
under `kx` and only for an operand whose `k` flag is set, so anywhere
else it is a field nothing reads and the program is refused.

`CFT_SEQ_FEAT_KX9` (bit 3, CAPS[7]) publishes it, and what the loader
refuses on a device without it is not the bit but the INDEX: an index
at or past 256, naming the instruction and the constant a
revision-2 operand mux would have read instead. The two are the same
refusal, since the bit cannot be set without changing the index.

### What the loader refuses, added at revision 3

Everything docs/SEQUENCER.md lists, plus: a `scratch_io` word that is
non-zero with `SCRATCH_IO` clear (`CFT_ERR_ARTIFACT`); an
`n_scratch_in` or `n_scratch_out` past the device's `max_scratch`
(`CFT_ERR_UNSUPPORTED`, naming the field and both numbers); a static
`STL`/`LDL` slot at or past `max_scratch` (the same, naming the cap);
any of the four scratch codes on a device without
`CFT_SEQ_FEAT_SCRATCH`, or a `SCRATCH_IO` image on one without
`CFT_SEQ_FEAT_SCRATCH_IO`, or a constant index at or past 256 on one
without `CFT_SEQ_FEAT_KX9`, each by name; `imm[31]` non-zero on an ALU
instruction; a ninth index bit set without `kx`, or for an operand
that names a register; and, on the four scratch codes, every field
none of them reads - `rd` on an `STL`, `ra` on an `LDL`, `imm[23:0]`
on an `STX` or an `LDX`, and `rnd` or any `k` flag on all four.

### On the wire and on the tile

The remote protocol gains `PROG_RUN_EX` (docs/REMOTE.md), a third
opcode for the reason the second was a second. **Which of the three a
run becomes is read from the IMAGE's header flags and never from a
buffer's length** - a `BANK_EXT` program whose `n_consts` is zero has
a legitimately empty bank and still needs the bank opcode, and a
`SCRATCH_IO` program with two empty blocks is in the same position one
call further along.

The XRT backend accepts VERSION `0x800`, reads `CAPS2` at 0x6C for the
depth and the two feature bits, and binds `scratch_in` (kernel
argument 9, on the A master) and `scratch_out` (argument 10, on the D
master) on every 0x800 run - with a minimum one-beat buffer when the
program declares none, because the kernel has the arguments either way
and XRT will not submit a run with one unbound. A 0x700 tile keeps its
nine-argument call and a 0x600 its eight: the ARGUMENT COUNT is what
the contract version guards, and XRT throws rather than adapts.


## Reductions per segment at ABI 0.13: `cft_reduce_seg` (2026-09-14)

    cft_status cft_reduce_seg(cft_device *dev, cft_op op, cft_format fmt,
                              cft_round rnd, const void *a, const void *b,
                              void *d, size_t n, size_t seg,
                              uint32_t *flags_out, uint32_t *bus_out);

    d[s] == cft_reduce(op, a + s*seg, b + s*seg, seg)   for s in [0, n/seg)

`n / seg` results, contiguous in `d`; `flags_out` the OR over them, which
is also what one call's flags are over its tree. That one line is the
contract, and it is why nothing new had to be defined: a segment's tree
depends only on its length, so the software backend computes each slice
with the call that already exists, and a tile handed a segment computes
the same tree the whole-array call would over those elements. Every
reduction opcode is accepted - the composed ones (`CFT_DOT`, `CFT_SUMSQ`,
`CFT_SUMABS`) are their pass and their tree per slice, `CFT_MAXALL` its
maximum per slice, 9.4's infinity rule applied per slice as it is per
call. `n` must be a whole number of segments and `seg` at least one, or
`CFT_ERR_INVALID_ARGUMENT` with a sentence saying which; `n == 0`
writes nothing and raises nothing; `seg == n` is exactly `cft_reduce`.

**Where it runs.** On a device that publishes `CFT_FEAT_REDUCE_SEG`
(`cft_caps.seq_features`, CAPS2[8]) it is ONE run: the tile has a
SEG/NRES register pair (0x80/0x84, kernel argument 11, the map's
VERSION 0x900) and its accumulator restarts every `seg` elements,
packing the results into beats as the sequencer's drain packs deposits.
Whole segments are split across tiles, each tile's results landing in
its own slice of `d`, so there is nothing to combine. On a device WITHOUT
the bit the call is refused with `CFT_ERR_UNSUPPORTED` and a sentence
naming the bit and the count of round trips it would have cost: it
never loops the segments over the bus for you, because a caller who
wants that can write it in three lines and a caller who does not must
not be given it silently. The software backend carries it always and
publishes the bit to say so (since 2026-09-24; it computed the call
with the bit clear before that), reading the same bit before it
computes. A remote handle reports its server device's bit and sends one
frame (`REDUCE_SEG`, docs/REMOTE.md), the server's own library doing
the work - or refusing it by name, where the server's device lacks the
bit, so the word and the call agree there too. The bit says nothing
about `CFT_MAXALL` off a tile: the software backend and a remote handle
halve, whatever it says.

**Why it exists** is cft-rebound's seventh ask (docs/ROADMAP.md): the
corrector's convergence test is a maximum per SYSTEM over its `L`
coordinates, every pass, and `CFT_MAXALL` over the whole array expresses
neither the segments nor the "normal values only" - the second is the
five-instruction mask that already exists as a program
(`programs/normalabs-<fmt>.cfta`), and the first is this call. A call
per segment was estimated at about 35 ms a pass at a thousand systems
against the 0.2 ms the host loop costs; one run is the shape that can
compete, and the next image measured it: one run 4.15 ms against 86.4 ms
for the thousand calls at fp64 maxall, and still not faster than the
host loop (docs/VALIDATION.md, 2026-09-14).

**And `maxall` on the tile.** The same bit says opcode 31 is a REDUCTION
on this tile - the accumulator issuing the elementwise maximum in place
of the add - so `cft_reduce(CFT_MAXALL)` runs as one pass there instead
of `ceil(log2 n)` halvings. The bits are the halving's: 754 maximum is
exactly associative and commutative, flags included, which is the
argument the opcode's own block in `cft.h` makes and the reason a
hardware maxall could be added without a tree contract. A tile without
the bit decodes 31 as elementwise and libcft never sends it there.

## ABI 0.14: the seam of a parcel round (2026-09-15)

Declared first, built by parcels (docs/ROUND2.md). Three fields on
`cft_run_args`, one on `cft_elem_args`, two feature bits and one
sentinel:

    cft_run_args   idx_a, idx_b, idx_c        n uint32 indices each, or NULL
                   idx_a_src, idx_b_src,      the indexed source's length in elements
                   idx_c_src
                   idx_scratch_in             n * n_scratch_in indices, lane-major, or NULL
                   idx_scratch_src            the scratch pool's length in elements
                   lane_mask, lane_mask_bytes (n + 7) / 8 bytes, bit i lane i, or NULL
    cft_elem_args  idx_a, idx_b, idx_c, idx_a_src, idx_b_src, idx_c_src
    CFT_IDX_NONE   0xFFFFFFFF, the index that reads as +0
    CFT_SEQ_FEAT_INDEXED (CAPS2[9]), CFT_SEQ_FEAT_LANE_MASK (CAPS2[10])

**The contract** is docs/SEQUENCER.md revision 6: with a table, element
`i` of a block is `source[idx[i]]`, `CFT_IDX_NONE` reading as +0, and
the run is exactly the dense run over the gathered block; a masked lane
runs nothing and writes nothing, its outputs left as the caller had
them. Both are one line in the software backend, which is the
definition.

**The shape rules are checked first and are final** - a table on a NULL
operand, a table on an operand that is also scalar, a source length of
zero beside a table or a length beside no table, a scratch table on a
program that declares no scratch input, a mask whose byte count is not
`(n + 7) / 8` - each `CFT_ERR_INVALID_ARGUMENT` with a sentence naming
the field. A well-formed field on a tile that does not publish its
feature bit is `CFT_ERR_UNSUPPORTED` with a sentence naming what the
tile lacks. A caller built against 0.14 gets a refusal it can read
rather than a run with a field silently dropped, and every existing call
runs exactly as it did.

**`cft_program_run_ex`'s four tables are built (P1, 2026-09-15).**
Pass `idx_a` and `a` is the SOURCE the table indexes rather than the
run's `n` elements: it may hold any number of them, and `idx_a_src`
states how many. Element `i` of the stream is `a[idx_a[i]]`, and
`CFT_IDX_NONE` is `+0` - the format's positive zero, in a lane that
issues no read for it at all. `idx_scratch_in` is the same for the
scratch block: `n * n_scratch_in` entries, lane-major as the block is,
into the pool passed as `scratch_in`, whose length `idx_scratch_src`
states and whose `scratch_in_bytes` must agree with it. Three things
follow, and each is a refusal rather than a surprise:

* **An index at or past `idx_*_src` is refused BEFORE the run**, on
  every backend, `CFT_ERR_INVALID_ARGUMENT` naming the table, the
  entry and the value. A device must never read past a buffer for a
  caller, and a bound checked on the host is one every backend
  inherits without any of them having to agree on what a bad index
  would have computed.
* **A device that does not publish `CFT_SEQ_FEAT_INDEXED` is refused
  by name.** Ask `cft_get_caps` first. The software backend always
  carries it; a tile carries it from CAPS2[9]; a REMOTE handle
  publishes what its server's HELLO publishes and gathers on the
  client before the frame (P2), so the protocol has no field for a
  table and needs none.
* **An identity table is bit-identical to the dense run**, by
  construction and not by luck: the run is defined as the dense run
  over the gathered block, so there is no new rounding rule and
  nothing new for the model to define.

**`cft_run_ex`'s three tables are built (P2, 2026-09-15).** They mean
on an elementwise operand exactly what P1's mean on a stream - `a` is
the SOURCE, `idx_a_src` says how long it is, element `i` is
`a[idx_a[i]]` and `CFT_IDX_NONE` is `+0` - and the answer is the dense
`cft_run` over the gathered operands, every bit and every flag. The
shape rules above are unchanged, the bound is checked the same way and
on every backend, and three more rules are this call's:

* **A table on an operand the OPCODE does not read is refused by
  name** (`CFT_ERR_INVALID_ARGUMENT`). `cft_run(CFT_ADD, a, b, c)`
  ignores `b`, because ADD reads `a` and `c`; `idx_b` on an ADD is not
  ignored in the same way, because a table is a buffer you built for a
  fetch this call would then not make. Give the table to the operand
  the opcode reads, or pass the opcode whose operand it is. An
  UNASSIGNED opcode reads nothing at all, so every table on one is
  refused: its result is the canonical quiet NaN whatever any operand
  holds.
* **With a table, `d` may not overlap ANY operand.** Dense, `d` may
  alias `a`, `b` or `c` and still does: the run loads element `i`
  before it stores element `i`, so the two never disagree. Through a
  table lane `i` reads `source[idx[i]]`, which is any element of the
  source - read after write - and the dense operands beside it are
  refused for a second reason: a table makes the run a PROGRAM on a
  device, and a program's deposit window is a separate buffer role
  with its own write discipline, so `d` overlapping an operand would
  mean something different on each backend. Refused on every backend
  rather than only where it bites, and refused before a single index is
  read - it is checked behind every argument rule the dense run has,
  so an `n` the dense path rejects is rejected the same way here. The
  rule looks at all three operand pointers and not only the ones the
  opcode reads, so `d` overlapping `b` on an `ADD` is refused as well:
  over-broad by a pointer the run would never have fetched, which is
  the direction to be wrong in. A caller who wants an in-place update
  runs into their own buffer and copies.
* **A SCALAR operand beside an indexed one is legal and works.**
  `scalar_mask` and a table on the SAME operand remain
  `CFT_ERR_INVALID_ARGUMENT` (a stride of zero and a table are two
  answers to one question); on different operands they compose. On a
  tile the scalar becomes one of the composed program's own
  CONSTANTS - zero bytes a lane, no stride-0 stream needed - and the
  streams pack down past it.

**How it runs, per backend**, which is a performance statement and not
a contract one - the bits are the same on all three. On an XRT device
the library composes the run as a three-instruction program over P1's
mechanism (`op r3, <streams>; DEPOSIT r3; HALT`, `max_deposits` 1, one
deposit a lane landing dense in `d`), so the TILE gathers and the
elements the caller did not ask for never cross the bus; a device
without a sequencer, and then a device without CAPS2[9], is refused by
name in that order. A scalar operand on that route needs no
`CFT_SEQ_FEAT_SCALAR`: it becomes one of the composed program's
constants rather than `MODE[18:16]`, so CAPS2[7] gates the DENSE
scalar-mask run and nothing else. On the software backend the operands are gathered
and the dense path runs over them, which is the definition rather than
an approximation of it. On the remote backend the client gathers and
sends a dense `RUN`: the call is portable and the saving is not, which
is what `cft_get_caps` is for and is the same division the scalar
operand shipped with.

**`cft_program_run_ex`'s lane mask is built (P3, 2026-09-15).** Pass
`lane_mask` with `lane_mask_bytes` of exactly `(n + 7) / 8` and bit `i`
is lane `i`: a lane whose bit is SET runs, and a lane whose bit is
clear runs no instruction at all. What that means for the caller's
memory is the whole of it, and it is a promise about bytes rather than
about values:

* **A masked lane's outputs are NOT WRITTEN.** Its deposit slots, its
  deposit count and its scratch-out slots come back holding exactly
  what the caller put there. The normative "+0 in a slot nobody
  deposited into" is about the lanes the run OWNS, and a masked lane is
  not one of them - so a caller can mask a lane precisely in order to
  keep the value already in its slot, and a caller who wants +0 there
  must write it. On a tile that promise is kept in TWO places: the
  tile strobes a masked lane's bytes off, and the library stages the
  caller's deposit window, counts and scratch-out block to the device
  BEFORE a masked launch, because what a staged device copy "keeps" is
  whatever it held when the run began - and until 2026-09-15 it held
  the previous run's output (the card day found every masked lane
  holding exactly the value it would have deposited unmasked; the fix
  is `be1ac1f` and the sentence after it, `host/src/backend_xrt.cpp`).
  A RESIDENT window needs no upload: its device copy is the authority.
* **A masked lane contributes no flag and no status bit.** It cannot
  raise `inexact` any more than it can raise deposit overflow, and a
  run whose every lane is masked completes with nothing written and
  `flags` of zero. `ACTALL` reactivates every lane the CALLER has,
  which a masked lane is not.
* **An all-ones mask is bit-identical to no mask**, by construction:
  the mask is the floor under the active bit that `n_active` already
  was for the padding lanes.
* **A tile that does not publish `CFT_SEQ_FEAT_LANE_MASK` is refused
  by name.** Ask `cft_get_caps` first. The software backend always
  carries it; a tile carries it from CAPS2[10]; the REMOTE route
  carries it by running only the lanes the mask keeps - the server
  never sees a mask, which is why it works against a server of any
  age and why the flags are the kept lanes' and nobody else's. A
  remote handle publishes the bit its server's HELLO carries, so
  against a server without it the bit under-promises: the run is
  never refused there.

The mask is also the one field here that costs the tile a read: the
sequencer fetches a block's bits at block setup, one beat a block at
every format (a beat is 256 lanes' bits), and saves whatever the masked
lanes would have computed. docs/SEQUENCER.md R17 has the cycles.

**What lands with the parcels**, and where this section grew: P1
(the four tables of a program run), P2 (`cft_run_ex`'s three tables,
composed on a tile as a three-instruction program over P1's mechanism,
gathered on the client for the remote backend) and P3 (the mask, with
the tile publishing `CFT_SEQ_FEAT_LANE_MASK` and the remote backend
running only the lanes the mask keeps) are all in, above. The saving is
the tile's and the call is portable, as with the scalar operand: a
caller asks `cft_get_caps` to learn which it has.

## Identity at ABI 0.15: which library, which image (2026-09-28)

A certificate (docs/ROADMAP.md, "Segments, certificates and the audit
tool") records what ran. Until this step nothing in the library could
say it. `cft_abi_version` names which calls exist, and did not move
with the 2026-09-25 round's fixes. `cft_caps.device_version` is the
register map's VERSION, the same for every build of it. And the
xclbin's UUID stayed inside the XRT backend, where two builds can share
one. Two calls, both additive:

    const char *cft_build_id(void);
    cft_status  cft_get_image_id(cft_device *dev, cft_image_id *out);

**`cft_build_id()`: the library.** One line, in exactly one of two forms:

    commit=<40 lowercase hex> tracked=<clean|modified> untracked=<none|present>
    unknown

- `commit` is the full name of the commit checked out when the library
  was compiled (64 hex digits in a SHA-256 repository).
- `tracked` is `modified` when any tracked file differed from it.
- `untracked` is `present` when any file git does not ignore was
  untracked. A new source nobody added compiles in as easily as an
  edited one: the lesson `hw/rebuild-2022.sh` wrote down for
  bitstreams. It holds here twice over, since
  `bindings/arduino/sync.py` vendors every file in `host/src` and
  `host/include`, tracked or not.

Only `tracked=clean untracked=none` says "this library IS that commit".
Any other id says the build corresponds to no commit and cannot be
reproduced from one. It does not tell two such builds apart: two trees
modified differently at one commit carry the same id. It names the
source, not the compiler, the flags or the build profile.

The id is `unknown`, whole, wherever it was not measured.
`host/Makefile`'s own rule for `src/build_id.o` and `.lo` is the one
build that computes it:
- every other build of that file compiles `unknown`: the Arduino
  library's vendored copy, anything compiled by hand, and two of
  `host/Makefile`'s own targets, `profiles-check` and the fuzz
  harnesses, which compile the sources without the id. (The WebAssembly
  module compiles it too, and exports no call that reaches it: there it
  answers nothing at all.)
- the rule itself says `unknown` with no repository (a source tarball,
  a copy), with no git, and with a directory above `host/` that is not
  the top of its repository: a copy vendored inside another project,
  whose commit is not this tree's;
- and it says `unknown` when any git call answers with an error or a
  warning. git says "could not open directory" with exit 0 about a
  directory whose untracked files it then leaves out of its answer, so a
  warning means a count nobody can vouch for.

Never a guess, and never partly known. The commit is that of the
repository the tree is in, whichever it is: a copy of this tree
committed at the top of another project's repository carries that
project's commit - a true name for the source it was built from, and
not a commit of this project's.

**git's stderr is kept inside the generator's own shell** (2026-09-28).
The first version wrote git status's stderr to
`${TMPDIR:-/tmp}/gen_build_id.<pid>.err`. On the Windows desktop that
was blind under make: MSYS2's make hands a recipe no TMPDIR, the shell
running the generator (make's `/bin/sh`, MSYS2's) wrote the file into
its `/tmp`, `C:/msys64/tmp`, and the `cat` and `rm` it found on PATH -
Git for Windows' - looked in theirs. A warning was never read; the id
came out whole where it had to be `unknown`, `make test` passed it, and
one empty file leaked per build (verifier-C3 found it; 143 were removed,
the last 16 of them left by the runs that reproduced it and watched its
gate fail). Now git's stdout, stderr and status are taken apart with
the shell's own redirections and parameter expansions, and no second
runtime can look somewhere else.

**How it is made.** `host/tools/gen_build_id.sh` asks git on every make
that builds the library or anything linking it: the header's only
prerequisite is phony. It rewrites the header
`src/build_id.c` includes only when the id changes. make re-reads the
header's time after the recipe, so an unchanged tree rebuilds nothing.
A changed one recompiles that one file, re-archives `libcft.a` and
relinks what links it.
- The header is `host/gen/cft_build_id.h`, outside `host/src` and
  `host/include`. `sync.py` vendors both whole, so a generated file in
  either would fail `sync.py --check` on every commit.
- `.gitignore` ignores it. The id counts untracked files, so a header
  git could see would mark the next build dirty.
- Only `src/build_id.o` and `.lo` are handed it (`-DCFT_BUILD_ID_H`).
  Every other build of that file compiles the `unknown` it holds.
- `make -C host print-build-id` prints the tree's id as of now, and
  writes nothing.

**A static test binary carries the id it was linked with.** The id is
compiled in. A program that links `libcft.a` - every test binary in
`host/` does - carries the id of the archive it was linked against,
which is exactly the library code inside it. A binary not relinked
after the library was rebuilt runs the OLD library and reports the OLD
id. That is the stale test binary CLAUDE.md warns of ("`make -C host
all` does not build the test executables"), made visible:
- api-test prints its id first;
- `make -C host test` hands api-test the tree's id in
  `CFT_EXPECT_BUILD_ID`, and api-test fails if the two differ;
- device-test prints its id first too, and `device-test --build-id`
  prints it and exits. That is how `hw/card-identity.sh` holds a card
  run's binary to the tree before trusting it.

Through a remote handle the id is still the CLIENT's library: HELLO
does not carry the server's.

**`cft_get_image_id()`: the device.** A struct with the size handshake
`cft_caps` uses: zero it, set `struct_size`, call. On return
`struct_size` is how many bytes were filled.

    sha256[32]    SHA-256 over the exact bytes of the xclbin the backend loaded
    image_bytes   how many
    version       VERSION (0x48), as cft_caps.device_version
    n_caps        1 below VERSION 0x800 (CAPS alone), 2 from it (CAPS, CAPS2)
    caps[4]       CAPS (0x4C) and CAPS2 (0x6C), RAW; zero past n_caps

- **The digest is over what was LOADED.** `cft_open` reads the file
  once, hashes those bytes, and builds the `xrt::xclbin` it loads from
  the same bytes. So the digest cannot be of a file replaced after the
  load, and the compute-unit listing reads that object instead of the
  file a second time. It is not the xclbin's UUID, which two builds can
  share. Compare it with `sha256sum` of the file, as the card leg does.
- **The raw words carry every bit**, CAPS[15:8]'s opcode groups
  included, which no `cft_caps` field holds. Every opened tile's words
  are read at open and held equal to tile 0's, the ones the library
  decodes.

**Refused BY NAME where there is no image to name**, never answered
with a digest of zeros that reads as one. The refusal is
`CFT_ERR_UNSUPPORTED`, a sentence in `cft_last_error()`, `struct_size`
set to 0, and nothing else written.

* **The software backend** has no bitstream to hash and no CAPS
  register to read. What determines its bits is the library, whose
  identity is `cft_build_id()`, and the sentence says so.
* **A remote handle** cannot know its server's image. HELLO carries the
  server's DECODED device fields, the ones `cft_get_caps` reports. It
  carries no xclbin digest, no raw CAPS words and no server build
  (docs/REMOTE.md). A certificate made through one records the server's
  `cft_caps`, the client's `cft_build_id()`, and the server's image and
  build as not known.
* **An XRT image whose tiles publish different CAPS words** - a mixed
  layout (docs/LAYOUTS.md) - has no single set of words to name. The
  sentence names the tile and both words. The open itself is unchanged:
  this library has always decoded tile 0's CAPS for every tile, and
  whether a mixed image should open at all is not this call's question.
* **An XRT image one of whose tiles' CAPS could not be read at open**
  has no words to name for that tile. The sentence names the tile, and
  says so when the failure was planted by
  `CFT_XRT_CAPS=plant-unreadable`.

A NULL `dev` or `out`, or a `struct_size` below `sizeof(size_t)`, is
`CFT_ERR_INVALID_ARGUMENT` first, on every backend. The answer comes
from what `cft_open` recorded. So it reaches no device, and it answers
on a handle a failed run has poisoned: the image is still the one
loaded.

**The ABI version.** Both calls are additive: code written against 0.14
gets the same bits from the same calls. `CFT_ABI_VERSION_MINOR` moved
to 15 for them at the merge (2026-09-28). The integrator bumped it
together with the WebAssembly module's rebuild, as every step's is:
`verify.mjs` holds the committed page's `cftw_abi_version()` to the
macro, so a bump without the rebuild fails the `wasm` stage. A caller
that needs either call asks for 0.15.

**How it is held.**

* **api-test.**
  - The id's grammar, exactly. The check's own fourteen controls run
    first: four good ids and ten near-misses, among them a short
    commit, `tracked=dirty` and a trailing space.
  - The id printed. Under `make test`, the id equal to the tree's.
  - The software backend's refusal - status, sentence, `struct_size` 0
    and no other byte written - after the argument refusals.
* **`make -C host buildidtest`**, run by `make test`. The Makefile, the
  generator, `src/build_id.c`, `cft.h` and `.gitignore` are copied into
  scratch repositories and built there with make's own recipe, and both
  objects are linked into a program that prints the id. Twenty-nine
  checks:
  - a clean commit, then the same tree again (nothing rewritten or
    recompiled), and the build's own output ignored;
  - a tracked edit (the header rewritten, both objects recompiled), the
    edit reverted, an untracked source, both at once, a new commit;
  - a git whose status warns "could not open directory" and exits 0:
    `unknown` from the header and from `print-build-id`, with git's own
    words in the header's reason. It is red on the Windows desktop
    against the generator as first committed (e598b8f, 2026-09-28), the
    one that lost stderr;
  - a git whose status fails and says nothing;
  - a warning on either rev-parse call, exit 0: `unknown`, with git's
    words in the reason. Without this step, the two calls taken out of
    `git_run` with their stderr thrown away passed every other step, on
    both hosts (verifier-C3); with it that plant is red on both;
  - a linked worktree at one commit beside the main worktree at
    another: its own commit and its own status;
  - no repository, a copy inside another repository, and no git.
* **device-test**, every run and every mode: the software handle's
  refusal, and the handle under test answering for what it is.
  - Through a loopback server (verify/run.sh's `remote` stage), that is
    the remote refusal.
  - On an xclbin, the digest is held to device-test's own SHA-256 of
    the file, `image_bytes` to its length, VERSION to `cft_get_caps`
    and `n_caps` to VERSION. The raw words must decode to the handle's
    format mask, opcode groups (`cft_supports`, one opcode a group),
    feature nibbles and scratch depth.
  - A refusal the library gives by design - tiles that publish
    different words, or a tile whose words could not be read at open -
    FAILS this leg, in every mode, unless the run was told to expect
    it: `--expect-refusal mixed` or `--expect-refusal unreadable`, for
    an image that genuinely is so (a mixed layout, docs/LAYOUTS.md).
    Expected, it is held to its sentence and `struct_size` 0, and the
    digest and words are NOT TESTED, by name; an expectation the image
    does not meet fails too. (4d5d8e4 passed any such refusal, and
    verifier-C3 showed a real read failure, a comparison that refuses
    everything and a tile read from CAPS2 all going through; each is
    red since.)
  - `device-test <image> -i` runs that leg alone, and on an xclbin, on
    handles of its own opened before the handle under test, it also
    holds `CFT_XRT_CAPS` from both sides:
    - five malformed values (`plant-diff`, `PLANT-DIFFER`, a trailing
      space, `1`, `yes`), each refused by name at open, before anything
      is loaded; until 2026-09-28 each was quietly read as no plant;
    - both refusals planted (`plant-differ` gives tile 1 a word one bit
      off tile 0's, `plant-unreadable` makes its read throw), each by
      its own sentence, and each sentence naming the plant, so a plant
      set by accident cannot tell anyone their image is mixed. The
      plant acts on the backend's comparison, so a backend that stopped
      comparing, or named the wrong failure, fails. It needs two tiles;
      with one it is NOT TESTED, by name;
    - each planted handle's decode - every `cft_caps` field but
      `struct_size` and `abi_version`, and
      `cft_supports` for one opcode of each of the seven groups at every
      format - held equal to the unplanted handle under test: a plant
      changes the identity and nothing the library computes with.
  - A `CFT_XRT_CAPS` set from outside device-test reaches the handle
    under test: that is how a CAPS read failure at open is imitated
    from outside, and the leg must fail it.
* **`sync.py --check`**, with a built tree: 33 vendored files, the new
  `src/build_id.c` among them, and the generated header in none.
* **On the card**: `hw/card-identity.sh`, for whoever holds the card,
  with its own negative controls (docs/CARDDAY.md, "Owed to the next
  card day (added 2026-09-28)"). Measured so far:
  - in hw_emu on the 0907 quad image (XRT 2.14): `device-test -i` gave
    the digest `sha256sum` and the image's manifest give, the four
    tiles' CAPS equal, 15 checks; with the hash file planted, its
    digest check FAILED by name;
  - on the U50 at 09:59 on 2026-09-28 (XRT 2.19, both round-2 images,
    at 082400d): 16 of 16, the quick matrix 2,456 of 2,456 after the
    new load path, and both negative controls red by name. The records
    are `Data/runs/2026-09-28-cert-round/card-p2/`, which is not
    tracked;
  - the planted refusals came after that card run, and were paid by
    the next, at 11:26 the same day at 4d5d8e4: 17 of 17, the quad image
    refusing both by name on its four tiles, and the single image, with
    one tile, NOT TESTED by name (`card-p2b/`, beside `card-p2/`);
  - the unexpected-refusal rule, `--expect-refusal`, the malformed
    values and the planted handles' decode came after both card runs.
    They ran in hw_emu on the 0907 quad image, green, and each of their
    plants red there; on the card they were paid at 14:13 the same day,
    at 45898df: 23 of 23 (`card-p2c/`).
* **Held by reading alone**: that the file is read ONCE, so the bytes
  hashed are the bytes loaded. A second read that returned other bytes
  would pass every gate here; verifier-C3 showed it on a mock of XRT,
  and no cheap instrument can see a read that XRT would make itself.

## A software handle at a tile's depth: `cft_open_ex` (revision 7, 2026-09-29)

Revision 7 made the tile's program limits a build's parameters
(docs/SEQUENCER.md, "Revision 7, the program limits per build"): the
U50's revision-7 images hold 1,024 deposit slots a lane, 32,768
instructions and 2,048 scratch slots, the round-2 images and the
open-core builds 64, 16,384 and 256. Two of the three need nothing here:
`max_deposits` and `max_insns` are capacities, read from CAPS as they
always were, and a program that fits gets the same answers anywhere.
The scratch depth is not only a capacity - a non-strict `STX`/`LDX`
reduces its index modulo it - so a software handle has to be able to
stand for a deeper tile, and a comparison against one has to be able to
ask for that:

    typedef struct cft_open_args {
        size_t      struct_size;     /* in: sizeof(cft_open_args) */
        const char *artifact;        /* as cft_open's: NULL, a path, cft:// */
        int         index;           /* as cft_open's */
        uint32_t    scratch_depth;   /* 0, or a software handle's depth */
    } cft_open_args;

    cft_status cft_open_ex(const cft_open_args *args, cft_device **out);

- `scratch_depth` 0 is `cft_open` exactly. Otherwise, on the SOFTWARE
  backend only, the handle has that many scratch slots a lane: a power
  of two in 1..32,768, the most CAPS2[3:0] can publish. It publishes the
  depth in `cft_caps.max_scratch` and holds every program to it - a
  static slot or a scratch-I/O count past it is refused at load, by
  name, as on any backend - and its executor reduces a non-strict index
  modulo it and reports a strict one past it, which is what a tile of
  that depth computes.
- A plain `cft_open(NULL, ...)` is 256, so every result a software
  handle has ever given is the one it still gives.
- Refused, each with a sentence: a `struct_size` other than this
  library's (`CFT_ERR_INVALID_ARGUMENT`, as for every input struct); a
  depth that is not a power of two in range (`CFT_ERR_INVALID_ARGUMENT`);
  a non-zero depth with an xclbin or a `cft://` artifact
  (`CFT_ERR_UNSUPPORTED` - a device's depth is its image's, and a remote
  handle's its server's); and a depth in a `-DCFT_NO_PROGRAM` build
  (`CFT_ERR_UNSUPPORTED`), which has no scratch.
- Memory: a run of a program that uses the scratch holds a lane block of
  it, 64 lanes x depth x 260 bytes - 4.3 MB at 256, 34 MB at 2,048, 545
  MB at 32,768 - and clears per block only the slots the program can
  reach.

What takes it:
- `device-test` opens its software reference at the DEVICE's
  `max_scratch`, so a 2,048-slot tile is compared against a 2,048-slot
  reference; `--scratch-depth N` opens the software device under test
  ("sw") at N, which is how the whole matrix runs at the U50's depth
  without a card. Its sequencer leg walks a program 300 slots deep,
  plain and strict, and where the device is deeper than 256 holds the
  reference to having been deeper too: a plain 256-slot handle must
  compute another sum and report the strict walk past slot 255.
- `positive-run --scratch-depth N` makes a plate for a deeper tile on
  the software backend; it prints a `scratch-depth` line only when
  asked, so every other plate prints what it always did.

Not built, and named: `cft-serve` has no flag to serve a deeper software
device, so a remote handle to a software server is 256; `cft-segrun`
opens the software backend plainly, so a certificate made on software is
made at 256 (its `device-caps` reads `none`, and the audit re-runs it
at 256); the WebAssembly module exports no `cft_open_ex`.

ABI: an additive entry point and struct for 0.16. The version macro,
the WebAssembly rebuild and the bindings' tables move with the
integrator's bump at the merge, as every step's do.
