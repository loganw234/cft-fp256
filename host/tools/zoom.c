/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-zoom - a deep-zoom Mandelbrot reference orbit at binary256, and
 * the perturbed pixel orbits it serves at binary64.
 *
 *   ./cft-zoom
 *   ./cft-zoom --format fp64 --csv
 *   ./cft-zoom --engine loop --ref-iters 4000 --orbit orbit.txt
 *   ./cft-zoom --checkpoint run.ckpt --resume
 *
 * ---------------------------------------------------------------
 * The workload, and why it belongs to this contract
 * ---------------------------------------------------------------
 *
 * A deep zoom into the Mandelbrot set is two arithmetics stacked on
 * one another. ONE point - the reference - is iterated
 *
 *     z_{k+1} = z_k^2 + c
 *
 * at a precision wide enough to hold the centre, and every PIXEL is
 * then iterated as a perturbation of it,
 *
 *     d_{k+1} = 2 z_k d_k + d_k^2 + Dc,
 *
 * at binary64, because d and Dc are small and their arithmetic is
 * relative to their own size rather than to the centre's. At a zoom
 * whose pixels are about 10^-61 wide, binary64 cannot hold the centre
 * at all - its nearest neighbour is 10^45 pixels away - while
 * binary256 holds it to 10^-11 of a pixel. That gap is the whole
 * measurement this tool exists to make, and it is made with numbers
 * rather than asserted.
 *
 * Both halves go through libcft. The reference orbit is fp256 (or
 * whatever --format says) and the perturbation is fp64, so the image
 * is the contract's arithmetic end to end: same bits on the software
 * backend, on the tile, on any conforming implementation.
 *
 * ---------------------------------------------------------------
 * Why determinism is the product here
 * ---------------------------------------------------------------
 *
 * The reference orbit is a chaotic map. Two machines that disagree by
 * one ulp at iteration 1,000 disagree about everything by iteration
 * 3,000, and every pixel in the frame is computed FROM that orbit. So
 * "the same reference orbit, bit for bit" is not a nicety - it is the
 * entire reproducibility claim of a deep-zoom renderer, and it is
 * exactly what this library promises. The tool tests it rather than
 * claiming it: the same orbit comes out of the sequencer program and
 * the host loop, out of runs with different trip counts, and out of a
 * run that was interrupted and resumed.
 *
 * ---------------------------------------------------------------
 * The centre, derived rather than transcribed
 * ---------------------------------------------------------------
 *
 * A deep zoom needs a centre whose orbit stays bounded for a very long
 * time, which in practice means the nucleus of a tiny hyperbolic
 * component: there z_p = 0 exactly, the cycle is superattracting, and
 * a finite-precision orbit stays on it instead of drifting off. Rather
 * than copy a published location, this tool FINDS one, in the
 * library's own arithmetic:
 *
 *   - Near the tip c = -2 the set is self-similar with ratio 4, so the
 *     period-p nucleus nearest the tip sits at about 14.8 * 4^-p. With
 *     p = 51 that is 2.9e-30 from -2, and the nucleus itself is a
 *     71-digit binary256 number.
 *   - Every real c in [-2, 1/4] has a bounded critical orbit - that is
 *     what M intersect R IS - so on this segment z_p(c) is a
 *     continuous real function with no escape to work around, and a
 *     SIGN CHANGE of z_p brackets a nucleus.
 *   - So: evaluate z_p over a grid of exactly-representable candidates
 *     (one library call, one lane per candidate), take the first sign
 *     change, and bisect to the last bit of the format.
 *
 * The result is a nucleus of period p, deterministic, reproducible,
 * and checkable: host/tests/zoom_check.py re-derives the same bits
 * with the golden model and confirms with mpmath at 300 digits that
 * |z_p(c)| really is at the format's noise floor.
 *
 * ---------------------------------------------------------------
 * Exactness, rounding, and what the flags can say
 * ---------------------------------------------------------------
 *
 * Unlike the Collatz explorer, NOTHING here is exact. z^2 + c rounds
 * twice per component per iteration by construction, so `inexact` is
 * raised on essentially every call and carries no information about
 * whether the orbit is right. This is worth stating plainly because it
 * is the opposite of the other workload on this contract:
 *
 *   EXPECTED, on every call: CFT_FLAG_INEXACT.
 *   CERTIFICATES: the ABSENCE of invalid, divideByZero, overflow and
 *   underflow - none of which any step of this workload can produce
 *   while |z| <= 2 and |d| stays small - checked after every call;
 *   bit identity with python/cft_golden over the whole orbit; bit
 *   identity between the sequencer program and the host loop; and the
 *   escape test, which is a COMPARISON and therefore exact and quiet.
 *
 * The escape comparison is checked to raise nothing at all, per call,
 * in the host-loop engine where it can be issued on its own.
 *
 * No constant is transcribed. p is measured from the library (the
 * smallest k for which 2^k + 1 raises inexact); the bias follows from
 * p and the width; -2, 4, 1 and the grid multipliers are converted
 * from integers; the view radius is a power of two, so every pixel
 * offset is an exact odd multiple of a power of two in every format;
 * the glitch tolerance is 2^-(p/4) with p measured from the PIXEL
 * format; and SHA-256's round constants are derived from the cube
 * roots of the primes.
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 199309L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>

#include "cft.h"

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

#define MAX_ESZ 32          /* bytes in the widest element, binary256 */
#define DECMAX  2048        /* an exact decimal this tool will print */

static void die(const char *what)
{
    fprintf(stderr, "cft-zoom: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-zoom: %s: %s%s%s\n", what, cft_strerror(st),
            (d && *d) ? " - " : "", (d && *d) ? d : "");
    exit(2);
}

static void *xcalloc(size_t n, size_t sz)
{
    void *p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        die("out of memory");
    return p;
}

/* ===================================================================
 * A 128-bit unsigned, enough to derive SHA-256's constants
 *
 * The standing rule in this repository is that a constant is derived,
 * or copied in the base it was specified in; it is never retyped from
 * memory. SHA-256's eight initial words and sixty-four round constants
 * are SPECIFIED as the fractional parts of the square and cube roots
 * of the first primes, so that is how they are computed here. The
 * cross-check recomputes the whole chain with Python's hashlib, which
 * is what proves the derivation.
 * =================================================================== */
typedef struct { uint64_t hi, lo; } u128;

static u128 u128_mk(uint64_t hi, uint64_t lo)
{
    u128 r;
    r.hi = hi;
    r.lo = lo;
    return r;
}

static int u128_cmp(u128 a, u128 b)
{
    if (a.hi != b.hi)
        return a.hi < b.hi ? -1 : 1;
    if (a.lo != b.lo)
        return a.lo < b.lo ? -1 : 1;
    return 0;
}

static u128 u128_shl(u128 a, int s)
{
    u128 r;
    if (s == 0)
        return a;
    if (s >= 64) {
        r.hi = a.lo << (s - 64);
        r.lo = 0;
    } else {
        r.hi = (a.hi << s) | (a.lo >> (64 - s));
        r.lo = a.lo << s;
    }
    return r;
}

static u128 u128_mul64(uint64_t a, uint64_t b)
{
    uint64_t al = a & 0xffffffffu, ah = a >> 32;
    uint64_t bl = b & 0xffffffffu, bh = b >> 32;
    uint64_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint64_t mid = (ll >> 32) + (lh & 0xffffffffu) + (hl & 0xffffffffu);
    u128 r;
    r.lo = (ll & 0xffffffffu) | (mid << 32);
    r.hi = hh + (lh >> 32) + (hl >> 32) + (mid >> 32);
    return r;
}

static int u128_mul_small(u128 a, uint64_t b, u128 *out)
{
    u128 lo = u128_mul64(a.lo, b);
    u128 hi = u128_mul64(a.hi, b);
    if (hi.hi != 0)
        return 1;
    lo.hi += hi.lo;
    if (lo.hi < hi.lo)
        return 1;
    *out = lo;
    return 0;
}

static int u128_pow(uint64_t v, int root, u128 *out)
{
    u128 acc = u128_mk(0, v);
    int k;
    for (k = 1; k < root; k++)
        if (u128_mul_small(acc, v, &acc))
            return 1;
    *out = acc;
    return 0;
}

static void first_primes(uint32_t *out, int count)
{
    int have = 0;
    uint32_t cand;
    for (cand = 2; have < count; cand++) {
        uint32_t d;
        int prime = 1;
        for (d = 2; d * d <= cand; d++)
            if (cand % d == 0) { prime = 0; break; }
        if (prime)
            out[have++] = cand;
    }
}

/* floor(frac(p^(1/root)) * 2^32), root 2 or 3 */
static uint32_t root_frac32(uint32_t p, int root)
{
    u128 target = u128_shl(u128_mk(0, p), 32 * root);
    uint64_t lo = 0, hi = 1;
    for (;;) {
        u128 acc;
        if (u128_pow(hi, root, &acc) || u128_cmp(acc, target) > 0)
            break;
        hi <<= 1;
    }
    while (hi - lo > 1) {
        uint64_t mid = lo + (hi - lo) / 2;
        u128 acc;
        if (u128_pow(mid, root, &acc) || u128_cmp(acc, target) > 0)
            hi = mid;
        else
            lo = mid;
    }
    return (uint32_t)(lo & 0xffffffffu);
}

/* ---- SHA-256 ------------------------------------------------------ */
typedef struct {
    uint32_t h[8];
    uint64_t bits;
    uint8_t  buf[64];
    size_t   have;
} sha256;

static uint32_t SHA_K[64];
static uint32_t SHA_H0[8];
static int      sha_ready = 0;

static void sha_init_constants(void)
{
    uint32_t primes[64];
    int i;
    if (sha_ready)
        return;
    first_primes(primes, 64);
    for (i = 0; i < 64; i++)
        SHA_K[i] = root_frac32(primes[i], 3);
    for (i = 0; i < 8; i++)
        SHA_H0[i] = root_frac32(primes[i], 2);
    sha_ready = 1;
}

static uint32_t rotr32(uint32_t x, int n)
{
    return (x >> n) | (x << (32 - n));
}

