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
run from eight languages: the checksum is FNV-1a over the raw output
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
| C | `host/examples/vector_fma.c` | the reference example; the header IS the binding | Windows 2026-09-02 + Linux 2026-09-01; 2026-09-02 as runner stage `libcft` on Windows, the desktop's WSL, the box and CI | `cft.h` is the whole contract surface |
| C++ | `host/include/cft.hpp`, `host/examples/vector_fma.cpp`, `host/tests/cpp_api_test.cpp` | header-only wrapper: RAII for the three handles, a fixed-width byte type per format, span batches, and a Context/Float layer of the same shape as cftmpfr's and bindings/node's; plus the example and a test that issues every entry point twice | Windows 2026-09-02 (mingw64 g++ 16.1.0), at **both** `-std=c++17` and `-std=c++20`: the example's four checksums diff clean against the C example (`make -C host examples-lang`), and `make -C host cpptest` passes 2,871 checks each way including a 236,000-case `cft_conformance` replay through the wrapper; 2026-09-02 as runner stages `cpp` and `lang-cpp` on Windows, the desktop's WSL (g++ 11.4), the box (g++ 13.3) and CI (ubuntu-24.04), the replay 392,000 cases each way | computes nothing: every result is a libcft call, and the test is the proof - each entry point is issued through `cft.hpp` and through `cft.h` on the same bytes, compared for identical encodings AND identical flags. Operators are bound to an explicit Context (format + attribute) because a free `operator+` on a bare value type would need a hidden global attribute; the header says so at length |
| Fortran | `host/examples/vector_fma.f90` | example via iso_c_binding | Linux, gfortran 13.3 (`make -C host fortran`); 2026-09-02 as runner stage `lang-fortran` on the desktop's WSL (gfortran 11.4), CI (ubuntu-24.04) and Windows (mingw64 gfortran 16.1.0 from pacman); the example's header carries no date | the constituency the C ABI was chosen for |
| Python (ctypes) | `host/examples/vector_fma.py`, `vector_fma_ctypes.py` | example + the diff/seq/reduce/divsqrt check harnesses | Windows 2026-09-02 + Linux 2026-09-01, every `make -C host test`; 2026-09-02 as runner stage `libcft` on all four hosts | no build step, no generated bindings |
| Python (package) | `bindings/python/cftmpfr/` | full package: Context/Float scalar ops, batch ops, gmpy2 interop | Windows 2026-09-02 (80 tests; 300k/300k bit-identical to gmpy2); 2026-09-02 as runner stage `bindings` on Windows, the desktop's WSL (gmpy2 2.1.2), the box (gmpy2 2.3.1) and CI, 80 tests each | see Drop-ins below |
| Rust | `host/examples/vector_fma.rs` | single-file example, plain rustc, static-links libcft.a (MSVC rustc included) | Windows 2026-09-02 (rustc 1.94.1, x86_64-pc-windows-msvc); 2026-09-02 as runner stage `lang-rust` on Windows and CI (ubuntu-24.04) | why the static link survives MSVC is in its header |
| Julia | `host/examples/vector_fma.jl` | single-file example, stdlib ccall | Linux 2026-09-01 (julia 1.12.7); checksums also match the Windows set; Windows 2026-09-02 (julia 1.12.7 from the pinned zip, runner stage `lang-julia`) and the desktop's WSL the same evening (same version, same zip's Linux tarball); not on the CI image | born UNVERIFIED, asterisk lasted one day |
| Go | `host/examples/vector_fma.go` | single-file cgo example; compiles the real cft.h (nothing transcribed), FNV from stdlib | Linux 2026-09-01 (go 1.18); 2026-09-02 as runner stage `lang-go` on the desktop's WSL, CI, and Windows (go 1.26.4 from pacman, GOROOT carried by the runner) | static-links libcft.a as a direct linker input |
| C# / .NET | `host/examples/VectorFma.cs` (+ minimal csproj) | single-file P/Invoke, no NuGet | Windows 2026-09-02 (dotnet 10.0.301) + Linux 2026-09-01 (dotnet 8); 2026-09-02 as runner stage `lang-csharp` on Windows, the desktop's WSL (dotnet 8.0.130) and CI | resolver maps to exactly one candidate; error paths byte-identical |
| R | `host/examples/vector_fma.R` | example + the ~70-line .Call shim base R genuinely needs (it cannot pass by-value ints) | Linux 2026-09-01 (R 4.1.2); 2026-09-02 as runner stage `lang-r` on the desktop's WSL, and on Windows (R 4.6.1 with Rtools45, whose gcc 14.3 builds the shim) | 64-bit checksum computed exactly in split doubles - every intermediate below 2^42, proven never to round |
| Browser / WASM | `bindings/wasm/` - live at https://loganw234.github.io/cft-fp256/ | the software backend compiled to WebAssembly + a single-file conformance page (works from file://, ~1.1 MB, wasm 89 KB) with drag-drop full-set replay - the twenty opcode sets and, since 2026-09-03, the twenty transcendental ones - and a compute panel covering `cft_run`'s opcodes, composed div/sqrt and all twenty transcendentals; 58 `cftw_*` exports - the whole ABI 0.4 surface, wrappers included | Chrome 2026-09-01: embedded 4,015-case sample clean AND full 236,000-case replay clean; negative control screenshotted; two container builds byte-identical. Rebuilt 2026-09-02 (same pinned emsdk 6.0.9, source list now derived from `host/Makefile`): `node bindings/wasm/verify.mjs` extracts the committed page's module, gets ABI 0.2 from it, and replays 236,000 cases clean through it - not re-opened in a browser that day, template unchanged; 2026-09-02 as runner stage `wasm` on Windows and CI, 392,000 cases. Rebuilt again 2026-09-03 with the nine wrappers (module 88,875 bytes, sha256 `6ff4129e03d43682…`, three clean container builds byte-identical): `verify.mjs` gets ABI 0.3 and 47 exports from the committed page, replays **300,325 cases over 40 sets** through `cft_conformance` and drives **64,325 more through the nine wrappers themselves** - the check that fails when a wrapper is missing or wrong, shown failing with `cftw_pow`'s operands swapped while the internal replay stayed green. **Re-opened in a browser this time** (Chromium 148, served over loopback since `file://` was unreachable), because the template did change: identity line ABI 0.3, embedded sample 4,015 cases green, a drop of four transcendental sets + one opcode set clean at 32,465 cases with a misnamed file still refused, and the panel's new controls computing `exp(1)`, `log(+0)` = -inf/divideByZero, `pow(2,3)`=8 vs `pow(3,2)`=9 and `log2(2^10)`=10 exactly at binary256; the negative-control page failed red in the same browser. Rebuilt a third time later on 2026-09-03, with the eleven phase-2 wrappers, so the module never spent a day at 0.4 without them (module **98,392 bytes**, sha256 `ee66812e4bd17de7…`, 58 exports): `verify.mjs` gets ABI 0.4 from the committed page, replays **365,845 cases over 40 sets** through `cft_conformance` and drives **129,845 more through the twenty wrappers themselves**, zero mismatches either way. Three container builds again byte-identical - two back to back and a third after the negative control was reverted. That control was the operand order this time: `cftw_atan2`'s two pointers swapped fails all twenty transcendental sets at `atan2(+0, -0)`, which returns -0 where the vectors say pi, while the internal replay stayed green at 365,845. **Re-opened in a browser again**, because the markup changed again (eleven panel rows, eleven cwrap entries): Chromium 148 on the committed page over loopback - identity line ABI 0.4, embedded sample 4,015 cases green, a drop of four transcendental sets + one opcode set clean at 45,569 cases with a misnamed file still refused and the verdict downgraded, and the panel's eleven new controls computing `sinPi(1)`=+0 vs `sinPi(-1)`=-0, `tanPi(1)`=-0, `tanPi(1/2)`=+inf with divideByZero, `atanPi(+inf)`=1/2 exactly, `atan2(+0,-0)`=pi inexact against `atan2Pi(+0,-0)`=1 exact, `atan2Pi(1,0)`=1/2 against `atan2Pi(0,1)`=+0 (the operand order, in the UI), and at binary256 `asinPi(1)`=1/2, `acosPi(-1)`=1, `acosPi(1/2)`=1/3 inexact, `asin(2)` the canonical qNaN with invalid; the negative-control page failed red at `fp64.jsonl:2` in the same browser | bit-exact BY CONSTRUCTION - the softfloat is integer-only and wasm integer semantics are fully specified. Replays the published vectors with only a compliant browser. Browser-GPU compute is deliberately out of scope: that floating point is the nondeterminism this project exists against |
| Node / JavaScript | `bindings/node/` (package 0.5.0) | full package: the 67 `cftw_*` exports one-to-one, plus Context/Float scalars, batch `map`/`reduce`, the clause-5 surface, all twenty transcendentals on all three layers, exact-decimal I/O | Windows 2026-09-02, node 22.19.0: 43 tests; 236,000-case vectors replay clean through the page's own module; decimal parsing checked against V8's strtod; 2026-09-02 as runner stage `node` on Windows and CI - the 392,000-case replay takes 4 s, the 43 unit tests 272 s on the Windows host and 126 s on ubuntu, a gap measured and not yet explained. 2026-09-03 with the nine: **57 tests**, and `conformance.mjs` now **300,325 cases over 40 sets** - 236,000 through `cft_conformance` in 1.6 s, then 64,325 transcendental cases in 60.9 s driven through this package's own `Context` methods, per case and then as arrays. Negative control run and reverted: `cftw_pow`'s operands swapped fails 6 tests by name and all twenty transcendental sets, while the `cft_conformance` pass stays green. 2026-09-03 with the eleven, package 0.4.0: **74 tests**, and `conformance.mjs` **365,845 cases over 40 sets** - 236,000 through `cft_conformance` in 1.7 s, then 129,845 transcendental cases in 108.2 s through this package's own `Context` methods, per case and then as arrays. The ABI test reads 0.4. Negative control repeated on the new surface and reverted: `cftw_atan2`'s operands swapped fails 2 tests by name (`atan2(+0, -0) is pi and inexact`, `atan2(-0, +1) is -0`) and all twenty transcendental sets, the `cft_conformance` pass still green | loads the SAME wasm module as the browser page (sha256 checked, not assumed). Encodings are `Uint8Array`/`BigInt`, never a JS `number` - see Drop-ins below for why it is a drop-in for nothing |
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

