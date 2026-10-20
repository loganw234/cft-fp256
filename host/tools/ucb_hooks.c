/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft as the arithmetic under test in UCBTEST (docs/EXTERNAL-GENERATORS.md).
 *
 * UCBTEST's ucbdivtest, ucbsqrtest and ucbmultest generate their hard cases by
 * number theory (Kahan's constructions, ucbtest/div.c, sqr.c, mul.c) and keep
 * the arithmetic they test in separate functions, testdivd_, testsqrtd_,
 * testmuld_ and their single-precision kin, which take pointers:
 *
 *     void testdivd_(double *z, double *x, double *y)      *z = *x / *y
 *
 * so that a platform supplies its own. This file supplies them from libcft,
 * and links with UCBTEST's own div.c, sqr.c, mul.c, init.c and mains
 * UNCHANGED (host/tools/ucb_run.sh builds them from the extracted archive in
 * a directory of the caller's; no byte of UCBTEST is in this repository).
 * UCBTEST's own judge then decides, by exact integer arithmetic it derives
 * itself, whether libcft's quotient, root or product is the correctly rounded
 * one; its exit status and its UCBPASS / UCBFAIL line are the verdict.
 *
 * The rounding attribute is the host's: UCBTEST sets it through the platform
 * functions round_nearest, round_positive and round_zero (written at the end
 * of this file, with fesetround), and this file reads it back with fegetround
 * when it calls libcft. In practice every call runs under round to nearest:
 * ucbmultest sets the directed attributes only around its own host
 * arithmetic, and the dumps show no other attribute.
 *
 * Two extra instruments, both optional and both ours:
 *
 *   CFT_UCB_HOSTCHECK=1   every call is also computed by the host CPU's own
 *       IEEE hardware under the same rounding attribute (SSE division, square
 *       root and multiplication are correctly rounded per 754, defined by
 *       people who never saw this project - the oracle of host/tools/
 *       divsqrt_soak.c) and compared bit for bit, flags included. A mismatch
 *       is counted, and the process exits 3 at the end.
 *   CFT_UCB_DUMP=PREFIX   every call's operands are written, in TestFloat's
 *       raw hex (one case a line), to PREFIX.<function>.<mode>, so that the very
 *       same hard cases can be replayed through cft-tf-subject into
 *       testfloat_ver: SoftFloat as a third judge of what UCBTEST built.
 *
 *   CFT_UCB_SABOTAGE=1   flips the low bit of every 4,096th result after the
 *       library computes it: the negative control. A harness that cannot fail
 *       proves nothing; with it UCBTEST must report UCBFAIL (exit 42) and the
 *       host check must count mismatches (exit 3).
 *
 * CFT_SOAK_ARTIFACT names an .xclbin to run on instead of the software
 * backend, as the soak tools read it; the banner names the backend.
 *
 * Compiled -std=c99 -frounding-math -fno-math-errno (the host check's two
 * demands, as in the soak tools).
 */

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"

enum { OP_DIV, OP_SQRT, OP_MUL, NOPS };
static const char *OPNAME[NOPS][2] = { { "divs", "divd" },
                                       { "sqrts", "sqrtd" },
                                       { "muls", "muld" } };
static const char *MODENAME[4] = { "near_even", "min", "max", "minMag" };

static cft_device *dev;
static int started, hostcheck, sabotage;
static unsigned long long ncalls[NOPS][2], vmis[NOPS][2], fmis[NOPS][2];
static FILE *dump[NOPS][2][4];
static const char *dump_prefix;

static void fail(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-ucb-hooks: %s: %s%s%s\n", what, cft_strerror(st),
            (d && *d) ? " - " : "", (d && *d) ? d : "");
    _Exit(2);
}

static void report(void)
{
    int o, p;
    unsigned long long bad = 0;
    for (o = 0; o < NOPS; o++)
        for (p = 0; p < 2; p++) {
            int m;
            if (!ncalls[o][p])
                continue;
            fprintf(stderr, "cft-ucb-hooks: %s: %llu calls", OPNAME[o][p],
                    ncalls[o][p]);
            if (hostcheck)
                fprintf(stderr, ", host check: %llu value and %llu flag mismatches",
                        vmis[o][p], fmis[o][p]);
            fprintf(stderr, "\n");
            bad += vmis[o][p] + fmis[o][p];
            for (m = 0; m < 4; m++)
                if (dump[o][p][m])
                    fclose(dump[o][p][m]);
        }
    fflush(NULL);   /* UCBTEST's own verdict line is still in stdout's buffer */
    if (bad)
        _Exit(3);
}

static void start(void)
{
    const char *art = getenv("CFT_SOAK_ARTIFACT");
    const char *hc = getenv("CFT_UCB_HOSTCHECK");
    cft_status st;
    if (art && !*art)
        art = NULL;
    st = cft_open(art, 0, &dev);
    if (st != CFT_OK)
        fail(art ? "cft_open of the artifact failed" : "cft_open failed", st);
    fprintf(stderr, "cft-ucb-hooks: libcft on the %s backend%s%s\n",
            art ? "DEVICE" : "software", art ? ": " : "", art ? art : "");
    hostcheck = hc && *hc == '1';
    sabotage = getenv("CFT_UCB_SABOTAGE") && *getenv("CFT_UCB_SABOTAGE") == '1';
    dump_prefix = getenv("CFT_UCB_DUMP");
    if (dump_prefix && !*dump_prefix)
        dump_prefix = NULL;
    atexit(report);
    started = 1;
}

/* the host's rounding attribute as libcft's, and its slot in MODENAME */
static cft_round cur_round(int *mi)
{
    switch (fegetround()) {
    case FE_DOWNWARD:   *mi = 1; return CFT_RDN;
    case FE_UPWARD:     *mi = 2; return CFT_RUP;
    case FE_TOWARDZERO: *mi = 3; return CFT_RTZ;
    default:            *mi = 0; return CFT_RNE;
    }
}

static uint32_t fe_to_cft(int ex)
{
    return ((ex & FE_INVALID) ? CFT_FLAG_INVALID : 0) |
           ((ex & FE_DIVBYZERO) ? CFT_FLAG_DIVBYZERO : 0) |
           ((ex & FE_OVERFLOW) ? CFT_FLAG_OVERFLOW : 0) |
           ((ex & FE_UNDERFLOW) ? CFT_FLAG_UNDERFLOW : 0) |
           ((ex & FE_INEXACT) ? CFT_FLAG_INEXACT : 0);
}

static int is_nan_bits(uint64_t b, int dbl)
{
    return dbl ? ((b & 0x7ff0000000000000ull) == 0x7ff0000000000000ull &&
                  (b & 0x000fffffffffffffull) != 0)
               : ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu) != 0);
}

