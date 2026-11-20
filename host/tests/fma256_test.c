/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * fma256test - the GPU backend's fixed tier (round 3's G3A) held to
 * libcft's arithmetic on a HOST, with no GPU (make fma256test):
 *
 *     fma256-test [N [SEED]]          (default 200000 cases, seed 1)
 *
 * src/fma256_fixed.h and tools/fx256_stream.h are CFT_HD and need no GPU,
 * so the fixed tier's lane (fx256_steer, then fx256_fma_lane) and the
 * generic tier's (cft_sf_compute) run here on the same cases, compared
 * lane by lane, results and flags, as hip-fmadiff compares them on a GPU:
 *
 *   1. fx256_matches holds the header's typed-in constants to the format
 *      table: 1 for cft_sf_formats[3], 0 for the other three, and 0 for
 *      binary256's descriptor with any one of its eight fields moved;
 *   2. fx256_steer, the byte steering, against softfloat.c's own sf_steer
 *      on cft_bn over every triple of a pool of specials and values, at
 *      FMA, ADD, SUB and MUL and at every other opcode (both refuse);
 *   3. both streams (study, GPU-A's nine families; edge, the five classes
 *      after them), FMA and the three steered operations, N cases each:
 *      0 lanes differing, and the study stream's sums at seed 1 and
 *      200000 cases equal to GPU-A's CPU line (docs/studies/gpu-a/
 *      captured/desktop-checks.txt), the anchor of the move.
 *
 * bigint.c, softfloat.c and sha256.c are the tree's own text, included and
 * compiled with libcft's C flags, so the generic lane IS libcft's
 * cft_sf_compute and sf_steer is reachable (it is static). gcc does not
 * know `#pragma unroll`: host/Makefile adds -Wno-unknown-pragmas for this
 * file alone, and the header's loops are then simply not unrolled. The
 * last line counts the checks; exit 0 only when none failed.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../src/bigint.c"
#include "../src/softfloat.c"
#include "../src/fma256_fixed.h"
#include "../tools/fx256_stream.h"
#include "../src/sha256.c"

/* sha256.c's public one-shot cft_sha256 (which this test does not call)
 * clears libcft's error slot first, device.c's cft_clear_error; no libcft.a
 * is linked here, so this stands in for it. */
void cft_clear_error(void)
{
}

static long checks, failures;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        checks++;                                                        \
        if (!(cond)) {                                                   \
            failures++;                                                  \
            if (failures <= 20) {                                        \
                printf("  FAIL: ");                                      \
                printf(__VA_ARGS__);                                     \
                printf("\n");                                            \
            }                                                            \
        }                                                                \
    } while (0)

static double secs(clock_t t0)
{
    return (double)(clock() - t0) / CLOCKS_PER_SEC;
}

/* ---- 1. the constants against the table ------------------------------- */

static void test_matches(void)
{
    cft_fmt_desc d;
    int k, f, m;
    for (f = 0; f < 4; f++)
        CHECK(fx256_matches(&cft_sf_formats[f]) == (f == 3), "fx256_matches(%s) is %d",
              cft_sf_formats[f].name, fx256_matches(&cft_sf_formats[f]));
    for (k = 0; k < 8; k++) {
        d = cft_sf_formats[3];
        switch (k) {
        case 0: d.exp_w++; break;
        case 1: d.man_w--; break;
        case 2: d.width--; break;
        case 3: d.prec++; break;
        case 4: d.bias--; break;
        case 5: d.emax++; break;
        case 6: d.emin--; break;
        default: d.exp_mask >>= 1; break;
        }
        m = fx256_matches(&d);
        CHECK(m == 0, "fx256_matches with field %d of binary256 moved answers %d", k, m);
    }
    printf("  fx256_matches: 1 for fp256, 0 for fp32, fp64, fp128 and for each of fp256's "
           "eight fields moved\n");
}

/* ---- 2. the byte steering against sf_steer ---------------------------- */

enum { NPOOL = 26 };

static void pool_elem(int k, uint8_t *e)
{
    uint32_t w[8];
    uint64_t s = 0x1234567ull + (uint64_t)k * 0x9E3779B97F4A7C15ull;
    int i;
    for (i = 0; i < 8; i++) w[i] = 0;
    if (k < 16) {                    /* the stream's sixteen specials, by index */
        const uint32_t sg = (uint32_t)k & 1u;
        switch (k >> 1) {
        case 0: break;
        case 1: w[7] = 0x7FFFF000u; break;
        case 2: w[7] = sg ? 0x7FFFF000u : 0x7FFFF800u; w[0] = 1; break;
        case 3: w[7] = (uint32_t)FX256_BIAS << 12; break;
        case 4: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
                w[7] = 0x7FFFE000u | 0xFFFu; break;
        case 5: w[7] = 1u << 12; break;
        case 6: w[0] = 1; break;
        default: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
                 w[7] = 0xFFFu; break;
        }
        if (k >> 1 != 2) w[7] |= sg << 31;
    } else {                         /* random values: normal, subnormal, either sign */
        fxs_val(&s, w, (uint32_t)k & 1u,
                k < 20 ? (uint32_t)(FX256_BIAS - 20 + 3 * k) : k < 23 ? 0u : 0x7FFFEu - (uint32_t)k);
    }
    fxs_put(w, e);
}

