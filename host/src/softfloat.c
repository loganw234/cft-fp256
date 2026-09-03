/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The tile's arithmetic in C - a port of the golden model. See
 * softfloat.h for what "port" means here and what checks it.
 */

#include "softfloat.h"

const cft_fmt_desc cft_sf_formats[4] = {
    /* name    exp_w man_w width prec  bias    emax     emin    exp_mask */
    { "fp32",      8,   23,   32,  24,    127,    127,    -126,      255u },
    { "fp64",     11,   52,   64,  53,   1023,   1023,   -1022,     2047u },
    { "fp128",    15,  112,  128, 113,  16383,  16383,  -16382,    32767u },
    { "fp256",    19,  236,  256, 237, 262143, 262143, -262142,   524287u }
};

/* ---- packed constants ------------------------------------------- */

static void sf_set_ones(cft_bn *r, int lo, int nbits)
{
    int i;
    for (i = 0; i < nbits; i++)
        cft_bn_setbit(r, lo + i);
}

static void sf_set_field(cft_bn *r, int lo, int nbits, uint32_t val)
{
    int i;
    for (i = 0; i < nbits; i++)
        if ((val >> i) & 1u)
            cft_bn_setbit(r, lo + i);
}

static void sf_zero(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    cft_bn_zero(out);
    if (sign)
        cft_bn_setbit(out, f->width - 1);
}

static void sf_inf(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    cft_bn_zero(out);
    sf_set_ones(out, f->man_w, f->exp_w);
    if (sign)
        cft_bn_setbit(out, f->width - 1);
}

/* The canonical quiet NaN: the only NaN arithmetic here ever emits. */
static void sf_qnan(const cft_fmt_desc *f, cft_bn *out)
{
    cft_bn_zero(out);
    sf_set_ones(out, f->man_w, f->exp_w);
    cft_bn_setbit(out, f->man_w - 1);
}

static void sf_max_normal(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    cft_bn_zero(out);
    sf_set_ones(out, 0, f->man_w);
    sf_set_field(out, f->man_w, f->exp_w, f->exp_mask - 1u);
    if (sign)
        cft_bn_setbit(out, f->width - 1);
}

static void sf_one(const cft_fmt_desc *f, cft_bn *out)
{
    cft_bn_zero(out);
    sf_set_field(out, f->man_w, f->exp_w, (uint32_t)f->bias);
}

/* ---- unpack ------------------------------------------------------ */

enum { SF_ZERO, SF_SUB, SF_NORM, SF_INF, SF_NAN };

typedef struct {
    int    kind;
    int    sign;
    cft_bn m;      /* integer significand; value = (-1)^sign * m * 2^e */
    int    e;
    int    signaling;
} sf_unp;

static void sf_unpack(const cft_fmt_desc *f, const cft_bn *x, sf_unp *u)
{
    uint32_t ef = cft_bn_extract(x, f->man_w, f->exp_w);
    cft_bn_zero(&u->m);
    u->e = 0;
    u->signaling = 0;
    u->sign = cft_bn_bit(x, f->width - 1);
    cft_bn_copy(&u->m, x);
    cft_bn_mask(&u->m, f->man_w);
    if (ef == f->exp_mask) {
        if (cft_bn_is_zero(&u->m)) {
            u->kind = SF_INF;
        } else {
            u->kind = SF_NAN;
            u->signaling = !cft_bn_bit(x, f->man_w - 1);
        }
        cft_bn_zero(&u->m);
        return;
    }
    if (ef == 0) {
        if (cft_bn_is_zero(&u->m)) {
            u->kind = SF_ZERO;
            return;
        }
        u->kind = SF_SUB;
        u->e = f->emin - f->man_w;
        return;
    }
    u->kind = SF_NORM;
    cft_bn_setbit(&u->m, f->man_w);
    u->e = (int)ef - f->bias - f->man_w;
}

/* ---- rounding ---------------------------------------------------- */

static int sf_round_up(int rnd, int sign, int guard, int sticky, int lsb)
{
    switch (rnd) {
    case CFT_SF_RNE: return guard && (sticky || lsb);
    case CFT_SF_RMM: return guard;
    case CFT_SF_RTZ: return 0;
    case CFT_SF_RDN: return sign && (guard || sticky);
    default:         return !sign && (guard || sticky);   /* RUP */
    }
}

/* IEEE 754-2019 7.4: every mode signals overflow, but only some
 * deliver an infinity. */
static int sf_overflow_gives_inf(int rnd, int sign)
{
    switch (rnd) {
    case CFT_SF_RTZ: return 0;
    case CFT_SF_RDN: return sign;
    case CFT_SF_RUP: return !sign;
    default:         return 1;                            /* RNE, RMM */
    }
}

/* 754 6.3: an exact zero sum of oppositely-signed operands is +0 in
 * every attribute except roundTowardNegative. */
static int sf_cancel_zero_sign(int rnd)
{
    return rnd == CFT_SF_RDN ? 1 : 0;
}

