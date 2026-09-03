/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The scaled product reductions of IEEE 754-2019 clause 9.4:
 * scaledProd, scaledProdSum and scaledProdDiff.
 *
 * A port of python/cft_golden/reduce.py's scaled_prod(), which remains
 * the definition of correct. "Port" is the operative word here as it is
 * in softfloat.c: the order of the special-value rows, the leaf rule,
 * the node rule and the names are deliberately the same, so the two can
 * be read side by side.
 *
 * THE SHAPE, IN ONE PARAGRAPH. Every node carries a pair - a
 * significand in +-[1, 2) and an exact integer scale - so the value it
 * stands for is significand * 2^scale. A leaf splits its element into
 * that pair, which is exact for every finite non-zero operand,
 * subnormals included. A node multiplies its children's significands
 * under the caller's attribute (the node's one rounding), adds their
 * scales, and extracts the product's binade back out into the scale.
 * That last step is exact because the product is in +-[1, 4): scaling a
 * normal number by a power of two inside the exponent range never
 * rounds. The invariant is what delivers 9.4's requirement that pr not
 * be affected by overflow or underflow - both operands of every
 * multiply are in +-[1, 2), so no product can leave the format.
 *
 * These issue no device pass. There is no tile accumulator for a scaled
 * product - the accumulator streams ADDs - so the device argument is
 * context, exactly as it is for the transcendentals, and the results
 * are bit-identical across backends by construction.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

/* ---- lane accessors and classification (clause5.c's, restated) ---- */

#define SP_ZERO 0
#define SP_SUB  1
#define SP_NORM 2
#define SP_INF  3
#define SP_NAN  4

typedef struct {
    int kind;
    int sign;
    int signaling;
    uint32_t ef;
} sp_cls;

static void sp_classify(const cft_fmt_desc *f, const cft_bn *x, sp_cls *c)
{
    cft_bn frac;
    c->sign = cft_bn_bit(x, f->width - 1);
    c->ef = cft_bn_extract(x, f->man_w, f->exp_w);
    c->signaling = 0;
    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (c->ef == f->exp_mask) {
        if (cft_bn_is_zero(&frac)) {
            c->kind = SP_INF;
        } else {
            c->kind = SP_NAN;
            c->signaling = !cft_bn_bit(x, f->man_w - 1);
        }
        return;
    }
    if (c->ef == 0) {
        c->kind = cft_bn_is_zero(&frac) ? SP_ZERO : SP_SUB;
        return;
    }
    c->kind = SP_NORM;
}

/* ---- the scaling rule --------------------------------------------
 *
 * x (finite, non-zero) -> a significand in +-[1, 2) and the exact
 * scale k with x == significand * 2^k. Mirrors
 * cft_golden.reduce.norm_split().
 *
 * Used at both ends of the tree: on a leaf, where x is any finite
 * non-zero operand, and on a node's product, where |x| <= 4 and k comes
 * out as 0, 1 or 2. Exact in both cases - a subnormal has FEWER
 * significant bits than the format holds, so its normalised significand
 * always fits, which is the mechanism by which a scaled product cannot
 * underflow.
 */
static void sp_split(const cft_fmt_desc *f, const cft_bn *x,
                     cft_bn *sig, int64_t *k)
{
    sp_cls c;
    cft_bn m;
    int b, e;

    sp_classify(f, x, &c);

    /* m and e with |x| == m * 2^e, m an integer - the model's
     * unpack(). */
    cft_bn_copy(&m, x);
    cft_bn_mask(&m, f->man_w);
    if (c.ef == 0) {
        e = f->emin - f->man_w;                       /* subnormal */
    } else {
        cft_bn_setbit(&m, f->man_w);                  /* the hidden bit */
        e = (int)c.ef - f->bias - f->man_w;
    }

    b = cft_bn_bitlen(&m) - 1;                        /* m >= 1 here */
    /* significand = m scaled to [1, 2): shift its leading bit up to
     * the hidden-bit position, then wear the format's own bias. */
    (void)cft_bn_shl(&m, &m, f->man_w - b);
    cft_bn_mask(&m, f->man_w);
    {
        cft_bn ex;
        cft_bn_zero(&ex);
        cft_bn_set_u32(&ex, (uint32_t)f->bias);
        (void)cft_bn_shl(&ex, &ex, f->man_w);
        cft_bn_or(sig, &m, &ex);
    }
    if (c.sign)
        cft_bn_setbit(sig, f->width - 1);

    *k = (int64_t)e + (int64_t)b;
}

