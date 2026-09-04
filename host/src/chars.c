/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * IEEE 754-2019 clause 5.12 - conversions between the binary
 * interchange formats and external character sequences - and clause
 * 9.7's three NaN payload operations.
 *
 * python/cft_golden/chars.py defines every result here, exactly as
 * softfloat.py defines softfloat.c's, and the two are held together by
 * host/tests/character_check.py and by the character vector sets.
 *
 * HOST operations, every one: no cft_run pass is issued, the device
 * argument is context, and the results are bit-identical on every
 * backend by construction. There is nothing for a tile to accelerate -
 * the work is exact integer division and digit generation.
 *
 * ---------------------------------------------------------------
 * Why this file carries its own bignum
 * ---------------------------------------------------------------
 *
 * bigint.h is FIXED at 2048 bits, which is exactly right for what it
 * was written for: softfloat.c bounds its operand alignment and needs
 * about 1200 bits, and a fixed container costs stack rather than
 * allocation. Decimal conversion cannot be bounded that way. The exact
 * decimal expansion of the smallest binary256 subnormal is
 * 5^262378 * 10^-262378 - about 183,000 significant digits, 609,000
 * bits - and reading that same string back needs 10^262378, another
 * 872,000 bits. Those lengths come from the FORMAT, not from a design
 * choice, so a fixed container cannot be sized for them without being
 * absurd for every other call.
 *
 * So this file has a growable natural number: a limb vector with
 * add/compare/shift, multiply-and-add by a small integer, divide by
 * 10^9 with a remainder, a schoolbook multiply, binary
 * exponentiation for 5^k and 10^k, and one bounded long division.
 * Nothing else. Every allocation is checked and every path frees;
 * an allocation failure is CFT_ERR_OUT_OF_MEMORY, never a truncated
 * answer. Performance is not a goal here and the code says so where
 * it matters; correctness at every length is.
 *
 * ---------------------------------------------------------------
 * The exactness argument
 * ---------------------------------------------------------------
 *
 * A decimal sequence denotes (-1)^s * D * 10^K exactly - a RATIONAL,
 * num/den with den 1 or 10^-K. The binary window is ONE integer
 * division: with q = (bitlen(num) - bitlen(den)) - W and W = p + 3,
 * m = floor(num / (den * 2^q)) has W or W+1 bits and the remainder
 * says whether anything is left below it. The value is then exactly
 * (m + eps) * 2^q with eps in [0,1), non-zero exactly when the
 * remainder is - which is cft_sf_round_pack's own (m, e, sticky)
 * precondition. So the rounding and every flag come from the
 * library's single rounding authority, on an exactly-derived operand,
 * at any length. A hex sequence is the same argument with den = 1.
 *
 * The other direction needs no rounding authority at all in the exact
 * mode: m * 2^e is m * 5^-e * 10^e for e < 0 and m << e for e >= 0,
 * both integers, and their decimal digits ARE the answer. The
 * H-digit mode rounds that exact digit string on the decimal grid,
 * with the same guard/sticky/lsb rule round_pack applies on the
 * binary one - which is what makes "correctly rounded to H digits"
 * mean the same thing in both directions.
 *
 * ---------------------------------------------------------------
 * Clamping, and why it is not an approximation
 * ---------------------------------------------------------------
 *
 * A sequence's exponent is a caller-supplied integer: "1e999999999999"
 * is in the syntax. Materialising 10^999999999999 would be a denial of
 * service rather than a conversion, so two bands are answered without
 * doing the work:
 *
 *   a value whose leading bit sits at emax + 1 or above overflows in
 *   every attribute, and round_pack's delivered value and flags there
 *   depend on nothing but the attribute and the sign;
 *
 *   a value strictly below half the smallest subnormal - leading bit
 *   at emin - man_w - 2 or below - rounds to zero or to the smallest
 *   subnormal by attribute and sign alone, with inexact and underflow
 *   raised either way.
 *
 * Each band is replaced by ONE representative inside it, so the answer
 * is identical by construction rather than approximately right. The
 * band test brackets log2(10) with exact rational bounds and uses no
 * floating point. Outside the bands the exponent is bounded by the
 * format (about +-79,000 in decimal at fp256) and the arithmetic is
 * done in full.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

/* ------------------------------------------------------------------
 * A growable natural number
 *
 * Little-endian 32-bit limbs with 64-bit intermediates, the same
 * choice bigint.h makes and for the same reason: bit-exactness across
 * machines is the product, so nothing here may depend on the host's
 * word size. n is the significant limb count and v[n-1] is never
 * zero, so a small value stays cheap in a container sized for a large
 * one. Every function that can allocate returns 0, or 1 when it could
 * not - and callers turn that into CFT_ERR_OUT_OF_MEMORY.
 * ------------------------------------------------------------------ */

typedef struct {
    uint32_t *v;
    size_t    n;
    size_t    cap;
} nat;

static void nat_init(nat *a)
{
    a->v = NULL;
    a->n = 0;
    a->cap = 0;
}

static void nat_free(nat *a)
{
    free(a->v);
    a->v = NULL;
    a->n = 0;
    a->cap = 0;
}

static int nat_reserve(nat *a, size_t limbs)
{
    uint32_t *nv;
    size_t want;
    if (limbs <= a->cap)
        return 0;
    want = a->cap ? a->cap : 8;
    while (want < limbs) {
        if (want > ((size_t)-1) / 2 / sizeof *nv)
            return 1;
        want *= 2;
    }
    nv = (uint32_t *)realloc(a->v, want * sizeof *nv);
    if (!nv)
        return 1;
    a->v = nv;
    a->cap = want;
    return 0;
}

static void nat_trim(nat *a)
{
    while (a->n && a->v[a->n - 1] == 0)
        a->n--;
}

static int nat_is_zero(const nat *a) { return a->n == 0; }

static int nat_set_u32(nat *a, uint32_t x)
{
    if (nat_reserve(a, 1))
        return 1;
    a->v[0] = x;
    a->n = x ? 1 : 0;
    return 0;
}

static int nat_copy(nat *r, const nat *a)
{
    if (r == a)
        return 0;
    if (nat_reserve(r, a->n + 1))
        return 1;
    if (a->n)
        memcpy(r->v, a->v, a->n * sizeof *a->v);
    r->n = a->n;
    return 0;
}

static size_t nat_bitlen(const nat *a)
{
    uint32_t top;
    size_t k = 0;
    if (!a->n)
        return 0;
    top = a->v[a->n - 1];
    while (top) {
        top >>= 1;
        k++;
    }
    return (a->n - 1) * 32 + k;
}

static int nat_cmp(const nat *a, const nat *b)
{
    size_t i;
    if (a->n != b->n)
        return a->n < b->n ? -1 : 1;
    for (i = a->n; i-- > 0; )
        if (a->v[i] != b->v[i])
            return a->v[i] < b->v[i] ? -1 : 1;
    return 0;
}

/* a -= b; the caller guarantees a >= b. */
static void nat_sub_in(nat *a, const nat *b)
{
    uint64_t borrow = 0;
    size_t i;
    for (i = 0; i < a->n; i++) {
        uint64_t bv = i < b->n ? b->v[i] : 0;
        uint64_t cur = (uint64_t)a->v[i] - bv - borrow;
        a->v[i] = (uint32_t)cur;
        /* The true difference lies in [-2^32, 2^32); a negative one
         * wraps to at least 2^64 - 2^32, which is the only way bit 63
         * can be set. */
        borrow = (cur >> 63) & 1u;
    }
    nat_trim(a);
}

