# Card day

The plan for the day the U50C goes in a slot. It is written down so
the day executes a script rather than improvises, and so the record it
produces is a census rather than a memory.

**The day was 2026-09-08, and this file is kept as the runbook that was
actually followed** - the steps below carry what most of them printed,
and the checklist above them carries the six image pairs staged since.
The run itself is in docs/VALIDATION.md ("card day: first light, and the
published sets match on silicon", and the five pairs after it);
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

- [x] **THE ROUND-2 PAIR: the single built 2026-09-15 from main
      5b7aa19 at 135 MHz and run on the card the same night; the quad
      closed on the second implementation, 2026-09-16, and ran its
      four-tile legs within two minutes of staging** (`~/cardday-round2`;
      docs/VALIDATION.md, "round 2's card day, second half" and the
      2026-09-16 entries). Sequencer revision 6 - an input block fetched
      through an index table, a per-run lane mask, the beat-wide
      reduction accumulator - VERSION 0xA00, CAPS2[9] and [10], and it
      needs a host at ABI 0.14. Single: kernel margin +0.266 ns, routed
      +0.032. Quad: +0.040 kernel, +0.031 routed, with
      `PLACE_DIRECTIVE=ExtraTimingOpt ROUTE_DIRECTIVE=AggressiveExplore`
      after the default-directive quad missed by 0.363 ns on the
      engine's oldest path (359 minutes wasted, 468 spent well; the
      README in the staging directory says which half used what). The
      single's first gate on the card failed and the RTL was not the
      reason: two host defects (a masked run's stale device copy;
      page-granular buffer capacities), fixed the same night with no
      rebuild. A quad that misses 135 MHz rebuilds at 130 on Logan's
      word (2026-09-16); this one did not need it.

- [x] **THE REVISION-4 PAIR: built 2026-09-12 into 09-13 from main
      f636cf3, both halves at 135 MHz, verified, staged and exercised on
      the card** (`~/cardday-rev4`; docs/VALIDATION.md, 2026-09-13).
      The read-ahead pair plus two capability bits and the guard that
      came with the second: CAPS2[6] SCRATCH_STRICT, so an indexed
      scratch access at or past SCRATCH_D is REPORTED in STATUS[5]
      rather than reduced modulo the depth; CAPS2[7] SCALAR, so
      MODE[18:16] make a, b or c stride-0 and the engine reads ONE BEAT
      instead of n; and a refusal on any non-zero bit in MODE[31:19].
      VERSION stays 0x800 - both bits live inside registers that already
      existed - and it needs a host at ABI 0.12 for cft_run_ex, while
      0.11 and earlier drive everything else on it. **Its quad is the
      thinnest margin in the lineage at +0.022 ns**, met with zero
      failing endpoints of 519,061; the single is +0.210. An image using
      neither flag computes exactly what revision 3 computed, so the
      pair is a superset rather than a different answer. 12,296 checks
      on the card, 0 failed.

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
      library expects. The 9f73107 recipe: RETIMING=1 + phys_opt, default
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
      0e7264e, 135 MHz, `RETIMING=1` (which retimed nothing:
      docs/VALIDATION.md, 2026-10-12), kernel WNS **+0.433** (where the
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
      135 MHz, RETIMING=1 + phys_opt, routed WNS +0.018 with 0 failing
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
      the desktop's WSL, 1h32m): 9f73107, 135 MHz, RETIMING=1 + phys_opt,
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

**2. The image loads.** Use `device-test` with the single-tile image and
`-q -n 8`. The first thing it prints is the tile count, the contract
version and the format mask read from the card's own registers. If
MAGIC is wrong, nothing after this matters.

This step used to justify that with "`cft-selftest` cannot do this (it
opens the software backend)", which was wrong, and wrong in this
document alone: the tool takes `[vector-directory] [artifact.xclbin]`,
its own header names this file as the run it keeps, and **step 4 below
invokes it against an image**. The real reason it is not the tool for
step 2 is cost, not capability - it replays the published sets, about
ten minutes an image (docs/VERIFICATION.md), where step 2 wants the
register identity in a second and wants it before spending anything.

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

    bash hw/run-device-test.sh ~/cardday-0907/cft_hw_single.xclbin -r

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

Every case is a separate kernel launch in the element pass, so budget for
launch overhead rather than arithmetic - on the order of ten minutes an
image (584 s on 2026-09-08). If it is much slower than that, something is
wrong with the driver path rather than with the tile.

**5. Four tiles are correct, and identical to one.**

    bash hw/run-device-test.sh ~/cardday-0907/cft_hw_quad.xclbin -n 4096

Then the part that matters most: **run the same inputs through the
single-tile image and the quad image and compare the output buffers
byte for byte.** They must be identical. If they are not, the
determinism claim is false in the one way that would be hardest to
notice later.

Reductions carry the sharpest version of that test, and it is worth
doing explicitly rather than trusting the matrix:

    bash hw/run-device-test.sh ~/cardday-0907/cft_hw_quad.xclbin -r

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

## Round 2's additions to the day (2026-09-15)

The round that built the gather, the composed elementwise gather, the
lane mask and the beat-wide accumulator (docs/ROUND2.md) left these for
the card, each a claim a host cannot hold. The image is the round's
merged main at 135 MHz (`KERNEL_FREQ=135000000`, never the script's
default), built once at the end of wave 2.

- **`device-test` with the new legs**, both `-b` and not: the indexed
  program leg's third assertion (`compare_buffers_indexed`) fires only
  where the device reports resident buffers - on the software backend
  it is not counted - and says whether the second run BOUND the table
  rather than staging it again. The first run of that leg on a card is
  the first time that assertion has counted.
- **`host/tools/gathertime.py` at the gravity shape**: one HBM round
  trip a gathered element is the model's prediction (the read side
  keeps one burst in flight); the number goes into docs/ROADMAP.md's
  ask 1 and 4 entries and docs/SEQUENCER.md R16.
- **The composed elementwise run's `bus_out` and STATUS word.** On a
  device the composed route returns `cft_program_run_ex`'s STATUS where
  a dense elementwise run returns the engine's; both are zero on a
  host, so no gate compares them (V2). Run an indexed `cft_run_ex` and
  its dense twin on the tile and compare the words.
- **P3's half-masked probe** (`tb/probe_seq_cycles.py`'s masked rows
  have the model-memory numbers: dense plus four cycles and one read a
  block, all-masked equal to half-masked): on the card the extra read
  is one HBM round trip a block. Measure dense, half-masked and
  all-masked at each format; the mask buys bytes, flags and the early
  exit, never compute, and the card's number is the one docs/ROADMAP.md's
  ask 5 entry wants.
- **P4's segmented timing against the seq6 entry's table**
  (docs/SEQUENCER.md "What it measures"): fp32 `CFT_SUM` 11.3147 -> 1.4152
  cycles a beat marginal on the model; the per-segment flush (~100
  cycles) dominates a short segment, so measure `cft_reduce_seg` at the
  requester's segment lengths as well as whole-array sums.
- **The area column.** V3 measured the mask's logic at +59% of
  `cft_seq`'s own cells after a full yosys pass (before P3's rewrite of
  the block slice); the image's utilisation and WNS say what it cost
  in the shell, and that goes beside the cycle numbers.
- **The under-promising word**: a remote handle publishes its server's
  CAPS2[9] and [10] while both routes are the client's (docs/REMOTE.md);
  a card-backed `cft-serve` fronting a tile without a feature is the
  first place that sentence is reachable.

### Owed to the next card day (added 2026-09-18, after atlas-engine's handoff)

*Paid the same day, 09:11 to 09:16, on Logan's word that the card was
free - every item but the last, and every one as predicted
(docs/VALIDATION.md, "the card half"). Left as written, because the
list is also the recipe: `~/box_handoff_cardcheck.sh <commit>` on the
box runs it.*

Two host defects found on the card by a workload from outside this
project were fixed on 2026-09-18 without a card: the XRT backend is
compiled on the box and the tests run on the software backend, and the
patches themselves were verified on both images by atlas-engine before
they were handed over. What only a card can still say:

- **`device-test -q -n 8` on both round-2 images with the two new
  legs**: the scratch leg's section 2b (an index past the depth under
  `SCRATCH_STRICT`: +0, no store, and STATUS carrying bit 5 - the word
  the XRT backend used to drop) and the program run of 32,768 and
  32,769 lanes with no mask. Expect the round-2 count plus the legs'.
