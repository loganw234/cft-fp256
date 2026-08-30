/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * device-test - hold a device backend against the software one.
 *
 *     device-test <artifact.xclbin> [elements]
 *
 * The claim this program exists to check is the whole product: the
 * same call, with the same inputs, returns the same bits and the same
 * exception flags whether it ran on a laptop or on four compute units
 * of an FPGA. So it opens both backends at once, feeds them identical
 * data, and compares. Anything that differs is a bug in the device
 * path by definition, because the software backend is the one that has
 * been replayed against the golden model.
 *
 * It runs against a hw_emu image with no card present, which is the
 * point: multi-tile partitioning can be exercised, and its bugs found,
 * before any hardware exists. The same binary is what to run on the
 * card, and the only thing that changes is which xclbin it is given.
 *
 * Three things are checked, in increasing order of what they can
 * catch:
 *
 *   1. every supported (format, opcode, attribute) agrees with
 *      software, element for element and flag for flag;
 *   2. partition invariance - one call over n elements gives the same
 *      answer as several calls over consecutive slices of it, which is
 *      what the library does internally across tiles;
 *   3. sizes that straddle a beat and a tile boundary, because that is
 *      where a slice arithmetic error lives.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"

#define MAXE 32

static int failures;
static int checks;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        checks++;                                                        \
        if (!(cond)) {                                                   \
            printf("  FAIL: ");                                          \
            printf(__VA_ARGS__);                                         \
            printf("\n");                                                \
            failures++;                                                  \
        }                                                                \
    } while (0)

/* xorshift32, one step per byte - the same stream the examples use, so
 * a failing case can be regenerated from its seed alone. */
static uint32_t rs;
static uint8_t rbyte(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 17;
    rs ^= rs << 5;
    return (uint8_t)(rs & 0xffu);
}

/* Operands drawn from the whole encoding space, including NaNs and
 * infinities: a device that only ever sees well-behaved numbers is a
 * device whose special-case handling is untested. */
static void fill(uint8_t *p, size_t n, size_t esz)
{
    size_t i;
    for (i = 0; i < n * esz; i++)
        p[i] = rbyte();
}

static void hex(const uint8_t *p, size_t esz, char *out)
{
    static const char d[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < esz; i++) {
        out[2 * i]     = d[p[esz - 1 - i] >> 4];
        out[2 * i + 1] = d[p[esz - 1 - i] & 0xf];
    }
    out[2 * esz] = '\0';
}

struct buf { uint8_t *a, *b, *c, *sw, *hw; };

static int alloc_buffers(struct buf *B, size_t n, size_t esz)
{
    B->a  = malloc(n * esz);
    B->b  = malloc(n * esz);
    B->c  = malloc(n * esz);
    B->sw = malloc(n * esz);
    B->hw = malloc(n * esz);
    return B->a && B->b && B->c && B->sw && B->hw;
}

static void free_buffers(struct buf *B)
{
    free(B->a); free(B->b); free(B->c); free(B->sw); free(B->hw);
}