static void test_steer(void)
{
    uint8_t pl[NPOOL][32];
    const cft_fmt_desc *f = &cft_sf_formats[3];
    long n = 0, before = failures;
    int i, j, k, op;
    for (i = 0; i < NPOOL; i++)
        pool_elem(i, pl[i]);
    for (op = 0; op < 32; op++)
        for (i = 0; i < NPOOL; i++)
            for (j = 0; j < NPOOL; j++)
                for (k = 0; k < NPOOL; k++) {
                    uint8_t qa[32], qb[32], qc[32], ra[32], rb[32], rc[32];
                    cft_bn ba, bb, bc, sa, sb, sc;
                    int s1, s2;
                    if (op > 3 && (j || k))  /* the refusals: one triple an opcode is enough */
                        continue;
                    memcpy(qa, pl[i], 32); memcpy(qb, pl[j], 32); memcpy(qc, pl[k], 32);
                    s1 = fx256_steer(op, qa, qb, qc);
                    cft_bn_zero(&ba); cft_bn_zero(&bb); cft_bn_zero(&bc);
                    cft_bn_load(&ba, pl[i], 32); cft_bn_load(&bb, pl[j], 32);
                    cft_bn_load(&bc, pl[k], 32);
                    s2 = sf_steer(f, op, &ba, &bb, &bc, &sa, &sb, &sc);
                    n++;
                    if (s1 || s2) {
                        CHECK(s1 == s2 && !memcmp(qa, pl[i], 32) && !memcmp(qb, pl[j], 32) &&
                              !memcmp(qc, pl[k], 32), "opcode %d: fx256_steer %d, sf_steer "
                              "%d (or the operands moved on a refusal)", op, s1, s2);
                        continue;
                    }
                    cft_bn_store(&sa, ra, 32); cft_bn_store(&sb, rb, 32);
                    cft_bn_store(&sc, rc, 32);
                    CHECK(!memcmp(qa, ra, 32) && !memcmp(qb, rb, 32) && !memcmp(qc, rc, 32),
                          "opcode %d, pool %d %d %d: fx256_steer's operands are not "
                          "sf_steer's", op, i, j, k);
                }
    printf("  fx256_steer against sf_steer: %ld triples (every triple of %d at FMA, ADD, "
           "SUB and MUL; one an opcode at 4 to 31, both refusing), %ld failed\n", n, NPOOL,
           failures - before);
}

/* ---- 3. the streams ----------------------------------------------------- */

static void hash_hex(const uint8_t *p1, size_t n1, const uint8_t *p2, size_t n2,
                     const uint8_t *p3, size_t n3, const uint8_t *p4, size_t n4, char *hex)
{
    cft_sha256_ctx s;
    uint8_t dg[32];
    cft_sha256_init(&s);
    cft_sha256_update(&s, p1, n1);
    cft_sha256_update(&s, p2, n2);
    if (p3) cft_sha256_update(&s, p3, n3);
    if (p4) cft_sha256_update(&s, p4, n4);
    cft_sha256_final(&s, dg);
    cft_sha256_hex(dg, hex);
}

