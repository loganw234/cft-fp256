/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-bench-peers - the software backend priced against the libraries
 * people already use.
 *
 *   ./cft-bench-peers                  all four formats
 *   ./cft-bench-peers -f fp128         one format
 *   ./cft-bench-peers -n 8192 -t 0.5   working set / measurement length
 *   ./cft-bench-peers --csv            machine-readable
 *
 * cft-bench answers "what does width cost inside this library"; this
 * tool answers the question a prospective user asks right after: "and
 * how does that price compare to what I could already run?" The peers
 * are the honest ones for each rung:
 *
 *   mpfr      GNU MPFR at the format's exact precision (24/53/113/237
 *             bits), default exponent range - MPFR used the way MPFR
 *             users use it. This is the library the world treats as
 *             the reference for correctly-rounded arbitrary precision,
 *             and the same code this repo employs as its third oracle.
 *   mpfr+754  MPFR emulating the BINARY FORMAT, by its own manual's
 *             recipe: exponent range narrowed to the format, then
 *             mpfr_check_range + mpfr_subnormalize on every result.
 *             This is what a drop-in replacement for fp128/fp256
 *             semantics actually costs in MPFR - the apples-to-apples
 *             row - though it still keeps no NaN payloads and no
 *             signaling NaNs, which the contract does.
 *   quadmath  gcc's __float128 (fp128 only): compiler-emitted libgcc
 *             soft-float plus libquadmath's fmaq/sqrtq. The common way
 *             an x86 program gets binary128 today.
 *   cpu-hw    the CPU's own float/double (fp32/fp64 only). Not a peer
 *             a software library can beat - it is the ceiling, printed
 *             so the cost of leaving silicon is visible.
 *
 * Call shape is part of the price and is deliberately NOT normalised
 * away: libcft is timed through its batch entry points (one call per
 * pass, n elements), MPFR and __float128 through a per-element loop -
 * because that is how each is actually used. Amortised dispatch is a
 * real advantage of a batch ABI and pretending otherwise would be its
 * own distortion; the doc that quotes these numbers says so.
 *
 * Operands are the same stream cft-bench times: normal numbers, full
 * random significand, exponent within +/-8 of the bias - the fast-path
 * cost of a realistic element, nothing falling into subnormal, inf or
 * NaN early-outs. That choice buys a second property: every result is
 * a normal number comfortably inside every format's range, so every
 * correctly-rounding implementation here must produce IDENTICAL BITS
 * under round-to-nearest-even. The tool checks that, element by
 * element, and prints it per row: a timing whose "agree" column is
 * full is proof the row timed the same work, not a lookalike.
 *
 * What this is not: it is not the validation - docs/VALIDATION.md's
 * MPFR campaign (24.9M cases, all modes, flags derived independently)
 * owns correctness, and this tool's agreement check would pass a
 * library that was wrong about everything these operands avoid. It is
 * not the tile either: the software backend exists so the contract
 * runs anywhere; the card is where speed comes from. And cft_div /
 * cft_sqrt are priced at their documented shape - a fixed sequence of
 * ~25-30 opcode passes per element, the price of correct rounding
 * composed from FMA - so expect their rows to sit that far above the
 * single-pass ops. That is the route's cost on every conforming
 * implementation of it, not overhead looking for a fix.
 *
 * Build (needs the pinned oracle prefix; see verify/build-mpfr-oracle.sh):
 *
 *   make -C host cft-bench-peers CFLAGS="-O2 -I$PREFIX/include" \
 *                                LDLIBS="-L$PREFIX/lib"
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 199309L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#include <gmp.h>
#include <mpfr.h>

#include "cft.h"

#if defined(__GNUC__) && defined(__SIZEOF_FLOAT128__) && !defined(_WIN32)
#  include <quadmath.h>
#  define HAVE_QUAD 1
__extension__ typedef __float128 f128;
#else
#  define HAVE_QUAD 0
#endif

#if defined(_WIN32)
#  include <windows.h>
static double now_s(void)
{
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}
#else
#  include <time.h>
static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}
#endif

/* ---- formats (same table as mpfr_check.c) ------------------------- */

typedef struct {
    const char *name;
    cft_format fmt;
    int exp_w, man_w;
    int p;
    long emax, emin;
    size_t esz;
} fdesc;

