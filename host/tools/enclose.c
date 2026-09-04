/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-enclose - rigorous enclosures built out of the directed
 * roundings, so that a numerical result comes with a PROOF of where
 * the true value is.
 *
 *   ./cft-enclose --format fp256
 *   ./cft-enclose --format fp64 --csv bounds.csv
 *   ./cft-enclose --engine loop --kernels horner
 *   ./cft-enclose --checkpoint run.ckpt --resume
 *
 * ---------------------------------------------------------------
 * Why this workload, on this contract
 * ---------------------------------------------------------------
 *
 * Interval arithmetic needs exactly one thing from an arithmetic
 * implementation, and it is the thing almost nobody supplies
 * reliably: a CORRECTLY ROUNDED result in a DIRECTED attribute,
 * chosen per operation. Compute a quantity once under
 * roundTowardNegative and once under roundTowardPositive and the true
 * value is provably between the two - not probably, not to within a
 * tolerance, provably, because each rounding is monotone and each
 * result is on the correct side of the exact one by definition.
 *
 * This contract has all five attributes at every format, per call and
 * - in the sequencer - PER INSTRUCTION, with exact flags. So the
 * enclosure is not an estimate of the error; it IS the error bound,
 * and the flag word says whether the bound is strict.
 *
 * And because the contract is deterministic, two machines produce the
 * SAME interval rather than merely overlapping ones. That is the part
 * an interval library on ordinary hardware cannot offer: the width of
 * an enclosure computed elsewhere is a property of somebody else's
 * compiler flags. Here it is a property of the numbers.
 *
 * ---------------------------------------------------------------
 * The three kernels
 * ---------------------------------------------------------------
 *
 * 1. SERIES. exp(x) = sum_{k>=0} x^k / k!, over dyadic x in [0, 1],
 *    summed under both attributes with a rigorous tail bound added to
 *    the upper bound only. x = 1 is e itself. The term recurrence
 *    t_k = t_{k-1} * x / k is monotone in t_{k-1} for x >= 0, so the
 *    RDN chain stays below the true term and the RUP chain above it,
 *    and the partial sums inherit that. The tail is bounded by
 *
 *        sum_{k>N} x^k/k!  =  t_N * sum_{j>=1} x^j/((N+1)...(N+j))
 *                          <= t_N * (x/(N+1)) / (1 - x/(N+1))
 *                           = t_N * x / (N+1-x)   <=   t_N / N
 *
 *    for 0 <= x <= 1 and N >= 1, and the tool adds RUP(thi_N / N).
 *    N is not a table entry: it is the smallest N for which that
 *    bound falls below 2^-(p+1) at x = 1, found by running the
 *    recurrence at setup, so it tracks the format's own precision.
 *
 * 2. DOT. The classic verified linear-algebra kernel: cft_reduce with
 *    CFT_DOT under RDN and again under RUP. The vectors are built out
 *    of small odd integers times powers of two, so every element is a
 *    dyadic rational, every element is exactly representable at every
 *    format the tool offers, and the exact dot product is a rational
 *    Python's Fractions computes with no rounding at all - which is
 *    what makes the oracle exact rather than approximate.
 *
 *    Three shapes: one whose whole tree is exact (products and every
 *    partial sum inside p bits, so both bounds ARE the value and the
 *    flag word says so by staying clean); a ladder of deliberately
 *    ill-conditioned ones, built by mirroring a block of products so
 *    that they cancel exactly and leaving a known remainder of 1; and
 *    a small matrix-vector product whose exact result is the all-ones
 *    vector.
 *
 * 3. HORNER. A degree-d polynomial with INTERVAL coefficients,
 *    evaluated by interval Horner at dyadic points in [-1, 1]. The
 *    coefficients are 1/k!, which are not dyadic, so each is itself an
 *    enclosure the library computes with one RDN and one RUP division.
 *    This is the kernel that runs as an orbit-sequencer program, and
 *    it is where the per-instruction rounding attribute earns its
 *    encoding bits: the lower and upper bounds come out of ONE
 *    instruction stream, the FMA that advances the lower bound
 *    carrying RDN and the one beside it carrying RUP.
 *
 * ---------------------------------------------------------------
 * Which flags are EXPECTED and which are CERTIFICATES
 * ---------------------------------------------------------------
 *
 * Every operation this tool issues goes through the library and every
 * flag word is read. They divide cleanly:
 *
 *   EXPECTED: inexact. Under a directed attribute inexact means "the
 *     bound is STRICT on that side" - the normal, useful case. It is
 *     never treated as an error and never allowed to hide anything.
 *
 *   FORBIDDEN: invalid, divideByZero, overflow, underflow. Nothing in
 *     any kernel can produce them: no operand is a NaN, no divisor is
 *     zero, and every value stays inside the format's normal range by
 *     construction (the series' term count is tied to p, so the
 *     smallest term is about 2^-p and never subnormal). Any of them
 *     means the tool is wrong, so the tool stops.
 *
 *   CERTIFICATES, in increasing order of strength:
 *
 *     lo <= hi, checked in the library's own arithmetic on EVERY
 *       element of every call. An enclosure whose ends are the wrong
 *       way round is not an enclosure, and this catches a swapped
 *       attribute at the first item rather than at the oracle.
 *
 *     lo == hi, per element, which PROVES the true value is exactly
 *       representable and that both bounds are it. That direction is a
 *       theorem: lo <= v <= hi and lo == hi force v == lo. The
 *       converse is not a theorem and is not claimed.
 *
 *     a clean flag word on a paired call. If a call issued under RDN
 *       and its twin under RUP both report inexact CLEAR, then no
 *       rounding happened on either side, both chains evaluated the
 *       exact value, and every element's width is zero. The tool
 *       asserts that implication on every paired call. For the dot
 *       kernel the calls are per ITEM whatever the batch size, so
 *       there the flag word is a per-item certificate and the tool
 *       reports, per side, how often it was clean.
 *
 *     containment against the oracle, which is the only one of these
 *       that can catch a bound computed in the wrong direction on both
 *       sides at once. host/tests/enclose_check.py is that oracle.
 *
 * The union problem docs/COLLATZ.md records applies here too: a call
 * over a batch reports the OR of its elements' flags, so for the
 * series and Horner kernels the per-item side-exactness cannot be
 * read off the flag word at batch sizes above one. It is therefore
 * not recorded for them at all, rather than recorded at a value that
 * depends on the batch size - because everything this tool writes
 * down has to be batch-size independent.
 *
 * ---------------------------------------------------------------
 * Where each kernel runs, and why
 * ---------------------------------------------------------------
 *
 * --engine program (the default) runs the Horner kernel as orbit
 * sequencer programs (docs/SEQUENCER.md): eight Horner steps per
 * program, the incoming interval arriving in r1/r2 from the b and c
 * streams and the outgoing one leaving through two DEPOSITs, so the
 * deposits of one call are the streams of the next. --engine loop
 * issues the identical steps as four cft_run passes per Horner step
 * from the host. The two must agree bit for bit, and the cross-check
 * holds them to it.
 *
 * The other two kernels have ONE engine each, and the reasons are
 * worth writing down because they are observations about the program
 * model rather than about this workload:
 *
 *   The SERIES kernel divides. cft_div is a COMPOSED operation - a
 *   host-orchestrated seed-and-Newton sequence, per docs/HOSTAPI.md -
 *   and composed operations are not in the sequencer's opcode set, so
 *   a program cannot issue one. (The library itself already issues
 *   that sequence AS a program; what is missing is a way for one
 *   program to call another.) The obvious workaround - a bank of
 *   precomputed 1/k enclosures - runs into the second wall below.
 *
 *   The DOT kernel reduces. A reduction is not elementwise: it crosses
 *   lanes, and the sequencer is per-lane by construction (P2 of
 *   docs/SEQUENCER.md addresses every deposit by the lane's own
 *   index). There is no reduction instruction and there should not be
 *   one; cft_reduce is the right entry point and the contractual tree
 *   is what makes its answer reproducible.
 *
 * ---------------------------------------------------------------
 * The wall the Horner kernel actually hit
 * ---------------------------------------------------------------
 *
 * A sequencer instruction names its operands in FOUR-BIT fields, and
 * the `ka`/`kb`/`kc` bits redirect those same fields at the constant
 * bank - so a program can address exactly SIXTEEN constants, whatever
 * `n_consts` in its header says. A polynomial with interval
 * coefficients needs two constants per coefficient, so one program
 * holds eight coefficients and no more.
 *
 * That is why the Horner kernel is chunked into programs of eight
 * steps rather than compiled whole, and why --degree must satisfy
 * (degree + 1) % 8 == 0. The chunking is not a hardship - it is the
 * same "deposits feed the next call" pattern the Collatz explorer
 * uses to resume a trajectory - but the sixteen-constant ceiling is a
 * real limit on table-driven programs and is recorded in docs/ENCLOSE.md
 * for the sequencer's designers.
 *
 * ---------------------------------------------------------------
 * Determinism
 * ---------------------------------------------------------------
 *
 * An enclosure produced by this tool is the same bits on every
 * conforming host, so a verified result can be REPRODUCED rather than
 * merely re-derived. Nothing here depends on arrival order: the
 * reductions use the contract's index-fixed tree, the elementwise
 * work is elementwise, the deposits are addressed by element index,
 * and the hash chain is taken over records in item order rather than
 * completion order. The properties are tested rather than asserted -
 * host/tests/enclose_check.py and `make -C host enclosetest`.
 *
 * No constant below is transcribed. p is measured from the library by
 * finding the smallest k for which 2^k + 1 raises inexact; the series
 * term count follows from p; the coefficient enclosures are computed
 * by the library; the vector data comes from a SHA-256 stream rather
 * than from a generator with magic multipliers; and SHA-256's own
 * round constants are derived from the cube roots of the primes.
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

