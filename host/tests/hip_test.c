/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * hip-test - what only the GPU backend has, through the public API alone.
 *
 *     hip-test hip:N [-l LEGS] [-f FORMAT] [-s small|large|all]
 *
 * LEGS is a comma list of open, reduce, seg, compose, alias, two and
 * plants (default: all of them); -f keeps one format; -s chooses the
 * reduction sizes (default all). The legs:
 *
 *   open      cft_open's grammar for "hip:N" (each malformed spelling
 *             refused by name, with the grammar in the sentence), index
 *             1, a device past the count, an xclbin; the capability word
 *             (formats 15, groups 0x7F, tiles 1, version 0, flags
 *             readable, backend "hip", buffers_resident 0, the software
 *             handle's four capacities and its features less
 *             CFT_SEQ_FEAT_INDEXED and CFT_SEQ_FEAT_AUGADD); the image
 *             identity refused by name; another scratch depth refused.
 *   reduce    cft_reduce SUM and MAXALL against the software handle - the
 *             definition - bits and flags, at every n from 1 to 130 and
 *             every power of two with its neighbours up to 2^18 (-s), at
 *             every format and attribute, on six kinds of data: random
 *             finite values, the same with quiet and signalling NaNs,
 *             with infinities of both signs, with +infinity alone, values
 *             near the largest finite (overflow), and signed zeros; and n
 *             = 1 with a signalling NaN, which must come back verbatim
 *             with no flags.
 *   seg       cft_reduce_seg SUM and MAXALL the same way, with segments
 *             of 1, 2, 3, 7, 8, 64 and n (each n cut down to a multiple
 *             of the segment); every kind of data at n up to 130, the
 *             random kind past it.
 *   compose   DOT, SUMSQ and SUMABS, which device.c composes from a run
 *             and a SUM, whole and segmented by 3, at the same sizes:
 *             every kind of data at n up to 130, the random kind past it.
 *   alias     a scalar operand that d aliases: what the GPU does (a
 *             snapshot) and what the software loop does (it re-reads
 *             element 0 after writing it), each held to its own rule.
 *   two       two handles on one device, used in turn and closed in
 *             turn; two DEVICES where the runtime shows two (NOT RUN,
 *             named, where it shows one).
 *   plants    (a HIP_PLANTS=1 build) CFT_HIP_PLANT, CFT_HIP_CHUNK and
 *             CFT_HIP_INFO malformed and refused by name; fail-launch's
 *             poisoned handle. In a default build: NOT RUN, named.
 *
 * Every check counts; a NOT RUN line names what did not run and why; the
 * last line says how many checks failed. Exit 0 only when none did.
 */

#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"

static int failures, checks, not_run;
static int shown;                       /* FAIL lines printed */
static const char *const RND[5] = {"rne", "rtz", "rdn", "rup", "rmm"};

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        checks++;                                                        \
        if (!(cond)) {                                                   \
            failures++;                                                  \
            if (shown++ < 60) {                                          \
                printf("  FAIL: ");                                      \
                printf(__VA_ARGS__);                                     \
                printf("\n");                                            \
            }                                                            \
        }                                                                \
    } while (0)

static void nrun(const char *what, const char *why)
{
    printf("%s: NOT RUN - %s\n", what, why);
    not_run++;
}

static void put_env(const char *name, const char *value)
{
#ifdef _WIN32
    char buf[200];
    snprintf(buf, sizeof buf, "%s=%s", name, value ? value : "");
    _putenv(buf);
#else
    if (value)
        setenv(name, value, 1);
    else
        unsetenv(name);
#endif
}

/* ---- data ---------------------------------------------------------- */

static unsigned long long rs = 0x9E3779B97F4A7C15ull;
static unsigned long long rnd64(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 7;
    rs ^= rs << 17;
    return rs;
}

/* The IEEE interchange formats' exponent widths; the rest of an element
 * is its trailing significand and the sign. */
static const int EXPW[4] = {8, 11, 15, 19};

/* An element of `esz` bytes, little-endian: sign, biased exponent and a
 * trailing significand of random bits (mant: 0 none, 1 random, 2 random
 * with the top bit set, 3 random with the top bit clear but not zero). */
