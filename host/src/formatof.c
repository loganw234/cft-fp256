/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The formatOf arithmetic operations, IEEE 754-2019 clause 5.4.1:
 * addition, subtraction, multiplication, division, squareRoot and
 * fusedMultiplyAdd with the operands in one binary format and the
 * result in another, rounded once.
 *
 * python/cft_golden/formatof.py defines every result here; this is its
 * port, and "port" means what it means in softfloat.c and augmented.c -
 * the control flow, the order of the special cases and the names are
 * deliberately the same, so the two read side by side and a divergence
 * shows up as a structural difference rather than a subtle one.
 *
 * ----------------------------------------------------------------
 * TWO ROUTES, AND THE LINE BETWEEN THEM
 * ----------------------------------------------------------------
 *
 * dfmt NOT NARROWER THAN sfmt (which includes sfmt == dfmt): widen the
 * operands exactly with cft_convert and issue the existing same-format
 * operation. The interchange ladder nests, so widening rounds nothing
 * and the operation's own rounding is still the only one; the point of
 * going this way rather than computing on the host is that a device
 * backend then still runs the arithmetic on the tile, and bus_out
 * carries the pass's fault word.
 *
 * dfmt NARROWER: form the exact result here and round it ONCE against
 * the destination's descriptor through cft_sf_round_pack - the one
 * rounding seam this library has. No tile pass, bus_out reads 0.
 *
 * ----------------------------------------------------------------
 * WHY DIVISION AND SQUARE ROOT ARE NOT DOUBLE ROUNDED
 * ----------------------------------------------------------------
 *
 * The tempting shortcut in the narrowing direction is to call the
 * library's own correctly-rounded cft_div / cft_sqrt in sfmt and
 * convert the answer down - two roundings, and a device pass for the
 * first. docs/COMPLIANCE.md proposed exactly that, on the strength of
 * the standard result that double rounding through an intermediate of
 * at least 2p + 2 bits is innocuous for the basic operations: this
 * ladder satisfies 53 >= 2*24 + 2, 113 >= 2*53 + 2 and 237 >= 2*113 + 2.
 *
 * IT IS WRONG HERE, and the reason is a hypothesis, not a margin. That
 * theorem is about operands carrying the DESTINATION's precision p; its
 * engine is the bound that a quotient of two p-bit values cannot come
 * within 2^-(2p+2) of a p-bit midpoint without landing on it. Our
 * operands carry the SOURCE's precision, and that bound says nothing
 * about them. Concretely, for binary64 -> binary32 (ps = 53, pd = 24):
 *
 *   let m = 1 + 2^-24, the midpoint between 1 and 1 + 2^-23, whose
 *   lower neighbour is the even one;
 *   let y = 1 + (2^29 - 1) * 2^-52, a binary64 value chosen so that
 *   the exact product m*y misses the binary64 grid by exactly one unit
 *   in the last place of that exact product;
 *   let x be the binary64 value one such unit ABOVE m*y.
 *
 * Then x / y = m + 2^-76 / y - strictly above the destination midpoint,
 * so the correct binary32 result is 1 + 2^-23. Round to binary64 first
 * and the excess (about 2^-76) vanishes under a half-ulp of 2^-53: the
 * intermediate is exactly m, the second rounding sees a tie, breaks it
 * to even, and delivers 1.0. One ulp low, silently, with the same flag
 * word. The same construction works for every ordered pair on this
 * ladder, and squareRoot has its own version of it (the source value
 * one ulp above m*m has a root a quarter of an intermediate ulp above
 * m). python/cft_golden/formatof.py's double_rounding_witness() builds
 * all of them from the format descriptors and python/tests/
 * test_formatof.py runs the eighteen.
 *
 * Fused multiply-add is the case no intermediate width can rescue -
 * the product IS the destination midpoint and the addend is a free
 * choice of source value, so it can always be put below the
 * intermediate's half-ulp - and that is the case COMPLIANCE.md already
 * knew about. What this file adds is that division and square root are
 * in the same family, so all six narrow the exact way.
 *
 * That is why bigint.h's repertoire is not enough on its own: exact
 * narrowing division needs a quotient and exact narrowing square root
 * needs an integer root, and neither is something the same-format
 * library ever had to compute (cft_div and cft_sqrt reach their answers
 * by Newton refinement on the tile). Both live below as static
 * helpers - restoring division and the digit-by-digit root, each the
 * textbook shift-and-subtract, each obviously exact and neither on any
 * hot path - rather than in bigint.c, because nothing else here needs
 * them.
 *
 * ----------------------------------------------------------------
 * THE ALIGNMENT BOUND, RESTATED FOR TWO FORMATS
 * ----------------------------------------------------------------
 *
 * softfloat.c's FMA bounds the operand alignment at FAR = 2p + 4 and
 * argues it against one precision. Here there are two, and the bound
 * has to serve both: the far operand must fall entirely below the near
 * one's last computed bit, and that last bit is placed for the
 * DESTINATION's round_pack, which needs more than p_d significant bits
 * whenever a sticky accompanies them.
 *
 * Write the larger term as bm * 2^be with L = bitlen(bm), shift it up
 * by k = max(2, p_d + 2 - L), and let the smaller term have value
 * exponent at least FAR + 1 below the larger's. The smaller term is
 * then under 2^(VEbig - FAR), and it lies below the shifted term's LSB
 * exactly when FAR >= L - 1 + k:
 *
 *   product larger:  L <= 2 p_s. If p_d + 2 - L <= 2 then k = 2 and the
 *                    requirement is FAR >= L + 1, at most 2 p_s + 1;
 *                    otherwise k = p_d + 2 - L and it is FAR >= p_d + 1.
 *   addend larger:   L <= p_s, so the same two cases give FAR >= p_s + 1
 *                    and FAR >= p_d + 1.
 *
 * FAR = 2 p_s + p_d + 4 clears every one of them. The NEAR case is then
 * computed exactly, and its widest intermediate is at most
 * FAR + 2 p_s + 1 = 4 p_s + p_d + 5 bits - 1,066 for binary256 into
 * binary128, inside CFT_BN_BITS with room to spare.
 *
 * Every shift here is checked, so a violated bound returns
 * CFT_ERR_INTERNAL rather than a wrong answer.
 *
 * host/tests/formatof_check.py drives this file against the model over
 * every ordered pair, every operation and every attribute, and the
 * published <sfmt>-to-<dfmt>-formatof[-<rnd>].jsonl sets replay it.
 */

