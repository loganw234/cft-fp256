/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Parity with GNU MPFR: the third oracle, and the first independent
 * one that reaches every rung.
 *
 * The golden model is the definition of correct, and the CPU soak
 * checks fp32/fp64 against silicon nobody here designed - but silicon
 * stops at binary64. MPFR is the arbitrary-precision library the rest
 * of the world already treats as the reference for correctly-rounded
 * arithmetic, it computes at ANY precision, and it was written by
 * people who have never seen this project. Agreement at fp128 and
 * fp256 is therefore the strongest external evidence available this
 * side of silicon - and disagreement at fp32/fp64, where the CPU
 * campaign has already proven 23.9 billion cases, would indict this
 * HARNESS rather than the library, which is exactly the
 * self-calibration a new oracle needs.
 *
 * IEEE emulation follows the MPFR manual's own recipe: precision p,
 * mpfr_set_emin(emin - p + 2), mpfr_set_emax(emax + 1), compute, then
 * mpfr_check_range + mpfr_subnormalize with the ternary. Results are
 * compared in the MPFR domain (both sides converted exactly), NaN as
 * a CLASS (MPFR keeps no payloads; the model's canonicalisation is
 * pinned by its own tests), zeros by sign.
 *
 * Flags are NOT taken from MPFR's sticky flags, deliberately. The
 * contract defines underflow as tininess AFTER rounding AND inexact
 * (round_pack's q_unb test); MPFR's underflow flag has its own
 * definition, and reconciling definitions is how subtle disagreements
 * get explained away instead of found. Instead every case is computed
 * twice - once with the format's exponent range, once unbounded at
 * the same precision - and overflow/underflow fall out of comparing
 * the unbounded result against the format's thresholds: the same
 * derivation round_pack uses, computed by the oracle's arithmetic.
 * Inexact is the final ternary; invalid and divideByZero come from
 * operand classes (sNaN inputs classified from the bits, since MPFR
 * has no signaling NaNs - documented one-sided help to the oracle).
 *
 * Rounding modes: RNE/RTZ/RDN/RUP map directly onto MPFR. RMM
 * (ties-to-away) has NO MPFR equivalent - MPFR_RNDA rounds every
 * inexact value away, not just ties - so RMM is built from pure-MPFR
 * intermediates by the standard construction: truncate to p+1 bits
 * (RNDZ, ternary kept), where the extra bit is the guard and the
 * ternary is the sticky; a tie is exactly "ternary zero and guard
 * set", which rounds away, and everything else follows the RNE
 * decision. Subnormal landings redo the decision on the format's
 * fixed subnormal grid. The construction is a dozen lines and each
 * intermediate is MPFR's own arithmetic; it is labelled where it
 * runs, because an oracle with a footnote should say so.
 *
 * Usage:  mpfr-check [randoms-per-format] [seed]
 *         (directed specials always run; randoms are exponent-banded)
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
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

static const fdesc FMTS[4] = {
    { "fp32",  CFT_FP32,   8,  23,  24,    127,    -126,  4 },
    { "fp64",  CFT_FP64,  11,  52,  53,   1023,   -1022,  8 },
    { "fp128", CFT_FP128, 15, 112, 113,  16383,  -16382, 16 },
    { "fp256", CFT_FP256, 19, 236, 237, 262143, -262142, 32 },
};

static const struct { const char *name; cft_round cr; mpfr_rnd_t mr; }
MODES[5] = {
    { "rne", CFT_RNE, MPFR_RNDN },
    { "rtz", CFT_RTZ, MPFR_RNDZ },
    { "rdn", CFT_RDN, MPFR_RNDD },
    { "rup", CFT_RUP, MPFR_RNDU },
    { "rmm", CFT_RMM, MPFR_RNDN },   /* via the p+1 construction */
};

typedef enum { OP_ADD, OP_SUB, OP_MUL, OP_FMA, OP_DIV, OP_SQRT, NOPS }
    mop;
static const char *const OPN[NOPS] =
    { "add", "sub", "mul", "fma", "div", "sqrt" };
static const int OP_NARGS[NOPS] = { 2, 2, 2, 3, 2, 1 };

static uint64_t mismatches, flag_mismatches, cases;
static int shown;
static cft_device *dev;

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
 * the format (or inf/nan), plus contract flags. */
static void oracle(const fdesc *f, mop op, int mi,
                   const uint8_t *ba, const uint8_t *bb, const uint8_t *bc,
                   mpfr_t out, uint32_t *flags)
{
    mpfr_t a, b, c, runb, r, y;
    cls ca, cb, cc;
    int tunb = 0, inexact, nan_in = 0,
        is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
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
            sign = mpfr_sgn(y) < 0;
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

/* ---- the library side --------------------------------------------- */

static uint32_t lib_flags(const fdesc *f, mop op, cft_round rnd,
                          const uint8_t *a, const uint8_t *b,
                          const uint8_t *c, uint8_t *d)
{
    uint32_t fl = 0;
    switch (op) {
    case OP_ADD: cft_run(dev, CFT_ADD, f->fmt, rnd, a, NULL, c, d, 1,
                         &fl, NULL); break;
    case OP_SUB: cft_run(dev, CFT_SUB, f->fmt, rnd, a, NULL, c, d, 1,
                         &fl, NULL); break;
    case OP_MUL: cft_run(dev, CFT_MUL, f->fmt, rnd, a, b, NULL, d, 1,
                         &fl, NULL); break;
    case OP_FMA: cft_run(dev, CFT_FMA, f->fmt, rnd, a, b, c, d, 1,
                         &fl, NULL); break;
    case OP_DIV: cft_div(dev, f->fmt, rnd, a, b, d, 1, &fl, NULL); break;
    default:     cft_sqrt(dev, f->fmt, rnd, a, d, 1, &fl, NULL); break;
    }
    return fl;
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

/* ---- operand pools ------------------------------------------------- */

static uint64_t rs;
static uint64_t rng(void)
{
    uint64_t x = rs;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return rs = x;
}

static void set_field(uint8_t *b, int lo, int n, uint64_t v)
{
    int i;
    for (i = 0; i < n; i++) {
        int bit = lo + i;
        if ((v >> i) & 1) b[bit >> 3] |= (uint8_t)(1u << (bit & 7));
        else              b[bit >> 3] &= (uint8_t)~(1u << (bit & 7));
    }
}

static void rand_enc(const fdesc *f, uint8_t *b)
{
    size_t i;
    for (i = 0; i < f->esz; i++)
        b[i] = (uint8_t)rng();
    if ((rng() & 3) == 0) {
        /* band the exponent toward the edges, as the CPU soak does */
        unsigned long span = (2ul << (f->exp_w - 1)) - 1;
        unsigned long base[7] = {0, 1, 2, span / 2, span - 3, span - 2,
                                 span - 1};
        unsigned long e = base[rng() % 7] + (unsigned long)(rng() % 3);
        if (e > span) e = span;
        set_field(b, f->man_w, f->exp_w, e);
    }
}

#define MAXPOOL 64

static int build_pool(const fdesc *f, uint8_t pool[][32], int randoms)
{
    int n = 0, w = 1 + f->exp_w + f->man_w;
    memset(pool, 0, sizeof(uint8_t) * MAXPOOL * 32);

    /* +0 */                                                     n++;
    /* -0 */  set_field(pool[n], w - 1, 1, 1);                   n++;
    /* +inf */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);     n++;
    /* -inf */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], w - 1, 1, 1);                  n++;
    /* qNaN */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], f->man_w - 1, 1, 1);           n++;
    /* sNaN */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], 0, 1, 1);                      n++;
    /* min sub */ set_field(pool[n], 0, 1, 1);                   n++;
    /* max sub */ set_field(pool[n], 0, 1, 0);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* min normal */ set_field(pool[n], f->man_w, f->exp_w, 1);  n++;
    /* max normal */ set_field(pool[n], f->man_w, f->exp_w,
                               (1ul << f->exp_w) - 2);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* 1.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);                n++;
    /* 1.0 - ulp (largest < 1) */
               set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax - 1);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* 1.0 + ulp */
               set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);
               set_field(pool[n], 0, 1, 1);                      n++;
    /* 2.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);            n++;
    /* 3.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);
               set_field(pool[n], f->man_w - 1, 1, 1);           n++;
    /* 0.5 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax - 1);            n++;
    /* -1.0 */ set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);
               set_field(pool[n], w - 1, 1, 1);                  n++;
    /* -3.0 */ set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);
               set_field(pool[n], f->man_w - 1, 1, 1);
               set_field(pool[n], w - 1, 1, 1);                  n++;

    while (n < MAXPOOL && randoms-- > 0)
        rand_enc(f, pool[n++]);
    return n;
}