static void elem(unsigned char *e, int fmt, int sign, unsigned long exp, int mant)
{
    const int width = (int)cft_format_size((cft_format)fmt) * 8;
    const int ew = EXPW[fmt], mw = width - 1 - ew;
    int b;
    memset(e, 0, (size_t)width / 8);
    if (mant) {
        for (b = 0; b < width / 8; b += 8) {
            unsigned long long r = rnd64();
            int k;
            for (k = 0; k < 8 && b + k < width / 8; k++)
                e[b + k] = (unsigned char)(r >> (8 * k));
        }
        for (b = mw; b < width; b++)    /* the exponent and the sign: below */
            e[b / 8] &= (unsigned char)~(1u << (b % 8));
        if (mant == 2)
            e[(mw - 1) / 8] |= (unsigned char)(1u << ((mw - 1) % 8));
        if (mant == 3) {
            e[(mw - 1) / 8] &= (unsigned char)~(1u << ((mw - 1) % 8));
            e[0] |= 1u;                     /* a signalling NaN is not inf */
        }
    }
    for (b = 0; b < ew; b++)
        if ((exp >> b) & 1u)
            e[(mw + b) / 8] |= (unsigned char)(1u << ((mw + b) % 8));
    if (sign)
        e[(width - 1) / 8] |= (unsigned char)(1u << ((width - 1) % 8));
}

enum { K_RANDOM, K_NAN, K_INF, K_PINF, K_OVERFLOW, K_ZERO, K_COUNT };
static const char *const KIND[K_COUNT] = {"random", "NaN", "inf", "+inf",
                                          "overflow", "signed zero"};

/* n elements of kind k. Random finite values have exponents within 24 of
 * the bias, so sums cancel and round; the special kinds put their values
 * among them at random places (at least one each). */
static void fill(unsigned char *a, size_t n, int fmt, int k)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const unsigned long bias = (1ul << (EXPW[fmt] - 1)) - 1;
    const unsigned long top = (1ul << EXPW[fmt]) - 1;
    size_t i;
    for (i = 0; i < n; i++) {
        unsigned char *e = a + i * esz;
        switch (k) {
        case K_OVERFLOW:
            elem(e, fmt, (rnd64() % 8) == 0, top - 1 - rnd64() % 2, 1);
            break;
        case K_ZERO:
            elem(e, fmt, (int)(rnd64() & 1u), 0, 0);
            break;
        default:
            elem(e, fmt, (int)(rnd64() & 1u), bias - 24 + rnd64() % 49, 1);
        }
    }
    if (k == K_NAN || k == K_INF || k == K_PINF) {
        size_t m = 1 + n / 16, j;
        for (j = 0; j < m; j++) {
            unsigned char *e = a + (size_t)(rnd64() % n) * esz;
            if (k == K_NAN)
                elem(e, fmt, (int)(rnd64() & 1u), top, (rnd64() & 1u) ? 2 : 3);
            else
                elem(e, fmt, k == K_INF ? (int)(rnd64() & 1u) : 0, top, 0);
        }
    }
}

static int same(const unsigned char *x, const unsigned char *y, size_t bytes)
{
    return memcmp(x, y, bytes) == 0;
}

static void hex(char *out, const unsigned char *e, size_t esz)
{
    size_t i;
    for (i = 0; i < esz; i++)
        sprintf(out + 2 * i, "%02x", e[esz - 1 - i]);
}

/* ---- the open leg ------------------------------------------------------ */

static void open_refused(const char *artifact, int index, cft_status want,
                         const char *says)
{
    cft_device *h = NULL;
    const cft_status st = cft_open(artifact, index, &h);
    const char *msg = cft_last_error();
    CHECK(st == want && h == NULL && strstr(msg, says) != NULL,
          "cft_open(\"%s\", %d): %s with \"%s\" - wanted %s, saying \"%s\"",
          artifact, index, cft_strerror(st), msg, cft_strerror(want), says);
    if (st == CFT_OK)
        cft_close(h);
    printf("    cft_open(\"%s\", %d): %s - %s\n", artifact, index, cft_strerror(st), msg);
}