/* Round the exact magnitude (m + eps) * 2^e to a multiple of 2^q,
 * where eps is in [0,1) and is non-zero exactly when `sticky`.
 *
 * The sticky fraction is representable this way only because the
 * caller guarantees q > e whenever it is set (see sf_round_pack).
 * Given that, guard = (rem >= half) is unaffected by eps < 1, and eps
 * folds into the sticky bit and into inexactness. */
static int sf_round_at(const cft_bn *m, int e, int q, int sign, int rnd,
                       int sticky, cft_bn *kept, int *inexact)
{
    int shift = q - e;
    *inexact = 0;
    if (shift <= 0) {
        if (sticky)
            return 1;
        return cft_bn_shl(kept, m, -shift);
    }
    cft_bn_shr(kept, m, shift);
    if (!cft_bn_low_nonzero(m, shift) && !sticky)
        return 0;
    {
        int guard = cft_bn_bit(m, shift - 1);
        int stk   = cft_bn_low_nonzero(m, shift - 1) || sticky;
        int lsb   = cft_bn_bit(kept, 0);
        if (sf_round_up(rnd, sign, guard, stk, lsb) && cft_bn_inc(kept))
            return 1;
    }
    *inexact = 1;
    return 0;
}

/* Round the exact non-zero magnitude (m + eps) * 2^e into the format.
 * m must be non-zero, and must have more than `prec` bits whenever
 * `sticky` is set - which is what keeps sf_round_at's shift positive. */
static int sf_round_pack(const cft_fmt_desc *f, int sign, const cft_bn *m,
                         int e, int sticky, int rnd,
                         cft_bn *out, uint32_t *flags)
{
    int p = f->prec;
    int L = cft_bn_bitlen(m);
    int e_norm, q_unb, q, e_res, tiny, inexact = 0, dummy = 0;
    cft_bn kept_u, kept;
    uint32_t fl = 0;

    if (L == 0 || (sticky && L <= p))
        return 1;
    e_norm = e + L - 1;

    /* Tininess after rounding (as RISC-V does, and as the RTL does):
     * round as if the exponent range were unbounded and ask whether
     * the result still lands below 2^emin. */
    q_unb = e_norm - (p - 1);
    if (sf_round_at(m, e, q_unb, sign, rnd, sticky, &kept_u, &dummy))
        return 1;
    tiny = (q_unb + cft_bn_bitlen(&kept_u) - 1) < f->emin;

    /* The real rounding position: the format's ulp, clamped so nothing
     * below the subnormal ulp is representable. */
    q = (e_norm > f->emin ? e_norm : f->emin) - (p - 1);
    if (sf_round_at(m, e, q, sign, rnd, sticky, &kept, &inexact))
        return 1;
    if (inexact)
        fl |= CFT_SF_INEXACT;

    if (cft_bn_is_zero(&kept)) {
        /* Rounded past the smallest subnormal. Only the modes that
         * round toward this side of zero can land here. */
        sf_zero(f, sign, out);
        *flags = fl | CFT_SF_UNDERFLOW;
        return 0;
    }

    e_res = q + cft_bn_bitlen(&kept) - 1;
    if (e_res > f->emax) {
        if (sf_overflow_gives_inf(rnd, sign))
            sf_inf(f, sign, out);
        else
            sf_max_normal(f, sign, out);
        *flags = fl | CFT_SF_OVERFLOW | CFT_SF_INEXACT;
        return 0;
    }
    if (tiny && inexact)
        fl |= CFT_SF_UNDERFLOW;

    if (e_res < f->emin) {
        /* Subnormal: kept has fewer than p bits and its LSB weight is
         * exactly emin - (p - 1), so it IS the fraction field. */
        cft_bn_copy(out, &kept);
        if (sign)
            cft_bn_setbit(out, f->width - 1);
        *flags = fl;
        return 0;
    }

    if (cft_bn_bitlen(&kept) == p + 1)
        cft_bn_shr(&kept, &kept, 1);      /* rounding carried out */
    cft_bn_clearbit(&kept, f->man_w);     /* drop the hidden bit */
    cft_bn_copy(out, &kept);
    sf_set_field(out, f->man_w, f->exp_w, (uint32_t)(e_res + f->bias));
    if (sign)
        cft_bn_setbit(out, f->width - 1);
    *flags = fl;
    return 0;
}

