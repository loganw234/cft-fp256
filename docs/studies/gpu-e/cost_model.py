#!/usr/bin/env python3
"""GPU-E's cost model: IAS15 test-particle and self-gravitating rings on an
AMD Instinct MI300X, at binary64, binary128 and binary256 through libcft.

Nothing here has run on a GPU. Every input below is named with its source
and its mark: READ (a page or a file, given), MEASURED (this study's CPU
runs, captured/ring_runs.txt), COMPUTED (arithmetic on the others, done
below), ESTIMATE or BELIEVED. Run: python3 cost_model.py  (standard library).
Paths are cft-fp256's unless they name cft-rebound.
"""
import math

# ======================= INPUTS =======================================
# --- the device, AMD Instinct MI300X (gfx942) ---
CU = 304                 # READ rocm.docs.amd.com/en/latest/reference/gpu-arch-specs.html (304, 38 per XCD)
SIMD_PER_CU = 4          # READ rocmdocs.amd.com/projects/HIP/en/latest/understand/hardware_implementation.html
LANES_PER_SIMD = 16      # READ same page: 16 ALUs a SIMD
WAVE = 64                # READ gpu-arch-specs: wavefront size 64
WAVES_PER_SIMD_MAX = 8   # BELIEVED: 8 waveslots a SIMD on CDNA2 (rocprofiler-compute, pipeline-descriptions); not stated for CDNA3
VGPR_PER_LANE = 512      # READ llvm-project llvm/lib/TargetParser/AMDGPUTargetParser.cpp, getTotalNumVGPRs (GFX90A insts)
VGPR_GRANULE = 8         # READ same file, getVGPRAllocGranule
LDS_BYTES = 64 * 1024    # READ gpu-arch-specs
L2_BYTES = 32 * 2**20    # READ gpu-arch-specs: 4 MiB a XCD
MALL_BYTES = 256 * 2**20 # READ gpu-arch-specs: "L3 Cache (MiB) 256" (Infinity Cache)
HBM_BYTES = 192 * 2**30  # READ gpu-arch-specs: VRAM 192 GiB
HBM_BW = 5.3e12          # READ rocm.docs.amd.com/en/latest/_sources/reference/gpu-arch/mi300.md
FP64_VEC = 81.7e12       # READ mi300.md: vector FP64 81.7 TFLOPS
FP64_VEC_PER_CLK_CU = 128  # READ mi300.md: 128 FLOPS/clock/CU
CLOCK = FP64_VEC / (FP64_VEC_PER_CLK_CU * CU)        # COMPUTED: 2.10 GHz
ISSUE = SIMD_PER_CU * LANES_PER_SIMD * CU * CLOCK    # COMPUTED: 32-bit lane-instructions a second
# 32-bit integer multiply issues like an add on gfx942: READ llvm-project
# llvm/lib/Target/AMDGPU/SISchedule.td, SIDPGFX942FullSpeedModel: WriteIntMul 1, Write32Bit 1.

# --- cft-fp256's GPU-A study (docs/studies/GPU-A-hip.md) ---
GEN_FP256 = (0.5e9, 1.2e9)    # READ :516, an ESTIMATE there: generic fp256 FMAs a second
SPEC_FP256 = (0.8e10, 1.5e10) # READ :511, an ESTIMATE there: specialised fp256 FMAs a second
RX7600 = {"fp64": 229e6, "fp128": 158e6, "fp256": 77.4e6}  # READ :439, :465 (MEASURED there), generic kernel
KERNELS = {  # READ GPU-A-hip.md:532-533 and gpu-a/captured/part2-rates.txt:116-118 (gfx942 builds, not run)
    "generic FMA": (36, 5068, 6), "specialised FMA": (94, 272, 5), "sequencer runner": (74, 2276, 6)}
SLOTS_BOUND = {"generic": 40000, "specialised": 4200}  # READ :485, :863 - at most, lane-slots an FMA-class op

# --- libcft's own software cost, ns an element (docs/BENCHMARKS.md:266-294, READ) ---
NS = {"fp64": dict(add=309.8, mul=206.1, fma=316.3, div=4468.0, sqrt=5638.2),
      "fp128": dict(add=344.9, mul=243.5, fma=394.5, div=6678.4, sqrt=8018.5),
      "fp256": dict(add=488.3, mul=332.5, fma=448.3, div=11563.1, sqrt=12704.3)}
