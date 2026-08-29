# Hardware bring-up

The ordered gates between "green in simulation" and "the card
reproduces the vectors". Everything here needs the Linux box with
Vitis/Vivado (2022.2 or later recommended for the platform below) and
XRT; nothing before this file does.

Record each gate the way a census is recorded: tool versions, platform
name, xclbin hash, and the exact command. A bring-up you cannot replay
is a bring-up you do not have.

## 0. Environment

**Linux only, the whole flow.** Vivado alone runs on Windows, but v++
linking, XRT, pyxrt, and the Alveo platform packages (.deb/.rpm) are
Linux-only - keep packaging, linking, and the card on one Ubuntu box
rather than splitting the flow across OSes. WSL2 can *build* (it is a
Linux userland) but cannot reach the card; treat it as a compiler at
most.

Before installing anything, three pairings have to agree - check, then
install, in this order:

1. **Ubuntu release <-> Vitis release.** Vitis versions support
   specific Ubuntu point releases (2022.2 tops out at 22.04.1-era;
   24.04 needs a newer Vitis). `lsb_release -a` first, then pick the
   Vitis whose supported-OS table names it (UG1301 / release notes).
2. **Vitis release <-> platform package.** The platform here
   (`*_202210_1`) is the 2022.2-generation U50 platform; later Vitis
   releases still link against it while U50 remains in their support
   matrix.
3. **XRT <-> platform.** Install the XRT .deb the AMD U50 download
   page pairs with the deployment platform (the `-dev` platform
   package declares its minimum XRT).

Also worth checking before first contact: ~100-250 GB free disk for
Vitis (a lean device selection fits ~80 GB) plus workspace; BIOS
"Above 4G Decoding" enabled or the card will not enumerate; and
airflow appropriate to the card - stock U50s are passive and need
ducted chassis air, while this project's U50C is a custom active-cooled
unit (75 W, fan attached), which removes that worry. The U50C also
exposes a USB Mini-B JTAG/UART port: a recovery/flash path and Vivado
hw_manager access that stock U50s route through the PCIe shell only.

## Lab map (surveyed 2026-08-28)

| box | hardware | role |
|---|---|---|
| amd-arc-box (192.168.0.201) | Xeon E5-2697 v4 36t, 32 GB, 238 GB NVMe (167 free), RX 7600 + Arc B580 + Arc A750, Ubuntu 24.04 | **build box** (Vitis + v++); card host IF its X99-UD4 BIOS exposes Above 4G Decoding (common on X99 - check; /proc/iomem shows none mapped today) |
| nvidia-box (192.168.0.234) | i5-6600K 4t, 8 GB, 117 GB SSD, GTX 1080, mini-ITX, Ubuntu 24.04 | too small for v++ links (8 GB); last-resort card host - single slot means pulling the 1080, which breaks an atlas census column |
| Windows box (MSI PRO B760-P) | Vivado 2026.1 installed with U50 part support; Above-4G decoding confirmed ACTIVE | .xo packaging + synthesis experiments today; strong card-host fallback via dual-boot Ubuntu on a spare drive |

Both Linux boxes run Ubuntu 24.04, so the native Linux Vitis must be a
24.04-capable release (2026.1, matching Windows). The open question is
whether v++ 2026.1 still links against the 2022-era U50 platform
(`*_202210_1`); if it refuses, the fallback is the link step inside an
Ubuntu 22.04 Docker container carrying an older Vitis on amd-arc-box -
the OS-pairing problem dissolves in a container.

```bash
source /opt/xilinx/xrt/setup.sh          # also puts pyxrt on PYTHONPATH
source /tools/Xilinx/Vitis/2022.2/settings64.sh   # your version here
make check-env                            # tools, platforms, cards, in one look
xbutil examine
```

**TOOLING VERDICT (2026-08-29): hardware bitstreams for this platform
require era-matched tools.** Vivado 2026.1 cannot decrypt the shell's
2022-era encrypted IP (`clk_metadata_adapter` fails with Synth 8-5809
"encrypted envelope" - AMD obsoletes IP encryption keys after ~5
years), so `v++ -l -t hw` is impossible from 2026.1 no matter what the
kernel does. The build flow is **Vitis 2022.2**, bare-metal on Ubuntu
24.04 with two legacy libs (libtinfo5/libncurses5 from jammy, staged
in ~/installers on the build box; 22.04 container is the fallback if
bare-metal misbehaves). 2026.1 was removed from the Linux box (it
could neither build hw nor run hw_emu for this platform) and remains
on Windows for kernel packaging and OOC QoR work, where the encrypted
shell IP never enters the picture. xclbins built by 2022.2 run under
the newer XRT 2.19 runtime - that pairing is what AMD's own 2024.1
U50 deployment re-release ships.

