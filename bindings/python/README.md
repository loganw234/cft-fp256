# cftmpfr - libcft as a drop-in MPFR accelerator for Python

The way MPFR gets used from Python for reproducible binary floating
point is gmpy2 in an IEEE emulation context - `gmpy2.ieee(256)`,
precision pinned to an interchange format, exponent range bounded,
subnormals via `mpfr_subnormalize`, flags observed. This package is
that usage pattern, computed by
[libcft](../../host/include/cft.h) instead: same bits, whole arrays
per call, and the identical calls drive the CFT FPGA tile when one is
present.

"Same bits" is a proven claim, not a goal. libcft's software backend
agrees with the project's golden model across its full differential
and conformance suites, with 23.9 billion CPU-checked cases at
binary32/64 - and with **GNU MPFR itself**:
[host/tools/mpfr_check.c](../../host/tools/mpfr_check.c) drives add,
sub, mul, fma, div and sqrt against MPFR's IEEE emulation at all four
precisions under all five rounding attributes - **999,000 cases,
values and flags, zero disagreements**. One asterisk, stated rather
than buried: MPFR has no roundTiesToAway, so that suite's RNDNA rows
compare against a ties-to-away oracle *built from* pure-MPFR
intermediates (the p+1 guard/sticky construction) - there is no
native MPFR mode to compare against, which is also why cftmpfr's
RNDNA is worth having: it is the 754 attribute MPFR is missing.

The package is pure stdlib `ctypes` - no build step, no binding
generator, no compiled extension. That is not a convenience, it is
the design: the C ABI is the product's portability story, and this
package is the demonstration that reaching it costs one `CDLL` and a
page of argtypes. gmpy2 and numpy are both optional; without gmpy2
the decimal-string and inexact-conversion paths refuse loudly instead
of guessing, and everything else works.

## Quickstart

Build the library once (from the repo root):

```bash
make -C host              # produces host/cft.dll or host/libcft.so
```

Then, from this directory (or with it on `PYTHONPATH`; set `CFT_LIB`
if the library lives elsewhere):

```python
from cftmpfr import Context, batch

ctx = Context(237)                # binary256; or 24/53/113, or "binary64"
x = ctx("1.5")                    # decimal parse via gmpy2, correctly rounded
y = ctx.sqrt(x + 2)               # every op is a libcft call
print(y, ctx.flag_names(ctx.last_flags))

# bit-exact gmpy2 interop, integer-significand path, never through repr
import gmpy2
m = y.to_mpfr()
assert ctx.from_mpfr(m).same_bits(y)

# the batch surface: one C call per op, flags OR'd across the array
xs = [ctx.from_int(i) for i in range(1, 100001)]
sq, flags = batch.sqrt(ctx, xs)
inv, flags = batch.div(ctx, ctx.from_int(1), sq)   # broadcast numerator
```

Rounding is by MPFR's names - `RNDN`, `RNDZ`, `RNDD`, `RNDU` - plus
`RNDNA` (ties-to-away). Names only, no numbers: the CFT and MPFR
enums number the directions differently, and a silently transposed
rounding mode is the worst bug this package could ship.

Run the demo and the tests:

```bash
python demo_mpfr_dropin.py        # 100k-element binary256 workload
python -m pytest test_cftmpfr.py  # 80 tests; skips gmpy2/numpy parts if absent
```

## What the demo measures, honestly

A degree-8 Horner polynomial (8 fma), a square root and a division
per element, 100,000 elements at binary256, gmpy2 loop vs cftmpfr
batch, then **every phase compared element by element** - 300,000
encodings, bit-identical. The parity is the claim and it does not
move. The timings do, so they are dated. Windows, mingw64-built
cft.dll, software backend, gmpy2 2.2.1 / MPFR 4.2.1, **2026-09-02**:

| phase  | gmpy2 loop | cftmpfr batch | speedup |
|--------|-----------:|--------------:|--------:|
| horner (8 fma) | 2625 ns/elem | 3058 ns/elem | 0.86x |
| sqrt   | 494 ns/elem | 10747 ns/elem | 0.05x |
| div    | 619 ns/elem | 8798 ns/elem | 0.07x |

