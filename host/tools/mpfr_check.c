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
 * The augmented arithmetic operations of clause 9.5 are checked here
 * with one difference worth stating up front: MPFR has no
 * roundTiesTowardZero, so this harness cannot ask it for the answer.
 * It asks MPFR for the EXACT value at a precision that provably holds
 * it - and proves it by requiring a zero ternary - then applies 9.5's
 * tie rule itself and derives the error term by exact subtraction. See
 * the banner above check_augmented for why that is still an oracle and
 * exactly which part of it is not.
 *
 * The seven REDUCTIONS of clause 9.4 are checked here too, and what
 * this oracle can and cannot say about them is worth stating exactly,
 * because the honest answer is "half of it".
 *
 * MPFR CAN ARBITRATE EVERY NODE. Each node of a reduction is one add
 * or one multiply of two format values, correctly rounded in the
 * caller's attribute, and that is precisely what oracle() above
 * already decides - so the campaign REPLAYS the tree here with MPFR
 * doing every node's arithmetic and compares the root against the
 * library's, bits and flags. A node that rounded the wrong way, or
 * raised the wrong flag, or lost a subnormal, fails here.
 *
 * MPFR CANNOT ARBITRATE THE TREE. Which values are paired, and at
 * which level, is this CONTRACT's choice - 754-2019 9.4 explicitly
 * allows an implementation to "associate in any order or evaluate in
 * any wider format", so there is no external authority to appeal to
 * and MPFR has no opinion. The harness therefore reproduces the split
 * rather than judging it, and a reduction whose shape was wrong in
 * BOTH the library and this file would pass. What guards the shape is
 * a different thing entirely: two independent implementations of it
 * (python/cft_golden/reduce.py and libcft) compared against each other
 * by host/tests/reduce_check.py, the streaming accumulator's agreement
 * with the recursive definition, and the published vector sets.
 *
 * The same division applies to the three scaled products: MPFR decides
 * every node's multiply, and the binade extraction that follows it is
 * exact bit surgery on the encoding, with nothing to round and so
 * nothing to arbitrate. 9.4's special-value precedence is likewise the
 * contract's table, replayed rather than judged.
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

/* The Pi-variants - sinpi, cospi, tanpi, asinpi, acospi, atanpi and
 * atan2pi - arrived in MPFR 4.2.0. Composing them out of sin(pi*x)
 * would compare against a ROUNDED product and would decide nothing
 * about the last bit, so an older MPFR must fail HERE rather than
 * quietly check something weaker. */
#if MPFR_VERSION < MPFR_VERSION_NUM(4, 2, 0)
#  error "mpfr-check needs MPFR 4.2.0 or newer for sinpi/cospi/tanpi \
and the Pi-variants of the inverse trigonometrics (ABI 0.4), and for \
exp2m1/exp10m1/log2p1/log10p1/powr/compound_si/rootn_si (table 9.1's \
remainder). Every one of those is called DIRECTLY."
#endif

#include "../include/cft.h"
/* Not API: the transcendental instrumentation, which this tool
 * links statically and which is where docs/TRANSCENDENTALS.md's
 * escalation numbers are measured rather than asserted. */
#include "../src/transcend.h"

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
    /* the transcendentals, in the ABI's order - check_transcend
     * indexes this block as T_EXP + fn, so the two orders are one */
    T_EXP, T_EXPM1, T_EXP2, T_LOG, T_LOG1P, T_LOG2, T_LOG10, T_POW,
    T_HYPOT,
    T_SINPI, T_COSPI, T_TANPI, T_ASIN, T_ACOS, T_ATAN, T_ATAN2,
    T_ASINPI, T_ACOSPI, T_ATANPI, T_ATAN2PI,
    T_SIN, T_COS, T_TAN, T_SINH, T_COSH, T_TANH, T_ASINH, T_ACOSH,
    T_ATANH,
    T_EXP2M1, T_EXP10, T_EXP10M1, T_LOG2P1, T_LOG10P1, T_RSQRT,
    T_POWN, T_POWR, T_COMPOUND, T_ROOTN,
    /* clause 5.12, appended AFTER the transcendental block so
     * check_transcend's T_EXP + fn indexing is untouched */
    T_FROM_DEC, T_TO_DEC, T_FROM_HEX, T_TO_HEX,
    /* the augmented arithmetic operations of 754-2019 9.5 */
    T_AUG_ADD, T_AUG_SUB, T_AUG_MUL,
    /* the seven reductions of clause 9.4. A "case" here is a whole
     * VECTOR, not an element - the element count is reported
     * separately, because 400 cases over 20-element vectors is 8,000
     * arbitrated nodes and reporting only the smaller number would
     * undersell the campaign while reporting only the larger would
     * oversell its independence. */
    T_RSUM, T_RDOT, T_RSUMSQ, T_RSUMABS,
    T_SPROD, T_SPROD_SUM, T_SPROD_DIFF,
    /* the formatOf arithmetic of 5.4.1, tallied by SOURCE format like
     * convert - the destination is named in the run's per-pair line */
    T_FO_ADD, T_FO_SUB, T_FO_MUL, T_FO_DIV, T_FO_SQRT, T_FO_FMA,
    NTALLY
};
static const char *const TALLY_NAME[NTALLY] = {
    "add", "sub", "mul", "fma", "div", "sqrt",
    "rint", "rint_x", "scaleb", "convert",
    "from_i32", "from_u32", "from_i64", "from_u64",
    "to_i32", "to_u32", "to_i64", "to_u64",
    "logb", "next_up", "next_down", "rem",
    "exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow",
    "hypot",
    "sinpi", "cospi", "tanpi", "asin", "acos", "atan", "atan2",
    "asinpi", "acospi", "atanpi", "atan2pi",
    "sin", "cos", "tan", "sinh", "cosh", "tanh", "asinh", "acosh",
    "atanh",
    "exp2m1", "exp10", "exp10m1", "log2p1", "log10p1", "rsqrt",
    "pown", "powr", "compound", "rootn",
    "from_dec", "to_dec", "from_hex", "to_hex",
    "aug_add", "aug_sub", "aug_mul",
    "sum", "dot", "sumsq", "sumabs",
    "sprod", "sprod_sum", "sprod_diff",
    "fo_add", "fo_sub", "fo_mul", "fo_div", "fo_sqrt", "fo_fma"
};
static uint64_t tally[NTALLY][4];

/* Arbitrated NODES, separately from the vector count above. */
static uint64_t reduce_nodes;

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

/* An expected value, printed WITHOUT mpfr_out_str.
 *
 * mpfr_out_str with n = 0 segfaults on a zero in MPFR 4.2.1 as built
 * here, and dies on an extreme exponent as well - measured 2026-09-02,
 * both from this file. Either one turns the first reported mismatch
 * into a dead process and takes the report with it, which is the worst
 * possible failure mode for an oracle: it can only crash when it has
 * something to say. So the mantissa and the exponent are printed
 * directly, which is bounded work for any value MPFR can hold. */
static void print_mpfr(mpfr_srcptr v)
{
    mpz_t m;
    mpfr_exp_t e;
    /* A caller-supplied buffer, not mpz_get_str(NULL, ...): GMP
     * allocates with its own allocator and free() is not necessarily
     * its deallocator, which corrupts the heap on this toolchain. The
     * mantissa is at most p bits, so 128 bytes is generous. */
    char buf[128];
    if (mpfr_nan_p(v)) { printf("nan"); return; }
    if (mpfr_inf_p(v)) { printf("%sinf", mpfr_signbit(v) ? "-" : ""); return; }
    if (mpfr_zero_p(v)) { printf("%s0", mpfr_signbit(v) ? "-" : ""); return; }
    mpz_init(m);
    e = mpfr_get_z_2exp(m, v);
    if (mpz_sizeinbase(m, 16) + 3 <= sizeof buf) {
        mpz_get_str(buf, 16, m);
        printf("0x%s p2^%ld", buf, (long)e);
    } else {
        printf("<%lu hex digits> p2^%ld",
               (unsigned long)mpz_sizeinbase(m, 16), (long)e);
    }
    mpz_clear(m);
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
    print_mpfr(want);
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

/* ---- the augmented arithmetic operations (754-2019 9.5) ------------ *
 *
 * WHY THIS IS AN ORACLE, AND WHAT IT IS AN ORACLE FOR.
 *
 * MPFR has no roundTiesTowardZero. It has no mode that breaks a tie
 * toward the smaller magnitude, and MPFR_RNDZ is not it - RNDZ
 * truncates every inexact value, not only the ties. So this harness
 * cannot ask MPFR for the answer; it asks MPFR for the EXACT VALUE and
 * applies 9.5's rule itself:
 *
 *   1. compute x op y at a precision that holds the exact result with
 *      no rounding at all, and PROVE it did by requiring MPFR's ternary
 *      to be zero. That precision is not 2p: the exact sum of two
 *      p-bit values whose exponents span the whole format is
 *      emax - emin + p bits wide (524,522 at binary256), and the
 *      product's residual against a subnormal result is nearly as wide.
 *      AUG_PREC below covers both with margin, and the ternary check is
 *      what makes "exact" a measurement rather than an assumption.
 *   2. round that exact value to the format by 9.5's own definition -
 *      scale to the format's grid, split into an integer and a
 *      fraction with exact MPFR arithmetic, and compare the fraction
 *      with one half: strictly above rounds away, equal keeps the
 *      smaller magnitude ("the one with smaller magnitude shall be
 *      delivered"), below truncates. Overflow is the rounded value's
 *      exponent exceeding emax, and 9.5 sends it to an infinity.
 *   3. subtract exactly for the error term, and decide representability
 *      by rounding it the same way and asking whether the rounding
 *      changed it - which is 9.5's "can be represented exactly as a
 *      finite number in sourceFormat" tested rather than reasoned.
 *
 * Every arithmetic step above is MPFR's, every step is exact by
 * construction and checked to be, and the only thing this file
 * contributes is the tie rule and the flag policy - which are the two
 * things 9.5 states in words and the library must be scored against.
 * That makes this a genuine independent oracle for the VALUES and a
 * restatement for the FLAGS, and saying which is which is the point of
 * this paragraph.
 *
 * The flags are 9.5's, not clause 7's defaults: inexact "only when
 * roundTiesTowardZero(x + y) overflows", underflow when the error term
 * is "non-zero and lies strictly between +-b^emin" even though that
 * error term is exact, and both together for the one case 9.5 gives
 * augmentedMultiplication where the residual falls below the subnormal
 * grid.
 */

#define AUG_COUNT 3
static const char *const AUGN[AUG_COUNT] = { "aug_add", "aug_sub",
                                             "aug_mul" };

/* Wide enough to hold every exact intermediate: the widest is a SUM
 * spanning the whole exponent range, emax - emin + p bits. */
static long aug_prec(const fdesc *f)
{
    return (long)f->emax - f->emin + 2 * f->p + 16;
}

/* Round the exact non-zero finite value v into f's grid under 9.5's
 * roundTiesTowardZero, into `out`. Returns 1 if it overflowed. */
static int aug_rttz(const fdesc *f, mpfr_srcptr v, mpfr_ptr out)
{
    mpz_t n;
    mpfr_t scaled, frac, half;
    long E, q, er;
    int sign = mpfr_signbit(v) ? 1 : 0, cmp, ovf = 0;

    E = (long)mpfr_get_exp(v) - 1;               /* floor(log2 |v|) */
    q = (E > f->emin ? E : f->emin) - (f->p - 1);
    mpz_init(n);
    mpfr_init2(scaled, aug_prec(f));
    mpfr_init2(frac, aug_prec(f));
    mpfr_init2(half, 8);
    mpfr_abs(scaled, v, MPFR_RNDN);
    mpfr_mul_2si(scaled, scaled, -q, MPFR_RNDN); /* exact: an exponent */
    mpfr_get_z(n, scaled, MPFR_RNDZ);            /* floor */
    mpfr_sub_z(frac, scaled, n, MPFR_RNDN);      /* exact */
    mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
    cmp = mpfr_cmp(frac, half);
    if (cmp > 0)
        mpz_add_ui(n, n, 1);                     /* strictly above half */
    /* cmp == 0 is the TIE, and 9.5 keeps the smaller magnitude: nothing
     * happens here, and that one line is the whole difference from
     * roundTiesToEven. */
    if (mpz_sgn(n) == 0) {
        mpfr_set_zero(out, sign ? -1 : 1);       /* 6.3: the exact sign */
    } else {
        er = q + (long)mpz_sizeinbase(n, 2) - 1;
        if (er > f->emax) {
            ovf = 1;
            mpfr_set_inf(out, sign ? -1 : 1);
        } else {
            mpfr_set_z_2exp(out, n, q, MPFR_RNDN);       /* exact */
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
        }
    }
    mpz_clear(n);
    mpfr_clear(scaled);
    mpfr_clear(frac);
    mpfr_clear(half);
    return ovf;
}

/* The pair and the flags for one case. fn: 0 add, 1 sub, 2 mul. */
static void aug_oracle(const fdesc *f, int fn, const uint8_t *ba,
                       const uint8_t *bb, mpfr_ptr want_r, mpfr_ptr want_e,
                       uint32_t *flags)
{
    mpfr_t a, b, exact, rv, err, emin_mag;
    cls ca, cb;
    uint32_t fl = 0;
    int tern = 0, nan_in;
    long P = aug_prec(f);

    classify(f, ba, &ca);
    classify(f, bb, &cb);
    nan_in = ca.is_nan || cb.is_nan;
    if (ca.is_snan || cb.is_snan)
        fl |= CFT_FLAG_INVALID;

    mpfr_init2(a, f->p);
    mpfr_init2(b, f->p);
    mpfr_init2(exact, P);
    mpfr_init2(rv, P);
    mpfr_init2(err, P);
    mpfr_init2(emin_mag, 8);
    enc_to_mpfr(f, ba, a);
    enc_to_mpfr(f, bb, b);

    if (fn == 2)
        tern = mpfr_mul(exact, a, b, MPFR_RNDN);
    else if (fn == 1)
        tern = mpfr_sub(exact, a, b, MPFR_RNDN);
    else
        tern = mpfr_add(exact, a, b, MPFR_RNDN);
    if (tern != 0) {
        /* The working precision was supposed to make this impossible.
         * A non-zero ternary means the harness, not the library, is
         * wrong - surfaced rather than absorbed. */
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  AUG-TERNARY %s %s: the exact %s was rounded at %ld "
                   "bits\n", f->name, AUGN[fn],
                   fn == 2 ? "product" : "sum", P);
        }
    }

    if (mpfr_nan_p(exact)) {
        mpfr_set_nan(want_r);
        mpfr_set_nan(want_e);
        if (!nan_in)
            fl |= CFT_FLAG_INVALID;      /* inf + (-inf), inf * 0 */
        goto done;
    }
    if (!mpfr_number_p(exact) || mpfr_zero_p(exact)) {
        /* An infinity at unbounded range can only come from an infinite
         * OPERAND, so it signals nothing; a zero carries its own sign
         * (6.3), and 9.5 gives both outputs the same value either way. */
        mpfr_set(want_r, exact, MPFR_RNDN);
        mpfr_set(want_e, exact, MPFR_RNDN);
        goto done;
    }

    if (aug_rttz(f, exact, rv)) {
        mpfr_set(want_r, rv, MPFR_RNDN);
        mpfr_set(want_e, rv, MPFR_RNDN);
        fl |= CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        goto done;
    }
    mpfr_set(want_r, rv, MPFR_RNDN);

    tern = mpfr_sub(err, exact, rv, MPFR_RNDN);
    if (tern != 0) {
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  AUG-TERNARY %s %s: the residual was rounded\n",
                   f->name, AUGN[fn]);
        }
    }
    if (mpfr_zero_p(err)) {
        /* 9.5: an error term equal to zero "is returned with the sign of
         * roundTiesTowardZero(x + y)". */
        mpfr_set_zero(want_e, mpfr_signbit(rv) ? -1 : 1);
        goto done;
    }
    {
        mpfr_t rounded;
        int tiny;
        mpfr_set_ui_2exp(emin_mag, 1, f->emin, MPFR_RNDN);
        tiny = mpfr_cmpabs(err, emin_mag) < 0;
        mpfr_init2(rounded, P);
        (void)aug_rttz(f, err, rounded);         /* cannot overflow */
        if (mpfr_equal_p(rounded, err)) {
            mpfr_set(want_e, err, MPFR_RNDN);    /* exactly representable */
            if (tiny)
                fl |= CFT_FLAG_UNDERFLOW;
        } else {
            /* 9.5's one non-representable delivery, augmentedMulti-
             * plication only: the residual rounded the same way, with
             * the underflow flag raised and inexact signalled. */
            mpfr_set(want_e, rounded, MPFR_RNDN);
            fl |= CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
        }
        mpfr_clear(rounded);
    }

