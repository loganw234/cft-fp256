/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The transcendental set: phase 1's exp, expm1, exp2, log, log1p,
 * log2, log10, pow and hypot, and phase 2's sinPi, cosPi, tanPi, asin,
 * acos, atan, atan2, asinPi, acosPi, atanPi and atan2Pi - correctly
 * rounded at all four formats under all five rounding attributes, with
 * the 754-2019 clause 9.2 special values and the contract's exact
 * flags.
 *
 * Phase 2 is the part of clause 9 whose argument reduction is EXACT.
 * sinPi reduces by x mod 2 and x is a dyadic rational, so the
 * reduction is a mask on the encoding at every magnitude; the inverse
 * functions have nothing to reduce and meet pi only as a factor of the
 * answer. sin, cos and tan of a radian argument - the reduction
 * against pi itself - are not here.
 *
 * python/cft_golden/transcend.py is the definition of every bit here,
 * and the correspondence is deliberate: the same special-value order,
 * the same exact-case tests, the same neighbour rules, the same
 * working-precision schedule and the same cap. Where the model
 * evaluates a rigorous enclosure with mpmath's interval context, this
 * evaluates one with mpfloat.c's tracked error bound; the decision
 * procedure - round both ends, accept only when they agree on the bits
 * AND the flags - is identical, which is why the two agree without
 * either being a transliteration of the other.
 *
 * ---------------------------------------------------------------
 * The shape of a call
 * ---------------------------------------------------------------
 *
 * Every entry point is HOST work: no cft_run pass is issued, no bus
 * word is produced, and the device argument is context. That is not a
 * placeholder - it is the right first design. These are not opcodes
 * and cannot be composed from opcodes the way cft_div is: division
 * has an exactly measurable residual (a - q*b is one fused multiply
 * away and is exact), so a composed sequence can DECIDE its own last
 * bit. exp has no such residual. Nothing an FMA can compute tells you
 * which side of a rounding boundary e^x falls on; only more precision
 * does, and more precision means a multiprecision evaluator, which is
 * integer work. A tile-assisted fast path for the narrow formats is a
 * later optimisation and would have to reproduce these bits exactly.
 *
 * Per element:
 *
 *   1. The special-value tables (clause 9.2.1), which outrank
 *      everything - including, for pow, a quiet NaN operand.
 *   2. The exact cases, decided by exact integer arithmetic and packed
 *      through round_pack, so an exact result raises nothing and an
 *      exact value too large or too small to represent still gets
 *      clause 7's flags.
 *   3. The screens: a result provably past the format's thresholds is
 *      delivered as an overflow or underflow response without
 *      evaluating anything, which is also what keeps exp from ever
 *      being asked for e^(2^262143).
 *   4. The neighbour rules: an argument so small that the result
 *      cannot be separated from a representable neighbour by ANY
 *      working precision is decided by its side instead. Without these
 *      log1p(2^-1074) does not terminate.
 *   5. Otherwise the Ziv loop over mpfloat.c.
 *
 * Reaching the cap in step 5 returns CFT_ERR_INTERNAL. That is the
 * contract: an input that cannot be shown correctly rounded gets a
 * status, never a plausible number.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "mpfloat.h"
#include "softfloat.h"
#include "transcend.h"

/* Instrumentation. Not API - statically linked tools read it, which is
 * how docs/TRANSCENDENTALS.md's escalation numbers are measured rather
 * than asserted. */
uint64_t cft_tr_calls;
uint64_t cft_tr_ziv_calls;
uint64_t cft_tr_escalations;
uint64_t cft_tr_max_prec;
uint64_t cft_tr_exact;
uint64_t cft_tr_neighbour;
uint64_t cft_tr_reduce_calls;
uint64_t cft_tr_reduce_widen;
uint64_t cft_tr_max_window;
uint64_t cft_tr_max_cancel;

void cft_tr_reset_stats(void)
{
    cft_tr_calls = 0;
    cft_tr_ziv_calls = 0;
    cft_tr_escalations = 0;
    cft_tr_max_prec = 0;
    cft_tr_exact = 0;
    cft_tr_neighbour = 0;
    cft_tr_reduce_calls = 0;
    cft_tr_reduce_widen = 0;
    cft_tr_max_window = 0;
    cft_tr_max_cancel = 0;
}

/* ---- the working-precision schedule (mirrors the model) ----------- */

/* The first attempt's precision, and an override for tests only.
 *
 * CFT_TRANSCEND_MINPREC lowers it so that the escalation path runs at
 * all: in ordinary use this loop has never escalated once - 95,680
 * elements through the MPFR campaign and 76,115 through the model
 * check, zero escalations between them - and a path never taken is a
 * path never tested. It cannot change a result: a rounding the
 * enclosure decides at some precision is decided the same way at every
 * higher one, because raising the precision only narrows the
 * enclosure. host/tests/transcend_check.py --min-prec proves that by
 * replaying the whole sweep with it set. */
static int tr_start_prec(const cft_fmt_desc *f)
{
    static int probed, forced;
    if (!probed) {
        const char *e = getenv("CFT_TRANSCEND_MINPREC");
        probed = 1;
        forced = e ? atoi(e) : 0;
    }
    if (forced > 0) {
        int cap = 8 * f->prec + 128;
        int lo = f->prec / 2 > 64 ? f->prec / 2 : 64;
        if (cap > CFT_TR_PREC_CAP_CEILING)
            cap = CFT_TR_PREC_CAP_CEILING;
        if (forced > cap)
            return cap;
        return forced < lo ? lo : forced;
    }
    return 2 * f->prec + 40;
}

static int tr_prec_cap(const cft_fmt_desc *f)
{
    int c = 8 * f->prec + 128;
    return c < CFT_TR_PREC_CAP_CEILING ? c : CFT_TR_PREC_CAP_CEILING;
}

/* Headroom for the argument-reduction multiple: k in t = k*ln2 + r,
 * or the binade exponent E in log. Both are bounded by emax + man_w,
 * and the constant they multiply must be that many bits sharper. */
static int tr_headroom(const cft_fmt_desc *f)
{
    int v = f->emax + f->man_w + 2, n = 0;
    while (v) { n++; v >>= 1; }
    return n;
}

static int tr_wint(const cft_fmt_desc *f, int W)
{
    int w = W + 32 + tr_headroom(f);
    return w > CFT_MP_PREC_MAX ? CFT_MP_PREC_MAX : w;
}

/* ---- lane decode --------------------------------------------------- */

#define K_ZERO 0
#define K_SUB  1
#define K_NORM 2
#define K_INF  3
#define K_NAN  4

typedef struct {
    int kind;
    int sign;
    int signaling;
    cft_bn m;        /* integer significand; |value| = m * 2^e */
    long e;
} lane;

static void lane_decode(const cft_fmt_desc *f, const uint8_t *buf, size_t i,
                        lane *L)
{
    cft_bn x, frac;
    uint32_t ef;
    cft_bn_load(&x, buf + i * (size_t)(f->width / 8), f->width / 8);
    L->sign = cft_bn_bit(&x, f->width - 1);
    ef = cft_bn_extract(&x, f->man_w, f->exp_w);
    L->signaling = 0;
    cft_bn_copy(&frac, &x);
    cft_bn_mask(&frac, f->man_w);
    cft_bn_copy(&L->m, &frac);
    L->e = 0;
    if (ef == f->exp_mask) {
        if (cft_bn_is_zero(&frac)) {
            L->kind = K_INF;
        } else {
            L->kind = K_NAN;
            L->signaling = !cft_bn_bit(&x, f->man_w - 1);
        }
        return;
    }
    if (ef == 0) {
        L->kind = cft_bn_is_zero(&frac) ? K_ZERO : K_SUB;
        L->e = f->emin - f->man_w;
        return;
    }
    L->kind = K_NORM;
    cft_bn_setbit(&L->m, f->man_w);
    L->e = (long)ef - f->bias - f->man_w;
}

static void lane_store(const cft_fmt_desc *f, uint8_t *buf, size_t i,
                       const cft_bn *v)
{
    cft_bn_store(v, buf + i * (size_t)(f->width / 8), f->width / 8);
}

/* floor(log2 |value|) for a finite nonzero lane. */
static long lane_vexp(const lane *L)
{
    return L->e + cft_bn_bitlen(&L->m) - 1;
}

/* The odd-part form: |value| = M * 2^E with M odd. Every exactness
 * test below is stated in it. */
static void lane_odd(const lane *L, cft_bn *M, long *E)
{
    int t = 0, n = cft_bn_bitlen(&L->m);
    while (t < n && !cft_bn_bit(&L->m, t))
        t++;
    cft_bn_shr(M, &L->m, t);
    *E = L->e + t;
}

static int lane_is_one(const lane *L)
{
    cft_bn M;
    long E;
    if (L->kind != K_NORM && L->kind != K_SUB)
        return 0;
    lane_odd(L, &M, &E);
    return E == 0 && cft_bn_bitlen(&M) == 1;
}

/* (is_integer, is_odd_integer) for a finite operand, on the encoding. */
static void lane_integrality(const lane *L, int *is_int, int *is_odd)
{
    cft_bn M;
    long E;
    if (L->kind == K_ZERO) {
        *is_int = 1;
        *is_odd = 0;
        return;
    }
    if (L->kind == K_INF || L->kind == K_NAN) {
        *is_int = 0;
        *is_odd = 0;
        return;
    }
    lane_odd(L, &M, &E);
    *is_int = E >= 0;
    *is_odd = E == 0;
}

/* ---- packed results ------------------------------------------------ */

static void put_one(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    cft_bn_zero(out);
    cft_bn_set_u32(out, (uint32_t)f->bias);
    (void)cft_bn_shl(out, out, f->man_w);
    if (sign)
        cft_bn_setbit(out, f->width - 1);
}

/* Round an exactly-known nonzero dyadic magnitude m * 2^e. round_pack
 * is the library's single rounding authority: a representable value
 * packs with no flags, and one that is not gets exactly the flags any
 * other inexact result would. */
static int round_exact(const cft_fmt_desc *f, int sign, const cft_bn *m,
                       long e, int rnd, cft_bn *out, uint32_t *flags)
{
    if (e > (1 << 24) || e < -(1 << 24))
        return 1;
    return cft_sf_round_pack(f, sign, m, (int)e, 0, rnd, out, flags);
}

/* Provably above every finite magnitude. */
static int round_overflowing(const cft_fmt_desc *f, int sign, int rnd,
                             cft_bn *out, uint32_t *flags)
{
    cft_bn m;
    cft_bn_zero(&m);
    cft_bn_set_u32(&m, 3);
    return cft_sf_round_pack(f, sign, &m, f->emax, 0, rnd, out, flags);
}

/* Provably nonzero and below half the smallest subnormal. */
static int round_underflowing(const cft_fmt_desc *f, int sign, int rnd,
                              cft_bn *out, uint32_t *flags)
{
    cft_bn m;
    cft_bn_zero(&m);
    cft_bn_set_u32(&m, 1);
    return cft_sf_round_pack(f, sign, &m, f->emin - f->man_w - 2, 0, rnd,
                             out, flags);
}

/* Round a value lying strictly between the representable u and the
 * midpoint on one side of it. Every value in that half of the gap
 * rounds identically under all five attributes, so a witness an eighth
 * of a gap from u answers for all of them - and round_pack derives the
 * flags, including the overflow response when u is the largest finite
 * and the attribute steps past it.
 *
 * This is what makes exp of a tiny argument, expm1 and log1p of one,
 * pow of a base near one and hypot with a dominant operand decidable at
 * all: no working precision separates those results from u, and none
 * needs to, because the SIDE is known exactly. */
static int round_neighbour(const cft_fmt_desc *f, const lane *u, int away,
                           int rnd, cft_bn *out, uint32_t *flags)
{
    cft_bn w;
    cft_tr_neighbour++;
    if (cft_bn_shl(&w, &u->m, 3))
        return 1;
    if (away) {
        if (cft_bn_inc(&w))
            return 1;
    } else {
        if (cft_bn_is_zero(&w))
            return 1;
        cft_bn_dec(&w);
    }
    return round_exact(f, u->sign, &w, u->e - 3, rnd, out, flags);
}

/* ---- exact-case machinery ------------------------------------------ */

/* Saturating integer helpers: an exponent that leaves this range has
 * already been settled by a screen, so saturation is a clamp on
 * arithmetic that cannot reach a delivered result. */
#define TR_EXP_CAP ((long)1 << 24)

static long sat_mul(long a, long b)
{
    /* int64 deliberately: `long` is 32 bits on Windows, and two
     * exponents at the cap multiply to 2^48. The first version of this
     * did the multiply in long and wrapped, which turned pow of a
     * subnormal to a large negative power - an overflow - into an
     * underflow. */
    int64_t r;
    if (a == 0 || b == 0)
        return 0;
    r = (int64_t)a * (int64_t)b;
    if (r > TR_EXP_CAP)
        return TR_EXP_CAP;
    if (r < -TR_EXP_CAP)
        return -TR_EXP_CAP;
    return (long)r;
}

/* The integer M * 2^E, saturated at TR_EXP_CAP. Every caller has
 * already screened the values that could reach the cap. */
static long odd_to_long(const cft_bn *M, long E, int sign)
{
    long n = 0;
    int i;
    for (i = cft_bn_bitlen(M) - 1; i >= 0; i--) {
        if (n > TR_EXP_CAP) {
            n = TR_EXP_CAP;
            break;
        }
        n = (n << 1) | cft_bn_bit(M, i);
    }
    if (n > TR_EXP_CAP)
        n = TR_EXP_CAP;
    while (E-- > 0 && n < TR_EXP_CAP)
        n <<= 1;
    if (n > TR_EXP_CAP || E > 0)
        n = TR_EXP_CAP;
    return sign ? -n : n;
}

/* M ** n with an early exit once the odd part passes `maxbits`.
 * Returns 1 when it did (so the value cannot be a rounding boundary). */
static int odd_pow(cft_bn *r, const cft_bn *M, long n, int maxbits)
{
    cft_bn acc, t;
    long i;
    cft_bn_zero(&acc);
    cft_bn_set_u32(&acc, 1);
    for (i = 0; i < n; i++) {
        if (cft_bn_mul(&t, &acc, M))
            return 1;
        if (cft_bn_bitlen(&t) > maxbits)
            return 1;
        cft_bn_copy(&acc, &t);
    }
    cft_bn_copy(r, &acc);
    return 0;
}

/* The exact 2^k-th root of the odd M > 1, by k verified integer square
 * roots. Returns 0 and sets *root when it exists. */
static int odd_root_2k(cft_bn *root, const cft_bn *M, int k)
{
    cft_bn r, s;
    int i, exact;
    cft_bn_copy(&r, M);
    for (i = 0; i < k; i++) {
        if (cft_mp_isqrt(&s, &exact, &r))
            return 1;
        if (!exact)
            return 1;
        cft_bn_copy(&r, &s);
    }
    cft_bn_copy(root, &r);
    return 0;
}

/* ---- table 9.1's remainder: exact helpers -------------------------- *
 *
 * exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt, pown, powr, compound
 * and rootn add no evaluator and no constant. What they add is
 * EXACTNESS: each has a larger exact-case table than the function it is
 * built from, and each table has to be closed before the Ziv loop under
 * it is allowed to run. The helpers below are those tables' arithmetic.
 */

/* An exact cft_mp from an int64_t. Exact at every working precision the
 * schedule reaches, all of which are far above 64 bits - which is what
 * lets pown, compound and rootn multiply or divide by an exponent that
 * a uint32 could not hold. */
static int mp_set_i64(cft_mp *r, int W, int64_t v)
{
    cft_bn m, hi;
    uint64_t u;

    if (v == 0) {
        cft_mp_set_zero(r);
        return 0;
    }
    u = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
    cft_bn_zero(&m);
    cft_bn_set_u32(&m, (uint32_t)(u & 0xffffffffu));
    if ((uint32_t)(u >> 32)) {
        cft_bn_zero(&hi);
        cft_bn_set_u32(&hi, (uint32_t)(u >> 32));
        if (cft_bn_shl(&hi, &hi, 32))
            return 1;
        if (cft_bn_add(&m, &m, &hi))
            return 1;
    }
    return cft_mp_set_bn(r, W, v < 0, &m, 0);
}

static uint64_t i64_abs(int64_t n)
{
    return n < 0 ? (uint64_t)0 - (uint64_t)n : (uint64_t)n;
}

/* sat_mul with an int64 multiplier. The saturation is safe for the same
 * reason sat_mul's is: every caller tests the delivered exponent against
 * the format BEFORE packing, so a clamp at 2^24 - which is above emax at
 * all four rungs - reaches the overflow or underflow response and never
 * a wrong finite value. */
static long sat_mul_i64(long a, int64_t b)
{
    int64_t r;
    if (a == 0 || b == 0)
        return 0;
    if (b > TR_EXP_CAP || b < -TR_EXP_CAP)
        return ((a > 0) == (b > 0)) ? TR_EXP_CAP : -TR_EXP_CAP;
    r = (int64_t)a * b;
    if (r > TR_EXP_CAP)
        return TR_EXP_CAP;
    if (r < -TR_EXP_CAP)
        return -TR_EXP_CAP;
    return (long)r;
}

/* 1 + x as an EXACT dyadic m * 2^e, m >= 0, for a finite lane with
 * x >= -1. Never a rounded sum: the two exponents are aligned on the
 * lower of them and the integers are added, the discipline phase 3's
 * acosh and atanh keep for x - 1 and 1 - x.
 *
 * Returns 1 when the exact form would need more than `maxbits`, and for
 * every caller here that is a PROOF that no exact case exists rather
 * than a shrug. An exact case needs the odd part of 1 + x inside p+1
 * bits, or 1 + x itself a power of two; write x = +-M 2^E with M odd.
 * For E < 0 the odd part of 1 + x is 2^-E -+ M, which is odd and about
 * -E bits wide, so p+1 bits force -E <= p+1. For E >= 1 it is
 * M 2^E + 1, odd and E + bits(M) wide, so the same bound applies. And
 * 1 + x = 2^k with x representable forces |k| <= p, whose aligned form
 * is p+1 bits. maxbits = p+4 therefore discards nothing.
 */
static int lane_one_plus(const lane *L, cft_bn *m, long *e, int maxbits)
{
    cft_bn one, t, M;
    long E, e0, sh_one, sh_x;
    int nb;

    /* The ODD form, not the encoding's: |x| = M * 2^E with M odd is the
     * canonical shape every width bound below is stated in, and 2^-12 at
     * binary32 is the encoding 2^23 * 2^-35 - which would put the
     * alignment 23 bits deeper than the value needs. */
    lane_odd(L, &M, &E);
    e0 = E < 0 ? E : 0;
    sh_one = -e0;
    sh_x = E - e0;
    nb = cft_bn_bitlen(&M);
    if (sh_one > (long)maxbits || sh_x + nb > (long)maxbits)
        return 1;
    cft_bn_zero(&one);
    cft_bn_setbit(&one, (int)sh_one);
    if (cft_bn_shl(&t, &M, (int)sh_x))
        return 1;
    if (L->sign) {
        if (cft_bn_cmp(&one, &t) < 0)
            return 1;                    /* x < -1: the callers screen it */
        cft_bn_sub(m, &one, &t);
    } else {
        if (cft_bn_add(m, &one, &t))
            return 1;
    }
    *e = e0;
    return 0;
}

/* The exact k-th root of the odd M > 1, k >= 2, built one bit at a time
 * from the top and VERIFIED by raising it back - the same rule
 * odd_root_2k keeps with its integer square roots, and the same reason:
 * a root decided by a tolerance is not a root. Returns 0 and sets *root
 * when M is a perfect k-th power. */
static int odd_root_n(cft_bn *root, const cft_bn *M, long k)
{
    cft_bn r, t, cand;
    int nb = cft_bn_bitlen(M);
    int top, i, c;

    if (k >= (long)nb)
        return 1;                /* a root of 2 or more would need 2^k <= M */
    top = (int)(((long)nb + k - 1) / k);
    cft_bn_zero(&r);
    for (i = top; i >= 0; i--) {
        cft_bn_copy(&cand, &r);
        cft_bn_setbit(&cand, i);
        if (odd_pow(&t, &cand, k, nb))
            continue;                    /* already wider than M */
        c = cft_bn_cmp(&t, M);
        if (c <= 0)
            cft_bn_copy(&r, &cand);
        if (c == 0)
            break;
    }
    if (cft_bn_is_zero(&r))
        return 1;
    if (odd_pow(&t, &r, k, nb))
        return 1;
    if (cft_bn_cmp(&t, M) != 0)
        return 1;
    cft_bn_copy(root, &r);
    return 0;
}

/* (m * 2^e)^n as an exact dyadic, or 1 when no such value can be a
 * rounding boundary. m > 0, n != 0.
 *
 * This is pow_dyadic's integer-exponent branch restated on a DYADIC
 * rather than on an encoding, so that compound can apply it to the exact
 * 1 + x. The proof is phase 1's: the odd part of (M 2^E)^n is M^n, so
 * either M = 1 and the value is a pure exponent shift, or n <= p+1 and
 * the power is computed exactly with an early exit the moment it passes
 * p+1 bits, or the value's odd part is too wide to be a grid point or a
 * midpoint. A negative n with M > 1 gives a rational that is not dyadic,
 * which is not a boundary either. */
static int dyadic_pow_int(const cft_fmt_desc *f, const cft_bn *m, long e,
                          int64_t n, cft_bn *rm, long *re)
{
    cft_bn M, t;
    long E, tz = 0;
    int nb = cft_bn_bitlen(m), p = f->prec;

    while (tz < (long)nb && !cft_bn_bit(m, (int)tz))
        tz++;
    cft_bn_shr(&M, m, (int)tz);
    E = e + tz;
    if (cft_bn_bitlen(&M) == 1) {              /* |value| is 2^E */
        cft_bn_zero(rm);
        cft_bn_set_u32(rm, 1);
        *re = sat_mul_i64(E, n);
        return 0;
    }
    if (n < 0)
        return 1;                              /* 1/(odd > 1) is not dyadic */
    if (n > (int64_t)p + 1)
        return 1;
    if (odd_pow(&t, &M, (long)n, p + 1))
        return 1;
    cft_bn_copy(rm, &t);
    *re = sat_mul_i64(E, n);
    return 0;
}

