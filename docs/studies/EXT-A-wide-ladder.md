# Study EXT-A: the ladder above binary256

STATUS: a design study, 2026-09-21. No RTL, no host code and no
golden-model code was changed to write it; `docs/README.md` gained this
file's row and had its stated totals brought up to date, and nothing
else moved. **Nothing here is a plan.** No
document in this tree asks for a format above binary256 and this one
does not either. It is a map of where the walls are, drawn while the
question was cheap to ask, so that nobody has to rediscover them on the
day it is not.

Every number below is one of three kinds and says which:

- **READ** - out of this tree, with the file it came from;
- **RUN** - produced by one of the four instruments in
  `docs/studies/ext-a/`, whose captured output sits beside it, so a
  figure here can be diffed against a re-run (section 11);
- **MODELLED** - extrapolated from the four formats that exist to
  formats nobody has built. `ext-a/model.py` prints every such table
  with the model's residuals against what was measured, and the text
  says where the model is a guess.

**Scope.** Three questions, asked in this order on one day.

1. How easily would what is here port to binary512, binary1024,
   binary2048 and beyond - the golden model, libcft, the RTL, the
   verification - and where does each stop?
2. With every cheap limit raised, exponent arithmetic widened past 32
   bits and the 135 MHz clock HELD, how high does the ladder climb
   before the next wall? And is the multi-pass multiplier the seed of a
   machine that scales the way MPFR does - on this card, on an ASIC, on
   a carrier of chiplets?
3. Both of those end up counting in "MPFR cores". What does that
   yardstick leave out, given that MPFR is not an implementation of an
   IEEE format and this contract is stricter than the standard wherever
   it can afford to be?

**The one thing to take away** if nothing else is read: precision is
not what limits this design. The exponent range is. IEEE 754 gives
binary*k* four more exponent bits at every doubling of *k*, so the range
grows sixteenfold a rung while the significand grows twofold - and
everything here that stops, stops on the exponent: a table, a
conversion, an `int`, a proof.

The formats throughout are the standard's own. 754-2019 clause 3.6
defines binary*k* for every *k* >= 128 that is a multiple of 32, with
`exp_w = round(4 log2 k) - 13` and `p = k - exp_w`, so binary512 is
(23, 489), binary1024 (27, 997), binary2048 (31, 2017), binary4096
(35, 4061). `python/cft_golden/formats.py` opens by saying the ladder is
"exactly the interchange ladder - no bfloat, no TF32, no vendor
variants", and nothing below needs that sentence to change.

---

## 0. The short answers

1. **There is no hard wall in the construction.** The unmodified golden
   model computes binary512 through binary8192 today: 25,445 arithmetic
   checks and 1,600 square roots in the interior, 8,765 more at the
   edges of the exponent range of binary256, binary512 and binary1024,
   all five attributes, **zero mismatches** against witnesses that
   share no code with it (RUN, section 1).
2. **What exists instead is a ring of deliberate refusals sized for
   "256 is the top rung"** - `$error` guards, `#error` gates, fail-closed
   switches - and nearly all of it is a number or a table row. The
   machinery that lets this project shrink to an ESP32 or a quarter
   tile is the same machinery that would grow it; it has only ever been
   exercised downward (section 2).
3. **The structural work is in data movement, not arithmetic.** The
   beat is the element is the memory width, the precision code is two
   bits with arithmetic done on it, and the sequencer builds only at a
   256-bit beat. The engine's own comment names the wall (section 2.3).
4. **binary2048 is where 32-bit exponent arithmetic dies, by 4,028**,
   in the RTL's `int` algebra and in `softfloat.c`'s `int e` on the same
   line of reasoning. libcft already carries the gate that would refuse
   it - written to keep binary128 off a 16-bit AVR (section 3).
5. **One thing found would not fail loudly, and one would fail
   silently.** `sq_emit` writes a square-root program image past a
   stack buffer at a 64-byte element; and `_pow_dyadic`'s exactness
   proof is scoped to exponents below 2^24, so at binary1024
   `pow(2^(2^25), 2^-25)` returns 2.0 with a spurious `inexact`. Neither
   is reachable today (section 9).
6. **Held at 135 MHz, the U50 tops out at binary2048** - one lane, 57%
   of the device. binary4096 lands at 100% and does not fit. A first
   pass of this study said otherwise and the correction is in section
   5.2.
7. **The tile's 5.5x and 21x are a win over MPFR's overhead, not over
   a CPU's multiplier.** MPFR's effective rate climbs tenfold from 256
   to 4096 bits as its bookkeeping amortises; a whole U50 with every
   DSP busy is about 22 of those cores and no ladder changes that. It
   is an ASIC argument, and the roadmap's own figures put it at two
   orders of magnitude a square millimetre (section 6).
8. **Density pays only for resident work, and a program runs on tile 0
   only.** The many-chiplet machine's next wall is already on the debts
   list, and it is software (section 6.6).
9. **Contract adherence does not rescue the throughput comparison at
   width - and it was never going to be where its value was.** The tax
   for making MPFR answer as an IEEE *format* is flat - 8 to 17 ns as
   measured here, 4 to 8 with the pinned MPFR in `docs/BENCHMARKS.md` -
   so it is at most 41% of a multiply at binary256 and below the noise
   at binary4096. What remains is semantic, no MPFR
   configuration reaches it, and it matters more at width, not less:
   the outside oracles thin out to one, the implementations multiply,
   and the contract is what lets a slow open chip vouch for a fast
   closed one (section 7).
10. **The contract also sends a bill, and width is where it comes
    due.** Full-range correctly rounded radian trigonometry needs
    2^(exp_w - 1) bits of 2/pi: 2 GiB at binary4096, and at binary65536
    more digits of pi than have ever been computed (section 7.5).

---

## 1. What was run

Four instruments, all in `docs/studies/ext-a/`, none wired into any
gate. Section 11 has the commands.

### 1.1 The golden model, unmodified, above the ladder

`ext-a/wide_golden.py` builds each wide format as one line -
`FpFormat("fp512", 23, 488)` - and scores `fma`, `add`, `mul`, `div` and
`sqrt` under all five attributes. Nothing in `python/cft_golden` is
edited or patched.

The witness needs a paragraph, because the obvious one does not reach.
`python/tests/ref754.py` is the repository's independent oracle - exact
`Fraction` arithmetic, no code shared with the model - and it was
written as a microscope for eight-bit formats. At width two things stop
it: `ref_pack` builds 2^emax and 2^emin as Fractions on every call,
which is a 2^30-bit integer at binary2048, and `Fraction` normalises
with a gcd on every operation, which at 2^(+-4 million) is seconds a
check. So there are two witnesses, and each result says which it rests
on.

**Interior** - exponents within a few thousand of zero, where neither
range test can fire. The reference is the oracle's own primitives
(`floor_log2`, `rnd_int`, `enc_exact`) with `ref_pack`'s two range tests
left out. RUN:

| format | exp_w | p | arithmetic checks | mismatches | sqrt checks | failures |
|---|---|---|---|---|---|---|
| binary256 | 19 | 237 | 5,970 | 0 | 375 | 0 |
| binary512 | 23 | 489 | 5,950 | 0 | 375 | 0 |
| binary1024 | 27 | 997 | 5,965 | 0 | 375 | 0 |
| binary2048 | 31 | 2017 | 3,975 | 0 | 250 | 0 |
| binary4096 | 35 | 4061 | 2,390 | 0 | 150 | 0 |
| binary8192 | 39 | 8153 | 1,195 | 0 | 75 | 0 |

One case in five is a catastrophic cancellation (`c` set to the negated
rounded product, then perturbed in its low bits); significands are
shaped towards all-zeros, all-ones and long runs. Square roots are held
to an exact bracket - no square root of a representable number is a
midpoint, so `((v + down)/2)^2 < x < ((v + up)/2)^2` decides the nearest
attributes and the one-sided forms decide the directed ones.

