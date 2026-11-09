/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * routine-sweep - every argument of a routine, by name, run through libcft as the compiled program and compared in bits and
 * flags with MPFR (parcel M4X, 2026-11-09). Fp32's bound has no budget (docs/ROADMAP.md, Logan's answer 3 on M4's study): its
 * evidence is the box's samples and an exhaustive sweep of the 2^32 arguments of each function. This is the tool that sweeps,
 * in the soaks' form (host/tools/divsqrt_soak.c): a slice [lo, hi) of the encodings, a verdict line, the first sixteen
 * disagreements shown, the backend chosen by CFT_SOAK_ARTIFACT (unset: the software backend, which is the CPU fallback), so that
 * the card can run it slice by slice.
 *
 *   routine-sweep <op> <lo> <hi> <rne|rtz|rdn|rup|rmm|all>
 *   routine-sweep oracle <op> <rne|rtz|rdn|rup|rmm>      hex lanes on stdin, "lane result flags" a line each out; no device, no image
 *   routine-sweep list                                   the thirteen, each with its images found or `no image`
 *
 * op is <name>-f32 for exp, exp2, expm1, log, log2, log1p, sin, cos, tan, atan, asin and acos, and atan2-f32-x<8 hex digits> for
 * atan2 with x fixed and y swept (r0 the lanes' y, r1 the fixed x). Any op may end -d<8 hex digits>, the first 32 bits of the
 * sha256 of the five attributes' image and bank bytes, rne to rmm (image then bank, each attribute): a digest that is not the
 * images' is exit 2, which is how a slice is tied to the fragment it ran. [lo, hi) is 0 <= lo < hi <= 2^32, decimal or 0x; a
 * slice is any part of the space and a run keeps no state.
 *
 * THE IMAGES are the compiled shape of the routine's fragment (python/tests/mathlib_harness.r24_program), written by
 * host/tools/gen_sweep_images.py as <name>-fp32-<attr>.cftp (the program), .bank (its constants) and .marks (the lanes that must
 * mark, one hex word a line). They are read from CFT_SWEEP_IMAGES, else from sweep-images/ beside the binary. A missing or
 * unreadable file, a load the device refuses, or a bank that is not the program's n_consts words is exit 2, naming the file and
 * cft_last_error(). Atan, asin, acos and atan2 have an image only once parcels M4F1 and M4F2 are merged.
 *
 * A CALL is L lanes (16384, -DLANES=n at build, CFT_SWEEP_LANES at run), consecutive encodings in stream a and, for atan2, x in
 * stream b: one cft_program_run_ex a call, with lane_flags, counts, flags_out and bus_out all asked for. Each lane is judged
 * against ieee_tfn_oracle (host/tools/mpfr_tfn.h, mpfr-check's own):
 *   unmarked   its bits are the oracle's (a NaN is the canonical quiet NaN, 0x7fc00000, which MPFR compares only as a class and
 *              the contract's row fixes, so it is checked here) and its byte's [4:0] are the oracle's flags;
 *   marked     (byte bit 7: R24's mark, a lane whose last bit the routine's own test could not decide, to be replayed) counted,
 *              and its guess compared in value and flags. A wrong guess is counted and named and does NOT fail the slice: the
 *              replay decides a marked lane;
 *   a lane on the image's .marks list that is not marked is a flag mismatch, named; a mark not on the list is counted as "off
 *   the list", named, and fails nothing - the first sweeps are what find them.
 * Each call is held as mathlib_harness.check_r24 holds one: the OR of the bytes' [4:0] is flags_out; STATUS[6] is set exactly
 * when a byte's bit 7 is; no byte has [6:5]; every count is 1; STATUS has no other bit. A failure is a flag mismatch, named by
 * the call's range.
 *
 * THE WORD all runs the five attributes in one job: the five images loaded once, each call run five times, and each lane
 * evaluated once. The fast path is y = f(x) truncated to p + 1 bits by RNDZ with its ternary t at MPFR's widest exponents (the
 * construction rmm_round already rests on): where y is a number, t is not zero, MPFR's overflow and underflow flags are clear and
 * 2^-125 <= |y| < 2^127, every attribute's answer follows from y's last kept bit and its sign, the flags are exactly inexact, and
 * no tie is possible. Every other lane (every exact, special, subnormal or overflowing one) takes ieee_tfn_oracle under each
 * attribute. CFT_SWEEP_ORACLE_CHECK=N (4096 by default; 1 checks every lane; encodings that are multiples of N, so slices
 * compose) runs ieee_tfn_oracle beside the fast path, and a difference is a value mismatch named ORACLE.
 *
 * Output. stdout: the verdict, which hw/card_stress_lib.py's SOAK_LINE matches and no other line does,
 *     <op> <mode>: N cases, V value mismatches, F flag mismatches, E encodings, 0 skipped
 * (E = hi - lo; N = E, or 5 E under all), then
 *     <op> <mode>: M marked (rne a, rtz b, rdn c, rup d, rmm e), O off the list, W guesses wrong     (an attribute not run: -)
 * and the lines "  MISMATCH <mode> a=0x.. lib=0x.. mpfr=0x..", "  FLAGS <mode> a=0x.. lib=0x.. mpfr=0x.." and
 * "  MARK <mode> a=0x.. guess=0x.. right|WRONG", sixteen of each kind at most. stderr: the backend line the soaks print, word
 * for word; "oracle: MPFR <v> with GMP <v>, mpfr_ieee.h's emulation"; "image <name> <attr>: sha256 <image and bank>, I
 * instructions, K words" for each image; and "<op> <mode>: device S s, oracle S s, L lanes a call". Exit 0 when V and F are
 * zero, 1 when not (and after "  library call failed", as the soaks), 2 for a usage, image, open or load failure, with no
 * verdict.
 *
 * Negative controls, after the library computes (CFT_SOAK_SABOTAGE; each must exit 1): =1 flips the low bit of the first
 * unmarked lane's result of every call; =2 flips a flag bit of that lane's byte; =3 clears bit 7 of every byte, which only the
 * call's STATUS check can see (and which does nothing, and says so on stderr, in a slice with no marked lane).
 */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#  define _POSIX_C_SOURCE 200112L
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#  include <windows.h>
#endif

#include <gmp.h>
#include <mpfr.h>

#include "../include/cft.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-const-variable"
#include "mpfr_tfn.h"
#pragma GCC diagnostic pop

#ifndef LANES
#define LANES 16384
#endif
#define MAXLANES (1u << 24)
#define SHOW 16

static const fdesc F32 = { "fp32", CFT_FP32, 8, 23, 24, 127, -126, 4 };
#define QNAN32 0x7fc00000u

typedef struct { const char *name; int fn; } rtn;
static const rtn RTNS[13] = {
    { "exp", TF_EXP }, { "exp2", TF_EXP2 }, { "expm1", TF_EXPM1 }, { "log", TF_LOG }, { "log2", TF_LOG2 },
    { "log1p", TF_LOG1P }, { "sin", TF_SIN }, { "cos", TF_COS }, { "tan", TF_TAN }, { "atan", TF_ATAN },
    { "asin", TF_ASIN }, { "acos", TF_ACOS }, { "atan2", TF_ATAN2 },
};
static const struct { const char *name; mpfr_rnd_t mr; int rmm; } ATT[5] = {
    { "rne", MPFR_RNDN, 0 }, { "rtz", MPFR_RNDZ, 0 }, { "rdn", MPFR_RNDD, 0 }, { "rup", MPFR_RNDU, 0 },
    { "rmm", MPFR_RNDN, 1 },
};

static cft_device *dev;
static uint64_t cases, vmis, fmis, nmarked[5], off_list, wrong_guess;
static int shown_m, shown_f, shown_k;
static int sabotage;                       /* 0, or CFT_SOAK_SABOTAGE's 1, 2 or 3 */
static uint64_t sab3_cleared;              /* sabotage 3: the marks it cleared */
static double t_device, t_oracle_s;

/* ---- time ---------------------------------------------------------- */
static double now_s(void)
{
#ifdef _WIN32
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
#endif
}

/* ---- parsing ------------------------------------------------------- */

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* A non-negative number, decimal or 0x hex, the whole string, no sign, no space, no overflow of 64 bits. */
static int parse_u64(const char *s, uint64_t *out)
{
    uint64_t v = 0;
    unsigned base = 10;
    if (!s || !*s)
        return 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        base = 16;
        s += 2;
        if (!*s)
            return 0;
    }
    for (; *s; s++) {
        int d = hexval((unsigned char)*s);
        if (d < 0 || (unsigned)d >= base)
            return 0;
        if (v > (UINT64_MAX - (uint64_t)d) / base)
            return 0;
        v = v * base + (uint64_t)d;
    }
    *out = v;
    return 1;
}