**C++ added 2026-09-02**, same host and toolchain. `host/include/cft.hpp`
is header-only over the same ABI, so its example links `libcft.a` and
its output is diffed like every other language's: `examples-lang`'s
new `c++` leg printed the canonical four and matched. The wrapper's
own gate is `make -C host cpptest`, which builds
`host/tests/cpp_api_test.cpp` twice - once at C++17, where the batch
views are the header's own pointer+size type, and once at C++20, where
they are `std::span` - and runs both: **2,871 checks each, zero
failures**, covering every entry point at all four formats under all
five rounding attributes, the specials (both NaNs, both infinities,
both zeros, the subnormal edge), the reductions at n = 0/1/5/64/257
against `cft_reduce`, the sequencer-program and device-buffer handles,
and a 236,000-case `cft_conformance` replay issued through the
wrapper. Negative control run the same day: swapping the two operands
of the wrapper's `sub` fails 20 of those checks and exits non-zero, so
the comparison can distinguish a wrong wrapper from a right one.

**The languages as runner stages, 2026-09-02.** Everything above was
run by hand, one command per language, and nothing said per language
what passed. `verify/run.sh` now carries one stage per language -
`cpp`, `lang-cpp`, `lang-rust`, `lang-julia`, `lang-go`, `lang-csharp`,
`lang-r`, `lang-fortran`, `node`, `wasm` - SKIPped by name where the
toolchain is absent and FAILed where the bits differ, and the `host`
job of `.github/workflows/gates.yml` runs them on every push under
`--require-all`. The first runs, at 8c626a5 and efff78e:

| stage | Windows (this desktop) | desktop WSL, Ubuntu 22.04 | box, Ubuntu 24.04 | CI, ubuntu-24.04 |
|---|---|---|---|---|
| libcft (C, Python ctypes) | ok | ok | ok | ok |
| bindings (Python package) | ok | ok | ok, once pytest was installed | ok |
| cpp | ok | ok | ok | ok |
| lang-cpp | ok | ok | ok | ok |
| lang-rust | ok | SKIP no rustc | SKIP no rustc | ok |
| lang-julia | SKIP no julia | SKIP no julia | SKIP no julia | not selected: no julia on the image |
| lang-go | SKIP no go | ok | SKIP no go | ok |
| lang-csharp | ok | ok | SKIP no dotnet | ok |
| lang-r | SKIP no Rscript | ok | SKIP no Rscript | not selected: no R on the image |
| lang-fortran | SKIP no gfortran | ok | SKIP no gfortran | ok |
| node | ok | SKIP no node | SKIP no node | ok |
| wasm | ok | SKIP no node | SKIP no node | ok |

Two things the first run taught. The box has python3 and no pytest,
and the bindings stage FAILed there in 0 s instead of SKIPping by
name - so pytest became a named precondition (efff78e), the box got
pytest, and the stage then ran and passed. And a runner script must
not be edited while a run is in progress: bash reads it as it goes,
and a four-line insert during the Windows run's node stage put a
syntax error at the next stage line; that run was repeated on the
committed tree.

