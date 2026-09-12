# cft for Arduino

Deterministic IEEE 754-2019 binary32, binary64, binary128 and
binary256 arithmetic on a microcontroller, producing **the same bits**
as the host library, as the golden model in `python/cft_golden`, and
as the FPGA tile.

Not "the same to within an ulp". The same encoding and the same five
exception flags, for every operation, under every one of the five
rounding attributes. That claim is checkable and this library ships the
means to check it on your own board: see *Replaying the vectors*.

---

## Why this runs on a part with no FPU

libcft does not use floating-point hardware, and there is nothing to
port: the arithmetic is integer code over 32-bit limbs with 64-bit
intermediates, and the API boundary is byte-level little-endian
interchange encodings. A Cortex-M0+ with no FPU, an Xtensa with one it
never touches, and an 8-bit AVR with neither run the same source and
reach the same answer. The only thing that differs between parts is how
MUCH of the library fits, which is what the table below is about.

The cost is speed. This is software arithmetic on a microcontroller;
the `Bench` example measures it on your board and prints elements a
second. Use it where the answer has to be reproducible - a sensor whose
readings are checked against a host, a controller whose behaviour has
to be replayable, a device that must agree with a GPU or an FPGA - and
not where you want throughput.

## Installing

Copy the `cft-arduino` directory into your Arduino `libraries/` folder,
or point `arduino-cli` at its parent:

    arduino-cli compile --fqbn arduino:avr:uno \
        --libraries path/to/cft-fp256/bindings/arduino \
        path/to/cft-fp256/bindings/arduino/cft-arduino/examples/Hello

Then in a sketch:

```cpp
#include <cft.h>

cft_device *dev;

void setup() {
    Serial.begin(115200);
    cft_open(NULL, 0, &dev);          /* the software backend */

    /* fma(1 + 2^-52, 1 + 2^-52, -1) in binary64, little-endian */
    const uint8_t a[8] = {1,0,0,0,0,0,0xf0,0x3f};
    const uint8_t c[8] = {0,0,0,0,0,0,0xf0,0xbf};
    uint8_t d[8];
    uint32_t flags = 0;

    cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, a, a, c, d, 1, &flags, NULL);
    /* d is 0x3cc0000000000000 and flags is CFT_FLAG_INEXACT, on every
     * part, on every host, and on the card. */
}
```

Operands and results are **little-endian interchange encodings**, not
`float` or `double`: byte 0 is the least significant. That is the whole
of the ABI, and it is why the same buffer means the same number on a
part with a different word size.

`host/include/cft.h` is the reference for everything in the API; it is
the same header, vendored here (see *Where the code comes from*).

---

## What fits on which board

Measured, with `arduino-cli compile --warnings all`, at the commit this
README ships with. `docs/EMBEDDED.md` in the repository carries the full
table and the reasoning; this is the summary.

| board | flash | RAM | formats | what the library carries |
|---|---|---|---|---|
| Raspberry Pi Pico (RP2040) | 2 MB | 264 KB | fp32 fp64 fp128 fp256 | everything: the elementwise opcodes, divide and square root, the reductions and scaled products, the clause-5 completion set, augmented arithmetic, 9.6's magnitude forms, the formatOf arithmetic, the 5.12 character conversions, the sequencer, and all 39 correctly rounded transcendentals |
| ESP32 dev module | 4 MB | 520 KB | fp32 fp64 fp128 fp256 | the same |
| Arduino Mega (ATmega2560) | 256 KB | 8 KB | fp32 fp64 | elementwise, divide/sqrt, reductions and scaled products, clause 5, augmented arithmetic, 9.6 |
| Arduino Uno, Nano (ATmega328P) | 32 KB | 2 KB | fp32 fp64 | the same list; the replay sketch carries the elementwise verb only, because all of them plus a serial protocol do not fit in 32 KB |

Two things are absent on AVR and the reasons are numbers rather than
taste:

**binary128 and binary256 need a 32-bit `int`.** An unpacked
significand's exponent runs down to `emin - (p-1)`, and a multiply adds
two of them: -32,988 for binary128 and -524,756 for binary256, against
an `int16_t`'s -32,768. `cft_config.h` refuses the combination at
compile time with that number in the message. binary64's worst is
-2,148, fifteen times inside the range.

**The transcendentals need 117 KB of constant table.** The
trigonometric argument reduction reads a window of 2/pi from
`mp_2opi.h`, and on AVR every `const` object is copied into RAM at
startup. 117 KB into 8 KB is not a tuning problem.

## The examples

The three that compute ON the board, and are what
`bindings/arduino/verify.sh` compiles for every FQBN:

- **Hello** - what the board is, and one fused multiply-add whose
  answer is known in advance. Flash this first.
- **VectorReplay** - answers `host/tools/serial_replay.py` over the
  UART so the published conformance vectors can be replayed through the
  board. See below.
- **Bench** - elements a second for add, multiply and fused
  multiply-add at every format the build carries.

And three that make the board a CLIENT of a tile elsewhere, over the
frame protocol of docs/REMOTE.md rather than CSRP/1 - **RemoteSerialFma**,
**RemoteWiFiFma** and **RemoteReplay**. They belong to `src/remote/`
and are compiled by `src/remote/test/compile_check.py`, not by the
loop above.

## Replaying the vectors

The repository publishes 168 conformance vector sets, 1,068,915 cases:
every operation, every format, every rounding attribute, each with the
expected encoding and the expected exception flags. On a host,
`cft-selftest` replays them by opening the files. A microcontroller has
no files, so the sets stay on the host and the cases travel:

    arduino-cli compile --fqbn arduino:avr:uno --libraries bindings/arduino \
        bindings/arduino/cft-arduino/examples/VectorReplay
    arduino-cli upload  --fqbn arduino:avr:uno -p COM7 \
        bindings/arduino/cft-arduino/examples/VectorReplay

    python host/tools/serial_replay.py --port COM7 --sets 'fp32*' --limit 200
    python host/tools/serial_replay.py --port COM7            # all of it

The host reads the JSONL exactly as `host/src/conformance.c` does,
sends each case, and compares what comes back **bit for bit**. A case
the board cannot be asked - a format it does not carry, an operation
this build left out, a decimal sequence longer than its buffer - is
skipped BY NAME and counted, never scored as a pass.

The protocol is CSRP/1 and it is documented in `src/cft_replay.h`: hex
fields, a sequence number, a CRC-16 on every line, a per-case timeout.
`src/cft_replay.c` is the device half, and it is the same C the host's
`bindings/arduino/loopback` runs - which is how the harness gets tested
against the whole census, and against a loopback that answers wrongly
on purpose, before any board is plugged in.

## Where the code comes from

`src/cft/` is a **generated copy** of `host/include` and `host/src`.
Not a fork and not a port: byte-identical files, with
`bindings/arduino/vendor.json` recording a sha256 for each and
`bindings/arduino/sync.py --check` failing if any of them drifts. That
copy exists only because an Arduino build cannot compile sources
outside a library directory.

`src/cft.h`, `src/cft_replay.[ch]`, `library.properties`,
`keywords.txt`, this README and the examples are written here rather
than copied. The first six are listed in `vendor.json` under `owned`;
the examples and `src/remote/` are simply outside the subtree
`sync.py` audits.

Do not edit anything under `src/cft/`. Edit `host/` and run:

    python bindings/arduino/sync.py

## License

Apache-2.0. See `LICENSE` at the repository root: https://github.com/loganw234/cft-fp256.