One run of three; the horner speedup came out 0.85x, 0.86x and 0.94x.
The first recording of this table, on 2026-08-31, had that row at
3617 vs 3401 ns/elem - a 1.06x win - and said the fma family "edges
out a very well-tuned MPFR". It does not, here, today: the gmpy2 loop
got about a quarter faster on this machine while libcft's batch
barely moved, and the phase crossed from a small win to a small loss.

Neither number is the batch story. What the batch path actually buys
is one interpreter crossing instead of N, and at binary256 that is
worth about as much as MPFR's own per-element cost, so which side
wins is decided by whatever else changed that week. A spot check at
the narrower formats on 2026-09-02 put the same workload shape at
1.2-1.6x in libcft's favour at binary32/64/128 - but that was an
ad-hoc script, not this demo, which is fixed at binary256; nothing in
this repository regenerates those three numbers, so treat them as an
indication and not as a measurement.

div and sqrt are honest losses on the *software* backend, and that
part has not moved: libcft computes them as a fixed
seed/Newton/exact-residual sequence of 25-30 elementwise passes (the
price of correct rounding built from an FMA, and the same sequence on
every backend), while MPFR divides natively. On the tile those passes run at hardware speed;
the table is the cost of the contract on a laptop, not the cost of
the contract.

## Scope, precisely

* **Accelerated:** MPFR **as an IEEE binary-format emulator** - the
  `mpfr_set_emin`/`set_emax`/`mpfr_subnormalize` recipe from the MPFR
  manual, which is exactly what `gmpy2.ieee()` constructs - at
  precisions 24, 53, 113 and 237 (binary32/64/128/256).
* **Out of scope:** raw MPFR with its unbounded exponent range, or
  any other precision. libcft computes interchange formats; anything
  else would be pretending.
* **NaNs:** libcft arithmetic returns the one canonical quiet NaN
  (sign 0, quiet bit, payload 0) and raises invalid for signaling
  NaNs, per [docs/DETERMINISM.md](../../docs/DETERMINISM.md). MPFR
  keeps neither payloads nor a NaN sign, so mpfr interop is by class
  - lossless in practice, because everything MPFR can say about a
  NaN survives the trip.
* **Flags:** the contract's definitions (underflow = tininess after
  rounding AND inexact), OR'd across each batch call, sticky on the
  Context like MPFR's own flag model.
* **Conversions:** bit-exact or refused. The only rounding ever
  performed on the way in or out is gmpy2's own (decimal strings,
  over-long ints, float narrowing); with gmpy2 absent those refuse
  with instructions, and under RNDNA they refuse because MPFR cannot
  round ties-to-away and this package will not substitute its own
  arithmetic - a second implementation of the semantics is how
  bit-identity dies.

## The device backend is the same call

`Context(237)` opens libcft's software backend: no card, no driver,
no Linux. `Context(237, artifact="tile.xclbin")` is `cft_open()` with
an artifact path - the FPGA tile behind the identical API, returning
identical bits; `ctx.backend` tells you which one answered. Nothing
in user code changes, which is the adoption story of the whole
project: port once against the software backend, add hardware when
the problem earns it. A batch call is already shaped like the device
wants it - one dense buffer per operand, one flag word out - so the
speedup arrives without a rewrite.

A `Context` is not thread-safe (a `cft_device` is not; cft.h says
so). Open one per thread; they are cheap.

## Files

```
cftmpfr/_lib.py    the ctypes binding: discovery, prototypes, errors
cftmpfr/core.py    Context and Float: scalars, conversions, flags
cftmpfr/batch.py   whole-array ops and the contract's tree reductions
demo_mpfr_dropin.py   the workload above, timed and bit-verified
test_cftmpfr.py       conversions, gmpy2 parity, batch==scalar, flags,
                      refusals, and a negative control that proves the
                      comparison can fail
```

No packaging ceremony: it is a plain package directory. Copy it, put
it on `PYTHONPATH`, or vendor it next to your code; drop the shared
library beside `_lib.py` or point `CFT_LIB` at it.
