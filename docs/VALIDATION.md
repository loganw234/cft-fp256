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

## 2026-09-01 - hw_emu on the seed image: stopped by decision, clean

device-test -q against the b1a014c hw_emu image on cft2204: 33
kernel invocations over ~13 hours of saturated simulation, every one
completing with err=000 - the CSR programming, AXI DMA, buffer
staging and start/done handshake of the seed-bearing image, the fp32
FMA comparison (12 checks, 0 failed), and roughly half of the first
composed-divide sequence's steps, all through the real shell stack.
Stopped at Logan's call: at ~24 minutes per invocation the fp32
div/sqrt verdict alone was another ~14 hours away and the full
four-format matrix a multi-day affair, for confirmation that ~200
more invocations of an already-proven round-trip also work. The
composed sequence's remaining validation belongs to first light,
where those invocations cost microseconds; 13 hours of zero-error
saturation is the emulation's testimony.

## 2026-09-01 - the contract validates in a browser tab

bindings/wasm: the software backend compiled to WebAssembly (pinned
emsdk container, two clean builds byte-identical) behind a single
self-contained HTML page that works from file:// - no server, no
install, no network. Bit-exactness is by construction: the softfloat
is integer-only and wasm integer semantics are fully specified. The
page replayed its embedded 4,015-case sample (every opcode name in
every one of the 20 sets, seeds included) clean, then a drag-drop of
all 20 real vector sets: 236,000 cases, library matches the vectors
exactly, ~13 s. A wrongly-named file yields "NOTHING WAS CHECKED" in
red rather than a quiet pass, and the per-build negative control (one
corrupted expected value) fails loudly with the library's own
disagreement detail, screenshotted. The compute panel runs every
elementwise op plus the composed div/sqrt at all four formats -
binary256 square root, correctly rounded, in a browser tab. The bar
of entry is now one compliant browser.

## 2026-09-01 - clause 5, completed with zero new RTL

The operations the capability sheet still listed as absent -
roundToIntegral (named + Exact), formatOf-convertFormat (all 16
pairs), int32/uint32/int64/uint64 conversions both ways, scaleB,
logB, nextUp/nextDown, class, totalOrder/totalOrderMag, the
signaling comparisons, and exact remainder - landed as contract
functions in one day, in three layers, each proven before the next
was built:

    golden model     +42 pytest, arbiters sharing no code with it:
                     math.remainder/nextafter/ldexp/frexp, round/
                     floor/ceil/trunc, struct's double->float, an
                     exact-rational reference for all five attributes,
                     hand-derived 754 edges (nextUp's -0, rint's
                     signed zero, logB(0)'s divideByZero, the
                     totalOrder chain over the encoding zoo)
    sequences        rint_seq (the magic-constant addition made total)
                     and scaleb_seq (exact-power multiplies, staged
                     saturation proven consistent) bit-identical to
                     the contract over every format, attribute, and
                     each construction's own boundary families
    libcft           18 entry points (ABI 0.2), composed where
                     floating-point work exists, host-exact where none
                     does; clause5_check.py holds C == model over
                     112,372 per-element comparisons - all four
                     formats, all five attributes, the 16-pair
                     conversion matrix, chunk-crossing batches, and
                     the fp256 max-normal/min-subnormal remainder
                     (the ~786k-step walk), flags compared exactly

Design choices pinned into the contract on the way (DETERMINISM.md):
the RISC-V FCVT table for convertToInteger's invalid deliveries,
RISC-V fclass indices for class, the 5.10 order-embedding for
totalOrder, remainder consuming no rounding attribute because it
never rounds. The named roundToIntegral variants signal nothing, per
the standard - the composed route's scaffolding inexact is discarded
by the same flag discipline cft_div established.

The one model change beyond additions: _round_at became total in
memory as well as math (a scaleB shift of a billion no longer
materialises a mask that size), pinned by the same rational
reference. verify/run.sh gained a clause5 stage. MPFR and CPU-oracle
extensions for the new set are running; their numbers get their own
entry when they land.

## 2026-09-01 - the adversarial pair reports on the completion set

Two independent reviewers, per house practice, both required to
reproduce before reporting.

The NUMERICS reviewer ran ~3 million adversarial checks against
oracles sharing no code with the model - a Fraction-based 754
reference derived from the standard's own rules, CPython natives, a
rule-by-rule 5.10 restatement - including EXHAUSTIVE sweeps on three
toy formats (every encoding x mode x variant, all-pairs for binary
ops) with ladder reproduction required for any hit. Verdict: ZERO
contract bugs. It also confirmed the fp256->fp32 double-rounding trap
family is discriminating (the two-step route diverges on 1,200
constructed midpoint traps; the direct path passes all), and that the
staged-scaleB saturation delivers identical bits under the directed
attributes specifically. Findings: one DETERMINISM.md wording error
(the -0 edge of nextUp belongs to the negative subnormal of least
magnitude, not "most negative") and two loose comments - all fixed.

The ENGINEERING reviewer ran 28,973 C checks (aliasing differentials,
chunk equivalence, guard canaries, validation matrix) plus 22,272
model differentials, and found the day's one real bug: F1, the
internal "no rounding attribute" sentinel value -1 was accepted from
the PUBLIC API by ten entry points, computing under a chimera rounding
(increment rule from one default branch, overflow delivery from
another) that no legal attribute produces. Fixed by removing the
sentinel from the shared validator entirely - the operations that
consume an attribute now range-check it themselves - with a refusal
matrix in both the harness and api-test as regression. Also fixed on
its evidence: the "full-gap fp256 remainder" directed case actually
exited early (power-of-two divisor; the true full-gap walk needs an
odd significand and runs ~524.5k steps, not the ~786k two comments
claimed - both corrected, and the per-LANE cost stated honestly);
integer conversions now load/store the caller's arrays through their
declared native types instead of little-endian bytes (a silent
byte-swap on any big-endian host, plus an implementation-defined
cast, both gone); the integer-side size guard; and its test-gap list
- 32-bit conversion randoms that never landed in range, the
2^28..2^70 boundary window structurally unreachable at fp128/fp256,
host ops never batched, aliasing promised in a comment but tested
nowhere - all closed. clause5_check.py now runs 142,920 comparisons
(was 112,372), C == model on every one; api-test carries the
refusals, the hand-derived edges, and in-place-equals-separate for
the composed ops. Everything else it attacked held: aliasing, UB,
bn preconditions, the rem parity argument, the cvt_to cutoff,
validation parity with cft_div, chunking, memory.

## 2026-09-01 - MPFR reaches the rest of clause 5

host/tools/mpfr_check.c grew ~1,200 lines and the only external
oracle that reaches binary128/256 now covers the completion set:
rint (all five attributes + the Exact variant), scaleB across every
n regime including the emin-p host-path boundary and the INT64
extremes, all 16 convert pairs with destination-grid tie families,
the eight integer conversions (MPFR in range; the invalid deliveries
hardcoded from the contract's RISC-V table, which is the contract's
own choice and says so), logB, nextUp/nextDown - the grid-quantized
mpfr_nextabove reproduces the standard's -0 and saturation edges
from the machinery rather than special cases - and remainder with
exactness asserted from MPFR's own ternary. class/totalOrder/the
signaling compares are deliberately absent: MPFR has no independent
notion of them, and an oracle that restates the encoding walk would
be the harness testing itself.

Two campaigns, zero mismatches, values AND flags: 24,900,800 cases
each (4,356,800 on the new operations; the old div/sqrt-era checks
ran alongside and stayed green), once at a398a6b and again at
6ffffc4 after the review-round hardening landed mid-task. The same
harness prints an identical 238,328-case ledger on Windows/mingw64
and Linux. And because a zero-on-first-contact harness proves
nothing by itself, its convicting power was demonstrated before
being believed: deliberate mutations (a wrong RDN mapping, flipped
zero-signs, a swapped NaN delivery) fired 2,282 and 696 mismatches
respectively, then were reverted and the clean build rerun green.
No harness bugs this time - and no library bugs.

Environment note for reproducibility: amd-arc-box carried no MPFR
dev packages, so GMP 6.3.0 + MPFR 4.2.2 were built from SHA-verified
GNU sources into a prefix under ~/c5-mpfr (both upstream test suites
green), static-linked, nothing installed system-wide.

The clause-5 completion set now stands where div/sqrt stands: model
tests, sequence parity, 142,920 C-vs-model checks, ~3M adversarial
review checks, 24.9M MPFR cases at all four formats - and the
CPU-hardware soak's 285M-case quick campaign green with its 38.7B
exhaustive fp32 campaign running.

## 2026-09-01 - the review's instruments become standing gates

Retained from the adversarial round, per Logan's call, so the
one-shot attack becomes recurring coverage: ref754.py (the
independent Fraction oracle, deliberately outside cft_golden),
test_tiny_formats.py (exhaustive 8-bit-format sweeps of every
clause-5 operation, every attribute, every PAIR through
remainder/totalOrder/the signaling compares - 29 seconds in pytest,
and its port immediately re-caught the e5m2 logb ladder-scope assert
the review had found, which is the sign it has teeth), the
fp256->fp32 midpoint-trap family with its the-traps-must-catch-
something assertion, the totalOrder NaN zoo, and the remainder
torture set in clause5_check.py (now 145,032 comparisons, green).

The MPFR campaign's from-source recipe is now
verify/build-mpfr-oracle.sh: m4/GMP 6.3.0/MPFR 4.2.2 from pinned
SHA-256-verified GNU sources into a repo-local static prefix,
upstream suites run on the way, no root. Validated end-to-end on
amd-arc-box from a clean directory: fetch, hash-check, build, both
upstream test suites green, then mpfr-check built against the fresh
prefix and run - 100,736 cases, 0 value / 0 flag mismatches. The
verify runner's mpfr stage prefers the prefix over system packages,
and the same stage ran green locally through mingw64's system MPFR
(238,328 cases) in this machine's census, so both routes are proven.

## 2026-09-01 - the exhaustive CPU-hardware campaign closes clean

hw/run-c5-soak.sh, full depth, on amd-arc-box against pushed HEAD
6ffffc4: **40,658,293,642 cases, 0 value mismatches, 0 flag
mismatches**, all 618 shards ok, SOAK CLEAN. That includes EXHAUSTIVE
fp32 - every one of the 2^32 encodings - through roundToIntegral
under all five attributes (both the named variants and Exact),
nextUp, nextDown, logB and class, plus banded fp64 and the
integer-conversion, scaleB, convert and remainder campaigns, value
AND hardware-flag comparison behind directed probes that all read
RELIABLE on this box. The end-of-run negative control detected its
sabotaged run before the green was believed, per house rule. Worker
count self-throttled to 12 while the 135 MHz quad route held the
box; the campaign ran to completion beside it without touching it.

With this, every operation the clause-5 completion added stands on
the same four legs div/sqrt stood on: the golden model's own tests,
C-vs-model parity, GNU MPFR at all four formats, and the host CPU's
IEEE hardware at exhaustive-fp32 scale.

## 2026-09-01 - the 135 MHz card-day pair closes, verifies and stages

Both geometries at the decided clock, from the 39fc2c0 tree whose
rtl/ and hw/ are byte-identical to the general-purpose b1a014c:

    single @135  CLOSED  kernel_wns +0.255   verify-image 8/8
    quad   @135  CLOSED  kernel_wns +0.042   verify-image 8/8

staged to ~/cardday-135 with the copies re-hashed against the
manifests' build-time sha256 - byte-identical both. The quad number
is worth a sentence: +0.042 ns at 135 against +0.009 ns at 130. A
router handed a realistic target closed a HIGHER clock with MORE
slack, which is the "met-target slack is a stopping point, not a
capability statement" lesson from the ceiling bracket, observed now
in the favourable direction. CARDDAY.md's decision box is checked;
the fallback chain is 135 -> 130 general-purpose (~/cardday-ms) ->
bac9f550 -> 53bbba7.

## 2026-09-01 - correction: the single@147 attempt never ran

