# GPU-F: WebGPU - libcft's arithmetic in a browser's GPU, and run data from browsers

Study GPU-F, written 2026-11-13 by a study author (Opus 5.5) at Logan's word, the seventh
of the GPU series. Branch `gpu-f` from `0aa997a3`. Its prototype is in `studies/gpu-f/`, as
files only. Nothing outside `studies/` and the index changed.

> "As a study, dispatch an agent to look into webgpu approaches which might be possible
> here. It could provide a public and easily accessible way to collect independent run
> data from just a browser." (Logan)

**This is a paper study.** Nothing ran on a GPU, no browser tab was opened, no WebGPU
runtime was started, nothing was installed or downloaded, and the web was read only, each
page named with its URL. The prototype has never been opened in a browser and its WGSL
never compiled. Nothing was collected, and no endpoint, form or page was created.

Every figure is marked: **READ** (a page or a file, named), **COUNTED** (in a named
source), **COMPUTED** (arithmetic on the others, inputs given), **ESTIMATE** (a judgment,
its basis given) or **BELIEVED** (taken on trust, not checked). Nothing here is MEASURED:
no device was used. "Not run" means not run.

## The answer

1. **Worth building as an instrument, not as a backend.** A public page that runs libcft's
   integer arithmetic on a visitor's GPU through WebGPU, and names every lane that differs
   from the page's own WebAssembly module, would gather what none of our machines can: how
   browsers' WGSL compilers and the drivers under them treat this integer code on GPUs we
   do not own. GPU-D's Apple fault (refusals at default options, wrong values in a scratch
   variant, right results with optimisation off, the cause not pinned) is the kind it
   would catch.
2. **Route.** WGSL has no 64-bit integer. The two compile roads read (clspv, then Tint or
   naga) stop at libcft's 64-bit intermediates (READ; not run). The order: first this
   study's probe; then a go/no-go of clspv and Tint on GPU-D's OpenCL C text with the
   64-bit lines rewritten by counted edits, which keeps one source; a hand port of the FMA
   path, a second implementation, only if that fails.
3. **Held** in the page itself by three gates: the conformance vectors' FMA cases; a
   counter-generated stream against the page's WebAssembly module, the reference of
   record; and planted faults that must be seen before any PASS.
4. **Data.** The page sends nothing. It shows a short record (digests, counts, each
   mismatch with its case, the adapter's vendor and architecture as reported) that a
   visitor may paste into a GitHub issue form. A mismatch can be rechecked by anyone; a
   PASS is only a claim.
5. **Smallest first step.** The lead or Logan opens `studies/gpu-f/bn_probe.html` once in
   this desktop's Chrome and files its record (about 10 minutes, ESTIMATE). It answers the
   question every route shares: does WGSL on a real browser give exact u32 limb
   arithmetic, and are the four plants seen?

## 1. WGSL against libcft's needs

**Sources** (READ, 2026-11-13):
- WGSL, W3C Candidate Recommendation Draft of 6 November 2026, <https://www.w3.org/TR/WGSL/>.
  Its returned text ends in §12.4, so the built-ins and the address-space table are READ
  from the editor's draft source, <https://raw.githubusercontent.com/gpuweb/gpuweb/main/wgsl/index.bs>.
- WebGPU, W3C Candidate Recommendation Draft of 15 September 2026,
  <https://www.w3.org/TR/webgpu/>. Its returned text ends in §10, so device loss and the
  Feature Index are READ from <https://raw.githubusercontent.com/gpuweb/gpuweb/main/spec/index.bs>.
- libcft: `host/src` at `0aa997a3`.

**1. Integer types.** *libcft* (COUNTED, `grep -c uint64_t`): 32-bit limbs with 64-bit
intermediates. The three files the GPU backend compiles as device code (READ,
docs/HOSTAPI.md, "The GPU backend") hold `uint64_t` on 18 lines (10 in bigint.c, 6 in
softfloat.c, 2 in seq_exec.h) and `int64_t` on none. An FMA exercises bigint.c's 10 alone
(in extract, add, sub and mul: lines 95-230); softfloat.c's 6 are IMUL (:641) and the
reciprocal-square-root seed (:685-691), which a kernel entered through cft_sf_compute, as
GPU-A's and GPU-D's are, compiles too.
*WGSL:* i32 and u32 at run time, wrapping modulo 2^32 (§6.2.3). AbstractInt is 64-bit but
exists only while a shader is created. None of the extensions §3.8.5 names gives a 64-bit
integer; the one 64-bit feature is atomic minimum and maximum on `atomic<vec2<u32>>`
(§6.2.8), which WebGPU's Feature Index lists as atomic-vec2u-min-max, its only 64-bit
item. gpuweb's proposals directory lists no other 64-bit proposal beside
atomic-64-min-max.md (READ, <https://github.com/gpuweb/gpuweb/tree/main/proposals>, a
listing GitHub says may be incomplete). wgpu's `SHADER_INT64` is native only (READ,
docs.rs, wgpu-types 30.0.2).
**Cost:** each of those lines becomes a u32 pair, or a carry found by comparison.

