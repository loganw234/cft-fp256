# Novel results

Things this project does, or measured, for which no prior description
was found.

**The standard of evidence, stated first, because it limits every
claim below.** "We could not find it published" is not "it is
unpublished." Each entry therefore records what was searched, so that
a reader who knows the prior art can dismiss an entry cheaply rather
than having to re-derive why we thought it was new. Several searches
were bounded by paywalls, and those are named. If you know a
reference for any of these, the useful contribution is the citation,
not the correction.

Entries are split three ways, because they are worth different
amounts: results the design **uses**, results that are **negative**
(which are the most likely to be genuinely unpublished, since nobody
writes up what did not work), and **observations** we have not
exploited.

---

## Used

### 1. The reduction tree and the accumulator are the same object, by construction

The contract's reduction is an index-fixed binary tree. The hardware is
a streaming binary-counter accumulator: one add per element, a slot per
level, carry when a level is occupied. These are normally different
shapes, and the usual consequence is that the hardware approximates the
specification or the specification is written to whatever the hardware
happens to do.

Here they are the *same tree*, and the split rule is what makes them
so. A node divides at the **largest power of two strictly below the
range length**, not the floor midpoint:

    T(0,5) = add(T(0,4), x4)

That is exactly what a binary-counter accumulator produces: the
perfect subtree fills and carries, and the remainder sits beside it.
The midpoint split - the tidier balanced tree, and the first version
of this - is *not* streamable, and agrees with the pow2 split only
when n is a power of two.

Depth is `ceil(log2 n)` either way, so the accuracy argument for
pairwise summation is unaffected by the choice. The choice buys the
equivalence, and nothing else.

**What is not new:** pairwise summation and its error bound
(Higham); binary-counter / "cascaded accumulator" structures, which
are folklore in streaming-sum hardware.

**What we could not find:** the equivalence used as a *design rule* -
choosing the split so that the specification and the streaming
implementation are the same object rather than two things to be
reconciled. Reduction-tree literature discusses shape for accuracy or
for parallel depth; determinism-contract literature discusses fixing
an order. Deriving the fixed order *from* the streamable machine
appears not to be written down.

**Evidence in this repository:** `python/cft_golden/reduce.py`
(`split`, `stream_reduce`), `rtl/cft_reduce_acc.sv`. Verified: over
4,000 random fp32 inputs per size, the midpoint tree and the shipped
tree agree on **100% of cases at n = 2, 4, 8, 16, 64 and differ on
30-65% at every other size** - so the two really are different trees,
and the equivalence is load-bearing rather than incidental.

**How to falsify the novelty:** find a reduction-tree or
deterministic-summation reference that picks its split rule to match a
streaming accumulator.

### 2. Deferring the carries is what makes a pipelined adder usable for a reduction

A binary-counter accumulator carries when a level is occupied: level
`j+1` needs level `j`'s result. Resolve that eagerly and every carry
costs the adder's full latency, because the next carry cannot start
until the previous one retires. With a 15-stage adder that is
`ADD_LATENCY` per *level*, and it serialises the whole reduction.

Deferring the carries - letting levels be in flight together and
folding what remains at the end, lowest level first - costs the same
number of adds (`n-1`) and reaches roughly one cycle per element.

**Measured here: ~15.5 cycles/element eager against ~1.0 deferred.**
One cycle per element is what the engine's beat rate can actually
feed, so the deferral is not an optimisation - it is the difference
between the reduction being pipelined at all and not.

**What we could not find:** this stated as the design constraint that
makes a deeply-pipelined adder viable for streaming reduction. The
tension is obvious once written down, which is a reason to suspect it
*is* written down somewhere; we did not find it.

**Evidence:** `rtl/cft_reduce_acc.sv` and its header; `tb/test_reduce_acc.py`.

### 3. Backpressure as a determinism test rather than a robustness test

Bus-level fuzzing normally asks "does it still work." For a design
whose product *is* bit-reproducibility, it can be made to ask
something sharper.

Results are scored against a golden model that has **no notion of a
cycle**. So a run that survives a hostile schedule *and still matches
bit-for-bit* is not merely a passing test - it is a statement that the
schedule did not reach the answer. Timing is the most plausible thing
that could quietly perturb a floating-point result, and this converts
"we believe it cannot" into a property that fails visibly when false.