# BELIEVED: the same C runs on the GPU, so each op's cost in FMAs carries over
# (div and sqrt are ~25-30 FMA-class passes by construction, BENCHMARKS.md:587-593).
BYTES = {"fp64": 8, "fp128": 16, "fp256": 32}

# --- IAS15's arithmetic, COUNTED from cft-rebound src/ias15_cft.c (7a7a279) ---
# per coordinate per substep: the predictor (:1600-1606 FMA form, :1616-1625 REBOUND's)
PRED = {"fma": dict(fma=8, mul=1, add=2), "rebound": dict(mul=18, div=8, add=10)}
# per coordinate per corrector pass, all 7 substeps (:1650-1671, add_cs :1571-1587)
CORR = {"fma": dict(add=196, mul=49), "rebound": dict(add=196, mul=21, div=28)}
# per coordinate per step: g from b (:2800-2808), the end-of-step update
# (:2911-2922), predict_next_step (:2134-2148), and fl(dt h_n) per lane (:2811-2814)
STEP_COORD = {"fma": dict(mul=21 + 40 + 28, add=21 + 68 + 35),
              "rebound": dict(mul=21 + 25 + 28, add=21 + 68 + 35, div=15)}
DT_LANE = {"fma": dict(mul=14), "rebound": {}}
STEP_PARTICLE = dict(mul=68, add=82, sqrt=1, div=1)           # PRS23's sums and timescale (:2391-2431)
STEP_SYSTEM = dict(div=3, sqrt=1, mul=8)                     # :2446, :2468, :2483, :2975, q powers :2135-2136
PASS_SYSTEM = dict(div=1)                                    # pc_error's quotient (:1797)
PAIR_TP = dict(add=9, mul=9, sqrt=1, div=1)   # one test particle, one massive partner: REBOUND's test-particle loop
PAIR_ACTIVE = dict(add=12, mul=13, sqrt=1, div=1)            # an active pair, both sides (:1516-1535, :1562)
# J2 and J4 a body an evaluation, COUNTED from cft-rebound's src/ias15_zonal.inc at 291c99c (zonal_geometry
# :232-242, zonal_accel :298-325, zonal_apply :263-277 twice): 3 SUB (costed as ADD), 14 ADD, 34 MUL (13 of
# them the reaction's, made for a test particle too and discarded), 1 SQRT, 10 DIV (two exact: by 2 and 8);
# no FMA, so both forms. (Was an ESTIMATE until 2026-11-12: 1 DIV, 21 MUL, 6 FMA, 6 ADD.)
J2J4 = dict(add=3 + 14, mul=34, sqrt=1, div=10)
J2J4_REACT = dict(add=6)  # COUNTED: a massive body's reaction on the planet, 3 SUB a pass (:285), twice
# (Not modelled: the constants' 8 MUL of width 1 an evaluation, :250-252, a call's and not a body's.)
STATE_VALUES = 52        # READ cft-rebound docs/ENSEMBLE.md:34-37 - per-lane vectors per coordinate
TRAFFIC_VALUES = 12 + 46 # READ cft-rebound docs/HARDWARE.md:521-522 - values staged per coordinate per substep

# --- MEASURED here: one massless ring particle, circular orbit, ias15_cft, CPU ---
# (format, epsilon) -> (steps per orbit, corrector passes per step attempt); captured/ring_runs.txt
RING = {}   # filled below from the capture's numbers
# --- Saturn (READ; the study's section 4 gives the URLs) ---
GM = 37.931e6            # km^3 s^-2, NASA Saturn fact sheet
R_EQ = 60268.0           # km, same
J2, J4 = 16290.573e-6, -935.314e-6   # Iess et al. 2019 via arXiv:2304.09215, Table 4.1
MOONS = {"Mimas": (2.50349, 186000.), "Pan": (0.00028, 133600.), "Prometheus": (0.01071, 139400.),
         "Pandora": (0.00926, 141700.), "Epimetheus": (0.03514, 151400.), "Janus": (0.12662, 151500.)}  # GM km^3/s^2, a km: JPL SSD

# ======================= THE MODEL (COMPUTED) ===========================
FORMATS = ("fp64", "fp128", "fp256")

def weights(fmt):
    """Each op's cost in FMAs of the same format (BELIEVED to carry over from the CPU)."""
    w = {k: v / NS[fmt]["fma"] for k, v in NS[fmt].items()}
    w["neg"] = 0.0
    return w