The ceiling-bracket entry above says a single @147 was "running to
pin the number". The box says otherwise: no build-147 directory
exists in any tree, so the launch died silently at startup - the
known nohup failure class - and the watcher that timed out today was
watching for a verdict that was never coming. It is NOT being
relaunched: the decision that matters ("135 for card day, high-speed
testing after first light") was made with the bracket's existing
numbers (~148 single from the 70 ps miss at 150), and a build to
sharpen 148 into 147-or-148 buys nothing the decision needs. The
bracket entry's claim stands corrected rather than quietly deleted,
because a ledger that edits its past is not a ledger.

With it, the box is fully idle for the first time in two days: the
135 pair staged, the soak complete, no builds in flight.

## 2026-09-01 - the orbit sequencer exists in RTL and matches its model

Pulled forward from v2 on Logan's open-core argument - a DDR- or
PCIe-fed tile cannot afford a memory pass per step, so the sequencer
is the architecture there, not a refinement. Built bench-first: the
unit bench (tb/test_seq_core.py, by the Opus review agent) was
written against the behavioural contract while the body was being
implemented, and validated so that against the refuse-everything stub
its refusal matrix PASSED and every compute case failed with a
labelled comparison rather than a hang.

That bench then earned its keep six times over before going green:

    1. an Icarus livelock - always_comb evaluating a function
       automatic freezes simulation time the moment its inputs
       change; the semantically identical assign form is immune
    2. its stale-data twin - a continuous assign's function call
       re-evaluates only when ARGUMENTS change, so functions reading
       db_rdata/dcnt through static scope shipped the whole drain
       stream one element behind itself; every function read is now
       an argument
    3. a parser that held rready while peeling, so the memory handed
       over beats the parser dropped - any image over one beat
       starved forever
    4. a one-cycle read-latency skew on every banked memory consumer
    5. a 6-bit self-determined shift that wrapped at lane position 2,
       making SETACT judge the wrong lane's magnitude - lanes
       survived or died on their neighbours' values
    6. a block capacity clamped at fp32's 128 lanes for every
       precision, overrunning the 16-beat register file (beat 16
       aliasing beat 0 through the 4-bit beat field) at every wider
       format and skipping lane 64 outright

plus the structural round the first draft already paid: the beat-0
writeback that retires DURING the last issue cycles when NBEATS >
LATENCY, single-site B-response accounting, and the banked register
file itself (a byte-enable loop over a 256-bit word made yosys
flatten 8 KiB of BRAM into 130k registers; word enables ARE lane
enables here).

The verdicts, all green on 2026-09-01:

    tb/test_seq_core.py    9/9 suites - all four formats, single-op
                           through nested escape maps, ragged blocks,
                           deposition incl. overflow and the legal
                           zero budget, 62 fuzz programs, the refusal
                           matrix with zero write traffic per refusal
    tb/test_krnl_seq.py    PASS - the whole kernel through the CSR as
                           XRT drives it (by the integration agent,
                           with kernel.xml's missing STATUS row fixed
                           and the XRT device path compile-checked on
                           cft2204)
    make sim (15 targets)  45/45 - the sequencer integration changed
                           nothing the existing suite measures
    yosys lint             PASS, .ok verified

One bench expectation was itself corrected: refuses_zero_max_deposits
asserted a refusal that contradicted the model, the docs, and the
RTL's own contract in four places; it is now zero_max_deposits_is_
legal, scoring an ACCEPTED run whose every deposit lands in STATUS[4].
The seq_core and krnlseq targets folded into make sim the same day,
per the aggregate's own rule. device-test gained -s: sequencer
programs device-vs-software, the driver for the hw_emu gate ahead.

Still between "benched" and CAPABILITIES' "yes": hw_emu through the
real XRT stack, a bitstream, silicon - in that order, next.

## div/sqrt as sequencer programs (2026-09-01)

The sequencer's first customer is the library itself: `cft_div` and
`cft_sqrt` now issue their whole composed sequence as ONE program on
program-capable devices - the identical steps, restated with the
restore loop's per-lane conditionals as branchless CMPLT/SELECT and
IADD/ISUB ulp steps - in place of ~25-30 elementwise round trips.
python/cft_golden/seqprogs.py specifies the programs (47-60
instructions, 6-9 derived constants, three deposits per lane);
divsqrt.c's program route is the port; routing is automatic on
hardware backends, falls back to the chunk route on bitstreams that
cannot run programs, and CFT_DIVSQRT_SEQ forces either route.

Evidence, all green on 2026-09-01:

    test_seqprogs.py       22 tests: the program route against the
                           contract, bits AND flags, four formats,
                           all five attributes, the named hard
                           families per element (exact-tie divisors,
                           binade crossings, negative divisors, the
                           sqrt midpoint fabrications), mixed-special
                           batches exercising lane filtering and
                           deposit indexing
    divsqrt_check.py x2    29,124 cases through the chunk route and
                           29,124 through the program route forced
                           over the software executor - zero
                           disagreements; `make divsqrttest` now runs
                           both, permanently
    make test / seqtest    unchanged and green with the route in the
                           library: 392,000-case replay, C-vs-Python
                           identity, 695-program sequencer fuzz

Pending: the same comparison through hw_emu's device executor - the
gate in flight predates this commit, so the NEXT emulation image is
the one whose compare_divsqrt exercises the program route on-device.

## 2026-09-01 - one ALU array, and the two bugs that cost

The sequencer shipped with a PRIVATE second copy of the lane array
(`cft_seq_lanes`), a v1 deviation its own header documented and its
bench was built against. Nothing scored the deviation at the kernel
until the sequencer-era tile was synthesised whole, and then it was not
close:

    tile, OOC @135 MHz, xcu50    LUT        note
    pre-sequencer                 98,310
    sequencer, private array     288,764    the copy is 124,057 of it
    quad link of that tile     1,316,831    of 871,680 - PLACER NOT RUN

`VPL UTLZ-1`, LUT-as-logic over-utilised: the quad did not fail
timing, it failed to exist. The array is now one `rtl/cft_lanes.sv`
that `cft_krnl` owns, driven by both engines through a per-issue
request under the `MODE[15]` select that already chose the AXI owner -
no arbitration, because the two never run at once. `OWN_LANES` keeps a
private instance for each module's unit bench.

    one shared array, ladders off     162,482    -0.065 ns
    + sequencer control diet          139,404    +0.307 ns
    + fused ladders on                123,599    +0.097 ns

**The diet.** `cft_seq`'s address arithmetic multiplied by `esz` and
`max_deposits` and landed in DSP columns, owning the kernel's critical
path. Every multiply is by a power of two, so they became shifts; the
variable part-selects into the packed lane-state and deposit-count
vectors became loops over constant indices. cft_seq went 15 DSP -> 0,
49,657 -> 26,586 LUT in-kernel, and its worst path -0.065 -> +4.268 ns.
Simulation times identical to the picosecond at every step, which is
the cheap proof that no cycle moved. The largest single item was not
the one predicted: the variable part-select on the WRITE side of the
deposit counters was 8,064 of 14,887 logic LUTs and became 229, because
synthesis must decide per bit of an 896-bit vector whether the write
window covers it. Recorded negative result: splitting that index
arithmetic - the obvious fix - bought only -2,116; the construct was
the cost, not the parenthesisation.

**Then the shell said no, and it was our bug.** A single tile linked at
135 MHz with the ladders on missed at **WNS -0.577 ns, 776 failing
endpoints**, and the worst path was not the ladder:

    u_engine/u_reduce/dly_lvl_reg[14][0]
      -> u_lanes/g_lane32[0].u_fma/s0_byp_d_reg[15]   25 levels, DSP

While the reduction accumulator fed lane 0 of a PRIVATE array its
operands went straight to the pipe's `a`/`c` ports, past `cft_opmux`
(a passthrough for FMA) and past `cft_simpleops` entirely. Putting both
engines on one operand bus put the accumulator's combinational output
onto the bus that also feeds `cft_simpleops` - and `cft_fpfma_pipe`
latches that block's result into `s0_byp_d` UNCONDITIONALLY, no clock
enable - so every reduction operand crossed the accumulator's level
decode, its memory read and the whole simpleops mux tree in one cycle.
Out of context the same path read **+0.307** and hid.

One register on the accumulator's operands, with `cft_reduce_acc` told
`ADD_LATENCY = LATENCY + 1` so the destination level still arrives with
its sum (`dly_lvl[ADD_LATENCY-1]` is that module's stated contract),
makes the reduce path structurally the elementwise path that already
closes. Not a numeric change: the tree shape and the order of every add
are fixed by element index, never by timing.

**Two lessons, both paid for.** Out-of-context slack hid a cross-module
path - +0.307 became -0.577, a 0.88 ns swing, because OOC places the
kernel alone and the shell places it as one compute unit among many.
And sharing a datapath means sharing everything attached to it: the
win was real (-126k LUT) but the operand bus carried the accumulator
into a combinational block it had never touched, which is not something
an area argument surfaces.

**The ladders go back off.** 123,599 LUT against 139,404 - about 75% of
the device for a quad against 80% - but +0.097 ns OOC does not survive
the shell, and five points of area is not worth a bitstream that does
not close. They stay proven bit-exact and parameterised for a slower
clock or the smaller open-core part.

**Evidence on the final tree (8f5f149):**

    seq_core      9/9      krnlfused   2/2 (ladders on)
    krnlseq       1/1      krnlplain   2/2 (ladders off)
    krnl          2/2      quarter     1/1
    reduce        3/3      faults      4/4
    reduceacc     5/5      golden      370 passed
    make yosys-lint clean; Verilator width gate clean

The width gate earned its keep: it is fatal-on-width here and caught
seven implicitly-sized sites in the diet's new shift arithmetic that
Icarus and yosys both accepted. All seven were correct by truncation
and are now explicit, so synthesis and every number above are
unchanged.

**Pending, and not to be read as done:** a single and a quad are
building at 135 MHz from this commit with the ladders off; the routed
result is not yet known. hw_emu was rebuilt from this commit and IS
executing the design - a reduction ran to completion through the real
XRT stack with correct flags - but two gate stages failed to START on
the stale-emulation-state race `hw/run-device-test.sh` documents, and
are being re-run. No bitstream has closed, and there is still no card.

## 2026-09-02 - the sequencer fails on the device, and the engine does not

The first emulation of the sequencer-era image through the real XRT
stack. The elementwise engine passed on that image - `fma ok: 12 checks
so far, 0 failed` at fp32, and an earlier campaign run reached 24 fp64
FMA checks with 0 failed - and a reduction ran to completion with
correct flags. **Every sequencer program failed:**

    FAIL seq fma+deposit:  run status disagrees (sw ok, hw memory
                           system fault: the output is not valid)
    FAIL seq interval:     ... hw memory system fault
    FAIL seq escape loop:  ... hw memory system fault
    FAIL seq zero-budget:  ... hw memory system fault
    sequencer programs: 16 checks so far, 4 failed

"Memory system fault" is STATUS[2:0] - the engine's bus-fault bits - so
the device is reporting that the sequencer's own AXI traffic did not
complete cleanly. The failure is total (four of four programs, every
shape from a single deposit to a nested escape map) and it is isolated
to the sequencer: same image, same run, same masters, the elementwise
path is clean.

What has been ruled out already, by reading rather than guessing:

  * NOT the HBM bank binding. hw/kernel.xml puts `prog` (arg 6) on
    m_axi_a and `cnt` (arg 7) on m_axi_d, and hw/link.cfg binds those
    ports to HBM[0] and HBM[3]; verify-image confirms 4 masters, no
    channel shared.
  * NOT unbound arguments. cftx_program_run passes all eight in order,
    tile.pg and tile.cn included.
  * NOT the 4 KB burst rule. cft_seq's burst_len() clamps to
    (4096 - addr[11:0]) >> 5 exactly as the engine's does.

What this says about the benches: `seq_core` and `krnlseq` are green and
have been for a day, against cocotbext-axi's AxiRam. The device is
enforcing something that model does not - the classic shape of an
integration bug, and the reason the emulation gate exists at all. The
cocotb benches proved the sequencer's SEMANTICS against seq.py; they
never proved its bus behaviour against an interconnect that pushes back.

Evidence lost and being re-collected: run-device-test.sh keeps one
generation of .run, and the reductions gate overwrote the sequencer's
simulate.log before it was read. A sequencer-only re-run that snapshots
its own trace is queued.

**Status change.** The sequencer's row has read "benched - hw_emu
pending" since 2026-09-01. hw_emu has now run, and it fails. Until this
is root-caused the honest reading is: bit-exact against its model in
simulation, and NOT working on a device.

## 2026-09-02 - the sequencer passes on a device

The bank fix, through the same gate that condemned it this morning:

    before (8f5f149)   sequencer programs: 16 checks so far, 4 failed
                       FAIL seq fma+deposit / interval / escape loop /
                       zero-budget - all "hw memory system fault"
    after  (40149b1)   sequencer programs: 28 checks so far, 0 failed

Same image pipeline, same gate, same XRT stack; the only difference is
that cft_seq now says which buffer each read belongs to and cft_krnl
steers the request at the master that owns that bank. fp32 completed
its whole program set - every shape from one fma+deposit to the nested
escape map to the zero-deposit refusal - and the run had moved on to
fp64 when the 90-minute emulation cap stopped it.

**What this does and does not establish.** It establishes that the
sequencer's reads now reach the right memory on a banked device, which
is what failed before, and that all four program shapes execute
correctly at fp32 against the software backend. It does NOT establish
fp64/fp128/fp256 on a device (the cap cut fp64 short), and emulation is
not silicon.

The simulation-side proof arrived first and is the more reusable one:
tb/test_krnl_seq_banks.py gives each master a private store and checks
r0/r1/r2 arrive from A, B and C. Sabotaged back to the old routing it
fails on lane 0 with "operand b did not come from the B master" - 1.0
where 2.0 belonged - so the bench refutes rather than decorates, and it
runs in ninety seconds where this gate takes ninety minutes.

**An instrumentation gap this exposed, worth closing before the card.**
cft_engine_stream carries eight $display statements and narrates itself
through a run - START, each AR, RED, DONE - which is how the reduction
was confirmed working on 2026-09-01 from the trace alone. cft_seq has
ZERO. During a sequencer run the simulator log goes silent, so "stuck
or merely slow" cost an hour of guessing tonight and would cost more on
a card, where the only observable is pass or fail.

## 2026-09-02 - standardized verification runs on the shared-lanes tip, both platforms

Two censuses, one per platform, on the tree that carries the shared
ALU array, the sequencer's bank fix, retiming in the build flow, the
seed ROM as case tables and the layout catalogue. Each is quoted as
the runner printed it; the paragraphs after say what the first
attempts found, because three of the four things they found were
defects in the census machinery itself and one was real.

**Windows (Git Bash + Docker Desktop), the full standard set:**

    ## 2026-09-02 - standardized verification run (DESKTOP-T33SK86)

    verify/run.sh at b6aeccd: 15 stage(s) executed, 2 cached from earlier in the run, 0 failed, 1 skipped.
    Run id 20260902-120454-b6aeccd; per-stage logs under verify/state/.

    golden ok 166s | vectors ok 7s | sim ok 591s | lint ok 44s | formal ok 27s
    libcft ok 12s | selfcheck ok 1s | divsqrt ok 1s | clause5 ok 3s | diff ok 4s
    seq ok 2s | reduce ok 23s | bindings ok 2s | mpfr ok 5s | soak-quick ok 106s
    images SKIP (xclbinutil not present)

**Linux (WSL cft2204, its own clone), the host and model stages:**

    ## 2026-09-02 - standardized verification run (DESKTOP-T33SK86)

    verify/run.sh at 1515bae: 12 stage(s) executed, 0 cached from earlier in the run, 0 failed, 4 skipped.
    Run id 20260902-122143-1515bae; per-stage logs under verify/state/.

    golden ok 224s | vectors ok 4s | sim/lint/formal SKIP (docker not usable on this host)
    libcft ok 5s | selfcheck ok 1s | divsqrt ok 0s | clause5 ok 3s | diff ok 2s
    seq ok 1s | reduce ok 14s | bindings ok 1s | mpfr ok 3s | soak-quick ok 94s
    images SKIP (xclbinutil not present)

One label needs a footnote. The Windows run's id names b6aeccd, the
commit the tree was at when it started; by the time its `bindings`
stage ran, the working tree also held the three binding fixes below,
committed minutes later as b694a3f, 8c347fd and 1515bae. On gmpy2
2.2.1 the stage passes either way, so the result is not in question -
but a census that says one commit and tested another is the kind of
thing this file exists to say out loud. The Linux run is at 1515bae
throughout.

**What the first attempts found.**

*A Windows run at 0e7264e passed golden, vectors, the full sim suite,
lint and formal, then failed libcft in 0 s and every host-binary stage
after it in 1-3 s - ten FAILs.* The link errors (`undefined reference
to cft_open`, glibc's `__snprintf_chk`) read like a source defect.
`objdump -f` said otherwise: libcft.a and every object under host/src
were elf64-x86-64, left by a WSL build of the same checkout through
/mnt/c at 01:01, and Windows make took them as up to date. After
`make clean` the native build links cft.dll and the test target passes
- 392,000 conformance cases, C and Python the same bits. The runner's
libcft stage now cleans first (fb2463a); a census that depends on
which platform touched the tree last is not a census. Two Linux
executables that had been committed as build products, and that the
clean deletes, are untracked and ignored (b6aeccd).

*A Linux run at 0e7264e failed sim, lint and formal in 0 s each.* The
WSL distro has Docker Desktop's shim on PATH without the integration
enabled, and `command -v docker` is satisfied by a program whose only
output is how to enable it. `need docker` now asks whether docker
works, so the three stages skip by name, as above.

*The same Linux run failed `bindings` at every precision, and that one
was real.* `test_str_roundtrip` took -0 to "-0" and back to +0. Not the
library and not the codec: gmpy2 2.1.2 (MPFR 4.1.0) parses "-0" inside
the ieee() context the binding rounds in to a zero with no sign, and
from_mpfr takes the sign from is_signed. The same version refuses
every spelling of inf and nan ("invalid digits"), trailing whitespace,
and "+0" - all of which to_str can emit and 2.2.1 accepts, which is
why the Windows host had never seen any of it. from_str now takes the
sign of a zero result from the decimal (754: rounding never changes a
sign, so a negative decimal that is zero or underflows to zero is -0
in every attribute), lexes the special tokens itself (a token is
recognised, never rounded), strips whitespace and a leading plus, and
still hands a minus to MPFR with the digits because directed rounding
is not sign-symmetric. Two tests pin it at every precision. The
binding suite: 77 of 77 on gmpy2 2.2.1, 77 of 77 on 2.1.2.

The Linux clone also carried a stale XRT-flavoured libcft.a from an
earlier `XRT=1` build, which the clean-first stage removes, and
untracked emulation build directories and a card-day staging copy
that made the runner refuse to certify; those were moved aside, not
deleted, and the clean run above followed.

## 2026-09-02 - the retimed quad at 135 MHz misses in the shell

    build-quad-135r  40149b1 + bank fix, four tiles, 135 MHz, RETIMING=1
    routed WNS -0.141  TNS -45.890  failing endpoints 836  (no xclbin)
    the same design without retiming: -0.113 / -22.993 / 463

Retiming's +1.374 ns out of context (docs/ROADMAP.md) did not survive
four tiles in the shell; it was slightly worse. Post-place both builds
read +0.055 and both lost the margin in routing, which is wire, not
logic. The worst paths are the seed-ROM DSP cloud (6 of 10), the S10->
S11 normalise (3) and the S12->S13 round (1). The next quad is from
the tip - case-table ROM, retiming, phys_opt - at 135, then 130 if it
misses.

## 2026-09-02 - the round stage's precompute, gated

rtl/cft_fpfma_pipe.sv at 9f73107: K, the round window's shift, q and
both tininess compares computed in S12; the window extracted with a
(P+2)-bit shifter. The gate, run under Verilator so the whole suite
compiled the changed file:

    make -k SIM=verilator sim   15 targets built, 43 tests, 43 passed, 0 failed
                                (fp32/fp64/fp128/fp256 unit benches, simpleops,
                                 normseg, normshare, seedop, reduceacc, reduce,
                                 krnl, faults, seq_core, krnlseq, seqbanks)
    make quarter                1/1 under Icarus (its default)
    make mulfrac SIM=verilator  4/4, mulshare 3/3 - after c8123b9
    make yosys-lint             clean
    OOC @135, retimed           129,708 -> 123,420 LUT, +2.126 -> +2.222 ns

Two Verilator-only findings from that run, neither caused by the
change: mulfrac/mulshare had never built under Verilator (SELRANGE on
dead-arm constant slices; fixed in c8123b9 by clamping the offsets),
and `quarter` stops Verilator with an internal error on the reduce
serialiser's fp128 arm at BEAT_BITS=64 - identical on the pristine
tip, fine under Icarus, recorded in docs/ROADMAP.md.

## 2026-09-02 - the case-ROM single closes at 135 MHz with +0.433 in the kernel

    build-single-135r-rom   0e7264e (seed ROM as case tables), one tile,
                            135 MHz, RETIMING=1, hw/link.cfg
    routed WNS +0.055 (whole design: the shell's free-running clock,
                       the same figure every single build reports)
    kernel worst path  +0.433 ns  s12_enorm_reg -> s13_kept_r_reg, 19 levels
    xclbin              35,701,603 bytes, manifest clean, sources == commit

The same tree one commit earlier closed the same clock at +0.045; the
ROM change bought +0.39 ns in the shell against +0.445 out of context.
The worst kernel paths are all S12->S13 now, which 9f73107 moves up a
stage; the seed-ROM family does not appear. This image is a candidate
single for card day pending hw/verify-image.sh and a matching quad.

## 2026-09-02 - the cocotb suite in parallel on the 36-core box

`make -k SIM=verilator sim` at 9f73107 on amd-arc-box, the whole suite
under Verilator, run twice back to back by an ad-hoc script on the
build box that was not committed:

    serial   (-j1)    wall 1522 s    17 targets, 50 tests, 50 passed
    parallel (-j12)   wall   57 s    17 targets, 50 tests, 50 passed

Read carefully, because the two numbers do not measure the same thing.
The serial pass compiled every Verilator model from nothing and then
simulated; the parallel pass found those models already built under
tb/sim_build/ and simulated them twelve at a time. So 57 s is what the
suite's SIMULATION costs on that box once the models exist, and most
of the 1522 s was compilation - eighteen targets, eight of which
compile the identical full kernel. A cold `-j12` run, which would
parallelise the compiles too, was not taken because the box had
already been claimed by the next quad; the honest expectation is a few
minutes. De-duplicating the kernel compiles (one model, eight benches)
is the larger lever for cold runs and is recorded as such.

Both passes report `rc=2` with every test passing: the eighteenth
target, `quarter`, stops Verilator with the internal error recorded on
2026-09-02 (cft_engine_stream.sv's reduce serialiser at BEAT_BITS=64)
and produces no result under it. It passes under Icarus, its default.
Closed later the same evening - the arm's slice is clipped to the
beat at elaboration - so a rerun of this benchmark would build all
eighteen and return rc=0.

It did. The cold run, taken at 19:47 once the box's quad had finished,
at 7619f70 (the same RTL plus the quarter closure), from an empty
tb/sim_build each time:

    cold   (-j12)    wall  185 s    18 targets, 51 tests, 51 passed, rc=0
    warm   (-j12)    wall   56 s    18 targets, 51 tests, 51 passed, rc=0
    cold   (-j18)    wall  166 s    18 targets, 51 tests, 51 passed, rc=0

Three minutes for the whole suite from nothing against twenty-five for
the serial pass: the compiles parallelise as well as the simulations
did, and the eighteenth target - quarter, at BEAT_BITS=64 - builds
under Verilator now and adds its test to the count. The eighteenth
job buys 19 s over twelve, which says where the floor is: at one job
per target the wall is one full-kernel compile plus its bench, so
de-duplicating the eight identical kernel compiles now saves CPU time
on this box rather than wall time, and stays the lever wherever the
suite runs serially - the CI runner included. 44 GB free at the start
of each cold pass, 42 before the warm one; nothing was guarded or
killed.

The runner's own path, checked the same evening on the box:
`SIM_JOBS=12 bash verify/run.sh --only sim` at 617c35a, PASS in 327 s
under the container's Icarus - the suite's default simulator, ~40 min
serial - run id 20260902-195817-617c35a. That clone carried an
untracked build directory, so the runner marked its report dirty as it
should; the run certifies the knob, not the tree.

The same day, `make -C host examples-lang` under MSYS2 make on the
Windows host: rust and csharp same bits as the C example; julia, go
and R skipped by name for want of toolchains. The C# leg had been
failing on that host in a way that read as a bit mismatch - dotnet
missing the profile and PROGRAMFILES variables that MSYS make does not
pass to recipes - and now names a failed `dotnet run` as what it is.

## 2026-09-02 - the tip quad closes at 135 MHz: kernel +0.143, 0 failing endpoints

    build-quad-tip-135   9f73107, four tiles, 135 MHz, RETIMING=1 PHYS_OPT=1
    host                 DESKTOP-T33SK86 (WSL cft2204, 12 cores, 47 GB VM), 5h27m
    routed WNS +0.018    TNS 0.000   failing endpoints 0 of 1,028,763   WHS +0.009
    kernel worst path    +0.143 ns   g_bank128 lane 0, s10_mag -> s11_valw (LZC + coarse normalise)
    xclbin               51,286,320 bytes, sha256 fef73969...d1a55, manifest clean,
                         sources == commit, hw/verify-image.sh 8/8
    router trajectory    place +0.055 -> iter 0 -0.446 -> iter 1 +0.018 -> iter 2 +0.018 (met, stopped)
    second host          the box, same tree and flags, its own Vitis 2022.2: finished 19:39,
                         +0.018 / WHS +0.009 / 0 failing, verify-image 8/8,
                         xclbin 51,286,329 bytes, sha256 86ef3739...b5e7d;
                         BITSTREAM sections byte-identical after the .bit header

Against the two quads at 135 that missed (-0.113 unretimed, -0.141
retimed, both 463-836 failing endpoints), the difference is the tree:
the seed ROM as case tables (-11k LUT a tile, the DSP family gone),
the round stage's arithmetic in S12 (-6k LUT a tile, that family
gone), and the sequencer's bank fix. Staged as the quad half of the
card-day pair.

The box's copy of the same build - same tree, same flags, its own Vitis
2022.2, 26 minutes behind the desktop's - finished at 19:39 with the
same numbers to the picosecond (routed +0.018, hold +0.009, 0 failing of
1,028,763) and the same bitstream: the two BITSTREAM sections are
51,199,968 bytes each and differ in three bytes, all in the .bit
header's timestamp; the xclbin hashes differ only through that, the
xclbin UUID and the v++ install path in the build metadata (the box's is
86ef3739...b5e7d, 51,286,329 bytes, verify-image 8/8). Vivado's
determinism measured across two hosts rather than assumed: either image
is the card-day quad, and ~/cardday-tip/REPRODUCED.txt on the box holds
both hashes and the section hash.

## 2026-09-02 - the language stages: first runs on three hosts and CI

verify/run.sh gained one stage per language (cpp, lang-cpp, lang-rust,
lang-julia, lang-go, lang-csharp, lang-r, lang-fortran, node, wasm),
its stage list is read from its own `stage` calls, and gates.yml
gained a `host` job that runs the language stages under
--require-all. docs/COMPATIBILITY.md has the per-stage grid; the
runs:

    desktop WSL   20260902-202118-8c626a5   9 executed, 0 failed, 4 skipped by name            PASS
    box           20260902-202115-8c626a5   5 executed, 1 FAILED (bindings: no pytest, 0 s), 8 skipped
    box           20260902-202359-efff78e   5 executed, 0 failed, 8 skipped by name            PASS
    Windows       20260902-202124-8c626a5   9 stages ok through node (279 s), then run.sh was edited
                                            under the run and it broke at the next stage line
    Windows       20260902-202756-efff78e   9 executed, 0 failed, 4 skipped by name (node 272 s, wasm 3 s)   PASS
    CI host job   8c626a5 green in 3m19s; efff78e green in 3m30s (node 126 s, wasm 3 s, every selected stage ok)

Numbers worth keeping. The cpp stage replays 392,000 cases through
the wrapper at both standards - the vectors stage regenerates all
five attributes first, and the 236,000 quoted for cpptest earlier
was the older vectors/out. The Node replay of the same 392,000 cases
takes 4 s; the binding's 43 unit tests take 272 s on the
Windows host and 126 s on ubuntu, a gap measured here and not
yet explained. The box's bindings stage passed 80 tests against gmpy2
2.3.1, a release newer than the 2.1.2 and 2.2.1 the binding was
written against.

## 2026-09-02 - the tip single closes at 135 MHz: kernel +0.618, the pair is one tree

    build-single-tip-135  9f73107, one tile, 135 MHz, RETIMING=1 PHYS_OPT=1
    host                  DESKTOP-T33SK86 (WSL cft2204), 1h32m, beside the language runs
    routed WNS +0.055     TNS 0.000   failing endpoints 0 of 572,783   WHS +0.009
    kernel worst path     +0.618 ns   op_r -> g_bank128 lane 1 s0_byp_d (seedop bypass, 15 levels)
    xclbin                35,805,116 bytes, sha256 afc483e2...dfda4, manifest clean,
                          hw/verify-image.sh 8/8, staged as ~/cardday-tip/cft_hw_single.xclbin

Against the case-ROM single from 0e7264e (kernel +0.433), the round
stage's precompute buys another 0.19 ns on the single tile, and the
worst path is the seedop bypass family again - the one the quad also
shows nothing of at +0.143, because in four tiles it is placement and
routing that set the margin, not logic depth. The card-day pair is
now single and quad from one commit.

## 2026-09-02 - the first census with nothing skipped: 26 of 26 on the desktop's WSL

verify/run.sh at 47f4fbd on DESKTOP-T33SK86's WSL (Ubuntu 22.04, 12
cores), every stage in the standard set executed and passed, images
included. The desktop was given every toolchain the stages want that
evening (docs/COMPATIBILITY.md has the recipe), and XRT's xclbinutil
is there, so this is the one host where the whole set can run:

    golden 260s   vectors 6s    sim 602s (SIM_JOBS=8, Icarus)   lint 91s
    formal 41s    libcft 8s     selfcheck 0s   divsqrt 1s    clause5 2s
    diff 3s       seq 1s        reduce 20s     bindings 0s   cpp 15s
    lang-cpp 1s   lang-rust 0s  lang-julia 1s  lang-go 0s    lang-csharp 5s
    lang-r 9s     lang-fortran 0s   node 105s  wasm 2s       mpfr 4s
    soak-quick 114s   images 3s (both 9f73107 images, 8/8 each)

    VERDICT: PASS, nothing skipped - 26 executed, 0 failed, 0 skipped
    Run id 20260902-205134-47f4fbd; 22 minutes wall, with Vivado's
    single build finishing beside it.

The seconds are honest. The stages that read 0 or 1 s print their
counts in their logs - the bindings' 80 tests, selfcheck's "agree on
every case, bits and flags", divsqrt's 29,124 cases, clause5's 145,032
comparisons, seq/diff/reduce agreeing on every program, case and tree,
formal's 7 of 7 with the negative control refuted, mpfr's 238,328 cases
with 0 mismatches - and a stage the runner marks ok is one whose
command exited 0 after printing that.

The Windows host, same evening, at f5a9176 - everything but images,
which Windows can never run because xclbinutil is Linux-only - through
Docker Desktop for the three container stages, SIM_JOBS=8:

    golden 215s   vectors 7s    sim 502s       lint 59s      formal 37s
    libcft 15s    selfcheck 1s  divsqrt 1s     clause5 4s    diff 4s
    seq 2s        reduce 25s    bindings 1s    cpp 19s       lang-cpp 2s
    lang-rust 1s  lang-julia 2s lang-go 1s     lang-csharp 6s   lang-r 9s
    lang-fortran 0s   node 264s   wasm 3s      mpfr 4s       soak-quick 79s
    images SKIP (xclbinutil not present - XRT hosts only)

    VERDICT: PASS with 1 skip - 25 executed, 0 failed, 1 skipped by name
    Run id 20260902-205823-f5a9176; 21 minutes wall.

Two hosts, two operating systems, one tree, the same 25 verdicts; the
26th runs where the tool exists. The Node unit tests remain the one
stage that is slower on Windows (264 s against 105 s), still measured
and still unexplained.

---

## 2026-09-02 - the phase-1 transcendentals (ABI 0.3), commissioned

Nine new library entry points - `cft_exp`, `cft_expm1`, `cft_exp2`,
`cft_log`, `cft_log1p`, `cft_log2`, `cft_log10`, `cft_pow`,
`cft_hypot` - correctly rounded at all four formats under all five
rounding attributes, with IEEE 754-2019 clause 9.2.1's special values
and the contract's exact flags. Zero RTL. docs/TRANSCENDENTALS.md is
the design, its proofs and its honest gaps.

What was run, on DESKTOP-T33SK86 (Windows 11, mingw64 gcc 16.1, MPFR
4.2.1, CPython 3.12):

| check | count | result |
|---|---|---|
| `python/tests/test_transcend.py` - the model's own suite | 389 tests | pass |
| `python/tests/test_mp_consts.py` - the generated constants | 3 tests | pass |
| `host/tests/transcend_check.py` - the C against the model, per element for exact flags plus batch calls | 77,315 comparisons | C == model on every one, bits and flags |
| the same, with the library forced to START below the precision it needs, against an unescalated model | 72,275 comparisons | identical results through the escalation path |
| `cft_conformance` replay of the new sets | 64,325 cases in 20 sets (part of 456,325 in 40) | every case, bits and flags |
| MPFR parity, the nine functions, four formats, five attributes | 95,680 cases (part of 334,008) | **zero value mismatches, zero flag mismatches** |
| `cft.hpp` against `cft.h`, every entry point twice | 3,267 checks at C++17 and again at C++20 | identical encodings and flags |
| the cftmpfr drop-in against gmpy2's IEEE emulation | 268 tests | bit-for-bit at every precision and attribute MPFR has |
| `api-test` contract checks | all | pass |

MPFR is not the third oracle here but the ONLY one. libm is neither
correctly rounded nor reproducible, so unlike div and sqrt there is no
CPU campaign at fp32/fp64 to calibrate the harness against; agreement
with MPFR is the entire external case. The signaling-NaN rows are the
documented one-sided help - MPFR has none - and divideByZero comes from
operand classes, as everywhere else in that harness.

**Escalation, measured.** Over the MPFR campaign's 95,680 elements,
15,350 reached the Ziv loop and it escalated **zero** times: every one
was decided at the first attempt, 2p+40 bits. Over
`transcend_check.py`'s pools the model escalated 36 times, all of them
the `pow(1+u, -(1+u))` family, and the deepest working precision any
input needed was **832 bits - the fp256 cap itself**, for that family.
2,605 elements were decided exactly and 39,620 by a neighbour's side
rather than by any precision at all.

Because a path never taken is a path never tested, the `transcend`
stage runs the sweep twice, the second time with the C forced to start
at 64 bits. That run drives **6,542 escalations** and finds the same
answers as an unescalated model over 72,275 comparisons.

**Two defects the escalation run found**, both in code that the
contract's own working precisions never reach:

- the evaluator's error bound was destroyed rather than widened by an
  EXACT cancellation of two inexact approximations, because zero has no
  relative error to carry; `pow(1 + 2^-112, 1 + 2^-112)` at fp128 then
  returned exactly 1 from a degenerate enclosure the loop believed.
  `cft_mp_add` now hands back a saturated bound instead;
- a result that came out exactly zero because the precision was too
  coarse returned `CFT_ERR_INTERNAL` where it should have escalated.

**One defect in the reference's arbiter.** mpmath's interval context is
documented as rigorous and is not, quite: at 514 bits
`iv.power(1 + 2^-236, -(1 + 2^-236))` returns a DEGENERATE interval
that excludes the true value by 2^-709, costing the last bit of that
`pow` under roundTowardPositive. The model now moves every endpoint
outward by 256 units of the working precision before believing it. The
C - whose error bound is derived and checked rather than inherited -
had the right answer throughout, which is the argument for having two
implementations rather than one.

**Negative control**, run and restored the same day. Inverting one
character - the SIDE of the neighbour rule's witness in
`round_neighbour` - is caught by:

- `transcend_check.py`, on its first neighbour case (`fp64 exp rtz`,
  the smallest subnormal: `0x3fefffffffffffff` where the model says
  `0x3ff0000000000000`);
- the conformance replay, at `fp32-transcend-rtz.jsonl:2`;
- MPFR parity, with mismatches from the first `exp` row.

`api-test` did NOT catch it, because it had no case in that family at
all. Five went in - exp of the smallest subnormal to nearest and
upward, expm1 and log1p of it in the two directions that differ - and
with those it reports `api-test: 3 FAILED` against the same sabotage.
A gate that cannot fail is not a gate, and that is what the control is
for.

Standardized run, `bash verify/run.sh --only vectors,libcft,mpfr,transcend`
at 729d1ba, clean tree, run id 20260903-000408-729d1ba:

    vectors      ok      10s
    libcft       ok      58s
    transcend    ok      63s
    mpfr         ok      13s

    VERDICT: PASS, nothing skipped

The seconds are honest, and the stage logs carry the counts: libcft's
40 sets and 456,325 cases replayed twice each, transcend's 77,315 then
72,275 comparisons with the model's own escalation numbers printed
underneath, mpfr's 334,008 cases with the library's evaluator counters
(95,680 elements, 15,350 through the Ziv loop, 0 escalations, deepest
514 bits) after them.

The wasm artifacts were rebuilt the next morning, because leaving them
stale is not a documentation choice but a failing gate: both the page
verifier and the Node test assert the module's ABI against the tree's,
by design. `bash bindings/wasm/build.sh` against the pinned emsdk
6.0.9, with `--transcend 0` added to its generator arguments - the
emscripten image carries no mpmath, and the page samples the twenty
opcode sets by name anyway. The module now reports ABI 0.3 and the
`cft_conformance` inside it understands the new sets; no `cftw_*`
wrapper or page control exists for any of the nine, so no JavaScript
caller can invoke one, and docs/COMPATIBILITY.md says so in those
words. `bash verify/run.sh --only wasm,node`: PASS, nothing skipped.

What did NOT run, and why: the RTL, formal and container simulation
stages (nothing in this change touches them, and the transcendentals
issue no device pass at all); and the native-oracle soak, because there
is no CPU oracle for these functions - libm is neither correctly
rounded nor reproducible, which is the whole reason MPFR is the only
external arbiter here.

---

## 2026-09-03 - standardized verification run (DESKTOP-T33SK86)

verify/run.sh at fd717b0: 24 stage(s) executed, 0 cached from earlier
in the run, 0 failed, 3 skipped. Run id 20260903-003242-fd717b0;
per-stage logs under verify/state/.

The first full run with the transcendentals in it - every gate on this
host, including the RTL suite and the formal proofs, which this change
does not touch and which are here to show it did not touch them:

    golden 164s   vectors 10s   sim 1415s    lint 42s      formal 26s
    libcft 56s    selfcheck 1s  divsqrt 1s   clause5 2s    transcend 59s
    diff 3s       seq 2s        reduce 16s   bindings 4s   cpp 153s
    lang-cpp 1s   lang-rust 0s  lang-go 0s   lang-csharp 4s
    lang-fortran 1s   node 257s   wasm 2s    mpfr 13s      soak-quick 75s
    lang-julia   SKIP (no julia on PATH)
    lang-r       SKIP (no Rscript on PATH)
    images       SKIP (xclbinutil not present - XRT hosts only)

    VERDICT: PASS with 3 skips - 24 executed, 0 failed

`sim` at 1,415 s rather than the 502 s of 2026-09-02 is SIM_JOBS=1
against that run's 8, not a change in the suite. The three skips are
absent toolchains named by the runner, the same three this host has
always lacked.

The reviewer's gate on the merge, 2026-09-03 01:14 on the desktop with
every toolchain present: verify/run.sh at d469ba0, run id
20260903-011408-d469ba0, 26 stages executed, 0 failed, 1 skipped by
name (images: xclbinutil is Linux-only), PASS - the transcend stage
in 60 s, the conformance replay now 456,325 cases, mpfr 13 s over the
nine as well. The one review fix before the merge was a README bullet
that called the wasm page ABI 0.3 'surface included'; it reports 0.3
and carries no wrapper for the nine, and the bullet now says so.

---

## 2026-09-03 - the JavaScript surfaces reach the nine, and the half-step closes

This morning's rebuild left the wasm module reporting ABI 0.3 with no
`cftw_*` wrapper for any of the nine transcendentals: the arithmetic
was in (the build derives its source list from `host/Makefile`, so
`mpfloat.c` and `transcend.c` came along on their own) and no
JavaScript caller could reach it. docs/COMPATIBILITY.md called that
the half-step and said so in those words. This entry is what closed
it, and what was measured closing it. **No host source moved** -
`host/src`, `cft.h`, the vectors generator and the golden model are
untouched, which is why no arithmetic gate is re-run below.

What the surfaces gained:

| surface | before | after |
|---|---|---|
| `bindings/wasm/wasm_api.c` | 38 `cftw_*` wrappers | **47** - the nine added, one per declaration in cft.h, none with a `bus_out` the contract does not give them |
| the page's compute panel | opcodes + composed div/sqrt | + the nine, nine rows in the panel's own table |
| the page's drop zone | 20 opcode set names | + the 20 `<fmt>-transcend[-<rnd>].jsonl` names it had been refusing |
| `bindings/wasm/verify.mjs` | 4 checks | **5** - the fifth drives the wrappers themselves |
| `bindings/node` | clause-5 surface, 43 tests | + the nine on raw/Context-Float/`map`, **57 tests**, package 0.3.1 |

Measured on DESKTOP-T33SK86 (Windows 11, node 22.19.0, Docker Desktop
29.2.1, emsdk 6.0.9 pinned by tag and digest):

| check | count | result |
|---|---|---|
| build reproducibility, three clean container builds | `conformance.html` sha256 `30292f731a4b553d…`, wasm `6ff4129e03d43682…` | byte-identical all three times - two back to back, the third after the negative control was reverted |
| module size / exports | 88,875 bytes, 47 `cftw_*` | where the wrapperless 0.3 build was 88,541: the nine doors cost 334 bytes |
| `node bindings/wasm/verify.mjs`, `make vectors` sets | 300,325 cases over 40 sets via `cft_conformance`, then 64,325 through the nine wrappers | zero mismatches either way, 2 min |
| `node bindings/node/test.mjs` | 57 tests (43 + 14 new) | 0 failures |
| `node bindings/node/conformance.mjs`, `make vectors` sets | 236,000 in 1.6 s + 64,325 through `Context`'s own methods in 60.9 s = 300,325 over 40 sets | zero mismatches |
| `bash verify/run.sh --only vectors,node,wasm` at 9a5cfca, clean tree | vectors 10 s, node 317 s, wasm 128 s; 456,325 cases over 40 sets in each script's replay (the runner regenerates at the generator's defaults - 19,600 per opcode set, so 392,000 + 64,325) | **PASS, nothing skipped**. Run id 20260903-023112-9a5cfca, per-stage logs under `verify/state/` |

The commits after 9a5cfca in this change are prose and comments only -
a README wording fix, `verify.mjs`'s header count, one line of a Files
block - and change no line any stage executes; `git diff 9a5cfca` says
so.

**The negative control, and why it is the important line here.**
`cft_conformance` dispatches the nine internally, in C. It replayed
the transcendental sets happily on a module with no JavaScript surface
for them at all - that is precisely how the half-step passed every
gate this morning. So the new check had to be shown failing on the
thing the old one cannot see. `cftw_pow`'s two operand pointers were
swapped in `wasm_api.c` and the module rebuilt:

* `verify.mjs` step 5 fails all twenty transcendental sets at
  `fp32-transcend.jsonl:1543` - `pow(+0, +inf)` returns 1 where the
  vectors say +0 - and exits 1;
* its step 4, the `cft_conformance` replay, stays **green** through
  the same run: 300,325 cases, all matching;
* `test.mjs` fails 6 of 57 by name, the plainest being
  `pow(2,3): expected 8, got 9`;
* `conformance.mjs` fails all twenty transcendental sets.

Reverted, rebuilt, hashes reproduced.

**The page was opened in a browser**, which the two previous rebuilds
did not need to be: they could lean on `page_template.html` being
byte-identical to the version Chrome ran on 2026-09-01, and this
change edits the template. Chromium 148 on this host, the committed
`conformance.html` served over a loopback `http.server` (this
session's browser will not open a `file://` path). Section 1 read
*libcft ABI 0.3*; section 2 replayed the embedded sample green -
4,015 cases over 20 sets; section 3 accepted a drop of four
transcendental sets and one opcode set, **32,465 cases all matching**,
with a deliberately misnamed sixth file refused by name and the
verdict correctly downgraded to "not a full pass"; section 4's new
controls computed `exp(+0) = 1` with no flags, `exp(1) =
0x4005bf0a8b145769` inexact, `log(+0) = -inf` with divideByZero,
`pow(2,3) = 8` against `pow(3,2) = 9`, `hypot(3,4) = 5`, and
`log2(2^10) = 10` exactly at binary256 under roundTowardPositive.
`build/negative_control.html` was opened in the same browser and
failed red at `fp64.jsonl:2` with the library's own disagreement, so
the checker was watched failing here too.

What did NOT run, and why: every arithmetic gate below the bindings -
`golden`, `libcft`, `transcend`, `mpfr`, `diff`, the RTL suite, the
formal proofs, the soak - because this change adds no arithmetic and
touches no file any of them reads. The nine were already commissioned
on 2026-09-02 against MPFR (95,680 cases, zero value and zero flag
mismatches) and against the model (77,315 comparisons); nothing here
re-decides a bit. Also not run: any JavaScript runtime other than node
22.19.0 / V8 and Chromium 148, and any device backend - wasm32 has no
PCIe, and these are host operations besides.

A note for whoever reads the stage times next: `wasm` was 2 s before
this change and is 128 s now, and `node` moved from 257 s to 317 s.
Both differences are the transcendental passes - 64,325 correctly
rounded evaluations, a quarter of them at binary256, one `_malloc` per
scalar call across a wasm boundary. The cost buys the only check that
can see a broken wrapper, which this morning's module proved was
worth having.
## 2026-09-03 - the phase-2 trigonometrics, ABI 0.4

sinPi, cosPi, tanPi, asin, acos, atan, atan2, asinPi, acosPi, atanPi
and atan2Pi, correctly rounded at all four formats under all five
rounding attributes, with 754-2019 clause 9.2.1's special values and
the contract's exact flags - the half of clause 9's trigonometry whose
argument reduction is EXACT (`x mod 2` on a dyadic operand for the
forward Pi-variants; nothing at all for the inverses).
docs/TRANSCENDENTALS.md's phase-2 section is the design and its proofs.

Windows 11 (DESKTOP-T33SK86), mingw64 gcc 16.1.0, MPFR 4.2.2 as the C
oracle, CPython 3.12 with gmpy2 2.2.1 (which links its own MPFR 4.2.1),
2026-09-03.

| check | count | result |
|---|---|---|
| `python/tests/test_transcend.py` | 567 tests (was 389) | pass |
| `python/tests/test_mp_consts.py` | 4 tests (was 3) | pass |
| the whole `python/tests` suite | 941 tests, 1 skipped | pass |
| `host/tests/transcend_check.py` - the C against the model, per element for exact flags plus batch calls, over TWENTY functions | 154,269 comparisons | C == model on every one, bits and flags |
| the same, with the library forced to START below the precision it needs, against an unescalated model | 143,069 comparisons | identical results through the escalation path |
| `cft_conformance` replay of the transcendental sets | 129,845 cases in 20 sets (part of 521,845 in 40 at the runner's generation, 365,845 at the Makefile's) | every case, bits and flags, replayed twice |
| MPFR parity, all twenty functions, four formats, five attributes | 175,680 transcendental cases (95,680 phase 1 + 80,000 phase 2), part of 414,008 | **zero value mismatches, zero flag mismatches** |
| the same campaign with `CFT_TRANSCEND_MINPREC=64` | 414,008 cases, 38,338 escalations | **zero mismatches** |
| `cft.hpp` against `cft.h`, every entry point twice | 3,751 checks at C++17 and again at C++20 (was 3,267) | identical encodings and flags |
| the cftmpfr drop-in | 384 tests (was 268) | pass, asin/acos/atan/atan2 bit-for-bit against gmpy2 |
| `api-test` contract checks | all | pass |
| `make -C host examples-lang`, the legs this host can run | c++, rust, csharp | the canonical four checksums, diff clean |

MPFR is again not the third oracle but the ONLY one, and for the seven
Pi-variants it is called directly: `mpfr_sinpi`, `mpfr_cospi`,
`mpfr_tanpi`, `mpfr_asinpi`, `mpfr_acospi`, `mpfr_atanpi` and
`mpfr_atan2pi` are MPFR 4.2.0 functions, asserted by a `#error` at the
top of `host/tools/mpfr_check.c`. Composing sinPi out of
`mpfr_sin(pi * x)` would compare against a ROUNDED product and would
decide nothing about the last bit. `mpfr_asin`, `mpfr_acos`,
`mpfr_atan` and `mpfr_atan2` exist in every MPFR.

**Escalation, measured.** Over the MPFR campaign's 175,680
transcendental elements, 74,755 reached the Ziv loop and it escalated
**zero** times; the deepest working precision used was **514 bits** -
fp256's own first attempt, `2p + 40`. **No input reached the cap.**
18,520 elements were decided exactly and 43,155 by a neighbour's side
rather than by any precision at all. Over `transcend_check.py`'s pools
the model escalated 36 times, all of them still the phase-1
`pow(1+u, -(1+u))` family, and the deepest precision any input needed
was 832 bits, the fp256 cap itself, for that family. **No phase-2 input
escalated at all** at the contract's own precisions.

Forced low, the second run of the `transcend` stage: 143,069
comparisons of an escalated C against an unescalated model with
identical results, and 38,338 escalations driven through the MPFR
campaign with zero mismatches.

**Three defects, two of them pre-existing and invisible until this
phase's gates were built.**

- `host/tools/mpfr_check.c`'s `build_tpool` had tested `enc_from_val`
  against 0 since it was written, where 1 is success. Every directed
  transcendental operand it meant to add - the exp2 integers, the log2
  powers of two, the log10 powers of ten, the neighbours of 1, the
  arguments below `2^-(p+3)` - was discarded and a zeroed encoding kept
  in its place, so the phase-1 MPFR campaign ran on `build_pool`'s
  specials plus randoms. Found because the new trigonometric pool came
  out at 42 entries where 192 were asked for. The 2026-09-02 entry's
  escalation figures are annotated accordingly; its case COUNTS are
  unaffected, because the pool was topped up with randoms to the same
  size.
- With the pool repaired, the forced-escalation run failed 75 cases,
  all `pow` at fp128 with a base one ulp from 1. `tr_ziv` refused
  outright when `tr_eval` failed, where a failure BELOW the cap means
  the precision was too coarse rather than that no precision can
  decide; it now escalates, and only a failure AT the cap is a
  refusal.
- Five cases survived that, and they were phase 1's exact-cancellation
  repair being unsound. It returned the larger operand with a SATURATED
  bound, on the reasoning that the enclosure would then reach zero. It
  does not: `err` saturates at 2^40 while the significand is
  `2^(W-1)`, so at any working precision above 41 bits the enclosure is
  narrow, decidable and wrong - `pow(2 + ulp, ~10^4)` at fp128
  overflowed where the true value is about `2^9888`. The true
  difference is bounded only in ABSOLUTE terms, which a relative bound
  around any value cannot express, so it is now a failure and the loop
  escalates on it.

**Negative control**, run and restored the same day. Inverting one
character - the `away` argument of atan's neighbour witness in
`do_atan_family`, so the true value is claimed to lie above its
argument rather than below - is caught by:

- `api-test`, at the new `atan(min subnormal)` toward-zero case:
  `api-test: 1 FAILED`;
- `transcend_check.py`, on its first atan case (`fp32 atan rtz`, the
  smallest subnormal: `0x1` where the model says `0x0`);
- the conformance replay, which stops at 68,542 cases with
  `expected 0x00000000 flags 0x18 / got 0x00000001 flags 0x18`;
- MPFR parity, with mismatches from the first `fp32 atan rtz` row;
- the cftmpfr drop-in against gmpy2, 12 tests failing.

`cpptest` is deliberately not on that list, and that is not a gap: it
issues each entry point through `cft.hpp` and through `cft.h` on the
same library, so a library defect moves both sides. It is a marshalling
check by construction, and the phase-1 control noted the same shape.
Phase 1's control found that `api-test` could not catch a flipped side
because it had no case in that family; phase 2 has six neighbour
families and one case from each went in, which is why `api-test` is on
the list this time.

Standardized run, `bash verify/run.sh --only vectors,libcft,mpfr,transcend`
at 0a9a06c, run id 20260903-031637-0a9a06c:

    vectors      ok      13s
    libcft       ok      88s
    transcend    ok     100s
    mpfr         ok      62s

    VERDICT: PASS, nothing skipped

The seconds are honest and the stage logs carry the counts: vectors 40
sets at the runner's own generation parameters, libcft's 521,845 cases
replayed twice each, transcend's 154,269 then 143,069 comparisons with
the model's escalation numbers printed underneath, and mpfr's 414,008
cases with the library's evaluator counters after them.

Repeated on the finished tree, so the record is of the commit that
ships rather than of one before it: run id 20260903-032203-a8ba574,
vectors 12s, libcft 87s, transcend 100s, mpfr 62s - **PASS, nothing
skipped**, and mpfr's log ends
`TOTAL 414008 cases, 0 value mismatches, 0 flag mismatches`.

What did NOT run, and why: the RTL, formal and container simulation
stages (nothing in this change touches them - these eleven issue no
device pass at all); the native-oracle soak, because there is no CPU
oracle for these functions; and the Node and wasm stages, because
`bindings/node` and `bindings/wasm` were deliberately left alone -
another change is working on the JavaScript surface for ABI 0.3's nine,
and the eleven have no JavaScript surface at all. docs/COMPATIBILITY.md
records that per row rather than in general. Fortran, Julia, Go and R
were not re-run: this host carries none of those four toolchains, so
those rows stand on their dated runs and on nothing newer.

## 2026-09-03 - the JavaScript surface reaches ABI 0.4

The eleven phase-2 trigonometrics landed in libcft an hour before this
change, and the committed wasm artifacts were still built from the 0.3
sources: the module reported 0.3, exported none of the eleven, and the
`cft_conformance` inside it refused the regenerated vector sets on the
function name. The docs said so - docs/COMPATIBILITY.md's 0.4 ledger
carried two rows reading "no ABI 0.4 surface" - which was honest and
was also the third time that gap had opened. It closed here, in the
same commit as the rebuild, which is the part worth recording: a
rebuild alone would have answered `cftw_abi_version()` with 4 while
exporting nothing 0.4 names, and that is precisely what 0.2 and 0.3
each spent a day doing.

**What was added.** Eleven `cftw_*` wrappers in
`bindings/wasm/wasm_api.c`, one per declaration in `host/include/cft.h`
and in cft.h's order - `cftw_sinpi`, `cftw_cospi`, `cftw_tanpi`,
`cftw_asin`, `cftw_acos`, `cftw_atan`, `cftw_asinpi`, `cftw_acospi`,
`cftw_atanpi`, then `cftw_atan2` and `cftw_atan2pi`, which read y
first. None carries a `bus_out`: these are host operations, they issue
no device pass, and the contract gives them no such parameter. Eleven
rows in the page's compute panel and eleven entries in its cwrap table;
the drop zone needed nothing, having accepted the twenty transcendental
set names since that morning. `bindings/node` carries all eleven on all
three layers - the raw table, `Context`/`Float` scalars, and `map()`
over an array, which dispatches by arity and so needed only the name
lists - at package version 0.4.0.

**The artifacts.** Rebuilt with `bash bindings/wasm/build.sh` against
the pinned emsdk 6.0.9 image (tag and digest both), node 22.19.0 on
Windows 11:

| | |
|---|---|
| module | **98,392 bytes**, sha256 `ee66812e4bd17de7dcf6b5a63f652b803f196e1f1afd0bf8e572de6c86f2a68f` |
| page | `conformance.html` 1,144,530 bytes, sha256 `b9ddcecc2dddf342faf77a1014b525f2283c07d3439ff1d39e072c5b17fc5254` |
| exports | **58 `cftw_*`**, up from 47 |
| `cftw_abi_version()` | 4 = ABI 0.4, matching `cft.h` |
| node loader | byte-identical to the page's module, checked rather than assumed |

Three container builds of the tree: two back to back, byte-identical,
and a third after the negative control below was reverted, which is the
stronger statement because it says the tree round-tripped.

**Measured, with `make vectors` from the repo root (40 sets, 236,000
opcode cases + 129,845 transcendental):**

| check | result |
|---|---|
| `node bindings/wasm/verify.mjs` | ABI 0.4 and 58 exports from the committed page; **365,845 cases over 40 sets** through `cft_conformance`; **129,845 more through the twenty wrappers themselves**, per case then per family as arrays; zero mismatches either way |
| `node bindings/node/test.mjs` | **74 passed, 0 failed** (57 before) |
| `node bindings/node/conformance.mjs` | 236,000 opcode cases in 1.7 s, then **129,845 transcendental cases in 108.2 s** through this package's own `Context` methods; **365,845 over 40 sets in all** |

The seventeen new Node tests are what a vector set cannot express:
`sinPi`'s zeros carrying the ARGUMENT's sign (`sinPi(1) = +0`,
`sinPi(-1) = -0`), `cosPi`'s unsigned half-integer zero, `tanPi(1) =
-0` and the half-integer pole signalling divideByZero rather than
overflow, the Pi-forms' larger exact table including `atanPi(±inf) =
±1/2` raising nothing at all, the inverses exact only at their zeros,
`atan2(±0, -0) = ±pi` inexact against `atan2Pi(±0, -0) = ±1` exact,
the operand order, a quiet NaN losing to `atan2`'s table where it beats
`pow`'s, invalid for `|x| > 1` and for an infinity in the forward set,
the signaling NaN across all eleven, `sinPi(2^80)` and
`sinPi(maxFinite)` exact by a reduction that is a mask on the encoding,
all eleven at all four formats, the `Float` methods, and
batch-equals-scalar over 129 elements for each.

One of those deserves its own line, because it is the case that looks
exact and is not. `asinPi(1/2)` is exactly 1/6 - rational, by Niven,
but NOT a dyadic rational, so it rounds. The test checks that it is
1/6 by DERIVING 1/6 from `cft_div(1, 6)` in the same attribute rather
than transcribing a constant, and it does so in all five attributes:
two correctly rounded results of one real number are one encoding, so
agreement in all five is a much stronger statement than agreement in
roundTiesToEven. `acosPi(1/2) = 1/3` is checked the same way.

**Negative control**, run and reverted. The control moved with the
surface: at ABI 0.3 it was `cftw_pow`, because pow is not symmetric;
here it is **`cftw_atan2`**, which is sharper for the same reason and
one more - atan2 takes y first, so swapping its two operand pointers
returns a plausible number for *every* input rather than failing loudly
anywhere. Swapped, rebuilt, and caught by name in three places:

- `verify.mjs` step 5 fails **all twenty** transcendental sets, first
  at `fp32-transcend.jsonl:4072` - `atan2(+0, -0)` comes back
  `0x80000000` where the vectors say `0x40490fdb` with inexact, which
  is exactly the clause 9.2.1 row cft.h says implementations most often
  miss;
- `bindings/node/test.mjs` fails 2 of 74 by name (`atan2(+0, -0) is pi
  and inexact`, `atan2(-0, +1) is -0`);
- `bindings/node/conformance.mjs` fails all twenty transcendental sets.

And, the part that is the whole reason those checks exist:
`verify.mjs` **step 4 stayed green at 365,845 cases** throughout, and
so did `conformance.mjs`'s opcode pass. `cft_conformance` dispatches
all twenty transcendentals internally, in C, and never touches a
wrapper - so the internal replay cannot see a broken JavaScript
surface, which is the half-step's failure mode reproduced on purpose.
Reverted, rebuilt, and the artifacts hash to what they hashed before.

Standardized run, `bash verify/run.sh --only vectors,node,wasm` on a
clean tree at 32ece03, run id 20260903-043340-32ece03:

    vectors      ok      14s
    node        ok     367s
    wasm        ok     213s

    VERDICT: PASS, nothing skipped

The runner generates its own vectors at its own parameters, which are
larger than the Makefile's, so its counts are its own and not the ones
above: 392,000 opcode cases over twenty sets plus the same 129,845
transcendental cases, **521,845 over 40 sets**, replayed clean by both
stages, with `test.mjs`'s 74 tests inside the node stage.

**Watched in a browser**, because the markup changed again - eleven
rows in the compute panel's table, eleven entries in the cwrap table -
and `verify.mjs` step 5 checks the wrappers, not the markup between a
click and them. Chromium 148 on Windows 11, the committed
`conformance.html` served over a loopback `http.server`, `file://`
still being unreachable from this session:

- section 1 read **libcft ABI 0.4**;
- section 2's embedded sample replayed **4,015 cases over 20 sets,
  green**;
- section 3 took a drop of four transcendental sets and one opcode set
  - **45,569 cases, all matching** - with a deliberately misnamed
  sixth file refused by name and the verdict correctly downgraded to
  "not a full pass". The four transcendental sets carry the eleven's
  cases, so the drop path saw them too;
- section 4 offered all eleven new operations, each labelled with its
  ABI step and entry point and each enabling exactly the operand
  fields its arity uses. Computed through the button: `sinPi(1)` = +0
  against `sinPi(-1)` = -0 with no flags either way; `tanPi(1)` = -0;
  `tanPi(1/2)` = +inf **with divideByZero, not overflow**;
  `cosPi(3/2)` = +0; `atanPi(+inf)` = `0x3fe0000000000000`, exactly
  1/2, silent; `atan2(+0, -0)` = `0x400921fb54442d18` = pi and
  *inexact* against `atan2Pi(+0, -0)` = 1 exactly; `atan2Pi(1, 0)` =
  1/2 against `atan2Pi(0, 1)` = +0, which is the operand order made
  visible in the UI; and at binary256 `asinPi(1)` = 1/2 and
  `acosPi(-1)` = 1 both exact and silent, `acosPi(1/2)` =
  `0x3fffd5555…5555` = 1/3 with inexact, `asin(2)` the canonical quiet
  NaN with invalid. The panel refused a 65-hex-digit operand by count
  rather than truncating it;
- `build/negative_control.html` was opened in the same browser and
  failed red at `fp64.jsonl:2` (`expected 0x7ff8000000000001 / got
  0x7ff8000000000000`), so the checker was watched failing on this
  build and not only on the previous one.

**What did NOT run, and why.** The RTL, formal and container
simulation stages, the libcft/transcend/mpfr stages and the language
legs: this change touches no C source, no header, no generator and no
golden model, and `git diff` against the phase-2 merge is confined to
`bindings/` and the docs. No other JS runtime and no device backend -
wasm32 has no PCIe, so `Context.open` here is always the software
backend.

## 2026-09-03 - the reviewer's gates on the phase-2 merge (ABI 0.4)

Three runs on DESKTOP-T33SK86 (Windows), each on a clean tree, before
phase 2 and the JavaScript surface it needed were merged.

**The phase-2 tree itself, c9a180e, the whole standard set:** 26
stages executed, 25 ok, images skipped by name (no xclbinutil on
Windows), and ONE failure that was the expected one - `wasm` in 3 s,
the page's ABI check refusing a module at 0.3 against a header at 0.4.
Everything the C side touches passed: golden 173 s (941 tests), vectors
14 s, sim 408 s at SIM_JOBS=8, lint 46 s, formal 28 s, libcft 93 s
(365,845-case replay), transcend 107 s (154,269 comparisons, then
143,069 through the escalation path), mpfr 47 s (414,008 cases, zero
mismatches), cpp 326 s (3,751 checks at each standard), bindings 6 s
(384 tests), the seven language legs, node 269 s, soak-quick 85 s. Run
id 20260903-033117-c9a180e.

**The merged tree, 047430a (phase 2 over the 0.3 JavaScript surface),
the eight stages the merge could move:** vectors, libcft, transcend,
bindings, cpp and mpfr ok; node and wasm FAIL - `unknown function
"sinpi" - this package's table and cft.h have diverged` and `the page
reports ABI 0.3 where the tree is at 0.4`. Both refusals by name, which
is what the JavaScript gates were built to do when the library moves
under them. Run id 20260903-033321-047430a.

**The tree that ships, with the 0.4 modules:** vectors, bindings, node
and wasm ok - node 376 s, wasm 218 s - the 58-export module
replaying every set the drop zone accepts. Run id 20260903-051451-f3d36ed.

Two defects phase 2 found in phase 1's work are worth restating here
because the 2026-09-02 entries above were written before them: the
MPFR harness's transcendental pool had discarded every directed
operand since it was written (an inverted success test), so the
phase-1 parity campaign ran on specials and randoms; and the
exact-cancellation repair in the evaluator's add was unsound below the
contract's working precisions (a saturated RELATIVE bound cannot hold
an ABSOLUTE window around zero). Neither produced a wrong answer at
any precision the contract uses - the forced-low run is what reached
them - and both are fixed on the tree above, with the MPFR campaign
re-run on the repaired pool.

## 2026-09-03 - phase 3 of the transcendentals: the reduction against pi, and the hyperbolics (ABI 0.5)

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2, CPython 3.12. The first half
of this phase - the constant, the model, the library with its
reduction - was built by an agent that was stopped twice by server
errors; the reviewer finished the tests, the harnesses, the bindings,
the JavaScript surface and the docs in the same worktree, and every
number here is from a run the reviewer made on the tree that ships.

    2/pi                  270,336 bits generated (host/tools/gen_2opi.py), re-derived to
                          the last bit from Chudnovsky in plain Python integers
    worst-case search     fp32 29 bits (128 binades, every one), fp64 61 (1,024, every one),
                          fp128 121 (every 16th of 16,384), fp256 245 (every 512th of 262,144);
                          --validate: 219 instances vs exhaustive search, 0 disagreements
    python/tests          944 passed, 1 skipped
    transcend_check       280,670 comparisons over 29 functions, C == model;
                          264,430 more with the C forced to start at 64 bits
    make vectors          40 sets, 478,915 cases (242,915 transcendental)
    make -C host test     api-test all contract checks passed (the phase-3 block included);
                          478,915 cases replayed twice
    mpfr-check            451,988 cases, 37,980 for the nine: 0 value, 0 flag mismatches;
                          again with CFT_TRANSCEND_MINPREC=64: 0 mismatches, 48,301 escalations
    reduction             9,855 arguments reduced, 0 widenings,
                          widest window 1,184 bits, deepest cancellation 239 bits
    cpptest               4,111 checks at C++17 and at C++20
    test_cftmpfr          576 tests
    node                  79 tests; page 69ff0ff911e9ce1e..., wasm 5718aa19e85dad2b...,
                          67 exports, 140,869 bytes, two clean builds byte-identical
    runner                20260903-073156-d729aef: vectors, libcft, transcend, mpfr, cpp, bindings,
                          node, wasm - PASS, nothing skipped; libcft replays 634,915 cases at
                          the generator's defaults (the runner regenerates rather than trusting
                          vectors/out); node 425 s, wasm 312 s, cpp 426 s, transcend 244 s

