# libcft in WebAssembly - the contract, one browser away

`conformance.html` is the whole product of this directory: a single
self-contained HTML file (committed, ~1 MB) that loads libcft's
software backend compiled to wasm, prints the library's identity, and
replays conformance vectors through `cft_conformance()` - the same C
code path every backend, binding and port of this project is judged
by. It runs from `file://`, makes no network request, and needs no
server, no toolchain and no card. That is the point: the README at
the repo root says the guarantee is machine-checkable, and this file
lowers "check it" to *open a page*.

Open it, and either the verdict line reads

    N cases, library matches the vectors exactly

or the page shows you the first disagreement - op, operands, expected
and got, flags - verbatim from the library. There is no third
rendering: a run that checked nothing says so in red, because a
conformance pass that quietly checked nothing would be worse than a
failing one.

## What a green verdict proves, spelled out

The claim it supports is narrow and strong: **compiling this library
to wasm cannot have changed a single result bit, and the replay shows
it did not.**

1. The software backend's arithmetic is integer-only. Every operation
   is computed on uint32 limbs with uint64 intermediates
   (`host/src/bigint.c`, `host/src/softfloat.c`); no C `float` or
   `double` arithmetic appears anywhere in the result path, so the
   host FPU - the usual door nondeterminism walks through - is never
   consulted.
2. WebAssembly specifies integer arithmetic totally: wrap-around,
   shifts, widths, everything. Two compliant wasm engines cannot
   disagree on an integer program's output; there is no
   fast-math, no FMA contraction, no x87 double rounding, no
   vendor-shaped anything to vary.
3. Therefore the wasm build is bit-exact *by construction*, and the
   page's replay is the *measurement* that the construction holds -
   through the real `cft_conformance()`: per-element pass for exact
   per-case flags, then the array pass, per set.

The embedded sample (4,015 cases; deterministic rule below) spans all
four formats, all five rounding attributes and every opcode class,
the divide/sqrt seeds 26/27 and the unassigned `reserved15/28/255`
included. For the full 236,000-case claim, generate the sets in a
checkout (`make vectors`) and drag the `vectors/out/*.jsonl` files
onto the page - same code path, whole files. Verified at build time:
the full 20-set drop replays with zero mismatches, from both
LF (Linux) and CRLF (Windows) generated files.

Since 2026-09-03 the drop zone also accepts the **twenty
transcendental sets** ABI 0.3 added (`<fmt>-transcend[-<rnd>].jsonl`,
64,325 cases), which `cft_conformance` has understood since the module
was first built from the 0.3 sources but which the page's own name
list refused - so a `make vectors` drop, the thing this page tells the
reader to do, had half its files bounced. Measured, not assumed:
`verify.mjs` replays all forty sets one file per directory, which is
exactly what the drop zone does with a dropped file, and the drop
itself was watched working in Chromium (see the 2026-09-03 block
below) - four transcendental sets and one opcode set, 32,465 cases,
with a misnamed file still refused by name. Those same twenty files
carry **242,915 cases** since ABI 0.5 added the nine phase-3
functions to them (129,845 at 0.4, 64,325 at 0.3); the file names did
not change, so the drop zone needed nothing.

The page is also a working binary32/64/128/256 calculator: one
element through `cft_run()`, the composed `cft_div`/`cft_sqrt`
sequence, or any of the twenty-nine transcendentals - phase 1's nine,
phase 2's eleven and phase 3's nine - operands and results as raw
encodings, flags
decoded, every answer pinned by the replay above it.

## Building

One requirement: Docker. From anywhere in the repo:

```bash
bash bindings/wasm/build.sh
```

The entire build - vector regeneration, compilation, page assembly -
runs inside the official emscripten image pinned by tag **and**
digest (`emscripten/emsdk:6.0.9@sha256:96617f27...`, stated in
`build.sh`), so no host compiler, emsdk or Python is consulted and
the toolchain is identical on every machine. The tag is also the
emcc version these images carry, and `build.sh` checks that at
runtime: an emcc that is not 6.0.9 **refuses to build** unless
`CFT_WASM_EMCC_ANY=1` says otherwise, because the page is a committed
build product whose provenance block names its toolchain, and a page
built by a different one should never be committable by accident. The
check is stage 0, before the minute of vector generation, and it was
watched working on 2026-09-02 with a stub `emcc` earlier on `PATH`:
it refuses at once with the pinned version in the message, and under
the override it warns and proceeds. Stages:

1. regenerate the published vector sets into `build/vectors/` with
   the exact `make vectors` arguments (deterministic, seed 3; the
   build trusts its own regeneration, not whatever `vectors/out`
   holds);
2. `emcc` the library sources - **asked of `host/Makefile`, not
   listed here** (see below), currently nine: bigint, softfloat,
   device, divsqrt, clause5, mpfloat, transcend, program, conformance
   - `mpfloat.c` and `transcend.c` arrived with ABI 0.3 and were
   compiled in without anyone editing this directory, which is the
   derivation doing its job; the XRT backend is not compiled, wasm32
   having no PCIe to speak - plus `wasm_api.c`,
   twice with identical flags: split (`.js` + `.wasm`, so the
   reported wasm size is a measured fact) and `-sSINGLE_FILE` for
   embedding;
3. `make_page.py` samples the sets and splices runtime, sample and
   provenance into `page_template.html` → `conformance.html`;
4. the same assembly with `--corrupt` →
   `build/negative_control.html` (untracked): one expected value
   deliberately flipped, so anyone can watch the page fail. The
   corrupted expectation, the red verdict and the library's verbatim
   disagreement report are the proof that this checker *can* fail;
   a checker never seen failing proves nothing;
5. the same module once more with `-sENVIRONMENT=node` →
   `build/cft_node.js` + `.wasm`, and into `bindings/node/` when that
   package is present. `-sENVIRONMENT` changes the loader and not the
   wasm, so this is the page's module with a different front door -
   measured, not assumed: both builds hash to
   `7504440ef7ca5c9d…` on 2026-09-02. It is what lets `verify.mjs`
   replay the full sets without a browser.

**The source list is derived, because the typed one drifted.**
`host/Makefile` grew `src/clause5.c` with ABI 0.2 on 2026-09-01 and
this directory's build kept compiling the six it had been given. The
wasm build still linked - nothing in the other six references
clause5.c - so for a day the module reported an ABI version whose
whole content was the operations it did not contain. `build.sh` no
longer holds a list: it asks `host/Makefile` (via `make --eval`) what
`SRC` is, compiles exactly that, and cross-checks the answer against
`host/src/*.c` so that a source neither of them builds fails the
build instead of vanishing from it.

**The sampling rule** (also in `build.sh`, `make_page.py`, and on the
page): from each of the 20 sets (4 formats × 5 rounding attributes,
11,800 lines each) take every 59th line - 0-based lines 0, 59, 118, …
= exactly 200 per set - then add the set's first line of any opcode
name the stride missed, so every opcode class is embedded per set by
construction rather than by luck. `conformance.html` is a committed
build product; rebuild it with the pinned image and the only intended
diff is none.

`wasm_api.c` is the module's complete exported surface: 58 `cftw_*`
wrappers that project `host/include/cft.h` one declaration at a time,
adapting only what JavaScript cannot reach (out-params, the sized
caps struct, a uint64). No invented semantics; cft.h remains the
contract. Since 2026-09-02 that includes the clause-5 completion set
- `cftw_rint`, `cftw_convert`, the eight integer conversions,
`cftw_scaleb`/`cftw_logb`, `cftw_next_up`/`_down`, `cftw_class`,
`cftw_total_order`(`_mag`), `cftw_cmp_sig`, `cftw_rem` - which the
page does not call and a module claiming its ABI version should not be
without. Since 2026-09-03 it includes the nine phase-1
transcendentals: `cftw_exp`, `cftw_expm1`, `cftw_exp2`, `cftw_log`,
`cftw_log1p`, `cftw_log2`, `cftw_log10`, `cftw_pow`, `cftw_hypot`.
Those nine end at their flag word - no `bus_out` - because cft.h gives
them none: they are host operations that issue no device pass, and a
wrapper that grew a parameter to match its neighbours would be
describing a round trip that does not happen. Later the same day it
gained the eleven phase-2 trigonometrics on the same terms:
`cftw_sinpi`, `cftw_cospi`, `cftw_tanpi`, `cftw_asin`, `cftw_acos`,
`cftw_atan`, `cftw_asinpi`, `cftw_acospi`, `cftw_atanpi`, and
`cftw_atan2` / `cftw_atan2pi`, which take **y first, then x** - the C
order, cft.h's, and the one thing in this file a passthrough could get
wrong while still returning a plausible number for every input.

