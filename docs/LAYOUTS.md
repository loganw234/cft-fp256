# Layouts

Every xclbin the U50 could carry, as a catalogue - derived, not typed.
`hw/gen_layouts.py` holds the measured costs and the rules, computes
how many tiles of each kind fit, and writes one link config per layout
to `hw/layouts/`. Edit the script, never the configs;
`python hw/gen_layouts.py --check` says whether they are stale.

## What a layout is, and when it is decided

A layout is a tile mix - how many compute units of which kernel variant
- plus the clock each variant closes at. **It is fixed when `v++`
links.** The mix, each tile's rungs and each CU's clock are the placed
and routed netlist; there is no runtime switch that changes what logic
exists or what frequency a region closed at. A different mix is a
different xclbin: hours to build.

Switching between *pre-built* layouts is seconds. The U50 shell is a
partial-reconfiguration design - every timing report names
`pblock_dynamic_region` - and an xclbin IS the partial bitstream for
that region. Loading one leaves the shell, the PCIe link and the HBM
controllers in place. The host opens a specific artifact
(`cftx_open(artifact, ...)`), so the practical shape is a library of
layouts chosen per workload, swapped by closing one and opening
another.

What stays a runtime choice, within whatever layout is loaded: the
precision, opcode and rounding attribute of every run, the sequencer
program, which tiles receive work, the vector sizes. A full tile runs
any rung; a narrow tile refuses what it lacks (`prec_ok`) and says so
in CAPS[3:0].

## The variants

One RTL, three generics (`rtl/cft_krnl.sv`: `EN_FP64`, `EN_FP128`,
`EN_FP256`). A narrow variant does not build the banks it drops; the
engine, sequencer, FIFOs, reduction accumulator and CSR are
`BEAT_BITS`-wide and stay.

| kernel | rungs | generics off | clock (MHz) | provenance |
|---|---|---|---|---|
| `cft_krnl` | fp32 fp64 fp128 fp256 | - | 135 | measured: single closes +0.045 retimed; quad pending |
| `cft_krnl_f128` | fp32 fp64 fp128 | `EN_FP256=0` | 150* | target, unmeasured |
| `cft_krnl_f64` | fp32 fp64 | `EN_FP128=0 EN_FP256=0` | 170* | target, unmeasured |
| `cft_krnl_f32` | fp32 | `EN_FP64=0 EN_FP128=0 EN_FP256=0` | 190* | target, unmeasured |

`*` targets, not results: the OOC ceilings in docs/ARCHITECTURE.md
(232 MHz at fp32, 148 at fp256, the middle rungs between) less the
~0.9 ns the shell has cost in practice. The widest rung a tile carries
sets its clock, which is the whole reason narrow tiles exist. The
platform has **two kernel clocks**, so a layout carries at most two
distinct frequencies; a build closes at the frequency it asked for and
XRT programs that at load - a layout can be run slower than it closed,
never legitimately faster.

## The catalogue

The default is the homogeneous quad. Then one fp256 anchor with the
rest of the ladder filled to the budget at each lower rung; then the
same pattern one rung down; then the homogeneous narrow layouts that
complete it. Counts are the largest that keep the model under 80% of
the device (the routed quad closes at 80.6%) and inside the HBM wall.