done:
    *flags = fl;
    mpfr_clear(a); mpfr_clear(b); mpfr_clear(exact);
    mpfr_clear(rv); mpfr_clear(err); mpfr_clear(emin_mag);
}

/* Both values and the flag word, as ONE case in the ledger. */
static void aug_judge(int ti, int fj, int fn, const fdesc *f,
                      const uint8_t *a, const uint8_t *b,
                      const uint8_t *gr, const uint8_t *ge,
                      mpfr_srcptr wr, mpfr_srcptr we,
                      uint32_t gf, uint32_t wf, cft_status st)
{
    int rbad = (st != CFT_OK) || !agree(f, gr, wr);
    int ebad = (st != CFT_OK) || !agree(f, ge, we);
    int fbad = (gf != wf);
    if (rbad || ebad)
        mismatches++;
    if (fbad)
        flag_mismatches++;
    if (rbad || fbad)
        report_c5(AUGN[fn], "9.5", f, a, b, f, gr, wr, gf, wf, rbad,
                  st != CFT_OK ? "(status!=OK)" : "(r)");
    if (ebad && !rbad)
        report_c5(AUGN[fn], "9.5", f, a, b, f, ge, we, gf, wf, ebad,
                  "(e, the error term)");
    cases++;
    tally[ti][fj]++;
}

static cft_status aug_lib(const fdesc *f, int fn, const uint8_t *a,
                          const uint8_t *b, uint8_t *r, uint8_t *e,
                          uint32_t *fl)
{
    switch (fn) {
    case 0:  return cft_augmented_add(dev, f->fmt, a, b, r, e, 1, fl);
    case 1:  return cft_augmented_sub(dev, f->fmt, a, b, r, e, 1, fl);
    default: return cft_augmented_mul(dev, f->fmt, a, b, r, e, 1, fl);
    }
}

/* 2^E as a normal encoding (E must be >= emin). */
static void aug_pow2(const fdesc *f, long E, int sign, uint8_t *b)
{
    memset(b, 0, 32);
    set_field(b, f->man_w, f->exp_w, (uint64_t)(E + f->emax));
    if (sign)
        set_field(b, 1 + f->exp_w + f->man_w - 1, 1, 1);
}

