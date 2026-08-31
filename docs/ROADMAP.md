# Roadmap

Milestones end with something checkable, and no milestone depends on a
later one. The contract (docs/DETERMINISM.md) never changes shape -
later versions only widen what it covers.

## v0 - the spine (this repository, now)

One verified path from Python host intent to verified RTL results, and
the golden model that everything else is scored against.

- [x] Golden model: exact fp32/fp64/fp128/fp256 fma/add/sub/mul with
      flags, proven against native binary64, `math.fma`, mpmath, and
      hand-computed IEEE 754-2019 anchors (16 pytest gates).
- [x] Parameterized behavioural FMA core + fixed-latency pipe.
- [x] v0 engine: 8x fp32 lanes + 1x fp256 unit behind one CSR/AXI
      contract; ap_ctrl_hs; sticky FLAGS CSR.
- [x] cocotb benches: streamed unit vectors (fp32, fp256) and the
      full-kernel AXI end-to-end, all against the golden model.
      First full run 2026-08-28: 4000 + 1300 vectors and 7 kernel runs
      bit-exact, flags included, zero RTL fixes required after the
      compile-clean pass.
- [x] Vitis packaging collateral (kernel.xml, package_xo script, HBM
      link.cfg) and the pyxrt host example.
- [x] Conformance vector emitter (vectors/gen_vectors.py).

### Independent review (2026-08-29)

Two adversarial reviews, one on the numeric datapath and one on the
control/protocol logic, of code that already passed 57,000 vectors and
26 kernel runs. What they found is a useful map of where testbenches
are structurally blind:

- The **datapath was clean** - confirmed by exhaustive transliteration
  (23.6M operand triples x every rounding attribute on structurally
  faithful small formats, plus tree exactness for every P in 2..384).
  What it did surface: two elaboration guards that were
  simulation-only and so guarded nothing in synthesis, three
  load-bearing comments whose stated *reasons* were false, and a
  period-5 blind spot in the bench's rounding-attribute ordering
  against a 15-stage pipe.
- The **control logic held one real bug**: the CSR sampled the AXI
  write data one cycle after the handshake. Invisible to any master
  that waits for the write response before moving on, which is both
  of ours.

The lesson worth keeping: a cooperative testbench and a cooperative
memory model cannot find bugs in *when* a slave samples, in what a
design does with an error response, or in a parameter combination
nobody instantiates. Those need either a hostile driver or a reader.

## v0.x - hardware bring-up (needs the Vitis box + card)

Gates in docs/BRINGUP.md, in order: package_xo validates; hw_emu run
of the kernel test pattern; timing closure at a reduced clock; first
on-card `vector_fma.py` run bit-exact against the golden model; then
the same at every N and both precisions, plus flags.

**Done when:** the card reproduces `vectors/out/*.jsonl` exactly, and
the run is recorded (platform, XRT, tool versions, xclbin hash) the
way atlas-darkroom records a census.

## v1 - the fractured array and a real engine

- [x] **The pipelined core (2026-08-29):** 15-stage cft_fpfma_pipe
      with a structurally staged multiplier (24-bit chunk columns +
      four registered tree levels). Measured OOC on xcu50:
      fp32 ~232 MHz (3.6x v0), fp256 ~148 MHz (10.5x v0), DSPs down
      196->140, full suite bit-exact, Yosys-clean. Card-day kernel
      clock rises 10 -> ~100 MHz. Remaining nanoseconds live in the
      DSP column cascades (split columns, +1 stage) and the round
      stage - chase when a platform clock demands it.
- [x] **fp64 and fp128 rungs (2026-08-29):** wired through
      the MODE precision field = 1, 2 as 4x/2x lane banks of the same
      pipe (the golden model and vector sets already covered them -
      hardware caught up to the contract, with zero core-RTL fixes:
      the chunked multiplier degenerates to 3/5 columns). Kernel
      VERSION 0x200 adds the CAPS CSR (0x4C, precision bitmask) and
      cft_krnl EN_FP64/EN_FP128/EN_FP256 trim parameters for
      constrained open-core targets. Suite grew to 4000+4000+2100+
      1300 unit vectors + 12 kernel AXI runs, all bit-exact. Measured
      OOC ladder on xcu50-2 (per lane): fp32 ~232 MHz 2.5k LUT
      2 DSP, fp64 ~201 MHz 4.7k LUT 9 DSP, fp128 ~188 MHz 11.5k LUT
      35 DSP, fp256 ~148 MHz 31k LUT 140 DSP. The whole kernel
      synthesized out of context (hw/synth_krnl_ooc.tcl) closes
      **WNS +3.62 ns at 100 MHz** at 95,537 LUT / 46,617 FF / 262
      DSP - ~11% and 4.4% of the VU35P, and confirmation that the
      engine, CSR and bank muxes add no critical path the per-core
      probe would have missed.
- The fused significand array: one physical multiplier serving
  1x fp256 / 2x fp128 / 4x fp64 / 8x fp32 per beat with
  mode-gated partial products (granule tiling study in
  docs/ARCHITECTURE.md), pipelined to platform clock - the chunked
  column decomposition above is exactly the granule structure the
  fracture needs, so this work is its foundation, and the four-bank
  version just landed is its behavioural spec: the array replaces
  the banks only when it produces identical bits.

  **Why this and not trimmed tiles (decided 2026-08-30).** Area
  measurement put three options on the table, and heterogeneous tiles
  looked cheapest: `EN_FP64`/`EN_FP128`/`EN_FP256` already exist, an
  fp32+fp64 tile is 45% smaller, and nine of them fit where four full
  tiles do. It is still the wrong trade for this product.

  **Every tile stays fp256-capable, and precision stays a runtime
  choice.** Scaling has to work on the largest supported rung, not on
  which bitstream happens to be loaded. A device whose CUs disagree
  about what they implement turns precision into a deployment
  question - the host must know which tiles can take an fp256 slice,
  the conformance argument has to cover a mixed device, and choosing
  fp256 becomes "reload the card" rather than "set MODE". One
  bitstream, identical tiles, `MODE[11:8]` selects the rung: that is
  what makes the software tier and the hardware tier the same
  contract rather than two.

  The fused array is the only option that buys area without buying
  that problem: measured 119.5k LUT/tile today, an estimated 91.7k
  fused, which is the difference between four tiles and six under the
  85% routing limit - with every tile still doing every format.

  Note DSPs are NOT the constraint on this part and will not become
  one: the quad sits at 17.7% of them against 69.2% of LUTs. Judge
  area work on LUTs. The fused array's 47% DSP saving is a bonus that
  buys nothing here, though it is decisive on the open-toolchain
  targets where an Artix-7 has 240 DSPs against this part's 5,952.

- **Dedicated-rung builds, as a performance option rather than an area
  one (noted 2026-08-30).** The decision above rejects heterogeneous
  tiles as the way to fit more compute. It does not reject a
  single-rung build as a way to go *faster* at one precision.

  A tile that implements only fp32 spends none of its silicon on the
  wide rungs, so the same die holds far more of them - and every lane
  is fp32, so peak fp32 throughput is several times a mixed device's.
  The same argument runs for a fp256-only tile, where the narrow banks
  are the dead weight. That is a genuinely different product from the
  general-purpose card: an image whose whole area is committed to one
  precision, for a workload known in advance to want exactly that.

  The parameters to build it already exist and are proven by the
  quarter-tile bench. What is missing is the host story - capability-
  aware partitioning, and a conformance argument for a device that
  answers CAPS with less than 0xF. Worth building once the general
  image is done and there is a workload measured well enough to say
  which rung to commit to.
- [x] **Streaming engine (2026-08-29):** cft_engine_stream - burst
      reads (16-beat, 4KB-safe) into per-stream FIFOs, one beat
      issued per cycle, index-order burst writes, read/compute/write
      overlapped. Measured in the kernel bench: ~4.4 cycles/beat net
      of CSR overhead - the shared-port bound (4 transfers/beat) -
      vs ~40 for the naive engine, which stays in rtl/ as the
      readable reference. Order of issue and writeback remains
      total, so the determinism argument is unchanged. Validated
      against the vendor's own interconnect models, not just our
      testbench: fp32 n=296 (37 beats = two full bursts + a ragged
      tail) is bit-exact through hw_emu.
