# libcft in Node - the C ABI, one to one, plus a Context

`bindings/wasm` put the contract in a browser tab. This puts it in a
`node` process: the **same wasm module**, byte for byte, with a
JavaScript wrapper instead of a page. IEEE binary32, binary64,
binary128 and binary256, all five rounding attributes, exact flags,
and results that are libcft's bits and nothing else.

```bash
node bindings/node/test.mjs         # 125 tests, no dependencies
make vectors                        # from the repo root, once
node bindings/node/conformance.mjs  # 1,067,635 published cases
```

```js
import { Context } from "./bindings/node/index.mjs";

const ctx = await Context.open(256);          // or 128 / "binary128" / 113
const x = ctx.from("1.5");                    // exact decimal, no rounding
const y = ctx.sqrt(ctx.add(x, 2));
console.log(y.toString(), ctx.flagNames(ctx.lastFlags));

const xs = Array.from({ length: 100000 }, (_, i) => ctx.fromBigInt(BigInt(i)));
const roots = ctx.map("mul", xs, xs);         // ONE cft_run for the array
const total = ctx.reduce("sum", roots);       // the contract's fixed tree
```

## Correctly rounded transcendentals, at 237 bits

Since ABI 0.3 the package carries the phase-1 set - `exp`, `expm1`,
`exp2`, `log`, `log1p`, `log2`, `log10`, `pow`, `hypot` - and since
ABI 0.4 the phase-2 trigonometrics as well - `sinpi`, `cospi`,
`tanpi`, `asin`, `acos`, `atan`, `asinpi`, `acospi`, `atanpi`,
`atan2`, `atan2pi` - and since ABI 0.5 the phase-3 set: `sin`, `cos`,
`tan` of a RADIAN argument, reduced against pi inside the library at
any magnitude the format holds, and `sinh`, `cosh`, `tanh`, `asinh`,
`acosh`, `atanh`. **ABI 0.6 completes 754-2019 table 9.1** with
`exp2m1`, `exp10`, `exp10m1`, `log2p1`, `log10p1`, `rsqrt`, `powr`,
and `pown`, `compound`, `rootn` - the three that take an INTEGER
exponent, which is a BigInt here (or a safe integer widened for you)
because 9.2.1 asks for `integralFormat` and the contract's type is
int64. All thirty-nine on all three layers: the raw `cftw_*` exports,
`Context`/`Float` scalars, and `map()` over an array.

ABI 0.6 also brings the three packages that are not transcendentals:
clause 5.12's character conversions with clause 9.7's payload
operations, clause 9.5's augmented arithmetic, and clause 9.4's
remaining reductions.

```js
ctx.fromDecimal("1.5e-300");     // the library's own 5.12 parser, with
                                 // H unbounded and no window - a
                                 // sequence outside the syntax is
                                 // REFUSED, never guessed at
ctx.toDecimal(x);                // the exact conversion, every digit
ctx.toDecimal(x, {digits: ctx.decimalDigits});   // Pmin: 9/17/36/73,
                                 // where the round trip is guaranteed
ctx.toHex(x);                    // the shortest EXACT hex sequence

const {r, e} = ctx.augmentedAdd(x, y);   // r + e is exactly x + y,
                                 // under roundTiesTowardZero, which
                                 // 9.5 fixes and no attribute changes
const {pr, sf} = ctx.scaledProd(xs);     // a significand in ±[1, 2)
ctx.scaleb(pr, sf);              // and an int64 scale (a BigInt here)

ctx.reduce("sumsq", xs);         // opcodes 28 and 29, the same fixed
ctx.reduce("sumabs", xs);        // tree over a different leaf
```

**ABI 0.7** brings two more. 754-2019 **7.1**'s status word is now the
one this package has: `ctx.flags` is a view of the library's sticky
word rather than a second copy accumulated in JavaScript, with
5.7.4's six operations over it under their own names, and 5.7.1's
three conformance predicates beside them. **9.6**'s four magnitude
forms of minimum and maximum join the four opcodes they defer to. And
clause **5.4.1**'s six formatOf operations arrive with a
**destination format as a real argument** - not a mode on the context,
because a context that carried one would make `ctx.add(x, y)` mean
different things depending on state set somewhere else.

