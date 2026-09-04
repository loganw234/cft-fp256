/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The remaining clause-5 operations: roundToIntegral, the conversions,
 * scaleB/logB, nextUp/nextDown, classification, totalOrder, the
 * signaling comparisons, and remainder.
 *
 * python/cft_golden/softfloat.py (the clause-5 section) defines every
 * result here, and python/cft_golden/sequences.py specifies the two
 * routes that run on the backend. The operations split the same way
 * the whole library splits:
 *
 *   COMPOSED - cft_rint, cft_scaleb, cft_cmp_sig. The floating-point
 *   work is cft_run() passes (so on a device it runs on the tile's own
 *   FMA path), and the host keeps only exact integer bookkeeping:
 *   which lanes substitute, and what the contract flags are. Same
 *   division of labour as cft_div.
 *
 *   HOST - cft_convert, the integer conversions, cft_logb, cft_next_*,
 *   cft_class, cft_total_order*, cft_rem. These contain NO
 *   floating-point arithmetic at all - they are round_pack and bit
 *   surgery on the encoding - so there is nothing for a device to
 *   accelerate and no backend pass to issue. The device argument is
 *   context (and keeps one calling convention), not a participant.
 *   They are bit-identical on every backend by construction.
 *
 * Flags follow the composition discipline established by divsqrt.c:
 * scaffolding runs discard their flags, and what a caller sees is
 * derived from operand classes plus the one real rounding - except
 * cft_scaleb's multiply chain, where the mul's own flags ARE the
 * contract flags because the factor 2^n is exact (see scaleb_seq).
 *
 * cft_rem walks the exponent gap one quotient bit per step, bounded
 * p-bit integer work throughout where the model does one unbounded
 * divmod. The gap tops out at emax - emin + p - 2 steps (~524.5k for
 * fp256) - roughly ten milliseconds PER adversarial lane on the host,
 * so an array full of adversarial pairs pays it per element - and is
 * typically a handful. A power-of-two divisor exits the walk early,
 * which is why the check harness's full-gap case carries an odd
 * significand. host/tests/clause5_check.py holds the two identical.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"

#define CHUNK 4096

/* ---- lane accessors and classification (divsqrt.c's, restated) ---- */

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

static void bn_one_f(const cft_fmt_desc *f, cft_bn *v)
{
    cft_bn_zero(v);
    cft_bn_set_u32(v, (uint32_t)f->bias);
    (void)cft_bn_shl(v, v, f->man_w);
}

static void bn_max_normal(const cft_fmt_desc *f, int sign, cft_bn *v)
{
    cft_bn m;
    cft_bn_zero(v);
    cft_bn_set_u32(v, f->exp_mask - 1);
    (void)cft_bn_shl(v, v, f->man_w);
    cft_bn_zero(&m);
    cft_bn_set_u32(&m, 1);
    (void)cft_bn_shl(&m, &m, f->man_w);
    cft_bn_dec(&m);                          /* man_mask */
    cft_bn_or(v, v, &m);
    if (sign)
        cft_bn_setbit(v, f->width - 1);
}

/* The significand-and-exponent view of a finite nonzero lane: value is
 * (-1)^sign * m * 2^e with m the integer significand. Mirrors unpack. */
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

/* A scaffolding run: value kept, flags discarded, bus faults fatal.
 * Discarded from the status word too, which is what the mute is for -
 * see softfloat.h. */
static cft_status step(cft_device *dev, cft_op op, cft_format fmt, int rnd,
                       const void *a, const void *b, const void *c, void *d,
                       size_t n, uint32_t *bus_out)
{
    const int muted = cft_flags_mute(dev, 1);
    cft_status st = cft_run(dev, op, fmt, (cft_round)rnd, a, b, c, d, n,
                            NULL, bus_out);
    (void)cft_flags_mute(dev, muted);
    return st;
}

/* The shared argument checks. The rounding attribute is deliberately
 * NOT here: an early version admitted a "no attribute" sentinel
 * through the same range check the public entry points used, and a
 * caller's (cft_round)-1 sailed through to compute under a rounding
 * no legal attribute produces (the adversarial review's F1). The
 * operations that consume `rnd` now range-check it themselves with
 * rnd_ok(); the ones that do not consume it never look at it at all.
 * Support requirements differ per entry, so callers check those
 * themselves too. */
