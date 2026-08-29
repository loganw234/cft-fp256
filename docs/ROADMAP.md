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

## v0.x - hardware bring-up (needs the Vitis box + card)

Gates in docs/BRINGUP.md, in order: package_xo validates; hw_emu run
of the kernel test pattern; timing closure at a reduced clock; first
on-card `vector_fma.py` run bit-exact against the golden model; then
the same at every N and both precisions, plus flags.

**Done when:** the card reproduces `vectors/out/*.jsonl` exactly, and
the run is recorded (platform, XRT, tool versions, xclbin hash) the
way atlas-darkroom records a census.

## v1 - the fractured array and a real engine

- The fused significand array: one physical multiplier serving
  1x fp256 / 2x fp128 / 4x fp64 / 8x fp32 per half-beat with
  mode-gated partial products (granule tiling study in
  docs/ARCHITECTURE.md), pipelined to platform clock.
- fp64 and fp128 rungs wired through MODE[7:4] = 1, 2 (the golden
  model and vector sets already cover them - hardware catches up to
  the contract, not the reverse).
- Engine: AXI bursts, multiple outstanding, overlapped read/compute/
  write; multiple CUs with per-CU HBM pseudo-channel groups.
- Directed rounding modes (RZ/RU/RD) in the reserved MODE field -
  the interval-arithmetic unlock for scientific users.
- Reduction ops (dot, sum) with the index-fixed tree the contract
  already specifies.

## v2 - the coordinated part

- **Orbit/walk engine**: a micro-sequencer running iterated maps
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

## The adoption story these serve

Two tiers, one contract: a software library anyone can run on
anything (the GPU det library exists and is proven at one hash across
three vendors), and this hardware for people doing heavy compute -
same bits, more speed, and precision up to fp256 when the problem
needs it. The entry point stays a simple library; the tile only makes
it faster.
