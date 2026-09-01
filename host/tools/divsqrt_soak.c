/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Soak cft_div and cft_sqrt against the host CPU's own IEEE hardware.
 *
 * Everything else in this repository is checked against the golden
 * model, which is the definition of correct - but the model and the
 * library share an author, so at fp32/fp64 there is one more oracle
 * worth consulting: the CPU under the test itself. x86-64 SSE division
 * and square root are correctly rounded per 754 in the prevailing
 * rounding mode, with hardware exception flags, and they were defined
 * by people who have never seen this project. A disagreement with them
 * is a real bug in somebody's silicon or ours; agreement at scale is
 * assurance the model matrix cannot provide, because this oracle can
 * afford EXHAUSTIVE fp32 sqrt - all 2^32 encodings - and billions of
 * random divisions at C speed.
 *
 * What this validates: the contract div/sqrt semantics and the
 * composed-sequence C implementation (cft_div/cft_sqrt drive the same
 * sequence code on every backend; here the steps land in softfloat.c).
 * What it cannot validate: the tile itself - that stays with hw_emu
 * and card day. But the image implements the model, so a model bug
 * found here is an image bug found early.
 *
 * Oracle honesty notes, each load-bearing:
 *
 *   * NaN payloads are compared as a CLASS. The hardware propagates
 *     input payloads; the contract canonicalises. Both are 754-legal,
 *     the difference is pinned by the model tests, and insisting on
 *     bit equality here would only re-test that known choice. Flags
 *     still compare exactly.
 *   * RMM (ties-to-away) has no x86 rounding mode. For SQUARE ROOT
 *     that costs nothing: an inexact root is never on a tie (a p+1-bit
 *     midpoint squared needs 2p+1 bits), so RMM == RNE case by case,
 *     and this tool checks RMM sqrt against the RNE oracle. RMM
 *     DIVISION has real ties and is left to the model matrix.
 *   * Flags are accumulated per batch on both sides and compared as
 *     the OR, because cft_div's flags are per-call by design. A batch
 *     whose OR disagrees, or any batch with a value mismatch, is
 *     re-run one element at a time to name the culprit exactly.
 *   * Build with -fno-math-errno (keeps sqrt a bare instruction) and
 *     -frounding-math (keeps the compiler from folding across
 *     fesetround). Default x86-64 codegen is SSE2, so there is no
 *     x87 double rounding to worry about.
 *
 * Usage (one process per job; hw/run-soak.sh fans these out):
 *
 *   divsqrt-soak sqrt32 <lo> <hi> <rne|rtz|rdn|rup|rmm>
 *       exhaustive over encodings [lo, hi) as uint32
 *   divsqrt-soak div32|div64|sqrt64 <count> <seed> <rne|rtz|rdn|rup>
 *       random, xorshift-seeded, exponent-banded operands
 */

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
static uint64_t mismatches, flag_mismatches, cases;
static int shown;

/* ---- rounding modes ----------------------------------------------- */

static const struct { const char *name; cft_round cr; int fe; int native; }
MODES[] = {
    { "rne", CFT_RNE, FE_TONEAREST,  1 },
    { "rtz", CFT_RTZ, FE_TOWARDZERO, 1 },
    { "rdn", CFT_RDN, FE_DOWNWARD,   1 },
    { "rup", CFT_RUP, FE_UPWARD,     1 },
    /* RMM checked against the RNE oracle; sqrt only (no ties). */
    { "rmm", CFT_RMM, FE_TONEAREST,  0 },
};

static int mode_index(const char *s)
{
    int i;
    for (i = 0; i < 5; i++)
        if (!strcmp(MODES[i].name, s))
            return i;
    return -1;
}

/* ---- native flag capture ------------------------------------------ */

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

/* ---- bit views ---------------------------------------------------- */

static uint32_t f2u(float x)  { uint32_t u; memcpy(&u, &x, 4); return u; }
static float    u2f(uint32_t u) { float x; memcpy(&x, &u, 4); return x; }
static uint64_t d2u(double x) { uint64_t u; memcpy(&u, &x, 8); return u; }
static double   u2d(uint64_t u) { double x; memcpy(&x, &u, 8); return x; }

