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
 *   divsqrt-soak div32-hard|div64-hard <lo> <hi> <rne|rtz|rdn|rup>
 *   divsqrt-soak sqrt64-hard <lo> <hi> <rne|rtz|rdn|rup|rmm>
 *       the hard-case modes: indices [lo, hi) of a deterministic space of
 *       CONSTRUCTED operands (below), RMM too for the square root
 *   divsqrt-soak hard-space <div32-hard|div64-hard|sqrt64-hard>
 *   divsqrt-soak hard-dump <div32-hard|div64-hard|sqrt64-hard> <lo> <hi>
 *   divsqrt-soak hard-count <div32-hard|div64-hard|sqrt64-hard> <lo> <hi>
 *       the space's segment table; the operands of indices [lo, hi); the
 *       cases and skipped slots of [lo, hi) by segment (no device is
 *       opened). python/hardcases.py prints all three line for line
 *
 * Built with `make divsqrt-soak MPFR=1` (host/Makefile), thirty more: the
 * wide modes, fp64, fp128 and fp256 division and square root against MPFR
 * (mpfr-check's emulation, tools/mpfr_ieee.h) with a second check by the
 * ladder - the section "The wide formats" below. Built without it, the
 * tool is exactly what it was before them.
 */

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"

#pragma STDC FENV_ACCESS ON

/* Operands a call: 4096, unless the build says otherwise. host/Makefile's
 * SOAK_CHUNK targets compile this tool with -DBATCH=<n>, and the library it
 * links with -DCFT_CHUNK=<n>, the same n, so that one call is one pass.
 * Flags are compared per batch (above), so a larger BATCH compares them over
 * more operands at once; main names both values on stderr when either is
 * not 4096. */
#ifndef BATCH
#define BATCH 4096
#endif

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
        /* Two statements, so the two draws come in one order on every
         * compiler (C leaves the order of a sum's operands open): the
         * band first, as every gcc build measured on 2026-10-20 did. */
        uint32_t e = bands[rng() % 7];
        e += (uint32_t)(rng() % 3);
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
        uint64_t e = bands[rng() % 7];      /* two statements, as above */
        e += rng() % 3;
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

/* ================================================================
 * Hard cases: constructed operands, not drawn ones (parcel HC)
 *
 * div32-hard, div64-hard and sqrt64-hard take <lo> <hi> over a
 * deterministic INDEX SPACE, the way the exhaustive modes take
 * encodings, and call the same batch kernel (run_batch) as the random
 * modes, so the oracle, the flag discipline and the sabotage are the
 * random modes' by construction; only the operand source differs.
 *
 * Why. A quotient of two p-bit significands lies closer than 2^-p of an
 * ulp to a rounding boundary with probability about ln 2 / 2^(p-1) a
 * draw: 8e-8 at fp32 and 1.5e-16 at fp64, so a sampler never reaches
 * the fp64 class (docs/studies/SWP-A-coverage.md section 4.2). One
 * modular inverse builds it: for an odd divisor my, the dividend mx
 * with mx 2^k = +-1 (mod my) is at the least distance a quotient can
 * come to a midpoint (k = p) or a representable number (k = p - 1);
 * square root has the same structure in the squares of odd integers.
 * python/hardcases.py is the reference: it builds the same operands
 * and verifies each case in exact integers, and `hard-dump` prints
 * ours so that the two are compared line for line.
 *
 * The space. A mode is a list of segments (hard-space prints it); an
 * index belongs to one segment and makes `k` slots - division: the four
 * sign combinations of one operand pair, slot s = sign(a) + 2 sign(b);
 * square root: one. Within a segment an index is 4 j + v: j picks the
 * base (a divisor, a pair of odd parts, a strip depth) and v one of four
 * variants of it. The families:
 *   F3a  ties in the subnormal strip: b = 2^(s+3), the exact quotient an
 *        odd multiple of half the smallest subnormal, s places below
 *        the smallest normal, in four bit patterns
 *   F3b  powers of two across the whole quotient-exponent range
 *   F2   b = 1 +- k ulp (and a = 1.0 or 2 - ulp): the repository's own
 *        failing family a = 1, b = 1 - ulp is j = 0
 *   F1   exact quotients: a = ob oq, b = ob, in four exponent classes
 *   F0   closest approach to a midpoint or a representable number over
 *        odd divisors: A from the bottom of the binade, D from the top,
 *        K (fp64) keyed, the top 12 fraction bits taking every value
 *        once in 4,096 divisors (in a scrambled order)
 *   S1   sqrt(1 + k ulp), k odd, and three kin
 *   S0   the inputs nearest the squares of midpoints, from the 2-adic
 *        square roots of rho = 8 m + 1 (1, -7, 9, -15, ...)
 *
 * A SKIP is an index whose construction yields no operand pair - for
 * F0, a divisor that has no dividend at |N| = 1 for the index's target
 * and sign in either binade (about 31 per cent of them); for S0, a rho
 * without a root in range. All k slots of a skipped index are skipped.
 *
 * Coverage. The verdict line carries the exhaustive modes' clause,
 * ", E encodings, S skipped": E here counts INDICES, every (index, slot)
 * is compared (a case) or skipped, so cases + S = k * E with k fixed by
 * the mode (4, 4 and 1), and hw/card_stress_lib.py holds a slice to it.
 * A slice of 64 or more indices in which EVERY index skipped is
 * refused by name instead (exit 2): the construction yields a case for
 * most indices everywhere, so a run that long means it is broken.
 *
 * Self-check. Every F0 case is verified in exact 128-bit integers as it
 * is built (|N| = 1, and its sign), and every S0 case (u^2 = rho mod
 * 2^s); a failure refuses the run by name, exit 2: a case that is not
 * the hard case it claims to be proves nothing.
 *
 * Flags are compared per batch, as in every mode here. The families are
 * contiguous segments, so a batch is nearly always of one family; the
 * exact quotients (F1) are the only family whose flags are all clear.
 * ================================================================ */

static uint64_t hencodings, hskipped;     /* indices run, slots skipped (the verdict's clause) */
static int hard_mode;                     /* the verdict line says what it covered */

#ifdef __SIZEOF_INT128__          /* 64-bit gcc and clang; elsewhere the hard modes refuse by name */

__extension__ typedef unsigned __int128 u128;

enum { H_F3A, H_F3B, H_F2, H_F1, H_F0A, H_F0D, H_F0K, H_S1, H_S0 };
#define HMAXSEG 8
#define HMIN_REFUSE 64            /* an all-skipped slice this long is refused */
#define H_SALT_F0K 0x5851F42D4C957F2Dull
#define H_SALT_F1  0x14057B7EF767814Full

typedef struct {
    const char *mode;
    soak_op op;
    int p, bias, k, nseg;
    struct { int fam; const char *name; uint64_t count; } seg[HMAXSEG];
} hspace;

static const hspace HSPACES[] = {
    { "div32-hard", OP_DIV32, 24, 127, 4, 6, {
        { H_F3A, "F3a", 4u * 24 },
        { H_F3B, "F3b", 4u * (4 * 127 - 1) },
        { H_F2,  "F2",  (uint64_t)4 << 16 },
        { H_F1,  "F1",  (uint64_t)4 << 20 },
        { H_F0A, "F0A", (uint64_t)4 << 21 },
        { H_F0D, "F0D", (uint64_t)4 << 21 } } },
    { "div64-hard", OP_DIV64, 53, 1023, 4, 7, {
        { H_F3A, "F3a", 4u * 53 },
        { H_F3B, "F3b", 4u * (4 * 1023 - 1) },
        { H_F2,  "F2",  (uint64_t)4 << 16 },
        { H_F1,  "F1",  (uint64_t)4 << 20 },
        { H_F0A, "F0A", (uint64_t)4 << 21 },
        { H_F0D, "F0D", (uint64_t)4 << 21 },
        { H_F0K, "F0K", (uint64_t)4 << 26 } } },
    { "sqrt64-hard", OP_SQRT64, 53, 1023, 1, 2, {
        { H_S1,  "S1",  (uint64_t)4 << 16 },
        { H_S0,  "S0",  (uint64_t)4 << 20 } } },
};

static const hspace *hspace_of(const char *mode)
{
    size_t i;
    for (i = 0; i < sizeof HSPACES / sizeof HSPACES[0]; i++)
        if (!strcmp(HSPACES[i].mode, mode))
            return &HSPACES[i];
    return NULL;
}

static uint64_t hspace_total(const hspace *sp)
{
    uint64_t t = 0;
    int i;
    for (i = 0; i < sp->nseg; i++)
        t += sp->seg[i].count;
    return t;
}

static int herr;                  /* set by a builder whose exact self-check failed */

static uint64_t mix64(uint64_t x)
{
    x += 0x9E3779B97F4A7C15ull;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
    return x ^ (x >> 31);
}

static int bitlen(uint64_t n)
{
    int l = 0;
    while (n) { l++; n >>= 1; }
    return l;
}

/* The positive normal number sig * 2^(e - bias - (p-1)), sig in [2^(p-1), 2^p). */
static uint64_t henc(const hspace *sp, int64_t e, uint64_t sig)
{
    uint64_t p1 = (uint64_t)1 << (sp->p - 1);
    if (e < 1 || e > 2 * (int64_t)sp->bias || sig < p1 || sig >= 2 * p1)
        herr = 1;
    return ((uint64_t)e << (sp->p - 1)) | (sig - p1);
}

/* The exact value n 2^t, n a positive integer of at most p bits. */
static uint64_t henc_int(const hspace *sp, uint64_t n, int t)
{
    int len = bitlen(n);
    return henc(sp, sp->bias + len - 1 + t, n << (sp->p - len));
}

/* An odd integer of exactly `len` bits: all ones, 10..01, 1010..1, and
 * all ones but bit 1. */
static uint64_t tie_pattern(int len, int v)
{
    uint64_t full = ((uint64_t)1 << len) - 1, top = (uint64_t)1 << (len - 1);
    if (v == 0) return full;
    if (v == 1) return top | 1;
    if (v == 2) return (0x5555555555555555ull & full) | top | 1;
    return (full & ~(uint64_t)2) | top | 1;
}

/* The inverse of 2^kk modulo an odd my (3 <= my < 2^54), in [1, my). */
static uint64_t inv_pow2(int kk, uint64_t my)
{
    uint64_t t = 1;
    int64_t r0 = (int64_t)my, x0 = 0, x1 = 1, r1;
    int i;
    for (i = 0; i < kk; i++) {
        t <<= 1;
        if (t >= my) t -= my;
    }
    r1 = (int64_t)t;
    while (r1) {
        int64_t q = r0 / r1, tmp = r0 - q * r1;
        r0 = r1; r1 = tmp;
        tmp = x0 - q * x1; x0 = x1; x1 = tmp;
    }
    return (uint64_t)(x0 < 0 ? x0 + (int64_t)my : x0);
}

static uint64_t f0_divisor(const hspace *sp, int fam, uint64_t jj)
{
    uint64_t p1 = (uint64_t)1 << (sp->p - 1);
    if (fam == H_F0A) return p1 + 1 + 2 * jj;
    if (fam == H_F0D) return 2 * p1 - 1 - 2 * jj;
    return p1 | (((jj * 2659) & 4095) << (sp->p - 13)) |
           (mix64(jj ^ H_SALT_F0K) & (((uint64_t)1 << (sp->p - 13)) - 1)) | 1;
}

/* |N| = 1 and its sign, in exact integers: x 2^kk = +-1 (mod my) for the
 * representable target, and (x 2^p mod 2 my) = my +- 1 for the midpoint
 * (N = that - my). x is the numerator in the window [my, 2 my). */
static int f0_exact(int p, uint64_t x, uint64_t my, int target, int plus)
{
    if (target == 0) {
        uint64_t t = (uint64_t)(((u128)x << p) % (2 * (u128)my));
        return t == (plus ? my + 1 : my - 1);
    }
    return (uint64_t)(((u128)x << (p - 1)) % my) == (plus ? 1 : my - 1);
}

/* An odd u, 0 <= u < 2^t, with u^2 = rho (mod 2^t), rho = 1 (mod 8). */
static uint64_t hensel(uint64_t rho, int t)
{
    uint64_t u = 1;
    int b;
    for (b = 3; b < t; b++)
        if (((u * u - rho) >> b) & 1)
            u += (uint64_t)1 << (b - 1);
    return u & (((uint64_t)1 << t) - 1);
}

/* The positive operand pair of an index (b unused for the square root):
 * 1 for a case, 0 for a skip. */
static int hard_base(const hspace *sp, uint64_t idx, uint64_t *a, uint64_t *b)
{
    int p = sp->p, bias = sp->bias, s = 0, v;
    uint64_t p1 = (uint64_t)1 << (p - 1), pp = 2 * p1, i0 = idx, j;
    int fam = -1;
    for (s = 0; s < sp->nseg; s++) {
        if (i0 < sp->seg[s].count) { fam = sp->seg[s].fam; break; }
        i0 -= sp->seg[s].count;
    }
    j = i0 >> 2;
    v = (int)(i0 & 3);
    switch (fam) {
    case H_F3A: {
        int sd = (int)j + 1;
        *a = henc(sp, 4, tie_pattern(p - sd + 1, v) << (sd - 1));
        *b = henc(sp, bias + sd + 3, p1);
        return 1;
    }
    case H_F3B: {
        int64_t eq = (int64_t)j - (2 * (int64_t)bias - 1);
        int64_t ea = 1 + (eq > 0 ? eq : 0), eb = 1 + (eq < 0 ? -eq : 0);
        uint64_t sig = (v == 0 || v == 2) ? pp - 1 : (uint64_t)3 << (p - 2);
        if (v < 2) { *a = henc(sp, ea, sig); *b = henc(sp, eb, p1); }
        else       { *a = henc(sp, ea, p1);  *b = henc(sp, eb, sig); }
        return 1;
    }
    case H_F2: {
        uint64_t k = j + 1;
        *a = henc(sp, bias, v < 2 ? p1 : pp - 1);
        *b = (v & 1) == 0 ? henc(sp, bias, p1 + k) : henc(sp, bias - 1, pp - k);
        return 1;
    }
    case H_F1: {
        int h = (p - 1) / 2, e = bias / 3, tb3 = bias / 2, sh = p - 2, ta, tb;
        uint64_t ob = 2 * (mix64((2 * j) ^ H_SALT_F1) >> (64 - (h - 1))) + 1;
        uint64_t oq = 2 * (mix64((2 * j + 1) ^ H_SALT_F1) >> (64 - (h - 1))) + 1;
        ta = v == 0 ? 0 : v == 1 ? e : v == 2 ? -e : tb3 + (1 - bias) - sh;
        tb = v == 0 ? 0 : v == 1 ? -e : v == 2 ? e : tb3;
        *a = henc_int(sp, ob * oq, ta);
        *b = henc_int(sp, ob, tb);
        return 1;
    }
    case H_F0A: case H_F0D: case H_F0K: {
        uint64_t my = f0_divisor(sp, fam, j), r, x, mx;
        int target = v >> 1, plus = !(v & 1);
        r = inv_pow2(target == 0 ? p : p - 1, my);
        if (!plus) r = my - r;
        x = r + my;
        if (x < pp) mx = x;
        else if (!(x & 1)) mx = x >> 1;
        else return 0;
        if (!f0_exact(p, x, my, target, plus)) { herr = 1; return 0; }
        *a = henc(sp, bias, mx);
        *b = henc(sp, bias, my);
        return 1;
    }
    case H_S1: {
        uint64_t k = 2 * j + 1;
        *a = v == 0 ? henc(sp, bias, p1 + k) : v == 1 ? henc(sp, bias + 1, pp - k) :
             v == 2 ? henc(sp, bias - 1, pp - k) : henc(sp, bias + 510, p1 + k);
        return 1;
    }
    case H_S0: {
        int par = v >> 1, r = v & 1, sh = p + 1 + par, nr = 0, i, c;
        int64_t m = (j & 1) ? -(int64_t)((j + 1) >> 1) : (int64_t)(j >> 1);
        uint64_t rho = (uint64_t)(8 * m + 1), u0 = hensel(rho, p + 2);
        uint64_t size = (uint64_t)1 << sh, c0 = u0 & (size - 1), cand[4], root[4], t;
        u128 sq, lim = (u128)1 << (2 * p + 1);
        cand[0] = c0;
        cand[1] = (size - c0) & (size - 1);
        cand[2] = (c0 + (size >> 1)) & (size - 1);
        cand[3] = (size - c0 + (size >> 1)) & (size - 1);
        for (i = 0; i < 4; i++) {
            sq = (u128)cand[i] * cand[i];
            if (cand[i] >= pp && cand[i] < 2 * pp && ((sq < lim) == (par == 0))) {
                for (c = nr++; c > 0 && root[c - 1] > cand[i]; c--)
                    root[c] = root[c - 1];
                root[c] = cand[i];
            }
        }
        if (r >= nr) return 0;
        sq = (u128)root[r] * root[r];
        if ((uint64_t)(sq & (size - 1)) != (rho & (size - 1))) { herr = 1; return 0; }
        t = (uint64_t)((sq + ((u128)1 << (sh - 1))) >> sh);
        if (t < p1 || t >= pp) return 0;
        *a = henc(sp, bias + par, t);
        return 1;
    }
    default:
        herr = 1;
        return 0;
    }
}

/* [lo, hi) must be a non-empty part of the mode's indices: refused by
 * name, like the exhaustive modes' ranges. */
static int hard_range(const hspace *sp, const char *slo, const char *shi,
                      uint64_t *lo, uint64_t *hi)
{
    char *e1, *e2;
    *lo = strtoull(slo, &e1, 0);
    *hi = strtoull(shi, &e2, 0);
    if (!*slo || !*shi || *e1 || *e2 || *lo >= *hi || *hi > hspace_total(sp)) {
        fprintf(stderr, "need 0 <= lo < hi <= %llu (the indices of %s), "
                "got [%s, %s)\n", (unsigned long long)hspace_total(sp),
                sp->mode, slo, shi);
        return 1;
    }
    return 0;
}

static int soak_hard(const hspace *sp, uint64_t lo, uint64_t hi, int mi)
{
    static uint8_t A[BATCH * 8], B[BATCH * 8];
    int has_b = sp->k == 4, w = op_esz(sp->op) * 8, sl, rc = 0;
    size_t n = 0;
    uint64_t idx, a = 0, b = 0, sign = (uint64_t)1 << (w - 1);
    for (idx = lo; idx < hi && !rc; idx++) {
        if (n + (size_t)sp->k > BATCH) {
            rc = run_batch(sp->op, mi, A, has_b ? B : NULL, n);
            n = 0;
            if (rc) break;
        }
        hencodings++;
        if (!hard_base(sp, idx, &a, &b)) {
            if (herr) {
                fprintf(stderr, "%s: the exact check of index %llu failed - "
                        "the construction is broken, not the library\n",
                        sp->mode, (unsigned long long)idx);
                return 2;
            }
            hskipped += (uint64_t)sp->k;
            continue;
        }
        if (herr) {
            fprintf(stderr, "%s: index %llu built an operand outside the "
                    "format - the construction is broken\n", sp->mode,
                    (unsigned long long)idx);
            return 2;
        }
        for (sl = 0; sl < sp->k; sl++, n++) {
            uint64_t sa = (sl & 1) ? sign : 0, sb = (sl & 2) ? sign : 0;
            if (w == 32) {
                ((uint32_t *)(void *)A)[n] = (uint32_t)(a | sa);
                if (has_b) ((uint32_t *)(void *)B)[n] = (uint32_t)(b | sb);
            } else {
                ((uint64_t *)(void *)A)[n] = a | sa;
                if (has_b) ((uint64_t *)(void *)B)[n] = b | sb;
            }
        }
    }
    if (!rc && n)
        rc = run_batch(sp->op, mi, A, has_b ? B : NULL, n);
    if (!rc && !cases && hi - lo >= HMIN_REFUSE) {
        fprintf(stderr, "%s: every one of the %llu indices of [%llu, %llu) "
                "skipped - a run of skips that long is a broken "
                "construction, not an empty region; refused\n", sp->mode,
                (unsigned long long)(hi - lo), (unsigned long long)lo,
                (unsigned long long)hi);
        return 2;
    }
    return rc;
}

static int hard_space_cmd(const char *mode)
{
    const hspace *sp = hspace_of(mode);
    uint64_t start = 0;
    int i;
    if (!sp) {
        fprintf(stderr, "unknown hard-case mode %s\n", mode);
        return 2;
    }
    printf("%s k=%d total=%llu\n", sp->mode, sp->k,
           (unsigned long long)hspace_total(sp));
    for (i = 0; i < sp->nseg; i++) {
        printf("%s %llu %llu\n", sp->seg[i].name, (unsigned long long)start,
               (unsigned long long)sp->seg[i].count);
        start += sp->seg[i].count;
    }
    return 0;
}

static int hard_dump_cmd(const char *mode, const char *slo, const char *shi)
{
    const hspace *sp = hspace_of(mode);
    uint64_t lo, hi, idx, a = 0, b = 0, sign;
    int w, sl, hx;
    if (!sp) {
        fprintf(stderr, "unknown hard-case mode %s\n", mode);
        return 2;
    }
    if (hard_range(sp, slo, shi, &lo, &hi))
        return 2;
    w = (int)op_esz(sp->op) * 8;
    hx = w / 4;
    sign = (uint64_t)1 << (w - 1);
    for (idx = lo; idx < hi; idx++) {
        int ok = hard_base(sp, idx, &a, &b);
        if (herr) {
            fprintf(stderr, "%s: the exact check of index %llu failed\n",
                    sp->mode, (unsigned long long)idx);
            return 2;
        }
        for (sl = 0; sl < sp->k; sl++) {
            if (!ok)
                printf("%llu %d skip\n", (unsigned long long)idx, sl);
            else if (sp->k == 1)
                printf("%llu %d 0x%0*llx\n", (unsigned long long)idx, sl, hx,
                       (unsigned long long)a);
            else
                printf("%llu %d 0x%0*llx 0x%0*llx\n", (unsigned long long)idx,
                       sl, hx, (unsigned long long)(a | ((sl & 1) ? sign : 0)),
                       hx, (unsigned long long)(b | ((sl & 2) ? sign : 0)));
        }
    }
    return 0;
}

/* The cases a slice makes, without the library: per segment, its indices, the
 * cases (k a built index) and the skipped slots, then the total, then the
 * longest run of consecutive skipped indices (the refusal of an all-skipped
 * slice needs it to be shorter than HMIN_REFUSE). The exact count behind
 * "cases + skipped = k x encodings" for any slice. */
static int hard_count_cmd(const char *mode, const char *slo, const char *shi)
{
    const hspace *sp = hspace_of(mode);
    uint64_t lo, hi, start = 0, ti = 0, tc = 0, ts = 0, run = 0, maxrun = 0;
    int i;
    if (!sp) {
        fprintf(stderr, "unknown hard-case mode %s\n", mode);
        return 2;
    }
    if (hard_range(sp, slo, shi, &lo, &hi))
        return 2;
    for (i = 0; i < sp->nseg; i++) {
        uint64_t a_lo = lo > start ? lo : start, idx, built = 0, a, b;
        uint64_t a_hi = hi < start + sp->seg[i].count ? hi : start + sp->seg[i].count;
        if (a_lo < a_hi) {
            for (idx = a_lo; idx < a_hi; idx++) {
                int ok = hard_base(sp, idx, &a, &b);
                if (herr) {
                    fprintf(stderr, "%s: the exact check of index %llu failed\n",
                            sp->mode, (unsigned long long)idx);
                    return 2;
                }
                built += (uint64_t)ok;
                run = ok ? 0 : run + 1;
                if (run > maxrun)
                    maxrun = run;
            }
            printf("%s %llu %llu %llu\n", sp->seg[i].name,
                   (unsigned long long)(a_hi - a_lo),
                   (unsigned long long)(built * (uint64_t)sp->k),
                   (unsigned long long)((a_hi - a_lo - built) * (uint64_t)sp->k));
            ti += a_hi - a_lo;
            tc += built * (uint64_t)sp->k;
            ts += (a_hi - a_lo - built) * (uint64_t)sp->k;
        }
        start += sp->seg[i].count;
    }
    printf("total %llu %llu %llu\n", (unsigned long long)ti,
           (unsigned long long)tc, (unsigned long long)ts);
    printf("maxskip %llu\n", (unsigned long long)maxrun);
    return 0;
}

static int hard_known(const char *word)
{
    return hspace_of(word) != NULL;
}

/* The hard-case modes' run: <lo> <hi> over the mode's indices, attribute mi.
 * RMM rides the RNE oracle for the square root only, as everywhere here.
 * Returns 2 for a refusal (nothing was run), else soak_hard's status. */
static int hard_run(const char *word, const char *slo, const char *shi, int mi)
{
    const hspace *sp = hspace_of(word);
    uint64_t lo, hi;
    if (sp->op != OP_SQRT64 && !MODES[mi].native) {
        fprintf(stderr, "rmm is only checkable for sqrt (no native mode, "
                        "and division has real ties)\n");
        return 2;
    }
    if (hard_range(sp, slo, shi, &lo, &hi))
        return 2;
    return soak_hard(sp, lo, hi, mi);
}

#else  /* no 128-bit integer: the modes are named and refused, never approximated */

static int hard_unsupported(void)
{
    fprintf(stderr, "the hard-case modes need a 128-bit integer type "
                    "(__int128), which this compiler does not have\n");
    return 2;
}
static int hard_known(const char *word)
{
    return !strcmp(word, "div32-hard") || !strcmp(word, "div64-hard") ||
           !strcmp(word, "sqrt64-hard");
}
static int hard_run(const char *word, const char *slo, const char *shi, int mi)
{
    (void)word; (void)slo; (void)shi; (void)mi;
    return hard_unsupported();
}
static int hard_space_cmd(const char *mode)
{
    (void)mode;
    return hard_unsupported();
}
static int hard_dump_cmd(const char *mode, const char *slo, const char *shi)
{
    (void)mode; (void)slo; (void)shi;
    return hard_unsupported();
}
static int hard_count_cmd(const char *mode, const char *slo, const char *shi)
{
    (void)mode; (void)slo; (void)shi;
    return hard_unsupported();
}

#endif

#ifdef CFT_SOAK_MPFR
/* ================================================================
 * The wide formats: fp64, fp128 and fp256 (parcel HXa, 2026-10-26)
 *
 * Compiled in only by `make divsqrt-soak MPFR=1` (host/Makefile), which
 * defines CFT_SOAK_MPFR and links MPFR and GMP. Without it nothing below
 * exists, the tool is the one it was before, object for object, and a
 * wide mode word is an "unknown op" (exit 2). docs/studies/HX-wide-
 * sweeps.md section 6 row 1 is the specification; docs/CARDDAY.md names
 * the claim each mode's pass makes.
 *
 * THE ORACLE. At fp128 and fp256: MPFR, through mpfr_ieee.h, which is
 * mpfr-check's own IEEE emulation (moved there so both tools take the
 * one copy): the format's precision, the unbounded result as the
 * overflow and underflow authority, the flags by the oracle's own
 * arithmetic, RMM by a truncation to p + 1 bits. At fp64: the CPU's
 * double, as every fp64 mode here (native_batch); RMM rides its RNE
 * result, because neither a square root nor a reciprocal 1/x of a
 * widened fp32 value is ever a tie (a reciprocal is exact when x is a
 * power of two and otherwise not a dyadic rational at all).
 *
 * THE SECOND CHECK, by the ladder (the study's 4.1, rule R1). For the
 * modes whose inputs are narrow values widened exactly - the fp32
 * slice, and the fp64 hard operands - the library's wide result is
 * rounded back to the narrow format under the same attribute (the
 * rounding of an exact value, mpfr_ieee.h's ieee_round_into) and
 * compared with the CPU's own narrow operation: the value, and the
 * flags as the rounding's inexact, underflow and overflow with the
 * invalid and divideByZero the operand classes decide. p' >= 2p + 2
 * at every rung here, so the two must agree exactly; what the check
 * can see is the top 2p bits or so of the wide result (the study's
 * 4.1 says how little that is at fp128 and fp256), and that it is a
 * second lineage. Under rmm the narrow CPU result is its RNE one for
 * the square root and the reciprocal (no ties, as above); division of
 * the fp64 hard operands has real ties at fp64 (F3a) and no native
 * rmm, so there the ladder is not run under rmm, and says so.
 *
 * THE MODES. Each is `<lo> <hi> <attribute>` over its indices, all five
 * attributes, with the verdict line's ", E encodings, S skipped".
 *   sqrt{64,128,256}-f32, recip{64,128,256}-f32
 *       index = the fp32 encoding, [0, 2^32), widened exactly: every
 *       fp32 input, both signs, zeros, subnormals, infinities and NaNs
 *       (an sNaN widens to an sNaN). recip is 1 / x. k = 1, no skips.
 *   {sqrt,recip}{128,256}-win-{ones,zeros,alt,key}
 *       the low-bit windows: x = 1.H L in [1, 2), the low 32 fraction
 *       bits L = the index, the high ones H by name - all ones, all
 *       zeros, alternating from the top (1.0101...), and a keyed draw.
 *       k = 1, no skips. MPFR alone (no narrow value to ladder to).
 *   div{128,256}-f64hard, sqrt{128,256}-f64hard
 *       div64-hard's and sqrt64-hard's own indices and operands
 *       (hard_base above, unchanged), widened exactly; k and the skips
 *       are theirs. The ladder narrows to fp64.
 *   div{128,256}-hard, sqrt{128,256}-hard
 *       the hard-case families at p = 113 and 237 (python/hardcases.py
 *       holds the same spaces): the builders below, in GMP, with F1's
 *       odd parts and F0K's keyed low bits drawn from as many 64-bit
 *       words as p needs (the first word is the one the fp32 and fp64
 *       spaces draw, so those are unchanged), the F3a tie patterns'
 *       alternation carried past 64 bits likewise, and every F0 and S0
 *       case checked exactly as it is built. MPFR alone.
 * `hard-space`, `hard-dump` and `hard-count` take the four new spaces
 * and the four f64hard names (whose space is div64-hard's or
 * sqrt64-hard's).
 *
 * THE CONTROLS. CFT_SOAK_SABOTAGE=1 flips the low bit of the first
 * library result of every batch, as in every mode here: the primary
 * oracle must name it. CFT_SOAK_SABOTAGE=2 flips the low bit of the
 * first CPU narrow result of every batch instead: the ladder must name
 * it (lines "MISMATCH <attribute> ladder ...") while the primary
 * check passes.
 * ================================================================ */

#ifndef __SIZEOF_INT128__
#error "divsqrt-soak's wide modes (MPFR=1) use the hard-case builders, which need a 128-bit integer type (__int128)"
#endif

#include "mpfr_ieee.h"

#define WMAX 32                               /* fp256's bytes */
#define W_GOLDEN 0x9E3779B97F4A7C15ull        /* splitmix64's increment */
#define H_SALT_WIN 0xD1B54A32D192ED03ull      /* the keyed window's salt */

enum { WF32, WF64, WF128, WF256 };
static const fdesc WF[4] = {
    { "fp32",  CFT_FP32,   8,  23,  24,    127,    -126,  4 },
    { "fp64",  CFT_FP64,  11,  52,  53,   1023,   -1022,  8 },
    { "fp128", CFT_FP128, 15, 112, 113,  16383,  -16382, 16 },
    { "fp256", CFT_FP256, 19, 236, 237, 262143, -262142, 32 },
};
/* the attribute's MPFR rounding, by MODES index; RMM is the oracle's own build */
static const mpfr_rnd_t WMR[5] = { MPFR_RNDN, MPFR_RNDZ, MPFR_RNDD, MPFR_RNDU, MPFR_RNDN };

/* ---- the wide hard-case spaces (GMP builders) ---------------------- */

typedef struct {
    const char *mode;
    int div, wf, p, bias, k, nseg;
    struct { int fam; const char *name; uint64_t count; } seg[HMAXSEG];
} whspace;

static const whspace WHSPACES[] = {
    { "div128-hard", 1, WF128, 113, 16383, 4, 7, {
        { H_F3A, "F3a", 4u * 113 },
        { H_F3B, "F3b", 4u * (4 * 16383 - 1) },
        { H_F2,  "F2",  (uint64_t)4 << 16 },
        { H_F1,  "F1",  (uint64_t)4 << 20 },
        { H_F0A, "F0A", (uint64_t)4 << 21 },
        { H_F0D, "F0D", (uint64_t)4 << 21 },
        { H_F0K, "F0K", (uint64_t)4 << 26 } } },
    { "div256-hard", 1, WF256, 237, 262143, 4, 7, {
        { H_F3A, "F3a", 4u * 237 },
        { H_F3B, "F3b", 4u * (4 * 262143 - 1) },
        { H_F2,  "F2",  (uint64_t)4 << 16 },
        { H_F1,  "F1",  (uint64_t)4 << 20 },
        { H_F0A, "F0A", (uint64_t)4 << 21 },
        { H_F0D, "F0D", (uint64_t)4 << 21 },
        { H_F0K, "F0K", (uint64_t)4 << 26 } } },
    { "sqrt128-hard", 0, WF128, 113, 16383, 1, 2, {
        { H_S1,  "S1",  (uint64_t)4 << 16 },
        { H_S0,  "S0",  (uint64_t)4 << 20 } } },
    { "sqrt256-hard", 0, WF256, 237, 262143, 1, 2, {
        { H_S1,  "S1",  (uint64_t)4 << 16 },
        { H_S0,  "S0",  (uint64_t)4 << 20 } } },
};
#define NWHS ((int)(sizeof WHSPACES / sizeof WHSPACES[0]))

static const whspace *whspace_of(const char *mode)
{
    int i;
    for (i = 0; i < NWHS; i++)
        if (!strcmp(WHSPACES[i].mode, mode))
            return &WHSPACES[i];
    return NULL;
}

static uint64_t whspace_total(const whspace *sp)
{
    uint64_t t = 0;
    int i;
    for (i = 0; i < sp->nseg; i++)
        t += sp->seg[i].count;
    return t;
}

/* the builders' scratch: initialized once, reused (GMP grows them as needed) */
static mpz_t wz_p1, wz_pp, wz_a, wz_b, wz_t, wz_u, wz_d, wz_x, wz_my, wz_r;
static int wz_ready;

static void wz_init(void)
{
    if (wz_ready)
        return;
    mpz_init(wz_p1); mpz_init(wz_pp); mpz_init(wz_a); mpz_init(wz_b);
    mpz_init(wz_t); mpz_init(wz_u); mpz_init(wz_d); mpz_init(wz_x);
    mpz_init(wz_my); mpz_init(wz_r);
    wz_ready = 1;
}

/* The positive normal number sig * 2^(e - bias - (p-1)) of the space's
 * format, sig in [2^(p-1), 2^p), as its little-endian encoding. */
static void wenc(const whspace *sp, int64_t e, const mpz_t sig, uint8_t *out)
{
    mpz_t enc, ex;
    memset(out, 0, WMAX);
    if (e < 1 || e > 2 * (int64_t)sp->bias || mpz_sgn(sig) <= 0 ||
        mpz_sizeinbase(sig, 2) != (size_t)sp->p) {
        herr = 1;
        return;
    }
    mpz_init_set(enc, sig);
    mpz_clrbit(enc, (mp_bitcnt_t)(sp->p - 1));     /* the hidden bit: sig - 2^(p-1) */
    mpz_init_set_si(ex, (long)e);
    mpz_mul_2exp(ex, ex, (mp_bitcnt_t)(sp->p - 1));
    mpz_ior(enc, enc, ex);
    mpz_export(out, NULL, -1, 1, 0, 0, enc);
    mpz_clear(enc);
    mpz_clear(ex);
}

/* The exact value n 2^t, n a positive integer of at most p bits. */
static void wenc_int(const whspace *sp, const mpz_t n, int64_t t, uint8_t *out)
{
    int len = (int)mpz_sizeinbase(n, 2);
    mpz_t s;
    mpz_init(s);
    mpz_mul_2exp(s, n, (mp_bitcnt_t)(sp->p - len));
    wenc(sp, sp->bias + len - 1 + t, s, out);
    mpz_clear(s);
}

/* The top `nbits` bits of the words W0 W1 ... (W0 the most significant),
 * W_i = mix64(seed + i 2^64 / phi): splitmix64's stream from `seed`. For
 * nbits <= 64 it is W0 >> (64 - nbits), the one-word draw the fp32 and
 * fp64 spaces make. */
static void wdraw_top(mpz_t out, uint64_t seed, int nbits)
{
    int nw = (nbits + 63) / 64, i;
    mpz_set_ui(out, 0);
    for (i = 0; i < nw; i++) {
        uint64_t w = mix64(seed + (uint64_t)i * W_GOLDEN);
        /* in two halves: an unsigned long may be 32 bits */
        mpz_mul_2exp(out, out, 32);
        mpz_add_ui(out, out, (unsigned long)(w >> 32));
        mpz_mul_2exp(out, out, 32);
        mpz_add_ui(out, out, (unsigned long)(w & 0xffffffffu));
    }
    mpz_fdiv_q_2exp(out, out, (mp_bitcnt_t)(64 * nw - nbits));
}

/* The low `nbits` bits of the words W0 + W1 2^64 + ... (W0 the least
 * significant), W_i as above. For nbits <= 64 it is W0 masked, the
 * one-word draw. */
static void wdraw_low(mpz_t out, uint64_t seed, int nbits)
{
    int nw = (nbits + 63) / 64, i;
    mpz_set_ui(out, 0);
    for (i = nw - 1; i >= 0; i--) {
        uint64_t w = mix64(seed + (uint64_t)i * W_GOLDEN);
        mpz_mul_2exp(out, out, 32);
        mpz_add_ui(out, out, (unsigned long)(w >> 32));
        mpz_mul_2exp(out, out, 32);
        mpz_add_ui(out, out, (unsigned long)(w & 0xffffffffu));
    }
    mpz_fdiv_r_2exp(out, out, (mp_bitcnt_t)nbits);
}

/* The bits of even position below len: 0x...5555 carried as far as len
 * needs (0x5555555555555555 masked, for len <= 64). */
static void weven_bits(mpz_t out, int len)
{
    int i;
    mpz_set_ui(out, 0);
    for (i = 0; i < len; i += 2)
        mpz_setbit(out, (mp_bitcnt_t)i);
}

/* tie_pattern, at any length: all ones, 10..01, 1010..1, all ones but bit 1 */
static void wtie_pattern(mpz_t out, int len, int v)
{
    if (v == 0) {
        mpz_set_ui(out, 0);
        mpz_setbit(out, (mp_bitcnt_t)len);
        mpz_sub_ui(out, out, 1);
        return;
    }
    if (v == 2)
        weven_bits(out, len);
    else if (v == 3) {
        mpz_set_ui(out, 0);
        mpz_setbit(out, (mp_bitcnt_t)len);
        mpz_sub_ui(out, out, 1);
        mpz_clrbit(out, 1);
    } else
        mpz_set_ui(out, 0);
    mpz_setbit(out, (mp_bitcnt_t)(len - 1));
    mpz_setbit(out, 0);
}

static void wset_pow2(mpz_t out, int e)
{
    mpz_set_ui(out, 0);
    mpz_setbit(out, (mp_bitcnt_t)e);
}

/* The positive operands of an index of a wide space: 1 for a case, 0 for
 * a skip; herr set when an exact check fails or an operand would leave
 * the format. b is unused for the square root. */
static int whard_base(const whspace *sp, uint64_t idx, uint8_t *a, uint8_t *b)
{
    int p = sp->p, bias = sp->bias, s, v, fam = -1;
    uint64_t i0 = idx, j;
    wz_init();
    wset_pow2(wz_p1, p - 1);
    wset_pow2(wz_pp, p);
    for (s = 0; s < sp->nseg; s++) {
        if (i0 < sp->seg[s].count) { fam = sp->seg[s].fam; break; }
        i0 -= sp->seg[s].count;
    }
    j = i0 >> 2;
    v = (int)(i0 & 3);
    switch (fam) {
    case H_F3A: {
        int sd = (int)j + 1;
        wtie_pattern(wz_a, p - sd + 1, v);
        mpz_mul_2exp(wz_a, wz_a, (mp_bitcnt_t)(sd - 1));
        wenc(sp, 4, wz_a, a);
        wenc(sp, bias + sd + 3, wz_p1, b);
        return 1;
    }
    case H_F3B: {
        int64_t eq = (int64_t)j - (2 * (int64_t)bias - 1);
        int64_t ea = 1 + (eq > 0 ? eq : 0), eb = 1 + (eq < 0 ? -eq : 0);
        if (v == 0 || v == 2)
            mpz_sub_ui(wz_t, wz_pp, 1);
        else {
            wset_pow2(wz_t, p - 2);
            mpz_mul_ui(wz_t, wz_t, 3);
        }
        if (v < 2) { wenc(sp, ea, wz_t, a); wenc(sp, eb, wz_p1, b); }
        else       { wenc(sp, ea, wz_p1, a); wenc(sp, eb, wz_t, b); }
        return 1;
    }
    case H_F2: {
        unsigned long k = (unsigned long)(j + 1);
        if (v < 2)
            mpz_set(wz_t, wz_p1);
        else
            mpz_sub_ui(wz_t, wz_pp, 1);
        wenc(sp, bias, wz_t, a);
        if ((v & 1) == 0) {
            mpz_add_ui(wz_u, wz_p1, k);
            wenc(sp, bias, wz_u, b);
        } else {
            mpz_sub_ui(wz_u, wz_pp, k);
            wenc(sp, bias - 1, wz_u, b);
        }
        return 1;
    }
    case H_F1: {
        int h = (p - 1) / 2, e = bias / 3, tb3 = bias / 2, sh = p - 2;
        int64_t ta, tb;
        wdraw_top(wz_a, (2 * j) ^ H_SALT_F1, h - 1);          /* ob = 2 draw + 1 */
        mpz_mul_2exp(wz_a, wz_a, 1);
        mpz_add_ui(wz_a, wz_a, 1);
        wdraw_top(wz_b, (2 * j + 1) ^ H_SALT_F1, h - 1);      /* oq */
        mpz_mul_2exp(wz_b, wz_b, 1);
        mpz_add_ui(wz_b, wz_b, 1);
        ta = v == 0 ? 0 : v == 1 ? e : v == 2 ? -e : (int64_t)tb3 + (1 - bias) - sh;
        tb = v == 0 ? 0 : v == 1 ? -e : v == 2 ? e : tb3;
        mpz_mul(wz_t, wz_a, wz_b);
        wenc_int(sp, wz_t, ta, a);
        wenc_int(sp, wz_a, tb, b);
        return 1;
    }
    case H_F0A: case H_F0D: case H_F0K: {
        int target = v >> 1, plus = !(v & 1), kk = target == 0 ? p : p - 1;
        if (fam == H_F0A) {
            mpz_add_ui(wz_my, wz_p1, 1);
            mpz_set_ui(wz_t, (unsigned long)j);
            mpz_addmul_ui(wz_my, wz_t, 2);
        } else if (fam == H_F0D) {
            mpz_sub_ui(wz_my, wz_pp, 1);
            mpz_set_ui(wz_t, (unsigned long)j);
            mpz_submul_ui(wz_my, wz_t, 2);
        } else {
            wdraw_low(wz_my, j ^ H_SALT_F0K, p - 13);
            mpz_set_ui(wz_t, (unsigned long)((j * 2659) & 4095));
            mpz_mul_2exp(wz_t, wz_t, (mp_bitcnt_t)(p - 13));
            mpz_ior(wz_my, wz_my, wz_t);
            mpz_ior(wz_my, wz_my, wz_p1);
            mpz_setbit(wz_my, 0);
        }
        wset_pow2(wz_t, kk);
        mpz_mod(wz_t, wz_t, wz_my);
        if (!mpz_invert(wz_r, wz_t, wz_my)) { herr = 1; return 0; }
        if (!plus)
            mpz_sub(wz_r, wz_my, wz_r);
        mpz_add(wz_x, wz_r, wz_my);
        if (mpz_cmp(wz_x, wz_pp) < 0)
            mpz_set(wz_u, wz_x);
        else if (mpz_even_p(wz_x))
            mpz_fdiv_q_2exp(wz_u, wz_x, 1);
        else
            return 0;
        /* |N| = 1 and its sign, exactly: (x 2^p mod 2 my) = my +- 1 for the
         * midpoint, x 2^(p-1) = +-1 (mod my) for the representable target */
        if (target == 0) {
            mpz_mul_2exp(wz_t, wz_x, (mp_bitcnt_t)p);
            mpz_mul_2exp(wz_d, wz_my, 1);
            mpz_mod(wz_t, wz_t, wz_d);
            mpz_set(wz_d, wz_my);
            if (plus) mpz_add_ui(wz_d, wz_d, 1); else mpz_sub_ui(wz_d, wz_d, 1);
        } else {
            mpz_mul_2exp(wz_t, wz_x, (mp_bitcnt_t)(p - 1));
            mpz_mod(wz_t, wz_t, wz_my);
            if (plus) mpz_set_ui(wz_d, 1); else mpz_sub_ui(wz_d, wz_my, 1);
        }
        if (mpz_cmp(wz_t, wz_d) != 0) { herr = 1; return 0; }
        wenc(sp, bias, wz_u, a);
        wenc(sp, bias, wz_my, b);
        return 1;
    }
    case H_S1: {
        unsigned long k = (unsigned long)(2 * j + 1);
        if (v == 0)      { mpz_add_ui(wz_u, wz_p1, k); wenc(sp, bias, wz_u, a); }
        else if (v == 1) { mpz_sub_ui(wz_u, wz_pp, k); wenc(sp, bias + 1, wz_u, a); }
        else if (v == 2) { mpz_sub_ui(wz_u, wz_pp, k); wenc(sp, bias - 1, wz_u, a); }
        else             { mpz_add_ui(wz_u, wz_p1, k); wenc(sp, bias + 510, wz_u, a); }
        return 1;
    }
    case H_S0: {
        int par = v >> 1, r = v & 1, sh = p + 1 + par, nr = 0, i, c, bb;
        int64_t m = (j & 1) ? -(int64_t)((j + 1) >> 1) : (int64_t)(j >> 1);
        mpz_t rho, size, cand[4], root[4];
        mpz_init_set_si(rho, (long)(8 * m + 1));
        mpz_init(size);
        wset_pow2(size, sh);
        /* hensel(rho, p + 2): an odd u, u = 1 (mod 4), u^2 = rho (mod 2^(p+2)),
         * lifted one bit at a time; wz_d carries u^2 - rho */
        mpz_set_ui(wz_u, 1);
        mpz_ui_sub(wz_d, 1, rho);
        for (bb = 3; bb < p + 2; bb++)
            if (mpz_tstbit(wz_d, (mp_bitcnt_t)bb)) {
                /* (u + 2^(bb-1))^2 - rho = d + u 2^bb + 2^(2bb-2) */
                mpz_mul_2exp(wz_t, wz_u, (mp_bitcnt_t)bb);
                mpz_add(wz_d, wz_d, wz_t);
                wset_pow2(wz_t, 2 * bb - 2);
                mpz_add(wz_d, wz_d, wz_t);
                wset_pow2(wz_t, bb - 1);
                mpz_add(wz_u, wz_u, wz_t);
            }
        mpz_fdiv_r_2exp(wz_u, wz_u, (mp_bitcnt_t)(p + 2));
        for (i = 0; i < 4; i++) { mpz_init(cand[i]); mpz_init(root[i]); }
        mpz_fdiv_r_2exp(cand[0], wz_u, (mp_bitcnt_t)sh);              /* c0 */
        mpz_sub(cand[1], size, cand[0]);
        mpz_fdiv_r_2exp(cand[1], cand[1], (mp_bitcnt_t)sh);
        mpz_fdiv_q_2exp(wz_t, size, 1);
        mpz_add(cand[2], cand[0], wz_t);
        mpz_fdiv_r_2exp(cand[2], cand[2], (mp_bitcnt_t)sh);
        mpz_add(cand[3], cand[1], wz_t);
        mpz_fdiv_r_2exp(cand[3], cand[3], (mp_bitcnt_t)sh);
        wset_pow2(wz_x, 2 * p + 1);                                   /* lim */
        for (i = 0; i < 4; i++) {
            mpz_mul(wz_t, cand[i], cand[i]);
            if (mpz_sizeinbase(cand[i], 2) == (size_t)(p + 1) &&     /* in [2^p, 2^(p+1)) */
                ((mpz_cmp(wz_t, wz_x) < 0) == (par == 0))) {
                for (c = nr++; c > 0 && mpz_cmp(root[c - 1], cand[i]) > 0; c--)
                    mpz_set(root[c], root[c - 1]);
                mpz_set(root[c], cand[i]);
            }
        }
        if (r < nr) {
            mpz_mul(wz_t, root[r], root[r]);
            mpz_fdiv_r_2exp(wz_d, wz_t, (mp_bitcnt_t)sh);
            mpz_fdiv_r_2exp(wz_x, rho, (mp_bitcnt_t)sh);              /* rho mod 2^sh, nonnegative */
            if (mpz_cmp(wz_d, wz_x) != 0)
                herr = 1;
            else {
                wset_pow2(wz_x, sh - 1);
                mpz_add(wz_t, wz_t, wz_x);
                mpz_fdiv_q_2exp(wz_t, wz_t, (mp_bitcnt_t)sh);
                if (mpz_cmp(wz_t, wz_p1) >= 0 && mpz_cmp(wz_t, wz_pp) < 0) {
                    wenc(sp, bias + par, wz_t, a);
                    nr = -1;                                          /* a case */
                }
            }
        }
        for (i = 0; i < 4; i++) { mpz_clear(cand[i]); mpz_clear(root[i]); }
        mpz_clear(rho);
        mpz_clear(size);
        return nr == -1;
    }
    default:
        herr = 1;
        return 0;
    }
}

/* ---- the wide modes ------------------------------------------------- */

typedef enum { WK_SLICE, WK_WIN, WK_F64HARD, WK_HARD } wkind;

typedef struct {
    const char *mode;
    wkind kind;
    int div;          /* division (1 / x for the slice and the windows), or square root */
    int wf;           /* the format the operation runs at */
    int arg;          /* a window's H (0 ones, 1 zeros, 2 alt, 3 key) */
} wmode;

static const wmode WMODES[] = {
    { "sqrt64-f32",  WK_SLICE, 0, WF64, 0 },  { "sqrt128-f32",  WK_SLICE, 0, WF128, 0 },
    { "sqrt256-f32", WK_SLICE, 0, WF256, 0 }, { "recip64-f32",  WK_SLICE, 1, WF64, 0 },
    { "recip128-f32", WK_SLICE, 1, WF128, 0 }, { "recip256-f32", WK_SLICE, 1, WF256, 0 },
    { "sqrt128-win-ones", WK_WIN, 0, WF128, 0 }, { "sqrt128-win-zeros", WK_WIN, 0, WF128, 1 },
    { "sqrt128-win-alt", WK_WIN, 0, WF128, 2 },  { "sqrt128-win-key", WK_WIN, 0, WF128, 3 },
    { "sqrt256-win-ones", WK_WIN, 0, WF256, 0 }, { "sqrt256-win-zeros", WK_WIN, 0, WF256, 1 },
    { "sqrt256-win-alt", WK_WIN, 0, WF256, 2 },  { "sqrt256-win-key", WK_WIN, 0, WF256, 3 },
    { "recip128-win-ones", WK_WIN, 1, WF128, 0 }, { "recip128-win-zeros", WK_WIN, 1, WF128, 1 },
    { "recip128-win-alt", WK_WIN, 1, WF128, 2 },  { "recip128-win-key", WK_WIN, 1, WF128, 3 },
    { "recip256-win-ones", WK_WIN, 1, WF256, 0 }, { "recip256-win-zeros", WK_WIN, 1, WF256, 1 },
    { "recip256-win-alt", WK_WIN, 1, WF256, 2 },  { "recip256-win-key", WK_WIN, 1, WF256, 3 },
    { "div128-f64hard", WK_F64HARD, 1, WF128, 0 }, { "div256-f64hard", WK_F64HARD, 1, WF256, 0 },
    { "sqrt128-f64hard", WK_F64HARD, 0, WF128, 0 }, { "sqrt256-f64hard", WK_F64HARD, 0, WF256, 0 },
    { "div128-hard", WK_HARD, 1, WF128, 0 },  { "div256-hard", WK_HARD, 1, WF256, 0 },
    { "sqrt128-hard", WK_HARD, 0, WF128, 0 }, { "sqrt256-hard", WK_HARD, 0, WF256, 0 },
};
#define NWM ((int)(sizeof WMODES / sizeof WMODES[0]))

static const wmode *wmode_of(const char *mode)
{
    int i;
    for (i = 0; i < NWM; i++)
        if (!strcmp(WMODES[i].mode, mode))
            return &WMODES[i];
    return NULL;
}

/* the fp64 space an f64hard mode runs over */
static const hspace *wm_f64space(const wmode *wm)
{
    return hspace_of(wm->div ? "div64-hard" : "sqrt64-hard");
}

static uint64_t wm_total(const wmode *wm)
{
    if (wm->kind == WK_F64HARD)
        return hspace_total(wm_f64space(wm));
    if (wm->kind == WK_HARD)
        return whspace_total(whspace_of(wm->mode));
    return (uint64_t)1 << 32;
}

static int wm_k(const wmode *wm)
{
    if (wm->kind == WK_F64HARD)
        return wm_f64space(wm)->k;
    if (wm->kind == WK_HARD)
        return whspace_of(wm->mode)->k;
    return 1;
}

/* the narrow format the ladder rounds back to, or -1 for none */
static int wm_narrow(const wmode *wm)
{
    return wm->kind == WK_SLICE ? WF32 : wm->kind == WK_F64HARD ? WF64 : -1;
}

/* n (<= 64) bits of v into the little-endian encoding b at bit lo */
static void put_bits(uint8_t *b, int lo, int n, uint64_t v)
{
    int i;
    for (i = 0; i < n; i++) {
        int bit = lo + i;
        if ((v >> i) & 1) b[bit >> 3] |= (uint8_t)(1u << (bit & 7));
        else              b[bit >> 3] &= (uint8_t)~(1u << (bit & 7));
    }
}

/* The encoding of a narrow value (fp32 or fp64) in a wider format, exactly:
 * the same sign, a NaN's payload and quiet bit carried at the top of the
 * fraction (an sNaN stays an sNaN), a subnormal normalised. */
static void widen(const fdesc *N, const uint8_t *src, const fdesc *W, uint8_t *dst)
{
    uint64_t u = 0, frac, ex, emask = ((uint64_t)1 << N->exp_w) - 1;
    memcpy(&u, src, N->esz);
    frac = u & (((uint64_t)1 << N->man_w) - 1);
    ex = (u >> N->man_w) & emask;
    memset(dst, 0, WMAX);
    if (ex == emask) {
        put_bits(dst, W->man_w, W->exp_w, ((uint64_t)1 << W->exp_w) - 1);
        put_bits(dst, W->man_w - N->man_w, N->man_w, frac);
    } else if (ex != 0 || frac != 0) {
        uint64_t m = ex ? frac | ((uint64_t)1 << N->man_w) : frac;
        long e2 = ex ? (long)ex - N->emax - N->man_w : N->emin - N->man_w;
        int msb = bitlen(m) - 1;
        put_bits(dst, W->man_w - msb, msb, m & (((uint64_t)1 << msb) - 1));
        put_bits(dst, W->man_w, W->exp_w, (uint64_t)(e2 + msb + W->emax));
    }
    if ((u >> (8 * N->esz - 1)) & 1)
        put_bits(dst, 8 * (int)W->esz - 1, 1, 1);
}

/* x = 1.H L in [1, 2) at format W, L the index's 32 bits, H the window's:
 * all ones, all zeros, alternating from the top (1.0101...), or keyed */
static void window_x(const fdesc *W, int h, uint64_t L, uint8_t *dst)
{
    int hb = W->man_w - 32, i;
    memset(dst, 0, WMAX);
    put_bits(dst, 0, 32, L);
    for (i = 0; i < hb; i += 64) {
        int n = hb - i < 64 ? hb - i : 64;
        uint64_t w = h == 0 ? ~(uint64_t)0 : h == 1 ? 0 : h == 2 ? 0x5555555555555555ull :
                     mix64(H_SALT_WIN + (uint64_t)(i / 64) * W_GOLDEN);
        put_bits(dst, 32 + i, n, w);
    }
    put_bits(dst, W->man_w, W->exp_w, (uint64_t)W->emax);    /* biased exponent = bias: [1, 2) */
}

/* the batch: wide operands, library results, the fp64 oracle's results,
 * the narrow operands and the CPU's narrow results; MPFR's results and flags */
static uint8_t WA[BATCH * WMAX], WB[BATCH * WMAX], WD[BATCH * WMAX], WO[BATCH * 8];
static uint8_t NA[BATCH * 8], NB[BATCH * 8], NW[BATCH * 8];
static mpfr_t WOUT[BATCH];
static uint32_t WFL[BATCH];
static int wout_prec;
static int lsabotage = -1;
static uint64_t lcases, lmism, lflag;     /* the ladder's own count */

static cft_status wide_lib(const wmode *wm, int mi, const uint8_t *a, const uint8_t *b,
                           uint8_t *d, size_t n, uint32_t *fl)
{
    cft_format fmt = WF[wm->wf].fmt;
    cft_status st = wm->div ? cft_div(dev, fmt, MODES[mi].cr, a, b, d, n, fl, NULL)
                            : cft_sqrt(dev, fmt, MODES[mi].cr, a, d, n, fl, NULL);
    if (sabotage < 0) {
        const char *e = getenv("CFT_SOAK_SABOTAGE");
        sabotage = (e && *e == '1') ? 1 : 0;
    }
    if (st == CFT_OK && sabotage && n > 0)
        d[0] ^= 1u;
    return st;
}

static void hexw(const uint8_t *b, size_t n, char *out)
{
    out[0] = '0';
    out[1] = 'x';
    hexdump(b, n, out + 2);
}

/* one value disagreement, named: the operands, the library's result and the oracle's */
static void wide_report(const wmode *wm, int mi, const uint8_t *a, const uint8_t *b,
                        const uint8_t *got, const uint8_t *want64, mpfr_srcptr want)
{
    const fdesc *W = &WF[wm->wf];
    char ha[2 * WMAX + 3], hb[2 * WMAX + 3], hg[2 * WMAX + 3], hw[2 * WMAX + 3];
    if (shown++ >= 16)
        return;
    hexw(a, W->esz, ha);
    hexw(got, W->esz, hg);
    hb[0] = 0;
    if (wm->div)
        hexw(b, W->esz, hb);
    if (want64) {
        hexw(want64, 8, hw);
        printf("  MISMATCH %s a=%s%s%s lib=%s cpu=%s\n", MODES[mi].name, ha,
               wm->div ? " b=" : "", hb, hg, hw);
    } else {
        mpfr_printf("  MISMATCH %s a=%s%s%s lib=%s mpfr=%Ra\n", MODES[mi].name, ha,
                    wm->div ? " b=" : "", hb, hg, want);
    }
}

/* Element by element, a suspect batch: each element through the library
 * alone (n = 1), its value and flags against the oracle's for it. */
static void wide_recheck(const wmode *wm, int mi, size_t n)
{
    const fdesc *W = &WF[wm->wf];
    size_t e = W->esz, i;
    for (i = 0; i < n; i++) {
        uint8_t got[WMAX], w8[8];
        uint32_t lf = 0, of;
        int ok;
        const uint8_t *a = WA + i * e, *b = WB + i * e;
        if (wide_lib(wm, mi, a, b, got, 1, &lf) != CFT_OK)
            continue;
        if (wm->wf == WF64) {
            uint64_t g, w;
            of = native_batch(wm->div ? OP_DIV64 : OP_SQRT64, MODES[mi].fe, a,
                              wm->div ? b : NULL, w8, 1);
            memcpy(&g, got, 8);
            memcpy(&w, w8, 8);
            ok = agree64(g, w);
        } else {
            of = WFL[i];
            ok = agree(W, got, WOUT[i]);
        }
        if (!ok) {
            mismatches++;
            wide_report(wm, mi, a, b, got, wm->wf == WF64 ? w8 : NULL, WOUT[i]);
        }
        if (lf != of) {
            char ha[2 * WMAX + 3];
            flag_mismatches++;
            if (shown < 16) {
                hexw(a, e, ha);
                printf("  FLAGS %s a=%s%s lib=0x%02x %s=0x%02x\n", MODES[mi].name, ha,
                       wm->div ? " (div)" : "", (unsigned)lf,
                       wm->wf == WF64 ? "cpu" : "mpfr", (unsigned)of);
                shown++;
            }
        }
    }
}

/* invalid and divideByZero of the narrow operation, from its operands' classes */
static uint32_t class_flags(const fdesc *N, int div, const uint8_t *a, const uint8_t *b)
{
    cls ca, cb;
    classify(N, a, &ca);
    if (!div)
        return (ca.is_snan || (ca.sign && !ca.is_zero && !ca.is_nan)) ? CFT_FLAG_INVALID : 0;
    classify(N, b, &cb);
    if (ca.is_snan || cb.is_snan)
        return CFT_FLAG_INVALID;
    if (ca.is_nan || cb.is_nan)
        return 0;
    if ((ca.is_zero && cb.is_zero) || (ca.is_inf && cb.is_inf))
        return CFT_FLAG_INVALID;
    if (cb.is_zero && !ca.is_inf)
        return CFT_FLAG_DIVBYZERO;
    return 0;
}

/* The ladder's view of element i: the library's wide result rounded to the
 * narrow format under the attribute (R1: that rounding's flags, with the
 * operand classes' invalid and divideByZero). */
static uint32_t ladder_one(const wmode *wm, int mi, size_t i, mpfr_t x, mpfr_t out)
{
    const fdesc *W = &WF[wm->wf], *N = &WF[wm_narrow(wm)];
    const uint8_t *d = WD + i * W->esz;
    uint32_t fl = class_flags(N, wm->div, NA + i * N->esz, NB + i * N->esz), f2 = 0;
    cls c;
    classify(W, d, &c);
    mpfr_set_prec(out, N->p);
    if (c.is_nan)
        mpfr_set_nan(out);
    else if (c.is_inf)
        mpfr_set_inf(out, c.sign ? -1 : 1);
    else if (c.is_zero)
        mpfr_set_zero(out, c.sign ? -1 : 1);
    else {
        enc_to_mpfr(W, d, x);
        ieee_round_into(N, x, WMR[mi], mi == 4, out, &f2);
    }
    return fl | f2;
}

static void ladder_report(const wmode *wm, int mi, size_t i, mpfr_srcptr narrowed, const uint8_t *cpu,
                          int flags_only, uint32_t lf, uint32_t cf)
{
    const fdesc *N = &WF[wm_narrow(wm)];
    char ha[19], hb[19], hc[19];
    if (shown++ >= 16)
        return;
    hexw(NA + i * N->esz, N->esz, ha);
    hexw(cpu, N->esz, hc);
    hb[0] = 0;
    if (wm->div)
        hexw(NB + i * N->esz, N->esz, hb);
    if (flags_only)
        printf("  FLAGS %s ladder a=%s%s%s narrowed=0x%02x cpu=0x%02x\n", MODES[mi].name, ha,
               wm->div ? " b=" : "", hb, (unsigned)lf, (unsigned)cf);
    else
        mpfr_printf("  MISMATCH %s ladder a=%s%s%s narrowed=%Ra cpu=%s\n", MODES[mi].name, ha,
                    wm->div ? " b=" : "", hb, narrowed, hc);
}

/* The second check of a batch: every element's narrowed result against the
 * CPU's own narrow operation, flags per batch and then per element. */
static void wide_ladder(const wmode *wm, int mi, size_t n)
{
    const fdesc *W = &WF[wm->wf], *N = &WF[wm_narrow(wm)];
    soak_op nop = N->esz == 4 ? (wm->div ? OP_DIV32 : OP_SQRT32) : (wm->div ? OP_DIV64 : OP_SQRT64);
    size_t ne = N->esz, i;
    uint32_t cf, lf = 0;
    int bad = 0;
    mpfr_t x, out;
    if (lsabotage < 0) {
        const char *e = getenv("CFT_SOAK_SABOTAGE");
        lsabotage = (e && e[0] == '2' && !e[1]) ? 1 : 0;
    }
    mpfr_init2(x, W->p);
    mpfr_init2(out, N->p);
    cf = native_batch(nop, MODES[mi].fe, NA, wm->div ? NB : NULL, NW, n);
    if (lsabotage && n > 0)
        NW[0] ^= 1u;
    for (i = 0; i < n; i++) {
        lf |= ladder_one(wm, mi, i, x, out);
        if (!agree(N, NW + i * ne, out))
            bad = 1;
    }
    if (lf != cf)
        bad = 1;
    if (bad) {
        for (i = 0; i < n; i++) {
            uint8_t w[8];
            uint32_t l1 = ladder_one(wm, mi, i, x, out);
            uint32_t c1 = native_batch(nop, MODES[mi].fe, NA + i * ne, wm->div ? NB + i * ne : NULL,
                                       w, 1);
            if (lsabotage)
                w[0] ^= 1u;
            if (!agree(N, w, out)) {
                mismatches++;
                lmism++;
                ladder_report(wm, mi, i, out, w, 0, 0, 0);
            }
            if (l1 != c1) {
                flag_mismatches++;
                lflag++;
                ladder_report(wm, mi, i, out, w, 1, l1, c1);
            }
        }
    }
    lcases += n;
    mpfr_clear(x);
    mpfr_clear(out);
}

static int wide_batch(const wmode *wm, int mi, size_t n)
{
    const fdesc *W = &WF[wm->wf];
    size_t e = W->esz, i;
    uint32_t of = 0, lf = 0;
    int bad = 0;
    mop op = wm->div ? OP_DIV : OP_SQRT;
    if (wm->wf == WF64)
        of = native_batch(wm->div ? OP_DIV64 : OP_SQRT64, MODES[mi].fe, WA, wm->div ? WB : NULL, WO, n);
    else
        for (i = 0; i < n; i++) {
            ieee_oracle(W, op, WMR[mi], mi == 4, WA + i * e, wm->div ? WB + i * e : WA + i * e,
                        WA + i * e, WOUT[i], &WFL[i]);
            of |= WFL[i];
        }
    if (wide_lib(wm, mi, WA, WB, WD, n, &lf) != CFT_OK) {
        printf("  library call failed\n");
        return 1;
    }
    for (i = 0; i < n && !bad; i++) {
        if (wm->wf == WF64) {
            uint64_t g, w;
            memcpy(&g, WD + i * 8, 8);
            memcpy(&w, WO + i * 8, 8);
            bad = !agree64(g, w);
        } else
            bad = !agree(W, WD + i * e, WOUT[i]);
    }
    if (lf != of)
        bad = 1;
    if (bad)
        wide_recheck(wm, mi, n);
    cases += n;
    if (wm_narrow(wm) >= 0 && !(wm->div && wm->kind == WK_F64HARD && mi == 4))
        wide_ladder(wm, mi, n);
    return 0;
}

/* The operands of an index, positive where the slots sign them: wide ones
 * into wa/wb, the narrow ones the ladder needs into na/nb. 1 for a case, 0
 * for a skip; herr on a failed exact check. */
static int wide_base(const wmode *wm, uint64_t idx, uint8_t *wa, uint8_t *wb, uint8_t *na,
                     uint8_t *nb)
{
    const fdesc *W = &WF[wm->wf];
    static const uint8_t one32[4] = { 0x00, 0x00, 0x80, 0x3f };
    uint8_t *x = wm->div ? wb : wa;
    switch (wm->kind) {
    case WK_SLICE: {
        uint32_t u = (uint32_t)idx;
        uint8_t *nx = wm->div ? nb : na;
        memcpy(nx, &u, 4);
        widen(&WF[WF32], nx, W, x);
        if (wm->div) {
            memcpy(na, one32, 4);
            widen(&WF[WF32], na, W, wa);
        }
        return 1;
    }
    case WK_WIN:
        window_x(W, wm->arg, idx, x);
        if (wm->div)
            widen(&WF[WF32], one32, W, wa);
        return 1;
    case WK_F64HARD: {
        uint64_t a = 0, b = 0;
        if (!hard_base(wm_f64space(wm), idx, &a, &b))
            return 0;
        memcpy(na, &a, 8);
        memcpy(nb, &b, 8);
        widen(&WF[WF64], na, W, wa);
        if (wm->div)
            widen(&WF[WF64], nb, W, wb);
        return 1;
    }
    default:
        return whard_base(whspace_of(wm->mode), idx, wa, wb);
    }
}

static int wide_range(const char *mode, uint64_t total, const char *slo, const char *shi,
                      uint64_t *lo, uint64_t *hi)
{
    char *e1, *e2;
    *lo = strtoull(slo, &e1, 0);
    *hi = strtoull(shi, &e2, 0);
    if (!*slo || !*shi || *e1 || *e2 || *slo == '-' || *shi == '-' || *lo >= *hi || *hi > total) {
        fprintf(stderr, "need 0 <= lo < hi <= %llu (the indices of %s), got [%s, %s)\n",
                (unsigned long long)total, mode, slo, shi);
        return 1;
    }
    return 0;
}

static int wide_soak(const wmode *wm, uint64_t lo, uint64_t hi, int mi)
{
    const fdesc *W = &WF[wm->wf];
    int k = wm_k(wm), nf = wm_narrow(wm), sl, rc = 0, i;
    size_t n = 0, e = W->esz, ne = nf >= 0 ? WF[nf].esz : 0;
    uint64_t idx;
    uint8_t a[WMAX], b[WMAX], na[8], nb[8];
    if (wout_prec != W->p) {
        for (i = 0; i < BATCH; i++) {
            if (wout_prec)
                mpfr_set_prec(WOUT[i], W->p);
            else
                mpfr_init2(WOUT[i], W->p);
        }
        wout_prec = W->p;
    }
    memset(a, 0, sizeof a);
    memset(b, 0, sizeof b);
    memset(na, 0, sizeof na);
    memset(nb, 0, sizeof nb);
    for (idx = lo; idx < hi && !rc; idx++) {
        int ok;
        if (n + (size_t)k > BATCH) {
            rc = wide_batch(wm, mi, n);
            n = 0;
            if (rc)
                break;
        }
        hencodings++;
        ok = wide_base(wm, idx, a, b, na, nb);
        if (herr) {
            fprintf(stderr, "%s: the exact check of index %llu failed, or it built an operand "
                    "outside the format - the construction is broken, not the library\n",
                    wm->mode, (unsigned long long)idx);
            return 2;
        }
        if (!ok) {
            hskipped += (uint64_t)k;
            continue;
        }
        for (sl = 0; sl < k; sl++, n++) {
            /* the slot's signs, where an index makes four: s = sign(a) + 2 sign(b) */
            memcpy(WA + n * e, a, e);
            memcpy(WB + n * e, b, e);
            if (k == 4 && (sl & 1)) WA[n * e + e - 1] |= 0x80;
            if (k == 4 && (sl & 2)) WB[n * e + e - 1] |= 0x80;
            if (nf >= 0) {
                memcpy(NA + n * ne, na, ne);
                memcpy(NB + n * ne, nb, ne);
                if (k == 4 && (sl & 1)) NA[n * ne + ne - 1] |= 0x80;
                if (k == 4 && (sl & 2)) NB[n * ne + ne - 1] |= 0x80;
            }
        }
    }
    if (!rc && n)
        rc = wide_batch(wm, mi, n);
    if (!rc && !cases && hi - lo >= HMIN_REFUSE) {
        fprintf(stderr, "%s: every one of the %llu indices of [%llu, %llu) skipped - a run of skips "
                "that long is a broken construction, not an empty region; refused\n", wm->mode,
                (unsigned long long)(hi - lo), (unsigned long long)lo, (unsigned long long)hi);
        return 2;
    }
    return rc;
}

/* A wide mode's run: 2 for a refusal (nothing was run), else wide_soak's status. */
static int wide_run(const wmode *wm, const char *slo, const char *shi, int mi)
{
    uint64_t lo, hi;
    int rc, nf = wm_narrow(wm);
    if (wide_range(wm->mode, wm_total(wm), slo, shi, &lo, &hi))
        return 2;
    if (wm->wf == WF64)
        fprintf(stderr, "oracle: the CPU's double%s; the ladder: the CPU's float\n",
                mi == 4 ? " (rmm rides its rne result: no ties)" : "");
    else
        fprintf(stderr, "oracle: MPFR %s with GMP %s, mpfr_ieee.h's emulation%s\n",
                mpfr_get_version(), gmp_version,
                nf < 0 ? "" : nf == WF32 ? "; the ladder: the CPU's float"
                : wm->div && mi == 4 ? "; the ladder: not under rmm for division (fp64 has ties, "
                                       "the CPU no rmm)"
                : "; the ladder: the CPU's double");
    rc = wide_soak(wm, lo, hi, mi);
    if (rc == 2)
        return 2;
    if (nf >= 0)
        printf("  ladder: %llu of the %llu cases rounded to %s and checked against the CPU's own, "
               "%llu value and %llu flag disagreements\n", (unsigned long long)lcases,
               (unsigned long long)cases, WF[nf].name, (unsigned long long)lmism,
               (unsigned long long)lflag);
    return rc;
}

/* ---- hard-space, hard-dump and hard-count for the new names ---------
 * Every new mode word is taken. The slice and window spaces are one
 * segment of 2^32 indices, k = 1, none skipped: "fp32" (the encoding) and
 * "L" (the low 32 bits); their dump prints the wide operand (the dividend
 * 1 and the divisor x for the reciprocal). The f64hard names are their
 * fp64 space's, operands in fp64 as the fp64 modes dump them. */

static int wide_hard_known(const char *mode)
{
    return wmode_of(mode) != NULL;
}

static const char *wm_segname(const wmode *wm)
{
    return wm->kind == WK_SLICE ? "fp32" : "L";
}

static int whard_space_cmd(const char *mode)
{
    const wmode *wm = wmode_of(mode);
    uint64_t start = 0;
    int i;
    if (wm->kind == WK_SLICE || wm->kind == WK_WIN) {
        printf("%s k=1 total=%llu\n%s 0 %llu\n", mode, (unsigned long long)wm_total(wm),
               wm_segname(wm), (unsigned long long)wm_total(wm));
    } else if (wm->kind == WK_F64HARD) {
        const hspace *sp = wm_f64space(wm);
        printf("%s k=%d total=%llu\n", mode, sp->k, (unsigned long long)hspace_total(sp));
        for (i = 0; i < sp->nseg; i++) {
            printf("%s %llu %llu\n", sp->seg[i].name, (unsigned long long)start,
                   (unsigned long long)sp->seg[i].count);
            start += sp->seg[i].count;
        }
    } else {
        const whspace *sp = whspace_of(mode);
        printf("%s k=%d total=%llu\n", mode, sp->k, (unsigned long long)whspace_total(sp));
        for (i = 0; i < sp->nseg; i++) {
            printf("%s %llu %llu\n", sp->seg[i].name, (unsigned long long)start,
                   (unsigned long long)sp->seg[i].count);
            start += sp->seg[i].count;
        }
    }
    return 0;
}

static int whard_dump_cmd(const char *mode, const char *slo, const char *shi)
{
    const wmode *wm = wmode_of(mode);
    const whspace *sp;
    uint64_t lo, hi, idx;
    uint8_t a[WMAX], b[WMAX];
    char ha[2 * WMAX + 3], hb[2 * WMAX + 3];
    int sl;
    size_t e;
    if (wm->kind == WK_F64HARD)
        return hard_dump_cmd(wm->div ? "div64-hard" : "sqrt64-hard", slo, shi);
    if (wm->kind == WK_SLICE || wm->kind == WK_WIN) {
        uint8_t na[8], nb[8];
        e = WF[wm->wf].esz;
        if (wide_range(mode, wm_total(wm), slo, shi, &lo, &hi))
            return 2;
        for (idx = lo; idx < hi; idx++) {
            wide_base(wm, idx, a, b, na, nb);
            hexw(a, e, ha);
            if (wm->div) {
                hexw(b, e, hb);
                printf("%llu 0 %s %s\n", (unsigned long long)idx, ha, hb);
            } else
                printf("%llu 0 %s\n", (unsigned long long)idx, ha);
        }
        return 0;
    }
    sp = whspace_of(mode);
    e = WF[sp->wf].esz;
    if (wide_range(mode, whspace_total(sp), slo, shi, &lo, &hi))
        return 2;
    for (idx = lo; idx < hi; idx++) {
        int ok = whard_base(sp, idx, a, b);
        if (herr) {
            fprintf(stderr, "%s: the exact check of index %llu failed\n", mode,
                    (unsigned long long)idx);
            return 2;
        }
        for (sl = 0; sl < sp->k; sl++) {
            uint8_t sa[WMAX], sb[WMAX];
            if (!ok) {
                printf("%llu %d skip\n", (unsigned long long)idx, sl);
                continue;
            }
            memcpy(sa, a, WMAX);
            memcpy(sb, b, WMAX);
            if (sl & 1) sa[e - 1] |= 0x80;
            if (sl & 2) sb[e - 1] |= 0x80;
            hexw(sa, e, ha);
            if (sp->k == 1) {
                printf("%llu %d %s\n", (unsigned long long)idx, sl, ha);
                continue;
            }
            hexw(sb, e, hb);
            printf("%llu %d %s %s\n", (unsigned long long)idx, sl, ha, hb);
        }
    }
    return 0;
}

static int whard_count_cmd(const char *mode, const char *slo, const char *shi)
{
    const wmode *wm = wmode_of(mode);
    const whspace *sp;
    uint64_t lo, hi, start = 0, ti = 0, tc = 0, ts = 0, run = 0, maxrun = 0;
    uint8_t a[WMAX], b[WMAX];
    int i;
    if (wm->kind == WK_F64HARD)
        return hard_count_cmd(wm->div ? "div64-hard" : "sqrt64-hard", slo, shi);
    if (wm->kind == WK_SLICE || wm->kind == WK_WIN) {
        if (wide_range(mode, wm_total(wm), slo, shi, &lo, &hi))
            return 2;
        printf("%s %llu %llu 0\ntotal %llu %llu 0\nmaxskip 0\n", wm_segname(wm),
               (unsigned long long)(hi - lo), (unsigned long long)(hi - lo),
               (unsigned long long)(hi - lo), (unsigned long long)(hi - lo));
        return 0;
    }
    sp = whspace_of(mode);
    if (wide_range(mode, whspace_total(sp), slo, shi, &lo, &hi))
        return 2;
    for (i = 0; i < sp->nseg; i++) {
        uint64_t a_lo = lo > start ? lo : start, idx, built = 0;
        uint64_t a_hi = hi < start + sp->seg[i].count ? hi : start + sp->seg[i].count;
        if (a_lo < a_hi) {
            for (idx = a_lo; idx < a_hi; idx++) {
                int ok = whard_base(sp, idx, a, b);
                if (herr) {
                    fprintf(stderr, "%s: the exact check of index %llu failed\n", mode,
                            (unsigned long long)idx);
                    return 2;
                }
                built += (uint64_t)ok;
                run = ok ? 0 : run + 1;
                if (run > maxrun)
                    maxrun = run;
            }
            printf("%s %llu %llu %llu\n", sp->seg[i].name, (unsigned long long)(a_hi - a_lo),
                   (unsigned long long)(built * (uint64_t)sp->k),
                   (unsigned long long)((a_hi - a_lo - built) * (uint64_t)sp->k));
            ti += a_hi - a_lo;
            tc += built * (uint64_t)sp->k;
            ts += (a_hi - a_lo - built) * (uint64_t)sp->k;
        }
        start += sp->seg[i].count;
    }
    printf("total %llu %llu %llu\n", (unsigned long long)ti, (unsigned long long)tc,
           (unsigned long long)ts);
    printf("maxskip %llu\n", (unsigned long long)maxrun);
    return 0;
}

static void wide_usage(const char *argv0)
{
    fprintf(stderr,
        "       %s sqrt64-f32|sqrt128-f32|sqrt256-f32|recip64-f32|recip128-f32|recip256-f32 "
        "<lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
        "       %s {sqrt,recip}{128,256}-win-{ones,zeros,alt,key} <lo> <hi> "
        "<rne|rtz|rdn|rup|rmm>\n"
        "       %s {div,sqrt}{128,256}-hard|{div,sqrt}{128,256}-f64hard <lo> <hi> "
        "<rne|rtz|rdn|rup|rmm>\n"
        "       %s hard-space|hard-dump|hard-count {div,sqrt}{128,256}-{hard,f64hard} "
        "[<lo> <hi>]\n"
        "       (the wide modes, built with MPFR %s)\n",
        argv0, argv0, argv0, argv0, mpfr_get_version());
}

#endif /* CFT_SOAK_MPFR */

int main(int argc, char **argv)
{
    int mi, rc = 1;
#ifdef CFT_SOAK_MPFR
    const wmode *wm = argc == 5 ? wmode_of(argv[1]) : NULL;
    if (argc >= 3 && wide_hard_known(argv[2])) {
        if (argc == 3 && !strcmp(argv[1], "hard-space"))
            return whard_space_cmd(argv[2]);
        if (argc == 5 && !strcmp(argv[1], "hard-dump"))
            return whard_dump_cmd(argv[2], argv[3], argv[4]);
        if (argc == 5 && !strcmp(argv[1], "hard-count"))
            return whard_count_cmd(argv[2], argv[3], argv[4]);
    }
#endif
    if (argc == 3 && !strcmp(argv[1], "hard-space"))
        return hard_space_cmd(argv[2]);
    if (argc == 5 && !strcmp(argv[1], "hard-dump"))
        return hard_dump_cmd(argv[2], argv[3], argv[4]);
    if (argc == 5 && !strcmp(argv[1], "hard-count"))
        return hard_count_cmd(argv[2], argv[3], argv[4]);
    if (argc != 5) {
        fprintf(stderr,
            "usage: %s sqrt32 <lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
            "       %s div32|div64|sqrt64 <count> <seed> <rne|rtz|rdn|rup>\n"
            "       %s div32-hard|div64-hard <lo> <hi> <rne|rtz|rdn|rup>\n"
            "       %s sqrt64-hard <lo> <hi> <rne|rtz|rdn|rup|rmm>\n"
            "       %s hard-space <div32-hard|div64-hard|sqrt64-hard>\n"
            "       %s hard-dump <div32-hard|div64-hard|sqrt64-hard> "
            "<lo> <hi>\n"
            "       %s hard-count <div32-hard|div64-hard|sqrt64-hard> "
            "<lo> <hi>\n",
            argv[0], argv[0], argv[0], argv[0], argv[0], argv[0], argv[0]);
#ifdef CFT_SOAK_MPFR
        wide_usage(argv[0]);
#endif
        return 2;
    }
    mi = mode_index(argv[4]);
    if (mi < 0) {
        fprintf(stderr, "unknown rounding mode %s\n", argv[4]);
        return 2;
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
#if BATCH != 4096 || CFT_CHUNK != 4096
        /* A build that moved the call size or the library's pass size says
         * so, on a line of its own: the line above is parsed by
         * hw/card_stress_lib.py and stays as it was, and a default build
         * compiles this out and prints nothing more. */
        fprintf(stderr, "soaking with BATCH %lu and CFT_CHUNK %lu "
                "(the defaults are 4096)\n",
                (unsigned long)BATCH, (unsigned long)CFT_CHUNK);
#endif
    }

#ifdef CFT_SOAK_MPFR
    if (wm) {
        /* the wide modes: <lo> <hi> over the mode's indices, all five attributes */
        hard_mode = 1;
        rc = wide_run(wm, argv[2], argv[3], mi);
        if (rc == 2) {
            cft_close(dev);
            return 2;
        }
    } else
#endif
    if (!strcmp(argv[1], "sqrt32")) {
        uint64_t lo = strtoull(argv[2], NULL, 0);
        uint64_t hi = strtoull(argv[3], NULL, 0);
        rc = soak_sqrt32(lo, hi, mi);
    } else if (hard_known(argv[1])) {
        /* the hard-case modes: <lo> <hi> over the mode's indices */
        hard_mode = 1;
        rc = hard_run(argv[1], argv[2], argv[3], mi);
        if (rc == 2) {
            cft_close(dev);
            return 2;
        }
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

    if (hard_mode)
        printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
               "mismatches, %llu encodings, %llu skipped\n", argv[1], argv[4],
               (unsigned long long)cases, (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches,
               (unsigned long long)hencodings, (unsigned long long)hskipped);
    else
        printf("%s %s: %llu cases, %llu value mismatches, %llu flag "
               "mismatches\n", argv[1], argv[4], (unsigned long long)cases,
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
    cft_close(dev);
    if (rc || mismatches || flag_mismatches)
        return 1;
    return 0;
}
