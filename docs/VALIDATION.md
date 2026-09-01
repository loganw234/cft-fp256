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

## 2026-08-31 - image verifier commissioned (hw/verify-image.sh)

Static verification that a staged xclbin IS the build its manifest
describes - the wrong-file-staged failure class, caught before a card
is involved. Eight checks: sha256 (the artifact's only trustworthy
identity; filenames are deliberately not checked, the card-day set is
renamed on purpose), platform VBNV, Bitstream-content-vs-target,
CU set vs clock_cus, link config and the 130 MHz kernel constraint
recovered from BUILD_METADATA's recorded v++ line (NOT from
CLOCK_FREQ_TOPOLOGY - this shell realises the constraint as a
statically-configured ULP clock wizard, so the topology section only
shows the shell's own clocks), clock-topology sanity, and the memory
intent: every master on HBM, no pseudo-channel shared between two
masters anywhere in the image. Absent sections SKIP by name - and
under a target-hw manifest, absence is a FAIL.

Commissioned against the real card-day pair on the box: both
bac9f550 images pass 8/8. Four negative controls behaved: an altered
kernel_freq failed exactly that check with sha256 still green; the
quad image under the single manifest failed on five independent axes;
a section-stripped image SKIPped by name under an emu manifest and
FAILED under a hw one. Finding recorded en route: the bac9f550
masters each span 2 (quad) or 4 (single) HBM channels - they predate
the one-channel-per-master link.cfg - with disjointness holding, so
same-ID ordering rests on the HBM switch there. The milestone pair
building from b1a014c carries the audited single-channel config and
should verify as one channel per master.

## 2026-08-31 - formal gate commissioned (formal/, `make formal`)

Property proofs for the modules whose correctness is a control
argument rather than an arithmetic one, in a pinned container
(Yosys 0.68, SBY, bitwuzla). Seven proofs, ~37 s total:

  * cft_fifo at 8x8: count consistency, the full/empty contract, and
    head-data integrity/ordering against a port-only shadow FIFO -
    UNBOUNDED (mode prove, abc pdr), with covers proving all eight
    control shapes reachable (both bypass captures, the two-cycle
    age-out, wrap, mid-stream clear included).
  * cft_seedop at fp32: decode exactness plus every special-class
    routing including flush-at-input, complete over all 2^40 inputs;
    expected encodings derived from field expressions, never typed.
  * cft_simpleops == the frozen pre-rewrite ref on valid/d/flags for
    ALL 2^104 inputs with op != 26/27 (the sanctioned reassignment
    divergence) - the area rewrite's equivalence, which the benches
    sampled, is now a theorem at the fp32 rung. Budgeted 30 minutes
    as a stretch; bitwuzla closed it in two seconds.

