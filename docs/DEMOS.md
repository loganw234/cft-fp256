# The five workloads, in a browser tab

`bindings/wasm/demos.html` is one self-contained HTML file that runs
the five contract workloads of `docs/BENCHMARKS.md` - zoom, orbits,
Collatz, enclose, Mersenne - on the **same wasm module the conformance
page embeds**, and prints, beside each result, the SHA-256 chain the
native C tool produced for exactly that configuration.

That is the whole claim, and it is one sentence: **the browser computes
the same bits as the C tool.** Not "an equivalent implementation
agrees to a tolerance"; the same records, hashed the same way, matching
to the digit.

    bash bindings/wasm/build_demos.sh          # build the page
    node bindings/wasm/verify_demos.mjs        # check it without a browser

Live beside the conformance page at
<https://loganw234.github.io/cft-fp256/demos.html>.

| | |
|---|---|
| page | `bindings/wasm/demos.html`, 539,646 bytes |
| sha256 | `b78d6a6dd57e7411ef98783c17f080bb3d429ab50e021926fba2638e9924fdc1` |
| module | `bindings/node/cft_node.wasm`, 225,354 bytes, sha256 `29cce150ec46676ba4783e5d8395c825ce85930b0999de2e422ad7b050bcfea4` |
| toolchain | emcc 6.0.9 (4e4223852a0835923411059a3929907d7df1232e), `emscripten/emsdk:6.0.9@sha256:96617f27fe16421588241def73908fd348a7f9d260440ed0d00b36dcf7a063cc` |
| configurations | 13, over 15 chains |
| recorded | 2026-09-09, per `bindings/wasm/demos_chains.json`'s own `recorded` field |

---

## Why this page exists next to the conformance page

`conformance.html` answers "does the library still produce the
published bits?" by replaying vector sets. It is the right check and
it is not a picture of anything. These five workloads were written the
other way round - each for a property the contract has and a
conventional float library does not - and each of them has an
*output you can look at*: a frame, an ellipse, a trajectory, a bar
chart, a residue.

So the page is a demonstration that carries its own proof. Every panel
draws a picture, and under the picture is a hash that either matches
the C tool's or does not. A demo whose only evidence is that it looks
plausible is a screenshot; this one fails red when it is wrong, and
`bindings/wasm/build/demos_negative_control.html` exists so that
"fails red" is something anyone can watch happen.

## What each panel shows, and why it needs this contract

### 1 - zoom (`host/tools/zoom.c`, `docs/ZOOM.md`)

A deep-zoom Mandelbrot frame by perturbation: one **reference orbit**
at binary256, and 16,384 pixels each carrying a binary64 offset from
it. The panel draws the frame row-block by row-block as the pixels
resolve, and beside it the frame the *same code* produces when the
reference is computed at binary64 instead.

The two pictures are the argument. At this depth one pixel is
`2^-202`, about `1.6e-61`. The fp256 reference lands on the period-51
nucleus the tool derives, and the frame is a minibrot. The fp64
reference rounds the centre to exactly `-2`, which is
**1.87668e+31 pixels** away from where the view is, and the frame is a
smooth gradient of something else entirely - computed without a single
flag being raised. Nothing in binary64 says "you are not where you
think you are"; the only thing that says it is a wider format to
compare against.

What the contract supplies: a bit-identical fp256 reference orbit, so
the frame is the same frame on every host, and correctly rounded
binary64 for the perturbation so the pixel chain is too.

### 2 - orbits (`host/tools/orbits.c`, `docs/ORBITS.md`)

A Kepler two-body problem at eccentricity 3/4, integrated with
Stormer-Verlet, by an ensemble of eight members whose initial
conditions differ by a ladder of single ulps. The panel runs the same
ensemble at fp256 and at fp64 and plots three things: the ellipse, the
two invariant drifts, and the ensemble separating.

The middle plot is the point. **Energy drift is a property of the
method** - the leapfrog scheme has an `O(h^2)` bounded energy error,
and it is `7.9e-4` at fp256 and `7.9e-4` at fp64, because it has
nothing to do with the arithmetic. **Angular-momentum drift is a
property of the arithmetic** - the scheme conserves `L` exactly, so
every bit of drift is roundoff, and it is `4.2e-70` at fp256 against
`7.9e-15` at fp64. The two lines sit about `2^184` apart on a log
axis, and that gap is the whole of what the width bought.

The panel runs the ensemble twice more, at `--rsqrt newton`, and those
two runs are there for a different reason: they are the route a
sequencer program can hold, so they are where the page's program engine
has something to be equal to. They are **different arithmetic** - a
published Newton refinement from the tile's own seed opcode, not the
correctly rounded `cft_sqrt`/`cft_div` route - with chains of their own,
and they are not the panel's argument. The plots draw whichever pair
ran last.

The third plot needs a note. The members' separation `|q_m - q_0|` is
computed **in the run's own format** and only then converted to a
double for the axis. It has to be: at fp256 two members differ by
about `1e-70`, and their binary64 shadows agree to every bit binary64
has, so subtracting *those* would plot a flat zero. Every printed
quantity on this page goes through the same route (see "presentation"
below), but this is the one where it changes what you see.

### 3 - Collatz (`host/tools/collatz.c`, `docs/COLLATZ.md`)

The trajectory of any typed starting value, as a log plot, with the
`2^p` exactness edge drawn across it - and a short sweep beneath, as a
stopping-time scatter.

