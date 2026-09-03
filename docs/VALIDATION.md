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
under Verilator, run twice back to back by tb/box_parallel_sim.sh:

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