**fp256 contract compliant** marks the layouts on which the binary256
conformance vectors replay - at least one tile carries the fp256 rung.
Every layout honours the contract for the rungs it carries, bit-exact
and deterministic, and CAPS tells a host which those are; the mark is
about *capability*, and it is what docs/SCALING.md's settled
homogeneous-tile decision ("every tile can do fp256, so precision is a
runtime choice rather than a deployment one") guarantees for the first
two rows and gives up, deliberately, on the rest.

| layout | tiles | CUs | HBM PCs | clocks (MHz) | model LUT | of device | fit | fp256 contract | status |
|---|---|---|---|---|---|---|---|---|---|
| `u50-4xfp256` | 4x fp256 (full) | 4 | 16 | 135 | 680,607 | 78.2% | fits | **✓** | built |
| `u50-1xfp256` | 1x fp256 (full) | 1 | 4 | 135 | 253,605 | 29.1% | fits | **✓** | built |
| `u50-1xfp256-3xfp128` | 1x fp256 (full) + 3x fp128-max | 4 | 16 | 135 / 150* | 587,289 | 67.4% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp256-4xfp64` | 1x fp256 (full) + 4x fp64-max | 5 | 20 | 135 / 170* | 610,957 | 70.2% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp256-6xfp32` | 1x fp256 (full) + 6x fp32-max | 7 | 28 | 135 / 190* | 684,633 | 78.6% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp128-5xfp64` | 1x fp128-max + 5x fp64-max | 6 | 24 | 150* / 170* | 669,189 | 76.9% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp128-6xfp32` | 1x fp128-max + 6x fp32-max | 7 | 28 | 150* / 190* | 653,527 | 75.1% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp64-6xfp32` | 1x fp64-max + 6x fp32-max | 7 | 28 | 170* / 190* | 631,637 | 72.5% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-5xfp128` | 5x fp128-max | 5 | 20 | 150* | 667,411 | 76.7% | fits |  | placeholder (needs variant packaging; host-ready) |
| `u50-6xfp64` | 6x fp64-max | 6 | 24 | 170* | 647,299 | 74.3% | fits |  | placeholder (needs variant packaging; host-ready) |
| `u50-8xfp32` | 8x fp32-max | 8 | 32 | 190* | 685,975 | 78.8% | fits |  | placeholder (needs variant packaging; host-ready) |

*(generated by `python hw/gen_layouts.py` on 2026-09-02; the two
"built" rows are `hw/link_quad.cfg` and `hw/link.cfg` by another name -
identical connectivity.)*

Two rows sit within one tile of the budget and will move when the bank
costs below are replaced by measured ones: `u50-1xfp256-3xfp128` (a
fourth fp128 tile lands at 80.2%) and `u50-1xfp256-6xfp32` (a seventh
would be the eighth CU, at the HBM wall).

## Costs, and where they come from

| quantity | value | provenance |
|---|---|---|
| device LUTs | 870,720 | the "Available" column of the routed quad's `full_util_placed.rpt` |
| shell, one CU | 123,897 | differenced routed builds, docs/SCALING.md |
| each further CU | 12,626 | the quad's fixed cost was 161,775 - sixteen masters of crossbar - so (161,775 - 123,897) / 3 |
| full tile, OOC | 129,708 | the 2026-09-02 case-ROM A/B, ladders off, retimed (docs/ROADMAP.md) |
| fp32 / fp64 / fp128 / fp256 bank | 14,840 / 17,500 / 21,890 / 31,106 | **placeholder**: the 2026-08-30 per-lane pipe figures times lanes, less the ROM saving - being replaced by `hw/synth_attrib.tcl` on the same tree |
| HBM | 32 pseudo-channels, 4 per tile | one PC per master for ordering (docs/SCALING.md): eight tiles hard |
| fits / tight / no | <= 80% / <= 85% / above | the quad closes at 80.6%; 85% is docs/SCALING.md's practical routing limit |

The model is a little conservative on purpose: it predicts 724k for
the routed quad that placed at 701,664, because the cross-boundary
optimisation `v++` does at link time is invisible to a sum of OOC
figures. A narrow tile is the full tile less the banks it drops; the
remainder does not shrink with the rungs.

## What makes a placeholder a build

Every layout that names a narrow variant is a complete, correct link
config for an `.xo` that does not exist yet. Two changes, both in the
build flow and neither in the RTL:

1. **Variant packaging.** `hw/package_kernel.tcl` packages `cft_krnl`
   with its generic defaults and `hw/kernel.xml` names it. It needs to
   take a kernel name and a generics list (`set_property generic` on
   the fileset before `ipx::package_project`, the name substituted
   into the xml), and `rebuild-2022.sh` needs to package one `.xo` per
   variant a layout uses and hand all of them to `v++ -l`.
2. **Per-variant clocks.** `rebuild-2022.sh` derives one `--clock.freqHz`
   from `KERNEL_FREQ` and the first `nk=` line. A layout with two
   variants needs the `[clock]` lines each config already carries
   (commented) passed instead; until then the script refuses a config
   with more than one `nk=` line rather than leaving the second
   variant's CUs on the platform default clock - the silent failure
   its own comments warn about.

And one change on the host, for the mixed rows only: `backend.h` says
"device.c never learns that tiles exist" - one format mask, every CU
alike, work split across all of them. A mixed layout needs per-CU
capability masks (CAPS is per CU already) and a precision-aware split.
The homogeneous narrow rows work with the host as it is, which is why
they are marked host-ready.

## Building one

    LINK_CFG=hw/layouts/u50-4xfp256.cfg KERNEL_FREQ=135000000 \
      RETIMING=1 bash hw/rebuild-2022.sh

works today for the two full-tile rows. Every other row builds the
same way once the two changes above land, and the manifest records
which config it came from.
