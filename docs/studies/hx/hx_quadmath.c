/* hx_quadmath.c - parcel HX: is gcc's __float128 a second oracle at fp128? (docs/studies/HX-wide-sweeps.md, 4.3;
 * scratch beside the study, nothing in the tree builds it).
 *
 * For add, sub, mul, div (libgcc's soft-fp), sqrtq and fmaq (libquadmath), under the four attributes the SSE
 * control word carries (fesetround), it compares every result with GNU MPFR emulating binary128 by its manual's
 * recipe (precision 113, emin -16493, emax 16384, check_range and subnormalize), values in the MPFR domain (both
 * exact at 113 bits; zeros by sign, NaN as a class), and the inexact flag (fetestexcept after the operation against
 * MPFR's final ternary). Operands: random normal values with exponents within 40 of the bias and, as a second
 * stream, fp32 values widened (the slice of the study). Then the time of each __float128 operation alone.
 *
 * HX_QUAD_SABOTAGE=1 flips the last bit of every 1,000th __float128 result before the comparison: the counts must
 * then show it (the control that shows the comparison can fail).
 *
 *   gcc -O2 hx_quadmath.c -o hx-quadmath -lquadmath -lmpfr -lgmp -lm && ./hx-quadmath [N]
 */
#define _POSIX_C_SOURCE 200112L
#include <fenv.h>
#include <quadmath.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <mpfr.h>

#pragma STDC FENV_ACCESS ON

static uint64_t rs = 0x2545F4914F6CDD1Dull;
static uint64_t rng(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }

static __float128 from_bits(uint64_t hi, uint64_t lo)
{
    __float128 x;
    unsigned char b[16];
    memcpy(b, &lo, 8);
    memcpy(b + 8, &hi, 8);
    memcpy(&x, b, 16);
    return x;
}

static void to_bits(__float128 x, uint64_t *hi, uint64_t *lo)
{
    unsigned char b[16];
    memcpy(b, &x, 16);
    memcpy(lo, b, 8);
    memcpy(hi, b + 8, 8);
}

/* a random normal binary128 value, exponent within 40 of the bias; or an fp32 value widened */
static __float128 operand(int slice, int positive)
{
    if (slice) {
        uint32_t u;
        float f;
        do { u = (uint32_t)rng(); } while (((u >> 23) & 0xff) == 0xff);
        if (positive) u &= 0x7fffffffu;
        memcpy(&f, &u, 4);
        return (__float128)f;
    } else {
        uint64_t hi = rng(), lo = rng();
        uint64_t e = 16383 + (rng() % 81) - 40;
        hi = (hi & 0x0000ffffffffffffull) | (e << 48) | (positive ? 0 : (rng() & 1) << 63);
        return from_bits(hi, lo);
    }
}

/* the exact value of a finite x into m (precision 113 holds it) */
static void to_mpfr(mpfr_t m, __float128 x)
{
    uint64_t hi, lo;
    int e, s;
    mpz_t z;
    to_bits(x, &hi, &lo);
    s = (int)(hi >> 63);
    e = (int)((hi >> 48) & 0x7fff);
    if (e == 0x7fff) {
        if ((hi & 0x0000ffffffffffffull) | lo) mpfr_set_nan(m);
        else mpfr_set_inf(m, s ? -1 : 1);
        return;
    }
    mpz_init(z);
    mpz_set_ui(z, (unsigned long)(hi & 0x0000ffffffffffffull) | (e ? (1ul << 48) : 0));
    mpz_mul_2exp(z, z, 64);
    mpz_add_ui(z, z, 0);
    {
        mpz_t l;
        mpz_init(l);
        mpz_set_ui(l, (unsigned long)(lo >> 32));
        mpz_mul_2exp(l, l, 32);
        mpz_add_ui(l, l, (unsigned long)(lo & 0xffffffffu));
        mpz_add(z, z, l);
        mpz_clear(l);
    }
    if (s) mpz_neg(z, z);
    mpfr_set_z_2exp(m, z, (e ? e : 1) - 16383 - 112, MPFR_RNDN);   /* exact */
    if (mpz_sgn(z) == 0 && s) mpfr_neg(m, m, MPFR_RNDN);
    mpz_clear(z);
}

static int same(mpfr_t a, mpfr_t b)
{
    if (mpfr_nan_p(a) || mpfr_nan_p(b)) return mpfr_nan_p(a) && mpfr_nan_p(b);
    if (mpfr_zero_p(a) || mpfr_zero_p(b))
        return mpfr_zero_p(a) && mpfr_zero_p(b) && mpfr_signbit(a) == mpfr_signbit(b);
    return mpfr_equal_p(a, b);
}

enum { O_ADD, O_SUB, O_MUL, O_DIV, O_SQRT, O_FMA, NOP };
static const char *ONAME[NOP] = { "add", "sub", "mul", "div", "sqrtq", "fmaq" };

static __float128 qop(int op, __float128 a, __float128 b, __float128 c)
{
    switch (op) {
    case O_ADD: return a + b;
    case O_SUB: return a - b;
    case O_MUL: return a * b;
    case O_DIV: return a / b;
    case O_SQRT: return sqrtq(a);
    default: return fmaq(a, b, c);
    }
}