**The era-build environments (2026-08-29).** Two interchangeable
Vitis 2022.2 homes, both driven by `hw/rebuild-2022.sh` from the repo
root:

- amd-arc-box: `/data/Xilinx` on the Micron 256 GB (label
  `vitisdata`, fstab nofail; the drive rides a PCIe x1 adapter and is
  not hot-plug - reseat means reboot). Shims libtinfo5/libncurses5
  installed.
- Windows box: WSL distro `cft2204` (Ubuntu 22.04 on D:\wsl, ~1 TB
  virtual disk), Vitis at `/opt/Xilinx`, installer + dev-platform deb
  staged in `/mnt/d/cft-vitis2022`. Enter with
  `wsl -d cft2204 -u root`.

Auth for AMD installers, learned the hard way: `AuthTokenGen` tokens
from this account are rejected at Install time on every machine and
both installer generations - the GUI login works every time. Use the
GUI (on the box's desktop, or via WSLg from the distro).

**Network note for future debugging on amd-arc-box:** its "wired"
path is switch -> Wi-Fi extender -> router. The extender bridges
wired MACs by ARP-NAT translation, and that state table wedges after
port flapping (measured 2026-08-29: LAN unicast kept flowing while
ARP/ND to the router alone failed, both IP versions). If the box
drops off the network, power-cycle the extender FIRST - and never
dual-home it on Wi-Fi + wire simultaneously (ARP flux). A direct
cable or powerline run is the long-term fix. Also: www.amd.com
requires a browser user-agent from scripts; bare wget fails on the
front door (download.amd.com is fine).

**Card-day kernel prep:** XRT 2.19's DKMS drivers do not build
against the box's 7.0-series kernel and no 6.8 GA kernel is
installed. Before flashing, run:

```bash
sudo apt install -y linux-image-generic linux-headers-generic
sudo dpkg-reconfigure xrt   # rebuilds DKMS for the 6.8 kernel
```

then boot the 6.8 entry from GRUB for card sessions.

**Licensing (resolved 2026-08-29, applies to 2026.1+ tools).** The
2026.1 release gates Vivado's *launch* on a license; the free BASIC
tier does not cover xcu50 (Virtex UltraScale+ needs CORE+, Alveo has
its own tier). What works: the **Alveo-tier license** that comes with
an Alveo card purchase, generated on the AMD portal, node-locked to
the build box's NIC MAC. On amd-arc-box: `~/.Xilinx/Xilinx.lic`,
HOSTID = eno1 (fc:aa:14:2e:43:5a), features Vivado_Alveo_Package +
Synthesis + Implementation + Simulation, **valid through 2027-08-29**
- calendar the renewal; synthesis stops when it lapses. The account
allows one node-lock per entitlement: it lives where v++ runs. The
CLI AuthTokenGen flow produced tokens the installer rejected twice;
the GUI installer's interactive login worked - prefer it.

`xbutil examine` names the shell the card actually runs. The Makefile
default is `xilinx_u50_gen3x16_xdma_5_202210_1`; a U50C may report a
different platform name/generation - pass `PLATFORM=<what xbutil
says>` to make rather than editing files. If the reported part differs
from `xcu50-fsvh2104-2-e`, pass `PART=` too.

## 1. Gate: the packaging script runs - **MET 2026-08-28**

```bash
make xo
```

Ran clean on first contact against Vivado 2026.1 (Windows install,
`PART=xcu50-fsvh2104-2-e`): interfaces auto-inferred from the port
prefixes, `build/cft_krnl.xo` written with all six RTL sources and the
kernel.xml arg map (`mode, n, a, b, c, d`) embedded and verified by
inspection. `.xo` files are portable - packaging on Windows and
linking on Linux is a legitimate split while the Linux Vitis lands.

Still holds for any future RTL change: the testbenches guard the RTL,
so changes loop through `make sim-docker` before repackaging.

## 2. Gate: hardware emulation - **MET under the era stack (2026-08-29)**

Final state first: with the fully era-matched stack (Vitis 2022.2
link + the 202210 platform + XRT 2.14.354, in the cft2204 WSL distro),
`host/examples/vector_fma.py` **PASSES bit-exact against cft_golden
on both precisions** - fp32 fma n=32 (specials-laced stream, sticky
flags matching) and fp256 fma (the 237-bit datapath correct to the
last bit) - through the complete XRT/shell/CSR/engine/HBM-model
chain. The 2026.1-era write-payload ghost was confirmed pure version
skew; the kernel was innocent throughout, exactly as the AXI traces
testified. Era-emulation prerequisites beyond the tools: XRT 2.14
22.04 deb (via the amdOpenDownload endpoint with browser headers),
build-essential (the platform's SystemC models compile at link time),
python3-numpy (this pyxrt's readback path).

**Re-met on the v1 design (2026-08-29), all four rungs and the
streaming engine.** `hw/emu_smoke.sh` runs one op per precision
through the same stack: fp32/fp64/fp128/fp256 fma all bit-exact
against the golden model, including the sticky-flag word. Then the
case that matters for the burst engine - fp32 fma n=296, i.e. 37
beats, so each stream issues two full 16-beat bursts plus a ragged
5-beat tail, with reads, compute and writes overlapping - **PASSES
bit-exact** against Xilinx's own interconnect and HBM models. That
is the evidence cocotb's RAM model cannot give: the burst geometry
(4KB-boundary safety, ARLEN/AWLEN encoding, WLAST placement,
back-pressure) is validated against the vendor's checkers, not
against our own testbench's assumptions.

Field note on reading smoke output: a *numerical* failure always
prints MISMATCH/FAIL lines. A case that prints no verdict line at all
is an infrastructure fault, not a result. It happens intermittently -
observed on the first case of one run and on the second case of
another, roughly one case in ten - and the same case passes when
rerun alone every time it has been tried. Python exits 0 with empty
output, so the run is being lost somewhere in the emulator handoff
rather than crashing the host process. The script reports the exit
code in that situation so the two can never be confused; rerun the
case before believing anything about it.

The tooling-skew record below is kept for the field notes it contains.

### The original 2026.1 attempt - blocked by tooling, evidence recorded

Attempted in full on amd-arc-box: the hw_emu xclbin links and boots,
and instrumented runs proved through real XRT + the real shell design:
argument marshaling to the CSR (every offset exact), the ap_ctrl_hs
protocol against XRT's scheduler, BO addressing, the read path
end-to-end, and the engine emitting byte-perfect writes the platform
acknowledges OKAY. Then the write PAYLOAD arrives at memory as zeros -
at 512-bit and at native 256-bit, single-bank and grouped, ERT on and
off, while host-only sync round-trips work. Verdict: the 2022-built
platform simulation models lose W-channel payloads under 2026.1's
emulation libraries (the sim log's XTLM deprecation warnings are the
tell). Nothing in that failing path exists in hardware.

Waived accordingly: correctness weight rests on the cocotb suite and
the on-card vector gates below. If emulation is ever needed again,
the fix is era-matched tools (Vitis 2022.2 + XRT 2.13) in an Ubuntu
22.04 container - not more debugging of the skewed stack. The
campaign's lasting artifacts: synthesis-guarded $display tracing in
cft_csr/cft_engine, and the move to a 256-bit m00_axi (native HBM
pseudo-channel width, no converters anywhere, simpler engine, looser
host contract).

Original plan for reference:

```bash
make xclbin TARGET=hw_emu
make emconfig     # emits build/emconfig.json - hw_emu refuses to run without it
cd build && XCL_EMULATION_MODE=hw_emu python3 ../host/examples/vector_fma.py \
    cft_hw_emu.xclbin --format fp32 --op fma --n 64
```

(XRT looks for emconfig.json in the working directory or EMCONFIG_PATH;
running from build/ is the simplest arrangement.)

Runs the RTL against the platform's SystemC HBM model with the real
XRT stack - the first time the kernel.xml argument map, the CSR
protocol, and the host code meet Xilinx's implementation rather than
cocotb's. Small N; hw_emu is slow.

## 3. Gate: link for hardware - **MET 2026-08-29**

```bash
TARGETS=hw KERNEL_FREQ=100000000 bash hw/rebuild-2022.sh
```

Three bitstreams are banked on amd-arc-box, oldest first:

| file | design | kernel clock |
|---|---|---|
| `cft_hw_v0_10mhz.xclbin` | v0 behavioural core, naive engine | 10 MHz |
| `cft_hw_v1_2bank_100mhz.xclbin` | v1 pipelined core, fp32+fp256 banks | 100 MHz |
| `cft_hw_v1_4rung_90mhz_prereview.xclbin` | four rungs, streaming engine, rounding attributes | 90 MHz |
| `cft_hw.xclbin` | the same, plus the control-review fixes (STATUS, latched run config) - **the card-day image** | 90 MHz |

Build cost on amd-arc-box, measured on the four-rung design: synthesis
18m, logic opt 3m, placement 44m, routing 18m, bitstream 25m - 1h47m
end to end, or ~1h25m if a run only needs the timing report and stops
after routing. One link peaks at ~12 GB, so the 31 GB box runs two
concurrently; that is the binding constraint on any frequency sweep,
not the 36 cores.

**Calibration, and a correction to how it was first read.** Two
routed builds:

| design | target | routed WNS | endpoints |
|---|---|---|---|
| v1 core, two banks | 100 MHz | +0.051 ns | 480,929 |
| four rungs + streaming engine | 90 MHz | +0.055 ns | 523,123 |
| the same + control-review fixes | 90 MHz | +0.055 ns | 523,361 |

All three land ~50 ps above zero, across different clocks and a 3x
difference in logic. The first was recorded here as "the shell and
routing eat essentially all the margin" - that reading does not
survive the second data point. Vivado's implementation is
*constraint-driven*: it optimises until the constraint is met and then
stops. A WNS of +0.05 ns is evidence that the design **met the clock
it was asked for**, not that it barely scraped past a physical
ceiling. The true maximum clock of either design is unknown and would
need a frequency sweep to find.

What still holds: out-of-context numbers (~148 MHz for the fp256 unit,
+3.3 ns at 100 MHz for the whole kernel) are not promises. They rank
design choices; they do not tell you what will close inside the shell.
Ask for a clock you actually want, and read the routed report rather
than the OOC one.

Determinism is clock-independent; a 90 MHz bitstream proves every
numerical claim a 300 MHz one would. Prefer a working image of the
current design over a faster image of an older one.

**Done when:** `build/cft_hw.xclbin` exists with timing met at the
constrained clock. (v++ fails the link on a timing violation, so a
bitstream existing IS the closure evidence; the routed WNS is in
`build/_x_hw/link/vivado/vpl/prj/prj.runs/impl_1/dr_timing_summary.rpt`.)

## 4. Gate: first light

```bash
python3 host/examples/vector_fma.py build/cft_hw.xclbin \
    --format fp32 --op fma --n 4096
python3 host/examples/vector_fma.py build/cft_hw.xclbin \
    --format fp256 --op fma --n 512
```

or, for one op per precision plus the whole rounding contract:

```bash
CFT_SMOKE_MODE=hw CFT_SMOKE_DEEP=1 bash hw/emu_smoke.sh build/cft_hw.xclbin
```

**Done when:** PASS on all four precisions and all four ops, across
several N and seeds, with the FLAGS register matching the golden OR
each time and STATUS reading zero every time. A non-zero STATUS means
the memory system did not deliver what the kernel computed on, and the
comparison against the golden model is meaningless until it is clean -
check the pointers are in range and 32-byte aligned first.

## 5. Gate: the vectors

Replay `vectors/out/*.jsonl` (gen_vectors.py emits them; a small
replay host is a natural first contribution here) so the card is
scored against the identical artifact any other implementation of the
contract is scored against. Record the run.

## Known open questions to settle on the box

- U50C shell confirmation. No `xilinx_u50c_*` platform exists in AMD's
  published packages (checked 2026-08-28); "U50C"-branded cards run
  standard U50 shells, and the part on this card
  (`xcu50-fsvh2104-2-e`) is standard U50 silicon. `xbmgmt examine`
  is ground truth - confirm the running shell matches the installed
  deployment package generation before the first link.
- Whether `interrupt="false"` polling latency is acceptable for the
  intended run lengths, or the v1 CSR should export the interrupt.
- ~~Behavioural-core synthesis QoR~~ **answered 2026-08-28** with
  `hw/synth_ooc.tcl` on Vivado 2026.1, xcu50-fsvh2104-2-e:

  | instance | LUTs | regs | DSPs | critical path | tolerable clock |
  |---|---|---|---|---|---|
  | fp32 lane (LATENCY=3) | 2,428 (0.28%) | 171 | 2 | ~15.3 ns | ~65 MHz |
  | fp256 unit (LATENCY=3) | 27,774 (3.19%) | 1,291 | 196 (3.3%) | ~68 ns | ~14 MHz |

  Area is a non-issue - the full v0 kernel (8 lanes + 1 wide unit +
  engine) is on the order of 6% of the part. Speed says the bring-up
  clock is set by the fp256 cloud: link the first bitstream at ~12
  MHz (both banks correct, everything provable), and make pipelining
  the wide core the first post-first-light task. Correctness claims
  are clock-independent; only throughput waits on v1.

  Also measured, so nobody retries it: LATENCY=8 plus `synth_design
  -retiming` changes nothing (WNS identical, the extra stages collapse
  into shift registers instead of migrating into the cloud). There is
  no parameter-level shortcut - v1's speed comes from real stage
  boundaries in the RTL (unpack | multiply | align | add | normalize |
  round), behind the same cft_fpfma_pipe ports and testbenches.