/* One (format, op, attribute) across n elements, both backends. */
static void compare(cft_device *sw, cft_device *hw, cft_format fmt,
                    cft_op op, cft_round rnd, size_t n, uint32_t seed)
{
    size_t esz = cft_format_size(fmt), i;
    uint32_t fsw = 0, fhw = 0, bus = 0;
    cft_status ssw, shw;
    struct buf B;
    size_t bad = 0;

    if (!alloc_buffers(&B, n, esz)) {
        printf("  FAIL: out of memory\n");
        failures++;
        return;
    }
    rs = seed ? seed : 1;
    fill(B.a, n, esz);
    fill(B.b, n, esz);
    fill(B.c, n, esz);
    memset(B.sw, 0, n * esz);
    memset(B.hw, 0, n * esz);

    ssw = cft_run(sw, op, fmt, rnd, B.a, B.b, B.c, B.sw, n, &fsw, NULL);
    shw = cft_run(hw, op, fmt, rnd, B.a, B.b, B.c, B.hw, n, &fhw, &bus);

    CHECK(ssw == CFT_OK, "software %s %s n=%lu: %s",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(ssw));
    CHECK(shw == CFT_OK, "device %s %s n=%lu: %s (bus 0x%x) %s",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(shw), (unsigned)bus, cft_last_error());
    if (ssw != CFT_OK || shw != CFT_OK) {
        free_buffers(&B);
        return;
    }

    for (i = 0; i < n; i++) {
        if (memcmp(B.sw + i * esz, B.hw + i * esz, esz) != 0) {
            if (bad < 3) {
                char h1[2 * MAXE + 1], h2[2 * MAXE + 1];
                char ha[2 * MAXE + 1], hb[2 * MAXE + 1], hc[2 * MAXE + 1];
                hex(B.a + i * esz, esz, ha);
                hex(B.b + i * esz, esz, hb);
                hex(B.c + i * esz, esz, hc);
                hex(B.sw + i * esz, esz, h1);
                hex(B.hw + i * esz, esz, h2);
                printf("  FAIL: %s %s %d element %lu of %lu\n"
                       "        a %s\n        b %s\n        c %s\n"
                       "        software %s\n        device   %s\n",
                       cft_format_name(fmt), cft_op_name(op), (int)rnd,
                       (unsigned long)i, (unsigned long)n, ha, hb, hc,
                       h1, h2);
            }
            bad++;
        }
    }
    checks++;
    if (bad) {
        failures++;
        printf("  FAIL: %lu of %lu elements differ\n",
               (unsigned long)bad, (unsigned long)n);
    }
    CHECK(fsw == fhw, "%s %s flags: software 0x%02x, device 0x%02x",
          cft_format_name(fmt), cft_op_name(op),
          (unsigned)fsw, (unsigned)fhw);
    free_buffers(&B);
}

/* Partition invariance. One call over n, then the same data as a
 * sequence of shorter calls; the concatenation must be identical and
 * the flags must be the OR. This is precisely what the library does
 * across compute units, so if slicing were wrong in a way that
 * happened to be self-consistent, this is what would still catch it. */
static void compare_partitioned(cft_device *hw, cft_format fmt, cft_op op,
                                cft_round rnd, size_t n, const size_t *cuts,
                                size_t ncuts, uint32_t seed)
{
    size_t esz = cft_format_size(fmt), off = 0, i;
    uint32_t whole_f = 0, split_f = 0;
    struct buf B;
    uint8_t *split;

    if (!alloc_buffers(&B, n, esz))
        return;
    split = malloc(n * esz);
    if (!split) { free_buffers(&B); return; }

    rs = seed ? seed : 1;
    fill(B.a, n, esz);
    fill(B.b, n, esz);
    fill(B.c, n, esz);
    memset(B.hw, 0, n * esz);
    memset(split, 0, n * esz);

    if (cft_run(hw, op, fmt, rnd, B.a, B.b, B.c, B.hw, n, &whole_f, NULL)
        != CFT_OK) {
        printf("  FAIL: whole run: %s\n", cft_last_error());
        failures++;
        free(split); free_buffers(&B);
        return;
    }
    for (i = 0; i < ncuts; i++) {
        uint32_t f = 0;
        size_t k = cuts[i];
        if (off + k > n)
            k = n - off;
        if (k == 0)
            continue;
        if (cft_run(hw, op, fmt, rnd, B.a + off * esz, B.b + off * esz,
                    B.c + off * esz, split + off * esz, k, &f, NULL)
            != CFT_OK) {
            printf("  FAIL: slice run: %s\n", cft_last_error());
            failures++;
            free(split); free_buffers(&B);
            return;
        }
        split_f |= f;
        off += k;
    }
    CHECK(off == n, "slices covered %lu of %lu elements",
          (unsigned long)off, (unsigned long)n);
    CHECK(memcmp(B.hw, split, n * esz) == 0,
          "%s %s n=%lu: splitting the call changed the result",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n);
    CHECK(whole_f == split_f,
          "%s %s n=%lu: whole flags 0x%02x, OR of slices 0x%02x",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          (unsigned)whole_f, (unsigned)split_f);
    free(split);
    free_buffers(&B);
}