/* Exactly eight hex digits. */
static int parse_hex8(const char *s, uint32_t *out)
{
    uint32_t v = 0;
    int i;
    for (i = 0; i < 8; i++) {
        int d = hexval((unsigned char)s[i]);
        if (d < 0)
            return 0;
        v = (v << 4) | (uint32_t)d;
    }
    if (s[8])
        return 0;
    *out = v;
    return 1;
}

typedef struct { int ri; int has_x; uint32_t x; int has_d; uint32_t d; } opspec;

/* <name>-f32[-x<8 hex>][-d<8 hex>]; x belongs to atan2 and atan2 requires it. 0 and a message on failure. */
static int parse_op(const char *s, opspec *o, const char **why)
{
    size_t k, nl;
    const char *rest = NULL;
    memset(o, 0, sizeof *o);
    o->ri = -1;
    for (k = 0; k < 13; k++) {
        nl = strlen(RTNS[k].name);
        if (!strncmp(s, RTNS[k].name, nl) && !strncmp(s + nl, "-f32", 4) &&
            (s[nl + 4] == 0 || s[nl + 4] == '-')) {
            o->ri = (int)k;
            rest = s + nl + 4;
            break;
        }
    }
    if (o->ri < 0) {
        *why = "unknown op (the thirteen are exp exp2 expm1 log log2 log1p sin cos tan atan asin acos atan2, each as <name>-f32)";
        return 0;
    }
    /* walk the suffixes by hand: -x<8> then -d<8> */
    rest = s + strlen(RTNS[o->ri].name) + 4;
    while (*rest) {
        char buf[9];
        uint32_t v;
        if (rest[0] != '-' || (rest[1] != 'x' && rest[1] != 'd')) {
            *why = "bad suffix (after <name>-f32 only -x<8 hex digits> and -d<8 hex digits> may follow)";
            return 0;
        }
        if (strlen(rest) < 10) {
            *why = "a -x or -d word is exactly eight hex digits";
            return 0;
        }
        memcpy(buf, rest + 2, 8);
        buf[8] = 0;
        if (!parse_hex8(buf, &v)) {
            *why = "a -x or -d word is exactly eight hex digits";
            return 0;
        }
        if (rest[1] == 'x') {
            if (o->has_x || o->has_d) {
                *why = "-x is given once, before -d";
                return 0;
            }
            o->has_x = 1;
            o->x = v;
        } else {
            if (o->has_d) {
                *why = "-d is given once";
                return 0;
            }
            o->has_d = 1;
            o->d = v;
        }
        rest += 10;
    }
    if (RTNS[o->ri].fn == TF_ATAN2 && !o->has_x) {
        *why = "atan2 takes its fixed x as atan2-f32-x<8 hex digits>";
        return 0;
    }
    if (RTNS[o->ri].fn != TF_ATAN2 && o->has_x) {
        *why = "only atan2 takes -x";
        return 0;
    }
    return 1;
}

