# The enclosure tool

`host/tools/enclose.c`, built by `make -C host enclose`, computes three
kernels twice - once under `roundTowardNegative` and once under
`roundTowardPositive` - and prints the interval. The true value is
provably inside it. `host/tests/enclose_check.py` scores every one of
those intervals against a value Python computes without rounding;
`make -C host enclosetest` runs that.

> **The reproducibility claim, in one sentence.** An enclosure produced
> by this tool is the same bits on every conforming host, so a verified
> result can be *reproduced*, not merely re-derived.

That sentence is the whole point, and it is what an interval library on
ordinary hardware cannot say. Interval arithmetic needs correctly
rounded results in a directed attribute, chosen per operation; this
contract has all five attributes at every format, per call and - in the
sequencer - **per instruction**, with exact flags. So the enclosure is
not an estimate of the error, it *is* the error bound; the flag word
says whether the bound is strict; and because the arithmetic is
deterministic, two machines produce the SAME interval rather than two
overlapping ones. The width of an enclosure computed on ordinary
hardware is a property of somebody else's compiler flags. Here it is a
property of the numbers.

---

## The three kernels

### 1. Series - a rigorous tail bound

`exp(x) = sum_{k>=0} x^k / k!` over dyadic `x = j/P` in [0, 1]; `x = 1`
is `e` itself. The term recurrence is

    t_k = t_{k-1} * x / k          one MUL and one cft_div per side
    s   = s + t_k                  one ADD per side

with the lower chain issued entirely under RDN and the upper entirely
under RUP. For `x >= 0` both steps are monotone increasing in
`t_{k-1}`, so the RDN chain stays at or below the true term at every k
and the RUP chain at or above it; the partial sums inherit that, and
the lower bound needs nothing else, because a partial sum of positive
terms is already below the limit.

The **tail** is charged to the upper bound alone:

    sum_{k>N} x^k/k!  =  t_N * sum_{j>=1} x^j / ((N+1)...(N+j))
                      <= t_N * (x/(N+1)) / (1 - x/(N+1))
                       = t_N * x / (N+1-x)     <=   t_N / N

for `0 <= x <= 1` and `N >= 1`, and the tool adds `RUP(thi_N / N)`,
which is at or above `t_N / N` because `thi_N >= t_N`.

**N is derived, not tabulated.** It is the smallest term count whose
tail bound at `x = 1` falls below `2^-(p+1)`, found by running the
recurrence at setup with the format's own measured p. That gives 10
terms at binary32, 18 at binary64, 31 at binary128 and 54 at
binary256 - and it is why the tail is never the reason a width is
wide: at binary256 it is below a quarter of an ulp of `e`, where the
rounding of 54 divisions is about 53 ulps.

### 2. Dot and matrix-vector - the exact case, and the useless one

`cft_reduce` with `CFT_DOT` under RDN, then again under RUP. Every
element is a small odd integer times a power of two, so it is a dyadic
rational the format holds exactly, **and the exact dot product is a
rational Python's `fractions` computes with no rounding at all**. That
is what makes the oracle exact rather than approximate, and it is the
reason the vectors are constructed rather than drawn from a float
generator.

Three shapes, fifteen items:

| item | shape | exact value |
|---|---|---|
| `exact` | 128 small integers; every product and every partial sum of the tree fits inside p bits | 68 |
| `cancel-spread<s>` x 6 | `x = [v, v, 1]`, `y = [w, -w, 1]` under one shared permutation, so the mirrored block cancels **exactly** as a rational | 1 |
| `matvec-row<i>` x 8 | the same construction per row of an 8 x 65 matrix | 1 each, so `A b` is the all-ones vector |

The permutation is not decoration. Without it the mirror image of a
subtree is another subtree, the contractual tree cancels the two
against each other at one node, the cancellation is exact and the case
tests nothing.

**Does the contractual tree's fixed order matter for the bound?** For
CONTAINMENT, no, and that is worth being clear about: any order of
additions under RDN gives a result at or below the exact sum, because
every node is, so the enclosure would be valid whatever shape the
reduction took. Reassociating changes the WIDTH - a different shape
loses a different number of ulps - but never the containment.