static void sha256_block(sha256 *s, const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, h;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) |
               ((uint32_t)p[4 * i + 2] << 8) | (uint32_t)p[4 * i + 3];
    for (i = 16; i < 64; i++) {
        uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^
                      (w[i - 15] >> 3);
        uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^
                      (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (i = 0; i < 64; i++) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + SHA_K[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha256_start(sha256 *s)
{
    sha_init_constants();
    memcpy(s->h, SHA_H0, sizeof s->h);
    s->bits = 0;
    s->have = 0;
}

static void sha256_push(sha256 *s, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    s->bits += (uint64_t)n * 8u;
    while (n) {
        size_t take = 64 - s->have;
        if (take > n)
            take = n;
        memcpy(s->buf + s->have, p, take);
        s->have += take;
        p += take;
        n -= take;
        if (s->have == 64) {
            sha256_block(s, s->buf);
            s->have = 0;
        }
    }
}

static void sha256_end(sha256 *s, uint8_t out[32])
{
    uint64_t bits = s->bits;
    int i;
    s->buf[s->have++] = 0x80;
    if (s->have > 56) {
        while (s->have < 64)
            s->buf[s->have++] = 0;
        sha256_block(s, s->buf);
        s->have = 0;
    }
    while (s->have < 56)
        s->buf[s->have++] = 0;
    for (i = 7; i >= 0; i--)
        s->buf[s->have++] = (uint8_t)(bits >> (8 * i));
    sha256_block(s, s->buf);
    for (i = 0; i < 8; i++) {
        out[4 * i]     = (uint8_t)(s->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)s->h[i];
    }
}

static void hex32(const uint8_t in[32], char out[65])
{
    static const char D[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 32; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[64] = 0;
}

static int unhex32(const char *in, uint8_t out[32])
{
    int i;
    for (i = 0; i < 64; i++) {
        int c = (unsigned char)in[i], v;
        if (c >= '0' && c <= '9')      v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else return 0;
        if (i & 1) out[i / 2] = (uint8_t)(out[i / 2] | v);
        else       out[i / 2] = (uint8_t)(v << 4);
    }
    return in[64] == 0;
}

/* ===================================================================
 * Format parameters, measured rather than tabulated
 * =================================================================== */
typedef struct {
    cft_format fmt;
    size_t     esz;
    int        width;
    int        prec;
    int        exp_w;
    uint64_t   bias;
} fmt_info;

static cft_device *DEV;
static uint32_t    FLAGS_SEEN;
static int         FLAGS_TRUSTED = 1;
static uint64_t    OPS_ISSUED;      /* elementwise opcode issues */

/* Every step of this workload rounds, so inexact is expected and says
 * nothing. What must never appear is anything else: |z| <= 2 while the
 * orbit is live and |d| stays bounded, so an invalid, a division by
 * zero, an overflow or an underflow would mean the TOOL is wrong. */
#define FORBIDDEN (CFT_FLAG_INVALID | CFT_FLAG_DIVBYZERO | \
                   CFT_FLAG_OVERFLOW | CFT_FLAG_UNDERFLOW)

static void note_flags(uint32_t f, const char *where)
{
    FLAGS_SEEN |= f;
    if (f & FORBIDDEN) {
        fprintf(stderr,
                "cft-zoom: the library raised 0x%02x in %s, on a step that "
                "can only ever raise inexact - stopping\n", (unsigned)f,
                where);
        exit(3);
    }
}

static void runN(cft_op op, cft_format fmt, const void *a, const void *b,
                 const void *c, void *d, size_t n, const char *where)
{
    uint32_t f = 0;
    cft_status st = cft_run(DEV, op, fmt, CFT_RNE, a, b, c, d, n, &f, NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    OPS_ISSUED += n;
    note_flags(f, where);
}

/* The escape test is a comparison: 754 says it rounds nothing and
 * signals nothing on ordinary operands, and this workload leans on
 * that, so the loop engine issues it on its own and checks. */
static void run_cmp(cft_op op, cft_format fmt, const void *a, const void *b,
                    void *d, size_t n)
{
    uint32_t f = 0;
    cft_status st = cft_run(DEV, op, fmt, CFT_RNE, a, b, NULL, d, n, &f,
                            NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    OPS_ISSUED += n;
    if (f) {
        fprintf(stderr,
                "cft-zoom: the escape comparison raised 0x%02x - a "
                "comparison rounds nothing and must signal nothing here; "
                "one of the tool or the library is wrong\n", (unsigned)f);
        exit(3);
    }
}

static void run1(cft_op op, cft_format fmt, const void *a, const void *b,
                 const void *c, void *d)
{
    runN(op, fmt, a, b, c, d, 1, "a scalar step");
}

static void measure_format(fmt_info *fi, cft_format fmt)
{
    uint8_t one[MAX_ESZ], pow[MAX_ESZ], sum[MAX_ESZ];
    int64_t i1 = 1;
    int k;
    cft_status st;

    memset(fi, 0, sizeof *fi);
    fi->fmt = fmt;
    fi->esz = cft_format_size(fmt);
    if (!fi->esz || fi->esz > MAX_ESZ)
        die("unknown format");
    fi->width = (int)fi->esz * 8;

    st = cft_cvt_from_i64(DEV, fmt, CFT_RNE, &i1, one, 1, NULL);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);

    /* p is the smallest k for which 2^k + 1 is not representable, and
     * the library answers that question itself, in the flag it raises. */
    fi->prec = 0;
    for (k = 1; k < fi->width; k++) {
        uint32_t fl = 0;
        st = cft_scaleb(DEV, fmt, CFT_RNE, one, k, pow, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_scaleb", st);
        st = cft_run(DEV, CFT_ADD, fmt, CFT_RNE, pow, NULL, one, sum, 1,
                     &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        if (fl & CFT_FLAG_INEXACT) {
            fi->prec = k;
            break;
        }
    }
    if (!fi->prec)
        die("could not measure the format's precision");
    fi->exp_w = fi->width - fi->prec;
    fi->bias  = ((uint64_t)1 << (fi->exp_w - 1)) - 1;
}

/* ===================================================================
 * Values
 * =================================================================== */
static void val_from_i64(const fmt_info *fi, int64_t v, uint8_t *out)
{
    uint32_t fl = 0;
    cft_status st = cft_cvt_from_i64(DEV, fi->fmt, CFT_RNE, &v, out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);
    if (fl & CFT_FLAG_INEXACT)
        die("a small integer constant was not exact in this format");
}

static void val_pow2(const fmt_info *fi, int e, uint8_t *out)
{
    uint8_t one[MAX_ESZ];
    cft_status st;
    val_from_i64(fi, 1, one);
    st = cft_scaleb(DEV, fi->fmt, CFT_RNE, one, e, out, 1, NULL, NULL);
    if (st != CFT_OK)
        die_st("cft_scaleb", st);
}

/* The exact decimal of a value: cft_to_decimal_char with digits = 0 is
 * 5.12.2's exact conversion, and cft_from_decimal_char reads it back to
 * the same bits. That round trip is what lets a checkpoint be text. */
static void val_to_dec(const fmt_info *fi, const void *v, char *out,
                       size_t cap)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, 0, out,
                                        cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

static int val_from_dec(const fmt_info *fi, const char *s, void *out)
{
    const char *arr[1];
    uint32_t fl = 0;
    cft_status st;
    arr[0] = s;
    st = cft_from_decimal_char(DEV, fi->fmt, CFT_RNE, arr, out, 1, NULL,
                               &fl);
    if (st != CFT_OK)
        return 0;
    if (fl & (CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW))
        return 0;
    return 1;
}

static int pred_true(const fmt_info *fi, const void *v)
{
    uint8_t zero[MAX_ESZ];
    memset(zero, 0, fi->esz);
    return memcmp(v, zero, fi->esz) != 0;
}

static int val_lt(const fmt_info *fi, const void *a, const void *b)
{
    uint8_t r[MAX_ESZ];
    run_cmp(CFT_CMPLT, fi->fmt, a, b, r, 1);
    return pred_true(fi, r);
}

static void bcast(const fmt_info *fi, uint8_t *dst, const uint8_t *v,
                  size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        memcpy(dst + i * fi->esz, v, fi->esz);
}

/* ===================================================================
 * Programs for the orbit sequencer
 * =================================================================== */
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };

static uint64_t alu(int op, int rd, int ra, int rb, int rc,
                    int ka, int kb, int kc)
{
    return (uint64_t)(uint32_t)op |
           ((uint64_t)(uint32_t)rd << 8) |
           ((uint64_t)(uint32_t)ra << 12) |
           ((uint64_t)(uint32_t)rb << 16) |
           ((uint64_t)(uint32_t)rc << 20) |
           ((uint64_t)(uint32_t)(ka ? 1 : 0) << 27) |
           ((uint64_t)(uint32_t)(kb ? 1 : 0) << 28) |
           ((uint64_t)(uint32_t)(kc ? 1 : 0) << 29);
}

static uint64_t ctl(int code, int ra, uint32_t imm)
{
    return (uint64_t)(uint32_t)code |
           ((uint64_t)(uint32_t)ra << 12) |
           ((uint64_t)1 << 31) |
           ((uint64_t)imm << 32);
}

static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static void put_le64(uint8_t *p, uint64_t v)
{
    put_le32(p, (uint32_t)v);
    put_le32(p + 4, (uint32_t)(v >> 32));
}

static uint8_t *pack_program(const fmt_info *fi, const uint64_t *ins,
                             uint32_t n, const uint8_t *consts,
                             uint32_t nconst, uint32_t max_deposits,
                             size_t *bytes_out)
{
    size_t esz = fi->esz, off, i;
    uint8_t *img;
    *bytes_out = 32 + (size_t)nconst * esz + (size_t)n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);
    put_le32(img + 8, n);
    put_le32(img + 12, nconst);
    put_le32(img + 16, max_deposits);
    put_le32(img + 20, (uint32_t)fi->fmt);
    off = 32;
    memcpy(img + off, consts, (size_t)nconst * esz);
    off += (size_t)nconst * esz;
    for (i = 0; i < n; i++) {
        put_le64(img + off, ins[i]);
        off += 8;
    }
    return img;
}

/* ---- the reference orbit ------------------------------------------
 *
 *   r0 = zr, r1 = zi        (streams a and b; r2..r15 start at +0)
 *   constants: 4, cr, ci
 *
 * One iteration is nine instructions plus the two deposits that ARE
 * the orbit. The escape test runs on z_k BEFORE the step, so a lane
 * whose |z_k|^2 has passed 4 deposits nothing more and the deposit
 * count says exactly how far it got. */
enum { OK_FOUR = 0, OK_CR, OK_CI, N_ORBK };
enum { OR_ZR = 0, OR_ZI, OR_UNUSED, OR_A, OR_B, OR_M, OR_P, OR_T, OR_D };

static uint32_t orbit_insns(uint64_t *ins, uint32_t reps)
{
    uint32_t n = 0;
    ins[n++] = ctl(C_REPEAT, 0, reps);
    ins[n++] = alu(CFT_MUL,   OR_A,  OR_ZR, OR_ZR,   0,       0, 0, 0);
    ins[n++] = alu(CFT_MUL,   OR_B,  OR_ZI, OR_ZI,   0,       0, 0, 0);
    ins[n++] = alu(CFT_ADD,   OR_M,  OR_A,  0,       OR_B,    0, 0, 0);
    ins[n++] = alu(CFT_CMPLE, OR_P,  OR_M,  OK_FOUR, 0,       0, 1, 0);
    ins[n++] = ctl(C_SETACT, OR_P, 0);
    ins[n++] = alu(CFT_ADD,   OR_T,  OR_ZR, 0,       OR_ZR,   0, 0, 0);
    ins[n++] = alu(CFT_SUB,   OR_D,  OR_A,  0,       OR_B,    0, 0, 0);
    ins[n++] = alu(CFT_FMA,   OR_ZI, OR_T,  OR_ZI,   OK_CI,   0, 0, 1);
    ins[n++] = alu(CFT_ADD,   OR_ZR, OR_D,  0,       OK_CR,   0, 0, 1);
    ins[n++] = ctl(C_DEPOSIT, OR_ZR, 0);
    ins[n++] = ctl(C_DEPOSIT, OR_ZI, 0);
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_ACTALL, 0, 0);
    ins[n++] = ctl(C_HALT, 0, 0);
    return n;
}

/* ---- the nucleus search -------------------------------------------
 *
 *   r0 = c (stream a), r1 = z, starting at +0 because that is what
 *   z_0 is. One multiply and one add per iteration, plus the guard
 *   that stops a candidate whose orbit has left the disc. */
enum { SK_FOUR = 0, N_SCANK };
enum { SR_C = 0, SR_Z, SR_S, SR_P };

static uint32_t scan_insns(uint64_t *ins, uint32_t reps)
{
    uint32_t n = 0;
    ins[n++] = ctl(C_REPEAT, 0, reps);
    ins[n++] = alu(CFT_MUL,   SR_S, SR_Z, SR_Z,    0,    0, 0, 0);
    ins[n++] = alu(CFT_CMPLE, SR_P, SR_S, SK_FOUR, 0,    0, 1, 0);
    ins[n++] = ctl(C_SETACT, SR_P, 0);
    ins[n++] = alu(CFT_ADD,   SR_Z, SR_S, 0,       SR_C, 0, 0, 0);
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_ACTALL, 0, 0);
    ins[n++] = ctl(C_DEPOSIT, SR_Z, 0);
    ins[n++] = ctl(C_HALT, 0, 0);
    return n;
}

/* ===================================================================
 * The reference-orbit engine
 * =================================================================== */
typedef struct {
    const fmt_info *fi;
    int          use_program;
    uint32_t     reps;
    uint32_t     n_insns;
    cft_program *prog;
    uint8_t     *dep;              /* 2 * reps elements */
    uint32_t     counts[1];
    uint8_t      k[N_ORBK][MAX_ESZ];
    uint64_t     calls;
} orbit_engine;

static void orbit_engine_init(orbit_engine *E, const fmt_info *fi,
                              const uint8_t *cr, const uint8_t *ci,
                              int use_program, uint32_t reps)
{
    memset(E, 0, sizeof *E);
    E->fi = fi;
    E->use_program = use_program;
    E->reps = reps;
    val_from_i64(fi, 4, E->k[OK_FOUR]);
    memcpy(E->k[OK_CR], cr, fi->esz);
    memcpy(E->k[OK_CI], ci, fi->esz);
    if (use_program) {
        uint64_t ins[32];
        uint8_t consts[N_ORBK * MAX_ESZ];
        uint8_t *img;
        size_t bytes = 0;
        cft_status st;
        int i;
        E->n_insns = orbit_insns(ins, reps);
        for (i = 0; i < N_ORBK; i++)
            memcpy(consts + (size_t)i * fi->esz, E->k[i], fi->esz);
        img = pack_program(fi, ins, E->n_insns, consts, N_ORBK,
                           2u * reps, &bytes);
        st = cft_program_load(DEV, img, bytes, &E->prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load (orbit)", st);
        E->dep = (uint8_t *)xcalloc((size_t)reps * 2, fi->esz);
    }
}

static void orbit_engine_free(orbit_engine *E)
{
    free(E->dep);
    if (E->prog)
        cft_program_free(E->prog);
}

/* Advance the orbit by up to `reps` iterations from (zr, zi), writing
 * the points into out_r/out_i. Returns how many iterations ran; a
 * count below `reps` means |z|^2 passed 4 on the next one. */
static uint32_t orbit_pass(orbit_engine *E, uint8_t *zr, uint8_t *zi,
                           uint8_t *out_r, uint8_t *out_i)
{
    const fmt_info *fi = E->fi;
    size_t esz = fi->esz;
    uint32_t did, j;

    E->calls++;
    if (E->use_program) {
        uint32_t f = 0, bus = 0;
        cft_status st = cft_program_run(E->prog, zr, zi, NULL, E->dep,
                                        E->counts, 1, &f, &bus);
        if (st != CFT_OK)
            die_st("cft_program_run", st);
        if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
            die("the deposit buffer overflowed - the program is wrong");
        note_flags(f, "the reference orbit program");
        if (E->counts[0] & 1u)
            die("the orbit program deposited an odd number of values");
        did = E->counts[0] / 2;
        /* eight ALU instructions an iteration - two multiplies, three
         * adds, a subtract, a fused multiply-add and the comparison;
         * REPEAT, SETACT and the two DEPOSITs are control, not
         * arithmetic, and the host loop issues exactly the same eight */
        OPS_ISSUED += (uint64_t)did * 8u;
        for (j = 0; j < did; j++) {
            memcpy(out_r + (size_t)j * esz, E->dep + (size_t)(2 * j) * esz,
                   esz);
            memcpy(out_i + (size_t)j * esz,
                   E->dep + (size_t)(2 * j + 1) * esz, esz);
        }
        if (did) {
            memcpy(zr, out_r + (size_t)(did - 1) * esz, esz);
            memcpy(zi, out_i + (size_t)(did - 1) * esz, esz);
        }
        return did;
    }

    for (did = 0; did < E->reps; did++) {
        uint8_t a[MAX_ESZ], b[MAX_ESZ], m[MAX_ESZ], p[MAX_ESZ];
        uint8_t t[MAX_ESZ], d[MAX_ESZ], nzi[MAX_ESZ];
        run1(CFT_MUL, fi->fmt, zr, zr, NULL, a);
        run1(CFT_MUL, fi->fmt, zi, zi, NULL, b);
        run1(CFT_ADD, fi->fmt, a, NULL, b, m);
        run_cmp(CFT_CMPLE, fi->fmt, m, E->k[OK_FOUR], p, 1);
        if (!pred_true(fi, p))
            break;
        run1(CFT_ADD, fi->fmt, zr, NULL, zr, t);
        run1(CFT_SUB, fi->fmt, a, NULL, b, d);
        run1(CFT_FMA, fi->fmt, t, zi, E->k[OK_CI], nzi);
        run1(CFT_ADD, fi->fmt, d, NULL, E->k[OK_CR], zr);
        memcpy(zi, nzi, esz);
        memcpy(out_r + (size_t)did * esz, zr, esz);
        memcpy(out_i + (size_t)did * esz, zi, esz);
    }
    return did;
}

/* ===================================================================
 * The nucleus search
 *
 * Evaluate z_p(c) over a batch of candidates. The program route runs
 * one lane per candidate in one call; the loop route does the same
 * arithmetic with the active mask spelled out, and the two must agree
 * bit for bit.
 * =================================================================== */
typedef struct {
    const fmt_info *fi;
    int          use_program;
    uint32_t     iters;
    size_t       cap;
    cft_program *prog;
    uint8_t     *dep;
    uint32_t    *counts;
    uint8_t     *z, *s, *p, *live, *cand, *four;
    uint32_t     n_insns;
} scan_engine;

static void scan_engine_init(scan_engine *S, const fmt_info *fi,
                             int use_program, uint32_t iters, size_t cap)
{
    size_t esz = fi->esz;
    uint8_t four[MAX_ESZ];

    memset(S, 0, sizeof *S);
    S->fi = fi;
    S->use_program = use_program;
    S->iters = iters;
    S->cap = cap;
    val_from_i64(fi, 4, four);
    if (use_program) {
        uint64_t ins[16];
        uint8_t consts[N_SCANK * MAX_ESZ];
        uint8_t *img;
        size_t bytes = 0;
        cft_status st;
        S->n_insns = scan_insns(ins, iters);
        memcpy(consts, four, esz);
        img = pack_program(fi, ins, S->n_insns, consts, N_SCANK, 1, &bytes);
        st = cft_program_load(DEV, img, bytes, &S->prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load (scan)", st);
        S->dep = (uint8_t *)xcalloc(cap, esz);
        S->counts = (uint32_t *)xcalloc(cap, sizeof(uint32_t));
    } else {
        S->z    = (uint8_t *)xcalloc(cap, esz);
        S->s    = (uint8_t *)xcalloc(cap, esz);
        S->p    = (uint8_t *)xcalloc(cap, esz);
        S->live = (uint8_t *)xcalloc(cap, esz);
        S->cand = (uint8_t *)xcalloc(cap, esz);
        S->four = (uint8_t *)xcalloc(cap, esz);
        bcast(fi, S->four, four, cap);
    }
}

static void scan_engine_free(scan_engine *S)
{
    free(S->dep); free(S->counts);
    free(S->z); free(S->s); free(S->p); free(S->live);
    free(S->cand); free(S->four);
    if (S->prog)
        cft_program_free(S->prog);
}

static void scan_eval(scan_engine *S, const uint8_t *c, uint8_t *out,
                      size_t n)
{
    const fmt_info *fi = S->fi;
    size_t esz = fi->esz, i;
    uint32_t it;

    if (n > S->cap)
        die("the scan batch is larger than the engine was built for");
    if (S->use_program) {
        uint32_t f = 0, bus = 0;
        cft_status st = cft_program_run(S->prog, c, NULL, NULL, S->dep,
                                        S->counts, n, &f, &bus);
        if (st != CFT_OK)
            die_st("cft_program_run (scan)", st);
        if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
            die("the scan program overflowed its deposit buffer");
        note_flags(f, "the nucleus scan program");
        for (i = 0; i < n; i++)
            if (S->counts[i] != 1)
                die("a scan lane deposited the wrong number of values");
        memcpy(out, S->dep, n * esz);
        OPS_ISSUED += (uint64_t)n * S->iters * 2u;
        return;
    }

    memset(S->z, 0, n * esz);
    {
        uint8_t one[MAX_ESZ];
        val_from_i64(fi, 1, one);
        bcast(fi, S->live, one, n);
    }
    for (it = 0; it < S->iters; it++) {
        runN(CFT_MUL, fi->fmt, S->z, S->z, NULL, S->s, n, "the scan");
        run_cmp(CFT_CMPLE, fi->fmt, S->s, S->four, S->p, n);
        runN(CFT_MIN, fi->fmt, S->live, S->p, NULL, S->live, n, "the scan");
        runN(CFT_ADD, fi->fmt, S->s, NULL, c, S->cand, n, "the scan");
        runN(CFT_SELECT, fi->fmt, S->cand, S->z, S->live, S->z, n,
             "the scan");
    }
    memcpy(out, S->z, n * esz);
}

/* ===================================================================
 * The run
 * =================================================================== */
typedef struct {
    cft_format  fmt;
    int         use_program;
    uint32_t    period;
    int         zoom_exp;
    uint32_t    width;
    uint64_t    ref_iters;
    uint64_t    pixel_iters;
    size_t      batch;
    uint32_t    reps;
    int         glitch_bits;
    long        ref_offset;
    const char *ckpt;
    double      ckpt_interval;
    int         resume;
    long        stop_after_passes;
    double      time_limit;
    const char *artifact;
    const char *orbit_path;
    const char *pixels_path;
    const char *pgm_path;
    const char *compare_path;
    const char *centre_s;
    int         csv;
    int         quiet;
    int         no_pixels;
} options;

typedef struct {
    uint32_t iter;
    uint8_t  kind;      /* 0 escaped, 1 glitched, 2 interior */
    uint8_t  filled;
} pixrec;

typedef struct {
    const fmt_info *fi;      /* the reference format */
    const fmt_info *pf;      /* the pixel format, always binary64 */
    options        *opt;

    uint8_t   cr[MAX_ESZ], ci[MAX_ESZ];     /* the centre, in fi */
    uint8_t   c256r[MAX_ESZ], c256i[MAX_ESZ];  /* the derived nucleus */
    uint8_t   pixscale[MAX_ESZ];            /* one pixel, in fi */
    uint8_t   radius[MAX_ESZ];

    uint64_t  k;                 /* orbit iterations resolved */
    uint64_t  escaped_at;        /* 0 if it never escaped */
    uint8_t   zr[MAX_ESZ], zi[MAX_ESZ];
    uint8_t  *orb_r, *orb_i;     /* ref_iters + 1 points, index 0 = z_0 */
    uint8_t   chain[32];
    uint8_t   pixchain[32];

    uint8_t   minmag[MAX_ESZ];
    uint64_t  minmag_at;
    int       have_min;

    orbit_engine eng;
    long      passes;
    FILE     *orbf;

    pixrec   *pix;
    uint64_t  n_escaped, n_glitched, n_interior;
    uint64_t  pixel_work;
    uint32_t  esc_min, esc_max;
    uint64_t  ops_ref, ops_pix;   /* elementwise operations issued */
} runstate;

/* ---- the hash chains --------------------------------------------- */
static void chain_absorb(uint8_t chain[32], const char *line)
{
    sha256 h;
    size_t len = strlen(line);
    sha256_start(&h);
    sha256_push(&h, chain, 32);
    sha256_push(&h, line, len);
    sha256_push(&h, "\n", 1);
    sha256_end(&h, chain);
}

static void orbit_record(runstate *R, uint64_t idx, char *out, size_t cap)
{
    char a[DECMAX], b[DECMAX];
    const fmt_info *fi = R->fi;
    int len;
    val_to_dec(fi, R->orb_r + idx * fi->esz, a, sizeof a);
    val_to_dec(fi, R->orb_i + idx * fi->esz, b, sizeof b);
    len = snprintf(out, cap, "%" PRIu64 " %s %s", idx, a, b);
    if (len <= 0 || (size_t)len >= cap)
        die("an orbit record line is too long");
}

/* ===================================================================
 * Deriving the centre
 *
 * Near the tip the set is self-similar with ratio 4, so a period-p
 * nucleus sits a small multiple of 4^-p from -2. Every candidate on
 * the grid is EXACT in the format: -2 plus (i * 2^-3) * 4^-p, with i a
 * small integer, needs about (2p + 12) significand bits, which every
 * format wide enough to run this workload has.
 * =================================================================== */
#define SCAN_STEPS 320          /* i = 1..320, so eps/4^-p in (0, 40] */

static void derive_centre(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz;
    options *O = R->opt;
    uint8_t *cand = (uint8_t *)xcalloc(SCAN_STEPS, esz);
    uint8_t *zval = (uint8_t *)xcalloc(SCAN_STEPS, esz);
    uint8_t minus2[MAX_ESZ], w[MAX_ESZ], eighth[MAX_ESZ], step[MAX_ESZ];
    uint8_t zero[MAX_ESZ], lo[MAX_ESZ], hi[MAX_ESZ], mid[MAX_ESZ];
    uint8_t zlo[MAX_ESZ], zhi[MAX_ESZ], zmid[MAX_ESZ], mag[MAX_ESZ];
    uint8_t maglo[MAX_ESZ], maghi[MAX_ESZ];
    scan_engine S;
    size_t i, brk = 0;
    int found = 0, sgn_lo;
    size_t per_call = O->batch ? O->batch : 1;

    /* A grid point is -2 + (i/8) * 4^-p with i a small integer, so its
     * highest bit is 2^1 and its lowest is 2^(-3-2p): it needs exactly
     * 2p + 5 significand bits to be exact, and an inexact candidate
     * would make the sign of z_p a question about the grid rather than
     * about the set. Derived from the format, not tabulated. */
    if (2 * (int)O->period + 5 > fi->prec)
        die("this format cannot hold the search grid for that period "
            "exactly; use a smaller --period or a wider format");

    val_from_i64(fi, -2, minus2);
    val_pow2(fi, -2 * (int)O->period, w);      /* 4^-p */
    val_pow2(fi, -3, eighth);
    memset(zero, 0, esz);

    scan_engine_init(&S, fi, O->use_program, O->period,
                     per_call < SCAN_STEPS ? per_call : SCAN_STEPS);

    for (i = 0; i < SCAN_STEPS; i++) {
        uint8_t ival[MAX_ESZ], eps[MAX_ESZ];
        val_from_i64(fi, (int64_t)(i + 1), ival);
        run1(CFT_MUL, fi->fmt, ival, w, NULL, step);
        run1(CFT_MUL, fi->fmt, step, eighth, NULL, eps);
        run1(CFT_ADD, fi->fmt, minus2, NULL, eps, cand + i * esz);
    }
    for (i = 0; i < SCAN_STEPS; i += per_call) {
        size_t n = SCAN_STEPS - i;
        if (n > per_call)
            n = per_call;
        scan_eval(&S, cand + i * esz, zval + i * esz, n);
    }

    /* the first sign change, with both endpoints still in the disc */
    for (i = 0; i + 1 < SCAN_STEPS; i++) {
        int a = val_lt(fi, zval + i * esz, zero);
        int b = val_lt(fi, zval + (i + 1) * esz, zero);
        if (a != b) {
            brk = i;
            found = 1;
            sgn_lo = a;
            break;
        }
    }
    if (!found)
        die("no sign change of z_p was found near the tip - try another "
            "--period");

    memcpy(lo, cand + brk * esz, esz);
    memcpy(hi, cand + (brk + 1) * esz, esz);
    memcpy(zlo, zval + brk * esz, esz);
    memcpy(zhi, zval + (brk + 1) * esz, esz);

    /* Bisect to the last bit the format has. The midpoint is exact
     * (a sum then a halving), and the loop stops when the interval can
     * no longer be halved, which is one ulp. */
    for (;;) {
        uint8_t sum[MAX_ESZ], half[MAX_ESZ];
        int s;
        val_pow2(fi, -1, half);
        run1(CFT_ADD, fi->fmt, lo, NULL, hi, sum);
        run1(CFT_MUL, fi->fmt, sum, half, NULL, mid);
        if (memcmp(mid, lo, esz) == 0 || memcmp(mid, hi, esz) == 0)
            break;
        scan_eval(&S, mid, zmid, 1);
        s = val_lt(fi, zmid, zero);
        if (s == sgn_lo) {
            memcpy(lo, mid, esz);
            memcpy(zlo, zmid, esz);
        } else {
            memcpy(hi, mid, esz);
            memcpy(zhi, zmid, esz);
        }
    }

    /* Of the two adjacent values the bisection ended on, keep the one
     * whose |z_p| is smaller: that is the nucleus to the precision the
     * format can express. */
    run1(CFT_MUL, fi->fmt, zlo, zlo, NULL, maglo);
    run1(CFT_MUL, fi->fmt, zhi, zhi, NULL, maghi);
    if (val_lt(fi, maghi, maglo)) {
        memcpy(R->c256r, hi, esz);
        memcpy(mag, maghi, esz);
    } else {
        memcpy(R->c256r, lo, esz);
        memcpy(mag, maglo, esz);
    }
    memset(R->c256i, 0, esz);
    (void)mag;

    scan_engine_free(&S);
    free(cand);
    free(zval);
}

/* ===================================================================
 * Checkpoint
 *
 * A line-oriented ASCII file written to <path>.tmp and renamed over the
 * target, so a reader never sees a half-written one. It carries the
 * centre, the orbit so far in EXACT DECIMAL, and the chain over it -
 * every number that describes a result, and nothing that describes the
 * machine, which is what lets two runs with different trip counts and
 * different engines end on byte-identical files.
 *
 * It is O(the orbit), which is honest rather than convenient: at
 * 100,000 iterations the file is about 48 MB. Checkpointing is opt-in
 * for that reason. The PIXEL phase does not checkpoint - it is one
 * batch of independent elements, like the Collatz explorer's deep
 * mode, and its determinism property is batch-size independence rather
 * than resume.
 * =================================================================== */
#define CKPT_MAGIC "cft-zoom-checkpoint 1"

static int ckpt_replace(const char *tmp, const char *path)
{
#if defined(_WIN32)
    return MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING) ? 0 : -1;
#else
    return rename(tmp, path);
#endif
}

static void ckpt_write(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    char tmp[1024], a[DECMAX], b[DECMAX], chain[65];
    FILE *f;
    uint64_t i;

    if (!O->ckpt)
        return;
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt) >= sizeof tmp)
        die("checkpoint path too long");
    f = fopen(tmp, "wb");
    if (!f)
        die("cannot write the checkpoint");

    hex32(R->chain, chain);
    val_to_dec(fi, R->cr, a, sizeof a);
    val_to_dec(fi, R->ci, b, sizeof b);
    fprintf(f, "%s\n", CKPT_MAGIC);
    fprintf(f, "format %s\n", cft_format_name(fi->fmt));
    fprintf(f, "centre %s %s\n", a, b);
    fprintf(f, "refiters %" PRIu64 "\n", O->ref_iters);
    fprintf(f, "k %" PRIu64 "\n", R->k);
    fprintf(f, "escapedat %" PRIu64 "\n", R->escaped_at);
    /* No minmag here: it is a function of the orbit below, and the
     * checkpoint carries results, not restatements of them. */
    fprintf(f, "chain %s\n", chain);
    fprintf(f, "orbit %" PRIu64 "\n", R->k);
    for (i = 1; i <= R->k; i++) {
        val_to_dec(fi, R->orb_r + i * fi->esz, a, sizeof a);
        val_to_dec(fi, R->orb_i + i * fi->esz, b, sizeof b);
        fprintf(f, "z %s %s\n", a, b);
    }
    fprintf(f, "end\n");
    if (fflush(f) != 0 || fclose(f) != 0)
        die("the checkpoint did not write cleanly");
    if (ckpt_replace(tmp, O->ckpt) != 0)
        die("the checkpoint could not be renamed into place");
}

static char *trim_nl(char *s)
{
    size_t n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r'))
        s[--n] = 0;
    return s;
}

static void ckpt_read(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    FILE *f = fopen(O->ckpt, "rb");
    char *line = (char *)xcalloc(4 * DECMAX, 1);
    size_t cap = 4 * DECMAX;
    uint64_t i, want = 0;

    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, (int)cap, f) || strcmp(trim_nl(line), CKPT_MAGIC) != 0)
        die("that file is not a cft-zoom checkpoint of this version");

    while (fgets(line, (int)cap, f)) {
        char key[64], *rest;
        trim_nl(line);
        if (sscanf(line, "%63s", key) != 1)
            continue;
        rest = line + strlen(key);
        while (*rest == ' ')
            rest++;
        if (!strcmp(key, "format")) {
            if (strcmp(rest, cft_format_name(fi->fmt)) != 0)
                die("the checkpoint was written for a different format");
        } else if (!strcmp(key, "centre")) {
            char *sp = strchr(rest, ' ');
            if (!sp)
                die("bad checkpoint centre");
            *sp = 0;
            if (!val_from_dec(fi, rest, R->cr) ||
                !val_from_dec(fi, sp + 1, R->ci))
                die("bad checkpoint centre value");
        } else if (!strcmp(key, "refiters")) {
            /* a result of the run, not a machine setting: a resume that
             * asked for a different length is a different run */
            if (strtoull(rest, NULL, 10) != O->ref_iters)
                die("the checkpoint was written for a different "
                    "--ref-iters");
        } else if (!strcmp(key, "k")) {
            R->k = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "escapedat")) {
            R->escaped_at = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "chain")) {
            if (!unhex32(rest, R->chain))
                die("bad checkpoint chain");
        } else if (!strcmp(key, "orbit")) {
            want = strtoull(rest, NULL, 10);
            if (want > O->ref_iters)
                die("the checkpoint holds more orbit than --ref-iters");
            for (i = 1; i <= want; i++) {
                char *sp;
                if (!fgets(line, (int)cap, f))
                    die("the checkpoint ended inside its orbit");
                trim_nl(line);
                if (strncmp(line, "z ", 2) != 0)
                    die("bad checkpoint orbit line");
                sp = strchr(line + 2, ' ');
                if (!sp)
                    die("bad checkpoint orbit line");
                *sp = 0;
                if (!val_from_dec(fi, line + 2,
                                  R->orb_r + i * fi->esz) ||
                    !val_from_dec(fi, sp + 1, R->orb_i + i * fi->esz))
                    die("bad checkpoint orbit value");
            }
        } else if (!strcmp(key, "end")) {
            break;
        }
    }
    fclose(f);
    if (want != R->k)
        die("the checkpoint's orbit length and cursor disagree");
    if (R->k) {
        memcpy(R->zr, R->orb_r + R->k * fi->esz, fi->esz);
        memcpy(R->zi, R->orb_i + R->k * fi->esz, fi->esz);
    }
    free(line);
}

