# GPU-E: what fills an MI300X with IAS15 - a Saturn-like ring, sized

Study GPU-E, written 2026-11-11 by a study author (Opus 5.5) at Logan's word,
the sixth of the GPU series. Branch `gpu-e` from `53ec490b`. Its cost model,
run script and captured outputs are in `studies/gpu-e/`. Nothing outside
`studies/` and the index changed, and nothing in cft-rebound changed.

> "When time comes to run the MI300X trials, I'd also like to do an IAS15 run,
> but utilizing as many resources from the MI300X as possible, perhaps
> something 'simple' but highly parallel like hundreds of thousands of bodies
> in a ring around a world? Similar to Saturn." (Logan, 2026-11-11)

**This is a paper study.** No GPU kernel was written and nothing ran on a GPU.
The MI300X's time is AMD's and not yet approved. The measurements are IAS15
runs on this desktop's CPU, from a clone of cft-rebound in WSL.

Every figure is marked: **MEASURED** (run here; `studies/gpu-e/run_ring.sh`,
captured in `studies/gpu-e/captured/ring_runs.txt`), **READ** (a page or a
file, named), **COMPUTED** (arithmetic on the others, in
`studies/gpu-e/cost_model.py`), **ESTIMATE** (a judgment, with its basis) or
**BELIEVED** (taken on trust, not checked). "Not run" means not run.

## The answer (the recommendation is mine; the choices are Logan's)

