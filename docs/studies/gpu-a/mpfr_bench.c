/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A part 2: MPFR's speed beside libcft's sequencer, one core, by
 * docs/BENCHMARKS.md's mpfr+754 method (host/tools/cft_bench_peers.c): the
 * exponent range narrowed to the binary format's (emin = emin_f - p + 2,
 * emax = emax_f + 1), and mpfr_check_range then mpfr_subnormalize on every
 * result, round to nearest; per-element calls over 4,096 elements, passes
 * repeated for at least 0.3 s, the best pass reported.
 *
 * The arguments are bench.bin's (gen_programs.py): the typical lanes of the
 * rate programs, exp, sin and atan at fp64 (53 bits) and fp256 (237 bits).
 * The fp256 FMA's operands are the fp256 exp lanes taken three apart
 * (a = x[i], b = x[i + 1], c = x[i + 2]).
 *
 *   mpfr_bench BENCH.bin
 */
#define _POSIX_C_SOURCE 199309L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <gmp.h>
#include <mpfr.h>

#define N 4096

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + 1e-9 * t.tv_nsec;
}

/* An encoding of binary64 or binary256 into x (zero, normal or subnormal). */
static void dec(mpfr_t x, const uint8_t *p, int width)
{
    const int ew = width == 64 ? 11 : 19, fw = width - 1 - ew;
    const long bias = (1L << (ew - 1)) - 1;
    mpz_t z;
    long e = 0;
    int s, i;
    mpz_init(z);
    mpz_import(z, (size_t)width / 8, -1, 1, -1, 0, p);       /* little-endian bytes */
    s = mpz_tstbit(z, (mp_bitcnt_t)width - 1);
    for (i = 0; i < ew; i++)
        e |= (long)mpz_tstbit(z, (mp_bitcnt_t)(fw + i)) << i;
    mpz_fdiv_r_2exp(z, z, (mp_bitcnt_t)fw);                    /* the fraction */
    if (e == 0x7FFFF || (width == 64 && e == 0x7FF)) {
        fprintf(stderr, "a special argument in the bench corpus\n"); exit(2);
    }
    if (e)
        mpz_setbit(z, (mp_bitcnt_t)fw);
    mpfr_set_z_2exp(x, z, (e ? e : 1) - bias - fw, MPFR_RNDN);  /* exact: p >= fw + 1 */
    if (s)
        mpfr_neg(x, x, MPFR_RNDN);
    mpz_clear(z);
}

enum { OP_FMA, OP_EXP, OP_SIN, OP_ATAN };

static double pass(int op, mpfr_t *r, mpfr_t *a, mpfr_t *b, mpfr_t *c)
{
    const double t0 = now();
    int i, t;
    for (i = 0; i < N; i++) {
        switch (op) {
        case OP_FMA: t = mpfr_fma(r[i], a[i], b[i], c[i], MPFR_RNDN); break;
        case OP_EXP: t = mpfr_exp(r[i], a[i], MPFR_RNDN); break;
        case OP_SIN: t = mpfr_sin(r[i], a[i], MPFR_RNDN); break;
        default:     t = mpfr_atan(r[i], a[i], MPFR_RNDN); break;
        }
        t = mpfr_check_range(r[i], t, MPFR_RNDN);
        mpfr_subnormalize(r[i], t, MPFR_RNDN);
    }
    return now() - t0;
}

int main(int argc, char **argv)
{
    static const char *names[4] = {"fma", "exp", "sin", "atan"};
    FILE *fp;
    uint8_t *raw;
    long len, off = 0;
    int k, i;
    const uint8_t *lanes[6] = {0};
    if (argc != 2 || !(fp = fopen(argv[1], "rb"))) {
        fprintf(stderr, "usage: mpfr_bench BENCH.bin\n"); return 2;
    }
    fseek(fp, 0, SEEK_END); len = ftell(fp); fseek(fp, 0, SEEK_SET);
    raw = malloc((size_t)len);
    if (!raw || fread(raw, 1, (size_t)len, fp) != (size_t)len) return 2;
    fclose(fp);
    for (k = 0; k < 6 && off < len; k++) {       /* bench.bin's six cases, in order */
        uint32_t h[10];
        memcpy(h, raw + off + 8, 40);
        if (memcmp(raw + off, "CFTSEQA1", 8) || h[1] != N || h[4] != 3) {
            fprintf(stderr, "case %d is not bench.bin's\n", k); return 2;
        }
        lanes[k] = raw + off + 48 + h[9] + h[2] + h[3];
        off += 48 + h[9] + h[2] + h[3] + 3L * N * (h[0] == 1 ? 8 : 32);
    }
    printf("mpfr_bench: MPFR %s, GMP %s; one core, per-element calls over %d elements, "
           "mpfr+754 (narrowed range, check_range and subnormalize), round to nearest\n",
           mpfr_get_version(), gmp_version, N);
    for (k = 0; k < 2; k++) {                     /* fp64, then fp256 */
        const int width = k ? 256 : 64, p = k ? 237 : 53;
        const long emin = k ? -262142 : -1022, emax = k ? 262143 : 1023;
        const mpfr_exp_t e0 = mpfr_get_emin(), e1 = mpfr_get_emax();
        int op;
        for (op = k ? OP_FMA : OP_EXP; op <= OP_ATAN; op++) {
            mpfr_t *r = malloc(N * sizeof(mpfr_t)), *a = malloc(N * sizeof(mpfr_t)),
                   *b = malloc(N * sizeof(mpfr_t)), *c = malloc(N * sizeof(mpfr_t));
            const uint8_t *src = lanes[k * 3 + (op == OP_FMA ? 0 : op - 1)];
            double best = 1e30, tot = 0;
            int npass = 0;
            for (i = 0; i < N; i++) {
                mpfr_inits2(p, r[i], a[i], b[i], c[i], (mpfr_ptr)0);
                dec(a[i], src + (size_t)i * width / 8, width);
                dec(b[i], src + (size_t)((i + 1) % N) * width / 8, width);
                dec(c[i], src + (size_t)((i + 2) % N) * width / 8, width);
            }
            mpfr_set_emin((mpfr_exp_t)(emin - p + 2));
            mpfr_set_emax((mpfr_exp_t)(emax + 1));
            pass(op, r, a, b, c);                 /* a warm-up pass */
            while (tot < 0.3 || npass < 3) {
                const double s = pass(op, r, a, b, c);
                tot += s;
                npass++;
                if (s < best) best = s;
            }
            mpfr_set_emin(e0);
            mpfr_set_emax(e1);
            printf("mpfr_bench: %s at %d bits (binary%d): %.1f ns an element (best of %d "
                   "passes; mean %.1f), %.4g a second\n", names[op], p, width, best * 1e9 / N,
                   npass, tot / npass * 1e9 / N, N / best);
            for (i = 0; i < N; i++)
                mpfr_clears(r[i], a[i], b[i], c[i], (mpfr_ptr)0);
            free(r); free(a); free(b); free(c);
        }
    }
    free(raw);
    return 0;
}
