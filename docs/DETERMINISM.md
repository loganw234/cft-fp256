# The determinism contract

What this hardware promises about every bit it produces, stated so it
can be checked by someone who trusts none of this code. Clause
references are to IEEE Std 754-2019, quote-verified 2026-08-28 against
the licensed PDF, with the standard's own words where the choice is
load-bearing.

## The promise

**Same inputs, same op, same bits - on this tile, on the golden model,
and on any other implementation of this contract.** No configuration,
compiler, driver, tool version, placement seed, or timing behaviour may
change a result bit or a flag bit. A divergence is a bug in the
diverging implementation, by definition, and the conformance vectors
(vectors/) are how the claim is scored.

This is the same bar the atlas-engine det library holds on GPUs - one
hash across vendors - reached from the other side. GLSL earns it by
pinning a hostile toolchain operation by operation; RTL earns it by
construction, because there is no driver between the source and the
gates. The two meet at the primitive set: pinned add/sub/mul/fma with
RNE, denormals, and exact selections. An algorithm written against
those primitives (every `det_*` function is fma/Newton/polynomial
chains over them) lands on identical bits wherever the primitives do.

## Formats

The IEEE 754-2019 binary interchange ladder, exactly:

| format | w (exp) | t (frac) | p | emax | bias |
|---|---|---|---|---|---|
| fp32  | 8  | 23  | 24  | 127    | 127    |
| fp64  | 11 | 52  | 53  | 1023   | 1023   |
| fp128 | 15 | 112 | 113 | 16383  | 16383  |
| fp256 | 19 | 236 | 237 | 262143 | 262143 |

fp256 parameters follow Table 3.5's binary{k} formulas; the standard
names the example itself: "binary256 would have p = 237 and
emax = 262143" (3.6, Table 3.5). No bfloat, no TF32, no vendor
variants: identity needs one definition per width.

Hardware and golden model both implement all four rungs; a trimmed
tile advertises what it carries in the CAPS CSR
(docs/ARCHITECTURE.md) and is bit-identical on those rungs.

## Operations

The arithmetic core: `fma(a,b,c) = a*b + c`, `add`, `sub`, `mul` -
elementwise over vectors. Everything else the tile implements is
non-arithmetic and is specified further down.

ADD/SUB/MUL are defined as operand-steered FMA (see
`cft_golden.softfloat.steer` and rtl/cft_opmux.sv); the steering is
proven equivalent to the direct IEEE definitions by
`test_steering_composition`, signed zeros and specials included.

fusedMultiplyAdd computes "(x × y) + z as if with unbounded range and
precision, rounding only once to the destination format" (5.4.1). The
product is exact inside the datapath; it cannot overflow, underflow,
or round before the addend joins. `test_fp32_fused_single_rounding_witness`
holds the canonical witness: fp32 `fma(1+2^-23, 1-2^-23, -1) = -2^-46`
exactly, where any double-rounded implementation returns +0.

## Rounding

All five 754-2019 rounding-direction attributes (4.3.1, 4.3.2),
selected per operation in MODE[14:12] using RISC-V's `frm` encoding:

| code | attribute | name here |
|---|---|---|
| 0 | roundTiesToEven | `rne` - the default, and what "the contract" means unless a run says otherwise |
| 1 | roundTowardZero | `rtz` |
| 2 | roundTowardNegative | `rdn` |
| 3 | roundTowardPositive | `rup` |
| 4 | roundTiesToAway | `rmm` |

Encodings 5-7 are reserved: the hardware treats them as `rne`, and the
golden model rejects them outright, so no conforming host can depend
on a value the contract does not define.

**Each attribute is its own deterministic contract** - the same inputs
under the same attribute always give the same bits, on every device
that implements this specification. Determinism was never a property
of round-to-nearest specifically; it is a property of the rounding
being *specified*.

Two consequences that catch implementations out, both of them
mode-dependent and both pinned by named tests:

- **Overflow (7.4)** is signalled in every attribute, but what gets
  delivered differs: `rne`/`rmm` give an infinity; `rtz` never does
  (it gives the largest finite magnitude); `rdn` gives -infinity only
  on the negative side and `rup` +infinity only on the positive one.
- **The sign of an exact zero (6.3)** is +0 in every attribute except
  `rdn`, where it is -0.

The attribute travels with its operation down the pipeline rather than
being latched per run, so adjacent operations may use different ones.
That is what interval arithmetic wants: a lower and an upper bound
from a single pass. `test_directed_modes_bracket_the_exact_value`
proves the pair brackets the exact result and, when inexact, that the
two bounds are adjacent - the tightest interval the format admits.

