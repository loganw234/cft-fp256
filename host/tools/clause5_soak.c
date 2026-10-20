/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Soak the clause-5 completion set against the host CPU's own IEEE
 * hardware, the way divsqrt_soak.c soaks division and square root.
 *
 * The golden model defines every bit these entry points return, but
 * the model and the library share an author. The second opinion here
 * is silicon and a libm written by strangers: SSE conversions and
 * casts are correctly rounded per 754 in the prevailing rounding mode
 * with hardware flags, and glibc's trunc/floor/ceil/round/roundeven,
 * nextafter, logb, scalbn, remainder and llrint families restate the
 * same clause-5 operations from an independent lineage. Agreement at
 * exhaustive-fp32 scale is assurance the model matrix cannot provide.
 *
 * Oracle honesty notes, each load-bearing:
 *
 *   * NaN payloads compare as a CLASS, exactly as in divsqrt_soak:
 *     the contract canonicalises, the hardware and libm propagate or
 *     quieten payloads, both are 754-legal, and the difference is
 *     pinned by the model tests.
 *   * Two flag disciplines, chosen per operation. Where the C
 *     environment RAISES the contract flags (scaleb via scalbn's
 *     final multiply, fp64->fp32 narrowing via the cast, integer->
 *     float via cvtsi), the OR of fetestexcept over a batch is
 *     compared against the library's OR - after a directed probe
 *     proves the environment reliable; a probe failure degrades that
 *     comparison honestly and says so in the log. Where the C
 *     operation is documented NOT to signal like ours (the named
 *     roundToIntegral functions never signal inexact; nextafter
 *     signals underflow the contract's nextUp never does), expected
 *     flags are DERIVED from operand classes and the oracle's own
 *     values - sNaN in, invalid out; oracle value differs from the
 *     operand, inexact out of the Exact variant - so libm's flag
 *     quirks are never mistaken for library bugs.
 *   * roundTiesToAway costs nothing here, unlike in divsqrt: C's
 *     round() and llround() ARE ties-to-away by definition, so RMM
 *     gets a native oracle for roundToIntegral and convertToInteger.
 *     scaleb and convert under RMM stay with the model and MPFR.
 *   * convertToInteger compares IN-RANGE lanes only. Out-of-range C
 *     conversion is undefined behaviour, so lanes whose rounded value
 *     leaves the target's range are skipped and counted; the invalid
 *     table is pinned by the model tests. The filter is derived, not
 *     guessed: llrint is total for finite |x| < 2^63 (values >= 2^53
 *     are already integral, so rounding never pushes a magnitude
 *     across the 2^63 line), and the u64 top half [2^63, 2^64) is
 *     integral by the same argument and cast exactly.
 *   * Build with -fno-math-errno and -frounding-math, like the
 *     divsqrt soak: the first keeps libm calls bare instructions
 *     where they can be, the second keeps casts and folds honest
 *     across fesetround. 64-bit only; x87 double rounding on a
 *     32-bit build would poison every fp32 oracle.
 *
 * Usage (one process per job; hw/run-c5-soak.sh fans these out):
 *
 *   clause5-soak rint32 <lo> <hi> <rne|rtz|rdn|rup|rmm>
 *       exhaustive over encodings [lo, hi); checks exact=0 AND exact=1
 *   clause5-soak nextup32|nextdown32|logb32|class32 <lo> <hi>
 *       exhaustive over encodings [lo, hi)
 *   clause5-soak rint64 <count> <seed> <rne|rtz|rdn|rup|rmm>
 *   clause5-soak scaleb32|scaleb64 <count> <seed> <rne|rtz|rdn|rup>
 *       random operands x the directed nexp list
 *   clause5-soak conv64to32 <count> <seed> <rne|rtz|rdn|rup>
 *   clause5-soak conv32to64 <count> <seed>
 *   clause5-soak cvtto32|cvtto64 <count> <seed> <rne|rtz|rdn|rup|rmm>
 *       count operand lanes, each against all four integer targets
 *   clause5-soak cvtfrom32|cvtfrom64 <count> <seed> <rne|rtz|rdn|rup>
 *       count lanes per source type i32/u32/i64/u64
 *   clause5-soak rem32|rem64 <count> <seed>
 *   clause5-soak nextup64|nextdown64|logb64|class64 <count> <seed>
 *   clause5-soak probe scalbn|castflags|cvtfrom
 *       report the environment verdicts and exit 0 iff values honour
 *       the rounding modes (the script gates directed jobs on this)
 *
 * EXHAUSTIVE modes of the operations whose operand is 32 bits wide, one
 * for each random mode that would otherwise only sample it. Each takes
 * the operand's encodings [lo, hi) - 0 <= lo < hi <= 2^32, so a slice
 * is any part of the space - and calls the same batch kernels as the
 * random mode of the operation: the oracle, flag discipline, probes and
 * sabotage below are that mode's, and only the operand source differs.
 * A reader tells one from the other by the job word, which ends -all or
 * -wide here, and by the arguments: <lo> <hi>, not <count> <seed>.
 *
 *   clause5-soak conv32to64-all <lo> <hi>
 *       every fp32 encoding widened to fp64
 *   clause5-soak cvtto32-all <lo> <hi> <rne|rtz|rdn|rup|rmm>
 *       every fp32 encoding against all four integer targets, each
 *       in-range lane as exact=0 and exact=1
 *   clause5-soak cvtfrom32-all|cvtfrom64-all <lo> <hi> <rne|rtz|rdn|rup>
 *       every 32-bit integer as an i32 and as a u32 source, converted to
 *       fp32 (cvtfrom32-all) or fp64 (cvtfrom64-all)
 *   clause5-soak scaleb32-all <lo> <hi> <rne|rtz|rdn|rup>
 *       every fp32 encoding against the directed exponent list
 *   clause5-soak scaleb32-wide <lo> <hi> <rne|rtz|rdn|rup>
 *       every fp32 encoding against every exponent that can change a
 *       result, -278..277, and against twelve past those edges that
 *       must land as the edges do
 *   clause5-soak probe scalebrange
 *       measure that range on the host's libm and exit 0 iff it holds
 *
 * The exhaustive modes print "..., E encodings, S skipped" after the
 * usual counts on the verdict line: E operand encodings ran, and every
 * (encoding, check) pair was either compared or skipped, so cases + S is
 * k * E with k fixed by the mode (1, 4, 2, 2, 17 and 568). Skipped is
 * zero except in cvtto32-all, which compares in-range lanes only. See
 * the section "Exhaustive modes" below.
 *
 * Which of them reach a device: scaleb32-all and scaleb32-wide are
 * composed from tile passes (below the format's subnormal floor, -149
 * for fp32, cft_scaleb takes its host path). conv32to64-all, cvtto32-all,
 * cvtfrom32-all and cvtfrom64-all are libcft HOST operations (the
 * header of host/src/clause5.c: no floating-point arithmetic, the
 * device argument is context): a run of them against a device is
 * libcft's host code against this CPU, bit-identical on every backend
 * by construction, and the software backend repeats it.
 *
 * CLASS-LEVEL (L2) modes of the 64-bit rounding operations, one for each of
 * five random modes whose operand space (2^64) no sweep reaches. Each takes
 * <lo> <hi> over the operation's INDEX space (the operands of a representative
 * of every class of dropped bits, with a walking one over the kept and dropped
 * bits, at every rounding position and at the range edges), calls the same
 * batch kernels as the random mode, and prints the exhaustive modes' verdict
 * clause with k fixed by the mode (1 for conv64to32-class and cvtfrom64-class;
 * 4 for cvtto64-class, a case a target, and for rint64-class and
 * scaleb64-class, a case a lane of a tile), E counting indices. A class
 * case is run alone, and the tile modes in each lane. The job word ends
 * -class. See the
 * section "Class-level (L2) modes" below, and python/c5_class_enum.py, which is
 * the reference for the index maps and the counts. The claim is at the class
 * level and is plausible: it rests on the structure SWP-A section 4.3 assumes.
 *
 *   clause5-soak conv64to32-class|cvtfrom64-class|scaleb64-class <lo> <hi>
 *                <rne|rtz|rdn|rup>
 *       the fp64 -> fp32 narrowing; the 64-bit integer sources i64 and u64
 *       converted to fp64; x * 2^n in the subnormal strips and at overflow
 *   clause5-soak rint64-class|cvtto64-class <lo> <hi> <rne|rtz|rdn|rup|rmm>
 *       roundToIntegral, both variants (k = 4: each operand in each lane); fp64
 *       against all four integer targets, in-range lanes only (cvtto64-class:
 *       k = 4, S counts the rest)
 *   clause5-soak dump <job>-class size | <lo> <hi>
 *       print the index space's size, or one line an index (index, operand,
 *       and the source type or the exponent), for a diff against the Python
 *       reference; opens no device
 *
 * Which of them reach a device: rint64-class and scaleb64-class (the latter
 * for exponents at or above -1074; below that cft_scaleb takes its host path).
 * conv64to32-class, cvtto64-class and cvtfrom64-class are libcft HOST
 * operations, as their random modes are.
 *
 * CFT_SOAK_SABOTAGE=1 flips the low bit of the first result of every
 * library call, after the library computes it. A harness that cannot
 * fail proves nothing; the runner requires one sabotaged job to fail
 * before believing any green.
 */

#define _GNU_SOURCE   /* issignaling, roundeven declarations (glibc) */

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"

#pragma STDC FENV_ACCESS ON

#define BATCH 4096

static cft_device *dev;
static uint64_t mismatches, flag_mismatches, cases, skipped;
static int shown;
static uint64_t encodings;   /* exhaustive modes: operand encodings run (see the section
                              * "Exhaustive modes" below) */
static int exh_mode;          /* set for the -all, -wide and -class jobs: their
                              * verdict line says what they covered */

/* ---- rounding modes ----------------------------------------------- */

static const struct { const char *name; cft_round cr; int fe; }
MODES[] = {
    { "rne", CFT_RNE, FE_TONEAREST  },
    { "rtz", CFT_RTZ, FE_TOWARDZERO },
    { "rdn", CFT_RDN, FE_DOWNWARD   },
    { "rup", CFT_RUP, FE_UPWARD     },
    /* RMM has no fenv mode; the ops that accept it here have
     * mode-independent ties-away oracles (round, llround). */
    { "rmm", CFT_RMM, FE_TONEAREST  },
};

static int mode_index(const char *s)
{
    int i;
    for (i = 0; i < 5; i++)
        if (!strcmp(MODES[i].name, s))
            return i;
    return -1;
}

/* ---- flag mapping and bit views ----------------------------------- */

static uint32_t fe_to_cft(int ex)
{
    uint32_t f = 0;
    if (ex & FE_INVALID)   f |= CFT_FLAG_INVALID;
    if (ex & FE_DIVBYZERO) f |= CFT_FLAG_DIVBYZERO;
    if (ex & FE_OVERFLOW)  f |= CFT_FLAG_OVERFLOW;
    if (ex & FE_UNDERFLOW) f |= CFT_FLAG_UNDERFLOW;
    if (ex & FE_INEXACT)   f |= CFT_FLAG_INEXACT;
    return f;
}

static uint32_t f2u(float x)  { uint32_t u; memcpy(&u, &x, 4); return u; }
static float    u2f(uint32_t u) { float x; memcpy(&x, &u, 4); return x; }
static uint64_t d2u(double x) { uint64_t u; memcpy(&u, &x, 8); return u; }
static double   u2d(uint64_t u) { double x; memcpy(&x, &u, 8); return x; }

#define EXPM32  (0xffu << 23)
#define QBIT32  (1u << 22)
#define SIGN32  (1u << 31)
#define EXPM64  (0x7ffull << 52)
#define QBIT64  (1ull << 51)
#define SIGN64  (1ull << 63)

static int is_nan32(uint32_t u)
{
    return (u & EXPM32) == EXPM32 && (u & 0x007fffffu);
}

static int is_nan64(uint64_t u)
{
    return (u & EXPM64) == EXPM64 && (u & 0x000fffffffffffffull);
}

/* The contract's signaling test (quiet bit clear), used to DERIVE
 * expected flags. The class oracle uses glibc's issignaling instead,
 * so the two definitions check each other across the sweep. */
static int is_snan32(uint32_t u) { return is_nan32(u) && !(u & QBIT32); }
static int is_snan64(uint64_t u) { return is_nan64(u) && !(u & QBIT64); }

static int is_finite32(uint32_t u) { return (u & EXPM32) != EXPM32; }
static int is_finite64(uint64_t u) { return (u & EXPM64) != EXPM64; }
static int is_inf32(uint32_t u) { return (u & ~SIGN32) == EXPM32; }
static int is_inf64(uint64_t u) { return (u & ~SIGN64) == EXPM64; }
static int is_zero32(uint32_t u) { return (u & ~SIGN32) == 0; }
static int is_zero64(uint64_t u) { return (u & ~SIGN64) == 0; }

/* value agreement: bit-identical, or both NaN (payload is the
 * model-pinned canonicalisation difference - see the header) */
static int agree32(uint32_t a, uint32_t b)
{
    return a == b || (is_nan32(a) && is_nan32(b));
}

static int agree64(uint64_t a, uint64_t b)
{
    return a == b || (is_nan64(a) && is_nan64(b));
}

/* ---- random operands (divsqrt_soak's, restated) ------------------- */

static uint64_t rng_state;

static uint64_t rng(void)
{
    uint64_t x = rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return rng_state = x;
}

static uint32_t banded32(void)
{
    uint32_t x = (uint32_t)rng();
    if ((rng() & 3) == 0) {
        static const uint32_t bands[7] = {0, 1, 2, 127, 252, 253, 254};
        uint32_t e = bands[rng() % 7] + (uint32_t)(rng() % 3);
        if (e > 255) e = 255;
        x = (x & 0x807fffffu) | (e << 23);
    }
    return x;
}

static uint64_t banded64(void)
{
    uint64_t x = rng();
    if ((rng() & 3) == 0) {
        static const uint64_t bands[7] = {0, 1, 2, 1023, 2044, 2045, 2046};
        uint64_t e = bands[rng() % 7] + (rng() % 3);
        if (e > 2047) e = 2047;
        x = (x & 0x800fffffffffffffull) | (e << 52);
    }
    return x;
}

/* Probe conversions must not be re-scheduled around the flag reads:
 * gcc does not model FENV_ACCESS, and it will sink a cast below
 * fetestexcept when the result is only consumed by a cold boolean
 * (measured here on gcc 13: the castflags probe read zero flags the
 * hardware had raised, and the disassembly showed cvtsd2ss scheduled
 * after the fetestexcept call). A store to a static volatile is
 * memory an opaque libc call may observe, so the conversion is
 * anchored before the read. The batch loops never needed this - they
 * store results to static arrays before reading flags - but every
 * probe case and every per-element flag recheck goes through these
 * sinks. */
static volatile uint32_t c5_sink32;
static volatile uint64_t c5_sink64;

/* ---- negative control --------------------------------------------- */

static int sabotage = -1;

static void sab(void *d, size_t esz, size_t n)
{
    if (sabotage < 0) {
        const char *e = getenv("CFT_SOAK_SABOTAGE");
        sabotage = (e && *e == '1') ? 1 : 0;
    }
    (void)esz;
    if (sabotage && n > 0)
        ((uint8_t *)d)[0] ^= 1u;
}

/* ---- mismatch reporting ------------------------------------------- */

