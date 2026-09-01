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

/* ---- the sequencer-program route -----------------------------------
 *
 * The same construction as div_chunk/sqrt_chunk - the SAME steps, in
 * the same order, under the same rounding attributes - restated as one
 * sequencer program per call instead of ~25-30 elementwise runs.
 * python/cft_golden/seqprogs.py is this section's specification, the
 * same way sequences.py specifies the chunk routes, and
 * test_seqprogs.py holds the program bit-identical to the contract.
 *
 * What moves on-chip: the entire floating-point core plus the restore
 * loop's per-lane conditionals, which become branchless CMPLT/SELECT
 * with IADD/ISUB ulp steps on the encoding. The model's early break
 * needs no bookkeeping: a settled lane re-evaluates to the same
 * decisions and steps zero times, so two unconditional passes are the
 * loop. What stays host: classification and centring (integer surgery
 * on encodings the host holds anyway) and round_pack from the three
 * deposits (q/result, exact residual, midpoint probe).
 *
 * Route choice: a hardware-backed device takes this path - one round
 * trip instead of ~28 - and falls back to the chunk route if the
 * bitstream cannot run programs (load or first run answers
 * UNSUPPORTED; d has not been touched yet at that point, which is what
 * keeps the fallback legal under d-aliases-a). The software backend
 * keeps the chunk route, where there is no round trip to save.
 * CFT_DIVSQRT_SEQ=1|0 in the environment forces the choice either way
 * - =1 is how the tests drive this route through the software
 * executor's program interpreter without a device.
 */

#include "backend.h"

enum { RG_A = 0, RG_B = 1, RG_Y = 3, RG_NB = 4, RG_T1 = 5, RG_T2 = 6,
       RG_Q = 7, RG_PW = 8, RG_DN = 9, RG_UP = 10, RG_TMP = 11,
       RG_SP = 12 };
enum { CK_ZERO = 0, CK_ONE, CK_INT1, CK_EXP, CK_MW, CK_MW1,
       CK_HALF, CK_3H, CK_SQ };
#define CK_NDIV  6
#define CK_NSQRT 9

typedef struct { uint64_t w[80]; int n; } sq_prog;

static void sq_push(sq_prog *p, uint64_t w)
{
    p->w[p->n++] = w;
}

static uint64_t sq_word(int op, int rd, int ra, int rb, int rc, int rnd,
                        int ka, int kb, int kc)
{
    return (uint64_t)((uint32_t)op | ((uint32_t)rd << 8) |
                      ((uint32_t)ra << 12) | ((uint32_t)rb << 16) |
                      ((uint32_t)rc << 20) | ((uint32_t)rnd << 24) |
                      ((uint32_t)(ka != 0) << 27) |
                      ((uint32_t)(kb != 0) << 28) |
                      ((uint32_t)(kc != 0) << 29));
}

static uint64_t sq_ctrlw(int code, int ra)
{
    return (uint64_t)((uint32_t)code | ((uint32_t)ra << 12) | (1u << 31));
}
#define SQ_CTRL_HALT    0
#define SQ_CTRL_DEPOSIT 3

/* One restore pass, division. Mirrors seqprogs._restore_pass_div. */
static void sq_restore_div(sq_prog *p)
{
    const int R = CFT_SF_RNE;
    sq_push(p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_Q, RG_A, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_CMPLT, RG_DN, RG_T2, CK_ZERO, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_ISUB, RG_TMP, RG_Q, CK_INT1, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_SELECT, RG_Q, RG_TMP, RG_Q, RG_DN, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_IAND, RG_PW, RG_Q, CK_EXP, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_ISUB, RG_PW, RG_PW, CK_MW, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_FMA, RG_UP, RG_NB, RG_PW, RG_T2, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_CMPLT, RG_UP, CK_ZERO, RG_UP, 0, R, 1, 0, 0));
    sq_push(p, sq_word(CFT_SUB, RG_TMP, CK_ONE, 0, RG_DN, R, 1, 0, 0));
    sq_push(p, sq_word(CFT_MUL, RG_UP, RG_UP, RG_TMP, 0, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_IADD, RG_TMP, RG_Q, CK_INT1, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_SELECT, RG_Q, RG_TMP, RG_Q, RG_UP, R, 0, 0, 0));
}

