GPU-F's prototype: bn_probe.html.  NOT RUN.

Written 2026-11-13 by study GPU-F as files only. Nobody has opened the page in a
browser, and its WGSL has never been compiled. It claims no result.
Checked: the JavaScript parsed by node --check (nothing executed); the WGSL
checked by reading only, no compiler here. docs/studies/GPU-F-webgpu.md, section 5.

What it is
  One static HTML file: a WGSL kernel (the <script type="text/plain" id="kernel">
  block) and a runner. The kernel is a hand port of host/src/bigint.c's core
  (add, sub, mul, shl, shr, cmp, and softfloat.c's ISUB built from them) over
  8-limb (256-bit) operands into 16-limb results. It is a SECOND IMPLEMENTATION,
  not libcft's code: route (a) of the study, at its smallest.
  Its reference is JavaScript's BigInt, exact by definition: a second witness.
  The reference of record for a conformance page would be the existing
  WebAssembly module, libcft's software backend, held to python/cft_golden by
  the conformance vectors. It is not used here because it does not export the
  bigint core.

What it is for
  The smallest test of the question every route to WGSL shares: does a
  browser's WGSL compiler, on a visitor's GPU, give exact u32 arithmetic for
  the patterns libcft's limbs need (a 32x32->64 product by 16-bit halves, carry
  and borrow chains found by comparison, variable shifts at 0, 31 and 32,
  function-scope arrays indexed at run time), and can the page be seen to fail?

How it would be run (the lead's or Logan's choice)
  1. Open docs/studies/gpu-f/bn_probe.html from a checkout in a browser with
     WebGPU: Chrome or Edge 113 or later on Windows or macOS, Safari 26, Firefox
     141 or later on Windows (READ, the study's section 4). It fetches nothing,
     so file:// should do (BELIEVED: file:// counts as a secure context, which
     navigator.gpu and crypto.subtle need).
  2. Keep lanes 480000 and seed 20261113, and press Run once.
  3. Read the log and the record, then close the tab.

What it would show
  - kernel_sha256 8d6e91b5f8a7e9cd213e49190d47f0d786fb4ab520cd50142e6387c6905cd761
    (COMPUTED here by Python over the kernel text with LF line ends, as a DOM
    holds it). Any other value means another text.
  - compile: errors with line and column, if any. A first run that stops at a
    slip in this hand-written file is a finding about the file, not WebGPU.
  - plants first: PLANT 1 to 4, each on lanes 0 to 47,999; each must make at
    least one lane differ, or the verdict is BLIND. Their counts are not
    predicted.
  - the run: 10 dispatches of 48,000 lanes, every lane's 18 output words
    against BigInt's. PASS; FAIL with the first 8 differing lanes (lane, op, k,
    inputs, expected, got), each of which BigInt can recompute anywhere from
    the lane and seed; BLIND; or REFUSED with its reason, device loss included.
  - wall time per dispatch, submit to map, as performance.now() reports it. It
    includes the copy back and is not a rate.

What it would not show
  Anything about libcft's FMA, its conformance, or its speed in a browser.

The machine that runs it
  A dispatch is 48,000 lanes of at most 64 limb products each (ESTIMATE: well
  under a second on a WebGPU device). Windows resets a GPU that has not yielded
  in 2 s, and more than 5 resets in 60 s bug-check the machine (READ, Microsoft's
  TDR registry keys page on learn.microsoft.com; the study's item 10). A lost
  device ends the run and is never retried.

The record
  JSON in the text box: the schema line, the kernel digest, the generator's
  rule and seed, the adapter's vendor and architecture as the browser reports
  them (possibly empty) and isFallbackAdapter, compile errors and time, the
  plants, the run's counts and first mismatches, and the verdict. Never the
  adapter's device or description, the user agent, the limits or the features.
  Copying it is the visitor's choice: the page sends nothing anywhere.
