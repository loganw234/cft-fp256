# GPU-A: libcft's arithmetic on GPUs through HIP, one source for ROCm and CUDA

Study GPU-A, written 2026-11-10 by a study author (Opus 5.5) at Logan's word,
for the roadmap's note "Noted 2026-11-10: a GPU backend through HIP (no
dates)" ([ROADMAP.md](../ROADMAP.md)). Branch `gpu-a` from `237806ac`.
Its code, runbooks and captured outputs are in `studies/gpu-a/`. Nothing
outside `studies/` and the index was changed. No backend was built.

Every figure is marked: **MEASURED** (run here, with its command in the
appendix), **READ** (from a file, a page or a tool), **COMPUTED** (arithmetic on
the others), **ESTIMATE** (a judgment, with its basis) or **BELIEVED** (taken on
trust and not checked). "Not run" means not run. It never means passed.

Corrected the same day at send-back 1, after the verifier VGPU-A's first
pass: the second kernel's range by batch size and the RX 7600's step (with
VGPU-A's series), hazards.sh's verdict over a sanitizer leg that did not
run, section 7's list of immediates, and four notes (a one-sided plant, the
two sessions' spread, the package names, the generator's coverage).

**Part 2, programs on the GPU,** written the same day at Logan's word,
follows this part's appendix: libcft's sequencer programs, one thread a
lane, bit for bit on all three cards, and their rates.

## The answer

**One HIP source works on both vendors, bit for bit.** MEASURED, results and
flags, against the golden model, on four devices and two CPU builds:
- the RTX 4070 (sm_89) and the RTX 5060 Ti (sm_120), through HIP 7.2.4 on CUDA 12.9;
- the RX 7600 (gfx1102), through HIP 7.16 on ROCm 10.1;
- one core of this desktop's CPU, running the same device copy and libcft's own C;
- the RX 7600 machine's CPU.

Each was checked on two corpora:
- the conformance vectors' FMA cases: 73,780 cases, every format, all five attributes;
- a seeded stream of 4,000,000 FMAs.

Every output hashes to the golden model's sha256. Three planted faults go
red on every device they were run on. The same source also builds with
plain nvcc and no HIP at all, through a 52-line header of the study's own,
with the same hashes on both NVIDIA cards (section 3).

**What the generic port costs.** The first kernel runs `host/src/softfloat.c`
and `bigint.c` as they are. At fp256 it makes 77 to 175 M FMAs a second,
kernel only (MEASURED). That is 0.18 to 0.41 of the quad's 427 M with
resident data (READ). The top of both ranges is the RTX 4070 in this study's
session; the verifier VGPU-A MEASURED 144 M/s on it (0.34 of the quad), with
the display taking 8 to 19 % of that card (section 8).

**What a specialised kernel reaches.** The second kernel is a second
implementation of the fp256 FMA on fixed limbs in registers. It makes 0.80
to 1.46 G a second, kernel only (MEASURED), 1.9 to 3.4 times the quad, by
device and batch size:
- the RX 7600's 1.38 to 1.46 G/s holds at 1.5M lanes or fewer; it is 1.00 to 1.01 at 2M and 3M lanes and, at 4M, 0.80 (this study's 803 M/s) to 0.83 (VGPU-A's 0.82 to 0.83) (VGPU-A's MEASURED series, section 8), a step whose cause is not known;
- the 5060 Ti makes 0.885 to 0.935 G/s at 1M to 4M lanes, and the 4070 0.94 to 1.08 across the two sessions (section 8).

It is held bit for bit to:
- the same corpora;
- the first kernel, on 2^30 counter-generated hard cases on the 5060 Ti and on the RX 7600, and 2^28 on the 4070, with 0 differing.

End to end, with the operands copied over PCIe on every call, both kernels
fall to 31 to 51 M a second (MEASURED). The transfers, not the arithmetic,
set that figure.

**The roadmap's question.** "That decides whether a backend is worth
building." The answer is yes, on three conditions:
- its fp256 arithmetic is a specialised kernel, held inside the gates to libcft's own code running on the same GPU;
- its data stays on the device, as the card's resident mode keeps it;
- NVIDIA's leg has a HIP that still targets it (section 3).

The generic port alone is not worth a backend at fp256. It is the reference
that makes the specialised kernel trustworthy.

