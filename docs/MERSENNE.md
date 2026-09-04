# The Mersenne verifier

`host/tools/mersenne.c`, built by `make -C host mersenne`, runs the
Lucas-Lehmer test

    s_0 = 4,   s_{k+1} = s_k^2 - 2   (mod 2^P - 1)

and reports that 2^P - 1 is prime exactly when s_{P-2} = 0.
`host/tests/mersenne_check.py` scores it against a Python big-integer
oracle; `make -C host mersennetest` runs that.

It is here because it is the workload where fp256's **width** is the
whole story, and because it inverts the usual relationship between a
floating-point program and its correctness proof:

1. **The exactness is a flag, not an error analysis.** A squaring is a
   convolution of limbs; `cft_reduce(CFT_DOT)` *is* that convolution;
   and while every partial sum of its contractual tree stays below
   2^237, no node rounds and the reduction raises nothing. `flags == 0`
   over a coefficient is therefore a certificate, issued by the library,
   that the coefficient is the exact integer sum.
2. **fp256 is not merely more exact here - it is faster.** The limb
   width is bounded by half the significand, the limb count is P/b, and
   the work is L^2 limb products per squaring, so a wider format does
   quadratically less work. Measured below: fp256 does the same
   verification in **1/22 to 1/29 of the limb products, and 1/7 to
   1/13 of the wall time**, that fp64 needs - and the ratio grows with
   the exponent.
3. **A residue is reproducible rather than repeated.** The record is
   the exponent, the verdict, the squaring count and res64 - the low 64
   bits of the canonical residue, which is the number every other
   Lucas-Lehmer implementation reports. fp32, fp64, fp128 and fp256
   return the **same chain** even though their limb geometries have
   nothing in common.

**This is not a record attempt, and the arithmetic of the gap is at the
end of this file.** It is a verifier of known Mersenne primes of modest
size, and a benchmark of the exact-integer regime.

---

## The exactness argument

### The bound, derived rather than chosen

Everything below comes from p, the format's significand width, which
the tool measures from the library rather than tabulating: the smallest
k for which `2^k + 1` raises `inexact`. Three bounds then fix the limb
geometry, and `geometry_derive()` is the only place in the tool that
decides how wide a limb is.

| | bound | why |
|---|---|---|
| **B1** | `2b <= p` | a product of two b-bit limbs is under 2^(2b), and every integer in [0, 2^p] is exactly representable, so the product never rounds |
| **B2** | `L * 2^(2b) <= 2^p` | a convolution coefficient is a sum of at most L such products. Every partial sum of the contractual tree is at most the total, so if the total is representable, **no node of the tree rounds** |
| **B3** | `d + 2 <= b` | after one carry pass a coefficient is under `2^b + 2^(p-b)`; the fold multiplies the high half by 2^d and adds, so the result is under `2^(p-b+d+2)`, and B1 makes `2^b <= 2^(p-b)` |

with `L = ceil(P/b)` limbs and `d = L*b - P` the fold's shift.

Work is `L^2` limb products per squaring, so the tool scans L upward
and takes the first that fits. For a given L the **narrowest** width
`b = ceil(P/L)` is both the most feasible - every one of B1, B2 and B3
gets easier as b shrinks, B3 because `d + 2 <= b` is `b*(L-1) <= P - 2`
- and the one with the smallest fold, so it is the only width worth
testing at each L.

At binary256 that lands on limbs of **102 to 116 bits**, not the 59 a
symmetric split of the significand would give. 59 bits would put half
the significand under the product and half under the accumulation
count, which is a fine rule of thumb and about four times more work
than the bound actually requires: at P = 11213, b = 115 needs 98 limbs
and 9,604 limb products a squaring where b = 59 needs 191 limbs and
36,481. The bound is measured, so the tool takes what it allows.

`--limb N` overrides the derivation and is **refused** unless the bound
allows it; `--limb N --unsafe-limb` forces it past the refusal, and
then the library's `inexact` is what stops the run. The cross-check
exercises both, because they are different mechanisms and a tool that
confused them would be reporting its own opinion rather than the
library's.

### The modulus is free, and so is the subtraction

The residue is L limbs of b bits, limb k weighing 2^(k*b), so it holds
a value under 2^(L*b) - which is **wider** than 2^P, by d bits. That
slack is the trick. Since

    2^P == 1   (mod 2^P - 1)      =>   2^(L*b) == 2^d

folding the high half of a product onto the low half is a multiply by
2^d: a power of two, and therefore exact at every format and every
magnitude. There is no division and nothing crosses a limb boundary.

Subtracting the 2 of the recurrence is an addition for the same reason:
`-2 == 2^P - 3 (mod 2^P - 1)`, and 2^P - 3 is a fixed vector of limbs
(every limb full, the top one only `b - d` wide, limb 0 short by two).
Adding it rather than subtracting keeps **every limb of every
intermediate non-negative**, which is what lets the carry split below
read encodings instead of handling signs.