**Edges** - both ends of the exponent range, subnormals, products that
land on the boundaries, the widest alignments a format admits. The
reference is 754's rounding restated on plain integers (value =
N/D x 2^E, no gcd): 7.4 overflow, 7.5 tininess *after* rounding,
underflow as tiny-and-inexact. **Before it is trusted it is scored
against `ref754.ref_pack` itself** wherever that is affordable: every
finite encoding of the three tiny formats against 24 sampled partners,
and the edges of binary256. RUN: **338,505 checks and 280 checks, zero
disagreements.** Then:

| format | checks | mismatches | of which overflow | underflow |
|---|---|---|---|---|
| binary256 | 3,980 | 0 | 367 | 765 |
| binary512 | 3,985 | 0 | 447 | 805 |
| binary1024 | 800 | 0 | 67 | 170 |

**What this does and does not establish.** The tiny-format gate
(`python/tests/test_tiny_formats.py`) proves `softfloat`'s clause-5
surface generic *downward*, exhaustively. This is its upward
counterpart, sampled, and it covers the arithmetic core only:
`transcend`, `divfull`, `chars`, `reduce`, `formatof` and the sequencer
model are *written* against `FpFormat` and were not exercised at width
here, beyond what 1.3 and 1.4 show.

### 1.2 What the model's plain-shift alignment costs

The model's `fma` aligns with `uc.m << (uc.e - e0)`
(`softfloat.py:360`) - a shift by the true exponent difference, which is
what makes it obviously right. RUN, one `fma(max, 1, min_subnormal)`
under roundTowardPositive and one `remainder(max, small)`:

| format | widest alignment | as an integer | `fma` | `remainder` |
|---|---|---|---|---|
| binary256 | 524,521 bits | 0.06 MiB | 0.2 ms | 0.2 ms |
| binary512 | 8,389,093 bits | 1.0 MiB | 5.0 ms | 6.2 ms |
| binary1024 | 134,218,721 bits | 16 MiB | 73.6 ms | 138.2 ms |
| binary2048 | 2,147,485,661 bits | 256 MiB | 1,145 ms | 3,419 ms |

Sixteenfold a rung, exactly as the exponent range says. It shows up in
the edge campaign's own clock: the model spent 0.04 ms a check at
binary256, 1.06 ms at binary512 and 17.5 ms at binary1024. binary4096
would want 4 GiB integers. A clamp (anything past 3p + 2 bits is sticky)
removes it, at the price of a little of the obviousness that is the
model's whole job; libcft and the RTL already clamp (section 3).

### 1.3 The transcendentals: the cap, and the cap lifted

`ext-a/transcend_cap.py`. READ: the Ziv schedule starts at `2p + 40`
bits and stops at `min(8p + 128, PREC_CAP_CEILING)`, and the ceiling is
832 (`transcend.py:163`) because the C port's 2048-bit container cannot
hold more - the two are coupled on purpose, "so that both
implementations give up in the same place". RUN:

| format | p | first attempt | cap | attempts as shipped |
|---|---|---|---|---|
| fp256 | 237 | 514 | 832 | 514, 832 |
| fp512 | 489 | 1,018 | 832 | **832 only** |
| fp1024 | 997 | 2,034 | 832 | **832 only** |

At binary512 the schedule degenerates to one attempt below the
precision the design says it should start at; `exp(3)`, `log(3)` and
`atan(3)` still decide there, because 832 > 489 and the inputs are
easy. At binary1024 the cap is below the target precision itself and
all three are **refused by name** (`ZivEscalation`), which is the
contract working. With the ceiling lifted *in the instrument's own
process* (a module attribute assigned after import; nothing on disk
changes) all six evaluate, at both widths, in a millisecond or two.
They were not scored against an outside oracle - the point was only
that nothing else in the path is sized for 256.

### 1.4 A proof with a ladder in it

READ, `transcend.py:388-430`: `_pow_dyadic` decides whether `x**y` can
be a grid point or a midpoint, and its docstring is explicit that
returning `None` "is a PROOF, not a shrug". One branch:

    k = -F
    if k > 24:
        # 2^k then exceeds both the widest odd part on this ladder and
        # the widest |E|, so only M == 1 with E == 0 could pass ...
        return None

"On this ladder" is doing work. The widest |E| is the smallest
subnormal's, `man_w - emin`: 262,378 at fp256 and 4,194,790 at
binary512, both below 2^24. At binary1024 it is 67,109,858, above 2^26,
and `emax` is 2^26 - 1 - so `x = 2^(2^25)`,
`y = 2^-25` is a representable pair whose power is **2, exactly**. RUN,
ceiling lifted as in 1.3:

| case | attribute | delivered | flags |
|---|---|---|---|
| `pow(2^(2^25), 2^-25)`, binary1024, k = 25 | RNE | 2.0 | **inexact - wrong** |
| | RMM | 2.0 | **inexact - wrong** |
| | RTZ, RDN, RUP | refused (`ZivEscalation` at 8,104 bits) | - |
| `pow(2^(2^24), 2^-24)`, binary1024, k = 24 | RNE | 2.0 | none - right |
| `pow(2^(2^21), 2^-21)`, binary512, k = 21 | RNE | 2.0 | none - right |

The nearest attributes accept the enclosure (both endpoints round to
2.0) and force `inexact`, which is a wrong flag delivered quietly; the
directed ones can never agree across an exact value and refuse. This is
the only place in the whole audit where a wider format would produce a
**wrong answer with no refusal**, and it is sound through binary512.

### 1.5 MPFR across widths

`ext-a/mpfr_scale.c`, the two rows of `host/tools/cft_bench_peers.c` -
`mpfr`, and `mpfr+754` by the manual's recipe - carried to widths that
tool does not reach. RUN on the development desktop (i5-12400F, WSL2,
Ubuntu 22.04's MPFR 4.1.0 - **not** the pinned oracle build - one
thread, round-to-nearest-even, operands uniform in [1, 2)), ns an
element:

| format | p | mul | +754 | fma | +754 | div | +754 | sqrt | +754 |
|---|---|---|---|---|---|---|---|---|---|
| binary256 | 237 | 37.7 | 53.3 | 54.6 | 68.2 | 76.3 | 94.4 | 127.2 | 142.0 |
| binary512 | 489 | 59.0 | 74.1 | 80.8 | 94.3 | 124.0 | 140.9 | 232.4 | 271.9 |
| binary1024 | 997 | 133.7 | 141.8 | 188.4 | 205.8 | 249.5 | 263.8 | 393.1 | 413.6 |
| binary2048 | 2017 | 363.9 | 394.1 | 516.4 | 511.9 | 689.1 | 680.1 | 709.7 | 740.8 |
| binary4096 | 4061 | 1,130.9 | 1,138.5 | 1,548.0 | 1,573.0 | 2,111.2 | 2,093.8 | 1,626.2 | 1,620.2 |
| binary8192 | 8153 | 3,225.1 | 3,218.3 | 4,277.5 | 4,253.3 | 5,700.3 | 5,725.3 | 4,092.3 | 4,129.9 |

Three cautions. An earlier run of the same program on the same machine
read 33.3 and 1,255.8 ns for the binary256 and binary4096 multiplies,
so **these figures carry about 10% from run to run**, and a `+754`
column that reads *below* its neighbour is that noise and nothing else.
Second, `docs/BENCHMARKS.md`'s peer table is the same CPU measured
properly - the sim container, one pinned core, a quiet machine, the
pinned MPFR 4.2.2 - and has fp256 at 36.1 / 65.0 / 85.3 / 140.2, which
this run sits within 4 to 16% of; but it has the recipe at **4 to 8
ns** where this run reads 8 to 17, so the older MPFR (or WSL) makes the
`+754` columns here an upper bound. Third, README.md's 5.5x
and 21.1x were measured against amd-arc-box's Xeon, a slower core than
this one: "MPFR cores" below means *this desktop's* cores throughout,
which is why today's tile reads 4.0x on multiply in section 4 and not
5.5x.

---

## 2. The ladder, layer by layer

Each layer gets three lists: what is already generic, what is a number
or a row (and refuses by name today), and what is structural.

### 2.1 The golden model