Every integer below `2^p` is exact in a binary format, so at fp256 a
seventy-two-digit starting value is ordinary arithmetic. The default is
`2^237 - 1315`, computed in the page rather than typed, which resolves
in **2,437 exact steps**. The tool's rule - and the port's - is that a
step is committed only when `3n+1` was computed *exactly*, and the
witness for that is not a comment: over every call, the library's
INEXACT flag and the tool's per-element exactness witness must agree,
or the run stops. Type a value near the edge, or drop the format to
fp32, and the plot marks the step where exactness ended.

What the contract supplies: exact integers to `2^237` and the inexact
flag as the certificate. A float library that reports "close enough"
cannot draw that line, because it does not know where the line is.

### 4 - enclose (`host/tools/enclose.c`, `docs/ENCLOSE.md`)

Three interval kernels - a series, a dot ladder, an interval Horner -
run at **all four formats**, with the dot ladder's enclosure widths
drawn as bars on a log axis.

The ladder is a dot product whose exact value is `1` and whose terms
cancel over an exponent spread that grows down the rungs. Evaluate the
lower end under roundTowardNegative and the upper under
roundTowardPositive and the true value is inside, always - the question
is only whether the answer is *useful*. At the widest rung:

| format | lower bound | upper bound | |
|---|---|---|---|
| fp32 | -5.2368e+11 | 3.0095e+11 | straddles 0 |
| fp64 | -7.6800e+02 | 6.4000e+02 | straddles 0 |
| fp128 | 1.0000e+00 | 1.0000e+00 | encloses |
| fp256 | 1.0000e+00 | 1.0000e+00 | **exact** |

Every one of those is a rigorous bound. Two of them say "the answer is
somewhere between minus a lot and plus a lot", which is true and worth
nothing. At fp256 all fifteen dot enclosures come back with both ends
equal and the flag word clean - the bars sit flat on the axis - which
is the certificate that not one addition in the tree rounded.

What the contract supplies: roundDown and roundUp per instruction, and
a fixed reduction tree so that both ends are computed over the same
associations.

### 5 - Mersenne (`host/tools/mersenne.c`, `docs/MERSENNE.md`)

A Lucas-Lehmer verifier with a progress bar and the residue chain:
exponent, verdict, squarings, limb geometry, `res64`, and a SHA-256 of
the residue limbs.

fp256 holds every integer below `2^237` exactly, so a wide integer
becomes an array of limbs and its square becomes a convolution of
`CFT_DOT` reductions - and the reductions' **clean flag word is the
certificate that not one limb product rounded**. The limb width is
derived from the format's own measured `p` (`2b <= p`,
`L * 2^(2b) <= 2^p`, `d + 2 <= b`), never tabulated: at `P = 2281`
that is 20 limbs of 115 bits. Two composite controls, 1277 and 1619,
are in the default set so the verdict is checked in both directions.

The larger exponents are offered behind a time warning, and the
warning says the honest thing: they compute something the recorded
chain is not about, so the panel will say "other config" rather than
"match".

---

## The scaled parameters

The tools' defaults are sized for a workstation over minutes. These are
sized for a browser tab over seconds, and every one is expressible in
the tool's existing flags - no tool was edited to make a configuration
reachable.

| panel | the tool's default | the page's default | why |
|---|---|---|---|
| zoom | 64x64 px, 100,000 reference iterations, 4,096 cap | 128x128 px, 1,001 reference iterations, 1,000 cap | the frame wants resolution more than orbit length; 1,001 reference points is one more than the cap, which is what the pixel phase reads |
| orbits | 16 members, 16 periods x 1,024 steps, sampled per period | 8 members, 4 periods x 512 steps, sampled every 32 | 2,048 steps and 65 samples: enough for a closed ellipse and a readable drift curve |
| collatz | sweep from 1, batch 4,096 | one deep value (`2^237 - 1315`, batch 1) and a sweep of 1..1000 (batch 1,000) | the trajectory is one lane by construction; the scatter wants a thousand |
| enclose | 1,024 points, `--cond-max 225` | 16 points, `--cond-max 164`, one run per format | see below |
| mersenne | the 13-exponent `known` set to 11213 | the first seven, 521..2281 | 9,773 squarings, seconds; the rest is a button with a warning |

**`--cond-max 164` is derived, not chosen.** The tool's own default of
225 is *refused* at binary32: the ladder's smallest element is
`2^(dot_top - 2*mw - spread)` and at `dot_top = 60`, `mw = 11` that is
`2^(38 - 225) = 2^-187`, below binary32's smallest normal, so
`dot_representable()` stops the run. The largest spread every format
holds exactly is therefore `dot_top - 2*mw - emin(binary32)` =
`60 - 22 - (-126)` = **164**, and the page computes it from
`measureFormat("fp32")` rather than carrying the number. That is what
lets fp32 appear in the ladder at all - and at 164 the story is
unchanged: fp32 and fp64 straddle zero on 14 of 15 enclosures, fp128
and fp256 on none, and fp256's fifteen are exact.

Every parameter above is a control on the page. Retuning one is
expected and is not a failure: the panel then says **"other config"**
against the recorded chain and counts for nothing, because "DIFFER"
there would be a claim about which of the two is wrong.

---

## The chain pairs, and how each was produced