- [x] **The host library, and multi-tile (2026-08-29):** libcft, about
      1,700 lines of C99 with no dependencies, plus an XRT backend that
      is the only C++ in the tree. The software backend replays 228,000
      conformance cases and agrees with the golden model on 213,000
      differential cases including the ones built to straddle its one
      structural difference, bounded operand alignment. GCC 13.3 on
      Ubuntu against glibc and GCC 16.1 on Windows against msvcrt print
      the same four checksums character for character, which is the
      product claim demonstrated on the cheapest hardware in the
      building.

      Multi-tile lives in the library because a four-CU bitstream is
      not four times one CU from the host's side: each CU's master is
      wired to its own HBM group, so there is no shared input array.
      The library gives each tile its own buffers and its own slice,
      ORs four sets of sticky registers into one answer, and callers
      never learn tiles exist.

      Tested with **no card present**, against a quad hw_emu image:
      `host/tests/device_test.c` runs the device and software backends
      side by side and compares bits and flags, then checks partition
      invariance - one call over n against a sequence of calls over
      slices of it - at sizes chosen to straddle beat and tile
      boundaries. The same binary is what runs on the card.

      A review pass over the untested backend found four
      silent-wrong-answer paths, all closed: a failed run left compute
      units active and the RTL silently drops a start issued to a busy
      CU, so a retry would have returned the previous run's output; the
      bus-fault register went unread when the flags were unreadable;
      flags_out was written as a clean zero for a word never read; and
      unreadable CAPS were replaced with a guess of maximum capability,
      which on a trimmed bitstream returns a buffer of zeros with clean
      flags. The last three shared a root - carrying on without the
      status registers - and the backend now refuses to open at all in
      that state.

      The same review found that `cft_conformance`, the published
      acceptance test for a new backend, replayed every case at n=1 and
      was therefore structurally incapable of failing on a partitioning
      bug. Each set is now replayed twice, and the array pass was
      verified by injecting a slice off-by-one.
- Engine knobs still open: multiple outstanding ARs, per-CU HBM
  pseudo-channel groups.
- [x] **Directed rounding attributes (2026-08-29):** all five of
      754-2019's attributes in the MODE rounding field (RISC-V frm),
      carried with each operation down the pipeline rather than
      latched per run - so one pass can produce both interval bounds.
      The mode-dependent rules came with it: the 7.4 overflow table
      (rtz never yields an infinity; the directed attributes only on
      their own side) and the 6.3 signed zero of an exact
      cancellation. Verified against the *definition*, not another
      implementation: test_rounding.py decodes each result to an
      exact rational and re-derives 754's requirement by rational
      floor division, then RTL matches the model across every
      attribute in the unit benches and end to end through the CSR -
      and through the real XRT stack in hw_emu, all five attributes
      bit-exact.
- [x] **In-shell frequency ceiling, and a negative result
      (2026-08-29):** four full platform links on the U50 shell, same
      RTL, same link config, only `--clock.freqHz` changed. 115 and
      145 MHz close (145 at WNS +0.055 ns); 175 fails at -0.562 ns
      with 2,753 failing endpoints. Read the **path delay, not the
      slack**: Vivado optimises until the asked clock is met and then
      stops, so the 145 MHz run reports 6.842 ns while the 175 MHz
      run - where the tool tried its hardest - reports 6.276 ns. The
      ceiling is that second number, **~159 MHz**.

      The S11 split (commit 7753428) was then tested at 175 MHz and
      **made it worse: -0.673 ns, a ~157 MHz ceiling.** It has been
      reverted.

      The interesting part is why, because it did what it claimed. S11
      is no longer the critical path, and failing endpoints nearly
      halved (2,753 -> 1,484) - the fan-in/fan-out seam was real and
      splitting it fixed a broad shallow class of paths. What surfaced
      underneath is narrower and deeper: **S12 -> S13**, the
      exponent-normalise register into the rounded significand, 34
      logic levels of which 20 are CARRY8 (the 237-bit round
      increment, carried as a ripple), and still 68% routing. The
      split's 653 extra registers cost enough placement pressure to
      push that path past where S11 had been.

      Two things to carry forward. **The out-of-context core
      measurement is not a valid predictor for this design** - it said
      5.871 -> 5.746 ns, a 2% improvement, and the in-shell answer was
      a regression. It did not merely understate the gain; it pointed
      the wrong way, because a core placed alone in a small region
      never sees the congestion that decides a shell build. Trust the
      in-shell number or do not run the experiment. And **the next
      nanoseconds are in the round stage, not the normalizer.**
- [x] **The round stage was the ceiling, and the fix worked
  (2026-08-30).** Two
  independent measurements now agree that the critical path is S12
  into S13 - the exponent register through the round window into the
  rounded significand - at 39 logic levels, 21 of them CARRY8, and
  about 61% routing. Reading `stage13` shows why: it does a variable
  right shift of the 717-bit normalised significand AND a 238-bit
  increment **in series in one cycle**, because `up` depends on the
  guard and sticky bits the shift produces, and `kept + up` then waits
  for `up`.

  The increment does not have to be on that path. `kept` and
  `kept + 1` both depend only on the shift, so both can be computed
  while the guard/sticky reduction and `round_up` are still resolving,
  and `up` then selects between them. A 238-bit ripple carry becomes a
  238-bit multiplexer, the adder hides behind the sticky OR-reduction,
  and nothing about the latency, the stage count or the arithmetic
  changes - which matters, because this is the most safety-critical
  logic in the design and the 441,000-case suite is what would have to
  agree afterwards.

  **Done, and measured in shell rather than out of context.** The
  round stage now computes `kept` and `kept + 1` in parallel with the
  guard/sticky reduction and selects between them, so the 238-bit
  ripple carry hides behind the OR-reduction instead of queueing after
  it. Latency, stage count and arithmetic are unchanged, and the full
  suite agrees afterwards.

  In-shell result, single tile on the U50 platform: **145 MHz closes
  at kernel WNS +0.116 ns**, where the same design at 130 MHz reports
  +0.137. The whole 0.22 ns the sweep said was missing came back.

  Two cautions attached to those numbers. They are the KERNEL clock's
  slack (`clk_out1_ulp_clk_wiz_0`), not the global WNS the manifest
  used to record - the global figure is a shell transceiver path,
  identical in every build on this platform, and quoting it as this
  design's headroom is what happened here first. And a passing run
  never reveals a ceiling: Vivado stops optimising once the asked
  clock is met, so +0.116 at 145 MHz is a floor on the margin, not a
  measure of how much further the design could go.

  The quad tells the other half of the story. Four tiles at 130 MHz
  close at only **+0.022 ns**, with the critical path still landing in
  `g_bank256.u_wfma` S12 -> S13 (38 levels, 21 CARRY8) - which both
  confirms the diagnosis and shows that congestion, not logic depth,
  is what four tiles add: the same design pays ~0.115 ns more per path
  at four instances than at one.

  7753428 (the reverted S11 split) is still worth cherry-picking back
  and retesting as a pair, since S11 was only ever second-worst.
- [x] **One AXI master per stream (2026-08-30):** the engine used to
  share one 256-bit port between three operand reads and one result
  write. Steady state costs 4 transfers per beat and a port retires
  one per cycle, so it was pinned at ~4.4 cycles/beat no matter how
  fast the arithmetic ran - the pipe accepts a beat every cycle.
  Four masters, `AR_DEPTH=4` bursts in flight per stream, and each
  master its own HBM pseudo-channel group: **1.25 cycles/beat, a
  3.5x.**

  A dedicated port alone would not have done it. With a single
  outstanding AR the reader waits out the full memory latency after
  every RLAST, and a 16-beat burst followed by a ~60-cycle bubble is
  ~4.8 cycles/beat - back where it started. Pipelining the address
  phases is what converts four ports into four times the throughput.

  Two bugs found in the building of it, both of the kind a cooperative
  testbench does not catch. `ARADDR`/`ARLEN` were combinational on a
  FIFO count while `ARVALID` was asserted, which violates AXI4 A3.2.1
  - payload must be stable until handshake - and is invisible to a
  memory model that samples once. And `len[FIFO_LOG2+1:0]` selected
  bit 8 of an 8-bit signal, a width trap that reads as correct.
  FIFO space is now reserved at AR issue rather than at R arrival,
  because two bursts in flight can together exceed the space each
  looked at separately, and that overflow would corrupt operands
  rather than stall.

  **The 1.25 is a simulation number and is labelled as one.**
  cocotbext-axi's memory model is cooperative in exactly the way an
  HBM controller is not obliged to be. What it settles is that the
  port was the bottleneck and that splitting it removed that
  bottleneck; where the number lands on silicon is CARDDAY step 6.

  What is NOT yet known is the area. Per-CU AXI plumbing was already
  24k LUT - 20% of a tile, as large as the whole fp128 bank - and this
  is four masters per tile against one, on a quad that already sits at
  69% of the device. A single-tile measurement against the known
  243,440-LUT baseline is the outstanding number, and if sixteen
  masters do not route on a quad then the honest summary is "3.5x per
  tile, at the cost of tile count", which is a decision rather than a
  detail.