**A Windows host with every toolchain, 2026-09-02.** The desktop was
set up to run the whole standard set, and the recipe is short enough
to keep. Nothing needs an administrator: gfortran and go are pacman
packages in the MSYS2 that already builds libcft
(`mingw-w64-x86_64-gcc-fortran`, `mingw-w64-x86_64-go`); Julia is the
pinned 1.12.7 zip from julialang-s3, SHA-256 checked against the
published checksums file, unpacked under `%LOCALAPPDATA%\Programs`;
R 4.6.1 is CRAN's Inno installer with `/VERYSILENT /CURRENTUSER`,
md5 checked against the master server's `md5sum.R-4.6.1.txt`, and
Rtools45 the same way into `C:\rtools45`, where R's own Makeconf
looks for it (an R without Rtools reaches for whatever `gcc` is on
PATH and fails on the `.def` file it writes for the shim). Julia's
and R's `bin` directories go on the user PATH; pacman's tools do
not need to, because the runner looks in mingw64's bin directory
and HOSTMAKE prepends it. Three things the runner and the Makefile
carry so nobody has to: pacman's go is a trimmed binary that needs
GOROOT, MSYS make hands recipes a stripped environment, and MSYS2's
`env` drops an inherited GOROOT on the way to a native child while
keeping one assigned on its own command line - so GOROOT travels as
a make variable into the Makefile's WINENV block, beside the profile
variables dotnet, julia and R also need there. With that, every
language leg runs on the Windows host; `images` is the one stage
Windows can never run, because XRT's xclbinutil is Linux-only, and
the desktop's WSL distro runs that one with the rest.

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

Two rows have moved since. As of 2026-09-02 the wasm module exports
all twenty clause-5 entry points (it had been built from six sources,
missing `src/clause5.c` entirely); the *page* still calls none of them,
because the published vectors cover `cft_run`'s opcode space and not
clause 5. `bindings/node` is the first binding outside
`host/tests/clause5_check.py` that actually drives them - rint,
scaleb, logb, nextUp/nextDown, class, totalOrder, the signaling
compares, convert, the integer conversions and remainder each have a
test - on the wasm build rather than the native library. As of
2026-09-02 the C++ row drives the same twenty entry points against the
**native** library, and against the C calls rather than against
expected values: `host/tests/cpp_api_test.cpp` issues each one through
`cft.hpp` and through `cft.h` on the same operands and compares
encodings and flags. That is a marshalling check, not a second opinion
on the semantics - the semantics have one implementation, which is the
point.

**ABI 0.3 (2026-09-02)** added the phase-1 transcendentals - cft_exp,
cft_expm1, cft_exp2, cft_log, cft_log1p, cft_log2, cft_log10, cft_pow
and cft_hypot - correctly rounded at all four formats under all five
attributes, with clause 9.2.1's special values and exact flags. Same
shape as the clause-5 host operations: plain positional C functions,
no bus word, reachable through exactly the FFI each row above already
uses. docs/TRANSCENDENTALS.md is the design.