For BIT IDENTITY it matters entirely, and that is the point of the
whole exercise. `docs/DETERMINISM.md` fixes the pairing by element
index - split at the largest power of two inside the range - and leaves
the schedule and the operand side free. So the interval this tool
prints for a given vector is the same interval on one tile or four, in
simulation or on silicon, today or next year; a reduction whose order
depended on arrival would still produce a valid enclosure and a
different one, and "a verified result can be reproduced" would become
"a verified result can be re-derived, approximately". A bound nobody
else can reproduce exactly is a weaker object than a bound anybody can.

Two knobs set how hard the case is, and they are not the same knob:

- `--dot-top` (60) fixes the magnitude of the largest product, so the
  **condition number** `2*sum|x_i y_i| / |x.y|` is about **2^60 to
  2^66** for every rung. That is how many bits of precision are needed
  before the first bit of the answer is right, which is why binary64
  (p = 53) has nothing left on any of them.
- the rung's **exponent spread** fixes how many significand bits the
  exact cancellation *requires*: products run from `2^top` down to
  `2^(top-spread)`, so the exact sum is a multiple of a quantum
  `2^(top - 2*mw - spread)` with a magnitude near `2^(top+8)`, needing
  about `2*mw + 8 + spread` bits. A format holds the whole cancellation
  exactly when p exceeds that - which is the entire fp64-versus-fp256
  result in one line.

**binary32 cannot run this kernel at all, and that is a fact about the
formats rather than a gap in the tool.** A spread wide enough to defeat
binary256's 237-bit significand puts the smallest element below
binary32's smallest normal. The tool checks the ladder against the
format's range before any work starts and refuses with that message
rather than silently rounding the data. `--kernels series,horner` runs
the other two at binary32.

### 3. Horner - interval coefficients, one instruction stream

`P(x) = sum_{k=0}^{d} x^k / k!` at dyadic points in [-1, 1], evaluated
by interval Horner. The coefficients `1/k!` are not dyadic, so each is
itself an enclosure, built by the library:

    c_0 = [1, 1]                            exact
    c_k = [ RDN(clo_{k-1}/k), RUP(chi_{k-1}/k) ]

which contains `1/k!` by induction. `host/tests/enclose_check.py`
checks that containment separately, so a failure says which of the two
claims broke.

The recurrence, for a point `x` and an interval `[a, b]`:

    x >= 0:   [a, b] <- [ RDN(x*a + clo),  RUP(x*b + chi) ]
    x <  0:   [a, b] <- [ RDN(x*b + clo),  RUP(x*a + chi) ]

`x*[a,b]` is `[x*a, x*b]` when x is non-negative and `[x*b, x*a]` when
it is not; that swap is the only thing the sign costs, and it is two
`SELECT`s. Containment is then immediate: if `a <= Y <= b` and
`clo <= C <= chi` then `x*a + clo <= x*Y + C <= x*b + chi` for
`x >= 0`, and RDN/RUP move each end further out, never in.

---

## The step, as an orbit-sequencer program

This is the kernel that runs on-chip, and it is where the
**per-instruction rounding attribute** earns its three encoding bits.
`docs/SEQUENCER.md` says the attribute travels with each operation
rather than being latched per run, and that "is what makes one pass
able to produce both interval bounds". This is that pass:

```
  CMPLE    r6 <- r5 <= r0        ; r5 is +0 and never written to
                                 ;   -> nn, "x is non-negative"

  ; eight times, once per coefficient of this chunk:
  SELECT   r7 <- nn ? r1 : r2    ; the operand the LOWER bound needs
  SELECT   r8 <- nn ? r2 : r1    ; ...and the one the UPPER bound needs
  FMA.RDN  r1 <- r0*r7 + clo_j   ; <- the two attributes that make
  FMA.RUP  r2 <- r0*r8 + chi_j   ;    this ONE instruction stream

  DEPOSIT  r1                    ; the lower bound out
  DEPOSIT  r2                    ; the upper bound out
  HALT
```

Thirty-six instructions, sixteen format-width constants,
`max_deposits` = 2 - an 832-byte image at binary256. `r0` arrives from
the `a` stream as the evaluation point; `r1` and `r2` arrive from `b`
and `c` as the incoming interval, and are `+0` on the first chunk
because a caller may pass NULL. The loader's rules are satisfied
without effort: there is no loop, so `HALT` is at the top level by
construction, every field an instruction does not read is zero, and the
worst-case instruction count is thirty-six.

