# Study D: the contract and the system above the RTL

STATUS: a design study, 2026-09-06. No RTL, no host code and no
existing document was changed to write it. Every number below is
either read out of this tree or derived from numbers in it, and the
derivations are shown so they can be checked.

**Scope.** This study looks at everything above the gates: the
sequencer's program model, the host API, the memory and bandwidth
budget the two of them spend, what the five benchmark workloads and
the atlas port actually asked for, and which build options should
exist at all. Three sibling studies own the arithmetic datapath, the
lane array and its parallelism, and timing and physical
implementation. Where an idea of mine lands on their ground I say so
and stop rather than guess.

**The one freedom this vantage point has** is that it may propose
changing *what the tile is asked to do*. Several of the conclusions
below use it: the largest single win I found is not a faster tile, it
is a program model that stops asking the memory system for things it
did not need to ask for.

---

## 0. Two facts in the tree that nobody has written down

Both were found by reading the RTL against the workload tools, and
both are checkable in five minutes. They come first because they
change the priority of everything after them.

### 0.1 The tile will refuse the deep-zoom program as the tool builds it

`rtl/cft_krnl.sv:580` instantiates the sequencer with `MAXD(64)` -
sixty-four deposit slots per lane - and `rtl/cft_seq.sv:985` refuses
any image whose `max_deposits` exceeds it, with `STATUS[3]`, before a
byte is computed.

`docs/ZOOM.md` builds its reference-orbit program with `max_deposits =
2K` where `K` is `--steps-per-call`, whose default (`host/tools/zoom.c:2106`,
`O.reps = 1024`) is 1,024. **That is `max_deposits = 2048`, thirty-two
times the tile's cap.** The software backend accepts it (`program.c`'s
`SEQ_MAX_DEPOSITS` is `1 << 20`), so the tool is green today and will
be refused the first time it is handed an `--artifact`.