Concretely: the same operation matrix runs at stall duties of 0.15,
0.45 and 0.75 on every channel of every AXI master, seeded per
channel so failures reproduce, and every result must be identical to
the unstalled run and to the model.

**What is not new:** constrained-random bus stimulus with backpressure
is standard verification practice.

**What we could not find:** the framing that makes it a *determinism*
proof rather than a liveness or robustness check - i.e. relying on the
reference model's cycle-independence so that a bit-exact match under
adversarial timing is evidence about observability, not just
correctness.

**Evidence:** `tb/busfx.py`, and the backpressure section of
`tb/test_krnl.py`.

### 4. The DSP count is a structural checksum on the multiplier mapping

The per-lane DSP ladder is fully determined by the significand widths
and the DSP48E2 cascade rule `N = ceil((P-10)/17)`:

    8 x fp32   8 x 1 x 2   =  16
    4 x fp64   4 x 3 x 3   =  36
    2 x fp128  2 x 5 x 7   =  70
    1 x fp256  1 x 10 x 14 = 140
                            ----
                             262

The routed design reports **exactly 262**. Four rungs, four exact
matches, no slack anywhere in the arithmetic.

That makes the DSP count a cheap falsifiable check on something no
other report states directly: whether Vivado is still accumulating
partial products *inside* the DSP column on the `PCIN` cascade path
rather than spilling them into fabric adders. A change that pushes one
multiply into LUTs moves the count off 262 and is visible in one line
of any utilisation report.

**What is not new:** the cascade rule is UG579; using resource counts
as a sanity check is ordinary practice.

**What we could not find:** the specific observation that an exact
match against a derived ladder certifies the cascade mapping, used as
a standing regression check.

**Evidence:** `docs/ROADMAP.md` open-core sizing table; any
`*_util.rpt` in a build directory.

### 5. Contract-level exactness used to remove hardware

`CFT_DOT` is advertised in CAPS and is **not separate hardware**. The
contract makes `dot(a,b) == sum(mul(a,b))` exact, flags included, so
the host issues an elementwise multiply and then a sum.

The direction of causation is the point: the composition property was
put into the contract *partly so that this implementation choice would
exist*. The alternative was a multiply pass sharing the accumulator's
pipe with tagged results and arbitration between muls and adds - the
most schedule-sensitive logic in the engine - to save one round trip.

**What is not new:** decomposing dot into multiply-then-reduce.

**What we could not find:** the practice of writing an exactness
property into a public numerical contract specifically to license a
hardware omission, and documenting it as such so that a future
implementer knows the freedom is deliberate rather than accidental.

**Evidence:** `host/include/cft.h` reduction section; `host/src/device.c`.

---

### 10. The binary256 datapath itself has no published hardware precedent

Surveyed 2026-08-31 (an ~70-search sweep: web, arXiv, IEEE Xplore
titles, authenticated GitHub code search, OpenCores, vendor IP
catalogues; primary sources downloaded and read where they existed).
**No hardware implementation of IEEE 754 binary256 was found anywhere**
- not in commercial silicon, not in academic FPGA/ASIC work, not in
open RTL, not in vendor IP, not as an ISA proposal. A 2025
peer-reviewed statement agrees: Zhang & Aiken (SC'25,
doi:10.1145/3712285.3759876) - "no processors have ever featured
hardware support beyond quadruple precision."

What this tile's fp256 rung does therefore appears to be unpublished
as hardware: an IEEE binary256 FMA datapath with all five rounding
attributes, tininess-after-rounding, gradual underflow, and
single-rounded fused multiply-add, running beside fp32/64/128 under
one contract.

**The nearest miss, and it is worth respecting: GRAPE-MP /
GRAPE9-MPX** (Daisaka, Nakasato, Ishikawa et al.; structured ASIC
2011, Arria V FPGAs 2014-2018; arXiv:1410.3252, arXiv:1803.07224).
The only published hardware computing floating-point arithmetic at
octuple SCALE. Its own table says why it is not binary256: a
1+19+240 format, 260 bits internally, truncated to 256 on host
transfer - the exponent width was borrowed from binary256, the
significand was not. Add and multiply only, no FMA; divide is a
software Newton iteration off a low-precision rsqrt seed; rounding
modes, subnormals and exception semantics are undocumented in every
accessible paper. Honest framing: octuple-scale FPGA arithmetic has
been done once, in a custom format; a CONFORMANT binary256 unit has
not.