/* r = a << k. r must not alias a. */
static int nat_shl(nat *r, const nat *a, size_t k)
{
    size_t limbs = k >> 5, bits = k & 31, i, n;
    if (a->n == 0) {
        r->n = 0;
        return 0;
    }
    n = a->n + limbs + 1;
    if (nat_reserve(r, n))
        return 1;
    memset(r->v, 0, n * sizeof *r->v);
    for (i = 0; i < a->n; i++) {
        uint64_t v = (uint64_t)a->v[i] << bits;
        r->v[i + limbs]     |= (uint32_t)v;
        r->v[i + limbs + 1] |= (uint32_t)(v >> 32);
    }
    r->n = n;
    nat_trim(r);
    return 0;
}

/* a >>= 1. */
static void nat_shr1(nat *a)
{
    size_t i;
    for (i = 0; i < a->n; i++) {
        uint32_t hi = (i + 1 < a->n) ? a->v[i + 1] : 0;
        a->v[i] = (a->v[i] >> 1) | (hi << 31);
    }
    nat_trim(a);
}

/* r = a >> k. r must not alias a. */
static int nat_shr(nat *r, const nat *a, size_t k)
{
    size_t limbs = k >> 5, bits = k & 31, i, n;
    if (limbs >= a->n) {
        r->n = 0;
        return 0;
    }
    n = a->n - limbs;
    if (nat_reserve(r, n))
        return 1;
    for (i = 0; i < n; i++) {
        uint32_t lo = a->v[i + limbs];
        uint32_t hi = (i + limbs + 1 < a->n) ? a->v[i + limbs + 1] : 0u;
        r->v[i] = bits ? ((lo >> bits) | (hi << (32 - bits))) : lo;
    }
    r->n = n;
    nat_trim(r);
    return 0;
}

/* a = a * m + add. */
static int nat_muladd_small(nat *a, uint32_t m, uint32_t add)
{
    uint64_t carry = add;
    size_t i;
    if (nat_reserve(a, a->n + 1))
        return 1;
    for (i = 0; i < a->n; i++) {
        uint64_t cur = (uint64_t)a->v[i] * m + carry;
        a->v[i] = (uint32_t)cur;
        carry = cur >> 32;
    }
    if (carry)
        a->v[a->n++] = (uint32_t)carry;
    return 0;
}

/* a /= 10^9, returning the remainder.
 *
 * The divide-by-a-small-integer this file needs, and the only one:
 * 10^9 is the chunk a decimal expansion comes out in, and its being a
 * LITERAL rather than a parameter is what lets the compiler turn
 * the 64-by-32 division into a multiply-and-shift. Measured on this
 * toolchain that is the difference between a hardware divide per limb
 * per chunk and a couple of multiplies - and the decimal expansion of
 * an fp256 subnormal runs to 20,000 chunks over 19,000 limbs, so it
 * is most of the cost of the exact conversion. */
static uint32_t nat_div_1e9(nat *a)
{
    uint64_t r = 0;
    size_t i;
    for (i = a->n; i-- > 0; ) {
        uint64_t cur = (r << 32) | a->v[i];
        a->v[i] = (uint32_t)(cur / 1000000000u);
        r = cur % 1000000000u;
    }
    nat_trim(a);
    return (uint32_t)r;
}

/* r = a * b, schoolbook. r must not alias either operand. */
static int nat_mul(nat *r, const nat *a, const nat *b)
{
    size_t i, j, n;
    if (a->n == 0 || b->n == 0) {
        r->n = 0;
        return 0;
    }
    n = a->n + b->n;
    if (nat_reserve(r, n))
        return 1;
    memset(r->v, 0, n * sizeof *r->v);
    for (i = 0; i < a->n; i++) {
        uint64_t carry = 0, av = a->v[i];
        if (!av)
            continue;
        for (j = 0; j < b->n; j++) {
            uint64_t cur = av * b->v[j] + r->v[i + j] + carry;
            r->v[i + j] = (uint32_t)cur;
            carry = cur >> 32;
        }
        /* Nothing has been written at or above i + b->n yet, so this
         * is an assignment rather than an add. */
        r->v[i + b->n] = (uint32_t)carry;
    }
    r->n = n;
    nat_trim(r);
    return 0;
}

/* r = base^e, by squaring. Quadratic in the result's length, which is
 * what makes 10^262378 (872,000 bits) affordable at all. */
static int nat_pow_small(nat *r, uint32_t base, uint64_t e)
{
    nat sq, acc, tmp;
    int rc = 1;
    nat_init(&sq);
    nat_init(&acc);
    nat_init(&tmp);
    if (nat_set_u32(&acc, 1) || nat_set_u32(&sq, base))
        goto done;
    while (e) {
        if (e & 1) {
            if (nat_mul(&tmp, &acc, &sq) || nat_copy(&acc, &tmp))
                goto done;
        }
        e >>= 1;
        if (e) {
            if (nat_mul(&tmp, &sq, &sq) || nat_copy(&sq, &tmp))
                goto done;
        }
    }
    rc = nat_copy(r, &acc);
done:
    nat_free(&sq);
    nat_free(&acc);
    nat_free(&tmp);
    return rc;
}

/* q = floor(a / b), *rem_nz = (a mod b != 0).
 *
 * Binary long division, one bit of quotient per pass over the
 * divisor. That is the right algorithm here and not a lazy one: every
 * quotient this file needs is p + 4 bits wide at most, while the
 * operands can run to a million, so the cost is (p + 4) passes rather
 * than anything proportional to the operand length. `max_shift` is
 * the caller's assertion about that width; exceeding it is an
 * internal invariant failure, not a caller error. */
static int nat_divmod_bounded(nat *q, const nat *a, const nat *b,
                              int *rem_nz, size_t max_shift)
{
    nat R, T;
    size_t la = nat_bitlen(a), lb = nat_bitlen(b), s, i, qlimbs;
    int rc = 1;

    nat_init(&R);
    nat_init(&T);
    if (lb == 0)
        goto done;                       /* the caller never divides by 0 */
    if (la < lb) {
        q->n = 0;
        *rem_nz = !nat_is_zero(a);
        rc = 0;
        goto done;
    }
    s = la - lb;
    if (s > max_shift)
        goto done;
    qlimbs = s / 32 + 1;
    if (nat_reserve(q, qlimbs) || nat_copy(&R, a) || nat_shl(&T, b, s))
        goto done;
    memset(q->v, 0, qlimbs * sizeof *q->v);
    q->n = qlimbs;
    for (i = s + 1; i-- > 0; ) {
        if (nat_cmp(&R, &T) >= 0) {
            nat_sub_in(&R, &T);
            q->v[i >> 5] |= 1u << (i & 31);
        }
        nat_shr1(&T);
    }
    nat_trim(q);
    *rem_nz = !nat_is_zero(&R);
    rc = 0;
done:
    nat_free(&R);
    nat_free(&T);
    return rc;
}

/* ---- bridges to the fixed-width core ----------------------------- */

