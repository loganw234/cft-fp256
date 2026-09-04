/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-orbits - symplectic few-body integration where the roundoff
 * floor and the method's truncation error are two SEPARATELY
 * MEASURABLE numbers.
 *
 *   ./cft-orbits --problem kepler --periods 64
 *   ./cft-orbits --problem outer --years 300 --format fp64
 *   ./cft-orbits --scheme yoshida4 --engine program --rsqrt newton
 *   ./cft-orbits --checkpoint run.ckpt --resume
 *
 * ---------------------------------------------------------------
 * Why this workload, on this contract
 * ---------------------------------------------------------------
 *
 * A symplectic integrator has two error sources and they behave
 * completely differently:
 *
 *   TRUNCATION is a property of the METHOD. Stormer-Verlet is second
 *   order, so its energy error is O(h^2) and - because the scheme is
 *   symplectic - it OSCILLATES with the orbit rather than growing. It
 *   is the same number in every arithmetic; it does not care how many
 *   bits you have.
 *
 *   ROUNDOFF is a property of the ARITHMETIC. It has no reason to
 *   cancel, so it accumulates: the energy random-walks and the phase
 *   drifts secularly. In binary64 that drift buries the method's own
 *   error after a few million steps, and from then on a long
 *   integration is measuring the floating-point format rather than
 *   the physics.
 *
 * Split them and each becomes a number:
 *
 *   truncation  =  ||(300-digit run of THIS scheme)  -  exact orbit||
 *   roundoff    =  ||(this format's run)  -  (300-digit run of the
 *                    same scheme from the same starting bits)||
 *
 * The second line is what this tool exists to measure, and it is why
 * binary256 is interesting here: at p = 237 the roundoff term is
 * 2^184 times smaller than binary64's, which puts it far below the
 * truncation error for any integration a person would actually run.
 * The method's error becomes the ONLY error, which is the condition
 * under which a step-size study means what it says.
 *
 * host/tests/orbits_check.py is the oracle: mpmath at 300 digits,
 * running the identical discrete scheme from the identical starting
 * ENCODINGS, plus - for the Kepler problem - the closed form through
 * Kepler's equation, so both terms above are measured rather than
 * assumed.
 *
 * ---------------------------------------------------------------
 * The two problems
 * ---------------------------------------------------------------
 *
 * --problem kepler   A test particle around a unit point mass at the
 *   origin, in the plane. mu = 1, semi-major axis a = 1, eccentricity
 *   e = 3/4 - a dyadic rational, so 1-e and 1+e are exact in every
 *   format and only the initial speed needs rounding. The initial
 *   condition is Hairer, Lubich and Wanner's (Geometric Numerical
 *   Integration, 2nd ed., section I.2.2), at apoapsis... at
 *   PERIapsis in their orientation:
 *
 *       q = (1-e, 0)        v = (0, sqrt((1+e)/(1-e)))
 *
 *   which gives H = -1/2 and L = sqrt(1-e^2) exactly, and period
 *   T = 2*pi. With e = 3/4 the speed is sqrt(7), the one initial
 *   value that is not exact - and it is delivered by cft_sqrt,
 *   correctly rounded.
 *
 *   The two zeros in that initial condition are not a convenience:
 *   they are what lets the sequencer run this problem at all. See
 *   "Where the step runs" below.
 *
 * --problem outer    The outer solar system: Sun (carrying the inner
 *   planets' mass), Jupiter, Saturn, Uranus, Neptune, in heliocentric
 *   coordinates, AU and days, from the same book's section I.2.3.
 *   The gravitational constant is NOT transcribed: it is k^2, the
 *   square of the IAU 1976 Gaussian gravitational constant
 *   k = 0.01720209895, computed here by one multiply. The positions,
 *   velocities and masses ARE transcribed - they are measurements,
 *   not derivable - so orbits_check.py validates them physically,
 *   recovering each planet's osculating semi-major axis and period
 *   from its own (r, v) and comparing against the published sidereal
 *   periods. A typo in the table moves a period by percent.
 *
 * ---------------------------------------------------------------
 * The scheme
 * ---------------------------------------------------------------
 *
 * --scheme leapfrog is Stormer-Verlet in its drift-kick-drift form,
 * one force evaluation per step:
 *
 *       q += (h/2) v ;  v += h a(q) ;  q += (h/2) v
 *
 * --scheme yoshida4 is Yoshida's fourth-order composition of it,
 *
 *       S4(h) = S2(w1 h) . S2(w0 h) . S2(w1 h)
 *       w1 = 1/(2 - 2^(1/3))      w0 = -2^(1/3)/(2 - 2^(1/3))
 *
 * with 2^(1/3) delivered by cft_rootn (754-2019 9.2's rootn,
 * correctly rounded) and w0, w1 composed from it by cft_div and
 * cft_run - derived, never typed. The adjacent drifts of two
 * neighbouring substeps are deliberately NOT merged: merging is a
 * different sequence of roundings, and the point of the exercise is
 * that the sequence of roundings is the contract.
 *
 * Two schemes over one arithmetic is the whole argument: the same
 * roundoff floor sits under two different truncation errors, so a
 * plot of one against the other separates them by construction.
 *
 * ---------------------------------------------------------------
 * 1/r^3, and where the rounding goes
 * ---------------------------------------------------------------
 *
 * Every kick needs G m / r^3 for every pair. r^2 comes from one
 * multiply and (ndim-1) fused multiply-adds; what happens next is
 * --rsqrt:
 *
 *   --rsqrt exact (the default)      s = cft_sqrt(r2)
 *                                    w = r2 * s          (= r^3)
 *                                    g = cft_div(K, w)
 *     Two CORRECTLY ROUNDED composed operations and one multiply:
 *     three roundings for the whole factor. cft_sqrt and cft_div are
 *     the library's own compositions of the tile's seed opcodes and
 *     its FMA (docs/HOSTAPI.md, python/cft_golden/sequences.py), so
 *     every rounding in them is the contract's.
 *
 *   --rsqrt newton                   y = CFT_RSQRT_SEED(r2)
 *                                    n x { y = y + (y/2)(1 - r2 y^2) }
 *                                    g = K * y^3
 *     A fixed, published Newton refinement from the tile's own seed
 *     opcode. NOT correctly rounded - it is a documented composition
 *     with a few ulps of its own - but every instruction in it is an
 *     ALU opcode, which is what makes it expressible on-chip. The
 *     iteration count is DERIVED from the format's p by iterating the
 *     seed's stated relative error bound 2^-8.5 through the Newton
 *     error recurrence e -> 1.5 e^2 until it passes 2^-(p+2); it is
 *     never tabulated.
 *
 * Measured on the software backend, --rsqrt exact costs about 1.4x
 * what --rsqrt newton costs at binary256 (docs/ORBITS.md). Correct
 * rounding is nearly free here, which is why it is the default.
 *
 * ---------------------------------------------------------------
 * Where the step runs, and the two things that stop it
 * ---------------------------------------------------------------
 *
 * --engine loop issues every operation as a cft_run / cft_sqrt /
 * cft_div pass over the ensemble. It runs both problems, both
 * schemes, both routes, and it is the reference the program engine
 * is held to.
 *
 * --engine program compiles the whole integration into ONE orbit
 * sequencer program (docs/SEQUENCER.md) per batch: the ensemble is
 * loaded into lane registers once, every step executes from the
 * instruction memory, and the sampled states come back through the
 * deposit stream. It is restricted to `--problem kepler --rsqrt
 * newton`, and BOTH restrictions are facts about the program model
 * rather than about this tool:
 *
 *   (1) THREE INPUT STREAMS. cft_program_run initialises r0, r1 and
 *       r2 from a, b and c; r3..r15 start at +0, normatively. A
 *       Hamiltonian system with d degrees of freedom has 2d state
 *       values per lane, and 2d > 3 for everything here: 4 for the
 *       planar Kepler problem, 30 for the outer solar system. So a
 *       program can be ENTERED only at a state with at most three
 *       non-zero components. The Kepler initial condition has exactly
 *       two - q = (1-e, 0), v = (0, v0) - and the registers that must
 *       hold the zeros are the ones that start at +0, so step 0 is
 *       reachable and no later step is. That is why the program
 *       engine runs the whole integration in one call and cannot
 *       resume into the middle of one, and it is why the outer solar
 *       system has no program engine at all.
 *
 *   (2) CORRECTLY ROUNDED DIVIDE AND SQUARE ROOT ARE NOT PROGRAMS.
 *       python/cft_golden/seqprogs.py - which is the library's own
 *       in-program cft_div/cft_sqrt - partitions the route as HOST
 *       prep (operand classification and the prenormalise/centre
 *       surgery), PROGRAM core, HOST finish (round_pack, the
 *       contract's single rounding authority). The core alone uses
 *       r0..r12 of the sixteen registers. So the composed route
 *       cannot be inlined inside a larger program's loop body: it
 *       needs the host between its halves, and it would not leave
 *       room for the orbit state if it did not. --rsqrt exact is
 *       therefore a loop-engine route, and --rsqrt newton exists so
 *       that the two engines have a step they can BOTH run - which
 *       they must run bit for bit.
 *
 * Under `--problem kepler --rsqrt newton` the two engines produce
 * byte-identical records, byte-identical checkpoints and the same
 * chain, and host/tests/orbits_check.py tests exactly that.
 *
 * ---------------------------------------------------------------
 * Flags: which are expected, which are certificates
 * ---------------------------------------------------------------
 *
 * NOTHING HERE IS EXACT. Every drift, every kick, every step of the
 * refinement rounds, so CFT_FLAG_INEXACT is EXPECTED on essentially
 * every call and carries no information. Saying so is the point: a
 * tool that treated inexact as a fault here would be lying about its
 * own workload, and one that never mentioned flags would be hiding
 * the four that DO mean something.
 *
 * The certificates are the other four. Over this workload
 *
 *   INVALID      would mean a NaN reached the arithmetic;
 *   DIVBYZERO    would mean r reached zero - a collision;
 *   OVERFLOW     would mean the integration went unstable;
 *   UNDERFLOW    would mean a value fell into the subnormals, which
 *                for state of order 1 (Kepler) or 1e-3..1e2 (outer)
 *                cannot happen while the integration is sane.
 *
 * so every one of them is checked on every call and any of them stops
 * the run. They are the workload's exception-flag gate, and they are
 * cheap because the library computes them anyway.
 *
 * Beside them sit the three certificates that are NOT flags, and they
 * are the ones that carry the result:
 *
 *   - the two invariants, energy and angular momentum, whose drift is
 *     reported per period at every format;
 *   - agreement with the 300-digit run of the same scheme, in ulps,
 *     which is what orbits_check.py scores;
 *   - bit identity between engines and across batch sizes.
 *
 * ---------------------------------------------------------------
 * Determinism
 * ---------------------------------------------------------------
 *
 * The ensemble advances in LOCKSTEP: one library call per operation
 * per step per batch chunk, so --batch is purely how many ensemble
 * members ride in one call and can never reach a result. Nothing
 * reduces across ensemble members. Records are chained in
 * (sample, member) order, which is fixed by construction and not by
 * the schedule. The checkpoint carries results and nothing about the
 * machine, so two runs at different batch sizes end on byte-identical
 * files - which `make -C host orbitstest` checks rather than asserts.
 *
 * No constant below is transcribed except the published initial
 * conditions, which are measurements and are cited. p is measured
 * from the library, pi comes from cft_acos(-1), 2^(1/3) from
 * cft_rootn, the Gaussian constant is squared rather than copied, the
 * Newton iteration count is derived from p, and SHA-256's round
 * constants are computed from the cube roots of the primes exactly as
 * host/tools/collatz.c computes them.
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
#define MAX_BODIES  8
#define MAX_DIM     3
#define MAX_COMP    (MAX_BODIES * MAX_DIM)
#define DECMAX   2048     /* one exact decimal, generously */

static void die(const char *what)
{
    fprintf(stderr, "cft-orbits: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-orbits: %s: %s%s%s\n", what, cft_strerror(st),
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
 * mistype. host/tests/orbits_check.py recomputes the whole chain with
 * Python's hashlib, which is what proves the derivation. This block
 * is host/tools/collatz.c's, unchanged, for the same reason the two
 * tools share a checkpoint shape.
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
    int        prec;     /* p, significand bits, hidden one included */
    int        newton;   /* refinement passes, derived from p */
} fmt_info;

static cft_device *DEV;
static uint32_t    FLAGS_SEEN = 0;
static int         FLAGS_TRUSTED = 1;
static uint64_t    N_CALLS = 0;      /* library calls issued */
static uint64_t    N_ELEMOPS = 0;    /* elementwise opcode issues */
static uint64_t    N_COMPOSED = 0;   /* cft_div / cft_sqrt element calls */

/* Every arithmetic instruction in this workload rounds, so INEXACT is
 * EXPECTED and says nothing. The other four are certificates: none of
 * them can arise from a sane integration of either problem, so any of
 * them stops the run rather than being folded into a summary. */
#define EXPECTED_FLAGS  ((uint32_t)CFT_FLAG_INEXACT)
#define CERT_FLAGS      ((uint32_t)(CFT_FLAG_INVALID | CFT_FLAG_DIVBYZERO | \
                                    CFT_FLAG_OVERFLOW | CFT_FLAG_UNDERFLOW))

static void note_flags(uint32_t f, const char *what)
{
    FLAGS_SEEN |= f;
    if (FLAGS_TRUSTED && (f & CERT_FLAGS)) {
        fprintf(stderr,
                "cft-orbits: %s raised 0x%02x - this workload can only ever "
                "raise inexact, so invalid, divide-by-zero, overflow or "
                "underflow means the integration or the tool is wrong "
                "(docs/ORBITS.md, \"Flags\")\n", what, (unsigned)f);
        exit(3);
    }
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

    /* The Newton refinement count, derived, in integers, and
     * conservative at every step.
     *
     * CFT_RSQRT_SEED's stated relative error is below 2^-8.5
     * (host/include/cft.h), so the seed is good to at least EIGHT
     * bits - the weaker integer bound, deliberately, so that nothing
     * here needs an irrational constant. The Newton-Raphson step for
     * 1/sqrt takes a relative error e to 1.5 e^2 + O(e^3), and
     * 1.5 * (2^-b)^2 < 2^-(2b-1), so a step at least DOUBLES the
     * correct bits and loses at most one. Iterating b -> 2b - 1 from
     * 8 until it passes p + 2 is therefore an upper bound on the
     * passes needed and never a lower one, and it is what the format
     * asked for rather than what somebody remembered. */
    {
        int bits = 8;
        fi->newton = 0;
        while (bits < fi->prec + 2) {
            bits = 2 * bits - 1;
            fi->newton++;
            if (fi->newton > 32)
                die("the Newton refinement did not converge - impossible");
        }
    }
}

/* ===================================================================
 * Values
 * =================================================================== */
static void run1(cft_op op, const fmt_info *fi, const void *a, const void *b,
                 const void *c, void *d)
{
    uint32_t fl = 0;
    cft_status st = cft_run(DEV, op, fi->fmt, CFT_RNE, a, b, c, d, 1, &fl,
                            NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    FLAGS_SEEN |= fl;
}

static void val_from_i64(const fmt_info *fi, int64_t v, uint8_t *out)
{
    uint32_t fl = 0;
    cft_status st = cft_cvt_from_i64(DEV, fi->fmt, CFT_RNE, &v, out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);
    if (fl & CFT_FLAG_INEXACT)
        die("an integer constant was not exact in this format");
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

/* The exact decimal of one value, 5.12.2's digits = 0 conversion.
 * Every binary float is a finite decimal, so this is the value
 * itself and not a rendering of it - which is what makes a
 * checkpoint round trip lossless and a record comparable against a
 * 300-digit oracle. */
static void val_to_dec(const fmt_info *fi, const void *v, char *out,
                       size_t cap)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, 0, out,
                                        cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

/* A short decimal, for human-readable summary lines only. Never used
 * for a record, a chain or a checkpoint. */
static void val_to_dec_short(const fmt_info *fi, const void *v, char *out,
                             size_t cap, size_t digits)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, digits,
                                        out, cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

static int val_from_dec_ok(const fmt_info *fi, const char *s, void *out,
                           int require_exact)
{
    const char *arr[1];
    uint32_t fl = 0;
    cft_status st;
    arr[0] = s;
    st = cft_from_decimal_char(DEV, fi->fmt, CFT_RNE, arr, out, 1, NULL, &fl);
    if (st != CFT_OK)
        return 0;
    if (require_exact && (fl & (CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW)))
        return 0;
    return 1;
}

/* An initial condition is a decimal literal from a published table.
 * It is converted once, correctly rounded, and the rounding is
 * expected - the table is a measurement, not a binary value. */
static void val_from_dec(const fmt_info *fi, const char *s, void *out)
{
    if (!val_from_dec_ok(fi, s, out, 0))
        die("an initial-condition literal could not be converted");
}

static int val_lt(const fmt_info *fi, const void *a, const void *b)
{
    uint8_t r[MAX_ESZ], zero[MAX_ESZ];
    run1(CFT_CMPLT, fi, a, b, NULL, r);
    memset(zero, 0, fi->esz);
    return memcmp(r, zero, fi->esz) != 0;
}

/* ===================================================================
 * The problems
 *
 * The Kepler initial condition is derived from the eccentricity, a
 * dyadic rational, so only the speed needs rounding. The outer solar
 * system's table is TRANSCRIBED, with its source, and validated
 * physically by host/tests/orbits_check.py: a mistyped digit moves an
 * osculating period by percent, and the check compares against the
 * published sidereal periods.
 *
 * Hairer, Lubich and Wanner, "Geometric Numerical Integration:
 * Structure-Preserving Algorithms for Ordinary Differential
 * Equations", 2nd edition (Springer, 2006), sections I.2.2 (Kepler)
 * and I.2.3 (the outer solar system). Masses are in solar masses,
 * lengths in AU, times in days; the Sun's mass carries the inner
 * planets.
 * =================================================================== */
enum { PROB_KEPLER = 0, PROB_OUTER = 1 };

#define ECC_NUM  3        /* eccentricity 3/4: dyadic, so 1-e and 1+e */
#define ECC_DEN  4        /* are exact in every format */

typedef struct {
    const char *name;
    const char *mass;     /* solar masses, decimal literal */
    const char *q[3];
    const char *v[3];
} body_row;

/* HLW section I.2.3. The Sun starts at rest at the origin, so the
 * barycentre drifts - that is the published setup, and the total
 * energy and total angular momentum are conserved regardless. */
static const body_row OUTER[] = {
    { "Sun",     "1.00000597682",
      { "0", "0", "0" },
      { "0", "0", "0" } },
    { "Jupiter", "0.000954786104043",
      { "-3.5023653", "-3.8169847", "-1.5507963" },
      { "0.00565429", "-0.00412490", "-0.00190589" } },
    { "Saturn",  "0.000285583733151",
      { "9.0755314", "-3.0458353", "-1.6483708" },
      { "0.00168318", "0.00483525", "0.00192462" } },
    { "Uranus",  "0.0000437273164546",
      { "8.3101420", "-16.2901086", "-7.2521278" },
      { "0.00354178", "0.00137102", "0.00055029" } },
    { "Neptune", "0.0000517759138449",
      { "11.4707666", "-25.7294829", "-10.8169456" },
      { "0.00288930", "0.00114527", "0.00039677" } }
};
#define N_OUTER ((int)(sizeof OUTER / sizeof OUTER[0]))

/* The IAU 1976 Gaussian gravitational constant. G in AU^3 day^-2
 * Msun^-1 is k^2, so this is squared rather than the square being
 * transcribed. */
#define GAUSS_K  "0.01720209895"

/* ===================================================================
 * The run
 * =================================================================== */
enum { SCHEME_LEAPFROG = 0, SCHEME_YOSHIDA4 = 1 };
enum { RSQRT_EXACT = 0, RSQRT_NEWTON = 1 };
enum { ENG_LOOP = 0, ENG_PROGRAM = 1 };
#define MAX_SUB 3

typedef struct {
    int         problem, scheme, rsqrt, engine;
    cft_format  fmt;
    size_t      members, batch;
    uint64_t    spread;
    uint64_t    steps_per_period, periods;   /* kepler */
    uint64_t    days, years;                 /* outer */
    uint64_t    sample_every;
    uint64_t    steps_opt;                   /* --steps override */
    const char *ckpt;
    double      ckpt_interval;
    int         resume;
    long        stop_after_samples, stop_after_steps;
    const char *records_path;
    const char *artifact;
    int         csv, quiet, dump_setup;
} options;

typedef struct {
    const fmt_info *fi;
    options        *O;

    int      nb, nd, ncomp;     /* bodies, dims, components = nb*nd */
    int      nsub;              /* composition substeps */
    int      nL;                /* angular-momentum components */

    uint64_t nsteps, nsamples, stride;

    /* ensemble state, SoA: comp c of member m at (c*M + m) */
    uint8_t *q, *v;
    /* scratch, all M-wide */
    uint8_t *d[MAX_DIM], *x, *y, *w, *e, *z, *g, *t1, *t2, *acc;

    /* broadcast constants, M-wide */
    uint8_t *c_hd[MAX_SUB];     /* w_i * h / 2   (drift) */
    uint8_t *c_mg[MAX_SUB];     /* -(w_i * h * mu)                kepler */
    uint8_t *c_hm[MAX_SUB][MAX_BODIES];   /*  w_i*h*m_b           outer */
    uint8_t *c_mhm[MAX_SUB][MAX_BODIES];  /* -(w_i*h*m_b)         outer */
    uint8_t *c_G, *c_mu, *c_half, *c_mone, *c_mhalf;
    uint8_t *c_m[MAX_BODIES], *c_halfm[MAX_BODIES];
    uint8_t *c_gmm[MAX_BODIES][MAX_BODIES];

    /* scalar copies (1 element) of the things the summary prints */
    uint8_t  s_h[MAX_ESZ];      /* the step size */

    /* per-member invariants and their extremes */
    uint8_t *H0, *L0[3], *Hd, *Ld[3], *dHmax, *dLmax[3];
    uint8_t *q0, *v0;           /* the initial ensemble, for separations */

    /* progress */
    uint64_t step, sample;
    uint8_t  chain[32];
    FILE    *recf;

    /* the program engine */
    cft_program *prog;
    uint8_t     *dep;
    uint32_t    *depcount;
    uint32_t     n_insns, max_deposits;
    uint64_t     alu_per_step;   /* ALU issues one step costs a lane */
} runstate;

/* ---- chunked library calls ---------------------------------------
 * Every elementwise operation goes through here, and it is the only
 * place --batch appears. n is always the ensemble size; the chunking
 * is the library-call boundary and nothing else, which is what makes
 * batch-size independence a property of every operation rather than
 * of the tool's outer loop. */
static void opN(runstate *R, cft_op op, const void *a, const void *b,
                const void *c, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_run(DEV, op, fi->fmt, CFT_RNE,
                                a ? (const uint8_t *)a + i * esz : NULL,
                                b ? (const uint8_t *)b + i * esz : NULL,
                                c ? (const uint8_t *)c + i * esz : NULL,
                                (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        note_flags(fl, cft_op_name(op));
        N_CALLS++;
        N_ELEMOPS += n;
    }
}

static void sqrtN(runstate *R, const void *a, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_sqrt(DEV, fi->fmt, CFT_RNE,
                                 (const uint8_t *)a + i * esz,
                                 (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_sqrt", st);
        note_flags(fl, "cft_sqrt");
        N_CALLS++;
        N_COMPOSED += n;
    }
}

static void divN(runstate *R, const void *a, const void *b, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_div(DEV, fi->fmt, CFT_RNE,
                                (const uint8_t *)a + i * esz,
                                (const uint8_t *)b + i * esz,
                                (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        note_flags(fl, "cft_div");
        N_CALLS++;
        N_COMPOSED += n;
    }
}

static uint8_t *alloc_m(runstate *R)
{
    return (uint8_t *)xcalloc(R->O->members, R->fi->esz);
}

static void bcast(runstate *R, uint8_t *dst, const uint8_t *v)
{
    size_t i, esz = R->fi->esz;
    for (i = 0; i < R->O->members; i++)
        memcpy(dst + i * esz, v, esz);
}

static uint8_t *alloc_bcast(runstate *R, const uint8_t *v)
{
    uint8_t *p = alloc_m(R);
    bcast(R, p, v);
    return p;
}

#define CQ(R, c)  ((R)->q + (size_t)(c) * (R)->O->members * (R)->fi->esz)
#define CV(R, c)  ((R)->v + (size_t)(c) * (R)->O->members * (R)->fi->esz)
#define COMP(R, b, k)  ((b) * (R)->nd + (k))

/* ===================================================================
 * 1/r^3, both routes
 *
 * On entry R->x holds r^2 for every member; on exit `dst` holds
 * scale / r^3, where `scale` is a broadcast constant. The two routes
 * are different arithmetic and are not expected to agree - which is
 * why --rsqrt is a run parameter that the checkpoint records.
 * =================================================================== */
static void inv_r3_scaled(runstate *R, const uint8_t *scale, uint8_t *dst)
{
    int k;
    if (R->O->rsqrt == RSQRT_EXACT) {
        sqrtN(R, R->x, R->y);                       /* s   = sqrt(r^2)  */
        opN(R, CFT_MUL, R->x, R->y, NULL, R->w);    /* w   = r^2 * s    */
        divN(R, scale, R->w, dst);                  /* dst = scale / r^3 */
        return;
    }
    /* y0 = seed, then the derived number of Newton passes:
     *      y <- y + (y/2)(1 - x y^2)
     * written as the four ALU opcodes a sequencer program carries. */
    opN(R, CFT_RSQRT_SEED, R->x, NULL, NULL, R->y);
    for (k = 0; k < R->fi->newton; k++) {
        opN(R, CFT_MUL, R->x, R->y, NULL, R->w);            /* w = x*y      */
        opN(R, CFT_FMA, R->w, R->y, R->c_mone, R->e);       /* e = x y^2 -1 */
        opN(R, CFT_MUL, R->y, R->c_mhalf, NULL, R->z);      /* z = -y/2     */
        opN(R, CFT_FMA, R->z, R->e, R->y, R->y);            /* y = y - ye/2 */
    }
    opN(R, CFT_MUL, R->y, R->y, NULL, R->w);                /* w = y^2      */
    opN(R, CFT_MUL, R->w, R->y, NULL, R->w);                /* w = y^3      */
    opN(R, CFT_MUL, R->w, scale, NULL, dst);
}

/* ===================================================================
 * The force, and the substep
 * =================================================================== */
static void kepler_r2(runstate *R)
{
    /* r^2 = q0^2 + q1^2, one multiply and one FMA, in a fixed order */
    opN(R, CFT_MUL, CQ(R, 1), CQ(R, 1), NULL, R->w);
    opN(R, CFT_FMA, CQ(R, 0), CQ(R, 0), R->w, R->x);
}

static void drift(runstate *R, int sub)
{
    int c;
    for (c = 0; c < R->ncomp; c++)
        opN(R, CFT_FMA, R->c_hd[sub], CV(R, c), CQ(R, c), CQ(R, c));
}

static void kick_kepler(runstate *R, int sub)
{
    kepler_r2(R);
    inv_r3_scaled(R, R->c_mg[sub], R->g);   /* g = -(w h mu)/r^3 */
    opN(R, CFT_FMA, R->g, CQ(R, 0), CV(R, 0), CV(R, 0));
    opN(R, CFT_FMA, R->g, CQ(R, 1), CV(R, 1), CV(R, 1));
}

/* Pairs in lexicographic (i, j) order with i < j, and the kick
 * accumulated straight into v as each pair is computed. Both are part
 * of the arithmetic, not of the implementation: a different pair
 * order is a different sequence of roundings and therefore a
 * different (equally valid, equally reproducible) result. */
static void kick_outer(runstate *R, int sub)
{
    int i, j, k;
    for (i = 0; i < R->nb; i++) {
        for (j = i + 1; j < R->nb; j++) {
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_SUB, CQ(R, COMP(R, j, k)), NULL,
                    CQ(R, COMP(R, i, k)), R->d[k]);
            opN(R, CFT_MUL, R->d[R->nd - 1], R->d[R->nd - 1], NULL, R->w);
            for (k = R->nd - 2; k > 0; k--)
                opN(R, CFT_FMA, R->d[k], R->d[k], R->w, R->w);
            opN(R, CFT_FMA, R->d[0], R->d[0], R->w, R->x);
            inv_r3_scaled(R, R->c_G, R->t1);          /* t1 = G / r^3 */
            opN(R, CFT_MUL, R->t1, R->c_hm[sub][j], NULL, R->g);
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_FMA, R->g, R->d[k], CV(R, COMP(R, i, k)),
                    CV(R, COMP(R, i, k)));
            opN(R, CFT_MUL, R->t1, R->c_mhm[sub][i], NULL, R->g);
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_FMA, R->g, R->d[k], CV(R, COMP(R, j, k)),
                    CV(R, COMP(R, j, k)));
        }
    }
}

static void substep(runstate *R, int sub)
{
    drift(R, sub);
    if (R->O->problem == PROB_KEPLER)
        kick_kepler(R, sub);
    else
        kick_outer(R, sub);
    drift(R, sub);
}

static void one_step(runstate *R)
{
    int s;
    for (s = 0; s < R->nsub; s++)
        substep(R, s);
}

/* ===================================================================
 * The invariants
 *
 * Summed in a fixed index order with elementwise adds - never through
 * cft_reduce, whose reduction runs over ELEMENTS, and an element here
 * is an ensemble member.
 * =================================================================== */
static void invariants(runstate *R, const uint8_t *qq, const uint8_t *vv,
                       uint8_t *H, uint8_t *L[3])
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members;
    int i, j, k;
    const uint8_t *Q, *V;
#define QC(c) (qq + (size_t)(c) * M * esz)
#define VC(c) (vv + (size_t)(c) * M * esz)

    if (R->O->problem == PROB_KEPLER) {
        /* H = (v0^2 + v1^2)/2 - mu/r */
        opN(R, CFT_MUL, VC(1), VC(1), NULL, R->w);
        opN(R, CFT_FMA, VC(0), VC(0), R->w, R->t1);
        opN(R, CFT_MUL, R->t1, R->c_half, NULL, R->t1);
        opN(R, CFT_MUL, QC(1), QC(1), NULL, R->w);
        opN(R, CFT_FMA, QC(0), QC(0), R->w, R->x);
        sqrtN(R, R->x, R->y);
        divN(R, R->c_mu, R->y, R->t2);
        opN(R, CFT_SUB, R->t1, NULL, R->t2, H);
        /* L = q0 v1 - q1 v0 */
        opN(R, CFT_MUL, QC(1), VC(0), NULL, R->w);
        opN(R, CFT_NEG, R->w, NULL, NULL, R->w);
        opN(R, CFT_FMA, QC(0), VC(1), R->w, L[0]);
        return;
    }

    /* KE = sum_b (m_b/2) |v_b|^2, bodies in index order */
    for (i = 0; i < R->nb; i++) {
        opN(R, CFT_MUL, VC(COMP(R, i, R->nd - 1)),
            VC(COMP(R, i, R->nd - 1)), NULL, R->w);
        for (k = R->nd - 2; k >= 0; k--)
            opN(R, CFT_FMA, VC(COMP(R, i, k)), VC(COMP(R, i, k)), R->w,
                R->w);
        opN(R, CFT_MUL, R->w, R->c_halfm[i], NULL, R->t1);
        if (i == 0)
            memcpy(R->acc, R->t1, M * esz);
        else
            opN(R, CFT_ADD, R->acc, NULL, R->t1, R->acc);
    }
    memcpy(H, R->acc, M * esz);
    /* PE = -sum_{i<j} G m_i m_j / r_ij, pairs in the kick's own order */
    for (i = 0; i < R->nb; i++) {
        for (j = i + 1; j < R->nb; j++) {
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_SUB, QC(COMP(R, j, k)), NULL, QC(COMP(R, i, k)),
                    R->d[k]);
            opN(R, CFT_MUL, R->d[R->nd - 1], R->d[R->nd - 1], NULL, R->w);
            for (k = R->nd - 2; k > 0; k--)
                opN(R, CFT_FMA, R->d[k], R->d[k], R->w, R->w);
            opN(R, CFT_FMA, R->d[0], R->d[0], R->w, R->x);
            sqrtN(R, R->x, R->y);
            divN(R, R->c_gmm[i][j], R->y, R->t1);
            opN(R, CFT_SUB, H, NULL, R->t1, H);
        }
    }
    /* L = sum_b m_b (q_b x v_b), components in x, y, z order */
    for (k = 0; k < 3; k++) {
        int k1 = (k + 1) % 3, k2 = (k + 2) % 3;
        for (i = 0; i < R->nb; i++) {
            Q = QC(COMP(R, i, k2));
            V = VC(COMP(R, i, k1));
            opN(R, CFT_MUL, Q, V, NULL, R->w);
            opN(R, CFT_NEG, R->w, NULL, NULL, R->w);
            opN(R, CFT_FMA, QC(COMP(R, i, k1)), VC(COMP(R, i, k2)), R->w,
                R->t1);
            opN(R, CFT_MUL, R->t1, R->c_m[i], NULL, R->t1);
            if (i == 0)
                memcpy(L[k], R->t1, M * esz);
            else
                opN(R, CFT_ADD, L[k], NULL, R->t1, L[k]);
        }
    }
#undef QC
#undef VC
}

/* ===================================================================
 * Records and the hash chain
 *
 *   chain_0     = 32 zero bytes
 *   chain_(i+1) = SHA-256( chain_i || record_i || "\n" )
 *
 * over records in (sample, member) order. That order is fixed by
 * construction and never by the schedule, which is what makes the
 * chain independent of the batch size, of the engine and of where a
 * run was interrupted.
 * =================================================================== */
static void chain_absorb(runstate *R, const char *line)
{
    sha256 h;
    sha256_start(&h);
    sha256_push(&h, R->chain, sizeof R->chain);
    sha256_push(&h, line, strlen(line));
    sha256_push(&h, "\n", 1);
    sha256_end(&h, R->chain);
}

/* Build one record line: sample, step, member, then every state
 * component and every invariant as an EXACT decimal. */
static void record_line(runstate *R, uint64_t sample, uint64_t step,
                        size_t m, const uint8_t *qq, const uint8_t *vv,
                        const uint8_t *H, uint8_t *const L[3],
                        char *out, size_t cap)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, used;
    char dec[DECMAX];
    int c, k, n;

    n = snprintf(out, cap, "%" PRIu64 " %" PRIu64 " %" PRIu64,
                 sample, step, (uint64_t)m);
    if (n <= 0 || (size_t)n >= cap)
        die("record line too long");
    used = (size_t)n;
#define PUT(ptr) do {                                                    \
        val_to_dec(fi, (ptr), dec, sizeof dec);                          \
        if (used + strlen(dec) + 2 >= cap) die("record line too long");   \
        out[used++] = ' ';                                               \
        memcpy(out + used, dec, strlen(dec));                            \
        used += strlen(dec);                                             \
        out[used] = 0;                                                   \
    } while (0)
    for (c = 0; c < R->ncomp; c++)
        PUT(qq + ((size_t)c * M + m) * esz);
    for (c = 0; c < R->ncomp; c++)
        PUT(vv + ((size_t)c * M + m) * esz);
    PUT(H + m * esz);
    for (k = 0; k < R->nL; k++)
        PUT(L[k] + m * esz);