static int mode_of(const char *s)
{
    int i;
    for (i = 0; i < 5; i++)
        if (!strcmp(ATT[i].name, s))
            return i;
    return !strcmp(s, "all") ? 5 : -1;
}

/* ---- files --------------------------------------------------------- */

static char imgdir[1024];

static void set_imgdir(const char *argv0)
{
    const char *e = getenv("CFT_SWEEP_IMAGES");
    if (e && *e) {
        snprintf(imgdir, sizeof imgdir, "%s", e);
    } else {
        const char *p = argv0 ? argv0 : "", *last = NULL;
        size_t n;
        for (; *p; p++)
            if (*p == '/' || *p == '\\')
                last = p;
        n = last ? (size_t)(last - argv0) : 0;
        if (n > sizeof imgdir - 20)
            n = sizeof imgdir - 20;
        if (last)
            snprintf(imgdir, sizeof imgdir, "%.*s/sweep-images", (int)n, argv0);
        else
            snprintf(imgdir, sizeof imgdir, "sweep-images");
    }
}

static void path_of(char *buf, size_t n, int ri, int m, const char *ext)
{
    snprintf(buf, n, "%s/%s-fp32-%s.%s", imgdir, RTNS[ri].name, ATT[m].name, ext);
}

/* 0 and *why filled on failure; the buffer is malloc'd (one spare byte). */
static int read_file(const char *path, uint8_t **buf, size_t *n)
{
    FILE *f = fopen(path, "rb");
    size_t cap = 1 << 14, have = 0;
    uint8_t *b;
    if (!f)
        return 0;
    b = (uint8_t *)malloc(cap);
    if (!b) {
        fclose(f);
        return 0;
    }
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *nb = (uint8_t *)realloc(b, cap * 2);
            if (!nb) {
                free(b);
                fclose(f);
                return 0;
            }
            b = nb;
            cap *= 2;
        }
        got = fread(b + have, 1, cap - have, f);
        have += got;
        if (got == 0)
            break;
    }
    fclose(f);
    *buf = b;
    *n = have;
    return 1;
}

typedef struct {
    uint8_t *img, *bank;
    size_t imgn, bankn;
    uint32_t *marks;
    size_t nmarks;
    char sha[65];
    char ipath[1100], bpath[1100];
    cft_program *prog;
    uint32_t ninsn, nwords;
} image;

static void hex_of(const uint8_t *d, size_t n, char *out)
{
    static const char x[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i] = x[d[i] >> 4];
        out[2 * i + 1] = x[d[i] & 15];
    }
    out[2 * n] = 0;
}

static int cmp_u32(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return x < y ? -1 : x > y;
}

/* Read the three files of (routine, attribute). 0 and a message on a missing or bad file. */
static int load_files(int ri, int m, image *im, char *msg, size_t msgn)
{
    char mpath[1100];
    uint8_t *mk = NULL, *cat;
    size_t mkn = 0, i, line = 1;
    uint32_t v = 0;
    int digits = 0;
    uint8_t d32[32];
    memset(im, 0, sizeof *im);
    path_of(im->ipath, sizeof im->ipath, ri, m, "cftp");
    path_of(im->bpath, sizeof im->bpath, ri, m, "bank");
    path_of(mpath, sizeof mpath, ri, m, "marks");
    if (!read_file(im->ipath, &im->img, &im->imgn)) {
        snprintf(msg, msgn, "cannot read %s", im->ipath);
        return 0;
    }
    if (!read_file(im->bpath, &im->bank, &im->bankn)) {
        snprintf(msg, msgn, "cannot read %s", im->bpath);
        return 0;
    }
    if (!read_file(mpath, &mk, &mkn)) {
        snprintf(msg, msgn, "cannot read %s", mpath);
        return 0;
    }
    im->marks = (uint32_t *)malloc((mkn / 2 + 2) * sizeof(uint32_t));
    for (i = 0; i <= mkn; i++) {
        int c = i < mkn ? mk[i] : '\n';
        if (c == '\n' || c == '\r') {
            if (digits)
                im->marks[im->nmarks++] = v;
            v = 0;
            digits = 0;
            if (c == '\n')
                line++;
        } else if (hexval(c) >= 0 && digits < 8) {
            v = (v << 4) | (uint32_t)hexval(c);
            digits++;
        } else {
            snprintf(msg, msgn, "%s line %lu: not a hex lane", mpath, (unsigned long)line);
            free(mk);
            return 0;
        }
    }
    free(mk);
    qsort(im->marks, im->nmarks, sizeof(uint32_t), cmp_u32);
    cat = (uint8_t *)malloc(im->imgn + im->bankn + 1);
    memcpy(cat, im->img, im->imgn);
    memcpy(cat + im->imgn, im->bank, im->bankn);
    cft_sha256(cat, im->imgn + im->bankn, d32);
    free(cat);
    hex_of(d32, 32, im->sha);
    return 1;
}

