/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-mersenne - the Lucas-Lehmer test over the known Mersenne primes,
 * with fp256 used as an EXACT wide-integer multiplier rather than as a
 * fast approximate one.
 *
 *   ./cft-mersenne --set small
 *   ./cft-mersenne --exponents 1279,1277 --format fp64 --engine loop
 *   ./cft-mersenne --set known --checkpoint run.ckpt --checkpoint-interval 60
 *   ./cft-mersenne --selftest
 *
 * ---------------------------------------------------------------
 * Why this workload, on this contract
 * ---------------------------------------------------------------
 *
 * Lucas-Lehmer: s_0 = 4, s_{k+1} = s_k^2 - 2 mod (2^P - 1), and 2^P - 1
 * is prime exactly when s_{P-2} = 0. The whole cost is the squaring, and
 * a squaring of a P-bit number is a convolution of limbs.
 *
 * Every published fast implementation of that convolution is a
 * floating-point FFT, which is not exact: the answer is rounded and
 * then rounded back to integers, and the implementation has to PROVE
 * separately that the rounding was small enough - GIMPS does it with
 * Gerbicz error checking and an independent double-check of every
 * result. This tool does the opposite. It keeps the convolution inside
 * the format's exact range and lets the library's own `inexact` flag be
 * the proof:
 *
 *   - binary256 has p = 237, so every integer in [0, 2^p] is exact.
 *   - a product of two b-bit limbs is under 2^(2b), so it is exact for
 *     every b <= p/2 - no rounding, no flag.
 *   - `cft_reduce(CFT_DOT)` is sum over i of round(a[i]*b[i]) over a
 *     tree whose SHAPE IS PART OF THE CONTRACT (docs/DETERMINISM.md).
 *     Every partial sum of L such products is at most L * 2^(2b); while
 *     that is at most 2^p every node is an exactly representable
 *     integer, so no node rounds and the reduction raises nothing.
 *   - therefore `flags == 0` over a convolution is not a hope. It is a
 *     certificate that the coefficient is the exact integer sum, issued
 *     by the library rather than argued by the host.
 *
 * The limb width is DERIVED from that bound in geometry_derive() below,
 * never typed in. Nothing else in this file decides how wide a limb is.
 *
 * ---------------------------------------------------------------
 * The representation, and why the modulus is free
 * ---------------------------------------------------------------
 *
 * A residue is L limbs of b bits, limb k weighing 2^(k*b), holding a
 * value under 2^(L*b) - which is WIDER than 2^P, by d = L*b - P bits.
 * That slack is the whole trick for the modulus. Since
 *
 *     2^P == 1   (mod 2^P - 1)      =>   2^(L*b) == 2^d
 *
 * folding the high half of a product onto the low half is a multiply by
 * 2^d, which is a power of two and therefore EXACT at every format. No
 * division, no bit-shifting across limb boundaries, and the fold is one
 * `CFT_MUL` and one `CFT_ADD`.
 *
 * Subtracting the 2 of the recurrence is an addition, for the same
 * reason: -2 == 2^P - 3 (mod 2^P - 1), and 2^P - 3 is a fixed vector of
 * limbs. Adding it instead of subtracting keeps every limb of every
 * intermediate NON-NEGATIVE, which is what lets the carry split below
 * work on encodings rather than on signed values.
 *
 * ---------------------------------------------------------------
 * Carry propagation without a rounding operation
 * ---------------------------------------------------------------
 *
 * A convolution coefficient is far wider than a limb, so it must be
 * split: v = hi * B + lo with 0 <= lo < B, B = 2^b. The obvious ways to
 * take the integer part are both wrong here, for the reasons
 * docs/COLLATZ.md gives for the same choice:
 *
 *   - the magic constant (x + 2^(p-1)) - 2^(p-1) RAISES INEXACT on
 *     every non-integer, which would flood the very flag this tool
 *     uses as its certificate, in the same call as the accumulation;
 *   - `cft_rint` never signals and is correct, but it is a COMPOSED
 *     host-side operation and so is not in the sequencer's opcode set.
 *
 * So the split reads the encoding, exactly as collatz.c reads parity
 * from it. For a positive t = 2^E * (1 + f) with 0 <= E <= p-1, the
 * bits of the significand below 2^0 are the low ((p-1) - E) of the
 * encoding, so
 *
 *     trunc(t) = (bits(t) >> s) << s,   s = (p-1) + bias - biased_exp(t)
 *
 * and s comes from t's own encoding by ISHR and ISUB. Four quiet
 * integer opcodes, no rounding, no flag, all of them in the sequencer's
 * set. t < 1 has no integer part and is the one edge the shift cannot
 * express - s would exceed p-1 and the shift is modulo the format width
 * - so a CMPLT against 1 and a SELECT say so explicitly.
 *
 * THE INTEGER OPCODES ARE QUIET, WHICH MEANS NO FLAG CAN EVER SAY THE
 * SPLIT WAS WRONG. That is what the per-element witness is for: the
 * same step computes, in the library's own arithmetic,
 *
 *     recon = fma(hi, B, lo)
 *     ok    =  recon == v  and  0 <= lo  and  lo < B
 *
 * which is exact (recon's true value is v, which is representable) and
 * which the host checks for EVERY element of EVERY pass. A wrong shift
 * cannot survive it. The negative control in docs/MERSENNE.md is that
 * witness removed.
 *
 * ---------------------------------------------------------------
 * Which flags are expected, and which are certificates
 * ---------------------------------------------------------------
 *
 * EXPECTED, exactly twice, and both outside the computation:
 *   - measuring p asks the library for the smallest k with 2^k + 1
 *     inexact, which raises inexact on purpose. The status word is
 *     lowered once after setup (754-2019 7.1's "at the user's
 *     request"), and never again.
 *   - `--selftest` builds an accumulation that crosses 2^p on purpose
 *     and requires inexact to be raised.
 *
 * CERTIFICATES, everywhere else: every call this tool issues during a
 * Lucas-Lehmer step must raise NOTHING AT ALL. A dot that raises
 * inexact means the accumulation left the exact range; a multiply,
 * add or fused multiply-add that raises anything means the derivation
 * above is wrong. Either way the residue is refused rather than
 * reported. Because the two expected sites are in setup and in a
 * separate mode, no expected flag can mask a certificate, and the
 * report prints the device status word beside the union of the calls'
 * flags as a second, free check on that.
 *
 * ---------------------------------------------------------------
 * Where the step runs
 * ---------------------------------------------------------------
 *
 * A convolution is a CROSS-ELEMENT reduction and the carry chain reads
 * a neighbour, so neither can be an orbit-sequencer program: a lane has
 * its own registers, three input streams and no path to another lane
 * (docs/SEQUENCER.md). The convolution is therefore `cft_reduce`, whose
 * tree the contract fixes, and the carry's shifted add is `cft_run`
 * with an offset pointer.
 *
 * What IS elementwise is the carry split, and that is what
 * `--engine program` runs: nineteen instructions, four constants, three
 * deposits, one program call per pass instead of fifteen `cft_run`
 * passes. `--engine loop` issues the identical fifteen opcodes from the
 * host, and the two must agree bit for bit. The base B is carried in
 * the program's b and c streams rather than in its constant bank, so
 * ONE program serves the three bases this tool splits at.
 *
 * No constant below is transcribed. p is measured from the library; the
 * bias follows from p and the format width; the limb width, the limb
 * count and the fold's shift are derived from p and the exponent; and
 * SHA-256's round constants are computed from the cube roots of the
 * primes, exactly as collatz.c computes them.
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

#define MAX_ESZ    32     /* bytes in the widest element, binary256 */
#define DECMAX    160     /* a limb's decimal form; b <= 118 bits */
#define MAX_EXPS   64     /* exponents in one run */
#define PARK_MAX 8192     /* residue limbs a checkpoint may carry */

static void die(const char *what)
{
    fprintf(stderr, "cft-mersenne: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-mersenne: %s: %s%s%s\n", what, cft_strerror(st),
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
 * are SPECIFIED as the fractional parts of the square and cube roots of
 * the first primes, so that is how they are computed here. This block
 * is collatz.c's, unchanged, and host/tests/mersenne_check.py proves
 * the derivation the same way: by recomputing the chain with hashlib.
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
        uint32_t dv;
        int prime = 1;
        for (dv = 2; dv * dv <= cand; dv++)
            if (cand % dv == 0) { prime = 0; break; }
        if (prime)
            out[have++] = cand;
    }
}

static uint32_t root_frac32(uint32_t pr, int root)
{
    u128 target = u128_shl(u128_mk(0, pr), 32 * root);
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
    int        prec;       /* p, significand bits, hidden one included */
    int        exp_w;
    uint64_t   bias;
} fmt_info;

static cft_device *DEV;
static uint32_t    FLAGS_SEEN;      /* union over every step call */
static int         FLAGS_TRUSTED;
static uint64_t    N_CALLS;         /* library calls issued by the run */
static uint64_t    N_ELEM_OPS;      /* elementwise opcode issues */
static uint64_t    N_LIMB_PROD;     /* limb products the dots performed */

static const char *flag_names(uint32_t f)
{
    static char buf[96];
    buf[0] = 0;
    if (f & CFT_FLAG_INVALID)   strcat(buf, "invalid ");
    if (f & CFT_FLAG_DIVBYZERO) strcat(buf, "divideByZero ");
    if (f & CFT_FLAG_OVERFLOW)  strcat(buf, "overflow ");
    if (f & CFT_FLAG_UNDERFLOW) strcat(buf, "underflow ");
    if (f & CFT_FLAG_INEXACT)   strcat(buf, "inexact ");
    if (!buf[0])
        strcat(buf, "nothing ");
    buf[strlen(buf) - 1] = 0;
    return buf;
}

/* Every call this tool issues during a step goes through one of these
 * three, and every one of them reads the flag word. Nothing may raise
 * anything: `what` names the phase, and says what a flag there would
 * mean, so a certificate failure is self-explanatory. */
static void expect_clean(uint32_t f, const char *what)
{
    FLAGS_SEEN |= f;
    if (!FLAGS_TRUSTED || !f)
        return;
    fprintf(stderr,
            "cft-mersenne: %s raised 0x%02x (%s), and every operation of a "
            "Lucas-Lehmer step here is exact by construction - the residue "
            "is REFUSED, not reported\n",
            what, (unsigned)f, flag_names(f));
    exit(3);
}

static void run1(cft_op op, cft_format fmt, const void *a, const void *b,
                 const void *c, void *d, uint32_t *fl)
{
    cft_status st = cft_run(DEV, op, fmt, CFT_RNE, a, b, c, d, 1, fl, NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
}

static void measure_format(fmt_info *fi, cft_format fmt)
{
    uint8_t one[MAX_ESZ], pw[MAX_ESZ], sum[MAX_ESZ];
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
     * the library answers that question itself, in the flag it raises.
     * This is the one place in setup where inexact is EXPECTED; the
     * status word is lowered once when setup is done. */
    fi->prec = 0;
    for (k = 1; k < fi->width; k++) {
        uint32_t fl = 0;
        st = cft_scaleb(DEV, fmt, CFT_RNE, one, k, pw, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_scaleb", st);
        run1(CFT_ADD, fmt, pw, NULL, one, sum, &fl);
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
 * back into a plain integer here. Lifted from collatz.c, which needed
 * the same thing for the same reason. */
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
 * cannot hold exactly, because an inexact limb is not a limb. */
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

static uint64_t val_to_u64(const fmt_info *fi, const void *v)
{
    uint64_t out = 0;
    uint32_t fl = 0;
    cft_status st = cft_cvt_to_u64(DEV, fi->fmt, CFT_RTZ, 1, v, &out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_to_u64", st);
    if (fl)
        die("a value that must fit 64 bits exactly did not");
    return out;
}

/* ===================================================================
 * Limb geometry, derived from the format's own parameters
 *
 * b is the limb width, L the limb count, d = L*b - P the fold's shift.
 * Three bounds decide them, and every one is a fact about p:
 *
 *   B1  a product of two limbs must be exact:      2b <= p
 *   B2  a coefficient is at most L such products,
 *       and every node of the contractual tree is
 *       at most the total:                         L * 2^(2b) <= 2^p
 *   B3  after ONE carry pass a coefficient is under 2^b + 2^(p-b), and
 *       the fold scales the high half by 2^d and adds it, so
 *       (2^b + 2^(p-b)) * (1 + 2^d) <= 2^p, for which d + 2 <= b
 *       suffices (2b <= p makes 2^b <= 2^(p-b)).
 *
 * Among the (b, L) pairs that satisfy them, work is L^2 limb products
 * per squaring, so the fewest limbs wins; and among the b that reach
 * that L, the smallest is taken, because d = L*b - P shrinks with b and
 * a smaller fold costs fewer carry passes.
 * =================================================================== */
typedef struct {
    int exp;      /* P */
    int b;
    int L;
    int d;
} geom;

/* L * 2^(2b) <= 2^p, in integers - so L <= 2^(p - 2b). The shift is on
 * a uint64_t and capped, because `long` is 32 bits on this platform and
 * p - 2b routinely exceeds that. */
static int bound_dot_ok(int p, int b, long L)
{
    int room;
    if (b < 2 || 2 * b > p)
        return 0;
    room = p - 2 * b;
    if (room >= 40)
        return 1;                       /* 2^40 limbs is beyond any run */
    return (uint64_t)L <= ((uint64_t)1 << room);
}

static int geom_ok(int p, int P, int b, int L, int d)
{
    if (b < 2 || L < 2 || d < 0 || d >= b)
        return 0;
    if ((long)L * b - P != d)
        return 0;
    if (!bound_dot_ok(p, b, L))
        return 0;
    if (d + 2 > b)                      /* B3 */
        return 0;
    return 1;
}

/* The fewest limbs the bounds allow.
 *
 * Work is L^2 limb products per squaring, so scanning L upward and
 * taking the first that fits minimises it. For a given L the NARROWEST
 * width is both the most feasible - every one of B1, B2 and B3 gets
 * easier as b shrinks, B3 because d + 2 <= b is b*(L-1) <= P - 2 - and
 * the one with the smallest fold, so b = ceil(P/L) is the only width
 * worth testing at each L. An L that no width reaches (because
 * ceil(P/ceil(P/L)) comes back smaller) is skipped. */
static int geometry_derive(const fmt_info *fi, int P, geom *g)
{
    int L, b, d;

    for (L = 2; L <= P; L++) {
        b = (P + L - 1) / L;
        if ((P + b - 1) / b != L)
            continue;
        d = L * b - P;
        if (geom_ok(fi->prec, P, b, L, d)) {
            g->exp = P;
            g->b = b;
            g->L = L;
            g->d = d;
            return 1;
        }
    }
    return 0;
}

static int geometry_force(const fmt_info *fi, int P, int b, int unsafe_ok,
                          geom *g)
{
    int L = (P + b - 1) / b;
    g->exp = P;
    g->b = b;
    g->L = L;
    g->d = L * b - P;
    if (unsafe_ok)
        return (b >= 2 && L >= 2);
    return geom_ok(fi->prec, P, g->b, g->L, g->d);
}

/* ===================================================================
 * The carry split, as an orbit-sequencer program
 * =================================================================== */
enum { K_ZERO = 0, K_ONE, K_PM1, K_ISH, N_CONST };
enum { R_V = 0, R_INV, R_NEG, R_T, R_S, R_HI, R_P, R_LO, R_B, R_W, R_P2 };

/* control codes, docs/SEQUENCER.md */
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };

#define DEPOSITS   3        /* lo, hi, witness */
#define SPLIT_ALU 15        /* elementwise opcodes in one split */

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

/* v = hi * B + lo, with 0 <= lo < B and a witness that says so.
 *
 * B does not appear in the constant bank: 2^-B arrives in r1 and -B in
 * r2, the b and c streams, so this ONE program splits at 2^b during
 * carrying, at 2^(b-d) when the residue is reduced below 2^P, and at
 * 2^64 when the low word is read out. */
static uint8_t *build_program(const fmt_info *fi, size_t *bytes_out,
                              uint32_t *insn_out)
{
    uint64_t ins[64];
    uint32_t n = 0;
    uint8_t consts[N_CONST][MAX_ESZ];
    uint8_t *img;
    size_t esz = fi->esz, i, off;

    val_from_i64(fi, 0, consts[K_ZERO]);
    val_from_i64(fi, 1, consts[K_ONE]);
    bits_from_u64(fi, (uint64_t)(fi->prec - 1), consts[K_PM1]);
    bits_from_u64(fi, (uint64_t)(fi->prec - 1) + fi->bias, consts[K_ISH]);

    /* t = v / B: a power-of-two multiply, exact at every magnitude */
    ins[n++] = alu(CFT_MUL, R_T, R_V, R_INV, 0, 0, 0, 0);
    /* trunc(t) from the encoding: four quiet integer opcodes */
    ins[n++] = alu(CFT_ISHR, R_S, R_T, K_PM1, 0, 0, 1, 0);
    ins[n++] = alu(CFT_ISUB, R_S, K_ISH, R_S, 0, 1, 0, 0);
    ins[n++] = alu(CFT_ISHR, R_HI, R_T, R_S, 0, 0, 0, 0);
    ins[n++] = alu(CFT_ISHL, R_HI, R_HI, R_S, 0, 0, 0, 0);
    /* t < 1 has no integer part, and is the one case the shift above
     * cannot express - s would exceed p-1 and wrap */
    ins[n++] = alu(CFT_CMPLT, R_P, R_T, K_ONE, 0, 0, 1, 0);
    ins[n++] = alu(CFT_SELECT, R_HI, K_ZERO, R_HI, R_P, 1, 0, 0);
    /* lo = v - hi*B: exact, because the true result is an integer
     * below B and the fused multiply-add rounds once or not at all */
    ins[n++] = alu(CFT_FMA, R_LO, R_HI, R_NEG, R_V, 0, 0, 0);
    /* the witness. The integer opcodes above are QUIET, so no flag can
     * report a wrong shift; this can, per element, in the library's own
     * arithmetic. */
    ins[n++] = alu(CFT_NEG, R_B, R_NEG, 0, 0, 0, 0, 0);
    ins[n++] = alu(CFT_FMA, R_W, R_HI, R_B, R_LO, 0, 0, 0);
    ins[n++] = alu(CFT_CMPEQ, R_W, R_W, R_V, 0, 0, 0, 0);
    ins[n++] = alu(CFT_CMPLT, R_P2, R_LO, R_B, 0, 0, 0, 0);
    ins[n++] = alu(CFT_MIN, R_W, R_W, R_P2, 0, 0, 0, 0);
    ins[n++] = alu(CFT_CMPLE, R_P2, K_ZERO, R_LO, 0, 1, 0, 0);
    ins[n++] = alu(CFT_MIN, R_W, R_W, R_P2, 0, 0, 0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_LO, 0);
    ins[n++] = ctl(C_DEPOSIT, R_HI, 0);
    ins[n++] = ctl(C_DEPOSIT, R_W, 0);
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
 * The run
 * =================================================================== */
typedef struct {
    uint64_t exponent;
    int      prime;
    uint64_t squarings;
    uint64_t res64;
} record;

typedef struct {
    cft_format  fmt;
    int         use_program;
    size_t      batch;
    int         limb_req;        /* 0 = derive */
    int         unsafe_limb;
    const char *ckpt;
    double      ckpt_interval;
    int         resume;
    const char *artifact;
    const char *dump_path;
    long        dump_every;
    long        max_squarings;    /* absolute cap per exponent */
    long        stop_after;       /* squarings this INVOCATION may do */
    double      time_limit;
    int         csv;
    int         quiet;
    int         selftest;
} options;

typedef struct {
    const fmt_info *fi;
    options        *opt;
    geom            g;

    /* the program route */
    cft_program *prog;
    uint32_t     n_insns;
    uint8_t     *dep;
    uint32_t    *counts;

    /* per-element arrays, all cap elements of esz bytes */
    size_t   cap;
    uint8_t *y, *yrev, *c, *lo, *hi, *cs, *wit, *scr;
    uint8_t *loop[SPLIT_ALU];    /* scratch for the host-loop engine */

    /* broadcast constants */
    uint8_t *invB, *negB;        /* base 2^b */
    uint8_t *invT, *negT;        /* base 2^(b-d), the reduction below 2^P */
    uint8_t *invW, *negW;        /* base 2^64, reading the low word out */
    uint8_t *bpow2d;             /* 2^d, broadcast, for the fold */
    uint8_t *bmagic;             /* 2^(p-1), broadcast, the integrality gate */
    uint8_t *kminus2;            /* the limbs of 2^P - 3 */
    uint8_t *kmodulus;           /* the limbs of 2^P - 1 */
    uint8_t  one[MAX_ESZ], zero[MAX_ESZ], pow2d[MAX_ESZ];

    /* results */
    record  *recs;
    size_t   nrec;
    uint8_t  chain[32];
    uint64_t squarings_total;
    uint64_t passes_total;

    /* the exponent list and where the run is in it */
    int      exps[MAX_EXPS];
    int      nexp;
    int      at;                 /* index of the exponent in progress */
    long     step;               /* squarings completed for it */
    int      have_current;

    FILE    *dumpf;
} runstate;

/* ---- the three call wrappers ------------------------------------- */
static void runN(runstate *R, cft_op op, const void *a, const void *b,
                 const void *c, void *d, size_t n, const char *what)
{
    size_t off = 0, esz = R->fi->esz, batch = R->opt->batch;
    while (off < n) {
        size_t take = n - off;
        uint32_t f = 0;
        cft_status st;
        if (take > batch)
            take = batch;
        st = cft_run(DEV, op, R->fi->fmt, CFT_RNE,
                     a ? (const uint8_t *)a + off * esz : NULL,
                     b ? (const uint8_t *)b + off * esz : NULL,
                     c ? (const uint8_t *)c + off * esz : NULL,
                     (uint8_t *)d + off * esz, take, &f, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        expect_clean(f, what);
        N_CALLS++;
        N_ELEM_OPS += take;
        off += take;
    }
}

static void dot(runstate *R, const void *a, const void *b, void *d,
                size_t n)
{
    uint32_t f = 0;
    cft_status st = cft_reduce(DEV, CFT_DOT, R->fi->fmt, CFT_RNE, a, b, d,
                               n, &f, NULL);
    if (st != CFT_OK)
        die_st("cft_reduce", st);
    expect_clean(f, "a convolution coefficient (CFT_DOT), where inexact "
                    "means the accumulation left the format's exact range "
                    "and the limb width is too wide for this exponent");
    N_CALLS++;
    N_LIMB_PROD += n;
}

/* v -> (lo, hi, witness) elementwise. The program route runs the
 * nineteen-instruction image once per chunk; the loop route issues the
 * same fifteen opcodes as fifteen cft_run passes. They must agree bit
 * for bit, and mersenne_check.py holds them to it. */
static void split(runstate *R, const uint8_t *v, const uint8_t *inv,
                  const uint8_t *neg, uint8_t *out_lo, uint8_t *out_hi,
                  uint8_t *out_wit, size_t n)
{
    size_t esz = R->fi->esz, off = 0, batch = R->opt->batch, i;

    while (off < n) {
        size_t take = n - off;
        uint32_t f = 0;
        if (take > batch)
            take = batch;

        if (R->opt->use_program) {
            uint32_t bus = 0;
            cft_status st = cft_program_run(R->prog, v + off * esz,
                                            inv + off * esz,
                                            neg + off * esz,
                                            R->dep, R->counts, take, &f,
                                            &bus);
            if (st != CFT_OK)
                die_st("cft_program_run", st);
            if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
                die("the deposit buffer overflowed - the program is wrong");
            expect_clean(f, "the carry split (sequencer program)");
            for (i = 0; i < take; i++) {
                const uint8_t *dp = R->dep + i * DEPOSITS * esz;
                if (R->counts[i] != DEPOSITS)
                    die("a lane deposited the wrong number of values");
                memcpy(out_lo  + (off + i) * esz, dp + 0 * esz, esz);
                memcpy(out_hi  + (off + i) * esz, dp + 1 * esz, esz);
                memcpy(out_wit + (off + i) * esz, dp + 2 * esz, esz);
            }
            N_CALLS++;
            N_ELEM_OPS += take * SPLIT_ALU;
        } else {
            const uint8_t *vv = v + off * esz;
            const uint8_t *iv = inv + off * esz;
            const uint8_t *nv = neg + off * esz;
            uint8_t *t = R->loop[0], *s = R->loop[1], *h = R->loop[2];
            uint8_t *pr = R->loop[3], *lo = R->loop[4], *bb = R->loop[5];
            uint8_t *w = R->loop[6], *p2 = R->loop[7];
            const char *what = "the carry split (host cft_run loop)";
            size_t m = take;

#define LRUN(op, A, B, C, D) do {                                      \
        uint32_t lf = 0;                                               \
        cft_status ls = cft_run(DEV, (op), R->fi->fmt, CFT_RNE,        \
                                (A), (B), (C), (D), m, &lf, NULL);     \
        if (ls != CFT_OK) die_st("cft_run", ls);                       \
        expect_clean(lf, what);                                        \
        N_CALLS++; N_ELEM_OPS += m;                                    \
    } while (0)

            LRUN(CFT_MUL,    vv, iv, NULL, t);
            LRUN(CFT_ISHR,   t,  R->loop[8],  NULL, s);   /* p-1 */
            LRUN(CFT_ISUB,   R->loop[9], s,   NULL, s);   /* ish - s */
            LRUN(CFT_ISHR,   t,  s,  NULL, h);
            LRUN(CFT_ISHL,   h,  s,  NULL, h);
            LRUN(CFT_CMPLT,  t,  R->loop[10], NULL, pr);  /* one */
            LRUN(CFT_SELECT, R->loop[11], h, pr, h);      /* zero */
            LRUN(CFT_FMA,    h,  nv, vv, lo);
            LRUN(CFT_NEG,    nv, NULL, NULL, bb);
            LRUN(CFT_FMA,    h,  bb, lo, w);
            LRUN(CFT_CMPEQ,  w,  vv, NULL, w);
            LRUN(CFT_CMPLT,  lo, bb, NULL, p2);
            LRUN(CFT_MIN,    w,  p2, NULL, w);
            LRUN(CFT_CMPLE,  R->loop[11], lo, NULL, p2);  /* zero <= lo */
            LRUN(CFT_MIN,    w,  p2, NULL, w);
#undef LRUN
            memcpy(out_lo  + off * esz, lo, take * esz);
            memcpy(out_hi  + off * esz, h,  take * esz);
            memcpy(out_wit + off * esz, w,  take * esz);
        }
        off += take;
    }

    /* Every element's witness, every pass. A wrong shift is invisible
     * to the flag word, so this is the only thing that can see it. */
    for (i = 0; i < n; i++)
        if (memcmp(out_wit + i * esz, R->one, esz) != 0) {
            fprintf(stderr,
                    "cft-mersenne: the carry split's per-element witness "
                    "failed at limb %" PRIu64 " - v != hi*B + lo, or lo is "
                    "outside [0, B). The tool, the library, or the argument "
                    "in docs/MERSENNE.md is wrong\n", (uint64_t)i);
            exit(3);
        }
}

/* ---- byte-level predicates over library-produced encodings -------- */
static int is_zero_val(const runstate *R, const uint8_t *v)
{
    return memcmp(v, R->zero, R->fi->esz) == 0;
}

static int all_zero(const runstate *R, const uint8_t *a, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        if (!is_zero_val(R, a + i * R->fi->esz))
            return 0;
    return 1;
}

/* ===================================================================
 * The limb machinery
 * =================================================================== */

/* One carry pass over n limbs. wrap != 0 folds the carry out of the top
 * limb back into limb 0 scaled by 2^d, which is what 2^(L*b) == 2^d
 * means; wrap == 0 requires that carry to be zero, which the value
 * bound guarantees. Returns 1 if anything carried. */
static int carry_pass(runstate *R, uint8_t *y, size_t n, int wrap)
{
    size_t esz = R->fi->esz;

    split(R, y, R->invB, R->negB, R->lo, R->hi, R->wit, n);
    R->passes_total++;
    if (all_zero(R, R->hi, n))
        return 0;

    if (wrap) {
        uint32_t f = 0;
        cft_status st = cft_run(DEV, CFT_MUL, R->fi->fmt, CFT_RNE,
                                R->hi + (n - 1) * esz, R->pow2d, NULL,
                                R->cs, 1, &f, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        expect_clean(f, "the cyclic fold of the top carry");
        N_CALLS++;
        N_ELEM_OPS += 1;
    } else {
        if (!is_zero_val(R, R->hi + (n - 1) * esz))
            die("a carry escaped the top limb of a product, which the "
                "value bound forbids");
        memcpy(R->cs, R->zero, esz);
    }
    memcpy(R->cs + esz, R->hi, (n - 1) * esz);
    runN(R, CFT_ADD, R->lo, NULL, R->cs, y, n, "the carry add");
    return 1;
}

static void normalize(runstate *R, uint8_t *y, size_t n, int wrap)
{
    long guard = 0;
    while (carry_pass(R, y, n, wrap))
        if (++guard > 1000000L)
            die("carry propagation did not converge");
}

/* Every limb must be an INTEGER, and neither the flag word nor the
 * split's witness can say so.
 *
 * The witness proves v == hi*B + lo with 0 <= lo < B. That does not pin
 * hi down: v = 3B/2 satisfies it with (hi, lo) = (1, B/2) and equally
 * with (1.5, 0), and a shift amount that was off by one produces the
 * second - exactly, raising nothing, with the witness satisfied. The
 * error then rides in the limbs, and the dot only notices when the
 * extra fractional bits push a coefficient past 2^p, which at a small
 * exponent they never do. This gate was added because writing the
 * negative controls found that hole.
 *
 * So once per squaring, on the L limbs that are the only state crossing
 * from one squaring to the next: (y + M) - M == y with M = 2^(p-1) is
 * "y is an integer", the magic-constant round the carry split could not
 * use. Here it is exactly the right instrument, because a limb below
 * 2^b is far below M and the addition is exact if and only if the limb
 * is an integer - so the INEXACT it raises is not noise to be masked,
 * it IS the answer, and a correct run raises nothing here either.
 */
static void integrality_gate(runstate *R, uint8_t *y, size_t n)
{
    size_t i;
    runN(R, CFT_ADD, y, NULL, R->bmagic, R->scr, n,
         "the limb integrality gate, where inexact means a limb is not an "
         "integer - which is exactly what the gate is for");
    runN(R, CFT_SUB, R->scr, NULL, R->bmagic, R->scr, n,
         "the limb integrality gate");
    runN(R, CFT_CMPEQ, R->scr, y, NULL, R->scr, n,
         "the limb integrality gate");
    for (i = 0; i < n; i++)
        if (memcmp(R->scr + i * R->fi->esz, R->one, R->fi->esz) != 0) {
            fprintf(stderr,
                    "cft-mersenne: limb %" PRIu64 " of the residue is not an "
                    "integer - the carry split's shift is wrong in a way "
                    "its own witness cannot see\n", (uint64_t)i);
            exit(3);
        }
}

/* Reduce to the unique representative in [0, 2^P - 2]. The residue is
 * carried in L limbs of b bits, so it can sit anywhere below 2^(L*b);
 * only the low (b - d) bits of the top limb belong below 2^P, and what
 * is above folds down with weight 2^0 because 2^P == 1. */
static void canonicalize(runstate *R, uint8_t *y)
{
    size_t esz = R->fi->esz;
    int L = R->g.L;
    long guard = 0;

    for (;;) {
        split(R, y + (size_t)(L - 1) * esz, R->invT, R->negT,
              R->lo, R->hi, R->wit, 1);
        R->passes_total++;
        if (is_zero_val(R, R->hi))
            break;
        memcpy(y + (size_t)(L - 1) * esz, R->lo, esz);
        runN(R, CFT_ADD, y, NULL, R->hi, y, 1, "the reduction below 2^P");
        normalize(R, y, (size_t)L, 1);
        if (++guard > 1000000L)
            die("the reduction below 2^P did not converge");
    }
    /* 2^P - 1 is zero in this ring, and it is the one value the fold
     * above leaves standing. */
    if (memcmp(y, R->kmodulus, (size_t)L * esz) == 0) {
        int k;
        for (k = 0; k < L; k++)
            memcpy(y + (size_t)k * esz, R->zero, esz);
    }
}

/* One Lucas-Lehmer step: y <- y^2 - 2 (mod 2^P - 1), canonical in,
 * canonical out.
 *
 *  1. the linear convolution, 2L-1 dot reductions over slices of y and
 *     of its reversal, whose flag words are the certificates;
 *  2. + (2^P - 3), which is the "- 2";
 *  3. ONE carry pass, which brings every coefficient under
 *     2^b + 2^(p-b) - enough headroom for the fold's 2^d;
 *  4. the fold, y_k = v_k + 2^d * v_{k+L};
 *  5. carry to convergence, cyclically;
 *  6. reduce below 2^P.
 */
static void ll_step(runstate *R)
{
    size_t esz = R->fi->esz;
    int L = R->g.L, k;

    for (k = 0; k < L; k++)
        memcpy(R->yrev + (size_t)k * esz, R->y + (size_t)(L - 1 - k) * esz,
               esz);

    for (k = 0; k < 2 * L - 1; k++) {
        int i0 = k - L + 1 < 0 ? 0 : k - L + 1;
        int i1 = k < L - 1 ? k : L - 1;
        size_t len = (size_t)(i1 - i0 + 1);
        dot(R, R->y + (size_t)i0 * esz,
            R->yrev + (size_t)(L - 1 - k + i0) * esz,
            R->c + (size_t)k * esz, len);
    }
    memcpy(R->c + (size_t)(2 * L - 1) * esz, R->zero, esz);

    runN(R, CFT_ADD, R->c, NULL, R->kminus2, R->c, (size_t)L,
         "the -2 of the recurrence");

    (void)carry_pass(R, R->c, (size_t)(2 * L), 0);

    runN(R, CFT_MUL, R->c + (size_t)L * esz, R->bpow2d, NULL, R->scr,
         (size_t)L, "the fold's scale by 2^d");
    runN(R, CFT_ADD, R->c, NULL, R->scr, R->y, (size_t)L, "the fold");

    normalize(R, R->y, (size_t)L, 1);
    canonicalize(R, R->y);
    integrality_gate(R, R->y, (size_t)L);
}

/* The low 64 bits of a canonical residue - GIMPS's res64, and the one
 * fingerprint that does not depend on which format computed it. The
 * limbs are the library's; splitting each at 2^64 is a library call
 * too; assembling 64 bits out of the pieces is host bookkeeping, and
 * only the limbs with k*b < 64 can reach into the window. */
static uint64_t residue_res64(runstate *R)
{
    size_t esz = R->fi->esz;
    uint64_t out = 0;
    int k;
    for (k = 0; k < R->g.L; k++) {
        int sh = k * R->g.b;
        uint64_t word;
        if (sh >= 64)
            break;
        split(R, R->y + (size_t)k * esz, R->invW, R->negW,
              R->lo, R->hi, R->wit, 1);
        word = val_to_u64(R->fi, R->lo);
        out += word << sh;      /* modulo 2^64, which is what res64 is */
    }
    return out;
}

/* SHA-256 over the canonical limbs, one exact decimal per line. It is
 * the whole residue rather than a window of it, so a wrong limb
 * anywhere shows; it names b and L because those choose the limbs. */
static void residue_digest(runstate *R, uint8_t out[32])
{
    sha256 h;
    char buf[DECMAX];
    int k;
    sha256_start(&h);
    for (k = 0; k < R->g.L; k++) {
        val_to_dec(R->fi, R->y + (size_t)k * R->fi->esz, buf, sizeof buf);
        sha256_push(&h, buf, strlen(buf));
        sha256_push(&h, "\n", 1);
    }
    sha256_end(&h, out);
}

static void residue_set_small(runstate *R, int v)
{
    int k;
    for (k = 0; k < R->g.L; k++)
        memcpy(R->y + (size_t)k * R->fi->esz, R->zero, R->fi->esz);
    val_from_i64(R->fi, v, R->y);
}

/* ===================================================================
 * Per-exponent setup
 * =================================================================== */
static void bcast(const fmt_info *fi, uint8_t *dst, const uint8_t *v,
                  size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        memcpy(dst + i * fi->esz, v, fi->esz);
}

static void engine_setup(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, cap;
    uint8_t t1[MAX_ESZ], t2[MAX_ESZ], three[MAX_ESZ];
    int i, L = R->g.L, b = R->g.b, d = R->g.d;

    cap = (size_t)(2 * L + 2);
    R->cap = cap;

    R->y    = (uint8_t *)xcalloc(cap, esz);
    R->yrev = (uint8_t *)xcalloc(cap, esz);
    R->c    = (uint8_t *)xcalloc(cap, esz);
    R->lo   = (uint8_t *)xcalloc(cap, esz);
    R->hi   = (uint8_t *)xcalloc(cap, esz);
    R->cs   = (uint8_t *)xcalloc(cap, esz);
    R->wit  = (uint8_t *)xcalloc(cap, esz);
    R->scr  = (uint8_t *)xcalloc(cap, esz);
    for (i = 0; i < SPLIT_ALU; i++)
        R->loop[i] = (uint8_t *)xcalloc(cap, esz);

    R->invB = (uint8_t *)xcalloc(cap, esz);
    R->negB = (uint8_t *)xcalloc(cap, esz);
    R->invT = (uint8_t *)xcalloc(cap, esz);
    R->negT = (uint8_t *)xcalloc(cap, esz);
    R->invW = (uint8_t *)xcalloc(cap, esz);
    R->negW = (uint8_t *)xcalloc(cap, esz);
    R->bpow2d   = (uint8_t *)xcalloc(cap, esz);
    R->bmagic   = (uint8_t *)xcalloc(cap, esz);
    R->kminus2  = (uint8_t *)xcalloc(cap, esz);
    R->kmodulus = (uint8_t *)xcalloc(cap, esz);

    val_from_i64(fi, 0, R->zero);
    val_from_i64(fi, 1, R->one);
    val_from_i64(fi, 3, three);
    val_pow2(fi, d, R->pow2d);
    bcast(fi, R->bpow2d, R->pow2d, cap);
    val_pow2(fi, fi->prec - 1, t1);
    bcast(fi, R->bmagic, t1, cap);

    /* the three bases this tool splits at */
    val_pow2(fi, -b, t1);        bcast(fi, R->invB, t1, cap);
    val_pow2(fi, b, t1);
    run1(CFT_NEG, fi->fmt, t1, NULL, NULL, t2, NULL);
    bcast(fi, R->negB, t2, cap);
    val_pow2(fi, -(b - d), t1);  bcast(fi, R->invT, t1, cap);
    val_pow2(fi, b - d, t1);
    run1(CFT_NEG, fi->fmt, t1, NULL, NULL, t2, NULL);
    bcast(fi, R->negT, t2, cap);
    val_pow2(fi, -64, t1);       bcast(fi, R->invW, t1, cap);
    val_pow2(fi, 64, t1);
    run1(CFT_NEG, fi->fmt, t1, NULL, NULL, t2, NULL);
    bcast(fi, R->negW, t2, cap);

    /* the loop engine's broadcast constants, in the same slots the
     * program's constant bank uses */
    bits_from_u64(fi, (uint64_t)(fi->prec - 1), t1);
    bcast(fi, R->loop[8], t1, cap);
    bits_from_u64(fi, (uint64_t)(fi->prec - 1) + fi->bias, t1);
    bcast(fi, R->loop[9], t1, cap);
    bcast(fi, R->loop[10], R->one, cap);
    bcast(fi, R->loop[11], R->zero, cap);

    /* 2^P - 1 as limbs: every limb full, the top one only b-d wide;
     * and 2^P - 3, which is what "- 2" is in this ring */
    val_pow2(fi, b, t1);
    run1(CFT_SUB, fi->fmt, t1, NULL, R->one, t2, NULL);       /* 2^b - 1 */
    for (i = 0; i < L - 1; i++)
        memcpy(R->kmodulus + (size_t)i * esz, t2, esz);
    for (i = 0; i < L - 1; i++)
        memcpy(R->kminus2 + (size_t)i * esz, t2, esz);
    run1(CFT_SUB, fi->fmt, t1, NULL, three, t2, NULL);        /* 2^b - 3 */
    memcpy(R->kminus2, t2, esz);
    val_pow2(fi, b - d, t1);
    run1(CFT_SUB, fi->fmt, t1, NULL, R->one, t2, NULL);   /* 2^(b-d) - 1 */
    memcpy(R->kmodulus + (size_t)(L - 1) * esz, t2, esz);
    memcpy(R->kminus2  + (size_t)(L - 1) * esz, t2, esz);

    if (R->opt->use_program) {
        size_t bytes = 0;
        uint8_t *img = build_program(fi, &bytes, &R->n_insns);
        cft_status st = cft_program_load(DEV, img, bytes, &R->prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load", st);
        R->dep = (uint8_t *)xcalloc(R->opt->batch * DEPOSITS, esz);
        R->counts = (uint32_t *)xcalloc(R->opt->batch, sizeof(uint32_t));
    }
}

static void engine_teardown(runstate *R)
{
    if (R->prog)
        cft_program_free(R->prog);
    R->prog = NULL;
    free(R->y); free(R->yrev); free(R->c); free(R->lo); free(R->hi);
    free(R->cs); free(R->wit); free(R->scr);
    {
        int i;
        for (i = 0; i < SPLIT_ALU; i++) {
            free(R->loop[i]);
            R->loop[i] = NULL;
        }
    }
    free(R->invB); free(R->negB); free(R->invT); free(R->negT);
    free(R->invW); free(R->negW); free(R->bpow2d); free(R->bmagic);
    free(R->kminus2); free(R->kmodulus);
    free(R->dep); free(R->counts);
    R->y = R->yrev = R->c = R->lo = R->hi = R->cs = R->wit = R->scr = NULL;
    R->invB = R->negB = R->invT = R->negT = R->invW = R->negW = NULL;
    R->bpow2d = NULL;
    R->bmagic = NULL;
    R->kminus2 = R->kmodulus = NULL;
    R->dep = NULL;
    R->counts = NULL;
}

/* ===================================================================
 * Records and the hash chain
 *
 * The record is FORMAT-INDEPENDENT on purpose: the exponent, the
 * verdict, the number of squarings and the low 64 bits of the final
 * residue. Two runs at fp64 and fp256 therefore return the same chain,
 * which is the ladder's one contract seen from outside - and res64 is
 * the number every other Lucas-Lehmer implementation reports, so the
 * composite controls are comparable with anybody's.
 * =================================================================== */
static void record_line(const record *r, char *out, size_t cap)
{
    int len = snprintf(out, cap, "%" PRIu64 " %s %" PRIu64 " %016" PRIx64,
                       r->exponent, r->prime ? "prime" : "composite",
                       r->squarings, r->res64);
    if (len <= 0 || (size_t)len >= cap)
        die("record line too long");
}

static void chain_absorb(runstate *R, const record *r)
{
    sha256 h;
    char line[256];
    size_t len;
    record_line(r, line, sizeof line);
    len = strlen(line);
    line[len++] = '\n';
    sha256_start(&h);
    sha256_push(&h, R->chain, sizeof R->chain);
    sha256_push(&h, line, len);
    sha256_end(&h, R->chain);
}

static void dump_residue(runstate *R, long k)
{
    uint8_t dg[32];
    char hx[65];
    if (!R->dumpf)
        return;
    residue_digest(R, dg);
    hex32(dg, hx);
    fprintf(R->dumpf, "%d %ld %d %d %016" PRIx64 " %s\n", R->g.exp, k,
            R->g.b, R->g.L, residue_res64(R), hx);
    fflush(R->dumpf);
}

/* ===================================================================
 * Checkpoint
 *
 * Line-oriented ASCII, written to <path>.tmp and renamed over the
 * target so a reader never sees a half-written one. Everything here
 * describes a RESULT - the exponent list, the records, the chain, the
 * residue in exact decimal limbs and the step index - and nothing
 * describes the machine, which is what lets two runs at different batch
 * sizes and different engines end on byte-identical files. The limb
 * geometry is in it because it is derived from the format and the
 * exponent and a resume must not silently change it.
 * =================================================================== */
#define CKPT_MAGIC "cft-mersenne-checkpoint 1"

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
    options *O = R->opt;
    char tmp[1024], buf[DECMAX], chx[65], line[256];
    FILE *f;
    size_t i;
    int k;

    if (!O->ckpt)
        return;
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt) >= sizeof tmp)
        die("checkpoint path too long");
    f = fopen(tmp, "wb");
    if (!f)
        die("cannot write the checkpoint");

    hex32(R->chain, chx);
    fprintf(f, "%s\n", CKPT_MAGIC);
    fprintf(f, "format %s\n", cft_format_name(R->fi->fmt));
    fprintf(f, "limb %d\n", O->limb_req);
    fprintf(f, "exponents");
    for (k = 0; k < R->nexp; k++)
        fprintf(f, "%c%d", k ? ',' : ' ', R->exps[k]);
    fprintf(f, "\n");
    fprintf(f, "done %" PRIu64 "\n", (uint64_t)R->nrec);
    for (i = 0; i < R->nrec; i++) {
        record_line(&R->recs[i], line, sizeof line);
        fprintf(f, "result %s\n", line);
    }
    fprintf(f, "chain %s\n", chx);
    fprintf(f, "squarings %" PRIu64 "\n", R->squarings_total);
    if (R->have_current) {
        fprintf(f, "current %d %ld\n", R->g.exp, R->step);
        fprintf(f, "geom %d %d %d\n", R->g.b, R->g.L, R->g.d);
        fprintf(f, "residue %d\n", R->g.L);
        for (k = 0; k < R->g.L; k++) {
            val_to_dec(R->fi, R->y + (size_t)k * R->fi->esz, buf,
                       sizeof buf);
            fprintf(f, "%s\n", buf);
        }
    } else {
        fprintf(f, "current - -\n");
        fprintf(f, "geom - - -\n");
        fprintf(f, "residue 0\n");
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

static void parse_exponents(const char *s, int *out, int *n)
{
    char *copy = (char *)xcalloc(strlen(s) + 1, 1);
    char *tok, *save;
    memcpy(copy, s, strlen(s));
    *n = 0;
    save = copy;
    while (save && *save) {
        char *comma = strchr(save, ',');
        tok = save;
        if (comma) { *comma = 0; save = comma + 1; }
        else save = NULL;
        while (*tok == ' ')
            tok++;
        if (!*tok)
            continue;
        if (*n >= MAX_EXPS)
            die("too many exponents in one run");
        out[(*n)++] = (int)strtol(tok, NULL, 10);
    }
    free(copy);
}

/* Read the checkpoint. It is read BEFORE the arrays are sized, so it
 * carries the geometry it was written with and the residue is parked in
 * a scratch list until engine_setup() has run. */
static void ckpt_read(runstate *R, char **park, int *park_n, int *cur_exp,
                      long *cur_step, int *ck_b, int *ck_L, int *ck_d)
{
    options *O = R->opt;
    FILE *f = fopen(O->ckpt, "rb");
    char line[4096];
    int i;

    *park_n = 0;
    *cur_exp = 0;
    *cur_step = 0;
    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, sizeof line, f) ||
        strcmp(trim_nl(line), CKPT_MAGIC) != 0)
        die("that file is not a cft-mersenne checkpoint of this version");

    while (fgets(line, sizeof line, f)) {
        char key[64], *rest;
        trim_nl(line);
        if (sscanf(line, "%63s", key) != 1)
            continue;
        rest = line + strlen(key);
        while (*rest == ' ')
            rest++;
        if (!strcmp(key, "format")) {
            if (strcmp(rest, cft_format_name(R->fi->fmt)) != 0)
                die("the checkpoint was written for a different format");
        } else if (!strcmp(key, "limb")) {
            if (atoi(rest) != O->limb_req)
                die("the checkpoint was written with a different --limb");
        } else if (!strcmp(key, "exponents")) {
            int got[MAX_EXPS], n = 0;
            parse_exponents(rest, got, &n);
            if (n != R->nexp || memcmp(got, R->exps, (size_t)n * sizeof(int)))
                die("the checkpoint was written for a different exponent "
                    "list");
        } else if (!strcmp(key, "done")) {
            R->nrec = (size_t)strtoull(rest, NULL, 10);
            if (R->nrec > (size_t)R->nexp)
                die("the checkpoint holds more results than exponents");
        } else if (!strcmp(key, "result")) {
            char verdict[32];
            record *r;
            if (R->at >= (int)R->nrec)
                die("the checkpoint holds more result lines than it says");
            r = &R->recs[R->at];
            if (sscanf(rest, "%" SCNu64 " %31s %" SCNu64 " %" SCNx64,
                       &r->exponent, verdict, &r->squarings, &r->res64) != 4)
                die("bad checkpoint result line");
            r->prime = strcmp(verdict, "prime") == 0;
            R->at++;
        } else if (!strcmp(key, "chain")) {
            if (!unhex32(rest, R->chain))
                die("bad checkpoint chain");
        } else if (!strcmp(key, "squarings")) {
            R->squarings_total = strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "current")) {
            if (strcmp(rest, "- -") != 0) {
                if (sscanf(rest, "%d %ld", cur_exp, cur_step) != 2)
                    die("bad checkpoint current line");
            }
        } else if (!strcmp(key, "geom")) {
            if (strcmp(rest, "- - -") != 0 &&
                sscanf(rest, "%d %d %d", ck_b, ck_L, ck_d) != 3)
                die("bad checkpoint geom line");
        } else if (!strcmp(key, "residue")) {
            int n = atoi(rest);
            if (n < 0 || n > PARK_MAX)
                die("bad checkpoint residue count");
            *park_n = n;
            for (i = 0; i < n; i++) {
                if (!fgets(line, sizeof line, f))
                    die("the checkpoint ended inside its residue");
                trim_nl(line);
                park[i] = (char *)xcalloc(strlen(line) + 1, 1);
                memcpy(park[i], line, strlen(line));
            }
        } else if (!strcmp(key, "end")) {
            break;
        }
    }
    fclose(f);
    R->at = (int)R->nrec;
}

/* ===================================================================
 * The exactness-bound self test
 *
 * Two dot products, both built from p alone:
 *
 *   under   (2^(p-1) - 1) * 2  +  1 * 1  =  2^p - 1, which the format
 *           holds exactly, so nothing may be raised;
 *   over    2^(p-1) * 2        +  1 * 1  =  2^p + 1, which it does not,
 *           so inexact MUST be raised - and this tool refuses a
 *           reduction that raises it.
 *
 * and a third at the geometry the run will actually use: L copies of
 * (2^b - 1)^2, the largest coefficient any convolution here can
 * produce, which must be clean.
 * =================================================================== */
static int selftest(const fmt_info *fi, options *O, const int *exps,
                    int nexp)
{
    uint8_t a[2 * MAX_ESZ], b[2 * MAX_ESZ], d[MAX_ESZ], want[MAX_ESZ];
    uint8_t t1[MAX_ESZ];
    uint32_t f;
    cft_status st;
    int bad = 0;
    size_t esz = fi->esz;
    char got[DECMAX], expect[DECMAX];

    printf("cft-mersenne selftest, %s, p = %d\n", cft_format_name(fi->fmt),
           fi->prec);

    /* under the bound */
    val_pow2(fi, fi->prec - 1, t1);
    val_from_i64(fi, 1, d);
    run1(CFT_SUB, fi->fmt, t1, NULL, d, a, NULL);
    val_from_i64(fi, 1, a + esz);
    val_from_i64(fi, 2, b);
    val_from_i64(fi, 1, b + esz);
    f = 0;
    st = cft_reduce(DEV, CFT_DOT, fi->fmt, CFT_RNE, a, b, d, 2, &f, NULL);
    if (st != CFT_OK)
        die_st("cft_reduce", st);
    val_pow2(fi, fi->prec, t1);
    val_from_i64(fi, 1, want);
    run1(CFT_SUB, fi->fmt, t1, NULL, want, want, NULL);
    val_to_dec(fi, d, got, sizeof got);
    val_to_dec(fi, want, expect, sizeof expect);
    if (f == 0 && strcmp(got, expect) == 0) {
        printf("  ok   an accumulation reaching 2^p - 1 is exact and raises "
               "nothing: %s\n", got);
    } else {
        printf("  FAIL: 2^p - 1 came back as %s with flags 0x%02x, wanted "
               "%s and 0x00\n", got, (unsigned)f, expect);
        bad++;
    }

    /* over the bound */
    val_pow2(fi, fi->prec - 1, a);
    val_from_i64(fi, 1, a + esz);
    f = 0;
    st = cft_reduce(DEV, CFT_DOT, fi->fmt, CFT_RNE, a, b, d, 2, &f, NULL);
    if (st != CFT_OK)
        die_st("cft_reduce", st);
    val_to_dec(fi, d, got, sizeof got);
    if (f & CFT_FLAG_INEXACT) {
        printf("  ok   an accumulation crossing 2^p raises inexact "
               "(0x%02x); it returned %s, which is not 2^p + 1, and this "
               "tool REFUSES such a coefficient\n", (unsigned)f, got);
    } else {
        printf("  FAIL: 2^p + 1 raised 0x%02x - the certificate this tool "
               "depends on is not there\n", (unsigned)f);
        bad++;
    }

    /* the working geometry, for every exponent this run would do */
    {
        int i;
        uint8_t *vec;
        int maxL = 2;
        geom g;
        for (i = 0; i < nexp; i++) {
            int okg = O->limb_req
                        ? geometry_force(fi, exps[i], O->limb_req,
                                         O->unsafe_limb, &g)
                        : geometry_derive(fi, exps[i], &g);
            if (!okg)
                continue;
            if (g.L > maxL)
                maxL = g.L;
        }
        vec = (uint8_t *)xcalloc((size_t)maxL, esz);
        for (i = 0; i < nexp; i++) {
            int okg = O->limb_req
                        ? geometry_force(fi, exps[i], O->limb_req,
                                         O->unsafe_limb, &g)
                        : geometry_derive(fi, exps[i], &g);
            int k;
            if (!okg) {
                printf("  ok   P = %d has no limb geometry this format can "
                       "hold exactly, and is refused\n", exps[i]);
                continue;
            }
            val_pow2(fi, g.b, t1);
            val_from_i64(fi, 1, want);
            run1(CFT_SUB, fi->fmt, t1, NULL, want, want, NULL);
            for (k = 0; k < g.L; k++)
                memcpy(vec + (size_t)k * esz, want, esz);
            f = 0;
            st = cft_reduce(DEV, CFT_DOT, fi->fmt, CFT_RNE, vec, vec, d,
                            (size_t)g.L, &f, NULL);
            if (st != CFT_OK)
                die_st("cft_reduce", st);
            if (f == 0) {
                printf("  ok   P = %5d: b = %3d, L = %3d, d = %3d - the "
                       "largest coefficient, L*(2^b - 1)^2, is exact\n",
                       exps[i], g.b, g.L, g.d);
            } else {
                printf("  FAIL: P = %d at b = %d, L = %d raised 0x%02x on "
                       "the worst-case coefficient\n",
                       exps[i], g.b, g.L, (unsigned)f);
                bad++;
            }
        }
        free(vec);
    }

    printf("%s\n", bad ? "MERSENNE SELFTEST FAILED"
                       : "MERSENNE SELFTEST OK");
    return bad ? 1 : 0;
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-mersenne - Lucas-Lehmer on libcft, with fp256 as an exact wide\n"
"               integer multiplier\n"
"\n"
"  --set known|small|device   a named exponent list (default known)\n"
"  --exponents a,b,c          an explicit list instead\n"
"  --format fp32|fp64|fp128|fp256    default fp256\n"
"  --engine program|loop      the carry split as a sequencer program\n"
"                             (default) or as fifteen cft_run passes\n"
"  --limb N                   force the limb width; refused unless the\n"
"                             exactness bound allows it\n"
"  --unsafe-limb              accept a limb width the bound forbids, so\n"
"                             that the library's own flag is what stops\n"
"                             the run (this is a test, not a mode)\n"
"  --batch N                  elements per elementwise call (default 4096)\n"
"  --checkpoint PATH          write a resumable checkpoint\n"
"  --checkpoint-interval S    seconds between checkpoints (default 30)\n"
"  --resume                   continue from --checkpoint\n"
"  --dump-residues PATH       write residues for the oracle to check\n"
"  --dump-every K             ...every K squarings (default 1)\n"
"  --max-squarings N          stop each exponent after N squarings\n"
"  --stop-after-squarings N   stop cleanly after N squarings in THIS\n"
"                             invocation, mid-exponent (the resume test)\n"
"  --time S                   stop cleanly after S seconds\n"
"  --artifact PATH            an .xclbin; omit for the software backend\n"
"  --selftest                 the exactness bound, probed rather than\n"
"                             asserted\n"
"  --csv                      machine-readable summary\n"
"  --quiet                    summary only\n"
"\n"
"Every operation of a step is exact or the residue is refused;\n"
"docs/MERSENNE.md is the argument.\n");
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        die("that option needs a value");
    return argv[++(*i)];
}

/* The exponent lists. `known` is the Mersenne prime exponents this
 * software backend can reach in minutes, with the two classic composite
 * controls among them - 1277 and 1619 are prime exponents whose
 * Mersenne numbers are not prime, so the verdicts are checked in both
 * directions. `device` is the next four up, wired in and NOT run here.
 * Ascending order, because the chain is over records in list order. */
static const int SET_KNOWN[] = {
    521, 607, 1277, 1279, 1619, 2203, 2281, 3217, 4253, 4423,
    9689, 9941, 11213
};
static const int SET_SMALL[] = { 521, 607, 1277, 1279, 1619 };
static const int SET_DEVICE[] = { 19937, 21701, 23209, 44497 };

int main(int argc, char **argv)
{
    options O;
    fmt_info fi;
    runstate R;
    cft_caps caps;
    cft_status st;
    double t0, tckpt, elapsed;
    int i, k, stopping = 0, wrote_stop_ckpt = 0;
    long did = 0;
    static char *park[PARK_MAX];
    int park_n = 0, cur_exp = 0, ck_b = 0, ck_L = 0, ck_d = 0;
    long cur_step = 0;
    const char *exps_s = NULL, *set_s = "known";

    memset(&O, 0, sizeof O);
    memset(&R, 0, sizeof R);
    O.fmt = CFT_FP256;
    O.use_program = 1;
    O.batch = 4096;
    O.ckpt_interval = 30.0;
    O.dump_every = 1;
    O.max_squarings = -1;
    O.stop_after = -1;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "--set"))       set_s = need(argc, argv, &i);
        else if (!strcmp(a, "--exponents")) exps_s = need(argc, argv, &i);
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
        } else if (!strcmp(a, "--limb")) {
            O.limb_req = (int)strtol(need(argc, argv, &i), NULL, 10);
            if (O.limb_req < 2) die("--limb must be at least 2");
        }
        else if (!strcmp(a, "--unsafe-limb")) O.unsafe_limb = 1;
        else if (!strcmp(a, "--batch")) {
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
            if (!O.batch) die("--batch must be positive");
        }
        else if (!strcmp(a, "--checkpoint")) O.ckpt = need(argc, argv, &i);
        else if (!strcmp(a, "--checkpoint-interval"))
            O.ckpt_interval = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--resume")) O.resume = 1;
        else if (!strcmp(a, "--dump-residues"))
            O.dump_path = need(argc, argv, &i);
        else if (!strcmp(a, "--dump-every"))
            O.dump_every = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--max-squarings"))
            O.max_squarings = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--stop-after-squarings"))
            O.stop_after = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--time"))
            O.time_limit = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--selftest")) O.selftest = 1;
        else if (!strcmp(a, "--csv")) O.csv = 1;
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-mersenne: unknown option %s\n", a);
            return 2;
        }
    }
    if (O.dump_every < 1)
        die("--dump-every must be at least 1");

    st = cft_open(O.artifact, 0, &DEV);
    if (st != CFT_OK)
        die_st("cft_open", st);

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(DEV, &caps) != CFT_OK)
        die("cft_get_caps failed");
    if (!(caps.format_mask & (1u << (unsigned)O.fmt)))
        die("this backend does not carry that format");
    FLAGS_TRUSTED = caps.flags_readable != 0;

    measure_format(&fi, O.fmt);
    R.fi = &fi;
    R.opt = &O;

    if (exps_s) {
        parse_exponents(exps_s, R.exps, &R.nexp);
    } else if (!strcmp(set_s, "known")) {
        R.nexp = (int)(sizeof SET_KNOWN / sizeof SET_KNOWN[0]);
        memcpy(R.exps, SET_KNOWN, sizeof SET_KNOWN);
    } else if (!strcmp(set_s, "small")) {
        R.nexp = (int)(sizeof SET_SMALL / sizeof SET_SMALL[0]);
        memcpy(R.exps, SET_SMALL, sizeof SET_SMALL);
    } else if (!strcmp(set_s, "device")) {
        R.nexp = (int)(sizeof SET_DEVICE / sizeof SET_DEVICE[0]);
        memcpy(R.exps, SET_DEVICE, sizeof SET_DEVICE);
    } else {
        die("--set takes known, small or device");
    }
    if (!R.nexp)
        die("no exponents to test");
    for (k = 0; k < R.nexp; k++)
        if (R.exps[k] < 3)
            die("a Lucas-Lehmer exponent must be at least 3");

    R.recs = (record *)xcalloc((size_t)R.nexp, sizeof(record));

    /* Measuring p deliberately raised inexact, and 754-2019 7.1 says a
     * status flag is lowered only at the user's request. This is that
     * request: from here the word holds what the RUN raised and nothing
     * else, which the report cross-checks against the union. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);

    if (O.selftest)
        return selftest(&fi, &O, R.exps, R.nexp);

    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R, park, &park_n, &cur_exp, &cur_step, &ck_b, &ck_L,
                  &ck_d);
    }
    if (O.dump_path) {
        R.dumpf = fopen(O.dump_path, O.resume ? "ab" : "wb");
        if (!R.dumpf)
            die("cannot write the residue dump");
    }

    if (!O.quiet && !O.csv)
        printf("cft-mersenne: %s backend, %s, p = %d, %s engine, %d "
               "exponent%s\n", caps.backend, cft_format_name(fi.fmt),
               fi.prec, O.use_program ? "sequencer-program" : "host-loop",
               R.nexp, R.nexp == 1 ? "" : "s");
    if (!FLAGS_TRUSTED && !O.quiet && !O.csv)
        printf("  NOTE: this backend cannot read the exception flags, so "
               "the exactness certificate is not checked\n");

    t0 = now_s();
    tckpt = t0;

    for (; R.at < R.nexp && !stopping; R.at++) {
        int P = R.exps[R.at];
        long need_steps = P - 2, kk;
        double te0 = now_s();
        uint64_t lp0 = N_LIMB_PROD;
        int okg;
        record *rec;

        okg = O.limb_req ? geometry_force(&fi, P, O.limb_req, O.unsafe_limb,
                                          &R.g)
                         : geometry_derive(&fi, P, &R.g);
        if (!okg) {
            fprintf(stderr,
                    "cft-mersenne: P = %d has no limb width this format "
                    "holds exactly (p = %d): a limb needs 2b <= p and a "
                    "coefficient L*2^(2b) <= 2^p, and no b satisfies both "
                    "with L = ceil(P/b)\n", P, fi.prec);
            return 2;
        }
        R.g.exp = P;
        engine_setup(&R);
        R.have_current = 1;

        if (O.resume && P == cur_exp && park_n) {
            if (ck_b != R.g.b || ck_L != R.g.L || ck_d != R.g.d)
                die("the checkpoint's limb geometry is not the one this "
                    "format and exponent derive");
            if (park_n != R.g.L)
                die("the checkpoint's residue is the wrong length");
            for (k = 0; k < R.g.L; k++)
                if (!val_from_dec(&fi, park[k],
                                  R.y + (size_t)k * fi.esz))
                    die("a checkpoint residue limb is not exact in this "
                        "format");
            R.step = cur_step;
            park_n = 0;
        } else {
            residue_set_small(&R, 4);
            R.step = 0;
            if (R.step == 0 && R.dumpf)
                dump_residue(&R, 0);
        }

        if (!O.quiet && !O.csv)
            printf("  P = %-6d b = %3d  L = %3d  d = %3d  %ld squarings, "
                   "%ld limb products each\n",
                   P, R.g.b, R.g.L, R.g.d, need_steps,
                   (long)R.g.L * R.g.L);

        for (kk = R.step; kk < need_steps; kk++) {
            ll_step(&R);
            R.step = kk + 1;
            R.squarings_total++;
            did++;
            if (R.dumpf && (R.step % O.dump_every) == 0)
                dump_residue(&R, R.step);
            if (O.ckpt && now_s() - tckpt >= O.ckpt_interval) {
                ckpt_write(&R);
                tckpt = now_s();
            }
            if (O.max_squarings >= 0 && R.step >= O.max_squarings) {
                stopping = 1;
                break;
            }
            if (O.stop_after >= 0 && did >= O.stop_after) {
                stopping = 1;
                break;
            }
            if (O.time_limit > 0 && now_s() - t0 >= O.time_limit) {
                stopping = 1;
                break;
            }
        }

        if (R.step < need_steps) {
            /* Stopped part way. The checkpoint carries the residue, and
             * it is written HERE, while the arrays still exist; the
             * trailing write below would find them freed. */
            if (O.ckpt) {
                ckpt_write(&R);
                wrote_stop_ckpt = 1;
            }
            if (!O.quiet && !O.csv)
                printf("       stopped at squaring %ld of %ld\n", R.step,
                       need_steps);
            engine_teardown(&R);
            break;
        }

        if (R.dumpf && (R.step % O.dump_every) != 0)
            dump_residue(&R, R.step);

        rec = &R.recs[R.at];
        rec->exponent = (uint64_t)P;
        rec->squarings = (uint64_t)need_steps;
        rec->prime = all_zero(&R, R.y, (size_t)R.g.L);
        rec->res64 = residue_res64(&R);
        chain_absorb(&R, rec);
        R.nrec = (size_t)(R.at + 1);
        R.have_current = 0;
        if (!O.quiet && !O.csv)
            printf("       2^%d - 1 is %-9s res64 %016" PRIx64
                   "   %.3f s, %.0f limb products/s\n",
                   P, rec->prime ? "PRIME" : "COMPOSITE", rec->res64,
                   now_s() - te0,
                   (now_s() - te0) > 0
                       ? (double)(N_LIMB_PROD - lp0) / (now_s() - te0)
                       : 0.0);
        engine_teardown(&R);
        if (O.ckpt)
            ckpt_write(&R);
    }
    elapsed = now_s() - t0;
    if (O.ckpt && !wrote_stop_ckpt)
        ckpt_write(&R);
    if (R.dumpf)
        fclose(R.dumpf);

    /* ---- the report ---- */
    {
        char chx[65];
        double lps = elapsed > 0 ? (double)N_LIMB_PROD / elapsed : 0.0;
        double sps = elapsed > 0 ? (double)R.squarings_total / elapsed : 0.0;
        double eps = elapsed > 0 ? (double)N_ELEM_OPS / elapsed : 0.0;
        uint32_t sw = cft_save_all_flags(DEV);
        hex32(R.chain, chx);

        if (O.csv) {
            printf("backend,format,engine,batch,exponents,resolved,primes,"
                   "squarings,limb_products,elem_ops,calls,seconds,"
                   "limb_products_per_s,squarings_per_s,elem_ops_per_s,"
                   "flags,status,chain\n");
            printf("%s,%s,%s,%" PRIu64 ",%d,%" PRIu64 ",", caps.backend,
                   cft_format_name(fi.fmt),
                   O.use_program ? "program" : "loop",
                   (uint64_t)O.batch, R.nexp, (uint64_t)R.nrec);
            {
                uint64_t np = 0;
                size_t j;
                for (j = 0; j < R.nrec; j++)
                    np += R.recs[j].prime ? 1u : 0u;
                printf("%" PRIu64 ",", np);
            }
            printf("%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64
                   ",%.6f,%.1f,%.3f,%.1f,0x%02x,0x%02x,%s\n",
                   R.squarings_total, N_LIMB_PROD, N_ELEM_OPS, N_CALLS,
                   elapsed, lps, sps, eps, (unsigned)FLAGS_SEEN,
                   (unsigned)sw, chx);
            for (i = 0; i < (int)R.nrec; i++)
                printf("exponent,%" PRIu64 ",%s,%" PRIu64 ",%016" PRIx64
                       "\n", R.recs[i].exponent,
                       R.recs[i].prime ? "prime" : "composite",
                       R.recs[i].squarings, R.recs[i].res64);
        } else if (!O.quiet) {
            printf("\n");
            printf("  backend        %s\n", caps.backend);
            printf("  format         %s, p = %d, integers to 2^%d exact\n",
                   cft_format_name(fi.fmt), fi.prec, fi.prec);
            if (O.use_program)
                printf("  engine         sequencer program, %u instructions,"
                       " %d constants, %d deposits, batch %" PRIu64 "\n",
                       R.n_insns, (int)N_CONST, DEPOSITS,
                       (uint64_t)O.batch);
            else
                printf("  engine         host cft_run loop, %d opcode passes"
                       " per split, batch %" PRIu64 "\n", SPLIT_ALU,
                       (uint64_t)O.batch);
            printf("  resolved       %" PRIu64 " of %d exponents\n",
                   (uint64_t)R.nrec, R.nexp);
            printf("  squarings      %" PRIu64 "\n", R.squarings_total);
            printf("  limb products  %" PRIu64 "\n", N_LIMB_PROD);
            printf("  carry passes   %" PRIu64 "\n", R.passes_total);
            printf("  elem op issues %" PRIu64 "\n", N_ELEM_OPS);
            printf("  library calls  %" PRIu64 "\n", N_CALLS);
            printf("  flags seen     0x%02x%s\n", (unsigned)FLAGS_SEEN,
                   FLAGS_TRUSTED ? "" : "  (this backend cannot read flags)");
            printf("  status word    0x%02x%s\n", (unsigned)sw,
                   sw == FLAGS_SEEN ? " (agrees with the union above)"
                                    : "  DISAGREES WITH THE UNION ABOVE");
            printf("  time           %.3f s\n", elapsed);
            printf("  throughput     %.0f limb products/s, %.3f squarings/s,"
                   " %.0f elementwise op issues/s\n", lps, sps, eps);
            printf("  chain          %s\n", chx);
            printf("\n");
            for (i = 0; i < (int)R.nrec; i++)
                printf("  2^%-6" PRIu64 " - 1  %-9s  %6" PRIu64
                       " squarings  res64 %016" PRIx64 "\n",
                       R.recs[i].exponent,
                       R.recs[i].prime ? "PRIME" : "COMPOSITE",
                       R.recs[i].squarings, R.recs[i].res64);
            printf("\n");
        } else {
            printf("%s\n", chx);
        }
    }

    for (i = 0; i < park_n; i++)
        free(park[i]);
    free(R.recs);
    engine_teardown(&R);
    cft_close(DEV);
    return 0;
}
