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
the toolchain is identical on every machine. Stages:

1. regenerate the published vector sets into `build/vectors/` with
   the exact `make vectors` arguments (deterministic, seed 3; the
   build trusts its own regeneration, not whatever `vectors/out`
   holds);
2. `emcc` the six library sources - bigint, softfloat, device,
   divsqrt, program, conformance; the XRT backend is not compiled,
   wasm32 having no PCIe to speak - plus `wasm_api.c`, twice with
   identical flags: split (`.js` + `.wasm`, so the reported wasm size
   is a measured fact) and `-sSINGLE_FILE` for embedding;
3. `make_page.py` samples the sets and splices runtime, sample and
   provenance into `page_template.html` → `conformance.html`;
4. the same assembly with `--corrupt` →
   `build/negative_control.html` (untracked): one expected value
   deliberately flipped, so anyone can watch the page fail. The
   corrupted expectation, the red verdict and the library's verbatim
   disagreement report are the proof that this checker *can* fail;
   a checker never seen failing proves nothing.

**The sampling rule** (also in `build.sh`, `make_page.py`, and on the
page): from each of the 20 sets (4 formats × 5 rounding attributes,
11,800 lines each) take every 59th line - 0-based lines 0, 59, 118, …
= exactly 200 per set - then add the set's first line of any opcode
name the stride missed, so every opcode class is embedded per set by
construction rather than by luck. `conformance.html` is a committed
build product; rebuild it with the pinned image and the only intended
diff is none.

`wasm_api.c` is the module's complete exported surface: `cftw_*`
wrappers that project `host/include/cft.h` one declaration at a time,
adapting only what JavaScript cannot reach (out-params, the sized
caps struct, a uint64). No invented semantics; cft.h remains the
contract.

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
build/               untracked: vectors, module, negative control
```
