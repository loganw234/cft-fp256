# Compatibility

What can call this library today, what is on its way, and what
"compatible" means here - because in this project it is not a
feelings word. The compatibility test is the identity protocol in
`host/examples/`: every binding drives the same vectors through the
same library and must print byte-identical checksum lines, and the
canonical four are

    fp32   0x9af9d3973816adcf
    fp64   0x04110a4c30c6df4d
    fp128  0xb815aa4a3a3eb024
    fp256  0x0eea048c14040a4e

on every platform, from every language, forever (a change to these is
a contract change, not a refresh). "Verified" below means that diff
has actually been run and matched, on the named platform and date,
and the claim regenerates with `make -C host examples-lang` wherever
the toolchain exists. Nothing here is checked in CI's default lane -
toolchains are optional by design - so the honest status is recorded
per row and updated when it changes, the census way: no row says more
than its diff has shown.

Worth stating once, because it is why this comparison survives being
run from seven languages: the checksum is FNV-1a over the raw output
encodings, printed as hex. No port formats or parses a decimal
floating-point number anywhere in the line being diffed, so a locale,
a printf rounding rule, a `-0` spelling and a language's idea of `inf`
cannot get into it. The two places that came closest are handled and
say so in their own files - C# pins `InvariantGlobalization`, and R
builds the 16 hex digits out of split doubles because it has no
64-bit integer. The Fortran example is the exception that proves the
rule: it prints decimals, and it is the one example NOT in the
checksum diff - a four-line iso_c_binding demonstration whose expected
output lives in its own header and is compared by eye.

## Language bindings and examples

| Language | Path | What exists | Verified | Notes |
|---|---|---|---|---|
| C | `host/examples/vector_fma.c` | the reference example; the header IS the binding | Windows 2026-09-02 + Linux 2026-09-01 | `cft.h` is the whole contract surface |
| Fortran | `host/examples/vector_fma.f90` | example via iso_c_binding | Linux, gfortran 13.3 (`make -C host fortran`); the example's header carries no date | the constituency the C ABI was chosen for |
| Python (ctypes) | `host/examples/vector_fma.py`, `vector_fma_ctypes.py` | example + the diff/seq/reduce/divsqrt check harnesses | Windows 2026-09-02 + Linux 2026-09-01, every `make -C host test` | no build step, no generated bindings |
| Python (package) | `bindings/python/cftmpfr/` | full package: Context/Float scalar ops, batch ops, gmpy2 interop | Windows 2026-09-02 (80 tests; 300k/300k bit-identical to gmpy2) | see Drop-ins below |
| Rust | `host/examples/vector_fma.rs` | single-file example, plain rustc, static-links libcft.a (MSVC rustc included) | Windows 2026-09-02 (rustc 1.94.1, x86_64-pc-windows-msvc) | why the static link survives MSVC is in its header |
| Julia | `host/examples/vector_fma.jl` | single-file example, stdlib ccall | Linux 2026-09-01 (julia 1.12.7); checksums also match the Windows set | born UNVERIFIED, asterisk lasted one day |
| Go | `host/examples/vector_fma.go` | single-file cgo example; compiles the real cft.h (nothing transcribed), FNV from stdlib | Linux 2026-09-01 (go 1.18) | static-links libcft.a as a direct linker input |
| C# / .NET | `host/examples/VectorFma.cs` (+ minimal csproj) | single-file P/Invoke, no NuGet | Windows 2026-09-02 (dotnet 10.0.301) + Linux 2026-09-01 (dotnet 8) | resolver maps to exactly one candidate; error paths byte-identical |
| R | `host/examples/vector_fma.R` | example + the ~70-line .Call shim base R genuinely needs (it cannot pass by-value ints) | Linux 2026-09-01 (R 4.1.2) | 64-bit checksum computed exactly in split doubles - every intermediate below 2^42, proven never to round |
| Browser / WASM | `bindings/wasm/` - live at https://loganw234.github.io/cft-fp256/ | the software backend compiled to WebAssembly + a single-file conformance page (works from file://, ~1 MB, wasm ~50 KB) with drag-drop full-set replay and a compute panel incl. composed div/sqrt | Chrome 2026-09-01: embedded 4,015-case sample clean AND full 236,000-case replay clean; negative control screenshotted; two container builds byte-identical. The committed page still carries the module built that morning, which reports ABI 0.1 - see its README | bit-exact BY CONSTRUCTION - the softfloat is integer-only and wasm integer semantics are fully specified. Replays the published vectors with only a compliant browser. Browser-GPU compute is deliberately out of scope: that floating point is the nondeterminism this project exists against |
| MATLAB | - | planned (loadlibrary) | - | namechecked in cft.h; wants a licensed seat to verify honestly |
| Java | - | planned (Panama FFI) | - | waiting for the FFI story to be the obvious one |

