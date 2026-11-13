# GPU-D: libcft's arithmetic as OpenCL C, one host harness for Apple's GPU, AMD's, Intel's and any CPU

Study GPU-D of the GPU series, written 2026-11-11 by a study author (Opus 5.5) at Logan's word, branch
`gpu-d` from `21b98aec`; clocks are `date` on each machine. It follows [GPU-A](GPU-A-hip.md) (one HIP
source, bit for bit on NVIDIA and AMD) and [GPU-C](GPU-C-hip-intel-apple.md), which found the device copy
to be OpenCL C 1.2 by three edits, syntax only, with nothing built or run. Logan's words: 2026-11-10,
about 19:05, "Go ahead and dispatch a parcel to look into HIP compilation to Intel Arc and Apple Metal";
2026-11-11, on a second host harness over the same arithmetic text, "If thats the cleanest option then
its acceptable"; and about 05:30, "Dispatch the OpenCL C parcel now alongside M4".

Markings: MEASURED (run here, 2026-11-11), READ (with its path or URL), COMPUTED, ESTIMATE (with its
basis), BELIEVED (not checked); "not run" is said. The rule of GPU-A holds: the device runs **libcft's
own arithmetic** by a scripted, checked copy, and anything else is named a second implementation.

**A note of 2026-11-11, the lead's: the Arc A750 ran this study's bundle** (the study's text stays as written).
After Logan swapped an Arc A750 into amd-arc-box, the bundle of section 7, unchanged, ran there through Intel's
runtime from Canonical's archive. That needed the four packages GPU-C's runbook adds the same day (its dated
note): without them the build failed with OpenCL error -6 in 0.2 ms, log empty (MEASURED). With them, the run is
**ALL AS EXPECTED** (MEASURED):
- platform "Intel(R) OpenCL Graphics", OpenCL 3.0; device "Intel(R) Arc(TM) A750 Graphics", NEO driver 23.43.027642,
  448 compute units;
- clBuildProgram 2.2 s cold and 1.3 ms cached, log empty, `-cl-std=CL1.2`, the text `02efcc15...`;
- the three plants RED at GPU-A's planted outputs;
- conf-fp32 to conf-fp256 and stream-fp32 and stream-fp256 (1M lanes each) GREEN at their hashes, each confirmed
  by gen_corpus.py verify;
- fp256 FMA at 5.18e7 a second, kernel median of 10 at 1M lanes, work-group 1024 (2.69e7 end to end), against
  5.41e7 for GPU-C's chipStar build on the same card.
That this route needs libigdfcl1 itself stays BELIEVED: it was present in both runs.

**A note of 2026-11-13, the lead's: Logan's answers to questions 1 and 2** (the study's text stays as
written). Asked that morning with the lead's leanings, he answered, verbatim: question 1, Apple's
`-cl-opt-disable` (bit for bit on every corpus here, 3.6 times slower than the failing default), "Accept
for now"; question 2, a report to Apple, "Note it, dont chase it". So Apple's OpenCL runs with
`-cl-opt-disable`, and the reduced case is not built. The Mac's working folders, kept for it, were removed
the same day, after a look; the bisection's last output is kept in the lead's records.

## 1. The answer

1. **One OpenCL C text and one C host harness run libcft's FMA bit for bit on three devices** (MEASURED):
   - PoCL 7.2's CPU device on this desktop, and the RX 7600 through ROCm 10.1's OpenCL, at default build
     options;
   - Apple's M2 Pro GPU **only with `-cl-opt-disable`**.
   On each of them every corpus gives GPU-A's expected hash (conf-fp256 `da932116...`). The three plants
   go RED with GPU-A's planted outputs, byte for byte (the same wrong bits as on GPU-A's devices).
