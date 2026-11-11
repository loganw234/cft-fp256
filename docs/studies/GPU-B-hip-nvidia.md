# GPU-B: what bringing HIP's NVIDIA platform back to the official build would involve

Study GPU-B, written 2026-11-10 by a study author (Sonnet 5.5) at Logan's word,
as the third leg of his answer on study GPU-A's NVIDIA leg: "see what would be
involved in bringing nvidia support back to the 'official' build (just a study
incase it could be significant work)". Branch `gpu-b` from `e6bfd38e`
(GPU-A's tip). Its scripts and captured outputs are in `studies/gpu-b/`.
Nothing outside `studies/` and the index was changed. Nothing was posted,
opened or commented anywhere; the web was only read.

Every figure is marked: **MEASURED** (run here), **READ** (a file, a page or a
tool, with where; web pages were read on 2026-11-10), **COMPUTED**,
**ESTIMATE** (a judgment, with its basis) or **BELIEVED** (taken on trust).
"Not run" means not run.

## The answer

**It is not significant work to build; it is real work to keep and to ship.**

- **The NVIDIA platform was not removed from ROCm 10.1's sources. It was left
  out of the release.** ROCm's CMake, headers, hipcc's NVIDIA mode and an AMD
  CI job for it are all still in the 10.1 tag. What is gone is the packaging
  and the documentation. READ, section 1.
- **MEASURED: HIP 7.16.26385 for NVIDIA assembles from the 10.1 sources in
  about 6 minutes wall (16:50 to 16:56) with one change.** The sources are
  `rocm-systems` tag `therock-10.1` and `llvm-project` tag `therock-10.1`; the
  builds are ROCm's own CMake; the change is C1, thirteen lines wrapped in
  `#if CUDA_VERSION >= 13010`, for CUDA 12.9 (section 3).
- **MEASURED: the result is bit for bit GPU-A's.** `toolchain_check` passes on
  the RTX 5060 Ti with 0 of 1,048,576 lanes wrong, and the fp256 conformance
  corpus is GREEN with sha256 `da932116...a9`, the hash in GPU-A's captured
  runs, by both the plain-nvcc build and the build through the hipcc made
  from source.
- **What stays broken in 10.1: hipcc's NVIDIA mode.** GPU-A's hazards N1 to N3
  (`--offload-arch` passed to nvcc, the `.hip` suffix, `-isystem` dropped with
  `-x`) reproduce unchanged in the hipcc built from the 10.1 source, and
  `gcnArchName` is still unwritten (section 3).
- **AMD says, in its own CI file, that it will not ship CUDA-based
  artifacts** (section 1). That makes "AMD ships the NVIDIA packages again"
  the least likely of the three ways to "official", and the cheapest ways the
  ones that do not need AMD (section 4).
- **Recommendation (mine):** do not fork. Keep the study header as the
  dependency-free NVIDIA leg and the pinned recipe of this study as the check
  that the same source also goes through real HIP (section 5).

## 1. What was dropped, when and why

| # | finding | mark and source |
|---|---|---|
| 1 | ROCm 10.1 (HIP 7.16.0) was released 2026-10-05. Its release notes do not mention the NVIDIA platform, hipother or hipcc-nvidia, in the 100,000 characters read of 147,077. | READ, rocm.docs.amd.com/en/docs-10.1.0/about/release-notes.html. The last 47,077 characters: not read. The page does mention CUDA backends of libraries (hipSPARSE, hipFFT); those are not the HIP NVIDIA platform |
| 2 | Since ROCm 7.14 ROCm is built and released through TheRock. Its transition guide lists what was removed or moved (ROCm SMI, the bandwidth test, ...), the `amdrocm-` package names, HIPCC into `amdrocm-llvm`. It does not mention NVIDIA, hipother or hipcc-nvidia. | READ, rocm.docs.amd.com/en/docs-7.14.0/about/transition-guide-TheRock.html; github.com/ROCm/TheRock/wiki |
| 3 | TheRock never builds the NVIDIA platform: at tag `therock-10.1` (`b324869f`) it passes `-DHIP_PLATFORM=amd` in three places and has no `HIPNV_DIR`; the one use of hipother is a test-selection map. | READ, TheRock `core/CMakeLists.txt` lines 298, 364, 586; `test_tools/determine_rocm_test_dependencies.py:110` |
| 4 | The new packaging (amdrocm 10.1.0-3, repo.radeon.com/rocmradeon/apt/26.16) has no hipcc-nvidia, hip-runtime-nvidia or hipother; the last release packaging them is 7.2.4 (repo.radeon.com/rocm/apt/7.2.4). I did not re-read the repositories. | READ by GPU-A (docs/studies/GPU-A-hip.md, section 3) |
| 5 | The documentation went before the packages: HIP's install page for 6.4.1 has an NVIDIA section (`hip-runtime-nvidia`, `hip-dev`, `HIP_PLATFORM=nvidia`); the pages for 7.2.4 and 7.16.0 have none, and say HIP installs on AMD platforms. The pages between 6.4.1 and 7.2.4 were not read. | READ, rocm.docs.amd.com/projects/HIP/en/docs-6.4.1, docs-7.2.4, latest (install/install.html) |
| 6 | HIP's own 10.1 index describes HIP as designed for AMD GPUs, while its CONTRIBUTING still describes portable applications for AMD and NVIDIA GPUs. | READ, `projects/hip/docs/index.md:9`; `projects/hip/CONTRIBUTING.md:27` |
| 7 | **The build option is not dropped.** `clr/hipamd/CMakeLists.txt` still has `HIP_PLATFORM=nvidia` (runtime `cuda`, compiler `nvcc`, a required `HIPNV_DIR`), `hip-config-nvidia.cmake.in`, and a CPack component `runtime-nvidia` (package `hip-runtime-nvidia`, depends on `cuda (>= 7.5), hipcc-nvidia`). `amd/hipcc` still defines the `hipcc-nvidia` package. | READ and MEASURED (section 3) |
| 8 | **The CI is not dropped; it was added.** PR #5864 "Add nvidia build", merged 2026-06-23, adds `.github/workflows/hip-nvidia-ci.yml`. It configures and builds clr and hip-tests for `HIP_PLATFORM=nvidia` in an `nvidia/cuda` 13.2.0 devel container pinned by digest, with hipcc's `hipconfig` built from `amd/hipcc` and **nvcc symlinked as `hipcc`**. It has no test step: nothing runs on an NVIDIA GPU. The author means it to become a required check. | READ, github.com/ROCm/rocm-systems/pull/5864; the workflow file at tag `therock-10.1` |
| 9 | **Why** (AMD's words, in that workflow's first lines): the NVIDIA build is kept apart from TheRock's CI because "We do not want to publish any CUDA based artifacts." and because the CLR builds neither consume nor affect the rest. No announcement of dropping the packages was found in the release notes, the transition guide, the install pages or two web searches. | READ for the comment; the announcement: not found. That the packages stopped for that reason is BELIEVED |

So, exactly: **gone** are the apt/rpm packages for the NVIDIA platform (from
the TheRock-based releases), the NVIDIA install documentation, and any word about it
in the part of the 10.1 release notes that was read (row 1). **Kept** are the source, the CMake option, the
CPack definitions, the headers, hip-tests' NVIDIA support (71 uses of
`__HIP_PLATFORM_NVIDIA__` in `projects/hip-tests`, MEASURED by grep; its README
defines `HT_NVIDIA`), and a compile-only CI.