static cft_status c5_validate(cft_device *dev, cft_format fmt,
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

static int rnd_ok(cft_round rnd)
{
    return (int)rnd >= 0 && (int)rnd <= 4;
}

static int size_overflows(const cft_fmt_desc *f, size_t n)
{
    return n > ((size_t)-1) / (size_t)(f->width / 8);
}

/* The rounding-direction increment rule, on an integer grid. Restates
 * the model's _round_up; softfloat.c's copy is static and this needs
 * so little of it that sharing would cost more surface than it saves. */
static int round_up_rule(int rnd, int sign, int guard, int sticky, int lsb)
{
    switch (rnd) {
    case CFT_SF_RNE: return guard && (sticky || lsb);
    case CFT_SF_RMM: return guard;
    case CFT_SF_RTZ: return 0;
    case CFT_SF_RDN: return sign && (guard || sticky);
    default:         return !sign && (guard || sticky);   /* RUP */
    }
}

/* ---- roundToIntegral: composed (rint_seq) ------------------------- */

CFT_API cft_status cft_rint(cft_device *dev, cft_format fmt, cft_round rnd,
                            int exact, const void *a, void *d, size_t n,
                            uint32_t *flags_out, uint32_t *bus_out)
{
    const cft_fmt_desc *f;
    uint8_t *aw = NULL, *mb = NULL, *t = NULL;
    uint8_t *core = NULL;
    uint32_t acc = 0;
    size_t off = 0, esz;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (!cft_supports(dev, CFT_ADD, fmt) ||
        !cft_supports(dev, CFT_COPYSIGN, fmt))
        return CFT_ERR_UNSUPPORTED;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }

    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    aw = (uint8_t *)malloc(CHUNK * esz);
    mb = (uint8_t *)malloc(CHUNK * esz);
    t  = (uint8_t *)malloc(CHUNK * esz);
    core = (uint8_t *)malloc(CHUNK);
    if (!aw || !mb || !t || !core) {
        st = CFT_ERR_OUT_OF_MEMORY;
        goto out;
    }

    while (off < n) {
        size_t c = n - off > CHUNK ? CHUNK : n - off;
        const uint8_t *ap = (const uint8_t *)a + off * esz;
        uint8_t *dp = (uint8_t *)d + off * esz;
        cft_bn v, cval;
        size_t i;

        /* The magic constant C = 2^(p-1): the float whose ulp is 1. */
        cft_bn_zero(&cval);
        cft_bn_set_u32(&cval, (uint32_t)(f->man_w + f->bias));
        (void)cft_bn_shl(&cval, &cval, f->man_w);

        /* Classify. Lanes at or beyond 2^(p-1) are already integral
         * (and outside the trick's Sterbenz bound), infinities ride
         * with them; NaN lanes take the contract result directly so
         * the final copySign pass cannot stamp the operand's sign
         * onto the canonical NaN. Core lanes copy into aw; special
         * lanes get benign 1.0 so the passes stay quiet. */
        for (i = 0; i < c; i++) {
            lane_cls k;
            cft_bn xa;
            lane_load(f, ap, i, &xa);
            cls_of(f, &xa, &k);
            core[i] = 0;
            if (k.kind == K_NAN) {
                cft_sf_qnan(f, &v);
                if (k.signaling)
                    acc |= CFT_SF_INVALID;
            } else if (k.kind == K_INF ||
                       k.ef >= (uint32_t)(f->bias + f->man_w)) {
                cft_bn_copy(&v, &xa);
            } else {
                core[i] = 1;
                lane_store(f, aw, i, &xa);
                continue;
            }
            lane_store(f, dp, i, &v);
            bn_one_f(f, &v);
            lane_store(f, aw, i, &v);
        }

        for (i = 0; i < c; i++)
            lane_store(f, mb, i, &cval);

        /* m = copysign(C, x); t = (x + m) - m under the caller's
         * attribute; then x's sign restored, which is where the -0 of
         * roundToIntegral(-0.4) comes from. */
        st = step(dev, CFT_COPYSIGN, fmt, CFT_SF_RNE, mb, aw, NULL, mb, c,
                  bus_out);
        if (st != CFT_OK) goto out;
        st = step(dev, CFT_ADD, fmt, (int)rnd, aw, NULL, mb, t, c, bus_out);
        if (st != CFT_OK) goto out;
        st = step(dev, CFT_SUB, fmt, (int)rnd, t, NULL, mb, t, c, bus_out);
        if (st != CFT_OK) goto out;
        st = step(dev, CFT_COPYSIGN, fmt, CFT_SF_RNE, t, aw, NULL, t, c,
                  bus_out);
        if (st != CFT_OK) goto out;

        /* The contract flags are synthesised, never accumulated: the
         * adds' inexact was scaffolding. Only the Exact variant
         * reports rounding, as "this finite lane's bits changed". */
        for (i = 0; i < c; i++) {
            if (!core[i])
                continue;
            if (exact &&
                memcmp(t + i * esz, aw + i * esz, esz) != 0)
                acc |= CFT_SF_INEXACT;
            memcpy(dp + i * esz, t + i * esz, esz);
        }
        off += c;
    }
    st = CFT_OK;
    cft_flags_emit(dev, acc, flags_out);
out:
    free(aw); free(mb); free(t); free(core);
    return st;
}

/* ---- scaleB: composed (scaleb_seq) -------------------------------- */

/* The float 2^e as a lane constant, subnormal encodings included -
 * exact for every e down to the smallest subnormal, which is what
 * makes the multiply by it a single rounding of the true result. */
static int bn_scale_factor(const cft_fmt_desc *f, int e, cft_bn *v)
{
    if (e >= f->emin) {
        if (e > f->emax)
            return 1;
        cft_bn_zero(v);
        cft_bn_set_u32(v, (uint32_t)(e + f->bias));
        return cft_bn_shl(v, v, f->man_w);
    }
    if (e < f->emin - f->man_w)
        return 1;
    cft_bn_zero(v);
    cft_bn_set_u32(v, 1);
    return cft_bn_shl(v, v, e - (f->emin - f->man_w));
}