The two published worst cases of the reduction - 16367173 * 2^72 at
binary32 and 0x1.6ac5b262ca1ffp+849 at binary64 - are in
host/tests/api_test.c with their sines decided by the rule beside 1
and their cosines (the reduced arguments themselves) with bits mpmath
derived at 700 bits. A reduction that dropped the wrong bits of 2/pi
would return the sine of a slightly different number, and those two
lines would fail first.

Negative control, run and restored: the SIDE of sin's neighbour
witness inverted in `do_radian`, so sin is claimed to lie above a tiny
argument. Caught by api-test ("sin(min subnormal) downward is +0"),
by transcend_check.py at fp32 under roundTowardZero, by the
conformance replay and by MPFR parity.

Repeated on the tree that ships, after the docs above were committed:
run 20260903-080110-bc1ec32, the same eight stages - vectors 43 s,
libcft 129 s, transcend 254 s, bindings 10 s, cpp 438 s, node 425 s,
wasm 320 s, mpfr 50 s - PASS, nothing skipped, clean tree.

## 2026-09-03 - clause 5.12's character sequences and clause 9.7's payloads

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2, CPython 3.12, on a twelve-core
box running three other agents' builds throughout - so every wall clock
below is longer than this tree deserves and none of them is a
performance number. The last runner invocation was STOPPED before it
finished; what did and did not run is spelled out below rather than
estimated.

