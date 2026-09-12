# Building a bitstream

The commands, and the four ways a build silently produces something
nobody can use. Every failure recorded here cost hours, and three of
them exit zero.

Written 2026-09-12, after an overnight run produced two images at the
wrong clock and a probe script quietly disabled XRT on the build host.

## The commands

On a 2022.2 host (`cft2204` WSL distro, or the amd-arc-box), from the
repo root:

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