- [x] **Reduction ops (2026-08-30):** `CFT_SUM` (24) and `CFT_DOT` (25),
  with the index-fixed tree the contract had already promised. Golden
  model, libcft, RTL and the device path, plus the multi-tile
  partitioning that a reduction needs and an elementwise op does not.

  **The tree changed once, deliberately, before any hardware existed.**
  The first version split at the midpoint - the tidier balanced tree.
  It is index-fixed and satisfies the contract, and it is not
  streamable. The natural hardware is a binary-counter accumulator
  (one add per element, ceil(log2 n) levels, carry when a level is
  occupied), and that machine produces the LARGEST-POWER-OF-TWO split,
  agreeing with the midpoint only when n is a power of two. Rather than
  build a walker for a shape nothing wanted, the model moved. Depth is
  ceil(log2 n) either way, so the accuracy argument - textbook pairwise
  summation - is unchanged. `stream_reduce()` is that machine written
  in Python and is the RTL's specification.

  **Carries are deferred, and that is measured.** The adder is 15
  stages and a carry at level j+1 needs level j's result, so resolving
  eagerly costs ADD_LATENCY per LEVEL: ~15.5 cycles per input against
  ~1.0 when the levels are allowed to be in flight together. Total adds
  is n-1 either way.

  **CFT_DOT is advertised but is not separate hardware.** The contract
  makes `dot(a,b) == sum(mul(a,b))` exact, flags included, so the host
  issues an elementwise MUL and then a SUM. The alternative was a
  multiply pass sharing the accumulator's pipe with tagged results and
  arbitration between muls and adds - the most schedule-sensitive logic
  in the engine, for one saved round trip. The composition property
  went into the contract partly so this choice would exist.

  It also surfaced a pre-existing engine bug that had been invisible:
  the beat count is a truncating shift, which is correct for
  elementwise (N is a whole number of beats and the host pads) and
  silently drops the tail for a reduction, which must be given the true
  element count. n=1 fp32 computed zero beats and finished having
  summed nothing.

  VERSION 0x410 -> 0x500, and VERSION's meaning is now written down: it
  guards the REGISTER MAP, not the feature set, so the host accepts a
  SET of versions and lets CAPS decide features. One value would have
  orphaned the card-day images over a feature they were not going to
  use.

### Second independent review, and the hostile driver it argued for (2026-08-30)

Two more adversarial reviews, on the same split as the first: one on
the numeric datapath and contract, one on control, protocol and
integration. Four real bugs, one of which was a wrong answer rather
than a wrong margin.

- **`cftx_reduce` computed the wrong sum on any quad image.** Staging
  wrote every range into `D.tiles[k % ntiles]` up front and the launch
  loop then reused tiles in waves, so with more ranges than tiles -
  which is routine, since the canonical cut needs an extra range at
  n = 5, 9, 17, 33, 65 - range 4 overwrote range 0's operands before
  range 0 had run. Clean STATUS, plausible flags, wrong answer: fp32
  over four CUs at n=9 gave 51.0 instead of 45.0.
- **CAPS dropped the integer opcode group** while gaining reduction,
  making eight implemented opcodes unreachable. Both benches had been
  updated to assert the wrong literal, and `device-test` skipped the
  opcodes silently, because a skip is not a failure.
- **Two latent quarter-tile faults**, invisible at 256-bit beats: a
  hardcoded shift in the write path's 4KB term that reaches zero near
  a page end and hangs, and a hardcoded elements-per-beat in the
  reduction serializer.
- **The manifest could call a build reproducible when it was not**,
  because `git diff` does not see untracked files and the packaging
  tcl globs `rtl/*.sv`.

The first review's closing line was that the bugs it found "need
either a hostile driver or a reader". The reader has now run twice, so
this round built the driver.

- [x] **A hostile bus (2026-08-30):** `tb/busfx.py`. Backpressure on
  every channel of every master, seeded per channel; error responses
  (SLVERR/DECERR) on any master; and burst-length violations in both
  directions. Eleven bench targets, 27 tests.

  For this design backpressure asks a sharper question than "does it
  still work". Results are scored against a golden model that has no
  notion of a cycle, so a run that survives a hostile schedule AND
  matches is a statement that the SCHEDULE DID NOT REACH THE ANSWER -
  which is the product claim, tested against the most plausible thing
  that could quietly break it.

  It also closed the 4KB-boundary gap. No bench had ever reached a
  page boundary at any geometry: every base is page-aligned and the
  largest run was 48 elements, 192 bytes into a 4096-byte page. Both
  tiles now cross one, and the shortening is visible rather than
  assumed - bursts landing at `0xfe0 len=1`, `0x41fc0 len=2`,
  `0x82fa0 len=3`, each ending exactly on a boundary.

- [x] **A bus fault ends the run (2026-08-30):** the three `err_acc`
  bits were never equivalent. A bad RESPONSE still carries its beat,
  so the run completes and STATUS is read after. A bad LENGTH withholds
  beats that were promised, so compute starves, `ap_done` never
  asserts, and the fault sits in a register nobody can read - because
  nothing can be read until a run that will not end, ends. The host's
  twenty-minute timeout was the only recourse.

  AXI4 requires exactly AxLEN+1 transfers (A3.4.1) and says nothing
  about master recovery, so the behaviour was taken from the
  neighbouring conventions, which agree: PCIe logs and completes, an
  AXI interconnect answers SLVERR rather than stalling the fabric, and
  ap_ctrl_hs cannot express a run that never finishes. A hang costs a
  card reset; a clean `CFT_ERR_BUS_FAULT` costs a retry.

  Abandoning is not stopping. No new AR or AW; any burst already
  committed finishes, holding WVALID with stale data if the FIFO ran
  dry, because there is no way to withdraw a committed burst and the
  run is being reported failed anyway; outstanding reads land before
  done, so their beats cannot arrive during the next run.

  Not covered, deliberately: a slave that stops answering entirely.
  Nothing in the kernel can tell that from a slow slave, so it stays
  with the host timeout.

## v2 - the coordinated part

- [x] **Orbit sequencer: design, model and software backend
      (2026-08-29):** docs/SEQUENCER.md is the ISA and the argument;
      python/cft_golden/seq.py is the definition of correct;
      host/src/program.c is libcft's executor, and the two agree over a
      shared fuzz corpus on deposits, deposit counts, exception flags,
      status, and which programs to refuse. A program can be written
      and run today, on any machine, with no card - what the hardware
      adds is the on-chip iteration that makes it worth building.

      Three determinism properties, each a test rather than a claim:
      the ALU is the existing verified pipeline; deposits are addressed
      by element index so splitting lanes across tiles cannot change
      the answer; and the all-lanes-done early exit changes the
      instruction count and nothing else.

      A review found the third one false. HALT is the only instruction
      whose effect is not per-lane, so the active mask cannot gate it:
      with every lane inactive, skipping a loop containing one
      continues the program while entering it stops the program - and
      it drags the deposit-addressing property down with it, because
      lane i's deposit count then depends on whether some other lane
      was still active. Four partitionings of one program gave four
      different answers. It is refused inside a loop now, and a fuzz
      with the rule removed confirms the rule is what holds the
      property up.

      The same review found the ISA had been specified as though
      execution were single-cycle, against a 15-stage pipeline with no
      stall path. The answer is that lanes are independent, so a block
      of at least LATENCY lanes fills the pipe on its own - which makes
      the lane block the design's central sizing constraint and puts
      the register file at L*16*element_bytes beside the deposit
      buffer.
