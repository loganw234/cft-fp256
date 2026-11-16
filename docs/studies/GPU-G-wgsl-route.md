# GPU-G: the one-source road to WGSL - GPU-D's OpenCL C text through clspv and Tint, its 64-bit lines rewritten by counted edits

Study GPU-G of the GPU series, written 2026-11-16 by a study author (Opus 5.5) at Logan's word, branch
`gpu-g` from `9abd37ab`; clocks are `date` on the machine named. It is the go/no-go that
docs/ROADMAP.md's note of 2026-11-13 ("a WebGPU page, from study GPU-F") puts first, on route (b') of
[GPU-F](GPU-F-webgpu.md): [GPU-D](GPU-D-opencl.md)'s OpenCL C text, its 64-bit lines rewritten by
counted edits, through clspv to SPIR-V and Tint to WGSL. Logan's words: 2026-11-13, answering GPU-F's
question 3, "One source first"; the same day, on the tools, "Go ahead and install both, and add the note to
the roadmap"; 2026-11-16, on this parcel, "Yes, before" (this week, before GPU round 2's GPU builds).

Markings: MEASURED (run here, 2026-11-16, in WSL cft-gpu on this desktop's CPU unless said), READ (with
its path), COUNTED, COMPUTED, ESTIMATE (with its basis), BELIEVED (not checked); "not run" is said. No GPU
was used, no browser opened, nothing installed or downloaded. PoCL is the CPU.

## 1. The answer: GO

1. **GO.** 26 counted edits on GPU-D's text (W1 to W11), 45 in all with GPU-D's 19 (COUNTED), against
   GPU-F's ESTIMATE of 25 to 40: five over. Four clspv options are pipeline steps, two of them workarounds.
2. **The bits hold** (MEASURED, PoCL 7.2): the edited text through GPU-D's harness and ocl_run.sh gives the
   three plants RED at GPU-A's planted hashes and conf-fp32 to conf-fp256, stream-fp32 and stream-fp256
   GREEN at GPU-A's sums, as the unedited text does beside it in the same run.
3. **clspv** emits SPIR-V whose only capability is `Shader`: no Int64, no Int8 (MEASURED).
4. **Tint** turns it into WGSL, rc 0, 15,851 lines, and reads that WGSL back, rc 0 (MEASURED).
5. **The probe page** is written, `docs/studies/gpu-g/fma_probe.html`, NOT RUN: Logan or the lead runs it.

The rewritten rsqrt seed equals the 64-bit original on all 1,024 inputs its one caller can pass (MEASURED,
gcc 13.3.0 with UBSan), and a copy with one entry made wrong is refused (MEASURED).

## 2. The edits (item 1)

**The tool.** `docs/studies/gpu-g/wgslcopy.py` imports GPU-D's oclcopy.py and calls its `derive()`, so a
change there reaches it: its own selftest plants a change in oclcopy's shim and sees W9 refuse (MEASURED).
Each edit is an exact replacement on oclcopy's text with the number of matches it must find; a count that
differs refuses the text and names the edit. Its output counts them by kind (MEASURED, at the base):

`oclcopy's edits I 7, O1 2, O2 7, O3 1, O4 2 (19); GPU-G's W1 3, W2 2, W3 2, W4 1, W5 1, W6 3, W7 1, W8 2, W9 1, W10 8, W11 2 (26); 45 in all`

The text: 99,258 B, sha256 `e4cd93df...` (MEASURED); GPU-D's unedited text at the same base is 96,078 B,
`9d49589f...` (not GPU-D's own `02efcc15`: host/src has moved since GPU-D's base). The W edits remove 64
lines and add 125 of its 2,478 (COUNTED, diff).