static void vmis(const char *what, const char *mode, uint64_t xa,
                 int has_b, uint64_t xb, uint64_t got, uint64_t want)
{
    mismatches++;
    if (shown++ >= 16)
        return;
    if (has_b)
        printf("  MISMATCH %s %s a=0x%016llx b=0x%016llx lib=0x%016llx "
               "cpu=0x%016llx\n", what, mode, (unsigned long long)xa,
               (unsigned long long)xb, (unsigned long long)got,
               (unsigned long long)want);
    else
        printf("  MISMATCH %s %s a=0x%016llx lib=0x%016llx cpu=0x%016llx\n",
               what, mode, (unsigned long long)xa,
               (unsigned long long)got, (unsigned long long)want);
}

static void fmis(const char *what, const char *mode, uint64_t xa,
                 uint32_t lib, uint32_t want)
{
    flag_mismatches++;
    if (shown++ >= 16)
        return;
    printf("  FLAGS %s %s a=0x%016llx lib=0x%02x want=0x%02x\n",
           what, mode, (unsigned long long)xa, (unsigned)lib,
           (unsigned)want);
}

static void hard_fail(const char *what)
{
    printf("  library call failed in %s\n", what);
}

/* ================================================================
 * roundToIntegral
 *
 * Oracle: the five NAMED C functions, which are the five 754
 * roundToIntegral attributes by definition - trunc/floor/ceil are
 * RTZ/RDN/RUP, round is ties-to-away, and RNE is roundeven where the
 * libc has it (probed by the runner, CFT_SOAK_HAVE_ROUNDEVEN) or
 * rint under FE_TONEAREST, which is the same function. None of them
 * signals inexact, matching the contract's named variants; the Exact
 * variant's inexact is derived as "this finite lane's bits changed",
 * which is the library's own definition applied to the ORACLE value.
 * ================================================================ */

static float rint_oracle32(int mi, float x)
{
    switch (mi) {
    case 1:  return truncf(x);
    case 2:  return floorf(x);
    case 3:  return ceilf(x);
    case 4:  return roundf(x);
    default:
#ifdef CFT_SOAK_HAVE_ROUNDEVEN
        return roundevenf(x);
#else
        return rintf(x);         /* FE_TONEAREST is set by the caller */
#endif
    }
}

static double rint_oracle64(int mi, double x)
{
    switch (mi) {
    case 1:  return trunc(x);
    case 2:  return floor(x);
    case 3:  return ceil(x);
    case 4:  return round(x);
    default:
#ifdef CFT_SOAK_HAVE_ROUNDEVEN
        return roundeven(x);
#else
        return rint(x);
#endif
    }
}

/* Per-lane expected flags; exact=1 adds derived inexact. */
static uint32_t rint_expect32(uint32_t in, uint32_t want, int exact)
{
    uint32_t fl = is_snan32(in) ? CFT_FLAG_INVALID : 0;
    if (exact && is_finite32(in) && want != in)
        fl |= CFT_FLAG_INEXACT;
    return fl;
}

static uint32_t rint_expect64(uint64_t in, uint64_t want, int exact)
{
    uint32_t fl = is_snan64(in) ? CFT_FLAG_INVALID : 0;
    if (exact && is_finite64(in) && want != in)
        fl |= CFT_FLAG_INEXACT;
    return fl;
}

/* Flags disagreed at batch level: name the lane with n=1 calls. */
static void rint_recheck32(int mi, const uint32_t *A, size_t n,
                           const uint32_t *W)
{
    size_t i;
    int ex;
    for (i = 0; i < n; i++) {
        for (ex = 0; ex <= 1; ex++) {
            uint32_t d = 0, fl = 0, want;
            if (cft_rint(dev, CFT_FP32, MODES[mi].cr, ex, &A[i], &d, 1,
                         &fl, NULL) != CFT_OK)
                continue;
            want = rint_expect32(A[i], W[i], ex);
            if (fl != want)
                fmis(ex ? "rintx32" : "rint32", MODES[mi].name, A[i],
                     fl, want);
        }
    }
}

static void rint_recheck64(int mi, const uint64_t *A, size_t n,
                           const uint64_t *W)
{
    size_t i;
    int ex;
    for (i = 0; i < n; i++) {
        for (ex = 0; ex <= 1; ex++) {
            uint64_t d = 0;
            uint32_t fl = 0, want;
            if (cft_rint(dev, CFT_FP64, MODES[mi].cr, ex, &A[i], &d, 1,
                         &fl, NULL) != CFT_OK)
                continue;
            want = rint_expect64(A[i], W[i], ex);
            if (fl != want)
                fmis(ex ? "rintx64" : "rint64", MODES[mi].name, A[i],
                     fl, want);
        }
    }
}

static int rint_batch32(int mi, const uint32_t *A, size_t n)
{
    static uint32_t W[BATCH], D0[BATCH], D1[BATCH];
    uint32_t f0 = 0, f1 = 0, e0 = 0, e1 = 0;
    size_t i;

    fesetround(MODES[mi].fe);
    for (i = 0; i < n; i++)
        W[i] = f2u(rint_oracle32(mi, u2f(A[i])));
    fesetround(FE_TONEAREST);
    for (i = 0; i < n; i++) {
        e0 |= rint_expect32(A[i], W[i], 0);
        e1 |= rint_expect32(A[i], W[i], 1);
    }
    if (cft_rint(dev, CFT_FP32, MODES[mi].cr, 0, A, D0, n, &f0, NULL)
        != CFT_OK) { hard_fail("rint32"); return 1; }
    sab(D0, 4, n);
    if (cft_rint(dev, CFT_FP32, MODES[mi].cr, 1, A, D1, n, &f1, NULL)
        != CFT_OK) { hard_fail("rint32"); return 1; }
    sab(D1, 4, n);
    for (i = 0; i < n; i++) {
        if (!agree32(D0[i], W[i]))
            vmis("rint32", MODES[mi].name, A[i], 0, 0, D0[i], W[i]);
        if (!agree32(D1[i], W[i]))
            vmis("rintx32", MODES[mi].name, A[i], 0, 0, D1[i], W[i]);
    }
    if (f0 != e0 || f1 != e1)
        rint_recheck32(mi, A, n, W);
    cases += n;
    return 0;
}

static int rint_batch64(int mi, const uint64_t *A, size_t n)
{
    static uint64_t W[BATCH], D0[BATCH], D1[BATCH];
    uint32_t f0 = 0, f1 = 0, e0 = 0, e1 = 0;
    size_t i;

    fesetround(MODES[mi].fe);
    for (i = 0; i < n; i++)
        W[i] = d2u(rint_oracle64(mi, u2d(A[i])));
    fesetround(FE_TONEAREST);
    for (i = 0; i < n; i++) {
        e0 |= rint_expect64(A[i], W[i], 0);
        e1 |= rint_expect64(A[i], W[i], 1);
    }
    if (cft_rint(dev, CFT_FP64, MODES[mi].cr, 0, A, D0, n, &f0, NULL)
        != CFT_OK) { hard_fail("rint64"); return 1; }
    sab(D0, 8, n);
    if (cft_rint(dev, CFT_FP64, MODES[mi].cr, 1, A, D1, n, &f1, NULL)
        != CFT_OK) { hard_fail("rint64"); return 1; }
    sab(D1, 8, n);
    for (i = 0; i < n; i++) {
        if (!agree64(D0[i], W[i]))
            vmis("rint64", MODES[mi].name, A[i], 0, 0, D0[i], W[i]);
        if (!agree64(D1[i], W[i]))
            vmis("rintx64", MODES[mi].name, A[i], 0, 0, D1[i], W[i]);
    }
    if (f0 != e0 || f1 != e1)
        rint_recheck64(mi, A, n, W);
    cases += n;
    return 0;
}

static int drv_rint32(uint64_t lo, uint64_t hi, int mi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (rint_batch32(mi, A, n))
            return 1;
        v += n;
    }
    return 0;
}

