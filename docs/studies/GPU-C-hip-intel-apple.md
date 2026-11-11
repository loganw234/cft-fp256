# GPU-C: HIP's code on Intel Arc and Apple Metal, what exists and what works

Study GPU-C of the GPU series, written 2026-11-10 (Sonnet 5.5, a study author; clocks are `date` on the
desktop and in the WSL distro cft-gpu). It follows [GPU-A](GPU-A-hip.md) (one HIP source runs libcft's
arithmetic bit for bit on NVIDIA and AMD) and [GPU-B](GPU-B-hip-nvidia.md) (HIP's NVIDIA platform).
Logan's word, 2026-11-10, about 19:05: "Go ahead and dispatch a parcel to look into HIP compilation to Intel
Arc and Apple Metal, Im unsure what exists for it, but compatibility for both would be a nice plus." And about
19:18, on the hardware: "I can swap in an intel card into the amd-arc-box (it hosts the U50 as well), and the
macbook can be available when needed."

Markings: MEASURED (run here, 2026-11-10), READ (with URL or path; read 2026-11-10), COMPUTED, ESTIMATE
(with its basis), BELIEVED (not checked), "not run" and "not read" where that is the case. The rule of GPU-A holds:
the GPU runs **libcft's own arithmetic**, by GPU-A's scripted copy. A route that needs the arithmetic rewritten
in another language is a **second implementation**, said so, with its cost, and ranked below.

## 1. The answer first

1. **Intel.** MEASURED: GPU-A's `cft_fma.hip` and `cft_seq.hip`, **unchanged**, built by the scripted device
   copy through **chipStar v1.3.0** with a packaged clang 22, run on **PoCL 7.2's CPU device (SPIR-V through
   OpenCL), not an Intel GPU**, give the fp256 conformance corpus hash
   `da932116555557bef8fcd6980da18963b1420bfc892163c67b32d1cc53a2eba9`, the three other conformance corpora and
   1,000,000-case streams GREEN, every sequencer corpus equal to GPU-A's recorded reference sums, and every
   plant RED. This is the Intel software path with the one step that needs the card missing. A bundle that
   runs the same checks on an Arc, and a runbook, are in [gpu-c/](gpu-c/); the runbook recommends the **A750**
   (section 7). Nothing ran on an Intel GPU.
2. **Apple.** No route to the Metal GPU that keeps the one source has been shown to work. MEASURED: chipStar's
   SPIR-V is the OpenCL "Kernel" flavour and SPIRV-Cross refuses it. READ: chipStar on macOS runs through PoCL,
   **CPU only**. What gets closest: the arithmetic text compiles as **OpenCL C 1.2** with three small edits
   (MEASURED, syntax only), which Apple's deprecated OpenCL takes as source text, and a scripted edit could
   make it Metal Shading Language (BELIEVED). Both need a **new host harness**, not new arithmetic. A probe
   runbook for the M2 Pro is in [gpu-c/RUNBOOK-M2.txt](gpu-c/RUNBOOK-M2.txt).
3. The recommendation, the costs and the questions for Logan are in sections 8 to 10.

## 2. What exists for Intel

All READ on 2026-11-10 unless marked. Dates are as the pages print them (several print no year).

