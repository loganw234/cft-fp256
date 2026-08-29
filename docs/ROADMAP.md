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

| target | open flow | fits | role |
|---|---|---|---|
| **Alchitry Pt V2 (XC7A100T-2) - CHOSEN, 2026-08-29** | openXC7 (well-documented part; DSP inference immature) | full tile via free-tier Vivado day one (~79% LUTs, 165/240 DSPs); nano-tile via openXC7 now; open full tile when DSP support lands or via a serialized-multiplier variant | the platform: SparkFun-backed longevity, published schematics, 256MB DDR3L, FTDI JTAG, GTPs (future LitePCIe host link) |
| Alchitry Au V2 (XC7A35T-2, $150) | openXC7 on prjxray's reference part - the most mature open target there is | quarter-tile (4x fp32 + engine, ~67%) or one fp64 rung; fp256 physically impossible (needs 27.8k of 20.8k LUTs) | **the conformance node**: cheapest object that attests the contract; no transceivers (FTG256) but none needed - FT2232 USB at 8 MB/s replays vector sets in seconds, so an Au farm is a powered USB hub, no carrier required |
| ECP5-85F (ULX3S etc.) | Yosys+nextpnr, most mature | 8x fp32 bank + engine only | fallback nano-tile if boards resurface (scarce as of 2026-08) |
| Artix-7 200T | openXC7 | full tile even with LUT-fallback multipliers | the headroom alternative if open-full-tile-today ever becomes a hard requirement |
| Tang Mega 138K (GW5A) | Apicula, youngest flow | full tile (138k LUT4) | cheapest option - verify Apicula status first |

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