/* ---- fused multiply-add ------------------------------------------ *
 *
 * Everything above matches the golden model line for line. This is the
 * one function that does not, and the reason is worth stating.
 *
 * The model computes the sum exactly: it shifts both terms to a common
 * exponent min(ep, ec) and adds. For fp256 that alignment can span the
 * whole exponent range - the product of two huge normals against the
 * smallest subnormal addend is about 790,000 bits, a hundred kilobytes
 * of shifting for one element. Correct, and unusable.
 *
 * So the alignment is bounded. Let VEp and VEc be the positions of the
 * two terms' leading bits (their value exponents). Define
 *
 *     FAR = 2p + 4
 *
 * NEAR case, |VEp - VEc| <= FAR. Compute exactly, as the model does.
 * The span is bounded: with Lp in [2p-1, 2p] and Lc in [1, p], the
 * exponent difference ep - ec lies in [-4p-3, p+5], so the widest
 * intermediate is about 5p+3 bits - 1188 for fp256, which is what
 * CFT_BN_LIMBS is sized for.
 *
 * FAR case. The smaller term lies entirely below the larger term's
 * last bit, so it can only ever be a sticky bit. Write the larger term
 * as m * 2^e, left-shifted by k = max(2, p + 2 - L) so that m has at
 * least p+2 bits (sf_round_pack needs more than p whenever a sticky
 * accompanies it), and check that the smaller term still falls below
 * 2^e:
 *
 *   product larger:  need FAR > Lp - 1 + k. Lp >= 2p-1 forces k = 2,
 *                    so FAR > 2p + 1.                       OK
 *   addend larger:   need FAR >= Lc - 1 + k. If Lc >= p then k = 2 and
 *                    FAR >= p + 1; otherwise k = p + 2 - Lc and again
 *                    FAR >= p + 1.                          OK
 *
 * Then the result is exactly (m +/- tau) * 2^e with 0 < tau < 2^e:
 *
 *   like signs:      magnitude m + tau        -> (m,     sticky)
 *   unlike signs:    magnitude m - tau
 *                      = (m-1) + (1 - tau)    -> (m - 1, sticky)
 *
 * and in both cases the sign is the larger term's, because the far
 * condition makes it strictly larger in magnitude.
 *
 * The reduction is argued here and checked elsewhere:
 * host/tests/diff_check.py drives both implementations over exactly
 * the operand pairs that probe these boundaries.
 */

static int sf_nan_result(const cft_fmt_desc *f, const sf_unp *ua,
                         const sf_unp *ub, const sf_unp *uc,
                         cft_bn *out, uint32_t *flags)
{
    int inv = (ua->kind == SF_NAN && ua->signaling) ||
              (ub->kind == SF_NAN && ub->signaling) ||
              (uc != 0 && uc->kind == SF_NAN && uc->signaling);
    sf_qnan(f, out);
    *flags = inv ? CFT_SF_INVALID : 0u;
    return 0;
}

