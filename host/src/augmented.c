/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The augmented arithmetic operations, IEEE 754-2019 clause 9.5:
 * augmentedAddition, augmentedSubtraction, augmentedMultiplication.
 *
 * python/cft_golden/augmented.py defines every result here; this is its
 * port, and "port" means the same thing it means in softfloat.c - the
 * control flow, the order of the special cases and the names are
 * deliberately the same, so the two read side by side and a divergence
 * shows up as a structural difference rather than a subtle one.
 *
 * HOST operations, like most of the clause-5 set: there is no
 * floating-point pass to issue. The rounding is 9.5's own
 * roundTiesTowardZero, which the tile's five attributes do not include,
 * so a device pass could not produce r even if one were free; what runs
 * is exact integer arithmetic through the library's ONE round_pack,
 * extended with that sixth direction (CFT_SF_RTTZ).
 *
 * THE ONE PLACE THIS IS NOT A TRANSLITERATION OF THE MODEL
 *
 * The model forms the exact sum by shifting both operands to a common
 * exponent in unbounded Python integers. For fp256 that alignment spans
 * the whole exponent range - the largest finite against the smallest
 * subnormal is about 524,500 bits - which the 2048-bit bigint core does
 * not hold and should not have to. So the alignment is bounded, by the
 * same FAR/NEAR argument softfloat.c's FMA uses, and the bound is
 * exact rather than sticky-approximated because 9.5 needs the residual
 * itself:
 *
 *   Let VEx and VEy be the operands' value exponents (position of the
 *   leading bit) with |x| >= |y|, both finite and non-zero, and
 *
 *       FAR:  VEx - VEy >= p + 2
 *
 *   Then |y| < 2^(VEy+1) <= 2^(VEx-p-1). The smallest gap anywhere
 *   beside x is 2^(VEx-p) (the binade below x, when x is a power of
 *   two), so |y| is strictly under HALF of the nearest gap in either
 *   direction: x + y is nearer to x than to any other representable
 *   value, and not a tie. Therefore r = x exactly and e = y exactly,
 *   with no arithmetic at all - which is also why the FAR case cannot
 *   overflow (|x + y| < maxfinite + ulp/4) and why its only possible
 *   flag is the underflow a subnormal y earns.
 *
 *   x cannot be subnormal in the FAR case: VEx <= emin - 1 would force
 *   VEy <= emin - p - 3, below the smallest subnormal, so y would be
 *   zero.
 *
 *   NEAR (VEx - VEy <= p + 1) is computed exactly, as the model does.
 *   The common exponent is min(ex, ey) >= VEy - (p-1) >= VEx - 2p, and
 *   the sum's magnitude is under 2^(VEx+1), so the widest intermediate
 *   is 2p + 1 bits - 475 at fp256, well inside the core.
 *
 * The product needs no such split: the exact product of two p-bit
 * significands is 2p bits by construction. Its RESIDUAL, though, is
 * differenced against r at the finer of the two grids, and when r is
 * subnormal that grid can be far below r's own. The shift is still
 * bounded - a non-zero r puts the exact value within half an ulp of it,
 * which pins the product's exponent to within 2p of r's - and every
 * shift here is checked, so a violated bound would return
 * CFT_ERR_INTERNAL rather than a wrong answer.
 *
 * host/tests/augmented_check.py drives both implementations over the
 * operand families that probe these boundaries, and the published
 * <fmt>-augmented.jsonl sets replay this one.
 */

#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

/* ---- lane accessors and classification (clause5.c's, restated) ---- */

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

#define K_ZERO 0
#define K_SUB  1
#define K_NORM 2
#define K_INF  3
#define K_NAN  4

typedef struct {
    int kind;
    int sign;
    int signaling;
    uint32_t ef;
} lane_cls;

static void cls_of(const cft_fmt_desc *f, const cft_bn *x, lane_cls *c)
{
    cft_bn frac;
    c->sign = cft_bn_bit(x, f->width - 1);
    c->ef = cft_bn_extract(x, f->man_w, f->exp_w);
    c->signaling = 0;
    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (c->ef == f->exp_mask) {
        if (cft_bn_is_zero(&frac)) {
            c->kind = K_INF;
        } else {
            c->kind = K_NAN;
            c->signaling = !cft_bn_bit(x, f->man_w - 1);
        }
        return;
    }
    if (c->ef == 0) {
        c->kind = cft_bn_is_zero(&frac) ? K_ZERO : K_SUB;
        return;
    }
    c->kind = K_NORM;
}

