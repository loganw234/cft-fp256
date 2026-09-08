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

    18107 comparisons, 0 failures
    COLLATZ CHECK OK - the tool, the library and the big-integer oracle agree

| what it checks | result |
|---|---|
| fp256 sweep 1..5000, both engines | 5,000 records each, oracle-exact |
| fp64 sweep 1..5000 | oracle-exact, and byte-identical to fp256's records |
| fp256 / fp64 / fp32 boundary sets, 24 values each | oracle-exact, 15 of the 24 leaving exact arithmetic exactly where the oracle says |
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
there is no bus to save - what it saves is 23 dispatches, format
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

Restoring the file, rebuilding, and the gate is green again at 18,107
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

## 2026-09-04 - the enclosure tool: the directed roundings put to work, and what fp64 has left

`host/tools/enclose.c` and `host/tests/enclose_check.py` are new;
`docs/ENCLOSE.md` is the argument behind them. Nothing under
`host/src/`, `host/include/`, `python/cft_golden/` or `verify/` was
touched, and the ABI version is unchanged - this is a tool over the
existing contract, not a change to it.

The workload is verified computing. Compute a quantity once under
`roundTowardNegative` and once under `roundTowardPositive` and the true
value is provably between the two, because each result is correctly
rounded and each rounding is monotone. That needs all five attributes,
per call and - in the sequencer - per instruction, which is a half of
this contract nothing else here exercises. And because the arithmetic is
deterministic, two machines produce the SAME interval rather than two
overlapping ones: **an enclosure produced by this tool is the same bits
on every conforming host, so a verified result can be reproduced rather
than merely re-derived.**

Three kernels. A series for `exp(x)` over dyadic x in [0,1] with the
tail bounded by `t_N/N` and charged to the upper end only, its term
count derived from the format's measured p (10 at binary32, 18 at
binary64, 31 at binary128, 54 at binary256). Dot and matrix-vector
products through `cft_reduce` under both attributes, over vectors of
dyadic rationals mirrored so the exact answer is 1 however violent the
cancellation. And an interval Horner with interval coefficients, which
is the one that runs as an orbit-sequencer program.

### What the gate is, and what it scores

`make -C host enclosetest` scores every interval against a value Python
computes without rounding: exact `fractions` for the dot products and
the polynomial (both are rationals, because every input is dyadic),
mpmath at 300 digits for `exp` - about 228 decimal digits more than a
binary256 enclosure carries, so the comparison is never close. The
library stays the authority on arithmetic; Python is the authority on
the domain.

    2658 comparisons, 0 failures
    ENCLOSE CHECK OK - every enclosure contains the value the oracle
    computed, and the same bits come out at every batch size, from
    either engine, interrupted or not

| what it checks | result |
|---|---|
| containment, fp256 / fp64, all three kernels, 145 items each | every interval contains the exact value |
| containment, fp256 Horner through the loop engine | same |
| containment, fp32 series and Horner, 130 items | same |
| containment, fp32 series at 2048 points, where the terms go subnormal | 2,049 intervals, all containing exp(x), flag word 0x18 |
| the interval coefficients contain 1/k! | 24 of 24, at every format |
| tightness | every width inside its rounding budget - a few thousand ulps for the point kernels, a few ulps per addition of the largest partial magnitude for the dot kernel |
| the exact-by-construction dot product | width zero, both bounds ARE the rational, flag word clean |
| the two Horner engines, fp256 and fp64 | byte-identical records at different batch sizes |
| batch 7 / 64 / 1024 | byte-identical checkpoints AND byte-identical record streams |
| interrupt and resume, 41 stops at a different batch size | byte-identical to the uninterrupted run |
| the hash chain over 145 records | recomputed with `hashlib`, identical |
| four refusals | a degree the constant bank cannot hold, a non-power-of-two point count, a format whose exponent range cannot carry the ladder, an unknown kernel |

The interrupt leg runs at `--stop-after-passes 4` against a 54-term
series on purpose, so that 40 of its 41 stops caught an item part way
through its recurrence, with partly summed terms in flight, rather than
on a batch boundary.

### The measurements

Software backend, single thread, DESKTOP-T33SK86 (Windows 11, MINGW64,
`gcc -O2`), 2026-09-04. `--points 2048 --batch 256`, so every row is
4,113 enclosures except binary32's 4,098 - it runs `--kernels
series,horner`, because it cannot express the dot ladder.

| format | enclosures/s | element-ops/s | library calls | seconds |
|---|---|---|---|---|
| fp256 | 1,821 | 389,150 | 2,991 | 2.259 |
| fp128 | 5,097 | 738,901 | 1,749 | 0.807 |
| fp64 | 11,660 | 1,237,434 | 1,047 | 0.353 |
| fp32 | 25,441 | 2,086,129 | 585 | 0.161 |

An enclosure is one item with BOTH bounds computed. Throughput is flat
in the batch size - 64, 256, 1,024 and 4,096 all land between 1,669 and
1,897 enclosures/s at fp256, with no trend - and all four return the
same chain, `2a4f7fa58560dac13b59879406d914768db27531c9829a23cd50dffcf6cf5ade`.

The Horner kernel alone, 8,193 enclosures at `--batch 512`: the
sequencer program is **1.19x to 1.41x faster than the host `cft_run`
loop on the software backend**, where there is no bus to save - 48,502
against 34,505 enclosures/s at fp256, 79,992 against 67,055 at fp64,
and **51 library calls against 1,649**. The margin is smaller than the
Collatz explorer's 1.5x-2.1x for a plain reason: a Horner step is four
opcodes against that workload's twenty-three, so there is less per-call
overhead per unit of work to remove. Both engines return the same chain.

The sweep that was run, 20.081 s:

    ./cft-enclose --format fp256 --points 16384 --batch 512 \
                  --checkpoint run.ckpt --checkpoint-interval 30 \
                  --csv run.csv

    32,785 enclosures, 9 of them exact, flags seen 0x10 (inexact only)
    widest series width  9.59902e-70
    widest horner width  3.62228e-71
    widest dot width     3.13215e-53
    dot enclosures straddling zero: 0
    throughput  1,633 enclosures/s, 349,323 element-ops/s
    chain       573609c0a0befe28f576dbd2cef79cf0bb16c6477ed8b39aae1fae5870e83c7e

The same command at fp64 takes 3.264 s and returns chain
`cdead7ef4138b108ca7c7f175577ea3bcae46b229e191b5eb66d678e39cd06a8`,
with **14 of its 15 dot enclosures straddling zero**.

### fp64 against fp256, in numbers

e, enclosed by the series with its rigorous tail:

| format | terms | width of the enclosure of e |
|---|---|---|
| fp32 | 10 | 2.1e-6 |
| fp64 | 18 | 7.5e-15 |
| fp128 | 31 | 1.2e-32 |
| fp256 | 54 | **9.6e-70** |

The widest width per kernel over the same 2,048 points: series 7.99e-15
at fp64 against 9.60e-70 at fp256 (a factor of 2^182), Horner 8.88e-16
against 3.62e-71 (2^184), dot 2.18e+3 against 3.13e-53 (2^186).

The ill-conditioned dot products are the row that matters. Every one of
them has the exact value **1** and a condition number near 2^60-2^66:

| case | fp64 | fp128 | fp256 |
|---|---|---|---|
| `cancel-spread0` | [-0, 256] | [1, 1] | [1, 1] |
| `cancel-spread90` | [-768, 512] | [1, 1] | [1, 1] |
| `cancel-spread225` | [-742.82, 793.19] | width 1.0e-15 | width 2.1e-53 |
| `matvec-row2` | [-1152, 1024] | width 1.1e-15 | width 1.0e-53 |

binary64's answer is not wrong; it is honest and useless. The interval
does contain 1 - it also contains 0 and -700, so it does not determine
the sign of the answer. Fourteen of the fifteen are like that, and a
non-interval binary64 dot product would print a single number somewhere
in that range with no indication that anything was wrong. binary256
returns the exact rational with the flag word clean on six of the
fourteen, and about 1e-53 on the rest.

It is worth recording the other half honestly: **on the two point
kernels fp64's enclosures are perfectly usable.** 7.5e-15 for e is
fifteen good digits, and a reader who needs fifteen digits should use
binary64 and enjoy the 6.4x throughput. What binary256 buys is the
regime where the CONDITIONING rather than the answer sets the precision
needed.

### What the writing of it found

**Three observations about the program model, and one of them is a
limit.** A sequencer instruction names its operands in four-bit fields,
and `ka`/`kb`/`kc` redirect those same fields at the constant bank - so
a program addresses exactly **sixteen constants**, whatever `n_consts`
in its header says. An interval coefficient costs two, so one program
holds eight coefficients, which is why the Horner kernel is compiled
into chunk programs of eight steps and why `--degree` refuses anything
that does not make `degree + 1` a multiple of eight. That is a real
ceiling on any table-driven kernel; `imm` is already 32 bits wide and
unused by ALU instructions, so a `ka`-with-`imm`-index form would cost
no encoding space. The other two are the ones `docs/COLLATZ.md` already
recorded: three input streams and no fourth (exactly enough here -
point, lower bound, upper bound - by luck rather than design), and no
way for one program to call another, which is what keeps the series
kernel's `cft_div` out of the ISA.

**Underflow is expected, not forbidden.** The first flag policy stopped
the run on it. That was wrong: the series' terms are `x^k/k!`, so a
small x in a narrow format reaches the subnormal range - at binary32 an
x of 2^-11 gets there by the tenth term - and tininess costs the
enclosure nothing, because a directed rounding of a subnormal is still
correctly rounded. The lower chain stays below the true term (it may
reach +0, which is still below) and the upper chain stays above it,
since `roundTowardPositive` cannot carry a positive value to +0, so the
tail bound survives. The check script now runs binary32 at 2,048 points
on purpose to exercise the case.

**A batch-wide call needs a batch-wide operand.** The loop engine handed
`cft_run` the scalar zero as the first operand of a `CFT_CMPLE` over n
elements, and `cft_run` reads n elements from every operand it is
given. Small batches survived it; batch 37 walked off a 32-byte
allocation and the process died. Neither the oracle nor any internal
gate caught that one - the operating system did - but it was the check
script that ran the loop engine at a batch size the smoke tests had not.

**The mirroring needs a permutation.** The first ill-conditioned
construction put the mirrored block at a fixed offset, and the
contractual tree then cancelled the two halves against each other at a
single node: exact, tidy, and testing nothing. Twelve of fifteen dot
products came back with width zero at binary64. One shared permutation
of x and y leaves the exact answer alone and destroys the structure the
tree was exploiting.

### The negative control

Two faults, each rebuilt and run through the same gate.

| control | what was changed | caught by | first thing it said |
|---|---|---|---|
| A | `CFT_RUP` to `CFT_RDN` on the Horner kernel's upper-bound FMA, in BOTH engines | the oracle alone, on 245 containment rows | `horner item 0 does not contain the true value (lo 0.36787944117144233, hi 0.36787944117144233)` |
| B | `cft_reduce`'s RDN and RUP swapped in the dot kernel | the tool's own `lo <= hi` gate, before a record was written | `an enclosure came back with its ends the wrong way round - a rounding attribute is wrong` |

Control A is the instructive one. Every internal gate passes, and each
for a good reason: `lo <= hi` holds because both chains now round the
same way; the two engines agree because both were sabotaged; the
batch-size property, the resume property, the chain and the refusals
are untouched; and the flag/width certificate is *satisfied*, because
the widths really are zero. The tool then reports

    horner        9 enclosures, 9 exact (both bounds ARE the value)
                  widest 0 at item 0

which is a confident, self-consistent claim that every value it
computed is exactly representable and that both of its bounds are it.
Only the oracle knows otherwise. The honest statement is:

> Every internal check in this tool is a CONSISTENCY check, and control
> A does not make the tool inconsistent - it makes it consistently
> compute the wrong thing. Only an independent computation of the true
> value can tell you that an interval does not contain it, which is why
> the oracle computes in exact rationals rather than by rerunning the
> library.

Control B never reaches an oracle: the internal gate fires on the first
ill-conditioned item and the harness reports it as a result rather than
a crash, five rows at once. Restoring the file, rebuilding, and the gate
is green again at 2,658 comparisons, 0 failures.

### What was NOT run, and why

- No device, in emulation or otherwise. The tool takes `--artifact` and
  issues the same program either way, but nothing here has been through
  XRT; `docs/BRINGUP.md` owns those gates. No device number is quoted.
- The RTL stages (`sim`, `lint`, `formal`): no opcode was added and no
  RTL file touched. The Horner program uses `CFT_CMPLE`, `CFT_SELECT`
  and `CFT_FMA`, and the control codes `DEPOSIT` and `HALT`, all of
  which `tb/` and the vector sets already cover. The per-instruction
  rounding attribute this workload leans on is already benched:
  `tb/test_seq_core.py`'s `constants_and_rounding` runs adjacent RDN
  and RUP FMAs against the model precisely because "the interval
  pattern is the reason the attribute is per instruction rather than
  per run". This tool is the first APPLICATION of that pattern; the
  RTL case for it was written before the application existed.
- The rest of `verify/run.sh`: nothing under `host/src/` changed, so the
  library gates certify the same library. No runner stage was added;
  `verify/run.sh` was deliberately left alone.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md`,
  `docs/BENCHMARKS.md` and the ABI version were left to the integrator,
  as at 0.7.

## 2026-09-04 - the Mersenne verifier: exactness as a flag, and the width paying for itself

`host/tools/mersenne.c` and `host/tests/mersenne_check.py` are new;
`docs/MERSENNE.md` is the argument behind them. Nothing under
`host/src/`, `host/include/`, `python/cft_golden/` or `verify/` was
touched, and the ABI version is unchanged - this is a tool over the
existing contract, not a change to it.

The workload is Lucas-Lehmer, `s_{k+1} = s_k^2 - 2 mod (2^P - 1)`. A
squaring is a convolution of limbs, and `cft_reduce(CFT_DOT)` **is**
that convolution: while every partial sum of its contractual tree stays
below 2^p no node rounds, so `flags == 0` over a coefficient is a
certificate - issued by the library - that the coefficient is the exact
integer sum. That is the property GIMPS has to rebuild with Gerbicz
error checking and an independent double-check, because a
floating-point FFT is fast but not exact.

The limb geometry is derived from p and the exponent in one function
and nowhere else: `2b <= p` for a product, `L * 2^(2b) <= 2^p` for a
coefficient, `d + 2 <= b` so the fold's scale by `2^d` cannot overflow,
with `L = ceil(P/b)` and `d = L*b - P`. At binary256 that lands on
102-116 bit limbs, which is about four times less work than the
symmetric 59-bit split would be.

### What the gate is, and what it scores

`make -C host mersennetest` runs a Python big-integer oracle against
the tool. It is a stricter join than the Collatz check's, because a
Lucas-Lehmer verdict is one bit and one bit is easy to get right by
accident: the oracle recomputes `s_k` for **every** k the tool dumps
and compares the **whole residue** - res64 plus a SHA-256 over every
canonical limb - so a wrong carry shows at the first squaring that
breaks it rather than 1,275 squarings later.

    388 comparisons, 0 failures
    MERSENNE CHECK OK - the tool, the library and the big-integer oracle agree

| what it checks | result |
|---|---|
| verdicts, squaring counts and res64 at fp256 (both engines) and fp64 | 5 exponents each, oracle-exact, **3 prime and 2 composite** |
| every intermediate residue, whole | 251 at fp256/program, 36 at fp256/loop, 61 at fp64, 11 at fp32 |
| the two engines | identical chain, identical checkpoint |
| fp32 / fp64 / fp128 / fp256 | the same chain - the record carries no format |
| the hash chain | recomputed with `hashlib`, identical |
| batch 3 / batch 4096 / host loop at batch 11 | byte-identical checkpoints |
| interrupt and resume, 17 stops, all mid-exponent | byte-identical to the uninterrupted run |
| the exactness bound | 15 selftest probes; a forbidden `--limb` refused before any arithmetic; `--unsafe-limb` stopped by the library's `inexact` |

The composite controls are the half that is easy to leave out: **1277
and 1619 are prime exponents whose Mersenne numbers are not prime**, so
a tool that always answered "prime" would pass a test set of Mersenne
primes alone and fail here. Their res64 values, `5613a480590e78ba` and
`3f964611757ce4e0`, are what an unrelated implementation prints.

### The measurements

Software backend, single thread, DESKTOP-T33SK86 (Windows 11, MINGW64,
`gcc -O2`), 2026-09-04, other work sharing the box (repeat runs within
~5%).

The whole known set - eleven Mersenne prime exponents up to 11213 and
the two composite controls - in **212.285 s**:

    ./cft-mersenne --set known --format fp256 --engine program --batch 4096 \
                   --checkpoint run.ckpt --checkpoint-interval 30

    52,497 squarings, 270,377,166 limb products, 7,484,340 library calls
    flags seen   0x00
    status word  0x00 (agrees with the union above)
    throughput   1,273,651 limb products/s, 247.3 squarings/s
    chain        851b85d1e262b0f1e887f641f25bd684df1384d9c128e991646c3f9a18eed9cf

**270 million exact 115-bit limb products and not one raised a flag.**

fp256 against fp64, same tool, same chain, at P = 1279 / 2203 / 4423:

| P | fp64 / fp256 limb products | fp64 / fp256 wall time |
|---|---|---|
| 1279 | 21.8x | 7.4x |
| 2203 | 25.5x | 10.7x |
| 4423 | 29.3x | 12.7x |

fp64 is *faster per limb product* (2.08M/s against fp256's 0.71M/s at
P = 1279) and much slower overall, because its 53-bit significand
forces 23-bit limbs where fp256 carries 107. **A wider format is the
cheaper way to buy exactness on this workload**, which is the opposite
of the usual intuition. fp32 at P = 1279 needs 160 limbs of 8 bits:
177.8x the limb products and 50x the wall time. Every rung is exact and
every rung returns the same chain; what the narrow ones lose is
throughput, not correctness.

The sequencer route is **1.02x to 1.27x** faster than the host loop
here, where docs/COLLATZ.md measured 1.5x to 2.1x on the same backend.
That is structural: in Collatz the program is the whole step, and here
it is only the carry split. The convolution cannot be a program at all
- a coefficient is a cross-element reduction and the carry chain reads
a neighbour, and a lane has no path to another lane - so most of the
time is in `cft_reduce`, which is identical in both engines.
docs/MERSENNE.md records what would change that: a lane shift, or a
cross-lane reduction inside a program.

### What the writing of it found

**The split's witness leaves a hole, and it took a negative control to
see it.** The witness proves `v == hi*B + lo` with `0 <= lo < B`, which
does *not* pin `hi` down: `v = 3B/2` satisfies it at `(1, B/2)` and
equally at `(1.5, 0)`. A shift amount off by one produces the second -
exactly, raising nothing, witness green - and the error then rides in
the limbs. The dot only notices when the extra fractional bits push a
coefficient past 2^p, which at `b = 105, L = 5` they never do.

So there is now a third gate: once per squaring, over the L limbs that
are the only state crossing between squarings,
`(y + 2^(p-1)) - 2^(p-1) == y`. The magic-constant round the carry
split could not use is exactly the right instrument there, because a
limb below 2^b is far below 2^(p-1) and the addition is exact if and
only if the limb is an integer - the `inexact` it would raise IS the
answer rather than noise to be masked. It costs 3.7% of the elementwise
issues at P = 3217, inside the timing noise, and the chain is unchanged.

### The negative controls

Three faults, each rebuilt and run through the same gate, and each
caught by a **different** layer.

| control | what was changed | caught by | first thing it said |
|---|---|---|---|
| A | the `t < 1` guard deleted from the carry split, in both engines | the **flag word**, on the first squaring, at all four formats | `the carry add raised 0x10 (inexact) ... the residue is REFUSED, not reported` |
| B | the split's shift constant `(p-1) + bias` becomes `p + bias`, so the shift reaches one bit past the significand into the low bit of the biased exponent and `hi` comes back HALVED | the **limb integrality gate** - not the witness, which is perfectly satisfied by `(0.5, v - B/2)` | `the limb integrality gate raised 0x10 (inexact)` |
| C | the recurrence's `2^P - 3` becomes `2^P - 2`, so it subtracts 1 instead of 2 | **only the oracle** | `residue after squaring 1 differs - tool res64 ...0010, oracle res64 ...000e` |

Control A is the honest ordering, and worth recording: for that bug the
flag is the *faster* detector, because a fractional `hi` makes
`lo = fma(hi, -B, v)` inexact and the check fires inside the split
before the witness is looked at. Twenty-one of the check's twenty-two
rows fail; only the four bound probes pass, since they carry nothing.

Control C is the one that makes the case for an oracle. **Every
internal gate stays green**: flags `0x00`, status word `0x00`, the
witness satisfied on every element of every pass, the integrality gate
satisfied on every limb, both engines in exact agreement, all four
formats in exact agreement, batch-size independence holding, and
interrupt/resume landing on a byte-identical checkpoint. The tool then
reports `2^521 - 1 COMPOSITE, res64 0000000000000002`, which is wrong.
Stated plainly:

> The flag word certifies that no operation rounded. The witness
> certifies that the split reconstructs. The integrality gate certifies
> that a limb is an integer. None of the three certifies that the tool
> is computing the Lucas-Lehmer sequence, and control C is a tool that
> is exactly, reproducibly, deterministically computing the wrong
> recurrence.

Restoring, rebuilding and re-running is green again: **382 comparisons
at `--quick`, 388 at the default size, 397 at `--full`, 0 failures**.

### GIMPS, stated honestly

The doc carries the arithmetic rather than a slogan. At this tool's own
measured rate, the current record exponent (P = 136,279,841) would need
`L = 1,185,043` limbs, `1.91 x 10^20` limb products and **4.2 million
years** on one thread - about nine orders of magnitude against a GIMPS
client's day on one GPU, ten against the parallelism one really uses.
It splits into `10^4.8` of algorithm (a direct convolution is `L^2`, an
FFT about `L log2 L`) and `10^5`-`10^6` of hardware. The algorithmic
half is the **price of the certificate**: an FFT's twiddle factors are
irrational, which is exactly why GIMPS needs Gerbicz checking and a
double-check. The exact sub-quadratic route is Karatsuba - 330x fewer
limb products at that size, certificate intact - and it is not built.

What the exactness buys instead is that the rounding class of error is
*gone* rather than bounded, and that a re-run is a reproduction rather
than a second opinion. It buys nothing against a bit flip, and the doc
says so.

### What was NOT run, and why

- No device, in emulation or otherwise. The tool takes `--artifact` and
  issues the same program either way, but nothing here has been through
  XRT; `docs/BRINGUP.md` owns those gates. No device number is quoted.
- The RTL stages (`sim`, `lint`, `formal`): no opcode was added and no
  RTL file touched. The split program uses `CFT_MUL`, `CFT_ISHR`,
  `CFT_ISUB`, `CFT_ISHL`, `CFT_CMPLT`, `CFT_SELECT`, `CFT_FMA`,
  `CFT_NEG`, `CFT_CMPEQ`, `CFT_MIN` and `CFT_CMPLE`, all of which `tb/`
  and the vector sets already cover, and the control codes `DEPOSIT`
  and `HALT` that `tb/test_seq_core.py` already scores.
- The rest of `verify/run.sh`: nothing under `host/src/` changed, so
  the library gates certify the same library. No runner stage was
  added; `verify/run.sh` was deliberately left alone.