/* ===================================================================
 * The reference orbit
 * =================================================================== */
static void orbit_absorb(runstate *R, uint64_t idx)
{
    char line[3 * DECMAX];
    orbit_record(R, idx, line, sizeof line);
    chain_absorb(R->chain, line);
    if (R->orbf)
        fprintf(R->orbf, "%s\n", line);
}

/* The smallest |z_k|^2 the reference reaches, and where.
 *
 * This is a property of the finished orbit rather than of the
 * iteration, so it is computed ONCE, afterwards, in whole-array calls -
 * three elementwise passes and a MIN tournament, about 2*log2(n) + 4
 * library calls for any n. Doing it per iteration instead cost four
 * single-element calls per point, which is half as much work again as
 * the orbit itself and four hundred thousand library calls where the
 * sequencer had got the count down to ninety-eight. It is worth
 * recording why that mattered: a per-iteration host-side statistic
 * quietly undoes exactly what the sequencer is for.
 *
 * The number matters because it is where perturbation is fragile: the
 * closer a reference passes to the origin, the fewer pixels can glitch
 * against it. */
static void compute_minmag(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, n = (size_t)R->k, len, i;
    uint8_t *a, *b, *m, *t, *bc, *p;

    if (!n)
        return;
    a = (uint8_t *)xcalloc(n, esz);
    b = (uint8_t *)xcalloc(n, esz);
    m = (uint8_t *)xcalloc(n, esz);
    t = (uint8_t *)xcalloc(n, esz);
    bc = (uint8_t *)xcalloc(n, esz);
    p = (uint8_t *)xcalloc(n, esz);

    runN(CFT_MUL, fi->fmt, R->orb_r + esz, R->orb_r + esz, NULL, a, n,
         "the minimum-magnitude pass");
    runN(CFT_MUL, fi->fmt, R->orb_i + esz, R->orb_i + esz, NULL, b, n,
         "the minimum-magnitude pass");
    runN(CFT_ADD, fi->fmt, a, NULL, b, m, n,
         "the minimum-magnitude pass");

    memcpy(t, m, n * esz);
    len = n;
    while (len > 1) {
        size_t half = len >> 1;
        runN(CFT_MIN, fi->fmt, t, t + half * esz, NULL, t, half,
             "the minimum-magnitude pass");
        if (len & 1) {
            memcpy(t + half * esz, t + (len - 1) * esz, esz);
            len = half + 1;
        } else {
            len = half;
        }
    }
    bcast(fi, bc, t, n);
    run_cmp(CFT_CMPEQ, fi->fmt, m, bc, p, n);
    for (i = 0; i < n; i++) {
        if (pred_true(fi, p + i * esz)) {
            R->minmag_at = i + 1;
            break;
        }
    }
    memcpy(R->minmag, t, esz);
    R->have_min = 1;

    free(a); free(b); free(m); free(t); free(bc); free(p);
}