Each tool records `chain_0 = 32 zero bytes`,
`chain_(i+1) = SHA-256(chain_i || record_i || "\n")` over its records
in a fixed order. Two of the five (zoom, and only zoom) keep two
chains: one over the reference orbit, one over the pixels.

The browser configuration is **defined by the native tool's own flags**
in every case: the command below is the command, run from the repo
root, that produced the chain the page prints as "native tool
(recorded)". Where a tool's chain covers records the browser
configuration does not compute, the browser configuration was chosen so
that it does - which is why the zoom panel runs 1,001 reference
iterations rather than the tool's 100,000, and why the collatz panel is
two runs rather than one.

| # | panel / run | native command | chain |
|---|---|---|---|
| 1 | collatz / trajectory | `./host/cft-collatz --engine loop --format fp256 --mode deep --values 220855883097298041197912187592864814478435487109452369765200775161576157 --batch 1` | `b13572843b19a7efba863c3c32390e6730108fe40bd8213acee7400bad676a2f` |
| 2 | collatz / sweep | `./host/cft-collatz --engine loop --format fp256 --mode sweep --from 1 --to 1001 --batch 1000` | `c2ccab682e3747261561871ee0f99d3b3d43f88fa7fa4de18eff7e46a0555c51` |
| 3 | zoom / fp256-reference (orbit) | `./host/cft-zoom --engine loop --format fp256 --width 128 --ref-iters 1001 --pixel-iters 1000 --batch 1024` | `ebec460efc657fa70293a5ade8f8919cd3f06afbd4b5603be6a3f3a66ecf9b3d` |
| 4 | zoom / fp256-reference (pixels) | (the same run) | `5fb8f0de8bb1be57ef39f7a0f69520d0ed8f0cdd0cad600a6e7e4ada757d11f3` |
| 5 | zoom / fp64-reference (orbit) | `./host/cft-zoom --engine loop --format fp64 --width 128 --ref-iters 1001 --pixel-iters 1000 --batch 1024` | `9c83048409fa65ad1cd0524f0463f0d8bf747e5d4d8ed6c3e3a7844758674258` |
| 6 | zoom / fp64-reference (pixels) | (the same run) | `878ae482df8da39326d658c0ec9047d1a29c2b1eb15902a24175d4e899c81dda` |
| 7 | orbits / fp256 | `./host/cft-orbits --engine loop --rsqrt exact --format fp256 --members 8 --periods 4 --steps-per-period 512 --sample-every 32` | `12012be36beb6d5fc15f9b4b17e84af30923399503a744bdef7a6e4042d93cc9` |
| 8 | orbits / fp64 | `./host/cft-orbits --engine loop --rsqrt exact --format fp64 --members 8 --periods 4 --steps-per-period 512 --sample-every 32` | `3ebf95ae53d96a38c5b541ec08cb9c6d60e59cb7727cdc6ea5ae5aba6d4aa96a` |
| 9 | orbits / fp256-newton | `./host/cft-orbits --engine loop --rsqrt newton --format fp256 --members 8 --periods 4 --steps-per-period 512 --sample-every 32` | `d1e580c42eee48f2fad8d14fbf0c1b5529dc3b74287ea16e35ce3a8a27df78d8` |
| 10 | orbits / fp64-newton | `./host/cft-orbits --engine loop --rsqrt newton --format fp64 --members 8 --periods 4 --steps-per-period 512 --sample-every 32` | `6b38342d22e85da1d432077fe1c1e90853337a7dff5620352596bd95b4001c2a` |
| 11 | enclose / fp32 | `./host/cft-enclose --engine loop --format fp32 --kernels series,dot,horner --points 16 --cond-max 164` | `d9f761c22220f1aa185c2ccbfbf4b2d83e4f8d84dced8e61cdb8882d7528b208` |
| 12 | enclose / fp64 | `./host/cft-enclose --engine loop --format fp64 --kernels series,dot,horner --points 16 --cond-max 164` | `835ca8ab9aa3358d6ad0dcfdf167e813a65ed3bfb5dffcf31b32927f28c7e3d1` |
| 13 | enclose / fp128 | `./host/cft-enclose --engine loop --format fp128 --kernels series,dot,horner --points 16 --cond-max 164` | `4ff5b22ba2333153491c101eb8aab83e4128a051a50d73e0e654a07438cc4f0c` |
| 14 | enclose / fp256 | `./host/cft-enclose --engine loop --format fp256 --kernels series,dot,horner --points 16 --cond-max 164` | `93cdda3270eaa7ba434ddbbabcc54d77a5afa28779e05bccef4f7b81cc43400c` |
| 15 | mersenne / to-2281 | `./host/cft-mersenne --engine loop --format fp256 --exponents 521,607,1277,1279,1619,2203,2281` | `7555f58433fa902b06a0c2b7057d8d1b86b55e2aeff7636abb55ef53c0d80aca` |
All fifteen were reproduced by the compute core under node, and all
fifteen again in Chromium, in a Web Worker, over
`bindings/node/cft_node.wasm` - with the zoom and orbits panels on the
**sequencer program engine**, which is what makes rows 3-6, 9 and 10 a
statement about two engines rather than one. The page's own verdict
line after a full run reads:

    15 of 15 chains computed in this browser, every one identical to
    the C tool's.

`bindings/wasm/demos_chains.json` is the recorded file: for each run it
carries the command, the configuration, the chains, and the tool's own
cost lines. It also carries the sha256 of the module and of the compute
core it was recorded against, and `make_demos.py` **refuses to build a
page** whose module or core does not match - a chain recorded against a
different program is a chain about a different program.