/* The first 32 bits of the sha256 of the five attributes' image and bank, rne to rmm. */
static uint32_t digest_of(const image im[5])
{
    size_t tot = 0, at = 0;
    int m;
    uint8_t *cat, d32[32];
    for (m = 0; m < 5; m++)
        tot += im[m].imgn + im[m].bankn;
    cat = (uint8_t *)malloc(tot + 1);
    for (m = 0; m < 5; m++) {
        memcpy(cat + at, im[m].img, im[m].imgn);
        at += im[m].imgn;
        memcpy(cat + at, im[m].bank, im[m].bankn);
        at += im[m].bankn;
    }
    cft_sha256(cat, tot, d32);
    free(cat);
    return ((uint32_t)d32[0] << 24) | ((uint32_t)d32[1] << 16) | ((uint32_t)d32[2] << 8) | d32[3];
}

static void free_image(image *im)
{
    if (im->prog)
        cft_program_free(im->prog);
    free(im->img);
    free(im->bank);
    free(im->marks);
    memset(im, 0, sizeof *im);
}

/* ---- the oracle, as bits ------------------------------------------- */

static mpfr_t o_out, o_chk;                /* precision 24 */

static void put32(uint8_t *b, uint32_t v)
{
    b[0] = (uint8_t)v; b[1] = (uint8_t)(v >> 8); b[2] = (uint8_t)(v >> 16); b[3] = (uint8_t)(v >> 24);
}

/* The exact fp32 value in `v` as its encoding; a NaN is the canonical quiet NaN. A value that is not an fp32 value is an
 * internal error (exit 3), not a mismatch. */
static uint32_t mpfr_to_bits(const mpfr_t v)
{
    float fl;
    uint32_t b;
    if (mpfr_nan_p(v))
        return QNAN32;
    if (mpfr_inf_p(v))
        return mpfr_signbit(v) ? 0xff800000u : 0x7f800000u;
    if (mpfr_zero_p(v))
        return mpfr_signbit(v) ? 0x80000000u : 0u;
    fl = mpfr_get_flt(v, MPFR_RNDN);
    mpfr_set_flt(o_chk, fl, MPFR_RNDN);
    if (!mpfr_equal_p(o_chk, v)) {
        fprintf(stderr, "routine-sweep: internal error: the oracle's value is not an fp32 value\n");
        exit(3);
    }
    memcpy(&b, &fl, 4);
    return b;
}

/* ieee_tfn_oracle for one lane under attribute m: the answer's bits and the contract's flags. */
static void slow_lane(int fn, int m, uint32_t a, uint32_t bx, uint32_t *bits, uint32_t *flags)
{
    uint8_t ba[4], bb[4];
    put32(ba, a);
    put32(bb, bx);                         /* a unary call passes a real word: tfn_class_flags reads bb */
    ieee_tfn_oracle(&F32, fn, ATT[m].mr, ATT[m].rmm, ba, bb, 0, o_out, flags);
    *bits = mpfr_to_bits(o_out);
}

static mpfr_t j_w;                         /* judge()'s, precision 24 */
static mpfr_t f_a, f_b, f_y;               /* the fast path's: precisions 24, 24, 25 */

/* The fast path (see the header). 1 and the five attributes' bits and flags if the lane is on it, else 0. */
static int fast_lane(int fn, uint32_t a, uint32_t bx, uint32_t ob[5], uint32_t of[5])
{
    uint8_t ba[4], bb[4];
    cls ca, cb;
    mpfr_exp_t save_emin = mpfr_get_emin(), save_emax = mpfr_get_emax();
    int t, ok, m, sign;
    double d;
    uint64_t db, m52;
    uint32_t m24, guard, E;
    put32(ba, a);
    put32(bb, bx);
    classify(&F32, ba, &ca);
    if (ca.is_nan || ca.is_inf || ca.is_zero)
        return 0;
    if (fn == TF_ATAN2) {
        classify(&F32, bb, &cb);
        if (cb.is_nan || cb.is_inf || cb.is_zero)
            return 0;
    }
    enc_to_mpfr(&F32, ba, f_a);
    enc_to_mpfr(&F32, bb, f_b);
    mpfr_set_emin(mpfr_get_emin_min());
    mpfr_set_emax(mpfr_get_emax_max());
    mpfr_clear_flags();
    t = raw_tfn(f_y, fn, f_a, f_b, 0, MPFR_RNDZ);
    ok = mpfr_number_p(f_y) && !mpfr_zero_p(f_y) && t != 0 && !mpfr_overflow_p() && !mpfr_underflow_p();
    if (ok) {
        mpfr_exp_t e = mpfr_get_exp(f_y);             /* |y| in [2^(e-1), 2^e) */
        ok = e >= -124 && e <= 127;                    /* 2^-125 <= |y| < 2^127 */
    }
    mpfr_set_emin(save_emin);
    mpfr_set_emax(save_emax);
    if (!ok)
        return 0;
    sign = mpfr_signbit(f_y) != 0;
    d = mpfr_get_d(f_y, MPFR_RNDZ);                    /* y has 25 bits and the exponent is in range: exact */
    if (d < 0)
        d = -d;
    memcpy(&db, &d, 8);
    m52 = db & 0xfffffffffffffull;
    if (m52 & 0xfffffffull) {                           /* the 25 bits are the top 24 of the 52 */
        fprintf(stderr, "routine-sweep: internal error: the fast path's y has more than 25 bits\n");
        exit(3);
    }
    m24 = (uint32_t)((1u << 23) | (uint32_t)(m52 >> 29));
    guard = (uint32_t)((m52 >> 28) & 1);
    E = (uint32_t)((int)((db >> 52) & 0x7ff) - 1023);
    for (m = 0; m < 5; m++) {
        int away = 0;
        uint32_t mm = m24, ee = E;
        switch (m) {
        case 0: away = (int)guard; break;               /* rne: above the midpoint (t != 0) if the guard is set, else below */
        case 1: away = 0; break;                        /* rtz */
        case 2: away = sign; break;                     /* rdn: a negative value moves away from zero */
        case 3: away = !sign; break;                    /* rup */
        default: away = (int)guard; break;              /* rmm: no tie is possible, so it is rne */
        }
        if (away) {
            mm++;
            if (mm == (1u << 24)) {
                mm = 1u << 23;
                ee++;
            }
        }
        ob[m] = ((uint32_t)sign << 31) | ((ee + 127u) << 23) | (mm & 0x7fffffu);
        of[m] = CFT_FLAG_INEXACT;
    }
    return 1;
}

