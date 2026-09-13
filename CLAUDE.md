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

## Gates, and which ones mean something

**`make sim` now gates (fixed 2026-09-12).** It runs its twenty-one
benches and then reads the `results.xml` each one wrote, via
`tb/check_results.py`. A recorded failure, a missing results file or an
unparseable one all fail the target and name the bench and the message.
Before this, cocotb's inability to set an exit code — stated in its own
makefile at `Makefile.inc:88`, which checks only that the file *exists* —
meant three real RTL failures were reported as a pass.

Two things were always caught and still are: a compile or elaboration
failure (cocotb deletes the results file before each run, so a bench that
never wrote one trips cocotb's own check) and a hang (the `timeout`
wrappers). The hole was a bench that ran, compared against the golden
model, found a mismatch, and recorded it in XML nothing opened.

The bench list is the variable `SIM_BENCHES` and the files checked are
*derived* from it, so a bench cannot be added to the run and left out of
the check. Override it to gate a subset: `make sim SIM_BENCHES=fp32`.

**`make all XRT=1` now builds `cft-resident` (fixed 2026-09-12).** It
appended to `$(TOOLS)` from below the `all` rule, and make expands a
prerequisite list when it *reads* the rule — so the tool was in `$(TOOLS)`
and absent from `all:`. The repo's idiom is a second `all: <tool>` line,
which make merges; this one tool had skipped it. It also had no clean
rule, so a stale binary could outlive a `clean`.

**`bindings/arduino/sync.py --check` passes.** Measured 2026-09-12: 28
vendored files, all identical to `host/`. This entry previously claimed it
failed on a clean checkout; it does not. Treat a failure from it as a real
divergence.

**The XRT=1 host build is warning-free as of 2026-09-12** — the first time.
`cft-serve.c` was writing a `long` into `char[16]` under
`-Wformat-truncation`; provably unreachable, because the value is a port
validated to five digits, but GCC could not see the bound across two
conditions. Treat any warning there as new.

**`make fp32 SIM=verilator` elaborates again (fixed 2026-09-12).** fp32 is
the one format whose mantissa fits a single multiplier pass, so its pass
counter compares against zero and Verilator called it constant — fatal,
since warnings are fatal in this suite by design. Scoped `lint_off
UNSIGNED` on the two lines, with the argument beside them.

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
