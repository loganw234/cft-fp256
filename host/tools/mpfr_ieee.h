/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The MPFR oracle's IEEE emulation, shared: host/tools/mpfr_check.c (where
 * it was written, and whose header explains every choice in it) and the
 * wide modes of host/tools/divsqrt_soak.c (parcel HXa, 2026-10-26) both
 * include this file, so the soak's fp128 and fp256 oracle is mpfr-check's
 * emulation and not a second one.
 *
 * Moved here from mpfr_check.c as it stood at 0192ab11, unchanged but in
 * one respect: oracle() and c5_round_into() read the attribute from that
 * file's MODES table by index, and here they take it as two parameters
 * (the MPFR rounding and whether the attribute is RMM) - ieee_oracle()
 * and ieee_round_into(). mpfr_check.c keeps oracle() and c5_round_into()
 * as one-line wrappers that pass MODES[mi].mr and MODES[mi].cr == CFT_RMM,
 * which is what their bodies read before.
 *
 * In brief (mpfr_check.c's header has the argument): each case is computed
 * twice, at the format's precision with MPFR's own exponent range
 * (unbounded for every format here) and, for a subnormal landing, again at
 * the format's range with mpfr_subnormalize; overflow and underflow fall
 * out of the unbounded result against the format's thresholds (tininess
 * after rounding); inexact is the ternary; invalid and divideByZero come
 * from the operand classes. RMM is built from a truncation to p + 1 bits
 * (the guard) and its ternary (the sticky). NaN compares as a class.
 */
#ifndef CFT_MPFR_IEEE_H
#define CFT_MPFR_IEEE_H

#include <stdint.h>
#include <string.h>

#include <gmp.h>
#include <mpfr.h>

#include "../include/cft.h"

typedef struct {
    const char *name;
    cft_format fmt;
    int exp_w, man_w;
    int p;                     /* man_w + 1 */
    long emax, emin;           /* IEEE unbiased normal range */
    size_t esz;
} fdesc;

typedef enum { OP_ADD, OP_SUB, OP_MUL, OP_FMA, OP_DIV, OP_SQRT, NOPS }
    mop;

/* ---- bit-level classify (works on the little-endian encoding) ----- */

typedef struct { int sign, is_nan, is_snan, is_inf, is_zero; } cls;

static int bit_at(const uint8_t *b, int i) { return (b[i >> 3] >> (i & 7)) & 1; }

static void classify(const fdesc *f, const uint8_t *b, cls *c)
{
    int w = 1 + f->exp_w + f->man_w, i;
    int eones = 1, mzero = 1;
    c->sign = bit_at(b, w - 1);
    for (i = 0; i < f->exp_w; i++)
        if (!bit_at(b, f->man_w + i)) { eones = 0; break; }
    for (i = 0; i < f->man_w; i++)
        if (bit_at(b, i)) { mzero = 0; break; }
    c->is_nan  = eones && !mzero;
    c->is_snan = c->is_nan && !bit_at(b, f->man_w - 1);
    c->is_inf  = eones && mzero;
    {
        int ezero = 1;
        for (i = 0; i < f->exp_w; i++)
            if (bit_at(b, f->man_w + i)) { ezero = 0; break; }
        c->is_zero = ezero && mzero;
    }
}

/* ---- encoding -> mpfr (exact) ------------------------------------- */

static void enc_to_mpfr(const fdesc *f, const uint8_t *b, mpfr_t x)
{
    cls c;
    classify(f, b, &c);
    if (c.is_nan)  { mpfr_set_nan(x); return; }
    if (c.is_inf)  { mpfr_set_inf(x, c.sign ? -1 : 1); return; }
    if (c.is_zero) { mpfr_set_zero(x, c.sign ? -1 : 1); return; }
    {
        mpz_t enc, man;
        unsigned long biased;
        long e;
        mpz_init(enc); mpz_init(man);
        mpz_import(enc, f->esz, -1, 1, 0, 0, b);
        mpz_fdiv_r_2exp(man, enc, f->man_w);
        mpz_fdiv_q_2exp(enc, enc, f->man_w);
        biased = mpz_get_ui(enc) & ((1ul << f->exp_w) - 1);
        if (biased) {
            mpz_setbit(man, f->man_w);
            e = (long)biased - f->emax - f->man_w;
        } else {
            e = f->emin - f->man_w;
        }
        mpfr_set_z_2exp(x, man, e, MPFR_RNDN);     /* <= p bits: exact */
        if (c.sign)
            mpfr_neg(x, x, MPFR_RNDN);
        mpz_clear(enc); mpz_clear(man);
    }
}

/* ---- the oracle ---------------------------------------------------- */