/* ---- reporting ----------------------------------------------------- */

static void rep_mismatch(const char *what, const char *mode, uint32_t a, uint32_t lib, uint32_t want, const char *who)
{
    if (shown_m++ < SHOW)
        printf("  MISMATCH %s%s%s a=0x%08lx %s=0x%08lx mpfr=0x%08lx\n", what, what[0] ? " " : "", mode,
               (unsigned long)a, who, (unsigned long)lib, (unsigned long)want);
}

static void rep_flags(const char *mode, uint32_t a, uint32_t lib, uint32_t want, const char *note)
{
    if (shown_f++ < SHOW)
        printf("  FLAGS %s a=0x%08lx lib=0x%02lx mpfr=0x%02lx%s\n", mode, (unsigned long)a, (unsigned long)lib,
               (unsigned long)want, note);
}

/* ---- one job ------------------------------------------------------- */

typedef struct {
    int ri, fn, mode;                      /* mode: 0..4 one attribute, 5 all */
    int first, last;                       /* attributes run: first..last */
    uint32_t x;
    image im[5];
    uint32_t chk;                          /* CFT_SWEEP_ORACLE_CHECK */
    size_t lanes;
} job;

static int on_list(const image *im, uint32_t a)
{
    size_t lo = 0, hi = im->nmarks;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (im->marks[mid] < a) lo = mid + 1; else hi = mid;
    }
    return lo < im->nmarks && im->marks[lo] == a;
}

/* Run one attribute's program over the call; the call-level checks. 0 on a library failure. */
static int run_call(job *J, int m, const uint32_t *A, const uint32_t *B, size_t nl, uint32_t *dep, uint8_t *lfl,
                    uint32_t *cnt, uint64_t lo)
{
    cft_run_args ra;
    cft_status st;
    uint32_t fl = 0, bus = 0, orb = 0, marked = 0, c1 = 1;
    size_t i;
    double t0 = now_s();
    memset(&ra, 0, sizeof ra);
    ra.struct_size = sizeof ra;
    ra.a = A;
    ra.b = RTNS[J->ri].fn == TF_ATAN2 ? (const void *)B : NULL;
    ra.n = nl;
    ra.bank = J->im[m].bank;
    ra.bank_bytes = J->im[m].bankn;
    ra.deposits = dep;
    ra.counts = cnt;
    ra.flags_out = &fl;
    ra.bus_out = &bus;
    ra.lane_flags = lfl;
    ra.lane_flags_bytes = nl;
    st = cft_program_run_ex(J->im[m].prog, &ra);
    t_device += now_s() - t0;
    if (st != CFT_OK) {
        const char *detail = cft_last_error();
        printf("  library call failed\n");
        fprintf(stderr, "cft_program_run_ex(%s %s, lanes 0x%08lx..) failed: %s%s%s\n", RTNS[J->ri].name, ATT[m].name,
                (unsigned long)lo, cft_strerror(st), (detail && *detail) ? " - " : "", (detail && *detail) ? detail : "");
        return 0;
    }
    if (sabotage) {
        size_t pick = 0;
        for (i = 0; i < nl; i++)
            if (!(lfl[i] & CFT_LANE_MARKED)) { pick = i; break; }
        if (sabotage == 1) {
            dep[pick] ^= 1u;
        } else if (sabotage == 2) {
            lfl[pick] ^= 1u;
        } else if (sabotage == 3) {
            for (i = 0; i < nl; i++) {
                if (lfl[i] & CFT_LANE_MARKED)
                    sab3_cleared++;
                lfl[i] = (uint8_t)(lfl[i] & ~CFT_LANE_MARKED);
            }
        }
    }
    for (i = 0; i < nl; i++) {
        orb |= lfl[i] & CFT_FLAGS_ALL;
        marked |= (lfl[i] & CFT_LANE_MARKED) ? 1u : 0u;
    }
#define CALLBAD(msg) do { fmis++; if (shown_f++ < SHOW) \
    printf("  FLAGS %s call a=0x%08lx..0x%08lx %s\n", ATT[m].name, (unsigned long)lo, (unsigned long)(lo + nl - 1), msg); } while (0)
    if (fl != orb)
        CALLBAD("flags_out is not the OR of the lanes' bytes");
    if ((bus & CFT_STATUS_MARKED) != 0 && !marked)
        CALLBAD("STATUS[6] set and no lane's byte has bit 7");
    if ((bus & CFT_STATUS_MARKED) == 0 && marked)
        CALLBAD("a lane's byte has bit 7 and STATUS[6] is clear");
    if (bus & ~(uint32_t)CFT_STATUS_MARKED)
        CALLBAD("STATUS has a bit beside STATUS[6]");
    for (i = 0; i < nl; i++)
        if (lfl[i] & (CFT_LANE_DEPOSIT_OVERFLOW | CFT_LANE_SCRATCH_RANGE)) {
            CALLBAD("a lane's byte has bit 5 or 6");
            break;
        }
    for (i = 0; i < nl; i++)
        if (cnt[i] != c1) {
            CALLBAD("a deposit count is not 1");
            break;
        }