The residue is reduced to the unique representative in [0, 2^P - 2]
after every squaring, so what the checkpoint carries and what the
oracle compares is one number rather than one of many congruent
representations.

### Carry propagation without a rounding operation

A coefficient must be split: `v = hi * B + lo` with `0 <= lo < B`,
`B = 2^b`. The two obvious ways to take the integer part are both
wrong, for exactly the reasons `docs/COLLATZ.md` gives for the same
choice:

| route | correct? | why not |
|---|---|---|
| the magic constant `(x + 2^(p-1)) - 2^(p-1)` | yes | it **raises `inexact` on every non-integer**, in the same run as the accumulation, and would flood the flag this tool uses as its certificate |
| `cft_rint(exact = 0)`, which never signals | yes | it is a **composed** host-side operation and so is not in the sequencer's opcode set; a step built on it could never become an on-chip program |
| the integer opcodes on the encoding | yes | chosen |

For a positive `t = 2^E * (1 + f)` with `0 <= E <= p-1`, the bits of
the significand below 2^0 are the low `(p-1) - E` of the encoding, so

    trunc(t) = (bits(t) >> s) << s,   s = (p-1) + bias - biased_exp(t)

and `s` comes from `t`'s own encoding by `ISHR` and `ISUB`. Four quiet
integer opcodes, no rounding, no flag, all of them in the sequencer's
set. `t < 1` has no integer part and is the one case the shift cannot
express - `s` would exceed `p-1`, and the shift is modulo the format
width - so a `CMPLT` against 1 and a `SELECT` say so explicitly. That
edge is not decoration: `t < 1` is `v < B`, which is most limbs most of
the time.

### The witness, and why a flag cannot replace it

**The integer opcodes are quiet by specification, so no exception flag
can ever say the split was wrong.** That is the whole reason for a
per-element witness. The same step computes, in the library's own
arithmetic and for the cost of one `NEG`, one `FMA` and four
predicates:

    recon = fma(hi, B, lo)
    ok    =  (recon == v)  and  (0 <= lo)  and  (lo < B)

`recon`'s true value is `v`, which is representable, so the fused
multiply-add rounds nothing and raises nothing. The host checks `ok` for
**every element of every pass** and stops with an error if one fails.

### The hole the witness leaves, and the gate that closes it

That witness does **not** pin `hi` down. `v = 3B/2` satisfies
`v == hi*B + lo` with `0 <= lo < B` at `(hi, lo) = (1, B/2)` and equally
at `(1.5, 0)`, and a shift amount that was off by one produces the
second - exactly, raising nothing, with the witness green. The error
then rides in the limbs, and the dot only notices when the extra
fractional bits push a coefficient past 2^p, which at `b = 105, L = 5`
they never do.

So once per squaring, over the L limbs that are the only state crossing
from one squaring to the next:

    (y + 2^(p-1)) - 2^(p-1) == y        <=>   y is an integer

which is the magic constant the carry split could not use, in the one
place where it is exactly the right instrument. A limb below 2^b is far
below 2^(p-1), so the addition is exact **if and only if** the limb is
an integer - the `inexact` it would raise is not noise to be masked, it
*is* the answer, and a correct run raises nothing here either. Three
elementwise passes over L limbs per squaring: +3.7% of the elementwise
issues at P = 3217, inside the timing noise.

This gate was written because the negative controls found the hole;
control B below is it.

### Which flags are expected, and which are certificates

EXPECTED, exactly twice, and both outside the computation:

- measuring p asks the library for the smallest k with `2^k + 1`
  inexact, which raises `inexact` on purpose. The status word is
  lowered once with `cft_lower_flags` when setup is done -
  754-2019 7.1's "lowered only at the user's request" - and never
  touched again;
- `--selftest` builds an accumulation that crosses 2^p on purpose and
  requires `inexact` to be raised.

CERTIFICATES, everywhere else. Every call a Lucas-Lehmer step issues
must raise **nothing at all**:

| call | operation | what a flag would mean |
|---|---|---|
| `cft_reduce(CFT_DOT)`, 2L-1 per squaring | a convolution coefficient | `inexact`: the accumulation left the exact range - B2 is violated and the residue is refused |
| `cft_run(CFT_ADD)` | the `-2`, the carry add, the fold | the value bound is wrong |
| `cft_run(CFT_MUL)` | the fold's scale by 2^d | a power-of-two multiply rounded, which cannot happen |
| the split, program or loop | `MUL`, four integer opcodes, `CMPLT`, `SELECT`, `FMA`, and the witness | the derivation above is wrong |
| the integrality gate, once per squaring | `(y + 2^(p-1)) - 2^(p-1)` | `inexact`: a limb is not an integer. Here the flag is not a by-product, it **is** the detector - see below |

Because the two expected sites are in setup and in a separate mode, no
expected flag can mask a certificate. The report prints the device
status word beside the union of the calls' `flags_out` as a second,
free check on that, and a clean run says

```
  flags seen     0x00
  status word    0x00 (agrees with the union above)
```