/* One call: z = x op y (y unused for the root), `dbl` selecting binary64. */
static void call(int op, int dbl, void *z, const void *x, const void *y)
{
    cft_format fmt = dbl ? CFT_FP64 : CFT_FP32;
    uint32_t fl = 0;
    cft_status st = CFT_OK;
    int mi;
    cft_round r;
    uint64_t xb = 0, yb = 0, zb = 0, hb = 0;

    if (!started)
        start();
    r = cur_round(&mi);
    switch (op) {
    case OP_DIV:  st = cft_div(dev, fmt, r, x, y, z, 1, &fl, NULL); break;
    case OP_SQRT: st = cft_sqrt(dev, fmt, r, x, z, 1, &fl, NULL); break;
    default:      st = cft_run(dev, CFT_MUL, fmt, r, x, y, NULL, z, 1, &fl, NULL);
    }
    if (st != CFT_OK)
        fail("a libcft call failed", st);
    ncalls[op][dbl]++;
    if (sabotage && ncalls[op][dbl] % 4096 == 0)
        ((unsigned char *)z)[0] ^= 1u;   /* the negative control */

    if (dump_prefix || hostcheck) {
        size_t sz = dbl ? 8 : 4;
        memcpy(&xb, x, sz);
        if (op != OP_SQRT)
            memcpy(&yb, y, sz);
        memcpy(&zb, z, sz);
    }
    if (dump_prefix) {
        FILE **f = &dump[op][dbl][mi];
        if (!*f) {
            char path[1024];
            snprintf(path, sizeof path, "%s.%s.%s", dump_prefix,
                     OPNAME[op][dbl], MODENAME[mi]);
            *f = fopen(path, "w");
            if (!*f) {
                fprintf(stderr, "cft-ucb-hooks: cannot write %s\n", path);
                _Exit(2);
            }
        }
        if (op == OP_SQRT)
            fprintf(*f, dbl ? "%016llX\n" : "%08llX\n", (unsigned long long)xb);
        else
            fprintf(*f, dbl ? "%016llX %016llX\n" : "%08llX %08llX\n",
                    (unsigned long long)xb, (unsigned long long)yb);
    }
    if (hostcheck) {
        int ex;
        feclearexcept(FE_ALL_EXCEPT);
        if (dbl) {
            volatile double a, b = 0, c;
            memcpy((void *)&a, &xb, 8);
            memcpy((void *)&b, &yb, 8);
            c = op == OP_DIV ? a / b : op == OP_SQRT ? sqrt(a) : a * b;
            memcpy(&hb, (const void *)&c, 8);
        } else {
            volatile float a, b = 0, c;
            uint32_t xb32 = (uint32_t)xb, yb32 = (uint32_t)yb, hb32;
            memcpy((void *)&a, &xb32, 4);
            memcpy((void *)&b, &yb32, 4);
            c = op == OP_DIV ? a / b : op == OP_SQRT ? sqrtf(a) : a * b;
            memcpy(&hb32, (const void *)&c, 4);
            hb = hb32;
        }
        ex = fetestexcept(FE_ALL_EXCEPT);
        if (!(hb == zb || (is_nan_bits(hb, dbl) && is_nan_bits(zb, dbl))))
            vmis[op][dbl]++;
        if (fe_to_cft(ex) != fl)
            fmis[op][dbl]++;
    }
}