The consequence is not subtle. At `K = 32`, the largest the tile can
take, a 100,000-iteration reference orbit is **3,125 library calls
instead of the 98 the design note advertises**. Each call costs the
~36 fixed cycles `make cycles` measured plus the ~15 AXI-Lite
transactions of `docs/SCALING.md`, call it 15 us: 3,125 x 15 us = **47
ms of pure control overhead**. Against the compute - 100,000
iterations x 11 instructions x ~31 cycles a dependent instruction
(NBEATS issue + LATENCY drain) = 34.1 Mcycles = 341 ms at 100 MHz -
that is 14%, and on a remote tile at 25 us a round trip
(docs/REMOTE.md's WSL figure) it is 78 ms against 2.5 ms, a 31x
regression on the transport the third tier is built around.

Two things follow. First, **a device's on-chip caps must be
discoverable** (item 3 below); today a tool cannot ask, and the first
symptom is a refusal on card day. Second, the deposit buffer's shape
is worth attacking directly (item 9), because it is both the reason
for the cap and, by `docs/SEQUENCER.md`'s own accounting, the largest
of the sequencer's three memories: `MAXD * NBEATS * 32 B` = 64 x 16 x
32 = **32 KiB, four times the 8 KiB register file**.

The BRAM arithmetic makes the second point sharper. `docs/PLATFORMS.md`
puts the whole tile at **16 BRAM**, and the sequencer's four memories
account for essentially all of it: the deposit buffer is eight
32-bit banks 1,024 deep, which is exactly **8 RAMB36**; `imem` at
1,024 x 64 bits is 2; the register file's mirrored 2 x 8 KiB is about
6; `kmem` at 16 x 256 bits is LUTRAM. **The deposit buffer is half the
tile's block RAM**, and it is spent buffering a scatter that item 9
removes.

### 0.2 Half of the instruction memory is provably zero

`imm` is bits 63:32 of every instruction word, and the loader refuses
a non-zero `imm` on any ALU instruction (`seq.py:188`, `program.c`'s
validator). An image that is mostly arithmetic - all five workload
programs, every det function, every positive - therefore spends
**half its instruction memory storing enforced zeros**: 4 KiB of the
tile's 8 KiB `imem` at `IMEM_D = 1024`.

`docs/ENCLOSE.md` already spotted the encoding half of this ("the
`imm` field is already 32 bits wide and is unused by ALU
instructions"). The memory half is the stronger argument: an indexed
constant form does not merely cost no encoding space, it **reclaims
storage that is already paid for and already zero**. That is why item
1 ranks first.

A third, smaller inconsistency sits beside them: `cft_seq` accepts a
header declaring up to `KMEM_D = 256` constants and stores only the
first `KREG = 16` (`cft_seq.sv:1017`, `if (kons_i < KREG)`). Nothing
in `seq.py`, `program.c` or the RTL refuses `n_consts > 16`, so a
program may legally carry constants that no instruction can ever
name. Either refuse them or make them addressable; item 1 makes them
addressable, which is why I have not proposed the refusal.

---

## 1. The ranked list

Ranked by expected value per unit of implementation cost, best first.
Each item says which layer it needs: **model** = `python/cft_golden`
only; **model+lib** = that plus `host/src` and `host/include`;
**+RTL** = also `rtl/` and `tb/`. Nothing here can ship without the
model first; that is the house rule, not a preference.

| # | idea | layer | one line |
|---|---|---|---|
| 1 | indexed constants (`kx` = bit 30, `imm` as three 8-bit indices, bank to 256) | model+lib, then RTL | costs no encoding and no memory, and takes the enclose Horner from 6.6 to 102.6 operations per element moved |
| 2 | `IMUL`, opcode 30, 32-bit low product | model+lib, then RTL | the one arithmetic gap between the tile and the whole atlas workload |
| 3 | publish `MAXD`/`IMEM_D`/`KREG` in the free CAPS bits and in `cft_caps` | model+lib, one wire | turns 0.1's card-day refusal into a startup calculation |
| 4 | stride-0 scalar operands on `cft_run` | model+lib+RTL | 25% of elementwise read bandwidth per scalar operand, and 6,144 stores a pixel iteration gone |
| 5 | an external constant-bank pointer, re-bound per run | model+lib+RTL | answers the zoom per-iteration broadcast by unrolling, with no new addressing mode |
| 6 | `n_init` register planes at a new pointer, plane-major | model+lib+RTL | makes every 2- and 3-DoF system resumable; plane-major means no transpose |
| 7 | `IMEM_D` 1024 -> 4096 | RTL parameter | six BRAM buys the code-size problem `CALL` was for |
| 8 | the program API in the wasm surface | neither | the demos currently measure the engine the architecture argues against |
| 9 | static deposit slots: a machine cursor, plane-major output | model+lib+RTL | returns half the tile's BRAM, retires `MAXD`, and makes P2 independent of P3 |
| 10 | a profile name over CAPS | model+lib | the third tier needs a target an emitter can name |
| 11 | per-lane flags in `counts[31:27]` behind a MODE bit | model+lib+RTL | the cheap half of the per-element-flag ask; does not remove the Collatz witness |
| 12 | a lane shift behind a non-splittable-program flag | model+lib+RTL | buildable, one workload, and the first program class whose answer depends on partitioning |
| 13 | `CALL` | RTL | mostly deleted by item 7; does not deliver what orbits and enclose asked for |
| 14 | in-program cross-lane reduction | - | **reject**: a program sees a block, and the block size differs between backends |
| 15 | in-program correctly rounded divide/sqrt | - | **reject as stated**: it needs a second rounding authority |

---

### 1. Indexed constants: `imm` as a constant index, the bank to 256

**Layer: model+lib to be useful; +RTL to be fast. Both are small.**

**Mechanism.** Instruction bit 30 is reserved and must be zero, so
defining it can never reinterpret a valid existing program - an old
loader refuses a new program by the rule it already has, which is
exactly the version guard this feature needs and the reason no
program-header VERSION bump is required. Define bit 30 as `kx`: when
set, the constant indices for the three operands come from `imm[7:0]`,
`imm[15:8]`, `imm[23:16]`, and the 4-bit `ra`/`rb`/`rc` fields of any
operand whose `k` bit is set must be zero (canonicity, so a readback
hash stays a hash). `imm[31:24]` stays reserved-must-be-zero, which
leaves room for the counter-indexed form of item 5 without touching
this one. The bank grows from 16 addressable to 256, which is
`KMEM_D`'s existing value - the RTL header check already permits
`n_consts <= 256` and only the storage and the operand mux are 16 wide.

**What it buys, with arithmetic.** `docs/ENCLOSE.md`'s interval Horner
is the measured case. Today: 33 arithmetic instructions per chunk
against 5 element transfers (three stream loads, two deposits) =
**6.6 operations per element moved**, which that document correctly
notes is below `docs/SEQUENCER.md`'s K ~ 30 compute-bound crossover.
A degree-127 interval polynomial needs 128 coefficients = 256
constants exactly, and as one program is `1 CMPLE + 128 x (2 SELECT +
2 FMA) = 513` arithmetic instructions over the same 5 transfers =
**102.6 operations per element moved**. That is **15.5x the
arithmetic intensity** and **3.4x past the crossover** - the
difference between a kernel that is still memory-bound on a device and
one that is not. The chunk count for that polynomial goes from 16 to
1, and `docs/REMOTE.md` measures what a chunk costs over a socket
directly: the enclose tool's 189/237/315/453 library calls are
dominated by chunking.

For atlas it is the difference between chunked programs and one image
per positive: `docs/ATLAS.md` counts 11 of the 16 slots gone to
`P[8]`, `uT`, `TAU` and `PI` before a single coefficient, and an
inlined `det_sincos` wants a dozen more.

**Costs.** Encoding: zero (bit 30 and `imm` are both already spent as
zeros). Instruction memory: zero - see 0.2. Constant memory: 256 x 32
B = 8 KiB where 512 B of LUTRAM stood, about **+4 RAMB36** once the
three read ports are accounted for - a quarter of the tile's sixteen,
and under 1% of a Kintex-7 325T's 445 or an Artix-7 200T's 365
(`docs/PLATFORMS.md`). ABI: none at all - a program is data, `cft_program_load`
validates it, and no entry point changes signature. CAPS: one feature
bit (see item 3). The real cost is in the RTL and belongs to the
timing study: `cft_seq.sv:1254` reads `kmem` combinationally into the
issue registers, and a 256-entry bank is a BRAM read rather than a LUT
mux, so the issue path grows a stage.

**What must be proven.** The golden model gains the `kx` decode and
its canonicity refusals; `test_seq.py`'s 40,000-program fuzz and
`make libcft-seq`'s shared corpus grow a `kx` arm; the refusal matrix
gains "index >= n_consts under `kx`", "non-zero operand field under
`kx`", "non-zero `imm[31:24]`". Then `tb/test_seq_core.py` against the
model as usual. P1 is untouched (no arithmetic added), P2 and P3 are
untouched (a constant is not lane state).

**Doctrine.** None. It uses a reserved bit for exactly what reserved
bits are for, and the old-loader-refuses-new-program behaviour is the
compatibility rule working rather than being bent.

---

### 2. `IMUL`, opcode 30, 32-bit low product

**Layer: model+lib unblocks atlas entirely in software; +RTL for the tile.**

**Mechanism.** Opcode 30 is free (`softfloat.py` assigns 0-14, 16-23,
24-25 for reductions, 26-27 for the seeds, 28-29 for the composed
reductions; 15 and 30 up are unassigned, and `cft_run` already answers
an unassigned opcode with a canonical quiet NaN and `invalid`). Define
`IMUL` in the integer group (CAPS[12]) as the **low 32 bits of the
product of the low 32 bits of the two operand encodings, zero-extended
to the format width**. Defining it on 32 bits rather than on the full
`W`-bit encoding is the whole design decision: the workload is a
32-bit hash, and a `W`-bit low product would be a 256x256 multiplier at
fp256 for nobody's benefit.

**What it buys.** Everything atlas does. `docs/ATLAS.md`'s census
finds exactly two operations that do not map, and both are the draw
stream: `lowbias32` is two 32-bit multiplies per draw, and it "cannot
be built from the float opcodes either, because a 32x32-bit product
exceeds the 24-bit significand". With `IMUL` the whole draw stream is
in-lane - and, as section 4 below argues, that alone removes the
*third* of the four atlas asks, because five of the seven per-sample
values are draws derived from the sixth.

**Costs.** Model: one line and its vectors. libcft: one case in
`softfloat.c`'s dispatch. RTL: one 32x32 low multiplier per lane, so
8 at fp32 - roughly 1k LUT each unmapped, or 2-3 DSP48E1 each. Against
the tile's 292 DSPs that is +8%, or roughly 6% of a 123k-LUT tile if
mapped to fabric. **This number belongs to the datapath and array
studies and I have not tried to settle it**, but the interesting
observation from up here is that the tile already contains a very wide
integer multiplier - the FMA's significand array, built as 24-bit
chunk columns and now iterable under `MUL_PASSES` - and `IMUL` should
be steered through it rather than given its own silicon. Whether that
steering is cheap is study A's question.

**What must be proven.** Exhaustive is impossible (2^64 pairs), so:
the model against Python's own integer arithmetic over a directed
corpus (zeros, ones, 2^k, 2^k-1, the `lowbias32` constants
`0x7feb352d` and `0x846ca68b`, the wraparound boundary) plus randoms;
`tb/` against the model at all four formats, which is where the
zero-extension rule earns its test; and the atlas parity harness,
which is the real oracle - the GPU's `lowbias32` and the tile's must
produce the same stream or the whole port is meaningless.

**Doctrine.** It adds arithmetic, which P1 says the *sequencer* does
not - but P1 is about the sequencer introducing arithmetic of its own,
and this is an opcode in the shared `cft_lanes` array that
`cft_engine_stream` can issue too. That is the same category as the
seed opcodes 26/27. No collision.

---

### 3. Publish the sequencer's on-chip caps; put the free CAPS bits to work

**Layer: model+lib, and one wire in the RTL.**

**Mechanism.** `CAPS` (0x4C) reads `{16'b0, op_caps, 4'b0, prec_caps}`
- **bits 31:16 and 7:4 are hard zeros today**. Assign:

| bits | meaning |
|---|---|
| 7:4 | sequencer feature nibble: wide constant index, init block, per-lane flags, static deposit |
| 19:16 | `log2(MAXD)` - deposit slots per lane |
| 23:20 | `log2(IMEM_D)` - instruction capacity |
| 27:24 | `log2(KREG)` - addressable constants |
| 31:28 | reserved |

`cft_caps` carries `struct_size` precisely so it can grow, so add
`max_deposits`, `max_insns`, `max_consts` and a `seq_features` word to
it; a caller compiled against the old struct is unaffected. `VERSION`
does not move, because `VERSION` guards the register map and this
changes a value inside a register that already exists.

**What it buys.** It converts 0.1 from a card-day surprise into a
sizing calculation a tool does at startup. `cft-zoom` reads
`max_deposits`, picks `K = cap/2`, and runs. Every future tool gets
the same. It is also the precondition for shipping trimmed open-core
tiles at all: `docs/ROADMAP.md`'s third tier wants "open tiles that
emit identical bits, slower, on anything", and a tile with a smaller
`IMEM_D` is a perfectly good conforming tile that a host currently
cannot detect.

**Costs.** Twelve wires and a `case` arm in `cft_csr.sv`; four fields
in a struct that was designed to grow; a paragraph in HOSTAPI. The
remote protocol's `HELLO` caps block already carries the format mask
and opcode groups and would carry these the same way.

**What must be proven.** `host/tests/device_test.c` gains "the caps a
backend reports match the caps it enforces" - which is a real test,
because it is exactly the invariant 0.1 violates today between the
software backend and the RTL.

**Doctrine.** None. This is CAPS doing the job HOSTAPI's own "weak
links" section created it for: a host asks rather than guesses.

---

### 4. A scalar (stride-0) operand class for `cft_run`

**Layer: model+lib+RTL, but each part is small.**

**Mechanism.** Three `MODE` bits - `MODE[18:16]`, and `MODE[31:16]`
is entirely free today - say that operand A, B or C is a single
element to be broadcast to every lane rather than an `n`-element
array. The library takes the same flags as three `int` arguments on a
new entry point (`cft_run_scalar`, or a `flags` word on a
`cft_run_ex`; adding a function is additive, changing `cft_run`'s
signature is not).

**What it buys.** Bandwidth, which on the third tier is the whole
question. `docs/PLATFORMS.md` derives the tile's elementwise appetite
as 3.456 GB/s per master, 13.82 GB/s across four. **One scalar operand
removes one master's traffic: 13.82 -> 10.36 GB/s, a 25% cut. Two
removes 50%.** On a 7-series board whose DDR3 delivers about 12.8 GB/s
that is the difference between over the ceiling and under it, and it
costs nothing in arithmetic. Above that, it removes the fill loops the
workloads pay today: `docs/DEMOS.md:605` counts **6,144 stores per
pixel iteration** in the zoom panel, "measurably more than the wasm
call they accompany", and `dfill` in `pixel_chunk` is the same loop in
C. The Mersenne carry base and every interval coefficient are the same
shape.

**Costs.** The RTL is friendlier than it looks: `cft_engine_stream`'s
readers are already a per-stream `generate` loop with their own
`beats_total`, `base`, and burst logic, so a stride-0 stream is
`beats_total = 1` plus hold-and-broadcast on the pop side - and the
broadcast function already exists, as `cft_seq.sv`'s `kbroad`. Model:
a stride argument in `vectors/` and a conformance set that exercises
it, because "a contract shape, not a backend detail" is exactly right
- the tile and the model must agree that a scalar operand's element is
read once and that its flags are the flags of `n` uses of it, not one.

**What must be proven.** That `cft_run(op, a, b_scalar, c)` is bit- and
flag-identical to `cft_run(op, a, fill(b), c)` for every op, format,
attribute and `n`, including `n = 0` and the ragged tail. That is a
pure equivalence property and it is cheap to fuzz.

**Doctrine.** None, and it is the one host-API ask that is genuinely
also a hardware feature rather than a convenience.

---

### 5. The constant bank as per-run data: an external bank pointer

**Layer: model+lib+RTL. This is the answer to the zoom broadcast, and it is cheaper than the ask.**

**Mechanism.** Today the constant bank is part of the program image,
so changing a constant means loading a new program. Add one CSR
pointer (a new `kernel.xml` argument, id 8, appended - the map's own
rule) and a header bit saying "the bank is external, at `K_PTR`". The
loader validates the bank's size against `n_consts` as it does now;
the image's instruction stream, its digest and its attestation are
unchanged, and the same loaded program can be run many times with
different banks.

**What it buys.** `docs/ZOOM.md` asks for "a per-iteration broadcast:
an operand that steps through a vector as the loop iterates, shared by
every lane", and offers two shapes - a fourth stream read by iteration
index, or a counter-addressable constant bank. **Both are more than
the workload needs.** With item 1's 256-entry bank, the perturbation
program unrolls 128 iterations (two reference-orbit components per
iteration) and re-binds the bank per call. A 100,000-iteration
perturbation becomes 782 runs of 128 iterations each, and the fixed
cost - 36 cycles plus ~15 us of control plane - is amortised 128 ways
instead of 1. The program image is loaded exactly once.

Against the alternative (a counter-indexed constant fetch), this needs
no new addressing mode in the issue path, no decision about which of
four nested loop counters indexes, and no new determinism argument.

**Costs.** One appended kernel argument, one CSR pointer, one header
bit, one more read burst at run start. It does add a fourth thing the
program's `m_rd_sel` steering must name on a banked device, which is a
line in `cft_krnl`.

**What must be proven.** That a program run with an external bank
equals the same program run with that bank inlined - a direct
equivalence over the existing corpus.

**Doctrine.** One clause needs writing: the attestation story. Today
"read the image back and hash it" attests the whole run. With an
external bank the hash must cover the bank too, so `cft_program_run`'s
contract becomes "the digest of the image and the bank together". That
is a documentation change, not a weakening, and it should be made
explicitly rather than discovered.

---

### 6. The init block: `n_init` register planes

**Layer: model+lib+RTL.**

**Mechanism.** One of the header's two reserved words becomes
`n_init` (0..13). An old loader refuses a non-zero reserved word,
which is again the version guard already in place. When `n_init > 0`,
registers `r3 .. r(2 + n_init)` are loaded from `n_init` **planes** at
a new `INIT_PTR`, where plane `j` is a dense array of `n` elements at
`base + j * n * esz`. `r0`, `r1`, `r2` still come from `a`, `b`, `c`,
so nothing existing moves.

**Plane-major, not lane-major, and that is the whole cost argument.**
A plane is byte-for-byte the same address pattern the `a` stream
already reads, so the load loop is the existing stream read executed
`n_init` times with a different base: **no transpose, no crossbar, no
new datapath.** A lane-major block - value `j` of lane `i` at `i*R+j`,
which is the shape the deposit buffer already produces - would need a
word-level transpose on the load path to fill a beat-organised
register file, and that is real silicon for a convenience the host can
provide.

**What it buys.** `docs/COLLATZ.md` and `docs/ORBITS.md` asked for the
same thing in different words. Orbits shows the limit binding: "a
program can be entered only at a state with at most three non-zero
components", so a planar Kepler integration is one call that cannot
resume and the outer solar system cannot start at all. With `n_init`,
every 2-degree-of-freedom system is resumable and every
3-degree-of-freedom one is expressible - which is the ask's own
wording. Collatz's fourth state value stops depending on the luck that
it starts at +0.

**What it does not buy, and this should be said plainly.** The outer
solar system's **thirty** state values do not fit sixteen registers,
so no amount of loading reaches them. That workload needs a wider
register file, which is the array study's ground, and the honest
statement is that `n_init` makes the *stated* asks true and leaves the
*hardest* case exactly where it was.

**Costs.** One appended kernel argument (id 9), one header word, one
loop in the load state machine, `n_init` extra read bursts at run
start. The host API needs a new entry point rather than a changed one:
`cft_program_run_init(prog, a, b, c, init, deposits, counts, n, flags,
bus)`.

**What must be proven.** That `n_init = 0` is byte-identical to today
across the whole corpus, and that a program entered with `n_init`
planes equals the same program entered with those values arriving some
other way. P2 and P3 are untouched: an initial value is not a
cross-lane condition.

---

### 7. `IMEM_D` 1024 -> 4096, before anyone builds `CALL`

**Layer: +RTL only, and it is a parameter.**

**Mechanism.** Change the default. `PCW = $clog2(IMEM_D)` grows from
10 to 12 bits; the header check and the loader cap follow the
parameter as they already do.

**What it buys.** `docs/ATLAS.md`'s fourth ask is code size: `hopf` is
"roughly 600 instructions" against 1,024, and "`buddha` with its two
nested loops more". At 4,096 the question stops existing for both, and
the emitter can stop hoisting to fit.

**Costs.** 1,024 x 8 B = 8 KiB today; 4,096 x 8 B = 32 KiB. That is
+24 KiB = **+6 RAMB36**: a real 37% on the tile's own sixteen, and
1.3% of a Kintex-7 325T's 445 or 1.6% of an Artix-7 200T's 365. On the
VU35P it is noise. Note also that under item 1 half of every ALU word
stops being zero, so the *effective* growth is smaller than the
nominal one - and that items 1 and 7 together cost about ten BRAM
while item 9 returns about seven, which is the arithmetic that makes
the three of them one plan rather than three.

**Why this ranks above `CALL`.** `CALL` trades instruction memory for
a return-address register, a call/return state machine, a depth limit
that has to be validated the way `MAX_LOOP_DEPTH` is, and a new class
of program the loader must refuse (recursion, unbalanced returns). It
buys image size. If image size costs six BRAMs, buy the BRAMs. Build
`CALL` when a positive overflows 4,096 - which step 3 of ATLAS.md's
order of work will measure on sixty-eight real positives rather than
guess.

---

### 8. The program API in the wasm surface

**Layer: neither model nor RTL. Pure binding work.**

**Mechanism.** `bindings/wasm/wasm_api.c` exports `cftw_*` for every
library operation and not `cft_program_load` / `_run` / `_free` /
`_get_info`. Wrap them.

**What it buys.** The five browser demos currently run the tools' loop
engines, so the page measures the engine the design does not advocate.
`docs/BENCHMARKS.md` reports the program engine at 1.06-2.1x the loop
natively; the demos cannot show it. It also makes the browser a place
where an atlas positive can be run and its records compared, which is
the cheapest possible parity harness.

**Costs.** A module rebuild, which `docs/HOSTAPI.md` already notes is
the reason it has waited. Nothing else - and it is the only item in
this list that touches neither the contract nor the tile.

---

### 9. Static deposit slots: a machine cursor instead of a per-lane count

**Layer: model+lib+RTL. The largest structural idea here; see section 3.1 for the full argument.**

**Mechanism.** A new control code (6 is free; only 0-5 are assigned of
an 8-bit field) writes register `ra` to slot `cursor`, where `cursor`
is a **single per-run counter incremented on every execution of the
instruction regardless of any lane's active bit**, not a per-lane
count. Because every lane executes the same instruction stream, the
cursor is identical on every lane and every tile.

**What it buys.** Three things at once, and they are unusual company.
(a) The deposit buffer's `max_deposits * NBEATS * 32 B` shrinks to
roughly one beat plus a drain FIFO, because every active lane in a
beat writes the same slot in the same cycle - **32 KiB back, which by
0.1's BRAM arithmetic is eight of the tile's sixteen RAMB36** - and
`MAXD` stops being a cap at all, which retires 0.1. (b)
`docs/SEQUENCER.md` currently has to concede that "**P2 is a corollary
of P3, not an independent property**", because the deposit address
contains `d`, the lane's own count, which depends on the early exit.
With a machine cursor the address is a function of the instruction
stream and the immediate trip counts alone - **P2 becomes independent
of P3**, which is a strengthening of the determinism argument, not a
trade against it. (c) The zoom workload's flagship shape - deposit
every iteration - becomes free rather than the case that makes the
deposit buffer dominate.

**Costs.** It needs a companion decision on layout. At the current
lane-major addressing (`i * max_deposits + d`) a beat's eight lanes at
one cursor are 8 scattered words, which is why the buffer exists. A
**plane-major** deposit - slot `d` of lane `i` at `d * n + i` - makes
that write eight contiguous words, i.e. one beat, and streams. So the
new control code should carry a plane-major output layout, and the
header should say which layout an image uses. That is two ABI shapes
where there was one, and the host must be able to present either.

**Why it is a new code and not a change to `DEPOSIT`.** They produce
different bytes when lanes diverge: today an inactive lane's skipped
deposit shifts all its later deposits down; with a cursor it leaves a
`+0` hole. An opcode's meaning may never change once assigned, so
`DEPOSIT` stays exactly as it is and this sits beside it.

**What must be proven.** The whole existing lattice: the model first,
then `test_seq.py`'s optimisation-on/optimisation-off equivalence
(which becomes *easier* to state, per (b)), then the fuzz corpus
shared with `program.c`, then `tb/test_seq_core.py`. Plus the new
invariant: a run split across tiles writes the same bytes, which for
the plane-major layout means the split must be on `n` and the stride
must be the *global* `n`, not the tile's slice - a real trap and worth
a directed test.

**Doctrine.** It brushes nothing and repairs one thing. The only
caution is that `counts` remains necessary (a deposited `+0` is still
indistinguishable from an untouched slot), so this is not a
simplification of the host API.

---

### 10. A profile name in CAPS, for the third tier

**Layer: model+lib, plus four bits of an existing register.**

**Mechanism.** CAPS already encodes formats and opcode groups. Name
the useful combinations - say `CFT-BASE` (fp32/fp64, arithmetic +
sign + min/max + predicate + integer), `CFT-SEQ` (BASE + sequencer +
the item-3 feature nibble), `CFT-FULL` (everything, all four rungs) -
in `docs/COMPLIANCE.md` and let `cft_get_caps` report the highest
profile a device satisfies.

**What it buys.** The third tier's whole premise is many small tiles
on many parts. An emitter targeting "any tile with `CFT-SEQ`" is a
different and much better proposition than one probing eight CAPS bits
and hoping. It costs nothing in bits (it is a *name* for a CAPS value,
computed, not stored) and it gives docs/PLATFORMS.md's board survey a
column that means something.

**Doctrine.** It is the only place I would extend the *contract's*
surface rather than the tile's, and it deliberately does not create a
tier that computes different bits. A profile names a subset of
operations; it never names a different answer. That distinction is
what keeps `docs/DETERMINISM.md`'s promise intact and is why I would
not build any of the "reproducible tier that trades an operation's
shape for portability" ideas - see 3.4.

---

### 11. Per-lane flags packed into the `counts` word

**Layer: model+lib+RTL, and it costs no new stream.**

**Mechanism.** `counts` is one `uint32` per lane and a deposit count
needs at most 21 bits (the model's own `MAX_DEPOSITS` is 2^20). Behind
a `MODE` bit, put the lane's sticky five IEEE flags in `counts[31:27]`.
Zero new pointers, zero new arguments, zero new AXI masters - and
default-off means byte-identical to today.

**What it buys.** `docs/COLLATZ.md`'s and `docs/HOSTAPI.md`'s ask 1,
for the program path only: `flags_out` is a union over the call and
cannot say which element left exactness.

**What it does not buy, and the ask overstates this.** The Collatz
witness FMA is doing double duty: it is also the *predicate* that
`SETACT` uses to drop an element out mid-trajectory. An end-of-run
per-lane flag word cannot do that, because the trajectory would
already be wrong. So per-element flags remove a reporting problem and
one deposit slot of four, not the two instructions the design note
implies. That is worth writing down before anyone builds it expecting
10% of a loop body back.

**Costs.** Five bits per lane of sticky state (640 flops at fp32 x
NBEATS x WORDS), the OR into them where the run-level OR already
happens, and the pack at drain. `cft_run` has no `counts` array, so
this does *not* generalise to the elementwise path - which is the
right answer, because the elementwise path's union is per-call and a
caller who wants per-element flags there can issue smaller calls.

---

### 12. A lane shift, behind a non-splittable program flag

**Layer: model+lib+RTL, and it is the only item that costs doctrine.**

**Mechanism.** An operand form that reads register `r` of lane `i-1`.
In the RTL the register file is already beat-wide, so within a beat
this is a barrel shift of 256 bits by `esz`; across a beat it needs
the previous beat's word, which the issue machine read the cycle
before, so one holding register.

**What it buys.** `docs/MERSENNE.md`'s carry chain becomes one program
with a `REPEAT` and a `SETACT` on "still carrying", which is exactly
the early exit's shape, and "would turn five host calls per pass into
one program call per squaring".

**What it costs, and why it ranks here.** Lane 0 of a block needs the
last lane of block `b-1`. Blocks are the library's partitioning, and
P2/P3 exist to make partitioning invisible. **A cross-lane read makes
the partition observable**, which means a program using it may not be
split across tiles and its block boundaries must be defined in the
contract. That is buildable - a header flag marks the program
non-splittable, libcft refuses to partition it, CAPS advertises the
feature, and lane -1 is defined as `+0` at the run's start and the
previous lane's value in index order thereafter - but it creates the
first class of program whose answer depends on a machine property, and
the whole project is built on there being no such class. One workload
is not enough to buy that. The partial workaround `docs/MERSENNE.md`
itself records - two streams at different offsets into the same array -
needs no hardware and is the right answer until a second workload asks.

---

### 13. `CALL`

**Layer: +RTL. Ranked here because item 7 removes most of its value.**

Its only real customer is atlas code size, and six BRAMs are cheaper.
It does **not** deliver what `docs/ORBITS.md` and `docs/ENCLOSE.md`
asked for - see 2.6 - so it should not be sold as answering that ask.

---

### 14. In-program cross-lane reduction - **reject**

`docs/MERSENNE.md` asks for it and `docs/ENCLOSE.md` argues against
it in the same breath ("a reduction crosses lanes, so the dot kernel
can never be a program, and should not be"). The decisive fact is
mechanical rather than doctrinal: the contract's tree is defined over
the **whole index range**, and a program only ever sees a block -
`BLOCK_LANES = 64` in `program.c`, `NBEATS * WORDS = 128` at fp32 in
the RTL. A reduction inside a program would therefore be a reduction
over a block, and **the block size differs between the two backends
today**. There is no version of this feature that does not either put
the block size in the contract or return different bits on different
backends. `cft_reduce` exists and is correct; leave it there.

---

### 15. In-program correctly rounded divide / square root - **reject as stated**

`seqprogs.py` partitions div and sqrt into host prep, program core,
host finish, and the finish is not incidental: `div_finish` assembles
a `(p+2)`-bit significand from a deposited residual and a midpoint
probe, then calls `round_pack` at exponent `u2.e + D - 2`. That is a
single rounding of a wider-than-format value at an arbitrary scale
into a possibly-subnormal destination, and it cannot be a `MUL` by
`2^D` (which double-rounds in the subnormal case) - which is precisely
why `cft_scaleb` is a different operation. An in-program divide
therefore needs a **new rounding opcode**, i.e. a second implementation
of the contract's single rounding authority. "One definition of
correct" is the repo's first design rule. If a hardware divide is ever
wanted, it should be a microcoded macro-op executing the existing
sequence on hidden registers - which is study A's question, not mine -
and not a `CALL`.

---

## 2. The nine asks: a verdict

| # | ask | from | verdict |
|---|---|---|---|
| P1 | more input streams / load registers from the deposit buffer | Collatz, orbits | **build**, as plane-major init planes (item 6), not as a fourth stream and not from the deposit buffer |
| P2 | optional per-element flag output | Collatz | **build small**, in `counts[31:27]` behind a MODE bit (item 11); it buys less than the ask thinks |
| P3 | more than sixteen constants | enclose | **build first** (item 1). Highest value per unit cost in the whole set |
| P4 | a per-iteration broadcast | zoom | **build, but not as asked** (item 5): an external bank re-bound per call, unrolled 128 deep, is cheaper than a counter-indexed fetch and needs no new addressing mode |
| P5 | a lane shift and an in-program cross-lane reduction | Mersenne | **split them**: the shift is buildable behind a non-splittable-program flag and is not yet worth the doctrine (item 12); the reduction is a **reject** (item 14) |
| P6 | a callable composed operation | orbits, enclose | **reject as stated** (item 15). `CALL` does not deliver it; a microcoded divide might, and that is another study's call |
| H1 | per-element flags on `cft_run` and `cft_program_run` | Collatz | **program only** (item 11). Not on `cft_run`: no `counts` array to hide it in, and a caller wanting per-element flags there can issue smaller calls |
| H2 | a stride-0 scalar operand for `cft_run` | all five | **build** (item 4). The only host-API ask that is also a 25%-per-operand bandwidth cut |
| H3 | the program API in the wasm surface | demos | **build** (item 8). Costs a module rebuild and nothing else |

Sentence by sentence:

**P1 (input streams).** Worth building, and the right shape is not the
one asked for. A fourth *stream* solves one case; `n_init` register
planes solve all of them at the same cost, because a plane is the
existing stream read at a different base. Loading from the *deposit
buffer* is the expensive version of the same idea - the deposit buffer
is lane-major and the register file is beat-major, so it needs a
transpose the plane form does not. Note the honest limit: this makes
every 2- and 3-degree-of-freedom system work and leaves the outer solar
system's thirty values exactly where they were, because sixteen
registers is the wall there, not the loading.

**P2 / H1 (per-element flags).** Worth building cheaply, and worth
being clear that it does not remove the Collatz witness, which is also
the loop's drop-out predicate. `counts[31:27]` behind a MODE bit costs
no stream and no argument; a fifth output stream for `cft_run` costs
both and buys a report a smaller call already gives.

**P3 (more constants).** Build it first. It is the only ask that costs
nothing in encoding, nothing in instruction memory (0.2), and turns a
measured 6.6 operations-per-element-moved into a measured 102.6 on the
one workload that quantified itself.

**P4 (per-iteration broadcast).** Worth solving; the ask's two proposed
shapes are both bigger than the problem. An external constant bank plus
a 128-deep unroll gets the zoom perturbation onto the tile with no new
addressing mode and no new determinism argument, and leaves
`imm[31:24]` free for a counter-indexed form if measurement later
demands one.

**P5 (lane shift / reduction).** These are two asks, not one. The
reduction is impossible without putting a block size in the contract
and should be refused permanently. The shift is possible but creates
the project's first non-splittable program class, and one workload -
whose own design note supplies a no-hardware workaround - does not
justify that yet.

**P6 (callable composed operation).** The workloads want correctly
rounded division inside a loop. `CALL` would not give it to them,
because `cft_div`'s host finish is a single rounding of a wide
significand at an arbitrary scale and its core already occupies
thirteen registers. Refuse the ask as stated and record what would
actually answer it, so nobody builds `CALL` and finds the loop still
leaves the program.

**H2 (stride-0).** Build. It is the highest-value host-API change and
it is a hardware feature wearing an API costume: 25% of the elementwise
read bandwidth per scalar operand, on a tile that `docs/PLATFORMS.md`
puts within a few percent of a 7-series DDR3 ceiling.

**H3 (wasm program API).** Build whenever the module is next rebuilt.
It is the only item in this study that changes no contract and no
silicon, and until it lands the public demos measure the engine the
architecture argues against.

**Ordering.** 1 (indexed constants) -> 3 (publish the caps) -> 2
(`IMUL`) -> 4 (stride-0) -> 5 (external bank) -> 6 (init planes) ->
7 (`IMEM_D`) -> 8 (wasm) -> 9 (static deposit) -> 11 (per-lane flags).
The first three are the ones I would do before anything else, and
together they are about a fortnight of model-and-library work plus one
RTL step.

---

## 3. Five things this project has not written down

### 3.1 The deposit cursor makes P2 independent of P3

Item 9's real payload is not the 32 KiB. `docs/SEQUENCER.md` is
scrupulous about a weakness in its own argument: the deposit address
contains `d`, the lane's own deposit count, and `d` depends on the
shared program counter, which depends on the early exit, which is a
cross-lane condition - "so **P2 is a corollary of P3, not an
independent property**", and the two have to be fuzzed together.

A machine-level deposit cursor - one counter per run, advanced by the
instruction and not by any lane - removes that dependency. The address
becomes a function of the instruction stream and the immediate trip
counts alone: two facts that are the same on every tile, in every
partition, whatever converges when. **P2 stops needing P3 at all.**

That is worth more than the area. This project's central asset is that
its determinism properties are provable rather than probable, and one
of the three is currently a corollary. Making it independent is a
strengthening that also happens to save the largest of the sequencer's
three memories and retire the `MAXD` cap that 0.1 says will otherwise
refuse the flagship workload on card day. I have not seen a proposal
in this repo that improves the doctrine and the area and the
throughput at once, and this is one.

### 3.2 `IMUL` deletes the atlas input-block ask

`docs/ATLAS.md` lists four asks and treats them as four. Reading them
together, the third is a consequence of the first.

The registry contract hands a positive seven per-sample values: `q.x`,
`q.y`, four in `rnd`, and `seed`. But `rnd` is not independent data -
it is four draws, and a draw is `lowbias32` on a bit pattern, which is
what `IMUL` makes expressible in-lane. ATLAS.md half-says this itself
("With it, the whole stream is in-lane and the three input streams are
enough") and then lists the wider input block anyway. The emitter
should hand the tile `q.x`, `q.y`, `seed` - **exactly three streams** -
and generate `rnd[0..3]` in-lane from `seed` with the same hash the GPU
uses, which is what makes the parity claim hold in the first place.

So the atlas port's minimal hardware requirement is **two** things, not
four: `IMUL` and indexed constants. Section 4 walks it.

### 3.3 The instruction memory is 50% enforced zeros, and that is the budget for everything else

Every ALU instruction carries 32 bits of `imm` that the loader refuses
to let be non-zero. On a 1,024-instruction image that is 4 KiB of the
8 KiB `imem` provably zero. This is not a criticism of the encoding -
a uniform 64-bit word is why the loader can be simple and the readback
hash can be canonical - but it reframes the cost of every proposal
that wants to say something more per instruction. Indexed constants
(item 1), a counter-index mode, a scalar-operand form, a lane-shift
operand form: all of them fit in space that is already allocated,
already zero, and already refused. The right question is not "can we
afford an immediate field" but "which one thing should the immediate
field mean", and the answer that serves the most workloads is a
constant index.

### 3.4 There should not be a "reproducible tier"

The brief invites the idea of a contract tier that trades an
operation's shape for portability. I looked for a version of it worth
proposing and could not find one, and I think the negative is the
useful finding.

Every candidate has the same defect. A tier that let an implementation
pick its own reduction tree would produce different bits and end the
product. A tier that let a small tile round differently would too. A
tier that let a tile *refuse* operations already exists - it is CAPS,
and `CAPABILITIES.md`'s (repository root) "A MODE selecting a
precision the build lacks is **refused** ... rather than answered with
plausible garbage from banks that are not there" is exactly the right
behaviour. And a tier
that let a tile be *slower* needs no contract change at all, because
latency and rate are nowhere in the contract - which is the observation
`docs/ROADMAP.md`'s `MUL_PASSES` step already banked.

What is genuinely missing is not a tier but a **name** for a subset:
item 10. A profile is a label on a CAPS value, so it can never produce
a different answer, and it gives the third tier's many small tiles
something an emitter can target. That is the whole of the useful idea
that "reproducible tier" gestures at, and it costs four bits and a
paragraph.

### 3.5 Nothing in the ISA should be removed, and here is the evidence

I counted opcode use across the five workload tools
(`host/tools/{collatz,enclose,mersenne,orbits,zoom}.c`):

    MUL 62  FMA 51  ADD 37  SUB 21  SELECT 20  NEG 14  MIN 14
    CMPLT 12  CMPLE 11  ISHR 8  CMPEQ 6  ABS 6  MAX 5
    RSQRT_SEED 4  ISUB 4  ISHL 2  ICMPLT 2  IAND 2  IADD 2
    COPYSIGN 1

Never used: `MINNUM`, `MAXNUM`, `IOR`, `IXOR`, `RECIP_SEED`. All five
survive scrutiny anyway. `MINNUM`/`MAXNUM` are clause 9.6 requirements
and removing them would end the conformance claim. `RECIP_SEED` is
used inside `cft_div`, which is the library's own first customer.
`IOR` and `IXOR` are used by `docs/ATLAS.md`'s census - the det
library's `^`, `&`, `|` on bit patterns - which is the workload the
tile exists for. So: **no opcode should be removed**, and the fact that
five are unused by the benchmark suite is a statement about the
benchmark suite, not about the ISA.

Two things *are* worth trimming, and neither is an opcode. The
`n_consts <= 256` allowance against sixteen addressable slots is dead
payload (0.2) and item 1 resolves it by making the slots real. And
loop depth 4 has never been exercised beyond 2 by any workload - orbits
uses two levels, everything else uses one or none - but the cost is a
four-entry stack of `{pc, count}` in the RTL and one multiply-out in
the loader, so it is not worth the churn to narrow it. Recording that
nothing has used depth 3 or 4 is more useful than removing them,
because it says where a future program model could spend the depth
instead.

*(One idea I considered and dropped, recorded because the reasoning is
reusable: a `GETFL rd` control code exposing the lane's sticky flags as
a value. The plumbing is nearly free - `cft_seq` already receives
`lane_flags`, five bits per lane per issue, and currently only
OR-reduces them, so making them addressable is a writeback mux. But the
workloads' "witnesses" turn out to be **value identities**, not flag
reads: Collatz's is `fma(x, -3, y) == 1`, Mersenne's is `hi*B + lo ==
v` plus two range checks. `GETFL` would cost more instructions than the
witnesses it replaced. The cheap plumbing was not the constraint; the
algorithms were.)*

---

## 4. What the atlas integration actually needs, minimally

The finding that matters: **atlas can run a positive end to end with
zero RTL**, because the software backend is a conforming
implementation of the same contract and `cft_program_run` reaches it.
The tile is a speed step afterwards, not a precondition. That reorders
`docs/ATLAS.md`'s order of work usefully.

The minimum, in order, with what each unblocks:

**Step A - `IMUL` in the golden model and libcft** (model+lib, no
RTL). One line in `softfloat.py`, one case in `softfloat.c`, a
conformance set in `vectors/`. Unblocks the entire draw stream, and by
3.2 unblocks the seven-wide input block too: the emitter hands `q.x`,
`q.y`, `seed` and generates `rnd[0..3]` in-lane. **After this step every
det function is expressible as a program.**

**Step B - indexed constants in the golden model and `program.c`**
(model+lib, no RTL). Bit 30 as `kx`, `imm` as three 8-bit indices, the
bank to 256. Unblocks one image per positive: `hopf`'s eleven contract
constants plus an inlined `det_sincos`'s dozen stop competing for
sixteen slots.

**Step C - the det library's ISA target** (atlas-engine, no cft-fp256
change). `tools/gen-detlib.mjs` grows an ISA output; `u2f` is the
six-instruction conversion ATLAS.md derives; the two `lowbias32` sites
become `IMUL`. Verified function by function against the pinned GLSL
through libcft's software backend.

**Step D - `core/emit-cft.mjs` and `host/tools/positive-run.c`**
(atlas-engine + a new tool here). `hopf` and `jong` first. The oracle
is `seq.py`; the second oracle is a debug GLSL variant writing records
instead of depositing, compared per sample. **This is the positive
running end to end, and nothing above it needed hardware.**

**Step E - `IMUL` and `kx` in the RTL** (+RTL). Model-first as always,
then `tb/`, then CAPS and the feature nibble of item 3. This is the
first RTL the workload asks for and it is two features, not four.

**Step F - only if step D measures the need**: `IMEM_D` to 4,096
(item 7) if a positive overflows; `n_init` planes (item 6) if some
positive genuinely needs more than three per-sample inputs that are
not derivable from a seed; `CALL` last and probably never.

Against `docs/ATLAS.md`'s own list: ask 1 (`IMUL`) is step A, ask 2
(immediate constants) is subsumed by step B - **and should be, because
an immediate is a value and a value is format-dependent**: 32 bits is a
whole fp32 constant and a fifth of an fp256 one, so "operand C is
`imm`" works only at fp32 and would need a widening rule everywhere
else. An *index* has no such problem and serves both the fp32 atlas
port and the fp256 enclosure tool. Ask 3 (more inputs) is deleted by
3.2. Ask 4 (`CALL`) is deferred behind six BRAMs.

---

## 5. What I would build in one week

**Indexed constants: item 1, in the golden model and libcft only. No
RTL.**

Why this one. It costs no encoding space, no instruction memory and no
ABI surface; its version guard already exists as the reserved-bit
refusal; it is the prerequisite for the atlas port (step B above); and
it is the only proposal in this study whose payoff can be **measured
today, on the software backend, with no card and no simulator.**

The week: two days for `seq.py` (the `kx` decode, the canonicity
refusals, the fuzz arm) and its property tests; two days for
`program.c` and the shared corpus (`make libcft-seq`); one day to
teach `host/tools/enclose.c` to emit a single unchunked Horner when the
device advertises the feature; one day for the measurement below and
the doc changes.

**The measurement that decides whether it worked**, and all four parts
run in the quick budget:

1. **The chain is unchanged.** `cft-enclose --engine program` at every
   format prints the same SHA-256 chain it prints today, and the same
   one `bindings/wasm/demos_chains.json` recorded on 2026-09-04.
   Indexed constants reorder nothing and re-associate nothing, so a
   changed chain means a bug, not a design question. This is the gate;
   the rest are the payoff.
2. **The call count collapses.** `--degree 127` goes from 16 chunk
   programs to 1. `docs/REMOTE.md` records the enclose tool's library
   calls as 189/237/315/453 for fp32/fp64/fp128/fp256; the chunk-driven
   share of those should fall by about 16x.
3. **The frames collapse, from the server's own counters.** Run it
   against `cft-serve` and read `STATS`. This is the number that
   matters for `docs/ROADMAP.md`'s third tier, and it is the same kind
   of measurement that produced "one frame where the chunk route needs
   twenty-one".
4. **The arithmetic intensity crosses the line.** 33 instructions over
   5 element transfers = 6.6 today; 513 over 5 = 102.6 at degree 127.
   `docs/SEQUENCER.md`'s crossover is K ~ 30. Crossing it is the claim
   the sequencer was built on, and this would be the first workload to
   cross it on a *table-driven* kernel rather than an iterative one.

If (1) fails the feature is wrong. If (1) holds and (4) does not - if
the intensity does not move because something else dominates - the
feature is right and the priority was wrong, and item 3 (publish the
caps) becomes the next week instead.

**Second choice, if a week of RTL were wanted instead:** item 3, the
CAPS publication, because 0.1 says the alternative is discovering the
`MAXD` refusal on card day with a soldering iron in the room.

---

## 6. What I could not evaluate

- **Any area or timing number for anything I propose.** I read
  `cft_seq.sv` and `cft_krnl.sv` for structure and capacity and quoted
  the repo's own measured numbers (139,404 LUT, +0.307 ns, 292 DSP,
  1.250 marginal cycles a beat, 36 fixed), but I ran no synthesis - the
  brief forbade it and the host is busy. The BRAM arithmetic in items
  1 and 7 is capacity arithmetic (bytes to RAMB36), not a synthesis
  result. **The 256-entry constant bank's effect on the issue path is
  the item I am least able to price**, because `cft_seq.sv:1254` reads
  `kmem` combinationally today and a BRAM read is a stage; that is
  study C's question and it could change item 1's ranking if the answer
  is bad.

- **`IMUL`'s real cost.** Whether it can be steered through the FMA's
  existing chunked significand multiplier - which would make it nearly
  free - or needs eight 32x32 multipliers of its own, is study A's and
  study B's question. My ranking assumes the expensive answer and it
  still ranks second, so the conclusion is robust to it, but the number
  is not mine.

- **Whether sixteen registers is the right number.** Item 6 stops at
  the outer solar system's thirty values and says so. Widening the
  register file trades against the lane block and the deposit buffer -
  `docs/SEQUENCER.md`'s "trading pipeline depth against deposit depth
  is the axis a chiplet turns" - and that whole axis belongs to the
  array study.

- **Any hardware throughput claim.** There is no card, `hw_emu` seconds
  measure the simulator, and this repo's rule is that projections live
  in `docs/SCALING.md` labelled as projections. Every "what it buys"
  above is either a static count (instructions, transfers, frames,
  library calls, bytes) or a ratio of such counts. None of them is a
  wall-clock prediction and none should be read as one.

- **Whether the atlas emitter can actually hold its register
  discipline.** Step C of section 4 assumes a det function inlines into
  a register allocation that fits sixteen registers alongside the
  positive's own state. `docs/ATLAS.md` counts instructions but not
  registers, and `seqprogs.py`'s divide core - thirteen of sixteen -
  is the warning that a plausible-looking sequence can run out of
  registers before it runs out of instruction memory. That is a
  measurement step D would produce and I could not.

- **`buddha`, and every positive except `hopf`.** The 600-instruction
  figure is ATLAS.md's for one positive. Whether 1,024 or 4,096 is the
  right `IMEM_D` is a census over sixty-eight positives that does not
  exist yet, which is exactly why item 7 is a parameter change and not
  an architecture.