#undef PUT
}

/* ===================================================================
 * One sample: invariants, extremes, records, chain
 * =================================================================== */
static void emit_sample(runstate *R, uint64_t sample, uint64_t step,
                        const uint8_t *qq, const uint8_t *vv)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, m;
    char *line;
    int k;

    invariants(R, qq, vv, R->Hd, R->Ld);

    if (sample == 0) {
        memcpy(R->H0, R->Hd, M * esz);
        for (k = 0; k < R->nL; k++)
            memcpy(R->L0[k], R->Ld[k], M * esz);
    } else {
        opN(R, CFT_SUB, R->Hd, NULL, R->H0, R->t1);
        opN(R, CFT_ABS, R->t1, NULL, NULL, R->t1);
        opN(R, CFT_MAX, R->dHmax, R->t1, NULL, R->dHmax);
        for (k = 0; k < R->nL; k++) {
            opN(R, CFT_SUB, R->Ld[k], NULL, R->L0[k], R->t1);
            opN(R, CFT_ABS, R->t1, NULL, NULL, R->t1);
            opN(R, CFT_MAX, R->dLmax[k], R->t1, NULL, R->dLmax[k]);
        }
    }

    line = (char *)xcalloc(1, (size_t)(2 * R->ncomp + 8) * DECMAX);
    for (m = 0; m < M; m++) {
        record_line(R, sample, step, m, qq, vv, R->Hd, R->Ld, line,
                    (size_t)(2 * R->ncomp + 8) * DECMAX);
        chain_absorb(R, line);
        if (R->recf)
            fprintf(R->recf, "%s\n", line);
    }
    free(line);
}