static int nat_from_bn(nat *r, const cft_bn *b)
{
    int i;
    if (nat_reserve(r, (size_t)(b->n ? b->n : 1)))
        return 1;
    for (i = 0; i < b->n; i++)
        r->v[i] = b->v[i];
    r->n = (size_t)b->n;
    nat_trim(r);
    return 0;
}

/* 1 when the value does not fit bigint.h's fixed container - which
 * only ever happens if a windowing step above went wrong, so callers
 * report it as CFT_ERR_INTERNAL. */
static int nat_to_bn(const nat *a, cft_bn *out)
{
    size_t i;
    if (a->n > CFT_BN_LIMBS)
        return 1;
    cft_bn_zero(out);
    for (i = 0; i < a->n; i++)
        out->v[i] = a->v[i];
    out->n = (int)a->n;
    return 0;
}

/* ------------------------------------------------------------------
 * Format bookkeeping shared with clause5.c's shapes
 * ------------------------------------------------------------------ */

#define K_ZERO 0
#define K_SUB  1
#define K_NORM 2
#define K_INF  3
#define K_NAN  4

typedef struct {
    int kind;
    int sign;
    int signaling;
} lane_cls;

static void lane_load(const cft_fmt_desc *f, const uint8_t *buf, size_t i,
                      cft_bn *v)
{
    cft_bn_load(v, buf + i * (size_t)(f->width / 8), f->width / 8);
}

static void lane_store(const cft_fmt_desc *f, uint8_t *buf, size_t i,
                       const cft_bn *v)
{
    cft_bn_store(v, buf + i * (size_t)(f->width / 8), f->width / 8);
}

static void cls_of(const cft_fmt_desc *f, const cft_bn *x, lane_cls *c)
{
    cft_bn frac;
    uint32_t ef = cft_bn_extract(x, f->man_w, f->exp_w);
    c->sign = cft_bn_bit(x, f->width - 1);
    c->signaling = 0;
    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (ef == f->exp_mask) {
        if (cft_bn_is_zero(&frac)) {
            c->kind = K_INF;
        } else {
            c->kind = K_NAN;
            c->signaling = !cft_bn_bit(x, f->man_w - 1);
        }
        return;
    }
    if (ef == 0) {
        c->kind = cft_bn_is_zero(&frac) ? K_ZERO : K_SUB;
        return;
    }
    c->kind = K_NORM;
}

/* The significand-and-exponent view of a finite non-zero lane. */
static void bn_sig_exp(const cft_fmt_desc *f, const cft_bn *x,
                       const lane_cls *c, cft_bn *m, int *e)
{
    cft_bn_copy(m, x);
    cft_bn_mask(m, f->man_w);
    if (c->kind == K_NORM) {
        cft_bn_setbit(m, f->man_w);
        *e = (int)cft_bn_extract(x, f->man_w, f->exp_w) - f->bias - f->man_w;
    } else {
        *e = f->emin - f->man_w;
    }
}

/* The payload field: bits d2..d(p-1) of the trailing significand
 * (6.2.1), which is everything below the quiet bit. */
static void bn_payload(const cft_fmt_desc *f, const cft_bn *x, cft_bn *out)
{
    cft_bn_copy(out, x);
    cft_bn_mask(out, f->man_w - 1);
}

static void bn_nan_with(const cft_fmt_desc *f, int sign, const cft_bn *payload,
                        int signaling, cft_bn *out)
{
    int i;
    cft_bn_copy(out, payload);
    cft_bn_mask(out, f->man_w - 1);
    for (i = 0; i < f->exp_w; i++)
        cft_bn_setbit(out, f->man_w + i);
    if (!signaling)
        cft_bn_setbit(out, f->man_w - 1);
    if (sign)
        cft_bn_setbit(out, f->width - 1);
}

static int rnd_ok(cft_round rnd) { return (int)rnd >= 0 && (int)rnd <= 4; }

static int size_overflows(const cft_fmt_desc *f, size_t n)
{
    return n > ((size_t)-1) / (size_t)(f->width / 8);
}

/* ------------------------------------------------------------------
 * Rounding an exact rational into the format
 * ------------------------------------------------------------------ */

/* The window: p + 3 bits plus a sticky. p + 2 would do - round_pack
 * needs strictly more than p bits whenever a sticky rides along - and
 * the third bit is margin that costs nothing. */
#define WINDOW 3

/* Exact rational bounds on log2(10), scaled by 10^6. */
#define L10_LO  3321928
#define L10_HI  3321929
#define L10_DEN 1000000

static void log2_10_bounds(int64_t t, int64_t *lo, int64_t *hi)
{
    /* t is bounded by the exponent parser's saturation, so neither
     * product can overflow int64. */
    if (t >= 0) {
        *lo = (t * L10_LO) / L10_DEN;
        *hi = -((-t * L10_HI) / L10_DEN);
    } else {
        *lo = (t * L10_HI) / L10_DEN;
        *hi = -((-t * L10_LO) / L10_DEN);
    }
}

/* The band answer for a non-zero value whose leading-bit position is
 * known to lie in [e_lo, e_hi]; 0 when the bands do not decide it. */
static int band_round(const cft_fmt_desc *f, int sign, int64_t e_lo,
                      int64_t e_hi, int rnd, cft_bn *out, uint32_t *flags)
{
    int w = f->prec + WINDOW, e;
    cft_bn m;
    if (e_lo > (int64_t)f->emax + 1)
        e = f->emax + 1 - w;
    else if (e_hi <= (int64_t)(f->emin - f->man_w - 2))
        e = f->emin - f->man_w - 2 - w;
    else
        return 0;
    cft_bn_zero(&m);
    cft_bn_setbit(&m, w);
    cft_bn_setbit(&m, 0);              /* 2^w + 1: w+1 bits, and inexact */
    if (cft_sf_round_pack(f, sign, &m, e, 0, rnd, out, flags))
        return -1;
    return 1;
}

/* Round the exact non-zero value (-1)^sign * num/den into the format.
 * One bounded division and one round_pack; see the file banner. */
static cft_status round_rational(const cft_fmt_desc *f, int sign,
                                 const nat *num, const nat *den, int rnd,
                                 cft_bn *out, uint32_t *flags)
{
    nat a, b, m;
    cft_bn mb;
    cft_status st = CFT_ERR_OUT_OF_MEMORY;
    int64_t q;
    int rem_nz = 0, w = f->prec + WINDOW;

    nat_init(&a);
    nat_init(&b);
    nat_init(&m);
    q = (int64_t)nat_bitlen(num) - (int64_t)nat_bitlen(den) - w;
    if (q >= 0) {
        if (nat_copy(&a, num) || nat_shl(&b, den, (size_t)q))
            goto done;
    } else {
        if (nat_shl(&a, num, (size_t)(-q)) || nat_copy(&b, den))
            goto done;
    }
    /* m lands with w or w+1 bits by construction, so the long division
     * is that many passes and no more. */
    if (nat_divmod_bounded(&m, &a, &b, &rem_nz, (size_t)w + 2)) {
        st = CFT_ERR_INTERNAL;
        goto done;
    }
    if (nat_bitlen(&m) <= (size_t)f->prec) {
        st = CFT_ERR_INTERNAL;         /* the window argument is wrong */
        goto done;
    }
    if (nat_to_bn(&m, &mb)) {
        st = CFT_ERR_INTERNAL;
        goto done;
    }
    if (cft_sf_round_pack(f, sign, &mb, (int)q, rem_nz, rnd, out, flags))
        st = CFT_ERR_INTERNAL;
    else
        st = CFT_OK;
done:
    nat_free(&a);
    nat_free(&b);
    nat_free(&m);
    return st;
}