/* |x|^(1/n) as an exact dyadic, or 1 when it is not one.
 *
 * (M 2^E)^(1/n) is rational exactly when M is a perfect |n|-th power and
 * |n| divides E - one verified integer root and one exact division - and
 * for a negative n the reciprocal of that is dyadic only when the root
 * is 1, because 1/(odd > 1) is not a dyadic rational. */
static int rootn_dyadic(const cft_fmt_desc *f, const lane *x, int64_t n,
                        cft_bn *rm, long *re)
{
    cft_bn M, root;
    long E, F;
    uint64_t k = i64_abs(n);

    (void)f;
    lane_odd(x, &M, &E);
    if (E != 0) {
        uint64_t ae = (uint64_t)(E < 0 ? -E : E);
        if (k > ae)
            return 1;                          /* |n| > |E| > 0: no divisor */
        if (E % (long)k)
            return 1;
        F = E / (long)k;
    } else {
        F = 0;
    }
    if (cft_bn_bitlen(&M) == 1) {              /* M == 1 */
        cft_bn_zero(rm);
        cft_bn_set_u32(rm, 1);
        *re = n < 0 ? -F : F;
        return 0;
    }
    if (n < 0)
        return 1;
    if (k > (uint64_t)cft_bn_bitlen(&M))
        return 1;
    if (odd_root_n(&root, &M, (long)k))
        return 1;
    cft_bn_copy(rm, &root);
    *re = F;
    return 0;
}

/* 5^n, with an early exit the moment it passes `maxbits`. The only
 * exact-case test exp10 and log10p1 need, and the same shape log10's
 * has carried since phase 1. */
static int pow5(cft_bn *r, long n, int maxbits)
{
    cft_bn acc, five, t;
    long i;
    cft_bn_zero(&acc);
    cft_bn_set_u32(&acc, 1);
    cft_bn_zero(&five);
    cft_bn_set_u32(&five, 5);
    for (i = 0; i < n; i++) {
        if (cft_bn_mul(&t, &acc, &five))
            return 1;
        if (cft_bn_bitlen(&t) > maxbits)
            return 1;
        cft_bn_copy(&acc, &t);
    }
    cft_bn_copy(r, &acc);
    return 0;
}

/* ---- the multiprecision series ------------------------------------- */

static void mp_bump(cft_mp *v, uint64_t k)
{
    uint64_t s = v->err + k;
    v->err = (s < v->err || s > CFT_MP_ERR_MAX) ? CFT_MP_ERR_MAX : s;
}

/* Has the series term fallen below the working precision's reach? */
static int term_negligible(const cft_mp *term, const cft_mp *sum, int W)
{
    if (term->zero)
        return 1;
    if (sum->zero)
        return 0;
    return cft_mp_exp2_of(term) < cft_mp_exp2_of(sum) - (long)(W + 8);
}

/* exp(t) for |t| <= 0.36, by five halvings, the Taylor series, and
 * five squarings. Halving is exact (an exponent decrement), so the
 * series argument is at most 0.0113 and about W/6.5 terms reach the
 * working precision; each squaring at most doubles the accumulated
 * relative error, which is the 5 bits of the guard budget it costs. */
#define TR_HALVINGS 5

static int mp_exp_core(cft_mp *r, const cft_mp *t, int W)
{
    cft_mp u, term, sum, tmp;
    uint32_t j;
    int i;

    cft_mp_copy(&u, t);
    cft_mp_shift(&u, -TR_HALVINGS);
    if (cft_mp_set_ui(&sum, W, 0, 1, 0))
        return 1;
    cft_mp_copy(&term, &sum);
    for (j = 1; j < 4096; j++) {
        if (cft_mp_mul(&tmp, &term, &u, W))
            return 1;
        if (cft_mp_div_ui(&term, &tmp, j, W))
            return 1;
        if (cft_mp_add(&tmp, &sum, &term, W))
            return 1;
        cft_mp_copy(&sum, &tmp);
        if (term_negligible(&term, &sum, W))
            break;
    }
    mp_bump(&sum, 1);            /* the truncated tail, generously */
    for (i = 0; i < TR_HALVINGS; i++) {
        if (cft_mp_mul(&tmp, &sum, &sum, W))
            return 1;
        cft_mp_copy(&sum, &tmp);
    }
    cft_mp_copy(r, &sum);
    return 0;
}

/* expm1(t) for |t| <= 0.36, by the same halvings and the doubling
 * identity expm1(2u) = expm1(u) * (expm1(u) + 2). The identity is used
 * rather than exp - 1 because for a negative argument expm1(u) lies in
 * (-1, 0) and expm1(u) + 2 in (1, 2): the product never cancels, where
 * exp(t) - 1 would lose every bit the answer has. */
static int mp_expm1_core(cft_mp *r, const cft_mp *t, int W)
{
    cft_mp u, term, sum, tmp, two;
    uint32_t j;
    int i;

    cft_mp_copy(&u, t);
    cft_mp_shift(&u, -TR_HALVINGS);
    cft_mp_copy(&sum, &u);
    cft_mp_copy(&term, &u);
    for (j = 2; j < 4096; j++) {
        if (cft_mp_mul(&tmp, &term, &u, W))
            return 1;
        if (cft_mp_div_ui(&term, &tmp, j, W))
            return 1;
        if (cft_mp_add(&tmp, &sum, &term, W))
            return 1;
        cft_mp_copy(&sum, &tmp);
        if (term_negligible(&term, &sum, W))
            break;
    }
    mp_bump(&sum, 1);
    if (cft_mp_set_ui(&two, W, 0, 1, 1))
        return 1;
    for (i = 0; i < TR_HALVINGS; i++) {
        if (cft_mp_add(&tmp, &sum, &two, W))
            return 1;
        if (cft_mp_mul(&sum, &sum, &tmp, W))
            return 1;
    }
    cft_mp_copy(r, &sum);
    return 0;
}

/* 2 * atanh(z) = 2(z + z^3/3 + z^5/5 + ...), for |z| < 1/2. Every term
 * has the sign of z, so the sum never cancels. */
static int mp_atanh2(cft_mp *r, const cft_mp *z, int W)
{
    cft_mp z2, term, sum, tmp, q;
    uint32_t j;

    if (cft_mp_mul(&z2, z, z, W))
        return 1;
    cft_mp_copy(&sum, z);
    cft_mp_copy(&term, z);
    for (j = 1; j < 8192; j++) {
        if (cft_mp_mul(&tmp, &term, &z2, W))
            return 1;
        cft_mp_copy(&term, &tmp);
        if (cft_mp_div_ui(&q, &term, 2 * j + 1, W))
            return 1;
        if (cft_mp_add(&tmp, &sum, &q, W))
            return 1;
        cft_mp_copy(&sum, &tmp);
        if (term_negligible(&q, &sum, W))
            break;
    }
    mp_bump(&sum, 1);
    cft_mp_copy(r, &sum);
    cft_mp_shift(r, 1);
    return 0;
}

/* exp(t) for any t the screens let through: t = k ln2 + s with |s| <=
 * ln2/2, then exp(s) scaled by 2^k. k need not be the NEAREST integer
 * - an off-by-one only widens |s| to 0.7, which the series still
 * carries - so a cheap estimate is enough. */
static int mp_exp_full(cft_mp *r, const cft_mp *t, int W)
{
    cft_mp l2, e2, q, ks, s;
    int64_t k;
    int neg;

    if (t->zero)
        return cft_mp_set_ui(r, W, 0, 1, 0);
    if (cft_mp_const(&e2, CFT_MP_C_LOG2E, W))
        return 1;
    if (cft_mp_mul(&q, t, &e2, W))
        return 1;
    k = cft_mp_trunc_to_int(&q);
    if (k > (1 << 24) || k < -(1 << 24))
        return 1;                       /* the screens keep this away */
    if (k == 0) {
        cft_mp_copy(&s, t);
    } else {
        if (cft_mp_const(&l2, CFT_MP_C_LN2, W))
            return 1;
        neg = k < 0;
        if (cft_mp_mul_ui(&ks, &l2, (uint32_t)(neg ? -k : k), W))
            return 1;
        if (neg)
            cft_mp_neg(&ks);
        if (cft_mp_sub(&s, t, &ks, W))
            return 1;
    }
    if (mp_exp_core(r, &s, W))
        return 1;
    cft_mp_shift(r, (long)k);
    return 0;
}

/* log of an exactly-known positive value m * 2^e.
 *
 * x = m' * 2^E with m' in [1/sqrt2, sqrt2), so that |log m'| <= ln2/2
 * and E ln2 cannot cancel it by more than one bit - the reduction to
 * [1, 2) is the one that fails, because x just below 1 would then be
 * -ln2 + (ln2 - eps) and lose every bit of the answer.
 *
 * log m' = 2 atanh((m'-1)/(m'+1)), and both the subtraction and the
 * addition are on EXACT operands, so the cancellation in m'-1 costs
 * nothing at all: it amplifies an error of zero. */
static int mp_log_exact(cft_mp *r, const cft_bn *m, long e, int W)
{
    cft_mp x, mm, one, num, den, z, lm, l2, el2, tmp;
    cft_bn sq;
    long E;
    int neg;

    if (cft_mp_set_bn(&x, W, 0, m, e))
        return 1;
    E = cft_mp_exp2_of(&x);
    cft_mp_copy(&mm, &x);
    mm.exp = -(long)(W - 1);            /* the significand as [1, 2) */
    if (cft_bn_mul(&sq, &mm.m, &mm.m))
        return 1;
    if (cft_bn_bitlen(&sq) == 2 * W) {  /* m' >= sqrt(2): halve it */
        mm.exp -= 1;
        E += 1;
    }
    if (cft_mp_set_ui(&one, W, 0, 1, 0))
        return 1;
    if (cft_mp_sub(&num, &mm, &one, W))
        return 1;
    if (num.zero) {                     /* x is a power of two exactly */
        cft_mp_set_zero(&lm);
    } else {
        if (cft_mp_add(&den, &mm, &one, W))
            return 1;
        if (cft_mp_div(&z, &num, &den, W))
            return 1;
        if (mp_atanh2(&lm, &z, W))
            return 1;
    }
    if (E == 0) {
        cft_mp_copy(r, &lm);
        return 0;
    }
    neg = E < 0;
    if (cft_mp_const(&l2, CFT_MP_C_LN2, W))
        return 1;
    if (cft_mp_mul_ui(&el2, &l2, (uint32_t)(neg ? -E : E), W))
        return 1;
    if (neg)
        cft_mp_neg(&el2);
    if (cft_mp_add(&tmp, &el2, &lm, W))
        return 1;
    cft_mp_copy(r, &tmp);
    return 0;
}

/* log1p(u) for an exactly-known u > -1, in three regimes, and the
 * boundaries are where 1 + u stops being exactly representable at the
 * working precision:
 *
 *   |u| <= 1/4          z = u/(u+2) directly. 1 + u is NEVER formed,
 *                       which is the whole point: for u = 2^-1074 it
 *                       would round to 1 and take the answer with it.
 *   |u| <= 2^(p+30)     1 + u is exact at W >= 2p+40 bits, so the
 *                       ordinary logarithm applies.
 *   larger              log1p(u) = log(u) + log1p(1/u), with 1/u tiny
 *                       and positive, so the first regime finishes it
 *                       and neither term can cancel the other.
 */
static int mp_log1p_small(cft_mp *r, const cft_mp *u, int W)
{
    cft_mp two, den, z;
    if (cft_mp_set_ui(&two, W, 0, 1, 1))
        return 1;
    if (cft_mp_add(&den, u, &two, W))
        return 1;
    if (cft_mp_div(&z, u, &den, W))
        return 1;
    return mp_atanh2(r, &z, W);
}

/* log(1 + u) for an exactly-known lane u > -1, SIGNED, in the three
 * regimes above. Factored out because log2p1, log10p1 and compound all
 * need exactly it - and all need it never to form 1 + u when u is tiny,
 * which is the property this function exists to keep. */
static int mp_log1p_lane(cft_mp *r, const cft_fmt_desc *f, const lane *a,
                         int Wi)
{
    cft_mp x, t, l, one, inv, part;
    long v = lane_vexp(a);

    if (cft_mp_set_bn(&x, Wi, a->sign, &a->m, a->e))
        return 1;
    if (v <= -2)
        return mp_log1p_small(r, &x, Wi);
    if (v <= (long)f->prec + 30) {
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_add(&t, &one, &x, Wi))
            return 1;
        if (t.zero || t.sign)
            return 1;                    /* u <= -1 was handled upstream */
        return mp_log_exact(r, &t.m, t.exp, Wi);
    }
    if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
        return 1;
    if (cft_mp_div(&inv, &one, &x, Wi))
        return 1;
    if (mp_log1p_small(&part, &inv, Wi))
        return 1;
    if (mp_log_exact(&l, &a->m, a->e, Wi))
        return 1;
    return cft_mp_add(r, &l, &part, Wi);
}


/* ---- phase 2: the trigonometric series ------------------------------ *
 *
 * Both series below split their terms into a POSITIVE and a NEGATIVE
 * accumulator and subtract once at the end, instead of adding
 * alternating terms into a single running sum. The reason is the error
 * model: cft_mp_add's unlike-signs rule charges a factor of two per
 * step even when nothing cancels, because the result can be half the
 * larger operand. Over a hundred and thirty terms that is 2^130 and
 * the bound saturates; split in two it is one doubling in total, and
 * the accumulators themselves only ever add like signs.
 *
 * The final subtraction is safe by construction. For sin, the positive
 * part is v + v^5/120 + ... and the negative v^3/6 + ..., so with
 * |v| <= pi/4 the difference keeps more than four fifths of the larger;
 * for cos it keeps two thirds; for atan, more than nine tenths. None of
 * them is a cancellation.
 */

/* sin(v) and cos(v) together, for 0 <= v <= pi/4.
 *
 * term_n = v^n / n!, and n mod 4 says which of the four accumulators it
 * belongs to: 0 cos+, 1 sin+, 2 cos-, 3 sin-. The terms decrease
 * monotonically because v < 1, so the first one that falls below the
 * working precision's reach ends the sum - and the test is against the
 * SINE's accumulator, which is the smaller of the two whenever v is
 * small and is therefore the one that sets the requirement. */
static int mp_sincos(cft_mp *sn, cft_mp *cs, const cft_mp *v, int W)
{
    cft_mp term, tmp, acc[4];
    uint32_t n;
    int i;

    for (i = 0; i < 4; i++)
        cft_mp_set_zero(&acc[i]);
    if (cft_mp_set_ui(&term, W, 0, 1, 0))          /* term_0 = 1 */
        return 1;
    cft_mp_copy(&acc[0], &term);
    for (n = 1; n < 8192; n++) {
        if (cft_mp_mul(&tmp, &term, v, W))
            return 1;
        if (cft_mp_div_ui(&term, &tmp, n, W))
            return 1;
        i = (int)(n & 3);
        if (cft_mp_add(&tmp, &acc[i], &term, W))
            return 1;
        cft_mp_copy(&acc[i], &tmp);
        if (n >= 3 && term_negligible(&term, &acc[1], W))
            break;
    }
    for (i = 0; i < 4; i++)
        mp_bump(&acc[i], 1);                       /* the truncated tail */
    if (cft_mp_sub(sn, &acc[1], &acc[3], W))
        return 1;
    return cft_mp_sub(cs, &acc[0], &acc[2], W);
}

/* atan(z) for 0 < z <= 0.15, by its alternating series, split. */
static int mp_atan_series(cft_mp *r, const cft_mp *z, int W)
{
    cft_mp z2, pw, q, pos, neg, tmp;
    uint32_t k;

    if (cft_mp_mul(&z2, z, z, W))
        return 1;
    cft_mp_copy(&pos, z);
    cft_mp_set_zero(&neg);
    cft_mp_copy(&pw, z);
    for (k = 1; k < 16384; k++) {
        if (cft_mp_mul(&tmp, &pw, &z2, W))
            return 1;
        cft_mp_copy(&pw, &tmp);
        if (cft_mp_div_ui(&q, &pw, 2 * k + 1, W))
            return 1;
        if (term_negligible(&q, &pos, W))
            break;
        if (k & 1) {
            if (cft_mp_add(&tmp, &neg, &q, W))
                return 1;
            cft_mp_copy(&neg, &tmp);
        } else {
            if (cft_mp_add(&tmp, &pos, &q, W))
                return 1;
            cft_mp_copy(&pos, &tmp);
        }
    }
    mp_bump(&pos, 1);
    mp_bump(&neg, 1);
    return cft_mp_sub(r, &pos, &neg, W);
}

/* The number of halvings before the series. atan(u) =
 * 2 atan(u/(1 + sqrt(1+u^2))) is exact, and three of them take the
 * largest argument this routine ever sees - 2 - down to 0.1421, where
 * the series needs about W/5.6 terms. Each halving costs one square
 * root and one division and no cancellation at all: 1 + u^2 and
 * 1 + sqrt are both like-signs adds. */
#define TR_ATAN_HALVINGS 3

/* atan(t) for any t > 0.
 *
 * t >= 2 goes through atan(t) = pi/2 - atan(1/t), where 1/t <= 1/2 puts
 * atan(1/t) below 0.464 and the difference above 1.1 - so the
 * subtraction loses no bits. Below 2 the halvings handle it directly;
 * the threshold is 2 rather than 1 precisely so that the pi/2 branch
 * never has to subtract something close to pi/2 from it. */
static int mp_atan_pos(cft_mp *r, const cft_mp *t, int W)
{
    cft_mp u, one, s, d, q, a, pi;
    int i, recip;

    if (t->zero)
        return 1;                         /* the callers screen zero out */
    recip = cft_mp_exp2_of(t) >= 1;
    if (cft_mp_set_ui(&one, W, 0, 1, 0))
        return 1;
    if (recip) {
        if (cft_mp_div(&u, &one, t, W))
            return 1;
    } else {
        cft_mp_copy(&u, t);
    }
    for (i = 0; i < TR_ATAN_HALVINGS; i++) {
        if (cft_mp_mul(&s, &u, &u, W))
            return 1;
        if (cft_mp_add(&d, &s, &one, W))
            return 1;
        if (cft_mp_sqrt(&s, &d, W))
            return 1;
        if (cft_mp_add(&d, &s, &one, W))
            return 1;
        if (cft_mp_div(&q, &u, &d, W))
            return 1;
        cft_mp_copy(&u, &q);
    }
    if (mp_atan_series(&a, &u, W))
        return 1;
    cft_mp_shift(&a, TR_ATAN_HALVINGS);
    if (!recip) {
        cft_mp_copy(r, &a);
        return 0;
    }
    if (cft_mp_const(&pi, CFT_MP_C_PI, W))
        return 1;
    cft_mp_shift(&pi, -1);                /* pi/2, exactly */
    return cft_mp_sub(r, &pi, &a, W);
}

/* sqrt((1 - |x|)(1 + |x|)) for a lane with |x| < 1.
 *
 * The product form, not 1 - x^2. For |x| just below 1 the factor
 * 1 - |x| is EXACT - both operands are exact at the working precision,
 * so the cancellation amplifies an error of zero and costs nothing -
 * where 1 - x^2 formed directly would lose every bit the answer has.
 * Phase 1's log(m') is the same shape for the same reason. */
static int mp_asin_root(cft_mp *r, const lane *x, int W)
{
    cft_mp ax, one, lo, hi, p;
    if (cft_mp_set_bn(&ax, W, 0, &x->m, x->e))
        return 1;
    if (cft_mp_set_ui(&one, W, 0, 1, 0))
        return 1;
    if (cft_mp_sub(&lo, &one, &ax, W))
        return 1;
    if (cft_mp_add(&hi, &one, &ax, W))
        return 1;
    if (cft_mp_mul(&p, &lo, &hi, W))
        return 1;
    return cft_mp_sqrt(r, &p, W);
}

/* Multiply by the generated 1/pi, for the Pi-variants of the inverse
 * functions. A division by pi would do as well and cost sixty times
 * more; the constant carries its own two units of error and the
 * multiply adds three. */
static int mp_over_pi(cft_mp *r, const cft_mp *a, int W)
{
    cft_mp inv;
    if (cft_mp_const(&inv, CFT_MP_C_INVPI, W))
        return 1;
    return cft_mp_mul(r, a, &inv, W);
}

/* ---- phase 3: the Payne-Hanek reduction against pi/2 ---------------- *
 *
 * `x mod (pi/2)` for a dyadic x of any magnitude the formats allow, in
 * integer arithmetic, with the quadrant.
 *
 * THE IDENTITY. Write |x| = m * 2^e with m the p-bit significand, and
 * 2/pi = sum_(j>=1) b_j 2^-j. Then
 *
 *     |x| * (2/pi) = m * sum_j b_j 2^(e-j)
 *
 * and every term with e - j >= 2 is m times a multiple of 4. Those
 * terms cannot change the quadrant and cannot change the fraction, so
 * they are dropped EXACTLY: the window of 2/pi starts at bit
 * j0 = max(1, e-1) and the bits above it are never read. That is the
 * whole of why a quarter-megabit constant is enough for an argument as
 * large as 2^262143 - the window's START is an exponent-range question
 * and its WIDTH is a precision question, and they are separate.
 *
 * THE CANCELLATION IS A MEASUREMENT. Take the low `wbits` of the
 * product, read the quadrant off the two bits above the binary point,
 * and the reduced fraction off the rest. If |x| happens to sit very
 * close to a multiple of pi/2 that fraction has leading zeros, and the
 * window must be that many bits wider to still deliver the working
 * precision. How many is not a theorem: the irrationality measure of pi
 * (mu < 7.104, Zeilberger-Zudilin 2020) permits 2^-1600000 at fp256,
 * which is useless. So this routine MEASURES the cancellation from the
 * bits it has, widens the window by exactly the deficit, and repeats -
 * escalate, never guess - and refuses with CFT_ERR_INTERNAL past
 * CFT_TR_PH_WINDOW_MAX. host/tools/pi_worstcase.py measures the real
 * depth per format: 29 bits at fp32 and 61 at fp64 over every binade,
 * 121 and 245 over sampled fp128 and fp256 binades, against an
 * allowance of about seven thousand.
 *
 * The scratch below is a plain limb array rather than a cft_bn on
 * purpose: cft_bn is 2048 bits, which would cap the cancellation
 * allowance at a few hundred and make the CONTAINER the thing the
 * contract refuses on. Nothing else in this file needs an integer this
 * wide, and nothing else is allowed to use this one.
 */

