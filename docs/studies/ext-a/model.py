# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""model.py - an instrument of docs/studies/EXT-A-wide-ladder.md.

Every MODELLED table in that study is printed by this file, so a number
in the study can be diffed against a re-run:

    python docs/studies/ext-a/model.py > docs/studies/ext-a/model.out.txt

It imports nothing from the repository. Its inputs are of two kinds and
each is labelled where it is used:

  READ   figures quoted from documents in this tree (docs/LAYOUTS.md,
         docs/ARCHITECTURE.md, docs/SCALING.md, docs/ROADMAP.md,
         README.md), restated here with the place they come from;
  RUN    the MPFR timings in mpfr_scale.out.txt beside this file, which
         mpfr_scale.c wrote and which this file PARSES rather than
         restates.

Everything else is arithmetic on those, and the arithmetic is the model:
it is an extrapolation from four measured formats to formats nobody has
built, and it says so at every table.
"""
import math
import pathlib
import re
import sys

# LF on every platform, like the vector sets: a captured run should diff
# clean against a re-run wherever either was made.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(newline="\n")

HERE = pathlib.Path(__file__).resolve().parent

# ---- READ: the tree's own figures ------------------------------------
MCH = 24                      # rtl/cft_mulgeom.svh: CFT_MUL_MCH
F_SHIP = 135e6                # the shipping kernel clock
BEATS_PER_S = 107e6           # one tile, resident, README.md / docs/SCALING.md
U50_LUT = 870_720             # docs/LAYOUTS.md, "device LUTs"
U50_DSP = 5_952               # docs/SCALING.md
SHELL_1CU = 123_897           # docs/LAYOUTS.md, "shell, one CU"
SHELL_NEXT = 12_626           # docs/LAYOUTS.md, "each further CU"
ROUTE_LIMIT = 0.82            # the routed quad sits at 80.6%; SCALING.md calls 85% the practical limit
HBM_TILES = 8                 # 32 pseudo-channels, four masters a tile (docs/SCALING.md)
# docs/LAYOUTS.md, per LANE, all-in: pipe + opmux + simpleops + seedop
LANE_ALL_IN = {24: 2472 + 34 + 360 + 458, 53: 5014 + 66 + 758 + 488,
               113: 11649 + 131 + 1401 + 565, 237: 31258 + 262 + 3139 + 674}
# docs/ARCHITECTURE.md, the MUL_PASSES table (whole tile, OOC synthesis)
TILE_LUT_MP1, TILE_LUT_MP10 = 123_214, 115_310
TILE_DSP_ROUTED = 262
# docs/ARCHITECTURE.md, "Timing": ~232 MHz at fp32 and ~148 MHz at fp256, out of context
OOC_MHZ = {24: 232.0, 237: 148.0}
SHELL_NS = 0.9                # docs/LAYOUTS.md: "the ~0.9 ns the shell has cost in practice"


def ieee(k):
    """754-2019 table 3.5 / clause 3.6: (exp_w, p) of binary{k}."""
    if k == 32:
        return 8, 24
    if k == 64:
        return 11, 53
    w = round(4 * math.log2(k)) - 13
    return w, k - w


def chunks(p):
    return -(-p // MCH)


def geometry(p, budget):
    """rtl/cft_mulgeom.svh: (columns a lane builds, passes it takes)."""
    nmc = chunks(p)
    cols = -(-nmc // max(1, budget))
    return cols, -(-nmc // cols)


def dsp_per_column(p):
    # A p x 24 column on DSP48E2s: the 24-bit chunk on the 27-bit port,
    # the significand cut into 17-bit pieces on the 18-bit one.
    return -(-p // 17)


def load_mpfr():
    rows = {}
    path = HERE / "mpfr_scale.out.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)((?:\s+[\d.]+){8})\s*$", line)
        if m:
            v = [float(x) for x in m.group(4).split()]
            rows[int(m.group(1))] = dict(mul=v[0], mul754=v[1], fma=v[2], fma754=v[3],
                                         div=v[4], div754=v[5], sqrt=v[6], sqrt754=v[7])
    return rows


MPFR = load_mpfr()
RUNGS = (256, 512, 1024, 2048, 4096, 8192, 16384)


def section(title):
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


# ======================================================================
section("1. Format geometry, and the widths the pipe hard-codes or guards")
print(f"{'k':>6} {'exp_w':>5} {'p':>6} {'emax':>16}   {'NW=3man_w+9':>11} {'lsh bits':>8} "
      f"{'granules':>8} {'half-add':>8} {'tree add':>8} {'chunks':>6} {'tree lv':>7}")
for k in (32, 64, 128) + RUNGS:
    w, p = ieee(k)
    mw = p - 1
    nw = 3 * mw + 9
    aw = nw + 1
    print(f"{k:>6} {w:>5} {p:>6} {(1 << (w - 1)) - 1:>16,}   {nw:>11,} {max(1, (nw - 1).bit_length()):>8} "
          f"{-(-nw // 64):>8} {aw // 2:>8,} {2 * p + 2 * MCH:>8,} {chunks(p):>6} "
          f"{max(0, (chunks(p) - 1).bit_length()):>7}")
print("guards today: cft_lzcone NW <= 1024 and lsh[9:0]; nrm_csh/aln_csh [3:0] = 16 granules;")
print("              the pipe's own tree holds 16 chunks; the exponent algebra is `int`.")
widest = max(mw for mw in range(24, 400) if 3 * mw + 9 <= 1024)
print(f"-> the LZC guard admits man_w <= {widest} (the pipe's comment says 383, from the 16-chunk tree alone)")
for k in range(256, 513, 32):
    w, p = ieee(k)
    ok = 3 * (p - 1) + 9 <= 1024 and chunks(p) <= 16
    print(f"   binary{k}: man_w={p - 1:<4} NW={3 * (p - 1) + 9:<5} chunks={chunks(p):<3} "
          f"{'elaborates' if ok else 'REFUSED'}")

# ======================================================================
section("2. Exponent arithmetic: where 32 and 64 bits run out")
print("libcft's rule (host/include/cft_config.h): INT_MAX >= 2 * |ea + eb|, ea in [emin-(p-1), emax-(p-1)]")
for k in RUNGS + (65536, 262144, 524288):
    w, p = ieee(k)
    emin = 2 - (1 << (w - 1))
    ep = 2 * (emin - (p - 1))
    print(f"  binary{k:<7} exp_w={w:<3} ea+eb reaches {ep:>28,}   "
          f"int32: {'ok' if 2 * abs(ep) <= 2**31 - 1 else ('RAW OVERFLOW' if abs(ep) > 2**31 else 'margin gone')}"
          f"   int64: {'ok' if 2 * abs(ep) <= 2**63 - 1 else 'gone'}")
w, p = ieee(2048)
print(f"  binary2048 passes INT32_MIN by {abs(2 * (2 - (1 << (w - 1)) - (p - 1))) - 2**31:,}")

# ======================================================================
section("3. What scales with 2^emax rather than with p")
print(f"{'k':>6} {'exp_w':>5} {'2/pi table':>12} {'decimal digits of it':>21} {'align span, bits':>18} "
      f"{'min subnormal, digits':>22}")
for k in RUNGS + (32768, 65536):
    w, p = ieee(k)
    bias = (1 << (w - 1)) - 1
    bits = (bias - (p - 1)) + 8192 + 238        # host/src/mp_2opi.h's own sizing rule
    size = bits / 8
    unit, div = next(u for u in (("TiB", 2**40), ("GiB", 2**30), ("MiB", 2**20), ("KiB", 2**10)) if size >= u[1])
    print(f"{k:>6} {w:>5} {size / div:>8.1f} {unit} {bits / math.log2(10):>21.3e} {2 * bias + (p - 1):>18,} "
          f"{(bias + p - 1) * math.log10(5):>22.3e}")
print("largest computations of pi to date are of order 3e14 decimal digits")

# ======================================================================
section("4. The area model, and its residuals against the four measured lanes")
# Columns: the MUL_PASSES=10 tile dropped 9 fp256 + 2x4 fp128 + 4x2 fp64 columns
# and gained an accumulator per multi-pass lane (about p + 60 LUT each).
col_bits = 9 * 237 + 2 * 4 * 113 + 4 * 2 * 53
acc = (237 + 60) + 2 * (113 + 60) + 4 * (53 + 60)
LUT_PER_COLBIT = (TILE_LUT_MP1 - TILE_LUT_MP10 + acc) / col_bits
print(f"READ  MUL_PASSES 1 -> 10 saved {TILE_LUT_MP1 - TILE_LUT_MP10:,} LUT for {col_bits:,} column-bits removed, "
      f"+~{acc:,} of accumulators")
print(f"      -> {LUT_PER_COLBIT:.2f} LUT per column-bit (a column is p bits)")
SHIFT = lambda p: 3 * math.log2(3 * p)          # two 3p-wide log shifters, a 4:1 mux per LUT6
BASE = (LANE_ALL_IN[237] - LUT_PER_COLBIT * 237 * chunks(237)) / 237 - SHIFT(237)
print(f"      calibrated on the fp256 lane ({LANE_ALL_IN[237]:,} all-in): base = {BASE:.1f} LUT per significand bit")


def lane_lut(p, cols, restaged):
    # restaged: carry-select adders and incrementer, deeper shifter staging - a GUESS of +21 LUT/bit
    return p * (BASE + SHIFT(p) + (21 if restaged else 0)) + LUT_PER_COLBIT * p * cols


print("      lane(p, C) = p * (base + 3 log2(3p)) + %.2f p C      residuals:" % LUT_PER_COLBIT)
for p, meas in LANE_ALL_IN.items():
    got = lane_lut(p, chunks(p), False)
    print(f"        p={p:>4} measured {meas:>7,}  model {got:>9,.0f}  {100 * (got - meas) / meas:+6.1f}%")
got = sum(n * lane_lut(p, chunks(p), False) for n, p in ((8, 24), (4, 53), (2, 113), (1, 237)))
print(f"      DSP check: shipping tile, model {sum(n * chunks(p) * dsp_per_column(p) for n, p in ((8, 24), (4, 53), (2, 113), (1, 237)))}"
      f" against {TILE_DSP_ROUTED} routed")

INFRA = 20_000          # engine + sequencer + CSR + multi-beat assembly: a flat GUESS (15,300 today)


def tiles_that_fit(tile_lut, tile_dsp):
    n = 0
    while n < HBM_TILES:
        need = (n + 1) * tile_lut + SHELL_1CU + n * SHELL_NEXT
        if need > ROUTE_LIMIT * U50_LUT or (n + 1) * tile_dsp > 0.8 * U50_DSP:
            break
        n += 1
    return n


# ======================================================================
section("5. If only the widths move: the 16-stage map kept, the clock allowed to fall")
t24, t237 = 1e3 / OOC_MHZ[24], 1e3 / OOC_MHZ[237]
BETA = (t237 - t24) / (237 - 24)
ALPHA = t24 - BETA * 24
print(f"clock: linear in p through the two published OOC points: {ALPHA:.2f} ns + {BETA * 1e3:.2f} ps/bit, "
      f"+{SHELL_NS} ns in the shell")
print("       (optimistic from binary1024 up: the critical path is already two-thirds routing)")
print(f"{'k':>6} {'passes':>6} {'DSP':>7} {'lane LUT':>10} {'of U50 w/ shell':>15} {'MHz':>5} {'ns/elem':>9} "
      f"{'x MPFR mul':>10} {'x MPFR fma':>10}")
for k in (512, 1024, 2048, 4096):
    w, p = ieee(k)
    budget = 1
    while geometry(p, budget)[0] * dsp_per_column(p) > 0.45 * U50_DSP:
        budget += 1
    cols, passes = geometry(p, budget)
    lut = lane_lut(p, cols, False)
    f = 1e3 / (ALPHA + BETA * p + SHELL_NS)
    rate = min(f / passes, (BEATS_PER_S / F_SHIP) * f / (k / 256))       # M elem/s
    ns = 1e3 / rate
    print(f"{k:>6} {passes:>6} {cols * dsp_per_column(p):>7,} {lut:>10,.0f} "
          f"{(lut + INFRA + SHELL_1CU) / U50_LUT:>15.0%} {f:>5.0f} {ns:>9.1f} "
          f"{MPFR[k]['mul'] / ns:>10.1f} {MPFR[k]['fma'] / ns:>10.1f}")
print(f"for scale, today: one fp256 lane at {BEATS_PER_S / 1e6:.0f} M/s = {1e9 / BEATS_PER_S:.2f} ns/elem -> "
      f"{MPFR[256]['mul'] / (1e9 / BEATS_PER_S):.1f}x MPFR mul, {MPFR[256]['fma'] / (1e9 / BEATS_PER_S):.1f}x fma "
      f"(this desktop's MPFR; README.md's 5.5x is another machine's)")

# ======================================================================
section("6. With the clock held at 135 MHz: wide-only tiles on the U50")
print("beat-limited means an element every (k/256) * %.3f cycles; the multiplier keeps up with" % (F_SHIP / BEATS_PER_S))
print("C = ceil(chunks / floor(that period)) columns - which comes out CONSTANT, because both grow with k")
print(f"{'k':>6} {'cols':>4} {'passes':>6} {'DSP/tile':>8} {'tile LUT':>10} {'tiles':>5} {'of U50':>7} "
      f"{'card Mfma/s':>11} {'MPFR cores fma/mul':>19} {'vs mpfr+754 fma':>16}")
for k in RUNGS:
    w, p = ieee(k)
    period = (k / 256) * F_SHIP / BEATS_PER_S
    cols = -(-chunks(p) // max(1, math.floor(period)))
    passes = -(-chunks(p) // cols)
    dsp = cols * dsp_per_column(p)
    tile = lane_lut(p, cols, True) + INFRA
    n = tiles_that_fit(tile, dsp)
    used = ((max(n, 1)) * tile + SHELL_1CU + max(0, n - 1) * SHELL_NEXT) / U50_LUT
    rate = n * min(BEATS_PER_S / (k / 256), F_SHIP / passes) / 1e6
    if k in MPFR and n:
        cores = (f"{rate / (1e3 / MPFR[k]['fma']):8.1f} / {rate / (1e3 / MPFR[k]['mul']):<5.1f}",
                 f"{rate / (1e3 / MPFR[k]['fma754']):8.1f}")
    else:
        cores = ("        -", "       -")
    print(f"{k:>6} {cols:>4} {passes:>6} {dsp:>8,} {tile:>10,.0f} {n:>5} {used:>7.0%} {rate:>11.1f} "
          f"{cores[0]:>19} {cores[1]:>16}")
today = 4 * BEATS_PER_S / 1e6
print(f"today: 4 full-ladder tiles, {today:.0f} M fma/s = {today / (1e3 / MPFR[256]['fma']):.1f} MPFR cores (fma), "
      f"{today / (1e3 / MPFR[256]['mul']):.1f} (mul), {today / (1e3 / MPFR[256]['fma754']):.1f} against mpfr+754 (fma)")
print("sensitivity: the restaging overhead (+21 LUT/bit) and the flat infra (20k) are guesses.")
for extra, infra in ((10, 15_000), (21, 20_000), (30, 40_000)):
    fits = []
    for k in (512, 1024, 2048, 4096):
        w, p = ieee(k)
        period = (k / 256) * F_SHIP / BEATS_PER_S
        cols = -(-chunks(p) // max(1, math.floor(period)))
        tile = p * (BASE + SHIFT(p) + extra) + LUT_PER_COLBIT * p * cols + infra
        fits.append(f"binary{k}: {tiles_that_fit(tile, cols * dsp_per_column(p))} ({(tile + SHELL_1CU) / U50_LUT:.0%} for one)")
    print(f"   +{extra:>2} LUT/bit, infra {infra:>6,}: " + "; ".join(fits))

# ======================================================================
section("7. What the multiplier is worth: effective bit-products per second")
for k in (256, 512, 1024, 2048, 4096, 8192):
    w, p = ieee(k)
    print(f"  MPFR, one core, binary{k:<5} mul: {p * p / (MPFR[k]['mul'] * 1e-9):.2e} bp/s"
          f"   (step from the rung below: x{MPFR[k]['mul'] / MPFR[k // 2]['mul']:.2f} in time)")
print(f"  one shipping fp256 lane ({BEATS_PER_S / 1e6:.0f} M/s x 237^2):            {BEATS_PER_S * 237 * 237:.2e} bp/s")
u50 = U50_DSP * MCH * 17 * F_SHIP
print(f"  the whole U50, every DSP on a 24x17 product at 135 MHz: {u50:.2e} bp/s "
      f"= {u50 / (ieee(4096)[1] ** 2 / (MPFR[4096]['mul'] * 1e-9)):.0f} MPFR cores at binary4096")

section("8. ASIC, from docs/ROADMAP.md's own napkin figures (5-8 gates per bit-product)")
for name, gates_mm2, clk in (("130 nm open PDK: ~1M gates in 15-25 mm2, 50-150 MHz", (40e3, 67e3), (50e6, 150e6)),
                             ("28 nm: ~15x the density, ~1 GHz", (600e3, 1000e3), (0.8e9, 1.0e9))):
    print(f"  {name}: {gates_mm2[0] / 8 * clk[0]:.1e} .. {gates_mm2[1] / 5 * clk[1]:.1e} bp/s per mm2 of multiplier")
core = ieee(4096)[1] ** 2 / (MPFR[4096]['mul'] * 1e-9)
print(f"  for scale: one desktop core under MPFR = {core:.1e} bp/s; at ~7.5 mm2 a core, ~{core / 7.5:.1e} bp/s/mm2")
w, p = ieee(4096)
print(f"  binary4096, a 16-stage pipe held on `en`: ~{16 * 4 * p:,} flops (~{16 * 4 * p * 6 / 1e6:.1f}M gates) beside one "
      f"p x 24 column (~{p * MCH * 6 / 1e3:.0f}k gates)")
print(f"  a 3p+6 = {3 * p + 6:,}-bit add spread over {chunks(p)} passes is a {-(-(3 * p + 6) // chunks(p))}-bit adder")

section("9. Bytes moved per bit-product, streaming elementwise (three operands in, one out)")
for k in (256, 1024, 4096, 16384):
    w, p = ieee(k)
    bpb = (4 * k / 8) / (p * p)
    print(f"  binary{k:<6} {bpb:.2e} B/bp -> 1e14 bp/s (about 1 mm2 of 28 nm columns) wants {1e14 * bpb / 1e9:7.1f} GB/s")

section("10. Newton steps from the 2^-8.5 seed, and the divide/sqrt program lengths")
for k in RUNGS:
    w, p = ieee(k)
    n = math.ceil(math.log2(p / 8.5))
    print(f"  binary{k:<6} p={p:<6} steps={n:<3} div program {39 + 2 * n} words, sqrt program {45 + 3 * n} words "
          f"(host/src/divsqrt.c holds 80); sqrt image {32 + 9 * (k // 8) + (45 + 3 * n) * 8:,} bytes "
          f"(SQ_IMAGE_MAX is {32 + 9 * 32 + 80 * 8})")