static const fdesc FMTS[4] = {
    { "fp32",  CFT_FP32,   8,  23,  24,    127,    -126,  4 },
    { "fp64",  CFT_FP64,  11,  52,  53,   1023,   -1022,  8 },
    { "fp128", CFT_FP128, 15, 112, 113,  16383,  -16382, 16 },
    { "fp256", CFT_FP256, 19, 236, 237, 262143, -262142, 32 },
};

/* ---- operand generation (same generator, same seed as cft-bench,
 * so the two tools time the same stream) ---------------------------- */

static void put_bits(unsigned char *e, int lo, int nbits, uint64_t val)
{
    int i;
    for (i = 0; i < nbits; i++) {
        int b = lo + i;
        unsigned char m = (unsigned char)(1u << (b & 7));
        if ((val >> i) & 1u) e[b >> 3] |= m;
        else                 e[b >> 3] = (unsigned char)(e[b >> 3] & ~m);
    }
}

static uint64_t rng_state = 0x243f6a8885a308d3ull;
static uint64_t rng_next(void)
{
    uint64_t x = rng_state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    rng_state = x;
    return x * 0x2545f4914f6cdd1dull;
}

static void fill(unsigned char *buf, const fdesc *f, size_t n, int spread)
{
    int total = 1 + f->exp_w + f->man_w;
    uint64_t bias = ((uint64_t)1 << (f->exp_w - 1)) - 1;
    size_t i, j;

    for (i = 0; i < n; i++) {
        unsigned char *e = buf + i * f->esz;
        for (j = 0; j < f->esz; j += 8) {
            uint64_t r = rng_next();
            size_t k, lim = (f->esz - j < 8) ? f->esz - j : 8;
            for (k = 0; k < lim; k++) e[j + k] = (unsigned char)(r >> (k * 8));
        }
        {
            uint64_t off = rng_next() % (uint64_t)(2 * spread + 1);
            put_bits(e, f->man_w, f->exp_w, bias + off - (uint64_t)spread);
        }
        put_bits(e, total - 1, 1, rng_next() & 1u);
    }
}

/* ---- encoding -> mpfr (exact; same code as mpfr_check.c) ---------- */

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

static int mpfr_same(const mpfr_t x, const mpfr_t y)
{
    if (mpfr_nan_p(x) || mpfr_nan_p(y))
        return mpfr_nan_p(x) && mpfr_nan_p(y);
    if (mpfr_zero_p(x) && mpfr_zero_p(y))
        return mpfr_signbit(x) == mpfr_signbit(y);
    return mpfr_equal_p(x, y) != 0;
}

/* ---- the passes ---------------------------------------------------
 * One pass = the whole n-element working set, once. The timing loop
 * below calls a pass repeatedly through a function pointer, which is
 * also the wall that stops the compiler hoisting the cpu-hw loops out
 * of the repetition. */

enum { B_ADD, B_MUL, B_FMA, B_DIV, B_SQRT, NBOPS };
static const char *const BOPN[NBOPS] = { "add", "mul", "fma", "div", "sqrt" };

struct ctx {
    const fdesc *f;
    size_t n;
    cft_device *dev;
    /* byte encodings: a, b, c random; ap = a with the sign cleared */
    unsigned char *a, *b, *c, *ap, *d;
    /* mpfr mirrors of the same operands, plus the result array */
    mpfr_t *A, *B, *C, *Ap, *R;
    int use_754;               /* check_range + subnormalize per op */
#if HAVE_QUAD
    f128 *qa, *qb, *qc, *qap, *qr;
#endif
    float  *fa, *fb, *fc, *fap, *fr;
    double *da, *db, *dc, *dap, *dr;
};

typedef void (*pass_fn)(struct ctx *, int op);