2. **Apple's GPU at default options is RED, by refusals** (MEASURED): 3,447 of conf-fp256's 18,360 cases,
   and 199,592 of stream-fp256's 1,000,000. Every differing lane was a refusal the harness caught
   (d = 0, flags 0x80), and none carried a wrong value. The cause is not pinned (section 6). A
   one-attribute change in a scratch variant moved the fault, and then 1,503 lanes did carry wrong
   values, so "it fails loudly" cannot be relied on there.
3. **The text is libcft's**: GPU-A's device copy, made OpenCL C by 19 exact, counted replacements: 7
   include lines and 12 of four kinds (section 3). One kind, O4, is **not syntax only**: it takes the
   recursive reduction tree out, because PoCL refused the whole program for it. The lane is GPU-A's
   `gpua_fma_lane`, taken from `cft_fma.hip` byte for byte at every build.
4. **On the RX 7600 the same arithmetic runs at the same speed through either runtime** (MEASURED, one
   session): 8.24 to 8.28 x 10^7 fp256 FMA/s through OpenCL against 8.30 to 8.31 x 10^7 through HIP,
   kernel only. Apple's M2 Pro, optimisation off, makes 8.6 x 10^6 by the host clock.
5. **The Arc bundle** (132 MB) is built and rehearsed on PoCL. The same bundle, unchanged, passed on the
   RX 7600. It needs only libOpenCL.so.1 and Intel's runtime, with libigdfcl1. Nothing ran on an Intel
   GPU: that run is the lead's, on amd-arc-box ([gpu-d/RUNBOOK-ARC.txt](gpu-d/RUNBOOK-ARC.txt)).

## 2. What was built ([gpu-d/](gpu-d/), 1,307 lines)

| file | lines | what it is |
|---|---|---|
| `oclcopy.py` | 322 | devcopy.py's output to ONE OpenCL C text: the edits counted, the lane extracted, the call-graph scan, `--check`, `--selftest` |
| `fma_kernel.cl` | 36 | the kernel: one work-item a lane, global bytes to private and back, the descriptor out of `__constant` |
| `cft_fma_ocl.c` | 473 | the host harness, C and the OpenCL 1.2 API, one source for Linux and macOS |
| `build_ocl.sh` | 34 | devcopy.py, oclcopy.py, then the harness and libcft's `sha256.c` by `cc` |
| `ocl_run.sh` | 77 | one device's checks: plants first, six corpora, the rate (Linux, or macOS's bash 3.2) |
| `make_bundle.sh` | 28 | the Arc bundle, built in cft-gpu |
| `RUNBOOK-ARC.txt` | 35 | the lead's run on amd-arc-box |
| `rp_probe.c` | 83 | diagnosis only, never the route: the reduced case of section 6, with a host plant |
| `captured/` | 219 | go/no-go builds, the PoCL rehearsal, the M2 Pro, the RX 7600 |

GPU-A's `devcopy.py`, `cft_fma.hip` (its lane only), `gen_corpus.py` and `build.sh` are used as they are.

## 3. The text, and its edits

`oclcopy.py DEVSRC OUT.cl` writes the text, checks it, and prints its sha256. MEASURED: 94,634 bytes,
2,448 lines, sha256 `02efcc1531f10bbdd32fa92a9d00e822d1648157d120eb99abc867347e67524d`. The same digest
was made by its own run on this desktop, in cft-gpu and on the M2 Pro MacBook. It holds, in order:
- a generated header naming every input by git blob id;
- the shim: the `<stdint.h>` typedefs in OpenCL C's types, and `CFT_HD` empty;
- `cft_config.h`, `bigint.h`, `softfloat.h`, `bigint.c` and `softfloat.c` from devsrc;
- GPU-A's lane and `fma_kernel.cl`.

Each part is preceded by `#line`, so a compiler names the original file and line.