/* Run the orbit to --ref-iters, or until it escapes, or until a stop
 * condition fires. Returns 1 if it stopped early. */
static int run_reference(runstate *R, double t0, double *tckpt)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    size_t esz = fi->esz;
    uint8_t *br = (uint8_t *)xcalloc(O->reps, esz);
    uint8_t *bi = (uint8_t *)xcalloc(O->reps, esz);
    int stopped = 0;

    while (R->k < O->ref_iters && !R->escaped_at) {
        uint32_t did = orbit_pass(&R->eng, R->zr, R->zi, br, bi);
        uint64_t take = did;
        uint64_t j;
        if (take > O->ref_iters - R->k)
            take = O->ref_iters - R->k;
        for (j = 0; j < take; j++) {
            uint64_t idx = R->k + j + 1;
            memcpy(R->orb_r + idx * esz, br + j * esz, esz);
            memcpy(R->orb_i + idx * esz, bi + j * esz, esz);
            orbit_absorb(R, idx);
        }
        R->k += take;
        if (take)
            memcpy(R->zr, R->orb_r + R->k * esz, esz);
        if (take)
            memcpy(R->zi, R->orb_i + R->k * esz, esz);
        if (did < O->reps && take == did) {
            /* the lane went inactive: |z_k|^2 has passed 4 */
            R->escaped_at = R->k;
        }
        R->passes++;
        if (O->ckpt && now_s() - *tckpt >= O->ckpt_interval) {
            ckpt_write(R);
            *tckpt = now_s();
        }
        if (O->stop_after_passes >= 0 && R->passes >= O->stop_after_passes) {
            stopped = 1;
            break;
        }
        if (O->time_limit > 0 && now_s() - t0 >= O->time_limit) {
            stopped = 1;
            break;
        }
    }
    free(br);
    free(bi);
    if (O->ckpt)
        ckpt_write(R);
    return stopped;
}