CFT_API cft_status cft_scaleb(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, int64_t nexp, void *d, size_t n,
                              uint32_t *flags_out, uint32_t *bus_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t esz;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (!cft_supports(dev, CFT_MUL, fmt))
        return CFT_ERR_UNSUPPORTED;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }

    f = &cft_sf_formats[(int)fmt];
    esz = (size_t)(f->width / 8);
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;

    if (nexp >= (int64_t)(f->emin - f->man_w)) {
        /* The composed path: multiplies by exact powers of two. One
         * multiply whenever 2^n is encodable; above emax, chunks of
         * 2^emax whose saturation scaleb_seq proves consistent. The
         * mul's own flags ARE the contract flags here - exact factor,
         * single rounding - so they are kept, not discarded, and the
         * stages OR (pre-final stages contribute nothing or the true
         * overflow). NaN, infinity and zero lanes ride the multiplies
         * to their contract results without any substitution. */
        int64_t remaining =
            nexp < 3 * (int64_t)f->emax ? nexp : 3 * (int64_t)f->emax;
        const void *src = a;
        uint8_t *fact;
        cft_bn v;
        size_t i, take, offel;

        fact = (uint8_t *)malloc(CHUNK * esz);
        if (!fact)
            return CFT_ERR_OUT_OF_MEMORY;
        for (;;) {
            int stepe = remaining >= 0
                ? (int)(remaining < f->emax ? remaining : f->emax)
                : (int)remaining;
            uint32_t fl = 0;
            if (bn_scale_factor(f, stepe, &v)) {
                free(fact);
                return CFT_ERR_INTERNAL;
            }
            for (i = 0; i < (n < CHUNK ? n : CHUNK); i++)
                lane_store(f, fact, i, &v);
            for (offel = 0; offel < n; offel += take) {
                int muted;
                take = n - offel > CHUNK ? CHUNK : n - offel;
                /* The mul's flags ARE scaleB's contract flags (the
                 * factor is exact), but they are collected here and
                 * emitted once at the end - so the pass itself stays
                 * muted like every other internal pass, and the word
                 * receives the whole operation's union rather than one
                 * chunk of one exponent step's. */
                muted = cft_flags_mute(dev, 1);
                st = cft_run(dev, CFT_MUL, fmt, rnd,
                             (const uint8_t *)src + offel * esz, fact, NULL,
                             (uint8_t *)d + offel * esz, take, &fl, bus_out);
                (void)cft_flags_mute(dev, muted);
                if (st != CFT_OK) {
                    free(fact);
                    return st;
                }
                acc |= fl;
            }
            remaining -= stepe;
            if (remaining == 0)
                break;
            src = d;
        }
        free(fact);
        cft_flags_emit(dev, acc, flags_out);
        return CFT_OK;
    }

    /* Below the smallest subnormal power there is no exact factor and
     * no double-rounding-safe uniform staging: the host packs each
     * lane once, exactly, at the shifted exponent. Clamped so the
     * shift arithmetic stays in int range; beyond the clamp every
     * lane's result is decided by sign and attribute alone. */
    {
        int64_t nc = nexp;
        int64_t floor_n = -(4 * (int64_t)f->emax + 2 * (int64_t)f->prec);
        size_t i;
        if (nc < floor_n)
            nc = floor_n;
        for (i = 0; i < n; i++) {
            lane_cls k;
            cft_bn xa, m, v;
            uint32_t fl = 0;
            int e;
            lane_load(f, (const uint8_t *)a, i, &xa);
            cls_of(f, &xa, &k);
            if (k.kind == K_NAN) {
                cft_sf_qnan(f, &v);
                if (k.signaling)
                    acc |= CFT_SF_INVALID;
            } else if (k.kind == K_INF || k.kind == K_ZERO) {
                cft_bn_copy(&v, &xa);
            } else {
                bn_sig_exp(f, &xa, &k, &m, &e);
                if (cft_sf_round_pack(f, k.sign, &m, e + (int)nc, 0,
                                      (int)rnd, &v, &fl))
                    return CFT_ERR_INTERNAL;
                acc |= fl;
            }
            lane_store(f, (uint8_t *)d, i, &v);
        }
        cft_flags_emit(dev, acc, flags_out);
        return CFT_OK;
    }
}

/* ---- signaling comparisons: composed ------------------------------ */