**The roadmap's ESTIMATE** said 10^9 to 10^10 fp256 FMAs a second on a large
GPU. Measured on three mid-range consumer cards:
- the generic kernel reaches 0.8 to 1.8 x 10^8 (the top the 4070's in this study's session, 1.4 in VGPU-A's), an order of magnitude below the ESTIMATE's floor;
- the specialised kernel reaches 0.80 to 1.46 x 10^9 by device and batch, so it straddles the ESTIMATE's floor of 10^9:
  - below the floor: the 5060 Ti (0.885 to 0.935), the RX 7600 at 4M lanes (0.80 to 0.83) and the 4070 in VGPU-A's session (0.94);
  - on it: the RX 7600 at 2M and 3M lanes (1.00 to 1.01);
  - above it: the RX 7600 at 1.5M lanes or fewer (1.38 to 1.46) and the 4070 in this study's session (1.07 to 1.08);
  - nothing reaches 1.5 x 10^9, the bottom sixth of the ESTIMATE's decade on a log scale.

The MI300X would most likely land inside the range for the specialised
kernel (ESTIMATE, sections 8 and 9).

## 1. What was built

All of it is in `studies/gpu-a/` (2,189 lines of code and runbooks, 436 of
captured output).

| file | lines | what it is |
|---|---|---|
| `devcopy.py` | 168 | the scripted copy of libcft's arithmetic for device code, and its check (section 2) |
| `cft_fma.hip` | 754 | the one source: both kernels, the CPU path, the test generator, the harness (`check`, `bench`, `diff`, `info`) |
| `fma256_fixed.h` | 368 | the second kernel: an fp256 FMA on fixed limbs, a second implementation |
| `gen_corpus.py` | 231 | the corpora from the golden model; the bit-flip plant; an independent verifier |
| `build.sh` | 104 | one build line per target: `cpu`, `cpu-libcft`, `nvidia`, `amd`, `cuda` |
| `cudahip/hip/hip_runtime.h` | 52 | the study's own header, not HIP: the harness's HIP names mapped onto CUDA's, for plain nvcc (section 3) |
| `run_checks.sh`, `bench.sh`, `hazards.sh` | 27, 28, 119 | every corpus through one build, the rates, the compilers' hazards |
| `run_wsl_nvidia.sh`, `run_amd.sh` | 108, 84 | the desktop's runbook and the AMD body |
| `run_rx7600.sh`, `run_mi300x.sh` | 29, 61 | the two AMD runbooks |
| `toolchain_check.hip` | 56 | the smallest program that proves a toolchain and device |
| `captured/` | 436 | the corpora's sums, the expected outputs' sums, the final runs' summaries, send-back 1's reruns |

**The harness.** It is one source compiled four ways:

| target | compiler | arithmetic |
|---|---|---|
| CPU | `g++ -x c++` | the device copy, with `CFT_HD` empty |
| CPU, libcft's C | `cc` on `host/src` | libcft's own C, linked under the same harness |
| NVIDIA | `hipcc` with `HIP_PLATFORM=nvidia` | the device copy |
| AMD | `hipcc` with `HIP_PLATFORM=amd` | the device copy |

A lane does what `device.c`'s software loop does for one element:
`cft_bn_load` three operands, `cft_sf_compute(f, CFT_SF_FMA, rnd, ...)`,
`cft_bn_store`, with the attribute given per lane. One thread is one lane.

A lane whose `cft_sf_compute` refuses writes d = 0 and flags 0x80, so a
refusal is a difference and never a silent pass. The output file is d ||
flags, in the corpus's own layout. The harness compares it with the golden
model's and hashes it with libcft's own `host/src/sha256.c`, built as it is
at the library's own `CFT_ERRMSG_MAX=1` profile. `gen_corpus.py verify`
compares it again and hashes it with Python's hashlib.

**The corpora** (`gen_corpus.py`; no vector file committed, their sums in
`captured/corpus.sha256` and `captured/expect.sha256`):

- *Conformance.* `vectors/gen_vectors.py` at `make vectors`' counts makes the
  twenty elementwise sets: `--directed 3000 --random 4000 --simple 200`, seed 3.
  Each set's sha256 equals its line in `vectors/SHA256SUMS`, or the generator
  refuses (MEASURED). The `"op": "fma"` lines are 18,435, 18,440, 18,545 and
  18,360 cases at fp32, fp64, fp128 and fp256, a fifth under each attribute,
  73,780 in all. They took 3.8 s with two workers (MEASURED).
- *The seeded stream.* 200,000 FMA triples a format from the golden model's
  own adversarial strategies (`vectors.random_cases`, seed 20261110 plus the
  format code): alignment sweeps, near-total cancellation, both range edges,
  ties and raw bits. Each triple runs under all five attributes, with the
  expected value from `softfloat.fma`. That is 4,000,000 golden FMAs in 49.8 s
  on two workers (MEASURED). The model takes 7.5, 9.0, 11.6 and 33.3 µs an FMA
  at fp32, fp64, fp128 and fp256 in one process (MEASURED).
- *The differential stream* (the second kernel only, section 6): a
  counter-based generator in the source. Lane i of seed S is one case on every
  device and on the CPU, and nine families weight it to the hard cases.

## 2. One source of arithmetic, not two

**The route is the scripted copy, not clang's pragma.** HIP's NVIDIA
platform compiles with nvcc, which has no
`#pragma clang force_cuda_host_device`. A copy also lists the edit a backend
round would make in `host/src` behind a macro.

`devcopy.py` copies five files:
- `host/src/bigint.h`, `bigint.c`, `softfloat.h` and `softfloat.c`;
- `host/include/cft_config.h`, unedited, so that `bigint.h`'s `"../include/cft_config.h"` resolves inside the copy.

It applies one edit kind and refuses a copy that differs in anything else,
naming the line, at every build.

**E1, the only edit: `CFT_HD ` before every function declaration and
definition at file scope.** That is 105 lines: 24 in `bigint.h`, 26 in
`bigint.c`, 16 in `softfloat.h` and 39 in `softfloat.c` (MEASURED).
- The including file defines `CFT_HD` as `__host__ __device__` on a GPU build and as empty on the CPU build, so the CPU build compiles the original text.
- Declarations carry it too, because a redeclaration in another execution space is an error in nvcc and an overload in clang.
- The check derives every edited line from its original, refuses an unedited E1 line, refuses an added or removed line, and compares the whole copy byte for byte.
- `devcopy.py --selftest` plants four faults (an operator changed, an E1 missing, a line added, a body edited). Each is refused by name on this desktop and on the RX 7600 machine (MEASURED).
- The originals' git blob ids are printed at every build (`softfloat.c` 09e9830b..., `bigint.c` 14088c5a...). They equal `237806ac`'s.

**What did not need an edit.** Each item below was checked by compiling,
running and reading:
- **The tables.** `cft_sf_formats` and its `const char *name` stay host data. The host passes the descriptor to the kernel by value, and no device path reads the name.
- **C as C++.** No cast, initialiser or `void *` conversion needed changing. `g++ -Wall` compiles the copy as C++ with no warning (MEASURED). The copy has no `memcpy` and no builtin: `u32_bitlen` is a loop.
- **`long` and `size_t`.** The only `long` is `1uL << 28` in `seed_recip_entry`, which fits 32 bits on either data model. `size_t` appears only in the reduction tree and the canonical ranges, which the FMA never reaches.
- **Recursion.** `cft_sf_reduce` recurses and carries E1 like everything else. Neither compiler complained, and neither kernel reaches it: AMD reports "Dynamic Stack: False" and ptxas a static frame (MEASURED).
- **Shift counts.** Each shift in `bigint.c` is guarded against a count of 32 or more. UBSan ran over all 4,073,780 cases with no report (section 5).

**What a backend round would change in `host/src`:** the same 105 lines
behind a `CFT_HD` macro defined in a header, empty unless a GPU compiler
includes it (ESTIMATE: 105 one-token edits and a ten-line header; no other
file).

## 3. One HIP source on two vendors

**The source has no platform `#ifdef`.** Four preprocessor switches exist,
each named in the source's header comment:
- `CFT_GPUA_CPU` drops HIP for the CPU build;
- `CFT_GPUA_LIBCFT_C` links libcft's C instead of the copy;
- two plants, `CFT_GPUA_PLANT_RMM_AS_RNE` and `CFT_GPUA_PLANT_DROP_FLAG`.

No line tests which GPU vendor it is compiled for.

**The build lines differ** (MEASURED, `logs/tc_nvidia.log`, the ledger):
- AMD: `hipcc --offload-arch=gfx1102` works as documented.
- **N1:** on NVIDIA, HIP 7.2.4's `hipcc --offload-arch=sm_89` hands the flag to nvcc: "nvcc fatal : Unknown option '--offload-arch=sm_89'". The NVIDIA line says `-gencode arch=compute_89,code=sm_89` instead.
- **N2:** nvcc does not know the `.hip` suffix: "nvcc fatal : Don't know what to do with 'toolchain_check.hip'".
- **N3:** given `-x cu` to fix N2, hipcc drops its own `-isystem`: "fatal error: hip/hip_runtime.h: No such file or directory".

The working NVIDIA line is
`hipcc -x cu -isystem $HIP_PATH/include -O2 -gencode ...`. The same bytes
copied to a `.cpp` name also build, because hipcc adds `-x cu` and the
`-isystem` for `.cpp`. `build.sh` uses the first form, so there is no copy to
keep equal.

**A runtime quirk.** On NVIDIA, HIP 7.2.4's `hipGetDeviceProperties` does not
write `gcnArchName`, and stack garbage printed as the architecture
(MEASURED). The harness zeroes the struct and tells an AMD device by a "gfx"
name, not by a platform test.

**HIP's NVIDIA platform ends at ROCm 7.2.4** (READ 2026-11-10, the ledger
holds the listings):
- The RX 7600 machine runs ROCm 10.1 in AMD's new `amdrocm` packaging (`repo.radeon.com/rocmradeon/apt/26.16`). The index of that repository's `pool/main/a/`, the one directory read (15:10), lists no package whose name contains `nvidia`, `hipcc`, `hip-` or `hipother`. That is a statement about package names, not about the compiler: a `hipcc` is present on the RX 7600 machine, outside dpkg's records (`dpkg -S /usr/bin/hipcc` finds no package: READ by the lead), and this study's AMD builds ran a `hipcc` there (HIP 7.16.26385).
- HIP's current install page (HIP 7.18, ROCm 10.1's documentation) no longer mentions NVIDIA.
- The last release that packages the NVIDIA platform is 7.2.4 (`repo.radeon.com/rocm/apt/7.2.4`: `hip-runtime-nvidia`, `hipcc-nvidia`).

So the NVIDIA leg runs HIP 7.2.4 and the AMD leg HIP 7.16. The source is the
same, and its results and hashes are the same on both.

How one source on CUDA survives this:
- **(a) HIP 7.2.4, frozen,** is what was installed and what works today. It is three .debs, 0.6 MB, header-only on NVIDIA.
- **(b) A study header of its own, built** (52 lines, `cudahip/hip/hip_runtime.h`, every line written for this study and copied from nothing). Under the name `hip/hip_runtime.h`, so the unchanged source finds it, it maps 27 names onto CUDA's:
  - three types (`hipError_t`, `hipEvent_t`, `hipFuncAttributes`);
  - 21 functions and constants (errors, devices, the stack limit, malloc, free, memcpy, memset and its two directions, events, function attributes, occupancy);
  - `hipDeviceProp_t` with an empty `gcnArchName` beside CUDA's fields, and its `hipGetDeviceProperties`;
  - `HIP_VERSION`, set to 0 so a log shows this header, not a release.

  `build.sh cuda` compiles with plain nvcc. Its line names no HIP path (`nvcc -x cu -I.../cudahip -O2 ...`), and the preprocessed source names no HIP install. MEASURED on both cards (`captured/desktop-checks.txt`): every corpus's hash equals the HIP 7.2.4 build's for both kernels, rmm-as-rne goes red for both, and a 2^28-case differential on each card shows 0 differing, with the same first-chunk hashes.

  Not covered, because the harness does not use them: HIP streams beyond the default, `hipLaunchKernelGGL` (the source launches with `<<< >>>`), hiprtc, managed memory, textures, cooperative groups, any `hipDeviceProp_t` field CUDA does not have, and AMD (there the source uses ROCm's own HIP).
- **(c) AMD's `hipother` sources** still live in the ROCm monorepo (`ROCm/rocm-systems`, `projects/hipother`, READ in the develop branch's listing). Building HIP's NVIDIA headers from there at ROCm 10.1's tag is the current route. Not tried.

**The CUDA version.** CUDA 12.9 was chosen over 13.x because HIP 7.2's
NVIDIA layer is BELIEVED to be written against CUDA 12. Its headers map
`cudaDeviceProp` fields, some of which CUDA 13 removed (BELIEVED, not
checked). CUDA 12.9 has both sm_89 and sm_120 (READ, its `-gencode` built
both).

## 4. The toolchain as installed

All installs were made under Logan's approval in the brief, with the lead's
answers of 15:20 and 15:22. Each download was checked against its vendor's
published sum (MEASURED). The ledger records sizes, sums and removal.

| what | version | source | where | check |
|---|---|---|---|---|
| Ubuntu WSL image | 24.04.5 (389 MB) | releases.ubuntu.com (Canonical) | distro `cft-gpu`, disk on D: | sha256 = Canonical's SHA256SUMS |
| build-essential, gcc, g++ | 12.10ubuntu1, 13.3.0 | Canonical's archive | `cft-gpu` | apt's signed index |
| cuda-keyring | 1.1-1 | developer.download.nvidia.com, wsl-ubuntu | `cft-gpu` | = the signed index's sum |
| cuda-nvcc, -cudart-dev, -cuobjdump, -nvdisasm, -sanitizer, -profiler-api | 12.9 (100 MB) | NVIDIA's wsl-ubuntu repository | `/usr/local/cuda-12.9` | apt plan refused any `cuda`, `cuda-drivers`, `nvidia-*` |
| hip-dev, hipcc-nvidia, rocm-core | 7.2.4 (0.6 MB) | repo.radeon.com/rocm/apt/7.2.4 | `dpkg -x` into `/opt/rocm-7.2.4` | gpgv Good signature (AMD key CA8B...3C5C); Packages = signed Release; each .deb = Packages |