```js
const c = await Context.open(64);
c.lowerFlags(FLAGS_ALL);         // 5.7.4, and the only thing that can
c.add(1e308, 1e308);             // lower a flag - the library never does
c.testFlags(FLAG_OVERFLOW);      // true; c.flags is the library's word
const saved = c.saveAllFlags();
c.restoreFlags(saved, FLAGS_ALL);     // RESTORES, so a flag low in
                                 // `saved` comes back low
c.is754version2019();            // true; 2008 is false, and cft.h and
                                 // docs/COMPLIANCE.md say exactly why

c.maxMag(3, -3);                 // +3: equal magnitudes are 9.6's
                                 // "otherwise", so it defers to maximum

c.formatOfDiv("fp32", a, b);     // operands binary64, result binary32,
                                 // ONE rounding - not a binary64 divide
                                 // converted down, which rounds twice
                                 // and lands one ulp low on operands
                                 // the format descriptors can construct
c.mapFormatOf("fma", "fp32", as, bs, cs);   // the same over arrays
```

**Two shapes are worth naming**, because both are the C's rather than
a JavaScript convenience. The `to_` conversions keep cft.h's two-call
sizing protocol underneath: `toDecimal()` runs it for you and hands
back a string, and `toDecimalInto(x, cap)` exposes it raw - a `cap` of
0 asks for the length and refuses, a `cap` one byte short refuses with
the length still set and **nothing written**, because this library does
not truncate a number. And every integer at this boundary is a BigInt:
a scaled product's scale, `pown`'s exponent, `scaleb`'s. They are
int64 in the contract, a JS number stops being an integer above 2^53,
and a value that lost its low bits on the way in would be a wrong
answer wearing a plausible one's clothes.

```js
const ctx = await Context.open(128);
ctx.exp(1).toString();          // e correctly rounded to 113 bits, as
                                // that binary value's exact decimal
ctx.withRounding("rup").log(2); // the same question, rounded the other way
ctx.map("hypot", xs, ys);       // one call for the whole array

ctx.sinpi(1).sign;              // 0 - sinPi(1) is +0, sinPi(-1) is -0
ctx.atanpi(ctx.inf(0));         // exactly 1/2, and it raises nothing
ctx.atan2(y, x);                // y FIRST, the C order and cft.h's
ctx.atan2pi(ctx.zero(0), ctx.zero(1));   // exactly 1: (+0, -0) is the
                                         // negative real axis, not zero
```

**`atan2` and `atan2pi` take y first**, everywhere in this package:
`ctx.atan2(y, x)`, `y.atan2(x)` on a `Float`, and `ctx.map("atan2",
ys, xs)` in a batch. That is cft.h's order and C's, and it is checked
by running it rather than by reading it - swapping the two pointers
in the wrapper fails two named tests and every transcendental vector
set (see the measurements below).

What the eleven have in common is what they do *not* need: an argument
reduction against pi. `sinPi`'s reduction is x mod 2, a mask on the
encoding, so it is exact at every magnitude - `ctx.sinpi(maxFinite)` is
a zero decided by integer arithmetic. `sin`, `cos` and `tan` of a
*radian* argument are a different problem and are not here.

**Correctly rounded** is the whole point, and it is not the usual
promise. Not "accurate to an ulp", not "faithful", not
"algorithm-defined": the result is the mathematical value rounded once
in the context's attribute, so every correct implementation returns
the same encoding and this one can be scored against any of them.
`Math.exp` cannot make that promise on any JavaScript engine, at any
precision, and neither can libm. The exact cases are decided by exact
arithmetic rather than by a tolerance - `exp(0)` is 1 with no inexact
flag, `log2(1024)` is 10, `hypot(3, 4)` is 5 - and 754-2019 clause
9.2.1's special values hold in full, including the rows
implementations most often differ on: `pow(x, ±0)` is 1 for any `x`
including a quiet NaN, `pow(1, y)` is 1 for any `y`, `hypot(±inf, y)`
is +inf even against a NaN, `log(±0)` is -inf with divideByZero
rather than invalid, `sinPi(1)` is +0 and `sinPi(-1)` is -0 - the
sign of the *argument* - `tanPi(1)` is -0, `tanPi(1/2)` is an infinity
with divideByZero rather than overflow, and `atan2(±0, -0)` is ±pi
rather than a zero, because a minus-zero denominator names the
negative real axis. A *signaling* NaN is not covered by those rows
and raises invalid like everywhere else in this contract - deliberately
unlike C's `pow(sNaN, 0)`, and cft.h says so. The one asymmetry worth
knowing: a *quiet* NaN beats `pow`'s table and loses to `atan2`'s.