Where each surface stands, stated per row rather than in general,
because the honest answer differs:

| surface | status at ABI 0.3 |
|---|---|
| C (`cft.h`) | complete. `host/tests/api_test.c` covers the refusals, the aliasing rule and the clause 9.2.1 edges; `host/tests/transcend_check.py` is the reference ctypes consumer, 77,315 comparisons against the model |
| C++ (`cft.hpp`) | complete, all three layers, and `cpp_api_test` issues every one twice - through the wrapper and through `cft.h` - comparing encodings and flags: 3,267 checks at C++17 and C++20 |
| Python (`cftmpfr`) | complete on `Context` and in `batch`, with 268 tests including bit-for-bit agreement with gmpy2's IEEE emulation at every precision and every attribute MPFR has |
| conformance vectors | complete: 20 new sets, `<fmt>-transcend[-<rnd>].jsonl`, 64,325 cases, replayed by `cft_conformance` |
| Node (`bindings/node`) | complete on all three layers (package 0.3.1): the nine `cftw_*` exports, `Context`/`Float` scalars, `map()` over an array. 57 tests, and `conformance.mjs` drives all 64,325 transcendental cases through the package's own methods on top of the 236,000 through `cft_conformance` - 300,325 over 40 sets |
| Browser / WASM page | complete: `wasm_api.c` carries the nine (47 `cftw_*` exports), the compute panel has a control for each, and the drop zone accepts the twenty transcendental sets. `verify.mjs` replays 300,325 cases over 40 sets and drives 64,325 through the wrappers themselves. The embedded sample stays the twenty opcode sets its sampling rule covers - the containerized build has no mpmath and cannot generate the others |

The last two rows were the honest half-step for part of 2026-09-03,
and this is what that meant and how it closed. `bash
bindings/wasm/build.sh` rebuilt both artifacts that morning against
the pinned emsdk, and because that build asks `host/Makefile` what it
compiles rather than carrying a list, `mpfloat.c` and `transcend.c`
came along on their own: the module reported ABI 0.3 and the
`cft_conformance` inside it understood the new vector sets. What had
NOT happened was a `cftw_*` wrapper or a page control for any of the
nine, so no JavaScript caller could invoke one and no test on either
surface drove one. A row that said "ABI 0.3" and stopped there would
have been true and misleading.

Closed the same day, and the closing is what the two rows above now
record: nine wrappers in `wasm_api.c`, one per declaration in cft.h
and none of them carrying a `bus_out` the contract does not give them;
nine rows in the page's compute panel; the nine on all three Node
layers; and, the part that makes the rest checkable, a test on each
JavaScript surface that *drives the wrappers* rather than the internal
replay. That distinction is the whole lesson of the half-step:
`cft_conformance` dispatches the nine in C, so it was green on a
module with no JavaScript surface for them at all, and it stays green
today with `cftw_pow`'s operands deliberately swapped - a negative
control that was run, caught by both new checks, and reverted. Three
clean container builds of the final tree produced byte-identical
artifacts.

**ABI 0.4 (2026-09-03)** added the phase-2 trigonometrics -
cft_sinpi, cft_cospi, cft_tanpi, cft_asin, cft_acos, cft_atan,
cft_atan2, cft_asinpi, cft_acospi, cft_atanpi and cft_atan2pi -
correctly rounded at all four formats under all five attributes, with
clause 9.2.1's special values and exact flags. Same shape again: plain
positional C functions, host operations, no bus word, reachable through
exactly the FFI each row above already uses. `atan2` and `atan2pi` take
y first, as C's atan2 does. docs/TRANSCENDENTALS.md is the design.

Where each surface stands at ABI 0.4, stated per row because the honest
answer differs.