| route | what it takes and gives | state | one source? |
|---|---|---|---|
| **chipStar** (CHIP-SPV), github.com/CHIP-SPV/chipStar | HIP and CUDA source to SPIR-V, run through OpenCL or Level Zero | v1.3.0, 20 May (commit date 2026-05-20, MEASURED from the clone); latest commit 2026-11-10 (api.github.com); README: "still heavily in development" | **yes**, MEASURED |
| Intel compute-runtime ("NEO") with IGC, github.com/intel/compute-runtime/releases | the OpenCL 3.0 and Level Zero 1.18 runtime for Alchemist and Battlemage: a runtime, not a compiler | 26.40.40196.8, 3 Nov; Alchemist and Battlemage "Production" | n/a |
| Canonical's noble archive (MEASURED, `apt-cache policy`) | intel-opencl-icd, libigc1, libze-intel-gpu1 at 23.43.27642.40 and IGC 1.0.15468.25 | December 2023 builds | n/a |
| PoCL, github.com/pocl/pocl/releases | OpenCL on CPUs with SPIR-V input; this study's stand-in for the card | 7.2 (04 Sep; commit 2026-09-02 MEASURED), supports LLVM 18 to 22 | n/a |
| oneAPI DPC++ (intel/llvm) | SYCL C++ to SPIR-V; takes SYCL, not HIP | nightlies, latest 2026-11-09 (api.github.com); docs not read | **no**: the source is rewritten in SYCL |
| SYCLomatic, github.com/oneapi-src/SYCLomatic | migrates CUDA to SYCL "with final editing manual"; its page does not mention HIP | daily prereleases, latest 2026-09-28; "None of the branches in the project are stable" | **no** (and HIP not stated) |
| AdaptiveCpp (formerly hipSYCL) | SYCL; lists Intel and Apple GPUs; PCUDA (CUDA or HIP code) "experimental" | latest release v25.10.0, 2025-11-05 (a year old); backends and how Apple works were **not read** | **no** for SYCL; PCUDA not tried |
| OpenCL C written by hand | the arithmetic as OpenCL C 1.2 (section 5.4) | n/a | text yes, **harness new** |

What chipStar asks of the OpenCL device (README, READ): OpenCL 2.0 or 3.0 with coarse-grained buffer SVM, SPIR-V
input, the generic address space and program-scope variables; warp primitives need sub-group extensions. MEASURED
here, the SPIR-V chipStar made from `cft_fma.hip` declares only the capabilities Addresses, Linkage, Kernel,
Int64, GenericPointer and Int8 (captured/spirv_for_apple.txt): **no Float64 and no Float16 is required**.
Integer width is the whole requirement: Int64 is declared, and the 32 x 32 to 64-bit multiply the bignum uses is
ordinary integer multiplication in the copy.

## 3. What exists for Apple

| route | what it does | state | one source? |
|---|---|---|---|
| chipStar on macOS, docs/MacOS.md | HIP to SPIR-V run by **PoCL on the CPU**; "macOS's built-in OpenCL runtime does not support SPIR-V" | v1.3.0's release page: "macOS is now a supported chipStar platform, including Apple CPU Silicon via PoCL"; MacOS.md at v1.3.0: "LLVM/Clang (18, 19, or 20) with patches", tested at LLVM 19.0, built from source from CHIP-SPV's forks (llvm-project branch `chipStar-llvm-19`; PoCL branch `macos-chipstar`), Xcode command-line tools, Homebrew | yes, **CPU only, no Metal** |
| chipStar native Vulkan backend (README) | SPIR-V for Vulkan compute | experimental, "requires LLVM 24+", Vulkan 1.3 driver, libclc; commits on it as late as 2026-11-10; whether it runs on Apple was **not read** | yes, unproven on Apple |
| KosmicKrisp (Mesa; LunarG), docs.mesa3d.org, lunarg.com | Vulkan on Metal 4 for Apple Silicon, macOS 26 or later | Vulkan 1.3 conformant, later 1.4 (Phoronix, October 2026); shaderInt64 not read | the Vulkan driver a Vulkan route would use |
| MoltenVK, github.com/KhronosGroup/MoltenVK | Vulkan on Metal, SPIR-V to MSL at run time | README: "Khronos has deprecated MoltenVK"; community best-effort; Khronos points Apple Silicon at KosmicKrisp | as above |
| SPIRV-Cross | SPIR-V (Vulkan "Shader" flavour) to MSL, GLSL, HLSL | maintained under Khronos; **refuses chipStar's output, MEASURED** (5.2) | no |
| clspv, github.com/google/clspv | **OpenCL C 1.2** to Vulkan compute SPIR-V; "not an official Google product", passed OpenCL 3.0 conformance | daily builds; 64-bit integers and private-memory limits not stated on the page | text via 5.4, not run |
| Apple's OpenCL | OpenCL C source text, 1.2 (BELIEVED), no SPIR-V | deprecated in macOS 10.14 (Apple's developer page); a forum report says it still runs on macOS 26.5 | text via 5.4 |
| Metal Shading Language, Apple | C++14-based; compiled by Apple's `metal` (Xcode) | Windows-hosted tools exist but need a developer-account login (READ, search results); not downloaded | via a scripted edit, BELIEVED |
| WebGPU: wgpu, Dawn, naga | WGSL to MSL | no standardized 64-bit integer type found in Chrome's WebGPU notes through September 2026; a Khronos slide lists 64-bit atomics as upcoming (BELIEVED absent) | **no**: 32-bit-limb rewrite |
| AdaptiveCpp | lists Apple GPUs; mechanism **not read** | as in section 2 | no |