- **Orbit/walk engine** (the RTL): a micro-sequencer running iterated maps
  on-chip (the atlas positive's inner loop: fma chains, exact
  selections, integer/bit ops, the hash), with point deposition into
  HBM and deterministic-by-index accumulation. This is where the
  "coordinated" in CFT earns its name: deposition order is a hardware
  guarantee, the thing no GPU warp scheduler can promise.
- **Atlas parity column**: a detbits.py-style harness replaying the
  det library's primitive sequences per-op on the tile, hashed against
  the GPU columns - the FPGA as the next column in atlas-engine's
  one-hash matrix, and the first external consumer of vectors/.
- **High-precision oracle**: fp64/fp128/fp256 shadow evaluation of the
  same programs, replacing the float64 accuracy-reference role that
  `measure.mjs` plays today (atlas-engine docs/DETERMINISM.md, Phase
  1) with a reference whose own arithmetic is contract-bound.

## Memory strategy and the family ladder (analysis, 2026-08-29)

**DDR4 costs this workload far less than HBM branding implies.** From
the tile's own numbers: elementwise streaming is 0.125 flops/byte, so
one tile at the v1 target (300 MHz) saturates ~38 GB/s - two DDR4
channels. HBM's 316 GB/s only pays when many tiles stream at once.
The workloads this project exists for (iterated orbits, oracles) are
compute-dense and barely touch memory. The one HBM-native pattern -
scattered deposition - gets architected away on ANY memory by binning
deposits into on-chip URAM tiles (27 MB on VU35P; a 2048-square count
tile is 16 MB) and committing them as fixed-order linear bursts,
which determinism wants regardless. Verdict: a custom carrier or a
current-line part with hardened DDR4/LPDDR4 loses multi-tile
streaming headroom and nothing else.

**Family ladder:**

- **Alveo U55C** - the scale-up sibling: same 2022-era flow, VU47P
  (1.3M LUTs), 16 GB HBM2 @ 460 GB/s, same
  discontinued-hardware-gets-cheap dynamics as the U50C.
- **Versal Prime + DDR4** - the custom-carrier line: hardened memory
  controllers, current tools, covered by the analysis above.
- **Open-toolchain targets** - see below.

## What can be shared, and what only looks like it can (analysis, 2026-08-30)

Two axes get proposed whenever area is short, and they are worth very
different amounts.

**Across the four tiles: nothing, and that is structural rather than an
oversight.** The tiles exist to run in parallel; anything shared
between them becomes a single issue point that all four queue behind,
which needs buffering and sequencing to hide and gives back more than
it saves. The only block genuinely duplicated without being a datapath
is `cft_csr` at 624 LUT, and it cannot be shared anyway: the Vitis CU
model gives every compute unit its own AXI4-Lite control interface, and
4 x 624 is 0.5% of a quad - not a reason to leave the standard flow.
Anything else that is four-of-a-kind is four-of-a-kind *because* it is
computing four things at once.

**Inside one tile, across the precision banks: this is the real axis,
and it is free of the sequencing problem.** `prec_r` is snapshot at
start and cannot move while anything is in flight, so exactly one bank
is live for the duration of a run. The fp256 bank is idle for every
fp32 job and vice versa. Sharing between them needs no arbitration, no
buffering and no schedule - only a mode input.

