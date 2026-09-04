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

**One near-exception, now retired.** The reduction path (`CFT_SUM`,
`CFT_DOT`) was the newest thing here, and this paragraph used to say
it had never been exercised through a real AXI stack. That is no
longer true: on 2026-08-30 hw_emu at contract 0x500 ran reductions
green on a single tile (64 checks, 0 failed) and on the quad -
including the five-ranges-across-four-tiles case (n=33) that
validates the wave-staging fix, the one bug class that only appears
with more canonical ranges than tiles. Steps 3 and 5 still call
reductions out separately, because they remain the only path where
the element count is an operand rather than a loop bound.

## Before the day

- [x] **DECISION 2026-09-01: the card-day clock is 135 MHz, both
      geometries - EXECUTED the same day.** The measured ceilings are
      ~148 single / ~139 quad (docs/VALIDATION.md, the bracket
      entry), so 135 carries real margin on both instead of the
      quad's nine-picosecond squeak at 130. High-speed testing (145+)
      stays deliberately deferred past first light.

- [x] **The PRIMARY pair: 135 MHz, staged and verified**
      (2026-09-01). Built at 39fc2c0, whose rtl/ and hw/ are
      byte-identical to the b1a014c general-purpose tree (the only
      diff is a soak script that never reaches a netlist) - seed
      opcodes (CAPS bit 14), one HBM pseudo-channel per master,
      reductions at 0x500, the bus-fault abort. hw/verify-image.sh
      8/8 on both; staged copies re-hashed against the manifests'
      build-time sha256, byte-identical:

          ~/cardday-135/cft_hw_single.xclbin   kernel_wns +0.255
          ~/cardday-135/cft_hw_quad.xclbin     kernel_wns +0.042
          ~/cardday-135/SHA256SUMS             (+ both manifests)

      Note the quad's margin: +0.042 ns at 135 against +0.009 at
      130 - the router given a realistic target closed HIGHER with
      MORE slack, which is the met-target-slack lesson from the
      ceiling bracket paying out in the right direction.

      The STATUS[3] precision-refusal and the sequencer post-date
      these images and are in main only.

      So does the sequencer's bank fix (40149b1, 2026-09-02): an image
      built between the sequencer's arrival and that commit fails
      every program on a banked device - all three operand reads left
      through one master bound to one HBM pseudo-channel. The staged
      135 and 130 pairs predate the sequencer entirely and are not
      affected. Candidates from the tip - seed ROM as case tables, the
      round stage precomputed - are building as quads at 135 on both
      hosts with 130 queued behind; a case-ROM single is routing.
      Whichever closes goes through hw/verify-image.sh and SHA256SUMS
      before it is called a pair, exactly as above.

      The single half is staged (2026-09-02, evening): built at
      0e7264e, 135 MHz, retimed, kernel WNS **+0.433** (where the
      same clock had +0.045 before the case-table ROM), verify-image
      8/8, copied and re-hashed against the manifest's build-time
      sha256, byte-identical:

          ~/cardday-tip/cft_hw_single.xclbin    kernel_wns +0.433
          ~/cardday-tip/SHA256SUMS              (+ manifest, README)
          sha256 6e6d878d129c746902ddb1a6f6df0067eecd6fb87f8c1c2b1828a894020d401c

      It carries the sequencer's bank fix and the seed ROM as case
      tables, not the round-stage precompute (9f73107). Its quad is
      the open half: the tip quads at 135 on both hosts, 130 behind.

      The quad half closed the same evening (2026-09-02, 19:13): 9f73107,
      135 MHz, retiming + phys_opt, routed WNS +0.018 with 0 failing
      endpoints, kernel WNS **+0.143**, verify-image 8/8, re-hashed
      against its manifest after the copy, byte-identical:

          ~/cardday-tip/cft_hw_quad.xclbin      kernel_wns +0.143
          ~/cardday-tip/SHA256SUMS              (single + quad + manifests)
          ~/cardday-tip/REPRODUCED.txt          (the second host's copy, hashed)
          sha256 fef73969f505960908e92dd29521f4ef4783745499cd70f20aacf33ab49d1a55

      The box rebuilt the same image independently (2026-09-02, 19:39):
      sha256 86ef3739...b5e7d, 51,286,329 bytes, verify-image 8/8; its
      BITSTREAM section is byte-identical to the staged copy's after the
      .bit header's three timestamp bytes. Either copy is the quad;
      REPRODUCED.txt records both hashes and the section hash.

      The single half followed from the same tree (2026-09-02, 20:48,
      the desktop's WSL, 1h32m): 9f73107, 135 MHz, retiming + phys_opt,
      routed WNS +0.055 with 0 failing endpoints of 572,783, kernel WNS
      **+0.618** (worst path the seedop bypass into s0_byp_d, 15 logic
      levels), verify-image 8/8, re-hashed after the copy:

          ~/cardday-tip/cft_hw_single.xclbin    kernel_wns +0.618
          sha256 afc483e2e78e09f870c0a1f95d270d7959b068f78e030b67950d0c70092dfda4

      It replaces the 0e7264e single (kernel +0.433), kept beside it in
      prev-0e7264e/; SHA256SUMS covers the pair and both manifests. The
      pair is one tree, and the first pair with the sequencer in both
      halves.

      FIRST fallback: the 130 MHz general-purpose pair at b1a014c in
      `~/cardday-ms` (single +0.220, quad +0.009, verified 8/8),
      identical hardware one notch slower.

      SECOND fallback: the 130 MHz pair at bac9f550 - one AXI master
      per stream, reductions at VERSION 0x500, the bus-fault abort,
      both closed with hbm_aclk clean at 450.0:

          ~/cardday-130b/cft_hw_single.xclbin   one tile,   kernel_wns +0.271
          ~/cardday-130b/cft_hw_quad.xclbin     four tiles, kernel_wns +0.019
          ~/cardday-130b/SHA256SUMS             (+ both manifests, README)

      The 53bbba7 pair stays in ~/cardday-130 as the THIRD fallback - shared
      port, no reductions, but the configuration hw_emu validated
      longest. If the new pair misbehaves on silicon, fall back and the
      day still produces first light. Neither set carries the shared
      shifter ladders or the BRAM FIFOs (2026-08-31 work, in-shell
      unproven); the single-channel link.cfg also postdates both.

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

    bash hw/run-device-test.sh ~/cardday-135/cft_hw_single.xclbin -n 4096

Full matrix: every format, ten opcodes, five rounding attributes,
against the software backend, plus the boundary sizes. This is the
step that says the arithmetic in silicon is the arithmetic in the
golden model.

Reductions are part of that matrix and run automatically, but they are
worth being able to run alone when something goes wrong, because they
are the only path where the element count is an operand:

    bash hw/run-device-test.sh ~/cardday-135/cft_hw_single.xclbin -r

One tile means one canonical range and no fold, so a failure here is
the reduction datapath itself rather than the split.

**4. The conformance vectors, on the card.**

    ./host/cft-selftest vectors/out cardday/single/cft_hw.xclbin

Every published case replayed through the hardware (1,223,635 over 168
sets at the 0.7 census; the count grows with the contract), each one
twice:
element at a time for exact flags, then as arrays (the sets were
regenerated when the seed opcodes joined the contract - regenerate
locally with `make vectors` before the day so the card replays the
current sets). This is the claim the project is for, so it is the
run whose output gets kept. Follow it with the composed divide and
square root - `bash hw/run-device-test.sh <image> -q` includes them -
because on silicon the ~30-invocation sequence costs microseconds,
and that run completes the general-purpose story emulation priced in
days.

Every case is a separate kernel launch in the element pass, so budget
for launch overhead rather than arithmetic - on the order of tens of
seconds, not minutes. If it is much slower than that, something is
wrong with the driver path rather than with the tile.

**5. Four tiles are correct, and identical to one.**

    bash hw/run-device-test.sh ~/cardday-135/cft_hw_quad.xclbin -n 4096

Then the part that matters most: **run the same inputs through the
single-tile image and the quad image and compare the output buffers
byte for byte.** They must be identical. If they are not, the
determinism claim is false in the one way that would be hardest to
notice later.

Reductions carry the sharpest version of that test, and it is worth
doing explicitly rather than trusting the matrix:

    bash hw/run-device-test.sh ~/cardday-135/cft_hw_quad.xclbin -r

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