static void leg_open(const char *artifact, cft_device *hw, cft_device *sw)
{
    static const char *const bad[] = {"hip", "hip:", "hip:x", "hip:0x1", "hip:1 ",
                                      "hip:-1", "hip:+1", "hip: 1"};
    cft_caps c, s;
    cft_image_id im;
    cft_open_args oa;
    cft_device *h = NULL;
    cft_status st;
    size_t i;
    int f;
    const uint32_t want_feat = (CFT_SEQ_FEAT_WIDE_CONST | CFT_SEQ_FEAT_REGS32 |
                                CFT_SEQ_FEAT_BANK_PTR | CFT_SEQ_FEAT_KX9 |
                                CFT_ALU_EXT_IMUL | CFT_SEQ_FEAT_SCRATCH |
                                CFT_SEQ_FEAT_SCRATCH_IO |
                                CFT_SEQ_FEAT_SCRATCH_STRICT | CFT_SEQ_FEAT_SCALAR |
                                CFT_FEAT_REDUCE_SEG | CFT_SEQ_FEAT_LANE_MASK |
                                CFT_SEQ_FEAT_SCRATCH_STEP | CFT_SEQ_FEAT_LANE_FLAGS |
                                CFT_SEQ_FEAT_FLAG_CONTROL);
    const int before = failures;

    printf("open\n");
    for (i = 0; i < sizeof bad / sizeof bad[0]; i++)
        open_refused(bad[i], 0, CFT_ERR_INVALID_ARGUMENT, "followed by the device's number");
    open_refused(artifact, 1, CFT_ERR_INVALID_ARGUMENT, "pass index 0");
    open_refused("hip:999", 0, CFT_ERR_NO_DEVICE, "the HIP runtime sees");
    open_refused("hip:99999999999999999999", 0, CFT_ERR_NO_DEVICE, "the HIP runtime sees");
    open_refused("cft_hw_emu.xclbin", 0, CFT_ERR_NO_DEVICE, "opens hip:N only");

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    memset(&s, 0, sizeof s);
    s.struct_size = sizeof s;
    CHECK(cft_get_caps(hw, &c) == CFT_OK && cft_get_caps(sw, &s) == CFT_OK,
          "cft_get_caps failed: %s", cft_last_error());
    printf("    caps: backend \"%s\", formats 0x%x, tiles %u, version %u, flags "
           "readable %d, seq_features 0x%x, capacities %u/%u/%u, max_scratch %u, "
           "buffers_resident %d\n", c.backend, (unsigned)c.format_mask,
           (unsigned)c.tiles, (unsigned)c.device_version, c.flags_readable,
           (unsigned)c.seq_features, (unsigned)c.max_deposits, (unsigned)c.max_insns,
           (unsigned)c.max_consts, (unsigned)c.max_scratch, c.buffers_resident);
    CHECK(!strcmp(c.backend, "hip"), "backend \"%s\", not \"hip\"", c.backend);
    CHECK(c.format_mask == 0x0Fu, "format mask 0x%x, not 15", (unsigned)c.format_mask);
    CHECK(c.tiles == 1 && c.device_version == 0 && c.flags_readable == 1,
          "tiles %u, version %u, flags readable %d - wanted 1, 0, 1",
          (unsigned)c.tiles, (unsigned)c.device_version, c.flags_readable);
    CHECK(c.seq_features == want_feat &&
          c.seq_features == (s.seq_features &
                             ~(uint32_t)(CFT_SEQ_FEAT_INDEXED | CFT_SEQ_FEAT_AUGADD)),
          "seq_features 0x%x: wanted 0x%x, the software handle's 0x%x less INDEXED "
          "and AUGADD", (unsigned)c.seq_features, (unsigned)want_feat,
          (unsigned)s.seq_features);
    CHECK(c.max_deposits == s.max_deposits && c.max_insns == s.max_insns &&
          c.max_consts == s.max_consts && c.max_scratch == s.max_scratch,
          "capacities %u/%u/%u/%u, the software handle's %u/%u/%u/%u",
          (unsigned)c.max_deposits, (unsigned)c.max_insns, (unsigned)c.max_consts,
          (unsigned)c.max_scratch, (unsigned)s.max_deposits, (unsigned)s.max_insns,
          (unsigned)s.max_consts, (unsigned)s.max_scratch);
    CHECK(c.buffers_resident == 0, "buffers_resident %d before the GPU keeps "
          "device copies", c.buffers_resident);
    /* the seven opcode groups, by one opcode each, at every format */
    for (f = 0; f < 4; f++) {
        static const cft_op g[7] = {CFT_FMA, CFT_ABS, CFT_MIN, CFT_CMPLT, CFT_IADD,
                                    CFT_SUM, CFT_RECIP_SEED};
        int k;
        for (k = 0; k < 7; k++)
            CHECK(cft_supports(hw, g[k], (cft_format)f) ==
                      cft_supports(sw, g[k], (cft_format)f),
                  "cft_supports(%s, %s) differs from the software handle's",
                  cft_op_name(g[k]), cft_format_name((cft_format)f));
        CHECK(cft_supports(hw, CFT_IMUL, (cft_format)f) == 1, "IMUL at %s",
              cft_format_name((cft_format)f));
    }

    memset(&im, 0xA5, sizeof im);
    im.struct_size = sizeof im;
    st = cft_get_image_id(hw, &im);
    CHECK(st == CFT_ERR_UNSUPPORTED && im.struct_size == 0 &&
          strstr(cft_last_error(), "the GPU backend loads no device image") &&
          strstr(cft_last_error(), "cft_build_id()"),
          "the image identity: %s, struct_size %lu, \"%s\"", cft_strerror(st),
          (unsigned long)im.struct_size, cft_last_error());
    printf("    image identity: %s - %s\n", cft_strerror(st), cft_last_error());

    memset(&oa, 0, sizeof oa);
    oa.struct_size = sizeof oa;
    oa.artifact = artifact;
    oa.scratch_depth = 2048;
    st = cft_open_ex(&oa, &h);
    CHECK(st == CFT_ERR_UNSUPPORTED && h == NULL &&
          strstr(cft_last_error(), "SOFTWARE handle's depth"),
          "cft_open_ex at 2,048 scratch slots: %s, \"%s\"", cft_strerror(st),
          cft_last_error());
    if (h)
        cft_close(h);
    printf("    cft_open_ex(%s, scratch_depth 2048): %s - %s\n", artifact,
           cft_strerror(st), cft_last_error());
    printf("  open: %d failed\n", failures - before);
}