int main(int argc, char **argv)
{
    static const cft_op ops[] = {CFT_FMA, CFT_ADD, CFT_SUB, CFT_MUL,
                                 CFT_MIN, CFT_MAXNUM, CFT_CMPLT,
                                 CFT_SELECT, CFT_IXOR, CFT_ISHR};
    static const cft_round rnds[] = {CFT_RNE, CFT_RTZ, CFT_RDN, CFT_RUP,
                                     CFT_RMM};
    cft_device *sw = NULL, *hw = NULL;
    cft_caps caps;
    cft_status st;
    size_t n = (argc > 2) ? (size_t)strtoul(argv[2], NULL, 10) : 256;
    int f, o, r;

    if (argc < 2) {
        fprintf(stderr, "usage: %s <artifact.xclbin> [elements]\n", argv[0]);
        return 2;
    }

    st = cft_open(NULL, 0, &sw);
    if (st != CFT_OK) {
        fprintf(stderr, "software backend: %s\n", cft_strerror(st));
        return 2;
    }
    st = cft_open(argv[1], 0, &hw);
    if (st != CFT_OK) {
        fprintf(stderr, "device %s: %s\n  %s\n", argv[1], cft_strerror(st),
                cft_last_error());
        cft_close(sw);
        return 2;
    }

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(hw, &caps) == CFT_OK) {
        printf("device: backend %s, %u tile%s, contract 0x%08x, "
               "formats", caps.backend, (unsigned)caps.tiles,
               caps.tiles == 1 ? "" : "s", (unsigned)caps.device_version);
        for (f = 0; f < 4; f++)
            if (caps.format_mask & (1u << f))
                printf(" %s", cft_format_name((cft_format)f));
        printf("\n");
        if (!caps.flags_readable)
            printf("  WARNING: flags are not readable on this device\n");
    }
    printf("comparing %lu elements per case against the software "
           "backend\n", (unsigned long)n);

    for (f = 0; f < 4; f++) {
        cft_format fmt = (cft_format)f;
        if (!cft_supports(hw, CFT_FMA, fmt)) {
            printf("%-6s not on this device, skipped\n",
                   cft_format_name(fmt));
            continue;
        }
        printf("%s\n", cft_format_name(fmt));
        for (o = 0; o < (int)(sizeof ops / sizeof ops[0]); o++) {
            if (!cft_supports(hw, ops[o], fmt))
                continue;
            for (r = 0; r < (int)(sizeof rnds / sizeof rnds[0]); r++)
                compare(sw, hw, fmt, ops[o], rnds[r], n,
                        0x51ce0000u + (uint32_t)(f * 100 + o * 10 + r));
        }

        /* Sizes chosen to straddle the awkward boundaries: one
         * element, one beat, one more than a beat, an odd count that
         * cannot divide evenly across four tiles, and a prime. */
        {
            static const size_t odd[] = {1, 2, 3, 7, 8, 9, 31, 32, 33, 37};
            static const size_t cuts[] = {1, 2, 5, 8, 16, 64, 1024};
            size_t i;
            for (i = 0; i < sizeof odd / sizeof odd[0]; i++)
                compare(sw, hw, fmt, CFT_FMA, CFT_RNE, odd[i],
                        0x0dd00000u + (uint32_t)(f * 50 + i));
            compare_partitioned(hw, fmt, CFT_FMA, CFT_RNE, n, cuts,
                                sizeof cuts / sizeof cuts[0],
                                0x5717000u + (uint32_t)f);
        }
    }

    cft_close(hw);
    cft_close(sw);
    printf("\n%d checks, %d failed\n", checks, failures);
    if (!failures)
        printf("the device and the software backend agree on every "
               "case, bits and flags\n");
    return failures ? 1 : 0;
}