- Of the device-era exponents (19937, 21701, 23209, 44497), only
  **19937** was run - and it was run to a verdict: **2^19937 - 1 is
  PRIME**, the twenty-fourth Mersenne prime, 6,002 decimal digits,
  19,935 squarings and 610 million exact limb products across THREE
  separate invocations (300 s, then 60 s, then 53 s) with the
  checkpoint carrying the residue between them and flags 0x00
  throughout. Python's big integers agree, verdict and res64. 21701,
  23209 and 44497 were not run; 44497 is about eleven times 19937's
  work, which is 80 minutes here.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md` and the
  ABI version were left to the integrator, as at 0.7.

## 2026-09-04 - the orbit integrator: the roundoff floor and the method's error, measured apart

`host/tools/orbits.c` and `host/tests/orbits_check.py` are new;
`docs/ORBITS.md` is the argument behind them. Nothing under
`host/src/`, `host/include/`, `python/cft_golden/` or `verify/` was
touched, and the ABI version is unchanged - this is a tool over the
existing contract, not a change to it.

The workload integrates the Kepler two-body problem and the outer
solar system with Stormer-Verlet and with Yoshida's fourth-order
composition of it, every arithmetic step through libcft, at any of the
four formats, over an ensemble of copies perturbed by an exact integer
number of ulps.

It is here because it has two error sources that behave completely
differently, and it separates them into two numbers rather than
reporting their sum:

- the **energy** drift is the METHOD's, and comes out identical at
  binary64 and binary256 to every digit printed;
- the **angular-momentum** drift is the ARITHMETIC's alone, because
  both schemes conserve total angular momentum exactly in exact
  arithmetic - a drift adds `m c (v x v) = 0`, and the kick's pair
  term cancels because `m_i g_ij = h G m_i m_j / r^3` is symmetric,
  which is Newton's third law written in the arithmetic.

### What the gate is, and what it scores

`make -C host orbitstest` runs a 300-digit mpmath oracle against the
tool, in two roles that are deliberately kept apart. The **same
discrete scheme** at 300 digits, from the tool's own starting
encodings and the tool's own derived constants, whose difference from
the run is the format's ROUNDOFF and nothing else. And the **closed
form** through Kepler's equation, whose difference from the discrete
solution is the method's TRUNCATION error.

Keeping "the same constants" honest is what `--dump-setup` is for: `h`
is `fl(2*pi/S)` and the drift scale is `fl(fl(w*h)*0.5)`, so an oracle
using the exact real numbers would be charging the constants' rounding
to the integration. The tool prints every derived constant as an exact
decimal and the oracle integrates with those.

    26 checks, 0 failures
    ORBITS CHECK OK - the tool, the library and the 300-digit oracle agree

| what it checks | result |
|---|---|
| roundoff, fp256 and fp64 against their own 300-digit twins | `5.500e-68` and `1.050e-12` over 2,048 steps; ratio `1.91e55` against `2^184 = 2.45e55` |
| truncation, and both schemes' orders | halving `h` cuts the error from the closed form by **3.99** (leapfrog, order 2) and **15.96** (yoshida4, order 4) |
| the roundoff floor against the truncation error | fp256's is `5.52e64` times below leapfrog's, `8.68e61` below yoshida4's |
| `H0` and `L0` at sample 0 | 0.6 and 0.0 ulps of binary256 from the 300-digit values |
| the initial condition | `a - 1 = 4.2e-71`, `e - 3/4 = 1.1e-71` |
| the angular-momentum certificate | bounded by `steps^2 2^-p 10^6` for both problems and both schemes |
| the outer solar system against its 300-digit twin | `3.118e-70` at fp256, `3.707e-15` at fp64 - a factor of `1.19e55` |
| the transcribed table, against the sky | osculating periods within 0.01% (Jupiter) to 0.75% (Neptune) of the published sidereal periods |
| the hash chain | recomputed with `hashlib`, identical |
| batch 8 / 3 / 1 | byte-identical checkpoints |
| the sequencer program against the host loop | byte-identical records AND checkpoints |
| interrupt and resume, 6 stops, 5 of them mid sample interval | byte-identical checkpoint and records to the uninterrupted run |
| the three things `--engine program` must refuse | refused, each with its reason |

The interrupt leg stops every 37 steps on purpose, which does not
divide the 96-step sample interval, so most stops catch the ensemble
part way through one; the checkpoint is step-granular for that reason.

### The measurements

Software backend, single thread, DESKTOP-T33SK86 (Windows 11, MINGW64,
`gcc -O2`), 2026-09-04, box busy with other work.

**The result the workload exists for.** 2000 Kepler periods at 512
steps a period - 1,024,000 steps - over four ensemble members:

| scheme | format | energy drift | angular-momentum drift | seconds |
|---|---|---|---|---|
| leapfrog | fp256 | `7.94534e-4` | `9.00177e-69` | 133.6 |
| leapfrog | fp64 | `7.94534e-4` | `1.44687e-13` | 64.0 |
| yoshida4 | fp256 | `2.04280e-5` | `6.91390e-69` | 399.9 |
| yoshida4 | fp64 | `2.04280e-5` | `2.20051e-13` | 204.8 |

The energy column is identical across formats and 38.9x apart across
schemes. The angular-momentum column is `1.61e55` and `3.18e55` apart
across formats - `2^184` is `2.45e55` - and within 30% across schemes.
**The same roundoff floor under two different truncation errors**,
which is what carrying two schemes was for.

The outer solar system over 300 years at a 10-day step, eight members,
says the same thing: `dH = 4.02616e-6` (leapfrog) and `2.52287e-9`
(yoshida4) at BOTH formats, against `dL` of `4.44569e-70` /
`1.70779e-14` and `1.12624e-69` / `2.45873e-14`.

**The floor across the whole ladder**, 64 periods, leapfrog:

| format | p | energy drift | angular-momentum drift |
|---|---|---|---|
| fp32 | 24 | `7.89642e-4` | `1.34269e-5` |
| fp64 | 53 | `7.92692e-4` | `4.49838e-14` |
| fp128 | 113 | `7.92692e-4` | `2.02365e-32` |
| fp256 | 237 | `7.92692e-4` | `7.87227e-70` |

`dL` tracks `2^-p` across four rungs to within a factor of two, and
**binary32 is the rung where the columns stop being independent** -
its energy drift disagrees with every wider format's in the fifth
digit, because at `p = 24` the roundoff has grown into the truncation
measurement. Locating that crossover is what the workload is for; at
binary256 it is `2^213` further away.

**Throughput**, 16 members, 8,192 Kepler steps:

| scheme | 1/r^3 | format | engine | seconds | element-steps/s | library calls |
|---|---|---|---|---|---|---|
| leapfrog | exact | fp256 | loop | 3.720 | 35,233 | 90,395 |
| leapfrog | exact | fp64 | loop | 1.570 | 83,487 | 90,395 |
| leapfrog | newton | fp256 | loop | 1.656 | 79,150 | 295,195 |
| leapfrog | newton | fp256 | **program** | 1.376 | 95,263 | **284** |
| yoshida4 | exact | fp256 | loop | 10.853 | 12,077 | 270,619 |

binary256 costs **2.4x** binary64 here, not the 30x a significand
argument predicts; correct rounding (`cft_sqrt` + `cft_div`) costs
**2.2x** the seed-and-Newton route and is still the default; and the
sequencer's contribution is **284 library calls instead of 295,195**
for the same arithmetic - 1.20x on the software backend, where there
is no bus to save.

### What the writing of it found

**The sequencer cannot hold this workload, and there are two
independent reasons, either fatal alone.** Both are properties of the
program model rather than of the tool, and both are new information
for docs/SEQUENCER.md.

1. **Three input streams against `2d` state values.**
   `cft_program_run` initialises `r0`, `r1`, `r2`; `r3..r15` start at
   `+0`. A Hamiltonian system with `d` degrees of freedom has `2d`
   values per lane - 4 for the planar Kepler problem, 30 for the outer
   solar system - so a program can be ENTERED only at a state with at
   most three non-zero components. The Kepler initial condition has
   exactly two, and the registers that must hold the zeros are the
   ones that start at `+0`, so step 0 is reachable and no later step
   is. That is why the Kepler program engine runs the whole
   integration in one call, cannot resume into the middle of one, and
   does not exist for the outer solar system. docs/COLLATZ.md recorded
   the same limit gently ("it only fits because the fourth is an
   output that always starts at +0"); this workload shows it binding.
   **A fourth input stream, or a "load `r3..` from the deposit buffer"
   mode, would make every 2-degree-of-freedom system resumable and
   every 3-degree-of-freedom one expressible.** Sixteen registers are
   already enough for a 6-value state; only the loading is missing.

2. **Correctly rounded divide and square root are not programs.**
   `python/cft_golden/seqprogs.py` partitions its own route as HOST
   prep, PROGRAM core, HOST finish - `round_pack` is the contract's
   single rounding authority and it is host work by design - and the
   core alone occupies `r0..r12` of sixteen registers. So the composed
   route cannot be inlined into a larger program's loop body. That is
   why `--rsqrt exact` is a loop-engine route and why `--rsqrt newton`
   exists at all: so that the two engines have a step they can BOTH
   run, which they then have to run bit for bit.

**Nothing in this workload is exact, and saying so is the design.**
Every drift and every kick rounds, so `INEXACT` is expected on every
call and carries no information; the other four flags are
certificates, are checked on every call, and stop the run. A sweep of
18 deliberately under-resolved configurations - three formats, six
step sizes from 3 to 12 steps per orbit, 3,000 periods each - raised
nothing but `INEXACT`. The certificate never fires on a healthy
integration or even a badly wrong one; it fires on arithmetic that has
left the domain, which is what a certificate should do.

### The negative control

Three faults, each rebuilt and run through the same gate, chosen to be
caught by three different gates.

| control | what was changed | caught by | what stayed green |
|---|---|---|---|
| A | `c_mhm[sub][i]` -> `[j]` in the outer kick: Newton's third law | the angular-momentum certificate (`2.05411e-3` against a `2.35e-60` bound) and the 300-digit oracle (`2.756e-01` against `9.389e-62`) | every Kepler row, the flags (`0x10`, perfectly clean), the chain, batch, engines, resume, the refusals |
| B | `note_flags` no longer fatal on the certificate flags, plus `CFT_FMA` -> `CFT_SUB` in `kepler_r2` | with the gate IN: exit 3 at the first step, `cft_sqrt raised 0x01`, at every format. With the gate OUT: the run completes, `dH = nan`, **`dL = 0`**, a chain, and 8 of 26 checks fail | **the angular-momentum certificate passes, reporting `0`** - a NaN state conserves everything |
| C | the ORDER of the two roundings in `kepler_r2` reversed - mathematically identical | **exactly one check**: the sequencer program against the host loop | everything else, the 300-digit oracle included (`1.946e-68` against the unsabotaged `2.372e-68`) |

Control C is the one worth keeping. **The oracle cannot see a change
in the order of the roundings and never could** - two different
roundings of the same real number are both correct answers to the
domain's question. Had the fault been applied to both engines, nothing
in the check would have caught it, and the chains published in
docs/ORBITS.md would be the only witness. That is the plainest
statement of what an oracle is for and what it is not: it bounds the
answer, and only a bit-exact reference bounds the bits.

Control B is the complement. The certificate flags are the only gate
that fires BEFORE a wrong answer exists - every other gate scores a
number the tool has already produced - and the only gate a NaN cannot
satisfy.

Restoring the file, rebuilding, and the gate is green again at 26
checks.

### What was NOT run, and why

- No device, in emulation or otherwise. The tool takes `--artifact`
  and issues the same calls either way, but nothing here has been
  through XRT; docs/BRINGUP.md owns those gates. No device number is
  quoted.
- The RTL stages (`sim`, `lint`, `formal`): no opcode was added and no
  RTL file touched. The program uses `CFT_FMA`, `CFT_MUL` and
  `CFT_RSQRT_SEED` with the control codes `REPEAT`, `ENDREP`,
  `DEPOSIT` and `HALT`, all of which `tb/` and the vector sets already
  cover.
- The rest of `verify/run.sh`: nothing under `host/src/` changed, so
  the library gates certify the same library. No runner stage was
  added; `verify/run.sh` was deliberately left alone.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md` and the
  ABI version were left to the integrator, as at 0.7.

## 2026-09-04 - the deep-zoom explorer: a reference orbit at binary256, a frame at binary64

`host/tools/zoom.c` and `host/tests/zoom_check.py` are new;
`docs/ZOOM.md` is the argument behind them. Nothing under `host/src/`,
`host/include/`, `python/cft_golden/` or `verify/` was touched, and the
ABI version is unchanged - this is a tool over the existing contract,
not a change to it.

The workload is the project's own mission field. One point - the
reference - iterates `z <- z^2 + c` at binary256 as an orbit-sequencer
program; a batch of pixels around it iterates `d <- 2 z d + d^2 + Dc`
at binary64 through `cft_run`. Both halves go through libcft, so the
frame is the contract's arithmetic end to end, and the question it
answers with numbers is what the wide format buys.

### The centre is derived, not transcribed

Near the tip `c = -2` the set is self-similar with ratio 4; every real
`c` in [-2, 1/4] has a bounded critical orbit; and a grid point
`-2 + (i/8)*4^-p` needs exactly `2p + 5` significand bits, which the
tool computes from the format's measured `p` and refuses if the format
is too narrow. So a sign change of `z_p` on that segment brackets a
period-`p` nucleus, and 320 candidates in one call plus 130 bisection
steps land on it - 85 ms, no Newton, no seed, no published coordinate
copied in. At `p = 51` that is `-2 + 2.9196544e-30`, a
240-digit binary256 number whose orbit is superattracting and therefore
bounded past 100,000 iterations.

The cross-check re-derives the same bits with `python/cft_golden` and
then asks mpmath at 300 digits whether it is really a nucleus:
`|z_51(c)| = 1.61181e-42`, against `4.59177e-41` for one ulp of `c`
amplified through 51 steps of a map whose derivative is about 4 per
step. It is the nearest binary256 value to a nucleus, which is all any
binary256 number can be.

### What the gate is, and what it scores

`make -C host zoomtest`. The library stays the authority on arithmetic
and `python/cft_golden` is where that is written down, so the tool must
be BIT-IDENTICAL to it - the centre, every orbit point, every pixel's
escape iteration under the model's own binary64 semantics. mpmath at
300 digits is the authority on the domain, where the tool must be
CLOSE, and how close is the measurement.

    11222 comparisons, 0 failures
    ZOOM CHECK OK - the tool, the golden model and mpmath agree

about 14 seconds.

| what it checks | result |
|---|---|
| the derived centre | identical to the golden model's, all 237 bits; a nucleus at 300 digits; bounded for 100,000 iterations |
| the reference orbit, both engines | 4,000 points each, bit-identical to the model |
| a COMPLEX centre (-0.125, 0.75) | 3,000 points bit-identical - the derived centre is real, so this is the only row that exercises the imaginary half |
| program versus loop | byte-identical orbits and byte-identical checkpoints |
| trip counts 1024 / 63 | byte-identical checkpoints |
| batch 3 / 4096 | the same derived centre and the same checkpoint |
| interrupt and resume, 11 stops at a different trip count | byte-identical to the uninterrupted run |
| the perturbed pixels, 3 frames | 64 pixels each, bit-identical to the model's binary64 semantics: 64 escaping, 23/41 escaping/interior at a complex centre, 60/4 escaping/glitched off the nucleus |
| batch 7 / 64 / 4096 | byte-identical pixel records |
| the chain | recomputed with `hashlib`, identical |
| the 754 status word | equals the union of every call's `flags_out`, on an orbit-only run and on a full frame |
| refusals | a width that is not a power of two, a centre the format cannot hold, an unknown option, a resume that moves the centre, a zoom below binary64's normal range, a glitch tolerance outside the format's precision, sizes larger than memory |

mpmath is optional; when it is absent the script prints a SKIP naming
the four rows that are then missing, and its summary line becomes
"ZOOM CHECK OK against the golden model - but mpmath was MISSING, so
nothing here checked the domain" rather than the usual one. That exists
because writing the negative controls found the control script putting
a different interpreter first on PATH, and four rows vanished without a
word.

### The binary64-versus-binary256 result

Derived from the format parameters: a centre near `|c| = 2` is held to
`2^(1-p)`, so binary64 reaches a pixel scale of about 1e-15 and
binary256 about 1e-71. **Fifty-six decades.** Measured at this frame's
3.11e-61 pixel, the tool prints `|c_fmt - c_fp256| / pixel` exactly:

| reference format | centre error, in pixels | escape iterations | pixels differing from the fp256 frame |
|---|---|---|---|
| binary256 | **0** | 307..3227 | - |
| binary128 | 1.78e+26 | 148..156 | 4096 of 4096 |
| binary64 | 9.38e+30 | 74..107 | 4096 of 4096 |
| binary32 | 9.38e+30 | 74..107 | 4096 of 4096 |

Not a worse image; a different one. binary32 and binary64 agree because
both round this centre to exactly -2, and they return the same orbit
chain for that reason.

Reference validity length, against the 300-digit orbit. The absolute
criterion - the first `k` at which the formats' orbits differ by more
than one pixel - gives 21 for binary256 and 1 for binary64 at 1e-60.
But that criterion measures the map's Lyapunov exponent rather than the
reference's usability, because the reference error and a pixel's own
offset obey the same linearised recurrence and amplify together. The
criterion that decides the image is the ratio, and by it the binary256
reference never drifts past a pixel's own deviation in 600 iterations
while binary64's is past it at iteration **1**, before a single pixel
has moved.

### The flag that says nothing, in one measurement

    ./cft-zoom --format fp64 --ref-iters 100000 --no-pixels
    orbit flags   0x00  (inexact is expected; anything else stops the run)

The binary64 reference orbit raises **nothing at all**. Its centre
rounded to exactly -2, so the orbit is 0, -2, 2, 2, 2, ... and every
operation in it is exact for a hundred thousand iterations - a
perfectly exact computation of the wrong problem. That is the sharpest
statement this repository has of what an exception flag cannot tell
you, and it is the opposite of the Collatz explorer, where `inexact` is
a per-element detector. Here `inexact` is EXPECTED on every call; the
certificates are the absence of the other four (checked after every
call), the escape comparison raising exactly zero (checked per call in
the loop engine, because a comparison rounds nothing), bit identity
with the golden model, and bit identity between the engines.

### The measurements

Software backend, single thread, DESKTOP-T33SK86 (Windows 11, MINGW64,
`gcc -O2`), 2026-09-04. A shared box: the same measurement taken while
other work ran came back about 25% lower across the board, so every row
is a median of five and the ratios are the result rather than the
absolutes. `--ref-iters 100000 --no-pixels`:

| format | engine | reference iterations/s | elementwise ops/s |
|---|---|---|---|
| fp256 | program | 174,462 | 1,395,696 |
| fp256 | loop | 162,374 | 1,298,992 |
| fp128 | program | 275,562 | 2,204,496 |
| fp64 | program | 450,980 | 3,607,840 |
| fp32 | program | 493,293 | 3,946,344 |

The pixel batch is 399,782 pixel-iterations/s at binary64 - about 9.2
million elementwise operations a second at 23 per pixel-iteration -
375,000 to 411,000 from batch 64 to batch 16,384, with an identical
pixel chain at every one.

The headline frame: 100,000 reference iterations at fp256 in 0.54 s
through **98 library calls** (the host loop issues 800,000), then 4,096
pixels in 4.6 s: 4,010 escaped, 0 glitched, 86 interior, escape
iterations 307..3227, orbit chain
`8cf49c0b2cdcf6bf899ba7fbc763aa5ee82449807578052f20934cc365afc3e4`.

**The sequencer's margin here is only 1.06x to 1.16x**, against 1.5x to
2.1x for the Collatz explorer, and the reason is structural rather than
disappointing: a reference orbit is ONE lane, so the program saves
per-call dispatch on a call that was doing one element's work anyway.
What it does buy is the call count, and on a device the memory round
trip per step. The domain's own answer is many references at once,
which is what multi-reference rendering does and what would turn this
into the sequencer's best case.

### What the writing of it found

**A per-iteration host-side statistic quietly undoes what the sequencer
is for.** The running minimum of `|z_k|^2` began as four
single-element library calls per orbit point: half as much work again
as the eight the step needs, and 400,000 calls where the sequencer had
got the count down to 98. It is now three whole-array passes and a MIN
tournament after the run - about `2*log2(n) + 4` calls for any `n` -
and it left the checkpoint, because it is a function of the orbit that
is already there.

**The perturbation cannot be a sequencer program, and the obstacle is
exact.** It needs six live values a step: four per-lane and persistent,
which the register file holds, and two that change every iteration and
are shared by every lane. The model has three input streams that
initialise once, and a constant bank fixed at load time and addressed
by the 4-bit register field - **at most 16 constants**, so not enough to
unroll. There is no operand source that advances with the loop counter.
The missing feature is a per-iteration broadcast: a fourth stream read
by iteration index rather than by lane, or a constant bank the loop
counter can address. Recorded for the sequencer's designers, because
perturbation rendering is the reason a deep-zoom engine wants a
sequencer at all.

**A real centre hides half the arithmetic.** The derived nucleus is on
the real axis, so `zi` is exactly +0 for the whole orbit and
`zr^2 - zi^2` and `zr^2 + zi^2` are the same value. The complex-centre
row exists because negative control A swapped exactly those two and
nothing else in the check noticed.

### The negative controls

Three faults, each rebuilt and run through the same gate, then
restored.

| control | what was changed | caught by | result |
|---|---|---|---|
| A | `zr^2 - zi^2` became `zr^2 + zi^2`, in BOTH engines | the complex-centre rows, alone - the orbit and the pixel cap | 35 green, 2 failing |
| B | the reference rounded into binary64 with RTZ instead of RNE | the per-pixel oracle, alone: `pixel 2: tool says (176, 'esc'), the golden model says (175, 'esc')` | 35 green, 1 failing |
| C | the program's final add reads `zr` instead of `zr^2 - zi^2` - ONE engine | the engine cross-check, the checkpoints, the resume, the model and mpmath | 29 green, 11 failing |

A and B are the interesting pair. Under both, the engines agree with
each other, the checkpoints match across trip counts and batch sizes,
the resumed run lands byte-identically, the chain matches hashlib, and
the binary64 comparison still reports 4096 of 4096. Internal
consistency proves the tool computes the same thing every time; it
cannot prove the thing is right, and two engines built from one
understanding are wrong together. C is here to show the internal gates
are live, which is what makes A and B's silence meaningful.

Restoring the file, rebuilding, and the gate is green again at 11,222
comparisons.

### What a review of the finished tool found

Seven silent-failure paths, all closed, and the worst of them is worth
recording because the cross-check could not have found it. **A resume
that moved the centre continued the checkpoint's orbit prefix with this
invocation's parameter**: the centre is baked into the sequencer
program's constant bank when the engine is built, and `ckpt_read` ran
afterwards and overwrote it, so `--resume --ref-offset 40` produced a
chain matching neither the offset-0 run nor the offset-40 one while
still printing the offset-0 centre. The check resumed only ever with
identical arguments, so it saw nothing. The checkpoint is now read
before the engine is built, a differing centre is refused, and both the
refusal and the ordinary resume are rows of the gate.

The others were guards rather than bugs, each against something that
raised no flag and printed nothing: `--zoom-exp` past binary64's
smallest normal collapsed the frame into `width^2` copies of the
reference with every pixel offset rounded to `+0`; the reference's
narrowing conversion into binary64 bypassed the forbidden-flag gate, so
an orbit point becoming a subnormal would not have stopped the run; the
"status word agrees with the union" line was printed and never read, and
the report's own roundings were happening after the word was sampled;
and `--glitch-bits`, `--ref-iters` and `--ref-offset` were unbounded in
ways that disabled the glitch test, wrapped an allocation, and
overflowed a 32-bit `long` respectively. In the oracle: the orbit rows
asserted no minimum length, so an orbit that escaped at iteration one
would have passed as "1 point identical".

