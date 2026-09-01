/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft_div and cft_sqrt: correctly-rounded division and square root,
 * composed from the operations the tile actually has.
 *
 * python/cft_golden/sequences.py is the specification of this file,
 * and the correspondence is deliberately line-for-line: every
 * floating-point step here is one cft_run() over the chunk - the same
 * opcode, operands and rounding attribute as the matching _v() step
 * in the model - and every integer step (classify, centre, the ulp
 * steps of the restore, the final pack) is exact host arithmetic on
 * the encodings. That split is the same division of labour
 * cft_reduce() draws when it folds partial sums on the host: floats
 * on the backend, where a device computes them with the contract's
 * own FMA; integers here, where they are exact by nature. On the
 * software backend the floating steps land in softfloat.c and this
 * file reproduces the contract div/sqrt bit for bit - which
 * test_sequences.py proves of the model sequence, and
 * host/tests/divsqrt_check.py re-proves of this port.
 *
 * The construction (Markstein, with the two rescues the model's test
 * matrix forced - see sequences.py for the failure families):
 *
 *   divide   operands pre-normalised (exact power-of-two multiplies)
 *            and CENTRED so the core quotient lives in (1/2, 2);
 *            reciprocal seed, Newton to full precision, a truncating
 *            (RTZ, tie-free) Markstein finish driven to floor by a
 *            restore step against exact residual signs; then the
 *            guard MEASURED as the sign of one exact fma against the
 *            half-ulp midpoint, the sticky as the remaining
 *            nonzeroness, and one rounding by round_pack - the
 *            library's single rounding authority - at the true scale.
 *
 *   sqrt     the same shape: centred to [1, 4) with the exponent's
 *            parity folded in, rsqrt seed, Newton, floor by restore,
 *            guard from the sign of the exact midpoint discriminant
 *            acen - (s + u/2)^2 evaluated in three exact steps.
 *
 * Flags: each step is its own run and FLAGS is per-run, so the
 * scaffolding steps' flags are DISCARDED - they describe the
 * scaffolding, not the operation. What a caller sees is derived the
 * way the contract derives it: invalid and divideByZero from operand
 * classes, inexact/underflow/overflow from the one real rounding
 * inside round_pack.
 *
 * Work proceeds in bounded chunks so the scratch footprint is fixed
 * (a dozen lane buffers of CHUNK elements) rather than proportional
 * to n. Chunks also keep the aliasing contract: a chunk reads its
 * slice of a and b completely before it writes that slice of d, and
 * later chunks never revisit earlier slices.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

#define CHUNK 4096

/* Newton iteration counts, derived from the proven seed bound 2^-8.5:
 * each step squares the relative error. Keyed by precision. */
static int newton_steps(const cft_fmt_desc *f)
{
    switch (f->prec) {
    case 24:  return 2;
    case 53:  return 3;
    case 113: return 4;
    case 237: return 5;
    }
    return -1;
}

/* ---- lane accessors ----------------------------------------------- */

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

/* The float 2^e as bits. e must be in the normal range - the callers
 * construct e from a centred value's fields, which guarantees it, and
 * the guard turns a broken invariant into a loud internal error
 * rather than a wrong constant. */
static int lane_pow2(const cft_fmt_desc *f, uint8_t *buf, size_t i, int e)
{
    cft_bn v;
    if (e < f->emin || e > f->emax)
        return 1;
    cft_bn_set_u32(&v, (uint32_t)(e + f->bias));
    if (cft_bn_shl(&v, &v, f->man_w))
        return 1;
    lane_store(f, buf, i, &v);
    return 0;
}

/* Fill a whole chunk buffer with one constant value. */
static int fill_const(const cft_fmt_desc *f, uint8_t *buf, size_t n,
                      const cft_bn *v)
{
    size_t i;
    for (i = 0; i < n; i++)
        lane_store(f, buf, i, v);
    return 0;
}