/* The significand-and-exponent view of a finite non-zero lane: the
 * value is (-1)^sign * m * 2^e with m the integer significand. */
static void bn_sig_exp(const cft_fmt_desc *f, const cft_bn *x,
                       const lane_cls *c, cft_bn *m, int *e)
{
    cft_bn_copy(m, x);
    cft_bn_mask(m, f->man_w);
    if (c->kind == K_NORM) {
        cft_bn_setbit(m, f->man_w);
        *e = (int)c->ef - f->bias - f->man_w;
    } else {
        *e = f->emin - f->man_w;
    }
}

/* ---- the pair, from an exact non-zero (-1)^sign * t * 2^e0 -------- *
 *
 * `is_mul` selects the one behaviour that differs between the
 * operations: whether a residual the format cannot hold is a defined
 * delivery (multiplication, 9.5's own carve-out) or an impossibility
 * (addition, where reaching it means the representability argument in
 * this file's banner is wrong - so it returns an error rather than a
 * plausible number).
 */
static int aug_pair(const cft_fmt_desc *f, int sign_t, const cft_bn *t,
                    int e0, int is_mul, cft_bn *vr, cft_bn *ve,
                    uint32_t *acc)
{
    cft_bn r, T, R, Rs, mag;
    lane_cls kr;
    int re, q, cmp, sign_e, tiny;
    uint32_t rfl = 0, efl = 0;

    if (cft_sf_round_pack(f, sign_t, t, e0, 0, CFT_SF_RTTZ, &r, &rfl))
        return 1;

    if (rfl & CFT_SF_OVERFLOW) {
        /* "If roundTiesTowardZero(x + y) is infinite, both produced
         * results are the result of roundTiesTowardZero(x + y)", and
         * an overflow signals overflow and inexact per 7.4 - the only
         * route by which these operations report inexact for r. */
        cft_sf_inf(f, sign_t, vr);
        cft_bn_copy(ve, vr);
        *acc |= CFT_SF_OVERFLOW | CFT_SF_INEXACT;
        return 0;
    }
    cft_bn_copy(vr, &r);

    /* e = (x op y) - r, exactly. Both are dyadic rationals; put them on
     * the finer of the two grids and subtract as integers. r carries
     * sign_t (round_pack packs with the sign it was given), so the
     * subtraction is one magnitude comparison rather than a signed add. */
    cls_of(f, &r, &kr);
    if (kr.kind == K_ZERO) {
        cft_bn_zero(&R);
        re = e0;
    } else {
        bn_sig_exp(f, &r, &kr, &R, &re);
    }
    q = e0 < re ? e0 : re;
    if (cft_bn_shl(&T, t, e0 - q))
        return 1;
    if (cft_bn_shl(&Rs, &R, re - q))
        return 1;

    cmp = cft_bn_cmp(&T, &Rs);
    if (cmp == 0) {
        /* "where if x + y - roundTiesTowardZero(x + y) equals zero, it
         * is returned with the sign of roundTiesTowardZero(x + y)" */
        cft_sf_zero(f, kr.sign, ve);
        return 0;
    }
    if (cmp > 0) {
        cft_bn_sub(&mag, &T, &Rs);
        sign_e = sign_t;
    } else {
        cft_bn_sub(&mag, &Rs, &T);
        sign_e = !sign_t;
    }

    /* 9.5: underflow when the error term is "non-zero and lies strictly
     * between +-b^emin". A statement about e, decided on the exact
     * residual, and it holds even though e is exact - which is why this
     * is not round_pack's own underflow bit. */
    tiny = (q + cft_bn_bitlen(&mag) - 1) < f->emin;

    if (cft_sf_round_pack(f, sign_e, &mag, q, 0, CFT_SF_RTTZ, ve, &efl))
        return 1;
    if (efl & CFT_SF_INEXACT) {
        /* The residual carried non-zero digits below the format's
         * smallest quantum. 9.5 gives this delivery to
         * augmentedMultiplication alone; for a sum it cannot happen,
         * and saying so out loud beats absorbing it into a flag. */
        if (!is_mul || !tiny)
            return 1;
        *acc |= CFT_SF_UNDERFLOW | CFT_SF_INEXACT;
        return 0;
    }
    if (tiny)
        *acc |= CFT_SF_UNDERFLOW;
    return 0;
}

/* ---- one lane ----------------------------------------------------- */