This is the last REQUIRED part of clause 5 the library did not meet.
5.12 opens with a **shall**, not a should: an implementation must
convert between each supported binary format and external decimal
character sequences such that the round trip under roundTiesToEven
recovers the original representation. Every other numeric claim in this
repository is about arithmetic; this one is about the edge where
callers arrive, and until now every caller reaching libcft from a text
format was reaching some other implementation's decimal rounding.

### What ran, and what it said

    python/tests            1083 passed, 5 skipped (321 s). 139 of them
                            are new: chars.py against ref754's rational
                            restatement of 754 in all five attributes,
                            against CPython's own binary64 parse and
                            "%.16e" write, and against the exact value
                            of every sequence read back as a Fraction
                            by the TEST rather than by the model
    make vectors            60 sets, 492,731 cases; 13,816 of them the
                            twenty new character sets
    make -C host test       api-test all contract checks passed (the new
                            block and its negative control included);
                            reduce-parts 6,294 partitions; 492,731 cases
                            replayed; C and Python examples identical
    runner, stage vectors   ok 79 s - 60 sets at the generator's
                            defaults, 13,816 character cases
    runner, stage libcft    ok 333 s - clean rebuild, api-test,
                            reduce-parts, 648,731 cases replayed over
                            60 sets
    runner, stage character ok 166 s - 20,819 comparisons over four
                            formats and five attributes, C == model on
                            every one, with the Pmin-1 collision
                            exhibited per format
    runner, stage bindings  ok 146 s - 640 tests (was 636)
    runner, stage cpp       C++17 leg complete: 648,731 conformance
                            cases through the wrapper and all 210,511
                            checks passed. The C++20 leg was RUNNING
                            when the run was stopped - see below
    mpfr-check 24 7         458,300 cases, 0 value and 0 flag
                            mismatches, 6,312 of them the four
                            conversions
    mpfr-check 2 7          298,904 cases, 0 value and 0 flag
                            mismatches, 20,172 of them the four
                            conversions, on the ENLARGED pools this
                            tree ships
    cpptest, standalone     210,511 checks at C++17 and again at C++20,
                            492,731 conformance cases through the
                            wrapper each time - run before the MPFR
                            harness and the conformance summary line
                            were last touched, neither of which the
                            wrapper compiles against