static void bn_one(const cft_fmt_desc *f, cft_bn *v)
{
    cft_bn_zero(v);
    cft_bn_set_u32(v, (uint32_t)f->bias);
    (void)cft_bn_shl(v, v, f->man_w);
}

static void bn_pow2(const cft_fmt_desc *f, int e, cft_bn *v)
{
    cft_bn_zero(v);
    cft_bn_set_u32(v, (uint32_t)(e + f->bias));
    (void)cft_bn_shl(v, v, f->man_w);
}

/* ---- classification ----------------------------------------------- */

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

static void classify(const cft_fmt_desc *f, const cft_bn *x, lane_cls *c)
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

/* Sign bit of the lane, and the exact +/-0 tests the restore and
 * guard logic branch on - all on raw encodings, as the model does. */
static int lane_negbit(const cft_fmt_desc *f, const uint8_t *buf, size_t i)
{
    cft_bn v;
    lane_load(f, buf, i, &v);
    return cft_bn_bit(&v, f->width - 1);
}

static int lane_is_zero_of_sign(const cft_fmt_desc *f, const uint8_t *buf,
                                size_t i, int sign)
{
    cft_bn v;
    lane_load(f, buf, i, &v);
    if (cft_bn_bit(&v, f->width - 1) != sign)
        return 0;
    cft_bn_clearbit(&v, f->width - 1);
    return cft_bn_is_zero(&v);
}

static int lane_mag_zero(const cft_fmt_desc *f, const uint8_t *buf, size_t i)
{
    cft_bn v;
    lane_load(f, buf, i, &v);
    cft_bn_clearbit(&v, f->width - 1);
    return cft_bn_is_zero(&v);
}

/* One ulp step on the encoding, in place. Monotone across binades,
 * which is what makes it the restore step. */
static void lane_step(const cft_fmt_desc *f, uint8_t *buf, size_t i, int up)
{
    cft_bn v;
    lane_load(f, buf, i, &v);
    if (up)
        (void)cft_bn_inc(&v);
    else
        cft_bn_dec(&v);
    lane_store(f, buf, i, &v);
}

/* ---- one sequence step -------------------------------------------- */

/* A scaffolding run: value kept, flags discarded, bus faults fatal. */
static cft_status step(cft_device *dev, cft_op op, cft_format fmt, int rnd,
                       const void *a, const void *b, const void *c, void *d,
                       size_t n, uint32_t *bus_out)
{
    return cft_run(dev, op, fmt, (cft_round)rnd, a, b, c, d, n,
                   NULL, bus_out);
}

/* ---- shared scratch ----------------------------------------------- */

typedef struct {
    uint8_t *b[12];          /* CHUNK lanes each */
    lane_cls *ca, *cb;
    int      *D;             /* per-lane exponent adjustment */
    uint8_t  *core;          /* 1 = takes the composed path */
    uint8_t  *settled;
    uint8_t  *sq;            /* quotient sign */
} scratch;

static void scratch_free(scratch *s)
{
    int i;
    for (i = 0; i < 12; i++)
        free(s->b[i]);
    free(s->ca); free(s->cb); free(s->D);
    free(s->core); free(s->settled); free(s->sq);
    memset(s, 0, sizeof *s);
}

static int scratch_alloc(scratch *s, size_t esz)
{
    int i;
    memset(s, 0, sizeof *s);
    for (i = 0; i < 12; i++) {
        s->b[i] = (uint8_t *)malloc(CHUNK * esz);
        if (!s->b[i])
            goto fail;
    }
    s->ca = (lane_cls *)malloc(CHUNK * sizeof *s->ca);
    s->cb = (lane_cls *)malloc(CHUNK * sizeof *s->cb);
    s->D  = (int *)malloc(CHUNK * sizeof *s->D);
    s->core    = (uint8_t *)malloc(CHUNK);
    s->settled = (uint8_t *)malloc(CHUNK);
    s->sq      = (uint8_t *)malloc(CHUNK);
    if (!s->ca || !s->cb || !s->D || !s->core || !s->settled || !s->sq)
        goto fail;
    return 0;
fail:
    scratch_free(s);
    return 1;
}