#undef CALLBAD
    return 1;
}

/* Judge one lane of attribute m: lib bits (unmarked or guess) and byte against the oracle's bits and flags. */
static void judge(job *J, int m, uint32_t a, uint32_t lib, uint8_t byte, uint32_t ob, uint32_t of)
{
    const char *mode = ATT[m].name;
    int bad = lib != ob;
    cases++;
    if (bad && ob != QNAN32) {
        /* the decision is agree()'s: the bits differ, so ask it whether the VALUES do */
        uint8_t lb[4], wb[4];
        put32(lb, lib);
        put32(wb, ob);
        enc_to_mpfr(&F32, wb, j_w);
        bad = !agree(&F32, lb, j_w);
    }
    if (byte & CFT_LANE_MARKED) {
        int wrong = bad || (byte & CFT_FLAGS_ALL) != of;
        int listed = on_list(&J->im[m], a);
        nmarked[m]++;
        if (!listed)
            off_list++;
        if (wrong)
            wrong_guess++;
        if (shown_k++ < SHOW)
            printf("  MARK %s a=0x%08lx guess=0x%08lx %s%s\n", mode, (unsigned long)a, (unsigned long)lib,
                   wrong ? "WRONG" : "right", listed ? "" : " (off the list)");
        return;
    }
    if (bad) {
        vmis++;
        rep_mismatch("", mode, a, lib, ob, "lib");
    }
    if ((byte & CFT_FLAGS_ALL) != of) {
        fmis++;
        rep_flags(mode, a, byte & CFT_FLAGS_ALL, of, "");
    }
    if (on_list(&J->im[m], a)) {
        fmis++;
        rep_flags(mode, a, byte, of, " (on the marks list, and not marked)");
    }
}

static int run_slice(job *J, uint64_t lo, uint64_t hi)
{
    size_t L = J->lanes, i, nl;
    uint32_t *A = (uint32_t *)malloc(L * 4), *B = (uint32_t *)malloc(L * 4), *cnt = (uint32_t *)malloc(L * 4);
    uint32_t *dep[5] = { 0 };
    uint8_t *lfl[5] = { 0 };
    uint64_t at;
    int m, rc = 0;
    int fn = J->fn;
    if (!A || !B || !cnt) {
        fprintf(stderr, "routine-sweep: out of memory\n");
        return 2;
    }
    for (m = J->first; m <= J->last; m++) {
        dep[m] = (uint32_t *)malloc(L * 4);
        lfl[m] = (uint8_t *)malloc(L);
        if (!dep[m] || !lfl[m]) {
            fprintf(stderr, "routine-sweep: out of memory\n");
            return 2;
        }
    }
    for (i = 0; i < L; i++)
        B[i] = J->x;
    for (at = lo; at < hi; at += nl) {
        double t0;
        nl = (size_t)(hi - at < L ? hi - at : L);
        for (i = 0; i < nl; i++)
            A[i] = (uint32_t)(at + i);
        for (m = J->first; m <= J->last; m++)
            if (!run_call(J, m, A, B, nl, dep[m], lfl[m], cnt, at)) {
                rc = 1;
                goto out;
            }
        t0 = now_s();
        for (i = 0; i < nl; i++) {   /* the lanes of one call */
            uint32_t a = A[i], ob[5], of[5];
            if (J->mode < 5) {
                slow_lane(fn, J->mode, a, J->x, &ob[J->mode], &of[J->mode]);
            } else if (fast_lane(fn, a, J->x, ob, of)) {
                if (J->chk && a % J->chk == 0) {
                    for (m = 0; m < 5; m++) {
                        uint32_t sb, sf;
                        slow_lane(fn, m, a, J->x, &sb, &sf);
                        if (sb != ob[m] || sf != of[m]) {
                            vmis++;
                            rep_mismatch("ORACLE", ATT[m].name, a, ob[m], sb, "fast");
                        }
                    }
                }
            } else {
                for (m = 0; m < 5; m++)
                    slow_lane(fn, m, a, J->x, &ob[m], &of[m]);
            }
            for (m = J->first; m <= J->last; m++)
                judge(J, m, a, dep[m][i], lfl[m][i], ob[m], of[m]);
        }
        t_oracle_s += now_s() - t0;
    }
out:
    for (m = J->first; m <= J->last; m++) {
        free(dep[m]);
        free(lfl[m]);
    }
    free(A);
    free(B);
    free(cnt);
    return rc;
}

/* ---- main ---------------------------------------------------------- */

static void usage(const char *p)
{
    fprintf(stderr,
            "usage: %s <op> <lo> <hi> <rne|rtz|rdn|rup|rmm|all>\n"
            "       %s oracle <op> <rne|rtz|rdn|rup|rmm>        hex lanes on stdin\n"
            "       %s list\n"
            "  op: <name>-f32 for exp exp2 expm1 log log2 log1p sin cos tan atan asin acos, or atan2-f32-x<8 hex digits>;\n"
            "      either may end -d<8 hex digits>, the images' digest (routine-sweep list prints them)\n"
            "  [lo, hi): 0 <= lo < hi <= 2^32, decimal or 0x\n"
            "  CFT_SWEEP_IMAGES (the images' directory, else sweep-images/ beside the binary), CFT_SOAK_ARTIFACT, CFT_XRT_TILES,\n"
            "  CFT_SWEEP_LANES, CFT_SWEEP_ORACLE_CHECK, CFT_SOAK_SABOTAGE (=1 flips the low bit of, =2 a flag bit of, the first\n"
            "  UNMARKED lane of each call, not the first lane: a marked first lane would only make a wrong guess, which fails\n"
            "  nothing; =3 clears every mark)\n", p, p, p);
}