Every edit is an exact string replacement with the number of matches it must find. A count that differs
refuses the copy and names the edit (devcopy's discipline):

| kind | where | matches | what | syntax only? |
|---|---|---|---|---|
| I | all five files | 7 | each `#include` line made a comment; the files are joined in include order, each keeps its guard; `size_t` and `INT_MAX` are OpenCL C's own | yes |
| O1 | softfloat.h, .c | 2 | the format table and its `extern` in `__constant` (OpenCL C 1.2 keeps program-scope data there) | yes |
| O2 | softfloat.c | 7 (6 strings) | the identifier `half` renamed `half_` in `cft_sf_canonical_ranges` (`half` is a type in OpenCL C); comments untouched | yes |
| O3 | softfloat.h | 1 | the table's `name` field a `__constant char *` (its initialisers are string literals) | yes |
| O4 | softfloat.c | 2 | `#if 0` and `#endif` on the blank lines around `cft_sf_reduce`, so the line count is kept | **no**: a function leaves the program |

**O4 is not syntax only.** It takes the reduction tree out of the program. MEASURED, in section 4:
- PoCL 7.2 refused the program without it: "Recursion detected in function: 'cft_sf_reduce'". OpenCL C
  1.2 has no recursion.
- The FMA never reaches the function: in the copy its only calls are its own two recursive ones. oclcopy
  checks this at every build. In the code outside the excluded lines, with comments and strings
  blanked, the identifier may appear once, as softfloat.h's prototype.
- PoCL alone enforced the rule. The same text without O4 (sha256 `4d48953f...`) built on Apple's and
  AMD's compilers with empty logs.
- With O4, PoCL builds the program. PoCL's check is not complete (MEASURED, 06:58; and VGPU-D's
  cases). I appended one uncalled recursive function to the text at a time:
  - PoCL flagged a non-static, non-tail recursive one ("Recursion detected in function: 'gpud_p'"),
    which is cft_sf_reduce's kind;
  - it built a static one, and tail-recursive ones of either kind.
- **No function left in the text recurses** (COMPUTED by oclcopy at every build, not left to a
  compiler).
  - Method: definitions are a name, a parameter list and a brace. Their edges are the defined names
    each body calls. The scan runs on the code with comments and strings blanked and O4's lines
    removed, and searches the graph for a cycle.
  - Result: 66 functions, 165 calls, no cycle.
  - Its plants: it refuses the text without O4 for "cft_sf_reduce -> cft_sf_reduce", a function that
    calls itself, and a static mutual pair.

**O4's known limit:** a later routine that calls `cft_sf_reduce` cannot go through this route until the
reduction has a non-recursive form. oclcopy refuses such a use at build time wherever the identifier is
written, because it counts the identifier as a token. The selftest refuses a call, a spaced call
`cft_sf_reduce (`, and a use by address. A name assembled by token pasting would not be seen; the
call-graph scan below covers recursion, not that.

**The lane is not a copy.** At every build `gpua_fma_lane` is taken from `cft_fma.hip` byte for byte,
from the line starting `CFT_HD static void gpua_fma_lane(` (line 68) through its closing brace (line
97). With `CFT_HD` empty it is OpenCL C, its pointers private. GPU-A's plants live in that lane, so
they are GPU-A's code too. `fma_kernel.cl` is this study's: it copies a lane's operands from global
memory into private bytes and back, and the descriptor out of the `__constant` table, because libcft's
functions take private pointers. GPU-A passed the descriptor by value for the same reason.

**How a change in host/src shows** (MEASURED, `oclcopy.py --selftest`, eleven plants, each refused by
name, captured/go-nogo.txt):

| change | how it shows |
|---|---|
| a line an edit matches is changed | the count is 0, not 1: refused |
| a second match appears | the count is 2: refused |
| a new `#include` | refused ("an #include survived the edits") |
| a use of `cft_sf_reduce`: a call, a spaced call, by address | refused by O4's token count |
| a recursive function, or a mutual pair | refused by the call-graph scan, naming the cycle |
| the lane changes in `cft_fma.hip` | the text's sha256 changes, and `--check` of an old text refuses it |
| the written text is edited | `--check` refuses it, naming the line |