static void pass_cft(struct ctx *x, int op)
{
    uint32_t fl;
    cft_status st = CFT_OK;
    switch (op) {
    case B_ADD:  st = cft_run(x->dev, CFT_ADD, x->f->fmt, CFT_RNE,
                              x->a, x->b, x->c, x->d, x->n, &fl, NULL); break;
    case B_MUL:  st = cft_run(x->dev, CFT_MUL, x->f->fmt, CFT_RNE,
                              x->a, x->b, x->c, x->d, x->n, &fl, NULL); break;
    case B_FMA:  st = cft_run(x->dev, CFT_FMA, x->f->fmt, CFT_RNE,
                              x->a, x->b, x->c, x->d, x->n, &fl, NULL); break;
    case B_DIV:  st = cft_div(x->dev, x->f->fmt, CFT_RNE,
                              x->a, x->b, x->d, x->n, &fl, NULL); break;
    case B_SQRT: st = cft_sqrt(x->dev, x->f->fmt, CFT_RNE,
                               x->ap, x->d, x->n, &fl, NULL); break;
    }
    if (st != CFT_OK) {
        fprintf(stderr, "libcft %s %s: %s\n  %s\n", x->f->name, BOPN[op],
                cft_strerror(st), cft_last_error());
        exit(1);
    }
}

static void pass_mpfr(struct ctx *x, int op)
{
    size_t i;
    for (i = 0; i < x->n; i++) {
        int t = 0;
        switch (op) {
        case B_ADD:  t = mpfr_add(x->R[i], x->A[i], x->C[i], MPFR_RNDN); break;
        case B_MUL:  t = mpfr_mul(x->R[i], x->A[i], x->B[i], MPFR_RNDN); break;
        case B_FMA:  t = mpfr_fma(x->R[i], x->A[i], x->B[i], x->C[i],
                                  MPFR_RNDN); break;
        case B_DIV:  t = mpfr_div(x->R[i], x->A[i], x->B[i], MPFR_RNDN); break;
        case B_SQRT: t = mpfr_sqrt(x->R[i], x->Ap[i], MPFR_RNDN); break;
        }
        if (x->use_754) {
            t = mpfr_check_range(x->R[i], t, MPFR_RNDN);
            mpfr_subnormalize(x->R[i], t, MPFR_RNDN);
        }
    }
}

#if HAVE_QUAD
static void pass_quad(struct ctx *x, int op)
{
    size_t i, n = x->n;
    switch (op) {
    case B_ADD:  for (i = 0; i < n; i++) x->qr[i] = x->qa[i] + x->qc[i]; break;
    case B_MUL:  for (i = 0; i < n; i++) x->qr[i] = x->qa[i] * x->qb[i]; break;
    case B_FMA:  for (i = 0; i < n; i++)
                     x->qr[i] = fmaq(x->qa[i], x->qb[i], x->qc[i]);      break;
    case B_DIV:  for (i = 0; i < n; i++) x->qr[i] = x->qa[i] / x->qb[i]; break;
    case B_SQRT: for (i = 0; i < n; i++) x->qr[i] = sqrtq(x->qap[i]);    break;
    }
}
#endif

static void pass_hw32(struct ctx *x, int op)
{
    size_t i, n = x->n;
    switch (op) {
    case B_ADD:  for (i = 0; i < n; i++) x->fr[i] = x->fa[i] + x->fc[i]; break;
    case B_MUL:  for (i = 0; i < n; i++) x->fr[i] = x->fa[i] * x->fb[i]; break;
    case B_FMA:  for (i = 0; i < n; i++)
                     x->fr[i] = fmaf(x->fa[i], x->fb[i], x->fc[i]);      break;
    case B_DIV:  for (i = 0; i < n; i++) x->fr[i] = x->fa[i] / x->fb[i]; break;
    case B_SQRT: for (i = 0; i < n; i++) x->fr[i] = sqrtf(x->fap[i]);    break;
    }
}

static void pass_hw64(struct ctx *x, int op)
{
    size_t i, n = x->n;
    switch (op) {
    case B_ADD:  for (i = 0; i < n; i++) x->dr[i] = x->da[i] + x->dc[i]; break;
    case B_MUL:  for (i = 0; i < n; i++) x->dr[i] = x->da[i] * x->db[i]; break;
    case B_FMA:  for (i = 0; i < n; i++)
                     x->dr[i] = fma(x->da[i], x->db[i], x->dc[i]);       break;
    case B_DIV:  for (i = 0; i < n; i++) x->dr[i] = x->da[i] / x->db[i]; break;
    case B_SQRT: for (i = 0; i < n; i++) x->dr[i] = sqrt(x->dap[i]);     break;
    }
}

/* ---- timing (same auto-repetition discipline as cft-bench) -------- */