| kind | what it does | edits | needed by the chain today? (MEASURED, the ablation below) |
|---|---|---|---|
| W1 | `cft_g_mul`, a 32x32 product as (hi, lo) by 16-bit halves; cft_bn_mul's schoolbook step through it; IMUL's low half as a u32 product | 3 | yes: without W1 and W9, Int64 |
| W2 | add's carry and sub's borrow by comparison | 2 | yes: Int64 |
| W3 | extract's 64-bit funnel as two 32-bit shifts, guarded at offset 0 | 2 | yes: Int64 |
| W4 | seed_recip_entry's `1uL << 28` as `1u << 28` | 1 | no: the literal folds; kept for the tool's scan |
| W5 | seed_rsqrt_entry in 32-bit pieces (the lead's change to my plan) | 1 | no: dead after inlining (the lane passes CFT_SF_FMA); kept for one source and the seeds a later page will want |
| W6 | the kernel's `long n` as `uint2` (8 bytes, as GPU-D's harness binds its cl_long), the bound n <= 2^27, `long i` as uint | 3 | yes: Int64 |
| W7 | fix (B): `reqd_work_group_size(64, 1, 1)` | 1 | yes: Tint's internal error |
| W8 | cft_fmt_desc's `name` pointer and the table's four strings out | 2 | yes: clspv crashes |
| W9 | the shim's int64_t and uint64_t left undefined | 1 | no: a check, so a leftover 64-bit type fails to compile |
| W10 | bytes as 32-bit words: the kernel's six buffers as uint (rnd's and flags' byte in word i/4, flags by atomic AND and OR on that byte), the lane on words, cft_g_load and cft_g_store | 8 | for the layout: without it clspv at --int8=false stores each char in a 32-bit element, 4x GPU-D's buffers; with int8 allowed, Int8 |
| W11 | reduce_leaf between `#if 0` and `#endif`, as O4 takes cft_sf_reduce out | 2 | yes, with --int8=false: clspv refuses its void pointers |

**What GPU-F expected and what came.** GPU-F named the ten bigint lines, IMUL, the seed, the aliased call,
six pointer choices and a lane on words (READ, GPU-F section 2). The aliased call and the pointer choices
needed nothing: clspv's SPIR-V carries no VariablePointers capability (MEASURED); that its full inlining
removed them is BELIEVED. Not foreseen: the struct's pointer (W8), the work-group size (W7), the kernel's
`long` and its binding (W6), reduce_leaf (W11), the check W9, and the int8 option below.

**The checks at every build** (wgslcopy.py, MEASURED at the base):
- a call graph from `cft_fma_ocl`, every call counted whatever the opcode: 58 of the text's 68 functions
  reachable (COUNTED). No `long`, `ulong`, `int64_t`, `uint64_t`, `char`, `uchar`, `int8_t`, `uint8_t`,
  `size_t` or L-suffixed literal in them or the three structs they name; no `#define` but CFT_EXP_SPAN's
  four carries such a literal, and CFT_EXP_SPAN is read by `#if` alone;
- oclcopy's own checks on the result: cft_sf_reduce named once (its prototype), no recursion; and W11's
  in their manner: reduce_leaf named nowhere outside its excluded lines;
- `--check`: the written text against the derivation, byte for byte.

`--selftest` plants eleven faults and each is refused by name (MEASURED): a doctored count, host/src's
schoolbook line changed, a second `1uL << 28`, oclcopy's shim changed, a ulong in the kernel, a uchar in
the lane, `1uL` back in seed_recip_entry, a 64-bit `#define`, a caller of reduce_leaf, a function calling
itself, one byte of the written text.

**The seed (W5).** Its inputs are COUNTED from its one caller, sf_rsqrt_seed:
`((uint32_t)odd << 9) | cft_bn_extract(x, f->man_w - 9, 9)` with `odd = E & 1`, so 2 x 512 = 1,024;
`--seedcheck` refuses if that caller's text changes. It writes C holding the original from host/src (as
oclcopy copies it) and the W5 version with `cft_g_mul`, both taken from the texts by name; run_gpug.sh
compiles it with `gcc -O2 -std=c99 -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all`:
"seedcheck: 1024 inputs, 0 differ: OK" (MEASURED). `--plant` makes entry 300 wrong: "1024 inputs, 1 differ:
REFUSED", rc 1 (MEASURED). The rewrite: 2^44 / m2 (m2 below 2^12) by long division in 16-bit steps, the
squares and their products with m2 as (hi, lo) pairs, the same three steps as the original. It held at its
first run, so the lead's fallback (removal) was not needed.

