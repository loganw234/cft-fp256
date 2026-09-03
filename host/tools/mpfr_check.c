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
 * The phase-1 transcendentals (ABI 0.3) are checked here too, and for
 * them this is not the third oracle but the ONLY one: libm is neither
 * correctly rounded nor reproducible, so unlike div and sqrt there is
 * no CPU campaign at fp32/fp64 to calibrate against. See the banner
 * above check_transcend for how MPFR's own exponent range is handled
 * (exp of the largest fp256 overflows MPFR too) and which expectations
 * are the contract's rather than MPFR's.
 *
 * The clause-5 completion set (ABI 0.2) is checked here too - rint,
 * scaleB, convertFormat, the eight integer conversions, logB,
 * nextUp/nextDown and remainder - by the same machinery: see the
 * banner comment above c5_round_into() for what maps onto what, which
 * expectations are MPFR-derived and which are the contract's own
 * (cvt_to's invalid-case delivery table), and why class, totalOrder
 * and the signaling comparisons are left to the other oracles.
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

/* Per-op, per-format case ledger, printed at the end - the campaign's
 * receipt. The first six rows are the arithmetic this file always
 * checked; the rest are the clause-5 completion set. convert is
 * tallied by SOURCE format; rint and rint_x are the named attributes
 * and the Exact variant respectively. */
enum {
    T_ADD, T_SUB, T_MUL, T_FMA, T_DIV, T_SQRT,
    T_RINT, T_RINTX, T_SCALEB, T_CONVERT,
    T_FROM_I32, T_FROM_U32, T_FROM_I64, T_FROM_U64,
    T_TO_I32, T_TO_U32, T_TO_I64, T_TO_U64,
    T_LOGB, T_NEXTUP, T_NEXTDOWN, T_REM,
    /* the phase-1 transcendentals, in the ABI's order - check_transcend
     * indexes this block as T_EXP + fn, so the two orders are one */
    T_EXP, T_EXPM1, T_EXP2, T_LOG, T_LOG1P, T_LOG2, T_LOG10, T_POW,
    T_HYPOT, NTALLY
};
static const char *const TALLY_NAME[NTALLY] = {
    "add", "sub", "mul", "fma", "div", "sqrt",
    "rint", "rint_x", "scaleb", "convert",
    "from_i32", "from_u32", "from_i64", "from_u64",
    "to_i32", "to_u32", "to_i64", "to_u64",
    "logb", "next_up", "next_down", "rem",
    "exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow",
    "hypot"
};
static uint64_t tally[NTALLY][4];

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

/* =================================================================
 * The clause-5 completion set (ABI 0.2), against the same oracle.
 *
 * Everything below reuses the machinery above rather than restating
 * it: enc_to_mpfr for exact operands, agree() for the verdict, and
 * c5_round_into() - the one new piece - which is oracle()'s delivery
 * logic (unbounded p-bit rounding as the over/underflow authority,
 * tininess after rounding by construction, fixed-grid subnormal
 * landings, the p+1 RMM build) applied to a value that is already
 * EXACT in an mpfr variable. That is the shape of every rounding
 * clause-5 operation: convert, scaleB and the integer conversions
 * are each ONE rounding of an exactly-representable value, which is
 * why they share a router where add/mul/div needed a recompute.
 *
 * What maps onto what:
 *   rint      mpfr_rint under RNDN (ties-to-even) / trunc / floor /
 *             ceil / round (ties-to-away). The named variants signal
 *             nothing but sNaN invalid; the Exact variant adds
 *             inexact iff the value moved; a zero result's sign is
 *             the operand's - pinned by the contract and derived
 *             here rather than trusted to MPFR's rint family.
 *   scaleb    mpfr_mul_2si in unbounded range (exact), then
 *             c5_round_into. n is clamped in the ORACLE only, at
 *             +-(4*emax + 2p + 64): past that, every nonzero finite
 *             operand overflows (resp. lands below half a subnormal
 *             grid step) whatever its exponent, so delivery and
 *             flags are constant in n - the library is called with
 *             the raw n, INT64_MIN/MAX included.
 *   convert   c5_round_into at the destination grid; NaN as class.
 *   cvt_from  the integer exactly via mpz, then c5_round_into.
 *   cvt_to    mpfr_rint at p+2 bits (always exact: the integer part
 *             of a p-bit value carries at most p+1 bits), the range
 *             test in mpz. The DELIVERED value of the invalid cases
 *             is the contract's own RISC-V FCVT table - cft.h
 *             documents the choice, 754 leaves it open - so those
 *             expectations are hardcoded from the doc, not derived
 *             from MPFR. Invalid pre-empts inexact, and only the
 *             Exact variants report inexact at all.
 *   logb      mpfr_get_exp minus one (MPFR holds the mantissa in
 *             [1/2,1), IEEE's logB in [1,2)); value-based, so a
 *             subnormal reports its true exponent; delivery is
 *             asserted exact since |logB| <= emax + man_w fits every
 *             format's significand with room to spare.
 *   next_up   mpfr_nextabove at p bits in UNBOUNDED range, then
 *             c5_round_into toward +inf. On the format's grid the
 *             step is at most one p-bit ulp, so the directed
 *             re-round lands exactly one grid position up - and the
 *             standard's edges fall out instead of being restated:
 *             nextabove(-min_sub) is a sub-grid negative that RUP
 *             delivers as -0, nextabove(max_normal) trips the
 *             overflow branch whose RUP delivery is +inf, and
 *             nextabove(-inf) is a huge negative whose RUP overflow
 *             delivery is -max_normal. Quantisation flags are
 *             discarded - the contract signal is sNaN invalid and
 *             nothing else, asserted separately. next_down is the
 *             mirror through nextbelow/RDN.
 *   rem       mpfr_remainder, exact by the standard theorem (a
 *             nonzero ternary is surfaced as a mismatch, never
 *             absorbed). MPFR documents a zero result's sign as x's,
 *             which is also the contract's rule; the sign is still
 *             forced from the operand here so the expectation is the
 *             contract's own. The flag comparison doubles as the
 *             exactness assertion: the expected mask never contains
 *             inexact/overflow/underflow, so the library raising any
 *             of them fails the case.
 *
 * cft_class and cft_total_order* are not checked here: MPFR has no
 * independent notion of either (an oracle would just restate the
 * encoding walk), and cmp_sig's value is the quiet predicate the
 * golden model already pins while its flag rule is one classify()
 * away from the harness testing itself. next_up/next_down DID make
 * the cut because the construction above is honest MPFR arithmetic
 * end to end.
 * ================================================================= */

static uint64_t get_field(const uint8_t *b, int lo, int n)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < n; i++)
        v |= (uint64_t)bit_at(b, lo + i) << i;
    return v;
}

/* +-1 on the little-endian encoding: one grid step on a finite
 * magnitude, which is how the directed generators reach "the
 * neighbour of" a boundary value without restating nextUp. */
static void enc_step(const fdesc *f, uint8_t *b, int up)
{
    size_t i;
    for (i = 0; i < f->esz; i++) {
        if (up) { if (++b[i] != 0) break; }
        else    { if (b[i]-- != 0) break; }
    }
}

static void enc_neg(const fdesc *f, uint8_t *b)
{
    int w = 1 + f->exp_w + f->man_w;
    b[(w - 1) >> 3] ^= (uint8_t)(1u << ((w - 1) & 7));
}

/* Encode (-1)^sign * m * 2^e2 exactly, if the format can. Returns 1
 * and fills b on success, 0 when the value is not representable -
 * directed generators simply skip those. Every success is verified
 * against enc_to_mpfr before it is used, because a generator bug
 * here would silently test the wrong value. */
