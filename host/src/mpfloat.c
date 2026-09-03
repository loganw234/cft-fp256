/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The multiprecision floating-point evaluator. See mpfloat.h for why
 * it is floating rather than fixed point, and for the error contract.
 *
 * ---------------------------------------------------------------
 * The error bounds, derived
 * ---------------------------------------------------------------
 *
 * `err` counts units of 2^-W of RELATIVE error:
 *
 *     |true - value| <= err * 2^-W * |value|
 *
 * Relative rather than absolute-in-ulps for one reason, and it is the
 * difference between a usable evaluator and a useless one: relative
 * error is ADDITIVE through multiplication and division, where an
 * ulp count is not. A significand sitting just above 2^(W-1) has ulps
 * twice as coarse, relatively, as one sitting just below 2^W, so a
 * bound expressed in ulps has to be multiplied by two at every
 * multiply to stay safe - and 2^170 over a series is not a bound, it
 * is a surrender. In relative terms the same step costs an addition.
 *
 * The rules, each an upper bound and each rounded up:
 *
 *   truncation   The significand is truncated toward zero to W bits.
 *                One unit in its last place is 2^exp and the value is
 *                at least 2^(W-1+exp), so the truncation is at most
 *                2 * 2^-W relatively.                          +2
 *
 *   mul          Relative errors add: (1+ea)(1+eb) = 1 + ea + eb +
 *                ea*eb. The cross term is below 2^-W as long as
 *                Ea*Eb < 2^W, which the saturation at 2^40 and the
 *                minimum W of 88 guarantee.           Ea + Eb + 3
 *
 *   div          The same, with (1+ea)/(1+eb) = 1 + ea - eb + O(eb^2)
 *                and eb below 1/2 throughout.          Ea + Eb + 3
 *
 *   add, like signs
 *                |a+b| >= max(|a|,|b|), so each term's absolute error
 *                is at most its own relative error times |a+b|.
 *                                                      Ea + Eb + 2
 *
 *   add, unlike signs (cancellation)
 *                The absolute errors survive and the result shrank.
 *                With value exponents va = ea + W and vb = eb + W and
 *                the result's vr, the amplification is 2^(va - vr) and
 *                2^(vb - vr) respectively:
 *                        2*(Ea << (ea-er)) + 2*(Eb << (eb-er)) + 2
 *                which is where a subtraction that loses k bits costs
 *                k bits of the error budget. This is the term the
 *                algorithms in transcend.c are shaped to keep small.
 *
 *   sqrt         sqrt(1+e) = 1 + e/2 + O(e^2).      ceil(Ea/2) + 2
 *
 *   scale by 2^k Exact.                                        +0
 *
 * All of it is saturating upward at CFT_MP_ERR_MAX, which is not a
 * failure: a saturated bound simply cannot decide a rounding, so the
 * Ziv loop raises the working precision and tries again. The one thing
 * that would be a failure is a bound that is too small, which is why
 * every rule above rounds up and why none of them is an estimate.
 */

#include <string.h>

#include "mpfloat.h"
#include "mp_consts.h"

/* ---- saturating error arithmetic --------------------------------- */

static uint64_t err_add(uint64_t a, uint64_t b)
{
    uint64_t s = a + b;
    if (s < a || s > CFT_MP_ERR_MAX)
        return CFT_MP_ERR_MAX;
    return s;
}

static uint64_t err_shl(uint64_t a, int k)
{
    if (a == 0)
        return 0;
    if (k < 0)
        return a >> (-k > 63 ? 63 : -k);
    if (k >= 63 || a > (CFT_MP_ERR_MAX >> k))
        return CFT_MP_ERR_MAX;
    return a << k;
}

/* ---- normalisation ------------------------------------------------ *
 *
 * Bring (sign, m, e) to exactly W significand bits. `err_in` is the
 * incoming relative error in units of 2^-W; a right shift truncates
 * and costs two more units, a left shift is exact.
 */
static int mp_norm(cft_mp *r, int W, int sign, const cft_bn *m, long e,
                   uint64_t err_in)
{
    int L = cft_bn_bitlen(m);
    if (L == 0) {
        cft_mp_set_zero(r);
        return 0;
    }
    r->sign = sign ? 1 : 0;
    r->zero = 0;
    if (L > W) {
        cft_bn_shr(&r->m, m, L - W);
        r->exp = e + (L - W);
        r->err = err_add(err_in, 2);
    } else {
        if (cft_bn_shl(&r->m, m, W - L))
            return 1;
        r->exp = e - (W - L);
        r->err = err_in;
    }
    return 0;
}