static void test_stream(int stream, int op, long total, uint64_t seed, const char *want_in,
                        const char *want_out)
{
    static const char *const OPN[4] = {"fma", "add", "sub", "mul"};
    const cft_fmt_desc *f = &cft_sf_formats[3];
    uint8_t *in = malloc((size_t)total * 97), *o1 = malloc((size_t)total * 33),
            *o2 = malloc((size_t)total * 33);
    uint8_t *a = in, *b = in + total * 32, *c = in + 2 * total * 32, *r = in + 3 * total * 32;
    char hi[65], h1[65], h2[65];
    long i, bad = 0, first = -1;
    clock_t t0 = clock();
    if (!in || !o1 || !o2) {
        CHECK(0, "out of host memory for %ld cases", total);
        free(in); free(o1); free(o2);
        return;
    }
    for (i = 0; i < total; i++) {
        fxs_gen_case(f, stream, seed, (int64_t)i, a + i * 32, b + i * 32, c + i * 32, r + i);
        fxs_prep_case(f, op, a + i * 32, b + i * 32, c + i * 32);
    }
    for (i = 0; i < total; i++) {
        fxs_generic_lane(f, op, a + i * 32, b + i * 32, c + i * 32, r[i], o1 + i * 32,
                         o1 + total * 32 + i);
        fxs_fixed_lane(op, a + i * 32, b + i * 32, c + i * 32, r[i], o2 + i * 32,
                       o2 + total * 32 + i, 0u);
        if (memcmp(o1 + i * 32, o2 + i * 32, 32) || o1[total * 32 + i] != o2[total * 32 + i]) {
            if (first < 0)
                first = i;
            bad++;
        }
    }
    hash_hex(a, (size_t)total * 32, b, (size_t)total * 32, c, (size_t)total * 32, r,
             (size_t)total, hi);
    hash_hex(o1, (size_t)total * 32, o1 + total * 32, (size_t)total, NULL, 0, NULL, 0, h1);
    hash_hex(o2, (size_t)total * 32, o2 + total * 32, (size_t)total, NULL, 0, NULL, 0, h2);
    CHECK(bad == 0, "%s stream, %s: %ld of %ld lanes differ, the first %ld",
          stream == FXS_EDGE ? "edge" : "study", OPN[op], bad, total, first);
    if (want_in) {
        CHECK(!strcmp(hi, want_in), "%s stream, %s: inputs' sha256 %s, GPU-A's %s",
              stream == FXS_EDGE ? "edge" : "study", OPN[op], hi, want_in);
        CHECK(!strcmp(h1, want_out) && !strcmp(h2, want_out), "%s stream, %s: outputs' "
              "sha256 %s / %s, GPU-A's %s", stream == FXS_EDGE ? "edge" : "study", OPN[op],
              h1, h2, want_out);
    }
    printf("  %-5s %s: %ld cases, seed %llu: %ld differ; sha256 inputs %.8s..., generic "
           "%.8s..., fixed %.8s...%s; %.2f s\n", stream == FXS_EDGE ? "edge" : "study",
           OPN[op], total, (unsigned long long)seed, bad, hi, h1, h2,
           want_in ? (!strcmp(hi, want_in) && !strcmp(h1, want_out) && !strcmp(h2, want_out)
                      ? " = GPU-A's CPU line" : " - NOT GPU-A's CPU line") : "", secs(t0));
    free(in); free(o1); free(o2);
}

int main(int argc, char **argv)
{
    /* GPU-A's CPU line, seed 1, 200000 cases (captured/desktop-checks.txt) */
    static const char *const IN[4] = {
        "15f6d14cf02ca2eeebf4e1d133d06594efa8d6ff1bd0edbfdf6221e77f2967cd",
        "290d14adf9c700275e75f02c3d75f8e23276b0e32e3601fbd525034162393a14",
        "f64f124c433a832e63987ec81aec280192d7e0c5703bd1425e8c4306f7b47bf8",
        "15f6d14cf02ca2eeebf4e1d133d06594efa8d6ff1bd0edbfdf6221e77f2967cd"};
    static const char *const OUT[4] = {
        "5010e777db905b8a2c5779295a9210433b9401f9835855055bb6c461197b5536",
        "ce928430fb8ba23cfd77117fd4865e05f9afcd55e972269ccfb3642753d999db",
        "ce928430fb8ba23cfd77117fd4865e05f9afcd55e972269ccfb3642753d999db",
        "e4048b0b16f2d49c7e8feef70519938191dea09ecb1ac63fd61fe148dd685240"};
    const long total = argc > 1 ? atol(argv[1]) : 200000;
    const uint64_t seed = argc > 2 ? strtoull(argv[2], NULL, 10) : 1;
    const int anchor = total == 200000 && seed == 1;
    clock_t t0 = clock();
    int op;
    if (total < 1 || total > 4000000) {
        fprintf(stderr, "usage: %s [N [SEED]], N in 1..4000000\n", argv[0]);
        return 2;
    }
    printf("fma256test: the fixed tier's lane against libcft's cft_sf_compute, on this host\n");
    test_matches();
    test_steer();
    for (op = 0; op < 4; op++)
        test_stream(FXS_STUDY, op, total, seed, anchor ? IN[op] : NULL,
                    anchor ? OUT[op] : NULL);
    for (op = 0; op < 4; op++)
        test_stream(FXS_EDGE, op, total, seed, NULL, NULL);
    if (!anchor)
        printf("  (GPU-A's sums are for 200000 cases at seed 1; not compared here)\n");
    printf("\n%ld checks, %ld failed, %.1f s\n", checks, failures, secs(t0));
    return failures ? 1 : 0;
}