#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

/* ---- the six operations, internal numbering ----------------------- *
 *
 * NOT cft_op numbers, deliberately: two of these six have no opcode and
 * never will, because division and square root are compositions here
 * rather than tile instructions. See cft.h's block for why the API is
 * six entry points instead of one dispatcher over an opcode. */
#define FO_ADD  0
#define FO_SUB  1
#define FO_MUL  2
#define FO_DIV  3
#define FO_SQRT 4
#define FO_FMA  5

/* ---- lane accessors and classification (augmented.c's, restated) --- */

static void fo_load(const cft_fmt_desc *f, const uint8_t *buf, size_t i,
                    cft_bn *v)
{
    cft_bn_load(v, buf + i * (size_t)(f->width / 8), f->width / 8);
}

static void fo_store(const cft_fmt_desc *f, uint8_t *buf, size_t i,
                     const cft_bn *v)
{
    cft_bn_store(v, buf + i * (size_t)(f->width / 8), f->width / 8);
}

#define FK_ZERO 0
#define FK_SUB  1
#define FK_NORM 2
#define FK_INF  3
#define FK_NAN  4

typedef struct {
    int    kind;
    int    sign;
    int    signaling;
    cft_bn m;        /* integer significand; value = (-1)^sign * m * 2^e */
    int    e;
} fo_unp;

static void fo_unpack(const cft_fmt_desc *f, const cft_bn *x, fo_unp *u)
{
    uint32_t ef = cft_bn_extract(x, f->man_w, f->exp_w);
    u->sign = cft_bn_bit(x, f->width - 1);
    u->signaling = 0;
    u->e = 0;
    cft_bn_copy(&u->m, x);
    cft_bn_mask(&u->m, f->man_w);
    if (ef == f->exp_mask) {
        if (cft_bn_is_zero(&u->m)) {
            u->kind = FK_INF;
        } else {
            u->kind = FK_NAN;
            u->signaling = !cft_bn_bit(x, f->man_w - 1);
        }
        cft_bn_zero(&u->m);
        return;
    }
    if (ef == 0) {
        if (cft_bn_is_zero(&u->m)) {
            u->kind = FK_ZERO;
            return;
        }
        u->kind = FK_SUB;
        u->e = f->emin - f->man_w;
        return;
    }
    u->kind = FK_NORM;
    cft_bn_setbit(&u->m, f->man_w);
    u->e = (int)ef - f->bias - f->man_w;
}

