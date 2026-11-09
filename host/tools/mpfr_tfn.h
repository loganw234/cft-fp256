/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The MPFR oracle for the transcendental functions, shared: host/tools/
 * mpfr_check.c (where it was written, and whose banner above check_transcend
 * explains every choice in it) and host/tools/routine_sweep.c (parcel M4X,
 * 2026-11-09) both include this file, so the sweep's oracle is mpfr-check's
 * and not a second one. It sits on mpfr_ieee.h, as mpfr_ieee.h sits on
 * nothing, and is the second file of that kind (mpfr_c5.h is the third).
 *
 * Moved here from mpfr_check.c as it stood at 76dcdddb, unchanged but in two
 * respects:
 *
 *  1. t_oracle() read the attribute from that file's MODES table by index;
 *     here ieee_tfn_oracle() takes it as two parameters (the MPFR rounding
 *     and whether the attribute is RMM), as ieee_oracle() does. mpfr_check.c
 *     keeps t_oracle() as a one-line wrapper that passes MODES[mi].mr and
 *     MODES[mi].cr == CFT_RMM, which is what its body read before.
 *  2. mpfr_check.c refuses MPFR below 4.2.0 at compile time (its #error
 *     stays there). This header must also build on 4.1.0, for the thirteen
 *     routines of the fp32 sweep (exp, exp2, expm1, log, log2, log1p, sin,
 *     cos, tan, atan, asin, acos, atan2), none of which needs a 4.2 call. The
 *     fourteen functions that arrived in 4.2.0 are therefore given, below,
 *     under #if MPFR_VERSION < 4.2.0 only, a stand-in macro that refuses by
 *     name at run time (tfn_needs_42(), exit 3). raw_tfn() is otherwise the
 *     text it was, and on 4.2.0 or newer the stand-ins do not exist.
 *
 * It needs <stdio.h> and <stdlib.h> for the refusal, and defines get_field(),
 * which mpfr_check.c also uses and no longer defines itself.
 */
#ifndef CFT_MPFR_TFN_H
#define CFT_MPFR_TFN_H

#include <stdio.h>
#include <stdlib.h>

#include "mpfr_ieee.h"

#if MPFR_VERSION < MPFR_VERSION_NUM(4, 2, 0)
static int tfn_needs_42(const char *fn)
{
    fprintf(stderr, "mpfr_tfn.h: %s needs MPFR 4.2.0 or newer; this build "
            "has MPFR %s\n", fn, MPFR_VERSION_STRING);
    exit(3);
    return 0;
}
#define mpfr_sinpi(r, a, rnd)          tfn_needs_42("mpfr_sinpi")
#define mpfr_cospi(r, a, rnd)          tfn_needs_42("mpfr_cospi")
#define mpfr_tanpi(r, a, rnd)          tfn_needs_42("mpfr_tanpi")
#define mpfr_asinpi(r, a, rnd)         tfn_needs_42("mpfr_asinpi")
#define mpfr_acospi(r, a, rnd)         tfn_needs_42("mpfr_acospi")
#define mpfr_atanpi(r, a, rnd)         tfn_needs_42("mpfr_atanpi")
#define mpfr_atan2pi(r, a, b, rnd)     tfn_needs_42("mpfr_atan2pi")
#define mpfr_exp2m1(r, a, rnd)         tfn_needs_42("mpfr_exp2m1")
#define mpfr_exp10m1(r, a, rnd)        tfn_needs_42("mpfr_exp10m1")
#define mpfr_log2p1(r, a, rnd)         tfn_needs_42("mpfr_log2p1")
#define mpfr_log10p1(r, a, rnd)        tfn_needs_42("mpfr_log10p1")
#define mpfr_powr(r, a, b, rnd)        tfn_needs_42("mpfr_powr")
#define mpfr_compound_si(r, a, n, rnd) tfn_needs_42("mpfr_compound_si")
#define mpfr_rootn_si(r, a, n, rnd)    tfn_needs_42("mpfr_rootn_si")
#endif

static uint64_t get_field(const uint8_t *b, int lo, int n)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < n; i++)
        v |= (uint64_t)bit_at(b, lo + i) << i;
    return v;
}

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

/* One transcendental case through MPFR, delivered into the format, under
 * the attribute (rnd, is_rmm). */
static void ieee_tfn_oracle(const fdesc *f, int fn, mpfr_rnd_t rnd,
                            int is_rmm, const uint8_t *ba,
                            const uint8_t *bb, long nn, mpfr_t out,
                            uint32_t *flags)
{
    mpfr_t a, b, runb, r, y;
    cls ca, cb;
    int tunb = 0, inexact;
    int ovf = 0, unf = 0;
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
            /* The sign BIT: y is recomputed here at MPFR's DEFAULT
             * exponent range, where a value this far below the
             * format's grid underflows to a SIGNED zero, and
             * mpfr_sgn of a signed zero is 0. On an LP64 host
             * (mpfr_exp_t 64-bit) the unbounded evaluation above
             * holds pown(-2.5, -2147483647) without underflowing, so
             * it lands here, and until 2026-09-30 came out +0 where
             * libcft and the golden model give -0: 37 cases on
             * amd-arc-box. With a 32-bit mpfr_exp_t (Windows)
             * that evaluation underflows first, and the underflow
             * branch above reads the sign bit already. */
            sign = mpfr_signbit(y) != 0;
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

#endif /* CFT_MPFR_TFN_H */