## 4. Hands-on, Intel route, on this desktop

### 4.1 What was installed (all in cft-gpu; nothing else touched)

The WSL distro cft-gpu is Ubuntu 24.04, 12 threads, 47 GB (MEASURED). The one script that reproduces it is
[gpu-c/install_desktop.sh](gpu-c/install_desktop.sh). No GPU driver. Packages by source:

| what | source | version | size | where |
|---|---|---|---|---|
| clang-22, llvm-22-dev, libclang-22-dev, libclang-cpp22-dev, lld-22, clang-tools-22 | apt.llvm.org noble-22, key fingerprint 6084 F3CF 814B 57C1 CF12 EFD5 15CF 4D18 AF4F 7421 (matches the page) | 22.1.8 (built 2026-07-14) | 54 packages in all, 196 MB download, 1214 MB disk; clang-tools-22 9.9 MB | /usr/lib/llvm-22 |
| ninja, ocl-icd, opencl-headers, clinfo, spirv-tools, spirv-headers, hwloc, zstd, edit, xml2 dev files | Canonical | noble | (in the 196 MB) | system |
| python3-mpmath, python3-pytest (gen_programs.py needs them); spirv-cross | Canonical | noble | 794 kB; 825 kB | system |
| SPIRV-LLVM-Translator, branch llvm_release_220 (+ SPIRV-Headers at its pin cb42dec3) | github.com/KhronosGroup | built here | 22 MB installed | /opt/gpu-c/spirv-tr |
| PoCL v7.2 (commit 888c9774) | github.com/pocl/pocl | built here | 17 MB | /opt/gpu-c/pocl; its ICD file landed outside the prefix, in /etc/opt/gpu-c |
| chipStar v1.3.0 (commit ed3bc0cb), submodules | github.com/CHIP-SPV | built here | 48 MB | /opt/gpu-c/chipstar |