Every rounding in the implementation still happens at exactly one site
in each of the golden model (`round_pack`) and the RTL (stage 13 of
`cft_fpfma_pipe`), which is what makes the claim auditable. The
attributes are verified against the *definition* rather than against
another implementation: `python/tests/test_rounding.py` decodes each
result into an exact rational and re-derives what 754 requires by
exact rational floor division, sharing no code path with the model.

## The non-arithmetic operations

Nineteen opcodes that do not round, do not consult the rounding
attribute, and cannot be inexact:

| group | operations | clause |
|---|---|---|
| sign | `abs`, `negate`, `copySign` | 5.5.1 |
| min/max | `minimum`, `maximum`, `minimumNumber`, `maximumNumber` | 9.6 |
| predicate | `cmplt`, `cmple`, `cmpeq` (quiet comparisons) | 5.11 |
| data | `select` | - |
| integer | `iand`, `ior`, `ixor`, `iadd`, `isub`, `ishl`, `ishr`, `icmplt` | - |

Rules worth stating because they are the ones implementations get
wrong:

- **`min(+0, -0)` is -0 and `max(+0, -0)` is +0.** Not a choice: 9.6
  says "for this operation, -0 compares less than +0", which takes ±0
  out of the "either operand" case. A min/max that returns "either,
  they're equal" is non-conforming and free to differ per device.
- **The `...Number` forms return the NUMBER when one operand is a
  signaling NaN**, raising invalid but not converting it - 9.6 says
  the sNaN "is otherwise ignored and not converted to a quiet NaN".
  This changed from 754-2008's minNum/maxNum; implementing the old
  behaviour is the common mistake.
- **The plain `minimum`/`maximum` forms return the canonical quiet
  NaN**, per the canonicalisation rule below - they do not forward the
  operand's payload.
- **`cmplt`/`cmple`/`cmpeq` are the QUIET predicates** (5.11): they
  signal only on a signaling NaN, and an unordered pair makes every
  predicate false. They yield 1.0 or +0.0 rather than a condition
  code; 5.6.1 calls the result boolean and nowhere fixes its
  representation, so this conforms and lets `select` consume it.

### Where the canonical-NaN rule does not apply

The rule below - any NaN in, one canonical quiet NaN out, sNaN raises
invalid - governs **arithmetic**. Three groups are outside it, and
saying so precisely matters because this document is what an
independent implementation is scored against:

| group | NaN behaviour |
|---|---|
| `abs`, `negate`, `copySign` | pass the pattern through, payload intact, signal **nothing** even for a signaling NaN (5.5.1: "they only affect the sign bit... and signal no exception"; 6.2.3 exempts exactly these) |
| `select` | moves whichever operand it selects through intact, payload and all, and signals nothing |
| the integer group | there are no NaNs - the operand is a W-bit unsigned word, and no bit pattern means anything but itself |

None of this weakens determinism. The canonical rule exists because in
arithmetic *which operand's payload survives* is where implementations
diverge; in every case above the result is a function of the input
bits with no choice to make. 754-2019 7.1 leaves the signalling
behaviour of operations outside the standard to the implementation,
and this table is that definition.

### Unassigned opcodes

Opcode 15 and everything from **26** up are unassigned. They return the
canonical quiet NaN with **invalid** raised, in the hardware and in
the golden model alike. Deterministic, and visible in the flags -
which matters because those codes are where divide, square root and
conversions will land, so a host that issues one early should learn it
now rather than get a plausible number that changes meaning under a
later bitstream.

24 and 25 were unassigned and are not any more: they are `sum` and
`dot`, assigned 2026-08-30. That is exactly the hazard this section
warns about, and it played out as designed - a vector set generated
before the assignment still names opcode 24 "reserved24", and
replaying one now would score a sum against an answer recorded for the
unassigned-opcode result. `cft_conformance` detects that specifically
and says so, rather than reporting a mismatch.

## Subnormals

Fully supported, in and out, never flushed - there is no FTZ/DAZ mode
to even switch on. This is the freedom GLSL grants drivers ("a driver
may flush denormals", the exact hazard atlas finding 73 measured) that
this hardware simply does not have.

## NaN

Any NaN in, one canonical quiet NaN out: sign 0, exponent all ones,
quiet bit set, payload zero. A signaling NaN operand raises invalid
(7.2). Invalid operations (`inf * 0`, `inf - inf` in any fused
arrangement) produce the same canonical qNaN with invalid raised.

Deliberate deviation from a 754 *recommendation*: 6.2.3 recommends
(should, not shall) propagating an input NaN's payload. Payload
propagation order is exactly where implementations diverge - which
operand wins varies by vendor - so this contract chooses the one
canonical output instead. RISC-V made the same choice for the same
reason.

## Signed zero

Per 6.3, and the standard's words carry the two rules people miss:

- "When the sum of two operands with opposite signs (or the difference
  of two operands with like signs) is exactly zero, the sign of that
  sum (or difference) shall be +0" in every attribute except
  roundTowardNegative, where it is -0. Implemented in both the model
  and the RTL; `test_exact_cancellation_sign` pins all five.