The commissioning's most valuable output is a failure mode: Yosys's
open frontend silently drops `bind` and elaborates hierarchical
references as fresh dangling wires, and the first FIFO "proof" passed
with ZERO assertions in the model. The gate now counts assertion
cells per elaborated model before trusting any verdict, the FIFO
proof uses pdr (the engine synthesises the inductive invariant the
frontend won't let a human write), and a negative control - a
deliberately false "the bypass was never needed" claim - must be
refuted (counterexample at step 3, the write-at-read-head capture)
for the gate to report green. Each harness was also mutation-tested
before first commit. Scope limits are in formal/README.md and are
part of the claim.

## 2026-08-31 - RTL deep soak on the build box (clean)

The cocotb suite far past its CI depth, in the cft-sim container on
amd-arc-box under nice -19 beside two Vivado routes: one full
baseline pass of all 15 targets, then deep-random fpfma passes at two
seeds (fp32/fp64 at 120k vectors each, fp128 at 60k, fp256 at 40k,
Verilator) plus 60k-vector simpleops passes - roughly 800,000
deep-random vectors against the golden model over the same RTL the
milestone images were built from. Every results file FAIL=0.

## 2026-08-31 - Verilator width-warning audit (merged b127a7a)

The blanket WIDTHEXPAND/WIDTHTRUNC suppression came off tb/cocotb.mk:
225 warnings across 25 source lines triaged to ZERO - twelve lines
made explicitly-widthed where provably bit-identical, thirteen kept
under tightly-scoped waivers each carrying its safety argument. Width
warnings are now FATAL under Verilator, so the compile is a standing
gate. Proven behind it: equivalence benches with warnings fatal, the
full suite 40/40, yosys clean, and the simpleops formal theorem
re-proven after that file's edits. Three findings deliberately NOT
fixed (no bit-level-NOP fix exists) and recorded for design action:
the stream FIFOs hardcode WIDTH(256) so a quarter tile carries 4x the
BRAM it needs; AR_DEPTH >= 256 would silently wrap AR_MAX and hang a
run (wants a generate $error); and prec_caps is readback-only - the
engine never refuses a cfg_prec outside its caps, which matters the
moment trimmed open-core builds exist. Also recorded: 95 pre-existing
SELRANGE warnings (a different lint class, never covered by the old
blanket) and a Verilator 5.020 internal error keep mulfrac/mulshare/
quarter Icarus-only, as they already were.

## 2026-08-31 - standardized verification runner commissioned (verify/)

verify/run.sh: every accumulated gate in one resumable, skippable,
logged invocation - 13 stages from the golden model through the
native-oracle spot check, per-stage .ok/.fail markers, resume that
refuses to cross commits, a per-run lock (added after a killed
wrapper's orphaned stage ran beside its own resume and interleaved
two runs' state), skips named with reasons and --require-all to turn
them into failures, and a census block for this file at the end.
Commissioning run at e0db303 on the dev box: 11 stages ran, sim's 15
targets and the formal proofs included; the single failure was the
soak stage's own aggregator counting the negative control's 65,536
intentional mismatches into the totals - the control eating the
experiment - fixed by keeping the control's output outside the
sweep's glob. The runner's clean first full run is recorded below
when it lands post-merge.

## 2026-08-31 - native-oracle campaign COMPLETE on the build box (clean)

The full campaign hw/run-soak.sh was commissioned for: 332 of 332
jobs, 23.875 billion cases, ZERO value mismatches, ZERO flag
mismatches. That is exhaustive fp32 square root - every one of the
2^32 encodings - under all five rounding attributes (21.47B cases;
RMM rode the RNE oracle, sqrt having no ties), plus 2.4 billion
exponent-banded random div32/div64/sqrt64 under the four native
modes. cft_div and cft_sqrt never once disagreed with the host CPU's
own IEEE hardware, results or exception flags; the only mismatches in
the raw logs were the negative control's 65,536 injected corruptions,
all detected. Ran at nice -19 beside two Vivado routes and the RTL
soak, ~6 hours wall. (The box ran the pre-fix aggregator whose
summary line counts the control's log; the verdict above is taken
from the 332 job logs directly, control excluded - the fixed
aggregator is in hw/run-soak.sh as of 86b136b.)

## 2026-08-31 - standardized verification run (DESKTOP-T33SK86)

verify/run.sh at 86b136b, clean tree: 13 stages; 0 failed, 1 skipped
(images - xclbinutil not present on this host, named as such). The
runner's first full clean census: golden 148s, vectors 8s, sim (all
15 targets) 1826s, lint 51s, formal 37s, libcft/selfcheck/divsqrt/
diff/seq/reduce 33s together, soak-quick with its sabotage control
121s. Run id 20260831-2019-86b136b. A note on the small numbers,
because they looked wrong until measured: divsqrt_check's 29,124
cases take 0.6 s - the model is microseconds per case at fp32/64 and
the library is C - so sub-second stages are honest, not cached.

## 2026-08-31 - MPFR parity: the third oracle, first to reach every rung

host/tools/mpfr_check.c (make mpfr-check; `mpfr` stage of
verify/run.sh): add/sub/mul/fma/div/sqrt against GNU MPFR 4.2.2 -
the arbitrary-precision library the rest of the world treats as the
reference for correct rounding, and the first INDEPENDENT oracle
that reaches binary128 and binary256 (the CPU stops at binary64; the
golden model shares an author with the library). IEEE emulation per
the MPFR manual's own recipe; results compared in the MPFR domain,
NaN as a class; over/underflow derived from an unbounded-range
recompute so tininess-after-rounding matches round_pack's definition
rather than reconciling flag semantics; RMM (no MPFR mode exists)
built from pure-MPFR intermediates by the p+1 guard/sticky
construction, with subnormal landings quantised on the fixed grid.

Results: 999,000 cases clean - 177,240 in commissioning plus two
full-pool runs of 410,880 (seeds 7 and 1913) - across all four
formats x six operations x five modes, specials, hard families and
exponent-banded randoms, values AND flags, zero disagreements.
Commissioning also worked as designed in the other direction: the
harness's first draft had two bugs (its invalid rule consulted
operands the op does not read; its subnormal RMM rounded at a
precision instead of the fixed grid) and the fp32/fp64 rows - already
proven against 23.9B CPU cases - convicted the harness immediately,
while the library was right in every disagreement, including the
tie-at-the-subnormal-grid case. That is the self-calibration a new
oracle owes before its fp128/fp256 verdicts count.

## 2026-08-31 - precision refusal (STATUS[3]) + the adversarial pair

