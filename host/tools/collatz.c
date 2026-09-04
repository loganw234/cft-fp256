/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-collatz - the Collatz conjecture, computed as a PROOF rather
 * than as a plausible number.
 *
 *   ./cft-collatz --from 1 --count 100000
 *   ./cft-collatz --format fp64 --engine loop --csv
 *   ./cft-collatz --mode deep --values 27,703,626331
 *   ./cft-collatz --checkpoint run.ckpt --resume
 *
 * ---------------------------------------------------------------
 * Why this workload, on this contract
 * ---------------------------------------------------------------
 *
 * Iterate n -> n/2 when n is even, 3n+1 when it is odd, until n
 * reaches 1. Record the stopping time and the peak. It is a toy, and
 * it is chosen because every operation the iteration needs is one this
 * library performs EXACTLY over a range no fixed-width integer type
 * reaches:
 *
 *   - binary256 represents every integer in [0, 2^p] exactly, p = 237.
 *     That is 2^173 times the reach of int64 and 2^184 times the reach
 *     of binary64.
 *   - n * 0.5 is a multiply by a power of two: exact for every n >= 1,
 *     because it only decrements the exponent.
 *   - 3n+1 is ONE fused multiply-add, so it rounds once or not at all.
 *   - parity, the comparisons and the conditional move are the tile's
 *     own opcodes and none of them rounds anything.
 *
 * So while the trajectory stays inside the format, the floating-point
 * values ARE the integers, and the stopping time this prints is a
 * theorem rather than an estimate. The moment that stops being true,
 * the library says so: the fused multiply-add raises INEXACT, and this
 * tool treats that as "this element's result is no longer a proof" -
 * it stops the element, records the step at which exactness ran out,
 * and never counts it as verified.
 *
 * ---------------------------------------------------------------
 * The exactness witness, and why the flag alone is not enough
 * ---------------------------------------------------------------
 *
 * cft_run and cft_program_run report the UNION of the exception flags
 * over a whole call. That is the right contract - 754's flags are
 * sticky and per-run - but it cannot say WHICH element of a batch left
 * exact arithmetic, and a per-element answer is exactly what a
 * verification needs.
 *
 * So each step also computes a per-element witness, in the library's
 * own arithmetic, at the cost of one extra fused multiply-add:
 *
 *     y   = fma(n, 3, 1)          the step
 *     res = fma(n, -3, y)         the residual, y - 3n
 *     exact  <=>  res == 1
 *
 * The residual is the integer 1 + (y - (3n+1)), whose magnitude is at
 * most 1 + ulp(y)/2, so for every y below 2^(2p-2) it is representable
 * and the second FMA returns it without rounding. It answers the
 * question the flag answers, one element at a time. This tool asserts
 * on every call that the two agree in BOTH directions:
 *
 *     (flags & INEXACT) != 0   <=>   some live element's witness failed
 *
 * and stops with an error if they ever disagree. That assertion is
 * what makes the flag load-bearing rather than decorative, and it is
 * the property the negative control in docs/COLLATZ.md breaks. The
 * witness's domain is checked too: after every call the host verifies
 * that no peak has reached 2^(2p-4).
 *
 * ---------------------------------------------------------------
 * Parity without a rounding operation
 * ---------------------------------------------------------------
 *
 * The obvious parity test is q = n * 0.5, floor it, and compare. Both
 * ways of flooring it are wrong here, for different reasons:
 *
 *   - the magic-constant trick, (q + 2^(p-1)) - 2^(p-1), RAISES INEXACT
 *     on every odd n, because q is then a half-integer and the sum is
 *     not representable. It would flood the very flag this tool uses
 *     as its detector.
 *   - cft_rint(exact = 0) never signals, and is correct, but it is a
 *     COMPOSED operation - a host-side sequence around cft_run - and
 *     so it is not in the sequencer's opcode set. A step built on it
 *     could never become an on-chip program.
 *
 * This tool uses the integer opcodes instead, which are quiet by
 * specification and are in the sequencer's set. For a positive
 * floating-point integer n = 2^E * (1 + f), the coefficient of 2^0 in
 * the significand is fraction bit (p-1-E), so
 *
 *     odd(n)  <=>  ( encoding(n) >> ((p-1) + bias - biased_exponent(n)) ) & 1
 *
 * with the shift amount itself computed by ISHR/ISUB from n's own
 * encoding. At E = 0 the shift reaches the low bit of the biased
 * exponent field, which is the low bit of the bias - odd for every
 * IEEE binary format, since the bias is 2^(w-1)-1 - and n = 1 is the
 * only integer with E = 0 and it is odd, so that edge is right rather
 * than lucky. Five integer opcodes, no rounding, no flags, and
 * expressible on-chip.
 *
 * The other edge is E > p-1, where the shift amount would go negative:
 * there the significand has no 2^0 coefficient at all, because ulp is
 * at least 2, so EVERY representable value at or above 2^p is even.
 * Two more opcodes say so - the parity is ANDed with (n < 2^p) - and
 * that is not a formality: without it a value above 2^p reads as odd,
 * takes an odd step that cannot be exact, and the trajectory is
 * abandoned several steps too early. With it, a trajectory that climbs
 * past 2^p halves back down and carries on being a proof.
 *
 * ---------------------------------------------------------------
 * Where the step runs
 * ---------------------------------------------------------------
 *
 * --engine program (the default) compiles the nineteen-instruction
 * step into ONE orbit-sequencer program (docs/SEQUENCER.md) and runs
 * up to --steps-per-call iterations of it per library call. The
 * sequencer's escape masking is exactly the semantics this workload
 * wants: SETACT narrows the active set, an inactive lane writes
 * nothing, deposits nothing and raises no flag, and the early exit
 * fires when the last lane converges. Convergence masking is
 * therefore free, and the four per-lane results - final n, stopping
 * time, peak, escape flag - come back through the deposit buffer,
 * which is what DEPOSIT is for.
 *
 * --engine loop issues the same step as twenty-three cft_run passes per
 * iteration from the host. It exists to be compared against: the two
 * must agree bit for bit on every element, and it is what a device
 * without the sequencer would run. The three extra passes are the
 * price of doing by hand what the active mask does for free -
 * neutralising the odd branch for elements that are no longer live,
 * so that a finished element cannot push a flag into the run.
 *
 * ---------------------------------------------------------------
 * Determinism
 * ---------------------------------------------------------------
 *
 * The same starting range produces bit-identical results and a
 * bit-identical checkpoint whatever the batch size, the engine, the
 * host or the backend. Nothing here reduces across elements, nothing
 * depends on arrival order, and the hash chain is taken over records
 * in starting-value order rather than in completion order. Both
 * properties are tested rather than asserted - see
 * host/tests/collatz_check.py and `make -C host collatztest`.
 *
 * No constant below is transcribed. p is measured from the library by
 * finding the smallest k for which 2^k + 1 raises inexact; the bias
 * follows from p and the format width; 0.5, 3 and -3 are converted
 * from integers; and even SHA-256's round constants are derived from
 * the cube roots of the primes rather than typed in.
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
#define DECMAX  512         /* a decimal integer this tool will print */