The RTL was benched for this before the application existed:
`tb/test_seq_core.py`'s `constants_and_rounding` runs adjacent RDN and
RUP FMAs against the model and asserts up front that the two bounds
*differ*, because "the interval pattern is the reason the attribute is
per instruction rather than per run: one pass produces both bounds".
This tool is the first application of that pattern rather than the
first use of the encoding.

**No `REPEAT`, and no `SETACT`.** Horner has nothing to converge to:
every lane runs every step, so there is no early exit to be had and
nothing for the active mask to do. That is worth recording beside the
Collatz explorer, which is all escape masking - the two workloads
exercise opposite halves of the same ISA.

### The wall this workload hit: sixteen constants

A sequencer instruction names its operands in **four-bit fields**
(`rd` at 11:8, `ra` at 15:12, `rb` at 19:16, `rc` at 23:20), and the
`ka`/`kb`/`kc` bits redirect those same fields at the constant bank. So
**a program can address exactly sixteen constants, whatever `n_consts`
in its header says.** `host/src/program.c`'s validator agrees: it
refuses a constant index at or above `n_consts`, and the index can
never exceed 15.

An interval coefficient costs two constants. One program therefore
holds eight of them and no more, which is why the Horner kernel is
compiled into `ceil((d+1)/8)` chunk programs rather than one, and why
`--degree` refuses anything that does not make `degree + 1` a multiple
of eight. The chunking is not a hardship - the deposits of one call are
the `b` and `c` streams of the next, the same pattern
`docs/COLLATZ.md` uses to resume a trajectory mid-orbit - but the
ceiling is a real limit on any table-driven program, and it is the one
observation this workload has for the sequencer's designers:

> **A wider constant index, or an indexed constant fetch, is what a
> polynomial wants.** Sixteen constants is eight interval coefficients,
> or sixteen point ones. Every table-driven kernel - a polynomial
> approximation, a lookup-and-refine, a fixed filter - is chunked at
> that boundary and pays a memory round trip per chunk. The `imm` field
> is already 32 bits wide and is unused by ALU instructions; a
> `ka`-with-`imm`-index form would cost no encoding space at all.

Two smaller notes on the same subject, both consistent with what
`docs/COLLATZ.md` recorded:

- **A program has three input streams and no fourth.** Here that is
  exactly enough - point, lower bound, upper bound - and it is exactly
  enough by luck rather than by design. An interval Horner over an
  interval `x` rather than a point would need four.
- **Composed operations are not in the ISA.** The series kernel divides,
  and `cft_div` is a host-orchestrated seed-and-Newton sequence, so a
  program cannot issue one. (The library already issues that sequence
  *as* a program; what is missing is a way for one program to call
  another.) The workaround - a bank of precomputed `1/k` enclosures -
  runs straight into the sixteen-constant ceiling above.
- **A reduction crosses lanes**, so the dot kernel can never be a
  program, and should not be: `cft_reduce`'s index-fixed tree is what
  makes its answer reproducible, and P2 of `docs/SEQUENCER.md`
  addresses every deposit by the lane's own index precisely so that
  nothing crosses lanes.

So `--engine program|loop` selects the engine for the **Horner** kernel,
which is the only one that has two. `--engine loop` issues the identical
steps as four `cft_run` passes per Horner step from the host. The two
must agree bit for bit, and the cross-check holds them to it at two
different batch sizes and two formats.

---

## Which flags are EXPECTED and which are CERTIFICATES

Every operation goes through the library and every flag word is read.

**EXPECTED - inexact.** Under a directed attribute `inexact` means *the
bound is strict on that side*. It is the normal, useful case, never
treated as an error, and never allowed to stand in for a certificate.

**EXPECTED - underflow**, in the series kernel at a narrow format. The
terms are `x^k/k!`, so a small `x` reaches the subnormal range; at
binary32 an `x` of `2^-11` gets there by the tenth term and the run
comes back with `flags seen 0x18`. That is tininess, not error, and it
costs the enclosure nothing: a directed rounding of a subnormal is
still correctly rounded, so the lower chain stays below the true term
(it may reach `+0`, which is still below) and the upper chain stays
above it - `roundTowardPositive` can never carry a positive value to
`+0`, so the tail bound survives. The tool prints the reason beside the
flag rather than tolerating it silently, and the cross-check runs
binary32 at 2048 points on purpose to exercise it.