/* Round the exact non-zero value (-1)^sign * m * 2^e, m a natural of
 * any width - the hexadecimal sequence's arithmetic, where the value
 * is already dyadic and the only work is windowing m down to
 * something round_pack's fixed container holds. */
static cft_status round_dyadic(const cft_fmt_desc *f, int sign, const nat *m,
                               int64_t e, int rnd, cft_bn *out,
                               uint32_t *flags)
{
    size_t len = nat_bitlen(m), w = (size_t)f->prec + WINDOW, i;
    int64_t lead = e + (int64_t)len - 1;
    int banded, sticky = 0;
    cft_bn mb;

    banded = band_round(f, sign, lead, lead, rnd, out, flags);
    if (banded)
        return banded < 0 ? CFT_ERR_INTERNAL : CFT_OK;

    if (len > w) {
        size_t drop = len - w;
        nat top;
        int rc;
        /* Anything below the window becomes the sticky bit. Scanned a
         * limb at a time and then a bit at a time, because `drop` is
         * bounded only by the caller's sequence: a hexadecimal
         * significand of a million digits is in the syntax. */
        for (i = 0; i < (drop >> 5) && !sticky; i++)
            sticky = m->v[i] != 0;
        for (i = (drop >> 5) << 5; i < drop && !sticky; i++)
            sticky = (m->v[i >> 5] >> (i & 31)) & 1u;
        nat_init(&top);
        rc = nat_shr(&top, m, drop);
        if (!rc)
            rc = nat_to_bn(&top, &mb);
        nat_free(&top);
        if (rc)
            return CFT_ERR_OUT_OF_MEMORY;
        e += (int64_t)drop;
    } else if (nat_to_bn(m, &mb)) {
        return CFT_ERR_INTERNAL;
    }
    if (cft_sf_round_pack(f, sign, &mb, (int)e, sticky, rnd, out, flags))
        return CFT_ERR_INTERNAL;
    return CFT_OK;
}

/* ------------------------------------------------------------------
 * The lexer
 * ------------------------------------------------------------------ */

static int is_digit(int c) { return c >= '0' && c <= '9'; }

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int lower(int c)
{
    return (c >= 'A' && c <= 'Z') ? c - 'A' + 'a' : c;
}

static int ci_eq(const char *s, size_t n, const char *word)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (!word[i] || lower((unsigned char)s[i]) != word[i])
            return 0;
    }
    return word[n] == '\0';
}

/* The exponent field, saturating: a value this large is decided by
 * the bands, so the saturation point only has to be far outside every
 * format's range and inside the range where the log2(10) bounds
 * cannot overflow. */
#define EXP_SATURATE ((int64_t)1000000000)

static int64_t parse_exp_digits(const char *s, size_t n, int neg)
{
    int64_t v = 0;
    size_t i;
    for (i = 0; i < n; i++) {
        if (v < EXP_SATURATE)
            v = v * 10 + (s[i] - '0');
    }
    if (v > EXP_SATURATE)
        v = EXP_SATURATE;
    return neg ? -v : v;
}

/* 1 matched (out written), 0 not one of 5.12.1's words, -1 one of them
 * with a payload this format cannot hold. */
static int lex_special(const cft_fmt_desc *f, const char *body, size_t n,
                       int sign, cft_bn *out)
{
    size_t head = n, open = 0, i;
    int signaling, has_payload = 0, rc = -1;
    nat pay, limit;
    cft_bn payb;

    if (ci_eq(body, n, "inf") || ci_eq(body, n, "infinity")) {
        cft_sf_inf(f, sign, out);
        return 1;
    }
    if (n && body[n - 1] == ')') {
        for (i = 0; i < n; i++)
            if (body[i] == '(') {
                open = i;
                has_payload = 1;
                break;
            }
        if (!has_payload)
            return 0;
        head = open;
    }
    if (ci_eq(body, head, "nan"))
        signaling = 0;
    else if (ci_eq(body, head, "snan"))
        signaling = 1;
    else
        return 0;

    nat_init(&pay);
    nat_init(&limit);
    if (nat_set_u32(&pay, 0) || nat_set_u32(&limit, 1))
        goto done;
    /* limit = 2^(man_w - 1), one past the largest admissible payload */
    {
        nat t;
        nat_init(&t);
        if (nat_shl(&t, &limit, (size_t)(f->man_w - 1)) ||
            nat_copy(&limit, &t)) {
            nat_free(&t);
            goto done;
        }
        nat_free(&t);
    }

    if (has_payload) {
        const char *p = body + open + 1;
        size_t plen = n - open - 2;
        if (plen == 0) {
            rc = 0;                      /* "nan()" is not one of the words */
            goto done;
        }
        if (plen > 2 && p[0] == '0' && lower((unsigned char)p[1]) == 'x') {
            for (i = 2; i < plen; i++) {
                int hv = hexval((unsigned char)p[i]);
                if (hv < 0) {
                    rc = 0;
                    goto done;
                }
                if (nat_muladd_small(&pay, 16, (uint32_t)hv))
                    goto done;
            }
        } else {
            for (i = 0; i < plen; i++) {
                if (!is_digit((unsigned char)p[i])) {
                    rc = 0;
                    goto done;
                }
                if (nat_muladd_small(&pay, 10, (uint32_t)(p[i] - '0')))
                    goto done;
            }
        }
    } else if (signaling) {
        /* A bare "snan" needs SOME payload: payload 0 with the quiet
         * bit clear is an infinity encoding, so it takes the smallest
         * admissible one - which is what setPayloadSignaling accepts
         * as well. */
        if (nat_set_u32(&pay, 1))
            goto done;
    }

    if (nat_cmp(&pay, &limit) >= 0 ||
        (signaling && nat_is_zero(&pay))) {
        rc = -1;                         /* in the syntax, not admissible */
        goto done;
    }
    if (nat_to_bn(&pay, &payb))
        goto done;
    bn_nan_with(f, sign, &payb, signaling, out);
    rc = 1;
done:
    nat_free(&pay);
    nat_free(&limit);
    return rc;
}

/* ------------------------------------------------------------------
 * convertFromDecimalCharacter (5.4.2, 5.12.2)
 * ------------------------------------------------------------------ */

