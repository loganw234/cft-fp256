# Building a bitstream

The commands, and the four ways a build silently produces something
nobody can use. Every failure recorded here cost hours, and three of
them exit zero.

Written 2026-09-12, after an overnight run produced two images at the
wrong clock and a probe script quietly disabled XRT on the build host.

## Which host, and why it is not a coin flip

**Default to `amd-arc-box`:** `ssh logan@192.168.0.201` (key auth), 36
threads, 46 GB, Vitis at `/data/Xilinx`, and **the U50 is in this box**
(`02:00.0 Alveo U50 XMDA Platform`) — so an image can be tested where it
was built instead of moved. `docs/BRINGUP.md` already names it for
`-t hw` links.

**`cft2204` is a WSL distro on the Windows desktop, not a separate
machine.** 12 threads and 47 GB, shared with everything running on
Windows, Vitis at `/opt/Xilinx`, no card. It links correctly — it
produced working images on 2026-09-11 — but it is the fallback, not the
default.

The distinction is written down because collapsing it is not a
hypothetical: "the Linux box" was read as cft2204 on 2026-09-12 and a
five-hour build went to the host with a third of the cores and no card
to verify against. `hw/rebuild-2022.sh` searches both Vitis roots, so
the host choice is yours to make and nothing will correct it for you.

Nothing FPGA runs on Windows itself — `xclbinutil` is Linux-only.

## The script, which is the short answer

```bash
setsid nohup hw/build-pair.sh --tag rev4 \
    --commit <sha> --require <token> --require-in rtl/cft_krnl.sv:<token> \
    > ~/build-rev4.out 2>&1 &
```

`hw/build-pair.sh` is this document as an executable. It sets the clock,
retiming and phys_opt rather than inheriting the defaults; **refuses a
clock below 100 MHz** instead of quietly building the one that meets
timing trivially; asserts the commit *and* greps the sources for content
only the intended commit has; builds single before quad and skips the quad
entirely if the single did not verify; runs `hw/verify-image.sh` before
anything is staged; re-hashes each staged copy against its manifest; and
writes `SHA256SUMS` and a README naming the lineage. `--dry-run` runs every
assertion and builds nothing, which is how the refusals are tested.

It exists because this recipe was rebuilt from memory several times and
memory got it wrong in ways that exit 0 — once costing five hours on a
10 MHz image.

## The commands it runs, which are the explanation

From the repo root, on whichever host you chose:

```bash
# 1. the tree, asserted - not assumed
git remote set-url origin https://github.com/loganw234/cft-fp256.git
git fetch --quiet origin main
git checkout --quiet --detach <sha>
[ "$(git rev-parse HEAD)" = "<sha>" ] || { echo "FATAL"; exit 1; }

# 2. the host library and tools, WITH XRT
make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all

# 3. the bitstream, AT THE CLOCK YOU MEAN
KERNEL_FREQ=135000000 BUILD=build-<name> TARGETS=hw \
    LINK_CFG=hw/link.cfg bash hw/rebuild-2022.sh        # one tile
KERNEL_FREQ=135000000 BUILD=build-<name>q TARGETS=hw \
    LINK_CFG=hw/link_quad.cfg bash hw/rebuild-2022.sh   # four
```

`BUILD` differs per link because `rebuild-2022.sh` parameterises it for
exactly that reason: two links sharing a directory overwrite each
other's `.xo`, temp dir and xclbin.

## The four traps

### 1. KERNEL_FREQ defaults to 10 MHz

`hw/rebuild-2022.sh` line 17: `KERNEL_FREQ=${KERNEL_FREQ:-10000000}`,
commented "v0 behavioural core". That value is from the first bring-up,
before any higher clock had been shown to work. **It is dead history in
a default, not a safe starting point.** Every card-day image is 135 MHz
(docs/CARDDAY.md).

A build at 10 MHz succeeds, meets timing trivially, and produces an
image roughly thirteen times slower than the shipped pair. It cannot be
staged and cannot be compared against anything.

**The tell is an absurd kernel WNS.** At 135 MHz expect a fraction of a
nanosecond - the quad's 2026-09-02 record is `+0.143`. A run reporting
`kernel_wns_ns: 83.892` is not a triumph; it is a design that was asked
for nothing. Check the clock that was actually applied:

```bash
grep -m1 "Clock constraint argument" <log>   # want 135000000:...
```

### 2. XRT is off by default in the host build

`host/Makefile`: `XRT ?= 0`, and `-DCFT_ENABLE_XRT` is added only under
`XRT=1`. Without it `src/backend_xrt.cpp` **still compiles** to an
object and lands in `libcft.a`, so nothing about the build looks wrong -
but the backend is inert, and `cft_open()` of an xclbin PATH answers
`CFT_ERR_NO_DEVICE`:

```
device /path/to/cft_hw_emu.xclbin: no such device
```

Every image on the box fails that way at once, old and new alike, which
makes it read as a broken emulation environment rather than a broken
binary. It is the binary.

```bash
ldd host/device-test | grep xrt     # want libxrt_coreutil.so
```

Never run a bare `make -C host <target>` on a host that opens
artifacts. It will replace a working library with an XRT-less one.

### 3. `make -C host clean` removes every tool

Not just the one you are about to rebuild. `cft-asm`, `positive-run`,
`cft-selftest`, `cft-serve`, `cft-collatz`, `cft-orbits`, `cft-zoom`,
`api-test`, `reduce-parts` - all of them. If you clean, rebuild with
`all` and the extra targets, not with the single one you wanted.

### 4. One heavy link at a time

A quad `place_design` wants 25-30 GB. `cft2204` has ~47 GB. Two links
in parallel is an OOM kill, and an OOM kill reads in the log like a
design failure - which is the expensive way to find out. Order the legs
cheapest-first so a flow mistake surfaces in minutes:

    hw_emu single  ~4 min
    hw single      ~105 min
    hw quad        ~175 min

`hw_emu` takes no clock constraint at all (`rebuild-2022.sh` adds
`--clock.freqHz` only for `hw`), so an emulation image does not need
rebuilding when the clock changes.

## What to check before believing a build

| check | command | want |
|---|---|---|
| the tree | `git rev-parse HEAD` | the SHA you meant |
| the feature is in the RTL | `grep scr_strict_q rtl/cft_seq.sv` | present |
| the clock applied | `grep "Clock constraint argument" <log>` | `135000000:` |
| the margin is real | `grep kernel_wns_ns <log>` | small and positive |
| errors | `grep -cE "^ERROR" <log>` | 0 |
| the image exists | `ls -l <build>/*.xclbin` | tens of MB |

A SHA that matches on a clone that never fetched is the failure
`rev-parse` cannot see, which is why the feature grep is a separate row:
assert the CONTENT, not only the pointer.

## Verifying a capability actually shipped

`rc=0` says v++ was happy, not that the bit is in the image. For a
capability bit (`CAPS2`), read it back:

```bash
bash hw/run-device-test.sh <build>/cft_hw_emu.xclbin -n 8 -f fp32
```

`device-test` reads `CAPS2` over AXI and checks both directions - a
published feature must load its image, an absent one must be refused
*by name*. On the software backend only the positive branch can ever
fire, because `cft_sw_seq_caps` carries every feature the contract
defines; a device image is the first thing that can exercise the other
half.