Why each build was from source (the lead's rule: packaged where the stated minimum is met): Canonical's PoCL is
5.0 (MEASURED, apt-cache) and chipStar's Getting_Started.md (READ, on `main`) says the apt PoCL lacks SPIR-V; the v1.3.0
release page says only "PoCL support updated to version 7" and no page I read gives a minimum; I did not run PoCL 5.0; Ubuntu's SPIRV headers (1.4.309) are
too old for the translator, and no llvm-spirv is packaged for 22; chipStar has no package. **The patched LLVM
that chipStar's README names was not needed and not built.**

Build times (MEASURED, -j4, nice 10): translator 19:22:05 to 19:24:11; PoCL 19:26:19 to 19:27:50; chipStar's
last pass 19:41:04 to 19:41:46 after two earlier passes (the first from 19:31:06 failed after about two minutes),
about 3 minutes of compilation in all. The first run of a kernel JITs the SPIR-V (7.2 s on PoCL, then cached).
`update-alternatives`: the `cuda`, `cuda-12`, `cuda-13`, `cc` and `c++` groups unchanged; one new group,
`automake` (a dependency of libltdl-dev), no clang or cc alternative registered. The one file placed inside the
apt package's directory is `/usr/lib/llvm-22/bin/llvm-spirv` (the wrapper, 4.2). Remove it all: section 11.

### 4.2 The errors, and the changes they needed

The device copy and `cft_fma.hip` and `cft_seq.hip` were **not edited**. The changes are to the toolchain, in
[gpu-c/captured/chipstar_errors.txt](gpu-c/captured/chipstar_errors.txt):

1. `clang-offload-bundler` missing: apt `clang-tools-22`.
2. `hipspv-link ... exit code 17`, "SPIR-V version was restricted to at most 1.1 but a construct needs 1.2":
   stock clang 22's HIP-to-SPIR-V driver calls `llvm-spirv --spirv-max-version=1.1 --spirv-ext=+all`.
   [gpu-c/llvm-spirv-wrapper.sh](gpu-c/llvm-spirv-wrapper.sh), installed as `llvm-spirv` beside clang, changes
   **two arguments** to what chipStar's own LLVM 22 patch
   (`llvm-patches/llvm/0001-0004-spirv-version-and-extensions-llvm22.patch`) makes the driver pass: max version
   1.2, and an extension list of four names instead of `+all`.
3. The second change was found by its failure: with `+all` LLVM 22's translator declares
   `SPV_KHR_untyped_pointers`, chipStar's SPIR-V parser prints "Parameter type ID 29 not found in type map",
   drops every kernel parameter, and the launch fails `CL_INVALID_KERNEL_ARGS`.
4. A CUDA sample that "requires SPIR-V version 1.6": `-DCHIP_BUILD_SAMPLES=OFF`.
5. chipStar's translator patch (`llvm-patches/spirv-translator/0002-Pretend-...-1.2.patch`, shuffles need 1.2
   not 1.3) is **one line**, applied by `sed` because `git apply` missed on this branch. MEASURED, it is **not
   needed** for `cft_fma.hip`: with the line put back and the translator rebuilt, the same build is GREEN
   (20:03 to 20:07). The recipe keeps it because chipStar's patch README gives it as the way to warp-level
   primitives.