/* One restore pass, square root. Mirrors seqprogs._restore_pass_sqrt. */
static void sq_restore_sqrt(sq_prog *p)
{
    const int R = CFT_SF_RNE;
    sq_push(p, sq_word(CFT_NEG, RG_NB, RG_Q, 0, 0, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_Q, RG_A, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_CMPLT, RG_DN, RG_T2, CK_ZERO, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_ISUB, RG_TMP, RG_Q, CK_INT1, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_SELECT, RG_Q, RG_TMP, RG_Q, RG_DN, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_IADD, RG_SP, RG_Q, CK_INT1, 0, R, 0, 1, 0));
    sq_push(p, sq_word(CFT_NEG, RG_NB, RG_SP, 0, 0, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_FMA, RG_UP, RG_NB, RG_SP, RG_A, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_CMPLE, RG_UP, CK_ZERO, RG_UP, 0, R, 1, 0, 0));
    sq_push(p, sq_word(CFT_SUB, RG_TMP, CK_ONE, 0, RG_DN, R, 1, 0, 0));
    sq_push(p, sq_word(CFT_MUL, RG_UP, RG_UP, RG_TMP, 0, R, 0, 0, 0));
    sq_push(p, sq_word(CFT_SELECT, RG_Q, RG_SP, RG_Q, RG_UP, R, 0, 0, 0));
}

static void sq_put_le32(uint8_t *d, uint32_t v)
{
    d[0] = (uint8_t)v;
    d[1] = (uint8_t)(v >> 8);
    d[2] = (uint8_t)(v >> 16);
    d[3] = (uint8_t)(v >> 24);
}

/* The constant bank, derived from the format's own fields. Index
 * order is the CK_* enum; the sqrt bank extends the div bank. */
static void sq_const(const cft_fmt_desc *f, int idx, cft_bn *v)
{
    switch (idx) {
    case CK_ZERO:
        cft_bn_zero(v);
        break;
    case CK_ONE:
        bn_one(f, v);
        break;
    case CK_INT1:
        cft_bn_zero(v);
        cft_bn_set_u32(v, 1);
        break;
    case CK_EXP:
        cft_bn_zero(v);
        cft_bn_set_u32(v, f->exp_mask);
        (void)cft_bn_shl(v, v, f->man_w);
        break;
    case CK_MW:
        cft_bn_zero(v);
        cft_bn_set_u32(v, (uint32_t)f->man_w);
        (void)cft_bn_shl(v, v, f->man_w);
        break;
    case CK_MW1:
        cft_bn_zero(v);
        cft_bn_set_u32(v, (uint32_t)(f->man_w + 1));
        (void)cft_bn_shl(v, v, f->man_w);
        break;
    case CK_HALF:
        bn_pow2(f, -1, v);
        break;
    case CK_3H:
        bn_one(f, v);
        cft_bn_setbit(v, f->man_w - 1);
        break;
    case CK_SQ:
        /* Turns (exp field << 1) into 2^(2e-2): the target field is
         * 2E - bias - 2*man_w - 2, and the shifted field holds 2E. */
        cft_bn_zero(v);
        cft_bn_set_u32(v, (uint32_t)(f->bias + 2 * f->man_w + 2));
        (void)cft_bn_shl(v, v, f->man_w);
        break;
    }
}

/* Emit a complete program image - header, constants, instructions -
 * into buf (which must hold SQ_IMAGE_MAX). Returns the byte count. */
#define SQ_IMAGE_MAX (32 + 9 * 32 + 80 * 8)