static void oracle_init(void)
{
    mpfr_init2(o_out, 24);
    mpfr_init2(o_chk, 24);
    mpfr_init2(f_a, 24);
    mpfr_init2(f_b, 24);
    mpfr_init2(f_y, 25);
    mpfr_init2(j_w, 24);
}

static void oracle_line(void)
{
    fprintf(stderr, "oracle: MPFR %s with GMP %s, mpfr_ieee.h's emulation\n", mpfr_get_version(), gmp_version);
}

static int cmd_list(const char *argv0)
{
    int ri, m;
    set_imgdir(argv0);
    for (ri = 0; ri < 13; ri++) {
        image im[5];
        char msg[1300];
        int have = 0, ok = 1;
        for (m = 0; m < 5; m++) {
            memset(&im[m], 0, sizeof im[m]);
            if (load_files(ri, m, &im[m], msg, sizeof msg))
                have++;
            else
                ok = 0;
        }
        if (ok)
            printf("%s-f32: images rne rtz rdn rup rmm, digest %08lx\n", RTNS[ri].name, (unsigned long)digest_of(im));
        else if (have == 0)
            printf("%s-f32: no image\n", RTNS[ri].name);
        else
            printf("%s-f32: %d of 5 images found (%s)\n", RTNS[ri].name, have, msg);
        for (m = 0; m < 5; m++)
            free_image(&im[m]);
    }
    return 0;
}