**The rule, and it has been measured in both directions: share what is
LINEAR in the format width, not what is QUADRATIC.** NOVEL.md entry 6
states the FPGA half of this ("fracture what the fabric implements in
LUTs, not what it implements in hard blocks"); the sizing argument is
what makes it predictive rather than a rule of thumb.

Every bank consumes exactly one 256-bit beat - eight fp32, four fp64,
two fp128, one fp256 - so **aggregate operand width is identical across
the ladder.** For a structure whose width is linear in the format
width, the shared version is therefore exactly as wide as the widest
bank, and the narrow modes waste nothing. For a quadratic structure the
widest bank alone is most of the total, so the same collapse buys far
less:

| structure | scaling | aggregate across banks | shared | collapse |
|---|---|---|---|---|
| aligner / normaliser | linear, `3P + 7` | 2,706 bits | 718 | **3.77x** |
| significand multiplier | quadratic, `P x P` | 97,551 bit-products | 63,990 | **1.52x** |

**Corrected 2026-08-30 (evening): an earlier version of this table put
the fp256 bank in the multiplier's aggregate column instead of the sum
over banks, and reported 1.0x - "no collapse at all". That was an
inconsistency with the aligner row, not a result.** The multiplier does
collapse; it collapses about half as well.

**And that is not why `cft_mulfrac` lost, which is the more important
correction.** The measured numbers are `262 -> 259 DSP` and `+693 LUT`:

| | LUT | DSP | WNS |
|---|---|---|---|
| private multipliers | 124,589 | 262 | +0.959 ns |
| fractured array | 125,282 | 259 | -0.181 ns |

Ten live slots of 237x27 cost essentially what four banks of
right-sized multipliers cost, because **a wide cascaded multiplier is
less DSP-efficient per bit-product than a narrow one** - roughly 246
bit-products per DSP against 372 - and the cascade overhead eats the
1.52x before it reaches the resource count. What the array added
instead was operand packing and product distribution, which are LUTs.
It spent the scarce resource to save none of the abundant one; DSP sits
at 4.4% and is not the constraint. That is NOVEL.md entry 6's original
finding, and the scaling argument above is a refinement of it, not a
replacement.

**A second axis, and the one `cft_mulfrac` got wrong.** The array does
gang the lanes exactly as intended - mode 0 is eight independent 24x24
products in one beat, mode 3 is one 237x237, and `tb_mulshare` proves
bit-identity. But it shares the *number* of partial products, not their
*width*: `prod = aop * bch` is `[PMAX-1:0] x [MCH-1:0]`, a 237x27
multiplier, in every mode. At fp32 that is a 24x24 job in hardware
built for 237x27 - **9% of the silicon it occupies.** Every lane is
utilized and almost none of the hardware is. Cutting the width instead
- the granule grid `docs/ARCHITECTURE.md` sketched, tiling 237x237 into
24x24 granules with gated cross-terms so fp32 lights eight small
granules - is the version that would pay, and remains unbuilt.

This cuts in favour of the aligner work rather than against it: the
aligner is LUTs, which are the constraint, so its 3.77x lands where the
multiplier's 1.52x could not.

What that predicts, for the parts of the FMA pipe that are linear.
`AW = 3P + 7`, so the aligner is 79 / 166 / 346 / 718 bits per lane:

| bank | lanes | AW/lane | aggregate |
|---|---|---|---|
| fp32 | 8 | 79 | 632 |
| fp64 | 4 | 166 | 664 |
| fp128 | 2 | 346 | 692 |
| fp256 | 1 | 718 | 718 |
| | | | **2,706** |

**A segmented aligner sized for fp256 is 718 bits and hosts every bank:
3.77x the width collapses into 1x, with under 14% slack at the narrow
end.** The normaliser is the same shape (`NW = 3P + 6`) and the same
ratio. These are the two structures the ASIC multi-precision papers
segment, and unlike the multiplier they are LUTs here, so the trade
does not invert.

**This is a ratio, not a LUT promise.** The FMA pipes hold 95,120 LUT
and no measurement here says what fraction of that the two shifters
are. It is also a redesign of the one part of this project that is
proven bit-exact, which is a different risk class from rewriting the
block that bypasses the arithmetic. The ratio is recorded so the work
can be scoped; it should not be started without first measuring the
shifters inside the pipe the way `cft_simpleops` was measured.

#### Both halves measured (2026-08-31)

**What the shifters cost.** By ablation - freezing the four variable
shift amounts to constants so the ladders and their sticky masks
collapse to wiring, and differencing whole-kernel OOC synthesis. The
LZC is left alive, so what this isolates is the shifts:

| tree | LUT | vs base | share |
|---|---|---|---|
| base | 117,530 | | |
| alignment frozen | 95,228 | **-22,302** | 19.0% |
| normalise frozen | 101,997 | **-15,533** | 13.2% |
| both frozen | 79,742 | **-37,788** | **32.2%** |

The two are additive to within 47 LUT of each other, which is the
internal check that the ablations isolate what they claim. `base`
reproduced to the digit across two separate batches. **A third of the
kernel is barrel shifter**, three times what the ladder widths alone
predicted, because depth counts as well as width.

**What sharing recovers.** `rtl/cft_normseg.sv` is the segmented
version of the normalise shifter, and `hw/synth_shiftcmp.tcl` measures
it against the fifteen it replaces, hierarchy preserved:

| | LUT | FF |
|---|---|---|
| fifteen private | 10,405 | 5,475 |
| one shared | **5,269** | **1,490** |
| saving | 5,136 (**1.97x**) | 3,985 |

**1.97x, not the 3.77x the bit counts predicted, and the per-instance
numbers say why.** A private shifter costs 0.46 LUT per stage-bit at
every rung - fp32 253, fp64 558, fp128 1,411, fp256 3,327, all within
4% of that constant. The shared ladder costs 0.73. It pays fp256's
full ten-stage depth in every mode where fp32 privately needs seven,
and segmentation itself costs about 1.6x per stage-bit.

That 1.6x is not a coding artifact. It was rewritten to split the
boundary gate into explicit per-bit cases so the constant masks could
not hide from the optimiser, and the result was **5,269 LUT before and
after** - Vivado folds them either way.

Integration adds a gather multiplexer this comparison does not
include: the shared input must select among four banks per bit, about
720 LUT. So the realistic figure is **~4,400 LUT and ~4,000 FF, 3.8%
of the kernel**, for the normaliser alone.

#### EXT_NORM measured at the kernel (2026-08-31)

`FUSE_NORM` wires the ladder into the engine. Same tree, same script,
same machine, one generic apart - the shape that caught `cft_mulfrac`
not paying:

| | LUT | FF | DSP | WNS @130 | levels |
|---|---|---|---|---|---|
| `FUSE_NORM=0` | 115,903 | 50,293 | 262 | +2.456 | 21 |
| `FUSE_NORM=1` | 109,971 | 45,955 | 262 | +1.758 | 25 |
| delta | **-5,932** | **-4,338** | 0 | -0.698 | +4 |

**The gather multiplexer is nearly free.** It was budgeted at ~720 LUT
against the 5,136 the shifters alone saved; the kernel delta is larger
than that standalone figure, not smaller. Vivado absorbs it, most bit
positions having fewer than four real sources.

**And the S11 split paid for itself before any sharing.** The
`FUSE_NORM=0` baseline is 115,903 against 117,530 measured the same
night at the previous commit - **-1,627 LUT** purely from pulling the
leading-zero scan out of the register process, because the old form
duplicated the shift expression across both arms of the empty-window
`if`. Bit-identical, and it lands whether sharing is ever enabled.

**Where the slack goes, which is the part worth knowing.** The
critical path WITHOUT sharing is not the normaliser at all:

    FUSE_NORM=0   s12_enorm_reg -> s13_kept_r_reg        21 levels
    FUSE_NORM=1   s10_mag_reg   -> normseg/cs_r_reg[592] 25 levels

Sharing inserts a 25-level path into the ladder's first register and
that takes over from the S13 rounding stage. The two halves of the
ladder are not symmetric: the first stage's amount bits come live off
the leading-zero count, so its path is LZC + slot mux + SPLIT levels,
while the second stage's bits are already registered and its path is
just the remaining levels. Balancing the LEVEL COUNTS is therefore the
wrong instinct - and rebalancing 4/6 to 5/5 measured very slightly
WORSE (+1.758 against +1.788), because it moved a level into the stage
that carries the LZC.

The split is now a parameter, `SPLIT`, and every value computes the
same function - the equivalence bench passes at 1, 2, 3, 4, 5, 7 and 9.
The target is arithmetic rather than taste: the ladder path must come
down about four levels to stop being critical, which is SPLIT near 1.

**Whether to spend it.** On Alveo the pressure is off - the quad
closes at 130 MHz with 30% of the device free - so this is about the
FIFTH TILE there. At 121,158 LUT per tile plus the 123,897-LUT shell,
five tiles is 83.8% of the device; take ~10% off the tile (the
normaliser plus the aligner, the same trick against a 22,302-LUT
target) and five tiles is ~76.8%, plausibly routable for 25% more
throughput.

**On the open-core target the answer is simpler: turn it on.** The
0.698 ns objection is a defence of 130 MHz, and an openXC7 Kintex-7
build is nowhere near that clock - at 120 MHz the shared version
already carries +2.399 ns. Footprint is the whole objective there, and
the parameter is per-build, so Alveo and Kintex need not agree.

#### EXT_ALIGN measured at the kernel (2026-08-31)

The same trick against the larger target. The alignment shifters
ablate at 22,302 LUT to the normaliser's 15,533, and unlike the
normaliser the shift is bidirectional - left when the addend anchors,
right when the product does, lanes free to disagree - which is what
`cft_normseg`'s BIDIR mode exists for. Sticky never enters the shared
ladder: the two incremental lost-bit masks are equivalent to one mask
on the pre-shift operand, so the marker is computed in the lane and
delayed beside the shift. The far case gates the value to zero at
hand-off.

| | LUT | FF | WNS @130 | levels |
|---|---|---|---|---|
| neither shared | 116,932 | 50,707 | +2.411 | 22 |
| norm shared | 112,003 | 46,068 | +2.521 | 21 |
| **both shared** | **101,264** | **40,464** | +0.327 | 28 |

**FUSE_ALIGN is -10,739 LUT and -5,604 FF on top of the shared
normaliser - nearly double the normaliser's own saving.** The FF drop
is the fifteen private `s7_sml` staging registers collapsing into the
ladder. DSP 262 throughout.

Two honest notes. The neither-shared baseline moved +1,029 against the
pre-restructure tree (116,932 vs 115,903): the S7/S8 split pays a
small price in the PRIVATE configuration, where one 10-bit-amount
thermometer mask replaces two narrower ones. And the both-shared
timing is thin at +0.327 - the critical path is the same LZC-fed
norm-ladder path that set SPLIT=1, now at 78% ROUTING estimate, which
is the OOC placer pricing the density of two 720-bit ladders plus
gathers. Whether that congestion is real is an in-shell question, and
OOC slack does not predict shell slack in either direction.

#### The FIFOs move to block RAM, and the kernel crosses 100k (2026-08-31)

The last queued item. `cft_fifo`'s async read (`rd_data = mem[rp]`,
same cycle) is what foreclosed BRAM, and the callers depend on that
contract twice over: rd_data valid the same cycle `count` reads
nonzero, and `count` moving at the write edge so the readers'
free-space reservation never overestimates. So the conversion happens
INSIDE the port list: a sync-read RAM whose address is led by the pop
(`rp + rd_en`), plus a two-cycle head bypass covering the only cases
that break - a write landing at the read head. The capture condition
(`count==0 || (count==1 && rd_en)`) IS the address compare, evaluated
where the answer is already known, and it forces count to 1, so the
bypass can never mask a different word than the RAM would present.

Proof: the four FIFO-heavy benches green (krnl with backpressure at
three duties and page crossings, quarter, reduce, faults with error
injection); negative control - dropping the head-pop capture term -
fails 4 of 4 with element mismatches.

| | LUT | as memory | FF | BRAM | WNS @130 |
|---|---|---|---|---|---|
| both shared, LUTRAM FIFOs | 101,264 | 7,276 | 40,464 | 0 | +0.327 |
| both shared, BRAM FIFOs | **98,310** | 4,671 | 41,295 | 16 | +0.327 |

-2,954 LUT for 16 of 1,344 block RAMs the design had never touched,
timing-neutral.

**The campaign, end to end - every step equivalence-proven, every
sharing behind a per-build parameter, DSP at 262 throughout:**

| | LUT | FF | note |
|---|---|---|---|
| start (2026-08-30 evening) | 131,860 | 59,999 | |
| cft_simpleops rewrite | 120,303 | 59,598 | mux sources, not opcodes |
| cft_reduce_acc as memory | 117,530 | 49,846 | the 40:1 mux dissolves |
| + FUSE_NORM, SPLIT=1 | 110,780 | 46,048 | timing-free at the measured split |
| + FUSE_ALIGN | 101,264 | 40,464 | bidirectional ladder, sticky in-lane |
| + BRAM FIFOs | **98,310** | 41,295 | **-25.4% / -31.2%** |