static int is_nan32(uint32_t u)
{
    return (u & 0x7f800000u) == 0x7f800000u && (u & 0x007fffffu);
}

static int is_nan64(uint64_t u)
{
    return (u & 0x7ff0000000000000ull) == 0x7ff0000000000000ull &&
           (u & 0x000fffffffffffffull);
}

/* value agreement: bit-identical, or both NaN (payload is a known,
 * model-pinned difference of convention - see the header) */
static int agree32(uint32_t a, uint32_t b)
{
    return a == b || (is_nan32(a) && is_nan32(b));
}

static int agree64(uint64_t a, uint64_t b)
{
    return a == b || (is_nan64(a) && is_nan64(b));
}

/* ---- random operands ---------------------------------------------- */

static uint64_t rng_state;

static uint64_t rng(void)
{
    uint64_t x = rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return rng_state = x;
}

/* Uniform bits reach the exponent extremes almost never, and the
 * subnormal/overflow bands are exactly where a rounding bug would
 * live. So a quarter of operands get their exponent field forced
 * into a band at one of the range's edges or the middle. */
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

/* ---- the batch engine --------------------------------------------- */

typedef enum { OP_DIV32, OP_DIV64, OP_SQRT32, OP_SQRT64 } soak_op;

static size_t op_esz(soak_op op)
{
    return (op == OP_DIV32 || op == OP_SQRT32) ? 4 : 8;
}

/* Native results and OR'd native flags for one batch. */
static uint32_t native_batch(soak_op op, int fe, const uint8_t *a,
                             const uint8_t *b, uint8_t *want, size_t n)
{
    int ex;
    size_t i;
    fesetround(fe);
    feclearexcept(FE_ALL_EXCEPT);
    switch (op) {
    case OP_DIV32:
        for (i = 0; i < n; i++) {
            float r = u2f(((const uint32_t *)(const void *)a)[i]) /
                      u2f(((const uint32_t *)(const void *)b)[i]);
            ((uint32_t *)(void *)want)[i] = f2u(r);
        }
        break;
    case OP_DIV64:
        for (i = 0; i < n; i++) {
            double r = u2d(((const uint64_t *)(const void *)a)[i]) /
                       u2d(((const uint64_t *)(const void *)b)[i]);
            ((uint64_t *)(void *)want)[i] = d2u(r);
        }
        break;
    case OP_SQRT32:
        for (i = 0; i < n; i++)
            ((uint32_t *)(void *)want)[i] =
                f2u(sqrtf(u2f(((const uint32_t *)(const void *)a)[i])));
        break;
    case OP_SQRT64:
        for (i = 0; i < n; i++)
            ((uint64_t *)(void *)want)[i] =
                d2u(sqrt(u2d(((const uint64_t *)(const void *)a)[i])));
        break;
    }
    ex = fetestexcept(FE_ALL_EXCEPT);
    fesetround(FE_TONEAREST);
    return fe_to_cft(ex);
}

/* Negative control: CFT_SOAK_SABOTAGE=1 flips the low bit of the
 * first result in every batch AFTER the library computes it. A
 * harness that cannot fail proves nothing, so hw/run-soak.sh QUICK
 * mode runs one sabotaged job and requires it to report mismatches. */
static int sabotage = -1;

static cft_status lib_call(soak_op op, cft_round cr, const uint8_t *a,
                           const uint8_t *b, uint8_t *d, size_t n,
                           uint32_t *fl)
{
    cft_format fmt = op_esz(op) == 4 ? CFT_FP32 : CFT_FP64;
    cft_status st;
    if (op == OP_DIV32 || op == OP_DIV64)
        st = cft_div(dev, fmt, cr, a, b, d, n, fl, NULL);
    else
        st = cft_sqrt(dev, fmt, cr, a, d, n, fl, NULL);
    if (sabotage < 0) {
        const char *e = getenv("CFT_SOAK_SABOTAGE");
        sabotage = (e && *e == '1') ? 1 : 0;
    }
    if (st == CFT_OK && sabotage && n > 0)
        d[0] ^= 1u;
    return st;
}