**Generic.** A grep of `softfloat.py` for 256, 237, 236, 19 and the
four format names finds comments and docstrings only. `round_pack`,
`unpack`, `div` and `sqrt` derive everything from `fmt`; `formatof.py`
and `augmented.py` take any `(src, dst)` pair; `reduce.py`, `seq.py` and
`asm.py` need only `width % 8 == 0`; `PREC_CODE` is written as a full
32-bit header word and read back by reverse lookup, never masked.
`vectors/gen_vectors.py` loops over `FORMATS`, so **the 168 sets become
235 on their own** with a fifth format - and the growth is in formatOf,
which is the square of the format count (80 of the 168 today, 125 of
the 235). The seed ROM is shared by every rung by design: the index is
the top nine fraction bits of whatever format asks
(`test_seeds.py`'s `test_seed_is_format_consistent`).

**A row or a number.** `_NEWTON = {24: 2, 53: 3, 113: 4, 237: 5}`
(`sequences.py:76`) - a `KeyError` for a fifth format, and the rows it
needs follow from the comment beside it (each step squares a 2^-8.5
error): **6, 7, 8 and 9 steps** at binary512 to binary4096, one more a
doubling. `_WORST_SWEEP` (`vectors.py:506`) wants a row.
`gen_divfull.py:39` lists the four formats and emits `[4]`. The
double-rounding witness builder hard-codes `exp_w = 24` for its
synthetic intermediate (`formatof.py`, `_wide_format`), which overflows
for a binary1024 source; it is test scaffolding.

**Structural.** The 832-bit cap (1.3), which is a C constraint wearing
a Python constant. The `k > 24` proof (1.4). The plain-shift alignment
in `fma` and `remainder` (1.2). And `chars.py`'s exact path, which is
correct at any length and whose lengths come from the format: the
smallest subnormal's exact decimal expansion is 183,000 digits at
binary256, 2.9 million at binary512, 47 million at binary1024 and 750
million at binary2048 (MODELLED, `model.out.txt` section 3).

### 2.2 libcft

**Generic, and more so than a four-format library has any right to
be.** In the C library `CFT_FP256` appears where it is defined
(`cft.h:181`) and in one comment; the descriptor's fields (`f->prec`,
`f->man_w`, `f->emax`, `f->width` and the rest) are read **512 times**
across `host/src/*.c`. (`cft.hpp` adds five template specialisations
and aliases, which a fifth format would want a sixth of.) The format
table is `FpFormat`'s twin (`softfloat.c:10`, `cft_sf_formats[4]`); byte
sizes are `f->width / 8` everywhere; only a handful of `switch` sites
dispatch on the precision at all. Every multiprecision operation takes
its working width `W` at run time; the transcendental series terminate
on `term_negligible`, not on a count; `chars.c` carries its own
heap-growable bignum *because* "those lengths come from the FORMAT, not
from a design choice" (`chars.c:28`) and uses `int64_t` exponents
throughout. `device.c`'s image buffer is sized
`32 + 3 * (4 << CFT_MAX_FORMAT) + 3 * 8` with a comment that reads "a
format added above fp256 grows it without anyone remembering to".

**A row or a number**, each of which refuses loudly today:

| what | where | today | binary512 wants |
|---|---|---|---|
| bigint container, 5p + 3 bits | `bigint.h:53`, `cft_config.h:260` | 64 limbs (2,048 bits; fp256 needs 1,188) | 77 limbs; 156, 316, 635 at the next three rungs |
| the ceiling itself | `cft_config.h:136` | `#error` if `CFT_MAX_FORMAT > 3` | 4 |
| Newton steps | `divsqrt.c:76` | `switch (f->prec)`, returns -1 otherwise, callers check | a case |
| element bytes | `backend_xrt.cpp`, `backend_remote.c`, `elem_bytes()` | `case 3: return 32` | a case each |
| arrays indexed by format | `softfloat.h:48`, `divfull_images.h`, `conformance.c`, `device.c` | `[4]`, `f < 4` | about eight `4`s |
| the divide/sqrt images | `divfull_images.h` | generated by `python/gen_divfull.py` | a regeneration |

The bigint functions return 1 rather than truncate, `softfloat.c` turns
that into `CFT_ERR_INTERNAL`, and `cft_config.h` says why the shortage
is allowed to be loud: "Too few limbs is loud ... Too little STACK is
silent." The cost of more limbs is exactly that stack: `sizeof(cft_bn)`
is 260 bytes today, 312 at binary512 and about 2.5 KB at binary4096.

