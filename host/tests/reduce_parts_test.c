/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft_sf_canonical_ranges: the partitioning a multi-tile reduction
 * needs, checked by the property it exists for rather than against a
 * table of expected answers.
 *
 * The property: reducing each range separately and folding the partials
 * with the same tree gives bit-identical results to reducing the whole
 * array in one go, for every n and every power-of-two part count. That
 * is the entire reason canonical ranges are not just even slices, and
 * it is checkable here without a card, without Python and without any
 * agreement about what the right sum actually is.
 *
 * Built against src/ rather than include/ because the partitioner is
 * internal - a host calls cft_reduce and never sees it.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"
#include "softfloat.h"

static int failures;
static long checks;

#define CHECK(cond, ...)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                 \
            printf(__VA_ARGS__);                                        \
            printf("\n");                                               \
            failures++;                                                 \
        }                                                               \
    } while (0)

/* xorshift64*, so the operands are the same on every platform. */
static uint64_t rng_state = 0x9E3779B97F4A7C15ull;
static uint64_t rng_next(void)
{
    uint64_t x = rng_state;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    rng_state = x;
    return x * 0x2545F4914F6CDD1Dull;
}

/* A normal number with a full random significand and a mid-range
 * exponent, so the adds actually interact. */
static void fill(uint8_t *buf, const cft_fmt_desc *f, size_t n)
{
    size_t esz = (size_t)f->width / 8, i, j;
    for (i = 0; i < n; i++) {
        uint8_t *e = buf + i * esz;
        for (j = 0; j < esz; j += 8) {
            uint64_t r = rng_next();
            size_t k, lim = (esz - j < 8) ? esz - j : 8;
            for (k = 0; k < lim; k++) e[j + k] = (uint8_t)(r >> (k * 8));
        }
        /* force a sane exponent: clear it, then set bias +/- a little */
        {
            int ebits = f->exp_w, mbits = f->man_w, b;
            uint32_t ev = (uint32_t)(f->bias + (int)(rng_next() % 21) - 10);
            for (b = 0; b < ebits; b++) {
                size_t bit = (size_t)mbits + (size_t)b;
                uint8_t m = (uint8_t)(1u << (bit & 7));
                if ((ev >> b) & 1u) e[bit >> 3] |= m;
                else                e[bit >> 3] = (uint8_t)(e[bit >> 3] & ~m);
            }
        }
    }
}

int main(void)
{
    static const size_t sizes[] = {
        1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 13, 15, 16, 17, 23, 31, 32, 33,
        63, 64, 65, 100, 127, 128, 129, 255, 256, 257, 500
    };
    static const size_t parts_list[] = { 1, 2, 4, 8, 16, 32, 64 };
    const size_t NSIZES = sizeof sizes / sizeof sizes[0];
    const size_t NPARTS = sizeof parts_list / sizeof parts_list[0];

    size_t lo[64], hi[64];
    uint8_t *buf = malloc(600 * 32);
    uint8_t *partials = malloc(64 * 32);
    int fi;

    if (!buf || !partials) {
        printf("out of memory\n");
        return 2;
    }

    for (fi = 0; fi < 4; fi++) {
        const cft_fmt_desc *f = &cft_sf_formats[fi];
        size_t esz = (size_t)f->width / 8;
        size_t si, pi;
        int rnd;

        for (si = 0; si < NSIZES; si++) {
            size_t n = sizes[si];
            fill(buf, f, n);

            for (rnd = 0; rnd < 5; rnd++) {
                cft_bn whole;
                uint32_t wflags = 0;

                if (cft_sf_reduce(f, CFT_SUM, rnd, buf, NULL, esz,
                                  0, n, &whole, &wflags)) {
                    CHECK(0, "%s n=%lu: whole reduction failed",
                          f->name, (unsigned long)n);
                    continue;
                }

                for (pi = 0; pi < NPARTS; pi++) {
                    size_t parts = parts_list[pi];
                    size_t k, got = cft_sf_canonical_ranges(n, parts,
                                                            lo, hi, 64);
                    uint32_t pflags = 0, cflags = 0;
                    cft_bn combined;

                    CHECK(got > 0, "%s n=%lu parts=%lu: no ranges",
                          f->name, (unsigned long)n, (unsigned long)parts);
                    if (got == 0) continue;

                    /* they must tile [0, n) exactly, in order */
                    CHECK(lo[0] == 0, "%s n=%lu parts=%lu: first range "
                          "starts at %lu", f->name, (unsigned long)n,
                          (unsigned long)parts, (unsigned long)lo[0]);
                    CHECK(hi[got - 1] == n, "%s n=%lu parts=%lu: last "
                          "range ends at %lu", f->name, (unsigned long)n,
                          (unsigned long)parts, (unsigned long)hi[got - 1]);
                    for (k = 1; k < got; k++)
                        CHECK(lo[k] == hi[k - 1],
                              "%s n=%lu parts=%lu: gap between range %lu "
                              "and %lu", f->name, (unsigned long)n,
                              (unsigned long)parts, (unsigned long)(k - 1),
                              (unsigned long)k);

                    /* each range reduced separately, then folded */
                    for (k = 0; k < got; k++) {
                        cft_bn p;
                        uint32_t fl = 0;
                        if (cft_sf_reduce(f, CFT_SUM, rnd, buf, NULL, esz,
                                          lo[k], hi[k], &p, &fl)) {
                            CHECK(0, "%s n=%lu: range reduction failed",
                                  f->name, (unsigned long)n);
                            break;
                        }
                        pflags |= fl;
                        cft_bn_store(&p, partials + k * esz, (int)esz);
                    }

                    if (cft_sf_reduce(f, CFT_SUM, rnd, partials, NULL, esz,
                                      0, got, &combined, &cflags)) {
                        CHECK(0, "%s n=%lu: combine failed",
                              f->name, (unsigned long)n);
                        continue;
                    }

                    checks++;
                    CHECK(cft_bn_cmp(&combined, &whole) == 0,
                          "%s n=%lu parts=%lu rnd=%d: %lu-way partition "
                          "gives a different sum from the whole array - "
                          "the ranges are not canonical tree nodes",
                          f->name, (unsigned long)n, (unsigned long)parts,
                          rnd, (unsigned long)got);
                    CHECK((pflags | cflags) == wflags,
                          "%s n=%lu parts=%lu rnd=%d: flags %#x from the "
                          "partition, %#x from the whole",
                          f->name, (unsigned long)n, (unsigned long)parts,
                          rnd, (unsigned)(pflags | cflags),
                          (unsigned)wflags);
                }
            }
        }
    }

    /* A non-power-of-two must be refused rather than quietly producing
     * ranges that are not nodes. */
    CHECK(cft_sf_canonical_ranges(64, 3, lo, hi, 64) == 0,
          "parts=3 must be refused: only a clean level cut yields nodes");
    CHECK(cft_sf_canonical_ranges(0, 4, lo, hi, 64) == 0,
          "an empty reduction has no ranges");

    free(buf);
    free(partials);

    if (checks < 1000) {
        printf("only %ld partitions checked - the sweep did not cover "
               "what it claims\n", checks);
        return 1;
    }
    printf("  %ld partitions checked across 4 formats x %lu sizes x "
           "%lu part counts x 5 attributes\n",
           checks, (unsigned long)NSIZES, (unsigned long)NPARTS);
    if (failures) {
        printf("reduce-parts: %d FAILED\n", failures);
        return 1;
    }
    printf("reduce-parts: every canonical partition reproduces the whole\n");
    return 0;
}
