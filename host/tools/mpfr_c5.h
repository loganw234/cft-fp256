/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The MPFR oracle's clause-5 rules, shared: host/tools/mpfr_check.c (where
 * they were written; its banner above c5_round_into() says what maps onto
 * what, and why) and the wide class modes of host/tools/clause5_soak.c
 * (parcel HXb, 2026-10-27) both include this file, so the soak's fp128 and
 * fp256 clause-5 oracle is mpfr-check's rules and not a second set. It
 * includes mpfr_ieee.h, the emulation the rules round with (parcel HXa).
 *
 * Moved here from mpfr_check.c as it stood at 3ec0081c, unchanged but in
 * two respects. (1) The rules read the attribute from that file's MODES
 * table by index; here they take the contract's attribute (cft_round), and
 * c5_mpfr_rnd() gives the MPFR rounding that table's `mr` column gave for
 * it (RMM's is MPFR_RNDN, which ieee_round_into() reads only to deliver an
 * overflow away from zero, as for RNE: its RMM is the p + 1 build). (2) The
 * bodies of check_rint, check_scaleb, check_convert, check_cvt_from and
 * check_cvt_to that DERIVE the expectation of one case are functions here,
 * each returning the expected value (an mpfr value, or a cvt_to's integer
 * bits) and flags; mpfr_check.c's loops call them where the bodies stood,
 * and its library calls, verdicts, reports and tallies are where they were.
 * rint_by_mode() is c5_rint_value(), and cvt_to's table of targets and their
 * RISC-V FCVT deliveries is C5_TO (mpfr_check.c's TY less its tally column,
 * which is T_TO_I32 + the target's index there).
 *
 * Every MPFR and GMP function called here is in MPFR 4.1.0 and GMP 6.2
 * (WSL cft2204's), so the soak builds against the system's MPFR there;
 * mpfr-check's own floor of 4.2.0 is for its transcendentals, not these.
 */
#ifndef CFT_MPFR_C5_H
#define CFT_MPFR_C5_H

#include "mpfr_ieee.h"

/* The attribute's MPFR rounding, as mpfr_check.c's MODES[].mr gave it. */
static mpfr_rnd_t c5_mpfr_rnd(cft_round cr)
{
    switch (cr) {
    case CFT_RTZ: return MPFR_RNDZ;
    case CFT_RDN: return MPFR_RNDD;
    case CFT_RUP: return MPFR_RNDU;
    default:      return MPFR_RNDN;      /* RNE, and RMM via the p+1 build */
    }
}

/* The rounding of the EXACT finite value x into format f under the
 * attribute: mpfr_ieee.h's ieee_round_into(), as mpfr_check.c's
 * c5_round_into() calls it. */
static void c5_round(const fdesc *f, const mpfr_t x, cft_round cr,
                     mpfr_t out, uint32_t *flags)
{
    ieee_round_into(f, x, c5_mpfr_rnd(cr), cr == CFT_RMM, out, flags);
}

/* roundToIntegral by attribute. RNDN under mpfr_rint is ties-to-even;
 * mpfr_round is ties-to-away; the directed three are their names. The
 * target's p+2 bits always hold the integer exactly, so there is no
 * second rounding hiding in the call. */
static int c5_rint_value(mpfr_t r, const mpfr_t v, cft_round cr)
{
    switch (cr) {
    case CFT_RNE: return mpfr_rint(r, v, MPFR_RNDN);
    case CFT_RTZ: return mpfr_trunc(r, v);
    case CFT_RDN: return mpfr_floor(r, v);
    case CFT_RUP: return mpfr_ceil(r, v);
    default:      return mpfr_round(r, v);
    }
}

/* ---- roundToIntegral ---------------------------------------------- */

/* The expectation of rint of the operand a (format f) under the attribute,
 * the Exact variant when `exact`: want (the caller's, at f->p) and flags.
 * The named variants signal nothing but sNaN invalid; the Exact variant
 * adds inexact iff the value moved; a zero result keeps the operand's
 * sign - the contract's, derived here, not trusted to MPFR's rint. */
static void c5_rint_expect(const fdesc *f, const uint8_t *a, cft_round cr,
                           int exact, mpfr_t want, uint32_t *flags)
{
    uint32_t wf = 0;
    mpfr_t av;
    cls ca;

    classify(f, a, &ca);
    mpfr_init2(av, f->p);
    enc_to_mpfr(f, a, av);
    if (ca.is_nan) {
        mpfr_set_nan(want);
        if (ca.is_snan)
            wf |= CFT_FLAG_INVALID;
    } else {
        int tern = c5_rint_value(want, av, cr);
        if (mpfr_zero_p(want))
            mpfr_setsign(want, want, ca.sign, MPFR_RNDN);
        if (exact && tern != 0)
            wf |= CFT_FLAG_INEXACT;
    }
    mpfr_clear(av);
    *flags = wf;
}

/* ---- scaleB ------------------------------------------------------- */

/* The expectation of scaleB(a, n): the product in unbounded range (exact),
 * then one rounding. n is clamped in the ORACLE only, at
 * +-(4*emax + 2p + 64): past that every nonzero finite operand overflows
 * (or lands below half a subnormal grid step) whatever its exponent, so the
 * delivery and flags are constant in n; the library is given the raw n. */
static void c5_scaleb_expect(const fdesc *f, const uint8_t *a, int64_t n,
                             cft_round cr, mpfr_t want, uint32_t *flags)
{
    uint32_t wf = 0;
    mpfr_t av;
    cls ca;
    int64_t emax = f->emax, p = f->p;

    classify(f, a, &ca);
    mpfr_init2(av, f->p);
    enc_to_mpfr(f, a, av);
    if (ca.is_nan) {
        mpfr_set_nan(want);
        if (ca.is_snan)
            wf |= CFT_FLAG_INVALID;
    } else if (ca.is_inf || ca.is_zero) {
        mpfr_set(want, av, MPFR_RNDN);
    } else {
        int64_t nc = n;
        int64_t lim = 4 * emax + 2 * p + 64;
        if (nc > lim) nc = lim;
        if (nc < -lim) nc = -lim;
        mpfr_mul_2si(av, av, (long)nc, MPFR_RNDN); /* exact */
        c5_round(f, av, cr, want, &wf);
    }
    mpfr_clear(av);
    *flags = wf;
}

/* ---- convertFormat ------------------------------------------------ */

/* The expectation of converting a (format fs) to format fd: the rounding of
 * the exact operand at the destination; NaN as a class, sNaN invalid. */
static void c5_convert_expect(const fdesc *fs, const fdesc *fd,
                              const uint8_t *a, cft_round cr, mpfr_t want,
                              uint32_t *flags)
{
    uint32_t wf = 0;
    mpfr_t av;
    cls ca;

    classify(fs, a, &ca);
    mpfr_init2(av, fs->p);
    enc_to_mpfr(fs, a, av);
    if (ca.is_nan) {
        mpfr_set_nan(want);
        if (ca.is_snan)
            wf |= CFT_FLAG_INVALID;
    } else if (ca.is_inf) {
        mpfr_set_inf(want, ca.sign ? -1 : 1);
    } else {
        c5_round(fd, av, cr, want, &wf);
    }
    mpfr_clear(av);
    *flags = wf;
}

/* ---- convertFromInt ----------------------------------------------- */

/* The expectation of converting the integer whose bits are `raw`, of source
 * type ty (0 i32, 1 u32, 2 i64, 3 u64: the low 32 bits for the 32-bit
 * types), to format f: the integer exactly via mpz, then one rounding. */
static void c5_cvtfrom_expect(const fdesc *f, int ty, uint64_t raw,
                              cft_round cr, mpfr_t want, uint32_t *flags)
{
    uint64_t mag = 0;
    int neg = 0;
    mpfr_t ex;
    mpz_t z;

    switch (ty) {
    case 0: {
        int32_t x = (int32_t)(uint32_t)raw;
        neg = x < 0;
        mag = neg ? ~(uint64_t)(uint32_t)x + 1 : (uint64_t)x;
        mag &= 0xffffffffull;
        break;
    }
    case 1:
        mag = (uint32_t)raw;
        break;
    case 2: {
        int64_t x = (int64_t)raw;
        neg = x < 0;
        mag = neg ? ~(uint64_t)x + 1 : (uint64_t)x;
        break;
    }
    default:
        mag = raw;
        break;
    }

    mpz_init(z);
    mpz_import(z, 1, -1, 8, 0, 0, &mag);
    if (neg)
        mpz_neg(z, z);
    mpfr_init2(ex, 70);
    mpfr_set_z(ex, z, MPFR_RNDN);      /* <= 64 bits: exact */
    c5_round(f, ex, cr, want, flags);
    mpz_clear(z);
    mpfr_clear(ex);
}

/* ---- convertToInteger --------------------------------------------- */

/* The targets, in the order i32, u32, i64, u64, and the delivered values of
 * their invalid cases: the CONTRACT's RISC-V FCVT table, hardcoded from
 * cft.h's doc - NaN and +inf to the type's maximum, -inf and negative
 * overflow to its minimum, a negative rounded below zero to unsigned 0.
 * 754 leaves these open; the contract does not, and MPFR cannot derive a
 * choice. */
static const struct {
    const char *name;
    int width, is_signed;
    uint64_t maxv, minv;
} C5_TO[4] = {
    { "to_i32", 32, 1, 0x7fffffffull, 0x80000000ull },
    { "to_u32", 32, 0, 0xffffffffull, 0 },
    { "to_i64", 64, 1, 0x7fffffffffffffffull, 0x8000000000000000ull },
    { "to_u64", 64, 0, 0xffffffffffffffffull, 0 },
};

/* The expectation of converting a (format f) to target ty (C5_TO's index)
 * under the attribute, the Exact variant when `exact`: the delivered
 * integer's bits (want64; a 32-bit target's in its low 32) and the flags.
 * mpfr_rint at p+2 bits (always exact: the integer part of a p-bit value
 * carries at most p+1 bits), the range test in mpz, the table above for
 * the invalid cases. Invalid pre-empts inexact, and only the Exact
 * variants report inexact at all. */
static void c5_cvtto_expect(const fdesc *f, const uint8_t *a, int ty,
                            cft_round cr, int exact, uint64_t *want64,
                            uint32_t *flags)
{
    uint32_t wf = 0;
    uint64_t w = 0;
    mpz_t zmax, zmin, zr, zt;
    mpfr_t av, R;
    cls ca;

    mpz_init(zmax); mpz_init(zmin); mpz_init(zr); mpz_init(zt);
    mpz_import(zmax, 1, -1, 8, 0, 0, &C5_TO[ty].maxv);
    if (C5_TO[ty].is_signed) {
        mpz_import(zmin, 1, -1, 8, 0, 0, &C5_TO[ty].minv);
        mpz_neg(zmin, zmin);
    }

    classify(f, a, &ca);
    mpfr_init2(av, f->p);
    mpfr_init2(R, f->p + 2);
    enc_to_mpfr(f, a, av);

    if (ca.is_nan) {
        w = C5_TO[ty].maxv;
        wf = CFT_FLAG_INVALID;
    } else if (ca.is_inf) {
        w = ca.sign ? C5_TO[ty].minv : C5_TO[ty].maxv;
        wf = CFT_FLAG_INVALID;
    } else {
        int tern = c5_rint_value(R, av, cr);
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
            w = oor < 0 ? C5_TO[ty].minv : C5_TO[ty].maxv;
            wf = CFT_FLAG_INVALID;  /* pre-empts inexact */
        } else {
            if (mpz_sgn(zr) >= 0) {
                uint64_t wv = 0;
                mpz_export(&wv, NULL, -1, 8, 0, 0, zr);
                w = wv;
            } else {
                uint64_t wv = 0;
                mpz_neg(zt, zr);
                mpz_export(&wv, NULL, -1, 8, 0, 0, zt);
                w = ~wv + 1;
            }
            if (exact && tern != 0)
                wf = CFT_FLAG_INEXACT;
        }
    }

    mpfr_clear(av);
    mpfr_clear(R);
    mpz_clear(zmax); mpz_clear(zmin); mpz_clear(zr); mpz_clear(zt);
    *want64 = w;
    *flags = wf;
}

#endif /* CFT_MPFR_C5_H */