static int sf_fma(const cft_fmt_desc *f, const cft_bn *xa, const cft_bn *xb,
                  const cft_bn *xc, int rnd, cft_bn *out, uint32_t *flags)
{
    sf_unp ua, ub, uc;
    cft_bn mp, tp, tc, t;
    int sp, ep, Lp, Lc, VEp, VEc, FAR, e0;

    sf_unpack(f, xa, &ua);
    sf_unpack(f, xb, &ub);
    sf_unpack(f, xc, &uc);
    *flags = 0;

    if (ua.kind == SF_NAN || ub.kind == SF_NAN || uc.kind == SF_NAN)
        return sf_nan_result(f, &ua, &ub, &uc, out, flags);

    sp = ua.sign ^ ub.sign;

    if (ua.kind == SF_INF || ub.kind == SF_INF) {
        if (ua.kind == SF_ZERO || ub.kind == SF_ZERO) {
            sf_qnan(f, out);                     /* inf * 0 */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        if (uc.kind == SF_INF && uc.sign != sp) {
            sf_qnan(f, out);                     /* inf - inf */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        sf_inf(f, sp, out);
        return 0;
    }
    if (uc.kind == SF_INF) {
        sf_inf(f, uc.sign, out);
        return 0;
    }

    if (ua.kind == SF_ZERO || ub.kind == SF_ZERO) {
        if (uc.kind == SF_ZERO) {
            int rs = (uc.sign == sp) ? uc.sign : sf_cancel_zero_sign(rnd);
            sf_zero(f, rs, out);
            return 0;
        }
        cft_bn_copy(out, xc);        /* 0*b + c is c, exactly */
        return 0;
    }

    if (cft_bn_mul(&mp, &ua.m, &ub.m))
        return 1;
    ep = ua.e + ub.e;

    if (uc.kind == SF_ZERO)
        return sf_round_pack(f, sp, &mp, ep, 0, rnd, out, flags);

    Lp  = cft_bn_bitlen(&mp);
    Lc  = cft_bn_bitlen(&uc.m);
    VEp = ep + Lp - 1;
    VEc = uc.e + Lc - 1;
    FAR = 2 * f->prec + 4;

    if (VEp - VEc > FAR || VEc - VEp > FAR) {
        const cft_bn *bm;
        int be, bsign, osign, L, k;
        cft_bn m;

        if (VEp > VEc) {
            bm = &mp;      be = ep;     bsign = sp;        osign = uc.sign;
        } else {
            bm = &uc.m;    be = uc.e;   bsign = uc.sign;   osign = sp;
        }
        L = cft_bn_bitlen(bm);
        k = f->prec + 2 - L;
        if (k < 2)
            k = 2;
        if (cft_bn_shl(&m, bm, k))
            return 1;
        if (osign != bsign)
            cft_bn_dec(&m);
        return sf_round_pack(f, bsign, &m, be - k, 1, rnd, out, flags);
    }

    e0 = ep < uc.e ? ep : uc.e;
    if (cft_bn_shl(&tp, &mp, ep - e0))
        return 1;
    if (cft_bn_shl(&tc, &uc.m, uc.e - e0))
        return 1;

    if (sp == uc.sign) {
        if (cft_bn_add(&t, &tp, &tc))
            return 1;
        return sf_round_pack(f, sp, &t, e0, 0, rnd, out, flags);
    }
    {
        int c = cft_bn_cmp(&tp, &tc);
        if (c == 0) {
            sf_zero(f, sf_cancel_zero_sign(rnd), out);
            return 0;
        }
        if (c > 0) {
            cft_bn_sub(&t, &tp, &tc);
            return sf_round_pack(f, sp, &t, e0, 0, rnd, out, flags);
        }
        cft_bn_sub(&t, &tc, &tp);
        return sf_round_pack(f, uc.sign, &t, e0, 0, rnd, out, flags);
    }
}

/* ---- operand steering -------------------------------------------- *
 *
 * ADD, SUB and MUL are the one FMA with the operands steered, exactly
 * as rtl/cft_opmux.sv does it. Defining the steering in one place is
 * what keeps the model, the RTL and this library from drifting: the
 * quirks of realising a + c as a * 1.0 + c are then the same quirks
 * everywhere, rather than three implementations of "addition".
 */
static int sf_steer(const cft_fmt_desc *f, int op,
                    const cft_bn *xa, const cft_bn *xb, const cft_bn *xc,
                    cft_bn *ra, cft_bn *rb, cft_bn *rc)
{
    cft_bn_copy(ra, xa);
    switch (op) {
    case CFT_SF_FMA:
        cft_bn_copy(rb, xb);
        cft_bn_copy(rc, xc);
        return 0;
    case CFT_SF_ADD:
        sf_one(f, rb);
        cft_bn_copy(rc, xc);
        return 0;
    case CFT_SF_SUB:
        sf_one(f, rb);
        cft_bn_copy(rc, xc);
        if (cft_bn_bit(rc, f->width - 1))
            cft_bn_clearbit(rc, f->width - 1);
        else
            cft_bn_setbit(rc, f->width - 1);
        return 0;
    case CFT_SF_MUL:
        cft_bn_copy(rb, xb);
        sf_zero(f, cft_bn_bit(xa, f->width - 1) ^ cft_bn_bit(xb, f->width - 1),
                rc);
        return 0;
    default:
        return 1;
    }
}

/* ---- non-arithmetic operations ----------------------------------- *
 *
 * 754-2019 5.5.1 calls abs/negate/copySign quiet-computational: they
 * touch the sign bit and nothing else, signal nothing at all (not even
 * for a signaling NaN), and pass every other bit through - a NaN's
 * payload included. That is a deliberate exception to the canonical
 * NaN rule and does not weaken it: the canonical rule exists because
 * in arithmetic the choice of which payload survives is where
 * implementations diverge, and here there is exactly one source.
 */

static void sf_magnitude(const cft_fmt_desc *f, const cft_bn *x, cft_bn *r)
{
    cft_bn_copy(r, x);
    cft_bn_clearbit(r, f->width - 1);
}

/* x < y for non-NaN operands, IEEE comparison, so -0 == +0. */
static int sf_numeric_lt(const cft_fmt_desc *f, const cft_bn *xa,
                         const cft_bn *xb)
{
    cft_bn ma, mb;
    int sa = cft_bn_bit(xa, f->width - 1);
    int sb = cft_bn_bit(xb, f->width - 1);
    sf_magnitude(f, xa, &ma);
    sf_magnitude(f, xb, &mb);
    if (cft_bn_is_zero(&ma) && cft_bn_is_zero(&mb))
        return 0;
    if (sa != sb)
        return sa;
    /* Same sign: the magnitude ordering of the encoding is monotone,
     * so the payload-free bit pattern compares directly. */
    return sa ? (cft_bn_cmp(&ma, &mb) > 0) : (cft_bn_cmp(&ma, &mb) < 0);
}

static int sf_is_nan(const cft_fmt_desc *f, const cft_bn *x, int *signaling)
{
    cft_bn frac;
    if (cft_bn_extract(x, f->man_w, f->exp_w) != f->exp_mask)
        return 0;
    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (cft_bn_is_zero(&frac))
        return 0;
    if (signaling)
        *signaling = !cft_bn_bit(x, f->man_w - 1);
    return 1;
}

/* 754-2019 9.6. `number` selects the ...Number variants, which return
 * the non-NaN operand instead of propagating the NaN. */
static void sf_minmax(const cft_fmt_desc *f, const cft_bn *xa,
                      const cft_bn *xb, int want_max, int number,
                      cft_bn *out, uint32_t *flags)
{
    int sa = 0, sb = 0;
    int a_nan = sf_is_nan(f, xa, &sa);
    int b_nan = sf_is_nan(f, xb, &sb);
    cft_bn ma, mb;

    *flags = ((a_nan && sa) || (b_nan && sb)) ? CFT_SF_INVALID : 0u;
    if (a_nan || b_nan) {
        if (!number || (a_nan && b_nan))
            sf_qnan(f, out);
        else
            cft_bn_copy(out, a_nan ? xb : xa);
        return;
    }
    sf_magnitude(f, xa, &ma);
    sf_magnitude(f, xb, &mb);
    if (cft_bn_is_zero(&ma) && cft_bn_is_zero(&mb)) {
        /* Signed zeros compare equal but are not interchangeable: the
         * standard requires min(+0,-0) = -0 and max(+0,-0) = +0. */
        int za = cft_bn_bit(xa, f->width - 1);
        int zb = cft_bn_bit(xb, f->width - 1);
        if (za == zb) {
            cft_bn_copy(out, xa);
        } else {
            const cft_bn *neg = za ? xa : xb;
            const cft_bn *pos = za ? xb : xa;
            cft_bn_copy(out, want_max ? pos : neg);
        }
        return;
    }
    {
        int a_lt_b = sf_numeric_lt(f, xa, xb);
        if (want_max)
            cft_bn_copy(out, a_lt_b ? xb : xa);
        else
            cft_bn_copy(out, a_lt_b ? xa : xb);
    }
}

/* 754-2019 5.11 quiet comparison, yielding 1.0 or +0.0 rather than a
 * condition code - which is what makes it the operand a later SELECT
 * consumes, and what makes branchless conditional code expressible. */
static void sf_compare(const cft_fmt_desc *f, const cft_bn *xa,
                       const cft_bn *xb, int want,
                       cft_bn *out, uint32_t *flags)
{
    int sa = 0, sb = 0;
    int a_nan = sf_is_nan(f, xa, &sa);
    int b_nan = sf_is_nan(f, xb, &sb);
    int lt, gt, eq, truth;

    *flags = ((a_nan && sa) || (b_nan && sb)) ? CFT_SF_INVALID : 0u;
    if (a_nan || b_nan) {
        sf_zero(f, 0, out);                   /* unordered: all false */
        return;
    }
    lt = sf_numeric_lt(f, xa, xb);
    gt = sf_numeric_lt(f, xb, xa);
    eq = !lt && !gt;
    truth = (want == CFT_SF_CMPLT) ? lt : (want == CFT_SF_CMPLE) ? (lt || eq)
                                                                 : eq;
    if (truth)
        sf_one(f, out);
    else
        sf_zero(f, 0, out);
}

/* Shifts take their count from b's low bits, modulo the width. Every
 * format here is a power-of-two number of bits, so this is exactly the
 * low log2(width) bits and no count can be out of range. */
static int sf_shift_amount(const cft_fmt_desc *f, const cft_bn *xb)
{
    return (int)(cft_bn_extract(xb, 0, 32) & (uint32_t)(f->width - 1));
}

static int sf_integer_op(const cft_fmt_desc *f, int op, const cft_bn *xa,
                         const cft_bn *xb, cft_bn *out)
{
    switch (op) {
    case CFT_SF_IAND: cft_bn_and(out, xa, xb); return 0;
    case CFT_SF_IOR:  cft_bn_or(out, xa, xb);  return 0;
    case CFT_SF_IXOR: cft_bn_xor(out, xa, xb); return 0;
    case CFT_SF_IADD:
        if (cft_bn_add(out, xa, xb))
            return 1;
        cft_bn_mask(out, f->width);
        return 0;
    case CFT_SF_ISUB: {
        cft_bn t;
        cft_bn_copy(&t, xa);
        cft_bn_setbit(&t, f->width);          /* borrow, then wrap */
        cft_bn_sub(out, &t, xb);
        cft_bn_mask(out, f->width);
        return 0;
    }
    case CFT_SF_ISHL:
        if (cft_bn_shl(out, xa, sf_shift_amount(f, xb)))
            return 1;
        cft_bn_mask(out, f->width);
        return 0;
    case CFT_SF_ISHR:
        cft_bn_shr(out, xa, sf_shift_amount(f, xb));   /* logical, always */
        return 0;
    case CFT_SF_ICMPLT:
        if (cft_bn_cmp(xa, xb) < 0)
            sf_one(f, out);
        else
            sf_zero(f, 0, out);
        return 0;
    default:
        return 1;
    }
}

/* ---- divide/sqrt seeds --------------------------------------------
 *
 * Mirrors of _seed_recip_entry/_seed_rsqrt_entry and recip_seed/
 * rsqrt_seed in the model, per the standing rule that constants are
 * derived, never transcribed: both entry functions compute the
 * nearest integer by exact integer arithmetic, the same arithmetic
 * the model states, and the RTL's ROM is generated from the same
 * definitions. Quiet by specification - no flags, ever - and
 * subnormal INPUTS flush to their zero-class result, a deliberate
 * spec choice the model documents at recip_seed.
 */

/* Nearest integer to 2^18 / (1 + (i + 1/2)/2^9); ties (impossible,
 * proven by test_seeds.py) would round to even. In (2^17, 2^18). */
static uint32_t seed_recip_entry(uint32_t i)
{
    uint32_t num = 1u << 28;              /* 2^18 * 2^10 */
    uint32_t den = (1u << 10) + (i << 1) + 1u;
    uint32_t q = num / den, r = num % den;
    if (2u * r > den || (2u * r == den && (q & 1u)))
        q++;
    return q;
}

/* Nearest integer to 2^17 / sqrt(mid), mid = (1 + (i + 1/2)/2^9) *
 * 2^odd, decided by exact comparison against the squared midpoint -
 * no floating point anywhere. In (2^16, 2^17). */
static uint32_t seed_rsqrt_entry(uint32_t j)
{
    uint32_t odd = j >> 9, i = j & 511u;
    uint64_t m2 = (uint64_t)(((1u << 10) + (i << 1) + 1u)) << odd;
    uint64_t target = 1ull << 44;
    uint64_t t = target / m2;
    uint64_t q = 0, bit;
    /* floor(sqrt(t)); t < 2^34, so 18 candidate bits cover it */
    for (bit = 1ull << 17; bit; bit >>= 1) {
        uint64_t c = q | bit;
        if (c * c <= t)
            q = c;
    }
    while ((q + 1) * (q + 1) * m2 <= target)
        q++;
    /* round up when (q + 1/2)^2 * m2 < 2^44 */
    if ((2 * q + 1) * (2 * q + 1) * m2 < (1ull << 46))
        q++;
    return (uint32_t)q;
}

/* round_pack without the flags: the pack of the seed value into a
 * subnormal result at the range edges is defined as RNE and is part
 * of the spec, not a mode choice. */
static void seed_pack(const cft_fmt_desc *f, int sign, uint32_t r, int e,
                      cft_bn *out)
{
    cft_bn m;
    uint32_t discard = 0;
    cft_bn_set_u32(&m, r);
    (void)sf_round_pack(f, sign, &m, e, 0, CFT_SF_RNE, out, &discard);
}

static int sf_recip_seed(const cft_fmt_desc *f, const cft_bn *x, cft_bn *out)
{
    int sign = cft_bn_bit(x, f->width - 1);
    uint32_t ef = cft_bn_extract(x, f->man_w, f->exp_w);
    cft_bn frac;
    int E, e_out, rbits;
    uint32_t r;

    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (ef == f->exp_mask) {
        if (!cft_bn_is_zero(&frac)) {
            sf_qnan(f, out);                     /* NaN, quietly */
            return 0;
        }
        sf_zero(f, sign, out);                   /* +/-inf -> +/-0 */
        return 0;
    }
    if (ef == 0) {
        /* Zero OR subnormal: flush-at-input, see the model. */
        sf_inf(f, sign, out);
        return 0;
    }
    E = (int)ef - f->bias;
    r = seed_recip_entry(cft_bn_extract(x, f->man_w - 9, 9));
    e_out = -E - 18;
    rbits = 18;                                  /* msb always set */
    if (e_out + rbits - 1 > f->emax) {
        sf_inf(f, sign, out);
        return 0;
    }
    seed_pack(f, sign, r, e_out, out);
    return 0;
}

static int sf_rsqrt_seed(const cft_fmt_desc *f, const cft_bn *x, cft_bn *out)
{
    int sign = cft_bn_bit(x, f->width - 1);
    uint32_t ef = cft_bn_extract(x, f->man_w, f->exp_w);
    cft_bn frac;
    int E, odd, e_out;
    uint32_t r;

    cft_bn_copy(&frac, x);
    cft_bn_mask(&frac, f->man_w);
    if (ef == f->exp_mask && !cft_bn_is_zero(&frac)) {
        sf_qnan(f, out);
        return 0;
    }
    if (ef == 0) {
        /* Zero-class (subnormals included, by flush-at-input): the
         * correspondingly-signed infinity, the 754 limit. */
        sf_inf(f, sign, out);
        return 0;
    }
    if (sign) {
        sf_qnan(f, out);                         /* negative */
        return 0;
    }
    if (ef == f->exp_mask) {
        sf_zero(f, 0, out);                      /* +inf -> +0 */
        return 0;
    }
    E = (int)ef - f->bias;
    odd = E & 1;
    r = seed_rsqrt_entry(((uint32_t)odd << 9) |
                         cft_bn_extract(x, f->man_w - 9, 9));
    /* (E - odd) is even, so C's truncating division is the model's
     * floor division here. */
    e_out = -((E - odd) / 2) - 17;
    seed_pack(f, 0, r, e_out, out);
    return 0;
}

/* ---- dispatch ---------------------------------------------------- */

int cft_sf_op_assigned(int op)
{
    return (op >= 0 && op <= 14) || (op >= 16 && op <= 23) ||
           (op >= CFT_SF_SUM && op <= CFT_SF_SUMABS);
}

int cft_sf_is_reduction(int op)
{
    return op == CFT_SF_SUM || op == CFT_SF_DOT ||
           op == CFT_SF_SUMSQ || op == CFT_SF_SUMABS;
}

unsigned cft_sf_op_operands(int op)
{
    switch (op) {
    case CFT_SF_FMA:      return 1u | 2u | 4u;
    case CFT_SF_ADD:      return 1u | 4u;          /* b steered to 1.0 */
    case CFT_SF_SUB:      return 1u | 4u;
    case CFT_SF_MUL:      return 1u | 2u;          /* c steered to zero */
    case CFT_SF_ABS:
    case CFT_SF_NEG:      return 1u;
    case CFT_SF_RECIP_SEED:
    case CFT_SF_RSQRT_SEED: return 1u;
    case CFT_SF_SELECT:   return 1u | 2u | 4u;
    case CFT_SF_SUM:      return 1u;
    case CFT_SF_DOT:      return 1u | 2u;
    /* One vector each: sumSquare squares a against ITSELF, so it does
     * not read a second one, and b may be NULL for both. */
    case CFT_SF_SUMSQ:
    case CFT_SF_SUMABS:   return 1u;
    default:              return cft_sf_op_assigned(op) ? (1u | 2u) : 0u;
    }
}

/* ---- the reduction tree ------------------------------------------
 *
 * Mirrors python/cft_golden/reduce.py exactly, including the two edges
 * that look like oversights and are not: a single element is returned
 * verbatim with no flags (one leaf means zero adds, so nothing can be
 * raised - not even for a signalling NaN), and an empty range is +0.0.
 */

/* One leaf. For sum that is the element itself; for dot it is the
 * ROUNDED product, which is what makes dot(a,b) == sum(mul(a,b)). */
static int reduce_leaf(const cft_fmt_desc *f, int op, int rnd,
                       const void *a, const void *b, size_t esz, size_t i,
                       cft_bn *out, uint32_t *flags)
{
    cft_bn ba, bb, bz;

    cft_bn_zero(&ba);
    cft_bn_zero(&bb);
    cft_bn_zero(&bz);
    cft_bn_load(&ba, (const uint8_t *)a + i * esz, (int)esz);

    if (op == CFT_SF_DOT) {
        cft_bn_load(&bb, (const uint8_t *)b + i * esz, (int)esz);
        return cft_sf_compute(f, CFT_SF_MUL, rnd, &ba, &bb, &bz, out, flags);
    }
    *out = ba;
    *flags = 0;
    return 0;
}

int cft_sf_reduce(const cft_fmt_desc *f, int op, int rnd,
                  const void *a, const void *b, size_t esz,
                  size_t lo, size_t hi,
                  cft_bn *out, uint32_t *flags)
{
    cft_bn left, right, dummy;
    uint32_t lf = 0, rf = 0, af = 0;
    size_t mid;

    *flags = 0;
    if (hi < lo)
        return 1;
    if (hi == lo) {
        sf_zero(f, 0, out);
        return 0;
    }
    if (hi - lo == 1)
        return reduce_leaf(f, op, rnd, a, b, esz, lo, out, flags);

    /* The one place the shape is written down on this side of the
     * fence: the largest power of two strictly inside the range, so the
     * LEFT child is always a perfect subtree and the remainder goes
     * right. Matches cft_golden.reduce.split().
     *
     * Not the midpoint, and the difference is the whole reason the
     * shape is this one: this tree is exactly what a streaming
     * binary-counter accumulator produces - one add per element,
     * ceil(log2 n) levels, carry when a level is occupied - which is
     * what the RTL will be. The midpoint tree agrees only when n is a
     * power of two. */
    {
        size_t m = hi - lo, k = 1;
        while (k < m)
            k <<= 1;                 /* smallest power of two >= m */
        mid = lo + (k >> 1);         /* m >= 2 here, so k >= 2 */
    }

    if (cft_sf_reduce(f, op, rnd, a, b, esz, lo, mid, &left, &lf))
        return 1;
    if (cft_sf_reduce(f, op, rnd, a, b, esz, mid, hi, &right, &rf))
        return 1;

    /* ADD reads a and c - b is steered to 1.0 - so the two addends go
     * in the first and THIRD slots. Passing them as a and b would
     * silently compute a*1.0 + 0.0 and drop the right subtree. */
    cft_bn_zero(&dummy);
    if (cft_sf_compute(f, CFT_SF_ADD, rnd, &left, &dummy, &right, out, &af))
        return 1;

    *flags = lf | rf | af;
    return 0;
}

int cft_sf_compute(const cft_fmt_desc *f, int op, int rnd,
                   const cft_bn *a, const cft_bn *b, const cft_bn *c,
                   cft_bn *out, uint32_t *flags)
{
    *flags = 0;
    switch (op) {
    case CFT_SF_FMA:
    case CFT_SF_ADD:
    case CFT_SF_SUB:
    case CFT_SF_MUL: {
        cft_bn sa, sb, sc;
        if (sf_steer(f, op, a, b, c, &sa, &sb, &sc))
            return 1;
        return sf_fma(f, &sa, &sb, &sc, rnd, out, flags);
    }
    case CFT_SF_ABS:
        sf_magnitude(f, a, out);
        return 0;
    case CFT_SF_NEG:
        cft_bn_copy(out, a);
        if (cft_bn_bit(a, f->width - 1))
            cft_bn_clearbit(out, f->width - 1);
        else
            cft_bn_setbit(out, f->width - 1);
        return 0;
    case CFT_SF_COPYSIGN:
        sf_magnitude(f, a, out);
        if (cft_bn_bit(b, f->width - 1))
            cft_bn_setbit(out, f->width - 1);
        return 0;
    case CFT_SF_MIN:    sf_minmax(f, a, b, 0, 0, out, flags); return 0;
    case CFT_SF_MAX:    sf_minmax(f, a, b, 1, 0, out, flags); return 0;
    case CFT_SF_MINNUM: sf_minmax(f, a, b, 0, 1, out, flags); return 0;
    case CFT_SF_MAXNUM: sf_minmax(f, a, b, 1, 1, out, flags); return 0;
    case CFT_SF_SELECT: {
        /* d = (c is not zero) ? a : b. Inspects nothing but c's
         * magnitude, so it moves NaNs and infinities intact. */
        cft_bn mc;
        sf_magnitude(f, c, &mc);
        cft_bn_copy(out, cft_bn_is_zero(&mc) ? b : a);
        return 0;
    }
    case CFT_SF_CMPLT:
    case CFT_SF_CMPLE:
    case CFT_SF_CMPEQ:
        sf_compare(f, a, b, op, out, flags);
        return 0;
    case CFT_SF_IAND:
    case CFT_SF_IOR:
    case CFT_SF_IXOR:
    case CFT_SF_IADD:
    case CFT_SF_ISUB:
    case CFT_SF_ISHL:
    case CFT_SF_ISHR:
    case CFT_SF_ICMPLT:
        return sf_integer_op(f, op, a, b, out);
    case CFT_SF_RECIP_SEED:
        return sf_recip_seed(f, a, out);
    case CFT_SF_RSQRT_SEED:
        return sf_rsqrt_seed(f, a, out);
    default:
        /* Unassigned. A defined result, not an exception: the device
         * answers the same way, so a host issuing an opcode its
         * bitstream predates sees it in the flags rather than
         * receiving a plausible number. */
        sf_qnan(f, out);
        *flags = CFT_SF_INVALID;
        return 0;
    }
}

/* ---- canonical tile ranges ---------------------------------------- */

size_t cft_sf_canonical_ranges(size_t n, size_t parts,
                               size_t *lo_out, size_t *hi_out, size_t cap)
{
    size_t count, i, k;

    if (n == 0 || parts == 0 || cap == 0)
        return 0;
    /* Only a power of two corresponds to a clean cut of whole levels. */
    if (parts & (parts - 1))
        return 0;

    lo_out[0] = 0;
    hi_out[0] = n;
    count = 1;

    while (count < parts) {
        size_t next = count;
        /* Capacity is decided BEFORE the pass, never during it. A pass
         * splits every range it can, so it may double the count; a
         * check inside the loop that bailed out partway left the array
         * half-updated - some ranges split, some not - and the result
         * no longer tiled [0, n). It reported a plausible smaller
         * partition covering only part of the array, which is the worst
         * shape a bug like this could take. */
        if (count > cap / 2)
            break;
        /* Split every range once; walk backwards so an in-place
         * expansion never overwrites a range it has not read. */
        for (i = count; i-- > 0; ) {
            size_t lo = lo_out[i], hi = hi_out[i], m = hi - lo, half;
            if (m < 2)
                continue;
            /* the same split() the tree uses: largest power of two
             * strictly inside the range */
            half = 1;
            while (half < m)
                half <<= 1;
            half >>= 1;
            /* shift the tail up by one to make room for the right half */
            for (k = next; k > i + 1; k--) {
                lo_out[k] = lo_out[k - 1];
                hi_out[k] = hi_out[k - 1];
            }
            hi_out[i]     = lo + half;
            lo_out[i + 1] = lo + half;
            hi_out[i + 1] = hi;
            next++;
        }
        if (next == count)
            break;                 /* every range is a single element */
        count = next;
    }
    return count;
}

/* ---- exposure for the library's own compositions -------------------
 *
 * divsqrt.c rounds and builds specials through these rather than
 * through copies, so there is exactly one round_pack in the library -
 * the same single-authority rule the model follows. The statics stay
 * static; these are the only doors.
 */

int cft_sf_round_pack(const cft_fmt_desc *f, int sign, const cft_bn *m,
                      int e, int sticky, int rnd,
                      cft_bn *out, uint32_t *flags)
{
    return sf_round_pack(f, sign, m, e, sticky, rnd, out, flags);
}

void cft_sf_qnan(const cft_fmt_desc *f, cft_bn *out) { sf_qnan(f, out); }

void cft_sf_inf(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    sf_inf(f, sign, out);
}

void cft_sf_zero(const cft_fmt_desc *f, int sign, cft_bn *out)
{
    sf_zero(f, sign, out);
}
