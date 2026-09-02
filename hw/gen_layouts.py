# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The layout catalogue: every xclbin the U50 could carry, derived.

A LAYOUT is a tile mix - how many compute units of which kernel
variant - plus the clock each variant closes at. It is fixed when v++
links: the mix, each tile's rungs and each CU's clock are the placed
netlist, and a different mix is a different xclbin (hours to build,
seconds to load - the xclbin is the shell's partial bitstream, and
swapping one is what the dynamic region exists for).

This script is the single source for docs/LAYOUTS.md's table and for
hw/layouts/<name>.cfg. The tile COUNTS are computed, not typed: "max
remaining at fp64" means as many fp64-max tiles as fit beside the
anchor under the area budget and the HBM wall, from the measured tile
costs below. Per the standing rule, constants are derived or copied
with their provenance, never transcribed from memory.

    python hw/gen_layouts.py            # writes hw/layouts/*.cfg, prints the table
    python hw/gen_layouts.py --check    # exit 1 if the committed cfgs are stale

The four kernel variants are one RTL with three generics off
(rtl/cft_krnl.sv: EN_FP64 / EN_FP128 / EN_FP256). prec_ok refuses the
rungs a variant lacks and CAPS[3:0] advertises what it has, so a host
that reads CAPS cannot be lied to. Only `cft_krnl` (all four rungs)
is packaged today; the narrow variants need hw/package_kernel.tcl to
take a kernel name and generics, and rebuild-2022.sh to package one .xo
per variant and take clocks per variant - the two changes that turn a
placeholder into a build. Until then every layout naming a narrow
variant is a PLACEHOLDER: a correct, complete link config for an .xo
that does not exist yet.
"""
import argparse
import io
import sys
from pathlib import Path

HW = Path(__file__).resolve().parent
OUT = HW / "layouts"

# ---- the part, the shell, the walls ----------------------------------
#
# LUT_DEVICE: the "Available" column of the routed quad's
#   full_util_placed.rpt (2026-09-02), which is what Vivado will place
#   into, not the marketing figure.
# SHELL_1CU: the single-tile shell measured by differencing routed
#   builds (docs/SCALING.md, "LUTs"). SHELL_PER_EXTRA_CU: the quad's
#   fixed cost came to 161,775 (sixteen masters of crossbar), so each
#   CU past the first adds (161,775 - 123,897) / 3.
# The model is deliberately a little conservative: it predicts 724k for
# the routed quad that placed at 701,664, because cross-boundary
# optimisation at link time is not something an OOC sum can see.
# HBM_PCS / MASTERS_PER_TILE: 32 pseudo-channels, four masters a tile,
#   one PC per master for ordering (docs/SCALING.md) - eight tiles hard.
LUT_DEVICE          = 870_720
SHELL_1CU           = 123_897
SHELL_PER_EXTRA_CU  = (161_775 - 123_897) // 3
HBM_PCS             = 32
MASTERS_PER_TILE    = 4
MAX_TILES           = HBM_PCS // MASTERS_PER_TILE
FITS_PCT            = 80.0   # the quad closes at 80.6%; call that "fits"
LIMIT_PCT           = 85.0   # docs/SCALING.md's practical routing limit

# ---- what a tile costs, out of context ---------------------------------
#
# FULL: cft_krnl with every rung, ladders off, retimed, at eb8ef2a
#   (the case-ROM commit): 129,708 LUT from the 2026-09-02 A/B in
#   docs/ROADMAP.md. A narrow variant is FULL minus the banks it does
#   not build; the bank costs are per-module figures with the hierarchy
#   preserved (hw/synth_attrib.tcl on the same tree), each bank being
#   its lanes' pipe + simpleops + seedop + opmux. The remainder -
#   engine, sequencer and its register file, FIFOs, reduction
#   accumulator, CSR, lane steering - is BEAT_BITS-wide and does not
#   shrink with the rungs.
#
# Placeholder values are marked; replace them from the attrib run and
# re-run this script. A wrong bank cost moves a tile count by one, and
# the table says which counts sit within one tile of the budget.
LUT_FULL_TILE = 129_708
BANK_LUT = {                 # provenance: see docs/LAYOUTS.md "Costs"
    "fp32":  14_840,         # PLACEHOLDER (2026-08-30 per-lane x8, less the ROM saving)
    "fp64":  17_500,         # PLACEHOLDER
    "fp128": 21_890,         # PLACEHOLDER
    "fp256": 31_106,         # PLACEHOLDER
}

# ---- the kernel variants ----------------------------------------------
# name -> (rungs carried, generics off, target clock in MHz, clock provenance)
# Clocks: only the full tile has a measured in-shell figure (135 MHz,
# single closes at +0.045 retimed; quad pending). The narrow targets
# are the OOC ceilings from docs/ARCHITECTURE.md ("232 MHz fp32 / 148
# fp256, fp64/fp128 between") less the ~0.9 ns the shell has cost in
# practice - TARGETS TO MEASURE, not results.
VARIANTS = {
    "cft_krnl":      dict(rungs=("fp32", "fp64", "fp128", "fp256"), generics="",
                          mhz=135, clock="measured: single +0.045 @135 retimed; quad pending"),
    "cft_krnl_f128": dict(rungs=("fp32", "fp64", "fp128"), generics="EN_FP256=0",
                          mhz=150, clock="target, unmeasured"),
    "cft_krnl_f64":  dict(rungs=("fp32", "fp64"), generics="EN_FP128=0 EN_FP256=0",
                          mhz=170, clock="target, unmeasured"),
    "cft_krnl_f32":  dict(rungs=("fp32",), generics="EN_FP64=0 EN_FP128=0 EN_FP256=0",
                          mhz=190, clock="target, unmeasured"),
}
TOP = {"cft_krnl": "fp256", "cft_krnl_f128": "fp128", "cft_krnl_f64": "fp64",
       "cft_krnl_f32": "fp32"}
SHORT = {"cft_krnl": "fp256", "cft_krnl_f128": "fp128", "cft_krnl_f64": "fp64",
         "cft_krnl_f32": "fp32"}


def tile_lut(variant: str) -> int:
    missing = [b for b in BANK_LUT if b not in VARIANTS[variant]["rungs"]]
    return LUT_FULL_TILE - sum(BANK_LUT[b] for b in missing)


def shell_lut(n_cu: int) -> int:
    return SHELL_1CU + SHELL_PER_EXTRA_CU * (n_cu - 1)


def total_lut(mix) -> int:
    n = sum(c for _, c in mix)
    return shell_lut(n) + sum(tile_lut(v) * c for v, c in mix)


def pct(lut: int) -> float:
    return 100.0 * lut / LUT_DEVICE


def fill(anchor: str, filler: str):
    """Max filler tiles beside one anchor: the largest k with the whole
    layout under FITS_PCT and within the HBM wall."""
    k = 0
    while True:
        mix = [(anchor, 1), (filler, k + 1)]
        if 1 + k + 1 > MAX_TILES or pct(total_lut(mix)) > FITS_PCT:
            return k
        k += 1


def homogeneous(variant: str) -> int:
    k = 0
    while k + 1 <= MAX_TILES and pct(total_lut([(variant, k + 1)])) <= FITS_PCT:
        k += 1
    return k


# ---- the family -------------------------------------------------------
#
# The default is the homogeneous quad, then one fp256 anchor with the
# rest of the ladder filled to the budget at each lower rung, then the
# same pattern one rung down, and the homogeneous narrow layouts that
# complete it. Homogeneous layouts work with the CURRENT host (one
# format mask, every CU alike); mixed ones need per-CU capabilities in
# the backend first (docs/LAYOUTS.md).
def family():
    rows = []
    rows.append(("u50-4xfp256", [("cft_krnl", 4)], "the default; hw/link_quad.cfg"))
    rows.append(("u50-1xfp256", [("cft_krnl", 1)], "the single; hw/link.cfg"))
    ladder = ["cft_krnl", "cft_krnl_f128", "cft_krnl_f64", "cft_krnl_f32"]
    for ai, anchor in enumerate(ladder[:-1]):
        for filler in ladder[ai + 1:]:
            k = fill(anchor, filler)
            if k == 0:
                continue
            name = f"u50-1x{SHORT[anchor]}-{k}x{SHORT[filler]}"
            rows.append((name, [(anchor, 1), (filler, k)], ""))
    for v in ladder[1:]:
        k = homogeneous(v)
        rows.append((f"u50-{k}x{SHORT[v]}", [(v, k)], "homogeneous: works with the current host"))
    return rows


def cu_names(mix):
    names = []
    for v, c in mix:
        names += [f"{v}_{i + 1}" for i in range(c)]
    return names


def render_cfg(name, mix, note) -> str:
    n = sum(c for _, c in mix)
    lut = total_lut(mix)
    placeholder = any(v != "cft_krnl" for v, _ in mix)
    w = io.StringIO()
    p = w.write
    p(f"# {name} - GENERATED by hw/gen_layouts.py; edit the table there, not this file.\n")
    p("#\n")
    p(f"# Tiles: " + ", ".join(f"{c} x {v} ({'/'.join(VARIANTS[v]['rungs'])})" for v, c in mix) + "\n")
    p(f"# Model: {lut:,} LUT of {LUT_DEVICE:,} = {pct(lut):.1f}% "
      f"(shell {shell_lut(n):,} for {n} CUs + tiles); HBM PCs {n * MASTERS_PER_TILE} of {HBM_PCS}\n")
    p(f"# fp256 contract compliant: {'YES' if any(v == 'cft_krnl' for v, _ in mix) else 'no - no tile carries binary256'}\n")
    if placeholder:
        p("#\n# PLACEHOLDER: names kernel variants that are not packaged yet. Needs\n")
        p("#   hw/package_kernel.tcl to take a kernel name + generics, and\n")
        p("#   rebuild-2022.sh to package one .xo per variant and pass the\n")
        p("#   [clock] lines below instead of one KERNEL_FREQ for every CU.\n")
    if note:
        p(f"# {note}\n")
    p("\n[connectivity]\n")
    for v, c in mix:
        p(f"nk={v}:{c}:" + ".".join(f"{v}_{i + 1}" for i in range(c)) + "\n")
    pc = 0
    for cu in cu_names(mix):
        for m in "abcd":
            p(f"sp={cu}.m_axi_{m}:HBM[{pc}]\n")
            pc += 1
    p("\n# One clock per variant (the platform has two kernel clocks, so at\n")
    p("# most two distinct frequencies per layout). rebuild-2022.sh passes\n")
    p("# --clock.freqHz from KERNEL_FREQ today; these are what a per-variant\n")
    p("# flow would pass. Full tile: measured. Narrow tiles: targets.\n")
    p("#[clock]\n")
    for v, c in mix:
        cus = ",".join(f"{v}_{i + 1}.ap_clk" for i in range(c))
        p(f"#freqHz={VARIANTS[v]['mhz'] * 1_000_000}:{cus}   # {VARIANTS[v]['clock']}\n")
    return w.getvalue()


def render_table(rows) -> str:
    w = io.StringIO()
    p = w.write
    p("| layout | tiles | CUs | HBM PCs | clocks (MHz) | model LUT | of device | fit | fp256 contract | status |\n")
    p("|---|---|---|---|---|---|---|---|---|---|\n")
    for name, mix, note in rows:
        n = sum(c for _, c in mix)
        lut = total_lut(mix)
        pc = pct(lut)
        fit = "fits" if pc <= FITS_PCT else ("tight" if pc <= LIMIT_PCT else "no")
        tiles = " + ".join(f"{c}x {SHORT[v]}-max" if v != "cft_krnl" else f"{c}x fp256 (full)" for v, c in mix)
        clocks = " / ".join(f"{VARIANTS[v]['mhz']}{'' if v == 'cft_krnl' else '*'}" for v, _ in mix)
        ok = "**✓**" if any(v == "cft_krnl" for v, _ in mix) else ""
        if all(v == "cft_krnl" for v, _ in mix):
            status = "built" if name == "u50-4xfp256" or name == "u50-1xfp256" else "placeholder"
        elif len(mix) == 1:
            status = "placeholder (needs variant packaging; host-ready)"
        else:
            status = "placeholder (needs variant packaging + per-CU host split)"
        p(f"| `{name}` | {tiles} | {n} | {n * MASTERS_PER_TILE} | {clocks} | {lut:,} | {pc:.1f}% | {fit} | {ok} | {status} |\n")
    return w.getvalue()


def main(argv=None) -> int:
    # The table carries a check mark; a cp1252 console (Windows) cannot
    # print one and would abort AFTER the configs were written.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if hw/layouts is stale")
    args = ap.parse_args(argv)
    rows = family()
    stale = []
    OUT.mkdir(exist_ok=True)
    for name, mix, note in rows:
        text = render_cfg(name, mix, note)
        dest = OUT / f"{name}.cfg"
        if args.check:
            if not dest.exists() or dest.read_text(encoding="utf-8") != text:
                stale.append(dest.name)
        else:
            dest.write_text(text, encoding="utf-8", newline="\n")
    print(f"tile costs (OOC model): " + ", ".join(f"{SHORT[v]} {tile_lut(v):,}" for v in VARIANTS))
    print(f"shell: {SHELL_1CU:,} + {SHELL_PER_EXTRA_CU:,} per extra CU; budget {FITS_PCT:.0f}% of {LUT_DEVICE:,}; HBM wall {MAX_TILES} tiles")
    print()
    print(render_table(rows))
    if args.check:
        if stale:
            print("STALE: " + ", ".join(stale) + " - run python hw/gen_layouts.py")
            return 1
        print("hw/layouts up to date")
    else:
        print(f"wrote {len(rows)} configs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
