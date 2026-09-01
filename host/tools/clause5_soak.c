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

static int drv_scaleb(int is64, uint64_t count, int mi)
{
    static uint32_t A32[BATCH], D32[BATCH], W32[BATCH];
    static uint64_t A64[BATCH], D64[BATCH], W64[BATCH];
    const int64_t *list = is64 ? SCALEB_N64 : SCALEB_N32;
    size_t listn = is64 ? sizeof(SCALEB_N64) / sizeof(SCALEB_N64[0])
                        : sizeof(SCALEB_N32) / sizeof(SCALEB_N32[0]);
    const char *nm = is64 ? "scaleb64" : "scaleb32";
    int flags_ok = 1;
    int values_ok = probe_scalbn(&flags_ok);

    if (!values_ok && mi != 0) {
        printf("scalbn probe: directed-mode values NOT honoured; "
               "this job is covered by rne + the model matrix\n");
        return 0;                 /* main prints the zero-case line */
    }
    if (!flags_ok)
        printf("scalbn probe: flag environment unreliable; "
               "comparing values only\n");

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i, li;
        uint64_t sub;
        for (i = 0; i < n; i++) {
            if (is64) A64[i] = banded64(); else A32[i] = banded32();
        }
        for (li = 0; li < listn; li++) {
            int nn = (int)list[li];
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
                         (uint64_t)(int64_t)nn,
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

static int drv_conv64to32(uint64_t count, int mi)
{
    static uint64_t A[BATCH];
    static uint32_t W[BATCH], D[BATCH];
    int flags_ok = probe_castflags();
    if (!flags_ok)
        printf("castflags probe: flag environment unreliable; "
               "comparing values only\n");
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        uint32_t nf, lf = 0;
        int raised;
        for (i = 0; i < n; i++)
            A[i] = banded64();
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
        count -= n;
    }
    return 0;
}

static int drv_conv32to64(uint64_t count)
{
    static uint32_t A[BATCH];
    static uint64_t W[BATCH], D[BATCH];
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        uint32_t lf = 0, ex = 0;
        for (i = 0; i < n; i++) {
            A[i] = banded32();
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

static int drv_cvtto(int is64, uint64_t count, int mi)
{
    static uint64_t A64[BATCH];
    static uint32_t A32[BATCH];
    static uint8_t C[BATCH * 8];        /* compacted operands */
    static uint64_t EXPV[BATCH];        /* expected integer bits */
    static uint8_t INX[BATCH];          /* per-lane derived inexact */
    static uint8_t OUT[BATCH * 8];
    cft_format fmt = is64 ? CFT_FP64 : CFT_FP32;
    size_t esz = is64 ? 8 : 4;

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        int ti;
        for (i = 0; i < n; i++) {
            if (is64) A64[i] = cvtto_operand64();
            else      A32[i] = cvtto_operand32();
        }
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
        if (rng() & 1)
            v = (uint64_t)-(int64_t)v;
    }
    if (width == 32)
        v &= 0xffffffffull;
    return v;
}

static int drv_cvtfrom(int is64, uint64_t count, int mi)
{
    static uint64_t V[BATCH];
    static uint32_t S32[BATCH];
    static uint64_t S64[BATCH];
    static uint32_t W32[BATCH], D32[BATCH];
    static uint64_t W64[BATCH], D64[BATCH];
    static const struct { int w; int sg; const char *nm; } SRC[4] = {
        { 32, 1, "cvt_from_i32" }, { 32, 0, "cvt_from_u32" },
        { 64, 1, "cvt_from_i64" }, { 64, 0, "cvt_from_u64" },
    };
    cft_format fmt = is64 ? CFT_FP64 : CFT_FP32;
    int flags_ok = 1;
    int values_ok = probe_cvtfrom(&flags_ok);

    if (!values_ok && mi != 0) {
        printf("cvtfrom probe: directed-mode values NOT honoured; "
               "this job is covered by rne + the model matrix\n");
        return 0;                 /* main prints the zero-case line */
    }
    if (!flags_ok)
        printf("cvtfrom probe: inexact flag unreliable; "
               "comparing values only\n");

    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        int si;
        for (si = 0; si < 4; si++) {
            uint32_t nf, lf = 0;
            int raised;
            cft_status st;
            for (i = 0; i < n; i++) {
                V[i] = cvtfrom_int(SRC[si].w);
                if (SRC[si].w == 32)
                    S32[i] = (uint32_t)V[i];
                else
                    S64[i] = V[i];
            }
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
        "       %s probe scalbn|castflags|cvtfrom\n",
        argv0, argv0, argv0, argv0, argv0, argv0);
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
        usage(argv[0]);
        return 2;
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

    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "cft_open failed\n");
        return 2;
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
    } else {
        usage(argv[0]);
        cft_close(dev);
        return 2;
    }

    if (skipped)
        printf("  skipped %llu lane-target pairs outside the target "
               "range (invalid table is model-pinned)\n",
               (unsigned long long)skipped);
    printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", job, modename, (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    if (rc || mismatches || flag_mismatches)
        return 1;
    return 0;
}