void cft_mp_set_zero(cft_mp *r)
{
    r->sign = 0;
    r->zero = 1;
    r->exp = 0;
    r->err = 0;
    cft_bn_zero(&r->m);
}

int cft_mp_set_bn(cft_mp *r, int W, int sign, const cft_bn *m, long e)
{
    return mp_norm(r, W, sign, m, e, 0);
}

int cft_mp_set_ui(cft_mp *r, int W, int sign, uint32_t v, long e)
{
    cft_bn t;
    cft_bn_zero(&t);
    cft_bn_set_u32(&t, v);
    return mp_norm(r, W, sign, &t, e, 0);
}

void cft_mp_copy(cft_mp *r, const cft_mp *a)
{
    if (r == a)
        return;
    r->sign = a->sign;
    r->zero = a->zero;
    r->exp = a->exp;
    r->err = a->err;
    cft_bn_copy(&r->m, &a->m);
}

void cft_mp_neg(cft_mp *r)
{
    if (!r->zero)
        r->sign ^= 1;
}

void cft_mp_shift(cft_mp *r, long k)
{
    if (!r->zero)
        r->exp += k;
}

long cft_mp_exp2_of(const cft_mp *a)
{
    return a->exp + cft_bn_bitlen(&a->m) - 1;
}

/* ---- multiply ----------------------------------------------------- */

int cft_mp_mul(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn p;
    if (a->zero || b->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    if (cft_bn_mul(&p, &a->m, &b->m))
        return 1;
    return mp_norm(r, W, a->sign ^ b->sign, &p, a->exp + b->exp,
                   err_add(err_add(a->err, b->err), 1));
}

int cft_mp_mul_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W)
{
    cft_bn f, p;
    if (a->zero || u == 0) {
        cft_mp_set_zero(r);
        return 0;
    }
    cft_bn_zero(&f);
    cft_bn_set_u32(&f, u);
    if (cft_bn_mul(&p, &a->m, &f))
        return 1;
    return mp_norm(r, W, a->sign, &p, a->exp, a->err);
}

/* ---- add and subtract --------------------------------------------- */

/* The alignment is bounded exactly as sf_fma bounds it: past W + 2
 * places the smaller term lies entirely below the larger's last bit
 * and can only ever perturb it by less than one unit, which the two
 * units charged for truncation already cover. */
int cft_mp_add(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn ma, mb, s;
    long ea, eb, e0;
    uint64_t erra, errb, err_out;
    int sa, sb, cmp, sign;

    if (a->zero) { cft_mp_copy(r, b); return 0; }
    if (b->zero) { cft_mp_copy(r, a); return 0; }

    ea = a->exp; eb = b->exp;
    sa = a->sign; sb = b->sign;
    erra = a->err; errb = b->err;

    if (ea - eb > W + 2) {
        cft_mp_copy(r, a);
        r->err = err_add(erra, 2);
        return 0;
    }
    if (eb - ea > W + 2) {
        cft_mp_copy(r, b);
        r->err = err_add(errb, 2);
        return 0;
    }

    e0 = ea < eb ? ea : eb;
    if (cft_bn_shl(&ma, &a->m, (int)(ea - e0)))
        return 1;
    if (cft_bn_shl(&mb, &b->m, (int)(eb - e0)))
        return 1;

    if (sa == sb) {
        if (cft_bn_add(&s, &ma, &mb))
            return 1;
        sign = sa;
        err_out = err_add(erra, errb);
    } else {
        cmp = cft_bn_cmp(&ma, &mb);
        if (cmp == 0) {
            cft_mp_set_zero(r);
            return 0;
        }
        if (cmp > 0) {
            cft_bn_sub(&s, &ma, &mb);
            sign = sa;
        } else {
            cft_bn_sub(&s, &mb, &ma);
            sign = sb;
        }
        /* Cancellation: the amplification is the drop from each
         * operand's value exponent to the result's, and it is applied
         * before the result is renormalised, in units of 2^-W. */
        {
            int lr = cft_bn_bitlen(&s);
            int la = cft_bn_bitlen(&ma);
            int lb = cft_bn_bitlen(&mb);
            err_out = err_add(err_shl(erra, la - lr + 1),
                              err_shl(errb, lb - lr + 1));
        }
    }
    return mp_norm(r, W, sign, &s, e0, err_out);
}

int cft_mp_sub(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_mp nb;
    cft_mp_copy(&nb, b);
    cft_mp_neg(&nb);
    return cft_mp_add(r, a, &nb, W);
}