/* ---- division ----------------------------------------------------- */

static cft_status div_chunk(cft_device *dev, const cft_fmt_desc *f,
                            cft_format fmt, int rnd,
                            const uint8_t *a, const uint8_t *b, uint8_t *d,
                            size_t n, scratch *s,
                            uint32_t *acc, uint32_t *bus_out)
{
    uint8_t *aw = s->b[0], *bw = s->b[1], *ac = s->b[2], *bc = s->b[3];
    uint8_t *nb = s->b[4], *y  = s->b[5], *t1 = s->b[6], *t2 = s->b[7];
    uint8_t *q2 = s->b[8], *r2 = s->b[9], *pw = s->b[10], *one = s->b[11];
    cft_bn v, w;
    cft_status st;
    size_t i;
    int it, N = newton_steps(f);

    if (N < 0)
        return CFT_ERR_INTERNAL;

    /* Classify; specials answered from operand class, never computed.
     * Core lanes get their pre-normalising power (an exact multiply)
     * staged into pw/one as per-lane constants; special lanes get
     * benign 1.0 operands so the composed steps stay finite, and
     * their results are never read. Each lane's inputs are fully read
     * before its output is written, which is what keeps d free to
     * alias a or b. */
    for (i = 0; i < n; i++) {
        lane_cls *ka = &s->ca[i], *kb = &s->cb[i];
        cft_bn xa, xb;
        lane_load(f, a, i, &xa);
        lane_load(f, b, i, &xb);
        classify(f, &xa, ka);
        classify(f, &xb, kb);
        s->sq[i] = (uint8_t)(ka->sign ^ kb->sign);
        s->core[i] = 0;
        s->settled[i] = 0;
        s->D[i] = 0;

        if (ka->kind == K_NAN || kb->kind == K_NAN) {
            cft_sf_qnan(f, &v);
            if (ka->signaling || kb->signaling)
                *acc |= CFT_SF_INVALID;
        } else if (ka->kind == K_INF) {
            if (kb->kind == K_INF) {
                cft_sf_qnan(f, &v);
                *acc |= CFT_SF_INVALID;
            } else {
                cft_sf_inf(f, s->sq[i], &v);
            }
        } else if (kb->kind == K_INF) {
            cft_sf_zero(f, s->sq[i], &v);
        } else if (kb->kind == K_ZERO) {
            if (ka->kind == K_ZERO) {
                cft_sf_qnan(f, &v);
                *acc |= CFT_SF_INVALID;
            } else {
                cft_sf_inf(f, s->sq[i], &v);
                *acc |= CFT_SF_DIVZERO;
            }
        } else if (ka->kind == K_ZERO) {
            cft_sf_zero(f, s->sq[i], &v);
        } else {
            s->core[i] = 1;
            lane_store(f, aw, i, &xa);
            lane_store(f, bw, i, &xb);
            if (ka->kind == K_SUB) {
                if (lane_pow2(f, pw, i, f->prec))
                    return CFT_ERR_INTERNAL;
                s->D[i] -= f->prec;
            } else {
                bn_one(f, &w);
                lane_store(f, pw, i, &w);
            }
            if (kb->kind == K_SUB) {
                if (lane_pow2(f, one, i, f->prec))
                    return CFT_ERR_INTERNAL;
                s->D[i] += f->prec;
            } else {
                bn_one(f, &w);
                lane_store(f, one, i, &w);
            }
            continue;
        }
        lane_store(f, d, i, &v);
        bn_one(f, &w);
        lane_store(f, aw, i, &w);
        lane_store(f, bw, i, &w);
        lane_store(f, pw, i, &w);
        lane_store(f, one, i, &w);
    }

    /* Pre-normalise subnormal operands: exact power-of-two multiplies,
     * shift tracked in D. (pw and one currently hold the per-lane
     * powers; one is rebuilt as the constant 1.0 right after.) */
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, aw, pw, NULL, aw, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, bw, one, NULL, bw, n, bus_out);
    if (st != CFT_OK) return st;

    /* Centre: significand kept, exponent field replaced by the bias,
     * sign STRIPPED - the whole finish reasons about positive
     * magnitudes, and the sign is applied exactly once, by round_pack.
     * Host bit surgery on the encodings, as the model's _centre. */
    for (i = 0; i < n; i++) {
        cft_bn x;
        if (!s->core[i]) {
            bn_one(f, &v);
            lane_store(f, ac, i, &v);
            lane_store(f, bc, i, &v);
            continue;
        }
        lane_load(f, aw, i, &x);
        s->D[i] += (int)cft_bn_extract(&x, f->man_w, f->exp_w) - f->bias;
        cft_bn_mask(&x, f->man_w);
        cft_bn_set_u32(&v, (uint32_t)f->bias);
        (void)cft_bn_shl(&v, &v, f->man_w);
        cft_bn_or(&x, &x, &v);
        lane_store(f, ac, i, &x);

        lane_load(f, bw, i, &x);
        s->D[i] -= (int)cft_bn_extract(&x, f->man_w, f->exp_w) - f->bias;
        cft_bn_mask(&x, f->man_w);
        cft_bn_or(&x, &x, &v);
        lane_store(f, bc, i, &x);
    }

    bn_one(f, &v);
    fill_const(f, one, n, &v);

    /* Seed and Newton: y -> 1/bc to full precision, under RNE. The
     * centring above is what discharges the seed's flush-at-input
     * precondition - every lane it sees is normal. */
    st = step(dev, CFT_RECIP_SEED, fmt, CFT_SF_RNE, bc, NULL, NULL, y, n,
              bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, bc, NULL, NULL, nb, n, bus_out);
    if (st != CFT_OK) return st;
    for (it = 0; it < N; it++) {
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, y, one, t2, n, bus_out);
        if (st != CFT_OK) return st;
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, y, t2, y, y, n, bus_out);
        if (st != CFT_OK) return st;
    }

    /* Markstein to a truncated quotient: RNE tighten twice, then RTZ -
     * which has no ties to fabricate. */
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, ac, y, NULL, t1, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, t1, ac, t2, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, t2, y, t1, t1, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, t1, ac, t2, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RTZ, t2, y, t1, q2, n, bus_out);
    if (st != CFT_OK) return st;

    /* Restore to floor: at most one ulp step either way per pass,
     * decided by exact residual signs. The residual and the room test
     * are device fmas; the steps are host increments on the encoding. */
    for (it = 0; it < 2; it++) {
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, q2, ac, r2, n, bus_out);
        if (st != CFT_OK) return st;
        for (i = 0; i < n; i++) {
            int stepped = 0;
            if (!s->core[i] || s->settled[i]) {
                bn_one(f, &v);
                lane_store(f, pw, i, &v);
                continue;
            }
            if (lane_negbit(f, r2, i) && !lane_mag_zero(f, r2, i)) {
                lane_step(f, q2, i, 0);
                stepped = 1;
            }
            if (stepped) {
                /* room test skipped this pass, as in the model */
                bn_one(f, &v);
                lane_store(f, pw, i, &v);
                s->settled[i] = 2;      /* transient: skip up phase */
            } else {
                cft_bn q;
                int e_v;
                lane_load(f, q2, i, &q);
                e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
                      - f->bias - f->man_w;
                if (lane_pow2(f, pw, i, e_v))
                    return CFT_ERR_INTERNAL;
            }
        }
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, pw, r2, t2, n, bus_out);
        if (st != CFT_OK) return st;
        for (i = 0; i < n; i++) {
            if (!s->core[i])
                continue;
            if (s->settled[i] == 2) {   /* stepped down; try again */
                s->settled[i] = 0;
                continue;
            }
            if (s->settled[i])
                continue;
            if (!lane_negbit(f, t2, i) &&
                !lane_is_zero_of_sign(f, t2, i, 0))
                lane_step(f, q2, i, 1);
            else
                s->settled[i] = 1;
        }
    }

    /* The exact remainder, the measured guard, and the one rounding. */
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, q2, ac, r2, n, bus_out);
    if (st != CFT_OK) return st;
    for (i = 0; i < n; i++) {
        if (!s->core[i] || lane_mag_zero(f, r2, i)) {
            bn_one(f, &v);
            lane_store(f, pw, i, &v);
            continue;
        }
        {
            cft_bn q;
            int e_v;
            lane_load(f, q2, i, &q);
            e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
                  - f->bias - f->man_w;
            if (lane_pow2(f, pw, i, e_v - 1))
                return CFT_ERR_INTERNAL;
        }
    }
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, pw, r2, t2, n, bus_out);
    if (st != CFT_OK) return st;

    for (i = 0; i < n; i++) {
        cft_bn q, m;
        uint32_t fl = 0;
        int guard, sticky, e_v;
        if (!s->core[i])
            continue;
        if (lane_mag_zero(f, r2, i)) {
            guard = 0;
            sticky = 0;
        } else if (lane_mag_zero(f, t2, i)) {
            guard = 1;                       /* exact tie */
            sticky = 0;
        } else if (lane_negbit(f, t2, i)) {
            guard = 0;                       /* below the midpoint */
            sticky = 1;
        } else {
            guard = 1;                       /* above the midpoint */
            sticky = 1;
        }
        lane_load(f, q2, i, &q);
        e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
              - f->bias - f->man_w;
        cft_bn_mask(&q, f->man_w);
        cft_bn_setbit(&q, f->man_w);         /* centred: always normal */
        if (cft_bn_shl(&m, &q, 2))
            return CFT_ERR_INTERNAL;
        if (guard)
            cft_bn_setbit(&m, 1);
        if (sticky)
            cft_bn_setbit(&m, 0);
        if (cft_sf_round_pack(f, s->sq[i], &m, e_v + s->D[i] - 2, 0, rnd,
                              &v, &fl))
            return CFT_ERR_INTERNAL;
        *acc |= fl;
        lane_store(f, d, i, &v);
    }
    return CFT_OK;
}

