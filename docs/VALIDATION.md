# Validation ledger

Append-only record of validation campaigns: what ran, where, against
which commit, and exactly what it proved. CARDDAY.md promises runs get
recorded "the way atlas-darkroom records a census" - this file is that
census. One entry per campaign, newest last, numbers verbatim from the
run. An entry never edits history; a correction is a new entry naming
the old one.

The standing inventory (what runs continuously or per-commit, as
opposed to the campaigns below): the golden-model pytest suite and the
cocotb RTL suite + yosys elaboration gate in CI on every push; the
host library's `make test` (API contract, canonical-partition
property, conformance replay, C/ctypes identity) on demand; and the
model-vs-library sweeps `difftest`, `divsqrttest`, `seqtest`,
`reducetest`.

---

## 2026-08-30 - card-day image pair at bac9f550 (amd-arc-box)

The 130 MHz pair staged for card day: one AXI master per stream,
reductions at contract 0x500, the bus-fault abort.

    cft_hw_single.xclbin   kernel_wns +0.271 ns
    cft_hw_quad.xclbin     kernel_wns +0.019 ns, routed_wns 0.018
                           (whole design, shell included)

Manifests with tool versions, commit, and sha256 sit beside the
artifacts in `~/cardday-130b` on the box (SHA256SUMS verified after
copy). hw_emu at contract 0x500 ran reductions green the same day:
single tile 64 checks, and the quad including the
five-ranges-across-four-tiles case (n=33) that only exists when
canonical ranges outnumber tiles.

## 2026-08-31 - the 260 MHz attempt: a measured ceiling, on purpose

A deliberate long-shot single-tile build at 260 MHz, expected to fail,
run to measure WHERE it fails. Route completed; timing did not:

    WNS  -3.163 ns   (target period 3.846 ns)
    TNS  -37,377.6 ns over 29,937 failing endpoints
    hold clean (WHS +0.006, 0 violations)
    no bitstream written (Vitis refuses on timing failure - correct)

Achieved period 7.01 ns = a measured in-shell ceiling of ~142.7 MHz
for the current RTL, agreeing with the OOC-derived estimate of
138-145. The miss is broad - thirty thousand endpoints, not one rogue
path - so 260 means re-pipelining, not tweaking. The control build at
130 MHz from the same tree closed at kernel_wns +0.450 (best single to
date), which also validated the BRAM FIFO and the one-pseudo-channel
link.cfg in-shell. A single-tile attempt at ~145 is the recorded
next experiment against this ceiling.

## 2026-08-31 - divide/sqrt seed opcodes in RTL (commits 100a254, 61779f8)

The seed stack: cft_seedop at every lane of all four banks, ROM
generated from the model and drift-locked, CAPS bit 14 set.

  * tb_seedop: 85,264 comparisons against the model - all 512 table
    indices at both exponent parities across the exponent range
    including the recip subnormal-landing band, every special class,
    all four rungs. Plus a negative control.
  * full cocotb suite after engine wiring: 15 targets / 40 tests, 0
    failures; per-rung end-to-end seed runs in test_krnl where FLAGS
    must return zero with specials in the stream.
  * yosys elaboration gate, now with `hierarchy -check` - added after
    discovering the file list had drifted (cft_reduce_acc shipped
    unlisted and was silently blackboxed; a gate that can skip a
    module without saying so is not a gate).
  * CI runs 33449312557 / 33451145693: green.

## 2026-08-31 - cft_div / cft_sqrt in libcft (commit b1a014c)

The composed sequence as C, one code path for every backend.

  * host/tests/divsqrt_check.py: 29,124 cases against the golden
    model - four formats x five rounding attributes over the operand
    families that killed five earlier constructions, flags compared
    per element, plus a 5,000-element batch crossing the library's
    4,096-element chunk boundary. Zero disagreements.
  * conformance: 20 vector sets regenerated (the replayer's stale-set
    trap fired on the old ones - opcode 26 was recorded as reserved
    and is now assigned, the second time the "unassigned example"
    hazard has fired; vectors.py now samples 28). 392,000 cases
    replayed exactly, each set twice (per-element and batched).
  * api-test: hand-derived 754 answers (1/3, sqrt(2), both divide
    flags, signed-zero sqrt, fp256 identities) plus the argument
    contract, in C.
  * device_test software self-check with seeds in the opcode matrix
    and the new div/sqrt comparison: 1,784 checks, 0 failed.

## 2026-08-31 - native-oracle soak (tool commissioned)

host/tools/divsqrt_soak.c + hw/run-soak.sh: cft_div/cft_sqrt at
fp32/fp64 against the host CPU's own IEEE division and square root -
an oracle nobody in this repository defined. Exhaustive fp32 sqrt
(all 2^32 encodings) under all five attributes (RMM rides the RNE
oracle: sqrt provably has no ties), random banded div32/div64/sqrt64
under the four native modes, hardware exception flags compared via
fenv. NaN payloads compared as a class (hardware propagates, the
contract canonicalises; the difference is model-pinned).

Commissioning on the Windows dev box: 13.4M cases across subnormal,
around-1.0, inf/NaN, negative and random-banded operands - 0 value
and 0 flag disagreements. Negative control (CFT_SOAK_SABOTAGE=1)
detected 65,536/65,536 injected corruptions. Campaign results on the
build box get their own entry when they land.