Two tiles at 98,310 plus a 20k platform budget: 216,620 LUT -
**72.5% of a 480T, 85.2% of a 410T, 83.1% of a 420T** - and still over
a 325T, whose two-tile story remains through-fp64 trims (their own
numbers also shrink with sharing; unmeasured). The 7-series caveat
stands: these are UltraScale+ figures and CARRY4 makes them
optimistic.

The module is built, proven against 2,977 comparisons at every legal
shift and every rung, and measured. What is NOT done is `EXT_NORM`
plumbing through `cft_fpfma_pipe`, which is the bit-exact core and a
different risk class from everything above it.

**What none of this buys: low-precision throughput.** Lane count is
pinned by the 256-bit beat - 8x32, 4x64, 2x128 and 1x256 all consume
exactly one beat - so freed area cannot become more fp32 lanes. It
becomes more tiles.

## The open core

The core RTL is deliberately vendor-clean and, as of 2026-08-29,
**the complete kernel elaborates in Yosys** (`make yosys-lint`, CI
job `portability`) - so the open-core port is a thin platform wrapper
(LiteX is the intended harness) around the same rtl/, gated by the
same conformance vectors, never a fork. The determinism contract
makes low clocks irrelevant to correctness, so cheap open boards
produce bit-identical results to the U50C - "verify our silicon
claims on hardware you can audit down to place-and-route" is a
conformance story no closed flow can tell.

#### What a tile actually costs (measured 2026-08-30, corrected)

The fits below were originally estimated by summing the fp32 and fp256
OOC numbers. That undercounted by more than half, because a full tile
carries **all four rungs**, and the earlier arithmetic left out the
fp64 and fp128 banks entirely. The real numbers, from differencing
routed in-shell builds on the U50:

Superseded once more on 2026-08-30 by a `report_utilization
-hierarchical` run, which is a measurement per module rather than a
difference between builds. Per lane, from `build_ooc_hier`:

| rung | P | LUT/lane | DSP | lanes | bank LUT | LUT per significand bit |
|---|---|---|---|---|---|---|
| fp32 | 24 | 2,580 | 2 | 8 | 20,640 | 107.5 |
| fp64 | 53 | 5,100 | 9 | 4 | 20,400 | 96.2 |
| fp128 | 113 | 11,670 | 35 | 2 | 23,340 | 103.3 |
| **fp256** | 237 | **31,831** | 140 | 1 | **31,831** | **134.3** |
| | | | | | **96,211** | |

**Each bank costs about the same, because lane count halves as
precision doubles - until fp256, which cannot halve further and pays a
30% per-bit penalty on top.** The area exponent across the ladder is
0.86, then 1.09, then 1.35. That last rung therefore carries roughly
**8,000 LUT of superlinear excess**, and it is the concrete target for
any narrowing work on the aligner and normaliser.

Whole tile, and the figure to size other parts with:

Whole tile, by module, from `hw/synth_attrib.tcl` with the hierarchy
preserved - so every instance is charged what it actually contains:

| module | instances | LUT | share | DSP |
|---|---|---|---|---|
| `cft_fpfma_pipe` | 15 | 95,120 | 71.1% | 262 |
| **`cft_simpleops`** | **15** | **22,418** | **16.7%** | 0 |
| `cft_reduce_acc` | 1 | 7,138 | 5.3% | 0 |
| engine own logic | - | 4,505 | 3.4% | 4 |
| `cft_fifo` | 4 | 3,196 | 2.4% | 0 |
| `cft_opmux` | 15 | 788 | 0.6% | 0 |
| `cft_csr` | 1 | 415 | 0.3% | 0 |
| **kernel, hierarchy preserved** | | **133,852** | | **266** |
| kernel, flattened (normal build) | | 134,697 | | 266 |
| one tile in shell, 4 masters + reductions | | 138,083 | | 267 |

The DSP column is the load-bearing check: the per-lane ladder predicts
`8x2 + 4x9 + 2x35 + 1x140 = 262` and the arithmetic reports exactly
262. The four extra were a variable multiply in the reduction
serializer where a shift belonged - found *because* the ladder
disagreed, which is what makes it worth keeping as a standing check.

**Why this table needed its own synthesis run.** The flattened report
charges merged logic to whichever instance survived, and it put
`cft_simpleops` inside the four FIFOs: they came out at 14,092 / 9,741
/ 1,431 / 202 logic LUTs for four *identical* modules. With the
boundaries kept they are 896 / 770 / 769 / 761, as four copies of one
module must be. Two successive readings of that flattened report were
wrong in opposite directions - first that the FIFOs were negligible,
then that they were 27,834 LUT and the largest non-arithmetic block.
Neither survived contact with an attribution run.

**`cft_simpleops` is the finding.** 22,418 LUT - larger than the whole
fp64 FMA bank - for the opcodes that BYPASS the arithmetic: min/max,
predicates, select, and the eight integer/bitwise ops. It scales with
width (6,378 at fp256, 2,912 at fp128, 1,338 at fp64, 608 at fp32),
which points at the integer shifts: `ishl` and `ishr` are two
independent barrel shifters per lane on a W-bit word, where one shifter
plus two bit-reversals would do. Nothing had looked at this module
before 2026-08-30, because until the hierarchy was preserved it was
invisible.

#### Acting on it: -11,557 LUT from one file (2026-08-30, measured)

Rewritten at 2377054 and measured the way a shipping change has to be -
two full-kernel OOC runs at 130 MHz on the same machine with the same
script, differing in exactly one file:

| | LUT | as logic | LUTRAM | FF | DSP | WNS |
|---|---|---|---|---|---|---|
| base (7ab02b3) | 131,860 | 124,880 | 6,980 | 59,999 | 262 | +1.754 |
| new (2377054) | **120,303** | 113,323 | 6,980 | 59,598 | 262 | +1.754 |
| delta | **-11,557** | -11,557 | 0 | -401 | 0 | 0.000 |

**-8.8% of the kernel, from the block nobody had looked at.** The whole
saving is `LUT as Logic` and LUTRAM is unchanged to the bit, so nothing
was relocated rather than removed. DSP is unchanged, as it must be -
this module does not multiply, and the ladder check still reads 262.

The shifts were the smallest of the four causes, not the largest. What
dominated was **mux source count**: on this fabric a 4:1 mux is one
LUT6 and MUXF7/MUXF8 are free, so a wide mux costs 2 LUT/bit per
octave of *sources* - 8:1 costs 2, 16:1 costs 4. A `case (op)` that
assigns a W-bit value per opcode prices itself by opcode count, and
there were twenty-odd. Grouping the opcodes by the SHAPE of the answer
gets it to eight. abs, negate and copySign were three separate sources
for what is `a` with a different sign bit; they now override bit W-1
alone and cost one LUT between them.

**On the two numbers, because they look contradictory and are not.**
22,418 is the module's cost with `-flatten_hierarchy none`, which is
what makes per-module attribution possible at all. 11,557 is what
actually left the kernel under the flatten settings that ship. The gap
is not error: with boundaries dissolved Vivado had already been merging
some of this logic into its neighbours, so the unflattened figure is an
**upper bound** on what a rewrite can reach, and the rewrite captured
about half of it. Attribution runs say where to look; only a
before/after under shipping settings says what a change is worth.

The new flattened report re-earns that warning in the opposite
direction: `u_fifo_a` is charged 7,644 LUT for a module holding 592
LUTRAM, and the fp32/fp64/fp128 `cft_simpleops` instances do not appear
at all.

**Equivalence, not inspection.** `tb/wrappers/cft_simpleops_ref.sv`
freezes the previous implementation and `tb_simpleops` runs both at all
four rungs from one operand word: 453,424 comparisons of `d`, `flags`
and `valid`, zero mismatches, plus the full 12-bench suite green. Two
negative controls, both caught - an off-by-one in the output bit
reversal, and dropping the equality term from the substituted
comparator. Comparing the two forms to each other rather than each to
the model is the `tb_mulshare` argument, and it reaches ground the
model has no opinion about: the 233 reserved opcodes, the arithmetic
group's unread default, and flags on operands the model never emits.

#### `cft_reduce_acc`: the levels were a memory pretending to be registers

The same report charged `u_reduce` **5,955 LUT and 10,853 FF**. The
flip-flops are the giveaway - 40 levels x 256 bits is 10,240 bits - so
the array had been inferred as registers behind a 40:1 multiplexer, and
that multiplexer is most of the LUTs. Nothing here wants registers: the
array is written once per add and read once per issue, which is a
memory.