static int drv_rint64(uint64_t count, int mi)
{
    static uint64_t A[BATCH];
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded64();
        if (rint_batch64(mi, A, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * nextUp / nextDown
 *
 * Oracle: nextafter toward the matching infinity. Values are
 * mode-independent bit surgery on both sides, so bit comparison is
 * exact everywhere (NaN as class). glibc's nextafter deliberately
 * signals underflow/inexact on subnormal results and overflow at the
 * top step - Annex F says so - while the contract's nextUp signals
 * only invalid-on-sNaN, so expected flags are DERIVED, never read
 * from fetestexcept. The standard's own signed-zero edges are also
 * asserted directly against contract-derived encodings, so the edge
 * behaviour does not rest on glibc agreeing about zeros.
 * ================================================================ */

static int next_batch32(int up, const uint32_t *A, size_t n)
{
    static uint32_t W[BATCH], D[BATCH];
    uint32_t fl = 0, ex = 0;
    size_t i;
    const char *nm = up ? "nextup32" : "nextdown32";
    cft_status st;

    for (i = 0; i < n; i++) {
        W[i] = f2u(nextafterf(u2f(A[i]), up ? INFINITY : -INFINITY));
        if (is_snan32(A[i]))
            ex |= CFT_FLAG_INVALID;
    }
    feclearexcept(FE_ALL_EXCEPT);   /* nextafter's own signals are noise */
    st = up ? cft_next_up(dev, CFT_FP32, A, D, n, &fl)
            : cft_next_down(dev, CFT_FP32, A, D, n, &fl);
    if (st != CFT_OK) { hard_fail(nm); return 1; }
    sab(D, 4, n);
    for (i = 0; i < n; i++)
        if (!agree32(D[i], W[i]))
            vmis(nm, "-", A[i], 0, 0, D[i], W[i]);
    if (fl != ex) {
        for (i = 0; i < n; i++) {
            uint32_t d1, f1 = 0, want;
            st = up ? cft_next_up(dev, CFT_FP32, &A[i], &d1, 1, &f1)
                    : cft_next_down(dev, CFT_FP32, &A[i], &d1, 1, &f1);
            if (st != CFT_OK)
                continue;
            want = is_snan32(A[i]) ? CFT_FLAG_INVALID : 0;
            if (f1 != want)
                fmis(nm, "-", A[i], f1, want);
        }
    }
    cases += n;
    return 0;
}

static int next_batch64(int up, const uint64_t *A, size_t n)
{
    static uint64_t W[BATCH], D[BATCH];
    uint32_t fl = 0, ex = 0;
    size_t i;
    const char *nm = up ? "nextup64" : "nextdown64";
    cft_status st;

    for (i = 0; i < n; i++) {
        W[i] = d2u(nextafter(u2d(A[i]), up ? INFINITY : -INFINITY));
        if (is_snan64(A[i]))
            ex |= CFT_FLAG_INVALID;
    }
    feclearexcept(FE_ALL_EXCEPT);
    st = up ? cft_next_up(dev, CFT_FP64, A, D, n, &fl)
            : cft_next_down(dev, CFT_FP64, A, D, n, &fl);
    if (st != CFT_OK) { hard_fail(nm); return 1; }
    sab(D, 8, n);
    for (i = 0; i < n; i++)
        if (!agree64(D[i], W[i]))
            vmis(nm, "-", A[i], 0, 0, D[i], W[i]);
    if (fl != ex) {
        for (i = 0; i < n; i++) {
            uint64_t d1;
            uint32_t f1 = 0, want;
            st = up ? cft_next_up(dev, CFT_FP64, &A[i], &d1, 1, &f1)
                    : cft_next_down(dev, CFT_FP64, &A[i], &d1, 1, &f1);
            if (st != CFT_OK)
                continue;
            want = is_snan64(A[i]) ? CFT_FLAG_INVALID : 0;
            if (f1 != want)
                fmis(nm, "-", A[i], f1, want);
        }
    }
    cases += n;
    return 0;
}

/* The 5.3.1 edges, checked against encodings derived from the
 * contract itself (not from the libm oracle): nextUp(+-0) is
 * +min_subnormal, nextUp(-min_subnormal) is MINUS zero, the largest
 * finite steps to infinity, -inf steps back to -max_normal. */
static int next_edges32(int up)
{
    const uint32_t minsub = 1u, maxn = EXPM32 - 1, inf = EXPM32;
    const uint32_t upin[8] = { 0, SIGN32, SIGN32 | minsub, maxn,
                               SIGN32 | inf, inf, minsub, SIGN32 | maxn };
    const uint32_t upex[8] = { minsub, minsub, SIGN32, inf,
                               SIGN32 | maxn, inf, 2u,
                               SIGN32 | (maxn - 1) };
    size_t i;
    for (i = 0; i < 8; i++) {
        /* nextDown(x) is -nextUp(-x): same table, signs flipped. */
        uint32_t in = up ? upin[i] : upin[i] ^ SIGN32;
        uint32_t want = up ? upex[i] : upex[i] ^ SIGN32;
        uint32_t d = 0, fl = 0;
        cft_status st = up
            ? cft_next_up(dev, CFT_FP32, &in, &d, 1, &fl)
            : cft_next_down(dev, CFT_FP32, &in, &d, 1, &fl);
        if (st != CFT_OK) { hard_fail("next32 edges"); return 1; }
        sab(&d, 4, 1);
        if (d != want)
            vmis(up ? "nextup32-edge" : "nextdown32-edge", "-",
                 in, 0, 0, d, want);
        if (fl != 0)
            fmis(up ? "nextup32-edge" : "nextdown32-edge", "-", in, fl, 0);
        cases++;
    }
    return 0;
}

static int next_edges64(int up)
{
    const uint64_t minsub = 1ull, maxn = EXPM64 - 1, inf = EXPM64;
    const uint64_t upin[8] = { 0, SIGN64, SIGN64 | minsub, maxn,
                               SIGN64 | inf, inf, minsub, SIGN64 | maxn };
    const uint64_t upex[8] = { minsub, minsub, SIGN64, inf,
                               SIGN64 | maxn, inf, 2ull,
                               SIGN64 | (maxn - 1) };
    size_t i;
    for (i = 0; i < 8; i++) {
        uint64_t in = up ? upin[i] : upin[i] ^ SIGN64;
        uint64_t want = up ? upex[i] : upex[i] ^ SIGN64;
        uint64_t d = 0;
        uint32_t fl = 0;
        cft_status st = up
            ? cft_next_up(dev, CFT_FP64, &in, &d, 1, &fl)
            : cft_next_down(dev, CFT_FP64, &in, &d, 1, &fl);
        if (st != CFT_OK) { hard_fail("next64 edges"); return 1; }
        sab(&d, 8, 1);
        if (d != want)
            vmis(up ? "nextup64-edge" : "nextdown64-edge", "-",
                 in, 0, 0, d, want);
        if (fl != 0)
            fmis(up ? "nextup64-edge" : "nextdown64-edge", "-", in, fl, 0);
        cases++;
    }
    return 0;
}

static int drv_next32(int up, uint64_t lo, uint64_t hi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    if (next_edges32(up))
        return 1;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (next_batch32(up, A, n))
            return 1;
        v += n;
    }
    return 0;
}

static int drv_next64(int up, uint64_t count)
{
    static uint64_t A[BATCH];
    if (next_edges64(up))
        return 1;
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded64();
        if (next_batch64(up, A, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * logB
 *
 * Oracle: logbf/logb, which glibc computes value-based on subnormals
 * (the historical fdlibm subnormal bug is long fixed). Expected flags
 * derived: divideByZero for a zero operand, invalid for sNaN, nothing
 * else - matching the contract's always-exact promise.
 * ================================================================ */

static int logb_batch32(const uint32_t *A, size_t n)
{
    static uint32_t W[BATCH], D[BATCH];
    uint32_t fl = 0, ex = 0;
    size_t i;

    for (i = 0; i < n; i++) {
        W[i] = f2u(logbf(u2f(A[i])));
        if (is_zero32(A[i]))
            ex |= CFT_FLAG_DIVBYZERO;
        if (is_snan32(A[i]))
            ex |= CFT_FLAG_INVALID;
    }
    feclearexcept(FE_ALL_EXCEPT);
    if (cft_logb(dev, CFT_FP32, A, D, n, &fl) != CFT_OK) {
        hard_fail("logb32"); return 1;
    }
    sab(D, 4, n);
    for (i = 0; i < n; i++)
        if (!agree32(D[i], W[i]))
            vmis("logb32", "-", A[i], 0, 0, D[i], W[i]);
    if (fl != ex) {
        for (i = 0; i < n; i++) {
            uint32_t d1, f1 = 0, want;
            if (cft_logb(dev, CFT_FP32, &A[i], &d1, 1, &f1) != CFT_OK)
                continue;
            want = (is_zero32(A[i]) ? CFT_FLAG_DIVBYZERO : 0) |
                   (is_snan32(A[i]) ? CFT_FLAG_INVALID : 0);
            if (f1 != want)
                fmis("logb32", "-", A[i], f1, want);
        }
    }
    cases += n;
    return 0;
}

static int logb_batch64(const uint64_t *A, size_t n)
{
    static uint64_t W[BATCH], D[BATCH];
    uint32_t fl = 0, ex = 0;
    size_t i;

    for (i = 0; i < n; i++) {
        W[i] = d2u(logb(u2d(A[i])));
        if (is_zero64(A[i]))
            ex |= CFT_FLAG_DIVBYZERO;
        if (is_snan64(A[i]))
            ex |= CFT_FLAG_INVALID;
    }
    feclearexcept(FE_ALL_EXCEPT);
    if (cft_logb(dev, CFT_FP64, A, D, n, &fl) != CFT_OK) {
        hard_fail("logb64"); return 1;
    }
    sab(D, 8, n);
    for (i = 0; i < n; i++)
        if (!agree64(D[i], W[i]))
            vmis("logb64", "-", A[i], 0, 0, D[i], W[i]);
    if (fl != ex) {
        for (i = 0; i < n; i++) {
            uint64_t d1;
            uint32_t f1 = 0, want;
            if (cft_logb(dev, CFT_FP64, &A[i], &d1, 1, &f1) != CFT_OK)
                continue;
            want = (is_zero64(A[i]) ? CFT_FLAG_DIVBYZERO : 0) |
                   (is_snan64(A[i]) ? CFT_FLAG_INVALID : 0);
            if (f1 != want)
                fmis("logb64", "-", A[i], f1, want);
        }
    }
    cases += n;
    return 0;
}

static int drv_logb32(uint64_t lo, uint64_t hi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (logb_batch32(A, n))
            return 1;
        v += n;
    }
    return 0;
}

static int drv_logb64(uint64_t count)
{
    static uint64_t A[BATCH];
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded64();
        if (logb_batch64(A, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * class
 *
 * Oracle: fpclassify + signbit for the eight number classes, and
 * glibc's issignaling for the NaN split (with the bit test as a
 * documented fallback where the macro is missing). Non-computational:
 * there are no flags to check, only the byte.
 * ================================================================ */

static uint8_t class_oracle32(uint32_t u)
{
    float x = u2f(u);
    switch (fpclassify(x)) {
    case FP_INFINITE:
        return signbit(x) ? CFT_CLASS_NEG_INF : CFT_CLASS_POS_INF;
    case FP_NORMAL:
        return signbit(x) ? CFT_CLASS_NEG_NORM : CFT_CLASS_POS_NORM;
    case FP_SUBNORMAL:
        return signbit(x) ? CFT_CLASS_NEG_SUB : CFT_CLASS_POS_SUB;
    case FP_ZERO:
        return signbit(x) ? CFT_CLASS_NEG_ZERO : CFT_CLASS_POS_ZERO;
    default:
#ifdef issignaling
        return issignaling(x) ? CFT_CLASS_SNAN : CFT_CLASS_QNAN;
#else
        return is_snan32(u) ? CFT_CLASS_SNAN : CFT_CLASS_QNAN;
#endif
    }
}

static uint8_t class_oracle64(uint64_t u)
{
    double x = u2d(u);
    switch (fpclassify(x)) {
    case FP_INFINITE:
        return signbit(x) ? CFT_CLASS_NEG_INF : CFT_CLASS_POS_INF;
    case FP_NORMAL:
        return signbit(x) ? CFT_CLASS_NEG_NORM : CFT_CLASS_POS_NORM;
    case FP_SUBNORMAL:
        return signbit(x) ? CFT_CLASS_NEG_SUB : CFT_CLASS_POS_SUB;
    case FP_ZERO:
        return signbit(x) ? CFT_CLASS_NEG_ZERO : CFT_CLASS_POS_ZERO;
    default:
#ifdef issignaling
        return issignaling(x) ? CFT_CLASS_SNAN : CFT_CLASS_QNAN;
#else
        return is_snan64(u) ? CFT_CLASS_SNAN : CFT_CLASS_QNAN;
#endif
    }
}

static int class_batch32(const uint32_t *A, size_t n)
{
    static uint8_t C[BATCH];
    size_t i;
    if (cft_class(dev, CFT_FP32, A, C, n) != CFT_OK) {
        hard_fail("class32"); return 1;
    }
    sab(C, 1, n);
    for (i = 0; i < n; i++) {
        uint8_t w = class_oracle32(A[i]);
        if (C[i] != w)
            vmis("class32", "-", A[i], 0, 0, C[i], w);
    }
    cases += n;
    return 0;
}

static int class_batch64(const uint64_t *A, size_t n)
{
    static uint8_t C[BATCH];
    size_t i;
    if (cft_class(dev, CFT_FP64, A, C, n) != CFT_OK) {
        hard_fail("class64"); return 1;
    }
    sab(C, 1, n);
    for (i = 0; i < n; i++) {
        uint8_t w = class_oracle64(A[i]);
        if (C[i] != w)
            vmis("class64", "-", A[i], 0, 0, C[i], w);
    }
    cases += n;
    return 0;
}

static int drv_class32(uint64_t lo, uint64_t hi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (class_batch32(A, n))
            return 1;
        v += n;
    }
    return 0;
}

static int drv_class64(uint64_t count)
{
    static uint64_t A[BATCH];
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded64();
        if (class_batch64(A, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * scaleB
 *
 * Oracle: scalbnf/scalbn under fesetround. glibc lands subnormal and
 * saturated results through real hardware multiplies, which honour
 * the dynamic mode and raise the contract's own flags - but that is
 * an implementation fact, not a documented promise, so a directed
 * probe proves it before any directed-mode job runs: value honour
 * gates the job (the runner also asks via `probe scalbn`), and flag
 * honour gates the flag comparison, each degradation printed.
 *
 * nexp sweeps a directed list per operand: the values the task pins
 * (0, +-1, +-23, +-52, +-126, +-127, +-149, +-150, +-1000 - the two
 * significand widths, fp32's emin, exponent edges around fp32's
 * subnormal floor, and a beyond-everything magnitude), plus fp64's
 * own edges for the 64-bit lane (+-1022, +-1023, +-1074, +-1075) and
 * +-2200, past 2x emax, to force the saturated and host paths.
 * ================================================================ */

static const int64_t SCALEB_N32[] = {
    0, 1, -1, 23, -23, 52, -52, 126, -126, 127, -127,
    149, -149, 150, -150, 1000, -1000
};
static const int64_t SCALEB_N64[] = {
    0, 1, -1, 23, -23, 52, -52, 126, -126, 127, -127,
    149, -149, 150, -150, 1000, -1000,
    1022, -1022, 1023, -1023, 1074, -1074, 1075, -1075, 2200, -2200
};

/* One directed scalbn case: does the value land where the contract
 * says, and does the environment raise exactly the expected flags? */
static int scalbn_case32(int fe, uint32_t in, int nn, uint32_t want,
                         uint32_t wantfl, int *flags_ok)
{
    volatile uint32_t vin = in;  /* volatile, here and in every probe:
                                  * a constant-folded oracle raises no
                                  * flags at runtime, and the probe
                                  * would blame the environment for
                                  * the compiler's shortcut */
    uint32_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = f2u(scalbnf(u2f(vin), nn));
    c5_sink32 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    if (fe_to_cft(raised) != wantfl)
        *flags_ok = 0;
    return got == want;
}

static int scalbn_case64(int fe, uint64_t in, int nn, uint64_t want,
                         uint32_t wantfl, int *flags_ok)
{
    volatile uint64_t vin = in;
    uint64_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = d2u(scalbn(u2d(vin), nn));
    c5_sink64 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    if (fe_to_cft(raised) != wantfl)
        *flags_ok = 0;
    return got == want;
}

/* Every encoding below is derived where it stands: min_subnormal is
 * encoding 1, max_normal is the infinity encoding minus one, and the
 * probe values are one-ulp dressings of 1.0 whose rounded landings
 * are worked out in the comments. UF here is underflow|inexact, OF
 * overflow|inexact - the pairs 754 makes inseparable on these
 * cases. */
static int probe_scalbn(int *flags_ok)
{
    const uint32_t one32 = 127u << 23;          /* 1.0f */
    const uint32_t onep32 = one32 | 1u;         /* 1 + 2^-23 */
    const uint32_t oneh32 = one32 | (1u << 22); /* 1.5 */
    const uint32_t max32 = EXPM32 - 1, inf32 = EXPM32;
    const uint64_t one64 = 1023ull << 52;
    const uint64_t onep64 = one64 | 1ull;       /* 1 + 2^-52 */
    const uint64_t max64 = EXPM64 - 1, inf64 = EXPM64;
    const uint32_t UF = CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
    const uint32_t OF = CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
    int ok = 1, fok = 1;

    /* (1+2^-23)*2^-149 sits between min_sub and 2*min_sub, nearer
     * min_sub: up in RUP alone. */
    ok &= scalbn_case32(FE_TONEAREST,  onep32, -149, 1u, UF, &fok);
    ok &= scalbn_case32(FE_TOWARDZERO, onep32, -149, 1u, UF, &fok);
    ok &= scalbn_case32(FE_DOWNWARD,   onep32, -149, 1u, UF, &fok);
    ok &= scalbn_case32(FE_UPWARD,     onep32, -149, 2u, UF, &fok);
    /* 1.0*2^-150 is the exact midpoint of [0, min_sub]: the even end
     * (zero) for RNE, up only for RUP. */
    ok &= scalbn_case32(FE_TONEAREST,  one32, -150, 0u, UF, &fok);
    ok &= scalbn_case32(FE_UPWARD,     one32, -150, 1u, UF, &fok);
    ok &= scalbn_case32(FE_DOWNWARD,   one32, -150, 0u, UF, &fok);
    /* 1.5*2^-149: midpoint of [min_sub, 2*min_sub]; RNE takes the
     * even (2), RDN/RTZ the low end. */
    ok &= scalbn_case32(FE_TONEAREST,  oneh32, -149, 2u, UF, &fok);
    ok &= scalbn_case32(FE_TOWARDZERO, oneh32, -149, 1u, UF, &fok);
    /* Overflow honours 7.4: RTZ and RDN(+) stop at max_normal. */
    ok &= scalbn_case32(FE_TONEAREST,  max32, 1, inf32, OF, &fok);
    ok &= scalbn_case32(FE_TOWARDZERO, max32, 1, max32, OF, &fok);
    ok &= scalbn_case32(FE_DOWNWARD,   max32, 1, max32, OF, &fok);
    ok &= scalbn_case32(FE_UPWARD,     max32, 1, inf32, OF, &fok);
    ok &= scalbn_case32(FE_DOWNWARD, SIGN32 | max32, 1,
                        SIGN32 | inf32, OF, &fok);
    ok &= scalbn_case32(FE_TOWARDZERO, SIGN32 | max32, 1,
                        SIGN32 | max32, OF, &fok);
    /* The saturated big-n paths must land the same way. */
    ok &= scalbn_case32(FE_TOWARDZERO, one32, 100000, max32, OF, &fok);
    ok &= scalbn_case32(FE_UPWARD,     one32, -100000, 1u, UF, &fok);
    ok &= scalbn_case32(FE_DOWNWARD, SIGN32 | one32, -100000,
                        SIGN32 | 1u, UF, &fok);
    ok &= scalbn_case32(FE_TONEAREST,  one32, -100000, 0u, UF, &fok);
    /* fp64 restates the same geometry at its own floor. */
    ok &= scalbn_case64(FE_TONEAREST,  onep64, -1074, 1ull, UF, &fok);
    ok &= scalbn_case64(FE_UPWARD,     onep64, -1074, 2ull, UF, &fok);
    ok &= scalbn_case64(FE_TONEAREST,  one64, -1075, 0ull, UF, &fok);
    ok &= scalbn_case64(FE_UPWARD,     one64, -1075, 1ull, UF, &fok);
    ok &= scalbn_case64(FE_TOWARDZERO, max64, 1, max64, OF, &fok);
    ok &= scalbn_case64(FE_TONEAREST,  max64, 1, inf64, OF, &fok);
    ok &= scalbn_case64(FE_UPWARD,     one64, -100000, 1ull, UF, &fok);
    ok &= scalbn_case64(FE_TOWARDZERO, one64, 100000, max64, OF, &fok);
    if (flags_ok)
        *flags_ok = fok;
    return ok;
}

/* The scalbn probe's verdict, applied: 1 when a job may run. The random
 * modes and the exhaustive ones say the same words. */
static int scaleb_gate(int mi, int *flags_ok)
{
    int values_ok = probe_scalbn(flags_ok);

    if (!values_ok && mi != 0) {
        printf("scalbn probe: directed-mode values NOT honoured; "
               "this job is covered by rne + the model matrix\n");
        return 0;                 /* main prints the zero-case line */
    }
    if (!*flags_ok)
        printf("scalbn probe: flag environment unreliable; "
               "comparing values only\n");
    return 1;
}

/* One batch of n operands (fp32 or fp64, by is64) against each exponent
 * of `list`: the oracle's scalbn under the attribute's rounding mode,
 * then the library, values compared per lane and flags by the batch OR
 * first, the lane named by n=1 calls only when the OR disagrees.
 * `orc`, when given, is the exponent the ORACLE is asked for where the
 * library is asked for list[li]: scaleb32-wide checks the exponents
 * past its range against the oracle at the range's edge that way. Every
 * exponent adds n to `cases`. The random mode and the exhaustive ones
 * both run exactly this. */
static int scaleb_batch(int is64, int mi, const void *ops, size_t n,
                        const int64_t *list, const int64_t *orc,
                        size_t listn, int flags_ok, const char *nm)
{
    static uint32_t D32[BATCH], W32[BATCH];
    static uint64_t D64[BATCH], W64[BATCH];
    const uint32_t *A32 = (const uint32_t *)ops;
    const uint64_t *A64 = (const uint64_t *)ops;
    size_t i, li;

    for (li = 0; li < listn; li++) {
        int nn = (int)(orc ? orc[li] : list[li]);
        uint32_t nf, lf = 0;
        int raised;
        cft_status st;
        fesetround(MODES[mi].fe);
        feclearexcept(FE_ALL_EXCEPT);
        if (is64)
            for (i = 0; i < n; i++)
                W64[i] = d2u(scalbn(u2d(A64[i]), nn));
        else
            for (i = 0; i < n; i++)
                W32[i] = f2u(scalbnf(u2f(A32[i]), nn));
        raised = fetestexcept(FE_ALL_EXCEPT);
        fesetround(FE_TONEAREST);
        nf = fe_to_cft(raised);
        st = is64
            ? cft_scaleb(dev, CFT_FP64, MODES[mi].cr, A64, list[li],
                         D64, n, &lf, NULL)
            : cft_scaleb(dev, CFT_FP32, MODES[mi].cr, A32, list[li],
                         D32, n, &lf, NULL);
        if (st != CFT_OK) { hard_fail(nm); return 1; }
        sab(is64 ? (void *)D64 : (void *)D32, is64 ? 8 : 4, n);
        for (i = 0; i < n; i++) {
            if (is64 ? !agree64(D64[i], W64[i])
                     : !agree32(D32[i], W32[i]))
                vmis(nm, MODES[mi].name,
                     is64 ? A64[i] : (uint64_t)A32[i], 1,
                     (uint64_t)list[li],
                     is64 ? D64[i] : (uint64_t)D32[i],
                     is64 ? W64[i] : (uint64_t)W32[i]);
        }
        if (flags_ok && lf != nf) {
            /* name the lane: per-element oracle and library */
            for (i = 0; i < n; i++) {
                uint32_t f1 = 0, w1;
                uint64_t dv;
                fesetround(MODES[mi].fe);
                feclearexcept(FE_ALL_EXCEPT);
                c5_sink64 = is64
                    ? d2u(scalbn(u2d(A64[i]), nn))
                    : (uint64_t)f2u(scalbnf(u2f(A32[i]), nn));
                raised = fetestexcept(FE_ALL_EXCEPT);
                fesetround(FE_TONEAREST);
                w1 = fe_to_cft(raised);
                st = is64
                    ? cft_scaleb(dev, CFT_FP64, MODES[mi].cr, &A64[i],
                                 list[li], &dv, 1, &f1, NULL)
                    : cft_scaleb(dev, CFT_FP32, MODES[mi].cr, &A32[i],
                                 list[li], &D32[i], 1, &f1, NULL);
                if (st != CFT_OK)
                    continue;
                if (f1 != w1)
                    fmis(nm, MODES[mi].name,
                         is64 ? A64[i] : (uint64_t)A32[i], f1, w1);
            }
        }
        cases += n;
    }
    return 0;
}

static int drv_scaleb(int is64, uint64_t count, int mi)
{
    static uint32_t A32[BATCH];
    static uint64_t A64[BATCH];
    const int64_t *list = is64 ? SCALEB_N64 : SCALEB_N32;
    size_t listn = is64 ? sizeof(SCALEB_N64) / sizeof(SCALEB_N64[0])
                        : sizeof(SCALEB_N32) / sizeof(SCALEB_N32[0]);
    const char *nm = is64 ? "scaleb64" : "scaleb32";
    int flags_ok = 1;

    if (!scaleb_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        uint64_t sub;
        for (i = 0; i < n; i++) {
            if (is64) A64[i] = banded64(); else A32[i] = banded32();
        }
        if (scaleb_batch(is64, mi,
                         is64 ? (const void *)A64 : (const void *)A32, n,
                         list, NULL, listn, flags_ok, nm))
            return 1;
        sub = (uint64_t)n * listn;
        count = count > sub ? count - sub : 0;
    }
    return 0;
}

/* ================================================================
 * convertFormat, fp32 <-> fp64
 *
 * Narrowing oracle: a plain (float) cast - one cvtsd2ss, correctly
 * rounded in the dynamic mode under -frounding-math, raising the
 * hardware's overflow/underflow/inexact/invalid. The flag
 * environment is probed with directed cases whose expected sets are
 * derived in the comments; failure degrades to value-only, said out
 * loud. Widening is exact: bits must match (NaN as class) and the
 * only expected flag is invalid-on-sNaN, derived.
 * ================================================================ */

static int castflags_case(int fe, uint64_t in, uint32_t want,
                          uint32_t wantfl)
{
    volatile uint64_t vin = in;
    uint32_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = f2u((float)u2d(vin));
    c5_sink32 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    if (got != want || fe_to_cft(raised) != wantfl) {
        printf("  castflags case in=0x%016llx fe=%d: got=0x%08x "
               "want=0x%08x raised=0x%02x wantfl=0x%02x\n",
               (unsigned long long)in, fe, got, want,
               (unsigned)fe_to_cft(raised), (unsigned)wantfl);
        return 0;
    }
    return 1;
}

static int probe_castflags(void)
{
    const uint64_t one64 = 1023ull << 52;
    const uint32_t max32 = EXPM32 - 1, inf32 = EXPM32;
    const uint32_t UF = CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
    const uint32_t OF = CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
    int ok = 1;

    /* 2^128 overflows fp32 in every mode; RTZ delivers max_normal. */
    ok &= castflags_case(FE_TONEAREST, (1023ull + 128) << 52, inf32, OF);
    ok &= castflags_case(FE_TOWARDZERO, (1023ull + 128) << 52, max32, OF);
    /* 2^-150 is the midpoint tie at the bottom: +0 under RNE,
     * min_sub under RUP, both tiny and inexact. */
    ok &= castflags_case(FE_TONEAREST, (1023ull - 150) << 52, 0u, UF);
    ok &= castflags_case(FE_UPWARD, (1023ull - 150) << 52, 1u, UF);
    /* 2^-140 is exactly a fp32 subnormal (2^9 min_subs): silent. */
    ok &= castflags_case(FE_TONEAREST, (1023ull - 140) << 52,
                         1u << 9, 0);
    /* 1 + 2^-40 rounds to 1.0f: inexact alone. */
    ok &= castflags_case(FE_TONEAREST, one64 | (1ull << 12),
                         127u << 23, CFT_FLAG_INEXACT);
    /* sNaN (quiet bit clear, payload set): invalid, NaN out. */
    {
        volatile uint64_t vin = EXPM64 | 1ull;
        uint32_t got;
        int raised;
        feclearexcept(FE_ALL_EXCEPT);
        got = f2u((float)u2d(vin));
        c5_sink32 = got;
        raised = fetestexcept(FE_ALL_EXCEPT);
        ok &= is_nan32(got) && fe_to_cft(raised) == CFT_FLAG_INVALID;
    }
    return ok;
}

/* One batch of n fp64 encodings narrowed to fp32 under attribute mi: the
 * oracle is the (float) cast in the dynamic rounding mode, values compared
 * per lane and flags by the batch OR first, the lane named by n=1 calls
 * only when the OR disagrees. The random mode and conv64to32-class both
 * run exactly this. */
static int conv64to32_batch(int mi, const uint64_t *A, size_t n,
                            int flags_ok)
{
    static uint32_t W[BATCH], D[BATCH];
    uint32_t nf, lf = 0;
    int raised;
    size_t i;

    fesetround(MODES[mi].fe);
    feclearexcept(FE_ALL_EXCEPT);
    for (i = 0; i < n; i++)
        W[i] = f2u((float)u2d(A[i]));
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    nf = fe_to_cft(raised);
    if (cft_convert(dev, CFT_FP64, CFT_FP32, MODES[mi].cr, A, D, n,
                    &lf) != CFT_OK) {
        hard_fail("conv64to32"); return 1;
    }
    sab(D, 4, n);
    for (i = 0; i < n; i++)
        if (!agree32(D[i], W[i]))
            vmis("conv64to32", MODES[mi].name, A[i], 0, 0, D[i], W[i]);
    if (flags_ok && lf != nf) {
        for (i = 0; i < n; i++) {
            uint32_t d1, f1 = 0, w1;
            fesetround(MODES[mi].fe);
            feclearexcept(FE_ALL_EXCEPT);
            c5_sink32 = f2u((float)u2d(A[i]));
            raised = fetestexcept(FE_ALL_EXCEPT);
            fesetround(FE_TONEAREST);
            w1 = fe_to_cft(raised);
            if (cft_convert(dev, CFT_FP64, CFT_FP32, MODES[mi].cr,
                            &A[i], &d1, 1, &f1) != CFT_OK)
                continue;
            if (f1 != w1)
                fmis("conv64to32", MODES[mi].name, A[i], f1, w1);
        }
    }
    cases += n;
    return 0;
}

/* The castflags probe's verdict, applied: the flag comparison degrades to
 * values only, said out loud. The random mode and conv64to32-class say the
 * same words. */
static int conv64to32_gate(void)
{
    int flags_ok = probe_castflags();
    if (!flags_ok)
        printf("castflags probe: flag environment unreliable; "
               "comparing values only\n");
    return flags_ok;
}

static int drv_conv64to32(uint64_t count, int mi)
{
    static uint64_t A[BATCH];
    int flags_ok = conv64to32_gate();
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded64();
        if (conv64to32_batch(mi, A, n, flags_ok))
            return 1;
        count -= n;
    }
    return 0;
}

/* One batch of n fp32 encodings widened to fp64: exact, so the oracle
 * is the cast and the only expected flag is invalid-on-sNaN, derived.
 * The random mode and conv32to64-all both run exactly this. */
static int conv32to64_batch(const uint32_t *A, size_t n)
{
    static uint64_t W[BATCH], D[BATCH];
    size_t i;
    uint32_t lf = 0, ex = 0;
    for (i = 0; i < n; i++) {
        W[i] = d2u((double)u2f(A[i]));
        if (is_snan32(A[i]))
            ex |= CFT_FLAG_INVALID;
    }
    feclearexcept(FE_ALL_EXCEPT);
    if (cft_convert(dev, CFT_FP32, CFT_FP64, CFT_RNE, A, D, n, &lf)
        != CFT_OK) {
        hard_fail("conv32to64"); return 1;
    }
    sab(D, 8, n);
    for (i = 0; i < n; i++)
        if (!agree64(D[i], W[i]))
            vmis("conv32to64", "rne", A[i], 0, 0, D[i], W[i]);
    if (lf != ex) {
        for (i = 0; i < n; i++) {
            uint64_t d1;
            uint32_t f1 = 0, w1;
            if (cft_convert(dev, CFT_FP32, CFT_FP64, CFT_RNE, &A[i],
                            &d1, 1, &f1) != CFT_OK)
                continue;
            w1 = is_snan32(A[i]) ? CFT_FLAG_INVALID : 0;
            if (f1 != w1)
                fmis("conv32to64", "rne", A[i], f1, w1);
        }
    }
    cases += n;
    return 0;
}

static int drv_conv32to64(uint64_t count)
{
    static uint32_t A[BATCH];
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++)
            A[i] = banded32();
        if (conv32to64_batch(A, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * convertToInteger
 *
 * Oracle: llrintf/llrint under the four fenv modes (cvtss2si /
 * cvtsd2si - the mode honour is architectural), llroundf/llround for
 * RMM (ties-away by definition, mode-free), and in RTZ a (long long)
 * cast cross-checks the oracle against itself. IN-RANGE lanes only,
 * per the header's derivation; each surviving lane is checked under
 * exact=0 (which must raise nothing) and exact=1 (inexact iff the
 * oracle's integer differs from the operand's value).
 * ================================================================ */

static const struct { int width; int is_signed; const char *nm; }
TGT[4] = {
    { 32, 1, "cvt_to_i32" }, { 32, 0, "cvt_to_u32" },
    { 64, 1, "cvt_to_i64" }, { 64, 0, "cvt_to_u64" },
};

static cft_status cvtto_call(int ti, cft_format fmt, int mi, int exact,
                             const void *a, void *out, size_t n,
                             uint32_t *fl)
{
    switch (ti) {
    case 0: return cft_cvt_to_i32(dev, fmt, MODES[mi].cr, exact, a,
                                  (int32_t *)out, n, fl);
    case 1: return cft_cvt_to_u32(dev, fmt, MODES[mi].cr, exact, a,
                                  (uint32_t *)out, n, fl);
    case 2: return cft_cvt_to_i64(dev, fmt, MODES[mi].cr, exact, a,
                                  (int64_t *)out, n, fl);
    default: return cft_cvt_to_u64(dev, fmt, MODES[mi].cr, exact, a,
                                   (uint64_t *)out, n, fl);
    }
}

/* A quarter of operands aim at the integer boundaries: powers of two
 * from the significand widths up to 2^64, jittered a few encodings
 * either side, either sign. */
static uint64_t cvtto_operand64(void)
{
    if ((rng() & 3) == 0) {
        static const int ks[9] = { 23, 24, 31, 32, 52, 53, 62, 63, 64 };
        double x = ldexp(1.0, ks[rng() % 9]);
        int j = (int)(rng() % 7) - 3;
        while (j > 0) { x = nextafter(x, INFINITY); j--; }
        while (j < 0) { x = nextafter(x, 0.0); j++; }
        if (rng() & 1) x = -x;
        return d2u(x);
    }
    return banded64();
}

static uint32_t cvtto_operand32(void)
{
    if ((rng() & 3) == 0) {
        static const int ks[9] = { 23, 24, 31, 32, 52, 53, 62, 63, 64 };
        float x = (float)ldexp(1.0, ks[rng() % 9]);
        int j = (int)(rng() % 7) - 3;
        while (j > 0) { x = nextafterf(x, INFINITY); j--; }
        while (j < 0) { x = nextafterf(x, 0.0f); j++; }
        if (rng() & 1) x = -x;
        return f2u(x);
    }
    return banded32();
}

/* One batch of n operands (fp32 or fp64, by is64) against all four
 * integer targets under attribute mi, each in-range lane as exact=0 and
 * exact=1. The random mode and cvtto32-all both run exactly this; the
 * lane-target pairs it leaves out are counted in `skipped`, so for any
 * batch cases + skipped is 4 * n. */
static int cvtto_batch(int is64, int mi, const void *ops, size_t n)
{
    static uint8_t C[BATCH * 8];        /* compacted operands */
    static uint64_t EXPV[BATCH];        /* expected integer bits */
    static uint8_t INX[BATCH];          /* per-lane derived inexact */
    static uint8_t OUT[BATCH * 8];
    const uint64_t *A64 = (const uint64_t *)ops;
    const uint32_t *A32 = (const uint32_t *)ops;
    cft_format fmt = is64 ? CFT_FP64 : CFT_FP32;
    size_t esz = is64 ? 8 : 4;
    size_t i;
    int ti;

    for (ti = 0; ti < 4; ti++) {
        size_t m = 0;
        int exact;
        uint32_t orinx = 0;
        fesetround(MODES[mi].fe);
        for (i = 0; i < n; i++) {
            double xv;
            long long r;
            int hi_half = 0;
            uint64_t bits = is64 ? A64[i] : (uint64_t)A32[i];
            if (is64 ? !is_finite64(A64[i]) : !is_finite32(A32[i])) {
                skipped++;
                continue;
            }
            xv = is64 ? u2d(A64[i]) : (double)u2f(A32[i]);
            if (TGT[ti].is_signed == 0 && TGT[ti].width == 64 &&
                xv >= 0x1p63 && xv < 0x1p64) {
                /* integral by construction: values past 2^53 have
                 * no fraction, so no rounding and no mode */
                EXPV[m] = (uint64_t)xv;
                INX[m] = 0;
                hi_half = 1;
                r = 0;
            } else if (!(xv >= -0x1p63 && xv < 0x1p63)) {
                skipped++;
                continue;
            } else if (mi == 4) {
                r = is64 ? llround(u2d(A64[i]))
                         : llroundf(u2f(A32[i]));
            } else {
                r = is64 ? llrint(u2d(A64[i]))
                         : llrintf(u2f(A32[i]));
                if (mi == 1) {
                    /* the oracle cross-checks itself in RTZ */
                    long long r2 = is64 ? (long long)u2d(A64[i])
                                        : (long long)u2f(A32[i]);
                    if (r2 != r) {
                        printf("  ORACLE llrint vs cast disagree "
                               "a=0x%016llx\n",
                               (unsigned long long)bits);
                        mismatches++;
                    }
                }
            }
            if (!hi_half) {
                if (TGT[ti].width == 32) {
                    if (TGT[ti].is_signed) {
                        if (r < (long long)INT32_MIN ||
                            r > (long long)INT32_MAX) {
                            skipped++;
                            continue;
                        }
                    } else if (r < 0 || r > (long long)UINT32_MAX) {
                        skipped++;
                        continue;
                    }
                } else if (!TGT[ti].is_signed && r < 0) {
                    skipped++;
                    continue;
                }
                EXPV[m] = (uint64_t)r;
                /* (double)r is exact here: |r| < 2^63 and either
                 * |r| <= 2^53 or r equals the already-integral
                 * operand, so the compare is exact. */
                INX[m] = ((double)r != xv);
            }
            if (INX[m])
                orinx = CFT_FLAG_INEXACT;
            memcpy(C + m * esz,
                   is64 ? (void *)&A64[i] : (void *)&A32[i], esz);
            m++;
        }
        fesetround(FE_TONEAREST);
        if (m == 0)
            continue;
        for (exact = 0; exact <= 1; exact++) {
            uint32_t lf = 0, want = exact ? orinx : 0;
            size_t osz = (size_t)TGT[ti].width / 8;
            if (cvtto_call(ti, fmt, mi, exact, C, OUT, m, &lf)
                != CFT_OK) {
                hard_fail(TGT[ti].nm);
                return 1;
            }
            sab(OUT, osz, m);
            for (i = 0; i < m; i++) {
                uint64_t got;
                if (osz == 4) {
                    uint32_t g;
                    memcpy(&g, OUT + i * 4, 4);
                    got = g;
                } else {
                    memcpy(&got, OUT + i * 8, 8);
                }
                if ((osz == 4 ? (got != (EXPV[i] & 0xffffffffull))
                              : (got != EXPV[i]))) {
                    uint64_t inbits;
                    memcpy(&inbits, C + i * esz, esz);
                    if (esz == 4) inbits &= 0xffffffffull;
                    vmis(TGT[ti].nm, MODES[mi].name, inbits, 0, 0,
                         got, osz == 4 ? (EXPV[i] & 0xffffffffull)
                                       : EXPV[i]);
                }
            }
            if (lf != want) {
                for (i = 0; i < m; i++) {
                    uint32_t f1 = 0, w1;
                    uint64_t inbits;
                    memcpy(&inbits, C + i * esz, esz);
                    if (esz == 4) inbits &= 0xffffffffull;
                    if (cvtto_call(ti, fmt, mi, exact, C + i * esz,
                                   OUT, 1, &f1) != CFT_OK)
                        continue;
                    w1 = (exact && INX[i]) ? CFT_FLAG_INEXACT : 0;
                    if (f1 != w1)
                        fmis(TGT[ti].nm, MODES[mi].name, inbits,
                             f1, w1);
                }
            }
        }
        cases += m;
    }
    return 0;
}

static int drv_cvtto(int is64, uint64_t count, int mi)
{
    static uint64_t A64[BATCH];
    static uint32_t A32[BATCH];

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++) {
            if (is64) A64[i] = cvtto_operand64();
            else      A32[i] = cvtto_operand32();
        }
        if (cvtto_batch(is64, mi,
                        is64 ? (const void *)A64 : (const void *)A32, n))
            return 1;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * convertFromInt
 *
 * Oracle: the plain casts. i32/i64/u32 are single cvtsi
 * instructions; u64 is the compiler's round-to-odd halving dance,
 * which is exactly the double-rounding-safe construction - the probe
 * proves both the mode honour and the inexact flag on directed
 * cases before any directed job trusts them. The only contract flag
 * is inexact.
 * ================================================================ */

static int cvtfrom_case64(int fe, uint64_t v, int is_signed,
                          uint64_t want, int want_inexact, int *flags_ok)
{
    volatile uint64_t vv = v;
    uint64_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = is_signed ? d2u((double)(int64_t)vv) : d2u((double)vv);
    c5_sink64 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    if (!!(raised & FE_INEXACT) != want_inexact)
        *flags_ok = 0;
    return got == want;
}

static int cvtfrom_case32(int fe, uint64_t v, int is_signed,
                          uint32_t want, int want_inexact, int *flags_ok)
{
    volatile uint64_t vv = v;
    uint32_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = is_signed ? f2u((float)(int64_t)vv) : f2u((float)vv);
    c5_sink32 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    if (!!(raised & FE_INEXACT) != want_inexact)
        *flags_ok = 0;
    return got == want;
}

static int probe_cvtfrom(int *flags_ok)
{
    int ok = 1, fok = 1;
    /* 2^24+1 halves exactly between 2^24 and 2^24+2 in fp32: RNE to
     * the even (2^24), RUP one ulp higher; and its negation lands on
     * the other side under RDN/RUP. Encodings derived: 2^24 is
     * exponent 24+127 with a zero fraction; one ulp there is fraction
     * bit 0. */
    {
        const uint32_t p24 = (uint32_t)(24 + 127) << 23;
        ok &= cvtfrom_case32(FE_TONEAREST, (1ull << 24) + 1, 1,
                             p24, 1, &fok);
        ok &= cvtfrom_case32(FE_UPWARD, (1ull << 24) + 1, 1,
                             p24 | 1u, 1, &fok);
        ok &= cvtfrom_case32(FE_TOWARDZERO, (1ull << 24) + 1, 1,
                             p24, 1, &fok);
        ok &= cvtfrom_case32(FE_DOWNWARD,
                             (uint64_t)-(int64_t)((1ull << 24) + 1), 1,
                             SIGN32 | p24 | 1u, 1, &fok);
        ok &= cvtfrom_case32(FE_UPWARD,
                             (uint64_t)-(int64_t)((1ull << 24) + 1), 1,
                             SIGN32 | p24, 1, &fok);
        ok &= cvtfrom_case32(FE_TONEAREST, 1ull << 24, 1, p24, 0, &fok);
    }
    /* The u64 top half: 2^63 + 2^10 needs 54 bits, so fp64 rounds at
     * ulp 2^11 - down to 2^63 except under RUP. */
    {
        const uint64_t p63 = (uint64_t)(63 + 1023) << 52;
        ok &= cvtfrom_case64(FE_TONEAREST, (1ull << 63) + (1ull << 10),
                             0, p63, 1, &fok);
        ok &= cvtfrom_case64(FE_UPWARD, (1ull << 63) + (1ull << 10),
                             0, p63 | 1ull, 1, &fok);
        ok &= cvtfrom_case64(FE_TOWARDZERO, (1ull << 63) + (1ull << 10),
                             0, p63, 1, &fok);
        ok &= cvtfrom_case64(FE_TONEAREST, 1ull << 63, 0, p63, 0, &fok);
        /* all-ones u64 rounds to 2^64 except toward zero */
        ok &= cvtfrom_case64(FE_TONEAREST, ~0ull, 0,
                             (uint64_t)(64 + 1023) << 52, 1, &fok);
        ok &= cvtfrom_case64(FE_TOWARDZERO, ~0ull, 0,
                             ((uint64_t)(64 + 1023) << 52) - 1, 1, &fok);
    }
    if (flags_ok)
        *flags_ok = fok;
    return ok;
}

static uint64_t cvtfrom_int(int width)
{
    uint64_t v = rng();
    if ((rng() & 7) == 0) {
        static const int ks[8] = { 23, 24, 31, 32, 52, 53, 62, 63 };
        v = (1ull << ks[rng() % 8]) + (uint64_t)((int64_t)(rng() % 5) - 2);
        /* The negative of v modulo 2^64, in unsigned arithmetic. This was
         * `(uint64_t)-(int64_t)v` from the generator's first commit, which
         * is the same value for every v but overflows a signed negation
         * when v is 2^63 (k = 63, offset 0) - undefined behaviour that
         * UBSan reported on 2026-10-19. No operand changes. */
        if (rng() & 1)
            v = (uint64_t)0 - v;
    }
    if (width == 32)
        v &= 0xffffffffull;
    return v;
}

static const struct { int w; int sg; const char *nm; } SRC[4] = {
    { 32, 1, "cvt_from_i32" }, { 32, 0, "cvt_from_u32" },
    { 64, 1, "cvt_from_i64" }, { 64, 0, "cvt_from_u64" },
};

/* The cvtfrom probe's verdict, applied: 1 when a job may run. The
 * random mode and the exhaustive ones say the same words. */
static int cvtfrom_gate(int mi, int *flags_ok)
{
    int values_ok = probe_cvtfrom(flags_ok);

    if (!values_ok && mi != 0) {
        printf("cvtfrom probe: directed-mode values NOT honoured; "
               "this job is covered by rne + the model matrix\n");
        return 0;                 /* main prints the zero-case line */
    }
    if (!*flags_ok)
        printf("cvtfrom probe: inexact flag unreliable; "
               "comparing values only\n");
    return 1;
}

/* One source type (si indexes SRC: i32, u32, i64, u64) of one batch of
 * n lanes under attribute mi, converted to fp64 when is64 and to fp32
 * otherwise. S32 or S64 holds the source lanes by the source's width;
 * V is each lane as the log prints it. The random mode and
 * cvtfrom32-all / cvtfrom64-all both run exactly this. */
static int cvtfrom_check(int is64, int mi, int si, size_t n, int flags_ok,
                         const uint64_t *V, const uint32_t *S32,
                         const uint64_t *S64)
{
    static uint32_t W32[BATCH], D32[BATCH];
    static uint64_t W64[BATCH], D64[BATCH];
    cft_format fmt = is64 ? CFT_FP64 : CFT_FP32;
    uint32_t nf, lf = 0;
    int raised;
    cft_status st;
    size_t i;

    fesetround(MODES[mi].fe);
    feclearexcept(FE_ALL_EXCEPT);
    for (i = 0; i < n; i++) {
        if (is64) {
            double r;
            if (SRC[si].w == 32)
                r = SRC[si].sg ? (double)(int32_t)S32[i]
                               : (double)S32[i];
            else
                r = SRC[si].sg ? (double)(int64_t)S64[i]
                               : (double)S64[i];
            W64[i] = d2u(r);
        } else {
            float r;
            if (SRC[si].w == 32)
                r = SRC[si].sg ? (float)(int32_t)S32[i]
                               : (float)S32[i];
            else
                r = SRC[si].sg ? (float)(int64_t)S64[i]
                               : (float)S64[i];
            W32[i] = f2u(r);
        }
    }
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    nf = fe_to_cft(raised) & CFT_FLAG_INEXACT;
    switch (si) {
    case 0: st = cft_cvt_from_i32(dev, fmt, MODES[mi].cr,
                (const int32_t *)(const void *)S32,
                is64 ? (void *)D64 : (void *)D32, n, &lf);
        break;
    case 1: st = cft_cvt_from_u32(dev, fmt, MODES[mi].cr, S32,
                is64 ? (void *)D64 : (void *)D32, n, &lf);
        break;
    case 2: st = cft_cvt_from_i64(dev, fmt, MODES[mi].cr,
                (const int64_t *)(const void *)S64,
                is64 ? (void *)D64 : (void *)D32, n, &lf);
        break;
    default: st = cft_cvt_from_u64(dev, fmt, MODES[mi].cr, S64,
                is64 ? (void *)D64 : (void *)D32, n, &lf);
        break;
    }
    if (st != CFT_OK) { hard_fail(SRC[si].nm); return 1; }
    sab(is64 ? (void *)D64 : (void *)D32, is64 ? 8 : 4, n);
    for (i = 0; i < n; i++) {
        if (is64 ? (D64[i] != W64[i]) : (D32[i] != W32[i]))
            vmis(SRC[si].nm, MODES[mi].name, V[i], 0, 0,
                 is64 ? D64[i] : (uint64_t)D32[i],
                 is64 ? W64[i] : (uint64_t)W32[i]);
    }
    if (flags_ok && lf != nf) {
        for (i = 0; i < n; i++) {
            uint32_t f1 = 0, w1;
            fesetround(MODES[mi].fe);
            feclearexcept(FE_ALL_EXCEPT);
            if (is64) {
                double r;
                if (SRC[si].w == 32)
                    r = SRC[si].sg ? (double)(int32_t)S32[i]
                                   : (double)S32[i];
                else
                    r = SRC[si].sg ? (double)(int64_t)S64[i]
                                   : (double)S64[i];
                c5_sink64 = d2u(r);
            } else {
                float r;
                if (SRC[si].w == 32)
                    r = SRC[si].sg ? (float)(int32_t)S32[i]
                                   : (float)S32[i];
                else
                    r = SRC[si].sg ? (float)(int64_t)S64[i]
                                   : (float)S64[i];
                c5_sink32 = f2u(r);
            }
            raised = fetestexcept(FE_ALL_EXCEPT);
            fesetround(FE_TONEAREST);
            w1 = fe_to_cft(raised) & CFT_FLAG_INEXACT;
            switch (si) {
            case 0: st = cft_cvt_from_i32(dev, fmt, MODES[mi].cr,
                        (const int32_t *)(const void *)&S32[i],
                        is64 ? (void *)&D64[i] : (void *)&D32[i],
                        1, &f1);
                break;
            case 1: st = cft_cvt_from_u32(dev, fmt, MODES[mi].cr,
                        &S32[i],
                        is64 ? (void *)&D64[i] : (void *)&D32[i],
                        1, &f1);
                break;
            case 2: st = cft_cvt_from_i64(dev, fmt, MODES[mi].cr,
                        (const int64_t *)(const void *)&S64[i],
                        is64 ? (void *)&D64[i] : (void *)&D32[i],
                        1, &f1);
                break;
            default: st = cft_cvt_from_u64(dev, fmt, MODES[mi].cr,
                        &S64[i],
                        is64 ? (void *)&D64[i] : (void *)&D32[i],
                        1, &f1);
                break;
            }
            if (st != CFT_OK)
                continue;
            if (f1 != w1)
                fmis(SRC[si].nm, MODES[mi].name, V[i], f1, w1);
        }
    }
    cases += n;
    return 0;
}

static int drv_cvtfrom(int is64, uint64_t count, int mi)
{
    static uint64_t V[BATCH];
    static uint32_t S32[BATCH];
    static uint64_t S64[BATCH];
    int flags_ok = 1;

    if (!cvtfrom_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        int si;
        for (si = 0; si < 4; si++) {
            for (i = 0; i < n; i++) {
                V[i] = cvtfrom_int(SRC[si].w);
                if (SRC[si].w == 32)
                    S32[i] = (uint32_t)V[i];
                else
                    S64[i] = V[i];
            }
            if (cvtfrom_check(is64, mi, si, n, flags_ok, V, S32, S64))
                return 1;
        }
        count -= n;
    }
    return 0;
}

/* ================================================================
 * remainder
 *
 * Oracle: remainderf/remainder - mode-independent and exact, like
 * the operation itself. Expected flags derived from operand classes:
 * invalid for sNaN, an infinite dividend, or a zero divisor; nothing
 * for anything else, exactness being the operation's own theorem.
 * A quarter of the pairs are directed at the walk: a top-band
 * dividend against a bottom-band divisor stretches the exponent gap
 * the host walks a bit at a time.
 * ================================================================ */

static uint32_t rem_expect32(uint32_t a, uint32_t b)
{
    if (is_snan32(a) || is_snan32(b))
        return CFT_FLAG_INVALID;
    if (is_nan32(a) || is_nan32(b))
        return 0;
    if (is_inf32(a) || is_zero32(b))
        return CFT_FLAG_INVALID;
    return 0;
}

static uint32_t rem_expect64(uint64_t a, uint64_t b)
{
    if (is_snan64(a) || is_snan64(b))
        return CFT_FLAG_INVALID;
    if (is_nan64(a) || is_nan64(b))
        return 0;
    if (is_inf64(a) || is_zero64(b))
        return CFT_FLAG_INVALID;
    return 0;
}

static void rem_pair32(uint32_t *pa, uint32_t *pb)
{
    if ((rng() & 3) == 0) {
        uint32_t a = (uint32_t)rng(), b = (uint32_t)rng();
        uint32_t eh = 252u + (uint32_t)(rng() % 3);
        uint32_t el = (uint32_t)(rng() % 3);
        *pa = (rng() & 7) == 0 ? ((a & SIGN32) | (EXPM32 - 1))
                               : ((a & 0x807fffffu) | (eh << 23));
        *pb = (rng() & 7) == 0 ? ((b & SIGN32) | 1u)
                               : ((b & 0x807fffffu) | (el << 23));
        return;
    }
    *pa = banded32();
    *pb = banded32();
}

static void rem_pair64(uint64_t *pa, uint64_t *pb)
{
    if ((rng() & 3) == 0) {
        uint64_t a = rng(), b = rng();
        uint64_t eh = 2044ull + (rng() % 3);
        uint64_t el = rng() % 3;
        *pa = (rng() & 7) == 0 ? ((a & SIGN64) | (EXPM64 - 1))
                               : ((a & 0x800fffffffffffffull) | (eh << 52));
        *pb = (rng() & 7) == 0 ? ((b & SIGN64) | 1ull)
                               : ((b & 0x800fffffffffffffull) | (el << 52));
        return;
    }
    *pa = banded64();
    *pb = banded64();
}

static int drv_rem(int is64, uint64_t count)
{
    static uint32_t A32[BATCH], B32[BATCH], W32[BATCH], D32[BATCH];
    static uint64_t A64[BATCH], B64[BATCH], W64[BATCH], D64[BATCH];
    const char *nm = is64 ? "rem64" : "rem32";
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        uint32_t lf = 0, ex = 0;
        cft_status st;
        for (i = 0; i < n; i++) {
            if (is64) {
                rem_pair64(&A64[i], &B64[i]);
                W64[i] = d2u(remainder(u2d(A64[i]), u2d(B64[i])));
                ex |= rem_expect64(A64[i], B64[i]);
            } else {
                rem_pair32(&A32[i], &B32[i]);
                W32[i] = f2u(remainderf(u2f(A32[i]), u2f(B32[i])));
                ex |= rem_expect32(A32[i], B32[i]);
            }
        }
        feclearexcept(FE_ALL_EXCEPT);
        st = is64
            ? cft_rem(dev, CFT_FP64, A64, B64, D64, n, &lf)
            : cft_rem(dev, CFT_FP32, A32, B32, D32, n, &lf);
        if (st != CFT_OK) { hard_fail(nm); return 1; }
        sab(is64 ? (void *)D64 : (void *)D32, is64 ? 8 : 4, n);
        for (i = 0; i < n; i++) {
            if (is64 ? !agree64(D64[i], W64[i]) : !agree32(D32[i], W32[i]))
                vmis(nm, "-", is64 ? A64[i] : (uint64_t)A32[i], 1,
                     is64 ? B64[i] : (uint64_t)B32[i],
                     is64 ? D64[i] : (uint64_t)D32[i],
                     is64 ? W64[i] : (uint64_t)W32[i]);
        }
        if (lf != ex) {
            for (i = 0; i < n; i++) {
                uint32_t f1 = 0, w1;
                uint64_t d1;
                st = is64
                    ? cft_rem(dev, CFT_FP64, &A64[i], &B64[i], &d1, 1, &f1)
                    : cft_rem(dev, CFT_FP32, &A32[i], &B32[i], &D32[i],
                              1, &f1);
                if (st != CFT_OK)
                    continue;
                w1 = is64 ? rem_expect64(A64[i], B64[i])
                          : rem_expect32(A32[i], B32[i]);
                if (f1 != w1)
                    fmis(nm, "-", is64 ? A64[i] : (uint64_t)A32[i],
                         f1, w1);
            }
        }
        cases += n;
        count -= n;
    }
    return 0;
}

/* ================================================================
 * Exhaustive modes: every encoding of a 32-bit operand
 *
 * conv32to64-all, cvtto32-all, cvtfrom32-all, cvtfrom64-all,
 * scaleb32-all and scaleb32-wide take <lo> <hi> over the operand's 2^32
 * encodings, the way rint32 and its neighbours do. They call the SAME
 * batch kernels as the random mode of the operation (conv32to64_batch,
 * cvtto_batch, cvtfrom_check, scaleb_batch, with the same probe
 * gates), so the oracle, the flag discipline, the probes and the
 * sabotage are the random mode's by construction; only the operand
 * source differs. A job word ending -all or -wide is how a log says
 * which one ran.
 *
 * Coverage. A count of checks alone cannot show a slice ran whole:
 * cvtto32-all skips the lane-target pairs whose rounded value leaves
 * the target's range, so its checks depend on the operands. These modes
 * therefore count the operand encodings they ran, in the batch loop,
 * and their verdict line says it: "..., E encodings, S skipped". Every
 * (encoding, check) pair is either compared, and counted in cases, or
 * skipped, so cases + skipped is k * encodings with k fixed by the
 * mode - 1, 4, 2, 2, 17 and 568 for the six, in the order above - and
 * hw/card_stress_lib.py holds the line to both.
 * ================================================================ */

/* [lo, hi) must be a non-empty part of the 2^32 encodings. The loops
 * below cast the running value to the operand's 32 bits, so a range
 * past 2^32 would quietly wrap and run encodings twice: it is refused
 * by name instead, as is anything that is not a whole number. */
static int exh_range(const char *slo, const char *shi, uint64_t *lo,
                     uint64_t *hi)
{
    char *e1, *e2;
    *lo = strtoull(slo, &e1, 0);
    *hi = strtoull(shi, &e2, 0);
    if (!*slo || !*shi || *e1 || *e2 || *lo >= *hi ||
        *hi > 0x100000000ull) {
        fprintf(stderr, "need 0 <= lo < hi <= 2^32 (the encodings of a "
                "32-bit operand), got [%s, %s)\n", slo, shi);
        return 1;
    }
    return 0;
}

static int drv_conv32to64_all(uint64_t lo, uint64_t hi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (conv32to64_batch(A, n))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

static int drv_cvtto32_all(uint64_t lo, uint64_t hi, int mi)
{
    static uint32_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (cvtto_batch(0, mi, A, n))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

/* Every 32-bit integer as an i32 source and as a u32 source, converted
 * to fp32 (is64 = 0) or to fp64. The i64 and u64 sources of the random
 * mode have 2^64 values and are not part of this one. */
static int drv_cvtfrom_all(int is64, uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t V[BATCH];
    static uint32_t S32[BATCH];
    int flags_ok = 1;
    uint64_t v = lo;

    if (!cvtfrom_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        int si;
        for (i = 0; i < n; i++) {
            S32[i] = (uint32_t)(v + i);
            V[i] = S32[i];
        }
        for (si = 0; si < 2; si++)              /* i32, then u32 */
            if (cvtfrom_check(is64, mi, si, n, flags_ok, V, S32, NULL))
                return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

static int drv_scaleb32_all(uint64_t lo, uint64_t hi, int mi)
{
    static uint32_t A[BATCH];
    int flags_ok = 1;
    uint64_t v = lo;

    if (!scaleb_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (scaleb_batch(0, mi, A, n, SCALEB_N32, NULL,
                         sizeof(SCALEB_N32) / sizeof(SCALEB_N32[0]),
                         flags_ok, "scaleb32"))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

/* ----------------------------------------------------------------
 * scaleb32-wide: every exponent that can change a result
 *
 * A finite nonzero fp32 operand x has 2^-149 <= |x| < 2^128 (the
 * smallest subnormal, and the largest finite value's ceiling), so x *
 * 2^n has two edges.
 *
 *   High. n = 277 is the first exponent that overflows EVERY nonzero
 *   finite operand: 2^-149 * 2^277 = 2^128 is already out of range, and
 *   at n = 276 the same operand gives 2^127, finite. From 277 on, a
 *   nonzero finite operand's result is the overflow landing of its sign
 *   and the attribute (infinity, or max_normal), whatever n is.
 *
 *   Low. n = -278 is the first exponent that puts EVERY finite operand
 *   strictly below half the smallest subnormal: |x| * 2^-278 < 2^128 *
 *   2^-278 = 2^-150. Rne then gives a signed zero, and rtz, rdn and
 *   rup give what the attribute gives any value in (0, 2^-149): zero or
 *   min_subnormal, by sign. At n = -277 rne does not saturate (1.5 *
 *   2^127 * 2^-277 = 0.75 * 2^-149 rounds to min_subnormal, where -278
 *   gives zero); the three directed attributes already saturate there,
 *   and are last changed at -276 (1.5 * 2^127 * 2^-276 = 1.5 *
 *   2^-149 is 2 * 2^-149 under rup).
 *
 * Zero, infinity and NaN operands do not depend on n. So the exponents
 * that can change a result are -277..276, and the range - those plus
 * one saturated exponent on each side to stand for everything beyond
 * it - is [-278, 277]: 556 exponents. `probe scalebrange` measures the
 * edges on the host's libm; the exponents past them are CHECKED, not
 * assumed, on every operand of every slice: BEYOND lists twelve, six
 * on each side, among them the library's own clamps (-556, 381) and
 * the extremes of an int and of an int64_t, and each is compared with
 * the oracle at the edge it must equal (scaleb_batch's `orc`). A range
 * too narrow by one would show there as a disagreement, named
 * "scaleb32-beyond".
 * ---------------------------------------------------------------- */

#define WIDE_LO (-278)
#define WIDE_HI 277
#define WIDE_N (WIDE_HI - WIDE_LO + 1)

static const int64_t BEYOND[] = {
    -279, -556, -557, -100000, -2147483647, INT64_MIN,
    278, 381, 382, 100000, 2147483647, INT64_MAX
};
#define BEYOND_N (sizeof(BEYOND) / sizeof(BEYOND[0]))

static int drv_scaleb32_wide(uint64_t lo, uint64_t hi, int mi)
{
    static uint32_t A[BATCH];
    static int64_t list[WIDE_N], orc[BEYOND_N];
    int flags_ok = 1;
    uint64_t v = lo;
    size_t k;

    if (!scaleb_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */
    for (k = 0; k < WIDE_N; k++)
        list[k] = WIDE_LO + (int64_t)k;
    for (k = 0; k < BEYOND_N; k++)
        orc[k] = BEYOND[k] < 0 ? WIDE_LO : WIDE_HI;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = (uint32_t)(v + i);
        if (scaleb_batch(0, mi, A, n, list, NULL, WIDE_N, flags_ok,
                         "scaleb32") ||
            scaleb_batch(0, mi, A, n, BEYOND, orc, BEYOND_N, flags_ok,
                         "scaleb32-beyond"))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

/* The wide range, measured on the host's libm alone (no device is
 * opened). For each attribute and a fixed operand set - the directed
 * values below with both signs, and 8192 banded ones - it finds the
 * lowest exponent from -300 whose result differs from the one at -300,
 * and the highest up to 300 whose result differs from the one at 300:
 * the range must be exactly one exponent outside the widest of those,
 * and every exponent past either edge, including an int's extremes,
 * must land as the edge does, values and flags both. */
static uint32_t range_oracle(int fe, uint32_t x, int nn, uint32_t *fl)
{
    volatile uint32_t vx = x;
    uint32_t got;
    int raised;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    got = f2u(scalbnf(u2f(vx), nn));
    c5_sink32 = got;
    raised = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    *fl = fe_to_cft(raised);
    return got;
}

static int range_same(int fe, uint32_t x, int n1, int n2)
{
    uint32_t f1, f2;
    uint32_t v1 = range_oracle(fe, x, n1, &f1);
    uint32_t v2 = range_oracle(fe, x, n2, &f2);
    return agree32(v1, v2) && f1 == f2;
}

static int probe_scalebrange(void)
{
    enum { ND = 14, NB = 8192, NS = 2 * ND + NB };
    static const uint32_t directed[ND] = {
        0x00000000u, 0x00000001u, 0x00000002u, 0x007fffffu, 0x00800000u,
        0x3f800000u, 0x3fc00000u, 0x3f800001u, 0x7f000000u, 0x7f400000u,
        0x7f7fffffu, 0x7f800000u, 0x7fc00000u, 0x7f800001u
    };
    static const int below[] = { -279, -280, -400, -556, -557, -100000,
                                 -2147483647, INT32_MIN };
    static const int above[] = { 278, 279, 300, 381, 382, 100000,
                                 2000000000, INT32_MAX };
    static uint32_t S[NS];
    int first[4], last[4];
    int at, k, n, holds = 1, lo_edge = 0, hi_edge = 0;
    size_t i;

    for (i = 0; i < ND; i++) {
        S[2 * i] = directed[i];
        S[2 * i + 1] = directed[i] | SIGN32;
    }
    rng_state = 0xC5A1E0005ull;
    for (i = 0; i < NB; i++)
        S[2 * ND + i] = banded32();

    for (at = 0; at < 4; at++) {
        int fe = MODES[at].fe;
        int sat_ok = 1;
        for (i = 0; i < NS; i++) {
            for (k = 0; k < (int)(sizeof(below) / sizeof(below[0])); k++)
                if (!range_same(fe, S[i], below[k], WIDE_LO))
                    sat_ok = 0;
            for (k = 0; k < (int)(sizeof(above) / sizeof(above[0])); k++)
                if (!range_same(fe, S[i], above[k], WIDE_HI))
                    sat_ok = 0;
        }
        first[at] = last[at] = 0;
        for (n = -300; n <= -250 && !first[at]; n++)
            for (i = 0; i < NS; i++)
                if (!range_same(fe, S[i], n, -300)) {
                    first[at] = n;
                    break;
                }
        for (n = 300; n >= 250 && !last[at]; n--)
            for (i = 0; i < NS; i++)
                if (!range_same(fe, S[i], n, 300)) {
                    last[at] = n;
                    break;
                }
        if (!sat_ok) {
            printf("probe scalebrange: %s: an exponent past an edge does "
                   "NOT land as the edge does\n", MODES[at].name);
            holds = 0;
        }
        if (!lo_edge || first[at] < lo_edge)
            lo_edge = first[at];
        if (!hi_edge || last[at] > hi_edge)
            hi_edge = last[at];
    }
    printf("probe scalebrange: lowest exponent that changes a result: "
           "rne %d, rtz %d, rdn %d, rup %d; highest: rne %d, rtz %d, "
           "rdn %d, rup %d\n", first[0], first[1], first[2], first[3],
           last[0], last[1], last[2], last[3]);
    if (lo_edge - 1 != WIDE_LO || hi_edge + 1 != WIDE_HI)
        holds = 0;
    printf("probe scalebrange: range [%d, %d] is one exponent outside "
           "[%d, %d]: %s; %d operands, %d exponents past each edge, "
           "every attribute, values and flags\n", WIDE_LO, WIDE_HI,
           lo_edge, hi_edge, holds ? "HOLDS" : "DOES NOT HOLD", NS,
           (int)(sizeof(below) / sizeof(below[0])));
    return holds;
}

/* ================================================================
 * Class-level (L2) modes: the 64-bit rounding operations by classes
 *
 * A 64-bit operand has 2^64 encodings and no sweep reaches them; what a
 * sweep CAN reach is every CLASS of operand, under the structure
 * docs/studies/SWP-A-coverage.md section 4.3 assumes of the rounding
 * unit: it depends on the dropped bits only through guard and a sticky
 * tree, on the kept bits only through the lsb and the carry, and on the
 * exponent only through a rebias and range checks. conv64to32-class,
 * rint64-class, cvtto64-class, cvtfrom64-class and scaleb64-class take
 * <lo> <hi> over the INDEX SPACE of the operation, one index an operand
 * (an operand-exponent pair for scaleB), and call the SAME batch kernels
 * as the random mode of the operation (conv64to32_batch, rint_batch64,
 * cvtto_batch, cvtfrom_check, scaleb_batch, behind the same probe
 * gates), so the oracle, the flag discipline and the sabotage are the
 * random mode's; only the operand source differs. The verdict line is
 * the exhaustive modes': ", E encodings, S skipped", E counting INDICES
 * here, and cases + S is k * E with k fixed by the mode (1, 4, 4, 1, 4 for
 * the five in the order below: a case a lane for the two tile modes, a case
 * a target for cvtto64-class). Skipped is zero except in cvtto64-class,
 * which compares in-range lanes only, as cvtto32-all does.
 *
 * THE CLAIM IS AT THE CLASS LEVEL (L2) AND IS PLAUSIBLE: a pass says the
 * library agrees with the host FPU on a representative of every class
 * and a walking one over the dropped and kept bits, not that the unit
 * has the structure. The index maps are python/c5_class_enum.py's, which
 * is the reference; `dump` prints this file's side of them for a diff:
 *
 *   index = ((position * 2 + sign) * 4 + class) * (4 + W) + pattern
 *
 * position: the exponents at which the rounding position or the range
 * class changes, then the witnesses (the walking ones and zeros of the
 * biased exponent field, and the subnormals); sign; class of the dropped
 * bits (0 zero, 1 below half, 2 half, 3 above half); pattern t < 4 the
 * kept lsb and whether the bits above it are all ones, t >= 4 a walking
 * one at fraction bit t - 4. cvtfrom64-class is cells of (source type,
 * bit length) and scaleb64-class cells of (route, strip); see
 * python/c5_class_enum.py for both and for the counts.
 * ================================================================ */

enum { CLS_CONV, CLS_RINT, CLS_CVTTO, CLS_CVTFROM, CLS_SCALEB, CLS_NJOB };

static const struct { const char *job; int rmm; } CLASS_JOBS[CLS_NJOB] = {
    { "conv64to32-class", 0 }, { "rint64-class", 1 },
    { "cvtto64-class", 1 }, { "cvtfrom64-class", 0 },
    { "scaleb64-class", 0 },
};

#define CLS_NCLS 4
#define CLS_W 52                        /* fraction bits of an fp64 operand */
#define CLS_NPAT (4 + CLS_W)            /* 4 kept patterns + a walking one a bit */
#define CLS_CELL (2 * CLS_NCLS * CLS_NPAT)   /* a position: sign x class x pattern */
#define CLS_NWIT 23                     /* exponent witnesses: 2 * 11 + 1 */
#define CLS_NPAT_FROM (4 + 63)          /* cvtfrom: a walking one per magnitude bit */
#define CLS_NCELL_FROM (63 + 63 + 64)   /* i64+ L=1..63, i64- L=1..63, u64 L=1..64 */
#define CLS_NSPECIAL_FROM 3             /* -2^63, 0 as i64, 0 as u64 */
#define CLS_NSTRIP 54                   /* scaleb strips: p + 1 */
#define CLS_STRIPIDX (3 * CLS_NSTRIP * CLS_CELL)   /* 3 routes */
#define CLS_BLOCK 36                    /* 2 signs x 3 operands x 6 exponents */

/* The structural exponents of the three floating-point operations: the
 * first and last exponent at which a rounding position or a range class
 * changes, with one saturated exponent beyond each end. */
static const int CLS_LO_E[3] = { -152, -3, -3 };
static const int CLS_HI_E[3] = { 128, 53, 64 };

static uint64_t cls_mask(int n)
{
    return n <= 0 ? 0 : (n >= 64 ? ~0ull : (1ull << n) - 1);
}

/* The P-bit significand (top bit set) whose low d bits the rounding
 * drops, of class c and pattern t: python/c5_class_enum.py `sig`. */
static uint64_t cls_sig(int P, int d, int c, int t)
{
    uint64_t K, D = 0, walk = 0, half;
    int k;

    if (d > P + 1)
        d = P + 1;
    k = P - d;
    if (t >= 4) {
        walk = 1ull << (t - 4);
        K = k >= 1 ? 1ull << (k - 1) : 0;
    } else if (k <= 0) {
        K = 0;
    } else if (k == 1) {
        K = 1;
    } else {
        K = ((t >> 1) ? cls_mask(k) - 1 : 1ull << (k - 1)) |
            (uint64_t)(t & 1);
    }
    if (d >= 1) {
        half = (d - 1) < 64 ? 1ull << (d - 1) : 0;
        D = c == 0 ? 0 : (c == 1 ? 1 : (c == 2 ? half : (half | 1)));
    }
    return ((d < 64 ? K << d : 0) | D | walk | (1ull << (P - 1))) &
           cls_mask(P);
}

/* The biased exponent field of witness j: 2^j, then the all-ones field
 * with bit j cleared, then 0 (the subnormals). */
static int cls_witness(int j)
{
    if (j < 11)
        return 1 << j;
    if (j < 22)
        return 2047 ^ (1 << (j - 11));
    return 0;
}

static int cls_nstruct(int job) { return CLS_HI_E[job] - CLS_LO_E[job] + 1; }

/* Indices of the operation `job`'s space. */
static uint64_t cls_size(int job)
{
    switch (job) {
    case CLS_CONV: case CLS_RINT: case CLS_CVTTO:
        return (uint64_t)(cls_nstruct(job) + CLS_NWIT) * CLS_CELL;
    case CLS_CVTFROM:
        return (uint64_t)CLS_NCELL_FROM * CLS_NCLS * CLS_NPAT_FROM +
               CLS_NSPECIAL_FROM;
    default:
        return (uint64_t)CLS_STRIPIDX + 2 * CLS_BLOCK;
    }
}

/* The fp64 operand of index i of conv64to32, rint64 or cvtto64. */
static uint64_t cls_round_operand(int job, uint64_t i)
{
    int t = (int)(i % CLS_NPAT), c, sign, e, b, d;
    uint64_t pi;

    i /= CLS_NPAT;
    c = (int)(i % CLS_NCLS);
    i /= CLS_NCLS;
    sign = (int)(i % 2);
    pi = i / 2;
    if (pi < (uint64_t)cls_nstruct(job)) {
        e = CLS_LO_E[job] + (int)pi;
        b = e + 1023;
    } else {
        b = cls_witness((int)(pi - (uint64_t)cls_nstruct(job)));
        e = b - 1023;
    }
    if (b == 0)
        d = CLS_W + 2;                  /* the subnormals: P + 1 */
    else if (job == CLS_CONV)
        d = 29 + (e < -126 ? -126 - e : 0);
    else
        d = e < CLS_W ? CLS_W - e : 0;
    return ((uint64_t)sign << 63) | ((uint64_t)b << 52) |
           (cls_sig(CLS_W + 1, d, c, t) & cls_mask(CLS_W));
}

/* The 64-bit source of index i of cvtfrom64: its bit pattern, and whether
 * it is a u64 (else an i64). */
static void cls_cvtfrom_operand(uint64_t i, uint64_t *v, int *is_u64)
{
    const uint64_t base = (uint64_t)CLS_NCELL_FROM * CLS_NCLS * CLS_NPAT_FROM;

    if (i >= base) {
        *is_u64 = (i - base) == 2;
        *v = (i - base) == 0 ? 1ull << 63 : 0;
        return;
    }
    {
        int t = (int)(i % CLS_NPAT_FROM);
        int c = (int)((i / CLS_NPAT_FROM) % CLS_NCLS);
        int ci = (int)(i / ((uint64_t)CLS_NPAT_FROM * CLS_NCLS));
        int sv, L;
        uint64_t m;
        if (ci < 63)       { sv = 0; L = ci + 1; }
        else if (ci < 126) { sv = 1; L = ci - 63 + 1; }
        else               { sv = 2; L = ci - 126 + 1; }
        m = cls_sig(L, L > 53 ? L - 53 : 0, c, t);
        *v = sv == 1 ? (uint64_t)0 - m : m;
        *is_u64 = sv == 2;
    }
}

/* The (operand, exponent) pair of index i of scaleb64: the strips, then
 * the overflow block, then the block deeper than the last strip. */
static void cls_scaleb_operand(uint64_t i, uint64_t *a, int64_t *nx)
{
    if (i < (uint64_t)CLS_STRIPIDX) {
        int t = (int)(i % CLS_NPAT), c, sign, route, s;
        uint64_t pi;
        i /= CLS_NPAT;
        c = (int)(i % CLS_NCLS);
        i /= CLS_NCLS;
        sign = (int)(i % 2);
        pi = i / 2;
        route = (int)(pi / CLS_NSTRIP);
        s = (int)(pi % CLS_NSTRIP) + 1;
        if (route == 0) {
            *a = ((uint64_t)sign << 63) | (1023ull << 52) |
                 (cls_sig(53, s, c, t) & cls_mask(52));
            *nx = -1022 - s;
        } else if (route == 1) {
            *a = ((uint64_t)sign << 63) | (2046ull << 52) |
                 (cls_sig(53, s, c, t) & cls_mask(52));
            *nx = -1022 - s - 1023;
        } else {
            *a = ((uint64_t)sign << 63) | (cls_sig(52, s - 1, c, t) & cls_mask(52));
            *nx = 1 - s;
        }
    } else {
        int j = (int)(i - CLS_STRIPIDX), deep = j >= CLS_BLOCK, sign, oi, li;
        uint64_t b, frac;
        int64_t ex;
        j %= CLS_BLOCK;
        sign = j / 18;
        j %= 18;
        oi = j / 6;
        li = j % 6;
        if (oi == 0)      { b = 1023; frac = 0; ex = 0; }
        else if (oi == 1) { b = 2046; frac = cls_mask(52); ex = 1023; }
        else              { b = 0; frac = 1; ex = -1074; }
        *a = ((uint64_t)sign << 63) | (b << 52) | frac;
        if (!deep) {
            int64_t nf = 1023 + 1 - ex;
            const int64_t l[6] = { nf, nf + 1, 3 * 1023, 3 * 1023 + 1, 100000,
                                   INT64_MAX };
            *nx = l[li];
        } else {
            int64_t nl = -1022 - 53 - 2 - ex;
            const int64_t l[6] = { nl, nl - 1, -(4 * 1023 + 2 * 53),
                                   -(4 * 1023 + 2 * 53) - 1, -100000,
                                   INT64_MIN };
            *nx = l[li];
        }
    }
}

static int class_job(const char *job)
{
    int j;
    for (j = 0; j < CLS_NJOB; j++)
        if (!strcmp(job, CLASS_JOBS[j].job))
            return j;
    return -1;
}

/* [lo, hi) must be a non-empty part of the operation's index space. The
 * drivers index the space with the running value, so a range past it
 * would read operands that do not exist: refused by name, as is anything
 * that is not a whole number. */
static int class_range(int job, const char *slo, const char *shi,
                       uint64_t *lo, uint64_t *hi)
{
    char *e1, *e2;
    *lo = strtoull(slo, &e1, 0);
    *hi = strtoull(shi, &e2, 0);
    if (!*slo || !*shi || *e1 || *e2 || *lo >= *hi || *hi > cls_size(job)) {
        fprintf(stderr, "need 0 <= lo < hi <= %llu (the indices of the %s "
                "space), got [%s, %s)\n",
                (unsigned long long)cls_size(job), CLASS_JOBS[job].job,
                slo, shi);
        return 1;
    }
    return 0;
}

/* HOW A CLASS CASE IS RUN. A class case is a deliberate operand, so it is run
 * ALONE: CLS_BATCH operands a kernel call, 1 by default. The kernels compare
 * values per lane but flags by the OR over a call, and only where the ORs
 * disagree do they look at a lane by itself, so a flag a defect drops on one
 * operand among others that raise it goes unseen in a batch (MEASURED, a
 * library that drops INEXACT for the one operand whose dropped bits are 0...01:
 * the whole conv64to32-class space passes in batches and one index of it fails
 * alone). A call of one operand makes every flag the operand's own.
 *
 * The TILE modes (rint64-class, scaleb64-class) have a second axis. A tile's
 * fp64 array is CLS_LANES lanes wide and an element goes to lane (its place in
 * the pass) mod CLS_LANES, so an operand always run first in a call would
 * only ever meet lane 0, and one run in a long batch would meet the one lane
 * its index gives it. Each operand is therefore run once in each lane, behind
 * 0 to CLS_LANES - 1 benign operands (1.0 for rint, +0 for scaleB: exact, no
 * flags, answered correctly by the oracle and the library alike, and not
 * counted as cases), which also keeps its flags the only ones in the call.
 * The cost of both is calls, not cases: k is CLS_LANES for these two modes,
 * and a call on a device is dominated by its passes, so a whole space takes
 * minutes on a tile where the software backend takes seconds. Build with
 * -DCLS_BATCH=4092 for batches (fast, flags per batch, lanes still rotated),
 * -DCLS_LANES=1 for no rotation, -DCLS_LANES=<n> for a tile of n lanes. */

#ifndef CLS_BATCH
#define CLS_BATCH 1
#endif
#ifndef CLS_LANES
#define CLS_LANES 4                     /* fp64 lanes of a tile (docs/ARCHITECTURE.md) */
#endif
#if CLS_BATCH < 1 || CLS_LANES < 1 || CLS_BATCH + CLS_LANES - 1 > BATCH
#error "CLS_BATCH and CLS_LANES must leave room for the benign operands in front of a call"
#endif
#define CLS_ONE64 0x3ff0000000000000ull /* 1.0, the benign operand of rint */

static int drv_class_conv(uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t A[BATCH];
    int flags_ok = conv64to32_gate();
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > CLS_BATCH ? CLS_BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = cls_round_operand(CLS_CONV, v + i);
        if (conv64to32_batch(mi, A, n, flags_ok))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

/* rint64: a tile mode. Each operand runs in each lane behind 1.0s. */
static int drv_class_rint(uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > CLS_BATCH ? CLS_BATCH : (size_t)(hi - v), i;
        int ln;
        for (ln = 0; ln < CLS_LANES; ln++) {
            for (i = 0; i < (size_t)ln; i++)
                A[i] = CLS_ONE64;
            for (i = 0; i < n; i++)
                A[(size_t)ln + i] = cls_round_operand(CLS_RINT, v + i);
            if (rint_batch64(mi, A, n + (size_t)ln))
                return 1;
            cases -= (uint64_t)ln;             /* the 1.0s are not cases */
        }
        encodings += n;
        v += n;
    }
    return 0;
}

static int drv_class_cvtto(uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t A[BATCH];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > CLS_BATCH ? CLS_BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            A[i] = cls_round_operand(CLS_CVTTO, v + i);
        if (cvtto_batch(1, mi, A, n))
            return 1;
        encodings += n;
        v += n;
    }
    return 0;
}

/* The sources run as i64 or u64 by runs of one type: a call is cut where
 * the type changes. */
static int drv_class_cvtfrom(uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t V[BATCH], S64[BATCH];
    static int U[BATCH];
    int flags_ok = 1;
    uint64_t v = lo;

    if (!cvtfrom_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */
    while (v < hi) {
        size_t n = hi - v > CLS_BATCH ? CLS_BATCH : (size_t)(hi - v), i, j;
        for (i = 0; i < n; i++) {
            cls_cvtfrom_operand(v + i, &S64[i], &U[i]);
            V[i] = S64[i];
        }
        for (i = 0; i < n; i = j) {
            for (j = i + 1; j < n && U[j] == U[i]; j++)
                ;
            if (cvtfrom_check(1, mi, U[i] ? 3 : 2, j - i, flags_ok,
                              V + i, NULL, S64 + i))
                return 1;
        }
        encodings += n;
        v += n;
    }
    return 0;
}

/* scaleb64: a tile mode. The operands of a run of one exponent are one
 * scaleb_batch call per lane, behind +0s. The library takes an int64_t
 * exponent and the oracle's scalbn an int, so the oracle is asked for the
 * exponent clamped to int's range: past 2098 and below -2099 every nonzero
 * finite fp64 operand overflows or falls under half the smallest subnormal, so
 * x * 2^INT64_MAX and x * 2^INT32_MAX have the same correctly rounded value
 * (the blocks' last exponents are 2^63 - 1 and -2^63, and without the clamp
 * the cast to int would be -1 and 0). */
static int drv_class_scaleb(uint64_t lo, uint64_t hi, int mi)
{
    static uint64_t A[BATCH], B[BATCH];
    static int64_t NX[BATCH];
    int flags_ok = 1;
    uint64_t v = lo;

    if (!scaleb_gate(mi, &flags_ok))
        return 0;                 /* main prints the zero-case line */
    while (v < hi) {
        size_t n = hi - v > CLS_BATCH ? CLS_BATCH : (size_t)(hi - v), i, j;
        for (i = 0; i < n; i++)
            cls_scaleb_operand(v + i, &A[i], &NX[i]);
        for (i = 0; i < n; i = j) {
            int64_t oc = NX[i] > INT32_MAX ? INT32_MAX
                       : (NX[i] < INT32_MIN ? INT32_MIN : NX[i]);
            int ln;
            for (j = i + 1; j < n && NX[j] == NX[i]; j++)
                ;
            for (ln = 0; ln < CLS_LANES; ln++) {
                size_t q;
                for (q = 0; q < (size_t)ln; q++)
                    B[q] = 0;                  /* +0 rides the multiply, no flags */
                memcpy(B + ln, A + i, (j - i) * sizeof B[0]);
                if (scaleb_batch(1, mi, B, (j - i) + (size_t)ln, &NX[i], &oc, 1,
                                 flags_ok, "scaleb64"))
                    return 1;
                cases -= (uint64_t)ln;         /* the +0s are not cases */
            }
        }
        encodings += n;
        v += n;
    }
    return 0;
}

/* `dump <job> size` prints the size of the job's index space; `dump <job>
 * <lo> <hi>` prints one line a index: the index, the operand as 16 hex
 * digits, and for cvtfrom64-class the source type, for scaleb64-class the
 * exponent. No device is opened. python/c5_class_enum.py --dump prints the
 * same lines from its side, and the test diffs them. */
static int class_dump(int argc, char **argv)
{
    int job = argc >= 4 ? class_job(argv[2]) : -1;
    uint64_t lo, hi, i;

    if (job < 0)
        return 2;
    if (argc == 4 && !strcmp(argv[3], "size")) {
        printf("%llu\n", (unsigned long long)cls_size(job));
        return 0;
    }
    if (argc != 5 || class_range(job, argv[3], argv[4], &lo, &hi))
        return 2;
    for (i = lo; i < hi; i++) {
        uint64_t a;
        int64_t nx;
        int u;
        if (job == CLS_CVTFROM) {
            cls_cvtfrom_operand(i, &a, &u);
            printf("%llu 0x%016llx %s\n", (unsigned long long)i,
                   (unsigned long long)a, u ? "u64" : "i64");
        } else if (job == CLS_SCALEB) {
            cls_scaleb_operand(i, &a, &nx);
            printf("%llu 0x%016llx %lld\n", (unsigned long long)i,
                   (unsigned long long)a, (long long)nx);
        } else {
            printf("%llu 0x%016llx\n", (unsigned long long)i,
                   (unsigned long long)cls_round_operand(job, i));
        }
    }
    return 0;
}

/* ---- main --------------------------------------------------------- */

static void usage(const char *argv0)
{
    fprintf(stderr,
        "usage: %s rint32 <lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
        "       %s nextup32|nextdown32|logb32|class32 <lo> <hi>\n"
        "       %s rint64|cvtto32|cvtto64 <count> <seed> <mode+rmm>\n"
        "       %s scaleb32|scaleb64|conv64to32|cvtfrom32|cvtfrom64 "
        "<count> <seed> <rne|rtz|rdn|rup>\n"
        "       %s conv32to64|rem32|rem64|nextup64|nextdown64|logb64|"
        "class64 <count> <seed>\n"
        "       %s conv32to64-all <lo> <hi>\n"
        "       %s cvtto32-all <lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
        "       %s cvtfrom32-all|cvtfrom64-all|scaleb32-all|scaleb32-wide "
        "<lo> <hi> <rne|rtz|rdn|rup>\n"
        "       %s conv64to32-class|cvtfrom64-class|scaleb64-class "
        "<lo> <hi> <rne|rtz|rdn|rup>\n"
        "       %s rint64-class|cvtto64-class <lo> <hi> <mode+rmm>\n"
        "       %s dump <job>-class size | <lo> <hi>\n"
        "       %s probe scalbn|castflags|cvtfrom|scalebrange\n",
        argv0, argv0, argv0, argv0, argv0, argv0, argv0, argv0, argv0,
        argv0, argv0, argv0);
}

int main(int argc, char **argv)
{
    const char *job, *modename = "-";
    int mi = 0, rc = 1;
    uint64_t p1 = 0, p2 = 0;

    if (argc < 3) {
        usage(argv[0]);
        return 2;
    }
    job = argv[1];

    if (!strcmp(job, "probe")) {
        int fok = 1, vok;
        if (!strcmp(argv[2], "scalbn")) {
            vok = probe_scalbn(&fok);
            printf("probe scalbn: directed-mode values %s\n",
                   vok ? "HONOURED" : "NOT honoured");
            printf("probe scalbn: flag environment %s\n",
                   fok ? "RELIABLE" : "UNRELIABLE");
            return vok ? 0 : 1;
        }
        if (!strcmp(argv[2], "castflags")) {
            vok = probe_castflags();
            printf("probe castflags: cast flag environment %s\n",
                   vok ? "RELIABLE" : "UNRELIABLE");
            return vok ? 0 : 1;
        }
        if (!strcmp(argv[2], "cvtfrom")) {
            vok = probe_cvtfrom(&fok);
            printf("probe cvtfrom: directed-mode values %s\n",
                   vok ? "HONOURED" : "NOT honoured");
            printf("probe cvtfrom: inexact flag %s\n",
                   fok ? "RELIABLE" : "UNRELIABLE");
            return vok ? 0 : 1;
        }
        if (!strcmp(argv[2], "scalebrange"))
            return probe_scalebrange() ? 0 : 1;
        usage(argv[0]);
        return 2;
    }

    if (!strcmp(job, "dump")) {
        int drc = class_dump(argc, argv);
        if (drc == 2)
            usage(argv[0]);
        return drc;
    }

    if (argc < 4) {
        usage(argv[0]);
        return 2;
    }
    p1 = strtoull(argv[2], NULL, 0);
    p2 = strtoull(argv[3], NULL, 0);
    if (argc >= 5) {
        mi = mode_index(argv[4]);
        if (mi < 0) {
            fprintf(stderr, "unknown rounding mode %s\n", argv[4]);
            return 2;
        }
        modename = MODES[mi].name;
    }

    /* CFT_SOAK_ARTIFACT names an .xclbin to soak instead of the software
     * backend. Unset it and this is exactly the call that was here before:
     * NULL selects software. The oracle does not change - it is the host
     * CPU's own IEEE hardware either way - so the same billions of cases
     * that scored software now score a tile. */
    {
        const char *art = getenv("CFT_SOAK_ARTIFACT");
        cft_status ost;
        if (art && !*art) art = NULL;
        ost = cft_open(art, 0, &dev);
        if (ost != CFT_OK) {
            /* cft_strerror always says something. cft_last_error is set
             * only on the paths that bothered, and a refusal with an
             * empty reason is the kind this contract calls a defect. */
            const char *detail = cft_last_error();
            fprintf(stderr, "cft_open(%s) failed: %s%s%s\n",
                    art ? art : "software", cft_strerror(ost),
                    (detail && *detail) ? " - " : "",
                    (detail && *detail) ? detail : "");
            return 2;
        }
        /* Named, every run. A card soak and a software soak are otherwise
         * indistinguishable in a log, and one of them is evidence about
         * hardware. */
        fprintf(stderr, "soaking the %s backend%s%s\n",
                art ? "DEVICE" : "software",
                art ? ": " : "", art ? art : "");
    }
    fesetround(FE_TONEAREST);

    if (!strcmp(job, "rint32") && argc == 5) {
        rc = drv_rint32(p1, p2, mi);
    } else if (!strcmp(job, "nextup32") && argc == 4) {
        rc = drv_next32(1, p1, p2);
    } else if (!strcmp(job, "nextdown32") && argc == 4) {
        rc = drv_next32(0, p1, p2);
    } else if (!strcmp(job, "logb32") && argc == 4) {
        rc = drv_logb32(p1, p2);
    } else if (!strcmp(job, "class32") && argc == 4) {
        rc = drv_class32(p1, p2);
    } else if (!strcmp(job, "rint64") && argc == 5) {
        rng_state = p2 | 1;
        rc = drv_rint64(p1, mi);
    } else if (!strcmp(job, "scaleb32") && argc == 5 && mi != 4) {
        rng_state = p2 | 1;
        rc = drv_scaleb(0, p1, mi);
    } else if (!strcmp(job, "scaleb64") && argc == 5 && mi != 4) {
        rng_state = p2 | 1;
        rc = drv_scaleb(1, p1, mi);
    } else if (!strcmp(job, "conv64to32") && argc == 5 && mi != 4) {
        rng_state = p2 | 1;
        rc = drv_conv64to32(p1, mi);
    } else if (!strcmp(job, "conv32to64") && argc == 4) {
        rng_state = p2 | 1;
        modename = "rne";
        rc = drv_conv32to64(p1);
    } else if (!strcmp(job, "cvtto32") && argc == 5) {
        rng_state = p2 | 1;
        rc = drv_cvtto(0, p1, mi);
    } else if (!strcmp(job, "cvtto64") && argc == 5) {
        rng_state = p2 | 1;
        rc = drv_cvtto(1, p1, mi);
    } else if (!strcmp(job, "cvtfrom32") && argc == 5 && mi != 4) {
        rng_state = p2 | 1;
        rc = drv_cvtfrom(0, p1, mi);
    } else if (!strcmp(job, "cvtfrom64") && argc == 5 && mi != 4) {
        rng_state = p2 | 1;
        rc = drv_cvtfrom(1, p1, mi);
    } else if (!strcmp(job, "rem32") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_rem(0, p1);
    } else if (!strcmp(job, "rem64") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_rem(1, p1);
    } else if (!strcmp(job, "nextup64") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_next64(1, p1);
    } else if (!strcmp(job, "nextdown64") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_next64(0, p1);
    } else if (!strcmp(job, "logb64") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_logb64(p1);
    } else if (!strcmp(job, "class64") && argc == 4) {
        rng_state = p2 | 1;
        rc = drv_class64(p1);
    } else if ((!strcmp(job, "conv32to64-all") && argc == 4) ||
               (!strcmp(job, "cvtto32-all") && argc == 5) ||
               ((!strcmp(job, "cvtfrom32-all") ||
                 !strcmp(job, "cvtfrom64-all") ||
                 !strcmp(job, "scaleb32-all") ||
                 !strcmp(job, "scaleb32-wide")) && argc == 5 && mi != 4)) {
        /* the exhaustive modes: <lo> <hi> over a 32-bit operand's
         * encodings, validated here (a range the loops would wrap is
         * refused), and a verdict line that says what was covered */
        if (exh_range(argv[2], argv[3], &p1, &p2)) {
            cft_close(dev);
            return 2;
        }
        exh_mode = 1;
        if (!strcmp(job, "conv32to64-all")) {
            modename = "rne";
            rc = drv_conv32to64_all(p1, p2);
        } else if (!strcmp(job, "cvtto32-all")) {
            rc = drv_cvtto32_all(p1, p2, mi);
        } else if (!strcmp(job, "cvtfrom32-all")) {
            rc = drv_cvtfrom_all(0, p1, p2, mi);
        } else if (!strcmp(job, "cvtfrom64-all")) {
            rc = drv_cvtfrom_all(1, p1, p2, mi);
        } else if (!strcmp(job, "scaleb32-all")) {
            rc = drv_scaleb32_all(p1, p2, mi);
        } else {
            rc = drv_scaleb32_wide(p1, p2, mi);
        }
    } else if (class_job(job) >= 0 && argc == 5 &&
               (mi != 4 || CLASS_JOBS[class_job(job)].rmm)) {
        /* the class-level modes: <lo> <hi> over the operation's index
         * space, validated here, and a verdict line that says what was
         * covered */
        int cj = class_job(job);
        if (class_range(cj, argv[2], argv[3], &p1, &p2)) {
            cft_close(dev);
            return 2;
        }
        exh_mode = 1;
        switch (cj) {
        case CLS_CONV:    rc = drv_class_conv(p1, p2, mi); break;
        case CLS_RINT:    rc = drv_class_rint(p1, p2, mi); break;
        case CLS_CVTTO:   rc = drv_class_cvtto(p1, p2, mi); break;
        case CLS_CVTFROM: rc = drv_class_cvtfrom(p1, p2, mi); break;
        default:          rc = drv_class_scaleb(p1, p2, mi); break;
        }
    } else {
        usage(argv[0]);
        cft_close(dev);
        return 2;
    }

    if (skipped)
        printf("  skipped %llu lane-target pairs outside the target "
               "range (invalid table is model-pinned)\n",
               (unsigned long long)skipped);
    if (exh_mode)
        printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
               "mismatches, %llu encodings, %llu skipped\n", job, modename,
               (unsigned long long)cases, (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches,
               (unsigned long long)encodings, (unsigned long long)skipped);
    else
        printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
               "mismatches\n", job, modename, (unsigned long long)cases,
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
    cft_close(dev);
    if (rc || mismatches || flag_mismatches)
        return 1;
    return 0;
}