### What was NOT run, and why

- No device, in emulation or otherwise. The tool takes `--artifact` and
  issues the same program either way, but nothing here has been through
  XRT; `docs/BRINGUP.md` owns those gates. No device number is quoted.
- The RTL stages (`sim`, `lint`, `formal`): no opcode was added and no
  RTL file touched. The orbit program uses `CFT_MUL`, `CFT_ADD`,
  `CFT_SUB`, `CFT_FMA` and `CFT_CMPLE`; the pixel batch adds
  `CFT_NEG`, `CFT_MIN`, `CFT_MAX` and `CFT_SELECT`; the search adds
  nothing. All are covered by `tb/` and the vector sets, and the four
  control codes used are ones `tb/test_seq_core.py` already scores.
- The rest of `verify/run.sh`: nothing under `host/src/` changed, so
  the library gates certify the same library they certified this
  morning. No runner stage was added; `verify/run.sh` was deliberately
  left alone.
- `README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md`,
  `docs/BENCHMARKS.md` and the ABI version were left to the integrator,
  as at 0.7. `host/Makefile`'s `clean` was left alone too: the new
  targets sit in their own delimited block with their own `TOOLS +=`
  line and a `zoomclean`, so that four parallel workloads merge beside
  one another rather than through one recipe.

## 2026-09-04 - the five workloads in a browser tab, chained against the C tools

`bindings/wasm/demos.html` is new, and so are the six files that build
and check it (`demos_template.html`, `demos_core.js`,
`demos_worker.js`, `demos_chains.json`, `make_demos.py`,
`build_demos.sh`, `verify_demos.mjs`); `docs/DEMOS.md` is the argument
behind them. Nothing under `host/src/`, `host/include/`,
`host/tools/`, `python/` or `verify/` was touched, the ABI version is
unchanged, **no wasm module was rebuilt**, and `conformance.html` was
not modified - this is a second page over the existing build product,
not a change to it.

The page runs the five workloads of docs/BENCHMARKS.md - zoom, orbits,
Collatz, enclose, Mersenne - as five panels, each a port of one tool's
`--engine loop` path, on the module `conformance.html` embeds. Each
panel prints the SHA-256 chain the native C tool produced for exactly
its configuration beside the chain it just computed, and a control
compares them. That comparison is the whole deliverable: **the browser
computes the same bits as the C tool**, or the panel goes red.

### What was verified, and how

`node bindings/wasm/verify_demos.mjs` is the browserless gate. Three
checks, in order, and the first two exist so the third is about the
right program:

| what it checks | result |
|---|---|
| the module the page embeds, walked out of emcc's SINGLE_FILE literal | 211,869 bytes, sha256 `a1f0a4715516d3f6…` - identical to `bindings/node/cft_node.wasm`, the module `conformance.html` embeds |
| the compute core the page embeds | byte-identical to `demos_core.js`, so the report is about the page and not a lookalike |
| 13 chains over 11 configurations, three ways: the native tool run just now, the compute core over the committed module, and the recording in `demos_chains.json` | 13 of 13 agree, all three ways |

And then in a real browser: served over loopback and driven in
Chromium, every panel run, **13 of 13 chains computed in this browser,
every one identical to the C tool's** - in a Web Worker, with the tab
responsive, progress posted in batches and Cancel honoured between
them. One PNG per panel in `docs/img/demos/`.

The eleven configurations are all expressible in the tools' existing
flags; no tool was edited to make one reachable. Two of them deserve a
line. The zoom panel runs `--ref-iters 1001 --pixel-iters 1000` rather
than the tool's 100,000/4,096 because a browser wants a frame more than
an orbit, and 1,001 is exactly one more reference point than the pixel
phase reads. The enclose panel runs `--cond-max 164` rather than the
tool's 225 because 225 is *refused* at binary32 - the ladder's smallest
element would be `2^-187`, below binary32's smallest normal - and 164
is the largest spread every format holds exactly,
`dot_top - 2*mw - emin(binary32)`, derived on the page from
`measureFormat("fp32")` rather than carried as a number. At 164 the
result is unchanged: fp32 and fp64 straddle zero on 14 of 15
enclosures, fp128 and fp256 on none, and fp256's fifteen are exact.

### The build

`bash bindings/wasm/build_demos.sh`, inside the image `build.sh` pins -
and the pin is read out of `build.sh` rather than typed again. **Two
clean container builds with `bindings/wasm/build/` removed between
them, byte-identical: 486,822 bytes, sha256
`e3711319627e68281dc97636a65da169b9c3b8d467ed45b2e1da9bceb6538a67`.**

The build refuses to ship a page whose module is not the committed one,
and checks that fact three times: the split `.wasm` from the same emcc
run against `bindings/node/cft_node.wasm` (stage 2), `make_demos.py`
again, and then by walking the bytes back out of the assembled HTML.
`demos_chains.json` also records the module and core hashes it was
recorded against, and the build refuses a mismatch - a chain recorded
against a different program is a chain about a different program.

One emcc flag differs from `build.sh`: `-sENVIRONMENT=web,worker`
instead of `-sENVIRONMENT=web`, because the page computes in a Worker.
`ENVIRONMENT` selects branches of the JavaScript loader and nothing
else, and stage 2 does not assume that - the module it produced hashes
identically to the committed one.

### The negative controls

Two of them, one sabotage: the Collatz panel's running peak computed
with `CFT_MIN` instead of `CFT_MAX`. That site was chosen because
nothing else notices it - the flag/witness agreement still holds, the
step count is right, the final value is right, the run reports success
- and only the chain is wrong. It is exactly the failure a chain
comparison is for.

- **The page.** `build/demos_negative_control.html` (untracked, built
  by stage 4) carries a red banner naming the sabotage; running its
  Collatz panel gives *"2 of 2 computed chains DIFFER from the native
  tools. The page is wrong until shown otherwise."* Screenshot in
  `docs/img/demos/negative-control.png`.
- **The checker.** The same edit to `demos_core.js` makes
  `verify_demos.mjs --panel collatz` fail four times - each chain
  against the tool it just ran *and* against the recording - which is
  the point of keeping both references. `git checkout --` restores it
  and both go green.

### Rates, measured on both sides

Software backend, one thread, DESKTOP-T33SK86, wall clock over work
done. **Measurements of a slow software tier, not a performance
claim**, and the page prints that sentence under every panel.

| panel / run | native `--engine loop` | node (wasm) | Chromium (wasm) |
|---|---|---|---|
| zoom / fp256-reference | 346,414 pixel-iter/s | 269,380 | 343,381 |
| zoom / fp64-reference | 383,738 pixel-iter/s | 251,440 | 297,215 |
| orbits / fp256 | 24,922 element-steps/s | 17,210 | 22,645 |
| orbits / fp64 | 55,589 element-steps/s | 47,216 | 50,945 |
| collatz / sweep | 221,294 steps/s | 149,228 | 173,491 |
| collatz / trajectory | 239,666 steps/s | 42,754 | 58,865 |
| enclose / fp256 | 1,526 enclosures/s | 980 | 1,247 |
| mersenne / to-2281 | 646,661 limb products/s | 403,953 | 473,911 |

wasm runs between 0.8x and 1.4x of native wherever a call carries a
batch, and the browser is consistently a little faster than node on the
same module. The collatz trajectory row is the outlier and it is call
shape, not arithmetic: one lane, 23 wasm crossings per Collatz step.

### What the port had to do differently, and why neither changes a bit

**Elements are batched.** Where a tool issues one library call per
element, the port issues one per batch. `cft_run` is elementwise by
contract - which is why every one of these tools' gates already runs a
configuration at two batch sizes and compares bytes - and one `_malloc`
per scalar call is the wasm boundary's known trap, so every buffer is
allocated once per job.

**zoom's seven per-iteration reference scalars are hoisted** out of the
pixel loop into seven batched passes over the whole reference. They
depend on the reference alone; element `k` of the batched pass is the
C's `k`-th scalar call on the same operands. It removes 112,000 wasm
crossings and leaves the pixel chain identical, which is the check that
matters.

**Presentation is fenced off.** Anything computed for the screen goes
through a save/restore of the 7.1 status word (5.7.4) *and* of the call
counters, so a printed decimal cannot pollute a flag union or inflate a
rate. That is `enclose.c`'s own `val_to_dec` pattern with the counters
added; with it, the orbits panel reports the tool's own 23,627 library
calls exactly.

**Constants are derived.** SHA-256's `K` and `H0` are computed from the
first 64 primes over BigInt exactly as the C computes them over a
128-bit integer; every format's `p` is measured by asking the library
where `2^k + 1` first goes inexact; `--cond-max` is derived above; the
Collatz default `2^237 - 1315` is computed in the page. The opcode,
format, rounding and flag numbers are audited against the module at
open time via `cftw_op_name`, `cftw_format_name` and `cftw_flags_all`,
because a mistranscribed opcode field computes a different operation
and reports nothing.

### What the sequencer's program API would have bought, measured

The wasm surface exports no `cft_program_*`, so every panel runs a host
loop. Both engines return the same chain, so the gap is a rate and
nothing else, and it was measured at the page's own configurations
rather than quoted:

| the page's configuration | program | host loop | ratio |
|---|---|---|---|
| collatz, sweep 1..1000 | 413,018 steps/s | 222,660 | 1.85x |
| collatz, deep `2^237-1315` | 506,053 steps/s | ~240,000 | ~2.1x |
| zoom, the 1,001-iteration reference orbit | 109,871 iter/s | 78,713 | 1.40x |
| orbits, Kepler leapfrog, `--rsqrt newton` | 82,492 el-steps/s | 65,717 | 1.26x |
| enclose, interval Horner, 17 items | 19,970 /s | 15,351 | 1.30x |

Which makes the ask small and worth stating with its limits: exporting
the three program entry points would buy four panels 1.3x-2.1x, and the
fifth - zoom, whose pixel phase is nineteen of the page's twenty
seconds - nothing at all, because those pixels go through `cft_run` in
the C tool too. The orbits row is not even available as configured: the
page runs `--rsqrt exact`, which `cft-orbits` refuses to run as a
program. The gain in wasm should exceed the gain in C, since what a
program removes is call boundaries and a wasm boundary costs more - but
that could not be measured, because the API is not exported, so it is
recorded as an expectation and not a number.

### What was NOT run, and why

- **No module rebuild.** `bindings/node/cft_node.wasm` is untouched and
  its sha256 is unchanged; the conformance page and three documents
  quote it, and the integrator schedules module rebuilds. Every check
  above is against the committed bytes.
- **No device.** The panels drive the software backend, the only
  backend a browser can be. No hardware number appears here.
- **The RTL stages and the rest of `verify/run.sh`.** No opcode was
  added, no RTL file touched, nothing under `host/src/` changed, and
  `verify/run.sh` was deliberately left alone. The library gates
  certify the same library they certified this morning.
- **`README.md`, `docs/COMPATIBILITY.md`, `docs/COMPLIANCE.md`,
  `docs/BENCHMARKS.md` and the ABI version** were left to the
  integrator, as at 0.7. `.github/workflows/pages.yml` was edited,
  because the new page has to be deployed: it now stages
  `conformance.html` twice (as `index.html` and under its own name, so
  the demos page's relative link resolves on the site) and
  `demos.html` beside them, and `bindings/wasm/demos.html` is in the
  trigger paths.
- **The larger Mersenne exponents.** 3217..11213 and 19937..44497 are
  offered on the page behind a time warning and were not run; neither
  has a recorded chain, and the page says so when either is selected.

## 2026-09-06 - the remote backend: a tile behind a socket, held to the contract across an OS boundary

Step 1 of docs/ROADMAP.md's "After card day: the third tier", and
docs/PLATFORMS.md section 6's Windows answer. A third `libcft` backend
beside the software and XRT ones, opened with
`cft_open("cft://host:port", 0, &dev)`; a server, `host/tools/cft-serve.c`,
holding one library device per connection; a frame protocol written
down in docs/REMOTE.md before it was implemented. Commits `18af987`
(the backend, server, tests and protocol document), `4f58087` (the
server multiplexes its connections; the runner's `remote` stage) and
the docs commit that carries this entry.

### What the gate is, and what it scores

Bit identity through the transport, the way every backend is scored:
the published sets replayed through a remote device must give the
report the local replay gives, and the workload tools run with
`--artifact cft://...` must print the chains they print locally. The
server computes with the library and the library is the contract, so
a remote replay that disagrees with a local one is the transport's
fault until proven otherwise - which is why the transport refuses
rather than guesses: a 32-byte little-endian header with a magic, the
protocol version, the sender's ABI version (a mismatch is refused,
not warned), a request id, an opcode, a status and a length; a CRC-32
over header and payload; a length cap enforced before allocation;
encodings as bytes and flags as `uint32`, never a parsed number; and a
refusal that closes the connection and poisons the client handle, as
the XRT backend poisons a handle whose compute units may still be
running.

Only the calls that touch a device cross: `cft_run`, `cft_reduce` for
sum and dot, and the program runs. Every host operation runs in the
client's own copy of the library. The status word stays on the client
handle - each response carries the call's flag word and `device.c` ORs
it in through `cft_flags_emit`, so 5.7.4's six operations cost no
round trip and the composition discipline is unchanged.

### The measurements

Windows host DESKTOP-T33SK86 (mingw64 gcc 16.1.0), the Linux server in
its WSL2 distro `cft2204` (Ubuntu 22.04, gcc 11.4.0, kernel
5.15.153.1-microsoft-standard-WSL2), both built from the same sources.
"Loopback" is a Windows `cft-serve` on `127.0.0.1`; "WSL" is the Linux
`cft-serve` reached from the Windows client at `cft://localhost:7755`
through WSL2's localhost forwarding. One thread everywhere; the box
was carrying its usual load.

**(a) The published sets, 168 of them, 1,223,635 cases, every set
replayed exactly as `cft_conformance` replays it locally:**

| client -> server | result | seconds | cases/s |
|---|---|---|---|
| Windows local (software backend) | 168 sets, 1,223,635 cases, all matching | TODO_A_LOCAL | TODO |
| Windows -> Windows loopback | same report | TODO_A_LOOP | TODO |
| Windows -> Linux in WSL | same report | TODO_A_WSL | TODO |
| Linux local (software backend, in WSL) | same report | 503.8 | 2,429 |
| Linux -> Linux loopback (in WSL) | same report | 541.3 | 2,261 |

The per-element pass of the elementwise sets is one round trip per
case, which is the hardest shape for a socket and the one the replay
deliberately keeps (a device backend that only ever saw n = 1 would
hide every partitioning bug; here it is the transport that gets no
batching to hide behind).

**(b) The five workloads, at the eleven configurations
`bindings/wasm/demos_chains.json` recorded on 2026-09-04 and at the
program engines of the four tools that have one, local against
loopback against WSL:** TODO_B_TABLE

**(c) The cross-OS run** is the WSL column of both tables: a Linux
`libcft` behind `cft-serve` in `cft2204`, a Windows `libcft` in the
client, TODO_C_SUMMARY.

**(d) The cost.** A one-element `cft_run` round trip: 22-24 us on
Windows loopback, 18.4 us on Linux loopback, TODO_D_WSL us across the
WSL2 boundary (WSL2's localhost relay, not the library: the Linux
server answers its own loopback in 18 us). A 4,096-element fp64 FMA:
1.35-1.40 ms per call on Windows loopback (2.9-3.0 M elements/s),
0.38 ms on Linux loopback (10.7 M/s), TODO_D_WSL4096. The composed
operations' round trips, read from the server's own `STATS` counters
rather than inferred, fp64, per call of n elements up to the 4,096
chunk:

| operation | chunk route (`CFT_DIVSQRT_SEQ=0`) | program route (default on a device) |
|---|---|---|
| `cft_div` | 21 `RUN` frames | 1 `PROG_RUN` (plus 1 `PROG_LOAD` the first time) |
| `cft_sqrt` | 32 `RUN` frames | 1 `PROG_RUN` (plus 1 `PROG_LOAD`) |
| `cft_rint` | 4 `RUN` | 4 `RUN` |
| `cft_scaleb` | 1 `RUN` | 1 `RUN` |
| `cft_cmp_sig` | 1 `RUN` | 1 `RUN` |
| `cft_formatof_add` fp32->fp64, n = 4,096 | 128 `RUN` | 128 `RUN` |

so the program route saves 20 round trips per chunk of a division and
31 per chunk of a square root, and on this loopback that is 27 ms
against 16 ms for 4,096 fp64 divisions (the server's own arithmetic is
most of what remains). `cft_formatof_add`'s 128 frames at n = 4,096 are
the widening route's 32-element blocks, one `cft_run` each - a shape
worth knowing about before pointing it at a slow link.

### The controls

`host/tests/device_test.c` holds the remote backend against the
software one exactly as it holds the XRT one - every supported format,
opcode and attribute, partition invariance, the awkward reduction
lengths: **2,248 checks, 0 failed** on Windows loopback (twice, before
and after the server learned to multiplex) and on Windows -> WSL.
`host/tests/remote_test.c` speaks the frames badly on purpose: an ABI
one minor version away, a corrupted crc, a bad magic, a length past the
cap, a `RUN` before `HELLO`, a wrong protocol version - each REFUSED
and the connection closed; a truncated frame dropped with the next
connection served; an unknown opcode and a bad handle answered with a
status and the connection kept; the buffer and status-word operations
libcft's client never issues; and a bit-identity sample on both
div/sqrt routes: **245 checks, 0 failures**, on loopback and on WSL.
The CRC-32 the frames carry agrees with Python's `zlib.crc32` on the
standard check string and on a 1,000-byte stream.

TODO_NEGATIVE_CONTROL

### The runner

`verify/run.sh` gains the `remote` stage, in the quick budget. TODO_RUNNER

### What the writing of it found

- **The protocol's own length discipline caught the first bug in the
  code.** `RUN` and `REDUCE` carry four `u32` and a `u64` before their
  operands - 24 bytes - and the first client and server both started
  the operands at 20. The server refused the first real frame ("n =
  14758742324779417601 elements cannot fit a frame": n's high word had
  overlapped the first operand) rather than compute on it. The Collatz
  chain had matched anyway on the same bug, because an fp256 integer's
  low bytes are zero; a check that passes for a reason like that is
  why the replay and `device-test` are the gate and a chain is a
  witness.
- **One connection at a time was a deadlock waiting for a second
  handle.** The first server served connections sequentially;
  `remote-test`'s fresh refusal connections sat behind its own open
  handle until they timed out, and `device-test`'s two handles (one
  software, one remote) only worked because the software one has no
  socket. The server now multiplexes with `select()` and a process may
  hold as many handles as it likes.
- **Windows needed no link flag, and that decided the design.**
  `libcft.a` is linked by the Go example through cgo with no way to add
  `-lws2_32` outside the example, and by the Fortran and Rust examples
  and the soak tools. Loading `ws2_32.dll` at first use keeps the
  archive's link set what it was; even `FD_ISSET` is done by hand on
  Windows, because the macro there calls into `ws2_32`.
- **WSL2's localhost forwarding costs more than the arithmetic.** TODO_WSL_FINDING

### What was NOT run, and why

- **No card.** The server was a software backend on both platforms;
  `--artifact` is wired and untested on silicon, which is card day's
  business. The step's claim is bit identity through the transport,
  and a software server is the honest way to make it before a tile
  exists behind the socket.
- **No LAN.** Loopback and the WSL2 boundary only; `--bind 0.0.0.0`
  on a real network is a trust decision the document states and this
  step does not make.
- **No wasm module rebuild.** `src/backend_remote.c` is in the
  library's source list (the wasm build cross-checks that list against
  `host/src`), compiled under emscripten to a stub that reports
  `CFT_ERR_NO_DEVICE`; the committed module is untouched and its hash
  unchanged.
- **The ABI version is unchanged** (0.7): one additive spelling of an
  existing argument, no new signature. README.md, COMPATIBILITY.md,
  COMPLIANCE.md, PLATFORMS.md, ROADMAP.md and the bindings were left
  to the integrator, as the brief asked.

## 2026-09-06 - the multi-cycle fp256 rung: bit-identical, and the area it does not save

Step 3 of docs/ROADMAP.md's third tier, built to make a tile fit parts
a third of the U50's size and measured to do something else. The
mechanism, the parameter and the full table are in
docs/ARCHITECTURE.md's "The multi-cycle rung"; this entry is what was
run.

**The bit-identity gate.** `MUL_PASSES` iterates the chunk-column
multiplier over passes and the pipe around it is held by one enable, so
the claim is that every result is identical to the single-pass tile's
at every pass count. The whole cocotb suite has a multi-cycle
counterpart - `make simmc MC=<n>` in `tb/` - and at **MC=10**, the
deepest configuration (fp256 taking a result every ten cycles):

    13 targets, 31 tests, 31 passed, 0 failed

covering the four format banks against the golden model, the reduction
accumulator, the kernel through its CSR and AXI interfaces, the
sequencer core, the sequencer's banked reads, the quarter-tile trim,
the fault paths, and two benches written for this work: `mulcycle`,
which holds `cft_mulpass` against the pipe's own side-by-side array on
random and edge operands, and `cycles`, which asserts the pacing
property - the same program and the same stream give the same bits at
every pass count, so determinism does not depend on the issue cadence.
Each pass count builds in its own `sim_build` directory, because two
counts sharing one would let a stale build answer for the other.

**The default is untouched.** The suite at `MUL_PASSES=1` is the
shipping RTL's own suite, re-run on the changed RTL - **21 targets, 60
tests, 60 passed, 0 failed** - and unchanged; the parameter defaults
to 1 and every `MUL_PASSES=1` elaboration collapses the pass machinery
to a constant.

**The area, out of context on the U50 part** (Vivado 2026.1, 135 MHz
ask, synthesis only, one build at a time through `hw/mc_sweep.sh`):

| MUL_PASSES | LUT | DSP | implied path delay |
|---|---|---|---|
| 1 | 123,214 | 262 | 5.821 ns |
| 2 | 120,391 | 152 | 5.585 ns |
| 5 | 116,158 | 70 | 5.585 ns |
| 10 | 115,310 | 56 | 5.585 ns |

**The finding: DSPs fall 79%, LUTs 6.4%.** The step assumed a
time-multiplexed multiplier would shrink the tile enough to fit a
Kintex-7 or an Artix-7; it does not, because the tile's LUTs are in the
aligner and normaliser and its multiplier is DSPs. That is the sharing
doctrine's own rule arriving from the other side, and it means the fit
lever for a small part remains the fused ladders while `MUL_PASSES` is
what makes a DSP-poor part stop caring about the multiplier. Recorded
as a measured result rather than presented as the answer it was
expected to be.

**The formal task that would not close.** A bounded proof of the pass
accumulation against a reference product at the real chunk width (25
and 49 bits) ran **four hours without returning** and was stopped
rather than left running on a shared machine; a bounded model check
over a multiplier is exactly the shape a SAT solver does worst at. The
`.sby` now carries narrow tasks - a reduced chunk width where the same
property closes - beside the real-width ones, and which of those closed
is not claimed here, because they were not run to completion in this
session. The bit identity rests on the benches above, which is where it
rested for `FUSE_NORM`, `FUSE_ALIGN` and `FUSE_MUL` too.

**The negative control: one dropped carry.** In `cft_mulpass`'s
accumulator, `acc <= s[P+K:K]` becomes `acc <= s[P+K:K] & ~(1 << 3)`,
so one carry bit is cleared on every pass - a fault that is arithmetic
rather than structural, and identical on every run:

    mulcycle    4 tests, 0 passed, 4 FAILED  (identical_per_format,
                identical_across_cadences, identical_on_specials,
                identical_under_precision_changes)
    fp256mc     1 test,  0 passed, 1 FAILED
    fp64mc      1 test,  0 passed, 1 FAILED
    cyclesmc    1 test,  1 PASSED