The exact sets are enumerations with proofs behind them rather than
tolerances. Niven's theorem bounds the forward ones - `sinPi` and
`cosPi` exact exactly at the half-integers, `tanPi` at the quarter-
integers - and Hermite-Lindemann bounds the inverses to their zeros,
which is why `asinPi(±1)` is exactly ±1/2 while `asinPi(1/2)` is
exactly 1/6 and *inexact*: rational, but not a dyadic rational.
docs/TRANSCENDENTALS.md carries both arguments.

These are host operations: no device pass, no bus word, and nothing
here computes them - each call is one `cftw_*` call on bytes, exactly
like every other operation in this package.

## What this is a drop-in for: nothing, on purpose

The Python package next door (`bindings/python/cftmpfr`) is a drop-in
for a real thing - the gmpy2 `ieee(n)` context, which is how people
already write reproducible binary floating point in Python. There is
no JavaScript equivalent to slot into, and pretending otherwise would
be the dishonest move. Checked on 2026-09-02, against the versions npm
serves today:

| package | version | what it models | why not |
|---|---|---|---|
| `decimal.js` | 10.6.0 | arbitrary-precision **decimal** | wrong radix. Its `precision` counts decimal digits and its rounding modes round decimals; binary32/64/128/256 is a different question |
| `bignumber.js` | 11.1.5 | arbitrary-precision decimal | same |
| `big.js` | 7.0.1 | arbitrary-precision decimal | same |
| `gmp-wasm` | 1.3.2 | GMP + **MPFR** in wasm - genuinely binary | closest thing there is, and still not it: its `getFloatContext` takes `precisionBits` and a rounding mode and nothing else. No exponent bounds, no subnormalization - `mpfr_set_emin/emax` and `mpfr_subnormalize` exist only on the raw `gmp.binding` surface - so it is unbounded-exponent MPFR, not an interchange format. Its fifth rounding mode is MPFR's `RNDA` (away from zero for **every** inexact value), which is not roundTiesToAway |
| the language | - | `number` is binary64; `Float64Array`/`Float32Array` | nothing wider exists, and nothing carries flags |

So the shape here is the honest one: **the C ABI projected one to one,
plus a Context/Float layer of the same shape as cftmpfr's** - because
that shape (a precision, an attribute, sticky flags) is what numerical
code is written in, not because it imitates a particular package.
`lib.mjs` is the ABI, `core.mjs` is the shape, and anything cft.h
documents is reachable without going through the second layer.

If someone does want MPFR interop, the path is the one cftmpfr already
uses and needs no new semantics: integer significand and exponent
through `Float.bits` / `Context.fromBits`, never a decimal detour.

## Encodings are bytes, and never a JS number

The wrapper's central rule, and the reason the API looks the way it
does:

* **`Uint8Array` is the transport.** Dense, little-endian,
  `cft_format_size(fmt)` bytes per element - which is what cft.h says
  a buffer element is, so an array of them goes into `cft_run`
  unconverted. `Float.bytes` gives you a copy.
* **`BigInt` is the scalar spelling of the same bits.** `Float.bits`
  and `Context.fromBits` are exact at 256 bits, which is the point;
  JS's `number` is not.
* **`number` appears only where its name says so.** `fromNumber` and
  `toNumber` convert through `cft_convert` - exact when widening,
  correctly rounded by the *library* when narrowing. Nothing else in
  the package takes or returns one, because a binary64 cannot hold an
  fp128 and would canonicalise a NaN payload on the way through.
* Mixing formats is refused, not silently widened: `convert()` is how
  you change format, and it is a library call with flags.

## Decimal strings: exact, or rounded by libcft, or refused

There is no `strtod` here and no second implementation of rounding -
the same rule `cftmpfr` keeps, reached a different way.

**Out** (`Float.toString()`) is the **exact** decimal. Every binary
float is a finite decimal, so this always terminates and always reads
back to the same bits; no library and no agreement about "shortest" is
involved. Zeros keep their sign (`-0`), and `nan` / `inf` / `-inf` are
written as words. The price is length, stated rather than hidden: the
smallest binary256 subnormal is 2<sup>-262378</sup>, whose exact
decimal runs to roughly 183,000 significant digits. Ordinary values
are short.

**In** (`Context.from(str)` / `parse`), in order:

1. If the value is exactly representable, the codec packs it. No
   rounding happens, so no flag is raised. This covers everything
   `toString()` writes, at any magnitude.
2. Otherwise, if the decimal is an **exact numerator over an exact
   denominator** in this format, the library rounds it: one `cft_div`
   (for `M / 10^k`) or one `cft_mul` (for `M x 10^e`) or one
   `cft_cvt_from_u64`, on operands the codec produced exactly. One
   rounding, in the context's own attribute, with the library's own
   flags. `"0.1"` at binary64 is `0x3fb999999999999a` with inexact
   set, which is the correctly rounded answer.
3. Otherwise it is **refused**, with the window in the message.

The window is a property of the precision, computed rather than
tabulated (`pow5Limit`): about 7 significant digits and |exponent| ≤ 10
at binary32, 15 and 22 at binary64, 34 and 48 at binary128, 71 and 102
at binary256. Inside it, this package rounds decimals under
**roundTiesToAway** as happily as under the other four - which the
Python drop-in cannot do at all, because MPFR has no such attribute and
cftmpfr will not substitute its own. Outside it, `"1e100"` at binary64
is a refusal rather than a guess (it is fine at binary256, where the
format holds 10<sup>100</sup>'s factors exactly).

Two consequences worth naming. The sign of a zero needs no special
handling on the rounded path - a negative decimal reaches the library
with its sign, and rounding never changes one - which is the bug
`bindings/python` had to fix by hand at `b694a3f` when a gmpy2 version
dropped it. And specials are lexed here, never handed to a parser, for
the reason `8c347fd` records: `toString()` writes them without a
library, so `parse` has to read them without one or the round trip is
asymmetric by construction.

## Determinism: what a Node consumer can and cannot rely on

**Can.** The bits. The module is libcft's software backend compiled to
wasm32; its arithmetic is uint32 limbs and uint64 intermediates with no
host float anywhere, and WebAssembly specifies integer arithmetic
totally. Two compliant engines cannot disagree, so the same call
returns the same encoding on every platform, browser or node, today and
after an engine upgrade. Reductions have a fixed tree shape that is
part of the contract, so a sum is not "whatever the accumulation order
was". Flags are the contract's definitions, per call and sticky - and
since ABI 0.7 the sticky half is **the library's own word** (754-2019
7.1), read through `ctx.flags` rather than accumulated separately
here. It is per DEVICE, so `withRounding()` and every other context
over the same handle see one word, which is 7.1's own granularity: the
flags belong to the computation, not to the attribute it ran under.
`lastFlags` stays per call and per object.

**Cannot.** Anything that passes through a JS `number`: it is a
binary64, so it cannot carry binary128/256 at all and cannot carry a
NaN payload even at binary64. `toNumber()` is a conversion, not a view.
`JSON.stringify` of a `Float` is not defined here; move values as
`bits` (BigInt) or `bytes`. And nothing about *speed* is promised -
this is a software backend behind a wasm boundary, one `_malloc` per
scalar call. The batch surface (`map`, `reduce`) exists because one
call over an array is the shape a device wants; scalar calls are for
clarity, not throughput.

Not promised because not measured here: cross-engine agreement was
argued from the wasm spec and measured on **node 22.19.0 / V8** only.
The browser side of the same module has been run in Chrome
(bindings/wasm/README.md), which is the same engine family. No other
runtime - Bun, Deno, Safari, Firefox - has been tried.

## What has been verified, and when

**2026-09-02, Windows 11, node 22.19.0, wasm module sha256
`7504440ef7ca5c9d…`** (identical to the module inside
`bindings/wasm/conformance.html` - `node bindings/wasm/verify.mjs`
checks that, and refuses to report a replay if they differ):

* `node conformance.mjs` - **236,000 cases over 20 sets, zero
  mismatches**, in 1.9 s. The replay is `cft_conformance()` itself over
  MEMFS, not a JS restatement of it. Its negative control was run too:
  one expected value in `fp128-rup.jsonl` flipped by a hex digit stops
  the run at case 4,322 and prints the library's own disagreement - op,
  operands, expected vs got, flags.
* `node test.mjs` - **43 tests, 0 failures**: the codec both ways and
  the exact-decimal round trip over 51 encodings per format (specials,
  both zeros, the subnormal and normal edges, 40 seeded random
  patterns); decimal parsing checked against **V8's own strtod** over
  400 random 15-digit decimals at binary64, which is an independent
  correctly-rounded oracle for that path; flags; every clause-5 entry
  point; batch-equals-scalar over 257 elements; and `cft_reduce`
  against the contract's tree shape rebuilt from scalar adds, with a
  sequential sum shown to differ. Plus a negative control that shows
  the comparisons failing on a one-bit change.