| surface | status at ABI 0.4 |
|---|---|
| C (`cft.h`) | complete. `host/tests/api_test.c` covers the refusals, the aliasing rule, the exact cases and one case from every neighbour family; `host/tests/transcend_check.py` is the reference ctypes consumer, 154,269 comparisons against the model over twenty functions |
| C++ (`cft.hpp`) | complete, all three layers, and `cpp_api_test` issues every one twice - through the wrapper and through `cft.h` - comparing encodings and flags: **3,751 checks** at C++17 and again at C++20, up from 3,267 |
| Python (`cftmpfr`) | complete on `Context` and in `batch`, **384 tests** (up from 268), including asin/acos/atan/atan2 bit-for-bit against gmpy2's IEEE emulation at every precision and attribute MPFR has. gmpy2 2.2.1 binds none of MPFR 4.2.0's Pi-variants, so those are checked against MPFR in `host/tools/mpfr_check.c` instead, which calls `mpfr_sinpi` and friends directly |
| conformance vectors | complete: the same 20 `<fmt>-transcend[-<rnd>].jsonl` files now carry all twenty functions - **129,845 transcendental cases** of 365,845 in 40 sets, replayed by `cft_conformance` |
| Node (`bindings/node`) | complete on all three layers (package 0.4.0): the eleven `cftw_*` exports, `Context`/`Float` scalars with `y.atan2(x)` in cft.h's order, `map()` over an array. **74 tests** (up from 57), and `conformance.mjs` drives all 129,845 transcendental cases through the package's own methods on top of the 236,000 through `cft_conformance` - **365,845 over 40 sets** |
| Browser / WASM page | complete: `wasm_api.c` carries the eleven (**58 `cftw_*` exports**), the compute panel has a control for each, and the drop zone already accepted the transcendental sets. `verify.mjs` replays 365,845 cases over 40 sets and drives 129,845 through the wrappers themselves. The embedded sample stays the twenty opcode sets its sampling rule covers - the containerized build has no mpmath and cannot generate the others |

These last two rows were "not started" for about an hour, and the
distance between 0.3's half-step and this one is the point. At 0.3 the
JavaScript artifacts had been rebuilt from sources that carried the
nine, so the module reported a version whose operations no JavaScript
caller could invoke, and that gap lasted a day. At 0.4 the artifacts
were not rebuilt at all, which is a smaller lie but the same one
waiting: a rebuild on its own would have answered `cftw_abi_version()`
with 4 while exporting none of the eleven. So the rebuild and the
wrappers landed in one commit, which is what the two rows now record:
eleven wrappers in `wasm_api.c`, one per declaration in cft.h and in
cft.h's order, none carrying a `bus_out` the contract does not give
them; eleven rows in the page's compute panel; the eleven on all three
Node layers; and a test on each JavaScript surface that *drives the
wrappers* rather than the internal replay.

The negative control moved with the surface. At 0.3 it was `cftw_pow`'s
operands, because pow is not symmetric; at 0.4 it is `cftw_atan2`'s,
for the same reason and a sharper one - `atan2` takes y first, and a
swap returns a plausible number for every input. Swapped, rebuilt:
`verify.mjs` step 5 fails all twenty transcendental sets at
`atan2(+0, -0)`, which comes back -0 where the vectors say pi, while
step 4's `cft_conformance` replay stays green at 365,845 cases;
`test.mjs` fails 2 of 74 by name; `conformance.mjs` fails all twenty
sets. Reverted, rebuilt, and the artifacts hash to what they hashed
before - three clean container builds of the final tree, byte-identical.

The page was re-opened in a browser, as it was for 0.3 and for the same
reason: `verify.mjs` step 5 checks the wrappers, and the markup between
a click and those wrappers is not something a node harness can reach.
Chromium 148, the committed page over loopback: ABI 0.4 on the identity
line, the embedded sample green at 4,015 cases, a five-set drop clean
at 45,569 with a misnamed sixth file still refused by name, and every
one of the eleven new controls computing its special values - including
`atan2(+0, -0)` = pi inexact next to `atan2Pi(+0, -0)` = 1 exact, and
`atan2Pi(1, 0)` = 1/2 next to `atan2Pi(0, 1)` = +0, which is the
operand order made visible. bindings/wasm/README.md lists the rest.