## Verifying it, without a browser

```bash
make vectors                       # from the repo root, once
node bindings/wasm/verify.mjs      # 2 min, node 22
```

No build is needed: the loader it drives is `bindings/node`'s
committed one. `bash bindings/wasm/build.sh` puts a fresh copy in
`build/` as well, and `verify.mjs` takes whichever it finds.

A person watching a browser is how this page was signed off, and it
is not a thing you can re-run after a rebuild - which is exactly how
the module spent a day reporting the wrong ABI version. `verify.mjs`
is the re-runnable half, and it checks the **committed file**, not
the build directory:

1. it pulls the wasm back out of `conformance.html` (emscripten's
   `-sSINGLE_FILE` embeds it as a JS string literal) and hashes it;
2. instantiates those bytes with stub imports and calls
   `cftw_abi_version()`, comparing against
   `CFT_ABI_VERSION_MAJOR/MINOR` read out of `cft.h` - so the check
   is *page agrees with header*, not *page equals a number typed
   into a test*;
3. checks the node loader's `.wasm` is the same module by sha256,
   because a replay through a lookalike would prove nothing about
   the page;
4. hands the extracted bytes to the node loader as
   `Module.wasmBinary` and replays the full sets through
   `cft_conformance()` over MEMFS - the page's own bytes, the
   library's own file-reading path, one call per set. One set per
   directory, which is what the page does with a dropped file, over
   every name the drop zone accepts: the twenty opcode sets and, when
   `make vectors` has written them, the twenty transcendental ones;
5. drives the **twenty-nine transcendentals through their own
   wrappers**, reading the same files itself: `cftw_exp` … `cftw_hypot`,
   since ABI 0.4 `cftw_sinpi` … `cftw_atan2pi`, and since ABI 0.5
   `cftw_sin` … `cftw_atanh`, one element at a time for
   exact per-case flags and then once per family as an array,
   comparing encodings and flags against the file. Step 4 cannot
   substitute for this and it is worth being blunt about why:
   `cft_conformance` dispatches all twenty-nine internally, in C, so it is
   green whether or not a single `cftw_*` wrapper for them exists. For
   a day it was (docs/COMPATIBILITY.md's half-step). Step 5 is the one
   that fails when the JavaScript surface is missing, or present and
   wrong - including `atan2` with its two operands the wrong way
   round, which is the negative control the 0.4 block below records.

**Measured 2026-09-02**, node 22.19.0 on Windows 11, against the page
rebuilt that day: module 66,422 bytes, sha256 `7504440ef7ca5c9d…`,
identical to the node loader's `bindings/node/cft_node.wasm` (and to
`build/cft_node.wasm`); `cftw_abi_version()` = 2 = ABI
0.2, matching `cft.h`; 38 `cftw_*` exports; **236,000 cases over 20
sets, zero mismatches**. Two clean container builds produced the same
`conformance.html` (sha256 `333dabd8c067a04a…`), so the
reproducibility claim below still holds with the derived source list.
And the harness was seen failing before it was believed: one expected
value in `fp128-rup.jsonl` flipped by a hex digit stops the run at
case 4,322 and prints the library's own disagreement - op, operands,
expected vs got, flags. The rebuilt page itself was **not** opened in
a browser on this host (no browser could reach a `file://` path from
the session that rebuilt it); what stands behind the page's UI is
that `page_template.html` is byte-identical to the version Chrome ran
on 2026-09-01.

**Measured 2026-09-03**, node 22.19.0 on Windows 11, against the page
rebuilt that day with the nine wrappers in it: module **88,875 bytes**,
sha256 `6ff4129e03d43682…`, identical to the node loader's
`bindings/node/cft_node.wasm` (and to `build/cft_node.wasm`);
`cftw_abi_version()` = 3 = ABI 0.3, matching `cft.h`; **47 `cftw_*`
exports**; **300,325 cases over 40 sets** through `cft_conformance`
(236,000 opcode + 64,325 transcendental) and **64,325 more through the
nine wrappers themselves**, zero mismatches either way, in 2 min.
Three clean container builds produced the same `conformance.html`
(sha256 `30292f731a4b553d…`) - two back to back, and a third after the
negative control below was reverted, which is a stronger statement
than two, since it says the tree round-tripped. The negative control
for the new surface was the operand order: `cftw_pow`'s two operand
pointers swapped, rebuilt, and then **step 5 fails all twenty
transcendental sets while step 4 stays green** - `pow(+0, +inf)`
returns 1 where the vectors say +0 - and `bindings/node/test.mjs`
fails 6 of 57 by name (`pow(2,3): expected 8, got 9`). That is the
half-step's failure mode reproduced on purpose: the internal replay
cannot see a broken wrapper, and now something can.