/* ---- the reductions ---------------------------------------------------- */

static size_t sizes[200];
static size_t nsizes;

static void make_sizes(int which)
{
    size_t n;
    int k;
    nsizes = 0;
    if (which != 2)
        for (n = 1; n <= 130; n++)
            sizes[nsizes++] = n;
    if (which != 1)
        for (k = 8; k <= 18; k++) {
            sizes[nsizes++] = ((size_t)1 << k) - 1;
            sizes[nsizes++] = (size_t)1 << k;
            sizes[nsizes++] = ((size_t)1 << k) + 1;
        }
}

/* One reduction on both handles, held to each other: result and flags. */
static void red_case(cft_device *hw, cft_device *sw, cft_op op, int fmt, int rnd,
                     const unsigned char *a, const unsigned char *b, size_t n,
                     size_t seg, const char *kind, long *ncmp)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const size_t nres = seg ? n / seg : 1;
    unsigned char *dh = (unsigned char *)malloc(nres * esz);
    unsigned char *ds = (unsigned char *)malloc(nres * esz);
    uint32_t fh = 0xFFu, fs = 0xFFu;
    cft_status sh, ss;
    if (!dh || !ds) {
        CHECK(0, "out of memory");
        free(dh);
        free(ds);
        return;
    }
    memset(dh, 0x5A, nres * esz);
    memset(ds, 0xA5, nres * esz);
    if (seg) {
        sh = cft_reduce_seg(hw, op, (cft_format)fmt, (cft_round)rnd, a, b, dh, n, seg, &fh, NULL);
        ss = cft_reduce_seg(sw, op, (cft_format)fmt, (cft_round)rnd, a, b, ds, n, seg, &fs, NULL);
    } else {
        sh = cft_reduce(hw, op, (cft_format)fmt, (cft_round)rnd, a, b, dh, n, &fh, NULL);
        ss = cft_reduce(sw, op, (cft_format)fmt, (cft_round)rnd, a, b, ds, n, &fs, NULL);
    }
    (*ncmp)++;
    if (sh != CFT_OK || ss != CFT_OK) {
        CHECK(0, "%s %s %s n=%lu seg=%lu %s: GPU %s, software %s (%s)", cft_op_name(op),
              cft_format_name((cft_format)fmt), RND[rnd],
              (unsigned long)n, (unsigned long)seg, kind, cft_strerror(sh),
              cft_strerror(ss), cft_last_error());
    } else if (!same(dh, ds, nres * esz) || fh != fs) {
        size_t r = 0;
        char xh[70], xs[70];
        while (r + 1 < nres && same(dh + r * esz, ds + r * esz, esz))
            r++;
        hex(xh, dh + r * esz, esz);
        hex(xs, ds + r * esz, esz);
        CHECK(0, "%s %s %s n=%lu seg=%lu %s: result %lu GPU %s flags 0x%02x, "
              "software %s flags 0x%02x", cft_op_name(op),
              cft_format_name((cft_format)fmt), RND[rnd],
              (unsigned long)n, (unsigned long)seg, kind, (unsigned long)r, xh,
              (unsigned)fh, xs, (unsigned)fs);
    } else {
        checks++;
    }
    free(dh);
    free(ds);
}