/* ===================================================================
 * The step as an orbit-sequencer program (Kepler, --rsqrt newton)
 *
 * docs/SEQUENCER.md's encoding. Registers:
 *
 *   r0 = q0   (the a stream)          r4 = r^2
 *   r1 = v1   (the b stream)          r5 = y, the rsqrt iterate
 *   r2 = q1   (the c stream: +0)      r6 = w
 *   r3 = v0   (starts at +0)          r7 = e
 *                                     r8 = z
 *                                     r9 = g
 *
 * The mapping is forced. cft_program_run can initialise only r0, r1
 * and r2, and the Kepler initial condition has exactly two non-zero
 * components, so the two that must be zero are put in registers that
 * start at +0 - r2 by passing c = NULL, r3 because r3..r15 always do.
 * =================================================================== */
enum { R_Q0 = 0, R_V1 = 1, R_Q1 = 2, R_V0 = 3,
       R_X = 4, R_Y = 5, R_W = 6, R_E = 7, R_Z = 8, R_G = 9 };
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };
#define DEPOSITS_PER_SAMPLE 4

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

/* Constant-bank indices. c_hd[s] and c_mg[s] are per substep, so the
 * bank grows with the composition. */
#define KB_MONE   0
#define KB_MHALF  1
#define KB_HD(s)  (2 + 2 * (s))
#define KB_MG(s)  (3 + 2 * (s))