- "However, ... when x is zero, x + x and x − (−x) have the sign of x"
  - like-signed zeros keep their sign.
- The zero product keeps XOR of the operand signs, which is why MUL's
  steering injects a zero addend carrying sign(a)^sign(b) rather than
  +0.
- FMA: an exactly-zero (a×b)+c follows the sum rules; a result that is
  zero *because of rounding* "takes the sign of the exact result"
  (6.3) - the underflowed-to-zero path keeps the true sign.

## Underflow and the flags

Flags are sticky data, never traps: every element yields a 5-bit set
`{inexact, underflow, overflow, divzero, invalid}` (divzero reserved
until a divide op exists), and a run's FLAGS CSR is the OR over all
elements - order-independent by construction.

Tininess is detected **after rounding**: a result is tiny when "a
non-zero result computed as though the exponent range were unbounded
would lie strictly between ± b^emin" (7.5 a). The standard requires
one consistent choice across all operations (7.5); this contract picks
after-rounding (as RISC-V does) and
`test_fp32_tininess_after_rounding_boundary` pins the observable
boundary: `fma(0.75, min_sub, max_sub)` rounds up to exactly
min_normal and must NOT raise underflow, where a before-rounding
implementation raises it.

The underflow flag rises only when the result is both tiny and inexact
(7.5: "if the rounded result is inexact ... the underflow flag shall be
raised. If the rounded result is exact, no flag is raised"). Exact
subnormal results are flagless.

Overflow follows 7.4: overflow and inexact are both raised in every
attribute, and the delivered value is the one that attribute's table
requires (see Rounding above) - infinity under `rne`/`rmm`, the
largest finite magnitude under `rtz`, and one or the other under the
directed attributes depending on which side of zero the result lies.
`test_overflow_response_table` holds all ten combinations as literals.

## Ordering

Elementwise work raises no ordering question at all: element i of the
output depends on element i of the inputs and nothing else, so the
flags OR is the only cross-element artifact and OR is commutative.

**Reductions landed 2026-08-30 and keep the promise this section made
before they existed:** their tree shape is fixed by element index,
never by arrival time or lane availability. A float accumulation whose
order depends on scheduling is the GPU failure mode this design refuses
(the darkroom measured it directly: a compare-and-swap deposit chain
measures warp arrival order, not the plate).

What that fixes, and what it deliberately leaves free, is worth being
precise about, because the freedom is load-bearing:

- **Fixed: the pairing.** Which values are added together, and at which
  level of the tree. `python/cft_golden/reduce.py` defines it - split at
  the largest power of two inside the index range - and everything else
  calls that one function.
- **Free: the schedule.** Adds may be issued in any order and be in
  flight together. A pair's operands are both determined before it
  issues, so when it issues cannot reach the answer. The hardware
  accumulator relies on this: it defers carries so several adds run at
  once, which is the difference between ~1 and ~15 cycles per element.
- **Free: the operand side.** `add(a,b) == add(b,a)` bit for bit here -
  magnitude is symmetric, the sign of an exact cancellation comes from
  the rounding attribute (6.3) rather than operand order, and NaN
  results are always the canonical quiet NaN rather than a propagated
  payload. Verified over 80,000 pairs and pinned by a test, because it
  is a property three implementations quietly depend on.
- **Free: which tile.** A partial result is reusable if its range is a
  node of the tree; which physical tile evaluated that node cannot
  enter the answer. See docs/SCALING.md - this is why dynamic load
  balancing is available to a deterministic machine.

## The verification lattice

Every claim above is a test somewhere, and the layers share no code:

| layer | proves | against |
|---|---|---|
| `python/tests/test_softfloat.py` | golden model semantics | CPython native binary64, `math.fma`, mpmath (all four formats), hand-computed 754 anchors |
| `tb/test_fpfma_fp32.py` / `_fp256.py` | RTL datapath, streamed | golden model, bit-for-bit incl. flags |
| `tb/test_krnl.py` | CSR + engine + AXI + steering + banks | golden model through the same interfaces XRT uses |
| `vectors/gen_vectors.py` | any external implementation | replayable JSONL conformance sets |

What is deliberately NOT claimed yet: behaviour on a physical card
(docs/BRINGUP.md gates that), and any timing/performance number.

## Clause locator index

For auditors with the standard open: format parameters 3.6 Table 3.5;
fusedMultiplyAdd 5.4.1; NaN semantics 6.2 (payload recommendation
6.2.3); sign bit rules 6.3; invalid 7.2; overflow 7.4; underflow and
tininess 7.5.