static void raw_op(mpfr_t r, mop op, const mpfr_t a, const mpfr_t b,
                   const mpfr_t c, mpfr_rnd_t rnd, int *tern)
{
    switch (op) {
    case OP_ADD:  *tern = mpfr_add(r, a, c, rnd); break;   /* b unused */
    case OP_SUB:  *tern = mpfr_sub(r, a, c, rnd); break;
    case OP_MUL:  *tern = mpfr_mul(r, a, b, rnd); break;
    case OP_FMA:  *tern = mpfr_fma(r, a, b, c, rnd); break;
    case OP_DIV:  *tern = mpfr_div(r, a, b, rnd); break;
    default:      *tern = mpfr_sqrt(r, a, rnd); break;
    }
}

/* Round the pure value held as (y truncated to p+1 bits, sticky) to
 * `prec` bits ties-to-away, into r at that precision. y must be
 * finite nonzero. The guard is y's lowest kept bit at prec+1; a tie
 * is sticky==0 && guard==1. */
static void rmm_round(mpfr_t r, const mpfr_t y, int sticky, mpfr_prec_t prec)
{
    mpfr_t t;
    int guard;
    mpfr_init2(t, prec + 1);
    mpfr_set(t, y, MPFR_RNDZ);              /* may drop bits: fold below */
    if (!mpfr_equal_p(t, y))
        sticky = 1;
    {
        /* guard = lowest significant bit of the prec+1 view */
        mpz_t z;
        mpfr_exp_t e;
        mpz_init(z);
        e = mpfr_get_z_2exp(z, t);
        (void)e;
        guard = mpz_odd_p(z) ? 1 : 0;
        mpz_clear(z);
    }
    mpfr_set_prec(r, prec);
    if (guard && !sticky)
        mpfr_set(r, t, MPFR_RNDA);          /* exact tie: away */
    else if (guard)
        mpfr_set(r, t, MPFR_RNDA);          /* above midpoint: away */
    else
        mpfr_set(r, t, MPFR_RNDZ);          /* below midpoint: down */
    mpfr_clear(t);
}

/* One case through MPFR: result encoded as an mpfr value clamped to
 * the format (or inf/nan), plus contract flags. rnd is the attribute's
 * MPFR rounding (MPFR_RNDN for RMM), is_rmm whether it is RMM. */
