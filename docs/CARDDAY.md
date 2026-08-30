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

**One exception, and it is the newest thing here.** The reduction path
(`CFT_SUM`, `CFT_DOT`) is proven in cocotb, in the golden model and in
C, and as of this writing has not yet been exercised through a real
AXI stack even in emulation, because every emulation artifact built
before 2026-08-30 predates the opcode group. Until an emulation run at
contract 0x500 is green, treat reductions as bring-up work on the day
rather than as re-confirmation - which is why step 3 and step 5 below
call them out separately.

## Before the day

- [x] **Both images built, staged and verified** (2026-08-30). The
      card-day set is the 130 MHz pair - see the card-day clock section
      of BRINGUP.md for why, and for the one measurement that argues
      the other way. They are staged together on the build box:

          ~/cardday-130/cft_hw_single.xclbin    one tile,  53bbba7
          ~/cardday-130/cft_hw_quad.xclbin      four tiles, 53bbba7
          ~/cardday-130/SHA256SUMS
          ~/cardday-130/README

      Each was checked against the sha256 its own manifest recorded at
      build time, and again after the copy. Re-check on arrival with
      `sha256sum -c SHA256SUMS`; a manifest whose hash does not match
      its file is worse than no manifest, because it would be believed.
- [ ] If the manifest's commit is not HEAD - and it usually will not
      be, because a link takes two hours and work continues - check
      whether that matters rather than assuming it does. The manifest
      now answers this itself, in `bitstream_sources:`, which reports
      whether `rtl/` and `hw/` differ from the named commit rather than
      whether the whole tree does. That distinction is not academic:
      `quad145` was flagged `tree: DIRTY` for host-side files while its
      RTL was byte-identical to its commit. To check by hand:

          git diff <manifest commit>..HEAD -- rtl/ hw/

      An empty diff means the image is HEAD's hardware. So does a diff
      that touches only `synthesis translate_off` regions, since
      nothing inside one reaches the netlist. Rebuilding a good image
      because a documentation commit landed afterwards costs two hours
      and buys nothing.
- [ ] `sha256sum` of both xclbins recorded somewhere that is not the
      build box.
- [ ] `make libcft-test` green on the machine that will host the card.
- [ ] `bash hw/run-device-test.sh <quad hw_emu image> -q` green, so
      the multi-tile host path is known good before hardware is added
      as a variable.
- [ ] `bash hw/run-device-test.sh <quad hw_emu image> -r` green. The
      reduction path is the newest hardware and the only one where the
      element count is a real operand rather than a loop bound, so it
      is the one most worth having proven before the card is also a
      variable. NOTE: this needs an image at contract 0x500 or later -
      every emulation artifact built before 2026-08-30 reports 0x410
      and predates reductions entirely, so it will report the opcode
      group as absent rather than fail.
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
MAGIC is wrong, nothing after this matters.

VERSION is a narrower signal than it looks: it guards the REGISTER
MAP, not the feature set, so the host accepts a SET of known versions
and lets CAPS decide what the image can actually do. A version outside
that set means the host does not know how to talk to this image at
all; a known version with a CAPS bit clear means the image simply does
not carry that feature, which is a normal thing for an older
bitstream to say.

**3. One tile is correct.**

    bash hw/run-device-test.sh ~/cardday-130/cft_hw_single.xclbin -n 4096

Full matrix: every format, ten opcodes, five rounding attributes,
against the software backend, plus the boundary sizes. This is the
step that says the arithmetic in silicon is the arithmetic in the
golden model.

Reductions are part of that matrix and run automatically, but they are
worth being able to run alone when something goes wrong, because they
are the only path where the element count is an operand:

    bash hw/run-device-test.sh ~/cardday-130/cft_hw_single.xclbin -r

One tile means one canonical range and no fold, so a failure here is
the reduction datapath itself rather than the split.

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

    bash hw/run-device-test.sh ~/cardday-130/cft_hw_quad.xclbin -n 4096

Then the part that matters most: **run the same inputs through the
single-tile image and the quad image and compare the output buffers
byte for byte.** They must be identical. If they are not, the
determinism claim is false in the one way that would be hardest to
notice later.

Reductions carry the sharpest version of that test, and it is worth
doing explicitly rather than trusting the matrix:

    bash hw/run-device-test.sh ~/cardday-130/cft_hw_quad.xclbin -r

An elementwise op splits across tiles trivially - element i does not
care which tile computed it. A reduction does not: the array is cut
into canonical ranges, one per tile, and the partials are folded on
the host. That fold is only correct if the tree shape is right in two
places at once, so a quad reduction that disagrees with a single-tile
reduction is the partitioning, not the arithmetic.

**6. Throughput.** Now, and not before, measure. Beats per second per
tile, and the four-tile total.

The prediction has moved, so measure against the current one: the
engine now has one AXI master per stream rather than one shared port,
and simulates at **1.25 cycles per beat against the shared port's
~4.4**. That 3.5x is a simulation number against a cooperative memory
model, which is exactly the kind of number a real HBM controller is
entitled to disagree with - so the interesting question is not whether
1.25 survives, but where it lands and whether four tiles scale or HBM
is already the wall. That is the number deciding whether the sequencer
is urgent or merely desirable.

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
  `cft_last_error()` carries what XRT said, and STATUS says which of
  the three faults it was: [0] a read response was not OKAY, [1] a
  write response was not OKAY, [2] a read burst delivered the wrong
  number of beats.

  A **wrong beat count** (STATUS bit 2) is worth separating from the
  other two. The other two are the memory refusing an address; this
  one is the memory breaking the AXI protocol, which on a working
  interconnect should not happen at all and points at the shell, the
  pseudo-channel mapping in `link.cfg`, or a pointer that made a burst
  cross a 4KB boundary.
- **A hang should no longer be how a bus fault presents.** It used to
  be: a short read burst starves compute, so the engine latched the
  error and never completed, and the host's timeout was the only
  recourse. Since 2026-08-30 a length error ENDS the run - the engine
  stops issuing new bursts, finishes any write burst it had already
  committed, lets outstanding reads land, and asserts `ap_done` with
  STATUS non-zero. So a length fault now arrives as a prompt
  `CFT_ERR_BUS_FAULT` rather than a twenty-minute wait.

  A genuine `CFT_ERR_TIMEOUT` therefore means something the engine
  cannot see: a slave that stopped answering entirely, sending neither
  the remaining beats nor `RLAST`. Nothing in the kernel can tell that
  from a slow slave, which is why the timeout still exists. Read the
  STATUS bits the timeout path now reports alongside it - clean STATUS
  with a timeout is a stalled interconnect, not a kernel bug.
