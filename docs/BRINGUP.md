# Hardware bring-up

The ordered gates between "green in simulation" and "the card
reproduces the vectors". Everything here needs the Linux box with
Vitis/Vivado (2022.2 or later recommended for the platform below) and
XRT; nothing before this file does.

Record each gate the way a census is recorded: tool versions, platform
name, xclbin hash, and the exact command. A bring-up you cannot replay
is a bring-up you do not have.

## 0. Environment

```bash
source /opt/xilinx/xrt/setup.sh
source /tools/Xilinx/Vitis/2022.2/settings64.sh   # your version here
xbutil examine
```

`xbutil examine` names the shell the card actually runs. The Makefile
default is `xilinx_u50_gen3x16_xdma_5_202210_1`; a U50C may report a
different platform name/generation - pass `PLATFORM=<what xbutil
says>` to make rather than editing files. If the reported part differs
from `xcu50-fsvh2104-2-e`, pass `PART=` too.

## 1. Gate: the packaging script runs

```bash
make xo
```

`hw/package_kernel.tcl` follows the documented Vitis RTL-kernel
sequence but HAS NOT yet been run against a live Vivado - expect
first-contact friction here, not silence. Likely first failures:
interface inference (the `ipx::associate_bus_interfaces` names must
match what packaging inferred from the port prefixes) and synthesis
lint on the behavioural core. Fix forward; the RTL is the artifact the
testbenches guard, so any RTL change loops back through `make
sim-docker` first.

**Done when:** `build/cft_krnl.xo` exists and `v++ --list_kernels`
(or the link step) sees `cft_krnl`.

## 2. Gate: hardware emulation

```bash
make xclbin TARGET=hw_emu
XCL_EMULATION_MODE=hw_emu python3 host/examples/vector_fma.py \
    build/cft_hw_emu.xclbin --format fp32 --op fma --n 64
```

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

- Exact U50C platform naming and whether the deployment shell
  generation matches the development platform installed.
- Whether `interrupt="false"` polling latency is acceptable for the
  intended run lengths, or the v1 CSR should export the interrupt.
- Behavioural-core synthesis QoR: LUT cost of the fp256 unit as
  written (the wide priority encoders and shifters are the suspects).
  This number decides how much of v1's pipelining lands before or
  after first light.