static size_t sq_emit(const cft_fmt_desc *f, cft_format fmt, int is_sqrt,
                      uint8_t *buf)
{
    const int R = CFT_SF_RNE;
    sq_prog p;
    int N = newton_steps(f), it, k, nconst;
    size_t off, esz = (size_t)(f->width / 8);
    cft_bn v;

    p.n = 0;
    if (!is_sqrt) {
        sq_push(&p, sq_word(CFT_RECIP_SEED, RG_Y, RG_B, 0, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_NEG, RG_NB, RG_B, 0, 0, R, 0, 0, 0));
        for (it = 0; it < N; it++) {
            sq_push(&p, sq_word(CFT_FMA, RG_T1, RG_NB, RG_Y, CK_ONE,
                                R, 0, 0, 1));
            sq_push(&p, sq_word(CFT_FMA, RG_Y, RG_Y, RG_T1, RG_Y,
                                R, 0, 0, 0));
        }
        sq_push(&p, sq_word(CFT_MUL, RG_T1, RG_A, RG_Y, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_T1, RG_A, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_Q, RG_T2, RG_Y, RG_T1, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_Q, RG_A, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_Q, RG_T2, RG_Y, RG_Q,
                            CFT_SF_RTZ, 0, 0, 0));
        sq_restore_div(&p);
        sq_restore_div(&p);
        sq_push(&p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_Q, RG_A, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_IAND, RG_PW, RG_Q, CK_EXP, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_ISUB, RG_PW, RG_PW, CK_MW1, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_UP, RG_NB, RG_PW, RG_T2,
                            R, 0, 0, 0));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_Q));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_T2));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_UP));
        sq_push(&p, sq_ctrlw(SQ_CTRL_HALT, 0));
        nconst = CK_NDIV;
    } else {
        sq_push(&p, sq_word(CFT_RSQRT_SEED, RG_Y, RG_A, 0, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_NEG, RG_NB, RG_A, 0, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_MUL, RG_NB, RG_NB, CK_HALF, 0, R, 0, 1, 0));
        for (it = 0; it < N; it++) {
            sq_push(&p, sq_word(CFT_MUL, RG_T1, RG_Y, RG_Y, 0, R, 0, 0, 0));
            sq_push(&p, sq_word(CFT_FMA, RG_T1, RG_NB, RG_T1, CK_3H,
                                R, 0, 0, 1));
            sq_push(&p, sq_word(CFT_MUL, RG_Y, RG_Y, RG_T1, 0, R, 0, 0, 0));
        }
        sq_push(&p, sq_word(CFT_MUL, RG_T1, RG_A, RG_Y, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_MUL, RG_UP, RG_Y, CK_HALF, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_NEG, RG_NB, RG_T1, 0, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_T1, RG_A, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_Q, RG_T2, RG_UP, RG_T1, R, 0, 0, 0));
        sq_restore_sqrt(&p);
        sq_restore_sqrt(&p);
        sq_push(&p, sq_word(CFT_NEG, RG_NB, RG_Q, 0, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_FMA, RG_T2, RG_NB, RG_Q, RG_A, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_IAND, RG_PW, RG_Q, CK_EXP, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_ISUB, RG_UP, RG_PW, CK_MW, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_MUL, RG_UP, RG_Q, RG_UP, 0, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_SUB, RG_TMP, RG_T2, 0, RG_UP, R, 0, 0, 0));
        sq_push(&p, sq_word(CFT_ISHL, RG_PW, RG_PW, CK_INT1, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_ISUB, RG_PW, RG_PW, CK_SQ, 0, R, 0, 1, 0));
        sq_push(&p, sq_word(CFT_SUB, RG_TMP, RG_TMP, 0, RG_PW, R, 0, 0, 0));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_Q));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_T2));
        sq_push(&p, sq_ctrlw(SQ_CTRL_DEPOSIT, RG_TMP));
        sq_push(&p, sq_ctrlw(SQ_CTRL_HALT, 0));
        nconst = CK_NSQRT;
    }

    sq_put_le32(buf + 0, 0x50544643u);           /* "CFTP" */
    sq_put_le32(buf + 4, 1u);
    sq_put_le32(buf + 8, (uint32_t)p.n);
    sq_put_le32(buf + 12, (uint32_t)nconst);
    sq_put_le32(buf + 16, 3u);                   /* max_deposits */
    sq_put_le32(buf + 20, (uint32_t)fmt);
    sq_put_le32(buf + 24, 0u);
    sq_put_le32(buf + 28, 0u);
    off = 32;
    for (k = 0; k < nconst; k++) {
        sq_const(f, k, &v);
        cft_bn_store(&v, buf + off, esz);
        off += esz;
    }
    for (k = 0; k < p.n; k++) {
        sq_put_le32(buf + off, (uint32_t)p.w[k]);
        sq_put_le32(buf + off + 4, (uint32_t)(p.w[k] >> 32));
        off += 8;
    }
    return off;
}

/* Exact host multiply for the prenormalise step - the same op the
 * chunk route issues to the backend, computed by the same softfloat. */
