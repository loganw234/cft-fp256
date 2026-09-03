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

The page is also a working binary32/64/128/256 calculator: one
element through `cft_run()` (or the composed `cft_div`/`cft_sqrt`
sequence), operands and results as raw encodings, flags decoded -
every answer pinned by the replay above it.

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
   listed here** (see below), currently seven: bigint, softfloat,
   device, divsqrt, clause5, program, conformance; the XRT backend is
   not compiled, wasm32 having no PCIe to speak - plus `wasm_api.c`,
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

`wasm_api.c` is the module's complete exported surface: 38 `cftw_*`
wrappers that project `host/include/cft.h` one declaration at a time,
adapting only what JavaScript cannot reach (out-params, the sized
caps struct, a uint64). No invented semantics; cft.h remains the
contract. Since 2026-09-02 that includes the clause-5 completion set
- `cftw_rint`, `cftw_convert`, the eight integer conversions,
`cftw_scaleb`/`cftw_logb`, `cftw_next_up`/`_down`, `cftw_class`,
`cftw_total_order`(`_mag`), `cftw_cmp_sig`, `cftw_rem` - which the
page does not call and a module claiming its ABI version should not be
without.

## Verifying it, without a browser

```bash
make vectors                       # from the repo root, once
node bindings/wasm/verify.mjs      # 2 s, node 22
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
   library's own file-reading path, one call per set.

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
* **The page is at ABI 0.3 as of 2026-09-03, surface included.** The
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
verify.mjs           the browserless check of that build product
build/               untracked: vectors, module, node loader,
                     negative control
```