- **Not installed anywhere:** a GPU driver. WSL reaches the cards through the Windows driver, 617.42.
- **The RX 7600 machine:** nothing installed, and no sudo used. Its ROCm 10.1 (HIP 7.16.26385, AMD clang 24.0.0git) was used as found.
- **WSL:** WSL 2.2.4 has no `--install --name --location`, so the distro is a `wsl --import`. Neither `.wslconfig` nor any Windows setting was touched.
- **Removal:** `wsl --unregister cft-gpu`, then delete its folder. The lead removes `~/gpu-a` on the box after the merge.

## 5. Correctness: bit for bit

Every check below is MEASURED in the final runs from the committed scripts:
- this desktop, 16:07 to 16:11 (`captured/bench.txt`, `hazards.txt`), and its runbook again 16:25 to 16:28 with section 3 (b)'s step added (`captured/desktop-checks.txt`);
- the RX 7600 machine, 16:07 to 16:09 (`captured/rx7600-checks.txt`).

Earlier runs of the same scripts gave the same hashes, and the ledger holds
them.

**The first kernel (libcft's arithmetic).** Each device's output equals the
golden model's on every corpus. 0 results differ, 0 flags differ, 0 are
refused, under every attribute.

| corpus | cases | expected sha256 (d \|\| flags) | cpu | cpu-libcft | 4070 | 5060 Ti | RX 7600 | box cpu |
|---|---|---|---|---|---|---|---|---|
| conf-fp32 | 18,435 | dd3d83be... | = | = | = | = | = | = |
| conf-fp64 | 18,440 | 3a8a9b2c... | = | = | = | = | = | = |
| conf-fp128 | 18,545 | fcc92da3... | = | = | = | = | = | = |
| conf-fp256 | 18,360 | da932116... | = | = | = | = | = | = |
| stream-fp32 | 1,000,000 | 15545866... | = | = | = | = | = | = |
| stream-fp64 | 1,000,000 | dbf29a85... | = | = | = | = | = | = |
| stream-fp128 | 1,000,000 | c967ac1e... | = | = | = | = | = | = |
| stream-fp256 | 1,000,000 | 9c7f2f6e... | = | = | = | = | = | = |

"=" means the harness's sha256 (libcft's `sha256.c`) and hashlib's of the
same file both equal the expected value. The full sums are in
`captured/expect.sha256`.

**The container's sizing.** cft_config.h allows smaller sizings, and each
gives the same answers (MEASURED):