### What did NOT run, and why

The runner invocation `--only vectors,libcft,character,mpfr,cpp,bindings`
(run id 20260903-111141-60d046d) was **stopped under time pressure on a
contended host**, with four of its six stages green and no failure
anywhere. Specifically:

  * `cpp` - the C++17 half passed with its counts above; the C++20 half
    was mid-replay and has no verdict from THIS run. The same binary at
    the same standard passed standalone earlier on the same wrapper
    source (210,511 checks), so the gap is a missing re-run rather than
    an unknown.
  * `mpfr` - never started in that run. The campaign it would have run
    (`mpfr-check 24 7`) completed twice earlier with zero mismatches,
    but never once with BOTH the census random count and the enlarged
    character pools this tree ships: the 24-argument run predates the
    pool increase and the 2-argument run postdates it. That combination
    is the one number this entry does not have.

Nothing was skipped by the runner's own logic and nothing failed. There
is no VERDICT line for that run, so it certifies nothing on its own;
the four green stages are recorded as the individual stage results they
are.

### The round trip, held and cornered

Pmin comes out 9, 17, 36 and 73 from `1 + ceiling(p * log10 2)`,
derived rather than transcribed, and the standard lists the first three
so the formula is checked before it is trusted at binary256. The round
trip holds at Pmin in both directions under both nearest attributes.
One digit short it does not, and that is shown rather than assumed:
`0x417ffff5` and `0x417ffff6` are neighbouring binary32 encodings just
below 16 that both write `1.5999990e+1` at eight digits, so reading
that sequence back can recover at most one of them. The colliding pair
is found by walking down from the top of each binade - where the
decimal grid is coarsest relative to the binary one - and one is
exhibited per format. binary64's is `0x3ffffffffffffffe` against
`0x3fffffffffffffff`, and there BOTH are lost, because their shared
sixteen-digit decimal `2.000000000000000e+0` rounds to a third
encoding between them.

**The negative control is the round trip itself.** An implementation
that ignored the digit count and always wrote the exact value would
satisfy every round-trip check ever written, so the last block of
api_test.c asserts that the round trip FAILS at Pmin - 1, which it can
only do if the digit count is being honoured.

### What MPFR arbitrates here, and what it cannot

mpfr_strtofr and mpfr_get_str are correctly rounded in every mode at
any precision, so both directions are scored against them - values and
flags, five attributes, four rungs. Three things are deliberately
outside that, and are written where the harness runs: the absurd
exponents (`1e999999999999`) are outside MPFR's own exponent range, so
feeding them to the oracle would score MPFR's overflow rather than the
format's; NaN PAYLOADS cannot be arbitrated by a library that keeps
none; and the EXACT conversion cannot be asked of mpfr_get_str at all,
which produces shortest-or-N digits. The exact conversion is scored a
different way that is just as strong - the sequence the library wrote
is handed back to mpfr_strtofr at the format's precision, and MPFR must
report a ternary of ZERO and the same value. The halfway sequences the
attribute alone decides are built on the oracle side with GMP, from the
midpoint between an encoding and its successor, so they owe the library
nothing.

### cftmpfr's from_str moved off gmpy2, and the switch was measured first

2,480 parses across four precisions and the four attributes MPFR has,
the library's route against the gmpy2 one: ZERO encoding differences,
and 32 flag differences, every one of them the same row - a decimal
that lands exactly on a subnormal, where MPFR raises underflow and 754
7.5 says "If the rounded result is exact, no flag is raised". The
library is right and the package now says so. Two smaller changes rode
along: `-nan` keeps its sign, and `snan` reads as a signaling NaN
rather than as an error. `to_str` was NOT switched - it is the shortest
sequence that reads back and the library's is the exact one, and no
measurement can make those the same string.

### A defect this work found in its own harness

The MPFR side builds the exact decimal of a midpoint with GMP, and
`mpfr_get_z_2exp` hands back a NEGATIVE significand for a negative
value while the harness was also prepending its own sign - so every
negative midpoint was written `--.1000...e+1` and the library correctly
REFUSED all thirty of them. The refusal reached the report as a bare
"status != OK" naming no sequence, so a `REFUSED` line that names it
went in before the bug was found. Two oracles disagreeing is the normal
case; an oracle that cannot say what it disagreed about is the problem.


