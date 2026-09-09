# libcft on microcontrollers

The claim this project exists to make is that the same operation gives
the same bits everywhere. "Everywhere" has meant a host, a WebAssembly
module, and an FPGA tile. This is the same library on parts with
kilobytes: a Raspberry Pi Pico, an ESP32, and the 8-bit ATmegas of the
Arduino Uno, Nano and Mega.

Nothing was ported. libcft has no floating-point dependence to begin
with - it is integer arithmetic over 32-bit limbs with 64-bit
intermediates, and its API boundary is byte-level little-endian
interchange encodings - so a Cortex-M0+ with no FPU computes what an
x86 computes because it is running the same source, not an equivalent
one. What this document is about is the two questions that remain:
**how much of the library fits on which part**, and **how you check
that what fits is right**.

Both are answered with numbers. The sizes are from
`arduino-cli compile`; the stack figures are from `avr-gcc
-fstack-usage`; the conformance results are replays of the published
vector sets, case by case, bit for bit.

Contents: [what fits](#what-fits) · [the build
profiles](#the-build-profiles) · [what AVR cannot
have](#what-avr-cannot-have-and-why) · [sizes](#sizes-per-board-per-sketch)
· [the stack](#the-stack) · [the replay
harness](#the-replay-harness) · [the
protocol](#the-protocol-csrp1) · [flashing and
replaying](#flashing-and-replaying-per-board) · [what is
pending](#pending-on-hardware)

---

## What fits

| board | MCU | flash | RAM | formats | library |
|---|---|---|---|---|---|
| Raspberry Pi Pico | RP2040, Cortex-M0+ 133 MHz, no FPU | 2 MB | 264 KB | fp32 fp64 fp128 fp256 | everything |
| ESP32 dev module | Xtensa LX6 240 MHz | 4 MB | 520 KB | fp32 fp64 fp128 fp256 | everything |
| Arduino Mega | ATmega2560, 16 MHz | 256 KB | 8 KB | fp32 fp64 | `CFT_TINY` |
| Arduino Uno / Nano | ATmega328P, 16 MHz | 32 KB | 2 KB | fp32 fp64 | `CFT_TINY` |

"Everything" on the 32-bit boards means: the elementwise opcodes
(`cft_run`), the reductions and 9.4's scaled products, divide and
square root, the clause-5 completion set, 9.5's augmented arithmetic,
9.6's magnitude forms, 5.4.1's formatOf arithmetic, 5.12's character
conversions with 9.7's payload operations, the sequencer
(`cft_program_*`), and all 39 correctly rounded transcendentals. Two
things are always left out on a board, automatically, because there is
nothing for them to do: the `cft://` socket backend (there is no
Berkeley socket layer) and `cft_conformance()` (there is no directory
of vector sets to open). `cft_config.h` does that from the `ARDUINO`
macro, so an Arduino build needs no flags.

`CFT_TINY` on the AVRs means: the elementwise opcodes, the reductions
and scaled products, divide and square root, clause 5, augmented
arithmetic and 9.6 - at fp32 and fp64. No transcendentals, no
sequencer, no character conversions, no formatOf. The next two sections
say why.

## The build profiles

`host/include/cft_config.h` is new and is the whole of the mechanism.
It names each removable piece, gives every macro a default that
reproduces the library exactly as it was, and defines one profile
macro, `CFT_TINY`, that turns on the set an 8-bit part needs.

**What "reproduces it exactly" is worth, measured.** Fourteen of the
library's fifteen translation units compile at the default profile to
objects that are byte-identical to the ones the same compiler produced
before `cft_config.h` existed. The fifteenth is `device.c`: same
sections, same symbols, same sizes, and the difference is fourteen
instructions of `cft_reduce` that the scheduler put in a different
order around an added test it folded away to nothing. Total text across
all fifteen is 280,248 bytes before and after.

| macro | removes | default |
|---|---|---|
| `CFT_MAX_FORMAT` | formats above the ceiling, and sizes `CFT_BN_LIMBS` from it | 3 (fp256) |
| `CFT_BN_LIMBS` | the width of every intermediate | 64 / 18 / 9 by ceiling |
| `CFT_CHUNK` | elements per pass in the composed operations | 4096, 32 on a board, 8 tiny |
| `CFT_ERRMSG_MAX` | the last-error buffer and its `vsnprintf` | 320, 1 tiny |
| `CFT_NO_TRANSCEND` | `transcend.c`, `mpfloat.c`, `mp_2opi.h` | off |
| `CFT_NO_PROGRAM` | `program.c`, `sha256.c` | off |
| `CFT_NO_CHARS` | `chars.c` | off |
| `CFT_NO_FORMATOF` | `formatof.c` | off |
| `CFT_NO_DIVSQRT` | `divsqrt.c` (implies `CFT_NO_FORMATOF`) | off |
| `CFT_NO_CLAUSE5` | `clause5.c` (implies `CFT_NO_FORMATOF`) | off |
| `CFT_NO_AUGMENTED` | `augmented.c` | off |
| `CFT_NO_REDUCE` | `reduce.c` | off |
| `CFT_NO_CONFORMANCE` | `conformance.c` | off, on under `ARDUINO` |
| `CFT_NO_REMOTE` | `backend_remote.c` | off, on under `ARDUINO` |
| `CFT_NO_GETENV` | the two route-override environment reads | off |

Each module switch removes its translation unit **entirely** rather
than leaving it for the linker's `--gc-sections`, because what does not
fit on a small part is as often a constant table as it is code, and a
table reachable from one live function is not collected.

None of this changes an answer. Every profile computes what the golden
model computes; the switches decide what is PRESENT, and an absent
entry point is absent at link time, which is a message a caller can
act on. That is checked rather than asserted - see
[the replay harness](#the-replay-harness).

**The library on an ATmega328P**, per module, `avr-gcc -Os
-ffunction-sections`, before `--gc-sections`:

| module | flash | RAM |
|---|---:|---:|
| clause5 | 18,666 | 0 |
| divsqrt | 14,088 | 0 |
| softfloat | 9,642 | 126 |
| device | 5,368 | 675 |
| reduce | 4,886 | 0 |
| bigint | 4,748 | 0 |
| augmented | 4,352 | 0 |
| **total** | **61,750** | **801** |

Twice the Uno's flash, which is what `--gc-sections` is for: a sketch
pays for what it calls. `Hello`, which calls `cft_run` and
`cft_get_caps`, is 13,180 bytes.

Note the 801 bytes of RAM, on a part that has 2,048. On AVR every
`const` object is copied into RAM at startup unless it is marked
`PROGMEM`, so `cft_op_name`'s table, `cft_strerror`'s messages and
`cft_sf_formats` are static RAM there. That is the single largest
non-obvious cost of this library on an 8-bit part, and it is why
`CFT_REPLAY_MIN` (below) drops the explanatory half of a refusal.

## What AVR cannot have, and why

Three exclusions on the ATmegas are not tuning decisions. Each is a
number against a hard limit.

**binary128 and binary256 need a 32-bit `int`.** `softfloat.c` holds
exponents in `int`, and `int` is sixteen bits on an 8-bit AVR. An
unpacked significand is an integer whose least significant bit has
weight `2^e`, so `e` runs down to `emin - (p-1)`; the fused
multiply-add's first line adds two of them.

| format | `emin - (p-1)` | `ep = ua.e + ub.e` at worst | fits `int16_t`? |
|---|---:|---:|---|
| fp32 | -149 | -298 | yes, 100x over |
| fp64 | -1,074 | -2,148 | yes, 15x over |
| fp128 | -16,494 | **-32,988** | no, and by 220 |
| fp256 | -262,378 | **-524,756** | no, by a factor of 16 |

So binary128 on a 16-bit `int` is not a tight fit that might work: a
subnormal-times-subnormal multiply wraps on the first line.
`cft_config.h` refuses the combination at compile time and prints that
number. Widening every exponent local to `int32_t` would fix it and
would cost an 8-bit part two bytes and two instructions on each of
them, for a format an ATmega would take the better part of a second an
element on. **The binding limit on the Mega is not its 8 KB of RAM -
it is the width of `int`.**

**The transcendentals need 117 KB of constant table.** Phase 3's
argument reduction reads a window of 2/pi from `mp_2opi.h`, which is
117,220 bytes. On AVR that is RAM. Against 8 KB.

**A wide `cft_bn` costs stack, and stack is the scarce thing.**
`cft_bn` is the container every intermediate lives in, so a call's
frame is roughly linear in `CFT_BN_LIMBS`. Measured on an ATmega328P:

| limbs | `sizeof(cft_bn)` | bits | `cft_run` + `cft_sf_compute` |
|---:|---:|---:|---:|
| 8 | 34 | 256 | 630 |
| 9 | 38 | 288 | 686 |
| 10 | 42 | 320 | 742 |
| 12 | 50 | 384 | 854 |
| 16 | 66 | 512 | 1,072 |

`bigint.h`'s requirement is the near-case addend alignment, about
`5p + 3` bits: 268 for binary64, so 9 limbs (288 bits). The narrow
profiles take exactly that - the requirement rounded up to a whole
limb, no margin - and the reason is which failure each shortage
produces. Too few limbs is **loud**: `bigint.c` returns 1 from any
operation that would not fit, `softfloat.c` turns it into
`CFT_ERR_INTERNAL`, and a replay reports a refusal on the first case
that needs the width. Too little stack is **silent**: it writes through
the top of RAM and the part carries on.

(8 limbs - 256 bits, below the bound - also replays every published
fp32 and fp64 case without a refusal. That is why the bound matters:
the sets are a sample of the input space and 269 bits is a statement
about all of it.)

**A composed operation's scratch was sized for a host.** `divsqrt.c`
and `clause5.c` hold a fixed scratch of `CHUNK` elements, and `CHUNK`
was 4,096 - which is 393 KB at binary64 and 1.5 MB at binary256. Every
`cft_div` on every board would have answered `CFT_ERR_OUT_OF_MEMORY`.
It is `CFT_CHUNK` now: 4,096 on a host, 32 on a 32-bit board, 8 under
`CFT_TINY`. A chunk boundary is where the loop reloads its slice, so
this changes no answer; the census at `CFT_CHUNK` 8 is the evidence.

## Sizes, per board, per sketch

`arduino-cli 1.5.2-rc.1` with `arduino:avr 1.8.8` (avr-gcc 7.3.0),
`esp32:esp32 3.3.0` and `rp2040:rp2040 6.1.0`, `--warnings all`,
**zero warnings on every one of the fifteen**. Flash is
`.text + .data`; RAM is the linker's static total, and "free" is what
is left for stack and heap.

| FQBN | sketch | flash | | RAM | | free |
|---|---|---:|---|---:|---|---:|
| `arduino:avr:uno` | Hello | 13,180 | 40% | 608 | 29% | 1,440 |
| `arduino:avr:uno` | VectorReplay | 22,246 | 68% | 931 | 45% | 1,117 |
| `arduino:avr:uno` | Bench | 14,754 | 45% | 812 | 39% | 1,236 |
| `arduino:avr:nano` | Hello | 13,180 | 42% | 608 | 29% | 1,440 |
| `arduino:avr:nano` | VectorReplay | 22,246 | 72% | 931 | 45% | 1,117 |
| `arduino:avr:nano` | Bench | 14,754 | 48% | 812 | 39% | 1,236 |
| `arduino:avr:mega` | Hello | 13,524 | 5% | 608 | 7% | 7,584 |
| `arduino:avr:mega` | VectorReplay | 38,980 | 15% | 4,193 | 51% | 3,999 |
| `arduino:avr:mega` | Bench | 15,120 | 5% | 2,092 | 25% | 6,100 |
| `esp32:esp32:esp32` | Hello | 304,535 | 23% | 21,016 | 6% | 306,664 |
| `esp32:esp32:esp32` | VectorReplay | 419,323 | 31% | 78,520 | 23% | 249,160 |
| `esp32:esp32:esp32` | Bench | 303,211 | 23% | 53,784 | 16% | 273,896 |
| `rp2040:rp2040:rpipico` | Hello | 63,520 | 3% | 9,204 | 3% | 252,940 |
| `rp2040:rp2040:rpipico` | VectorReplay | 173,096 | 8% | 66,736 | 25% | 195,408 |
| `rp2040:rp2040:rpipico` | Bench | 62,824 | 3% | 41,972 | 16% | 220,172 |

Most of the ESP32 and Pico figures are their cores, not this library:
`Hello` on an ESP32 is 304 KB of which the Arduino-ESP32 runtime is
about 290. The library's own contribution is visible in the Pico
column, where `Hello` (elementwise only) is 63 KB and `VectorReplay`
(which reaches the transcendentals, the character conversions and the
formatOf arithmetic) is 173 KB.

Two sizings needed a measurement rather than a guess:

- **ESP32.** 104 KB of static replay buffers overflowed the linker's
  `dram0_0_seg` by 3,088 bytes - that segment is about 160 KB after the
  IDF's own statics, not the 520 KB the part has. 56 KB fits.
- **Uno / Nano.** `VectorReplay` with the whole verb set is about 38 KB
  against 32,256 available. `CFT_REPLAY_MIN` (see below) brings it
  under 23 KB.

A third is a limit rather than a sizing. The Pico and the ESP32 carry a
32 KB character-conversion buffer, and **25 cases** of the 9,300
`to_decimal`/`to_hex` cases in the sets produce a sequence longer than
that - all 25 in binary256, whose smallest subnormal's exact decimal is
183,476 characters. Every binary32, binary64 and binary128 sequence
fits. Those 25 are skipped by name and counted; holding them would need
180 KB of buffer AND the arbitrary-precision natural that produces them
(5^262378 is 609,000 bits), which is not a buffer size problem.

## The stack

The replay's deepest chain on an ATmega328P, from `avr-gcc
-fstack-usage` at the profile the sketch actually builds:

| frame | bytes |
|---|---:|
| `cft_replay_line` (with `rp_do_run` inlined into it) | 168 |
| `cft_run` | 210 |
| `cft_sf_compute` (with `sf_fma` inlined into it) | 476 |
| deepest leaf under it, `cft_bn_mul` | 91 |
| **worst case** | **945** |

Plus return addresses and the timer ISR's frame, call it 985. The Uno
build leaves 1,117, so the margin is about 130 bytes. There is no
recursion in this chain: the two recursive functions in the library are
`cft_sf_reduce` and `sp_tree`, both in the reduction tree, and the
Uno's responder carries no verb that reaches them.

`Hello` (1,440 free) and `Bench` (1,236 free) have more. `Bench`'s
batch is 8 elements on the ATmega328P for exactly this reason: at 24 it
was 1,324 bytes of globals and the fp64 chain would not have fitted
under it.

The 32-bit boards are not close to any of this: the Pico's worst frame
is the fp256 `cft_sf_compute`, and it has 195 KB free.

## The replay harness

The published vectors are 168 set files and 1,071,635 cases: every
operation, every format, every rounding attribute, each with the
expected encoding and the expected exception flags.
`host/tools/cft_selftest.c` replays them by opening the files. A
microcontroller has no files and no room for 194 MB of them, so the
sets stay on the host and the **cases** travel.

    host/tools/serial_replay.py            the host half
    examples/VectorReplay/VectorReplay.ino the device half, over a UART
    bindings/arduino/loopback              the device half, over a pipe
    src/cft_replay.[ch]                    what both of those run

The host reads a line of JSONL exactly as `host/src/conformance.c`'s
reader does - the same sets, walked in the same order, the same fields,
the same expected values - sends the case, and compares what comes back
bit for bit. The report is `cft-selftest`'s shape:

    libcft ABI 0.11 over csrp/1
    transport      COM7 at 115200 baud
    backend        software
    formats        fp32 fp64
    buffers        line 96, stage 0 x2, out 0
    verbs          clr,get,id,put,run

    replaying vectors/out
    ...
    24 sets, 195248 cases, all matching (one element at a time, ...)
    195248 cases checked

**What it checks and what it does not.** `cft_conformance()` replays
each set twice: once an element at a time, which is the pass that pins
each case's exception flags exactly, and once as whole arrays, which
exists to exercise a device backend's partitioning across tiles. This
is the first pass. There are no tiles behind a UART and a part with
2 KB of RAM cannot hold a set, and the report says so rather than
letting the smaller claim read as the larger one.

**A case the device cannot be asked is skipped by name and counted**,
never scored. Three things cause that, and the device declares all
three in its `id` answer so the host knows in advance: a format the
build does not carry, a verb the build does not carry, and a payload
larger than the board's buffers.

### The loopback, and the negative control

`bindings/arduino/loopback` builds the same responder as a host process
speaking the same protocol over pipes. It compiles the **vendored**
copy of libcft - the bytes an Arduino build puts on the part, whose
hashes `vendor.json` records - so a loopback run is the board's library
being held to the golden model at a rate no UART reaches.

    make -C bindings/arduino/loopback CC=gcc
    python host/tools/serial_replay.py --loopback
    python host/tools/serial_replay.py --loopback --corrupt

or all of it at once, which is what the gate runs:

    make embedded                    every leg, every profile, every board
    make embedded EMBEDDED_ARGS=--quick        a shorter census
    bindings/arduino/verify.sh --no-boards     without arduino-cli

It builds four profiles, and each one is a board's:

| binary | profile | what it stands for |
|---|---|---|
| `-full` | default | a host |
| `-board` | `CFT_NO_REMOTE CFT_NO_CONFORMANCE` | Pico, ESP32 |
| `-tiny` | `CFT_TINY` | Uno, Nano, Mega |
| `-tiny128` | `CFT_TINY CFT_MAX_FORMAT=2` | the fp128 ceiling, on a 32-bit part |

`--corrupt` is the reason a green report means anything. The loopback
damages exactly one answer, six ways, and the harness is required to
notice every time:

| mode | what it damages | reaches |
|---|---|---|
| `bits` | one nibble of the result encoding | the encoding comparison |
| `flags` | one nibble of the exception flags | the flag comparison |
| `crc` | the frame's checksum, answer intact | the frame check |
| `seq` | the sequence number, answer intact | the ordering check |
| `drop` | no answer at all | the per-case timeout |
| `text` | one nibble of a `to_decimal` sequence | the `get` path |

A checker that has never been seen to fail proves nothing about the
board it passes.

## The protocol (CSRP/1)

Documented in full in
`bindings/arduino/cft-arduino/src/cft_replay.h`. In brief: ASCII lines
terminated by `\n`.

    request    >SS VERB [field ...] *CCCC
    response   <SS ok  [field ...] *CCCC
               <SS err REASON [text] *CCCC

`SS` is the request's sequence number in two hex digits, echoed by the
response, so a lost or duplicated line is recognised as one rather than
scored as a wrong answer. `CCCC` is CRC-16/CCITT-FALSE over everything
before the ` *`, computed by the same polynomial on both sides and
checked BEFORE the parse, so a damaged line never reaches an operation.

Element encodings travel as the **set file's own spelling**: `0x`
stripped, most significant digit first. Not little-endian byte order -
the wire carries what the JSONL carries, so an expected value is
compared as the string it already is and there is no byte order to get
wrong twice. Character sequences travel as `h` plus hex, because a 5.12
sequence may legally contain spaces and may be empty. Operation names
travel as **names**, resolved on the device through the library's own
`cft_op_name()` and `cft_tr_from_name()`, so there is no third table
for the mapping to drift in.

Verbs: `id`, `run`, `trn`, `aug`, `mmg`, `fof`, `red`, `chs`, `chw`,
`pay`, `put`, `get`, `clr`. Which of them a build carries follows the
library's profile - there is no `trn` where there are no
transcendentals - and `id` reports the list.

`CFT_REPLAY_MIN`, on a part with under 64 KB of flash, narrows that to
`id`, `clr`, `put`, `get`, `run` and drops the explanatory text from a
refusal. Both are flash and RAM decisions with numbers behind them: the
full verb set is 38 KB against the Uno's 32,256, and on AVR a string
literal passed as an argument is RAM whether or not the callee reads
it, so the text is dropped at the CALL through a macro rather than
inside the function. It is a choice about the replay TOOL and not about
the library: `cft_reduce`, `cft_augmented_add` and the magnitude
operations are all still there on an Uno, and a sketch that calls one
gets it.

## Flashing and replaying, per board

Every command below is one line and can be run as written from the
repository root. Replace `COM7` with the port
`arduino-cli board list` shows for that board - **and check it: never
flash `COM1`, which is the motherboard's serial port and not a board.**

Build the tools once:

    make vectors PYTHON=<python>
    make -C bindings/arduino/loopback CC=gcc

### Raspberry Pi Pico

    arduino-cli compile --fqbn rp2040:rp2040:rpipico --libraries bindings/arduino --warnings all bindings/arduino/cft-arduino/examples/VectorReplay
    arduino-cli upload  --fqbn rp2040:rp2040:rpipico -p COM7 bindings/arduino/cft-arduino/examples/VectorReplay
    python host/tools/serial_replay.py --port COM7 --sets 'fp32*' --limit 500 --progress
    python host/tools/serial_replay.py --port COM7 --progress

### ESP32 dev module

    arduino-cli compile --fqbn esp32:esp32:esp32 --libraries bindings/arduino --warnings all bindings/arduino/cft-arduino/examples/VectorReplay
    arduino-cli upload  --fqbn esp32:esp32:esp32 -p COM7 bindings/arduino/cft-arduino/examples/VectorReplay
    python host/tools/serial_replay.py --port COM7 --sets 'fp32*' --limit 500 --progress
    python host/tools/serial_replay.py --port COM7 --progress

### Arduino Mega

    arduino-cli compile --fqbn arduino:avr:mega --libraries bindings/arduino --warnings all bindings/arduino/cft-arduino/examples/VectorReplay
    arduino-cli upload  --fqbn arduino:avr:mega -p COM7 bindings/arduino/cft-arduino/examples/VectorReplay
    python host/tools/serial_replay.py --port COM7 --sets 'fp32,fp64' --limit 500 --progress
    python host/tools/serial_replay.py --port COM7 --sets 'fp32*,fp64*' --progress

### Arduino Uno

    arduino-cli compile --fqbn arduino:avr:uno --libraries bindings/arduino --warnings all bindings/arduino/cft-arduino/examples/VectorReplay
    arduino-cli upload  --fqbn arduino:avr:uno -p COM7 bindings/arduino/cft-arduino/examples/VectorReplay
    python host/tools/serial_replay.py --port COM7 --sets 'fp32,fp64' --limit 500 --progress
    python host/tools/serial_replay.py --port COM7 --sets 'fp32*,fp64*' --progress

### Arduino Nano

Same as the Uno with `--fqbn arduino:avr:nano`. A Nano with the older
bootloader needs `--fqbn arduino:avr:nano:cpu=atmega328old` to upload;
the compile is identical either way.

### The other two sketches

`Hello` first, on any board - it prints the ABI, the backend, the
formats and one fused multiply-add whose answer is known in advance,
and if that is right the toolchain and the profile are sound. `Bench`
prints elements a second per format and operation; leave a serial
monitor open at 115200.

    arduino-cli compile --fqbn <FQBN> --libraries bindings/arduino bindings/arduino/cft-arduino/examples/Hello
    arduino-cli upload  --fqbn <FQBN> -p COM7 bindings/arduino/cft-arduino/examples/Hello
    arduino-cli monitor -p COM7 --config baudrate=115200

### Rate, and how long a full replay takes

`--limit` and `--sets` exist because a board is not a host. The whole
census is 1,071,635 cases and every case is a round trip; at 115,200
baud the wire alone is about 1 ms for a `run` pair, so the ceiling is
roughly a thousand cases a second before the arithmetic. Start with a
few hundred cases of one set, then run the subset the board carries,
then leave the whole thing overnight.

    --sets 'fp32*'          globs over set names, comma-separated
    --limit 500             at most N cases per set
    --list-sets             what would run, with case counts
    --progress              a running count on stderr
    --timeout 30            seconds to wait for one answer

## Keeping the copy honest

An Arduino build compiles every source under a library's `src/` and
cannot reach outside the library directory, so the library **contains**
libcft: `bindings/arduino/cft-arduino/src/cft/` is a byte-identical
copy of `host/include` and `host/src`.

That copy is generated and checked, never made by hand:

    python bindings/arduino/sync.py            copy, rewrite vendor.json
    python bindings/arduino/sync.py --check    fail if the copy drifted

`vendor.json` records a sha256 per file. `--check` fails if a vendored
file differs from its source by one byte, if a source has appeared or
vanished upstream, or if a file has been left behind that no manifest
entry explains - which is the case that matters most, because a stale
file compiles, and compiles the old code.

The layout preserves `include/` and `src/` as siblings so that every
`#include "../include/cft.h"` resolves unchanged; nothing is rewritten,
which is what lets the copy be compared by hash. `src/cft.h` is a
three-line shim so a sketch can write `#include <cft.h>`.

Two directories under `src/` are not vendored and not audited by
`sync.py`: `src/remote/`, which belongs to the remote client for these
same boards, and the hand-written `src/cft_replay.[ch]`.

## What has been checked

At the commit this document ships with, on the Windows host (mingw64
gcc 16.1.0, Python 3.12.9):

- **The host gates are unchanged.** `make -C host test`: the API
  contract, the canonical-partition property, `cft-selftest` over
  `vectors/out` (168 sets, 1,071,635 cases, all matching), and the
  C/ctypes identity check. `make -C host remotetest` and `wstest` on
  the same tree. And the object-code comparison above.
- **Fifteen board compiles**, five FQBNs by three sketches, warnings
  on, zero warnings.
- **The loopback census, four profiles.** The full profile over all 168
  sets: 1,071,635 cases, all matching. The board profile (Pico, ESP32)
  over all 168: the same. `CFT_TINY` over the fp32 and fp64 sets: 24
  sets, 195,248 cases. `CFT_TINY` at fp128: 36 sets, 271,776 cases.
- **The negative control**: six corruptions, six caught.
- **pytest** `python/tests/test_serial_replay.py`: 20 tests over the
  frame, the checksum against its published check value, the refusals,
  the set-discovery order, and an end-to-end run against the loopback
  and against a loopback that lies.

`docs/VALIDATION.md` carries the run with every number.

## Pending on hardware

No board has been attached. Everything above that involves a board is a
COMPILE result; nothing here reports a board run, and the sizes are the
linker's rather than a measurement of a running part.

What is pending, and the command that settles each:

| pending | command |
|---|---|
| the ABI, backend and one fused multiply-add, per board | `Hello`, above |
| elements a second, per format and operation, per board | `Bench`, above |
| the fp32 and fp64 sets on an Uno and a Nano | `serial_replay.py --port COM7 --sets 'fp32*,fp64*'` |
| the same plus the reductions, augmented arithmetic and 9.6 on a Mega | the same command; the Mega carries the full verb set |
| all 168 sets on a Pico and an ESP32 | `serial_replay.py --port COM7 --progress` |
| the RAM a running part actually has free | `Hello` prints it |

Two things in particular are worth watching on the first board run,
because they are the places where a static analysis stops being enough:

**The stack margin on an ATmega328P is about 130 bytes** and it is a
sum of frames rather than a measurement of a running part. If it is
wrong, the symptom is corruption rather than a refusal. `Hello` prints
the free RAM; a `VectorReplay` that answers the first few hundred fp64
cases and then stops answering is the signature to look for, and
`VR_LINE` in the sketch is the knob.

**The heap on a Pico during a large `to_decimal`.** `chars.c` builds
the exact decimal in an arbitrary-precision natural it allocates, and
the sets reach 11,572 characters at binary128 and 32,768 at binary256
within the buffer. Nothing here has measured what that costs on a part
with 195 KB free. A case that cannot be allocated answers
`err internal` and is skipped by name, so the failure is visible rather
than silent - but the count of them is a number this document does not
yet have.

When a board is attached, `arduino-cli board list` must show a
recognised board on the port before anything is flashed to it.
