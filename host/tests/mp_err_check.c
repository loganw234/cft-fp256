/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The multiprecision evaluator's error claims, each held exactly: the
 * rules of its arithmetic, its constants' count, and its logarithm's
 * conversion of an argument's error.
 *
 * host/src/mpfloat.c carries with every value a count of units of
 * 2^-W of relative error, and derives a rule for each operation (its
 * header, "The error bounds, derived"). Each rule claims that when the
 * operands' true values lie anywhere in their enclosures v(1 +- e),
 * the true result lies in the enclosure the operation reports. This
 * holds each rule to that claim on operands built field by field - any
 * significand, exponent, sign, width and count, from zero to infinity
 * - and computes every verdict in GMP's integers, so the library's own
 * bigint never checks itself. The worst case over the operands'
 * enclosures, exactly:
 *
 *   add, sub         |a + b - r| + ea|a| + eb|b| <= er|r|
 *   mul, div         all four corners of the operands' enclosures:
 *                    the true result is affine or monotone in each
 *                    operand, so its extremes are there
 *   mul_ui, div_ui   both ends of the one operand's enclosure
 *   sqrt             both ends, squared so that the comparison stays
 *                    rational; the low end at max(0, 1 - ea), the
 *                    operand being known nonnegative wherever the
 *                    evaluator takes a root
 *   set_bn           the truncation of an exact value
 *   cmp_int          a +1 or a -1 must hold for the whole enclosure
 *
 * and the count's own arithmetic (cft_mp_err_*) against exact integers:
 * every result at or above the exact one, canonical, and exact
 * wherever mpfloat.h says it is.
 *
 * Two error claims outside those rules are held end to end, against
 * MPFR (since verifier-W5 found, on 2026-09-30, that nothing held
 * them):
 *
 *   cft_mp_const   the true constant lies in the enclosure of the value
 *                  it returns, for all six, at every W from 2 to
 *                  CFT_MP_PREC_MAX - the widest any caller asks for
 *   mp_log_of_mp   src/transcend.c's conversion of an argument's error
 *                  into its logarithm's: for every V in the argument's
 *                  enclosure, log V lies in the result's - log is
 *                  increasing, so the enclosure's two ends decide it,
 *                  and a finite count where that enclosure reaches
 *                  zero fails. A fixed-seed sample at the working
 *                  widths the evaluator takes a logarithm at, 104 to
 *                  928, with arguments of that width, narrower and
 *                  wider, and counts from zero past 2^W to infinity.
 *                  The function is static: a probe build of
 *                  src/transcend.c (-DCFT_TRANSCEND_PROBE, this
 *                  tool's make target and nothing else) reaches it
 *
 * Each true value is bracketed by MPFR's two directed roundings - the
 * constant, or the logarithm of an end, rounded down and up - so it lies
 * between them and a verdict that holds is a proof; the enclosure's
 * ends are exact dyadics, compared exactly. NOT held here: transcend.c's
 * own allowances, such as a truncated series' tail or the reduction
 * window's (mp_bump). Those are its algorithms' analysis, and reach the
 * gate only through the results the transcend and mpfr stages compare.
 *
 * Two more things are held wherever the operands are W bits wide and
 * their counts 2^40 or less - the old count's range:
 *
 *   monotonicity   every count a rule gives is at least the one the
 *                  rules before 2026-09-30 gave (as at aeb3f5e). The
 *                  header's argument that no answer changes rests on
 *                  it.
 *   the control    the old rules' counts, put through the same
 *                  verdicts, must FAIL on some operands: the clamp at
 *                  2^40, and at W = 6 the second-order terms the old
 *                  rules left to slack. A checker that cannot fail them
 *                  could not see a rule that is not a bound.
 *
 * The two MPFR legs have controls of their own, which must fail too: a
 * constant's count cut to one unit, half the truncation it carries, and
 * the logarithm with its argument's error left out.
 *
 * And one regression end to end, verifier-W4's: two subtractions at
 * W = 88 through which the old code scaled a clamp back down into an
 * ordinary-looking count of 34, against a worst true error of 2^46.97
 * units (the section "regressions" below).
 *
 * The old rules are transcribed below from the old code. Built with
 * -DMP_ERR_CHECK_BASE against the old tree itself, this file checks
 * that transcription against the old library, operand by operand, and
 * reports the old library's own failures - which is how the control
 * was confirmed against the real thing, not a copy of it. That build
 * leaves the MPFR legs out (the old tree has no probe) and needs GMP
 * alone.
 *
 *     mp-err-check              W = 6 exhaustively (every significand
 *                               pair, alignment and sign pair, and
 *                               fourteen counts each), then a
 *                               fixed-seed sample: 100,000 trials of
 *                               each operation at each width from 8
 *                               to 128 bits, a quarter of that at 256
 *                               and a sixteenth at 512 and 928, a
 *                               million of the count's arithmetic,
 *                               the six constants at every width, and
 *                               8,000 logarithm arguments. The
 *                               runner's mpfr stage runs this: about
 *                               half a minute on the Windows desktop.
 *     mp-err-check --full       the full random sweep: ten times the
 *                               sample, ten million of the arithmetic
 *                               and 80,000 logarithm arguments
 *     mp-err-check --seed N     another seed for the sample
 *     mp-err-check --per N      N trials per width instead
 *     mp-err-check --logs N     N logarithm arguments instead
 *
 * Exit 0 when every rule held and the controls failed; 1 otherwise,
 * with the first failures printed.
 */

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <math.h>

#include <gmp.h>
#ifndef MP_ERR_CHECK_BASE
#include <mpfr.h>
#endif

#include "../src/mpfloat.h"

#ifndef MP_ERR_CHECK_BASE
/* src/transcend.c's probe, compiled into this tool alone by its make
 * target (-DCFT_TRANSCEND_PROBE): mp_log_of_mp itself. */
int cft_tr_probe_log_of_mp(cft_mp *r, const cft_mp *v, int W);
#endif

#define OLD_MAX ((uint64_t)1 << 40)      /* the old count's clamp */

/* ---- exact integers ------------------------------------------------ */

/* unsigned long is 32 bits on Windows, so a uint64 goes in halves. */
static void z_set_u64(mpz_t z, uint64_t v)
{
    mpz_set_ui(z, (unsigned long)(v >> 32));
    mpz_mul_2exp(z, z, 32);
    mpz_add_ui(z, z, (unsigned long)(v & 0xffffffffu));
}

static void z_set_i64(mpz_t z, int64_t v)
{
    uint64_t u = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
    z_set_u64(z, u);
    if (v < 0)
        mpz_neg(z, z);
}

static long z_bitlen(const mpz_t z)
{
    return mpz_sgn(z) ? (long)mpz_sizeinbase(z, 2) : 0;
}

static void z_from_bn(mpz_t z, const cft_bn *b)
{
    mpz_import(z, (size_t)b->n, -1, 4, 0, 0, b->v);
}

static int bn_from_z(cft_bn *b, const mpz_t z)
{
    size_t n = 0;
    if (mpz_sgn(z) <= 0 || z_bitlen(z) > CFT_BN_BITS - 32)
        return 1;
    cft_bn_zero(b);
    mpz_export(b->v, &n, -1, 4, 0, 0, z);
    b->n = (int)n;
    return 0;
}

/* x = (-1)^s * m * 2^sh, sh >= 0; x may be m. */
static void zterm(mpz_t x, int s, const mpz_t m, long sh)
{
    mpz_mul_2exp(x, m, (mp_bitcnt_t)sh);
    if (s)
        mpz_neg(x, x);
}

/* 2^w + sigma * e */
static void one_pm(mpz_t x, long w, int sigma, const mpz_t e)
{
    mpz_set_ui(x, 1);
    mpz_mul_2exp(x, x, (mp_bitcnt_t)w);
    if (sigma > 0)
        mpz_add(x, x, e);
    else
        mpz_sub(x, x, e);
}

static long lmin(long a, long b)
{
    return a < b ? a : b;
}

/* ---- the random source: fixed, and the same on every host ---------- */

static uint64_t rs = 0x9E3779B97F4A7C15ull;

static uint64_t next(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 7;
    rs ^= rs << 17;
    return rs;
}

static uint64_t below(uint64_t n)
{
    return n ? next() % n : 0;
}

/* A random significand of exactly w bits. */
static void rnd_sig(mpz_t z, long w)
{
    long i;
    mpz_set_ui(z, 0);
    for (i = 0; i < w; i += 32) {
        mpz_mul_2exp(z, z, 32);
        mpz_add_ui(z, z, (unsigned long)(next() & 0xffffffffu));
    }
    mpz_fdiv_r_2exp(z, z, (mp_bitcnt_t)w);
    mpz_setbit(z, (mp_bitcnt_t)(w - 1));
}

/* ---- counts ---------------------------------------------------------- */

/* A count as this file writes one: c * 2^k units, or infinity. */
typedef struct {
    uint64_t c;
    long k;
    int inf;
} spec;

static spec sp(uint64_t c, long k)
{
    spec s;
    s.c = c;
    s.k = k;
    s.inf = 0;
    return s;
}

static spec sp_inf(void)
{
    spec s = sp(1, 0);
    s.inf = 1;
    return s;
}

static spec sp_pow2(long j)
{
    return j <= 62 ? sp((uint64_t)1 << j, 0) : sp((uint64_t)1 << 62, j - 62);
}

/* The largest count written here below 2^j, j >= 1. */
static spec sp_below(long j)
{
    const uint64_t top = ((uint64_t)1 << 63) - 1;
    return j <= 63 ? sp((((uint64_t)1 << (j - 1)) - 1) * 2 + 1, 0)
                   : sp(top, j - 63);
}

/* Fourteen counts that mark every regime a rule has, at width W: zero,
 * small, either side of 2^(W-1) (div's and the log's limit) and of 2^W
 * (sqrt's), a relative error of 8, either side of the old clamp, the
 * start of the exponent, 3 * 2^100, and infinity. */
#define NSPEC 14

static spec spec_at(int i, int W)
{
    switch (i) {
    case 0:  return sp(0, 0);
    case 1:  return sp(1, 0);
    case 2:  return sp(3, 0);
    case 3:  return sp_below(W - 1);
    case 4:  return sp_pow2(W - 1);
    case 5:  return sp_below(W);
    case 6:  return sp_pow2(W);
    case 7:  return sp_pow2(W + 3);
    case 8:  return sp(OLD_MAX, 0);
    case 9:  return sp(OLD_MAX + 1, 0);
    case 10: return sp(((uint64_t)1 << 63) - 1, 0);
    case 11: return sp((uint64_t)1 << 62, 2);          /* 2^64 */
    case 12: return sp((uint64_t)3 << 61, 39);         /* 3 * 2^100 */
    default: return sp_inf();
    }
}

static spec rnd_spec(int W)
{
    uint64_t c;
    long k = 0;
    if (next() & 1)
        return spec_at((int)below(NSPEC), W);
    c = (next() >> 1) >> below(63);
    if (below(4) == 0)
        k = (long)below((uint64_t)(2 * W + 64));
    return sp(c, k);
}

/* Within the old count's range: where the old rules can be compared. */
static int spec_small(spec s)
{
    return !s.inf && s.k == 0 && s.c <= OLD_MAX;
}


#ifdef MP_ERR_CHECK_BASE
/* The old field, a uint64_t. */
static int put_err(cft_mp *x, spec s)
{
    if (s.inf || s.k >= 64 || (s.k > 0 && (s.c >> (64 - s.k))))
        return 0;                      /* the old field cannot hold it */
    x->err = s.c << s.k;
    return 1;
}

static void get_err(mpz_t z, int *inf, const cft_mp *x)
{
    *inf = 0;
    z_set_u64(z, x->err);
}
#else
static int put_err(cft_mp *x, spec s)
{
    x->err = s.inf ? cft_mp_err_inf()
                   : cft_mp_err_up(cft_mp_err_u64(s.c), s.k);
    return 1;
}

static void get_err(mpz_t z, int *inf, const cft_mp *x)
{
    *inf = cft_mp_err_is_inf(x->err);
    z_set_u64(z, x->err.c);
    if (!*inf)
        mpz_mul_2exp(z, z, (mp_bitcnt_t)x->err.k);
}
#endif

/* ---- the tally ------------------------------------------------------- */

typedef struct {
    const char *name;
    unsigned long long checked;   /* results the verdict judged */
    unsigned long long over;      /* ... that were over their bound */
    unsigned long long refused;   /* the rule's own refusals */
    unsigned long long unheld;    /* operands the old field cannot hold */
    unsigned long long cmp;       /* compared with the old rules */
    unsigned long long below_old; /* ... where the count was below theirs */
    unsigned long long ctl_fail;  /* ... where their count failed */
    unsigned long long model;     /* base mode: transcription != library */
    unsigned long long decided;   /* cmp_int: answers other than 0 */
} tally;

static unsigned long long failures;

static void fail(tally *T, const char *what, const char *fmt, ...)
{
    va_list ap;
    failures++;
    if (failures > 40)
        return;
    printf("  FAIL %s: %s: ", T->name, what);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
}

/* ---- operands ---------------------------------------------------------- */

static mpz_t ma, mb, mr, Ea, Eb, Er, Eo, t1, t2, t3, t4, t5, lhs, rhs;

typedef struct {
    int s;
    long e;
    long w;
    int inf;
} side;

static int mk(cft_mp *x, int sign, long e, const mpz_t m, spec s)
{
    memset(x, 0, sizeof *x);
    x->sign = sign;
    x->zero = 0;
    x->exp = e;
    if (bn_from_z(&x->m, m))
        return 0;
    return put_err(x, s);
}

static void load(const cft_mp *x, mpz_t m, mpz_t E, side *d)
{
    z_from_bn(m, &x->m);
    d->s = x->sign;
    d->e = x->exp;
    d->w = z_bitlen(m);
    get_err(E, &d->inf, x);
}

static void load_value(const cft_mp *x, mpz_t m, side *d)
{
    z_from_bn(m, &x->m);
    d->s = x->sign;
    d->e = x->exp;
    d->w = z_bitlen(m);
    d->inf = 0;
}

static void show(char *buf, size_t n, const cft_mp *x)
{
    mpz_t m, E;
    int inf;
    mpz_init(m);
    mpz_init(E);
    z_from_bn(m, &x->m);
    get_err(E, &inf, x);
    if (x->zero)
        snprintf(buf, n, "0");
    else if (inf)
        gmp_snprintf(buf, n, "%s0x%Zx*2^%ld (w %ld) count inf",
                     x->sign ? "-" : "", m, x->exp, z_bitlen(m));
    else
        gmp_snprintf(buf, n, "%s0x%Zx*2^%ld (w %ld) count %Zd",
                     x->sign ? "-" : "", m, x->exp, z_bitlen(m), E);
    mpz_clear(m);
    mpz_clear(E);
}

/* ---- the verdicts ------------------------------------------------------ *
 *
 * Each returns 1 when the result r, carrying the count er (or infinity),
 * encloses the true result for every true operand in the operands'
 * enclosures, and 0 when it does not. Every quantity is scaled to an
 * integer by one power of two and compared exactly.
 */

static int ok_add(const cft_mp *a, const cft_mp *b, const cft_mp *r,
                  const mpz_t er, int rinf)
{
    side A, B, R;
    long emin, P;
    load(a, ma, Ea, &A);
    load(b, mb, Eb, &B);
    if (rinf)
        return 1;
    if (A.inf || B.inf)
        return 0;
    if (r->zero) {             /* only an exact zero from exact operands */
        if (mpz_sgn(Ea) || mpz_sgn(Eb))
            return 0;
        emin = lmin(A.e, B.e);
        zterm(t1, A.s, ma, A.e - emin);
        zterm(t2, B.s, mb, B.e - emin);
        mpz_add(t1, t1, t2);
        return mpz_sgn(t1) == 0;
    }
    load_value(r, mr, &R);
    emin = lmin(lmin(A.e, B.e), R.e);
    P = A.w + B.w + R.w;
    zterm(t1, A.s, ma, A.e - emin + P);
    zterm(t2, B.s, mb, B.e - emin + P);
    zterm(t3, R.s, mr, R.e - emin + P);
    mpz_add(t1, t1, t2);
    mpz_sub(t1, t1, t3);
    mpz_abs(lhs, t1);
    mpz_mul(t2, Ea, ma);
    mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(A.e - emin + B.w + R.w));
    mpz_add(lhs, lhs, t2);
    mpz_mul(t2, Eb, mb);
    mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(B.e - emin + A.w + R.w));
    mpz_add(lhs, lhs, t2);
    mpz_mul(rhs, er, mr);
    mpz_mul_2exp(rhs, rhs, (mp_bitcnt_t)(R.e - emin + A.w + B.w));
    return mpz_cmp(lhs, rhs) <= 0;
}