static void ieee_oracle(const fdesc *f, mop op, mpfr_rnd_t rnd, int is_rmm,
                        const uint8_t *ba, const uint8_t *bb,
                        const uint8_t *bc, mpfr_t out, uint32_t *flags)
{
    mpfr_t a, b, c, runb, r, y;
    cls ca, cb, cc;
    int tunb = 0, inexact, nan_in = 0;
    uint32_t fl = 0;

    classify(f, ba, &ca);
    classify(f, bb, &cb);
    classify(f, bc, &cc);

    mpfr_init2(a, f->p); mpfr_init2(b, f->p); mpfr_init2(c, f->p);
    mpfr_init2(runb, f->p); mpfr_init2(r, f->p);
    mpfr_init2(y, f->p + 1);
    enc_to_mpfr(f, ba, a);
    enc_to_mpfr(f, bb, b);
    enc_to_mpfr(f, bc, c);

    /* Which operands the op actually reads - the steering makes ADD
     * ignore b and MUL ignore c, and both the sNaN rule and the
     * NaN-source rule below must honour that, or an unread qNaN in c
     * absolves an inf*0 of its invalid. */
    {
        int use_b = (op == OP_MUL || op == OP_FMA || op == OP_DIV);
        int use_c = (op == OP_ADD || op == OP_SUB || op == OP_FMA);
        if (ca.is_snan || (use_b && cb.is_snan) || (use_c && cc.is_snan))
            fl |= CFT_FLAG_INVALID;
        nan_in = ca.is_nan || (use_b && cb.is_nan) || (use_c && cc.is_nan);
    }
    /* divideByZero: finite nonzero / exact zero */
    if (op == OP_DIV && cb.is_zero && !ca.is_zero && !ca.is_nan &&
        !ca.is_inf)
        fl |= CFT_FLAG_DIVBYZERO;

    /* Unbounded-range result at p bits: the over/underflow authority.
     * (Also the RMM candidate when the landing is normal.) */
    if (is_rmm) {
        int t1;
        raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
        if (!mpfr_number_p(y) || mpfr_zero_p(y)) {
            mpfr_set(runb, y, MPFR_RNDN);
            tunb = 0;
        } else {
            rmm_round(runb, y, t1 != 0, f->p);
            tunb = !mpfr_equal_p(runb, y) || t1;
        }
    } else {
        raw_op(runb, op, a, b, c, rnd, &tunb);
    }

    /* invalid from the operation itself: NaN out of non-NaN in */
    if (mpfr_nan_p(runb) && !nan_in)
        fl |= CFT_FLAG_INVALID;

    inexact = (tunb != 0);

    if (mpfr_nan_p(runb) || mpfr_inf_p(runb) || mpfr_zero_p(runb)) {
        mpfr_set(out, runb, MPFR_RNDN);
        /* exact specials carry only the class flags computed above;
         * an inf produced EXACTLY (x/0, inf+inf) is not an overflow */
        if (inexact) fl |= CFT_FLAG_INEXACT;
        *flags = fl;
        goto done;
    }

    {
        mpfr_exp_t e_unb = mpfr_get_exp(runb);   /* value in [2^(e-1),2^e) */
        long e_res = (long)e_unb - 1;            /* IEEE-style exponent */

        if (e_res > f->emax) {
            /* overflow: after-rounding, from the unbounded result -
             * the same test round_pack applies. Delivery per mode. */
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ) away = 0;
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                /* max normal, built exactly */
                mpfr_set_ui_2exp(out, 1, f->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0) mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
            goto done;
        }

        if (e_res >= f->emin) {
            /* normal landing: the unbounded result IS the answer */
            mpfr_set(out, runb, MPFR_RNDN);
            if (inexact) fl |= CFT_FLAG_INEXACT;
            *flags = fl;
            goto done;
        }

        /* subnormal landing: re-round the TRUE value on the fixed
         * grid 2^(emin - man_w). For the four native modes MPFR does
         * it (compute at range, subnormalize); for RMM the p+1 view
         * re-rounds on the grid. Tininess is after-rounding by
         * construction here: we only got here because |runb| (the
         * p-bit unbounded rounding) fell below 2^emin. */
        if (!is_rmm) {
            mpfr_exp_t save_emin = mpfr_get_emin();
            mpfr_exp_t save_emax = mpfr_get_emax();
            int t2;
            mpfr_set_emin(f->emin - f->p + 2);
            mpfr_set_emax(f->emax + 1);
            raw_op(r, op, a, b, c, rnd, &t2);
            t2 = mpfr_check_range(r, t2, rnd);
            t2 = mpfr_subnormalize(r, t2, rnd);
            mpfr_set_emin(save_emin);
            mpfr_set_emax(save_emax);
            mpfr_set(out, r, MPFR_RNDN);
            if (t2 != 0 || inexact) fl |= CFT_FLAG_INEXACT;
            if ((t2 != 0 || inexact)) fl |= CFT_FLAG_UNDERFLOW;
            *flags = fl;
        } else {
            /* RMM on the subnormal grid. The grid POSITION is fixed at
             * 2^(emin - man_w) regardless of magnitude, so this cannot
             * be a precision-relative rounding (the first version was,
             * and returned unrounded values for anything below the
             * grid). Ties-to-away collapses to round-half-away on the
             * magnitude: away iff the fractional grid part >= 1/2 -
             * the truncation sticky cannot promote a below-half
             * fraction to half, and at exactly half both the tie and
             * the above-tie case go away. Every step is exact
             * MPFR/GMP arithmetic. */
            int t1, up, sign;
            long grid = f->emin - f->man_w;
            mpz_t n;
            mpfr_t scaled, frac, half;
            raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
            sign = mpfr_signbit(y) != 0;       /* a signed zero keeps it */
            mpz_init(n);
            mpfr_init2(scaled, f->p + 4);
            mpfr_init2(frac, f->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);  /* exact */
            mpfr_get_z(n, scaled, MPFR_RNDZ);                /* floor */
            mpfr_sub_z(frac, scaled, n, MPFR_RNDN);          /* exact */
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(n, n, 1);
            mpfr_set_prec(out, f->p);
            mpfr_set_z_2exp(out, n, grid, MPFR_RNDN);        /* exact */
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
            if (!mpfr_zero_p(frac) || t1)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(n);
            mpfr_clear(scaled); mpfr_clear(frac); mpfr_clear(half);
            *flags = fl;
        }
        goto done;
    }

done:
    mpfr_clear(a); mpfr_clear(b); mpfr_clear(c);
    mpfr_clear(runb); mpfr_clear(r); mpfr_clear(y);
}

/* ---- comparison ---------------------------------------------------- */

static int agree(const fdesc *f, const uint8_t *got, const mpfr_t want)
{
    mpfr_t g;
    int ok;
    cls c;
    classify(f, got, &c);
    if (mpfr_nan_p(want))
        return c.is_nan;
    mpfr_init2(g, f->p);
    enc_to_mpfr(f, got, g);
    if (mpfr_zero_p(want) && mpfr_zero_p(g))
        ok = (mpfr_signbit(want) != 0) == (mpfr_signbit(g) != 0);
    else
        ok = mpfr_equal_p(g, want) &&
             (mpfr_signbit(want) != 0) == (mpfr_signbit(g) != 0);
    mpfr_clear(g);
    return ok;
}