/* ===================================================================
 * The perturbed pixel batch, at binary64
 *
 * One library call per operation per iteration over the live pixels.
 * The reference is rounded into binary64 once - which is what the
 * technique asks for, since the product 2 z_k d only needs the
 * reference to binary64's own relative accuracy - and every pixel's
 * offset from the centre is an exact odd multiple of a power of two,
 * so the grid itself contributes no rounding.
 * =================================================================== */
typedef struct {
    const fmt_info *pf;
    size_t cap;
    double *dcr, *dci, *dr, *di, *live, *glit, *iter;
    double *s1, *s2, *s3, *ndr, *u1, *u2, *d2, *ndi, *ndi_neg;
    double *fr, *fi_, *pp, *mm, *glok, *escok, *ok, *glnow, *glev;
    double *bA, *bB, *bnB, *bZr, *bZi, *bGT, *bK, *bFOUR, *bZERO, *bONE;
    size_t *idx;
} pixel_engine;

static double *dalloc(size_t n)
{
    return (double *)xcalloc(n, sizeof(double));
}

static void pixel_engine_init(pixel_engine *P, const fmt_info *pf,
                              size_t cap)
{
    memset(P, 0, sizeof *P);
    P->pf = pf;
    P->cap = cap;
    P->dcr = dalloc(cap); P->dci = dalloc(cap);
    P->dr = dalloc(cap); P->di = dalloc(cap);
    P->live = dalloc(cap); P->glit = dalloc(cap); P->iter = dalloc(cap);
    P->s1 = dalloc(cap); P->s2 = dalloc(cap); P->s3 = dalloc(cap);
    P->ndr = dalloc(cap); P->u1 = dalloc(cap); P->u2 = dalloc(cap);
    P->d2 = dalloc(cap); P->ndi = dalloc(cap); P->ndi_neg = dalloc(cap);
    P->fr = dalloc(cap); P->fi_ = dalloc(cap); P->pp = dalloc(cap);
    P->mm = dalloc(cap); P->glok = dalloc(cap); P->escok = dalloc(cap);
    P->ok = dalloc(cap); P->glnow = dalloc(cap); P->glev = dalloc(cap);
    P->bA = dalloc(cap); P->bB = dalloc(cap); P->bnB = dalloc(cap);
    P->bZr = dalloc(cap); P->bZi = dalloc(cap); P->bGT = dalloc(cap);
    P->bK = dalloc(cap); P->bFOUR = dalloc(cap); P->bZERO = dalloc(cap);
    P->bONE = dalloc(cap);
    P->idx = (size_t *)xcalloc(cap, sizeof(size_t));
}