6. `hipDeviceGetLimit(hipLimitStackSize)` is **unsupported by chipStar** (`hipErrorInvalidHandle`, "Invalid
   Limit value"). It is called only by the harness's `info` subcommand (cft_fma.hip:625 and 653), which therefore fails
   here; `check` and `bench` ran without it, and `cft_seq.hip` has the same two calls (lines 631 and 651, grep) in
   a diagnostic routine its `run` subcommand ran without (its `info` was not run). This is the only place a
   GPU-A source depends on an API chipStar lacks, and it is a diagnostic.

### 4.3 The results (MEASURED, device: PoCL 7.2 on this desktop's i5-12400F, 12 compute units)

Scripts: [gpu-c/run_chipstar.sh](gpu-c/run_chipstar.sh), [gpu-c/run_seq_chipstar.sh](gpu-c/run_seq_chipstar.sh);
captured in gpu-c/captured/ (`run_chipstar-fp-conf.txt`, `run_seq_chipstar.txt`, `stream_bench_info.txt`).
**Plants first**, on the fp256 conformance corpus (GPU-A's plants, built through chipStar):

| plant | result | what it shows |
|---|---|---|
| one expected bit flipped (case 12345) | RED: 1 result differs; Python verify RED too | the compare sees one bit |
| rmm taken as rne (build flag) | RED: 51 results differ | a wrong rounding mode is seen |
| underflow flag dropped (build flag) | RED: 1452 flags differ | a wrong flag is seen |
| sequencer: mask and constant plants (cft_seq) | both RED | the program runner's check sees them |

Then, all GREEN, and each output file hashed again by hashlib in Python (`gen_corpus.py verify`; its lines are
kept for the streams only, in stream_bench_info.txt, to hold the captures short):

| corpus | cases | output sha256 (first 16 hex) |
|---|---|---|
| conf-fp32 | 18435 | dd3d83be8ba2477c |
| conf-fp64 | 18440 | 3a8a9b2cb98a5be9 |
| conf-fp128 | 18545 | fcc92da36e24b19c |
| **conf-fp256** | 18360 | **da932116555557bef8fcd6980da18963b1420bfc892163c67b32d1cc53a2eba9** (full) |
| stream-fp32, stream-fp256 | 1,000,000 each | 15545866e2b21b6f, 9c7f2f6e9130003b |

The sequencer (GPU-A part 2): routines and fuzz at fp64 and fp256, the eight systems and the bench programs, 0
refused, all GREEN against libcft's own `seq_ref` output; the references were remade here and their sha256 equal
GPU-A's captured sums (MEASURED, by `sha256sum`); the refusal of `augmentedAddition` by name is printed
unchanged. Rate (not a GPU figure): fp256 FMA, 1M lanes, 10 reps, **1.62e7 FMA/s** kernel median on the CPU
device, 61.8 ns a lane.

### 4.4 The bundle for the card, and its rehearsal

`make_bundle.sh` builds in cft-gpu (the same Ubuntu 24.04 and glibc as the box) everything the Arc needs into
one 127 MB tarball: the binaries (SPIR-V inside), chipStar's `libCHIP.so` (26 MB; MEASURED `ldd`: it needs only
libOpenCL, libstdc++, libm, libgcc, libc), the planted builds, the corpora and `arc_run.sh`. The box then needs
no compiler, no LLVM and no chipStar. How the inputs are made (MEASURED, in cft-gpu): `gen_corpus.py conformance OUT` and `gen_corpus.py stream OUT`
(the conformance files take a second; the streams 130 MB at fp256), `gen_programs.py OUT` (needs python3-mpmath and
python3-pytest, 14 s), and `build_seq.sh ref W` then `W/seq_ref run CORPUS OUT` for each reference file.
The bundle was unpacked in a fresh directory and `arc_run.sh` run on the
PoCL CPU device: rc 0, "ALL AS EXPECTED" (captured/arc_run-rehearsal-pocl.txt). Only the ICD, `CHIP_DEVICE_TYPE`
and the card change on the box.

## 5. Hands-on, Apple, as far as it goes without a Mac

5.1 **Nothing in cft-gpu or on Windows compiles to Metal.** The `metal` compiler is Apple's and closed;
Windows-hosted tools need a developer-account download (READ), which is outside the sources I may install from.
So no compile-only Metal check was possible, and none is claimed.

5.2 **Why chipStar's SPIR-V cannot go to Metal through SPIRV-Cross (MEASURED).** The SPIR-V chipStar made
from `cft_fma.hip` is, by two methods (MEASURED 20:34, same source and flags): **428,976 bytes** as the translator wrote it
(`hipcc --save-temps`, the file `cft_fma-hip-spirv64-generic.out`), and **372,272 bytes** as `spirv-extractor` (chipStar's tool)
pulls it out of the linked binary `cft_fma`; the capabilities are the same in both: `OpCapability Kernel`, `OpMemoryModel Physical64 OpenCL`.
`spirv-cross --msl` on it prints "SPIRV-Cross threw an exception: Kernel capability not supported."
(SPIRV-Cross 2021.01.15 from Ubuntu; an old build, so a newer one might differ: BELIEVED not). `spirv-val
--target-env vulkan1.3` rejects it on the addressing model. It validates clean under the OpenCL environment.
The Vulkan route needs the *Shader* flavour, which chipStar's OpenCL path does not emit.

5.3 **The Vulkan-on-Metal chain** that could keep the one source is chipStar's native Vulkan backend (READ,
experimental, LLVM 24 or later) running on KosmicKrisp or MoltenVK. Not shown to exist for Apple, not run.

5.4 **The device copy as OpenCL C 1.2 (MEASURED, syntax only, nothing run)**
([gpu-c/ocl_c12_check.sh](gpu-c/ocl_c12_check.sh), captured/ocl_c12_check.txt): `clang -x cl -cl-std=CL1.2
-target spir64`, with a scratch `stdint.h` and `string.h` shim. `bigint.c` compiles with **no error**. `softfloat.c`
had 10, from three causes: the format table needs `__constant` (two lines); `half` is a type name in OpenCL C and
libcft uses it as a variable (one function); and the table's `name` string must be `__constant char *`. With those
three edits `softfloat.c` compiles clean. These are edits to a *scratch copy*; they are not in libcft and not
in devcopy.py. What this shows: the arithmetic is nearly OpenCL C already. What it does not show: that it runs, that
Apple's compiler accepts it, or that callers passing `&cft_sf_formats[i]` (a `__constant` pointer) to private
parameters compile (they do not; a private copy is needed) (BELIEVED).
The same text would also run on Intel through its own OpenCL (NEO) without chipStar (BELIEVED; not run).

5.5 **The device copy as MSL.** MEASURED, the copy has 65 function definitions, 82 lines with a pointer
parameter or declaration, no recursion, no function pointer, no goto, no 128-bit integer. MSL needs an address
space on each pointer (BELIEVED), so a scripted edit, a sibling of devcopy.py's E1, is required. Not written.

## 6. Integer support and what blocks bit exactness

- **64-bit integers:** the SPIR-V needs only Int64 (and Int8); the copy has no floating-point arithmetic of its
  own to keep exact (BELIEVED, from GPU-A). MEASURED on PoCL; on an Intel GPU, IGC lowers 64-bit integer multiply (BELIEVED, to be settled by the run).
- **Stack or local memory, about 4.5 KB a lane:** PoCL put no limit on it (MEASURED). On an Arc each lane's private
  array becomes scratch memory (BELIEVED); the runbook says what a failure there looks like.
- **Rounding and flags:** the copy is integer code (BELIEVED, from GPU-A), so a floating-point contraction or
  fast-math setting has nothing to change; GPU-A's hazard runs were not repeated here.
- **What blocks exactness by route:** chipStar (nothing found; the plants are red); SPIR-V through a Vulkan driver
  (shaderInt64 must be present: not read for KosmicKrisp or MoltenVK); WebGPU (no 64-bit integer: a rewrite); SYCL
  and the rest (a rewrite, which would need its own proof).

## 7. The runbooks (in gpu-c/)

[gpu-c/RUNBOOK-ARC.txt](gpu-c/RUNBOOK-ARC.txt): the card, the install list for amd-arc-box with sizes and sums, the
bundle, the run, what a failure means, the removal. **Card recommendation: the A750.** READ: the A750 (56A1) is
supported by the in-kernel i915 driver on Ubuntu 24.04 kernels 6.2 and later; the B580 needs the xe driver and
kernel 6.11 (initial) to 6.12 (full support) (READ by VGPU-C, 2026-11-10, from
https://dgpu-docs.intel.com/overview/supported-hardware/i915-driver-gpus.html and .../xe-driver-gpus.html: A750 (56A1) initial
"Kernel 6.0", full "Ubuntu 24.04+ (6.2)"; B580 (E20B) initial "Kernel 6.11", full "Ubuntu 24.04+ (6.12)"; the pages call them
guidance only, vendor kernels may include backported support); the box ran kernel 6.8.0-139 (docs/BENCHMARKS.md:67, a
record of 2026-09-08, not re-checked). A B580 would
need a new kernel on the box that hosts the U50, whose XRT modules follow the kernel. Install default: **nothing
system-wide**, five Canonical packages (15.6 MB) extracted in a home directory. [gpu-c/RUNBOOK-M2.txt](gpu-c/RUNBOOK-M2.txt):
facts to collect, the compile-only Metal test once the edit exists, the CPU leg, the Vulkan probe.

## 8. Recommendation (mine)

| target | route | cost (ESTIMATE, basis) | one source? |
|---|---|---|---|
| **Intel Arc** | chipStar + packaged clang-22 + wrapper + NEO OpenCL, via the bundle | the lead's time on the box about 1 to 2 hours plus the card swap; basis: the same bundle ran in about 2 minutes on a CPU device, builds took 3 minutes | **yes**, MEASURED up to the card |
| Intel, fallback | the OpenCL C text (5.4) with a new OpenCL host harness | 2 to 4 days; basis: cft_fma.hip is 863 lines (wc), most of it harness (BELIEVED), which a new host API must repeat | text yes, harness new |
| Apple, first | the probe runbook A to D; chipStar's Vulkan backend on KosmicKrisp if the reading in D says it can | the probe about half a day; a Vulkan build could not be priced (LLVM 24, unread) | yes if it works |
| Apple, then | OpenCL C 1.2 text on Apple's deprecated OpenCL, new host harness | 2 to 4 days, and the platform is deprecated | text yes, harness new |
| Apple, third | MSL by a scripted edit (E2) and a Metal host harness in Swift or Objective-C++ | 3 to 6 days | text yes, harness new |
| not recommended | SYCL (DPC++, AdaptiveCpp), SYCLomatic, WebGPU | a rewrite of the arithmetic and its proof | **no, a second implementation** |

One observation for planning: an OpenCL C harness would serve the Arc (NEO), a Mac (Apple's OpenCL), PoCL on any
CPU, and AMD or NVIDIA OpenCL as well (BELIEVED; none of these was run), with one edit set. chipStar is the cheaper route for Intel today only
because the HIP harness already exists.

## 9. Questions for Logan

1. The **A750** for the Arc run, with the kernel and XRT left alone? A power cycle of amd-arc-box for the swap
   (the U50 comes back with it) is yours to allow, in the daytime.
2. Intel's runtime from **Canonical's archive** (23.43, December 2023, no third-party repository), and newer
   from Intel only if that one fails?
3. Is **a toolchain wrapper** (two argument changes, no patched LLVM) an acceptable recipe, or should the study's
   next step build chipStar's patched LLVM 22 (ESTIMATE 60 to 120 minutes at -j4, not run, needs the lead's word)?
4. For Apple, does a **second host harness over the same arithmetic text** count as keeping the one source, or
   only the CPU leg and the Vulkan route?
5. Is the M2 Pro probe (A) worth its half hour before any Apple build?

## 10. Not run, not read

Not run: any Intel GPU, Level Zero (chipStar's L0 backend was not built: no loader installed), chipStar's own test
suite, the second kernel (`--kernel fixed`), the `diff` stream, GPU-A's hazard runs and seq builds with
transcendentals, `cft_seq` at fp32 and fp128, anything on a Mac, clspv, MoltenVK, KosmicKrisp, AdaptiveCpp,
DPC++, SYCLomatic, wgpu. Not read: dgpu-docs' client install page (my fetch returned nothing), Intel's graphics
PPA, Apple's MSL specification (over 10 MB), AdaptiveCpp's backend list, chipStar's Vulkan backend page, any
chipStar issue list. Three pages give three LLVM ranges for chipStar: the releases page for v1.3.0 prints 20, 21, 22; the README at the v1.3.0
tag (as the lead read it) prints 18, 19, 20, and docs/MacOS.md at that tag "18, 19, or 20 with patches", tested at 19.0;
the README on `main` prints 21, 22, 23. Clang 22 (unpatched, with the wrapper) worked for this kernel, which is outside
the tag's README range; the study does not say it is supported.

## 11. Record and removal

Ledger: Data/runs/2026-11-10-gpu-a/ledger/GPU-C.md (every install and read). Remove, in cft-gpu, as root:
`rm -r /opt/gpu-c /etc/opt/gpu-c /root/gpu-c /usr/lib/llvm-22/bin/llvm-spirv`;
`rm /etc/apt/sources.list.d/gpu-c-llvm22.list /etc/apt/keyrings/gpu-c-apt.llvm.org.asc`; `apt-get update`;
`apt-get purge clang-22 clang-tools-22 llvm-22-dev libclang-22-dev libclang-cpp22-dev lld-22 python3-mpmath
spirv-cross` and `apt-get autoremove` (reviewing what it lists: ninja, spirv-tools, clinfo and the OpenCL headers
are small and harmless to keep). Disk after: /opt/gpu-c 86 MB, /root/gpu-c about 1.4 GB (sources, corpora, bundle).

## 12. Files

[gpu-c/](gpu-c/): `install_desktop.sh`, `llvm-spirv-wrapper.sh`, `build_chipstar.sh`, `run_chipstar.sh`,
`run_seq_chipstar.sh`, `make_bundle.sh`, `arc_run.sh`, `ocl_c12_check.sh`, `RUNBOOK-ARC.txt`, `RUNBOOK-M2.txt`,
`captured/`. GPU-A's `devcopy.py`, `cft_fma.hip`, `cft_seq.hip`, `run_checks.sh` and `gen_*.py` are used as they are.