/* ---- driver -------------------------------------------------------- */

static void report(const fdesc *f, mop op, int mi, const uint8_t *a,
                   const uint8_t *b, const uint8_t *c,
                   const uint8_t *got, const mpfr_t want,
                   uint32_t gf, uint32_t wf, int value_bad)
{
    char ha[65], hb[65], hc[65], hg[65];
    if (shown >= 16) return;
    shown++;
    hexdump(a, f->esz, ha); hexdump(b, f->esz, hb);
    hexdump(c, f->esz, hc); hexdump(got, f->esz, hg);
    printf("  %s %s %s %s a=0x%s b=0x%s c=0x%s\n", value_bad ?
           "MISMATCH" : "FLAGS", f->name, OPN[op], MODES[mi].name,
           ha, hb, hc);
    printf("    lib=0x%s flags=0x%02x  mpfr=", hg, (unsigned)gf);
    mpfr_out_str(stdout, 16, 0, want, MPFR_RNDN);
    printf(" flags=0x%02x\n", (unsigned)wf);
}

int main(int argc, char **argv)
{
    int randoms = argc > 1 ? atoi(argv[1]) : 24;
    rs = argc > 2 ? strtoull(argv[2], NULL, 0) | 1 : 0x5EEDF00Dull;
    static uint8_t pool[MAXPOOL][32];
    int fi, oi, mi, i, j;

    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "cft_open failed\n");
        return 2;
    }
    printf("MPFR %s as oracle\n", mpfr_get_version());

    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn = build_pool(f, pool, randoms);
        uint64_t fmt_cases = 0;

        for (oi = 0; oi < NOPS; oi++) {
            int nargs = OP_NARGS[oi];
            for (mi = 0; mi < 5; mi++) {
                for (i = 0; i < pn; i++) {
                    int jmax = nargs >= 2 ? pn : 1;
                    for (j = 0; j < jmax; j++) {
                        const uint8_t *a = pool[i];
                        const uint8_t *b = pool[j];
                        const uint8_t *c = pool[(i + j) % pn];
                        uint8_t d[32];
                        uint32_t gf, wf;
                        mpfr_t want;
                        int vbad, fbad;

                        mpfr_init2(want, f->p);
                        oracle(f, (mop)oi, mi, a, b, c, want, &wf);
                        gf = lib_flags(f, (mop)oi, MODES[mi].cr,
                                       a, b, c, d);
                        vbad = !agree(f, d, want);
                        fbad = (gf != wf);
                        if (vbad) mismatches++;
                        if (fbad) flag_mismatches++;
                        if (vbad || fbad)
                            report(f, (mop)oi, mi, a, b, c, d, want,
                                   gf, wf, vbad);
                        mpfr_clear(want);
                        cases++; fmt_cases++;
                    }
                }
            }
        }
        printf("%s: %llu cases done (running mismatches: %llu value, "
               "%llu flag)\n", f->name,
               (unsigned long long)fmt_cases,
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    printf("TOTAL %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    mpfr_free_cache();
    return (mismatches || flag_mismatches) ? 1 : 0;
}