static void pixel_engine_free(pixel_engine *P)
{
    free(P->dcr); free(P->dci); free(P->dr); free(P->di);
    free(P->live); free(P->glit); free(P->iter);
    free(P->s1); free(P->s2); free(P->s3); free(P->ndr);
    free(P->u1); free(P->u2); free(P->d2); free(P->ndi); free(P->ndi_neg);
    free(P->fr); free(P->fi_); free(P->pp); free(P->mm);
    free(P->glok); free(P->escok); free(P->ok); free(P->glnow);
    free(P->glev);
    free(P->bA); free(P->bB); free(P->bnB); free(P->bZr); free(P->bZi);
    free(P->bGT); free(P->bK); free(P->bFOUR); free(P->bZERO);
    free(P->bONE);
    free(P->idx);
}

static void dfill(double *p, double v, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        p[i] = v;
}

#define PRUN(op, a, b, c, d, n) \
    runN((op), CFT_FP64, (a), (b), (c), (d), (n), "the pixel batch")

/* One chunk of pixels, run to the iteration cap or to extinction. */
static void pixel_chunk(runstate *R, pixel_engine *P, const double *ref_r,
                        const double *ref_i, size_t n, uint64_t maxk)
{
    options *O = R->opt;
    uint64_t k;
    size_t live = n, i;
    double tol;

    /* tol = 2^-glitch_bits, and glitch_bits is derived from the pixel
     * format's measured precision, not typed in. */
    tol = 1.0;
    {
        int b;
        for (b = 0; b < O->glitch_bits; b++)
            tol *= 0.5;
    }

    dfill(P->bFOUR, 4.0, n);
    dfill(P->bZERO, 0.0, n);
    dfill(P->bONE, 1.0, n);
    dfill(P->live, 1.0, n);
    dfill(P->glit, 0.0, n);
    dfill(P->iter, 0.0, n);
    memset(P->dr, 0, n * sizeof(double));
    memset(P->di, 0, n * sizeof(double));

    for (k = 0; k < maxk && live; k++) {
        double zr = ref_r[k], zi = ref_i[k];
        double nr = ref_r[k + 1], ni = ref_i[k + 1];
        double a2[1], b2[1], nb2[1], gm[1], t1[1], t2[1];
        double one_r[1], one_i[1], tolv[1];

        /* the per-iteration scalars, computed in the library so that
         * nothing about the reference is done by the host */
        one_r[0] = zr; one_i[0] = zi;
        PRUN(CFT_ADD, one_r, NULL, one_r, a2, 1);        /* 2 zr, exact */
        PRUN(CFT_ADD, one_i, NULL, one_i, b2, 1);        /* 2 zi, exact */
        runN(CFT_NEG, CFT_FP64, b2, NULL, NULL, nb2, 1, "the pixel batch");
        one_r[0] = nr; one_i[0] = ni;
        PRUN(CFT_MUL, one_r, one_r, NULL, t1, 1);
        PRUN(CFT_FMA, one_i, one_i, t1, t2, 1);          /* |Z_{k+1}|^2 */
        tolv[0] = tol;
        PRUN(CFT_MUL, t2, tolv, NULL, gm, 1);
        PRUN(CFT_MUL, gm, tolv, NULL, gm, 1);            /* tol^2 |Z|^2 */

        dfill(P->bA, a2[0], live);
        dfill(P->bB, b2[0], live);
        dfill(P->bnB, nb2[0], live);
        dfill(P->bZr, nr, live);
        dfill(P->bZi, ni, live);
        dfill(P->bGT, gm[0], live);
        dfill(P->bK, (double)(k + 1), live);

        /* d' = 2 Z d + d^2 + Dc, real then imaginary */
        PRUN(CFT_FMA, P->bA, P->dr, P->dcr, P->s1, live);
        PRUN(CFT_FMA, P->bnB, P->di, P->s1, P->s2, live);
        PRUN(CFT_FMA, P->dr, P->dr, P->s2, P->s3, live);
        runN(CFT_NEG, CFT_FP64, P->di, NULL, NULL, P->ndi_neg, live,
             "the pixel batch");
        PRUN(CFT_FMA, P->ndi_neg, P->di, P->s3, P->ndr, live);
        PRUN(CFT_FMA, P->bA, P->di, P->dci, P->u1, live);
        PRUN(CFT_FMA, P->bB, P->dr, P->u1, P->u2, live);
        PRUN(CFT_ADD, P->dr, NULL, P->dr, P->d2, live);
        PRUN(CFT_FMA, P->d2, P->di, P->u2, P->ndi, live);

        /* the pixel's own value, and the two tests on it */
        PRUN(CFT_ADD, P->bZr, NULL, P->ndr, P->fr, live);
        PRUN(CFT_ADD, P->bZi, NULL, P->ndi, P->fi_, live);
        PRUN(CFT_MUL, P->fr, P->fr, NULL, P->pp, live);
        PRUN(CFT_FMA, P->fi_, P->fi_, P->pp, P->mm, live);
        run_cmp(CFT_CMPLE, CFT_FP64, P->bGT, P->mm, P->glok, live);
        run_cmp(CFT_CMPLE, CFT_FP64, P->mm, P->bFOUR, P->escok, live);
        PRUN(CFT_MIN, P->glok, P->escok, NULL, P->ok, live);
        PRUN(CFT_SELECT, P->bZERO, P->bONE, P->glok, P->glnow, live);
        PRUN(CFT_MIN, P->live, P->glnow, NULL, P->glev, live);
        PRUN(CFT_MAX, P->glit, P->glev, NULL, P->glit, live);
        PRUN(CFT_SELECT, P->bK, P->iter, P->live, P->iter, live);
        PRUN(CFT_SELECT, P->ndr, P->dr, P->live, P->dr, live);
        PRUN(CFT_SELECT, P->ndi, P->di, P->live, P->di, live);
        PRUN(CFT_MIN, P->live, P->ok, NULL, P->live, live);

        R->pixel_work += live;

        /* Compact the survivors to the front every so often. An
         * element's trajectory depends on its own values and nothing
         * else, so where it sits in the array cannot change what it
         * computes - the same reason the sequencer may compact lanes. */
        if ((k & 31u) == 31u) {
            size_t keep = 0;
            for (i = 0; i < live; i++) {
                if (P->live[i] == 0.0) {
                    pixrec *pr = &R->pix[P->idx[i]];
                    pr->iter = (uint32_t)P->iter[i];
                    pr->kind = P->glit[i] != 0.0 ? 1 : 0;
                    pr->filled = 1;
                    continue;
                }
                if (keep != i) {
                    P->dcr[keep] = P->dcr[i]; P->dci[keep] = P->dci[i];
                    P->dr[keep] = P->dr[i];   P->di[keep] = P->di[i];
                    P->live[keep] = P->live[i];
                    P->glit[keep] = P->glit[i];
                    P->iter[keep] = P->iter[i];
                    P->idx[keep] = P->idx[i];
                }
                keep++;
            }
            live = keep;
        }
    }

    for (i = 0; i < live; i++) {
        pixrec *pr = &R->pix[P->idx[i]];
        pr->iter = (uint32_t)P->iter[i];
        if (P->glit[i] != 0.0)
            pr->kind = 1;
        else if (P->live[i] != 0.0)
            pr->kind = 2;
        else
            pr->kind = 0;
        pr->filled = 1;
    }
}

static void run_pixels(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    uint64_t maxk = O->pixel_iters;
    uint64_t npix = (uint64_t)O->width * O->width;
    double *ref_r, *ref_i;
    pixel_engine P;
    uint64_t base;
    size_t i;
    uint8_t pixhalf[MAX_ESZ];
    double pixd;

    if (maxk + 1 > R->k)
        maxk = R->k ? R->k - 1 : 0;
    if (!maxk)
        die("the reference orbit is too short for any pixel work");

    /* the reference, rounded once into binary64 */
    ref_r = dalloc((size_t)maxk + 2);
    ref_i = dalloc((size_t)maxk + 2);
    {
        uint32_t f = 0;
        cft_status st;
        st = cft_convert(DEV, fi->fmt, CFT_FP64, CFT_RNE, R->orb_r,
                         ref_r, (size_t)maxk + 2, &f);
        if (st != CFT_OK)
            die_st("cft_convert (reference to binary64)", st);
        FLAGS_SEEN |= f;
        f = 0;
        st = cft_convert(DEV, fi->fmt, CFT_FP64, CFT_RNE, R->orb_i,
                         ref_i, (size_t)maxk + 2, &f);
        if (st != CFT_OK)
            die_st("cft_convert (reference to binary64)", st);
        FLAGS_SEEN |= f;
    }

    /* one half-pixel, as a binary64 number: the view radius is
     * 2^-zoom_exp and the grid is 2*width half-pixels wide, so this is
     * a power of two and every offset below is an exact odd multiple
     * of it */
    {
        uint32_t w = O->width, sh = 0;
        while (w > 1) { w >>= 1; sh++; }
        val_pow2(R->pf, -O->zoom_exp - (int)sh, pixhalf);
        memcpy(&pixd, pixhalf, sizeof pixd);
    }

    pixel_engine_init(&P, R->pf, O->batch);
    R->esc_min = 0xffffffffu;
    R->esc_max = 0;

    for (base = 0; base < npix; base += O->batch) {
        size_t n = (size_t)(npix - base);
        if (n > O->batch)
            n = O->batch;
        for (i = 0; i < n; i++) {
            uint64_t g = base + i;
            long ix = (long)(g % O->width);
            long iy = (long)(g / O->width);
            /* (2i + 1 - width) is an odd integer; times one half-pixel
             * it is exact in every format wide enough to hold it */
            P.dcr[i] = (double)(2 * ix + 1 - (long)O->width - 2 *
                                O->ref_offset) * pixd;
            P.dci[i] = (double)(2 * iy + 1 - (long)O->width) * pixd;
            P.idx[i] = (size_t)g;
        }
        pixel_chunk(R, &P, ref_r, ref_i, n, maxk);
    }

    for (i = 0; i < (size_t)npix; i++) {
        pixrec *pr = &R->pix[i];
        if (!pr->filled)
            die("a pixel record was never filled");
        if (pr->kind == 0) {
            R->n_escaped++;
            if (pr->iter < R->esc_min) R->esc_min = pr->iter;
            if (pr->iter > R->esc_max) R->esc_max = pr->iter;
        } else if (pr->kind == 1) {
            R->n_glitched++;
        } else {
            R->n_interior++;
        }
    }

    pixel_engine_free(&P);
    free(ref_r);
    free(ref_i);
}

static const char *pix_kind_name(int k)
{
    return k == 0 ? "esc" : (k == 1 ? "glitch" : "interior");
}

static void pixel_chain_and_dump(runstate *R)
{
    options *O = R->opt;
    uint64_t npix = (uint64_t)O->width * O->width, i;
    FILE *f = NULL;
    if (O->pixels_path) {
        f = fopen(O->pixels_path, "wb");
        if (!f)
            die("cannot write the pixel records file");
    }
    for (i = 0; i < npix; i++) {
        char line[128];
        snprintf(line, sizeof line, "%" PRIu64 " %u %s", i,
                 (unsigned)R->pix[i].iter, pix_kind_name(R->pix[i].kind));
        chain_absorb(R->pixchain, line);
        if (f)
            fprintf(f, "%s\n", line);
    }
    if (f)
        fclose(f);
}