struct meas { double ns_per_elem; double elems_per_s; int reps; double s; };

static struct meas time_pass(pass_fn fn, struct ctx *x, int op,
                             double target_s)
{
    struct meas m;
    double t0, t1, elapsed;
    int reps = 1, i;

    fn(x, op);                       /* one untimed warm pass */
    for (;;) {
        t0 = now_s();
        for (i = 0; i < reps; i++) fn(x, op);
        t1 = now_s();
        elapsed = t1 - t0;
        if (elapsed >= target_s || reps >= (1 << 20)) break;
        if (elapsed <= 0.0) { reps *= 16; continue; }
        {
            double grow = target_s / elapsed * 1.25;
            int next = (grow > 64.0) ? reps * 64 : (int)((double)reps * grow) + 1;
            if (next <= reps) next = reps + 1;
            reps = next;
        }
    }
    m.reps = reps;
    m.s = elapsed;
    m.elems_per_s = (double)x->n * (double)reps / elapsed;
    m.ns_per_elem = elapsed * 1e9 / ((double)x->n * (double)reps);
    return m;
}

/* ---- agreement against the libcft bytes --------------------------- */

static size_t agree_bytes(const unsigned char *ref, const void *out,
                          size_t n, size_t esz)
{
    size_t i, ok = 0;
    const unsigned char *o = (const unsigned char *)out;
    for (i = 0; i < n; i++)
        if (!memcmp(ref + i * esz, o + i * esz, esz)) ok++;
    return ok;
}

static size_t agree_mpfr(struct ctx *x, const unsigned char *ref)
{
    size_t i, ok = 0;
    mpfr_t t;
    mpfr_init2(t, (mpfr_prec_t)x->f->p);
    for (i = 0; i < x->n; i++) {
        enc_to_mpfr(x->f, ref + i * x->f->esz, t);
        if (mpfr_same(t, x->R[i])) ok++;
    }
    mpfr_clear(t);
    return ok;
}

/* ---- reporting ----------------------------------------------------- */

static int g_csv;

static void report(const fdesc *f, const char *impl, int op,
                   struct meas m, double cft_ns, size_t ok, size_t n,
                   int is_ref)
{
    if (g_csv) {
        printf("%s,%s,%s,%.4f,%.0f,%.3f,%lu,%lu,%d,%.4f\n",
               f->name, impl, BOPN[op], m.ns_per_elem, m.elems_per_s,
               m.ns_per_elem / cft_ns, (unsigned long)ok, (unsigned long)n,
               m.reps, m.s);
    } else {
        char agr[32];
        if (is_ref)             snprintf(agr, sizeof agr, "ref");
        else if (ok == n)       snprintf(agr, sizeof agr, "agree");
        else                    snprintf(agr, sizeof agr, "DIFF %lu/%lu",
                                         (unsigned long)(n - ok),
                                         (unsigned long)n);
        printf("  %-6s %-9s %12.2f %12.3f %9.3fx   %s\n",
               BOPN[op], impl, m.ns_per_elem, m.elems_per_s / 1e6,
               m.ns_per_elem / cft_ns, agr);
    }
}