#include "mp_2opi.h"

#define TR_PH_LIMBS ((CFT_TR_PH_WINDOW_MAX + 512) / 32)

typedef struct {
    uint32_t v[TR_PH_LIMBS];        /* little-endian */
} ph_int;

/* Bits j0 .. j0+wbits-1 of 2/pi as a wbits-bit integer, most
 * significant first. wbits is always a multiple of 32, which is what
 * makes this one masked shift per limb rather than a bit loop. */
static int ph_window(ph_int *B, long j0, int wbits)
{
    long s = j0 - 1;                     /* 0-based index into the stream */
    int wi = (int)(s >> 5), off = (int)(s & 31);
    int nw = wbits / 32, i;

    if (s < 0 || wbits <= 0 || nw > TR_PH_LIMBS)
        return 1;
    if (wi + nw + 1 >= CFT_TWO_OVER_PI_WORDS)
        return 1;                        /* would read past the constant */
    memset(B->v, 0, sizeof B->v);
    for (i = 0; i < nw; i++) {
        uint32_t lo = cft_two_over_pi[wi + i];
        uint32_t hi = cft_two_over_pi[wi + i + 1];
        B->v[nw - 1 - i] = off ? ((lo << off) | (hi >> (32 - off))) : lo;
    }
    return 0;
}

/* P = B * m, schoolbook. m is a significand, so at most eight limbs. */
static int ph_mul(ph_int *P, const ph_int *B, int bw, const cft_bn *m)
{
    int i, j, k;
    memset(P->v, 0, sizeof P->v);
    for (i = 0; i < m->n; i++) {
        uint64_t carry = 0;
        uint32_t mi = m->v[i];
        if (!mi)
            continue;
        for (j = 0; j < bw; j++) {
            uint64_t t;
            if (i + j >= TR_PH_LIMBS)
                return 1;
            t = (uint64_t)B->v[j] * mi + P->v[i + j] + carry;
            P->v[i + j] = (uint32_t)t;
            carry = t >> 32;
        }
        for (k = i + bw; carry; k++) {
            uint64_t t;
            if (k >= TR_PH_LIMBS)
                return 1;
            t = (uint64_t)P->v[k] + carry;
            P->v[k] = (uint32_t)t;
            carry = t >> 32;
        }
    }
    return 0;
}

static int ph_bit(const ph_int *P, long i)
{
    if (i < 0 || i >= (long)TR_PH_LIMBS * 32)
        return 0;
    return (int)((P->v[i >> 5] >> (i & 31)) & 1u);
}

static long ph_bitlen(const ph_int *P)
{
    int i;
    for (i = TR_PH_LIMBS - 1; i >= 0; i--) {
        if (P->v[i]) {
            uint32_t w = P->v[i];
            int b = 0;
            while (w) { b++; w >>= 1; }
            return (long)i * 32 + b;
        }
    }
    return 0;
}

/* R = (2^d - P) for 0 < P < 2^d, as ~P + 1 over d bits. */
static void ph_neg_mod_pow2(ph_int *R, const ph_int *P, long d)
{
    int nw = (int)((d + 31) >> 5), i;
    uint64_t carry = 1;
    if (nw > TR_PH_LIMBS)
        nw = TR_PH_LIMBS;
    memset(R->v, 0, sizeof R->v);
    for (i = 0; i < nw; i++)
        R->v[i] = ~P->v[i];
    if (d & 31)
        R->v[nw - 1] &= (uint32_t)((1u << (d & 31)) - 1u);
    for (i = 0; i < nw && carry; i++) {
        uint64_t t = (uint64_t)R->v[i] + carry;
        R->v[i] = (uint32_t)t;
        carry = t >> 32;
    }
    if (d & 31)
        R->v[nw - 1] &= (uint32_t)((1u << (d & 31)) - 1u);
}

/* The low `d` bits of P, in place. */
static void ph_mask_low(ph_int *P, long d)
{
    int nw = (int)((d + 31) >> 5), i;
    if (nw >= TR_PH_LIMBS)
        return;                          /* d covers the whole scratch */
    for (i = nw; i < TR_PH_LIMBS; i++)
        P->v[i] = 0;
    if (d & 31)
        P->v[nw - 1] &= (uint32_t)((1u << (d & 31)) - 1u);
}

/* The top `keep` bits of V (whose length is `b`) into a cft_bn, with
 * the shift that was applied. */
static void ph_top_bits(cft_bn *out, long *shift, const ph_int *V, long b,
                        int keep)
{
    long s = b > (long)keep ? b - (long)keep : 0;
    int wi = (int)(s >> 5), off = (int)(s & 31);
    int need = (int)(((b - s) + 31) / 32) + 1, i;

    if (need > CFT_BN_LIMBS)
        need = CFT_BN_LIMBS;
    cft_bn_zero(out);
    for (i = 0; i < need; i++) {
        uint32_t lo = (wi + i < TR_PH_LIMBS) ? V->v[wi + i] : 0u;
        uint32_t hi = (wi + i + 1 < TR_PH_LIMBS) ? V->v[wi + i + 1] : 0u;
        out->v[i] = off ? ((lo >> off) | (hi << (32 - off))) : lo;
    }
    out->n = need;
    while (out->n > 0 && out->v[out->n - 1] == 0)
        out->n--;
    *shift = s;
}

/* The reduction constant, checked two ways that prove different things.
 *
 * 1. The TOP of the array against 2/pi derived from the pi in
 *    mp_consts.h - which cft_mp_consts_selfcheck has already re-derived
 *    from Machin's formula out of small-integer arithmetic that touches
 *    no stored constant. That says the stored bit stream really is
 *    2/pi, to the 1088 bits the other header carries. It says nothing
 *    whatever about bit 1089 onward.
 *
 * 2. An FNV-1a checksum over every word, against the value the
 *    generator computed. That says the array in this binary is the
 *    array gen_2opi.py emitted - it catches a truncation, a byte swap,
 *    a corrupted object file, an edit - and it says nothing about those
 *    deep bits being 2/pi's either.
 *
 * Only regeneration proves the deep bits, and that is what
 * python/tests/test_mp_consts.py does on every test run, twice: once
 * against the generator and once against an INDEPENDENT Chudnovsky
 * derivation in plain Python integers that shares nothing with mpmath.
 * Saying which of the three proves what is the point of having three.
 *
 * Cached, with a sticky failure, for the reason phase 2's Machin
 * derivation is cached: it is a property of compile-time data, and a
 * bad header must not become good on the second call. */
static int tr_2opi_ok(void)
{
    static int state;                    /* 0 not run, 1 ok, 2 failed */
    const int W = 512;
    ph_int B;
    cft_bn bn, dm;
    cft_mp got, pi, two, want;
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    int i, k;

    if (state)
        return state == 1 ? 0 : 1;
    state = 2;

    for (i = 0; i < CFT_TWO_OVER_PI_WORDS; i++)
        for (k = 0; k < 4; k++) {
            h ^= (uint64_t)((cft_two_over_pi[i] >> (8 * k)) & 0xffu);
            h *= UINT64_C(0x100000001b3);
        }
    if (h != CFT_TWO_OVER_PI_FNV1A)
        return 1;

    if (ph_window(&B, 1, W))
        return 1;
    cft_bn_zero(&bn);
    for (i = 0; i < W / 32; i++)
        bn.v[i] = B.v[i];
    bn.n = W / 32;
    while (bn.n > 0 && bn.v[bn.n - 1] == 0)
        bn.n--;
    if (cft_mp_set_bn(&got, W, 0, &bn, -W))
        return 1;
    if (cft_mp_const(&pi, CFT_MP_C_PI, W))
        return 1;
    if (cft_mp_set_ui(&two, W, 0, 1, 1))
        return 1;
    if (cft_mp_div(&want, &two, &pi, W))
        return 1;
    /* Both are W-bit normalisations of the same number, so the
     * exponents match and the significands differ by the handful of
     * units two truncations and one division cost. A WRONG constant
     * differs by about 2^(W-1) of them. The comparison is done on the
     * significands rather than through cft_mp_sub because that routine
     * treats an exact cancellation of two inexact operands as a
     * failure, and these two agreeing to the last bit is the case this
     * check most hopes for. */
    if (got.exp != want.exp)
        return 1;
    if (cft_bn_cmp(&got.m, &want.m) >= 0)
        cft_bn_sub(&dm, &got.m, &want.m);
    else
        cft_bn_sub(&dm, &want.m, &got.m);
    if (cft_bn_bitlen(&dm) > 32)
        return 1;

    state = 1;
    return 0;
}

/* The reduction's answer. `t` is |x|*(2/pi) - n as a tracked mp with
 * |t| <= about 1/2, and `quadrant` is n mod 4; the reduced argument
 * itself is t * (pi/2) and is formed at each working precision by
 * tr_eval, because the constant it multiplies is precision-dependent
 * where t is not. */
typedef struct {
    int    quadrant;
    long   t_exp2;                  /* floor(log2 |t|) */
    cft_mp t;
} tr_pi_red;

static int tr_ph_reduce(tr_pi_red *R, const lane *a, const cft_fmt_desc *f)
{
    int p = f->prec;
    int Wr = tr_wint(f, tr_prec_cap(f));    /* the deepest attempt's width */
    long e = a->e;
    long j0 = e - 1 < 1 ? 1 : e - 1;
    int wbits = ((p + Wr + 64) + 31) & ~31;

    cft_tr_reduce_calls++;
    for (;;) {
        ph_int B, P, T;
        cft_bn tm;
        long d, tb, vt, avail, sh;
        int i2, n, tneg;

        if (wbits > CFT_TR_PH_WINDOW_MAX)
            return 1;                    /* deeper than the contract covers */
        if (ph_window(&B, j0, wbits))
            return 1;
        if (ph_mul(&P, &B, wbits / 32, &a->m))
            return 1;
        d = j0 + wbits - 1 - e;          /* |x|*(2/pi) == P * 2^-d, mod 4 */
        if (d <= 1)
            return 1;                    /* wbits > p keeps this away */

        /* The two bits above the point are the quadrant; the bit just
         * below decides whether the nearest integer is that one or the
         * next, and the remainder is the reduced fraction. Both are
         * exact integer arithmetic on the window - no rounding decides
         * a sign here, which is the same discipline phase 2 keeps with
         * its mask. */
        i2 = ph_bit(&P, d) | (ph_bit(&P, d + 1) << 1);
        if (ph_bit(&P, d - 1)) {
            ph_int Fr;
            Fr = P;
            ph_mask_low(&Fr, d);
            ph_neg_mod_pow2(&T, &Fr, d);     /* |t| = 1 - phi */
            n = i2 + 1;
            tneg = 1;
        } else {
            T = P;
            ph_mask_low(&T, d);
            n = i2;
            tneg = 0;
        }
        tb = ph_bitlen(&T);
        if (tb == 0) {
            /* The window saw an exact multiple of pi/2, which no
             * nonzero dyadic is: it means the cancellation is at least
             * as deep as the window, and there is nothing to widen BY.
             * Double and look again. */
            cft_tr_reduce_widen++;
            wbits *= 2;
            continue;
        }
        vt = tb - 1 - d;                 /* floor(log2 |t|) */

        /* The dropped tail of 2/pi is below 2^-(j0+wbits-1), so the
         * absolute error in |x|*(2/pi) is below 2^-avail. Relative to
         * |t| that is 2^-(avail+vt), and the reduced argument has to
         * carry the deepest working precision plus a guard. */
        avail = j0 + wbits - 1 - e - p;
        if (avail + vt < (long)Wr + 8) {
            long deficit = (long)Wr + 8 - (avail + vt);
            long want = (long)wbits + deficit + 32;
            cft_tr_reduce_widen++;
            wbits = (int)((want + 31) & ~(long)31);
            continue;
        }

        if ((uint64_t)wbits > cft_tr_max_window)
            cft_tr_max_window = (uint64_t)wbits;
        if (lane_vexp(a) >= 0 && vt < -1) {
            uint64_t c = (uint64_t)(-vt - 1);
            if (c > cft_tr_max_cancel)
                cft_tr_max_cancel = c;
        }

        ph_top_bits(&tm, &sh, &T, tb, Wr + 64);
        if (cft_mp_set_bn(&R->t, Wr, tneg, &tm, sh - d))
            return 1;
        mp_bump(&R->t, 1);               /* the window's truncated tail */
        R->quadrant = n & 3;
        R->t_exp2 = vt;
        return 0;
    }
}

/* log(v) for an mp v > 1, treating its stored significand as exact and
 * charging the value's own error back afterwards.
 *
 * mp_log_exact takes an exactly-known dyadic, which is what every
 * phase-1 caller had. asinh, acosh and atanh do not: their logarithm's
 * argument is itself computed. If the true value is within eps
 * relatively of the stored one then the logarithms differ by at most
 * 2*eps ABSOLUTELY, and dividing that by the result's own magnitude
 * turns it back into the relative bound the type carries. Every caller
 * here keeps |log v| above 0.48, so the conversion costs at most three
 * doublings; a caller that did not would get a refusal and an
 * escalation rather than a silent widening. */
static int mp_log_of_mp(cft_mp *r, const cft_mp *v, int W)
{
    cft_mp l;
    uint64_t add;
    long E0;
    int sh;

    if (v->zero || v->sign)
        return 1;
    if (mp_log_exact(&l, &v->m, v->exp, W))
        return 1;
    if (l.zero)
        return 1;                        /* v was exactly 1 */
    E0 = cft_mp_exp2_of(&l);
    if (E0 < -32)
        return 1;                        /* too near 1 to convert the bound */
    add = v->err;
    sh = 1 - (int)E0;
    if (sh > 0) {
        if (sh >= 40 || add > (CFT_MP_ERR_MAX >> sh))
            add = CFT_MP_ERR_MAX;
        else
            add <<= sh;
    } else if (sh < 0) {
        add >>= (-sh > 63 ? 63 : -sh);
    }
    mp_bump(&l, add);
    cft_mp_copy(r, &l);
    return 0;
}

/* log1p of a computed (not exactly known) positive value, in the two
 * regimes phase 1's log1p already justifies: below 1 the atanh form
 * never forms 1 + w, and above it the ordinary logarithm applies with
 * no cancellation, because log(1 + w) is then above log 2. */
static int mp_log1p_of_mp(cft_mp *r, const cft_mp *w, int W)
{
    cft_mp one, s;
    if (w->zero)
        return 1;                        /* the callers screen it */
    if (cft_mp_exp2_of(w) < 0)
        return mp_log1p_small(r, w, W);
    if (cft_mp_set_ui(&one, W, 0, 1, 0))
        return 1;
    if (cft_mp_add(&s, &one, w, W))
        return 1;
    return mp_log_of_mp(r, &s, W);
}

/* ---- the evaluator ------------------------------------------------- */

/* An internal function code, past the ABI's: the magnitude is
 * `quarters` * pi/4. asin(+-1), acos(+-0), acos(-1), atan(+-inf) and
 * every radian row of atan2's axis-and-diagonal table are that, and
 * none of them is exact, so all of them go through the same Ziv loop
 * as everything else. */
#define TR_PI_QUARTERS 100

typedef struct {
    const cft_fmt_desc *f;
    int fn;
    lane a;
    lane b;
    /* phase 2. s is the exactly reduced |x| mod 2 argument of the
     * Pi-variants; k_even and want_cos are the quadrant's answers to
     * "which series is the magnitude"; x_neg is atan2's second
     * operand's sign, which decides pi - a rather than a. */
    cft_bn s_m;
    long   s_e;
    int    k_even;
    int    want_cos;
    int    x_neg;
    int    quarters;
    /* phase 3. The reduction against pi/2 is done ONCE, before the Ziv
     * loop, at the width the deepest attempt could need: the quadrant
     * is exact integer arithmetic and must not change between
     * attempts, because the result's SIGN comes off it. Only the
     * multiplication by pi/2 is redone per precision. */
    tr_pi_red red;
    /* table 9.1's remainder: the INTEGER operand of pown, compound and
     * rootn, carried per element beside the encoding. */
    int64_t nn;
} tr_args;

/* |f(a[,b])| at working precision W. The SIGN of the result is decided
 * exactly by the caller and never by this. */