static int cmd_oracle(int argc, char **argv)
{
    opspec o;
    const char *why = "";
    char line[256];
    int m;
    if (argc != 4) {
        usage(argv[0]);
        return 2;
    }
    if (!parse_op(argv[2], &o, &why)) {
        fprintf(stderr, "routine-sweep: %s: %s\n", argv[2], why);
        return 2;
    }
    m = mode_of(argv[3]);
    if (m < 0 || m > 4) {
        fprintf(stderr, "routine-sweep: oracle takes one of rne rtz rdn rup rmm, not %s\n", argv[3]);
        return 2;
    }
    oracle_init();
    oracle_line();
    while (fgets(line, sizeof line, stdin)) {
        char *s = line;
        size_t n;
        uint64_t v;
        uint32_t bits, fl;
        while (*s == ' ' || *s == '\t')
            s++;
        n = strlen(s);
        while (n && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t'))
            s[--n] = 0;
        if (!n)
            continue;
        {
            char tmp[300];
            const char *h = s;
            if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
                h = s + 2;
            snprintf(tmp, sizeof tmp, "0x%s", h);
            if (!*h || !parse_u64(tmp, &v) || v > 0xffffffffull) {
                fprintf(stderr, "routine-sweep: oracle: not a 32-bit hex lane: %s\n", s);
                return 2;
            }
        }
        slow_lane(RTNS[o.ri].fn, m, (uint32_t)v, o.x, &bits, &fl);
        printf("%08lx %08lx %02lx\n", (unsigned long)v, (unsigned long)bits, (unsigned long)fl);
    }
    return 0;
}

int main(int argc, char **argv)
{
    opspec o;
    const char *why = "", *art;
    uint64_t lo, hi;
    int mode, m, rc = 0, i;
    job J;
    char opword[256];
    cft_status ost;
    const char *e;

    if (argc == 2 && !strcmp(argv[1], "list"))
        return cmd_list(argv[0]);
    if (argc >= 2 && !strcmp(argv[1], "oracle"))
        return cmd_oracle(argc, argv);
    if (argc != 5) {
        usage(argv[0]);
        return 2;
    }
    if (strlen(argv[1]) >= sizeof opword) {
        fprintf(stderr, "routine-sweep: the op word is too long\n");
        return 2;
    }
    strcpy(opword, argv[1]);
    if (!parse_op(argv[1], &o, &why)) {
        fprintf(stderr, "routine-sweep: %s: %s\n", argv[1], why);
        return 2;
    }
    if (!parse_u64(argv[2], &lo) || !parse_u64(argv[3], &hi)) {
        fprintf(stderr, "routine-sweep: [lo, hi) is two non-negative numbers, decimal or 0x: %s %s\n", argv[2], argv[3]);
        return 2;
    }
    if (lo >= hi || hi > (1ull << 32)) {
        fprintf(stderr, "routine-sweep: [%s, %s) must satisfy 0 <= lo < hi <= 2^32\n", argv[2], argv[3]);
        return 2;
    }
    mode = mode_of(argv[4]);
    if (mode < 0) {
        fprintf(stderr, "routine-sweep: unknown rounding mode %s (rne rtz rdn rup rmm all)\n", argv[4]);
        return 2;
    }
    memset(&J, 0, sizeof J);
    J.ri = o.ri;
    J.fn = RTNS[o.ri].fn;
    J.mode = mode;
    J.x = o.x;
    J.first = mode < 5 ? mode : 0;
    J.last = mode < 5 ? mode : 4;
    J.lanes = LANES;
    if ((e = getenv("CFT_SWEEP_LANES")) && *e) {
        uint64_t v;
        if (!parse_u64(e, &v) || v < 1 || v > MAXLANES) {
            fprintf(stderr, "routine-sweep: CFT_SWEEP_LANES is a number from 1 to %u\n", MAXLANES);
            return 2;
        }
        J.lanes = (size_t)v;
    }
    J.chk = 4096;
    if ((e = getenv("CFT_SWEEP_ORACLE_CHECK")) && *e) {
        uint64_t v;
        if (!parse_u64(e, &v) || v > 0xffffffffull) {
            fprintf(stderr, "routine-sweep: CFT_SWEEP_ORACLE_CHECK is a number (0 checks no lane)\n");
            return 2;
        }
        J.chk = (uint32_t)v;
    }
    if ((e = getenv("CFT_SOAK_SABOTAGE")) && (*e == '1' || *e == '2' || *e == '3'))
        sabotage = *e - '0';

    /* the files: all five when the word is all or a digest is named, else the one attribute's */
    set_imgdir(argv[0]);
    {
        int need_all = (mode == 5) || o.has_d;
        char msg[1300];
        for (m = 0; m < 5; m++)
            if (need_all || m == mode)
                if (!load_files(o.ri, m, &J.im[m], msg, sizeof msg)) {
                    fprintf(stderr, "routine-sweep: %s\n", msg);
                    return 2;
                }
        if (o.has_d) {
            uint32_t d = digest_of(J.im);
            if (d != o.d) {
                fprintf(stderr, "routine-sweep: %s names digest %08lx, the images' digest is %08lx\n", opword,
                        (unsigned long)o.d, (unsigned long)d);
                return 2;
            }
        }
    }

    art = getenv("CFT_SOAK_ARTIFACT");
    if (art && !*art)
        art = NULL;
    ost = cft_open(art, 0, &dev);
    if (ost != CFT_OK) {
        const char *detail = cft_last_error();
        fprintf(stderr, "cft_open(%s) failed: %s%s%s\n", art ? art : "software", cft_strerror(ost),
                (detail && *detail) ? " - " : "", (detail && *detail) ? detail : "");
        return 2;
    }
    fprintf(stderr, "soaking the %s backend%s%s\n", art ? "DEVICE" : "software", art ? ": " : "", art ? art : "");
    oracle_init();
    oracle_line();
    for (m = J.first; m <= J.last; m++) {
        image *im = &J.im[m];
        cft_program_info pi;
        ost = cft_program_load(dev, im->img, im->imgn, &im->prog);
        if (ost != CFT_OK) {
            const char *detail = cft_last_error();
            fprintf(stderr, "routine-sweep: the device refused %s: %s%s%s\n", im->ipath, cft_strerror(ost),
                    (detail && *detail) ? " - " : "", (detail && *detail) ? detail : "");
            cft_close(dev);
            return 2;
        }
        memset(&pi, 0, sizeof pi);
        pi.struct_size = sizeof pi;
        ost = cft_program_get_info(im->prog, &pi);
        if (ost != CFT_OK) {
            fprintf(stderr, "routine-sweep: no program info for %s: %s\n", im->ipath, cft_strerror(ost));
            cft_close(dev);
            return 2;
        }
        im->ninsn = pi.n_insns;
        im->nwords = pi.n_consts;
        if (pi.max_deposits != 1 || (size_t)pi.n_consts * 4 != im->bankn || pi.format != CFT_FP32) {
            fprintf(stderr, "routine-sweep: %s is not an fp32 program of one deposit with the %lu constants of %s (%lu bytes)\n",
                    im->ipath, (unsigned long)pi.n_consts, im->bpath, (unsigned long)im->bankn);
            cft_close(dev);
            return 2;
        }
        fprintf(stderr, "image %s %s: sha256 %s, %lu instructions, %lu words\n", RTNS[o.ri].name, ATT[m].name, im->sha,
                (unsigned long)im->ninsn, (unsigned long)im->nwords);
    }

    rc = run_slice(&J, lo, hi);
    if (rc == 2) {
        cft_close(dev);
        return 2;
    }
    if (sabotage == 3 && !sab3_cleared)
        fprintf(stderr, "sabotage 3: no lane of this slice is marked, so nothing was cleared and nothing is sabotaged\n");
    printf("%s %s: %llu cases, %llu value mismatches, %llu flag mismatches, %llu encodings, 0 skipped\n", opword, argv[4],
           (unsigned long long)cases, (unsigned long long)vmis, (unsigned long long)fmis, (unsigned long long)(hi - lo));
    {
        uint64_t tot = 0;
        char col[5][24];
        for (i = 0; i < 5; i++) {
            if (i >= J.first && i <= J.last) {
                tot += nmarked[i];
                snprintf(col[i], sizeof col[i], "%llu", (unsigned long long)nmarked[i]);
            } else {
                snprintf(col[i], sizeof col[i], "-");
            }
        }
        printf("%s %s: %llu marked (rne %s, rtz %s, rdn %s, rup %s, rmm %s), %llu off the list, %llu guesses wrong\n", opword,
               argv[4], (unsigned long long)tot, col[0], col[1], col[2], col[3], col[4], (unsigned long long)off_list,
               (unsigned long long)wrong_guess);
    }
    fprintf(stderr, "%s %s: device %.3f s, oracle %.3f s, %lu lanes a call\n", opword, argv[4], t_device, t_oracle_s,
            (unsigned long)J.lanes);
    for (m = 0; m < 5; m++)
        free_image(&J.im[m]);
    cft_close(dev);
    return (rc || vmis || fmis) ? 1 : 0;
}