/* One int64 addition of the scale accumulator, checked. The model
 * checks every addition too rather than only the total, so that the two
 * refuse on exactly the same inputs - a transient partial that wrapped
 * here and came back in range would be a silent divergence. */
static int sp_scale_add(int64_t a, int64_t b, int64_t *out)
{
    if (b > 0 && a > INT64_MAX - b)
        return 1;
    if (b < 0 && a < INT64_MIN - b)
        return 1;
    *out = a + b;
    return 0;
}

/* T(lo, hi) over the factors. The same split() the sum tree uses: the
 * largest power of two strictly inside the range, so the LEFT child is
 * a perfect subtree. Depth is ceil(log2 n), at most 64 frames for any n
 * a host can express.
 *
 * Returns 0, 1 on an internal invariant failure, or 2 when the scale
 * left the int64 range. */
static int sp_tree(const cft_fmt_desc *f, int rnd, const void *fac,
                   size_t esz, size_t lo, size_t hi, cft_bn *sig,
                   int64_t *scale, uint32_t *flags)
{
    cft_bn left, right, prod, dummy;
    int64_t lk = 0, rk = 0, k = 0, acc = 0;
    uint32_t lf = 0, rf = 0, pf = 0;
    size_t mid;
    int st;

    *flags = 0;
    if (hi - lo == 1) {
        cft_bn leaf;
        cft_bn_load(&leaf, (const uint8_t *)fac + lo * esz, (int)esz);
        sp_split(f, &leaf, sig, scale);
        return 0;
    }

    {
        size_t m = hi - lo, kk = 1;
        while (kk < m)
            kk <<= 1;                /* smallest power of two >= m */
        mid = lo + (kk >> 1);        /* m >= 2 here, so kk >= 2 */
    }

    if ((st = sp_tree(f, rnd, fac, esz, lo, mid, &left, &lk, &lf)) != 0)
        return st;
    if ((st = sp_tree(f, rnd, fac, esz, mid, hi, &right, &rk, &rf)) != 0)
        return st;

    cft_bn_zero(&dummy);
    if (cft_sf_compute(f, CFT_SF_MUL, rnd, &left, &right, &dummy, &prod, &pf))
        return 1;
    sp_split(f, &prod, sig, &k);

    if (sp_scale_add(lk, rk, &acc) || sp_scale_add(acc, k, scale))
        return 2;
    *flags = lf | rf | pf;
    return 0;
}

/* ---- the entry points --------------------------------------------- */