**The fp128 rung is rarer company than expected, too.** Hardware
binary128 exists in exactly three commercial families - IBM z
(continuously since the S/390 G5 in 1998, multi-pass through the BFU
until z13 moved it onto the decimal engine's 140-bit pipelined
dataflow), IBM POWER (9 onward), and NEC SX-Aurora - and their
capabilities are narrower than they look. IBM z has NO SCALAR quad
FMA (verified against the z/Architecture Principles of Operation:
scalar MULTIPLY AND ADD exists only for short and long formats);
z14 (2017) added a binary128 FMA in the VECTOR instruction set
(WFMAXB family, single-element, confirmed in LLVM's SystemZ backend:
"We only have fused f128 multiply-addition on vector registers").
NEC SX-Aurora has scalar quad add/sub/mul only - no FMA, no divide,
and its own manual says subnormals "are cut down to zero." POWER9/10
has the full set including FMA - each QP instruction is a single
internal op (the User's Manual's cracked/expanded column reads "-"
for all of them), with multiply/FMA occupying the 12-stage pipe for
12 cycles, i.e. multi-pass but not cracked; quad FMA throughput is
52x worse than double FMA on the same core. z14 and POWER9 both
landed in 2017, so neither can safely be called the first hardware
binary128 FMA - and both are ITERATIVE designs: the z14 patent
(US10303438B2) runs seven passes through a 113x113 carry-save
multiplier, and POWER9 occupies its 12-stage pipe for 12 cycles per
FMA. A fully pipelined binary128 FMA - one issue per cycle - appears
to have no commercial precedent at any date, which makes this tile's
fp128 bank (two lanes, each one FMA per cycle) unpublished in a
second, narrower sense before the fp256 rung is even counted. In open RTL the strongest is CORE-V Wally's Q
configuration; Berkeley HardFloat is tested at quad; robfinch/Float
has a full binary128 module set with, per its author, "rudimentary
testing."

**Why nobody did it, probably - and it is not area.** Berkeley
SoftFloat/TestFloat, the reference tooling every credible quad
implementation verifies against, stops at f128. There is no f256
reference model, no standard vector generator, nothing to be checked
against. A binary256 datapath obliges its builder to supply the
definition of correct before writing the hardware - which is
precisely the golden-model-first discipline this repo was built on,
for its own reasons. The missing precondition elsewhere was this
project's starting point.

**What is not new:** wide-significand hardware per se. The bounding
prior art is real and worth citing: CEA's variable-precision RISC-V
units (UNUM-derived, up to 512-bit significands, silicon in 22nm);
APFP's 512/1024-bit FPGA multiply-add (non-IEEE, 63-bit exponent, no
rounding modes); quad-double MAC units (256 bits of storage, double's
exponent range); Kulisch accumulators and the posit quire (wide
FIXED-point exactness, not a floating-point format). Every one of
these buys width by leaving IEEE semantics behind, which is exactly
the part this design refuses to leave.

**What we could not find:** any of - a binary256 arithmetic unit; an
octuple-precision FMA in any format; an ISA extension beyond
binary128 for binary FP; a taped-out chip or patent claiming either.
One paper qualifier: Synopsys DesignWare's DW_fp_* ASIC synthesis
components have a REPORTED (login-walled, not independently verified)
parameter range of sig_width 2-253 / exp_width 3-31, which would
admit binary256 geometry on paper. Synopsys advertises nothing above
double, no characterisation at such widths is public, and a legal
parameter range is not an implementation - but "no vendor IP reaches
fp256" should be read with that asterisk, where "no vendor FPGA IP
reaches even fp128" (AMD PG060 verbatim: "binary128 (Quadruple
Format) - not supported"; Intel caps at 64 bits total) needs none.
GitHub code search for RTL with binary256 geometry returns one
untested 445-line file (no FMA, non-IEEE rounding, flushes
subnormals) and one format-decoder. Searches that returned zero are
listed in the survey provenance, held with this file's usual caveat:
"we could not find it published" is not "it is unpublished," and the
survey itself caught a 2025 peer-reviewed absence claim that missed
two real quad implementations (IBM z, NEC) - expert surveys
under-count in this area, so this entry claims "none found," never
"none exists."