| sizing | where | frame / scratch | corpora | result |
|---|---|---|---|---|
| `CFT_BN_LIMBS=38` (fp256's stated need) | CPU, 5060 Ti | 2,704 B frame | all 8 | green, 0 refused |
| `CFT_BN_LIMBS=38` | RX 7600 | 3,068 B scratch | all 8 | green, 0 refused |
| `CFT_BN_LIMBS=40` | CPU, 5060 Ti | 2,840 B frame | all 8 | green, 0 refused |
| `CFT_MAX_FORMAT=1` (9 limbs) | CPU, 5060 Ti | 728 B frame | the fp32 and fp64 corpora | green, 0 refused |

**The plants.** "A check that cannot fail is worth nothing." Each plant was
run, and each went red (MEASURED):

| plant | what it changes | red on | what went red |
|---|---|---|---|
| devcopy selftest | four faults in a copy | this desktop, the box | each refused by name |
| flip | bit 0 of case 12345's expected d, in a copy of conf-fp256 | cpu, 4070, 5060 Ti, RX 7600, box cpu | 1 result (case 12345, under rup); `gen_corpus.py verify` red too on every GPU and the cpu |
| rmm-as-rne | the lane takes rmm for rne (built in) | cpu, 4070, 5060 Ti, RX 7600 | 51 results, all under rmm |
| drop-underflow | the lane drops flag 8 (built in) | cpu, 4070, 5060 Ti, RX 7600 | 1,452 flags (290/291/290/291/290 by attribute) |

The plants' outputs hash alike across vendors (MEASURED): rmm-as-rne
ffe3f2eb..., drop-underflow f0ca15e0.... The same wrong answer is wrong in
the same bits everywhere.

The built-in plants are compiled into both kernels, so they leave the
differential of section 6 green. One plant is one-sided:
`-DCFT_GPUA_PLANT_FIXED_RMM_AS_RNE` changes the second kernel alone. Under it
`cft_fma diff 16777216 20261110` goes red, 378,784 of 2^24 cases differing on
the 5060 Ti and on the RX 7600, with the unplanted build at 0 (MEASURED at
send-back 1, `captured/diff-plant.txt`). Every differing lane is an rmm lane,
since the plant changes no other. VGPU-A found the same 378,784 with a
one-sided plant of its own, and 3,494,301 with the flag drop made one-sided
(VGPU-A's MEASURED, the 5060 Ti).

**Not run:**
- the plants on cpu-libcft. Its arithmetic is libcft's object code, and the plants live in the harness's lane, which it shares.
- gfx942. It was built, not run.

## 6. The second kernel: a second implementation

**It is not libcft's code, and its agreement is evidence by test, not a
proof.** `fma256_fixed.h` is an fp256 FMA written for the GPU.
- Every array has a fixed size and every index is a constant once the loops unroll, so the values stay in registers.
- Unpacking and the special cases follow `sf_fma` in its order.
- The finite case places the higher term's leading bit at position 509 of a 512-bit window and shifts the other term into it, folding what falls below into a sticky bit. The sum is then the value `sf_fma` rounds, and the header's comment argues why.
- Rounding is `sf_round_pack`'s, step for step, including tininess after rounding.

It takes the whole fp256 space (all five attributes, every flag, NaN,
infinity, zero, subnormal inputs and results, overflow, underflow,
cancellation and ties) with no fallback to the generic path. It refuses any
other format by name.

Its first run refused 13,715 of 18,360 conformance cases. One line in its
shifter read the shifted limb instead of the bits shifted out. After that fix
nothing else changed, and every check below is green (MEASURED):

- **Corpora.** conf-fp256 and stream-fp256 give the golden hashes on the CPU, the 4070, the 5060 Ti, the RX 7600 and the box's CPU.
- **Plants.** rmm-as-rne (51 results) and drop-underflow (1,452 flags) go red on the 4070, the 5060 Ti and the RX 7600, with the first kernel's planted hashes.
- **The compilers' hazards.** Every variant of section 7 ran it on both fp256 corpora, green.
- **The differential stream** (`cft_fma diff N SEED`) runs both kernels on the same lanes and compares them lane by lane on the device:

| device | cases (seed 20261110) | differing | first chunk's sha256: inputs, both outputs |
|---|---|---|---|
| RTX 5060 Ti | 1,073,741,824 (2^30) | 0 | b0764272..., 0bb5295e... = 0bb5295e... |
| RTX 4070 | 268,435,456 (2^28) | 0 | the same |
| RX 7600 | 1,073,741,824 (2^30) | 0 | the same |
| CPU | 200,000 (seed 1) | 0 | 15f6d14c..., 5010e777... = 5010e777... |

The generator's nine families are, each with a random attribute:
- raw bits;
- operands at the subnormal edge;
- products at the underflow edge, with c zero or subnormal;
- products at the overflow edge;
- deep cancellation, c = -(a*b) rounded by libcft's own lane and moved a few ulps;
- exact cancellation with short significands;
- exact ties, normal and subnormal;
- c swept across +-514 binades of the product;
- the specials in every slot.

Its first 2,097,152 inputs hash alike on AMD and NVIDIA (MEASURED), so the
same cases ran on both vendors. Each diff took under 25 s.

**A known limit of the generator:** it does not aim at cancellation near
EMIN or EMAX, at a subnormal c at the normal boundary, or at overflow by a
rounding carry. VGPU-A's own golden corpus of 747,560 cases covers those four
classes, and both kernels are green on it on the CPU, the 5060 Ti and the
RX 7600, hash 067880f5... (VGPU-A's MEASURED; its ledger,
`Data/runs/2026-11-10-gpu-a/ledger/verifier-VGPU-A.md`, item 6, in the
records, which are not committed).

**What a backend using it would need to stay honest:**
- the generic kernel built beside it, as its reference inside the gates;
- the conformance corpus and a differential stream run against both on every build and every device;
- the fixed kernel refused by name on any format or opcode it does not cover.

## 7. The compilers' hazards

Each hazard is a build variant that must give the golden hashes on every
corpus. Every variant listed was run and was green (MEASURED,
`captured/hazards.txt`), for the first kernel on all 8 corpora and the
second on both fp256 corpora.

- **Fast math and FMA contraction.** The arithmetic is integer. The default lines are `-O2` (nvcc: `--fmad=true`, no fast math; HIP-Clang: its default `-ffp-contract`). Builds with `--use_fast_math` (nvidia) and `-ffast-math` (amd) are green. The ISA settles it:
  - AMD gfx1102, the whole translation unit: no floating-point instruction in either FMA kernel. The only three, `v_rcp_f32` and two `v_fmamk_f32`, are in the test generator: the compiler's 64-bit modulo by a variable.
  - NVIDIA: the only floating-point opcode in either FMA kernel is `HFMA2 R, -RZ, RZ, 0, imm`, nvcc's constant move: -0 times 0 plus the immediate pair writes the pair's bits. There are 378 in the first kernel and 148 in the second, on sm_120 only; sm_89 has none. By hazards.sh's listing of every HFMA2 with its operands (MEASURED at send-back 1, `captured/hazards.txt`):
    - the first kernel's 378: 333 with the immediate 0, and 45 with fp16 subnormals whose bit patterns are the integers 1 (33), 2 (3), 4 (4), 16 (4) and 128 (1);
    - the second kernel's 148: 143 with 0, and 5 with the integers 1 (1), 16 (2) and 20 (2).
    I2F, MUFU.RCP and F2I appear in the generator alone, beside 119 HFMA2 of its own. (The study first listed 1, 2, 4, 16 and 128 alone, from the five commonest immediates over the whole binary; the zeros and the 20 were missed.)
- **Flush to zero.** Irrelevant, since neither FMA kernel computes in floating point. The constant moves have zero inputs, and the fast-math builds, which flush, are green.
- **Shift counts at or past the width.** `-fsanitize=undefined,address -fno-sanitize-recover=all` on the device copy, on libcft's C and on the second kernel found no report on every corpus.
- **`long`'s width.** One `1uL` (section 2), whose value fits either width.
- **Stack and local memory:**
  - The first kernel: nvcc reports a 4,472-byte frame, 40 registers and 0 spills. The runtime raised a thread's stack from 1,024 to 4,480 bytes by itself at the first launch, on both cards. AMD reports 5,052 B of scratch a lane on gfx1102 (5,068 on gfx942), with no dynamic stack. Static counts: 435 to 527 LDL and 913 to 2,050 STL in its SASS; 322 scratch loads and 348 stores on AMD.
  - The second kernel: 110 registers and no local memory on sm_89; 64 registers and an 8-byte spill on sm_120; 82 VGPRs and 208 B of scratch on gfx1102; 94 and 272 B on gfx942.
- **Uninitialised memory.** `-ftrivial-auto-var-init=pattern` and `=zero` give the same hashes on the CPU and on the RX 7600. An automatic variable read before it is written would change at least one of them.
- **`-O0` and `-G`.** Green on the CPU and AMD, and `-G` (device code unoptimised) on NVIDIA.
- **Reductions by atomics.** Neither FMA kernel has one. The differential's mismatch counter is an atomic integer sum, which no order can change.
- **Not run:**
  - compute-sanitizer: under WSL it asks for `EnableDebuggerInterface.bat` run as administrator, a Windows change that was not made, and reports "Device not supported". It still runs the program, uninstrumented, and counts its own two errors. hazards.sh printed those lines under a GREEN verdict; since send-back 1 it names the leg "not run: compute-sanitizer (...)" with the reason printed, and its verdict counts it as not run, never green (`captured/hazards.txt`, the NVIDIA section re-made from a rerun);
  - `-ftrivial-auto-var-init` on NVIDIA, which nvcc does not have;
  - valgrind and MemorySanitizer, which were not installed; the auto-var-init pair stands in.

**Hazards found in the harness and the toolchain,** each fixed or worked
around and recorded in the ledger:
- N1 to N3 and `gcnArchName` (section 3); in bash, an apostrophe inside `${HIP_PATH:?...}`, `| head` under `pipefail`, and CRLF that Python's `write_text` put into `build.sh` on Windows.
- A binary built before `--case` existed ignored it and timed the wrong thing. The harness now refuses any option it does not know (MEASURED).
- On the 5060 Ti, some binaries' single-shot `check` timings carried about 300 ms of first-launch cost. This was not explained; it changes no result, and the rates come from warmed medians.

## 8. Throughput

**Method.** `bench.sh` runs each corpus through `cft_fma bench`:
- one warm-up, then 10 timed repetitions (3 on the CPU);
- kernel time by events; end to end as host-to-device copies, kernel and copies back, in pageable memory;
- each repetition allocates, copies and frees, so the end-to-end figure is a per-call cost.

Batches are the stream's 1,000,000 lanes, or 4,000,000 replicated. The
medians are below, with min/max in `captured/bench.txt`.

Conditions:
- Clocks were not controlled, and `nvidia-smi` read 2.5 to 2.9 GHz under load.
- The 4070 drives the display, hence its wider spread. In VGPU-A's session the display took 8 to 19 % of that card, and VGPU-A MEASURED lower 4070 figures (below).
- The RX 7600 shared its card with an idle resident llama-server holding 6.1 GB of its 8 GB (Logan's word: sharing is fine). Its runs used at most about 0.7 GB. VGPU-A's batch series in the footnote was taken with the card free.
- Load averages were 0.1 to 0.6.
- The CPU figures are one core of this desktop's i5-12400F under WSL, one thread, `-O2`, 3 repetitions. VGPU-A's CPU figures differ from these by up to about 17 % (VGPU-A's MEASURED, 3 repetitions), so a CPU figure here carries that spread.

Two sessions measured the 4070 and disagree by up to 22 % (175.3 against
143.7). The fp256 table gives VGPU-A's 4070 figures beside this session's;
the other formats' 4070 figures were measured in this session alone and
carry the same spread.

**fp256, MEASURED (final runs, block 128).** Kernel only, 1M lanes (4M);
then end to end at 1M:

| device | first kernel | second kernel | end to end (first / second) |
|---|---|---|---|
| RTX 4070 (sm_89, 46 SMs) | 175.3 M/s (172.0); VGPU-A: 143.7 (136.6) | 1,079 M/s (1,069); VGPU-A: 940 (940) | 44.7 / 48.2 M/s |
| RTX 5060 Ti (sm_120, 36 SMs) | 143.3 M/s (146.6) | 887 M/s (935) | 34.6 / 40.9 M/s |
| RX 7600 (gfx1102, 16 "CUs" to HIP) | 77.4 M/s (77.8) | 1,383 M/s (803*) | 31.5 / 51.0 M/s |
| one CPU core, device copy | 461 ns (366 ns) | 327 ns (314 ns) | - |
| one CPU core, libcft's C | 450 ns (447 ns) | - | - |

\* At 4M lanes the RX 7600's second kernel makes 803 M/s, against 1,383 M/s
at 1M. **It is a step in the batch size, and not the resident server's
VRAM.** VGPU-A MEASURED the series with the card free (every run after the
server was unloaded at 16:45, amd-smi showing 8,120 MB free and no other GPU
process), kernel only, median of 10:

| lanes | 0.5M | 1M | 1.5M | 2M | 3M | 4M |
|---|---|---|---|---|---|---|
| G/s | 1.46 | 1.38 to 1.40 | 1.40 | 1.01 | 1.00 | 0.82 to 0.83 |

At 4M lanes, every lane on one case gives 0.88 G/s, and blocks of 64 to 256
give 0.83 to 0.84. So the step lies between 1.5M and 2M lanes. **Its cause
is not known.** NVIDIA shows no such step: the 5060 Ti's second kernel makes
0.885, 0.918 and 0.935 G/s at 1M, 2M and 4M lanes, and the 4070's 0.94 at 1M
and at 4M (VGPU-A's MEASURED).

The other formats, first kernel, block 128, kernel only (MEASURED):

| device | fp32 | fp64 | fp128 |
|---|---|---|---|
| 4070 | 903 M/s | 690 M/s | 411 M/s |
| 5060 Ti | 793 M/s | 720 M/s | 390 M/s |
| RX 7600 | 232 M/s | 229 M/s | 158 M/s |
| one CPU core | 179 ns | 209 ns | 310 ns |

The block size (64, 128, 256) moves no rate by more than its spread.

**Compared like with like** (COMPUTED from the table and docs/ROADMAP.md's
427 M with resident data, READ):

| | 4070 | 5060 Ti | RX 7600 |
|---|---|---|---|
| first kernel, times the quad | 0.41 (VGPU-A: 0.34) | 0.34 | 0.18 |
| second kernel, times the quad, 1M lanes | 2.5 (VGPU-A: 2.2) | 2.1 | 3.2 |
| second kernel, times the quad, 4M lanes | 2.5 (VGPU-A: 2.2) | 2.2 | 1.9 |

- Against `mpfr+754`'s 71 ns a core (READ): the first kernel is 5.5 to 12.4 cores (10.2 at VGPU-A's 4070 figure), and the second 57 to 104 (the RX 7600 at 4M lanes and at 0.5M).
- Against libcft's own C on one core here (450 ns, with the CPU's spread above): the second kernel is 360 to 660 cores (the same two figures).
- The end-to-end rates compare with nothing of the card's. The card's 427 M is with resident data, and its per-call path costs about 35 µs a run (READ, the same section). Neither was measured here.

**The roadmap's ESTIMATE** (10^9 to 10^10 on a large GPU, low confidence),
against the measurements:
- Its basis was about 1,000 32-bit operations an fp256 FMA. The first kernel spends about 38,000 lane-instruction slots per FMA (COMPUTED: 1.32 x 10^13 slots a second on the 5060 Ti at 2.87 GHz, over 346 M FMAs a second with every lane on one case). The second has about 14,900 slots per FMA at that rate (COMPUTED: the card's issue rate over the measured FMA rate), the slots available, not a measure of what it spends: part 2 bounds what it needs at about 4,200 per FMA-class instruction, inside fp256 exp (P2.5).
- The ESTIMATE was an order of magnitude high for the generic port. The specialised kernel straddles its floor on mid-range cards: 0.80 to 1.46 x 10^9 by device and batch (the answer gives which is where).

**What limits the first kernel** (MEASURED; desktop and RX 7600 experiments in
the ledger):
- **Not the container.** 38 limbs make 146 M/s against 143 to 145 at 64 on the 5060 Ti, and 82.9 against 78.1 on the RX 7600. The code touches only `n` limbs.
- **Not occupancy.** It is 100 % at blocks 64 to 256 on every card, and the block size moves nothing.
- **Divergence, by 2.1 to 3.5 times.** With every lane on one case (near with like signs, near with unlike signs close, near with unlike signs apart, far), the 5060 Ti makes 302 to 419 M/s and the RX 7600 168 to 273 M/s, against 143 and 78 for the mixed stream.
- **The instruction count of a portable bignum.** Loops of data-dependent length, bit-at-a-time helpers (`u32_bitlen`, `sf_set_field`), and every limb in local memory: thousands of LDL/STL and scratch instructions statically.

**What limits the second kernel:**
- Divergence costs 0 to 7 % at 1M lanes (one case a lane: 903 to 957 M/s on NVIDIA, 1.46 to 1.48 G/s on the RX 7600).
- Its register count holds NVIDIA's occupancy at 33 % (sm_89) and 67 % (sm_120) (MEASURED).
- On the RX 7600 at 1M lanes it moves 130 bytes an FMA at 1.38 G/s, about 180 GB/s (COMPUTED). That is close to the card's 288 GB/s (BELIEVED, its specification). Past the step it moves less (1.0 G/s is 130 GB/s, 0.82 is 107 GB/s, COMPUTED), so that bandwidth does not explain the step.
- On NVIDIA it uses about a quarter of the memory bandwidth. Part 2's measurement contradicts the BELIEVED "issue-bound" this line gave (P2.5): what bounds the stand-alone kernel on NVIDIA is not tested. Candidates, each untested: global-memory latency, and occupancy at 64 to 110 registers.

**A tuned kernel** (ESTIMATE, medium-low confidence) might gain 1.5 to 3
times on NVIDIA:
- 64-bit limbs where the hardware has wide multiplies;
- fewer selects in the shifters;
- `__launch_bounds__` tuned for occupancy.

With resident data it would gain more on AMD, where at 1M lanes it runs near
the card's bandwidth.

**The MI300X, ESTIMATE until measured.**
- **The second kernel: 0.8 to 1.5 x 10^10 a second.** Basis:
  - 304 CUs against the RX 7600's 32, at a similar clock (BELIEVED, the specifications; HIP reports the 7600's as 16, BELIEVED to be its work-group processors);
  - wave64 giving up the per-CU throughput that the 7600's dual issue gives (BELIEVED);
  - 5.3 TB/s of HBM against 288 GB/s (BELIEVED, the specifications);
  - the RX 7600's rate it scaled, its 1M-lane 1.38 G/s (the 4M figure was then set aside as an anomaly). Scaled the same way from the card's rate past its step (0.80 to 1.0 G/s at 2M to 4M lanes), the range is 0.46 to 1.1 x 10^10. Whether the MI300X has a step, and where, is not known.
- **The first kernel: 0.5 to 1.2 x 10^9 a second.**

## 9. The MI300X

**The runbook is `run_mi300x.sh`**, for the lead to run when Logan has the
time. Its steps:
1. the toolchain check for gfx942;
2. the corpora against `captured/corpus.sha256`;
3. `run_amd.sh gfx942`: every corpus, the plants, the second kernel and a 2^30 differential;
4. both kernels' rates at 1M, 4M and 16M lanes;
5. one case a lane.

ESTIMATE: under 10 minutes on one GPU.

**It builds without the card** (MEASURED on the RX 7600 machine, its ROCm
10.1, `-Rpass-analysis`):
- the first kernel: 36 VGPRs, 5,068 B of scratch a lane, 6 waves a SIMD;
- the second kernel: 94 VGPRs, 272 B, 5 waves.

Run on the 7600, the gfx942 binary is refused by name ("device kernel image
is invalid"). Nothing has run on an MI300X. `run_mi300x.sh` as a whole has
not run anywhere. Each of its steps has run on the RX 7600 machine at
gfx1102, except the 16M-lane rates, which that card's free memory does not
hold.

**Heavier runs worth its time,** for Logan to choose from. None is planned.
The times are ESTIMATEs on this section's rates for one GPU, and an
eight-GPU node divides them by about eight:

| run | size | ESTIMATE | what it buys |
|---|---|---|---|
| (a) `run_mi300x.sh` as written | the corpora, 2^30 differential | under 10 min | both kernels measured on a data-centre GPU, the ESTIMATEs above replaced |
| (b) a deep differential | 2^40 cases (1.1 x 10^12) | 20 to 45 min: the generic reference and the generator's cancellation cases (about 1.35 x 10^12 generic FMAs) dominate; the second kernel's share is about 2 min | a thousand times the evidence this study gives the second kernel |
| (c) a golden-checked stream | 10^9 fp256 cases | the golden model on the host's CPUs: about 9 core-hours (33 µs a case, MEASURED here), minutes on a large host; the replay takes seconds | the golden model itself, not the first kernel, as the second kernel's referee at a thousand times the stream's size |
| (d) rates with resident data | 16M to 256M lanes, several launches per copy | minutes | the like-with-like figure against the quad's 427 M with resident data |

## 10. What a backend would need (about a page)

A fourth backend in `host/src/backend.h`, beside the software, XRT and
remote backends:

- **The arithmetic, two-tier.**
  - The generic kernel (libcft's code under E1) runs every format and opcode the software backend runs, unchanged. It is the reference.
  - Specialised kernels (fp256 FMA first; ADD, SUB and MUL through `sf_steer`'s operand steering; fp128 next) are each held to the reference inside the gates.
  - A device publishes what it has in CAPS and refuses the rest by name, as the card does.
- **Residency, or the speed is lost.** End to end is 31 to 51 M/s against 0.80 to 1.46 G/s kernel only (by device and batch). The backend needs `cft_alloc`'d device copies under `cft.h`'s authority rule, as the card's resident mode has. A program's registers should live on the device, as the sequencer's model already wants: one instruction stream, many lanes, one thread a lane.
- **The flags.** A call's flags are an OR over its lanes, which atomics compute deterministically, since OR is associative and commutative. `cft_reduce`'s sums keep their fixed tree, a kernel per level, never an atomic add on values.
- **`host/src`.** E1 behind a `CFT_HD` header (section 2). Nothing else in the arithmetic needs to change for device code (MEASURED by this study's build).
- **The NVIDIA leg.** HIP 7.2.4 frozen, the study's header (section 3 (b), built and held to the same hashes), or `hipother` from source. This is Logan's choice (questions).
- **The gates.**
  - the conformance corpus through the backend, as `--device sw` and the card are run;
  - `host/tests/seq_check.py` through a device handle;
  - the photograph stage;
  - a differential stream of the specialised kernels against the generic one on every device in the round;
  - the plants of section 5 kept as controls.
- **The sequencer on the GPU** is sketched only: `program.c`'s interpreter as device code under E1, one thread a lane, its registers in local memory for the generic tier. Its cost is unmeasured, and the first kernel's local-memory traffic suggests the same order as section 8's generic rates (ESTIMATE).

## 11. Questions for Logan

1. **A backend round?** With a specialised fp256 kernel held to libcft's own code on the GPU, a 5060 Ti or RX 7600 runs fp256 FMAs at 1.9 to 3.4 times the quad's resident rate, kernel only, by batch size (the RX 7600's 3.2 to 3.4 holds at 1.5M lanes or fewer, 1.9 at 4M). Is that worth a round, and which first: fp256 FMA/ADD/SUB/MUL, or fp128 too?
2. **The NVIDIA leg.** HIP's NVIDIA platform is packaged only up to ROCm 7.2.4. For a backend, which: keep HIP 7.2.4 frozen, use the study's 52-line CUDA header (built here, same hashes), build `hipother` from ROCm's sources, or drop NVIDIA?
3. **Specialised kernels in the contract.** The second kernel is a second implementation. Its agreement is evidence by test (73,780 conformance, 1,000,000 stream and 2.4 x 10^9 differential cases), not a proof. Is "generic as reference inside the gates" enough, or should a specialised kernel need a proof (an exhaustive small-format analogue, say)?
4. **The MI300X.** Which of section 9's runs (a) to (d) are worth its time, if any? Each needs your word.
5. **The CPU too?** The first kernel's cost on one CPU core is about 450 ns an fp256 FMA, against mpfr+754's 71 ns. Most of it is the portable bignum's bit-at-a-time helpers. Should `host/src` get faster helpers on every platform, behind the same vectors?
6. **This desktop's distro `cft-gpu`.** Keep it for the verifier and a later round, or remove it after the merge?
7. **The RX 7600 machine's resident llama-server** holds 6.1 GB of the card. Is it to stay?

## Appendix: commands

All run from the tree's root, on the machine named. `CORPUS` and `WORK` are
directories outside the tree.

```
# corpora (this desktop, Windows Python 3.12 + mpmath 1.3.0; ~1 min), then checked
python -B docs/studies/gpu-a/gen_corpus.py conformance CORPUS --jobs 2   # and: stream
# the desktop (WSL cft-gpu): runbook ~3 min; then bench.sh and hazards.sh as below
HIP_PATH=/opt/rocm-7.2.4 bash docs/studies/gpu-a/run_wsl_nvidia.sh CORPUS WORK
FORMATS=fp256 bash docs/studies/gpu-a/bench.sh WORK/build/nvidia/cft_fma nv1-fixed \
    CORPUS --device 1 --kernel fixed   # without the last two words: the first kernel
bash docs/studies/gpu-a/hazards.sh nvidia CORPUS WORK --device 1   # and: cpu
# the RX 7600 machine (~2.5 min): the commands in run_rx7600.sh's header
# section 8's experiments: the container, and one case a lane (cases 5, 4, 1, 2)
DEFS="-DCFT_BN_LIMBS=38 -DCFT_NO_TRANSCEND" bash docs/studies/gpu-a/build.sh nvidia WORK/l38
WORK/build/nvidia/cft_fma bench CORPUS/stream-fp256.bin --block 128 --lanes 1000000 --case 5
# send-back 1: the one-sided plant (section 5), then the diff it turns red
DEFS=-DCFT_GPUA_PLANT_FIXED_RMM_AS_RNE bash docs/studies/gpu-a/build.sh nvidia WORK/plant
WORK/plant/cft_fma diff 16777216 20261110 --device 1
```

# Part 2: programs on the GPU

Written 2026-11-10, the same day, by the same author at Logan's word:

> "I'd also be curious if programs could run well on the gpu kernels at speed. If possible that could be added to the study"

Part 1 measured one operation. This part runs libcft's sequencer
**programs**: one instruction stream over many lanes with a lane mask. It
runs the math library's routines as fragments, cftc's compiled systems, and
the golden model's own fuzz programs. The marks are part 1's. Part 2's code
is in `studies/gpu-a/` beside part 1's.

## P2.1 The answer

**Yes, bit for bit, on all three cards.** A runner with one thread a lane
executes the same program words libcft runs. Its outputs match libcft's own
sequencer byte for byte (MEASURED) on the RTX 5060 Ti, the RTX 4070, the
RX 7600 and the runner's CPU build:
- results, flags, status, deposit counts, R23's lane bytes and the scratch-out block;
- masked lanes left as the caller filled them.

The corpora:

| corpus | cases | lanes | what it holds |
|---|---|---|---|
| seq_check's routine corpus, its first round at seed 17 | 480 | 29,627 | every fragment, both shapes, five attributes; fp32, fp64, fp128 and fp256 |
| the golden model's fuzz programs | 800 | 44,662 | every control code but augmentedAddition's two; 200 a format |
| cftc's compiled systems | 8 | 4,608 | loops of 10 to 100 steps (up to 17,422 instructions a lane), the scratch block, R24's regions |
| the rate programs on typical arguments | 6 | 24,576 | exp, sin and atan at fp64 and fp256 |

On the routine corpus the golden model gives the same bytes too. Two plants
go red by name on every device.

**At speed, yes.** These are kernel-only rates, with the program and the
lanes resident, at 1M lanes. Each lane runs one of 4,096 typical
arguments (exp and atan uniform in [-20, 20], sin in [-100, 100]). The table
gives lane-programs a second (MEASURED, P2.5).

| | 5060 Ti | 4070 | RX 7600 | libcft, one core | MPFR, one core |
|---|---|---|---|---|---|
| exp, fp64 | 13.4 M | 9.9 to 10.5 M | 5.9 to 6.0 M | 45.5 K | 1.2 to 1.3 M |
| exp, fp256, libcft's arithmetic | 2.64 M | 3.5 to 3.9 M | 2.11 M | 23.4 K | 0.59 to 0.60 M |
| exp, fp256, the fixed path | 25.6 M | 8.0 to 8.6 M | 7.1 to 7.3 M | - | - |

- **Against one core of libcft's sequencer:** at fp256 exp, the generic arithmetic is 90 to 165 times faster, and the fixed path 300 to 1,090 times (COMPUTED).
- **Against one core of MPFR** (mpfr+754, MPFR 4.2.1, P2.5): at fp256 exp, the generic arithmetic is 3.5 to 6.6 times faster, and the fixed path 12 to 43 times (COMPUTED). At fp256 atan, where MPFR is slowest, the fixed path is 42 to 149 MPFR cores.
- **The card:** no rate for programs at fp64 or fp256 is recorded (READ, P2.5). There is nothing to set these figures beside.

**Two qualifications.**
- **The fixed path differs by card.** It is 9.7 times the generic path on the 5060 Ti, 2.1 to 2.5 times on the 4070 and 3.4 times on the RX 7600. Not explained (P2.5).
- **Rates depend on the lanes.** On the routine corpus's own lanes (specials, edges and centres, 63 to 129 distinct), the NVIDIA cards are up to 44 % slower than on typical arguments (P2.5).

**What it is.** The executor is libcft's own `seq_run_block`, copied by
script and checked at every build (P2.3). The run's setup around it, about
150 lines, is a **second implementation of the sequencer's run semantics**,
held bit for bit to libcft's sequencer, and not libcft's code.

## P2.2 What was built

| file | lines | what it is |
|---|---|---|
| `devcopy.py --seq` | +159 | the executor taken from program.c by script: E2 to E4, checked; four plants |
| `cft_seq.hip` | 693 | the runner: one source for the CPU, NVIDIA and AMD, as part 1's |
| `seq_ref.c` | 245 | the reference: libcft's `cft_program_run_ex`, `libcft.a` built from a copy of `host/` |
| `gen_programs.py` | 345 | the corpora, by seq_check's and the golden model's own builders; the golden outputs; the census |
| `build_seq.sh`, `run_seq.sh` | 86, 93 | the builds; the runbook body for any HIP device |
| `mpfr_bench.c` | 145 | MPFR on one core, BENCHMARKS.md's mpfr+754 method |
| `cft_fma.hip --op` | +121 | ADD, SUB and MUL through the fixed FMA by libcft's steering (P2.6) |
| `run_mi300x.sh`, `hazards.sh` | +15, +10 | step 6, the runner on gfx942; the sanitizer rule refined (P2.8) |
| `captured/` | 545 | the corpora's sums (`programs.sha256`), every run's log (`part2-*.txt`) |

Nothing in `host/src` changed.

**The output layout.** Both executors write, per case: the program's
information (`cft_program_get_info` in seq_ref, the runner's own parse), the
run's status, FLAGS and STATUS, then the deposits, counts, lane bytes and
scratch-out. Every buffer is first filled with seq_check's pattern, so a
write that must not happen shows.

## P2.3 The executor copied, the run re-expressed

**The copy (`devcopy.py --seq`).**
- It extracts 28 pieces of `program.c`, in its order: `seq_run_block` and every function, type and constant it reaches (`seq_decode`, `seq_source`, `seq_step`, `seq_post_step`, `struct cft_program`, `seq_block`, `seq_load_in` and the rest). That is edit E2, the extraction.
- Each piece is byte for byte as in program.c, but for three edits:
  - E1 (`CFT_HD`) on its 12 function lines;
  - E3, `BLOCK_LANES` 64 becomes 1;
  - E4, seq_run_block's one ALU call goes through a hook, `CFT_GPUA_ALU`. It is `cft_sf_compute` itself unless the fp256 path is built.
- `cft.h` is copied unedited. Part 1's copy of softfloat and bigint is unchanged: 105 E1 edits.
- Four new plants are each refused by name: an operator changed, `BLOCK_LANES` 2, the hook missing, a piece missing (MEASURED, `devcopy.py --selftest`).

**What is re-expressed.** It is the runner's alone, held to libcft by the
comparison:
- `gpua_parse`: the image's header, constants and instructions, and `seq_scratch_footprint`'s two fields;
- `gpua_seq_lane`: what `seq_program_run` does around `seq_run_block` for one lane:
  - the registers zeroed, a, b and c loaded;
  - R17's mask setting `keep` and `active`;
  - a kept lane's deposits zero-filled;
  - the scratch zeroed to its reach and preloaded;
  - the counts, lane bytes and scratch-out read back for kept lanes only;
- the run's FLAGS and STATUS, which are an OR of the lanes' words by atomic OR on a GPU. No order can change an OR.

The runner does not validate an image. Every image it ran was first loaded,
and so validated, by libcft in seq_ref.

**Refused by name**, never computed: augmentedAddition, control codes 10 and
11 (`augmented.c` is not in the device copy); a format the build does not
carry; an image whose header the parser does not know. **Not run:** ABI
0.14's index tables, for which the runner has no input, and any scratch depth
but a plain software handle's 256.

## P2.4 Why a block of one lane gives a block of 64's bits

This is the runner's foundation, stated from the code.

**Within the block loop.** `seq_run_block` (`host/src/program.c` :1975 to
:2248) acts on each lane through `active[i]`: an ALU instruction, DEPOSIT,
SETACT, STL and LDL, STX and LDX with their post-steps, the augmented halves
and RAISE all skip an inactive lane. Only four things act on the block as a
whole: REPEAT and ENDREP test whether **any** lane is active; HALT ends the
block; QUIET and ENDQUIET count a depth in program order, the same for every
lane.

**Across iterations.** The validator refuses ACTALL and HALT inside a loop
(program.c :946 to :961): ACTALL could reactivate a lane, and HALT's effect
is not per lane. SETACT only narrows. So a lane that goes inactive inside a
loop stays inactive until the loop ends, and each iteration it sits through
writes nothing of its own. That is SEQUENCER.md's P3, "the early exit is
invisible" (docs/SEQUENCER.md :270 to :282).

**The consequence.** A lane's active iterations are the same in a block of 1
and a block of 64:
- while it is active, `any` is true in both;
- once it is inactive, nothing touches it until both blocks reach the same `ENDREP + 1`.

The other effects are per lane: a deposit's address, (lane) x max_deposits +
count, is the global lane's alone (P2); the scratch is per lane; FLAGS and
STATUS are ORs.

**Reductions.** The sequencer has none. No instruction reduces across
lanes: `cft_reduce` is a separate call, outside `program.c`'s executor.

**The test** is the byte-for-byte comparison with libcft at `BLOCK_LANES`
64. The loops in it:
- the systems' loops of 10 to 100 steps;
- the fuzz corpus's 1,102 REPEATs, 860 SETACTs and 342 ACTALLs across the four formats;
- 233 runs that report a deposit overflow, 55 a strict scratch range and 330 a mark.

All are green. **A plant that breaks block independence was not made.** It
would have to change the copied executor, which devcopy's check refuses. The
runner-level plants are below.

## P2.5 Correctness, devices and rates

**Hashes.** The sha256 of each corpus's output, equal on every device run
(MEASURED, `captured/part2-*.txt`). Every device here means: libcft
(seq_ref), the runner's CPU build, the 5060 Ti, the 4070 and the RX 7600, the
fixed path included where it applies.

| corpus | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| routines | a7ff1aef... | 4eb03cc3... | 30b7a930... | dd159120... |
| fuzz | 735f6e86... | 347c9957... | e8f855b4... | 9dec942c... |

- The golden model's outputs equal the routine row (`gen_programs.py --golden`).
- systems: 581b9c30...; bench: 6cba53d3...

**The plants.** Each is red by name, with the same wrong bytes on every
device (MEASURED: the CPU, the 5060 Ti, the 4070 and the RX 7600):
- `CFT_GPUA_PLANT_SEQ_MASK`, the runner ignoring R17's mask: 24 of the 130 fp64 routine cases differ, hash e1537046.... They are the cases whose mask clears a lane (COMPUTED: 24 of the 34 masked cases).
- `CFT_GPUA_PLANT_SEQ_KONST`, an operand source, a constant read from the bank's next entry: 130 of 130 differ, hash 70225177....
- The augadd program is refused by name everywhere.

**The fragments are straight-line.** `gen_programs.py --census` reads every
fragment, both shapes and five attributes, at four formats. Their control
codes are DEPOSIT, HALT, QUIET, ENDQUIET and RAISE only; their branching is
the ALU's SELECT. The rate programs' lengths at fp64 and fp256:
- exp: 183 and 204 instructions;
- sin: 409 and 392;
- atan: 179 and 206.

At fp256, 124 of exp's 204 are FMA, ADD, SUB or MUL (rne, stand-alone).

**The rates.** Method: `cft_seq bench` times the kernel by events, a warm-up
then 5 repetitions (3 at fp256), median given, a case's lanes repeated to 1M
(1,048,576), block 128, outputs left on the device; `seq_ref bench` runs
libcft's `cft_program_run_ex` over 4,096 lanes on one core, best of 3 to 5;
MPFR runs per element over the same arguments, best pass. Clocks were not
controlled.

The RX 7600 figures were taken with the card free (amd-smi: 8,120 MB free,
no other process). Part 1's were taken beside the resident server.

Lane-programs a second, typical arguments (MEASURED):

| | 5060 Ti | 4070 | RX 7600 | libcft, one core | MPFR+754, one core |
|---|---|---|---|---|---|
| exp, fp64 | 13.4 M | 9.9 to 10.5 M | 5.9 to 6.0 M | 45.5 K (22 µs) | 1.2 to 1.3 M (777 to 820 ns) |
| sin, fp64 | 5.97 M | 4.9 to 5.3 M | 2.67 M | 19.3 K | 0.70 to 0.81 M (1,240 to 1,429 ns) |
| atan, fp64 | 13.3 M | 10.2 to 10.9 M | 5.75 M | 43.8 K | 0.50 to 0.52 M (1,927 to 1,989 ns) |
| exp, fp256 | 2.64 M | 3.5 to 3.9 M | 2.11 M | 23.4 K (43 µs) | 0.59 to 0.60 M (1,661 to 1,698 ns) |
| sin, fp256 | 1.25 M | 1.8 to 1.9 M | 0.98 M | 11.9 K | 0.45 to 0.47 M (2,146 to 2,220 ns) |
| atan, fp256 | 2.65 M | 3.8 to 4.1 M | 2.04 M | 24.0 K | 0.16 M (6,190 to 6,224 ns) |
| exp, fp256, fixed | 25.6 M | 8.0 to 8.6 M | 7.1 to 7.3 M | - | - |
| sin, fp256, fixed | 12.8 M | 3.8 to 3.9 M | 3.5 M | - | - |
| atan, fp256, fixed | 23.9 M | 7.4 to 7.8 M | 6.8 to 6.9 M | - | - |

Ranges are the sessions measured: three on the desktop (17:35 to 17:41,
17:54 to 17:55 and 17:58 to 18:01), two on the RX 7600 (17:42 and 17:58) and
two of MPFR (17:42 and 18:03). The 5060 Ti's three agree within 1 %. The
4070 drives the display, which used 7 to 44 % of it between the runs
(nvidia-smi). As lane-instructions a second:
- fp64: 1.0 to 2.5 x 10^9;
- fp256 with libcft's arithmetic: 0.39 to 0.84 x 10^9;
- fp256 with the fixed path: 1.4 to 5.2 x 10^9.

One core of libcft runs 120 to 215 ns a lane-instruction. MPFR's FMA at 237
bits takes 62.3 to 65.3 ns here, against BENCHMARKS.md's 71 ns (READ).

**On the corpus's own lanes** (seq_check's mix of specials, edges, centres
and random), MEASURED at 1M lanes:

| | 5060 Ti | 4070 | RX 7600 |
|---|---|---|---|
| exp, fp64 | 7.48 M | 5.2 to 5.6 M | 4.2 M |
| exp, fp256 | 1.97 M | 2.5 to 2.7 M | 1.40 M |
| exp, fp256, fixed | 22.7 M | 6.2 to 7.2 M | 6.4 to 6.6 M |

Divergence is one plausible cause of the difference from typical arguments.
It was not tested.

**The batch curve**, fp256 exp on the fixed path, typical arguments, in M
lane-programs a second (MEASURED, the runbook's session, `captured/part2-desktop.txt`
and `part2-rx7600.txt`; the earlier sessions agree within 6 % on the 5060 Ti
and the RX 7600, and within 8 % on the 4070 but 18 % at 4K lanes):

| lanes | 4K | 16K | 64K | 256K | 1M | 2M | 4M |
|---|---|---|---|---|---|---|---|
| 5060 Ti | 7.7 | 17.0 | 23.5 | 24.9 | 25.5 | 25.6 | 25.6 |
| 4070 | 4.5 | 7.4 | 7.0 | 7.8 | 7.9 | 8.3 | 8.2 |
| RX 7600 | 2.3 | 6.3 | 7.0 | 6.9 | 7.1 | 7.4 | 7.4 |

- On the corpus's lanes, fp64 exp's curve (`captured/part2-rates.txt`) is flat from 256K lanes on every card.
- The block size (64, 128, 256) moves fp256 exp by at most 7 %.
- **The RX 7600 shows no step here** between 1.5M and 2M lanes, unlike part 1's FMA kernel (section 8). Not explained.

**The fixed path's spread across cards** (MEASURED, ptxas and the HIP-Clang
resource report):
- 5060 Ti: the runner holds 64 registers a thread with the fixed path and 48 without; 83 % occupancy without.
- 4070: 128 registers with or without, with spills of 108 and 184 bytes in the fixed build; 33 % occupancy.
- RX 7600: 74 VGPRs and 8,724 B of scratch a lane; 75 % occupancy.

These are facts, not an explanation. A 4070 build with `-maxrregcount=64`
still compiled at 128 registers, so the register count's effect was not
tested.

**A correction to part 1** (approved by the lead), from the fixed path's
rate inside exp:
- The 5060 Ti runs 25.6 M fp256 exp lane-programs a second. That is at least 3.17 x 10^9 executions of the second kernel's code a second, through FMA, ADD, SUB and MUL.
- That means at most about 4,200 slots per FMA-class instruction on average, in fp256 exp at these arguments (COMPUTED from the MEASURED 25.6 M lane-programs a second).
- This bounds those 124 instructions' kinds together. ADD and MUL may run shorter paths when an operand is exactly 1 or 0, so it is not a general FMA's cost.
- So part 1's 14,900 slots per FMA, taken on part 1's own stream (`gen_corpus.py stream` replicated), were the slots available at that rate, not what the FMA spends.
- Part 1's BELIEVED "issue-bound" on NVIDIA is contradicted.
- The inputs differ between the two measurements: part 1's stream against exp's 4,096 uniform arguments.
- On the RX 7600 the comparison goes the other way: 0.9 x 10^9 FMA-class instructions a second inside exp, against part 1's 1.38 G/s at 1.5M lanes or fewer. MEASURED; not explained.

**The card** (READ): one tile runs an arithmetic instruction in 0.98 ns a lane
and a control code in about 4 ns, MEASURED there at fp32 (docs/BENCHMARKS.md
:452 to :466, docs/SEQUENCER.md :1624 to :1632); exp-f32 at about 2.6 M cases
a second a tile is COMPUTED there (docs/CARDDAY.md :2038 to :2040); the quad's
resident FMA is 1,664 M at fp64 and 427 M at fp256 (docs/ROADMAP.md :6879 to
:6882). No rate of the card for programs at fp64 or fp256 was found (those
files, HX-wide-sweeps.md and INTEGRATION.md), so the GPU's program rates have
no card figure to stand beside.

## P2.6 ADD, SUB and MUL through the fixed FMA

The runner's fp256 path takes FMA, ADD, SUB and MUL through `sf_steer`. That
is libcft's own steering, the same identities the RTL's operand mux uses:
- ADD = FMA(a, 1, c);
- SUB = FMA(a, 1, -c);
- MUL = FMA(a, b, +-0 by the product's sign).

The steering feeds `f256_fma_lane`. `cft_fma diff --op add|sub|mul` holds
each identity against `cft_sf_compute(op)` itself, results and flags, on
part 1's counter-based hard-case stream under the five attributes. For ADD
and SUB, a becomes fl(a x b), so the stream's cancellation and alignment
families meet a + c as they met a x b + c.

| device | cases an operation | differing |
|---|---|---|
| RTX 5060 Ti | 268,435,456 (2^28) | 0, 0, 0 |
| RTX 4070 | 67,108,864 (2^26) | 0, 0, 0 |
| RX 7600 | 67,108,864 (2^26) | 0, 0, 0 |
| CPU | 200,000 (seed 1) | 0, 0, 0 |

The first chunk hashes alike on every device: inputs 21ae7619... (add),
86ad800f... (sub), b0764272... (mul); outputs b2b0aa08... (add and sub alike)
and c59668cd... (mul). Part 1's FMA diff reproduces its own hashes from the
same build. The identities are used.

## P2.7 What was not run, and what a backend's sequencer would need

**Not run:**
- augmentedAddition (refused);
- index tables;
- other scratch depths;
- seq_check's other corpora through the runner: scratch, indexed, masked, rev8 and flags (the fuzz corpus covers their control codes, not their directed cases);
- the hard workloads (`programs/workloads/`);
- the runner on an MI300X (built for gfx942 on the RX 7600 machine: 74 VGPRs and 2,276 B at fp64, 148 and 9,156 B with the fixed path, refused there by name as a foreign image);
- fp32 and fp128 rates;
- `-maxrregcount`'s effect (the build did not take it).

**What a backend's sequencer would need.** By functions, as Logan answered.
Each round covers every precision libcft covers (fp32 to fp256):
1. **The executor as libcft's code.** Here it is copied by script and checked. A backend would rather have `program.c` split so that `seq_program_run`'s per-lane setup is a function both executors call. Then nothing of the run would be re-expressed, and this part's second implementation would go.
2. **The classes refused here:** `augmented.c` copied under E1 (AUGADD, AUGERR), index tables in the lane setup, and a handle's scratch depth.
3. **Residency:** program, bank and lanes on the device, one launch a run. A lane's registers live in its thread's local memory: 5,280 bytes at 40 limbs.
4. **Specialised arithmetic, by function.** The fp256 FMA class first: FMA, ADD, SUB and MUL by steering, 61 to 77 % of exp's, sin's and atan's instructions at fp256. Each is held inside the gates to the generic path.
5. **Per-card tuning:** the 4070's register allocation, untested.
6. **The gates:** every corpus here on every device, seq_check's eight corpora through the device, and the plants as controls.

**The coverage an overnight campaign would need** before it accepts a
second implementation (Logan's answer 3; ESTIMATE of what is enough):
- **the fixed kernel:** the conformance FMA corpus and VGPU-A's 747,560 hard cases on every build and device; `diff` and `diff --op` at 2^30 or more an operation on each device class, with the one-sided plant red; a golden-checked stream (part 1, section 9 (c)) as a referee that is not the generic kernel. The campaign: 2^40 differential cases an operation.
- **the runner:** seq_check's eight corpora through it (directed cases for every class); 10^4 fuzz programs a format with every arm, augmentedAddition included once copied; the systems and the hard workloads; both plants red. The campaign: 10^6 fuzz programs a format against libcft.

## P2.8 Records, GPU time and the RX 7600 job

- **The record:** `captured/programs.sha256` (the 21 corpora and reference outputs), `captured/part2-*.txt` (every run's log, paths removed).
- **The corpora are not committed.** `gen_programs.py` remakes them in about 80 s (MEASURED; it needs mpmath and pytest, as seq_check's routine corpus does), and the sums hold them.
- **Desktop GPU time in part 2:** about 6 minutes in all (COMPUTED from the logs).
- **The RX 7600 machine:**
  - every run was in `~/gpu-a`, with amd-smi before each GPU step;
  - the long jobs were launched detached, `ssh -n` with `nohup setsid bash SCRIPT > LOG 2>&1 < /dev/null &`;
  - each ended by itself, and `ps` showed nothing of them left when the log was collected.
- **hazards.sh's sanitizer rule** (VGPU-A's note on part 1, refined here): "not run" only when the tool's errors are exactly its two known sentences (no debugger interface, device not supported); a summary counting more, or another "Error:" line, is red. MEASURED on five fake outputs (not run, red, red, green, not run as intended); the captured NVIDIA section reads "not run" under both rules.
- **One install, approved:** `libmpfr-dev` 4.2.1-1build1.1 and `libgmp-dev` 2:6.3.0+dfsg-2ubuntu6.1 (with `libgmpxx4ldbl`) from Ubuntu's noble-updates into `cft-gpu`. Each .deb's sha256 equals the signed index's (the ledger).

## P2.9 Questions for Logan

1. **A backend round for programs?** The 5060 Ti runs fp256 exp at 25.6 M lane-programs a second, about 1,090 times one core of libcft's sequencer and 43 MPFR cores. Is that worth a round, and is exp's family, then trig, then the inverse functions the order?
2. **One executor, not two.** Should `program.c` be split so that its per-lane run setup is a function a GPU backend calls? That would remove this part's second implementation.
3. **The 4070.** Its fixed path is a third of the 5060 Ti's. Is a tuning study worth it, or is the 5060 Ti class (and the MI300X) the target?
4. **augmentedAddition next?** It is the one class this part refuses.
5. **The MI300X.** Should `run_mi300x.sh`'s new step 6 run with part 1's steps, if they are run?

## P2 appendix: commands

```
# corpora (this desktop, Windows Python 3.12 + mpmath 1.3.0 + pytest; ~80 s), then checked
python -B docs/studies/gpu-a/gen_programs.py PROGS --formats fp32 fp64 fp128 fp256 --golden
python -B docs/studies/gpu-a/gen_programs.py PROGS --census            # P2.5's census
# the reference (WSL cft-gpu): libcft.a from a copy of host/, one job
bash docs/studies/gpu-a/build_seq.sh ref WORK/ref
WORK/ref/seq_ref run PROGS/routines-fp64.bin PROGS/ref-fp64.out   # each corpus; and: bench
# every device: the runbook body (the desktop: DEVICE=1, then REUSE=1 DEVICE=0)
HIP_PATH=/opt/rocm-7.2.4 DEVICE=1 bash docs/studies/gpu-a/run_seq.sh nvidia PROGS WORK 89 120
bash docs/studies/gpu-a/run_seq.sh amd PROGS WORK gfx1102 gfx942    # the RX 7600 machine
# MPFR, one core
cc -O2 docs/studies/gpu-a/mpfr_bench.c -lmpfr -lgmp -o WORK/mpfr_bench && WORK/mpfr_bench PROGS/bench.bin
# the identities
WORK/fma-nv/cft_fma diff 268435456 20261110 --op add --device 1   # sub, mul; 2^26 elsewhere
```