A dot that raises `inexact` is not an error to be recovered from: the
tool prints which phase raised what and exits 3. **The residue is
refused, not reported.**

---

## The step, as an instruction sequence

One Lucas-Lehmer squaring, `ll_step()`:

```
  yrev[k]  = y[L-1-k]                        ; a reversal - bytes, not arithmetic

  for k in 0 .. 2L-2:                        ; the linear convolution
      c[k] = DOT( &y[i0], &yrev[L-1-k+i0], len )     ; i0 = max(0, k-L+1)
                                                     ; len = min(k,L-1)-i0+1
  c[0..L-1] += limbs(2^P - 3)                ; the "- 2" of the recurrence

  one carry pass over c[0 .. 2L-1]           ; brings every coefficient
                                             ;   under 2^b + 2^(p-b)
  y[k] = c[k] + 2^d * c[k+L]   for k < L     ; the fold: 2^(L*b) == 2^d

  carry to convergence over y[0 .. L-1],     ; cyclically: the carry out of
      folding the top carry by 2^d           ;   the top limb re-enters limb 0

  reduce below 2^P, and map 2^P - 1 to 0     ; the canonical representative
  (y + 2^(p-1)) - 2^(p-1) == y   for all k   ; every limb is an integer
```

The dots are **slices**: `y` and its reversal are laid out so that the
k-th coefficient is a contiguous window of each, so the whole
convolution is 2L-1 calls with two offset pointers and no data
movement. The sum over k of the slice lengths is exactly `L^2`, which
is the number this tool reports as *limb products*.

And the carry split, which is what `--engine program` compiles into one
orbit-sequencer image (`docs/SEQUENCER.md`):

```
  MUL     r3  <- r0 * r1                ; t = v / B, exact: r1 is 2^-B
  ISHR    r4  <- r3 >> (p-1)            ; the biased exponent
  ISUB    r4  <- ((p-1)+bias) - r4      ; s = (p-1) - E
  ISHR    r5  <- r3 >> r4
  ISHL    r5  <- r5 << r4               ; trunc(t), valid for t >= 1
  CMPLT   r6  <- r3 < 1.0
  SELECT  r5  <- r6 ? 0.0 : r5          ; hi
  FMA     r7  <- r5*r2 + r0             ; lo = v - hi*B, exact: r2 is -B
  NEG     r8  <- -r2                    ; B
  FMA     r9  <- r5*r8 + r7             ; recon = hi*B + lo
  CMPEQ   r9  <- r9 == r0               ; the witness...
  CMPLT   r10 <- r7 < r8                ;   ...lo < B
  MIN     r9  <- r9 min r10
  CMPLE   r10 <- 0.0 <= r7              ;   ...0 <= lo
  MIN     r9  <- r9 min r10
  DEPOSIT r7                            ; lo
  DEPOSIT r5                            ; hi
  DEPOSIT r9                            ; the witness
  HALT
```

Nineteen instructions, **four** constants and three deposits. The base
`B` is not in the constant bank: `2^-B` arrives in `r1` and `-B` in
`r2`, the `b` and `c` streams, so this one program serves all three
bases the tool splits at - `2^b` while carrying, `2^(b-d)` when the
residue is reduced below 2^P, and `2^64` when res64 is read out. The
loader's rules are satisfied without effort: no loop, so `HALT` is at
the top level; every field an instruction does not read is zero; the
worst-case instruction count is 19.

`--engine loop` issues the same **fifteen** elementwise opcodes as
fifteen `cft_run` passes. The two must agree bit for bit, and the
cross-check holds them to that on the chain, on the checkpoint and on
every intermediate residue.

### What the program model could not hold, and why

**The convolution cannot be a program, and neither can the carry
chain.** This is the observation for the sequencer's designers, and it
is a different one from the Collatz tool's:

- a convolution coefficient is a **cross-element reduction**. A lane
  has sixteen private registers, three input streams and **no path to
  another lane** (`docs/SEQUENCER.md`), and `cft_reduce`'s tree is not
  in the sequencer's opcode set. Sixteen registers could hold sixteen
  limbs, but nothing can get limb *j* into lane *i*.
- the carry chain's shifted add reads the **neighbouring** element's
  carry. Same obstacle.

So the convolution is `cft_reduce`, whose tree shape the contract
fixes, and the shifted add is `cft_run` with an offset pointer. What
remains elementwise is the split, and that is what runs as a program:
one call per pass instead of fifteen.

Two things would change that, and both are cheap to state:

- **a lane shift**: an instruction that reads register *r* of lane
  *i-1* (or of lane *i* in the previous beat) would put the entire
  carry propagation on-chip as one program with a `REPEAT` and a
  `SETACT` on "this limb still has a carry" - which is exactly the
  early exit's shape, since carries die out after two or three passes
  and the last passes are almost all no-ops. It would turn five host
  calls per pass into one program call per squaring.
- **a cross-lane reduction** inside a program would put the convolution
  on-chip too, and then a whole Lucas-Lehmer step would be one call.

