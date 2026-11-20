/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * fma128test - the GPU backend's fixed tier at binary128 (round 3's G3A2)
 * held to libcft's arithmetic on a HOST, with no GPU (make fma128test):
 *
 *     fma128-test [N [SEED]]          (default 200000 cases, seed 1)
 *
 * src/fma128_fixed.h and tools/fx128_stream.h are CFT_HD and need no GPU,
 * so the fixed tier's lane (fx128_steer, then fx128_fma_lane) and the
 * generic tier's (cft_sf_compute) run here on the same cases, compared
 * lane by lane, results and flags, as hip-fmadiff --format fp128 compares
 * them on a GPU (the sibling of fma256test, which this file does not touch):
 *
 *   1. fx128_matches holds the header's typed-in constants to the format
 *      table: 1 for cft_sf_formats[2], 0 for the other three, and 0 for
 *      binary128's descriptor with any one of its eight fields moved;
 *   2. fx128_steer, the byte steering, against softfloat.c's own sf_steer
 *      on cft_bn over every triple of a pool of specials and values, at
 *      FMA, ADD, SUB and MUL and at every other opcode (both refuse);
 *   3. the anchor: the study and edge streams at FMA, 2^21 cases from lane
 *      0 at seed 20261110 - the first chunk of hip-fmadiff --format fp128
 *      and of G3A's prototype (fma128_proto.hip) - their inputs' and both
 *      outputs' sha256 equal to the prototype's, measured on both GPUs;
 *   4. both streams, FMA and the three steered operations, N cases each:
 *      0 lanes differing.
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
#include "../src/fma128_fixed.h"
#include "../tools/fx128_stream.h"
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
        CHECK(fx128_matches(&cft_sf_formats[f]) == (f == 2), "fx128_matches(%s) is %d",
              cft_sf_formats[f].name, fx128_matches(&cft_sf_formats[f]));
    for (k = 0; k < 8; k++) {
        d = cft_sf_formats[2];
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
        m = fx128_matches(&d);
        CHECK(m == 0, "fx128_matches with field %d of binary128 moved answers %d", k, m);
    }
    printf("  fx128_matches: 1 for fp128, 0 for fp32, fp64, fp256 and for each of fp128's "
           "eight fields moved\n");
}

/* ---- 2. the byte steering against sf_steer ---------------------------- */

enum { NPOOL = 26 };

static void pool_elem(int k, uint8_t *e)
{
    uint32_t w[4];
    uint64_t s = 0x1234567ull + (uint64_t)k * 0x9E3779B97F4A7C15ull;
    int i;
    for (i = 0; i < 4; i++) w[i] = 0;
    if (k < 16) {                    /* the stream's sixteen specials, by index */
        const uint32_t sg = (uint32_t)k & 1u;
        switch (k >> 1) {
        case 0: break;
        case 1: w[3] = 0x7FFF0000u; break;
        case 2: w[3] = sg ? 0x7FFF0000u : 0x7FFF8000u; w[0] = 1; break;
        case 3: w[3] = (uint32_t)FX128_BIAS << 16; break;
        case 4: for (i = 0; i < 3; i++) w[i] = 0xFFFFFFFFu;
                w[3] = 0x7FFE0000u | 0xFFFFu; break;
        case 5: w[3] = 1u << 16; break;
        case 6: w[0] = 1; break;
        default: for (i = 0; i < 3; i++) w[i] = 0xFFFFFFFFu;
                 w[3] = 0xFFFFu; break;
        }
        if (k >> 1 != 2) w[3] |= sg << 31;
    } else {                         /* random values: normal, subnormal, either sign */
        fxs128_val(&s, w, (uint32_t)k & 1u,
                   k < 20 ? (uint32_t)(FX128_BIAS - 20 + 3 * k) : k < 23 ? 0u : 0x7FFEu - (uint32_t)k);
    }
    fxs128_put(w, e);
}