static int tr_eval(const tr_args *A, int W, cft_mp *r)
{
    const cft_fmt_desc *f = A->f;
    int Wi = tr_wint(f, W);
    cft_mp x, y, t, l, tmp;

    switch (A->fn) {
    case CFT_TR_EXP:
    case CFT_TR_EXPM1:
        if (cft_mp_set_bn(&x, Wi, A->a.sign, &A->a.m, A->a.e))
            return 1;
        if (A->fn == CFT_TR_EXP) {
            if (mp_exp_full(r, &x, Wi))
                return 1;
        } else {
            long v = lane_vexp(&A->a);
            if (v <= -2) {
                if (mp_expm1_core(&t, &x, Wi))
                    return 1;
            } else {
                if (mp_exp_full(&t, &x, Wi))
                    return 1;
                if (cft_mp_set_ui(&tmp, Wi, 0, 1, 0))
                    return 1;
                if (cft_mp_sub(&t, &t, &tmp, Wi))
                    return 1;
            }
            if (t.sign)
                cft_mp_neg(&t);
            cft_mp_copy(r, &t);
        }
        return 0;

    case CFT_TR_EXP2: {
        /* t = k + s with k the integer part and s the fraction, both
         * EXACT on the encoding - no constant is consumed by this
         * reduction, unlike exp's - and then 2^t = 2^k * exp(s ln2)
         * with |s ln2| below ln2. */
        cft_bn ip, frac;
        long k;
        int nb;
        if (A->a.e >= 0)
            return 1;                    /* an integer: handled upstream */
        cft_bn_zero(&ip);
        cft_bn_zero(&frac);
        nb = cft_bn_bitlen(&A->a.m);
        if (-A->a.e >= nb) {
            cft_bn_copy(&frac, &A->a.m);
        } else {
            cft_bn_shr(&ip, &A->a.m, (int)(-A->a.e));
            cft_bn_copy(&frac, &A->a.m);
            cft_bn_mask(&frac, (int)(-A->a.e));
        }
        k = odd_to_long(&ip, 0, A->a.sign);
        if (cft_bn_is_zero(&frac)) {
            if (cft_mp_set_ui(r, Wi, 0, 1, 0))
                return 1;
        } else {
            cft_mp l2;
            if (cft_mp_set_bn(&x, Wi, A->a.sign, &frac, A->a.e))
                return 1;
            if (cft_mp_const(&l2, CFT_MP_C_LN2, Wi))
                return 1;
            if (cft_mp_mul(&t, &x, &l2, Wi))
                return 1;
            if (mp_exp_core(r, &t, Wi))
                return 1;
        }
        cft_mp_shift(r, k);
        return 0;
    }

    case CFT_TR_LOG:
    case CFT_TR_LOG2:
    case CFT_TR_LOG10:
        if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
            return 1;
        if (A->fn == CFT_TR_LOG2 || A->fn == CFT_TR_LOG10) {
            cft_mp c;
            if (cft_mp_const(&c, A->fn == CFT_TR_LOG2 ? CFT_MP_C_LOG2E
                                                      : CFT_MP_C_LOG10E, Wi))
                return 1;
            if (cft_mp_mul(&tmp, &l, &c, Wi))
                return 1;
            cft_mp_copy(&l, &tmp);
        }
        if (l.sign)
            cft_mp_neg(&l);
        cft_mp_copy(r, &l);
        return 0;

    case CFT_TR_LOG1P:
        if (mp_log1p_lane(&l, f, &A->a, Wi))
            return 1;
        if (l.sign)
            cft_mp_neg(&l);
        cft_mp_copy(r, &l);
        return 0;

    case CFT_TR_POW:
        if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
            return 1;
        if (cft_mp_set_bn(&y, Wi, A->b.sign, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_mul(&t, &y, &l, Wi))
            return 1;
        return mp_exp_full(r, &t, Wi);

    case CFT_TR_HYPOT: {
        cft_mp xa, xb, s;
        if (cft_mp_set_bn(&xa, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_set_bn(&xb, Wi, 0, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_mul(&x, &xa, &xa, Wi))
            return 1;
        if (cft_mp_mul(&y, &xb, &xb, Wi))
            return 1;
        if (cft_mp_add(&s, &x, &y, Wi))
            return 1;
        return cft_mp_sqrt(r, &s, Wi);
    }

    /* ---- phase 2 ---------------------------------------------- */

    case TR_PI_QUARTERS: {
        cft_mp pi;
        if (cft_mp_const(&pi, CFT_MP_C_PI, Wi))
            return 1;
        cft_mp_shift(&pi, -2);                 /* pi/4, exactly */
        return cft_mp_mul_ui(r, &pi, (uint32_t)A->quarters, Wi);
    }

    case CFT_TR_SINPI:
    case CFT_TR_COSPI:
    case CFT_TR_TANPI: {
        cft_mp s, pi, v, sn, cs;
        /* |s| <= 1/4 is EXACT on the encoding, so v = pi|s| carries
         * only the constant's own error - no argument reduction
         * against pi happens here at all, which is the whole reason
         * these three are in phase 2. */
        if (cft_mp_set_bn(&s, Wi, 0, &A->s_m, A->s_e))
            return 1;
        if (cft_mp_const(&pi, CFT_MP_C_PI, Wi))
            return 1;
        if (cft_mp_mul(&v, &s, &pi, Wi))
            return 1;
        if (mp_sincos(&sn, &cs, &v, Wi))
            return 1;
        if (A->fn == CFT_TR_TANPI)
            return A->k_even ? cft_mp_div(r, &sn, &cs, Wi)
                             : cft_mp_div(r, &cs, &sn, Wi);
        cft_mp_copy(r, A->want_cos ? &cs : &sn);
        return 0;
    }

    case CFT_TR_ASIN:
    case CFT_TR_ASINPI: {
        cft_mp ax, rt, a;
        if (mp_asin_root(&rt, &A->a, Wi))
            return 1;
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_div(&t, &ax, &rt, Wi))
            return 1;
        if (mp_atan_pos(&a, &t, Wi))
            return 1;
        if (A->fn == CFT_TR_ASINPI)
            return mp_over_pi(r, &a, Wi);
        cft_mp_copy(r, &a);
        return 0;
    }

    case CFT_TR_ACOS:
    case CFT_TR_ACOSPI: {
        cft_mp ax, rt, a, pi;
        if (mp_asin_root(&rt, &A->a, Wi))
            return 1;
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        /* atan(sqrt(1-x^2)/|x|) rather than pi/2 - asin: for |x| just
         * below 1 the difference form cancels the whole answer away,
         * and this one computes a small angle as a small angle. */
        if (cft_mp_div(&t, &rt, &ax, Wi))
            return 1;
        if (mp_atan_pos(&a, &t, Wi))
            return 1;
        if (A->a.sign) {
            /* acos(-|x|) = pi - acos(|x|), and acos(|x|) <= pi/2, so
             * the result never drops below pi/2 and the subtraction
             * costs at most one bit. */
            if (cft_mp_const(&pi, CFT_MP_C_PI, Wi))
                return 1;
            if (cft_mp_sub(&tmp, &pi, &a, Wi))
                return 1;
            cft_mp_copy(&a, &tmp);
        }
        if (A->fn == CFT_TR_ACOSPI)
            return mp_over_pi(r, &a, Wi);
        cft_mp_copy(r, &a);
        return 0;
    }

    case CFT_TR_ATAN:
    case CFT_TR_ATANPI: {
        cft_mp a;
        if (cft_mp_set_bn(&t, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (mp_atan_pos(&a, &t, Wi))
            return 1;
        if (A->fn == CFT_TR_ATANPI)
            return mp_over_pi(r, &a, Wi);
        cft_mp_copy(r, &a);
        return 0;
    }

    case CFT_TR_ATAN2:
    case CFT_TR_ATAN2PI: {
        cft_mp ay, ax, a, pi;
        if (cft_mp_set_bn(&ay, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_set_bn(&ax, Wi, 0, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_div(&t, &ay, &ax, Wi))
            return 1;
        if (mp_atan_pos(&a, &t, Wi))
            return 1;
        if (A->x_neg) {
            /* pi - atan(|y/x|) with atan below pi/2: at most one bit. */
            if (cft_mp_const(&pi, CFT_MP_C_PI, Wi))
                return 1;
            if (cft_mp_sub(&tmp, &pi, &a, Wi))
                return 1;
            cft_mp_copy(&a, &tmp);
        }
        if (A->fn == CFT_TR_ATAN2PI)
            return mp_over_pi(r, &a, Wi);
        cft_mp_copy(r, &a);
        return 0;
    }

    /* ---- phase 3 ---------------------------------------------- */

    case CFT_TR_SIN:
    case CFT_TR_COS:
    case CFT_TR_TAN: {
        cft_mp pi, v, sn, cs;
        /* |r| = |t| * pi/2, with |t| <= about 1/2 from the reduction,
         * so v lands in [0, pi/4] - exactly mp_sincos's domain, and
         * exactly what phase 2 said phase 3 would inherit. */
        if (cft_mp_const(&pi, CFT_MP_C_PI, Wi))
            return 1;
        cft_mp_shift(&pi, -1);                 /* pi/2, exactly */
        if (cft_mp_mul(&v, &A->red.t, &pi, Wi))
            return 1;
        if (v.sign)
            cft_mp_neg(&v);
        if (mp_sincos(&sn, &cs, &v, Wi))
            return 1;
        if (A->fn == CFT_TR_TAN)
            return A->k_even ? cft_mp_div(r, &sn, &cs, Wi)
                             : cft_mp_div(r, &cs, &sn, Wi);
        cft_mp_copy(r, A->want_cos ? &cs : &sn);
        return 0;
    }

    case CFT_TR_SINH: {
        cft_mp ax, u, s, q;
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (v <= -2) {
            /* sinh(x) = u(u+2) / (2(u+1)) with u = expm1(x). For a
             * small x every factor is positive and bounded away from
             * zero, so nothing cancels - where (e^x - e^-x)/2 would
             * lose every bit the answer has. */
            if (mp_expm1_core(&u, &ax, Wi))
                return 1;
            if (cft_mp_set_ui(&s, Wi, 0, 1, 1))
                return 1;
            if (cft_mp_add(&t, &u, &s, Wi))         /* u + 2 */
                return 1;
            if (cft_mp_mul(&q, &u, &t, Wi))
                return 1;
            if (cft_mp_set_ui(&s, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_add(&t, &u, &s, Wi))         /* u + 1 */
                return 1;
            if (cft_mp_div(r, &q, &t, Wi))
                return 1;
            cft_mp_shift(r, -1);
            return 0;
        }
        /* |x| >= 1/2 puts e^|x| above 1.64 and 1/e^|x| below 0.61, so
         * the difference keeps more than four fifths of the larger and
         * costs at most one bit. */
        if (mp_exp_full(&u, &ax, Wi))
            return 1;
        if (cft_mp_set_ui(&s, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_div(&q, &s, &u, Wi))
            return 1;
        if (cft_mp_sub(r, &u, &q, Wi))
            return 1;
        cft_mp_shift(r, -1);
        return 0;
    }

    case CFT_TR_COSH: {
        cft_mp ax, E, one, q;
        /* (E + 1/E)/2, and both terms are positive: cosh is the one
         * function in this set with no cancellation anywhere. */
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (mp_exp_full(&E, &ax, Wi))
            return 1;
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_div(&q, &one, &E, Wi))
            return 1;
        if (cft_mp_add(r, &E, &q, Wi))
            return 1;
        cft_mp_shift(r, -1);
        return 0;
    }

    case CFT_TR_TANH: {
        cft_mp ax, u, two, d;
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        cft_mp_shift(&ax, 1);                       /* 2|x| */
        if (cft_mp_set_ui(&two, Wi, 0, 1, 1))
            return 1;
        if (v <= -2) {
            /* tanh(x) = u/(u+2) with u = expm1(2x): for a small x the
             * numerator is about 2x and the denominator about 2, and
             * neither is a difference. */
            if (mp_expm1_core(&u, &ax, Wi))
                return 1;
        } else {
            cft_mp E, one;
            if (mp_exp_full(&E, &ax, Wi))
                return 1;
            if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_sub(&u, &E, &one, Wi))       /* e^2x - 1 >= e - 1 */
                return 1;
        }
        if (cft_mp_add(&d, &u, &two, Wi))
            return 1;
        return cft_mp_div(r, &u, &d, Wi);
    }

    case CFT_TR_ASINH: {
        cft_mp ax, sq, one, rt, w;
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_mul(&sq, &ax, &ax, Wi))
            return 1;
        if (cft_mp_add(&t, &sq, &one, Wi))          /* 1 + x^2 */
            return 1;
        if (cft_mp_sqrt(&rt, &t, Wi))
            return 1;
        if (v <= -2) {
            /* asinh(x) = log1p(x + x^2/(1 + sqrt(1+x^2))). The second
             * term is sqrt(1+x^2) - 1 written so that it is never
             * formed as a difference; for |x| < 1/2 the whole argument
             * stays below 0.62 and log1p's small regime finishes it. */
            if (cft_mp_add(&t, &rt, &one, Wi))
                return 1;
            if (cft_mp_div(&w, &sq, &t, Wi))
                return 1;
            if (cft_mp_add(&t, &ax, &w, Wi))
                return 1;
            return mp_log1p_small(r, &t, Wi);
        }
        /* |x| >= 1/2 puts x + sqrt(1+x^2) above 1.618, so its logarithm
         * is above 0.48 and the conversion in mp_log_of_mp costs three
         * doublings of the bound and nothing else. */
        if (cft_mp_add(&w, &ax, &rt, Wi))
            return 1;
        return mp_log_of_mp(r, &w, Wi);
    }

    case CFT_TR_ACOSH: {
        cft_mp ax, one, d, s, pr, rt, w;
        /* acosh(x) = log1p((x-1) + sqrt((x-1)(x+1))). For x near 1 the
         * factor x - 1 is EXACT at the working precision - both
         * operands are exact dyadics and Sterbenz applies - so the
         * cancellation amplifies an error of zero, where sqrt(x^2 - 1)
         * formed directly would lose every bit the answer has. Phase
         * 1's log(m') and phase 2's asin root are the same shape. */
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_sub(&d, &ax, &one, Wi))
            return 1;
        if (d.zero || d.sign)
            return 1;                    /* x <= 1 was handled upstream */
        if (cft_mp_add(&s, &ax, &one, Wi))
            return 1;
        if (cft_mp_mul(&pr, &d, &s, Wi))
            return 1;
        if (cft_mp_sqrt(&rt, &pr, Wi))
            return 1;
        if (cft_mp_add(&w, &d, &rt, Wi))
            return 1;
        return mp_log1p_of_mp(r, &w, Wi);
    }

    case CFT_TR_ATANH: {
        cft_mp ax, one, den, u;
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&ax, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (v <= -3) {
            /* |x| <= 1/4: the atanh series on the EXACT operand, which
             * is the one place in this set where the argument carries
             * no error at all. mp_atanh2 returns twice the value. */
            if (mp_atanh2(r, &ax, Wi))
                return 1;
            cft_mp_shift(r, -1);
            return 0;
        }
        /* atanh(x) = log1p(2x/(1-x))/2, and 1 - |x| is exact at every
         * working precision this reaches (|x| > 1/8 there, so the
         * difference needs at most p + 3 bits), which is what keeps the
         * cancellation next to 1 free. */
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        if (cft_mp_sub(&den, &one, &ax, Wi))
            return 1;
        if (den.zero || den.sign)
            return 1;                    /* |x| >= 1 was handled upstream */
        if (cft_mp_div(&u, &ax, &den, Wi))
            return 1;
        cft_mp_shift(&u, 1);
        if (mp_log1p_of_mp(r, &u, Wi))
            return 1;
        cft_mp_shift(r, -1);
        return 0;
    }

    /* ---- the rest of table 9.1 --------------------------------- */

    case CFT_TR_EXP2M1: {
        cft_mp l2;
        long v = lane_vexp(&A->a);
        /* 2^x - 1 = expm1(x ln2), never exp(x ln2) - 1: for a small x
         * the second form loses every bit the answer has. |x| < 1/4
         * puts |x ln2| below 0.174, inside mp_expm1_core's domain. */
        if (cft_mp_set_bn(&x, Wi, A->a.sign, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_const(&l2, CFT_MP_C_LN2, Wi))
            return 1;
        if (cft_mp_mul(&t, &x, &l2, Wi))
            return 1;
        if (v <= -2) {
            if (mp_expm1_core(&l, &t, Wi))
                return 1;
        } else {
            if (mp_exp_full(&l, &t, Wi))
                return 1;
            if (cft_mp_set_ui(&tmp, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_sub(&l, &l, &tmp, Wi))
                return 1;
        }
        if (l.sign)
            cft_mp_neg(&l);
        cft_mp_copy(r, &l);
        return 0;
    }

    case CFT_TR_EXP10:
    case CFT_TR_EXP10M1: {
        cft_mp l10;
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&x, Wi, A->a.sign, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_const(&l10, CFT_MP_C_LN10, Wi))
            return 1;
        if (cft_mp_mul(&t, &x, &l10, Wi))
            return 1;
        if (A->fn == CFT_TR_EXP10)
            return mp_exp_full(r, &t, Wi);
        /* |x| < 1/8 puts |x ln10| below 0.288, which mp_expm1_core
         * carries; anything larger takes the general path, where
         * exp(t) - 1 keeps at least a quarter of the larger operand and
         * costs two bits. */
        if (v <= -4) {
            if (mp_expm1_core(&l, &t, Wi))
                return 1;
        } else {
            if (mp_exp_full(&l, &t, Wi))
                return 1;
            if (cft_mp_set_ui(&tmp, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_sub(&l, &l, &tmp, Wi))
                return 1;
        }
        if (l.sign)
            cft_mp_neg(&l);
        cft_mp_copy(r, &l);
        return 0;
    }

    case CFT_TR_LOG2P1:
    case CFT_TR_LOG10P1: {
        cft_mp c;
        if (mp_log1p_lane(&l, f, &A->a, Wi))
            return 1;
        if (cft_mp_const(&c, A->fn == CFT_TR_LOG2P1 ? CFT_MP_C_LOG2E
                                                    : CFT_MP_C_LOG10E, Wi))
            return 1;
        if (cft_mp_mul(&tmp, &l, &c, Wi))
            return 1;
        if (tmp.sign)
            cft_mp_neg(&tmp);
        cft_mp_copy(r, &tmp);
        return 0;
    }

    case CFT_TR_RSQRT: {
        cft_mp s, one;
        /* The evaluator's own square root and one division. The tile's
         * RSQRT_SEED opcode is a LATER fast path for the narrow formats
         * and would have to reproduce these bits exactly; it is not
         * part of this contract, and nothing here reads it. */
        if (cft_mp_set_bn(&x, Wi, 0, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_sqrt(&s, &x, Wi))
            return 1;
        if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
            return 1;
        return cft_mp_div(r, &one, &s, Wi);
    }

    case CFT_TR_POWN: {
        cft_mp nn;
        if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
            return 1;
        if (mp_set_i64(&nn, Wi, A->nn))
            return 1;
        if (cft_mp_mul(&t, &nn, &l, Wi))
            return 1;
        return mp_exp_full(r, &t, Wi);
    }

    case CFT_TR_POWR:
        /* exp(y log x) with x > 0 by construction - pow's evaluation
         * with the sign question deleted. */
        if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
            return 1;
        if (cft_mp_set_bn(&y, Wi, A->b.sign, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_mul(&t, &y, &l, Wi))
            return 1;
        return mp_exp_full(r, &t, Wi);

    case CFT_TR_COMPOUND: {
        cft_mp nn;
        /* exp(n log1p(x)), and log1p rather than log(1 + x) for the
         * reason phase 1 gives: 1 + x formed at the working precision
         * rounds to 1 for a tiny x and takes the answer with it. */
        if (mp_log1p_lane(&l, f, &A->a, Wi))
            return 1;
        if (mp_set_i64(&nn, Wi, A->nn))
            return 1;
        if (cft_mp_mul(&t, &nn, &l, Wi))
            return 1;
        return mp_exp_full(r, &t, Wi);
    }

    case CFT_TR_ROOTN: {
        cft_mp nn, q, s;
        int64_t n = A->nn;
        /* The square roots go through the evaluator's own, which is
         * exact to within one unit in the last place by construction;
         * everything else is exp(log(x)/n), whose absolute error in the
         * exponent's argument becomes the result's relative error - the
         * same accounting pow already carries. */
        if (n == 2 || n == -2) {
            if (cft_mp_set_bn(&x, Wi, 0, &A->a.m, A->a.e))
                return 1;
            if (cft_mp_sqrt(&s, &x, Wi))
                return 1;
            if (n == 2) {
                cft_mp_copy(r, &s);
                return 0;
            }
            if (cft_mp_set_ui(&tmp, Wi, 0, 1, 0))
                return 1;
            return cft_mp_div(r, &tmp, &s, Wi);
        }
        if (n == -1) {
            if (cft_mp_set_bn(&x, Wi, 0, &A->a.m, A->a.e))
                return 1;
            if (cft_mp_set_ui(&tmp, Wi, 0, 1, 0))
                return 1;
            return cft_mp_div(r, &tmp, &x, Wi);
        }
        if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
            return 1;
        if (mp_set_i64(&nn, Wi, n))
            return 1;
        if (cft_mp_div(&q, &l, &nn, Wi))
            return 1;
        return mp_exp_full(r, &q, Wi);
    }

    default:
        return 1;
    }
}

/* The Ziv loop: evaluate, try to round, escalate, and fail loudly. */
static cft_status tr_ziv(const tr_args *A, int sign, int rnd, cft_bn *out,
                         uint32_t *flags)
{
    const cft_fmt_desc *f = A->f;
    int cap = tr_prec_cap(f);
    int W = tr_start_prec(f);
    int first = 1;

    cft_tr_ziv_calls++;
    for (;;) {
        cft_mp r;
        int decided = 0;
        if (!first)
            cft_tr_escalations++;
        first = 0;
        if ((uint64_t)W > cft_tr_max_prec)
            cft_tr_max_prec = (uint64_t)W;
        /* An evaluation that FAILS below the cap has run out of
         * container width or off the end of an internal screen at a
         * precision too coarse to see the answer - not proof that no
         * precision can. pow(1 + 2^-112, 2^113) at fp128 does it when
         * the loop is forced to start at 64 bits: the logarithm comes
         * out as 2*atanh(1/2) instead of 2^-112, the exponential's
         * argument-reduction multiple then lands past its own cap, and
         * mp_exp_full refuses. The answer to that is the same as the
         * answer to an undecided rounding - raise the precision - and
         * only a failure AT the cap is a refusal.
         *
         * Found on 2026-09-03, once mpfr_check.c's transcendental pool
         * started carrying the directed operands it had always meant
         * to (its success test had been inverted since it was
         * written), which put pow of a base one ulp from 1 against a
         * huge exponent into the forced-escalation run for the first
         * time. */
        if (tr_eval(A, W, &r)) {
            if (W >= cap)
                return CFT_ERR_INTERNAL;
            W = 2 * W < cap ? 2 * W : cap;
            continue;
        }
        /* A result that came out EXACTLY zero at this precision means
         * the working precision was too coarse to see the value at all
         * - log(1 + 2^-112) at fp128 does it once the precision drops
         * below p - and the answer is to raise it, not to refuse. The
         * exact zeros of these functions are all decided long before
         * the loop. */
        if (!r.zero &&
            cft_mp_round(&r, sign, f, rnd, out, flags, &decided)) {
            if (W >= cap)
                return CFT_ERR_INTERNAL;
            W = 2 * W < cap ? 2 * W : cap;
            continue;
        }
        if (decided)
            return CFT_OK;
        if (W >= cap)
            return CFT_ERR_INTERNAL;
        W = 2 * W < cap ? 2 * W : cap;
    }
}

/* The screen: deliver the overflow or underflow response when the
 * result's base-two logarithm is provably outside the format. Returns
 * 1 when it fired (and wrote out/flags), 0 to fall through, -1 on an
 * internal failure.
 *
 * The thresholds carry a whole unit past what they need - emax + 2
 * rather than emax + 1 - to match the model, which needs the slack
 * because mpmath's accuracy is a few ulps rather than exact. Here the
 * enclosure is already rigorous, so the extra unit only means a few
 * more inputs take the ordinary path, which answers them identically. */
static int tr_screen(const tr_args *A, const cft_mp *log2r, int sign,
                     int rnd, cft_bn *out, uint32_t *flags)
{
    const cft_fmt_desc *f = A->f;
    if (cft_mp_cmp_int(log2r, (int64_t)f->emax + 2) > 0)
        return round_overflowing(f, sign, rnd, out, flags) ? -1 : 1;
    if (cft_mp_cmp_int(log2r, (int64_t)f->emin - f->man_w - 2) < 0)
        return round_underflowing(f, sign, rnd, out, flags) ? -1 : 1;
    return 0;
}

/* log2 of the result's magnitude, at screening precision. The operand
 * is exact at that precision because it carries at most p bits, which
 * is what makes a screen an enclosure of the RIGHT function. */
static int tr_log2_estimate(const tr_args *A, cft_mp *q)
{
    const cft_fmt_desc *f = A->f;
    int W = f->prec + 32;
    cft_mp x, l, e2, t;

    if (cft_mp_const(&e2, CFT_MP_C_LOG2E, W))
        return 1;
    switch (A->fn) {
    case CFT_TR_EXP:
    case CFT_TR_EXPM1:
        if (cft_mp_set_bn(&x, W, A->a.sign, &A->a.m, A->a.e))
            return 1;
        return cft_mp_mul(q, &x, &e2, W);
    case CFT_TR_SINH:
    case CFT_TR_COSH:
        /* log2 of e^|x|, which brackets both: sinh and cosh lie between
         * e^|x|/4 and e^|x| for every |x| >= 1, so an enclosure of this
         * above emax + 3 proves the result is above 2^(emax+1). */
        if (cft_mp_set_bn(&x, W, 0, &A->a.m, A->a.e))
            return 1;
        return cft_mp_mul(q, &x, &e2, W);
    case CFT_TR_EXP2:
        return cft_mp_set_bn(q, W, A->a.sign, &A->a.m, A->a.e);
    case CFT_TR_POW:
    case CFT_TR_POWR:
        if (mp_log_exact(&l, &A->a.m, A->a.e, W))
            return 1;
        if (cft_mp_set_bn(&x, W, A->b.sign, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_mul(&t, &x, &l, W))
            return 1;
        return cft_mp_mul(q, &t, &e2, W);
    case CFT_TR_EXP2M1:
        return cft_mp_set_bn(q, W, A->a.sign, &A->a.m, A->a.e);
    case CFT_TR_EXP10:
    case CFT_TR_EXP10M1: {
        cft_mp l10;
        if (cft_mp_set_bn(&x, W, A->a.sign, &A->a.m, A->a.e))
            return 1;
        if (cft_mp_const(&l10, CFT_MP_C_LN10, W))
            return 1;
        if (cft_mp_mul(&t, &x, &l10, W))
            return 1;
        return cft_mp_mul(q, &t, &e2, W);
    }
    case CFT_TR_POWN: {
        cft_mp nn;
        if (mp_log_exact(&l, &A->a.m, A->a.e, W))
            return 1;
        if (mp_set_i64(&nn, W, A->nn))
            return 1;
        if (cft_mp_mul(&t, &nn, &l, W))
            return 1;
        return cft_mp_mul(q, &t, &e2, W);
    }
    case CFT_TR_ROOTN: {
        cft_mp nn, dq;
        if (mp_log_exact(&l, &A->a.m, A->a.e, W))
            return 1;
        if (mp_set_i64(&nn, W, A->nn))
            return 1;
        if (cft_mp_div(&dq, &l, &nn, W))
            return 1;
        return cft_mp_mul(q, &dq, &e2, W);
    }
    case CFT_TR_COMPOUND: {
        cft_mp nn;
        /* A WIDER screening precision than the rest, and for a stated
         * reason: mp_log1p_lane's middle regime forms 1 + x and treats
         * it as exact, which it is only at 2p+31 bits or more. p+32
         * would enclose the logarithm of a ROUNDED operand - a correct
         * answer to the wrong question. Firing a screen on that could
         * deliver an overflow for an input that does not overflow. */
        int Wc = 2 * f->prec + 72;
        cft_mp e2c;
        if (cft_mp_const(&e2c, CFT_MP_C_LOG2E, Wc))
            return 1;
        if (mp_log1p_lane(&l, f, &A->a, Wc))
            return 1;
        if (mp_set_i64(&nn, Wc, A->nn))
            return 1;
        if (cft_mp_mul(&t, &nn, &l, Wc))
            return 1;
        return cft_mp_mul(q, &t, &e2c, Wc);
    }
    default:
        return 1;
    }
}

/* ---- per-function drivers ------------------------------------------ */

static cft_status do_exp_family(const cft_fmt_desc *f, int fn, const lane *a,
                                int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    int minus_one = (fn == CFT_TR_EXPM1);
    int base_two = (fn == CFT_TR_EXP2);
    long v;
    int sign;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign) {
            if (minus_one)
                put_one(f, 1, out);          /* expm1(-inf) = -1 */
            else
                cft_sf_zero(f, 0, out);      /* exp(-inf) = +0 */
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        if (minus_one)
            cft_sf_zero(f, a->sign, out);    /* expm1(+-0) = +-0 */
        else
            put_one(f, 0, out);
        return CFT_OK;
    }

    if (base_two) {
        cft_bn M;
        long E;
        lane_odd(a, &M, &E);
        if (E >= 0) {
            /* an integer argument: 2^n exactly, or clause 7's flags */
            long n = odd_to_long(&M, E, a->sign);
            cft_bn t;
            cft_tr_exact++;
            if (n > f->emax)
                return round_overflowing(f, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            if (n < f->emin - f->man_w)
                return round_underflowing(f, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            cft_bn_zero(&t);
            cft_bn_set_u32(&t, 1);
            return round_exact(f, 0, &t, n, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
    }

    v = lane_vexp(a);
    if (minus_one) {
        if (v <= -(long)(f->prec + 3))
            return round_neighbour(f, a, a->sign == 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
    } else if (v <= -(long)(f->prec + 4)) {
        lane one;
        memset(&one, 0, sizeof one);
        one.kind = K_NORM;
        one.sign = 0;
        cft_bn_zero(&one.m);
        cft_bn_set_u32(&one.m, 1);
        (void)cft_bn_shl(&one.m, &one.m, f->man_w);
        one.e = -(long)f->man_w;
        return round_neighbour(f, &one, a->sign == 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    A.f = f;
    A.fn = fn;
    A.a = *a;
    memset(&A.b, 0, sizeof A.b);
    sign = (minus_one && a->sign) ? 1 : 0;

    {
        cft_mp q;
        if (tr_log2_estimate(&A, &q))
            return CFT_ERR_INTERNAL;
        if (minus_one) {
            if (cft_mp_cmp_int(&q, (int64_t)f->emax + 2) > 0)
                return round_overflowing(f, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            if (cft_mp_cmp_int(&q, -(int64_t)(f->prec + 3)) < 0) {
                /* exp(x) is below 2^-(p+2): expm1(x) sits that far
                 * above -1, and no precision separates them. */
                lane negone;
                memset(&negone, 0, sizeof negone);
                negone.kind = K_NORM;
                negone.sign = 1;
                cft_bn_zero(&negone.m);
                cft_bn_set_u32(&negone.m, 1);
                (void)cft_bn_shl(&negone.m, &negone.m, f->man_w);
                negone.e = -(long)f->man_w;
                return round_neighbour(f, &negone, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            }
        } else {
            int s = tr_screen(&A, &q, sign, rnd, out, flags);
            if (s < 0)
                return CFT_ERR_INTERNAL;
            if (s > 0)
                return CFT_OK;
        }
    }
    return tr_ziv(&A, sign, rnd, out, flags);
}

static cft_status do_log_family(const cft_fmt_desc *f, int fn, const lane *a,
                                int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn M;
    long E;
    int sign;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_sf_inf(f, 1, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (a->sign) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        cft_sf_inf(f, 0, out);
        return CFT_OK;
    }

    lane_odd(a, &M, &E);
    if (E == 0 && cft_bn_bitlen(&M) == 1) {        /* x == 1 */
        cft_tr_exact++;
        cft_sf_zero(f, 0, out);
        return CFT_OK;
    }
    if (fn == CFT_TR_LOG2 && cft_bn_bitlen(&M) == 1) {
        cft_bn n;
        cft_tr_exact++;
        cft_bn_zero(&n);
        cft_bn_set_u32(&n, (uint32_t)(E < 0 ? -E : E));
        return round_exact(f, E < 0, &n, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }
    if (fn == CFT_TR_LOG10 && E >= 0 && E <= f->prec) {
        cft_bn five, acc, t;
        long i;
        cft_bn_zero(&five);
        cft_bn_set_u32(&five, 5);
        cft_bn_zero(&acc);
        cft_bn_set_u32(&acc, 1);
        for (i = 0; i < E; i++) {
            if (cft_bn_mul(&t, &acc, &five))
                return CFT_ERR_INTERNAL;
            cft_bn_copy(&acc, &t);
        }
        if (cft_bn_cmp(&acc, &M) == 0) {           /* x == 10^E */
            cft_bn n;
            cft_tr_exact++;
            if (E == 0) {
                cft_sf_zero(f, 0, out);
                return CFT_OK;
            }
            cft_bn_zero(&n);
            cft_bn_set_u32(&n, (uint32_t)E);
            return round_exact(f, 0, &n, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
    }

    A.f = f;
    A.fn = fn;
    A.a = *a;
    memset(&A.b, 0, sizeof A.b);
    sign = lane_vexp(a) < 0 ? 1 : 0;
    return tr_ziv(&A, sign, rnd, out, flags);
}

static cft_status do_log1p(const cft_fmt_desc *f, const lane *a, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn M;
    long E;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign) {
            cft_sf_qnan(f, out);
            *flags = CFT_SF_INVALID;
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);
        return CFT_OK;
    }
    lane_odd(a, &M, &E);
    if (a->sign && E == 0 && cft_bn_bitlen(&M) == 1) {   /* x == -1 */
        cft_sf_inf(f, 1, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (a->sign && lane_vexp(a) >= 0) {                  /* x < -1 */
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (lane_vexp(a) <= -(long)(f->prec + 3))
        return round_neighbour(f, a, a->sign == 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    A.f = f;
    A.fn = CFT_TR_LOG1P;
    A.a = *a;
    memset(&A.b, 0, sizeof A.b);
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

/* pow's exact-value test: |x|**y as (m, e) when it is a dyadic
 * rational whose odd part fits in p+1 bits - which is exactly the
 * condition for it to be able to sit ON a rounding boundary. Returns 1
 * when no such value exists, and that is a proof rather than a shrug:
 * the value is then irrational, or rational but not dyadic, or dyadic
 * with an odd part too wide to be a grid point or a midpoint, and the
 * enclosure decides it in finite time. */
static int pow_dyadic(const cft_fmt_desc *f, const lane *x, const lane *y,
                      cft_bn *m, long *e)
{
    cft_bn M, Y, root, r;
    long E, F, n;
    int p = f->prec, k, i;

    lane_odd(x, &M, &E);
    lane_odd(y, &Y, &F);

    if (F >= 0) {
        int ybits = cft_bn_bitlen(&Y);
        if (cft_bn_bitlen(&M) == 1) {          /* |x| is a power of two */
            long nn = odd_to_long(&Y, F, y->sign);
            cft_bn_zero(m);
            cft_bn_set_u32(m, 1);
            *e = sat_mul(E, nn);
            return 0;
        }
        if (y->sign)
            return 1;                          /* 1/(odd > 1): not dyadic */
        if (ybits + F > 12)
            return 1;                          /* n > p+1 for every format */
        n = 0;
        for (i = ybits - 1; i >= 0; i--)
            n = (n << 1) | cft_bn_bit(&Y, i);
        n <<= F;
        if (n > p + 1)
            return 1;
        if (odd_pow(m, &M, n, p + 1))
            return 1;
        *e = sat_mul(E, n);
        return 0;
    }

    /* y = +-Y / 2^k with Y odd: |x|**y is rational only if |x| is an
     * exact 2^k-th power - Y odd forces every prime exponent of M, and
     * E, to be divisible by 2^k. */
    k = (int)(-F);
    if (k > 24)
        return 1;
    if (E & (((long)1 << k) - 1))
        return 1;
    if (cft_bn_bitlen(&M) == 1) {
        cft_bn_zero(&root);
        cft_bn_set_u32(&root, 1);
    } else if (odd_root_2k(&root, &M, k)) {
        return 1;
    }
    if (cft_bn_bitlen(&root) == 1) {
        long nn = odd_to_long(&Y, 0, y->sign);
        cft_bn_zero(m);
        cft_bn_set_u32(m, 1);
        *e = sat_mul(E >> k, nn);
        return 0;
    }
    if (y->sign)
        return 1;
    if (cft_bn_bitlen(&Y) > 12)
        return 1;
    n = 0;
    for (i = cft_bn_bitlen(&Y) - 1; i >= 0; i--)
        n = (n << 1) | cft_bn_bit(&Y, i);
    if (n > p + 1)
        return 1;
    if (odd_pow(&r, &root, n, p + 1))
        return 1;
    cft_bn_copy(m, &r);
    *e = sat_mul(E >> k, n);
    return 0;
}

static cft_status do_pow(const cft_fmt_desc *f, const lane *x, const lane *y,
                         int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;
    long e;
    int y_int, y_odd, sign;

    *flags = 0;
    if ((x->kind == K_NAN && x->signaling) ||
        (y->kind == K_NAN && y->signaling)) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    /* The two rows that outrank even a quiet NaN operand. */
    if (y->kind == K_ZERO) {
        put_one(f, 0, out);
        return CFT_OK;
    }
    if (x->kind != K_NAN && !x->sign && lane_is_one(x)) {
        put_one(f, 0, out);
        return CFT_OK;
    }
    if (x->kind == K_NAN || y->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }

    /* An infinite exponent first, so pow(+-0, -inf) takes the |x| < 1
     * row - +inf, and NO divideByZero: that signal is the pole at a
     * FINITE negative exponent, not the limit. */
    if (y->kind == K_INF) {
        int gt1;
        if (x->kind != K_ZERO && x->kind != K_INF && lane_is_one(x)) {
            put_one(f, 0, out);              /* pow(-1, +-inf) = 1 */
            return CFT_OK;
        }
        gt1 = (x->kind == K_INF) ? 1
            : (x->kind == K_ZERO ? 0 : lane_vexp(x) >= 0);
        if (gt1 == !y->sign)
            cft_sf_inf(f, 0, out);
        else
            cft_sf_zero(f, 0, out);
        return CFT_OK;
    }

    lane_integrality(y, &y_int, &y_odd);

    if (x->kind == K_ZERO) {
        int neg = x->sign && y_odd;
        if (y->sign) {
            cft_sf_inf(f, neg, out);
            *flags = CFT_SF_DIVZERO;
        } else {
            cft_sf_zero(f, neg, out);
        }
        return CFT_OK;
    }
    if (x->kind == K_INF) {
        int neg = x->sign && y_odd;
        if (y->sign)
            cft_sf_zero(f, neg, out);
        else
            cft_sf_inf(f, neg, out);
        return CFT_OK;
    }
    if (x->sign && !y_int) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }

    sign = (x->sign && y_odd) ? 1 : 0;

    if (pow_dyadic(f, x, y, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (vexp < f->emin - f->man_w - 1)
            return round_underflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, sign, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    A.f = f;
    A.fn = CFT_TR_POW;
    A.a = *x;
    A.a.sign = 0;
    A.b = *y;

    {
        cft_mp q;
        int s;
        if (tr_log2_estimate(&A, &q))
            return CFT_ERR_INTERNAL;
        s = tr_screen(&A, &q, sign, rnd, out, flags);
        if (s < 0)
            return CFT_ERR_INTERNAL;
        if (s > 0)
            return CFT_OK;
        /* A result that cannot be separated from 1: |y log2 x| below
         * 2^-(p+3) puts x**y strictly inside the half gap next to 1,
         * on the side the exact operand signs give. */
        if (!q.zero && cft_mp_exp2_of(&q) + 4 < -(long)(f->prec + 3)) {
            lane one;
            int up = (lane_vexp(x) >= 0) != (y->sign != 0);
            memset(&one, 0, sizeof one);
            one.kind = K_NORM;
            one.sign = sign;
            cft_bn_zero(&one.m);
            cft_bn_set_u32(&one.m, 1);
            (void)cft_bn_shl(&one.m, &one.m, f->man_w);
            one.e = -(long)f->man_w;
            return round_neighbour(f, &one, up, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
    }
    return tr_ziv(&A, sign, rnd, out, flags);
}

/* hypot's exact-value test: sqrt(x^2 + y^2) when the sum is a perfect
 * square in the dyadic rationals. x^2 and y^2 have odd significands, so
 * their sum loses at most one low bit to carries - a pair whose set
 * bits span more than p+6 places therefore has a sum whose odd part is
 * wider than 2p+2 bits, whose square root cannot be a boundary. */
static int hypot_dyadic(const cft_fmt_desc *f, const lane *x, const lane *y,
                        cft_bn *m, long *e)
{
    cft_bn xs, ys, s, root;
    long ex = x->e, ey = y->e, e0, total;
    long top, bot;
    int lowx = 0, lowy = 0, i, exact, sh;

    while (lowx < cft_bn_bitlen(&x->m) && !cft_bn_bit(&x->m, lowx))
        lowx++;
    while (lowy < cft_bn_bitlen(&y->m) && !cft_bn_bit(&y->m, lowy))
        lowy++;
    top = ex + cft_bn_bitlen(&x->m);
    if (ey + cft_bn_bitlen(&y->m) > top)
        top = ey + cft_bn_bitlen(&y->m);
    bot = ex + lowx < ey + lowy ? ex + lowx : ey + lowy;
    if (top - bot > f->prec + 6)
        return 1;

    e0 = ex < ey ? 2 * ex : 2 * ey;
    if (cft_bn_mul(&xs, &x->m, &x->m))
        return 1;
    if (cft_bn_shl(&xs, &xs, (int)(2 * ex - e0)))
        return 1;
    if (cft_bn_mul(&ys, &y->m, &y->m))
        return 1;
    if (cft_bn_shl(&ys, &ys, (int)(2 * ey - e0)))
        return 1;
    if (cft_bn_add(&s, &xs, &ys))
        return 1;
    sh = 0;
    for (i = 0; i < cft_bn_bitlen(&s); i++) {
        if (cft_bn_bit(&s, i))
            break;
        sh++;
    }
    cft_bn_shr(&s, &s, sh);
    total = e0 + sh;
    if (total & 1)
        return 1;
    if (cft_mp_isqrt(&root, &exact, &s))
        return 1;
    if (!exact)
        return 1;
    if (cft_bn_bitlen(&root) > f->prec + 1)
        return 1;
    cft_bn_copy(m, &root);
    *e = total / 2;
    return 0;
}

static cft_status do_hypot(const cft_fmt_desc *f, const lane *x, const lane *y,
                           int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;
    long e;
    const lane *big, *small;

    *flags = 0;
    if ((x->kind == K_NAN && x->signaling) ||
        (y->kind == K_NAN && y->signaling)) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (x->kind == K_INF || y->kind == K_INF) {
        cft_sf_inf(f, 0, out);
        return CFT_OK;
    }
    if (x->kind == K_NAN || y->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }
    if (x->kind == K_ZERO && y->kind == K_ZERO) {
        cft_sf_zero(f, 0, out);
        return CFT_OK;
    }
    if (x->kind == K_ZERO || y->kind == K_ZERO) {
        const lane *nz = x->kind == K_ZERO ? y : x;
        return round_exact(f, 0, &nz->m, nz->e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    if (hypot_dyadic(f, x, y, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, 0, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    /* A dominant operand: sqrt(X^2+Y^2) - X < Y^2/(2X), so once
     * 2*esml + p + 2 < 2*ebig the excess is below a quarter of the gap
     * above the larger magnitude, and the side (always up) settles
     * it. */
    if (lane_vexp(x) >= lane_vexp(y)) {
        big = x; small = y;
    } else {
        big = y; small = x;
    }
    if (2 * lane_vexp(small) + f->prec + 2 < 2 * lane_vexp(big)) {
        lane u = *big;
        u.sign = 0;
        return round_neighbour(f, &u, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    A.f = f;
    A.fn = CFT_TR_HYPOT;
    A.a = *x;
    A.a.sign = 0;
    A.b = *y;
    A.b.sign = 0;
    return tr_ziv(&A, 0, rnd, out, flags);
}


/* ---- phase 2: exact helpers on the encoding ------------------------- */

/* q = a / b when b divides a exactly; returns 1 when it does not.
 * Both operands here are ODD SIGNIFICANDS, so at most p bits wide, and
 * schoolbook is the whole of it. bigint.h deliberately carries no
 * division and this is the only place outside mpfloat.c that wants
 * one. */
static int bn_exact_div(cft_bn *q, const cft_bn *a, const cft_bn *b)
{
    cft_bn rem;
    int i, nb = cft_bn_bitlen(a);
    cft_bn_zero(q);
    cft_bn_zero(&rem);
    for (i = nb - 1; i >= 0; i--) {
        if (cft_bn_shl(&rem, &rem, 1))
            return 1;
        if (cft_bn_bit(a, i))
            cft_bn_setbit(&rem, 0);
        if (cft_bn_shl(q, q, 1))
            return 1;
        if (cft_bn_cmp(&rem, b) >= 0) {
            cft_bn_sub(&rem, &rem, b);
            cft_bn_setbit(q, 0);
        }
    }
    return cft_bn_is_zero(&rem) ? 0 : 1;
}

/* |a| == |b| for two finite nonzero lanes. The exponents are compared
 * first so the alignment shift can never leave the container: two
 * values with the same base-two exponent differ by at most p places. */
static int lane_mag_eq(const lane *a, const lane *b)
{
    cft_bn ma, mb;
    long e0;
    if (lane_vexp(a) != lane_vexp(b))
        return 0;
    e0 = a->e < b->e ? a->e : b->e;
    if (cft_bn_shl(&ma, &a->m, (int)(a->e - e0)))
        return 0;
    if (cft_bn_shl(&mb, &b->m, (int)(b->e - e0)))
        return 0;
    return cft_bn_cmp(&ma, &mb) == 0;
}

/* |y| / |x| as an exact dyadic m * 2^e with m odd, or 1 when the
 * quotient is not a dyadic rational at all.
 *
 * |y|/|x| = (My/Mx) * 2^(Ey-Ex) with both odd parts, so it is dyadic
 * exactly when Mx divides My - and the quotient's odd part is then no
 * wider than My. That is why atan2's neighbour case never has to think
 * about an odd part wider than p bits. */
static int lane_exact_quotient(const lane *y, const lane *x, cft_bn *m,
                               long *e)
{
    cft_bn My, Mx;
    long Ey, Ex;
    lane_odd(y, &My, &Ey);
    lane_odd(x, &Mx, &Ex);
    if (bn_exact_div(m, &My, &Mx))
        return 1;
    *e = Ey - Ex;
    return 0;
}

/* Round a value known to lie strictly between the exact dyadic
 * V = m * 2^e and V -+ a quarter of the format's grid step there.
 *
 * round_neighbour above starts from a representable ENCODING, which is
 * not enough for atan2: the value it must sit beside is the quotient
 * y/x, and that can land on a subnormal MIDPOINT rather than on the
 * grid - atan2(minSubnormal, 2) is exactly that case, and a value just
 * below a midpoint rounds differently from the midpoint itself. So this
 * one works from the dyadic directly and derives the step.
 *
 * Returns 1 when V is not on the eighth-step grid, which the callers
 * screen for; falling through to the enclosure is then correct, because
 * a V that coarse is not a rounding boundary. */
static int round_side(const cft_fmt_desc *f, int sign, const cft_bn *m,
                      long e, int away, int rnd, cft_bn *out,
                      uint32_t *flags)
{
    cft_bn w;
    long vexp, g;

    vexp = e + cft_bn_bitlen(m) - 1;
    g = vexp - (long)f->prec + 1;
    if (g < (long)f->emin - f->man_w)
        g = (long)f->emin - f->man_w;
    if (e < g - 3)
        return 1;
    cft_tr_neighbour++;
    if (cft_bn_shl(&w, m, (int)(e - g + 3)))
        return 1;
    if (away) {
        if (cft_bn_inc(&w))
            return 1;
    } else {
        if (cft_bn_is_zero(&w))
            return 1;
        cft_bn_dec(&w);
    }
    return round_exact(f, sign, &w, g - 3, rnd, out, flags);
}

/* A witness beside the exactly representable 1 or 1/2. */
static int round_side_of(const cft_fmt_desc *f, int sign, long e, int away,
                         int rnd, cft_bn *out, uint32_t *flags)
{
    cft_bn one;
    cft_bn_zero(&one);
    cft_bn_set_u32(&one, 1);
    return round_side(f, sign, &one, e, away, rnd, out, flags);
}

/* |x| mod 2 = k/2 + S * 2^e, EXACTLY, and that is the whole reason the
 * Pi-variants belong to phase 2 rather than to the reduction problem:
 * a dyadic operand reduced modulo 2 is a mask, at every magnitude, with
 * no constant consumed and no cancellation possible. sinPi(2^262000) is
 * decided by integer arithmetic where sin(2^262000) would need pi to a
 * quarter of a million bits.
 *
 * Returns k in 0..4 and writes |S| with its sign. S == 0 exactly when
 * |x| is a half-integer, which is where every exact case of the family
 * lives - so the callers, which have already handled those, can assert
 * that it is not. */
static int lane_pi_reduce(const lane *L, cft_bn *smag, int *sneg, long *se)
{
    cft_bn tm, low;
    long k2, d;
    int k0, carry, k, nb;

    cft_bn_zero(smag);
    *sneg = 0;
    *se = 0;
    if (L->e >= 1)                       /* every bit is above 2^1 */
        return 0;                        /* an even integer */
    k2 = -L->e;
    nb = cft_bn_bitlen(&L->m);
    if (k2 >= (long)nb + 2) {
        /* |x| < 1/4, so the reduction is the identity and k is 0 */
        cft_bn_copy(smag, &L->m);
        *se = L->e;
        return 0;
    }
    cft_bn_copy(&tm, &L->m);
    if (k2 + 1 < nb)
        cft_bn_mask(&tm, (int)(k2 + 1));
    if (k2 == 0)                         /* an integer: t is 0 or 1 */
        return 2 * cft_bn_bit(&tm, 0);
    d = k2 - 1;
    if (d == 0)                          /* a half-integer: 2t is an int */
        return (int)cft_bn_extract(&tm, 0, 2);
    k0 = (int)cft_bn_extract(&tm, (int)d, 2);
    carry = cft_bn_bit(&tm, (int)d - 1);
    cft_bn_copy(&low, &tm);
    cft_bn_mask(&low, (int)d);
    *se = L->e;
    if (carry) {
        cft_bn p2;
        cft_bn_zero(&p2);
        cft_bn_setbit(&p2, (int)d);
        cft_bn_sub(smag, &p2, &low);     /* |S| = 2^d - low, in (0, 2^(d-1)] */
        *sneg = 1;
        k = k0 + 1;
    } else {
        cft_bn_copy(smag, &low);
        k = k0;
    }
    return k;
}

/* ---- phase 2 drivers ------------------------------------------------ */

/* A result that is an exact multiple of pi/4: the axes and diagonals of
 * atan2, asin(+-1), acos(+-0), acos(-1), atan(+-inf).
 *
 * In the Pi-variant every one of them is a dyadic rational the format
 * holds exactly and the answer raises NOTHING; in radians every one but
 * zero is a rounding of an irrational number and is inexact. That
 * asymmetry is not an implementation detail - it is the reason the Pi
 * forms are separate functions. */
static cft_status deliver_quarters(const cft_fmt_desc *f, int sign,
                                   int quarters, int over_pi, int rnd,
                                   cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;

    *flags = 0;
    if (quarters == 0) {
        cft_tr_exact++;
        cft_sf_zero(f, sign, out);
        return CFT_OK;
    }
    if (over_pi) {
        cft_tr_exact++;
        cft_bn_zero(&m);
        cft_bn_set_u32(&m, (uint32_t)quarters);
        return round_exact(f, sign, &m, -2, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }
    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = TR_PI_QUARTERS;
    A.quarters = quarters;
    return tr_ziv(&A, sign, rnd, out, flags);
}

static int tr_nan_in(const cft_fmt_desc *f, const lane *a, const lane *b,
                     cft_bn *out, uint32_t *flags)
{
    if ((a->kind == K_NAN && a->signaling) ||
        (b && b->kind == K_NAN && b->signaling)) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return 1;
    }
    if (a->kind == K_NAN || (b && b->kind == K_NAN)) {
        cft_sf_qnan(f, out);
        *flags = 0;
        return 1;
    }
    return 0;
}

static cft_status do_pi_trig(const cft_fmt_desc *f, int fn, const lane *a,
                             int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn M;
    long E, sv;
    int sneg, k, k_even, sin_neg, cos_neg, sign, want_cos;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        /* sin, cos and tan of an infinity have no limit at all. */
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        if (fn == CFT_TR_COSPI)
            put_one(f, 0, out);                 /* cosPi(+-0) = 1 */
        else
            cft_sf_zero(f, a->sign, out);       /* sinPi/tanPi(+-0) */
        return CFT_OK;
    }

    /* The exact cases, and Niven's theorem says they are all of them:
     * for a rational r, sin(pi r) is rational only at 0, +-1/2 and +-1,
     * and a DYADIC r can never produce +-1/2 (that would need r = 1/6
     * and its friends), so sinPi and cosPi are exact exactly at the
     * half-integers. tan(pi r) is rational only at 0 and +-1, which
     * puts tanPi's exact cases at the quarter-integers and its poles at
     * the half-integers. Everything else is irrational, hence not a
     * rounding boundary, hence decided by the enclosure in finite
     * time. */
    lane_odd(a, &M, &E);
    if (E >= 0) {                               /* |x| is an integer n */
        int odd_n = (E == 0);
        cft_tr_exact++;
        if (fn == CFT_TR_SINPI)
            cft_sf_zero(f, a->sign, out);       /* the sign of n */
        else if (fn == CFT_TR_COSPI)
            put_one(f, odd_n, out);             /* (-1)^n */
        else
            cft_sf_zero(f, a->sign ^ odd_n, out);
        return CFT_OK;
    }
    if (E == -1) {                              /* |x| is n + 1/2 */
        int neg = a->sign ^ cft_bn_bit(&M, 1);
        if (fn == CFT_TR_SINPI) {
            cft_tr_exact++;
            put_one(f, neg, out);               /* +-1 */
            return CFT_OK;
        }
        if (fn == CFT_TR_COSPI) {
            cft_tr_exact++;
            cft_sf_zero(f, 0, out);             /* +0, for both signs */
            return CFT_OK;
        }
        /* tanPi at a pole: an exact infinity from finite operands, so
         * 754-2019 7.3 raises divideByZero. The sign is sinPi's,
         * because cosPi there is +0. MPFR 4.2.2 delivers the same rows
         * (tanpi(1/2) = +Inf, tanpi(3/2) = -Inf, divide-by-zero set). */
        cft_sf_inf(f, neg, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (E == -2 && fn == CFT_TR_TANPI) {        /* |x| is n/4, n odd */
        cft_tr_exact++;
        put_one(f, a->sign ^ cft_bn_bit(&M, 1), out);
        return CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    k = lane_pi_reduce(a, &A.s_m, &sneg, &A.s_e);
    if (cft_bn_is_zero(&A.s_m))
        return CFT_ERR_INTERNAL;                /* a half-integer got past */
    k_even = !(k & 1);
    A.k_even = k_even;

    /* The quadrant's signs, read off exactly. No evaluation decides the
     * sign of a value it is about to round. */
    switch (k & 3) {
    case 0:  sin_neg = sneg;  cos_neg = 0;      break;
    case 1:  sin_neg = 0;     cos_neg = !sneg;  break;
    case 2:  sin_neg = !sneg; cos_neg = 1;      break;
    default: sin_neg = 1;     cos_neg = sneg;   break;
    }
    if (fn == CFT_TR_SINPI)
        sign = a->sign ^ sin_neg;               /* odd function */
    else if (fn == CFT_TR_COSPI)
        sign = cos_neg;                         /* even function */
    else
        sign = a->sign ^ sin_neg ^ cos_neg;     /* the quotient's */

    /* |sin(pi t)| is sin(pi|s|) when k is even and cos(pi|s|) when it is
     * odd; |cos(pi t)| is the other way round. */
    want_cos = (fn == CFT_TR_COSPI) ? k_even : !k_even;
    A.want_cos = want_cos;

    /* The one neighbour rule this family needs. cos(u) < 1 for u != 0
     * and 1 - cos(u) <= u^2/2, so with u = pi|s| the result sits below 1
     * by less than 4.94 s^2; half the gap below 1 is 2^-(p+1), and
     * 4.94 * 2^(2v+2) < 2^-(p+1) reduces to 2v + p + 6 <= 0. No working
     * precision separates those from 1, and none needs to: the side is
     * known, and it is always downward. */
    sv = A.s_e + cft_bn_bitlen(&A.s_m) - 1;
    if (fn != CFT_TR_TANPI && want_cos &&
        2 * sv + (long)f->prec + 6 <= 0)
        return round_side_of(f, sign, 0, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    return tr_ziv(&A, sign, rnd, out, flags);
}

/* |x| > 1 for a finite lane. */
static int lane_mag_gt_one(const lane *a)
{
    return lane_vexp(a) >= 0 && !lane_is_one(a);
}

static cft_status do_asin_family(const cft_fmt_desc *f, int fn, const lane *a,
                                 int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    int over_pi = (fn == CFT_TR_ASINPI);
    long ex;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF || (a->kind != K_ZERO && lane_mag_gt_one(a))) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);           /* asin(+-0) = +-0 */
        return CFT_OK;
    }
    if (lane_is_one(a))                         /* +-pi/2, or +-1/2 */
        return deliver_quarters(f, a->sign, 2, over_pi, rnd, out, flags);

    ex = lane_vexp(a);
    if (!over_pi && 2 * ex + (long)f->prec + 2 <= 0)
        /* asin(x) - x = x^3/6 + 3x^5/40 + ... > 0, and |asin(x) - x| <=
         * 0.2|x|^3 sits inside half the gap on the far side of x once
         * 2e + p + 2 <= 0. asinPi rides no such rule: its answer is
         * about x/pi, which is not next to anything. */
        return round_side(f, a->sign, &a->m, a->e, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

static cft_status do_acos_family(const cft_fmt_desc *f, int fn, const lane *a,
                                 int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    int over_pi = (fn == CFT_TR_ACOSPI);

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF || (a->kind != K_ZERO && lane_mag_gt_one(a))) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO)                      /* pi/2, or exactly 1/2 */
        return deliver_quarters(f, 0, 2, over_pi, rnd, out, flags);
    if (lane_is_one(a)) {
        if (!a->sign) {
            cft_tr_exact++;
            cft_sf_zero(f, 0, out);             /* acos(1) = +0 */
            return CFT_OK;
        }
        return deliver_quarters(f, 0, 4, over_pi, rnd, out, flags);
    }
    if (over_pi && lane_vexp(a) <= -(long)(f->prec + 2))
        /* acosPi(x) = 1/2 - asin(x)/pi and |asin(x)/pi| <= 0.33|x|,
         * which is inside half the gap next to 1/2 once |x| <=
         * 2^-(p+2). The side is the operand's: a positive x pulls the
         * answer below 1/2. */
        return round_side_of(f, 0, -1, a->sign ? 1 : 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    return tr_ziv(&A, 0, rnd, out, flags);
}

static cft_status do_atan_family(const cft_fmt_desc *f, int fn, const lane *a,
                                 int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    int over_pi = (fn == CFT_TR_ATANPI);
    long ex;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);
        return CFT_OK;
    }
    if (a->kind == K_INF)                       /* +-pi/2, or +-1/2 */
        return deliver_quarters(f, a->sign, 2, over_pi, rnd, out, flags);
    if (over_pi && lane_is_one(a)) {            /* +-1/4, exactly */
        cft_bn m;
        cft_tr_exact++;
        cft_bn_zero(&m);
        cft_bn_set_u32(&m, 1);
        return round_exact(f, a->sign, &m, -2, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    ex = lane_vexp(a);
    if (!over_pi && 2 * ex + (long)f->prec + 3 <= 0)
        /* atan(x) - x = -x^3/3 + x^5/5 - ... is NEGATIVE for x in
         * (0, 1) and no bigger than x^3/3, so the true value lies on
         * the zero side of x - the opposite side from asin's, which is
         * what makes a pair of directed roundings tell the two apart. */
        return round_side(f, a->sign, &a->m, a->e, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    if (over_pi && ex >= (long)f->prec + 1)
        /* atanPi(x) = 1/2 - atan(1/x)/pi with atan(1/x) <= 1/|x|, so
         * once |x| >= 2^(p+1) the answer is inside half the gap below
         * 1/2. In radians the same corner sits next to pi/2, which the
         * format does not hold, so no rule is needed there. */
        return round_side_of(f, a->sign, -1, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

/* atan2(y, x), y first as C has it, and the whole of 9.2.1's table.
 *
 * The row implementations most often get wrong is atan2(+-0, -0) =
 * +-pi: a MINUS zero denominator names the negative real axis, so the
 * answer is pi and not zero. Its Pi-variant is +-1 and is exact.
 * Confirmed against MPFR 4.2.2 before it was written down. */
static cft_status do_atan2_family(const cft_fmt_desc *f, int fn,
                                  const lane *y, const lane *x, int rnd,
                                  cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn qm;
    long qe, ey, ex, qv, g;
    int over_pi = (fn == CFT_TR_ATAN2PI);
    int sign;

    *flags = 0;
    if (tr_nan_in(f, y, x, out, flags))
        return CFT_OK;
    sign = y->sign;
    if (y->kind == K_INF) {
        if (x->kind == K_INF)                   /* +-pi/4 or +-3pi/4 */
            return deliver_quarters(f, sign, x->sign ? 3 : 1, over_pi, rnd,
                                    out, flags);
        return deliver_quarters(f, sign, 2, over_pi, rnd, out, flags);
    }
    if (x->kind == K_INF || y->kind == K_ZERO)
        /* a finite y against an infinite x, and a zero y against
         * anything: +-0 for a positive x, +-pi for a negative one -
         * and the SIGN of a zero x decides, which is the row the whole
         * table is remembered for. */
        return deliver_quarters(f, sign, x->sign ? 4 : 0, over_pi, rnd,
                                out, flags);
    if (x->kind == K_ZERO)
        return deliver_quarters(f, sign, 2, over_pi, rnd, out, flags);

    /* The diagonals are the last exact rows, and Niven says there are
     * no others: a dyadic multiple of pi has a rational tangent only at
     * 0, +-1 and the pole. */
    if (lane_mag_eq(y, x))
        return deliver_quarters(f, sign, x->sign ? 3 : 1, over_pi, rnd,
                                out, flags);

    ey = lane_vexp(y);
    ex = lane_vexp(x);

    if (!over_pi && !x->sign && lane_exact_quotient(y, x, &qm, &qe) == 0) {
        /* atan2(y, x>0) is atan(y/x), so when that quotient is itself a
         * dyadic rational on the format's fine grid the answer is a hair
         * below it and no precision can say how far. atan2(minSub, 2)
         * lands on a subnormal MIDPOINT this way, which is why
         * round_side and not round_neighbour. */
        qv = qe + cft_bn_bitlen(&qm) - 1;
        g = qv - (long)f->prec + 1;
        if (g < (long)f->emin - f->man_w)
            g = (long)f->emin - f->man_w;
        if (2 * qv + (long)f->prec + 3 <= 0 && qe >= g - 1) {
            if (round_side(f, sign, &qm, qe, 0, rnd, out, flags))
                return CFT_ERR_INTERNAL;
            return CFT_OK;
        }
    }
    if (over_pi) {
        /* Near +-1 (a tiny quotient against a negative x) and near
         * +-1/2 (a dominant y), the answer is within half a gap of a
         * value the format holds. In radians the same corners sit
         * beside pi and pi/2, which it does not. */
        if (x->sign && ey - ex <= -(long)(f->prec + 1))
            return round_side_of(f, sign, 0, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (ex - ey <= -(long)(f->prec + 2))
            return round_side_of(f, sign, -1, x->sign ? 1 : 0, rnd, out,
                                 flags) ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *y;
    A.a.sign = 0;
    A.b = *x;
    A.b.sign = 0;
    A.x_neg = x->sign;
    return tr_ziv(&A, sign, rnd, out, flags);
}

/* ---- phase 3 drivers ------------------------------------------------ */

/* sin, cos and tan of a RADIAN argument.
 *
 * Everything above the reduction is phase 2's do_pi_trig, line for
 * line: the same quadrant-to-sign table, the same "which series is the
 * magnitude" rule, the same insistence that no evaluation decides a
 * sign. What changed is where the quadrant comes from - a mask on the
 * encoding there, a Payne-Hanek window here - and that the exact cases
 * collapsed to one. sin(x), cos(x) and tan(x) of a nonzero dyadic x are
 * transcendental (Hermite-Lindemann: sin(x) = a algebraic would make
 * e^(ix) a root of z^2 - 2iaz - 1 and hence algebraic), so the only
 * exact arguments are the zeros - where sinPi and tanPi had the half-
 * and quarter-integers and cosPi had a pole-free table of its own. */
static cft_status do_radian(const cft_fmt_desc *f, int fn, const lane *a,
                            int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    long ex, vr;
    int sin_neg, cos_neg, sign, k, k_even;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        /* No limit exists: 9.2.1 makes all three invalid, exactly as it
         * does for sinPi, cosPi and tanPi. */
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        if (fn == CFT_TR_COS)
            put_one(f, 0, out);                 /* cos(+-0) = 1 */
        else
            cft_sf_zero(f, a->sign, out);       /* sin/tan(+-0) = +-0 */
        return CFT_OK;
    }

    /* The tiny-argument rules, on the OPERAND: there the reduction is
     * the identity, so these are statements about x itself.
     *   sin(x) - x = -x^3/6 + ...   below x, by at most |x|^3/6
     *   tan(x) - x = +x^3/3 + ...   above x, by at most 0.357|x|^3
     *   1 - cos(x) <= x^2/2         below 1
     * Each compared against a quarter of the grid step, the way phase
     * 2 derives asin's and atan's; cos's threshold is one worse than
     * cosh's because the gap below 1 is half the gap above it. */
    ex = lane_vexp(a);
    if (fn == CFT_TR_SIN && 2 * ex + (long)f->prec + 2 <= 0)
        return round_neighbour(f, a, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    if (fn == CFT_TR_TAN && 2 * ex + (long)f->prec + 3 <= 0)
        return round_neighbour(f, a, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    if (fn == CFT_TR_COS && 2 * ex + (long)f->prec + 3 <= 0)
        return round_side_of(f, 0, 0, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    if (tr_ph_reduce(&A.red, a, f))
        return CFT_ERR_INTERNAL;         /* the loud refusal, and the only
                                          * one this phase adds */
    k = A.red.quadrant;
    k_even = !(k & 1);
    A.k_even = k_even;

    switch (k & 3) {
    case 0:  sin_neg = A.red.t.sign;  cos_neg = 0;                break;
    case 1:  sin_neg = 0;             cos_neg = !A.red.t.sign;    break;
    case 2:  sin_neg = !A.red.t.sign; cos_neg = 1;                break;
    default: sin_neg = 1;             cos_neg = A.red.t.sign;     break;
    }
    if (fn == CFT_TR_SIN)
        sign = a->sign ^ sin_neg;               /* odd function */
    else if (fn == CFT_TR_COS)
        sign = cos_neg;                         /* even function */
    else
        sign = a->sign ^ sin_neg ^ cos_neg;     /* the quotient's */

    A.want_cos = (fn == CFT_TR_COS) ? k_even : !k_even;

    /* The one rule the reduced argument needs. When the magnitude is
     * cos(v) and v is tiny - which is x sitting a hair from a multiple
     * of pi/2, the deep-cancellation case - the answer is inside half
     * the gap below 1 and no working precision separates it. |r| is at
     * most 2^(t_exp2+1), so 2v + p + 3 <= 0 is the same condition
     * cosPi's rule has, on the reduced argument rather than on a mask.
     *
     * tan gets no such rule: |tan| near 1 would need |r| within
     * 2^-(p+2) of pi/4, which is a coincidence of a different order
     * from any this reduction has measured, and if one occurred the
     * loop would refuse rather than guess. */
    vr = A.red.t_exp2 + 1;
    if (fn != CFT_TR_TAN && A.want_cos && 2 * vr + (long)f->prec + 3 <= 0)
        return round_side_of(f, sign, 0, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    return tr_ziv(&A, sign, rnd, out, flags);
}

/* sinh and cosh: one exponential each, and the overflow screen that
 * keeps mp_exp_full from ever being asked for e^(2^262143). */
static cft_status do_sinh_cosh(const cft_fmt_desc *f, int fn, const lane *a,
                               int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    int is_cosh = (fn == CFT_TR_COSH);
    int sign = is_cosh ? 0 : a->sign;
    long ex;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        cft_sf_inf(f, is_cosh ? 0 : a->sign, out);
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        if (is_cosh)
            put_one(f, 0, out);                 /* cosh(+-0) = 1 */
        else
            cft_sf_zero(f, a->sign, out);       /* sinh(+-0) = +-0 */
        return CFT_OK;
    }

    ex = lane_vexp(a);
    if (!is_cosh && 2 * ex + (long)f->prec + 2 <= 0)
        /* sinh(x) - x = x^3/6 + ... has the sign of x and is at most
         * 0.17|x|^3: asin's threshold, for the series that differs from
         * sin's only in the sign of every second term. */
        return round_neighbour(f, a, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    if (is_cosh && 2 * ex + (long)f->prec + 2 <= 0)
        /* cosh(x) - 1 = x^2/2 + ... > 0, at most 0.51x^2, against half
         * the gap ABOVE 1, which is 2^-p - twice the gap below it. */
        return round_side_of(f, 0, 0, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    A.a.sign = 0;

    {
        cft_mp q;
        if (tr_log2_estimate(&A, &q))
            return CFT_ERR_INTERNAL;
        if (cft_mp_cmp_int(&q, (int64_t)f->emax + 3) > 0)
            return round_overflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
    }
    return tr_ziv(&A, sign, rnd, out, flags);
}

/* tanh, the one function in this phase whose infinity is an exact
 * finite value. */
static cft_status do_tanh(const cft_fmt_desc *f, const lane *a, int rnd,
                          cft_bn *out, uint32_t *flags)
{
    tr_args A;
    long ex;
    int bl, v;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        put_one(f, a->sign, out);               /* tanh(+-inf) = +-1 */
        return CFT_OK;                          /* a limit, and exact */
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);
        return CFT_OK;
    }

    ex = lane_vexp(a);
    if (2 * ex + (long)f->prec + 3 <= 0)
        /* tanh(x) - x = -x^3/3 + ... lies on the zero side of x, by at
         * most 0.357|x|^3: atan's rule for atan's series with the signs
         * flipped. */
        return round_neighbour(f, a, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    for (bl = 0, v = f->prec + 2; v; v >>= 1)
        bl++;
    if (ex >= bl)
        /* 1 - tanh(x) = 2/(e^2x + 1) < 2 e^-2x, inside half the gap
         * below 1 once x > 0.347(p+2). 2^ex >= p+2 implies that with
         * room, and it is an integer test on the encoding. */
        return round_side_of(f, a->sign, 0, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_TANH;
    A.a = *a;
    A.a.sign = 0;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

static cft_status do_asinh(const cft_fmt_desc *f, const lane *a, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    tr_args A;
    long ex;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        cft_sf_inf(f, a->sign, out);
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);
        return CFT_OK;
    }

    ex = lane_vexp(a);
    if (2 * ex + (long)f->prec + 2 <= 0)
        /* asinh(x) - x = -x^3/6 + ... lies on the zero side of x: sin's
         * rule exactly, and the mirror of sinh's. */
        return round_neighbour(f, a, 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    /* No overflow screen, and none is possible: |asinh(x)| is below
     * log(2|x| + 1), about 181,705 at the top of fp256. */
    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_ASINH;
    A.a = *a;
    A.a.sign = 0;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

/* acosh, whose domain is [1, +inf) and whose only exact case is its
 * left endpoint. No neighbour rule: near 1 the answer behaves like
 * sqrt(2(x-1)), which is not beside anything the format holds - the
 * same reason phase 2's acos has none near 1. */
static cft_status do_acosh(const cft_fmt_desc *f, const lane *a, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    tr_args A;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        if (a->sign) {
            cft_sf_qnan(f, out);
            *flags = CFT_SF_INVALID;
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO || a->sign || lane_vexp(a) < 0) {
        cft_sf_qnan(f, out);                    /* x < 1 */
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (lane_is_one(a)) {
        cft_tr_exact++;
        cft_sf_zero(f, 0, out);                 /* acosh(1) = +0 */
        return CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_ACOSH;
    A.a = *a;
    return tr_ziv(&A, 0, rnd, out, flags);
}

static cft_status do_atanh(const cft_fmt_desc *f, const lane *a, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    tr_args A;
    long ex;

    *flags = 0;
    if (tr_nan_in(f, a, NULL, out, flags))
        return CFT_OK;
    if (a->kind == K_INF) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);
        return CFT_OK;
    }
    if (lane_is_one(a)) {
        /* The pole. 754-2019 7.3 raises divideByZero exactly where an
         * operation on finite operands has an exact infinite result,
         * which is the row tanPi takes at a half-integer. */
        cft_sf_inf(f, a->sign, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (lane_mag_gt_one(a)) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }

    ex = lane_vexp(a);
    if (2 * ex + (long)f->prec + 3 <= 0)
        /* atanh(x) - x = x^3/3 + ... has the sign of x: tan's rule, and
         * the mirror of tanh's. */
        return round_neighbour(f, a, 1, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_ATANH;
    A.a = *a;
    A.a.sign = 0;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

/* ---- table 9.1's remainder: the drivers ---------------------------- */

/* The lane for an exactly representable power of two, so a neighbour
 * witness can be anchored on it. n must be inside the normal range. */
static void lane_pow2(const cft_fmt_desc *f, long n, lane *u)
{
    memset(u, 0, sizeof *u);
    u->kind = K_NORM;
    u->sign = 0;
    cft_bn_zero(&u->m);
    cft_bn_set_u32(&u->m, 1);
    (void)cft_bn_shl(&u->m, &u->m, f->man_w);
    u->e = n - (long)f->man_w;
}

/* The lane for +-1. */
static void lane_one(const cft_fmt_desc *f, int sign, lane *u)
{
    lane_pow2(f, 0, u);
    u->sign = sign;
}

/* 2^x - 1.
 *
 * EXACT at every integer argument, which is the widest exact table in
 * this set: 2^n - 1 is a dyadic rational for every n, positive or
 * negative, and it is a rounding boundary of a p-bit format exactly
 * while |n| <= p+1. Past that the value is still exactly known but is
 * delivered by a SIDE rather than by a rounding of it, because the exact
 * integer 2^n - 1 is up to 262,143 bits wide at fp256 and this
 * container is 2048:
 *
 *   n >= p+2   2^n - 1 sits in the top HALF of the gap below 2^n,
 *              above its midpoint (the gap there is 2^(n-p) and
 *              1 < 2^(n-p-1));
 *   n <= -(p+2) -(1 - 2^n) sits in the half gap above -1, whose nearest
 *              boundary is -(1 - 2^-(p+1)).
 *
 * There is NO tiny-argument rule: 2^x - 1 is about x ln2, which is not
 * beside x. Only a base of e puts it there, which is why expm1 has one
 * and this does not.
 */
static cft_status do_exp2m1(const cft_fmt_desc *f, const lane *a, int rnd,
                            cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn M, t;
    long E, n;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign)
            put_one(f, 1, out);                 /* exp2m1(-inf) = -1 */
        else
            cft_sf_inf(f, 0, out);
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);           /* exp2m1(+-0) = +-0 */
        return CFT_OK;
    }

    lane_odd(a, &M, &E);
    if (E >= 0) {                               /* an integer argument */
        n = odd_to_long(&M, E, a->sign);
        if (n >= -(long)(f->prec + 1) && n <= (long)(f->prec + 1)) {
            cft_tr_exact++;
            cft_bn_zero(&t);
            cft_bn_setbit(&t, (int)(n < 0 ? -n : n));
            cft_bn_dec(&t);                     /* 2^|n| - 1 */
            return round_exact(f, n < 0, &t, n < 0 ? n : 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
        if (n > 0) {
            lane u;
            if (n > f->emax)
                return round_overflowing(f, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            lane_pow2(f, n, &u);
            return round_neighbour(f, &u, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
        {
            lane negone;
            lane_one(f, 1, &negone);
            return round_neighbour(f, &negone, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_EXP2M1;
    A.a = *a;
    {
        cft_mp q;
        if (tr_log2_estimate(&A, &q))            /* log2(2^x) is x */
            return CFT_ERR_INTERNAL;
        if (cft_mp_cmp_int(&q, (int64_t)f->emax + 2) > 0)
            return round_overflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (cft_mp_cmp_int(&q, -(int64_t)(f->prec + 3)) < 0) {
            lane negone;
            lane_one(f, 1, &negone);
            return round_neighbour(f, &negone, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
    }
    return tr_ziv(&A, a->sign ? 1 : 0, rnd, out, flags);
}

/* 10^x and 10^x - 1.
 *
 * EXACT exactly at the non-negative integers whose 10^n (odd part 5^n)
 * or 10^n - 1 (odd, so its own odd part) fits in p+1 bits. A negative
 * power of ten is not a dyadic rational at all, and a non-integer dyadic
 * exponent gives an algebraic irrational, so neither can be a boundary.
 *
 * exp10 gets the beside-1 rule for a tiny argument - |10^x - 1| <= 2.64|x|
 * is inside the half gap next to 1 once |x| < 2^-(p+3) - and exp10m1
 * does NOT, for exp2m1's reason: 10^x - 1 is about x ln10, which is not
 * beside x. What exp10m1 gets instead is the rule beside -1, where 10^x
 * has fallen below half a gap.
 */
static cft_status do_exp10_family(const cft_fmt_desc *f, int fn,
                                  const lane *a, int rnd, cft_bn *out,
                                  uint32_t *flags)
{
    tr_args A;
    cft_bn M;
    long E;
    int minus_one = (fn == CFT_TR_EXP10M1);

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign) {
            if (minus_one)
                put_one(f, 1, out);             /* exp10m1(-inf) = -1 */
            else
                cft_sf_zero(f, 0, out);         /* exp10(-inf) = +0 */
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        if (minus_one)
            cft_sf_zero(f, a->sign, out);       /* exp10m1(+-0) = +-0 */
        else
            put_one(f, 0, out);                 /* exp10(+-0) = 1 */
        return CFT_OK;
    }

    lane_odd(a, &M, &E);
    if (E >= 0 && !a->sign) {                   /* a positive integer */
        long n = odd_to_long(&M, E, 0);
        if (n <= (long)f->prec + 1) {
            cft_bn five;
            if (pow5(&five, n, f->prec + 1) == 0) {
                cft_bn ten;
                if (!minus_one) {
                    cft_tr_exact++;
                    return round_exact(f, 0, &five, n, rnd, out, flags)
                        ? CFT_ERR_INTERNAL : CFT_OK;
                }
                if (cft_bn_shl(&ten, &five, (int)n) == 0) {
                    cft_bn_dec(&ten);           /* 10^n - 1, odd */
                    if (cft_bn_bitlen(&ten) <= f->prec + 1) {
                        cft_tr_exact++;
                        return round_exact(f, 0, &ten, 0, rnd, out, flags)
                            ? CFT_ERR_INTERNAL : CFT_OK;
                    }
                }
            }
        }
    }

    if (!minus_one && lane_vexp(a) <= -(long)(f->prec + 4)) {
        lane one;
        lane_one(f, 0, &one);
        return round_neighbour(f, &one, a->sign == 0, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    {
        cft_mp q;
        if (tr_log2_estimate(&A, &q))
            return CFT_ERR_INTERNAL;
        if (minus_one) {
            if (cft_mp_cmp_int(&q, (int64_t)f->emax + 2) > 0)
                return round_overflowing(f, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            if (cft_mp_cmp_int(&q, -(int64_t)(f->prec + 3)) < 0) {
                lane negone;
                lane_one(f, 1, &negone);
                return round_neighbour(f, &negone, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            }
        } else {
            int s = tr_screen(&A, &q, 0, rnd, out, flags);
            if (s < 0)
                return CFT_ERR_INTERNAL;
            if (s > 0)
                return CFT_OK;
        }
    }
    return tr_ziv(&A, minus_one && a->sign ? 1 : 0, rnd, out, flags);
}

/* log2(1 + x) and log10(1 + x).
 *
 * EXACT exactly where 1 + x is a power of two, or of ten - unique
 * factorisation, the same argument log2 and log10 have carried since
 * phase 1 - and 1 + x is formed EXACTLY on the encoding rather than in
 * the format, which is the whole reason these functions exist.
 *
 * NO neighbour rule, and that is a derivation rather than an omission:
 * for a tiny x the value is x/ln2 or x/ln10, which is not beside x. Only
 * a base of e puts it there, which is why log1p has a rule and these do
 * not; the enclosure resolves them to full relative precision and
 * round_pack carries the underflow.
 */
static cft_status do_logp1_family(const cft_fmt_desc *f, int fn,
                                  const lane *a, int rnd, cft_bn *out,
                                  uint32_t *flags)
{
    tr_args A;
    cft_bn M, sm, O, n;
    long E, se, F;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign) {
            cft_sf_qnan(f, out);                /* 1 + (-inf) < 0 */
            *flags = CFT_SF_INVALID;
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_tr_exact++;
        cft_sf_zero(f, a->sign, out);           /* f(+-0) = +-0 */
        return CFT_OK;
    }
    lane_odd(a, &M, &E);
    if (a->sign && E == 0 && cft_bn_bitlen(&M) == 1) {   /* x == -1 */
        cft_sf_inf(f, 1, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (a->sign && lane_vexp(a) >= 0) {                  /* x < -1 */
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }

    if (lane_one_plus(a, &sm, &se, f->prec + 4) == 0) {
        int tz = 0, nb = cft_bn_bitlen(&sm);
        while (tz < nb && !cft_bn_bit(&sm, tz))
            tz++;
        cft_bn_shr(&O, &sm, tz);
        F = se + tz;
        if (fn == CFT_TR_LOG2P1 && cft_bn_bitlen(&O) == 1) {
            cft_tr_exact++;                      /* 1 + x == 2^F */
            if (F == 0) {
                cft_sf_zero(f, 0, out);
                return CFT_OK;
            }
            cft_bn_zero(&n);
            cft_bn_set_u32(&n, (uint32_t)(F < 0 ? -F : F));
            return round_exact(f, F < 0, &n, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
        if (fn == CFT_TR_LOG10P1 && F >= 0 && F <= f->prec) {
            cft_bn five;
            if (pow5(&five, F, f->prec + 2) == 0 &&
                cft_bn_cmp(&five, &O) == 0) {
                cft_tr_exact++;                  /* 1 + x == 10^F */
                if (F == 0) {
                    cft_sf_zero(f, 0, out);
                    return CFT_OK;
                }
                cft_bn_zero(&n);
                cft_bn_set_u32(&n, (uint32_t)F);
                return round_exact(f, 0, &n, 0, rnd, out, flags)
                    ? CFT_ERR_INTERNAL : CFT_OK;
            }
        }
    }

    /* The one family no working precision can decide, and the reason
     * these two functions have a neighbour rule after all - just not the
     * tiny-argument one their siblings have.
     *
     * For x = 2^k the value is k + log2(1 + 2^-k): an exponentially
     * small step ABOVE the integer k, and k is a grid point of every
     * format on this ladder. An enclosure would have to separate the two
     * and cannot; the SIDE is the whole answer, and it is a theorem
     * (log2(1+u) > 0 for u > 0) rather than a measurement.
     *
     * The threshold is derived. The excess is at most 2^(-k+0.529), and
     * the nearest boundary above k is half an ulp away at 2^(g-p) with
     * g = floor(log2 k), so the excess is inside it once
     * k > p - g + 0.529 - that is, once k >= p - g + 1. At k = p - g the
     * excess is at least 1.26 half-gaps, so the enclosure decides that
     * one with two bits to spare: there is no band between the two.
     *
     * For x = 10^k the same shape in another base: the excess is at most
     * 10^-k/ln10, and the comparison against the half gap is made in
     * EXACT integers against 23025/10000, a rational below ln 10. The
     * closest that comparison comes to an equality over every k any
     * format on this ladder holds is a factor of 2^0.495 (fp128,
     * k = 32), so five decimals of ln 10 decide it with room.
     *
     * Nothing else in these two functions needs a rule. x = 2^k + one
     * ulp puts the value about 2^(1-p) above k in RELATIVE terms, which
     * the enclosure resolves in p + log2(k) bits; only the exact power,
     * where the whole perturbation is the "+1", is out of its reach. */
    if (!a->sign && E >= 1) {
        long k = E, g = 0, kk = E;
        while (kk > 1) {
            kk >>= 1;
            g++;
        }
        if (fn == CFT_TR_LOG2P1 && cft_bn_bitlen(&M) == 1 &&
            k >= (long)f->prec - g + 1) {
            cft_bn km;
            cft_bn_zero(&km);
            cft_bn_set_u32(&km, (uint32_t)k);
            return round_side(f, 0, &km, 0, 1, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        }
        if (fn == CFT_TR_LOG10P1 && k <= (long)f->prec) {
            cft_bn five, ten, half, lhs, rhs, c;
            if (pow5(&five, k, f->prec + 2) == 0 &&
                cft_bn_cmp(&five, &M) == 0) {         /* x == 10^k */
                cft_bn_zero(&half);
                cft_bn_setbit(&half, (int)((long)f->prec - g));
                cft_bn_zero(&c);
                cft_bn_set_u32(&c, 10000);
                if (cft_bn_mul(&lhs, &half, &c))
                    return CFT_ERR_INTERNAL;
                if (cft_bn_shl(&ten, &five, (int)k))
                    return CFT_ERR_INTERNAL;
                cft_bn_zero(&c);
                cft_bn_set_u32(&c, 23025);
                if (cft_bn_mul(&rhs, &ten, &c))
                    return CFT_ERR_INTERNAL;
                if (cft_bn_cmp(&lhs, &rhs) < 0) {
                    cft_bn km;
                    cft_bn_zero(&km);
                    cft_bn_set_u32(&km, (uint32_t)k);
                    return round_side(f, 0, &km, 0, 1, rnd, out, flags)
                        ? CFT_ERR_INTERNAL : CFT_OK;
                }
            }
        }
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = fn;
    A.a = *a;
    return tr_ziv(&A, a->sign, rnd, out, flags);
}

/* 1/sqrt(x) on [0, +inf].
 *
 * rSqrt(+-0) is +-INFINITY with divideByZero - the sign SURVIVES, which
 * is 754-2019 9.2.1's row and is not what GNU MPFR's mpfr_rec_sqrt
 * delivers (it returns +inf for both zeros; measured on 4.2.2,
 * 2026-09-03, and recorded in docs/TRANSCENDENTALS.md).
 *
 * EXACT exactly at the even powers of two: 1/sqrt(M 2^E) is rational
 * only if sqrt(M) is, and dyadic only if sqrt(M) is a power of two,
 * which for an odd M forces M = 1 - and then E must be even.
 *
 * It can neither overflow nor underflow at any rung: the largest result
 * is 1/sqrt(minSubnormal) = 2^((emax+p-1)/2), and half of emax+p-1 is
 * below emax whenever emax > p-1, which holds at all four. So there is
 * no screen here, and none is missing.
 */
static cft_status do_rsqrt(const cft_fmt_desc *f, const lane *a, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn M, one;
    long E;

    *flags = 0;
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        if (a->signaling)
            *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        cft_sf_inf(f, a->sign, out);
        *flags = CFT_SF_DIVZERO;
        return CFT_OK;
    }
    if (a->sign) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        cft_sf_zero(f, 0, out);
        return CFT_OK;
    }

    lane_odd(a, &M, &E);
    if (cft_bn_bitlen(&M) == 1 && (E % 2) == 0) {
        cft_tr_exact++;
        cft_bn_zero(&one);
        cft_bn_set_u32(&one, 1);
        return round_exact(f, 0, &one, -(E / 2), rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_RSQRT;
    A.a = *a;
    return tr_ziv(&A, 0, rnd, out, flags);
}

/* The screen and the beside-1 rule shared by pown, powr, compound and
 * rootn: every one of them is exp(something * a logarithm), so a result
 * provably past the format is delivered without evaluating anything, and
 * one provably inside the half gap next to 1 is delivered by its side.
 * `up` is the side the exact operand signs give.
 *
 * Returns 1 when it fired, 0 to fall through, -1 on an internal
 * failure. */
static int tr_pow_like_screen(const tr_args *A, int sign, int up, int rnd,
                              cft_bn *out, uint32_t *flags)
{
    const cft_fmt_desc *f = A->f;
    cft_mp q;
    int s;

    if (tr_log2_estimate(A, &q))
        return -1;
    s = tr_screen(A, &q, sign, rnd, out, flags);
    if (s != 0)
        return s;
    if (!q.zero && cft_mp_exp2_of(&q) + 4 < -(long)(f->prec + 3)) {
        lane one;
        lane_one(f, sign, &one);
        return round_neighbour(f, &one, up, rnd, out, flags) ? -1 : 1;
    }
    return 0;
}

/* x^n for an integer n. 9.2.1's own rows, which are pow's with the
 * non-integer exponent deleted - and with pow(1, y) = 1 deleted too,
 * because an integer n makes that an ordinary exact case rather than a
 * table entry. pown(x, 0) is 1 for any x that is not a signaling NaN, a
 * quiet NaN and an infinity included. */
static cft_status do_pown(const cft_fmt_desc *f, const lane *a, int64_t n,
                          int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;
    long e;
    int odd = (int)(n & 1), sign, up;

    *flags = 0;
    if (a->kind == K_NAN && a->signaling) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (n == 0) {
        put_one(f, 0, out);                     /* even a quiet NaN */
        return CFT_OK;
    }
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        int neg = a->sign && odd;
        if (n < 0) {
            cft_sf_inf(f, neg, out);
            *flags = CFT_SF_DIVZERO;
        } else {
            cft_sf_zero(f, neg, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        int neg = a->sign && odd;
        if (n < 0)
            cft_sf_zero(f, neg, out);
        else
            cft_sf_inf(f, neg, out);
        return CFT_OK;
    }

    sign = (a->sign && odd) ? 1 : 0;
    if (dyadic_pow_int(f, &a->m, a->e, n, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (vexp < f->emin - f->man_w - 1)
            return round_underflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, sign, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_POWN;
    A.a = *a;
    A.a.sign = 0;
    A.nn = n;
    up = (lane_vexp(a) >= 0) != (n < 0);
    {
        int s = tr_pow_like_screen(&A, sign, up, rnd, out, flags);
        if (s < 0)
            return CFT_ERR_INTERNAL;
        if (s > 0)
            return CFT_OK;
    }
    return tr_ziv(&A, sign, rnd, out, flags);
}

/* x^y defined as exp(y log x), so the domain excludes a negative base
 * and the table is NOT pow's. The rows that differ, and every one of
 * them is a deliberate difference rather than an oversight:
 *
 *   powr(x, y) for x < 0            invalid, for EVERY y, a NaN included
 *   powr(+-0, +-0)                  invalid
 *   powr(+inf, +-0)                 invalid
 *   powr(+1, +-inf)                 invalid
 *   powr(qNaN, y), powr(x, qNaN)    qNaN and silent - so powr(qNaN, 0)
 *                                   is a NaN where pow(qNaN, 0) is 1,
 *                                   which is the point of having both
 *
 * MPFR 4.2.2 returns 1 for mpfr_powr(1, qNaN); the standard's row is
 * "powr(+1, y) is 1 for FINITE y" and it lists powr(x, qNaN) for x >= 0
 * separately, so this contract delivers the quiet NaN. Measured and
 * recorded in docs/TRANSCENDENTALS.md.
 */
static cft_status do_powr(const cft_fmt_desc *f, const lane *x, const lane *y,
                          int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;
    long e;
    int up;

    *flags = 0;
    if ((x->kind == K_NAN && x->signaling) ||
        (y->kind == K_NAN && y->signaling)) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    /* x < 0 outranks even a quiet NaN exponent: it is a domain error,
     * and 9.2.1's NaN row is written "for x >= 0". */
    if (x->kind != K_NAN && x->sign && x->kind != K_ZERO) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (x->kind == K_NAN || y->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }
    if (x->kind == K_ZERO) {
        if (y->kind == K_ZERO) {
            cft_sf_qnan(f, out);                /* powr(+-0, +-0) */
            *flags = CFT_SF_INVALID;
        } else if (y->sign) {
            cft_sf_inf(f, 0, out);
            if (y->kind != K_INF)
                *flags = CFT_SF_DIVZERO;        /* the pole, not the limit */
        } else {
            cft_sf_zero(f, 0, out);
        }
        return CFT_OK;
    }
    if (x->kind == K_INF) {                     /* +inf only */
        if (y->kind == K_ZERO) {
            cft_sf_qnan(f, out);                /* powr(+inf, +-0) */
            *flags = CFT_SF_INVALID;
        } else if (y->sign) {
            cft_sf_zero(f, 0, out);
        } else {
            cft_sf_inf(f, 0, out);
        }
        return CFT_OK;
    }
    if (lane_is_one(x)) {
        if (y->kind == K_INF) {
            cft_sf_qnan(f, out);                /* powr(+1, +-inf) */
            *flags = CFT_SF_INVALID;
        } else {
            put_one(f, 0, out);                 /* every finite y */
        }
        return CFT_OK;
    }
    if (y->kind == K_ZERO) {
        put_one(f, 0, out);                     /* finite x > 0 */
        return CFT_OK;
    }
    if (y->kind == K_INF) {
        if ((lane_vexp(x) >= 0) == !y->sign)
            cft_sf_inf(f, 0, out);
        else
            cft_sf_zero(f, 0, out);
        return CFT_OK;
    }

    if (pow_dyadic(f, x, y, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (vexp < f->emin - f->man_w - 1)
            return round_underflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, 0, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_POWR;
    A.a = *x;
    A.b = *y;
    up = (lane_vexp(x) >= 0) != (y->sign != 0);
    {
        int s = tr_pow_like_screen(&A, 0, up, rnd, out, flags);
        if (s < 0)
            return CFT_ERR_INTERNAL;
        if (s > 0)
            return CFT_OK;
    }
    return tr_ziv(&A, 0, rnd, out, flags);
}

/* (1 + x)^n for an integer n, on [-1, +inf].
 *
 * 9.2.1's rows, and the one an implementation is most likely to get
 * wrong is the first: compound(x, 0) is 1 "for x >= -1 or quiet NaN",
 * which makes compound(x, 0) for x < -1 INVALID rather than 1. MPFR
 * 4.2.2 agrees (measured: mpfr_compound_si(-2, 0) is NaN).
 *
 * 1 + x is formed EXACTLY and then raised by pown's own procedure, so
 * compound(2^-1074, 1) at binary64 is the correctly rounded 1 + 2^-1074
 * - which is 1 with inexact, and is NOT what evaluating (1 + x)^1 in
 * the format would give.
 */
static cft_status do_compound(const cft_fmt_desc *f, const lane *a,
                              int64_t n, int rnd, cft_bn *out,
                              uint32_t *flags)
{
    tr_args A;
    cft_bn sm, m;
    long se, e;
    int below, up;

    *flags = 0;
    if (a->kind == K_NAN && a->signaling) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    below = a->kind != K_NAN && a->sign &&
            (a->kind == K_INF || (a->kind != K_ZERO && !lane_is_one(a) &&
                                  lane_vexp(a) >= 0));
    if (n == 0) {
        if (a->kind == K_NAN) {
            put_one(f, 0, out);                 /* even a quiet NaN */
        } else if (below) {
            cft_sf_qnan(f, out);
            *flags = CFT_SF_INVALID;
        } else {
            put_one(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }
    if (below) {
        cft_sf_qnan(f, out);                    /* x < -1, -inf included */
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->sign && a->kind != K_ZERO && lane_is_one(a)) {   /* x == -1 */
        if (n < 0) {
            cft_sf_inf(f, 0, out);
            *flags = CFT_SF_DIVZERO;
        } else {
            cft_sf_zero(f, 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        put_one(f, 0, out);                     /* compound(+-0, n) = 1 */
        return CFT_OK;
    }
    if (a->kind == K_INF) {                     /* +inf */
        if (n > 0)
            cft_sf_inf(f, 0, out);
        else
            cft_sf_zero(f, 0, out);
        return CFT_OK;
    }

    if (lane_one_plus(a, &sm, &se, f->prec + 4) == 0 &&
        dyadic_pow_int(f, &sm, se, n, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (vexp < f->emin - f->man_w - 1)
            return round_underflowing(f, 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, 0, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_COMPOUND;
    A.a = *a;
    A.nn = n;
    up = (a->sign == 0) != (n < 0);             /* 1 + x is above 1 iff x is */
    {
        int s = tr_pow_like_screen(&A, 0, up, rnd, out, flags);
        if (s < 0)
            return CFT_ERR_INTERNAL;
        if (s > 0)
            return CFT_OK;
    }

    /* A DOMINANT operand, and the second family in this set that no
     * working precision reaches. For a large x the value is x^n times
     * (1 + 1/x)^n, and when x^n is itself an exact dyadic the correction
     * is below a quarter of the grid step there - so the side settles
     * it, exactly as hypot's dominant operand is settled.
     *
     * Without this, compound(2^1022, 1) at binary64 is 2^1022 + 1: one
     * unit above a grid point whose ulp is 2^970, and no precision under
     * the cap separates them.
     *
     * The threshold is derived. vexp(x) >= p + 2 + bits(|n|) makes
     * |n/x| < 2^-(p+2); the binomial tail |(1+1/x)^n - 1 - n/x| is below
     * 2(n/x)^2 and so below it again; and a quarter of the relative grid
     * step is 2^-(p+1). The correction's SIGN is n's, because 1 + 1/x is
     * above 1 for a positive x. */
    {
        uint64_t an = i64_abs(n);
        int nbits = 0;
        while (an) {
            nbits++;
            an >>= 1;
        }
        if (!a->sign &&
            lane_vexp(a) >= (long)f->prec + 2 + nbits &&
            dyadic_pow_int(f, &a->m, a->e, n, &m, &e) == 0)
            return round_side(f, 0, &m, e, n > 0, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
    }
    return tr_ziv(&A, 0, rnd, out, flags);
}

/* x^(1/n) for a nonzero integer n.
 *
 * rootn(x, 1) is x, exactly and silently. rootn(x, 2) is squareRoot(x)
 * on every input EXCEPT x = -0, where the standard's own NOTE says they
 * differ: rootn(-0, 2) is +0 by the even-n row where squareRoot(-0) is
 * -0. host/tests/transcend_check.py tests both halves of that.
 *
 * EXACT exactly when the odd significand is a perfect |n|-th power and
 * |n| divides the exponent, which one verified integer root decides;
 * a negative n turns it into a reciprocal, dyadic only when that root
 * is 1. For a large |n| the answer is inside the half gap next to 1 and
 * the beside-1 rule delivers it, which is the same rule pow uses and the
 * reason exp(log(x)/n) never has to be evaluated for an |n| that would
 * make it meaningless.
 */
static cft_status do_rootn(const cft_fmt_desc *f, const lane *a, int64_t n,
                           int rnd, cft_bn *out, uint32_t *flags)
{
    tr_args A;
    cft_bn m;
    long e;
    int odd = (int)(n & 1), sign, up;

    *flags = 0;
    if (a->kind == K_NAN && a->signaling) {
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (n == 0) {
        /* Table 9.1: "n = 0: invalid operation". Zero is outside the
         * domain for EVERY x, a quiet NaN included, and 9.2's rule for
         * an operand outside the domain is a quiet NaN with invalid. */
        cft_sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (a->kind == K_NAN) {
        cft_sf_qnan(f, out);
        return CFT_OK;
    }
    if (a->kind == K_ZERO) {
        if (n < 0) {
            cft_sf_inf(f, (odd && a->sign) ? 1 : 0, out);
            *flags = CFT_SF_DIVZERO;
        } else {
            cft_sf_zero(f, (odd && a->sign) ? 1 : 0, out);
        }
        return CFT_OK;
    }
    if (a->kind == K_INF) {
        if (a->sign && !odd) {
            cft_sf_qnan(f, out);
            *flags = CFT_SF_INVALID;
        } else if (n > 0) {
            cft_sf_inf(f, a->sign, out);
        } else {
            cft_sf_zero(f, a->sign, out);
        }
        return CFT_OK;
    }
    if (a->sign && !odd) {
        cft_sf_qnan(f, out);                    /* x < 0 with an even n */
        *flags = CFT_SF_INVALID;
        return CFT_OK;
    }
    if (n == 1) {
        cft_tr_exact++;                         /* rootn(x, 1) = x */
        return round_exact(f, a->sign, &a->m, a->e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    sign = a->sign;
    if (rootn_dyadic(f, a, n, &m, &e) == 0) {
        long vexp = e + cft_bn_bitlen(&m) - 1;
        cft_tr_exact++;
        if (vexp > f->emax)
            return round_overflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        if (vexp < f->emin - f->man_w - 1)
            return round_underflowing(f, sign, rnd, out, flags)
                ? CFT_ERR_INTERNAL : CFT_OK;
        return round_exact(f, sign, &m, e, rnd, out, flags)
            ? CFT_ERR_INTERNAL : CFT_OK;
    }

    memset(&A, 0, sizeof A);
    A.f = f;
    A.fn = CFT_TR_ROOTN;
    A.a = *a;
    A.a.sign = 0;
    A.nn = n;
    up = (lane_vexp(a) >= 0) != (n < 0);
    {
        int s = tr_pow_like_screen(&A, sign, up, rnd, out, flags);
        if (s < 0)
            return CFT_ERR_INTERNAL;
        if (s > 0)
            return CFT_OK;
    }
    return tr_ziv(&A, sign, rnd, out, flags);
}

/* ---- the public entry points ---------------------------------------- */

static int rnd_ok(cft_round rnd)
{
    return (int)rnd >= 0 && (int)rnd <= 4;
}

static cft_status tr_validate(cft_device *dev, cft_format fmt,
                              const void *a, const void *d, size_t n)
{
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0)
        return CFT_OK;
    if (!a || !d)
        return CFT_ERR_INVALID_ARGUMENT;
    return CFT_OK;
}

static cft_status tr_batch(cft_device *dev, int fn, cft_format fmt,
                           cft_round rnd, const void *a, const void *b,
                           const int64_t *nn, void *d, size_t n,
                           uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = tr_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (cft_tr_arity(fn) == 2) {
        if (!b)
            return CFT_ERR_INVALID_ARGUMENT;
    }
    if (cft_tr_has_int(fn) && !nn)
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    if (n > ((size_t)-1) / (size_t)(f->width / 8))
        return CFT_ERR_INVALID_ARGUMENT;
    if (cft_mp_consts_selfcheck())
        return CFT_ERR_INTERNAL;
    if (fn >= CFT_TR_SIN && fn <= CFT_TR_TAN && tr_2opi_ok())
        return CFT_ERR_INTERNAL;         /* only these three read 2/pi */

    for (i = 0; i < n; i++) {
        lane la, lb;
        cft_bn out;
        uint32_t fl = 0;
        cft_tr_calls++;
        lane_decode(f, (const uint8_t *)a, i, &la);
        memset(&lb, 0, sizeof lb);
        if (b)
            lane_decode(f, (const uint8_t *)b, i, &lb);
        switch (fn) {
        case CFT_TR_EXP:
        case CFT_TR_EXPM1:
        case CFT_TR_EXP2:
            st = do_exp_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_LOG:
        case CFT_TR_LOG2:
        case CFT_TR_LOG10:
            st = do_log_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_LOG1P:
            st = do_log1p(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_POW:
            st = do_pow(f, &la, &lb, (int)rnd, &out, &fl);
            break;
        case CFT_TR_HYPOT:
            st = do_hypot(f, &la, &lb, (int)rnd, &out, &fl);
            break;
        case CFT_TR_SINPI:
        case CFT_TR_COSPI:
        case CFT_TR_TANPI:
            st = do_pi_trig(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ASIN:
        case CFT_TR_ASINPI:
            st = do_asin_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ACOS:
        case CFT_TR_ACOSPI:
            st = do_acos_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ATAN:
        case CFT_TR_ATANPI:
            st = do_atan_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ATAN2:
        case CFT_TR_ATAN2PI:
            st = do_atan2_family(f, fn, &la, &lb, (int)rnd, &out, &fl);
            break;
        case CFT_TR_SIN:
        case CFT_TR_COS:
        case CFT_TR_TAN:
            st = do_radian(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_SINH:
        case CFT_TR_COSH:
            st = do_sinh_cosh(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_TANH:
            st = do_tanh(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ASINH:
            st = do_asinh(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ACOSH:
            st = do_acosh(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_ATANH:
            st = do_atanh(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_EXP2M1:
            st = do_exp2m1(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_EXP10:
        case CFT_TR_EXP10M1:
            st = do_exp10_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_LOG2P1:
        case CFT_TR_LOG10P1:
            st = do_logp1_family(f, fn, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_RSQRT:
            st = do_rsqrt(f, &la, (int)rnd, &out, &fl);
            break;
        case CFT_TR_POWN:
            st = do_pown(f, &la, nn[i], (int)rnd, &out, &fl);
            break;
        case CFT_TR_POWR:
            st = do_powr(f, &la, &lb, (int)rnd, &out, &fl);
            break;
        case CFT_TR_COMPOUND:
            st = do_compound(f, &la, nn[i], (int)rnd, &out, &fl);
            break;
        case CFT_TR_ROOTN:
            st = do_rootn(f, &la, nn[i], (int)rnd, &out, &fl);
            break;
        default:
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (st != CFT_OK)
            return st;
        acc |= fl;
        lane_store(f, (uint8_t *)d, i, &out);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

#define TR_UNARY(name, code)                                              \
CFT_API cft_status name(cft_device *dev, cft_format fmt, cft_round rnd,   \
                        const void *a, void *d, size_t n,                 \
                        uint32_t *flags_out)                              \
{                                                                         \
    return tr_batch(dev, code, fmt, rnd, a, NULL, NULL, d, n, flags_out); \
}

TR_UNARY(cft_exp,   CFT_TR_EXP)
TR_UNARY(cft_expm1, CFT_TR_EXPM1)
TR_UNARY(cft_exp2,  CFT_TR_EXP2)
TR_UNARY(cft_log,   CFT_TR_LOG)
TR_UNARY(cft_log1p, CFT_TR_LOG1P)
TR_UNARY(cft_log2,  CFT_TR_LOG2)
TR_UNARY(cft_log10, CFT_TR_LOG10)

CFT_API cft_status cft_pow(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, const void *b, void *d, size_t n,
                           uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_POW, fmt, rnd, a, b, NULL, d, n,
                    flags_out);
}

CFT_API cft_status cft_hypot(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const void *b, void *d, size_t n,
                             uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_HYPOT, fmt, rnd, a, b, NULL, d, n,
                    flags_out);
}

TR_UNARY(cft_sinpi,  CFT_TR_SINPI)
TR_UNARY(cft_cospi,  CFT_TR_COSPI)
TR_UNARY(cft_tanpi,  CFT_TR_TANPI)
TR_UNARY(cft_asin,   CFT_TR_ASIN)
TR_UNARY(cft_acos,   CFT_TR_ACOS)
TR_UNARY(cft_atan,   CFT_TR_ATAN)
TR_UNARY(cft_asinpi, CFT_TR_ASINPI)
TR_UNARY(cft_acospi, CFT_TR_ACOSPI)
TR_UNARY(cft_atanpi, CFT_TR_ATANPI)

/* y first, then x, as C's atan2 has it - and as every caller expects,
 * which is worth more than matching the (a, b) naming of the operands
 * everywhere else in this header. */
CFT_API cft_status cft_atan2(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const void *b, void *d, size_t n,
                             uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_ATAN2, fmt, rnd, a, b, NULL, d, n,
                    flags_out);
}

CFT_API cft_status cft_atan2pi(cft_device *dev, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               void *d, size_t n, uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_ATAN2PI, fmt, rnd, a, b, NULL, d, n,
                    flags_out);
}

TR_UNARY(cft_sin,   CFT_TR_SIN)
TR_UNARY(cft_cos,   CFT_TR_COS)
TR_UNARY(cft_tan,   CFT_TR_TAN)
TR_UNARY(cft_sinh,  CFT_TR_SINH)
TR_UNARY(cft_cosh,  CFT_TR_COSH)
TR_UNARY(cft_tanh,  CFT_TR_TANH)
TR_UNARY(cft_asinh, CFT_TR_ASINH)
TR_UNARY(cft_acosh, CFT_TR_ACOSH)
TR_UNARY(cft_atanh, CFT_TR_ATANH)

/* The rest of table 9.1. The five unary ones take the shape everything
 * above takes; the four powers do not, and the reason is 9.2.1's:
 * pown, compound and rootn read an INTEGER second operand, so they take
 * an int64_t array beside the encoding array and the element count moves
 * to `count`. powr reads two encodings like pow. */
TR_UNARY(cft_exp2m1,  CFT_TR_EXP2M1)
TR_UNARY(cft_exp10,   CFT_TR_EXP10)
TR_UNARY(cft_exp10m1, CFT_TR_EXP10M1)
TR_UNARY(cft_log2p1,  CFT_TR_LOG2P1)
TR_UNARY(cft_log10p1, CFT_TR_LOG10P1)
TR_UNARY(cft_rsqrt,   CFT_TR_RSQRT)

CFT_API cft_status cft_powr(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, const void *b, void *d, size_t n,
                            uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_POWR, fmt, rnd, a, b, NULL, d, n, flags_out);
}

#define TR_INT1(name, code)                                               \
CFT_API cft_status name(cft_device *dev, cft_format fmt, cft_round rnd,   \
                        const void *a, const int64_t *n, void *d,         \
                        size_t count, uint32_t *flags_out)                \
{                                                                         \
    return tr_batch(dev, code, fmt, rnd, a, NULL, n, d, count, flags_out); \
}

TR_INT1(cft_pown,     CFT_TR_POWN)
TR_INT1(cft_compound, CFT_TR_COMPOUND)
TR_INT1(cft_rootn,    CFT_TR_ROOTN)

const char *cft_tr_name(int fn)
{
    switch (fn) {
    case CFT_TR_EXP:   return "exp";
    case CFT_TR_EXPM1: return "expm1";
    case CFT_TR_EXP2:  return "exp2";
    case CFT_TR_LOG:   return "log";
    case CFT_TR_LOG1P: return "log1p";
    case CFT_TR_LOG2:  return "log2";
    case CFT_TR_LOG10: return "log10";
    case CFT_TR_POW:     return "pow";
    case CFT_TR_HYPOT:   return "hypot";
    case CFT_TR_SINPI:   return "sinpi";
    case CFT_TR_COSPI:   return "cospi";
    case CFT_TR_TANPI:   return "tanpi";
    case CFT_TR_ASIN:    return "asin";
    case CFT_TR_ACOS:    return "acos";
    case CFT_TR_ATAN:    return "atan";
    case CFT_TR_ATAN2:   return "atan2";
    case CFT_TR_ASINPI:  return "asinpi";
    case CFT_TR_ACOSPI:  return "acospi";
    case CFT_TR_ATANPI:  return "atanpi";
    case CFT_TR_ATAN2PI: return "atan2pi";
    case CFT_TR_SIN:     return "sin";
    case CFT_TR_COS:     return "cos";
    case CFT_TR_TAN:     return "tan";
    case CFT_TR_SINH:    return "sinh";
    case CFT_TR_COSH:    return "cosh";
    case CFT_TR_TANH:    return "tanh";
    case CFT_TR_ASINH:   return "asinh";
    case CFT_TR_ACOSH:   return "acosh";
    case CFT_TR_ATANH:   return "atanh";
    case CFT_TR_EXP2M1:   return "exp2m1";
    case CFT_TR_EXP10:    return "exp10";
    case CFT_TR_EXP10M1:  return "exp10m1";
    case CFT_TR_LOG2P1:   return "log2p1";
    case CFT_TR_LOG10P1:  return "log10p1";
    case CFT_TR_RSQRT:    return "rsqrt";
    case CFT_TR_POWN:     return "pown";
    case CFT_TR_POWR:     return "powr";
    case CFT_TR_COMPOUND: return "compound";
    case CFT_TR_ROOTN:    return "rootn";
    default:             return "unknown";
    }
}

int cft_tr_arity(int fn)
{
    return (fn == CFT_TR_POW || fn == CFT_TR_HYPOT ||
            fn == CFT_TR_ATAN2 || fn == CFT_TR_ATAN2PI ||
            fn == CFT_TR_POWR) ? 2 : 1;
}

int cft_tr_has_int(int fn)
{
    return fn == CFT_TR_POWN || fn == CFT_TR_COMPOUND ||
           fn == CFT_TR_ROOTN;
}

int cft_tr_from_name(const char *s)
{
    int i;
    for (i = 0; i < CFT_TR_COUNT; i++)
        if (strcmp(cft_tr_name(i), s) == 0)
            return i;
    return -1;
}

cft_status cft_tr_apply(cft_device *dev, int fn, cft_format fmt,
                        cft_round rnd, const void *a, const void *b,
                        const int64_t *nn, void *d, size_t n,
                        uint32_t *flags_out)
{
    return tr_batch(dev, fn, fmt, rnd, a, b, nn, d, n, flags_out);
}