static void die(const char *what)
{
    fprintf(stderr, "cft-collatz: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-collatz: %s: %s%s%s\n", what, cft_strerror(st),
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
 * of the first primes, so that is how they are computed here - by
 * integer search, with no floating point and nothing to mistype. The
 * cross-check in host/tests/collatz_check.py recomputes the whole
 * chain with Python's hashlib, which is what proves the derivation.
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

/* a << s, 0 <= s < 128 */
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

/* exact 64 x 64 -> 128 */
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

/* a * b; 1 when the product does not fit 128 bits */
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

/* v^root, 1 on overflow */
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

/* floor(frac(p^(1/root)) * 2^32), root 2 or 3: the low 32 bits of
 * floor((p << (32*root))^(1/root)), found by binary search over an
 * exact 128-bit power. */
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
    size_t     esz;        /* bytes per element */
    int        width;      /* bits */
    int        prec;       /* p, significand bits, hidden one included */
    int        exp_w;      /* width - p */
    uint64_t   bias;       /* 2^(exp_w - 1) - 1 */
} fmt_info;

static cft_device *DEV;

static void run1(cft_op op, cft_format fmt, const void *a, const void *b,
                 const void *c, void *d, uint32_t *fl)
{
    cft_status st = cft_run(DEV, op, fmt, CFT_RNE, a, b, c, d, 1, fl, NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
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
        run1(CFT_ADD, fmt, pow, NULL, one, sum, &fl);
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
 * Values: build them, print them, read them
 * =================================================================== */

/* a little-endian integer bit pattern of the element's width */
static void bits_from_u64(const fmt_info *fi, uint64_t v, uint8_t *out)
{
    size_t i;
    memset(out, 0, fi->esz);
    for (i = 0; i < 8 && i < fi->esz; i++)
        out[i] = (uint8_t)(v >> (8 * i));
}

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

/* An exact decimal integer string. cft_to_decimal_char(digits = 0) is
 * 5.12.2's exact conversion, which for an integer value has no
 * fractional digits to lose; the "d.ddde+E" form it writes is shifted
 * back into a plain integer here. */
static void val_to_dec(const fmt_info *fi, const void *v, char *out,
                       size_t cap)
{
    char raw[1024], digits[1024];
    size_t len = 0, nd = 0, want, need, i;
    cft_status st;
    const char *p;
    long expo = 0;
    int neg = 0;

    st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, 0, raw, sizeof raw,
                             &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);

    p = raw;
    if (*p == '-') { neg = 1; p++; }
    else if (*p == '+') p++;
    while (*p && *p != 'e' && *p != 'E') {
        if (*p != '.') {
            if (nd + 1 >= sizeof digits)
                die("decimal too long");
            digits[nd++] = *p;
        }
        p++;
    }
    if (*p == 'e' || *p == 'E')
        expo = strtol(p + 1, NULL, 10);
    digits[nd] = 0;

    if (nd == 0 || (nd == 1 && digits[0] == '0')) {
        if (cap < 2)
            die("decimal buffer too small");
        out[0] = '0';
        out[1] = 0;
        return;
    }
    if (expo < 0)
        die("that value is not an integer");
    want = (size_t)expo + 1;
    if (want < nd)
        die("that value is not an integer");
    need = want + (size_t)neg + 1;
    if (need > cap)
        die("decimal buffer too small");
    i = 0;
    if (neg)
        out[i++] = '-';
    memcpy(out + i, digits, nd);
    for (; nd < want; nd++)
        out[i + nd] = '0';
    out[i + want] = 0;
}

/* Parse a decimal integer into the format; refuse anything the format
 * cannot hold exactly, because an inexact start is not a start. */
static int val_from_dec(const fmt_info *fi, const char *s, void *out)
{
    const char *arr[1];
    uint32_t fl = 0;
    cft_status st;
    arr[0] = s;
    st = cft_from_decimal_char(DEV, fi->fmt, CFT_RNE, arr, out, 1, NULL, &fl);
    if (st != CFT_OK)
        return 0;
    if (fl & (CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW))
        return 0;
    return 1;
}

static int val_lt(const fmt_info *fi, const void *a, const void *b)
{
    uint8_t r[MAX_ESZ], zero[MAX_ESZ];
    run1(CFT_CMPLT, fi->fmt, a, b, NULL, r, NULL);
    memset(zero, 0, fi->esz);
    return memcmp(r, zero, fi->esz) != 0;
}

static int pred_true(const fmt_info *fi, const void *v)
{
    uint8_t zero[MAX_ESZ];
    memset(zero, 0, fi->esz);
    return memcmp(v, zero, fi->esz) != 0;
}

static uint64_t val_to_u64(const fmt_info *fi, const void *v)
{
    uint64_t out = 0;
    uint32_t fl = 0;
    cft_status st = cft_cvt_to_u64(DEV, fi->fmt, CFT_RTZ, 1, v, &out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_to_u64", st);
    if (fl)
        die("a step count did not fit a 64-bit integer exactly");
    return out;
}

/* ===================================================================
 * The step, as an orbit-sequencer program
 * =================================================================== */
enum {
    K_HALF = 0, K_ONE, K_THREE, K_MTHREE, K_ZERO, K_2P,
    K_IPM1, K_ISH, K_I1, N_CONST
};
enum { R_N = 0, R_CNT, R_PEAK, R_Q, R_T, R_ODD, R_NN, R_Y, R_EX, R_ND,
       R_ESC };

/* control codes, docs/SEQUENCER.md */
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };

#define DEPOSITS 4          /* n, steps, peak, escaped */

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

/* The whole workload, as one program image. */
static uint8_t *build_program(const fmt_info *fi, uint32_t reps,
                              size_t *bytes_out, uint32_t *insn_out)
{
    uint64_t ins[64];
    uint32_t n = 0;
    uint8_t consts[N_CONST][MAX_ESZ];
    uint8_t *img;
    size_t esz = fi->esz, i, off;

    val_pow2(fi, -1, consts[K_HALF]);
    val_from_i64(fi, 1, consts[K_ONE]);
    val_from_i64(fi, 3, consts[K_THREE]);
    val_from_i64(fi, -3, consts[K_MTHREE]);
    val_from_i64(fi, 0, consts[K_ZERO]);
    val_pow2(fi, fi->prec, consts[K_2P]);
    bits_from_u64(fi, (uint64_t)(fi->prec - 1), consts[K_IPM1]);
    bits_from_u64(fi, (uint64_t)(fi->prec - 1) + fi->bias, consts[K_ISH]);
    bits_from_u64(fi, 1, consts[K_I1]);

    ins[n++] = ctl(C_REPEAT, 0, reps);
    /* an element already at 1 is finished: drop it before it steps */
    ins[n++] = alu(CFT_CMPLT, R_ND, K_ONE, R_N, 0, 1, 0, 0);
    ins[n++] = ctl(C_SETACT, R_ND, 0);
    /* q = n * 0.5, exact for every n >= 1 */
    ins[n++] = alu(CFT_MUL, R_Q, R_N, K_HALF, 0, 0, 1, 0);
    /* parity from the encoding: five quiet integer opcodes */
    ins[n++] = alu(CFT_ISHR, R_T, R_N, K_IPM1, 0, 0, 1, 0);
    ins[n++] = alu(CFT_ISUB, R_T, K_ISH, R_T, 0, 1, 0, 0);
    ins[n++] = alu(CFT_ISHR, R_T, R_N, R_T, 0, 0, 0, 0);
    ins[n++] = alu(CFT_IAND, R_T, R_T, K_I1, 0, 0, 1, 0);
    ins[n++] = alu(CFT_ICMPLT, R_ODD, K_ZERO, R_T, 0, 1, 0, 0);
    /* above 2^p the significand has no units bit and every value is
     * even; the shift above would have wrapped, so say it explicitly */
    ins[n++] = alu(CFT_CMPLT, R_T, R_N, K_2P, 0, 0, 1, 0);
    ins[n++] = alu(CFT_MIN, R_ODD, R_ODD, R_T, 0, 0, 0, 0);
    /* the odd branch is neutralised for even elements, so that the
     * only fused multiply-add that can round is one this element
     * actually takes */
    ins[n++] = alu(CFT_SELECT, R_NN, R_N, K_ONE, R_ODD, 0, 1, 0);
    ins[n++] = alu(CFT_FMA, R_Y, R_NN, K_THREE, K_ONE, 0, 1, 1);
    /* the witness: res = y - 3n, which is 1 exactly when y was exact */
    ins[n++] = alu(CFT_FMA, R_EX, R_NN, K_MTHREE, R_Y, 0, 1, 0);
    ins[n++] = alu(CFT_CMPEQ, R_EX, R_EX, K_ONE, 0, 0, 1, 0);
    ins[n++] = alu(CFT_SELECT, R_ESC, K_ZERO, K_ONE, R_EX, 1, 1, 0);
    ins[n++] = ctl(C_SETACT, R_EX, 0);
    /* committed only by elements whose step was exact */
    ins[n++] = alu(CFT_SELECT, R_N, R_Y, R_Q, R_ODD, 0, 0, 0);
    ins[n++] = alu(CFT_ADD, R_CNT, R_CNT, 0, K_ONE, 0, 0, 1);
    ins[n++] = alu(CFT_MAX, R_PEAK, R_PEAK, R_N, 0, 0, 0, 0);
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_ACTALL, 0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_N, 0);
    ins[n++] = ctl(C_DEPOSIT, R_CNT, 0);
    ins[n++] = ctl(C_DEPOSIT, R_PEAK, 0);
    ins[n++] = ctl(C_DEPOSIT, R_ESC, 0);
    ins[n++] = ctl(C_HALT, 0, 0);

    *insn_out = n;
    *bytes_out = 32 + (size_t)N_CONST * esz + (size_t)n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);                     /* version */
    put_le32(img + 8, n);
    put_le32(img + 12, (uint32_t)N_CONST);
    put_le32(img + 16, DEPOSITS);
    put_le32(img + 20, (uint32_t)fi->fmt);
    off = 32;
    for (i = 0; i < N_CONST; i++) {
        memcpy(img + off, consts[i], esz);
        off += esz;
    }
    for (i = 0; i < n; i++) {
        put_le64(img + off, ins[i]);
        off += 8;
    }
    return img;
}