static int enc_from_val(const fdesc *f, int sign, uint64_t m, long e2,
                        uint8_t *b)
{
    int msb = 63, w = 1 + f->exp_w + f->man_w;
    long E;

    if (m == 0)
        return 0;
    while (!((m >> msb) & 1))
        msb--;
    E = e2 + msb;
    memset(b, 0, 32);
    if (E > f->emax)
        return 0;
    if (E >= f->emin) {
        int shift = f->man_w - msb;
        if (shift >= 0) {
            set_field(b, shift, msb + 1, m);
        } else {
            if (-shift > 63 || (m & ((1ull << -shift) - 1)))
                return 0;                    /* low bits would be lost */
            set_field(b, 0, msb + 1 + shift, m >> -shift);
        }
        set_field(b, f->man_w, f->exp_w, (uint64_t)(E + f->emax));
    } else {
        long pos = e2 - (f->emin - f->man_w);
        if (pos >= 0) {
            if (msb + pos >= f->man_w)
                return 0;                    /* cannot happen: E < emin */
            set_field(b, (int)pos, msb + 1, m);
        } else {
            if (-pos > 63 || (m & ((1ull << -pos) - 1)))
                return 0;                    /* below the subnormal grid */
            set_field(b, 0, msb + 1 + (int)pos, m >> -pos);
        }
    }
    if (sign)
        set_field(b, w - 1, 1, 1);
    {
        mpfr_t chk, ref;
        mpfr_init2(chk, f->p);
        mpfr_init2(ref, 70);
        enc_to_mpfr(f, b, chk);
        mpfr_set_ui(ref, (unsigned long)(m >> 32), MPFR_RNDN);
        mpfr_mul_2ui(ref, ref, 32, MPFR_RNDN);
        mpfr_add_ui(ref, ref, (unsigned long)(m & 0xffffffffu),
                    MPFR_RNDN);              /* both steps exact at 70b */
        mpfr_mul_2si(ref, ref, e2, MPFR_RNDN);
        if (sign)
            mpfr_neg(ref, ref, MPFR_RNDN);
        if (!mpfr_equal_p(chk, ref)) {
            fprintf(stderr,
                    "enc_from_val self-check failed: %s sign=%d "
                    "m=0x%llx e2=%ld\n", f->name, sign,
                    (unsigned long long)m, e2);
            exit(3);
        }
        mpfr_clear(chk);
        mpfr_clear(ref);
    }
    return 1;
}

/* Round the EXACT finite value x into format f under MODES[mi], with
 * oracle()'s own delivery derivation: the unbounded p-bit rounding is
 * the overflow/underflow authority (tininess after rounding by
 * construction), subnormal landings re-round the true value on the
 * fixed grid, RMM goes through the p+1 guard/sticky build. Where
 * oracle() recomputes the operation, this rounds a known value -
 * every clause-5 rounding is one rounding of an exactly-held value,
 * so mpfr_set IS the operation here. */
static void c5_round_into(const fdesc *f, const mpfr_t x, int mi,
                          mpfr_t out, uint32_t *flags)
{
    mpfr_t runb, y;
    int inexact, is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
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
             * block oracle() applies */
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
            /* RMM on the fixed subnormal grid - oracle()'s block, on
             * the p+1 truncation of the exact value. The granularity
             * of the truncated fraction in grid units is 2^(exp-emin-2)
             * <= 1/4 and the truncation error is below one granule, so
             * the >= 1/2 decision cannot be crossed by truncating. */
            int t1b, up, sgn;
            long grid = f->emin - f->man_w;
            mpz_t nn;
            mpfr_t scaled, frac, half;
            t1b = mpfr_set(y, x, MPFR_RNDZ);
            sgn = mpfr_sgn(y) < 0;
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

/* roundToIntegral by attribute. RNDN under mpfr_rint is ties-to-even;
 * mpfr_round is ties-to-away; the directed three are their names. The
 * target's p+2 bits always hold the integer exactly, so there is no
 * second rounding hiding in the call. */
static int rint_by_mode(mpfr_t r, const mpfr_t v, int mi)
{
    switch (MODES[mi].cr) {
    case CFT_RNE: return mpfr_rint(r, v, MPFR_RNDN);
    case CFT_RTZ: return mpfr_trunc(r, v);
    case CFT_RDN: return mpfr_floor(r, v);
    case CFT_RUP: return mpfr_ceil(r, v);
    default:      return mpfr_round(r, v);
    }
}

static void report_c5(const char *opn, const char *mode, const fdesc *fa,
                      const uint8_t *a, const uint8_t *b, const fdesc *fg,
                      const uint8_t *got, mpfr_srcptr want, uint32_t gf,
                      uint32_t wf, int value_bad, const char *extra)
{
    char ha[65], hb[65], hg[65];
    if (shown >= 16)
        return;
    shown++;
    if (a) hexdump(a, fa->esz, ha); else strcpy(ha, "-");
    if (b) hexdump(b, fa->esz, hb); else strcpy(hb, "-");
    hexdump(got, fg->esz, hg);
    printf("  %s %s %s %s a=0x%s b=0x%s %s\n",
           value_bad ? "MISMATCH" : "FLAGS", fa->name, opn, mode, ha, hb,
           extra ? extra : "");
    printf("    lib=0x%s flags=0x%02x  mpfr=", hg, (unsigned)gf);
    /* Not mpfr_out_str unconditionally: with n = 0 it segfaults on a
     * ZERO in MPFR 4.2.1 as built here, which would turn the first
     * reported mismatch into a dead process and lose the report that
     * was the point. Measured 2026-09-02, on the underflowed pow that
     * found the sign bug above. */
    if (mpfr_nan_p(want))
        printf("nan");
    else if (mpfr_inf_p(want))
        printf("%sinf", mpfr_signbit(want) ? "-" : "");
    else if (mpfr_zero_p(want))
        printf("%s0", mpfr_signbit(want) ? "-" : "");
    else
        mpfr_out_str(stdout, 16, 0, want, MPFR_RNDN);
    printf(" flags=0x%02x\n", (unsigned)wf);
}

/* One case's verdict: value plus flags, ledger, first-16 reporting. */
static void c5_judge(int ti, int fj, const char *opn, const char *mode,
                     const fdesc *fa, const uint8_t *a, const uint8_t *b,
                     const fdesc *fg, const uint8_t *got, mpfr_srcptr want,
                     uint32_t gf, uint32_t wf, cft_status st,
                     const char *extra)
{
    int vbad = (st != CFT_OK) || !agree(fg, got, want);
    int fbad = (gf != wf);
    if (vbad)
        mismatches++;
    if (fbad)
        flag_mismatches++;
    if (vbad || fbad)
        report_c5(opn, mode, fa, a, b, fg, got, want, gf, wf, vbad,
                  st != CFT_OK ? "(status!=OK)" : extra);
    cases++;
    tally[ti][fj]++;
}

/* ---- roundToIntegral ---------------------------------------------- */

static void check_rint(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t extra[64][32];
    uint8_t d[32];
    int ne = 0, i, mi, exact, s;

    /* the tie families: n + 1/2 both signs, quarters, and the
     * integral threshold 2^(p-1) with its neighbours - enc-1 of the
     * threshold is 2^(p-1) - 1/2, the last value with a fraction */
    for (s = 0; s <= 1; s++) {
        uint64_t k;
        for (k = 0; k <= 7; k++)
            if (enc_from_val(f, s, 2 * k + 1, -1, extra[ne]))
                ne++;
        if (enc_from_val(f, s, 45, -1, extra[ne])) ne++;      /* 22.5 */
        if (enc_from_val(f, s, 1, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 5, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 7, -2, extra[ne])) ne++;
        if (enc_from_val(f, 0, 1, f->p - 1, extra[ne])) {
            if (s)
                enc_neg(f, extra[ne]);
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_step(f, extra[ne + 1], 0);
            memcpy(extra[ne + 2], extra[ne], 32);
            enc_step(f, extra[ne + 2], 1);
            ne += 3;
        }
    }

    for (mi = 0; mi < 5; mi++)
        for (exact = 0; exact <= 1; exact++)
            for (i = 0; i < pn + ne; i++) {
                const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t av, want;
                cls ca;
                cft_status st;
                char note[24];

                classify(f, a, &ca);
                mpfr_init2(av, f->p);
                mpfr_init2(want, f->p);
                enc_to_mpfr(f, a, av);
                if (ca.is_nan) {
                    mpfr_set_nan(want);
                    if (ca.is_snan)
                        wf |= CFT_FLAG_INVALID;
                } else {
                    int tern = rint_by_mode(want, av, mi);
                    if (mpfr_zero_p(want))
                        mpfr_setsign(want, want, ca.sign, MPFR_RNDN);
                    if (exact && tern != 0)
                        wf |= CFT_FLAG_INEXACT;
                }
                memset(d, 0, sizeof d);
                st = cft_rint(dev, f->fmt, MODES[mi].cr, exact, a, d, 1,
                              &gf, NULL);
                snprintf(note, sizeof note, "exact=%d", exact);
                c5_judge(exact ? T_RINTX : T_RINT, fj, "rint",
                         MODES[mi].name, f, a, NULL, f, d, want, gf, wf,
                         st, note);
                mpfr_clear(av);
                mpfr_clear(want);
            }
}

/* ---- scaleB ------------------------------------------------------- */

static void check_scaleb(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    int64_t ns[24];
    uint8_t d[32];
    int nn = 0, i, mi, k;
    int64_t emax = f->emax, p = f->p;

    /* every n regime: zero, small, the precision, the range edges,
     * the staging chunks above emax, past every saturation clamp,
     * the composed/host boundary at emin - p + 1, and the raw int64
     * extremes */
    ns[nn++] = 0;  ns[nn++] = 1;  ns[nn++] = -1;
    ns[nn++] = 2;  ns[nn++] = -2;
    ns[nn++] = p;  ns[nn++] = -p; ns[nn++] = f->man_w;
    ns[nn++] = emax;      ns[nn++] = emax + 1;
    ns[nn++] = -emax;     ns[nn++] = 2 * emax + p;
    ns[nn++] = 3 * emax;  ns[nn++] = 3 * emax + 1;
    ns[nn++] = 3 * emax + 1234567;
    ns[nn++] = f->emin - f->man_w;          /* deepest composed n */
    ns[nn++] = f->emin - p;                 /* first host-path n */
    ns[nn++] = -2 * emax;
    ns[nn++] = -(4 * emax + 2 * p) + 1;     /* the host clamp, straddled */
    ns[nn++] = -(4 * emax + 2 * p);
    ns[nn++] = -(4 * emax + 2 * p) - 1;
    ns[nn++] = INT64_MAX;
    ns[nn++] = INT64_MIN;

    for (k = 0; k < nn; k++)
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < pn; i++) {
                const uint8_t *a = pool[i];
                uint32_t gf = 0, wf = 0;
                mpfr_t av, want;
                cls ca;
                cft_status st;
                char note[40];

                classify(f, a, &ca);
                mpfr_init2(av, f->p);
                mpfr_init2(want, f->p);
                enc_to_mpfr(f, a, av);
                if (ca.is_nan) {
                    mpfr_set_nan(want);
                    if (ca.is_snan)
                        wf |= CFT_FLAG_INVALID;
                } else if (ca.is_inf || ca.is_zero) {
                    mpfr_set(want, av, MPFR_RNDN);
                } else {
                    int64_t nc = ns[k];
                    int64_t lim = 4 * emax + 2 * p + 64;
                    if (nc > lim) nc = lim;
                    if (nc < -lim) nc = -lim;
                    mpfr_mul_2si(av, av, (long)nc, MPFR_RNDN); /* exact */
                    c5_round_into(f, av, mi, want, &wf);
                }
                memset(d, 0, sizeof d);
                st = cft_scaleb(dev, f->fmt, MODES[mi].cr, a, ns[k], d, 1,
                                &gf, NULL);
                snprintf(note, sizeof note, "n=%lld", (long long)ns[k]);
                c5_judge(T_SCALEB, fj, "scaleb", MODES[mi].name, f, a,
                         NULL, f, d, want, gf, wf, st, note);
                mpfr_clear(av);
                mpfr_clear(want);
            }
}