**FORBIDDEN - invalid, divideByZero, overflow.** No operand is ever a
NaN, no divisor is ever zero, and the dot kernel's largest product is
checked against the format's range before any work starts. Any of them
means the tool is wrong, so the tool stops with exit 3.

**CERTIFICATES**, in increasing order of strength:

| certificate | what it proves | where |
|---|---|---|
| `lo <= hi`, per element, in the library's own arithmetic | the interval is an interval | every emitted enclosure |
| `lo == hi` | the true value is exactly representable and BOTH bounds are it - a theorem, since `lo <= v <= hi` | per element |
| a clean flag word on a paired call | no rounding on either side, so both chains evaluated the exact value and every element's width is zero | asserted on every paired call |
| the per-item flag word | which SIDE was exact | the dot kernel only |
| containment against the oracle | the bound is a bound | `enclose_check.py` |

Two honest limits, both stated rather than papered over:

- **The converse of `lo == hi` is not a theorem** and is not claimed. A
  rounding smaller than the final ulp can vanish; what the tool asserts
  is the direction that holds.
- **The union problem `docs/COLLATZ.md` records applies here too.** A
  call over a batch reports the OR of its elements' flags, so for the
  series and Horner kernels the per-item side-exactness cannot be read
  off the flag word at any batch size above one. It is therefore **not
  recorded for them at all**, rather than recorded at a value that
  depends on the batch size - because everything this tool writes down
  has to be batch-size independent. The dot kernel is the exception,
  and not by accident: a reduction takes one vector, so its two calls
  are per item whatever `--batch` says, and there the flag word is a
  per-item certificate. At binary256 seven of the fifteen lower bounds
  and seven of the fifteen upper bounds come back certified exact; at
  binary64, one and one.

Beside all that, the tool uses ABI 0.7's status word (754-2019 7.1) as
a free cross-check, exactly as the Collatz explorer does: setup
deliberately raises inexact (measuring p does, and so do the
coefficient enclosures), the tool lowers the word once with
`cft_lower_flags` when setup is done - 7.1's "lowered only at the
user's request" - and the report prints it beside the union of the
calls' own `flags_out`. Printing a decimal raises inexact and is not
arithmetic, so `val_to_dec` saves the word with `cft_save_all_flags`
and puts it back with `cft_restore_flags` - which is what 5.7.4
provides them for, and without it the cross-check would be measuring
the printing.

---

## The checkpoint format

A line-oriented ASCII file with LF endings, written to `<path>.tmp`,
flushed, closed and then **renamed over** the target
(`MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` on Windows, `rename()`
elsewhere), so a reader never sees a half-written one.

It carries every number that describes a **result** and nothing that
describes the **machine**: no batch size, no engine, no timing. That is
the whole design rule, and it is what lets two runs with different
batch sizes and different engines end on byte-identical files.

```
cft-enclose-checkpoint 1
format fp256
kernels 111                   which of series,dot,horner are enabled
points 64                     the workload's shape - these define the
degree 23                       ITEMS, so they belong here
dotm 32
cond 60 225 6                 --dot-top, --cond-max, --cond-levels
rows 8
terms 54                      derived from p; carried as a cross-check
cursor 145                    items whose records are in the chain
items 145
kernel series 65 1 0x1.a8p-230 46      n, n_exact, widest width, its item
kernel dot 15 7 0x1.8p-175 13
kernel horner 65 1 0x1p-234 57
dotsides 7 7 0                lower/upper bounds certified exact, straddles
e 0x1.5bf0a8b1...272p+1 0x1.5bf0a8b1...2a7p+1
chain 79f876f17294b03b...     SHA-256 chain over the records so far
inflight 0 54                 items part way through the series, and the term
end
```

and when a stop lands **inside** the series recurrence, the in-flight
block carries the partial state, four values per item:

```
inflight 8 3
run <t_lo> <t_hi> <s_lo> <s_hi>       ...one line per item in flight
```

