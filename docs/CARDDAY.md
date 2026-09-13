# Card day

The plan for the day the U50C goes in a slot. It is written down so
the day executes a script rather than improvises, and so the record it
produces is a census rather than a memory.

**The day was 2026-09-08, and this file is kept as the runbook that
was actually followed** - the steps below carry what each one printed,
and the checklist above them carries the four image pairs staged since.
The run itself is in docs/VALIDATION.md ("card day: first light, and
the published sets match on silicon", and the three pairs after it);
docs/BRINGUP.md carries the gate verdicts and docs/BENCHMARKS.md the
throughput. Read this file as the procedure and those as the record.

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

- [x] **THE READ-AHEAD PAIR: built 2026-09-09 morning from main 49a9a1b,
      both halves at 135 MHz, verified, staged and measured as each
      landed** (`~/cardday-ra`; docs/VALIDATION.md, the read-ahead
      pair's entry). Revision 3 plus the streaming engine's deeper
      read-ahead: 107 million beats a second a tile with the bus taken
      out, 1.8x the pair below, the same bits; it needs a host at ABI
      0.11 or later, which the box has. Use it for anything that
      needs the rate; its worst path is the sequencer's instruction
      memory now, and thin on four tiles.

- [x] **THE REVISION-3 PAIR: built overnight 2026-09-08 into 09-09 from
      main 99d2700, both halves at 135 MHz, verified, staged and run on
      the card as each landed** (`~/cardday-rev3`; docs/VALIDATION.md,
      the integrator's revision-3 entry). A 256-slot per-lane scratch
      with its per-run block, 16,384 instructions, a 512-entry bank,
      VERSION 0x800, CAPS feature nibble 1111 and CAPS2 - it needs a
      host at ABI 0.10, which the box has. Use it for anything that
      needs revision 3; the two pairs below stay as they were.

- [x] **THE REVISION-2 PAIR: 2026-09-08, from 9c086d3, both halves at
      135 MHz, verified, staged and run on the card the same afternoon**
      (`~/cardday-rev2`; docs/VALIDATION.md, that entry). Thirty-two
      registers a lane, 4,096 instructions, the per-run constant bank,
      VERSION 0x700, CAPS feature nibble 0111 - it needs a host at ABI
      0.9, which the box has. Use it for anything that needs revision
      2; the pair below stays the proven 0x600 pair.

- [x] **THE PAIR FOR THE DAY: 2026-09-07, from ed752dd, both halves
      at 135 MHz, verified and staged** (built on amd-arc-box the
      evening before card day). main as of that evening: IMUL and the
      indexed constants, CAPS publishing the sequencer's capacities and
      both features (so cft-zoom and cft-orbits size themselves and the
      imul cases replay instead of being skipped), the leading-zero
      cone as its own stage (LATENCY 16), ABI 0.8 - the hardware the
      library expects. The 9f73107 recipe: retiming + phys_opt, default
      directives. hw/verify-image.sh 8/8 on each; each staged copy
      re-hashed against its manifest's build-time sha256, byte-identical;
      the runner's `images` stage over both: PASS (run
      20260907-213830-ed752dd); `sha256sum -c SHA256SUMS` clean:

          ~/cardday-0907/cft_hw_single.xclbin   one tile,   kernel_wns +0.316  routed +0.055  136 min
          ~/cardday-0907/cft_hw_quad.xclbin     four tiles, kernel_wns +0.067  routed +0.031  267 min
          ~/cardday-0907/SHA256SUMS             (+ both manifests, README)

          single  3870fc4371e63b3390278442897c7d2b3c750d44646339768aa8ff42c0c981e0  35,783,663 bytes
          quad    496f8ac0881581f182b9d95d94b21933881cfd1783e8ea5d3e2fb340d1828307  51,422,147 bytes

      The quad closed with 0 failing endpoints of 984,222 and hold
      +0.009; its worst kernel path (+0.067) runs from the fp256 bank's
      read-delay register into a bank64 lane's s13_tiny, a cross-bank
      path the placer chose, where the 9f73107 quad had +0.143 on the
      LZC-plus-coarse-normalise path the cone stage since removed. The
      single's worst (+0.316, against +0.618 before) is the seedop
      bypass family out of the stream FIFO, 16 to 18 levels. The
      round's hardware cost margin on both halves and both still meet
      135 with room; 130 was not needed. Use this pair FIRST; the
      9f73107 pair in ~/cardday-tip is the fallback, and it lacks
      IMUL, kx and the published caps (the absences listed under step
      2 apply to it, not to this pair). The commits after ed752dd on
      main touch RTL this image does not elaborate (a multi-pass
      counter compare spelled for lint) and comments; `git diff
      ed752dd..HEAD -- rtl/ hw/` shows exactly that, and the manifests
      say `bitstream_sources: rtl/ and hw/ identical to ed752dd`.
      The library on the card host may be newer than the images: ABI
      0.9, the sequencer's revision 2 of 2026-09-08, still accepts
      VERSION 0x600 images and refuses by name any program that needs
      what they lack (thirty-two registers, the per-run bank), and the
      div/sqrt programs and every tool's kernel fit the old limits - so
      nothing on the day changes, and the revision-2 hardware gets its
      own pair after it.

- [x] **The PRIMARY pair until the 0907 pair lands: 135 MHz, staged
      and verified**
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
- [x] `sha256sum` of both xclbins recorded somewhere that is not the
      build box: the 0907 pair's hashes are in this file, above, and
      in docs/VALIDATION.md (2026-09-07 evening).
- [x] `make libcft-test` green on the machine that will host the card:
      amd-arc-box, main 6f100ff, 2026-09-07 18:14 - 1,071,635 cases,
      C and Python the same bits, 10 min, against sets the box
      generated itself (all 168 byte-identical to the desktop's after
      CR stripping). The box has no mpmath and cannot make a venv, so
      the desktop's mpmath 1.3.0 sits in ~/pylib with
      PYTHONPATH=$HOME/pylib; device-test and cft-bench are built there
      against /opt/xilinx/xrt.
- [ ] `bash hw/run-device-test.sh <quad hw_emu image> -q` green, so
      the multi-tile host path is known good before hardware is added
      as a variable. 2026-09-07 evening, on the desktop's WSL against
      a quad hw_emu image of ed752dd: the first run returned 0 after
      five minutes with NONE of device-test's own output and two
      protobuf parse errors at the first host-to-device copy - the
      driver's stale-emulation-state class, or a crash the runtime's
      handler turned into exit 0; not a pass. Not re-run: the single's
      own `-q -n 8` ran 221 min and was still inside fp32 (fma 22,
      sequencer programs 42, composed div/sqrt 50 checks, 0 failed)
      when it was stopped on the morning of card day, because quick
      mode is hundreds of invocations now and xsim charges one to
      three minutes each. The multi-tile host path IS proven another
      way: `-s -n 24` on the quad image passed 98 checks in all four
      formats overnight (docs/VALIDATION.md 2026-09-08). Step 2 with
      the single image and step 3's full matrix cover the rest on the
      card itself.
- [ ] `bash hw/run-device-test.sh <quad hw_emu image> -r` green. NOT
      a pre-day check after all: on 2026-09-07 the gate ran 133 min
      under xsim, about 95 single-element fp32 reductions each
      completing through the real XRT stack with err=000, and had not
      finished the first 16-case block, because every case splits
      into several one-element invocations at about 1.4 min each. The
      full gate is days of simulation; it was stopped, and the
      reductions are proven on the card at step 5 instead. What the
      run did establish: the four-tile image answers through XRT with
      contract 0x600, all four formats, and CAPS publishing 64
      deposits, 1,024 instructions, 256 constants and both feature
      bits, and the library refuses the over-size programs by name. The
      reduction path is the newest hardware and the only one where the
      element count is a real operand rather than a loop bound, so it
      is the one most worth having proven before the card is also a
      variable. NOTE: this needs an image at contract 0x500 or later -
      every emulation artifact built before 2026-08-30 reports 0x410
      and predates reductions entirely, so it will report the opcode
      group as absent rather than fail.
- [x] `xbutil examine` shows the card, and `Above 4G Decoding` is on
      in the host BIOS (BRINGUP.md gate 0). Done 2026-09-08: the card
      showed as the golden image first, was flashed to
      `xilinx_u50_gen3x16_xdma_base_5` (the base package needs
      `xilinx-cmc-u50` and `xilinx-sc-fw-u50` beside it; `xbmgmt` by
      its full path under sudo; cold boot), and both functions came
      up ready. The 4G setting is the Intel platform's "PCI 64-Bit
      Resource Allocation", enabled by default on this board and
      readable from efivarfs without touching the menu.

## The day, in order

Each step is a gate: if it fails, stop and diagnose rather than
continuing, because every later step assumes the earlier ones.

**1. The card is there.** `xbutil examine`, `xbutil validate`. (On
2026-09-08 `validate` died inside xrt-smi's device-info parser before
any test - "Mac address exceed IP4 maximum value" - a tool bug on this
card; steps 2 to 5 are the stronger check and ran instead.) Record
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

Every set staged before the 0907 pair predates 2026-09-07, and three
things landed in the library that day which such an image will show
as absences, all of them normal (docs/HOSTAPI.md, docs/SEQUENCER.md);
the 0907 pair carries all three, and on it none of this applies:

- **CAPS[27:16] reads zero**, so `cft_get_caps` reports the
  sequencer's capacities as unknown and enforces nothing against
  them. The tile still enforces its own 64 deposit slots a lane at
  the header, with STATUS[3] and no message - so a program that
  deposits once an iteration must be sized by hand on these images:
  `cft-zoom --steps-per-call 32`, `cft-orbits --periods 15` (at most
  15 samples a run). On an image that publishes its caps the tools
  do this themselves.
- **CAPS[4] and CAPS[28] read zero**: no indexed constants, no
  `IMUL`. `cft_program_load` refuses an image that uses either,
  naming the instruction, and `cft_supports` answers no for opcode
  30. `cft-enclose` probes and falls back to its chunked shape.
- **The published opcode sets carry 200 `imul` cases each** since
  the opcode was assigned. The replay skips them by name on a device
  that does not publish `IMUL` - one `imul skipped, not on this
  device` line per set, and the case count it prints excludes them -
  rather than failing the set. A run of `cft-selftest` on these
  images should therefore print twenty such lines and a smaller
  count than `make vectors` wrote; a `cft_run failed:
  unsupported` line instead is a library defect, not the card's.

**3. One tile is correct.**

    bash hw/run-device-test.sh ~/cardday-0907/cft_hw_single.xclbin -n 4096

(Run 2026-09-08: 2,258 checks, 0 failed at n=1120, 886 reductions
checks, 0 failed; the `-n 4096` form tripped the partition test's
own coverage check on the tree of the day and was fixed the same
afternoon - docs/VALIDATION.md.)

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

    ./host/cft-selftest vectors/out ~/cardday-0907/cft_hw_single.xclbin

(Run 2026-09-08: 168 sets, 1,071,635 cases, all matching, 584 s on
one tile and 587 s on four.)

Every published case replayed through the hardware (1,071,635 over
168 sets from `make vectors` at ABI 0.8, of which the 4,000 `imul`
cases are skipped by name on an image that predates the opcode; the
runner's own census draws larger pools and counts 1.2 million), each
one twice:
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

*Measured 2026-09-09, the morning after the revision-3 pair
(docs/BENCHMARKS.md, "The engine, measured"): 59 to 60 M beats a
second a tile at every format against the 108 predicted - 2.25
cycles a beat - and four tiles exactly four times one, byte-identical
to each other and to software. HBM is not the wall; the read path's
own latency is, and a deeper read-ahead is the RTL item that closes
the gap. The staged path through `cft_run` sits a further factor of
three below that, which is the bus.*

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
- **A program refused with STATUS[3] and no library message** is a
  cap the image did not publish - 64 deposit slots a lane on every
  staged image - so the library could not refuse it first. Size the
  program down (the flags above) rather than suspect the arithmetic.
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

## The build trees, and what is kept when they go

A staged pair holds the image, its manifest and `SHA256SUMS`. That is
enough to load an image and prove it is the one the manifest describes. It
is **not** enough to answer a question about the design, and the difference
cost a real answer on 2026-09-12: asked whether revision 4's broadcast mux
had created a new critical path, the only honest reply was that the
read-ahead pair's build tree had already been cleaned, so the comparison
could be made between *margins* and not between *paths*.

A build tree is 1-3 GB, almost all of it the `_x_hw` intermediate. The part
worth keeping is under a megabyte. So `~/cardday-forensics/<build dir>/`
holds, per build:

- the manifest, which carries commit, flags, both WNS figures and the
  image's sha256;
- the routed timing summary, gzipped - the whole report, for when the
  distillation is not enough;
- `*.worst.txt`, the distilled part: the kernel clock's row in the
  intra-clock table and the worst path inside that clock group, with source
  cell, destination cell, requirement, data path delay and logic levels.

13,415 MB of build tree reduced to 9 MB that way.

**The distillation names the KERNEL clock on purpose.** A routed timing
summary prints its clock groups in its own order, and the first `Max Delay
Paths` entry in the file belongs to whichever group came first - on these
U50 images `io_clk_freerun_00`, a shell clock sitting around +7.3 ns. The
design's margin is `clk_out1_ulp_clk_wiz_0`, named by the manifest's
`kernel_clock:` line. A reader who takes the first number in the file gets
a figure that is correct about the wrong clock, which is worse than no
figure; the first attempt at this archive made exactly that mistake and had
to be redone.

What the archive makes possible, as an example - the limiting path of every
single-tile build that closed:

| build | commit | kernel WNS | limiting path |
|---|---|---|---|
| `build-135s` | `39fc2c04` | +0.255 | `u_fifo_a/mem_reg_2` -> `g_lane32[6].u_fma/s0_byp_d_reg[7]` |
| `build-ms-single` | `b1a014cb` | +0.220 | `u_fifo_a/mem_reg_2` -> `g_lane32[5].u_fma/s0_byp_d_reg[14]` |
| `build-rev4-hw` | `f636cf39` | +0.210 | `u_fifo_a/mem_reg_0` -> `g_bank64.g_lane64[1].u_fma/s0_byp_d_reg[26]` |

One structural path - operand FIFO A's block RAM output into an FMA's
stage-0 bypass register, eighteen logic levels, mostly DSP - has limited
this design across three revisions. That is a useful thing to know before
optimising somewhere else, and it is not recoverable from a staged pair.

A failed build is evidence too: `build-seq135s` is preserved at **-0.286**,
limited by `u_seq/prec_q_reg[1]_rep__1_replica` -> `u_seq/wr_addr_reg[56]`,
which is a record of what the sequencer could not do at 135 MHz.

**Extract before reclaiming, as two separate runs.** A script that extracts
and deletes in one pass, and fails in the middle, has deleted something it
did not copy. Reclamation additionally refuses to run while any `v++` or
`vivado` is alive, since a live link owns its build directory, and skips any
build whose forensics are not already on disk.