static void write_pgm(runstate *R)
{
    options *O = R->opt;
    uint64_t npix = (uint64_t)O->width * O->width, i;
    FILE *f;
    uint32_t span;
    if (!O->pgm_path)
        return;
    f = fopen(O->pgm_path, "wb");
    if (!f)
        die("cannot write the PGM");
    fprintf(f, "P5\n%u %u\n255\n", O->width, O->width);
    span = (R->esc_max > R->esc_min) ? R->esc_max - R->esc_min : 1;
    for (i = 0; i < npix; i++) {
        int v;
        if (R->pix[i].kind == 2)
            v = 0;
        else if (R->pix[i].kind == 1)
            v = 255;
        else
            v = 1 + (int)((uint64_t)(R->pix[i].iter - R->esc_min) * 253u
                          / span);
        fputc(v, f);
    }
    fclose(f);
}

/* Compare this run's escape map against another run's records file -
 * which is how the fp64-versus-fp256 answer becomes a number. */
static void compare_pixels(runstate *R, uint64_t *differ, uint64_t *total)
{
    options *O = R->opt;
    FILE *f = fopen(O->compare_path, "rb");
    char line[256];
    uint64_t i = 0;
    *differ = 0;
    *total = 0;
    if (!f)
        die("cannot read the file named by --compare-pixels");
    while (fgets(line, sizeof line, f)) {
        uint64_t idx;
        unsigned it;
        char kind[32];
        if (sscanf(line, "%" SCNu64 " %u %31s", &idx, &it, kind) != 3)
            continue;
        if (idx >= (uint64_t)O->width * O->width)
            break;
        (*total)++;
        if (R->pix[idx].iter != it ||
            strcmp(pix_kind_name(R->pix[idx].kind), kind) != 0)
            (*differ)++;
        i++;
    }
    (void)i;
    fclose(f);
}

/* ===================================================================
 * Reporting
 * =================================================================== */
static void dec_digits(const fmt_info *fi, const void *v, size_t digits,
                       char *out, size_t cap)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, digits,
                                        out, cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

/* |c_fmt - c_fp256| measured in pixels: the reference's own
 * representation error, which is what decides whether a format can
 * serve a zoom at all. */
static void centre_error_pixels(runstate *R, char *out, size_t cap)
{
    uint8_t wide[MAX_ESZ], diff[MAX_ESZ], q[MAX_ESZ], adiff[MAX_ESZ];
    uint8_t px[MAX_ESZ];
    uint32_t fl = 0, w = R->opt->width, sh = 0;
    cft_status st;
    fmt_info big;

    big.fmt = CFT_FP256;
    big.esz = cft_format_size(CFT_FP256);
    if (R->fi->fmt == CFT_FP256) {
        memcpy(wide, R->cr, R->fi->esz);
    } else {
        st = cft_convert(DEV, R->fi->fmt, CFT_FP256, CFT_RNE, R->cr, wide,
                         1, &fl);
        if (st != CFT_OK)
            die_st("cft_convert", st);
    }
    /* The subtraction is exact: both operands are binary256 values a
     * few decades apart in magnitude, so their difference fits. */
    run1(CFT_SUB, CFT_FP256, wide, NULL, R->c256r, diff);
    runN(CFT_ABS, CFT_FP256, diff, NULL, NULL, adiff, 1, "the report");
    while (w > 1) { w >>= 1; sh++; }
    /* one pixel = 2 * radius / width */
    val_pow2(&big, 1 - R->opt->zoom_exp - (int)sh, px);
    fl = 0;
    st = cft_div(DEV, CFT_FP256, CFT_RNE, adiff, px, q, 1, &fl, NULL);
    if (st != CFT_OK)
        die_st("cft_div", st);
    dec_digits(&big, q, 6, out, cap);
}

static void report(runstate *R, double t_ref, double t_pix,
                   const char *backend, uint32_t status)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    char chain[65], pchain[65], cr[DECMAX], ci[DECMAX], mm[64], err[64];
    char pix[64];
    double rps = t_ref > 0 ? (double)R->k / t_ref : 0.0;
    double pps = t_pix > 0 ? (double)R->pixel_work / t_pix : 0.0;
    double eps = t_pix > 0 ? (double)O->width * O->width / t_pix : 0.0;
    uint64_t cmp_diff = 0, cmp_tot = 0;

    hex32(R->chain, chain);
    hex32(R->pixchain, pchain);
    val_to_dec(fi, R->cr, cr, sizeof cr);
    val_to_dec(fi, R->ci, ci, sizeof ci);
    if (R->have_min)
        dec_digits(fi, R->minmag, 6, mm, sizeof mm);
    else
        snprintf(mm, sizeof mm, "-");
    centre_error_pixels(R, err, sizeof err);
    {
        fmt_info big;
        big.fmt = CFT_FP256;
        big.esz = cft_format_size(CFT_FP256);
        dec_digits(&big, R->pixscale, 6, pix, sizeof pix);
    }
    if (O->compare_path)
        compare_pixels(R, &cmp_diff, &cmp_tot);

    if (O->csv) {
        printf("backend,format,engine,batch,steps_per_call,period,zoom_exp,"
               "width,ref_iters,k,escaped_at,minmag,minmag_at,"
               "centre_err_pixels,escaped,glitched,interior,esc_min,"
               "esc_max,pixel_iterations,ref_seconds,pixel_seconds,"
               "ref_iters_per_s,pixel_iters_per_s,pixels_per_s,flags,"
               "chain,pixchain,compare_differ,compare_total,"
               "centre_re,centre_im,ref_ops,pixel_ops\n");
        printf("%s,%s,%s,%" PRIu64 ",%" PRIu64 ",%u,%d,%u,%" PRIu64
               ",%" PRIu64 ",%" PRIu64 ",%s,%" PRIu64 ",%s,%" PRIu64
               ",%" PRIu64 ",%" PRIu64 ",%u,%u,%" PRIu64
               ",%.6f,%.6f,%.1f,%.1f,%.1f,0x%02x,%s,%s,%" PRIu64
               ",%" PRIu64 ",%s,%s,%" PRIu64 ",%" PRIu64 "\n",
               backend, cft_format_name(fi->fmt),
               O->use_program ? "program" : "loop",
               (uint64_t)O->batch, (uint64_t)O->reps, O->period,
               O->zoom_exp, O->width, O->ref_iters, R->k, R->escaped_at,
               mm, R->minmag_at, err, R->n_escaped, R->n_glitched,
               R->n_interior,
               R->n_escaped ? R->esc_min : 0, R->esc_max, R->pixel_work,
               t_ref, t_pix, rps, pps, eps, (unsigned)status,
               chain, pchain, cmp_diff, cmp_tot, cr, ci,
               R->ops_ref, R->ops_pix);
        return;
    }

    printf("\n");
    printf("  backend       %s\n", backend);
    printf("  reference     %s, p = %d\n", cft_format_name(fi->fmt),
           fi->prec);
    printf("  engine        %s, %" PRIu64 " iterations per call\n",
           O->use_program ? "sequencer program" : "host cft_run loop",
           (uint64_t)O->reps);
    printf("  centre        %s\n", cr);
    printf("                + %s i   (period-%u nucleus at the tip)\n",
           ci, O->period);
    printf("  view radius   2^-%d, %u x %u pixels, one pixel = %s\n",
           O->zoom_exp, O->width, O->width, pix);
    printf("  centre error  %s pixels  (|c in %s  -  c in fp256|)\n",
           err, cft_format_name(fi->fmt));
    printf("  orbit         %" PRIu64 " iterations", R->k);
    if (R->escaped_at)
        printf(", ESCAPED at %" PRIu64, R->escaped_at);
    printf("\n");
    printf("  smallest |z|^2 %s at k = %" PRIu64 "\n", mm, R->minmag_at);
    printf("  library calls %" PRIu64 " for the orbit\n", R->eng.calls);
    if (!O->no_pixels) {
        printf("  pixels        %" PRIu64 " escaped, %" PRIu64
               " glitched, %" PRIu64 " interior\n",
               R->n_escaped, R->n_glitched, R->n_interior);
        if (R->n_escaped)
            printf("                escape iterations %u..%u\n",
                   R->esc_min, R->esc_max);
        printf("  glitch test   |Z+d|^2 < 2^-%d^2 |Z|^2  (2^-p/4 at "
               "p = %d)\n", O->glitch_bits, R->pf->prec);
        printf("  pixel work    %" PRIu64 " pixel-iterations at fp64\n",
               R->pixel_work);
    }
    if (O->compare_path)
        printf("  compared      %" PRIu64 " of %" PRIu64
               " pixels differ from %s\n", cmp_diff, cmp_tot,
               O->compare_path);
    printf("  flags seen    0x%02x%s\n", (unsigned)FLAGS_SEEN,
           FLAGS_TRUSTED ? "" : "  (this backend cannot read flags)");
    /* The device's 754 status word (7.1), lowered once after the setup
     * and never touched since, sampled before this report did any
     * rounding of its own. Nothing but the run raises anything, so the
     * two must agree - which is a free cross-check on the claim that
     * the steps above are the only source of flags. */
    printf("  status word   0x%02x%s\n", (unsigned)status,
           status == FLAGS_SEEN
               ? " (agrees with the union above)"
               : "  DISAGREES WITH THE UNION ABOVE");
    printf("  time          %.3f s reference, %.3f s pixels\n",
           t_ref, t_pix);
    printf("  throughput    %.0f reference iterations/s at %s "
           "(%.0f elementwise ops/s)\n", rps, cft_format_name(fi->fmt),
           t_ref > 0 ? (double)R->ops_ref / t_ref : 0.0);
    if (!O->no_pixels)
        printf("                %.0f pixel-iterations/s at fp64 "
               "(%.0f elementwise ops/s), %.1f pixels/s\n", pps,
               t_pix > 0 ? (double)R->ops_pix / t_pix : 0.0, eps);
    printf("  orbit chain   %s\n", chain);
    if (!O->no_pixels)
        printf("  pixel chain   %s\n", pchain);
    printf("\n");
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-zoom - a deep-zoom Mandelbrot reference orbit on libcft\n"
"\n"
"  --format fp32|fp64|fp128|fp256   the REFERENCE format (default fp256);\n"
"                           the perturbed pixels are always fp64\n"
"  --engine program|loop    orbit sequencer program (default) or host loop\n"
"  --period N               the tip nucleus period to derive (default 51)\n"
"  --centre RE,IM           use this centre instead of deriving one\n"
"  --zoom-exp E             view radius 2^-E (default 196)\n"
"  --width W                W x W pixels, W a power of two (default 64)\n"
"  --ref-iters N            reference orbit length (default 100000)\n"
"  --pixel-iters N          per-pixel iteration cap (default 4096)\n"
"  --batch N                pixels in flight per call (default 4096)\n"
"  --steps-per-call N       orbit program trip count (default 1024)\n"
"  --glitch-bits B          glitch when |Z+d| < 2^-B |Z| (default p/4)\n"
"  --ref-offset N           move the reference N pixels off the nucleus\n"
"  --checkpoint PATH        write a resumable checkpoint of the orbit\n"
"  --checkpoint-interval S  seconds between checkpoints (default 10)\n"
"  --resume                 continue from --checkpoint\n"
"  --stop-after-passes N    stop cleanly after N orbit engine calls\n"
"  --time S                 stop cleanly after S seconds\n"
"  --orbit PATH             one line per orbit point, exact decimal\n"
"  --pixels PATH            one line per pixel\n"
"  --pgm PATH               an escape-iteration image\n"
"  --compare-pixels PATH    count pixels differing from that records file\n"
"  --no-pixels              reference orbit only\n"
"  --artifact PATH          an .xclbin; omit for the software backend\n"
"  --csv                    machine-readable summary\n"
"  --quiet                  summary only\n"
"\n"
"docs/ZOOM.md is the argument; host/tests/zoom_check.py is the gate.\n");
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        die("that option needs a value");
    return argv[++(*i)];
}