CFT_API cft_status cft_cmp_sig(cft_device *dev, cft_op cmp, cft_format fmt,
                               const void *a, const void *b, void *d,
                               size_t n, uint32_t *flags_out,
                               uint32_t *bus_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    if (cmp != CFT_CMPLT && cmp != CFT_CMPLE && cmp != CFT_CMPEQ)
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (!cft_supports(dev, cmp, fmt))
        return CFT_ERR_UNSUPPORTED;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (!b)
        return CFT_ERR_INVALID_ARGUMENT;

    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;

    /* The VALUE is the quiet predicate's value - unordered is false
     * either way. Only the flag differs: invalid for ANY NaN operand,
     * derived here by classification (before the run, because d may
     * alias a or b), while the run's own flags are discarded. */
    for (i = 0; i < n; i++) {
        lane_cls ka, kb;
        cft_bn x;
        lane_load(f, (const uint8_t *)a, i, &x);
        cls_of(f, &x, &ka);
        lane_load(f, (const uint8_t *)b, i, &x);
        cls_of(f, &x, &kb);
        if (ka.kind == K_NAN || kb.kind == K_NAN) {
            acc |= CFT_SF_INVALID;
            break;
        }
    }
    st = step(dev, cmp, fmt, CFT_SF_RNE, a, b, NULL, d, n, bus_out);
    if (st != CFT_OK)
        return st;
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---- format conversion: host -------------------------------------- */

CFT_API cft_status cft_convert(cft_device *dev, cft_format sfmt,
                               cft_format dfmt, cft_round rnd,
                               const void *a, void *d, size_t n,
                               uint32_t *flags_out)
{
    const cft_fmt_desc *fs, *fd;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    if ((int)dfmt < 0 || (int)dfmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, sfmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }

    fs = &cft_sf_formats[(int)sfmt];
    fd = &cft_sf_formats[(int)dfmt];
    if (size_overflows(fs, n) || size_overflows(fd, n))
        return CFT_ERR_INVALID_ARGUMENT;

    /* Elements change size, so unlike every same-format entry point d
     * MUST NOT overlap a (documented in cft.h): an in-place widening
     * would overwrite element i+1 while writing element i. */
    for (i = 0; i < n; i++) {
        lane_cls k;
        cft_bn xa, m, v;
        uint32_t fl = 0;
        int e;
        lane_load(fs, (const uint8_t *)a, i, &xa);
        cls_of(fs, &xa, &k);
        if (k.kind == K_NAN) {
            cft_sf_qnan(fd, &v);
            if (k.signaling)
                acc |= CFT_SF_INVALID;
        } else if (k.kind == K_INF) {
            cft_sf_inf(fd, k.sign, &v);
        } else if (k.kind == K_ZERO) {
            cft_sf_zero(fd, k.sign, &v);
        } else {
            bn_sig_exp(fs, &xa, &k, &m, &e);
            if (cft_sf_round_pack(fd, k.sign, &m, e, 0, (int)rnd, &v, &fl))
                return CFT_ERR_INTERNAL;
            acc |= fl;
        }
        lane_store(fd, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---- integer conversions: host ------------------------------------ */

static void bn_from_u64(cft_bn *v, uint64_t x)
{
    cft_bn t;
    cft_bn_zero(v);
    cft_bn_set_u32(v, (uint32_t)(x >> 32));
    (void)cft_bn_shl(v, v, 32);
    cft_bn_zero(&t);
    cft_bn_set_u32(&t, (uint32_t)(x & 0xffffffffu));
    (void)cft_bn_add(v, v, &t);
}

static uint64_t bn_low_u64(const cft_bn *v)
{
    return (uint64_t)cft_bn_extract(v, 0, 32) |
           ((uint64_t)cft_bn_extract(v, 32, 32) << 32);
}

static cft_status cvt_from_core(cft_device *dev, cft_format fmt,
                                cft_round rnd, const void *src, int elem_sz,
                                int is_signed, void *d, size_t n,
                                uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, fmt, src, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n) || n > ((size_t)-1) / (size_t)elem_sz)
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        uint64_t raw, mag;
        int sign = 0;
        cft_bn m, v;
        uint32_t fl = 0;
        /* Native typed loads, matching the pointee type each public
         * wrapper actually declares - these arrays are the caller's
         * ints, not interchange byte strings, so reading them as
         * little-endian bytes would silently swap on a big-endian
         * host (the adversarial review's F3). Widening a signed value
         * through int64_t and then to uint64_t is fully defined and
         * preserves the two's-complement pattern. */
        if (elem_sz == 4)
            raw = is_signed
                ? (uint64_t)(int64_t)((const int32_t *)src)[i]
                : (uint64_t)((const uint32_t *)src)[i];
        else
            raw = is_signed
                ? (uint64_t)((const int64_t *)src)[i]
                : ((const uint64_t *)src)[i];
        if (is_signed && (raw >> 63)) {
            sign = 1;
            mag = ~raw + 1;                  /* two's complement, exact */
        } else {
            mag = raw;
        }
        if (mag == 0) {
            cft_sf_zero(f, 0, &v);           /* integer zero is +0 */
        } else {
            bn_from_u64(&m, mag);
            if (cft_sf_round_pack(f, sign, &m, 0, 0, (int)rnd, &v, &fl))
                return CFT_ERR_INTERNAL;
            acc |= fl;
        }
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_cvt_from_i32(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const int32_t *src,
                                    void *d, size_t n, uint32_t *flags_out)
{
    return cvt_from_core(dev, fmt, rnd, src, 4, 1, d, n, flags_out);
}

CFT_API cft_status cft_cvt_from_u32(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const uint32_t *src,
                                    void *d, size_t n, uint32_t *flags_out)
{
    return cvt_from_core(dev, fmt, rnd, src, 4, 0, d, n, flags_out);
}

CFT_API cft_status cft_cvt_from_i64(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const int64_t *src,
                                    void *d, size_t n, uint32_t *flags_out)
{
    return cvt_from_core(dev, fmt, rnd, src, 8, 1, d, n, flags_out);
}

CFT_API cft_status cft_cvt_from_u64(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const uint64_t *src,
                                    void *d, size_t n, uint32_t *flags_out)
{
    return cvt_from_core(dev, fmt, rnd, src, 8, 0, d, n, flags_out);
}

/* One lane to one integer. Delivers RISC-V's FCVT table for the
 * invalid cases, as the model defines: NaN and +inf to the maximum,
 * -inf and negative overflow to the minimum; invalid pre-empts
 * inexact; and the Exact variants alone report inexact at all. */
static void cvt_to_lane(const cft_fmt_desc *f, const cft_bn *xa,
                        int width, int is_signed, int rnd, int exact,
                        uint64_t *out, uint32_t *fl)
{
    lane_cls k;
    uint64_t hi_mag, lo_mag, mag;
    int neg;
    cft_bn m, kept;
    int e, inexact = 0;

    /* Range edges as magnitudes: hi is the largest deliverable
     * positive, lo the largest deliverable negative magnitude. */
    if (is_signed) {
        hi_mag = (width == 32) ? 0x7fffffffull : 0x7fffffffffffffffull;
        lo_mag = hi_mag + 1;
    } else {
        hi_mag = (width == 32) ? 0xffffffffull : 0xffffffffffffffffull;
        lo_mag = 0;
    }
    *fl = 0;

    cls_of(f, xa, &k);
    if (k.kind == K_NAN) {
        *out = hi_mag;
        *fl = CFT_SF_INVALID;
        return;
    }
    if (k.kind == K_INF) {
        *out = k.sign ? (is_signed ? ~lo_mag + 1 : 0) : hi_mag;
        *fl = CFT_SF_INVALID;
        return;
    }
    if (k.kind == K_ZERO) {
        *out = 0;
        return;
    }

    bn_sig_exp(f, xa, &k, &m, &e);
    /* Beyond 2^66 no rounding can bring the magnitude into any 64-bit
     * range; inside it, the exact integer fits comfortably in the bn. */
    if (e + cft_bn_bitlen(&m) - 1 > 66) {
        *out = k.sign ? (is_signed ? ~lo_mag + 1 : 0) : hi_mag;
        *fl = CFT_SF_INVALID;
        return;
    }
    if (e >= 0) {
        if (cft_bn_shl(&kept, &m, e)) {
            *out = 0;                        /* unreachable, bounded above */
            *fl = CFT_SF_INVALID;
            return;
        }
    } else {
        /* Round at the integer grid. The bn primitives are total for
         * any shift - bits beyond the value read as zero, a shift past
         * the top yields zero - so one formula covers everything from
         * a half-ulp trim to a subnormal shifted out entirely. */
        int shift = -e;
        int guard = cft_bn_bit(&m, shift - 1);
        int sticky = cft_bn_low_nonzero(&m, shift - 1);
        cft_bn_shr(&kept, &m, shift);
        inexact = guard || sticky;
        if (inexact &&
            round_up_rule(rnd, k.sign, guard, sticky,
                          cft_bn_bit(&kept, 0)))
            (void)cft_bn_inc(&kept);
    }

    if (cft_bn_bitlen(&kept) > 64) {
        *out = k.sign ? (is_signed ? ~lo_mag + 1 : 0) : hi_mag;
        *fl = CFT_SF_INVALID;
        return;
    }
    mag = bn_low_u64(&kept);
    neg = k.sign && mag != 0;
    if (neg) {
        if (!is_signed || mag > lo_mag) {
            *out = is_signed ? ~lo_mag + 1 : 0;
            *fl = CFT_SF_INVALID;
            return;
        }
        *out = ~mag + 1;
    } else {
        if (mag > hi_mag) {
            *out = hi_mag;
            *fl = CFT_SF_INVALID;
            return;
        }
        *out = mag;
    }
    if (exact && inexact)
        *fl = CFT_SF_INEXACT;
}

static cft_status cvt_to_core(cft_device *dev, cft_format fmt, cft_round rnd,
                              int exact, const void *a, void *dst,
                              int elem_sz, int is_signed, size_t n,
                              uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    if (!rnd_ok(rnd))
        return CFT_ERR_INVALID_ARGUMENT;
    st = c5_validate(dev, fmt, a, dst, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n) || n > ((size_t)-1) / (size_t)elem_sz)
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        cft_bn xa;
        uint64_t out64;
        uint32_t fl;
        lane_load(f, (const uint8_t *)a, i, &xa);
        cvt_to_lane(f, &xa, elem_sz * 8, is_signed, (int)rnd, exact,
                    &out64, &fl);
        acc |= fl;
        /* Native typed stores, the mirror of cvt_from_core's loads
         * (writing through the unsigned counterpart of the declared
         * pointee type, which the aliasing rules permit). */
        if (elem_sz == 4)
            ((uint32_t *)dst)[i] = (uint32_t)out64;
        else
            ((uint64_t *)dst)[i] = out64;
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_cvt_to_i32(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  int32_t *dst, size_t n,
                                  uint32_t *flags_out)
{
    return cvt_to_core(dev, fmt, rnd, exact, a, dst, 4, 1, n, flags_out);
}

CFT_API cft_status cft_cvt_to_u32(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  uint32_t *dst, size_t n,
                                  uint32_t *flags_out)
{
    return cvt_to_core(dev, fmt, rnd, exact, a, dst, 4, 0, n, flags_out);
}

CFT_API cft_status cft_cvt_to_i64(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  int64_t *dst, size_t n,
                                  uint32_t *flags_out)
{
    return cvt_to_core(dev, fmt, rnd, exact, a, dst, 8, 1, n, flags_out);
}

CFT_API cft_status cft_cvt_to_u64(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  uint64_t *dst, size_t n,
                                  uint32_t *flags_out)
{
    return cvt_to_core(dev, fmt, rnd, exact, a, dst, 8, 0, n, flags_out);
}

/* ---- logB: host --------------------------------------------------- */

CFT_API cft_status cft_logb(cft_device *dev, cft_format fmt, const void *a,
                            void *d, size_t n, uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        lane_cls k;
        cft_bn xa, m, v;
        uint32_t fl = 0;
        int e, E;
        lane_load(f, (const uint8_t *)a, i, &xa);
        cls_of(f, &xa, &k);
        if (k.kind == K_NAN) {
            cft_sf_qnan(f, &v);
            if (k.signaling)
                acc |= CFT_SF_INVALID;
        } else if (k.kind == K_INF) {
            cft_sf_inf(f, 0, &v);
        } else if (k.kind == K_ZERO) {
            cft_sf_inf(f, 1, &v);
            acc |= CFT_SF_DIVZERO;
        } else {
            bn_sig_exp(f, &xa, &k, &m, &e);
            E = e + cft_bn_bitlen(&m) - 1;   /* value-based, subnormals too */
            if (E == 0) {
                cft_sf_zero(f, 0, &v);
            } else {
                cft_bn_zero(&m);
                cft_bn_set_u32(&m, (uint32_t)(E < 0 ? -E : E));
                if (cft_sf_round_pack(f, E < 0, &m, 0, 0, CFT_SF_RNE,
                                      &v, &fl) || fl != 0)
                    return CFT_ERR_INTERNAL;  /* |E| is always exact */
            }
        }
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---- nextUp / nextDown: host -------------------------------------- */

/* nextUp of one lane; the standard's own edges restated from the
 * model: -min_subnormal steps to -0, +max_normal to +inf with no
 * overflow signal, and only a signaling NaN says anything at all. */
static void next_up_lane(const cft_fmt_desc *f, const cft_bn *xa,
                         cft_bn *v, uint32_t *acc)
{
    lane_cls k;
    cls_of(f, xa, &k);
    if (k.kind == K_NAN) {
        cft_sf_qnan(f, v);
        if (k.signaling)
            *acc |= CFT_SF_INVALID;
        return;
    }
    if (k.kind == K_INF) {
        if (k.sign)
            bn_max_normal(f, 1, v);
        else
            cft_bn_copy(v, xa);
        return;
    }
    if (k.kind == K_ZERO) {
        cft_bn_zero(v);
        cft_bn_set_u32(v, 1);                /* +min_subnormal */
        return;
    }
    cft_bn_copy(v, xa);
    if (k.sign) {
        /* One step toward zero on the magnitude; the sign bit goes
         * back on unconditionally, because a magnitude that hit zero
         * is exactly the standard's -0 case. */
        cft_bn_clearbit(v, f->width - 1);
        cft_bn_dec(v);
        cft_bn_setbit(v, f->width - 1);
    } else {
        (void)cft_bn_inc(v);                 /* +max_normal + 1 IS +inf */
    }
}

CFT_API cft_status cft_next_up(cft_device *dev, cft_format fmt,
                               const void *a, void *d, size_t n,
                               uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    for (i = 0; i < n; i++) {
        cft_bn xa, v;
        lane_load(f, (const uint8_t *)a, i, &xa);
        next_up_lane(f, &xa, &v, &acc);
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_next_down(cft_device *dev, cft_format fmt,
                                 const void *a, void *d, size_t n,
                                 uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    for (i = 0; i < n; i++) {
        lane_cls k;
        cft_bn xa, v;
        lane_load(f, (const uint8_t *)a, i, &xa);
        cls_of(f, &xa, &k);
        if (k.kind == K_NAN) {
            /* handled before the negate trick, so the canonical NaN
             * comes back sign-positive */
            cft_sf_qnan(f, &v);
            if (k.signaling)
                acc |= CFT_SF_INVALID;
        } else {
            cft_bn t;
            cft_bn_copy(&t, &xa);
            if (cft_bn_bit(&t, f->width - 1))
                cft_bn_clearbit(&t, f->width - 1);
            else
                cft_bn_setbit(&t, f->width - 1);
            next_up_lane(f, &t, &v, &acc);
            if (cft_bn_bit(&v, f->width - 1))
                cft_bn_clearbit(&v, f->width - 1);
            else
                cft_bn_setbit(&v, f->width - 1);
        }
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---- classification: host ----------------------------------------- */

CFT_API cft_status cft_class(cft_device *dev, cft_format fmt, const void *a,
                             uint8_t *cls, size_t n)
{
    const cft_fmt_desc *f;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, cls, n);
    if (st != CFT_OK || n == 0)
        return st;
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    for (i = 0; i < n; i++) {
        lane_cls k;
        cft_bn xa;
        uint8_t code;
        lane_load(f, (const uint8_t *)a, i, &xa);
        cls_of(f, &xa, &k);
        switch (k.kind) {
        case K_INF:  code = k.sign ? CFT_CLASS_NEG_INF : CFT_CLASS_POS_INF;
            break;
        case K_NORM: code = k.sign ? CFT_CLASS_NEG_NORM : CFT_CLASS_POS_NORM;
            break;
        case K_SUB:  code = k.sign ? CFT_CLASS_NEG_SUB : CFT_CLASS_POS_SUB;
            break;
        case K_ZERO: code = k.sign ? CFT_CLASS_NEG_ZERO : CFT_CLASS_POS_ZERO;
            break;
        default:     code = k.signaling ? CFT_CLASS_SNAN : CFT_CLASS_QNAN;
            break;
        }
        cls[i] = code;
    }
    return CFT_OK;
}

/* ---- totalOrder: host --------------------------------------------- */

/* The 5.10 order-embedding: negative encodings complement, positive
 * encodings set the sign bit; one unsigned compare of the keys is the
 * whole predicate, NaN payload ordering included. */
static void torder_key(const cft_fmt_desc *f, const cft_bn *x, cft_bn *key)
{
    if (cft_bn_bit(x, f->width - 1)) {
        cft_bn full;
        cft_bn_zero(&full);
        cft_bn_set_u32(&full, 1);
        (void)cft_bn_shl(&full, &full, f->width);
        cft_bn_dec(&full);                   /* 2^width - 1 */
        cft_bn_xor(key, x, &full);
    } else {
        cft_bn_copy(key, x);
        cft_bn_setbit(key, f->width - 1);
    }
}

static cft_status torder_run(cft_device *dev, cft_format fmt, const void *a,
                             const void *b, void *d, size_t n, int mag)
{
    const cft_fmt_desc *f;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK || n == 0)
        return st;
    if (!b)
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    for (i = 0; i < n; i++) {
        cft_bn xa, xb, ka, kb, v;
        lane_load(f, (const uint8_t *)a, i, &xa);
        lane_load(f, (const uint8_t *)b, i, &xb);
        if (mag) {
            cft_bn_clearbit(&xa, f->width - 1);
            cft_bn_clearbit(&xb, f->width - 1);
        }
        torder_key(f, &xa, &ka);
        torder_key(f, &xb, &kb);
        if (cft_bn_cmp(&ka, &kb) <= 0)
            bn_one_f(f, &v);
        else
            cft_sf_zero(f, 0, &v);
        lane_store(f, (uint8_t *)d, i, &v);
    }
    return CFT_OK;
}

CFT_API cft_status cft_total_order(cft_device *dev, cft_format fmt,
                                   const void *a, const void *b, void *d,
                                   size_t n)
{
    return torder_run(dev, fmt, a, b, d, n, 0);
}

CFT_API cft_status cft_total_order_mag(cft_device *dev, cft_format fmt,
                                       const void *a, const void *b, void *d,
                                       size_t n)
{
    return torder_run(dev, fmt, a, b, d, n, 1);
}

/* ---- remainder: host ---------------------------------------------- */

/* One lane. Exact by definition; the walk peels one quotient bit per
 * step across the exponent gap in p-bit integer work, where the model
 * does one unbounded divmod. Only the quotient's PARITY matters (for
 * the tie), and every subtraction before the final step carries an
 * even weight, so parity is the last step's bit alone. */
static int rem_lane(const cft_fmt_desc *f, const cft_bn *xa,
                    const cft_bn *xb, cft_bn *v, uint32_t *acc)
{
    lane_cls ka, kb;
    cft_bn ma, mb, r, t;
    int ea, eb, lz, parity = 0, sign_r, cmp2;
    uint32_t fl = 0;

    cls_of(f, xa, &ka);
    cls_of(f, xb, &kb);
    if (ka.kind == K_NAN || kb.kind == K_NAN) {
        cft_sf_qnan(f, v);
        if (ka.signaling || kb.signaling)
            *acc |= CFT_SF_INVALID;
        return 0;
    }
    if (ka.kind == K_INF || kb.kind == K_ZERO) {
        cft_sf_qnan(f, v);
        *acc |= CFT_SF_INVALID;
        return 0;
    }
    if (kb.kind == K_INF || ka.kind == K_ZERO) {
        cft_bn_copy(v, xa);                  /* x exactly, sign included */
        return 0;
    }

    /* Normalise both magnitudes to exactly p bits. */
    bn_sig_exp(f, xa, &ka, &ma, &ea);
    bn_sig_exp(f, xb, &kb, &mb, &eb);
    lz = f->prec - cft_bn_bitlen(&ma);
    if (cft_bn_shl(&ma, &ma, lz))
        return 1;
    ea -= lz;
    lz = f->prec - cft_bn_bitlen(&mb);
    if (cft_bn_shl(&mb, &mb, lz))
        return 1;
    eb -= lz;

    if (ea < eb) {
        /* |x| < |y|. n is 0 or 1; 1 requires |x| > |y|/2, which pins
         * ea to exactly eb-1 (both significands are p bits), so the
         * only wide value here is mb doubled once. */
        int pos_x = ea + f->prec - 1;
        int pos_h = (eb - 1) + f->prec - 1;
        int c;
        if (pos_x < pos_h) {
            cft_bn_copy(v, xa);
            return 0;
        }
        if (pos_x > pos_h)
            return 1;                        /* impossible: ea < eb */
        c = cft_bn_cmp(&ma, &mb);
        if (c <= 0) {
            /* below the half, or the exact tie - whose n of {0, 1}
             * resolves to the even 0, leaving x untouched */
            cft_bn_copy(v, xa);
            return 0;
        }
        if (cft_bn_shl(&t, &mb, 1))
            return 1;
        cft_bn_sub(&t, &t, &ma);             /* |y| - |x| at grid 2^ea */
        sign_r = ka.sign ^ 1;
        if (cft_sf_round_pack(f, sign_r, &t, ea, 0, CFT_SF_RNE, v, &fl)
            || fl != 0)
            return 1;                        /* exactness is the theorem */
        return 0;
    }

    /* ea >= eb: the walk. Invariant entering each shift: r < mb. */
    cft_bn_copy(&r, &ma);
    if (ea == eb) {
        if (cft_bn_cmp(&r, &mb) >= 0) {
            cft_bn_sub(&r, &r, &mb);
            parity = 1;
        }
    } else {
        int e = ea;
        if (cft_bn_cmp(&r, &mb) >= 0)
            cft_bn_sub(&r, &r, &mb);         /* weight >= 2: parity even */
        while (e > eb) {
            if (cft_bn_is_zero(&r)) {
                parity = 0;                  /* remainder 0: tie unreachable */
                break;
            }
            if (cft_bn_shl(&r, &r, 1))
                return 1;
            e--;
            if (cft_bn_cmp(&r, &mb) >= 0) {
                cft_bn_sub(&r, &r, &mb);
                parity = 1;
            } else {
                parity = 0;
            }
        }
    }

    if (cft_bn_is_zero(&r)) {
        cft_sf_zero(f, ka.sign, v);          /* zero takes x's sign */
        return 0;
    }
    /* Nearest: compare 2r against mb; the tie goes to the even
     * quotient, i.e. steps only when the walked quotient was odd. */
    if (cft_bn_shl(&t, &r, 1))
        return 1;
    cmp2 = cft_bn_cmp(&t, &mb);
    if (cmp2 > 0 || (cmp2 == 0 && parity)) {
        cft_bn_sub(&t, &mb, &r);             /* mb - r */
        cft_bn_copy(&r, &t);
        sign_r = ka.sign ^ 1;
    } else {
        sign_r = ka.sign;
    }
    if (cft_sf_round_pack(f, sign_r, &r, eb, 0, CFT_SF_RNE, v, &fl)
        || fl != 0)
        return 1;                            /* exactness is the theorem */
    return 0;
}

CFT_API cft_status cft_rem(cft_device *dev, cft_format fmt, const void *a,
                           const void *b, void *d, size_t n,
                           uint32_t *flags_out)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (!b)
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;
    for (i = 0; i < n; i++) {
        cft_bn xa, xb, v;
        lane_load(f, (const uint8_t *)a, i, &xa);
        lane_load(f, (const uint8_t *)b, i, &xb);
        if (rem_lane(f, &xa, &xb, &v, &acc))
            return CFT_ERR_INTERNAL;
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---------------------------------------------------------------
 * The magnitude forms of minimum and maximum (754-2019 9.6, ABI 0.7)
 *
 * The other four of clause 9.6, quoted in cft.h and defined by the
 * standard purely by deferral:
 *
 *   "minimumMagnitude(x, y) is x if |x| < |y|, y if |y| < |x|,
 *    otherwise minimum(x, y)." (9.6)
 *
 * They live in this file rather than a new one because they are the
 * same KIND of operation as everything above - host-side bit surgery
 * on the encoding, no floating-point arithmetic, no pass to issue -
 * and because they are written out of exactly the lane helpers this
 * file already has (c5_validate, lane_load/lane_store, cls_of). A
 * second file would have had to copy all four.
 *
 * The base operations in the last position are the tile's opcodes 7
 * to 10, but issuing cft_run for them would be wrong here rather than
 * merely slow: cft_run gates on the device's min/max opcode group and
 * would refuse on a trimmed bitstream, where these four - being host
 * operations with no opcode of their own - are always available. So
 * the base rule is restated below, from the same 9.6 text
 * python/cft_golden/softfloat.py's _minmax implements, and
 * host/tests/minmax_mag_check.py holds the two identical over seeded
 * pools at all four formats.
 *
 * The whole operation, once the NaNs are out of the way, is a compare
 * of the two sign-cleared encodings: for non-NaN operands that bit
 * pattern is monotone in the magnitude, which is the same property
 * the ordering above relies on.
 * --------------------------------------------------------------- */

/* One lane of any of the four. want_max picks maximum over minimum;
 * number picks the ...Number form. Writes the result and ORs this
 * lane's exceptions into *acc. */
static void minmax_mag_lane(const cft_fmt_desc *f, const cft_bn *xa,
                            const cft_bn *xb, int want_max, int number,
                            cft_bn *v, uint32_t *acc)
{
    lane_cls ka, kb;
    cft_bn ma, mb;
    int cmp;

    cls_of(f, xa, &ka);
    cls_of(f, xb, &kb);

    /* 9.6 through 6.2: a signaling NaN operand signals invalid in
     * every one of the four, and it is the only exception any of them
     * can raise - there is no arithmetic here to be inexact. */
    if ((ka.kind == K_NAN && ka.signaling) ||
        (kb.kind == K_NAN && kb.signaling))
        *acc |= CFT_SF_INVALID;

    if (ka.kind == K_NAN || kb.kind == K_NAN) {
        /* |NaN| is unordered against everything, so both magnitude
         * tests are false and this is 9.6's "otherwise" - the base
         * operation's NaN rule, which is the whole difference between
         * the plain and the ...Number forms:
         *
         *   minimum/maximum: "a quiet NaN if either operand is a NaN,
         *   according to 6.2".
         *   minimumNumber/maximumNumber: "the number if one operand is
         *   a number and the other is a NaN ... If both operands are
         *   NaNs, a quiet NaN is returned ... unless both operands are
         *   NaNs, the signaling NaN is otherwise ignored and not
         *   converted to a quiet NaN".
         */
        if (!number || (ka.kind == K_NAN && kb.kind == K_NAN))
            cft_sf_qnan(f, v);
        else if (ka.kind == K_NAN)
            cft_bn_copy(v, xb);
        else
            cft_bn_copy(v, xa);
        return;
    }

    /* |a| against |b|, on the sign-cleared encodings. */
    cft_bn_copy(&ma, xa);
    cft_bn_copy(&mb, xb);
    cft_bn_clearbit(&ma, f->width - 1);
    cft_bn_clearbit(&mb, f->width - 1);
    cmp = cft_bn_cmp(&ma, &mb);

    if (cmp != 0) {
        /* The magnitude decides, and the sign has no say at all:
         * minimumMagnitude(-5, +1) is +1. */
        int take_a = want_max ? (cmp > 0) : (cmp < 0);
        cft_bn_copy(v, take_a ? xa : xb);
        return;
    }

    /* Equal magnitudes: 9.6's "otherwise" again, so the base
     * operation decides on the SIGN. Both forms agree here, since
     * neither operand is a NaN:
     *
     *   minimum: "x if x < y, y if y < x ... For this operation, -0
     *   compares less than +0. Otherwise (i.e., when x = y and signs
     *   are the same) it is either x or y."
     *
     * Equal magnitude with equal sign means x = y and the standard
     * leaves the choice open; this contract takes x, which is what
     * the model does and what makes the answer a function of the
     * operand bits rather than of an implementation's mood. Equal
     * magnitude with DIFFERENT signs is the interesting row: the
     * negative one is the smaller, the positive one the larger, and
     * that covers +-0 as a special case of itself. */
    if (ka.sign == kb.sign) {
        cft_bn_copy(v, xa);
        return;
    }
    /* ka.sign != kb.sign: a is the negative one iff ka.sign. */
    if (want_max)
        cft_bn_copy(v, ka.sign ? xb : xa);
    else
        cft_bn_copy(v, ka.sign ? xa : xb);
}

static cft_status minmax_mag_batch(cft_device *dev, cft_format fmt,
                                   const void *a, const void *b, void *d,
                                   size_t n, uint32_t *flags_out,
                                   int want_max, int number)
{
    const cft_fmt_desc *f;
    uint32_t acc = 0;
    size_t i;
    cft_status st;

    st = c5_validate(dev, fmt, a, d, n);
    if (st != CFT_OK)
        return st;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (!b)
        return CFT_ERR_INVALID_ARGUMENT;
    f = &cft_sf_formats[(int)fmt];
    if (size_overflows(f, n))
        return CFT_ERR_INVALID_ARGUMENT;

    for (i = 0; i < n; i++) {
        cft_bn xa, xb, v;
        /* Both operands read before the store, so d may alias either. */
        lane_load(f, (const uint8_t *)a, i, &xa);
        lane_load(f, (const uint8_t *)b, i, &xb);
        minmax_mag_lane(f, &xa, &xb, want_max, number, &v, &acc);
        lane_store(f, (uint8_t *)d, i, &v);
    }
    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

CFT_API cft_status cft_min_mag(cft_device *dev, cft_format fmt,
                               const void *a, const void *b, void *d,
                               size_t n, uint32_t *flags_out)
{
    return minmax_mag_batch(dev, fmt, a, b, d, n, flags_out, 0, 0);
}

CFT_API cft_status cft_max_mag(cft_device *dev, cft_format fmt,
                               const void *a, const void *b, void *d,
                               size_t n, uint32_t *flags_out)
{
    return minmax_mag_batch(dev, fmt, a, b, d, n, flags_out, 1, 0);
}

CFT_API cft_status cft_minnum_mag(cft_device *dev, cft_format fmt,
                                  const void *a, const void *b, void *d,
                                  size_t n, uint32_t *flags_out)
{
    return minmax_mag_batch(dev, fmt, a, b, d, n, flags_out, 0, 1);
}

CFT_API cft_status cft_maxnum_mag(cft_device *dev, cft_format fmt,
                                  const void *a, const void *b, void *d,
                                  size_t n, uint32_t *flags_out)
{
    return minmax_mag_batch(dev, fmt, a, b, d, n, flags_out, 1, 1);
}