/* ---- convertFormat ------------------------------------------------ */

static void check_convert(int sfi, int dfi, uint8_t pool[][32], int pn)
{
    const fdesc *fs = &FMTS[sfi], *fd = &FMTS[dfi];
    uint8_t extra[24][32];
    uint8_t d[32];
    int ne = 0, i, mi;
    char note[16];

    if (fs->man_w > fd->man_w) {
        /* narrowing stress: destination-grid ties built in the wider
         * source - a one at the destination's rounding position
         * (exact tie), and the same with the sticky bit lit (just
         * above the tie) - at a plain exponent, at the destination's
         * emax, and down on its subnormal grid */
        long Es[5];
        int nE = 0, t, s, v;
        Es[nE++] = 0;
        Es[nE++] = fd->emax;
        Es[nE++] = fd->emin;
        Es[nE++] = fd->emin - 3;
        Es[nE++] = fd->emin - fd->man_w + 1;
        for (t = 0; t < nE; t++)
            for (s = 0; s <= 1; s++)
                for (v = 0; v <= 1; v++) {
                    uint8_t *b = extra[ne];
                    memset(b, 0, 32);
                    set_field(b, fs->man_w, fs->exp_w,
                              (uint64_t)(Es[t] + fs->emax));
                    set_field(b, fs->man_w - (fd->man_w + 1), 1, 1);
                    if (v)
                        set_field(b, 0, 1, 1);
                    if (s)
                        enc_neg(fs, b);
                    ne++;
                }
    }
    snprintf(note, sizeof note, "->%s", fd->name);

    for (mi = 0; mi < 5; mi++)
        for (i = 0; i < pn + ne; i++) {
            const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
            uint32_t gf = 0, wf = 0;
            mpfr_t av, want;
            cls ca;
            cft_status st;

            classify(fs, a, &ca);
            mpfr_init2(av, fs->p);
            mpfr_init2(want, fd->p);
            enc_to_mpfr(fs, a, av);
            if (ca.is_nan) {
                mpfr_set_nan(want);
                if (ca.is_snan)
                    wf |= CFT_FLAG_INVALID;
            } else if (ca.is_inf) {
                mpfr_set_inf(want, ca.sign ? -1 : 1);
            } else {
                c5_round_into(fd, av, mi, want, &wf);
            }
            memset(d, 0, sizeof d);
            st = cft_convert(dev, fs->fmt, fd->fmt, MODES[mi].cr, a, d, 1,
                             &gf);
            c5_judge(T_CONVERT, sfi, "convert", MODES[mi].name, fs, a,
                     NULL, fd, d, want, gf, wf, st, note);
            mpfr_clear(av);
            mpfr_clear(want);
        }
}

/* ---- convertFromInt ----------------------------------------------- */