---

## How the panels were ported

Each panel is a port of one tool's engine. Three of the five have only
the `--engine loop` path, because their step does not fit the program
model and each says exactly what stopped it - docs/SEQUENCER.md's "What
the workloads asked of the program model" is that list. **Two of them,
zoom and orbits, carry both engines**, because since 2026-09-07 the
wasm module exports the sequencer's program API. It began as five -
`cftw_program_load`, `cftw_program_get_info`, `cftw_program_run`,
`cftw_program_free` and `cftw_status_deposit_overflow`, one per
declaration in cft.h's program section plus the macro projected as a
call - and grew with each sequencer revision the same way: thirteen in
`bindings/wasm/wasm_api.c` today, adding `cftw_program_run_bank`,
`cftw_program_digest`, `cftw_program_flags`, `cftw_program_run_ex`,
the three scratch accessors and two more macro projections.

The engine is a control on those two panels and it changes no bit. Each
tool's own gate already holds its two engines to byte-identical
records; `verify_demos.mjs` step 4 holds this port's two to each other
and to the image the C tool loads, and the page's `sameCfg()` therefore
drops `engine` from the configuration comparison the way orbits.c's
checkpoint drops it - that file "carries every number that describes a
RESULT and nothing that describes the MACHINE - no batch size, no
engine, no timing". If the two ever parted, the page would say DIFFER
rather than "other config", which is the point of dropping it.

**The images are the C tools', byte for byte.** `demos_core.js` ports
`pack_program` and the instruction encoders from `host/tools/zoom.c`
and `host/tools/orbits.c` - the third copy of three, since each tool
carries its own - and a copy is only worth having if something checks
it. The check is the bytes: each image the core loads is hashed and
compared against the image the tool loads, dumped from the tool itself
by compiling `host/tools/*.c` exactly as they stand and linking them
with `-Wl,--wrap=cft_program_load` and a shim that writes the image out
before forwarding. Nothing under `host/` was edited to get them.

| image | bytes | sha256 |
|---|---|---|
| the nucleus scan, 51 iterations at fp256 (both zoom runs; the centre is derived at binary256 whatever the reference format is) | 136 | `8fad50d414aadc685faba7d64e701a0269a12ccd25d91d75bb656f454722272a` |
| the reference orbit, 1,001 iterations at fp256 | 248 | `9aaefec8adf583c63dcc70d1e7b940f596649dfd743f8b6cd574b011cfbe8ff1` |
| the reference orbit, 1,001 iterations at fp64 | 176 | `752e5489d358303d190bd3e51a491c69d016ddfe1c3547243ef6ea440ee4c8bc` |
| the Kepler integration at fp256, 49 instructions, 6 Newton passes | 552 | `adcd627af5f1e71bab5647674176967e558f3663d191a08fbc354193b454b382` |
| the Kepler integration at fp64, 37 instructions, 3 Newton passes | 360 | `d1ded7c1613b35099447d3a76a3a3b0e6fed139238d2fd324a2e18fa2511664f` |

A program is an artefact: the host DMAs it to the tile and can read it
back, so what executed can be attested rather than assumed. "The same
answer" is therefore not the whole claim, and these five lines are the
rest of it.

**The orbits panel needed a second pair of runs to say anything at
all.** `cft-orbits` refuses `--engine program` with `--rsqrt exact`,
and refuses it for a reason that is a fact about the program model
rather than about the tool: the correctly rounded 1/r^3 route is
`cft_sqrt` and `cft_div`, which are themselves programs, partitioned
host-prep / program-core / host-finish, and cannot sit inside another
program's loop body. So the recorded `fp256`/`fp64` pair stays the
correctly rounded route and stays loop-only, and a `fp256-newton` /
`fp64-newton` pair was recorded beside it: the same integration with
the tile's own `rsqrt` seed and a derived number of Newton refinements,
which is the route a program can hold. It is **different arithmetic**
and has its own chains; it is not a second spelling of the first pair.

`bindings/wasm/demos_core.js` is a **plain script**: no import, no
export, no module scope. The page splices it into a Blob its Worker
runs; `verify_demos.mjs` loads the same bytes with
`vm.runInThisContext`. One file, one set of bits, two drivers - which
is what makes "the browser computed the same records" checkable without
a browser.

| panel | the operation sequence | the batch shape |
|---|---|---|
| collatz | `engine_pass()`: 23 elementwise passes - a live mask, `n*0.5`, the parity read out of the encoding with ISHR/ISUB/ISHR/IAND/ICMPLT, the `n < 2^p` guard, two FMAs whose residual `3n+1-3n == 1` is the exactness witness, and the commits | one call per opcode over the whole live batch; 1 lane for the trajectory, 1,000 for the sweep |
| zoom | `scan_eval()`'s 5 opcodes x 51 iterations for the nucleus; `orbit_pass()`'s 8 (MUL, MUL, ADD, CMPLE, ADD, SUB, FMA, ADD) at fp256; `pixel_chunk()`'s 23 at fp64 | scan 320 candidates then 1 per bisection step; the orbit is scalar by nature; pixels 1,024 per call, in 16 chunks of 8 rows |
| orbits | `drift`, `kick_kepler`, `drift` - 2 FMA, MUL, FMA, `cft_sqrt`, MUL, `cft_div`, 2 FMA, 2 FMA per step; `invariants()`'s 11 per sample | one call per operation over all 8 members, exactly as `opN`/`sqrtN`/`divN` issue them |
| enclose | `series_pass()`'s 6 (MUL/DIV under RDN, MUL/DIV under RUP, two ADDs); `dot_batch()`'s two `CFT_DOT` reductions per item under RDN and RUP; `horner_batch()`'s CMPLE plus 4 per degree (two SELECTs, an RDN FMA and an RUP FMA) | the whole kernel batch per call - 17, 15 and 17 items |
| mersenne | `ll_step()`: `2L-1` `CFT_DOT` reductions, the `-2`, one carry pass, the `2^d` fold, carry to convergence, reduce below `2^P`, the integrality gate; the carry split is the loop route's 15 `cft_run` passes | `L` or `2L` limbs per call - 5 to 20 at these exponents |