static void report32(const char *what, uint32_t xa, uint32_t xb, int has_b,
                     uint32_t got, uint32_t want)
{
    if (shown++ >= 16)
        return;
    if (has_b)
        printf("  MISMATCH %s a=0x%08x b=0x%08x lib=0x%08x cpu=0x%08x\n",
               what, xa, xb, got, want);
    else
        printf("  MISMATCH %s a=0x%08x lib=0x%08x cpu=0x%08x\n",
               what, xa, got, want);
}

static void report64(const char *what, uint64_t xa, uint64_t xb, int has_b,
                     uint64_t got, uint64_t want)
{
    if (shown++ >= 16)
        return;
    if (has_b)
        printf("  MISMATCH %s a=0x%016llx b=0x%016llx lib=0x%016llx "
               "cpu=0x%016llx\n", what, (unsigned long long)xa,
               (unsigned long long)xb, (unsigned long long)got,
               (unsigned long long)want);
    else
        printf("  MISMATCH %s a=0x%016llx lib=0x%016llx cpu=0x%016llx\n",
               what, (unsigned long long)xa, (unsigned long long)got,
               (unsigned long long)want);
}

/* Element-by-element re-run of a suspect batch: per-element native
 * flags against per-element (n=1) library flags, so the culprit is
 * named exactly rather than smeared across the OR. */
static void recheck_batch(soak_op op, int mi, const uint8_t *a,
                          const uint8_t *b, size_t n)
{
    size_t esz = op_esz(op), i;
    int has_b = (op == OP_DIV32 || op == OP_DIV64);
    uint8_t got[8], want[8];
    for (i = 0; i < n; i++) {
        uint32_t nf = native_batch(op, MODES[mi].fe, a + i * esz,
                                   b ? b + i * esz : NULL, want, 1);
        uint32_t lf = 0;
        if (lib_call(op, MODES[mi].cr, a + i * esz,
                     b ? b + i * esz : NULL, got, 1, &lf) != CFT_OK)
            continue;
        if (esz == 4) {
            uint32_t g, w, xa, xb = 0;
            memcpy(&g, got, 4); memcpy(&w, want, 4);
            memcpy(&xa, a + i * 4, 4);
            if (b) memcpy(&xb, b + i * 4, 4);
            if (!agree32(g, w)) {
                mismatches++;
                report32(MODES[mi].name, xa, xb, has_b, g, w);
            }
            if (lf != nf && shown < 16) {
                flag_mismatches++;
                printf("  FLAGS %s a=0x%08x%s lib=0x%02x cpu=0x%02x\n",
                       MODES[mi].name, xa, has_b ? " (div)" : "",
                       (unsigned)lf, (unsigned)nf);
                shown++;
            } else if (lf != nf) {
                flag_mismatches++;
            }
        } else {
            uint64_t g, w, xa, xb = 0;
            memcpy(&g, got, 8); memcpy(&w, want, 8);
            memcpy(&xa, a + i * 8, 8);
            if (b) memcpy(&xb, b + i * 8, 8);
            if (!agree64(g, w)) {
                mismatches++;
                report64(MODES[mi].name, xa, xb, has_b, g, w);
            }
            if (lf != nf) {
                flag_mismatches++;
                if (shown < 16) {
                    printf("  FLAGS %s a=0x%016llx lib=0x%02x cpu=0x%02x\n",
                           MODES[mi].name, (unsigned long long)xa,
                           (unsigned)lf, (unsigned)nf);
                    shown++;
                }
            }
        }
    }
}