static void check_augmented(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    static uint8_t xa[96][32], xb[96][32];
    int np = 0, fn, i, j, s;
    uint8_t gr[32], ge[32];

    /* THE TIE, at binade edges: x is 2^k + 1 ulp (an ODD significand,
     * which is the only place roundTiesTowardZero and roundTiesToEven
     * can differ) and y is exactly half an ulp of that binade. */
    {
        long ks[6];
        int nk = 0;
        ks[nk++] = 0;
        ks[nk++] = 1;
        ks[nk++] = f->emin;
        ks[nk++] = f->emin + f->p;
        ks[nk++] = f->emax - 1;
        ks[nk++] = f->emax / 2;
        for (i = 0; i < nk; i++) {
            long k = ks[i];
            if (k - f->p < f->emin || np > 88)
                continue;
            for (s = 0; s <= 1; s++) {
                aug_pow2(f, k, s, xa[np]);
                set_field(xa[np], 0, 1, 1);            /* + 1 ulp: odd */
                aug_pow2(f, k - f->p, 0, xb[np]);      /* half an ulp */
                np++;
                aug_pow2(f, k, s, xa[np]);
                set_field(xa[np], 0, 1, 1);
                aug_pow2(f, k - f->p, 1, xb[np]);      /* and below it */
                np++;
            }
        }
    }
    /* THE OVERFLOW THRESHOLD: the largest finite plus exactly half an
     * ulp is the midpoint 9.5 rounds DOWN, silently; one ulp is past
     * it and goes to an infinity with overflow and inexact. */
    for (s = 0; s <= 1 && np < 92; s++) {
        int k;
        for (k = 0; k < 2; k++) {
            memset(xa[np], 0, 32);
            set_field(xa[np], f->man_w, f->exp_w,
                      (uint64_t)((1ull << f->exp_w) - 2));
            for (i = 0; i < f->man_w; i++)
                set_field(xa[np], i, 1, 1);            /* max normal */
            if (s)
                set_field(xa[np], 1 + f->exp_w + f->man_w - 1, 1, 1);
            aug_pow2(f, f->emax - f->p + k, s, xb[np]);
            np++;
        }
    }
    /* A SUBNORMAL RESIDUAL: 1 against the bottom of the grid, which is
     * underflow with no inexact - the combination 9.5 alone produces. */
    for (i = 0; i < 3 && np < 95; i++) {
        aug_pow2(f, i == 0 ? 0 : (i == 1 ? f->p : f->emax - 1), 0, xa[np]);
        memset(xb[np], 0, 32);
        set_field(xb[np], i, 1, 1);                    /* a tiny subnormal */
        np++;
    }

    for (fn = 0; fn < AUG_COUNT; fn++) {
        for (i = 0; i < pn + np; i++) {
            int jmax = i < pn ? pn : 1;
            for (j = 0; j < jmax; j++) {
                const uint8_t *pa = i < pn ? pool[i] : xa[i - pn];
                const uint8_t *pb = i < pn ? pool[j] : xb[i - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t wr, we;
                cft_status st;

                mpfr_init2(wr, f->p);
                mpfr_init2(we, f->p);
                aug_oracle(f, fn, pa, pb, wr, we, &wf);
                memset(gr, 0, sizeof gr);
                memset(ge, 0, sizeof ge);
                st = aug_lib(f, fn, pa, pb, gr, ge, &gf);
                aug_judge(T_AUG_ADD + fn, fj, fn, f, pa, pb, gr, ge, wr, we,
                          gf, wf, st);
                mpfr_clear(wr);
                mpfr_clear(we);
            }
        }
    }
}

/* ---- clause 5.12: conversions to and from character sequences ------ *
 *
 * MPFR is the right arbiter for these and is used as one in both
 * directions: mpfr_strtofr and mpfr_get_str are correctly rounded in
 * every rounding mode, at any precision, and neither has ever seen
 * this project. So the parse is scored against MPFR's parse and the
 * write against MPFR's digits, values AND flags, in all five
 * attributes at all four rungs.
 *
 * Four things about this block are worth stating rather than leaving
 * to be discovered.
 *
 * 1. There is no mpfr_t that holds the exact value of a decimal
 *    sequence - "0.1" is not dyadic - so c5_round_into cannot be
 *    reused here and chars_round_str below is its derivation with the
 *    source changed from mpfr_set to mpfr_strtofr. Same unbounded
 *    p-bit rounding as the overflow/underflow authority, same
 *    subnormal re-rounding on the format's fixed grid, same p+1
 *    guard/sticky build for RMM - only the thing being rounded
 *    differs. base 0 reads both radices: "0x..." is hexadecimal with a
 *    p exponent, anything else is decimal.
 *
 * 2. RMM is built rather than compared, in both directions, because
 *    MPFR has no ties-to-away. Reading in, it is the same p+1
 *    construction the rest of this file uses. Writing out it is
 *    simpler than that and exactly right: ties-to-away on a DECIMAL
 *    grid rounds up exactly when digit H+1 is 5 or more, and no sticky
 *    is needed for that decision - so the oracle asks mpfr_get_str for
 *    H+1 digits truncated and rounds the last one half-up.
 *
 * 3. The EXACT conversion cannot be asked of mpfr_get_str, which
 *    produces shortest-or-N digits and not the full expansion. It is
 *    scored a different way that is just as strong: the sequence the
 *    library wrote is handed back to mpfr_strtofr at the format's own
 *    precision, and MPFR must report a ternary of ZERO - the parse was
 *    exact - and the same value. A sequence that denotes exactly x is
 *    what "exact" means, and MPFR decides it. Same check for the
 *    hexadecimal form.
 *
 * 4. What is deliberately NOT scored here. The absurd exponents
 *    ("1e999999999999") are outside MPFR's own exponent range, so
 *    feeding them to the oracle would score MPFR's overflow rather
 *    than the format's - the pools stay inside MPFR's range and well
 *    outside every format's, and the bands are scored by the golden
 *    model and the vectors instead. NaN PAYLOADS are not scored here
 *    either: MPFR keeps no payload, so it cannot arbitrate the one
 *    thing 5.12.1's suffix exists for. The 9.7 payload operations are
 *    pure bit surgery with no arithmetic in them at all and belong to
 *    the model, which is where character_check.py scores them.
 */

/* c5_round_into's derivation, on a character sequence. */
static void chars_round_str(const fdesc *f, const char *s, int mi,
                            mpfr_t out, uint32_t *flags)
{
    mpfr_t runb, y;
    int inexact, is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = 0;
    char *end = NULL;
    int t1;

    mpfr_init2(runb, f->p);
    mpfr_init2(y, f->p + 1);
    if (is_rmm) {
        t1 = mpfr_strtofr(y, s, &end, 0, MPFR_RNDZ);
        rmm_round(runb, y, t1 != 0, f->p);
        inexact = (t1 != 0) || !mpfr_equal_p(y, runb);
    } else {
        t1 = mpfr_strtofr(runb, s, &end, 0, rnd);
        inexact = (t1 != 0);
    }

    if (mpfr_zero_p(runb) && !inexact) {
        mpfr_set_prec(out, f->p);
        mpfr_set(out, runb, MPFR_RNDN);          /* signed zero rides along */
        *flags = 0;
        mpfr_clear(runb);
        mpfr_clear(y);
        return;
    }

    {
        long e_res;
        if (mpfr_zero_p(runb)) {
            /* rounded away below the smallest representable: the
             * subnormal branch decides it */
            e_res = (long)f->emin - 1;
        } else {
            e_res = (long)mpfr_get_exp(runb) - 1;
        }

        if (e_res > f->emax) {
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
            mpfr_exp_t save_emin = mpfr_get_emin();
            mpfr_exp_t save_emax = mpfr_get_emax();
            mpfr_t r;
            int t2;
            mpfr_init2(r, f->p);
            mpfr_set_emin(f->emin - f->p + 2);
            mpfr_set_emax(f->emax + 1);
            t2 = mpfr_strtofr(r, s, &end, 0, rnd);
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
            /* RMM on the fixed subnormal grid, from the p+1 truncation
             * - c5_round_into's block, and its granularity argument
             * holds unchanged because y is a truncation here too. */
            int t1b, up, sgn;
            long grid = f->emin - f->man_w;
            mpz_t nn;
            mpfr_t scaled, frac, half;
            t1b = mpfr_strtofr(y, s, &end, 0, MPFR_RNDZ);
            sgn = mpfr_signbit(y) ? 1 : 0;
            mpz_init(nn);
            mpfr_init2(scaled, f->p + 4);
            mpfr_init2(frac, f->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);
            mpfr_get_z(nn, scaled, MPFR_RNDZ);
            mpfr_sub_z(frac, scaled, nn, MPFR_RNDN);
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(nn, nn, 1);
            mpfr_set_prec(out, f->p);
            mpfr_set_z_2exp(out, nn, grid, MPFR_RNDN);
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

/* Read one sequence through the library, both ways compared. */
static void chars_check_parse(int fj, const char *s, int hexform)
{
    const fdesc *f = &FMTS[fj];
    int mi;
    for (mi = 0; mi < 5; mi++) {
        uint8_t d[32];
        uint32_t gf = 0, wf = 0;
        mpfr_t want;
        cft_status st;
        const char *one = s;
        size_t bad = 0;

        mpfr_init2(want, f->p);
        chars_round_str(f, s, mi, want, &wf);
        memset(d, 0, sizeof d);
        st = hexform
             ? cft_from_hex_char(dev, f->fmt, MODES[mi].cr, &one, d, 1, &bad,
                                 &gf)
             : cft_from_decimal_char(dev, f->fmt, MODES[mi].cr, &one, d, 1,
                                     &bad, &gf);
        /* A refusal is its own thing and gets its own line: "the
         * library would not read a sequence MPFR read" and "it read a
         * different number" want different responses from whoever is
         * looking at the report. */
        if (st != CFT_OK && shown < 16) {
            shown++;
            printf("  REFUSED %s %s %s: %.160s\n", f->name,
                   hexform ? "from_hex" : "from_dec", MODES[mi].name, s);
        }
        c5_judge(hexform ? T_FROM_HEX : T_FROM_DEC, fj,
                 hexform ? "from_hex" : "from_dec", MODES[mi].name, f, NULL,
                 NULL, f, d, want, gf, wf, st, s);
        mpfr_clear(want);
    }
}

/* The library's answer, written into a fresh buffer. */
static char *chars_write(int fj, int mi, const uint8_t *a, size_t digits,
                         int hexform, uint32_t *flags, cft_status *st)
{
    const fdesc *f = &FMTS[fj];
    size_t need = 0;
    char *buf;

    *flags = 0;
    *st = hexform ? cft_to_hex_char(dev, f->fmt, a, NULL, 0, &need)
                  : cft_to_decimal_char(dev, f->fmt, MODES[mi].cr, a, digits,
                                        NULL, 0, &need, flags);
    if (need < 2) {
        *st = *st == CFT_OK ? CFT_ERR_INTERNAL : *st;
        return NULL;
    }
    buf = (char *)malloc(need);
    if (!buf) {
        *st = CFT_ERR_OUT_OF_MEMORY;
        return NULL;
    }
    *st = hexform ? cft_to_hex_char(dev, f->fmt, a, buf, need, &need)
                  : cft_to_decimal_char(dev, f->fmt, MODES[mi].cr, a, digits,
                                        buf, need, &need, flags);
    if (*st != CFT_OK) {
        free(buf);
        return NULL;
    }
    return buf;
}

/* "the sequence denotes exactly this value" - MPFR's verdict, which is
 * the whole content of an exact conversion. */
static void chars_check_exact(int fj, const uint8_t *a, const char *s,
                              const char *what, int ti)
{
    const fdesc *f = &FMTS[fj];
    mpfr_t x, back;
    char *end = NULL;
    int t;

    mpfr_init2(x, f->p);
    mpfr_init2(back, f->p);
    enc_to_mpfr(f, a, x);
    t = mpfr_strtofr(back, s, &end, 0, MPFR_RNDN);
    cases++;
    tally[ti][fj]++;
    if (t != 0 || !mpfr_equal_p(back, x) ||
        (end && *end) || mpfr_signbit(back) != mpfr_signbit(x)) {
        mismatches++;
        if (shown < 16) {
            char ha[65];
            shown++;
            hexdump(a, f->esz, ha);
            printf("  MISMATCH %s %s a=0x%s\n", f->name, what, ha);
            printf("    the library wrote %.*s%s\n", 120, s,
                   strlen(s) > 120 ? "..." : "");
            printf("    mpfr_strtofr reads it back ternary %d, equal %d, "
                   "trailing %d\n", t, mpfr_equal_p(back, x),
                   end && *end ? 1 : 0);
        }
    }
    mpfr_clear(x);
    mpfr_clear(back);
}

/* The library's H-digit sequence against mpfr_get_str's. */
static void chars_check_digits(int fj, int mi, const uint8_t *a, size_t h)
{
    const fdesc *f = &FMTS[fj];
    char *got;
    uint32_t gf = 0;
    cft_status st;
    mpfr_t x;
    mpfr_exp_t e10 = 0;
    char *want;
    char buf[512];
    int is_rmm = (MODES[mi].cr == CFT_RMM);
    size_t n = h + (is_rmm ? 1 : 0);
    int bad = 0;

    if (h < 2 || n + 4 > sizeof buf)
        return;                            /* mpfr_get_str wants n >= 2 */

    got = chars_write(fj, mi, a, h, 0, &gf, &st);
    cases++;
    tally[T_TO_DEC][fj]++;
    if (!got) {
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  MISMATCH %s to_dec %s: status %s\n", f->name,
                   MODES[mi].name, cft_strerror(st));
        }
        return;
    }

    mpfr_init2(x, f->p);
    enc_to_mpfr(f, a, x);
    want = mpfr_get_str(buf, &e10, 10, n,
                        x, is_rmm ? MPFR_RNDZ : MODES[mi].mr);
    if (!want) {
        free(got);
        mpfr_clear(x);
        return;
    }
    {
        /* mpfr_get_str writes 0.d1..dn * 10^e10 with the sign as a
         * leading '-'; the library writes d1.d2..dn e (e10 - 1). */
        char digits[520];
        int neg = want[0] == '-';
        long exp10;
        size_t i, len;
        char expect[560];

        snprintf(digits, sizeof digits, "%s", want + (neg ? 1 : 0));
        len = strlen(digits);
        exp10 = (long)e10 - 1;
        if (is_rmm && len == n) {
            /* ties-to-away on a decimal grid: up exactly when the
             * dropped digit is 5 or more, no sticky needed */
            int up = digits[n - 1] >= '5';
            digits[n - 1] = '\0';
            len = n - 1;
            if (up) {
                size_t k = len;
                while (k-- > 0) {
                    if (digits[k] != '9') {
                        digits[k]++;
                        break;
                    }
                    digits[k] = '0';
                    if (k == 0) {
                        digits[0] = '1';
                        exp10++;
                    }
                }
            }
        }
        /* Assemble what the library should have written. */
        {
            char body[540];
            size_t w = 0;
            body[w++] = digits[0];
            if (len > 1) {
                body[w++] = '.';
                for (i = 1; i < len && w + 2 < sizeof body; i++)
                    body[w++] = digits[i];
            }
            body[w] = '\0';
            snprintf(expect, sizeof expect, "%s%se%s%ld", neg ? "-" : "",
                     body, exp10 >= 0 ? "+" : "-",
                     exp10 >= 0 ? exp10 : -exp10);
        }
        if (strcmp(expect, got) != 0)
            bad = 1;
        if (bad) {
            char ha[65];
            mismatches++;
            if (shown < 16) {
                shown++;
                hexdump(a, f->esz, ha);
                printf("  MISMATCH %s to_dec %s a=0x%s h=%lu\n", f->name,
                       MODES[mi].name, ha, (unsigned long)h);
                printf("    lib  %s\n    mpfr %s\n", got, expect);
            }
        }
    }
    free(got);
    mpfr_clear(x);
}

/* The exact decimal of the midpoint between an encoding and its
 * successor, built with GMP - the tie only the attribute can decide,
 * and generated by the ORACLE side so it owes the library nothing.
 * Returns 0 when the expansion does not fit the caller's buffer, which
 * is how the extremes of the wide formats are left out. */
static int chars_midpoint(const fdesc *f, const uint8_t *a, char *buf,
                          size_t cap)
{
    uint8_t up[32];
    mpz_t m1, m2, mid, five;
    mpfr_t v1, v2;
    long e1, e2, e, p10;
    int ok = 0;
    cls ca;

    classify(f, a, &ca);
    if (ca.is_nan || ca.is_inf)
        return 0;
    memcpy(up, a, f->esz);
    enc_step(f, up, 1);
    classify(f, up, &ca);
    if (ca.is_nan || ca.is_inf)
        return 0;

    mpfr_init2(v1, f->p);
    mpfr_init2(v2, f->p);
    enc_to_mpfr(f, a, v1);
    enc_to_mpfr(f, up, v2);
    if (mpfr_zero_p(v1) || mpfr_zero_p(v2) || mpfr_sgn(v1) != mpfr_sgn(v2)) {
        mpfr_clear(v1);
        mpfr_clear(v2);
        return 0;
    }
    mpz_init(m1);
    mpz_init(m2);
    mpz_init(mid);
    mpz_init(five);
    e1 = (long)mpfr_get_z_2exp(m1, v1);
    e2 = (long)mpfr_get_z_2exp(m2, v2);
    e = (e1 < e2 ? e1 : e2) - 1;
    mpz_mul_2exp(m1, m1, (unsigned long)(e1 - e));
    mpz_mul_2exp(m2, m2, (unsigned long)(e2 - e));
    mpz_add(mid, m1, m2);
    mpz_tdiv_q_2exp(mid, mid, 1);              /* (m1 + m2) / 2, exact */
    /* The sign is carried separately below - mpfr_get_z_2exp hands
     * back a NEGATIVE significand for a negative value, and letting
     * mpz_get_str write its own '-' as well produced "--..." */
    mpz_abs(mid, mid);

    /* mid * 2^e is mid * 5^-e * 10^e for e < 0, and mid << e for e >= 0 */
    if (e >= 0) {
        mpz_mul_2exp(mid, mid, (unsigned long)e);
        p10 = 0;
    } else {
        mpz_ui_pow_ui(five, 5, (unsigned long)(-e));
        mpz_mul(mid, mid, five);
        p10 = e;
    }
    if (mpz_sizeinbase(mid, 10) + 24 < cap) {
        char *digits = (char *)malloc(mpz_sizeinbase(mid, 10) + 4);
        if (digits) {
            size_t len, keep;
            long exp10;
            mpz_get_str(digits, 10, mid);
            len = strlen(digits);
            exp10 = (long)len - 1 + p10;
            keep = len;
            while (keep > 1 && digits[keep - 1] == '0')
                keep--;
            digits[keep] = '\0';
            if (keep == 1)
                snprintf(buf, cap, "%s%se%s%ld", mpfr_signbit(v1) ? "-" : "",
                         digits, exp10 >= 0 ? "+" : "-",
                         exp10 >= 0 ? exp10 : -exp10);
            else
                snprintf(buf, cap, "%s%c.%se%s%ld",
                         mpfr_signbit(v1) ? "-" : "", digits[0], digits + 1,
                         exp10 >= 0 ? "+" : "-", exp10 >= 0 ? exp10 : -exp10);
            ok = 1;
            free(digits);
        }
    }
    mpz_clear(m1);
    mpz_clear(m2);
    mpz_clear(mid);
    mpz_clear(five);
    mpfr_clear(v1);
    mpfr_clear(v2);
    return ok;
}

static void check_chars(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    size_t h = cft_format_decimal_digits(f->fmt);
    int i, mi, k;

    /* -- writing out ------------------------------------------------ */
    for (i = 0; i < pn; i++) {
        cls ca;
        classify(f, pool[i], &ca);
        if (ca.is_nan || ca.is_inf || ca.is_zero)
            continue;                     /* MPFR keeps no payload; the
                                           * words are the model's */
        for (mi = 0; mi < 5; mi++) {
            chars_check_digits(fj, mi, pool[i], h);
            chars_check_digits(fj, mi, pool[i], h - 1);
            chars_check_digits(fj, mi, pool[i], h + 3);
            chars_check_digits(fj, mi, pool[i], 5);
            chars_check_digits(fj, mi, pool[i], 2);
        }
        /* The exact forms, in both radices, verified by reading them
         * back through MPFR - which is what "exact" means. */
        {
            uint32_t gf = 0;
            cft_status st;
            char *s = chars_write(fj, 0, pool[i], 0, 0, &gf, &st);
            if (s) {
                if (gf == 0)
                    chars_check_exact(fj, pool[i], s, "to_dec exact",
                                      T_TO_DEC);
                else {
                    mismatches++;
                    if (shown++ < 16)
                        printf("  FLAGS %s to_dec exact raised 0x%02x\n",
                               f->name, (unsigned)gf);
                }
                chars_check_parse(fj, s, 0);
                free(s);
            }
            s = chars_write(fj, 0, pool[i], 0, 1, &gf, &st);
            if (s) {
                chars_check_exact(fj, pool[i], s, "to_hex", T_TO_HEX);
                chars_check_parse(fj, s, 1);
                free(s);
            }
        }
    }

    /* -- reading in: sequences this file builds itself --------------- */
    {
        static const char *const fixed[] = {
            "0", "-0", "1", "-1", "0.1", "0.5", "2.5", "1.25",
            "3.14159265358979323846264338327950288419716939937510",
            "2.71828182845904523536028747135266249775724709369995",
            "1e10", "1e-10", "1e100", "1e-100", "9.99999999999999999e2",
            "123456789012345678901234567890e-15",
            "0.000000000000000000000000000000000000001",
            "99999999999999999999999999999999999999", NULL
        };
        for (k = 0; fixed[k]; k++)
            chars_check_parse(fj, fixed[k], 0);
    }
    {
        static const char *const fixedhex[] = {
            "0x0p+0", "-0x0p+0", "0x1p+0", "-0x1p+0", "0X1P+0",
            "0x1.8p+1", "0x.8p+1", "0x8.p-3", "0x1.fffffffffffffp+1023",
            "0xfffffffffffffffffffffffffffffffffp-4",
            "0x1.23456789abcdefp-100", "-0x1.fedcba9876543p+100", NULL
        };
        for (k = 0; fixedhex[k]; k++)
            chars_check_parse(fj, fixedhex[k], 1);
    }

    /* Exponents inside MPFR's own range and well outside every
     * format's, so overflow and underflow are scored by the oracle
     * rather than assumed. */
    for (k = 0; k < 8 * nrand; k++) {
        char s[128];
        int nd = 1 + (int)(rng() % 34), j, pos = 0;
        long ex = (long)(rng() % 200001) - 100000;
        if (rng() & 1)
            s[pos++] = '-';
        for (j = 0; j < nd; j++)
            s[pos++] = (char)('0' + (int)(rng() % 10));
        snprintf(s + pos, sizeof s - (size_t)pos, "e%ld", ex);
        chars_check_parse(fj, s, 0);
    }

    /* Random hexadecimal significands, mostly WIDER than the format
     * holds - which is the only way a hex sequence can need rounding
     * at all, and so the only part of 5.12.3 an oracle can arbitrate
     * beyond "did it read the bits back". */
    for (k = 0; k < 4 * nrand; k++) {
        char s[256];
        int nd = 1 + (int)(rng() % (unsigned)(f->p / 4 + 6)), j, pos = 0;
        long ex = (long)(rng() % (2u * (unsigned)f->emax + 61)) - f->emax - 30;
        if (rng() & 1)
            s[pos++] = '-';
        s[pos++] = '0';
        s[pos++] = 'x';
        for (j = 0; j < nd; j++) {
            s[pos++] = "0123456789abcdef"[rng() % 16];
            if (j == 0 && (rng() & 1))
                s[pos++] = '.';
        }
        snprintf(s + pos, sizeof s - (size_t)pos, "p%+ld", ex);
        chars_check_parse(fj, s, 1);
    }

    /* The exact halfway sequences: the tie the attribute alone
     * decides, built here from GMP and owing the library nothing. */
    for (i = 0; i < pn; i++) {
        char mid[4096];
        if (chars_midpoint(f, pool[i], mid, sizeof mid))
            chars_check_parse(fj, mid, 0);
    }
}

/* ---- the transcendentals ------------------------------------------- *
 *
 * The nine functions of ABI 0.3 and the eleven of ABI 0.4 against
 * MPFR's own, which is the only external oracle that reaches fp128 and
 * fp256 - and, for these operations, the only external oracle at all:
 * the CPU's libm is neither correctly rounded nor reproducible, so
 * there is nothing at fp32/fp64 to calibrate against either. Agreement
 * here is therefore the whole external case for the transcendental
 * set.
 *
 * For phase 2 the version matters and is asserted at the top of this
 * file: mpfr_sinpi, mpfr_cospi, mpfr_tanpi, mpfr_asinpi, mpfr_acospi,
 * mpfr_atanpi and mpfr_atan2pi are MPFR 4.2.0 functions, and this host
 * carries 4.2.2. They are called DIRECTLY. Composing sinPi out of
 * mpfr_sin(pi * x) would be a comparison against a rounded product -
 * it would agree to a few ulps and decide nothing about the bit this
 * library exists to get right - and for a large x it would not even
 * agree to that. mpfr_asin, mpfr_acos, mpfr_atan and mpfr_atan2 exist
 * in every MPFR and need no guard.
 *
 * Phase 3's nine - mpfr_sin, mpfr_cos, mpfr_tan and the six
 * hyperbolics - exist in every MPFR too. What matters for the first
 * three is that MPFR reduces a HUGE argument correctly, against a pi
 * of its own computed to however many bits the exponent demands, so
 * agreement on sin(2^262143) at fp256 is agreement between two
 * independent reductions. It is slow there - a fraction of a second
 * per call - which is why the phase-3 pool samples the exponent
 * range rather than sweeping it.
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
    TF_POW, TF_HYPOT,
    TF_SINPI, TF_COSPI, TF_TANPI, TF_ASIN, TF_ACOS, TF_ATAN, TF_ATAN2,
    TF_ASINPI, TF_ACOSPI, TF_ATANPI, TF_ATAN2PI,
    TF_SIN, TF_COS, TF_TAN, TF_SINH, TF_COSH, TF_TANH, TF_ASINH,
    TF_ACOSH, TF_ATANH,
    TF_EXP2M1, TF_EXP10, TF_EXP10M1, TF_LOG2P1, TF_LOG10P1, TF_RSQRT,
    TF_POWN, TF_POWR, TF_COMPOUND, TF_ROOTN, TF_COUNT
} tfn;

static const char *const TFN_NAME[TF_COUNT] = {
    "exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow", "hypot",
    "sinpi", "cospi", "tanpi", "asin", "acos", "atan", "atan2",
    "asinpi", "acospi", "atanpi", "atan2pi",
    "sin", "cos", "tan", "sinh", "cosh", "tanh", "asinh", "acosh",
    "atanh",
    "exp2m1", "exp10", "exp10m1", "log2p1", "log10p1", "rsqrt",
    "pown", "powr", "compound", "rootn"
};
static const int TFN_NARGS[TF_COUNT] = {
    1, 1, 1, 1, 1, 1, 1, 2, 2,
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 2, 1, 1
};
/* Which of them read an INTEGER operand beside the floating one. MPFR
 * spells that operand `long`, which is 32 bits on this host, so the
 * campaign's exponents stop at the long range; the whole int64 range is
 * covered against the model by host/tests/transcend_check.py. */
static const int TFN_HASINT[TF_COUNT] = {
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 1, 0, 1, 1
};

static int raw_tfn(mpfr_t r, int fn, const mpfr_t a, const mpfr_t b,
                   long nn, mpfr_rnd_t rnd)
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
    case TF_HYPOT: return mpfr_hypot(r, a, b, rnd);
    /* The Pi-variants arrived in MPFR 4.2.0 and this host carries
     * 4.2.2, so they are called directly rather than composed out of
     * sin(pi*x) - which would be a comparison against a ROUNDED
     * product and would decide nothing about the last bit. That is
     * also why they are guarded: an older MPFR has to fail to build
     * here rather than quietly check something else. */
    case TF_SINPI:   return mpfr_sinpi(r, a, rnd);
    case TF_COSPI:   return mpfr_cospi(r, a, rnd);
    case TF_TANPI:   return mpfr_tanpi(r, a, rnd);
    case TF_ASIN:    return mpfr_asin(r, a, rnd);
    case TF_ACOS:    return mpfr_acos(r, a, rnd);
    case TF_ATAN:    return mpfr_atan(r, a, rnd);
    case TF_ATAN2:   return mpfr_atan2(r, a, b, rnd);
    case TF_ASINPI:  return mpfr_asinpi(r, a, rnd);
    case TF_ACOSPI:  return mpfr_acospi(r, a, rnd);
    case TF_ATANPI:  return mpfr_atanpi(r, a, rnd);
    case TF_ATAN2PI: return mpfr_atan2pi(r, a, b, rnd);
    case TF_SIN:     return mpfr_sin(r, a, rnd);
    case TF_COS:     return mpfr_cos(r, a, rnd);
    case TF_TAN:     return mpfr_tan(r, a, rnd);
    case TF_SINH:    return mpfr_sinh(r, a, rnd);
    case TF_COSH:    return mpfr_cosh(r, a, rnd);
    case TF_TANH:    return mpfr_tanh(r, a, rnd);
    case TF_ASINH:   return mpfr_asinh(r, a, rnd);
    case TF_ACOSH:   return mpfr_acosh(r, a, rnd);
    case TF_ATANH:   return mpfr_atanh(r, a, rnd);
    /* Table 9.1's remainder. exp2m1, exp10m1, log2p1, log10p1, powr,
     * compound_si and rootn_si are MPFR 4.2.0 functions and this host
     * carries 4.2.2; the version is asserted at the top of this file so
     * that an older one fails to BUILD rather than quietly comparing
     * against something composed. Composing exp10m1 out of
     * exp10(x) - 1, or rootn out of exp(log(x)/n), would be a
     * comparison against a rounded intermediate and would decide
     * nothing about the last bit. */
    case TF_EXP2M1:   return mpfr_exp2m1(r, a, rnd);
    case TF_EXP10:    return mpfr_exp10(r, a, rnd);
    case TF_EXP10M1:  return mpfr_exp10m1(r, a, rnd);
    case TF_LOG2P1:   return mpfr_log2p1(r, a, rnd);
    case TF_LOG10P1:  return mpfr_log10p1(r, a, rnd);
    case TF_RSQRT:    return mpfr_rec_sqrt(r, a, rnd);
    case TF_POWN:     return mpfr_pow_si(r, a, nn, rnd);
    case TF_POWR:     return mpfr_powr(r, a, b, rnd);
    case TF_COMPOUND:
        /* THE ONE PLACE THIS CAMPAIGN DOES NOT TRUST MPFR.
         *
         * mpfr_compound_si is off by one unit in the last place for a
         * NEGATIVE n whenever 1 + x is not representable at the working
         * precision - a double rounding of the intermediate sum.
         * Measured on 4.2.2, this host, 2026-09-03, at 24 bits:
         *
         *   compound(1 + 2^-23, -1) toward zero returns 0x7.fffffp-4
         *   where (2 + 2^-23)^-1 computed at 400 bits and rounded once
         *   is 0x7.fffff8p-4;
         *   compound(3 - 2^-22, -1) to nearest returns 0x4p-4 where the
         *   same reference gives 0x4.000008p-4.
         *
         * n = -2 and n = -4 do it too; a NON-NEGATIVE n does not, and
         * mpfr_pow_si and mpfr_rootn_si are sound at every n this
         * campaign uses (all three checked by the same 400-bit
         * reference). So n >= 0 goes through MPFR's own compound, which
         * is the comparison worth having, and n < 0 is built from the
         * EXACTLY formed 1 + x and mpfr_pow_si - still MPFR arithmetic,
         * still one rounding, and not the entry point with the defect.
         *
         * The library's answers were confirmed independently three
         * ways before this workaround was written: the golden model's
         * rigorous mpmath enclosure, the C's own tracked error bound,
         * and python/tests/test_transcend.py's brute-force enclosure at
         * four times the escalation cap all agree with the 400-bit
         * reference and not with mpfr_compound_si. */
        if (nn >= 0 || !mpfr_regular_p(a) || mpfr_cmp_si(a, -1) <= 0)
            return mpfr_compound_si(r, a, nn, rnd);   /* the domain rows */
        {
            mpfr_t s;
            mpfr_exp_t e = mpfr_get_exp(a);
            mpfr_prec_t need = (mpfr_prec_t)((e < 0 ? -e : e) +
                                             (long)mpfr_get_prec(a) + 8);
            int t;
            mpfr_init2(s, need);
            mpfr_add_ui(s, a, 1, MPFR_RNDN);     /* exact at `need` bits */
            t = mpfr_pow_si(r, s, nn, rnd);
            mpfr_clear(s);
            return t;
        }
    default:          return mpfr_rootn_si(r, a, nn, rnd);
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
                                const uint8_t *bb, long nn)
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
    case TF_LOG1P: case TF_LOG2P1: case TF_LOG10P1:
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
    case TF_RSQRT:
        /* the domain is [0, +inf]: a zero is the POLE (divideByZero,
         * 7.3's rule for an exact infinity from a finite operand) and
         * anything below it is out of domain */
        if (ca.is_nan)
            break;
        if (ca.is_zero)
            fl |= CFT_FLAG_DIVBYZERO;
        else if (ca.sign)
            fl |= CFT_FLAG_INVALID;
        break;
    case TF_POWN:
        if (nn == 0 || ca.is_nan)
            break;                       /* pown(x, 0) is 1; NaNs pass */
        if (ca.is_zero && nn < 0)
            fl |= CFT_FLAG_DIVBYZERO;
        break;
    case TF_POWR:
        if (ca.is_nan || cb.is_nan)
            break;                       /* decided in t_oracle */
        if (ca.sign && !ca.is_zero) {
            fl |= CFT_FLAG_INVALID;      /* x < 0, for every y */
        } else if (cb.is_zero && (ca.is_zero || ca.is_inf)) {
            fl |= CFT_FLAG_INVALID;      /* powr(+-0,+-0), powr(inf,+-0) */
        } else if (ca.is_zero && cb.sign && !cb.is_inf) {
            fl |= CFT_FLAG_DIVBYZERO;    /* the pole, not the limit */
        } else if (cb.is_inf && !ca.is_zero && !ca.is_inf) {
            mpfr_t v;
            mpfr_init2(v, f->p);
            enc_to_mpfr(f, ba, v);
            if (mpfr_cmp_ui(v, 1) == 0)
                fl |= CFT_FLAG_INVALID;  /* powr(+1, +-inf) */
            mpfr_clear(v);
        }
        break;
    case TF_COMPOUND: {
        /* the domain is [-1, +inf]: below -1 is invalid EVEN at n = 0,
         * which is what "compound(x, 0) is 1 for x >= -1 or quiet NaN"
         * makes of the row rather than states */
        mpfr_t v;
        int c;
        if (ca.is_nan)
            break;
        if (ca.is_inf) {
            if (ca.sign)
                fl |= CFT_FLAG_INVALID;
            break;
        }
        mpfr_init2(v, f->p);
        enc_to_mpfr(f, ba, v);
        c = mpfr_cmp_si(v, -1);
        if (c < 0)
            fl |= CFT_FLAG_INVALID;
        else if (c == 0 && nn < 0)
            fl |= CFT_FLAG_DIVBYZERO;
        mpfr_clear(v);
        break;
    }
    case TF_ROOTN:
        /* n = 0 is outside the domain for EVERY x, a quiet NaN
         * included; a negative operand with an even n likewise */
        if (nn == 0) {
            fl |= CFT_FLAG_INVALID;
            break;
        }
        if (ca.is_nan)
            break;
        if (ca.is_zero) {
            if (nn < 0)
                fl |= CFT_FLAG_DIVBYZERO;
        } else if (ca.sign && (nn % 2 == 0)) {
            fl |= CFT_FLAG_INVALID;
        }
        break;
    case TF_SINPI: case TF_COSPI:
        if (ca.is_inf)
            fl |= CFT_FLAG_INVALID;      /* no limit at infinity */
        break;
    case TF_TANPI:
        if (ca.is_inf) {
            fl |= CFT_FLAG_INVALID;
        } else if (!ca.is_nan && !ca.is_zero) {
            /* a pole at every half-odd-integer: an exact infinity from
             * finite operands, which is 7.3's divideByZero. Decided on
             * the ENCODING - the lowest set bit's exponent is -1 - so
             * no arithmetic is involved. */
            int lowest = -1, i2, man_lsb;
            long ef2 = (long)get_field(ba, f->man_w, f->exp_w);
            for (i2 = 0; i2 < f->man_w; i2++)
                if (bit_at(ba, i2)) { lowest = i2; break; }
            if (ef2 == 0) {
                man_lsb = (int)(f->emin - f->man_w) +
                          (lowest < 0 ? 0 : lowest);
            } else {
                if (lowest < 0)
                    lowest = f->man_w;
                man_lsb = (int)(ef2 - f->emax - f->man_w) + lowest;
            }
            if (man_lsb == -1)
                fl |= CFT_FLAG_DIVBYZERO;
        }
        break;
    case TF_ASIN: case TF_ACOS: case TF_ASINPI: case TF_ACOSPI: {
        /* |x| > 1 is out of domain, infinities included */
        mpfr_t v;
        if (ca.is_nan)
            break;
        if (ca.is_inf) {
            fl |= CFT_FLAG_INVALID;
            break;
        }
        mpfr_init2(v, f->p);
        enc_to_mpfr(f, ba, v);
        mpfr_abs(v, v, MPFR_RNDN);
        if (mpfr_cmp_si(v, 1) > 0)
            fl |= CFT_FLAG_INVALID;
        mpfr_clear(v);
        break;
    }
    case TF_SIN: case TF_COS: case TF_TAN:
        if (ca.is_inf)
            fl |= CFT_FLAG_INVALID;      /* no limit at infinity */
        break;
    case TF_ACOSH:
        /* the domain is [1, +inf): every zero, every negative value
         * and -infinity are invalid; +infinity is +infinity */
        if (ca.is_nan)
            break;
        if (ca.is_zero || ca.sign) {
            fl |= CFT_FLAG_INVALID;
        } else if (!ca.is_inf) {
            mpfr_t v;
            mpfr_init2(v, f->p);
            enc_to_mpfr(f, ba, v);
            if (mpfr_cmp_si(v, 1) < 0)
                fl |= CFT_FLAG_INVALID;
            mpfr_clear(v);
        }
        break;
    case TF_ATANH: {
        /* the domain is (-1, 1); +-1 is a POLE - an exact infinity
         * from a finite operand, 7.3's divideByZero, the row tanPi
         * takes at a half-integer - and beyond it is invalid,
         * infinities included */
        mpfr_t v;
        int c;
        if (ca.is_nan)
            break;
        if (ca.is_inf) {
            fl |= CFT_FLAG_INVALID;
            break;
        }
        mpfr_init2(v, f->p);
        enc_to_mpfr(f, ba, v);
        mpfr_abs(v, v, MPFR_RNDN);
        c = mpfr_cmp_si(v, 1);
        if (c > 0)
            fl |= CFT_FLAG_INVALID;
        else if (c == 0)
            fl |= CFT_FLAG_DIVBYZERO;
        mpfr_clear(v);
        break;
    }
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
                     const uint8_t *bb, long nn, mpfr_t out,
                     uint32_t *flags)
{
    mpfr_t a, b, runb, r, y;
    cls ca, cb;
    int tunb = 0, inexact, is_rmm = (MODES[mi].cr == CFT_RMM);
    int ovf = 0, unf = 0;
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = tfn_class_flags(f, fn, ba, bb, nn);
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

    /* Two rows where MPFR 4.2.2 and 754-2019 differ, given here the same
     * one-sided help this harness already gives MPFR for signaling NaNs.
     * Both were MEASURED on this host before they were written down.
     *
     *   rSqrt(-0). 9.2.1 says "rSqrt(+-0) is +-infinity"; mpfr_rec_sqrt
     *   returns +infinity for both zeros.
     *
     *   powr's NaN corner. 9.2.1 says "powr(+1, y) is 1 for FINITE y"
     *   and lists "powr(x, qNaN) is qNaN for x >= 0" separately, so
     *   powr(1, qNaN) is a quiet NaN; mpfr_powr returns 1. The whole
     *   corner is decided here so the reading is in one place: a NaN in
     *   either operand gives a quiet NaN, and a negative base gives one
     *   with invalid, whichever the other operand is. */
    if (fn == TF_RSQRT && ca.is_zero && ca.sign) {
        mpfr_set_prec(out, f->p);
        mpfr_set_inf(out, -1);
        *flags = CFT_FLAG_DIVBYZERO;
        goto done;
    }
    if (fn == TF_POWR && (ca.is_nan || cb.is_nan ||
                          (ca.sign && !ca.is_zero))) {
        mpfr_set_prec(out, f->p);
        mpfr_set_nan(out);
        *flags = (!ca.is_nan && ca.sign && !ca.is_zero)
                 ? CFT_FLAG_INVALID : 0;
        goto done;
    }

    /* The unbounded-range evaluation: MPFR's widest exponents, so that
     * an overflow HERE means the true value is past anything the
     * format could hold. */
    mpfr_set_emin(mpfr_get_emin_min());
    mpfr_set_emax(mpfr_get_emax_max());
    mpfr_clear_flags();
    if (is_rmm) {
        int t1 = raw_tfn(y, fn, a, b, nn, MPFR_RNDZ);
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
        tunb = raw_tfn(runb, fn, a, b, nn, rnd);
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
            t2 = raw_tfn(r, fn, a, b, nn, rnd);
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
            t1 = raw_tfn(y, fn, a, b, nn, MPFR_RNDZ);
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
                        const uint8_t *a, const uint8_t *b, long nn,
                        uint8_t *d, cft_status *st)
{
    uint32_t fl = 0;
    int64_t n64 = (int64_t)nn;
    switch (fn) {
    case TF_EXP:   *st = cft_exp(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXPM1: *st = cft_expm1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP2:  *st = cft_exp2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG:   *st = cft_log(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG1P: *st = cft_log1p(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG2:  *st = cft_log2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG10: *st = cft_log10(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_POW:   *st = cft_pow(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    case TF_HYPOT: *st = cft_hypot(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    case TF_SINPI:  *st = cft_sinpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COSPI:  *st = cft_cospi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TANPI:  *st = cft_tanpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ASIN:   *st = cft_asin(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOS:   *st = cft_acos(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN:   *st = cft_atan(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN2:  *st = cft_atan2(dev, f->fmt, rnd, a, b, d, 1, &fl);
                    break;
    case TF_ASINPI: *st = cft_asinpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOSPI: *st = cft_acospi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATANPI: *st = cft_atanpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN2PI: *st = cft_atan2pi(dev, f->fmt, rnd, a, b, d, 1, &fl);
                    break;
    case TF_SIN:    *st = cft_sin(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COS:    *st = cft_cos(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TAN:    *st = cft_tan(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_SINH:   *st = cft_sinh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COSH:   *st = cft_cosh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TANH:   *st = cft_tanh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ASINH:  *st = cft_asinh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOSH:  *st = cft_acosh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATANH:  *st = cft_atanh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP2M1: *st = cft_exp2m1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP10:  *st = cft_exp10(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP10M1:
        *st = cft_exp10m1(dev, f->fmt, rnd, a, d, 1, &fl);
        break;
    case TF_LOG2P1: *st = cft_log2p1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG10P1:
        *st = cft_log10p1(dev, f->fmt, rnd, a, d, 1, &fl);
        break;
    case TF_RSQRT:  *st = cft_rsqrt(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_POWN:
        *st = cft_pown(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    case TF_POWR:
        *st = cft_powr(dev, f->fmt, rnd, a, b, d, 1, &fl);
        break;
    case TF_COMPOUND:
        *st = cft_compound(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    default:
        *st = cft_rootn(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    }
    return fl;
}


/* Operands aimed at the transcendentals specifically, in their own
 * larger pool: the families that matter here - the exact cases, the
 * overflow and underflow thresholds, a base one ulp from 1 - are not
 * the families that matter for an FMA, and the arithmetic phase's
 * 64-operand pool is sized for a cross product this phase does not
 * take. */
/* enc_from_val returns 1 on SUCCESS. build_tpool tested it against 0
 * from the day it was written, so every directed operand it meant to
 * add - the exp2 integers, the log2 powers of two, the log10 powers of
 * ten, the neighbours of 1, the arguments below 2^-(p+3) - was
 * discarded and a zeroed encoding kept in its place. The transcendental
 * phase of this campaign therefore ran on build_pool's specials plus
 * randoms until 2026-09-03. Found while adding the trigonometric pool,
 * whose entries came out at 42 where 192 were asked for. */
#define TPOOL_MAX 208
#define TRIGPOOL_MAX 192

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
        if (enc_from_val(f, 0, mag, 0, pool[n])) {
            if (ks[k] < 0)
                enc_neg(f, pool[n]);
            n++;
        }
        /* 2^k: log2's exact cases, with a neighbour above and below */
        if (enc_from_val(f, 0, 1, ks[k], pool[n])) {
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
            if (!enc_from_val(f, 0, five, e, pool[n]))
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
    if (n < TPOOL_MAX - 10 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
    }
    for (k = 2; k < 12 && n < TPOOL_MAX - 4; k++) {
        if (enc_from_val(f, 0, 1, -(long)f->p - k, pool[n])) {
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

/* The trigonometric pool. The families that catch sinPi are not the
 * families that catch exp: half-integers and quarter-integers (where
 * sinPi and tanPi are exact), integers (where sinPi's zero takes the
 * sign of the ARGUMENT), the top of the range (where every value is an
 * even integer), the two sides of 1 (where asin's domain ends), and
 * every neighbour threshold this set has. */
static int build_trigpool(const fdesc *f, uint8_t pool[][32],
                          uint8_t const base[][32], int nbase, int randoms)
{
    int n = 0, k;
    static const long HALVES[] = { 1, 3, 5, 7, 9, 17, 33 };
    static const long QUARTS[] = { 1, 3, 5, 7, 9, 11, 13 };
    static const long INTS[]   = { 1, 2, 3, 4, 5, 8, 17 };

    memset(pool, 0, sizeof(uint8_t) * TRIGPOOL_MAX * 32);
    /* every special build_pool already constructs - both zeros, both
     * infinities, both NaNs, the subnormal and normal extremes - and
     * then the families this set needs and that one does not */
    for (k = 0; k < nbase && k < 18 && n < TRIGPOOL_MAX; k++)
        memcpy(pool[n++], base[k], 32);

    for (k = 0; k < (int)(sizeof HALVES / sizeof HALVES[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)HALVES[k], -1, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }
    for (k = 0; k < (int)(sizeof QUARTS / sizeof QUARTS[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)QUARTS[k], -2, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_neg(f, pool[n]); n++;
        }
    }
    for (k = 0; k < (int)(sizeof INTS / sizeof INTS[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)INTS[k], 0, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }
    /* the top of the range: every value there is an even integer */
    {
        long tops[4];
        tops[0] = f->p; tops[1] = f->p + 1; tops[2] = 2 * f->p;
        tops[3] = f->emax;
        for (k = 0; k < 4 && n < TRIGPOOL_MAX - 4; k++)
            if (enc_from_val(f, 0, 1, tops[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 0);
                n++;
            }
    }
    /* every neighbour threshold, one step either side */
    {
        long ks[9];
        ks[0] = f->p / 2; ks[1] = f->p / 2 + 1; ks[2] = f->p / 2 + 2;
        ks[3] = f->p; ks[4] = f->p + 1; ks[5] = f->p + 2;
        ks[6] = f->p + 3; ks[7] = 2 * f->p; ks[8] = 4 * f->p;
        for (k = 0; k < 9 && n < TRIGPOOL_MAX - 6; k++) {
            if (enc_from_val(f, 0, 1, -ks[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
            if (enc_from_val(f, 0, 3, -ks[k] - 1, pool[n]))
                n++;
        }
    }
    /* one ulp either side of +-1, where asin's domain ends */
    if (n < TRIGPOOL_MAX - 6 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
    }
    while (n < TRIGPOOL_MAX && randoms-- > 0) {
        rand_enc(f, pool[n]);
        n++;
    }
    return n;
}

/* An mpfr value already rounded into the format, as an encoding.
 * Normal values only, which is all the phase-3 pool asks of it: the
 * significand is exactly p bits, the exponent is in the normal range,
 * and the fields are assembled with mpz so the wide formats need no
 * 64-bit detour. */
static int mpfr_to_enc(const fdesc *f, const mpfr_t v, uint8_t *b)
{
    mpz_t z, enc;
    mpfr_exp_t e2;
    long E;
    int sign = mpfr_signbit(v) ? 1 : 0;

    if (!mpfr_regular_p(v))
        return 0;
    mpz_init(z);
    mpz_init(enc);
    e2 = mpfr_get_z_2exp(z, v);                 /* v = z * 2^e2 */
    mpz_abs(z, z);
    if (mpz_sizeinbase(z, 2) != (size_t)f->p) {
        mpz_clear(z); mpz_clear(enc);
        return 0;
    }
    E = (long)e2 + f->p - 1;                    /* the unbiased exponent */
    if (E < f->emin || E > f->emax) {
        mpz_clear(z); mpz_clear(enc);
        return 0;
    }
    mpz_clrbit(z, (mp_bitcnt_t)f->man_w);       /* the hidden bit */
    mpz_set_si(enc, E + f->emax);
    mpz_mul_2exp(enc, enc, (mp_bitcnt_t)f->man_w);
    mpz_add(enc, enc, z);
    if (sign)
        mpz_setbit(enc, (mp_bitcnt_t)(f->exp_w + f->man_w));
    memset(b, 0, 32);
    mpz_export(b, NULL, -1, 1, 0, 0, enc);
    mpz_clear(z);
    mpz_clear(enc);
    return 1;
}

#define P3POOL_MAX 224

/* The phase-3 pool: what the reduction against pi and the hyperbolics'
 * domain edges need, which neither pool above has. Nothing in it is a
 * typed "known hard case". The arguments nearest a multiple of pi/2 are
 * built here from MPFR's own pi, rounded into the format, with a grid
 * neighbour either side; the sinh/cosh overflow edge from MPFR's ln 2
 * the same way. So the pool is derived at run time from the oracle
 * that judges it, and a wrong constant anywhere would show up as a
 * disagreement rather than as a pool that quietly tested nothing. */
static int build_p3pool(const fdesc *f, uint8_t pool[][32],
                        uint8_t const base[][32], int nbase, int randoms)
{
    int n = 0, k;
    static const long KS[] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                               100, 355, 1000, 12345, 1000000 };
    mpfr_t pi, l2, v, t;

    memset(pool, 0, sizeof(uint8_t) * P3POOL_MAX * 32);
    for (k = 0; k < nbase && k < 18 && n < P3POOL_MAX; k++)
        memcpy(pool[n++], base[k], 32);

    /* powers of two across the exponent range, both signs: the
     * window's START is the argument's exponent, and a power of two is
     * its cleanest probe. The wide formats are sampled - MPFR's own
     * reduction of 2^262143 is the slow half of this campaign. */
    {
        long es[20];
        int ne = 0;
        es[ne++] = f->emin - f->man_w; es[ne++] = f->emin;
        es[ne++] = -f->p; es[ne++] = -f->p / 2; es[ne++] = -2;
        es[ne++] = -1; es[ne++] = 0; es[ne++] = 1; es[ne++] = 2;
        es[ne++] = 3; es[ne++] = 5; es[ne++] = 10; es[ne++] = 20;
        es[ne++] = f->p; es[ne++] = 2 * f->p; es[ne++] = 100;
        es[ne++] = f->emax / 4; es[ne++] = f->emax / 2;
        es[ne++] = f->emax - 1; es[ne++] = f->emax;
        for (k = 0; k < ne && n < P3POOL_MAX - 4; k++)
            if (enc_from_val(f, 0, 1, es[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
    }

    mpfr_init2(pi, (mpfr_prec_t)f->p + 64);
    mpfr_init2(l2, (mpfr_prec_t)f->p + 64);
    mpfr_init2(t, (mpfr_prec_t)f->p + 64);
    mpfr_init2(v, f->p);
    mpfr_const_pi(pi, MPFR_RNDN);
    mpfr_const_log2(l2, MPFR_RNDN);

    /* the representable numbers nearest k*pi/2, from MPFR's pi rounded
     * into the format, each with a grid neighbour either side and its
     * negative: where the reduction cancels and its window widens */
    for (k = 0; k < (int)(sizeof KS / sizeof KS[0]) &&
                n < P3POOL_MAX - 8; k++) {
        mpfr_mul_si(t, pi, KS[k], MPFR_RNDN);
        mpfr_div_2ui(t, t, 1, MPFR_RNDN);
        mpfr_set(v, t, MPFR_RNDN);
        if (mpfr_to_enc(f, v, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }

    /* the sinh/cosh overflow edge: n*ln2 for n = emax, emax+1, emax+2,
     * walked two ulps either way, so the screen fires in exactly the
     * right place and the enclosure decides the rest */
    {
        long ns[3];
        ns[0] = f->emax; ns[1] = f->emax + 1; ns[2] = f->emax + 2;
        for (k = 0; k < 3 && n < P3POOL_MAX - 12; k++) {
            mpfr_mul_si(t, l2, ns[k], MPFR_RNDN);
            mpfr_set(v, t, MPFR_RNDN);
            if (mpfr_to_enc(f, v, pool[n])) {
                uint8_t c[32];
                memcpy(c, pool[n], 32);
                n++;
                memcpy(pool[n], c, 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], c, 32); enc_step(f, pool[n], 0); n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 0); n++;
                memcpy(pool[n], c, 32); enc_neg(f, pool[n]); n++;
            }
        }
    }
    mpfr_clear(pi); mpfr_clear(l2); mpfr_clear(t); mpfr_clear(v);

    /* where tanh stops being separable from 1: 2^bitlen(p+2), straddled */
    {
        int bl = 0, vv = f->p + 2;
        while (vv) { bl++; vv >>= 1; }
        for (k = bl - 1; k <= bl + 1 && n < P3POOL_MAX - 6; k++)
            if (enc_from_val(f, 0, 1, k, pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            }
    }
    /* one ulp either side of +-1: acosh's domain edge and atanh's pole */
    if (n < P3POOL_MAX - 6 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
    }
    /* every tiny threshold in the family, straddled */
    {
        long ks[8];
        ks[0] = f->p / 2 - 1; ks[1] = f->p / 2; ks[2] = f->p / 2 + 1;
        ks[3] = f->p / 2 + 2; ks[4] = f->p; ks[5] = f->p + 2;
        ks[6] = 2 * f->p; ks[7] = 4 * f->p;
        for (k = 0; k < 8 && n < P3POOL_MAX - 4; k++) {
            if (enc_from_val(f, 0, 1, -ks[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
            if (enc_from_val(f, 0, 3, -ks[k] - 1, pool[n]))
                n++;
        }
    }
    while (n < P3POOL_MAX && randoms-- > 0) {
        rand_enc(f, pool[n]);
        n++;
    }
    return n;
}

/* The integer exponents pown, compound and rootn are tried against.
 * Both signs, both parities, a value past p+1 (where the exact-case
 * test gives up), and the ends of the LONG range - which is 32 bits on
 * this host, and is MPFR's own type for these operands. The whole int64
 * range is covered against the model in host/tests/transcend_check.py;
 * what is checked here is agreement with MPFR over what MPFR can be
 * asked. */
static const long TFN_NS[] = {
    0, 1, -1, 2, -2, 3, -3, 5, -5, 17, -17, 120, -120,
    2147483647L, -2147483647L
};
#define TFN_NS_COUNT ((int)(sizeof TFN_NS / sizeof TFN_NS[0]))

static void check_transcend(int fj, uint8_t pool[][32], int pn,
                            uint8_t tpool[][32], int tn,
                            uint8_t hpool[][32], int hn, int first,
                            int last)
{
    const fdesc *f = &FMTS[fj];
    int fn, mi, i, j;

    for (fn = first; fn < last; fn++) {
        int nargs = TFN_NARGS[fn];
        uint64_t esc_before = cft_tr_escalations;
        /* Unary: every operand. Binary: every operand against a strided
         * eighth of the pool, so the pair count stays linear - the full
         * cross product of two hundred operands times five attributes
         * times two functions is not a sharper test, only a longer
         * one. */
        uint8_t (*P)[32] = fn >= TF_EXP2M1 ? tpool
                         : fn >= TF_SIN ? hpool
                         : fn >= TF_SINPI ? tpool : pool;
        int np = fn >= TF_EXP2M1 ? tn
               : fn >= TF_SIN ? hn : fn >= TF_SINPI ? tn : pn;
        int hasn = TFN_HASINT[fn];
        int jstep = nargs == 2 ? (np / 8 > 0 ? np / 8 : 1) : 1;
        int nstep = hasn ? 3 : 1;
        for (mi = 0; mi < 5; mi++) {
            for (i = 0; i < np; i++) {
                int jmax = nargs == 2 ? np : 1;
                int k;
                /* The integer operand is strided the same way a second
                 * encoding is: every n against every operand times five
                 * attributes would be a longer campaign rather than a
                 * sharper one, and the rows that turn on n's sign and
                 * parity are all inside the first few. */
                for (k = hasn ? i % nstep : 0;
                     k < (hasn ? TFN_NS_COUNT : 1); k += nstep) {
                    long nn = hasn ? TFN_NS[k] : 0;
                    for (j = (nargs == 2 ? i % jstep : 0); j < jmax;
                         j += jstep) {
                        const uint8_t *a = P[i];
                        const uint8_t *b = P[j];
                        uint8_t d[32];
                        uint32_t gf, wf = 0;
                        cft_status st = CFT_OK;
                        char extra[48];
                        mpfr_t want;

                        mpfr_init2(want, f->p);
                        t_oracle(f, fn, mi, a, b, nn, want, &wf);
                        memset(d, 0, sizeof d);
                        gf = tfn_lib(f, fn, MODES[mi].cr, a, b, nn, d, &st);
                        if (hasn)
                            snprintf(extra, sizeof extra, "n=%ld", nn);
                        c5_judge(T_EXP + fn, fj, TFN_NAME[fn],
                                 MODES[mi].name, f, a,
                                 nargs == 2 ? b : NULL, f, d, want, gf, wf,
                                 st, hasn ? extra : NULL);
                        mpfr_clear(want);
                    }
                }
            }
        }
        /* Which function escalated, and how often - a total at the
         * end would say that something did without saying what. */
        if (cft_tr_escalations != esc_before)
            printf("  %s %s: %llu Ziv escalation(s), deepest working "
                   "precision so far %llu bits\n", f->name, TFN_NAME[fn],
                   (unsigned long long)(cft_tr_escalations - esc_before),
                   (unsigned long long)cft_tr_max_prec);
    }
}

/* ---- the reductions of clause 9.4 ---------------------------------- *
 *
 * See the banner at the top of this file for what this can and cannot
 * settle. In one line: MPFR decides every NODE, and the TREE is
 * reproduced here rather than judged, because 9.4 leaves the
 * association to the implementation and there is nothing to appeal to.
 */

/* An MPFR value already ON the format's grid -> its encoding. The
 * nodes feed each other - oracle() consumes encodings and produces an
 * mpfr value - so the replay needs the inverse of enc_to_mpfr.
 *
 * Not mpfr_to_enc() above, which takes normal values only and refuses
 * everything else: a reduction's nodes produce infinities, signed
 * zeros, subnormals and NaNs as a matter of course, and those classes
 * are most of what its edges are about.
 *
 * It checks its own work, because a value this function could not
 * represent exactly would silently corrupt every node above it and
 * the campaign would report a library bug. */
static void rd_to_enc(const fdesc *f, mpfr_srcptr x, uint8_t *out)
{
    memset(out, 0, f->esz);
    if (mpfr_nan_p(x)) {
        /* the canonical quiet NaN, which is the only NaN this contract
         * emits and the only one MPFR can be said to have returned */
        set_field(out, f->man_w, f->exp_w, (1ul << f->exp_w) - 1);
        out[(f->man_w - 1) / 8] |= (uint8_t)(1u << ((f->man_w - 1) % 8));
        return;
    }
    if (mpfr_signbit(x))
        out[f->esz - 1] |= 0x80;
    if (mpfr_inf_p(x)) {
        set_field(out, f->man_w, f->exp_w, (1ul << f->exp_w) - 1);
        return;
    }
    if (mpfr_zero_p(x))
        return;                          /* the sign is already in */
    {
        mpz_t z;
        mpfr_exp_t e;
        long ee, ebiased;
        size_t bits, i;
        uint8_t tmp[32];

        mpz_init(z);
        e = mpfr_get_z_2exp(z, x);       /* x = z * 2^e, exactly */
        mpz_abs(z, z);
        bits = mpz_sizeinbase(z, 2);
        ee = (long)e + (long)bits - 1;   /* IEEE-style exponent */
        if (ee >= f->emin) {
            long sh = (long)f->p - (long)bits;
            if (sh > 0)
                mpz_mul_2exp(z, z, (unsigned long)sh);
            else if (sh < 0)
                mpz_fdiv_q_2exp(z, z, (unsigned long)(-sh));
            mpz_clrbit(z, f->man_w);     /* the hidden bit */
            ebiased = ee + f->emax;
        } else {
            long sh = (long)e - (f->emin - f->man_w);
            if (sh > 0)
                mpz_mul_2exp(z, z, (unsigned long)sh);
            else if (sh < 0)
                mpz_fdiv_q_2exp(z, z, (unsigned long)(-sh));
            ebiased = 0;
        }
        memset(tmp, 0, sizeof tmp);
        mpz_export(tmp, NULL, -1, 1, 0, 0, z);
        for (i = 0; i < f->esz; i++)
            out[i] |= tmp[i];
        if (ebiased)
            set_field(out, f->man_w, f->exp_w, (unsigned long)ebiased);
        mpz_clear(z);
    }
    if (!agree(f, out, x)) {
        char h[70];
        hexdump(out, f->esz, h);
        printf("HARNESS BUG: rd_to_enc lost a value at %s -> 0x%s\n",
               f->name, h);
        mismatches++;
    }
}

/* The contract's split: the largest power of two strictly inside the
 * range, so the LEFT child is a perfect subtree. REPRODUCED, not
 * arbitrated. */
static size_t rd_split(size_t lo, size_t hi)
{
    size_t m = hi - lo, k = 1;
    while (k < m)
        k <<= 1;
    return lo + (k >> 1);
}

/* enc (finite, non-zero) -> a significand in +-[1, 2) and the exact
 * scale, the scaled products' leaf and node rule. Exact bit surgery:
 * there is nothing here to round, so there is nothing here for MPFR
 * to arbitrate, and saying so is the point. */
static void rd_norm_split(const fdesc *f, const uint8_t *x, uint8_t *sig,
                          long long *k)
{
    mpz_t enc, man;
    unsigned long biased;
    long e;
    size_t bits, i;
    uint8_t tmp[32];
    int sign = (x[f->esz - 1] >> 7) & 1;

    mpz_init(enc);
    mpz_init(man);
    mpz_import(enc, f->esz, -1, 1, 0, 0, x);
    mpz_fdiv_r_2exp(man, enc, f->man_w);
    mpz_fdiv_q_2exp(enc, enc, f->man_w);
    biased = mpz_get_ui(enc) & ((1ul << f->exp_w) - 1);
    if (biased) {
        mpz_setbit(man, f->man_w);
        e = (long)biased - f->emax - f->man_w;
    } else {
        e = f->emin - f->man_w;
    }
    bits = mpz_sizeinbase(man, 2);
    *k = (long long)e + (long long)bits - 1;
    mpz_mul_2exp(man, man, (unsigned long)(f->man_w - (bits - 1)));
    mpz_clrbit(man, f->man_w);
    memset(sig, 0, f->esz);
    memset(tmp, 0, sizeof tmp);
    mpz_export(tmp, NULL, -1, 1, 0, 0, man);
    for (i = 0; i < f->esz; i++)
        sig[i] |= tmp[i];
    set_field(sig, f->man_w, f->exp_w, (unsigned long)f->emax);
    if (sign)
        sig[f->esz - 1] |= 0x80;
    mpz_clear(enc);
    mpz_clear(man);
}

/* The sum tree over already-transformed leaves, MPFR at every node. */
static void rd_tree(const fdesc *f, int mi, const uint8_t (*leaf)[32],
                    size_t lo, size_t hi, uint8_t *out, uint32_t *flags)
{
    uint8_t l[32], r[32], dummy[32];
    uint32_t lf = 0, rf = 0, nf = 0;
    mpfr_t v;
    size_t mid;

    *flags = 0;
    if (hi - lo == 1) {
        memcpy(out, leaf[lo], f->esz);
        return;
    }
    mid = rd_split(lo, hi);
    rd_tree(f, mi, leaf, lo, mid, l, &lf);
    rd_tree(f, mi, leaf, mid, hi, r, &rf);
    memset(dummy, 0, sizeof dummy);
    mpfr_init2(v, f->p);
    /* ADD reads a and c - b is steered to 1.0 - which oracle() and
     * raw_op() already honour. */
    oracle(f, OP_ADD, mi, l, dummy, r, v, &nf);
    rd_to_enc(f, v, out);
    mpfr_clear(v);
    reduce_nodes++;
    *flags = lf | rf | nf;
}

/* The scaled product tree: MPFR decides the multiply, the extraction
 * is exact. */
static void rd_sp_tree(const fdesc *f, int mi, const uint8_t (*fac)[32],
                       size_t lo, size_t hi, uint8_t *sig,
                       long long *scale, uint32_t *flags)
{
    uint8_t l[32], r[32], prod[32], dummy[32];
    uint32_t lf = 0, rf = 0, nf = 0;
    long long lk = 0, rk = 0, k = 0;
    mpfr_t v;
    size_t mid;

    *flags = 0;
    if (hi - lo == 1) {
        rd_norm_split(f, fac[lo], sig, scale);
        return;
    }
    mid = rd_split(lo, hi);
    rd_sp_tree(f, mi, fac, lo, mid, l, &lk, &lf);
    rd_sp_tree(f, mi, fac, mid, hi, r, &rk, &rf);
    memset(dummy, 0, sizeof dummy);
    mpfr_init2(v, f->p);
    oracle(f, OP_MUL, mi, l, r, dummy, v, &nf);
    rd_to_enc(f, v, prod);
    mpfr_clear(v);
    rd_norm_split(f, prod, sig, &k);
    *scale = lk + rk + k;
    reduce_nodes++;
    *flags = lf | rf | nf;
}

/* The seven, by the order they are tallied in. */
enum { RF_SUM, RF_DOT, RF_SUMSQ, RF_SUMABS,
       RF_PROD, RF_PROD_SUM, RF_PROD_DIFF, RF_COUNT };
static const char *const RFN_NAME[RF_COUNT] = {
    "sum", "dot", "sumsq", "sumabs",
    "scaled_prod", "scaled_prod_sum", "scaled_prod_diff"
};
static const int RFN_BINARY[RF_COUNT] = { 0, 1, 0, 0, 0, 1, 1 };

/* 9.4's special-value tables, replayed. These are the CONTRACT's rows
 * and MPFR has no opinion on them; what MPFR settles is the
 * arithmetic underneath. */
static void rd_classes(const fdesc *f, const uint8_t (*v)[32], size_t n,
                       int *inf, int *zero, int *nan, int *snan, int *sign)
{
    size_t i;
    *inf = *zero = *nan = *snan = *sign = 0;
    for (i = 0; i < n; i++) {
        cls c;
        classify(f, v[i], &c);
        *sign ^= c.sign;
        if (c.is_nan) {
            *nan = 1;
            *snan |= c.is_snan;
        } else if (c.is_inf) {
            *inf = 1;
        } else if (c.is_zero) {
            *zero = 1;
        }
    }
}

#define RD_MAXN 65

static void rd_oracle(const fdesc *f, int fn, int mi,
                      const uint8_t (*a)[32], const uint8_t (*b)[32],
                      size_t n, mpfr_t want, long long *want_sf,
                      uint32_t *wf)
{
    uint8_t leaf[RD_MAXN][32], out[32], dummy[32];
    uint32_t fl = 0, lf = 0;
    int inf = 0, zero = 0, nan = 0, snan = 0, sign = 0;
    size_t i;

    *want_sf = 0;
    memset(dummy, 0, sizeof dummy);

    if (n == 0) {
        if (fn >= RF_PROD) {
            mpfr_set_ui(want, 1, MPFR_RNDN);      /* 9.4: pr = 1, sf = +0 */
        } else {
            mpfr_set_zero(want, 1);               /* 9.4: +0 */
        }
        *wf = 0;
        return;
    }

    /* the leaves */
    for (i = 0; i < n; i++) {
        mpfr_t v;
        switch (fn) {
        case RF_SUM:
            memcpy(leaf[i], a[i], f->esz);
            break;
        case RF_SUMABS:
            /* abs: 5.5.1 says it touches the sign bit and signals
             * nothing, so there is no arithmetic here to arbitrate */
            memcpy(leaf[i], a[i], f->esz);
            leaf[i][f->esz - 1] &= 0x7f;
            break;
        case RF_DOT:
        case RF_SUMSQ:
            mpfr_init2(v, f->p);
            oracle(f, OP_MUL, mi, a[i], fn == RF_DOT ? b[i] : a[i], dummy,
                   v, &lf);
            rd_to_enc(f, v, leaf[i]);
            mpfr_clear(v);
            fl |= lf;
            reduce_nodes++;
            break;
        case RF_PROD:
            memcpy(leaf[i], a[i], f->esz);
            break;
        default:
            mpfr_init2(v, f->p);
            oracle(f, fn == RF_PROD_SUM ? OP_ADD : OP_SUB, mi, a[i], dummy,
                   b[i], v, &lf);
            rd_to_enc(f, v, leaf[i]);
            mpfr_clear(v);
            fl |= lf;
            reduce_nodes++;
            break;
        }
    }

    if (fn < RF_PROD) {
        uint32_t tf = 0;
        /* 9.4 puts an infinity ahead of a NaN for sumSquare and sumAbs,
         * and only for those two. The rows are stated over the OPERAND
         * ELEMENTS, not over the leaves: an element whose square
         * overflows to an infinity is not "an operand element that is
         * an infinity", and squaring a signalling NaN produces a quiet
         * one, so classifying the leaves gets this wrong in both
         * directions. It did, until the campaign said so. */
        rd_classes(f, a, n, &inf, &zero, &nan, &snan, &sign);
        if ((fn == RF_SUMSQ || fn == RF_SUMABS) && inf && nan) {
            mpfr_set_inf(want, 1);
            *wf = snan ? CFT_FLAG_INVALID : 0u;
            return;
        }
        rd_tree(f, mi, (const uint8_t (*)[32])leaf, 0, n, out, &tf);
        enc_to_mpfr(f, out, want);
        *wf = fl | tf;
        return;
    }

    /* The scaled products' rows, in 9.4's order, over the FACTORS -
     * which for scaledProdSum and scaledProdDiff are the rounded sums
     * and differences, and for scaledProd are the elements. */
    rd_classes(f, (const uint8_t (*)[32])leaf, n, &inf, &zero, &nan, &snan,
               &sign);
    if (nan) {
        mpfr_set_nan(want);
        *wf = fl | (snan ? CFT_FLAG_INVALID : 0u);
        return;
    }
    if (inf && zero) {
        mpfr_set_nan(want);
        *wf = fl | CFT_FLAG_INVALID;
        return;
    }
    if (inf) {
        mpfr_set_inf(want, sign ? -1 : 1);
        *wf = fl;
        return;
    }
    if (zero) {
        mpfr_set_zero(want, sign ? -1 : 1);
        *wf = fl;
        return;
    }
    {
        uint32_t tf = 0;
        rd_sp_tree(f, mi, (const uint8_t (*)[32])leaf, 0, n, out, want_sf,
                   &tf);
        enc_to_mpfr(f, out, want);
        *wf = fl | tf;
    }
}

static cft_status rd_lib(const fdesc *f, int fn, cft_round rnd,
                         const uint8_t *a, const uint8_t *b, size_t n,
                         uint8_t *d, long long *sf, uint32_t *flags)
{
    int64_t scale = 0;
    cft_status st;
    *flags = 0;
    switch (fn) {
    case RF_SUM:
        st = cft_reduce(dev, CFT_SUM, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_DOT:
        st = cft_reduce(dev, CFT_DOT, f->fmt, rnd, a, b, d, n, flags, NULL);
        break;
    case RF_SUMSQ:
        st = cft_reduce(dev, CFT_SUMSQ, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_SUMABS:
        st = cft_reduce(dev, CFT_SUMABS, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_PROD:
        st = cft_scaled_prod(dev, f->fmt, rnd, n ? a : NULL, d, &scale, n,
                             flags);
        break;
    case RF_PROD_SUM:
        st = cft_scaled_prod_sum(dev, f->fmt, rnd, n ? a : NULL,
                                 n ? b : NULL, d, &scale, n, flags);
        break;
    default:
        st = cft_scaled_prod_diff(dev, f->fmt, rnd, n ? a : NULL,
                                  n ? b : NULL, d, &scale, n, flags);
        break;
    }
    *sf = (long long)scale;
    return st;
}

static void check_reduce(int fj, uint8_t pool[][32], int pn, int nvec)
{
    static const size_t LENS[] = { 0, 1, 2, 3, 5, 7, 8, 9, 15, 16, 17,
                                   31, 32, 33, 63, 64, 65 };
    const fdesc *f = &FMTS[fj];
    uint8_t va[RD_MAXN][32], vb[RD_MAXN][32];
    uint8_t flat_a[RD_MAXN * 32], flat_b[RD_MAXN * 32];
    uint8_t d[32], big[32], tiny[32];
    int fn, mi, li, v, i;
    int nl = (int)(sizeof LENS / sizeof LENS[0]);

    /* The two ends of the format, built here rather than taken from
     * the pool by index. build_pool's ORDER is its own business -
     * pool[0] is +0 and the tail is random - so a draw that claimed to
     * alternate the extremes while taking pool[0] and pool[pn-1] would
     * be describing something it does not do. It did, until this. */
    memset(big, 0, sizeof big);
    set_field(big, f->man_w, f->exp_w, (1ul << f->exp_w) - 2);
    for (i = 0; i < f->man_w; i++)
        set_field(big, i, 1, 1);                  /* max normal */
    memset(tiny, 0, sizeof tiny);
    set_field(tiny, 0, 1, 1);                     /* min subnormal */

    for (fn = 0; fn < RF_COUNT; fn++) {
        for (mi = 0; mi < 5; mi++) {
            for (li = 0; li < nl; li++) {
                size_t n = LENS[li];
                for (v = 0; v < nvec; v++) {
                    mpfr_t want;
                    long long want_sf = 0, got_sf = 0;
                    uint32_t gf = 0, wf = 0;
                    cft_status st;
                    char extra[96];

                    /* Vectors are drawn from the pool by a stride that
                     * changes with the draw, so a run covers the
                     * specials-heavy pool in different combinations
                     * rather than the same prefix every time. The
                     * fourth draw of every length is the format's two
                     * EXTREMES alternating - the largest finite value
                     * and the smallest subnormal - which is the vector
                     * a scaled product exists for: its true product
                     * leaves the format by hundreds of binades in both
                     * directions and the answer must not. */
                    for (i = 0; i < (int)n; i++) {
                        if (v % 4 == 3) {
                            memcpy(va[i], (i & 1) ? tiny : big, f->esz);
                            memcpy(vb[i], (i & 1) ? big : tiny, f->esz);
                        } else {
                            memcpy(va[i], pool[(i * (v + 1) + li) % pn],
                                   f->esz);
                            memcpy(vb[i], pool[(i * (v + 2) + fn + 1) % pn],
                                   f->esz);
                        }
                        memcpy(flat_a + (size_t)i * f->esz, va[i], f->esz);
                        memcpy(flat_b + (size_t)i * f->esz, vb[i], f->esz);
                    }

                    mpfr_init2(want, f->p);
                    rd_oracle(f, fn, mi, (const uint8_t (*)[32])va,
                              (const uint8_t (*)[32])vb, n, want, &want_sf,
                              &wf);
                    memset(d, 0, sizeof d);
                    st = rd_lib(f, fn, MODES[mi].cr, flat_a,
                                RFN_BINARY[fn] ? flat_b : NULL, n, d,
                                &got_sf, &gf);
                    snprintf(extra, sizeof extra,
                             "n=%lu scale got %lld want %lld",
                             (unsigned long)n, got_sf, want_sf);
                    /* The scale is a second result, so a case that
                     * agrees on pr and disagrees on sf must fail. */
                    if (fn >= RF_PROD && got_sf != want_sf && st == CFT_OK)
                        st = CFT_ERR_INTERNAL;
                    c5_judge(T_RSUM + fn, fj, RFN_NAME[fn], MODES[mi].name,
                             f, n ? va[0] : NULL, NULL, f, d, want, gf, wf,
                             st, extra);
                    mpfr_clear(want);
                }
            }
        }
    }
}

/* ---- the formatOf arithmetic of clause 5.4.1 ----------------------- *
 *
 * MPFR IS A FULL ORACLE HERE, with no footnote, and it is worth saying
 * why: 5.4.1's cross-format operations are DEFINED as "the operands
 * read at their own precision, the infinitely precise result rounded
 * once to the destination", and that sentence is a literal description
 * of mpfr_add / mpfr_mul / mpfr_fma / mpfr_div / mpfr_sqrt with the
 * operand variables at the source precision and the result variable at
 * the destination's. Nothing here restates a rule the way the augmented
 * harness has to restate 9.5's tie, and nothing here reproduces a shape
 * the way the reduction harness reproduces the tree. The library and
 * MPFR are told the same thing and their answers are compared.
 *
 * The exponent range is the DESTINATION's, and it is handled exactly as
 * oracle() handles the same-format case: the unbounded-range result at
 * the destination's precision decides overflow and tininess (the same
 * after-rounding test round_pack applies), and a subnormal landing is
 * re-rounded through the MPFR manual's recipe - emin/emax set to the
 * destination's, mpfr_check_range, mpfr_subnormalize with the ternary.
 * RMM is the p+1 construction the rest of this file uses, at the
 * destination's p.
 *
 * The three DOUBLE-ROUNDING WITNESSES are built here too, from the two
 * descriptors with GMP integers - the cases where computing in the
 * source format and converting down gives a different answer from the
 * single rounding 5.4.1 asks for. They are the only cases in this file
 * whose expected answer would be reached by a plausible wrong
 * implementation, so they are constructed rather than hoped for.
 */

/* Add one to a little-endian encoding: nextUp for a positive finite
 * value that is not the largest, nextDown for a negative one. */
static void enc_inc(uint8_t *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (++b[i] != 0)
            return;
    }
}

static void enc_dec(uint8_t *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (b[i]-- != 0)
            return;
    }
}

/* One case through MPFR, with the operands at fs's precision and the
 * result at fd's - oracle()'s body with the one format split in two.
 * The duplication is deliberate: oracle() is the same-format campaign's
 * and is left exactly as it was, so a change here cannot silently
 * re-verdict 24 million same-format cases. */
static void fo_oracle(const fdesc *fs, const fdesc *fd, mop op, int mi,
                      const uint8_t *ba, const uint8_t *bb,
                      const uint8_t *bc, mpfr_t out, uint32_t *flags)
{
    mpfr_t a, b, c, runb, r, y;
    cls ca, cb, cc;
    int tunb = 0, inexact, nan_in = 0,
        is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = 0;

    classify(fs, ba, &ca);
    classify(fs, bb, &cb);
    classify(fs, bc, &cc);

    mpfr_init2(a, fs->p); mpfr_init2(b, fs->p); mpfr_init2(c, fs->p);
    mpfr_init2(runb, fd->p); mpfr_init2(r, fd->p);
    mpfr_init2(y, fd->p + 1);
    enc_to_mpfr(fs, ba, a);
    enc_to_mpfr(fs, bb, b);
    enc_to_mpfr(fs, bc, c);

    {
        int use_b = (op == OP_MUL || op == OP_FMA || op == OP_DIV);
        int use_c = (op == OP_ADD || op == OP_SUB || op == OP_FMA);
        if (ca.is_snan || (use_b && cb.is_snan) || (use_c && cc.is_snan))
            fl |= CFT_FLAG_INVALID;
        nan_in = ca.is_nan || (use_b && cb.is_nan) || (use_c && cc.is_nan);
    }
    if (op == OP_DIV && cb.is_zero && !ca.is_zero && !ca.is_nan &&
        !ca.is_inf)
        fl |= CFT_FLAG_DIVBYZERO;

    if (is_rmm) {
        int t1;
        raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
        if (!mpfr_number_p(y) || mpfr_zero_p(y)) {
            mpfr_set(runb, y, MPFR_RNDN);
            tunb = 0;
        } else {
            rmm_round(runb, y, t1 != 0, fd->p);
            tunb = !mpfr_equal_p(runb, y) || t1;
        }
    } else {
        raw_op(runb, op, a, b, c, rnd, &tunb);
    }

    if (mpfr_nan_p(runb) && !nan_in)
        fl |= CFT_FLAG_INVALID;

    inexact = (tunb != 0);

    if (mpfr_nan_p(runb) || mpfr_inf_p(runb) || mpfr_zero_p(runb)) {
        mpfr_set(out, runb, MPFR_RNDN);
        if (inexact) fl |= CFT_FLAG_INEXACT;
        *flags = fl;
        goto fo_done;
    }

    {
        mpfr_exp_t e_unb = mpfr_get_exp(runb);
        long e_res = (long)e_unb - 1;

        if (e_res > fd->emax) {
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ) away = 0;
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                mpfr_set_ui_2exp(out, 1, fd->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0) mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
            goto fo_done;
        }

        if (e_res >= fd->emin) {
            mpfr_set(out, runb, MPFR_RNDN);
            if (inexact) fl |= CFT_FLAG_INEXACT;
            *flags = fl;
            goto fo_done;
        }

        if (!is_rmm) {
            mpfr_exp_t save_emin = mpfr_get_emin();
            mpfr_exp_t save_emax = mpfr_get_emax();
            int t2;
            mpfr_set_emin(fd->emin - fd->p + 2);
            mpfr_set_emax(fd->emax + 1);
            raw_op(r, op, a, b, c, rnd, &t2);
            t2 = mpfr_check_range(r, t2, rnd);
            t2 = mpfr_subnormalize(r, t2, rnd);
            mpfr_set_emin(save_emin);
            mpfr_set_emax(save_emax);
            mpfr_set(out, r, MPFR_RNDN);
            if (t2 != 0 || inexact) fl |= CFT_FLAG_INEXACT;
            if (t2 != 0 || inexact) fl |= CFT_FLAG_UNDERFLOW;
            *flags = fl;
        } else {
            int t1, up, sign;
            long grid = fd->emin - fd->man_w;
            mpz_t n;
            mpfr_t scaled, frac, half;
            raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
            sign = mpfr_sgn(y) < 0;
            mpz_init(n);
            mpfr_init2(scaled, fd->p + 4);
            mpfr_init2(frac, fd->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);
            mpfr_get_z(n, scaled, MPFR_RNDZ);
            mpfr_sub_z(frac, scaled, n, MPFR_RNDN);
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(n, n, 1);
            mpfr_set_prec(out, fd->p);
            mpfr_set_z_2exp(out, n, grid, MPFR_RNDN);
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
            if (!mpfr_zero_p(frac) || t1)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(n);
            mpfr_clear(scaled); mpfr_clear(frac); mpfr_clear(half);
            *flags = fl;
        }
        goto fo_done;
    }

fo_done:
    mpfr_clear(a); mpfr_clear(b); mpfr_clear(c);
    mpfr_clear(runb); mpfr_clear(r); mpfr_clear(y);
}

/* The library side. `op` is the same mop the oracle took. */
static cft_status fo_lib(const fdesc *fs, const fdesc *fd, mop op,
                         cft_round rnd, const uint8_t *a, const uint8_t *b,
                         const uint8_t *c, uint8_t *d, uint32_t *fl)
{
    switch (op) {
    case OP_ADD:  return cft_formatof_add(dev, fs->fmt, fd->fmt, rnd,
                                          a, c, d, 1, fl, NULL);
    case OP_SUB:  return cft_formatof_sub(dev, fs->fmt, fd->fmt, rnd,
                                          a, c, d, 1, fl, NULL);
    case OP_MUL:  return cft_formatof_mul(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, d, 1, fl, NULL);
    case OP_FMA:  return cft_formatof_fma(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, c, d, 1, fl, NULL);
    case OP_DIV:  return cft_formatof_div(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, d, 1, fl, NULL);
    default:      return cft_formatof_sqrt(dev, fs->fmt, fd->fmt, rnd,
                                           a, d, 1, fl, NULL);
    }
}

/* An exact value into a source encoding, or 0 if the source cannot hold
 * it. mpfr_to_enc wants a value already at the format's precision, so
 * the caller's variable is set at that precision and the ternary says
 * whether anything was lost. */
static int fo_exact_enc(const fdesc *fs, mpfr_srcptr v, uint8_t *b)
{
    mpfr_t t;
    int tern, ok;
    mpfr_init2(t, fs->p);
    tern = mpfr_set(t, v, MPFR_RNDN);
    ok = (tern == 0) && mpfr_to_enc(fs, t, b);
    mpfr_clear(t);
    return ok;
}

/* The three double-rounding witnesses for (fs -> fd), built from the
 * descriptors. `which`: 0 fma, 1 div, 2 sqrt. Returns 1 when the pair
 * has one - which is exactly when fd is strictly narrower.
 *
 * Each puts the exact result a hair ABOVE a midpoint of the DESTINATION
 * grid and closer to it than half an ulp of the SOURCE, so a first
 * rounding into the source lands on the midpoint and the second ties to
 * even, downward, while the single correct rounding goes up. */
static int fo_witness(const fdesc *fs, const fdesc *fd, int which,
                      uint8_t *ba, uint8_t *bb, uint8_t *bc)
{
    long ps = fs->p, pd = fd->p;
    mpz_t M, Y, T;
    mpfr_t v;
    int ok = 0;

    if (pd >= ps)
        return 0;
    memset(ba, 0, 32); memset(bb, 0, 32); memset(bc, 0, 32);
    mpz_init(M); mpz_init(Y); mpz_init(T);
    mpfr_init2(v, (mpfr_prec_t)(2 * ps + 8));

    mpz_ui_pow_ui(M, 2, (unsigned long)pd);
    mpz_add_ui(M, M, 1);                       /* M = 2^pd + 1, odd */

    if (which == 0) {
        /* a = M * 2^-pd is the destination midpoint just above 1 and a
         * source value; b = 1; c = the source's least subnormal, which
         * is positive and far below the source's own half-ulp at 1. */
        mpfr_set_z_2exp(v, M, -pd, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, ba))
            goto done;
        mpfr_set_ui(v, 1, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, bb))
            goto done;
        bc[0] = 1;                             /* 2^(emin - man_w) */
        ok = 1;
        goto done;
    }

    if (which == 1) {
        /* Y = 2^(ps-1) + 2^(ps-pd) - 1 satisfies Y == -1 (mod 2^pd), so
         * M*Y is one unit short of a multiple of the source grid at
         * weight 2^(1-pd-ps); the dividend is that product plus one
         * unit, and x/y is the midpoint plus one unit over y. */
        mpz_ui_pow_ui(Y, 2, (unsigned long)(ps - 1));
        mpz_ui_pow_ui(T, 2, (unsigned long)(ps - pd));
        mpz_add(Y, Y, T);
        mpz_sub_ui(Y, Y, 1);
        mpfr_set_z_2exp(v, Y, 1 - ps, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, bb))
            goto done;
        mpz_mul(T, M, Y);
        mpz_add_ui(T, T, 1);
        mpfr_set_z_2exp(v, T, 1 - pd - ps, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, ba))
            goto done;
        ok = 1;
        goto done;
    }

    /* which == 2: the square of the midpoint needs 2*pd + 1 bits, which
     * every ordered pair of this ladder holds; the source value one ulp
     * above it has a root a quarter of a source ulp above the midpoint. */
    if (2 * pd + 1 > ps)
        goto done;
    mpz_mul(T, M, M);
    mpfr_set_z_2exp(v, T, -2 * pd, MPFR_RNDN);
    if (!fo_exact_enc(fs, v, ba))
        goto done;
    enc_inc(ba, fs->esz);
    ok = 1;

done:
    mpz_clear(M); mpz_clear(Y); mpz_clear(T);
    mpfr_clear(v);
    return ok;
}

static const mop FO_OPS[6] = { OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_SQRT,
                               OP_FMA };
static const int FO_TALLY[6] = { T_FO_ADD, T_FO_SUB, T_FO_MUL, T_FO_DIV,
                                 T_FO_SQRT, T_FO_FMA };

static void check_formatof(int sfi, int dfi, uint8_t pool[][32], int pn)
{
    const fdesc *fs = &FMTS[sfi], *fd = &FMTS[dfi];
    uint8_t extra[64][32];
    uint8_t d[32];
    int ne = 0, i, oi, mi;
    char note[24];
    mpfr_t v;

    snprintf(note, sizeof note, "->%s", fd->name);
    mpfr_init2(v, (mpfr_prec_t)(fd->p + 4));

    /* The DESTINATION's landmarks, expressed in the source. Every one
     * of them is an unremarkable source value and a decision in the
     * destination, which is the class of case a same-format pool
     * cannot contain. */
    {
        long marks[4];
        int k, nm = 0;
        marks[nm++] = fd->emin - fd->man_w;         /* least subnormal */
        marks[nm++] = fd->emin - fd->man_w - 1;     /* half of it: a tie */
        marks[nm++] = fd->emin;                     /* least normal */
        marks[nm++] = fd->emin - fd->man_w / 2;     /* mid-subnormal */
        for (k = 0; k < nm && ne < 60; k++) {
            mpfr_set_ui_2exp(v, 1, marks[k], MPFR_RNDN);
            if (!fo_exact_enc(fs, v, extra[ne]))
                continue;
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_neg(fs, extra[ne + 1]);
            ne += 2;
        }
    }
    if (ne < 58) {
        /* the largest finite of the destination, and the overflow
         * midpoint above it - 7.4's threshold, invisible from here */
        mpfr_set_ui_2exp(v, 1, fd->emax + 1, MPFR_RNDN);
        mpfr_nextbelow(v);                          /* maxfinite(fd) */
        if (fo_exact_enc(fs, v, extra[ne])) {
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_neg(fs, extra[ne + 1]);
            ne += 2;
        }
        {
            mpfr_t w;
            mpfr_init2(w, (mpfr_prec_t)(fd->p + 1));
            mpfr_set_ui_2exp(w, 1, fd->emax + 1, MPFR_RNDN);
            mpfr_nextbelow(w);                      /* the midpoint */
            if (ne < 58 && fo_exact_enc(fs, w, extra[ne])) {
                memcpy(extra[ne + 1], extra[ne], 32);
                enc_neg(fs, extra[ne + 1]);
                ne += 2;
            }
            mpfr_clear(w);
        }
    }
    if (fs->p > fd->p) {
        /* destination midpoints, with a source-grid neighbour either
         * side - the only place a rounding written against the wrong
         * descriptor can be caught */
        long Es[3];
        int k, nE = 0;
        Es[nE++] = 0;
        Es[nE++] = fd->emax;
        Es[nE++] = fd->emin;
        for (k = 0; k < nE && ne < 58; k++) {
            mpfr_t w;
            mpfr_init2(w, (mpfr_prec_t)(fd->p + 1));
            mpfr_set_ui_2exp(w, 1, Es[k] + 1, MPFR_RNDN);
            mpfr_nextbelow(w);          /* 2^(E+1) - ulp_d/2: a midpoint */
            if (fo_exact_enc(fs, w, extra[ne])) {
                memcpy(extra[ne + 1], extra[ne], 32);
                enc_inc(extra[ne + 1], fs->esz);
                memcpy(extra[ne + 2], extra[ne], 32);
                enc_dec(extra[ne + 2], fs->esz);
                ne += 3;
            }
            mpfr_clear(w);
        }
    }
    mpfr_clear(v);

    for (oi = 0; oi < 6; oi++) {
        mop op = FO_OPS[oi];
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < pn + ne; i++) {
                const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                int jb = (i * 7 + 1) % (pn + ne);
                int jc = (i * 13 + 5) % (pn + ne);
                const uint8_t *b = jb < pn ? pool[jb] : extra[jb - pn];
                const uint8_t *c = jc < pn ? pool[jc] : extra[jc - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;

                mpfr_init2(want, fd->p);
                fo_oracle(fs, fd, op, mi, a, b, c, want, &wf);
                memset(d, 0, sizeof d);
                st = fo_lib(fs, fd, op, MODES[mi].cr, a, b, c, d, &gf);
                c5_judge(FO_TALLY[oi], sfi, OPN[op], MODES[mi].name,
                         fs, a, op == OP_SQRT ? NULL : b, fd, d, want,
                         gf, wf, st, note);
                mpfr_clear(want);
            }
    }

    /* The witnesses, in every attribute: the cases a source-format
     * rounding would get wrong. */
    if (fd->p < fs->p) {
        int w;
        for (w = 0; w < 3; w++) {
            uint8_t wa[32], wb[32], wc[32];
            mop op = (w == 0) ? OP_FMA : (w == 1) ? OP_DIV : OP_SQRT;
            int ti = (w == 0) ? T_FO_FMA : (w == 1) ? T_FO_DIV : T_FO_SQRT;
            if (!fo_witness(fs, fd, w, wa, wb, wc))
                continue;
            for (mi = 0; mi < 5; mi++) {
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;
                mpfr_init2(want, fd->p);
                fo_oracle(fs, fd, op, mi, wa, wb, wc, want, &wf);
                memset(d, 0, sizeof d);
                st = fo_lib(fs, fd, op, MODES[mi].cr, wa, wb, wc, d, &gf);
                c5_judge(ti, sfi, OPN[op], MODES[mi].name, fs, wa,
                         op == OP_SQRT ? NULL : wb, fd, d, want, gf, wf,
                         st, "double-rounding witness");
                mpfr_clear(want);
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
    static uint8_t gpool[TRIGPOOL_MAX][32];
    static uint8_t hpool[P3POOL_MAX][32];
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
        check_chars(fi, pool, pn, 48 * mult);
        check_augmented(fi, pool, pn);
        printf("%s clause5+9.5: %llu cases done (running mismatches: "
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
        int gn = build_trigpool(f, gpool, (const uint8_t (*)[32])pool,
                                pn, randoms);
        int hn = build_p3pool(f, hpool, (const uint8_t (*)[32])pool,
                              pn, randoms);
        uint64_t before = cases;
        check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, 0, TF_SINPI);
        printf("%s transcend: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        before = cases;
        check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, TF_SINPI,
                        TF_SIN);
        printf("%s trig: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
        before = cases;
        check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, TF_SIN,
                        TF_EXP2M1);
        printf("%s radian+hyperbolic: %llu cases done (running "
               "mismatches: %llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
        before = cases;
        check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, TF_EXP2M1,
                        TF_COUNT);
        printf("%s table91: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    /* The seven reductions. Their pools are the arithmetic phase's -
     * the specials are exactly what a reduction's edges turn on - and
     * the campaign reports NODES as well as cases, because a case here
     * is a whole vector and the node count is what MPFR actually
     * arbitrated. */
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn = build_pool(f, pool, randoms);
        uint64_t before = cases, nodes_before = reduce_nodes;
        check_reduce(fi, pool, pn, 4);
        printf("%s reduce: %llu vectors done, %llu nodes arbitrated "
               "(running mismatches: %llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)(reduce_nodes - nodes_before),
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

    /* The formatOf arithmetic of 5.4.1: every ordered pair of formats,
     * all six operations, all five attributes. MPFR is a FULL oracle
     * here - the clause's definition IS "the operands at the source
     * precision, the infinitely precise result rounded once to the
     * destination", which is exactly what mpfr_add and friends do when
     * the variables are declared that way - so nothing in this phase is
     * a restatement of a rule or a reproduction of a shape. */
    for (fi = 0; fi < 4; fi++) {
        int pn = build_pool(&FMTS[fi], pool, randoms);
        int dfi;
        for (dfi = 0; dfi < 4; dfi++) {
            uint64_t before = cases;
            check_formatof(fi, dfi, pool, pn);
            printf("%s->%s formatOf: %llu cases done (running "
                   "mismatches: %llu value, %llu flag)\n",
                   FMTS[fi].name, FMTS[dfi].name,
                   (unsigned long long)(cases - before),
                   (unsigned long long)mismatches,
                   (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
    }

    {
        int t, k;
        printf("\nper-op case counts (convert and formatOf by source "
               "format):\n");
        printf("  %-10s %12s %12s %12s %12s\n", "op", "fp32", "fp64",
               "fp128", "fp256");
        for (t = 0; t < NTALLY; t++) {
            printf("  %-10s", TALLY_NAME[t]);
            for (k = 0; k < 4; k++)
                printf(" %12llu", (unsigned long long)tally[t][k]);
            printf("\n");
        }
    }

    printf("\ntranscendental evaluator: %llu elements, %llu reached the "
           "Ziv loop,\n  %llu escalations, deepest working precision %llu "
           "bits, %llu decided exactly,\n  %llu decided by a neighbour's "
           "side\n",
           (unsigned long long)cft_tr_calls,
           (unsigned long long)cft_tr_ziv_calls,
           (unsigned long long)cft_tr_escalations,
           (unsigned long long)cft_tr_max_prec,
           (unsigned long long)cft_tr_exact,
           (unsigned long long)cft_tr_neighbour);

    printf("reduction against pi: %llu arguments reduced, %llu window "
           "widenings,\n  widest window %llu bits, deepest cancellation "
           "seen %llu bits (allowance %d)\n",
           (unsigned long long)cft_tr_reduce_calls,
           (unsigned long long)cft_tr_reduce_widen,
           (unsigned long long)cft_tr_max_window,
           (unsigned long long)cft_tr_max_cancel,
           CFT_TR_PH_WINDOW_MAX);

    printf("reductions: %llu tree nodes arbitrated by MPFR (the SHAPE of "
           "the tree\n  is this contract's choice and is reproduced by the "
           "harness, not judged\n  by it - 9.4 lets an implementation "
           "associate in any order)\n",
           (unsigned long long)reduce_nodes);

    printf("TOTAL %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    mpfr_free_cache();
    return (mismatches || flag_mismatches) ? 1 : 0;
}