- **The second leg's negative control, which exists only on XRT**: with
  the mask buffer's sizing put back to one beat and `stage_mask`'s
  check left in, the leg must FAIL by name ("a sizing defect in this
  backend") and the process must exit cleanly - a named failure of one
  run where there used to be a corrupted heap. Then restored, green.
- **atlas-engine's program set with the STOCK runner**:
  `python3 run_set.py --runner host/positive-run --device <image>` from
  the handoff's `program-set/`; 140 of 140 on both images, where the
  patched runner and the unpatched library gave 139.
  - On a revision-7 image, whose scratch is 2,048 slots, the same set
    gives **138 of 140, by design**. The two exceptions are `r8-modulo`
    and `r8-strict`, which index slot 256 and beyond. A 256-slot tile
    wraps an index from 256 up or reports it; a 2,048-slot tile does
    that only from 2,048 up.
  - Their expectations were made at 256 slots. On the card each equals
    the software backend opened at the device's depth (`positive-run
    --scratch-depth 2048`), byte for byte, and the same runner gives
    140 of 140 on a round-2 image (docs/VALIDATION.md, 2026-09-29).
- **The photograph through MAIN's library**:
  `python3 host/tests/photograph_check.py --device <image>` on both
  images. atlas-engine's card run matched the GPU on every pass with
  their own patched library; main's fix is the same sizing change, and
  a pass is 1,048,576 lanes - thirty-two times past the boundary the
  old mask buffer overran - so this is also the fix at scale.
- **The reductions' overlap**, still first in docs/ROADMAP.md's debts.
  *Paid too, later the same morning: it was never the tiles. Found by
  reading, proved in a scratch build, fixed and re-measured
  (docs/VALIDATION.md, "the reductions' missing rate" and "the
  reductions' fix").*

### What the card said (2026-09-15, the round-2 single tile; docs/VALIDATION.md has the whole day)

- **The new legs**: green on both images once the tests were right
  for an older image (1ee9189) - and on the round-2 image only after
  TWO host defects the card found, neither in the RTL: a masked run's
  staged deposit window came back holding the previous run's output
  (the tile strobes a masked lane off; the device copy was never the
  caller's - be1ac1f/db085ab stage it first), and buffer-object
  capacities above ~300 lanes corrupted the heap (page-granular
  behaviour behind a beat-granular capacity - d40ad23). device-test
  -n 8 / 336 / 1000 / 4097: 2,248 checks, 0 failed; -b: 729, 0, the
  resident-binds assertion counting for the first time.
- **gathertime at the gravity shape**: 310-340 ns a gathered element
  at every format - one HBM round trip, as R16 predicted; 128 bodies
  fp64 one run 15.6 ms against 127 calls at 26.7 ms (x1.71, the host
  gathers removed as well).
- **The composed route's STATUS word**: compared with the dense run's
  in `compare_indexed_elem` (ce01e41) - equal on the card.
- **The mask's cost**: x1.013 of the unmasked run at 384 lanes, every
  format - one beat read a block and no compute saved, as R17 said.
- **P4's segmented timing**: fp64 E = 1000 x L = 192 sum 2,351 us in
  one call against 91,108 us in a thousand; fp32 1,739 us; fp128
  3,863 us; the whole-array flush dominates below E = 64 (220 us).
- **The area column**: kernel WNS +0.266 ns at 135 MHz for the single
  tile; the quad's is its own entry.
- **The instruments that tell a host defect from a tile defect**, added
  from 2026-09-18 to 2026-09-28
  - `CFT_XRT_REDUCE_BC` (2026-09-18): what the XRT reduction paths do
    with the `b` and `c` buffers a reduction never uses. Unset, they are
    allocated and never written; `poison` fills them with 0xFF - a NaN
    at every format - and uploads them, which is how to ask a NEW image
    whether its reductions still ignore them (`device-test` does it for
    you on an XRT device; by hand, `CFT_XRT_REDUCE_BC=poison
    device-test -r -q <image>`); `zero` is the behaviour before that
    date, for an A/B timing. Under `CFT_XRT_TRACE` each reduction launch
    says which it did.
  - `CFT_XRT_TILE_ORDER` and `CFT_XRT_PROGRAM_CUTS` (2026-09-25): the
    scheduler's placement fuzz (backend_xrt.cpp, run_job). `seed:<N>`
    on the first permutes which tile runs which task, for every kind
    of run; on the second it re-cuts a program's lanes anywhere - one
    lane, an odd offset, a slice left out - and `skew:<N>` plants a
    one-lane slip, the placement tests' negative control. A card day
    runs device-test's matrix under a few seeds of each and requires
    every leg green, and `skew` red. Both refuse a malformed value by
    name; unset is the default placement.
  - `CFT_XRT_WITNESS` (2026-09-25): the completion witness's planted
    fault (backend_xrt.cpp). `busy-before` makes the first task's tile
    read busy in CTRL before its wave is staged, `busy-after` busy for
    50 ms after XRT's completion (so a witness that did not wait is
    seen not to), `busy-open` (2026-09-26) busy when a handle opens the
    tile; each must be refused by name, with the caller's output
    untouched and the handle - or, for an open, the next open - right
    straight after. device-test asks exactly that on every XRT device
    (`check_completion_witness`, and the open before the handle under
    test exists). The defect the witness exists for cannot be planted
    from a test without poisoning the card for everyone: see "A tile a
    run was abandoned on", below.
  - `CFT_XRT_BIND` (2026-09-26): `decline-outputs` makes a resident
    OUTPUT bind that would allocate, fill or re-window a device copy
    decline and be staged, as one too large for its channel does, so the
    staged collects that write a resident buffer's mirror are reachable
    on a card - device-test's "stale copies" runs its sequences again
    under it, each into a fresh buffer. An output copy already live at
    the same window is reused, not declined (verifier-V9). A malformed
    value is refused by name.
  - `CFT_XRT_CAPS` (2026-09-28): the image identity's two refusals,
    planted at open (backend_xrt.cpp). `plant-differ` gives tile 1 a
    CAPS word one bit off tile 0's, so `cft_get_image_id` refuses the
    image as mixed; `plant-unreadable` makes tile 1's CAPS read throw,
    so it refuses it as unreadable. Each refusal's sentence names the
    plant. Only the identity's record sees the planted word: a planted
    handle computes exactly as an unplanted one, and `device-test -i`
    holds its decode equal. It needs two tiles; on one it does nothing.
    `device-test -i` plants both on handles of its own, and a value set
    from outside reaches the handle under test, whose identity leg must
    then FAIL, unless the run was told to expect that refusal
    (`--expect-refusal mixed|unreadable`). A malformed value is refused
    by name at open, before anything is loaded.
- **A tile a run was abandoned on** (found 2026-09-25): a run that
  outlives `CFT_TIMEOUT_MS`, or a process killed mid-run, leaves its
  tile running after XRT has aborted the command, and until the image
  is reloaded XRT can report LATER runs on that tile - any process's -
  complete early. Before 2026-09-25 those came back wrong with rc 0; the
  library now refuses them by name ("was still running it", "is running
  work this process did not start"). Two rules for a card day:
  - **size a leg's wait to its run.** `CFT_TIMEOUT_MS` is one minute by
    default; a leg that can run longer sets it (the scheduler gate's
    one-tile 4,000-step run needed about 110 s and poisoned the next leg
    - docs/VALIDATION.md).
  - **after any timeout, reload the image before trusting a result** -
    load another xclbin, then this one. A load of the same image is a
    no-op, and it cures nothing: after the round's orphan every load was
    logged "xclbin is already downloaded" until the reload at 12:05:26,
    and the program set run through those loads was still wrong in the
    same lanes (docs/VALIDATION.md, 2026-09-28; the journal excerpt is
    `Data/runs/2026-09-25-ode-round/card-witness/journal-probe3-probe4.txt`,
    gitignored).
    `journalctl -k` shows every abandonment as `kds_del_cu_context: 1
    outstanding command(s)`, and a real load as `Config end completed`.
  The witness's card leg makes one on purpose (an fp256 run on tile 1
  with `CFT_TIMEOUT_MS=5000`), requires the refusals while it runs and
  after it ends and no wrong answer anywhere, requires a witness-off
  build to hand back wrong bytes with rc 0 on the same poisoned tile,
  and reloads last.
  - `CFT_XRT_TRACE` (what the tile received, and a pattern in the
  count window's staging pad that the strobes must leave alone),
  `CFT_XRT_MASK_ADDR_OVERRIDE` (does the tile read the mask: a fault
  says yes), `host/tools/maskflags.py` (did the mask reach the lanes:
  FLAGS under poisoned masked lanes) - stay in the tree and belong to
  every card day after this one: read them in the order above, and
  the RTL last.

## Owed to the next card day (added 2026-09-28): identity in libcft

*Paid the same day at 09:59, on the U50 (XRT 2.19), at 082400d: the
script's sixteen checks over both round-2 images, the quick matrix 2,456 of
2,456 after the new load path, and both negative controls red by name.
The records are `Data/runs/2026-09-28-cert-round/card-p2/`, which is not
tracked. What came after it - step 2's two planted refusals, new with
verifier-C3's send-back - was paid at 11:26 the same day, at 4d5d8e4:
seventeen checks, 0 failed, the quad image refusing both plants by name
on its four tiles, and the single image, with one tile, NOT TESTED by
name (`card-p2b/`, beside `card-p2/`). Owed again after P2c, and paid
at 14:13 the same day, at 45898df: twenty-three checks, 0 failed. Step
2's two new per-image lines (the malformed CFT_XRT_CAPS values, the
planted handles' decode) held on both images, and step 3's controls c
and d on the quad: an unexpected refusal failed by name, an expected
one passed by name (`card-p2c/`). Left as written below, because the
list is also the recipe.*

The certificate round's step 2 (docs/ROADMAP.md) gave the library two
identity calls: `cft_build_id()` names the source tree a library was
built from, and `cft_get_image_id()` names the device image by the
SHA-256 of the bytes the XRT backend loaded and by its raw CAPS words
(docs/HOSTAPI.md, "Identity at ABI 0.15"). Everything but the XRT half
is held on the desktop. The XRT half is compiled against XRT 2.14, ran
in hw_emu there (the 0907 quad image), and ran on the card at 09:59:
- the file read once, hashed, and loaded from those bytes, where XRT
  used to read it by path;
- the per-tile CAPS words.

What only a card can say:

    make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test
    bash hw/card-identity.sh <image.xclbin> [<another image.xclbin>]

From the root of the branch's checkout, with nothing new written into
the tree since the build: the script takes the tree's build id when it
runs. In order, each step an `ok` or a `FAIL` line:

1. **The build.** device-test links XRT (CLAUDE.md's trap 2). Its build
   id - `device-test --build-id` - equals the tree's
   (`make -C host print-build-id`), and that id names HEAD. On a clean
   tree, equal ids mean the binary is not stale. On a dirty one they
   cannot mean that - two edits of one commit carry one id - so the
   script says so on a NOTE line rather than an `ok`.
2. **Each image.** `device-test <image> -i` exits 0. That is
   device-test's own checks:
   - the digest against its own SHA-256 of the file, the bytes, VERSION,
     and the raw words decoding to the handle's caps and opcode groups;
   - on an image with two tiles or more, both refusals planted through
     `CFT_XRT_CAPS` - a tile whose CAPS differs from tile 0's, and one
     whose CAPS cannot be read - each refused by its own sentence, which
     names the plant (NOT TESTED, by name, on a single tile). The script
     counts those lines;
   - five malformed `CFT_XRT_CAPS` values refused by name at open, and
     each planted handle decoding exactly as the unplanted one. The
     script requires both lines to be shown.
   The digest it prints must also equal `sha256sum` of the file, and its
   bytes `stat`'s, and a manifest beside the image, where there is one,
   must say the same sha256.
3. **The negative controls**, a to c each required to FAIL by name.
   - a. `CFT_DEVICE_TEST_HASH_FILE` makes device-test hash itself in
     place of the image, and its digest check must fail naming both
     digests.
   - b. The script's own comparison, fed another file's digest and two
     empty strings, must refuse both.
   - c. On the first image with two tiles or more, `CFT_XRT_CAPS=
     plant-unreadable` set from outside device-test imitates a CAPS read
     that failed at open, and the identity leg must FAIL it: a refusal
     nobody asked for is a fault, not an answer.
   - d, which must PASS by name: the same kind of refusal told to
     expect - `CFT_XRT_CAPS=plant-differ` from outside, with
     `--expect-refusal mixed`, as a genuinely mixed layout is run.
4. **Two images**, when given: two digests, each its own file's. So the
   digest follows the image loaded.
5. **The open the digest changed still runs**: `device-test <image> -q
   -n 8` exits 0.
6. **A remote handle to a card-backed server**: `cft-serve --artifact
   <image>` on loopback, and `device-test cft://... -i` must see the
   remote handle refuse by name, even though the server holds an image.
   The server is stopped by PID.

Steps 1 to 4 and 6 open images and read registers, and start no run on
a tile. Step 5 is the quick matrix, 2,456 checks on the quad image, and a
run there can time out like any other: if one does, reload the image
before trusting anything after it (a load of the image already loaded
is a no-op, and cures nothing). Keep the script's output with the day's
record: the digest it prints is the "xclbin sha256" below, measured by
the library itself.

## Owed to the next card day (added 2026-09-28): the segment runner

*Paid the same day, from 15:21 to 15:23, on the U50 (XRT 2.19), at
99f1b43: card-segrun.sh 8 checks of 8. The gate gave 295 of 295 with
the certificates made on the quad's four tiles and 295 of 295 on the
single, and the negative control failed the device lines by name. The
records are `Data/runs/2026-09-28-cert-round/card-p3/`, which is not
tracked. It ran again at 4eed552, eb2d1ae and d4abe2a, P3b's three
answers (not at ff7ff7b alone), 8 of 8 each time,
the gate on each image 373 of 373 at 4eed552, 382 of 382 at eb2d1ae,
and 384 of 384 at d4abe2a, nothing skipped (card-p3b/, card-p3b2/ and
card-p3b3/, beside card-p3/). Left as written below, because the list
is also the recipe.*

The certificate round's step 3 (docs/ROADMAP.md) is `cft-segrun`
(docs/CERTIFICATES.md, "The segment runner"). It is held on the
desktop's software backend and through a loopback server. It is built
with XRT=1 against XRT 2.14 in WSL. It had not run on a tile when this
was written. What only a card can say:

    make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test
    bash hw/card-segrun.sh <image.xclbin> [<another image.xclbin>]

From the root of the branch's checkout, with python3 on PATH (the golden
model needs the standard library only). In order, each step an `ok` or a
`FAIL` line:

1. **The build.** cft-segrun links XRT. Its build id is the tree's, and
   names HEAD, with a NOTE on a dirty tree for the reason step 1 of the
   identity leg above gives.
2. **Each image.** `device-test <image> -i` names the image: VERSION,
   CAPS, tiles and formats, with `sha256sum` of the file. Then
   `host/tests/segrun_check.py --device <image>`, with those as what
   every certificate's device lines must say:
   - the three ODE programs at fp64 and fp256, certified on the tile,
     keyed and open, each with a half-step run, and at fp64 a wider fp128
     run (left out, on a NOTE line, for an image without fp128);
   - `flagstep`, whose segments raise flags and a STATUS the ODE
     programs never do (a NOTE, NOT TESTED, if the image refuses it);
   - since P3b, `lorenz63-rk4` at fp64 once more, its half-step run
     entered from a state of its own;
   - each certificate accepted by the golden reader, byte for byte the
     golden writer's from the initial states, its boundary files the
     golden chain's, and accepted by the golden audit, in full and
     sampled - all but that last one, which the audit must refuse
     `aux-start`;
   - each made again on the software backend, every run block byte for
     byte the card's;
   - on the software backend, the gate's refusals, and since P3b's
     send-backs its memory checks: what a run beside the main run costs,
     and what the trial costs the runs, each the least `ulimit -v` found
     by bisection. At eb2d1ae the first alone took about 22 s on the
     box, the gate going from 54 and 51 s to 76 and 75 s (card-p3b/,
     card-p3b2/).