static cft_status from_decimal_one(const cft_fmt_desc *f, const char *s,
                                   int rnd, cft_bn *out, uint32_t *flags)
{
    const char *body;
    size_t n, i, int_beg, int_len, frac_beg = 0, frac_len = 0, nd;
    int sign = 0, sp;
    int64_t k, lo, hi;
    nat digits, num, den, pw;
    cft_status st;

    *flags = 0;
    if (!s)
        return CFT_ERR_INVALID_ARGUMENT;
    n = strlen(s);
    if (n && (s[0] == '+' || s[0] == '-')) {
        sign = s[0] == '-';
        body = s + 1;
        n--;
    } else {
        body = s;
    }
    if (n == 0)
        return CFT_ERR_INVALID_ARGUMENT;

    sp = lex_special(f, body, n, sign, out);
    if (sp)
        return sp > 0 ? CFT_OK : CFT_ERR_INVALID_ARGUMENT;

    i = 0;
    int_beg = 0;
    while (i < n && is_digit((unsigned char)body[i]))
        i++;
    int_len = i;
    if (i < n && body[i] == '.') {
        i++;
        frac_beg = i;
        while (i < n && is_digit((unsigned char)body[i]))
            i++;
        frac_len = i - frac_beg;
    }
    if (int_len == 0 && frac_len == 0)
        return CFT_ERR_INVALID_ARGUMENT;
    k = 0;
    if (i < n) {
        size_t eb;
        int eneg = 0;
        if (lower((unsigned char)body[i]) != 'e')
            return CFT_ERR_INVALID_ARGUMENT;
        i++;
        if (i < n && (body[i] == '+' || body[i] == '-')) {
            eneg = body[i] == '-';
            i++;
        }
        eb = i;
        while (i < n && is_digit((unsigned char)body[i]))
            i++;
        if (i != n || eb == i)
            return CFT_ERR_INVALID_ARGUMENT;
        k = parse_exp_digits(body + eb, i - eb, eneg);
    }
    k -= (int64_t)frac_len;
    /* A saturation, not a semantic clamp: at |k| this large the value
     * is decided by the bands below for any digit string a machine
     * could hold (it would take more than 10^12 digits to reach out of
     * one), and keeping k here also keeps the log2(10) bounds inside
     * int64. */
    if (k > (int64_t)1000000000000)
        k = (int64_t)1000000000000;
    if (k < -(int64_t)1000000000000)
        k = -(int64_t)1000000000000;

    /* The digit string, leading zeros skipped. */
    nat_init(&digits);
    nat_init(&num);
    nat_init(&den);
    nat_init(&pw);
    st = CFT_ERR_OUT_OF_MEMORY;
    nd = 0;
    {
        size_t seen = 0;
        int started = 0;
        uint32_t chunk = 0;
        int in_chunk = 0;
        for (seen = 0; seen < int_len + frac_len; seen++) {
            char c = seen < int_len ? body[int_beg + seen]
                                    : body[frac_beg + (seen - int_len)];
            if (!started && c == '0')
                continue;
            started = 1;
            chunk = chunk * 10u + (uint32_t)(c - '0');
            nd++;
            if (++in_chunk == 9) {
                if (nat_muladd_small(&digits, 1000000000u, chunk))
                    goto done;
                chunk = 0;
                in_chunk = 0;
            }
        }
        if (in_chunk) {
            static const uint32_t P10[9] = {
                10u, 100u, 1000u, 10000u, 100000u, 1000000u,
                10000000u, 100000000u, 1000000000u
            };
            if (nat_muladd_small(&digits, P10[in_chunk - 1], chunk))
                goto done;
        }
    }
    if (nd == 0) {
        /* A zero decimal is a zero, and rounding never changes a sign
         * (754 6.3), so a negative one is -0 in every attribute. */
        cft_sf_zero(f, sign, out);
        st = CFT_OK;
        goto done;
    }

    /* floor(log2(digits)) lies in [b-1, b), and k*log2(10) is
     * bracketed exactly, so the leading bit lands in [b-2+lo, b+hi]. */
    {
        int64_t b = (int64_t)nat_bitlen(&digits);
        int banded;
        log2_10_bounds(k, &lo, &hi);
        banded = band_round(f, sign, b - 2 + lo, b + hi, rnd, out, flags);
        if (banded) {
            st = banded < 0 ? CFT_ERR_INTERNAL : CFT_OK;
            goto done;
        }
    }
    /* Past the bands the decimal exponent is bounded by the format -
     * about +-79,000 at fp256, plus the caller's digit count - so
     * 10^|k| is affordable and the arithmetic is done in full. */
    if (k >= 0) {
        if (nat_pow_small(&pw, 10, (uint64_t)k) || nat_mul(&num, &digits, &pw)
            || nat_set_u32(&den, 1))
            goto done;
    } else {
        if (nat_copy(&num, &digits) ||
            nat_pow_small(&den, 10, (uint64_t)(-k)))
            goto done;
    }
    st = round_rational(f, sign, &num, &den, rnd, out, flags);
done:
    nat_free(&digits);
    nat_free(&num);
    nat_free(&den);
    nat_free(&pw);
    return st;
}

/* ------------------------------------------------------------------
 * convertFromHexCharacter (5.4.3, 5.12.3)
 * ------------------------------------------------------------------ */

static cft_status from_hex_one(const cft_fmt_desc *f, const char *s, int rnd,
                               cft_bn *out, uint32_t *flags)
{
    const char *body;
    size_t n, i, int_beg, int_len, frac_beg = 0, frac_len = 0, nd = 0;
    int sign = 0, sp, eneg = 0;
    int64_t e;
    nat m;
    cft_status st;

    *flags = 0;
    if (!s)
        return CFT_ERR_INVALID_ARGUMENT;
    n = strlen(s);
    if (n && (s[0] == '+' || s[0] == '-')) {
        sign = s[0] == '-';
        body = s + 1;
        n--;
    } else {
        body = s;
    }
    if (n == 0)
        return CFT_ERR_INVALID_ARGUMENT;

    sp = lex_special(f, body, n, sign, out);
    if (sp)
        return sp > 0 ? CFT_OK : CFT_ERR_INVALID_ARGUMENT;

    if (n < 2 || body[0] != '0' || lower((unsigned char)body[1]) != 'x')
        return CFT_ERR_INVALID_ARGUMENT;
    i = 2;
    int_beg = i;
    while (i < n && hexval((unsigned char)body[i]) >= 0)
        i++;
    int_len = i - int_beg;
    if (i < n && body[i] == '.') {
        i++;
        frac_beg = i;
        while (i < n && hexval((unsigned char)body[i]) >= 0)
            i++;
        frac_len = i - frac_beg;
    }
    if (int_len == 0 && frac_len == 0)
        return CFT_ERR_INVALID_ARGUMENT;
    /* 5.12.3's grammar writes {decExponent}, not {decExponent}? - the
     * binary exponent is required, and a sequence without one is a
     * refusal rather than an assumed p+0. */
    if (i >= n || lower((unsigned char)body[i]) != 'p')
        return CFT_ERR_INVALID_ARGUMENT;
    i++;
    if (i < n && (body[i] == '+' || body[i] == '-')) {
        eneg = body[i] == '-';
        i++;
    }
    {
        size_t eb = i;
        while (i < n && is_digit((unsigned char)body[i]))
            i++;
        if (i != n || eb == i)
            return CFT_ERR_INVALID_ARGUMENT;
        e = parse_exp_digits(body + eb, i - eb, eneg);
    }
    e -= 4 * (int64_t)frac_len;

    nat_init(&m);
    st = CFT_ERR_OUT_OF_MEMORY;
    {
        size_t seen;
        int started = 0;
        for (seen = 0; seen < int_len + frac_len; seen++) {
            char c = seen < int_len ? body[int_beg + seen]
                                    : body[frac_beg + (seen - int_len)];
            int hv = hexval((unsigned char)c);
            if (!started && hv == 0)
                continue;
            started = 1;
            nd++;
            if (nat_muladd_small(&m, 16, (uint32_t)hv))
                goto done;
        }
    }
    if (nd == 0) {
        cft_sf_zero(f, sign, out);
        st = CFT_OK;
        goto done;
    }
    st = round_dyadic(f, sign, &m, e, rnd, out, flags);
done:
    nat_free(&m);
    return st;
}