static int ok_mul(const cft_mp *a, const cft_mp *b, const cft_mp *r,
                  const mpz_t er, int rinf)
{
    side A, B, R;
    long emin;
    int sa, sb;
    load(a, ma, Ea, &A);
    load(b, mb, Eb, &B);
    if (rinf)
        return 1;
    if (A.inf || B.inf || r->zero)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(A.e + B.e, R.e);
    zterm(t3, R.s, mr, R.e - emin + A.w + B.w + R.w);
    mpz_mul(rhs, er, mr);
    mpz_mul_2exp(rhs, rhs, (mp_bitcnt_t)(R.e - emin + A.w + B.w));
    mpz_mul(t4, ma, mb);
    zterm(t4, A.s ^ B.s, t4, A.e + B.e - emin + R.w);
    for (sa = -1; sa <= 1; sa += 2)
        for (sb = -1; sb <= 1; sb += 2) {
            one_pm(t1, A.w, sa, Ea);
            one_pm(t2, B.w, sb, Eb);
            mpz_mul(t5, t4, t1);
            mpz_mul(t5, t5, t2);
            mpz_sub(t5, t5, t3);
            mpz_abs(t5, t5);
            if (mpz_cmp(t5, rhs) > 0)
                return 0;
        }
    return 1;
}

/* |a(1 + sa ea) - r b (1 + sb eb)| <= er |r| |b| (1 + sb eb): the corner
 * inequality multiplied through by |b|(1 + sb eb) > 0, which needs
 * eb < 1 - past it no finite bound exists and only infinity passes. */
static int ok_div(const cft_mp *a, const cft_mp *b, const cft_mp *r,
                  const mpz_t er, int rinf)
{
    side A, B, R;
    long emin;
    int sa, sb;
    load(a, ma, Ea, &A);
    load(b, mb, Eb, &B);
    if (rinf)
        return 1;
    if (A.inf || B.inf || r->zero)
        return 0;
    mpz_set_ui(t1, 1);
    mpz_mul_2exp(t1, t1, (mp_bitcnt_t)B.w);
    if (mpz_cmp(Eb, t1) >= 0)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(A.e, R.e + B.e);
    for (sa = -1; sa <= 1; sa += 2)
        for (sb = -1; sb <= 1; sb += 2) {
            one_pm(t1, A.w, sa, Ea);
            one_pm(t2, B.w, sb, Eb);
            mpz_mul(t3, ma, t1);
            zterm(t3, A.s, t3, A.e - emin + B.w + R.w);
            mpz_mul(t4, mr, mb);
            mpz_mul(t4, t4, t2);
            mpz_mul_2exp(t5, t4, (mp_bitcnt_t)(R.e + B.e - emin + A.w));
            zterm(t4, R.s ^ B.s, t4, R.e + B.e - emin + A.w + R.w);
            mpz_sub(t3, t3, t4);
            mpz_abs(lhs, t3);
            mpz_mul(rhs, er, t5);
            if (mpz_cmp(lhs, rhs) > 0)
                return 0;
        }
    return 1;
}