**And this time the page was opened in a browser** - which matters,
because `page_template.html` did change (the compute panel gained the
nine, the drop zone gained the twenty set names) and the two previous
rebuilds could lean on it being byte-identical to the version Chrome
ran on 2026-09-01. It cannot any more, so it was run: Chromium 148 on
Windows 11, the committed `conformance.html` served over a loopback
`http.server` because this session's browser will not open a `file://`
path. Section 1 read *libcft ABI 0.3*; section 2's embedded sample
replayed **4,015 cases over 20 sets, green**; section 3 accepted a
drop of four transcendental sets and one opcode set - 32,465 cases,
all matching, with a deliberately misnamed sixth file refused by name
and the verdict correctly downgraded to "not a full pass"; section
4's panel computed through the new controls, `exp(+0) = 1` with no
flags, `exp(1) = 0x4005bf0a8b145769` inexact, `log(+0) = -inf` with
divideByZero, `pow(2,3) = 8` against `pow(3,2) = 9` (the operand order,
in the UI), `hypot(3,4) = 5`, and `log2(2^10) = 10` exactly at
binary256 under roundTowardPositive. `build/negative_control.html` was
opened in the same browser and failed red at `fp64.jsonl:2` with the
library's own disagreement, so the checker was watched failing here
too.

**Measured 2026-09-03, later the same day**, node 22.19.0 on Windows
11, against the page rebuilt with the eleven phase-2 wrappers in it:
module **98,392 bytes**, sha256 `ee66812e4bd17de7…`, identical to the
node loader's `bindings/node/cft_node.wasm` (and to
`build/cft_node.wasm`); `cftw_abi_version()` = 4 = ABI 0.4, matching
`cft.h`; **58 `cftw_*` exports**; **365,845 cases over 40 sets**
through `cft_conformance` (236,000 opcode + 129,845 transcendental -
the same twenty transcendental files, now carrying all twenty
functions) and **129,845 more through the twenty wrappers
themselves**, zero mismatches either way. Three clean container builds
produced the same `conformance.html` (sha256 `b9ddcecc2dddf342…`) -
two back to back and a third after the negative control was reverted,
which is the stronger statement because it says the tree round-tripped.

The negative control moved with the surface. At 0.3 it was `cftw_pow`,
because pow is not symmetric; here it is **`cftw_atan2`, whose two
operand pointers were swapped**, which is sharper for the same reason:
atan2 takes y first, so a swap answers a plausible number everywhere
rather than failing loudly anywhere. Swapped and rebuilt, **step 5
fails all twenty transcendental sets while step 4 stays green at
365,845 cases** - `atan2(+0, -0)` comes back `-0` where the vectors say
pi, which is exactly the clause 9.2.1 row cft.h says implementations
most often miss - and `bindings/node/test.mjs` fails 2 of 74 by name
(`atan2(+0, -0) is pi and inexact`, `atan2(-0, +1) is -0`) while
`bindings/node/conformance.mjs` fails all twenty sets. Reverted,
rebuilt, hashes reproduce.

**And the page was opened in a browser again**, because the markup
changed again - eleven rows in the compute panel's table, eleven
entries in the cwrap table - and `verify.mjs` step 5 checks the
wrappers, not the markup between a click and them. Chromium 148 on
Windows 11, the committed `conformance.html` served over a loopback
`http.server` (`file://` is still not reachable from this session).

* Section 1 read *libcft ABI 0.4*; section 2's embedded sample
  replayed **4,015 cases over 20 sets, green**.