The pattern for adding a language is deliberately boring: load the
shared library (or link the static one), declare a dozen functions,
drive the same vectors, diff the checksums. A binding that needs more
than that is evidence the ABI failed at its one job.

**Re-run 2026-09-02** on Windows 11 (mingw64 gcc 16.1.0, CPython
3.13), `make -C host clean` first because a stale object from the
other platform has poisoned a build here before: C, Python (ctypes),
Rust and C# each printed the canonical four and diffed clean against
the C example - C# byte-identical without even the
`--strip-trailing-cr` concession the Makefile allows - and the
missing-artifact stderr path matched byte for byte across C, ctypes
and Rust. `cft-selftest` replayed all twenty published sets, 236,000
cases, clean. Fortran, Julia, Go and R were NOT re-run: that host
carries no gfortran, julia, go or Rscript, so those four rows stand on
their dated Linux runs above and on nothing newer.

One wrinkle for whoever runs `make -C host examples-lang` on Windows
next. Under MSYS2 make the recipe environment arrives stripped of
`USERPROFILE`, NuGet then cannot locate its packages folder, and the
C# leg fails the target with `NuGet.targets(782,5): error : Value
cannot be null. (Parameter 'path1')` - while `dotnet run --project
host/examples/vector_fma_cs.csproj` succeeds from an ordinary shell on
the same tree. The environment, not the example, and not something the
target currently distinguishes from a real bit mismatch.

**ABI 0.2 (2026-09-01)** widened the surface with the clause-5
completion set - cft_rint, cft_convert, the integer conversions,
cft_scaleb/cft_logb, cft_next_up/_down, cft_class, cft_total_order,
cft_cmp_sig, cft_rem - all plain positional C functions reachable
through exactly the FFI each row above already uses. The verified
column stays honest: every example above exercises the original
vector_fma surface, and none has been extended to the new calls yet.
host/tests/clause5_check.py is the reference consumer (ctypes,
every entry point) a new binding can crib declarations from.

## Drop-ins

Higher-level packages that slot into an existing ecosystem's shape,
so adopting the library does not mean rewriting numerics.

| Drop-in | Path | Replaces / accelerates | Status |
|---|---|---|---|
| `cftmpfr` | `bindings/python/cftmpfr/` | MPFR-as-IEEE-emulator usage in Python (the gmpy2 pattern) at binary32/64/128/256 | working. 300,000/300,000 encodings bit-identical to gmpy2 in the demo workload, re-run 2026-09-02; 80 tests; parity claim backed by the 999,000-case MPFR oracle suite (docs/VALIDATION.md). Honest performance story in its README, dated there because it moved: div/sqrt is the tile's win, and the batch FMA phase - a 1.06x win when first recorded on 2026-08-31 - measured 0.85-0.94x at binary256 on the same host on 2026-09-02. Same calls either way |

Candidates worth building when their audience shows up: a NumPy
dtype/ufunc layer over the batch API; an mpmath context; a
gmpy2-compatible C extension for zero-source-change swaps. Each is a
shape question, not a semantics question - the semantics are the
contract, and the contract does not move.
