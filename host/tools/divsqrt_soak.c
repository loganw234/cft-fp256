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

int main(int argc, char **argv)
{
    int mi, rc = 1;
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