**The row worth keeping is the last one.** The cadence bench compares
the tile with itself at different pass counts, and a deterministic
arithmetic fault is present identically in both, so it reports
agreement while every result is wrong. The pacing property is a
determinism check and not a correctness one; what catches a wrong
product is the comparison against the golden model and against the
pipe's own side-by-side array. The same lesson the enclosure workload
recorded on 2026-09-04, from the other end of the stack.

Restored from git and the same four re-run: **7 tests, 7 passed, 0
failed**.

**The 7-series cells, run the next hour on a part that was
available.** The area matrix's `xc7k325t` and `xc7a200t` cells failed
because this host's Vivado 2026.1 carries only the UltraScale+ and
Versal families; the 2022.2 install in the `cft2204` distro carries
Zynq-7000 but its licence is node-locked to Alveo devices, so
`xc7z045` refused in eighteen seconds. `xc7z020` is in every free
edition's device list and its fabric is Artix-7 class, so the four
cells were run there - too small to hold a tile, which is not what they
were for:

| MUL_PASSES | ladders | LUT | DSP | implied delay |
|---|---|---|---|---|
| 1 | off | 135,865 | 220 (capped) | 16.157 ns |
| 1 | on | 120,282 | 220 (capped) | 16.327 ns |
| 10 | off | 116,498 | 56 | 16.428 ns |
| 10 | on | **99,287** | **56** | 17.140 ns |

The single-pass rows carry a caveat rather than a number: the part has
220 DSPs, a single-pass tile wants 262, and Vivado capped inference at
100% and spilled the rest into fabric, so those LUT figures are
inflated by an unknown amount. The `MUL_PASSES=10` rows are clean, and
between them the fused ladders are worth 14.8% of the tile's LUTs on
this fabric.

**The result the step was after, arrived at by both levers rather than
one:** a full fp256-capable tile at **99,287 LUT and 56 DSP** on
7-series fabric is 49% of a Kintex-7 325T and 74% of an Artix-7 200T,
where a single-pass tile's 262 DSPs would have been 31% and 35% of
those parts' DSP columns and 119% of this one's. The implied path is
17.1 ns on a -1 part, about 58 MHz, which is the trade stated as a
number.

**The real parts, an hour later.** The device families were
installed and the cells run for the two boards docs/PLATFORMS.md
recommends, both with the ladders on:

| part | passes | LUT | of device | DSP | implied delay |
|---|---|---|---|---|---|
| xc7k325tffg900-2 (-2) | 10 | 98,929 | 48.5% | 56 | 9.698 ns |
| xc7k325tffg900-2 (-2) | 1 | 109,225 | 53.6% | 262 | 9.956 ns |
| xc7a200tsbg484-1 (-1) | 10 | 98,929 | 73.5% | 56 | 17.422 ns |
| xc7a200tsbg484-1 (-1) | 1 | 109,225 | 81.1% | 262 | 17.785 ns |

Logic maps identically on the two parts, as it should; the speed grade
is the difference. **The Kintex-7 325T carries a full fp256-capable
tile at 48.5% with 9.698 ns of implied path against a 100 MHz ask**, a
WNS of -0.066 - which is a far better clock than the Zynq-7020
stand-in's -1 fabric predicted, and it is the board the survey already
recommended. The Artix-7 200T holds the same tile at 73.5% and about
57 MHz.

**A licence trap worth a line in anyone's runbook.** These cells were
"impossible" for an afternoon: Vivado 2026.1 picks ONE licence tier at
startup and exposes only that tier's devices, so with an Alveo and a
Basic entitlement in one `Xilinx.lic` it chose ALVEO, reported 12
parts, and said `xc7k325tffg900-2` could not be found - with the
7-series device files correctly installed and the Basic increment in
the same file. Pointing `XILINXD_LICENSE_FILE` at a Basic-only copy
turns 12 parts into 1,215. The device install was necessary; it was
not sufficient, and neither was owning the licence.

**Still not run.** Implementation at any pass count on any part, so no
post-route number on 7-series fabric - which is where a 48.5% design
with 66 picoseconds of synthesis slack would actually be decided.

## 2026-09-07 - the open-core board: the configuration simulated as one thing, and what the speed grade costs

The tile a Kintex-7 325T would carry is `MUL_PASSES=10` with both
fused ladders on. Every one of those three parameters had been
simulated and never all three at once - `krnlfused` runs the ladders at
one pass, the `*mc` targets run the passes with the ladders off - and a
configuration only ever covered a parameter at a time is a
configuration nobody has run. `tb/Makefile` gains `board`, which is
that configuration on the three benches that matter for a part with no
host streaming a beat a cycle: the kernel through its CSR and AXI
interfaces, the same kernel driven by the sequencer, and the fp256
bank. **3 targets, 4 tests, 4 passed, 0 failed** at MC=10.

**Routed, and the speed grade is the finding.** All out of context
through `hw/mc_sweep.sh`, ladders on, ten passes:

| part | grade | ask | routed WNS | verdict |
|---|---|---|---|---|
| xc7k325tffg900-2 | -2 | 100 MHz | **+0.096 ns** | closes; 95,695 LUT (47.0%), 43,365 FF, 36 BRAM, 56 DSP |
| xc7k325tffg676-1 | -1 | 100 MHz | -2.782 ns | misses |
| xc7k325tffg676-1 | -1 | 80 MHz | -0.384 ns | misses; implies about 77 MHz |
| xc7k410tfbg676-2 | -2 | 100 MHz | -0.957 ns, 650 endpoints | misses |
| xc7k410tffg900-2 | -2 | 100 MHz | -0.957 ns | identical - the package is not a variable in an out-of-context design with no bonded I/O |
| xc7k410tfbg676-2 | -2 | 80 MHz | +0.607 ns | closes |

Two things follow that a buyer needs. **The speed grade decides the
board**: the same tile closes 100 MHz on a -2 and misses 80 on a -1, so
the cheapest listed K325T core board (`xc7k325tffg676-1`, about $99)
would run near 75 MHz where a -2 runs at 100. And **the bigger die is
the slower one**: docs/studies/OPT-C-timing.md took the two 410T
netlists apart and found them identical to a picosecond of logic delay,
with the entire 1.053 ns difference in route - 1.33x the fabric area,
whose square root predicts 15.3% more wire against 13.5% measured.

**A defect these runs exposed.** `hw/mc_sweep.sh` keyed its output
directory on part, passes, ladders and stage but not frequency, so two
asks for one configuration overwrote each other's reports; the summary
appends, so the QOR lines above survived and the 80 MHz run's detailed
timing did not. The tag now carries the frequency.

**Not run.** Any Alveo implementation with these parameters; any
post-route number under a shell rather than out of context, where this
project has one recorded 0.88 ns swing; and the frequency sweep that
would establish either part's ceiling, which docs/studies/OPT-C-timing.md
specifies and which the routed pairs here make possible.

## 2026-09-07 - what four design studies found wrong, corrected

Four studies (docs/studies/OPT-A to OPT-D) were commissioned for ideas,
and their ideas stay ideas; what this entry records is the defects and
stale claims they turned up on the way, each verified before it was
fixed.

**A live defect for card day: two workloads' defaults do not fit a
tile.** `cft_seq` refuses a program header whose `max_deposits`
exceeds `MAXD`, which rtl/cft_krnl.sv sets to 64 slots a lane, and the
software backend accepts 2^20 - so a program that runs on the software
backend has not been shown to fit a tile, and neither `cft_caps` nor
docs/SEQUENCER.md said so. `cft-zoom` deposits two values a trip and
its default `--steps-per-call 1024` asks for 2,048 slots; `cft-orbits`
deposits four values a sample plus four at the start, for a whole run
in one call, and its default of 16 periods sampled once a period asks
for 68. Both defaults would have been refused by the tile with a
status bit and no explanation. Both tools now refuse first, on any
backend but the software one, naming the flag and the bound (32 trips;
15 samples); the software backend's behaviour and every recorded chain
are unchanged, and `zoomtest` and `orbitstest` pass. docs/SEQUENCER.md
now states the three on-chip capacities (`MAXD` 64, `IMEM_D` 1024,
`KMEM_D` 256) and that the loader does not enforce them.

**Claims that were true of one backend and stated for both.**
docs/ZOOM.md's "98 library calls" and docs/BENCHMARKS.md's row are the
software backend's; at the tile's 32-trip cap the same reference is
3,125 calls, still 256x fewer than the host loop. docs/ORBITS.md's "284
calls" run is the benchmark's 16-period once-a-period sampling, which
is 16 samples and would be refused; both documents now say so.

**The 159 MHz ceiling.** docs/studies/OPT-C-timing.md refit the U50
runs against their asks - each 1 ns taken off the ask bought about
0.4 ns of path, so the 175 MHz run is a point on a slope rather than
the floor - and puts the ceiling at 147-157 MHz with 159 as the upper
end. docs/BRINGUP.md and docs/ROADMAP.md now quote the range.

**The ~$100 board.** The QMTech core board's `xc7k325tffg676-1` is the
-1 grade the previous entry routed at about 77 MHz; docs/PLATFORMS.md
and docs/ROADMAP.md recommended it without saying so and now do, with
the -2 alternatives named.

**Also folded in.** The routed table reached docs/ARCHITECTURE.md,
whose multi-cycle section still said implementation had not been run;
`hw/impl_krnl_ooc.tcl` now writes a routed checkpoint and reports 25
unique-pin paths rather than three, which is what a frequency sweep
needs to read.

**Not done here, on purpose.** None of the studies' designs - the
nested rungs, the retimed ladders, the pipelined leading-zero cone,
the indexed constants and the published caps. Those are proposals
with their own gates in the study documents.

## 2026-09-07 - the det library as sequencer programs: nineteen functions bit-identical, and the census corrected

Step 1 of docs/ATLAS.md's order of work, done in atlas-engine (branch
`cft-detlib`, commit af5feda, unmerged there) and recorded here because
it measured this project's claims. `gen-detlib --target cft` turns the
shipped det library - the thirteen det_* functions, their four helpers,
`u2f` and `hashu` - into sequencer instruction sequences, and
`tools/verify-cft-detlib.mjs` executes each sequence instruction by
instruction through libcft's `cft_run` at binary32 against an
interpreter over the shipped text, on 4,096-point sweeps per function:

    every emitted function reproduces the library's bits

Re-run by the integrator from the branch: the same line, 31 seconds.
NaN-payload-only differences are excluded and attributed to the oracle
(JavaScript has one NaN). `hashu`'s two integer multiplies are emulated
because opcode 30 does not exist yet - libcft answers it with a
canonical qNaN, measured.

**Three corrections to docs/ATLAS.md, each measured rather than
argued.** The library ships unfused: the generator rewrites all 56
`fma` calls (the census said 42) before the byte comparison that proves
it identical to the darkroom's, and emitting `FMA` gives 3,834 one-ULP
differences across 14 of 19 functions - a different library, not a
faster one. GLSL's `min`/`max` are comparisons, not 754's
`minimum`/`maximum`: the opcodes cost 36 mismatches in `det_atan` at
`det_atan(+0, NaN)`, compare-and-select costs 8 instructions
library-wide and none. `u2f` is nine instructions, not six.

**The asks, counted.** Eleven of nineteen functions need indexed
constants (`det_div` lands on exactly 16; `det_pow` wants 43), `hashu`
alone needs `IMUL`, `det_pow` alone needs a seventeenth register, and
no det function takes three inputs - the wider input block is the
positive's ask. All nineteen are 1,362 image words; `hopf` is 541 and
`jong` 466, and 28 of the 69 positives are over the 1,024-word image
on their det_* calls alone.

**Also run, after the report.** atlas-engine's `ci-smoke.mjs`: 69
positives smoked, 66 passing, 3 failing (`buddha`, `qjulia`, `vlsi`) -
the pre-existing failures its `known-smoke-failures.json` tolerates,
and "smoke matches the record"; the work touched none of the files it
exercises. **Not run.** The Chrome/GPU probes, and anything on a
device.

## 2026-09-07 - the browser reaches the tile: the frame protocol over WebSocket

A second transport for docs/REMOTE.md's frame protocol and a
JavaScript client for it. `cft-serve --ws PORT` opens a second
listener that speaks RFC 6455, and one WebSocket message carries
exactly one frame of the protocol, unchanged - the same 32-byte
header, the same little-endian fields, the same CRC-32 over the same
bytes. The protocol version does not move, because a transport is not
a protocol change. New: `host/tools/ws.c` and `ws.h` (the envelope,
the handshake, SHA-1 and base64), `bindings/wasm/remote.mjs` (the
frames in JavaScript, over WebSocket or TCP),
`bindings/wasm/remote.html` (a page that runs a check on the server
and in the wasm module beside it and compares them) and
`bindings/node/remote_test.mjs` (the same headless, `make -C host
wstest`).

### What the gate is, and what it scores

The same thing every backend is scored on: bit identity. A result the
server computes and sends over a WebSocket must equal the one the
local wasm module computes for the same bytes, and must equal the
golden model's published one. Beside that, two things specific to a
second transport:

- **The counters must not move.** The server counts PROTOCOL bytes -
  `CFTR_HDR_BYTES + length` - and frames by opcode, on both paths. The
  same sequence of calls over each transport must leave `STATS`
  saying the same thing, which is what "one message carries one frame"
  means operationally.
- **The refusals must still fire.** The protocol's own (a wrong magic,
  a corrupted CRC, a wrong ABI, a request before `HELLO`, a length
  past the cap) and docs/REMOTE.md's two negative controls.

### The measurements

DESKTOP-T33SK86 (Windows 11, MINGW64, gcc -O2, Node v22.19.0),
server and clients all on `127.0.0.1`, the box carrying other work.

**The TCP path, unchanged, with the WebSocket code compiled in.**
`make -C host remotetest`: `remote_check: every check passed` -
`remote-test` **245 checks, 0 failures** on both div/sqrt routes,
`device-test` against a remote handle **2,248 checks, 0 failed**, a
bounded 28-set replay **184,496 cases, all matching**, local and
remote reporting the same thing, and the Collatz sweep chain
`3d16b9d7ac66234495c47d202358df24aeeb0aaffc32e5babb0072f2d9e159b7`
local and remote. The frame path was not edited, which is why it is
a second listener and not a detection on the first; this run is what
that decision was for.

**The replay over WebSocket.** `node bindings/node/remote_test.mjs
--sets 20 --cases 11800`: **46 checks, 0 failures**. All twenty
opcode sets of `vectors/out`, every line - **392,000 cases** in 75.4
s - each run on the server over WebSocket, on the server over TCP,
and in the local wasm module, and the three compared as it went:

| comparison | result |
|---|---|
| WebSocket against the local wasm module | 392,000 cases, 0 differing |
| WebSocket against the golden model's published `d` | 392,000 cases, 0 differing |
| WebSocket against the published flag word | 392,000 cases, 0 differing |
| WebSocket against TCP | 392,000 cases, 0 differing |
| the reduction sets' sum and dot, as `REDUCE` frames | 2,560 cases, 0 differing |

**The counters.** After that work the two connections' `STATS` say
the same thing to the byte: **394,562 requests each, `RUN` x392,000
each, 40,958,524 bytes in and 21,700,888 out each**. The counters
count protocol bytes - header plus payload - so the envelope does
not move them, which is what "one message carries one frame" means
operationally.

**The envelope's own branches**, driven by a raw RFC 6455 client
written inside the test because a client library will not fragment
or ping on request: a `HELLO` split across three fragments is
answered; a ping comes back as a pong with the same 14 bytes; the
connection serves a request after the ping; a close is answered with
a close. `Sec-WebSocket-Accept` was recomputed with `node:crypto`'s
SHA-1 and matched, which is a second implementation of the thing
`tools/ws.c` implements.

**The refusals**, over WebSocket: a wrong magic, a corrupted CRC, an
oversize length (status 8), a wrong ABI (status 2), a request before
`HELLO` (status 1), a text message; and, before the upgrade, a `GET`
without `Upgrade` and a binary frame on the WebSocket port, each
`HTTP/1.1 400 Bad Request`.

**The negative control**, docs/REMOTE.md's two sabotages applied to
the JavaScript client. One bit of one returned encoding, flipped
after the CRC passed: the transport notices nothing - the frame was
well formed - and the comparison catches it, local
`0000000000000000000000000080ff7f` against sabotaged
`0100000000000000000000000080ff7f`. A `RUN` header claiming one byte
more than its payload holds: `truncated frame: the header claims 73
payload bytes and the WebSocket message carries 72`, and the handle
is poisoned for good. The message boundary catches it at once where
the TCP path waits out its stall minute - same verdict, sooner.

**The cost.** Three runs of 5,000 one-element calls and 500
batched ones, the same Node client over each transport:

| call | TCP | WebSocket |
|---|---|---|
| 1 fp64 element | 57.5 / 69.8 / 58.7 us | 81.7 / 70.4 / 77.4 us |
| 4,096 fp64 elements | 2.656 / 2.793 / 2.693 ms | 3.62 / 3.44 / 3.75 ms |

At one element the envelope disappears into the run-to-run spread.
At 4,096 it costs 0.65 to 1.06 ms over the 131,136 bytes that cross,
about 5 to 8 nanoseconds a byte, which is the masking RFC 6455 5.1
requires of a client and the server's unmasking of it: the
envelope's cost is per byte, not per call. These are a JavaScript
client's numbers and not the C client's - 22.5 us and 1.40 ms on
this box, from the entry above - so the comparable figure is TCP
against WebSocket from the same client, which is the table.