def cost(ops, fmt):
    w = weights(fmt)
    return sum(w[k] * n for k, n in ops.items())

def add(*dicts, scale=None):
    out = {}
    for i, d in enumerate(dicts):
        s = 1 if scale is None else scale[i]
        for k, n in d.items():
            out[k] = out.get(k, 0) + s * n
    return out

def tp_step_ops(form, p, partners, j2j4=True):
    """One test particle, one step attempt with p corrector passes: ops by kind.
    Force evaluations: 1 at the step's start + 7 a pass (ias15_cft.c:2795, :2863)."""
    force = add(PAIR_TP, scale=[partners])
    if j2j4:
        force = add(force, J2J4)
    per_pass = add(PRED[form], CORR[form], PASS_SYSTEM, scale=[7 * 3, 3, 1])
    per_step = add(STEP_COORD[form], DT_LANE[form], STEP_PARTICLE, STEP_SYSTEM, scale=[3, 1, 1, 1])
    return add(per_pass, force, per_step, force, scale=[p, 7 * p, 1, 1])

def rate(fmt, tier, lo_hi):
    """FMAs a second of format fmt. Generic: GPU-A's fp256 ESTIMATE scaled by the
    RX 7600's MEASURED format ratio (ESTIMATE). Specialised: fp256 only in round 3's
    first kernels; other formats get GPU-A's fp256 ratio as a what-if (ESTIMATE)."""
    base = (GEN_FP256 if tier == "generic" else SPEC_FP256)[lo_hi]
    return base * RX7600[fmt] / RX7600["fp256"]

def resident_lanes(waves_per_simd):
    return CU * SIMD_PER_CU * waves_per_simd * WAVE