## 2. Where the NVIDIA code lives and whether it is kept

| piece | where | last change, branches and tags | kept? |
|---|---|---|---|
| nvidia_detail headers (14 files, 6,268 lines, MEASURED) | `rocm-systems/projects/hipother/hipnv/include/hip/nvidia_detail/` | newest commit 2026-11-05 (#14463); 20 commits to that path since 2026-05-20, nearly all adding HIP APIs to the NVIDIA runtime header; "Add nvidia build" 2026-06-23; a missing `nvidia_hip_cooperative_groups_scan.h` added 2026-06-26. READ, the path's commit pages | **Yes, actively**, by the people adding HIP APIs |
| the hipother repository | github.com/ROCm/hipother | README: **retired**; `develop` takes only a bot's mirror of rocm-systems. 90 refs; the newest tag is `rocm-7.2.4`, none for 7.14 or 10.x; the newest release branch is `release/rocm-rel-7.2` (MEASURED, `git ls-remote`). The 7.2.4 tag's content is of 2025-11-04, so it is behind its own release | mirror only; the home is rocm-systems |
| HIP's include tree | `projects/hip/include/hip/` | `hip_runtime.h` picks `nvidia_detail/nvidia_hip_runtime.h` when `__HIP_PLATFORM_NVIDIA__` is defined (READ line 37 ff.); `hip_version.h` is generated by clr's CMake | yes |
| clr / hipamd CMake and packaging | `projects/clr/hipamd/CMakeLists.txt`, `packaging/CMakeLists.txt` | whole tree tagged `therock-10.1` at `7da43026` (2026-09-25). `rocm-systems` has tags `rocm-7.1.0` to `rocm-7.2.4` and `therock-7.x`, `therock-10.0`, `therock-10.1` (MEASURED) | yes, and exercised by the CI of row 8 |
| hipcc's NVIDIA mode | `llvm-project/amd/hipcc/src/hipBin_nvidia.h` (631 lines, MEASURED). The old `ROCm/hipcc` repository ends at tag `rocm-6.0.2` (MEASURED) | the file's last change is **2025-07-11** (an `-isystem` for nvcc on Windows); 18 commits since 2021 (READ, its history page). The directory itself had 20 commits to 2026-11-05, none about NVIDIA by title (READ) | **dormant for 16 months**; the CI does not use it as a compiler (it symlinks nvcc) |
| tests | `projects/hip-tests/catch` | NVIDIA branches throughout (71 uses) | yes, built by the CI, not run |

BELIEVED: the CI's hipcc-less design (a symlink for `hipcc`) is why the
hipcc NVIDIA mode can rot without a red check; section 3 shows it has.

## 3. The build by hand

Everything below ran in the WSL distro `cft-gpu` (CUDA 12.9.86), into the
prefix `/opt/gpu-b`; `/opt/rocm-7.2.4` was not touched. Scripts:
`studies/gpu-b/`. The ledger names every clone, its commit and size.

**Sources** (all shallow, from github.com/ROCm; a git tag has no published
sum, so the commit id is the pin):
- `rocm-systems` tag `therock-10.1` = `7da43026e4f2` (sparse: `projects/hip`,
  `clr`, `hipother`, later `hip-tests`, `.github/workflows`; .git 86 MB);
- `llvm-project` tag `therock-10.1` = `d6f6cb691863` (sparse `amd/hipcc` as the
  lead asked: .git 29 MB, tree 308 KB, 10 s);
- `TheRock` tag `therock-10.1` = `b324869fb311` (read only), and `hipother` tag
  `rocm-7.2.4` = `e56867449451` (for a diff only).
- Installed in cft-gpu from Canonical: `cmake` 3.28.3 (it had none).

**Steps, with their errors** (the study's evidence of the work; clock times are
`date` on this desktop):

| # | what | result | change needed |
|---|---|---|---|
| E1 | `nvcc -x cu -D__HIP_PLATFORM_NVIDIA__ -I<hip>/include -I<hipnv>/include` on `toolchain_check.hip`, straight from the source tree (the lead's first test) | **1 error**: `hip/hip_version.h` not found. The header is generated by clr's CMake, not in the tree | run the CMake (E2); no source change |
| E2 | `build_hip_nv.sh`: clr's own CMake, `-DHIP_PLATFORM=nvidia -DCLR_BUILD_HIP=ON -DHIP_COMMON_DIR -DHIPNV_DIR -DHIPCC_BIN_DIR=`, then build and install | configure rc 0 (52.3 s, nearly all git), build rc 0, install rc 0, 117 files; `hip_version.h` says 7.16.26385, the RX 7600's HIP | **none** (the CI's recipe works without the hipcc dir) |
| E3 | the same nvcc line against `/opt/gpu-b/include` | **30 errors**, all in `nvidia_hip_runtime_api.h`: `cudaExecutionContext_t`, `cudaDevResource*`, `cudaDevSmResource*`, `cudaGreenCtxCreate`, `cudaExecutionCtx*` and the other green-context names (lines 468 to 488, 3661 to 3728), and `cudaErrorStreamDetached`/`CUDA_ERROR_STREAM_DETACHED` (lines 1190, 1322, 1455, 1651) | **C1**: `patch_cuda12.py` wraps those 6 pieces of the *installed copy* in `#if CUDA_VERSION >= 13010` (13 lines added; the script keeps the original beside it as `<header>.orig`, a line added in send-back 1; the first run, before that line, had the copy made by hand). READ: 7.2.4's hipother has none of these names (0 `cudaExecutionContext_t`), AMD's CI uses CUDA 13.2 |
| E4 | after C1, `toolchain_check.hip` and GPU-A's `cft_fma.hip` (`build.sh plain`, sm_89 + sm_120, `-Xptxas -v`) | **0 errors**; warnings only: `HIP_GET_PROC_ADDRESS_*` redefined (3 macros, from the CUDA headers), CUDA deprecations (`captured/plain-build.txt`) | none |
| E5 | `build_hipcc.sh`: `amd/hipcc`'s own CMake | rc 0 x3; `hipcc`, `hipconfig` installed; 32 compiler warnings, not read; 2 CMake warnings (`DEB_TIMESTAMP` newline) | none |
| E6 | `hipconfig --platform/--compiler/--version`; `hipcc --version` | `nvidia`, `nvcc`, `7.16.26385-7da43026e4`; it runs nvcc 12.9 | none |
| E7 | `hipcc_probe.sh`: five command lines through the new hipcc (`captured/hipcc-probe.txt`) | **N2 reproduced**: `hipcc -O2 -c x.hip` fails, nvcc "Don't know what to do with" the `.hip` file; **N1 reproduced**: `--offload-arch=sm_89` reaches nvcc, "Unknown option"; **N3 reproduced**: with `-x cu` hipcc's `-isystem` is gone and `hip/hip_runtime.h` is not found; GPU-A's line (`-x cu -isystem <hip>/include -gencode ...`) compiles, rc 0 | none for the harness (GPU-A's line); fixes for N1 to N3 are section 4 (b) |
| E8 | `build.sh hipcc`: `cft_fma.hip` and `toolchain_check` through the new hipcc with GPU-A's line | rc 0 | none |
| E9 | `pack_deb.sh`: the sources' own CPack | **`hipcc-nvidia` 1.1.1.99999-local, `hip-runtime-nvidia` and `hip-dev` .deb files are generated** (not installed). `hip-runtime-nvidia` depends on `cuda (>= 7.5), hipcc-nvidia`; **`hip-dev` depends on `rocm-llvm, hsa-rocr-dev, hipcc, hip-runtime-amd`** (`captured/debs.txt`): the very dependency GPU-A had to unpack around with `dpkg -x` | none to make them; the dependency would need relaxing (ESTIMATE in section 4) |

**The runs** (16:56:06 to 16:56:12 by `date`; `nvidia-smi` before each: no
compute process on either card; the RTX 4070 showed 20 to 44 % utilisation
with no compute application listed; the run used CUDA device 1 only;
`captured/gpu-run.txt`):
- `toolchain_check` built by plain nvcc against `/opt/gpu-b` and by the new
  hipcc: both `HIP_VERSION 71626385` (COMPUTED: 7 x 10^7 + 16 x 10^5 + 26,385),
  RTX 5060 Ti, cc 12.0, 0 of 1,048,576 lanes wrong, PASS. MEASURED.
- `cft_fma check conf-fp256.bin --device 1`, both builds: 18,360 cases, 0
  results and 0 flags differ, sha256 `da932116555557bef8fcd6980da18963b1420bfc892163c67b32d1cc53a2eba9`,
  the hash of GPU-A's `captured/desktop-checks.txt` for the 5060 Ti (READ) and
  of the CPU legs; `gen_corpus.py verify` agrees. MEASURED. The corpus file's
  own sha256 `8c903f53...` matches `captured/corpus.sha256` (MEASURED).
- GPU time in all: about 6 s of wall for the four runs.

**One thing the run showed that GPU-A's note predicts:** in the plain-nvcc
`toolchain_check` the printed `arch` is garbage bytes, in the hipcc one it is
empty. `gcnArchName` is declared in the common `hipDeviceProp_t` ("HIP Only")
and nothing in hipother writes it (MEASURED: `grep` finds no assignment in
`projects/hipother`). The harness does not use it; any tool that does would
read an uninitialised string on NVIDIA. BELIEVED cause: the field is not set
by the NVIDIA `hipGetDeviceProperties`; I did not read that function.

**Drift** (MEASURED, `captured/hipother-7.2.4-vs-10.1.txt`): hipother's
`nvidia_detail` from tag `rocm-7.2.4` to `therock-10.1`: 12 to 14 files
(`nvidia_hip_cooperative_groups_reduce.h` and `_scan.h` new), 6,059 to 6,268
lines, 365 lines added and 202 removed (about 9 % of the file set in about a
year of releases), all 12 old files differ and 2 are new.

## 4. What "official" would take

"Official" has three readings; the estimates are mine and each states its
basis. Hours are of one engineer who has read this study.

**(a) A local recipe: done.** What step 3 gives: `build_hip_nv.sh`,
`build_hipcc.sh`, `patch_cuda12.py`, `build.sh`, `gpu_run.sh`, pinned to two
tags. MEASURED: about 6 minutes from first clone to a passing card run, about
180 MB of clones and trees, no root but the one `apt install cmake`. Remaining cost:
each ROCm release needs a re-pin and a re-run; ESTIMATE 1 to 2 hours (basis:
the six minutes, plus reading 10.1's diff if the build breaks; 7.2.4 to 10.1
changed 9 % of the headers and broke only on a CUDA-version mismatch).
**With CUDA 13.1 or later C1 is BELIEVED unnecessary** (AMD's CI builds the
same headers on 13.2); not run: no CUDA 13 here, and a further CUDA version
needs the lead's word.

**(b) A fork kept in step with ROCm's releases, packaged.** What it adds to
(a), with ESTIMATE and basis:
1. hipcc N1 to N3: three places in `hipBin_nvidia.h` (631 lines): the
   argument loop keeps `--offload-arch=`/`--amdgpu-target=` in `toolArgs`
   although it parsed them (about line 437); a `.hip` input sets `hasCU` but
   only `hasCXX` adds `-x cu` (about 548 to 570); the `-isystem` is part of
   `HIPCXXFLAGS` (lines 208, 222), which, BELIEVED from E7, an explicit `-x` bypasses. Plus `gcnArchName`. The
   fixes are tens of lines (READ, from the file); with a test per hazard
   **ESTIMATE 1 to 2 days**. I did not look for existing tests of the file.
2. Packaging that installs without the AMD stack: relax `hip-dev`'s
   `Depends` for an NVIDIA-only build (a CPack variable; BELIEVED, not run),
   and a place to host the .debs (a Debian repository or release assets):
   **ESTIMATE 0.5 to 1 day**, the hosting decision unknown.
3. A job that re-pins, builds, packs, runs `toolchain_check` and the corpus
   on a card per release and per CUDA release: **ESTIMATE 1 day**, then the
   upkeep of (a) per release plus the breaks nobody has predicted. The hardware
   is Logan's own cards, which GitHub-hosted runners do not have.
4. Subtotal for (b): **ESTIMATE 3 to 5 days to set up, 2 to 4 hours a release
   after**, most of the first being N1 to N3, which (b) does not strictly need:
   the harness's workaround line works (E7, E8).

**(c) Upstream** (the packages back in AMD's release):
- *The process* (READ): development is in `ROCm/rocm-systems` `develop`
  (hipother's README sends there; the repo's CONTRIBUTING and HIP's give pull
  request guidelines, an MIT licence header on every file, CODEOWNERS for
  hipother: four AMD handles). hipcc lives in `ROCm/llvm-project`
  `amd/hipcc`; its contribution rules: not read. I opened and posted
  nothing.
- *What AMD already does* (READ): a required-in-intent compile-only NVIDIA CI
  (row 8), active header maintenance (section 2), and the stated unwillingness
  to publish CUDA artifacts (row 9). Issue #7709 (open, labelled `nvidia`) shows
  the CI is a topic of friction inside AMD; READ.
- *So:* the **source-level asks are plausible** (N1 to N3 fixes, a
  `gcnArchName` write; the CI could even use the real hipcc instead of a
  symlink). ESTIMATE 1 to 2 days to write and test, plus review time that I
  cannot estimate. **The packaging ask is unlikely** against row 9: BELIEVED,
  and nothing was asked of AMD.
- *CI on NVIDIA hardware:* AMD's job never runs a kernel (READ). A runtime
  job would need an NVIDIA runner in AMD's infrastructure or a donated one;
  whether AMD wants either: unknown.
- *Unknown:* any AMD statement on whether NVIDIA support will continue past
  the legacy 7.2 stream (none found); whether AMD would accept N1 to N3; the
  review time; whether `hipother` lives on after the monorepo move is complete.

## 5. Recommendation (mine) and questions

1. **Do not fork and do not package.** The official sources already build the
   platform, AMD's CI keeps the headers compiling, and the one break I met was
   a CUDA-version mismatch. A fork buys the N1 to N3 fixes, which the harness
   does not need.
2. **Keep GPU-A's study header as the NVIDIA leg** (no HIP, nothing to
   track) and **keep this study's recipe as the check that the same source
   passes through real HIP on NVIDIA.** Both gave the same hash. The recipe
   is pinned by two tags, so it does not move unless someone moves it.
3. **If a tool ever needs `hipcc` on NVIDIA,** carry N1 to N3 as a small patch
   set against `amd/hipcc` (section 4 (b) 1) and consider offering it upstream
   only with Logan's word.
4. **Watch one thing:** the day `nvidia_detail` needs a CUDA newer than the
   one on the machines. That is the first place the recipe breaks (C1 was it).

Questions for Logan:
- Which "official" did he mean: AMD shipping packages again (unlikely, row 9),
  or building HIP for NVIDIA from AMD's sources (done)?
- May a CUDA 13.x go into cft-gpu, to test that C1 is unnecessary there (a
  download of several GB; the lead's word is needed)?
- Is the recipe wanted as a verification stage (three clones, nvcc, a card;
  skipped by name where absent), or left as a study?
- Is it worth writing the N1 to N3 patch set and its tests (1 to 2 days),
  though the harness does not need it?
- May anyone ask AMD anything (an issue on `rocm-systems` is the route its
  README names)? I did not.

## 6. Not run

- A CUDA 13.x build: none installed. C1's threshold (13010) is BELIEVED, from
  AMD's CI container and the names missing in 12.9; the exact CUDA release
  that introduced them was not read.
- `hip-tests` on NVIDIA, with or without a GPU; the other seven corpora; the
  second (fixed-limb) kernel; the plants; the 2^30 differential; the RTX 4070.
  Only the fp256 conformance corpus and `toolchain_check`, on the RTX 5060 Ti.
- Installing any of the generated .deb files; the dependency relaxation.
- Fixes for N1 to N3 and `gcnArchName`: not written.
- The 32 compiler warnings of the hipcc build; `hipfile-build-nvidia.yml`;
  contribution rules of `llvm-project`; docs pages of HIP between 6.4.1 and
  7.2.4; the last 47,077 characters of the 10.1 release notes.
- compute-sanitizer; anything on AMD hardware or the other machines.

## Appendix: files and commands

`studies/gpu-b/` (run in cft-gpu; each script's header says its use):
`build_hip_nv.sh SRC PREFIX` (E2), `build_hipcc.sh SRC PREFIX` (E5),
`attempt_a.sh PREFIX OUT` (E1, E3), `patch_cuda12.py HEADER` (C1),
`build.sh plain|hipcc OUT 89 120` (E4, E8), `build_tc.sh OUT` (the two `toolchain_check` binaries the runs need), `hipcc_probe.sh PREFIX OUT` (E7),
`pack_deb.sh` (E9), `gpu_run.sh OUT CORPUS 1` (the runs), `collect.sh DEST`
(the scrubbed captures in `captured/`; the configure and clone-size lines are in the ledger only).
Clone commands: `git clone --depth 1 --filter=blob:none --sparse --branch
therock-10.1 <url>`, then `git sparse-checkout set <paths>`.
Web pages read, all on 2026-11-10: the URLs named in the tables above and
github.com/ROCm/hipother, github.com/ROCm/rocm-systems (README and the commit
pages of `projects/hipother`, `projects/hipother/hipnv`),
github.com/ROCm/llvm-project (commit pages of `amd/hipcc` and
`hipBin_nvidia.h`), `rocm-systems/pull/5865` and `/issues/7709`.
