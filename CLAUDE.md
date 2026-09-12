# Working on cft-fp256

Short, and only things that are non-obvious AND have already cost hours.
The README says what this project is; this says what will bite you.

## The machines, and the one that gets confused

You are working from **a Windows desktop**. There are two Linux
environments and they are **not the same machine**:

| name | what it is | how | threads / RAM | card? |
|---|---|---|---|---|
| `cft2204` | a **WSL distro on this same Windows desktop** | `wsl -d cft2204` | 12 / 47 GB, **shared with Windows** | no |
| `amd-arc-box` | a **separate physical Linux machine** | `ssh logan@192.168.0.201` (key auth) | 36 / 46 GB | **yes — U50 at `02:00.0`** |

**"The Linux box" always means `amd-arc-box`.** WSL is the Windows
machine wearing a Linux layer; calling it "the Linux box" is how a
five-hour bitstream gets built on the wrong host with a third of the
cores and no card to test it on. That happened on 2026-09-12.

Vitis 2022.2 lives at `/data/Xilinx` on amd-arc-box and `/opt/Xilinx` on
cft2204; `hw/rebuild-2022.sh` searches both, so it needs no edit either
way. `-t hw` links and anything touching the card belong on
amd-arc-box — `docs/BRINGUP.md` names it for exactly that.

Nothing FPGA can run on Windows itself: `xclbinutil` is Linux-only.

## Bitstream builds: four traps, three of which exit 0

Full procedure in **`docs/BITSTREAM-BUILDS.md`**. The short version:

1. **`KERNEL_FREQ=135000000`, always.** `hw/rebuild-2022.sh` defaults to
   `10000000` — a value from first bring-up, before any higher clock had
   been shown to work. A run on that default produces images that meet
   timing trivially and cannot be staged. **The tell is an absurd kernel
   WNS**: +84 ns against a 100 ns period is a design being asked for
   nothing; 135 MHz wants a fraction of a nanosecond.
2. **`make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt`** on any box that
   will open an artifact. `XRT ?= 0`, and `backend_xrt.cpp` still
   *compiles* without it — so the build looks clean and `cft_open()` of
   an xclbin answers `CFT_ERR_NO_DEVICE`, printed as `no such device`.
   Every image on the box fails at once, old ones included, which reads
   as a broken emulation environment rather than a broken binary. Check
   `ldd host/device-test | grep xrt` before believing any card or
   hw_emu result.
3. **`make -C host clean` removes every tool in `host/`**, not the one
   you are rebuilding. Rebuild what you need, or `make -C host all
   XRT=1`.
4. **One heavy link at a time.** A quad `place_design` wants 25–30 GB,
   and an OOM kill reads like a design failure.

## Gates that cannot fail (known, unfixed)

- **`make sim` exits 0 even when cocotb reports failures.** `results.xml`
  records them and nothing reads it. Read `TESTS=`/`FAIL=` out of the
  log; never trust the exit code. Three real RTL failures were reported
  as a pass this way.
- **`bindings/arduino/sync.py --check` fails on a clean checkout** —
  vendored files differ at HEAD, so `make embedded` is red independently
  of whatever you changed.

## Before believing a remote build

Assert the **SHA and the content separately**. A clone reporting the
right SHA whose working tree never updated is the failure `rev-parse`
cannot see, so also grep the sources for something only the new commit
has. Both build hosts produced stale bundles in one day once.

When comparing trees across Windows and Linux, compare **git tree
hashes** (`git rev-parse HEAD:rtl`), not `sha256sum` output — MSYS
prints `hash *file` and Linux prints `hash  file`, so the digests differ
on formatting alone and look like a mismatch.

## The discipline that matters most here

`python/cft_golden` **is the authority**. The golden model, libcft, the
simulator and the card must agree bit for bit, and anything the hardware
cannot do is refused **by name** rather than approximated. A refusal
that says `CFT_ERR_ARTIFACT` where it means "this tile is too old" is a
defect, not a detail.

Simulate with **`SIM=verilator`** while iterating — measured 9.7x faster
than Icarus on the sequencer suites (90 s against 879 s) — then confirm
with Icarus, which is the project default and therefore what `make sim`
means.