/* ------------------------------------------------------------------
 * The output side
 * ------------------------------------------------------------------ */

/* A growable char buffer for the answer. The library assembles the
 * whole sequence before it looks at the caller's capacity, so a buffer
 * too small is refused with the required length and NOTHING written -
 * a truncated number would be a wrong answer that looks like a right
 * one. */
typedef struct {
    char  *s;
    size_t n;
    size_t cap;
} sbuf;

static void sb_init(sbuf *b) { b->s = NULL; b->n = 0; b->cap = 0; }
static void sb_free(sbuf *b) { free(b->s); b->s = NULL; b->n = b->cap = 0; }

static int sb_reserve(sbuf *b, size_t want)
{
    char *ns;
    size_t cap;
    if (want <= b->cap)
        return 0;
    cap = b->cap ? b->cap : 64;
    while (cap < want) {
        if (cap > ((size_t)-1) / 2)
            return 1;
        cap *= 2;
    }
    ns = (char *)realloc(b->s, cap);
    if (!ns)
        return 1;
    b->s = ns;
    b->cap = cap;
    return 0;
}

static int sb_putc(sbuf *b, char c)
{
    if (sb_reserve(b, b->n + 1))
        return 1;
    b->s[b->n++] = c;
    return 0;
}

static int sb_puts(sbuf *b, const char *s, size_t n)
{
    if (sb_reserve(b, b->n + n))
        return 1;
    memcpy(b->s + b->n, s, n);
    b->n += n;
    return 0;
}

/* An explicitly signed decimal integer, written without printf so no
 * locale can reach it. */
static int sb_put_exp(sbuf *b, long v)
{
    char tmp[24];
    int k = 0;
    unsigned long mag = v < 0 ? (unsigned long)(-(v + 1)) + 1ul
                              : (unsigned long)v;
    if (sb_putc(b, v < 0 ? '-' : '+'))
        return 1;
    do {
        tmp[k++] = (char)('0' + (int)(mag % 10ul));
        mag /= 10ul;
    } while (mag);
    while (k--)
        if (sb_putc(b, tmp[k]))
            return 1;
    return 0;
}

/* The decimal digits of a natural number, most significant first.
 * Repeated division by 10^9: the compiler turns a 64-by-constant
 * division into a multiply, so this is a few cycles per limb per
 * chunk rather than a hardware divide. */
static int nat_digits(nat *a, char **out, size_t *len)
{
    size_t bits = nat_bitlen(a), cap, pos;
    char *buf;
    if (bits == 0)
        return 1;
    cap = bits / 3 + 4;               /* a digit is more than 3 bits */
    buf = (char *)malloc(cap);
    if (!buf)
        return 1;
    pos = cap;
    while (!nat_is_zero(a)) {
        uint32_t rem = nat_div_1e9(a);
        int j;
        if (nat_is_zero(a)) {
            while (rem) {
                buf[--pos] = (char)('0' + (int)(rem % 10u));
                rem /= 10u;
            }
        } else {
            for (j = 0; j < 9; j++) {
                buf[--pos] = (char)('0' + (int)(rem % 10u));
                rem /= 10u;
            }
        }
    }
    *out = buf;
    *len = cap - pos;
    memmove(buf, buf + pos, cap - pos);
    return 0;
}

/* The 5.12.1 spelling of a zero, an infinity or a NaN; 0 when the lane
 * is a finite non-zero number. `zero_text` is what a zero prints as,
 * which is the one thing the two radices spell differently. */
static int special_text(const cft_fmt_desc *f, const cft_bn *x,
                        const lane_cls *c, const char *zero_text, sbuf *b)
{
    if (c->kind == K_NORM || c->kind == K_SUB)
        return 0;
    if (c->sign && sb_putc(b, '-'))
        return -1;
    if (c->kind == K_ZERO)
        return sb_puts(b, zero_text, strlen(zero_text)) ? -1 : 1;
    if (c->kind == K_INF)
        return sb_puts(b, "inf", 3) ? -1 : 1;
    /* "snan" rather than "nan" for a signaling NaN, which 5.12.1
     * allows and which is the spelling that raises NOTHING - the
     * alternative it offers, writing "nan" and signaling invalid,
     * would lose the distinction the round trip has to keep. */
    if (sb_puts(b, c->signaling ? "snan" : "nan", c->signaling ? 4 : 3))
        return -1;
    {
        cft_bn pay;
        int top;
        bn_payload(f, x, &pay);
        if (cft_bn_is_zero(&pay))
            return 1;
        if (sb_puts(b, "(0x", 3))
            return -1;
        top = cft_bn_bitlen(&pay);
        for (top = (top + 3) / 4; top-- > 0; ) {
            uint32_t nib = cft_bn_extract(&pay, top * 4, 4);
            if (sb_putc(b, "0123456789abcdef"[nib]))
                return -1;
        }
        if (sb_putc(b, ')'))
            return -1;
    }
    return 1;
}

/* Hand the assembled sequence to the caller. *len is ALWAYS the bytes
 * required including the NUL, so cap = 0 with out = NULL is how a
 * caller asks for the size. */
static cft_status deliver(const sbuf *b, char *out, size_t cap, size_t *len)
{
    if (len)
        *len = b->n + 1;
    if (cap < b->n + 1)
        return CFT_ERR_INVALID_ARGUMENT;
    memcpy(out, b->s, b->n);
    out[b->n] = '\0';
    return CFT_OK;
}

/* ------------------------------------------------------------------
 * convertToDecimalCharacter (5.4.2, 5.12.2)
 * ------------------------------------------------------------------ */

/* Round the exact digit string to h significant digits under `rnd`,
 * in place. Returns the carry into the exponent (0 or 1).
 *
 * The guard/sticky pair is round_pack's, transposed onto a decimal
 * grid: guard is "the dropped tail is at least half an ulp", which is
 * drop >= 5; sticky has to make (guard or sticky) mean "the tail is
 * non-zero" and (guard and sticky) mean "strictly more than half", so
 * it is "the tail is neither exactly zero nor exactly one half". That
 * is what makes "correctly rounded to H digits" mean the same thing
 * here as it does anywhere else in this library. */
static int round_digits(char *d, size_t len, size_t h, int sign, int rnd)
{
    int drop = d[h] - '0', sticky = 0, guard, up, lsb;
    size_t i;
    for (i = h + 1; i < len && !sticky; i++)
        sticky = d[i] != '0';
    guard = drop >= 5;
    sticky = sticky || (drop != 0 && drop != 5);
    lsb = (d[h - 1] - '0') & 1;
    switch (rnd) {
    case CFT_SF_RNE: up = guard && (sticky || lsb); break;
    case CFT_SF_RMM: up = guard; break;
    case CFT_SF_RTZ: up = 0; break;
    case CFT_SF_RDN: up = sign && (guard || sticky); break;
    default:         up = !sign && (guard || sticky); break;   /* RUP */
    }
    if (!up)
        return 0;
    for (i = h; i-- > 0; ) {
        if (d[i] != '9') {
            d[i]++;
            return 0;
        }
        d[i] = '0';
    }
    d[0] = '1';                       /* 999... carried out to 1000... */
    return 1;
}