/* ---- UCBTEST's names for them -------------------------------------- */

void testdivs_(float *z, float *x, float *y)    { call(OP_DIV, 0, z, x, y); }
void testdivd_(double *z, double *x, double *y) { call(OP_DIV, 1, z, x, y); }
void testsqrts_(float *z, float *x)             { call(OP_SQRT, 0, z, x, NULL); }
void testsqrtd_(double *z, double *x)           { call(OP_SQRT, 1, z, x, NULL); }
void testmuls_(float *z, float *x, float *y)    { call(OP_MUL, 0, z, x, y); }
void testmuld_(double *z, double *x, double *y) { call(OP_MUL, 1, z, x, y); }

/* The exact helpers ucbmultest's judge calls through the same interface
 * (abs, ceil, floor and fmod: each is exact in every rounding attribute).
 * They are the HOST's libm on purpose: they are the judge's tools, not the
 * arithmetic under test, and a judge that asked the subject for its own
 * verdict's ingredients would prove nothing. */
void testabss_(float *z, float *x)            { *z = fabsf(*x); }
void testabsd_(double *z, double *x)          { *z = fabs(*x); }
void testceils_(float *z, float *x)           { *z = ceilf(*x); }
void testceild_(double *z, double *x)         { *z = ceil(*x); }
void testfloors_(float *z, float *x)          { *z = floorf(*x); }
void testfloord_(double *z, double *x)        { *z = floor(*x); }
void testmods_(float *z, float *x, float *y)  { *z = fmodf(*x, *y); }
void testmodd_(double *z, double *x, double *y) { *z = fmod(*x, *y); }

/* the significand width UCBTEST asks of the arithmetic under test */
void testsignifs_(int *n) { *n = 24; }
void testsignifd_(int *n) { *n = 53; }

/* The platform glue UCBTEST's ucbtest/ieee.c would give, written for this
 * platform instead of compiled from it: ieee.c's C99 branch (__FPCE_IEEE__)
 * reports that it cannot change the rounding precision and stops the run,
 * but an x86-64 SSE2 host has no precision to set (binary32 and binary64
 * arithmetic is exactly that wide), and the arithmetic under test here is
 * libcft's. So
 * the rounding direction is fesetround, which the call() above reads back,
 * and the precision functions do nothing. */
void round_nearest(void)     { fesetround(FE_TONEAREST); }
void round_positive(void)    { fesetround(FE_UPWARD); }
void round_zero(void)        { fesetround(FE_TOWARDZERO); }
void generic_precision(void) { }
void default_precision(void) { }
void retrospective(void)     { }