static int aug_add_lane(const cft_fmt_desc *f, const cft_bn *xa,
                        const cft_bn *xb, cft_bn *vr, cft_bn *ve,
                        uint32_t *acc)
{
    lane_cls ka, kb;
    cft_bn ma, mb, ta, tb, t;
    int ea, eb, VEa, VEb;

    cls_of(f, xa, &ka);
    cls_of(f, xb, &kb);

    if (ka.kind == K_NAN || kb.kind == K_NAN) {
        cft_sf_qnan(f, vr);
        cft_bn_copy(ve, vr);
        if (ka.signaling || kb.signaling)
            *acc |= CFT_SF_INVALID;
        return 0;
    }
    if (ka.kind == K_INF && kb.kind == K_INF && ka.sign != kb.sign) {
        cft_sf_qnan(f, vr);                        /* inf + (-inf) */
        cft_bn_copy(ve, vr);
        *acc |= CFT_SF_INVALID;
        return 0;
    }
    if (ka.kind == K_INF || kb.kind == K_INF) {
        cft_sf_inf(f, ka.kind == K_INF ? ka.sign : kb.sign, vr);
        cft_bn_copy(ve, vr);
        return 0;
    }
    if (ka.kind == K_ZERO && kb.kind == K_ZERO) {
        /* 6.3: like-signed zeros keep their sign; an exact cancellation
         * is +0 in every attribute except roundTowardNegative, and
         * roundTiesTowardZero is not that one. */
        cft_sf_zero(f, ka.sign == kb.sign ? ka.sign : 0, vr);
        cft_bn_copy(ve, vr);
        return 0;
    }
    if (ka.kind == K_ZERO || kb.kind == K_ZERO) {
        const cft_bn *keep = ka.kind == K_ZERO ? xb : xa;
        cft_bn_copy(vr, keep);                     /* x + 0 is x exactly */
        cft_sf_zero(f, cft_bn_bit(keep, f->width - 1), ve);
        return 0;
    }

    bn_sig_exp(f, xa, &ka, &ma, &ea);
    bn_sig_exp(f, xb, &kb, &mb, &eb);
    VEa = ea + cft_bn_bitlen(&ma) - 1;
    VEb = eb + cft_bn_bitlen(&mb) - 1;

    if (VEa - VEb >= f->prec + 2 || VEb - VEa >= f->prec + 2) {
        /* FAR: r is the larger operand and e is the smaller, both
         * exactly - see this file's banner for why. The only flag
         * available is the underflow a subnormal residual earns. */
        int a_bigger = VEa > VEb;
        const lane_cls *ks = a_bigger ? &kb : &ka;
        cft_bn_copy(vr, a_bigger ? xa : xb);
        cft_bn_copy(ve, a_bigger ? xb : xa);
        if (ks->kind == K_SUB)
            *acc |= CFT_SF_UNDERFLOW;
        return 0;
    }

    {
        int e0 = ea < eb ? ea : eb;
        int cmp;
        if (cft_bn_shl(&ta, &ma, ea - e0))
            return 1;
        if (cft_bn_shl(&tb, &mb, eb - e0))
            return 1;
        if (ka.sign == kb.sign) {
            if (cft_bn_add(&t, &ta, &tb))
                return 1;
            return aug_pair(f, ka.sign, &t, e0, 0, vr, ve, acc);
        }
        cmp = cft_bn_cmp(&ta, &tb);
        if (cmp == 0) {
            cft_sf_zero(f, 0, vr);                 /* 6.3 cancellation */
            cft_bn_copy(ve, vr);
            return 0;
        }
        if (cmp > 0) {
            cft_bn_sub(&t, &ta, &tb);
            return aug_pair(f, ka.sign, &t, e0, 0, vr, ve, acc);
        }
        cft_bn_sub(&t, &tb, &ta);
        return aug_pair(f, kb.sign, &t, e0, 0, vr, ve, acc);
    }
}