static void hexdump(const uint8_t *b, size_t n, char *out)
{
    static const char d[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = d[b[n - 1 - i] >> 4];
        out[2 * i + 1] = d[b[n - 1 - i] & 0xf];
    }
    out[2 * n] = 0;
}

/* Round the EXACT finite value x into format f under the attribute
 * (rnd, is_rmm), with ieee_oracle()'s own delivery derivation: the
 * unbounded p-bit rounding is the overflow/underflow authority
 * (tininess after rounding by construction), subnormal landings
 * re-round the true value on the fixed grid, RMM goes through the p+1
 * guard/sticky build. Where ieee_oracle() recomputes the operation,
 * this rounds a known value - every clause-5 rounding is one rounding
 * of an exactly-held value, so mpfr_set IS the operation here. */
static void ieee_round_into(const fdesc *f, const mpfr_t x, mpfr_rnd_t rnd,
                            int is_rmm, mpfr_t out, uint32_t *flags)
{
    mpfr_t runb, y;
    int inexact;
    uint32_t fl = 0;

    if (mpfr_zero_p(x)) {
        mpfr_set_prec(out, f->p);
        mpfr_set(out, x, MPFR_RNDN);         /* signed zero rides along */
        *flags = 0;
        return;
    }

    mpfr_init2(runb, f->p);
    mpfr_init2(y, f->p + 1);
    if (is_rmm) {
        int t1 = mpfr_set(y, x, MPFR_RNDZ);
        rmm_round(runb, y, t1 != 0, f->p);
    } else {
        (void)mpfr_set(runb, x, rnd);
    }
    inexact = !mpfr_equal_p(runb, x);

    {
        mpfr_exp_t e_unb = mpfr_get_exp(runb);
        long e_res = (long)e_unb - 1;

        if (e_res > f->emax) {
            /* after-rounding overflow, delivery per mode - the same
             * block ieee_oracle() applies */
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ)
                away = 0;
            mpfr_set_prec(out, f->p);
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                mpfr_set_ui_2exp(out, 1, f->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0)
                    mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        } else if (e_res >= f->emin) {
            mpfr_set_prec(out, f->p);
            mpfr_set(out, runb, MPFR_RNDN);
            *flags = inexact ? (fl | CFT_FLAG_INEXACT) : fl;
        } else if (!is_rmm) {
            /* subnormal landing, native modes: the MPFR recipe at the
             * format's range, on the exact value */
            mpfr_exp_t save_emin = mpfr_get_emin();
            mpfr_exp_t save_emax = mpfr_get_emax();
            mpfr_t r;
            int t2;
            mpfr_init2(r, f->p);
            mpfr_set_emin(f->emin - f->p + 2);
            mpfr_set_emax(f->emax + 1);
            t2 = mpfr_set(r, x, rnd);
            t2 = mpfr_check_range(r, t2, rnd);
            t2 = mpfr_subnormalize(r, t2, rnd);
            mpfr_set_emin(save_emin);
            mpfr_set_emax(save_emax);
            mpfr_set_prec(out, f->p);
            mpfr_set(out, r, MPFR_RNDN);
            if (t2 != 0 || inexact)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            *flags = fl;
            mpfr_clear(r);
        } else {
            /* RMM on the fixed subnormal grid - ieee_oracle()'s block,
             * on the p+1 truncation of the exact value. The granularity
             * of the truncated fraction in grid units is 2^(exp-emin-2)
             * <= 1/4 and the truncation error is below one granule, so
             * the >= 1/2 decision cannot be crossed by truncating. */
            int t1b, up, sgn;
            long grid = f->emin - f->man_w;
            mpz_t nn;
            mpfr_t scaled, frac, half;
            t1b = mpfr_set(y, x, MPFR_RNDZ);
            sgn = mpfr_signbit(y) != 0;        /* a signed zero keeps it */
            mpz_init(nn);
            mpfr_init2(scaled, f->p + 4);
            mpfr_init2(frac, f->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);   /* exact */
            mpfr_get_z(nn, scaled, MPFR_RNDZ);                /* floor */
            mpfr_sub_z(frac, scaled, nn, MPFR_RNDN);          /* exact */
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(nn, nn, 1);
            mpfr_set_prec(out, f->p);
            mpfr_set_z_2exp(out, nn, grid, MPFR_RNDN);        /* exact */
            if (sgn)
                mpfr_neg(out, out, MPFR_RNDN);
            if (!mpfr_zero_p(frac) || t1b)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(nn);
            mpfr_clear(scaled);
            mpfr_clear(frac);
            mpfr_clear(half);
            *flags = fl;
        }
    }
    mpfr_clear(runb);
    mpfr_clear(y);
}

#endif /* CFT_MPFR_IEEE_H */
