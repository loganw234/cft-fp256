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
| amd-arc-box | Xeon E5-2697 v4 36t, 32 GB, 238 GB NVMe (167 free), RX 7600 + Arc B580 + Arc A750, Ubuntu 24.04 | **build box** (Vitis + v++); card host IF its X99-UD4 BIOS exposes Above 4G Decoding (common on X99 - check; /proc/iomem shows none mapped today) |
| nvidia-box | i5-6600K 4t, 8 GB, 117 GB SSD, GTX 1080, mini-ITX, Ubuntu 24.04 | too small for v++ links (8 GB); last-resort card host - single slot means pulling the 1080, which breaks an atlas census column |
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

### hw_emu: it was stale simulator state, and the fix is in the runner

**Resolved 2026-08-30.** The investigation below is kept because the
narrowing is what made the answer findable, and because the failure
mode recurs.

An interrupted emulation leaves its `xsimk` alive holding a socket
under `/tmp/$USER` and a directory under `.run`. Every later run then
talks to the wreckage of the earlier one and hangs at startup or after
its first kernel launch - which looks exactly like a design bug, and
cost this project an evening once before under the name "flakiness".
`hw/run-device-test.sh` now reaps them before every run, and with that
in place emulation completes:

> **The first version of that reap was incomplete, and it bit again on
> 2026-08-30.** The shim creates TWO sockets per run -
> `device0_0_<pid>` and `D2X_unix_sock_device0_0_<pid>` - and the
> reaper globbed `device*`, which matches only the first. Half the
> litter was swept and half accumulated: 26 sockets built up over about
> eighteen hours, and then runs began dying at startup with a protobuf
> parse failure on `xclCopyBufferHost2Device_response` followed by
> `SIMULATION EXITED`.
>
> That signature reads like a corrupt artifact or a version-skewed
> toolchain, which is where four runs and most of a three-way bisection
> went before anyone listed the directory. The reaper now clears the
> whole of `/tmp/$USER`, because a pattern that has to be kept in step
> with a vendor's socket naming will drift out of step silently and
> present as something expensive.
>
> A related harness flaw made it worse and is also fixed: `.run`
> directories were deleted at the START of a run, so every failure
> destroyed the previous failure's simulator log. Four failed runs, four
> erased post-mortems, and the one piece of evidence that would have
> named the cause was gone each time it was wanted.

    opened exclusive
    MAGIC 0x43465430  VERSION 0x00000410  CAPS 0x00001f0f
    wait returned state 4        <- ERT_CMD_STATE_COMPLETED
    FLAGS 0x0  STATUS 0x0        PROBE OK

and the engine's own trace confirms it, on all four tiles of the quad
image at once:

    [CFT-ENGS] DONE beats=1 flags=10100 err=000
    [CFT-ENGS] DONE beats=1 flags=10000 err=000
    [CFT-ENGS] DONE beats=1 flags=10100 err=000
    [CFT-ENGS] DONE beats=1 flags=10100 err=000

Four compute units, each on its own HBM group, each finishing with no
bus errors. **So the multi-tile host path is validated in emulation
with no card present**, which is what it was built for.

Two things made the diagnosis slower than it needed to be. The `DONE`
line did not exist, so a run that finished and a run that stalled
looked identical in the trace - it exists now. And the first two
hypotheses were both wrong (the higher HBM groups; exclusive CU
access), which is why the table below is worth keeping: it is the list
of things that are *not* the cause.

### The narrowing, kept for the next time

Recorded because a later reader will otherwise repeat the evening.

The multi-tile host path was built and taken as far as emulation
allows. Against the quad hw_emu image it **opens the device,
enumerates four compute units, reads MAGIC / VERSION / CAPS from the
card's own registers, and partitions the work correctly** - the
engine's own trace shows four runs of 8 elements each, at four
different HBM base addresses (`0x0`, `0x8000_0000`, `0xc000_0000`,
...), which is exactly the per-CU memory-group discipline
`hw/link_quad.cfg` requires. Each run reads its three operand streams,
computes, and issues its write.

What did not happen was completion: `xrt::run::wait` never returned.
Narrowed as far as it is worth narrowing:

| varied | result |
|---|---|
| 4 compute units vs 1 | same |
| exclusive vs shared CU access | same |
| libcft vs a 40-line XRT program using neither | same |

So it was neither a libcft defect nor a multi-tile one - a minimal XRT
program reproduced it. The observation that turned out to be the whole
answer was the one that looked incidental at the time: the emulation
environment is fragile in its own right, an interrupted run leaves an
orphan `xsimk` holding a socket, and on one attempt the simulator
kernel did not start at all while the host process spun at 99% CPU.

Two lessons rather than one. Ruling things out was necessary and not
sufficient - the cause was never in the list of things being varied,
so varying them harder would never have found it. And the instrument
that settled it (`[CFT-ENGS] DONE`) had to be built before the
question could be asked at all, which is worth doing earlier next
time.
That is the first thing to look at when this is picked up again.

None of it affects the hardware images. `-t hw` builds are unaffected,
the RTL is bit-exact in cocotb against a compliant AXI model, and
docs/CARDDAY.md step 3 is the same comparison against real silicon.

**The two homes are NOT interchangeable for hw_emu (2026-08-29).**
`-t hw` works on both. `-t hw_emu` works only on the 22.04 one, and
the reason is worth knowing because it will recur with every host OS
upgrade.

Emulation links a `libdpi.so` at elaboration time using the linker
Vivado ships - **binutils 2.37**, which predates the `SHT_RELR` (0x13)
relocation section type. Ubuntu 24.04's glibc uses it, so on
amd-arc-box that linker cannot read the system libm at all:

    ld: /lib/x86_64-linux-gnu/libm.so.6: unknown type [0x13] section `.relr.dyn'
    ld: skipping incompatible /lib/x86_64-linux-gnu/libm.so.6
    ERROR: [XSIM 43-4452] Linking failed for "libdpi.so"

Nothing about the design is involved and no flag fixes it: a 2022 tool
cannot link a 2024 libc. `readelf -S /lib/x86_64-linux-gnu/libm.so.6 |
grep relr` is the one-line test - a hit means that host cannot run
hw_emu under 2022.2. amd-arc-box (glibc 2.39) hits; cft2204 (glibc
2.35) does not.

So the split is:

| job | where | why |
|---|---|---|
| `-t hw` links, timing, bitstreams | amd-arc-box | 36 threads, 46 GB - a link is ~1h50m and ~12 GB |
| `-t hw_emu` and anything that runs under emulation | cft2204 (WSL, Ubuntu 22.04) | its glibc is old enough for Vivado's bundled linker |
| kernel packaging, OOC QoR | Windows / Vivado 2026.1 | no encrypted shell IP in the picture |

`hw/run-device-test.sh` sets the emulation environment (it needs the
full Vitis environment, not just XRT, plus `EMCONFIG_PATH`) so this
does not have to be remembered.

**The era-build environments (2026-08-29).** Two Vitis 2022.2 homes,
both driven by `hw/rebuild-2022.sh` from the repo root, and both now
real git checkouts rather than file copies - `hw/sync-worktree.sh`
puts an exact commit on either one, so the build manifests can name
the commit an artifact came from instead of recording "unknown":

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

## 2. Gate: hardware emulation - **MET on v1 (2026-08-29); MET on the sequencer tile at fp32 (2026-09-02); fp64 and wider programs not yet through**

**2026-09-02.** The gate that condemned the sequencer that morning
passed it that night: at 8f5f149 every program failed with a bus
fault (16 checks, 4 failed - all three operand reads left through
`m_axi_a`, which `link.cfg` binds to one HBM pseudo-channel); at
40149b1, with `cft_seq` naming the buffer each read belongs to and
`cft_krnl` steering it at the master that owns that bank, the same
image pipeline returned **28 checks, 0 failed** through real XRT. fp32
completed its whole program set; the 90-minute emulation cap stopped
the run in fp64, so the wider rungs are not yet through on a device.
Emulation is not silicon.

**Where this stands on the sequencer tile (2026-09-01, evening).** A
fresh `hw_emu` image was built from the shared-lanes commit and it **is
executing the design**: a reduction ran to completion through the real
XRT stack with the correct flags. That is the shared `cft_lanes` array,
the sequencer's control diet and the registered reduce operands running
against Xilinx's models rather than cocotb's, and it is real evidence.

It is not the gate. Two of the run's stages never started at all, with
two signatures this file already knows:

    [libprotobuf ERROR] Can't parse message of type
    "xclCopyBufferHost2Device_response"
    Failed to connect to device process

Both are the stale-emulation-state startup race documented at length in
`hw/run-device-test.sh`'s own header - not a design fault, and a
failure mode that header records having twice been diagnosed as
something more expensive. Those stages are being re-run with settling
delays. Until they pass, what has been shown is that the image builds
and the design runs - **not** that it is correct through the stack; and
no sequencer PROGRAM has been through emulation at all, on any image.

**Done when:** every stage of `hw/run-device-test.sh` completes against
a hw_emu image built from the commit under test, bit-exact against the
golden model, FLAGS matching and STATUS zero each time - and, for the
sequencer, with at least one program run scored against `seq.py`. A
stage that did not start is not a stage that passed, which is the whole
reason the startup race gets a paragraph rather than a footnote.

The v1 record below is unchanged and stands for the design it was taken
on.

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

**Field note: clear the emulator scratch, or runs start failing.**
A case that prints no verdict line at all is an infrastructure fault,
not a result - a *numerical* failure always prints MISMATCH/FAIL.
Run one unfiltered and the cause is visible:

```
[libprotobuf ERROR message_lite.cc:133] Can't parse message of type
"xclCopyBufferHost2Device_response" because it is missing required
fields: size
SIMULATION EXITED
```

The XRT-to-simulator transport truncates a message on the
host-to-device buffer copy, before the kernel runs at all. Root cause
found 2026-08-29: **`/usr/bin/.run/<pid>` scratch directories and
`/tmp/root` sockets accumulate, one pair per emulation run, and the
failure rate climbs with them.** At 53 stale directories one case had
failed four times running; after

```bash
rm -rf /usr/bin/.run/* /tmp/root/*      # no xsim processes running
```

the same case passed three times out of three. Disk and memory were
never the constraint (833 GB free, no leaked processes) - it is the
accumulated state itself. Clear it between sessions. This was written
off as random flakiness for most of a day before anyone ran the case
without a grep filter in the way, which is its own lesson.

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

## 3. Gate: link for hardware - **MET 2026-08-29 on the pre-sequencer design; the sequencer tile's single closes at 135 MHz (2026-09-02), its quad has not**

**2026-09-02.** The shared-array sequencer tile links as a single at
135 MHz with +0.045 of slack (with retiming and without; +0.050 at
130) and as a quad it has missed 135 twice, -0.113 and -0.141, with
no image either time. The quad's worst paths are three named
families (docs/ROADMAP.md); the tree that removes the largest and
shortens the next is building as a quad at 135 on two hosts with 130
queued behind. The bitstreams below are unchanged by any of this.

```bash
TARGETS=hw KERNEL_FREQ=100000000 bash hw/rebuild-2022.sh
```

Bitstreams banked on amd-arc-box, oldest first. The first six are
history - kept because they are the timing evidence behind the clock
choice, not because any of them would go on a card:

| file | design | kernel clock |
|---|---|---|
| `cft_hw_v0_10mhz.xclbin` | v0 behavioural core, naive engine | 10 MHz |
| `cft_hw_v1_2bank_100mhz.xclbin` | v1 pipelined core, fp32+fp256 banks | 100 MHz |
| `cft_hw_v1_4rung_90mhz_prereview.xclbin` | four rungs, streaming engine, rounding attributes | 90 MHz |
| `cft_hw.xclbin` | the same, plus the control-review fixes (STATUS, latched run config) | 90 MHz |
| `sweep/f115/cft_hw.xclbin` | four rungs, from the sweep | 115 MHz |
| `sweep/f145/cft_hw.xclbin` | four rungs, from the sweep | 145 MHz |

And the four card-day candidates, built on the round-stage RTL after
the sweep bitstreams aged out from under it:

| file | design | kernel clock | kernel WNS |
|---|---|---|---|
| **`~/cardday-130/cft_hw_single.xclbin`** | **one tile - card-day set** | **130 MHz** | **+0.137 ns** |
| **`~/cardday-130/cft_hw_quad.xclbin`** | **four tiles - card-day set** | **130 MHz** | **+0.022 ns** |
| `cardday/single145/cft_hw.xclbin` | one tile | 145 MHz | +0.116 ns |
| `~/cft-exp/cardday/quad145/cft_hw.xclbin` | four tiles | 145 MHz | +0.028 ns |

**Card-day clock: 130 MHz** (decided 2026-08-30). Both pairs were
built, so this was a choice between finished artifacts rather than a
prediction:

| set | tile | commit | kernel WNS | HBM | build |
|---|---|---|---|---|---|
| **130** | `cardday/single` | 53bbba7 | +0.137 ns | 450.0 | 1h46m |
| **130** | `cardday/quad` | 53bbba7 | +0.022 ns | 449.8 (1 endpoint, -0.001 ns) | 1h46m |
| 145 | `cardday/single145` | eb8a97a | +0.116 ns | 450.0 | ~1h50m |
| 145 | `cardday/quad145` | 5cc559a | +0.028 ns | 450.0 | 3h56m |

130 wins on the two things that were being optimised for. Build cost:
3h56m for the 145 quad against 1h46m, because Vivado works a path
exactly as hard as the constraint demands and then stops - the
difference is entirely the ask, not the design. And provenance: the
130 pair is one commit and one directory, both trees clean, while the
145 pair spans two commits in two directories and its quad manifest
needed a hand annotation to explain a `tree: DIRTY` flag that was
about host-side files.

**One fact points the other way, and it is recorded rather than
buried.** The 130 quad is the only one of the four with a violating
clock: `hbm_aclk` misses by 0.001 ns on 1 endpoint of 39,282, and
Vivado auto-scales HBM from 450.0 to 449.8 MHz - a 0.04% adjustment on
a shell clock. The 145 quad closes HBM clean at 450.0. This does not
touch the kernel clock and cannot affect a result: correctness in this
design is clock-independent by construction, which is the same
property that let the first bitstream be linked at 12 MHz. It is a
throughput footnote, not a determinism one. If the card ever shows
memory trouble, `cardday/quad145` is the built, closed alternative to
try before anything is rebuilt.

The sweep bitstreams predate the non-arithmetic opcodes and are timing
evidence, not deliverables. For the measured ceiling itself see the
frequency table below: 145 closes and 175 misses by 0.562 ns, so
either choice sits well inside the envelope.

Build cost on amd-arc-box, measured on the four-rung design: synthesis
18m, logic opt 3m, placement 44m, routing 18m, bitstream 25m - 1h47m
end to end, or ~1h25m if a run only needs the timing report and stops
after routing. One link peaks at ~12 GB, so the 31 GB box runs two
concurrently; that is the binding constraint on any frequency sweep,
not the 36 cores.

### The sequencer tile: one miss, and a pending pair (2026-09-01)

Every bitstream above predates the orbit sequencer. The sequencer-era
tile has not closed one, and the attempt that has finished is a failure
worth the space.

**The 135 MHz single with the fused ladders on missed timing: WNS
-0.577 ns, 776 failing endpoints.** The worst path was not the ladder
the build existed to test:

    u_engine/u_reduce/dly_lvl_reg[14][0]
      -> u_lanes/g_lane32[0].u_fma/s0_byp_d_reg[15]
    25 levels, through a DSP cascade

That is the shared-array refactor's own regression, and the build is
what found it. While the reduction accumulator fed lane 0 of the
engine's PRIVATE array its operands went straight to the pipe's `a`/`c`
ports; putting both engines on one operand bus put the accumulator's
combinational output onto the bus that also feeds `cft_simpleops`,
whose result `cft_fpfma_pipe` latches unconditionally. Fixed at 8f5f149
by registering the accumulator's operands and raising
`cft_reduce_acc`'s `ADD_LATENCY` to `LATENCY + 1` - not a numeric
change, since the tree shape and the order of every add are fixed by
element index. docs/ROADMAP.md carries the full accounting.

**Building now, outcome unknown:** a single and a quad, 135 MHz, from
the fixed commit, with `FUSE_NORM`/`FUSE_ALIGN` off. Nothing about them
may be reported as closed until a manifest says so, and no result of
theirs is in this file yet.

Note the clock: 135, not the 130 chosen above. That choice was made
between finished artifacts of the **pre-sequencer** design, and 135 is
the frequency every out-of-context measurement of the sequencer tile
has been taken at. Different designs, and the choice has not been
re-made on this one.

### Which RTL is in this bitstream?

Hash the file and read the manifest beside it:

```bash
sha256sum build/cft_hw.xclbin
cat build/cft_hw.manifest.txt
```

`hw/rebuild-2022.sh` writes one manifest per artifact carrying the
commit, `git describe`, whether the tree was dirty, the platform,
part, link config, kernel clock, Vivado version and the routed WNS.

The hash is the key rather than the filename, because filenames get
copied and renamed and the tag does not stay put. **`cardday-base` is
a moving marker**: it names the last state that passed everything, and
it advances as the week does, because most of this design is
verifiable without the card and there is no reason to sit on a stale
point. That makes the tag useless for provenance by design, which is
exactly why the manifest exists.

A bitstream built from a dirty tree says so, in those words. It should
never reach the card; if it does, its results correspond to no commit
and cannot be reproduced.

### Calibration: read the path delay, not the slack

This note has been rewritten twice as data arrived, and the final
version is the useful one. Six routed builds of the same design
family:

| design | target | routed WNS | implied path delay |
|---|---|---|---|
| v1 core, two banks | 100 MHz | +0.051 ns | 9.949 ns |
| four rungs + streaming | 90 MHz | +0.055 ns | 11.056 ns |
| the same + review fixes | 90 MHz | +0.055 ns | 11.056 ns |
| four rungs | 115 MHz | +0.036 ns | 8.660 ns |
| four rungs | 145 MHz | +0.055 ns | 6.842 ns |
| four rungs | **175 MHz** | **-0.562 ns** | 6.276 ns |

**The path delay shrinks as the constraint tightens** - 11.06, 8.66,
6.84, 6.28 ns for the same RTL. That is what constraint-driven
implementation looks like measured rather than asserted: the tool
works the critical path exactly as hard as it must and then stops. It
also explains why every closing build lands ~50 ps above zero, which
was first misread here as the shell eating all the margin.

So a routed WNS tells you the design met what it was asked for and
almost nothing about headroom. **The number that predicts the ceiling
is the path delay**, and at maximum effort it asymptotes: 6.276 ns
at 175 MHz implies a real ceiling near **159 MHz** for this design.
Verified from both sides - 145 MHz closes, 175 MHz misses by 0.562 ns.

The out-of-context probe was right about both things that matter, and
was only misleading in the one number this note originally quoted:

- it named the critical path exactly - `s10_mag` -> `s11_valw` in the
  fp256 unit, the leading-zero-count and coarse-normalize stage - and
  the 175 MHz failure is that same path, register for register;
- its **path delay** of 6.666 ns implied ~150 MHz against a measured
  ~159 MHz, accurate to about 6%;
- its **slack** at a loose constraint (+3.3 ns at 100 MHz) meant
  nothing at all, for exactly the reason above.

Read the OOC path delay. Ignore the OOC slack.

**And do not read either as shell timing (2026-09-01).** Everything
above compares one module measured two ways; a shell build asks a
different question. Out of context the kernel is placed alone, and in
the shell it is one compute unit among the platform's own logic, so a
path that crosses module boundaries can be routed very differently. The
sequencer tile read **+0.307 ns OOC with the ladders off and +0.097
with them on**; the ladders-on link came back at **-0.577 ns** - a
swing larger than either OOC margin, on a path OOC had not named in
either configuration. An OOC number is a screen, useful for deciding
what is worth linking. It is never the report of what closed.

Determinism is clock-independent; a 90 MHz bitstream proves every
numerical claim a 300 MHz one would. Prefer a working image of the
current design over a faster image of an older one.

**Done when:** `build/cft_hw.xclbin` exists with timing met at the
constrained clock, **for the design being taken to the card** - this
gate is earned per design, not once and for all, which is why the
sequencer tile has to earn it again. (v++ fails the link on a timing
violation, so a bitstream existing IS the closure evidence; the routed
WNS is in
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