1. **Run a test-particle ring, one wave a system:** each 64-lane wave holds 57 massless ring particles with Saturn (J2, J4) and six moons, each wave with its own adaptive step; 10^6 particles in the annulus 130,000 to 142,000 km (the Encke gap with Pan, the Keeler gap, the A ring's edge, the F ring between Prometheus and Pandora).
2. **binary128 at epsilon 1e-9 for 10 orbits (5.8 days), binary64 on the same steps beside it, binary256 on a tenth of the waves** (ESTIMATE, generic tier: 1.4 to 3.3 h, 0.4 to 0.9 h and 3.2 to 9.2 h; specialised: 7 to 12 min, 2 to 3 min, 15 to 35 min).
3. **It fills the device by occupancy** (17,544 waves against 6,080 to 7,296 resident), not by memory (2.5 % of HBM held, at most 3.1 % of its bandwidth). Every lane is live, so the integer issue it reaches is the arithmetic kernel's own, unmeasured on any AMD GPU; 7 lanes of 64 carry Saturn and the moons.
4. **Built first:** a divide and a square root callable inside a kernel (none is: divsqrt.c's run on the host; mine, the sequencer's divfull and sqrtfull on the device's executor), the IAS15 wave kernel, J2 and J4 in libcft's format, and the replay check against cft-rebound's CPU engine. The ladder is the RX 7600 at 3 x 10^4 particles and the 5060 Ti at 10^5.
5. **Fallback:** 3 x 10^5 particles, 3 orbits, binary128 and binary64 (generic, 9 to 25 min and 2 to 7 min). A self-gravitating ring costs 10^3 times the test-particle ring at 10^5 bodies and 5 x 10^4 times at 10^6 (an orbit at 10^6: 1.4 to 3.4 years generic).

The one finding that changes a plan: **divide and square root are 58 % of a
substep-pass** (COMPUTED, binary256): 74 % of the force, which is 79 % of the
substep-pass. A specialised FMA, ADD and MUL alone (round 3's first kernels)
speed the ring by x1.5 to x1.7, not x7 to x30, unless the divide and square
root ride on them.

## 0. Sources and what was not done

READ in cft-rebound (7a7a279, read only; its `git status` and HEAD were the
same before and after, `?? bash.exe.stackdump` only): README.md, src/ias15_limits.h,
docs/ENSEMBLE.md, docs/HARDWARE.md, docs/HORIZON.md, docs/VALIDATION.md (the
ensemble and replay entries), src/ias15_cft.c. In this repository:
studies/GPU-A-hip.md, docs/BENCHMARKS.md, G1A's tree at `066dde9f` by
`git show`, and the GPU backend's round-1 plan. The web pages are named where used.

MEASURED: cft-rebound and its pinned cft-fp256 (`922c2ad`) cloned from this
desktop's repositories into WSL cft-gpu, `make -j4 build/ias15_cft` (10 s, no
warning), and 23 runs of `ias15_cft`, one at a time, 3 to 103 s each
(2026-11-11 11:23 to 11:38; WSL load 0.8 rising to 5.1, the desktop busy with
other parcels). Not run: anything on a GPU, any register or scratch count of
an IAS15 kernel, any collision or J2 run (the standalone program has neither).

## 1. What "fully utilized" means here

**The device, READ:**

| | MI300X (gfx942) | source |
|---|---|---|
| compute units | 304: 8 XCDs of 38 active (40 built) | [ROCm GPU specs](https://rocm.docs.amd.com/en/latest/reference/gpu-arch-specs.html), [ROCm MI300](https://rocm.docs.amd.com/en/latest/_sources/reference/gpu-arch/mi300.md) |
| SIMDs a CU | 4, each 16 lanes; a wave is 64 lanes | [HIP hardware implementation](https://rocmdocs.amd.com/projects/HIP/en/latest/understand/hardware_implementation.html); GPU specs |
| waves a SIMD | 8 waveslots on CDNA2; not stated for CDNA3, BELIEVED 8 | [rocprofiler-compute, pipeline descriptions](https://rocm.docs.amd.com/projects/rocprofiler-compute/en/latest/conceptual/cdna/pipeline-descriptions.html) |
| registers | 512 KiB VGPR file a CU; 512 registers a lane, VGPRs and AGPRs together (the AGPRs after the VGPRs rounded up to 4), allocated in 8s | GPU specs; LLVM [AMDGPUTargetParser.cpp](https://github.com/llvm/llvm-project/blob/main/llvm/lib/TargetParser/AMDGPUTargetParser.cpp) (`getTotalNumVGPRs`, `getVGPRAllocGranule`), [AMDGPUBaseInfo.cpp](https://github.com/llvm/llvm-project/blob/main/llvm/lib/Target/AMDGPU/Utils/AMDGPUBaseInfo.cpp) |
| SGPRs, LDS | 12.5 KiB; 64 KiB a CU | GPU specs |
| caches | L1 32 KiB a CU; L2 4 MiB a XCD (32 MiB); Infinity Cache 256 MiB | GPU specs |
| HBM | 192 GiB at 5.3 TB/s | GPU specs; ROCm MI300 |
| FP64 vector | 81.7 TFLOPS, 128 FLOPS a clock a CU | ROCm MI300 |
| 32-bit integer add and multiply | one issue slot each on gfx942 (`WriteIntMul` 1, `Write32Bit` 1); BELIEVED to be the hardware's rate | LLVM [SISchedule.td](https://github.com/llvm/llvm-project/blob/main/llvm/lib/Target/AMDGPU/SISchedule.td), `SIDPGFX942FullSpeedModel` |

COMPUTED: the clock is 81.7 x 10^12 / (128 x 304) = **2.10 GHz**, and the
32-bit issue rate is 4 x 16 x 304 x 2.10 GHz = **4.09 x 10^13 lane-instructions
a second**, adds and multiplies alike. AMD's data sheet and product page timed
out when fetched, so the clock is derived rather than read.

GPU-A's gfx942 builds (READ, GPU-A-hip.md:532-533 and
gpu-a/captured/part2-rates.txt:116-118; compiled, never run):

| kernel | VGPRs | scratch a lane | waves a SIMD | lanes resident (COMPUTED) |
|---|---|---|---|---|
| generic fp256 FMA (libcft's code) | 36 | 5,068 B | 6 | 466,944 |
| specialised fp256 FMA | 94 | 272 B | 5 | 389,120 |
| the sequencer's runner | 74 | 2,276 B | 6 | 466,944 |

The register rule gives 5 waves at 94 and 6 at 74, as compiled; at 36 it gives
8, and the compiler said 6, so something else bounds the generic kernel (AGPRs
or a limit not printed; not known). At 8 waves the device holds 622,592 lanes.

**The three measures, used throughout:**
- **(i) lanes resident:** launched waves over resident waves, 1,216 SIMDs x w, where w is the kernel's waves a SIMD. Below 1, the device idles. A run at 1 is full.
- **(ii) arithmetic issue:** the fraction of the 4.09 x 10^13 slots the run issues. It is the product of the arithmetic kernel's own fraction (f_k) and the live lanes (lanes not masked, over lanes issued). Work a lane does that a lone particle would not (Saturn and the moons carried in every lane or wave) is live; it is a multiplier on the time, given beside (ii) as "work a particle". f_k is not measured on any AMD GPU. GPU-A's rates on the RTX 5060 Ti leave at most about 40,000 slots an FMA-class operation for the generic path and 4,200 for the specialised one (READ :485, :863), the slots available at the measured rate, not a count of what is spent. At GPU-A's MI300X rates an FMA has 34,000 to 82,000 slots (generic) and 2,700 to 5,100 (specialised) (COMPUTED), so the top of each estimate assumes a kernel near issue-bound. This study can give the lane efficiency only.
- **(iii) memory:** HBM held over 192 GiB, and bytes a second over 5.3 TB/s.

**What bounds an IAS15 lane's occupancy.** A body's state is 52 values a
coordinate (READ, ENSEMBLE.md:34-37: `x, v, a, x0, v0, a0, csx, csv, csa0, at`
and the seven-fold `g, b, e, csb, er, br`), so 156 values a body (COMPUTED):

| format | state a body | in a lane's 2,048 B of registers | bodies a CU in LDS | bodies in HBM |
|---|---|---|---|---|
| binary64 | 1,248 B | fits, at 312 of 512 registers: 1 wave a SIMD | 52 | 1.65 x 10^8 |
| binary128 | 2,496 B | does not fit | 26 | 8.3 x 10^7 |
| binary256 | 4,992 B | does not fit | 13 | 4.1 x 10^7 |

So the state cannot live in registers or LDS at a useful occupancy (a CU holds
1,536 lanes at 6 waves) and streams from HBM through L2 and the Infinity
Cache: 58 values a coordinate a substep (READ, HARDWARE.md:521-522, the values
a predictor run and a corrector run stage). **What bounds occupancy is the
arithmetic's registers and scratch, not the state** (ESTIMATE): an IAS15
kernel inlines libcft's softfloat, so it sits at the generic FMA's 6 waves
or lower. Its own count needs a compile of a kernel that does not exist; the
prototype in section 6 gives it.

## 2. IAS15's cost per particle-step

**HARDWARE.md's measured counts first (READ, :63-72):** per Kepler step, 1,868
library calls at binary64 (255 divide or square root, 2.39 corrector passes),
4,321 at binary128 (612, 6.0 passes), 9,400 at binary256 in the FMA form (276,
18.1 passes). Calls are vectors over the lanes, so they count operations a
coordinate, not by kind; the kinds are counted here from src/ias15_cft.c.

**COUNTED from src/ias15_cft.c (7a7a279), operations by kind:**

| where | FMA form (`--arith fma`) | REBOUND's form | lines |
|---|---|---|---|
| predictor, a coordinate a substep | 8 FMA, 1 MUL, 2 ADD | 18 MUL, 8 DIV, 10 ADD | :1600-1606, :1616-1625 |
| corrector, a coordinate a pass (7 substeps) | 196 ADD, 49 MUL | 196 ADD, 21 MUL, 28 DIV | :1650-1671, add_cs :1571-1587 |
| corrector's error, a system a pass | 1 DIV (and maxima, integer work) | the same | :1797 |
| a step, a coordinate: g from b, end-of-step update, next-step prediction | 89 MUL, 124 ADD | 74 MUL, 124 ADD, 15 DIV | :2800-2808, :2911-2922, :2134-2148 |
| a step, a particle: PRS23's timescale | 68 MUL, 82 ADD, 1 SQRT, 1 DIV | the same | :2391-2431 |
| a step, a system: the step's choice and ratio | 8 MUL, 3 DIV, 1 SQRT (FMA form: 14 MUL more for `fl(dt h_n)`) | the same | :2446-2483, :2975, :2811-2814 |
| gravity, a test particle and one massive partner | 9 ADD, 9 MUL, 1 SQRT, 1 DIV | the same | REBOUND's test-particle loop |
| gravity, an active pair, both sides | 12 ADD, 13 MUL, 1 SQRT, 1 DIV | the same | :1516-1535, :1562 |
| J2 and J4, a body an evaluation | ESTIMATE: 1 DIV, 21 MUL, 6 FMA, 6 ADD | the same | not in cft-rebound |

Gravity runs once at a step's start and seven times a pass (:2795, :2863), so
a step attempt with p passes makes 7p + 1 force evaluations.

**The check that can fail, MEASURED:** the counts give the divides and square
roots a run issues exactly: 99 a pass and 23 an attempt in REBOUND's form, 15
and 8 in the FMA form. Between a 100-step and a 200-step run of the same
setting, two samples each, `divsqrt_calls` moved by 32,099 (binary64), 57,641
(binary128) and 17,300 (binary256, FMA form), **identical** to the count at all
three (`ring_runs.py`). The other kinds are counted by the same reading and not
checked by a run.

**One ring particle, seven massive partners (Saturn and six moons) and J2+J4,
a step attempt** (COMPUTED by `cost_model.py` at the MEASURED passes of
section 3; FMA-equivalents weight each op by libcft's own measured cost against
an FMA of its format, READ, BENCHMARKS.md:266-294: a divide is 14, 17 and 26
FMAs at binary64, 128 and 256, a square root 18, 20 and 28):

| format, epsilon, passes | form | ADD | MUL | FMA | DIV | SQRT | FMA-equivalents |
|---|---|---|---|---|---|---|---|
| binary64, 1e-9, 3.03 | FMA | 3,890 | 2,728 | 641 | 184 | 157 | 11,636 |
| binary64, 1e-9, 3.03 | REBOUND's | 4,398 | 3,495 | 133 | 992 | 157 | 23,529 |
| binary128, 1e-9, 8.01 | FMA | 9,438 | 6,497 | 1,688 | 469 | 401 | 30,042 |
| binary128, 1e-12, 5.66 | FMA | 6,823 | 4,720 | 1,195 | 335 | 286 | 21,557 |
| binary256, 1e-9, 19.98 | FMA | 22,761 | 15,546 | 4,202 | 1,151 | 988 | 98,207 |
| binary256, 1e-16, 11.04 | FMA | 12,805 | 8,783 | 2,323 | 641 | 550 | 54,897 |
| binary256, 1e-16, 11.04 | REBOUND's | 14,659 | 11,737 | 469 | 3,467 | 550 | 130,140 |

A substep-pass costs 496, 516 and 692 FMA-equivalents in the FMA form
(binary64, 128, 256) and 1,029, 1,146 and 1,651 in REBOUND's: **REBOUND's form
costs 2.1 to 2.4 times the FMA form** (COMPUTED). 97 % of the difference at
binary256 is the divides REBOUND writes, 24 a particle a substep in the predictor
(by small integers) and 12 in the corrector (by the node spacings), which the FMA
form replaces by multiplications by exact reciprocals rounded once. The FMA form
differs from REBOUND at round-off (3e-15 relative at binary64, READ
HARDWARE.md:89-92) and is cft-rebound's own gated form.

**Where the work is** (COMPUTED, binary256, FMA form): the force is 79 % of a
substep-pass and the divide and square root are 74 % of the force, one of each
a partner for `1/r^3` (correctly rounded, as REBOUND's bits need). The
BELIEVED premise is that each op's cost in FMAs carries from the CPU to the GPU,
since the same C runs and `cft_div` is ~25-30 FMA-class passes by construction
(READ, BENCHMARKS.md:587-593). So a specialised tier x6.7 to x30 on every op is
that much faster, but on FMA, ADD and MUL alone it is **x1.54 to x1.67**.

## 3. The tolerance, and steps per orbit

**MEASURED here:** one massless particle on a circular orbit about a unit mass
(G = M = r = 1, period 2 pi), `ias15_cft`, REBOUND's form, PRS23, `--max-iter 60`,
200 steps; steps an orbit from the last 100 steps (the step is constant on a
circular orbit; the two halves agree to 1 %):

| epsilon | steps an orbit, any format | passes, binary64 | binary128 | binary256 |
|---|---|---|---|---|
| 1e-9 (REBOUND's default) | 36.2 | 3.03 | 8.01 | 19.98 |
| 1e-12 | 96.9 | | 5.66 | 15.02 |
| 1e-16 | 359.7 | | 4.04 | 11.04 |
| 1e-20 | 1,330 | | | 8.08 |
| 1e-24 | 4,987 | | | 7.08 (one rejected step) |

The FMA form gives the same steps and passes (5.645 at binary128 1e-12, 11.035
at binary256 1e-16). The step is set by epsilon alone, as eps^(-1/7) (x2.68 for
10^3, x3.71 for 10^4, COMPUTED from the table), and the passes by the format.
HORIZON.md measured the same on an e = 1/2 orbit (READ, :71-73, :96): 51, 138 and
513 steps an orbit at 1e-9, 1e-12 and 1e-16, passes 3.4 at binary64 and 8.6,
6.1, 4.2 at binary128; the circular orbit takes 0.70 to 0.71 of those steps.

Force evaluations an orbit, steps x (7p + 1) (COMPUTED): 803 (binary64, 1e-9),
2,066 and 3,936 (binary128, 1e-9 and 1e-12), 5,099 and 28,140 (binary256, 1e-9
and 1e-16). Binary256 at REBOUND's default epsilon costs 6.3 times binary64's
force evaluations, all of it corrector passes.

**What epsilon must be for the wider format to matter.** HORIZON.md (READ):
- **for a regular orbit, epsilon 1e-12 or tighter**, "with the patience for 5 to 12 times the force evaluations" (:221-236); at 1e-9 binary128 buys an order of magnitude in horizon at 1e-6 of an orbit and almost nothing at 0.1 (:98-111);
- **binary256 differs from binary128 only below binary128's floor**, which no measured run reaches in the phase (:76-81); binary128 is at its own floor at 1e-16;
- **for a chaotic problem the format matters at REBOUND's default tolerance**: binary64's solution of the Pythagorean problem differs from binary256's by 1e-12 at t = 6.9 and is unrelated from t = 66; binary128 stays 60 bits closer, and the truncation error is nine decades below the round-off error at the moment binary64 is lost (:139-177).

**For a ring, mine:** a ring particle far from every moon is a regular orbit
over 10 to 1,000 orbits, and binary64's phase there is 2.11e-16 x orbits^1.525
at the 90th percentile (READ, HORIZON.md:50), 8e-12 of an orbit at 1,000
orbits (COMPUTED): **no format and no epsilon matters for it.** The format
matters for **particles that meet a moon**: inside Pan's or Prometheus's
reach an encounter amplifies round-off as the Pythagorean problem's do
(BELIEVED; no encounter was run), so binary128 at epsilon 1e-9 is already the
useful setting, at 2.6 times binary64's
force evaluations. Binary256 is for the certificate: the reference against which
binary128's round-off is measured by difference, on the same steps.

## 4. Saturn, READ

| quantity | value | source |
|---|---|---|
| GM | 37.931 x 10^6 km^3 s^-2 | [NASA Saturn fact sheet](https://nssdc.gsfc.nasa.gov/planetary/factsheet/saturnfact.html) |
| equatorial radius (1 bar) | 60,268 km | the same |
| J2 | 16,298 x 10^-6 (fact sheet, reference radius not stated); Cassini: 16,290.573 +- 0.028 x 10^-6 | the same; Iess et al. 2019, in [Fortney et al., arXiv:2304.09215](https://arxiv.org/abs/2304.09215), Table IV.1 |
| J4 | -935.314 +- 0.037 x 10^-6 (Cassini; the table states no reference radius, BELIEVED 60,330 km) | the same table |

The rings, km from Saturn's centre ([NASA ring fact sheet](https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html)):
D 66,900-74,510; C 74,658-91,975; B 91,975-117,507; A 122,340-136,780;
Encke gap 133,410; Keeler gap 136,487; F 139,826; G 166,000-173,000;
E 180,000-480,000.

The moons ([JPL SSD, physical parameters](https://ssd.jpl.nasa.gov/sats/phys_par/) and [mean elements](https://ssd.jpl.nasa.gov/sats/elem/), Laplace-plane elements, "not intended for ephemeris computation"):

| moon | GM, km^3 s^-2 | a, km | e | period, d | Hill radius (COMPUTED) |
|---|---|---|---|---|---|
| Mimas | 2.50349 +- 0.00014 | 186,000 | 0.020 | 0.942422 | 521 km |
| Pan | 0.00028 +- 0.00014 | 133,600 | 0.000 | 0.575051 | 18 km |
| Prometheus | 0.01071 | 139,400 | 0.002 | 0.615878 | 63 km |
| Pandora | 0.00926 | 141,700 | 0.004 | 0.631369 | 61 km |
| Epimetheus | 0.03514 | 151,400 | 0.020 | 0.697012 | 102 km |
| Janus | 0.12662 | 151,500 | 0.007 | 0.697353 | 157 km |

A ring particle's period (COMPUTED, Kepler's law with the GM above): 5.78 h
at the C ring's inner edge, 11.41 h at the B ring's outer edge, **13.81 h at the
Encke gap**, 14.34 h at the A ring's outer edge, 14.82 h at the F ring. At the
Encke gap J2 (R_eq/a)^2 is 3.3e-3 and J4 (R_eq/a)^4 is -3.9e-5 (COMPUTED), the
sizes of their terms against the central one; a resonance's radius moves by about
that fraction, hundreds of km (BELIEVED).

What the rings show and why (READ): the B ring's outer edge "is maintained by an
m=2 inner LR with the satellite Mimas" ([Hahn, Spitale & Porco 2009, ApJ 699:686](https://arxiv.org/abs/0904.0743));
the A ring's outer edge "is associated with a 7:6 resonance with Janus"; Pan,
about 20 km across, orbits in the Encke Gap; the rings hold particles "as large
as 100 m or so", each of which "imprints a characteristic propeller-like
feature" ([Murray 2007, Physics Today](https://physicstoday.aip.org/quick-study/saturns-dynamical-rings)).

**What "Saturn-like" needs at the least for a run to show something real**
(mine; BELIEVED, standard ring dynamics, not run here):
- **a gap and its moonlet** - Pan and test particles within a few hundred km of it. The edge waves and wakes are kinematic and test particles show them, within an orbit of a particle's passage. **This is the one a test-particle ring shows for certain.**
- **a resonance edge** - Mimas's 2:1 at the B ring's edge, or Janus's 7:6 at the A ring's. Test particles show the forced m = 2 or m = 7 response. The sharp edge itself needs the ring's collisions, which test particles do not have.
- **a density wave** - launched at a Lindblad resonance, it carries itself outward by the ring's own gravity. Test particles show the forcing and not the wave.
- **a propeller** - a ~100 m moonlet in a self-gravitating, colliding ring. Real ring simulations of one are local (a shearing box with a tree and collisions), and cft-rebound refuses shear boundaries and the tree code by name (READ, README.md:47-58).
- **J2 and J4**, without which every resonance sits in the wrong place.

## 5. The candidate workloads

All COMPUTED by `cost_model.py` in the FMA form. Device time is an ESTIMATE:
FMA-equivalents over GPU-A's MI300X rates (READ, ESTIMATEs there: generic
0.5 to 1.2 x 10^9 fp256 FMAs a second, specialised 0.8 to 1.5 x 10^10), scaled to
binary64 and binary128 by the RX 7600's MEASURED format ratios (x2.96, x2.04,
READ GPU-A :439, :465), and by occupancy (i) at 5 and 6 waves. Specialised
rates assume divide and square root specialised too, and at binary64 and 128
are a what-if: round 3 starts at binary256. Below full occupancy the model holds
each wave's pace fixed (latency-bound, BELIEVED), so 10^5 and 3 x 10^5
particles take the same time an orbit; an issue-bound kernel would take
less at 10^5. Close encounters, which shorten steps, are in none of it.

### (a) A test-particle ring: Saturn with J2 and J4, six moons, N massless particles

Three parallel shapes (the moons and Saturn are integrated in every system):
- **a1, one lane a system** (ENSEMBLE.md's ensemble): a lane carries Saturn, six moons and one particle, so each lane does **5.2 to 5.6 times** a lone particle's work (COMPUTED: eight bodies' corrector, 28 pairs). Each lane has its own step and its own passes; inside a wave the passes diverge, and the lanes that converged ride along masked. MEASURED here on eight members spread from r = 1.0 to 1.7: pc_lane_efficiency 0.986 at binary64, 0.93 at binary128 (READ VALIDATION.md:655-657: 0.687 to 0.996 on the gate's families). Steps diverge too: every member takes the same steps per own orbit (36 or 97, MEASURED), so a member at 1.7 needs 2.2 times fewer steps per unit time than one at 1.0 (COMPUTED); lanes sorted by radius keep a wave's members within a narrow annulus.
- **a2, one wave a system:** 57 particles share a step with Saturn and the moons in seven lanes; 57/64 of the lanes carry particles. No divergence inside a wave: one step, one pass count, the reductions (the corrector's maxima, the step's minimum) across 64 lanes in registers.
- **a3, one system:** all N share one step and one exit test. MEASURED here: one system of 8, 16 and 32 particles takes the innermost particle's step (35.9 steps an orbit at r = 1.0, as one particle alone) at 3.03 to 3.09 passes, so IAS15's global error estimate (max|tmp| over max|at|) did not add passes at these N. But every particle takes the shortest timescale's step: over the C ring to the F ring, uniform in radius, 0.617 of the steps are useful (COMPUTED), and one particle near Pan sets every particle's step (BELIEVED; not run). The maxima are device-wide reductions, a kernel boundary a pass.

The three measures and the time for one orbit of every particle (COMPUTED;
generic and specialised kept apart):

| shape | format, epsilon | N | (i) occupancy, 5 / 6 waves | (ii) live lanes; work a particle | (iii) HBM held | (iii) bandwidth, generic / specialised | generic, an orbit | specialised, an orbit |
|---|---|---|---|---|---|---|---|---|
| a3 | binary64, 1e-9 | 10^6 | 1.00 / 1.00 | 1.000; x1 in an annulus (x1.62 from the C ring to the F ring) | 3.6 GB, 1.8 % | 0.18 % / 2.2 % | 2 to 5 min | 9 to 18 s |
| a3 | binary128, 1e-9 | 10^5 / 3 x 10^5 / 10^6 | 0.26, 0.77, 1.00 / 0.21, 0.64, 1.00 | 1.000; x1 | 2.6 / 3.1 / 4.9 GB | 0.06, 0.19, 0.24 % / 0.8, 2.4, 3.1 % | 3 to 8, 3 to 8, 7 to 18 min | 14 to 31 s, 14 to 31 s, 36 to 67 s |
| a2 | binary64, 1e-9 | 10^6 | 1.00 / 1.00 | 1.000; x1.12 | 3.8 GB, 1.8 % | 0.18 % / 2.2 % | 2 to 5 min | 11 to 20 s |
| a2 | binary128, 1e-9 | 10^5 / 3 x 10^5 / 10^6 | 0.29, 0.87, 1.00 / 0.24, 0.72, 1.00 | 1.000; x1.12 | 2.6 / 3.2 / 5.2 GB | 0.07, 0.21, 0.24 % / 0.9, 2.6, 3.1 % | 3 to 8, 3 to 8, 8 to 20 min | 14 to 31 s, 14 to 31 s, 40 to 75 s |
| a2 | binary128, 1e-12 | 10^6 | 1.00 / 1.00 | 1.000; x1.12 | 5.2 GB, 2.5 % | 0.24 % / 3.0 % | 16 to 38 min | 77 s to 2 min |
| a2 | binary256, 1e-9 | 10^6 | 1.00 / 1.00 | 1.000; x1.12 | 8.0 GB, 3.9 % | 0.18 % / 2.3 % | 55 min to 2.2 h | 4 to 8 min |
| a2 | binary256, 1e-16 | 10^6 | 1.00 / 1.00 | 1.000; x1.12 | 8.0 GB, 3.9 % | 0.18 % / 2.2 % | 5.1 to 12.3 h | 25 to 46 min |
| a1 | binary128, 1e-9 | 10^6 | 1.00 / 1.00 | 0.930; x5.38 | 22.3 GB, 10.8 % | 0.24 % / 3.1 % | 43 min to 1.7 h | 3 to 6 min |
| a1 | binary256, 1e-16 | 10^6 | 1.00 / 1.00 | 0.930 (ASSUMED as binary128's); x5.24 | 42.3 GB, 20.5 % | 0.18 % / 2.2 % | 26 h to 2.6 d | 2.1 to 3.9 h |

The full table, every shape at every N and setting, is the script's output.
HBM held includes 2.37 GB of the generic kernel's scratch for 466,944 lanes;
the largest N HBM holds is 1.6 x 10^8, 8.2 x 10^7 and 4.1 x 10^7 particles
(binary64, 128, 256; COMPUTED), far past any N a day of device time integrates.

**What it shows physically:** Pan's wakes on the Encke gap's edges, the F ring's
particles perturbed at each Prometheus passage, the forced responses at the Mimas
2:1 and Janus 7:6 resonances, J2's precession - all kinematic (section 4; BELIEVED,
not run).

**What it shows for cft:** bit for bit across devices (a sampled wave against the
CPU, section 6), reproducibility, and the round-off floor of binary64 and of
binary128 measured by differencing formats on the same steps (HORIZON.md's
"certificate", :232-236) - here on a million trajectories, the encounter-driven
ones among them, where the difference is the measurement.

### (b) A self-gravitating ring: every pair

N(N-1)/2 pairs a force evaluation, 7p + 1 evaluations a step. cft-rebound caps a
system at **1,024 bodies** (READ, ias15_limits.h:19-29, "1024 bodies want 4.4 GB
and 2048 would want 17.7 GB" at binary256): its layout holds 52 state vectors and
~300 broadcast constants, each max(3N, N(N-1)/2) wide (READ, ENSEMBLE.md:143-147),
28 TB at 10^5 bodies in binary128 (COMPUTED). A GPU port computes each pair where
it is used and holds 156 values a body, so memory is not the wall. Time is:

| format, epsilon | N | pairs | generic, an orbit | specialised, an orbit |
|---|---|---|---|---|
| binary128, 1e-12 | 1,024 | 5.2 x 10^5 | 47 to 113 s | 4 to 7 s |
| binary256, 1e-9 | 1,024 | 5.2 x 10^5 | 3 to 7 min | 14 to 26 s |
| binary128, 1e-12 | 10^4 | 5.0 x 10^7 | 75 min to 3.0 h | 6 to 11 min |
| binary128, 1e-12 | 10^5 | 5.0 x 10^9 | 5.2 to 12.4 d | 10 to 19 h |
| binary128, 1e-12 | 10^6 | 5.0 x 10^11 | 1.4 to 3.4 years | 42 to 78 d |

(ESTIMATE, with steps an orbit taken from the single particle: a colliding,
self-gravitating ring takes far smaller steps, so these are lower bounds.)
REBOUND's direct collision search is quadratic too, but once a step against 7p + 1
force evaluations: 0.06 to 0.30 % of a step (COMPUTED). Its cost is elsewhere:
cft-rebound runs it on the binary64 view between steps and refuses it above
binary64 without `accurate = 1` (READ, README.md:67-120). **At N = 1,024 one
system has 5.2 x 10^5 pairs, a lane each fills the device, and it is the
largest self-gravitating ring cft-rebound can check bit for bit.** At the same
format and epsilon it costs 10^3 times the test-particle ring (a2) at 10^5 bodies
and 5 x 10^4 times at 10^6 (COMPUTED from the two tables).

The three measures (COMPUTED): (i) the pair phase fills the device from N = 1,024
(8,184 waves); (iii) HBM holds 156 values a body, 2.5 GB at 10^6 in binary128, and
the bandwidth is the test-particle ring's order; but (ii) the **accumulation** in
REBOUND's partner order is a dependent chain of N - 1 adds for each of the 3N
coordinates: at N = 1,024 that is 48 waves, under 1 % of the resident lanes, and
each lane's chain is about 13 times the pair phase's work a lane at binary256
(1,023 adds against 5.2 x 10^5 pairs of 77 FMA-equivalents over 466,944 lanes). With each
wave's pace fixed (the model's assumption), the accumulation, not the pairs,
sets the time at the cap; reassociating it would change REBOUND's bits. Its
3N lanes fill the device from N = 1.5 to 2 x 10^5.

### (c) Hybrids: M moonlets among N particles, one shared step

COMPUTED at binary128, 1e-12: M = 100 moonlets and 10^6 particles cost 2.5 to 6.0 h
an orbit generic, 12 to 22 min specialised; M = 1,000, 23 h to 2.3 d and 1.8 to
3.4 h. One wave a system cannot carry them (each wave would replicate M bodies),
so the shape is a3, and every moonlet's encounters set every particle's step
(BELIEVED). The particles' force is (M + 7) pairs each: the divides and square
roots again. The measures follow a3's: (i) as a3's at the same N (one lane a
particle), (ii) every lane live with (M + 7) partners each, (iii) a few GB. A
propeller needs the ring's self-gravity besides, which (b) prices.

## 6. What must be built before the MI300X run (sizes are ESTIMATEs)

1. **A divide and a square root callable inside a device kernel.** `cft_div` and `cft_sqrt` are composed in host/src/divsqrt.c as `cft_run` steps whose floating steps run on the backend and whose integer steps (classify, centre, the ulp restore, the pack) run exactly on the host (READ, its head); at G1A's tip it carries no `CFT_HD` (MEASURED: `git show 066dde9f:host/src/divsqrt.c | grep -c CFT_HD` is 0, against 26 in bigint.c and 39 in softfloat.c). Through `hip:N` they would run as host-orchestrated round trips: usable from the host API, not callable in a kernel, and an IAS15 thread needs `1/r^3` at every pair and node. Two routes:
   - **(i) the sequencer's whole-operation routines, divfull and sqrtfull, on the device's own executor** (seq_exec.h, under `CFT_HD` at G1A's tip): raw operands in, the correctly rounded result and its five flags out, the prep and the rounding in integer instructions (READ, programs/divfull-fp256.cfta's head; ROADMAP.md:2945-2953). At binary256 they are 216 and 195 instructions, of which 27 and 34 are FMA-class (fma, mul, sub) and 180 and 146 integer or select (MEASURED, counted in the program text). Already held: the images are byte-identical to `python/cft_golden/divfull.py`'s by the generated gate, and the model is held to `softfloat.div` and `softfloat.sqrt`, bits and flags, by test_divfull.py's 38 tests, 16,720 + 6,300 checker cases and 80,000 random pairs (READ, ROADMAP.md:2947-2953). On the device: seq_check.py through `hip:N` (G1C's gate) and the kernel's own call against host `cft_div` and `cft_sqrt` on host/tests/divsqrt_check.py's corpus. Its cost on a GPU and the runner's registers inside an IAS15 kernel are not measured (the runner alone: 74 to 148 VGPRs at gfx942, 6 to 3 waves, READ part2-rates.txt).
   - **(ii) divsqrt.c's sequence ported per element**, its integer steps on the device under `CFT_HD`: 400 to 700 lines (ESTIMATE), no interpreter, a second implementation of the route. Held to `python/cft_golden/sequences.py`, divsqrt.c's line-for-line specification, to host `cft_div` and `cft_sqrt` on divsqrt_check.py's corpus at every format and attribute, and to route (i) on the same operands.

   **Mine: (i) first.** It is one source - the model's image run by the host's own executor text - already proven against the contract and already in the tree; (ii) is a second implementation that would have to be held to the first. The prototype (item 7) measures (i)'s cost and registers, and (ii) is built only if they bind. Either rides a specialised FMA once round 3 has one (the runner's FMA-class instructions through the fixed path, as GPU-A's part 2 ran ADD, SUB and MUL), **which is what lets round 3 multiply this workload's rate.**
2. **The IAS15 device port, one wave a system (a2):** the state lane-major in HBM (156 values a body); one kernel a substep for predict, force with J2/J4, and correct, each thread a body; Saturn's and the moons' predicted positions shared through LDS or cross-lane moves; the corrector's maxima (`normalabs` then a maximum, as pc_error does) and PRS23's minimum across the wave; masks for the wave's exit, rejection and end of block, as ENSEMBLE.md's masking does. 1,500 to 2,500 lines of HIP and C from ias15_cft.c's step, the FMA form first; REBOUND's form after, for binary64 against REBOUND. A route with no port exists: cft-rebound's `--engine program` pointed at `hip:N`, once the backend runs programs with index tables (round 2). It keeps the per-call structure HARDWARE.md measured on the card (four fifths of a step not arithmetic) and ENSEMBLE.md's layout, which for a2's 17,544 systems of 64 bodies - massless ones computing every pair, 2,016 a system against 420 - is 199 GB at binary128 and 398 GB at binary256 (COMPUTED from ENSEMBLE.md:143-147): a ladder rung at small E, not the MI300X run.
3. **J2 and J4 in libcft's format** (~100 lines). cft-rebound evaluates `additional_forces` at binary64 even in a binary256 run, and "a component the routine writes is binary64 from that node on" (READ, README.md:122-128), so the drop-in cannot be the reference above binary64 and REBOUND has none. **Verified against (mine):** (a) the golden model (`python/cft_golden`) evaluating the same operation sequence at sampled nodes, bit for bit; (b) the format-difference check: the same steps at binary128 and binary256 must differ at binary128's round-off, about 1e-34 relative, and a J2/J4 term at binary64 would make them differ at 1e-16 - the check that fails on exactly the defect the README names; (c) at binary64, REBOUNDx's harmonics op for op, if its formula is the one ported (REBOUNDx is not in cft-rebound's pins; not read).
4. **Verification against cft-rebound's CPU IAS15** (400 to 800 lines of driver). The standalone program has no test particles and no J2; a massless active body gets the same acceleration bits as a test particle, since every extra term is a signed zero added to a non-zero sum (BELIEVED from the code, :1542-1546; not run), so: (a2) a sampled wave is a 64-body system `ias15_cft` runs directly, without J2/J4, at every format; (a3) a sampled particle is replayed with the GPU run's steps (`--dt-file`) and pass counts (`--replay-iters`) in a system of Saturn, the moons and that particle (BELIEVED exact; the replay is MEASURED identical in cft-rebound for runs with no rejected step, READ VALIDATION.md:674-698; the two options together not run). At binary64, REBOUND's form against REBOUND, which is cft-rebound's own gate.
5. **The ladder** (ESTIMATE, a2, 10 orbits, at GPU-A's MEASURED rates, READ :437-439 and :463-465): the RX 7600 at 3 x 10^4 particles, binary64 10 min, binary128 39 min, binary256 4.3 h generic and 14 min specialised; the RTX 5060 Ti at 10^5, binary64 11 min, binary128 52 min, binary256 7.7 h and 75 min. Then the MI300X. Each rung's records bit for bit against the others' and the CPU's.
6. **The rounds:** round 1 (G1A's `CFT_HD`, G1B's backend) is the base; item 1 is in no round's plan, and should come before round 3's exp family, since round 3's FMA, ADD, SUB and MUL alone give this workload x1.5 to x1.7 (section 2); round 4's tuning and the MI300X after.
7. **The smallest prototype for the numbers only a run gives** (its registers, scratch and rate): the a2 kernel for Saturn and one particle-wave at binary128, no moons, no J2, against `ias15_cft` on the same 64 bodies: about 800 lines once item 1 exists; runs of minutes on the RX 7600 and the 5060 Ti, reporting VGPRs, scratch, waves a SIMD, particle-steps a second and, under rocprofv3, VALU busy for f_k.

**Where the port lives.** cft-rebound's README settles one option already (READ,
:163-170): REBOUND is GPL-3.0-or-later, libcft Apache-2.0 under a
permissive-only dependency rule, "so the combined work lives here, under
REBOUND's licence, and no REBOUND source is ever copied into cft-fp256". The options:
- **(a) in cft-rebound**, a third engine beside the loop and the program engines, with its gates (check_ensemble, check_records) and its pin moved to a cft-fp256 with `CFT_HD` and the device divide;
- **(b) in cft-fp256**: ruled out by that rule, since the port derives from REBOUND's IAS15;
- **(c) a new GPL repository** pinning both, with records of its own.

**Mine: (a).** Its reference is cft-rebound's own engine, its licence is the one
the README requires, and cft-fp256 then supplies only the device-compiled library
through the pin. Logan's to decide.

## 7. Recommendation (mine)

- **Configuration:** workload (a), shape a2, FMA form, Saturn with J2 and J4 and six moons, 10^6 particles in 130,000 to 142,000 km, waves sorted by radius.
- **Runs:** binary128 at epsilon 1e-9 for 10 orbits at the Encke gap (5.8 days); binary64 on the same steps per wave (the difference is binary64's round-off on every trajectory); binary256 at 1e-9 on 10^5 of the particles (binary128's round-off). Device time (ESTIMATE): generic 83 min to 3.3 h, 22 to 53 min and 3.2 to 9.2 h, **about 5 to 13 device-hours in all**; specialised 7 to 12 min, 2 to 3 min and 15 to 35 min, under an hour.
- **What it fills:** (i) 17,544 waves for 6,080 to 7,296 resident, every SIMD full for the whole run; (ii) every lane live (one step and one pass count a wave), so the arithmetic kernel's own fraction, unmeasured, with 57 of 64 lanes on particles; (iii) 2.5 % of HBM held and at most 3.1 % of its bandwidth. Memory is not what this workload fills, and no IAS15 shape at these N fills it.
- **Built first:** section 6's items 1 to 4, and the ladder.
- **Fallback, if AMD's time is short:** 3 x 10^5 particles, 3 orbits, binary128 and binary64 at 1e-9: generic 9 to 25 min and 2 to 7 min (specialised 41 to 93 s and 11 to 25 s); binary256 on 10^5 particles for one orbit, 19 to 55 min.

## What was not run

No GPU kernel, no GPU run, no MI300X; no IAS15 kernel's registers, scratch,
occupancy or rate on any device; f_k on any AMD GPU; any run with J2, J4,
moons, collisions or close encounters; the shared step with more than 32
particles; the two-format replay of section 6's item 4; divfull and sqrtfull on
any GPU or inside any kernel. The MI300X's waves a
SIMD and the integer multiply's rate are BELIEVED from CDNA2's statement and
LLVM's scheduling model. That each op's CPU cost in FMAs holds on the GPU is BELIEVED.

## Questions for Logan, each with my recommendation

1. **The workload:** a test-particle ring, one wave a system (a2), as the MI300X's IAS15 run? *Yes: it fills the device at 10^6 and shows Pan's wakes and the moons' resonances; a self-gravitating ring or propellers need a tree and shear boundaries that cft-rebound refuses by name.*
2. **The device divide and square root:** add them to the GPU backend's rounds, before round 3's exp family? *Yes, since they are 58 % of a substep-pass of this workload: the sequencer's divfull and sqrtfull on the device's executor first, a per-element port of divsqrt.c only if the prototype shows their cost or registers bind.*
3. **The form:** the FMA form for the MI300X run, REBOUND's form ported after for the binary64 gate against REBOUND? *Yes: REBOUND's form costs 2.1 to 2.4 times more.*
4. **J2 and J4 in libcft's format,** verified by the golden model and the format-difference check? *Yes.*
5. **The formats:** binary128 at 1e-9 with binary64 on the same steps, binary256 on a tenth? *Yes; binary256 at 1e-16 costs 5 to 12 hours an orbit generic and is not needed for a ring.*
6. **Where the port lives:** cft-rebound, as a third engine? *Yes (section 6).*