A trimmed build now REFUSES a MODE precision it does not carry (and
codes 4-15 on every build): engine never starts, no memory moves,
done still asserts, STATUS[3] sticky until the next accepted start,
FLAGS untouched. Proven at both geometries: the quarter tile refuses
fp128/fp256/code-5/code-15 with the D pattern intact and the sticky
clearing on the next accepted run; the full tile refuses code 9; the
faults bench pins fault-run-then-refusal reading exactly 0x8.

Before it merged, two adversarial reviewers went over it plus the
week's tooling - the pattern that previously found four bugs. This
round: 16 confirmed findings between them, every one closed. The
hardware half SIMULATED the worst one (a refusal's STATUS ORed with
the previous run's stale fault bits, misfiled by the host as a bus
fault on a run that never touched the bus - fixed by masking the
engine's sticky while the last start was refused), and found
cft_seedop's width guard admitting the one width its own shift cannot
survive. The tooling half demonstrated four real misbehaviors of
verify/run.sh (same-minute run adoption, typo'd --only passing with a
crashed census, Windows docker-build paths, --skip re-verdicting
finished work), independently derived the STATUS bug, and cleared
divsqrt.c's core after a 176k-case forced lane-state interrogation.
Collateral finds en route: busfx.unstall had left a third of the AXI
channels frozen paused since the day it was written - invisible
because no test had ever driven traffic after unstalling - and the
first bench to do so was the refusal block itself.

Suite after everything: 15 targets / 40 tests green, yosys clean,
XRT backend compiled against real headers.

## 2026-09-01 - the general-purpose milestone pair (b1a014c, amd-arc-box)

Both 130 MHz images closed and staged to ~/cardday-ms - the first
card images on which every 754 operation the contract defines runs
(seed opcodes in hardware, div/sqrt composed by libcft):

    cft_hw_single.xclbin  kernel_wns +0.220 ns  (0 of 104,664 failing)
    cft_hw_quad.xclbin    kernel_wns +0.009 ns  (0 of 418,294 failing)

hw/verify-image.sh: 8/8 checks on both, and the memory intent reads
EXACTLY one HBM pseudo-channel per master - the audited link.cfg
property, now confirmed in silicon-bound metadata (the bac9f550 pair
spans 2-4 channels per master; same-ID ordering there rests on the
HBM switch, here on the channel by construction). The quad's +0.009
against bac9f550's +0.019 is the seed ROMs' cost made visible.
SHA256SUMS verified after staging; the 145 MHz single attempt against
the measured 142.7 ceiling launched from the same tree immediately
after, and gets its own entry when it lands.

## 2026-09-01 - standardized verification run at the merged HEAD

verify/run.sh at 6a888b0 (clean tree): 13 stages executed, 0 failed,
1 skipped (images - xclbinutil, named). First census carrying the
refusal feature, the reviewed runner, and the mpfr stage: golden
148s, vectors 9s, sim 1778s, lint 48s, formal 34s, the library
chain 35s together, mpfr parity 2s, soak-quick + control 103s.
Run id 20260831-222657-6a888b0.

## 2026-09-01 - the ceiling moves: 145 MHz closes with margin

The single-tile attempt at 145 MHz - launched against the "measured
~142.7 ceiling" the 260 failure implied - CLOSED: kernel_wns
+0.032 ns, image verified 8/8 (sha256 91c9f322...), seeds aboard,
staged in build-145 on the box. The lesson is about the measurement,
not just the design: an achieved-period reading from a hopelessly
over-constrained run understates what the router does for an
achievable target. The true ceiling is >= 145; a quad attempt at 145
and a single at 150 launched immediately to bracket it, and 145 is
now a real candidate clock for a future card-day set (+11.5%
throughput over the staged 130 pair) once emulation and first light
vouch for the 130s.

## 2026-09-01 - the ceiling bracket completes

    single @145  CLOSED  kernel_wns +0.032   (image verified 8/8)
    single @150  failed  WNS -0.070, 163 of ~540k endpoints, hold clean
    quad   @145  failed  WNS -0.302, 4,132 of 903,889 endpoints, hold clean

Single-tile ceiling: ~148 MHz (the 150 miss is 70 ps wide). Quad
ceiling: ~139 MHz - and note what the quad numbers say about
measurement bias a second time: at 130 the router stopped at +0.009
because it only needed to, while pushed to 145 it achieved a period
equivalent to ~138.9 MHz. A router's slack at a met target is a
stopping point, not a capability statement; only a failed target
measures the edge. A single @147 attempt (predicted ~+66 ps from the
bracket) is running to pin the number; quad attempts past ~139 are
not worth the hours.