**The ablation** (MEASURED, a scratch script recorded in the ledger): the full set less one kind, with W9 also
left out where W9 would turn the 64-bit code into a compile error, through the same clspv and Tint.

| left out | clspv | Tint |
|---|---|---|
| nothing (the chain) | Shader | rc 0, 15,851 lines |
| W1 (helper kept), W2, W3 or W6, each with W9 | Shader Int64 | "Failed to parse SPIR-V: SPIR-V capability 'Int64' is not supported" |
| W4; W5 with W9; W9 alone | Shader | rc 0 |
| W7 | Shader | rc -4: "resolver.cc:227 internal compiler error: AST node 'tint::ast::Identifier' was not reached by the resolver" |
| W8 | rc -11 (segfault) after "ptr addrspace(1)"; at `--cl-std=CL1.2` alone, on the unedited text, rc 134, "Invalid bitcast ... ptr addrspace(2) ... to i32 / LLVM ERROR: Broken module found" | not reached |
| W10, at --int8=false | Shader | rc 0, 16,258 lines; each char in a 32-bit element (READ from that WGSL: flags indexed by lane) |
| W10, int8 allowed | Shader Int8 | "SPIR-V capability 'Int8' is not supported" |
| W11 | rc 255: "error: pointer-to-void is only supported with int8 support and opaque pointers" | not reached |
| the option --int8=false | Shader Int8: `OpUConvert %uchar` of a shifted word, 13 times, and 50 compares with uchar constants 0 to 4 and 16, in the final text (MEASURED by the verifier; the "ten times" first written here was a draft's count) (BELIEVED: the optimiser narrowing the rnd byte's tests; the final SPIR-V has no OpSwitch) | refuses Int8 |
| the option --inline-entry-points | Shader | "SPIR-V failed validation ... OpFunctionCall Argument ... type does not match ... parameter type" |
| the option --pod-ubo | Shader | rc 0 (the draft's WGSL then holds n, fmt and esz as `var<immediate>`) |

W8's construct: the kernel's `f = cft_sf_formats[fmt]` copies a struct that holds a `__constant` pointer
(the format's name, which no code reads: grep). W7's: the work-group size as clspv's spec-constant
WorkgroupSize, as in the lead's smoke test of 2026-11-13. Fix (A) on the text without W7 (`spirv-opt
--freeze-spec-const --eliminate-dead-code-aggressive --strip-nonsemantic`) also gives WGSL, rc 0, but with
`@workgroup_size(1u, 1u, 1u)` (MEASURED): a work-group of one. Fix (B) gives 64.

## 3. The bits, held (item 2)

**How** (MEASURED, run_gpug.sh in cft-gpu, 06:50:36-06:51:31): the corpora by GPU-A's gen_corpus.py, all
eight at GPU-A's captured sums; GPU-D's bundle by its make_bundle.sh (harness, unedited text, corpora,
ocl_run.sh, gen_corpus.py); the edited text added. PoCL 7.2, its ICD from /etc/opt/gpu-c, four compute units
as GPU-D ran it. Then GPU-D's ocl_run.sh twice:
- **the control,** the unedited text: ALL AS EXPECTED;
- **the edited text,** `CL=cft_fma_g.cl ocl_run.sh --wg 64`: ALL AS EXPECTED.

In each run (MEASURED):
- the plants first, each RED with GPU-A's planted output: the flipped corpus `da932116...`, rmm-as-rne
  `ffe3f2eb...`, drop-flag `f0ca15e0...`;
- conf-fp32 to conf-fp256 (18,435, 18,440, 18,545 and 18,360 cases), stream-fp32 and stream-fp256 (1,000,000
  each) GREEN at GPU-A's sums (conf-fp256 `da932116...`, stream-fp256 `9c7f2f6e...`), each confirmed by
  gen_corpus.py verify: 0 results and 0 flags differ.

No difference, so no edit is a NO-GO. The same held in two earlier runs of the whole chain, at 06:30 and
06:42, and for a draft of the edits at 06:23 (MEASURED).

**--wg 64.** For W7's kernel PoCL reports CL_KERNEL_WORK_GROUP_SIZE 4096, and the harness's launch at 4096
fails with OpenCL error -54 (MEASURED). The harness's own `--wg 64` sets the size the kernel requires.
The fp256 rate in that run, for the record only: 7.694e6 FMA/s at work-group 64 against 3.967e6 for the
control at 4096 (MEASURED, kernel medians of 10; two work-group sizes, one session, not a comparison of the
texts).

**Two known limits of W10 on PoCL:**
- the flags are written by atomic AND and OR, which read the flags buffer; GPU-D's harness creates it
  CL_MEM_WRITE_ONLY, and OpenCL leaves a kernel's read of such a buffer undefined (BELIEVED, not looked up
  here);
- when n is not a multiple of 4 (conf-fp32's 18,435, conf-fp128's 18,545, the harness's one-lane first
  launch), the last word of rnd and flags reaches up to 3 bytes past the n-byte buffer. The kernel never
  changes those bytes (the AND keeps them, the OR adds nothing to them), and a 4-byte-aligned word never
  crosses a page (COMPUTED); that PoCL's allocation covers them is BELIEVED.

The page sizes those two buffers to whole words, so neither limit reaches it.

## 4. clspv (item 3)

**Options:** `--cl-std=CL1.2 --inline-entry-points --pod-ubo --int8=false`:
- `-cl-std=CL1.2` as GPU-D's harness builds;
- `--inline-entry-points`, a workaround: without it clspv's SPIR-V fails validation;
- `--pod-ubo` puts fmt, esz and n in a uniform buffer, which a WebGPU page binds;
- `--int8=false`, a workaround: without it the optimiser's narrowed switch brings Int8 back.

The plants are GPU-A's macros, as `-D` options to clspv. The tools' sha256 equal the lead's list of
2026-11-13 (MEASURED; READ, tools-1113/bin-sha256-and-sizes.txt in the round's records).

| module | -D | SPIR-V (MEASURED) | sha256 | capabilities (spirv-dis) |
|---|---|---|---|---|
| plain | none | 298,584 B | `3288df3ae139898360e8c57db90670b6171ee75ef711474dbbcd663d26c5b365` | Shader |
| rmm-as-rne | CFT_GPUA_PLANT_RMM_AS_RNE | 298,628 B | `e07c03b47d9e042fbfbc0b328703821d73824dd9eabf3d473a89752961f34d71` | Shader |
| drop-flag | CFT_GPUA_PLANT_DROP_FLAG=8 | 309,384 B | `e14afde80ce97e49ffc1ed56617e10a7135978372d5986aa425c145dd01afdf9` | Shader |

Each build gives 8 warnings, all "macro is not used" (MEASURED). In each module the one numeric type is
`OpTypeInt 32 0`, the extensions are SPV_KHR_storage_buffer_storage_class and SPV_KHR_non_semantic_info, and
the memory model is Logical GLSL450 (MEASURED, spirv-dis).

## 5. Tint (item 4)

`tint X.spv --format wgsl`, then `tint X.wgsl --input-format wgsl --format wgsl` (MEASURED):

| module | WGSL | sha256 | read back |
|---|---|---|---|
| plain | 15,851 lines, 840,008 B | `b4de3258e8cbf68abcea53f886b0c0b140751d83462bf99dd43c961c1dcfdf00` | rc 0 |
| rmm-as-rne | 15,851 lines, 840,034 B | `d25d7e9aa6cbbbb2860f53ccd73827bfc45dbf4aa36cba49f163937f03821d9c` | rc 0 |
| drop-flag | 17,405 lines, 922,419 B | `ca6f8041f3bed4af3f7af1963f828b36a3ae78f41eda1f5103f1c80140b8320d` | rc 0 |

**Every refusal and internal error met** is in section 2's ablation, each with its construct: Int64 (the
64-bit lines and the kernel's long), Int8 (the bytes; the narrowed switch), Tint's internal error at
resolver.cc:227 (the spec-constant work-group size), a SPIR-V validation failure (clspv without full
inlining), clspv's crash (the struct's pointer) and its void-pointer error (reduce_leaf at --int8=false).
Each workaround is counted: W7, W8, W10 and W11 as edits, two options as pipeline steps.

**The shader's shape** (READ from the plain WGSL): six `var<storage, read_write>` bindings, @group(0)
@binding(0) to (5), a, b, c, rnd, d and flags, flags as `array<atomic<u32>>`; @binding(6) a
`var<uniform>` of {u32 fmt, u32 esz, vec2<u32> n}, 16 B; `@compute @workgroup_size(64u, 1u, 1u) fn
cft_fma_ocl`. Everything is inlined into that one function.

**A risk for the page, not tested:** that function declares 30 arrays (23 of 65 u32, which is a cft_bn; 3 of
69; 4 of 8), 6,936 B, and 878 u32 and 1,178 bool scalars (COUNTED). WGSL guarantees 8,192 B of function-scope
variables a function, and an implementation may support more (READ, GPU-F section 1, item 5). Whether a
browser accepts this shader, and how long it compiles, is unknown until the page runs. The page reports a
compilation error by name and times the module and the pipeline.

## 6. The verdict (item 5)

**GO:** items 2 to 4 all hold. The edits by kind: W1 3, W2 2, W3 2, W4 1, W5 1, W6 3, W7 1, W8 2, W9 1, W10 8,
W11 2: 26 (COUNTED). With GPU-D's 19 that is 45, five above GPU-F's 25 to 40 (an ESTIMATE). By the ablation,
three of the 26 are not needed by this clspv and Tint today (W4, W5 and the check W9), and W1's IMUL line sits
on a path the FMA lane cannot take, as W5 does (BELIEVED to fold the same way; it was not left out alone).
The pipeline adds two workaround options. On this GO the hand port of route (a) is not the next step; it
stays the fallback should a browser refuse this shader (question 1).

## 7. The probe page (item 6), NOT RUN

`docs/studies/gpu-g/fma_probe.html`, 456,300 B, sha256 `6e2d4f05...` (MEASURED; run_gpug.sh fills it again
equal byte for byte), on bn_probe.html's model, in the layout of ROADMAP's note:
nothing runs until Run is pressed, the plants first, each verdict named, the record shown and never sent.
- **The WGSL:** the three modules of section 5, byte for byte, with their sha256.
- **The cases:** GPU-A's conformance corpora, the published vectors' elementwise FMA cases at the counts of
  `make vectors`, with the golden model's results. From each, every k-th case from case 0, k = n div 1,024:
  1,024 cases a format, 4,096 in all (COUNTED). The rounding attributes rne/rtz/rdn/rup/rmm: fp32 and fp64
  205/205/205/205/204, fp128 207/206/206/206/199, fp256 216/216/216/216/160 (COUNTED).
- **The blob:** ONE gzip blob, base64 in the page: 7 parts and a header, 2,856,918 B; 328,858 B gzipped;
  438,480 B base64 on 4,385 lines (MEASURED). One blob does not compress better: the seven parts gzipped apart
  take 328,764 B without the header the blob needs (MEASURED). DEFLATE's window is 32 KB (BELIEVED) and the
  modules are 0.8 to 0.9 MB, so the plants' likeness to the plain module is out of its reach. Interleaving
  the modules in 4 KB chunks would take their 231,015 B to 157,798 B (MEASURED), at the cost of code in the
  page: not done.
- **The digests:** after decompression and before any use the page checks each part's sha256 against its
  own constants, refuses on any difference, and shows all three module digests in its record.
- **The plants:** the rmm-as-rne and drop-flag modules run first. Each must be RED, and its d || flags on
  each subset must equal PoCL's, which the page holds (MEASURED here: rmm-as-rne 3, 2, 4 and 4 results differ
  in fp32 to fp256, drop-flag 79, 85, 74 and 74 flags). A flipped expected bit must then be counted exactly
  once. Then the plain module, every lane compared.
- **The verdict:** PASS, FAIL, BLIND (a plant not seen), REFUSED (no WebGPU, a digest, a compilation error)
  or DEVICE LOST, never retried.
- **Sends nothing:** a Content-Security-Policy of `default-src 'none'`, and no fetch, XMLHttpRequest,
  sendBeacon, WebSocket, EventSource, link, image or `src=` in the file (COUNTED: 0).

**Checked outside a browser** (MEASURED, node v22.19.0 on this desktop): `node --check` parses the page's
script. `page_datapath.mjs` runs the page's own unpack(), corpus() and compare() with a stub for its DOM and
no WebGPU: 7 parts, each sha256 equal to the page's; four subsets of 1,024; compare() 0 lanes against a
subset's own values and 1 against a flipped bit; OK. With one digest character changed it fails, rc 1.

**How to run it** (Logan or the lead): open the file in a browser with WebGPU, Chrome or Edge, from the local
disk or localhost (a secure context), and press Run. **What it would show:** the browser and adapter; for each
module the time to the pipeline; per format, lanes and differing lanes by attribute, and whether d || flags
equals PoCL's; the plants seen or not; the flip; the verdict. A PASS means the GPU computed libcft's FMA bit
for bit on these 4,096 cases. A FAIL shows its first three lanes.

## 8. What was not run

- The page, in any browser; the WGSL, on any GPU. No GPU device was used.
- The edited text on GPU-D's other runtimes (Apple's, AMD's, Intel's): PoCL alone.
- naga; spirv-val beyond Tint's own validation; a browser's Tint, which may differ from this build.
- IMUL's and the seeds' lines on PoCL: no corpus calls them. The seed is held exhaustively by gcc; IMUL's low
  half of the product is the product modulo 2^32, which is what C's uint32_t multiplication gives (BELIEVED,
  C's unsigned arithmetic; not run).
- Fix (A) beyond the one build in section 2; clspv without full inlining beyond its validation failure.
- The WGSL's compile time and its function-scope size in any browser (section 5).

## 9. Questions for Logan

1. **The shader is large.** 15,851 lines, because clspv inlines the whole FMA path, the only mode Tint took
   here (section 5). Run the probe page once on the machine that ran bn_probe, before GPU round 2 builds on
   this road? *Mine:* yes. It is the cheapest test of whether a browser takes a shader of this size, and it
   times the compile. On a REFUSED for its size, the next step is clspv's validation failure without full
   inlining, before any hand port.
2. **W10 on GPU-D's harness.** Its atomics read a CL_MEM_WRITE_ONLY buffer, and its last word reaches up to
   3 bytes past rnd and flags (section 3). Pad those two buffers to whole words, and drop WRITE_ONLY on
   flags, when GPU-D's harness is next changed? *Mine:* yes, then; nothing now.
3. **The blob's size.** Interleaving the modules would cut the WGSL's gzip by about a third (section 7).
   *Mine:* not for this probe; for the real page if its 0.46 MB matters.
4. **The toolchain.** The road depends on clspv d41b518e at `--int8=false` and Tint 93adb9c9's SPIR-V reader.
   run_gpug.sh prints the tools' sha256 at every run. Pin them in a container, as GPU-F suggested, before the
   page is built? *Mine:* yes, at the page's parcel, rebuilt from those commits; until then the printed sums
   are the pin.

## 10. Files and how to rerun

- `docs/studies/gpu-g/wgslcopy.py`: the copy tool (the edits, the scans, `--check`, `--selftest`,
  `--seedcheck`).
- `docs/studies/gpu-g/run_gpug.sh`, given an output directory and a corpus directory: the whole chain on
  one Linux host with PoCL, clspv, Tint and gcc (cft-gpu): the texts, the seed, clspv, Tint, PoCL's control
  and edited runs, the page's data. Last line ALL AS EXPECTED. It also says whether the page it fills
  equals the committed one, byte for byte.
- `docs/studies/gpu-g/make_probe.py`: the subsets and the page's two marked regions.
- `docs/studies/gpu-g/fma_probe.html`: the probe page, NOT RUN.
- `docs/studies/gpu-g/page_datapath.mjs`: the page's data path in node (above).

To rerun: move the tree into cft-gpu (a tar of the commit), make the corpora with GPU-A's gen_corpus.py
(conformance and stream), then, with PoCL's ICD in OCL_ICD_VENDORS, run run_gpug.sh with a new output
directory and the corpus directory (MEASURED 46 and 55 s); and on a machine with node 22, run
page_datapath.mjs on the page.
