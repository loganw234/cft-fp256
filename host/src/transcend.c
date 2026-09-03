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

void cft_tr_reset_stats(void)
{
    cft_tr_calls = 0;
    cft_tr_ziv_calls = 0;
    cft_tr_escalations = 0;
    cft_tr_max_prec = 0;
    cft_tr_exact = 0;
    cft_tr_neighbour = 0;
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

    case CFT_TR_LOG1P: {
        long v = lane_vexp(&A->a);
        if (cft_mp_set_bn(&x, Wi, A->a.sign, &A->a.m, A->a.e))
            return 1;
        if (v <= -2) {
            if (mp_log1p_small(&l, &x, Wi))
                return 1;
        } else if (v <= (long)f->prec + 30) {
            cft_mp one;
            if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_add(&t, &one, &x, Wi))
                return 1;
            if (t.zero || t.sign)
                return 1;                /* u <= -1 was handled upstream */
            if (mp_log_exact(&l, &t.m, t.exp, Wi))
                return 1;
        } else {
            cft_mp inv, one, part;
            if (cft_mp_set_ui(&one, Wi, 0, 1, 0))
                return 1;
            if (cft_mp_div(&inv, &one, &x, Wi))
                return 1;
            if (mp_log1p_small(&part, &inv, Wi))
                return 1;
            if (mp_log_exact(&l, &A->a.m, A->a.e, Wi))
                return 1;
            if (cft_mp_add(&t, &l, &part, Wi))
                return 1;
            cft_mp_copy(&l, &t);
        }
        if (l.sign)
            cft_mp_neg(&l);
        cft_mp_copy(r, &l);
        return 0;
    }

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
    case CFT_TR_EXP2:
        return cft_mp_set_bn(q, W, A->a.sign, &A->a.m, A->a.e);
    case CFT_TR_POW:
        if (mp_log_exact(&l, &A->a.m, A->a.e, W))
            return 1;
        if (cft_mp_set_bn(&x, W, A->b.sign, &A->b.m, A->b.e))
            return 1;
        if (cft_mp_mul(&t, &x, &l, W))
            return 1;
        return cft_mp_mul(q, &t, &e2, W);
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
                           void *d, size_t n, uint32_t *flags_out)
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
        if (flags_out)
            *flags_out = 0;
        return CFT_OK;
    }
    if (cft_tr_arity(fn) == 2) {
        if (!b)
            return CFT_ERR_INVALID_ARGUMENT;
    }
    f = &cft_sf_formats[(int)fmt];
    if (n > ((size_t)-1) / (size_t)(f->width / 8))
        return CFT_ERR_INVALID_ARGUMENT;
    if (cft_mp_consts_selfcheck())
        return CFT_ERR_INTERNAL;

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
        default:
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (st != CFT_OK)
            return st;
        acc |= fl;
        lane_store(f, (uint8_t *)d, i, &out);
    }
    if (flags_out)
        *flags_out = acc;
    return CFT_OK;
}

#define TR_UNARY(name, code)                                              \
CFT_API cft_status name(cft_device *dev, cft_format fmt, cft_round rnd,   \
                        const void *a, void *d, size_t n,                 \
                        uint32_t *flags_out)                              \
{                                                                         \
    return tr_batch(dev, code, fmt, rnd, a, NULL, d, n, flags_out);       \
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
    return tr_batch(dev, CFT_TR_POW, fmt, rnd, a, b, d, n, flags_out);
}

CFT_API cft_status cft_hypot(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const void *b, void *d, size_t n,
                             uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_HYPOT, fmt, rnd, a, b, d, n, flags_out);
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
    return tr_batch(dev, CFT_TR_ATAN2, fmt, rnd, a, b, d, n, flags_out);
}

CFT_API cft_status cft_atan2pi(cft_device *dev, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               void *d, size_t n, uint32_t *flags_out)
{
    return tr_batch(dev, CFT_TR_ATAN2PI, fmt, rnd, a, b, d, n, flags_out);
}

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
    default:             return "unknown";
    }
}

int cft_tr_arity(int fn)
{
    return (fn == CFT_TR_POW || fn == CFT_TR_HYPOT ||
            fn == CFT_TR_ATAN2 || fn == CFT_TR_ATAN2PI) ? 2 : 1;
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
                        void *d, size_t n, uint32_t *flags_out)
{
    return tr_batch(dev, fn, fmt, rnd, a, b, d, n, flags_out);
}