static void leg_reduce(cft_device *hw, cft_device *sw, int only_fmt, int segmented,
                       int composed)
{
    static const size_t segs[6] = {1, 2, 3, 7, 8, 64};
    const int before = failures;
    long ncmp = 0;
    size_t z, maxn = 0;
    int f, r, k;
    unsigned char *a, *b;
    clock_t t0 = clock();

    for (z = 0; z < nsizes; z++)
        if (sizes[z] > maxn)
            maxn = sizes[z];
    a = (unsigned char *)malloc(maxn * 32);
    b = (unsigned char *)malloc(maxn * 32);
    if (!a || !b) {
        CHECK(0, "out of memory for %lu elements", (unsigned long)maxn);
        free(a);
        free(b);
        return;
    }
    printf("%s\n", composed ? "compose" : segmented ? "seg" : "reduce");
    for (f = 0; f < 4; f++) {
        if (only_fmt >= 0 && f != only_fmt)
            continue;
        for (z = 0; z < nsizes; z++) {
            const size_t n = sizes[z];
            for (k = 0; k < K_COUNT; k++) {
                /* past 130 only the random kind segments and composes */
                if ((segmented || composed) && n > 130 && k != K_RANDOM)
                    continue;
                fill(a, n, f, k);
                fill(b, n, f, K_RANDOM);
                for (r = 0; r < 5; r++) {
                    if (composed) {
                        red_case(hw, sw, CFT_DOT, f, r, a, b, n, 0, KIND[k], &ncmp);
                        red_case(hw, sw, CFT_SUMSQ, f, r, a, NULL, n, 0, KIND[k], &ncmp);
                        red_case(hw, sw, CFT_SUMABS, f, r, a, NULL, n, 0, KIND[k], &ncmp);
                        if (n >= 3) {
                            red_case(hw, sw, CFT_DOT, f, r, a, b, n - n % 3, 3, KIND[k], &ncmp);
                            red_case(hw, sw, CFT_SUMSQ, f, r, a, NULL, n - n % 3, 3,
                                     KIND[k], &ncmp);
                            red_case(hw, sw, CFT_SUMABS, f, r, a, NULL, n - n % 3, 3,
                                     KIND[k], &ncmp);
                        }
                    } else if (segmented) {
                        size_t q;
                        for (q = 0; q <= 6; q++) {
                            const size_t seg = q < 6 ? segs[q] : n;
                            const size_t nn = n - n % seg;
                            if (!nn)
                                continue;
                            red_case(hw, sw, CFT_SUM, f, r, a, NULL, nn, seg, KIND[k], &ncmp);
                            red_case(hw, sw, CFT_MAXALL, f, r, a, NULL, nn, seg, KIND[k],
                                     &ncmp);
                        }
                    } else {
                        red_case(hw, sw, CFT_SUM, f, r, a, NULL, n, 0, KIND[k], &ncmp);
                        red_case(hw, sw, CFT_MAXALL, f, r, a, NULL, n, 0, KIND[k], &ncmp);
                    }
                }
            }
        }
        if (!segmented && !composed) {
            /* n = 1, a signalling NaN: verbatim, no flags, on both */
            const size_t esz = cft_format_size((cft_format)f);
            unsigned char out[32];
            uint32_t fl = 0xFFu;
            const unsigned long top = (1ul << EXPW[f]) - 1;
            elem(a, f, 0, top, 3);
            memset(out, 0, sizeof out);
            CHECK(cft_reduce(hw, CFT_SUM, (cft_format)f, CFT_RNE, a, NULL, out, 1, &fl,
                             NULL) == CFT_OK && same(out, a, esz) && fl == 0,
                  "%s: a one-element sum of a signalling NaN is not that element with "
                  "no flags (flags 0x%x)", cft_format_name((cft_format)f), (unsigned)fl);
            ncmp++;
        }
    }
    printf("  %s: %ld reductions compared with the software handle (%lu sizes "
           "from %lu to %lu, %s, every attribute), %.1f s, %d failed\n",
           composed ? "compose" : segmented ? "seg" : "reduce", ncmp,
           (unsigned long)nsizes, (unsigned long)sizes[0],
           (unsigned long)sizes[nsizes - 1],
           only_fmt >= 0 ? cft_format_name((cft_format)only_fmt) : "every format",
           (double)(clock() - t0) / CLOCKS_PER_SEC, failures - before);
    free(a);
    free(b);
}

/* ---- a scalar operand that d aliases ------------------------------------ */

static void leg_alias(cft_device *hw, cft_device *sw)
{
    /* d[i] = a[0] + c[i] with d == a: the software loop writes d[0] = a[0]
     * first and then re-reads element 0 for i >= 1; a staged GPU reads the
     * snapshot it uploaded. Each is held to its own rule here. */
    enum { N = 24 };
    const size_t esz = 8;
    unsigned char dh[N * 8], ds[N * 8], c[N * 8], a0[8], snap[N * 8], chain[N * 8];
    unsigned char run0[8];
    cft_elem_args E;
    cft_status st;
    size_t i;
    const int before = failures;

    printf("alias\n");
    fill(c, N, CFT_FP64, K_RANDOM);
    fill(a0, 1, CFT_FP64, K_RANDOM);
    /* the rules, each computed one element at a time on the software handle */
    for (i = 0; i < N; i++) {
        CHECK(cft_run(sw, CFT_ADD, CFT_FP64, CFT_RNE, a0, NULL, c + i * esz,
                      snap + i * esz, 1, NULL, NULL) == CFT_OK, "the snapshot rule");
        memcpy(run0, i ? chain : a0, esz);
        CHECK(cft_run(sw, CFT_ADD, CFT_FP64, CFT_RNE, run0, NULL, c + i * esz,
                      chain + i * esz, 1, NULL, NULL) == CFT_OK, "the re-read rule");
    }
    for (i = 0; i < 2; i++) {
        cft_device *dev = i ? sw : hw;
        unsigned char *d = i ? ds : dh;
        memset(d, 0, sizeof dh);
        memcpy(d, a0, esz);
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = d;                        /* the scalar, which d aliases */
        E.c = c;
        E.d = d;
        E.n = N;
        E.scalar_mask = 1u;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_OK, "cft_run_ex on %s: %s", i ? "software" : "GPU",
              cft_last_error());
    }
    CHECK(same(dh, snap, sizeof dh), "the GPU, a scalar a that d aliases: not the "
          "snapshot of a[0] for every element");
    CHECK(same(ds, chain, sizeof ds), "the software handle, a scalar a that d "
          "aliases: not element 0 re-read after it is written");
    printf("  alias: the GPU reads a snapshot of the scalar for every element "
           "(%s); the software loop re-reads element 0 after writing it (%s); the "
           "two %s; %d failed\n", same(dh, snap, sizeof dh) ? "held" : "NOT held",
           same(ds, chain, sizeof ds) ? "held" : "NOT held",
           same(dh, ds, sizeof dh) ? "agree" : "differ from element 1 on, as "
           "documented", failures - before);
}