/* 754 6.3: an exact zero sum of oppositely-signed operands is +0 in
 * every attribute except roundTowardNegative. softfloat.c's rule,
 * restated here rather than exported, so this file adds nothing to the
 * seam it shares. */
static int fo_cancel_zero_sign(int rnd)
{
    return rnd == CFT_SF_RDN ? 1 : 0;
}

static void fo_nan_out(const cft_fmt_desc *g, const fo_unp *ua,
                       const fo_unp *ub, const fo_unp *uc,
                       cft_bn *out, uint32_t *flags)
{
    int inv = (ua->kind == FK_NAN && ua->signaling) ||
              (ub != 0 && ub->kind == FK_NAN && ub->signaling) ||
              (uc != 0 && uc->kind == FK_NAN && uc->signaling);
    cft_sf_qnan(g, out);                    /* canonical, in the DEST */
    *flags = inv ? CFT_SF_INVALID : 0u;
}

/* The destination's rounding of one finite operand's exact value - the
 * tail of every "the answer is one of the operands, exactly" case.
 *
 * In the same-format operations those cases return the operand's own
 * encoding (softfloat.c's `cft_bn_copy(out, xc)` for 0*b + c). Here the
 * value is exact but the destination may not hold it, so the single
 * rounding still has to happen and still has to report its flags. */
static int fo_pack_operand(const cft_fmt_desc *g, const fo_unp *u, int rnd,
                           cft_bn *out, uint32_t *flags)
{
    if (u->kind == FK_ZERO) {
        cft_sf_zero(g, u->sign, out);
        *flags = 0;
        return 0;
    }
    return cft_sf_round_pack(g, u->sign, &u->m, u->e, 0, rnd, out, flags);
}

/* ---- exact bignum division and square root ------------------------ *
 *
 * Both are the textbook shift-and-subtract, chosen over anything
 * cleverer because they are obviously exact and neither is on a hot
 * path: one call per element, a few hundred iterations of work over a
 * few dozen limbs. Neither belongs in bigint.c - nothing else in this
 * library divides or takes a root of a bignum, because cft_div and
 * cft_sqrt reach their answers by Newton refinement instead.
 */

/* q = floor(num / den), *rem_nz = (num mod den) != 0. den must be
 * non-zero. Returns 0, or 1 if an intermediate would not fit. */
static int fo_divmod(cft_bn *q, int *rem_nz, const cft_bn *num,
                     const cft_bn *den)
{
    cft_bn rem, shifted;
    int i, L = cft_bn_bitlen(num);

    cft_bn_zero(q);
    cft_bn_zero(&rem);
    for (i = L - 1; i >= 0; i--) {
        if (cft_bn_shl(&shifted, &rem, 1))
            return 1;
        if (cft_bn_bit(num, i))
            cft_bn_setbit(&shifted, 0);
        if (cft_bn_cmp(&shifted, den) >= 0) {
            cft_bn_sub(&rem, &shifted, den);
            cft_bn_setbit(q, i);
        } else {
            cft_bn_copy(&rem, &shifted);
        }
    }
    *rem_nz = !cft_bn_is_zero(&rem);
    return 0;
}

/* root = floor(sqrt(n)), *rem_nz = (n - root^2) != 0. n must be
 * non-zero. The classic digit-by-digit method: `bit` walks the powers
 * of four downward and each step asks whether the next root digit is a
 * one, which is one comparison and one subtraction - so no
 * multiplication is ever formed, not even to test the remainder. */
static int fo_isqrt(cft_bn *root, int *rem_nz, const cft_bn *n)
{
    cft_bn num, res, bit, t;
    int L = cft_bn_bitlen(n);

    cft_bn_copy(&num, n);
    cft_bn_zero(&res);
    cft_bn_zero(&bit);
    cft_bn_setbit(&bit, 2 * ((L - 1) / 2));
    while (!cft_bn_is_zero(&bit)) {
        if (cft_bn_add(&t, &res, &bit))
            return 1;
        cft_bn_shr(&res, &res, 1);
        if (cft_bn_cmp(&num, &t) >= 0) {
            cft_bn_sub(&num, &num, &t);
            if (cft_bn_add(&res, &res, &bit))
                return 1;
        }
        cft_bn_shr(&bit, &bit, 2);
    }
    cft_bn_copy(root, &res);
    *rem_nz = !cft_bn_is_zero(&num);
    return 0;
}