int main(int argc, char **argv)
{
    size_t n = 4096;
    double target_s = 0.35;
    int only_fmt = -1, spread = 8, argi, fi, op;
    cft_device *dev = NULL;
    cft_status st;
    mpfr_exp_t def_emin, def_emax;

    for (argi = 1; argi < argc; argi++) {
        if (!strcmp(argv[argi], "-n") && argi + 1 < argc) {
            n = (size_t)strtoul(argv[++argi], NULL, 10);
        } else if (!strcmp(argv[argi], "-t") && argi + 1 < argc) {
            target_s = strtod(argv[++argi], NULL);
        } else if (!strcmp(argv[argi], "-s") && argi + 1 < argc) {
            spread = (int)strtol(argv[++argi], NULL, 10);
        } else if (!strcmp(argv[argi], "--csv")) {
            g_csv = 1;
        } else if (!strcmp(argv[argi], "-f") && argi + 1 < argc) {
            const char *want = argv[++argi];
            int i;
            for (i = 0; i < 4; i++)
                if (!strcmp(want, FMTS[i].name)) only_fmt = i;
            if (only_fmt < 0) {
                fprintf(stderr, "unknown format %s\n", want);
                return 2;
            }
        } else {
            fprintf(stderr, "usage: %s [-n elements] [-t seconds] "
                    "[-f fmt] [-s spread] [--csv]\n", argv[0]);
            return 2;
        }
    }
    if (n == 0) { fprintf(stderr, "-n must be positive\n"); return 2; }

    st = cft_open(NULL, 0, &dev);   /* the software backend, always */
    if (st != CFT_OK) {
        fprintf(stderr, "cft_open: %s\n  %s\n", cft_strerror(st),
                cft_last_error());
        return 2;
    }

    def_emin = mpfr_get_emin();
    def_emax = mpfr_get_emax();

    if (g_csv)
        printf("format,impl,op,ns_per_elem,elems_per_s,rel_time,"
               "agree,n,reps,seconds\n");
    else {
        printf("cft-bench-peers: software backend vs MPFR %s"
               " / __float128 / native CPU\n", mpfr_get_version());
        printf("%lu elements per pass, >=%.2gs per measurement, exponent "
               "spread +/-%d, RNE\nrel = time relative to libcft "
               "(smaller is faster)\n\n", (unsigned long)n, target_s,
               spread);
    }

    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        struct ctx x;
        unsigned char *ref[NBOPS];
        double cft_ns[NBOPS];
        size_t i;

        if (only_fmt >= 0 && fi != only_fmt) continue;

        memset(&x, 0, sizeof x);
        x.f = f; x.n = n; x.dev = dev;
        x.a  = malloc(n * f->esz);
        x.b  = malloc(n * f->esz);
        x.c  = malloc(n * f->esz);
        x.ap = malloc(n * f->esz);
        x.d  = malloc(n * f->esz);
        if (!x.a || !x.b || !x.c || !x.ap || !x.d) {
            fprintf(stderr, "out of memory\n"); return 2;
        }
        fill(x.a, f, n, spread);
        fill(x.b, f, n, spread);
        fill(x.c, f, n, spread);
        memcpy(x.ap, x.a, n * f->esz);
        for (i = 0; i < n; i++)
            put_bits(x.ap + i * f->esz, 1 + f->exp_w + f->man_w - 1, 1, 0);

        /* mpfr mirrors, converted exactly while the range is still the
         * library default */
        x.A  = malloc(n * sizeof(mpfr_t));
        x.B  = malloc(n * sizeof(mpfr_t));
        x.C  = malloc(n * sizeof(mpfr_t));
        x.Ap = malloc(n * sizeof(mpfr_t));
        x.R  = malloc(n * sizeof(mpfr_t));
        if (!x.A || !x.B || !x.C || !x.Ap || !x.R) {
            fprintf(stderr, "out of memory\n"); return 2;
        }
        for (i = 0; i < n; i++) {
            mpfr_init2(x.A[i],  (mpfr_prec_t)f->p);
            mpfr_init2(x.B[i],  (mpfr_prec_t)f->p);
            mpfr_init2(x.C[i],  (mpfr_prec_t)f->p);
            mpfr_init2(x.Ap[i], (mpfr_prec_t)f->p);
            mpfr_init2(x.R[i],  (mpfr_prec_t)f->p);
            enc_to_mpfr(f, x.a  + i * f->esz, x.A[i]);
            enc_to_mpfr(f, x.b  + i * f->esz, x.B[i]);
            enc_to_mpfr(f, x.c  + i * f->esz, x.C[i]);
            enc_to_mpfr(f, x.ap + i * f->esz, x.Ap[i]);
        }

#if HAVE_QUAD
        if (f->fmt == CFT_FP128) {
            x.qa  = malloc(n * sizeof(f128));
            x.qb  = malloc(n * sizeof(f128));
            x.qc  = malloc(n * sizeof(f128));
            x.qap = malloc(n * sizeof(f128));
            x.qr  = malloc(n * sizeof(f128));
            memcpy(x.qa,  x.a,  n * 16);
            memcpy(x.qb,  x.b,  n * 16);
            memcpy(x.qc,  x.c,  n * 16);
            memcpy(x.qap, x.ap, n * 16);
        }
#endif
        if (f->fmt == CFT_FP32) {
            x.fa  = malloc(n * sizeof(float));
            x.fb  = malloc(n * sizeof(float));
            x.fc  = malloc(n * sizeof(float));
            x.fap = malloc(n * sizeof(float));
            x.fr  = malloc(n * sizeof(float));
            memcpy(x.fa,  x.a,  n * 4);
            memcpy(x.fb,  x.b,  n * 4);
            memcpy(x.fc,  x.c,  n * 4);
            memcpy(x.fap, x.ap, n * 4);
        }
        if (f->fmt == CFT_FP64) {
            x.da  = malloc(n * sizeof(double));
            x.db  = malloc(n * sizeof(double));
            x.dc  = malloc(n * sizeof(double));
            x.dap = malloc(n * sizeof(double));
            x.dr  = malloc(n * sizeof(double));
            memcpy(x.da,  x.a,  n * 8);
            memcpy(x.db,  x.b,  n * 8);
            memcpy(x.dc,  x.c,  n * 8);
            memcpy(x.dap, x.ap, n * 8);
        }

        if (!g_csv)
            printf("%s (%lu B/elem, precision %d)\n  %-6s %-9s %12s %12s "
                   "%10s   %s\n", f->name, (unsigned long)f->esz, f->p,
                   "op", "impl", "ns/elem", "Melem/s", "rel", "agree");

        for (op = 0; op < NBOPS; op++) {
            struct meas m;
            size_t ok;

            /* libcft is the reference row: timed first, bytes kept */
            m = time_pass(pass_cft, &x, op, target_s);
            cft_ns[op] = m.ns_per_elem;
            ref[op] = malloc(n * f->esz);
            memcpy(ref[op], x.d, n * f->esz);
            report(f, "libcft", op, m, cft_ns[op], n, n, 1);

            x.use_754 = 0;
            m = time_pass(pass_mpfr, &x, op, target_s);
            ok = agree_mpfr(&x, ref[op]);
            report(f, "mpfr", op, m, cft_ns[op], ok, n, 0);

            mpfr_set_emin((mpfr_exp_t)(f->emin - f->p + 2));
            mpfr_set_emax((mpfr_exp_t)(f->emax + 1));
            x.use_754 = 1;
            m = time_pass(pass_mpfr, &x, op, target_s);
            ok = agree_mpfr(&x, ref[op]);
            mpfr_set_emin(def_emin);
            mpfr_set_emax(def_emax);
            report(f, "mpfr+754", op, m, cft_ns[op], ok, n, 0);

#if HAVE_QUAD
            if (f->fmt == CFT_FP128) {
                m = time_pass(pass_quad, &x, op, target_s);
                ok = agree_bytes(ref[op], x.qr, n, 16);
                report(f, "quadmath", op, m, cft_ns[op], ok, n, 0);
            }
#endif
            if (f->fmt == CFT_FP32) {
                m = time_pass(pass_hw32, &x, op, target_s);
                ok = agree_bytes(ref[op], x.fr, n, 4);
                report(f, "cpu-hw", op, m, cft_ns[op], ok, n, 0);
            }
            if (f->fmt == CFT_FP64) {
                m = time_pass(pass_hw64, &x, op, target_s);
                ok = agree_bytes(ref[op], x.dr, n, 8);
                report(f, "cpu-hw", op, m, cft_ns[op], ok, n, 0);
            }
        }
        if (!g_csv) printf("\n");

        for (op = 0; op < NBOPS; op++) free(ref[op]);
        for (i = 0; i < n; i++) {
            mpfr_clear(x.A[i]);  mpfr_clear(x.B[i]); mpfr_clear(x.C[i]);
            mpfr_clear(x.Ap[i]); mpfr_clear(x.R[i]);
        }
        free(x.A); free(x.B); free(x.C); free(x.Ap); free(x.R);
        free(x.a); free(x.b); free(x.c); free(x.ap); free(x.d);
#if HAVE_QUAD
        free(x.qa); free(x.qb); free(x.qc); free(x.qap); free(x.qr);
#endif
        free(x.fa); free(x.fb); free(x.fc); free(x.fap); free(x.fr);
        free(x.da); free(x.db); free(x.dc); free(x.dap); free(x.dr);
    }

    mpfr_free_cache();
    cft_close(dev);
    return 0;
}