static int ok_mul_ui(const cft_mp *a, uint32_t u, const cft_mp *r,
                     const mpz_t er, int rinf)
{
    side A, R;
    long emin;
    int sa;
    load(a, ma, Ea, &A);
    if (rinf)
        return 1;
    if (A.inf || r->zero)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(A.e, R.e);
    zterm(t3, R.s, mr, R.e - emin + A.w + R.w);
    mpz_mul(rhs, er, mr);
    mpz_mul_2exp(rhs, rhs, (mp_bitcnt_t)(R.e - emin + A.w));
    mpz_mul_ui(t4, ma, (unsigned long)u);
    zterm(t4, A.s, t4, A.e - emin + R.w);
    for (sa = -1; sa <= 1; sa += 2) {
        one_pm(t1, A.w, sa, Ea);
        mpz_mul(t5, t4, t1);
        mpz_sub(t5, t5, t3);
        mpz_abs(t5, t5);
        if (mpz_cmp(t5, rhs) > 0)
            return 0;
    }
    return 1;
}

/* |a(1 + sa ea) - r u| <= er |r| u */
static int ok_div_ui(const cft_mp *a, uint32_t u, const cft_mp *r,
                     const mpz_t er, int rinf)
{
    side A, R;
    long emin;
    int sa;
    load(a, ma, Ea, &A);
    if (rinf)
        return 1;
    if (A.inf || r->zero)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(A.e, R.e);
    mpz_mul_ui(t3, mr, (unsigned long)u);
    mpz_mul_2exp(rhs, t3, (mp_bitcnt_t)(R.e - emin + A.w));
    mpz_mul(rhs, rhs, er);
    zterm(t3, R.s, t3, R.e - emin + A.w + R.w);
    for (sa = -1; sa <= 1; sa += 2) {
        one_pm(t1, A.w, sa, Ea);
        mpz_mul(t4, ma, t1);
        zterm(t4, A.s, t4, A.e - emin + R.w);
        mpz_sub(t4, t4, t3);
        mpz_abs(t4, t4);
        if (mpz_cmp(t4, rhs) > 0)
            return 0;
    }
    return 1;
}

/* sqrt(a(1 + ea)) <= r(1 + er) and, when er < 1,
 * r(1 - er) <= sqrt(a(1 - min(ea, 1))): squared, both sides >= 0. */
static int ok_sqrt(const cft_mp *a, const cft_mp *r, const mpz_t er,
                   int rinf)
{
    side A, R;
    long emin;
    load(a, ma, Ea, &A);
    if (rinf)
        return 1;
    if (A.inf || r->zero)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(A.e, 2 * R.e);
    one_pm(t1, A.w, 1, Ea);
    mpz_mul(t1, t1, ma);
    mpz_mul_2exp(t1, t1, (mp_bitcnt_t)(A.e - emin + 2 * R.w));
    one_pm(t2, R.w, 1, er);
    mpz_mul(t2, t2, t2);
    mpz_mul(t3, mr, mr);
    mpz_mul(t2, t2, t3);
    mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(2 * R.e - emin + A.w));
    if (mpz_cmp(t1, t2) > 0)
        return 0;
    mpz_set_ui(t4, 1);
    mpz_mul_2exp(t4, t4, (mp_bitcnt_t)R.w);
    if (mpz_cmp(er, t4) < 0) {
        mpz_set_ui(t1, 1);
        mpz_mul_2exp(t1, t1, (mp_bitcnt_t)A.w);
        if (mpz_cmp(Ea, t1) < 0)
            mpz_sub(t1, t1, Ea);
        else
            mpz_set_ui(t1, 0);
        mpz_mul(t1, t1, ma);
        mpz_mul_2exp(t1, t1, (mp_bitcnt_t)(A.e - emin + 2 * R.w));
        mpz_sub(t2, t4, er);
        mpz_mul(t2, t2, t2);
        mpz_mul(t2, t2, t3);
        mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(2 * R.e - emin + A.w));
        if (mpz_cmp(t2, t1) > 0)
            return 0;
    }
    return 1;
}

/* An exact s * m * 2^e, normalised to r. */
static int ok_set(int s, const mpz_t m, long e, const cft_mp *r,
                  const mpz_t er, int rinf)
{
    side R;
    long emin;
    if (rinf)
        return 1;
    if (r->zero)
        return 0;
    load_value(r, mr, &R);
    emin = lmin(e, R.e);
    zterm(t1, s, m, e - emin + R.w);
    zterm(t2, R.s, mr, R.e - emin + R.w);
    mpz_sub(t1, t1, t2);
    mpz_abs(lhs, t1);
    mpz_mul(rhs, er, mr);
    mpz_mul_2exp(rhs, rhs, (mp_bitcnt_t)(R.e - emin));
    return mpz_cmp(lhs, rhs) <= 0;
}

/* cft_mp_cmp_int's +1 must mean every value in v's true enclosure is
 * above t, and -1 every one below it. */
static int ok_cmp(const cft_mp *v, int64_t t, int got)
{
    side V;
    long emin;
    if (got == 0)
        return 1;
    load(v, ma, Ea, &V);
    if (V.inf)
        return 0;
    emin = lmin(V.e, 0);
    zterm(t1, V.s, ma, V.e - emin + V.w);          /* v */
    mpz_mul(t2, Ea, ma);
    mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(V.e - emin)); /* e|v| */
    z_set_i64(t3, t);
    mpz_mul_2exp(t3, t3, (mp_bitcnt_t)(V.w - emin)); /* t */
    if (got > 0) {
        mpz_sub(t4, t1, t2);
        return mpz_cmp(t4, t3) > 0;
    }
    mpz_add(t4, t1, t2);
    return mpz_cmp(t4, t3) < 0;
}

/* ---- the old rules, as at aeb3f5e -------------------------------------- *
 *
 * Transcribed from the old mpfloat.c for W-bit operands whose counts are
 * 2^40 or less: its saturating sum, its scale (rounding up since the
 * lead's fix of that day), and each rule. Base mode holds this against
 * the old library itself.
 */

static uint64_t o_add(uint64_t a, uint64_t b)
{
    uint64_t s = a + b;
    return (s < a || s > OLD_MAX) ? OLD_MAX : s;
}

static uint64_t o_scale(uint64_t a, long k)
{
    if (a == 0)
        return 0;
    if (k < 0) {
        long s = -k;
        uint64_t q;
        if (s > 63)
            return 1;
        q = a >> s;
        if (a & (((uint64_t)1 << s) - 1))
            q++;
        return q;
    }
    if (k >= 63 || a > (OLD_MAX >> k))
        return OLD_MAX;
    return a << k;
}

static uint64_t o_norm(uint64_t x, int truncates)
{
    return truncates ? o_add(x, 2) : x;
}

/* 0 with the count, or 1 where the old code refused. */
static int old_add(uint64_t *out, const cft_mp *a, uint64_t xa,
                   const cft_mp *b, uint64_t xb, int W)
{
    long e0;
    int c;
    if (a->exp - b->exp > W + 2) {
        *out = o_add(xa, 2);
        return 0;
    }
    if (b->exp - a->exp > W + 2) {
        *out = o_add(xb, 2);
        return 0;
    }
    e0 = lmin(a->exp, b->exp);
    z_from_bn(t1, &a->m);
    mpz_mul_2exp(t1, t1, (mp_bitcnt_t)(a->exp - e0));
    z_from_bn(t2, &b->m);
    mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(b->exp - e0));
    if (a->sign == b->sign) {
        mpz_add(t3, t1, t2);
        *out = o_norm(o_add(xa, xb), z_bitlen(t3) > W);
        return 0;
    }
    c = mpz_cmp(t1, t2);
    if (c == 0) {
        if (xa == 0 && xb == 0) {
            *out = 0;
            return 0;
        }
        return 1;
    }
    mpz_sub(t3, t1, t2);
    mpz_abs(t3, t3);
    *out = o_norm(o_add(o_scale(xa, z_bitlen(t1) - z_bitlen(t3) + 1),
                        o_scale(xb, z_bitlen(t2) - z_bitlen(t3) + 1)),
                  z_bitlen(t3) > W);
    return 0;
}

static uint64_t old_mul(const cft_mp *a, uint64_t xa, const cft_mp *b,
                        uint64_t xb, int W)
{
    z_from_bn(t1, &a->m);
    z_from_bn(t2, &b->m);
    mpz_mul(t1, t1, t2);
    return o_norm(o_add(o_add(xa, xb), 1), z_bitlen(t1) > W);
}

static uint64_t old_mul_ui(const cft_mp *a, uint64_t xa, uint32_t u, int W)
{
    z_from_bn(t1, &a->m);
    mpz_mul_ui(t1, t1, (unsigned long)u);
    return o_norm(xa, z_bitlen(t1) > W);
}

static uint64_t old_div(uint64_t xa, uint64_t xb)
{
    return o_norm(o_add(o_add(xa, xb), 1), 1);
}

static uint64_t old_sqrt(const cft_mp *a, uint64_t xa, int W)
{
    long L, k, e;
    z_from_bn(t1, &a->m);
    L = z_bitlen(t1);
    k = 2 * (long)W - L;
    e = a->exp - k;
    if (e & 1)
        k--;
    mpz_mul_2exp(t1, t1, (mp_bitcnt_t)k);
    mpz_sqrtrem(t2, t3, t1);
    return o_add((xa + 1) / 2, mpz_sgn(t3) ? 2 : 0);
}

/* ---- one comparison with the old rules ----------------------------------
 *
 * Er holds the library's count for r. In the default build: the count
 * must be at least the old one, and the old one is put through the same
 * verdict, where it is expected to fail somewhere. In base mode the
 * library IS the old one, and the transcription must equal it. */