/* ---- two handles ---------------------------------------------------------- */

static int run_cmp(cft_device *h, cft_device *sw, const char *who, int fmt)
{
    enum { N = 1000 };
    static unsigned char a[N * 32], b[N * 32], c[N * 32], dh[N * 32], ds[N * 32];
    uint32_t fh = 0, fs = 0;
    const size_t esz = cft_format_size((cft_format)fmt);
    cft_status st;
    fill(a, N, fmt, K_RANDOM);
    fill(b, N, fmt, K_RANDOM);
    fill(c, N, fmt, K_RANDOM);
    st = cft_run(h, CFT_FMA, (cft_format)fmt, CFT_RNE, a, b, c, dh, N, &fh, NULL);
    CHECK(st == CFT_OK, "%s: cft_run %s", who, cft_last_error());
    CHECK(cft_run(sw, CFT_FMA, (cft_format)fmt, CFT_RNE, a, b, c, ds, N, &fs, NULL) ==
              CFT_OK, "software");
    CHECK(same(dh, ds, N * esz) && fh == fs, "%s: an FMA run differs from the "
          "software handle's", who);
    return st == CFT_OK && same(dh, ds, N * esz) && fh == fs;
}

static void leg_two(const char *artifact, cft_device *sw)
{
    cft_device *h1 = NULL, *h2 = NULL;
    const int before = failures;
    int ok = 1;
    printf("two\n");
    CHECK(cft_open(artifact, 0, &h1) == CFT_OK && cft_open(artifact, 0, &h2) == CFT_OK,
          "two handles on %s: %s", artifact, cft_last_error());
    if (h1 && h2) {
        ok &= run_cmp(h1, sw, "the first handle", CFT_FP256);
        ok &= run_cmp(h2, sw, "the second handle", CFT_FP256);
        ok &= run_cmp(h1, sw, "the first handle again", CFT_FP64);
        cft_close(h1);
        h1 = NULL;
        ok &= run_cmp(h2, sw, "the second handle, the first closed", CFT_FP32);
    }
    cft_close(h1);
    cft_close(h2);
    printf("  two handles on %s, used in turn and closed in turn: %s\n", artifact,
           ok ? "each agreed with the software handle" : "FAILED");
    {
        cft_device *d1 = NULL;
        const cft_status s1 = cft_open("hip:1", 0, &d1);
        if (s1 == CFT_OK) {
            cft_device *d0 = NULL;
            CHECK(cft_open("hip:0", 0, &d0) == CFT_OK, "hip:0 beside hip:1");
            if (d0) {
                ok = run_cmp(d0, sw, "hip:0 beside hip:1", CFT_FP256) &
                     run_cmp(d1, sw, "hip:1 beside hip:0", CFT_FP256) &
                     run_cmp(d0, sw, "hip:0 again", CFT_FP128);
                printf("  two devices, hip:0 and hip:1 in one process: %s\n",
                       ok ? "each agreed with the software handle" : "FAILED");
            }
            cft_close(d0);
            cft_close(d1);
        } else {
            nrun("  two devices",
                 "the HIP runtime shows this process one GPU (hip:1 is refused: "
                 "CFT_ERR_NO_DEVICE), so there is no second device to hold apart");
        }
    }
    printf("  two: %d failed\n", failures - before);
}

/* ---- the plants (a HIP_PLANTS=1 build) ------------------------------------ */

static void env_refused(const char *artifact, const char *var, const char *val)
{
    cft_device *h = NULL;
    cft_status st;
    put_env(var, val);
    st = cft_open(artifact, 0, &h);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT && h == NULL && strstr(cft_last_error(), var),
          "%s=\"%s\": %s (%s) - a malformed value must be refused by name at open",
          var, val, cft_strerror(st), cft_last_error());
    printf("    %s=\"%s\": %s - %s\n", var, val, cft_strerror(st), cft_last_error());
    if (h)
        cft_close(h);
    put_env(var, NULL);
}

