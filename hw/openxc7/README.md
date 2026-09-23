# hw/openxc7 - the tile through the open toolchain

The instruments behind docs/VALIDATION.md's entries of 2026-09-22 and
2026-09-23: the first runs of this tile through openXC7 (Yosys,
nextpnr-xilinx and Project X-Ray), and the census that sized the
XC7K410T question. They are records and measuring tools, not a
platform. Nothing here is a board top, and **every bitstream these
files produce is a place-and-route harness that must never be loaded
onto a board** - its pins drive arbitrary values.

The toolchain is the `cft-openxc7` image, built from
`docker/Dockerfile.openxc7` beside the project's other images; the pins
and their measured hashes are in that file's header.

    docker build -t cft-openxc7 -f docker/Dockerfile.openxc7 docker
    docker build --build-arg JOBS=24 ...     # on a box with the cores

25.5 minutes on amd-arc-box, 7.13 GB. That box's Docker has no buildx,
so its legacy builder refuses `--progress`.

## The files

| file | what it is | provenance |
|---|---|---|
| `gen_harness.py` | writes the place-and-route harness for `cft_krnl` from the kernel's OWN port list: every input from one register chain fed by a pin, every output XOR-folded and registered into one pin, so synthesis prunes nothing a real platform would keep. `NAME=VALUE` overrides a kernel parameter; with none, the `board` configuration. It refuses a parameter the kernel does not declare. | generalised 2026-09-23 from the version the board run used; with no arguments its output is byte-identical to that run's harness (sha256 `9b01d6b7...`) |
| `cft_pnr_harness.xdc` | the harness's five pins: openXC7 demo-projects blinky-kc705's clock pair (AD12/AD11, LVDS) and LED pin AB8, with its bank-33 neighbours AA8 and AC9 | as run |
| `run_pnr_inner.sh` | the staged flow, run inside `cft-openxc7`: Yosys (`read_verilog -defer`, `synth_xilinx -flatten -abc9 -arch xc7`), nextpnr-xilinx at 100 MHz with `--timing-allow-fail`, fasm2frames, xc7frames2bit. Each stage leaves `<stage>.log`, `.rc` and `.secs`; the run stops at the first failure | the 2026-09-23 runs used sha256 `aceba8ff...`, which listed the sixteen RTL files by name; the committed copy globs `rtl/*.sv` instead, since `rtl/cft_imul.sv` arrived that day |
| `synth_board.ys` | the 2026-09-22 synthesis of `cft_krnl` alone in the board configuration, parameters by `chparam` | as run (`d10aec43...`) |
| `census.tcl` | the tile- and site-type census of 7-series parts, each opened by `link_design -part` with no netlist | as run |
| `census-2026-09-22.txt` | its output for five Kintex-7 parts (Vivado 2026.1) | as measured |
| `prjxray-db-1768fb35-kintex7-tile-types.txt` | the 113 kintex7 tile types of prjxray-db at the commit the image pins, which the census was compared against | fetched 2026-09-22 |
| `imul_bisect.ys` | lists every `$mul` cell after each early synthesis pass, to find where a multiplier leaves the netlist | 2026-09-23 |
| `imul_bisect2.ys` | the second cut: `opt -full` run as its sub-passes, with the fp64 lane-0 IMUL result wire probed for its driver before and after. It named `opt_merge`, and a merge onto fp32 lane 0's identical product | 2026-09-23 |
| `dsp_by_lane.tcl` | counts a routed Vivado checkpoint's DSP48E1 cells by bank, lane and module | 2026-09-23 |

## Running them

The flow, for a configuration (the board one if no parameters are given):

    mkdir -p out
    python hw/openxc7/gen_harness.py rtl/cft_krnl.sv out/cft_pnr_harness.sv MUL_PASSES=1
    cp hw/openxc7/cft_pnr_harness.xdc hw/openxc7/run_pnr_inner.sh out/
    docker run --rm -v "$PWD:/work:ro" -v "$PWD/out:/pnr" cft-openxc7 bash /pnr/run_pnr_inner.sh

`gen_harness.py` prints the widths it derived. They must be 857 input
and 699 output bits - the standalone synthesis's 859 IBUF and 699 OBUF
less clock and reset - or the kernel's ports have changed and the
harness with them.

The census, with the Basic-only licence file (docs/BRINGUP.md explains
why the tier matters):

    XILINXD_LICENSE_FILE=<Basic-only .lic> vivado -mode batch -nolog -nojournal \
      -source hw/openxc7/census.tcl -tclargs census.txt \
      xc7k325tffg900-2 xc7k410tffg900-2

## What these numbers are, and are not

- **Synthesis and placement are measurements; nextpnr's timing is
  not the whole story.** nextpnr-xilinx 0.9.6 times a registered
  DSP48E1 as `TMG_IGNORE`, and 96 of the board configuration's 120 DSPs
  are registered, so its Fmax cannot see through most of them. Vivado
  on the same tree (`hw/mc_sweep.sh`) is the timing reference.
- **A bitstream that builds is not a design that works.** Arithmetic
  through openXC7 is unproven until the conformance vectors pass on
  hardware: nextpnr-xilinx PR #159 (DSP48E1 constant pins) was still
  open on 2026-09-22, and every DSP here has constant OPMODE, INMODE
  and ALUMODE.
- **The synthesis cost.** Without `-defer`, Yosys elaborates every
  module at its default parameters before `chparam` re-derives them:
  63.6 minutes against 46.7 with it, about 4.9 GB either way.