def waves_from_vgprs(v):
    return min(WAVES_PER_SIMD_MAX, VGPR_PER_LANE // (math.ceil(v / VGPR_GRANULE) * VGPR_GRANULE))

def fmt_s(x):
    if x < 120: return "%.0f s" % x
    if x < 7200: return "%.0f min" % (x / 60)
    if x < 2 * 86400: return "%.1f h" % (x / 3600)
    if x < 2 * 365 * 86400: return "%.1f d" % (x / 86400)
    return "%.2g yr" % (x / (365.25 * 86400))

# MEASURED (captured/ring_runs.txt): steps per orbit (mean of the two halves)
# and corrector passes per step attempt, one ring particle on a circular orbit.
RING = {("fp64", 1e-9): (36.2, 3.025), ("fp128", 1e-9): (36.2, 8.010), ("fp128", 1e-12): (96.9, 5.660),
        ("fp128", 1e-16): (359.7, 4.035), ("fp256", 1e-9): (36.2, 19.980), ("fp256", 1e-12): (96.9, 15.015),
        ("fp256", 1e-16): (359.7, 11.035), ("fp256", 1e-20): (1330.4, 8.080), ("fp256", 1e-24): (4986.9, 7.075)}
LANE_EFF = {"fp64": 0.986, "fp128": 0.93, "fp256": 0.93}  # MEASURED fp64 at 1e-9, fp128 at 1e-12 (E = 8, r 1.0-1.7); ASSUMED for fp128 at 1e-9 and fp256
K = 6                    # moons: Mimas, Pan, Prometheus, Pandora, Epimetheus, Janus
CASES = [("fp64", 1e-9), ("fp128", 1e-9), ("fp128", 1e-12), ("fp256", 1e-9), ("fp256", 1e-16)]
W_LO, W_HI = 5, 6        # waves a SIMD: GPU-A's gfx942 kernels (READ); an IAS15 kernel's is not known

def system_step_ops(form, p, n_tp, n_massive, j2j4=True):
    """One step attempt of a system: n_massive active bodies (the planet first), n_tp test particles."""
    bodies = n_tp + n_massive
    force = add(PAIR_ACTIVE, PAIR_TP, scale=[n_massive * (n_massive - 1) // 2, n_tp * n_massive])
    if j2j4:
        force = add(force, J2J4, J2J4_REACT, scale=[1, bodies - 1, n_massive - 1])
    per_pass = add(PRED[form], CORR[form], PASS_SYSTEM, scale=[7 * 3 * bodies, 3 * bodies, 1])
    per_step = add(STEP_COORD[form], DT_LANE[form], STEP_PARTICLE, STEP_SYSTEM, scale=[3 * bodies, 1, bodies, 1])
    return add(per_pass, force, per_step, force, scale=[p, 7 * p, 1, 1])

def occupancy(lanes, w):
    """(i): launched waves over resident waves at w a SIMD, at most 1."""
    return min(1.0, math.ceil(lanes / WAVE) / (CU * SIMD_PER_CU * w))

def span(work, f, tier, lanes):
    """Device seconds, best and worst: the rate's ends, scaled by occupancy at 5 and 6 waves."""
    return (work / (rate(f, tier, 1) * occupancy(lanes, W_LO)), work / (rate(f, tier, 0) * occupancy(lanes, W_HI)))

def main():
    print("== 1. the device (COMPUTED from READ): clock %.3f GHz, 32-bit issue %.4g lane-instructions/s" % (CLOCK / 1e9, ISSUE))
    for name, (v, scr, w) in KERNELS.items():
        print("   %-17s %3d VGPRs: %d waves a SIMD by registers (GPU-A's compile says %d), %d lanes resident;"
              " %d B scratch a lane = %.2f GB" % (name, v, waves_from_vgprs(v), w, resident_lanes(w), scr,
                                                  resident_lanes(w) * scr / 1e9))
    print("   at %d waves a SIMD: %d lanes" % (WAVES_PER_SIMD_MAX, resident_lanes(WAVES_PER_SIMD_MAX)))
    for f in FORMATS:
        sb = 3 * STATE_VALUES * BYTES[f]
        print("   %-5s IAS15 state %4d B a body (%d values); a lane's registers hold %d B; LDS holds %2d bodies a CU;"
              " HBM %.3g bodies" % (f, sb, 3 * STATE_VALUES, VGPR_PER_LANE * 4, LDS_BYTES // sb, HBM_BYTES / sb))
    for t, (lo, hi) in (("generic", GEN_FP256), ("specialised", SPEC_FP256)):
        print("   %-11s fp256: %.0f to %.0f issue slots an FMA at GPU-A's rates; GPU-A's measured bound: at most %d"
              % (t, ISSUE / hi, ISSUE / lo, SLOTS_BOUND[t]))
    print("\n== 2. one test particle, %d partners (the planet and %d moons) and J2+J4: ops a step attempt" % (K + 1, K))
    print("   format form    eps     passes | add    mul    fma   div   sqrt | FMA-eq a step | a substep-pass")
    for (f, eps) in CASES + [("fp256", 1e-24)]:
        spo, p = RING[(f, eps)]
        for form in ("fma", "rebound"):
            ops = tp_step_ops(form, p, K + 1)
            sub = (cost(tp_step_ops(form, p + 1, K + 1), f) - cost(ops, f)) / 7
            print("   %-6s %-7s %.0e %6.3f | %-6.0f %-6.0f %-5.0f %-5.0f %-4.0f | %-13.0f | %.0f" % (
                f, form, eps, p, ops.get("add", 0), ops.get("mul", 0), ops.get("fma", 0), ops.get("div", 0),
                ops.get("sqrt", 0), cost(ops, f), sub))
    force = add(PAIR_TP, J2J4, scale=[K + 1, 1])
    sub = (cost(tp_step_ops("fma", 12, K + 1), "fp256") - cost(tp_step_ops("fma", 11, K + 1), "fp256")) / 7
    ds = cost(dict(div=force["div"], sqrt=force["sqrt"]), "fp256")
    print("   fp256 FMA form: the force is %.0f%% of a substep-pass; div and sqrt are %.0f%% of the force, %.0f%% of"
          " the substep-pass; J2+J4 is %.0f%% of the force" % (100 * cost(force, "fp256") / sub, 100 * ds / cost(force, "fp256"),
          100 * ds / sub, 100 * cost(J2J4, "fp256") / cost(force, "fp256")))
    for sp in (SPEC_FP256[0] / GEN_FP256[1], SPEC_FP256[1] / GEN_FP256[0]):
        print("   specialised x%.1f on every op gains x%.1f; on FMA/ADD/MUL only, div and sqrt generic: x%.2f"
              % (sp, sp, sub / ((sub - ds) / sp + ds)))
    print("\n== 5a. test-particle rings, the FMA form: the three measures, and device time for one orbit of every particle")
    a1 = {c: cost(system_step_ops("fma", RING[c][1], 1, K + 1), c[0]) / cost(tp_step_ops("fma", RING[c][1], K + 1), c[0])
          for c in CASES}
    for shape in ("a3: one system, shared step", "a2: one wave a system (57 particles + planet + 6 moons)",
                  "a1: one lane a system (planet + 6 moons + 1 particle)"):
        print("  -- %s" % shape)
        print("   format eps    N     | (i) occ. 5/6 w | (ii) live lanes, work x | (iii) HBM held | HBM bw gen/spec | generic       | specialised")
        for (f, eps) in CASES:
            spo, p = RING[(f, eps)]
            step = cost(tp_step_ops("fma", p, K + 1), f)
            sb = 3 * STATE_VALUES * BYTES[f]
            for N in (1e5, 3e5, 1e6):
                # eff: live lanes over issued (masking); xw: work a particle over a lone
                # test particle's (the planet and moons carried in every wave or lane)
                if shape.startswith("a3"):
                    lanes, eff, xw, bodies = N, 1.0, 1.0, N + K + 1
                elif shape.startswith("a2"):
                    lanes = math.ceil(N / (WAVE - K - 1)) * WAVE
                    eff, xw, bodies = 1.0, lanes / N, lanes
                else:
                    lanes, eff, xw, bodies = N, LANE_EFF[f], a1[(f, eps)], N * (K + 2)
                work = N * spo * step * xw / eff
                held = bodies * sb + resident_lanes(W_HI) * KERNELS["generic FMA"][1]
                bw = [rate(f, t, 1) * occupancy(lanes, W_LO) / (step / (7 * p + 1)) * 3 * TRAFFIC_VALUES * BYTES[f] / HBM_BW
                      for t in ("generic", "specialised")]
                g, s = span(work, f, "generic", lanes), span(work, f, "specialised", lanes)
                print("   %-6s %.0e %.0e | %.2f / %.2f    | %.3f, x%.3f          | %5.1f GB %4.1f%% | %5.2f%% / %5.1f%% | %-6s..%6s | %s..%s"
                      % (f, eps, N, occupancy(lanes, W_LO), occupancy(lanes, W_HI), eff, xw, held / 1e9, 100 * held / HBM_BYTES,
                         100 * bw[0], 100 * bw[1], fmt_s(g[0]), fmt_s(g[1]), fmt_s(s[0]), fmt_s(s[1])))
    print("   a1's work a lane over a lone test particle's: " + ", ".join("%s %.0e x%.2f" % (c[0], c[1], r) for c, r in a1.items()))
    print("   largest N that HBM holds (state, plus the generic scratch of 6 waves): " + ", ".join(
        "%s %.3g" % (f, (HBM_BYTES - resident_lanes(W_HI) * KERNELS["generic FMA"][1]) / (3 * STATE_VALUES * BYTES[f]))
        for f in FORMATS))
    rmin, rmax = 74658.0, 139826.0       # READ NASA ring fact sheet: the C ring's inner edge, the F ring
    xs = [rmin + (rmax - rmin) * (i + 0.5) / 1000 for i in range(1000)]
    print("   a3 over the C ring to the F ring, uniform in radius: useful steps / shared steps = %.3f"
          % (sum((rmin / x) ** 1.5 for x in xs) / len(xs)))
    print("\n== 5b. a self-gravitating ring, one system, every pair, the FMA form")
    for (f, eps) in (("fp128", 1e-12), ("fp256", 1e-9)):
        spo, p = RING[(f, eps)]
        for n in (1024, 10000, 100000, 300000, 1000000):
            step = cost(system_step_ops("fma", p, 0, n, j2j4=False), f)
            pairs = n * (n - 1) // 2
            layout = (STATE_VALUES + 300) * max(3 * n, pairs) * BYTES[f]       # READ ENSEMBLE.md:143-147
            coll = pairs * cost(dict(add=6, mul=4), "fp64") * NS["fp64"]["fma"] / NS[f]["fma"]
            g, s = span(spo * step, f, "generic", pairs), span(spo * step, f, "specialised", pairs)
            print("   %-6s %.0e N=%-7d %.3g pairs: %.3g FMA-eq a step; an orbit: generic %s..%s, specialised %s..%s;"
                  " the CPU layout %.2g B; collision search %.2f%% of a step"
                  % (f, eps, n, pairs, step, fmt_s(g[0]), fmt_s(g[1]), fmt_s(s[0]), fmt_s(s[1]), layout, 100 * coll / step))
    print("\n== 5c. hybrids: M moonlets + the planet + 6 moons + N test particles, one shared step (fp128 eps 1e-12, FMA form)")
    spo, p = RING[("fp128", 1e-12)]
    for M in (100, 1000):
        for N in (1e5, 1e6):
            step = cost(system_step_ops("fma", p, int(N), M + K + 1), "fp128")
            g, s = span(spo * step, "fp128", "generic", N), span(spo * step, "fp128", "specialised", N)
            print("   M=%-5d N=%.0e: %.3g FMA-eq a step; an orbit: generic %s..%s, specialised %s..%s"
                  % (M, N, step, fmt_s(g[0]), fmt_s(g[1]), fmt_s(s[0]), fmt_s(s[1])))
    print("\n== 4. Saturn (COMPUTED from READ)")
    for name, a in (("C ring inner edge", 74658.), ("B ring outer edge", 117507.), ("Encke gap", 133410.),
                    ("A ring outer edge", 136780.), ("F ring", 139826.)):
        print("   %-18s a = %6.0f km: period %.2f h" % (name, a, 2 * math.pi * math.sqrt(a ** 3 / GM) / 3600))
    for m, (gm, a) in MOONS.items():
        print("   %-10s GM/GM_Saturn %.3g, a = %6.0f km, period %.2f h, Hill radius %.1f km"
              % (m, gm / GM, a, 2 * math.pi * math.sqrt(a ** 3 / GM) / 3600, a * (gm / (3 * GM)) ** (1 / 3)))
    print("   J2 (R_eq/a)^2 at the Encke gap: %.2e; J4 (R_eq/a)^4: %.2e" % (J2 * (R_EQ / 133410.) ** 2, J4 * (R_EQ / 133410.) ** 4))
    print("\n== 7. a2 runs, FMA form, in orbits at the Encke gap (%.2f h each)" % (2 * math.pi * math.sqrt(133410. ** 3 / GM) / 3600))
    for (N, orbits, f, eps) in ((1e6, 10, "fp128", 1e-9), (1e6, 10, "fp64", 1e-9), (1e5, 10, "fp256", 1e-9),
                                (1e6, 10, "fp128", 1e-12), (1e6, 10, "fp256", 1e-9), (1e6, 10, "fp256", 1e-16),
                                (3e5, 3, "fp128", 1e-9), (3e5, 3, "fp64", 1e-9), (1e5, 1, "fp256", 1e-9)):
        spo, p = RING[(f, eps)]
        lanes = math.ceil(N / (WAVE - K - 1)) * WAVE
        work = orbits * lanes * spo * cost(tp_step_ops("fma", p, K + 1), f)
        g, s = span(work, f, "generic", lanes), span(work, f, "specialised", lanes)
        print("   N=%.0e %2d orbits %-6s eps %.0e: %.3g FMA-eq; generic %s .. %s; specialised %s .. %s"
              % (N, orbits, f, eps, work, fmt_s(g[0]), fmt_s(g[1]), fmt_s(s[0]), fmt_s(s[1])))
    print("\n== 6. the ladder: a2, FMA form, 10 orbits, on GPU-A's MEASURED rates (READ :437-439, :463-465),"
          " the device full (ESTIMATE)")
    meas = {"RTX 5060 Ti": {"fp64": 720e6, "fp128": 390e6, "fp256": 143.3e6, "spec fp256": 887e6},
            "RX 7600": {"fp64": 229e6, "fp128": 158e6, "fp256": 77.4e6, "spec fp256": 1383e6}}
    for dev, N in (("RX 7600", 3e4), ("RTX 5060 Ti", 1e5)):
        for (f, eps) in (("fp64", 1e-9), ("fp128", 1e-9), ("fp256", 1e-9)):
            spo, p = RING[(f, eps)]
            work = 10 * math.ceil(N / (WAVE - K - 1)) * WAVE * spo * cost(tp_step_ops("fma", p, K + 1), f)
            extra = ("; specialised %s" % fmt_s(work / meas[dev]["spec fp256"])) if f == "fp256" else ""
            print("   %-11s N=%.0e %-6s eps %.0e: generic %s%s" % (dev, N, f, eps, fmt_s(work / meas[dev][f]), extra))

if __name__ == "__main__":
    main()
