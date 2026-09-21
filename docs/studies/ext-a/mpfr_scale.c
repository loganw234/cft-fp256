/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * mpfr_scale - an instrument of docs/studies/EXT-A-wide-ladder.md, and
 * nothing else. It is not built by any Makefile and no gate runs it.
 *
 * What it answers: how GNU MPFR's elementwise cost grows with precision,
 * from binary32's significand to binary8192's, one thread, and what the
 * MPFR manual's own IEEE-format recipe adds at each width.
 *
 *   mpfr      MPFR at the format's exact precision, default exponent
 *             range - the same row host/tools/cft_bench_peers.c calls
 *             `mpfr`.
 *   mpfr+754  the exponent range narrowed to the format's
 *             (mpfr_set_emin(emin - p + 2), mpfr_set_emax(emax + 1)),
 *             then mpfr_check_range + mpfr_subnormalize on every result
 *             - cft_bench_peers.c's `mpfr+754` row, the same two calls
 *             in the same order, at widths that tool does not reach.
 *             It still keeps no NaN payloads, no signaling NaNs, no
 *             roundTiesToAway and none of this contract's flag
 *             definitions; host/tools/mpfr_check.c's header lists what
 *             a caller has to add for each.
 *
 * Operands are uniform in [1, 2): normal, full random significand,
 * nothing near a range edge, so the +754 row prices the recipe's
 * fast path - the same choice cft_bench_peers.c makes and for the same
 * reason. Widths follow IEEE 754-2019 table 3.5 (3.6 for k >= 128):
 * exp_w = round(4 log2 k) - 13, p = k - exp_w.
 *
 *   gcc -O2 -o mpfr_scale mpfr_scale.c -lmpfr -lgmp && ./mpfr_scale
 */
#define _POSIX_C_SOURCE 200112L

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include <gmp.h>
#include <mpfr.h>

#define N 2048

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int exp_w_of(int k)
{
    if (k == 32) return 8;
    if (k == 64) return 11;
    return (int)floor(4.0 * log2((double)k) + 0.5) - 13;
}

int main(void)
{
    static const int widths[] = { 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192 };
    static const char *opname[] = { "mul", "fma", "div", "sqrt" };
    mpfr_exp_t def_emin = mpfr_get_emin(), def_emax = mpfr_get_emax();
    gmp_randstate_t rs;
    unsigned wi;

    gmp_randinit_default(rs);
    gmp_randseed_ui(rs, 12345);
    printf("MPFR %s, N=%d elements per pass, RNDN, one thread, ns per element\n",
           mpfr_get_version(), N);
    printf("%8s %6s %6s", "binary", "exp_w", "p");
    {
        int op;
        for (op = 0; op < 4; op++)
            printf(" %9s %9s", opname[op], "+754");
    }
    printf("\n");

    for (wi = 0; wi < sizeof widths / sizeof widths[0]; wi++) {
        int k = widths[wi], ew = exp_w_of(k);
        mpfr_prec_t p = (mpfr_prec_t)(k - ew);
        long long emax = (1LL << (ew - 1)) - 1, emin = 1 - emax;
        mpfr_t *a = malloc(N * sizeof *a), *b = malloc(N * sizeof *b);
        mpfr_t *c = malloc(N * sizeof *c), *d = malloc(N * sizeof *d);
        double t[4][2];
        int op, emu, i;

        for (i = 0; i < N; i++) {
            mpfr_init2(a[i], p); mpfr_init2(b[i], p);
            mpfr_init2(c[i], p); mpfr_init2(d[i], p);
            mpfr_urandomb(a[i], rs); mpfr_add_ui(a[i], a[i], 1, MPFR_RNDN);
            mpfr_urandomb(b[i], rs); mpfr_add_ui(b[i], b[i], 1, MPFR_RNDN);
            mpfr_urandomb(c[i], rs); mpfr_add_ui(c[i], c[i], 1, MPFR_RNDN);
        }
        for (emu = 0; emu < 2; emu++) {
            if (emu) {
                if (mpfr_set_emin((mpfr_exp_t)(emin - (long long)p + 2)) ||
                    mpfr_set_emax((mpfr_exp_t)(emax + 1))) {
                    fprintf(stderr, "binary%d: MPFR refused the format's exponent range\n", k);
                    return 1;
                }
            }
            for (op = 0; op < 4; op++) {
                long reps = 0;
                double t0 = now(), t1;
                do {
                    for (i = 0; i < N; i++) {
                        int tern;
                        switch (op) {
                        case 0:  tern = mpfr_mul(d[i], a[i], b[i], MPFR_RNDN); break;
                        case 1:  tern = mpfr_fma(d[i], a[i], b[i], c[i], MPFR_RNDN); break;
                        case 2:  tern = mpfr_div(d[i], a[i], b[i], MPFR_RNDN); break;
                        default: tern = mpfr_sqrt(d[i], a[i], MPFR_RNDN); break;
                        }
                        if (emu) {
                            tern = mpfr_check_range(d[i], tern, MPFR_RNDN);
                            mpfr_subnormalize(d[i], tern, MPFR_RNDN);
                        }
                    }
                    reps++;
                    t1 = now();
                } while (t1 - t0 < 0.4);
                t[op][emu] = (t1 - t0) * 1e9 / ((double)reps * N);
            }
            if (emu) {
                mpfr_set_emin(def_emin);
                mpfr_set_emax(def_emax);
            }
        }
        printf("%8d %6d %6d", k, ew, (int)p);
        for (op = 0; op < 4; op++)
            printf(" %9.1f %9.1f", t[op][0], t[op][1]);
        printf("\n");
        fflush(stdout);
        for (i = 0; i < N; i++) {
            mpfr_clear(a[i]); mpfr_clear(b[i]); mpfr_clear(c[i]); mpfr_clear(d[i]);
        }
        free(a); free(b); free(c); free(d);
    }
    gmp_randclear(rs);
    return 0;
}