static uint8_t *build_program(runstate *R, size_t *bytes_out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, i, off, nk;
    uint64_t *ins;
    uint32_t n = 0, cap;
    uint8_t *img;
    int s, k;

    nk = (size_t)(2 + 2 * R->nsub);
    cap = (uint32_t)(16 + R->nsub * (16 + 4 * R->fi->newton) + 16);
    ins = (uint64_t *)xcalloc(cap, sizeof(uint64_t));

    /* sample 0: the initial state, before a single step */
    ins[n++] = ctl(C_DEPOSIT, R_Q0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q1, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V1, 0);

    ins[n++] = ctl(C_REPEAT, 0, (uint32_t)R->nsamples);
    ins[n++] = ctl(C_REPEAT, 0, (uint32_t)R->stride);
    for (s = 0; s < R->nsub; s++) {
        ins[n++] = alu(CFT_FMA, R_Q0, KB_HD(s), R_V0, R_Q0, 1, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q1, KB_HD(s), R_V1, R_Q1, 1, 0, 0);
        ins[n++] = alu(CFT_MUL, R_W, R_Q1, R_Q1, 0, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_X, R_Q0, R_Q0, R_W, 0, 0, 0);
        ins[n++] = alu(CFT_RSQRT_SEED, R_Y, R_X, 0, 0, 0, 0, 0);
        for (k = 0; k < fi->newton; k++) {
            ins[n++] = alu(CFT_MUL, R_W, R_X, R_Y, 0, 0, 0, 0);
            ins[n++] = alu(CFT_FMA, R_E, R_W, R_Y, KB_MONE, 0, 0, 1);
            ins[n++] = alu(CFT_MUL, R_Z, R_Y, KB_MHALF, 0, 0, 1, 0);
            ins[n++] = alu(CFT_FMA, R_Y, R_Z, R_E, R_Y, 0, 0, 0);
        }
        ins[n++] = alu(CFT_MUL, R_W, R_Y, R_Y, 0, 0, 0, 0);
        ins[n++] = alu(CFT_MUL, R_W, R_W, R_Y, 0, 0, 0, 0);
        ins[n++] = alu(CFT_MUL, R_G, R_W, KB_MG(s), 0, 0, 1, 0);
        ins[n++] = alu(CFT_FMA, R_V0, R_G, R_Q0, R_V0, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_V1, R_G, R_Q1, R_V1, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q0, KB_HD(s), R_V0, R_Q0, 1, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q1, KB_HD(s), R_V1, R_Q1, 1, 0, 0);
    }
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q1, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V1, 0);
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_HALT, 0, 0);
    if (n > cap)
        die("the program image outgrew its buffer");

    R->n_insns = n;
    R->max_deposits = (uint32_t)((R->nsamples + 1) * DEPOSITS_PER_SAMPLE);
    R->alu_per_step = (uint64_t)R->nsub * (12 + 4 * (uint64_t)fi->newton);

    *bytes_out = 32 + nk * esz + (size_t)n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);
    put_le32(img + 8, n);
    put_le32(img + 12, (uint32_t)nk);
    put_le32(img + 16, R->max_deposits);
    put_le32(img + 20, (uint32_t)fi->fmt);
    off = 32;
    memcpy(img + off + (size_t)KB_MONE * esz, R->c_mone, esz);
    memcpy(img + off + (size_t)KB_MHALF * esz, R->c_mhalf, esz);
    for (s = 0; s < R->nsub; s++) {
        memcpy(img + off + (size_t)KB_HD(s) * esz, R->c_hd[s], esz);
        memcpy(img + off + (size_t)KB_MG(s) * esz, R->c_mg[s], esz);
    }
    off += nk * esz;
    for (i = 0; i < n; i++) {
        put_le64(img + off, ins[i]);
        off += 8;
    }
    free(ins);
    return img;
}

/* ===================================================================
 * The checkpoint
 *
 * A line-oriented ASCII file, written to <path>.tmp, flushed, closed
 * and then RENAMED over the target, so a reader never sees a
 * half-written one. It carries every number that describes a RESULT
 * and nothing that describes the MACHINE - no batch size, no engine,
 * no timing - which is what lets two runs with different batch sizes
 * end on byte-identical files.
 * =================================================================== */
#define CKPT_MAGIC "cft-orbits-checkpoint 1"

static int ckpt_replace(const char *tmp, const char *path)
{
#if defined(_WIN32)
    return MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING) ? 0 : -1;
#else
    return rename(tmp, path);
#endif
}