/* ---- square root -------------------------------------------------- */

static cft_status sqrt_chunk(cft_device *dev, const cft_fmt_desc *f,
                             cft_format fmt, int rnd,
                             const uint8_t *a, uint8_t *d,
                             size_t n, scratch *s,
                             uint32_t *acc, uint32_t *bus_out)
{
    uint8_t *aw = s->b[0], *acen = s->b[1], *nb = s->b[2], *y = s->b[3];
    uint8_t *t1 = s->b[4], *t2 = s->b[5], *s1 = s->b[6], *r2 = s->b[7];
    uint8_t *pw = s->b[8], *half = s->b[9], *th = s->b[10], *spb = s->b[11];
    cft_bn v, w;
    cft_status st;
    size_t i;
    int it, N = newton_steps(f);
    int k2 = f->prec + (f->prec & 1);        /* even prenorm shift */

    if (N < 0)
        return CFT_ERR_INTERNAL;

    for (i = 0; i < n; i++) {
        lane_cls *ka = &s->ca[i];
        cft_bn xa;
        lane_load(f, a, i, &xa);
        classify(f, &xa, ka);
        s->core[i] = 0;
        s->settled[i] = 0;
        s->D[i] = 0;

        if (ka->kind == K_NAN) {
            cft_sf_qnan(f, &v);
            if (ka->signaling)
                *acc |= CFT_SF_INVALID;
        } else if (ka->kind == K_ZERO) {
            cft_bn_copy(&v, &xa);            /* sqrt(+/-0) is +/-0 */
        } else if (ka->sign) {
            cft_sf_qnan(f, &v);              /* negative, -inf included */
            *acc |= CFT_SF_INVALID;
        } else if (ka->kind == K_INF) {
            cft_bn_copy(&v, &xa);
        } else {
            s->core[i] = 1;
            lane_store(f, aw, i, &xa);
            if (ka->kind == K_SUB) {
                if (lane_pow2(f, pw, i, k2))
                    return CFT_ERR_INTERNAL;
                s->D[i] = -(k2 / 2);
            } else {
                bn_one(f, &w);
                lane_store(f, pw, i, &w);
            }
            continue;
        }
        lane_store(f, d, i, &v);
        bn_one(f, &w);
        lane_store(f, aw, i, &w);
        lane_store(f, pw, i, &w);
    }

    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, aw, pw, NULL, aw, n, bus_out);
    if (st != CFT_OK) return st;

    /* Centre to [1, 2) then fold the exponent's parity in: odd lanes
     * are doubled by an exact multiply, so the core sees [1, 4) and
     * the rescale 2^D2 is a single representable power. */
    for (i = 0; i < n; i++) {
        cft_bn x;
        int E, odd;
        if (!s->core[i]) {
            bn_one(f, &v);
            lane_store(f, acen, i, &v);
            lane_store(f, pw, i, &v);
            continue;
        }
        lane_load(f, aw, i, &x);
        E = (int)cft_bn_extract(&x, f->man_w, f->exp_w) - f->bias;
        odd = E & 1;
        s->D[i] += (E - odd) / 2;            /* (E - odd) is even */
        cft_bn_mask(&x, f->man_w);
        cft_bn_set_u32(&v, (uint32_t)f->bias);
        (void)cft_bn_shl(&v, &v, f->man_w);
        cft_bn_or(&x, &x, &v);
        lane_store(f, acen, i, &x);
        if (odd) {
            if (lane_pow2(f, pw, i, 1))
                return CFT_ERR_INTERNAL;
        } else {
            bn_one(f, &v);
            lane_store(f, pw, i, &v);
        }
    }
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, acen, pw, NULL, acen, n,
              bus_out);
    if (st != CFT_OK) return st;

    bn_pow2(f, -1, &v);
    fill_const(f, half, n, &v);
    bn_pow2(f, 0, &v);
    cft_bn_setbit(&v, f->man_w - 1);         /* 1.5 */
    fill_const(f, th, n, &v);

    /* Seed and Newton under RNE: y -> 1/sqrt(acen). */
    st = step(dev, CFT_RSQRT_SEED, fmt, CFT_SF_RNE, acen, NULL, NULL, y, n,
              bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, acen, NULL, NULL, nb, n,
              bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, nb, half, NULL, nb, n, bus_out);
    if (st != CFT_OK) return st;             /* nb = -(a/2), exact */
    for (it = 0; it < N; it++) {
        st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, y, y, NULL, t1, n, bus_out);
        if (st != CFT_OK) return st;
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, t1, th, t1, n, bus_out);
        if (st != CFT_OK) return st;
        st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, y, t1, NULL, y, n, bus_out);
        if (st != CFT_OK) return st;
    }

    /* s0, h0, the exact residual, and the half-ulp correction. */
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, acen, y, NULL, s1, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, y, half, NULL, t2, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, s1, NULL, NULL, nb, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, s1, acen, r2, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, r2, t2, s1, s1, n, bus_out);
    if (st != CFT_OK) return st;

    /* Restore to floor, by exact residual signs. */
    for (it = 0; it < 2; it++) {
        st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, s1, NULL, NULL, nb, n,
                  bus_out);
        if (st != CFT_OK) return st;
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, s1, acen, r2, n,
                  bus_out);
        if (st != CFT_OK) return st;
        for (i = 0; i < n; i++) {
            if (!s->core[i] || s->settled[i]) {
                bn_one(f, &v);
                lane_store(f, spb, i, &v);
                continue;
            }
            if (lane_negbit(f, r2, i) && !lane_mag_zero(f, r2, i)) {
                lane_step(f, s1, i, 0);
                s->settled[i] = 2;           /* transient: skip up */
                bn_one(f, &v);
                lane_store(f, spb, i, &v);
            } else {
                cft_bn q;
                lane_load(f, s1, i, &q);
                (void)cft_bn_inc(&q);
                lane_store(f, spb, i, &q);
            }
        }
        st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, spb, NULL, NULL, nb, n,
                  bus_out);
        if (st != CFT_OK) return st;
        st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, spb, acen, t1, n,
                  bus_out);
        if (st != CFT_OK) return st;
        for (i = 0; i < n; i++) {
            if (!s->core[i])
                continue;
            if (s->settled[i] == 2) {
                s->settled[i] = 0;
                continue;
            }
            if (s->settled[i])
                continue;
            if (!lane_negbit(f, t1, i)) {
                cft_bn q;
                lane_load(f, spb, i, &q);
                lane_store(f, s1, i, &q);
            } else {
                s->settled[i] = 1;
            }
        }
    }

    /* Exact residual, then the midpoint discriminant in three exact
     * steps: d2 = r - s*u - u^2/4, whose sign is the guard. */
    st = step(dev, CFT_NEG, fmt, CFT_SF_RNE, s1, NULL, NULL, nb, n, bus_out);
    if (st != CFT_OK) return st;
    st = step(dev, CFT_FMA, fmt, CFT_SF_RNE, nb, s1, acen, r2, n, bus_out);
    if (st != CFT_OK) return st;
    for (i = 0; i < n; i++) {
        cft_bn q;
        int e_v;
        if (!s->core[i] || lane_mag_zero(f, r2, i)) {
            bn_one(f, &v);
            lane_store(f, pw, i, &v);
            continue;
        }
        lane_load(f, s1, i, &q);
        e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
              - f->bias - f->man_w;
        if (lane_pow2(f, pw, i, e_v))
            return CFT_ERR_INTERNAL;
    }
    st = step(dev, CFT_MUL, fmt, CFT_SF_RNE, s1, pw, NULL, t1, n, bus_out);
    if (st != CFT_OK) return st;             /* s * 2^e, exact */
    st = step(dev, CFT_SUB, fmt, CFT_SF_RNE, r2, NULL, t1, t1, n, bus_out);
    if (st != CFT_OK) return st;             /* r - s*u, exact */
    for (i = 0; i < n; i++) {
        cft_bn q;
        int e_v;
        if (!s->core[i] || lane_mag_zero(f, r2, i)) {
            bn_one(f, &v);
            lane_store(f, pw, i, &v);
            continue;
        }
        lane_load(f, s1, i, &q);
        e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
              - f->bias - f->man_w;
        if (lane_pow2(f, pw, i, 2 * e_v - 2))
            return CFT_ERR_INTERNAL;
    }
    st = step(dev, CFT_SUB, fmt, CFT_SF_RNE, t1, NULL, pw, t1, n, bus_out);
    if (st != CFT_OK) return st;             /* - u^2/4, exact */

    for (i = 0; i < n; i++) {
        cft_bn q, m;
        uint32_t fl = 0;
        int guard, sticky, e_v;
        if (!s->core[i])
            continue;
        if (lane_mag_zero(f, r2, i)) {
            guard = 0;
            sticky = 0;
        } else {
            guard = lane_negbit(f, t1, i) ? 0 : 1;
            /* an inexact root is never ON a representable or a
             * midpoint, so sticky is unconditional here */
            sticky = 1;
        }
        lane_load(f, s1, i, &q);
        e_v = (int)cft_bn_extract(&q, f->man_w, f->exp_w)
              - f->bias - f->man_w;
        cft_bn_mask(&q, f->man_w);
        cft_bn_setbit(&q, f->man_w);
        if (cft_bn_shl(&m, &q, 2))
            return CFT_ERR_INTERNAL;
        if (guard)
            cft_bn_setbit(&m, 1);
        if (sticky)
            cft_bn_setbit(&m, 0);
        if (cft_sf_round_pack(f, 0, &m, e_v + s->D[i] - 2, 0, rnd, &v, &fl))
            return CFT_ERR_INTERNAL;
        *acc |= fl;
        lane_store(f, d, i, &v);
    }
    return CFT_OK;
}

