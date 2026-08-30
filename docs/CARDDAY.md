# Card day

The plan for the day the U50C goes in a slot. It is written down so
the day executes a script rather than improvises, and so the record it
produces is a census rather than a memory.

The premise: **almost nothing here should be new on the day.** Both
images are built and hashed beforehand, the host library is written and
has already driven a four-tile image under emulation, and the vectors
have existed since before the hardware did. What genuinely cannot be
known until there is silicon is a short list, and the day is about
that list and nothing else.

## What can only be learned on the card

| unknown | why simulation cannot answer it |
|---|---|
| Does it work in real silicon at all | timing closure is a prediction until it is a measurement |
| Real HBM latency and bandwidth | the emulation models are explicitly approximate, and say so |
| Sustained throughput, and where the wall is | the shared-port bound is calculated, not measured |
| The XRT driver stack against a real device | emulation replaces exactly the layer under test |
| Thermals and long-run stability | no model |
| **Determinism across devices** | the claim needs a second machine to mean anything |

Everything else - correctness, flags, partitioning, the ABI, the
opcode set, the rounding attributes - is already checked and should
merely be re-confirmed.

## Before the day

- [ ] Both images built and their manifests kept: `cardday/single/`
      and `cardday/quad/`, each with `cft_hw.manifest.txt` naming the
      commit, the tree state, the clock and the routed WNS. An image
      whose manifest says `tree: DIRTY` does not go on the card.
- [ ] `sha256sum` of both xclbins recorded somewhere that is not the
      build box.
- [ ] `make libcft-test` green on the machine that will host the card.
- [ ] `bash hw/run-device-test.sh <quad hw_emu image> -q` green, so
      the multi-tile host path is known good before hardware is added
      as a variable.
- [ ] `xbutil examine` shows the card, and `Above 4G Decoding` is on
      in the host BIOS (BRINGUP.md gate 0).

## The day, in order

Each step is a gate: if it fails, stop and diagnose rather than
continuing, because every later step assumes the earlier ones.

**1. The card is there.** `xbutil examine`, `xbutil validate`. Record
the shell version, the XRT version and the device BDF.

**2. The image loads.** `cft-selftest` cannot do this (it opens the
software backend), so use `device-test` with the single-tile image and
`-q -n 8`. The first thing it prints is the tile count, the contract
version and the format mask read from the card's own registers. If
MAGIC or VERSION is wrong, nothing after this matters.

**3. One tile is correct.**

    bash hw/run-device-test.sh cardday/single/cft_hw.xclbin -n 4096

Full matrix: every format, ten opcodes, five rounding attributes,
against the software backend, plus the boundary sizes. This is the
step that says the arithmetic in silicon is the arithmetic in the
golden model.

**4. The conformance vectors, on the card.**

    ./host/cft-selftest vectors/out cardday/single/cft_hw.xclbin

228,000 published cases replayed through the hardware, each one twice:
element at a time for exact flags, then as arrays. This is the claim
the project is for, so it is the run whose output gets kept.

Every case is a separate kernel launch in the element pass, so budget
for launch overhead rather than arithmetic - on the order of tens of
seconds, not minutes. If it is much slower than that, something is
wrong with the driver path rather than with the tile.

**5. Four tiles are correct, and identical to one.**

    bash hw/run-device-test.sh cardday/quad/cft_hw.xclbin -n 4096

Then the part that matters most: **run the same inputs through the
single-tile image and the quad image and compare the output buffers
byte for byte.** They must be identical. If they are not, the
determinism claim is false in the one way that would be hardest to
notice later.

**6. Throughput.** Now, and not before, measure. Beats per second per
tile, and the four-tile total. The prediction is a shared-port bound
of about 4.4 cycles per beat; the interesting question is whether four
tiles scale or whether HBM is already the wall - which is the number
that decides whether the sequencer is urgent or merely desirable.

**7. Soak.** The same run, repeated, for as long as the day allows.
Every repetition must produce the identical checksum. A determinism
claim that holds for one run and not for a thousand is not a
determinism claim.

## What to record

The manifest format already exists; the run record should match it in
spirit - enough to replay, not enough to be a chore.

- host, OS, XRT version, shell version, card serial
- xclbin sha256 (not its filename)
- the commit, from the manifest
- for each step: the command, the exit status, and the checksum or
  case count it printed
- `xbutil examine` before and after the soak, for thermals

## If it fails

- **Timing-related misbehaviour** looks like intermittent wrong
  results that vary run to run. The single most useful response is to
  rebuild at a lower clock: determinism is clock-independent by
  construction, so a slower image that is right is a complete answer
  to the question the day is asking.
- **All-zero output with clean flags** means a precision the bitstream
  does not carry. Check the format mask `device-test` printed in step
  2 against what is being issued.
- **A bus fault** (`CFT_ERR_BUS_FAULT`) means the memory system did not
  vouch for the data - a bad pointer or alignment, not arithmetic.
  `cft_last_error()` carries what XRT said.
- **A hang** is most likely a short or long read burst; the engine
  records it in `err_acc` and then never completes, which is why the
  library has a timeout. `CFT_ERR_TIMEOUT` plus the STATUS bits is the
  diagnosis.
