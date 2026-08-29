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

## 2. Gate: hardware emulation

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

## 3. Gate: link for hardware

```bash
make xclbin TARGET=hw
```

The behavioural core will not close timing at the platform default
clock - that is expected, not a surprise (docs/ARCHITECTURE.md,
"Timing expectation"). Constrain the kernel clock down first, e.g.:

```
# added to hw/link.cfg when needed
[clock]
freqHz=100000000:cft_krnl_1
```

Determinism is clock-independent; a 100 MHz bring-up bitstream proves
every numerical claim a 300 MHz one would.

**Done when:** `build/cft_hw.xclbin` exists with timing met at the
constrained clock.

## 4. Gate: first light

```bash
python3 host/examples/vector_fma.py build/cft_hw.xclbin \
    --format fp32 --op fma --n 4096
python3 host/examples/vector_fma.py build/cft_hw.xclbin \
    --format fp256 --op fma --n 512
```

**Done when:** PASS on both precisions and all four ops, across
several N and seeds, and the FLAGS register matches the golden OR
each time.

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