static void sq_host_mul_pow2(const cft_fmt_desc *f, cft_bn *x, int e)
{
    cft_bn p2, z, out;
    uint32_t fl = 0;
    bn_pow2(f, e, &p2);
    cft_bn_zero(&z);
    (void)cft_sf_compute(f, CFT_MUL, CFT_SF_RNE, x, &p2, &z, &out, &fl);
    cft_bn_copy(x, &out);
}

typedef struct {
    uint8_t *ac, *bc;        /* centred operand streams */
    uint8_t *sv;             /* specials' results, held until finish */
    uint8_t *deps;           /* n * 3 deposit slots */
    uint32_t *cnt;
    int *D;
    uint8_t *core, *sq;
} pscratch;

static void pscratch_free(pscratch *s)
{
    free(s->ac); free(s->bc); free(s->sv); free(s->deps);
    free(s->cnt); free(s->D); free(s->core); free(s->sq);
    memset(s, 0, sizeof *s);
}

static int pscratch_alloc(pscratch *s, size_t esz)
{
    memset(s, 0, sizeof *s);
    s->ac   = (uint8_t *)malloc(CHUNK * esz);
    s->bc   = (uint8_t *)malloc(CHUNK * esz);
    s->sv   = (uint8_t *)malloc(CHUNK * esz);
    s->deps = (uint8_t *)malloc(CHUNK * 3 * esz);
    s->cnt  = (uint32_t *)malloc(CHUNK * sizeof *s->cnt);
    s->D    = (int *)malloc(CHUNK * sizeof *s->D);
    s->core = (uint8_t *)malloc(CHUNK);
    s->sq   = (uint8_t *)malloc(CHUNK);
    if (!s->ac || !s->bc || !s->sv || !s->deps || !s->cnt || !s->D ||
        !s->core || !s->sq) {
        pscratch_free(s);
        return 1;
    }
    return 0;
}

/* Centre one operand: significand kept, exponent field replaced by
 * the bias, sign stripped. Returns the true unbiased exponent. */
static int sq_centre(const cft_fmt_desc *f, cft_bn *x)
{
    cft_bn v;
    int e = (int)cft_bn_extract(x, f->man_w, f->exp_w) - f->bias;
    cft_bn_mask(x, f->man_w);
    cft_bn_set_u32(&v, (uint32_t)f->bias);
    (void)cft_bn_shl(&v, &v, f->man_w);
    cft_bn_or(x, x, &v);
    return e;
}