static const char *problem_name(int p)
{
    return p == PROB_KEPLER ? "kepler" : "outer";
}

static const char *scheme_name(int s)
{
    return s == SCHEME_LEAPFROG ? "leapfrog" : "yoshida4";
}

static const char *rsqrt_name(int r)
{
    return r == RSQRT_EXACT ? "exact" : "newton";
}

static void ckpt_write(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    char tmp[1024], dec[DECMAX], chain[65];
    FILE *f;
    size_t m, esz = fi->esz, M = O->members;
    int c, k;

    if (!O->ckpt)
        return;
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt) >= sizeof tmp)
        die("checkpoint path too long");
    f = fopen(tmp, "wb");
    if (!f)
        die("cannot write the checkpoint");

    hex32(R->chain, chain);
    fprintf(f, "%s\n", CKPT_MAGIC);
    fprintf(f, "format %s\n", cft_format_name(fi->fmt));
    fprintf(f, "problem %s\n", problem_name(O->problem));
    fprintf(f, "scheme %s\n", scheme_name(O->scheme));
    fprintf(f, "rsqrt %s\n", rsqrt_name(O->rsqrt));
    fprintf(f, "members %" PRIu64 "\n", (uint64_t)M);
    fprintf(f, "spread %" PRIu64 "\n", O->spread);
    fprintf(f, "bodies %d\n", R->nb);
    fprintf(f, "dims %d\n", R->nd);
    val_to_dec(fi, R->s_h, dec, sizeof dec);
    fprintf(f, "h %s\n", dec);
    fprintf(f, "steps %" PRIu64 "\n", R->nsteps);
    fprintf(f, "stride %" PRIu64 "\n", R->stride);
    fprintf(f, "samples %" PRIu64 "\n", R->nsamples);
    fprintf(f, "at %" PRIu64 " %" PRIu64 "\n", R->step, R->sample);
    fprintf(f, "chain %s\n", chain);
    for (m = 0; m < M; m++) {
        fprintf(f, "state %" PRIu64, (uint64_t)m);
        for (c = 0; c < R->ncomp; c++) {
            val_to_dec(fi, CQ(R, c) + m * esz, dec, sizeof dec);
            fprintf(f, " %s", dec);
        }
        for (c = 0; c < R->ncomp; c++) {
            val_to_dec(fi, CV(R, c) + m * esz, dec, sizeof dec);
            fprintf(f, " %s", dec);
        }
        fprintf(f, "\n");
    }
    for (m = 0; m < M; m++) {
        fprintf(f, "inv %" PRIu64, (uint64_t)m);
        val_to_dec(fi, R->H0 + m * esz, dec, sizeof dec);
        fprintf(f, " %s", dec);
        val_to_dec(fi, R->dHmax + m * esz, dec, sizeof dec);
        fprintf(f, " %s", dec);
        for (k = 0; k < R->nL; k++) {
            val_to_dec(fi, R->L0[k] + m * esz, dec, sizeof dec);
            fprintf(f, " %s", dec);
            val_to_dec(fi, R->dLmax[k] + m * esz, dec, sizeof dec);
            fprintf(f, " %s", dec);
        }
        fprintf(f, "\n");
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

/* Read one whitespace-delimited token out of *pp, advancing it. */
static int next_tok(char **pp, char *out, size_t cap)
{
    char *p = *pp;
    size_t n = 0;
    while (*p == ' ' || *p == '\t')
        p++;
    if (!*p)
        return 0;
    while (*p && *p != ' ' && *p != '\t') {
        if (n + 1 >= cap)
            return 0;
        out[n++] = *p++;
    }
    out[n] = 0;
    *pp = p;
    return 1;
}

static void ckpt_read(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    FILE *f = fopen(O->ckpt, "rb");
    size_t esz = fi->esz, linecap = (size_t)(2 * R->ncomp + 8) * DECMAX;
    char *line = (char *)xcalloc(1, linecap);
    char tok[DECMAX];
    int c, k;

    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, (int)linecap, f) ||
        strcmp(trim_nl(line), CKPT_MAGIC) != 0)
        die("that file is not a cft-orbits checkpoint of this version");

    while (fgets(line, (int)linecap, f)) {
        char *p = line;
        trim_nl(line);
        if (!next_tok(&p, tok, sizeof tok))
            continue;
        if (!strcmp(tok, "format")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, cft_format_name(fi->fmt)))
                die("the checkpoint was written for a different format");
        } else if (!strcmp(tok, "problem")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, problem_name(O->problem)))
                die("the checkpoint was written for a different problem");
        } else if (!strcmp(tok, "scheme")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, scheme_name(O->scheme)))
                die("the checkpoint was written for a different scheme");
        } else if (!strcmp(tok, "rsqrt")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, rsqrt_name(O->rsqrt)))
                die("the checkpoint was written for a different 1/r^3 route");
        } else if (!strcmp(tok, "members")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != (unsigned long long)O->members)
                die("the checkpoint has a different ensemble size");
        } else if (!strcmp(tok, "steps")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != R->nsteps)
                die("the checkpoint was written for a different step count");
        } else if (!strcmp(tok, "stride")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != R->stride)
                die("the checkpoint was written for a different sample "
                    "interval");
        } else if (!strcmp(tok, "h")) {
            uint8_t got[MAX_ESZ];
            if (!next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, got, 1) ||
                memcmp(got, R->s_h, esz) != 0)
                die("the checkpoint was written for a different step size");
        } else if (!strcmp(tok, "at")) {
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint at-line");
            R->step = strtoull(tok, NULL, 10);
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint at-line");
            R->sample = strtoull(tok, NULL, 10);
        } else if (!strcmp(tok, "chain")) {
            if (!next_tok(&p, tok, sizeof tok) || !unhex32(tok, R->chain))
                die("bad checkpoint chain");
        } else if (!strcmp(tok, "state")) {
            size_t m;
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint state line");
            m = (size_t)strtoull(tok, NULL, 10);
            if (m >= O->members)
                die("a checkpoint state line names a member out of range");
            for (c = 0; c < R->ncomp; c++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, CQ(R, c) + m * esz, 1))
                    die("bad checkpoint position");
            for (c = 0; c < R->ncomp; c++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, CV(R, c) + m * esz, 1))
                    die("bad checkpoint velocity");
        } else if (!strcmp(tok, "inv")) {
            size_t m;
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint inv line");
            m = (size_t)strtoull(tok, NULL, 10);
            if (m >= O->members)
                die("a checkpoint inv line names a member out of range");
            if (!next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, R->H0 + m * esz, 1) ||
                !next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, R->dHmax + m * esz, 1))
                die("bad checkpoint invariant");
            for (k = 0; k < R->nL; k++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, R->L0[k] + m * esz, 1) ||
                    !next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, R->dLmax[k] + m * esz, 1))
                    die("bad checkpoint invariant");
        } else if (!strcmp(tok, "end")) {
            break;
        }
    }
    fclose(f);
    free(line);
}

/* ===================================================================
 * Setting the ensemble up
 * =================================================================== */

/* nextUp applied `n` times to a positive finite value, as one integer
 * add on the encoding - the tile's own CFT_IADD, no rounding, no
 * flag. The perturbation ladder is therefore exact and identical on
 * every backend. */
static void bump_ulps(runstate *R, uint8_t *val, uint64_t n)
{
    const fmt_info *fi = R->fi;
    uint8_t bits[MAX_ESZ], zero[MAX_ESZ];
    size_t i;
    if (!n)
        return;
    memset(bits, 0, fi->esz);
    for (i = 0; i < 8 && i < fi->esz; i++)
        bits[i] = (uint8_t)(n >> (8 * i));
    memset(zero, 0, fi->esz);
    if (!val_lt(fi, zero, val))
        die("the perturbation ladder only steps positive values");
    run1(CFT_IADD, fi, val, bits, NULL, val);
}

static void setup_state(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, m;
    uint8_t tmp[MAX_ESZ];
    int b, k;

    if (O->problem == PROB_KEPLER) {
        uint8_t num[MAX_ESZ], den[MAX_ESZ], q0[MAX_ESZ], v1[MAX_ESZ];
        /* q0 = 1 - e = (DEN-NUM)/DEN, exact for a dyadic denominator */
        val_from_i64(fi, ECC_DEN - ECC_NUM, num);
        val_from_i64(fi, ECC_DEN, den);
        {
            uint32_t fl = 0;
            cft_status st = cft_div(DEV, fi->fmt, CFT_RNE, num, den, q0, 1,
                                    &fl, NULL);
            if (st != CFT_OK)
                die_st("cft_div", st);
            if (fl & CFT_FLAG_INEXACT)
                die("1 - e is not exact: choose a dyadic eccentricity");
            /* v1 = sqrt((1+e)/(1-e)) */
            val_from_i64(fi, ECC_DEN + ECC_NUM, num);
            val_from_i64(fi, ECC_DEN - ECC_NUM, den);
            st = cft_div(DEV, fi->fmt, CFT_RNE, num, den, tmp, 1, &fl, NULL);
            if (st != CFT_OK)
                die_st("cft_div", st);
            st = cft_sqrt(DEV, fi->fmt, CFT_RNE, tmp, v1, 1, NULL, NULL);
            if (st != CFT_OK)
                die_st("cft_sqrt", st);
        }
        for (m = 0; m < M; m++) {
            memcpy(CQ(R, 0) + m * esz, q0, esz);
            memset(CQ(R, 1) + m * esz, 0, esz);
            memset(CV(R, 0) + m * esz, 0, esz);
            memcpy(CV(R, 1) + m * esz, v1, esz);
            /* the ladder: member 0 unperturbed, then alternate q0 and
             * v1 with a rung of --spread ulps each time round */
            if (m) {
                uint64_t rung = (uint64_t)((m + 1) / 2) * O->spread;
                if (m & 1)
                    bump_ulps(R, CQ(R, 0) + m * esz, rung);
                else
                    bump_ulps(R, CV(R, 1) + m * esz, rung);
            }
        }
        return;
    }

    for (b = 0; b < R->nb; b++) {
        for (k = 0; k < R->nd; k++) {
            val_from_dec(fi, OUTER[b].q[k], tmp);
            for (m = 0; m < M; m++)
                memcpy(CQ(R, COMP(R, b, k)) + m * esz, tmp, esz);
            val_from_dec(fi, OUTER[b].v[k], tmp);
            for (m = 0; m < M; m++)
                memcpy(CV(R, COMP(R, b, k)) + m * esz, tmp, esz);
        }
    }
    /* the ladder, on Jupiter's x, alternating position and velocity.
     * Both are positive-signed? They are not - Jupiter's x is
     * negative - so the ladder steps the MAGNITUDE by working on
     * |x| and putting the sign back, which is still an exact
     * integer step on the encoding. */
    for (m = 1; m < M; m++) {
        uint64_t rung = (uint64_t)((m + 1) / 2) * O->spread;
        uint8_t *slot = (m & 1) ? CQ(R, COMP(R, 1, 0)) + m * esz
                                : CV(R, COMP(R, 1, 0)) + m * esz;
        uint8_t mag[MAX_ESZ], sgn[MAX_ESZ];
        memcpy(sgn, slot, esz);
        run1(CFT_ABS, fi, slot, NULL, NULL, mag);
        bump_ulps(R, mag, rung);
        run1(CFT_COPYSIGN, fi, mag, sgn, NULL, slot);
    }
}