/* ---- divide -------------------------------------------------------- *
 *
 * Schoolbook binary long division, not a Newton reciprocal, and the
 * reason is the error contract: a floor division with a remainder is
 * exact to within one unit in the last place BY CONSTRUCTION, where a
 * Newton iteration's accuracy has to be argued or measured. bigint.h
 * deliberately carries no division; this is the one place the library
 * needs one, it needs it once per logarithm, and W iterations of
 * shift-compare-subtract cost about the same as sixty multiplies.
 */
static int bn_divmod(cft_bn *q, const cft_bn *num, const cft_bn *den)
{
    cft_bn rem;
    int i, nb = cft_bn_bitlen(num);
    if (cft_bn_is_zero(den))
        return 1;
    cft_bn_zero(q);
    cft_bn_zero(&rem);
    for (i = nb - 1; i >= 0; i--) {
        if (cft_bn_shl(&rem, &rem, 1))
            return 1;
        if (cft_bn_bit(num, i))
            cft_bn_setbit(&rem, 0);
        if (cft_bn_shl(q, q, 1))
            return 1;
        if (cft_bn_cmp(&rem, den) >= 0) {
            cft_bn_sub(&rem, &rem, den);
            cft_bn_setbit(q, 0);
        }
    }
    return 0;
}

int cft_mp_div(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn num, q;
    if (b->zero)
        return 1;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    if (cft_bn_shl(&num, &a->m, W + 1))
        return 1;
    if (bn_divmod(&q, &num, &b->m))
        return 1;
    return mp_norm(r, W, a->sign ^ b->sign, &q,
                   a->exp - b->exp - (W + 1),
                   err_add(err_add(a->err, b->err), 1));
}

int cft_mp_div_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W)
{
    cft_bn num, den, q;
    if (u == 0)
        return 1;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    cft_bn_zero(&den);
    cft_bn_set_u32(&den, u);
    /* Two extra bits so the quotient still has at least W of them
     * before renormalisation; the divisor is a small integer, so the
     * numerator stays inside the container. */
    if (cft_bn_shl(&num, &a->m, 34))
        return 1;
    if (bn_divmod(&q, &num, &den))
        return 1;
    return mp_norm(r, W, a->sign, &q, a->exp - 34, a->err);
}

/* ---- square root --------------------------------------------------- *
 *
 * Digit-by-digit integer square root, for the same reason division is
 * schoolbook: floor(sqrt(N)) with a remainder is exact to within one
 * unit in the last place without an argument. */
static int bn_isqrt(cft_bn *root, const cft_bn *n)
{
    cft_bn rem, trial;
    int i, nb = cft_bn_bitlen(n);
    if (nb & 1)
        nb++;
    cft_bn_zero(root);
    cft_bn_zero(&rem);
    for (i = nb - 2; i >= 0; i -= 2) {
        if (cft_bn_shl(&rem, &rem, 2))
            return 1;
        if (cft_bn_bit(n, i + 1))
            cft_bn_setbit(&rem, 1);
        if (cft_bn_bit(n, i))
            cft_bn_setbit(&rem, 0);
        /* The trial subtrahend is 4R + 1, not 2R + 1: appending a
         * digit d takes the root from R to 2R+d, and (2R+1)^2 -
         * (2R)^2 is 4R + 1. */
        if (cft_bn_shl(&trial, root, 2))
            return 1;
        cft_bn_setbit(&trial, 0);
        if (cft_bn_shl(root, root, 1))
            return 1;
        if (cft_bn_cmp(&rem, &trial) >= 0) {
            cft_bn_sub(&rem, &rem, &trial);
            cft_bn_setbit(root, 0);
        }
    }
    return 0;
}

int cft_mp_isqrt(cft_bn *root, int *exact, const cft_bn *n)
{
    cft_bn sq;
    if (bn_isqrt(root, n))
        return 1;
    if (cft_bn_mul(&sq, root, root))
        return 1;
    *exact = (cft_bn_cmp(&sq, n) == 0);
    return 0;
}

int cft_mp_sqrt(cft_mp *r, const cft_mp *a, int W)
{
    cft_bn n, root;
    long e;
    int L, k;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    if (a->sign)
        return 1;
    L = cft_bn_bitlen(&a->m);
    k = 2 * W - L;                 /* land the significand on 2W bits */
    e = a->exp - k;
    if (e & 1) {                   /* the exponent must be even to halve */
        k--;
        e++;
    }
    if (k < 0 || cft_bn_shl(&n, &a->m, k))
        return 1;
    if (bn_isqrt(&root, &n))
        return 1;
    return mp_norm(r, W, 0, &root, e / 2, (a->err + 1) / 2);
}

