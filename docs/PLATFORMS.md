# Platforms

Which FPGA to buy, borrow or rent next, measured against the tile this
project actually builds. Surveyed 2026-09-05. Every capability figure
carries a source; every price carries a source and the date it was
seen. Where a number could not be verified it says so instead of
guessing - **UNVERIFIED** is a permitted answer here and appears
often.

This file does not replace docs/LAYOUTS.md, which is the catalogue of
mixes for the card the project owns. This is the catalogue of *cards*.

## The yardstick

Everything below is sized against the project's own measurements, not
against a vendor's marketing arithmetic. The constants:

| quantity | value | where it comes from |
|---|---|---|
| full tile, flattened (shipping settings) | **123,420 LUT** | 9f73107, 2026-09-02, docs/ROADMAP.md |
| full tile, hierarchy preserved (the sizing figure) | **131,386 LUT** | `hw/synth_attrib.tcl` on eb8ef2a, docs/LAYOUTS.md |
| DSP per tile | 292 ladders off / 277 ladders on | docs/SCALING.md |
| BRAM per tile | 16 | docs/LAYOUTS.md |
| fp128-max tile (drop fp256) | 96,053 LUT | 131,386 - 35,333, docs/LAYOUTS.md bank costs |
| fp64-max tile | 68,561 LUT | less the 27,492 fp128 bank |
| fp32-max tile | 43,257 LUT | less the 25,304 fp64 bank; LAYOUTS' "a third of a full one" |
| shell + one CU (U50) | 123,897 LUT | differenced routed builds, docs/SCALING.md |
| each further CU | +12,626 LUT | (161,775 - 123,897) / 3, docs/LAYOUTS.md |
| practical routing ceiling | ~85% | docs/SCALING.md; the routed quad closed at 80.6% |
| kernel clock | 135 MHz, -2 grade, retimed | 9f73107, docs/LAYOUTS.md |
| beat | 256 bits, one per cycle per stream | docs/ARCHITECTURE.md |
| streams | 3 in + 1 out = 4 AXI masters per tile | docs/ARCHITECTURE.md |
| measured cost | 1.250 cycles/beat marginal, 36 fixed | `make cycles`, docs/SCALING.md |

Two older figures appear in the brief and are kept here as the
historical lower bound, because they measure a different thing - out
of context, before the lane array was shared, before the sequencer:
fp32-only ~30k, through fp64 ~54k, through fp128 ~80k. The LAYOUTS
figures above are the current model and are larger, because the
~15,300 LUT of sequencer, engine, CSR and steering does not shrink
with the rungs. Size boards with the LAYOUTS numbers; the older ones
will flatter every part in this document.

### Per-tile memory demand, derived

One 256-bit beat is 32 bytes. At the measured 1.250 cycles/beat and
135 MHz, one stream retires 135e6 / 1.25 = 108e6 beats/s, so

* **per master: 108e6 x 32 B = 3.456 GB/s**
* **per tile (4 masters): 13.82 GB/s**

which reproduces docs/SCALING.md's ~3.3 and ~13.3 GB/s at its 130 MHz.
That 13.82 GB/s is the number every memory system below is measured
against.

## Method: how "how many tiles fit" is derived

Two budgets, because shell cards and bare parts are not the same
arithmetic and mixing them is how a board gets bought on a wrong
number.

**(A) Bare part.** No vendor shell. Budget is `device_LUT x 0.85`, and
the platform wrapper (PCIe, memory controller, whatever the open flow
needs) is **not counted** - the project has never built one, so every
bare-part fit below is an upper bound with the wrapper still to pay
for. Said once here rather than repeated in every row.