3. **The negative control.** Handed device-test's own SHA-256 as the
   image's, the gate must fail the device lines by name.

Every segment is a run on a tile. If one times out, reload the image
before trusting anything after it. `device-tiles` is held here and
nowhere else: the software backend and a software server have one tile,
so a writer that wrote 1 without asking the library passes every
desktop check (P3's plants, 2026-09-28).

## The long run (added 2026-10-16): `hw/card-stress.sh`

Logan's word, 2026-10-16: a long stress test of the card, cycling across all its capabilities
and keeping metrics, from the evening of the 16th until Monday morning, weighted toward the
four-tile quad and using the time for lengthy sweeps. Until then the card had short legs, one
image at a time, and two soaks that each drive one artifact. `hw/card-stress.sh` is the driver.
It is written and dry-run (docs/VALIDATION.md, the entry "the long-run stress driver, parcel
ST"); **it had not touched the card when this was written, and the lead's smoke below is its
first card run.** Agents never run it: it opens the card.

**What it does.** Rotates through revision 8's three images (default weights quad 4, single 1,
deep 1), and on each visit runs a battery of the card's own legs and then fills the rest of the
cycle with slices of the native-oracle soaks. Opening an image is switching to it: `cft_open`
loads the xclbin through XRT (`host/src/backend_xrt.cpp`, `cftx_open`), so there is no program
step. XRT treats loading the xclbin already there as a no-op, which is why a tile left running
by an abandoned run is cured by loading another image and then this one (docs/HOSTAPI.md, "A tile
a run was abandoned on") and why the failure policy does exactly that.

### Start, stop, read

```
# from a clean checkout at the commit under test, on amd-arc-box, in tmux (or: setsid nohup ... &)
bash hw/card-stress.sh --quick                              # the smoke
bash hw/card-stress.sh --until "2026-10-19 08:00" --out /data/card-stress-1016   # the long run
touch /data/card-stress-1016/STOP                           # stop: ends after the leg running
cat  /data/card-stress-1016/status.txt                      # now, any time
python3 hw/card_stress_report.py /data/card-stress-1016     # the report, any time (also report.txt)
```

- **Before the long run, `make vectors` in that checkout** (added 2026-10-16, after
  verifier-VST): the `selftest` leg replays `vectors/out`, which is gitignored, so a clean
  clone lacks it, and the leg would then end as a failed leg (status `fail`: cft-selftest prints
  '0 cases checked' and 'CONFORMANCE FAILED: ...' and exits 1) at every third visit of each
  image: a loud failure, never a false pass. `make vectors` writes only ignored paths, so the
  tree's build id stays clean; check it with `sha256sum -c SHA256SUMS` run in `vectors/`. The
  first long run's clone had it made by the lead before its first `selftest` leg.
- **Pre-flight, optional**: `bash hw/test-card-stress.sh --no-plants` runs the driver's dry-run
  tests (the verdict parsers on real logs, the scheduler, the failure policy, the guard, the
  sweep's resume, the report, and under POSIX the real `make` in a scratch copy) on the box, with
  no card and no XRT: about 5 minutes under WSL and 6 to 8 under Git Bash (2026-10-19, a desktop other
  sessions share), and it must be run alone on the host (two drivers at once see each other's
  stand-ins as card users). `--no-plants` leaves out the negative controls, which take about
  twice as long as everything else together (11 minutes under WSL). The runner and the pythons
  the suite itself starts run with `-B` (`-I` ignores `PYTHONDONTWRITEBYTECODE`); the report script
  the driver starts for itself does not, so a run in the tree under WSL still leaves one git-ignored
  card_stress_lib file in hw/__pycache__ unless that variable is set.
- **The smoke (`--quick`)**: every leg once on each image (quad, single, deep), short slices;
  exit 0 only if every leg passed (a leg skipped by name, with its reason, is not a failure).
  **Estimated** at 24 to 28 minutes on the card, from the 2026-10-06 card times where there are
  some (card-segrun 169-185 s an image, device-test's three matrices about 2, 11-14 and 2 s, the
  acceptance set 371-384 s for 20 entries so about 40 s for the two the smoke runs) and guesses
  where there are none (api-test, `dt-i`, `seq-check` at 60-120 s, the sweep's slices, an image
  load): COMPUTED and BELIEVED, not measured. If it runs past 30 minutes, those are the suspects.
  Outside the estimate: the host build (`make -C host XRT=1 ...`, once) and, if
  `--rev8-images` holds no cache, the revision-8 entry's 51 s compile on the quad. Since
  2026-10-20 the smoke's revision-8 leg on the quad also runs one routine entry, about 10 s
  (COMPUTED from the lead's 57 s for six), inside the estimate's margin. With `--sweep-items` the
  smoke sweeps the items named, not its own four (the sweep paragraph below).
- **The long run** needs `--until` (the box's local time). Use a **new `--out`** (default
  `~/card-stress-out/<stamp>-<commit>`; put it on `/data`) **outside the checkout** - files in the
  tree make it untracked, which changes the build id `hw/card-segrun.sh` asserts, so the driver
  refuses an `--out` inside it that git does not ignore - and a checkout nobody else touches:
  the driver builds the tools from it once and `hw/card-segrun.sh` asserts at every run that
  the tools' build id names HEAD, and the driver stops (`tree_moved`) if HEAD moves.
  `--resume --out DIR` continues a run (the sweep's state is read back from `metrics.jsonl`; a
  last line torn by a killed run is kept beside it as `metrics.torn-<time>.txt` and cut off, and
  the run records a `torn_tail` event).
- **Stop**: `touch $OUT/STOP`, or SIGTERM or SIGINT once. It ends **after the leg running**,
  never in the middle of one (an abandoned card run poisons its tile until an image reload);
  a sweep wave in flight finishes. A second signal terminates the legs running. Closing the
  terminal does not stop it (SIGHUP is ignored). A stale `STOP` at the start is refused.
- **Read**: `status.txt` (rewritten after every leg: time, cycle, image, totals by image,
  consecutive card failures, the last telemetry and the host's load, the sweep's coverage and
  rates, the deadline), `driver.log` (what the driver said), `metrics.jsonl` (the record),
  `logs/` (each leg's log: a passing leg's gzipped, a failing leg's whole), `STOPPED.txt` (why,
  when the policy stopped it), and the report. **What the smoke should print**: for each image
  `leg dt-i on <image>: pass`, and `build step image <name>: ok - ... equal to SHA256SUMS`; at the
  end `card-stress ends: quick_done (exit 0)`. Read `status.txt`'s `telemetry` line (values, or
  "no values parsed" with the error) and its `sweep` rates: those are the two things the
  dry run could not test against the real tools.

### The legs, the sweep, the records

| leg | command (all under `nice -n 10` and `timeout`) | verdict read | timeout (s) |
|---|---|---|---|
| `api-test` | `api-test` (built with XRT=1) | `api-test: all contract checks passed` | 300 |
| `dt-i` | `hw/run-device-test.sh IMAGE -i` | `N checks, F failed`, "identity holds", the image's SHA-256 and tiles held to the file's | 300 |
| `dt-q8`, `dt-full`, `dt-r`, `dt-b` | `... -q -n 8`; `-n 4096`; `-r`; `-b -n 4096` | `N checks, F failed`, the NOT-lines, "agree on every case that RAN" | 600, 900, 600, 600 |
| `card-segrun` | `hw/card-segrun.sh IMAGE` | `== card-segrun: N checks, F failed` | 1500 |
| `seq-check` | `host/tests/seq_check.py --trials 250 --formats fp32 fp64 fp128 fp256 --device IMAGE` | the device's "agree on every program" line, the program counts | 2400 |
| `acceptance` | `programs/acceptance.py --device IMAGE` | `acceptance: N of M PASS ...; K checks ok, F failed` | 2400 |
| `acceptance-rev8` | `... --set rev8 --legs set --device IMAGE --target T --images DIR --only ENTRIES` (+ `--lib`, naming this tree's host/libcft.so, when ENTRIES has a routine entry, as on the quad) | the same, as `acceptance rev8` | 2400 (+14400 until the workloads' images are cached) |
| `resident`, `selftest` | `cft-resident IMAGE`; `cft-selftest vectors/out IMAGE` (every 3rd visit) | `every row: status clean ...`; `N cases checked` | 600; 3600 |

The timeouts are several times the card times of 2026-10-06 (docs/VALIDATION.md), with a floor.
**A count in a record is a captured group of a line a pattern matched, or it is absent**; a log
no pattern reads is a `parse_error` leg, kept whole, and a log whose exit status contradicts its
verdict is refused the same way. `hw/card_stress_lib.py` holds every pattern, each citing the
printf it matches.

- **The revision-8 leg** runs the entries the image is (`--target`): programs/acceptance.py's
  rule puts fifteen on the quad - nine workloads and the six routine entries the math library
  added on 2026-10-19 - one on the deep and **none on the single** (where R21 alone keeps a
  workload off the quad, which none does), so the single's leg is recorded as skipped, by name.
  Two entries compile for 40 minutes and 2.2 hours (Gray-Scott extended, the deep's only entry,
  and Riccati extended): **they are left out unless their image and bank are already in
  `--rev8-images`** (default `$OUT/rev8-images`), so by default the quad runs fourteen (eight
  workloads and the six routine entries) and the deep's leg is skipped, by name, with that reason.
  The driver does not compile them in the background; seed that directory from the lead's W8
  images and it runs fifteen on the quad and one on the deep. The eight workloads that compile in
  minutes compile once, on the first visit of the quad, and are read back after.
  **The six routine entries** (the Lotka-Volterra, diode and culture references at fp64 and
  fp256: `REV8_ROUTINES` in programs/acceptance.py, the section "Owed to the next card day" below)
  have nothing to compile or to cache: their image and bank are committed files under
  programs/systems/compiled-tangent/, which `--images` does not touch, so they never add the
  compile allowance to the leg's timeout. They need libcft's shared library for the mark probe,
  and the leg names this tree's own, host/libcft.so, with `--lib`, rather than leave it to `$CFT_LIB`
  (acceptance.py's default); the build step has already asserted that library is XRT-linked. Of the
  box the six ask nothing the driver's build does not already make. They were missing from the
  driver from 2026-10-19 to 2026-10-20: `REV8_ENTRIES` is a table in hw/card_stress.py, and its test
  read `REV8` alone and counted its ten. The test now holds the table to `REV8` and
  `REV8_ROUTINES`, entry for entry and target for target, and goes red on any other `REV8` name in
  programs/acceptance.py that it has not been shown. The six took 57 s on the card (MEASURED, the
  lead's, below); the leg's 2400 s is 5.9 times the quad's fifteen, 353 s for the nine workloads
  (2026-10-12) and 57 s for the six, 410 s (COMPUTED). The smoke (`--quick`) runs one of them,
  `lotkavolterra-rk4-tangent-fp64`, beside `phi4_extended_fp64`: about 10 s more (COMPUTED, 57 s
  over six), the routine path on the card in the smoke instead of in the long run's first cycle.
- **The sweep** is hw/run-soak.sh's and hw/run-c5-soak.sh's campaigns - fp32 `sqrt32` under five
  attributes, fp32 `roundToIntegral` under five, `nextUp`, `nextDown`, `logB`, `class`, each over
  all 2^32 encodings; **the exhaustive conversion and scaleB items**, also over all 2^32
  encodings - `conv32to64-all`, `cvtto32-all` under five attributes, `cvtfrom32-all` and
  `cvtfrom64-all` (every 32-bit integer as an i32 and as a u32 source), `scaleb32-all` (every
  encoding against the directed exponent list) and `scaleb32-wide` (every encoding against the 556
  exponents, -278 to 277, that can change a result, and 12 past those edges that must land as
  the edges do), the last four under the four attributes the probes allow; and the random banded
  `div32`, `div64`, `sqrt64` and clause-5 jobs with those scripts' seeds (the 90 items: 36
  exhaustive and 54 random) - run slice by slice with `CFT_SOAK_ARTIFACT` naming the image. The
  scripts themselves cannot be sliced or resumed (each wipes its output directory and runs
  everything), so the driver runs the same binaries on the same job lines. Slices are sized from
  the rate it measures: the first slice of each op on an image is a probe of 2^20, later ones fill
  `--sweep-slice-seconds` (600) at the measured rate, in whole 2^20 steps. **On the quad the
  jobs are four processes at once, one a tile (`CFT_XRT_TILES=1..4`)**, the shape docs/HOSTAPI.md
  gives for independent jobs (a single process over four tiles pays to cut every small call);
  a single image gets one job. The sweep takes `--sweep-minutes` of each cycle (quad 45, single
  20, deep 20); exhaustive items outweigh random ones 3 to 1 (`--sweep-weights`).
  Coverage is **rebuilt from `metrics.jsonl` alone**: a slice is covered when its job finished
  with a verdict (a pass, or a disagreement, which is kept with its operands); a slice that timed
  out or lost the device is not covered and is run again, and one that fails to finish
  `--quarantine-after` (2) times is moved past and recorded. `--sweep-items sqrt32-rne,...`
  restricts the campaign (a wave runs one job a distinct item, so one tile per item named: name
  four items for four tiles). **With `--quick` the smoke's waves are those items** (since
  2026-10-20), in the order named and the least served first, skipping any that cannot run: the
  first four on the quad, one a wave (two waves) on a single image, so the single and then the deep
  take the next ones and not the same again, and with `--resume` a second smoke should go on again (read from
  `load_state`, which rebuilds the served counts; not run).
  Until then the smoke planned its own four items (`sqrt32-rne`, `rint32-rne`, `div32-rne`,
  `nextup32` on the quad) whatever was named: on 2026-10-19 `--quick --sweep-items` naming EX's 22
  exhaustive items named none of them, every wave was empty (the lead's account: the report said
  "slices: 0 completed") and the log said "sweep: nothing left to run in this campaign" on each
  image, which reads like a finished campaign. **A wave with nothing to run now says why**, in
  the log and as a `sweep_empty` event in `metrics.jsonl` (the report counts it in its events
  line): `nothing left to run in this campaign` (`nothing left to run for the items named by
  --sweep-items` when some are named) only when every item of the campaign is an exhaustive item
  already covered - decided over the campaign, never over the wave's own list. When only the
  wave's list is blocked it says `no job from this wave's list could start (...), but the campaign
  is NOT finished` and names what can still run; when nothing can run, `no sweep job could start,
  and the campaign is NOT finished`, with the items by cause (outside `--sweep-items`, disabled,
  covered, moved past by the quarantine, not in this run's catalog because a probe ruled it out).
  On a single image or the deep, if the smoke's first item cannot run (a covered `sqrt32-rne`, a
  resumed run's), it goes on to the second (`rint32-rne`) instead of ending that image's sweep.
  `nextup32` and `nextdown32` report 8 more cases than their range (the
  tool runs eight edge cases in every slice, clause5_soak.c `next_edges32`); the driver expects
  exactly that and refuses any other count.
  **The exhaustive conversion and scaleB items say what they covered**: their verdict line ends
  `, E encodings, S skipped`, and the driver holds each slice to it exactly - E is the slice's
  encodings, and cases + S is E times the checks an encoding takes (1, 4, 2, 2, 17 and 568 for
  the six modes in the order above). A slice short by one encoding or by one check is a
  `parse_error`, not covered, and served again, across a restart too. `cvtto32-all` compares
  in-range lanes only, so its cases are not a function of the slice (a slice of NaNs compares
  nothing and skips every pair, and is a pass): it is held to the encodings and that sum, and
  `S` is the pairs it left out. The other five skip nothing.
  **Which items reach the tile.** Each item is marked `tile` or `host`
  (hw/card_stress_lib.py, `OP_REACH`), from the library's own classification (the header of
  host/src/clause5.c, lines 13-25, and host/include/cft.h): `cft_rint`, `cft_scaleb`, `cft_div`
  and `cft_sqrt` are composed of tile passes (scaleB takes a host path below the subnormal floor,
  -149 for fp32); the conversions, `nextUp`/`nextDown`, `logB`, `class` and `remainder` are HOST
  operations - no floating-point arithmetic, "nothing for a device to accelerate", bit-identical
  on every backend by construction. **A card soak of a host item is libcft's host code run on
  the box against its CPU**: a full-space test of the library in which the tile computes nothing,
  which the software backend on any CPU repeats. 43 of the 90 items reach the tile (25 of the 54
  random, 18 of the 36 exhaustive) and 47 do not. The host items stay in the campaign. Every
  sweep record carries `sweep.reach`, status.txt has a `reach` line (how much of the exhaustive
  space each kind has covered), and the report a `reach` column (its last) and totals by reach.
- **Records.** `metrics.jsonl` is append-only: a `leg` record each (the cycle, the image and its
  SHA-256, the leg, its start and end, exit status and class - pass, fail, timeout, no_device,
  parse_error, skipped, error -, the counts its verdict line gave, cases or checks a second,
  the log), a `telemetry` record a sample, and `run_start`, `build`, `cycle_start`, `cycle_end`,
  `event` and `run_end` between. The report (`hw/card_stress_report.py`) reads it at any time:
  runs, passes, failures, cases and rates over time by image and leg, the telemetry's range and
  trend, every failure with its log, the sweep's coverage and every disagreement, the run's
  uptime and gaps.

### The exhaustive conversion and scaleB items: what to run, what it costs, what it must print

The six modes (host/tools/clause5_soak.c, "Exhaustive modes": `conv32to64-all`, `cvtto32-all`,
`cvtfrom32-all`, `cvtfrom64-all`, `scaleb32-all`, `scaleb32-wide`) take `<lo> <hi>` over the 32-bit
operand's encodings and, per attribute, are the random mode of the same operation with its operands
enumerated. `scaleb32-wide`'s exponent range, -278 to 277, is derived in the source above its
constants and **measured on the host's libm by `clause5-soak probe scalebrange`**: the lowest exponent
that changes a result is -277 under rne and -276 under rtz, rdn and rup, the highest is 276, and 12
witnesses past the edges (to the extremes of an int and of an int64) are checked on every operand
against the oracle at the edge they must equal.

| item (per attribute) | checks an encoding | one tile (COMPUTED) | four tiles on one item | software backend, one process (MEASURED, sampled) | reaches the tile |
|---|---|---|---|---|---|
| `conv32to64-all` (no attribute) | 1 | 12 min | 3.0 min | 9 min (run whole: 8.8) | no (host) |
| `cvtto32-all` (five) | 4 (some skipped) | 30 min | 7.5 min | 19 min (rne), 26 min (rup), 19 min (rmm) | no (host) |
| `cvtfrom32-all` (four) | 2 | at most 37 min | at most 9.3 min | 14 min (rne), 14 min (rup) | no (host) |
| `cvtfrom64-all` (four) | 2 | at most 38 min | at most 9.5 min | 12 min (rne), 16 min (rup) | no (host) |
| `scaleb32-all` (four) | 17 | 85 min | 21 min | 4.2 h (rne), 4.9 h (rdn) | yes |
| `scaleb32-wide` (four) | 568 | **47.5 h** | **11.9 h** | 5.8 days (rne), 6.6 days (rup) | yes |

The card figures are `2^32 / (the stress run's median rate a tile)` from the 2026-10-16 to 19 run's
`metrics.jsonl`, per job on a tile of the quad; the scaleB rates there are **checks** a second
(the random mode's count is decremented by the operands times the list's length), which is why
`scaleb32-all` is 17 times and `scaleb32-wide` 568 times an operand-rate figure. The cvtfrom
figures are upper bounds: the random mode makes four conversions a lane and these make two.
The `scaleb32-wide` figures carry a mix the rate was not measured on: the random mode's 17
exponents are 15 on the tile and 2 on the host, the wide item's 568 are 433 on the tile and 135
on the host, and the wide item's tile exponents take 1.43 tile passes a check against 1.27 for
the random list's (COMPUTED by verifier-VEX from the library's chunking rule, host/src/clause5.c),
so 47.5 h and 11.9 h are the right order, not a
prediction to the hour. The four tiles' column is four processes on four quarters of the space
(below). **The software
column is the whole item on one CPU core; `conv32to64-all`, `cvtto32-all`, `cvtfrom32-all` and
`cvtfrom64-all` are host operations, so any CPU's software backend is the same test as the
card's, and `scaleb32-wide` is hardware-only in practice.** The software figures are estimates,
not runs (`conv32to64-all` was run whole: 526.5 s): 2^32 times the mean time an encoding over 32
small slices, one in the middle of each of 32 equal cells of the space, on a WSL desktop other
sessions share (2026-10-19): good to about a quarter and no better - the same sampling gave
`conv32to64-all` 6.9 minutes against the 8.8 it took. A figure taken from the first slice of the
space runs high for scaleb32-all, whose start is subnormals: 169 K encodings a second there in
one run against 285 K to 310 K at three places in the normal range; verifier-VEX measured 225 to
238 K from the start against 248 to 314 K in the normal range, so the effect is real but smaller
than that one run suggests. `cvtfrom64-all` under rtz, rdn and rup computes the same exact
answers as under rne - a 32-bit integer converts to fp64 exactly - so three of its four
attributes repeat rne's results (3 x 38 min of a tile); it still tests that the library takes
each attribute's path.

Through the driver, on the box (one job a distinct item, so name four items for four tiles; the
driver builds the tools with XRT=1 itself):

    bash hw/card-stress.sh --until "YYYY-MM-DD HH:MM" --out ~/card-stress-exh \
         --legs api-test --weights quad=1,single=0,deep=0 --sweep-minutes quad=720,single=0,deep=0 \
         --sweep-items scaleb32-wide-rne,scaleb32-wide-rtz,scaleb32-wide-rdn,scaleb32-wide-rup

(four wide attributes in about 47.5 h; `scaleb32-all-*`, the four host families and the older items
are named the same way). A finished item shows in `status.txt` and in the report as 4,294,967,296 of
4,294,967,296 encodings, 100.000%, with its reach.

One item on all four tiles, without the driver - any of the six (the same binary and oracle;
`$IMG` the quad's xclbin built with XRT=1; `conv32to64-all` takes no attribute word):

    JOB=scaleb32-wide; ATTR=rne
    for k in 0 1 2 3; do
      CFT_SOAK_ARTIFACT=$IMG CFT_XRT_TILES=$((k + 1)) nice -n 10 host/clause5-soak $JOB \
          $((k << 30)) $(((k + 1) << 30)) $ATTR > $JOB-$ATTR-q$k.log 2>&1 &
    done; wait; grep -h " cases," $JOB-$ATTR-q?.log

The same on a CPU's software backend, for the four host families (and any other item; four cores
for four quarters): leave out the two variables of the loop's second line, so no
`CFT_SOAK_ARTIFACT` names an image and `cft_open(NULL)` selects the software backend. It needs
only `make -C host clause5-soak` (XRT=0 is the default) on a 64-bit Linux. (hw/run-c5-soak.sh's
no-argument form runs all of these, the wide item included: about 23 to 25 process-days, so
roughly 18 to 21 hours on 30 workers, nearly all of it `scaleb32-wide`; its header says so.)

    JOB=cvtto32-all; ATTR=rne
    for k in 0 1 2 3; do
      nice -n 10 host/clause5-soak $JOB $((k << 30)) $(((k + 1) << 30)) $ATTR > $JOB-$ATTR-q$k.log 2>&1 &
    done; wait; grep -h " cases," $JOB-$ATTR-q?.log

**What each must print.** The first line of each log is `soaking the DEVICE backend: <xclbin>`
(`soaking the software backend` when no artifact is named); the last is
`JOB ATTR: C cases, 0 value mismatches, 0 flag mismatches, E encodings, S skipped`, exit status 0,
with E the quarter's 1,073,741,824 and cases + S the checks an encoding takes times E:
`conv32to64-all rne` 1,073,741,824 cases, 0 skipped; `cvtfrom32-all` and `cvtfrom64-all`
2,147,483,648; `scaleb32-all` 18,253,611,008; `scaleb32-wide` 609,885,356,032; `cvtto32-all`
4,294,967,296 as cases plus skipped, the split being the attribute's (the software backend gives
the same split for the same quarter). Over the whole space the four lines' E add up to
4,294,967,296 and their value and flag mismatches are 0. A disagreement lists operands
(`MISMATCH ... a=0x...`, and for the scaleB items the exponent as `b=`); `scaleb32-beyond` names a
witness past the range's edge. Values are compared per lane; **flags per batch** (the library's
batch call returns one flags word, so the soak compares the OR over the batch and rechecks lanes
alone only where it differs): a flag the library drops on one lane among others that raise it is
not seen, e.g. one signalling NaN of many that fails to raise INVALID - the random modes share
this; it is seen when that lane is the only one in its batch to raise the flag.

The tool's side is tested by `python3 hw/test_c5_exhaustive.py` (POSIX with make and a C compiler,
about a minute): every mode and attribute over 37 slices of the special regions (zeros,
subnormals, the normal range's edges, infinities, quiet and signalling NaNs, the integer targets'
boundaries) and 96 slices across the whole space, the refusals, a sabotage control for each mode,
and plants - a library result changed for one operand, the oracle given the wrong attribute, the
exponent range wrong by one, the encodings miscounted, a skip filter too eager - each of which
must go red at its operand or exponent (`cvtto32-all`'s skipped pairs are also counted there
independently of the tool, which the driver cannot do: it holds that mode to E and
cases + S = 4E); `--baseline-tree DIR` also compares the random modes byte for byte with another
tree's (`git archive REV host | tar -x -C DIR`). The driver's side is `hw/test-card-stress.sh`
(group `sweepall`, and the plants).