### The zoom and orbits panels' program engines

Both are ports of their tool's `--engine program` path, and both build
their image with `demos_core.js`'s own `packProgram` / `seqAlu` /
`seqCtl` - a port of the three helpers `zoom.c` and `orbits.c` each
carry. The images are compared byte for byte against the tools' own
(the table above).

| panel | the program | trip counts | deposits a lane |
|---|---|---|---|
| zoom, the nucleus scan | 9 instructions, 1 constant: `z <- z^2 + c`, with `SETACT` on `|z^2| <= 4` so a candidate that leaves the disc stops, then `ACTALL` and one `DEPOSIT` | the period, 51 | 1 |
| zoom, the reference orbit | 15 instructions, 3 constants (4, `c_re`, `c_im`): the same eight ALU issues an iteration the host loop makes, the escape test **before** the step, and the two `DEPOSIT`s that ARE the orbit | `--steps-per-call`, 1,024, so 1,001 here in one call | `2 * trip` |
| orbits, the whole integration | 49 instructions at fp256 and 37 at fp64, 4 constants: two nested `REPEAT`s - samples outside, `--sample-every` steps inside - with four `DEPOSIT`s at the top and four at the end of each sample | the whole run, `nsamples * stride` | `(nsamples + 1) * 4` = 260 |

Three things follow from the model rather than from these ports, and
each is a line in docs/SEQUENCER.md's "What the workloads asked":

- **The orbits program is one call and cannot resume.** A program can
  be entered only at a state with at most three non-zero components,
  because `cft_program_run` initialises `r0`, `r1` and `r2` and the
  rest start at `+0`. Step 0 of a planar Kepler orbit is such a state
  and no later step is.
- **260 deposit slots a lane is a software-backend number.** A tile
  holds 64 (`MAXD`, `rtl/cft_krnl.sv`), which is 15 samples; the page
  is the software backend, which holds 2^20, and the core refuses at
  that cap with the tile's number named so it is not a surprise later.
- **The pixel phase is untouched.** It runs through `cft_run` in the C
  tool too. The sequencer does not reach it, which is why the zoom
  panel's nineteen seconds are nineteen seconds either way.

### The two departures from the C's call shape, and why neither changes a bit

**Elements are batched.** Where a tool issues one library call per
element, the port issues one call per batch. `cft_run` is elementwise
by contract, so `n` elements in one call and `n` calls of one element
produce the same `n` results - which is exactly why the tools' own
checkpoints are batch-size independent and why each tool's gate runs
the same configuration at two batch sizes and compares bytes. It is
also the only way a browser can run these at all: one `_malloc` per
scalar call is the wasm boundary's known trap, so every buffer is
allocated once per job and reused, and the arena is freed when the job
ends.

**zoom's per-iteration reference scalars are hoisted.** `pixel_chunk()`
computes seven scalars inside its `k`-loop - `2*Zr`, `2*Zi`, `-2*Zi`,
`|Z_{k+1}|^2` and the glitch threshold - and every one of them depends
on the reference alone, not on any pixel. The port computes all of them
as seven **batched passes over the whole reference** before the pixel
loop starts. Element `k` of the batched pass and the C's `k`-th scalar
call are the same operation on the same operands; what it saves is
`7 * maxk * chunks` = 112,000 wasm crossings. The pixel chain is
unchanged, which is the check that matters.

### Presentation is fenced off from the arithmetic

