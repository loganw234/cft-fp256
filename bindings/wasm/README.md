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
the divide/sqrt seeds 26/27 and the unassigned `reserved15/30/255`
included - that list lost 28 when ABI 0.6 assigned it to `sumsq`. For
the full 1,067,635-case claim, generate the sets in a
checkout (`make vectors`) and drag the `vectors/out/*.jsonl` files
onto the page - same code path, whole files. Verified at build time:
the full 20-set drop replays with zero mismatches, from both
LF (Linux) and CRLF (Windows) generated files.

Since 2026-09-03 the drop zone also accepts the **twenty
transcendental sets** ABI 0.3 added (`<fmt>-transcend[-<rnd>].jsonl`),
which `cft_conformance` has understood since the module
was first built from the 0.3 sources but which the page's own name
list refused - so a `make vectors` drop, the thing this page tells the
reader to do, had half its files bounced. Measured, not assumed:
`verify.mjs` replays every set one file per directory, which is
exactly what the drop zone does with a dropped file, and the drop
itself was watched working in Chromium (see the 2026-09-03 block
below) - four transcendental sets and one opcode set, 32,465 cases,
with a misnamed file still refused by name. Those same twenty files
carry **533,265 cases** since ABI 0.6 completed table 9.1 in them
(242,915 at 0.5, 129,845 at 0.4, 64,325 at 0.3); the file names did
not change, so the drop zone needed nothing for those. It did need
three more families at 0.6, and got them: `<fmt>-augmented.jsonl`
(one per format - 9.5 fixes the rounding, so there is no attribute to
sweep), `<fmt>-reduce[-<rnd>].jsonl` and
`<fmt>-character[-<rnd>].jsonl`. ABI 0.7 added two more:
`<fmt>-minmaxmag.jsonl` (one per format again, and for a stricter
reason - 9.6's magnitude forms *select* an operand, so there is no
rounding at all for an attribute to direct) and
`<sfmt>-to-<dfmt>-formatof[-<rnd>].jsonl`, **eighty** of them, one per
ordered pair of formats per attribute, because 5.4.1 asks for every
destination and, for each destination, every source. **168 names in
all.**

The page is also a working binary32/64/128/256 calculator: one
element through `cft_run()`, the composed `cft_div`/`cft_sqrt`
sequence, or any of the thirty-nine transcendentals - phase 1's nine,
phase 2's eleven, phase 3's nine and the ten that complete table 9.1 -
and since ABI 0.6 the character conversions of clause 5.12, the
payload operations of 9.7, the augmented arithmetic of 9.5 and clause
9.4's remaining reductions. ABI 0.7 adds 9.6's four magnitude forms
and 5.4.1's six formatOf operations, the latter with a second format
select, because a formatOf call's destination is an argument rather
than a mode. Operands and results as raw encodings, a
text field where the operation reads a sequence, two result lines
where it returns a pair, flags decoded, the 7.1 status word under the
result and a button that is the only thing on the page able to lower
it, and every answer pinned by the replay above it.

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
   listed here** (see below), currently thirteen: bigint, softfloat,
   device, divsqrt, clause5, chars, augmented, mpfloat, transcend,
   program, reduce, formatof, conformance
   - `mpfloat.c` and `transcend.c` arrived with ABI 0.3 and
   `formatof.c` with 0.7, each compiled in without anyone editing this
   directory, which is the
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
   every name the drop zone accepts: since ABI 0.7 that is all **168** -
   the twenty opcode sets, the twenty transcendental ones and, when
   `make vectors` has written them, the four augmented, twenty
   reduction and twenty character sets, the four magnitude sets of 9.6
   and the eighty formatOf sets of 5.4.1 (one per ordered pair of
   formats per attribute);