static void versus_old(tally *T, uint64_t old, int rinf, int held_old)
{
    T->cmp++;
    z_set_u64(Eo, old);
#ifdef MP_ERR_CHECK_BASE
    if (!held_old)
        T->ctl_fail++;             /* equal to the library's own verdict */
    if (rinf || mpz_cmp(Er, Eo) != 0) {
        T->model++;
        fail(T, "the transcription of the old rules",
             "old rule %llu, library %s", (unsigned long long)old,
             rinf ? "inf" : "different");
    }
#else
    if (!rinf && mpz_cmp(Er, Eo) < 0) {
        /* Through fail(), so its 40-line cap holds: printed for every
         * operand, a failing run wrote 34 to 58 MB of log (verifier-W5's
         * plants, 2026-09-30). The tally keeps the whole count. */
        char s1[64];
        T->below_old++;
        gmp_snprintf(s1, sizeof s1, "%Zd", Er);
        fail(T, "below the old rule's count", "%s < %llu", s1,
             (unsigned long long)old);
    }
    if (!held_old)
        T->ctl_fail++;
#endif
}

/* ---- the operations, one case each -------------------------------------- */

static tally T_add = { .name = "add" }, T_sub = { .name = "sub" },
             T_mul = { .name = "mul" }, T_div = { .name = "div" },
             T_mul_ui = { .name = "mul_ui" }, T_div_ui = { .name = "div_ui" },
             T_sqrt = { .name = "sqrt" }, T_set = { .name = "set_bn" },
             T_cmp = { .name = "cmp_int" },
             T_arith = { .name = "arith" };

