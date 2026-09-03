# libcft in Node - the C ABI, one to one, plus a Context

`bindings/wasm` put the contract in a browser tab. This puts it in a
`node` process: the **same wasm module**, byte for byte, with a
JavaScript wrapper instead of a page. IEEE binary32, binary64,
binary128 and binary256, all five rounding attributes, exact flags,
and results that are libcft's bits and nothing else.

```bash
node bindings/node/test.mjs         # 57 tests, no dependencies
make vectors                        # from the repo root, once
node bindings/node/conformance.mjs  # 300,325 published cases
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
`exp2`, `log`, `log1p`, `log2`, `log10`, `pow`, `hypot` - on all three
layers: the raw `cftw_*` exports, `Context`/`Float` scalars, and
`map()` over an array.

```js
const ctx = await Context.open(128);
ctx.exp(1).toString();                        // e to 113 bits, exactly
ctx.withRounding("rup").log(2);               // the other direction
ctx.map("hypot", xs, ys);                     // one call for the array
```

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
is +inf even against a NaN, and `log(±0)` is -inf with divideByZero
rather than invalid. A *signaling* NaN is not covered by those rows
and raises invalid like everywhere else in this contract - deliberately
unlike C's `pow(sNaN, 0)`, and cft.h says so.

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
was". Flags are the contract's definitions, per call and sticky.

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

Not verified: no other JS runtime, no device backend (wasm32 has no
PCIe; `Context.open` is always the software backend here), and no
performance claim. The 60.9 s for 64,325 transcendental cases is a
measurement, not a promise: it is one `_malloc` per scalar call across
a wasm boundary, at binary256 for a quarter of them.

## Files

```
index.mjs        the public surface
lib.mjs          the module load, the cftw_* table, the ABI audit
core.mjs         Context and Float, the codec, the decimal contract
cft_node.js      committed build product: emcc -sENVIRONMENT=node
cft_node.wasm    committed build product: THE PAGE'S MODULE, byte for byte
test.mjs         everything the vectors cannot express
conformance.mjs  the vectors replay - the package's conformance test;
                 cft_conformance for the opcode sets, this package's
                 own methods for the twenty transcendental ones
```

`cft_node.js` and `cft_node.wasm` are built by
`bash bindings/wasm/build.sh` (stage 5) from the same sources and the
same flags as the page's module, inside the same pinned emsdk image,
and copied here. Rebuild them there, not here; there is no build step
in this directory and no dependency to install.