## Negative

Negative results are the entries most likely to be genuinely
unpublished, because the incentive to write up a thing that did not
work is close to zero. Both of these cost real time to establish and
would cost the next person the same.

### 6. Fracturing a significand multiplier does not pay on an FPGA, and the ASIC literature inverts

The multi-precision FMA literature is consistent and, for its target,
correct: segment the wide datapath so the narrow modes reuse it.
Huang et al. (ARITH-18, 2007) report +18% area for 1xfp64 / 2xfp32;
Zhang, Chen & Ko (IEEE TC 68(7), 2019) report +10.6% for an 8-way
split; Akkaş & Schulte report +14% for a dual-mode fp128 adder.

**All of it is ASIC, where a multiplier is gates.** On an FPGA a
significand multiplier is DSP blocks. Fracturing it therefore saves
the resource that is abundant and spends the one that is scarce, and
the sign of the trade flips.

Built and measured here (`rtl/cft_mulfrac.sv`, out-of-context at 145
MHz):

| | LUT | DSP | WNS |
|---|---|---|---|
| private multipliers | 124,589 | 262 | +0.959 ns |
| fractured array | 125,282 | 259 | -0.181 ns |

**+693 LUT, -3 DSP, and timing closure lost.** The array is retained
behind `FUSE_MUL`, default off, because the *code* is correct and the
*trade* is wrong on this fabric.

The generalisable form: **on FPGA, fracture what the fabric implements
in LUTs, not what it implements in hard blocks.** For an FMA that
means the alignment shifter, the significand adder and the normaliser
- which the same ASIC papers also segment, and which are the parts
worth copying.

**Addendum (2026-08-30): the second criterion, which is about shape
rather than fabric, and which decides the question before anything is
built.** The banks here are mutually exclusive - one precision is live
per run - so time-sharing them needs no arbitration and no buffering.
What decides whether sharing pays is whether the structure's width is
**linear or quadratic** in the format width.

The tile is fed by a fixed memory beat, so every bank consumes exactly
one 256-bit beat: eight fp32, four fp64, two fp128, one fp256.
**Aggregate operand width is therefore identical in every mode.** A
linear-width structure shared across the banks is exactly as wide as
the widest bank and the narrow modes waste nothing. For a quadratic
structure the widest bank alone is most of the total, so the same
collapse buys much less.

The FMA's aligner is `3P + 7` bits, aggregating to 632 / 664 / 692 /
718 against a widest bank of 718: **3.77x collapses to 1x with under
14% slack.** The normaliser is the same shape. The multiplier, at
`P x P`, aggregates to 4,608 / 11,236 / 25,538 / 56,169 = **97,551
bit-products against a shared array's 63,990: 1.52x** - a real
collapse, but half the aligner's, because the fp256 bank alone is 58%
of the total.

*(An earlier draft of this addendum reported 1.0x for the multiplier by
putting the fp256 bank in the aggregate column rather than the sum over
banks - an inconsistency with the aligner row, not a measurement.
Corrected the same evening.)*

**The collapse ratio is the secondary reason, and the DSP column above
is the primary one.** 262 -> 259 says the fractured array saved no DSP
at all: a wide cascaded multiplier is less DSP-efficient per
bit-product than a narrow one - about 246 against 372 - so the 1.52x
is spent on cascade overhead before it reaches the resource count.
Sharing a hard block that sits at 4.4% utilisation cannot pay, whatever
the geometry says; the geometry only decides how badly it loses.

**A distinction the measurement makes that the ratio does not.** The
array *does* gang the lanes - mode 0 is eight independent 24x24
products per beat, mode 3 is one 237x237, and `tb_mulshare` proves
bit-identity across all four. What it shares is the NUMBER of partial
products, not their WIDTH: every slot is `PMAX x MCH` = 237x27 in every
mode, so an fp32 lane runs a 24x24 job through hardware built for
237x27 - **9% occupancy of the silicon it sits on, at 100% lane
utilisation.** "Every lane busy" and "every gate busy" are different
claims, and only the first one held.