static cft_status to_decimal_one(const cft_fmt_desc *f, const cft_bn *x,
                                 size_t want, int rnd, sbuf *b,
                                 uint32_t *flags)
{
    lane_cls c;
    cft_bn m;
    nat n5, xm, prod;
    char *digs = NULL;
    size_t dlen = 0, sig, total, i;
    long exp10;
    int e, sp;
    cft_status st;

    *flags = 0;
    cls_of(f, x, &c);
    sp = special_text(f, x, &c, "0", b);
    if (sp)
        return sp < 0 ? CFT_ERR_OUT_OF_MEMORY : CFT_OK;

    bn_sig_exp(f, x, &c, &m, &e);
    nat_init(&n5);
    nat_init(&xm);
    nat_init(&prod);
    st = CFT_ERR_OUT_OF_MEMORY;
    if (nat_from_bn(&xm, &m))
        goto done;
    if (e >= 0) {
        nat t;
        nat_init(&t);
        if (nat_shl(&t, &xm, (size_t)e) || nat_copy(&xm, &t)) {
            nat_free(&t);
            goto done;
        }
        nat_free(&t);
        exp10 = 0;
    } else {
        /* m * 2^e is m * 5^-e * 10^e exactly, so the exact decimal of
         * every binary float terminates - 2^-k = 5^k * 10^-k. */
        if (nat_pow_small(&n5, 5, (uint64_t)(-(int64_t)e)) ||
            nat_mul(&prod, &xm, &n5) || nat_copy(&xm, &prod))
            goto done;
        exp10 = e;
    }
    if (nat_digits(&xm, &digs, &dlen))
        goto done;
    exp10 += (long)dlen - 1;
    sig = dlen;
    while (sig > 1 && digs[sig - 1] == '0')
        sig--;

    if (want && want < sig) {
        exp10 += round_digits(digs, sig, want, c.sign, rnd);
        sig = want;
        /* digs carried no trailing zero, so digs[want..] ended in a
         * non-zero digit: something was dropped, and this is always
         * inexact. */
        *flags = CFT_SF_INEXACT;
    }
    /* `total` digits go out - the exact count in the exact mode, and
     * the caller's H otherwise, trailing zeros included so a caller
     * who asked for H can count H (5.12.2: more than H "shall pad with
     * trailing zeros", and H is unbounded here). */
    total = want ? want : sig;

    if ((c.sign && sb_putc(b, '-')) || sb_putc(b, digs[0]))
        goto done;
    if (total > 1) {
        if (sb_putc(b, '.') || sb_puts(b, digs + 1, sig - 1))
            goto done;
        for (i = sig; i < total; i++)
            if (sb_putc(b, '0'))
                goto done;
    }
    if (sb_putc(b, 'e') || sb_put_exp(b, exp10))
        goto done;
    st = CFT_OK;
done:
    free(digs);
    nat_free(&n5);
    nat_free(&xm);
    nat_free(&prod);
    return st;
}

/* ------------------------------------------------------------------
 * convertToHexCharacter (5.4.3, 5.12.3)
 * ------------------------------------------------------------------ */

static cft_status to_hex_one(const cft_fmt_desc *f, const cft_bn *x, sbuf *b)
{
    lane_cls c;
    cft_bn m;
    int e, sp, len, exp, nib, i;

    cls_of(f, x, &c);
    sp = special_text(f, x, &c, "0x0p+0", b);
    if (sp)
        return sp < 0 ? CFT_ERR_OUT_OF_MEMORY : CFT_OK;

    bn_sig_exp(f, x, &c, &m, &e);
    len = cft_bn_bitlen(&m);
    exp = e + len - 1;
    /* Normalise to a leading 1 so the spelling depends on the VALUE
     * and not on which side of the format's subnormal boundary it
     * sits: the smallest binary32 subnormal is 0x1p-149, not
     * 0x0.000002p-126. */
    cft_bn_clearbit(&m, len - 1);
    nib = (len + 2) / 4;                 /* ceil((len - 1) / 4) */
    if (nib && cft_bn_shl(&m, &m, 4 * nib - (len - 1)))
        return CFT_ERR_INTERNAL;
    while (nib > 0 && cft_bn_extract(&m, 0, 4) == 0) {
        cft_bn_shr(&m, &m, 4);
        nib--;
    }
    if ((c.sign && sb_putc(b, '-')) || sb_puts(b, "0x1", 3))
        return CFT_ERR_OUT_OF_MEMORY;
    if (nib) {
        if (sb_putc(b, '.'))
            return CFT_ERR_OUT_OF_MEMORY;
        for (i = nib; i-- > 0; ) {
            uint32_t v = cft_bn_extract(&m, i * 4, 4);
            if (sb_putc(b, "0123456789abcdef"[v]))
                return CFT_ERR_OUT_OF_MEMORY;
        }
    }
    if (sb_putc(b, 'p') || sb_put_exp(b, exp))
        return CFT_ERR_OUT_OF_MEMORY;
    return CFT_OK;
}

/* ------------------------------------------------------------------
 * The entry points
 * ------------------------------------------------------------------ */

CFT_API size_t cft_format_decimal_digits(cft_format fmt)
{
    const cft_fmt_desc *f;
    nat ten, two;
    size_t k = 0;
    if ((int)fmt < 0 || (int)fmt > 3)
        return 0;
    f = &cft_sf_formats[(int)fmt];
    /* 1 + ceiling(p * log10(2)), derived: ceiling(p * log10 2) is the
     * smallest k with 10^k >= 2^p, which is an exact integer question
     * and needs no table to go stale. */
    nat_init(&ten);
    nat_init(&two);
    if (nat_set_u32(&ten, 1) || nat_set_u32(&two, 1)) {
        nat_free(&ten);
        nat_free(&two);
        return 0;
    }
    {
        nat t;
        nat_init(&t);
        if (nat_shl(&t, &two, (size_t)f->prec) || nat_copy(&two, &t)) {
            nat_free(&t);
            nat_free(&ten);
            nat_free(&two);
            return 0;
        }
        nat_free(&t);
    }
    while (nat_cmp(&ten, &two) < 0) {
        if (nat_muladd_small(&ten, 10, 0)) {
            k = 0;
            break;
        }
        k++;
    }
    nat_free(&ten);
    nat_free(&two);
    return k ? k + 1 : 0;
}

static cft_status from_char_batch(cft_device *dev, cft_format fmt,
                                  cft_round rnd, const char *const *in,
                                  void *d, size_t n, size_t *bad_index,
                                  uint32_t *flags_out, int hex)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;

    if (bad_index)
        *bad_index = 0;
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3 || !rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (!in || !d)
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        cft_bn v;
        uint32_t fl = 0;
        cft_status st = hex ? from_hex_one(f, in[i], (int)rnd, &v, &fl)
                            : from_decimal_one(f, in[i], (int)rnd, &v, &fl);
        if (st != CFT_OK) {
            if (bad_index)
                *bad_index = i;
            return st;
        }
        acc |= fl;
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_from_decimal_char(cft_device *dev, cft_format fmt,
                                         cft_round rnd,
                                         const char *const *in, void *d,
                                         size_t n, size_t *bad_index,
                                         uint32_t *flags_out)
{
    return from_char_batch(dev, fmt, rnd, in, d, n, bad_index, flags_out, 0);
}