static void test_steer(void)
{
    uint8_t pl[NPOOL][16];
    const cft_fmt_desc *f = &cft_sf_formats[2];
    long n = 0, before = failures;
    int i, j, k, op;
    for (i = 0; i < NPOOL; i++)
        pool_elem(i, pl[i]);
    for (op = 0; op < 32; op++)
        for (i = 0; i < NPOOL; i++)
            for (j = 0; j < NPOOL; j++)
                for (k = 0; k < NPOOL; k++) {
                    uint8_t qa[16], qb[16], qc[16], ra[16], rb[16], rc[16];
                    cft_bn ba, bb, bc, sa, sb, sc;
                    int s1, s2;
                    if (op > 3 && (j || k))  /* the refusals: one triple an opcode is enough */
                        continue;
                    memcpy(qa, pl[i], 16); memcpy(qb, pl[j], 16); memcpy(qc, pl[k], 16);
                    s1 = fx128_steer(op, qa, qb, qc);
                    cft_bn_zero(&ba); cft_bn_zero(&bb); cft_bn_zero(&bc);
                    cft_bn_load(&ba, pl[i], 16); cft_bn_load(&bb, pl[j], 16);
                    cft_bn_load(&bc, pl[k], 16);
                    s2 = sf_steer(f, op, &ba, &bb, &bc, &sa, &sb, &sc);
                    n++;
                    if (s1 || s2) {
                        CHECK(s1 == s2 && !memcmp(qa, pl[i], 16) && !memcmp(qb, pl[j], 16) &&
                              !memcmp(qc, pl[k], 16), "opcode %d: fx128_steer %d, sf_steer "
                              "%d (or the operands moved on a refusal)", op, s1, s2);
                        continue;
                    }
                    cft_bn_store(&sa, ra, 16); cft_bn_store(&sb, rb, 16);
                    cft_bn_store(&sc, rc, 16);
                    CHECK(!memcmp(qa, ra, 16) && !memcmp(qb, rb, 16) && !memcmp(qc, rc, 16),
                          "opcode %d, pool %d %d %d: fx128_steer's operands are not "
                          "sf_steer's", op, i, j, k);
                }
    printf("  fx128_steer against sf_steer: %ld triples (every triple of %d at FMA, ADD, "
           "SUB and MUL; one an opcode at 4 to 31, both refusing), %ld failed\n", n, NPOOL,
           failures - before);
}