Anything computed for the screen rather than for a record goes through
`C.present()`, which saves and restores the 754-2019 7.1 status word
(5.7.4's `saveAllFlags`/`restoreFlags`) **and** the call counters. A
rounded decimal raises inexact; a conversion to binary64 for a plot
axis raises inexact; neither belongs in a flag union that is supposed
to describe the integration, and neither should inflate a rate.
`enclose.c`'s own `val_to_dec` does the first half of this for the same
reason. With the counters fenced too, the orbits panel reports the
tool's own 23,627 library calls exactly.

**Call counts are not comparable across the two sides in general**, and
the page does not print one. Each tool counts a different thing:
`cft-collatz` counts engine *passes* (2,437 for the trajectory, where
the port issues 58,489 `cft_run` calls); `cft-enclose` counts only
`runN`/`divN`/`dot_reduce` and not the `run1` behind its comparisons
and constants; `cft-mersenne` counts 1,232,076 where the port counts
1,232,293, the 217 being per-exponent engine setup and the `res64`
read-back that the tool's counter excludes. The rates below are wall
clock over work done, which is comparable.

### Constants are derived, not transcribed

SHA-256's `K` and `H0` are the fractional parts of the cube and square
roots of the first 64 primes, and the port computes them over BigInt
exactly as the C tools compute them over a 128-bit integer - rather
than carrying 72 hand-typed words that nothing would check. So is the
`--cond-max` above; so is the Collatz default `2^237 - 1315`; so is
every format's `p`, which is measured by asking the library for the
smallest `k` where `2^k + 1` is inexact. The opcode, format, rounding
and flag numbers are checked against the module at open time -
`cftw_op_name`, `cftw_format_name`, `cftw_flags_all` - because a
mistranscribed opcode field computes a different operation and reports
nothing.

---

## The rates

Both sides are the software backend on the same Windows desktop
(DESKTOP-T33SK86), single-threaded, 2026-09-04. **These are
measurements of a slow software tier, not a performance claim** - the
sentence `docs/BENCHMARKS.md` makes about every number in it, and the
page prints it under every panel.

The machine was not quiet: other work was running on it throughout, and
repeating the browser column moved individual cells by up to 40% on the
short runs (`enclose`, whose whole run is 20-50 ms, and the Collatz
sweep) while the long ones - zoom, Mersenne - held to a few percent.
Read the ratios and the orders, not the third digit, exactly as
`docs/BENCHMARKS.md` asks of its own tables.

| panel / run | work | native, `--engine loop` | node (wasm) | Chromium (wasm, Web Worker) |
|---|---|---|---|---|
| collatz / trajectory | 2,437 Collatz steps | 239,666 /s | 42,754 /s | 58,865 /s |
| collatz / sweep | 59,542 Collatz steps | 221,294 /s | 149,228 /s | 173,491 /s |
| zoom / fp256-reference | 6,342,288 fp64 pixel-iterations | 346,414 /s | 269,380 /s | 343,381 /s |
| zoom / fp64-reference | 1,835,008 fp64 pixel-iterations | 383,738 /s | 251,440 /s | 297,215 /s |
| orbits / fp256 | 16,384 element-steps | 24,922 /s | 17,210 /s | 22,645 /s |
| orbits / fp64 | 16,384 element-steps | 55,589 /s | 47,216 /s | 50,945 /s |
| enclose / fp32 | 49 enclosures | 6,942 /s | 3,267 /s | 2,917 /s |
| enclose / fp64 | 49 enclosures | 6,773 /s | 4,083 /s | 4,083 /s |
| enclose / fp128 | 49 enclosures | 3,881 /s | 2,882 /s | 2,475 /s |
| enclose / fp256 | 49 enclosures | 1,526 /s | 980 /s | 1,247 /s |
| mersenne / to-2281 | 2,425,336 limb products | 646,661 /s | 403,953 /s | 473,911 /s |

**Reading them:** wasm runs these between 0.8x and 1.4x of native on
the batched workloads, and the browser is consistently a little faster
than node on the same module - V8's tiering on a hot loop of wasm calls
is the whole difference, and neither number is about the arithmetic,
which is identical.

The two outliers are both call-shape, not arithmetic. `collatz /
trajectory` is one lane: 23 wasm crossings per Collatz step over a
single element, so the boundary is 100% of the cost and native wins
5.6x. `enclose` is 49 items in a few hundred calls, of which the first
few are format measurement - the run is over before anything warms up,
which is why the four enclose rows wobble by 40% between runs. The
zoom, orbits and Mersenne rows, where a call carries between 8 and
1,024 elements, are the ones worth reading.

---

## How the page is built

    bash bindings/wasm/build_demos.sh

Everything happens inside the emscripten image `build.sh` pins, and the
pin is **read out of `build.sh`** rather than typed again - two
spellings of one version is how they disagree. The only requirement is
Docker; no host compiler, no host emsdk, no host Python.

    stage 0   refuse an emcc that is not the pinned version
    stage 1   emcc the library sources - asked of host/Makefile, and
              cross-checked against host/src/*.c - plus wasm_api.c,
              twice: split (.js + .wasm) and -sSINGLE_FILE
    stage 2   the split .wasm must equal bindings/node/cft_node.wasm
              byte for byte, or the build stops
    stage 3   make_demos.py splices the loader, the compute core, the
              driver and demos_chains.json into demos.html
    stage 4   the same assembly with --corrupt, into
              build/demos_negative_control.html (untracked)

**This build does not produce a new module.** `bindings/node/cft_node.wasm`
is a committed build product whose sha256 the conformance page and
three documents quote; stage 1 recompiles it only so that the
SINGLE_FILE loader exists, and stages 2 and 3 refuse to ship a page
whose bytes are not identical to it. The one emcc flag that differs
from `build.sh` is `-sENVIRONMENT=web,worker` instead of
`-sENVIRONMENT=web`, because this page computes in a Worker;
`ENVIRONMENT` selects branches of the JavaScript loader and nothing
else, which stage 2 does not assume - it checks.

The module identity is checked three times over one fact: against the
split `.wasm` from the same emcc run, against the committed module, and
by walking the bytes back out of the assembled HTML. Three checks of
one fact is not paranoia when the fact is the whole argument.

**Two clean container builds, byte-identical:** 523,351 bytes, sha256
`2b75d080fafd8d2a887b0bdd18d5a5befb80e3467067d7b25ccc6487bfade5df`,
with `bindings/wasm/build/` removed between them (2026-09-07; the
2026-09-04 page was 486,822 bytes, sha256 `e3711319627e6828...`, built
the same way). Those are that day's bytes. The page has been rebuilt
with the module since - the committed one is 539,646 bytes, sha256
`b78d6a6dd57e7411...`, at ABI 0.11 - so read the pair above as the
2026-09-07 measurement and the table at the top of this file as what
is in the tree.

### Where the compute runs

The page builds one Blob from (emcc loader + compute core + driver) and
starts a **Web Worker** from it, so the tab stays responsive: progress
is posted in batches roughly ten times a second, Cancel is honoured
between batches, and a 19-second zoom draws itself as it goes.

A page opened from `file://` in a browser that refuses `blob:` workers
falls back to running **the same source on the main thread**,
cooperatively yielded, and the identity block says which of the two it
used and why. There are three ways to arrive at the fallback and only
one of them is the synchronous throw Chrome gives from a `file://`
document: the page also falls back when the Worker reports an error
before it is ready, and when it never becomes ready within five
seconds. A demo that silently did nothing would be worse than a slow
one, and a Worker that neither throws nor loads is exactly how a page
looks alive and computes nothing.
The fallback was exercised directly - `CftDemosDriver.handle()` driven
from the page's own scope, enclose/fp256, chain
`93cdda3270eaa7ba434ddbbabcc54d77a5afa28779e05bccef4f7b81cc43400c`,
identical.

The page makes **no network request at runtime**. Loading it costs one
GET for the file and one for the Worker's `blob:` URL; nothing else
appears in the network log.

---

## How it is verified

    node bindings/wasm/verify_demos.mjs

Four checks, in order:

1. **The module.** The bytes embedded in `demos.html` are walked back
   out of emcc's SINGLE_FILE string literal - one byte per code unit,
   walked rather than evaluated, because a build product is data - and
   hashed. They must equal `bindings/node/cft_node.wasm`.
2. **The compute core.** The core spliced into the page must be
   `demos_core.js` byte for byte, so that the report is about the page
   and not about a lookalike.
3. **The chains, three ways.** For each of the thirteen
   configurations: run the native tool with the flags the page prints,
   run the compute core over the committed module, and compare both
   against `demos_chains.json`. All three must agree.
4. **The sequencer program engine.** For each configuration that can
   run one - the two zoom frames and the two newton orbits runs - the
   core is run again with `engine: "program"`, and two things must
   hold: the chains must equal the loop engine's, and every program
   image the core loads must equal the image the C tool loads, byte for
   byte and by sha256. The first says the two engines are one
   configuration; the second says they are one program.

Flags: `--record` re-records the file (and needs the tools);
`--no-native` drops the tool run and compares against the recording;
`--panel X` / `--run Y` restrict it.

The five tools have to be built first - the checker does not build them,
because a checker that silently rebuilds its own reference is a checker
that can hide a stale one. On this Windows host, with mingw64 gcc on
PATH:

    make -C host CC=gcc OS=Windows_NT TMP=/tmp TEMP=/tmp \
         cft-collatz.exe cft-zoom.exe cft-orbits.exe \
         cft-enclose.exe cft-mersenne.exe

Elsewhere, `make -C host cft-collatz cft-zoom cft-orbits cft-enclose
cft-mersenne`.

### In a real browser

Served over loopback and driven in Chromium: every panel run, every
chain reproduced, `15 of 15 chains computed in this browser, every one
identical to the C tool's` - with the zoom and orbits panels on the
**sequencer program engine** (2026-09-07; the 2026-09-04 run was 13 of
13 on the host-loop engine, over the eleven configurations that
existed then). No console message of any level was logged during
either. The PNGs below are the 2026-09-04 run's, and the panels draw
the same pictures either way, because the engines produce the same
bits:

| | |
|---|---|
| `docs/img/demos/zoom.png` | the two frames side by side, and the 1.87668e+31-pixel centre error |
| `docs/img/demos/orbits.png` | the ellipse, the two drifts, and the ensemble separating |
| `docs/img/demos/collatz.png` | the 72-digit trajectory against the `2^237` edge, and the sweep's scatter |
| `docs/img/demos/enclose.png` | the ladder at four formats, and the straddle table |
| `docs/img/demos/mersenne.png` | the residue chain, seven exponents, two of them composite |
| `docs/img/demos/negative-control.png` | the sabotaged build reporting DIFFER |

### The negative control

A checker that has never been seen to fail proves nothing, so there are
two of them and they use the same sabotage: **the Collatz panel's
running peak computed with `CFT_MIN` instead of `CFT_MAX`.** That site
is chosen deliberately. The peak is in the record line and therefore in
the chain, but nothing else notices it: the flag/witness agreement
still holds, the step count is right, the final value is right, and the
run reports success. It is exactly the failure a chain comparison is
for.

**In the page.** `bash bindings/wasm/build_demos.sh` writes
`bindings/wasm/build/demos_negative_control.html` (untracked) with a
red banner naming the sabotage. Running its Collatz panel:

    2 of 2 computed chains DIFFER from the native tools.
    The page is wrong until shown otherwise.

    trajectory  chain  b13572843b19a7ef...  0ac473c7114abe77...  DIFFER
    sweep       chain  c2ccab682e374726...  0eb2fc42554fbfeb...  DIFFER

**In the checker.** The same edit made to `demos_core.js` and
`node bindings/wasm/verify_demos.mjs --panel collatz`:

    FAIL  chain: core 0ac473c7... != tool b13572843b...
    FAIL  chain: core 0ac473c7... != recorded b13572843b...
    FAIL  chain: core 0eb2fc42... != tool c2ccab682e...
    FAIL  chain: core 0eb2fc42... != recorded c2ccab682e...
    VERDICT: FAILED

`git checkout -- bindings/wasm/demos_core.js`, run it again, and both
chains are green. Note that the checker failed **twice per chain** -
against the tool it just ran and against the recording - which is the
point of keeping both.

---

## The deploy

`.github/workflows/pages.yml` stages both pages. `conformance.html`
goes up twice, as `index.html` at the site root and under its own name,
because `demos.html` links to it by that name and a relative link that
works from a checkout should work on the site too. `demos.html` goes to
`_site/demos.html`, and `bindings/wasm/demos.html` is in the trigger
paths. Nothing is built in CI: both pages are committed build products,
byte-reproducible from the pinned container, and the workflow serves
the files the repo already vouches for.

    https://loganw234.github.io/cft-fp256/            conformance
    https://loganw234.github.io/cft-fp256/demos.html  these five

---

## What the sequencer's program API bought, measured

Until 2026-09-07 this section was called *what it would have bought*,
and its table was the C tools' gap, because the wasm module exported
none of the four program calls and the browser gap could not be
measured at all. It can now, and the prediction it made - that the gain
in wasm should be LARGER than the gain in C, because what a program
removes is call boundaries and a wasm boundary costs more than a C one
- is the thing the numbers below confirm.

**Both engines return the same chain in every row**, which is what
makes this a comparison rather than two different computations timed
side by side.

Median of fifteen runs each, alternating engine run by run, through the
compute core on `bindings/node/cft_node.wasm` under node 22 on the same
Windows desktop. **The machine was not quiet** - it was running several
other jobs throughout, and the spread is wide because of it (the
per-run times are in the log). Alternating the engines is what makes
the ratio survive that: both halves of each pair met the same load.

| what | program | host loop | program removes | library calls |
|---|---|---|---|---|
| zoom, the 1,001-iteration reference orbit at fp256 | 0.0259 s | 0.0405 s | **1.56x** | 12 against 8,019 |
| zoom, the reference orbit at fp64 | 0.0111 s | 0.0167 s | **1.51x** | 12 against 8,019 |
| zoom, the nucleus scan and bisection (one lane a call) at fp256 | 0.0497 s | 0.0760 s | **1.53x** | not counted - the panel lowers its counters once the centre is derived |
| orbits, the whole Kepler integration at fp256, `--rsqrt newton` | 0.8655 s | 1.1402 s | **1.32x** | 1,100 against 74,827 |
| orbits, the same at fp64 | 0.2870 s | 0.3936 s | **1.37x** | 1,100 against 50,251 |

Read against the C tools' own gap for the same work, measured on
2026-09-04: 1.40x for the reference orbit and 1.26x for the Kepler
integration. Every row here is above its C counterpart, which is the
prediction holding.

Three things the table does not say on its own:

- **The zoom rows are the part the sequencer touches, not the panel.**
  The reference orbit is 1,001 iterations of nine instructions on one
  lane; the nucleus scan is 320 candidates in one call and then about
  two hundred bisection steps of one lane each. Together they are under
  a tenth of a second. The panel's other nineteen seconds are its pixel
  phase, which runs through `cft_run` in the C tool too, so **the zoom
  panel as a whole is no faster** and the page's report line says so.
- **The call counts are the mechanism.** 8,019 `cft_run` crossings
  become 12 for the reference orbit, and 74,827 become 1,100 for the
  Kepler integration - the 1,100 being the per-sample invariants, which
  are host work in the C tool too. What is left is not the arithmetic;
  it is the boundary.
- **The orbits row is `--rsqrt newton` on both sides.** The correctly
  rounded route is not a program and cannot be one, so `--rsqrt exact`
  has no program engine to compare against; for the configuration the
  panel's *argument* runs, the program API still buys nothing. That is
  not a disappointment, it is the last of docs/SEQUENCER.md's recorded
  asks - a callable composed operation - with a number beside it.

One smaller note, not a request, and unchanged: what would help the
zoom panel is not on the sequencer's side at all. The pixel batch
broadcasts six scalars across 1,024 elements every iteration with a
JavaScript fill loop - 6,144 stores per iteration, outside the library,
measurably more than the wasm call they accompany. A `cft_run` that
accepted a scalar (stride-0) operand would remove them. `dfill` in
`pixel_chunk` is the same loop in C, so this is a shape the contract
has, not a JavaScript problem.

## What was not done

- **No tool was edited.** `host/tools/` is untouched; every browser
  configuration is expressible in the flags the tools already have -
  including the two the program engine needed, `--engine program` and
  `--rsqrt newton`, which `cft-orbits` and `cft-zoom` have carried
  since the day they were written. The images dumped for the
  byte-for-byte comparison came from compiling those same sources
  unchanged and interposing on `cft_program_load` at link time.
- **No device.** The panels run the software backend, which is the
  only backend a browser can be (`wasm_api.c` says why). Nothing here
  is a hardware number.
- **The `known` and `device` Mersenne sets are offered, not run.**
  3217..11213 is minutes in a browser and 19937..44497 is hours;
  neither has a recorded chain, and the page says so when either is
  selected.
