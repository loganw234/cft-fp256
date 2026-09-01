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
has actually been run and matched, on the named platform, and the
claim regenerates with `make -C host examples-lang` wherever the
toolchain exists. Nothing here is checked in CI's default lane -
toolchains are optional by design - so the honest status is recorded
per row and updated when it changes, the census way: no row says more
than its diff has shown.

## Language bindings and examples

| Language | Path | What exists | Verified | Notes |
|---|---|---|---|---|
| C | `host/examples/vector_fma.c` | the reference example; the header IS the binding | Windows + Linux | `cft.h` is the whole contract surface |
| Fortran | `host/examples/vector_fma.f90` | example via iso_c_binding | Linux (`make -C host fortran`) | the constituency the C ABI was chosen for |
| Python (ctypes) | `host/examples/vector_fma.py`, `vector_fma_ctypes.py` | example + the diff/seq/reduce/divsqrt check harnesses | Windows + Linux, every `make -C host test` | no build step, no generated bindings |
| Python (package) | `bindings/python/cftmpfr/` | full package: Context/Float scalar ops, batch ops, gmpy2 interop | Windows (69 tests; 300k/300k bit-identical to gmpy2) | see Drop-ins below |
| Rust | `host/examples/vector_fma.rs` | single-file example, plain rustc, static-links libcft.a (MSVC rustc included) | Windows | why the static link survives MSVC is in its header |
| Julia | `host/examples/vector_fma.jl` | single-file example, stdlib ccall | Linux (julia 1.12.7); checksums also match the Windows set | born UNVERIFIED, asterisk lasted one day |
| Go | `host/examples/vector_fma.go` | single-file cgo example; compiles the real cft.h (nothing transcribed), FNV from stdlib | Linux (go 1.18) | static-links libcft.a as a direct linker input |
| C# / .NET | `host/examples/VectorFma.cs` (+ minimal csproj) | single-file P/Invoke, no NuGet | Windows (dotnet 10) + Linux (dotnet 8) | resolver maps to exactly one candidate; error paths byte-identical |
| R | `host/examples/vector_fma.R` | example + the ~70-line .Call shim base R genuinely needs (it cannot pass by-value ints) | Linux (R 4.1.2) | 64-bit checksum computed exactly in split doubles - every intermediate below 2^42, proven never to round |
| Browser / WASM | `bindings/wasm/` - live at https://loganw234.github.io/cft-fp256/ | the software backend compiled to WebAssembly + a single-file conformance page (works from file://, ~1 MB, wasm ~50 KB) with drag-drop full-set replay and a compute panel incl. composed div/sqrt | Chrome: embedded 4,015-case sample clean AND full 236,000-case replay clean; negative control screenshotted; two container builds byte-identical | bit-exact BY CONSTRUCTION - the softfloat is integer-only and wasm integer semantics are fully specified. Replays the published vectors with only a compliant browser. Browser-GPU compute is deliberately out of scope: that floating point is the nondeterminism this project exists against |
| MATLAB | - | planned (loadlibrary) | - | namechecked in cft.h; wants a licensed seat to verify honestly |
| Java | - | planned (Panama FFI) | - | waiting for the FFI story to be the obvious one |

The pattern for adding a language is deliberately boring: load the
shared library (or link the static one), declare a dozen functions,
drive the same vectors, diff the checksums. A binding that needs more
than that is evidence the ABI failed at its one job.

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
| `cftmpfr` | `bindings/python/cftmpfr/` | MPFR-as-IEEE-emulator usage in Python (the gmpy2 pattern) at binary32/64/128/256 | working. 300,000/300,000 encodings bit-identical to gmpy2 in the demo workload; 69 tests; parity claim backed by the 999,000-case MPFR oracle suite (docs/VALIDATION.md). Honest performance story in its README: batch FMA wins on the software backend, div/sqrt is the tile's win - same calls either way |

Candidates worth building when their audience shows up: a NumPy
dtype/ufunc layer over the batch API; an mpmath context; a
gmpy2-compatible C extension for zero-source-change swaps. Each is a
shape question, not a semantics question - the semantics are the
contract, and the contract does not move.