static int mop(int op, mpfr_t r, mpfr_t a, mpfr_t b, mpfr_t c, mpfr_rnd_t rnd)
{
    switch (op) {
    case O_ADD: return mpfr_add(r, a, b, rnd);
    case O_SUB: return mpfr_sub(r, a, b, rnd);
    case O_MUL: return mpfr_mul(r, a, b, rnd);
    case O_DIV: return mpfr_div(r, a, b, rnd);
    case O_SQRT: return mpfr_sqrt(r, a, rnd);
    default: return mpfr_fma(r, a, b, c, rnd);
    }
}

int main(int argc, char **argv)
{
    static const struct { int fe; mpfr_rnd_t r; const char *name; } MODES[4] = {
        { FE_TONEAREST, MPFR_RNDN, "rne" }, { FE_TOWARDZERO, MPFR_RNDZ, "rtz" },
        { FE_DOWNWARD, MPFR_RNDD, "rdn" }, { FE_UPWARD, MPFR_RNDU, "rup" } };
    long n = argc > 1 ? atol(argv[1]) : 100000, i;
    int sabotage = getenv("HX_QUAD_SABOTAGE") && !strcmp(getenv("HX_QUAD_SABOTAGE"), "1");
    int op, mi, slice, bad_total = 0;
    mpfr_t a, b, c, r, q;
    mpfr_set_emin(-16493);
    mpfr_set_emax(16384);
    mpfr_inits2(113, a, b, c, r, q, (mpfr_ptr)0);
    printf("hx-quadmath: %ld cases an (operation, attribute, stream); MPFR %s; gcc %d.%d%s\n", n, mpfr_get_version(),
           __GNUC__, __GNUC_MINOR__, sabotage ? "; SABOTAGE: every 1,000th result's last bit flipped" : "");
    for (slice = 0; slice < 2; slice++) {
        for (op = 0; op < NOP; op++) {
            for (mi = 0; mi < 4; mi++) {
                long vbad = 0, fbad = 0, inex = 0;
                for (i = 0; i < n; i++) {
                    __float128 x = operand(slice, op == O_SQRT), y = operand(slice, 0), z = operand(slice, 0), w;
                    int fq, t;
                    fesetround(MODES[mi].fe);
                    feclearexcept(FE_ALL_EXCEPT);
                    w = qop(op, x, y, z);
                    fq = fetestexcept(FE_INEXACT) != 0;
                    fesetround(FE_TONEAREST);
                    if (sabotage && i % 1000 == 0) {
                        uint64_t hi, lo;
                        to_bits(w, &hi, &lo);
                        w = from_bits(hi, lo ^ 1);
                    }
                    to_mpfr(a, x); to_mpfr(b, y); to_mpfr(c, z);
                    mpfr_clear_flags();
                    t = mop(op, r, a, b, c, MODES[mi].r);
                    t = mpfr_check_range(r, t, MODES[mi].r);
                    t = mpfr_subnormalize(r, t, MODES[mi].r);
                    to_mpfr(q, w);
                    if (!same(q, r) && vbad == 0 && !sabotage) {
                        mpfr_t d;                         /* the first mismatch of a cell, in MPFR's units */
                        mpfr_init2(d, 113);
                        mpfr_sub(d, q, r, MPFR_RNDN);
                        mpfr_printf("    first mismatch: %s(%Ra%s%s): __float128 %Ra, MPFR %Ra, difference %Ra\n",
                                    ONAME[op], a, op == O_SQRT ? "" : ", ", "", q, r, d);
                        mpfr_clear(d);
                    }
                    vbad += !same(q, r);
                    fbad += fq != (t != 0);
                    inex += t != 0;
                }
                printf("  %-6s %-5s %s: %ld value mismatches, %ld inexact-flag mismatches (%ld of %ld inexact)\n",
                       slice ? "fp32w" : "random", ONAME[op], MODES[mi].name, vbad, fbad, inex, n);
                bad_total += vbad != 0 || fbad != 0;
            }
        }
    }
    for (op = 0; op < NOP; op++) {
        __float128 acc = 0, x = operand(0, 1), y = operand(0, 0), z = operand(0, 0);
        struct timespec t0, t1;
        long reps = op == O_SQRT || op == O_FMA ? 200000 : 2000000;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        for (i = 0; i < reps; i++) {
            acc += qop(op, x, y, z);
            x += (__float128)1e-30;
        }
        clock_gettime(CLOCK_MONOTONIC, &t1);
        printf("  time %-5s %.1f ns a call (sum %g)\n", ONAME[op],
               ((t1.tv_sec - t0.tv_sec) * 1e9 + (t1.tv_nsec - t0.tv_nsec)) / reps, (double)acc);
    }
    printf("hx-quadmath: %d (stream, operation, attribute) cells with a mismatch\n", bad_total);
    mpfr_clears(a, b, c, r, q, (mpfr_ptr)0);
    return bad_total ? 1 : 0;
}