static void case_add(int W, int sa, long ea, const mpz_t xa, spec ca,
                     int sb, long eb, const mpz_t xb, spec cb, int sub)
{
    tally *T = sub ? &T_sub : &T_add;
    cft_mp a, b, r, nb;
    int rc, rinf, same_w;
    if (!mk(&a, sa, ea, xa, ca) || !mk(&b, sb, eb, xb, cb)) {
        T->unheld++;
        return;
    }
    if (sub) {
        rc = cft_mp_sub(&r, &a, &b, W);
        nb = b;
        nb.sign ^= 1;                  /* judged as a + (-b) */
    } else {
        rc = cft_mp_add(&r, &a, &b, W);
        nb = b;
    }
    if (rc) {
        /* The rule's one refusal: two approximations that cancel
         * exactly. Anything else is not a refusal the rule makes. */
        long e0 = lmin(a.exp, b.exp);
        z_from_bn(t1, &a.m);
        mpz_mul_2exp(t1, t1, (mp_bitcnt_t)(a.exp - e0));
        z_from_bn(t2, &b.m);
        mpz_mul_2exp(t2, t2, (mp_bitcnt_t)(b.exp - e0));
        get_err(Ea, &rinf, &a);
        get_err(Eb, &rinf, &b);
        if (a.sign == nb.sign || mpz_cmp(t1, t2) != 0 ||
            (mpz_sgn(Ea) == 0 && mpz_sgn(Eb) == 0))
            fail(T, "refused", "W %d", W);
        T->refused++;
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    if (!ok_add(&a, &nb, &r, Er, rinf)) {
        char s1[400], s2[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &a);
        show(s2, sizeof s2, &nb);
        show(s3, sizeof s3, &r);
        fail(T, "over its bound", "W %d: %s + %s -> %s", W, s1, s2, s3);
    }
    same_w = z_bitlen(xa) == W && z_bitlen(xb) == W;
    if (same_w && spec_small(ca) && spec_small(cb)) {
        uint64_t old;
        if (old_add(&old, &a, ca.c, &nb, cb.c, W) == 0) {
            z_set_u64(Eo, old);
            versus_old(T, old, rinf, ok_add(&a, &nb, &r, Eo, 0));
        }
    }
}

static void case_mul(int W, int sa, const mpz_t xa, spec ca, int sb,
                     const mpz_t xb, spec cb, long ea, long eb)
{
    tally *T = &T_mul;
    cft_mp a, b, r;
    int rinf;
    if (!mk(&a, sa, ea, xa, ca) || !mk(&b, sb, eb, xb, cb)) {
        T->unheld++;
        return;
    }
    if (cft_mp_mul(&r, &a, &b, W)) {
        fail(T, "refused", "W %d", W);
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    if (!ok_mul(&a, &b, &r, Er, rinf)) {
        char s1[400], s2[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &a);
        show(s2, sizeof s2, &b);
        show(s3, sizeof s3, &r);
        fail(T, "over its bound", "W %d: %s * %s -> %s", W, s1, s2, s3);
    }
    if (z_bitlen(xa) == W && z_bitlen(xb) == W && spec_small(ca) &&
        spec_small(cb)) {
        uint64_t old = old_mul(&a, ca.c, &b, cb.c, W);
        z_set_u64(Eo, old);
        versus_old(T, old, rinf, ok_mul(&a, &b, &r, Eo, 0));
    }
}

static void case_div(int W, int sa, const mpz_t xa, spec ca, int sb,
                     const mpz_t xb, spec cb, long ea, long eb)
{
    tally *T = &T_div;
    cft_mp a, b, r;
    int rinf;
    if (!mk(&a, sa, ea, xa, ca) || !mk(&b, sb, eb, xb, cb)) {
        T->unheld++;
        return;
    }
    if (cft_mp_div(&r, &a, &b, W)) {
        fail(T, "refused", "W %d", W);
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    if (!ok_div(&a, &b, &r, Er, rinf)) {
        char s1[400], s2[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &a);
        show(s2, sizeof s2, &b);
        show(s3, sizeof s3, &r);
        fail(T, "over its bound", "W %d: %s / %s -> %s", W, s1, s2, s3);
    }
    if (z_bitlen(xa) == W && z_bitlen(xb) == W && spec_small(ca) &&
        spec_small(cb)) {
        uint64_t old = old_div(ca.c, cb.c);
        z_set_u64(Eo, old);
        versus_old(T, old, rinf, ok_div(&a, &b, &r, Eo, 0));
    }
}

static void case_ui(int W, int div, int sa, const mpz_t xa, spec ca,
                    uint32_t u, long ea)
{
    tally *T = div ? &T_div_ui : &T_mul_ui;
    cft_mp a, r;
    int rinf, ok;
    if (!mk(&a, sa, ea, xa, ca)) {
        T->unheld++;
        return;
    }
    if (div ? cft_mp_div_ui(&r, &a, u, W) : cft_mp_mul_ui(&r, &a, u, W)) {
        fail(T, "refused", "W %d", W);
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    ok = div ? ok_div_ui(&a, u, &r, Er, rinf) : ok_mul_ui(&a, u, &r, Er, rinf);
    if (!ok) {
        char s1[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &a);
        show(s3, sizeof s3, &r);
        fail(T, "over its bound", "W %d: %s %s %lu -> %s", W, s1,
             div ? "/" : "*", (unsigned long)u, s3);
    }
    if (z_bitlen(xa) == W && spec_small(ca)) {
        uint64_t old = div ? o_norm(ca.c, 1) : old_mul_ui(&a, ca.c, u, W);
        z_set_u64(Eo, old);
        versus_old(T, old, rinf,
                   div ? ok_div_ui(&a, u, &r, Eo, 0)
                       : ok_mul_ui(&a, u, &r, Eo, 0));
    }
}

static void case_sqrt(int W, const mpz_t xa, spec ca, long ea)
{
    tally *T = &T_sqrt;
    cft_mp a, r;
    int rinf;
    if (!mk(&a, 0, ea, xa, ca)) {
        T->unheld++;
        return;
    }
    if (cft_mp_sqrt(&r, &a, W)) {
        fail(T, "refused", "W %d", W);
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    if (!ok_sqrt(&a, &r, Er, rinf)) {
        char s1[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &a);
        show(s3, sizeof s3, &r);
        fail(T, "over its bound", "W %d: sqrt %s -> %s", W, s1, s3);
    }
    if (z_bitlen(xa) == W && spec_small(ca)) {
        uint64_t old = old_sqrt(&a, ca.c, W);
        z_set_u64(Eo, old);
        versus_old(T, old, rinf, ok_sqrt(&a, &r, Eo, 0));
    }
}

static void case_set(int W, int s, const mpz_t m, long e)
{
    tally *T = &T_set;
    cft_mp r;
    cft_bn bm;
    int rinf;
    if (bn_from_z(&bm, m)) {
        T->unheld++;
        return;
    }
    if (cft_mp_set_bn(&r, W, s, &bm, e)) {
        fail(T, "refused", "W %d", W);
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    if (!ok_set(s, m, e, &r, Er, rinf)) {
        char s3[400];
        T->over++;
        show(s3, sizeof s3, &r);
        gmp_snprintf(s3 + strlen(s3), sizeof s3 - strlen(s3), " from 0x%Zx",
                     m);
        fail(T, "over its bound", "W %d: %s", W, s3);
    }
    {
        uint64_t old = z_bitlen(m) > W ? 2 : 0;
        z_set_u64(Eo, old);
        versus_old(T, old, rinf, ok_set(s, m, e, &r, Eo, 0));
    }
}

static void case_cmp(int W, int s, const mpz_t xa, spec ca, long ea,
                     int64_t t)
{
    tally *T = &T_cmp;
    cft_mp v;
    int got;
    (void)W;
    if (!mk(&v, s, ea, xa, ca)) {
        T->unheld++;
        return;
    }
    got = cft_mp_cmp_int(&v, t);
    T->checked++;
    if (got)
        T->decided++;
    if (!ok_cmp(&v, t, got)) {
        char s1[400];
        T->over++;
        show(s1, sizeof s1, &v);
        fail(T, "a decision the enclosure does not support",
             "%s against %lld: %d", s1, (long long)t, got);
    }
    /* The control: the answer the stored value alone gives, ignoring
     * its count, must fail the same verdict wherever the count
     * matters. */
    {
        side V;
        long emin;
        int naive;
        load(&v, ma, Ea, &V);
        emin = lmin(V.e, 0);
        zterm(t1, V.s, ma, V.e - emin + V.w);
        z_set_i64(t3, t);
        mpz_mul_2exp(t3, t3, (mp_bitcnt_t)(V.w - emin));
        naive = mpz_cmp(t1, t3);
        naive = naive > 0 ? 1 : (naive < 0 ? -1 : 0);
        if (naive) {
            T->cmp++;
            if (!ok_cmp(&v, t, naive))
                T->ctl_fail++;
        }
    }
}

/* ---- the count's own arithmetic ------------------------------------------ */

#ifndef MP_ERR_CHECK_BASE
static void spec_z(mpz_t z, spec s)
{
    z_set_u64(z, s.c);
    mpz_mul_2exp(z, z, (mp_bitcnt_t)s.k);
}

static int canonical(cft_mp_err x)
{
    const uint64_t top = (uint64_t)1 << 63, high = (uint64_t)1 << 62;
    if (cft_mp_err_is_inf(x))
        return 1;
    if (x.k < 0 || x.c >= top)
        return 0;
    return x.k == 0 || x.c >= high;
}

static void err_z(mpz_t z, cft_mp_err x)
{
    z_set_u64(z, x.c);
    mpz_mul_2exp(z, z, (mp_bitcnt_t)x.k);
}

static void arith_case(void)
{
    tally *T = &T_arith;
    spec sa = rnd_spec(64), sb = rnd_spec(64);
    cft_mp_err a, b, s, u;
    long j;
    int lt;
    if (sa.inf || sb.inf) {
        a = sa.inf ? cft_mp_err_inf() : cft_mp_err_u64(sa.c);
        s = cft_mp_err_add(a, cft_mp_err_u64(5));
        u = cft_mp_err_up(a, -(long)below(200));
        T->checked++;
        if (sa.inf && (!cft_mp_err_is_inf(s) || !cft_mp_err_is_inf(u) ||
                       cft_mp_err_lt_pow2(a, 1000)))
            fail(T, "infinity", "not kept");
        return;
    }
    a = cft_mp_err_up(cft_mp_err_u64(sa.c), sa.k);
    b = cft_mp_err_up(cft_mp_err_u64(sb.c), sb.k);
    T->checked++;
    /* exact below 2^63 and exact scaling up: the count is c * 2^k */
    spec_z(t1, sa);
    err_z(t2, a);
    if (!canonical(a) || mpz_cmp(t1, t2) != 0)
        fail(T, "u64 then up", "c %llu k %ld", (unsigned long long)sa.c,
             sa.k);
    /* the sum: at or above, and within 2^-61 of it plus one unit */
    spec_z(t3, sb);
    mpz_add(t1, t1, t3);
    s = cft_mp_err_add(a, b);
    err_z(t2, s);
    mpz_fdiv_q_2exp(t4, t1, 61);
    mpz_add(t4, t4, t1);
    mpz_add_ui(t4, t4, 1);
    if (!canonical(s) || mpz_cmp(t2, t1) < 0 || mpz_cmp(t2, t4) > 0)
        fail(T, "add", "c %llu k %ld + c %llu k %ld",
             (unsigned long long)sa.c, sa.k, (unsigned long long)sb.c, sb.k);
    /* up(a, j) is exactly ceil(a * 2^j) */
    j = (long)below(601) - 300;
    u = cft_mp_err_up(a, j);
    spec_z(t1, sa);
    if (j >= 0) {
        mpz_mul_2exp(t1, t1, (mp_bitcnt_t)j);
    } else {
        mpz_cdiv_q_2exp(t1, t1, (mp_bitcnt_t)(-j));
    }
    err_z(t2, u);
    if (!canonical(u) || mpz_cmp(t1, t2) != 0)
        fail(T, "up", "c %llu k %ld by %ld", (unsigned long long)sa.c, sa.k,
             j);
    /* lt_pow2 is exact on a canonical count */
    j = (long)below(260) - 5;
    lt = cft_mp_err_lt_pow2(a, j);
    spec_z(t1, sa);
    mpz_set_ui(t2, 1);
    if (j >= 0)
        mpz_mul_2exp(t2, t2, (mp_bitcnt_t)j);
    if ((j >= 0 ? mpz_cmp(t1, t2) < 0 : mpz_sgn(t1) == 0) != lt)
        fail(T, "lt_pow2", "c %llu k %ld against 2^%ld",
             (unsigned long long)sa.c, sa.k, j);
    /* u64 past 2^63: at or above, within 2^-62 */
    {
        uint64_t n = ((uint64_t)1 << 63) | (next() >> 1);
        cft_mp_err x = cft_mp_err_u64(n);
        z_set_u64(t1, n);
        err_z(t2, x);
        mpz_fdiv_q_2exp(t3, t1, 62);
        mpz_add(t3, t3, t1);
        mpz_add_ui(t3, t3, 1);
        if (!canonical(x) || mpz_cmp(t2, t1) < 0 || mpz_cmp(t2, t3) > 0)
            fail(T, "u64 past 2^63", "%llu", (unsigned long long)n);
    }
    /* the width conversion: exactly scaled up when narrower, kept when
     * wider */
    {
        cft_mp v;
        int W = 8 + (int)below(900), wv = 2 + (int)below(1000);
        rnd_sig(t3, wv);
        if (!mk(&v, 0, 0, t3, sa))
            return;
        u = cft_mp_err_at(&v, W);
        spec_z(t1, sa);
        if (wv < W)
            mpz_mul_2exp(t1, t1, (mp_bitcnt_t)(W - wv));
        err_z(t2, u);
        if (!canonical(u) || mpz_cmp(t1, t2) != 0)
            fail(T, "err_at", "width %d read at %d", wv, W);
    }
}
#endif

/* ---- regressions ------------------------------------------------------------ *
 *
 * verifier-W4, 2026-09-30, measured through the old library at W = 88: a
 * clamp scaled down by a later cancellation came back as an
 * ordinary-looking count that was not a bound. a = 2^87 + 12345 with a
 * count of 1000, and b = 2^87 exact: r1 = a - b cancels 74 bits, so its
 * count is about 2^85 units, which the old count clamped at 2^40. c =
 * (2^87 + 7) * 2^-37 exact: r2 = c - r1 scales r1's count back down, and
 * the old code returned 34 where the worst true error is 2^46.97 units.
 * Checked here rule by rule, and end to end: the true values of a's
 * whole enclosure, carried through both subtractions exactly, must lie
 * in r2's enclosure.
 */

static tally T_reg = { .name = "W4 case" };

static void q_value(mpq_t q, const cft_mp *x)
{
    z_from_bn(t1, &x->m);
    mpq_set_z(q, t1);
    if (x->exp >= 0)
        mpq_mul_2exp(q, q, (mp_bitcnt_t)x->exp);
    else
        mpq_div_2exp(q, q, (mp_bitcnt_t)(-x->exp));
    if (x->sign)
        mpq_neg(q, q);
}

/* The relative bound e = count * 2^-width; 1 when infinite. */
static int q_eps(mpq_t q, const cft_mp *x)
{
    int inf;
    get_err(t2, &inf, x);
    z_from_bn(t1, &x->m);
    mpq_set_z(q, t2);
    mpq_div_2exp(q, q, (mp_bitcnt_t)z_bitlen(t1));
    return inf;
}

static double q_log2(const mpq_t q)
{
    double d = mpq_get_d(q);
    return d > 0 ? log2(d) : 0.0;
}

static void regression_w4(void)
{
    const int W = 88;
    tally *T = &T_reg;
    cft_mp a, b, c, r1, r2, nb, nr1;
    mpz_t m;
    mpq_t qa, qb, qc, qr, ea, er, qt, qd, qw, qmax;
    int rinf, s, held = 1;
    char s1[400], s2[400];

    mpz_init(m);
    mpq_init(qa); mpq_init(qb); mpq_init(qc); mpq_init(qr); mpq_init(ea);
    mpq_init(er); mpq_init(qt); mpq_init(qd); mpq_init(qw); mpq_init(qmax);
    mpz_set_ui(m, 1);
    mpz_mul_2exp(m, m, 87);
    mpz_add_ui(m, m, 12345);
    mk(&a, 0, 0, m, sp(1000, 0));
    mpz_sub_ui(m, m, 12345);
    mk(&b, 0, 0, m, sp(0, 0));
    mpz_add_ui(m, m, 7);
    mk(&c, 0, -37, m, sp(0, 0));
    if (cft_mp_sub(&r1, &a, &b, W) || cft_mp_sub(&r2, &c, &r1, W)) {
        fail(T, "refused", "W %d", W);
        goto out;
    }
    nb = b;
    nb.sign ^= 1;
    nr1 = r1;
    nr1.sign ^= 1;
    /* rule by rule */
    T->checked += 2;
    get_err(Er, &rinf, &r1);
    if (!ok_add(&a, &nb, &r1, Er, rinf)) {
        T->over++;
        show(s1, sizeof s1, &r1);
        fail(T, "r1 = a - b over its bound", "%s", s1);
    }
    get_err(Er, &rinf, &r2);
    if (!ok_add(&c, &nr1, &r2, Er, rinf)) {
        T->over++;
        show(s1, sizeof s1, &r2);
        fail(T, "r2 = c - r1 over its bound", "%s", s1);
    }
    /* end to end: T = c - A + b for A anywhere in a's enclosure */
    T->checked++;
    q_value(qa, &a);
    q_value(qb, &b);
    q_value(qc, &c);
    q_value(qr, &r2);
    q_eps(ea, &a);
    rinf = q_eps(er, &r2);
    mpq_set_ui(qmax, 0, 1);
    for (s = -1; s <= 1; s += 2) {
        mpq_set(qt, ea);
        if (s < 0)
            mpq_neg(qt, qt);
        mpq_set_ui(qd, 1, 1);
        mpq_add(qt, qt, qd);
        mpq_mul(qt, qt, qa);                 /* A */
        mpq_sub(qd, qc, qt);
        mpq_add(qd, qd, qb);                 /* the true c - (A - b) */
        mpq_sub(qd, qd, qr);
        mpq_abs(qd, qd);                     /* |true - r2| */
        if (mpq_cmp(qd, qmax) > 0)
            mpq_set(qmax, qd);
        mpq_abs(qw, qr);
        mpq_mul(qw, qw, er);                 /* er |r2| */
        if (!rinf && mpq_cmp(qd, qw) > 0)
            held = 0;
    }
    /* the worst true error, in r2's units of 2^-88 */
    mpq_abs(qw, qr);
    mpq_div(qmax, qmax, qw);
    mpq_mul_2exp(qmax, qmax, (mp_bitcnt_t)W);
    show(s1, sizeof s1, &r1);
    show(s2, sizeof s2, &r2);
    printf("  W4 case  r1 = %s\n           r2 = %s\n           r2's worst "
           "true error about 2^%.2f units: %s\n", s1, s2, q_log2(qmax),
           held ? "within its count" : "OVER its count");
    if (!held) {
        T->over++;
        fail(T, "end to end", "r2's count is not a bound on its true error");
    }
out:
    mpz_clear(m);
    mpq_clear(qa); mpq_clear(qb); mpq_clear(qc); mpq_clear(qr);
    mpq_clear(ea); mpq_clear(er); mpq_clear(qt); mpq_clear(qd);
    mpq_clear(qw); mpq_clear(qmax);
}

#ifndef MP_ERR_CHECK_BASE
/* ---- the constants and the logarithm's conversion, against MPFR -------- *
 *
 * The header's two claims outside mpfloat.c's rules. Each true value is
 * bracketed by MPFR's directed roundings, [lo, hi], and the verdict is
 * that the enclosure r(1 -+ E 2^-w) holds the whole bracket: its low end
 * at or below lo and its high end at or above hi, compared exactly.
 */

static tally T_const = { .name = "const" }, T_log = { .name = "log" };
static unsigned long long const_ctl;           /* a count of 1 fails */
static unsigned long long log_ctl, log_ctl_of; /* the argument's error left out */
static unsigned long long log_inf, log_inf_early;

static mpz_t b1, b2, b3, g1, g2, g3;
static mpfr_t fr_a, fr_b, fr_v, fr_lo, fr_hi, fr_t, fr_y;

/* rop = N * 2^k, exactly: the precision is N's own bit length. */
static void fr_exact(mpfr_t rop, const mpz_t N, long k)
{
    long n = z_bitlen(N);
    mpfr_set_prec(rop, (mpfr_prec_t)(n < 2 ? 2 : n));
    mpfr_set_z_2exp(rop, N, (mpfr_exp_t)k, MPFR_RNDN);
}

/* r's enclosure holds [lo, hi]. Infinity holds everything; an exact
 * zero holds nothing a nonzero bracket can be. */
static int ok_bracket(const cft_mp *r, const mpz_t E, int rinf,
                      mpfr_t lo, mpfr_t hi)
{
    long w;
    if (rinf)
        return 1;
    if (r->zero)
        return 0;
    z_from_bn(b1, &r->m);
    w = z_bitlen(b1);
    mpz_mul(b2, E, b1);                        /* E m */
    zterm(b1, r->sign, b1, w);                 /* (-1)^s m 2^w */
    mpz_sub(b3, b1, b2);                       /* the low end, and */
    mpz_add(b2, b1, b2);                       /* the high, in 2^(e-w) */
    fr_exact(fr_a, b3, r->exp - w);
    fr_exact(fr_b, b2, r->exp - w);
    return mpfr_cmp(fr_a, lo) <= 0 && mpfr_cmp(hi, fr_b) <= 0;
}

/* Every constant at every width a caller can ask for. 1,400 bits put
 * the bracket far inside the smallest margin a correct count leaves:
 * the true error of a truncation of the stored 1088-bit value is under
 * two units at every W below 1088, against a count of four. */
#define CONST_PREC 1400

static void const_leg(void)
{
    static const char *nm[6] = { "ln2", "log2e", "ln10", "log10e", "pi",
                                 "1/pi" };
    mpfr_t lo[6], hi[6], ten;
    int c, W, rinf;
    for (c = 0; c < 6; c++) {
        mpfr_init2(lo[c], CONST_PREC);
        mpfr_init2(hi[c], CONST_PREC);
    }
    mpfr_init2(ten, 8);
    mpfr_set_ui(ten, 10, MPFR_RNDN);
    mpfr_const_log2(lo[CFT_MP_C_LN2], MPFR_RNDD);
    mpfr_const_log2(hi[CFT_MP_C_LN2], MPFR_RNDU);
    mpfr_log(lo[CFT_MP_C_LN10], ten, MPFR_RNDD);
    mpfr_log(hi[CFT_MP_C_LN10], ten, MPFR_RNDU);
    mpfr_const_pi(lo[CFT_MP_C_PI], MPFR_RNDD);
    mpfr_const_pi(hi[CFT_MP_C_PI], MPFR_RNDU);
    /* the reciprocals: 1/x falls as x rises */
    mpfr_ui_div(lo[CFT_MP_C_LOG2E], 1, hi[CFT_MP_C_LN2], MPFR_RNDD);
    mpfr_ui_div(hi[CFT_MP_C_LOG2E], 1, lo[CFT_MP_C_LN2], MPFR_RNDU);
    mpfr_ui_div(lo[CFT_MP_C_LOG10E], 1, hi[CFT_MP_C_LN10], MPFR_RNDD);
    mpfr_ui_div(hi[CFT_MP_C_LOG10E], 1, lo[CFT_MP_C_LN10], MPFR_RNDU);
    mpfr_ui_div(lo[CFT_MP_C_INVPI], 1, hi[CFT_MP_C_PI], MPFR_RNDD);
    mpfr_ui_div(hi[CFT_MP_C_INVPI], 1, lo[CFT_MP_C_PI], MPFR_RNDU);
    for (c = 0; c < 6; c++)
        for (W = 2; W <= CFT_MP_PREC_MAX; W++) {
            cft_mp r;
            if (cft_mp_const(&r, (cft_mp_constant)c, W)) {
                fail(&T_const, "refused", "%s at W %d", nm[c], W);
                continue;
            }
            T_const.checked++;
            get_err(Er, &rinf, &r);
            if (!ok_bracket(&r, Er, rinf, lo[c], hi[c])) {
                char s1[400];
                T_const.over++;
                show(s1, sizeof s1, &r);
                fail(&T_const, "the true constant outside its enclosure",
                     "%s at W %d: %s", nm[c], W, s1);
            }
            /* the control: one unit, where the truncation can cost two */
            mpz_set_ui(Eo, 1);
            if (!ok_bracket(&r, Eo, 0, lo[c], hi[c]))
                const_ctl++;
        }
    for (c = 0; c < 6; c++) {
        mpfr_clear(lo[c]);
        mpfr_clear(hi[c]);
    }
    mpfr_clear(ten);
}

/* One argument v = m * 2^e, of m's width wv, with the count cv, at the
 * working width W; ctl asks for the control on it. Nothing here draws a
 * random number, so the sample is the same whatever the library
 * answers. */
static void log_case(int W, long wv, const mpz_t m, long e, spec cv,
                     int ctl)
{
    tally *T = &T_log;
    cft_mp v, r, v0, r0;
    int rinf, vinf, inf0;
    long P;
    if (!mk(&v, 0, e, m, cv)) {
        T->unheld++;
        return;
    }
    if (cft_tr_probe_log_of_mp(&r, &v, W)) {
        /* Its refusals: the argument exactly 1, or its logarithm below
         * 2^-32 (E0 < -32, where the bound is not converted) - the
         * argument as mp_log_exact takes it, truncated to W bits when
         * it is wider. Anything else is not a refusal the conversion
         * makes. */
        if (wv > W) {
            mpz_fdiv_q_2exp(g1, m, (mp_bitcnt_t)(wv - W));
            fr_exact(fr_v, g1, e + (wv - W));
        } else {
            fr_exact(fr_v, m, e);
        }
        if (mpfr_cmp_ui(fr_v, 1) != 0) {
            mpfr_set_prec(fr_t, 64);
            mpfr_log(fr_t, fr_v, MPFR_RNDN);
            mpfr_set_prec(fr_y, 2);
            mpfr_set_ui_2exp(fr_y, 1, -31, MPFR_RNDN);
            if (mpfr_cmpabs(fr_t, fr_y) >= 0)
                fail(T, "refused", "W %d, v of width %ld, 2^%ld", W, wv,
                     e + wv);
        }
        T->refused++;
        return;
    }
    T->checked++;
    get_err(Er, &rinf, &r);
    get_err(Ea, &vinf, &v);                    /* v's count, units 2^-wv */
    if (rinf) {
        log_inf++;
        /* infinity is a bound; the rule makes it from a count of 2^(W-1)
         * or more read at W, and one sooner would cost a decision */
        if (!vinf) {
            mpz_set(g1, Ea);
            if (wv < W)
                mpz_mul_2exp(g1, g1, (mp_bitcnt_t)(W - wv));
            if (z_bitlen(g1) < W)
                log_inf_early++;
        }
        return;
    }
    if (vinf) {
        T->over++;
        fail(T, "a finite count from an argument with none",
             "W %d, v of width %ld", W, wv);
        return;
    }
    /* V's ends, m (2^wv -+ C) 2^(e - wv) */
    mpz_set_ui(g1, 1);
    mpz_mul_2exp(g1, g1, (mp_bitcnt_t)wv);
    mpz_sub(g2, g1, Ea);
    if (mpz_sgn(g2) <= 0) {
        char s1[400];
        T->over++;
        show(s1, sizeof s1, &r);
        fail(T, "a finite count where the argument's enclosure reaches zero",
             "W %d, v of width %ld, 2^%ld -> %s", W, wv, e + wv, s1);
        return;
    }
    mpz_mul(g2, g2, m);
    mpz_add(g3, g1, Ea);
    mpz_mul(g3, g3, m);
    P = (W > wv ? W : wv) + 64;
    fr_exact(fr_v, g2, e - wv);
    mpfr_set_prec(fr_lo, (mpfr_prec_t)P);
    mpfr_log(fr_lo, fr_v, MPFR_RNDD);         /* at or below log V_lo */
    fr_exact(fr_v, g3, e - wv);
    mpfr_set_prec(fr_hi, (mpfr_prec_t)P);
    mpfr_log(fr_hi, fr_v, MPFR_RNDU);         /* at or above log V_hi */
    if (!ok_bracket(&r, Er, 0, fr_lo, fr_hi)) {
        char s1[400], s3[400];
        T->over++;
        show(s1, sizeof s1, &v);
        show(s3, sizeof s3, &r);
        fail(T, "log of the argument's enclosure outside the result's",
             "W %d: log %s -> %s", W, s1, s3);
    }
    /* The control, on a quarter of the arguments that carry an error:
     * the same value with that error left out, which must fail. */
    if (mpz_sgn(Ea) && ctl) {
        v0 = v;
        put_err(&v0, sp(0, 0));
        if (cft_tr_probe_log_of_mp(&r0, &v0, W) == 0) {
            log_ctl_of++;
            get_err(Eo, &inf0, &r0);
            if (!ok_bracket(&r0, Eo, inf0, fr_lo, fr_hi))
                log_ctl++;
        }
    }
}

/* A random count in [2^j, 2^(j+1)), j >= 0. */
static spec sp_between(long j)
{
    if (j < 0)
        j = 0;
    if (j <= 61)
        return sp(((uint64_t)1 << j) + below((uint64_t)1 << j), 0);
    return sp(((uint64_t)1 << 62) | (next() >> 2), j - 62);
}

/* The argument's count, in units of its own width wv, by its relative
 * error e: zero; small; 2^-5 to 1/2, where the conversion's 2^(1 - E0)
 * has the least room; at the rule's limit of 1/2 read at W; 1/2 to 1;
 * 1 and past it, where no finite bound exists; and anything. */
static spec log_count(long wv, int W)
{
    uint64_t u = below(20);
    if (u < 3)
        return sp(0, 0);
    if (u < 5)
        return sp(1 + below((uint64_t)1 << 20), 0);
    if (u < 11)
        return sp_between(wv - 2 - (long)below(4));
    if (u < 13) {
        long j = wv > W && (next() & 1) ? W - 1 : wv - 1;
        switch (below(3)) {
        case 0:  return sp_below(j);
        case 1:  return sp_pow2(j);
        default: return j < 63 ? sp(((uint64_t)1 << j) + 1, 0)
                               : sp(((uint64_t)1 << 62) + 1, j - 62);
        }
    }
    if (u < 16)
        return sp_between(wv - 1);
    if (u < 19) {
        switch (below(6)) {
        case 0:  return sp_below(wv);
        case 1:  return sp_pow2(wv);
        case 2:  return sp_between(wv);
        case 3:  return sp_pow2(wv + 3);
        case 4:  return wv < 100 ? sp((uint64_t)3 << 61, 39) : sp_pow2(wv + 9);
        default: return sp_inf();
        }
    }
    return sp(next() >> below(63), 0);
}

/* Widths spanning those the evaluator takes a logarithm at (verifier-W5
 * measured {128, 189, 313, 565} at the contract's precision and
 * {104, 107, 111, 169, 175, 287} forced; 256, 832 and 928 here no call
 * reaches, which costs nothing, since the rule has no width-specific
 * code): Wi = W + 32 + the
 * format's headroom, from 104 (fp32 forced to start at 64 bits by
 * CFT_TRANSCEND_MINPREC, the narrowest any call reaches) through each
 * format's first attempt (128, 189, 313, 565) and cap (360, 595, 879,
 * 883) to CFT_MP_PREC_MAX. Narrower, the logarithm's own evaluation can
 * refuse (an exact cancellation of 8-bit sums), which is not the
 * conversion's refusal and no caller sees. */
static const int LOGW[] = { 104, 107, 111, 128, 169, 189, 256, 313, 360,
                            565, 595, 832, 879, 883, 928 };
#define NLOGW 15
#define LOG_ARGS 8000          /* the default run's; --full takes ten times */

/* n arguments, in three kinds: a logarithm just above a power of two
 * of either sign, so that the stored l sits at the bottom of its binade
 * where 2^(1 - E0) has the least room; an argument near 1, its log from
 * 2^-1 down past the refusal at 2^-32; and anywhere, at scales to
 * 2^+-200,000. Each at a width of its own: W, narrower, or wider (the
 * Payne-Hanek reduction's t is wider). Two thirds are drawn at the
 * widths to 360, since one at 832 or more costs a few milliseconds. */
static void log_leg(long n)
{
    long i;
    mpz_t m;
    mpz_init(m);
    for (i = 0; i < n; i++) {
        int W = LOGW[below(3) ? below(NLOGW - 6) : NLOGW - 6 + below(6)];
        uint64_t u = below(10), kind = below(8);
        long wv, e;
        wv = u < 6 ? W : (u < 8 ? W - 1 - (long)below(4)
                                : W + 1 + (long)below(u == 8 ? 40 : 300));
        if (wv < 2)
            wv = 2;
        if (kind < 3) {
            long E0 = below(4) ? (long)below(21) - 3 : -(long)below(33);
            mpfr_set_prec(fr_t, (mpfr_prec_t)(wv + 64));
            mpfr_set_prec(fr_y, 64);
            mpfr_set_ui(fr_y, (unsigned long)(next() & 0xffffffffu),
                        MPFR_RNDN);
            mpfr_mul_2si(fr_y, fr_y, -32 - (long)below(30), MPFR_RNDN);
            mpfr_add_ui(fr_y, fr_y, 1, MPFR_RNDN);  /* 1 + delta, exact */
            mpfr_mul_2si(fr_t, fr_y, E0, MPFR_RNDN);
            if (next() & 1)
                mpfr_neg(fr_t, fr_t, MPFR_RNDN);
            mpfr_set_prec(fr_v, (mpfr_prec_t)wv);
            mpfr_exp(fr_v, fr_t, MPFR_RNDN);
            e = (long)mpfr_get_z_2exp(m, fr_v);
        } else if (kind < 5) {
            long k = 1 + (long)below(40), lo = wv - 1 - k;
            mpz_set_ui(m, 1);
            if (lo >= 1) {
                rnd_sig(t5, lo);                    /* 2^-k-ish below 1 */
            } else {
                mpz_set_ui(t5, 1);
            }
            if (next() & 1) {                       /* 1 + small */
                mpz_mul_2exp(m, m, (mp_bitcnt_t)(wv - 1));
                mpz_add(m, m, t5);
                e = -(wv - 1);
            } else {                                /* 1 - small */
                mpz_mul_2exp(m, m, (mp_bitcnt_t)wv);
                mpz_sub(m, m, t5);
                e = -wv;
            }
        } else {
            rnd_sig(m, wv);
            e = -(wv - 1) + (below(8) ? (long)below(2001) - 1000
                                      : (long)below(400001) - 200000);
        }
        {
            spec cv = log_count(z_bitlen(m), W);
            int ctl = below(4) == 0;
            log_case(W, z_bitlen(m), m, e, cv, ctl);
        }
    }
    mpz_clear(m);
}
#endif

/* ---- the legs -------------------------------------------------------------- */

static const uint32_t UIS[] = { 1, 2, 3, 5, 7, 255, 0x80000001u, 0xffffffffu };
#define NUIS 8

/* W = 6, every significand, and fourteen counts on each operand. */
static void exhaustive(void)
{
    const int W = 6;
    long x, y, d;
    int i, j, s, u;
    mpz_t xa, xb;
    mpz_init(xa);
    mpz_init(xb);
    for (x = 32; x < 64; x++) {
        mpz_set_ui(xa, (unsigned long)x);
        for (y = 32; y < 64; y++) {
            mpz_set_ui(xb, (unsigned long)y);
            for (i = 0; i < NSPEC; i++)
                for (j = 0; j < NSPEC; j++) {
                    spec ca = spec_at(i, W), cb = spec_at(j, W);
                    for (s = 0; s < 2; s++) {
                        for (d = -(W + 4); d <= W + 4; d++)
                            case_add(W, 0, 0, xa, ca, s, d, xb, cb, 0);
                        case_mul(W, 0, xa, ca, s, xb, cb, 0, 0);
                        case_div(W, 0, xa, ca, s, xb, cb, 0, 0);
                    }
                }
        }
        for (i = 0; i < NSPEC; i++) {
            spec ca = spec_at(i, W);
            for (u = 0; u < NUIS; u++) {
                case_ui(W, 0, 0, xa, ca, UIS[u], 0);
                case_ui(W, 1, 1, xa, ca, UIS[u], 0);
            }
            case_sqrt(W, xa, ca, 0);
            case_sqrt(W, xa, ca, 1);
            for (d = -4; d <= 4; d++)
                for (s = 0; s < 2; s++) {
                    int64_t v = (int64_t)(x << (d + 4)) >> 4;  /* near v */
                    long k;
                    for (k = -1; k <= 1; k++)
                        case_cmp(W, s, xa, ca, d,
                                 s ? -(v + k) : v + k);
                }
        }
    }
    for (x = 1; x < (1L << (W + 5)); x++) {
        mpz_set_ui(xa, (unsigned long)x);
        case_set(W, (int)(x & 1), xa, -3);
    }
    mpz_clear(xa);
    mpz_clear(xb);
}

static const int WIDTHS[] = { 8, 12, 16, 24, 32, 53, 64, 88, 128, 256, 512, 928 };
#define NWIDTHS 12

/* A width near W: W itself half the time, else within 3 of it. */
static int near_w(int W)
{
    int w;
    if (next() & 1)
        return W;
    w = W + (int)below(7) - 3;
    return w < 2 ? 2 : w;
}

static void sample(long per)
{
    int wi;
    long n;
    mpz_t xa, xb;
    mpz_init(xa);
    mpz_init(xb);
    for (wi = 0; wi < NWIDTHS; wi++) {
        int W = WIDTHS[wi];
        long scale = W <= 128 ? per : (W <= 256 ? per / 4 : per / 16);
        if (scale < 1)
            scale = 1;
        for (n = 0; n < scale; n++) {
            int wa = near_w(W), wb = near_w(W);
            int kind = (int)below(3);
            long d;
            rnd_sig(xa, wa);
            if (kind == 0) {
                /* deep cancellation: b within a few units of a */
                mpz_set(xb, xa);
                if (next() & 1)
                    mpz_add_ui(xb, xb, (unsigned long)below(1000));
                else if (mpz_cmp_ui(xa, 2000) > 0)
                    mpz_sub_ui(xb, xb, (unsigned long)below(1000));
                if (z_bitlen(xb) != wa)
                    mpz_set(xb, xa);
                d = 0;
            } else if (kind == 1) {
                /* one place apart: b near 2a, or near a/2 */
                rnd_sig(xb, wb);
                d = (next() & 1) ? 1 : -1;
            } else {
                rnd_sig(xb, wb);
                d = (long)below((uint64_t)(2 * W + 13)) - (W + 6);
            }
            {
                spec ca = rnd_spec(W), cb = rnd_spec(W);
                int sub = (int)(next() & 1), sb = (int)(next() & 1);
                case_add(W, 0, 7, xa, ca, sb, 7 + d, xb, cb, sub);
            }
            rnd_sig(xb, wb);
            case_mul(W, (int)(next() & 1), xa, rnd_spec(W), (int)(next() & 1),
                     xb, rnd_spec(W), (long)below(40) - 20,
                     (long)below(40) - 20);
            case_div(W, (int)(next() & 1), xa, rnd_spec(W), (int)(next() & 1),
                     xb, rnd_spec(W), (long)below(40) - 20,
                     (long)below(40) - 20);
            case_ui(W, (int)(next() & 1), (int)(next() & 1), xa, rnd_spec(W),
                    (next() & 1) ? UIS[below(NUIS)]
                                 : (uint32_t)(next() | 1u),
                    (long)below(40) - 20);
            case_sqrt(W, xa, rnd_spec(W), (long)below(40) - 20);
            rnd_sig(xb, (long)(1 + below((uint64_t)(W + 70))));
            case_set(W, (int)(next() & 1), xb, (long)below(40) - 20);
            {
                /* a value between 1 and 2^20, against integers near it */
                long e = 20 - wa - (long)below(21);
                int s = (int)(next() & 1);
                int64_t v;
                mpz_mul_2exp(t5, xa, 0);
                if (e >= 0)
                    mpz_mul_2exp(t5, t5, (mp_bitcnt_t)e);
                else
                    mpz_fdiv_q_2exp(t5, t5, (mp_bitcnt_t)(-e));
                v = (int64_t)mpz_get_ui(t5) + (int64_t)below(3) - 1;
                case_cmp(W, s, xa, rnd_spec(W), e, s ? -v : v);
            }
        }
    }
    mpz_clear(xa);
    mpz_clear(xb);
}

/* ---- the report ------------------------------------------------------------ */

static unsigned long long control_failed;

static void report(const tally *T)
{
    int is_log = 0;
#ifndef MP_ERR_CHECK_BASE
    is_log = T == &T_log;
#endif
    printf("  %-8s %12llu results, %llu over their bound", T->name,
           T->checked, T->over);
    if (T->refused)
        printf(", %llu refused (%s)", T->refused,
               is_log ? "v exactly 1, or its log below 2^-32"
                      : "the exact cancellation");
    if (T->unheld)
        printf(", %llu operands %s", T->unheld,
               is_log ? "too wide to build" : "the old field cannot hold");
    printf("\n");
#ifndef MP_ERR_CHECK_BASE
    if (T == &T_const) {
        printf("           all six constants at every W from 2 to %d, "
               "against MPFR; a count of one unit fails on %llu of them\n",
               CFT_MP_PREC_MAX, const_ctl);
        return;
    }
    if (T == &T_log) {
        printf("           %llu infinite (%llu from a count below 2^(W-1) "
               "read at W); with the argument's error left out, %llu of "
               "%llu fail\n", log_inf, log_inf_early, log_ctl, log_ctl_of);
        return;
    }
#endif
    if (T == &T_cmp) {
        printf("           %llu decided; the stored value's own answer, "
               "ignoring the count, fails on %llu of %llu\n",
               T->decided, T->ctl_fail, T->cmp);
    } else if (T->cmp) {
#ifdef MP_ERR_CHECK_BASE
        printf("           the old rules transcribed: %llu of %llu agree; "
               "over their bound on %llu of those\n",
               T->cmp - T->model, T->cmp, T->ctl_fail);
#else
        printf("           the old rules on %llu of them: never above this "
               "count%s; their counts over the bound on %llu\n",
               T->cmp, T->below_old ? " - FAILED" : "", T->ctl_fail);
#endif
    }
}

int main(int argc, char **argv)
{
    long per = 100000, logs = -1;
    int full = 0, i;
    clock_t t0 = clock();
    const tally *all[] = { &T_add, &T_sub, &T_mul, &T_div, &T_mul_ui,
                           &T_div_ui, &T_sqrt, &T_set, &T_cmp, &T_arith,
                           &T_reg
#ifndef MP_ERR_CHECK_BASE
                           , &T_const, &T_log
#endif
                         };
    unsigned long long total = 0, over = 0;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--full")) {
            full = 1;
            per = 1000000;
        } else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
            rs = strtoull(argv[++i], NULL, 0) | 1;
        } else if (!strcmp(argv[i], "--per") && i + 1 < argc) {
            per = atol(argv[++i]);
        } else if (!strcmp(argv[i], "--logs") && i + 1 < argc) {
            logs = atol(argv[++i]);
        } else {
            fprintf(stderr, "usage: mp-err-check [--full] [--seed N] "
                            "[--per TRIALS-PER-WIDTH] [--logs ARGUMENTS]\n");
            return 2;
        }
    }
    mpz_init(ma); mpz_init(mb); mpz_init(mr); mpz_init(Ea); mpz_init(Eb);
    mpz_init(Er); mpz_init(Eo); mpz_init(t1); mpz_init(t2); mpz_init(t3);
    mpz_init(t4); mpz_init(t5); mpz_init(lhs); mpz_init(rhs);

#ifdef MP_ERR_CHECK_BASE
    printf("mp-err-check, built against the OLD library (MP_ERR_CHECK_BASE): "
           "its failures are the control's\n");
#endif
    printf("mp-err-check: W = 6, exhaustively\n");
    exhaustive();
    printf("mp-err-check: a %s sample, W = 8 to 928, seed 0x%llx\n",
           full ? "full" : "fixed-seed", (unsigned long long)rs);
    sample(per);
    printf("mp-err-check: verifier-W4's scaled-down clamp, at W = 88\n");
    regression_w4();
#ifndef MP_ERR_CHECK_BASE
    {
        long n, narith = full ? 10000000 : 1000000;
        long nlog = logs >= 0 ? logs : (full ? 10 * LOG_ARGS : LOG_ARGS);
        for (n = 0; n < narith; n++)
            arith_case();
        /* After every leg above, so their samples are what they were:
         * the logarithm's draws continue the same fixed sequence. */
        mpz_init(b1); mpz_init(b2); mpz_init(b3);
        mpz_init(g1); mpz_init(g2); mpz_init(g3);
        mpfr_init2(fr_a, 2); mpfr_init2(fr_b, 2); mpfr_init2(fr_v, 2);
        mpfr_init2(fr_lo, 2); mpfr_init2(fr_hi, 2); mpfr_init2(fr_t, 2);
        mpfr_init2(fr_y, 2);
        printf("mp-err-check: the six constants against MPFR, W = 2 to %d\n",
               CFT_MP_PREC_MAX);
        const_leg();
        printf("mp-err-check: the logarithm's conversion against MPFR's "
               "log, %ld arguments\n", nlog);
        log_leg(nlog);
    }
#endif
    for (i = 0; i < (int)(sizeof all / sizeof all[0]); i++) {
        if (!all[i]->checked)
            continue;
        report(all[i]);
        total += all[i]->checked;
        over += all[i]->over;
        control_failed += all[i]->ctl_fail;
    }
#ifdef MP_ERR_CHECK_BASE
    {
        unsigned long long model = 0;
        (void)logs;                      /* the MPFR legs are left out */
        for (i = 0; i < (int)(sizeof all / sizeof all[0]); i++)
            model += all[i]->model;
        printf("mp-err-check: the OLD library, %llu results: %llu over their "
               "bound (the control fails, as it must%s); the transcription "
               "of the old rules %s; %.1f s\n",
               total, over, over ? "" : " - it DID NOT",
               model ? "DISAGREES with the old library" : "agrees with it on "
               "every one compared",
               (double)(clock() - t0) / CLOCKS_PER_SEC);
        if (model)
            return 2;
        return over ? 1 : 3;
    }
#else
    control_failed -= T_cmp.ctl_fail;
    if (control_failed == 0) {
        printf("  FAIL the control: the old rules' counts passed every "
               "verdict, so this checker could not see a rule that is not "
               "a bound\n");
        failures++;
    }
    if (T_cmp.ctl_fail == 0) {
        printf("  FAIL the control: every answer from the stored value "
               "alone passed cmp_int's verdict, so it could not see an "
               "enclosure that decides too much\n");
        failures++;
    }
    if (const_ctl == 0) {
        printf("  FAIL the control: a constant's count of one unit held at "
               "every width, so this checker could not see a constant's "
               "count that is short\n");
        failures++;
    }
    if (log_ctl == 0) {
        printf("  FAIL the control: the logarithm held with its argument's "
               "error left out, so this checker could not see a conversion "
               "that is short\n");
        failures++;
    }
    printf("mp-err-check: %llu results over the rules, the constants, the "
           "logarithm's conversion and the count's arithmetic, %llu over "
           "their bound: %s; the old rules' counts fail the same verdicts "
           "on %llu, the stored value's own answers fail cmp_int's on %llu, "
           "a constant's count of one unit fails on %llu, and the logarithm "
           "without its argument's error on %llu (the controls); %.1f s\n",
           total, over, failures ? "FAILED" : "every one within its bound",
           control_failed, T_cmp.ctl_fail, const_ctl, log_ctl,
           (double)(clock() - t0) / CLOCKS_PER_SEC);
    return failures ? 1 : 0;
#endif
}