### The class-level items for the 64-bit rounding operations: what to run, what it costs, what it must print

(Parcel CL, 2026-10-20. This section is CL's alone; parcel HC may add one of its own, for division and square root.)

The 64-bit operand spaces (2^64 encodings, 2^128 pairs) are not swept; what a sweep can reach is every
**class** of operand, under the structure `docs/studies/SWP-A-coverage.md` section 4.3 calls the second
level: the rounding unit depends on the dropped bits only through guard and a sticky tree, on the kept
bits only through the lsb and the carry, and on the exponent only through a rebias and range checks. So
a representative of every class of dropped bits (zero, below half, half, above half), with the kept lsb
and the kept bits all ones, and a walking one over the kept and dropped bits, is run at every rounding
position and at the range edges. **A pass is a claim at the class level (L2), and it is PLAUSIBLE, not
proved**: it rests on that structural assumption about the tile (and, for the three host operations,
about libcft's own rounding code), which nothing here tests. It is not a claim at the value level (L1)
and not a sweep. The five modes (host/tools/clause5_soak.c, "Class-level (L2) modes"): `conv64to32-class`,
`rint64-class`, `cvtto64-class`, `cvtfrom64-class` and `scaleb64-class`, each `<lo> <hi> <attribute>`
over the operation's index space, calling the same batch kernels as the random mode of the operation
(so the oracle, the flag discipline, the probes and the sabotage are the random mode's) and printing
the exhaustive modes' verdict clause, `, E encodings, S skipped`, with E counting indices. The index maps are
written in `python/c5_class_enum.py`, which is the reference; `clause5-soak dump <job> size` and
`dump <job> <lo> <hi>` print the C side of them (no device opened), and the tool test holds all of it
equal to the Python, index for index.

**What an index is.** One operand (one operand-exponent pair for scaleB), numbered

    index = ((position * 2 + sign) * 4 + class) * (4 + W) + pattern

by an exponent or rounding position (the exponents at which the rounding position or the range class
changes, then 23 witnesses: the walking ones and zeros of the biased exponent field and the
subnormals), a sign, a class of the dropped bits, and a pattern (the kept lsb and whether the bits above
it are all ones, or a walking one at one fraction bit). **How each space was counted** (COMPUTED,
`python python/c5_class_enum.py --sizes`):

| mode | the space | N | k | distinct operands |
|---|---|---|---|---|
| `conv64to32-class` | (281 structural exponents, -152 to 128, + 23 witnesses) x 2 signs x 4 classes x 56 patterns | 136,192 | 1 | 124,984 |
| `rint64-class` | (57, exponents -3 to 53, + 23) x 448 | 35,840 | 4 | 26,032 |
| `cvtto64-class` | (68, exponents -3 to 64, + 23) x 448 | 40,768 | 4 | 27,242 |
| `cvtfrom64-class` | 190 cells (i64 positive, i64 negative, u64, by bit length) x 4 classes x 67 patterns + 3 (-2^63, 0 as i64, 0 as u64) | 50,923 | 1 | 11,557 |
| `scaleb64-class` | 3 routes x 54 strips x 448, + 36 overflow + 36 deeper than the last strip | 72,648 | 4 | 65,992 |

The study's 377,664 for conv64to32 is 281 x 4 x (2 x 2 + 52) x 2 x 3: three magnitude functions
(nearest, truncate, away from zero) with both signs each, a (function, sign) pair run once however
many (attribute, sign) pairs reach it (eight of them reach six). The soak runs one attribute a job, and each attribute covers its own mode code and sign path
(the study's own edge note, 4.3 (d)), so the figure per attribute is the same formula without the
three: 281 x 448 = 125,888, and 3 x 125,888 = 377,664 exactly. Mine is 136,192 = (281 + 23) x 448, the 23
being the exponent witnesses that make "the exponent matters only through a rebias and range checks"
testable at the 11-bit field's bits and not only across the 281 exponents where the result changes
class. **k** is the checks an index makes: one for `conv64to32-class` and `cvtfrom64-class` (host operations, one
result an index); a case a target for `cvtto64-class` (the four integer targets, each in-range lane as exact=0 and exact=1: **S, the
skipped, is the (operand, target) pairs whose rounded integer leaves the target's range, and only this
mode skips**); and a case a lane for the two that reach a tile (below). A space is regular by
construction, so a class or pattern that does not exist at a position repeats an operand: the last
column is the operands that differ, and a repeat costs cases and no coverage. Over the attributes the
soak runs (four, five, five, four, four): 22 items, 1,422,092 indices.

**How a class case is run.** Alone (`CLS_BATCH` = 1 operand a kernel call), and the two tile modes in
each of the tile's four fp64 lanes. The kernels compare values per lane but flags as the OR over a call, and look
at a lane by itself only where the ORs differ, so a flag a defect drops on one operand among others
that raise it is unseen in a batch: **MEASURED**, a library that drops INEXACT for the operands whose
dropped bits are exactly 0...01 and which do not overflow fp32 (the overflow path raises INEXACT itself) passes the whole `conv64to32-class` space in batches of 4,096 under all four
attributes and fails when the index 68,152 (0x3ff0000000000001) is run alone; under rtz a fault in the sticky tree can show
only in the flags (the planted one showed nothing under rtz), so the batch OR would hide all of rtz's evidence for it. And an element goes to the tile's
lane (its place in a pass) mod 4, the index space puts pattern t at index mod 4 = t mod 4, so a whole-space run
in batches meets each pattern in one lane: **MEASURED**, a fault planted in lane 2 of `cft_rint` that only the
operand with fraction field 0x20 meets passes a run that does not rotate and fails the default. So
each operand of `rint64-class` and `scaleb64-class` is run once in each lane, behind 0 to 3 benign
operands (1.0, +0: exact, no flags, not counted as cases), which is why k is 4 for them. The cost is calls,
not cases (the software backend has no lanes, so there it is only work). Build with
`-DCLS_BATCH=4092` for batches (flags per batch, lanes still rotated) or `-DCLS_LANES=1` for no rotation.

| item (per attribute) | cases a attribute | reaches the tile | software backend, one process, the whole item (MEASURED) | on the card, one tile (COMPUTED) |
|---|---|---|---|---|
| `conv64to32-class` (rne rtz rdn rup) | 136,192 | no (host) | 0.03 s | the stress run's rates, 5.6 to 6.2 M cases/s: 0.022 to 0.024 s |
| `rint64-class` (rne rtz rdn rup rmm) | 143,360 | yes | 0.5 s | lane-exact, 8 passes of about 260 microseconds a call and 4 calls an index: **about 5 min**; in batches (`-DCLS_BATCH=4092`) at 1.87 to 1.97 M cases/s: 0.073 to 0.077 s |
| `cvtto64-class` (rne rtz rdn rup rmm) | 91,005 / 91,484 / 85,141 / 91,478 / 90,986 compared, with 72,067 / 71,588 / 77,931 / 71,594 / 72,086 skipped | no (host) | 0.02 s | the stress run's rates, 4.7 to 5.0 M cases/s: 0.018 to 0.019 s |
| `cvtfrom64-class` (rne rtz rdn rup) | 50,923 | no (host) | 0.01 s | 7.4 to 7.6 M cases/s: 0.007 s |
| `scaleb64-class` (rne rtz rdn rup) | 290,592 | yes | 0.14 s | lane-exact, about one pass of 280 microseconds a call and 4 calls an index: **about 1.4 min**; in batches at 13.5 to 13.8 M cases/s: 0.021 to 0.022 s |

The host rates are the 2026-10-16 to 19 run's per-job medians on the quad (`docs/studies/swp-a/stress-final-item-rates.txt`);
a host item is a CPU job, so the software column is the same test as the card's. The tile
items' lane-exact figures use the study's per-pass cost (`tile_counts.out` T5, BELIEVED: a pass is
dominated by the call, not the 1 to 4 elements) and are the right order, not a prediction: on all five
attributes `rint64-class` is about 25 minutes of one tile and `scaleb64-class` about 6, no single item over about five
minutes, and none has run on a card yet. `cvtto64-class`'s compared cases are
the tool's counts on the software backend, each equal to an independent count made in Python from the
rounding rule alone, so a driver can hold the whole item to them.

On a tile of the quad, one item (the same binary and oracle; `$IMG` the quad's xclbin built with XRT=1; the four
attributes of `scaleb64-class` shown; `cvtto64-class` and `rint64-class` also take `rmm`):

    for ATTR in rne rtz rdn rup; do
      CFT_SOAK_ARTIFACT=$IMG CFT_XRT_TILES=1 nice -n 10 host/clause5-soak scaleb64-class 0 72648 $ATTR \
          > scaleb64-class-$ATTR.log 2>&1
    done; grep -h " cases," scaleb64-class-*.log

and on a CPU's software backend, for any of them, with no `CFT_SOAK_ARTIFACT`. **What each must print**: the last line
`JOB ATTR: C cases, 0 value mismatches, 0 flag mismatches, E encodings, S skipped`, exit 0, E the
slice's indices (the whole space: 136,192, 35,840, 40,768, 50,923, 72,648) and cases + S = k x E (k as
in the table above); a slice's coverage is held by `parse_soak`'s cover rule as it is for the exhaustive
modes. A disagreement lists operands (`MISMATCH ... a=0x...`, the exponent as `b=` for scaleB), and in a tile
mode a mismatch on a benign operand names 1.0 or +0. A range outside the space is refused by name (exit 2).

**The coverage check, and p = 24 and 53.** At e4m3 and e5m6, the formats where the study's exhaustion works, the
same enumerator built at those widths reaches every key (sign, position, class, kept lsb, kept all ones) that any encoding
exhibits, and every carry out of the kept bits (a (key, attribute) pair whose kept bits are all ones and whose attribute rounds up),
for all five operations: 8 instances, from 46 to 416 keys each, 0 missing (`python python/c5_class_enum.py --check`,
`python/tests/test_c5_class_enum.py`); a plant that never produces one class fails it by name, for each of the four
classes of each instance, and the classification the keys read off the definitions equals python/cft_golden's results on every
enumerated case. At p = 24 and 53 exhaustion is out of reach, and the argument is that it is **the same enumerator, wider**:
one function of (exponent width, fraction width, target), built at 4, 5, 8 and 11 exponent bits; a key's validity (which
classes and patterns exist at a position) depends on whether the dropped width is 0, 1 or at least 2 and the kept width is below 0, 0,
1, 2 or at least 3, and the small formats hold every such regime; and, measured over the enumerator's own whole space at p = 24 and 53, for every
one of the 22,480 non-degenerate indices of nine instances the key of the operand it builds equals the key the index names. What this does not show
is that the rounding unit has the structure.

**What the assumption excludes** (the study's own list, and this parcel's): a defect keyed by a combination of dropped bits beyond the walking
set (a carry-chain fault that needs a pattern longer than the walk); a pattern-dependent timing fault; the subnormal-operand
normalization paths of scaleB beyond the one leading-bit position it uses, and of the other operations beyond the b = 0 witness; and everything the
class level does not name (the i32 and u32 sources of cvtfrom, which `cvtfrom64-all` sweeps in full). The lane count (4) is read from
`docs/ARCHITECTURE.md` and the lane an element takes from the staging order (BELIEVED); a build with another count takes `-DCLS_LANES`.

The tool's side is tested by `python3 hw/test_c5_class.py` (POSIX with make and a C compiler, a minute and a half)
and the enumerator's by `python -m pytest python/tests/test_c5_class_enum.py` (eight seconds): the dump equal to the reference
for every index; every mode and attribute over its whole space and over 968 slices of odd alignment; the refusals; a sabotage control
for each; and plants, each red at the check written for it - a slice counted one index short (the cover rule), a mode that skips every index
(the cover rule passes it; the rule that a class item compare something refuses it), a wrong class selector (the dump comparison), a skip
filter too eager (the independent count), a sticky tree without the lowest dropped bit (the class mode catches it under rne, rdn and rup, and
the random mode's draws, 100 times as many, do not), a defect only a flag shows and one only a lane shows (both caught by the default build and missed by the builds the knobs make). `--baseline-tree DIR` compares
the random and the exhaustive modes byte for byte with another tree's.

### The hard-case division and square-root items: what they are, what a skip is, how to run one

Three more modes of the divsqrt soak (host/tools/divsqrt_soak.c, the section "Hard cases":
`div32-hard`, `div64-hard`, `sqrt64-hard`) take `<lo> <hi> <attribute>` over a deterministic **index
space** of constructed operands and call the same batch kernel as the random modes of the
operation, so the oracle (the host CPU's own division and square root in the prevailing rounding
mode), the flag discipline and the sabotage control are theirs. They exist because a sampler cannot
reach what they hold: a quotient of two p-bit significands comes within 2^-p of an ulp of a rounding
boundary with probability about ln 2 / 2^(p-1) a draw, 8 x 10^-8 at fp32 and 1.5 x 10^-16 at fp64
(a stress-run item of 1.45 x 10^10 draws expects 2.2 x 10^-6 of them: docs/studies/SWP-A-coverage.md
section 4.2). One modular inverse builds one: for an odd divisor `my` the dividend with
`mx 2^k = +-1 (mod my)` is the closest a quotient can come to a midpoint (k = p) or to a
representable number (k = p - 1); square root has the same structure in the squares of odd integers.
A division that computes 40 guard bits and ignores the remainder fails on 25 per cent of the
closest-approach-to-a-midpoint cases the generator builds at fp64 and on none of as many random
draws; and a copy of the library
whose guard test is blind to a quotient that close to a midpoint fails 485,236 of the 1.9 million
cases of one slice of `div64-hard` under rne, while 2,000,000 of the random mode's draws pass it
(MEASURED, `hw/test_divsqrt_hard.py`, plants).

**The space.** A mode is a list of segments, smallest first (`divsqrt-soak hard-space MODE` prints
it). An index belongs to one segment and makes **k slots**: for division the four sign
combinations of one operand pair (slot s is the sign of a plus twice the sign of b), for square
root one. Inside a segment an index is 4j + v: j picks the base and v one of four variants of it.

| segment | what its indices build | div32-hard | div64-hard | sqrt64-hard |
|---|---|---|---|---|
| F3a | ties in the subnormal strip: b = 2^(s+3) and an a for which the exact quotient is an odd multiple of half the smallest subnormal, s = 1..p places below the smallest normal, in four bit patterns | 96 | 212 | - |
| F3b | powers of two across the quotient exponent's whole range (every strip, the core, overflow): b = 2^m with a = 2 - ulp or 1.5, and a = 2^m with b = 2 - ulp or 1.5 | 2,028 | 16,364 | - |
| F2 | b = 1 + k ulp and b = 1 - k ulp, k = 1..65,536, with a = 1.0 or 2 - ulp; j = 0, a = 1.0, b = 1 - ulp is the family that broke the Markstein finish | 262,144 | 262,144 | - |
| F1 | exact quotients a = ob oq, b = ob (odd parts below 2^((p-1)/2), keyed), in four exponent classes, one of them with an exact subnormal quotient | 4,194,304 | 4,194,304 | - |
| F0 | closest approach to a midpoint or a representable number, above or below, for odd divisors from the bottom of the binade (A), from the top (D) and, at fp64, keyed with the top 12 fraction bits taking every value once in 4,096 divisors (K) | 8,388,608 + 8,388,608 | 8,388,608 + 8,388,608 + 268,435,456 | - |
| S1 | sqrt(1 + k ulp) for odd k, and x = 4 - k ulp, 1 - k ulp, 4^255 (1 + k ulp) | - | - | 262,144 |
| S0 | the inputs nearest the squares of midpoints: the 2-adic square roots of rho = 8m + 1 (1, -7, 9, -15, ...) in both binade parities, at distance |rho| 2^-2p of the root's grid | - | - | 4,194,304 |
| **indices** (k) | | **21,235,788** (4) | **289,685,696** (4) | **4,456,448** (1) |

**What a skip is.** An index whose construction yields no operand pair; all k of its slots are
skipped. Only two families skip: F0, for a divisor that has no dividend at |N| = 1 for the index's
target and sign in either quotient binade (at fp64 30.7 per cent of the keyed stream, 1 - ln 2
for uniform divisors; 4 slots of 33.5 million within 2^22 ulps of 1.0 and exactly half within 2^22
ulps of 2.0), and S0, for a rho with no root in range for the index's parity (64.6 per cent). The whole spaces, counted by `hard-count` (the builders
alone; MEASURED): div32-hard 64,346,592 cases and 20,596,560 skipped slots, div64-hard
812,489,184 and 346,253,600, sqrt64-hard 1,745,752 and 2,710,696. (The prototype's window
mx >= my skips about 61 per cent of odd divisors; these modes use the sampler's convention, the
dividend doubled when it is below the divisor, which reaches both quotient binades.)

**What it must print.** The first line of the log is `soaking the DEVICE backend: <xclbin>` (or
`soaking the software backend`); the last is the exhaustive modes' line,

    div64-hard rne: 812489184 cases, 0 value mismatches, 0 flag mismatches, 289685696 encodings, 346253600 skipped

and exit status 0. E counts **indices** (the clause's word is the driver's), every (index, slot)
is compared, a case, or skipped, so cases + S = k x E; the cases are not a function of the slice's
bounds, and `divsqrt-soak hard-count MODE LO HI` prints a slice's cases and skipped slots by
segment, then the longest run of consecutive skipped indices, without the library (60 s for the
whole of div64-hard). A slice of 64 or more indices in which every index skipped is **refused by
name** (exit 2, no verdict line): unlike `cvtto32-all`'s all-NaN slices, which are a pass, a run
of skips that long here means the construction is broken - the longest run in the whole spaces is
2 (div32-hard and div64-hard) and 5 (sqrt64-hard; MEASURED by `hard-count`), so a correct tool
never meets the rule. Refused by name too: a range that is empty, reversed, past the space or not a number,
rmm under division (the ties of division are in the subnormal strip, which has no host rounding
mode), and a build whose compiler has no 128-bit integer. Every F0 case is checked in exact
128-bit integers as it is built (|N| = 1 and its sign) and every S0 case (u^2 = rho mod 2^s); a
failure refuses the run, by name. A disagreement lists operands (`MISMATCH ... a=0x... b=0x...`).

**What is proved about the cases, and what is not.** `python/hardcases.py verify` decodes the
operand bits and classifies each case in exact integers (Fractions and isqrt), sharing nothing with
the builders: F0 has |N| = 1 and the designed sign (and its skips are genuine, by a second
construction), S0 has its nearest input rho 2^-2p from the square of a midpoint, S1 has |D| = k^2,
F1's quotient is exact, F2's operands are the designed ones, F3a's quotient is a half-integer of the
subnormal grid s places down, F3b's operand exponents differ by the designed quotient exponent and
its binade is exact. F2 and F3b are structural: their distance to a boundary is computed and not
claimed small. ARGUED at fp64, MEASURED by exhaustion at small precision
(`python/tests/test_hardcases.py`: F0 over every odd divisor and dividend at p = 9 and 10, S0 over
every input of [1, 4) at p = 10, 12 and 14): that F0 builds every dividend at |N| = 1 and only
those, that S0 lists every input at a given distance (the roots of u^2 = rho mod 2^s are four, which
the construction takes whole), and that sqrt(1 + ulp) and the predecessor of 4 are the only inputs
at distance 1 (the next distances are 7, 9, 15, 17, 23, as at fp32 in the study).

| item (per attribute) | indices | k | cases | one quad (COMPUTED) | software backend, one process (MEASURED) |
|---|---|---|---|---|---|
| `div32-hard` (four) | 21,235,788 | 4 | 64,346,592 | 8.0 to 8.5 s | rne run whole: 259 s (0.25 M cases a second), 0 mismatches |
| `div64-hard` (four) | 289,685,696 | 4 | 812,489,184 | 132 to 137 s | slices: the four structural segments (4,473,024 indices) 72 s under rne; the first 2^20 indices of F0A, F0D and F0K 9 to 21 s each under all four; the whole item about an hour a process (COMPUTED from 0.20 to 0.25 M cases a second) |
| `sqrt64-hard` (five) | 4,456,448 | 1 | 1,745,752 | 0.3 s | whole: 9.7 to 11.7 s under each of the five |

The quad figures are cases over four times the median rate of a tile job on the quad in the
2026-10-16 to 19 run (docs/studies/swp-a/stress-final-item-rates.txt: div32 1.90 to 2.02, div64 1.49
to 1.54, sqrt64 1.52 to 1.54 M cases a second a tile; sqrt64 under rmm has no row there and takes rne's),
four tiles on four quarters of the space: all thirteen items in 9.6 minutes. The generator's cost is
not in them (60 s for the builders over the whole of div64-hard, against about 530 s of a tile).
All three reach the tile, as the random modes do: `cft_div` and `cft_sqrt` are composed of tile
passes.

By hand, on a CPU's software backend (it needs only `make -C host divsqrt-soak`, XRT=0, on a 64-bit
Linux) or on the card (the quad's xclbin built with XRT=1, one process a tile, as for the items above):

    host/divsqrt-soak hard-space div64-hard
    nice -n 10 host/divsqrt-soak div64-hard 0 289685696 rne
    N=289685696; JOB=div64-hard; ATTR=rne
    for k in 0 1 2 3; do
      CFT_SOAK_ARTIFACT=$IMG CFT_XRT_TILES=$((k + 1)) nice -n 10 host/divsqrt-soak $JOB \
          $((N * k / 4)) $((N * (k + 1) / 4)) $ATTR > $JOB-$ATTR-q$k.log 2>&1 &
    done; wait; grep -h " cases," $JOB-$ATTR-q?.log

The four lines' encodings add up to N and their skipped slots to the whole space's (346,253,600
for div64-hard). The stress driver does not name these items yet (`hw/card_stress_lib.py` carries
the six exhaustive conversion and scaleB modes, not these); each item is `tile`, k above, the
space is not 2^32, and its cases are held to cases + S = k x E.

Known limits. Flags are compared per batch, as in every mode here: a flag the library drops on one
lane among others that raise it is not seen. The families are contiguous segments, so a batch is
nearly always one family, and F1's batches are the one family whose flags are all clear (a spurious
inexact there is seen). Operands are positive normal magnitudes in the four sign combinations;
zeros, infinities, NaNs and subnormal operands stay with the random modes' bands. F0 is built at
one exponent pair (both operands in [1, 2)), F1 and F3 at others with their own significands: the
product of structure and exponent is not swept (the scale lemma of the study, 4.3, argued at
p = 24 and 53), and a closest approach to a midpoint of the subnormal grid that is not a tie is
not built. The fp64 keyed stream is 2^26 of 2^51 odd divisors. The oracle is the host's, so
division under rmm is not checked.

The tool's side is tested by `python3 hw/test_divsqrt_hard.py --baseline-tree DIR` (POSIX with
make and a C compiler, about four minutes, a minute of it the three whole spaces counted): the
segment tables and 53,104 operand lines against `python/hardcases.py`, the whole-space figures
above, every mode and attribute over 173 slices of the segments' starts, ends and boundaries and
312 across the spaces (each also accepted by the driver's own `parse_soak`), the refusals, a
sabotage control for each mode, the plants (a construction off by one, a slice one encoding or one
skipped slot short, a mode that skips every index, a library whose guard test is blind to the
closest approach to a midpoint, a build with no 128-bit integer, the 40-guard-bit division), and
the random and exhaustive modes of another tree's tool (`git archive REV host | tar -x -C DIR`)
compared byte for byte; `python/tests/test_hardcases.py` holds the generator and the golden
model's answers on its cases to an exact arbiter, and the builders to exhaustion at small precision.

### The soak at a larger pass size (added 2026-10-20): how to build it, what it prints, what it gives up

**Why.** `cft_div`, `cft_sqrt`, `cft_rint` and `cft_scaleb` are composed of `cft_run` passes over
chunks of at most `CFT_CHUNK` elements (host/include/cft_config.h, 4096), and each soak tool hands
the library `BATCH` operands a call (4096 too: host/tools/divsqrt_soak.c, host/tools/clause5_soak.c).
On the card a pass is a staged run, so the passes set the rate. Logan, 2026-10-20: "Build time
override for now with future plans to make adjustable more easily" (docs/ROADMAP.md, "Decided
2026-10-20"). This is the override; the adjustable form is not built. MEASURED, the lead's,
2026-10-20 (`Data/runs/2026-10-12-math-round/box/batch-chunk/`, which is not in the repository):
on one tile of the quad at revision 8, BATCH and CFT_CHUNK both 16384 ran rint32 2.81 times as
fast as at 4096, rint64 2.00, scaleb32 1.25 and division and square root 1.13 to 1.22, with 0
mismatches; BATCH alone at 16384 changed nothing, since each call was still four passes.

**Build it.**

    make -C host SOAK_CHUNK=16384 soak-chunk
    make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt SOAK_CHUNK=16384 soak-chunk   # to open an artifact

makes `divsqrt-soak-c16384` and `clause5-soak-c16384` (`.exe` where the platform has it). Each is
compiled `-DCFT_CHUNK=16384 -DBATCH=16384` and linked against `libcft-c16384.a`, a library of its
own: the library's sources compiled `-DCFT_CHUNK=16384` into the directory `soak-c16384/`. XRT=1,
XRT_ROOT and `C5DEFS` act as they do for `divsqrt-soak` and `clause5-soak`. **The default
`libcft.a`, `divsqrt-soak`, `clause5-soak` and every other tool are not touched**: nothing here is
a prerequisite of `all`, sizes sit side by side, and `make -C host clean` removes the products of
every size the build allows (the 16 values below), each by its exact name and only when it is the
right kind of thing: a binary or archive when it is a regular file and no symlink, an object
directory when it is a directory and no symlink. Anything else of those names stays: a symlink to
anything, a dangling symlink, a FIFO, a directory named like a binary, a file named like an object
directory (`soak-c8192`). A `divsqrt-soak-c16384.log` or a `soak-c16384-notes/` of yours stays too.
A regular file with a product's exact name is the build's to remove, which is what `clean` is for.
(The first version used globs, `divsqrt-soak-c[0-9]*`, which took the `.log`; the second removed
the file `soak-c8192` and stopped on a directory with a binary's name; the third excluded only
directories and took a symlink, a dangling symlink and a FIFO; verifier VCK found each.)
.gitignore ignores the binaries and the directory by SHAPE, the name and exactly four
or five digits and nothing after them, so a build leaves the next build id `untracked=none`. A
shape is wider than the list: a four- or five-digit name that is no allowed size
(`divsqrt-soak-c1234`, `divsqrt-soak-c12345`) is ignored by these patterns too, and `clean` leaves
it. A `.log` or an archive of that name is ignored all the same, by the older blanket `*.log` and
`host/*.a`, and not by these patterns. **Refused by name**,
at parse time, when one of these goals is asked
for: no `SOAK_CHUNK` or an empty one; a value that is not one plain decimal number that is a
positive multiple of 4096 up to 65536 (`4097`, `0x4000`, `016384`, `65537` and `16384 8192` are
refused, each message giving the value); and a goal that names another size than `SOAK_CHUNK`
does. The 65536 is a bound this build sets, not a limit found in the library (READ: the scratch is
`malloc` of `CFT_CHUNK` times the element size, host/src/divsqrt.c and host/src/clause5.c; no
index there is narrower than `size_t`; the only check on `CFT_CHUNK` is that it is at least 1,
host/include/cft_config.h; the remote frame cap is 1 GiB and the kernel's `n` argument is 64 bits).
Nothing above 16384 has been run on the card.

**What the tool says.** When BATCH or CFT_CHUNK is not 4096 a tool prints a second line on stderr
after its `soaking the ... backend` line: `soaking with BATCH 16384 and CFT_CHUNK 16384 (the
defaults are 4096)`. The backend line is untouched, because hw/card_stress_lib.py matches it with
anchors. A default build compiles the new line out and prints nothing more, and its object file
is byte for byte the one built before (MEASURED, gcc 11.4 with the Makefile's flags). Both numbers
are the TOOL's own compile-time values, so they are the library's pass size only when the two
match, which these targets guarantee; a hand build with `-DBATCH=16384` alone prints both and is
the lead's first experiment, the one that changed nothing.

**What it gives up.** Read before comparing a chunked run with a default one.

1. **Flags are compared per batch** (the OR over a call; the tools' headers), so a flag defect on
   one operand among many that raise the same flag is hidden, and a larger batch is more operands
   to hide among. With p the share of operands that raise a flag and independence assumed, a
   batch of n has another operand raising it with probability 1 - (1 - p)^(n - 1) (COMPUTED): for
   p = 1/10,000 that is 34% at 4096 and 81% at 16384, for p = 1/100,000 4% and 15%. Parcel CL
   measured the effect itself (docs/VALIDATION.md, its entry: a dropped INEXACT that passes in
   batches and fails alone). **The lane-exact class items stay as they are**: the `*-class` modes
   run an operand a call (`CLS_BATCH`, 1) whatever BATCH is. A chunked soak is for throughput over
   the value comparison, and the per-batch flag comparison is weaker in it.
2. **A random scaleB slice's number of cases follows BATCH.** In `scaleb32` and `scaleb64`
   `count` is cases and a batch takes n = min(count, BATCH) operands against the list's 17 or 27
   exponents, so the cases of a slice are `count` rounded up by whole batches: `scaleb32 100000
   5 rne` ran 139,264 cases at 4096 and 278,528 at 16384 (MEASURED). A count of 17 (or 27) times
   32,768 is the same at both. Every other random mode takes `count` as operands.
3. **The same seed can mean another operand set in `cvtfrom32` and `cvtfrom64`** (random: they draw
   a full batch for each of four source types, clause5_soak.c; READ, not run; the case counts do
   agree). The other modes draw the same sequence at any BATCH.
4. **A call of a few operands is slower.** MEASURED (200,000 calls, two repetitions): `cft_rint`
   at fp64 over 1 operand 767 and 837 ns at 4096, 4,320 and 5,620 ns at 16384; `cft_div` over 1
   operand 16.0 and 18.6 microseconds against 21.3 and 21.8; `strace -c` counts `brk` calls at
   4,003 against 21,001 over 4,000 rint and 1,000 div calls (each composed call mallocs its
   scratch; READ, clause5.c's rint takes three buffers of CHUNK x 8 bytes and one of CHUNK bytes
   at fp64, 410 KB a call at 16384 and 102 KB at 4096). On the card a call is several passes of
   about 260 microseconds (BELIEVED), so this is under 1% there; on the software backend CL's
   class modes took 4.5 s at the default and 11.6 s with the chunked tools.
5. **A sabotaged run's counts follow the calls.** `CFT_SOAK_SABOTAGE=1` flips the first result of
   every library call, so the value-mismatch count of a mode that checks a call whole is about 3.8
   times smaller at 16384 (median over 73 of the sweep's 90 items), and in the modes that re-run a
   failing batch an element at a time it is larger (11 items: a batch whose first result is a NaN
   is not seen to fail, and the larger batch loses fewer of them). **Both sizes FAIL in every
   one** (118 of 118), and the flag-mismatch count is 0 at both in every one: the sabotage touches
   no flag, so it cannot show item 1.

**Evidence** (MEASURED, software backend, WSL cft2204, niced): the driver's 90 sweep items at two
slices each, HC's three hard-case modes under every attribute at the start of every segment and
the end and middle of the long ones, and CL's five class modes over their whole spaces and a
third of them, 352 comparisons
of a default build and a `SOAK_CHUNK=16384` one: **352 of 352 verdict lines identical** (cases,
value and flag mismatches, encodings, skipped; all with 0 mismatches), stdout byte for byte, and
the chunked stderr the default's with the one line added; and 118 sabotaged comparisons that all
fail (above). `python3 host/tests/soak_chunk_check.py --baseline-tree DIR` holds the build: the
refusals by name, the dry run of every recipe, the real build at 16384 and 8192, a probe linked
against each archive with `--wrap=cft_run` that finds the pass size the library really has
(largest pass 16384, 8192 and 4096, for division, square root, rint and scaleB), the stderr
lines, `clean` (the products of all 16 sizes, a synthetic set beside the tree's own build, gone; names
that only begin like a product, a `.log`, a `.txt`, `-old`, `-notes/`, a four- or five-digit name of no
allowed size, a file named like an object directory, a directory named like a binary, and of the
allowed sizes a symlink to a file, a dangling symlink, a FIFO and a symlink to a directory, still
there),
`.gitignore` (every product ignored, and no pattern of this build taking a name that only begins like
one, except the shape itself: the tool's name and four or five digits, which is ignored whether or not
the size is allowed), the default tools' output and objects unchanged against a baseline, and
thirteen planted breakages each caught by the check written for it, the earlier globs, the unguarded
`rm -rf` and `rm -f`, the directories-only test `[ ! -d ]` and the missing symlink test put back
among them, in `clean` and in `.gitignore`. **Not done:** the stress driver
does not use these tools yet (hw/ is parcel DR3's), and the pass size is not adjustable at run
time.

### Failure policy, processes, and what it guarantees

- **A failing leg** keeps its whole log, says so in its record, and the run goes on. So does an
  unexpected exception in the driver itself: it is recorded as a `driver_error` event with its
  traceback, what the run started is terminated, and the next cycle begins; the fifth in a row
  stops the run, by name. `cft-resident` and `cft-selftest` serve optional legs: if either is not
  built or not XRT-linked, its leg is skipped by name with that reason, and the run goes on.
- **The card not answering** - a no-device open, a tile left running ("already running when this
  handle opens it"), or a hang past the leg's timeout - waits `--retry-pause` (120 s) and retries
  the leg once; the second consecutive time it waits twice as long, opens **another image and
  comes back** (two `dt-i` legs recorded as `recovery`) and goes on to the next leg; after
  `--max-card-failures` (6) in a row the
  driver stops, writes `STOPPED.txt` and leaves the card idle. A leg that reached a verdict on the
  card ends the run of failures; `api-test`, which needs no card, neither ends nor extends it.
- **Timeouts and processes.** Every leg runs under GNU `timeout --signal=TERM -k 60` and
  `nice -n 10` (POSIX), with a Python-side backstop; it signals only the process groups it
  started, by PID, never by a pattern, and ends with none of its children alive.
- **The guard** refuses to start, and waits between legs (up to `--guard-wait-max`), while another
  process uses the card: a tool that opens an xclbin (`device-test`, `hw/card-segrun.sh`, any
  `cft-*`, ...; not `hw/verify-image.sh`, which only reads an image) with an xclbin argument, `acceptance.py`, `seq_check.py` or `cft-segrun` with a
  `--device` that is not `sw`, a soak with `CFT_SOAK_ARTIFACT` in its environment, or `xbutil`
  or `xrt-smi` running `program`, `reset` or `validate`. It detects, never kills. `verify/run.sh`
  runs use no card and are allowed; the run records `beside` when it sees one.
- **The CPU share** is small by design: one battery leg at a time (its own host work, mostly
  single-process Python) and, in a sweep, at most one soak process a tile - four on the quad, one
  on a single image, so 4 of the box's 36 threads at most, about 11 per cent (`--soak-jobs N`
  lowers it) - all under `nice -n 10`; the one-time build uses `--build-jobs` (4). The box's
  other runs (a gate, census stages) are CPU-only and share what is left.
- **The disk**: passing legs' logs are gzipped; the driver checks the free space of its output
  directory and of `/data` before every leg and stops cleanly below `--disk-floor-gb` (5).
- **The deadline** is read between legs: nothing starts after it, and a leg whose estimate would
  end more than `--deadline-grace` (900 s) past it is skipped by name; sweep slices are sized to
  the time left. A leg already running ends on its own.
- **Telemetry**: `xrt-smi` or `xbutil examine -d 0000:02:00.1 -r electrical|thermal|mechanical`
  (each report tries one tool and then the other, and remembers which answered), as JSON where
  it will, else as text, on a timer (300 s) and between legs, with the host's load, memory and
  free disk. **A sample is taken one at a time** (since 2026-10-20): the timer's thread and the
  run's own calls (before a cycle, after its battery, at the end) hold one lock from the first
  examine call to the append, so the records are in the order the readings were taken. Before,
  two overlapping samples could append in the other order; the dry-run test's telemetry check saw
  one pair swapped, once, on a busy desktop (docs/VALIDATION.md, parcel EX). **What the lock can
  cost**: a call that arrives while a sample is in flight waits for it, then takes its own. Every
  examine call is killed at `--telemetry-timeout` (60 s), and a sample is at most 12 calls (three
  reports, two tools, JSON and text), so the wait is at most 720 s, and only if every call hangs;
  a sample that answers takes about a second (BELIEVED: the stand-in's, not timed on the card). A
  run that is stopping (STOP, a signal, the deadline) drops the timer's sample at its next
  examine call, so the run's `end` sample waits for at most one call more: stopping takes at most
  one sample and one timeout longer than before, worst alignment, all calls hung. MEASURED in the
  dry run, every examine call hung and
  `--telemetry-timeout 2`, STOP touched during the first sample: STOP to end 8.4 s without the
  lock (the first two samples overlapped), 11.9 s with the lock alone and 9.8 s with the lock and
  that rule; each hung call was killed at its timeout and none was left running
  (`hw/test_card_stress.py`, group `telemetry`). **The JSON's shape is BELIEVED, not read from a card**: numbers are kept
  under whatever labels their neighbours give them, and a sample with no readable number is
  recorded as such, with its raw text, never as a reading. Add `platform` to
  `--telemetry-reports` for the clocks; it has failed in `xrt-smi` before (docs/VALIDATION.md,
  2026-09-08).

**It guarantees**: the build is asserted (the tree's commit and content, every tool linked to XRT,
the build id, each image against its SHA256SUMS and the hash it was given) before the card is
touched; a stop never comes mid-leg; a leg that fails, hangs or loses the card is recorded and the
run goes on or stops by the policy above; and every count in a record is read from a line the
tool printed. **It does not guarantee**: that the run lasts to Monday (a card that stops
answering, a disk below the floor, a moved tree or a build failure end it, by design, with the
reason written); that a card the tools refuse is distinguishable from one that has failed (both
are `no_device`); that a leg killed at its timeout leaves its tile healthy (it may not; the
recovery is a reload, and the run records what happened); that the guard sees a card user it has
no name for; anything about the card's rate or temperature (neither had been measured when this
was written); or that a sweep disagrees only when the tile is wrong (the oracle is the host CPU;
a disagreement is kept with its operands, and re-running the slice on the software backend,
which the driver does not do, is the next step).

## Owed to the next card day (added 2026-10-19): the math library's routine entries in the revision-8 set

M1's build, item 6 (docs/ROADMAP.md, "The math library: experiment E1, then M1's build and M2 to
M4"): STATUS[6] and the lane byte on a structured argument, and a routine case in the acceptance
sets. Parcel MA built the software side (docs/VALIDATION.md, 2026-10-19): `programs/acceptance.py
--set rev8` holds six routine entries after its ten workloads - the committed Lotka-Volterra
(exp), diode (expm1, log1p) and culture (exp2, log, log2) references at fp64 and fp256, each with
a structured lane on every tile that the routine marks. The driver's docstring ("The routine
entries") is the definition. **Nothing here has touched the card or amd-arc-box.**

Four facts that shape the commands:
- **Quad only.** The rule puts all six on `u50-rev8-quad`, read from each image's own words
  (1,537 to 3,642 instructions, 256 scratch slots declared, no R21). `--target u50-rev8-deep`
  selects none of them: the driver prints `FAIL  the set: no entry of --only on u50-rev8-deep` and
  exits 1 (MEASURED on the software backend), and `--target u50-rev8` does the same (READ: the
  filter is the entry's target). rev8a and rev8d have no routine entry, and the set gives an entry
  one target.
- **The stress run runs them since 2026-10-20** (the revision-8 leg, above): `hw/card_stress.py`'s
  table and its test now hold the ten workloads and the six, and the leg names the tree's own libcft with `--lib` for them. Of the box that asks nothing the driver's build does not already
  make: host/libcft.so (XRT=1, ldd-checked), `cft-segrun` and `cft-audit`, and the six's committed
  files, which a checkout has.
- **The lane byte needs libcft's shared library.** A version-1 certificate carries no per-lane
  block: cft-segrun asks the library for R23's byte a lane at format version 2 only, which refuses
  a segment that marks a lane unless an image replays it. So the driver's *mark probe* re-runs
  each segment from its certified start through libcft by ctypes (`--lib`), on the same device and
  image at the same depth, and asks for the block. The library must be the XRT-linked one: built
  without `XRT=1`, `cft_open` of an xclbin answers `no such device`.
- **The record is the software backend's.** The card must reproduce it bit for bit: every
  boundary, the flag words [29, 24, 24, 24], STATUS [64, 0, 0, 0], which lanes carry bit 7 (the
  four structured ones, byte 0x90, segment 0 only) and each segment's block hash. A tile that does
  not mark, marks another lane, or raises another flag fails by name.

On amd-arc-box, from the root of the branch's checkout (no other card user: a manual run is a
card user, and the stress run's guard sees it):

    source /opt/xilinx/xrt/setup.sh
    make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt cft-segrun cft-audit libcft.so
    ldd host/cft-segrun | grep xrt        # libxrt_coreutil
    ldd host/libcft.so  | grep xrt        # the same; none means an XRT=0 build
    X=$HOME/cardday-rev8q/cft_hw_quad.xclbin
    sha256sum $X                          # 4f9921a25af65444abc5c267fff1117a8e14abbc16a75de643e43c9dbf6ef53b
    python3 programs/acceptance.py --set rev8 --legs set --device $X --target u50-rev8-quad \
        --segrun host/cft-segrun --audit host/cft-audit --lib host/libcft.so \
        --only lotkavolterra-rk4-tangent-fp64,lotkavolterra-rk4-tangent-fp256,diode-rk4-tangent-fp64,diode-rk4-tangent-fp256,culture-rk4-tangent-fp64,culture-rk4-tangent-fp256 \
        > routines-rev8q.log 2>&1; echo rc=$?

**What it must print** (the software backend's run, MEASURED; the card's differences are marked):
- exit 0, and last, `acceptance rev8: 6 of 6 PASS on $X as u50-rev8-quad (set); 118 checks ok, 0
  failed, N s`. The software backend counts 117: the marks' controls add one on a card, the
  planted image (COMPUTED from the code, not run on a card). `N` was BELIEVED 150 to 300 (below); on the
  card it was 57 (MEASURED, the lead's, rev8q, 2026-10-19: 118 checks, as predicted).
- six `PASS` lines, each `... on xrt, flags [29, 24, 24, 24], status [64, 0, 0, 0]; every digest
  the set's, cft-audit accepts in full, no golden audit here (seq.py's cost), the spot check holds,
  4 structured lanes mark (bit 7, STATUS[6])`, and per entry fourteen `ok` lines, among them (the
  software backend's wording, a card's `xrt` and `device-tiles 4`):
  - `the rule's image is u50-rev8-quad, read from the image's own words`
  - `the certificate reads; backend xrt, device-xclbin 4f9921a25af65444, device-tiles 4, scratch
    depth 4096` and `the device is u50-rev8-quad's tiles and depth`
  - `the mark probe opened the certificate's device: xrt, 4 tiles, 4096 slots a lane, image
    4f9921a25af65444`
  - `the probe's 4 segments, re-run from their certified starts, end where the certificate's
    boundaries do, bit for bit, with its flag words and STATUS`
  - `R23's identities hold on every segment's block`
  - `the structured lanes mark: lanes [3, 67, 131, 195] carry bit 7 of their byte (0x90) in segment
    0 and its STATUS 0x40 carries STATUS[6]; bit 7 is set on no other lane of any segment,
    STATUS[6] in no other segment` (lanes [3, 19, 35, 51] at fp256)
  - `every boundary hash, flag word and STATUS is the set's (5 boundaries, flags [29, 24, 24, 24]),
    and so are the marked lanes with their bytes and the 4 per-lane blocks' hashes`
  - `cft-audit accepts it in full`, `the golden spot check`, `the golden mark check - segment 0`
- then the controls, once: 16 `ok` lines (the set's), then the marks' controls, 17 (18 on a
  card), none `FAIL`.
- A failure names its check. A tile that does not mark is `the structured lanes mark: lane L (tile
  T ...) has byte 0x10 in segment 0, without bit 7`; a STATUS that disagrees with the
  certificate's, a flag word or an end state that does is under `the probe's 4 segments ... end
  where the certificate's boundaries do`, and one that disagrees with the blocks under `R23's
  identities`; a mark the record does not have is under `every boundary hash, flag word and
  STATUS is the set's`, by lane; a library built without XRT is `the mark probe could not open
  ...: no such device`.

**Time.** The software backend took 113 s for the six at the stage's arguments on the desktop
(niced, shared with other sessions; 67 s in a quieter hour; MEASURED). On the box: BELIEVED 150 to
300 s, COMPUTED from the desktop's 67 to 113 s scaled by the box's pace against the desktop's (535
s against 375 s for the acceptance stage, docs/VERIFICATION.md), plus the card's opens -
cft-segrun's and the probe's, one each an entry - against 353 s for nine workloads on the quad
(2026-10-12), 39 s an entry, the same host-side work. The card has since run them: 57 s for the six
(MEASURED, the lead's, rev8q, 2026-10-19, with the box's stage runs beside it); a card run of
a segment (256 lanes, ten steps) is BELIEVED well under a second.

**Optional, the same day:**
- `--golden all` on the same command adds the golden audit over every segment of every entry, on
  seq.py, and holds cft-audit's verdict to it line for line. It accepts the marked segment 0
  (MEASURED on the software backend, the desktop niced and shared, in three runs of under ten
  minutes each): the audit over the four segments took 113 s for Lotka-Volterra at fp64 and 47 s at
  fp256, 142 s and 44 s for the diodes, 156 s and 48 s for the culture, 550 s for the six - the same
  host-side work on the box, BELIEVED about as long, and 530 s on the card's run (MEASURED, the lead's,
  rev8q, 2026-10-19: "6 of 6 PASS ... 124 checks ok, 0 failed"). Not in the default run, by seq.py's cost.
- The remade record on the box, a determinism check of the record across platforms (Windows made
  it): `python3 programs/acceptance.py --set rev8 --write --images /data/card-stress-rev8images`
  on the software backend (no `--device`), then `git diff --stat programs/acceptance-rev8.json`
  must print nothing. All sixteen entries; the desktop took 558 s, the box BELIEVED 10 to 15 minutes.
- **Not on this day:** rev8d (the command above selects no entry there).

## What to record

The manifest format already exists; the run record should match it in
spirit - enough to replay, not enough to be a chore.

- host, OS, XRT version, shell version, card serial
- xclbin sha256 (not its filename). Since 2026-09-28 device-test prints
  it from the library (`image: sha256 ...`, `cft_get_image_id`), and
  `hw/card-identity.sh` holds that to `sha256sum`
- the libcft build device-test prints first (`libcft build ...`)
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
  `CFT_ERR_BUS_FAULT` rather than a twenty-minute wait. That was the
  elementwise engine's; a sequencer run kept the hang until revision 8's
  abort (docs/SEQUENCER.md, "Revision 8 in the tile"), and a tile
  without it - every image built before revision 8 - still hangs on a
  short read burst in a program run.

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
