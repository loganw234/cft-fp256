/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * perm_check.c - a keyed Feistel permutation as a way to ENUMERATE a space without
 * repeating (parcel SC's study, "non-repeating enumeration").
 *
 * The idea: number the cases i = 0 .. N-1 and let operands(i) = perm_key(i), a
 * keyed bijection of the whole space. Then
 *   - the cases of any index interval [lo, hi) are pairwise distinct (exact counts),
 *   - an interval is a RANGE of one integer pair (lo, hi): resumable, mergeable, shardable,
 *   - perm is stateless: a device starts anywhere with no jump-ahead,
 *   - any prefix looks like a uniform random sample WITHOUT replacement.
 *
 * The permutation tested: a balanced Feistel network on 2w bits, round
 *   (L, R) -> (R, L xor F(R, k_j)),   F(x, k) = finalizer(x xor k) truncated to w bits,
 * the finalizer being the 32-bit (w <= 32) or the 64-bit (w > 32) multiply-xorshift mixer
 * of the MurmurHash3 family (the constants are written below; any odd multipliers give a
 * bijective mixer, and what is tested here is its QUALITY, not its provenance). Round
 * keys come from splitmix64 of the key. A Feistel network is a bijection whatever F is
 * (it is inverted by running the rounds backwards), so bijectivity is structural; the
 * exhaustive tests below confirm the implementation, and they catch a broken round.
 *
 * Tests (all on this machine's CPU; times are what they are):
 *   B  bijectivity by EXHAUSTION at w = 4, 8, 12, 14 and 16 (2^32 outputs, a 512 MiB bitmap),
 *      the inverse round trip at each, and a PLANTED broken round that must collide
 *   Q  statistical quality of perm(i) for sequential i at 64 bits, for 1, 2, 3, 4, 6 and 8
 *      rounds: bit balance, the 64 x 64 avalanche matrix, the top-12-bit histogram, serial
 *      correlation. One round must FAIL (the tests can fail), six must pass
 *   C  cycle walking onto a range N that is not a power of four: exact bijection on
 *      [0, N), the mean number of walks
 *   A  coverage accounting: the first K indices give exactly K distinct values; two index
 *      ranges give disjoint sets (sharding)
 *   S  speed: nanoseconds a permutation at 64 bits (4, 6, 8 rounds) and at 128 bits
 *   V  test vectors, printed for perm_check.py (an independent implementation) to reproduce
 *
 * usage: perm_check [all | B | Q | C | A | S | V]
 * Exit status 0 only if every CHECK held.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int fails;

#define CHECK(label, ok, ...)                                                   \
    do {                                                                        \
        int ok_ = (ok);                                                         \
        printf("CHECK %-84s %s ", label, ok_ ? "ok" : "FAILED");                \
        printf("" __VA_ARGS__);                                                 \
        printf("\n");                                                           \
        if (!ok_) fails++;                                                      \
    } while (0)

/* ---- mixers ---------------------------------------------------------- */

static uint32_t fmix32(uint32_t h)
{
    h ^= h >> 16;
    h *= 0x85ebca6bu;
    h ^= h >> 13;
    h *= 0xc2b2ae35u;
    h ^= h >> 16;
    return h;
}

static uint64_t fmix64(uint64_t h)
{
    h ^= h >> 33;
    h *= 0xff51afd7ed558ccdull;
    h ^= h >> 33;
    h *= 0xc4ceb9fe1a85ec53ull;
    h ^= h >> 33;
    return h;
}

static uint64_t splitmix64(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* ---- the Feistel permutation ------------------------------------------ */

typedef struct {
    int w;            /* half width in bits, 1 .. 64 */
    int rounds;
    uint64_t k[32];
    int broken;       /* a PLANTED defect: the round function reads the wrong half */
} feistel;

static void fe_init(feistel *f, int w, int rounds, uint64_t key)
{
    uint64_t s = key;
    int j;
    f->w = w;
    f->rounds = rounds;
    f->broken = 0;
    for (j = 0; j < rounds; j++)
        f->k[j] = splitmix64(&s);
}

static uint64_t wmask(int w) { return w >= 64 ? ~0ull : ((1ull << w) - 1); }

static uint64_t F(const feistel *f, uint64_t x, int j)
{
    if (f->w <= 32)
        return (uint64_t)fmix32((uint32_t)(x ^ f->k[j])) & wmask(f->w);
    return fmix64(x ^ f->k[j]) & wmask(f->w);
}

/* 2w <= 64 */
static uint64_t fe_perm(const feistel *f, uint64_t i)
{
    uint64_t m = wmask(f->w), L = (i >> f->w) & m, R = i & m;
    int j;
    for (j = 0; j < f->rounds; j++) {
        uint64_t t = L ^ F(f, f->broken ? L : R, j);
        L = R;
        R = t;
    }
    return (L << f->w) | R;
}

static uint64_t fe_inv(const feistel *f, uint64_t y)
{
    uint64_t m = wmask(f->w), L = (y >> f->w) & m, R = y & m;
    int j;
    for (j = f->rounds - 1; j >= 0; j--) {
        uint64_t t = R ^ F(f, L, j);
        R = L;
        L = t;
    }
    return (L << f->w) | R;
}

/* 128 bits: two 64-bit halves */
static void fe_perm128(const feistel *f, uint64_t *hi, uint64_t *lo)
{
    uint64_t L = *hi, R = *lo;
    int j;
    for (j = 0; j < f->rounds; j++) {
        uint64_t t = L ^ fmix64(R ^ f->k[j]);
        L = R;
        R = t;
    }
    *hi = L;
    *lo = R;
}

static void fe_inv128(const feistel *f, uint64_t *hi, uint64_t *lo)
{
    uint64_t L = *hi, R = *lo;
    int j;
    for (j = f->rounds - 1; j >= 0; j--) {
        uint64_t t = R ^ fmix64(L ^ f->k[j]);
        R = L;
        L = t;
    }
    *hi = L;
    *lo = R;
}

/* cycle walking: a bijection of [0, N) from a bijection of [0, 4^w) with 4^w >= N */
static uint64_t cw_perm(const feistel *f, uint64_t N, uint64_t i, uint64_t *walks)
{
    uint64_t x = i;
    do {
        x = fe_perm(f, x);
        if (walks) (*walks)++;
    } while (x >= N);
    return x;
}

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

/* ---- B: bijectivity ------------------------------------------------------ */

static uint64_t count_distinct(const feistel *f, int two_w, uint64_t K)
{
    uint64_t bits = 1ull << two_w, i, distinct = 0;
    uint8_t *bm = calloc((size_t)(bits / 8 + 1), 1);
    (void)bits;
    if (!bm) { printf("out of memory\n"); exit(2); }
    for (i = 0; i < K; i++) {
        uint64_t y = fe_perm(f, i);
        if (!(bm[y >> 3] & (1u << (y & 7)))) {
            bm[y >> 3] |= (uint8_t)(1u << (y & 7));
            distinct++;
        }
    }
    free(bm);
    return distinct;
}

static void test_B(void)
{
    static const int ws[] = { 4, 8, 12, 14, 16 };
    size_t t;
    printf("\n== B. bijectivity by exhaustion\n");
    printf("   (a bitmap of the outputs where it stays in cache, w <= 12; and for every w the left-inverse test: if\n"
           "    inverse(perm(i)) == i for ALL i of a finite domain, perm is injective, hence a bijection)\n");
    for (t = 0; t < sizeof ws / sizeof ws[0]; t++) {
        int w = ws[t], two_w = 2 * w, R;
        uint64_t N = 1ull << two_w, i, bad;
        if (w <= 12) {
            for (R = 1; R <= 6; R++) {
                feistel f;
                double t0 = now_s();
                uint64_t d;
                char lab[128];
                fe_init(&f, w, R, 0x1234567812345678ull + (uint64_t)w);
                d = count_distinct(&f, two_w, N);
                snprintf(lab, sizeof lab, "w=%2d (2^%d inputs), %d round(s): all outputs distinct", w, two_w, R);
                CHECK(lab, d == N, "(%llu of %llu, %.1f s)", (unsigned long long)d, (unsigned long long)N, now_s() - t0);
            }
        }
        {
            feistel f;
            char lab[128];
            double t0 = now_s();
            fe_init(&f, w, 6, 0xABCDEF0123456789ull + (uint64_t)w);
            bad = 0;
            for (i = 0; i < N; i++)
                if (fe_inv(&f, fe_perm(&f, i)) != i) bad++;
            snprintf(lab, sizeof lab, "w=%2d (2^%d inputs), 6 rounds: inverse(perm(i)) == i for EVERY i", w, two_w);
            CHECK(lab, bad == 0, "(%llu failures, %.1f s)", (unsigned long long)bad, now_s() - t0);
        }
    }
    {   /* the plants: a broken round must collide, and must fail the round trip */
        feistel f;
        uint64_t d, N = 1ull << 24, i, bad = 0;
        fe_init(&f, 12, 6, 99);
        f.broken = 1;
        d = count_distinct(&f, 24, N);
        CHECK("PLANT: a round that reads the wrong half is NOT a bijection at w=12 (collisions found)", d < N,
              "(%llu distinct of %llu)", (unsigned long long)d, (unsigned long long)N);
        fe_init(&f, 8, 6, 99);
        f.broken = 1;
        for (i = 0; i < (1ull << 16); i++)
            if (fe_inv(&f, fe_perm(&f, i)) != i) bad++;
        CHECK("PLANT: the same broken round fails inverse(perm(i)) == i at w=8", bad > 0, "(%llu failures of 65,536)", (unsigned long long)bad);
    }
}

/* ---- Q: statistical quality ------------------------------------------------ */

typedef struct { double maxz_bits, maxz_aval, chi_z, corr_z; } quality;

static uint64_t rng_s = 0x0DDBA11CAFEF00Dull;
static uint64_t rnd64(void) { return splitmix64(&rng_s); }

static quality measure(const feistel *f)
{
    quality q;
    const uint64_t N = 1ull << 22;
    uint64_t ones[64] = { 0 }, i;
    uint32_t hist[4096] = { 0 };
    double sx = 0, sy = 0, sxy = 0, sxx = 0, syy = 0, prev = 0, mean_n = (double)N;
    int j, k;
    for (i = 0; i < N; i++) {
        uint64_t y = fe_perm(f, i);
        double u = (double)(y >> 11) / 9007199254740992.0;   /* a uniform in [0, 1) */
        for (j = 0; j < 64; j++) ones[j] += (y >> j) & 1;
        hist[y >> 52]++;
        if (i) { sx += prev; sy += u; sxy += prev * u; sxx += prev * prev; syy += u * u; }
        prev = u;
    }
    q.maxz_bits = 0;
    for (j = 0; j < 64; j++) {
        double z = fabs((double)ones[j] - mean_n / 2) / sqrt(mean_n / 4);
        if (z > q.maxz_bits) q.maxz_bits = z;
    }
    {
        double chi = 0, e = mean_n / 4096.0;
        for (j = 0; j < 4096; j++) chi += ((double)hist[j] - e) * ((double)hist[j] - e) / e;
        q.chi_z = fabs(chi - 4095.0) / sqrt(2 * 4095.0);
    }
    {
        double n = mean_n - 1, cov = sxy / n - (sx / n) * (sy / n);
        double vx = sxx / n - (sx / n) * (sx / n), vy = syy / n - (sy / n) * (sy / n);
        double r = cov / sqrt(vx * vy);
        q.corr_z = fabs(r) * sqrt(n);
    }
    {   /* avalanche: flip input bit j; each output bit should change with probability 1/2 */
        const int M = 20000;
        static uint32_t flip[64][64];
        double maxz = 0;
        memset(flip, 0, sizeof flip);
        for (i = 0; i < (uint64_t)M; i++) {
            uint64_t x = rnd64(), y0 = fe_perm(f, x);
            for (j = 0; j < 64; j++) {
                uint64_t d = y0 ^ fe_perm(f, x ^ (1ull << j));
                for (k = 0; k < 64; k++) flip[j][k] += (d >> k) & 1;
            }
        }
        for (j = 0; j < 64; j++)
            for (k = 0; k < 64; k++) {
                double z = fabs((double)flip[j][k] - M / 2.0) / sqrt(M / 4.0);
                if (z > maxz) maxz = z;
            }
        q.maxz_aval = maxz;
    }
    return q;
}

static void test_Q(void)
{
    static const int rs[] = { 1, 2, 3, 4, 6, 8 };
    size_t t;
    quality res[6];
    printf("\n== Q. quality of perm(i), i = 0 .. 2^22 - 1, at 64 bits (w = 32); thresholds are z-scores\n");
    printf("   %-7s %12s %12s %12s %12s   %s\n", "rounds", "bit balance", "avalanche", "top-12 hist", "serial corr", "verdict");
    for (t = 0; t < sizeof rs / sizeof rs[0]; t++) {
        feistel f;
        int pass;
        fe_init(&f, 32, rs[t], 0xC0FFEE1234567ull);
        res[t] = measure(&f);
        pass = res[t].maxz_bits < 5.0 && res[t].maxz_aval < 5.6 && res[t].chi_z < 5.0 && res[t].corr_z < 5.0;
        printf("   %-7d %12.2f %12.2f %12.2f %12.2f   %s\n", rs[t], res[t].maxz_bits, res[t].maxz_aval, res[t].chi_z,
               res[t].corr_z, pass ? "PASS" : "fail");
    }
    printf("   (bit balance: max over 64 bits of |ones - N/2| / sd; avalanche: max over 64 x 64 input-output bit pairs of\n"
           "    |flips - M/2| / sd, M = 20,000; top-12 hist: |chi-square - df| / sd of 4,096 bins; serial: |r| sqrt(N-1))\n");
    CHECK("one round FAILS the quality tests (the tests can fail)",
          !(res[0].maxz_bits < 5.0 && res[0].maxz_aval < 5.6 && res[0].chi_z < 5.0 && res[0].corr_z < 5.0));
    CHECK("two rounds fail the avalanche test", res[1].maxz_aval >= 5.6, "(z = %.1f)", res[1].maxz_aval);
    CHECK("four rounds pass every test", res[3].maxz_bits < 5.0 && res[3].maxz_aval < 5.6 && res[3].chi_z < 5.0 && res[3].corr_z < 5.0,
          "(%.2f %.2f %.2f %.2f)", res[3].maxz_bits, res[3].maxz_aval, res[3].chi_z, res[3].corr_z);
    CHECK("six and eight rounds pass every test", res[4].maxz_aval < 5.6 && res[5].maxz_aval < 5.6 && res[4].chi_z < 5.0 && res[5].chi_z < 5.0 &&
                                                   res[4].maxz_bits < 5.0 && res[5].maxz_bits < 5.0 && res[4].corr_z < 5.0 && res[5].corr_z < 5.0);
}

/* ---- C: cycle walking -------------------------------------------------------- */

static void test_C(void)
{
    feistel f;
    uint64_t N = 3000000, i, d = 0, walks = 0, bad = 0, maxv = 0;
    uint8_t *bm = calloc((N + 7) / 8, 1);
    printf("\n== C. cycle walking onto a range that is not a power of four\n");
    fe_init(&f, 11, 6, 0xBEEF);            /* the domain 4^11 = 4,194,304 */
    for (i = 0; i < N; i++) {
        uint64_t y = cw_perm(&f, N, i, &walks);
        if (y >= N) { bad++; continue; }
        if (y > maxv) maxv = y;
        if (!(bm[y >> 3] & (1u << (y & 7)))) { bm[y >> 3] |= (uint8_t)(1u << (y & 7)); d++; }
    }
    free(bm);
    CHECK("N = 3,000,000 inside the domain 4^11: every output is in [0, N)", bad == 0, "(%llu outside)", (unsigned long long)bad);
    CHECK("N = 3,000,000: all N outputs distinct, a bijection of [0, N)", d == N, "(%llu distinct)", (unsigned long long)d);
    CHECK("the mean number of permutation calls an index is near 4^11 / N = 1.398",
          fabs((double)walks / N - 4194304.0 / N) < 0.02, "(%.4f)", (double)walks / N);
    {   /* a planted clamp instead of walking: min(y, N-1) collides */
        uint64_t dd = 0;
        uint8_t *bm2 = calloc((N + 7) / 8, 1);
        for (i = 0; i < N; i++) {
            uint64_t y = fe_perm(&f, i);
            if (y >= N) y = N - 1;
            if (!(bm2[y >> 3] & (1u << (y & 7)))) { bm2[y >> 3] |= (uint8_t)(1u << (y & 7)); dd++; }
        }
        free(bm2);
        CHECK("PLANT: clamping out-of-range outputs instead of walking loses cases (not a bijection)", dd < N,
              "(%llu distinct of %llu)", (unsigned long long)dd, (unsigned long long)N);
    }
}

/* ---- A: coverage accounting and sharding ----------------------------------------- */

static void test_A(void)
{
    feistel f;
    static const uint64_t Ks[] = { 1, 100, 1000000, 8000000, 16777216 };
    size_t t;
    uint64_t i;
    printf("\n== A. coverage accounting: the first K indices give exactly K distinct cases; shards are disjoint\n");
    fe_init(&f, 12, 6, 0x5EED);             /* 2^24 cases */
    for (t = 0; t < sizeof Ks / sizeof Ks[0]; t++) {
        uint64_t d = count_distinct(&f, 24, Ks[t]);
        char lab[96];
        snprintf(lab, sizeof lab, "indices [0, %llu): distinct cases", (unsigned long long)Ks[t]);
        CHECK(lab, d == Ks[t], "(%llu)", (unsigned long long)d);
    }
    {   /* two device shards by index range: [0, 1e6) and [1e6, 3e6) */
        uint8_t *bm = calloc((1ull << 24) / 8 + 1, 1);
        uint64_t overlap = 0, a = 0, b = 0;
        for (i = 0; i < 1000000; i++) { uint64_t y = fe_perm(&f, i); bm[y >> 3] |= (uint8_t)(1u << (y & 7)); a++; }
        for (i = 1000000; i < 3000000; i++) {
            uint64_t y = fe_perm(&f, i);
            if (bm[y >> 3] & (1u << (y & 7))) overlap++;
            b++;
        }
        free(bm);
        CHECK("two device shards, index ranges [0, 1e6) and [1e6, 3e6): the case sets are disjoint", overlap == 0,
              "(%llu shared of %llu + %llu)", (unsigned long long)overlap, (unsigned long long)a, (unsigned long long)b);
    }
    {   /* a PLANT: two shards that overlap in INDEX must overlap in cases - the check sees it */
        uint8_t *bm = calloc((1ull << 24) / 8 + 1, 1);
        uint64_t overlap = 0;
        for (i = 0; i < 1000000; i++) { uint64_t y = fe_perm(&f, i); bm[y >> 3] |= (uint8_t)(1u << (y & 7)); }
        for (i = 900000; i < 2000000; i++) { uint64_t y = fe_perm(&f, i); if (bm[y >> 3] & (1u << (y & 7))) overlap++; }
        free(bm);
        CHECK("PLANT: shards [0, 1e6) and [9e5, 2e6) share exactly their 100,000 common indices", overlap == 100000,
              "(%llu shared)", (unsigned long long)overlap);
    }
}

/* ---- S: speed ---------------------------------------------------------------- */

static void test_S(void)
{
    static const int rs[] = { 4, 6, 8 };
    size_t t;
    const uint64_t N = 1ull << 26;
    uint64_t i, acc = 0;
    printf("\n== S. speed, this CPU, one core, gcc -O2 (see the study for the machine)\n");
    for (t = 0; t < sizeof rs / sizeof rs[0]; t++) {
        feistel f;
        double t0, dt;
        fe_init(&f, 32, rs[t], 1);
        t0 = now_s();
        for (i = 0; i < N; i++) acc ^= fe_perm(&f, i);
        dt = now_s() - t0;
        printf("   64-bit domain, %d rounds : %6.2f ns a permutation (%5.1f M/s)   [%llx]\n", rs[t], dt * 1e9 / N, N / dt / 1e6,
               (unsigned long long)(acc & 0xffff));
    }
    {
        feistel f;
        double t0, dt;
        uint64_t hi = 1, lo = 2;
        fe_init(&f, 64, 6, 1);
        t0 = now_s();
        for (i = 0; i < N; i++) { hi += i; fe_perm128(&f, &hi, &lo); }
        dt = now_s() - t0;
        printf("   128-bit domain, 6 rounds : %6.2f ns a permutation (%5.1f M/s)   [%llx]\n", dt * 1e9 / N, N / dt / 1e6,
               (unsigned long long)((hi ^ lo) & 0xffff));
    }
    {   /* the fastest item's per-case time, for scale */
        printf("   for scale: the fastest sweep item (class32 exhaustive on the quad) ran 33.6 M cases/s a tile: %.1f ns a case\n",
               1e3 / 33.591);
    }
}

/* ---- V: vectors for the independent implementation ------------------------------- */

static void test_V(void)
{
    static const uint64_t keys[] = { 0, 1, 0xDEADBEEFCAFEF00Dull, 0xFFFFFFFFFFFFFFFFull };
    size_t t;
    int n;
    uint64_t s = 12345;
    printf("\n== V. vectors (for perm_check.py)\n");
    for (t = 0; t < sizeof keys / sizeof keys[0]; t++) {
        feistel f64, f46, f128;
        fe_init(&f64, 32, 6, keys[t]);
        fe_init(&f46, 23, 5, keys[t]);
        fe_init(&f128, 64, 6, keys[t]);
        for (n = 0; n < 8; n++) {
            uint64_t i = splitmix64(&s), i46 = i & ((1ull << 46) - 1), hi = splitmix64(&s), lo = splitmix64(&s);
            uint64_t o64 = fe_perm(&f64, i), o46 = fe_perm(&f46, i46), h2 = hi, l2 = lo;
            uint64_t walks = 0, cw = cw_perm(&f46, 50000000000000ull, i46 % 50000000000000ull, &walks);
            fe_perm128(&f128, &h2, &l2);
            printf("VEC64 key=%016llx i=%016llx out=%016llx\n", (unsigned long long)keys[t], (unsigned long long)i, (unsigned long long)o64);
            printf("VEC46 key=%016llx i=%012llx out=%012llx\n", (unsigned long long)keys[t], (unsigned long long)i46, (unsigned long long)o46);
            printf("VEC128 key=%016llx i=%016llx%016llx out=%016llx%016llx\n", (unsigned long long)keys[t], (unsigned long long)hi,
                   (unsigned long long)lo, (unsigned long long)h2, (unsigned long long)l2);
            printf("VECCW key=%016llx n=50000000000000 i=%014llu out=%014llu\n", (unsigned long long)keys[t],
                   (unsigned long long)(i46 % 50000000000000ull), (unsigned long long)cw);
        }
    }
    {   /* round trips at 64 and 128 bits on random inputs */
        feistel f64, f128;
        uint64_t bad64 = 0, bad128 = 0, k;
        fe_init(&f64, 32, 6, 7);
        fe_init(&f128, 64, 6, 7);
        for (k = 0; k < 5000000; k++) {
            uint64_t x = splitmix64(&s), hi = splitmix64(&s), lo = splitmix64(&s), h2 = hi, l2 = lo;
            if (fe_inv(&f64, fe_perm(&f64, x)) != x) bad64++;
            fe_perm128(&f128, &h2, &l2);
            fe_inv128(&f128, &h2, &l2);
            if (h2 != hi || l2 != lo) bad128++;
        }
        CHECK("5,000,000 random round trips inverse(perm(x)) == x at 64 bits", bad64 == 0, "(%llu)", (unsigned long long)bad64);
        CHECK("5,000,000 random round trips inverse(perm(x)) == x at 128 bits", bad128 == 0, "(%llu)", (unsigned long long)bad128);
    }
}

int main(int argc, char **argv)
{
    const char *what = argc > 1 ? argv[1] : "all";
    int all = !strcmp(what, "all");
    if (all || !strcmp(what, "B")) test_B();
    if (all || !strcmp(what, "Q")) test_Q();
    if (all || !strcmp(what, "C")) test_C();
    if (all || !strcmp(what, "A")) test_A();
    if (all || !strcmp(what, "S")) test_S();
    if (all || !strcmp(what, "V")) test_V();
    printf("\nperm_check.c: %s\n", fails ? "SOME CHECK FAILED" : "every CHECK held");
    return fails ? 1 : 0;
}