Two things blocked distributed-RAM inference, and neither is a
behavioural requirement. There were **two write statements** in one
process (`slot[res_lvl]` for a returning result, `slot[0]` for an
arriving input) where a distributed RAM has one write port; and the
writes sat inside the reset process, which nothing about them needs.

The two writes are not a real conflict, and the reason was already
load-bearing in that file for a different purpose - the issue
arbitration relies on it to argue a result and an input can never
contend for a slot: **a result never targets level 0.** An issue from
level t targets t+1, the input path targets 1, and the fold targets
`ptr`, which is at least 1 because the seed consumed the lower index
before `fold_started` went high. So level 0 has exactly one writer and
levels 1..39 have exactly one writer. Split them and each gets a single
port; level 0 becomes a plain register and the read port becomes one
2:1 mux instead of 40:1.

| | LUT | as logic | LUTRAM | FF |
|---|---|---|---|---|
| `u_reduce` before | 5,955 | 5,948 | 0 | 10,853 |
| `u_reduce` after | **2,868** | 2,565 | 296 | **867** |
| kernel before | 120,303 | 113,323 | 6,980 | 59,598 |
| kernel after | **117,530** | 110,254 | 7,276 | **49,846** |

**-2,773 LUT and -9,752 FF at the kernel, DSP and WNS again unchanged.**
The module shed 3,087 LUT and took on 296 LUTRAM, which is the trade
working exactly as intended - a 39 x 256 array in SLICEM instead of
10,240 flip-flops and a 40-input mux.

The invariant is asserted in simulation rather than assumed, because
its failure mode is silent: a result would land in the wrong level
instead of colliding visibly. The assertion was inverted once to prove
it is live and not dead code - it fires at 304 ns.

**Running total for the evening: 131,860 -> 117,530 LUT (-10.9%) and
-10,153 FF, from two files, with DSP and OOC WNS unchanged throughout.**
The next target is the FMA pipes at 95,120 LUT, which is a different
risk class - see the sharing analysis above for the ratio it would buy
and why it should be measured before it is started.

Two consequences, and the first one is unwelcome:

**A full 256-bit tile does not fit on an Artix-7 100T, and no longer
fits a 200T either.** Against the measured 138,083 LUT / 267 DSP:
the 100T is **218% / 111%**, and the 200T is **103% / 36%** - it fit
at 89% on the pre-reduction figure and does not any more. The Arty was
ordered on a "full tile, ~79% LUTs" estimate that was wrong on both
axes. It stays the right board to bring the open flow up on, because
it is openXC7 and LiteX's reference target and that is worth more than
width - but the full tile has to live somewhere else. See the Kintex-7
row below, which is where it now lives.

*Updated after the `cft_simpleops` rewrite (-11,557 LUT), which puts
the tile at ~126,500: the 100T is 200% and the 200T is 94%. The 200T
crossing back under 100% does not move the conclusion and should not be
planned on - a 94%-full 7-series part is not a part an open
place-and-route flow routes, and the DSP-to-LUT ratio penalty in the
next paragraph applies on top. The Kintex-7 row stays the target; what
the saving actually buys there is headroom (325T falls 68% -> 62%),
which is the difference between "fits" and "fits with somewhere to put
the next thing".*

**7-series will be worse than these numbers, not better.** They are
UltraScale+ figures, and the carry structure differs: the fp256 adder
uses 21 CARRY8 per critical path, which becomes 42 CARRY4 on Artix.
Wide-significand arithmetic is exactly the pattern that penalty falls
on, so treat every 7-series estimate below as optimistic.

BEAT_BITS is the knob that makes this a configuration rather than a
problem, and it is already a working, tested one - `tb_krnl_quarter`
runs the same RTL at 64-bit beats against the same golden model.