**2. A 32x32 to 64 product, or a multiply-high.** *libcft:* bigint.c's schoolbook step
`t + ai*bj + carry` in 64 bits (:230) and extract's 64-bit funnel (:102).
*WGSL:* no built-in read returns a high half or a wide product, and none adds with carry.
The numeric built-ins on integers are abs, clamp, countLeadingZeros, countOneBits,
countTrailingZeros, dot, dot4I8Packed, dot4U8Packed, extractBits, firstLeadingBit,
firstTrailingBit, insertBits, max, min, reverseBits, sign and bitcast; the pack, atomic and
subgroup built-ins add none (READ, the editor's draft, all but its last 28,791 characters,
where the subgroup functions end; the rest BELIEVED to be the grammar).
**Cost:** the product by 16-bit halves is 22 operations, 4 of them multiplies, and the
schoolbook step 30 (COUNTED, the prototype's `mul_wide` and `bn_mul`), where a GPU does the
step in about 3 instructions (BELIEVED: both vendors' ISAs have a 32x32+64 multiply-add).
fp256's 8x8-limb product then adds 27 x 64 = 1,728 operations an FMA. The add and the
subtract over the 38-limb window (1,188 bits, READ from bigint.h) add about 4 a limb each
(7 COUNTED in the prototype's `bn_add` against about 3, BELIEVED), 304 more. That is about
2,000 (COMPUTED), 5.3 % of the 38,000 issue slots GPU-A computed as available per generic
FMA on the 5060 Ti with every lane on one case (READ, GPU-A §8): the 64-bit emulation
would not set a generic port's speed (ESTIMATE).

**3. Shifts at or past the width.** *libcft:* every shift in bigint.c is guarded against a
count of 32 or more, and UBSan ran clean on 4,073,780 cases (READ, GPU-A §2 and §5).
*WGSL:* at run time the count is taken modulo the width, so `x >> 32u` is `x`; a
const-expression count at or past the width is a shader-creation error; `>>` is arithmetic
on i32 and logical on u32 (§8.10).
**Cost:** none while the guards stay. A port that drops one computes a wrong value, not
undefined behaviour: the prototype's plant 2 is exactly that slip.

**4. Division and remainder.** *libcft* (READ): the FMA path divides nothing.
seed_recip_entry divides in u32 (softfloat.c:673); seed_rsqrt_entry works in 64 bits
throughout (:685-698), dividing 2^44 by a divisor below 2^12 (COMPUTED from :685) and then
squaring and comparing; two small divisions sit at :784 and :1037.
*WGSL* (§8.8): division by zero gives the dividend and remainder by zero gives 0; i32's
most negative value divided by -1 gives itself, remainder 0; each is a shader-creation
error when the operands are const-expressions.
**Cost:** the u32 divisions port as they stand; the 64-bit one needs a short long division
or a table, for RECIP_SEED and RSQRT_SEED only.

**5. Private and workgroup memory, and arrays in function scope.** *libcft:* a cft_bn is
260 B at 64 limbs (COMPUTED: 4 + 64 x 4). The FMA path declares 17 (COUNTED: the lane's 4,
cft_sf_compute's 3, sf_fma's 8 with the three in its sf_unp operands, sf_round_pack's 2):
4,468 B with sf_unp's integers, 2,700 B at 38 limbs (COMPUTED), each within 4 B of GPU-A's
frames of 4,472 and 2,704 B (READ, GPU-A §5 and §7). The sequencer's 32 registers take
8,320 B (COMPUTED).
*WGSL:* the function, private and workgroup address spaces are read-write, and fixed-size
arrays are allowed in function scope. §2.4's minimum limits: 8,192 B of
function-address-space variables in one function, 8,192 B of private variables and 16,384
B of workgroup variables in a shader. An implementation may support more, and should
report an error past what it supports.
**Cost:** the FMA path fits even if one function declared every local. The sequencer's
registers do not at 64 limbs (8,320 > 8,192): a storage buffer, or 4,992 B at 38 limbs
(COMPUTED).

**6. Pointers and aliasing** (not in the brief's list; it costs edits). *libcft* (READ):
functions take pointers to cft_bn, and r may alias a or b (bigint.c's head); sf_round_pack
calls `cft_bn_shr(&kept, &kept, 1)` (softfloat.c:253); a pointer is chosen by a condition
at sf_fma's `bm` (:386-392) and in five `cft_bn_copy(out, c ? x : y)` (:535, :550, :557,
:559, :978).
*WGSL:* without the language extension unrestricted_pointer_parameters a pointer parameter
points into function or private space (§4.1.2, §11.4), and at a whole variable (BELIEVED:
the same table row names that rule, as read); two pointer arguments with one root
identifier, either written, are a shader-creation error (§11.4.1.2); a pointer cannot sit
in an array or a structure (§6.2.10), though a `let` may hold one (§6.2.1's example).
There is no `select` or comparison of pointers (BELIEVED: both are defined on scalars and
vectors in the sections read).
**Cost:** a temporary at the aliased call, and the six pointer choices as copies or
branches.

**7. Recursion and loops.** *libcft:* cft_sf_reduce recurses (softfloat.c:880-937); every
other loop read runs over at most CFT_BN_LIMBS limbs or 32 bits (BELIEVED for the
functions not read).
*WGSL:* recursion is disallowed, since no cycles are permitted among declarations (§11.4).
Loops are allowed; one that would run without bound is a dynamic error, which may end in
device loss (§9.4).
**Cost:** the reduction tree comes out, as GPU-D's edit O4 takes it out of the OpenCL
text, or runs one level a launch, as the HIP backend runs it (READ, docs/HOSTAPI.md, "The
GPU backend").

**8. Shader size and compile time.** *WGSL and WebGPU:* no shader-size limit beyond §2.4's
was found in either text as read. The browser translates WGSL into the platform's own
language and the driver compiles it again; Chrome compiles through DXC on Direct3D 12
hardware with shader model 6 since Chrome 121 (READ, a search summary of
developer.chrome.com's "New in WebGPU 121"; the page itself was not fetched).
**Cost** (ESTIMATE): 1 to 10 s cold for an FMA-path kernel of 1,200 to 2,500 WGSL lines.
Basis: GPU-D's 94,634-byte OpenCL C text built in 0.16 to 2.2 s cold on four runtimes
(READ, GPU-D's ledger and its Arc note), and a browser adds one translation.
`createComputePipelineAsync` keeps the page responsive meanwhile.

**9. Storage-buffer binding and dispatch limits.** *WebGPU defaults* (§3.6.2):
maxStorageBufferBindingSize 134,217,728 B; maxBufferSize 268,435,456 B;
maxComputeWorkgroupStorageSize 16,384 B; maxComputeInvocationsPerWorkgroup 256 (128 in
compatibility mode); maxComputeWorkgroupSizeX and Y 256 (128), Z 64;
maxComputeWorkgroupsPerDimension 65,535.
**Cost** (COMPUTED): an fp256 lane is 100 B in (three operands and an attribute word) and
36 B out, so one binding holds 1,342,177 lanes and 2^20 lanes take 104,857,600 B; at 64
invocations a workgroup, one dimension holds 4,194,240 lanes. A page that asks for nothing
above the defaults needs no adapter-specific limit, and reveals none.

**10. A long dispatch.** *WebGPU:* a user agent may set a watchdog so that a page cannot
stall the GPU for more than a few seconds (§2.1.9). A device may be lost when shader
execution does not end in a reasonable time, and its GPUDeviceLostInfo carries `reason`
("unknown" or "destroyed") and `message` (READ, the editor's draft, Fatal Errors). An
out-of-bounds read may return another in-bounds value or zeros, and an out-of-bounds write
may be discarded (§2.1.4), so a port's index slip gives a wrong value, not a crash;
implementations meet this by clamping indices (BELIEVED), a cost on every dynamic index
into a limb array.
*Windows:* TdrDelay is 2 s by default, and more than TdrLimitCount (5) resets within
TdrLimitTime (60 s) bug-check the machine (READ,
<https://learn.microsoft.com/en-us/windows-hardware/drivers/display/tdr-registry-keys>).
**Cost:** dispatches far below 2 s, sized by measurement; a lost device ends the run with
its reason and is never retried by the page. A retry loop on a faulting kernel is how a
visitor's Windows machine would pass five resets in a minute.

**What item 1 settles.** Every need has a WGSL form, so none of these blocks a port. Two
are costly (the 64-bit intermediates; the aliasing and its pointer choices), one forces an
edit (recursion), one needs care (shifts), and one bounds the page (dispatch time). All of
them stand against one source: no road read here takes libcft's C to WGSL as it is.

## 2. The routes to WGSL

**Any route needs three gates** (section 3 places them in the page): **G1**, the
conformance vectors' FMA cases; **G2**, a counter-generated stream against the page's
WebAssembly module; **G3**, plants. A second implementation also needs **G4**, a gate that
sees drift when `host/src` changes.

| route | one source? | exists (READ) | would be built (ESTIMATE) |
|---|---|---|---|
| (a) hand port | no, a second implementation | nothing for libcft; this study's probe, bigint.c's core in a 254-line kernel (COUNTED) | 1,200 to 1,800 WGSL lines for the FMA path at every format; 3 to 6 days with G1-G4 |
| (b) C to SPIR-V to WGSL | yes, with counted edits | clspv, Tint, naga; one browser demonstration, 32-bit only | 25 to 40 counted edits; clspv and Tint pinned; a go/no-go in 1 to 2 days |
| (c) a generator | from the golden model no; from the C yes | nothing | a C-subset-to-WGSL translator, 1,000 to 2,000 lines of Python |
| (d1) host/src 32-bit only | yes | the CFT_HD precedent | two primitives in bigint.h, about a day in a backend round |

**(a) A hand port.** libcft's code is ported nowhere yet; this study's prototype ports
bigint.c's core (add, sub, mul, shl, shr, cmp, and ISUB from them). It is a second
implementation, the status of GPU-A's `fma256_fixed.h`, and every change to bigint.c or
softfloat.c must be ported again by hand. *Size* (ESTIMATE): bigint.c (319 lines) and
softfloat.c's FMA path (unpack, the special cases, sf_fma, sf_round_pack, sf_round_at, the
steering: about 500 of its 1,093 lines) with item 1's rewrites. Basis: GPU-A's second
kernel, 368 lines, was written and held to the first on 2^30 cases within that study's day
(READ, GPU-A §6); a WGSL port is three to five times that, and its first runs are in
browsers, since no WGSL tool is installed here. *Gates:* G1 to G3 in the page; G4 means
those gates in CI under a software WebGPU, and the repository's workflows are gates.yml
and pages.yml only (READ, `ls .github/workflows`): question 7.

**(b) C to SPIR-V to WGSL.** What exists (READ):
- clspv compiles OpenCL C to Vulkan SPIR-V. It uses the Int64 capability when long or
  ulong appear, documents no option that lowers them, and adds VariablePointers where it
  needs them (<https://github.com/google/clspv>, docs/OpenCLCOnVulkan.md).
- Tint's SPIR-V reader validates for Vulkan 1.1, rejects features WGSL cannot express and
  assumes no VariablePointers (Dawn's docs/tint/spirv-reader-overview.md and
  spirv-ptr-ref.md, at <https://dawn.googlesource.com/dawn/>).
- naga's SPIR-V front end takes Int64 into its IR, but VariablePointers is not in its
  capability list and strict mode refuses it
  (<https://wgpu.rs/doc/src/naga/front/spv/mod.rs.html>); a WGSL `i64` is wgpu's
  native-only extension (item 1), which no browser takes (BELIEVED: WGSL has none).
- hipscript runs HIP in a browser by HIP, chipStar, clspv and Tint to WGSL, with 32-bit
  integers only (Ben Schattinger, 2025-01-07,
  <https://494.pages.dev/blog/2025/01/07/hip-script>).

So the road exists for 32-bit code and stops at libcft's 64-bit lines: GPU-D's text maps
`uint64_t` to OpenCL C's `ulong` (READ, `studies/gpu-d/oclcopy.py`:97), so clspv would
declare Int64 and Tint refuse it (BELIEVED from the pages above; not run).

**(b')** takes the same road with counted edits in the copy, in GPU-D's discipline:
bigint.c's 10 64-bit lines through two helpers, IMUL's product as a u32 multiply (the low
half it keeps is the same), seed_rsqrt_entry in 32-bit pieces, the aliased call through a
temporary, the six pointer choices as branches, O4 kept, and a lane that reads u32 words
in place of bytes. Then clspv and Tint might accept the text: not built and not run, since neither
tool is installed here and both build from source (clspv on LLVM: BELIEVED a large build).
*One source:* yes, in GPU-D's sense, though the 64-bit edits, like O4, are not syntax only,
and two compilers stand between the text and the GPU; the gates hold the bits. *Size*
(ESTIMATE): 25 to 40 counted edits on GPU-D's `oclcopy.py` (its 19 and about 19 new:
the 10 lines, IMUL, the seed, the aliased call, the six choices); clspv and Tint pinned in a
container, as `bindings/wasm/build.sh` pins emsdk by tag and digest (READ), 1 to 2 days;
then the go/no-go: does Tint accept clspv's SPIR-V of this text? *Gates:* G1 to G3. G4 is
not needed for the arithmetic, because a change in `host/src` flows through the edits or
is refused by their counts (GPU-D §3, READ).

**(c) A generator.** *From the golden model: no.* `python/cft_golden` computes in
Python's unbounded integers, and bigint.h's head says a faithful transliteration of its
fp256 FMA would want about 790,000 bits (READ). The model holds no limb algorithm to emit,
so a generator would carry its own: a second implementation written in Python. *From the C:* C
to WGSL is not a token-level rewrite as C to OpenCL C was (GPU-D's 19 replacements):
declarations and `->`, increments inside expressions (bigint.c:246, :259), C's implicit
integer conversions, stacked case labels (31 in softfloat.c, COUNTED) and the pointer
choices all change form. A translator for this subset (a C parser and a WGSL emitter) is
1,000 to 2,000 lines of Python with its own tests (ESTIMATE): one source, but a compiler
of the project's own whose errors only the gates see. It beats (b') only if clspv or Tint
refuse.

**(d) Anything else.**
- **(d1) host/src made 32-bit only:** two primitives in bigint.h, a 32x32 to 64 product
  and an add with carry, native on C targets and by halves for WGSL in the manner of
  CFT_HD, with the 16 lines of bigint.c and softfloat.c written through them. It takes the
  64-bit edits out of (b') and simplifies (c), but it changes the reference itself.
- **(d2) Other languages with a WGSL target** (Slang; rust-gpu then naga; IREE through
  SPIR-V and Tint): each needs the arithmetic rewritten in that language, a second
  implementation. Slang's 64-bit integers on its WGSL target were not read: its 64-bit
  page has no WGSL row (READ, shader-slang's docs/64bit-type-support.md on GitHub).
- **(d3) WebGL 2** is not a route: it has no compute shaders (BELIEVED). **(d4) The CPU
  path that exists,** the published pages' WebAssembly module, stays the reference of record.

## 3. The page

**What it would run on a visitor's GPU, in order** (a design; nothing is built but the
probe of section 5):
0. Nothing, until the visitor presses Run.
1. `requestAdapter`, then `requestDevice` with the default limits only (item 9).
2. Compile: `createShaderModule`, `getCompilationInfo` (errors by line),
   `createComputePipelineAsync`. A compile failure is a named REFUSED, and a finding.
3. **Plants first** (G3), as override constants in one WGSL text with one digest, the
   prototype's mechanism: GPU-A's rmm-as-rne and drop-underflow (51 results and 1,452 flags
   there, READ GPU-A §5) and porting hazards like the prototype's. Each must make lanes
   differ, or the verdict is BLIND.
4. **The conformance vectors' FMA cases** (G1): each lane's `d || flags` against the
   vector's. A refusal, d = 0 with flags 0x80 as in GPU-A §1, counts as a difference.
5. **The differential stream** (G2): lane i of seed S from an integer counter generator,
   the same case on every machine (GPU-A §6's discipline), computed on the GPU and by the
   page's WebAssembly module in Web Workers, compared chunk by chunk. SHA-256 digests the
   build makes with native libcft can ride along as a check that the page's module is the
   published one.
6. **The verdict**, each kind named: PASS (every plant seen, no difference); FAIL (the
   counts, and each difference with its case); BLIND (a plant not seen); REFUSED (no
   adapter, a compile error, a lost device).
7. **The record** of section 4, shown and never sent.

**Sizing** (ESTIMATE, from GPU-A's rates and item 1's costs).
- *The GPU, generic port.* GPU-A's HIP rates for libcft's code at fp256 are 77.4 M FMAs a
  second on the RX 7600, 143.3 on the RTX 5060 Ti and 175.3 on the RTX 4070, kernel only
  (READ, GPU-A §8). Item 1 puts the 32-bit cost near 5 % of the issue slots; a browser's
  translation and index clamps are unknown. I take 0.3 to 0.9 of HIP's rate: 23 to 70 M a
  second on an RX 7600-class card, 43 to 129 M on a 5060 Ti (COMPUTED). The 0.3 floor is a
  judgment; integrated GPUs have no basis here, and the plan below holds for any device
  ten times slower than the low figure.
- *The reference.* libcft's C makes an fp256 FMA in about 450 ns on one core (READ, GPU-A
  §8). The Chromium-to-native ratio of DEMOS.md's two rows of fp256 work, orbits and
  enclose, is 0.82 to 0.91 (COMPUTED from its rates table, which it says was taken on a
  busy machine, enclose's short runs moving up to 40 %): about 1.8 to 2.0 M FMAs a second a
  worker, 7.3 to 8.1 M for four (COMPUTED).
- *A dispatch* starts at 2^14 lanes, doubles while one takes under 50 ms, and is capped at
  2^20 by the binding (item 9). At the RX 7600 estimate 2^20 lanes take 15 to 45 ms, 44 to
  133 times inside Windows' 2 s (READ, item 10's Microsoft page), and at a tenth of the low
  figure 0.45 s (COMPUTED).
- *A visit.* The 73,780 FMA cases of the conformance sets (READ, GPU-A §1) take 3.2 ms of
  GPU time at 23.2 M a second, and weigh 4,569,560 B packed as four values and two bytes a
  case, 6,092,748 B as base64 (COMPUTED); the light alternative is the page's existing
  sample, 4,015 cases over all opcodes (READ, `bindings/wasm/README.md`). A 2^24-lane
  stream takes 0.24 to 0.72 s of GPU time on an RX 7600-class card and 7.2 s at a tenth of
  the low figure, and four workers check it in 2.1 to 2.3 s (COMPUTED). In a minute four
  workers check 4.4 to 4.8 x 10^8 lanes (COMPUTED); a slower device sets the count instead.

**What it would not be:** a benchmark (Chrome quantizes timestamp queries at 100 µs unless
a developer flag is set: section 4), a backend, or a proof: its agreement is evidence by
test, as GPU-A's was.

## 4. Independent run data, honestly

**What a browser can say about its device** (READ):
- GPUAdapterInfo has vendor, architecture, device and description, each the empty string
  when not provided; subgroupMinSize and subgroupMaxSize; and isFallbackAdapter (WebGPU
  §3.6.2.4; <https://developer.mozilla.org/en-US/docs/Web/API/GPUAdapterInfo>, last
  changed 2025-10-20).
- The specification asks for adapter identifiers as broad as possible and lets a user
  agent withhold them (§2.2.6), forbids revealing more than 32 distinguishable
  configurations (§2.2; its features and limits in §2.2.1), and reduces the precision of
  timing queries (§2.1.7.2).
- Chrome quantizes timestamp queries at 100 µs; its WebGPU Developer Features flag lifts
  that and adds non-standard adapter fields
  (<https://developer.chrome.com/docs/web-platform/webgpu/developer-features>, 2025-06-03).
  Brave clears the adapter descriptors
  (<https://brave.com/privacy-updates/38-webgl-webgpu-fingerprinting-protections>,
  2026-08-13).
- Reach: Chrome and Edge from 113 on Windows, macOS and ChromeOS; Android from 121; Firefox
  141 on Windows and 145 on macOS Tahoe (ARM64); Safari 26; Linux in progress at the time
  (<https://web.dev/blog/webgpu-supported-major-browsers>, 2025-11-25).

So "empty" is a legitimate value, and two visitors with one GPU may report it differently.
The record says what the browser reported and no more.

**What a record would hold**, all of it visible to the visitor and none of it sent by the
page: a schema line and the page's version; the WGSL text's SHA-256; the WebAssembly
module's SHA-256 (DEMOS.md records the demos module's: READ); the vectors' digest; the
generator's rule, seed and lane count; counts by format and attribute (cases, differences,
refusals); each plant, seen, with its count; the verdict; up to N differences, each with
its case (format, attribute, operands, expected and got d and flags, and the lane and seed
that make it again); timings as reported, labelled not a rate; and the adapter's vendor,
architecture and isFallbackAdapter as reported. Never: the user-agent string, the limits
or features, the device or description strings. A visitor who wants to name a browser and
system picks them in the issue form.

**What a record proves**, by the asymmetry SWP-A §6.6 set out for contributed results
(READ):
- **A mismatch carries its case.** Anyone recomputes its expected value (the page's
  module, native libcft, the golden model), so a record cannot misstate the right answer;
  whether the GPU gave the wrong one, the reporter, or anyone with the same browser,
  driver and GPU, can reproduce.
- **A PASS is a claim:** anyone can type one. Plants guard against a broken page, not
  against a forger, and a public page has no secret to hide a honeypot behind (SWP-A's
  keyed honeypot needs a key the contributor does not hold: READ, §6.6). PASS records
  count as claims ("N reports of PASS on vendor X, architecture Y"), never as coverage.
- **Neither proves which physical device ran:** nothing attests it (BELIEVED, as SWP-A
  §6.6).

**How a visitor would send it** (a design; nothing was created):
1. **Recommended: a GitHub issue form**, YAML in `.github/ISSUE_TEMPLATE` (this repository
   has none yet: READ, `ls .github`): a textarea for the pasted record, dropdowns for
   browser and system, and a required checkbox, "this issue is public and shows my GitHub
   account" (READ, form syntax:
   <https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms>,
   where issue forms are in public preview). No server; the data is what the visitor
   pastes; the page links to the form with no query string, so no data travels in a URL.
2. **A file:** the record saved as JSON on a click, for the visitor to attach where they
   choose.
3. **Not recommended: a collecting service.** A server to run, a third party in the path,
   visitors' addresses in its logs, a privacy policy to write, and the records still
   forgeable.

**Consent and minimal data:** nothing runs before Run; no cookies, storage or telemetry;
the record holds the fields above and no others; the visitor reads it, and may edit it,
before pasting. **Collected:** nothing. No endpoint and no form exist.

## 5. The prototype: files only, not run

`studies/gpu-f/bn_probe.html` (520 lines) and `studies/gpu-f/README.txt` (68 lines)
(COUNTED). Both are headed NOT RUN.

- **What it is.** One static page. Its WGSL kernel (254 lines, COUNTED) is a hand port of
  bigint.c's core over 8-limb operands into 16-limb results: add, sub, mul, shl, shr and
  cmp, and softfloat.c's ISUB from them, keeping bigint.c's names, loop order and `n`
  convention. It is a second implementation, so its reference is JavaScript's BigInt,
  exact by definition: a second witness. The reference of record for a conformance page is
  the WebAssembly module, which is not used here because it exports libcft's operations,
  not the bigint core. Both files say which reference is which.
- **Why this, first.** It is the smallest test of what every route shares: does a
  browser's WGSL compiler on a visitor's GPU give exact u32 arithmetic for the 32x32 to 64
  product by halves, carry and borrow chains found by comparison, shifts at 0, 31 and 32,
  and function-scope arrays indexed at run time?
- **Plants:** four porting hazards, chosen by an override constant so that they share one
  text and one digest: (1) a carry dropped in `bn_add`; (2) `bn_shl` without its
  `bits != 0` guard; (3) `mul_wide`'s middle carry dropped; (4) `bn_sub` forming
  `y + borrow` in 32 bits, which wraps at y = 0xffffffff. Each runs first on 48,000 lanes
  and must make lanes differ, or the page reports BLIND.
- **The generator** is integer only: a case is a function of its lane and the seed, and
  every 48 lanes hold each of six ops under each of eight families (random limbs, carry
  chains, short operands, equal operands, single bits, edge limbs, edge shift counts,
  complements).
- **How it would run** (the lead's or Logan's choice): open the file from a checkout in a
  browser with WebGPU, keep 480,000 lanes and seed 20261113, press Run once. It fetches
  nothing.
- **What it would show:** kernel_sha256 `8d6e91b5...` (COMPUTED here over the kernel text
  with LF line endings, as a DOM holds it; in full in its README); compile errors by line,
  if any; the four plants' counts; for 10 dispatches of 48,000 lanes, PASS, FAIL with the
  first 8 differing lanes (each remade from lane and seed), BLIND, or REFUSED with its
  reason; and wall times per dispatch as reported. Nothing about the FMA, conformance or
  speed. A first run that stops on a slip in this hand-written, never-compiled file is a
  finding about the file, not about WebGPU.
- **Checked:** the JavaScript parsed by node --check (nothing executed): the page's runner
  script, copied to scratch, parsed clean with the desktop's node 22.19.0, and a copy with
  one planted extra brace was refused ("SyntaxError: Unexpected end of input"). The WGSL
  was checked by reading only; no compiler here.

**This desktop's WebGPU-capable runtimes** (READ from file version resources and two
registry values; nothing launched): Chrome 157.0.8103.51 and Edge 157.0.4341.46 (Edge's
registry beacon says .42, a newer file waiting for a restart: BELIEVED); node 22.19.0,
which has no built-in WebGPU (BELIEVED); no Firefox, no Deno. Whether Chrome enables
WebGPU on this desktop's GPUs was not checked: that needs a launch.

## 6. Recommendation (mine)

| step | what | cost (ESTIMATE) | what it decides |
|---|---|---|---|
| 0 | run `bn_probe.html` once in this desktop's Chrome; if wished, Safari 26 on the M2 Pro, where GPU-D's fault lived (whether its Safari has WebGPU on: not checked) | 10 minutes a browser | whether real WGSL compilers give exact limb arithmetic, and whether the plants show |
| 1 | (b') go/no-go: clspv and Tint, pinned, on GPU-D's text with the 64-bit lines edited | 1 to 2 days | whether one source reaches WGSL |
| 2 | the page: the FMA kernel from (b'), or from (a) if step 1 fails; G1 to G3; the record; the issue form; a third page in pages.yml | 3 to 5 days | the instrument itself |
| 3 | later: the sequencer through WebGPU, registers in a storage buffer; the gates in CI under a software WebGPU | not sized | programs in browsers; drift |

**Why build it at all:** of the routes this study found, it is the one by which this
project could see browsers' GPU compilers at scale; a mismatch report needs no trust; and
it needs no server.

**What it does not change.** The pages' scope line ("browser GPU floating point
(WebGL/WebGPU) is exactly the vendor-shaped nondeterminism this project exists to remove",
`bindings/wasm/page_template.html`, READ) stays true of floating point. Integer WGSL has
specified semantics (item 1), the same argument the WebAssembly page rests on, but a page
that runs it needs a scope line of its own (question 6).

## 7. Questions for Logan

1. **Run the probe?** One press of Run in a browser, its record filed in the ledger.
   *Mine:* yes, this desktop's Chrome first, then Safari on the M2 Pro, because Apple's
   OpenCL stack is where GPU-D's fault showed.
2. **What the page is for:** an instrument for mismatch reports, or also a public tally of
   PASS claims? *Mine:* mismatch reports, with PASS counted as claims and labelled so.
3. **The route:** (b') first, clspv and Tint on GPU-D's text with counted edits, or
   straight to a hand port? *Mine:* (b') first, since it keeps one source; the hand port
   only on a no-go, labelled a second implementation.
4. **host/src 32-bit only** (d1): two primitives in bigint.h in a backend round, if (b')
   works and its edits prove awkward? *Mine:* only after (b') has shown the road, with the
   full gate and a CPU-rate check.
5. **Collection:** a GitHub issue form with a pasted record, or a service? *Mine:* the
   issue form; never a service.
6. **Where it lives:** a third page beside conformance.html and demos.html, with its own
   scope line while theirs stays? *Mine:* yes.
7. **CI:** the page's gates headless under a software WebGPU (G4)? *Mine:* a short study
   before step 2 if the route is (a); not needed for (b').

## 8. Not run, not read

**Not run:** anything on a GPU; the prototype, in any browser (its JavaScript was only
parsed, by node --check); any WGSL compiler (none is installed); clspv, Tint and naga; the
issue form and the page of section 3 (not built); this desktop's browsers (read from
files only).

**Not read:** the WGSL TR past §12.4 and the WebGPU TR past §10 (their editor's draft
sources were read in their place); Chrome's "New in WebGPU 121" page (a search summary
only); Slang's 64-bit integers on its WGSL target; naga's WGSL back end on i64; Firefox's
and Safari's adapter-information policies; any browser's policy for a page whose device
was lost repeatedly; GPU-D §4 itself (its ledger instead).

## 9. Record

The ledger, `Data/runs/2026-11-10-gpu-a/ledger/GPU-F.md` (the records, not committed),
holds every source read and everything run, timed by `date`: grep, git, PowerShell reading
file versions and two registry values, three Python scripts in scratch (the digest, the
figures, the script's extraction), and node `--version` and `--check` at the lead's word.
Nothing was installed or downloaded. Removal: delete `studies/gpu-f/` and this file.
