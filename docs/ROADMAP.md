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

| | LUT | DSP |
|---|---|---|
| 8x fp32 lanes | 20,000 | 16 |
| 4x fp64 lanes | 18,800 | 36 |
| 2x fp128 lanes | 23,000 | 70 |
| 1x fp256 unit | 31,000 | 140 |
| arithmetic subtotal | 92,800 | **262** |
| engine, FIFOs, AXI plumbing, steering | 26,743 | 0 |
| **one 256-bit tile, measured** | **119,543** | **262** |
| one tile with four AXI masters | 128,741 | 262 |

The DSP column reconciles **exactly** - 262 predicted from the per-lane
ladder, 262 measured in the routed design - which is the reason to
trust the LUT column too, and the reason this table is usable for
sizing any other part.

Two consequences, and the first one is unwelcome:

**A full 256-bit tile does not fit on an Artix-7 100T.** 119,543 LUTs
against 63,400 is 189%, and 262 DSPs against 240 is 109%. The board was
ordered on a "full tile, ~79% LUTs" estimate that was simply wrong.
It is still the right dev board - it is openXC7 and LiteX's reference
target, which is worth more than width - but what comes up on it is a
narrower tile, not the U50's.

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
| **Arty A7-100T - dev board, ORDERED 2026-08-29** | openXC7 + LiteX treat it as their reference target - open bring-up on rails | NOT a full tile (189% LUT, 109% DSP). Estimated: a 128-bit-beat tile through the fp128 rung, ~44k LUT / ~69%, or a 256-bit fp32-only tile at ~74% | where the open tile comes up first, at reduced width; Ethernet/Etherbone streaming; no transceivers ever (CSG324) |
| **Alchitry Pt V2 (XC7A100T-2) - the module, x4 when bundled** | same silicon as Arty; port is an afternoon | same as Arty - reduced width, not a full tile | the carrier/quad future: GTPs -> LitePCIe, module ring, verified execution modes |
| Alchitry Au V2 (XC7A35T-2, $150) | openXC7 on prjxray's reference part - the most mature open target there is | the quarter tile as already built: 64-bit beats, 2x fp32 + 1x fp64, ~20k LUT estimated against 20,800 - tight, and the first thing to measure. fp256 remains physically impossible at any width | **the conformance node**: cheapest object that attests the contract; no transceivers (FTG256) but none needed - FT2232 USB at 8 MB/s replays vector sets in seconds, so an Au farm is a powered USB hub, no carrier required |
| ECP5-85F (ULX3S etc.) | Yosys+nextpnr, most mature | fp32 bank + engine at reduced width | fallback nano-tile if boards resurface (scarce as of 2026-08) |
| **Artix-7 200T** | openXC7 | **the only 7-series part that takes a full tile**: 119,543 of 134,600 LUT is 89%, and 262 of 740 DSPs is 35% - no LUT-fallback multipliers needed, contrary to the earlier note | the headroom option, and now the *only* open route to a full-width tile |
| Tang Mega 138K (GW5A) | Apicula, youngest flow | full tile on LUT count (138k LUT4) but LUT4s are not LUT6s - assume worse, and the DSP story is unverified | cheapest option - verify Apicula status first |

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

No open toolchain reaches 4-8-tile monolithic silicon (prjxray ends
at 7-series ~134k LUTs; prjuray is immature; big Lattice is closed) -
so the open machine scales OUT: a backplane of open-flow modules
(quad-Pt carriers; or used SQRL Acorn/NiteFury A200T M.2 modules -
openXC7's biggest part, PCIe-native, LiteX-supported, mining surplus)
joined by the deterministic module ring. The contract's index-fixed
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