**What we could not find:** the beat invariant used this way - as an
a-priori test for which parts of a multi-precision datapath are worth
sharing, decided from the memory interface rather than from
synthesising both. The multi-precision FMA literature segments
everything it can and reports the aggregate; we found no statement
that a fixed-beat interface makes the linear parts nearly free to share
while leaving the quadratic parts barely worth it.

**What we could not find:** any FPGA measurement of a fractured
significand multiplier, positive or negative. The ASIC results are
well cited and, as far as we can tell, have not been checked against a
fabric where the multiplier is hard.

### 7. Cutting a tree into at most k parts can require more than k ranges

To split a reduction across tiles, the array is cut into canonical
*nodes* of the tree - anything else changes the answer. The natural
assumption is that asking for at most `k` parts yields at most `k`
ranges.

It does not. A level cut of the largest-power-of-two tree splits the
perfect left subtree and leaves the remainder beside it, so **four
tiles get five ranges** at n = 5, 9, 17, 33, 65, and eight tiles
exceed eight for **49 of the first thousand n**.

This is not an edge case reachable only at large n, and it caused a
silent wrong answer: a backend that staged one range per tile
overwrote range 0's operands with range 4's before range 0 had run,
returning a wrong sum with clean status and plausible flags. fp32 over
four compute units at n=9 gave 51.0 instead of 45.0.

**What we could not find:** this property stated anywhere. It is
elementary once seen, which is exactly why it is worth writing down -
the assumption it violates is the one a competent implementer makes
without noticing they have made it.

**Evidence:** `python/cft_golden/reduce.py` (`canonical_ranges`),
`host/tests/reduce_parts_test.c`, which now models the wave schedule
and fails 57 checks if the staging bug is reintroduced.

---

## Observed, not used

Recorded so the observation is not lost, and clearly separated because
we have **not** built these and they are therefore not evidence of
anything.

### 8. Sticky from a multiply-based alignment shift

**This entry was written as a broader claim and has been corrected.
The correction is kept visible rather than edited away, because it is
the document's own standard working as intended.**

The claim as first written was that shift-by-multiply had never been
combined with sticky extraction, and that the combination was
unexploited. **The first half is false.** Shift-via-multiply applied
to IEEE-754 alignment *and* normalisation is published and measured:

> "The alignment stage requires two iterations through the execution
> core. **Shifting in the DSP48E1 is implemented as a multiplication,
> with the 18 bit multiplier input set as 2^k**, where k is the shift
> amount calculated in the pre-alignment stage."
>
> — Brosser, Cheah & Fahmy, *Iterative Floating Point Computation
> Using FPGA DSP Blocks*, FPL 2013

The same paper does normalisation the same way, and reports 242 slice
LUTs / 161 registers / 1 DSP48E1 at 340 MHz for a single-precision
iterative adder - 48% fewer LUTs than their logic-only baseline. The
underlying technique is vendor-documented: Xilinx UG193 ch. 4 gives
the `2^K` one-hot multiply and an 18-bit two-DSP barrel shifter, and
UG479 lists "barrel shift" among DSP48E1 functions. It is also
attested as practitioner folklore back to at least 2006 (Andraka,
comp.arch.fpga).

**What survives, and it is much narrower: none of the DSP-shift
sources addresses sticky.** The FPL 2013 design is iterative and does
not discuss inexact generation; UG193 and the Microsoft barrel-shifter
patent (US 20240419446 A1) are integer applications; the ARM shift
instruction patent (US 10162633 B2) discusses rounding constants in
the multiplier array in the same passage and still does not connect
them. So the observation that the discarded low half of the product
*is already exactly the shifted-out vector*, and therefore yields
sticky with no mask, no AND and no OR-reduction, remains unstated as
far as we found.

That is a small residue of a claim that was mostly wrong, and it
should be read as such.