/* ---- one lane, wide source into narrow destination ---------------- */

/* fusedMultiplyAdd, and - through the operand steering below - addition,
 * subtraction and multiplication too. f is the source, g the
 * destination. */
static int fo_fma_lane(const cft_fmt_desc *f, const cft_fmt_desc *g,
                       const cft_bn *xa, const cft_bn *xb, const cft_bn *xc,
                       int rnd, cft_bn *out, uint32_t *flags)
{
    fo_unp ua, ub, uc;
    cft_bn mp, tp, tc, t;
    int sp, ep, Lp, Lc, VEp, VEc, FAR, e0;

    fo_unpack(f, xa, &ua);
    fo_unpack(f, xb, &ub);
    fo_unpack(f, xc, &uc);
    *flags = 0;

    if (ua.kind == FK_NAN || ub.kind == FK_NAN || uc.kind == FK_NAN) {
        fo_nan_out(g, &ua, &ub, &uc, out, flags);
        return 0;
    }

    sp = ua.sign ^ ub.sign;

    if (ua.kind == FK_INF || ub.kind == FK_INF) {
        if (ua.kind == FK_ZERO || ub.kind == FK_ZERO) {
            cft_sf_qnan(g, out);                    /* inf * 0 */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        if (uc.kind == FK_INF && uc.sign != sp) {
            cft_sf_qnan(g, out);                    /* inf - inf */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        cft_sf_inf(g, sp, out);
        return 0;
    }
    if (uc.kind == FK_INF) {
        cft_sf_inf(g, uc.sign, out);
        return 0;
    }

    if (ua.kind == FK_ZERO || ub.kind == FK_ZERO) {
        if (uc.kind == FK_ZERO) {
            int rs = (uc.sign == sp) ? uc.sign : fo_cancel_zero_sign(rnd);
            cft_sf_zero(g, rs, out);
            return 0;
        }
        /* 0*b + c is c exactly - but c is a SOURCE value and g may not
         * hold it, so this rounds where the same-format path copies. */
        return fo_pack_operand(g, &uc, rnd, out, flags);
    }

    if (cft_bn_mul(&mp, &ua.m, &ub.m))              /* exact, 2p_s bits */
        return 1;
    ep = ua.e + ub.e;

    if (uc.kind == FK_ZERO)
        return cft_sf_round_pack(g, sp, &mp, ep, 0, rnd, out, flags);

    Lp  = cft_bn_bitlen(&mp);
    Lc  = cft_bn_bitlen(&uc.m);
    VEp = ep + Lp - 1;
    VEc = uc.e + Lc - 1;
    FAR = 2 * f->prec + g->prec + 4;                /* see the banner */

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
        k = g->prec + 2 - L;                        /* the DESTINATION's */
        if (k < 2)
            k = 2;
        if (cft_bn_shl(&m, bm, k))
            return 1;
        if (osign != bsign)
            cft_bn_dec(&m);
        return cft_sf_round_pack(g, bsign, &m, be - k, 1, rnd, out, flags);
    }

    e0 = ep < uc.e ? ep : uc.e;
    if (cft_bn_shl(&tp, &mp, ep - e0))
        return 1;
    if (cft_bn_shl(&tc, &uc.m, uc.e - e0))
        return 1;

    if (sp == uc.sign) {
        if (cft_bn_add(&t, &tp, &tc))
            return 1;
        return cft_sf_round_pack(g, sp, &t, e0, 0, rnd, out, flags);
    }
    {
        int c = cft_bn_cmp(&tp, &tc);
        if (c == 0) {
            cft_sf_zero(g, fo_cancel_zero_sign(rnd), out);
            return 0;
        }
        if (c > 0) {
            cft_bn_sub(&t, &tp, &tc);
            return cft_sf_round_pack(g, sp, &t, e0, 0, rnd, out, flags);
        }
        cft_bn_sub(&t, &tc, &tp);
        return cft_sf_round_pack(g, uc.sign, &t, e0, 0, rnd, out, flags);
    }
}

/* One lane of division. The model's construction with the DESTINATION's
 * precision in place of the single format's: carry the quotient to at
 * least p_d + 3 bits and let round_pack's own sticky argument stand for
 * everything below the last computed bit.
 *
 * x / y = (ua.m / ub.m) * 2^(ua.e - ub.e)
 *       = (q + rem/ub.m) * 2^(ua.e - ub.e - k)
 *
 * with q = floor((ua.m << k) / ub.m), so the pair (q, rem != 0) is
 * exactly round_pack's (m + eps) * 2^e form and the fraction eps is the
 * true one rather than a folded marker. q carries at least p_d + 3 bits,
 * which is round_pack's precondition for a sticky. */
static int fo_div_lane(const cft_fmt_desc *f, const cft_fmt_desc *g,
                       const cft_bn *xa, const cft_bn *xb, int rnd,
                       cft_bn *out, uint32_t *flags)
{
    fo_unp ua, ub;
    cft_bn num, q;
    int sq, k, rem_nz;

    fo_unpack(f, xa, &ua);
    fo_unpack(f, xb, &ub);
    *flags = 0;

    if (ua.kind == FK_NAN || ub.kind == FK_NAN) {
        fo_nan_out(g, &ua, &ub, 0, out, flags);
        return 0;
    }
    sq = ua.sign ^ ub.sign;

    if (ua.kind == FK_INF) {
        if (ub.kind == FK_INF) {
            cft_sf_qnan(g, out);                    /* inf / inf */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        cft_sf_inf(g, sq, out);
        return 0;
    }
    if (ub.kind == FK_INF) {
        cft_sf_zero(g, sq, out);
        return 0;
    }
    if (ub.kind == FK_ZERO) {
        if (ua.kind == FK_ZERO) {
            cft_sf_qnan(g, out);                    /* 0 / 0 */
            *flags = CFT_SF_INVALID;
            return 0;
        }
        cft_sf_inf(g, sq, out);                     /* x / 0 */
        *flags = CFT_SF_DIVZERO;
        return 0;
    }
    if (ua.kind == FK_ZERO) {
        cft_sf_zero(g, sq, out);
        return 0;
    }

    k = (g->prec + 3) + cft_bn_bitlen(&ub.m) - cft_bn_bitlen(&ua.m) + 1;
    if (k < 0)
        k = 0;
    if (cft_bn_shl(&num, &ua.m, k))
        return 1;
    if (fo_divmod(&q, &rem_nz, &num, &ub.m))
        return 1;
    if (cft_bn_bitlen(&q) < g->prec + 3)
        return 1;                    /* the quotient-length invariant */
    return cft_sf_round_pack(g, sq, &q, (ua.e - ub.e) - k, rem_nz, rnd,
                             out, flags);
}

/* One lane of square root. The model's construction with the
 * DESTINATION's precision:
 *
 *   sqrt(m * 2^e) = (r + frac) * 2^(e/2)   with r = floor(sqrt(m))
 *
 * once e has been made even by shifting m up, and frac is non-zero
 * exactly when r*r != m - which is round_pack's sticky. r carries at
 * least p_d + 3 bits, the precondition for one.
 *
 * Unlike the same-format square root, this one CAN overflow and CAN
 * underflow: the root of the largest binary256 is about 2^131071, far
 * above binary32's emax, and the root of its smallest subnormal is
 * about 2^-131189, far below binary32's subnormal floor. round_pack
 * raises both, which is why nothing here special-cases them. */
static int fo_sqrt_lane(const cft_fmt_desc *f, const cft_fmt_desc *g,
                        const cft_bn *xa, int rnd,
                        cft_bn *out, uint32_t *flags)
{
    fo_unp ua;
    cft_bn m, r;
    int e, t, epar, rem_nz;

    fo_unpack(f, xa, &ua);
    *flags = 0;

    if (ua.kind == FK_NAN) {
        fo_nan_out(g, &ua, 0, 0, out, flags);
        return 0;
    }
    if (ua.kind == FK_ZERO) {
        cft_sf_zero(g, ua.sign, out);               /* sqrt(+/-0) */
        return 0;
    }
    if (ua.sign) {
        cft_sf_qnan(g, out);                        /* negative, -inf too */
        *flags = CFT_SF_INVALID;
        return 0;
    }
    if (ua.kind == FK_INF) {
        cft_sf_inf(g, 0, out);
        return 0;
    }

    e = ua.e;
    t = 2 * (g->prec + 3) - cft_bn_bitlen(&ua.m);
    if (t < 0)
        t = 0;
    /* keep e - t even. (e % 2) != 0 is the parity of a possibly
     * negative exponent without relying on the sign of the remainder. */
    epar = ((e % 2) != 0) ? 1 : 0;
    if ((t & 1) != epar)
        t++;
    if (cft_bn_shl(&m, &ua.m, t))
        return 1;
    e -= t;
    if ((e % 2) != 0)
        return 1;                                   /* the parity invariant */
    if (fo_isqrt(&r, &rem_nz, &m))
        return 1;
    if (cft_bn_bitlen(&r) < g->prec + 3)
        return 1;                                   /* the root-length one */
    return cft_sf_round_pack(g, 0, &r, e / 2, rem_nz, rnd, out, flags);
}

/* ---- operand steering, for the narrowing route -------------------- *
 *
 * ADD, SUB and MUL are the one fused multiply-add with the operands
 * steered, exactly as softfloat.c's sf_steer does it and for the same
 * reason: one implementation of "the exact result" rather than four, so
 * the quirks of realising a + c as a * 1.0 + c are the same quirks
 * everywhere. The steering happens in the SOURCE format, where the
 * operands live - the constants it builds are source values.
 */
static void fo_one(const cft_fmt_desc *f, cft_bn *out)
{
    int i;
    cft_bn_zero(out);
    for (i = 0; i < f->exp_w; i++)
        if ((((uint32_t)f->bias) >> i) & 1u)
            cft_bn_setbit(out, f->man_w + i);
}

static int fo_narrow_lane(const cft_fmt_desc *f, const cft_fmt_desc *g,
                          int op, const cft_bn *xa, const cft_bn *xb,
                          const cft_bn *xc, int rnd,
                          cft_bn *out, uint32_t *flags)
{
    cft_bn rb, rc;

    switch (op) {
    case FO_FMA:
        return fo_fma_lane(f, g, xa, xb, xc, rnd, out, flags);
    case FO_DIV:
        return fo_div_lane(f, g, xa, xb, rnd, out, flags);
    case FO_SQRT:
        return fo_sqrt_lane(f, g, xa, rnd, out, flags);
    case FO_ADD:
        fo_one(f, &rb);
        return fo_fma_lane(f, g, xa, &rb, xb, rnd, out, flags);
    case FO_SUB:
        fo_one(f, &rb);
        cft_bn_copy(&rc, xb);
        if (cft_bn_bit(&rc, f->width - 1))
            cft_bn_clearbit(&rc, f->width - 1);
        else
            cft_bn_setbit(&rc, f->width - 1);
        return fo_fma_lane(f, g, xa, &rb, &rc, rnd, out, flags);
    default:                                        /* FO_MUL */
        cft_sf_zero(f, cft_bn_bit(xa, f->width - 1) ^
                       cft_bn_bit(xb, f->width - 1), &rc);
        return fo_fma_lane(f, g, xa, xb, &rc, rnd, out, flags);
    }
}

/* ---- the widening route ------------------------------------------- *
 *
 * Convert the operands into the destination - exact, because the ladder
 * nests - and issue the existing same-format operation, so a device
 * backend runs the arithmetic on the tile and reports its bus word. The
 * conversion's only possible flag is the invalid a signaling NaN earns,
 * and the operation then sees a quiet NaN and adds nothing; OR-ing the
 * two words is therefore neither lossy nor double-counting.
 *
 * Chunked so the staging buffers are bounded: 32 elements of the widest
 * format is a kilobyte per operand, which is a stack frame rather than
 * an allocation.
 */
#define FO_CHUNK 32

static cft_status fo_widen_batch(cft_device *dev, int op, cft_format sfmt,
                                 cft_format dfmt, cft_round rnd,
                                 const void *a, const void *b,
                                 const void *c, void *d, size_t n,
                                 uint32_t *acc, uint32_t *bus)
{
    const cft_fmt_desc *f = &cft_sf_formats[(int)sfmt];
    const cft_fmt_desc *g = &cft_sf_formats[(int)dfmt];
    size_t sesz = (size_t)(f->width / 8), desz = (size_t)(g->width / 8);
    uint8_t wa[FO_CHUNK * 32], wb[FO_CHUNK * 32], wc[FO_CHUNK * 32];
    size_t done = 0;

    while (done < n) {
        size_t m = n - done;
        uint32_t fl = 0, bw = 0;
        cft_status st;
        if (m > FO_CHUNK)
            m = FO_CHUNK;

        st = cft_convert(dev, sfmt, dfmt, rnd,
                         (const uint8_t *)a + done * sesz, wa, m, &fl);
        if (st != CFT_OK)
            return st;
        *acc |= fl;
        if (op != FO_SQRT) {
            fl = 0;
            st = cft_convert(dev, sfmt, dfmt, rnd,
                             (const uint8_t *)b + done * sesz, wb, m, &fl);
            if (st != CFT_OK)
                return st;
            *acc |= fl;
        }
        if (op == FO_FMA) {
            fl = 0;
            st = cft_convert(dev, sfmt, dfmt, rnd,
                             (const uint8_t *)c + done * sesz, wc, m, &fl);
            if (st != CFT_OK)
                return st;
            *acc |= fl;
        }

        fl = 0;
        switch (op) {
        case FO_ADD:
            st = cft_run(dev, CFT_ADD, dfmt, rnd, wa, NULL, wb,
                         (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        case FO_SUB:
            st = cft_run(dev, CFT_SUB, dfmt, rnd, wa, NULL, wb,
                         (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        case FO_MUL:
            st = cft_run(dev, CFT_MUL, dfmt, rnd, wa, wb, NULL,
                         (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        case FO_FMA:
            st = cft_run(dev, CFT_FMA, dfmt, rnd, wa, wb, wc,
                         (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        case FO_DIV:
            st = cft_div(dev, dfmt, rnd, wa, wb,
                         (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        default:
            st = cft_sqrt(dev, dfmt, rnd, wa,
                          (uint8_t *)d + done * desz, m, &fl, &bw);
            break;
        }
        if (st != CFT_OK) {
            if (bus)
                *bus |= bw;
            return st;
        }
        *acc |= fl;
        if (bus)
            *bus |= bw;
        done += m;
    }
    return CFT_OK;
}

/* ---- validation, dispatch and the entry points -------------------- */

static int fo_fmt_ok(cft_format f)
{
    return (int)f >= 0 && (int)f <= 3;
}

static cft_status fo_validate(cft_device *dev, int op, cft_format sfmt,
                              cft_format dfmt, cft_round rnd,
                              const void *a, const void *b, const void *c,
                              const void *d, size_t n)
{
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!fo_fmt_ok(sfmt) || !fo_fmt_ok(dfmt))
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0)
        return CFT_OK;
    if (!a || !d)
        return CFT_ERR_INVALID_ARGUMENT;
    if (op != FO_SQRT && !b)
        return CFT_ERR_INVALID_ARGUMENT;
    if (op == FO_FMA && !c)
        return CFT_ERR_INVALID_ARGUMENT;
    return CFT_OK;
}

/* The one place every formatOf call's flag word becomes final.
 *
 * All six entry points are one line each into this function, and the
 * single cft_flags_emit() below is the point at which the batch's
 * exception group is complete: it writes flags_out and ORs the same
 * word into the device's sticky status word (754-2019 7.1), which is
 * why no raw `*flags_out =` survives anywhere in this file.
 *
 * The widening route's passes run MUTED. Every cft_convert, cft_run,
 * cft_div and cft_sqrt it issues is internal to one formatOf
 * operation - the same relationship divsqrt.c's Newton steps have to
 * cft_div - so their flags reach this function through their own
 * flags_out, are accumulated here, and reach the status word exactly
 * once, through the emit below. Without the mute a single
 * formatOf-division would OR its scaffolding into the word twice and,
 * worse, the widening cft_convert of a signaling NaN would put invalid
 * there on its own account rather than as part of the operation. */
static cft_status fo_batch(cft_device *dev, int op, cft_format sfmt,
                           cft_format dfmt, cft_round rnd, const void *a,
                           const void *b, const void *c, void *d, size_t n,
                           uint32_t *flags_out, uint32_t *bus_out)
{
    const cft_fmt_desc *f, *g;
    uint32_t acc = 0, bus = 0;
    cft_status st = fo_validate(dev, op, sfmt, dfmt, rnd, a, b, c, d, n);

    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        if (bus_out)
            *bus_out = 0;
        return CFT_OK;
    }

    f = &cft_sf_formats[(int)sfmt];
    g = &cft_sf_formats[(int)dfmt];
    if (n > ((size_t)-1) / (size_t)(f->width / 8) ||
        n > ((size_t)-1) / (size_t)(g->width / 8))
        return CFT_ERR_INVALID_ARGUMENT;

    if (g->prec >= f->prec) {
        /* Not narrower: widen exactly and issue the existing operation,
         * so a device backend still runs it on the tile. Muted, because
         * every pass it issues is internal to THIS operation - see the
         * banner above and the composition discipline in softfloat.h. */
        const int muted = cft_flags_mute(dev, 1);
        st = fo_widen_batch(dev, op, sfmt, dfmt, rnd, a, b, c, d, n,
                            &acc, &bus);
        (void)cft_flags_mute(dev, muted);
        if (st != CFT_OK) {
            if (bus_out)
                *bus_out = bus;
            return st;
        }
    } else {
        size_t i;
        for (i = 0; i < n; i++) {
            cft_bn xa, xb, xc, v;
            uint32_t fl = 0;
            fo_load(f, (const uint8_t *)a, i, &xa);
            if (op != FO_SQRT)
                fo_load(f, (const uint8_t *)b, i, &xb);
            else
                cft_bn_zero(&xb);
            if (op == FO_FMA)
                fo_load(f, (const uint8_t *)c, i, &xc);
            else
                cft_bn_zero(&xc);
            if (fo_narrow_lane(f, g, op, &xa, &xb, &xc, (int)rnd, &v, &fl))
                return CFT_ERR_INTERNAL;
            acc |= fl;
            fo_store(g, (uint8_t *)d, i, &v);
        }
    }

    /* <- the call's flag word is final: flags_out and 7.1's word, once */
    cft_flags_emit(dev, acc, flags_out);
    if (bus_out)
        *bus_out = bus;
    return CFT_OK;
}

CFT_API cft_status cft_formatof_add(cft_device *dev, cft_format sfmt,
                                    cft_format dfmt, cft_round rnd,
                                    const void *a, const void *b, void *d,
                                    size_t n, uint32_t *flags_out,
                                    uint32_t *bus_out)
{
    return fo_batch(dev, FO_ADD, sfmt, dfmt, rnd, a, b, NULL, d, n,
                    flags_out, bus_out);
}

CFT_API cft_status cft_formatof_sub(cft_device *dev, cft_format sfmt,
                                    cft_format dfmt, cft_round rnd,
                                    const void *a, const void *b, void *d,
                                    size_t n, uint32_t *flags_out,
                                    uint32_t *bus_out)
{
    return fo_batch(dev, FO_SUB, sfmt, dfmt, rnd, a, b, NULL, d, n,
                    flags_out, bus_out);
}

CFT_API cft_status cft_formatof_mul(cft_device *dev, cft_format sfmt,
                                    cft_format dfmt, cft_round rnd,
                                    const void *a, const void *b, void *d,
                                    size_t n, uint32_t *flags_out,
                                    uint32_t *bus_out)
{
    return fo_batch(dev, FO_MUL, sfmt, dfmt, rnd, a, b, NULL, d, n,
                    flags_out, bus_out);
}

CFT_API cft_status cft_formatof_div(cft_device *dev, cft_format sfmt,
                                    cft_format dfmt, cft_round rnd,
                                    const void *a, const void *b, void *d,
                                    size_t n, uint32_t *flags_out,
                                    uint32_t *bus_out)
{
    return fo_batch(dev, FO_DIV, sfmt, dfmt, rnd, a, b, NULL, d, n,
                    flags_out, bus_out);
}

CFT_API cft_status cft_formatof_sqrt(cft_device *dev, cft_format sfmt,
                                     cft_format dfmt, cft_round rnd,
                                     const void *a, void *d,
                                     size_t n, uint32_t *flags_out,
                                     uint32_t *bus_out)
{
    return fo_batch(dev, FO_SQRT, sfmt, dfmt, rnd, a, NULL, NULL, d, n,
                    flags_out, bus_out);
}

CFT_API cft_status cft_formatof_fma(cft_device *dev, cft_format sfmt,
                                    cft_format dfmt, cft_round rnd,
                                    const void *a, const void *b,
                                    const void *c, void *d,
                                    size_t n, uint32_t *flags_out,
                                    uint32_t *bus_out)
{
    return fo_batch(dev, FO_FMA, sfmt, dfmt, rnd, a, b, c, d, n,
                    flags_out, bus_out);
}