* The ABI audit runs at load: the module is asked what it calls each
  opcode and format number, and a disagreement refuses to run rather
  than computing the wrong operation quietly.

**2026-09-03, same host and node, wasm module sha256
`6ff4129e03d43682…`** - the rebuild that gave the nine their `cftw_*`
wrappers, so this package could reach them at all (package 0.3.1;
0.3.0 loaded a module that reported ABI 0.3 and exported none of the
nine, which is docs/COMPATIBILITY.md's half-step):

* `node conformance.mjs` - **300,325 cases over 40 sets, zero
  mismatches**: the 236,000 opcode cases through `cft_conformance()` in
  1.6 s as before, then **64,325 transcendental cases in 60.9 s driven
  through this package's own `Context` methods** - per case, so the
  flag word compared is that case's, then once per family through
  `map()` so the batch call is held to the scalar answer. That second
  pass is not redundancy: `cft_conformance` dispatches the nine
  internally in C and is green with or without a JavaScript surface for
  them.
* `node test.mjs` - **57 tests, 0 failures**: the 43 above plus 14 for
  the nine - the exact cases that must raise nothing at all, the
  signed zeros `expm1`/`log1p` exist for, the infinite arguments,
  `log`'s pole and its divideByZero, the canonical quiet NaN on every
  domain error, `pow`'s identities over its NaNs and the difference
  between its pole (`pow(±0, -1)`, divideByZero) and its limit
  (`pow(±0, -inf)`, +inf, silent), `hypot` preferring an infinity to a
  NaN and not overflowing on the way, the signaling-NaN break from C,
  all nine at all four formats, the `Float` methods, and
  batch-equals-scalar over 129 elements for each of the nine.
* Negative control for the new surface, run and reverted: `cftw_pow`'s
  two operand pointers swapped in `wasm_api.c` and the module rebuilt.
  6 of the 57 tests fail by name (`pow(2,3): expected 8, got 9`),
  `conformance.mjs` fails all twenty transcendental sets at
  `fp32-transcend.jsonl:1543`, and - the part worth writing down -
  the `cft_conformance` replay above stays green throughout, because
  it never calls the wrapper. That is the half-step reproduced on
  purpose, and the reason the second pass exists.

**2026-09-03, later the same day, same host and node, wasm module
sha256 `ee66812e4bd17de7…`** - the rebuild that gave the eleven
phase-2 trigonometrics their `cftw_*` wrappers, in the same commit as
the rebuild itself so this package never shipped against a module
reporting 0.4 with none of them in it (package 0.4.0; the ABI test
reads 0.4):

* `node conformance.mjs` - **365,845 cases over 40 sets, zero
  mismatches**: the 236,000 opcode cases through `cft_conformance()` in
  1.7 s, then **129,845 transcendental cases in 108.2 s driven through
  this package's own `Context` methods** - the same twenty files,
  carrying all twenty functions now - per case and then once per
  family through `map()`.
* `node test.mjs` - **74 tests, 0 failures**: the 57 above plus 17 for
  the eleven - `sinPi`'s zeros carrying the argument's sign, `cosPi`'s
  unsigned half-integer zero, `tanPi(1) = -0` and the pole at a
  half-integer signalling divideByZero rather than overflow, the
  Pi-forms' larger exact table including `atanPi(±inf) = ±1/2` raising
  nothing, `asinPi(1/2) = 1/6` shown inexact **and shown to be 1/6 in
  all five attributes** by deriving it from `cft_div` rather than
  transcribing a constant, the inverses exact only at their zeros,
  `atan2(±0, -0) = ±pi` inexact against `atan2Pi(±0, -0) = ±1` exact,
  the operand order, a quiet NaN losing to `atan2`'s table, the domain
  errors for `|x| > 1`, infinities invalid in `sinPi`/`cosPi`/`tanPi`,
  the signaling NaN across all eleven, `sinPi(2^80)` and
  `sinPi(maxFinite)` exact, all eleven at all four formats, the `Float`
  methods, and batch-equals-scalar over 129 elements for each.
* Negative control for the new surface, run and reverted: `cftw_atan2`'s
  two operand pointers swapped in `wasm_api.c` and the module rebuilt.
  2 of the 74 tests fail by name (`atan2(+0, -0) is pi and inexact`,
  `atan2(-0, +1) is -0`), `conformance.mjs` fails all twenty
  transcendental sets - `atan2(+0, -0)` returning -0 where the vectors
  say pi - and the `cft_conformance` replay stays green throughout, for
  the same reason as before. `atan2` is the sharper control than `pow`
  was: it takes y first, so a swap answers a plausible number for every
  input rather than failing loudly anywhere.

**2026-09-03, later again, same host and node, wasm module sha256
`5718aa19e85dad2b…`** - the rebuild that gave the nine phase-3 functions
their `cftw_*` wrappers, in the library's own step to 0.5 (package
0.5.0; the ABI test reads 0.5):