There is a partial workaround worth recording because it needs no
hardware: a program has three input streams, and the host may point two
of them at the **same array at different offsets**, so a lane can see
its neighbour's *input* even though it cannot see its neighbour's
registers. That buys one shifted operand per program, at the cost of
recomputing the neighbour's split; it is not used here because the
extra split costs more than the `cft_run` it saves, but on a device
where the call is a round trip it would not.

---

## The checkpoint format

Line-oriented ASCII with LF endings, written to `<path>.tmp`, flushed,
closed and then **renamed over** the target
(`MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` on Windows, `rename()`
elsewhere), so a reader never sees a half-written one.

It carries every number that describes a **result** and nothing that
describes the **machine**.

```
cft-mersenne-checkpoint 1
format fp256                    the format the run is in
limb 0                          0 = derived; a forced --limb is refused on resume
exponents 521,607,1277,...      the list, so a resume cannot change it
done 10                         results completed
result 521 prime 519 0000000000000000       <- one line each, in list order
result 1277 composite 1275 5613a480590e78ba
...
chain dff84a37...               SHA-256 chain over those records
squarings 24314                 total squarings performed
current 9689 2654               the exponent in progress and its step index
geom 114 85 1                   b, L, d - derived, and checked on resume
residue 85                      the residue, one exact decimal limb per line
20769187434139310514121985316880383
...
end
```

Limb values are decimal integers produced by `cft_to_decimal_char` with
`digits = 0` - 5.12.2's exact conversion - and read back by
`cft_from_decimal_char`, which refuses anything the format cannot hold
exactly. What the library writes, the library reads back.

The **hash chain** is

    chain_0     = 32 zero bytes
    chain_(i+1) = SHA-256( chain_i || record_i || "\n" )

over records in **exponent-list order**, where a record is

    <P> <prime|composite> <squarings> <res64 in hex>

That record mentions **no format and no limb geometry**, which is
deliberate: fp32, fp64, fp128 and fp256 therefore return the same
chain, and res64 is the number an unrelated Lucas-Lehmer implementation
would print. SHA-256's eight initial words and sixty-four round
constants are **derived** in the tool from the square and cube roots of
the first 64 primes by integer binary search, rather than typed in -
this repository's standing rule about constants - and the cross-check
recomputes the chain with Python's `hashlib`, which is what proves the
derivation right.

`--batch` does not appear in the file, and cannot: it is the number of
elements per **elementwise** call, and the tool chunks its passes by
it. The reduction lengths are not batched, because a dot's length is
the mathematics - the contract fixes the tree by index, so re-cutting
it would be a different sum, and the library's own multi-tile split
(which reproduces the cut levels) is the only re-cutting allowed.

---

## Determinism, and how it is tested

`host/tests/mersenne_check.py` tests these rather than asserting them.
The interesting one is the second: a Lucas-Lehmer verdict is one bit,
and one bit is easy to get right by accident, so the oracle compares
**whole intermediate residues** at every dump point - res64 plus a
SHA-256 over every canonical limb - and not just the answer.

| property | how |
|---|---|
| results | every verdict, squaring count and res64 against Python big integers, at fp256 and fp64, over Mersenne primes **and** the two composite controls |
| residues | every intermediate residue, whole, at fp256 (both engines), fp64 and fp32 - so a wrong carry shows at the first squaring that breaks it |
| engines | the sequencer program and the host `cft_run` loop must produce the same chain, the same checkpoint and the same residues |
| formats | fp32, fp64, fp128 and fp256 must produce the same chain |
| batch size | 3, 4096 and the host loop at 11 must end on byte-identical checkpoints |
| interruption | a run stopped mid-exponent and resumed at a different batch size must end on the same checkpoint - byte for byte - as one never stopped |
| the chain | recomputed with `hashlib` |
| the bound | the selftest's probes; a forbidden `--limb` refused before any arithmetic; `--unsafe-limb` stopped by the library's flag |
| the three internal gates | not directly, and they cannot be: a gate that never fires on correct input is only tested by breaking something. The three negative controls below are that test, one per gate |

The composite controls are the half that is easy to leave out. **1277
and 1619 are prime exponents whose Mersenne numbers are not prime** -
1277 is the smallest such with no known factor - so a tool that always
answered "prime" would pass a test set of Mersenne primes alone and
fail here. Their res64 values, `5613a480590e78ba` and
`3f964611757ce4e0`, are the fingerprints an unrelated implementation
would print.

The resume leg stops every 137 squarings on purpose, which is not a
multiple of any exponent's length, so every one of its interruptions
lands **inside** a Lucas-Lehmer sequence with a partial residue on
disk; a resume that only ever restarted between exponents would be
testing the cursor and nothing else.

---

## Measured

Software backend, single thread, on DESKTOP-T33SK86 (Windows 11,
MINGW64, `gcc -O2`), 2026-09-04. Other work shares this box, so
repeated runs of the same command land within about 5%; every ratio
below is large enough that the noise does not reach it.

### The whole known set