**(B) Alveo shell card.** AMD publishes, per platform and per SLR, the
LUTs left in the dynamic region: UG1120 states the table "represents
the total device resources after subtracting those used by the static
region"
([UG1120](https://docs.amd.com/r/en-US/ug1120-alveo-platforms), rev
2.0.1, 2023-10-11). Budget each SLR at 85% of that, and charge each
compute unit `131,386 + 12,626 = 144,012 LUT` - the tile plus the
project's own measured per-CU crossbar increment. Tiles do not straddle
SLRs, so the count is per SLR and then summed.

**The model is calibrated on the card the project owns.** U50 dynamic
region: SLR0 351K, SLR1 353K
([UG1120 U50 Gen3x16 XDMA base_5](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U50-Gen3x16-XDMA-base_5-Platform)).
At 85%: 298,350 and 300,050. Divided by 144,012: 2.07 and 2.08, so
**two tiles per SLR, four on the card** - which is exactly what
`u50-4xfp256` is, and it placed at 80.6%. A model that reproduces the
known answer is worth applying to the unknown ones.

**Which tile figure each budget uses, and why they differ.** Budget (B)
charges 131,386 - the hierarchy-preserved number docs/LAYOUTS.md sizes
with - because that is the figure the U50 calibration above was built
on and reproducing a known answer is the point. Budget (A) charges
123,420, the current flattened figure under shipping settings, because
a bare part has no shell build to calibrate against and the flattened
number is what a synthesis run would actually report. The two differ
by 6.5%, and every bare-part percentage in §2 and §3 would rise by
about that much if the conservative figure were used instead. Neither
is wrong; do not mix them within one comparison.

Note also the two *device* accountings differ and are not
interchangeable. UG1120's
"available" is a floorplan figure: 871,680 device LUTs less 704,000
dynamic leaves 167,680 for the static region *and* for fabric outside
the DFX pblock. The project's 123,897 "shell, one CU" is a utilisation
figure from differencing routed builds. Budget (B) uses the floorplan
number because that is the one that says where a CU may be placed.

## Shortlist

Prices are new unless the row says used. "Tiles" is budget (A) or (B)
as marked, and for open-flow rows read the 7-series penalty warning
below the table.

| candidate | device | LUT | DSP | BRAM / URAM | memory | host | tiles | free tools? | open flow? | price (date, source) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Alveo U55C** (used) | XCU55C / VU47P, 3 SLR | 1,304K | 9,024 | 70.9 Mb / 960 | 16 GB HBM2, 460 GB/s, 32 PC | Gen3 x16 | **6** (B) | Alveo tier | no | **$8,834+** asks (2026-09-05, PicClick) - get a distributor quote |
| **Alveo U280** (used) | XCU280 / VU37P, 3 SLR | 1,304K | 9,024 | 2,016 / 960 | 8 GB HBM2 460 GB/s + 32 GB DDR4 38 GB/s | Gen3 x16 / Gen4 x8 | **6** (B) | Alveo tier | no | **$5,750** (2026-09-05, IT Creations) - **discontinued, RMA closed** |
| **Alveo U250** (used) | XCU250 / VU13P, 4 SLR, **-2L** | 1,728K | 12,288 | - / 1,280 | 64 GB DDR4, 77 GB/s, 4 banks | Gen3 x16 | **7** area, **~5** bandwidth (B) | Alveo tier | no | **$3,499.99** (2026-09-05, eBay) |
| **Alveo U200** (used) | XCU200 / VU9P, 3 SLR, **-2L** | 1,182K | 6,840 | - / 960 | 64 GB DDR4, 77 GB/s, 4 banks | Gen3 x16 | **5** area, **~5** bandwidth (B) | Alveo tier | no | **$1,150-$1,373** (2026-09-05, PicClick) |
| **Alveo U50 / U50LV** (owned) | XCU50 / VU35P, 2 SLR | 872K | 5,952 | 1,344 / 640 | 8 GB HBM2, 316 GB/s, 32 PC | Gen3 x16 / Gen4 x8 | **4** (B, built) | Alveo tier | no | owned |
| **BittWare CVP-13** (used, bare) | VU13P, 4 SLR | 1,728K | 12,288 | 94.5 Mb / 1,280 | 4x DDR4 64-bit | **no shell** - DIY XDMA | **8** (A) | **NO - paid Core tier** | no | **$1,200** (2026-09-05, PicClick/eBay) |
| **SQRL BCU1525** (used, bare) | VU9P, 3 SLR | 1,182K | 6,840 | 75.9 Mb / 960 | 4x DDR4 64-bit | **no shell** - LiteX target exists | **6** (A) | **NO - paid Core tier** | no | **$395-$940** (2026-09-05, PicClick/eBay) |
| **KCU116** | XCKU5P-2FFVB676E | 217K | 1,824 | 16.9 Mb / 64 | DDR4 "up to 32-bit" | Gen3 x8 | **1** at 56.9% (A) | **yes, Basic** | no | $6,495 (2026-09-05, AMD store) |
| **VC707** | XC7VX485T-2FFG1761 | 304K | 2,800 | 37,080 Kb | 1 GB DDR3 SODIMM 64-bit | Gen2 x8 | **2** at 81.3% (A) | **yes, Basic** | **yes** | $5,995 new (2026-09-05, AMD store); used see §2 |
| **QMTech / STLV7325-class K7** | XC7K325T | 204K | 840 | 445 | DDR3, board-dependent | board-dependent | **1** at 60.6% (A) | **yes, Basic** | **yes** | see §3 |
| **Kintex-7 480T board** | XC7K480T | 299K | 1,920 | 955 | board-dependent | board-dependent | **2** at 82.7% (A) | **yes, Basic** | **yes** | see §3 |
| **Nexys Video / AX7A200** | XC7A200T | 135K | 740 | 365 | DDR3 | USB / board | **1** at 91.7% - do not plan on it | **yes, Basic** | **yes** | see §3 |
| **Arty A7-100T** (ordered) | XC7A100T | 63.4K | 240 | 135 | 256 MB DDR3L | USB / Ethernet | fp32-max at **68%** | **yes, Basic** | **yes** | ordered 2026-08-29 |
| **Alchitry Au V2** | XC7A35T | 20.8K | 90 | 50 | DDR3 | FT2232 USB | quarter tile, ~96% | **yes, Basic** | **yes** | see §3 |
| **AWS F2** (rent) | VU47P | 1,304K | 9,024 | 70.9 Mb / 960 | 16 GB HBM + 64 GB DDR4 | Gen4 x8 | n/a - **Vitis cannot make an AFI** | n/a | no | $1.98/h us-east-1 (2026-09-06, AWS feed) |
| **AWS F1** (rent) | VU9P | 1,182K | 6,840 | 2,160 / 960 | 64 GB DDR4 | Gen3 x16 | n/a - 2022.2 unsupported | n/a | no | $1.65/h us-east-1 (2026-09-06, AWS feed) |
| **Azure NP** (rent) | U250 | 1,728K | 12,288 | - / 1,280 | 64 GB DDR4 | - | n/a - **attestation closed** | n/a | no | $1.65/h East US (2026-09-05, Azure API) |

Device resource figures: Alveo from
[DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/Alveo-Product-Details),
[DS963](https://docs.amd.com/r/en-US/ds963-u280/Alveo-Product-Details),
[DS965](https://docs.amd.com/r/en-US/ds965-u50/Product-Details),
[DS978](https://docs.amd.com/r/en-US/ds978-u55c/Product-Details);
silicon from [DS890 v4.10,
2026-05-21](https://docs.amd.com/v/u/en-US/ds890-ultrascale-overview)
and [DS180 v2.6.1,
2020-09-08](https://docs.amd.com/v/u/en-US/ds180_7Series_Overview).

**Read every 7-series row as optimistic.** They are sized with
UltraScale+ measurements and the carry structure differs: the fp256
adder uses 21 CARRY8 per critical path, which becomes 42 CARRY4 on
7-series (docs/ROADMAP.md). And openXC7 splits wide multiplies into
18x18 partials rather than Vivado's 25x18, so a tile there should be
counted near 390-400 DSPs rather than 292 - which raises every
7-series DSP percentage by about 1.5x and, on every row above, still
flips no verdict.

## 1. Used data-centre cards

### The tiles-per-card arithmetic, in full

Budget (B), from UG1120's per-SLR dynamic-region LUTs, at 85%, divided
by 144,012 LUT per CU.

| card | SLR dynamic LUT | at 85% | tiles per SLR | **card total** |
|---|---|---|---|---|
| U50 (known good) | 351K / 353K | 298.4K / 300.1K | 2 / 2 | **4** |
| U200 | 388K / 205K / 385K | 329.8K / 174.3K / 327.3K | 2 / 1 / 2 | **5** |
| U250 | 420K / 205K / 407K / 424K | 357.0K / 174.3K / 346.0K / 360.4K | 2 / 1 / 2 / 2 | **7** |
| U280 | 386K / 364K / 381K | 328.1K / 309.4K / 323.9K | 2 / 2 / 2 | **6** |
| U55C | 386,880 / 364,320 / 395,040 | 328,848 / 309,672 / 335,784 | 2 / 2 / 2 | **6** |

Sources: [U50](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U50-Gen3x16-XDMA-base_5-Platform),
[U200](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U200-Gen3x16-XDMA-base_2-Platform),
[U250](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U250-Gen3x16-XDMA-4_1-Platform),
[U280](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U280-Gen3x16-XDMA-base_1-Platform),
[U55C](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U55C-Gen3x16-XDMA-base_3-Platform),
all UG1120 rev 2.0.1.

**SLR1 is where the U200 and U250 lose their advantage.** It carries
the static region on both parts, so its dynamic budget is 205K against
its neighbours' 385-424K - one tile where the others take two, and
1.21 tiles' worth of budget spent on one. A U250 whose 1,456K of
dynamic LUT were flat would take 8.59 tiles at 85%; SLR quantisation
costs it 1.6 of them.

DSP is not close to binding anywhere: seven tiles on a U250 is 2,044
of 10,634 dynamic DSPs, 19%.

### Then memory takes some of it back

Per-tile demand is 13.82 GB/s (derived above). Against each card's
published aggregate:

| card | memory | aggregate | tiles at 100% efficiency | binding wall |
|---|---|---|---|---|
| U50 | 8 GB HBM2, 32 PC | 316 GB/s peak / 201 GB/s nominal | 22.9 | **area at 4** |
| U55C | 16 GB HBM2, 32 PC | 460 GB/s | 33.3 | **area at 6** |
| U280 | 8 GB HBM2, 32 PC | 460 GB/s | 33.3 | **area at 6** |
| U250 | 64 GB DDR4, 4 banks | 77 GB/s | **5.57** | **memory at ~5, below the area wall of 7** |
| U200 | 64 GB DDR4, 4 banks | 77 GB/s | **5.57** | area and memory both ~5 |

HBM figures: [DS965](https://docs.amd.com/r/en-US/ds965-u50/Product-Details)
("The nominal bandwidth for HBM2 is 201 GB/s. Peak HBM2 bandwidth
measured ... is 316 GB/s in the non-PCIe compliant specification"),
[DS978](https://docs.amd.com/r/en-US/ds978-u55c/Product-Details),
[DS963](https://docs.amd.com/r/en-US/ds963-u280/Alveo-Product-Details).
DDR4: [DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/Alveo-Product-Details)
("DDR total bandwidth 77 GB/s", four 16 GB 2400 MT/s 64-bit ECC DIMMs).

5.57 is an upper bound and should be read as one. It assumes DDR4 at
100% of peak, which no controller delivers under four interleaved
streams per tile; the honest reading is that a U250 is a
**four-to-five tile card in practice**, not a seven-tile one. The
efficiency haircut is an estimate, not a measurement, and is the
single largest unverified number in this document.

### The HBM side, from the controller's own product guide

Worth stating precisely, because it is what a DDR4 card would be giving
up and because it settles two numbers this repo has been carrying.
From [PG276 rev 1.0,
2025-12-17](https://docs.amd.com/r/en-US/pg276-axi-hbm):

* **"16 independent 256-bit ports"** per stack, with "Expansion to 32
  AXI ports for dual stack configurations". "Each port operates at a
  4:1 ratio to lower the clock rate required in the user logic. This
  ratio requires a port width of 256-bits (4 x 64)."
  **The kernel's 256-bit masters are exactly the port width** - no
  width conversion anywhere on an HBM card, which is not true of DDR4.
* **The ordering argument is the vendor's, not just the project's.**
  "On the selected AXI3 channel, if the transactions are triggered
  using a different ID tag, then the transactions are reordered as per
  the AXI3 protocol. Conversely, if the selected AXI3 channel
  transactions are triggered using same ID tag, then the transactions
  are executed sequentially in the order they are triggered." That is
  docs/SCALING.md's single-ID-per-master rule, stated by AMD. (Note
  PG276's abstract says "AXI4 slave ports" while its body says AXI3
  throughout; the body is the more specific claim.)
* Each port accepts 64 outstanding reads and 32 writes, and carries a
  6-bit AXI ID.
* **"Pseudo channel memory access is limited to its own section of the
  memory (1/16 of the stack capacity)."** With 8 GB across 32 pseudo
  channels, that is **256 MB per pseudo channel** - which is where
  docs/SCALING.md's 256 MB per-argument-buffer cap comes from, and it
  can now be cited rather than asserted. On a **U55C the same
  arithmetic gives 512 MB** (16 GB / 32).

### What DDR4 does to this design

The brief asks the question directly. Five consequences, in order of
how much they matter.

**1. It does not change the beat, and that is the good news.** The
kernel's masters are 256 bits wide and stay that way. A DDR4 bank on
these platforms delivers 19.2 GB/s (77 GB/s / 4 banks), which at the
platform's 300 MHz default clock
([UG1120](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U250-Gen3x16-XDMA-4_1-Platform):
"The platform provides a 300 MHz default clock") is exactly a 512-bit
port: 512 bits x 300 MHz = 19.2 GB/s. `v++` inserts the width
converter. `BEAT_BITS` does not move, `cft_lanes` does not change, and
no rung is affected. **Porting to a DDR4 card is a link-configuration
change, not a datapath change.**

**2. Port count collapses from 32 to 4, and that is the bad news.**
The U50 exposes 32 pseudo-channels and the project spends four per
tile precisely so that each master owns one - done for ordering, so
that same-ID responses arrive in issue order by construction rather
than by trusting a switch across destinations (docs/SCALING.md). A
U200 or U250 has **four memory controllers in total**. Five tiles are
twenty masters on four controllers, five masters deep.

**3. The ordering argument survives that, but it needs re-stating
rather than assuming.** AXI orders same-ID responses from a single
slave. Each master still issues one ID and, if `--sp` pins it to one
DDR bank, still addresses one slave - so per-master ordering holds
even when several masters share a bank. What sharing costs is
bandwidth and latency variance, not correctness. **This is a
derivation from the AXI ordering rule, not something this project has
measured on a DDR4 platform, and it is the first thing to check on a
U250.**

**4. The 256 MB buffer cap disappears.** One HBM pseudo-channel is 256
MB, which is the per-argument-buffer-per-tile cap libcft does not
capacity-split (docs/SCALING.md). A DDR4 bank is 16 GB
([DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/Alveo-Product-Details)).
That is a 64x increase in the largest run a tile can take without
host-side splitting, and for the deep-zoom and orbit workloads it is a
real gain rather than a curiosity.

**5. And the workload the tile exists for is not the one being
penalised.** 13.82 GB/s per tile is the **elementwise streaming**
worst case: three operand streams and a writer, one beat per cycle,
every cycle. A sequencer run is a different shape. docs/ATLAS.md's
positives become "a sequencer program image, a constant bank, a stream
layout and a deposit schema" - the program and its sixteen constants
live on-chip, `s.orbit` becomes `REPEAT`/`ENDREP` executing many
instructions per sample, and the traffic is the deposits rather than
three streams at line rate. **Per unit of arithmetic, a sequencer
program moves far less memory than an elementwise run**, so the DDR4
bandwidth ceiling above bites hardest on precisely the mode
CAPABILITIES.md and the README already decline to sell (raw fp32/fp64
throughput) and least on the atlas workload the tile is for.

That is a genuine argument in a DDR4 card's favour and it is left
un-quantified deliberately: no sequencer program has been measured for
bandwidth, on any memory, and `make cycles` covers the streaming
engine only.

**6. Latency is unmeasured.** The 1.250 cycles/beat figure was
measured against cocotbext-axi's `AxiRam`, which docs/SCALING.md
already declines to call a prediction for HBM. It is even less of one
for DDR4, where a row miss costs far more and the engine's 16-beat
512-byte bursts become 8 beats on a 512-bit port. The engine pipelines
address phases and holds 128-beat FIFOs, so it should absorb it. Should.

### Shell-less bring-up, and why it might be the point

Every Alveo card can also be treated as a bare board: build an XDMA
design in Vivado against `xcu250-figd2104-2L-e` (or whichever part),
write the DDR4/HBM controllers yourself, and drive it with the XDMA
driver instead of XRT. What that buys and costs:

* **AMD supports it as a first-class flow and ships the constraints.**
  Every Alveo support page carries a **"Vivado Design Flow"** tab
  beside the Vitis one - "The following files are to be used when
  targeting Alveo Accelerator Cards using a traditional RTL design
  flow using Vivado Design Suite" - offering the card's XDC and board
  files (for the U55C: `U55C_xdc_1v00.xdc` and
  `au55c_boardfiles_v1_0_20211104.zip`) plus the `xbflash2` utility
  for programming a custom image onto the flash over PCIe
  ([U55C
  downloads](https://www.amd.com/en/support/downloads/alveo-downloads.html/accelerators/alveo/u55c.html),
  checked 2026-09-05). Shell-less is a documented option with vendor
  pin constraints, not a workaround.
* **It dissolves the era-matched-tools problem.** The U50 platform's
  encrypted shell IP is why `v++ -l -t hw` is impossible from 2026.1
  (Synth 8-5809, docs/BRINGUP.md). A shell-less design contains no
  encrypted vendor IP, so a current Vivado builds it. Note that the
  U200 platform was "Created by 2021.1 tools" and the U250's by
  2022.1 ([UG1120](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U200-Gen3x16-XDMA-base_2-Platform)),
  so a used U200/U250 **reproduces** the era problem rather than
  escaping it - the U200's keys are a year older than the U50's.
* **It recovers the static region.** A U250 gives 1,728,000 LUT
  instead of 1,456,000: +19%.
* **It is the only path on Windows.** See §6.
* **It costs the whole host stack.** XRT, pyxrt, `cftx_open`, the
  xclbin-as-partial-bitstream layout swap of docs/LAYOUTS.md, and the
  CU discovery loop all assume a Vitis shell. None of it survives.
* **Thermal and power supervision needs checking before it is
  trusted.** UG1120 publishes clock-throttling and shutdown thresholds
  per platform. Whether those are enforced by the card's satellite
  controller (independent of the FPGA image) or by logic inside the
  shell is **UNVERIFIED**, and on a 215 W card it is not a detail to
  guess at.

### Cooling and power, which decides what fits in the lab

| card | total card load | cooling | form factor | AUX power |
|---|---|---|---|---|
| U50 / U50LV | 75 W | passive | half height, half length | none |
| U55C | 150 W total, 115 W TDP | passive | full height, half length | yes |
| U280 | 215 W | passive **or** active | ¾ length (P) / full length (A), dual width | 150 W PCIe AUX required |
| U200 / U250 | 215 W | passive **or** active | ¾ length (P) / full length (A), dual width | 150 W PCIe AUX required |

From DS962/DS963/DS965/DS978 as cited above. DS962: "The CEM card
requires that a 150W PCIe AUX power cable be connected to the card."

**Buy the active SKU for a workstation.** `A-U200-A64G-PQ-G` and
`A-U250-A64G-PQ-G` carry fans; the `-P64G-` passive parts are
data-centre parts that assume ducted chassis air and will throttle or
shut down in a desktop (UG1120 Table 3 lists 92 °C throttle / 97 °C
shutdown on the FPGA sensor). The U55C is passive only, which makes it
the one HBM candidate that needs a real airflow answer before it is
bought. The project's own U50C is a custom active unit at 75 W, which
is why cooling has not yet been a problem (docs/BRINGUP.md).

### Documented bring-up hazards

* **U250 needs its shell partition reprogrammed after every reboot.**
  The U250 platforms are DFX-2RP two-stage: `xilinx_u250_gen3x16_xdma_2_1_202010_1`,
  `..._3_1_202020_1`, `..._4_1_202210_1`. AMD: "Prior to running an
  application on DFX-2RP two-stage platforms, it is necessary to first
  program the shell partition on the card, or else the application will
  fail to detect the shell and will not run" - and "the shell partition
  is not persistent and needs to be reloaded after both a cold and warm
  reboot"
  ([AR 75975](https://adaptivesupport.amd.com/s/article/75975?language=en_US),
  article dated 2022-04-26). The U50 platform is single-stage and has
  no equivalent step, so this is a new failure mode, not a familiar
  one. The U200 platform (`xdma_base_2`) is not on the DFX-2RP list.
* **Platform XRT support windows are documented as closed - but the
  packages are still published, and re-dated.** UG1120 says of the
  U50, U55C, U200, U250 and U280 platforms alike: "Supported XRT
  versions: 2022.1 with support planned through 2023." That window has
  passed. What AMD's download pages actually offer today is better
  than that reads. The U55C page, checked 2026-09-05, presents its
  Vitis section as **"Vitis Design Flow - Vitis 2025.1"** and serves:

  | package | filename |
  |---|---|
  | Xilinx Runtime | `xrt_202510.2.19.194_...` |
  | Deployment platform | `xilinx-u55c-gen3x16-xdma_2024.1_2024_0522_2343-noarch.rpm.tar.gz` |
  | Development platform | `xilinx-u55c-gen3x16-xdma-3-202210-1-dev-1-3514517.noarch.rpm` |

  ([Alveo U55C support and
  downloads](https://www.amd.com/en/support/downloads/alveo-downloads.html/accelerators/alveo/u55c.html)).

  So the **development** platform is still the `202210_1` generation
  UG1120 documents - the 2022.2 era - while the deployment package is
  a 2024-dated re-release and the runtime is XRT 2.19. **That is
  exactly the pairing docs/BRINGUP.md already found and runs**:
  "xclbins built by 2022.2 run under the newer XRT 2.19 runtime -
  that pairing is what AMD's own 2024.1 U50 deployment re-release
  ships." A U55C would not introduce a second toolchain era; it would
  use the one already installed.
* **Above 4G Decoding** in BIOS, or the card does not enumerate
  (docs/BRINGUP.md). Already confirmed active on the Windows box and
  unconfirmed on amd-arc-box's X99-UD4.
* **A used card carries no entitlement.** See §5.

### Per-card notes and used-market prices

**On the prices below.** All observed **2026-09-05**. eBay, Digi-Key
search, Colfax, Amazon and archive.org all refuse automated fetching,
so eBay figures come through **PicClick, a live eBay mirror**, and are
**asking prices on active listings, not sold prices**. No sold-price
data could be obtained at all - that is the weakest evidence in this
document and the gap most worth closing by hand.

#### Alveo, card by card

**U50 (owned).** `A-U50-P00G-PQ-G`. **$2,294.99-$2,499.99** for
HPE-branded bulk (`P24826-001`, `R4B02C`), $2,359 for a bare retail
card, most listings $4,500-$6,374
([PicClick](https://picclick.com/?q=alveo+u50)). One hazard worth
knowing about the card the project already owns: AMD's UG1370 warns
that the **HBM sits on a 10 W rail** and that this "may limit HBM
performance (see AR75222)". 316 GB/s and a full fabric are unlikely to
coexist inside 75 W. At four tiles the design asks 55 GB/s of it, so
this is a note for the record rather than a problem.

**U50LV.** Identical silicon; the only difference is core voltage
(VLOW 0.72 V against VNOM 0.85 V,
[DS965](https://docs.amd.com/r/en-US/ds965-u50/Summary)). Its only
shell is **Gen3 x4**, which AMD calls "application specific ... only
used with an application". **A bad development card**; no dated
listing found.

**U50C.** Not a public product. The name appears only in XCN23004 as
an internal grouping of U50-derived blockchain boards, all replaced by
the Varium C1100. No datasheet, no shell, no XRT platform.

**U200 - the cheapest supported-shell Alveo, by a lot.** **$1,150**
(passive, buy-it-now) and **$1,373.13** ("tested working"), ranging to
$8,489 ([PicClick](https://picclick.com/?q=alveo+u200)). Five tiles by
this document's arithmetic. Base SKUs are **not discontinued** -
XCN23004 (2023-05-29) retired only the SCD and dev-kit variants and
named the standard SKUs as their replacements.

**U250.** **$3,499.99 "New Sealed"** on eBay (listing 226818777716,
seen via mirror 2026-09-05) is the lowest found; then $4,497-$4,500,
clusters at $7,450-$8,445, up to $13,999
([PicClick](https://picclick.com/?q=alveo+u250)), and $14,253.52 from a
new-channel broker (page dated 2025-02-26). Seven tiles. Not
discontinued.

Its DDR4 is **four socketed 288-pin single-rank Micron
MTA18ASF2G72PZ RDIMMs**, 72-bit with ECC
([DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/DDR4-Specifications))
- **socketed, so a used card can arrive without them.** "Card only"
listings are common in this market; confirm all four DIMMs are present
and populated, on the U200 as well.

One structural reason to prefer the U250 over the U200 beyond tile
count: **the U250 gets one DDR bank per SLR**, while the U200's mapping
is lopsided - DDR[0] to SLR0, DDR[1] to SLR1 (in the static region),
and **both DDR[2] and DDR[3] to SLR2**. For a design that wants a tile's
four masters close to their memory, one-per-SLR is the better shape.

**U280 - the worst value here.** **$5,750.00** used at [IT
Creations](https://www.itcreations.com/product/141294) (page
timestamped 2026-09-05 19:38 PDT) and $6,295.00 for the
`AU280-P-08G-PQ-G`; eBay asks $12,888-$13,821. And it is
**discontinued**: XCN23008 v1.0, 2023-11-13, retires all three U280
part numbers with `A-U55C-P00G-PQ-G` as the replacement, **last time
buy 2023-12-31, last time ship 2024-03-31, RMA closed 2024-12-31**
([XCN23008](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/5731/XCN23008.pdf)).
So it costs more than the card AMD says replaces it, has half the HBM,
and carries no manufacturer recourse.

**U55C.** **$8,834-$14,201**, all listed "New" from Chinese resellers
([PicClick](https://picclick.com/?q=alveo+u55c)). Used supply is thin
and expensive - it is the current product and the U280's designated
replacement, so **get a distributor quote before paying an eBay ask**;
these may not be a real discount on new. Airflow, precisely: **512 LFM
/ 11.0 CFM at a 25 °C inlet, rising to 1,189 LFM at 55 °C**
([DS978](https://docs.amd.com/r/en-US/ds978-u55c/Operating-Conditions)),
temperature limits 88/97/107 °C. Its AUX is an 8-pin PCIe connector
and DS978 warns explicitly: "The PCIe AUX 8-pin connector is not
compatible with an ATX12V/EPS12V power cable source." Slot-only gives
75 W against a 150 W card.

#### Speed grade: the U200 and U250 are -2L, and the U50 is not

This is the sharpest single finding in the used-card research and it
bears directly on recommendation (c).

| card | device string | grade |
|---|---|---|
| U50 (owned) | `xcu50-fsvh2104-2-e` | **-2** (docs/BRINGUP.md) |
| KCU1500 | `XCKU115-2FLVB2104E` | **-2** ([UG1260](https://docs.amd.com/r/en-US/ug1260-kcu1500-data-center/Board-Features)) |
| **U200** | `XCU200-L2FSGD2104E` | **-2L** |
| **U250** | `XCU250-L2FIGD2104E` | **-2L** |
| VCU1525 | `XCVU9P-L2FSGD2104E` | **-2L** |

Only the KCU1500 string comes from docs.amd.com; the other three are
from a third-party mirror of UG1289 and UG1268, with the grade decoded
against DS890's ordering-code figure. Treat the three as strong but
not first-party.

**Why it matters.** Per DS890, **-2L is dual-voltage**: at 0.72 V it
performs like a plain UltraScale part at about 30% less power, and at
0.85 V it runs "over 30% faster". So a -2L at 0.85 V is roughly a -2,
and a -2L at 0.72 V is materially slower. **Which VCCINT the Alveo
deployment shell actually programs is UNVERIFIED.**

The project's kernel closes at 135 MHz with **+0.143 ns** of slack on
the quad (docs/LAYOUTS.md) - a margin that a slower voltage-speed
operating point would eat outright. **Do not assume a U200 or U250
reaches the U50's clock.** Verify the operating voltage on the card
before committing to any Fmax, and treat 135 MHz as a hypothesis there
rather than a carried-over result. Nothing similar applies to the
U55C, whose grade was not established either but which at least shares
the U50's HBM-part lineage.

#### The SmartNICs and video cards: ruled out, with reasons

**U30 - AMD says in writing it is not programmable.** Two XCU30
devices per card, each 230K LUT / 1,728 DSP / 312 BRAM / 96 URAM with
4 GB DDR4 - a resource fingerprint matching **ZU7EV** exactly (DS970
v1.3 against XMP104 v2.8), so 460K LUT of real fabric on a 25 W
passive HHHL card with PCIe Gen3 x8 bifurcated into 2x x4. The
[product
advisory](https://www.xilinx.com/content/dam/xilinx/publications/alveo-u30-limitations.pdf)
kills it: Vivado support is "No support"; "There are no design
examples, reference designs, Vivado board or xdc files available or
planned"; "There are not Vitis Platform deliverables available for
kernel compilation, the Alveo U30 provide a fixed Video Transcode
solution." XRT lists it only as a device to flash a fixed shell onto.
EOL. It sells for **$99-$500**, and it is worthless for this.

**U25 - real fabric, no public base platform.** XCU25 is an
**XCZU19EG-FFVC1760**, whose PL is 522,720 LUT / 1,968 DSP - about
three tiles by this document's arithmetic. **$335-$700** on the used
market against $2,439 new. But the base platform is not published
("Base stage is not public"), the boot mode is strapped to QSPI by a
0-ohm resistor requiring **0201 rework** to boot over JTAG, and the
NIC firmware is signed. It is a bare ZU19EG board to be brought up
from nothing, in SmartNIC clothing. Cheap fabric, expensive months.

**U25N.** A different part (XCU25N) for which **AMD publishes no
LUT/DSP/BRAM figures at all**, absent from the XRT platform list, with
"shell programming" meaning flashing a signed prebuilt image. **$750**,
one listing. Not a candidate.

#### The pre-Vitis developer cards

**VCU1525 - the U200's die without the shell tax.**
`XCVU9P-L2FSGD2104E`, four independent 64-bit DDR4 channels. Its shell
was `xilinx_vcu1525_xdma_201830_1` on **SDx/SDAccel 2018.3**, and it is
**absent from the XRT supported-platform list** - an SDAccel-era DSA,
not a Vitis card. AMD's board documentation has largely gone
(`ug1268-vcu1525-*` 404s in both forms), though the 2018.3
development-shell digests file was still live on AMD's CDN on
2026-09-05, which suggests the `.deb` may still be fetchable. EOL via
XCN18025, 2018-10-29. Plan on a bare Vivado/XDMA design.

Power ladder, which is unusually clearly documented (UG1268):
**75 W slot-only caps VCCINT at 35 A / 150 W with a 6-pin gives 110 A /
225 W with an 8-pin gives 160 A.**

**$1,500** with active cooling
([PicClick](https://picclick.com/?q=vcu1525)), with a $600-$1,300 range
reported on Hacker News dated 2024-07-27.

The strategic point: **it is the same VU9P die as the U200 with none of
the shell tax.** The U200's `base_2` shell takes roughly 189K LUT out of
SLR1, leaving 388K/205K/385K; a bare VCU1525 offers the full 394,080
per SLR in all three. At 85% and 123,420 per tile that is 2 per SLR
either way by this document's arithmetic - **6 tiles bare against the
U200's 5** - with the PCIe endpoint, DDR4 controllers and interconnect
still to come out of the same budget. A modest win, and only if a bare
design was going to be written anyway.

**VCU1550 does not exist.** No AMD document names it and PicClick
returns no items. It is most likely a conflation of the VCU1525
(VU9P), the VCU118 (VU9P dev board) or the VCU128 (VU37P HBM dev
board); the VU13P card of that era is the third-party BCU1525 / CVP-13.

**KCU1500 - ruled out on power, not just tooling.** `XCKU115-2FLVB2104E`:
**663,360 LUT, 5,520 DSP, 75.9 Mb BRAM, no UltraRAM at all** (UltraRAM
postdates UltraScale), 2 SLRs. Absent from the XRT platform list. From
[UG1260](https://docs.amd.com/r/en-US/ug1260-kcu1500-data-center/Board-Features):

* **PCIe x8, or x16 bifurcated into two x8** - it never presents a
  single x16 link, so roughly half a U200's host bandwidth and a
  different driver model;
* **16 GB DDR4-2400 soldered, and only three of the four banks carry
  ECC**;
* **75 W, slot power only, no aux connector**, with VCCINT_FPGA at
  0.95 V and **30 A** - a hard ceiling on how much of the KU115 can be
  lit at all. That is the disqualifier: three tiles of arithmetic
  cannot be powered from 30 A of VCCINT with any confidence.

Fully EOL and dated: XCN19018 v1.0, 2019-08-19, with
`A-U200-A64G-PQ-G` as the replacement, **last orders 2019-10-31, last
shipments 2019-11-29**. **$575** for one listing, then $3,830-$4,209
from drop-shippers.

One trap: **XCN19018 itself calls it "Kintex UltraScale+"**. It is
XCKU115, Kintex UltraScale, with no UltraRAM. Do not let a seller's
copy-paste of AMD's own typo sell it as an UltraScale+ part.

#### BittWare and Alpha Data - and the entitlement wall

**XUP-P3R** (VU9P, -2, four DIMM sites, PCIe x16 Gen3 + x8 Gen4,
double-width active, 6-pin AUX): production, but the flow is Vivado +
BittWorks II + **SDAccel** - no Vitis/XRT shell. **$5,580** and
**$5,690.86**.

**XUP-VV4** (VU13P in a lidless D2104, -2, up to 128 GB per DIMM site,
PCIe x16 Gen3, **double-width passive**, 8-pin AUX, **operating 5-35 °C
only**): **legacy** in BittWare's own words - "not recommended for new
designs ... development tools and software are no longer maintained for
compatibility with the latest FPGA tools and operating systems".
**$2,250** card-only.

**520N** (Intel Stratix 10 GX2800, PCIe x16 Gen3, 32 GB DDR4, 225 W
typical, 8-pin + 6-pin AUX, active): **obsolete** - "no longer
available for purchase". **$2,000-$2,499.99**, both the Molex-branded
520N-MX variant.

**The wall that applies to all three:** BittWare's BSPs, BittWorks II
and example projects live behind `developer.bittware.com`, which
requires an account tied to *your purchased products*. **A second-hand
card carries no entitlement**, and for the obsolete 520N there is no
route to buy one. Assume the OpenCL BSP is unobtainable and that a
bare PCIe/DDR4 design is the only path.

**Alpha Data ADM-PCIE-9V7** (XCVU13P-2, 4x 8 GB DDR4-2666 ECC, PCIe
Gen3 x16, **single-slot passive**), **9H7** (XCVU37P-2E, 8 GB HBM2,
Gen3 x16 / Gen4 x8) and **9V5** (XCVU9P-3): all **EOL, last order
2024-10-31**, all using Alpha Data's own ADXDMA driver rather than
XRT. No dated listings found. The 9V7's single-slot passive form
factor is unusual and would be attractive if one surfaced.

#### Intel / Altera

**PAC with Arria 10 GX** (`10AX115N2F40E2LG`, 427,200 ALM, 1,518 DSP,
2x 4 GB DDR4-2133, PCIe x8 Gen3 electrical, **66 W slot-only**,
passive): the stack is OPAE pinned to **Quartus Prime Pro 17.0.0 +
OPAE 0.13.1 on RHEL 7.6**, and **Intel OFS does not support Arria 10**
- OFS 2025.1-1 covers only Agilex 7 and the D5005. A software dead
end. No dated listing found.

**PAC D5005** (`1SX280HN2F43E2VG`, Stratix 10 **SX** 2800 with a quad
Cortex-A53, 11,520 18x19 multipliers, 229 Mb M20K, **4x 8 GB DDR4-2400
RDIMM = 32 GB**, PCIe Gen3 x16, **215 W with a mandatory 2x4 AUX**,
passive "requires server air flow"): the only Intel card here with
living tooling, still listed in OFS 2025.1-1. But OFS 2024.2-1 needs
**Quartus Prime Pro 23.4 with a licence patch plus a separate licensed
10G Ethernet MAC IP**, VT-d/IOMMU, and a custom `6.1.41-dfl` kernel on
RHEL 8.6. Bare silicon lists at **$20,133.96** on Digi-Key; the board
is listed but not available and **no dated used listing was found**.

**The whole PAC line is EOL** - PDN2211, 2022-03-11, covering PAC A10
GX, N3000 and D5005, last orders July 2022, final shipments
2023-03-10.

**There is no Intel PAC with HBM2.** The Stratix 10 MX HBM board is
the **BittWare 520N-MX**: MX2100 in F2597, **16 GB HBM2 at 410 GB/s**,
PCIe x16 Gen3, 225 W, 8-pin + 6-pin AUX, active. Its ALM/DSP/M20K
counts are UNVERIFIED.

**Nallatech** merged into BittWare in 2018. The **385A** is Arria 10 GX
1150 with **DDR3**, PCIe x8 Gen3, 75 W slot-only, HHHL active -
**obsolete**. The **385A-SoC** is a smaller Arria 10 SX 660 -
**obsolete**. No dated listings for any Nallatech card.

**And a units warning for all of the above.** Altera publishes ALM
structure - "eight inputs with a fracturable look-up table ...
implementing all 6-input logic functions" - but **no ALM-to-LUT6
conversion and no per-device ALM count in the family plan**. Do not
compare 123,420 AMD LUT6 against Intel's "1,150 K logic elements"; LE
is a legacy 4-LUT equivalence that overstates capacity by roughly 9x.
On the published ALM structure roughly 1 ALM covers 2 LUT6, which
would put the A10 GX 1150 near 6-7 tiles of raw fabric - **that is
reasoning, not a cited conversion**, and for this design the A10's
1,518 DSPs is likely the real ceiling anyway.

#### The finding that reframes this section: bare mining-era cards

Not in the brief, and the best fabric-per-dollar found anywhere.

**BittWare CVP-13** - the same VU13P as the XUP-VV4 and the U250:
1,728K LUT, 12,288 DSP, 360 Mb URAM, 4 SLRs, four DDR4 channels.
**$1,200** liquid-cooled (buy-it-now) and **£770.68**, with a new
open-box at $3,800 ([PicClick](https://picclick.com/?q=cvp-13)); an
Osprey E300/E313 single-CVP-13 VU13P card at **$1,350.55**. Bare - no
shell, no XRT - but community Vivado PCIe-to-MIG DDR4 example designs
name CVP13 and BCU1525 explicitly, tested on Vivado 2019.2 and 2022.1
([Custom_Part_Data_Files](https://github.com/d953i/Custom_Part_Data_Files)),
paired with AMD's own XDMA driver.

**SQRL BCU1525 and relatives** - VU9P, `xcvu9p-fsgd2104-2L-e`.
**$395-$940** across several listings, a TUL Sparkle BTU9p at **$500**,
an Osprey ECU200 at $1,230, and $680 on Made-in-China
([PicClick](https://picclick.com/?q=bcu1525)). These have the deepest
community tooling of any bare card: a LiteX target with DDR4, PCIe,
Ethernet and SATA.

**SQRL FK33** - VU33P, 8 GB HBM2 at 460 GB/s, **$299-$348**. Cheap
bandwidth but the wrong shape: 440K LUT on a **single monolithic SLR**
is 2 tiles by this document's arithmetic, fewer than the U50 carries.

Against a bare VU13P at $1,200 the arithmetic is stark. Charging
144,012 per CU against 432,000 LUT per SLR at 85% gives 2 tiles per
SLR, **8 tiles for $1,200 - about $150 a tile**, against roughly $240 a
tile for a $1,200 U200 and **$640 a tile for a $4,500 U250**. The price
of admission is exactly the shell-less work item of the previous
section, which is also the item that buys modern tools and Windows.

**And here is the catch that the fabric-per-dollar arithmetic hides: a
bare card is not an Alveo device, so the project's licence does not
cover it.** UG973's tier table lists "Alveo Devices" and "Virtex
UltraScale+ FPGA Devices" as **separate rows**. A U250 build targets
`xcu250-figd2104-2L-e`, an Alveo device, which the Alveo tier covers
and which the 2022.x free ML Standard edition covered outright. A
CVP-13, BCU1525 or VCU1525 build targets `xcvu13p-...` or
`xcvu9p-fsgd2104-2L-e` - **Virtex UltraScale+, which reads "None"
under Basic in 2026.1 and was absent from ML Standard in 2022.1.**

So the bare cards need a **paid Core-tier subscription** (or
Enterprise), which the project does not hold, in both tool eras. The
same applies to the KCU1500's XCKU115 (Basic covers only XCKU025 and
XCKU035) and the Innova-2's XCKU15P (Basic covers only KU3P and KU5P).

That does not kill the option - reported Core pricing is in the
$1,200-$1,800 a year range - but it roughly doubles the first-year cost
of a $1,200 CVP-13 and it recurs annually. **The honest comparison is
$1,200 + a subscription against $3,500 and no subscription**, and the
subscription is the part that does not stop. This correction is the
single most important thing in this section: "the same die without the
shell tax" is true of the silicon and false of the licence.

**Supply risk, documented rather than assumed.** On Made-in-China,
observed 2026-09-05, `XCVU9P-2FLGA2104I` marked "New and Original" at
**US$1.20-2.00**, mixed VU9P/VU13P lots at $0.10-1.00 with a 1,000-unit
MOQ, and `XCVU13P-3FHGB2104E` at $24.56-33.19. Genuine VU9P/VU13P
silicon is a four-figure part. **Treat any sub-$1,000 Chinese-sourced
VU9P/VU13P card as requiring incoming device-ID checks and a
full-fabric-at-temperature test** for recovered, reballed or remarked
die. This project has an unusually good instrument for that: the
conformance vectors.

#### Two other cards worth knowing about

**Alveo V80** (XCV80): **2.6M LUT, 10,848 DSP engines, 541 Mb URAM,
32 GB HBM2e at 819 GB/s**, PCIe Gen5, 190 W passive - roughly 21 tiles
and technically the right card. But it does **not** use Vitis/XRT
kernel shells: it used AVED, whose repository now says "This repository
is obsolete. Alveo Versal management and related software now live in
AMR" ([AVED](https://github.com/Xilinx/AVED)), replaced by
[AMR](https://github.com/Xilinx/AMR). A stack that has already churned
once, plus Versal needs the **Pro** licence tier. No dated listing
found.

**Mellanox/NVIDIA Innova-2 Flex** (`MNV303212A-ADLT`): ConnectX-5 plus
an **XCKU15P** (522,720 LUT, 1,968 DSP) with 8 GB DDR4 ECC, the FPGA
on PCIe x8 Gen3 *behind the ConnectX-5's internal switch*. Needs up to
**800 LFM**, Above 4G Decoding on and **Resizable BAR off**, the
bitstream split across dual flash at specific offsets, and some units
ship with locked OEM firmware needing a CH341A programmer to recover.
NVIDIA stopped distributing the bundle in 2026. There is a mature
community XDMA design for it. Three tiles, and a long weekend.

### Cross-cutting hazards on any used card

These come from AMD's own card documentation and apply regardless of
which card is bought.

1. **AUX power is not optional for a full-die design, and this is the
   number that matters.** VCCINT current *shutdown* thresholds on the
   U200/U250/U280 are **53.5 A with no PCIe AUX, 214 A with a 2x3
   (6-pin), 321 A with a 2x4 (8-pin)**
   ([DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/Card-Thermal-and-Electrical-Protections)).
   At ~0.85 V that is roughly 45 W, 182 W and 273 W of VCCINT. **A
   slot-only card will trip long before the die is full** - which is
   exactly what a multi-tile build does to it.
2. **The 8-pin AUX is not an EPS12V connector.** DS978 and the V80
   datasheet both warn that the PCIe AUX 8-pin "is not compatible with
   an ATX12V/EPS12V power cable source". They fit. Using the wrong one
   can damage the card.
3. **Forced air, always.** UG1370: "Do not power-on a passively cooled
   card without adequate forced airflow ... otherwise the card can be
   damaged", and "Removing the cooling enclosure voids the board
   warranty." At a 25 °C inlet: U50 ~260 LFM, U200/U250/U280 440 LFM,
   **U55C 512 LFM**, V80 230-460 LFM, Innova-2 up to 800 LFM. None of
   these is a quiet workstation.
4. **Flashing can brick the card and recovery needs JTAG.** UG1370:
   "Do not enter Ctrl + c in the terminal while the firmware is
   flashing as this can cause the card to become inoperable", and "The
   image will not boot from flash if the machine is only rebooted" -
   **a full cold power-off is mandatory**. Golden-image recovery
   (AR71757) is the procedure when the card stops appearing in `lspci`.
   **Buy a JTAG cable before buying a used card**, not after.
5. **Card-not-recognised checklist**, from AMD's own debug guide:
   disable **BIOS fastboot** (the FPGA is being configured while the
   BIOS boots); **disable PCIe bifurcation** - "Alveo platforms ... are
   expecting a non-bifurcated link"; and for U200/U250/U280, "ensure no
   USB cable is plugged into the card as it will block the FPGA from
   enumerating on the PCIe bus." Note the KCU1500 *requires* the
   opposite - x16 bifurcated into two x8 - so the same BIOS setting is
   wrong in opposite directions depending on the card in the slot.
6. **A missing AUX cable fails quietly, and there is a one-line
   diagnostic for it.** "The U200, U250, and U280 cards require 225W of
   power to run Vitis acceleration loads and `xbtest`"; without the
   cable, **`xbmgmt examine` reports "Max power 150W"** and loads fail
   ([Alveo card
   debug](https://xilinx.github.io/Alveo-Cards/master/debugging/build/html/docs/power-delivery.html)).
   Read that line before blaming a bitstream.
7. **A protection trip is indistinguishable from a dead card, and this
   is exactly how a many-tile build will fail.** On shutdown "the card
   is pulled off the PCIe bus and consequently is not seen by the
   host", **no AXI firewall alert is raised**, and recovery needs a
   cold server reboot
   ([DS962](https://docs.amd.com/r/en-US/ds962-u200-u250/Card-Thermal-and-Electrical-Protections);
   DS963 says the same of the U280). An under-powered or under-cooled
   quad will present as a card that vanished, not as a design that
   failed - so when a card disappears mid-run, suspect items 1 and 3
   before suspecting the netlist.
8. **On "Above 4G Decoding", an honest correction.** docs/BRINGUP.md
   lists it as a prerequisite. Searching UG1370, UG1301's minimum
   system requirements, both Alveo card-debug pages and XRT's system
   requirements turned up **no AMD statement requiring it for Alveo
   compute cards**. It *is* documented for the Alveo U25N and for the
   Innova-2. So it appears to be community lore rather than a
   requirement. It costs nothing and should still be enabled - but the
   repo should not treat it as a documented gate, and a card that fails
   to enumerate should send you to item 5 rather than to the BIOS.

## 2. Development boards in the tile's size class

### The licensing change that reshapes this section

Vivado 2026.1 moved to subscription tiers, and the free **Basic** tier
now covers **every 7-series device**: Zynq-7000, Virtex-7, Kintex-7,
Artix-7 and Spartan-7 all read "All" in the Basic column
([UG973 2026.1, Device Availability by Subscription
Tier](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Device-Availability-by-Subscription-Tier),
release date 2026-06-23). In the 2022.1 tables the free ML Standard
edition covered only XC7K70T and XC7K160T of the Kintex-7 family and
no Virtex-7 at all
([UG973 2022.1](https://docs.amd.com/r/2022.1-English/ug973-vivado-release-notes-install-license/Supported-Devices)).

**So the XC7K325T, XC7K420T, XC7K480T and XC7VX485T are now free to
build for in the vendor flow as well as the open one.** That removes
the licensing objection that used to sit under every cheap Kintex-7
board, and it is the single most consequential finding for the open
core.

The same table's other rows worth knowing:

| family | Basic (free) covers |
|---|---|
| 7 series, all five families | **All** |
| Artix UltraScale+ | All |
| Spartan UltraScale+ | All |
| Kria SOM | All |
| Kintex UltraScale+ | **XCKU3P, XCKU5P** only |
| Kintex UltraScale | XCKU025, XCKU035 only |
| Zynq UltraScale+ MPSoC | up to **XCZU7EV / XCZU7EG / XCZU7CG** |
| Virtex UltraScale, Virtex UltraScale+, VU+ HBM, VU+ 58G | **None** - Core tier or above |
| Versal, all series | None below Pro |
| Alveo | "Supported through the dedicated Alveo tier only." |

The table carries its own caveat, which should be read before
committing: "Some devices can have bitstream generation under license
control. Contact your sales FAE for access."

### What fits, by device

Budget (A): tile LUT against `device_LUT x 0.85` is the routable
question; the raw percentage is given because it is what the rest of
the repo quotes.

| device | LUT | DSP | 1 full tile (123,420) | 2 tiles | free tier? | openXC7? |
|---|---|---|---|---|---|---|
| XCKU5P (KCU116) | 216,960 | 1,824 | **56.9%** | 113.8% no | **yes** | no |
| XCKU3P | 162,720 | 1,368 | 75.8% tight | no | **yes** | no |
| XCKU11P | 298,560 | 2,928 | 41.3% | 82.7% tight | no - Core | no |
| XCZU7EV (ZCU104/106) | 230,400 | 1,728 | **53.6%** | 107% no | **yes** | no |
| XCZU9EG (ZCU102) | 274,080 | 2,520 | 45.0% | 90.1% no | no - Core | no |
| XCZU5EV (Kria K26/KV260) | 117,120 | 1,248 | 105% no; fp128-max 82% | no | **yes** | no |
| XC7VX485T (VC707) | 303,600 | 2,800 | 40.7% | **81.3%** tight but real | **yes** | **yes** |
| XC7K480T | 298,600 | 1,920 | 41.3% | **82.7%** tight but real | **yes** | **yes** |
| XC7K420T | 260,600 | 1,680 | 47.4% | 94.7% no | **yes** | **yes** |
| XC7K410T | 254,200 | 1,540 | 48.6% | 97.0% no | **yes** | **no - absent from the db** |
| XC7K325T | 203,800 | 840 | **60.6%** | 121% no | **yes** | **yes** |
| XC7K160T | 101,400 | 600 | 122% no; fp128-max 94.7% | no | **yes** | **yes** |
| XC7A200T | 134,600 | 740 | 91.7% - not routable in practice | no | **yes** | **yes** |
| XC7A100T (Arty) | 63,400 | 240 | 195% no; **fp32-max 68.2%** | no | **yes** | **yes** |
| XC7A35T (Au V2) | 20,800 | 90 | no; quarter tile ~96% | no | **yes** | **yes** |

7-series LUT/DSP from
[DS180 v2.6.1](https://docs.amd.com/v/u/en-US/ds180_7Series_Overview)
(CLB LUTs = slices x 4); UltraScale+ from
[DS890 v4.10](https://docs.amd.com/v/u/en-US/ds890-ultrascale-overview).

Three rows deserve comment.

**XCKU5P / KCU116 is the only fully-licensed UltraScale+ node in the
free tier that holds a whole tile.** Same CARRY8 structure as the U50,
so the project's area and timing numbers transfer directly instead of
carrying the 7-series penalty - it is the one board on which a tile's
measured 123,420 LUT and 135 MHz mean what they mean. The board:
XCKU5P-2FFVB676E, "DDR4 up to 32-bits", "PCIe Gen3 x8 compliant",
$6,495.00 new, part EK-U1-KCU116-G, 8-week lead time
([AMD store](https://www.xilinx.com/products/boards-and-kits/ek-u1-kcu116-g.html),
seen 2026-09-05). The 32-bit DDR4 is the catch: at DDR4-2400 that is
9.6 GB/s against a tile's 13.82 GB/s demand, so **one tile on a
KCU116 is memory-starved by about 30%** unless the DDR4 runs faster
than 2400 - which is UNVERIFIED for this board.

**VC707 / XC7VX485T is openXC7's largest supported die.** The
openXC7 database carries `xc7vx485tffg1761-{1,2,2L,3}`, which is the
exact part on the VC707
([openXC7/prjxray-db virtex7/mapping/parts.yaml](https://github.com/openXC7/prjxray-db/blob/master/virtex7/mapping/parts.yaml)).
The board is XC7VX485T-2FFG1761C with PCIe Gen2 x8 and 1 GB DDR3
SODIMM, $5,995.00 new
([AMD store](https://www.xilinx.com/products/boards-and-kits/ek-v7-vc707-g.html),
seen 2026-09-05) - a price nobody should pay, but the board is a
long-standing used-market staple. 64-bit DDR3 at 1600 Mbps is 12.8
GB/s, which is one tile's demand and change; a two-tile VC707 would be
memory-bound at roughly half rate.

**The Kria KV260 cannot hold a full tile and is worth listing anyway.**
XCZU5EV at 117,120 LUT takes the fp128-max tile at 82% and the
fp64-max at 58.5%. Kria is in the free Basic tier. It is the cheapest
*licensed* object that could carry three rungs of the ladder, and the
contract holds for the rungs a tile carries (docs/LAYOUTS.md) - so it
is a conformance node, not a compute one.

### Prices and availability

All seen 2026-09-05. AMD store figures were read from the product
pages; where a figure could not be loaded it says so.

| board | part | PL LUT / DSP | price | lead | free tier? |
|---|---|---|---|---|---|
| **KV260 Starter Kit** (`SK-KV260-G`) | XCK26 (K26 SOM) | 117,120 / 1,248 | **$249.00** (+$25 PSU) | **26 weeks** | ✅ |
| KR260 | XCK26, same SOM | 117,120 / 1,248 | UNVERIFIED | - | ✅ |
| **ZCU104** | XCZU7EV-2FFC1156 | 230,400 / 1,728 | UNVERIFIED (AMD page 404s) | - | ✅ |
| ZCU106 | ZU7EV, suffix unverified | 230,400 / 1,728 | UNVERIFIED | - | ✅ |
| **ZCU102** (`EK-U1-ZCU102-G`) | XCZU9EG-2FFVB1156 | 274,080 / 2,520 | **$3,234.00** | 8 weeks | ❌ paid |
| **KCU116** (`EK-U1-KCU116-G`) | XCKU5P-2FFVB676E | 216,960 / 1,824 | **$6,495.00** | 8 weeks | ✅ |
| KCU105 (`EK-U1-KCU105-G`) | XCKU040-2FFVA1156 | 242,400 / 1,920 | UNVERIFIED | - | ❌ paid |
| **VC707** (`EK-V7-VC707-G`) | XC7VX485T-2FFG1761C | 303,600 / 2,800 | **$5,995.00** | 8 weeks | ✅ |
| **Genesys 2** | XC7K325T-2FFG900C | 203,800 / 840 | **$1,154.00** | in stock | ✅ |

An Avnet search snippet gave $6,931.00 for the KCU116 against AMD's
own $6,495.00; the page could not be loaded to adjudicate, and AMD's
figure is the one to trust.

Two notes that change how these read.

**The KV260 is the cheapest capable board in this document by a wide
margin and the K26's size is routinely overstated.** AMD markets the
SOM at 256,200 *system logic cells*; the CLB LUT count is **117,120**.
On UltraScale and UltraScale+ parts system logic cells are CLB LUTs
x 2.1875, so quoting logic cells as LUTs overstates capacity by 2.19x
- a trap worth naming because it is the number that appears in most
KV260 marketing. At 117,120 LUT the KV260 holds the fp128-max tile at
82% or the fp64-max at 58.5%, never a full one, and it has 1,248 DSPs,
which is ample. The 26-week lead time is the real obstacle.

The K26's PL being a ZU5EV is an inference, not a quotation: every PL
figure in DS987 is byte-identical to DS890's XCZU5EV column, but AMD
never writes "ZU5EV" in DS987.

**Academic pricing exists but is not published per product.** Digilent
states "Digilent products have special academic pricing of 15% off
through our distribution network. Inquire with the distribution
partner on their academic policy"
([Digilent academic
pricing](https://digilent.com/academic-pricing/)). No AMD academic
board pricing could be sourced.

## 3. Cheap PCIe-capable boards for the open core

### Three findings, before any board

**1. You cannot currently have cheap, open and PCIe at the same time.**
`PCIE_2_1` is not in nextpnr-xilinx's supported-primitive list, there
is no PCIe demo in openXC7's CI, and no open issue tracks it. The
metadata exists (`site_type_PCIE_2_1.json` in both the artix7 and
kintex7 trees of `nextpnr-xilinx-meta`) but the packer does not claim
the block. GTP transceivers *do* work - the
`litex-sata-alientek-davincipro` demo runs SATA Gen1 over GTPs on an
XC7A35T in CI, and despite the `litex_pcie` name in its source it
instantiates `LiteSATAPHY`, not `S7PCIEPHY`. **PCIe on any of these
boards means Vivado.** Which, after the 2026.1 licensing change, is no
longer the objection it was.

**2. openXC7's DSP48E1 correctness bug is still open.** docs/ROADMAP.md
recorded [openXC7/nextpnr-xilinx
#159](https://github.com/openXC7/nextpnr-xilinx/issues/159) on
2026-08-20 as "one in-flight fix away". Re-checked 2026-09-05: **the
issue is still open and no DSP48E1 fix has been merged** (the 15
most-recently-updated pull requests contain none). The title is its
own summary - "inferred DSP48E1 ignores its A operand -- INMODE/ALUMODE2/3/OPMODE6
never get their tile constant bits" - and the reported hardware pass
rates before the proposed fix are **1 of 315** for a dual 16x16 DSP and
**25 of 430** for a 32x32 cascade. The reproducer that landed in
demo-projects on 2026-08-26 infers exactly one multiplier
(`wire [31:0] p = a * b;`) with no accumulate, cascade, pre-adder or
pipelining.

A design that passes post-synthesis simulation and returns wrong
results on silicon is the worst failure mode this project could adopt,
and 280 DSPs is three orders of magnitude past what the reproducer
exercises. **This is a hard stop on trusting an openXC7 bitstream for
arithmetic until #159 closes and a multi-hundred-DSP design has been
scored on hardware.** It is not a reason to stop *building* with
openXC7 - the conformance vectors would catch a complemented INMODE in
the first multiply, which is exactly the bring-up check this repo runs
anyway - but it is a reason not to buy a board *because* of the open
flow.

**3. The one published expert assessment is not encouraging.** The
chili-chips-ba openXC7-TetriSaraj project, a RISC-V SoC plus video
controller on a Basys3: "our expert assessment is that openXC7, while
not in its early infancy stage, is yet to reach the fully productive
age of maturity. We would therefore not recommend it for large or
commercial projects"
([openXC7-TetriSaraj](https://github.com/chili-chips-ba/openXC7-TetriSaraj)).
It documents the analytical placer locking up on designs with high
distributed-RAM usage, and STA "very rudimentary, down to not even
honoring timing constraints". The UberDDR3 port, which did reach real
hardware on six boards including Kintex-7 with 64-bit DDR3, reports
"nextpnr's timing-driven PNR capabilities are still limited, making it
difficult to run complex designs at high frequencies" and ran only at
the minimum DDR3 frequency
([openiphub,
2025-03-21](https://www.openiphub.com/post/uberddr3-openxc7-open-source-ddr3-controller-meets-open-source-fpga-toolchain)).

**No published openXC7 design above 50% utilisation could be found, on
any part, with any utilisation figure attached.** The demo repository
contains no logs or reports. That absence is itself the finding: the
project would be the first to try it at this size.

### Boards

Prices seen 2026-09-05. Marketplaces that block automated fetching
(eBay, AliExpress, Amazon, Digi-Key, Mouser, Avnet, digilent.com
direct) are marked where a figure came from a search index rather than
a loaded page - **click-verify those before ordering**.

| board | part | LUT | memory | host | price | notes |
|---|---|---|---|---|---|---|
| **Chinese K325T PCIe card** | XC7K325T-2FFG676I | 203,800 | 1 GB DDR3 | **PCIe Gen2 x8** | **$341.00** ([OpenSourceSDRLab](https://opensourcesdrlab.com/products/fpga-xilinx-kintex-7-xc7k325t-pcie-development-board-with-dual-gigabit-ethernet-ports-dual-10-gigabit-sfp-optical-communication)) | cheapest K325T card with a real x8 edge; 2x GbE + 2x 10G SFP+ |
| **QMTech K325T core board** | xc7k325tffg676-1 | 203,800 | 256 MB DDR3 16-bit | headers only | ~$99.90 (AliExpress listing title, **low confidence**) | openXC7 CI target (`blinky-qmtech`); no PCIe carrier found |
| **Numato Nereid** | XC7K160T-1 FBG676 | 101,400 | **4 GB DDR3L SODIMM** | **PCIe Gen2 x4** + FMC HPC | **not published** (RFQ) | LiteX+LitePCIe, in openXC7 DB; **fp128-max only, 79%** |
| **Alinx AX7325 / AX7325B** | XC7K325T-2FFG900I | 203,800 | **2 GB DDR3 64-bit**, SODIMM to 8 GB | **PCIe Gen2 x8** | £739.99, **sold out** | best memory of any K325T board found |
| **Genesys 2** | XC7K325T-2FFG900C | 203,800 | **1 GB DDR3 32-bit, 1800 Mbps** | FMC HPC, 10 GTX; **no PCIe edge** | **$1,154.00** ([Digilent](https://digilent.com/shop/genesys-2-kintex-7-fpga-development-board/)) | not discontinued; openXC7 CI target (`blinky-genesys2`) |
| **PZ-K7325T-SOM** | XC7K325T-2FFG900I | 203,800 | **2 GB DDR3 64-bit**, 16 GTX | via carrier | £331.99 (coderobin) | + `PZ-K7325T-KFB` carrier, PCIe 2.0 x8, **price quote-only** |
| **PZ-K7410T-SOM** | XC7K410T-2FFG900I | 254,200 | 2 GB 64-bit | via carrier | £453.99 | **XC7K410T is absent from the openXC7 database** - Vivado only |
| **Trenz TE0741** | XC7K325T-2FBG676C/I | 203,800 | **none on module** | via carrier | $868.26 (C) / $995.83 (I) ([Trenz](https://www.trenz-electronic.de)) | no onboard DDR; no PCIe carrier named |
| **Nexys Video** | XC7A200T-1SBG484C | 134,600 | 512 MB DDR3 | FMC LPC, no PCIe | **$577.00** (Digilent) | full tile 91% - too tight |
| **SQRL Acorn CLE-215+** | xc7a200t-fbg484-3 | 134,600 | 1 GB DDR3 16-bit | **PCIe Gen2 x4 (M.2)** | €219.00 with baseboard mini ([Enjoy-Digital](https://enjoy-digital-shop.myshopify.com/products/litex-acorn-baseboard-mini-sqrl-acorn-cle215)); $85-148 used (index, low confidence) | **SQRL is defunct** - `squirrelsresearch.com` is NXDOMAIN |
| **NiteFury II** | XC7A200T-2FBG484E | 134,600 | 1 GB DDR3 | PCIe Gen2 x4 (M.2 2280) | **not listed for sale**; LiteFury shown "Sold out" at $109 | availability is the problem |
| **Alchitry Pt V2** | XC7A100T FGG484 -2 | 63,400 | 256 MB DDR3L | FT2232HQ; **4 GTP broken out, no PCIe connector** | **$349.99** ([Alchitry](https://shop.alchitry.com/products/alchitry-pt)) | **no carrier exists** - the whole catalogue is 15 items and none is one |
| **Alchitry Au V2** | XC7A35T-2FTG256I | 20,800 | 256 MB DDR3L | FT2232HQ, no transceivers | **$149.99** | the conformance node of docs/ROADMAP.md |
| **Arty A7-100T** (ordered) | XC7A100TCSG324-1 | 63,400 | 256 MB DDR3L 16-bit @333 MHz | USB / Ethernet | **$314.00** (Digilent) | fp32-max tile at 68% |
| **Arty A7-35T** | XC7A35TICSG324-1L | 20,800 | - | USB | **RETIRED**, no price | Digilent: "no longer in production and is retired" |
| **aliexpress_rk_xcku5p** | xcku5p-ffvb676-2-i | 216,960 | **2 GB DDR4** | **PCIe 3.0 x4**, QSFP28, FMC HPC | **no price found** | added to litex-boards 2026-08-25; free tier; **not** an openXC7 target |

### Two board-level traps worth naming

**The A200T is the wrong size, and every cheap PCIe card is an A200T.**
Acorn CLE-215/215+, NiteFury II, Nexys Video, Numato Aller and Tagus
are all XC7A200T at 134,600 LUT. A full tile is 91.7% before the
7-series carry penalty. They are fp128-max boards (96,053 = 71%) at
best, not full-tile boards.

**And an M.2 slot cannot power one anyway.** An M.2 slot is limited to
8.25 W, against roughly 36 W for an A200T running heavy DSP and logic
- which is why the Acorn's carrier carries a 12 V connector. Any M.2
tile needs external power, and that turns the "M.2 module ring" idea
into a carrier design problem rather than a purchase.

**The Alchitry Pt V2 has no carrier and no PCIe connector.** Its four
GTP channels are broken out on the bottom Hirose connectors and
Alchitry's own blog says of PCIe that "it's unclear whether the
current style of connectors would support speeds that fast". The full
catalogue is fifteen items and none of them is a carrier. This
independently confirms docs/ROADMAP.md's 2026-08-30 decision to
supersede the Pt plan, on a second ground: not only does a full tile
not fit on the silicon, the carrier the plan needed does not exist and
would have to be designed. (Alchitry's shop also prints a
non-existent package, `XC7A100T-2FGG84I`; the schematic says
`XC7A100TFGG484`.)

### The licensing flip, and when it happened

The change described in §2 is recent enough to be worth dating.
UG973 **2025.2** still gave Kintex-7 as "XC7K70T, XC7K160T" for the
free edition - the same list it had carried since 2021.1
([UG973
2025.2](https://docs.amd.com/r/2025.2-English/ug973-vivado-release-notes-install-license/Supported-Devices)).
UG973 **2026.1**, released 2026-06-23, gives "All". So the XC7K325T,
K410T, K420T and K480T moved from paid-only to free **between 2025.2
and 2026.1**, and every Kintex-7 board in the table above changed
economic character this year.

One honest caveat on that: UG973 never states in words that "Basic" is
the zero-cost tier. It is the lowest of four, its UltraScale rows carry
exactly the historical WebPACK device lists, and AMD's licensing pages
describe Basic as free - but the inference should be confirmed against
a real licence install before budget is committed. It is on the
checklist in §9.

Still **not** free at any 7-series-adjacent size: XCKU040 (KCU105) and
XCZU9EG (ZCU102).

### What openXC7 actually covers, verified

The ROADMAP's claim that openXC7 supports Kintex-7 is correct and can
now be pinned to files rather than to recollection.

**The org's own claim.** "Free and open source FPGA toolchain for
AMD/Xilinx Series 7 chips, including Kintex-7. Supports Kintex7
(including 325/420/480t), Artix7, Spartan7 and Zynq7"
([github.com/openxc7](https://github.com/openxc7), read 2026-09-05).

**The bitstream database.** `openXC7/prjxray-db` at commit `5099b9e`
(2026-08-30) carries `artix7`, `kintex7`, `spartan7`, `virtex7` and
`zynq7` directories, each with full tile databases including
`mask_dsp_l/r`, `ppips_dsp_l/r`, `mask_bram_*`, the CLB tiles,
`mask_pcie_bot` and the GTX/GTP tiles. The per-family
`mapping/parts.yaml` files are the definitive list:

| family | dies with database coverage |
|---|---|
| artix7 | 35T, 50T, **100T**, **200T** |
| kintex7 | 70T, 160T, **325T**, **420T**, **480T** - every package, speed grades -1/-2/-2L/-3 |
| spartan7 | 25, 50 (75/100 fabric added 2026-08-30) |
| virtex7 | **xc7vx485t** only, five packages |
| zynq7 | 7z010, 7z020, 7z030, 7z035, **7z045**, 7z100 |

([kintex7/mapping/parts.yaml](https://github.com/openXC7/prjxray-db/blob/master/kintex7/mapping/parts.yaml),
[virtex7/mapping/parts.yaml](https://github.com/openXC7/prjxray-db/blob/master/virtex7/mapping/parts.yaml))

**XC7K410T is absent**, exactly as docs/ROADMAP.md cautioned. The
adjacent 420T is present, so adding the 410T remains plausible work
rather than new science - but it is still unproven, and buying a 410T
on the assumption is still the thing not to do. That rules the
PZ-K7410T-SOM out of an open flow specifically, while leaving it a
perfectly good Vivado part now that Kintex-7 is free.

`zynq7` covering 7z045 confirms docs/ROADMAP.md's ZC706 row.

**What CI actually builds**, from the `PART` line of each Makefile in
`openXC7/demo-projects` - 21 projects, all passing:

| part | project |
|---|---|
| `xc7k480tffg1156-1` | blinky-ypcb003381p1 |
| `xc7k420tffg901-1` | **litex-ddr-hpcstore-k420t** - a LiteX SoC with DDR3, 789 KB of generated Verilog |
| `xc7k325tffg900-2` | blinky-genesys2 |
| `xc7k325tffg676-1` | blinky-qmtech, blinky-stlv7325 |
| `xc7k160tffg676-2` | litex-ddr-enclustra-kx2 |
| `xc7a100tfgg676-1` | litex-ddr-qmtech-artix7 |
| `xc7a35tfgg484-2` | litex-sata-alientek-davincipro |

**Note the gap: there is no XC7A200T demo in CI**, although the part is
in the database - and the A200T is the die on the Acorn, the NiteFury
and the Nexys Video. The most-travelled openXC7 ground is Artix-7 35T
and Kintex-7 325T.

`nextpnr-xilinx` was at commit `bd9c74c5` (2026-09-01) when checked;
the repository is actively developed, with issues filed as recently as
2026-09-05.

**LiteX accepts it.** `litex/build/xilinx/yosys_nextpnr.py` takes
`openxc7` as a toolchain for any part matching
`xc7([aksz])([0-9]+)(.*)-([0-9])` and generates the chipdb on demand.
One documented restriction, verbatim: "false path constraints are
currently not supported by the yosys+nextpnr toolchain and are
ignored."

**What the upstream says, for contrast.** `f4pga/prjxray`'s own README
still describes Kintex-7 as an early experimental stage and Zynq-7000
and Spartan-7 as not yet documented
([f4pga/prjxray README](https://github.com/f4pga/prjxray)). The
openXC7 fork is well ahead of it, and the fork is what the demo
projects and the released nextpnr-xilinx build against. Cite the fork,
not the upstream, when this question comes up again.

**And what nextpnr-xilinx says it supports.** For xc7: "LUTs
(including fractured), FFs, DRAM (only RAM64X1D), carry (XORCY and
MUXCY or CARRY4), SRL16E and SRLC32E (no cascading), BRAM and IO",
plus xc7-only "... PLLE2_BASIC, PLLE2_ADV, MMCME2_ADV, MMCME2_BASIC,
**DSP48E1 (cascading works)**"
([openXC7/nextpnr-xilinx README](https://github.com/openXC7/nextpnr-xilinx)).
The DSP question docs/ROADMAP.md settled on 2026-08-31 is still
settled.

## 4. Non-AMD silicon

### The unit problem, first, because it decides most of these rows

**Of the five vendors surveyed, only Achronix publishes logic capacity
in 6-input LUTs.** Efinix, Microchip and Lattice all count
4-input-LUT-based cells; Altera counts ALMs. None of those four
publishes a conversion to 6-LUTs. So for most of this section the
honest answer to "does a 123,000-LUT tile fit" is **not a number**,
and no ratio has been invented to manufacture one. Where a fit can be
stated it is stated; where it cannot, the row says so.

One number *is* comparable regardless of LUT width, and it settles a
row on its own: the DSP count against the tile's 277-292.

### Summary

| family | logic (vendor's unit) | comparable to 123k LUT6? | DSP vs 277-292 | free tools for this part? | open flow |
|---|---|---|---|---|---|
| Efinix **Ti180** | 172,800 LE (4-LUT + FF) | no | 640 @ 19x18 ✓ | **yes, unrestricted** | synthesis only, no DSP map, **no bitstream** |
| Efinix **Ti375** | 370,137 LE (4-LUT) | no | 1,344 ✓ | **yes, unrestricted** | same |
| Microchip **MPF300 / MPF500** | 198,744 / 319,992 (4LUT+DFF) | no | 924 / 1,480 @ 18x18 ✓ | **UNVERIFIED, likely paid Gold** | best Yosys front end; no bitstream |
| Microchip **MPFS250T** (Icicle) | 254,000 (4LUT+DFF) | no | 784 ✓ | **yes - Silver covers it** | same |
| Lattice **CertusPro-NX** | 96K logic cells | no | **156 ✗ fails** | **no - paid subscription** | prjoxide has the die, nextpnr refuses it |
| Lattice **Avant-E70** | 637k system logic cells | no | 1,800 ✓ | **no - paid subscription** | none |
| Altera **Arria 10 GX 1150** | 427,200 ALM | bounded ✓ | 3,036 @ 18x19 ✓ | **no - Standard/Pro, paid** | none |
| Altera **Agilex 5 A5E065B** | 222,400 ALM | bounded ✓ | 1,692 @ 18x19 ✓ | paid Pro; a "no cost" Agilex 5 E licence is a lead | none |
| Achronix **AC7t1500** | **692k 6-input LUTs** | **yes ✓** | 2,560 MLPs, mapping unknown | **none found** | none |

### Efinix Titanium

Ti180: 172,800 logic elements, where a logic element carries "A
4-input LUT that supports any combinational logic function with four
inputs"
([Ti180 data sheet DSTi180-v3.7, March
2026](https://www.efinixinc.com/docs/titanium180-ds-v3.7.pdf)); 640
DSP blocks with a native 19x18 multiply and 48-bit accumulate; 13.11
Mb of embedded memory. Efinix's own shop page says 176,256 LE rather
than 172,800 - the two vendor sources disagree and it was not
resolved.

**The disqualifier for the Ti180 is not logic, it is the host link:
the Ti180 has no hardened PCIe controller.** The kits expose USB
Type-C for configuration only
([M484](https://www.efinixinc.com/products-devkits-titaniumti180m484.html),
[J484](https://www.efinixinc.com/products-devkits-titaniumti180j484.html)).
The **Ti375** does have PCIe Gen4, up to 4 lanes on the larger
packages ([Ti375](https://www.efinixinc.com/shop/ti375.php)), and is
the only Efinix part worth considering if a host link is wanted.

Kit prices (Digi-Key, seen 2026-09-05, via a search index rather than
a loaded page - click-verify before ordering): TI180M484-DK $825.01
but out of stock with backorders not accepted; TI180J484C-DK $825.00
with a 20-week factory lead; TI375N1156C-DK $1,995.00.

**Efinity is the best licensing story in this section, by a distance.**
Efinix: "Efinix provides FREE licenses for the Efinity software ...
The version you get is not a watered down web edition, it supports all
of our FPGAs"
([Efinity](https://www.efinixinc.com/products-efinity.html), checked
2026-09-05). No device tiering at all. And the SystemVerilog answer is
strong: the Efinity Synthesis User Guide states "Supports full
SystemVerilog IEEE 1800" and explicitly marks packages, interfaces,
generate, `always_comb`, `always_ff`, structures and parameter
overrides as supported
([UG-EFN-SYNTH-v4.4, Nov
2025](https://www.efinixinc.com/docs/efinity-synthesis-v4.4.pdf)) -
so this repo's RTL would very likely elaborate.

Open flow: `synth_efinix` exists in Yosys but emits EDIF/JSON only,
has **no DSP mapping file at all**, and carries no Ti180/Ti375 family
option - its primitive set is Trion-generation. There is no
nextpnr Efinix architecture and no bitstream documentation project.

### Microchip PolarFire

Device tables from the [PolarFire Family Fabric User
Guide](https://onlinedocs.microchip.com/oxy/GUID-A24E5843-5F7D-4E27-982B-8490F03A92EB-en-US-8/GUID-CD54E61A-D8BB-40AA-BA39-9E22E8FB2A59.html)
(checked 2026-09-05); the logic element is a 4-input LUT with carry
chain and D flip-flop, fracturable, with no 6-LUT equivalence given.

| device | logic elements | 18x18 MACC | LSRAM 20 Kb | µSRAM |
|---|---|---|---|---|
| MPF300 | 198,744 | 924 | 952 | 2,772 |
| MPF500 | 319,992 | 1,480 | 1,520 | 4,440 |
| MPFS250T (Icicle) | 254,000 | 784 | 812 | 2,352 |

**The Icicle Kit is the interesting one and the reason is licensing.**
MPFS250T-FCVG484EES with 2 GB LPDDR4 x32 and a **PCIe Gen2 x4 edge
connector**, $419.69 at Digi-Key or $489 direct
([Crowd
Supply](https://www.crowdsupply.com/microchip/polarfire-soc-icicle-kit),
seen 2026-09-05). Libero's free **Silver** tier covers programming for
a limited device list, and Microchip's Mi-V ecosystem FAQ states "The
device which is on the Icicle Kit is supported with the Libero Silver
licence", while noting the PolarFire Evaluation and Splash kits ship
with **Gold** ([Mi-V FAQ](https://mi-v-ecosystem.github.io/docs/faq/),
checked 2026-09-05). So the Icicle is free to build for; **MPF300 and
MPF500 free-tier status is UNVERIFIED** and the FAQ implies it is not
free.

Libero synthesises through Synopsys Synplify Pro ME rather than a
native front end. Synopsys claims SystemVerilog support in general
terms but names no IEEE 1800 revision and enumerates no constructs;
**a Microchip-published SystemVerilog-2012 construct list could not be
found.**

Open flow: **the best Yosys front end of any vendor here.**
`synth_microchip -family polarfire` carries real DSP inference
(`microchip_dsp.cc` with CREG packing and cascade pattern matchers,
`polarfire_dsp_map.v`), LSRAM and µSRAM inference and ARI1 carry
chains. It emits EDIF, and Libero does accept EDIF as a design source.
**But nobody has been found to have run that path end to end onto
silicon**, and there is no nextpnr Microchip architecture, so this is
a vendor-place-and-route flow with an open front end - not an open
flow.

Prices that could not be pinned: MPF300-EVAL-KIT returned two
conflicting index figures ($1,811.26 and $3,289.31) with every
tiebreaker distributor blocking; MPF300-SPLASH-KIT likewise ($581.13
vs $559.08). Neither should be used. The MPF300 eval kit's PCIe
generation, lane count and DRAM could not be sourced at all.

### Lattice - ruled out, twice over

**CertusPro-NX fails on arithmetic that no unit question can rescue.**
LFCPNX-100 has **156 18x18 multipliers**
([Lattice
CertusPro-NX](https://www.latticesemi.com/en/Products/FPGAandCPLD/CertusPro-NX),
checked 2026-09-05) against the tile's 277-292. It does not fit, and
that holds whatever a "logic cell" turns out to be. The LFCPNX-EVN
board also has **no DRAM at all** - 128 Mb of SPI flash and nothing
else.

Avant-E70 has ample compute (1,800 18x18 multipliers, 637k system
logic cells, 35.6 Mb memory) but the unit is undefined and the board
exposes USB-B for programming with no PCIe stated.

**Both families require a paid Radiant subscription.** Lattice's
licensing matrix marks CertusPro-NX (LFCPNX) and Avant (LAV-AT-E/G/X)
as SUBSCRIPTION rather than FREE
([Lattice licensing](https://www.latticesemi.com/Support/Licensing),
checked 2026-09-05). That also removes the appeal of the cheap board:
LFCPNX-EVN is $211.25 and LAV-E70-EVN $1,061.25 (Lattice store, loaded
2026-09-05), but all three Avant boards were out of stock that day.

Open flow: prjoxide does carry LFCPNX-100 in `devices.json` with
fuzzing across five packages, and its README says DSP and PLL have
been fuzzed - but "Most of the current testing has been done with
LIFCL-40 devices". The blocker is downstream: nextpnr's
`nexus/CMakeLists.txt` sets `ALL_NEXUS_FAMILIES` to `LIFCL` and raises
a fatal error for anything else, so **nextpnr-nexus will not build a
chipdb for CertusPro-NX today**. Avant has no open support of any kind.

### Altera - fits, probably, and costs money either way

The ALM is documented as "an 8-input fracturable look-up table (LUT)
with four dedicated registers"
([Arria 10 device
overview](https://docs.altera.com/r/docs/683332/current/arria-10-device-overview/adaptive-logic-module)).
Because an 8-input fracturable LUT can implement any 6-input function,
the ALM count is a defensible **upper-bound** comparison to a 6-LUT
count - but Altera publishes no packing ratio, so read the margin, not
the number.

* **Arria 10 GX 1150 (10AX115):** 427,200 ALM, 1,518 variable-precision
  DSP blocks = **3,036 18x19 multipliers**, 54,260 Kb M20K, 4 hard PCIe
  blocks
  ([maximum
  resources](https://docs.altera.com/r/docs/683332/current/arria-10-device-overview/maximum-resources)).
* **Agilex 5 E-Series A5E065B:** 222,400 ALM, 1,692 18x19 multipliers,
  31.46 Mb M20K, PCIe Gen4, DDR4/5 and LPDDR4/5
  ([device
  overview](https://docs.altera.com/r/docs/762191/current/agilex-5-fpgas-and-socs-device-overview/agilex-5-fpgas-and-socs-e-series)).

Both plausibly hold a tile with room. The problems are commercial.
**Quartus Prime Lite (free) covers neither**: its device list is
Cyclone 10 LP, Cyclone V, Cyclone IV, one Arria II part and MAX
10/V/II. Arria 10 needs Standard or Pro, Agilex needs Pro - both paid
([Quartus edition
comparison](https://www.altera.com/products/development-tools/quartus/compare),
checked 2026-09-05). A referenced "Agilex 5 E-Series No Cost License"
appears on the Quartus product page but its terms page could not be
found; treat it as a lead.

And the Arria 10 kit is **discontinued by Altera**, with DK-DEV-10AX115S-B
listed as a preview replacement; the practical route is used, where a
"New - Open Box" DK-DEV-10AX115S-A was listed at **US $1,499.00** on
eBay (seen 2026-09-05, index result, seller marked away). The Agilex 5
065B Premium kit is $3,125.00 for the production part and exposes
**PCIe Gen4 x4 through an FMC+ connector rather than a card edge** -
worth knowing before assuming it plugs into a host.

Quartus has the best-documented SystemVerilog support here: 1800-2005,
1800-2009 and **1800-2012**, listed by IEEE section including packages,
interfaces, data types, aggregate types and parameterised modules
([Quartus SystemVerilog
support](https://resources.altera.com/quartushelp/current/hdl/vlog/vlog_list_sys_vlog.htm)).

Open flow: **none**, for either family. Mistral covers Cyclone V only
and has been dormant since 2023-09-03; nextpnr-mistral is labelled
experimental and its directory has no DSP source file at all;
`synth_intel_alm` documents `cyclonev` as its only family; and
`synth_intel`'s `-vqm` Quartus handoff says in its own source that it
"has not been tested and is likely incompatible with recent versions
of Quartus".

### Achronix Speedster7t - the only sourced fit, on a dying card

**AC7t1500: 692,000 6-input LUTs**
([Achronix](https://www.achronix.com/product/speedster7t-fpgas),
checked 2026-09-05, corroborated by
[BittWare](https://www.bittware-molex.com/products/s7t-vg6/)). Against
123,000, that is 5.6x headroom **in the vendor's own unit, with no
conversion assumed** - the only such statement in this section. 195 Mb
of embedded memory. The VectorPath S7t-VG6 card carries 16 GB of GDDR6
at 3.5 Tbps plus up to 4 GB DDR4-2666 ECC, on **PCIe Gen5 x16**, in a
full-height dual-width 225 W envelope.

The compute question is open rather than answered: the part has 2,560
MLPs quoted by throughput per numeric format rather than as an
18x18-multiplier count, and **no ratio for mapping 277-292 DSP48-class
multipliers onto MLPs could be sourced.**

Then the commercial reality. BittWare's own notice: "This is a legacy
product and is not recommended for new designs. It is still available
for purchase, but development tools and software are no longer
maintained for compatibility with the latest FPGA tools and operating
systems." The replacement is the [VectorPath
815](https://www.achronix.com/product/vectorpath-accelerator-card),
whose price could not be found. **No public price exists for either
card** - an $8,495 MSRP figure is indexed against an achronix.com URL
that 403s, and given the legacy notice it should be treated as stale.
The ACE toolchain offers only an evaluation-licence request form with
no free edition and no published cost, and synthesises through an OEM
Synplify Pro. Open flow: none - `synth_achronix` targets the much
older Speedster22i, is self-described as experimental, and has no BRAM
or DSP inference. The bitstream is AES-GCM-256 encrypted with
PUF-derived keys.

### What this section is actually good for

**No non-AMD family is a better home for the tile than the AMD path,
and the reasons are commercial rather than technical.** Free tools and
adequate capacity are very nearly disjoint: Efinix gives unrestricted
tools on the part most likely to be too small and without hard PCIe;
Microchip gives a free tier only on the Icicle; Lattice and Achronix
and Altera all want money before the first bitstream. And no vendor
here has an open place-and-route flow to a bitstream on a part in this
size class, so the "audit it down to place-and-route" story that
justifies the open core does not transfer.

There is one honest use for a board from this section, and it is in
docs/ROADMAP.md already: **build-diversity pairing**. A second
vendor's toolchain running the same RTL in lockstep is dissimilar
redundancy, and it cross-checks place-and-route rather than
arithmetic. For that role the requirement is not capacity, it is
cheapness, free tools and a host link - and **the PolarFire SoC Icicle
Kit is the only board in this section that has all three** at $419-489
with PCIe Gen2 x4 and a Silver licence that covers its device. A
fp64-max or fp128-max tile there, cross-checked against the same tile
on a Kintex, would be a real result. It is a low priority against
everything in §1-3, and it is listed here so that the option is on
record rather than rediscovered.

## 5. Licensing: what the project's Alveo entitlement covers

The belief on record is that "used Alveo U200/U250 ... are covered by
the SAME Alveo-tier license and the same XRT flow as the U50C"
(docs/ROADMAP.md, scale-out doctrine). **The belief is correct, and
for the toolchain the project must actually use it is stronger than
stated - no licence is needed at all.** Two eras, two answers.

### The era the project builds in (Vitis/Vivado 2022.x)

UG973's supported-device table for 2022.1 lists, row by row, what each
edition covers. The Kintex-7 row reads "XC7K70T, XC7K160T" for ML
Standard and "All" for ML Enterprise. The Virtex UltraScale+ row lists
nothing at all for ML Standard. **The Alveo row reads "All" for ML
Standard and "All" for ML Enterprise**
([UG973 2022.1 Supported
Devices](https://docs.amd.com/r/2022.1-English/ug973-vivado-release-notes-install-license/Supported-Devices);
the same row appears in the
[2024.1 table](https://docs.amd.com/r/2024.1-English/ug973-vivado-release-notes-install-license/Supported-Devices)).

So in the free Vivado ML Standard Edition - which needed no licence
file at all in that era - **every Alveo device is buildable, U200 and
U250 included**, even though the bare `xcvu9p` and `xcvu13p` silicon
underneath them is Enterprise-only. The distinction is the *card
device* (`xcu200`, `xcu250`) versus the raw die, and the Alveo row
covers the card devices.

### The era the tools are moving to (2026.1+)

The tier table is explicit: Alveo devices are "Supported through the
dedicated Alveo tier only"
([UG973 2026.1, Device Availability by Subscription
Tier](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Device-Availability-by-Subscription-Tier)).
Virtex UltraScale+ and Virtex UltraScale+ HBM read "None" under Basic,
so there is no free path to `xcvu9p`/`xcvu13p`/`xcvu35p` as raw parts.

The project holds exactly that tier: an Alveo-tier licence generated
on the AMD portal with an Alveo card purchase, node-locked to
amd-arc-box's `eno1` MAC, features `Vivado_Alveo_Package + Synthesis +
Implementation + Simulation`, valid through 2027-08-29
(docs/BRINGUP.md). AMD describes the tier as covering Alveo devices as
a class rather than the purchased card, and the 2026.1 table's Alveo
row names no individual device.

### The finding, stated at the right confidence

* **A used U200, U250, U280 or U55C is buildable with what the project
  already has.** In the 2022.x flow it needs no licence; in 2026.1+ the
  Alveo tier is the right tier and it is held.
* **A used card carries no entitlement of its own**, and does not need
  to - the entitlement came with the U50C and the node-lock is on the
  build box, not the card.
* **The licence is not the reason to hesitate. The tools are.** The
  U200 platform was "Created by 2021.1 tools" and the U250's by 2022.1
  ([UG1120](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U200-Gen3x16-XDMA-base_2-Platform),
  [U250](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U250-Gen3x16-XDMA-4_1-Platform)),
  so a used U200/U250 walks straight back into the encrypted-shell-IP
  problem docs/BRINGUP.md solved by pinning to Vitis 2022.2 - with
  keys a year *older* on the U200. Buying one adds a card, not a
  toolchain.
* **The Alveo row covers the Alveo *device*, not the Vitis flow - so
  shell-less on an Alveo card is still licensed.** UG973 lists "Alveo
  Devices" and "Virtex UltraScale+ FPGA Devices" as separate rows, and
  the distinction is the part name, not the toolchain. A bare XDMA
  design in Vivado against `xcu250-figd2104-2L-e` is an Alveo device
  and the tier covers it. The same design against
  `xcvu13p-...` on a CVP-13 is Virtex UltraScale+, which reads **None**
  under Basic and needs a paid **Core** subscription. **This is the
  practical reason to prefer a used Alveo over a cheaper used mining
  card even when the shell is being discarded**, and it is the finding
  most likely to be got wrong by looking only at the price per LUT.
  The same trap catches the KCU1500 (XCKU115 - Basic covers only
  XCKU025/XCKU035) and the Innova-2 (XCKU15P - Basic covers only
  KU3P/KU5P).
* **What is still unverified: the licence file itself.** AMD's tier
  documentation says what the tier covers; it does not say what the
  FEATURE lines in one particular `Xilinx.lic` enumerate. Whether that
  file gates on device is answerable in ten minutes without buying
  anything - see the checklist in §8.
* **Also unverified:** whether the free-tier Alveo coverage of the
  2022.x era continues to apply to a *newly downloaded* 2022.2
  installation today, given that the licensing infrastructure has since
  changed. The project already has 2022.2 installed and licensed on
  two boxes, so this only matters for a third machine.

## 6. The Windows story

Short version: **shell means Linux, bare means Windows is possible.**

**XRT does not support Windows for PCIe accelerator cards.** AMD's own
system requirements list the supported host as "Linux running on
x86_64" and "Linux running on aarch64" for PCIe accelerator cards;
Windows appears only for the AMD NPU
([XRT system
requirements](https://xilinx.github.io/XRT/master/html/system_requirements.html)).
This confirms docs/BRINGUP.md's "Linux only, the whole flow" from the
vendor side. Every Alveo row in this document is therefore Linux-only
as long as it is driven through a Vitis shell, and that includes the
U55C, U280, U200 and U250 recommendations below.

**A bare XDMA design can be driven from Windows, with a caveat AMD
states itself.** AMD publishes a Windows binary driver for the XDMA
IP: "The PCIe DMA supports UltraScale+, UltraScale, Virtex-7 XT and 7
Series Gen2 devices; the provided driver can be used for all of these
devices" - and, plainly, "**The windows driver is only provided as a
reference to get started and has not been thoroughly tested**"
([AR 65444](https://adaptivesupport.amd.com/s/article/65444?language=en_US),
article last updated 2026-05-27; last Windows driver update
2023-02-07). Source access requires a registration request at
`account.amd.com/en/forms/registration/xdma_windows_driver.html`, the
binaries are attached to the answer record behind a login, and "the
provided drivers only support X86-based platforms".

Per candidate:

| candidate | Windows? |
|---|---|
| U50 / U55C / U280 / U200 / U250 **through the Vitis shell** | **no** - XRT is Linux-only |
| the same cards **shell-less, bare XDMA** | **yes, in principle** - AMD's Windows XDMA driver covers UltraScale+; untested by AMD's own statement, and the whole host stack is new work |
| VC707 (XC7VX485T) | **yes** - "Virtex-7 XT" is named in AR 65444; PCIe Gen2 x8 |
| KCU116, ZCU10x, KU3P/KU5P boards | **yes** - UltraScale+ is named |
| Kintex-7 325T/420T/480T with a PCIe endpoint | **only if the board wires PCIe**; the XDMA driver names "7 Series Gen2" |
| Arty A7-100T, Alchitry Au | **n/a** - no PCIe on either (CSG324 and FTG256 have no transceivers, docs/ROADMAP.md); USB/UART from Windows is unaffected |
| AWS F1/F2, Azure NP | **no** - Linux instances |

The Windows box already runs Vivado 2026.1 with Above-4G decoding
active (docs/BRINGUP.md), so the missing piece for a bare-card Windows
path is the host library's device backend, not the machine.

## 7. Renting instead of buying

The conclusion is negative and worth stating first: **no cloud will
run this project's xclbin, and neither major FPGA cloud will accept a
Vitis kernel at all.**

### AWS EC2 F2 - the right silicon, the wrong flow

F2 carries the **VU47P** - the same die as the Alveo U55C - with 16
GiB HBM at up to 460 GiB/s and 64 GiB DDR4 per FPGA
([AWS launch blog](https://aws.amazon.com/blogs/aws/now-available-second-generation-fpga-powered-amazon-ec2-instances-f2/),
published 2024-12-11, updated 2025-02-05). Sizes: f2.6xlarge (1 FPGA),
f2.12xlarge (2), f2.48xlarge (8). Eight regions as of
[2025-11-12](https://aws.amazon.com/about-aws/whats-new/2025/11/amazon-ec2-f2-instances-four-additional-aws-regions).

**But the Vitis flow cannot produce a loadable image.** From the
developer kit at repo tip (last commit 2026-08-05):

> "Vitis currently only supports Hardware Emulation. Hardware builds
> and AFI creation are not supported at this time."
> ([vitis/ERRATA.md](https://github.com/aws/aws-fpga/blob/f2/vitis/ERRATA.md))

Corroborated in three more places in the same repo, including
[vitis/README.md](https://github.com/aws/aws-fpga/blob/f2/vitis/README.md)
("Vitis AFI generation is not currently supported on F2 instances")
and the F2 User Guide, whose flow table lists the Vitis row's hardware
interface as "XDMA Engine (coming soon)". The HDK - raw RTL, no Vitis -
does work end to end.

Tool versions supported on F2 are 2024.1, 2024.2, 2025.1 and 2025.2
only
([supported_vivado_versions.txt](https://github.com/aws/aws-fpga/blob/f2/supported_vivado_versions.txt)),
so Vitis 2022.2 is not among them.

Pricing, from the AWS on-demand feed behind the public pricing page,
checked 2026-09-06: f2.6xlarge **$1.98/h** in us-east-1 and us-west-2,
$2.475 eu-central-1, $2.6736 ap-northeast-1; f2.48xlarge $15.84
us-east-1. Spot is documented and available - f2.6xlarge $0.672
us-east-1, checked 2026-09-06. **The "Running On-Demand F instances"
quota defaults to 0** and needs a service-quota increase (code
L-74FC7D96) before anything launches.

### AWS EC2 F1 - winding down, and the wrong era

VU9P, 64 GB DDR4 in four 16 GB ECC DIMMs, PCIe x16 Gen3; the shell
leaves 895,200 LUT / 5,640 DSP to the customer logic
([aws-fpga v1.6.1
README](https://github.com/aws/aws-fpga/blob/v1.6.1/README.md)). No
HBM at all.

Supported Vivado versions are 2019.1 through 2021.2 plus 2024.1
([v1.4.25](https://github.com/aws/aws-fpga/blob/v1.4.25/supported_vivado_versions.txt)) -
**2022.2 is not among them**, and no XRT 2.13/2.14 pairing exists. The
Vitis platform is `AWS_PLATFORM_201920_4`, a 2019.2-era platform.

F1 appears to be retiring without an announcement: its product page
301-redirects to the F2 page, the current EC2 accelerated-computing
documentation lists F2 and not F1, and the `aws-fpga` repo's `master`
branch has been deleted in favour of an `f2` default branch. **No
official AWS EOL notice with a date could be found**; third-party
claims of a 2025-12-31 end are UNVERIFIED. On-demand price checked
2026-09-06: f1.2xlarge $1.65/h us-east-1, f1.16xlarge $13.20/h.

### Azure NP-series - closed

The card is an **Alveo U250** on platform
`xilinx_u250_gen3x16_xdma_2_1_202010_1` with XRT 2022.1 and an
`-azure` variant. Loading a custom xclbin requires Microsoft's FPGA
Attestation Service, and Microsoft states: "New preview sign-ups
closed on May 1, 2026, and the service remains available to previously
approved users until June 1, 2026"
([Microsoft
Learn](https://learn.microsoft.com/en-us/azure/virtual-machines/field-programmable-gate-arrays-attestation)).
Both dates are past. A locally-built xclbin is rejected by the
hypervisor with "xclbin is invalid, please provide azure xclbin"
(Error -2060). NP-series retirement was announced 2026-04-02 with VMs
deallocated 2027-05-31. Price checked 2026-09-05 via the Azure Retail
Prices API: NP10s $1.65/h East US.

### What a cloud shell would change even if one worked

Worth recording because it is the reason renting is not a shortcut:

* **Memory topology.** F1 is four DDR4 channels, no HBM - AWS's own
  Alveo-to-F1 migration guide covers only U200-to-F1 and maps `--sp`
  onto four DDR banks. F2 has HBM but **does not hand you pre-wired
  ports**: you instantiate the AMD HBM IP inside the customer logic
  yourself and connect the shell's APB monitors, whose omission is a
  hard AFI-creation error. The HBM side there is **256-bit AXI3**, not
  the AXI4 masters `v++` wires up on a U50.
* **Clocks.** F1 caps the kernel clock at 250 MHz; F2's shell fixes
  `clk_main_a0` at 250 MHz with `clk_hbm_axi` configurable to 450 MHz.
  The project's 135 MHz is comfortably inside both.
* **XRT version.** Neither AWS platform pairs with XRT 2.13/2.14.
* **The host.** F2 replaces XRT buffer management with a
  user-implemented DMA or AWS's Streaming Data Engine, and pyxrt with
  AWS's own Cython `fpga_mgmt` bindings.

**Verdict: renting is a port, not a rental.** An F2 run would mean
lifting the RTL into the AWS customer-logic harness, instantiating HBM
IP and its monitors, converting to AXI3, and rewriting the host - and
at the end of it the Vitis path still cannot make an AFI, so it would
have to be the HDK path throughout. Card-day validation
(docs/CARDDAY.md) is cheaper on the card the project already owns.

### Other clouds and testbeds - not surveyed

Alibaba Cloud F3, Huawei Cloud FP1, Nimbix/Atos, Vast.ai, Chameleon
Cloud, CloudLab, the Open Cloud Testbed, AMD's XACC / Accelerator
Cloud and the academic FPGA clusters were **not reached** before this
survey's web-search budget ran out. They are listed here so the gap is
visible rather than implied to be empty.

Two things are worth knowing before anyone spends time on them.
First, **no provider was found offering U50 or U55C silicon**, and an
xclbin carries a place-and-routed bitstream for specific silicon and a
specific shell, so it cannot load elsewhere - Azure's own rejection
message ("xclbin is invalid, please provide azure xclbin") is a
concrete instance. Second, the academic testbeds (Chameleon, CloudLab,
Open Cloud Testbed, XACC) are the most likely to carry Alveo cards
with an ordinary Vitis/XRT flow and cost nothing, and they gate on an
application rather than a credit card. **If the U55C purchase is being
deliberated, an XACC or Open Cloud Testbed application is the cheapest
way to try the bigger card first**, and is the one unexplored lead in
this section worth an hour.

## 8. Scenario recommendations

### (a) The first open dev node beyond the Arty

**Buy a QMTech XC7K325T core board (~$100, low-confidence price) and
treat its first job as testing openXC7 rather than hosting a tile.**

The reasoning is about evidence, not specifications. `xc7k325tffg676-1`
is the exact die *and package* that openXC7's CI builds
(`blinky-qmtech`, `blinky-stlv7325`), and a demonstrated part is worth
more than a better one. A full tile is 60.6% of an XC7K325T, which is
the comfortable-fit row of §2's table, and Kintex-7 became free-tier
in Vivado 2026.1 so the same board is also a vendor-flow target - a
Vivado-versus-openXC7 A/B on one board is exactly the build-diversity
pairing docs/ROADMAP.md wants.

**But the first result to want from it is not a tile.** It is whether
[#159](https://github.com/openXC7/nextpnr-xilinx/issues/159) still
poisons DSP48E1 results, measured with this project's own conformance
vectors, which is the one instrument that would catch a complemented
INMODE in the first multiply. That is a $100 experiment answering a
question that otherwise blocks the entire open core, and it can run
long before a full tile is placed.

Its DDR3 is 256 MB and 16 bits wide, which at DDR3-800 is about 1.6
GB/s against a tile's 13.82 GB/s - **12% of streaming demand**. That
is fine for the open core's actual purpose (replaying vectors on
auditable hardware) and useless for throughput. Say so out loud rather
than discovering it.

If a host link is wanted in the same step, the **$341 XC7K325T PCIe
Gen2 x8 card** is the cheapest board found with a real x8 edge and 1
GB of DDR3 - but PCIe on it means Vivado, because openXC7 has no PCIe
hard-block support at all.

*Not recommended:* the PZ SOM family, until the carrier price is
quoted (the x8 KFB has no published price and the cheaper FH variant
silently wires only two lanes); and the PZ-K7410T specifically, since
XC7K410T is absent from the openXC7 database.

### (b) The cheapest conformance node that holds a quarter tile

**Buy nothing. The Arty A7-100T already ordered covers this, and the
Alchitry Au does not.**

A quarter tile is ~20k LUT against the XC7A35T's 20,800 - **96%**, and
a 96%-full 7-series part is not a part an open place-and-route flow
routes. The Au V2 at $149.99 remains the cheapest *object* that could
attest the contract, but it is the wrong side of the routability line
and docs/ROADMAP.md already flags it as "tight, and the first thing to
measure".

The Arty A7-100T, at 63,400 LUT, carries the **fp32-max tile at 68.2%**
- more than a quarter tile, on the part that is openXC7's and LiteX's
reference target, for a board already paid for. Measure that first.
`tb_krnl_quarter` already runs the RTL at 64-bit beats against the
golden model, so the software side of this is done.

Only if the Arty proves the flow and a *farm* is wanted does the Au
become interesting again, and its case was always the FT2232 USB
replay rate rather than its area.

### (c) The monolithic licensed step-up, and the licence

**The licence covers it. Buy it anyway only if 64 GB of DDR4 is the
point - not if tile count is.**

On the licence, the belief in docs/ROADMAP.md is confirmed and
strengthened: in the Vitis 2022.x era the project must use anyway,
UG973's Alveo row reads "All" for the free ML Standard edition, so
**no licence is needed at all** for a U200 or U250; and in 2026.1+ the
Alveo tier the project already holds is documented as the tier that
covers Alveo devices as a class. §5 has the citations. A used card
carries no entitlement and does not need one.

The arithmetic is where the enthusiasm should stop. A U250 takes
**seven tiles by area** but its four DDR4 banks deliver 77 GB/s, which
is 5.57 tiles at an efficiency no controller achieves under four
interleaved streams per tile. Against a U50 quad that is somewhere
between "no gain" and "one extra tile", for a 215 W dual-width card
that also brings **a -2L device where the U50 is a -2** - so the
135 MHz that closes with +0.143 ns on the owned card is a hypothesis
there, not a carried-over result - and:

* the **same encrypted-shell-IP era problem** - the U200 platform was
  built by 2021.1 tools, the U250's by 2022.1, so this is the U50's
  toolchain constraint again with older keys, not an escape from it;
* a **new reboot ritual** - U250 platforms are DFX-2RP and the shell
  partition must be reprogrammed after every cold and warm reboot
  (AR 75975);
* a **cooling problem** unless the active SKU is bought.

**And there is a cheaper way to buy fabric, if the shell is being
given up anyway.** A bare **BittWare CVP-13** is the same VU13P as the
U250 at **$1,200** - roughly $150 a tile against the U250's $500 at
its lowest observed price of $3,499.99 - and a bare **VCU1525** is the
U200's die without the shell's 189K-LUT bite out of SLR1. Neither has
a shell, XRT, `xbutil`, or any vendor support a second owner can
inherit; both are ex-mining cards; and §1's supply-risk note applies
with force at those prices. But the work they demand is the *same*
shell-less work that buys modern tools and Windows (§6).

**But check the licence before believing that arithmetic.** A bare
card targets `xcvu13p`/`xcvu9p`, which are **Virtex UltraScale+
devices, not Alveo devices** - separate rows in UG973's tier table, and
"None" under Basic. The Alveo entitlement the project holds does not
reach them, so a CVP-13 needs a **paid Core subscription** the project
does not have, every year. The real comparison is **$1,200 plus a
recurring subscription against $3,500 and none**. That narrows the gap
a great deal and reverses it by year two or three.

So: if `cftx_open`, `xbutil` and the layout library are to keep
working, only the U200 and U250 have a shell, and they are also the
only DDR4 option the current licence covers. The bare cards are for a
future in which the shell-less host backend exists and a Core
subscription is already being paid for something else.

One argument on the other side, recorded because it is real: the 5.57
figure prices the **elementwise streaming** mode, and a sequencer
program run - the atlas workload, the one the tile exists for - moves
far less memory per unit of arithmetic (§1). A U250 running sequencer
programs might well use its seven tiles. Nobody has measured a
sequencer program's bandwidth on any memory, so that argument cannot
yet carry a purchase.

**If a DDR4 card is bought, buy it for memory depth.** The U50's
one-master-one-pseudo-channel mapping caps an argument buffer at 256
MB per tile; a DDR4 bank is 16 GB. That is the genuine 64x win, and it
is the thing the deep-zoom and orbit workloads would actually feel.

**And on that basis buy the U200, not the U250.** They carry the same
64 GB of DDR4 at the same 77 GB/s, so the memory-depth argument -
the only argument that survives this section - is identical on both.
The U250's advantage is two extra tiles (seven against five) and a
tidier one-DDR-bank-per-SLR mapping against the U200's lopsided
DDR[2]-and-DDR[3]-on-SLR2. It costs **$3,499.99 at its lowest observed
price against the U200's $1,150-$1,373** - roughly three times the
money for 40% more tiles that the memory cannot feed anyway. Buy the
**active SKU** either way (`A-U200-A64G-PQ-G`) for a workstation host.

### (d) An HBM successor to the U50

**The Alveo U55C, and it is not close.**

Against the U50: **6 tiles instead of 4** (§1's per-SLR table), **16 GB
of HBM instead of 8**, **460 GB/s instead of 316**, and the same 32
pseudo-channels - so the one-master-one-PC rule that carries the
project's ordering argument survives unchanged, and the per-buffer cap
doubles from 256 MB to 512 MB.

**And the toolchain does not move.** Its development platform is still
`xilinx-u55c-gen3x16-xdma-3-202210-1-dev`, the same `202210_1`
generation as the U50's, served today from AMD's U55C download page
alongside XRT 2.19 and a 2024-dated deployment package. That is
precisely the era-matched pairing docs/BRINGUP.md already runs, so
`hw/rebuild-2022.sh`, the `cft2204` WSL distro and the Vitis 2022.2
install on amd-arc-box all transfer unchanged. **No second toolchain
era, no new encrypted-IP problem, no new host stack** - which is the
opposite of every other option in this document. The licence question
is the same one answered in (c).

Six tiles is an area result, not an interface one: 24 of 32
pseudo-channels are spent, and 6 x 13.82 = 82.9 GB/s is 18% of the
card's bandwidth. **Area is still the wall, exactly as it is on the
U50** - which means the sizing work docs/ROADMAP.md has been doing on
the tile pays out directly in tiles per card here, and the layout
catalogue of docs/LAYOUTS.md regenerates for a bigger budget without
changing shape.

The one thing to settle before buying: **it is passive-only**, 150 W
total load and 115 W TDP with a documented airflow dependency. The
project's U50C is a 75 W custom active unit and has never needed an
airflow answer; a U55C does.

*The U280 is the alternative and loses on both counts that matter:*
the same 6 tiles and the same 1,304K LUT, but 8 GB of HBM instead of
16, plus 32 GB of DDR4 this design has no use for, at 215 W and dual
width. Take it only if it is dramatically cheaper used.

### (e) Validation without buying

**Not possible today. Do card day on the U50C.**

All three routes are closed, each for a different reason (§7):

* **AWS F2** has *the right silicon* - VU47P, the same die as the
  U55C - and its own developer kit says at repo tip "Vitis currently
  only supports Hardware Emulation. Hardware builds and AFI creation
  are not supported at this time."
* **Azure NP** is a U250, and the attestation service that is the only
  way to load a custom xclbin closed to new sign-ups on 2026-05-01 and
  to everyone on 2026-06-01. The series is retiring.
* **AWS F1** supports no Vivado between 2021.2 and 2024.1, so not
  2022.2, has no HBM, and appears to be retiring without an
  announcement.

And even with a working path it would be a port rather than a rental:
different memory topology, AXI3 instead of AXI4 on F2's HBM, HBM IP
instantiated by hand with shell monitors whose omission is a hard AFI
error, XRT replaced by AWS's own bindings.

**Worth watching, though.** F2 *is* the U55C's die. If AWS enables the
Vitis AFI path - the F2 user guide's flow table already lists its
hardware interface as "XDMA Engine (coming soon)" - then an f2.6xlarge
at $1.98/h on-demand or $0.672/h spot becomes an exact rehearsal for a
U55C purchase, at a few dollars per experiment. That is the single
cheapest future option in this document and costs nothing to keep an
eye on.

### (f) The Windows story

**Shell means Linux; bare means Windows is possible but untested.**
§6 has the per-candidate table. In one line each:

* Every Alveo card **through its Vitis shell is Linux-only** - AMD's
  XRT system requirements list Linux for PCIe accelerator cards and
  Windows only for the NPU. That covers the U55C and U250
  recommendations above.
* The **same cards shell-less** can in principle run from Windows on
  AMD's own XDMA driver, which covers "UltraScale+, UltraScale,
  Virtex-7 XT and 7 Series Gen2 devices" - and which AMD describes as
  "only provided as a reference to get started and has not been
  thoroughly tested".
* The **VC707, KCU116, ZCU10x and any Kintex-7 board with a PCIe
  endpoint** are all in that driver's stated device range, so a bare
  design on any of them is a Windows candidate.
* The **Arty and the Alchitry Au have no PCIe at all** and reach
  Windows over USB regardless.
* **Nothing in the cloud is a Windows path.**

The Windows box already has Vivado 2026.1 and confirmed Above-4G
decoding (docs/BRINGUP.md), so what is missing for a Windows card path
is a device backend in libcft, not hardware. Given that shell-less
also dissolves the era-matched-tools problem (§1), a bare XDMA design
on a free-tier Kintex-7 is the one configuration in this document
that is simultaneously buildable on current tools, drivable from
Windows, and licensed for nothing.

## 9. Verify before buying

### 0. Free, do it first, blocks two recommendations

**Does the licence file actually enable a U250 part?** §5 establishes
what AMD says the tier covers. It does not establish what the FEATURE
lines in `~/.Xilinx/Xilinx.lic` on amd-arc-box enumerate. Ten minutes,
no purchase:

```bash
grep -i '^\(FEATURE\|INCREMENT\)' ~/.Xilinx/Xilinx.lic   # what is granted
# then the real test, on the Windows box or amd-arc-box under 2026.1:
vivado -mode batch -source /dev/stdin <<'EOF'
create_project -in_memory -part xcu250-figd2104-2L-e
EOF
```

A part that cannot be selected is the answer. If it can, take a
trivial design through `synth_design` and `write_bitstream` - the tier
table's own footnote warns "Some devices can have bitstream generation
under license control", so synthesis succeeding is not proof that
bitstream generation will.

**Is "Basic" actually the free tier?** The same session settles it.
Install 2026.1 with no licence file present and check that `xc7k325t`,
`xc7k480t` and `xc7vx485t` are selectable and that `write_bitstream`
completes. Every Kintex-7 recommendation in §3 rests on an inference
from UG973's tier ordering, not on AMD stating the word "free" in that
document.

### 1. Before the QMTech XC7K325T board (~$100)

* **Build `blinky-qmtech` from openXC7's demo-projects on your own
  machine before ordering.** If the toolchain does not build for you,
  the board is not the problem to solve first.
* Confirm the listing's **package is `ffg676`** - the CI part is
  `xc7k325tffg676-1`. A `ffg900` board is the Genesys 2 / Alinx
  package and is a different chipdb.
* Confirm DDR3 size and width. The figure found was 256 MB / 16-bit
  (MT41K128M16), and flash size conflicts between sources (128 vs 256
  Mbit).
* Confirm a JTAG programmer is included or on hand.
* **Re-check [#159](https://github.com/openXC7/nextpnr-xilinx/issues/159)
  before treating any openXC7 arithmetic result as meaningful.** If it
  is still open, plan the DSP vector run as the *first* experiment, not
  a later one.
* Price is from an AliExpress listing title and is **low confidence**.
  Confirm on the loaded page.

### 2. Before an Alveo U55C

* **Airflow.** 115 W TDP, passive only, with a documented airflow
  dependency ("TDP is dependent on server airflow capability", DS978).
  Decide the chassis before the card. This is the one item that has
  never applied to the project's active 75 W U50C.
* **AUX power.** The card takes AUX; confirm the PSU has the connector
  and that the host's slot is not a x8-wired x16.
* **Platform packages: confirmed present 2026-09-05, so download them
  now rather than trusting they persist.** The development platform
  `xilinx-u55c-gen3x16-xdma-3-202210-1-dev-1-3514517.noarch.rpm` and a
  2024-dated deployment package were both being served from AMD's U55C
  page on the date of this survey. Only `.rpm` builds were seen on the
  RHEL/CentOS tabs read; **confirm a `.deb` exists for Ubuntu 22.04**
  (the `cft2204` distro) before buying, or plan on `alien`.
  Archive both packages locally on purchase - the documented support
  window ("2022.1 with support planned through 2023") has passed and
  the pages could change without notice.
* **Card health on arrival.** `xbmgmt examine -d <bdf>` should report a
  base platform and an SC firmware version. A card that enumerates but
  reports no shell, or whose SC will not update, is the failure mode
  that makes a used card worthless.
* Confirm the SKU is `A-U55C-P00G-PQ-G` rather than an OEM variant with
  a different shell.
* Ask the seller whether the card came out of a mining or crypto
  deployment, and for its thermal history. Passive data-centre cards
  run hot by design; one that ran hot *without* ducted air is a
  different proposition.

### 3. Before an Alveo U200 or U250

Everything in list 2, plus:

* **Buy the active SKU** (`A-U200-A64G-PQ-G` / `A-U250-A64G-PQ-G`)
  unless the host is a real server with ducted airflow. The passive
  parts are ¾-length dual-width data-centre cards.
* **150 W PCIe AUX cable required** (DS962), on top of the 65 W from
  the slot.
* **Rehearse the DFX-2RP two-stage flow on the U250 before trusting
  it.** `xbmgmt program --shell <partition.xsabin> -d <bdf>` after
  every cold and warm reboot (AR 75975). Decide where that lives -
  a systemd unit, or `hw/run-device-test.sh` - before card day rather
  than during it.
* **Confirm the era-matched toolchain builds for it.** The U200
  platform was created by 2021.1 tools; whether Vitis 2022.2 links
  against it as cleanly as it does the U50's 2022.1-built platform is
  unverified. Test with a trivial kernel before committing to a
  multi-tile build.
* Confirm which of the three U250 platform generations the card's
  flash actually holds; `2_1_202010_1`, `3_1_202020_1` and
  `4_1_202210_1` are all DFX-2RP and all different.
* **Confirm all four DDR4 DIMMs are present.** They are socketed
  288-pin RDIMMs, and "card only" is a normal condition in this
  market.
* **Settle the -2L operating point before promising a clock.** These
  are -2L parts against the U50's -2. Read VCCINT from the card
  (`xbutil examine` sensor output) and re-run timing at whatever
  frequency actually closes; do not carry 135 MHz across.

### 4. Before a bare card (CVP-13, BCU1525, VCU1525)

* **Price the Vivado Core subscription into the purchase.** The part is
  `xcvu13p`/`xcvu9p`, not an Alveo device, so the project's Alveo
  entitlement does not cover it and Basic reads "None". This is a
  recurring cost, not a one-off, and it is the item most likely to be
  missed.
* **Budget the host stack as the real price.** No XRT, no `xbutil`, no
  xclbin, no `cftx_open`. libcft's device backend would need a second
  implementation against the XDMA driver.
* **Assume the die needs authentication.** At the prices in §1, incoming
  device-ID checks and a full-fabric-at-temperature run are not
  paranoia. The conformance vectors are the right instrument.
* Confirm the DDR4 DIMMs are populated and the cooling solution is
  intact - many of these are liquid-cooled ex-mining cards.
* Confirm the aux connectors the board actually wants (the VCU1525
  ladder is 75 W slot-only / 150 W with 6-pin / 225 W with 8-pin, and
  VCCINT is capped at 35 A on the first rung).

### 5. Before any used data-centre card at all

* **A JTAG cable, bought before the card, not after.** Golden-image
  recovery (AR71757) is the only route back from a bad flash, and it
  needs one.
* **Above 4G Decoding** in the host BIOS. Note §1's correction: this is
  not actually documented by AMD for Alveo compute cards. Enable it
  regardless - it costs nothing - but **still confirm it on
  amd-arc-box's X99-UD4**, which is the box holding the licence
  node-lock and the 46 GB of RAM, and if a card fails to enumerate go
  to the BIOS fastboot / bifurcation / USB-cable checklist first.
* Slot: x16 physical *and* electrical, non-bifurcated, and a chassis
  that takes a dual-width card if the SKU is dual-width.
* **The AUX cable, and the right one.** A missing one shows up as
  `xbmgmt examine` reporting "Max power 150W"; a wrong one
  (ATX12V/EPS12V into the PCIe 8-pin) can damage the card.
* **A seller's return policy is the only protection against a bricked
  golden image.** Prefer a seller who will take a card back.
* Kernel: XRT 2.19's DKMS drivers need a 6.8-series kernel on
  amd-arc-box (docs/BRINGUP.md) - that work is already recorded and
  applies to any card.
* **Know what a protection trip looks like before it happens**: the
  card leaves the PCIe bus with no firewall alert and needs a cold
  reboot. Write that into `hw/run-device-test.sh`'s failure guidance
  so an under-powered quad is not diagnosed as a design fault - which
  is exactly the class of expensive misdiagnosis docs/BRINGUP.md has
  twice recorded.

### 6. Before a KCU116 at list price

* **Check the used market first.** $6,495 for one tile at 57% is not a
  rational purchase; the same die appears on the
  `aliexpress_rk_xcku5p` board with 2 GB of DDR4 and PCIe 3.0 x4, for
  which no price could be found. Get one.
* **Check the DDR4 width.** AMD's page says "DDR4 up to 32-bits",
  which at DDR4-2400 is 9.6 GB/s against a tile's 13.82 GB/s. If that
  is the real width, one tile on a KCU116 is memory-starved by about
  30% and the board is a timing and area vehicle, not a throughput
  one.

## 10. What could not be verified

Listed rather than smoothed over, roughly in order of how much each
one matters to a decision.

**Numbers that are estimates, not measurements.**

* **The DDR4 efficiency haircut.** §1 divides 77 GB/s by 13.82 GB/s to
  get 5.57 tiles and then says the real figure is lower. *How much*
  lower is an estimate. It is the largest unverified number in this
  document and it is load-bearing for recommendation (c).
* **The per-CU crossbar increment on a 3- or 4-SLR device.** The
  12,626 LUT figure is differenced from U50 builds. docs/SCALING.md
  already warns that the shell crossbar "grows with port count and
  goes superlinear eventually"; twenty masters on a U250 is well past
  where that was measured.
* **7-series area for this design.** Every 7-series percentage is an
  UltraScale+ measurement carried across a different carry structure
  (21 CARRY8 becomes 42 CARRY4). Nothing in this document is a
  7-series measurement of this tile, because none exists.
* **openXC7 DSP counts.** The 390-400 figure is docs/ROADMAP.md's
  estimate from the 18x18 decomposition, un-measured.
* **A sequencer program's memory bandwidth**, on any memory. `make
  cycles` measures the streaming engine only, so every per-tile
  bandwidth figure here prices the elementwise mode and none of them
  prices the atlas workload. This is the measurement that would most
  change recommendation (c), and it can be taken in simulation without
  buying anything.

**Facts that are inferences.**

* **That Vivado's "Basic" tier is the zero-cost tier.** Strongly
  implied by tier ordering and by the UltraScale rows matching the
  historical WebPACK lists; not stated in words in UG973.
* **That the K26 SOM's PL is a ZU5EV.** Every DS987 PL figure matches
  DS890's XCZU5EV column exactly; AMD never writes it.
* **That AXI ordering survives DDR4 bank sharing.** Derived from the
  AXI same-ID-same-slave rule (§1), not measured on a DDR4 platform.
* **That the Alveo marketing LUT figures (892K for the U200, 1,341K
  for the U250) are post-shell.** They differ from DS962's device
  totals by 290K and 387K respectively, which is consistent with a
  shell, but no AMD source was found stating it. This document uses
  DS962's totals and UG1120's dynamic-region figures and ignores the
  marketing numbers entirely.

**Things simply not found.**

* **Which VCCINT the Alveo deployment shells actually program on a -2L
  part.** DS890 says a -2L runs like a plain UltraScale device at
  0.72 V and "over 30% faster" at 0.85 V. The U200, U250 and VCU1525
  are all -2L. Whether a U250 would reach the U50's 135 MHz therefore
  cannot be answered from documents; it needs a card. This is the
  second-most decision-relevant gap in the survey after used pricing.
* **The U55C's and U280's shipped speed grades.** No AMD datasheet
  states a speed grade for any Alveo card; the three -2L strings above
  come from third-party mirrors of UG1289 and UG1268, and no
  equivalent was found for the HBM cards.
* **Any sold price, anywhere.** eBay's sold-listing pages are
  403-blocked to this tooling, so every eBay figure in §1 is an
  *asking* price on an active listing. Asking prices in this market
  span an order of magnitude on the same part.
* **The Stratix 10 GX/SX 2800 ALM count**, and hence any honest
  fabric comparison for the D5005 and the 520N.

* **Whether shell-less Alveo retains thermal and power supervision.**
  UG1120 publishes throttle and shutdown thresholds per platform;
  whether they are enforced by the card's satellite controller
  independently of the FPGA image, or by logic inside the shell, could
  not be established. On a 215 W card this is not a detail.
* **The HBM controller's maximum AXI port clock.** PG276 gives the
  width (256-bit, 4:1 ratio) and the protocol but no maximum port
  frequency was located; AWS's F2 documentation says 450 MHz for the
  same AMD IP, but that is AWS's document about AWS's card. Not
  binding at 135 MHz.
* **Whether a *fresh* Vitis 2022.2 install today still receives the
  free Alveo device coverage** that UG973 2022.1 documents, given the
  licensing infrastructure has changed since. Only matters for a third
  build machine; both existing ones are already installed and licensed.
* **An official AWS end-of-life date for F1.** The evidence of
  retirement is circumstantial but strong (product page 301s to F2, F1
  absent from current instance documentation, `master` branch of
  `aws-fpga` deleted); third-party claims of 2025-12-31 are
  unconfirmed. `repost.aws` returned 403.
* **The exact XRT version in the current F2 developer AMI.** Release
  notes say "Updated XRT version" without a number.
* **A published openXC7 design above 50% utilisation, on any part.**
  Searched for; none found; the demo repository publishes no
  utilisation figures at all.
* **Prices:** Numato Nereid and Aller (RFQ only), the PZ x8 KFB
  carriers (quote only), KCU105, ZCU104, ZCU106, KR260, NiteFury II
  (not listed for sale), the `aliexpress_rk_xcku5p` board, VectorPath
  815, ACE licensing, and MPF300-EVAL-KIT / MPF300-SPLASH-KIT (two
  conflicting index figures each, every tiebreaker distributor
  blocking).
* **Board specs:** the MPF300 eval kit's PCIe generation, lane count
  and DRAM; the Arria 10 GX kit's board specs (product page 404s);
  Agilex 7 per-device DSP and M20K counts.
* **Vendor SystemVerilog statements** for Lattice (LSE specifically)
  and Achronix; both synthesise through Synplify Pro, whose vendor
  page claims SystemVerilog without naming an IEEE 1800 revision or
  enumerating constructs.

**A methodological limit worth recording.** This survey exhausted its
web-search budget partway through and finished on direct document
fetches. Several marketplaces (eBay, AliExpress, Amazon, Digi-Key,
Mouser, Avnet, Digilent direct) refuse automated fetching entirely, so
**used-market pricing is the weakest evidence in this document** and
every figure drawn from a search index rather than a loaded page is
marked as such. Treat those as leads to click, not as quotes.