static void leg_plants(const char *artifact, cft_device *sw)
{
    static const char *const badplant[] = {"bogus", "flip ", "FLIP", "flip,drop-flag",
                                           "1", "stale-publish"};
    static const char *const badchunk[] = {"abc", "7", "0", "12", "64 ", "-8",
                                           "1073741832", "0x40"};
    cft_device *h = NULL;
    cft_status st;
    size_t i;
    int plant_build;
    const int before = failures;

    printf("plants\n");
    env_refused(artifact, "CFT_HIP_INFO", "yes");
    put_env("CFT_HIP_PLANT", "bogus");
    st = cft_open(artifact, 0, &h);
    put_env("CFT_HIP_PLANT", NULL);
    plant_build = st != CFT_OK;
    if (h)
        cft_close(h);
    h = NULL;
    if (!plant_build) {
        nrun("  the plants", "this libcft is a default build, which compiles no plant "
             "and never reads CFT_HIP_PLANT (CFT_HIP_PLANT=bogus opened); build with "
             "HIP_PLANTS=1");
        printf("  plants: %d failed\n", failures - before);
        return;
    }
    for (i = 0; i < sizeof badplant / sizeof badplant[0]; i++)
        env_refused(artifact, "CFT_HIP_PLANT", badplant[i]);
    for (i = 0; i < sizeof badchunk / sizeof badchunk[0]; i++)
        env_refused(artifact, "CFT_HIP_CHUNK", badchunk[i]);

    /* fail-launch: the first launch reported failed after it ran; the call
     * fails by name and every later call is refused until the handle is
     * closed - and a new handle works */
    put_env("CFT_HIP_PLANT", "fail-launch");
    st = cft_open(artifact, 0, &h);
    put_env("CFT_HIP_PLANT", NULL);
    CHECK(st == CFT_OK, "open with fail-launch: %s", cft_last_error());
    if (h) {
        static unsigned char a[64 * 32], d[64 * 32];
        uint32_t fl = 0;
        cft_program *prog = NULL;
        /* fma r3, r0, r1, r2; deposit r3; halt - fp64 */
        static unsigned char img[32 + 24];
        static const uint32_t hdr[8] = {0x50544643u, 1, 3, 0, 1, 1, 0, 0};
        const uint64_t w[3] = {0u | (3u << 8) | (0u << 12) | (1u << 16) | (2u << 20),
                               3u | (3u << 12) | (1ull << 31), 1ull << 31};
        cft_run_args A;
        int j, k;
        for (j = 0; j < 8; j++)
            for (k = 0; k < 4; k++)
                img[4 * j + k] = (unsigned char)(hdr[j] >> (8 * k));
        for (j = 0; j < 3; j++)
            for (k = 0; k < 8; k++)
                img[32 + 8 * j + k] = (unsigned char)(w[j] >> (8 * k));
        fill(a, 64, CFT_FP64, K_RANDOM);
        st = cft_run(h, CFT_ADD, CFT_FP64, CFT_RNE, a, NULL, a, d, 64, &fl, NULL);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "fail-launch") &&
              strstr(cft_last_error(), "close it and open it again"),
              "fail-launch: the failed launch returned %s, \"%s\"", cft_strerror(st),
              cft_last_error());
        printf("    fail-launch, the run: %s - %s\n", cft_strerror(st), cft_last_error());
        st = cft_run(h, CFT_ADD, CFT_FP64, CFT_RNE, a, NULL, a, d, 64, &fl, NULL);
        CHECK(st == CFT_ERR_INTERNAL &&
              strstr(cft_last_error(), "left in an unknown state") &&
              strstr(cft_last_error(), "close it and open it again"),
              "poisoned: the next run returned %s, \"%s\"", cft_strerror(st),
              cft_last_error());
        printf("    poisoned, the next run: %s - %s\n", cft_strerror(st), cft_last_error());
        st = cft_reduce(h, CFT_SUM, CFT_FP64, CFT_RNE, a, NULL, d, 64, &fl, NULL);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "close it and open it again"),
              "poisoned: a reduction returned %s, \"%s\"", cft_strerror(st), cft_last_error());
        st = cft_reduce_seg(h, CFT_MAXALL, CFT_FP64, CFT_RNE, a, NULL, d, 64, 8, &fl, NULL);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "close it and open it again"),
              "poisoned: a segmented reduction returned %s, \"%s\"", cft_strerror(st),
              cft_last_error());
        CHECK(cft_program_load(h, img, sizeof img, &prog) == CFT_OK,
              "loading a three-instruction program: %s", cft_last_error());
        if (prog) {
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a;
            A.b = a;
            A.c = a;
            A.n = 64;
            A.deposits = d;
            st = cft_program_run_ex(prog, &A);
            CHECK(st == CFT_ERR_INTERNAL &&
                  strstr(cft_last_error(), "close it and open it again"),
                  "poisoned: a program run returned %s, \"%s\"", cft_strerror(st),
                  cft_last_error());
            printf("    poisoned, a program: %s - %s\n", cft_strerror(st), cft_last_error());
            cft_program_free(prog);
        }
        cft_close(h);
        h = NULL;
        CHECK(cft_open(artifact, 0, &h) == CFT_OK && run_cmp(h, sw, "a new handle after "
              "the poisoned one closed", CFT_FP64), "a new handle after the poisoned one");
        cft_close(h);
    }
    printf("  plants: %d failed\n", failures - before);
}