```
./cft-mersenne --set known --format fp256 --engine program --batch 4096 \
               --checkpoint run.ckpt --checkpoint-interval 30
```

**212.285 s**, and every verdict is right in both directions:

| P | b | L | d | squarings | limb products each | seconds | limb products/s | verdict |
|---|---|---|---|---|---|---|---|---|
| 521 | 105 | 5 | 4 | 519 | 25 | 0.049 | 266,670 | PRIME |
| 607 | 102 | 6 | 5 | 605 | 36 | 0.066 | 330,369 | PRIME |
| **1277** | 107 | 12 | 7 | 1275 | 144 | 0.304 | 603,028 | **COMPOSITE** |
| 1279 | 107 | 12 | 5 | 1277 | 144 | 0.337 | 544,978 | PRIME |
| **1619** | 116 | 14 | 5 | 1617 | 196 | 0.475 | 667,912 | **COMPOSITE** |
| 2203 | 116 | 19 | 1 | 2201 | 361 | 0.969 | 819,790 | PRIME |
| 2281 | 115 | 20 | 19 | 2279 | 400 | 1.097 | 830,843 | PRIME |
| 3217 | 115 | 28 | 3 | 3215 | 784 | 2.467 | 1,021,708 | PRIME |
| 4253 | 115 | 37 | 2 | 4251 | 1,369 | 5.068 | 1,148,400 | PRIME |
| 4423 | 114 | 39 | 23 | 4421 | 1,521 | 6.016 | 1,117,797 | PRIME |
| 9689 | 114 | 85 | 1 | 9687 | 7,225 | 52.687 | 1,328,391 | PRIME |
| 9941 | 115 | 87 | 64 | 9939 | 7,569 | 58.601 | 1,283,729 | PRIME |
| 11213 | 115 | 98 | 57 | 11211 | 9,604 | 84.125 | 1,279,881 | PRIME |

```
  squarings      52497
  limb products  270377166
  carry passes   304131
  elem op issues 280736311
  library calls  7484340
  flags seen     0x00
  status word    0x00 (agrees with the union above)
  time           212.285 s
  throughput     1273651 limb products/s, 247.295 squarings/s,
                 1322449 elementwise op issues/s
  chain          851b85d1e262b0f1e887f641f25bd684df1384d9c128e991646c3f9a18eed9cf
```

**270 million exact 115-bit limb products, and not one of them raised a
flag.** The two composite controls return the res64 values a
big-integer implementation returns - `5613a480590e78ba` for 2^1277 - 1
and `3f964611757ce4e0` for 2^1619 - 1 - so the verdict is checked in
both directions rather than only against a list of primes.

The rate **rises** with the exponent, from 267,000 limb products a
second at L = 5 to 1.28 million at L = 98, because a dot at L = 5 is a
call over five elements and the per-call cost dominates. That is the
same curve the sequencer exists to flatten, and it is flatter here than
it looks: the tool issues 2L-1 dots per squaring, so the SMALL
exponents are the ones paying for dispatch.

### fp256 against fp64, which is the point

The same exponent, the same tool, the same chain, at four rungs of the
ladder. The chain is format-independent by construction, so every row
of a block returns the same one.

**P = 1279** (chain `5f77f4df97259bc6441796bfbeffac242c799f86a87fbf93f60fd891add44e7c`):

| format | p | b | L | limb products | seconds | limb products/s | squarings/s |
|---|---|---|---|---|---|---|---|
| fp256 | 237 | 107 | 12 | 183,888 | 0.260 | 707,104 | 4,910 |
| fp128 | 113 | 54 | 24 | 735,552 | 0.603 | 1,220,590 | 2,119 |
| fp64 | 53 | 23 | 56 | 4,004,672 | 1.921 | 2,084,636 | 665 |
| fp32 | 24 | 8 | 160 | 32,691,200 | 13.014 | 2,512,037 | 98 |

**P = 2203** (chain `94b3ab60...`) and **P = 4423** (chain `3c2836d1...`):

| P | format | b | L | limb products | seconds |
|---|---|---|---|---|---|
| 2203 | fp256 | 116 | 19 | 794,561 | 0.943 |
| 2203 | fp128 | 53 | 42 | 3,882,564 | 2.460 |
| 2203 | fp64 | 23 | 96 | 20,284,416 | 10.130 |
| 4423 | fp256 | 114 | 39 | 6,724,341 | 5.924 |
| 4423 | fp64 | 21 | 211 | 196,827,341 | 75.033 |

So, as ratios of fp64 to fp256:

| P | limb products | wall time |
|---|---|---|
| 1279 | **21.8x** | **7.4x** |
| 2203 | **25.5x** | **10.7x** |
| 4423 | **29.3x** | **12.7x** |

and fp32 to fp256 at P = 1279 is **177.8x** the limb products and
**50.0x** the wall time.

Three things in those numbers:

- **The ratio is the square of the limb ratio, and it grows.** fp64's
  bound forces b down as L rises (23 bits at P = 1279, 21 at P = 4423)
  because `L * 2^(2b) <= 2^p` has to hold with a 53-bit significand,
  while fp256 sits comfortably at 114-116 the whole way. The width buys
  quadratically.
- **fp64 is faster per limb product and still much slower overall.**
  2.08 million a second against fp256's 0.71 million - softfloat does
  a 23-bit product in about a third the time of a 107-bit one - and it
  needs 21.8 times as many. A wider format is the cheaper way to buy
  exactness here, which is the opposite of the usual intuition.
- **fp64 is not WRONG, it is slow.** The limb width is derived from
  each format's own p, so every rung is exact and every rung returns
  the same chain. What fp64 loses is throughput, and what it would lose
  if it kept fp256's limb width is the certificate: `--format fp64
  --limb 107` is refused before any arithmetic, and
  `--format fp64 --limb 107 --unsafe-limb` runs until the library
  raises `inexact` and the residue is refused.

### The sequencer program against the host loop

Both engines issue **exactly** the same elementwise opcodes - the check
script confirms the counts are identical - and differ only in how many
library calls that takes.

| P | L | program s | loop s | program calls | loop calls | speedup |
|---|---|---|---|---|---|---|
| 607 | 6 | 0.064 | 0.065 | 14,536 | 65,244 | 1.02x |
| 1279 | 12 | 0.279 | 0.353 | 46,051 | 153,123 | 1.27x |
| 3217 | 28 | 2.461 | 2.635 | 218,054 | 479,756 | 1.07x |
| 9689 | 85 | 48.365 | 52.514 | 1,751,170 | 2,442,224 | 1.09x |

**1.02x to 1.27x**, where `docs/COLLATZ.md` measured 1.5x to 2.1x for
the same route on the same backend. The difference is honest and
structural rather than disappointing: in Collatz the program IS the
whole step, and here it is only the carry split. The convolution -
which cannot be a program at all, for the reason in the section above -
is where most of the time goes, and it is identical in both engines. On
a device the picture changes, because a call becomes a round trip;
that is the number the "what a device would change" section owns, and
it is not measured here.

### Throughput against batch size

`--batch` is the number of elements per elementwise call, so it can
never change a result and does not appear in the checkpoint. What it
changes is the call count, and only below the array length.

P = 9689, fp256, program:

| batch | library calls | seconds |
|---|---|---|
| 4 | 3,923,704 | 54.766 |
| 16 | 2,268,440 | 54.243 |
| 64 | 1,854,624 | 50.653 |
| 4096 | 1,751,170 | 51.656 |

Flat within the box's noise from batch 4 upward, even though batch 4
takes 2.2x the calls - which says the per-call cost is small beside a
dot at L = 85. Three consecutive runs of P = 3217 at batch 4096 gave
2.467, 2.554 and 2.432 s, which is the noise floor those numbers sit
on.

### The device-era exponents

`--set device` is 19937, 21701, 23209 and 44497, wired in with the
checkpoint so the tool can be left running and resumed rather than
waited on.

```
./cft-mersenne --set device --format fp256 --time 300 \
               --checkpoint dev.ckpt --checkpoint-interval 60
```

```
  P = 19937  b = 114  L = 175  d =  13  19935 squarings, 30625 limb products each
       stopped at squaring 14303 of 19935
  squarings      14303
  limb products  438029375
  library calls  5226490
  flags seen     0x00
  time           300.013 s
  throughput     1460033 limb products/s, 47.675 squarings/s
```

then `--resume` for sixty seconds more picks it up at 14,303 and
reaches 17,362 at 1,560,916 limb products a second, and a third
`--resume` finishes it:

```
  P = 19937  b = 114  L = 175  d =  13  19935 squarings, 30625 limb products each
       2^19937 - 1 is PRIME     res64 0000000000000000   53.200 s, 1481174 limb products/s
  flags seen     0x00
  status word    0x00 (agrees with the union above)