A new use of `half` elsewhere would match nothing and fail to compile (BELIEVED). Every other change
to host/src flows into the text and its sha256, which every run prints.

## 4. The go/no-go builds (MEASURED, 05:44 to 05:48; logs whole in captured/go-nogo.txt)

| device | binary, ICD | clBuildProgram | log | work-group |
|---|---|---|---|---|
| PoCL 7.2, cft-gpu, 4 CUs, text before O4 | cft-gpu's gcc 13.3 build; OCL_ICD_VENDORS at GPU-C's `pocl.icd` | FAILED (-11), 2,069 ms | the recursion error above | - |
| PoCL 7.2, the text with O4 | the same | built, 1,791 ms | empty | 4,096 |
| Apple M2 Pro GPU, OpenCL 1.2 | the Mac's own build (Apple clang 21.0.0, `-framework OpenCL`); no ICD | built, 165 ms | empty | 256 |
| RX 7600 (gfx1102), AMD-APP 3684.0 | **the cft-gpu binary**; `~/gpu-d/vendors/amd.icd` with OCL_ICD_VENDORS; the system's ocl-icd loader; no LD_LIBRARY_PATH | built, 1,504 ms | empty | 256 |

The work-group is the kernel's CL_KERNEL_WORK_GROUP_SIZE on each device. The RX 7600 reports 4,796
bytes of private memory a work-item; Apple and PoCL report 0. The lead messaged GO at 05:50.

## 5. The harness, `cft_fma_ocl`

GPU-A's `cft_fma.hip` harness over the OpenCL 1.2 host API, written new (BELIEVED none of GPU-A's host
code could be kept: it is HIP and C++):
- **Commands:** `check CORPUS OUT|-`, `bench CORPUS` and `info`.
- **Options:** `--platform N`, `--device N`, `--reps R` and `--lanes N`, as asked. Added: `--cl FILE`
  (the text), `--opts S` (build options after `-cl-std=CL1.2`), and `--wg N`, a smaller work-group than
  the kernel's, for experiments. Any other option is refused, never ignored (GPU-A's rule).
- **Formats:** it reads GPU-A's corpora and writes GPU-A's output layout. Its last line has GPU-A's
  form, so the expected hashes and `gen_corpus.py verify` apply unchanged.
- **Every run prints:** the platform and device, the text's sha256 (by libcft's `sha256.c`), the build
  options, clBuildProgram's time and log, the work-group size, and a first launch of one lane, timed
  apart (a runtime that compiles at first launch does it there).
- **Three times:** the kernel by the profiling events; the kernel by the host clock (enqueue to clFinish,
  inputs already written); and end to end (writes, kernel, reads).

**Two things this harness had to learn** (MEASURED):
- **PoCL's stack.** At its own work-group of 4,096, PoCL runs a work-group on one thread of the process.
  At glibc's default 8,192 KB thread stack every run segfaulted; at 64 MB and 256 MB the same run was
  GREEN (captured/pocl-rehearsal.txt). `ocl_run.sh` raises its own soft stack limit to 64 MB, for its own
  process, so the work-group stays the runtime's. A GPU's lanes do not live on these stacks.
- **Apple's profiling events.** They report 2.77 ms for 1M fp256 lanes, which the host clock times at
  116.5 ms (COMPUTED: 42 times). On PoCL and the RX 7600 the two agree within 0.1 % and 7 %. Apple's
  rates below are by the host clock.

## 6. The runs, plants first (MEASURED; the text 02efcc15 on every device)