* Section 3 took a drop of four transcendental sets and one opcode set
  - **45,569 cases, all matching** - with a deliberately misnamed
  sixth file (`fp64-transcend-rne.jsonl`, which is not a name the
  generator writes) refused by name and the verdict correctly
  downgraded to *not a full pass*. The transcendental sets dropped
  there carry the eleven's cases, so that path saw them too.
* Section 4's panel offered all eleven new operations, each labelled
  with its ABI step and entry point, each enabling exactly the operand
  fields its arity uses. Computed through the button: `sinPi(1)` = +0
  and `sinPi(-1)` = -0, no flags either way, which is the sign rule
  the argument decides; `tanPi(1)` = -0; `tanPi(1/2)` = +inf **with
  divideByZero and not overflow**; `cosPi(3/2)` = +0; `atanPi(+inf)`
  = `0x3fe0000000000000`, exactly 1/2, raising nothing;
  `atan2(+0, -0)` = `0x400921fb54442d18` = pi, *inexact*, against
  `atan2Pi(+0, -0)` = 1 exactly - the two answers side by side, which
  is why atan2Pi is a separate function; and `atan2Pi(1, 0)` = 1/2
  against `atan2Pi(0, 1)` = +0, which is the operand order visible in
  the UI. At binary256: `asinPi(1)` = 1/2 and `acosPi(-1)` = 1, both
  exact and silent, `acosPi(1/2)` = `0x3fffd5555…5555` = 1/3 with
  inexact, and `asin(2)` = the canonical quiet NaN with invalid. A
  65-hex-digit operand was refused by the panel with a count in the
  message rather than truncated.
* `build/negative_control.html` was opened in the same browser and
  failed red at `fp64.jsonl:2` - `expected 0x7ff8000000000001 / got
  0x7ff8000000000000` - so the checker was watched failing on this
  build too, not only on the previous one.

**Measured 2026-09-03, later again**, node 22.19.0 on Windows 11,
against the page rebuilt with the nine phase-3 wrappers in it - in the
same commit as the library's own step to 0.5, so this page never
reported a version whose operations it could not call: module
**140,869 bytes**, sha256 `5718aa19e85dad2b…`, identical to the node
loader's `bindings/node/cft_node.wasm`; `cftw_abi_version()` = 5 =
ABI 0.5, matching `cft.h`; **67 `cftw_*` exports**; **478,915
cases over 40 sets** through `cft_conformance` and the transcendental
cases again through the twenty-nine wrappers themselves, zero
mismatches either way. Two clean container builds produced the same
`conformance.html` (sha256 `69ff0ff911e9ce1e…`). The nine reach the module
with the library's 270,336-bit 2/pi compiled in - the reduction
against pi runs inside the browser at every magnitude binary256
holds. The page was not re-opened in a browser for this step: the
markup changed the way it changed at 0.4 (nine rows in the panel's
table, nine entries in the cwrap table, no new dispatch branch), and
`verify.mjs` step 5 drives the same wrappers the panel calls; the
claim stops there.

## Scope, honestly

* **This is the software backend in a browser.** Full contract
  validation and full computation, at software speed. It is the
  "runs on anything" tier of the adoption story, with "anything"
  now including a browser tab.
* **Device acceleration is not a browser thing.** The tile speaks
  XRT over PCIe; a page does not. Open the same library natively
  with an `.xclbin` and the identical calls run on hardware - the
  page changes the venue of the *check*, never the terms of the
  contract.
* **Browser GPU floating point is the problem, not the platform.**
  WebGL/WebGPU arithmetic varies by vendor, driver and flag - the
  exact nondeterminism this project exists to remove - so nothing
  here touches it. The wasm build is deterministic precisely because
  it stays on specified integer semantics.
* **The sequencer is compiled in but not exported.** No panel drives
  `cft_program_*` yet, and this page only claims surfaces it
  exercises.
* **The page is at ABI 0.2 as of 2026-09-02, surface included.** The
  page committed on 2026-09-01 (5ec0883) was built eighty minutes
  before the clause-5 completion set landed, so its module answered
  `cftw_abi_version()` with 1 and its identity line read *libcft ABI
  0.1* for a day. It has been rebuilt from the same pinned image:
  the module now answers 2, and - the part a version number alone
  would have papered over - `wasm_api.c` gained the twenty clause-5
  wrappers, so the module contains the operations 0.2 names rather
  than merely reporting the number. 38 `cftw_*` exports, 66,422 bytes
  of wasm where the old one was 50,153. The page's markup did not
  change: `page_template.html` is untouched, and the diff is the two
  spliced lines (runtime, build info).