```

**2^19937 - 1 - the twenty-fourth Mersenne prime, 6,002 decimal
digits - verified across three separate invocations**, 19,935 squarings
and 610 million exact limb products in total, with the checkpoint
carrying the residue between them and not one flag raised. Python's
big integers agree, verdict and res64. The whole thing took about seven
minutes of wall clock across the three, and needed no more than a
minute of attention at a time; that is what the checkpoint is for.

21701, 23209 and 44497 have not been run. Their cost is `L^2 (P-2)`
with `L ~ P/114`, so 44497 is about (44497/19937)^3 = 11 times 19937's
work - roughly 80 minutes on this backend, and a few seconds on a card
that could hold the convolution on-chip. **That is what "device-era"
means here: not that the software backend cannot do them, but that
they are the sizes where the round trips start to matter more than the
arithmetic.**

### What a device run would change

The same binary, given an `--artifact` path, opens the tile instead of
the software backend and issues the identical program. What changes:

- **Not the bits.** The chain and every res64 would be identical, which
  is the point of the exercise. `--engine program` and `--engine loop`
  would still have to agree with each other and with the software
  backend.
- **The call count, which is this workload's real cost on a bus.** A
  squaring at L = 98 is 195 dot reductions and about a dozen
  elementwise calls; the whole known set took 7.48 million library
  calls. On a device each of those is a round trip, and the sequencer
  can only absorb the dozen. A cross-lane reduction inside a program,
  or a lane shift, is what would absorb the 195 - see the section
  above.
- **The lane count.** A tile issues one beat per cycle - one fp256 lane
  - and the pipeline is 15 stages deep with no stall path, so a call
  below 15 elements runs at pipeline speed rather than throughput
  speed. That is a real constraint here: a linear convolution's dots
  are 1, 2, 3, ... elements long at the ends, and at L = 12 most of
  them are under 15.
- **What would not be measured honestly.** Numbers from `hw_emu` are
  RTL simulation seconds and mean nothing as hardware performance;
  `docs/BRINGUP.md` owns those gates. No device number is quoted here
  because no device has run this.

---

## The negative control

Three deliberate faults, each rebuilt and run through
`make -C host mersennetest`. They are worth reading together, because
each is caught by a **different** one of the three gates and the third
is caught by none of them.

### A: the `t < 1` guard deleted from the carry split

The `CMPLT` against 1 and the `SELECT` were deleted from
`build_program()` and from the host loop, so the shift wraps for
`v < B` and `hi` comes back as a truncation of `t` rather than as 0.

Caught by the **flag word**, on the first squaring, in both engines and
at all four formats - and not by the witness, which is never reached:

```
FAIL: fp256, sequencer program: the tool refused to finish -
      cft-mersenne: the carry add raised 0x10 (inexact), and every
      operation of a Lucas-Lehmer step here is exact by construction -
      the residue is REFUSED, not reported
```

That is the honest ordering, and it is worth stating: for **this** bug
the flag is the faster detector, because a `hi` that is a fraction
makes `lo = fma(hi, -B, v)` inexact and `expect_clean` fires inside the
split before the witness is looked at. Twenty-one of the check's
twenty-two rows fail; only the four bound probes still pass, since they
never carry anything.

### B: the split's shift constant off by one

`(p-1) + bias` became `p + bias`, so `s` is one too large and the
truncation clears one bit too few. `hi` comes back as a **half-integer**
and everything stays exact: the witness passes, because
`v == hi*B + lo` and `0 <= lo < B` are all true of `(1.5, 0)` as well
as of `(1, B/2)`.

Caught by the **limb integrality gate**, which exists because writing
this control found the hole:

```
FAIL: fp256, sequencer program: the tool refused to finish -
      cft-mersenne: the limb integrality gate raised 0x10 (inexact) ...
```

Before that gate existed this control was invisible at small exponents:
at `b = 105, L = 5` the extra fractional bits leave a coefficient at
215 significant bits against the format's 237, so no dot ever rounds
and no flag is ever raised. The dot only notices at large `L`, which
is to say it notices where the geometry happens to be tight and not
where the bug is.

### C: the recurrence subtracts 1 instead of 2

`2^b - 3` in limb 0 of the constant vector became `2^b - 2`, so the
step is `s^2 - 1` rather than `s^2 - 2`. One character, and every
operation is still exact.

**Every internal gate stays green.** Flags `0x00`, status word `0x00`,
the witness satisfied on every element of every pass, the integrality
gate satisfied on every limb, both engines in exact agreement, all four
formats in exact agreement, batch-size independence holding, and
interrupt/resume landing on a byte-identical checkpoint. The tool
reports, with total confidence:

```
  2^521    - 1  COMPOSITE     519 squarings  res64 0000000000000002
```

which is wrong: 2^521 - 1 is prime. **Only the oracle catches it**, and
it catches it at the *first* squaring rather than at the verdict,
because the check compares whole intermediate residues:

```
FAIL: fp256 program, 2^1277 - 1: residue after squaring 1 differs -
      tool res64 ...0010 digest 6af2d37c, oracle res64 ...000e digest 8b392b1a
ok   the sequencer program and the host cft_run loop return the same chain
ok   fp128 / fp64 / fp32 and fp256 return the same chain
ok   batch 3, batch 4096 and the host loop at batch 11 end on byte-identical
     checkpoints