CFT_API cft_status cft_from_hex_char(cft_device *dev, cft_format fmt,
                                     cft_round rnd, const char *const *in,
                                     void *d, size_t n, size_t *bad_index,
                                     uint32_t *flags_out)
{
    return from_char_batch(dev, fmt, rnd, in, d, n, bad_index, flags_out, 1);
}

CFT_API cft_status cft_to_decimal_char(cft_device *dev, cft_format fmt,
                                       cft_round rnd, const void *a,
                                       size_t digits, char *out, size_t cap,
                                       size_t *len, uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    cft_bn x;
    sbuf b;
    uint32_t fl = 0;
    cft_status st;

    if (len)
        *len = 0;
    cft_flags_emit(dev, 0, flags_out);
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The attribute is range-checked even in the exact mode, where it
     * is not consumed: one entry point that sometimes reads `rnd` and
     * sometimes does not is exactly where an out-of-range value would
     * hide until the day a caller asked for digits. */
    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    if (!a || (cap && !out))
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    cft_bn_load(&x, (const uint8_t *)a, f->width / 8);

    sb_init(&b);
    st = to_decimal_one(f, &x, digits, (int)rnd, &b, &fl);
    if (st == CFT_OK) {
        st = deliver(&b, out, cap, len);
        if (st == CFT_OK)
            cft_flags_emit(dev, fl, flags_out);
    }
    sb_free(&b);
    return st;
}

CFT_API cft_status cft_to_hex_char(cft_device *dev, cft_format fmt,
                                   const void *a, char *out, size_t cap,
                                   size_t *len)
{
    const cft_fmt_desc *f;
    cft_bn x;
    sbuf b;
    cft_status st;

    if (len)
        *len = 0;
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!a || (cap && !out))
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    cft_bn_load(&x, (const uint8_t *)a, f->width / 8);

    sb_init(&b);
    st = to_hex_one(f, &x, &b);
    if (st == CFT_OK)
        st = deliver(&b, out, cap, len);
    sb_free(&b);
    return st;
}

/* ------------------------------------------------------------------
 * The 9.7 NaN payload operations
 *
 * ENCODING operations, and they say so here for the same reason the
 * conversions above do: docs/DETERMINISM.md's canonical-NaN rule is
 * about ARITHMETIC, where the divergence between implementations is
 * over which operand's payload survives an operation. Reading a
 * payload out of an encoding and writing one into it is not
 * arithmetic, and 9.7 says these "signal no exceptions" - so there is
 * no flags argument on any of the three, and a signaling NaN operand
 * raises nothing.
 * ------------------------------------------------------------------ */

static cft_status payload_validate(cft_device *dev, cft_format fmt,
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
    if (size_overflows(&cft_sf_formats[(int)fmt], n))
        return CFT_ERR_INVALID_ARGUMENT;
    return CFT_OK;
}

CFT_API cft_status cft_get_payload(cft_device *dev, cft_format fmt,
                                   const void *a, void *d, size_t n)
{
    const cft_fmt_desc *f;
    size_t i;
    cft_status st = payload_validate(dev, fmt, a, d, n);
    if (st != CFT_OK || n == 0)
        return st;
    f = &cft_sf_formats[(int)fmt];
    for (i = 0; i < n; i++) {
        lane_cls c;
        cft_bn xa, pay, v;
        uint32_t fl = 0;
        lane_load(f, (const uint8_t *)a, i, &xa);
        cls_of(f, &xa, &c);
        if (c.kind != K_NAN) {
            /* 9.7: "If the source operand is not a NaN, the result is
             * -1." Signaling and quiet NaNs both answer with their
             * payload; nothing here signals. */
            cft_bn_zero(&v);
            {
                int k;
                for (k = 0; k < f->exp_w; k++)
                    if ((((uint32_t)f->bias) >> k) & 1u)
                        cft_bn_setbit(&v, f->man_w + k);
            }
            cft_bn_setbit(&v, f->width - 1);
        } else {
            bn_payload(f, &xa, &pay);
            if (cft_bn_is_zero(&pay)) {
                cft_sf_zero(f, 0, &v);
            } else if (cft_sf_round_pack(f, 0, &pay, 0, 0, CFT_SF_RNE, &v,
                                         &fl) || fl != 0) {
                /* A payload is below 2^(man_w - 1) < 2^p, so it is a
                 * representable integer at every rung and this can
                 * only fire if that stops being true. */
                return CFT_ERR_INTERNAL;
            }
        }
        lane_store(f, (uint8_t *)d, i, &v);
    }
    return CFT_OK;
}

/* 9.7's admissible-payload test. Returns 1 with `out` set, or 0.
 *
 * The set is exactly what the format's payload field holds,
 * 0 .. 2^(man_w-1) - 1. The test is on the VALUE, so -0 passes it as
 * the integer zero: 754 settles that -0 equals 0, and every other
 * value-based operation in this contract reads it the same way. */
static int payload_operand(const cft_fmt_desc *f, const cft_bn *x,
                           cft_bn *out)
{
    lane_cls c;
    cft_bn m;
    int e, len;
    cls_of(f, x, &c);
    if (c.kind == K_ZERO) {
        cft_bn_zero(out);
        return 1;
    }
    if ((c.kind != K_NORM && c.kind != K_SUB) || c.sign)
        return 0;
    bn_sig_exp(f, x, &c, &m, &e);
    len = cft_bn_bitlen(&m);
    if (e < 0) {
        if (-e >= len || cft_bn_low_nonzero(&m, -e))
            return 0;                    /* not an integer */
        cft_bn_shr(out, &m, -e);
    } else {
        if (len + e > f->man_w - 1)
            return 0;                    /* at or above 2^(man_w - 1) */
        if (cft_bn_shl(out, &m, e))
            return 0;
    }
    return cft_bn_bitlen(out) <= f->man_w - 1;
}

static cft_status set_payload_core(cft_device *dev, cft_format fmt,
                                   const void *a, void *d, size_t n,
                                   int signaling)
{
    const cft_fmt_desc *f;
    size_t i;
    cft_status st = payload_validate(dev, fmt, a, d, n);
    if (st != CFT_OK || n == 0)
        return st;
    f = &cft_sf_formats[(int)fmt];
    for (i = 0; i < n; i++) {
        cft_bn xa, pay, v;
        lane_load(f, (const uint8_t *)a, i, &xa);
        if (!payload_operand(f, &xa, &pay) ||
            (signaling && cft_bn_is_zero(&pay)))
            cft_sf_zero(f, 0, &v);       /* 9.7: "the result is +0" */
        else
            bn_nan_with(f, 0, &pay, signaling, &v);
        lane_store(f, (uint8_t *)d, i, &v);
    }
    return CFT_OK;
}

CFT_API cft_status cft_set_payload(cft_device *dev, cft_format fmt,
                                   const void *a, void *d, size_t n)
{
    return set_payload_core(dev, fmt, a, d, n, 0);
}

CFT_API cft_status cft_set_payload_signaling(cft_device *dev, cft_format fmt,
                                             const void *a, void *d, size_t n)
{
    return set_payload_core(dev, fmt, a, d, n, 1);
}