/* ---- 3 and 4. the streams --------------------------------------------- */

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
    const cft_fmt_desc *f = &cft_sf_formats[2];
    uint8_t *in = malloc((size_t)total * 49), *o1 = malloc((size_t)total * 17),
            *o2 = malloc((size_t)total * 17);
    uint8_t *a = in, *b = in + total * 16, *c = in + 2 * total * 16, *r = in + 3 * total * 16;
    char hi[65], h1[65], h2[65];
    long i, bad = 0, first = -1;
    clock_t t0 = clock();
    if (!in || !o1 || !o2) {
        CHECK(0, "out of host memory for %ld cases", total);
        free(in); free(o1); free(o2);
        return;
    }
    for (i = 0; i < total; i++) {
        fxs128_gen_case(f, stream, seed, (int64_t)i, a + i * 16, b + i * 16, c + i * 16, r + i);
        fxs128_prep_case(f, op, a + i * 16, b + i * 16, c + i * 16);
    }
    for (i = 0; i < total; i++) {
        fxs128_generic_lane(f, op, a + i * 16, b + i * 16, c + i * 16, r[i], o1 + i * 16,
                            o1 + total * 16 + i);
        fxs128_fixed_lane(op, a + i * 16, b + i * 16, c + i * 16, r[i], o2 + i * 16,
                          o2 + total * 16 + i, 0u);
        if (memcmp(o1 + i * 16, o2 + i * 16, 16) || o1[total * 16 + i] != o2[total * 16 + i]) {
            if (first < 0)
                first = i;
            bad++;
        }
    }
    hash_hex(a, (size_t)total * 16, b, (size_t)total * 16, c, (size_t)total * 16, r,
             (size_t)total, hi);
    hash_hex(o1, (size_t)total * 16, o1 + total * 16, (size_t)total, NULL, 0, NULL, 0, h1);
    hash_hex(o2, (size_t)total * 16, o2 + total * 16, (size_t)total, NULL, 0, NULL, 0, h2);
    CHECK(bad == 0, "%s stream, %s: %ld of %ld lanes differ, the first %ld",
          stream == FXS128_EDGE ? "edge" : "study", OPN[op], bad, total, first);
    if (want_in) {
        CHECK(!strcmp(hi, want_in), "%s stream, %s: inputs' sha256 %s, the prototype's %s",
              stream == FXS128_EDGE ? "edge" : "study", OPN[op], hi, want_in);
        CHECK(!strcmp(h1, want_out) && !strcmp(h2, want_out), "%s stream, %s: outputs' "
              "sha256 %s / %s, the prototype's %s", stream == FXS128_EDGE ? "edge" : "study",
              OPN[op], h1, h2, want_out);
    }
    printf("  %-5s %s: %ld cases, seed %llu: %ld differ; sha256 inputs %.8s..., generic "
           "%.8s..., fixed %.8s...%s; %.2f s\n", stream == FXS128_EDGE ? "edge" : "study",
           OPN[op], total, (unsigned long long)seed, bad, hi, h1, h2,
           want_in ? (!strcmp(hi, want_in) && !strcmp(h1, want_out) && !strcmp(h2, want_out)
                      ? " = the prototype's first chunk" : " - NOT the prototype's")
                   : "", secs(t0));
    free(in); free(o1); free(o2);
}

int main(int argc, char **argv)
{
    /* G3A's fp128 prototype (fma128_proto.hip, sha256 393612af...), its
     * first chunk at seed 20261110: 2^21 cases from lane 0 at FMA, the full
     * sums printed by a copy of it whose one printf prints them whole, the
     * same on the RTX 5060 Ti and the RX 7600 (G3A2's ledger, item 0) */
    static const char *const IN[2] = {
        "19f9e1a1c38af69f403964c9a5e9ecb03a805b6422abba623f51e8ec18a55281",
        "7959679a4197eadec84b0ac66ff8f3ac8375e419a1d787216e3f7dfb6ea8c5a3"};
    static const char *const OUT[2] = {
        "cbea6f91d1973fc235187d54322c15dd63e7961e400c1d77b2ffe4d2a10218fc",
        "160ea435c932a0f301618e418c65907e893c40336087d23bfb3d1aabc2884f2c"};
    const long total = argc > 1 ? atol(argv[1]) : 200000;
    const uint64_t seed = argc > 2 ? strtoull(argv[2], NULL, 10) : 1;
    clock_t t0 = clock();
    int op;
    if (total < 1 || total > 4000000) {
        fprintf(stderr, "usage: %s [N [SEED]], N in 1..4000000\n", argv[0]);
        return 2;
    }
    printf("fma128test: the fixed tier's fp128 lane against libcft's cft_sf_compute, on this "
           "host\n");
    test_matches();
    test_steer();
    test_stream(FXS128_STUDY, CFT_SF_FMA, 2097152, 20261110ull, IN[0], OUT[0]);
    test_stream(FXS128_EDGE, CFT_SF_FMA, 2097152, 20261110ull, IN[1], OUT[1]);
    for (op = 0; op < 4; op++)
        test_stream(FXS128_STUDY, op, total, seed, NULL, NULL);
    for (op = 0; op < 4; op++)
        test_stream(FXS128_EDGE, op, total, seed, NULL, NULL);
    printf("\n%ld checks, %ld failed, %.1f s\n", checks, failures, secs(t0));
    return failures ? 1 : 0;
}
