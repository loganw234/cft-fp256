# libcft in Node - the C ABI, one to one, plus a Context

`bindings/wasm` put the contract in a browser tab. This puts it in a
`node` process: the **same wasm module**, byte for byte, with a
JavaScript wrapper instead of a page. IEEE binary32, binary64,
binary128 and binary256, all five rounding attributes, exact flags,
and results that are libcft's bits and nothing else.

```bash
node bindings/node/test.mjs         # 43 tests, no dependencies
make vectors                        # from the repo root, once
node bindings/node/conformance.mjs  # 236,000 published cases
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

Not verified: no other JS runtime, no device backend (wasm32 has no
PCIe; `Context.open` is always the software backend here), and no
performance claim.

## Files

```
index.mjs        the public surface
lib.mjs          the module load, the cftw_* table, the ABI audit
core.mjs         Context and Float, the codec, the decimal contract
cft_node.js      committed build product: emcc -sENVIRONMENT=node
cft_node.wasm    committed build product: THE PAGE'S MODULE, byte for byte
test.mjs         everything the vectors cannot express
conformance.mjs  the vectors replay - the package's conformance test
```

`cft_node.js` and `cft_node.wasm` are built by
`bash bindings/wasm/build.sh` (stage 5) from the same sources and the
same flags as the page's module, inside the same pinned emsdk image,
and copied here. Rebuild them there, not here; there is no build step
in this directory and no dependency to install.
