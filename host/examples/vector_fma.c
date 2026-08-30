/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The smallest useful libcft program: run a fused multiply-add over a
 * vector at every precision and print a checksum of the result.
 *
 *     cc -Ihost/include host/examples/vector_fma.c host/libcft.a -o vector-fma
 *     ./vector-fma
 *
 * The checksum is the point. Run this on another machine, in another
 * operating system, built by another compiler, and the lines must be
 * character for character identical - and identical again to what
 * host/examples/vector_fma_ctypes.py prints, which reaches the same
 * library through Python instead of C. That is the entire product
 * reduced to something you can diff.
 *
 * Nothing here needs a card. Pass an xclbin path as argv[1] and the
 * same program runs on the tile instead, with the same output.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"

#define N 4096

/* ---- the operand stream ------------------------------------------ *
 *
 * xorshift32, stepped once per byte, so that the C and Python programs
 * can generate byte-identical inputs without sharing a file. It is not
 * a good random number generator and does not need to be: it needs to
 * be short enough to reimplement without error in any language, which
 * a good one would not be.
 */
static uint32_t rng_state;

static void rng_seed(uint32_t s)
{
    rng_state = s ? s : 1u;
}

static uint8_t rng_byte(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return (uint8_t)(rng_state & 0xffu);
}

/* One element: a normal with a fraction from the stream and an
 * exponent within 32 of 1.0, so that products stay in range and the
 * run exercises rounding rather than overflow. */
static void make_element(uint8_t *e, int width, int exp_w, int man_w, int bias)
{
    int nb = width / 8, kb = man_w / 8, rb = man_w % 8, j;
    uint32_t ef;

    for (j = 0; j < nb; j++)
        e[j] = rng_byte();
    ef = (uint32_t)(bias - 32 + (int)(rng_byte() & 63u));

    e[kb] &= (uint8_t)((1u << rb) - 1u);
    for (j = kb + 1; j < nb; j++)
        e[j] = 0;
    for (j = 0; j < exp_w; j++)
        if ((ef >> j) & 1u)
            e[(man_w + j) / 8] |= (uint8_t)(1u << ((man_w + j) % 8));
    if (rng_byte() & 1u)
        e[nb - 1] |= 0x80u;
}

/* FNV-1a, 64-bit. The constants are written in hex because that is
 * how they are specified; transcribing them as decimal is how you get
 * a checksum that is stable, plausible, and not FNV. */
static uint64_t fnv1a(const uint8_t *p, size_t n)
{
    uint64_t h = 0xcbf29ce484222325ull;
    size_t i;
    for (i = 0; i < n; i++) {
        h ^= p[i];
        h *= 0x100000001b3ull;
    }
    return h;
}

struct geom { int width, exp_w, man_w, bias; };

int main(int argc, char **argv)
{
    static const struct geom g[4] = {
        {  32,  8,  23,    127 },
        {  64, 11,  52,   1023 },
        { 128, 15, 112,  16383 },
        { 256, 19, 236, 262143 }
    };
    const char *artifact = (argc > 1) ? argv[1] : NULL;
    cft_device *dev = NULL;
    cft_status st;
    int f;

    st = cft_open(artifact, 0, &dev);
    if (st != CFT_OK) {
        fprintf(stderr, "cft_open(%s): %s\n",
                artifact ? artifact : "software", cft_strerror(st));
        return 1;
    }
    printf("cft-fp256 vector fma, %s backend\n",
           artifact ? artifact : "software");

    for (f = 0; f < 4; f++) {
        size_t esz = cft_format_size((cft_format)f);
        uint8_t *a, *b, *c, *d;
        uint32_t flags = 0;
        size_t i;

        if (!cft_supports(dev, CFT_FMA, (cft_format)f)) {
            printf("%-6s not available on this device\n",
                   cft_format_name((cft_format)f));
            continue;
        }

        a = (uint8_t *)malloc(N * esz);
        b = (uint8_t *)malloc(N * esz);
        c = (uint8_t *)malloc(N * esz);
        d = (uint8_t *)malloc(N * esz);
        if (!a || !b || !c || !d) {
            fprintf(stderr, "out of memory\n");
            free(a); free(b); free(c); free(d);
            cft_close(dev);
            return 1;
        }

        /* Seeded per format, so each line is independent of the ones
         * before it and can be reproduced on its own. */
        rng_seed(0x1234567u + (uint32_t)f);
        for (i = 0; i < N; i++) {
            make_element(a + i * esz, g[f].width, g[f].exp_w, g[f].man_w,
                         g[f].bias);
            make_element(b + i * esz, g[f].width, g[f].exp_w, g[f].man_w,
                         g[f].bias);
            make_element(c + i * esz, g[f].width, g[f].exp_w, g[f].man_w,
                         g[f].bias);
        }

        st = cft_run(dev, CFT_FMA, (cft_format)f, CFT_RNE,
                     a, b, c, d, N, &flags, NULL);
        if (st != CFT_OK) {
            fprintf(stderr, "cft_run %s: %s\n",
                    cft_format_name((cft_format)f), cft_strerror(st));
            free(a); free(b); free(c); free(d);
            cft_close(dev);
            return 1;
        }

        printf("%-6s n=%d rne  checksum 0x%016llx  flags 0x%02x\n",
               cft_format_name((cft_format)f), N,
               (unsigned long long)fnv1a(d, N * esz), (unsigned)flags);

        free(a); free(b); free(c); free(d);
    }

    cft_close(dev);
    return 0;
}