The evaluation point is *not* stored: it is a function of the item
index, so it is recomputed on resume rather than carried, which is one
fewer thing that can disagree.

**Values are hexadecimal**, produced by `cft_to_hex_char` - 5.12.3's
shortest sequence that represents the value exactly - and read back by
`cft_from_hex_char`, which refuses anything the format cannot hold
exactly. What the library writes, the library reads back, so a
checkpoint round trip cannot lose a bit. Hexadecimal rather than the
Collatz explorer's decimal because these values are not integers: the
exact decimal of a binary256 number near `2^-235` is 240 characters and
the hexadecimal is 75.

The **hash chain** is

    chain_0     = 32 zero bytes
    chain_(i+1) = SHA-256( chain_i || record_i || "\n" )

over records in **item order**, where a record is

    <kernel> <item> <lo> <hi> <width> exact|strict

`--records PATH` writes exactly those lines, so the chain can be
recomputed by anything; `host/tests/enclose_check.py` recomputes it with
`hashlib`, which is what proves the tool's derivation of SHA-256's
round constants from the cube roots of the first sixty-four primes
right. That file is truncated at the start of each run and is not
resume-aware - the checkpoint's chain is the thing that spans an
interruption.

The **width** is `RUP(hi - lo)`, so the number reported is itself an
upper bound on the true width. It is in the chained record because it
is a result; the straddle flag, the per-side flag certificates and the
CSV's decimal columns are not, because they are either derivable or -
for the point kernels - not available per item.

---

## Determinism, and how it is tested

| property | how |
|---|---|
| containment | every enclosure at fp256, fp64 and fp32 against exact `Fraction` arithmetic for the dot products and the polynomial, and mpmath at 300 digits for `exp` |
| coefficients | the interval coefficients must contain `1/k!` exactly - checked separately, so a failure says which claim broke |
| tightness | a valid but useless bound is a regression, so every width is held below a rounding budget: a few thousand ulps of the value for the point kernels, a few ulps per addition of the largest partial magnitude for the dot kernel, because a cancelling sum's answer is not the right scale to measure its width against |
| engines | the sequencer program and the host `cft_run` loop must produce byte-identical Horner records, at different batch sizes, at fp256 and fp64 |
| batch size | 7, 64 and 1024 over the same work must end on byte-identical checkpoints AND byte-identical record streams |
| interruption | a run stopped every four passes and resumed, at a different batch size, must end on the same checkpoint - byte for byte - as one that was never stopped, and the stops must land MID-ITEM |
| the chain | recomputed with `hashlib` |
| formats | fp256 against fp64 on provably identical input data |
| refusals | a degree the constant bank cannot hold, a point count that is not a power of two, a format whose exponent range cannot carry the ladder, an unknown kernel name |

The interrupt test uses `--stop-after-passes 4` against a 54-term
series so that a stop lands *inside* an item's recurrence, with partly
summed terms in flight: 40 of the 41 interruptions in the last run did.
A resume that only ever restarted on a batch boundary would be testing
the cursor and nothing else.

`make -C host enclosetest` on this tree: **2,658 comparisons, 0
failures.**

---

## Measured throughput

Software backend, single thread, on DESKTOP-T33SK86 (Windows 11,
MINGW64, `gcc -O2`), 2026-09-04. The command for one row is

```
./cft-enclose --format fp256 --points 2048 --batch 256 --summary-csv
```

with `--format` varied. Every row covers 4,113 enclosures except
binary32, which runs `--kernels series,horner` (4,098) because it
cannot express the dot ladder.

| format | enclosures/s | element-ops/s | element ops | library calls | seconds |
|---|---|---|---|---|---|
| fp256 | 1,821 | 389,150 | 879,063 | 2,991 | 2.259 |
| fp128 | 5,097 | 738,901 | 596,301 | 1,749 | 0.807 |
| fp64 | 11,660 | 1,237,434 | 436,479 | 1,047 | 0.353 |
| fp32 | 25,441 | 2,086,129 | 336,036 | 585 | 0.161 |