static cft_status div_prog_chunk(const cft_fmt_desc *f, int rnd,
                                 cft_program *prog,
                                 const uint8_t *a, const uint8_t *b,
                                 uint8_t *d, size_t n, pscratch *s,
                                 uint32_t *acc, uint32_t *bus_out)
{
    cft_bn v, w;
    cft_status st;
    size_t i;

    for (i = 0; i < n; i++) {
        lane_cls ka, kb;
        cft_bn xa, xb;
        int is_special = 1;
        lane_load(f, a, i, &xa);
        lane_load(f, b, i, &xb);
        classify(f, &xa, &ka);
        classify(f, &xb, &kb);
        s->sq[i] = (uint8_t)(ka.sign ^ kb.sign);
        s->core[i] = 0;
        s->D[i] = 0;

        if (ka.kind == K_NAN || kb.kind == K_NAN) {
            cft_sf_qnan(f, &v);
            if (ka.signaling || kb.signaling)
                *acc |= CFT_SF_INVALID;
        } else if (ka.kind == K_INF) {
            if (kb.kind == K_INF) {
                cft_sf_qnan(f, &v);
                *acc |= CFT_SF_INVALID;
            } else {
                cft_sf_inf(f, s->sq[i], &v);
            }
        } else if (kb.kind == K_INF) {
            cft_sf_zero(f, s->sq[i], &v);
        } else if (kb.kind == K_ZERO) {
            if (ka.kind == K_ZERO) {
                cft_sf_qnan(f, &v);
                *acc |= CFT_SF_INVALID;
            } else {
                cft_sf_inf(f, s->sq[i], &v);
                *acc |= CFT_SF_DIVZERO;
            }
        } else if (ka.kind == K_ZERO) {
            cft_sf_zero(f, s->sq[i], &v);
        } else {
            int ea, eb, d_adj = 0;
            is_special = 0;
            s->core[i] = 1;
            if (ka.kind == K_SUB) {
                sq_host_mul_pow2(f, &xa, f->prec);
                d_adj -= f->prec;
            }
            if (kb.kind == K_SUB) {
                sq_host_mul_pow2(f, &xb, f->prec);
                d_adj += f->prec;
            }
            ea = sq_centre(f, &xa);
            eb = sq_centre(f, &xb);
            s->D[i] = ea - eb + d_adj;
            lane_store(f, s->ac, i, &xa);
            lane_store(f, s->bc, i, &xb);
        }
        if (is_special) {
            lane_store(f, s->sv, i, &v);
            bn_one(f, &w);
            lane_store(f, s->ac, i, &w);        /* benign core operands */
            lane_store(f, s->bc, i, &w);
        }
    }

    st = cft_program_run(prog, s->ac, s->bc, NULL, s->deps, s->cnt, n,
                         NULL, bus_out);
    if (st != CFT_OK)
        return st;

    for (i = 0; i < n; i++) {
        cft_bn q, m;
        uint32_t fl = 0;
        int guard, sticky, e_v;
        if (!s->core[i]) {
            lane_load(f, s->sv, i, &v);
            lane_store(f, d, i, &v);
            continue;
        }
        if (s->cnt[i] != 3)
            return CFT_ERR_INTERNAL;
        if (lane_mag_zero(f, s->deps, i * 3 + 1)) {
            guard = 0;
            sticky = 0;
        } else if (lane_mag_zero(f, s->deps, i * 3 + 2)) {
            guard = 1;                           /* exact tie */
            sticky = 0;
        } else if (lane_negbit(f, s->deps, i * 3 + 2)) {
            guard = 0;                           /* below the midpoint */
            sticky = 1;
        } else {
            guard = 1;                           /* above the midpoint */
            sticky = 1;
        }
        lane_load(f, s->deps, i * 3 + 0, &q);
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
        if (cft_sf_round_pack(f, s->sq[i], &m, e_v + s->D[i] - 2, 0, rnd,
                              &v, &fl))
            return CFT_ERR_INTERNAL;
        *acc |= fl;
        lane_store(f, d, i, &v);
    }
    return CFT_OK;
}