/* The integer part of the value, truncated toward zero and saturated.
 * Only the exponential's argument reduction uses it, and there an
 * off-by-one merely widens the reduced argument from ln2/2 to ln2 -
 * which the series still carries - so truncation is enough and no
 * rounding rule is needed. */
int64_t cft_mp_trunc_to_int(const cft_mp *a)
{
    const int64_t CAP = (int64_t)1 << 40;
    cft_bn t;
    int64_t v = 0;
    long sh;
    int i;

    if (a->zero)
        return 0;
    if (cft_mp_exp2_of(a) > 40)
        return a->sign ? -CAP : CAP;
    if (cft_mp_exp2_of(a) < 0)
        return 0;
    sh = -a->exp;
    if (sh < 0)
        return a->sign ? -CAP : CAP;
    cft_bn_shr(&t, &a->m, (int)sh);
    for (i = t.n - 1; i >= 0; i--)
        v = (v << 32) | (int64_t)t.v[i];
    if (v > CAP)
        v = CAP;
    return a->sign ? -v : v;
}

/* ---- generated constants ------------------------------------------- */

int cft_mp_const(cft_mp *r, cft_mp_constant which, int W)
{
    const uint32_t *limbs;
    long e;
    cft_bn v;
    int i;

    switch (which) {
    case CFT_MP_C_LN2:    limbs = cft_mp_ln2_limbs;    e = CFT_MP_LN2_EXP; break;
    case CFT_MP_C_LOG2E:  limbs = cft_mp_log2e_limbs;  e = CFT_MP_LOG2E_EXP; break;
    case CFT_MP_C_LN10:   limbs = cft_mp_ln10_limbs;   e = CFT_MP_LN10_EXP; break;
    case CFT_MP_C_LOG10E: limbs = cft_mp_log10e_limbs; e = CFT_MP_LOG10E_EXP; break;
    default: return 1;
    }
    if (W > CFT_MP_CONST_BITS)
        return 1;
    cft_bn_zero(&v);
    for (i = 0; i < CFT_MP_CONST_LIMBS; i++)
        v.v[i] = limbs[i];
    v.n = CFT_MP_CONST_LIMBS;
    while (v.n > 0 && v.v[v.n - 1] == 0)
        v.n--;
    if (cft_bn_bitlen(&v) != CFT_MP_CONST_BITS)
        return 1;                 /* a truncated or corrupted header */
    /* The stored value is the true one truncated toward zero at 1088
     * bits, so it is already low by up to one unit there; truncating
     * further to W costs the two units mp_norm charges. */
    return mp_norm(r, W, 0, &v, e, 1);
}

int cft_mp_consts_selfcheck(void)
{
    static const struct { cft_mp_constant a, b; } pairs[2] = {
        { CFT_MP_C_LN2, CFT_MP_C_LOG2E },
        { CFT_MP_C_LN10, CFT_MP_C_LOG10E },
    };
    const int W = 256;
    int i;
    for (i = 0; i < 2; i++) {
        cft_mp x, y, p, one, d;
        if (cft_mp_const(&x, pairs[i].a, W) ||
            cft_mp_const(&y, pairs[i].b, W))
            return 1;
        if (cft_mp_mul(&p, &x, &y, W))
            return 1;
        if (cft_mp_set_ui(&one, W, 0, 1, 0))
            return 1;
        if (cft_mp_sub(&d, &p, &one, W))
            return 1;
        /* The product of two W-bit truncations differs from 1 by at
         * most a handful of units in the last place; a wrong constant
         * differs by vastly more. 2^-(W-8) is far outside the former
         * and far inside the latter. */
        if (!d.zero && cft_mp_exp2_of(&d) > -(W - 8))
            return 1;
    }
    return 0;
}

/* ---- the rounding decision ----------------------------------------- */

/* Compare the whole enclosure [value - err*ulp, value + err*ulp]
 * against an integer, exactly. The screens in transcend.c ask only
 * "is this provably past the threshold", so an inconclusive answer is
 * always safe: it falls through to the ordinary path.
 *
 * cmp_mag compares m * 2^e against the non-negative integer t without
 * materialising either side at full width - a value exponent above 63
 * settles it, and so does one below zero. */