* `node conformance.mjs` - **478,915 cases over 40 sets, zero
  mismatches**: the 236,000 opcode cases through `cft_conformance()`,
  then **242,915 transcendental cases in 154.4 s driven
  through this package's own `Context` methods** - the same twenty
  files, carrying all twenty-nine functions now, including sin, cos
  and tan of every power of two binary64 holds and of the arguments
  nearest a multiple of pi/2 that the reduction's worst-case search
  finds - per case and then once per family through `map()`.
* `node test.mjs` - **79 tests, 0 failures**: the 74 above plus
  the nine's exact cases (the zeros, and `tanh(±inf) = ±1` raising
  nothing), sin/cos/tan of an infinity invalid, acosh below 1 and
  atanh past 1 invalid with `atanh(±1)` a pole signalling divideByZero,
  one directed rounding per neighbour family at the smallest
  subnormal, and the binary64 worst case of the reduction -
  `sin(0x1.6ac5b262ca1ffp+849)` = 1 to nearest and nextDown(1)
  downward, its cosine the reduced argument with mpmath's bits - and
  `sin(2^1023)` finite and nonzero through the wasm.

**2026-09-03, later again, same host and node, wasm module sha256
`e8611510973d1081…`** - the rebuild that gave the four packages of ABI
0.6 their `cftw_*` wrappers, in the library's own step to 0.6 (package
0.6.0; the ABI test reads 0.6). 24 new wrappers, 67 exports to **91**:

* `node conformance.mjs` - **1,527,314 cases over 148 set replays,
  zero mismatches**. The **881,657 published cases over all 84 sets**
  through `cft_conformance()` in 669.5 s - 236,000 opcode, 533,265
  transcendental, 89,616 augmented, 8,960 reduction, 13,816 character
  - and then **645,657 of them again in 707.1 s through this package's
  own `Context` methods**, over the 64 sets that are not opcode sets:
  533,265 transcendental over 20, 89,616 augmented over 4, 8,960
  reduction over 20 and 13,816 character over 20. Per case, so the
  flag word compared is that case's, then as arrays wherever the C has
  a batch shape - `map()` for the elementwise families,
  `mapFromDecimal`/`mapFromHex` for 5.12's batch half. That second
  pass is not redundancy: `cft_conformance` dispatches every one of
  those internally in C and is green with or without a JavaScript
  surface for them.
* `node test.mjs` - **104 tests, 0 failures**: the 79 above plus 25
  for the four packages. Table 9.1's new exact cases (`exp2m1` at
  every integer, `exp10` where 5ⁿ fits, `log2p1`/`log10p1` with 1 + x
  formed exactly - shown by `log2p1(2^-1000)` being x/ln 2 where a
  rounded 1 + x would give an exact +0), `rSqrt(-0) = -inf` where
  MPFR returns +inf, the seven rows where `powr` is not `pow`,
  `pown(qNaN, 0) = 1` against `compound(-2, 0)` invalid, `rootn(-0, 2)
  = +0` against `squareRoot(-0) = -0`, and the int64 extremes both
  going through as BigInts. Then 5.12: `Pmin` from the library (9, 17,
  36, 73) with a round trip at it over ~50 interesting encodings per
  format, the exact conversion against a digit count, the sizing
  protocol's three answers including a one-byte-short buffer refused
  with nothing written, the syntax refusals (including `0x1.8` without
  its required binary exponent), and an sNaN payload surviving both
  directions as `snan(0x5)`. Then 9.5: `r + e` reconstructed exactly
  in BigInt over 180 pairs and again through the library's own
  binary128 add where the exact sum fits it, `roundTiesTowardZero`
  shown differing from ties-to-even at a midpoint whose lower
  neighbour is odd, underflow **without** inexact, and the NaN and
  overflow rows giving the same value in both outputs. Then 9.4:
  `sumsq == dot(x, x)` and `sumabs == sum(|x|)` at every format and
  seven lengths, the one infinity-before-NaN row where they are not
  the composition, `n == 1`'s different leaf for each, and a scaled
  product's `pr * 2^sf` reconstructed through `scaleb` and again in
  BigInt.