5. drives **every operation that is not an opcode through its own
   wrapper**, reading the same files itself: the thirty-nine
   transcendentals (`cftw_exp` … `cftw_hypot`, `cftw_sinpi` …
   `cftw_atan2pi`, `cftw_sin` … `cftw_atanh`, and since ABI 0.6
   `cftw_exp2m1` … `cftw_rootn`), clause 9.5's `cftw_augmented_add` …
   `cftw_augmented_mul` with their two outputs, clause 9.4's four sum
   reductions through `cftw_reduce` at opcodes 24/25/28/29 and the
   three `cftw_scaled_prod*` with their int64 scale, clause 5.12's
   `cftw_from_decimal_char` … `cftw_set_payload_signaling` - the last
   through the sizing protocol exactly as cft.h states it, short buffer
   included - and since ABI 0.7 clause 9.6's `cftw_min_mag` …
   `cftw_maxnum_mag` and clause 5.4.1's `cftw_formatof_add` …
   `cftw_formatof_fma`, the one family whose operand and result
   buffers are different widths in the same call. One element at a
   time for exact per-case flags, then as
   arrays wherever the C has a batch shape, comparing encodings,
   sequences, scales and flags against the file. Step 4 cannot
   substitute for this and it is worth being blunt about why:
   `cft_conformance` dispatches all of it internally, in C, so it is
   green whether or not a single `cftw_*` wrapper for it exists. For
   a day it was (docs/COMPATIBILITY.md's half-step). Step 5 is the one
   that fails when the JavaScript surface is missing, or present and
   wrong - including `atan2` with its two operands the wrong way
   round, which is the negative control the 0.4 block below records,
   `scaled_prod_diff` the same way at 0.6, and at 0.7 a formatOf call
   whose two formats are the wrong way round.

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

**Measured 2026-09-03, later again**, node 22.19.0 on Windows 11,
against the page rebuilt with the ABI 0.6 wrappers in it - the four
packages in one step, so this module never reported a version whose
operations it could not call: module **196,379 bytes**, sha256
`e8611510973d1081…`, identical to the node loader's
`bindings/node/cft_node.wasm` (and to `build/cft_node.wasm`);
`cftw_abi_version()` = 6 = ABI 0.6, matching `cft.h`; **91 `cftw_*`
exports**, against 67 at 0.5. Five clean container builds produced the
same module, and the last two the same `conformance.html` (sha256
`6fc065e25241bde6…`) - the page's own bytes changed once between them,
when a stale case count in its verdict text was corrected, and the
module did not, which is the split the build is supposed to have.

* **881,657 cases over 84 sets** through `cft_conformance` - the
  twenty opcode sets (236,000), the twenty transcendental ones
  (533,265, now carrying all thirty-nine functions), and the three new
  families: four augmented sets (89,616), twenty reduction sets
  (8,960) and twenty character sets (13,816). `make vectors` writes
  all 84; the drop zone accepts all 84.
* **645,657 of those driven through the wrappers themselves**, which
  is what step 5 grew into: 533,265 transcendental over 20 sets,
  89,616 augmented over 4, 8,960 reduction over 20 and 13,816
  character over 20 - 64 sets in all, since the opcode sets are
  `cftw_run`'s and step 4 is their check. Per case for exact flags,
  then as arrays wherever the C has a batch shape. Zero mismatches
  either way, `VERIFY OK`.
* The character family's step-5 pass runs the **sizing protocol** as
  cft.h states it rather than reading it: a NULL buffer with capacity
  0 must report the required length and refuse, a buffer one byte
  short must refuse with the length still set and **nothing written**,
  and only then does the real call run. All three are checked on every
  `to_decimal` and `to_hex` case, including the fp256 exact decimals
  that run to 183,600 characters.

**How much of the growth is the wrappers**, since the module went from
140,869 bytes at 0.5 to 196,379 here and the honest answer is "almost
none of it". Measured rather than estimated: rebuilding the same 0.6
library with the 0.5 `wasm_api.c` in place - 67 wrappers instead of 91,
everything else identical - gives **193,895 bytes**, so the 24 new
wrappers are **2,484 bytes**, 4.5 % of the 55,510-byte step. The rest
is the library's own new code, which this build compiles because
`build.sh` derives its source list from `host/Makefile`: `chars.c`,
`augmented.c`, `reduce.c` and `transcend.c`'s ten new functions. The
33 KiB 2/pi constant was already in the 0.5 module and is not part of
this step at all.

**The negative control moved with the surface again.** At 0.3 it was
`cftw_pow`, at 0.4 and 0.5 `cftw_atan2`; here it is
**`cftw_scaled_prod_diff`, whose two operand pointers were swapped**,
and it is the sharpest of the four for the reason `atan2` was sharper
than `pow`: the leaf is `a[i] - b[i]`, so a swap negates every factor
and returns a well-formed pair with a correct scale, correct flags and
one wrong sign bit. Nothing errors; the number is plausible everywhere.
Swapped and rebuilt (module sha256 `11cff18d025adcb1…`, a different
module):

* `verify.mjs` **fails all 20 reduction sets in step 5** - the first
  disagreement at `fp32-reduce.jsonl:386`, `expected 0x3fa59621 scale
  25` against `got 0xbfa59621 scale 25`, the same value with the sign
  flipped - while the other three families stay clean (40,000
  transcendental, 8,000 augmented, 13,816 character) and **step 4
  stays green at 110,776 cases over all 84 sets**, the reduction sets
  included. That is the half-step's failure mode exactly: the internal
  replay never calls the wrapper, so it cannot see it broken.
* `bindings/node/test.mjs` fails **1 of 104** by name - *the scaled
  sums and differences are their compositions, a first:
  scaledProdDiff n=1: pr is the composition's*.
* `bindings/node/conformance.mjs` fails **all 20 reduction sets**
  through `Context`'s own methods while its own `cft_conformance` pass
  reports 110,776 cases matching, again green throughout.

Reverted, rebuilt: module sha256 back to `e8611510973d1081…`, so the
tree round-tripped and the reproducibility claim above stands on a
build after a deliberate break rather than only on two in a row.

Those three runs used a **truncated copy** of the sets - the 20
reduction sets whole, since they carry the broken operation, and every
other family headed to 2,000 lines - because the point was to watch
the checker fail rather than to re-prove 1.5 M cases with a
deliberately wrong module. The clean numbers above are the full sets.

**And the page was opened in a browser**, which mattered more here
than at 0.4 or 0.5: the markup changed further than either of those -
three new input controls, a two-line result for each pair, a rounding
select that greys itself out, and five new dispatch branches - and
`verify.mjs` step 5 checks the wrappers, not the markup between a
click and them. Chromium on Windows 11, the committed
`conformance.html` served over a loopback `http.server`.

* Section 1 read *libcft ABI 0.6*; section 2's embedded sample
  replayed **4,015 cases over 20 sets, green**, with no console errors.
* Section 3 took a drop of `fp32-augmented.jsonl`,
  `fp32-reduce.jsonl`, `fp32-character.jsonl` and
  `fp64-reduce-rtz.jsonl` - all three new families - and replayed
  **55,798 cases, all matching**, with a deliberately misnamed fifth
  file refused by name and the verdict correctly downgraded to *not a
  full pass*. Before this step those four names were not in the drop
  zone's list at all.
* Section 4's panel offered **81 operations**, and each new control
  appeared for exactly the operations that use it. Computed through
  the button: `to_decimal(1.5)` at digits 0 gave `1.5e+0` and at
  digits 5 gave `1.5000e+0`, each reporting the length its own sizing
  call returned (7 and 10 bytes, NUL included); `to_hex(1.5)` gave
  `0x1.8p+0` labelled *exact, no attribute*; `from_decimal("1.5")`
  gave `0x3ff8000000000000`, while `"1..2"` and `from_hex("0x1.8")` -
  the latter missing 5.12.3's required binary exponent - were both
  **refused with the reason**, not guessed at. `rootn(8, 3)` = 2 and
  `rootn(-0, 2)` = **+0**, the even-n row where `squareRoot(-0)` is
  -0; `pown(2, 10)` = 1024; `rsqrt(-0)` = **-inf** with divideByZero,
  the sign the standard keeps and MPFR does not.
  `augmentedAddition(nextUp(1), 2^-53)` came back as the pair
  `(nextUp(1), 2^-53)` with the rounding select **disabled and
  labelled roundTiesTowardZero** - the tie roundTiesToEven takes the
  other way. `scaled_prod_diff(1, 2)` gave `pr` = -1 against
  `scaled_prod_diff(2, 1)` = +1, which is the operand order visible in
  the UI and the thing this step's negative control breaks;
  `sumsq([3])` = 9; `get_payload` of a quiet NaN with payload 5 gave
  5.0 with **no flag line at all**, because 9.7 says it signals
  nothing.

Every one of those matches `python/cft_golden`, which is where they
were taken from before they were typed here.

**Measured 2026-09-04**, node 22.19.0 on Windows 11 (DESKTOP-T33SK86),
against the page rebuilt with the ABI 0.7 wrappers in it - the two
packages in one step, so this module never reported a version whose
operations it could not call: module **211,869 bytes**, sha256
`04c3aad8748c9555…`, identical to the node loader's
`bindings/node/cft_node.wasm` (and to `build/cft_node.wasm`); **111
`cftw_*` exports**, against 91 at 0.6, with **80 named entry points**
checked present by name. `cftw_abi_version()` reads **6 = ABI 0.6, and
so does `cft.h`** - the integrator bumps `CFT_ABI_VERSION_MINOR` once,
for the whole 0.7 step, and `verify.mjs` compares the module against
the header rather than against a number typed into it, so this line
goes to 0.7 on that commit with nothing here to change. Two clean
container builds produced the same module and the same
`conformance.html` (**1,336,073 bytes**, sha256 `cf43d9b11ae34d28…`),
and a third after the negative control below was reverted.

The numbers below are one standardized run,
`bash verify/run.sh --fresh --only vectors,node,wasm`, run id
**20260904-030316-6b9a845** on a clean tree: `vectors` 275 s, `node`
1438 s, `wasm` 1100 s, **VERDICT: PASS, nothing skipped** (its state
directory lived in the JavaScript step's worktree and was not kept;
the re-run on the rebuilt module, 20260904-054715-2216e62, is in the
tree and reproduced the counts). It is the
second of two: the first (20260904-021432-cfab84c) ran while these two
README files were being written, so its header says *TREE DIRTY* and
it certifies nothing by this repository's own rule - it is recorded
only because it reported the same counts, stage for stage, which is
what a rerun on the same sources should do.

* **1,223,635 cases over 168 sets** through `cft_conformance` - the
  twenty opcode sets, the twenty transcendental ones (533,265), the
  four augmented (89,616), twenty reduction (8,960) and
  twenty character (13,816) sets of 0.6, and the two new families:
  four magnitude sets of 9.6 (**9,728**) and eighty formatOf sets of
  5.4.1 (**176,250**), one per ordered pair of formats per attribute.
  `make vectors` writes all 168; the drop zone accepts all 168. (That
  count is larger than the **1,067,635** the page quotes for
  `make vectors`, and the difference is entirely the opcode sets:
  `verify/run.sh`'s own `vectors` stage takes the generator's default
  directed/random/simple pools rather than `make vectors`'s
  `--directed 3000 --random 4000 --simple 200`, so its opcode sets
  carry 19,600 lines each where the published ones carry 11,800. The
  other six families are pool-size-independent and identical either
  way, which is why the step-5 numbers below are the same in both.)
* **831,635 of those driven through the wrappers themselves**, over
  the 148 sets that are not opcode sets - the four families of 0.6
  plus 9,728 magnitude cases over 4 sets and 176,250 formatOf cases
  over 80. Per case for exact flags, then as arrays wherever the C has
  a batch shape. Zero mismatches either way, `VERIFY OK`.
* The formatOf family is the first whose **operand and result
  encodings are different widths on the same line**, so its driver
  sizes every buffer from the format it belongs to and checks the
  record's own `sfmt`/`dfmt` against the file's name - with two
  formats there is a pairing to get wrong, and a set whose name and
  contents disagree is a failure mode no other family has.

**The negative control moved with the surface again.** At 0.3 it was
`cftw_pow`, at 0.4 and 0.5 `cftw_atan2`, at 0.6 `cftw_scaled_prod_diff`;
here it is **`cftw_formatof_sub`, whose two operand pointers were
swapped** so that the wrapper computes b - a. It is the same shape of
mistake for the same reason those were chosen: nothing errors, the
magnitude is right, and exactly one sign bit is wrong, so a checker
that looked only for a crash or a NaN would walk past it. Swapped and
rebuilt (module sha256 `2796f430c7d2c265…`, a different module):

* `verify.mjs` **fails all 80 formatOf sets in step 5** - the first
  disagreement at `fp32-to-fp32-formatof.jsonl:41`,
  `formatOf-sub fp32 -> fp32 rne`, `a 0x00000000 b 0x00000001`,
  `expected 0x80000001, got 0x00000001`: the same value with one sign
  bit, on a SAME-FORMAT pair, because an operand swap needs no change
  of format to show. The other five families stay clean (4,825
  transcendental, 967 augmented, 8,960 reduction, 6,372 character, 976
  magnitude) and **step 4 stays green over all 168 sets**, the 80
  formatOf sets included. That is the half-step's failure mode exactly:
  the internal replay never calls the wrapper, so it cannot see it
  broken.
* `bindings/node/conformance.mjs` fails **the same 80 sets** through
  `Context`'s own methods - 68 of 148 clean, and its `cft_conformance`
  pass reports 47,620 cases over 168 sets matching, green throughout.
* `bindings/node/test.mjs` fails **1 of 125** by name: *a same-format
  formatOf call IS the operation that was already here*, at binary32
  under roundTiesToEven. **Which one test that is, is the row worth
  keeping.** The batch test - `mapFormatOf` against the scalar methods
  - stays GREEN, because the control changes both identically and that
  test compares the package with itself; so does every test that
  drives `add`, `mul`, `div`, `sqrt` or `fma`. The one that catches it
  is the one that compares formatOf against `cft_run`/`cft_div`/
  `cft_sqrt` - a different thing, asserted for exactly this reason.

Reverted, rebuilt: module sha256 back to `04c3aad8748c9555…` and
`conformance.html` back to `cf43d9b11ae34d28…`, so the tree
round-tripped and the reproducibility claim above stands on a build
after a deliberate break rather than only on two in a row.

Those three runs used a **thinned copy** of the sets - all 168 names,
each strided down to about 240 lines - because the point was to watch
the checkers fail rather than to re-prove a million cases with a
deliberately wrong module. A `head` would not have done: the formatOf
and magnitude sets are grouped by operation, so the first 240 lines of
a formatOf set are all `add` and the broken `sub` would never have
been reached. The clean numbers above are the full sets.

**And the page was opened in a browser**, which mattered again: the
markup changed further than `verify.mjs` can see - a second format
select that appears for six operations and no others, a rounding
select that greys itself out for a second and different reason, a
status word rendered under the result, and a button that is the only
thing on the page able to lower a flag. Chromium 148 on Windows 11,
the committed `conformance.html` served over a loopback `http.server`
because this session's browser will not open a `file://` path.

* Section 1 read *libcft ABI 0.6* (the header's own answer, see above)
  and, new at 0.7, **`is754version1985 no   is754version2008 no
  is754version2019 yes`** - asked of the library, not restated by the
  page. Section 2's embedded sample replayed **4,015 cases over 20
  sets, green**, with no console errors.
* Section 3 took a drop of `fp32-minmaxmag.jsonl`,
  `fp256-minmaxmag.jsonl`, `fp64-to-fp32-formatof.jsonl` and
  `fp128-to-fp32-formatof-rtz.jsonl` - both new families - and
  replayed **13,414 cases, all matching**, with a deliberately
  misnamed fifth file (`fp64-to-fp32-formatOf.jsonl`, one capital)
  refused by name and the verdict correctly downgraded to *not a full
  pass*. Before this step those four names were not in the drop zone's
  list at all.
* Section 4's panel offered **91 operations**. `max_mag(+3, -3)` gave
  **+3** and `min_mag(+3, -3)` gave **-3** - 9.6's "otherwise",
  deferring to maximum and minimum, which is the one row a wrong
  reading is visible on - with the rounding select **disabled and
  labelled** *there is no rounding here for an attribute to direct*,
  which is a different sentence from the augmented three's *9.5 fixes
  this operation's rounding*. The destination select appeared for the
  formatOf six and for nothing else.
* The formatOf rows, computed through the button at binary64 →
  binary32 under roundTiesToEven: `formatof_add` of
  `0x8037478c91215dae` and `0xb690000000000000` - about -2^-968 plus
  exactly -2^-150, a hair past half of binary32's least subnormal -
  gave **`0x80000001` with underflow and inexact**, the destination's
  exceptions on the destination's grid and the row that caught the
  MPFR harness double rounding (docs/VALIDATION.md). `formatof_mul` of
  2^100 by 2^100 gave **+inf with overflow and inexact**, an exception
  the same multiply raises nowhere in binary64 (`test.mjs` asserts that
  half). And the
  double-rounding witness: `formatof_fma` of `0x3ff0000010000000` ×
  1 + binary64's smallest subnormal - a product that IS binary32's
  midpoint between 1 and nextUp(1), plus a hair - gave
  **`0x3f800001`**, while the same product *without* the addend gave
  **`0x3f800000`**, the tie broken to even downward. Those two values
  one ulp apart, in the same panel, are what "narrowing may not be
  double rounded" means.
* The status word read `0x00` on load, `0x1d` (invalid, overflow,
  underflow, inexact) after section 2's replay - a replay is calls,
  and the page says so rather than exempting itself - `0x00` again
  after the button, and then accumulated `0x18` and `0x1c` across the
  formatOf calls above while each call's own `flags` line stayed its
  own. `build/negative_control.html` was opened in the same browser
  and failed red at `fp64.jsonl:2` with the library's own
  disagreement, so the checker was watched failing here too.

Every one of those matches `python/cft_golden`, which is where they
were derived from before they were typed here.

**What was NOT run, and why.** The gate for this step was
`bash verify/run.sh --only vectors,node,wasm`, so the library's own
stages - `libcft`, `cpp`, `mpfr`, `formatof`, `status96`, `bindings` -
and the RTL ones did not run here. They belong to the two package
commits that landed the C, which docs/VALIDATION.md records; nothing
under `host/`, `python/` or `vectors/` was touched by this step, and
the module this page carries is compiled from those sources unchanged.
No device backend was exercised: wasm32 has no XRT and no PCIe, and
the software backend is the only device a browser can be. No other JS
engine was measured - the argument for cross-engine agreement is the
wasm integer spec, and the measurement is V8 (node 22.19.0 and
Chromium 148), which is one engine family. And
`CFT_ABI_VERSION_MINOR` still reads 6: the integrator bumps it once
for the whole 0.7 step, and every check here compares the module
against the header rather than against a version typed into a test.

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
                     identity, module hash, the 168-set vector replay,
                     and every non-opcode operation driven through its
                     own wrapper
build/               untracked: vectors, module, node loader,
                     negative control
```

### Rebuilt after the bump, 2026-09-04

The block above was measured on a tree whose `cft.h` still read 0.6:
the integrator's bump to 0.7 came after the JavaScript step this time,
the opposite order from 0.6, and the full run on the bumped tree
refused the page on one line - `cftw_abi_version() = 6 (0.6); cft.h
says 7 (0.7)` - which is the check doing its job. The page and the
module were rebuilt on the bumped tree with `build.sh`, twice, in the
pinned container, byte-identical: `conformance.html` **1,336,073
bytes**, sha256 `e1b42b3873416e39…`; module **211,869 bytes**, sha256
`a1f0a4715516d3f6…` (the same bytes as `bindings/node/cft_node.wasm`);
`cft_node.js` unchanged. Sizes identical to the block above, hashes
different by the one constant. `verify.mjs` then ran under
`bash verify/run.sh --fresh --only vectors,node,wasm`, run id
`20260904-054715-2216e62`, and passed with the same counts as the block above.

---

## A second page: the five workloads, measured (2026-09-04)

`demos.html` is the other deliverable of this directory. Same
directory, same container, same pinned image, and **the same module** -
but where `conformance.html` replays vector sets, this one runs the
five contract workloads of `docs/BENCHMARKS.md` and prints, beside
each result, the SHA-256 chain the native C tool produced for exactly
that configuration. `docs/DEMOS.md` is the argument; this block is what
was measured.

```
demos_template.html  the page, with six @CFT_*@ splice tokens open
demos_core.js        the compute core: five panels, each a port of one
                     tool's --engine loop path. A PLAIN SCRIPT, so the
                     page's Worker and node run the same bytes.
demos_worker.js      the driver - Worker, or main thread where a
                     browser refuses a blob: Worker from file://
demos_chains.json    what the NATIVE tools printed: 11 configurations,
                     13 chains, each with its command line
make_demos.py        page assembly (+ --corrupt), and the three module
                     identity checks
build_demos.sh       the containerized build; the image pin is READ
                     OUT OF build.sh rather than typed again
demos.html           THE DELIVERABLE - committed build product
verify_demos.mjs     the browserless check: module, core, and every
                     chain three ways (tool, core, recording)
```

**The page.** 486,822 bytes, sha256
`e3711319627e68281dc97636a65da169b9c3b8d467ed45b2e1da9bceb6538a67`.
Two clean container builds with `bindings/wasm/build/` removed between
them: byte-identical. emcc 6.0.9 (4e4223852a...), the image `build.sh`
pins.

**The module, three checks of one fact.** The demos page's chains are a
claim about a specific program, so the build refuses to ship a page
whose module is not the committed one: the split `.wasm` from the same
emcc run is hashed against `bindings/node/cft_node.wasm` (stage 2),
`make_demos.py` re-checks it and then walks the bytes back out of the
assembled HTML (stage 3), and `verify_demos.mjs` walks them out again
from the committed file. All four agree on **211,869 bytes, sha256
`a1f0a4715516d3f6...`** - the same module `conformance.html` embeds.
The one emcc flag that differs from `build.sh` is
`-sENVIRONMENT=web,worker`, which selects branches of the JavaScript
loader and nothing else; stage 2 does not assume that, it checks it.

**The chains.** 13, over 11 configurations, all reproduced three ways:

| | node, over the committed module | Chromium, in a Web Worker |
|---|---|---|
| chains reproduced | 13 of 13 | 13 of 13 |
| against | the tool run just now, and the recording | the recording |

The page's verdict line after a full run reads *"13 of 13 chains
computed in this browser, every one identical to the C tool's."*
`docs/DEMOS.md` lists every chain with the command that produced it.

**Rates, wall clock over work done.** Both sides are the software
backend on the same desktop, single-threaded. These are measurements of
a slow software tier, not a performance claim.

| panel / run | native `--engine loop` | node (wasm) | Chromium (wasm) |
|---|---|---|---|
| zoom / fp256-reference | 346,414 pixel-iter/s | 269,380 | 343,381 |
| zoom / fp64-reference | 383,738 pixel-iter/s | 251,440 | 297,215 |
| orbits / fp256 | 24,922 element-steps/s | 17,210 | 22,645 |
| orbits / fp64 | 55,589 element-steps/s | 47,216 | 50,945 |
| collatz / sweep | 221,294 steps/s | 149,228 | 173,491 |
| collatz / trajectory | 239,666 steps/s | 42,754 | 58,865 |
| enclose / fp256 | 1,526 enclosures/s | 980 | 1,247 |
| mersenne / to-2281 | 646,661 limb products/s | 403,953 | 473,911 |

0.8x to 1.4x of native wherever a call carries a batch; the collatz
trajectory row is one lane at 23 wasm crossings per step, which is the
boundary and not the arithmetic.

**The negative control.** `build_demos.sh` also writes
`build/demos_negative_control.html` (untracked), identical except that
the Collatz panel's running peak is computed with `CFT_MIN` instead of
`CFT_MAX` - a change that leaves the flag/witness agreement, the step
count and the final value all correct, and only the chain wrong. Its
Collatz panel reports **2 of 2 chains DIFFER**; the same edit made to
`demos_core.js` makes `verify_demos.mjs` fail four times (each chain
against both the tool and the recording); restoring the file makes both
green again. A checker that has never been seen to fail proves nothing.

**No network at runtime.** Loading the page costs one GET for the file
and one for the Worker's `blob:` URL. Nothing else appears in the
network log, from `file://` or over a server.