int main(int argc, char **argv)
{
    const char *artifact = NULL, *legs = "open,reduce,seg,compose,alias,two,plants";
    cft_device *hw = NULL, *sw = NULL;
    int only_fmt = -1, which = 0, i;
    cft_status st;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-l") && i + 1 < argc) {
            legs = argv[++i];
        } else if (!strcmp(argv[i], "-f") && i + 1 < argc) {
            const char *w = argv[++i];
            int f;
            for (f = 0; f < 4; f++)
                if (!strcmp(w, cft_format_name((cft_format)f)))
                    only_fmt = f;
            if (only_fmt < 0) {
                fprintf(stderr, "hip-test: unknown format %s\n", w);
                return 2;
            }
        } else if (!strcmp(argv[i], "-s") && i + 1 < argc) {
            const char *w = argv[++i];
            which = !strcmp(w, "small") ? 1 : !strcmp(w, "large") ? 2
                  : !strcmp(w, "all") ? 0 : -1;
            if (which < 0) {
                fprintf(stderr, "hip-test: -s small, large or all\n");
                return 2;
            }
        } else if (argv[i][0] != '-' && !artifact) {
            artifact = argv[i];
        } else {
            fprintf(stderr, "usage: %s hip:N [-l open,reduce,seg,compose,alias,two,"
                    "plants] [-f fp32|fp64|fp128|fp256] [-s small|large|all]\n",
                    argv[0]);
            return 2;
        }
    }
    if (!artifact) {
        fprintf(stderr, "usage: %s hip:N [-l LEGS] [-f FORMAT] [-s small|large|all]\n",
                argv[0]);
        return 2;
    }
    printf("libcft build %s\n", cft_build_id());
    if (cft_open(NULL, 0, &sw) != CFT_OK) {
        fprintf(stderr, "the software backend: %s\n", cft_last_error());
        return 2;
    }
    st = cft_open(artifact, 0, &hw);
    if (st != CFT_OK) {
        const int no_backend = st == CFT_ERR_NO_DEVICE &&
                               strstr(cft_last_error(), "no GPU backend") != NULL;
        printf("cft_open(\"%s\"): %s - %s\n", artifact, cft_strerror(st),
               cft_last_error());
        if (no_backend) {
            CHECK(strstr(cft_last_error(), "HIP=1") != NULL, "the sentence of a build "
                  "with no GPU backend does not say how to build one");
            nrun("every leg", "this libcft build has no GPU backend (HIP=0), and what "
                 "it says of hip:N is the refusal above");
            printf("\n%d checks, %d failed, %d NOT RUN\n", checks, failures, not_run);
            cft_close(sw);
            return failures ? 1 : 0;
        }
        cft_close(sw);
        return 2;
    }
    if (strstr(legs, "open"))
        leg_open(artifact, hw, sw);
    if (strstr(legs, "reduce")) {
        make_sizes(which);
        leg_reduce(hw, sw, only_fmt, 0, 0);
    }
    if (strstr(legs, "seg")) {
        make_sizes(which);
        leg_reduce(hw, sw, only_fmt, 1, 0);
    }
    if (strstr(legs, "compose")) {
        make_sizes(which);
        leg_reduce(hw, sw, only_fmt, 0, 1);
    }
    if (strstr(legs, "alias"))
        leg_alias(hw, sw);
    if (strstr(legs, "two"))
        leg_two(artifact, sw);
    if (strstr(legs, "plants"))
        leg_plants(artifact, sw);
    cft_close(hw);
    cft_close(sw);
    if (shown > 60)
        printf("  (%d FAIL lines past the first 60 not shown)\n", shown - 60);
    printf("\n%d checks, %d failed, %d NOT RUN\n", checks, failures, not_run);
    if (!failures)
        printf("hip-test: every check that ran passed%s\n",
               not_run ? " - the NOT RUN lines above say what did not run" : "");
    return failures ? 1 : 0;
}