**Why we are not doing it, which has not changed:** the exchange rate
is wrong at these widths. A DSP48E1/E2 is 25x18, giving shifts of 0-17
on a <=25-bit operand, so single precision already needs two cascaded
DSPs or two iterations and double precision is out of reach without
heavy time-multiplexing. Our 717-bit datapath is far beyond that.
Covering it costs roughly 22-66 DSPs to save ~470-1,400 LUT6 - about
20 LUT per DSP, against a device whose natural ratio is 146 LUT/DSP.

The strongest evidence against it is not arithmetic but behavioural:
`fbrosser/DSP48E1-FP`, by the same author as the FPL 2013 paper and
explicitly built to "use the DSP48E1 DSP slice for as many of the
computations as possible", **still implements its alignment and
normalisation shifters as fabric mux trees** and puts only the
significand add in the DSP. When the person who published the
technique does not use it in their own parallel design, the economics
are telling you something.

### 9. An 8-way fracture of a 237-bit-significand FMA on an FPGA

Every published multi-precision FMA is ASIC, at 2-way or 4-way, at
double or quad significand widths. An 8-way split of a 237-bit
significand, on FPGA, appears not to have been built by anyone.

That is a statement about the literature, not a recommendation. Given
entry 6 - our one local data point in this area is a *negative* one,
where a predicted saving evaporated on contact with the fabric - the
appropriate prior for an unpublished 8-way fracture is caution, and
the appropriate first step is measurement rather than construction.

---

## Provenance

**The 2026-08-31 fp256/fp128 hardware survey (entry 10)** ran ~70 web
searches and ~25 authenticated GitHub code searches, and downloaded
and read primary sources where they existed: both GRAPE9-MPX arXiv
papers, the ARITH-23 z13 quad paper, the z/Architecture Principles of
Operation (SA22-7832-13, instruction tables), the POWER9 User's Manual
(DFU section and Table A-1), the NEC SX-Aurora Architecture Guide Rev
1.1, Zhang & Aiken SC'25, and the full source of every RTL candidate
(mcjtag/fpx, robfinch/Float, CORE-V Wally configs, cvfpu's
fpnew_pkg.sv, libre-soc, SPEX-128). Zero-result searches recorded:
"binary256"/"octuple precision" hardware across web, arXiv, IEEE
titles and patents; GitHub RTL with EXP_W=19/MAN_W=236 geometry
(one untested file); "FLEN=128" RTL (zero); vendor IP above 80-bit
extended (zero). Blocked fetches recorded so they are not mistaken
for negatives: IET/ScienceDirect/ACM full texts (HTTP 403), Synopsys
DesignWare parameter tables (account-gated). One item explicitly
not-independently-verified: Fujitsu SPARC64 (Oracle's "any SPARC FPU"
statement and SC'25 both point to no-quad-hardware, but no Fujitsu
datasheet was obtained).


Entries 6 and 7 are measurements taken in this repository and are
reproducible from it. Entries 1-5 are design decisions whose novelty
claim rests on literature searches conducted 2026-08-30 across IEEE,
ACM, arXiv, Google Patents, AMD/Xilinx documentation, and the
open-source FPU cores FloPoCo, Berkeley HardFloat, FPnew/CVFPU and
DSP48E1-FP. Entries 8 and 9 are literature observations only.

The searches that were bounded, and where a contrary result is most
likely to be found: Bewick, *Fast Multiplication* (Stanford
CSL-TR-94-617) Appendix B; Ushenina, FarEastCon 2020 and CSOC 2020, on
FPGA carry-chain sticky generation; Gök & Özbilen, *Evaluation of
Sticky-Bit Generation Methods for Floating-Point Multipliers* (JSPS
2009), whose per-method area tables were not reachable.

**One entry has already been falsified.** Entry 8 was first written
claiming that shift-by-multiply had not been applied to IEEE-754
alignment; a further search found Brosser, Cheah & Fahmy (FPL 2013)
doing exactly that, plus vendor documentation of the underlying
technique in Xilinx UG193. The entry was narrowed to the part that
survives and the correction left visible.

That is the intended failure mode of this document, and it is worth
saying plainly: **entries here are claims about the literature, which
is a claim about an absence, which is the weakest kind of claim
there is.** The measured entries - 6 and 7 - do not depend on any
such claim and are the parts of this file worth relying on. Treat the
rest as an invitation to be corrected.