static int aug_mul_lane(const cft_fmt_desc *f, const cft_bn *xa,
                        const cft_bn *xb, cft_bn *vr, cft_bn *ve,
                        uint32_t *acc)
{
    lane_cls ka, kb;
    cft_bn ma, mb, mp;
    int ea, eb, sp;

    cls_of(f, xa, &ka);
    cls_of(f, xb, &kb);

    if (ka.kind == K_NAN || kb.kind == K_NAN) {
        cft_sf_qnan(f, vr);
        cft_bn_copy(ve, vr);
        if (ka.signaling || kb.signaling)
            *acc |= CFT_SF_INVALID;
        return 0;
    }
    sp = ka.sign ^ kb.sign;
    if ((ka.kind == K_INF && kb.kind == K_ZERO) ||
        (ka.kind == K_ZERO && kb.kind == K_INF)) {
        cft_sf_qnan(f, vr);                        /* inf * 0 */
        cft_bn_copy(ve, vr);
        *acc |= CFT_SF_INVALID;
        return 0;
    }
    if (ka.kind == K_INF || kb.kind == K_INF) {
        cft_sf_inf(f, sp, vr);
        cft_bn_copy(ve, vr);
        return 0;
    }
    if (ka.kind == K_ZERO || kb.kind == K_ZERO) {
        cft_sf_zero(f, sp, vr);                    /* 6.3: the XOR sign */
        cft_bn_copy(ve, vr);
        return 0;
    }

    bn_sig_exp(f, xa, &ka, &ma, &ea);
    bn_sig_exp(f, xb, &kb, &mb, &eb);
    if (cft_bn_mul(&mp, &ma, &mb))                 /* exact, 2p bits */
        return 1;
    return aug_pair(f, sp, &mp, ea + eb, 1, vr, ve, acc);
}

/* ---- the entry points --------------------------------------------- */

static cft_status aug_validate(cft_device *dev, cft_format fmt,
                               const void *a, const void *b,
                               const void *r, const void *e, size_t n)
{
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0)
        return CFT_OK;
    if (!a || !b || !r || !e)
        return CFT_ERR_INVALID_ARGUMENT;
    /* r and e are two outputs of one operation: writing both into one
     * buffer has no well-defined ordering, so the identical-pointer
     * case - the one a caller actually reaches by accident - is
     * refused here rather than computed. A partial overlap is
     * undefined and not policed, exactly as cft_convert's
     * "d MUST NOT overlap a" is not policed. Either output MAY alias
     * an input: each element is read before either is written. */
    if (r == e)
        return CFT_ERR_INVALID_ARGUMENT;
    return CFT_OK;
}

static cft_status aug_batch(cft_device *dev, cft_format fmt, int is_mul,
                            const void *a, const void *b, void *r, void *e,
                            size_t n, uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i, esz;
    cft_status st = aug_validate(dev, fmt, a, b, r, e, n);

    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        cft_bn xa, xb, vr, ve;
        int bad;
        lane_load(f, (const uint8_t *)a, i, &xa);
        lane_load(f, (const uint8_t *)b, i, &xb);
        bad = is_mul ? aug_mul_lane(f, &xa, &xb, &vr, &ve, &acc)
                     : aug_add_lane(f, &xa, &xb, &vr, &ve, &acc);
        if (bad)
            return CFT_ERR_INTERNAL;
        /* Both outputs are written after both inputs are read, so r or
         * e may alias a or b. */
        lane_store(f, (uint8_t *)r, i, &vr);
        lane_store(f, (uint8_t *)e, i, &ve);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_augmented_add(cft_device *dev, cft_format fmt,
                                     const void *a, const void *b,
                                     void *r, void *e, size_t n,
                                     uint32_t *flags_out)
{
    return aug_batch(dev, fmt, 0, a, b, r, e, n, flags_out);
}

CFT_API cft_status cft_augmented_sub(cft_device *dev, cft_format fmt,
                                     const void *a, const void *b,
                                     void *r, void *e, size_t n,
                                     uint32_t *flags_out)
{
    /* x - y is x + (-y) with every rule of augmentedAddition, the
     * signed zeros included - so the negation happens per element here
     * rather than the whole operation being written twice. b is read
     * before either output is written, so aliasing still holds. */
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i, esz;
    cft_status st = aug_validate(dev, fmt, a, b, r, e, n);

    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        cft_bn xa, xb, vr, ve;
        lane_load(f, (const uint8_t *)a, i, &xa);
        lane_load(f, (const uint8_t *)b, i, &xb);
        if (cft_bn_bit(&xb, f->width - 1))
            cft_bn_clearbit(&xb, f->width - 1);
        else
            cft_bn_setbit(&xb, f->width - 1);
        if (aug_add_lane(f, &xa, &xb, &vr, &ve, &acc))
            return CFT_ERR_INTERNAL;
        lane_store(f, (uint8_t *)r, i, &vr);
        lane_store(f, (uint8_t *)e, i, &ve);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_augmented_mul(cft_device *dev, cft_format fmt,
                                     const void *a, const void *b,
                                     void *r, void *e, size_t n,
                                     uint32_t *flags_out)
{
    return aug_batch(dev, fmt, 1, a, b, r, e, n, flags_out);
}
