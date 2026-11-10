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
red on every device they were run on.

**What the generic port costs.** The first kernel runs `host/src/softfloat.c`
and `bigint.c` as they are. At fp256 it makes 77 to 175 M FMAs a second,
kernel only (MEASURED). That is 0.18 to 0.41 of the quad's 427 M with
resident data (READ).

**What a specialised kernel reaches.** The second kernel is a second
implementation of the fp256 FMA on fixed limbs in registers. It makes 0.89
to 1.38 G a second, kernel only (MEASURED): 2.1 to 3.2 times the quad. It is
held bit for bit to:
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
- the generic kernel reaches 0.8 to 1.8 x 10^8, an order of magnitude below the ESTIMATE's floor;
- the specialised kernel reaches 0.9 to 1.4 x 10^9, inside its lower half.

The MI300X would most likely land inside the range for the specialised
kernel (ESTIMATE, sections 8 and 9).

## 1. What was built

All of it is in `studies/gpu-a/` (2,076 lines of code and runbooks, 385 of
captured output).

| file | lines | what it is |
|---|---|---|
| `devcopy.py` | 168 | the scripted copy of libcft's arithmetic for device code, and its check (section 2) |
| `cft_fma.hip` | 752 | the one source: both kernels, the CPU path, the test generator, the harness (`check`, `bench`, `diff`, `info`) |
| `fma256_fixed.h` | 366 | the second kernel: an fp256 FMA on fixed limbs, a second implementation |
| `gen_corpus.py` | 231 | the corpora from the golden model; the bit-flip plant; an independent verifier |
| `build.sh` | 92 | one build line per target: `cpu`, `cpu-libcft`, `nvidia`, `amd` |
| `run_checks.sh`, `bench.sh`, `hazards.sh` | 27, 28, 90 | every corpus through one build, the rates, the compilers' hazards |
| `run_wsl_nvidia.sh`, `run_amd.sh` | 92, 84 | the desktop's runbook and the AMD body |
| `run_rx7600.sh`, `run_mi300x.sh` | 29, 61 | the two AMD runbooks |
| `toolchain_check.hip` | 56 | the smallest program that proves a toolchain and device |
| `captured/` | 385 | the corpora's sums, the expected outputs' sums, the final runs' summaries |

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
- The RX 7600 machine runs ROCm 10.1 in AMD's new `amdrocm` packaging (`repo.radeon.com/rocmradeon/apt/26.16`). That repository has no `hipcc`, `hip-runtime-nvidia` or `hipother` package.
- HIP's current install page (HIP 7.18, ROCm 10.1's documentation) no longer mentions NVIDIA.
- The last release that packages the NVIDIA platform is 7.2.4 (`repo.radeon.com/rocm/apt/7.2.4`: `hip-runtime-nvidia`, `hipcc-nvidia`).

So the NVIDIA leg runs HIP 7.2.4 and the AMD leg HIP 7.16. The source is the
same, and its results and hashes are the same on both.

How one source on CUDA survives this:
- **(a) HIP 7.2.4, frozen,** is what was installed and what works today. It is three .debs, 0.6 MB, header-only on NVIDIA.
- **(b) A study header of its own.** It would map the 17 HIP runtime calls the harness uses onto CUDA's under plain nvcc: malloc, memcpy, events, device properties, occupancy, limits, errors. It is not built, because (a) works. ESTIMATE: 60 to 80 lines of `#define`s and two inline functions, with no change to either kernel, since `__global__`, `__host__ __device__`, `threadIdx` and `atomicAdd` are already CUDA's.
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
- this desktop, 16:07 to 16:11 (`captured/desktop-checks.txt`, `bench.txt`, `hazards.txt`);
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
  - NVIDIA: the only floating-point opcode in either FMA kernel is `HFMA2 R, -RZ, RZ, 0, imm`, nvcc's constant move. Its fp16 immediates 2^-24 to 2^-17 are the integers 1, 2, 4, 16 and 128. There are 378 in the first kernel and 148 in the second, on sm_120 only; sm_89 has none. I2F, MUFU.RCP and F2I appear in the generator alone.
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
  - compute-sanitizer: under WSL it asks for `EnableDebuggerInterface.bat` run as administrator, a Windows change that was not made;
  - `-ftrivial-auto-var-init` on NVIDIA, which nvcc does not have;
  - valgrind and MemorySanitizer, which were not installed; the auto-var-init pair stands in.