int main(int argc, char **argv)
{
    options O;
    fmt_info fi, pf;
    runstate R;
    cft_caps caps;
    cft_status st;
    double t0, tckpt, t_ref = 0.0, t_pix = 0.0;
    int i, stopped;

    memset(&O, 0, sizeof O);
    O.fmt = CFT_FP256;
    O.use_program = 1;
    O.period = 51;
    O.zoom_exp = 196;
    O.width = 64;
    O.ref_iters = 100000;
    O.pixel_iters = 4096;
    O.batch = 4096;
    O.reps = 1024;
    O.glitch_bits = -1;
    O.ckpt_interval = 10.0;
    O.stop_after_passes = -1;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "--format")) {
            const char *v = need(argc, argv, &i);
            if (!strcmp(v, "fp32")) O.fmt = CFT_FP32;
            else if (!strcmp(v, "fp64")) O.fmt = CFT_FP64;
            else if (!strcmp(v, "fp128")) O.fmt = CFT_FP128;
            else if (!strcmp(v, "fp256")) O.fmt = CFT_FP256;
            else die("--format takes fp32, fp64, fp128 or fp256");
        } else if (!strcmp(a, "--engine")) {
            const char *v = need(argc, argv, &i);
            if (!strcmp(v, "program")) O.use_program = 1;
            else if (!strcmp(v, "loop")) O.use_program = 0;
            else die("--engine takes program or loop");
        }
        else if (!strcmp(a, "--period"))
            O.period = (uint32_t)strtoul(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--centre") || !strcmp(a, "--center"))
            O.centre_s = need(argc, argv, &i);
        else if (!strcmp(a, "--zoom-exp"))
            O.zoom_exp = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--width"))
            O.width = (uint32_t)strtoul(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--ref-iters"))
            O.ref_iters = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--pixel-iters"))
            O.pixel_iters = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--batch")) {
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
            if (!O.batch) die("--batch must be positive");
        } else if (!strcmp(a, "--steps-per-call")) {
            O.reps = (uint32_t)strtoul(need(argc, argv, &i), NULL, 10);
            if (!O.reps) die("--steps-per-call must be positive");
        }
        else if (!strcmp(a, "--glitch-bits"))
            O.glitch_bits = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--ref-offset"))
            O.ref_offset = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--checkpoint")) O.ckpt = need(argc, argv, &i);
        else if (!strcmp(a, "--checkpoint-interval"))
            O.ckpt_interval = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--resume")) O.resume = 1;
        else if (!strcmp(a, "--stop-after-passes"))
            O.stop_after_passes = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--time"))
            O.time_limit = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--orbit")) O.orbit_path = need(argc, argv, &i);
        else if (!strcmp(a, "--pixels")) O.pixels_path = need(argc, argv, &i);
        else if (!strcmp(a, "--pgm")) O.pgm_path = need(argc, argv, &i);
        else if (!strcmp(a, "--compare-pixels"))
            O.compare_path = need(argc, argv, &i);
        else if (!strcmp(a, "--no-pixels")) O.no_pixels = 1;
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--csv")) O.csv = 1;
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-zoom: unknown option %s\n", a);
            return 2;
        }
    }

    if (O.width == 0 || (O.width & (O.width - 1)) != 0)
        die("--width must be a power of two, so that a pixel offset is "
            "exact in every format");
    if (!O.ref_iters)
        die("--ref-iters must be positive");

    st = cft_open(O.artifact, 0, &DEV);
    if (st != CFT_OK)
        die_st("cft_open", st);

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(DEV, &caps) != CFT_OK)
        die("cft_get_caps failed");
    if (!(caps.format_mask & (1u << (unsigned)O.fmt)))
        die("this backend does not carry that format");
    if (!(caps.format_mask & (1u << (unsigned)CFT_FP64)))
        die("this backend does not carry binary64, which the pixels need");
    FLAGS_TRUSTED = caps.flags_readable != 0;

    measure_format(&fi, O.fmt);
    measure_format(&pf, CFT_FP64);
    if (O.glitch_bits < 0)
        O.glitch_bits = pf.prec / 4;

    memset(&R, 0, sizeof R);
    R.fi = &fi;
    R.pf = &pf;
    R.opt = &O;
    R.orb_r = (uint8_t *)xcalloc((size_t)O.ref_iters + 2, fi.esz);
    R.orb_i = (uint8_t *)xcalloc((size_t)O.ref_iters + 2, fi.esz);
    R.pix = (pixrec *)xcalloc((size_t)O.width * O.width, sizeof(pixrec));

    /* The geometry, at binary256 whatever the reference format is: the
     * view radius is a power of two and one pixel is that over the
     * width, so both are exact in every format that can hold them. */
    {
        fmt_info g;
        uint32_t w = O.width, sh = 0;
        g.fmt = CFT_FP256;
        g.esz = cft_format_size(CFT_FP256);
        while (w > 1) { w >>= 1; sh++; }
        val_pow2(&g, -O.zoom_exp, R.radius);
        val_pow2(&g, 1 - O.zoom_exp - (int)sh, R.pixscale);
    }

    if (!O.quiet && !O.csv)
        printf("cft-zoom: %s backend, reference %s (p = %d), pixels fp64 "
               "(p = %d), %s engine\n", caps.backend,
               cft_format_name(fi.fmt), fi.prec, pf.prec,
               O.use_program ? "sequencer-program" : "host-loop");

    /* The centre. Derived at binary256 whatever the reference format
     * is, because a format that cannot hold the centre cannot be
     * trusted to find it either - and then rounded ONCE into the
     * run's format, which is exactly what a renderer using that
     * format would get. */
    {
        fmt_info f256;
        measure_format(&f256, CFT_FP256);
        if (O.centre_s) {
            char buf[2 * DECMAX];
            char *comma;
            snprintf(buf, sizeof buf, "%s", O.centre_s);
            comma = strchr(buf, ',');
            if (!comma)
                die("--centre takes RE,IM");
            *comma = 0;
            if (!val_from_dec(&f256, buf, R.c256r) ||
                !val_from_dec(&f256, comma + 1, R.c256i))
                die("--centre is not a pair binary256 holds exactly");
        } else {
            const fmt_info *save = R.fi;
            R.fi = &f256;
            derive_centre(&R);
            R.fi = save;
        }
        /* --ref-offset moves the REFERENCE off the nucleus by whole
         * pixels while the view stays where it was - which is how a
         * renderer that picked its reference carelessly behaves, and
         * the way to make the glitch criterion fire. The shift is an
         * exact power-of-two multiple, so it costs no rounding. */
        if (O.ref_offset) {
            uint8_t shift[MAX_ESZ], nref[MAX_ESZ];
            int64_t v = O.ref_offset;
            val_from_i64(&f256, v, shift);
            run1(CFT_MUL, CFT_FP256, shift, R.pixscale, NULL, nref);
            run1(CFT_ADD, CFT_FP256, R.c256r, NULL, nref, R.c256r);
            (void)shift;
        }
        if (O.fmt == CFT_FP256) {
            memcpy(R.cr, R.c256r, fi.esz);
            memcpy(R.ci, R.c256i, fi.esz);
        } else {
            uint32_t f = 0;
            st = cft_convert(DEV, CFT_FP256, O.fmt, CFT_RNE, R.c256r, R.cr,
                             1, &f);
            if (st != CFT_OK) die_st("cft_convert", st);
            f = 0;
            st = cft_convert(DEV, CFT_FP256, O.fmt, CFT_RNE, R.c256i, R.ci,
                             1, &f);
            if (st != CFT_OK) die_st("cft_convert", st);
        }
    }

    /* The status word (754-2019 7.1) is lowered ONCE, here, now that
     * the setup - which deliberately raises inexact while measuring p
     * and deriving the centre - is done. From this point it holds what
     * the run raised, and the report cross-checks it against the union
     * of the calls' flags_out. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);
    FLAGS_SEEN = 0;
    OPS_ISSUED = 0;

    orbit_engine_init(&R.eng, &fi, R.cr, R.ci, O.use_program, O.reps);
    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R);
    }
    if (O.orbit_path) {
        R.orbf = fopen(O.orbit_path, "wb");
        if (!R.orbf)
            die("cannot write the orbit file");
        /* not resume-aware: the checkpoint's chain is what spans an
         * interruption, exactly as the Collatz explorer's records file
         * is not resume-aware either */
    }

    t0 = now_s();
    tckpt = t0;
    stopped = run_reference(&R, t0, &tckpt);
    t_ref = now_s() - t0;
    R.ops_ref = OPS_ISSUED;
    if (R.orbf)
        fclose(R.orbf);
    /* After the timed phase, and outside it: a statistic over the
     * finished orbit is not part of computing the orbit. */
    compute_minmag(&R);

    if (!stopped && !O.no_pixels && R.k >= 2) {
        double p0 = now_s();
        run_pixels(&R);
        R.ops_pix = OPS_ISSUED - R.ops_ref;
        pixel_chain_and_dump(&R);
        write_pgm(&R);
        t_pix = now_s() - p0;
    }

    /* Sampled here, before the report's own decimal conversions and
     * division round anything into it. */
    report(&R, t_ref, t_pix, caps.backend, cft_save_all_flags(DEV));

    orbit_engine_free(&R.eng);
    free(R.orb_r);
    free(R.orb_i);
    free(R.pix);
    cft_close(DEV);
    return 0;
}