* **Rebuilt 2026-09-03 from the ABI 0.3 sources, and that is a
  half-step, not a 0.3 page.** The build asks `host/Makefile` what it
  compiles, so `mpfloat.c` and `transcend.c` came along on their own:
  the module answers `cftw_abi_version()` with 3 and the
  `cft_conformance` inside it replays the transcendental vector sets.
  What it does NOT have is a `cftw_*` wrapper for any of the nine, or
  a page control for them, so no JavaScript caller can invoke one -
  the module reports a number its surface has not earned, which is
  exactly what the previous bullet warns against, and
  docs/COMPATIBILITY.md's ledger says so in those words. The wrappers
  are the next rebuild's job.
* **The half-step closed the same day: the page is at ABI 0.3,
  surface included (2026-09-03).** `wasm_api.c` gained the nine -
  `cftw_exp`, `cftw_expm1`, `cftw_exp2`, `cftw_log`, `cftw_log1p`,
  `cftw_log2`, `cftw_log10`, `cftw_pow`, `cftw_hypot` - so the module
  now contains the operations 0.3 names rather than only reporting the
  number. 47 `cftw_*` exports, 88,875 bytes of wasm where the
  wrapperless 0.3 build that morning was 88,541 - the nine wrappers
  are 334 bytes, because the arithmetic they reach was already in the
  module and only the doors were missing, which is exactly why a
  version number could not tell the two builds apart. Unlike the 0.2
  rebuild, the **markup did change**, because this time it could be
  contained: the compute panel's operation list is built from a table
  in the page's own script, so the nine are nine rows and one `else
  if` in the dispatch, and the drop zone's accepted-names list gained
  the twenty transcendental sets it had been bouncing. Both are
  exercised without a browser - `verify.mjs` step 5 drives the same
  wrappers the panel calls, and its step 4 replays one dropped set per
  directory the way the drop zone does - which is the only kind of
  claim this file is willing to make about a page nobody watched.
* **The page is at ABI 0.5, surface included, wrappers and rebuild in
  the library's own step (2026-09-03).** Nine more `cftw_*` exports, 67
  in all; 140,869 bytes of wasm where the 0.4 build was 98,392 - the
  nine wrappers, the reduction, the hyperbolics and a 33 KiB constant
  together. Measured above.
* **The page was at ABI 0.4, surface included, and that time there was
  no half-step at all (2026-09-03).** The library reached 0.4 an hour
  before this rebuild, so a rebuild on its own would have answered
  `cftw_abi_version()` with 4 while exporting none of the eleven
  operations 0.4 names - the third occurrence of the failure the two
  bullets above describe. It did not get a third occurrence: the
  wrappers and the rebuild are one commit. 58 `cftw_*` exports, 98,392
  bytes of wasm where the 0.3 build was 88,875 - the eleven wrappers
  and the phase-2 arithmetic behind them together, which is why this
  step is 9,517 bytes where the nine wrappers alone were 334. The
  markup changed again, and contained the same way: eleven rows in the
  panel's table, eleven entries in the cwrap table, no new dispatch
  branch, because the two arity lists the dispatch reads already
  covered both. The drop zone did not change - it has accepted the
  twenty transcendental set names since the morning, and those same
  files now carry all twenty functions.
* Reproducibility claim, precisely: same pinned image + same repo
  state → same page. The vectors are seeded and the sampling is a
  pure function of them; `emcc` is deterministic within the pinned
  image. Across *different* emsdk releases the wasm bytes will
  differ; the arithmetic they compute must not - and the page is
  exactly the instrument that says whether it did.

## Files

```
build.sh             the containerized build, image pinned by tag+digest
wasm_api.c           the exported C surface (cftw_* ≙ cft.h, 1:1)
page_template.html   the page, with three @CFT_*@ splice tokens open
make_page.py         sampling rule + page assembly (+ --corrupt)
conformance.html     THE DELIVERABLE - committed build product
verify.mjs           the browserless check of that build product:
                     identity, module hash, the vector replay, and the
                     twenty driven through their own wrappers
build/               untracked: vectors, module, node loader,
                     negative control
```