**ABI 0.5 (2026-09-03)** added the phase-3 radian trigonometry and
the hyperbolics - cft_sin, cft_cos, cft_tan, cft_sinh, cft_cosh,
cft_tanh, cft_asinh, cft_acosh and cft_atanh - correctly rounded at all
four formats under all five attributes, with clause 9.2.1's special
values and exact flags. Same shape again: plain positional C functions,
host operations, no bus word, reachable through exactly the FFI each
row above already uses. sin, cos and tan take RADIANS and are reduced
against pi inside the library. docs/TRANSCENDENTALS.md is the design.

Where each surface stands at ABI 0.5. For the first time the JavaScript
rows moved in the same step as the library, so there was no half-step
to record.

| surface | status at ABI 0.5 |
|---|---|
| C (`cft.h`) | complete. `host/tests/api_test.c` covers the refusals, the exact cases, the special rows, one case from every neighbour family and the reduction's two published worst cases with bits from mpmath; `host/tests/transcend_check.py` is the reference ctypes consumer, 280,670 comparisons against the model over twenty-nine functions |
| C++ (`cft.hpp`) | complete, all three layers, and `cpp_api_test` issues every one twice - through the wrapper and through `cft.h` - comparing encodings and flags: **4,111 checks** at C++17 and again at C++20, up from 3,751 |
| Python (`cftmpfr`) | complete on `Context` and in `batch`, **576 tests** (up from 384), the nine bit-for-bit against gmpy2's IEEE emulation at every precision and attribute MPFR has - gmpy2 binds all nine, so unlike the Pi-variants every one has a Python-side oracle |
| conformance vectors | complete: the same 20 `<fmt>-transcend[-<rnd>].jsonl` files now carry all twenty-nine functions - **242,915 transcendental cases** of 478,915 in 40 sets at `make vectors`' arguments, replayed by `cft_conformance`; the radian pools carry every power of two across the exponent range and the arguments the worst-case search finds |
| Node (`bindings/node`) | complete on all three layers (package 0.5.0): the nine `cftw_*` exports, `Context`/`Float` scalars, `map()` over an array. **79 tests**, and `conformance.mjs` drives every transcendental case through the package's own methods on top of the opcode sets through `cft_conformance` |
| Browser / WASM page | complete: `wasm_api.c` carries the nine (**67 `cftw_*` exports**, module 140,869 bytes), the compute panel has a control for each, and the drop zone accepts the sets. `verify.mjs` replays every set and drives the transcendental cases through the wrappers themselves. Built twice from a clean container (emsdk 6.0.9, pinned tag and digest), byte-identical: page sha256 `69ff0ff911e9ce1e22ad4f2cf4955ba8d1d0dbb3c97d3e46aa4fdcf4932092d8`, wasm `5718aa19e85dad2b63727c8f537acceff90efc735f5bd89f7a4bde2098c22129` |

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

**JavaScript has nothing to be a drop-in for (surveyed 2026-09-02).**
`bindings/node` was built as a binding, not a drop-in, and the reason
is worth recording so the question does not get re-opened from
memory. Against the versions npm serves today: `decimal.js` 10.6.0,
`bignumber.js` 11.1.5 and `big.js` 7.0.1 are arbitrary-precision
**decimal** - their `precision` counts decimal digits and their
rounding modes round decimals, which is a different radix and a
different question, so imitating one would mean claiming semantics
this library does not implement. `gmp-wasm` 1.3.2 is the only binary
candidate - GMP and MPFR compiled to wasm - and is still not it: its
high-level `getFloatContext` takes `precisionBits` and a rounding mode
and nothing else, with no exponent bounds and no subnormalization
(`mpfr_set_emin`/`_emax`/`mpfr_subnormalize` live only on its raw
binding surface), so it is unbounded-exponent MPFR rather than an
interchange-format emulator; and its fifth rounding mode is MPFR's
`RNDA`, away-from-zero for every inexact value, not roundTiesToAway.
The language itself offers `number` (binary64) and the two typed
arrays, and nothing that carries flags. So the honest shape is the C
ABI one to one plus a Context/Float layer - the same layer cftmpfr
has, because that is the shape numerical code is written in, not
because it imitates a package. If a JavaScript MPFR context ever
grows the `ieee(n)` recipe, the interop path is the one cftmpfr
already uses: integer significand and exponent, never a decimal
detour.