/* ===================================================================
 * Constants: the step size, the composition weights, the masses
 * =================================================================== */
static void setup_constants(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    uint8_t one[MAX_ESZ], mone[MAX_ESZ], two[MAX_ESZ], tmp[MAX_ESZ];
    uint8_t half[MAX_ESZ], mhalf[MAX_ESZ], h[MAX_ESZ];
    uint8_t wgt[MAX_SUB][MAX_ESZ];
    uint8_t mass[MAX_BODIES][MAX_ESZ], gconst[MAX_ESZ];
    cft_status st;
    int s, b, j;

    val_from_i64(fi, 1, one);
    val_from_i64(fi, -1, mone);
    val_from_i64(fi, 2, two);
    val_pow2(fi, -1, half);
    run1(CFT_NEG, fi, half, NULL, NULL, mhalf);

    R->c_mone  = alloc_bcast(R, mone);
    R->c_half  = alloc_bcast(R, half);
    R->c_mhalf = alloc_bcast(R, mhalf);

    /* --- the step size --- */
    if (O->problem == PROB_KEPLER) {
        /* h = 2 pi / steps_per_period, with pi from the library:
         * acos(-1) is correctly rounded, so pi is the format's pi and
         * not a transcription of anybody's digits. */
        uint8_t pi[MAX_ESZ], twopi[MAX_ESZ], nsp[MAX_ESZ];
        st = cft_acos(DEV, fi->fmt, CFT_RNE, mone, pi, 1, NULL);
        if (st != CFT_OK)
            die_st("cft_acos", st);
        run1(CFT_MUL, fi, pi, two, NULL, twopi);
        val_from_i64(fi, (int64_t)O->steps_per_period, nsp);
        st = cft_div(DEV, fi->fmt, CFT_RNE, twopi, nsp, h, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
    } else {
        val_from_i64(fi, (int64_t)O->days, h);
    }
    memcpy(R->s_h, h, fi->esz);

    /* --- the composition weights --- */
    if (O->scheme == SCHEME_LEAPFROG) {
        R->nsub = 1;
        memcpy(wgt[0], one, fi->esz);
    } else {
        /* w1 = 1/(2 - 2^(1/3)),  w0 = -2^(1/3) * w1, derived from
         * rootn(2, 3) - 754-2019 9.2's correctly rounded root. */
        uint8_t cbrt2[MAX_ESZ], den[MAX_ESZ], w1[MAX_ESZ], w0[MAX_ESZ];
        int64_t three = 3;
        st = cft_rootn(DEV, fi->fmt, CFT_RNE, two, &three, cbrt2, 1, NULL);
        if (st != CFT_OK)
            die_st("cft_rootn", st);
        run1(CFT_SUB, fi, two, NULL, cbrt2, den);
        st = cft_div(DEV, fi->fmt, CFT_RNE, one, den, w1, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        run1(CFT_MUL, fi, cbrt2, w1, NULL, tmp);
        run1(CFT_NEG, fi, tmp, NULL, NULL, w0);
        R->nsub = 3;
        memcpy(wgt[0], w1, fi->esz);
        memcpy(wgt[1], w0, fi->esz);
        memcpy(wgt[2], w1, fi->esz);
    }

    /* --- masses and G --- */
    if (O->problem == PROB_KEPLER) {
        val_from_i64(fi, 1, mass[0]);              /* mu = 1 */
        R->c_mu = alloc_bcast(R, mass[0]);
    } else {
        uint8_t k[MAX_ESZ];
        val_from_dec(fi, GAUSS_K, k);
        run1(CFT_MUL, fi, k, k, NULL, gconst);     /* G = k^2 */
        R->c_G = alloc_bcast(R, gconst);
        for (b = 0; b < R->nb; b++) {
            val_from_dec(fi, OUTER[b].mass, mass[b]);
            R->c_m[b] = alloc_bcast(R, mass[b]);
            run1(CFT_MUL, fi, mass[b], half, NULL, tmp);
            R->c_halfm[b] = alloc_bcast(R, tmp);
        }
        for (b = 0; b < R->nb; b++)
            for (j = b + 1; j < R->nb; j++) {
                run1(CFT_MUL, fi, gconst, mass[b], NULL, tmp);
                run1(CFT_MUL, fi, tmp, mass[j], NULL, tmp);
                R->c_gmm[b][j] = alloc_bcast(R, tmp);
            }
    }

    /* --- the per-substep drift and kick scales --- */
    for (s = 0; s < R->nsub; s++) {
        uint8_t hs[MAX_ESZ], hd[MAX_ESZ];
        run1(CFT_MUL, fi, wgt[s], h, NULL, hs);        /* w_s h        */
        run1(CFT_MUL, fi, hs, half, NULL, hd);         /* w_s h / 2    */
        R->c_hd[s] = alloc_bcast(R, hd);
        if (O->problem == PROB_KEPLER) {
            run1(CFT_MUL, fi, hs, mass[0], NULL, tmp); /* w_s h mu     */
            run1(CFT_NEG, fi, tmp, NULL, NULL, tmp);
            R->c_mg[s] = alloc_bcast(R, tmp);
        } else {
            for (b = 0; b < R->nb; b++) {
                run1(CFT_MUL, fi, hs, mass[b], NULL, tmp);
                R->c_hm[s][b] = alloc_bcast(R, tmp);
                run1(CFT_NEG, fi, tmp, NULL, NULL, tmp);
                R->c_mhm[s][b] = alloc_bcast(R, tmp);
            }
        }
    }
}

/* ===================================================================
 * Reporting
 * =================================================================== */
static void max_over_members(runstate *R, const uint8_t *a, uint8_t *out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, m;
    memcpy(out, a, esz);
    for (m = 1; m < R->O->members; m++)
        if (val_lt(fi, out, a + m * esz))
            memcpy(out, a + m * esz, esz);
}

/* The separation of each member from member 0, as a Euclidean norm
 * over the whole state vector. One-element library calls: the
 * ensemble is the element axis, so a cross-member quantity cannot be
 * an elementwise op and is assembled member by member instead. */
static void separations(runstate *R, const uint8_t *qq, const uint8_t *vv,
                        uint8_t *out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, m;
    uint8_t acc[MAX_ESZ], t[MAX_ESZ], u[MAX_ESZ];
    int c;
    for (m = 0; m < M; m++) {
        memset(acc, 0, esz);
        for (c = 0; c < R->ncomp; c++) {
            run1(CFT_SUB, fi, qq + ((size_t)c * M + m) * esz, NULL,
                 qq + (size_t)c * M * esz, t);
            run1(CFT_FMA, fi, t, t, acc, acc);
            run1(CFT_SUB, fi, vv + ((size_t)c * M + m) * esz, NULL,
                 vv + (size_t)c * M * esz, u);
            run1(CFT_FMA, fi, u, u, acc, acc);
        }
        if (cft_sqrt(DEV, fi->fmt, CFT_RNE, acc, out + m * esz, 1, NULL,
                     NULL) != CFT_OK)
            die("cft_sqrt failed computing a separation");
    }
}

/* Every derived constant the integration will use, as an EXACT
 * decimal - the step size, the composition weights folded into the
 * drift and kick scales, G, the masses, the pairwise products.
 *
 * This is not a debugging aid. The 300-digit oracle has to run the
 * SAME discrete scheme the tool ran, and "the same" includes the
 * constants: h is fl(2*pi/S), the drift scale is fl(fl(w*h)*0.5), and
 * an oracle that used the exact real numbers instead would be
 * measuring the constants' rounding as though it were the
 * integration's. So the tool states what it is about to compute with,
 * the same way a program image can be read back to attest what
 * executed. */
static void dump_setup(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    char dec[DECMAX];
    int s, b, j;

    printf("setup format %s\n", cft_format_name(fi->fmt));
    printf("setup precision %d\n", fi->prec);
    printf("setup newton %d\n", fi->newton);
    printf("setup problem %s\n", problem_name(O->problem));
    printf("setup scheme %s\n", scheme_name(O->scheme));
    printf("setup rsqrt %s\n", rsqrt_name(O->rsqrt));
    printf("setup bodies %d\n", R->nb);
    printf("setup dims %d\n", R->nd);
    printf("setup nsub %d\n", R->nsub);
    printf("setup members %" PRIu64 "\n", (uint64_t)O->members);
    printf("setup steps %" PRIu64 "\n", R->nsteps);
    printf("setup stride %" PRIu64 "\n", R->stride);
    printf("setup samples %" PRIu64 "\n", R->nsamples);
    val_to_dec(fi, R->s_h, dec, sizeof dec);
    printf("setup h %s\n", dec);
    for (s = 0; s < R->nsub; s++) {
        val_to_dec(fi, R->c_hd[s], dec, sizeof dec);
        printf("setup hd %d %s\n", s, dec);
        if (O->problem == PROB_KEPLER) {
            val_to_dec(fi, R->c_mg[s], dec, sizeof dec);
            printf("setup mg %d %s\n", s, dec);
        } else {
            for (b = 0; b < R->nb; b++) {
                val_to_dec(fi, R->c_hm[s][b], dec, sizeof dec);
                printf("setup hm %d %d %s\n", s, b, dec);
                val_to_dec(fi, R->c_mhm[s][b], dec, sizeof dec);
                printf("setup mhm %d %d %s\n", s, b, dec);
            }
        }
    }
    if (O->problem == PROB_KEPLER) {
        val_to_dec(fi, R->c_mu, dec, sizeof dec);
        printf("setup mu %s\n", dec);
    } else {
        val_to_dec(fi, R->c_G, dec, sizeof dec);
        printf("setup G %s\n", dec);
        for (b = 0; b < R->nb; b++) {
            val_to_dec(fi, R->c_m[b], dec, sizeof dec);
            printf("setup mass %d %s\n", b, dec);
            val_to_dec(fi, R->c_halfm[b], dec, sizeof dec);
            printf("setup halfm %d %s\n", b, dec);
        }
        for (b = 0; b < R->nb; b++)
            for (j = b + 1; j < R->nb; j++) {
                val_to_dec(fi, R->c_gmm[b][j], dec, sizeof dec);
                printf("setup gmm %d %d %s\n", b, j, dec);
            }
    }
    val_to_dec(fi, R->c_half, dec, sizeof dec);
    printf("setup half %s\n", dec);
    printf("setup end\n");
}

static void report(runstate *R, double elapsed, const char *backend)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, m;
    uint8_t worstH[MAX_ESZ], worstL[MAX_ESZ], rel[MAX_ESZ], tmp[MAX_ESZ];
    uint8_t *sep0, *sep1;
    char chain[65], sh[64], sdh[64], sdl[64], ssep[64], sgrow[64];
    /* Snapshot before this function does any arithmetic of its own:
     * what is reported is what the INTEGRATION raised. */
    uint32_t flags_run = FLAGS_SEEN, status_run = cft_save_all_flags(DEV);
    double steps_s = elapsed > 0 ? (double)R->step / elapsed : 0.0;
    double elem_s = elapsed > 0 ?
        (double)R->step * (double)M / elapsed : 0.0;
    double ops_s = elapsed > 0 ?
        (double)(N_ELEMOPS + N_COMPOSED) / elapsed : 0.0;
    int k;

    hex32(R->chain, chain);
    val_to_dec_short(fi, R->s_h, sh, sizeof sh, 12);

    /* the worst relative energy drift over the ensemble */
    max_over_members(R, R->dHmax, worstH);
    run1(CFT_ABS, fi, R->H0, NULL, NULL, tmp);
    if (cft_div(DEV, fi->fmt, CFT_RNE, worstH, tmp, rel, 1, NULL, NULL)
        != CFT_OK)
        die("cft_div failed computing the energy drift");
    val_to_dec_short(fi, rel, sdh, sizeof sdh, 6);

    memset(worstL, 0, esz);
    for (k = 0; k < R->nL; k++) {
        max_over_members(R, R->dLmax[k], tmp);
        if (val_lt(fi, worstL, tmp))
            memcpy(worstL, tmp, esz);
    }
    {
        uint8_t l0[MAX_ESZ], best[MAX_ESZ];
        memset(best, 0, esz);
        for (k = 0; k < R->nL; k++) {
            run1(CFT_ABS, fi, R->L0[k], NULL, NULL, l0);
            if (val_lt(fi, best, l0))
                memcpy(best, l0, esz);
        }
        if (cft_div(DEV, fi->fmt, CFT_RNE, worstL, best, rel, 1, NULL, NULL)
            != CFT_OK)
            die("cft_div failed computing the angular-momentum drift");
        val_to_dec_short(fi, rel, sdl, sizeof sdl, 6);
    }

    sep0 = alloc_m(R);
    sep1 = alloc_m(R);
    separations(R, R->q0, R->v0, sep0);
    separations(R, R->q, R->v, sep1);

    if (O->csv) {
        printf("backend,format,problem,scheme,rsqrt,engine,members,batch,"
               "spread,h,steps,samples,seconds,steps_per_s,elem_steps_per_s,"
               "libops_per_s,calls,elemops,composed,energy_drift,"
               "angmom_drift,flags,chain\n");
        printf("%s,%s,%s,%s,%s,%s,%" PRIu64 ",%" PRIu64 ",%" PRIu64
               ",%s,%" PRIu64 ",%" PRIu64 ",%.6f,%.1f,%.1f,%.1f,%" PRIu64
               ",%" PRIu64 ",%" PRIu64 ",%s,%s,0x%02x,%s\n",
               backend, cft_format_name(fi->fmt), problem_name(O->problem),
               scheme_name(O->scheme), rsqrt_name(O->rsqrt),
               O->engine == ENG_PROGRAM ? "program" : "loop",
               (uint64_t)M, (uint64_t)O->batch, O->spread, sh,
               R->step, R->sample, elapsed, steps_s, elem_s, ops_s,
               N_CALLS, N_ELEMOPS, N_COMPOSED, sdh, sdl,
               (unsigned)flags_run, chain);
        free(sep0); free(sep1);
        return;
    }

    printf("\n");
    printf("  backend       %s\n", backend);
    printf("  format        %s, p = %d, %d Newton passes for rsqrt\n",
           cft_format_name(fi->fmt), fi->prec, fi->newton);
    printf("  problem       %s, %d bod%s in %dD, %" PRIu64 " ensemble "
           "members\n", problem_name(O->problem), R->nb,
           R->nb == 1 ? "y" : "ies", R->nd, (uint64_t)M);
    printf("  scheme        %s (%d substep%s), 1/r^3 route %s\n",
           scheme_name(O->scheme), R->nsub, R->nsub == 1 ? "" : "s",
           rsqrt_name(O->rsqrt));
    printf("  engine        %s, batch %" PRIu64 "\n",
           O->engine == ENG_PROGRAM ? "sequencer program" : "host cft_run loop",
           (uint64_t)O->batch);
    if (O->engine == ENG_PROGRAM)
        printf("  program       %u instructions, %u deposit slots per lane\n",
               R->n_insns, R->max_deposits);
    printf("  step size     %s\n", sh);
    printf("  steps done    %" PRIu64 " of %" PRIu64 ", %" PRIu64
           " samples of %" PRIu64 "\n",
           R->step, R->nsteps, R->sample, R->nsamples);
    printf("  energy drift  %s (max |H-H0|/|H0| over the ensemble)\n", sdh);
    printf("  angmom drift  %s (max |L-L0|/|L0| over the ensemble)\n", sdl);
    printf("  separations   member: initial -> final, growth\n");
    for (m = 1; m < M && m < 5; m++) {
        uint8_t growth[MAX_ESZ];
        char si[64];
        val_to_dec_short(fi, sep0 + m * esz, si, sizeof si, 4);
        val_to_dec_short(fi, sep1 + m * esz, ssep, sizeof ssep, 4);
        if (cft_div(DEV, fi->fmt, CFT_RNE, sep1 + m * esz, sep0 + m * esz,
                    growth, 1, NULL, NULL) != CFT_OK)
            die("cft_div failed computing a separation growth");
        val_to_dec_short(fi, growth, sgrow, sizeof sgrow, 4);
        printf("                %2" PRIu64 ": %s -> %s, x%s\n",
               (uint64_t)m, si, ssep, sgrow);
    }
    if (M > 5)
        printf("                (%" PRIu64 " more; --records has them all)\n",
               (uint64_t)(M - 5));
    printf("  library calls %" PRIu64 "\n", N_CALLS);
    printf("  elementwise   %" PRIu64 " opcode issues, plus %" PRIu64
           " composed div/sqrt\n", N_ELEMOPS, N_COMPOSED);
    printf("  flags seen    0x%02x  (inexact is EXPECTED here and means "
           "nothing;\n", (unsigned)FLAGS_SEEN);
    printf("                 the other four are certificates and are "
           "checked on every call)%s\n",
           FLAGS_TRUSTED ? "" : " - NOT readable on this backend");
    printf("  status word   0x%02x%s\n", (unsigned)status_run,
           status_run == flags_run ? " (agrees with the union above)"
                                   : "  DISAGREES WITH THE UNION ABOVE");
    printf("  time          %.3f s\n", elapsed);
    printf("  throughput    %.0f steps/s, %.0f element-steps/s, "
           "%.0f library element-ops/s\n", steps_s, elem_s, ops_s);
    printf("  chain         %s\n", chain);
    printf("\n");
    free(sep0);
    free(sep1);
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-orbits - symplectic few-body integration on libcft\n"
"\n"
"  --problem kepler|outer   Kepler two-body (default), or the outer\n"
"                           solar system: Sun, Jupiter, Saturn, Uranus,\n"
"                           Neptune\n"
"  --scheme leapfrog|yoshida4   Stormer-Verlet (default), or Yoshida's\n"
"                           fourth-order composition of it\n"
"  --format fp32|fp64|fp128|fp256   default fp256\n"
"  --engine loop|program    host cft_run loop (default), or the whole\n"
"                           integration as one sequencer program\n"
"                           (kepler + --rsqrt newton only; see the\n"
"                           header for the two reasons)\n"
"  --rsqrt exact|newton     1/r^3 from cft_sqrt and cft_div, correctly\n"
"                           rounded (default), or from the tile's seed\n"
"                           opcode and a derived Newton refinement\n"
"  --members N              ensemble size (default 16)\n"
"  --spread N               ulps per rung of the perturbation ladder\n"
"                           (default 1)\n"
"  --periods P              kepler: orbits to integrate (default 16)\n"
"  --steps-per-period N     kepler: steps per orbit (default 1024)\n"
"  --years Y                outer: years to integrate (default 100)\n"
"  --days D                 outer: step size in days (default 10)\n"
"  --steps N                override the step count directly\n"
"  --sample-every N         steps between recorded samples\n"
"  --batch N                ensemble members per library call\n"
"  --checkpoint PATH        write a resumable checkpoint\n"
"  --checkpoint-interval S  seconds between checkpoints (default 10)\n"
"  --resume                 continue from --checkpoint\n"
"  --stop-after-samples N   stop cleanly after N samples this run\n"
"  --records PATH           one line per (sample, member), exact decimal\n"
"  --artifact PATH          an .xclbin; omit for the software backend\n"
"  --csv                    machine-readable summary\n"
"  --quiet                  summary only\n"
"\n"
"Inexact is EXPECTED on every call here; docs/ORBITS.md is the argument\n"
"and host/tests/orbits_check.py is the 300-digit oracle.\n");
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
    long emitted = 0;
    uint64_t steps_this_run = 0;
    int stopping = 0;
    int i, c, k;
    size_t esz;

    memset(&O, 0, sizeof O);
    O.problem = PROB_KEPLER;
    O.scheme = SCHEME_LEAPFROG;
    O.rsqrt = RSQRT_EXACT;
    O.engine = ENG_LOOP;
    O.fmt = CFT_FP256;
    O.members = 16;
    O.batch = 0;
    O.spread = 1;
    O.steps_per_period = 1024;
    O.periods = 16;
    O.days = 10;
    O.years = 100;
    O.ckpt_interval = 10.0;
    O.stop_after_samples = -1;
    O.stop_after_steps = -1;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "--problem")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "kepler")) O.problem = PROB_KEPLER;
            else if (!strcmp(val, "outer")) O.problem = PROB_OUTER;
            else die("--problem takes kepler or outer");
        } else if (!strcmp(a, "--scheme")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "leapfrog")) O.scheme = SCHEME_LEAPFROG;
            else if (!strcmp(val, "yoshida4")) O.scheme = SCHEME_YOSHIDA4;
            else die("--scheme takes leapfrog or yoshida4");
        } else if (!strcmp(a, "--rsqrt")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "exact")) O.rsqrt = RSQRT_EXACT;
            else if (!strcmp(val, "newton")) O.rsqrt = RSQRT_NEWTON;
            else die("--rsqrt takes exact or newton");
        } else if (!strcmp(a, "--engine")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "loop")) O.engine = ENG_LOOP;
            else if (!strcmp(val, "program")) O.engine = ENG_PROGRAM;
            else die("--engine takes loop or program");
        } else if (!strcmp(a, "--format")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "fp32")) O.fmt = CFT_FP32;
            else if (!strcmp(val, "fp64")) O.fmt = CFT_FP64;
            else if (!strcmp(val, "fp128")) O.fmt = CFT_FP128;
            else if (!strcmp(val, "fp256")) O.fmt = CFT_FP256;
            else die("--format takes fp32, fp64, fp128 or fp256");
        }
        else if (!strcmp(a, "--members"))
            O.members = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--batch"))
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--spread"))
            O.spread = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--periods"))
            O.periods = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--steps-per-period"))
            O.steps_per_period = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--years"))
            O.years = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--days"))
            O.days = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--steps"))
            O.steps_opt = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--sample-every"))
            O.sample_every = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--checkpoint")) O.ckpt = need(argc, argv, &i);
        else if (!strcmp(a, "--checkpoint-interval"))
            O.ckpt_interval = strtod(need(argc, argv, &i), NULL);
        else if (!strcmp(a, "--resume")) O.resume = 1;
        else if (!strcmp(a, "--stop-after-samples"))
            O.stop_after_samples = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--stop-after-steps"))
            O.stop_after_steps = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--records"))
            O.records_path = need(argc, argv, &i);
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--dump-setup")) O.dump_setup = 1;
        else if (!strcmp(a, "--csv")) O.csv = 1;
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-orbits: unknown option %s\n", a);
            return 2;
        }
    }
    if (!O.members)
        die("--members must be positive");
    if (!O.batch)
        O.batch = O.members;

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

    memset(&R, 0, sizeof R);
    R.fi = &fi;
    R.O = &O;
    esz = fi.esz;
    R.nb = O.problem == PROB_KEPLER ? 1 : N_OUTER;
    R.nd = O.problem == PROB_KEPLER ? 2 : 3;
    R.ncomp = R.nb * R.nd;
    R.nL = O.problem == PROB_KEPLER ? 1 : 3;

    /* --- the schedule --- */
    if (O.steps_opt)
        R.nsteps = O.steps_opt;
    else if (O.problem == PROB_KEPLER)
        R.nsteps = O.periods * O.steps_per_period;
    else
        R.nsteps = (O.years * 36525ull) / (100ull * O.days);
    if (!R.nsteps)
        die("that is a run of zero steps");
    R.stride = O.sample_every;
    if (!R.stride)
        R.stride = O.problem == PROB_KEPLER ? O.steps_per_period
                                            : (36525ull / (100ull * O.days)
                                               ? 36525ull / (100ull * O.days)
                                               : 1);
    if (!R.stride)
        R.stride = 1;
    if (R.stride > R.nsteps)
        R.stride = R.nsteps;
    R.nsamples = R.nsteps / R.stride;
    if (!R.nsamples)
        die("--sample-every is larger than the run");
    R.nsteps = R.nsamples * R.stride;   /* an exact number of samples */

    if (O.engine == ENG_PROGRAM) {
        if (O.problem != PROB_KEPLER)
            die("--engine program cannot run --problem outer: a lane's "
                "state is 30 values and cft_program_run initialises three "
                "registers (docs/ORBITS.md, \"Where the step runs\")");
        if (O.rsqrt != RSQRT_NEWTON)
            die("--engine program needs --rsqrt newton: the correctly "
                "rounded route is host-prep, program core, host finish "
                "(python/cft_golden/seqprogs.py) and cannot sit inside "
                "another program's loop body");
        if (O.resume)
            die("--engine program cannot resume into the middle of a run: "
                "a restart state has four non-zero components and only "
                "three registers can be loaded");
        if (R.nsamples > 0xffffffffull || R.stride > 0xffffffffull)
            die("that run does not fit the sequencer's 32-bit trip counts");
    }

    /* --- allocation --- */
    R.q = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.v = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.q0 = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.v0 = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    for (k = 0; k < MAX_DIM; k++)
        R.d[k] = alloc_m(&R);
    R.x = alloc_m(&R); R.y = alloc_m(&R); R.w = alloc_m(&R);
    R.e = alloc_m(&R); R.z = alloc_m(&R); R.g = alloc_m(&R);
    R.t1 = alloc_m(&R); R.t2 = alloc_m(&R); R.acc = alloc_m(&R);
    R.H0 = alloc_m(&R); R.Hd = alloc_m(&R); R.dHmax = alloc_m(&R);
    for (k = 0; k < 3; k++) {
        R.L0[k] = alloc_m(&R);
        R.Ld[k] = alloc_m(&R);
        R.dLmax[k] = alloc_m(&R);
    }

    setup_constants(&R);
    setup_state(&R);
    memcpy(R.q0, R.q, (size_t)R.ncomp * O.members * esz);
    memcpy(R.v0, R.v, (size_t)R.ncomp * O.members * esz);

    /* Building the constants and the initial condition deliberately
     * rounds; 754-2019 7.1 says a status flag is lowered only at the
     * user's request, and this is that request. From here the word
     * holds what the INTEGRATION raised, which the report
     * cross-checks against the union of the calls' flags_out. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);
    FLAGS_SEEN = 0;

    if (O.dump_setup) {
        dump_setup(&R);
        cft_close(DEV);
        return 0;
    }

    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R);
    }
    if (O.records_path) {
        R.recf = fopen(O.records_path, O.resume ? "ab" : "wb");
        if (!R.recf)
            die("cannot write the records file");
    }

    if (!O.quiet && !O.csv)
        printf("cft-orbits: %s backend, %s, p = %d, %s, %s, %s engine\n",
               caps.backend, cft_format_name(fi.fmt), fi.prec,
               problem_name(O.problem), scheme_name(O.scheme),
               O.engine == ENG_PROGRAM ? "sequencer-program" : "host-loop");

    t0 = now_s();
    tckpt = t0;

    if (O.engine == ENG_PROGRAM) {
        size_t bytes = 0, M = O.members, m, chunk;
        uint8_t *img = build_program(&R, &bytes);
        uint8_t *qs, *vs;
        uint64_t s;
        st = cft_program_load(DEV, img, bytes, &R.prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load", st);
        R.dep = (uint8_t *)xcalloc(M * R.max_deposits, esz);
        R.depcount = (uint32_t *)xcalloc(M, sizeof(uint32_t));
        for (chunk = 0; chunk < M; chunk += O.batch) {
            size_t n = M - chunk < O.batch ? M - chunk : O.batch;
            uint32_t fl = 0, bus = 0;
            st = cft_program_run(R.prog, CQ(&R, 0) + chunk * esz,
                                 CV(&R, 1) + chunk * esz, NULL,
                                 R.dep + (size_t)chunk * R.max_deposits * esz,
                                 R.depcount + chunk, n, &fl, &bus);
            if (st != CFT_OK)
                die_st("cft_program_run", st);
            if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
                die("the deposit buffer overflowed - the program is wrong");
            note_flags(fl, "the sequencer program");
            N_CALLS++;
            /* the ALU issues a lane actually performed - the same
             * count the host loop makes for the same step, which is
             * what lets the two throughputs be compared */
            N_ELEMOPS += (uint64_t)n * R.nsteps * R.alu_per_step;
        }
        for (m = 0; m < M; m++)
            if (R.depcount[m] != R.max_deposits)
                die("a lane deposited the wrong number of values");
        /* Replay the deposits in (sample, member) order, computing the
         * invariants with the same host routine the loop engine uses,
         * so the two engines' records are the same bytes. */
        qs = (uint8_t *)xcalloc((size_t)R.ncomp * M, esz);
        vs = (uint8_t *)xcalloc((size_t)R.ncomp * M, esz);
        for (s = 0; s <= R.nsamples; s++) {
            for (m = 0; m < M; m++) {
                const uint8_t *d = R.dep +
                    ((size_t)m * R.max_deposits +
                     (size_t)s * DEPOSITS_PER_SAMPLE) * esz;
                memcpy(qs + (0 * M + m) * esz, d + 0 * esz, esz);
                memcpy(qs + (1 * M + m) * esz, d + 1 * esz, esz);
                memcpy(vs + (0 * M + m) * esz, d + 2 * esz, esz);
                memcpy(vs + (1 * M + m) * esz, d + 3 * esz, esz);
            }
            emit_sample(&R, s, s * R.stride, qs, vs);
            R.sample = s;
            R.step = s * R.stride;
        }
        memcpy(R.q, qs, (size_t)R.ncomp * M * esz);
        memcpy(R.v, vs, (size_t)R.ncomp * M * esz);
        free(qs);
        free(vs);
    } else {
        /* Sample 0 is the initial state. A checkpoint is only ever
         * written after it has been emitted, so a resume must not
         * emit it again. */
        if (!O.resume)
            emit_sample(&R, 0, 0, R.q, R.v);
        while (R.sample < R.nsamples && !stopping) {
            /* The checkpoint is STEP-granular, not sample-granular:
             * the ensemble state is complete after every step, so a
             * checkpoint may be taken between any two of them and a
             * resume picks up part way through a sample interval.
             * That is what makes an interruption cost at most one
             * --checkpoint-interval of work however coarse the
             * sampling is, and it is what the resume test in
             * host/tests/orbits_check.py exercises. */
            uint64_t upto = (R.sample + 1) * R.stride;
            while (R.step < upto) {
                one_step(&R);
                R.step++;
                steps_this_run++;
                if (O.ckpt && now_s() - tckpt >= O.ckpt_interval) {
                    ckpt_write(&R);
                    tckpt = now_s();
                }
                if (O.stop_after_steps >= 0 &&
                    steps_this_run >= (uint64_t)O.stop_after_steps) {
                    stopping = 1;
                    break;
                }
            }
            if (stopping)
                break;
            R.sample++;
            emit_sample(&R, R.sample, R.step, R.q, R.v);
            emitted++;
            if (O.ckpt && now_s() - tckpt >= O.ckpt_interval) {
                ckpt_write(&R);
                tckpt = now_s();
            }
            if (O.stop_after_samples >= 0 && emitted >= O.stop_after_samples)
                break;
        }
    }
    elapsed = now_s() - t0;
    if (O.ckpt)
        ckpt_write(&R);
    if (R.recf)
        fclose(R.recf);

    report(&R, elapsed, caps.backend);

    for (c = 0; c < MAX_DIM; c++)
        free(R.d[c]);
    free(R.q); free(R.v); free(R.q0); free(R.v0);
    free(R.x); free(R.y); free(R.w); free(R.e); free(R.z); free(R.g);
    free(R.t1); free(R.t2); free(R.acc);
    free(R.H0); free(R.Hd); free(R.dHmax);
    for (k = 0; k < 3; k++) { free(R.L0[k]); free(R.Ld[k]); free(R.dLmax[k]); }
    free(R.dep);
    free(R.depcount);
    if (R.prog)
        cft_program_free(R.prog);
    cft_close(DEV);
    return 0;
}