| device, options | plants (flip, rmm-as-rne, drop-flag) | conf-fp32/64/128/256 | stream-fp32, -fp256 (1M each) |
|---|---|---|---|
| PoCL 7.2, 4 CUs, default (the bundle unpacked fresh) | RED, at GPU-A's outputs `da932116`, `ffe3f2eb`, `f0ca15e0` | GREEN, `dd3d83be`, `3a8a9b2c`, `fcc92da3`, `da932116` | GREEN, `15545866`, `9c7f2f6e` |
| RX 7600, ROCm OpenCL, default (the same bundle) | RED, the same three | GREEN, the same four | GREEN, the same two |
| M2 Pro GPU, `-cl-opt-disable` on every build | RED, the same three | GREEN, the same four | GREEN, the same two |
| M2 Pro GPU, default | RED by refusals (they differ from GPU-A's) | RED by refusals | RED by refusals |

On the GREEN rows `gen_corpus.py verify` re-read every output file in Python and agreed (hashlib's
sha256, 0 results and 0 flags differing). On all three devices the plants differ exactly as on
GPU-A's, by attribute rne/rtz/rdn/rup/rmm:
- flip: 1 result (0/0/0/1/0), and its output is the golden one;
- rmm-as-rne: 51 results (0/0/0/0/51);
- drop-flag: 1,452 flags (290/291/290/291/290).

Full hashes: captured/*.txt and GPU-A's `captured/expect.sha256`. Device names and compile times:
- PoCL: "cpu-alderlake-12th Gen Intel(R) Core(TM) i5-12400F". Cold builds 1.2 to 1.8 s, then a first
  launch of 0.7 to 1.3 s (it compiles per work-group size); 34 to 61 ms from its cache.
- RX 7600: "gfx1102". Cold 1.50 to 1.53 s, 19 ms from comgr's cache; first launch 14 ms.
- M2 Pro: "Apple M2 Pro". 128 to 220 ms cold, 2.4 ms when cached. The first launch took 6 to 12 ms
  here and up to 16.1 ms in VGPU-D's runs (READ), so no large compile hides at the first launch.

**Apple at default options** (MEASURED, captured/m2pro.txt). Every differing lane is a refusal, d = 0
and flags 0x80: `cft_sf_compute` returned nonzero, and the harness counts that as a difference.
- conf-fp256: 3,447 of 18,360. By attribute (rne/rtz/rdn/rup/rmm): 871/29/829/847/871.
- stream-fp256: 199,592 of 1,000,000, by attribute 51,075/0/48,622/48,820/51,075.
- The other conformance formats: fp32 3,104, fp64 3,314, fp128 3,459.
- Repeated runs give identical counts. `--wg 32` and `--wg 1` give the same 3,447.

The stream's pattern fits the rounding increment: rtz never rounds up and refuses nothing there, and
`sf_round_at` refuses only if `cft_bn_inc` carries out of a 2,048-bit container. Conformance does not
fit it wholly, with 29 refusals under rtz. BELIEVED, from the code; not shown.

**Diagnosis, scratch variants only, never the route** (06:03 to 06:05 and 06:57, seconds of the Mac's
GPU in all):
- `__attribute__((optnone, noinline))` on any one of nine functions turned conf-fp256 GREEN. They were
  `cft_bn_inc`, `sf_round_at`, `sf_round_pack`, `cft_bn_shr`, `cft_bn_low_nonzero`, `sf_round_up`,
  `cft_bn_bit`, `sf_fma` and the lane. So did all of bigint.c, or either half of softfloat.c.
- `noinline` alone, on one function at a time:
  - on `sf_round_at`, `sf_round_pack` and `cft_bn_low_nonzero`, conf-fp256 turned GREEN;
  - on `sf_round_up` it got worse: 4,793 refused, by attribute 1,160/153/1,156/1,164/1,160. VGPU-D
    found the same;
  - on `cft_bn_bit` and `cft_bn_inc` it moved: 3,322 differed with 1,819 refused, and 485 refused, 97
    under each attribute;
  - on `sf_fma` and the lane, nothing changed.
- In the `cft_bn_bit` variant **1,503 lanes carried a wrong value that was not a refusal**: d = 0 and
  flags 0x00 where the golden model gives a non-zero result (case 9: want `4000080...`, flags 0x10).
- The reduced case, [gpu-d/rp_probe.c](gpu-d/rp_probe.c) (committed, diagnosis only). A probe kernel
  added to the text runs `cft_sf_round_pack` alone, the call the refusing path makes. It ran 4,096 fp256
  lanes shaped like `sf_fma`'s far path (a 239-bit significand, a sticky bit, every attribute) against
  libcft's own `softfloat.c` on the Mac's CPU (06:57; each line names its build options):
  - AGREES at `-cl-std=CL1.2` and at `-cl-std=CL1.2 -cl-opt-disable`;
  - its plant shows it can fail: with the host's rup lanes computed as rtz it DIFFERS on 377 lanes,
    all under rup, at both options.

**`cft_sf_round_pack` alone agrees on 4,096 lanes; the other functions were not reduced; the cause
stays unpinned.** Marking any one of nine functions optnone cures, which does not localise, and the one
reduced case agrees. So the ruling's second condition, a reduced case that differs at default against
the host, is not met. **The cause stays BELIEVED, with these candidates, not chosen between:**
- (a) a fault in Apple's optimiser: 64-bit operations lowered to 32-bit pairs, the carry chain, 64-bit
  division or remainder;
- (b) undefined behaviour in the source that UBSan and ASan cannot see, strict aliasing first. Against
  (b), MEASURED by a text search (grep) of the copy: no union, no `memcpy`, and no pointer cast but
  `reduce_leaf`'s byte reads, which O4 leaves uncalled; so no type-pun on the limbs. GPU-A's UBSan,
  ASan and `-ftrivial-auto-var-init` runs were clean (READ, GPU-A section 7). They ran on GPU-A's device
  copy (E1), not on this text with its O edits.

The discriminating test the lead suggested, `-cl-strict-aliasing` on the RX 7600, ran GREEN, but AMD's
compiler warned "OpenCL C version 1.2 does not support the option" (MEASURED). It discriminates
nothing.

**The rates, fp256 FMA, 1,000,000 lanes, median of 10** (MEASURED; the stream corpus):

| device | build options | kernel, events | kernel, host clock | end to end |
|---|---|---|---|---|
| PoCL 7.2, 4 CUs (work-group 4,096) | default | 2.99 x 10^6/s | 2.99 x 10^6/s | 2.71 x 10^6/s |
| RX 7600, OpenCL, work-group 256 | default | 8.24 x 10^7/s | 7.81 x 10^7/s | 3.08 x 10^7/s |
| RX 7600, OpenCL, work-group 128 | default, `--wg 128` | 8.28 x 10^7/s | 7.78 x 10^7/s | 3.06 x 10^7/s |
| RX 7600, HIP (GPU-A's `cft_fma`, rebuilt), block 128 | GPU-A's `build.sh amd` | 8.30 x 10^7/s | - | 3.24 x 10^7/s |
| RX 7600, HIP, block 256 | the same | 8.31 x 10^7/s | - | 3.23 x 10^7/s |
| M2 Pro GPU | `-cl-opt-disable` | (3.6 x 10^8/s, not trusted) | 8.59 x 10^6/s | 8.19 x 10^6/s |
| M2 Pro GPU, a RED build: prices the optimiser only | default | (1.3 x 10^9/s, not trusted) | 3.06 x 10^7/s | 2.57 x 10^7/s |

The RX 7600's rows come from the comparison run at 06:09. ocl_run.sh's own run at 06:08 gave 8.23, 7.73
and 3.06 x 10^7.

The commands:
- OpenCL: `cft_fma_ocl bench corpus/stream-fp256.bin --reps 10` (ocl_run.sh, plus `--wg 128` for
  that row).
- HIP: `cft_fma bench stream-fp256.bin --block 128 --reps 10`, GPU-A's bench.sh line, built this
  session in `~/gpu-d/hip` by GPU-A's `build.sh amd gfx1102`.

Same arithmetic, two runtimes, one card, one session: OpenCL's kernel rate is 0.991 and 0.998 of
HIP's, and its end to end 0.952 and 0.946 (COMPUTED). GPU-A recorded 7.74 x 10^7 for HIP on this card
on 2026-11-10, with a resident server holding 6.1 GB of it (READ). Today the card had no other GPU
process (MEASURED, amd-smi).

Apple's optimisation off costs 3.6 times its default build's time (COMPUTED). Its honest rate is 0.11
of the RX 7600's through OpenCL, and 0.020 of the quad's 427 M with resident data (COMPUTED; the 427 M
READ from GPU-A section 8).

Load during the runs:
- this desktop: Windows CPU load 0 to 9 % (MEASURED, Win32_Processor), other parcels light;
- the M2 Pro: load average 2.0 to 2.5, WindowServer about 45 % and Chrome about 55 % of a core, Logan's
  own use;
- the RX 7600 machine: idle.

## 7. The Arc bundle, and its rehearsal

`make_bundle.sh` builds in cft-gpu (Ubuntu 24.04, amd-arc-box's glibc) and packs:
- the harness, whose `ldd` is libOpenCL.so.1 and libc only;
- the text, the six corpora and the flipped one;
- `ocl_run.sh`, GPU-A's `gen_corpus.py` and SHA256SUMS.

MEASURED: 132,403,803 bytes, sha256 `1da16f887be1f5a49d1eef900cb51410b37fa6dbe95d0ad1d30a7fe0a17b3536`.
Unpacked in a fresh directory and run on PoCL: ALL AS EXPECTED (captured/pocl-rehearsal.txt). Copied to
the RX 7600 machine and run there unchanged: ALL AS EXPECTED.

The bundle is not byte-reproducible, and a rebuild differs in the harness binary's bytes. VGPU-D's
rebuild had the same size and the same contents but the binary, and sha256 `096efb32...` (READ,
VGPU-D). The binary embeds its build path, `/root/gpu-d/tree/docs/studies/gpu-d/cft_fma_ocl.c`, from
the `CK` macro's `__FILE__` (MEASURED, `strings`). That is one cause; others are not excluded. Check a
rebuilt bundle by its SHA256SUMS and its run, not by the tarball's digest.

**libigdfcl1: yes, BELIEVED needed.** This route hands NEO OpenCL C source, which NEO compiles through
its OpenCL C front end. GPU-C's route handed it SPIR-V. GPU-C's install list already holds the package,
so the box needs nothing beyond that list. The planted builds are build options, so no planted binary
is packed. The lead's steps are in [gpu-d/RUNBOOK-ARC.txt](gpu-d/RUNBOOK-ARC.txt). Not run on an Intel
GPU.

## 8. What this route costs, and what it does not cover

- **The edits** are in section 3: I, O1, O2 and O3 syntax only; O4 not. The kernel file is 36 lines
  of this study's and moves bytes only; the harness is new.
- **The program runner (GPU-A's `cft_seq.hip`) through OpenCL, ESTIMATE, not built.** Basis, READ from
  `cft_seq.hip` and `program.c`: the copied executor holds pointers into global memory, namely the
  instructions, the constant bank, the per-lane scratch (256 slots of 260 bytes a lane by default) and
  the deposits. `seq_src` returns a pointer that is a register (private) or a constant or scratch slot
  (global).
  - OpenCL C 1.2, Apple's only version, has no generic address space, so that function cannot be
    written without restructuring: a second implementation of part of the executor, its own proof, and
    Apple's optimiser question on top. ESTIMATE 3 to 5 days, low confidence.
  - OpenCL C 2.0 makes an unqualified pointer generic (BELIEVED). With `-cl-std=CL2.0` on AMD, Intel
    and PoCL, the same copied executor would probably need no address-space edit. The host side is a
    port of `cft_seq.hip`'s 693 lines, most of them harness. ESTIMATE 1 to 2 days, **on a thin basis**:
    - this study's FMA path went from the first line of oclcopy.py to GREEN on the third device in 28
      minutes (05:40 to 06:08), with a harness of 473 lines;
    - the runner's host side is larger, its program images and scratch have no OpenCL counterpart yet,
      and its device side has not been compiled once;
    - the 1 to 2 days is a judgment, not a measurement.
  - Its atomics, OR and min, are `atomic_or` and `atomic_min` on global 32-bit integers: core since
    OpenCL 1.1 (BELIEVED). Apple lists `cl_khr_global_int32_extended_atomics` (MEASURED, `info`).
- **Not covered:** GPU-A's second kernel (`fma256_fixed.h`), the `diff` stream, the hazard runs, NVIDIA's
  OpenCL, and any Intel GPU.

## 9. Recommendation (mine)

| target | route | cost (ESTIMATE, basis) |
|---|---|---|
| **Intel Arc** | run this bundle and GPU-C's chipStar bundle in the same box session after the swap; Intel's runtime extracted once serves both | about 30 minutes more of the lead's time than GPU-C's run alone; basis: this bundle's 30 s on the RX 7600 and the shared extraction |
| Intel, longer term | if both are GREEN, the OpenCL C text: no chipStar, no LLVM on the box, NEO alone; chipStar keeps the one HIP source and the runner already | the choice is Logan's (questions) |
| **Apple** | this route works with `-cl-opt-disable` and no other way found. Keep it as a correctness leg and a demonstration, not as a backend: Apple deprecated OpenCL (READ, GPU-C), it is 0.11 of an RX 7600, and its default build fails. Any Apple route keeps the plants and corpora as its gate on every build: section 6 shows a small change in inlining turning refusals into wrong values | none further now; Metal is GPU-C's third Apple route, untried |
| AMD, NVIDIA | HIP stays the route: the same rate on the RX 7600, and the runner exists. This harness is the cross-check | none |
| any CPU | PoCL, with `ocl_run.sh`'s stack limit | none |

## 10. Questions for Logan

1. **Apple:** accept `-cl-opt-disable` as Apple's build option (bit for bit on every corpus here, 3.6
   times slower than the failing default)? Or treat Apple's OpenCL as unsupported until the cause is
   pinned?
2. **A report to Apple** would need a reduced case (not built) and your account. Worth an hour?
3. **The Arc:** both bundles in one session after the swap?
4. **O4:** keep the reduction tree out of the OpenCL text, or give `cft_sf_reduce` a non-recursive form
   in host/src in a backend round? It would then need its own gates.
5. **The runner through OpenCL:** target OpenCL C 2.0 (AMD, Intel, PoCL; not Apple), or leave the runner
   to HIP?

## 11. Not run, not read

Not run:
- any Intel GPU; NVIDIA's OpenCL; GPU-A's second kernel, `diff`, hazards and runner through OpenCL;
- a reduced case that reproduces Apple's fault (`cft_sf_round_pack` alone did not);
- `-cl-strict-aliasing` on PoCL;
- stream-fp64 and stream-fp128 through this harness (made, not run);
- `--lanes` beyond 1M.

Not read: Apple's OpenCL documentation; NEO's documentation on libigdfcl.

Apple's compiled programs are cached by the OS, outside `~/gpu-d` (BELIEVED, as with the lead's probe).
That cache is not this study's to clear.

## 12. Record and removal

The ledger is `Data/runs/2026-11-10-gpu-a/ledger/GPU-D.md`: every run, every read, and the times.
Removal:
- cft-gpu: `rm -r /root/gpu-d` (sources, corpora 247 MB, the bundle, PoCL caches).
- The M2 Pro MacBook and the RX 7600 machine: `rm -rf ~/gpu-d` (the lead's). On the RX 7600 machine it
  holds the ICD file, comgr's cache and the HIP build.

Nothing was installed anywhere.