static void check_cvt_from(int fj, int nrand)
{
    const fdesc *f = &FMTS[fj];
    static const uint64_t DI[] = {
        0, 1, 2, 3, 5, 7, 0xff,
        (1ull << 23) - 1, 1ull << 23, (1ull << 23) + 1,
        (1ull << 24) - 1, 1ull << 24, (1ull << 24) + 1,
        (1ull << 24) + 2, (1ull << 25) + 2,
        (1ull << 31) - 1, 1ull << 31, (1ull << 31) + 1,
        (1ull << 32) - 1, 1ull << 32, (1ull << 32) + 1,
        (1ull << 52) - 1, 1ull << 52, (1ull << 52) + 1,
        (1ull << 53) - 1, 1ull << 53, (1ull << 53) + 1, (1ull << 53) + 2,
        1ull << 62, (1ull << 63) - 1, 1ull << 63, (1ull << 63) + 1,
        ~0ull, ~0ull - 1,
        0xaaaaaaaaaaaaaaaaull, 0x5555555555555555ull,
        0x7fffffffull, 0x80000000ull, 0x80000001ull,
        0x7fffffffffffffffull,
    };
    enum { NDI = (int)(sizeof DI / sizeof DI[0]) };
    uint64_t vals[NDI + 96];
    uint8_t d[32];
    int nv = 0, ty, mi, i;

    for (i = 0; i < (int)NDI; i++)
        vals[nv++] = DI[i];
    for (i = 0; i < nrand && nv < (int)NDI + 96; i++)
        vals[nv++] = rng() >> (rng() & 63);

    for (ty = 0; ty < 4; ty++)
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < nv; i++) {
                uint64_t raw = vals[i], mag = 0;
                int neg = 0, ti = 0;
                const char *opn = "?";
                uint32_t gf = 0, wf = 0;
                mpfr_t ex, want;
                mpz_t z;
                cft_status st = CFT_ERR_INTERNAL;
                char note[32];

                switch (ty) {
                case 0: {
                    int32_t x = (int32_t)(uint32_t)raw;
                    neg = x < 0;
                    mag = neg ? ~(uint64_t)(uint32_t)x + 1 : (uint64_t)x;
                    mag &= 0xffffffffull;
                    ti = T_FROM_I32; opn = "from_i32";
                    break;
                }
                case 1:
                    mag = (uint32_t)raw;
                    ti = T_FROM_U32; opn = "from_u32";
                    break;
                case 2: {
                    int64_t x = (int64_t)raw;
                    neg = x < 0;
                    mag = neg ? ~(uint64_t)x + 1 : (uint64_t)x;
                    ti = T_FROM_I64; opn = "from_i64";
                    break;
                }
                default:
                    mag = raw;
                    ti = T_FROM_U64; opn = "from_u64";
                    break;
                }

                mpz_init(z);
                mpz_import(z, 1, -1, 8, 0, 0, &mag);
                if (neg)
                    mpz_neg(z, z);
                mpfr_init2(ex, 70);
                mpfr_init2(want, f->p);
                mpfr_set_z(ex, z, MPFR_RNDN);      /* <= 64 bits: exact */
                c5_round_into(f, ex, mi, want, &wf);

                memset(d, 0, sizeof d);
                switch (ty) {
                case 0: {
                    int32_t x = (int32_t)(uint32_t)raw;
                    st = cft_cvt_from_i32(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                case 1: {
                    uint32_t x = (uint32_t)raw;
                    st = cft_cvt_from_u32(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                case 2: {
                    int64_t x = (int64_t)raw;
                    st = cft_cvt_from_i64(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                default: {
                    uint64_t x = raw;
                    st = cft_cvt_from_u64(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                }
                snprintf(note, sizeof note, "v=0x%llx",
                         (unsigned long long)raw);
                c5_judge(ti, fj, opn, MODES[mi].name, f, NULL, NULL, f, d,
                         want, gf, wf, st, note);
                mpz_clear(z);
                mpfr_clear(ex);
                mpfr_clear(want);
            }
}

/* ---- convertToInteger --------------------------------------------- */

static void check_cvt_to(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    /* The delivered values of the invalid cases are the CONTRACT's
     * RISC-V FCVT table, hardcoded from cft.h's doc - NaN and +inf to
     * the type's maximum, -inf and negative overflow to its minimum,
     * a negative rounded below zero to unsigned 0. 754 leaves these
     * open; the contract does not, and MPFR cannot derive a choice. */
    static const struct {
        const char *name;
        int ti, width, is_signed;
        uint64_t maxv, minv;
    } TY[4] = {
        { "to_i32", T_TO_I32, 32, 1, 0x7fffffffull, 0x80000000ull },
        { "to_u32", T_TO_U32, 32, 0, 0xffffffffull, 0 },
        { "to_i64", T_TO_I64, 64, 1, 0x7fffffffffffffffull,
          0x8000000000000000ull },
        { "to_u64", T_TO_U64, 64, 0, 0xffffffffffffffffull, 0 },
    };
    uint8_t extra[112][32];
    int ne = 0, ty, mi, exact, i, s;

    /* halves and quarters both signs, plus the representable
     * boundary ties (2^31 +- 1/2, 2^32 + 1/2, 2^63 - 1/2, 2^63 + 1) */
    for (s = 0; s <= 1; s++) {
        static const struct { uint64_t m; long e; } HV[6] = {
            {1, -1}, {3, -1}, {5, -1}, {7, -1}, {1, -2}, {3, -2},
        };
        for (i = 0; i < 6; i++)
            if (enc_from_val(f, s, HV[i].m, HV[i].e, extra[ne]))
                ne++;
        if (enc_from_val(f, s, (1ull << 32) + 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 32) - 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 33) + 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, ~0ull, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 63) + 1, 0, extra[ne])) ne++;
    }
    /* the powers at the type edges with their nearest neighbours,
     * both signs - 66 is past the implementation's early-out and past
     * every 64-bit range whatever the rounding */
    {
        static const long BE[5] = { 31, 32, 63, 64, 66 };
        for (i = 0; i < 5; i++) {
            if (!enc_from_val(f, 0, 1, BE[i], extra[ne]))
                continue;
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_step(f, extra[ne + 1], 0);
            memcpy(extra[ne + 2], extra[ne], 32);
            enc_step(f, extra[ne + 2], 1);
            memcpy(extra[ne + 3], extra[ne], 32);
            enc_neg(f, extra[ne + 3]);
            memcpy(extra[ne + 4], extra[ne + 1], 32);
            enc_neg(f, extra[ne + 4]);
            memcpy(extra[ne + 5], extra[ne + 2], 32);
            enc_neg(f, extra[ne + 5]);
            ne += 6;
        }
    }
    /* integer-range randoms: exponents banded into [-6, 71], where
     * the rounding is interesting - the shared pool's own randoms
     * already cover the far-out-of-range mass */
    for (i = 0; i < nrand && ne < 112; i++) {
        long E = (long)(rng() % 78) - 6;
        rand_enc(f, extra[ne]);
        set_field(extra[ne], f->man_w, f->exp_w, (uint64_t)(E + f->emax));
        ne++;
    }

    for (ty = 0; ty < 4; ty++) {
        mpz_t zmax, zmin, zr, zt;
        mpz_init(zmax); mpz_init(zmin); mpz_init(zr); mpz_init(zt);
        mpz_import(zmax, 1, -1, 8, 0, 0, &TY[ty].maxv);
        if (TY[ty].is_signed) {
            mpz_import(zmin, 1, -1, 8, 0, 0, &TY[ty].minv);
            mpz_neg(zmin, zmin);
        }

        for (mi = 0; mi < 5; mi++)
            for (exact = 0; exact <= 1; exact++)
                for (i = 0; i < pn + ne; i++) {
                    const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                    uint32_t gf = 0, wf = 0;
                    uint64_t want64 = 0, got64 = 0, mask;
                    mpfr_t av, R;
                    cls ca;
                    cft_status st = CFT_ERR_INTERNAL;

                    mask = TY[ty].width == 32 ? 0xffffffffull : ~0ull;
                    classify(f, a, &ca);
                    mpfr_init2(av, f->p);
                    mpfr_init2(R, f->p + 2);
                    enc_to_mpfr(f, a, av);

                    if (ca.is_nan) {
                        want64 = TY[ty].maxv;
                        wf = CFT_FLAG_INVALID;
                    } else if (ca.is_inf) {
                        want64 = ca.sign ? TY[ty].minv : TY[ty].maxv;
                        wf = CFT_FLAG_INVALID;
                    } else {
                        int tern = rint_by_mode(R, av, mi);
                        int oor = 0;
                        if (mpfr_zero_p(R)) {
                            mpz_set_ui(zr, 0);
                        } else if (mpfr_get_exp(R) > 70) {
                            oor = mpfr_sgn(R) < 0 ? -1 : 1;
                        } else {
                            mpfr_get_z(zr, R, MPFR_RNDZ); /* R integral */
                            if (mpz_cmp(zr, zmin) < 0)
                                oor = -1;
                            else if (mpz_cmp(zr, zmax) > 0)
                                oor = 1;
                        }
                        if (oor) {
                            want64 = oor < 0 ? TY[ty].minv : TY[ty].maxv;
                            wf = CFT_FLAG_INVALID;  /* pre-empts inexact */
                        } else {
                            if (mpz_sgn(zr) >= 0) {
                                uint64_t wv = 0;
                                mpz_export(&wv, NULL, -1, 8, 0, 0, zr);
                                want64 = wv;
                            } else {
                                uint64_t wv = 0;
                                mpz_neg(zt, zr);
                                mpz_export(&wv, NULL, -1, 8, 0, 0, zt);
                                want64 = ~wv + 1;
                            }
                            if (exact && tern != 0)
                                wf = CFT_FLAG_INEXACT;
                        }
                    }

                    switch (ty) {
                    case 0: {
                        int32_t o = 0;
                        st = cft_cvt_to_i32(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = (uint64_t)(uint32_t)o;
                        break;
                    }
                    case 1: {
                        uint32_t o = 0;
                        st = cft_cvt_to_u32(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = o;
                        break;
                    }
                    case 2: {
                        int64_t o = 0;
                        st = cft_cvt_to_i64(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = (uint64_t)o;
                        break;
                    }
                    default: {
                        uint64_t o = 0;
                        st = cft_cvt_to_u64(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = o;
                        break;
                    }
                    }

                    {
                        int vbad = (st != CFT_OK) ||
                                   (got64 & mask) != (want64 & mask);
                        int fbad = (gf != wf);
                        if (vbad)
                            mismatches++;
                        if (fbad)
                            flag_mismatches++;
                        if ((vbad || fbad) && shown < 16) {
                            char ha[65];
                            shown++;
                            hexdump(a, f->esz, ha);
                            printf("  %s %s %s %s exact=%d a=0x%s\n",
                                   vbad ? "MISMATCH" : "FLAGS", f->name,
                                   TY[ty].name, MODES[mi].name, exact,
                                   ha);
                            printf("    lib=0x%llx flags=0x%02x  "
                                   "want=0x%llx flags=0x%02x\n",
                                   (unsigned long long)(got64 & mask),
                                   (unsigned)gf,
                                   (unsigned long long)(want64 & mask),
                                   (unsigned)wf);
                        }
                        cases++;
                        tally[TY[ty].ti][fj]++;
                    }
                    mpfr_clear(av);
                    mpfr_clear(R);
                }
        mpz_clear(zmax); mpz_clear(zmin); mpz_clear(zr); mpz_clear(zt);
    }
}

/* ---- logB --------------------------------------------------------- */

static void check_logb(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    uint8_t extra[80][32];
    uint8_t d[32];
    int ne = 0, i, s;

    for (s = 0; s <= 1; s++) {
        if (enc_from_val(f, s, 1, f->emin - f->man_w, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, f->emin - f->man_w, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emin - 1, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emin, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emax, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, -1, extra[ne])) ne++;       /* 1.5 */
    }
    for (i = 0; i < nrand && ne < 80; i++) {
        rand_enc(f, extra[ne]);
        set_field(extra[ne], f->man_w, f->exp_w, 0);  /* subnormal band */
        ne++;
    }

    for (i = 0; i < pn + ne; i++) {
        const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
        uint32_t gf = 0, wf = 0;
        mpfr_t av, want;
        cls ca;
        cft_status st;

        classify(f, a, &ca);
        mpfr_init2(av, f->p);
        mpfr_init2(want, f->p);
        enc_to_mpfr(f, a, av);
        if (ca.is_nan) {
            mpfr_set_nan(want);
            if (ca.is_snan)
                wf |= CFT_FLAG_INVALID;
        } else if (ca.is_zero) {
            mpfr_set_inf(want, -1);
            wf |= CFT_FLAG_DIVBYZERO;
        } else if (ca.is_inf) {
            mpfr_set_inf(want, 1);            /* both signs, silently */
        } else {
            /* mpfr_get_exp sees the mantissa in [1/2, 1); IEEE's logB
             * sees [1, 2), one binade lower. Value-based, so
             * subnormals report their true exponent. |logB| <= emax +
             * man_w < 2^19 even at fp256, so the delivery is exact in
             * every format - asserted, not hoped. */
            long E = (long)mpfr_get_exp(av) - 1;
            if (mpfr_set_si(want, E, MPFR_RNDN) != 0) {
                fprintf(stderr, "logb oracle: E=%ld inexact in %s?!\n",
                        E, f->name);
                exit(3);
            }
        }
        memset(d, 0, sizeof d);
        st = cft_logb(dev, f->fmt, a, d, 1, &gf);
        c5_judge(T_LOGB, fj, "logb", "-", f, a, NULL, f, d, want, gf, wf,
                 st, NULL);
        mpfr_clear(av);
        mpfr_clear(want);
    }
}

/* ---- nextUp / nextDown -------------------------------------------- */

static void check_next(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t d[32], aflip[32];
    int i, dirn, s;

    for (dirn = 0; dirn < 2; dirn++)          /* 0 up, 1 down */
        for (s = 0; s <= 1; s++)
            for (i = 0; i < pn; i++) {
                const uint8_t *a;
                uint32_t gf = 0, wf = 0, discard = 0;
                mpfr_t av, want;
                cls ca;
                cft_status st;

                if (s) {
                    memcpy(aflip, pool[i], 32);
                    enc_neg(f, aflip);
                    a = aflip;
                } else {
                    a = pool[i];
                }
                classify(f, a, &ca);
                mpfr_init2(av, f->p);
                mpfr_init2(want, f->p);
                enc_to_mpfr(f, a, av);
                if (ca.is_nan) {
                    mpfr_set_nan(want);
                    if (ca.is_snan)
                        wf |= CFT_FLAG_INVALID;
                } else {
                    /* one representable step in unbounded range, then
                     * a directed re-round onto the format's grid;
                     * MODES[3] is rup, MODES[2] is rdn. The
                     * quantisation's flags are discarded: nextUp's
                     * only signal is the sNaN invalid above. */
                    if (dirn == 0)
                        mpfr_nextabove(av);
                    else
                        mpfr_nextbelow(av);
                    if (mpfr_inf_p(av))
                        mpfr_set(want, av, MPFR_RNDN); /* the fixed point */
                    else
                        c5_round_into(f, av, dirn == 0 ? 3 : 2, want,
                                      &discard);
                }
                memset(d, 0, sizeof d);
                st = dirn == 0
                    ? cft_next_up(dev, f->fmt, a, d, 1, &gf)
                    : cft_next_down(dev, f->fmt, a, d, 1, &gf);
                c5_judge(dirn == 0 ? T_NEXTUP : T_NEXTDOWN, fj,
                         dirn == 0 ? "next_up" : "next_down", "-", f, a,
                         NULL, f, d, want, gf, wf, st, NULL);
                mpfr_clear(av);
                mpfr_clear(want);
            }
}

/* ---- remainder ---------------------------------------------------- */

static void check_rem(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    static uint8_t xa[160][32], xb[160][32];
    uint8_t d[32];
    int np = 0, i, j, s;

    /* exact ties: (2k+1)/2 rem 1 - the quotient sits exactly on a
     * half and ties-to-even decides; both signs of x */
    for (s = 0; s <= 1; s++)
        for (i = 0; i <= 7 && np < 160; i++)
            if (enc_from_val(f, s, 2 * (uint64_t)i + 1, -1, xa[np]) &&
                enc_from_val(f, 0, 1, 0, xb[np]))
                np++;
    /* the same against an odd divisor: 3(2m+1)/2 rem 3 */
    for (s = 0; s <= 1; s++)
        for (i = 0; i <= 3 && np < 160; i++)
            if (enc_from_val(f, s, 6 * (uint64_t)i + 3, -1, xa[np]) &&
                enc_from_val(f, 0, 3, 0, xb[np]))
                np++;
    /* one encoding step either side of a tie: near-half quotients */
    for (s = 0; s <= 1; s++)
        for (i = 0; i < 2 && np < 157; i++) {
            uint64_t m = i ? 33 : 9;
            if (!enc_from_val(f, s, m, -1, xa[np]))
                continue;
            (void)enc_from_val(f, 0, 3, 0, xb[np]);
            memcpy(xa[np + 1], xa[np], 32);
            enc_step(f, xa[np + 1], 0);
            memcpy(xb[np + 1], xb[np], 32);
            memcpy(xa[np + 2], xa[np], 32);
            enc_step(f, xa[np + 2], 1);
            memcpy(xb[np + 2], xb[np], 32);
            np += 3;
        }
    /* the adversarial exponent gap, once per divisor: max_normal
     * against the smallest subnormals - at fp256 this is the
     * documented ~786k-step quotient-bit walk */
    if (np < 159) {
        memset(xa[np], 0, 32);
        set_field(xa[np], f->man_w, f->exp_w, (1ull << f->exp_w) - 2);
        for (i = 0; i < f->man_w; i++)
            set_field(xa[np], i, 1, 1);
        memset(xb[np], 0, 32);
        set_field(xb[np], 0, 1, 1);
        memcpy(xa[np + 1], xa[np], 32);
        memset(xb[np + 1], 0, 32);
        set_field(xb[np + 1], 0, 2, 3);
        np += 2;
    }
    /* gap-banded random pairs: y's exponent pulled within +-600 of
     * x's, so the walk is exercised without owning the clock */
    for (i = 0; i < nrand && np < 160; i++) {
        long ea, eb;
        long delta = (long)(rng() % 1201) - 600;
        rand_enc(f, xa[np]);
        rand_enc(f, xb[np]);
        ea = (long)get_field(xa[np], f->man_w, f->exp_w);
        eb = ea + delta;
        if (eb < 0)
            eb = 0;
        if (eb > (long)((1ull << f->exp_w) - 2))
            eb = (long)((1ull << f->exp_w) - 2);
        set_field(xb[np], f->man_w, f->exp_w, (uint64_t)eb);
        np++;
    }

    for (i = 0; i < pn + np; i++) {
        int jmax = i < pn ? pn : 1;
        for (j = 0; j < jmax; j++) {
            const uint8_t *pa = i < pn ? pool[i] : xa[i - pn];
            const uint8_t *pb = i < pn ? pool[j] : xb[i - pn];
            uint32_t gf = 0, wf = 0;
            mpfr_t av, bv, want;
            cls ca, cb;
            cft_status st;
            int tern = 0;

            classify(f, pa, &ca);
            classify(f, pb, &cb);
            mpfr_init2(av, f->p);
            mpfr_init2(bv, f->p);
            mpfr_init2(want, f->p);
            enc_to_mpfr(f, pa, av);
            enc_to_mpfr(f, pb, bv);
            if (ca.is_nan || cb.is_nan) {
                mpfr_set_nan(want);
                if (ca.is_snan || cb.is_snan)
                    wf |= CFT_FLAG_INVALID;
            } else if (ca.is_inf || cb.is_zero) {
                mpfr_set_nan(want);
                wf |= CFT_FLAG_INVALID;
            } else if (cb.is_inf || ca.is_zero) {
                mpfr_set(want, av, MPFR_RNDN);   /* x, sign included */
            } else {
                tern = mpfr_remainder(want, av, bv, MPFR_RNDN);
                if (mpfr_zero_p(want))
                    mpfr_setsign(want, want, ca.sign, MPFR_RNDN);
            }
            if (tern != 0) {
                /* the remainder of two p-bit values is representable
                 * in p bits (the standard theorem); a nonzero ternary
                 * is a harness-assumption failure, surfaced rather
                 * than absorbed */
                mismatches++;
                if (shown < 16) {
                    shown++;
                    printf("  REM-TERNARY %s: mpfr_remainder claims "
                           "inexact\n", f->name);
                }
            }
            memset(d, 0, sizeof d);
            st = cft_rem(dev, f->fmt, pa, pb, d, 1, &gf);
            /* the flag equality below IS the exactness assertion: wf
             * never contains inexact/overflow/underflow, so the
             * library raising any of them fails the case */
            c5_judge(T_REM, fj, "rem", "-", f, pa, pb, f, d, want, gf,
                     wf, st, NULL);
            mpfr_clear(av);
            mpfr_clear(bv);
            mpfr_clear(want);
        }
    }
}

/* ---- the phase-1 transcendentals ----------------------------------- *
 *
 * The nine functions of ABI 0.3 against MPFR's own, which is the only
 * external oracle that reaches fp128 and fp256 - and, for these
 * operations, the only external oracle at all: the CPU's libm is
 * neither correctly rounded nor reproducible, so there is nothing at
 * fp32/fp64 to calibrate against either. Agreement here is therefore
 * the whole external case for the transcendental set.
 *
 * The machinery is oracle()'s, with three differences worth stating:
 *
 *   * MPFR's OWN exponent range can overflow where the format's would
 *     too. exp of the largest fp256 is e^(1.6e78913), which no
 *     exponent field holds. So the unbounded evaluation runs with
 *     MPFR's widest range and its overflow/underflow flags are read:
 *     either one means the true value is past anything this format can
 *     express, and the delivery is the attribute's overflow or
 *     underflow response.
 *
 *   * Signaling NaNs are the documented one-sided help this harness
 *     already gives MPFR elsewhere - MPFR has none - so an sNaN
 *     operand's expectation is the contract's (invalid, canonical
 *     quiet NaN) rather than MPFR's.
 *
 *   * divideByZero is derived from operand classes, as everywhere else
 *     here: log and its friends at zero, log1p at -1, pow of a zero
 *     base to a FINITE negative exponent. pow(+-0, -inf) is the
 *     |x| < 1 row and signals nothing, which is the one row of that
 *     table implementations most often get wrong.
 */

typedef enum {
    TF_EXP = 0, TF_EXPM1, TF_EXP2, TF_LOG, TF_LOG1P, TF_LOG2, TF_LOG10,
    TF_POW, TF_HYPOT, TF_COUNT
} tfn;

static const char *const TFN_NAME[TF_COUNT] = {
    "exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow", "hypot"
};
static const int TFN_NARGS[TF_COUNT] = { 1, 1, 1, 1, 1, 1, 1, 2, 2 };

static int raw_tfn(mpfr_t r, int fn, const mpfr_t a, const mpfr_t b,
                   mpfr_rnd_t rnd)
{
    switch (fn) {
    case TF_EXP:   return mpfr_exp(r, a, rnd);
    case TF_EXPM1: return mpfr_expm1(r, a, rnd);
    case TF_EXP2:  return mpfr_exp2(r, a, rnd);
    case TF_LOG:   return mpfr_log(r, a, rnd);
    case TF_LOG1P: return mpfr_log1p(r, a, rnd);
    case TF_LOG2:  return mpfr_log2(r, a, rnd);
    case TF_LOG10: return mpfr_log10(r, a, rnd);
    case TF_POW:   return mpfr_pow(r, a, b, rnd);
    default:       return mpfr_hypot(r, a, b, rnd);
    }
}

/* Is v an integer, and is it an odd one? Decided on the encoding, so
 * an infinity is neither. */
static void enc_integrality(const fdesc *f, const uint8_t *b, int *is_int,
                            int *is_odd)
{
    cls c;
    long ef;
    int i, lowest = -1, man_lsb_exp;
    classify(f, b, &c);
    *is_int = 0;
    *is_odd = 0;
    if (c.is_nan || c.is_inf)
        return;
    if (c.is_zero) {
        *is_int = 1;
        return;
    }
    ef = (long)get_field(b, f->man_w, f->exp_w);
    for (i = 0; i < f->man_w; i++)
        if (bit_at(b, i)) { lowest = i; break; }
    if (ef == 0) {                       /* subnormal */
        man_lsb_exp = (int)(f->emin - f->man_w) + (lowest < 0 ? 0 : lowest);
    } else {
        if (lowest < 0)
            lowest = f->man_w;           /* the hidden bit is the lowest */
        man_lsb_exp = (int)(ef - (f->emax) - f->man_w) + lowest;
    }
    *is_int = man_lsb_exp >= 0;
    *is_odd = man_lsb_exp == 0;
}

/* The contract's invalid/divideByZero for one case, from classes. */
static uint32_t tfn_class_flags(const fdesc *f, int fn, const uint8_t *ba,
                                const uint8_t *bb)
{
    cls ca, cb;
    uint32_t fl = 0;
    int y_int, y_odd;
    classify(f, ba, &ca);
    classify(f, bb, &cb);
    if (ca.is_snan || (TFN_NARGS[fn] == 2 && cb.is_snan))
        return CFT_FLAG_INVALID;
    switch (fn) {
    case TF_LOG: case TF_LOG2: case TF_LOG10:
        if (ca.is_zero)
            fl |= CFT_FLAG_DIVBYZERO;
        else if (!ca.is_nan && ca.sign)
            fl |= CFT_FLAG_INVALID;
        break;
    case TF_LOG1P:
        if (!ca.is_nan && ca.sign) {
            mpfr_t v;
            mpfr_init2(v, f->p);
            enc_to_mpfr(f, ba, v);
            if (mpfr_cmp_si(v, -1) == 0)
                fl |= CFT_FLAG_DIVBYZERO;
            else if (mpfr_cmp_si(v, -1) < 0)
                fl |= CFT_FLAG_INVALID;
            mpfr_clear(v);
        }
        break;
    case TF_POW:
        if (cb.is_zero || ca.is_nan || cb.is_nan)
            break;                       /* pow(x,+-0) is 1; NaNs pass */
        enc_integrality(f, bb, &y_int, &y_odd);
        if (ca.is_zero && cb.sign && !cb.is_inf)
            fl |= CFT_FLAG_DIVBYZERO;
        else if (ca.sign && !ca.is_zero && !ca.is_inf && !cb.is_inf &&
                 !y_int)
            fl |= CFT_FLAG_INVALID;
        break;
    default:
        break;
    }
    return fl;
}

/* One transcendental case through MPFR, delivered into the format. */
static void t_oracle(const fdesc *f, int fn, int mi, const uint8_t *ba,
                     const uint8_t *bb, mpfr_t out, uint32_t *flags)
{
    mpfr_t a, b, runb, r, y;
    cls ca, cb;
    int tunb = 0, inexact, is_rmm = (MODES[mi].cr == CFT_RMM);
    int ovf = 0, unf = 0;
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = tfn_class_flags(f, fn, ba, bb);
    mpfr_exp_t save_emin = mpfr_get_emin(), save_emax = mpfr_get_emax();

    classify(f, ba, &ca);
    classify(f, bb, &cb);

    mpfr_init2(a, f->p);
    mpfr_init2(b, f->p);
    mpfr_init2(runb, f->p);
    mpfr_init2(r, f->p);
    mpfr_init2(y, f->p + 1);
    enc_to_mpfr(f, ba, a);
    enc_to_mpfr(f, bb, b);

    if (ca.is_snan || (TFN_NARGS[fn] == 2 && cb.is_snan)) {
        mpfr_set_prec(out, f->p);
        mpfr_set_nan(out);
        *flags = CFT_FLAG_INVALID;
        goto done;
    }

    /* The unbounded-range evaluation: MPFR's widest exponents, so that
     * an overflow HERE means the true value is past anything the
     * format could hold. */
    mpfr_set_emin(mpfr_get_emin_min());
    mpfr_set_emax(mpfr_get_emax_max());
    mpfr_clear_flags();
    if (is_rmm) {
        int t1 = raw_tfn(y, fn, a, b, MPFR_RNDZ);
        ovf = mpfr_overflow_p();
        unf = mpfr_underflow_p();
        if (!mpfr_number_p(y) || mpfr_zero_p(y)) {
            mpfr_set(runb, y, MPFR_RNDN);
            tunb = 0;
        } else {
            rmm_round(runb, y, t1 != 0, f->p);
            tunb = !mpfr_equal_p(runb, y) || t1;
        }
    } else {
        tunb = raw_tfn(runb, fn, a, b, rnd);
        ovf = mpfr_overflow_p();
        unf = mpfr_underflow_p();
    }
    mpfr_set_emin(save_emin);
    mpfr_set_emax(save_emax);
    inexact = (tunb != 0);

    if (ovf || unf) {
        /* mpfr_sgn of a signed zero is 0, and an underflow
         * delivers exactly that - so the sign comes from the sign
         * BIT. Getting this wrong turns pow of a negative base to
         * an odd negative power, which underflows to -0, into +0. */
        int sgn = mpfr_signbit(runb) ? -1 : 1;
        mpfr_set_prec(out, f->p);
        if (ovf) {
            int away = (rnd == MPFR_RNDU && sgn > 0) ||
                       (rnd == MPFR_RNDD && sgn < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ) away = 0;
            if (away)
                mpfr_set_inf(out, sgn);
            else {
                mpfr_set_ui_2exp(out, 1, f->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (sgn < 0) mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        } else {
            /* below half the smallest subnormal: zero, except where
             * the attribute points away from it */
            int up = (rnd == MPFR_RNDU && sgn > 0) ||
                     (rnd == MPFR_RNDD && sgn < 0);
            if (up) {
                mpfr_set_ui_2exp(out, 1, f->emin - f->man_w, MPFR_RNDN);
                if (sgn < 0) mpfr_neg(out, out, MPFR_RNDN);
            } else {
                mpfr_set_zero(out, sgn);
            }
            *flags = fl | CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
        }
        goto done;
    }

    if (mpfr_nan_p(runb) || mpfr_inf_p(runb) || mpfr_zero_p(runb)) {
        mpfr_set_prec(out, f->p);
        mpfr_set(out, runb, MPFR_RNDN);
        if (inexact) fl |= CFT_FLAG_INEXACT;
        *flags = fl;
        goto done;
    }

    {
        mpfr_exp_t e_unb = mpfr_get_exp(runb);
        long e_res = (long)e_unb - 1;

        if (e_res > f->emax) {
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ) away = 0;
            mpfr_set_prec(out, f->p);
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                mpfr_set_ui_2exp(out, 1, f->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0) mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
            goto done;
        }
        if (e_res >= f->emin) {
            mpfr_set_prec(out, f->p);
            mpfr_set(out, runb, MPFR_RNDN);
            if (inexact) fl |= CFT_FLAG_INEXACT;
            *flags = fl;
            goto done;
        }
        /* subnormal landing: re-round the TRUE value on the fixed grid */
        if (!is_rmm) {
            int t2;
            mpfr_set_emin(f->emin - f->p + 2);
            mpfr_set_emax(f->emax + 1);
            t2 = raw_tfn(r, fn, a, b, rnd);
            t2 = mpfr_check_range(r, t2, rnd);
            t2 = mpfr_subnormalize(r, t2, rnd);
            mpfr_set_emin(save_emin);
            mpfr_set_emax(save_emax);
            mpfr_set_prec(out, f->p);
            mpfr_set(out, r, MPFR_RNDN);
            if (t2 != 0 || inexact)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            *flags = fl;
        } else {
            int t1, up, sign;
            long grid = f->emin - f->man_w;
            mpz_t n;
            mpfr_t scaled, frac, half;
            t1 = raw_tfn(y, fn, a, b, MPFR_RNDZ);
            sign = mpfr_sgn(y) < 0;
            mpz_init(n);
            mpfr_init2(scaled, f->p + 4);
            mpfr_init2(frac, f->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);
            mpfr_get_z(n, scaled, MPFR_RNDZ);
            mpfr_sub_z(frac, scaled, n, MPFR_RNDN);
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(n, n, 1);
            mpfr_set_prec(out, f->p);
            mpfr_set_z_2exp(out, n, grid, MPFR_RNDN);
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
            if (!mpfr_zero_p(frac) || t1)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(n);
            mpfr_clear(scaled); mpfr_clear(frac); mpfr_clear(half);
            *flags = fl;
        }
    }

done:
    mpfr_set_emin(save_emin);
    mpfr_set_emax(save_emax);
    mpfr_clear(a); mpfr_clear(b);
    mpfr_clear(runb); mpfr_clear(r); mpfr_clear(y);
}

static uint32_t tfn_lib(const fdesc *f, int fn, cft_round rnd,
                        const uint8_t *a, const uint8_t *b, uint8_t *d,
                        cft_status *st)
{
    uint32_t fl = 0;
    switch (fn) {
    case TF_EXP:   *st = cft_exp(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXPM1: *st = cft_expm1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP2:  *st = cft_exp2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG:   *st = cft_log(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG1P: *st = cft_log1p(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG2:  *st = cft_log2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG10: *st = cft_log10(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_POW:   *st = cft_pow(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    default:       *st = cft_hypot(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    }
    return fl;
}


/* Operands aimed at the transcendentals specifically, in their own
 * larger pool: the families that matter here - the exact cases, the
 * overflow and underflow thresholds, a base one ulp from 1 - are not
 * the families that matter for an FMA, and the arithmetic phase's
 * 64-operand pool is sized for a cross product this phase does not
 * take. */
#define TPOOL_MAX 208

static int build_tpool(const fdesc *f, uint8_t pool[][32], int randoms)
{
    int n = build_pool(f, pool, randoms);
    long ks[12];
    int nk = 0, k;

    ks[nk++] = 1; ks[nk++] = 2; ks[nk++] = 3; ks[nk++] = 10;
    ks[nk++] = 17; ks[nk++] = f->p; ks[nk++] = f->emax;
    ks[nk++] = f->emax + 1; ks[nk++] = f->emin; ks[nk++] = -1;
    ks[nk++] = -3; ks[nk++] = f->emin - f->man_w;
    for (k = 0; k < nk && n < TPOOL_MAX - 8; k++) {
        uint64_t mag = (uint64_t)(ks[k] < 0 ? -ks[k] : ks[k]);
        /* the integer itself: an exp2 exact case, and a pow exponent */
        if (enc_from_val(f, 0, mag, 0, pool[n]) == 0) {
            if (ks[k] < 0)
                enc_neg(f, pool[n]);
            n++;
        }
        /* 2^k: log2's exact cases, with a neighbour above and below */
        if (enc_from_val(f, 0, 1, ks[k], pool[n]) == 0) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        }
    }
    /* powers of ten: log10's exact cases, until the odd part 5^k
     * outruns the significand */
    {
        uint64_t five = 1;
        long e = 0;
        while (n < TPOOL_MAX - 4 && five <= ((uint64_t)1 << 60)) {
            if (enc_from_val(f, 0, five, e, pool[n]) != 0)
                break;
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            five *= 5;
            e++;
        }
    }
    /* one ulp either side of 1 and of -1, and arguments below
     * 2^-(p+3), where the answer is decided by a SIDE and not by any
     * working precision */
    if (n < TPOOL_MAX - 10 && enc_from_val(f, 0, 1, 0, pool[n]) == 0) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
    }
    for (k = 2; k < 12 && n < TPOOL_MAX - 4; k++) {
        if (enc_from_val(f, 0, 1, -(long)f->p - k, pool[n]) == 0) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
        }
    }
    /* top up with randoms, which cost nothing and occasionally find
     * something the directed families did not think of */
    while (n < TPOOL_MAX) {
        rand_enc(f, pool[n]);
        n++;
    }
    return n;
}

static void check_transcend(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    int fn, mi, i, j;

    for (fn = 0; fn < TF_COUNT; fn++) {
        int nargs = TFN_NARGS[fn];
        /* Unary: every operand. Binary: every operand against a strided
         * eighth of the pool, so the pair count stays linear - the full
         * cross product of two hundred operands times five attributes
         * times two functions is not a sharper test, only a longer
         * one. */
        int jstep = nargs == 2 ? (pn / 8 > 0 ? pn / 8 : 1) : 1;
        for (mi = 0; mi < 5; mi++) {
            for (i = 0; i < pn; i++) {
                int jmax = nargs == 2 ? pn : 1;
                for (j = (nargs == 2 ? i % jstep : 0); j < jmax; j += jstep) {
                    const uint8_t *a = pool[i];
                    const uint8_t *b = pool[j];
                    uint8_t d[32];
                    uint32_t gf, wf = 0;
                    cft_status st = CFT_OK;
                    mpfr_t want;

                    mpfr_init2(want, f->p);
                    t_oracle(f, fn, mi, a, b, want, &wf);
                    memset(d, 0, sizeof d);
                    gf = tfn_lib(f, fn, MODES[mi].cr, a, b, d, &st);
                    c5_judge(T_EXP + fn, fj, TFN_NAME[fn], MODES[mi].name,
                             f, a, nargs == 2 ? b : NULL, f, d, want, gf, wf,
                             st, NULL);
                    mpfr_clear(want);
                }
            }
        }
    }
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
    static uint8_t tpool[TPOOL_MAX][32];
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
                        tally[oi][fi]++;
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

    /* The clause-5 completion set. Fresh pools (the rng has moved on,
     * so these randoms differ from the arithmetic phase's), and the
     * wide rungs get double the random weight: fp128/fp256 are the
     * formats only MPFR can arbitrate. */
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn = build_pool(f, pool, randoms);
        int mult = fi >= 2 ? 2 : 1;
        uint64_t before = cases;
        check_rint(fi, pool, pn);
        check_scaleb(fi, pool, pn);
        check_cvt_from(fi, 24 * mult);
        check_cvt_to(fi, pool, pn, 24 * mult);
        check_logb(fi, pool, pn, 24 * mult);
        check_next(fi, pool, pn);
        check_rem(fi, pool, pn, 48 * mult);
        printf("%s clause5: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }
    /* The phase-1 transcendentals. Their own pools, because the
     * families that matter here - exact cases, thresholds, a base one
     * ulp from 1 - are not the families that matter for an FMA. */
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn = build_tpool(f, tpool, randoms);
        uint64_t before = cases;
        check_transcend(fi, tpool, pn);
        printf("%s transcend: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    for (fi = 0; fi < 4; fi++) {
        int pn = build_pool(&FMTS[fi], pool, randoms);
        int dfi;
        uint64_t before = cases;
        for (dfi = 0; dfi < 4; dfi++)
            check_convert(fi, dfi, pool, pn);
        printf("%s convert: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", FMTS[fi].name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    {
        int t, k;
        printf("\nper-op case counts (convert by source format):\n");
        printf("  %-10s %12s %12s %12s %12s\n", "op", "fp32", "fp64",
               "fp128", "fp256");
        for (t = 0; t < NTALLY; t++) {
            printf("  %-10s", TALLY_NAME[t]);
            for (k = 0; k < 4; k++)
                printf(" %12llu", (unsigned long long)tally[t][k]);
            printf("\n");
        }
    }

    printf("TOTAL %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    mpfr_free_cache();
    return (mismatches || flag_mismatches) ? 1 : 0;
}