static cft_status sqrt_prog_chunk(const cft_fmt_desc *f, int rnd,
                                  cft_program *prog,
                                  const uint8_t *a, uint8_t *d, size_t n,
                                  pscratch *s, uint32_t *acc,
                                  uint32_t *bus_out)
{
    cft_bn v, w;
    cft_status st;
    size_t i;
    int k2 = f->prec + (f->prec & 1);

    for (i = 0; i < n; i++) {
        lane_cls ka;
        cft_bn xa;
        int is_special = 1;
        lane_load(f, a, i, &xa);
        classify(f, &xa, &ka);
        s->core[i] = 0;
        s->D[i] = 0;

        if (ka.kind == K_NAN) {
            cft_sf_qnan(f, &v);
            if (ka.signaling)
                *acc |= CFT_SF_INVALID;
        } else if (ka.kind == K_ZERO) {
            cft_bn_copy(&v, &xa);
        } else if (ka.sign) {
            cft_sf_qnan(f, &v);
            *acc |= CFT_SF_INVALID;
        } else if (ka.kind == K_INF) {
            cft_bn_copy(&v, &xa);
        } else {
            int E, odd, adj = 0;
            is_special = 0;
            s->core[i] = 1;
            if (ka.kind == K_SUB) {
                sq_host_mul_pow2(f, &xa, k2);
                adj = -(k2 / 2);
            }
            E = (int)cft_bn_extract(&xa, f->man_w, f->exp_w) - f->bias;
            odd = E & 1;
            cft_bn_mask(&xa, f->man_w);
            cft_bn_set_u32(&v, (uint32_t)f->bias);
            (void)cft_bn_shl(&v, &v, f->man_w);
            cft_bn_or(&xa, &xa, &v);
            if (odd)
                sq_host_mul_pow2(f, &xa, 1);
            s->D[i] = (E - odd) / 2 + adj;
            lane_store(f, s->ac, i, &xa);
        }
        if (is_special) {
            lane_store(f, s->sv, i, &v);
            bn_one(f, &w);
            lane_store(f, s->ac, i, &w);
        }
    }

    memset(s->bc, 0, n * (size_t)(f->width / 8));    /* unused b stream */
    st = cft_program_run(prog, s->ac, s->bc, NULL, s->deps, s->cnt, n,
                         NULL, bus_out);
    if (st != CFT_OK)
        return st;

    for (i = 0; i < n; i++) {
        cft_bn q, m;
        uint32_t fl = 0;
        int guard, sticky, e_v;
        if (!s->core[i]) {
            lane_load(f, s->sv, i, &v);
            lane_store(f, d, i, &v);
            continue;
        }
        if (s->cnt[i] != 3)
            return CFT_ERR_INTERNAL;
        if (lane_mag_zero(f, s->deps, i * 3 + 1)) {
            guard = 0;
            sticky = 0;
        } else {
            guard = lane_negbit(f, s->deps, i * 3 + 2) ? 0 : 1;
            sticky = 1;
        }
        lane_load(f, s->deps, i * 3 + 0, &q);
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

/* Route choice; see the section banner. */
static int divsqrt_route_program(cft_device *dev)
{
    const char *e = getenv("CFT_DIVSQRT_SEQ");
    if (e && e[0] == '0' && !e[1])
        return 0;
    if (e && e[0] == '1' && !e[1])
        return 1;
#ifdef CFT_ENABLE_XRT
    return cft_device_backend((const struct cft_device *)dev) != NULL;
#else
    (void)dev;
    return 0;
#endif
}

/* The whole call through the program route. Returns UNSUPPORTED only
 * before anything has been written to d, so the caller may legally
 * fall back to the chunk route even when d aliases a or b. */
static cft_status divsqrt_via_program(cft_device *dev,
                                      const cft_fmt_desc *f,
                                      cft_format fmt, int rnd, int is_sqrt,
                                      const uint8_t *a, const uint8_t *b,
                                      uint8_t *d, size_t n,
                                      uint32_t *acc, uint32_t *bus_out)
{
    uint8_t image[SQ_IMAGE_MAX];
    size_t bytes, off = 0, esz = (size_t)(f->width / 8);
    cft_program *prog = NULL;
    pscratch s;
    cft_status st;
    int wrote_any = 0;

    bytes = sq_emit(f, fmt, is_sqrt, image);
    st = cft_program_load(dev, image, bytes, &prog);
    if (st != CFT_OK)
        return st;
    if (pscratch_alloc(&s, esz)) {
        cft_program_free(prog);
        return CFT_ERR_OUT_OF_MEMORY;
    }
    while (off < n) {
        size_t c = n - off > CHUNK ? CHUNK : n - off;
        st = is_sqrt
            ? sqrt_prog_chunk(f, rnd, prog, a + off * esz,
                              d + off * esz, c, &s, acc, bus_out)
            : div_prog_chunk(f, rnd, prog, a + off * esz, b + off * esz,
                             d + off * esz, c, &s, acc, bus_out);
        if (st != CFT_OK) {
            /* After any chunk has written d, an UNSUPPORTED answer can
             * no longer be handed to the caller as "fall back": the
             * fallback would reread inputs a finished chunk may have
             * overwritten under aliasing. It cannot happen - support
             * does not change between chunks of one call - so it is an
             * internal error if it does. */
            if (st == CFT_ERR_UNSUPPORTED && wrote_any)
                st = CFT_ERR_INTERNAL;
            pscratch_free(&s);
            cft_program_free(prog);
            return st;
        }
        wrote_any = 1;
        off += c;
    }
    pscratch_free(&s);
    cft_program_free(prog);
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

    if (divsqrt_route_program(dev)) {
        st = divsqrt_via_program(dev, f, fmt, (int)rnd, 0,
                                 (const uint8_t *)a, (const uint8_t *)b,
                                 (uint8_t *)d, n, &acc, bus_out);
        if (st != CFT_ERR_UNSUPPORTED) {
            if (st == CFT_OK && flags_out)
                *flags_out = acc;
            return st;
        }
        acc = 0;         /* bitstream cannot run programs; d untouched */
    }

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

    if (divsqrt_route_program(dev)) {
        st = divsqrt_via_program(dev, f, fmt, (int)rnd, 1,
                                 (const uint8_t *)a, NULL,
                                 (uint8_t *)d, n, &acc, bus_out);
        if (st != CFT_ERR_UNSUPPORTED) {
            if (st == CFT_OK && flags_out)
                *flags_out = acc;
            return st;
        }
        acc = 0;         /* bitstream cannot run programs; d untouched */
    }

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