An *enclosure* is one item with **both** bounds computed, which is the
workload's natural unit. An *element-operation* is one element handed
to one library entry point: a `cft_div` counts as one there, though the
library composes it out of about 25 to 30 opcode passes, so the fp256
element-op rate is a floor on the opcode rate rather than an estimate
of it.

**Throughput is flat in the batch size.** At fp256 and 2,048 points:

| batch | enclosures/s | library calls |
|---|---|---|
| 64 | 1,880 | 10,887 |
| 256 | 1,821 | 2,991 |
| 1,024 | 1,669 | 1,017 |
| 4,096 | 1,897 | 359 |

That is a 13% spread with no trend, which is measurement noise on this
host, and all four runs return the same chain,
`2a4f7fa58560dac13b59879406d914768db27531c9829a23cd50dffcf6cf5ade`.

**The Horner kernel alone, program against loop**, 8,193 enclosures at
`--batch 512`:

| format | engine | enclosures/s | library calls |
|---|---|---|---|
| fp256 | program | 48,502 | 51 |
| fp256 | loop | 34,505 | 1,649 |
| fp64 | program | 79,992 | 51 |
| fp64 | loop | 67,055 | 1,649 |

**1.19x to 1.41x, on the software backend, where there is no bus and no
round trip to save.** What it saves is the per-call dispatch, the
format steering and the buffer walk that `cft_run` performs four times
per Horner step; the program does the same arithmetic inside one call
per chunk. Fifty-one library calls for 8,193 interval polynomial
evaluations is the sequencer's contribution stated as a number. The
gain is smaller than the Collatz explorer's 1.5x-2.1x for a plain
reason: a Horner step is four opcodes against that workload's
twenty-three, so there is less per-call overhead per unit of work to
remove. Both engines return the same chain,
`76cdb182bae8c7a835942d5352be851c9a9a508846f20d82a1e6077bec9a20e6` at
fp256.

**Where the time goes.** The series kernel is essentially all of an
fp256 run: on its own it takes 2.378 s for 2,049 enclosures (862/s)
against 2.259 s for all three kernels together, the difference being
run-to-run noise on this host. Each of its 54 terms costs two
correctly-rounded divisions per side, and a division is 25-30 FMA
passes. The dot kernel is 15 items and takes 2.6 ms; the Horner kernel
at 2,049 points takes about 40 ms. This is a
deliberately un-optimised shape: the host code is not tuned around the
library, and the divisions are not hoisted or replaced with a
reciprocal table, because the point is to price the contract's own
operations.

### The sweep that was run

```
./cft-enclose --format fp256 --points 16384 --batch 512 \
              --checkpoint run.ckpt --checkpoint-interval 30 \
              --csv run.csv
```

20.081 s, 2026-09-04, same host:

| | |
|---|---|
| enclosures | 32,785 (16,385 series, 15 dot, 16,385 Horner) |
| exact | 9 - both bounds ARE the value |
| widest series width | 9.59902e-70 |
| widest Horner width | 3.62228e-71 |
| widest dot width | 3.13215e-53, on a matrix row |
| dot enclosures straddling zero | **0** |
| element ops | 7,014,871 |
| library calls | 10,887 |
| flags seen | 0x10 - inexact only |
| status word | 0x10, agreeing with the union |
| throughput | 1,633 enclosures/s, 349,323 element-ops/s |
| chain | `573609c0a0befe28f576dbd2cef79cf0bb16c6477ed8b39aae1fae5870e83c7e` |

The same command at `--format fp64` takes 3.264 s and returns chain
`cdead7ef4138b108ca7c7f175577ea3bcae46b229e191b5eb66d678e39cd06a8`,
with **14 of its 15 dot enclosures straddling zero**.

---

## fp64 against fp256: the numbers

### e, computed as a series with a rigorous tail

| format | terms | enclosure of e | width |
|---|---|---|---|
| fp32 | 10 | [2.71828103065490722656250, 2.71828317642211914062500] | 2.1e-6 |
| fp64 | 18 | [2.71828182845904109399270, 2.71828182845904864350928] | 7.5e-15 |
| fp128 | 31 | [2.71828182845904523536028, 2.71828182845904523536029] | 1.2e-32 |
| fp256 | 54 | [2.71828182845904523536028, 2.71828182845904523536029] | **9.6e-70** |

