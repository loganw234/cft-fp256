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

**A note on the narrow rows.** Raw fp32 and fp64 throughput is not
what this project is for. Every CPU and GPU made serves those formats
at clocks and lane counts this fabric will not match. They are here
because binary32 and binary64 are rungs of the same IEEE 754 ladder as
binary128 and binary256, and carrying the whole ladder is what lets
one contract - bit-exact, deterministic, the same result on every
backend - cover all of them. Read the fp32- and fp64-heavy layouts as
a convenience and a conformance story, not as a performance target;
the numbers that matter are the fp128 and fp256 ones.

<!-- layouts:begin -->

| layout | tiles | CUs | HBM PCs | clocks (MHz) | model LUT | of device | fit | fp256 contract | status |
|---|---|---|---|---|---|---|---|---|---|
| `u50-4xfp256` | 4x fp256 (full) | 4 | 16 | 135 | 687,319 | 78.9% | fits | **✓** | built |
| `u50-1xfp256` | 1x fp256 (full) | 1 | 4 | 135 | 255,283 | 29.3% | fits | **✓** | built |
| `u50-1xfp256-4xfp128` | 1x fp256 (full) + 4x fp128-max | 5 | 20 | 135 / 150* | 689,999 | 79.2% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp256-5xfp64` | 1x fp256 (full) + 5x fp64-max | 6 | 24 | 135 / 170* | 661,218 | 75.9% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp256-7xfp32` | 1x fp256 (full) + 7x fp32-max | 8 | 32 | 135 / 190* | 646,464 | 74.2% | fits | **✓** | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp128-5xfp64` | 1x fp128-max + 5x fp64-max | 6 | 24 | 150* / 170* | 625,885 | 71.9% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp128-7xfp32` | 1x fp128-max + 7x fp32-max | 8 | 32 | 150* / 190* | 611,131 | 70.2% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-1xfp64-7xfp32` | 1x fp64-max + 7x fp32-max | 8 | 32 | 170* / 190* | 583,639 | 67.0% | fits |  | placeholder (needs variant packaging + per-CU host split) |
| `u50-5xfp128` | 5x fp128-max | 5 | 20 | 150* | 654,666 | 75.2% | fits |  | placeholder (needs variant packaging; host-ready) |
| `u50-7xfp64` | 7x fp64-max | 7 | 28 | 170* | 679,580 | 78.0% | fits |  | placeholder (needs variant packaging; host-ready) |
| `u50-8xfp32` | 8x fp32-max | 8 | 32 | 190* | 558,335 | 64.1% | fits |  | placeholder (needs variant packaging; host-ready) |

*(this table is written by `python hw/gen_layouts.py`; the two "built" rows are `hw/link_quad.cfg` and `hw/link.cfg` by another name - identical connectivity)*

<!-- layouts:end -->

Which wall binds differs by rung. The fp32 fillers reach the HBM wall
first - an eighth compute unit is the thirty-second pseudo-channel -
so every `+7xfp32` row and `u50-8xfp32` stop there with area to spare.
The fp64 and fp128 fillers are area-limited: one more fp64 tile beside
the fp256 anchor lands at 85%, an eighth homogeneous fp64 at 87%, a
fifth fp128 beside the anchor at 92%.

## Costs, and where they come from

| quantity | value | provenance |
|---|---|---|
| device LUTs | 870,720 | the "Available" column of the routed quad's `full_util_placed.rpt` |
| shell, one CU | 123,897 | differenced routed builds, docs/SCALING.md |
| each further CU | 12,626 | the quad's fixed cost was 161,775 - sixteen masters of crossbar - so (161,775 - 123,897) / 3 |
| full tile | 131,386 | `hw/synth_attrib.tcl` (hierarchy preserved) on the RTL of eb8ef2a, the case-ROM commit, 2026-09-02; the same tree flattened for QoR reads 129,708 (the A/B in docs/ROADMAP.md), 1.3% less |
| fp32 / fp64 / fp128 / fp256 bank | 26,592 / 25,304 / 27,492 / 35,333 | the same run: per lane, pipe + opmux + simpleops + seedop (fp32 2,472 + 34 + 360 + 458; fp64 5,014 + 66 + 758 + 488; fp128 11,649 + 131 + 1,401 + 565; fp256 31,258 + 262 + 3,139 + 674), times lanes |
| what does not shrink | ~15,300 | sequencer 8,565, engine 5,352 (FIFOs and accumulator inside), CSR 576, lane steering ~800 - all `BEAT_BITS`-wide |
| HBM | 32 pseudo-channels, 4 per tile | one PC per master for ordering (docs/SCALING.md): eight tiles hard |
| fits / tight / no | <= 80% / <= 85% / above | the quad closes at 80.6%; 85% is docs/SCALING.md's practical routing limit |

Each bank costs about the same - the ladder's known shape, lanes
halving as precision doubles - until fp256, which cannot halve and
pays a third more. So dropping the fp256 rung saves 35k, each further
rung about 26k, and an fp32-only tile is a third of a full one.

Calibration: the model puts the routed quad at 687,319 against the
701,664 it actually placed - 2% optimistic, and that 2% is inside the
80% "fits" line the quad itself sits on at 80.6%. A narrow tile is the
full tile less the banks it drops; the remainder does not shrink with
the rungs. Every narrow figure is a model until a narrow tile has been
linked; the first one built will recalibrate this table.

Since these costs were measured (eb8ef2a) the round stage's
precompute took the full tile to 123,420 flattened, -6,288 (9f73107,
docs/ROADMAP.md); the bank costs above are one commit behind and the
counts are conservative by about that much. They will be re-measured
with `hw/synth_attrib.tcl` on the same tree before any narrow tile is
packaged.

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