/* kind: 0 scaledProd, 1 scaledProdSum, 2 scaledProdDiff. */
static cft_status scaled_prod_impl(cft_device *dev, cft_format fmt,
                                   cft_round rnd, const void *a,
                                   const void *b, int kind, void *pr,
                                   int64_t *scale_out, size_t n,
                                   uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    size_t esz, i;
    uint32_t flags = 0;
    uint8_t *leaves = NULL;          /* only _sum and _diff need one */
    const void *fac;
    cft_bn out;
    int sign = 0, saw_inf = 0, saw_zero = 0, saw_nan = 0, saw_snan = 0;
    int64_t scale = 0;

    (void)dev;                       /* context: no device pass is issued */
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!pr || !scale_out)
        return CFT_ERR_INVALID_ARGUMENT;

    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)f->width / 8;

    /* 9.4: "When the vector length operand is zero, pr is 1 and sf is
     * +0 without exception." The multiplicative identity, and the only
     * result here that is not a function of any input - so it is
     * decided before the operands are even looked at, exactly as
     * cft_reduce decides the empty sum. */
    if (n == 0) {
        cft_bn one;
        cft_bn_zero(&one);
        cft_bn_set_u32(&one, (uint32_t)f->bias);
        (void)cft_bn_shl(&one, &one, f->man_w);
        cft_bn_store(&one, (uint8_t *)pr, (int)esz);
        *scale_out = 0;
        if (flags_out)
            *flags_out = 0;
        return CFT_OK;
    }

    if (!a || (kind != 0 && !b))
        return CFT_ERR_INVALID_ARGUMENT;
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

    /* The factors. For scaledProd they are the elements themselves and
     * nothing is allocated; for the other two they are the ROUNDED
     * sums or differences, materialised once into a scratch buffer the
     * size of one input array - the same trade CFT_DOT makes for its
     * multiply pass.
     *
     * That leaf rounding is a contract add in the caller's attribute
     * with its full flags, which is why those two - and only those
     * two - can signal overflow or underflow. */
    if (kind == 0) {
        fac = a;
    } else {
        leaves = (uint8_t *)malloc(n * esz);
        if (!leaves)
            return CFT_ERR_OUT_OF_MEMORY;
        for (i = 0; i < n; i++) {
            cft_bn xa, xb, s, dummy;
            uint32_t lf = 0;
            cft_bn_load(&xa, (const uint8_t *)a + i * esz, (int)esz);
            cft_bn_load(&xb, (const uint8_t *)b + i * esz, (int)esz);
            cft_bn_zero(&dummy);
            /* ADD and SUB read a and c - b is steered to 1.0 - so the
             * two addends go in the first and THIRD slots. */
            if (cft_sf_compute(f, kind == 1 ? CFT_SF_ADD : CFT_SF_SUB,
                               (int)rnd, &xa, &dummy, &xb, &s, &lf)) {
                free(leaves);
                return CFT_ERR_INTERNAL;
            }
            cft_bn_store(&s, leaves + i * esz, (int)esz);
            flags |= lf;
        }
        fac = leaves;
    }

    /* 9.4's special-value rows, in 9.4's order, over the factors. */
    for (i = 0; i < n; i++) {
        sp_cls c;
        cft_bn v;
        cft_bn_load(&v, (const uint8_t *)fac + i * esz, (int)esz);
        sp_classify(f, &v, &c);
        sign ^= c.sign;
        if (c.kind == SP_NAN) {
            saw_nan = 1;
            saw_snan |= c.signaling;
        } else if (c.kind == SP_INF) {
            saw_inf = 1;
        } else if (c.kind == SP_ZERO) {
            saw_zero = 1;
        }
    }

    if (saw_nan) {
        cft_sf_qnan(f, &out);
        if (saw_snan)
            flags |= CFT_FLAG_INVALID;
    } else if (saw_inf && saw_zero) {
        cft_sf_qnan(f, &out);
        flags |= CFT_FLAG_INVALID;
    } else if (saw_inf) {
        cft_sf_inf(f, sign, &out);
    } else if (saw_zero) {
        cft_sf_zero(f, sign, &out);
    } else {
        uint32_t tf = 0;
        int st = sp_tree(f, (int)rnd, fac, esz, 0, n, &out, &scale, &tf);
        if (st == 1) {
            free(leaves);
            return CFT_ERR_INTERNAL;
        }
        if (st == 2) {
            /* The scale left the int64 range. The product is not
             * delivered, so the tree's own flags are not either; the
             * leaf adds' flags stand, because those roundings did
             * happen. */
            cft_sf_qnan(f, &out);
            flags |= CFT_FLAG_INVALID;
            scale = 0;
        } else {
            flags |= tf;
        }
    }
    free(leaves);

    cft_bn_store(&out, (uint8_t *)pr, (int)esz);
    *scale_out = scale;
    if (flags_out)
        *flags_out = flags;
    return CFT_OK;
}

CFT_API cft_status cft_scaled_prod(cft_device *dev, cft_format fmt,
                                   cft_round rnd, const void *a,
                                   void *pr, int64_t *scale_out,
                                   size_t n, uint32_t *flags_out)
{
    return scaled_prod_impl(dev, fmt, rnd, a, NULL, 0, pr, scale_out, n,
                            flags_out);
}

CFT_API cft_status cft_scaled_prod_sum(cft_device *dev, cft_format fmt,
                                       cft_round rnd, const void *a,
                                       const void *b, void *pr,
                                       int64_t *scale_out, size_t n,
                                       uint32_t *flags_out)
{
    return scaled_prod_impl(dev, fmt, rnd, a, b, 1, pr, scale_out, n,
                            flags_out);
}

CFT_API cft_status cft_scaled_prod_diff(cft_device *dev, cft_format fmt,
                                        cft_round rnd, const void *a,
                                        const void *b, void *pr,
                                        int64_t *scale_out, size_t n,
                                        uint32_t *flags_out)
{
    return scaled_prod_impl(dev, fmt, rnd, a, b, 2, pr, scale_out, n,
                            flags_out);
}