**In a browser.** Chrome on the same machine, the page served over
loopback HTTP: the caps block printed, a 512-element binary256 `fma`
identical to the tab's own module for all 16,384 bytes, a 300-case
`fp64.jsonl` replayed at 2,227 cases/s with 0 differing against the
module, the published `d` and the published flags, and 264 us a call
over 1,000 sequential one-element calls with the tab visible (5.1 ms
with it hidden - a background tab is throttled by two orders, which
is the browser's scheduling and not the transport).

### What was not run

Nothing crossed a network: every run was `127.0.0.1` on one machine,
and the cross-OS run of the 2026-09-06 entry was not repeated over
WebSocket. `host/tools/ws.c` was not built or run on Linux - it is
C99 over the same socket shim with no platform branch, but that is
an argument and not a measurement, and the desktop's WSL distro was
left alone for card day. No TLS: the server does not terminate it,
the client accepts a `wss://` URL for a proxy that does and that was
not exercised. The transcendental, character, augmented, formatOf
and scaled-product conformance families were not replayed over
WebSocket, because they are host compositions that never cross the
wire; `cft_conformance` replayed all seven through the TCP path. No
sequencer program was loaded from JavaScript, so `PROG_RUN` over
WebSocket is written and not exercised (`PROG_LOAD`'s frame path is,
with bytes that are not an image; the buffer and status-word
operations are, with real ones). No workload chain was computed
through the WebSocket path: the five tools are C and speak the TCP
one. And `verify/run.sh` was not touched - wiring `make -C host
wstest` into the `remote` stage is an integrator's call, not this
step's.

## 2026-09-07 - the tile's on-chip capacities, published and enforced the same way everywhere

Item 3 of docs/studies/OPT-D-contract.md, built. The defect it retires
is the one the previous entry recorded as live: `cft_seq` refuses a
program header past `MAXD` (64 deposit slots a lane) with `STATUS[3]`
and no explanation, `host/src/program.c` accepted 2^20, and no host
could ask which of the two it was talking to. The two workload tools
had a `#define TILE_MAX_DEPOSITS 64` copied out of the RTL, which is
right until a tile ships with a different number and which nothing
could check.

**`CAPS` (0x4C) now carries the capacities.** `[19:16]` is log2 of the
deposit slots a lane, `[23:20]` log2 of the instruction capacity,
`[27:24]` log2 of the constants an instruction can ADDRESS, `[7:4]` a
sequencer feature nibble and `[31:28]` reserved; the full tile reads
6, 10, 4, 0 and 0, so `CAPS` is 0x04A6FF0F where it was 0x0000FF0F. An
exponent rather than a count, which is what makes each fit four bits.
`rtl/cft_krnl.sv` names the three numbers once, as the localparams it
hands `cft_seq`, and passes their `$clog2` to `cft_csr`; the fourth is
the width of the instruction's `ka`/`kb`/`kc` operand field, four
bits, and must equal `cft_seq`'s `localparam int KREG = 16`.
`tb/test_krnl.py` parses both files and checks the readback against
them, so a capacity that moves without `CAPS` moving is a test
failure rather than a card-day surprise. The feature nibble is zero in
this build and its four assignments are reserved in `rtl/cft_csr.sv`
(wide constant index, init block, per-lane flags, static deposit) so
that two builds cannot spend one bit twice. `cft_seq.sv` is untouched:
its header check was already correct.

**VERSION does not move.** These are values inside a register that
already exists, which is the rule `cft_csr.sv` states for itself: a
host built for 0x600 reads them correctly, and a host reading an older
tile gets zeros. Zero is UNKNOWN throughout - `cft_caps` says so, the
XRT backend maps an all-zero `CAPS[27:16]` to it, and nothing is
enforced against an unknown, which is what keeps the card-day 0x410
images behaving exactly as they did.

**`cft_caps` grew by four fields** - `max_deposits`, `max_insns`,
`max_consts`, `seq_features` - which is what its `struct_size`
handshake exists for; a caller compiled against the old struct passes
the old size and is unaffected. Each backend reports what it enforces
and enforces what it reports: XRT decodes the register, the remote
backend takes them from `HELLO`, and the software backend reports its
own (1,048,576 deposit slots a lane, the header field's own
4,294,967,295 instructions, 16 addressable constants) from
`host/src/program.c`, the file that enforces them. `cft_program_load`
- not `cft_program_run`, because a program is built once and run many
times - refuses an image past any of them with `CFT_ERR_UNSUPPORTED`
and a `cft_last_error()` naming the cap and both numbers.

**The software backend was NOT narrowed to the tile's 64.** It models
the program model rather than one implementation of it, a smaller tile
is meant to be a conforming tile, and every recorded workload chain
was produced through its accepted set. So "it ran on software" still
does not mean "it fits a tile"; what changed is that finding out costs
one call. The accepted set is unchanged; one status code moved, from
`CFT_ERR_INVALID_ARGUMENT` to `CFT_ERR_UNSUPPORTED`, for a header
asking more than 2^20 deposit slots a lane, so that every backend
gives the same explained refusal at its own cap.

**The remote caps block grew from 56 to 72 bytes by appending**, and
the client accepts any block of at least 56 and leaves what a shorter
one does not carry at zero. `CFTR_PROTO_VERSION` deliberately does not
move: the `proto` field is compared for equality at both ends, so a
bump would turn "an older server answers with a shorter block" into
"an older server refuses the connection". The pairing the tolerance
describes cannot occur today anyway - the ABI equality check on every
frame already refuses two libraries whose ABI differs, and appending
to `cft_caps` is an ABI minor step - so the tolerance is insurance for
the next growth. **No old-server pairing was built or simulated.**

**The tools size themselves from the answer.** `cft-zoom` takes
`--steps-per-call` from `cap / 2` when the device's budget is smaller
than its default of 1,024, printing what it chose, because a trip
count changes only how many calls a run takes and not what it
computes; a value the user typed is refused instead, naming the cap.
`cft-orbits` refuses either way, because its sample count is part of
what is recorded. On the software backend the caps are larger than
either default, so neither tool's behaviour changes there and the
recorded chains do not move.

Gates run on this tree, on the Windows host and in the pinned
containers, each line as the run printed it:

- `make yosys-lint` (cft-formal image): exit 0, 30 warnings, all of
  them the pre-existing `Replacing memory ... with list of registers`
  notes in `rtl/cft_lanes.sv`; no errors and no latches.
- `make krnl`: `TESTS=2 PASS=2 FAIL=0 SKIP=0`
- `make krnlseq`: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- `make seqbanks`: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- `make faults`: `TESTS=5 PASS=5 FAIL=0 SKIP=0`
- `make quarter`: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- `test_krnl_smoke` (no Makefile target; run through `cocotb.mk`):
  `TESTS=2 PASS=2 FAIL=0 SKIP=0`
- `api-test`: `api-test: all contract checks passed`
- `reduce-parts`: `6294 partitions checked across 4 formats x 29 sizes
  x 7 part counts x 5 attributes`
- `cft-selftest ../vectors/out` over a bounded set generated for this
  run: `28 sets, 184496 cases, all matching`
- the C-versus-Python ABI comparison: `C and Python reached the same
  library and got the same bits`
- `seq_check.py --trials 250 --formats fp32 fp64 fp128 fp256`: `695
  programs run through both implementations, 305 refused by both` -
  `libcft and the golden model agree on every program: deposits,
  counts, flags and status`
- `make -C host remotetest` (the loopback server, its PID recorded and
  stopped by that PID): `remote_check: every check passed`. Inside it,
  `remote-test` **251 checks, 0 failures** on both div/sqrt routes,
  up from 245 by the six the caps block added; `device-test` against
  `cft://127.0.0.1` **2256 checks, 0 failed**; the conformance replay
  `28 sets, 184496 cases` identical local and remote; and the collatz
  sweep chain
  `3d16b9d7ac66234495c47d202358df24aeeb0aaffc32e5babb0072f2d9e159b7`
  the same both ways.
- `make zoomtest`: `11222 comparisons, 0 failures`
- `make orbitstest`: `26 checks, 0 failures`
- the four `cft-zoom` and `cft-orbits` rows of
  `bindings/wasm/demos_chains.json` replayed against this worktree's
  binaries: all four chains identical to the ones recorded on
  2026-09-04 (`ebec460e.../5fb8f0de...`, `9c830484.../878ae482...`,
  `12012be3...`, `3ebf95ae...`). Both tools' new branches are
  unreachable on the software backend, and the chains say so.

What `device-test` states rather than skips: an image past the
software backend's instruction cap would be 34,359,738,400 bytes and
is NOT TESTED, and a constant index past 15 does not fit the
instruction's four-bit field, so a device that addresses all sixteen
has no representable violation to refuse.

**The tools' device branches, exercised without a device.** Both
tools' new paths are unreachable on the software backend, whose caps
are larger than either default, so they were run against a SCRATCH
COPY of `host/` whose software backend reports the tile's numbers
instead - 64 deposit slots a lane, 1024 instructions, two lines in
`host/src/program.c` - the same method docs/REMOTE.md's negative
control uses, with the worktree's own binaries left alone. Against
that copy:

- `cft-zoom --engine program` at its default `--steps-per-call 1024`
  printed `--steps-per-call 1024 needs 2048 deposit slots a lane and
  the software backend holds 64; using 32 (cft_caps.max_deposits / 2)`
  and ran;
- the same run with `--steps-per-call 100` typed on the command line
  was refused: `--steps-per-call 100 deposits 200 values a lane per
  call and the software backend holds 64 (cft_caps.max_deposits): use
  --steps-per-call 32 or lower`;
- the resized run and an explicit `--steps-per-call 32` produced the
  same chain,
  `3bf0520b16eb4ef3a7e07c5454a6be6606051d590c39a788a14818029be6de9c`,
  which is the property that makes resizing a default safe: the trip
  count is a call boundary and not a result;
- `cft-orbits --engine program` at 16 samples was refused - `16
  samples deposit 68 values a lane and the software backend holds 64
  (cft_caps.max_deposits): record at most 15 samples a run - raise
  --sample-every or lower --periods`, exit 2 - and at 15 samples ran
  and produced chain
  `b09a54f42083c9f91c5a23742d077284b3dd7d667a82162546c84c7556327922`,
  which is the same chain its loop engine produces for that run.

**Not run.** No card, no hw_emu, no synthesis and no bitstream - the
`CAPS` change is twelve wires and a concatenation, and neither Vivado
nor XRT saw it here, so the XRT backend's decode of the new field has
been read and not executed. `make sim` as a whole was not run, only the
six benches above. `bindings/` was not touched and its suites were not
run; `bindings/python/cftmpfr/_lib.py` mirrors the OLD `cft_caps` and
is correct as it stands, because it passes its own `sizeof` and the
handshake stops the copy there.

## 2026-09-07 - the four parsers that face untrusted bytes, fuzzed

Four places in this repository read bytes somebody else wrote: the
server's frames (`host/tools/cft-serve.c`), the client's replies
(`host/src/backend_remote.c`), the program image
(`host/src/program.c`), and the five workload tools' `--resume`
readers. Everything else in libcft takes arguments, and a wrong
argument is the caller's mistake. None of the four had been fuzzed.
All four now are, opt-in, under `host/fuzz`.

**The engine, and why it is not libFuzzer.** There is no clang on
either machine this repository builds on - not on `PATH`, not in
`/c/msys64/clang64` or `/c/msys64/mingw64`, not in the `cft-sim`
image - and the image carries no AFL++ either. What both toolchains do
carry is gcc with `-fsanitize=address,undefined`, and the Linux one
also has `-fsanitize-coverage=trace-pc`, so `host/fuzz/cft_fuzz.c` is
the part of libFuzzer that matters here: an AFL-style edge map,
bucketed hit counts, a corpus that grows when an input reaches a
bucket nothing else reached, havoc mutation, and a structure-aware
repair pass per target - without which a mutated frame never gets past
its crc and the whole budget goes into proving that a wrong crc is
refused. The three in-process harnesses INCLUDE the files under test
rather than refactoring them (`rdev`, `do_request` and every request
handler are static), so the fuzz lane needed no diff to the server or
the client. The five workload tools are driven as processes, because
each `ckpt_read` is static inside its own main file and a resume is a
whole-process act anyway; that arm has no coverage feedback, and says
so.

The Windows toolchain has neither sanitiser, so every number here was
measured in the `cft-sim` image (gcc 13.3.0, Linux, `-O1 -g
-fsanitize=address,undefined -fno-sanitize-recover=all`) on
DESKTOP-T33SK86, one core per campaign, never more than four at once,
about two hours ten minutes of CPU in total.

| target | engine | executions | per second | crashes | fixed | differentials |
|---|---|---|---|---|---|---|
| `cft_program_load` | coverage-guided, in process | 13,390,661 in 1800 s | 7,439 | 0 | - | 1 |
| `cft-serve`'s handlers | coverage-guided, in process | 9,157,596 in 1800 s | 5,088 | 0 | - | - |
| `backend_remote`'s replies | coverage-guided, in process | 10,788,875 in 1800 s | 5,994 | 0 | - | - |
| the loader against the model | mutation, ctypes, no coverage | 70,000 images | ~340 | - | - | 1 |
| the five `--resume` readers | structure-aware mutation, as processes | 1,061 resumes | 0.1 to 2.7 | 2 | 2 | - |

Coverage reached: 135 of 32,768 map buckets for the loader, 1,378 for
the server, 303 for the client. The reproducer for every finding below
is under `host/fuzz/crashes`, and `make -C host fuzz-repro` replays
them: three files, each one refused by name where it used to be a
crash or an acceptance. Replaying every corpus entry once with
LeakSanitizer on - 78, 1,156 and 76 entries - reported no leak in any
of the three.

**Two out-of-bounds writes in cft-collatz's resume, both from a count
the file was trusted for.** `fill_batch` takes how many slots to fill
from `nrec`, the batch's record count, and where to put them from
`live`, the lanes in flight; an uninterrupted run keeps `live <= nrec`
because every lane it starts makes a record. The checkpoint reader
bounded each against `--batch` and neither against the other, so
`batchrecords 0` with `inflight 1` wrote the next batch past the end of
six 2,048-byte engine arrays - ASan: `heap-buffer-overflow WRITE of
size 32 ... fill_batch tools/collatz.c:1462`. And each in-flight lane
names the record its result goes to; that number was not bounded at
all, so `run ... 999999` sent `harvest`'s `val_to_dec` writing wherever
`recs[999999]` landed - ASan: `SEGV on unknown address`. Twelve of the
fuzzer's first 172 collatz resumes hit the first of the two. Both are
bounds checks now, both refuse by name, and `collatz_check.py` builds
both files from a real interrupted run and asserts exit 2 with a
message.

**A trip-count product that wraps, in the program loader.**
`seq_validate` bounds a program's worst-case instruction count at 2^40
by multiplying the enclosing loops' trip counts - `mult[top] =
mult[top - 1] * d.imm`, both `uint64_t`, checked AFTER the multiply. A
product past 2^64 wraps to a small number and passes. `repeat 2^16 /
repeat 2^17 / repeat 2^31` is exactly 2^64: libcft accepted it, and
`python/cft_golden/seq.py`, whose integers do not wrap, refused it with
"worst-case instruction count exceeds 1099511627776". So the C loader
took a program describing 2^64 iterations of its body while the model -
which is the definition of what a program is - threw it back, and
`cft-serve` would have run it, from a PROG_LOAD and a PROG_RUN
totalling 118 bytes. Checked before the multiply now
(`d.imm > SEQ_MAX_INSNS / mult[top - 1]`, which is exactly
`mult * imm > MAX` and needs no wider type): one line and a comment,
and no program either implementation accepted before is refused now.
`seq_check.py` grew a ninth named corruption, `wrap_trip`, that builds
this program every time it fires; the image is
`host/fuzz/crashes/program-differential/repeat-trip-product-wraps`.

Nothing else disagreed: 70,000 mutated images through both loaders,
4,198 accepted by both and the rest refused by both, no other
divergence.

**A run whose answer could never be sent, done anyway.** `RUN`'s length
check is `24 + popcount(mask) * n * elemsize`, so an operand mask of
zero constrains `n` not at all - and a mask of zero is legal, because
an unassigned opcode reads no operand and still has a defined result,
the canonical quiet NaN with invalid raised. `cft-serve` capped `n` so
the OPERANDS fit a frame and then answered with eight bytes of flags
and status in front of the results, which for the largest `n` the cap
admits is eight bytes past what `cftr_send_frame` will send: 2^28 fp32
elements, a gigabyte allocated, a gigabyte of arithmetic, and then a
failed send and a dropped connection. It is refused before the work
now, and `remote-test` sends exactly that frame and checks that a
refusal comes back promptly - 248 checks, 0 failures, where it was 245.
What is NOT fixed, because it is the transport's terms rather than a
defect, is that a well-formed operand-less request still asks for up to
2^25 fp256 results from fifty-six bytes on the wire. docs/REMOTE.md now
says so, in the section that has always said this is not a security
boundary.

**Three silent wrong resumes, in three tools.** Not crashes; the
sanitisers cannot see these. They came from reading what the readers do
not check and then running it.

* `cft-mersenne` took its squaring counter from the file without
  bounding it against the exponent's sequence. `current 521 100000`
  printed **"2^521 - 1 COMPOSITE, 519 squarings"** and exited 0.
  2^521 - 1 is a known Mersenne prime; past the end of the sequence the
  squaring loop runs zero times and the parked residue is reported as a
  finished Lucas-Lehmer test. `current 521 -5` squares five times too
  many and reports a different wrong residue.
* `cft-enclose` took its series term counter the same way. `inflight 23
  1000`, where the recurrence for fp64 has 18 terms, finished the run
  and printed a full set of enclosures - exit 0, a different chain -
  that do not enclose, because the tail bound was charged to partial
  sums as though every term had been summed. In a tool whose entire
  claim is that the true value lies between its two numbers.
* `cft-zoom` records an escape as `escaped_at = k` at the iteration it
  happens on. `escapedat 7` on a 2,000-iteration reference skipped the
  orbit entirely and reported `k = 185, escaped at 7, orbit flags 0x00`
  and a different chain, exit 0.

Each is one bounds check and a named refusal, and each tool's own check
script now builds the file from a real interrupted run and asserts exit
2. `cft-orbits` needed nothing: its `state` and `inv` lines already
refuse a member index out of range, and its step and sample counters
are counters rather than indices.

**A second checkpoint campaign, against the patched tools.** 310
resumes over the five tools: 104 accepted, 206 refused by name, no
crash, no hang, no other exit status.

**One false positive, recorded because the harness was wrong and the
tool was not.** The first checkpoint campaign reported a hang in
`cft-zoom`. It was not one: zoom derives its fp256 centre BEFORE it
reads the checkpoint, so a resume it refuses outright still takes 11 to
25 seconds under the sanitisers, and the 20-second budget was inside
that window. The saved file is refused correctly - `bad checkpoint
orbit line`, exit 2 - 24 seconds in. The budget is 90 seconds now. A
fuzzer whose hang budget is shorter than its target's start-up reports
start-up.

**Gates, re-run on the patched tree.** In the `cft-sim` image (gcc
13.3.0, Linux): `make test` "28 sets, 184496 cases, all matching" over
a bounded generated set, plus api-test, reduce-parts and the C/Python
identity; `seqtest` 674 programs, 326 refused by both, "libcft and the
golden model agree on every program: deposits, counts, flags and
status"; `remotetest` "remote_check: every check passed", inside it
`device-test` 2,248 checks 0 failed and `remote-test` 248 checks 0
failures on both div/sqrt routes; `collatztest` 18,110 comparisons 0
failures; `enclosetest` 2,662 comparisons 0 failures; `mersennetest`
391 comparisons 0 failures; `orbitstest` 26 checks 0 failures;
`zoomtest` 11,223 comparisons 0 failures;
`program_differential.py --trials 50000` "0 disagreements";
`fuzz-repro` three reproducers, all handled. On Windows (MSYS2 mingw64
gcc 16.1.0, no sanitisers): a clean `make all` with no new warning
under `-Wall -Wextra -Wpedantic -Wshadow`, `seqtest` the same 674
programs, `mersennetest` 391 comparisons 0 failures, and
`remote_check.py` "remote_check: every check passed" against a
loopback server it started and stopped by PID. The default build is
unchanged: `make -C host` still needs one C99 compiler and no
sanitiser, and nothing under `host/fuzz` is a prerequisite of `all`.

**What was not run.** No RTL, no simulation, no hardware - nothing here
touches `rtl/`, `tb/` or the card. The full published vector replay was
not run: `vectors/out` is generated rather than committed and this
worktree had none, so `make test` ran against the same bounded set
`remote_check.py` generates - 184,496 cases - rather than the 1.2
million the runner's `vectors` stage makes. On Windows only the build,
`seqtest`, `mersennetest` and `remote_check.py` were re-run; the other
four workload checks were run on Linux alone. The sanitisers are
Linux-only here, so nothing was ever run under ASan or UBSan on
Windows. libFuzzer and AFL++ were not used, for the reason at the top;
neither was a coverage-guided arm for the checkpoint readers, which are
subprocess-driven and blind, and which therefore got a thousand resumes
where the in-process targets got tens of millions of executions. And
two hours of CPU across five targets is a first pass, not a clean bill:
thirteen million executions of the loader found nothing it gets wrong
about a header it already checks, which is a weaker statement than it
looks.

## 2026-09-07 - the sequencer's program API in JavaScript, and two demo panels that run on it

`cft_run` applies one operation to every element; a program applies a
SEQUENCE to every element without the operands making a round trip to
memory between steps. The library has had `cft_program_load`,
`cft_program_get_info`, `cft_program_run` and `cft_program_free` since
the sequencer was written, and until today no JavaScript caller could
reach any of them: the wasm module exported 111 `cftw_*` entry points
and not one of those four. docs/DEMOS.md recorded the consequence in
its own words - "the wasm surface exposes every library operation but
not the sequencer's program API" - and measured what it cost in a table
taken from the C tools, because the browser gap could not be measured
at all.

That is closed. **116 `cftw_*` exports**, five of them new; the node
package has a `Program`; and the zoom and orbits panels of
`bindings/wasm/demos.html` carry their tool's program engine as a
control.

Nothing under `host/src/`, `host/include/`, `host/tools/`, `rtl/`,
`python/` or `verify/` was touched and **no ABI number moved**: this is
a binding catching up with a contract that has not changed.
`host/tests/seq_check.py`, the library's own live gate for the
sequencer, is unmodified and stays the definition of whether the
executor is right.

### The C ABI, projected

One wrapper per declaration in cft.h's program section, in cft.h's
order, plus one projection. Three are not plain passthroughs and each
reason is the contract's:

- **the handle is an out-parameter** for `cftw_program_load`, as it is
  for `cftw_open_software`;
- **`cftw_program_get_info` projects the sized struct into four
  out-pointers** rather than copying it into the heap - a JS caller
  reading struct offsets is the silent ABI coupling the `struct_size`
  handshake exists to prevent. One call rather than four accessors,
  because a program's shape is fixed at load and because format's `0`
  is `fp32`, a legitimate answer, so an accessor returning 0 on failure
  could not say which of the two had happened;
- **`cftw_status_deposit_overflow()` projects a MACRO**, which is the
  one part of a header the far side of a wasm boundary cannot reach -
  the problem `CFT_FLAGS_ALL` has and the same answer. It matters here
  more than usual: that bit has already moved once, from STATUS[3] to
  STATUS[4] on 2026-09-01. Both JavaScript surfaces audit it against
  their own copy at load time and refuse to run if they disagree.

`bindings/node` gains `Program`: `ctx.loadProgram(image)`,
`prog.format` / `maxDeposits` / `nInsns` / `nConsts` read back through
`cft_program_get_info`, `prog.run(a, b, c)` returning
`{ deposits, counts, flags, status, depositOverflow }`, and `free()`.
There is deliberately **no assembler** in `core.mjs`: an image is
bytes, `cft_program_load` is the validator, and a second validator on
the JavaScript side would be a second opinion about what a device may
execute.

### What was verified

**The recorded corpus: 192 cases, 126 run and 66 refused.**
`host/tests/seq_check.py` is the live comparison and needs a built
library and a Python that can import `cft_golden`; `bindings/node` has
neither by design. So `bindings/node/make_seq_corpus.py` writes the C
executor's answers down once - refusing to record any case the golden
model disagrees with - and `program_test.mjs` and `test.mjs` replay
them through `cft_program_load` / `cft_program_run` in wasm. The
programs are `cft_golden.seq.random_program` from seed 2609, 48 per
format; roughly a third are deliberately corrupted by `seq_check.py`'s own `corrupt()`,
so a binding that loaded every program would pass every value
comparison in the file and still be wrong about what a loader is for.
`--check` regenerates the file and refuses if a byte moved; it does.

    node bindings/node/program_test.mjs
    corpus  126 programs run, 66 refused, 4492 deposits and 2680 counts
            compared, 46 runs overflowed their deposit budget
    17 passed, 0 failed

Beside the corpus, programs written by hand - a countdown loop with
`SETACT` and `DEPOSIT` whose expected deposits are derived from
docs/SEQUENCER.md and readable beside it - carry the two behaviours a
fuzz corpus records without explaining: **the early exit is invisible**
(trip counts 4, 9 and 40 agree on every deposit, count, flag and status
once every lane has dropped out, which is P3 in the one place a
JavaScript caller can check it) and **overflow drops the tail and says
so** (two slots, four deposits: what fit is right, the count is what
fit, `status` is bit 4 and `flags` is zero, because "your buffer was
too small" is not one of the five 754 names). Also: `n = 0` is an
answer; a zero deposit budget is a program and every deposit overflows;
`b` and `c` may be omitted and those registers start at `+0`; deposit
addresses do not move when the array grows (P2); a program carries its
own format; nine loader refusals arrive as errors carrying the
library's own words; and a freed program refuses every later call.

**Memory.** 2,000 load/run/free cycles, 2,000 load/free cycles, and
2,000 REFUSED loads - the path nobody exercises, where
`cft_program_load` frees its own partial allocation - each leave the
wasm heap the size it was and a probe allocation at the same address.

**A negative control**, because a checker that has never been seen to
fail proves nothing: one flipped bit in one deposit, a wrong count, a
wrong flag word, a wrong STATUS word, a wrong deposit budget, and a
refused program relabelled as one that runs - all six are caught.

### The two demo panels

`demos_core.js` ports `pack_program` and the instruction encoders from
`host/tools/zoom.c` and `host/tools/orbits.c`. It is the third copy of
three - each tool carries its own - and a copy is only worth having if
something checks it, so the check is the bytes:

| image | bytes | sha256 |
|---|---|---|
| the nucleus scan, 51 iterations at fp256 | 136 | `8fad50d414aadc68…` |
| the reference orbit, 1,001 iterations at fp256 | 248 | `9aaefec8adf583c6…` |
| the reference orbit, 1,001 iterations at fp64 | 176 | `752e5489d358303d…` |
| the Kepler integration at fp256, 49 instructions | 552 | `adcd627af5f1e71b…` |
| the Kepler integration at fp64, 37 instructions | 360 | `d1ded7c1613b3509…` |

Every one is the image the C tool loads, **byte for byte**. They were
dumped from the tools themselves by compiling `host/tools/*.c` exactly
as they stand and linking with `-Wl,--wrap=cft_program_load` and a shim
that writes the image out before forwarding; nothing under `host/` was
edited to get them. `verify_demos.mjs` step 4 now hashes each image the
core loads against those five, and `demos_core.js` asks
`cft_program_get_info` what the loader read back and refuses if it
disagrees with what it packed.

The orbits panel needed a second pair of runs to say anything at all.
`cft-orbits` refuses `--engine program` with `--rsqrt exact`, for a
reason that is a fact about the program model rather than the tool: the
correctly rounded 1/r^3 route is `cft_sqrt` and `cft_div`, themselves
programs partitioned host-prep / program-core / host-finish, and they
cannot sit inside another program's loop body. So the recorded
`fp256`/`fp64` pair stays the correctly rounded route and stays
loop-only, and a `fp256-newton` / `fp64-newton` pair was recorded beside
it - the same integration with the tile's own `rsqrt` seed and a
DERIVED number of Newton refinements, which is the route a program can
hold. Different arithmetic, its own chains, and not a second spelling
of the first pair. The recording is now **13 configurations over 15
chains**.

`engine` is left out of the page's `sameCfg()`, which is the claim
rather than a way of ducking a comparison: the two engines are one
configuration, so a chain computed either way is comparable - and if
they ever parted, the page says DIFFER rather than "other config".

### The gates

| gate | the line it printed |
|---|---|
| `node bindings/node/test.mjs` | `126 passed, 0 failed` - the 125 that were there plus the corpus replay, which reports `sequencer  126 programs run and 66 refused from seq_corpus.jsonl, 4492 deposits and 2680 counts compared with the C executor` |
| `node bindings/node/program_test.mjs` | `17 passed, 0 failed`, over `corpus  126 programs run, 66 refused, 4492 deposits and 2680 counts compared, 46 runs overflowed their deposit budget` |
| `node bindings/node/conformance.mjs` | `1,067,635 cases over 168 sets, library matches the vectors exactly (1036.5s)`, then `831,635 cases over 148 sets, through this package's own methods, encodings, sequences, scales and flags exact (1030.8s)`, then `1,899,270 cases over 316 set replays in all - a pass.` - the published result line, unchanged |
| `node bindings/wasm/verify.mjs` | `exports 116 cftw_* entry points`, `needed  85 named entry points checked present`, `831,635 cases over 148 sets driven through the wrappers themselves`, `VERIFY OK` |
| `node bindings/wasm/verify_demos.mjs` | 44 `ok` lines and no `FAIL`: `VERDICT: the browser's compute core produced the C tools' chains, over the module the conformance page embeds` |
| Chromium, the committed page over a loopback `http.server` | every panel run with the program engine selected on zoom and orbits: `15 of 15 chains computed in this browser, every one identical to the C tool's`, and **no console message of any level** |
| `python bindings/node/make_seq_corpus.py --check` | `192 cases, identical to a fresh generation` |
| two clean container builds, `bindings/wasm/build/` removed between | the module, its node loader and `conformance.html` byte-identical; `demos.html` byte-identical |

### What it bought, measured

Median of fifteen runs each, alternating engine run by run, through
the compute core on the committed module under node 22. **The machine
was not quiet** - this desktop was running several other jobs
throughout, and the per-run spread is wide because of it. Alternating
the engines is what makes the ratio survive that: both halves of each
pair met the same load. Read them against the C tools' own gap for the
same work, measured on 2026-09-04 - 1.40x for the reference orbit and
1.26x for the Kepler integration. Every row is above its C counterpart,
which is the prediction docs/DEMOS.md made when it could not yet
measure this: what a program removes is call boundaries, and a wasm
boundary costs more than a C one.

| the page's configuration | program | host loop | program removes | library calls |
|---|---|---|---|---|
| zoom, the 1,001-iteration reference orbit at fp256 | 0.026 s | 0.040 s | **1.56x** | 12 against 8,019 |
| zoom, the reference orbit at fp64 | 0.011 s | 0.017 s | **1.51x** | 12 against 8,019 |
| zoom, the nucleus scan and bisection (one lane a call) at fp256 | 0.050 s | 0.076 s | **1.53x** | not counted - the panel's counters are lowered after the centre is derived |
| orbits, the whole Kepler integration at fp256, `--rsqrt newton` | 0.865 s | 1.140 s | **1.32x** | 1,100 against 74,827 |
| orbits, the same at fp64 | 0.287 s | 0.394 s | **1.37x** | 1,100 against 50,251 |

The zoom rows are the two phases the program engine touches, timed
apart because their call shapes are opposite: the reference orbit is
one call of 1,001 iterations on one lane, and the nucleus scan is 320
candidates in one call followed by about two hundred bisection steps of
one lane each. Together they are under a tenth of a second, so **the
zoom panel as a whole is no faster** - its nineteen seconds are its
pixel phase, which runs through `cft_run` in the C tool too, and the
page's own report line says so. For the orbits panel's `--rsqrt exact` argument the program API
still buys nothing, which is not a disappointment but the last of
docs/SEQUENCER.md's recorded asks - a callable composed operation -
with a number beside it.

### What was rebuilt, and what was not

The module changed, because it gained five exports, and everything
downstream of it was rebuilt from the pinned container. **Each build
product was produced twice from a clean `bindings/wasm/build/` and came
out byte-identical both times**, which is what makes the hashes below
worth quoting:

| | |
|---|---|
| `bindings/node/cft_node.wasm` | 212,642 bytes, sha256 `f0975f3da635e92d8a5060f7843a0cf16af860b8b16f60d15f0edab631104768` |
| `bindings/wasm/conformance.html` | 1,337,454 bytes, sha256 `89e0dc54fa720247571c7a4be996048b4146fa42b9f48ba56f5a783c77ffef7a` |
| `bindings/wasm/demos.html` | 523,351 bytes, sha256 `2b75d080fafd8d2a887b0bdd18d5a5befb80e3467067d7b25ccc6487bfade5df` |
| `bindings/wasm/demos_core.js` | sha256 `0fc4643a77d988253c81ad5c229cbd688d1588e46109d5d90f89880a99b57e5c` |

`bindings/wasm/README.md` still says 111 exports and quotes the
previous module and page hashes; it is not in this change's scope and
is stale until an integrator updates it.

### What was not run

- **No device.** The panels and the tests are the software backend,
  which is the only backend a browser can be. Nothing here is a
  hardware number, and no sequencer program went through hw_emu or a
  card in this work.
- **`host/tests/seq_check.py` was not re-run as a gate** - it is
  unchanged and its subject is unchanged. `make_seq_corpus.py` drives
  the same model and the same library and refuses to record a
  disagreement, so it ran the comparison 126 times while recording.
- **The demos page's own negative control was rebuilt but not
  re-driven.** `bindings/wasm/build/demos_negative_control.html` is
  produced by stage 4 as before; the sabotage site in `demos_core.js`
  is untouched and still appears exactly once, which `make_demos.py`
  checks, but no one watched it go red today.
- **The rates table in docs/DEMOS.md was not re-measured.** It is the
  2026-09-04 recording and says so; the two newton rows are new and
  have no browser column in it.

## 2026-09-07 - the multi-cycle rung's exactness, proven at the real chunk width

The 2026-09-06 entry left one thing open. A bounded proof that
`cft_mulpass`' pass-accumulated product equals the pipe's side-by-side
array's ran four hours without returning and was stopped, so the rung's
bit identity rested on the benches and `formal/mulpass.sby` sat outside
the gate with a comment saying why. This entry closes the claim at
`CFT_MUL_MCH = 24` - the chunk the tile synthesises - for **every pass
geometry `cft_lanes` can build**, two independent ways, and records
what each cost and what did not close. formal/ only: no RTL, bench,
host or Python file is touched.

**The seven geometries.** `rtl/cft_mulgeom.svh` maps (P, MUL_PASSES) to
(COLS, passes). `cft_lanes` builds the fp64, fp128 and fp256 rungs at
P = 53, 113 and 237 and `MUL_PASSES` 2, 5 and 10; fp32 is one chunk and
never multi-pass. That is seven distinct (P, COLS) pairs, and all seven
are proven. The pass count each task claims is handed to its harness as
`EXP_NP` and re-derived there from cft_mulgeom.svh's own functions, so
a task whose geometry table drifts from the header refuses to elaborate
rather than proving something about a rung nobody builds.

**What made it close: not asking a solver to compare two multipliers.**
Split into three lemmas, none of them contains any multiplier
reasoning.

* **A, the fold** (`formal/tb_mulfold_formal.sv`). Every `dut.pcol[c]`
  - the column registers - is made a yosys `cutpoint`, which replaces
  the register and the multiplier behind it with an unconstrained
  value, and the harness reads those free values back. The claim is
  that the in-pass tree, the shift-accumulate with its shift-out
  register, the completed-product latch and the `en`-clocked level
  chain deliver at level 5 one operation's own column values summed at
  their column weights. Linear in those values. The .sby then asserts
  on the prepared model that no `$mul` cell survives, so the
  abstraction cannot silently not have happened.
* **B, the operands** (`formal/tb_mulsel_formal.sv`). `dut.a_r` and
  `dut.bsel_r` are probed: on pass p they hold the captured `a` and
  chunk group p of the captured `b`, at every offset in the interval
  including the boundary cycle where the operand registers still carry
  the previous operation's last pass.
* **C, the columns** (same harness). The column register holds those
  operands' product - written from the DUT's own operand wires so that
  yosys' `opt_merge` folds the reference multiply onto the module's own
  `$mul`, which the .sby checks by counting cells - a column the tree
  reads but the geometry does not build holds zero, and a built one is
  below 2^(P+24). The last two are exactly lemma A's side-conditions.

Multiplication is a function, so equal operands give equal products;
substituting B and C into A gives `sum_k (a * b[24k +: 24]) << 24k`
truncated to 2P, which is `cft_fpfma_pipe.sv`'s `g_mul_local`
expression term for term. formal/README.md writes the substitution out
and names the one thing the composition asserts rather than proves.

**No copy of the RTL exists anywhere in formal/.** `rtl/cft_mulpass.sv`
is read unmodified; the cut and the probes are made by `cutpoint` and
`connect -nounset -set` on the flattened netlist, because the Yosys
frontend gives formal code no in-language way to name a submodule's
internals - the same limitation that made the FIFO proof use `abc pdr`
instead of a hand-written invariant.

**What closed** (`formal/mulexact.sby`, bitwuzla 0.9.1 in the pinned
cft-formal image, one task at a time on the shared desktop with other
agents' simulations running, so these are upper bounds):

| task | P | COLS | passes | rung | checks | result | s |
|---|---|---|---|---|---|---|---|
| `fold_53c2` | 53 | 2 | 2 | fp64 x2 | 1 assert | pass | 10 |
| `sel_53c2` | 53 | 2 | 2 | fp64 x2 | 6 asserts | pass | 10 |
| `fold_53c1` | 53 | 1 | 3 | fp64 x5, x10 | 1 assert | pass | 11 |
| `sel_53c1` | 53 | 1 | 3 | fp64 x5, x10 | 3 asserts | pass | 11 |
| `fold_113c3` | 113 | 3 | 2 | fp128 x2 | 1 assert | pass | 9 |
| `sel_113c3` | 113 | 3 | 2 | fp128 x2 | 9 asserts | pass | 23 |
| `fold_113c1` | 113 | 1 | 5 | fp128 x5, x10 | 1 assert | pass | 10 |
| `sel_113c1` | 113 | 1 | 5 | fp128 x5, x10 | 3 asserts | pass | 5 |
| `fold_237c5` | 237 | 5 | 2 | fp256 x2 | 1 assert | pass | 277 |
| `sel_237c5` | 237 | 5 | 2 | fp256 x2 | 15 asserts | pass | 78 |
| `fold_237c2` | 237 | 2 | 5 | fp256 x5 | 1 assert | pass | 19 |
| `sel_237c2` | 237 | 2 | 5 | fp256 x5 | 6 asserts | pass | 36 |
| `fold_237c1` | 237 | 1 | 10 | fp256 x10 | 1 assert | pass | 12 |
| `sel_237c1` | 237 | 1 | 10 | fp256 x10 | 3 asserts | pass | 50 |
| `cover_fold` | 237 | 1 | 10 | - | 2 covers | pass | 76 |
| `cover_sel` | 237 | 1 | 10 | - | 4 covers | pass | 93 |

The check counts are read off the model sby actually solved, not off
the source; see the vacuity paragraph below.

**And the single property closes too, at four of the seven.**
`formal/mulpass_real.sby` asserts the whole thing in one place - the
module's output against the pipe's own column-sum expression, both
multipliers standing, no lemmas and no composition. That is the form
the 2026-09-06 entry could not get to return. It returns now for every
single-column geometry and for the smallest two-column one, **including
fp256 at MUL_PASSES = 10, the deepest configuration the tile builds**,
and those four tasks are now in the gate as an unfactored check under
the composition argument:

| task | P | COLS | passes | rung | boolector | bitwuzla |
|---|---|---|---|---|---|---|
| `p53c2` | 53 | 2 | 2 | fp64 x2 | **pass, 37 s** | pass, 47 s |
| `p53c1` | 53 | 1 | 3 | fp64 x5, x10 | **pass, 29 s** | no return in 60 min, step 19 |
| `p113c1` | 113 | 1 | 5 | fp128 x5, x10 | **pass, 39 s** | no return in 15 min, step 31 |
| `p237c1` | 237 | 1 | 10 | fp256 x10 | **pass, 133 s** | not run |
| `p113c3` | 113 | 3 | 2 | fp128 x2 | no return in 28 min, step 13 | no return in 15 min, step 13 |
| `p237c2` | 237 | 2 | 5 | fp256 x5 | no return in 15 min, step 31 | not run |
| `p237c5` | 237 | 5 | 2 | fp256 x2 | no return in 15 min, step 13 | not run |

**The obstacle, stated exactly.** Every failing task stalls inside the
first cycle at which its assertion is active - step 13 where the
interval is two passes, step 31 where it is five - never on the
unrolling, which finishes in seconds. That is the first query that
actually contains both multiplier arrays. The solver cannot match the
two sides' partial products structurally, because the module's operands
reach its `$mul` through registers and a variable-index chunk mux while
the reference's are combinational slices of the same operand at a
different width, so it bit-blasts a P x 24 array equality. The three
that stall are the three that build more than one column at P >= 113;
adding columns multiplies the number of such arrays in each query. Logs
are under the scratch path in this session's notes; each is an sby
workdir with the engine's own step-by-step trace.

**The engine mattered more than the property did.** Every other proof in
formal/ runs on bitwuzla, which is boolector's successor and faster on
all of them. On this property they are not comparable: bitwuzla did not
return on `p53c1` in **sixty minutes** and boolector closed the same
task in **twenty-nine seconds**. On the same task with a five-minute
bound each, yices, z3 and cvc5 all returned nothing, and the two AIG
engines never reached a solver at all - `abc bmc3` and `aiger aigbmc`
both fail in the model build with "Design contains 'x' or 'z' bits",
eight seconds in. So `formal/mulpass_real.sby` carries its own
`[engines]` line rather than inheriting the directory's, with the
measurement written beside it. Six engines were tried; one worked.

**The narrow-chunk file, for the record.** `formal/mulpass.sby` is the
same single property with `CFT_MUL_MCH_FORMAL=4`, kept out of the gate
because a narrowed chunk is not the tile's arithmetic. Re-run on
bitwuzla with the geometry cross-check added: `n18c1` passes in 22 s,
`n18c3` in 46 s, its `cover` task in 33 s, and the real-chunk `r49c2`
in 93 s - but `n38c5`, five columns even at a four-bit chunk, did not
return in 15 minutes. The claim in the 2026-09-06 entry that the narrow
tasks are where the property closes is therefore only true of the
narrow tasks with few columns; it is the column count, not the chunk
width, that this property founders on.

**Commissioning: six mutations, six refutations.** A decomposition can
be wrong in a way a single property cannot - each lemma passing while
the seam between them leaks - so each mutation was applied to a scratch
copy of rtl/ and formal/ and run against the task that ought to catch
it:

| mutation | caught by | refuted at |
|---|---|---|
| `acc <= s[P+K:K]` clears bit 3 - one carry dropped per pass | `fold_53c1`, `fold_53c2` | step 19, step 13 |
| the shift-out register keeps one stale low bit | `fold_53c1` | step 19 |
| the level chain is read one enabled edge short | `fold_53c1` | step 19 |
| the chunk group is selected one pass early (`pidx + 1`) | `sel_53c1`, `sel_53c2` | step 7, step 5 |
| a column multiplies the wrong chunk of its own group | `sel_53c2` | step 5, on two columns at once |
| **the harness's** own pass window is one cycle late (`ed[2]`) | `fold_53c1` | step 19 |

The last row mutates nothing in the RTL. It moves the harness's own
idea of which cycles belong to which operation, and if lemma A were
checking arithmetic and not timing it would still have passed. It did
not, so the fold's alignment to the pipeline enable is inside the
claim.

**A vacuity check that earned itself the same afternoon.** `chparam`
with a selection that matches nothing is silent. An early
`formal/mulexact.sby` used `chparam ... tb_*`, which matched nothing,
and every task ran at the harness's default geometry and passed. The
harness-side fix is `EXP_NP`. The general fix is in `formal/run.sh`:
every task, old and new, is now checked after it runs against
`<workdir>/model/design_prep.il` - the netlist sby handed the engine -
for a minimum number of surviving `$assert` and `$cover` cells, so a
task whose checks were dropped fails the gate even though the engine
said pass. The pre-run preflight is kept for the four single-file
harnesses; it cannot cover a model that only exists after a flatten and
a cutpoint, and mirroring those commands in a second script would be a
copy to drift. The same afternoon also cost an hour to a second silent
failure: `connect -set` unsets every existing driver of its left-hand
side, and a bare `assign qv = {qw7, ..., qw0}` in a harness makes `qv`
and `qw0` one net as far as yosys' signal map is concerned, so the
default quietly took the harness's own concatenation apart. Every
`connect` in mulexact.sby now carries `-nounset`, with a comment
saying why.

**The gate.** `formal/run.sh` was seven verdicts and 33 seconds. It is
now **27 of 27 in 14 minutes** on this host - 835 seconds of proof time
plus the preflight - and it still exits nonzero unless every proof
passes AND `negcontrol.sby`'s deliberately false property is refuted,
which it was, at step 3, as always. Twenty of the twenty-seven verdicts
and about thirteen of the fourteen minutes are cft_mulpass; the single
most expensive task is `mulexact.sby fold_237c5` at 237 seconds, which
is the widest in-pass tree the tile builds. One small correction went
in with it: the verdict count is now counted rather than written down,
because the line had said "11 of 11" while printing seven.

**Not run.** The proofs pace `cft_mulpass` at exactly the live rung's
pass count, which is what `cft_lanes` gives it; the module's header
also claims that a lane seeing a LONGER enabled period still produces
the right product by folding zeros, and that is not proven here.
`mulpass_real.sby`'s three failing tasks were given 15-minute
observation bounds rather than the full hour, except `p113c3` which got
28 minutes and `p53c1` under bitwuzla which got the full 60; no attempt
was made to find a bound at which they do return. No simulation, no
synthesis and no board work is in this entry, and none of the
2026-09-06 entry's area or bench numbers is re-measured or changed.

## 2026-09-07 - the leading-zero cone cut and rebuilt, LATENCY 15 to 16

docs/studies/OPT-C-timing.md's first and seventh ideas, built and gated.
Idea 1 puts a register boundary inside the S10->S11 leading-zero cone,
which the 2026-09-06 routed reports made 8.77 ns of an 11.55 ns fp256
path; idea 7 replaces the cone's two priority scans with balanced
(valid, count) trees. `LATENCY` is 16 edges now, S0..S15.

**What moved.** `rtl/cft_fpfma_pipe.sv`: the cone is `cft_lzcone`, a
module at the foot of the file, and a new S11 register holds its answer
- the window, the total shift, the msb, the empty flag - beside the
sign, the exponent anchor, the residue rail and the whole specials
sideband. Every parallel path crossing the boundary is registered in the
same commit, because this pipe is synchronised rather than linear and
the last stage added to it produced garbage, not drift. `DEPTH` 15 -> 16
carried the rounding-attribute delay line with it untouched: its taps
have always been written relative to `DEPTH`. The three `.LATENCY(15)`
in `rtl/cft_krnl.sv` and the parameter defaults in `cft_lanes` and
`cft_seq` follow; `cft_reduce_acc`'s `ADD_LATENCY` follows through
`cft_engine_stream`'s `LATENCY + 1` with no edit, and `cft_normseg`
needed none - its two-cycle contract is independent of the pipe's depth.
Nine testbench sites named 15 and now name 16. One file was already
ahead of the RTL: `hw/synth_ooc.tcl` says `set latency 16` with a
comment that the default must track the depth, and at depth 15 that
script could not have elaborated.

**NBEATS did not have to move, and docs/ROADMAP.md said it would.** That
file recorded "LATENCY 16 forces NBEATS to 32 and changes the block
model seq.py is bit-exact to", from the parameter's own comment (`>=
LATENCY + 1`). The relation is about keeping the pipe full, not about
correctness - results retire in arrival order through `wb_bt`, and
`S_ALU_ISSUE` and `S_ALU_WAIT` both run the writeback path - and
`python/cft_golden/seq.py` does not model blocks at all. `NBEATS` stays
16, `seq_core`'s nine tests pass at LATENCY 16, and the parameter now
carries the elaboration guard docs/ROADMAP.md asked for, stating the
constraint that is real: the register file addresses a beat in four
bits.

**The shape of the cone was decided by the simulator, not the fabric.**
Idea 7 as the study writes it is one radix-4 tree over the whole window.
That was built, proved bit-identical, and measured - and it costs the
cocotb matrix a factor it cannot afford. `tb_fpfma_fp32` and
`tb_fpfma_fp256` at `CFT_RANDOM=300`, cocotb's own elapsed time, every
form at LATENCY 16 and every form bit-identical to the others:

| cft_lzcone form | fp32 | fp256 |
|---|---|---|
| the priority scans it replaced | 21.6 s | 18.2 s |
| one tree, generate pyramid, one assign per node | 528.1 s | - |
| one tree, one process, per-level loops | 66.7 s | 71.4 s |
| one tree, one process, flat node loop | 47.6 s | 77.0 s |
| **chunk detect kept, trees where the scans were** | **20.2 s** | **25.8 s** |

Two things in that table. A generate pyramid needs multiply driven nets
and Icarus schedules every driver as its own event - 24x on fp32, for a
netlist that is otherwise identical. And a tree over 717 bits is 341
nodes where the old cone was twelve vector compares and one
64-iteration scan, which is the remaining 4x. The shipping form keeps
the 64-bit chunk zero-detect - the one part of the old cone Vivado
already mapped well, five CARRY4 for 0.484 ns - and puts trees only
where the two PRIORITY SCANS were: the twelve chunk flags, and the
sixty-four bits of the one chunk that matters.

**Gates that returned**, all on the committed tree, in the pinned
images:

- `formal/run.sh` in cft-formal: `FORMAL GATE: PASS (11 of 11, negative
  control refuted)`. Four of those eleven are new - `lzcone.sby` at
  fp32/fp64/fp128/fp256, a combinational equivalence miter of
  `cft_lzcone` against `formal/cft_lzcone_ref.sv`, the priority-loop
  form frozen at the moment of the split. Both sides combinational, so
  each BMC step is the whole input space at that rung: 2^78, 2^165,
  2^345, 2^717. Solver time 3, 4, 3 and 5 seconds against a 900-second
  per-rung bound. The vacuity preflight counts three assertion cells in
  the miter, so it is not passing empty.
- `make sim` in cft-sim: `SIM_RC=0`, twenty-one targets, zero failures.
  The four FMA benches are 39,032 + 39,032 + 20,507 + 12,707 = **111,278
  vectors bit-exact against cft_golden**, which is the suite this
  project quotes by that number.

**A defect this found.** `tb/Makefile`'s `simmc` target has carried a
literal backslash-n where a line continuation belonged, since the day
the board targets were appended to it. `make simmc` therefore ran
everything up to `seqbanksmc` and then died on `No rule to make target
'\n'` - so `board`, `boardkrnl`, `boardseq` and `boardfp256`, the three
benches that exist to run the open-core board's configuration as one
thing, had never run under that target at all. Fixed; `make -n simmc`
now lists them.

**Gates still running when this was written**, on a host carrying a
dozen other agents' simulations: `make MC=10 simmc` (its first thirteen
targets returned PASS with no failures, including the three `board*`
ones above), `make MC=2 simmc`, `krnlfused`/`krnlplain`/`cycles`, and
`make yosys-lint`. The same yosys-lint invocation passed on the
idea-1-only tree earlier the same day (exit 0, no latches, no errors),
and Verilator elaborates `cft_krnl` and `tb_normshare` clean - two
width warnings in `cft_lzcone` were found by exactly that gate and
fixed before this commit.

**Measured, out of context, tip only so far.** `xcu50-fsvh2104-2-e` at a
160 MHz ask, `MUL_PASSES=1` with the ladders off - the shipping
configuration - at 046adae:

| | tip |
|---|---|
| synthesis WNS / worst path | +0.410 / `s10_mag_reg[652]` -> `s11_valw_reg[448]`, 25 levels, **5.821 ns** |
| routed WNS / worst path | +0.120 / `s13_kept_r_reg[11]` -> `d_reg[148]`, 20 levels, **6.111 ns** |
| routed worst 25 by family | 13 round->pack, 8 `u_engine` `op_r`->`w_cnt`, 4 the cone (worst 6.068 ns) |
| routed LUT / FF / DSP / BRAM | 120,839 / 57,644 / 262 / 36 |

That confirms the study's central claim on a part it was not measured
on: **before placement the single worst path in the kernel is the
leading-zero cone.** It also shows what the routed picture is on this
part, which the study did not have: after routing the cone and the round
stage are within 0.04 ns, and the engine control path the study called
the second wall is third in the list.

**Not run here.** The branch's own implementations. The Kintex-7 325T
synthesis pair at 120 MHz `MUL_PASSES=10` with the ladders on, the U50
implementation pair, the idea-1-alone synthesis pair that would separate
the register cut from the trees, and the two 325T implementations were
queued one at a time behind the tip run above and had not returned; the
host was running six Vivado processes belonging to other agents for part
of the day. So this entry records a change that is PROVED bit-identical
and gated in simulation, and MEASURED only on the tip side. No frequency
claim is made for it, and none should be quoted until the pair exists -
this is the design whose out-of-context proxy has mispredicted the shell
by 0.88 ns once already.

## 2026-09-07 - two instructions the atlas port asked for: IMUL, and constants addressed through the immediate

docs/ATLAS.md's census of atlas-engine against this ISA found four
gaps. Two are now built, golden model first: **`IMUL`**, opcode 30,
the integer group's 32-bit low multiply, and **`kx`**, instruction bit
30, which moves the three operands' constant indices into the
immediate and takes the addressable constant bank from sixteen to 256.
docs/studies/OPT-D-contract.md ranked them 2 and 1 and set the four
measurements below; this entry is what they returned.

**The encodings, exactly.** `IMUL` is opcode 30 in the same 8-bit
space every other ALU opcode lives in: `d = ((a[31:0] * b[31:0]) mod
2^32)`, zero-extended to the format width, at every format. Thirty-two
bits and not `W`, which is the whole design decision - the caller is
`lowbias32`, a 32-bit hash whose value has to agree with a GPU
computing it on a `uint`, and a `W`-bit low product would be a 256x256
multiplier at binary256 for nobody. Quiet always, attribute-
independent, `c` unread; signedness does not enter, because the low 32
bits of a two's-complement product are the same bits either way.

`kx` is bit 30, which was reserved-must-be-zero. When it is set the
constant indices for the three operands come from `imm[7:0]`,
`imm[15:8]` and `imm[23:16]` instead of from the four-bit
`ra`/`rb`/`rc` fields; an operand whose `k` bit is clear still names a
register through its own field. The canonicity refusals are four more
applications of the rule docs/SEQUENCER.md already states rather than
a new one: under `kx`, the four-bit field of an operand that takes its
index from `imm` must be zero, the `imm` byte of an operand that names
a register must be zero, `imm[31:24]` must be zero, and `kx` set with
no operand naming a constant is refused because the bit then selects
nothing and the instruction has a second encoding. `kx` on a control
instruction is refused the way `ka` on a `DEPOSIT` always was.

**The version guard already existed, and only covers half.** A loader
that predates `kx` reads bit 30 as reserved and refuses the program,
so no program-header VERSION bump is needed and none was made. An old
BITSTREAM has no such rule - its operand mux would ignore bit 30 and
read the four-bit field - so what protects a device is a CAPS bit, and
CAPS publishes neither feature yet. Nothing in the library issues
`IMUL` or `kx` to a device on its own initiative; `cft_supports`
answers no for opcode 30 on every device; and `cft-enclose` says so
where it probes.

**Where it landed.** `python/cft_golden/softfloat.py` gains `imul()`,
and `seq.py` the `kx` decode, a `sources()` resolver, the refusals and
an opt-in `extended=True` arm on the fuzz generator - opt-in because
the default path must draw nothing new, or `tb/test_seq_core.py`'s
fixed-seed corpus would quietly stop being the 62 programs the RTL has
been held to. `host/src/softfloat.c` is one case in the integer
dispatch. `host/src/program.c`'s decoder, validator and executor learn
`kx` and resolve the three operand sources once per instruction rather
than once per lane. `rtl/cft_simpleops.sv` computes the product from
three 16x16 partial products - the fourth lands entirely at bit 32 and
above and is not computed - on the precomputed-result sideband the
rest of the integer group already uses, so the fp datapath is
untouched. `rtl/cft_seq.sv` grows `KREG` from 16 to `KMEM_D`, muxes
the index, and moves the bank read off the issue path.

**That last move is a saving.** The bank was read combinationally into
the issue registers once per BEAT, for a value that cannot change
during a run; it is now read once per INSTRUCTION, in its own
registered process, in the shadow of the fetch cycle that already
existed. No cycle was added and none was removed - the benches score
identical results. What a 256-entry bank does cost is memory: 256 x
256 bits with three read ports, on the order of 6 RAMB36 where 512 B
of LUTRAM stood. **No synthesis was run** - the brief forbade Vivado
on this host - so that is arithmetic on the array's shape, not a
measurement, and the timing effect is unmeasured. What was measured is
that the change costs the FRONT END nothing: `cft_seq` alone through
`read_verilog; hierarchy; proc; opt_clean; stat` takes 8.4 s and
82 MB against the pre-change file's 6.7 s and 83 MB, and `kmem` stays
a memory in both rather than being unrolled into registers.

### A bug the feature found on the way, older than the feature

`cft_seq`'s image parser peels one field per cycle and raises `rready`
only when the parse window is too empty to peel again. The condition
that decided "too empty" was eight bytes, at every element size. That
is right at fp64 and wider, where a constant is at least eight bytes,
and one beat too eager at fp32: the window still held four bytes, the
parser peeled instead of absorbing, and the beat the memory had
already handed over on that cycle's handshake fell on the floor. **Any
fp32 program whose CONSTANT REGION spans more than one beat starved
forever** - a hang, not a wrong answer, and the module's own header
had warned about exactly this failure mode for the instruction stream.

Nothing had ever reached it. Every directed case in
`tb/test_seq_core.py` and every program in the fuzz corpus carries four
constants or fewer, which is sixteen bytes at fp32 and never crosses a
32-byte beat; the enclose workload's chunked Horner carries sixteen,
which does cross a beat at binary256 - but there `esz` is 32 and the
old condition was correct. The first bench case to load a bank longer
than a beat at fp32 was written for indexed constants and hung on the
spot, at 40 constants and 160 bytes. The condition is now the size of
the NEXT field rather than a constant eight, and the regression that
finds it lives in `constants_and_rounding` at all four element sizes,
with banks of 40/20/12/6 - deliberately NOT a `kx` case, because the
bug is the parser's and predates the feature.

### The four measurements docs/studies/OPT-D-contract.md set

All four on the software backend, this host, 2026-09-07.

**1. The chain is unchanged - the gate.** `cft-enclose --engine
program` prints the same SHA-256 chain at every format that it printed
before, and the same one `bindings/wasm/demos_chains.json` recorded on
2026-09-04. Twenty chains were compared over two engines, four formats
and two degrees; none moved. `node bindings/wasm/verify_demos.mjs`
reports 28 checks and no failures over all eleven demo configurations,
each chain matching both the C tool and the recorded file. `make -C
host enclosetest` is **2,660 comparisons, 0 failures**, now including a
section that holds the single-program and chunked Horner shapes to
byte-identical records at fp256 degree 23 and fp32 degree 127.
Indexed constants reorder nothing and re-associate nothing, so a
changed chain would have been a bug and not a design question.

**2. The call count collapses.** `--degree 127`, 4,097 items, batch
512: **16 chunk programs and 144 library calls become one program and
9** - one call a batch, which is the floor. At the tool's default
degree 23 the whole three-kernel run at 17 items goes 95 -> 93 calls at
fp32 and 359 -> 357 at fp256; the series kernel's divisions dominate
that configuration and there is little chunking left to remove.

**3. The frames collapse, from the server's own log.** `cft-serve` on
loopback, fp64, degree 127, 32,769 points, batch 512, counted per
opcode from `--verbose`: the Horner kernel's program traffic falls
from **3,120 frames to 67**. The remote backend caches one program
image, so sixteen images cycling thrash that cache and each of the
1,040 calls costs `PROG_FREE`, `PROG_LOAD`, `PROG_RUN`; one image pays
that once and then 65 bare `PROG_RUN`s. Whole-connection frames go
167,381 -> 164,328, a difference of 3,053, which is 3,120 minus 67 and
nothing else: the 163,968 `RUN` frames of setup are identical either
way and dwarf the kernel at this point count. Wall clock over loopback
11.41 s -> 10.02 s, same chain.

**4. The arithmetic intensity crosses the line.** A program issues
`1 + 4 * steps` ALU instructions per lane against five element
transfers - three stream loads in, two deposits out - and
`cft-enclose` now prints both, from the program it actually built and
cross-checked against the instruction count that program carries:

| shape | steps | ALU instructions | per element moved |
|---|---|---|---|
| chunked | 8 | 33 | 6.6 |
| one program, degree 23 | 24 | 97 | 19.4 |
| one program, degree 127 | 128 | 513 | **102.6** |

docs/SEQUENCER.md's crossover is K ~ 30. The chunked kernel sat at a
fifth of it; a degree-127 polynomial as one program is **3.4x past
it**, and is the first table-driven kernel here to cross it at all.
Degree 23 does not cross it even as one program, which is worth saying
plainly: the feature raises the ceiling, it does not raise every
kernel through it. The tile's capacities are the next limit and they
are comfortable - 516 instructions of `IMEM_D`'s 1,024, 256 constants
of `KMEM_D`'s 256 - which is why the tool caps a program at 128
coefficients and chunks above that.

### The gates

Golden model, `python/tests`: **2,020 passed, 5 skipped** (2,011 and 5
before; the nine are the kx and IMUL properties, including one that
asserts the default fuzz corpus is byte-identical to the old one and
one that runs `lowbias32` as a program against Python's own integers).

The runner's `seq` stage - `host/tests/seq_check.py --trials 250
--formats fp32 fp64 fp128 fp256`, now alternating the old corpus with
an extended one that emits `IMUL` and `kx`: **731 programs run through
both implementations, 269 refused by both; 319 of them crossed
libcft's 64-lane block boundary; 500 programs drawn from the extended
corpus: 268 IMUL instructions, 780 indexed-constant instructions, 515
constant indices above 15; libcft and the golden model agree on every
program: deposits, counts, flags and status.** The stage now fails
loudly if the extended corpus stops producing either feature, because
a differential that covers nothing new still passes.

cocotb, Icarus, in `cft-sim`: `simpleops` 6/6 (a new `test_imul`
against the golden model at all four rungs over 6,225 operand pairs,
24,900 comparisons, with random junk in the bits above 31 that the
32-bit definition promises not to read); `seq_core` 10/10 (a new
`indexed_constants_and_imul` suite: constants 16..255 on each of the
three operand ports at fp32/fp64/fp256, the `kx` and plain forms
compared where both can encode the operand, a three-entry bank in a
256-entry memory, IMUL on stream operands at all four rungs, and
`lowbias32` as a program); `krnlseq` 1/1, `seqbanks` 1/1, `krnl` 2/2.

`make -C host test`: api-test all contract checks passed, with three
lines moved because 31 is now the first unassigned opcode. `make -C
host reducetest`: 12,696 reductions, 0 failures. The workloads:
COLLATZ, ORBITS, ZOOM and MERSENNE CHECK OK, unchanged chains
throughout.

The conformance round trip, which is where an assigned opcode is
easiest to get wrong: a freshly generated two-format set replays
**2,800 cases, all matching**, with 40 `imul` cases and 40
`reserved31` cases per format; and the same set with `imul` renamed
back to `reserved30` is REFUSED by name - "this set records an opcode
as reserved that the contract has since assigned". That refusal is why
`cft_op_name` had to learn the name today rather than when CAPS
publishes it.

**Lint.** `make yosys-lint` in the cft-sim image on the branch, re-run
by the integrator after the session was stopped: exit 0, the
pre-existing memory-replacement warnings in `cft_lanes.sv` only.

**Formal, not closed.** `formal/imul.sby`'s `value` task - three 16x16
partial products against one 32x32 multiply, truncated - ran
twenty-six minutes under bitwuzla without returning and was stopped;
the `check` task, the decode, the zero extension and the 32-bit rule
as a self-miter, was still waiting on the solver after sixteen
minutes in the agent's last attempt and after thirty in the
integrator's, on a box carrying other agents' simulations. Neither is
in the gate: the harness and the .sby stay in the tree with `sby -f
imul.sby check` and `value` to try again, and IMUL's value rests on
`tb/test_simpleops.py`'s `test_imul` - 6,225 operand pairs at four
rungs against the golden model - and on `host/tests/seq_check.py`'s
differential.

### What was not run, and why

- **No synthesis and no timing.** No Vivado on this host by the
  brief's rule, so the RAMB36 estimate for the widened bank is
  arithmetic and the registered bank read's effect on the critical
  path is unmeasured. The datapath and array studies own both.
- **No hardware.** No hw_emu and no card; the RTL claims here are
  simulation against the golden model, which is what every other RTL
  claim in this file rests on until a bitstream exists.
- **No CAPS bit, no VERSION step, and no rebuilt wasm module**, all
  three deliberately and all three the integrator's. The last one has
  a consequence worth naming: `bindings/node/cft_node.wasm` was built
  on 2026-09-04 and its embedded conformance replayer does not know
  the name `imul`, so the `node` and `wasm` verify stages refuse a
  freshly generated vector set with "unknown opcode name" until the
  module is rebuilt and its recorded SHA re-recorded. That is the same
  step 24, 26 and 28 each required when they were assigned.

## 2026-09-07 - the improvement round, integrated by hand: what merged, what was held, and the gates on the merged tree

Ten Opus agents were dispatched at once on disjoint targets. Four
returned their reports and were gated and merged as they landed (the
det library target, the WebSocket transport, the caps publication as
ABI 0.8, the fuzz hardening - each has its own entry above). The other
six sat waiting on hours-long runs and were stopped; their branches
were reconstructed from the worktrees and the logs, committed as the
agents left them, and integrated or held here.

**Merged from the worktrees.**

- *The program API in JavaScript* (its entry above): committed as
  left, merged, the module rebuilt. `test.mjs` 126 passed,
  `program_test.mjs` 17 passed, on the final module.
- *The multi-cycle rung's exactness* (its entry above): merged; its
  gate script became the base every other branch's proofs were ported
  onto.
- *The leading-zero cone cut, LATENCY 15 to 16* (its entry above):
  merged with the formal gate and the kernel's parameter block resolved
  by hand - the four `lzcone.sby` proofs in the merged gate's own
  signature, three `.LATENCY(16)` sites. Its own timing was never
  measured: the agent's queue waited on the tip runs and other agents'
  Vivado processes all day, and the integrator's attempt found a
  Vivado still running the tip's K325T implementation. The agent's leftover queue ran them after the stop, and the
  integrator read the reports: on the U50 at 160 MHz the routed slack
  went +0.120 to **+0.255** and the cone left the routed worst 25;
  on the -2 K325T at 120 MHz in the board configuration the tip
  misses by **-1.817** and the branch by **-0.078**, the wall now the
  engine's `beats_total -> rd_resv` chain - study C's second wall -
  so the board is a ~119 MHz part where it was a ~100 MHz one.
  docs/ARCHITECTURE.md carries the table.
- *IMUL and indexed constants* (its entry above, placeholders measured
  by the integrator): merged with four hand-resolved conflicts - the
  atlas document's step list, the sequencer document's capacities
  paragraph, the formal gate's proof list, the seq differential's
  corruption list (now the union: `wrap_trip` beside the five `kx`
  refusals). Then the integrator's half: **CAPS[4] publishes `kx` and
  CAPS[28] publishes `IMUL`**, decoded into `cft_caps.seq_features`
  bits 0 and 4 (`CFT_SEQ_FEAT_WIDE_CONST`, `CFT_ALU_EXT_IMUL`), the
  software backend reporting both and 256 addressable constants from
  the file that enforces them, and a clear bit meaning ABSENT: the
  loader refuses an image that uses either on a device that does not
  publish it, naming the instruction, and `cft_supports` answers no for
  opcode 30 there. No VERSION step - VERSION guards the register map and
  features are announced in CAPS. `SEQ_KIDX_W` is 8; `tb/test_krnl.py`
  parses the feature and extension literals and resolves `KREG`
  through `KMEM_D`. The published vectors changed with the opcode: the
  twenty opcode sets carry 12,000 lines (200 `imul` cases each) where
  they carried 11,800, 1,071,635 cases over 168 sets where the page
  said 1,067,635, 29 distinct opcodes where the sampler expected 28;
  the sampler's stride is 60, and every document that pinned the old
  numbers moved with them.

**Held on their branches, committed, not merged.**

- *Study A's idea 2, the round window folded into the normalise
  ladder* (`worktree-agent-a19215c1f69c52ee1`, de7c742). Bit-identical
  by the agent's model check (658,048 comparisons, 0 mismatches) and its
  formal miter (pass, negative control refuted); its cocotb gate was
  still running. Synthesis at 135 MHz on the U50 part, MUL_PASSES=1:

  | ladders | LUT before | LUT after | path before | path after |
  |---|---|---|---|---|
  | off | 123,214 | 116,464 | 5.821 ns | 5.965 ns |
  | on | 108,028 | 102,064 | 5.856 ns | 6.138 ns |

  Six thousand LUTs, more than the study estimated, at 0.14 to 0.28 ns
  more implied path on the same cone the LZC branch was built to
  shorten. That is a trade between the two things this project
  measures, and it is not the integrator's to make silently.
- *The runner's parallel vector generator*
  (`worktree-agent-a07f65f9943715fb5`, e18b290). Its own gate is
  identity: the 168 published sets rolled up by path and sha256 must
  not move. Against the reference `a0cd4bc4...` the rewritten generator
  produces `6449e6dc...` at `--jobs 4` and the same `6449e6dc...` at
  `--jobs 1` - consistent across job counts, but 20 files of the wide
  formats differ from the original's bytes, so the rewrite and not the
  scheduling changed them. Held until it reproduces the reference.
  Its measured baseline (gate budget, per stage) is in the session's
  scratchpad, and one of its findings - `simmc`'s literal backslash-n -
  was fixed on the tree the same day.
  **Correction, later the same day: it reproduces the reference, and
  always did.** The reference roll-up `a0cd4bc4...` was the runner's
  `vectors` stage's output, whose opcode sets draw the generator's
  default pools (19,600 lines a set); the integrator's identity runs
  used `make vectors`' pools (3000/4000/200, 11,800 lines a set). The
  twenty files that "differed" were the twenty opcode sets at two
  pool sizes. Regenerated with the ORIGINAL generator at the same
  pools, the reference is `6449e6dc...` - the rewrite's own roll-up,
  at one job and at four, byte for byte. On the merged tree at ABI
  0.8 the rewrite at four jobs and the original in series both give
  `edf57497...` over the 168 sets, in 3 min 5 s against 8 min 30 s.
  Merged the same afternoon; verify/README.md says what the knobs
  are and why the census leaves the cache off.

**Gates on the merged tree**, in the pinned images and on this host:

- `make sim` in cft-sim: 21 targets, 0 failures.
- `make MC=10 simmc` in cft-sim: sixteen of seventeen targets passed
  (the thirteen multi-cycle benches and the sequencer-driven and fp256
  board benches); the seventeenth, `boardkrnl` - the engine-driven
  kernel at ten passes with both ladders on - **does not finish under
  Icarus** on this tree: its simulated time advances at about 2 ns a
  second while the simulator burns a core, 160x slower than the same
  bench without the ladders, and it was stopped after two and a half
  hours at 17 microseconds. Isolated the same afternoon: the LZC
  agent's own tree crawls the same way (so its entry's claim that the
  board targets passed under `simmc` is not one its logs support -
  the target never reached a verdict there either), the tree before
  the ISA merge crawls, Verilator's lint finds no combinational loop
  on either tree, and **under Verilator the merged tree's board kernel
  passes both tests in 7.5 s** of wall clock (31,556 ns simulated).
  So the RTL is right in the board configuration and Icarus's
  evaluation of the new cone beside the ladders at ten passes is the
  pathology; `boardkrnl` now selects Verilator, and the cone's coding
  for Icarus is recorded as the defect to fix, with the board
  configuration under Icarus as its gate.
  **Correction, the same afternoon.** The control run - the tree from
  before the cone change, same bench, same simulator - crawls at the
  same rate: 2,292 ns of simulated time in the first fourteen minutes
  after compilation, four operations bit-exact, about 2.5 ns a second
  against 2.2 on the merged tree. So the cone change did not cause
  this; the engine-driven board kernel under Icarus is simply a
  three-and-a-half-hour bench in this configuration, which is how the
  morning's `board` run passed it, and the LZC agent's board targets
  were most likely still running rather than wrong. There is no cone
  defect to fix; the Verilator default stands as the simulator cost
  it is, and the claim two paragraphs up that Icarus's evaluation of
  the new cone is the pathology is withdrawn.
  **Second correction, the same evening.** Neither number above was
  what it claimed. The "7.5 s under Verilator" was the DEFAULT
  kernel: tb/cocotb.mk added `KRNL_PARAMS` to the compile line under
  Icarus only, so every parameterized target ever run with
  `SIM=verilator` - the multi-cycle suite, `krnlfused`, `krnlplain`,
  the three board targets - simulated the RTL default while its name
  said otherwise, and the Verilator `boardkrnl` result the paragraph
  above rests on simulated 31,376 ns, which is the `krnl` target's
  figure exactly. The tell was in the two logs side by side: the
  Icarus run spent 1,152 ns of simulated time on an fp256 fma the
  Verilator run did in 372, which is one iterated multiplier against
  none. Fixed: cocotb.mk now rewrites `-P<top>.<PARAM>=<v>` to
  Verilator's `-G<PARAM>=<v>` for the module that is TOPLEVEL and
  refuses a parameter aimed at any other module (Verilator itself
  refuses a name the design lacks: "Parameters from the command line
  were not found in the design"). The first build with the
  parameters applied raised five width warnings the default
  configuration never elaborates - the pass counter's saturation
  compare in cft_mulpass against the int NP, and the three 1-bit
  ladder switches in cft_krnl receiving a 32-bit `-G` literal - fixed
  as a cast to the counter's own width (exact, since PXW is
  $clog2(NP + 1)) and a lint_off pair scoped to the three
  declarations, the argument beside each. Then the board kernel under
  Verilator, parameters on: **both tests pass, 44,920 ns simulated in
  15.8 s** after an eleven-minute compile, the fp256 fma at the same
  2,732 ns the Icarus run reached it at, and the same simulated length
  as `krnlmc10` - the multi-cycle count, which the ladders do not
  change. And the "3.5 hours" was an extrapolation from the rate
  over the bench's first operations; the Icarus control held that
  2.5 ns a second through the fifty-seven 32-element operations and
  then, inside the 1,104-element fp32 stream, advanced 80 ns in forty
  minutes. Stopped at 3 h 56 min of simulation, 32,280 ns, 57 of 71
  operations bit-exact: the bench has no finite Icarus duration worth
  quoting, and the docs now say so. The Icarus targets that exercise
  the edited counter on this tree, in cft-sim: `mulpass` 1/1,
  `mulcycle` MC=10 4/4, `mulcycle2` 4/4, `krnlmc` MC=10 2/2 (44,920
  ns in 28 s), each under a minute with the box quiet - which is also
  the honest same-simulator comparison: the default and MC=10 kernels
  run at about 1,600 ns of simulated time a second under Icarus here,
  the board configuration at 2.5 and then 0.03. Lint under Verilator,
  default and board configurations: clean. Formal, on this tree: `FORMAL GATE: PASS (31 of 31, negative control refuted)` in 4.5 min beside the two simulations.
  **The ingredient, the same evening.** Three ten-minute Icarus
  probes of the full-kernel bench on this tree, side by side with the
  box otherwise quiet: both ladders on at ONE pass, 1.7 ns of
  simulated time a second (708 ns in seven minutes); the normalise
  ladder alone at ten passes, about 4 ns a second; the align ladder
  alone at ten passes, about 15 ns a second; against 1,636 ns a
  second for ten passes with neither ladder (`krnlmc` above). So the
  pass budget is not the ingredient - the shared ladders are, each on
  its own, the normaliser worse than the aligner, and together worse
  than either. cft_normseg's own benches run at about 1,000 ns a
  second under Icarus, so it is the ladder IN THE KERNEL that costs:
  the ladder is written per bit - a continuous assign for each of its
  720 bits at every level, with elaboration-constant masks, which is
  the form Vivado folds to 5,269 LUT - and Icarus schedules every one
  of those assigns as an event each time the ladder's 720-bit input
  settles, which in the kernel is once per slot whose source changes
  in a cycle rather than once a cycle as the unit bench drives it.
  Why the rate then falls another hundredfold inside the
  1,104-element stream is not established; the probes did not reach
  it. Recorded for the study that rewrites the ladder level-wise (a
  vector mask and shift per level, the same bits, a handful of
  operations where there is now one assign per bit) or that accepts
  Verilator as the fused configurations' simulator, which `boardkrnl`
  already does. Not before card day.
- `formal/run.sh` in cft-formal: `FORMAL GATE: PASS (31 of 31, negative
  control refuted)`, 420 s of solver time - after a first run had to be
  stopped at two and a half hours, stuck on `imul.sby`'s `check`
  task, which the integrator had left in the gate while writing that
  it was parked; it is parked now, both tasks.
- `make yosys-lint`: exit 0, the pre-existing memory-replacement warnings only.
- `make test`: `api-test: all contract checks passed`, `reduce-parts: every
  canonical partition reproduces the whole`, `168 sets, 1071635
  cases, all matching`, `C and Python reached the same library and
  got the same bits` - on the regenerated set.
- `make remotetest`: `remote_check: every check passed` - 2,256 device-test checks
  over loopback with 0 failed (after the feature-word mask in
  `device_test.c` was widened to the eight bits `seq_features` now
  carries; the first run failed both sides with 0x11), the replay
  identical local and remote over 184,592 cases, the collatz chain
  the same both ways, the bench round trips on both div/sqrt routes.
- `make wstest`: 46 checks, 0 failures, on the rebuilt module.
- `node bindings/wasm/verify.mjs`: `1,071,635 cases over 168 sets, library matches the vectors
  exactly` and `831,635 cases over 148 sets driven through the
  wrappers themselves, encodings, sequences, scales and flags exact`.
- `node bindings/wasm/verify_demos.mjs`: `the browser's compute core produced the C tools' chains, over the
  module the conformance page embeds` - after the chains were
  re-recorded against the rebuilt module, every one of the thirteen
  runs byte-identical to the previous record.
- the five workload checks: enclose 2,664 comparisons, collatz 18,110,
  mersenne 391, zoom 11,223, orbits 26 checks, all with 0 failures; the
  seq differential agrees on every program.

**Not run.** Anything on a device; the held branches' own gates beyond
what their logs already recorded.

## 2026-09-07 - the card-day check: what today's library says to an image built before today

The staged images predate everything the improvement round put on
main, so the question was whether tomorrow's runbook still holds on
them. Three absences are normal and now written into docs/CARDDAY.md:
`CAPS[27:16]` reads zero, so the library enforces no capacity and the
tile alone enforces its 64 deposit slots a lane - the two workloads
that deposit an iteration must be sized by hand on these images
(`cft-zoom --steps-per-call 32`, `cft-orbits --periods 15`); `CAPS[4]`
and `CAPS[28]` read zero, so the loader refuses any program using
indexed constants or `IMUL` by name and `cft_supports` answers no for
opcode 30; and the published opcode sets now carry 200 `imul` cases
each.

**The third one was a defect, found by reading rather than running.**
`cft_conformance` decided per set whether a device carries a format
(by asking about FMA) and then dispatched every opcode in the set; a
`cft_run` refusal failed the set. Before today no assigned opcode could
be absent from a device that had its group, so that was never
reachable. On a card-day image every one of the twenty opcode sets
would have failed on its first `imul` case. The replay now skips an
opcode the device does not publish by name, once per set, and does not
count the skipped cases as checked - `imul skipped, not on this device`
twenty times, and a count 4,000 short of what `make vectors` wrote, is
what tomorrow's `cft-selftest` should print. The skip is for ASSIGNED
opcodes a device does not publish; the first cut of it asked
`cft_supports` alone, which answers no for the unassigned `reserved`
opcodes by design, and so silently dropped the 600 reserved cases a
set carries - the cases that check every device's canonical-qNaN
answer - and the replay's own count caught it at 1,055,635 instead
of 1,071,635. Written against the code; not exercised on a device,
because no image lacking the opcode can be reached from this host
before tomorrow. On the software backend, which publishes the
opcode, nothing changes: `168 sets, 1071635 cases, all matching` and `1071635 cases checked`, no skip line, `api-test: all contract checks passed`, `C and Python reached the same library and got the same bits`.

**Also today.** The eight merged agents' worktrees are removed (their
branches stay); the two held branches keep theirs. A leftover build
queue from the area agent and a loopback server from the morning's
device-test were stopped by PID - the first attempt used `taskkill
/PID` from Git Bash, which rewrites `/PID` into a path and fails
silently unless the output is read; `MSYS_NO_PATHCONV=1` is the form
that works. The round-window fold does not rebase mechanically onto
the cone stage (two conflicting hunks in the pipe's S11 region and the
fold's amount select would have to be re-derived against the
registered cone), so it stays held for a proper rebase rather than a
cherry-pick. The parallel vector generator's difference is being
characterised against a freshly regenerated pre-rewrite reference: the original generator
at the same pool sizes reproduces the rewrite byte for byte, at one job
and at four, on the model before the ISA merge (`6449e6dc...`) and on
the merged tree (`edf57497...`, 3 min 5 s at four jobs against 8 min
30 s serial) - the twenty files the morning's check called different
were the runner's larger opcode pools against `make vectors`', and the
branch is merged; the round's entry carries the correction.

## 2026-09-07 - the card-day pair from ed752dd: single +0.316, quad +0.067, both at 135 MHz

Built on amd-arc-box the evening before card day by one detached chain
(`~/cardday_0907.sh`: pin origin to GitHub, worktree at the exact sha,
refuse a tree without the round's hardware by name, single and quad in
parallel, 130 MHz fallback per half, verify, stage, hash), the 9f73107
recipe - retiming + phys_opt, default directives:

    cd135single  ed752dd, one tile,   135 MHz   17:06 -> 19:22 (136 min)
                 routed WNS +0.055  kernel WNS +0.316  0 failing endpoints
                 worst: u_fifo_a BRAM -> g_bank128 lane 1 s0_byp_d, 16 levels (seedop bypass)
                 35,783,663 bytes  sha256 3870fc43...c981e0  verify-image 8/8
    cd135quad    ed752dd, four tiles, 135 MHz   17:08 -> 21:36 (267 min)
                 routed WNS +0.031  TNS 0  0 failing of 984,222  WHS +0.009
                 kernel WNS +0.067: g_bank256 rd_dly -> g_bank64 lane 0 s13_tiny, cross-bank
                 51,422,147 bytes  sha256 496f8ac0...828307  verify-image 8/8

Staged as ~/cardday-0907/cft_hw_{single,quad}.xclbin with manifests,
SHA256SUMS and a README; each copy re-hashed against its manifest,
byte-identical; `sha256sum -c` clean; `verify/run.sh --only images` over
both: PASS, run 20260907-213830-ed752dd. Against the 9f73107 pair the
round's hardware (IMUL and the indexed constants, the 72-byte caps
block, the cone stage) cost 0.30 ns on the single and 0.08 on the quad,
and both still close at 135; 130 was never needed. The quad's worst path
moved: 9f73107's was LZC-plus-coarse-normalise, which the cone stage
removed, and the new worst is a cross-bank register-to-register path
the placer chose. docs/CARDDAY.md names this pair as the one for the
day and the 9f73107 pair as the fallback.

**The card host, prepared the same evening.** amd-arc-box, main
6f100ff: `make libcft-test` PASS in 10 min - 1,071,635 cases, C and
Python the same bits - against sets the box generated itself, which are
byte-identical to the desktop's, all 168, once the desktop's CRLF is
stripped (the generator writes text mode on Windows). The box carries
no mpmath and its python cannot build a venv (no ensurepip), so the
desktop's mpmath 1.3.0 was copied to ~/pylib; device-test and cft-bench
are built there against XRT 2.19's userspace. The XRT kernel module is
still unbuilt on the box's 7.0 kernel; GA 6.8 is installed for the card
session, and the driver builds after that reboot.

**Firmware.** The box is a Gigabyte GA-X99-UD4 at F24c. Its menu has no
"Above 4G Decoding" because Gigabyte compiled the AMI question out of
the Setup form (the string survives in the string table, unreferenced),
but the Intel platform form's "PCI 64-Bit Resource Allocation" exists,
suppressed unconditionally, default Enabled, at IntelSetup offset 0x56 -
and efivarfs on that box is world-readable, so the live byte was read
over ssh: 0x01. MMIOHBase and MMIO High Size sit at their defaults (56 TB,
256 GB). Nothing to flip for the U50; the extraction kit (UEFIExtract,
IFRExtractor-RS, a UEFI shell with setup_var 0.3.1, findings and a
procedure) is kept on the desktop in case the answer ever changes.

**Emulation, the same evening**, on the desktop's WSL against hw_emu
images of ed752dd (one tile 33,150,127 bytes in 4 min, four tiles
57,295,639 in 6 min, 135 MHz), host tools against the era XRT:

- The four-tile image answers through the real XRT stack: `device:
  backend xrt, 4 tiles, contract 0x00000600, formats fp32 fp64 fp128
  fp256`, and `device reports max_deposits 64, max_insns 1024, max_consts
  256, seq_features 0x11` - the caps block of ABI 0.8 read from a device
  for the first time, with the +1-deposit and +1-instruction programs
  refused by name. The max_consts probe reports NOT TESTED because it
  still writes the four-bit index form; a kx probe is a small follow-up.
- `-q -n 8` on the quad: rc=0 in 5 min with none of device-test's own
  output and two protobuf parse errors at the first host-to-device copy.
  Not a pass; re-run queued and recorded below when it lands.
- `-r` on the quad: stopped after 133 min. About 95 single-element fp32
  reductions, every one completing with err=000, and the first 16-case
  block still unfinished - each case is several one-element invocations
  at about 1.4 min under xsim, so the full gate is days. The reductions
  are proven on the card instead (runbook step 5). The run's simulator
  log was lost to a defect in hw/run-device-test.sh, which kept one
  generation of .run under the repo root and the artifact directory but
  not under host/, where XRT actually writes it next to the binary;
  fixed in this commit.
- `-s -n 24` on the quad and `-q` on the single: running at the time of
  writing; their verdicts follow in a later entry.

## 2026-09-08 - emulation overnight: the four-tile image runs every format's programs bit-exact; the quick gates are no longer an evening's work

The chain from the previous entry finished at 05:44, stopped by hand
in its last gate. Verdicts, on the desktop's WSL against hw_emu images
of ed752dd, host tools against the era XRT:

    quad   -s -n 24   PASS   98 checks, 0 failed, in 333 min - fp32 38, fp64 20,
                             fp128 20, fp256 20; "the device and the software
                             backend agree on every case, bits and flags"
    single -q -n 8    PARTIAL, stopped at 221 min inside fp32 with every check
                             so far passed: fma 22, sequencer programs 42, composed
                             div/sqrt 50 checks, 0 failed; fp64/fp128/fp256 not reached
    quad   -q -n 8    NOT A VERDICT: the first run exited 0 in 5 min with none of
                             device-test's output (previous entry); not re-run, because
                             the single's run showed what a quick gate costs under xsim
    quad   -r         stopped at 133 min, no block verdict (previous entry)

So the sequencer's row moves: programs in all four formats have now run
through the real XRT stack on a four-tile image and matched the software
backend bit for bit and flag for flag - the fp32-only qualification of
2026-09-02 is lifted. Elementwise, seeds and the composed div/sqrt are
proven through the stack at fp32 on one tile. The wider formats'
elementwise paths and the reductions are proven in cocotb and await the
card, which is what the card is for.

The lesson is about the gate, not the design. device-test's quick mode
was thirty-three invocations on 2026-09-01; it is now one opcode per
format plus the programs, the composed div/sqrt, six boundary sizes, the
partition-invariance cases and nine reductions, hundreds of kernel
invocations, and under xsim each costs one to three minutes regardless of
its element count (the handshake and the DMA dominate, not the
arithmetic). A quick gate is therefore hours per format and the
reductions gate is days. docs/CARDDAY.md's two pre-day emulation items
are annotated accordingly, docs/VERIFICATION.md carries the measured
costs, and device-test wants an emulation budget - a mode that runs one
format's worth of each family and stops - before it is used as an
evening check again. Recorded as a follow-up, not done here.

## 2026-09-08 - revision 2 in the model and the tile: 32 registers, IMEM_D 4096, a per-run constant bank - and the register file doubles for nothing

The hardware-contract half of docs/SEQUENCER.md's "Revision 2"
section, built on 44e2a07: the golden model, rtl/cft_seq.sv,
rtl/cft_csr.sv, rtl/cft_krnl.sv, hw/kernel.xml and the benches. The
host library, the tools and the JavaScript binding are other agents'
work from the same spec and have their own entries.

### The OOC measurement R1 asked for

The contract said to measure what doubling the register file costs, to
record it even if the answer was bad, and not to shrink NBEATS to make
it fit. **It costs nothing.** Two out-of-context synthesis runs of
`cft_krnl` on trees identical apart from revision 2 - Vivado 2026.1,
xcu50-fsvh2104-2-e, 135 MHz, `hw/synth_krnl_ooc.tcl` with default
generics, the Windows desktop:

| | revision 1 (16 regs, IMEM_D 1024) | revision 2 (32 regs, IMEM_D 4096) | delta |
|---|---|---|---|
| CLB LUTs, tile | 120,173 | 119,915 | **-258 (-0.2%)** |
| CLB registers, tile | 60,543 | 60,750 | +207 (+0.3%) |
| Block RAM tiles | 50 | 48 | -2 |
| URAM | 0 | 1 (of 640) | +1 |
| DSPs | 307 | 307 | 0 |
| WNS at 135 MHz | +1.196 ns | **+1.196 ns** | **0.000** |
| synthesis wall time | 9 min 47 | 11 min 13 | |

`cft_seq` alone, from the hierarchical report: 24,702 -> **24,437**
LUT, 4,899 -> **5,042** FF, RAMB36 22 -> 20, RAMB18 24 -> 24, URAM
0 -> 1. Nothing else in the tile moved: `cft_lanes` is identical to
the LUT (88,184 both ways), `cft_engine_stream` differs by one, and
`cft_csr` grew 818 -> 824 LUT and 629 -> 693 FF, which is BANK_PTR.

**So the answer to the contract's question is yes, at 135 MHz on the
U50, with nothing shrunk.** Two facts explain a doubling that costs
nothing. The register file was already block RAM and stayed in the
same primitives - eight banks mirrored twice, and 512 x 32 bits fits
the RAMB18 that 256 x 32 did - so the depth doubled inside memories
that were already there. And the instruction memory, four times larger
at 4,096 x 64 bits, stopped fitting block RAM economically and Vivado
inferred **one UltraRAM** for it, a resource this tile was using none
of, which is why the BRAM tile count went DOWN by two while the
capacity went up fourfold.

Timing did not move because `cft_seq` is not on the critical path in
either tree. The worst path is the same one in both, to the picosecond
and to the pin:

    Slack (MET) : 1.196ns
      Source:      u_engine/u_fifo_a/mem_reg_0/CLKARDCLK
      Destination: u_lanes/g_lane32[0].u_fma/s0_byp_d_reg[24]/D

Two cautions on those numbers. **Out-of-context synthesis is not shell
timing** - this project paid to learn that once and docs/ROADMAP.md
carries the accounting - so +1.196 ns is a comparison between two
trees, not a prediction about a linked build. And this is **Vivado
2026.1**, where the tile's own recorded history (139,404 LUT at +0.307
ns) was measured under 2022.2: absolute numbers are not comparable
across that gap, which is exactly why the revision-1 baseline above
was re-synthesised today rather than quoted from the file.

The K325T pair (hw/mc_sweep.sh's configuration, MUL_PASSES=10 and both
ladders) was NOT run. It was second priority in the round and the U50
answer was decisive; the entry says so rather than leaving a reader to
assume it passed.

One implementation was run, of the revision-2 tree only - the round
allowed one and this is the configuration that matters.
`hw/impl_krnl_ooc.tcl`, same part and clock, **55 min 29 s**, exit 0:

    QOR_ROUTED_WNS_NS: 0.027          (135 MHz, period 7.407 ns)
    routed LUT 117,308   FF 60,768   BRAM tiles 48   URAM 1   DSP 307
    worst routed path, 16 levels, 7.314 ns datapath:
      u_engine/u_fifo_a/mem_reg_1/CLKARDCLK ->
      u_lanes/g_bank128.g_lane128[1].u_fma/s0_byp_d_reg[29]/D
    cft_seq routed: 24,014 LUT, 5,042 FF, RAMB36 20, RAMB18 24, URAM 1

It closes, and **it closes on a path that is not the sequencer's**:
the worst routed path is the same streaming-engine FIFO into the same
FMA input register that was worst at synthesis in BOTH trees.
Revision 2 is not what makes it tight.

Two things this run does NOT say, stated because the temptation is to
read them into it. There is **no revision-1 routed comparison** - one
implementation was the budget, so the before/after delta above is a
synthesis delta and nothing here upgrades it. And +0.027 ns of routed
OOC slack is not headroom: read the path delay, 7.380 ns against a
7.407 ns period, and remember that the tool works exactly as hard as
the constraint asks (docs/BRINGUP.md). What the run establishes is
that the revision-2 tile places and routes at 135 MHz on the U50 at
all, which is the question the contract asked and the one a synthesis
number alone could not answer.

### The gates

Everything below ran from this worktree. The container gates are
`MSYS2_ARG_CONV_EXCL='*' docker run --rm -v <worktree>:/work -w
/work/tb cft-sim make ...`.

    make -C python pytest (the golden model)      2026 passed, 5 skipped   10 min 0 s
      - 2,020 before; the six new are R1's bit table, r16..r31 running,
        the BANK_EXT image's length and its two-bank equivalence, the
        bank refusals, and the digest over image-plus-bank

    docker cft-sim: make -k -j4 sim                21 targets, 64 tests    18 min 1 s
                                                   PASS=64 FAIL=0 SKIP=0
      - the whole shipping suite, not just the sequencer's targets,
        because rtl/cft_krnl.sv and rtl/cft_csr.sv are shared: fp32
        fp64 fp128 fp256 mulfrac mulshare simpleops normseg normshare
        seedop reduceacc reduce krnl quarter faults seq_core krnlseq
        seqbanks mulpass mulcycle mulcycle2
      - seq_core is 12/12 where it was 10/10: `wide_registers` and
        `constant_bank_per_run` are new
      - the box was also carrying the Vivado implementation below, so
        18 min is a loaded number - and well under the 55 min
        docs/VERIFICATION.md records for four jobs beside a Vivado,
        which was a different load

    docker cft-sim: make MC=10 <seq targets>       3 targets, 14 tests    7 min 24 s
                                                   PASS=14 FAIL=0 SKIP=0
      - seq_coremc, krnlseqmc, seqbanksmc: the sequencer's share of
        `make simmc`, the multi-cycle tile's own census. The rest of
        simmc and the four board targets were not run in this round;
        they exercise the multiplier and the ladders, which revision 2
        does not touch.

    docker cft-sim: make yosys-lint                clean, exit 0           1 min
      - only the pre-existing "Replacing memory with list of
        registers" notes and the one translate_off warning

    docker cft-sim: verilator 5.020 --lint-only    clean, exit 0, BOTH     2 min
      cft_krnl, default and board configurations   configurations
      - warnings fatal, and no -Wno-* at all: tb/cocotb.mk's Verilator
        branch retired the blanket width suppressions and a width
        warning is a regression. The board configuration is
        -GFUSE_NORM=1 -GFUSE_ALIGN=1 -GMUL_PASSES=10, translated from
        the Icarus -P spelling the way cocotb.mk does it.
      - separately, -Wall filtered to WIDTH reports NOTHING in either
        configuration. No lint_off was added anywhere.

The formal gate was not run: it does not cover `cft_seq`, and revision
2 changes nothing it proves. `make simmc`'s multiplier and board
targets were not run, for the same kind of reason. No emulation and no
device run: the card-day images predate all of this and are
unaffected, and this round produced no bitstream.

### What the benches found

Three things, none of them in the feature under test, which is the
usual shape:

- **A transcribed pad width.** `rtl/cft_seq.sv` twice wrote
  `if ({21'b0, pc} >= h_ninsns)` - twenty-one zeros hand-counted to
  bring an 11-bit program counter up to the 32 bits it is compared
  against. At `PCW` 12 the counter is thirteen bits and the comparison
  became thirty-four wide. **The Verilator lint caught it, not a
  bench**, and the fix is `32'(pc)`, derived from the width on the
  other side of the comparison rather than counted out by hand.
- **A cycle budget that carried a cost implicitly.** Doubling the
  register file doubled the per-block wipe, 256 cycles to 512, and
  `tb/test_seq_core.py`'s budget had that cost buried inside a literal
  `400`. The `geometry` suite timed out at fp32 n=300 - three blocks,
  5,288 cycles allowed - which is a bound being wrong, not a design
  being slow. The budget now adds `RF_D` by name.
- **Two negative controls that had stopped failing.** Both
  `python/tests/test_seq.py`'s P3 fuzz and `tb/test_seq_core.py`'s
  `unchecked()` build a `Program` through `__new__` to bypass
  `validate()`, and `run()` reads two fields revision 2 added. The
  bench one raised; the fuzz one silently reported **zero
  divergences** - a control that passes by never testing anything,
  which is precisely the failure the project's third rule names. Both
  now set the fields `__init__` would have.

Two things were checked rather than assumed. The fuzz generator's
`wide_regs` arm follows `extended`'s precedent - off by default,
drawing the same values from `rng` - and 400 corpora generated from
the pre-change `seq.py` and this one were compared pairwise: 400
identical, 0 differing, so no existing bench's corpus was reshuffled.
And the two OOC trees were diffed before the numbers above were
believed, because two synthesis runs of the same tree would have shown
exactly the same "no cost".

### One place the contract was ambiguous, and what was chosen

R1 says "a control instruction reads at most `ra` (`DEPOSIT`,
`SETACT`), so on those two only `imm[25]` may be set and on the other
four none." Read literally that binds `REPEAT`, whose `imm` is its
whole trip count - and it would newly refuse `REPEAT 0xffffffff`,
which is the program docs/SEQUENCER.md's own worst-case-instruction
rule is written about, is legal today, and runs identically on every
existing bitstream.

**Chosen:** the register-high-bit rule binds instructions that name a
register. `REPEAT` names none, so `imm[27:24]` there are trip-count
bits like any other; `HALT`, `ENDREP` and `ACTALL` may set no part of
`imm` at all, which is stricter than "none of the four" and was
already true; `DEPOSIT` and `SETACT` may set `imm[25]` and nothing
else in the word. That keeps R1's own closing sentence - "Nothing else
in the encoding moves" - true, and keeps the model from refusing
programs that are correct on the tile in front of it. It is written
down as `IMM_ALLOWED` in `python/cft_golden/seq.py` with the reasoning
beside it, and it is why `validate()` now checks control instructions
against the raw encoding (`decode_raw`) rather than against
`decode()`'s merged five-bit view.