**Hazards found in the harness and the toolchain,** each fixed or worked
around and recorded in the ledger:
- N1 to N3 and `gcnArchName` (section 3).
- An apostrophe inside `${HIP_PATH:?...}` opened a quote in bash.
- `hipcc --version | head -1` under `pipefail` stopped the build on SIGPIPE.
- Python's `write_text` on Windows put CRLF into `build.sh`.
- An RX 7600 binary built before `--case` existed ignored the flag and timed the wrong thing. The harness now refuses any option it does not know (MEASURED).
- On the 5060 Ti, single-shot `check` timings of some binaries carried about 300 ms of first-launch cost. This was not explained; it changes no result, and the rates come from `bench`'s warmed medians.

## 8. Throughput

**Method.** `bench.sh` runs each corpus through `cft_fma bench`:
- one warm-up, then 10 timed repetitions (3 on the CPU);
- kernel time by events; end to end as host-to-device copies, kernel and copies back, in pageable memory;
- each repetition allocates, copies and frees, so the end-to-end figure is a per-call cost.

Batches are the stream's 1,000,000 lanes, or 4,000,000 replicated. The
medians are below, with min/max in `captured/bench.txt`.

Conditions:
- Clocks were not controlled, and `nvidia-smi` read 2.5 to 2.9 GHz under load.
- The 4070 drives the display, hence its wider spread.
- The RX 7600 shared its card with an idle resident llama-server holding 6.1 GB of its 8 GB (Logan's word: sharing is fine). Its runs used at most about 0.7 GB.
- Load averages were 0.1 to 0.6.
- The CPU figures are one core of this desktop's i5-12400F under WSL, one thread, `-O2`.

**fp256, MEASURED (final runs, block 128).** Kernel only, 1M lanes (4M);
then end to end at 1M:

| device | first kernel | second kernel | end to end (first / second) |
|---|---|---|---|
| RTX 4070 (sm_89, 46 SMs) | 175.3 M/s (172.0) | 1,079 M/s (1,069) | 44.7 / 48.2 M/s |
| RTX 5060 Ti (sm_120, 36 SMs) | 143.3 M/s (146.6) | 887 M/s (935) | 34.6 / 40.9 M/s |
| RX 7600 (gfx1102, 16 "CUs" to HIP) | 77.4 M/s (77.8) | 1,383 M/s (803*) | 31.5 / 51.0 M/s |
| one CPU core, device copy | 461 ns (366 ns) | 327 ns (314 ns) | - |
| one CPU core, libcft's C | 450 ns (447 ns) | - | - |

\* The RX 7600's second kernel at 4M lanes is an anomaly: 803 M/s, against
1,383 M/s at 1M. It is BELIEVED to come from the 1.9 GB of VRAM the resident
process leaves free. It was not shown.

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
| first kernel, times the quad | 0.41 | 0.34 | 0.18 |
| second kernel, times the quad | 2.5 | 2.1 | 3.2 |

- Against `mpfr+754`'s 71 ns a core (READ): the first kernel is 5.5 to 12.4 cores, and the second 63 to 98.
- Against libcft's own C on one core here (450 ns): the second kernel is 400 to 620 cores.
- The end-to-end rates compare with nothing of the card's. The card's 427 M is with resident data, and its per-call path costs about 35 µs a run (READ, the same section). Neither was measured here.

**The roadmap's ESTIMATE** (10^9 to 10^10 on a large GPU, low confidence),
against the measurements:
- Its basis was about 1,000 32-bit operations an fp256 FMA. The first kernel spends about 38,000 lane-instruction slots per FMA (COMPUTED: 1.32 x 10^13 slots a second on the 5060 Ti at 2.87 GHz, over 346 M FMAs a second with every lane on one case). The second spends about 14,900.
- The ESTIMATE was an order of magnitude high for the generic port. It holds for the specialised kernel, which already reaches its floor on mid-range cards.

**What limits the first kernel** (MEASURED; desktop and RX 7600 experiments in
the ledger):
- **Not the container.** 38 limbs make 146 M/s against 143 to 145 at 64 on the 5060 Ti, and 82.9 against 78.1 on the RX 7600. The code touches only `n` limbs.
- **Not occupancy.** It is 100 % at blocks 64 to 256 on every card, and the block size moves nothing.
- **Divergence, by 2.1 to 3.5 times.** With every lane on one case (near with like signs, near with unlike signs close, near with unlike signs apart, far), the 5060 Ti makes 302 to 419 M/s and the RX 7600 168 to 273 M/s, against 143 and 78 for the mixed stream.
- **The instruction count of a portable bignum.** Loops of data-dependent length, bit-at-a-time helpers (`u32_bitlen`, `sf_set_field`), and every limb in local memory: thousands of LDL/STL and scratch instructions statically.

**What limits the second kernel:**
- Divergence costs 0 to 7 % (one case a lane: 903 to 957 M/s on NVIDIA, 1.46 to 1.48 G/s on the RX 7600).
- Its register count holds NVIDIA's occupancy at 33 % (sm_89) and 67 % (sm_120) (MEASURED).
- On the RX 7600 it moves 130 bytes an FMA at 1.38 G/s, about 180 GB/s (COMPUTED). That is close to the card's 288 GB/s (BELIEVED, its specification), so with operands streamed from memory it is near that card's bandwidth.
- On NVIDIA it uses about a quarter of the memory bandwidth, so it is BELIEVED issue-bound there.

**A tuned kernel** (ESTIMATE, medium-low confidence) might gain 1.5 to 3
times on NVIDIA:
- 64-bit limbs where the hardware has wide multiplies;
- fewer selects in the shifters;
- `__launch_bounds__` tuned for occupancy.

With resident data it would gain more on AMD, where bandwidth binds.

**The MI300X, ESTIMATE until measured.**
- **The second kernel: 0.8 to 1.5 x 10^10 a second.** Basis:
  - 304 CUs against the RX 7600's 32, at a similar clock (BELIEVED, the specifications; HIP reports the 7600's as 16, BELIEVED to be its work-group processors);
  - wave64 giving up the per-CU throughput that the 7600's dual issue gives (BELIEVED);
  - 5.3 TB/s of HBM against 288 GB/s (BELIEVED, the specifications).
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
- **Residency, or the speed is lost.** End to end is 31 to 51 M/s against 0.9 to 1.4 G/s kernel only. The backend needs `cft_alloc`'d device copies under `cft.h`'s authority rule, as the card's resident mode has. A program's registers should live on the device, as the sequencer's model already wants: one instruction stream, many lanes, one thread a lane.
- **The flags.** A call's flags are an OR over its lanes, which atomics compute deterministically, since OR is associative and commutative. `cft_reduce`'s sums keep their fixed tree, a kernel per level, never an atomic add on values.
- **`host/src`.** E1 behind a `CFT_HD` header (section 2). Nothing else in the arithmetic needs to change for device code (MEASURED by this study's build).
- **The NVIDIA leg.** HIP 7.2.4 frozen, the study header of section 3 (b), or `hipother` from source. This is Logan's choice (questions).
- **The gates.**
  - the conformance corpus through the backend, as `--device sw` and the card are run;
  - `host/tests/seq_check.py` through a device handle;
  - the photograph stage;
  - a differential stream of the specialised kernels against the generic one on every device in the round;
  - the plants of section 5 kept as controls.
- **The sequencer on the GPU** is sketched only: `program.c`'s interpreter as device code under E1, one thread a lane, its registers in local memory for the generic tier. Its cost is unmeasured, and the first kernel's local-memory traffic suggests the same order as section 8's generic rates (ESTIMATE).

## 11. Questions for Logan

1. **A backend round?** With a specialised fp256 kernel held to libcft's own code on the GPU, a 5060 Ti or RX 7600 runs fp256 FMAs at 2 to 3 times the quad's resident rate, kernel only. Is that worth a round, and which first: fp256 FMA/ADD/SUB/MUL, or fp128 too?
2. **The NVIDIA leg.** HIP's NVIDIA platform is packaged only up to ROCm 7.2.4. Keep HIP 7.2.4 frozen, build `hipother` from ROCm's sources, write the study's small CUDA header, or drop NVIDIA from the backend?
3. **Specialised kernels in the contract.** The second kernel is a second implementation. Its agreement is evidence by test (73,780 conformance, 1,000,000 stream and 2.4 x 10^9 differential cases), not a proof. Is "generic as reference inside the gates" enough, or should a specialised kernel need a proof (an exhaustive small-format analogue, say)?
4. **The MI300X.** Which of section 9's runs (a) to (d) are worth its time, if any? Each needs your word.
5. **The CPU too?** The first kernel's cost on one CPU core is about 450 ns an fp256 FMA, against mpfr+754's 71 ns. Most of it is the portable bignum's bit-at-a-time helpers. Should `host/src` get faster helpers on every platform, behind the same vectors?
6. **This desktop's distro `cft-gpu`.** Keep it for the verifier and a later round, or remove it after the merge?
7. **The RX 7600 machine's resident llama-server** holds 6.1 GB of the card. Is it to stay? It may explain the 4M-lane anomaly.

## Appendix: commands

All run from the tree's root, on the machine named. `CORPUS` and `WORK` are
directories outside the tree.

```
# corpora (this desktop, Windows Python 3.12 + mpmath 1.3.0; ~1 min)
python -B docs/studies/gpu-a/gen_corpus.py conformance CORPUS --jobs 2
python -B docs/studies/gpu-a/gen_corpus.py stream CORPUS --jobs 2
(cd CORPUS && sha256sum -c TREE/docs/studies/gpu-a/captured/corpus.sha256)
# the desktop's NVIDIA leg and both CPU legs (WSL cft-gpu; ~1.5 min)
HIP_PATH=/opt/rocm-7.2.4 bash docs/studies/gpu-a/run_wsl_nvidia.sh CORPUS WORK
bash docs/studies/gpu-a/bench.sh WORK/build/nvidia/cft_fma nv1 CORPUS --device 1
FORMATS=fp256 bash docs/studies/gpu-a/bench.sh WORK/build/nvidia/cft_fma nv1-fixed \
    CORPUS --device 1 --kernel fixed          # likewise --device 0 for the 4070
BLOCKS=1 REPS=3 bash docs/studies/gpu-a/bench.sh WORK/build/cpu/cft_fma cpu CORPUS
bash docs/studies/gpu-a/hazards.sh cpu CORPUS WORK
bash docs/studies/gpu-a/hazards.sh nvidia CORPUS WORK --device 1
# the RX 7600 machine (ROCm 10.1; ~2.5 min): run_rx7600.sh's header lists
# the copy, then its runbook, bench.sh for both kernels and hazards.sh amd
# the experiments of section 8 (container, one case a lane)
DEFS="-DCFT_BN_LIMBS=38 -DCFT_NO_TRANSCEND" bash docs/studies/gpu-a/build.sh nvidia WORK/l38
WORK/l38/cft_fma bench CORPUS/stream-fp256.bin --device 1 --block 128
cft_fma bench CORPUS/stream-fp256.bin --block 128 --lanes 1000000 --case 5   # 5, 4, 1, 2
```