static int cmp_mag(const cft_bn *m, long e, uint64_t t)
{
    cft_bn tb, x;
    int i;
    if (cft_bn_is_zero(m))
        return t == 0 ? 0 : -1;
    if (t == 0)
        return 1;
    if (e + cft_bn_bitlen(m) > 80)
        return 1;                      /* > 2^79, far above any t */
    cft_bn_zero(&tb);
    for (i = 0; i < 2; i++)
        tb.v[i] = (uint32_t)(t >> (32 * i));
    tb.n = tb.v[1] ? 2 : (tb.v[0] ? 1 : 0);
    if (e >= 0) {
        if (cft_bn_shl(&x, m, (int)e))
            return 1;
        return cft_bn_cmp(&x, &tb);
    }
    if (-e > CFT_BN_BITS - 96)
        return -1;                     /* below 1, and t >= 1 */
    if (cft_bn_shl(&x, &tb, (int)(-e)))
        return -1;
    return cft_bn_cmp(m, &x);
}

/* The enclosure's two ends, as (significand, exponent) pairs. */
static void enclosure(const cft_mp *a, cft_bn *lo, cft_bn *hi, int *ok)
{
    cft_bn e;
    *ok = 0;
    /* The bound is a full 64-bit count, not a limb: a series that has
     * been through an argument reduction and five squarings carries
     * tens of billions of units and is STILL far inside the working
     * precision. Capping this at 2^32 turned a decidable pow into
     * CFT_ERR_INTERNAL. */
    cft_bn_zero(&e);
    e.v[0] = (uint32_t)a->err;
    e.v[1] = (uint32_t)(a->err >> 32);
    e.n = e.v[1] ? 2 : (e.v[0] ? 1 : 0);
    if (cft_bn_cmp(&a->m, &e) <= 0)
        return;                        /* the enclosure reaches zero */
    cft_bn_sub(lo, &a->m, &e);
    if (cft_bn_add(hi, &a->m, &e))
        return;
    *ok = 1;
}

/* The comparison of one signed (m, exp) endpoint against t. */
static int cmp_signed(int sign, const cft_bn *m, long e, int64_t t)
{
    uint64_t mag;
    int c;
    if (cft_bn_is_zero(m))
        return t == 0 ? 0 : (t < 0 ? 1 : -1);
    if (!sign) {
        if (t < 0)
            return 1;
        return cmp_mag(m, e, (uint64_t)t);
    }
    if (t >= 0)
        return -1;
    mag = (uint64_t)(-(t + 1)) + 1u;
    c = cmp_mag(m, e, mag);
    return -c;
}

int cft_mp_cmp_int(const cft_mp *a, int64_t t)
{
    cft_bn lo, hi;
    int ok;
    if (a->zero)
        return t == 0 ? 0 : (t < 0 ? 1 : -1);
    enclosure(a, &lo, &hi, &ok);
    if (!ok)
        return 0;                      /* too wide to decide: fall through */
    if (a->sign) {
        /* the enclosure of the VALUE runs from -(hi) up to -(lo) */
        if (cmp_signed(1, &hi, a->exp, t) > 0)
            return 1;
        if (cmp_signed(1, &lo, a->exp, t) < 0)
            return -1;
        return 0;
    }
    if (cmp_signed(0, &lo, a->exp, t) > 0)
        return 1;
    if (cmp_signed(0, &hi, a->exp, t) < 0)
        return -1;
    return 0;
}

int cft_mp_round(const cft_mp *a, int sign, const cft_fmt_desc *f, int rnd,
                 cft_bn *out, uint32_t *flags, int *decided)
{
    cft_bn lo, hi;
    cft_bn blo, bhi;
    uint32_t flo = 0, fhi = 0;
    int ok;

    *decided = 0;
    if (a->zero)
        return 1;                 /* the callers never round an exact 0 */
    if (a->exp > (1 << 24) || a->exp < -(1 << 24))
        return 1;                 /* the screens keep this unreachable */

    enclosure(a, &lo, &hi, &ok);
    if (!ok)
        return 0;                 /* too wide to decide: escalate */

    if (cft_sf_round_pack(f, sign, &lo, (int)a->exp, 0, rnd, &blo, &flo))
        return 1;
    if (cft_sf_round_pack(f, sign, &hi, (int)a->exp, 0, rnd, &bhi, &fhi))
        return 1;
    if (cft_bn_cmp(&blo, &bhi) != 0 || flo != fhi)
        return 0;

    cft_bn_copy(out, &blo);
    *flags = flo | CFT_SF_INEXACT;
    *decided = 1;
    return 0;
}