The true value is `2.718281828459045235360287471352662497757...`; every
row above contains it, and the fp256 row pins it to 69 decimal digits.
The width scales with the format's precision as it should: about 53
ulps at binary256, 17 at binary64 - roughly one ulp per division, which
is what a chain of `2N` directed roundings costs.

### The widest width in each kernel, same 2,048 points

| kernel | fp64 | fp128 | fp256 | fp64/fp256 |
|---|---|---|---|---|
| series | 7.99e-15 | 1.16e-32 | 9.60e-70 | 2^182 |
| horner | 8.88e-16 | 7.70e-34 | 3.62e-71 | 2^184 |
| dot | 2.18e+3 | 1.55e-15 | 3.13e-53 | 2^186 |

### The ill-conditioned dot products, where fp64 has nothing left

Every one of these has the exact value **1**, and a condition number of
about 2^60 to 2^66.

| case | fp64 enclosure | fp128 | fp256 |
|---|---|---|---|
| `exact` | [68, 68] | [68, 68] | [68, 68] |
| `cancel-spread0` | [-0, 256] | [1, 1] | [1, 1] |
| `cancel-spread45` | [-192, 448] | [1, 1] | [1, 1] |
| `cancel-spread90` | [-768, 512] | [1, 1] | [1, 1] |
| `cancel-spread135` | [-704, 704] | width 7.8e-16 | [1, 1] |
| `cancel-spread180` | [-448, 384] | width 5.6e-16 | [1, 1] |
| `cancel-spread225` | [-742.82, 793.19] | width 1.0e-15 | width 2.1e-53 |
| `matvec-row2` | [-1152, 1024] | width 1.1e-15 | width 1.0e-53 |

**binary64's answer is not wrong. It is honest, and it is useless.**
The interval genuinely contains 1; it also contains 0, -700 and +700,
so it does not determine the sign of the answer, let alone its
magnitude. Fourteen of the fifteen are like that. A non-interval
binary64 dot product on the same data would print a single number
somewhere in that range with no indication that anything was wrong,
which is exactly the failure this workload exists to make visible.

binary256 returns **the exact rational, with the flag word clean, on
six of the fourteen** - both bounds are the value, and the certificate
is the absence of `inexact` rather than an argument. On the rest the
width is around 1e-53 against an answer of 1: 52 correct decimal
digits, proven.

**And that is where fp256 buys something.** It is worth saying plainly,
because this document would be worth less if it did not: on the two
point kernels the fp64 enclosures are perfectly usable - 7.5e-15 for e
is fifteen good digits - and a reader who needs fifteen digits should
use binary64 and enjoy the 6.4x throughput. What binary256 buys is the
regime where the *conditioning* rather than the *answer* sets the
precision needed, and the dot ladder is that regime: 2^60 of
cancellation eats binary64's whole significand before the first correct
bit appears.

---

## The negative control

Two deliberate faults, each rebuilt and run through
`make -C host enclosetest`, then restored.

### A: the upper bound stops being an upper bound

`CFT_RUP` changed to `CFT_RDN` on the Horner kernel's upper-bound FMA -
**in both engines**, so that nothing internal can notice a
disagreement. The tool then reports:

```
  horner        9 enclosures, 9 exact (both bounds ARE the value)
                widest 0 at item 0
```

Every internal gate passes, and each of them for a good reason. `lo <=
hi` holds, because both chains now round the same way and the upper one
still starts from the larger coefficient. The two engines agree,
because both were sabotaged. The batch-size property, the resume
property, the chain and every refusal are untouched. And the flag/width
certificate is *satisfied*: the widths really are zero.

The tool is now claiming that every value it computed is exactly
representable and that both of its bounds are that value. It is a
confident, self-consistent, entirely wrong answer.

The oracle catches it, on the containment rows alone:

```
  ok   fp256 all: all 24 interval coefficients contain 1/k! exactly
  FAIL: fp256 all: horner item 0 does not contain the true value
        (lo 0.36787944117144233, hi 0.36787944117144233)
  ...
  ok   fp256: the sequencer program and the host cft_run loop produce
       byte-identical Horner records, at different batch sizes
  ok   fp256: batches 7, 64, 1024 end on byte-identical checkpoints
  ok   fp256: a run stopped and resumed 41 times ... ends on the same
       checkpoint - byte for byte - as one that was never stopped

  2658 comparisons, 245 failures
```