/* ===================================================================
 * The batch engine
 * =================================================================== */
typedef struct {
    const fmt_info *fi;
    size_t     cap;
    int        use_program;
    uint32_t   reps;
    uint32_t   n_insns;

    /* lane state */
    uint8_t   *n, *cnt, *peak, *esc, *live;
    /* scratch for the host-loop engine */
    uint8_t   *q, *t, *odd, *nn, *y, *ex, *nd, *cand, *tmp;
    uint8_t   *bc[N_CONST];

    /* the program route */
    cft_program *prog;
    uint8_t   *dep;
    uint32_t  *counts;

    /* host-side bookkeeping */
    uint8_t   *start;
    size_t    *rec;

    uint32_t   flags_seen;
    int        flags_trusted;
    uint64_t   calls;
    uint64_t   ops;          /* elementwise opcode issues, host loop only */
} engine;

static void bcast(const fmt_info *fi, uint8_t *dst, const uint8_t *v,
                  size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        memcpy(dst + i * fi->esz, v, fi->esz);
}

static void engine_init(engine *E, const fmt_info *fi, size_t cap,
                        int use_program, uint32_t reps, int flags_trusted)
{
    size_t esz = fi->esz, i;
    uint8_t c[MAX_ESZ];

    memset(E, 0, sizeof *E);
    E->fi = fi;
    E->cap = cap;
    E->use_program = use_program;
    E->reps = reps;
    E->flags_trusted = flags_trusted;

    E->n     = (uint8_t *)xcalloc(cap, esz);
    E->cnt   = (uint8_t *)xcalloc(cap, esz);
    E->peak  = (uint8_t *)xcalloc(cap, esz);
    E->esc   = (uint8_t *)xcalloc(cap, esz);
    E->live  = (uint8_t *)xcalloc(cap, esz);
    E->start = (uint8_t *)xcalloc(cap, esz);
    E->rec   = (size_t *)xcalloc(cap, sizeof(size_t));

    if (use_program) {
        size_t bytes = 0;
        uint8_t *img = build_program(fi, reps, &bytes, &E->n_insns);
        cft_status st = cft_program_load(DEV, img, bytes, &E->prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load", st);
        E->dep = (uint8_t *)xcalloc(cap * DEPOSITS, esz);
        E->counts = (uint32_t *)xcalloc(cap, sizeof(uint32_t));
    } else {
        E->q    = (uint8_t *)xcalloc(cap, esz);
        E->t    = (uint8_t *)xcalloc(cap, esz);
        E->odd  = (uint8_t *)xcalloc(cap, esz);
        E->nn   = (uint8_t *)xcalloc(cap, esz);
        E->y    = (uint8_t *)xcalloc(cap, esz);
        E->ex   = (uint8_t *)xcalloc(cap, esz);
        E->nd   = (uint8_t *)xcalloc(cap, esz);
        E->cand = (uint8_t *)xcalloc(cap, esz);
        E->tmp  = (uint8_t *)xcalloc(cap, esz);
        for (i = 0; i < N_CONST; i++)
            E->bc[i] = (uint8_t *)xcalloc(cap, esz);
        val_pow2(fi, -1, c);      bcast(fi, E->bc[K_HALF], c, cap);
        val_from_i64(fi, 1, c);   bcast(fi, E->bc[K_ONE], c, cap);
        val_from_i64(fi, 3, c);   bcast(fi, E->bc[K_THREE], c, cap);
        val_from_i64(fi, -3, c);  bcast(fi, E->bc[K_MTHREE], c, cap);
        val_from_i64(fi, 0, c);   bcast(fi, E->bc[K_ZERO], c, cap);
        val_pow2(fi, fi->prec, c); bcast(fi, E->bc[K_2P], c, cap);
        bits_from_u64(fi, (uint64_t)(fi->prec - 1), c);
        bcast(fi, E->bc[K_IPM1], c, cap);
        bits_from_u64(fi, (uint64_t)(fi->prec - 1) + fi->bias, c);
        bcast(fi, E->bc[K_ISH], c, cap);
        bits_from_u64(fi, 1, c);  bcast(fi, E->bc[K_I1], c, cap);
    }
}

static void engine_free(engine *E)
{
    size_t i;
    free(E->n); free(E->cnt); free(E->peak); free(E->esc); free(E->live);
    free(E->start); free(E->rec);
    free(E->q); free(E->t); free(E->odd); free(E->nn); free(E->y);
    free(E->ex); free(E->nd); free(E->cand); free(E->tmp);
    for (i = 0; i < N_CONST; i++)
        free(E->bc[i]);
    free(E->dep);
    free(E->counts);
    if (E->prog)
        cft_program_free(E->prog);
}

static void runN(cft_op op, const fmt_info *fi, const void *a, const void *b,
                 const void *c, void *d, size_t n, uint32_t *fl)
{
    uint32_t r = 0;
    cft_status st = cft_run(DEV, op, fi->fmt, CFT_RNE, a, b, c, d, n, &r,
                            NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    *fl |= r;
}

/* One pass of the engine over the `n` live slots: up to `reps` Collatz
 * steps for the program engine, exactly one for the host loop. */
static size_t engine_pass(engine *E, size_t n)
{
    const fmt_info *fi = E->fi;
    size_t esz = fi->esz, i, newly_escaped = 0;
    uint32_t f = 0;

    if (!n)
        return 0;

    if (E->use_program) {
        cft_status st;
        uint32_t bus = 0;
        st = cft_program_run(E->prog, E->n, E->cnt, E->peak, E->dep,
                             E->counts, n, &f, &bus);
        if (st != CFT_OK)
            die_st("cft_program_run", st);
        if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
            die("the deposit buffer overflowed - the program is wrong");
        for (i = 0; i < n; i++) {
            const uint8_t *d = E->dep + i * DEPOSITS * esz;
            if (E->counts[i] != DEPOSITS)
                die("a lane deposited the wrong number of values");
            memcpy(E->n    + i * esz, d + 0 * esz, esz);
            memcpy(E->cnt  + i * esz, d + 1 * esz, esz);
            memcpy(E->peak + i * esz, d + 2 * esz, esz);
            memcpy(E->esc  + i * esz, d + 3 * esz, esz);
            if (pred_true(fi, E->esc + i * esz))
                newly_escaped++;
        }
    } else {
        /* live &= (n > 1): an element already at 1 takes no step */
        runN(CFT_CMPLT, fi, E->bc[K_ONE], E->n, NULL, E->nd, n, &f);
        runN(CFT_MIN, fi, E->live, E->nd, NULL, E->live, n, &f);
        /* q = n * 0.5 */
        runN(CFT_MUL, fi, E->n, E->bc[K_HALF], NULL, E->q, n, &f);
        /* parity from the encoding */
        runN(CFT_ISHR, fi, E->n, E->bc[K_IPM1], NULL, E->t, n, &f);
        runN(CFT_ISUB, fi, E->bc[K_ISH], E->t, NULL, E->t, n, &f);
        runN(CFT_ISHR, fi, E->n, E->t, NULL, E->t, n, &f);
        runN(CFT_IAND, fi, E->t, E->bc[K_I1], NULL, E->t, n, &f);
        runN(CFT_ICMPLT, fi, E->bc[K_ZERO], E->t, NULL, E->odd, n, &f);
        /* every representable value at or above 2^p is even */
        runN(CFT_CMPLT, fi, E->n, E->bc[K_2P], NULL, E->t, n, &f);
        runN(CFT_MIN, fi, E->odd, E->t, NULL, E->odd, n, &f);
        /* an element that is no longer live must not reach the FMA with
         * its own value, or it would raise flags for ever */
        runN(CFT_MIN, fi, E->odd, E->live, NULL, E->tmp, n, &f);
        runN(CFT_SELECT, fi, E->n, E->bc[K_ONE], E->tmp, E->nn, n, &f);
        runN(CFT_FMA, fi, E->nn, E->bc[K_THREE], E->bc[K_ONE], E->y, n, &f);
        runN(CFT_FMA, fi, E->nn, E->bc[K_MTHREE], E->y, E->ex, n, &f);
        runN(CFT_CMPEQ, fi, E->ex, E->bc[K_ONE], NULL, E->ex, n, &f);
        /* escaped := live && !exact */
        runN(CFT_SELECT, fi, E->bc[K_ZERO], E->bc[K_ONE], E->ex, E->tmp, n,
             &f);
        runN(CFT_SELECT, fi, E->tmp, E->esc, E->live, E->esc, n, &f);
        runN(CFT_MIN, fi, E->live, E->ex, NULL, E->live, n, &f);
        /* commit, for live elements whose step was exact */
        runN(CFT_SELECT, fi, E->y, E->q, E->odd, E->cand, n, &f);
        runN(CFT_SELECT, fi, E->cand, E->n, E->live, E->n, n, &f);
        runN(CFT_ADD, fi, E->cnt, NULL, E->bc[K_ONE], E->tmp, n, &f);
        runN(CFT_SELECT, fi, E->tmp, E->cnt, E->live, E->cnt, n, &f);
        runN(CFT_MAX, fi, E->peak, E->n, NULL, E->peak, n, &f);
        E->ops += 23 * (uint64_t)n;
        for (i = 0; i < n; i++)
            if (pred_true(fi, E->esc + i * esz))
                newly_escaped++;
    }

    E->calls++;
    E->flags_seen |= f;

    /* Nothing in this step can signal invalid or divide-by-zero, and
     * the values stay near 2^p rather than near the format's edge, so
     * an overflow or underflow would mean the tool is wrong and not
     * that the data is interesting. */
    if (f & (CFT_FLAG_INVALID | CFT_FLAG_DIVBYZERO | CFT_FLAG_OVERFLOW |
             CFT_FLAG_UNDERFLOW)) {
        fprintf(stderr,
                "cft-collatz: the library raised 0x%02x on a step that can "
                "only ever raise inexact - stopping\n", (unsigned)f);
        exit(3);
    }

    /* The assertion that makes the flag load-bearing: over this call
     * INEXACT is raised if and only if at least one live element's
     * exactness witness failed. */
    if (E->flags_trusted) {
        int flag = (f & CFT_FLAG_INEXACT) != 0;
        int wit  = newly_escaped != 0;
        if (flag != wit) {
            fprintf(stderr,
                    "cft-collatz: the INEXACT flag (%d) and the per-element "
                    "exactness witness (%d escapes) disagree - one of the "
                    "tool, the library, or the argument in docs/COLLATZ.md "
                    "is wrong\n", flag, (int)newly_escaped);
            exit(3);
        }
    }
    return newly_escaped;
}

/* ===================================================================
 * Records, statistics, and the hash chain
 * =================================================================== */
typedef struct {
    char     n0[DECMAX];
    uint64_t steps;
    char     peak[DECMAX];
    char     final[DECMAX];
    int      escaped;
    int      filled;
} record;

typedef struct {
    uint64_t resolved, verified, escaped;
    uint64_t steps_total;
    uint64_t max_steps;
    char     max_steps_n[DECMAX];
    uint8_t  max_peak[MAX_ESZ];
    char     max_peak_n[DECMAX];
    int      have_peak;
    char     first_escape_n[DECMAX];
    uint64_t first_escape_step;
    int      have_escape;
    uint8_t  chain[32];
} stats;

static void record_line(const record *r, char *out, size_t cap)
{
    int len = snprintf(out, cap, "%s %" PRIu64 " %s %s %s",
                       r->n0, r->steps, r->peak, r->final,
                       r->escaped ? "esc" : "ok");
    if (len <= 0 || (size_t)len >= cap)
        die("record line too long");
}

static void chain_absorb(stats *S, const record *r)
{
    sha256 h;
    char line[4 * DECMAX + 64];
    size_t len;
    record_line(r, line, sizeof line);
    len = strlen(line);
    line[len++] = '\n';
    sha256_start(&h);
    sha256_push(&h, S->chain, sizeof S->chain);
    sha256_push(&h, line, len);
    sha256_end(&h, S->chain);
}

/* ===================================================================
 * The run
 * =================================================================== */
typedef struct {
    cft_format fmt;
    int        deep;
    int        use_program;
    size_t     batch;
    uint32_t   reps;
    const char *ckpt;
    double     ckpt_interval;
    int        resume;
    long       stop_after_batches;
    long       stop_after_passes;
    double     time_limit;
    const char *artifact;
    const char *records_path;
    int        csv;
    int        quiet;
    const char *from_s, *to_s, *count_s, *values_s;
} options;

typedef struct {
    const fmt_info *fi;
    options        *opt;
    stats           st;
    uint8_t         cursor[MAX_ESZ];
    uint8_t         lo[MAX_ESZ], hi[MAX_ESZ];
    uint8_t         one[MAX_ESZ];
    uint8_t         wcap[MAX_ESZ];     /* the witness's proven domain */
    int             have_hi;
    record         *recs;
    size_t          nrec;
    engine          eng;
    size_t          live;
    FILE           *recf;
    long            passes;
} runstate;

static void stat_update(runstate *R, const record *r, const uint8_t *peakv)
{
    stats *S = &R->st;
    S->resolved++;
    S->steps_total += r->steps;
    if (r->escaped) {
        S->escaped++;
        if (!S->have_escape) {
            S->have_escape = 1;
            S->first_escape_step = r->steps;
            snprintf(S->first_escape_n, DECMAX, "%s", r->n0);
        }
    } else {
        S->verified++;
        if (r->steps > S->max_steps) {
            S->max_steps = r->steps;
            snprintf(S->max_steps_n, DECMAX, "%s", r->n0);
        }
    }
    /* Every peak is an exactly-computed value, escaped elements
     * included: the step that lost exactness is never committed, so a
     * peak is always the largest value the element PROVABLY held. */
    if (!S->have_peak || val_lt(R->fi, S->max_peak, peakv)) {
        S->have_peak = 1;
        memcpy(S->max_peak, peakv, R->fi->esz);
        snprintf(S->max_peak_n, DECMAX, "%s", r->n0);
    }
    chain_absorb(S, r);
    if (R->recf) {
        char line[4 * DECMAX + 64];
        record_line(r, line, sizeof line);
        fprintf(R->recf, "%s\n", line);
    }
}

/* Harvest slots that have stopped, compacting survivors to the front.
 * Compaction is safe by construction: an element's trajectory depends
 * on its own registers and nothing else, and a deposit's address
 * derives from the element index alone, so where a lane sits cannot
 * change what it computes (docs/SEQUENCER.md, P2 and P3). */
static void harvest(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, i, keep = 0;
    engine *E = &R->eng;

    for (i = 0; i < R->live; i++) {
        const uint8_t *nv = E->n + i * esz;
        int escaped = pred_true(fi, E->esc + i * esz);
        int done = memcmp(nv, R->one, esz) == 0;
        record *r;
        if (!escaped && !done) {
            if (keep != i) {
                memcpy(E->n     + keep * esz, E->n     + i * esz, esz);
                memcpy(E->cnt   + keep * esz, E->cnt   + i * esz, esz);
                memcpy(E->peak  + keep * esz, E->peak  + i * esz, esz);
                memcpy(E->esc   + keep * esz, E->esc   + i * esz, esz);
                memcpy(E->live  + keep * esz, E->live  + i * esz, esz);
                memcpy(E->start + keep * esz, E->start + i * esz, esz);
                E->rec[keep] = E->rec[i];
            }
            keep++;
            continue;
        }
        r = &R->recs[E->rec[i]];
        val_to_dec(fi, E->start + i * esz, r->n0, DECMAX);
        val_to_dec(fi, E->peak + i * esz, r->peak, DECMAX);
        val_to_dec(fi, nv, r->final, DECMAX);
        r->steps = val_to_u64(fi, E->cnt + i * esz);
        r->escaped = escaped;
        r->filled = 1;
    }
    R->live = keep;
}

/* The witness is exact while the residual is representable, which
 * every peak below 2^(2p-4) guarantees. Checked rather than assumed. */
static void check_witness_domain(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, i;
    for (i = 0; i < R->live; i++)
        if (!val_lt(fi, R->eng.peak + i * esz, R->wcap))
            die("a trajectory left the exactness witness's proven domain");
}

static void flush_records(runstate *R, int print)
{
    size_t i;
    for (i = 0; i < R->nrec; i++) {
        record *r = &R->recs[i];
        uint8_t peakv[MAX_ESZ];
        if (!r->filled)
            die("a record was never filled");
        if (!val_from_dec(R->fi, r->peak, peakv))
            die("a peak could not be read back exactly");
        if (print)
            printf("  %-24s %6" PRIu64 " steps  peak %s%s\n",
                   r->n0, r->steps, r->peak,
                   r->escaped ? "   LEFT EXACT ARITHMETIC" : "");
        stat_update(R, r, peakv);
    }
    R->nrec = 0;
}

/* ===================================================================
 * Checkpoint
 *
 * A line-oriented ASCII file, written to <path>.tmp and then renamed
 * over the target, so a reader never sees a half-written one. Every
 * number that describes a RESULT is here; nothing that describes the
 * machine is, which is what lets two runs with different batch sizes
 * end on byte-identical files.
 * =================================================================== */
#define CKPT_MAGIC "cft-collatz-checkpoint 1"

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
    char tmp[1024], buf[DECMAX], chain[65];
    FILE *f;
    size_t i;
    engine *E = &R->eng;

    if (!O->ckpt)
        return;
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt) >= sizeof tmp)
        die("checkpoint path too long");
    f = fopen(tmp, "wb");
    if (!f)
        die("cannot write the checkpoint");

    hex32(R->st.chain, chain);
    fprintf(f, "%s\n", CKPT_MAGIC);
    fprintf(f, "format %s\n", cft_format_name(fi->fmt));
    fprintf(f, "mode %s\n", O->deep ? "deep" : "sweep");
    val_to_dec(fi, R->lo, buf, sizeof buf);
    fprintf(f, "lo %s\n", buf);
    if (R->have_hi) {
        val_to_dec(fi, R->hi, buf, sizeof buf);
        fprintf(f, "hi %s\n", buf);
    } else {
        fprintf(f, "hi -\n");
    }
    val_to_dec(fi, R->cursor, buf, sizeof buf);
    fprintf(f, "cursor %s\n", buf);
    fprintf(f, "resolved %" PRIu64 "\n", R->st.resolved);
    fprintf(f, "verified %" PRIu64 "\n", R->st.verified);
    fprintf(f, "escaped %" PRIu64 "\n", R->st.escaped);
    fprintf(f, "steps %" PRIu64 "\n", R->st.steps_total);
    fprintf(f, "maxsteps %" PRIu64 " %s\n", R->st.max_steps,
            R->st.max_steps ? R->st.max_steps_n : "-");
    if (R->st.have_peak) {
        val_to_dec(fi, R->st.max_peak, buf, sizeof buf);
        fprintf(f, "maxpeak %s %s\n", buf, R->st.max_peak_n);
    } else {
        fprintf(f, "maxpeak - -\n");
    }
    if (R->st.have_escape)
        fprintf(f, "firstescape %s %" PRIu64 "\n", R->st.first_escape_n,
                R->st.first_escape_step);
    else
        fprintf(f, "firstescape - -\n");
    fprintf(f, "chain %s\n", chain);

    fprintf(f, "batchrecords %" PRIu64 "\n", (uint64_t)R->nrec);
    for (i = 0; i < R->nrec; i++) {
        record *r = &R->recs[i];
        if (r->filled) {
            char line[4 * DECMAX + 64];
            record_line(r, line, sizeof line);
            fprintf(f, "done %s\n", line);
        } else {
            fprintf(f, "pending\n");
        }
    }
    fprintf(f, "inflight %" PRIu64 "\n", (uint64_t)R->live);
    for (i = 0; i < R->live; i++) {
        char a[DECMAX], b[DECMAX], c[DECMAX], d[DECMAX];
        val_to_dec(fi, E->start + i * fi->esz, a, sizeof a);
        val_to_dec(fi, E->n + i * fi->esz, b, sizeof b);
        val_to_dec(fi, E->cnt + i * fi->esz, c, sizeof c);
        val_to_dec(fi, E->peak + i * fi->esz, d, sizeof d);
        fprintf(f, "run %s %s %s %s %" PRIu64 "\n", a, b, c, d,
                (uint64_t)E->rec[i]);
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
    char line[8 * DECMAX];
    size_t i;
    engine *E = &R->eng;

    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, sizeof line, f) ||
        strcmp(trim_nl(line), CKPT_MAGIC) != 0)
        die("that file is not a cft-collatz checkpoint of this version");

    while (fgets(line, sizeof line, f)) {
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
        } else if (!strcmp(key, "mode")) {
            if (strcmp(rest, O->deep ? "deep" : "sweep") != 0)
                die("the checkpoint was written for a different mode");
        } else if (!strcmp(key, "lo")) {
            if (!val_from_dec(fi, rest, R->lo))
                die("bad checkpoint lo");
        } else if (!strcmp(key, "hi")) {
            if (!strcmp(rest, "-")) {
                R->have_hi = 0;
            } else {
                if (!val_from_dec(fi, rest, R->hi))
                    die("bad checkpoint hi");
                R->have_hi = 1;
            }
        } else if (!strcmp(key, "cursor")) {
            if (!val_from_dec(fi, rest, R->cursor))
                die("bad checkpoint cursor");
        } else if (!strcmp(key, "resolved")) {
            R->st.resolved = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "verified")) {
            R->st.verified = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "escaped")) {
            R->st.escaped = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "steps")) {
            R->st.steps_total = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "maxsteps")) {
            char who[DECMAX];
            if (sscanf(rest, "%" SCNu64 " %511s", &R->st.max_steps, who) == 2)
                snprintf(R->st.max_steps_n, DECMAX, "%s", who);
        } else if (!strcmp(key, "maxpeak")) {
            char pv[DECMAX], who[DECMAX];
            if (sscanf(rest, "%511s %511s", pv, who) == 2 &&
                strcmp(pv, "-") != 0) {
                if (!val_from_dec(fi, pv, R->st.max_peak))
                    die("bad checkpoint maxpeak");
                snprintf(R->st.max_peak_n, DECMAX, "%s", who);
                R->st.have_peak = 1;
            }
        } else if (!strcmp(key, "firstescape")) {
            char who[DECMAX];
            uint64_t at = 0;
            if (sscanf(rest, "%511s %" SCNu64, who, &at) == 2 &&
                strcmp(who, "-") != 0) {
                snprintf(R->st.first_escape_n, DECMAX, "%s", who);
                R->st.first_escape_step = at;
                R->st.have_escape = 1;
            }
        } else if (!strcmp(key, "chain")) {
            if (!unhex32(rest, R->st.chain))
                die("bad checkpoint chain");
        } else if (!strcmp(key, "batchrecords")) {
            size_t nb = (size_t)strtoull(rest, NULL, 10);
            if (nb > O->batch)
                die("the checkpoint's batch is larger than --batch");
            R->nrec = nb;
            for (i = 0; i < nb; i++) {
                char tag[16];
                record *r = &R->recs[i];
                memset(r, 0, sizeof *r);
                if (!fgets(line, sizeof line, f))
                    die("the checkpoint ended inside its batch");
                trim_nl(line);
                if (sscanf(line, "%15s", tag) != 1)
                    die("bad checkpoint batch line");
                if (!strcmp(tag, "pending")) {
                    r->filled = 0;
                } else if (!strcmp(tag, "done")) {
                    char what[16];
                    if (sscanf(line, "done %511s %" SCNu64 " %511s %511s %15s",
                               r->n0, &r->steps, r->peak, r->final,
                               what) != 5)
                        die("bad checkpoint record");
                    r->escaped = strcmp(what, "esc") == 0;
                    r->filled = 1;
                } else {
                    die("bad checkpoint batch line");
                }
            }
        } else if (!strcmp(key, "inflight")) {
            size_t nfl = (size_t)strtoull(rest, NULL, 10);
            if (nfl > O->batch)
                die("the checkpoint has more in flight than --batch");
            for (i = 0; i < nfl; i++) {
                char a[DECMAX], b[DECMAX], c[DECMAX], d[DECMAX];
                uint64_t slot = 0;
                if (!fgets(line, sizeof line, f))
                    die("the checkpoint ended inside its in-flight list");
                trim_nl(line);
                if (sscanf(line, "run %511s %511s %511s %511s %" SCNu64,
                           a, b, c, d, &slot) != 5)
                    die("bad checkpoint in-flight line");
                if (!val_from_dec(fi, a, E->start + i * fi->esz) ||
                    !val_from_dec(fi, b, E->n + i * fi->esz) ||
                    !val_from_dec(fi, c, E->cnt + i * fi->esz) ||
                    !val_from_dec(fi, d, E->peak + i * fi->esz))
                    die("bad checkpoint in-flight value");
                memset(E->esc + i * fi->esz, 0, fi->esz);
                memcpy(E->live + i * fi->esz, R->one, fi->esz);
                E->rec[i] = (size_t)slot;
            }
            R->live = nfl;
        } else if (!strcmp(key, "end")) {
            break;
        }
    }
    fclose(f);
}