/* ---- entry points ------------------------------------------------- */

static cft_status divsqrt_validate(cft_device *dev, cft_format fmt,
                                   cft_round rnd, const void *a,
                                   void *d, size_t n, cft_op seed_op)
{
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    /* Support is checked BEFORE the n==0 shortcut, mirroring cft_run:
     * an unsupported (device, format) pair is unsupported at every n,
     * and answering OK at zero elements would make the two entry
     * points disagree about the same device (the adversarial review's
     * F8). */
    if (!cft_supports(dev, CFT_FMA, fmt) ||
        !cft_supports(dev, CFT_NEG, fmt) ||
        !cft_supports(dev, seed_op, fmt))
        return CFT_ERR_UNSUPPORTED;
    if (n == 0)
        return CFT_OK;
    if (!a || !d)
        return CFT_ERR_INVALID_ARGUMENT;
    return CFT_OK;
}

CFT_API cft_status cft_div(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, const void *b, void *d, size_t n,
                           uint32_t *flags_out, uint32_t *bus_out)
{
    const cft_fmt_desc *f;
    scratch s;
    uint32_t acc = 0;
    size_t off = 0, esz;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    st = divsqrt_validate(dev, fmt, rnd, a, d, n, CFT_RECIP_SEED);
    if (st != CFT_OK || n == 0) {
        if (st == CFT_OK && flags_out)
            *flags_out = 0;
        return st;
    }
    if (!b)
        return CFT_ERR_INVALID_ARGUMENT;

    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;
    if (scratch_alloc(&s, esz))
        return CFT_ERR_OUT_OF_MEMORY;

    while (off < n) {
        size_t c = n - off > CHUNK ? CHUNK : n - off;
        st = div_chunk(dev, f, fmt, (int)rnd,
                       (const uint8_t *)a + off * esz,
                       (const uint8_t *)b + off * esz,
                       (uint8_t *)d + off * esz, c, &s, &acc, bus_out);
        if (st != CFT_OK) {
            scratch_free(&s);
            return st;
        }
        off += c;
    }
    scratch_free(&s);
    if (flags_out)
        *flags_out = acc;
    return CFT_OK;
}

CFT_API cft_status cft_sqrt(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out, uint32_t *bus_out)
{
    const cft_fmt_desc *f;
    scratch s;
    uint32_t acc = 0;
    size_t off = 0, esz;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    st = divsqrt_validate(dev, fmt, rnd, a, d, n, CFT_RSQRT_SEED);
    if (st != CFT_OK || n == 0) {
        if (st == CFT_OK && flags_out)
            *flags_out = 0;
        return st;
    }

    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;
    if (scratch_alloc(&s, esz))
        return CFT_ERR_OUT_OF_MEMORY;

    while (off < n) {
        size_t c = n - off > CHUNK ? CHUNK : n - off;
        st = sqrt_chunk(dev, f, fmt, (int)rnd,
                        (const uint8_t *)a + off * esz,
                        (uint8_t *)d + off * esz, c, &s, &acc, bus_out);
        if (st != CFT_OK) {
            scratch_free(&s);
            return st;
        }
        off += c;
    }
    scratch_free(&s);
    if (flags_out)
        *flags_out = acc;
    return CFT_OK;
}