| target | open flow | what actually fits | role |
|---|---|---|---|
| **Arty A7-100T - dev board, ORDERED 2026-08-29** | openXC7 + LiteX treat it as their reference target - open bring-up on rails | NOT a full tile (218% LUT, 111% DSP). Estimated: a 128-bit-beat tile through the fp128 rung, or a 256-bit fp32-only tile | where the open flow comes up first, at reduced width; Ethernet/Etherbone streaming; no transceivers ever (CSG324) |
| ~~Alchitry Pt V2 (XC7A100T-2), x4 when bundled~~ | ~~same silicon as Arty~~ | **superseded 2026-08-30.** Same 218% problem as the Arty, so the "quad carrier of full tiles" it was chosen for was never possible on that silicon | replaced by the PZ SOM family below, which is the same idea on a part that fits |
| **PZ-K7325T-SOM (XC7K325T), ~$379** | openXC7 **supports 325T** and ships working `xc7k325t-picosoc-nextpnr` / `xc7k325t-blinky-nextpnr` examples on this exact die; LiteX has `qmtech_kintex7_devboard.py` with a yosys+nextpnr option | **a full tile at 68% LUT / 32% DSP** | **the open full-tile target.** 2 GB 64-bit DDR3 and 16 GTX pairs on the module |
| **PZ-K7410T-SOM (XC7K410T), same footprint** | **410T is NOT in openXC7's supported list** (70T, 160T, 325T, 420T, 480T). The adjacent 420T *is*, so adding it is plausible work rather than new science - but it is unproven | **a full tile at 54% LUT / 17% DSP**, leaving 46% for the sequencer; two *lean* tiles would be 78% | the headroom part, reachable without redesigning the carrier |
| **PZ-K7325T-KFB / K7410T-KFB carrier, ~$499** | as the SOM it carries | PCIe, dual SFP, HDMI, SATA, DDR4 | turns either SOM into an actual card rather than a dev board |
| Alchitry Au V2 (XC7A35T-2, $150) | openXC7 on prjxray's reference part - the most mature open target there is | the quarter tile as already built: 64-bit beats, 2x fp32 + 1x fp64, ~20k LUT estimated against 20,800 - tight, and the first thing to measure. fp256 remains physically impossible at any width | **the conformance node**: cheapest object that attests the contract; no transceivers (FTG256) but none needed - FT2232 USB at 8 MB/s replays vector sets in seconds, so an Au farm is a powered USB hub, no carrier required |
| ECP5-85F (ULX3S etc.) | Yosys+nextpnr, most mature | fp32 bank + engine at reduced width | fallback nano-tile if boards resurface (scarce as of 2026-08) |
| **Artix-7 200T** (Nexys Video, ALINX AX7A200) | openXC7 | a full tile at 89% LUT / 35% DSP - no LUT-fallback multipliers needed, contrary to the earlier note | the smallest part that takes a full-width tile |
| **Kintex-7 325T - QMTech core board, ~$100** | openXC7 supports Kintex7 **325/420/480T**, with working `xc7k325t-picosoc-nextpnr` and `xc7k325t-blinky-nextpnr` examples on this exact part; LiteX ships `qmtech_kintex7_devboard.py` with a yosys+nextpnr toolchain option | **a full tile at 59% LUT / 31% DSP** - room left for the sequencer's register file and deposit buffer | **the open full-tile target.** Same price class as the Au, twice the Arty's density, and the flow is already demonstrated on the part |
| Kintex-7 480T (surplus) | openXC7 | **two full tiles**: 40% LUT, 14% DSP | the open multi-tile option - see the scale-out note below |
| Zynq-7045 (ZC706) | openXC7 covers Zynq7; a fully open Zynq-7000 flow was presented at FOSDEM 2025 | a full tile at 55% LUT / 29% DSP | viable but the PS is complexity this design does not need |
| ~~Tang Mega 138K (GW5A)~~ | ~~Apicula~~ | **ruled out 2026-08-30**: Apicula does not support the GW5A family (YosysHQ/apicula#204), so the part has no open flow regardless of its LUT count | revisit only if GW5A support lands |

**Kintex-7 is the correction that matters here.** The table above used
to consider only Artix-7, ECP5 and Gowin, and concluded the open story
was necessarily a reduced-width one. openXC7 covers Kintex-7 as well,
which puts a full tile on a board costing a few hundred dollars -
a better open target than the Arty on every axis except maturity, since
prjxray's most-travelled ground is Artix and the Kintex support is
newer.

**Why the PZ SOM family replaces the Pt plan** (2026-08-30). The Pt was
chosen as a module that could be bundled x4 behind a carrier, with
GTPs for a deterministic module ring - the scale-out doctrine's whole
mechanism. That plan was built on the belief that a Pt held a full
tile. It does not; it holds 46% of one. The PZ modules keep every
property the Pt was picked for and fix the one that was wrong:

  - **a full tile fits**, with room (68% on the 325T, 54% on the 410T);
  - **16 GTX pairs**, so PCIe and the module ring are both reachable -
    the Arty has no transceivers at all and the Au none either;
  - **2 GB of 64-bit DDR3 per module**, which the memory analysis
    below already argues is sufficient for this workload;
  - **one footprint, two dice.** The 325T and the 410T are the same
    SOM, so the carrier is designed once. That is what makes the
    toolchain risk tolerable: bring up on the 325T, which openXC7
    supports today, and move to the 410T later if the extra 50k LUT is
    wanted - without touching the board.
  - **a PCIe carrier exists** (~$499), so the open path ends at a card
    rather than a dev board on a bench.

The residual risk is named rather than buried: **the 410T is not in
openXC7's device list.** Buying into the family is safe because the
325T is; buying *the 410T specifically* on the assumption that the
open flow will reach it is not, until someone checks.

**Read every percentage in this table as optimistic**, for two reasons
that stack.

They compare against UltraScale+ measurements, and 7-series carry
structure is worse for exactly this arithmetic - 21 CARRY8 per fp256
adder path becomes 42 CARRY4. The K325T's 68% has margin to absorb
that; the K410T's 54% has a great deal.

**And the DSP assumption is unverified.** Every row credits the design
with 266 hard DSPs carrying the significand multipliers. If
`nextpnr-xilinx` cannot place clocked DSP48E1 - the reported error is
`Clocked DSP48E1s are currently unsupported`, with `yosys -nodsp` as
the documented workaround - then an openXC7 build puts all four
multiplier trees in fabric, and every LUT figure here is far too low.
**This is the single question that decides whether the open full-tile
story is real**, it applies identically to every 7-series row, and it
has not been checked. Check it before buying anything on the strength
of this table.

The Pt's serialized-multiplier note is a real design option, not a
consolation: a multi-cycle 237-bit significand multiply built for
open flows produces identical bits by contract - determinism makes
"slower but exact" an honorable configuration.

### Verified execution modes (multi-module redundancy)

Bit-determinism makes cross-device redundancy trivial where it is
normally a numerical-policy nightmare: compare is memcmp, any
mismatch is a hardware fault by definition, and bit-reproducible
retry auto-classifies faults (vanishes = transient/SEU; repeats =
persistent -> attribute against a third module and quarantine).
Planned modes, cheapest first:

1. **Host-library lockstep** - `run_redundant(devices, policy)` with
   pair-retry (1/2 throughput) and quorum (1/4) policies; works
   across ANY engines: two CUs on one card, card vs card, silicon vs
   golden model on sampled elements. No RTL.
2. **Build-diversity pairing** - one Vivado-built + one
   openXC7-built module in lockstep cross-checks the toolchains'
   place-and-route continuously (dissimilar redundancy, flight-
   control style), courtesy of the two-toolchain infrastructure.
3. **Carrier-ring voting** (quad carrier) - modules exchange result
   hashes over the spare-GTP neighbor ring and vote before readback;
   verified mode then costs one PCIe transfer, not four.

Boundary, stated plainly: redundancy guards the SILICON (SEUs,
non-ECC DRAM flips, marginal timing, toolchain miscompiles under
diversity) and can never catch a DESIGN bug - all modules agree on a
wrong answer with perfect confidence. Logic correctness remains the
golden model and conformance vectors' jurisdiction.

### The scale-out doctrine (open path to 4-8 tiles)

No open toolchain reaches 4-8-tile monolithic silicon (prjuray is
immature; big Lattice is closed) - so the open machine scales OUT: a
backplane of open-flow modules (quad-Pt carriers; or used SQRL
Acorn/NiteFury A200T M.2 modules - PCIe-native, LiteX-supported,
mining surplus) joined by the deterministic module ring.

**Two tiles, though, are now monolithic and open** (revised
2026-08-30). This paragraph used to say openXC7 topped out around
134k LUTs, which was the largest Artix-7; openXC7 also covers
Kintex-7 through the 480T at 298,600 LUTs.

**Corrected 2026-08-31: the "two tiles fit in 40%" in the previous
version of this paragraph was wrong by about 2x, and it is the number
the board plan was being made against.** 40% of a 480T is roughly ONE
tile. Against the measured tile - 121,158 LUT in shell, or 115,903 /
110,822 out of context with the shared normaliser off / on:

| part | LUT | two full tiles |
|---|---|---|
| XC7K325T | 203,800 | **109 - 119%, does not fit** |
| XC7K410T | 254,200 | 87 - 95%, not routable in practice |
| XC7K480T | 298,600 | **74 - 81%, tight but real** |

DSP is not the constraint anywhere: two tiles is 524 of the 480T's
1,920, 27%.

So the open ladder is one comfortable tile on a ~$100 K325T (now 54%
of it, down from 68% after the 2026-08-30/31 area work), two tiles on
a **480T** and not on the 325T or 410T, and the ring above that.
Reaching two full tiles on a 325T would need ~92,000 LUT each after a
platform budget; sharing both shift paths projects to ~96,000, and
7-series carry structure makes these UltraScale+ figures optimistic
rather than pessimistic. It is not reachable by sharing alone. The A200T is
also no longer openXC7's biggest part, and the M.2 modules are worth
keeping for their PCIe rather than their density. The contract's index-fixed
reduction ordering makes scale-out coherence-free by construction:
the ring IS the "Coordinated" in CFT. The pragmatic monolithic
alternative stays vendor-flow: used Alveo U200/U250 (VU9P: 8+ tiles,
64GB DDR4 - fine per the memory analysis) are covered by the SAME
Alveo-tier license and the same XRT flow as the U50C. Watch prjuray
and Apicula for the open ceiling moving.

**The chiplet flagpole (napkin study, 2026-08-29).** The scale-out
doctrine terminates in ASIC chiplets on the same carrier/ring
architecture the FPGA modules prototype. On 130nm open PDKs (IHP
SG13G2 open shuttles; Sky130-class): full tile ~1M gates ~15-25mm2
(just over an MPW slot); the serialized-multiplier variant ~6-10mm2 -
shuttle-sized. Realistic 50-150 MHz pipelined. Cost tiers: prototype
shuttles ~free-$10k; one mask set ~$100-150k NRE -> ~$100-150/part at
1k; ~$4-6/part at volume. No SerDes/DDR PHY at 130nm open -> hybrid
carrier by construction: chiplets on parallel source-synchronous
neighbor links (the ring, in copper), an FPGA module (the Pt) as
per-carrier hub for host/DRAM, SO-DIMM-style sockets for form-factor
scaling. The project's golden-model + vectors + cocotb stack is
already tapeout-grade DV scaffolding - normally the expensive missing
piece.

**Commercial-node endgame (if demand proves out):** a 130nm-proven
design retargets to modern nodes as a routine design-services
engagement (~\$300k-1M physical implementation; RTL + DV carry over
whole) - 28nm is the sweet spot (~15x density, ~1 GHz, licensed
SerDes/DDR PHYs so chiplets grow their own host links; ~\$1-2M masks;
sub-\$2/tile at volume; roughly 100-1000x per die over 130nm).
Openness survives the closed fab because determinism converts trust
from structural to behavioral: RTL/netlists/DV/vectors stay
published, and every commercial part is continuously ATTESTED against
the open ladder (golden model, FPGA tiles, 130nm reference silicon) -
the OpenTitan posture with a stronger proof story. The founding
two-tier doctrine, one level down: the open chip is the reference
standard; the fast chip must prove itself identical.

Sizing basis: measured 6-LUT costs x ~1.8-2 for 4-LUT fabrics; the
fp256 unit's ~196 18x18 multiplies exceed ECP5-85F's 156 DSPs, which
is why the full tile needs the bigger parts.

## The adoption story these serve

Two tiers, one contract: a software library anyone can run on
anything (the GPU det library exists and is proven at one hash across
three vendors), and this hardware for people doing heavy compute -
same bits, more speed, and precision up to fp256 when the problem
needs it. The entry point stays a simple library; the tile only makes
it faster.