/* ===================================================================
 * Filling a batch
 * =================================================================== */
static size_t fill_batch(runstate *R)
{
    const fmt_info *fi = R->fi;
    engine *E = &R->eng;
    size_t esz = fi->esz, want, i;

    want = R->opt->batch - R->nrec;   /* every slot filled makes a record */
    for (i = 0; i < want; i++) {
        size_t slot = R->live;
        uint32_t fl = 0;
        if (R->have_hi && !val_lt(fi, R->cursor, R->hi))
            break;
        memcpy(E->start + slot * esz, R->cursor, esz);
        memcpy(E->n + slot * esz, R->cursor, esz);
        memcpy(E->peak + slot * esz, R->cursor, esz);
        memset(E->cnt + slot * esz, 0, esz);
        memset(E->esc + slot * esz, 0, esz);
        memcpy(E->live + slot * esz, R->one, esz);
        E->rec[slot] = R->nrec;
        memset(&R->recs[R->nrec], 0, sizeof R->recs[R->nrec]);
        R->nrec++;
        R->live++;
        /* cursor += 1, in the format's own arithmetic, so an increment
         * the format cannot represent exactly is refused rather than
         * silently repeated */
        run1(CFT_ADD, fi->fmt, R->cursor, NULL, R->one, R->cursor, &fl);
        if (fl & CFT_FLAG_INEXACT)
            die("the sweep reached the largest integer this format holds "
                "exactly");
    }
    return R->live;
}