ok   a run stopped and resumed 11 times ... byte for byte
ok   not one operation of 2399 squarings raised a flag
```

So, plainly:

> The flag word certifies that no operation **rounded**. The witness
> certifies that the split **reconstructs**. The integrality gate
> certifies that a limb is an **integer**. None of the three certifies
> that the tool is computing the Lucas-Lehmer sequence, and control C
> is a tool that is exactly, reproducibly, deterministically computing
> the wrong recurrence. That is what the big-integer oracle is for, and
> why the cross-check compares residues rather than verdicts.

Restoring the file, rebuilding and re-running is green again:
**382 comparisons, 0 failures** at `--quick`, 388 at the default size.

---

## GIMPS, and the arithmetic of the gap

**This is not a record attempt, and it is not close to one.** The
arithmetic, done with this tool's own measured numbers rather than
asserted:

The cost model is exact. `L = ceil(P/b)` limbs with `b` near 115 at
binary256, `L^2` limb products per squaring, `P - 2` squarings, so

    limb products  =  L^2 * (P-2)  ~  P^3 / 115^2

which at P = 11213 predicts 1.066 x 10^8 against the 1.077 x 10^8 the
tool actually performed - the difference is the ceiling in `L`.

The largest known Mersenne prime exponent is above 10^8 (P = 136,279,841,
found in 2024). At that size this tool's geometry would be
L = 1,185,043 limbs, so

    limb products  =  1.185e6^2 * 1.363e8  =  1.91 x 10^20

and at the 1.46 x 10^6 limb products a second measured for P = 11213,

    1.91e20 / 1.46e6  =  1.31 x 10^14 s  =  4.2 million years

on one thread. GIMPS runs a primality test of that size in about a day
on one GPU, so the gap is **about 9 orders of magnitude against one
thread of this software backend**, and roughly 10 once the comparison
is made against the parallelism a real GIMPS client uses. It divides
into two parts, and only one of them is about hardware:

| | factor | what it is |
|---|---|---|
| algorithm | ~10^4.8 | a direct convolution is `L^2`; an FFT is about `L log2 L`. At L = 1.185e6 that ratio is `L / log2 L` = 58,700 |
| hardware | ~10^5 to 10^6 | 1.46 x 10^6 exact 115-bit limb products a second, single-threaded softfloat, against a GPU sustaining order 10^12 double-precision butterflies a second |

**The algorithmic half is the price of the certificate, and it is not
an oversight.** An FFT convolution's twiddle factors are roots of
unity, which are irrational, so a floating-point FFT is inexact by
construction - which is precisely why GIMPS needs Gerbicz error
checking during a run and an independent double-check afterwards. The
exact sub-quadratic route is Karatsuba or Toom-Cook, which are integer
identities and keep the certificate intact; at L = 1.185e6 Karatsuba's
`L^1.585` would be 330 times fewer limb products than `L^2`. That is
the obvious next thing to build here, and it is not built. The other
exact route is a number-theoretic transform, which is a different
machine: modular arithmetic, not IEEE 754.

The hardware half would not be closed by this project's tile either. A
tile issues one beat a cycle - one fp256 lane - so at 135 MHz it is
order 10^8 fp256 operations a second against this backend's ~10^6.2.
Two orders, not six.

### What the exactness actually buys, since it is not speed

- **The rounding class of error is gone, not bounded.** Gerbicz
  checking exists because an FFT's rounding error has to be kept below
  half an ulp of the integer result, and that is a property of the
  input data rather than of the code. Here the library says whether any
  rounding happened at all, per call, and a run that reports
  `flags 0x00` had none.
- **A re-run is a reproduction, not a second opinion.** A residue
  produced here is defined bit for bit by the contract
  (docs/DETERMINISM.md), so a conforming implementation on other
  hardware returns the *identical* res64 and the identical chain. That
  is a different thing from two approximate runs agreeing.
- **What it does NOT buy is immunity from hardware faults.** A bit flip
  in memory is not a rounding, and no exception flag will report it.
  For that the answer is still an independent run - but here that run
  is expected to agree exactly, which makes a disagreement a fault
  report rather than a puzzle.

### And what it does reach

The whole set of Mersenne prime exponents up to 11213 - eleven primes
and the two composite controls, 3,376 decimal digits at the top -
verifies in **212 seconds** on one thread, with every residue
reproducible bit for bit and the exactness carried by a flag. One rung
further, **2^19937 - 1 (6,002 digits) verifies in about seven minutes**
across three resumed invocations. 21701, 23209 and 44497 are wired in
and not run.

In exponent that is about four orders of magnitude below the record
(19,937 against 136,279,841). What it is *not* is small: the residues
are 6,002-digit integers, squared 19,935 times, and every one of those
squarings is exact by certificate rather than by argument.

---

## What this does not do

- **It does not find Mersenne primes.** It verifies known ones, and its
  contribution is that the verification is bit-reproducible and its
  exactness is a flag rather than an argument.
- **It has no FFT, and cannot have one.** An FFT convolution's twiddle
  factors are irrational, so a floating-point FFT is inexact by
  construction - which is the whole reason GIMPS needs Gerbicz checking
  and a second independent run. The exact sub-quadratic route is
  Karatsuba or Toom-Cook, which are exact integer identities and would
  reduce `L^2` to about `L^1.585` with no loss of the certificate. That
  is the obvious next thing to build here and is not built.
- **It has no `--limb` tuning by default and no assembly.** Every
  operation goes through `libcft`, one element at a time from the
  library's point of view; the tool never does arithmetic itself.
- **No device has run it.** Everything above is the software backend.
  The tool takes `--artifact` and issues the identical program either
  way, but nothing here has been through XRT; `docs/BRINGUP.md` owns
  those gates and no device number is quoted.