## 2026-09-03 - the rest of table 9.1: exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt, pown, powr, compound, rootn (part of the 0.6 step)

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2, CPython 3.12, with three
other agents building on the same box - so no wall-clock figure here is
comparable with an earlier entry and none is quoted as a performance
number. With these ten the library implements every operation IEEE
754-2019 table 9.1 lists for the binary formats.

    python/tests          1,241 passed, 1 skipped (944 before)
    transcend_check       607,217 comparisons over 39 functions, C == model on every
                          one; 580,977 more with the C forced to start at 64 bits
    rootn(x,2) == sqrt(x) 17,665 comparisons over 5 attributes - identical except at
                          x = -0, where 9.2.1's own NOTE says they differ, and the
                          difference is asserted rather than skipped
    make vectors          40 sets, 769,265 cases (533,265 transcendental), up from
                          478,915 (242,915)
    make -C host test     api-test all contract checks passed, the table-9.1 block
                          included; 769,265 cases replayed twice
    mpfr-check            544,788 cases, 92,800 of them for the ten: 0 value, 0 flag
                          mismatches; again with CFT_TRANSCEND_MINPREC=64: 0
                          mismatches, 72,381 escalations
    evaluator             306,460 transcendental elements, 138,825 reached the Ziv
                          loop, 9 escalations (all phase 3's tanh - none of the ten),
                          32,585 decided exactly, 56,835 by a neighbour's side
    cpptest               4,549 checks at C++17 and at C++20 (4,111 before)
    test_cftmpfr          668 tests (576 before)
    examples-lang         c++, rust, go, csharp: same library, same bits; julia and
                          R absent from this host
    runner                INCOMPLETE. Run 20260903-104410-a285ad8 got two stages in -
                          vectors ok 369 s, libcft ok 386 s - and was STOPPED during
                          the transcend stage under time pressure, with three other
                          agents on the box. mpfr, cpp and bindings were not reached
                          by the runner; all three were run standalone above, on the
                          same tree and with the same arguments the runner uses, and
                          the two stages the runner did finish agree with the
                          standalone runs. The runner has NOT been seen green
                          end-to-end on this tree and nothing here says otherwise.

Three rows follow 754-2019 where GNU MPFR 4.2.2 does not, each measured
on this host before it was written down: `rSqrt(-0)` is -infinity where
`mpfr_rec_sqrt` gives +infinity; `powr(1, qNaN)` is a quiet NaN where
`mpfr_powr` gives 1; and `compound(x, 0)` for x below -1 is invalid,
which MPFR agrees with and which the standard's row makes rather than
states.

**A defect in the oracle.** `mpfr_compound_si` is off by one unit in
the last place for a NEGATIVE n whenever 1 + x is not representable at
the working precision - a double rounding of the intermediate sum.
Measured at 24 bits: `compound(1 + 2^-23, -1)` toward zero returns
`0x7.fffffp-4` where the same value computed at 400 bits and rounded
once is `0x7.fffff8p-4`; `compound(3 - 2^-22, -1)` to nearest returns
`0x4p-4` where the reference gives `0x4.000008p-4`. n = -2 and n = -4
do it too; a non-negative n does not, and `mpfr_pow_si` and
`mpfr_rootn_si` are sound at every n in [-12, 12] against the same
reference. The library's answers were confirmed three independent ways
first - the golden model's mpmath enclosure, the C's own tracked error
bound, and `python/tests/test_transcend.py`'s brute-force enclosure at
four times the escalation cap - so `host/tools/mpfr_check.c` keeps
MPFR's own compound for n >= 0 and builds the expectation from the
exactly formed 1 + x and `mpfr_pow_si` for n < 0, with the reasoning in
a comment at the call site.

**Two neighbour rules the sweep found rather than the design
predicted**, both now in the model and the C with the same derived
thresholds: `log2p1(2^k)` and `log10p1(10^k)` sit an exponentially
small step above the integer k, which is a grid point no precision
separates them from; and `compound(x, n)` for a dominant x sits inside
a quarter step of x^n - without which `compound(2^1022, 1)` at binary64
is 2^1022 + 1, one unit above a grid point whose ulp is 2^970.

Negative control, run and restored: the `away` argument of log2p1's
neighbour witness inverted in `do_logp1_family`, so `log2p1(2^k)` is
claimed to lie below the integer k. Caught by api-test ("and upward it
is nextUp(30)"), by transcend_check.py at fp32 under roundTowardZero
(`log2p1(2^24)` came out `0x41bfffff` where the model says
`0x41c00000`), by the conformance replay (which stops at 92,033 cases)
and by MPFR parity.

Not covered here: `bindings/node` and `bindings/wasm` still carry the
twenty-nine. They replay the transcendental sets, which now name
thirty-nine functions and carry an `"n"` field, so they need the
rebuild the JavaScript step performs; nothing in this entry claims
otherwise.


## 2026-09-03 - the rest of clause 9.4: the five remaining reductions

sumSquare, sumAbs, scaledProd, scaledProdSum and scaledProdDiff, on the
terms `sum` and `dot` have held since 2026-08-30: one tree fixed by
element index, one rounding per node, in the caller's attribute. Part
of the 0.6 step; `CFT_ABI_VERSION_MINOR` untouched, left for the
integrator.

What was measured, and by what:

| gate | scope | result |
|---|---|---|
| `python/tests` (whole suite) | the golden model, which defines every bit | **1016 passed, 1 skipped** |
| `python/tests/test_reduce.py` | the five, specifically | **213 passed**, from 24 test functions to 43 |
| `make vectors` | the sets, Makefile arguments | 60 sets, of which **20 are new reduction sets** at 448 cases / 9,513 elements each |
| `make -C host test` | api-test, reduce-parts, the conformance replay | **60 sets, 487,875 cases, all matching** over the sets `make vectors` emits (the runner's are larger - see below); api-test all contract checks passed; reduce-parts 6,294 partitions, all canonical |
| `host/tests/reduce_check.py --trials 1500` | libcft against the model, four formats | **12,696 reductions, 0 failures** |
| `host/tools/mpfr-check 24 7` | GNU MPFR as the arbiter of every node | **461,508 cases, 0 value and 0 flag mismatches**; of those, 9,520 reduction vectors and **231,975 tree nodes arbitrated** |
| `make cpptest` | cft.hpp against cft.h, both standards | **4,891 checks each at C++17 and C++20**, 0 failed, from 4,771 |
| `test_cftmpfr.py` | the drop-in | **581 passed**, from 43 test functions to 46 |
| `device-test sw -n 96` | the composition across the backend boundary | **2,248 checks, 0 failed**, now including 48 sumsq and 48 sumabs |

Two numbers in that table are worth reading twice. The reduction sets
are the FIRST reductions the published vectors have ever carried - not
even `sum` was in them before - and they needed a third schema, because
a reduction's operand is a whole vector whose length is part of the
case and the two existing schemas are one line per case with a fixed
number of single-element operands. And the 231,975 MPFR-arbitrated
nodes are nodes, not vectors: a case here is a whole reduction.

**The identities, and the row that is not one.** reduce_check.py checks
`sumSquare == dot(a, a)` and `sumAbs == abs pass then sum` THROUGH THE
LIBRARY, because issuing exactly those calls is how the device and
software backends are made to agree, and a run that assumed them would
be taking the mechanism on trust. Over the standard sweep: **476
vectors where both identities hold verbatim, 272 where 9.4's
infinity-over-NaN row applies instead** - counted rather than skipped,
checked against the override, with the plain dot's quiet NaN as the
control. The check fails if the override is never exercised at all.

**What the MPFR campaign does NOT settle, stated in the tool's own
banner.** MPFR arbitrates every node - one add or one multiply of two
format values, correctly rounded - and has no opinion on the TREE,
because 9.4 says an implementation may "associate in any order or
evaluate in any wider format". The harness therefore reproduces the
split rather than judging it, and a reduction whose shape were wrong in
both libcft and this file would pass. What guards the shape is two
independent implementations of it compared against each other, the
streaming accumulator's agreement with the recursive definition, and
the published sets.

**One bug, in the harness, with two faces - found the moment the oracle
first ran.** The first campaign reported 36 value and 476 flag
mismatches, and every one came from a single wrong choice: the harness
classified the LEAVES rather than the operand elements when applying
9.4's infinity-over-NaN row. That is wrong in both directions at once.
An element whose SQUARE overflowed to an infinity fired an override the
standard's text does not - 9.4 says "operand element", and a finite
element is not an infinity however large its square. And a signalling
NaN stopped raising invalid, because squaring quiets it before the
classification ever saw it. The library was right both times, which is
what a new oracle is for. Fixed; 0 mismatches after.

**One overclaiming comment, found by re-reading rather than by a
gate.** The campaign's fourth draw of every length said it alternated
"the pool's extremes - maxfinite and the minimum subnormal". It did
not: `build_pool`'s `pool[0]` is +0 and its tail is random. The two
ends are now built from the format descriptor, the comment is true, and
the node count rose from 226,295 to 231,975 with the coverage the
comment had been claiming.

**A third firing of the reassignment hazard.** Assigning 28 and 29 made
`vectors.py`'s "unassigned, just past the seeds" representative stale,
and `cft_conformance` refused the regenerated set by name -
"this set records an opcode as reserved that the contract has since
assigned" - rather than scoring sumSquare against an answer recorded
for the unassigned-opcode result. 24 was the first (2026-08-30), 26 the
second (2026-08-31). The representative is now 30, and
docs/DETERMINISM.md's "everything from 28 up" now reads 30.

### Negative control, run and restored

The claim most worth attacking is the SCALING rule, because it is the
one thing 9.4 leaves implementation-defined and therefore the one thing
an oracle over values cannot check. So the control preserves the value
exactly and breaks only the pinned form: `sp_split` in
`host/src/reduce.c` was made to normalise into `±[2, 4)` instead of
`±[1, 2)`, with the scale one lower. **`scaleB(pr, sf)` is bit-for-bit
the same real number, every rounding in the tree is unchanged, and no
flag moves** - only the pair the contract pins.

Five gates caught it, and the sixth is worth recording because it
could not:

| gate | verdict on the broken tree |
|---|---|
| `api-test` | **2 FAILED** - `scaledProd(2^100 x 4)` returned `(2.0, 399)` for `(1.0, 400)`, and scaledProdSum `(2.0, 2)` for `(1.0, 3)` |
| `reduce_check.py --trials 200 --formats fp32` | **86 failures** of 1,565, including the pr-in-[1,2) invariant |
| `cft-selftest` conformance replay | **FAILED** at `fp32-reduce.jsonl:258` - expected `0x3f800000` scale -149, got `0x40000000` scale -150 |
| `mpfr-check 2 7` | **1,092 value mismatches**, 273 per format - and **0 flag mismatches**, exactly as designed: the arithmetic never moved |
| `test_cftmpfr.py` | **3 failed** of 581 |
| `cpp-api-test` (C++17) | **1 of 4,891** - and that one is the conformance replay, not the wrapper comparison. All 4,890 wrapper-against-C checks PASSED, because both sides call the same library: a C++ layer that only compares itself to the C is structurally incapable of catching a change of this class, and it is worth knowing which of your gates are which. |

Restored, rebuilt clean, api-test green again.

### The standardized run

`bash verify/run.sh --only vectors,libcft,reduce,mpfr,cpp,bindings` on
DESKTOP-T33SK86 (Windows, MINGW64), run **20260903-103848-642b5e4, on a
CLEAN tree**: vectors 56 s, libcft 164 s, reduce 16 s, bindings 15 s,
cpp 591 s, mpfr 89 s - **VERDICT: PASS, nothing skipped**.

The runner regenerates the sets with `gen_vectors.py`'s own defaults
rather than the Makefile's, so its libcft stage replayed **643,875
cases** where `make -C host test` replays 487,875 - the same 60 sets at
different budgets. Its cpp stage replayed those 643,875 through the
wrapper too, at both standards, 4,891 checks each. Its mpfr stage is
the 461,508-case, 231,975-node campaign in the table above.

An earlier run of the same six, 20260903-101107-aea195e, produced the
same verdict with a DIRTY tree (the docs were uncommitted), and so
certifies nothing on its own; it is mentioned only because it is where
the numbers were first taken and because it is in verify/state/. Every
number above was reproduced by the clean run - the reduction gates are
deterministic by construction, so "reproduced" here means identical,
not merely consistent: 12,696 reductions, the same 476/272 split, the
same 231,975 nodes.

The run was SCOPED to those six stages, so what it does not cover is
worth naming rather than leaving to be inferred:

- `golden` was not run under the runner; `python/tests` was run
  directly instead, which is the same suite - 1016 passed, 1 skipped.
- `sim` and `lint` need docker and cover the RTL. **This work adds no
  RTL and changes none**: neither of the two new opcodes is streamed by
  the accumulator, and a scaled product has no accumulator at all.
- `node` and `wasm` are out of scope by instruction - a separate agent
  adds the JavaScript surface. Both runners enumerate vector sets by
  NAME and ignore anything else, so they see the twenty new sets as
  "(ignoring fp32-reduce.jsonl, ...)": neither breaks on them, and
  neither scores them yet.
- `transcend`, `clause5`, `divsqrt`, `diff`, `seq`, `selfcheck` and the
  language stages were not re-run. Nothing in this work touches their
  code paths, and saying so is not the same as having measured it.

`device-test sw -n 96` was run directly rather than through the
`selfcheck` stage, which is what that stage runs.

## 2026-09-03 - the augmented arithmetic operations, IEEE 754-2019 clause 9.5

augmentedAddition, augmentedSubtraction and augmentedMultiplication -
`cft_augmented_add`, `cft_augmented_sub`, `cft_augmented_mul` - at all
four formats, both outputs and exact flags, under the one rounding
754-2019 defines for them and for nothing else: roundTiesTowardZero.
Part of the 0.6 step; the ABI minor is the integrator's to bump when
the whole step lands, and this work leaves it at 5.

Windows 11 (DESKTOP-T33SK86), mingw64 gcc 16.1.0, MPFR 4.2.1 as the C
oracle (what the run printed), CPython 3.12.9 with gmpy2 2.2.1,
2026-09-03. **Three other agents were building and running campaigns on
the same machine throughout**, so the wall times below are not
comparable with the earlier entries. The counts are.

| check | count | result |
|---|---|---|
| `python/tests/test_augmented.py` | 20 tests | pass |
| the whole `python/tests` suite | 964 passed, 1 skipped (was 944/1), 258 s | pass |
| `make vectors` | 44 sets, 568,531 cases - 4 new augmented sets, 89,616 cases | written |
| `cft_conformance` replay at the runner's generation | 44 sets, 724,531 cases, 89,616 of them augmented | every case, BOTH outputs and flags, replayed twice |
| `host/tests/augmented_check.py` - the C against the model per element, plus batches, aliasing and refusals | 140,088 comparisons at the default pool; 149,112 at `--trials 400`; 158,712 more at `--trials 800` over the four formats in two halves | C == model on every one |
| the pair identity `r + e == x op y`, exact integers, on the LIBRARY's output | 80,209 pairs | exact - plus 8,316 residuals delivered rounded, 9.5's one non-representable case |
| the FAR/NEAR alignment split, walked across its decision at every magnitude and both signs | 70,200 comparisons | C == model on every one |
| MPFR parity, the three operations, four formats | 21,492 augmented cases (5,373 per format), part of 473,480 | **zero value mismatches, zero flag mismatches** |
| `cft.hpp` against `cft.h`, every entry point twice | 4,311 checks at C++17 and again at C++20 (was 4,111) | identical encodings and flags |
| the cftmpfr drop-in | 594 tests (was 576) | pass |
| `api-test` contract checks | all | pass |
| neighbours, in case the shared `round_pack` moved: `divsqrt_check.py` / `clause5_check.py` | 29,124 / 145,032 | zero disagreements |

**The five attributes are unchanged, and the conformance replay is not
what proves it.** `make vectors` regenerates the sets from the current
model, so a change that moved model and library together would replay
clean - that argument is circular and saying so is the point of this
paragraph. The evidence that is not: `python/tests/test_rounding.py`
re-derives each attribute from exact rationals sharing no code with the
model (it is in the 964), `test_augmented.py` holds addition under all
five against the same independent reference, MPFR arbitrates the
library from outside, and as a one-off the current model was compared
directly against the model as it stood at the preceding commit
(ef2348e) over add/sub/mul/fma/div/sqrt: **216,480 cases across five
attributes and four formats, bit-identical including flags.**

**The oracle, stated honestly.** MPFR has no roundTiesTowardZero, and
`MPFR_RNDZ` is not it - RNDZ truncates every inexact value, not only
the ties. So `check_augmented` cannot ask MPFR for the answer. It asks
for the EXACT value at a precision that provably holds it - not 2p,
because the exact sum of two p-bit values spans the whole exponent
range (524,522 bits at binary256), and proved rather than assumed by
requiring MPFR's ternary to be zero - then applies 9.5's tie rule
itself and derives the error term by exact subtraction, deciding
representability by rounding it and asking whether that changed it.
Independent for the VALUES, a restatement for the FLAGS, and the banner
above the function says which is which.

**The flag words, enumerated.** Over the whole pool at every format the
three operations produce exactly five flag words and no others: nothing,
invalid, underflow alone, underflow with inexact, and overflow with
inexact. Inexact never appears alone and divideByZero cannot appear at
all. **Underflow alone is the one this contract admits nowhere else** -
9.5 raises underflow on a subnormal error term that is EXACT - and it
is asserted as a set equality, so a missing combination fails the test
rather than passing quietly.

**Negative control, run and restored.** `host/src/softfloat.c`'s
`CFT_SF_RTTZ` arm changed from `guard && sticky` to
`guard && (sticky || lsb)` - roundTiesToEven, which is the plausible
mistake and the one an implementation makes by not reading 9.5. Caught
by four independent gates: `api-test` at three named checks (the tie at
binary32, the same tie at binary64, and the overflow threshold);
`augmented_check.py` at its first fp32 pair; the conformance replay at
`fp32-augmented.jsonl` **after 28,932 non-augmented cases had already
passed**, which is the same evidence again that the five attributes do
not see this rounding; and the MPFR campaign, which reported the
mismatches from `aug_add` at fp32. Restored, rebuilt, `api-test` green
again.

**The pre-existing vector sets are byte-identical.** The new pool is a
new function; it must not have perturbed the RNG streams the opcode and
transcendental families draw from. Checked rather than reasoned: the
generator as it stood at ef2348e was run out of a scratch checkout and
its `fp32.jsonl`, `fp32-rtz.jsonl`, `fp32-transcend-rtz.jsonl`,
`fp64.jsonl`, `fp64-transcend.jsonl` compared byte for byte against the
current generator's. Identical.

**Runner.** `bash verify/run.sh --only vectors,libcft,augmented,mpfr,cpp,bindings`
at 04fcb56, run id 20260903-094456-04fcb56: vectors 61 s, libcft 162 s,
augmented 4 s, bindings 15 s, cpp 541 s, mpfr 91 s - **PASS, nothing
skipped.** Repeated on the tree that ships, after the docs above were
committed and with a clean tree: run id 20260903-100057-a019cd5 -
vectors 54 s, libcft 160 s, augmented 5 s, bindings 14 s, cpp 555 s,
mpfr 109 s - **PASS, nothing skipped.** Both runs replayed 44 sets and
724,531 cases and reported 473,480 MPFR cases with zero value and zero
flag mismatches. The wall times are roughly double the earlier entries'
for the same stages, which is the four-agent load on the box and not
the work.

Not run, and why: the RTL stages (`sim`, `lint`, `formal`) and the
`node`/`wasm` stages were outside this work's brief - no opcode was
consumed, no RTL file was touched, and the JavaScript surface is a
separate step that will add the augmented sets to its own replayer. The
`node` and `wasm` replayers already IGNORE an unknown `.jsonl` by name
rather than failing on it, so the four new sets are listed as ignored
there until that step lands.

## 2026-09-03 - the ABI 0.6 census: 28 of 29 on the Windows desktop, with the JavaScript surface in

`bash verify/run.sh --fresh` at e3e6267 on DESKTOP-T33SK86 (Windows,
MINGW64, Docker Desktop for the three container stages), the first
full run with all four 0.6 packages AND the JavaScript surface merged.
Run id 20260903-164537-e3e6267, on a clean tree, 227 minutes wall
beside a CUDA experiment, a UI server and a pool of multiprocessing
workers that were not this run's:

    golden 928s  vectors 1170s  sim 3369s  lint 254s  formal 208s
    libcft 1794s  selfcheck 1s  divsqrt 1s  clause5 2s  character 162s
    transcend 785s  augmented 3s  diff 4s  seq 2s  reduce 13s
    bindings 149s  cpp 1471s  lang-cpp 2s  lang-rust 1s  lang-julia SKIP
    lang-go 13s  lang-csharp 5s  lang-r SKIP  lang-fortran 1s  node 1553s
    wasm 1194s  mpfr 483s  soak-quick 74s  images SKIP

    VERDICT: PASS - 26 executed, 0 failed, 3 skipped by name
    (lang-julia, lang-r, images)

Two of the three skips were the shell's PATH, not the host: julia
1.12.7 and R 4.6.1 are installed, and `bash verify/run.sh --only
lang-julia,lang-r` with both on PATH executed them under run id
20260903-203425-5430990 (the tree two docs-only commits later) -
lang-julia 4 s, lang-r 10 s, both ok, so every language leg
holds bit-identity with the C example. The third skip is `images`,
which needs xclbinutil and is Linux-only.

The counts the stages printed, each the run's own:

| stage | printed |
|---|---|
| golden | 1472 passed, 5 skipped |
| libcft | 1037657 cases replayed through `cft_conformance`, 84 sets |
| divsqrt | 29124 cases, library matches the model exactly |
| clause5 | 145032 comparisons, C == model on every one |
| character | 20819 comparisons, C == model on every one |
| transcend | 607217 comparisons over 39 functions, then 580977 again through the escalation path (`--min-prec 64 --trials 16`), C == model on every one |
| augmented | 140088 comparisons, C == model on every one |
| reduce | the tree, the scaling, the bits and the flags agree |
| bindings | cftmpfr: 755 passed |
| cpp | 211931 checks, C++17 and C++20 |
| node | 1,683,314 cases over 148 set replays - a pass |
| wasm | VERIFY OK, 1,037,657 cases through `cft_conformance` and 645,657 through the wrappers |
| mpfr | 599380 cases, 0 value mismatches, 0 flag mismatches |
| soak-quick | 107886080 cases, 0 value mismatches, 0 flag mismatches |

The transcend stage's two numbers are the two invocations the stage
makes; the four-package gate earlier in the day (run
20260903-121735-8d091ff) printed the same two, because the pools are
seeded by format width and trial count, not by time. The 0.6 top-level
claims in README.md and docs/COMPATIBILITY.md were taken from that
earlier gate and this run reproduces every one of them.

## 2026-09-03 - ABI 0.7 package B: the status word, the conformance predicates, and 9.6's magnitude four

The package: 754-2019 7.1's sticky status word with 5.7.4's six
operations over it, the three conformance predicates of 5.7.1, and the
four magnitude forms of minimum and maximum from 9.6. The first two are
required for a conformance claim (docs/COMPLIANCE.md's items 2 and 3);
the third is recommended, and with it every operation clause 9 lists for
binary formats is present.

`bash verify/run.sh --fresh --only golden,vectors,libcft,clause5,status96,cpp,bindings,mpfr`
at 219e722 on DESKTOP-T33SK86 (Windows, MINGW64, Miniconda's python
first on PATH so the model's stages get mpmath). Run id
20260903-213827-219e722, on a clean tree, 58 minutes wall beside other
agents' work on the same box:

    golden 289s  vectors 299s  libcft 475s  clause5 2s  status96 1s
    bindings 141s  cpp 1447s  mpfr 490s

    VERDICT: PASS, nothing skipped - 8 executed, 0 failed, 0 skipped

The counts each stage printed, and what is new in them:

| stage | printed | of which this package |
|---|---|---|
| golden | 1566 passed, 5 skipped | +94 over 0.6's 1472, all of them `python/tests/test_minmax_mag.py` |
| vectors | 88 sets written | 4 new - `<fmt>-minmaxmag.jsonl`, 2432 cases each |
| libcft | `api-test: all contract checks passed`; 88 sets, 1,047,385 cases replayed through `cft_conformance` | the replay grew from 84 sets / 1,037,657 cases; the four new sets are replayed one element at a time and then as arrays. api-test gained a block of ~90 checks on the word and on 9.6's named rows |
| clause5 | 145,032 comparisons, C == model | unchanged in content, and that is the point: it is the regression check on the routing, since every clause-5 entry point's `flags_out` now comes out of `cft_flags_emit` |
| status96 | 53,517 comparisons, C == model on every one; 45 checks on the word; the predicates 0/0/1 | all of it |
| cpp | 212,019 checks at C++17 and again at C++20, each replaying 1,047,385 cases | up from 211,931: the four through `basic_context` batch and scalar, the tie and NaN rows, one word seen through two contexts, `cft::is754version*` |
| bindings | cftmpfr: 782 passed | +27 over 0.6's 755 |
| mpfr | 714,964 cases, 0 value mismatches, 0 flag mismatches (MPFR 4.2.1) | +115,584 over 0.6's 599,380: 7,224 cases for each of the four operations at each of the four formats |

Model comparisons: `test_minmax_mag.py` is 94 tests over the four
formats, arbitrating the two halves of 9.6's sentence separately. The
magnitude half gets an independent reading of the encoding written from
the format descriptor alone, plus CPython's native binary64 at fp64. The
deferral half is hand-derived from the standard's text, because there is
no external implementation of 2019's minimumNumber to ask - C's
`fmin`/`fmax` are 2008's `minNum`, whose signaling-NaN rule 2019 changed
(the NOTE at the end of 5.3.1).

The MPFR row is the only place in the package where an oracle and a
restatement sit in one function, and `host/tools/mpfr_check.c` says
which is which at the top of the block. The oracle half is MPFR's and
it is the whole numeric content: `mpfr_cmpabs` decides `|x|` against
`|y|`, and `mpfr_min`/`mpfr_max` decide the equal-magnitude case (the
MPFR manual defines those exactly as 754 defines minimum and maximum on
numbers, signed zeros included). The restatement half is the NaN
handling, and it has to be - MPFR has no signaling NaN, and `mpfr_min`
implements only the `...Number` NaN rule, so the plain forms' rule has
no counterpart to compare against.

### The negative controls

Both were run against the built tree and both were restored; `git
status` was clean afterwards, and the gate above ran on the restored
tree.

**1. The OR-in, broken for one entry point.** `cft_next_up` was put back
to the pre-0.7 shape - `if (flags_out) *flags_out = acc;`, reaching no
status word - which is the mistake a future entry point makes by copying
an old one. Nothing else was touched. Two gates caught it and named it:

    api-test.c:2233   FAIL  four flags standing after three calls
    status96          FAIL  minmax_mag_check.py:394, AssertionError on
                            cft_save_all_flags(dev) == DIVBYZERO|INVALID
                            after cft_next_up(sNaN)

Both are the same assertion in two harnesses: three calls raise
overflow+inexact, divideByZero and invalid, and the word must hold all
four. Restored; both green again.

**2. maximumMagnitude preferring y on equal magnitudes of opposite
sign.** The plausible wrong reading of 9.6 - "otherwise, return the
second operand" instead of "otherwise, maximum(x, y)" - applied to
`cft_max_mag` only, leaving `cft_min_mag` and the two `...Number` forms
correct, so the control is as narrow as a real mistake would be. It is
invisible everywhere except on that tie, and five gates caught it:

    api-test.c:2407   FAIL  maximumMagnitude(+3, -3) defers to maximum: +3
    api-test.c:2417   FAIL  max of the two zeros is +0
    libcft (replay)   FAIL  vectors/out/fp32-minmaxmag.jsonl
                            a 0x00000000 b 0x80000000
                            expected 0x00000000, got 0x80000000
    status96          FAIL  max_mag fp32 a=0x0 b=0x80000000:
                            C 0x80000000, model 0x0
    bindings          FAIL  8 tests - test_minmax_mag_matches_the_model
                            and test_minmax_mag_named_rows, all four
                            precisions each
    mpfr              FAIL  44 value mismatches per format in the
                            clause5+9.5+9.6 phase: "MISMATCH fp32 max_mag
                            a=0x00000000 b=0x80000000 lib=0x80000000
                            mpfr=0", and the same for +-inf

The MPFR row is the one worth noting: `mpfr_max` says the answer is `+0`
and `+inf`, so the equal-magnitude rule is scored by MPFR rather than by
a restatement of it.

### What was NOT run, and why

- The RTL stages (`sim`, `lint`, `formal`) and the `selfcheck`,
  `divsqrt`, `character`, `transcend`, `augmented`, `diff`, `seq`,
  `reduce` and `soak-quick` stages were outside this package's gate
  command. No opcode was consumed, no RTL file was touched, and no
  arithmetic changed: the four new operations are host-side selections
  with no opcode, and the status word is inert state that nothing reads
  back. `clause5` WAS run, because it is the regression check that
  matters here - every clause-5 entry point's flag write now goes
  through the new seam.
- The JavaScript surfaces (`node`, `wasm`) were left to the later agent
  that does the JavaScript side, and `bindings/wasm` and `bindings/node`
  were not touched. Both replayers list an unknown `.jsonl` as
  "(ignoring ...)" rather than failing on it, so the four
  `-minmaxmag` sets are ignored there until that step lands.
- The language legs (`lang-*`) were not run: no example changed, and the
  C ABI gained only additive entry points.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md` and the ABI
  version in `cft.h` were deliberately not touched - the integrator does
  those once, for the whole 0.7 step. The header and the docs say "ABI
  0.7" where they describe the new surface; `CFT_ABI_VERSION_MINOR`
  still reads 6.
- No device backend was exercised. The status word is a host-memory
  field on the device handle, written by the host on every path
  including the XRT one, so a card would not change it; the four
  magnitude forms are host operations with no opcode and no pass to
  issue.
- One earlier attempt at this same gate (run id 20260903-213234-f52ebe0)
  was abandoned and its state directory removed. It was killed
  deliberately, four minutes in, because a comment-only commit landed
  while it was running and a census that names one commit while
  compiling another certifies nothing. Its `golden` FAIL marker was that
  kill, not the suite.

Three wording fixes in `cft.h`, `docs/DETERMINISM.md` and
`docs/HOSTAPI.md` were held back until after this run for the same
reason and are the only commit between it and the tip.

## 2026-09-04 - ABI 0.7 package A: 5.4.1's formatOf arithmetic, and the double rounding nobody may use

`bash verify/run.sh --fresh --only golden,vectors,libcft,formatof,status96,cpp,bindings,mpfr`
at 9855955 on DESKTOP-T33SK86 (Windows, MINGW64), run id
20260904-001646-9855955, on a clean tree, beside other work on the same
box:

    golden 373s  vectors 274s  libcft 431s  status96 1s  formatof 5s
    bindings 137s  cpp 1370s  mpfr 480s

    VERDICT: PASS, nothing skipped

The tree is package A merged onto package B (`git merge shared-lanes` at
07c95a3), so this run gates both together; `status96` is here for that
reason and passed unchanged.

### The finding, because it changed a published claim

`docs/COMPLIANCE.md` said at 0.6 that the wide-to-narrow **division and
square root** could be computed in the source format and converted down
- that double rounding through an intermediate of at least 2p + 2 bits
is innocuous for the basic operations, and this ladder satisfies
53 >= 2x24 + 2, 113 >= 2x53 + 2 and 237 >= 2x113 + 2. **The rule does
not apply in this configuration, and the difference is a hypothesis
rather than a margin**: the theorem is about operands carrying the
DESTINATION's precision, and here they carry the SOURCE's. A quotient
or a root of two wide values can sit as close as it likes to a narrow
midpoint, so the first rounding lands exactly on it, the second ties to
even, and the answer is one ulp low with the same flag word. (The
matrix was corrected at b80da94, before this merge.)

`python/cft_golden/formatof.py`'s `double_rounding_witness()` constructs
the counterexample from the format descriptors alone - for division,
square root AND fused multiply-add - on every one of the six ordered
narrowing pairs. All eighteen were built and run, and every one shows
the composed route one ulp below the correct answer. The fused
multiply-add family was run again against intermediate precisions of
30, 53, 64, 113, 237, 400 and 1000 bits, all defeated, which is what
"cannot be double rounded at any width" means when it is measured
rather than asserted. So all six operations narrow the exact way, and
`host/src/formatof.c` carries a restoring division and a
digit-by-digit integer root for the two that needed them - neither of
which the same-format library ever had to form, because `cft_div` and
`cft_sqrt` reach their answers by Newton refinement instead.

Every harness that carries the witnesses asserts BOTH halves of each:
the implementation agrees with the model, and the composed route
disagrees with both. A witness that stopped separating the two would
leave those harnesses checking that two identical things are identical,
so that is a failure rather than a pass.

### The counts each stage printed

| stage | printed |
|---|---|
| golden | 2011 passed, 5 skipped |
| vectors | 168 sets |
| libcft | 168 sets, 1,223,635 cases replayed through `cft_conformance`; api-test green |
| status96 | 53,517 comparisons, C == model on every one |
| formatof | 509,118 comparisons over 16 format pairs, 18 double-rounding witnesses, 8 refusal checks |
| bindings | cftmpfr: 834 passed |
| cpp | 213,691 checks at C++17 and again at C++20, each replaying 1,223,635 cases |
| mpfr | 739,234 cases, 0 value mismatches, 0 flag mismatches |

The formatOf work inside them:

| layer | formatOf |
|---|---|
| `golden` | 445 tests in `python/tests/test_formatof.py` |
| `vectors` | 80 new sets, `<sfmt>-to-<dfmt>-formatof[-<rnd>].jsonl`, 35,250 cases per attribute and 176,250 over the five |
| `libcft` | the replay grew from 84 sets / 1,037,657 cases at 0.6 to 168 / 1,223,635, of which 80 sets and 176,250 cases are this package's and 4 sets / 9,728 cases are package B's |
| `formatof` | 509,118 comparisons: 22,470-22,770 for each same-format pair (which includes the alias check against `cft_run`/`cft_div`/`cft_sqrt`), 18,240-18,480 for each of the six widening pairs, and 51,363 for each of the six narrowing ones, where the pools carry the destination's midpoints and both its boundaries |
| `mpfr` | 24,270 formatOf cases across the sixteen ordered pairs, zero value and zero flag mismatches |

### The status word (package B's 7.1) through these six

All six entry points end at one `cft_flags_emit(dev, acc, flags_out)`;
no raw `*flags_out =` remains in `host/src/formatof.c`. The widening
route runs MUTED, and that is load-bearing rather than tidy: every
`cft_convert`, `cft_run`, `cft_div` and `cft_sqrt` it issues is
internal to one formatOf operation, so without the mute
`cft_formatof_div(1, 0)` would leave its scaffolding's inexact standing
beside the divideByZero, and a widening conversion of a signaling NaN
would put invalid in the word on its own account rather than as part of
the operation. `api_test.c` asserts both, plus that the word
accumulates across formatOf calls, and that a call signalling nothing
neither adds to it nor lowers it.

### The MPFR harness was wrong, and wrong the same way

Worth its own heading, because the first run of this gate
(20260903-230223-0c8884d) came back 7 of 8 with `mpfr` reporting 8
value mismatches and 0 flag mismatches - and the library was right.

Every one had the shape "library says the least subnormal, MPFR says
zero, both say underflow|inexact". At binary64 -> binary32 under
roundTiesToEven, a = `0x8037478c91215dae` (about -2^-968) and
c = `0xb690000000000000` (exactly -2^-150): half of binary32's least
subnormal IS 2^-150, so the exact sum is a hair above it in magnitude
and round-to-nearest delivers -2^-149. Checked against exact rationals,
the model and the library agree; MPFR did not.

`fo_oracle` had reached the destination's subnormal grid through the
MPFR manual's IEEE recipe - set emin to emin - p + 2, redo the
operation at the destination's precision, `mpfr_check_range`,
`mpfr_subnormalize`. That recipe needs the operation's own result to
land at or above the least subnormal's exponent, so that the ternary it
hands `subnormalize` still describes the rounding. A SAME-format sum
always does: both operands are multiples of the format's own smallest
quantum, so a non-zero exact sum is at least that quantum, which is
twice the half-way point - which is why `oracle()` has never hit this
in twenty-four million same-format cases. Across formats it does not.
`mpfr_add` underflowed against the very emin set for it, flushed, and
the ternary stopped carrying the hair. **The oracle was double
rounding**, which is the exact mistake this package exists to refuse.

It now rounds onto the destination's fixed grid explicitly, for all
five attributes, by the construction the same file already used for
9.5's roundTiesTowardZero: truncate toward zero at p + 2 bits with the
exponent range left alone, scale onto the grid, split into an integer
and a fraction with exact arithmetic, compare with one half. The
truncation cannot move the decision, and the argument is in the source.
The boundary is now pinned in two places that are NOT the oracle -
`python/tests/test_formatof.py` builds "a hair above half the
destination's least subnormal" from the two descriptors for every
narrowing pair and every attribute with the exact tie beside it, and
`api_test.c` carries the binary64 -> binary32 row and its negation.

Two smaller things the failure exposed: the harness printed the wrong
operand (the steering makes add and sub read a and c, and the report
always printed b), so the first diagnosis was of a value the case never
touched; and `docs/DETERMINISM.md`'s "MPFR is a full oracle here" now
carries the one footnote it has earned.

### The negative control

`host/src/formatof.c`'s wide-to-narrow fused multiply-add was changed
to round into the SOURCE format first and convert down - the double
rounding this package refuses - and every gate rebuilt explicitly,
since `make all` rebuilds neither `api-test` nor `mpfr-check`:

| gate | caught | the first case it named |
|---|---|---|
| `api-test` | yes | formatOf-fusedMultiplyAdd binary64 -> binary32 gave `0x3f800000`, wanted `0x3f800001` |
| `formatof` | yes | `fp64->fp32 fusedMultiplyAdd rne`: the same BITS, flags `0x10` where the model says `0x18` - the destination's underflow lost, because the source-format rounding was exact |
| `libcft` and `cpp` (the `cft_conformance` replay) | yes | `fp64-to-fp32-formatof.jsonl:3591`, `0x3f800000` for `0x3f800001` |
| `mpfr` | yes | 12 value and 48 flag mismatches at randoms=2, first `fp64 fma rne ->fp32` |
| `bindings` | yes | all six `test_formatof_is_not_a_double_rounding` cases |
| `cpp`'s wrapper checks | no, by design | 213,601 of 213,601 still passed. That test compares the typed path, the raw device method and `cft.h` against EACH OTHER, and the control changes all three identically; its conformance leg is what caught it. |
| `golden`, `vectors` | no, by design | both are model-only, and the control was in the C |

The row worth keeping is `formatof`'s: the first thing it found was not
a wrong value but a LOST FLAG - the destination's underflow, which a
rounding done in the source format never had a reason to raise. A
harness that compared only encodings would have walked past that case
and failed somewhere less informative.

`git checkout host/src/formatof.c`, rebuild, and every one of them is
green again. The control was run before the package-B merge; the merge
changed the flag PATH (through `cft_flags_emit`) and not the
arithmetic, and `api-test` covers the new path directly.

### What was NOT run, and why

- The RTL stages (`sim`, `lint`, `formal`): no opcode was consumed and
  no RTL file was touched. 5.4.1's cross-format forms are library entry
  points over the existing opcodes, and the narrowing direction issues
  no device pass at all.
- `node` and `wasm`: the JavaScript surface is a separate step, as it
  was at 0.6 and as it is for package B's four sets. Both replayers
  list an unknown `.jsonl` as ignored rather than failing on it, so the
  80 `-formatof` sets are ignored there until that step lands.
- `selfcheck`, `divsqrt`, `clause5`, `character`, `transcend`,
  `augmented`, `diff`, `seq`, `reduce`, `soak-quick`, the `lang-*` legs
  and `images`: outside this gate's command. Nothing here changes the
  arithmetic they cover; the six new entry points are additive, and the
  files package A shares with the rest of the library were appended to,
  never edited. `libcft` and `cpp` build and exercise all of it.
- No device backend. The narrowing route is host arithmetic by
  construction; the widening route issues ordinary `cft_run` /
  `cft_div` / `cft_sqrt` passes, which a card would run and which
  nothing here changes.
- `README.md`, `docs/COMPATIBILITY.md` and the ABI version in `cft.h`
  were deliberately left to the integrator, as for package B.
  `CFT_ABI_VERSION_MINOR` still reads 6.
- Two earlier attempts at this gate were abandoned and their state
  directories removed. 20260903-222925-32ebeb0 ran on the pre-merge
  tree and was stopped by PID because package B landed while it was
  running - a census that straddles a source change certifies nothing;
  it had reached `golden` ok 385 s, `vectors` ok 287 s and was inside
  `libcft`'s replay. 20260903-230223-0c8884d is the run whose `mpfr`
  FAIL is dissected above.

## 2026-09-04 - the ABI 0.7 census: the conformance step, every stage the desktop can run

Two runs, and the reason there are two is worth a paragraph.
`bash verify/run.sh --fresh` at d4fe397 - the bump commit, with both 0.7
packages and the JavaScript surface merged, julia and R on PATH this
time - on DESKTOP-T33SK86 (Windows, MINGW64, Docker Desktop for the
three container stages), run id 20260904-035237-d4fe397, on a clean tree,
110 minutes wall with the box quiet:

    golden 397s  vectors 308s  sim 605s  lint 47s  formal 29s
    libcft 450s  selfcheck 1s  divsqrt 1s  clause5 2s  character 156s
    transcend 755s  augmented 3s  status96 0s  formatof 6s  diff 3s
    seq 1s  reduce 12s  bindings 141s  cpp 1497s  lang-cpp 1s
    lang-rust 1s  lang-julia 2s  lang-go 1s  lang-csharp 6s  lang-r 9s
    lang-fortran 1s  node FAIL  wasm FAIL  mpfr 489s  soak-quick 96s
    images SKIP

    VERDICT: 28 executed ok, 2 failed, 1 skipped by name
    (images - xclbinutil is Linux-only)

The two failures were one line each: `node` ("abi (cft.h says):
expected 0.7, got 0.6") and `wasm` ("cftw_abi_version() = 6 (0.6);
cft.h says 7 (0.7)"). The JavaScript step had measured its module on
the tree BEFORE the integrator's bump, so the compiled module carried
6 while the header said 7 - the ordering mistake the 0.6 step avoided
by bumping first, and precisely the mismatch the two replayers exist
to refuse. The module and page were rebuilt on the bumped tree, twice,
in the pinned container - byte-identical: page sha256
`e1b42b3873416e39…` (1,336,073 bytes), module `a1f0a4715516d3f6…`
(211,869 bytes), the same bytes in `bindings/node/cft_node.wasm` - and
committed as 2216e62, where `bash verify/run.sh --fresh --only
vectors,node,wasm` ran as 20260904-054715-2216e62, 55 minutes:

    vectors 333s  node 1656s  wasm 1316s

    VERDICT: PASS, nothing skipped - node 125 passed, 0 failed; 2,055,270 cases over 316 set replays;
    wasm VERIFY OK

Nothing under host/, python/ or vectors/ changed between the two
commits - the rebuild touched two binary files and the runner gained
its `--budget` option - so the 28 library verdicts of the first run
stand for the tree of the second. Together they are the census behind
the conformance statement in docs/COMPLIANCE.md.

The counts the stages printed, each the run's own:

| stage | printed |
|---|---|
| golden | 2011 passed, 5 skipped |
| libcft | 1223635 cases replayed through `cft_conformance`, 168 sets |
| divsqrt | 29124 cases, library matches the model exactly |
| clause5 | 145032 comparisons, C == model on every one |
| character | 20819 comparisons, C == model on every one |
| status96 | 53517 comparisons over 9.6's four magnitude forms, C == model on every one, with the status-word checks |
| formatof | 509118 comparisons over all sixteen ordered format pairs, six operations, five attributes, C == model on every one |
| transcend | 607217 comparisons over 39 functions, then 580977 again through the escalation path, C == model on every one |
| augmented | 140088 comparisons, C == model on every one |
| reduce | the tree, the scaling, the bits and the flags agree |
| bindings | cftmpfr: 834 passed |
| cpp | 213691 checks, C++17 and C++20 |
| node | 125 passed, 0 failed; 2,055,270 cases over 316 set replays - a pass (second run) |
| wasm | VERIFY OK (second run) |
| mpfr | 739234 cases, 0 value mismatches, 0 flag mismatches |
| soak-quick | 107886080 cases, 0 value mismatches, 0 flag mismatches |

## 2026-09-04 - the Collatz explorer: exactness as a result, and the sequencer's second customer

`host/tools/collatz.c` and `host/tests/collatz_check.py` are new;
`docs/COLLATZ.md` is the argument behind them. Nothing under
`host/src/`, `host/include/`, `python/cft_golden/` or `verify/` was
touched, and the ABI version is unchanged - this is a tool over the
existing contract, not a change to it.

The workload iterates n -> n/2 or 3n+1 in binary256, where every
integer to 2^237 is exact and the whole step is `CFT_MUL` by 0.5, one
`CFT_FMA`, and opcodes that round nothing. That makes a printed
stopping time a theorem while the trajectory stays inside the format,
and makes the library's own `inexact` flag the thing that says when it
stops being one.

### What the gate is, and what it scores

`make -C host collatztest` runs a Python big-integer oracle against
the tool. Python's integers are exact, so they are the authority on
Collatz; the library stays the authority on arithmetic. The oracle
models the tool's stopping rule exactly rather than approximately -
including *which* step exactness ran out on - so a tool that gave up
one step early or one step late fails it.

    18103 comparisons, 0 failures
    COLLATZ CHECK OK - the tool, the library and the big-integer oracle agree

| what it checks | result |
|---|---|
| fp256 sweep 1..5000, both engines | 5,000 records each, oracle-exact |
| fp64 sweep 1..5000 | oracle-exact, and byte-identical to fp256's records |
| fp256 / fp64 / fp32 boundary sets, 23 values each | oracle-exact, 15 of the 23 leaving exact arithmetic exactly where the oracle says |
| fp32 sweep 26000..28999 | oracle-exact, the 2 escapes in that window included |
| the hash chain | recomputed with `hashlib`, identical |
| batch 64 / 1000 / 4096 over 1..12000 | byte-identical checkpoints |
| the two engines over the same range | byte-identical checkpoints |
| interrupt and resume, 138 stops | byte-identical to the uninterrupted run |
| a start value the format cannot hold | refused, not rounded |

The interrupt leg runs at `--steps-per-call 7` on purpose, so that
132 of its 138 stops caught elements part way through a trajectory
rather than on a batch boundary; and it resumes at a different batch
size and trip count from the run it is compared against, so it tests
the batch-size property at the same time.

### The measurements

Software backend, single thread, DESKTOP-T33SK86 (Windows 11, MINGW64,
`gcc -O2`), 2026-09-04, box otherwise quiet. `--from 1 --to 100001`,
`--batch 4096`, so every row covers the same 10,753,840 Collatz steps
except the two marked:

| format | engine | steps/s | elements/s | seconds |
|---|---|---|---|---|
| fp256 | program | 587,571 | 5,464 | 18.30 |
| fp256 | loop | 277,210 | 3,022 | 6.62 (20,000 starts) |
| fp128 | program | 779,357 | 7,247 | 13.80 |
| fp128 | loop | 418,520 | 4,562 | 4.38 (20,000 starts) |
| fp64 | program | 886,386 | 8,243 | 12.13 |
| fp64 | loop | 585,119 | 5,441 | 18.38 |
| fp32 | program | 878,145 | 8,178 | 12.23 |

fp256, fp128 and fp64 return the SAME chain over 1..100001,
`cca55ca957433144ebed4047a2beba65d6d53d125c64b70813ba4b37e287f7ae`,
with the published extremes - 350 steps at n = 77031, peak
1,570,824,736 at n = 77671. binary32 returns a different one and says
why: 87 of those 100,000 starting values leave exact arithmetic at
p = 24.

Two numbers worth keeping. The sequencer route is **1.5x to 2.1x
faster than the host `cft_run` loop on the SOFTWARE backend**, where
there is no bus to save - what it saves is 22 dispatches, format
steerings and buffer walks per Collatz step. And throughput is flat in
the batch size (256..16,384) and the trip count (128..8,192), all
within 565,000..600,000 steps/s at fp256: the per-call overhead has
already been engineered away.

The sweep that was run, 230.703 s:

    ./cft-collatz --format fp256 --engine program --batch 8192 \
                  --from 1 --to 1000001 --checkpoint run.ckpt \
                  --checkpoint-interval 30

    1,000,000 starting values, 1,000,000 verified, 0 left exact arithmetic
    longest      524 steps at n = 837799
    largest peak 56,991,483,520 at n = 704511
    steps        131,434,424
    library calls 123
    flags seen   0x00
    throughput   569,713 steps/s, 4,334.6 elements/s
    chain        966d0d7d23e92751490063609810b55577611e01e14da54822a3993e5db6e08f

Both extremes are the published values for that range. **123 library
calls for a million trajectories** is the sequencer's contribution as
a number.

### What the writing of it found

Two things, and the first is the reason the boundary set exists.

**"Above 2^p it has left exactness" is false**, and assuming it costs
correct proofs. For odd n, 3n+1 is even, and an even integer one bit
wider than the format still fits: a trajectory routinely climbs past
2^p, halves back down, and every step of it is exact. Not one of the
9,999 starting values below 10,000 escapes at binary32 even though many
peak above 2^24; the first that does is 26623.

**The first version of the tool read a value above 2^p as odd.** The
parity test is `(bits >> ((p-1) + bias - biased_exp)) & 1`, and that
shift goes negative - and wraps - once E exceeds p-1. Above 2^p there
is no units bit in the significand and every representable value is
even, so two more opcodes now say so. Before the fix, 2^237 - 3
stopped after 1 exact step where it manages 8. The flag/witness
assertion did **not** catch that, and correctly so: the fused
multiply-add really was inexact and the tool really did detect it -
what was wrong is that the element should never have taken that branch.
Only the oracle knew.

### The negative control

Two faults, each rebuilt and run through the same gate.

| control | what was changed | caught by | first thing it said |
|---|---|---|---|
| A | the two opcodes clamping parity to "even" above 2^p deleted from both engines | the oracle, on 4 of the check's 19 rows - all four boundary sets | `fp256 boundary set: got '...469 1 ...408 ...408 esc', oracle says '...469 8 ...408 ...991 esc'` |
| B | the witness `CMPEQ(res, 1.0)` weakened to `CMPLE(0.0, res)` in both engines | the flag/witness assertion in the loop engine, the oracle in the program engine | `the INEXACT flag (1) and the per-element exactness witness (0 escapes) disagree` |

Control A leaves every ordinary sweep, the chain, the batch-size
property and the resume property green, and both engines still agree
with each other - they are wrong identically. Only the boundary set
fails. That is the case for an independent oracle rather than internal
consistency alone, and it is not hypothetical: control A is the bug
the tool actually had.

Control B is the more interesting row. The **host loop** aborted with
exit 3 on its first step, because it checks the biconditional once per
Collatz step and the one rounding element was the only thing in the
call. The **sequencer program** did not abort: it checks once per call
of up to 1,024 iterations over 23 elements, and another element's
correct detection satisfied the union - so 2^237 - 1 sailed on with a
rounded value and reported a 245-step "verified" trajectory that does
not exist, which the oracle then caught. The honest statement is that
the flag/witness biconditional is **necessary and not sufficient**:
the coarser the call, the more a partly-broken witness can hide behind
another element's escape. It is a cheap continuous gate, not a
substitute for the oracle, and the two caught this control in two
different places.

Restoring the file, rebuilding, and the gate is green again at 18,103
comparisons.

### What was NOT run, and why

- No device, in emulation or otherwise. The tool takes `--artifact`
  and issues the same program either way, but nothing here has been
  through XRT; `docs/BRINGUP.md` owns those gates. No device number is
  quoted.
- The RTL stages (`sim`, `lint`, `formal`): no opcode was added and no
  RTL file touched. The program uses `CFT_MUL`, `CFT_FMA`, `CFT_ADD`,
  `CFT_MIN`, `CFT_MAX`, `CFT_SELECT`, `CFT_CMPLT`, `CFT_CMPEQ`,
  `CFT_ISHR`, `CFT_ISUB`, `CFT_IAND` and `CFT_ICMPLT`, all of which
  `tb/` and the vector sets already cover, and the six control codes
  `tb/test_seq_core.py` already scores.
- The rest of `verify/run.sh`: nothing under `host/src/` changed, so
  the library gates certify the same library they certified this
  morning. No runner stage was added; `verify/run.sh` was deliberately
  left alone.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md` and the
  ABI version were left to the integrator, as at 0.7.