/* ===================================================================
 * Reporting
 * =================================================================== */
static void report(runstate *R, double elapsed, const char *backend)
{
    stats *S = &R->st;
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    char chain[65], cur[DECMAX], peak[DECMAX];
    double sps = elapsed > 0 ? (double)S->steps_total / elapsed : 0.0;
    double eps = elapsed > 0 ? (double)S->resolved / elapsed : 0.0;

    hex32(S->chain, chain);
    val_to_dec(fi, R->cursor, cur, sizeof cur);
    if (S->have_peak)
        val_to_dec(fi, S->max_peak, peak, sizeof peak);
    else
        snprintf(peak, sizeof peak, "-");

    if (O->csv) {
        printf("backend,format,engine,batch,steps_per_call,cursor,resolved,"
               "verified,escaped,steps,max_steps,max_steps_n,max_peak,"
               "max_peak_n,seconds,steps_per_s,elements_per_s,chain\n");
        printf("%s,%s,%s,%" PRIu64 ",%" PRIu64 ",%s,%" PRIu64 ",%" PRIu64
               ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%s,%s,%s,%.6f,%.1f,"
               "%.1f,%s\n",
               backend, cft_format_name(fi->fmt),
               O->use_program ? "program" : "loop",
               (uint64_t)O->batch, (uint64_t)O->reps, cur,
               S->resolved, S->verified, S->escaped, S->steps_total,
               S->max_steps, S->max_steps ? S->max_steps_n : "-",
               peak, S->have_peak ? S->max_peak_n : "-",
               elapsed, sps, eps, chain);
        return;
    }

    printf("\n");
    printf("  backend       %s\n", backend);
    printf("  format        %s, p = %d, every integer to 2^%d exact\n",
           cft_format_name(fi->fmt), fi->prec, fi->prec);
    printf("  engine        %s, batch %" PRIu64 ", %" PRIu64
           " steps per call\n",
           O->use_program ? "sequencer program" : "host cft_run loop",
           (uint64_t)O->batch, (uint64_t)O->reps);
    printf("  cursor        %s\n", cur);
    printf("  resolved      %" PRIu64 " starting values\n", S->resolved);
    printf("  verified      %" PRIu64 " (every operation exact)\n",
           S->verified);
    printf("  left exact    %" PRIu64 "\n", S->escaped);
    if (S->have_escape)
        printf("                first at n = %s, after %" PRIu64
               " exact steps\n", S->first_escape_n, S->first_escape_step);
    printf("  longest       %" PRIu64 " steps, at n = %s\n", S->max_steps,
           S->max_steps ? S->max_steps_n : "-");
    printf("  largest peak  %s\n", peak);
    if (S->have_peak)
        printf("                at n = %s\n", S->max_peak_n);
    printf("  steps         %" PRIu64 "\n", S->steps_total);
    printf("  library calls %" PRIu64 "\n", R->eng.calls);
    if (O->use_program)
        printf("  program       %u instructions, %d constants, "
               "%d deposits per element\n",
               R->eng.n_insns, (int)N_CONST, DEPOSITS);
    else
        printf("  opcode issues %" PRIu64 " elementwise passes over one "
               "element each\n", R->eng.ops);
    printf("  flags seen    0x%02x%s\n", (unsigned)R->eng.flags_seen,
           R->eng.flags_trusted ? "" : "  (this backend cannot read flags)");
    /* The device's 754 status word (7.1), lowered once after the
     * constants were built and never touched since. It should hold
     * exactly what the steps raised, because nothing else in this tool
     * rounds anything - so printing both is a free cross-check on the
     * claim that the step is the only source of flags. */
    printf("  status word   0x%02x%s\n", (unsigned)cft_save_all_flags(DEV),
           cft_save_all_flags(DEV) == R->eng.flags_seen
               ? " (agrees with the union above)"
               : "  DISAGREES WITH THE UNION ABOVE");
    printf("  time          %.3f s\n", elapsed);
    printf("  throughput    %.0f Collatz steps/s, %.1f elements/s\n",
           sps, eps);
    printf("  chain         %s\n", chain);
    printf("\n");
}