static int run_batch(soak_op op, int mi, const uint8_t *a, const uint8_t *b,
                     size_t n)
{
    static uint8_t want[BATCH * 8], got[BATCH * 8];
    size_t esz = op_esz(op), i;
    uint32_t nf, lf = 0;
    int bad = 0;

    nf = native_batch(op, MODES[mi].fe, a, b, want, n);
    if (lib_call(op, MODES[mi].cr, a, b, got, n, &lf) != CFT_OK) {
        printf("  library call failed\n");
        return 1;
    }
    for (i = 0; i < n && !bad; i++) {
        if (esz == 4) {
            uint32_t g, w;
            memcpy(&g, got + i * 4, 4);
            memcpy(&w, want + i * 4, 4);
            if (!agree32(g, w)) bad = 1;
        } else {
            uint64_t g, w;
            memcpy(&g, got + i * 8, 8);
            memcpy(&w, want + i * 8, 8);
            if (!agree64(g, w)) bad = 1;
        }
    }
    if (lf != nf) bad = 1;
    if (bad)
        recheck_batch(op, mi, a, b, n);
    cases += n;
    return 0;
}

/* ---- drivers ------------------------------------------------------ */

static int soak_sqrt32(uint64_t lo, uint64_t hi, int mi)
{
    static uint8_t a[BATCH * 4];
    uint64_t v = lo;
    while (v < hi) {
        size_t n = hi - v > BATCH ? BATCH : (size_t)(hi - v), i;
        for (i = 0; i < n; i++)
            ((uint32_t *)(void *)a)[i] = (uint32_t)(v + i);
        if (run_batch(OP_SQRT32, mi, a, NULL, n))
            return 1;
        v += n;
    }
    return 0;
}

static int soak_random(soak_op op, uint64_t count, int mi)
{
    static uint8_t a[BATCH * 8], b[BATCH * 8];
    size_t esz = op_esz(op);
    int has_b = (op == OP_DIV32 || op == OP_DIV64);
    while (count) {
        size_t n = count > BATCH ? BATCH : (size_t)count, i;
        for (i = 0; i < n; i++) {
            if (esz == 4) {
                ((uint32_t *)(void *)a)[i] = banded32();
                if (has_b) ((uint32_t *)(void *)b)[i] = banded32();
            } else {
                ((uint64_t *)(void *)a)[i] = banded64();
                if (has_b) ((uint64_t *)(void *)b)[i] = banded64();
            }
        }
        if (run_batch(op, mi, a, has_b ? b : NULL, n))
            return 1;
        count -= n;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int mi, rc = 1;
    if (argc != 5) {
        fprintf(stderr,
            "usage: %s sqrt32 <lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
            "       %s div32|div64|sqrt64 <count> <seed> <rne|rtz|rdn|rup>\n",
            argv[0], argv[0]);
        return 2;
    }
    mi = mode_index(argv[4]);
    if (mi < 0) {
        fprintf(stderr, "unknown rounding mode %s\n", argv[4]);
        return 2;
    }
    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "cft_open failed\n");
        return 2;
    }

    if (!strcmp(argv[1], "sqrt32")) {
        uint64_t lo = strtoull(argv[2], NULL, 0);
        uint64_t hi = strtoull(argv[3], NULL, 0);
        rc = soak_sqrt32(lo, hi, mi);
    } else if (!MODES[mi].native) {
        /* RMM's oracle trick is sqrt-only; refuse loudly elsewhere. */
        fprintf(stderr, "rmm is only checkable for sqrt (no native mode, "
                        "and division has real ties)\n");
        cft_close(dev);
        return 2;
    } else if (!strcmp(argv[1], "div32")) {
        rng_state = strtoull(argv[3], NULL, 0) | 1;
        rc = soak_random(OP_DIV32, strtoull(argv[2], NULL, 0), mi);
    } else if (!strcmp(argv[1], "div64")) {
        rng_state = strtoull(argv[3], NULL, 0) | 1;
        rc = soak_random(OP_DIV64, strtoull(argv[2], NULL, 0), mi);
    } else if (!strcmp(argv[1], "sqrt64")) {
        rng_state = strtoull(argv[3], NULL, 0) | 1;
        rc = soak_random(OP_SQRT64, strtoull(argv[2], NULL, 0), mi);
    } else {
        fprintf(stderr, "unknown op %s\n", argv[1]);
        cft_close(dev);
        return 2;
    }

    printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", argv[1], argv[4], (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    if (rc || mismatches || flag_mismatches)
        return 1;
    return 0;
}