#define MAX_ESZ  32     /* bytes in the widest element, binary256 */
#define HEXMAX  160     /* an exact hexadecimal sequence, 5.12.3 */
#define DECMAX  512     /* a rounded decimal sequence, for humans */
#define CHUNK     8     /* Horner steps per program: 16 constants / 2 */

static void die(const char *what)
{
    fprintf(stderr, "cft-enclose: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-enclose: %s: %s%s%s\n", what, cft_strerror(st),
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
 * memory. SHA-256's eight initial words and sixty-four round
 * constants are SPECIFIED as the fractional parts of the square and
 * cube roots of the first primes, so that is how they are computed
 * here - by integer search, with no floating point and nothing to
 * mistype. host/tests/enclose_check.py recomputes the whole chain
 * with Python's hashlib, which is what proves the derivation.
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

/* exact 64 x 64 -> 128 */
static u128 u128_mul64(uint64_t a, uint64_t b)
{
    uint64_t al = a & 0xffffffffu, ah = a >> 32;
    uint64_t bl = b & 0xffffffffu, bh = b >> 32;
    uint64_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint64_t mid = (ll >> 32) + (lh & 0xffffffffu) + (hl & 0xffffffffu);
    u128 r;
    r.lo = (mid << 32) | (ll & 0xffffffffu);
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

/* floor(frac(v^(1/root)) * 2^32), root 2 or 3: the low 32 bits of
 * floor((v << (32*root))^(1/root)), found by binary search over an
 * exact 128-bit power. */
static uint32_t root_frac32(uint32_t v, int root)
{
    u128 target = u128_shl(u128_mk(0, v), 32 * root);
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

/* A reproducible byte stream, from SHA-256 rather than from a
 * generator whose multipliers would be magic numbers. The vectors of
 * the dot kernel are drawn from it, so they are the same on every
 * machine and are regenerated identically after a resume. */
typedef struct {
    const char *label;
    uint64_t    counter;
    uint8_t     buf[32];
    size_t      have;
} rng;

static void rng_seed(rng *g, const char *label, uint64_t stream)
{
    memset(g, 0, sizeof *g);
    g->label = label;
    g->counter = stream << 32;
}

static uint64_t rng_u64(rng *g)
{
    uint64_t v = 0;
    size_t i;
    if (g->have < 8) {
        sha256 h;
        uint8_t ctr[8];
        for (i = 0; i < 8; i++)
            ctr[i] = (uint8_t)(g->counter >> (8 * i));
        sha256_start(&h);
        sha256_push(&h, g->label, strlen(g->label));
        sha256_push(&h, ctr, sizeof ctr);
        sha256_end(&h, g->buf);
        g->counter++;
        g->have = 32;
    }
    for (i = 0; i < 8; i++)
        v |= (uint64_t)g->buf[32 - g->have + i] << (8 * i);
    g->have -= 8;
    return v;
}

/* ===================================================================
 * Format parameters, measured rather than tabulated
 * =================================================================== */
typedef struct {
    cft_format fmt;
    size_t     esz;      /* bytes per element */
    int        width;    /* bits */
    int        prec;     /* p, significand bits, hidden one included */
} fmt_info;

static cft_device *DEV;

static void run1(cft_op op, cft_format fmt, cft_round rnd, const void *a,
                 const void *b, const void *c, void *d, uint32_t *fl)
{
    cft_status st = cft_run(DEV, op, fmt, rnd, a, b, c, d, 1, fl, NULL);
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
     * the library answers that question itself, in the flag it
     * raises. */
    fi->prec = 0;
    for (k = 1; k < fi->width; k++) {
        uint32_t fl = 0;
        st = cft_scaleb(DEV, fmt, CFT_RNE, one, k, pow, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_scaleb", st);
        run1(CFT_ADD, fmt, CFT_RNE, pow, NULL, one, sum, &fl);
        if (fl & CFT_FLAG_INEXACT) {
            fi->prec = k;
            break;
        }
    }
    if (!fi->prec)
        die("could not measure the format's precision");
}

/* ===================================================================
 * Values
 * =================================================================== */
static void val_from_i64(const fmt_info *fi, int64_t v, void *out)
{
    uint32_t fl = 0;
    cft_status st = cft_cvt_from_i64(DEV, fi->fmt, CFT_RNE, &v, out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);
    if (fl & CFT_FLAG_INEXACT)
        die("an integer this workload needs is not exact in this format");
}

/* v * 2^e, 0 if the format cannot hold it exactly */
static int val_scale_ok(const fmt_info *fi, const void *v, int64_t e,
                        void *out)
{
    uint32_t fl = 0;
    cft_status st = cft_scaleb(DEV, fi->fmt, CFT_RNE, v, e, out, 1, &fl, NULL);
    if (st != CFT_OK)
        die_st("cft_scaleb", st);
    return fl == 0;
}

/* v * 2^e, refused rather than rounded */
static void val_scale(const fmt_info *fi, const void *v, int64_t e,
                      void *out)
{
    if (!val_scale_ok(fi, v, e, out))
        die("a scaled constant this workload needs is not exact in this "
            "format");
}

static void val_pow2(const fmt_info *fi, int64_t e, void *out)
{
    uint8_t one[MAX_ESZ];
    val_from_i64(fi, 1, one);
    val_scale(fi, one, e, out);
}

static void val_to_hex(const fmt_info *fi, const void *v, char *out,
                       size_t cap)
{
    size_t len = 0;
    cft_status st = cft_to_hex_char(DEV, fi->fmt, v, out, cap, &len);
    if (st != CFT_OK)
        die_st("cft_to_hex_char", st);
}

static int val_from_hex(const fmt_info *fi, const char *s, void *out)
{
    const char *arr[1];
    uint32_t fl = 0;
    cft_status st;
    arr[0] = s;
    st = cft_from_hex_char(DEV, fi->fmt, CFT_RNE, arr, out, 1, NULL, &fl);
    if (st != CFT_OK)
        return 0;
    return (fl & (CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW)) == 0;
}

/* A short decimal for human eyes, rounded in the direction that keeps
 * it a valid bound: a lower bound prints under RDN and an upper bound
 * under RUP, so the printed pair still encloses the value.
 *
 * This raises inexact, and it is not arithmetic - so the device's
 * 754-2019 7.1 status word is saved across it and restored after,
 * which is exactly what 5.7.4 provides saveAllFlags/restoreFlags for.
 * Without that the report's cross-check between the union of the
 * calls' flags and the status word would be measuring the printing. */
static void val_to_dec(const fmt_info *fi, const void *v, cft_round rnd,
                       size_t digits, char *out, size_t cap)
{
    uint32_t saved = cft_save_all_flags(DEV);
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, rnd, v, digits, out,
                                        cap, &len, NULL);
    cft_restore_flags(DEV, saved, CFT_FLAGS_ALL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

static int pred_true(const fmt_info *fi, const void *v)
{
    uint8_t zero[MAX_ESZ];
    memset(zero, 0, fi->esz);
    return memcmp(v, zero, fi->esz) != 0;
}

/* Comparisons go through the library like everything else. They are
 * quiet opcodes: no rounding, no flag, nothing to pollute. */
static int val_cmp_op(const fmt_info *fi, cft_op op, const void *a,
                      const void *b)
{
    uint8_t r[MAX_ESZ];
    run1(op, fi->fmt, CFT_RNE, a, b, NULL, r, NULL);
    return pred_true(fi, r);
}

static int val_lt(const fmt_info *fi, const void *a, const void *b)
{
    return val_cmp_op(fi, CFT_CMPLT, a, b);
}

static int val_le(const fmt_info *fi, const void *a, const void *b)
{
    return val_cmp_op(fi, CFT_CMPLE, a, b);
}

/* ===================================================================
 * The flag policy
 * =================================================================== */
#define FORBIDDEN_FLAGS (CFT_FLAG_INVALID | CFT_FLAG_DIVBYZERO | \
                         CFT_FLAG_OVERFLOW | CFT_FLAG_UNDERFLOW)

static void flags_expect(uint32_t f, const char *where)
{
    if (f & FORBIDDEN_FLAGS) {
        fprintf(stderr,
                "cft-enclose: %s raised 0x%02x, and inexact is the only "
                "flag any kernel here can produce - stopping\n",
                where, (unsigned)f);
        exit(3);
    }
}

/* ===================================================================
 * The batch engine
 * =================================================================== */
enum { KER_SERIES = 0, KER_DOT, KER_HORNER, N_KERNELS };

static const char *KERNEL_NAME[N_KERNELS] = { "series", "dot", "horner" };

/* sequencer control codes, docs/SEQUENCER.md */
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };

#define DEPOSITS 2      /* the lower and the upper bound */

static uint64_t alu(int op, int rnd, int rd, int ra, int rb, int rc,
                    int ka, int kb, int kc)
{
    return (uint64_t)(uint32_t)op |
           ((uint64_t)(uint32_t)rd << 8) |
           ((uint64_t)(uint32_t)ra << 12) |
           ((uint64_t)(uint32_t)rb << 16) |
           ((uint64_t)(uint32_t)rc << 20) |
           ((uint64_t)(uint32_t)rnd << 24) |
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

/* Registers, all of them named so the program reads like the doc.
 * r5 is the zero: r3..r15 start at +0 on every run and this program
 * never writes it, so the constant bank does not have to spend one of
 * its sixteen slots on a zero. */
enum { P_X = 0, P_LO = 1, P_HI = 2, P_ZERO = 5, P_NN = 6, P_MA = 7,
       P_MB = 8 };

/* One chunk of the interval Horner recurrence, as a program image.
 *
 *   nn <- (0 <= x)                          once, at the top
 *   ma <- nn ? lo : hi                      the operand the LOWER
 *   mb <- nn ? hi : lo                      bound needs, and the upper
 *   lo <- fma(x, ma, clo)  [RDN]            <- the two attributes that
 *   hi <- fma(x, mb, chi)  [RUP]               make this one stream
 *
 * repeated CHUNK times over CHUNK consecutive coefficients, then two
 * DEPOSITs. For a point x and an interval [lo, hi], x*[lo,hi] is
 * [x*lo, x*hi] when x >= 0 and [x*hi, x*lo] when it is negative -
 * which is the whole content of the two SELECTs.
 */
static uint8_t *build_chunk(const fmt_info *fi, const uint8_t *clo,
                            const uint8_t *chi, size_t nsteps,
                            size_t *bytes_out, uint32_t *insn_out)
{
    uint64_t ins[64];
    uint32_t n = 0;
    size_t esz = fi->esz, i, off, nconst = 2 * nsteps;
    uint8_t *img;

    if (nsteps == 0 || nsteps > CHUNK)
        die("a Horner chunk must hold between one and eight steps");

    ins[n++] = alu(CFT_CMPLE, CFT_RNE, P_NN, P_ZERO, P_X, 0, 0, 0, 0);
    for (i = 0; i < nsteps; i++) {
        ins[n++] = alu(CFT_SELECT, CFT_RNE, P_MA, P_LO, P_HI, P_NN, 0, 0, 0);
        ins[n++] = alu(CFT_SELECT, CFT_RNE, P_MB, P_HI, P_LO, P_NN, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, CFT_RDN, P_LO, P_X, P_MA, (int)(2 * i),
                       0, 0, 1);
        ins[n++] = alu(CFT_FMA, CFT_RUP, P_HI, P_X, P_MB, (int)(2 * i + 1),
                       0, 0, 1);
    }
    ins[n++] = ctl(C_DEPOSIT, P_LO, 0);
    ins[n++] = ctl(C_DEPOSIT, P_HI, 0);
    ins[n++] = ctl(C_HALT, 0, 0);

    *insn_out = n;
    *bytes_out = 32 + nconst * esz + (size_t)n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);                    /* version */
    put_le32(img + 8, n);
    put_le32(img + 12, (uint32_t)nconst);
    put_le32(img + 16, DEPOSITS);
    put_le32(img + 20, (uint32_t)fi->fmt);
    off = 32;
    for (i = 0; i < nsteps; i++) {
        memcpy(img + off, clo + i * esz, esz);
        off += esz;
        memcpy(img + off, chi + i * esz, esz);
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
    cft_format  fmt;
    int         use_program;
    int         want[N_KERNELS];
    size_t      points;        /* a power of two; each point kernel
                                * evaluates points + 1 items */
    int         degree;
    size_t      dot_m;         /* half-length of the mirrored block */
    int         dot_top;       /* exponent of the largest product */
    int         cond_max;      /* the widest exponent spread */
    int         cond_levels;
    size_t      rows;          /* matrix-vector rows */
    size_t      batch;
    const char *ckpt;
    double      ckpt_interval;
    int         resume;
    long        stop_after_batches;
    long        stop_after_passes;
    double      time_limit;
    const char *artifact;
    const char *records_path;
    const char *csv_path;
    const char *vec_path;
    const char *coef_path;
    int         summary_csv;
    int         quiet;
} options;

typedef struct {
    int      kernel;
    uint64_t idx;
    char     lo[HEXMAX], hi[HEXMAX], w[HEXMAX];
    int      exact;
} record;

typedef struct {
    uint64_t n[N_KERNELS], nexact[N_KERNELS];
    int      have_max[N_KERNELS];
    uint8_t  maxw[N_KERNELS][MAX_ESZ];
    uint64_t maxw_idx[N_KERNELS];
    /* the dot kernel alone can attribute a flag word to an item,
     * because its calls are per item at every batch size */
    uint64_t lo_side_exact, hi_side_exact, straddle;
    int      have_e;
    char     e_lo[HEXMAX], e_hi[HEXMAX];
    uint8_t  chain[32];
} stats;

typedef struct {
    const fmt_info *fi;
    options        *opt;
    stats           st;

    size_t   items[N_KERNELS];   /* per kernel */
    size_t   base[N_KERNELS];    /* first global index */
    size_t   total;
    size_t   cursor;             /* items whose records are in the chain */

    /* series */
    int      terms;              /* N, derived from p */
    size_t   inflight;
    int      inflight_kernel;
    int      sterm;
    uint8_t *sx, *stlo, *sthi, *sslo, *sshi;

    /* horner */
    uint8_t     *clo, *chi;      /* degree + 1 coefficient bounds */
    size_t       chunks;
    cft_program **prog;
    uint8_t     *dep;
    uint32_t    *counts;
    uint8_t     *hx, *hlo, *hhi, *hnn, *hma, *hmb, *hbclo, *hbchi, *hzero;

    /* dot */
    uint8_t *dx, *dy;
    size_t   dot_cap;

    /* scratch, batch-wide */
    uint8_t *t1, *t2, *kv, *zero, *one;

    uint32_t flags_seen;
    int      flags_trusted;
    uint64_t calls;
    uint64_t elem_ops;           /* elementwise element-operations */
    long     passes;

    FILE    *recf, *csvf;
} runstate;

/* ---- the item map ------------------------------------------------ */
static size_t dot_items(const options *O)
{
    return 1 + (size_t)O->cond_levels + O->rows;
}

static void plan_items(runstate *R)
{
    options *O = R->opt;
    size_t at = 0, k;
    R->items[KER_SERIES] = O->want[KER_SERIES] ? O->points + 1 : 0;
    R->items[KER_DOT]    = O->want[KER_DOT]    ? dot_items(O)  : 0;
    R->items[KER_HORNER] = O->want[KER_HORNER] ? O->points + 1 : 0;
    for (k = 0; k < N_KERNELS; k++) {
        R->base[k] = at;
        at += R->items[k];
    }
    R->total = at;
}

static int kernel_of(const runstate *R, size_t gi, size_t *local)
{
    size_t k;
    for (k = 0; k < N_KERNELS; k++) {
        if (R->items[k] && gi >= R->base[k] && gi < R->base[k] + R->items[k]) {
            *local = gi - R->base[k];
            return (int)k;
        }
    }
    die("an item index fell outside every kernel");
    return 0;
}

/* ---- records and the chain --------------------------------------- */
static void record_line(const record *r, char *out, size_t cap)
{
    int len = snprintf(out, cap, "%s %" PRIu64 " %s %s %s %s",
                       KERNEL_NAME[r->kernel], r->idx, r->lo, r->hi, r->w,
                       r->exact ? "exact" : "strict");
    if (len <= 0 || (size_t)len >= cap)
        die("record line too long");
}

static void chain_absorb(stats *S, const record *r)
{
    sha256 h;
    char line[4 * HEXMAX + 64];
    size_t len;
    record_line(r, line, sizeof line);
    len = strlen(line);
    line[len++] = '\n';
    sha256_start(&h);
    sha256_push(&h, S->chain, sizeof S->chain);
    sha256_push(&h, line, len);
    sha256_end(&h, S->chain);
}

/* Every enclosure the tool produces passes through here, in item
 * order. The width is hi - lo under RUP, so the number reported is
 * itself an upper bound on the true width. */
static void emit(runstate *R, int kernel, uint64_t idx, const void *lo,
                 const void *hi, const char *label)
{
    const fmt_info *fi = R->fi;
    stats *S = &R->st;
    record r;
    uint8_t w[MAX_ESZ];
    uint32_t fl = 0;
    char line[4 * HEXMAX + 64];

    if (!val_le(fi, lo, hi))
        die("an enclosure came back with its ends the wrong way round - "
            "a rounding attribute is wrong");

    run1(CFT_SUB, fi->fmt, CFT_RUP, hi, NULL, lo, w, &fl);
    flags_expect(fl, "the width");
    R->flags_seen |= fl;
    R->elem_ops += 1;

    memset(&r, 0, sizeof r);
    r.kernel = kernel;
    r.idx = idx;
    val_to_hex(fi, lo, r.lo, HEXMAX);
    val_to_hex(fi, hi, r.hi, HEXMAX);
    val_to_hex(fi, w, r.w, HEXMAX);
    r.exact = memcmp(lo, hi, fi->esz) == 0;

    S->n[kernel]++;
    if (r.exact)
        S->nexact[kernel]++;
    if (!S->have_max[kernel] || val_lt(fi, S->maxw[kernel], w)) {
        S->have_max[kernel] = 1;
        memcpy(S->maxw[kernel], w, fi->esz);
        S->maxw_idx[kernel] = idx;
    }
    if (kernel == KER_DOT) {
        if (val_le(fi, lo, R->zero) && val_le(fi, R->zero, hi))
            S->straddle++;
    }
    if (kernel == KER_SERIES && idx == R->opt->points) {
        S->have_e = 1;
        memcpy(S->e_lo, r.lo, sizeof S->e_lo);
        memcpy(S->e_hi, r.hi, sizeof S->e_hi);
    }

    chain_absorb(S, &r);
    record_line(&r, line, sizeof line);
    if (R->recf)
        fprintf(R->recf, "%s\n", line);
    if (R->csvf) {
        char dlo[DECMAX], dhi[DECMAX], dw[DECMAX];
        val_to_dec(fi, lo, CFT_RDN, 24, dlo, sizeof dlo);
        val_to_dec(fi, hi, CFT_RUP, 24, dhi, sizeof dhi);
        val_to_dec(fi, w,  CFT_RUP, 6,  dw,  sizeof dw);
        fprintf(R->csvf, "%s,%" PRIu64 ",%s,%s,%s,%s,%s,%s,%s,%s\n",
                KERNEL_NAME[kernel], idx, label, r.lo, r.hi, dlo, dhi,
                r.w, dw, r.exact ? "exact" : "strict");
    }
}

/* ===================================================================
 * Kernel 1: the series
 * =================================================================== */
static void runN(runstate *R, cft_op op, cft_round rnd, const void *a,
                 const void *b, const void *c, void *d, size_t n,
                 uint32_t *fl)
{
    uint32_t r = 0;
    cft_status st = cft_run(DEV, op, R->fi->fmt, rnd, a, b, c, d, n, &r,
                            NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    *fl |= r;
    R->calls++;
    R->elem_ops += n;
}

static void divN(runstate *R, cft_round rnd, const void *a, const void *b,
                 void *d, size_t n, uint32_t *fl)
{
    uint32_t r = 0;
    cft_status st = cft_div(DEV, R->fi->fmt, rnd, a, b, d, n, &r, NULL);
    if (st != CFT_OK)
        die_st("cft_div", st);
    *fl |= r;
    R->calls++;
    R->elem_ops += n;
}

static void bcast(const fmt_info *fi, uint8_t *dst, const void *v, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        memcpy(dst + i * fi->esz, v, fi->esz);
}

/* x = j / points, exact because points is a power of two */
static void series_point(runstate *R, size_t j, void *out)
{
    const fmt_info *fi = R->fi;
    size_t p = R->opt->points;
    int64_t sh = 0;
    uint8_t v[MAX_ESZ];
    while ((size_t)1 << sh != p)
        sh++;
    val_from_i64(fi, (int64_t)j, v);
    if (j == 0)
        memcpy(out, v, fi->esz);
    else
        val_scale(fi, v, -sh, out);
}

static void series_begin(runstate *R, size_t base, size_t n)
{
    const fmt_info *fi = R->fi;
    size_t i, esz = fi->esz;
    for (i = 0; i < n; i++) {
        series_point(R, base + i, R->sx + i * esz);
        memcpy(R->stlo + i * esz, R->one, esz);
        memcpy(R->sthi + i * esz, R->one, esz);
        memcpy(R->sslo + i * esz, R->one, esz);
        memcpy(R->sshi + i * esz, R->one, esz);
    }
    R->sterm = 0;
    R->inflight = n;
    R->inflight_kernel = KER_SERIES;
}

/* One term of the recurrence over the whole batch:
 *
 *   t <- t * x / k        both attributes, monotone in t for x >= 0
 *   s <- s + t
 */
static void series_pass(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t n = R->inflight;
    uint32_t f = 0;
    uint8_t k[MAX_ESZ];

    R->sterm++;
    val_from_i64(fi, R->sterm, k);
    bcast(fi, R->kv, k, n);

    runN(R, CFT_MUL, CFT_RDN, R->stlo, R->sx, NULL, R->t1, n, &f);
    divN(R, CFT_RDN, R->t1, R->kv, R->stlo, n, &f);
    runN(R, CFT_MUL, CFT_RUP, R->sthi, R->sx, NULL, R->t2, n, &f);
    divN(R, CFT_RUP, R->t2, R->kv, R->sthi, n, &f);
    runN(R, CFT_ADD, CFT_RDN, R->sslo, NULL, R->stlo, R->sslo, n, &f);
    runN(R, CFT_ADD, CFT_RUP, R->sshi, NULL, R->sthi, R->sshi, n, &f);

    flags_expect(f, "a series term");
    R->flags_seen |= f;
    R->passes++;
}

static void series_finish(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t n = R->inflight, i, esz = fi->esz;
    uint32_t f = 0;
    uint8_t nv[MAX_ESZ];

    /* the tail, bounded by t_N / N and charged to the UPPER bound
     * alone: the lower bound is a partial sum of positive terms and is
     * below the limit already. */
    val_from_i64(fi, R->terms, nv);
    bcast(fi, R->kv, nv, n);
    divN(R, CFT_RUP, R->sthi, R->kv, R->t2, n, &f);
    runN(R, CFT_ADD, CFT_RUP, R->sshi, NULL, R->t2, R->sshi, n, &f);
    flags_expect(f, "the series tail bound");
    R->flags_seen |= f;

    for (i = 0; i < n; i++) {
        char label[DECMAX];
        val_to_dec(fi, R->sx + i * esz, CFT_RNE, 12, label, sizeof label);
        emit(R, KER_SERIES, (uint64_t)(R->cursor + i),
             R->sslo + i * esz, R->sshi + i * esz, label);
    }
    R->cursor += n;
    R->inflight = 0;
}

/* N: the smallest term count whose tail bound at x = 1 falls below
 * 2^-(p+1). Found by running the recurrence, so it is the format's
 * answer and not a table's. */
static int series_terms(runstate *R)
{
    const fmt_info *fi = R->fi;
    uint8_t t[MAX_ESZ], kk[MAX_ESZ], tail[MAX_ESZ], lim[MAX_ESZ];
    int k;
    uint32_t saved = cft_save_all_flags(DEV);

    val_from_i64(fi, 1, t);
    val_pow2(fi, -(int64_t)fi->prec - 1, lim);
    for (k = 1; k < 4 * fi->prec; k++) {
        cft_status st;
        val_from_i64(fi, k, kk);
        st = cft_div(DEV, fi->fmt, CFT_RUP, t, kk, t, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        st = cft_div(DEV, fi->fmt, CFT_RUP, t, kk, tail, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        if (val_lt(fi, tail, lim)) {
            cft_restore_flags(DEV, saved, CFT_FLAGS_ALL);
            return k;
        }
    }
    die("the series never reached its tail bound");
    return 0;
}

/* ===================================================================
 * Kernel 2: the dot products
 *
 * Every element is (odd integer < 2^mw) * 2^e, so it is a dyadic
 * rational the format holds exactly and Python's Fractions computes
 * with exactly. mw is chosen so a PRODUCT of two of them still fits p
 * bits, which is what makes the product stage of the tree exact and
 * leaves the additions as the only thing that rounds.
 * =================================================================== */
static int dot_mantissa_bits(const fmt_info *fi)
{
    int mw = fi->prec / 2;
    return mw > 11 ? 11 : mw;
}

/* The rung's exponent SPREAD, which is what actually sets the
 * condition number of a summation: the products run from 2^top down to
 * 2^(top - spread), so the exact sum is a multiple of a quantum
 * 2^(top - 2*mw - spread) with a magnitude near 2^(top + log2 len).
 * It therefore needs about 2*mw + 5 + spread significand bits, and a
 * format holds the whole cancellation exactly when p exceeds that -
 * which is the entire fp64-versus-fp256 story in one line. */
static int dot_spread(const options *O, size_t rung)
{
    if (O->cond_levels <= 1)
        return O->cond_max;
    return (int)(rung * (size_t)O->cond_max / (size_t)(O->cond_levels - 1));
}

/* case 0 is the exact one, 1..cond_levels the ladder, the rest rows of
 * the matrix. Returns the vector length. */
static size_t dot_case(runstate *R, size_t which, const char **name_out,
                       int *spread_out)
{
    options *O = R->opt;
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, m = O->dot_m, len, i, j;
    int mw = dot_mantissa_bits(fi);
    int spread;
    rng g;
    static char name[48];

    if (which == 0) {
        /* Exact by construction: |v| and |w| below 2^(mw/2) and 4m of
         * them, so every product and every partial sum of the tree
         * stays well inside p bits. Both bounds are then the value and
         * the flag word stays clean, which is the certificate. */
        int sm = mw / 2;
        len = 4 * m;
        rng_seed(&g, "cft-enclose dot exact v1", 0);
        for (i = 0; i < len; i++) {
            int64_t a = (int64_t)(rng_u64(&g) % (uint64_t)(1 << sm)) + 1;
            int64_t b = (int64_t)(rng_u64(&g) % (uint64_t)(1 << sm)) + 1;
            if (rng_u64(&g) & 1) a = -a;
            if (rng_u64(&g) & 1) b = -b;
            val_from_i64(fi, a, R->dx + i * esz);
            val_from_i64(fi, b, R->dy + i * esz);
        }
        snprintf(name, sizeof name, "exact");
        *name_out = name;
        *spread_out = -1;
        return len;
    }

    if (which <= (size_t)O->cond_levels) {
        spread = dot_spread(O, which - 1);
        snprintf(name, sizeof name, "cancel-spread%d", spread);
        rng_seed(&g, "cft-enclose dot cancel v1", (uint64_t)which);
    } else {
        spread = O->cond_max;
        snprintf(name, sizeof name, "matvec-row%" PRIu64,
                 (uint64_t)(which - 1 - (size_t)O->cond_levels));
        rng_seed(&g, "cft-enclose dot matvec v1", (uint64_t)which);
    }
    *name_out = name;
    *spread_out = spread;

    /* x = [v, v, 1], y = [w, -w, 1] under one shared permutation. The
     * mirrored block cancels EXACTLY as a rational, so the dot product
     * is exactly 1 however violent the cancellation - which is what
     * makes the oracle able to state the answer rather than estimate
     * it. The permutation matters: without it the mirror image of a
     * subtree is another subtree and the contractual tree cancels the
     * two against each other at one node, which is exact and tests
     * nothing. */
    len = 2 * m + 1;
    for (i = 0; i < m; i++) {
        int64_t a = (int64_t)(rng_u64(&g) % (uint64_t)((uint64_t)1 << mw)) |
                    (int64_t)((uint64_t)1 << (mw - 1)) | 1;
        int64_t b = (int64_t)(rng_u64(&g) % (uint64_t)((uint64_t)1 << mw)) |
                    (int64_t)((uint64_t)1 << (mw - 1)) | 1;
        /* the two ends of the spread are pinned rather than drawn, so
         * the condition number is the rung's and not the dice's */
        int64_t e = (i == 0) ? 0
                  : (i == 1) ? spread
                  : (int64_t)(rng_u64(&g) % (uint64_t)(spread + 1));
        uint8_t bv[MAX_ESZ];
        val_from_i64(fi, a, R->dx + i * esz);
        val_from_i64(fi, b, bv);
        val_scale(fi, bv, (int64_t)O->dot_top - 2 * (int64_t)mw - e,
                  R->dy + i * esz);
        memcpy(R->dx + (m + i) * esz, R->dx + i * esz, esz);
        run1(CFT_NEG, fi->fmt, CFT_RNE, R->dy + i * esz, NULL, NULL,
             R->dy + (m + i) * esz, NULL);
    }
    val_from_i64(fi, 1, R->dx + 2 * m * esz);
    val_from_i64(fi, 1, R->dy + 2 * m * esz);

    for (i = len; i > 1; i--) {
        uint8_t tmp[MAX_ESZ];
        j = (size_t)(rng_u64(&g) % (uint64_t)i);
        memcpy(tmp, R->dx + (i - 1) * esz, esz);
        memcpy(R->dx + (i - 1) * esz, R->dx + j * esz, esz);
        memcpy(R->dx + j * esz, tmp, esz);
        memcpy(tmp, R->dy + (i - 1) * esz, esz);
        memcpy(R->dy + (i - 1) * esz, R->dy + j * esz, esz);
        memcpy(R->dy + j * esz, tmp, esz);
    }
    return len;
}

/* Whether this format can hold the ladder's data exactly, asked before
 * any work rather than discovered inside it. binary32's exponent range
 * is the thing that fails: a spread wide enough to defeat binary256's
 * 237-bit significand puts the smallest element below binary32's
 * smallest normal, so the two requirements cannot be met at once. That
 * is a fact about the formats and is reported as one. */
static int dot_representable(runstate *R)
{
    const fmt_info *fi = R->fi;
    int mw = dot_mantissa_bits(fi);
    int64_t topx = (int64_t)R->opt->dot_top - (int64_t)mw;
    int64_t lowx = (int64_t)R->opt->dot_top - 2 * (int64_t)mw -
                   (int64_t)R->opt->cond_max;
    uint8_t v[MAX_ESZ], t[MAX_ESZ];
    val_from_i64(fi, 1, v);
    if (!val_scale_ok(fi, v, topx + (int64_t)mw, t))
        return 0;                              /* the largest product */
    return val_scale_ok(fi, v, lowx, t);       /* the smallest element */
}

static void dot_reduce(runstate *R, cft_round rnd, size_t len, void *d,
                       uint32_t *fl)
{
    uint32_t r = 0;
    cft_status st = cft_reduce(DEV, CFT_DOT, R->fi->fmt, rnd, R->dx, R->dy,
                               d, len, &r, NULL);
    if (st != CFT_OK)
        die_st("cft_reduce", st);
    *fl |= r;
    R->calls++;
    R->elem_ops += len;
}

static void dot_batch(runstate *R, size_t base, size_t n)
{
    const fmt_info *fi = R->fi;
    size_t i, len;
    for (i = 0; i < n; i++) {
        uint8_t lo[MAX_ESZ], hi[MAX_ESZ];
        uint32_t flo = 0, fhi = 0;
        const char *name = "";
        int spread = 0;
        len = dot_case(R, base + i, &name, &spread);
        dot_reduce(R, CFT_RDN, len, lo, &flo);
        dot_reduce(R, CFT_RUP, len, hi, &fhi);
        flags_expect(flo | fhi, "a dot product");
        R->flags_seen |= flo | fhi;

        /* The paired-call certificate: no rounding on either side means
         * both trees evaluated the exact rational, so the bounds must
         * coincide. */
        if (!((flo | fhi) & CFT_FLAG_INEXACT) &&
            memcmp(lo, hi, fi->esz) != 0)
            die("a dot product raised no inexact and still returned two "
                "different bounds");
        if (!(flo & CFT_FLAG_INEXACT))
            R->st.lo_side_exact++;
        if (!(fhi & CFT_FLAG_INEXACT))
            R->st.hi_side_exact++;

        emit(R, KER_DOT, (uint64_t)(base + i), lo, hi, name);
    }
    R->cursor += n;
    R->passes++;
}

static void dot_dump(runstate *R, const char *path)
{
    const fmt_info *fi = R->fi;
    FILE *f = fopen(path, "wb");
    size_t which, esz = fi->esz, i;
    if (!f)
        die("cannot write the vector dump");
    fprintf(f, "# cft-enclose vectors, format %s\n",
            cft_format_name(fi->fmt));
    for (which = 0; which < dot_items(R->opt); which++) {
        const char *name = "";
        int spread = 0;
        size_t len = dot_case(R, which, &name, &spread);
        fprintf(f, "vec %" PRIu64 " %s %" PRIu64 "\n", (uint64_t)which,
                name, (uint64_t)len);
        for (i = 0; i < len; i++) {
            char hx[HEXMAX], hy[HEXMAX];
            val_to_hex(fi, R->dx + i * esz, hx, sizeof hx);
            val_to_hex(fi, R->dy + i * esz, hy, sizeof hy);
            fprintf(f, "xy %s %s\n", hx, hy);
        }
    }
    if (fclose(f) != 0)
        die("the vector dump did not write cleanly");
}

/* ===================================================================
 * Kernel 3: interval Horner
 * =================================================================== */
static void horner_point(runstate *R, size_t j, void *out)
{
    const fmt_info *fi = R->fi;
    size_t p = R->opt->points;
    int64_t sh = 0;
    uint8_t v[MAX_ESZ], t[MAX_ESZ];
    uint32_t fl = 0;
    while ((size_t)1 << sh != p)
        sh++;
    /* x = -1 + 2j/points, every one of them a dyadic rational the
     * format holds exactly - and computed, not parsed. */
    val_from_i64(fi, (int64_t)j, v);
    if (j == 0)
        memcpy(t, v, fi->esz);
    else
        val_scale(fi, v, 1 - sh, t);
    run1(CFT_SUB, fi->fmt, CFT_RNE, t, NULL, R->one, out, &fl);
    if (fl)
        die("a Horner evaluation point was not exact");
    R->elem_ops += 1;
}

/* c_0 = 1 exactly; c_k = c_{k-1}/k, one RDN division for the lower end
 * and one RUP for the upper, so 1/k! is inside [clo_k, chi_k] by
 * induction. They are the interval coefficients, and their
 * containment is checked independently by the oracle. */
static void horner_coeffs(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz;
    int k, d = R->opt->degree;
    uint32_t f = 0;

    val_from_i64(fi, 1, R->clo);
    val_from_i64(fi, 1, R->chi);
    for (k = 1; k <= d; k++) {
        uint8_t kk[MAX_ESZ];
        val_from_i64(fi, k, kk);
        divN(R, CFT_RDN, R->clo + (size_t)(k - 1) * esz, kk,
             R->clo + (size_t)k * esz, 1, &f);
        divN(R, CFT_RUP, R->chi + (size_t)(k - 1) * esz, kk,
             R->chi + (size_t)k * esz, 1, &f);
    }
    flags_expect(f, "a coefficient enclosure");
    R->flags_seen |= f;
}

static void horner_programs(runstate *R)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, ch;
    int d = R->opt->degree;
    uint8_t *clo = (uint8_t *)xcalloc(CHUNK, esz);
    uint8_t *chi = (uint8_t *)xcalloc(CHUNK, esz);

    R->prog = (cft_program **)xcalloc(R->chunks, sizeof(cft_program *));
    for (ch = 0; ch < R->chunks; ch++) {
        size_t bytes = 0, i;
        uint32_t insns = 0;
        uint8_t *img;
        cft_status st;
        for (i = 0; i < CHUNK; i++) {
            size_t k = (size_t)d - ch * CHUNK - i;
            memcpy(clo + i * esz, R->clo + k * esz, esz);
            memcpy(chi + i * esz, R->chi + k * esz, esz);
        }
        img = build_chunk(fi, clo, chi, CHUNK, &bytes, &insns);
        st = cft_program_load(DEV, img, bytes, &R->prog[ch]);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load", st);
    }
    free(clo);
    free(chi);
}

static void horner_batch(runstate *R, size_t base, size_t n)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    size_t esz = fi->esz, i, ch;
    uint32_t f = 0;

    for (i = 0; i < n; i++)
        horner_point(R, base + i, R->hx + i * esz);
    memset(R->hlo, 0, n * esz);
    memset(R->hhi, 0, n * esz);

    if (O->use_program) {
        for (ch = 0; ch < R->chunks; ch++) {
            uint32_t bus = 0, fr = 0;
            cft_status st = cft_program_run(R->prog[ch], R->hx,
                                            ch ? R->hlo : NULL,
                                            ch ? R->hhi : NULL,
                                            R->dep, R->counts, n, &fr, &bus);
            if (st != CFT_OK)
                die_st("cft_program_run", st);
            if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
                die("the deposit buffer overflowed - the program is wrong");
            for (i = 0; i < n; i++) {
                if (R->counts[i] != DEPOSITS)
                    die("a lane deposited the wrong number of values");
                memcpy(R->hlo + i * esz,
                       R->dep + (i * DEPOSITS + 0) * esz, esz);
                memcpy(R->hhi + i * esz,
                       R->dep + (i * DEPOSITS + 1) * esz, esz);
            }
            f |= fr;
            R->calls++;
            R->elem_ops += n * (size_t)(1 + 4 * CHUNK);
        }
    } else {
        int k;
        /* a batch-wide zero, not the scalar one: cft_run reads n
         * elements from every operand it is given */
        runN(R, CFT_CMPLE, CFT_RNE, R->hzero, R->hx, NULL, R->hnn, n,
             &f);
        for (k = O->degree; k >= 0; k--) {
            bcast(fi, R->hbclo, R->clo + (size_t)k * esz, n);
            bcast(fi, R->hbchi, R->chi + (size_t)k * esz, n);
            runN(R, CFT_SELECT, CFT_RNE, R->hlo, R->hhi, R->hnn, R->hma, n,
                 &f);
            runN(R, CFT_SELECT, CFT_RNE, R->hhi, R->hlo, R->hnn, R->hmb, n,
                 &f);
            runN(R, CFT_FMA, CFT_RDN, R->hx, R->hma, R->hbclo, R->hlo, n,
                 &f);
            runN(R, CFT_FMA, CFT_RUP, R->hx, R->hmb, R->hbchi, R->hhi, n,
                 &f);
        }
    }

    flags_expect(f, "a Horner step");
    R->flags_seen |= f;

    /* The paired-call certificate again, over the whole chunked run:
     * inexact clear anywhere on this batch means nothing rounded on
     * either side, so no element can have a nonzero width. */
    if (!(f & CFT_FLAG_INEXACT))
        for (i = 0; i < n; i++)
            if (memcmp(R->hlo + i * esz, R->hhi + i * esz, esz) != 0)
                die("a Horner batch raised no inexact and still produced a "
                    "nonzero width");

    for (i = 0; i < n; i++) {
        char label[DECMAX];
        val_to_dec(fi, R->hx + i * esz, CFT_RNE, 12, label, sizeof label);
        emit(R, KER_HORNER, (uint64_t)(base + i), R->hlo + i * esz,
             R->hhi + i * esz, label);
    }
    R->cursor += n;
    R->passes++;
}

static void horner_dump(runstate *R, const char *path)
{
    const fmt_info *fi = R->fi;
    FILE *f = fopen(path, "wb");
    int k;
    if (!f)
        die("cannot write the coefficient dump");
    fprintf(f, "# cft-enclose coefficients, format %s, degree %d\n",
            cft_format_name(fi->fmt), R->opt->degree);
    for (k = 0; k <= R->opt->degree; k++) {
        char a[HEXMAX], b[HEXMAX];
        val_to_hex(fi, R->clo + (size_t)k * fi->esz, a, sizeof a);
        val_to_hex(fi, R->chi + (size_t)k * fi->esz, b, sizeof b);
        fprintf(f, "coef %d %s %s\n", k, a, b);
    }
    if (fclose(f) != 0)
        die("the coefficient dump did not write cleanly");
}

/* ===================================================================
 * Checkpoint
 *
 * A line-oriented ASCII file, written to <path>.tmp and then renamed
 * over the target, so a reader never sees a half-written one. Every
 * number that describes a RESULT is here; nothing that describes the
 * MACHINE is - no batch size, no engine, no timing - which is what
 * lets two runs with different batch sizes and different engines end
 * on byte-identical files.
 * =================================================================== */
#define CKPT_MAGIC "cft-enclose-checkpoint 1"

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
    char tmp[1024], chain[65], h[HEXMAX];
    FILE *f;
    size_t i, esz = fi->esz;
    int k;

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
    fprintf(f, "kernels %d%d%d\n", O->want[0], O->want[1], O->want[2]);
    fprintf(f, "points %" PRIu64 "\n", (uint64_t)O->points);
    fprintf(f, "degree %d\n", O->degree);
    fprintf(f, "dotm %" PRIu64 "\n", (uint64_t)O->dot_m);
    fprintf(f, "cond %d %d %d\n", O->dot_top, O->cond_max,
            O->cond_levels);
    fprintf(f, "rows %" PRIu64 "\n", (uint64_t)O->rows);
    fprintf(f, "terms %d\n", R->terms);
    fprintf(f, "cursor %" PRIu64 "\n", (uint64_t)R->cursor);
    fprintf(f, "items %" PRIu64 "\n", (uint64_t)R->total);
    for (k = 0; k < N_KERNELS; k++) {
        fprintf(f, "kernel %s %" PRIu64 " %" PRIu64 " ", KERNEL_NAME[k],
                R->st.n[k], R->st.nexact[k]);
        if (R->st.have_max[k]) {
            val_to_hex(fi, R->st.maxw[k], h, sizeof h);
            fprintf(f, "%s %" PRIu64 "\n", h, R->st.maxw_idx[k]);
        } else {
            fprintf(f, "- -\n");
        }
    }
    fprintf(f, "dotsides %" PRIu64 " %" PRIu64 " %" PRIu64 "\n",
            R->st.lo_side_exact, R->st.hi_side_exact, R->st.straddle);
    if (R->st.have_e)
        fprintf(f, "e %s %s\n", R->st.e_lo, R->st.e_hi);
    else
        fprintf(f, "e - -\n");
    fprintf(f, "chain %s\n", chain);
    fprintf(f, "inflight %" PRIu64 " %d\n", (uint64_t)R->inflight, R->sterm);
    for (i = 0; i < R->inflight; i++) {
        char a[HEXMAX], b[HEXMAX], c[HEXMAX], d[HEXMAX];
        val_to_hex(fi, R->stlo + i * esz, a, sizeof a);
        val_to_hex(fi, R->sthi + i * esz, b, sizeof b);
        val_to_hex(fi, R->sslo + i * esz, c, sizeof c);
        val_to_hex(fi, R->sshi + i * esz, d, sizeof d);
        fprintf(f, "run %s %s %s %s\n", a, b, c, d);
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
    char line[8 * HEXMAX];
    size_t i, esz = fi->esz;

    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, sizeof line, f) ||
        strcmp(trim_nl(line), CKPT_MAGIC) != 0)
        die("that file is not a cft-enclose checkpoint of this version");

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
        } else if (!strcmp(key, "kernels")) {
            char want[8];
            snprintf(want, sizeof want, "%d%d%d", O->want[0], O->want[1],
                     O->want[2]);
            if (strcmp(rest, want) != 0)
                die("the checkpoint was written for a different kernel set");
        } else if (!strcmp(key, "points")) {
            if ((uint64_t)O->points != strtoull(rest, NULL, 10))
                die("the checkpoint was written with a different --points");
        } else if (!strcmp(key, "degree")) {
            if (O->degree != (int)strtol(rest, NULL, 10))
                die("the checkpoint was written with a different --degree");
        } else if (!strcmp(key, "cursor")) {
            R->cursor = (size_t)strtoull(rest, NULL, 10);
        } else if (!strcmp(key, "kernel")) {
            char nm[32], hw[HEXMAX], wi[64];
            uint64_t nn = 0, ne = 0;
            int k;
            if (sscanf(rest, "%31s %" SCNu64 " %" SCNu64 " %159s %63s",
                       nm, &nn, &ne, hw, wi) != 5)
                die("bad checkpoint kernel line");
            for (k = 0; k < N_KERNELS; k++)
                if (!strcmp(nm, KERNEL_NAME[k])) {
                    R->st.n[k] = nn;
                    R->st.nexact[k] = ne;
                    if (strcmp(hw, "-") != 0) {
                        if (!val_from_hex(fi, hw, R->st.maxw[k]))
                            die("bad checkpoint width");
                        R->st.have_max[k] = 1;
                        R->st.maxw_idx[k] = strtoull(wi, NULL, 10);
                    }
                }
        } else if (!strcmp(key, "dotsides")) {
            if (sscanf(rest, "%" SCNu64 " %" SCNu64 " %" SCNu64,
                       &R->st.lo_side_exact, &R->st.hi_side_exact,
                       &R->st.straddle) != 3)
                die("bad checkpoint dotsides line");
        } else if (!strcmp(key, "e")) {
            char a[HEXMAX], b[HEXMAX];
            if (sscanf(rest, "%159s %159s", a, b) == 2 &&
                strcmp(a, "-") != 0) {
                snprintf(R->st.e_lo, HEXMAX, "%s", a);
                snprintf(R->st.e_hi, HEXMAX, "%s", b);
                R->st.have_e = 1;
            }
        } else if (!strcmp(key, "chain")) {
            if (!unhex32(rest, R->st.chain))
                die("bad checkpoint chain");
        } else if (!strcmp(key, "inflight")) {
            uint64_t nfl = 0;
            int term = 0;
            if (sscanf(rest, "%" SCNu64 " %d", &nfl, &term) != 2)
                die("bad checkpoint inflight line");
            if (nfl > O->batch)
                die("the checkpoint has more in flight than --batch");
            for (i = 0; i < (size_t)nfl; i++) {
                char a[HEXMAX], b[HEXMAX], c[HEXMAX], d[HEXMAX];
                if (!fgets(line, sizeof line, f))
                    die("the checkpoint ended inside its in-flight list");
                trim_nl(line);
                if (sscanf(line, "run %159s %159s %159s %159s", a, b, c,
                           d) != 4)
                    die("bad checkpoint in-flight line");
                if (!val_from_hex(fi, a, R->stlo + i * esz) ||
                    !val_from_hex(fi, b, R->sthi + i * esz) ||
                    !val_from_hex(fi, c, R->sslo + i * esz) ||
                    !val_from_hex(fi, d, R->sshi + i * esz))
                    die("bad checkpoint in-flight value");
                /* the point itself is a function of the item index, so
                 * it is recomputed rather than stored */
                series_point(R, R->cursor + i, R->sx + i * esz);
            }
            R->inflight = (size_t)nfl;
            R->inflight_kernel = KER_SERIES;
            R->sterm = term;
        } else if (!strcmp(key, "end")) {
            break;
        }
    }
    fclose(f);
}

/* ===================================================================
 * Reporting
 * =================================================================== */
static void report(runstate *R, double elapsed, const char *backend)
{
    const fmt_info *fi = R->fi;
    options *O = R->opt;
    stats *S = &R->st;
    char chain[65];
    uint64_t done = S->n[0] + S->n[1] + S->n[2];
    double eps = elapsed > 0 ? (double)done / elapsed : 0.0;
    double ops = elapsed > 0 ? (double)R->elem_ops / elapsed : 0.0;
    int k;

    hex32(S->chain, chain);

    if (O->summary_csv) {
        printf("backend,format,engine,batch,items,exact,seconds,"
               "enclosures_per_s,element_ops_per_s,element_ops,calls,"
               "flags,chain\n");
        printf("%s,%s,%s,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%.6f,%.1f,"
               "%.1f,%" PRIu64 ",%" PRIu64 ",0x%02x,%s\n",
               backend, cft_format_name(fi->fmt),
               O->use_program ? "program" : "loop", (uint64_t)O->batch,
               done, S->nexact[0] + S->nexact[1] + S->nexact[2], elapsed,
               eps, ops, R->elem_ops, R->calls, (unsigned)R->flags_seen,
               chain);
        return;
    }
    if (O->quiet)
        return;

    printf("\n");
    printf("  backend       %s\n", backend);
    printf("  format        %s, p = %d\n", cft_format_name(fi->fmt),
           fi->prec);
    printf("  engine        %s, batch %" PRIu64 "\n",
           O->use_program ? "sequencer program (Horner) + host calls"
                          : "host cft_run loop throughout",
           (uint64_t)O->batch);
    printf("  enclosures    %" PRIu64 " of %" PRIu64 " items\n", done,
           (uint64_t)R->total);
    for (k = 0; k < N_KERNELS; k++) {
        char dw[DECMAX];
        if (!S->n[k])
            continue;
        printf("  %-13s %" PRIu64 " enclosures, %" PRIu64 " exact "
               "(both bounds ARE the value)\n",
               KERNEL_NAME[k], S->n[k], S->nexact[k]);
        if (S->have_max[k]) {
            val_to_dec(fi, S->maxw[k], CFT_RUP, 6, dw, sizeof dw);
            printf("                widest %s at item %" PRIu64 "\n", dw,
                   S->maxw_idx[k]);
        }
        if (k == KER_DOT) {
            printf("                %" PRIu64 " lower and %" PRIu64
                   " upper bounds certified exact by the flag word\n",
                   S->lo_side_exact, S->hi_side_exact);
            printf("                %" PRIu64
                   " enclosures straddle zero\n", S->straddle);
        }
    }
    if (S->have_e) {
        printf("  e in          [%s,\n                 %s]\n", S->e_lo,
               S->e_hi);
    }
    printf("  series terms  %d (tail below 2^-%d, derived from p)\n",
           R->terms, fi->prec + 1);
    if (S->n[KER_HORNER])
        printf("  horner        degree %d, %" PRIu64 " chunk programs of %d "
               "steps, 16 constants each\n", O->degree,
               (uint64_t)R->chunks, CHUNK);
    printf("  library calls %" PRIu64 "\n", R->calls);
    printf("  element ops   %" PRIu64 "\n", R->elem_ops);
    printf("  flags seen    0x%02x%s\n", (unsigned)R->flags_seen,
           R->flags_trusted ? "" : "  (this backend cannot read flags)");
    printf("  status word   0x%02x%s\n", (unsigned)cft_save_all_flags(DEV),
           cft_save_all_flags(DEV) == R->flags_seen
               ? " (agrees with the union above)"
               : "  DISAGREES WITH THE UNION ABOVE");
    printf("  time          %.3f s\n", elapsed);
    printf("  throughput    %.1f enclosures/s, %.0f element ops/s\n", eps,
           ops);
    printf("  chain         %s\n", chain);
    printf("\n");
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-enclose - rigorous enclosures from the directed roundings\n"
"\n"
"  --format fp32|fp64|fp128|fp256   default fp256\n"
"  --engine program|loop    the Horner kernel's engine (default program)\n"
"  --kernels a,b,c          any of series,dot,horner (default all)\n"
"  --points N               points per point kernel, a power of two\n"
"  --degree D               Horner degree; (D+1) must be a multiple of 8\n"
"  --dot-len M              half-length of the mirrored block (default 32)\n"
"  --dot-top E              exponent of the largest product (default 60)\n"
"  --cond-max C             widest exponent spread (default 225)\n"
"  --cond-levels L          rungs of the condition ladder (default 6)\n"
"  --rows N                 matrix-vector rows (default 8)\n"
"  --batch N                items in flight (default 256)\n"
"  --checkpoint PATH        write a resumable checkpoint\n"
"  --checkpoint-interval S  seconds between checkpoints (default 10)\n"
"  --resume                 continue from --checkpoint\n"
"  --stop-after-batches N   stop cleanly once N batches are complete\n"
"  --stop-after-passes N    stop cleanly after N engine passes, which for\n"
"                           the series kernel lands MID-item\n"
"  --time S                 stop cleanly after S seconds\n"
"  --records PATH           the record lines the chain is taken over\n"
"  --csv PATH               a CSV of every bound and width ('-' = stdout)\n"
"  --dump-vectors PATH      the dot kernel's vectors, exactly, for an oracle\n"
"  --dump-coeffs PATH       the Horner kernel's interval coefficients\n"
"  --summary-csv            one machine-readable summary row\n"
"  --artifact PATH          an .xclbin; omit for the software backend\n"
"  --quiet                  no report\n"
"\n"
"Every interval it prints contains the true value, and docs/ENCLOSE.md\n"
"is the argument.\n");
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        die("that option needs a value");
    return argv[++(*i)];
}

static void parse_kernels(options *O, const char *s)
{
    char buf[128], *tok, *save;
    int k;
    for (k = 0; k < N_KERNELS; k++)
        O->want[k] = 0;
    snprintf(buf, sizeof buf, "%s", s);
    tok = buf;
    while (tok && *tok) {
        int found = 0;
        save = strchr(tok, ',');
        if (save) { *save = 0; save++; }
        for (k = 0; k < N_KERNELS; k++)
            if (!strcmp(tok, KERNEL_NAME[k])) { O->want[k] = 1; found = 1; }
        if (!found)
            die("--kernels takes series, dot and horner");
        tok = save;
    }
    if (!O->want[0] && !O->want[1] && !O->want[2])
        die("--kernels selected nothing");
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
    int i, k, stopping = 0;
    size_t esz;

    memset(&O, 0, sizeof O);
    O.fmt = CFT_FP256;
    O.use_program = 1;
    O.want[0] = O.want[1] = O.want[2] = 1;
    O.points = 1024;
    O.degree = 23;
    O.dot_m = 32;
    O.dot_top = 60;
    O.cond_max = 225;
    O.cond_levels = 6;
    O.rows = 8;
    O.batch = 256;
    O.ckpt_interval = 10.0;
    O.stop_after_batches = -1;
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
        else if (!strcmp(a, "--kernels")) parse_kernels(&O, need(argc, argv, &i));
        else if (!strcmp(a, "--points"))
            O.points = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--degree"))
            O.degree = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--dot-len"))
            O.dot_m = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--dot-top"))
            O.dot_top = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--cond-max"))
            O.cond_max = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--cond-levels"))
            O.cond_levels = (int)strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--rows"))
            O.rows = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--batch")) {
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
            if (!O.batch) die("--batch must be positive");
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
        else if (!strcmp(a, "--records")) O.records_path = need(argc, argv, &i);
        else if (!strcmp(a, "--csv")) O.csv_path = need(argc, argv, &i);
        else if (!strcmp(a, "--dump-vectors")) O.vec_path = need(argc, argv, &i);
        else if (!strcmp(a, "--dump-coeffs")) O.coef_path = need(argc, argv, &i);
        else if (!strcmp(a, "--summary-csv")) O.summary_csv = 1;
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-enclose: unknown option %s\n", a);
            return 2;
        }
    }

    if (!O.points || (O.points & (O.points - 1)))
        die("--points must be a power of two, so that every evaluation "
            "point is a dyadic rational the format holds exactly");
    if (O.degree < 0 || ((O.degree + 1) % CHUNK) != 0)
        die("--degree must make (degree + 1) a multiple of 8: a sequencer "
            "instruction names a constant in a four-bit field, so a "
            "program addresses sixteen constants and no more, which is "
            "eight interval coefficients");
    if (O.cond_levels < 1)
        die("--cond-levels must be at least 1");
    if (!O.dot_m)
        die("--dot-len must be positive");

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
    if (2 * dot_mantissa_bits(&fi) > fi.prec)
        die("this format is too narrow for an exact product stage");

    memset(&R, 0, sizeof R);
    R.fi = &fi;
    R.opt = &O;
    R.flags_trusted = caps.flags_readable != 0;
    esz = fi.esz;
    plan_items(&R);

    R.zero = (uint8_t *)xcalloc(1, esz);
    R.one  = (uint8_t *)xcalloc(1, esz);
    val_from_i64(&fi, 0, R.zero);
    val_from_i64(&fi, 1, R.one);

    R.t1 = (uint8_t *)xcalloc(O.batch, esz);
    R.t2 = (uint8_t *)xcalloc(O.batch, esz);
    R.kv = (uint8_t *)xcalloc(O.batch, esz);
    R.sx   = (uint8_t *)xcalloc(O.batch, esz);
    R.stlo = (uint8_t *)xcalloc(O.batch, esz);
    R.sthi = (uint8_t *)xcalloc(O.batch, esz);
    R.sslo = (uint8_t *)xcalloc(O.batch, esz);
    R.sshi = (uint8_t *)xcalloc(O.batch, esz);
    R.hx  = (uint8_t *)xcalloc(O.batch, esz);
    R.hlo = (uint8_t *)xcalloc(O.batch, esz);
    R.hhi = (uint8_t *)xcalloc(O.batch, esz);
    R.hnn = (uint8_t *)xcalloc(O.batch, esz);
    R.hma = (uint8_t *)xcalloc(O.batch, esz);
    R.hmb = (uint8_t *)xcalloc(O.batch, esz);
    R.hbclo = (uint8_t *)xcalloc(O.batch, esz);
    R.hbchi = (uint8_t *)xcalloc(O.batch, esz);
    R.hzero = (uint8_t *)xcalloc(O.batch, esz);
    bcast(&fi, R.hzero, R.zero, O.batch);
    R.dep = (uint8_t *)xcalloc(O.batch * DEPOSITS, esz);
    R.counts = (uint32_t *)xcalloc(O.batch, sizeof(uint32_t));
    R.dot_cap = 4 * O.dot_m + 2;
    R.dx = (uint8_t *)xcalloc(R.dot_cap, esz);
    R.dy = (uint8_t *)xcalloc(R.dot_cap, esz);
    R.clo = (uint8_t *)xcalloc((size_t)O.degree + 1, esz);
    R.chi = (uint8_t *)xcalloc((size_t)O.degree + 1, esz);

    if (O.want[KER_DOT] && !dot_representable(&R))
        die("this format cannot hold the dot kernel's condition ladder "
            "exactly: the spread that defeats a 237-bit significand puts "
            "the smallest element below this format's smallest normal, or "
            "the largest product above its largest finite. Lower "
            "--cond-max and --dot-top, or run --kernels series,horner");

    R.terms = series_terms(&R);
    horner_coeffs(&R);
    R.chunks = ((size_t)O.degree + 1) / CHUNK;
    if (O.want[KER_HORNER] && O.use_program)
        horner_programs(&R);

    /* Setup deliberately raised inexact - measuring p does, and so do
     * the coefficient enclosures. 7.1 says a status flag is lowered
     * only at the user's request; this is that request, and from here
     * the word holds what the RUN raised, which the report cross-
     * checks against the union of the calls' own flag words. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);
    R.flags_seen = 0;
    R.elem_ops = 0;
    R.calls = 0;

    if (O.vec_path && O.want[KER_DOT])
        dot_dump(&R, O.vec_path);
    if (O.coef_path && O.want[KER_HORNER])
        horner_dump(&R, O.coef_path);

    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R);
    }
    if (O.records_path) {
        R.recf = fopen(O.records_path, "wb");
        if (!R.recf)
            die("cannot write the records file");
    }
    if (O.csv_path) {
        R.csvf = strcmp(O.csv_path, "-") ? fopen(O.csv_path, "wb") : stdout;
        if (!R.csvf)
            die("cannot write the CSV file");
        fprintf(R.csvf, "kernel,item,point,lo_hex,hi_hex,lo_dec,hi_dec,"
                        "width_hex,width_dec,exact\n");
    }

    if (!O.quiet && !O.summary_csv)
        printf("cft-enclose: %s backend, %s, p = %d, %s engine, %" PRIu64
               " items\n", caps.backend, cft_format_name(fi.fmt), fi.prec,
               O.use_program ? "sequencer-program" : "host-loop",
               (uint64_t)R.total);

    t0 = now_s();
    tckpt = t0;
    while (!stopping && R.cursor < R.total) {
        size_t local = 0, n, room;
        int kern = kernel_of(&R, R.cursor, &local);

        if (!R.inflight) {
            room = R.items[kern] - local;
            n = O.batch < room ? O.batch : room;
            if (kern == KER_SERIES)
                series_begin(&R, R.cursor, n);
            else {
                R.inflight = n;
                R.inflight_kernel = kern;
            }
        }
        n = R.inflight;

        if (kern == KER_SERIES) {
            while (R.sterm < R.terms) {
                series_pass(&R);
                if (O.ckpt && now_s() - tckpt >= O.ckpt_interval) {
                    ckpt_write(&R);
                    tckpt = now_s();
                }
                if (O.stop_after_passes >= 0 &&
                    R.passes >= O.stop_after_passes) {
                    stopping = 1;
                    break;
                }
            }
            if (stopping)
                break;
            series_finish(&R);
        } else if (kern == KER_DOT) {
            dot_batch(&R, local, n);
            R.inflight = 0;
        } else {
            horner_batch(&R, local, n);
            R.inflight = 0;
        }

        batches++;
        if (O.ckpt) {
            ckpt_write(&R);
            tckpt = now_s();
        }
        if (O.stop_after_batches >= 0 && batches >= O.stop_after_batches)
            break;
        if (O.stop_after_passes >= 0 && R.passes >= O.stop_after_passes)
            break;
        if (O.time_limit > 0 && now_s() - t0 >= O.time_limit)
            break;
    }
    elapsed = now_s() - t0;
    if (O.ckpt)
        ckpt_write(&R);
    if (R.recf)
        fclose(R.recf);
    if (R.csvf && R.csvf != stdout)
        fclose(R.csvf);

    report(&R, elapsed, caps.backend);

    for (k = 0; (size_t)k < R.chunks && R.prog; k++)
        cft_program_free(R.prog[k]);
    free(R.prog);
    free(R.zero); free(R.one); free(R.t1); free(R.t2); free(R.kv);
    free(R.sx); free(R.stlo); free(R.sthi); free(R.sslo); free(R.sshi);
    free(R.hx); free(R.hlo); free(R.hhi); free(R.hnn); free(R.hma);
    free(R.hmb); free(R.hbclo); free(R.hbchi); free(R.hzero);
    free(R.dep); free(R.counts); free(R.dx); free(R.dy);
    free(R.clo); free(R.chi);
    cft_close(DEV);
    return 0;
}