/* ===================================================================
 * Deep mode: an explicit set of starting values
 * =================================================================== */
static void deep_load(runstate *R, char *list)
{
    const fmt_info *fi = R->fi;
    engine *E = &R->eng;
    size_t esz = fi->esz;
    char *save = list;

    while (save && *save) {
        char *comma = strchr(save, ',');
        char *tok = save;
        size_t slot;
        if (comma) { *comma = 0; save = comma + 1; }
        else save = NULL;
        while (*tok == ' ')
            tok++;
        if (!*tok)
            continue;
        if (R->nrec >= R->opt->batch)
            die("--values holds more entries than --batch");
        slot = R->live;
        if (!val_from_dec(fi, tok, E->start + slot * esz))
            die("a --values entry is not an integer this format holds "
                "exactly");
        if (val_lt(fi, E->start + slot * esz, R->one))
            die("--values entries must be at least 1");
        memcpy(E->n + slot * esz, E->start + slot * esz, esz);
        memcpy(E->peak + slot * esz, E->start + slot * esz, esz);
        memset(E->cnt + slot * esz, 0, esz);
        memset(E->esc + slot * esz, 0, esz);
        memcpy(E->live + slot * esz, R->one, esz);
        E->rec[slot] = R->nrec;
        memset(&R->recs[R->nrec], 0, sizeof R->recs[R->nrec]);
        R->nrec++;
        R->live++;
    }
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-collatz - Collatz trajectories computed exactly, on libcft\n"
"\n"
"  --mode sweep|deep        consecutive starting values, or a named set\n"
"  --from N                 first starting value (default 1)\n"
"  --to N                   one past the last (exclusive)\n"
"  --count N                equivalent to --to (from + N)\n"
"  --values a,b,c           deep mode: the starting values to follow\n"
"  --format fp32|fp64|fp128|fp256   default fp256\n"
"  --engine program|loop    sequencer program (default) or host loop\n"
"  --batch N                elements in flight (default 4096)\n"
"  --steps-per-call N       program loop trip count (default 1024)\n"
"  --checkpoint PATH        write a resumable checkpoint\n"
"  --checkpoint-interval S  seconds between checkpoints (default 10)\n"
"  --resume                 continue from --checkpoint\n"
"  --stop-after-batches N   stop cleanly once N batches are complete\n"
"  --stop-after-passes N    stop cleanly after N engine passes, mid-batch\n"
"  --time S                 stop cleanly after S seconds\n"
"  --records PATH           one line per starting value THIS run resolved\n"
"                           (truncated at start; it is not resume-aware,\n"
"                           because the checkpoint's chain is)\n"
"  --artifact PATH          an .xclbin; omit for the software backend\n"
"  --csv                    machine-readable summary\n"
"  --quiet                  summary only\n"
"\n"
"Every value it reports is exact, or it is not reported as verified;\n"
"docs/COLLATZ.md is the argument.\n");
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
    fmt_info fi;
    runstate R;
    cft_caps caps;
    cft_status st;
    double t0, tckpt, elapsed;
    long batches = 0;
    int i, stopping = 0;
    char *values_copy = NULL;

    memset(&O, 0, sizeof O);
    O.fmt = CFT_FP256;
    O.use_program = 1;
    O.batch = 4096;
    O.reps = 1024;
    O.ckpt_interval = 10.0;
    O.stop_after_batches = -1;
    O.stop_after_passes = -1;
    O.from_s = "1";

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "--mode")) {
            const char *v = need(argc, argv, &i);
            if (!strcmp(v, "deep")) O.deep = 1;
            else if (!strcmp(v, "sweep")) O.deep = 0;
            else die("--mode takes sweep or deep");
        }
        else if (!strcmp(a, "--from"))   O.from_s = need(argc, argv, &i);
        else if (!strcmp(a, "--to"))     O.to_s = need(argc, argv, &i);
        else if (!strcmp(a, "--count"))  O.count_s = need(argc, argv, &i);
        else if (!strcmp(a, "--values")) O.values_s = need(argc, argv, &i);
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
        } else if (!strcmp(a, "--batch")) {
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
            if (!O.batch) die("--batch must be positive");
        } else if (!strcmp(a, "--steps-per-call")) {
            O.reps = (uint32_t)strtoul(need(argc, argv, &i), NULL, 10);
            if (!O.reps) die("--steps-per-call must be positive");
        }
        else if (!strcmp(a, "--checkpoint")) O.ckpt = need(argc, argv, &i);
        else if (!strcmp(a, "--checkpoint-interval"))
            O.ckpt_interval = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--resume")) O.resume = 1;
        else if (!strcmp(a, "--stop-after-batches"))
            O.stop_after_batches = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--stop-after-passes"))
            O.stop_after_passes = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--time"))
            O.time_limit = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--records"))
            O.records_path = need(argc, argv, &i);
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--csv")) O.csv = 1;
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-collatz: unknown option %s\n", a);
            return 2;
        }
    }

    st = cft_open(O.artifact, 0, &DEV);
    if (st != CFT_OK)
        die_st("cft_open", st);

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(DEV, &caps) != CFT_OK)
        die("cft_get_caps failed");
    if (!(caps.format_mask & (1u << (unsigned)O.fmt)))
        die("this backend does not carry that format");

    measure_format(&fi, O.fmt);

    memset(&R, 0, sizeof R);
    R.fi = &fi;
    R.opt = &O;
    R.recs = (record *)xcalloc(O.batch, sizeof(record));
    val_from_i64(&fi, 1, R.one);
    val_pow2(&fi, 2 * fi.prec - 4, R.wcap);
    engine_init(&R.eng, &fi, O.batch, O.use_program, O.reps,
                caps.flags_readable != 0);
    /* Measuring p deliberately raises inexact, and 7.1 says a status
     * flag is lowered only at the user's request. This is that
     * request: from here the device's word holds what the RUN raised
     * and nothing else, which the report cross-checks. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);

    if (O.records_path) {
        R.recf = fopen(O.records_path, "wb");
        if (!R.recf)
            die("cannot write the records file");
    }
    if (O.deep && O.ckpt)
        die("--mode deep does not checkpoint; use --mode sweep");

    if (!val_from_dec(&fi, O.from_s, R.lo))
        die("--from is not an integer this format holds exactly");
    memcpy(R.cursor, R.lo, fi.esz);
    if (O.to_s) {
        if (!val_from_dec(&fi, O.to_s, R.hi))
            die("--to is not an integer this format holds exactly");
        R.have_hi = 1;
    } else if (O.count_s) {
        uint8_t cnt[MAX_ESZ];
        uint32_t fl = 0;
        if (!val_from_dec(&fi, O.count_s, cnt))
            die("--count is not an integer this format holds exactly");
        run1(CFT_ADD, fi.fmt, R.lo, NULL, cnt, R.hi, &fl);
        if (fl & CFT_FLAG_INEXACT)
            die("--from plus --count is not exact in this format");
        R.have_hi = 1;
    }
    if (val_lt(&fi, R.lo, R.one))
        die("--from must be at least 1");

    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R);
    }

    if (O.deep) {
        if (O.values_s) {
            values_copy = (char *)xcalloc(strlen(O.values_s) + 1, 1);
            memcpy(values_copy, O.values_s, strlen(O.values_s));
            deep_load(&R, values_copy);
        } else if (!O.to_s && !O.count_s) {
            die("--mode deep needs --values, or --from with --count or --to");
        }
    }

    if (!O.quiet && !O.csv) {
        printf("cft-collatz: %s backend, %s, p = %d, %s engine\n",
               caps.backend, cft_format_name(fi.fmt), fi.prec,
               O.use_program ? "sequencer-program" : "host-loop");
        if (!caps.flags_readable)
            printf("  NOTE: this backend cannot read the exception flags, so "
                   "the flag/witness agreement is not checked\n");
    }

    t0 = now_s();
    tckpt = t0;
    while (!stopping) {
        if (!(O.deep && O.values_s))
            fill_batch(&R);
        /* Nothing in flight AND nothing waiting to be hashed: a
         * checkpoint taken exactly when a batch drained leaves the
         * second of those, and it still has to be flushed. */
        if (!R.live && !R.nrec)
            break;

        while (R.live) {
            engine_pass(&R.eng, R.live);
            R.passes++;
            check_witness_domain(&R);
            harvest(&R);
            if (O.ckpt && now_s() - tckpt >= O.ckpt_interval) {
                ckpt_write(&R);
                tckpt = now_s();
            }
            if (O.stop_after_passes >= 0 && R.passes >= O.stop_after_passes) {
                stopping = 1;
                break;
            }
        }
        if (stopping)
            break;
        flush_records(&R, O.deep && !O.csv && !O.quiet);
        batches++;
        if (O.ckpt)
            ckpt_write(&R);
        if (O.deep)
            break;
        if (O.stop_after_batches >= 0 && batches >= O.stop_after_batches)
            break;
        if (O.time_limit > 0 && now_s() - t0 >= O.time_limit)
            break;
        if (R.have_hi && !val_lt(&fi, R.cursor, R.hi))
            break;
    }
    elapsed = now_s() - t0;
    if (O.ckpt)
        ckpt_write(&R);
    if (R.recf)
        fclose(R.recf);

    report(&R, elapsed, caps.backend);

    free(values_copy);
    free(R.recs);
    engine_free(&R.eng);
    cft_close(DEV);
    return 0;
}