* Negative control for the new surface, run and reverted:
  `cftw_scaled_prod_diff`'s two operand pointers swapped in
  `wasm_api.c` and the module rebuilt. **1 of the 104 tests fails by
  name** (*the scaled sums and differences are their compositions, a
  first: scaledProdDiff n=1: pr is the composition's*),
  `conformance.mjs` fails **all 20 reduction sets** -
  `expected 0x3fa59621 scale 25`, `got 0xbfa59621 scale 25`, the same
  value with one sign bit - and, the part worth writing down, the
  `cft_conformance` replay above **stays green throughout**, because
  it never calls the wrapper. That is the half-step reproduced on
  purpose, and the reason the second pass exists. Reverted and
  rebuilt, the module hash reproduces.

**2026-09-04, same host and node (22.19.0, Windows 11,
DESKTOP-T33SK86), wasm module sha256 `04c3aad8748c9555…`** - the
rebuild that gave the two packages of ABI 0.7 their `cftw_*` wrappers,
in the library's own step to 0.7 (package **0.7.0**). 20 new wrappers,
91 exports to **111**. The ABI test no longer names a version: it
reads `CFT_ABI_VERSION_MAJOR/MINOR` out of `host/include/cft.h` and
asserts the module agrees, so it says *this module was built from this
tree* and goes green on the integrator's bump with nothing here to
change. On this run both read **0.6**, because the bump is the
integrator's single commit for the whole step.

Both figures below come from one standardized run on a
clean tree, `bash verify/run.sh --fresh --only vectors,node,wasm`, run
id **20260904-030316-6b9a845** (`vectors` 275 s, `node` 1438 s, `wasm`
1100 s, **PASS, nothing skipped**).

* `node conformance.mjs` - **2,055,270 cases over 316 set replays,
  zero mismatches**. **1,223,635 cases over all 168 sets**
  through `cft_conformance()` in 523.1 s - the opcode sets, 533,265
  transcendental, 89,616 augmented, 8,960 reduction, 13,816 character,
  and the two new families, 9,728 magnitude (9.6) and 176,250 formatOf
  (5.4.1) - and then **831,635 of them again in 637.2 s through this
  package's own `Context` methods**, over the 148 sets that are not
  opcode sets. Per case, so the flag word compared is that case's,
  then as arrays wherever the C has a batch shape - `map()` for the
  elementwise families including 9.6's four, `mapFormatOf()` for
  5.4.1's six, which `map()` cannot carry because their result is not
  the context's format. That second pass is not redundancy:
  `cft_conformance` dispatches every one of those internally in C and
  is green with or without a JavaScript surface for them.
* `node test.mjs` - **125 tests, 0 failures**: the 104 above plus 21
  for the two packages. The status word is checked to BE the library's
  word by the only means that distinguishes one word from two -
  `raiseFlags` touches nothing but the C, so a JavaScript copy would
  still read 0 after it - then the device granularity (`withRounding`,
  and the temporary context `toNumber` opens, all see one word), three
  calls leaving four flags standing with nothing in the library
  lowering them, the exceptionGroup forms, the save/restore round trip
  proving `restoreFlags` **restores rather than ORs**, `testSavedFlags`
  as a pure predicate, a mask outside `FLAGS_ALL` refused, and a fresh
  device opening lowered. The predicates answer no/no/yes, and 2008's
  no is given its reason: `minimumMagnitudeNumber(sNaN, 3)` returns 3
  **and** signals invalid, which is the 2019 row that replaced 2008's
  `minNumMag`. 9.6's four are read as the deferral they are -
  `minMag(+3, -3)` is -3 and `maxMag(+3, -3)` is +3 either way round,
  the zeros come from the base operation, a quiet NaN loses to the
  number in the `...Number` forms only, a signaling NaN raises invalid
  and nothing else can be raised at all, and the answer is one
  operand's own encoding bit for bit.
* And 5.4.1, where the tests are the argument: the same-format pairs
  are asserted to **be** `cft_run`/`cft_div`/`cft_sqrt` bit for bit at
  every format and attribute; widening is asserted to be
  convert-then-operate with the same flags; and the
  **double-rounding witnesses are rebuilt from the format descriptors
  alone** - the construction `python/cft_golden/formatof.py`'s
  `double_rounding_witness()` derives, ported rather than tabulated -
  for division, square root and fused multiply-add on all six
  narrowing pairs, **18 in all**. Each asserts BOTH halves: the single
  rounding is `nextUp(1)` in the destination, the composed route
  (round in the source, convert down, both through this same library)
  is `1.0`, and the two differ by one ulp with the composed one low. A
  witness that stopped separating them would be checking that two
  identical things are identical. Then the destination's exceptions on
  the destination's grid: the binary64 → binary32 row a hair above
  half the least subnormal and its negation, where underflow and
  inexact appear that the source had no reason to raise; an overflow
  binary64 does not have; and a signaling NaN giving the
  **destination's** canonical quiet NaN.
* Negative control for the new surface, run and reverted:
  `cftw_formatof_sub`'s two operand pointers swapped in `wasm_api.c`
  and the module rebuilt (sha256 `2796f430c7d2c265…`, a different
  module). **1 of the 125 tests fails by name** - *a same-format
  formatOf call IS the operation that was already here* -
  `conformance.mjs` fails **all 80 formatOf sets** through `Context`'s
  own methods (`fp32-to-fp32-formatof.jsonl:41`, `expected
  0x80000001, got 0x00000001`, the same value with one sign bit) while
  its `cft_conformance` pass **stays green throughout**, and
  `bindings/wasm/verify.mjs` says the same in its two passes. The row
  worth keeping is which test caught it: the `mapFormatOf`
  batch-versus-scalar test stayed GREEN, because the control changes
  both sides identically and that test compares the package with
  itself. The one that fails is the one comparing formatOf against
  `cft_run`/`cft_div`/`cft_sqrt`. Reverted and rebuilt, the module
  hash reproduces.

The gate for this step was
`bash verify/run.sh --only vectors,node,wasm`, so the library's own
stages did not run here: they belong to the two package commits that
landed the C, and nothing under `host/`, `python/` or `vectors/` was
touched by this step. `CFT_ABI_VERSION_MINOR` still reads 6, which is
exactly why the ABI test above reads the header rather than naming a
number - the integrator bumps it once for the whole 0.7 step.

Not verified: no other JS runtime, no device backend (wasm32 has no
PCIe; `Context.open` is always the software backend here), and no
performance claim. The timings above are measurements, not promises:
they are one `_malloc` per scalar call across a wasm boundary, at
binary256 for a quarter of them, the radian three reducing against pi
inside the module, and - since 0.6 - the character conversions
allocating a buffer the library sized, which for an fp256 exact
decimal is 183,600 bytes.

## Files

```
index.mjs        the public surface
lib.mjs          the module load, the cftw_* table, the ABI audit
core.mjs         Context and Float, the codec, the decimal contract
cft_node.js      committed build product: emcc -sENVIRONMENT=node
cft_node.wasm    committed build product: THE PAGE'S MODULE, byte for byte
test.mjs         everything the vectors cannot express
conformance.mjs  the vectors replay - the package's conformance test;
                 cft_conformance for all 168 sets, then this package's
                 own methods for the six families that are not
                 opcodes: transcendental, augmented, reduction,
                 character, minmaxmag, formatof
```

`cft_node.js` and `cft_node.wasm` are built by
`bash bindings/wasm/build.sh` (stage 5) from the same sources and the
same flags as the page's module, inside the same pinned emsdk image,
and copied here. Rebuild them there, not here; there is no build step
in this directory and no dependency to install.

**2026-09-04, rebuilt on the bumped tree, wasm module sha256
`a1f0a4715516d3f6…`** - the block above was measured before `cft.h` moved
to 0.7, and the ABI test refused the old module on the bumped tree
("expected 0.7, got 0.6"), as it should. The module was rebuilt twice
in the container on the 0.7 tree, byte-identical, and `test.mjs` and
`conformance.mjs` re-ran under `bash verify/run.sh --fresh --only
vectors,node,wasm`, run id `20260904-054715-2216e62`: the same test and case counts as
above, the ABI test now reading 0.7 from the header and the module
alike.