**The transcendentals need four ceilings raised together**, because
each was derived from the one below it:

    CFT_TR_PREC_CAP_CEILING  832   transcend.h:86   (= the model's)
    CFT_MP_PREC_MAX          928   mpfloat.h:81     832 + 32 guard + "the 19 bits ... the
                                                    fp256 exponent range can demand"
    CFT_MP_CONST_BITS       1088   mp_consts.h:23   six constants; cft_mp_const REFUSES W above it
    CFT_BN_LIMBS              64   bigint.h:53      cft_mp_mul forms the 2W-bit product

binary512's uncapped schedule runs to 4,040 bits and its products to
8,080; binary4096's to 32,616 and 65,232, at which point a
stack-resident `cft_bn` is no longer tenable and the multiprecision
layer wants `chars.c`'s heap `nat`.

**Structural.**

- **The capability word is full.** `format_mask = caps & 0xFu`
  (`backend_xrt.cpp:1055`, `backend_remote.c:1253`) is CAPS[3:0], and
  the nibble above it is the sequencer's feature nibble, which
  `docs/ARCHITECTURE.md` already records as full. A fifth precision bit
  has nowhere to go in that register. The remote frame's `fmt` is a
  full `u32`, so the wire carries a fifth code; both ends' `elem_bytes`
  and the HELLO mask are what have to move, in lockstep
  (`CFTR_PROTO_VERSION` is compared for equality).
- **The beat is 32 bytes in the host too.** `slice.h:53` computes
  `epb = 32 / elem_bytes` and then `if (epb == 0) epb = 1`, so a
  64-byte element is *silently* planned as one element a beat where
  everything else here refuses; `mask_bits.h` says "a beat is ONE lane
  at fp256"; the XRT backend rounds to 32 throughout.
- **Exponents are `int`** (section 3), and at binary4096 the descriptor
  itself breaks: `uint32_t exp_mask` cannot hold 2^35 - 1, `int32_t
  bias/emax/emin` cannot hold 17,179,869,183, and `cft_bn_extract` is
  documented to 32 bits and is what `sf_unpack` reads the exponent
  field with.
- **The 2/pi table** (section 3).

### 2.3 The RTL

**Generic.** `cft_fpfma_pipe`, `cft_opmux`, `cft_simpleops` and
`cft_seedop` are parameterised on `EXP_W` and `MAN_W` and derive their
widths; the multiplier geometry is one include (`cft_mulgeom.svh`) that
four modules share and cross-check at elaboration; `IMUL` is pinned to
32 bits at every format by definition ("a 256x256 multiplier at fp256
serving nobody"), so no integer multiplier grows with the rung; and
**division and square root are programs of FMAs**, so there is no
divider to widen at all - only one more Newton step a doubling.

**A number, each behind a guard.** READ, with the widths a wider rung
wants MODELLED in `model.out.txt` section 1:

| field | where | holds | binary512 / 1024 / 4096 want |
|---|---|---|---|
| LZC window `NW = 3 man_w + 9`, `lsh[9:0]` | `cft_lzcone`, `$error` if `NW > 1024` | 717 at fp256 | 1,473 / 2,997 / 12,189 (11 / 12 / 14 bits) |
| granule counts `nrm_csh`, `aln_csh` | `[3:0]` | 16 x 64 bits | 24 / 47 / 191 granules |
| multiplier tree | `$error` if `NMC > 16` | 16 chunks | 21 / 42 / 170 chunks, 5 / 6 / 8 levels |
| `r11_msb <= {22'b0, n11_msb}` | the pipe | 10 + 22 | follows `lsh` |
| sequencer `esz` | `cft_seq.sv:407`, six bits | 32 bytes | 64 / 128 / 512 |
| `cft_mulpass` | `$error` if `COLS > 16` | - | fine: 9 to 11 columns suffice (section 5.1) |

A small thing falls out. The pipe's comment says "MAN_W <= 383 is the
real ceiling" (`cft_fpfma_pipe.sv:310`), from the 16-chunk tree. The LZC
guard bites first: `3 man_w + 9 <= 1024` is **`man_w <= 338`**. By its
guards the pipe as written admits binary288, binary320 and **binary352**
(`man_w` 330, `NW` 999, 14 chunks) and refuses binary384 at the LZC.
Nothing was elaborated to confirm it; both guards refuse by name, so
only the comment is off.

**Structural**, and all of it is data movement:

- **The beat is the element is the memory width.**
  `cft_engine_stream.sv:410` refuses `BEAT_BITS > 256` by name, and the
  comment above it (line 362) says exactly what a wider format needs:
  "multi-beat elements and an assembly buffer; rather than pretend, the
  guards below refuse the configuration." 256 is the HBM pseudo-channel
  width, the design refuses width converters on principle, and the same
  file records that a 512-bit master "demonstrably lost write payloads
  through this platform's emulation models". A binary512 element is two
  beats; a binary4096 element is sixteen, which is one whole AXI burst
  at `BURST_LOG2 = 4`.
- **The precision code is two bits and arithmetic is done on it.**
  `cft_lanes.sv:91` takes `prec [1:0]`; `cft_krnl.sv:307` is
  `prec_ok = (cfg_prec[3:2] == 2'b00) && PREC_CAPS[cfg_prec[1:0]]`; the
  engines derive beats by *shifting on the code*
  (`assign beat_sh = 6'(LANE_SH) - {4'b0, cfg_prec[1:0]};`,
  `cft_engine_stream.sv:553`). The CSR field is four bits
  wide (`MODE[11:8]`) but everything behind it is not, the four banks
  in `cft_lanes` are four hand-unrolled copies, and every `case (prec)`
  has a `default:` arm that means fp256.
- **The sequencer builds only at a 256-bit beat**:
  `localparam bit SEQ_OK = (BEAT_BITS == 256)` (`cft_krnl.sv:317`),
  because the image header is one beat and constants are broadcast
  across one.
- **The sixteen-stage map has carry chains linear in p** (section 4),
  and the exponent algebra is `int` (section 3).

### 2.4 The machinery built to shrink is the machinery that grows

`CFT_MAX_FORMAT` and its limb ladder exist so the library fits an
ESP32. The `EN_FP32..256` generics exist so a tile can drop rungs.
`BEAT_BITS` exists so a quarter tile fits an Alchitry Au. `MUL_PASSES`
exists so a Kintex-7 stops caring about DSPs. Each is the hook a wider
rung would use, each has been exercised in one direction only, and each
**refuses the other direction by name**: `CFT_MAX_FORMAT > 3`,
`BEAT_BITS > 256`, `NMC > 16`. That is the project's discipline doing
its job, and it is why this section could be written as a list of
places rather than as a rewrite.

### 2.5 Verification

What carries over: MPFR still arbitrates every operation it can reach
at any precision (its exponent type is a `long` by default: 64 bits on
the Linux hosts, 32 on an LLP64 one, where it would hit binary2048 with
everything else). The vector sets grow on their own (2.1). The
multiplier proofs already run on a reduced chunk geometry
(`CFT_MUL_MCH_FORMAL`) and do not scale with `p` by construction. The
LZC equivalence proof would have to be re-run at each new `NW`. What
was already gone stays gone: CPU silicon arbitrates to binary64 and
`__float128` to binary128, so **above binary128 MPFR is the only
outside authority, at any width, today** - which section 7 comes back
to.

What does not carry over is cost. The thirty-nine transcendentals are
replayed through a schoolbook bignum at a working precision that grows
with `p`; that goes as roughly p^2.5 to p^3 a case, three orders of
magnitude from binary256 to binary4096, and the census that takes hours
becomes weeks. Since the verification is the product, this probably
binds before anything in section 3's table does.

---

## 3. What explodes is the exponent range

MODELLED (`model.out.txt` sections 2 and 3); what the same growth costs
the golden model was RUN, in 1.2:

| format | exp_w | emax | 2/pi table | smallest subnormal, exact decimal | `ea + eb` reaches | in 32 bits |
|---|---|---|---|---|---|---|
| binary256 | 19 | 2^18 | 33 KiB | 1.8e5 digits | -524,756 | fits |
| binary512 | 23 | 2^22 | 513 KiB | 2.9e6 | -8,389,580 | fits |
| binary1024 | 27 | 2^26 | 8 MiB | 4.7e7 | -134,219,716 | fits |
| binary2048 | 31 | 2^30 | 128 MiB | 7.5e8 | -2,147,487,676 | **over by 4,028** |
| binary4096 | 35 | 2^34 | 2 GiB | 1.2e10 | -34,359,746,484 | no; `exp_mask` outgrows `uint32_t` too |
| binary8192 | 39 | 2^38 | 32 GiB | 1.9e11 | -5.5e11 | no |

**The table.** `host/src/mp_2opi.h` stores 2/pi to 270,336 bits, and its
header derives the number: the Payne-Hanek window "may start as deep as
bit 261,906 (fp256's emax - man_w, less one) and may be as wide as ...
8,192 bits". It is `emax`-sized by construction, and it exists because
the contract asks for correctly rounded `sin`, `cos` and `tan` over the
*whole* range of an IEEE format. Only those three read it; the
Pi-variants reduce exactly by `x mod 2` and never touch it
(`transcend.c:20-27`).

**The integer.** `ep = ua.e + ub.e` (`softfloat.c:372`) is the widest
exponent quantity in the library, and `cft_config.h:144-189` already
reasons about it in full - for the opposite reason. The gate
`#if INT_MAX < 2 * CFT_EXP_SPAN` was written so that binary128 is
refused on a 16-bit AVR "by the compiler, with the number that refuses
it". Fed binary2048's span it refuses a 32-bit `int` the same way. The
RTL pipe does the same algebra in `int` and says so at
`cft_fpfma_pipe.sv:471`: "with EXP_W <= 19 there is no value a field can
hold that the cast moves". `cft_seedop` already does it the way that
has no wall - `logic signed [EXP_W+1:0]`, two bits of headroom, sized
from the parameter. With 64-bit exponents and the library's own 2x
margin the next failure is **binary524288** (exp_w = 63), which is not
a wall anyone will meet.

**Who is immune, and why it matters.** The RTL and `softfloat.c` clamp
alignment - the "far" case in the pipe, `FAR = 2p + 4` in the library -
so the exponent range costs them `exp_w` bits of adder and nothing
else. Everything that *materialises* something of size 2^emax is
exposed: the model's plain shift (1.2), `remainder` in both
implementations (which walk the exponent range, though they need not -
2^E mod m by square-and-multiply is about `exp_w` modular squarings),
the exact decimal conversions, and the table. **A non-IEEE wide format
with a modest exponent would dodge all of it**, and `formats.py`'s first
paragraph rules that out. The explosion is the standard's, accepted
with the standard.

---

## 4. If only the widths move

The cheapest possible port: every guard and field widened, the
sixteen-stage map kept exactly, the clock allowed to fall. MODELLED
(`model.out.txt` section 5). The clock is a line through the two
out-of-context figures `docs/ARCHITECTURE.md` publishes (232 MHz at
p = 24, 148 MHz at p = 237), which is 4.03 ns + 11.49 ps a bit, plus
the 0.9 ns `docs/LAYOUTS.md` says the shell has cost in practice. A
line is the right shape because the long paths are carry chains - the
round stage's increment, the split adder's 359-bit halves, the tree's
522-bit adds - and it is **optimistic from binary1024 up**, because
`docs/ARCHITECTURE.md` already has the critical path at two-thirds
routing.

| format | passes | DSP | lane LUT | one tile, of the U50 | clock | ns an element | x MPFR mul | x MPFR fma |
|---|---|---|---|---|---|---|---|---|
| binary256, today | 1 | 140 | 35,333 READ | - | 135 MHz READ | 9.35 READ | 4.0 | 5.8 |
| binary512 | 1 | 609 | 88,421 | 27% | 95 MHz | 26.6 | 2.2 | 3.0 |
| binary1024 | 1 | 2,478 | 237,791 | 44% | 61 MHz | 82.7 | 1.6 | 2.3 |
| binary2048 | 4 | 2,618 | 382,329 | 60% | 36 MHz | 283.6 | 1.3 | 1.8 |
| binary4096 | 16 | 2,629 | 665,927 | 93% | 19 MHz | 1,041 | 1.1 | 1.5 |

A side-by-side multiplier is quadratic in DSPs - 609, 2,478, then
10,115 and 40,630 against the part's 5,952 - so from binary2048 the
multiplier must iterate regardless, and the table takes the smallest
pass budget that keeps it under 45% of the DSPs. The "x MPFR" columns
are one tile against one core of this desktop (1.5).

The reading: the advantage over MPFR decays from 4x to parity across
four rungs, and every bit of that decay is the clock. The memory side
costs exactly the width - *k*/256 beats an element - which is the
property that makes the tile win in the first place. So the question
worth asking is the next one.

---

## 5. With the clock held

Assume the work is done: carry-select adders and a carry-select
incrementer, log shifters staged a level or two a cycle,
carry-save accumulation inside `cft_mulpass` (its fold is a
(p + K + 1)-bit add every cycle with K = 24 x columns - 754 bits at
binary512's eleven columns against the 522 of today's widest tree add,
so it is the critical path from the first new rung), multi-beat
elements, sized exponent vectors, tiles that carry the wide rung only.
None of it changes a bit; `LATENCY` is a parameter the engines already
take.

### 5.1 Staying beat-limited takes a constant nine columns

A tile retires 107 M beats a second at 135 MHz (READ), 1.262 cycles a
beat. An element of *k* bits is *k*/256 beats on each stream, so an
element is due every (k/256) x 1.262 cycles. The multiplier needs
`chunks / columns` passes with `chunks = ceil(p / 24)`. Both grow
linearly with the width, so the column count that keeps the multiplier
ahead of the memory is **the same at every rung**: MODELLED, 11 at
binary512 and **9 from binary1024 to binary16384**. DSPs therefore grow
at about 0.53 a significand bit - 319, 531, 1,071, 2,151, 4,320 - and
never bind before LUTs on this part. That is a better result than the
pass budget was built for: it was built to save DSPs on a Kintex-7, and
it turns out to be what keeps "one element costs exactly its width"
true at any width.

### 5.2 The area model, and a correction

READ: `docs/ARCHITECTURE.md`'s `MUL_PASSES` table has the tile at
123,214 LUT at one pass and 115,310 at ten. Ten passes remove nine
fp256 columns, eight fp128 and eight fp64 - 3,461 column-bits - and add
an accumulator a lane (about 1,095 LUT), which puts a multiplier column
at **2.60 LUT a column-bit**. Calibrating

    lane(p, C) = p * (base + 3 log2(3p)) + 2.60 * p * C

on the fp256 lane's all-in cost (`docs/LAYOUTS.md`: 31,258 + 262 +
3,139 + 674 = 35,333, the pipe with its opmux, simpleops and seedop)
gives `base = 94.7` LUT a significand bit, the `3 log2(3p)` term being
two 3p-wide log shifters at a 4:1 mux a LUT. Its residuals against the
other three measured lanes are **-16.4% at fp32, +4.2% at fp64 and
+9.2% at fp128**, and its DSP count for the shipping tile is 274 against
262 routed. Holding the clock adds a **guessed** 21 LUT a bit
(carry-select costs an adder three times over), and the tile's
non-shrinking infrastructure is a **guessed** flat 20,000 (15,300
today, plus assembly buffers).

**The correction.** A first pass of this model calibrated on the pipe
alone - 31,258 LUT, 132 a bit, the columns and the shifters then
subtracted too generously - and put one binary4096 lane at **78% of the
U50**, with six binary512 tiles and three binary1024. That figure was
given in conversation on the day of the study. Calibrated on the all-in
bank cost the repository publishes it is **100%**, and every tile count
below moves down. The first number is recorded here because it was
wrong, and because the way it was wrong - leaving out 17 LUT a bit of
opmux, simpleops and seedop that `docs/LAYOUTS.md` lists in the same
sentence - is the kind of thing a second reader should check this
section for again.

### 5.3 What fits, and what it is worth

MODELLED (`model.out.txt` section 6), wide-only tiles, the U50 to 82%
of 870,720 LUT with the shell at 123,897 + 12,626 a further CU (READ):

| format | columns / passes | DSP a tile | tile LUT | tiles | of the U50 | card, M fma/s | MPFR cores, fma / mul | against mpfr+754, fma |
|---|---|---|---|---|---|---|---|---|
| today, 4 full tiles | 10 / 1 | 262 READ | 123,420 READ | 4 | 80.6% READ | 428 | 23.4 / 16.1 | 29.2 |
| binary512 | 11 / 2 | 319 | 105,976 | 5 | 81% | 267.5 | 21.6 / 15.8 | 25.2 |
| binary1024 | 9 / 5 | 531 | 193,181 | 2 | 60% | 53.5 | 10.1 / 7.2 | 11.0 |
| binary2048 | 9 / 10 | 1,071 | 376,509 | 1 | 57% | 13.4 | 6.9 / 4.9 | 6.8 |
| binary4096 | 9 / 19 | 2,151 | 750,090 | **0** | 100% | - | - | - |
| binary8192 | 9 / 38 | 4,320 | 1,510,347 | 0 | 188% | - | - | - |

Sensitivity, because two inputs are guesses: at +10 LUT a bit and
15,000 of infrastructure the tile counts are 5 / 3 / 1 / 0 and one
binary4096 lane is 95% of the part; at +30 and 40,000 they are
4 / 2 / 1 / 0 and it is 107%. **binary2048 fits under all three and
binary4096 under none.** By the same model a 1.7M-LUT part (an Alveo
U250; `docs/ROADMAP.md` already names the U200 and U250 as the
pragmatic next cards) holds one binary4096 lane in a little over half
of itself, and the largest FPGAs made, at about 4M LUT, hold binary8192
comfortably and put binary16384 near 80% - with fewer than half the
DSPs nine columns would want, so no longer beat-limited.

Two readings. **The card's worth falls from about 23 MPFR cores to
about 7 by binary2048 even with the clock held**, and what takes it
down is LUTs, not the multiplier: the single binary2048 tile uses 18%
of the DSPs. The tile is beat-limited throughout, so each *tile* holds
its ground against MPFR (one binary2048 tile is 6.9 cores where one
fp256 tile today is 5.8); there are simply fewer of them, because
everything in a lane that is not the multiplier is linear in the width
and `docs/ARCHITECTURE.md` already found that is where the LUTs are.

### 5.4 The walls, in the order they bite

1. **LUTs** - binary2048 on a U50, a rung more on each larger part.
2. **Latency, which is free for streams and not for programs.** Holding
   135 MHz turns sixteen stages into something like thirty to forty by
   binary4096: each long shifter hop and each carry-select resolve
   wants a register. `cft_seq` guards `NBEATS` at 16
   (`cft_seq.sv:723`), and its own comment notes that a block shorter
   than the pipe is correct but does not keep it full. Dependent
   instruction chains - which section 6 argues are the workload that
   matters - slow in proportion unless the register file's beat field
   grows with the pipe.
3. **The contract's own tables** - section 3, and section 7.5.
4. **Verification cost** - section 2.5.
5. **64-bit exponents** - binary524288; not a wall.

---

## 6. The MPFR-shaped machine

The second half of question 2: accept that throughput falls with
precision, as MPFR's does, spend the silicon saved on more tiles, and
ask what that is worth on an FPGA, on an ASIC, and on a carrier of many
chiplets.

### 6.1 What the pass budget actually scales like

`cft_mulpass` iterates ONE dimension. Each pass is a full p x 24
column, so area goes as p and the time for one FMA as p / columns -
*better* than MPFR's p^2 in time, paid for in linear area. At a fixed
silicon budget the two come out alike: tiles go as 1/p and each runs at
1/p, so FMAs a second go as 1/p^2, the schoolbook exponent, which is
MPFR's up to about four thousand bits. The exponent is shared. Only the
constant differs, and the honest unit for the constant is **significand
bit-products a second**.

### 6.2 Bit-products a second

| | bit-products a second |
|---|---|
| MPFR, one core of this desktop, binary256 multiply RUN | 1.49e12 |
| the same core, binary1024 | 7.43e12 |
| the same core, binary4096 | 1.46e13 |
| the same core, binary8192 (each rung is x2.85 in time by now, not x4) | 2.06e13 |
| one shipping fp256 lane, 107 M/s x 237^2 READ | 6.01e12 |
| the whole U50, every one of 5,952 DSPs on a 24 x 17 product at 135 MHz | 3.28e14 |

Read the first three rows together. **MPFR gets ten times more
efficient from 256 to 4096 bits**, because thirty-odd nanoseconds of
per-call bookkeeping amortise over the limb products. One fp256 lane is
worth four such cores at 256 bits and would be worth 0.4 of one at the
rate MPFR reaches by 4096. The tile's 5.5x and 21.1x (README.md) are
therefore **a win over MPFR's overhead, not over the CPU's
multiplier**; as precision grows the comparison converges on raw
multiplier capacity, where this card is about **22 cores** with every
DSP busy and no arrangement of the ladder changes that number. It is
why section 5.3's best case never exceeds the low twenties.

### 6.3 Which is why it is an ASIC argument

A general-purpose core spends well under one percent of its area
multiplying. MODELLED from `docs/ROADMAP.md`'s chiplet paragraph (a
full tile "~1M gates ~15-25mm2" on a 130 nm open PDK at 50-150 MHz;
28 nm at "~15x density, ~1 GHz"), at 5 to 8 gates a bit-product:

| | bit-products a second per mm2 of multiplier |
|---|---|
| a desktop core under MPFR, of order 7.5 mm2 | ~2e12 |
| 130 nm open PDK | 2.5e11 to 2.0e12 |
| 28 nm | 6e13 to 2e14 |

These are the roadmap's napkin figures times another napkin, and the
two orders of magnitude at 28 nm are nonetheless structural: they are
the ratio between a die that is mostly multiplier and one that is
almost none. **At 130 nm a shuttle-sized die is about one modern core
of wide multiply** - a determinism and attestation artifact, which is
what the roadmap already says it is for, not a fast one. At 28 nm the
same arithmetic is a hundred-odd cores in 25 mm2, before counting
chiplets.

### 6.4 The pipeline enable is the asset

What makes a slow small tile *the same tile* is already built. In
enabled-edge terms the pipe is identical at every `MUL_PASSES`; results
are bit-identical by construction (no summation order changes an
integer); `tb_mulcycle` holds the array to it against itself; and
neither CAPS nor VERSION mentions the pass count, "because neither bits
nor the register map move" (`cft_krnl.sv`). `CONFORMANCE.md` makes it
normative: clock frequency and pipeline depth are an implementation's
own, and "**Determinism is clock-independent**: a slower conforming
implementation is a complete one". So a carrier may mix fast wide tiles
and slow small ones and the bits cannot differ - `docs/SCALING.md`'s
"determinism constrains which INDEX is computed, never which TILE",
extended from which tile to which *speed*.

### 6.5 An FPGA and an ASIC want opposite serialisations

READ: ten passes cut the tile's DSPs by 79% and its LUTs by 6.4%,
because "the tile's LUTs are in the aligner and the normaliser". On an
FPGA that is the right place to stop: flip-flops are free (the tile
uses 57 thousand of 1.7 million), so the deep pipe stays and only the
multiplier iterates.

On an ASIC a flop is about six gates. MODELLED: at binary4096 the
sixteen-stage pipe is some **260,000 flops, about 1.6M gates, idle for
169 cycles of every 170**, beside a p x 24 column of about 585k gates.
That is the wrong balance by a factor of three. An ASIC tile wants the
pipe collapsed to a few wide registers and SRAM, and the adder and the
shifter iterating under the same enable - the mechanism generalises,
since any stage may take up to `NP` wall cycles, and a 12,189-bit add
spread over 170 of them is a **72-bit adder**. Same contract, same
bits, a different datapath: MPFR's scaling in area as well as in time.
It would be a new module behind the ports `cft_lanes` already has, not
a change to anything above them.

### 6.6 Density pays only for resident work - and that is the next wall

Streaming an elementwise FMA moves 4*k* bits for p^2 bit-products.
MODELLED: 1e14 bit-products a second - about a square millimetre of
28 nm columns - wants **12 GB/s at binary4096 and 228 GB/s at
binary256**. The FPGA already taught this (the tile is beat-limited;
staging across PCIe costs five times resident execution), and the
roadmap's chiplet carrier - no SerDes at 130 nm, parallel
source-synchronous neighbour links, an FPGA hub for host and DRAM - has
far less bandwidth than HBM. `docs/SCALING.md` says as much: "there is
no shared HBM, the pseudo-channel wall is replaced by ring bandwidth".

So the chiplet machine is a *program* machine: reference orbits,
Newton and Horner chains, IAS15's inner loops, anything that iterates
on registers it already holds. And that is exactly the workload class
that does not scale across tiles today. READ, `docs/SCALING.md`: "a
PROGRAM run, resident or staged, executes on one tile" - atlas-engine
measured every program at the single's rate to the hundredth on the
quad - and the orchestrator is "not optional" for the chiplet endgame.
**The next wall on the many-tile path is a partitioner and a
scheduler for programs**, it is already on `docs/ROADMAP.md`'s debts
list, and no amount of silicon moves it.

### 6.7 Sub-quadratic software, and the limb route

Past about four thousand bits MPFR stops being schoolbook (the last row
of 6.2), and any schoolbook hardware loses ground as roughly p^0.4 from
there. An FPGA's margin does not survive that; two orders of magnitude
do, and Karatsuba is an integer identity that a sequencer can run over
column multipliers - `docs/MERSENNE.md` has Karatsuba and Toom-Cook as
"integer identities" that "keep the certificate intact", where a
floating-point FFT does not.

`docs/MERSENNE.md` is also the prototype of the *other* route to
precision: limbs over the ladder that exists, each limb product an
exact FMA with `flags == 0` as the certificate. It records that a wider
format does quadratically less work - limb width is about p/2 - so
**each rung added above fp256 makes the tile a four times better
exact-integer engine**, which is a second payoff of raising the ladder
that this study's tables do not count. As a route to wide *floats* on
today's tile it loses badly: an fp256 FMA used as a 107-bit limb
multiply spends its whole align, normalise and round path on nothing
and uses about a fifth of its bit-products, which works out an order of
magnitude slower than one MPFR core at 4,096 bits. `IMUL` is 32 bits by
decision. A full-width multiply returning high and low halves would be
the limb engine's primitive, and the p x p array is already in the
pipe; that is an observation and not a proposal.

---

## 7. What the MPFR-core yardstick leaves out: the contract

Sections 4 to 6 count in MPFR cores because it is the unit README.md
uses and the only outside one there is. It prices throughput. It does
not price what is being delivered, and the two things being compared
are not the same product.

### 7.1 MPFR is not an implementation of an IEEE format, and says so

MPFR is the library the world treats as the reference for correctly
rounded arbitrary-precision arithmetic, and this repository's third
oracle. It is correctly rounded in every rounding mode it has, portable,
and reproducible in value across platforms - none of what follows is a
criticism of it. It is a statement about what it is *for*: a precision
and a very wide exponent range, not a format. Its manual gives a recipe
for emulating one, and `host/tools/mpfr_check.c`'s header is this
project's record of everything a caller has to add on top of that
recipe before MPFR can answer this contract. READ, from that header:

| the contract delivers | what MPFR needs from its caller |
|---|---|
| subnormals and the format's exponent range | `mpfr_set_emin/emax`, then `mpfr_check_range` + `mpfr_subnormalize` with the ternary, on every result |
| the five flags of clause 7, underflow as tiny-after-rounding AND inexact | not MPFR's sticky flags - "MPFR's underflow flag has its own definition" - so the harness computes every case **twice**, bounded and unbounded, and derives them |
| invalid on a signaling NaN | "MPFR has no signaling NaNs": classified from the operand bits by the caller |
| NaN payloads, 9.7's payload operations | "MPFR keeps no payloads" |
| roundTiesToAway | "has NO MPFR equivalent - MPFR_RNDA rounds every inexact value away": built from a p+1-bit truncation and its ternary, "a dozen lines" |
| the augmented operations of 9.5 | "MPFR has no roundTiesTowardZero": the harness asks for the exact value and applies the tie rule itself |
| the seven reductions of 9.4, same bits on any partition | "MPFR CAN ARBITRATE EVERY NODE. MPFR CANNOT ARBITRATE THE TREE": 754 lets an implementation "associate in any order", so there is no outside authority on the shape |
| sinPi, cosPi, tanPi and the rest of table 9.1's tail | MPFR 4.2.0 or newer, called directly - the tool `#error`s on anything older |
| class, totalOrder, the signaling comparisons | "left to the other oracles" |
| dense arrays of interchange encodings as the observable | `mpfr_t`, packed and unpacked by the caller |

Fairness in the other direction: MPFR's `mpfr_sum` is specified as
*correctly rounded*, which is a stronger statement about a sum than any
tree. It is also a different function from every reduction 754 defines,
it raises none of 754's flags, and it needs every operand in one place.

### 7.2 The tax is small, flat, and gone at width

`docs/BENCHMARKS.md` already measured the first two rows of that table
at the four formats: "The emulation tax on MPFR is visible and small:
4-8 ns ... mpfr+754 is the closest MPFR gets to a binary-format drop-in,
and the remaining distance is semantic, not performance." RUN (1.5), the
same recipe at width, on the same CPU with an older MPFR, which makes
these an upper bound:

| format | mul | mul, +754 | the recipe costs | of the multiply |
|---|---|---|---|---|
| binary256 | 37.7 | 53.3 | 15.6 ns | 41% |
| binary512 | 59.0 | 74.1 | 15.1 ns | 26% |
| binary1024 | 133.7 | 141.8 | 8.1 ns | 6% |
| binary2048 | 363.9 | 394.1 | inside the noise | < 10% |
| binary4096 | 1,130.9 | 1,138.5 | inside the noise | < 1% |

It is a fixed cost, so it is a large fraction of a small operation and
no fraction of a large one. **Contract adherence therefore does not
rescue the throughput comparison at width.** Against `mpfr+754` today's
quad is 29 cores where against `mpfr` it is 23; at binary2048 the two
columns of 5.3 read 6.8 and 6.9. If speed were the contract's value,
the contract would be worth less with every rung. It is not where the
value is, and BENCHMARKS.md's sentence gets *more* true with width: the
remaining distance is semantic.

### 7.3 What the semantic distance consists of

Two levels, in `CONFORMANCE.md`'s terms.

**Level A - the standard, all of it, in radix 2.** `docs/COMPLIANCE.md`
walks it clause by clause: every clause-5 operation for every format,
the formatOf forms with one rounding, all 39 of table 9.1 correctly
rounded with exact flags, the reductions, the augmented operations, all
eight forms of 9.6, the payload operations, the status word of 7.1 with
5.7.4's six operations over it. Two of its rows are marked **exceeds**:
roundTiesToAway, "optional for binary formats", provided anyway; and
the decimal conversions "correctly rounded at every digit count -
5.12.2's H is unbounded". And clause 11 "counts only invalid,
divideByZero and overflow as reproducible flags; here underflow and
inexact reproduce too, because tininess detection and the rounding
position are part of the contract."

**Level B - every choice the standard leaves open, closed.** The
reduction tree and its empty and single-element cases; tininess after
rounding; one canonical quiet NaN out of every computational operation;
the sign of every exact zero, "including the two rules usually missed";
the values 754 leaves open on an invalid conversion; the reserved
rounding encodings; the flags of composed operations "with no
relaxation"; the program model; and **refusal, not approximation** -
"Nothing is ever computed 'as well as possible'."

And then the part no library can supply about itself: **it is
scored.** 1,068,915 cases with their SHA-256s, four checksum lines that
are "the whole compatibility test", replayers on a CPU, in a browser,
on a microcontroller and on the card, and a rule that a change to any
recorded bit or flag is a new profile number: "Never a quiet refresh".
"Conforming" here is a test result, not a description.

### 7.4 Why that is worth more at width, not less

**The oracles thin out to one, and then to none.** CPU silicon
arbitrates to binary64 - 23.875 billion cases of it - and `__float128`
to binary128. Above that MPFR is the only outside authority, and 7.1 is
the list of what it has no opinion on. For flags by this contract's
definition, for roundTiesToAway, for signaling NaNs, for the shape of a
reduction, for a whole program, **there is no outside authority at any
width**; two implementations of binary1024 can be held to each other
only through a golden model and a published, hashed set of cases. The
wider the format, the more of the evidence is the contract itself.

**The work that wants width is the work one bit destroys.** Nobody
computes a single binary1024 product. The consumers are long iterations
- deep-zoom reference orbits, few-body integration, IAS15 - and
README.md's founding argument is that a last-bit disagreement ends such
a run. cft-rebound's report is the concrete form: on the card "the
adaptive corrector took the same number of passes, which a single
differing bit would have moved". A tolerance gets harder to state as
precision grows; an identity does not.

**The implementations multiply, and the contract is what makes them one
machine.** Section 6 ends with a software backend, an FPGA tile, a
130 nm reference chiplet, a fast 28 nm part and a tile behind a socket,
at different clocks and pass budgets. The roadmap's endgame rests
entirely on this: "every commercial part is continuously ATTESTED
against the open ladder ... the open chip is the reference standard; the
fast chip must prove itself identical." An MPFR core can check a
chiplet's *values*, one operation at a time. It cannot check its flags,
its reductions or its programs, and it cannot be the thing a closed
part is attested against. The scored contract can, and it is the only
reason the slow open chip of 6.3 is worth fabricating at all.

**Scale-out stays free.** Partitioning is free provided "four tiles
must return what one returns, flags included", and `docs/SCALING.md`
has the partitioner checked at every tile count from 1 to 64 before a
single such machine exists. That
property is what lets section 6's carrier hold sixty-four chiplets
without a coherence protocol, and it is a Level B choice: 754 permits
any association.

**And refusal scales where approximation would not.** Width makes more
things unaffordable (7.5). The rule that an implementation refuses by
name, before it runs, means a binary4096 tile that cannot do radian
trigonometry above some exponent *says so*, in a way a caller can test
for - rather than returning something plausible. `CLAUDE.md` puts the
standard in one sentence - a refusal that says `CFT_ERR_ARTIFACT` where
it means "this tile is too old" is "a defect, not a detail" - and that
standard is what makes a partial rung honest.

### 7.5 The contract's own bill

It would be one-sided to stop there, because several of this study's
walls exist *only* because of the contract, and width is exactly where
"goes further than the standard where it can afford to" gets tested.

- **Full-range correctly rounded radian trigonometry** is what needs
  2^(exp_w - 1) bits of 2/pi. MODELLED: 2 GiB at binary4096, 32 GiB at
  binary8192, 8 TiB at binary32768, and at binary65536 about 3.4e14
  decimal digits - of the order of the largest computation of pi ever
  made. As far as the author knows no digit-extraction formula exists
  for 1/pi (pi has one; its reciprocal does not), so the window cannot
  be computed without everything before it. MPFR meets the same
  mathematics at run time, by computing pi to a length set by the
  argument's exponent, instead of from a table; that was not measured
  here.
- **Conversions at every digit count** is an *exceeds* item, and it is
  the first one to stop being affordable: `chars.c` is correct at any
  length and its multiply is schoolbook ("performance is not a goal
  here and the code says so"), so the worst-case conversion goes as the
  square of 2^exp_w - sixteenfold in length and 256-fold in time a rung.
- **All 39 transcendentals, correctly rounded, exact flags, every
  attribute** is what makes the census cost p^2.5 to p^3 (2.5).
- **A dependency-free C99 library that is bit-exact on an ESP32** is
  what makes the software backend 6 to 19 times slower than MPFR on
  add, multiply and FMA and 94 to 300 times on divide and square root
  at the formats that exist (README.md), and `cft_bn`'s portable 32-bit
  schoolbook limbs against GMP's assembly will widen that with every
  rung. README.md's sentence covers it - "It defines the contract; it
  does not compete for speed" - and it should be read as a cost.
- **roundTiesToAway, the canonical NaN, the zero signs, the reduction
  tree** cost nothing at any width: one more case in `round_up`, a
  constant, a rule, an order.

So the exceeds items sort cleanly into those that are free forever and
those whose cost is tied to 2^exp_w. A wide rung would have to say
which of the second kind it still carries, and `CONFORMANCE.md` already
has the mechanism: a new format "that changes no recorded case extends
the profile (1.1, 1.2, ...)", and what it cannot do it refuses by name.
What it must not do is carry them quietly at reduced strength, because
then the word that section 7.3 ends on stops meaning a test result.

### 7.6 So what is the right comparison

Three rows, not one. **`mpfr`** is what people actually run and is the
honest speed baseline. **`mpfr+754`** is MPFR answering as a format; it
costs a fixed handful of nanoseconds and this study carried it to
binary8192. **The contract** is a third thing that no MPFR
configuration reaches, and the distance to it is the table in 7.1 -
which somebody would have to write, verify and keep true, as
`mpfr_check.c` does for the purpose of *checking* this library and as
nothing does for the purpose of replacing it.

Counted in cores, the ladder above binary256 is a modest proposition on
an FPGA and a large one on an ASIC. Counted in what can be *held to
account* - arithmetic whose every bit and flag is defined, scored,
reproducible on any partition of any mix of hardware, and refused
rather than approximated - there is no second column to compare with,
and that is more true at binary1024 than at binary256.

---

## 8. Verdict by rung

| rung | software | RTL | on the U50, clock held | the contract |
|---|---|---|---|---|
| **binary512** | rows and numbers: `_NEWTON`, 77 limbs, four ceilings, a regenerated 513 KiB table, a fifth CAPS bit's home | every arithmetic field is a guard and `cft_mulpass` wants a carry-save fold; the real work is multi-beat elements through the engine, the sequencer and `slice.h` - weeks, not days | 5 wide-only tiles, about today's worth against MPFR | carries everything |
| **binary1024** | the `pow` proof needs its 24 derived; the worst decimal conversion is hours; an 8 MiB table stops being a header | the last rung where `int` exponents work | 2 tiles, about 10 cores | carries everything, slowly |
| **binary2048** | every exponent local becomes 64 bits and `cft_config.h`'s `int` argument is redone; 128 MiB table; the model's worst `fma` is a second | sized exponent vectors; the multiplier must iterate on this part | 1 tile, 57%, about 7 cores | the first rung where an *exceeds* item (exact decimal at extreme exponents) is not practical |
| **binary4096** | `exp_mask` outgrows `uint32_t`, `cft_bn_extract` its 32-bit contract; 2 GiB table; stack-resident `cft_bn` is untenable | as above | **does not fit** | a partial rung, refusing by name |
| above | 64-bit exponents last to binary524288 | - | a larger part a rung | full-range radian trig ends between binary8192 and binary65536 |

binary512 is a bounded project. binary1024 is the practical edge of
"the same design, widened". From binary2048 the right hardware is 6.5's
datapath rather than this one's, and the right question is no longer
how wide but how resident.

---

## 9. Found in the tree, and worth a look regardless of any of this

None of these is reachable with the four formats that exist. They are
here because an audit for one purpose found them.

1. **`sq_emit` is the one place a fifth format would not fail
   loudly.** `host/src/divsqrt.c:972` sizes its image as
   `32 + 9 * 32 + 80 * 8` - the `9 * 32` is nine constants at *fp256's*
   element size - the caller puts `uint8_t image[SQ_IMAGE_MAX]` on the
   stack (`:1377`), and `sq_emit` writes `nconst * esz` bytes with no
   check. MODELLED: at a 64-byte element the square-root image is
   **1,112 bytes into 960**. (The instruction array is fine: 63 words of
   80 at binary512, 78 at binary16384.) `device.c`'s equivalent buffer
   is derived from `CFT_MAX_FORMAT` and checked at run time; this one
   wants the same treatment. What stands in front of it today is
   `cft_config.h:136`'s `#error`, which is the first line a port
   moves.
2. **`_pow_dyadic`'s 24** (1.4). Either derive it -
   `(fmt.bias + fmt.man_w).bit_length()` is the quantity the comment
   reasons about - or assert the precondition, so that a future format
   refuses by name instead of raising `inexact` on an exact result. It
   is the only silent failure found.
3. **`slice.h:53`'s `if (epb == 0) epb = 1`** plans a 64-byte element
   as one a beat, quietly, in a library whose every other shortage is a
   named error.
4. **The pipe's "MAN_W <= 383 is the real ceiling"** is superseded by
   the LZC's `NW <= 1024`, which is `man_w <= 338` (2.3). A comment.
5. Unrelated to width, noticed on the way: `transcend.py:323` defines
   and documents `ENCLOSURE_MARGIN_ULPS = 256` and nothing reads it;
   `_endpoint` hard-codes the same margin as `outward << 16` on a grid
   of 2^(-prec-8). The values agree. The constant is decoration.

---

## 10. What this study did not do

- **No RTL was elaborated at any new width.** "binary352 is the widest
  the pipe admits" is a statement about two guards.
- **Nothing above the arithmetic core was run at width** except three
  transcendentals and one `pow`: not `divfull`, `chars`, `reduce`,
  `formatof` or the sequencer model.
- **No place and route.** The clock in section 4 is a line through two
  out-of-context points, which this project has one expensive
  demonstration does not survive the shell; section 5 *assumes* 135 MHz
  is reachable by restaging and does not show it.
- **The area model is calibrated on one lane and checked on three**,
  carries two guesses (5.2), and has already been wrong once.
- **The MPFR timings** are a desktop under WSL with the distribution's
  4.1.0 and about 10% of run-to-run spread; they are not
  `docs/bench/`-grade and are not comparable with its files.
- **The ASIC figures** are `docs/ROADMAP.md`'s napkin multiplied by a
  gates-per-bit-product range from general knowledge.
- **Three statements rest on the author's knowledge of the field
  rather than on a source in this tree**: that no digit-extraction
  formula is known for 1/pi, how MPFR reduces a large trigonometric
  argument, and how small a share of a general-purpose core its
  multiplier is.

---

## 11. Reproduction

Everything is in `docs/studies/ext-a/`; each `*.out.txt` is the run this
document quotes. From the repository root:

    python docs/studies/ext-a/wide_golden.py    > docs/studies/ext-a/wide_golden.out.txt     # ~5 min
    python docs/studies/ext-a/transcend_cap.py  > docs/studies/ext-a/transcend_cap.out.txt   # seconds; needs mpmath
    gcc -O2 -o mpfr_scale docs/studies/ext-a/mpfr_scale.c -lmpfr -lgmp -lm
    ./mpfr_scale                                > docs/studies/ext-a/mpfr_scale.out.txt      # ~30 s, Linux
    python docs/studies/ext-a/model.py          > docs/studies/ext-a/model.out.txt           # instant

`model.py` parses `mpfr_scale.out.txt`, so it goes last; its LUT, DSP
and clock inputs are constants at the top of the file with the document
each was read from. The Python instruments import `cft_golden` and
`python/tests/ref754.py` from the tree they sit in and change nothing in
it. Run on 2026-09-21 at `592c3ab`, Python 3.13.5 (the repository's
`.venv`, mpmath 1.4.1) on Windows 11 for the Python, WSL2 Ubuntu 22.04
(gcc 11.4.0, MPFR 4.1.0) on the same i5-12400F for the C.