245 failures, every one of them a containment row.

### B: the two attributes swapped

`cft_reduce`'s RDN and RUP exchanged in the dot kernel, so the "lower"
bound is computed under `roundTowardPositive`. This one never reaches
an oracle:

```
cft-enclose: an enclosure came back with its ends the wrong way round -
             a rounding attribute is wrong
```

The internal `lo <= hi` gate fires on the first ill-conditioned item,
exit 2, before a single record is written. The harness reports it as a
result rather than a crash, five rows at once:

```
  FAIL: fp256 all: the tool refused to finish - ...ends the wrong way round
  FAIL: check_batch_independence: the tool refused to finish - ...
  2307 comparisons, 5 failures
```

### What the oracle catches that the internal checks cannot

Plainly: **the direction of a bound.**

Every internal check in this tool is a consistency check. `lo <= hi`
says the two ends are ordered. The flag/width implication says a clean
flag word and a nonzero width cannot coexist. Program-versus-loop says
two implementations of the same recipe agree. Batch-size independence
and resume equivalence say the schedule does not reach the answer. All
five are necessary, all five are cheap, and all five are satisfied by
control A, because control A does not make the tool *inconsistent* - it
makes it consistently compute the wrong thing.

Only an independent computation of the true value can tell you that an
interval does not contain it. That is why `enclose_check.py` computes
in exact rationals and at 300 digits rather than by rerunning the
library, and it is why the oracle is the authority on the domain even
though the library is the authority on arithmetic.

Restoring the file, rebuilding, and the gate is green again at **2,658
comparisons, 0 failures.**

---

## What a device run would change

The same binary, given an `--artifact` path, opens the tile instead of
the software backend and issues the identical program.

- **Not the bits.** The chain would be identical, which is the point of
  the exercise. `--engine program` and `--engine loop` would still have
  to agree with each other and with the software backend, and an
  enclosure computed on the card would be the same interval as one
  computed on a laptop - not an overlapping one.
- **The arithmetic intensity, a little.** A Horner chunk is 33
  arithmetic instructions per lane against five element transfers -
  three stream loads and two deposits - so about 7 operations per
  element moved. That is below `docs/SEQUENCER.md`'s K ~ 30 crossover,
  so this kernel would still be partly memory-bound on a device. Raising `--degree` raises
  the chunk count rather than the work per chunk, because of the
  sixteen-constant ceiling; a wider constant index would raise K
  directly.
- **Not the series kernel's shape.** Its divisions already run as
  sequencer programs *inside the library* on a program-capable device
  (`docs/SEQUENCER.md`, "the first customer"), so a device run would
  accelerate the kernel without the tool changing a line.
- **The lane count.** A tile issues one beat per cycle - eight fp32
  lanes or one fp256 lane - and the pipeline is fifteen stages deep with
  no stall path, so a batch below `15 * lanes_per_beat` runs at pipeline
  speed rather than throughput speed. `--batch 512` is comfortably above
  that at every format.
- **What would not be measured honestly.** Numbers from `hw_emu` are RTL
  simulation seconds and mean nothing as hardware performance;
  `docs/BRINGUP.md` owns those gates. No device number is quoted here
  because no device has run this.

---

## What this does not do

- **It is not an interval arithmetic library.** It is three kernels
  written directly against `libcft`. A general interval type would want
  1788-2015's operations - division by an interval containing zero,
  intersection, hull, the decorations - and none of that is here.
- **It does not tighten anything.** No mean-value form, no Taylor
  model, no bisection. The widths above are what naive interval
  arithmetic gives on this contract, which is the number worth
  publishing: it is a floor that any smarter method is measured
  against, and it is reproducible.
- **The series kernel encloses `exp`, and the Horner kernel does not.**
  Horner's target is the *polynomial* `T_23(x)`, whose exact value at a
  dyadic point is a rational; the two are deliberately different so
  that one oracle is mpmath and the other is exact arithmetic.
- **binary32 cannot run the dot kernel**, for the exponent-range reason
  above. It is refused, not approximated.
- **No device has run it.** Everything above is the software backend.
