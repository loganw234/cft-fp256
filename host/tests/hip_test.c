/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * hip-test - what only the GPU backend has, through the public API alone.
 *
 *     hip-test hip:N [-l LEGS] [-f FORMAT] [-s small|large|all]
 *
 * LEGS is a comma list of the legs below (default: all of them); -f
 * keeps one format; -s chooses the reduction sizes (default all). The
 * legs:
 *
 *   open      cft_open's grammar for "hip:N" (each malformed spelling
 *             refused by name, with the grammar in the sentence), index
 *             1, a device past the count, an xclbin; the capability word
 *             (formats 15, groups 0x7F, tiles 1, version 0, flags
 *             readable, backend "hip", buffers_resident 1, the software
 *             handle's four capacities and all its features, 0x7ff1f as
 *             the software handle's); the image identity refused by
 *             name. What hip:N lacked in round 1, one item a parcel of
 *             round 2:
 *               nothing of round 2's G2B any more: CFT_SEQ_FEAT_INDEXED
 *               is published, and cft_open_ex opens hip:N at 256, 512,
 *               1,024 and 2,048 slots (max_scratch says so) and refuses
 *               4,096 by name, 3 and 0x7fffffff as no power of two, and
 *               an xclbin's depth by the generic sentence; the default
 *               handle's max_scratch is still 256;
 *
 *               CFT_SEQ_FEAT_AUGADD no longer: published since round 2's
 *               G2A, and held by the aug leg below.
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
 *   buffers   resident buffers (cft_alloc), each scenario held to the
 *             software handle running the same calls on plain memory: a
 *             publish takes effect, and a repeat binds resident; a publish
 *             over unread results refused, nothing changed; d == a in
 *             place; an output shifted over its own input (staged, the
 *             snapshot rule); a masked program into a resident window,
 *             before and after an unmasked one; a host write (a
 *             reduction's result) between runs, with a moved, unaligned
 *             window after it; reductions over resident windows. With
 *             plants: a failed upload (CFT_HIP_UPLOAD=fail-fill) and its
 *             retry, and a failed run's outputs LOST (fail-launch).
 *   plants    (a HIP_PLANTS=1 build) CFT_HIP_PLANT, CFT_HIP_CHUNK,
 *             CFT_HIP_PAGE and CFT_HIP_INFO malformed and refused by name;
 *             fail-launch's poisoned handle. In a default build: NOT RUN,
 *             named.
 *   (round 2's G2A: its legs here)
 *   aug       augmentedAddition: cft_augmented_add, _sub and _mul against
 *             the software handle, r, e and the flags of every call, at
 *             every format, over every pair of a pool of each class 9.5
 *             has a rule for (signed zeros, subnormals, the largest
 *             finite, infinities, quiet and signalling NaNs, ties where
 *             roundTiesTowardZero and roundTiesToEven part, the overflow
 *             threshold and one ulp past it, a product residual the
 *             format cannot hold): one call a pair, then the pairs in one
 *             call and 300 in another (a plant build's CFT_HIP_CHUNK
 *             cuts them); r or e over a or b; r == e, NULLs, bad formats
 *             and n = 0 refused or answered as the software handle; the
 *             same in cft_alloc buffers, outputs left on the device until
 *             read back, a second call binding all four with no page
 *             moved; a program of AUGADD and AUGERR with rd = ra and a
 *             quiet region. With plants: a failed call's outputs LOST.
 *   (round 2's G2B: its legs here)
 *   indexed   index tables (R16) against the software handle, bit for bit
 *             with flags, counts, lane bytes and scratch-out: cft_run_ex
 *             with a table on a, b, c alone, two and three at once, at
 *             one opcode of each elementwise group, a scalar beside a
 *             table, every format and attribute, n of 1, 8, 9, 300 and
 *             5,000, each source longer than n (indices reaching its last
 *             element) and shorter, one entry in five CFT_IDX_NONE, and d
 *             over a source refused; cft_program_run_ex with the three
 *             tables and the scratch table together (a pool longer than
 *             the block), with a lane mask, a bank, a strict access past
 *             the depth and the lane bytes, and a table past its source
 *             refused with nothing run; resident sources, tables and
 *             deposits (the second run binding resident, a table
 *             republished between runs, and in a plant build a table in
 *             a LOST buffer refused); a 96 MiB source, larger than any
 *             stage, read through a table that crosses many chunks.
 *   depth     cft_open_ex at 256, 512, 1,024 and 2,048 slots, each against
 *             a software handle opened at the same depth: an STX/LDX walk
 *             of depth + 44 slots, which reaches past 256 and wraps at
 *             the depth (plain) or is reported past it (strict); a static
 *             slot at depth - 1 runs and one at the depth is refused at
 *             load (max_scratch); at 512 a 273-slot program with a
 *             scratch-in and scratch-out block of 273 (cft-debris's
 *             degree-8 field), refused on a 256-slot handle; slot 256 on
 *             the default handle and slot 2,047 on a 256-slot one refused;
 *             and a 2,048-slot handle beside the default, both run.
 *   (round 2's G2C: its legs here)
 *   divsqrt   the divide and the square root: (a) the whole-operation
 *             images (divfull_images.h, divsqrt.c's CFT_DIVSQRT_FULL=1
 *             route) loaded on hip:N - the loader's answer printed for each
 *             of the eight, a refusal with its sentence a failure - and run
 *             with divsqrt.c's bank at every attribute on hip:N and on the
 *             software handle, n 1, 577 and 5,000, over every pair of a
 *             pool of the classes a divide has a rule for (the root's lanes
 *             its classes): both deposits of every lane, the counts, the
 *             run's flags and STATUS, byte for byte, and at fp64 a
 *             signalling NaN in each position quieted with INVALID in
 *             deposit 1; (b) the same with a, b and the deposits in
 *             cft_alloc buffers, left on the device, a second run binding
 *             them with no page moved, and with plants a failed run's
 *             deposits LOST; (c) cft_div and cft_sqrt through the API, each
 *             of the three routes forced here (CFT_DIVSQRT_SEQ=0, both
 *             unset, CFT_DIVSQRT_FULL=1), at every format and attribute, n
 *             1 (a call a case), 577 and 5,000, d over a and over b, n = 0,
 *             NULLs and bad formats, against the software handle's default
 *             route; and in a plant build the ROUTE PROOF: a marker program
 *             before each call, then the plant build's probe of the last
 *             program run says which route ran (its head), a check the
 *             bits cannot make: a refused image falls through to an equal
 *             answer.
 *   (round 3's G3A: its legs here)
 *   fixed     the fixed tier (CFT_HIP_TIER): (a) "", generic and fixed open
 *             and Fixed, FIXED, " fixed", "fixed ", 1, both and gen are
 *             refused by name with no handle; (b) fp256 FMA, ADD, SUB and
 *             MUL at every attribute on a fixed-tier handle against the
 *             software handle, bits and flags - a call a case over a pool
 *             of every class the FMA's rules part (signed zeros,
 *             subnormals, the smallest normal, 1, 1 + u, the largest
 *             finite and half its ulp, infinities, quiet and signalling
 *             NaNs, exact ties, u/2), then every triple of a larger pool
 *             in one call and 5,000 random triples in another - and the
 *             same on a generic-tier handle (the control) and at fp32,
 *             fp64 and fp128 on the fixed one (which run k_run); (c)
 *             every other opcode cft_run takes at fp256 on the fixed
 *             handle; (d) the forms of a call: a scalar a, b or c (all
 *             seven masks), NULL b and c, d == a in place, n = 0 and
 *             refusals; (e) a, b, c and d resident: the software
 *             handle's bits, d left on the device, a second call moving
 *             no page, an output shifted over its input staged, and with
 *             plants a failed run's d LOST; (f) in a plant build, the
 *             ROUTE PROOF: after every call, the plant build's probe of
 *             the last cft_run says which kernel ran - the fixed one for
 *             fp256 FMA, ADD, SUB and MUL on the fixed handle, the
 *             generic one for every other call - a check the bits cannot
 *             make, since a fall-through gives the same bits.
 *             Round 3's G3A2: fp128 is a covered format too - (b) on both
 *             handles and (c) to (e) at fp128 as at fp256, fp32 and fp64
 *             the formats left on k_run, and the route's kernel 1
 *             (k_run256) for fp256 and 2 (k_run128) for fp128, by the
 *             leg's own fx_want, never the library's fixed_covers; the
 *             failures are counted by format at the end; and a default
 *             build with CFT_HIP_PLANT set is refused by name, exit 2,
 *             no check counted (it has no plants to apply).
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
/* round 2's G2C: the whole-operation images (static const arrays, read by
 * the divsqrt leg alone), as divsqrt.c loads them */
#include "../src/divfull_images.h"

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
    /* The software handle's features, named one by one; hip:N publishes
     * them all since round 2: `lacks` is 0, each of round 2's parcels
     * having deleted its own line of it. */
    const uint32_t sw_feat = (CFT_SEQ_FEAT_WIDE_CONST | CFT_SEQ_FEAT_REGS32 |
                              CFT_SEQ_FEAT_BANK_PTR | CFT_SEQ_FEAT_KX9 |
                              CFT_ALU_EXT_IMUL | CFT_SEQ_FEAT_SCRATCH |
                              CFT_SEQ_FEAT_SCRATCH_IO |
                              CFT_SEQ_FEAT_SCRATCH_STRICT | CFT_SEQ_FEAT_SCALAR |
                              CFT_FEAT_REDUCE_SEG | CFT_SEQ_FEAT_INDEXED |
                              CFT_SEQ_FEAT_LANE_MASK | CFT_SEQ_FEAT_AUGADD |
                              CFT_SEQ_FEAT_SCRATCH_STEP | CFT_SEQ_FEAT_LANE_FLAGS |
                              CFT_SEQ_FEAT_FLAG_CONTROL);
    uint32_t lacks = 0, want_feat;
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
    /* round 2 publishes the two one parcel at a time: each deletes its own line */
    want_feat = sw_feat & ~lacks;
    CHECK(c.seq_features == want_feat &&
          c.seq_features == (s.seq_features & ~lacks),
          "seq_features 0x%x: wanted 0x%x, the software handle's 0x%x less 0x%x",
          (unsigned)c.seq_features, (unsigned)want_feat, (unsigned)s.seq_features,
          (unsigned)lacks);
    CHECK(c.max_deposits == s.max_deposits && c.max_insns == s.max_insns &&
          c.max_consts == s.max_consts && c.max_scratch == s.max_scratch,
          "capacities %u/%u/%u/%u, the software handle's %u/%u/%u/%u",
          (unsigned)c.max_deposits, (unsigned)c.max_insns, (unsigned)c.max_consts,
          (unsigned)c.max_scratch, (unsigned)s.max_deposits, (unsigned)s.max_insns,
          (unsigned)s.max_consts, (unsigned)s.max_scratch);
    CHECK(c.buffers_resident == 1, "buffers_resident %d: the GPU keeps device "
          "copies of a cft_alloc'd buffer", c.buffers_resident);
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

    /* the depth (round 2's G2B): 256 to 2,048 open, each in max_scratch;
     * past the cap, no power of two, and an xclbin's depth refused by
     * their sentences; the default handle's is still 256 */
    CHECK(c.max_scratch == 256, "the default handle's max_scratch is %u, not 256",
          (unsigned)c.max_scratch);
    {
        static const uint32_t ok[4] = {256, 512, 1024, 2048};
        static const struct {
            const char *art;
            uint32_t depth;
            cft_status want;
            const char *says, *also;
        } refuse[] = {
            {NULL, 4096, CFT_ERR_UNSUPPORTED, "slots a lane the GPU backend honours",
             "2048 is the card's depth"},
            {NULL, 3, CFT_ERR_INVALID_ARGUMENT, "is not a power of two", "1..32768"},
            {NULL, 0x7fffffffu, CFT_ERR_INVALID_ARGUMENT, "is not a power of two",
             "1..32768"},
            {"cft_hw_emu.xclbin", 256, CFT_ERR_UNSUPPORTED, "names a device, whose depth "
             "its image fixes", "SOFTWARE handle's depth"}};
        for (i = 0; i < 4; i++) {
            cft_caps hc;
            memset(&oa, 0, sizeof oa);
            oa.struct_size = sizeof oa;
            oa.artifact = artifact;
            oa.scratch_depth = ok[i];
            memset(&hc, 0, sizeof hc);
            hc.struct_size = sizeof hc;
            h = NULL;
            st = cft_open_ex(&oa, &h);
            CHECK(st == CFT_OK && h && cft_get_caps(h, &hc) == CFT_OK &&
                  hc.max_scratch == ok[i] && !strcmp(hc.backend, "hip") &&
                  hc.seq_features == c.seq_features,
                  "cft_open_ex(%s, scratch_depth %u): %s, \"%s\", max_scratch %u",
                  artifact, (unsigned)ok[i], cft_strerror(st), cft_last_error(),
                  (unsigned)hc.max_scratch);
            printf("    cft_open_ex(%s, scratch_depth %u): %s, max_scratch %u\n", artifact,
                   (unsigned)ok[i], cft_strerror(st), (unsigned)hc.max_scratch);
            cft_close(h);
        }
        for (i = 0; i < sizeof refuse / sizeof refuse[0]; i++) {
            memset(&oa, 0, sizeof oa);
            oa.struct_size = sizeof oa;
            oa.artifact = refuse[i].art ? refuse[i].art : artifact;
            oa.scratch_depth = refuse[i].depth;
            h = NULL;
            st = cft_open_ex(&oa, &h);
            CHECK(st == refuse[i].want && h == NULL &&
                  strstr(cft_last_error(), refuse[i].says) &&
                  strstr(cft_last_error(), refuse[i].also),
                  "cft_open_ex(%s, scratch_depth %lu): %s, \"%s\" - wanted %s, saying "
                  "\"%s\"", oa.artifact, (unsigned long)refuse[i].depth, cft_strerror(st),
                  cft_last_error(), cft_strerror(refuse[i].want), refuse[i].says);
            printf("    cft_open_ex(%s, scratch_depth %lu): %s - %s\n", oa.artifact,
                   (unsigned long)refuse[i].depth, cft_strerror(st), cft_last_error());
            if (h)
                cft_close(h);
        }
    }
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

/* ---- resident buffers ------------------------------------------------------ */

struct rb {
    cft_buffer *b;
    unsigned char *p;
};

static int rb_alloc(cft_device *dev, struct rb *r, size_t bytes)
{
    r->b = NULL;
    r->p = NULL;
    if (cft_alloc(dev, bytes, &r->b) != CFT_OK)
        return 0;
    r->p = (unsigned char *)cft_buffer_data(r->b);
    return r->p != NULL;
}

static void rb_free(struct rb *r)
{
    cft_buffer_free(r->b);
    r->b = NULL;
    r->p = NULL;
}

static cft_buffer_info rb_info(const struct rb *r)
{
    cft_buffer_info bi;
    memset(&bi, 0, sizeof bi);
    bi.struct_size = sizeof bi;
    (void)cft_buffer_get_info(r->b, &bi);
    return bi;
}

/* the mirror filled from `src`, then published */
static int rb_put(struct rb *r, const unsigned char *src, size_t bytes)
{
    memcpy(r->p, src, bytes);
    return cft_buffer_to_device(r->b) == CFT_OK;
}

/* "deposit fma(a, b, c); halt" at fp64: leg_plants' three instructions */
static void fma_image(unsigned char img[56])
{
    static const uint32_t hdr[8] = {0x50544643u, 1, 3, 0, 1, 1, 0, 0};
    const uint64_t w[3] = {0u | (3u << 8) | (0u << 12) | (1u << 16) | (2u << 20),
                           3u | (3u << 12) | (1ull << 31), 1ull << 31};
    int j, k;
    for (j = 0; j < 8; j++)
        for (k = 0; k < 4; k++)
            img[4 * j + k] = (unsigned char)(hdr[j] >> (8 * k));
    for (j = 0; j < 3; j++)
        for (k = 0; k < 8; k++)
            img[32 + 8 * j + k] = (unsigned char)(w[j] >> (8 * k));
}

static void leg_buffers(const char *artifact, cft_device *hw, cft_device *sw)
{
    enum { N = 200 };                   /* fp64: 1,600 bytes, pages at 256 */
    const size_t E = 8, NB = N * 8;
    static unsigned char x[N * 32], y[N * 32], z[N * 32], want[3 * N * 32],
        got[3 * N * 32], tmp[N * 32];
    struct rb A, B, D;
    cft_buffer_info i1, i2;
    uint32_t fl = 0, fs = 0;
    cft_status st;
    int f, plant_build;
    const int before = failures;

    printf("buffers\n");
    A.b = B.b = D.b = NULL;
    fill(x, N, CFT_FP64, K_RANDOM);
    fill(y, N, CFT_FP64, K_RANDOM);
    fill(z, N, CFT_FP64, K_RANDOM);

    /* 1. a publish takes effect, and a repeat binds resident; at fp64 and
     *    fp256 (a page is eight fp256 elements) */
    for (f = 1; f <= 3; f += 2) {
        const size_t esz = cft_format_size((cft_format)f), bytes = N * esz;
        unsigned char *x2 = tmp;
        fill(x, N, f, K_RANDOM);
        fill(x2, N, f, K_RANDOM);
        CHECK(rb_alloc(hw, &A, bytes) && rb_alloc(hw, &D, bytes), "cft_alloc: %s",
              cft_last_error());
        if (!A.b || !D.b)
            goto out;
        CHECK(rb_put(&A, x, bytes), "publishing a");
        CHECK(cft_run(hw, CFT_ABS, (cft_format)f, CFT_RNE, A.p, NULL, NULL, D.p, N, &fl,
                      NULL) == CFT_OK && cft_buffer_from_device(D.b) == CFT_OK,
              "the first run: %s", cft_last_error());
        CHECK(cft_run(sw, CFT_ABS, (cft_format)f, CFT_RNE, x, NULL, NULL, want, N, &fs,
                      NULL) == CFT_OK, "software");
        CHECK(same(D.p, want, bytes) && fl == fs, "%s: a resident run differs from the "
              "software handle's", cft_format_name((cft_format)f));
        i1 = rb_info(&A);
        CHECK(cft_run(hw, CFT_ABS, (cft_format)f, CFT_RNE, A.p, NULL, NULL, D.p, N, &fl,
                      NULL) == CFT_OK && cft_buffer_from_device(D.b) == CFT_OK,
              "the repeat: %s", cft_last_error());
        i2 = rb_info(&A);
        CHECK(i1.resident == 1 && i2.resident_binds == i1.resident_binds + 1 &&
              i2.staged_binds == i1.staged_binds,
              "%s: the repeat with nothing published was not resident (resident %d, "
              "binds %llu/%llu then %llu/%llu, \"%s\")", cft_format_name((cft_format)f),
              i1.resident, (unsigned long long)i1.resident_binds,
              (unsigned long long)i1.staged_binds, (unsigned long long)i2.resident_binds,
              (unsigned long long)i2.staged_binds, i2.staged_why);
        CHECK(rb_put(&A, x2, bytes), "republishing a");
        CHECK(cft_run(hw, CFT_ABS, (cft_format)f, CFT_RNE, A.p, NULL, NULL, D.p, N, &fl,
                      NULL) == CFT_OK && cft_buffer_from_device(D.b) == CFT_OK,
              "the run after the publish: %s", cft_last_error());
        CHECK(cft_run(sw, CFT_ABS, (cft_format)f, CFT_RNE, x2, NULL, NULL, want, N, &fs,
                      NULL) == CFT_OK, "software");
        CHECK(same(D.p, want, bytes), "%s: cft_buffer_to_device did not take effect - "
              "the run used the bytes published before", cft_format_name((cft_format)f));
        i1 = rb_info(&A);
        CHECK(i1.staged_binds == i2.staged_binds + 1, "%s: the run after a publish "
              "uploaded nothing (\"%s\")", cft_format_name((cft_format)f), i1.staged_why);
        printf("  %s: a publish took effect; a repeat bound resident (binds %llu resident, "
               "%llu staged: \"%s\")\n", cft_format_name((cft_format)f),
               (unsigned long long)i1.resident_binds, (unsigned long long)i1.staged_binds,
               i1.staged_why);
        rb_free(&A);
        rb_free(&D);
    }
    fill(x, N, CFT_FP64, K_RANDOM);

    /* 2. a publish over unread results: refused, nothing changed */
    CHECK(rb_alloc(hw, &A, NB) && rb_alloc(hw, &D, NB), "cft_alloc: %s", cft_last_error());
    if (!A.b || !D.b)
        goto out;
    CHECK(rb_put(&A, x, NB), "publishing a");
    CHECK(cft_run(hw, CFT_ABS, CFT_FP64, CFT_RNE, A.p, NULL, NULL, D.p, N, &fl, NULL) ==
          CFT_OK, "a run into d: %s", cft_last_error());
    i1 = rb_info(&D);
    st = cft_buffer_to_device(D.b);
    {
        char said[600];
        snprintf(said, sizeof said, "%s", cft_last_error());
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && strstr(said, "never read back") &&
              i1.device_authority == 1 && rb_info(&D).device_authority == 1,
              "a publish over unread results: %s, \"%s\", authority %d", cft_strerror(st),
              said, i1.device_authority);
        printf("  a publish over unread results: %s - %s\n", cft_strerror(st), said);
    }
    CHECK(cft_buffer_from_device(D.b) == CFT_OK && cft_buffer_to_device(D.b) == CFT_OK &&
          rb_info(&D).device_authority == 0, "read back, then published: %s",
          cft_last_error());
    CHECK(cft_run(sw, CFT_ABS, CFT_FP64, CFT_RNE, x, NULL, NULL, want, N, &fs, NULL) ==
          CFT_OK && same(D.p, want, NB), "the results kept through the refusal");

    /* 3. d == a, in place, stays resident */
    CHECK(cft_run(hw, CFT_FMA, CFT_FP64, CFT_RNE, A.p, y, z, A.p, N, &fl, NULL) == CFT_OK &&
          cft_buffer_from_device(A.b) == CFT_OK, "in place: %s", cft_last_error());
    CHECK(cft_run(sw, CFT_FMA, CFT_FP64, CFT_RNE, x, y, z, want, N, &fs, NULL) == CFT_OK,
          "software");
    i1 = rb_info(&A);
    CHECK(same(A.p, want, NB) && fl == fs && !strstr(i1.staged_why, "overlaps"),
          "d == a in place: %s, \"%s\"", same(A.p, want, NB) ? "bits right" : "BITS WRONG",
          i1.staged_why);
    printf("  d == a in place: %s; a's last binding: %llu resident, %llu staged\n",
           same(A.p, want, NB) ? "the software handle's bits" : "WRONG",
           (unsigned long long)i1.resident_binds, (unsigned long long)i1.staged_binds);
    rb_free(&A);
    rb_free(&D);

    /* 4. an output shifted one element over its own input: the input is
     *    staged and every element reads the published value (the snapshot
     *    rule, as a staged run reads it); the software loop's sequential
     *    order is its own (leg alias says the same of a scalar) */
    CHECK(rb_alloc(hw, &A, NB + E), "cft_alloc: %s", cft_last_error());
    if (!A.b)
        goto out;
    memcpy(want, x, E);
    CHECK(cft_run(sw, CFT_ABS, CFT_FP64, CFT_RNE, x, NULL, NULL, want + E, N, &fs, NULL) ==
          CFT_OK, "software");
    for (f = 0; f < 2; f++) {
        memcpy(A.p, x, NB);
        CHECK(cft_buffer_to_device(A.b) == CFT_OK, "publishing: %s", cft_last_error());
        CHECK(cft_run(hw, CFT_ABS, CFT_FP64, CFT_RNE, A.p, NULL, NULL, A.p + E, N, &fl,
                      NULL) == CFT_OK && cft_buffer_from_device(A.b) == CFT_OK,
              "the shifted run: %s", cft_last_error());
        i1 = rb_info(&A);
        CHECK(same(A.p, want, NB + E) && strstr(i1.staged_why, "overlaps an output"),
              "an output shifted over its input (try %d): %s, \"%s\"", f + 1,
              same(A.p, want, NB + E) ? "the snapshot rule held" : "NOT the snapshot rule",
              i1.staged_why);
    }
    printf("  an output shifted over its input: the snapshot rule, twice; \"%s\"\n",
           i1.staged_why);
    rb_free(&A);

    /* 5. a masked program into a resident deposit window, before and after
     *    an unmasked one (verifier-V4's shape) */
    {
        unsigned char img[56], mask[(N + 7) / 8];
        cft_program *ph = NULL, *ps = NULL;
        cft_run_args R;
        int k, ok = 1;
        size_t i;
        fma_image(img);
        for (i = 0; i < sizeof mask; i++)
            mask[i] = (unsigned char)(0x5Bu ^ (unsigned)(i * 37u));
        CHECK(rb_alloc(hw, &D, NB) && cft_program_load(hw, img, sizeof img, &ph) == CFT_OK &&
              cft_program_load(sw, img, sizeof img, &ps) == CFT_OK, "the program: %s",
              cft_last_error());
        for (k = 0; k < 3 && ph && ps && D.b; k++) {
            /* k 0: masked over a sentinel; 1: unmasked; 2: masked over a new one */
            const int masked = k != 1;
            memset(D.p, k ? 0x3C : 0x5A, NB);
            memset(want, k ? 0x3C : 0x5A, NB);
            ok &= cft_buffer_to_device(D.b) == CFT_OK;
            memset(&R, 0, sizeof R);
            R.struct_size = sizeof R;
            R.a = x;
            R.b = y;
            R.c = z;
            R.n = N;
            R.lane_mask = masked ? mask : NULL;
            R.lane_mask_bytes = masked ? sizeof mask : 0;
            R.deposits = want;
            ok &= cft_program_run_ex(ps, &R) == CFT_OK;
            R.deposits = D.p;
            ok &= cft_program_run_ex(ph, &R) == CFT_OK;
            ok &= cft_buffer_from_device(D.b) == CFT_OK;
            CHECK(ok && same(D.p, want, NB), "a %s program into a resident window (step "
                  "%d): %s", masked ? "masked" : "unmasked", k + 1,
                  ok ? "lanes differ from the software handle's" : cft_last_error());
        }
        printf("  a masked program into a resident window, before and after an unmasked "
               "one: %s\n", ok ? "the software handle's bytes, masked lanes kept" : "FAILED");
        cft_program_free(ph);
        cft_program_free(ps);
        rb_free(&D);
    }

    /* 6. a host write between runs (a reduction's result, which device.c
     *    writes on the host), then a moved, unaligned window, then the
     *    read-back: every byte the software sequence's */
    {
        unsigned char *w = want;
        const size_t lenD = 3 * NB;
        CHECK(rb_alloc(hw, &D, lenD), "cft_alloc: %s", cft_last_error());
        if (!D.b)
            goto out;
        memset(D.p, 0x77, lenD);
        memset(w, 0x77, lenD);
        CHECK(cft_buffer_to_device(D.b) == CFT_OK, "publishing");
        /* the run into [0, N), its results left on the device */
        CHECK(cft_run(hw, CFT_ABS, CFT_FP64, CFT_RNE, x, NULL, NULL, D.p, N, &fl, NULL) ==
              CFT_OK, "the run: %s", cft_last_error());
        CHECK(cft_run(sw, CFT_ABS, CFT_FP64, CFT_RNE, x, NULL, NULL, w, N, &fs, NULL) ==
              CFT_OK, "software");
        /* the host write: a sum into element 5, inside the run's window */
        CHECK(cft_reduce(hw, CFT_SUM, CFT_FP64, CFT_RNE, y, NULL, D.p + 5 * E, N, &fl,
                         NULL) == CFT_OK, "the reduction into the buffer: %s",
              cft_last_error());
        CHECK(cft_reduce(sw, CFT_SUM, CFT_FP64, CFT_RNE, y, NULL, w + 5 * E, N, &fs,
                         NULL) == CFT_OK, "software");
        /* a moved window: 150 elements from element 103 (unaligned), over
         * the run's tail and past it */
        CHECK(cft_run(hw, CFT_NEG, CFT_FP64, CFT_RNE, z, NULL, NULL, D.p + 103 * E, 150, &fl,
                      NULL) == CFT_OK, "the moved window: %s", cft_last_error());
        CHECK(cft_run(sw, CFT_NEG, CFT_FP64, CFT_RNE, z, NULL, NULL, w + 103 * E, 150, &fs,
                      NULL) == CFT_OK, "software");
        /* and the host write again, beside the moved window's start */
        CHECK(cft_reduce(hw, CFT_SUM, CFT_FP64, CFT_RNE, x, NULL, D.p + 102 * E, 7, &fl,
                         NULL) == CFT_OK, "the second reduction: %s", cft_last_error());
        CHECK(cft_reduce(sw, CFT_SUM, CFT_FP64, CFT_RNE, x, NULL, w + 102 * E, 7, &fs,
                         NULL) == CFT_OK, "software");
        CHECK(cft_buffer_from_device(D.b) == CFT_OK, "the read-back: %s", cft_last_error());
        memcpy(got, D.p, lenD);
        {
            size_t i = 0;
            while (i < lenD && got[i] == w[i])
                i++;
            CHECK(i == lenD, "host writes between runs and a moved window: byte %lu "
                  "(element %lu) differs from the software sequence's",
                  (unsigned long)i, (unsigned long)(i / E));
            printf("  a host write between runs, a moved unaligned window, another host "
                   "write, the read-back: %s\n",
                   i == lenD ? "every byte the software sequence's" : "DIFFERS");
        }
        rb_free(&D);
    }

    /* 7. reductions over resident windows, whole and interior */
    {
        size_t q;
        static const size_t lo[3] = {0, 3, 17};
        CHECK(rb_alloc(hw, &A, NB) && rb_alloc(hw, &B, NB), "cft_alloc: %s", cft_last_error());
        if (!A.b || !B.b)
            goto out;
        CHECK(rb_put(&A, x, NB) && rb_put(&B, y, NB), "publishing");
        for (q = 0; q < 3; q++) {
            unsigned char rh[N * 8], rs_[N * 8];
            const size_t m = N - lo[q] - (q ? 8 : 0);
            CHECK(cft_reduce(hw, CFT_SUM, CFT_FP64, CFT_RNE, A.p + lo[q] * E, NULL, rh, m,
                             &fl, NULL) == CFT_OK &&
                  cft_reduce(sw, CFT_SUM, CFT_FP64, CFT_RNE, x + lo[q] * E, NULL, rs_, m,
                             &fs, NULL) == CFT_OK && same(rh, rs_, E) && fl == fs,
                  "a resident sum from element %lu: %s", (unsigned long)lo[q],
                  cft_last_error());
            CHECK(cft_reduce(hw, CFT_DOT, CFT_FP64, CFT_RNE, A.p + lo[q] * E, B.p + lo[q] * E,
                             rh, m, &fl, NULL) == CFT_OK &&
                  cft_reduce(sw, CFT_DOT, CFT_FP64, CFT_RNE, x + lo[q] * E, y + lo[q] * E,
                             rs_, m, &fs, NULL) == CFT_OK && same(rh, rs_, E) && fl == fs,
                  "a resident dot from element %lu: %s", (unsigned long)lo[q],
                  cft_last_error());
            CHECK(cft_reduce_seg(hw, CFT_MAXALL, CFT_FP64, CFT_RNE, A.p + lo[q] * E, NULL, rh,
                                 m - m % 8, 8, &fl, NULL) == CFT_OK &&
                  cft_reduce_seg(sw, CFT_MAXALL, CFT_FP64, CFT_RNE, x + lo[q] * E, NULL, rs_,
                                 m - m % 8, 8, &fs, NULL) == CFT_OK &&
                  same(rh, rs_, (m / 8) * E) && fl == fs,
                  "a resident segmented maximum from element %lu: %s",
                  (unsigned long)lo[q], cft_last_error());
        }
        i1 = rb_info(&A);
        CHECK(i1.resident_binds > 0, "the reductions never bound a resident (\"%s\")",
              i1.staged_why);
        printf("  reductions over resident windows (sum, dot, segmented maximum, from "
               "elements 0, 3 and 17): a's binds %llu resident, %llu staged\n",
               (unsigned long long)i1.resident_binds, (unsigned long long)i1.staged_binds);
        rb_free(&A);
        rb_free(&B);
    }

    /* 8. with plants: a failed upload and its retry; a failed run's outputs */
    {
        cft_device *h = NULL;
        put_env("CFT_HIP_PLANT", "bogus");
        st = cft_open(artifact, 0, &h);
        put_env("CFT_HIP_PLANT", NULL);
        plant_build = st != CFT_OK;
        if (h)
            cft_close(h);
    }
    if (!plant_build) {
        nrun("  a failed upload's retry, a failed run's outputs LOST",
             "this libcft is a default build, which has neither CFT_HIP_UPLOAD nor "
             "CFT_HIP_PLANT=fail-launch; build with HIP_PLANTS=1");
    } else {
        int planted, untouched, retry;
        size_t i;
        /* the failed upload: a stale page's copy fails, the run is refused
         * with the output untouched, and the retry uploads the new bytes */
        CHECK(rb_alloc(hw, &A, NB), "cft_alloc: %s", cft_last_error());
        if (!A.b)
            goto out;
        CHECK(rb_put(&A, x, NB), "publishing x");
        CHECK(cft_run(hw, CFT_ADD, CFT_FP64, CFT_RNE, A.p, NULL, z, got, N, &fl, NULL) ==
              CFT_OK, "the first run: %s", cft_last_error());
        CHECK(rb_put(&A, y, NB), "publishing y");
        memset(got, 0x5A, NB);
        put_env("CFT_HIP_UPLOAD", "fail-fill");
        st = cft_run(hw, CFT_ADD, CFT_FP64, CFT_RNE, A.p, NULL, z, got, N, &fl, NULL);
        put_env("CFT_HIP_UPLOAD", NULL);
        planted = st != CFT_OK && strstr(cft_last_error(), "CFT_HIP_UPLOAD") != NULL;
        for (untouched = 1, i = 0; i < NB; i++)
            untouched &= got[i] == 0x5A;
        CHECK(planted && untouched, "CFT_HIP_UPLOAD=fail-fill: %s, \"%s\", output %s",
              cft_strerror(st), cft_last_error(), untouched ? "untouched" : "WRITTEN");
        printf("  a failed upload: %s - %s\n", cft_strerror(st), cft_last_error());
        CHECK(cft_run(hw, CFT_ADD, CFT_FP64, CFT_RNE, A.p, NULL, z, got, N, &fl, NULL) ==
              CFT_OK, "the retry: %s", cft_last_error());
        CHECK(cft_run(sw, CFT_ADD, CFT_FP64, CFT_RNE, y, NULL, z, want, N, &fs, NULL) ==
              CFT_OK && cft_run(sw, CFT_ADD, CFT_FP64, CFT_RNE, x, NULL, z, tmp, N, &fs,
                                NULL) == CFT_OK, "software");
        retry = same(got, want, NB);
        CHECK(retry, "the retry after a failed upload: %s", same(got, tmp, NB)
              ? "it answered for the OLD bytes - a failed upload left its pages fresh "
                "(KL-464's order)" : "bytes differ from the software handle's");
        printf("  its retry: %s\n", retry ? "the software handle's bytes for the new "
               "operand" : same(got, tmp, NB) ? "the OLD operand's bytes" : "WRONG");
        put_env("CFT_HIP_UPLOAD", "fill");
        st = cft_run(hw, CFT_ADD, CFT_FP64, CFT_RNE, A.p, NULL, z, got, N, &fl, NULL);
        put_env("CFT_HIP_UPLOAD", NULL);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && strstr(cft_last_error(), "CFT_HIP_UPLOAD"),
              "CFT_HIP_UPLOAD=fill: %s, \"%s\" - a malformed value must be refused by name",
              cft_strerror(st), cft_last_error());
        rb_free(&A);

        /* the failed run: its resident output LOST, refused until published */
        {
            cft_device *h = NULL;
            put_env("CFT_HIP_PLANT", "fail-launch");
            st = cft_open(artifact, 0, &h);
            put_env("CFT_HIP_PLANT", NULL);
            CHECK(st == CFT_OK, "open with fail-launch: %s", cft_last_error());
            if (h && rb_alloc(h, &A, NB) && rb_alloc(h, &D, NB)) {
                CHECK(rb_put(&A, x, NB), "publishing");
                st = cft_run(h, CFT_ABS, CFT_FP64, CFT_RNE, A.p, NULL, NULL, D.p, N, &fl,
                             NULL);
                CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "fail-launch"),
                      "the failed run: %s, \"%s\"", cft_strerror(st), cft_last_error());
                i1 = rb_info(&D);
                i2 = rb_info(&A);
                CHECK(!strncmp(i1.staged_why, "LOST:", 5) && i1.device_authority == 0 &&
                      strncmp(i2.staged_why, "LOST:", 5),
                      "after the failed run: d's why \"%s\" authority %d, a's \"%s\"",
                      i1.staged_why, i1.device_authority, i2.staged_why);
                printf("  a failed run's output: %s\n", i1.staged_why);
                st = cft_buffer_from_device(D.b);
                CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "failed on the "
                      "device"), "reading a LOST buffer back: %s, \"%s\"", cft_strerror(st),
                      cft_last_error());
                printf("  reading it back: %s - %s\n", cft_strerror(st), cft_last_error());
                CHECK(cft_buffer_to_device(D.b) == CFT_OK &&
                      strncmp(rb_info(&D).staged_why, "LOST:", 5) &&
                      cft_buffer_from_device(D.b) == CFT_OK,
                      "publishing a LOST buffer clears the loss: %s", cft_last_error());
            }
            rb_free(&A);
            rb_free(&D);
            cft_close(h);
        }
    }
out:
    rb_free(&A);
    rb_free(&B);
    rb_free(&D);
    printf("  buffers: %d failed\n", failures - before);
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
                                           "1", "stale", "fail-fill"};
    static const char *const badchunk[] = {"abc", "7", "0", "12", "64 ", "-8",
                                           "1073741832", "0x40"};
    static const char *const badpage[] = {"0", "16", "100", "2097152", "256 ", "0x100",
                                          "-256", "4k"};
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
    for (i = 0; i < sizeof badpage / sizeof badpage[0]; i++)
        env_refused(artifact, "CFT_HIP_PAGE", badpage[i]);

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

/* round 2's G2A: its leg functions here */

/* ---- augmentedAddition: the API's three calls and the executor's pair ---- */

static const char *const AUGN[3] = {"cft_augmented_add", "cft_augmented_sub",
                                    "cft_augmented_mul"};

static cft_status aug_call(cft_device *d, int op, int fmt, const void *a, const void *b,
                           void *r, void *e, size_t n, uint32_t *fl)
{
    return op == 0   ? cft_augmented_add(d, (cft_format)fmt, a, b, r, e, n, fl)
           : op == 1 ? cft_augmented_sub(d, (cft_format)fmt, a, b, r, e, n, fl)
                     : cft_augmented_mul(d, (cft_format)fmt, a, b, r, e, n, fl);
}

/* An exact encoding: m 0 a zero trailing significand, 1 its lowest bit, 2
 * every bit, 3 its top bit alone (1.5 in the binade), 4 random, 5 a quiet
 * NaN's, 6 a signalling NaN's. */
static void aug_put(unsigned char *e, int fmt, int sign, unsigned long exp, int m)
{
    const int mw = (int)cft_format_size((cft_format)fmt) * 8 - 1 - EXPW[fmt];
    int b;
    elem(e, fmt, sign, exp, m == 4 ? 1 : m == 5 ? 2 : m == 6 ? 3 : 0);
    if (m == 1)
        e[0] |= 1u;
    else if (m == 3)
        e[(mw - 1) / 8] |= (unsigned char)(1u << ((mw - 1) % 8));
    else if (m == 2)
        for (b = 0; b < mw; b++)
            e[b / 8] |= (unsigned char)(1u << (b % 8));
}

enum { AUG_P = 32, AUG_N = AUG_P * AUG_P };

/* The leg's operands at one format: every class 9.5 has a rule for, and
 * the pairs its words name - (1 + u) + u/2 and (1 + u) * 3 are ties where
 * roundTiesTowardZero and roundTiesToEven part, the largest finite plus
 * half its ulp is the overflow threshold (no flag) and plus its ulp one
 * past it, the smallest subnormal squared is a residual the format cannot
 * hold - each with its negation where the sign matters. */
static void aug_pool(unsigned char *p, int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const unsigned long mw = (unsigned long)esz * 8 - 1 - (unsigned long)EXPW[fmt];
    const unsigned long bias = (1ul << (EXPW[fmt] - 1)) - 1, top = (1ul << EXPW[fmt]) - 1;
    const struct { int s; unsigned long x; int m; } v[AUG_P] = {
        {0, 0, 0}, {1, 0, 0},                           /* zeros */
        {0, bias, 0}, {1, bias, 0},                     /* 1, -1 */
        {0, bias, 1}, {1, bias, 1},                     /* 1 + u, -(1 + u) */
        {0, bias - mw - 1, 0}, {1, bias - mw - 1, 0},   /* u/2, -u/2 */
        {0, bias + 1, 3}, {1, bias + 1, 3},             /* 3, -3 */
        {0, top - 1, 2}, {1, top - 1, 2},               /* the largest finite */
        {0, top - 2 - mw, 0}, {1, top - 2 - mw, 0},     /* half its ulp */
        {0, top - 1 - mw, 0}, {1, top - 1 - mw, 0},     /* its ulp */
        {0, 0, 1}, {1, 0, 1},                           /* the smallest subnormal */
        {0, 0, 2}, {0, 1, 0},                           /* the largest subnormal, the
                                                         * smallest normal */
        {0, top, 0}, {1, top, 0},                       /* infinities */
        {0, top, 5}, {1, top, 6},                       /* a quiet NaN, a signalling one */
        {0, bias - 3, 4}, {1, bias + 5, 4}, {0, 0, 4},  /* random: finite, finite,
                                                         * subnormal */
        {0, bias + 1, 0}, {0, bias - 1, 0},             /* 2, 0.5 */
        {1, bias - mw + 2, 4}, {0, bias - 40, 4}, {1, bias + 40, 4}};
    int i;
    for (i = 0; i < AUG_P; i++)
        aug_put(p + (size_t)i * esz, fmt, v[i].s, v[i].x, v[i].m);
}

static unsigned char aug_rh[AUG_N * 32], aug_eh[AUG_N * 32], aug_rs[AUG_N * 32],
    aug_es[AUG_N * 32], aug_t[AUG_N * 32];

/* The GPU's call held to the software handle's, which wrote aug_rs and
 * aug_es: both statuses CFT_OK, then r, e and the flag word; a FAIL line
 * names the first element that differs. */
static void aug_held(int op, int fmt, size_t n, const char *what, cft_status sh,
                     cft_status ss, const unsigned char *rh, const unsigned char *eh,
                     uint32_t fh, uint32_t fs)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    char x1[70], x2[70], x3[70], x4[70];
    size_t i = 0;
    if (sh != CFT_OK || ss != CFT_OK) {
        CHECK(0, "%s %s n=%lu %s: GPU %s (%s), software %s", AUGN[op],
              cft_format_name((cft_format)fmt), (unsigned long)n, what, cft_strerror(sh),
              cft_last_error(), cft_strerror(ss));
        return;
    }
    while (i < n && same(rh + i * esz, aug_rs + i * esz, esz) &&
           same(eh + i * esz, aug_es + i * esz, esz))
        i++;
    if (i == n && fh == fs) {
        checks++;
        return;
    }
    if (i == n)
        i = 0;                          /* the flags alone differ */
    hex(x1, rh + i * esz, esz);
    hex(x2, eh + i * esz, esz);
    hex(x3, aug_rs + i * esz, esz);
    hex(x4, aug_es + i * esz, esz);
    CHECK(0, "%s %s n=%lu %s: element %lu: GPU r %s e %s flags 0x%02x, software r %s "
          "e %s flags 0x%02x", AUGN[op], cft_format_name((cft_format)fmt), (unsigned long)n,
          what, (unsigned long)i, x1, x2, (unsigned)fh, x3, x4, (unsigned)fs);
}

/* One call on each handle. The GPU's outputs and flag word start as one
 * pattern and the software's as another, so nothing unwritten can pass. */
static void aug_case(cft_device *hw, cft_device *sw, int op, int fmt,
                     const unsigned char *a, const unsigned char *b, size_t n,
                     const char *what)
{
    const size_t bytes = n * cft_format_size((cft_format)fmt);
    uint32_t fh = 0xA5A5u, fs = 0x5A5Au;
    cft_status sh, ss;
    memset(aug_rh, 0x3C, bytes);
    memset(aug_eh, 0xC3, bytes);
    memset(aug_rs, 0x69, bytes);
    memset(aug_es, 0x96, bytes);
    ss = aug_call(sw, op, fmt, a, b, aug_rs, aug_es, n, &fs);
    sh = aug_call(hw, op, fmt, a, b, aug_rh, aug_eh, n, &fh);
    aug_held(op, fmt, n, what, sh, ss, aug_rh, aug_eh, fh, fs);
}

static const char *const AUGW[4] = {"r over a", "r over b", "e over a", "e over b"};

/* r or e over a or b (`which` indexes AUGW) on the GPU, held to the
 * software handle's UNALIASED pair: both outputs and the flags. */
static void aug_alias(cft_device *hw, cft_device *sw, int op, int fmt,
                      const unsigned char *a, const unsigned char *b, size_t n, int which)
{
    const size_t bytes = n * cft_format_size((cft_format)fmt);
    uint32_t fh = 0xA5A5u, fs = 0x5A5Au;
    unsigned char *r = which < 2 ? aug_t : aug_rh, *e = which < 2 ? aug_eh : aug_t;
    cft_status sh, ss;
    memcpy(aug_t, (which & 1) ? b : a, bytes);
    memset(aug_rh, 0x3C, bytes);
    memset(aug_eh, 0xC3, bytes);
    ss = aug_call(sw, op, fmt, a, b, aug_rs, aug_es, n, &fs);
    sh = aug_call(hw, op, fmt, (which & 1) ? a : aug_t, (which & 1) ? aug_t : b, r, e, n,
                  &fh);
    aug_held(op, fmt, n, AUGW[which], sh, ss, r, e, fh, fs);
}

/* A call both handles must refuse with CFT_ERR_INVALID_ARGUMENT (`any`
 * 0), or refuse alike (`any` 1: a format, whose status is the build's). */
static void aug_refused(cft_device *hw, cft_device *sw, int op, int fmt, const void *a,
                        const void *b, void *r, void *e, size_t n, int any, const char *what)
{
    uint32_t fh = 0, fs = 0;
    const cft_status sh = aug_call(hw, op, fmt, a, b, r, e, n, &fh);
    const cft_status ss = aug_call(sw, op, fmt, a, b, r, e, n, &fs);
    CHECK(sh == ss && (any ? sh != CFT_OK : sh == CFT_ERR_INVALID_ARGUMENT),
          "%s at format %d, %s: GPU %s, software %s", AUGN[op], fmt, what,
          cft_strerror(sh), cft_strerror(ss));
}

/* a, b, r and e in cft_alloc buffers: each call held to the software
 * handle; its outputs left on the device (the authority marks say so)
 * until read back; the second call binding all four without a page
 * moving; then r or e over a or b in the buffers, still resident. */
static void aug_resident(cft_device *hw, cft_device *sw, int fmt,
                         const unsigned char *xa, const unsigned char *xb, size_t n)
{
    const size_t bytes = n * cft_format_size((cft_format)fmt);
    struct rb A, B, R, E;
    struct rb *all[4];
    cft_buffer_info i0[4], i1[4];
    uint32_t fh = 0, fs = 0;
    cft_status sh, ss;
    int op, k, w, still = 1;
    A.b = B.b = R.b = E.b = NULL;
    all[0] = &A;
    all[1] = &B;
    all[2] = &R;
    all[3] = &E;
    CHECK(rb_alloc(hw, &A, bytes) && rb_alloc(hw, &B, bytes) && rb_alloc(hw, &R, bytes) &&
          rb_alloc(hw, &E, bytes), "cft_alloc: %s", cft_last_error());
    if (!A.b || !B.b || !R.b || !E.b)
        goto out;
    for (op = 0; op < 3; op++) {
        CHECK(rb_put(&A, xa, bytes) && rb_put(&B, xb, bytes), "publishing a and b: %s",
              cft_last_error());
        ss = aug_call(sw, op, fmt, xa, xb, aug_rs, aug_es, n, &fs);
        sh = aug_call(hw, op, fmt, A.p, B.p, R.p, E.p, n, &fh);
        i0[2] = rb_info(&R);
        i0[3] = rb_info(&E);
        CHECK(i0[2].device_authority == 1 && i0[3].device_authority == 1,
              "%s %s resident: r and e are not left on the device (authority %d, %d)",
              AUGN[op], cft_format_name((cft_format)fmt), i0[2].device_authority,
              i0[3].device_authority);
        CHECK(cft_buffer_from_device(R.b) == CFT_OK && cft_buffer_from_device(E.b) == CFT_OK &&
              rb_info(&R).device_authority == 0 && rb_info(&E).device_authority == 0,
              "%s %s resident: the read-back: %s", AUGN[op],
              cft_format_name((cft_format)fmt), cft_last_error());
        aug_held(op, fmt, n, "resident", sh, ss, R.p, E.p, fh, fs);
        /* the second call: nothing published, nothing written on the host */
        for (k = 0; k < 4; k++)
            i0[k] = rb_info(all[k]);
        sh = aug_call(hw, op, fmt, A.p, B.p, R.p, E.p, n, &fh);
        for (k = 0; k < 4; k++)
            i1[k] = rb_info(all[k]);
        for (k = 0; k < 4; k++)
            still &= i1[k].resident_binds == i0[k].resident_binds + 1 &&
                     i1[k].staged_binds == i0[k].staged_binds;
        CHECK(still, "%s %s: the second resident call moved pages (a %llu/%llu, r %llu/%llu "
              "binds resident/staged after it; \"%s\")", AUGN[op],
              cft_format_name((cft_format)fmt), (unsigned long long)i1[0].resident_binds,
              (unsigned long long)i1[0].staged_binds, (unsigned long long)i1[2].resident_binds,
              (unsigned long long)i1[2].staged_binds, i1[2].staged_why);
        CHECK(cft_buffer_from_device(R.b) == CFT_OK && cft_buffer_from_device(E.b) == CFT_OK,
              "the second read-back: %s", cft_last_error());
        aug_held(op, fmt, n, "resident, the second call", sh, ss, R.p, E.p, fh, fs);
    }
    for (w = 0; w < 4; w++) {
        struct rb *in = (w & 1) ? &B : &A;
        op = w % 3;
        CHECK(rb_put(&A, xa, bytes) && rb_put(&B, xb, bytes), "publishing a and b: %s",
              cft_last_error());
        ss = aug_call(sw, op, fmt, xa, xb, aug_rs, aug_es, n, &fs);
        i0[0] = rb_info(in);
        sh = aug_call(hw, op, fmt, A.p, B.p, w < 2 ? in->p : R.p, w < 2 ? E.p : in->p, n,
                      &fh);
        i1[0] = rb_info(in);
        for (k = 0; k < 4; k++)
            CHECK(cft_buffer_from_device(all[k]->b) == CFT_OK, "a read-back: %s",
                  cft_last_error());
        aug_held(op, fmt, n, w == 0 ? "resident, r over a" : w == 1 ? "resident, r over b"
                 : w == 2 ? "resident, e over a" : "resident, e over b", sh, ss,
                 w < 2 ? in->p : R.p, w < 2 ? E.p : in->p, fh, fs);
        CHECK(i1[0].resident_binds > i0[0].resident_binds && !strstr(i1[0].staged_why,
              "overlaps"), "%s %s resident, %s: the shared window was staged (\"%s\")",
              AUGN[op], cft_format_name((cft_format)fmt), AUGW[w], i1[0].staged_why);
    }
    printf("  %s: resident, each call held, r and e left on the device until read "
           "back, the second call bound all four with no page moved (%s), and r or e "
           "over a or b stayed resident\n", cft_format_name((cft_format)fmt),
           still ? "held" : "NOT held");
out:
    rb_free(&A);
    rb_free(&B);
    rb_free(&R);
    rb_free(&E);
}

/* AUGERR r3, r0, r1; AUGADD r0, r0, r1 (rd = ra); QUIET; AUGADD r4, r2,
 * r2; AUGERR r1, r1, r2 (rd = ra, in the region); ENDQUIET; DEPOSIT r0,
 * r3, r4 and r1; HALT - revision 8's pair at format fmt (device_test.c's
 * try_load_rev8 encodes the first two the same way). */
static size_t aug_image(unsigned char *img, int fmt)
{
    const uint32_t hdr[8] = {0x50544643u, 1, 11, 0, 4, (uint32_t)fmt, 0, 0};
    const uint64_t C = 1ull << 31;
    const uint64_t w[11] = {C | 11u | (3u << 8) | (0u << 12) | (1u << 16),
                            C | 10u | (0u << 8) | (0u << 12) | (1u << 16),
                            C | 12u,
                            C | 10u | (4u << 8) | (2u << 12) | (2u << 16),
                            C | 11u | (1u << 8) | (1u << 12) | (2u << 16),
                            C | 13u,
                            C | 3u | (0u << 12), C | 3u | (3u << 12),
                            C | 3u | (4u << 12), C | 3u | (1u << 12),
                            C};
    int j, k;
    for (j = 0; j < 8; j++)
        for (k = 0; k < 4; k++)
            img[4 * j + k] = (unsigned char)(hdr[j] >> (8 * k));
    for (j = 0; j < 11; j++)
        for (k = 0; k < 8; k++)
            img[32 + 8 * j + k] = (unsigned char)(w[j] >> (8 * k));
    return 32 + 11 * 8;
}

/* The executor's AUGADD and AUGERR through cft_program_run_ex on both
 * handles: every deposit, the run's flags and every lane's flag byte. */
static void aug_program(cft_device *hw, cft_device *sw, int fmt, const unsigned char *xa,
                        const unsigned char *xb, const unsigned char *xc, size_t n)
{
    static unsigned char dh[4 * AUG_N * 32], ds[4 * AUG_N * 32], lh[AUG_N], ls[AUG_N];
    unsigned char img[32 + 11 * 8];
    const size_t dbytes = 4 * n * cft_format_size((cft_format)fmt);
    const size_t bytes = aug_image(img, fmt);
    cft_program *ph = NULL, *ps = NULL;
    uint32_t fh = 0xA5A5u, fs = 0x5A5Au;
    cft_run_args R;
    cft_status sh, ss;
    CHECK(cft_program_load(hw, img, bytes, &ph) == CFT_OK &&
          cft_program_load(sw, img, bytes, &ps) == CFT_OK,
          "loading the AUGADD/AUGERR program at %s: %s", cft_format_name((cft_format)fmt),
          cft_last_error());
    if (ph && ps) {
        memset(dh, 0x3C, dbytes);
        memset(ds, 0x69, dbytes);
        memset(lh, 0xEE, n);
        memset(ls, 0x11, n);
        memset(&R, 0, sizeof R);
        R.struct_size = sizeof R;
        R.a = xa;
        R.b = xb;
        R.c = xc;
        R.n = n;
        R.deposits = dh;
        R.flags_out = &fh;
        R.lane_flags = lh;
        R.lane_flags_bytes = n;
        sh = cft_program_run_ex(ph, &R);
        R.deposits = ds;
        R.flags_out = &fs;
        R.lane_flags = ls;
        ss = cft_program_run_ex(ps, &R);
        CHECK(sh == CFT_OK && ss == CFT_OK && same(dh, ds, dbytes) && fh == fs &&
              same(lh, ls, n), "the AUGADD/AUGERR program at %s, %lu lanes: GPU %s, "
              "software %s; deposits %s, flags 0x%x and 0x%x, lane flags %s",
              cft_format_name((cft_format)fmt), (unsigned long)n, cft_strerror(sh),
              cft_strerror(ss), same(dh, ds, dbytes) ? "equal" : "DIFFER", (unsigned)fh,
              (unsigned)fs, same(lh, ls, n) ? "equal" : "DIFFER");
    }
    cft_program_free(ph);
    cft_program_free(ps);
}

/* A failed call's resident outputs (a HIP_PLANTS=1 build's fail-launch):
 * LOST, refused on reading back, its inputs untouched. */
static void aug_lost(const char *artifact, int fmt, const unsigned char *xa,
                     const unsigned char *xb, size_t n)
{
    const size_t bytes = n * cft_format_size((cft_format)fmt);
    cft_device *h = NULL;
    struct rb A, B, R, E;
    cft_buffer_info ir, ie, ia;
    uint32_t fl = 0;
    cft_status st;
    A.b = B.b = R.b = E.b = NULL;
    put_env("CFT_HIP_PLANT", "fail-launch");
    st = cft_open(artifact, 0, &h);
    put_env("CFT_HIP_PLANT", NULL);
    CHECK(st == CFT_OK, "open with fail-launch: %s", cft_last_error());
    if (h && rb_alloc(h, &A, bytes) && rb_alloc(h, &B, bytes) && rb_alloc(h, &R, bytes) &&
        rb_alloc(h, &E, bytes)) {
        CHECK(rb_put(&A, xa, bytes) && rb_put(&B, xb, bytes), "publishing");
        st = cft_augmented_add(h, (cft_format)fmt, A.p, B.p, R.p, E.p, n, &fl);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "fail-launch"),
              "the failed augmented call: %s, \"%s\"", cft_strerror(st), cft_last_error());
        printf("  a failed augmented call: %s - %s\n", cft_strerror(st), cft_last_error());
        ir = rb_info(&R);
        ie = rb_info(&E);
        ia = rb_info(&A);
        CHECK(!strncmp(ir.staged_why, "LOST:", 5) && !strncmp(ie.staged_why, "LOST:", 5) &&
              ir.device_authority == 0 && strncmp(ia.staged_why, "LOST:", 5),
              "after the failed call: r's why \"%s\", e's \"%s\", a's \"%s\"",
              ir.staged_why, ie.staged_why, ia.staged_why);
        printf("  its outputs: r %s; e %s\n", ir.staged_why, ie.staged_why);
        st = cft_buffer_from_device(E.b);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "failed on the device"),
              "reading a LOST e back: %s, \"%s\"", cft_strerror(st), cft_last_error());
    }
    rb_free(&A);
    rb_free(&B);
    rb_free(&R);
    rb_free(&E);
    cft_close(h);
}

static void leg_aug(const char *artifact, cft_device *hw, cft_device *sw, int only_fmt)
{
    static unsigned char pool[AUG_P * 32], xa[AUG_N * 32], xb[AUG_N * 32], xc[AUG_N * 32];
    const int before = failures;
    const int checks0 = checks;
    cft_device *h = NULL;
    clock_t t0 = clock();
    int f, op, w, plant_build;

    printf("aug\n");
    for (f = 0; f < 4; f++) {
        const size_t esz = cft_format_size((cft_format)f);
        const int checks1 = checks;
        uint32_t fl;
        size_t i;
        if (only_fmt >= 0 && f != only_fmt)
            continue;
        aug_pool(pool, f);
        for (i = 0; i < (size_t)AUG_N; i++) {
            memcpy(xa + i * esz, pool + (i / AUG_P) * esz, esz);
            memcpy(xb + i * esz, pool + (i % AUG_P) * esz, esz);
            memcpy(xc + i * esz, pool + ((i * 7 + 3) % AUG_P) * esz, esz);
        }
        for (op = 0; op < 3; op++) {
            /* one call a pair: the flags of exactly one element */
            for (i = 0; i < (size_t)AUG_N; i++)
                aug_case(hw, sw, op, f, xa + i * esz, xb + i * esz, 1, "one pair");
            /* every pair in one call, and 300 from pair 37: the flags' OR */
            aug_case(hw, sw, op, f, xa, xb, AUG_N, "every pair in one call");
            aug_case(hw, sw, op, f, xa + 37 * esz, xb + 37 * esz, 300, "300 pairs");
            for (w = 0; w < 4; w++)
                aug_alias(hw, sw, op, f, xa, xb, AUG_N, w);
            /* refused before any device: r == e, a NULL, a format */
            aug_refused(hw, sw, op, f, xa, xb, aug_rh, aug_rh, 1, 0, "r == e");
            aug_refused(hw, sw, op, f, NULL, xb, aug_rh, aug_eh, 1, 0, "a NULL");
            aug_refused(hw, sw, op, f, xa, NULL, aug_rh, aug_eh, 1, 0, "b NULL");
            aug_refused(hw, sw, op, f, xa, xb, NULL, aug_eh, 1, 0, "r NULL");
            aug_refused(hw, sw, op, f, xa, xb, aug_rh, NULL, 1, 0, "e NULL");
            aug_refused(hw, sw, op, -1, xa, xb, aug_rh, aug_eh, 1, 1, "format -1");
            aug_refused(hw, sw, op, 4, xa, xb, aug_rh, aug_eh, 1, 1, "format 4");
            aug_refused(hw, sw, op, 99, xa, xb, aug_rh, aug_eh, 1, 1, "format 99");
            fl = 0xDEADu;
            CHECK(aug_call(hw, op, f, xa, xb, aug_rh, aug_eh, 0, &fl) == CFT_OK && fl == 0,
                  "%s %s n = 0: not CFT_OK with the flag word cleared (0x%x)", AUGN[op],
                  cft_format_name((cft_format)f), (unsigned)fl);
        }
        CHECK(cft_augmented_add(NULL, (cft_format)f, xa, xb, aug_rh, aug_eh, 1, NULL) ==
              CFT_ERR_INVALID_ARGUMENT, "a NULL device was not refused");
        printf("  %s: %d pairs x 3 calls, one call a pair, then all %d in one call and 300 "
               "in another; r and e over a or b; r == e, NULLs, bad formats and n = 0: %d "
               "checks\n", cft_format_name((cft_format)f), AUG_N, AUG_N, checks - checks1);
        aug_resident(hw, sw, f, xa, xb, AUG_N);
        aug_program(hw, sw, f, xa, xb, xc, AUG_N);
    }
    put_env("CFT_HIP_PLANT", "bogus");
    plant_build = cft_open(artifact, 0, &h) != CFT_OK;
    put_env("CFT_HIP_PLANT", NULL);
    cft_close(h);
    if (!plant_build) {
        nrun("  a failed augmented call's outputs LOST", "this libcft is a default build, "
             "which has no CFT_HIP_PLANT=fail-launch; build with HIP_PLANTS=1");
    } else {
        f = only_fmt >= 0 ? only_fmt : CFT_FP64;
        aug_pool(pool, f);
        aug_lost(artifact, f, pool, pool + 8 * cft_format_size((cft_format)f), 16);
    }
    printf("  aug: %d checks, the three calls and the program held to the software "
           "handle (r, e and the flags of every call), %s, %.1f s, %d failed\n",
           checks - checks0,
           only_fmt >= 0 ? cft_format_name((cft_format)only_fmt) : "every format",
           (double)(clock() - t0) / CLOCKS_PER_SEC, failures - before);
}

/* round 2's G2B: its leg functions here */

/* ---- index tables and scratch depths (round 2's G2B) ----------------------- */

/* The sequencer's words as device-test packs them (docs/SEQUENCER.md;
 * program.c parses this layout), registers r0 to r15 only: an ALU word
 * (kb, kc: rb, rc name constants), a control word (0 HALT, 1 REPEAT imm,
 * 2 ENDREP, 3 DEPOSIT ra), and the scratch codes (6 STL ra to a slot, 7
 * LDL rd from one, 8 STX ra to [rb], 9 LDX rd from [rb]). */
static uint64_t sq_alu(unsigned op, unsigned rd, unsigned ra, unsigned rb, unsigned rc,
                       unsigned kb, unsigned kc)
{
    return (uint64_t)op | ((uint64_t)rd << 8) | ((uint64_t)ra << 12) |
           ((uint64_t)rb << 16) | ((uint64_t)rc << 20) | ((uint64_t)kb << 28) |
           ((uint64_t)kc << 29);
}

static uint64_t sq_ctrl(unsigned code, unsigned ra, uint32_t imm)
{
    return (uint64_t)code | ((uint64_t)ra << 12) | ((uint64_t)1 << 31) |
           ((uint64_t)imm << 32);
}

static uint64_t sq_scr(unsigned code, unsigned rd, unsigned ra, unsigned rb, uint32_t slot)
{
    return (uint64_t)code | ((uint64_t)rd << 8) | ((uint64_t)ra << 12) |
           ((uint64_t)rb << 16) | ((uint64_t)1 << 31) |
           ((uint64_t)(slot & 0xFFFFFFu) << 32);
}

/* header, constants (none under BANK_EXT) and instructions: its bytes */
static size_t sq_image(unsigned char *out, int fmt, const uint64_t *ins, unsigned ni,
                       const unsigned char *k, unsigned nk, uint32_t md, uint32_t flags,
                       uint32_t nsi, uint32_t nso)
{
    const uint32_t hdr[8] = {0x50544643u, 1, ni, nk, md, (uint32_t)fmt, flags,
                             (nsi & 0xFFFFu) | ((nso & 0xFFFFu) << 16)};
    const size_t esz = cft_format_size((cft_format)fmt);
    size_t off = 32;
    unsigned i;
    int b;
    for (i = 0; i < 8; i++)
        for (b = 0; b < 4; b++)
            out[4 * i + (unsigned)b] = (unsigned char)(hdr[i] >> (8 * b));
    if (!(flags & CFT_PROG_FLAG_BANK_EXT) && nk) {
        memcpy(out + off, k, nk * esz);
        off += nk * esz;
    }
    for (i = 0; i < ni; i++, off += 8)
        for (b = 0; b < 8; b++)
            out[off + (size_t)b] = (unsigned char)(ins[i] >> (8 * b));
    return off;
}

/* an unsigned integer as a raw bit pattern (STX and LDX read their slot
 * from one), and the float 1 + 2^-k (k 0: 1) */
static void put_int(unsigned char *e, int fmt, uint32_t v)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    size_t j;
    memset(e, 0, esz);
    for (j = 0; j < 4 && j < esz; j++)
        e[j] = (unsigned char)(v >> (8 * j));
}

static void one_plus(unsigned char *e, int fmt, int k)
{
    const int width = (int)cft_format_size((cft_format)fmt) * 8;
    const int mw = width - 1 - EXPW[fmt];
    elem(e, fmt, 0, (1ul << (EXPW[fmt] - 1)) - 1, 0);
    if (k > 0 && k <= mw)
        e[(mw - k) / 8] |= (unsigned char)(1u << ((mw - k) % 8));
}

/* n entries into a source of srcn elements: one in five CFT_IDX_NONE (the
 * lanes `r` shifts), lane 0 the source's LAST element, the rest spread
 * over the whole of it - so a source cut short, a table read at another
 * chunk's window, or a sentinel read as 0 each changes an answer */
static void ix_table(uint32_t *t, size_t n, size_t srcn, unsigned r)
{
    size_t i;
    for (i = 0; i < n; i++)
        t[i] = (i + r) % 5 == 4 ? CFT_IDX_NONE
             : i == 0 ? (uint32_t)(srcn - 1)
             : (uint32_t)(((uint64_t)i * (2654435761u + 2u * r) + r) % srcn);
}

static uint32_t pp_bus;         /* the GPU's STATUS from the last prog_pair */

/* One image run on the GPU and on the software handle with the same
 * arguments, each with its own outputs filled alike first (H's, as the
 * caller filled them): deposits, counts, lane bytes, scratch-out, flags and
 * STATUS compared byte for byte, and the two statuses. Returns the GPU's. */
static cft_status prog_pair(cft_device *hw, cft_device *sw, int fmt, const unsigned char *img,
                            size_t bytes, cft_run_args *H, uint32_t md, uint32_t nso,
                            const char *what)
{
    const size_t esz = cft_format_size((cft_format)fmt), n = H->n;
    const size_t db = n * md * esz, sb = n * nso * esz;
    cft_program *ph = NULL, *ps = NULL;
    cft_run_args S = *H;
    uint32_t fh = 0, fs = 0, bh = 0, bs = 0;
    unsigned char *dep = (unsigned char *)malloc(db + 1), *so = (unsigned char *)malloc(sb + 1);
    unsigned char *lf = (unsigned char *)malloc(n + 1);
    uint32_t *cnt = (uint32_t *)malloc(n * 4 + 4);
    cft_status sth = CFT_ERR_OUT_OF_MEMORY, sts = CFT_ERR_OUT_OF_MEMORY;
    char msg[600] = "";
    if (dep && so && lf && cnt) {
        if (H->deposits) memcpy(dep, H->deposits, db);
        if (H->scratch_out) memcpy(so, H->scratch_out, sb);
        if (H->lane_flags) memcpy(lf, H->lane_flags, n);
        if (H->counts) memcpy(cnt, H->counts, n * 4);
        S.deposits = H->deposits ? dep : NULL;
        S.scratch_out = H->scratch_out ? so : NULL;
        S.lane_flags = H->lane_flags ? lf : NULL;
        S.counts = H->counts ? cnt : NULL;
        H->flags_out = &fh;
        H->bus_out = &bh;
        S.flags_out = &fs;
        S.bus_out = &bs;
        sth = cft_program_load(hw, img, bytes, &ph);
        if (sth == CFT_OK)
            sth = cft_program_run_ex(ph, H);
        snprintf(msg, sizeof msg, "%s", cft_last_error());
        sts = cft_program_load(sw, img, bytes, &ps);
        if (sts == CFT_OK)
            sts = cft_program_run_ex(ps, &S);
    }
    CHECK(sth == CFT_OK && sts == CFT_OK, "%s: the GPU says %s (%s), the software handle "
          "%s (%s)", what, cft_strerror(sth), msg, cft_strerror(sts), cft_last_error());
    if (sth == CFT_OK && sts == CFT_OK) {
        const int d1 = !H->deposits || same((const unsigned char *)H->deposits, dep, db);
        const int d2 = !H->counts || same((const unsigned char *)H->counts,
                                          (const unsigned char *)cnt, n * 4);
        const int d3 = !H->scratch_out || same((const unsigned char *)H->scratch_out, so, sb);
        const int d4 = !H->lane_flags || same(H->lane_flags, lf, n);
        CHECK(d1 && d2 && d3 && d4 && fh == fs && bh == bs,
              "%s: the GPU's run differs from the software handle's - deposits %s, counts "
              "%s, scratch-out %s, lane bytes %s, flags 0x%x and 0x%x, STATUS 0x%x and 0x%x",
              what, d1 ? "equal" : "DIFFER", d2 ? "equal" : "DIFFER", d3 ? "equal" : "DIFFER",
              d4 ? "equal" : "DIFFER", (unsigned)fh, (unsigned)fs, (unsigned)bh,
              (unsigned)bs);
    }
    pp_bus = bh;
    H->flags_out = NULL;
    H->bus_out = NULL;
    cft_program_free(ph);
    cft_program_free(ps);
    free(dep);
    free(so);
    free(lf);
    free(cnt);
    return sth;
}

/* cft_run_ex's tables: the GPU's run (device.c composes it as a three-
 * instruction program over the indexed streams) against the software
 * handle's (a host gather and the dense run - the definition). One opcode
 * of each elementwise group, with the operands it reads. */
static const struct {
    cft_op op;
    unsigned reads;               /* bit 0 a, bit 1 b, bit 2 c */
} IX_OPS[] = {{CFT_FMA, 7}, {CFT_ADD, 5}, {CFT_ABS, 1}, {CFT_MIN, 3}, {CFT_CMPLT, 3},
              {CFT_IADD, 3}, {CFT_RECIP_SEED, 1}};    /* ADD is a + c (cft.h) */
enum { IX_NMAX = 5000, IX_SMAX = 3 * IX_NMAX + 5 };
static unsigned char ix_src[3][IX_SMAX * 32], ix_den[3][IX_NMAX * 32], ix_dh[IX_NMAX * 32],
    ix_ds[IX_NMAX * 32];
static uint32_t ix_tab[3][IX_NMAX];

static void ix_elem(cft_device *hw, cft_device *sw, int f, int small)
{
    static const size_t NS[5] = {1, 8, 9, 300, IX_NMAX};
    const size_t esz = cft_format_size((cft_format)f);
    size_t o, si, sl;
    unsigned T, r;
    int runs = 0, before = failures;
    char msg[600];
    for (o = 0; o < sizeof IX_OPS / sizeof IX_OPS[0]; o++)
        for (T = 1; T < 8; T++) {
            if ((T & IX_OPS[o].reads) != T)
                continue;
            for (si = 0; si < (small ? 4u : 5u); si++)
                for (sl = 0; sl < 2; sl++) {
                    const size_t n = NS[si], srcn = sl ? n / 3 + 1 : 3 * n + 5;
                    const cft_round rnd = (cft_round)(runs % 5);
                    const int kind = runs % K_COUNT;
                    const void *opnd[3] = {NULL, NULL, NULL};
                    uint32_t fh = 0, fs = 0;
                    cft_status sh, ss;
                    cft_elem_args E;
                    memset(&E, 0, sizeof E);
                    E.struct_size = sizeof E;
                    for (r = 0; r < 3; r++) {
                        if (!((IX_OPS[o].reads >> r) & 1u))
                            continue;
                        if ((T >> r) & 1u) {
                            fill(ix_src[r], srcn, f, kind);
                            ix_table(ix_tab[r], n, srcn, r);
                            opnd[r] = ix_src[r];
                        } else {
                            fill(ix_den[r], n, f, kind);
                            opnd[r] = ix_den[r];
                        }
                    }
                    E.a = opnd[0];
                    E.b = opnd[1];
                    E.c = opnd[2];
                    E.n = n;
                    E.idx_a = (T & 1u) ? ix_tab[0] : NULL;
                    E.idx_b = (T & 2u) ? ix_tab[1] : NULL;
                    E.idx_c = (T & 4u) ? ix_tab[2] : NULL;
                    E.idx_a_src = (T & 1u) ? srcn : 0;
                    E.idx_b_src = (T & 2u) ? srcn : 0;
                    E.idx_c_src = (T & 4u) ? srcn : 0;
                    memset(ix_dh, 0x5A, n * esz);
                    memset(ix_ds, 0x5A, n * esz);
                    E.d = ix_dh;
                    E.flags_out = &fh;
                    sh = cft_run_ex(hw, IX_OPS[o].op, (cft_format)f, rnd, &E);
                    snprintf(msg, sizeof msg, "%s", cft_last_error());
                    E.d = ix_ds;
                    E.flags_out = &fs;
                    ss = cft_run_ex(sw, IX_OPS[o].op, (cft_format)f, rnd, &E);
                    runs++;
                    CHECK(sh == CFT_OK && ss == CFT_OK && same(ix_dh, ix_ds, n * esz) &&
                              fh == fs,
                          "cft_run_ex %s %s %s, tables 0x%x, n %lu, source %lu (%s): the "
                          "GPU %s (%s), flags 0x%x; the software handle %s, flags 0x%x; "
                          "results %s", cft_op_name(IX_OPS[o].op), cft_format_name(
                          (cft_format)f), RND[rnd], T, (unsigned long)n, (unsigned long)srcn,
                          KIND[kind], cft_strerror(sh), msg, (unsigned)fh, cft_strerror(ss),
                          (unsigned)fs, same(ix_dh, ix_ds, n * esz) ? "equal" : "DIFFER");
                }
        }
    /* a scalar beside a table: FMA, its lowest operand without a table one
     * element (device.c makes it one of the image's constants) */
    for (T = 1; T < 7; T++) {
        const unsigned s = !(T & 1u) ? 0u : !(T & 2u) ? 1u : 2u;
        static const size_t SN[2] = {9, 300};
        for (si = 0; si < 2; si++) {
            const size_t n = SN[si], srcn = 3 * n + 5;
            uint32_t fh = 0, fs = 0;
            cft_status sh, ss;
            cft_elem_args E;
            memset(&E, 0, sizeof E);
            E.struct_size = sizeof E;
            for (r = 0; r < 3; r++) {
                if ((T >> r) & 1u) {
                    fill(ix_src[r], srcn, f, K_RANDOM);
                    ix_table(ix_tab[r], n, srcn, r);
                } else {
                    fill(ix_den[r], r == s ? 1 : n, f, K_RANDOM);
                }
            }
            E.a = (T & 1u) ? (const void *)ix_src[0] : ix_den[0];
            E.b = (T & 2u) ? (const void *)ix_src[1] : ix_den[1];
            E.c = (T & 4u) ? (const void *)ix_src[2] : ix_den[2];
            E.n = n;
            E.scalar_mask = 1u << s;
            E.idx_a = (T & 1u) ? ix_tab[0] : NULL;
            E.idx_b = (T & 2u) ? ix_tab[1] : NULL;
            E.idx_c = (T & 4u) ? ix_tab[2] : NULL;
            E.idx_a_src = (T & 1u) ? srcn : 0;
            E.idx_b_src = (T & 2u) ? srcn : 0;
            E.idx_c_src = (T & 4u) ? srcn : 0;
            memset(ix_dh, 0x5A, n * esz);
            memset(ix_ds, 0x5A, n * esz);
            E.d = ix_dh;
            E.flags_out = &fh;
            sh = cft_run_ex(hw, CFT_FMA, (cft_format)f, CFT_RNE, &E);
            snprintf(msg, sizeof msg, "%s", cft_last_error());
            E.d = ix_ds;
            E.flags_out = &fs;
            ss = cft_run_ex(sw, CFT_FMA, (cft_format)f, CFT_RNE, &E);
            runs++;
            CHECK(sh == CFT_OK && ss == CFT_OK && same(ix_dh, ix_ds, n * esz) && fh == fs,
                  "cft_run_ex fma %s, tables 0x%x, operand %c scalar, n %lu: the GPU %s "
                  "(%s), the software handle %s, results %s", cft_format_name((cft_format)f),
                  T, 'a' + s, (unsigned long)n, cft_strerror(sh), msg, cft_strerror(ss),
                  same(ix_dh, ix_ds, n * esz) ? "equal" : "DIFFER");
        }
    }
    /* d over an indexed source: refused alike, by name */
    {
        const size_t n = 300, srcn = 3 * n + 5;
        cft_status sh, ss;
        cft_elem_args E;
        fill(ix_src[0], srcn, f, K_RANDOM);
        fill(ix_den[2], n, f, K_RANDOM);
        ix_table(ix_tab[0], n, srcn, 0);
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = ix_src[0];
        E.c = ix_den[2];
        E.n = n;
        E.idx_a = ix_tab[0];
        E.idx_a_src = srcn;
        E.d = ix_src[0] + 7 * esz;
        sh = cft_run_ex(hw, CFT_ADD, (cft_format)f, CFT_RNE, &E);
        snprintf(msg, sizeof msg, "%s", cft_last_error());
        ss = cft_run_ex(sw, CFT_ADD, (cft_format)f, CFT_RNE, &E);
        CHECK(sh == CFT_ERR_INVALID_ARGUMENT && ss == sh &&
              strstr(msg, "d overlaps operand a") && strstr(cft_last_error(), "d overlaps"),
              "d over an indexed source, %s: the GPU %s (%s), the software handle %s (%s)",
              cft_format_name((cft_format)f), cft_strerror(sh), msg, cft_strerror(ss),
              cft_last_error());
        if (f == CFT_FP64 || f == CFT_FP32)
            printf("    d over an indexed source (%s): %s - %s\n",
                   cft_format_name((cft_format)f), cft_strerror(sh), msg);
    }
    printf("    cft_run_ex %s: %d runs with tables against the software handle, %d "
           "failed\n", cft_format_name((cft_format)f), runs, failures - before);
}

/* cft_program_run_ex with the three tables and the scratch table at once:
 * r4..r6 gathered from the pool, an FMA of the gathered streams, two
 * deposits and a scratch-out block - plain, from a bank, and strict with an
 * LDX past the depth (and the lane bytes), each with and without a mask */
static void ix_prog(cft_device *hw, cft_device *sw, int f, int small)
{
    static const size_t NS[3] = {9, 300, IX_NMAX};
    const size_t esz = cft_format_size((cft_format)f), nsi = 3, nso = 2;
    unsigned char k[2 * 32], img[32 + 2 * 32 + 16 * 8];
    uint64_t ins[16];
    size_t si, i;
    int v, m, before = failures, runs = 0;
    one_plus(k, f, 1);                            /* k0: 1.5 */
    put_int(k + esz, f, 300);                     /* k1: an index past 256 */
    for (si = 0; si < (small ? 2u : 3u); si++) {
        const size_t n = NS[si];
        const size_t sa = 3 * n + 5, sb = n / 3 + 1, sc = 2 * n + 1, sp = n * nsi * 2 + 7;
        unsigned char *pa = (unsigned char *)malloc(sa * esz);
        unsigned char *pb = (unsigned char *)malloc(sb * esz);
        unsigned char *pc = (unsigned char *)malloc(sc * esz);
        unsigned char *pp = (unsigned char *)malloc(sp * esz);
        unsigned char *dep = (unsigned char *)malloc(n * 3 * esz);
        unsigned char *so = (unsigned char *)malloc(n * nso * esz);
        unsigned char *lf = (unsigned char *)malloc(n);
        unsigned char *msk = (unsigned char *)malloc((n + 7) / 8);
        uint32_t *ta = (uint32_t *)malloc(n * 4), *tb = (uint32_t *)malloc(n * 4);
        uint32_t *tc = (uint32_t *)malloc(n * 4), *tsi = (uint32_t *)malloc(n * nsi * 4);
        uint32_t *cnt = (uint32_t *)malloc(n * 4);
        cft_run_args A;
        cft_program *p = NULL;
        cft_status st;
        char what[160];
        int untouched;
        if (!pa || !pb || !pc || !pp || !dep || !so || !lf || !msk || !ta || !tb || !tc ||
            !tsi || !cnt) {
            CHECK(0, "indexed programs: out of host memory");
            goto next;
        }
        fill(pa, sa, f, K_RANDOM);
        fill(pb, sb, f, K_NAN);
        fill(pc, sc, f, K_RANDOM);
        fill(pp, sp, f, K_OVERFLOW);
        ix_table(ta, n, sa, 0);
        ix_table(tb, n, sb, 1);
        ix_table(tc, n, sc, 2);
        ix_table(tsi, n * nsi, sp, 3);
        for (i = 0; i < (n + 7) / 8; i++)
            msk[i] = (unsigned char)rnd64();
        for (v = 0; v < 3; v++)
            for (m = 0; m < 2; m++) {
                const uint32_t md = v == 2 ? 3 : 2;
                const uint32_t flags = CFT_PROG_FLAG_SCRATCH_IO |
                                       (v == 1 ? CFT_PROG_FLAG_BANK_EXT : 0u) |
                                       (v == 2 ? CFT_PROG_FLAG_SCRATCH_STRICT : 0u);
                unsigned ni = 0;
                size_t bytes;
                ins[ni++] = sq_scr(7, 4, 0, 0, 0);                 /* LDL r4 <- 0 */
                ins[ni++] = sq_scr(7, 5, 0, 0, 1);                 /* LDL r5 <- 1 */
                ins[ni++] = sq_scr(7, 6, 0, 0, 2);                 /* LDL r6 <- 2 */
                ins[ni++] = sq_alu(CFT_FMA, 7, 0, 1, 4, 0, 0);     /* r7 = a*b + r4 */
                ins[ni++] = sq_alu(CFT_FMA, 8, 2, 0, 5, 1, 0);     /* r8 = c*k0 + r5 */
                ins[ni++] = sq_alu(CFT_ADD, 9, 7, 6, 0, 0, 0);     /* r9 = r7 + r6 */
                ins[ni++] = sq_ctrl(3, 9, 0);
                ins[ni++] = sq_ctrl(3, 8, 0);
                ins[ni++] = sq_scr(6, 0, 9, 0, 0);                 /* STL r9 -> 0 */
                ins[ni++] = sq_scr(6, 0, 7, 0, 1);                 /* STL r7 -> 1 */
                if (v == 2) {
                    ins[ni++] = sq_alu(CFT_IADD, 11, 12, 1, 0, 1, 0);  /* r11 = k1 */
                    ins[ni++] = sq_scr(9, 10, 0, 11, 0);           /* LDX r10 <- [300] */
                    ins[ni++] = sq_ctrl(3, 10, 0);
                }
                ins[ni++] = sq_ctrl(0, 0, 0);
                bytes = sq_image(img, f, ins, ni, k, 2, md, flags, (uint32_t)nsi,
                                 (uint32_t)nso);
                memset(&A, 0, sizeof A);
                A.struct_size = sizeof A;
                A.a = pa;
                A.b = pb;
                A.c = pc;
                A.n = n;
                if (v == 1) {
                    A.bank = k;
                    A.bank_bytes = 2 * esz;
                }
                A.scratch_in = pp;
                A.scratch_in_bytes = sp * esz;
                A.scratch_out = so;
                A.scratch_out_bytes = n * nso * esz;
                A.deposits = dep;
                A.counts = cnt;
                A.idx_a = ta;
                A.idx_b = tb;
                A.idx_c = tc;
                A.idx_a_src = sa;
                A.idx_b_src = sb;
                A.idx_c_src = sc;
                A.idx_scratch_in = tsi;
                A.idx_scratch_src = sp;
                A.lane_mask = m ? msk : NULL;
                A.lane_mask_bytes = m ? (n + 7) / 8 : 0;
                A.lane_flags = v == 2 ? lf : NULL;
                A.lane_flags_bytes = v == 2 ? n : 0;
                memset(dep, 0x5A, n * 3 * esz);
                memset(so, 0x5A, n * nso * esz);
                memset(lf, 0x5A, n);
                memset(cnt, 0x5A, n * 4);
                snprintf(what, sizeof what, "a program with four tables, %s, %s, n %lu, %s",
                         v == 0 ? "plain" : v == 1 ? "a bank" : "strict, lane bytes",
                         cft_format_name((cft_format)f), (unsigned long)n,
                         m ? "masked" : "no mask");
                st = prog_pair(hw, sw, f, img, bytes, &A, md, (uint32_t)nso, what);
                CHECK(st != CFT_OK || v != 2 || (pp_bus & CFT_STATUS_SCRATCH_RANGE),
                      "%s: STATUS 0x%x has no SCRATCH_RANGE for an LDX past the depth",
                      what, (unsigned)pp_bus);
                runs++;
            }
        /* a table past its source: refused by the host check, nothing run */
        ta[n - 1] = (uint32_t)sa;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = pa;
        A.n = n;
        A.deposits = dep;
        A.idx_a = ta;
        A.idx_a_src = sa;
        memset(dep, 0x5A, n * 3 * esz);
        ins[0] = sq_ctrl(3, 0, 0);
        ins[1] = sq_ctrl(0, 0, 0);
        st = cft_program_load(hw, img, sq_image(img, f, ins, 2, NULL, 0, 1, 0, 0, 0), &p);
        if (st == CFT_OK)
            st = cft_program_run_ex(p, &A);
        for (untouched = 1, i = 0; i < n * esz; i++)
            untouched &= dep[i] == 0x5A;
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && strstr(cft_last_error(), "at or past") &&
              untouched, "a table past its source, n %lu: %s, \"%s\", deposits %s",
              (unsigned long)n, cft_strerror(st), cft_last_error(),
              untouched ? "untouched" : "WRITTEN");
        if (si == 0 && (f == CFT_FP64 || f == CFT_FP32))
            printf("    a table past its source: %s - %s; the deposits %s\n",
                   cft_strerror(st), cft_last_error(), untouched ? "untouched" : "WRITTEN");
        cft_program_free(p);
    next:
        free(pa); free(pb); free(pc); free(pp); free(dep); free(so); free(lf); free(msk);
        free(ta); free(tb); free(tc); free(tsi); free(cnt);
    }
    printf("    cft_program_run_ex %s: %d runs with four tables, %d failed\n",
           cft_format_name((cft_format)f), runs, failures - before);
}

/* resident sources, tables and deposits: the second run binds resident, a
 * table republished between runs is the one read, and (in a plant build)
 * a table in a LOST buffer is refused by that buffer's sentence */
static void ix_resident(const char *artifact, cft_device *hw, cft_device *sw, int f)
{
    enum { N = 1000, SRC = 3000, POOL = 2500 };
    const size_t esz = cft_format_size((cft_format)f);
    static unsigned char s[SRC * 32], p[POOL * 32], want[N * 32], got[N * 32], prev[N * 32];
    static uint32_t t[N], tp[N], t2[N];
    unsigned char img[32 + 4 * 8];
    uint64_t ins[4];
    size_t bytes;
    struct rb S, T, P, TP, Dd;
    cft_buffer_info b1[4], b2[4];
    cft_program *ph = NULL, *ps = NULL;
    cft_run_args A;
    cft_status st;
    uint32_t fl = 0;
    int k, plant_build, before = failures;

    S.b = T.b = P.b = TP.b = Dd.b = NULL;
    ins[0] = sq_scr(7, 4, 0, 0, 0);                     /* LDL r4 <- 0 */
    ins[1] = sq_alu(CFT_ADD, 5, 0, 4, 0, 0, 0);         /* r5 = a + r4 */
    ins[2] = sq_ctrl(3, 5, 0);
    ins[3] = sq_ctrl(0, 0, 0);
    bytes = sq_image(img, f, ins, 4, NULL, 0, 1, CFT_PROG_FLAG_SCRATCH_IO, 1, 0);
    fill(s, SRC, f, K_RANDOM);
    fill(p, POOL, f, K_RANDOM);
    ix_table(t, N, SRC, 0);
    ix_table(tp, N, POOL, 3);
    for (k = 0; k < N; k++)
        t2[k] = t[(k + 1) % N];
    CHECK(rb_alloc(hw, &S, SRC * esz) && rb_alloc(hw, &T, N * 4) &&
          rb_alloc(hw, &P, POOL * esz) && rb_alloc(hw, &TP, N * 4) &&
          rb_alloc(hw, &Dd, N * esz), "cft_alloc: %s", cft_last_error());
    if (!S.b || !T.b || !P.b || !TP.b || !Dd.b)
        goto out;
    CHECK(rb_put(&S, s, SRC * esz) && rb_put(&T, (const unsigned char *)t, N * 4) &&
          rb_put(&P, p, POOL * esz) && rb_put(&TP, (const unsigned char *)tp, N * 4),
          "publishing: %s", cft_last_error());
    CHECK(cft_program_load(hw, img, bytes, &ph) == CFT_OK &&
          cft_program_load(sw, img, bytes, &ps) == CFT_OK, "loading: %s", cft_last_error());
    if (!ph || !ps)
        goto out;
    for (k = 0; k < 3; k++) {
        const uint32_t *tab = k < 2 ? t : t2;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.n = N;
        A.idx_a_src = SRC;
        A.idx_scratch_src = POOL;
        A.scratch_in_bytes = POOL * esz;
        A.flags_out = &fl;
        /* the software handle, on plain memory with the same bytes */
        A.a = s;
        A.idx_a = tab;
        A.scratch_in = p;
        A.idx_scratch_in = tp;
        A.deposits = want;
        st = cft_program_run_ex(ps, &A);
        CHECK(st == CFT_OK, "the software handle: %s", cft_last_error());
        /* the GPU, every operand resident */
        b1[0] = rb_info(&S); b1[1] = rb_info(&T); b1[2] = rb_info(&P); b1[3] = rb_info(&TP);
        A.a = S.p;
        A.idx_a = (const uint32_t *)T.p;
        A.scratch_in = P.p;
        A.idx_scratch_in = (const uint32_t *)TP.p;
        A.deposits = Dd.p;
        st = cft_program_run_ex(ph, &A);
        CHECK(st == CFT_OK && cft_buffer_from_device(Dd.b) == CFT_OK,
              "resident run %d: %s", k + 1, cft_last_error());
        memcpy(got, Dd.p, N * esz);
        b2[0] = rb_info(&S); b2[1] = rb_info(&T); b2[2] = rb_info(&P); b2[3] = rb_info(&TP);
        CHECK(same(got, want, N * esz), "resident run %d, %s: the deposits differ from the "
              "software handle's", k + 1, cft_format_name((cft_format)f));
        if (k == 1) {
            int j, held = 1;
            for (j = 0; j < 4; j++)
                held &= b2[j].resident_binds == b1[j].resident_binds + 1 &&
                        b2[j].staged_binds == b1[j].staged_binds;
            CHECK(held, "the second run, %s: source, table, pool and its table should each "
                  "bind resident with no transfer - resident binds %llu/%llu/%llu/%llu "
                  "from %llu/%llu/%llu/%llu, staged %llu/%llu/%llu/%llu from "
                  "%llu/%llu/%llu/%llu", cft_format_name((cft_format)f),
                  (unsigned long long)b2[0].resident_binds,
                  (unsigned long long)b2[1].resident_binds,
                  (unsigned long long)b2[2].resident_binds,
                  (unsigned long long)b2[3].resident_binds,
                  (unsigned long long)b1[0].resident_binds,
                  (unsigned long long)b1[1].resident_binds,
                  (unsigned long long)b1[2].resident_binds,
                  (unsigned long long)b1[3].resident_binds,
                  (unsigned long long)b2[0].staged_binds,
                  (unsigned long long)b2[1].staged_binds,
                  (unsigned long long)b2[2].staged_binds,
                  (unsigned long long)b2[3].staged_binds,
                  (unsigned long long)b1[0].staged_binds,
                  (unsigned long long)b1[1].staged_binds,
                  (unsigned long long)b1[2].staged_binds,
                  (unsigned long long)b1[3].staged_binds);
            printf("    resident, %s: the second run bound source, table, pool and its "
                   "table resident: %s\n", cft_format_name((cft_format)f),
                   held ? "yes" : "NO");
            memcpy(prev, got, N * esz);
            /* the table rewritten and published: the next run reads it */
            memcpy(T.p, t2, N * 4);
            CHECK(cft_buffer_to_device(T.b) == CFT_OK, "republishing the table: %s",
                  cft_last_error());
        }
        if (k == 2)
            CHECK(!same(got, prev, N * esz), "the republished table, %s: the run answered "
                  "as for the old table", cft_format_name((cft_format)f));
    }
    /* a table in a LOST buffer, with a plant build's fail-launch: a run that
     * wrote the buffer failed, and a program reading it as a table is
     * refused by the loss's sentence, before anything runs */
    {
        /* the plant this process was started with, if any, is put back
         * after: a later leg's handles must open with it */
        const char *was = getenv("CFT_HIP_PLANT");
        char keep[64] = "";
        cft_device *h = NULL;
        if (was)
            snprintf(keep, sizeof keep, "%s", was);
        put_env("CFT_HIP_PLANT", "bogus");
        st = cft_open(artifact, 0, &h);
        put_env("CFT_HIP_PLANT", keep[0] ? keep : NULL);
        plant_build = st != CFT_OK;
        if (h)
            cft_close(h);
    }
    if (!plant_build) {
        nrun("  a table in a LOST buffer", "this libcft is a default build, which has no "
             "CFT_HIP_PLANT=fail-launch to lose one; build with HIP_PLANTS=1");
    } else {
        const char *was = getenv("CFT_HIP_PLANT");
        char keep[64] = "";
        cft_device *h = NULL;
        struct rb L;
        cft_program *pl = NULL;
        L.b = NULL;
        if (was)
            snprintf(keep, sizeof keep, "%s", was);
        put_env("CFT_HIP_PLANT", "fail-launch");
        st = cft_open(artifact, 0, &h);
        put_env("CFT_HIP_PLANT", keep[0] ? keep : NULL);
        if (h && rb_alloc(h, &L, N * 4) && rb_put(&L, (const unsigned char *)t, N * 4) &&
            cft_program_load(h, img, bytes, &pl) == CFT_OK) {
            st = cft_run(h, CFT_ABS, CFT_FP32, CFT_RNE, s, NULL, NULL, L.p, N, &fl, NULL);
            CHECK(st == CFT_ERR_INTERNAL && !strncmp(rb_info(&L).staged_why, "LOST:", 5),
                  "the failed run: %s, buffer \"%s\"", cft_strerror(st), rb_info(&L).staged_why);
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.n = N;
            A.a = s;
            A.idx_a = (const uint32_t *)L.p;
            A.idx_a_src = SRC;
            A.scratch_in = p;
            A.scratch_in_bytes = POOL * esz;
            A.idx_scratch_in = tp;
            A.idx_scratch_src = POOL;
            A.deposits = got;
            st = cft_program_run_ex(pl, &A);
            CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "failed on the device"),
                  "a table in a LOST buffer: %s, \"%s\"", cft_strerror(st), cft_last_error());
            printf("    a table in a LOST buffer: %s - %s\n", cft_strerror(st),
                   cft_last_error());
        } else {
            CHECK(0, "the fail-launch handle: %s", cft_last_error());
        }
        cft_program_free(pl);
        rb_free(&L);
        cft_close(h);
    }
out:
    cft_program_free(ph);
    cft_program_free(ps);
    rb_free(&S);
    rb_free(&T);
    rb_free(&P);
    rb_free(&TP);
    rb_free(&Dd);
    printf("    resident %s: %d failed\n", cft_format_name((cft_format)f), failures - before);
}

/* a source larger than any stage (96 MiB; a stage is at most 64 MiB), read
 * through a table over all of it whose lanes cross many chunks */
static void ix_big(cft_device *hw, cft_device *sw, int f)
{
    const size_t esz = cft_format_size((cft_format)f);
    const size_t srcn = ((size_t)96 << 20) / esz, n = 200000;
    unsigned char *src = (unsigned char *)malloc(srcn * esz);
    unsigned char *dep = (unsigned char *)malloc(n * esz);
    uint32_t *t = (uint32_t *)malloc(n * 4);
    unsigned char img[32 + 2 * 8];
    uint64_t ins[2];
    char what[120];
    cft_run_args A;
    if (!src || !dep || !t) {
        CHECK(0, "a 96 MiB source: out of host memory");
    } else {
        fill(src, srcn, f, K_RANDOM);
        ix_table(t, n, srcn, 0);
        ins[0] = sq_ctrl(3, 0, 0);
        ins[1] = sq_ctrl(0, 0, 0);
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = src;
        A.n = n;
        A.deposits = dep;
        A.idx_a = t;
        A.idx_a_src = srcn;
        memset(dep, 0x5A, n * esz);
        snprintf(what, sizeof what, "a %lu-element %s source (96 MiB) through %lu lanes",
                 (unsigned long)srcn, cft_format_name((cft_format)f), (unsigned long)n);
        (void)prog_pair(hw, sw, f, img, sq_image(img, f, ins, 2, NULL, 0, 1, 0, 0, 0), &A, 1,
                        0, what);
        printf("    %s: compared\n", what);
    }
    free(src);
    free(dep);
    free(t);
}

static void leg_indexed(const char *artifact, cft_device *hw, cft_device *sw, int only_fmt,
                        int small)
{
    const int before = failures;
    int f;
    printf("indexed\n");
    for (f = 0; f < 4; f++) {
        if (only_fmt >= 0 && f != only_fmt)
            continue;
        ix_elem(hw, sw, f, small);
        ix_prog(hw, sw, f, small);
    }
    for (f = CFT_FP64; f <= CFT_FP256; f += 2) {
        if (only_fmt >= 0 && f != only_fmt)
            continue;
        ix_resident(artifact, hw, sw, f);
        if (small)
            nrun("  a 96 MiB source", "-s small leaves it out; -s large or all runs it");
        else
            ix_big(hw, sw, f);
    }
    printf("  indexed: %d failed\n", failures - before);
}

/* An STX/LDX walk of `walk` slots (device-test's, at a length of its own):
 * v stored into slots 0 .. walk - 1, then read back from walk - 1 down and
 * summed - past the depth it wraps (plain) or is reported (strict) */
static size_t walk_image(unsigned char *img, int fmt, uint32_t walk, int strict)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    unsigned char k[3 * 32];
    uint64_t ins[14];
    put_int(k, fmt, 1);                                   /* k0: the integer 1 */
    one_plus(k + esz, fmt, 8);                            /* k1: 1 + 2^-8 */
    one_plus(k + 2 * esz, fmt, 0);                        /* k2: 1 */
    ins[0] = sq_alu(CFT_COPYSIGN, 4, 0, 0, 0, 0, 0);       /* v = x */
    ins[1] = sq_ctrl(1, 0, walk);
    ins[2] = sq_scr(8, 0, 4, 3, 0);                       /*   STX v -> [i] */
    ins[3] = sq_alu(CFT_IADD, 3, 3, 0, 0, 1, 0);           /*   i += 1 */
    ins[4] = sq_alu(CFT_FMA, 4, 4, 1, 2, 1, 1);            /*   v = v * k1 + k2 */
    ins[5] = sq_ctrl(2, 0, 0);
    ins[6] = sq_ctrl(1, 0, walk);
    ins[7] = sq_alu(CFT_ISUB, 3, 3, 0, 0, 1, 0);           /*   i -= 1 */
    ins[8] = sq_scr(9, 5, 0, 3, 0);                       /*   LDX s <- [i] */
    ins[9] = sq_alu(CFT_FMA, 6, 5, 2, 6, 1, 0);            /*   acc = s * k2 + acc */
    ins[10] = sq_ctrl(2, 0, 0);
    ins[11] = sq_ctrl(3, 6, 0);
    ins[12] = sq_ctrl(3, 4, 0);
    ins[13] = sq_ctrl(0, 0, 0);
    return sq_image(img, fmt, ins, 14, k, 3, 2, strict ? CFT_PROG_FLAG_SCRATCH_STRICT : 0u,
                    0, 0);
}

/* STL x -> slot; LDL r4 <- slot; deposit r4 */
static size_t slot_image(unsigned char *img, int fmt, uint32_t slot)
{
    uint64_t ins[4];
    ins[0] = sq_scr(6, 0, 0, 0, slot);
    ins[1] = sq_scr(7, 4, 0, 0, slot);
    ins[2] = sq_ctrl(3, 4, 0);
    ins[3] = sq_ctrl(0, 0, 0);
    return sq_image(img, fmt, ins, 4, NULL, 0, 1, 0, 0, 0);
}

static cft_status open_at(const char *artifact, uint32_t depth, cft_device **out)
{
    cft_open_args oa;
    memset(&oa, 0, sizeof oa);
    oa.struct_size = sizeof oa;
    oa.artifact = artifact;
    oa.scratch_depth = depth;
    *out = NULL;
    return cft_open_ex(&oa, out);
}

/* a load that must be refused by name, naming max_scratch */
static void load_refused(cft_device *dev, const unsigned char *img, size_t bytes,
                         const char *what)
{
    cft_program *p = NULL;
    const cft_status st = cft_program_load(dev, img, bytes, &p);
    CHECK(st != CFT_OK && p == NULL && strstr(cft_last_error(), "max_scratch"),
          "%s: %s, \"%s\" - wanted a refusal naming max_scratch", what, cft_strerror(st),
          cft_last_error());
    printf("    %s: %s - %s\n", what, cft_strerror(st), cft_last_error());
    cft_program_free(p);
}

static void leg_depth(const char *artifact, cft_device *hw, cft_device *sw, int only_fmt)
{
    static const uint32_t DS[4] = {256, 512, 1024, 2048};
    enum { N = 100, NB = 300, S273 = 273 };
    static unsigned char a[NB * 32], dh[NB * 2 * 32], d256[NB * 2 * 32],
        img[32 + 3 * 32 + 14 * 8];
    unsigned char *sin_ = NULL, *sout = NULL;
    cft_device *h = NULL, *s = NULL;
    cft_run_args A;
    cft_caps hc, scp;
    char what[160];
    size_t bytes, di;
    int f, strict;
    const int before = failures;

    printf("depth\n");
    for (di = 0; di < 4; di++) {
        const uint32_t D = DS[di];
        memset(&hc, 0, sizeof hc);
        hc.struct_size = sizeof hc;
        memset(&scp, 0, sizeof scp);
        scp.struct_size = sizeof scp;
        CHECK(open_at(artifact, D, &h) == CFT_OK && open_at(NULL, D, &s) == CFT_OK &&
              cft_get_caps(h, &hc) == CFT_OK && cft_get_caps(s, &scp) == CFT_OK &&
              hc.max_scratch == D && scp.max_scratch == D,
              "opening %s and the software handle at %u: %s (max_scratch %u and %u)",
              artifact, (unsigned)D, cft_last_error(), (unsigned)hc.max_scratch,
              (unsigned)scp.max_scratch);
        if (!h || !s)
            goto next;
        for (f = CFT_FP64; f <= CFT_FP256; f += 2) {
            if (only_fmt >= 0 && f != only_fmt)
                continue;
            fill(a, N, f, K_RANDOM);
            for (strict = 0; strict < 2; strict++) {
                bytes = walk_image(img, f, D + 44, strict);
                memset(&A, 0, sizeof A);
                A.struct_size = sizeof A;
                A.a = A.b = A.c = a;
                A.n = N;
                A.deposits = dh;
                memset(dh, 0x5A, N * 2 * 32);
                snprintf(what, sizeof what, "a walk of %u slots at depth %u, %s%s",
                         (unsigned)(D + 44), (unsigned)D, cft_format_name((cft_format)f),
                         strict ? ", strict" : "");
                (void)prog_pair(h, s, f, img, bytes, &A, 2, 0, what);
                CHECK(!strict || (pp_bus & CFT_STATUS_SCRATCH_RANGE),
                      "%s: STATUS 0x%x - an index past %u must be reported", what,
                      (unsigned)pp_bus, (unsigned)D);
                if (D > 256) {
                    /* and the depth reached past 256: the same walk on the
                     * default (256-slot) handle wraps there (plain) or
                     * reports there (strict) and answers otherwise */
                    cft_program *p = NULL;
                    uint32_t b256 = 0;
                    A.deposits = d256;
                    A.bus_out = &b256;
                    CHECK(cft_program_load(sw, img, bytes, &p) == CFT_OK &&
                          cft_program_run_ex(p, &A) == CFT_OK, "the 256-slot reference: %s",
                          cft_last_error());
                    cft_program_free(p);
                    CHECK(!same(dh, d256, N * 2 * cft_format_size((cft_format)f)),
                          "%s: the GPU at %u answered as a 256-slot handle does - the "
                          "comparison could not tell the depths apart", what, (unsigned)D);
                }
            }
            /* a static slot at depth - 1 runs; one at the depth is refused */
            bytes = slot_image(img, f, D - 1);
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a;
            A.n = N;
            A.deposits = dh;
            memset(dh, 0x5A, N * 32);
            snprintf(what, sizeof what, "static slot %u at depth %u, %s", (unsigned)(D - 1),
                     (unsigned)D, cft_format_name((cft_format)f));
            (void)prog_pair(h, s, f, img, bytes, &A, 1, 0, what);
            bytes = slot_image(img, f, D);
            snprintf(what, sizeof what, "static slot %u at depth %u", (unsigned)D,
                     (unsigned)D);
            load_refused(h, img, bytes, what);
        }
        printf("  depth %u: the walk, plain and strict, and slot %u held to the software "
               "handle at %u\n", (unsigned)D, (unsigned)(D - 1), (unsigned)D);
    next:
        cft_close(h);
        cft_close(s);
        h = s = NULL;
    }

    /* 273 static slots at 512, with a scratch-in and scratch-out block of
     * 273 (cft-debris's degree-8 field): reach 273, not the depth */
    sin_ = (unsigned char *)malloc((size_t)NB * S273 * 32);
    sout = (unsigned char *)malloc((size_t)NB * S273 * 32);
    if (!sin_ || !sout || open_at(artifact, 512, &h) != CFT_OK ||
        open_at(NULL, 512, &s) != CFT_OK) {
        CHECK(0, "the 273-slot program: %s", cft_last_error());
    } else {
        for (f = CFT_FP64; f <= CFT_FP256; f += 2) {
            const size_t esz = cft_format_size((cft_format)f);
            uint64_t ins[8];
            if (only_fmt >= 0 && f != only_fmt)
                continue;
            ins[0] = sq_scr(7, 4, 0, 0, S273 - 1);             /* LDL r4 <- 272 */
            ins[1] = sq_scr(7, 5, 0, 0, 0);                    /* LDL r5 <- 0 */
            ins[2] = sq_alu(CFT_FMA, 6, 4, 5, 0, 0, 0);        /* r6 = r4*r5 + a */
            ins[3] = sq_scr(6, 0, 6, 0, S273 - 1);             /* STL r6 -> 272 */
            ins[4] = sq_scr(6, 0, 4, 0, 0);                    /* STL r4 -> 0 */
            ins[5] = sq_ctrl(3, 6, 0);
            ins[6] = sq_ctrl(0, 0, 0);
            bytes = sq_image(img, f, ins, 7, NULL, 0, 1, CFT_PROG_FLAG_SCRATCH_IO, S273, S273);
            fill(a, NB, f, K_RANDOM);
            fill(sin_, (size_t)NB * S273, f, K_RANDOM);
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a;
            A.n = NB;
            A.deposits = dh;
            A.scratch_in = sin_;
            A.scratch_in_bytes = (size_t)NB * S273 * esz;
            A.scratch_out = sout;
            A.scratch_out_bytes = (size_t)NB * S273 * esz;
            memset(dh, 0x5A, NB * esz);
            memset(sout, 0x5A, (size_t)NB * S273 * esz);
            snprintf(what, sizeof what, "273 static slots and a 273-slot block at depth "
                     "512, %s", cft_format_name((cft_format)f));
            (void)prog_pair(h, s, f, img, bytes, &A, 1, S273, what);
            printf("    %s: held to the software handle at 512\n", what);
            load_refused(hw, img, bytes, "the 273-slot block on the default 256-slot handle");
        }
    }
    cft_close(h);
    cft_close(s);
    h = s = NULL;
    free(sin_);
    free(sout);

    /* slot 256 on the default handle; slot 2,047 on a 256-slot one, which
     * a 2,048-slot one loads */
    bytes = slot_image(img, CFT_FP64, 256);
    load_refused(hw, img, bytes, "static slot 256 on the default handle");
    if (open_at(artifact, 256, &h) == CFT_OK && open_at(artifact, 2048, &s) == CFT_OK) {
        cft_program *p = NULL;
        bytes = slot_image(img, CFT_FP64, 2047);
        load_refused(h, img, bytes, "static slot 2047 on a handle opened at 256");
        CHECK(cft_program_load(s, img, bytes, &p) == CFT_OK,
              "static slot 2047 on a handle opened at 2048: %s", cft_last_error());
        cft_program_free(p);
    } else {
        CHECK(0, "opening at 256 and 2048: %s", cft_last_error());
    }
    cft_close(h);
    cft_close(s);
    h = s = NULL;

    /* a 2,048-slot handle beside the default, both run, in turn */
    if (open_at(artifact, 2048, &h) == CFT_OK && open_at(NULL, 2048, &s) == CFT_OK) {
        int round;
        fill(a, N, CFT_FP64, K_RANDOM);
        bytes = walk_image(img, CFT_FP64, 300, 0);
        for (round = 0; round < 2; round++) {
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = A.b = A.c = a;
            A.n = N;
            A.deposits = dh;
            (void)prog_pair(h, s, CFT_FP64, img, bytes, &A, 2, 0,
                            "a walk of 300 on the 2,048-slot handle beside the default");
            A.deposits = d256;
            (void)prog_pair(hw, sw, CFT_FP64, img, bytes, &A, 2, 0,
                            "a walk of 300 on the default handle beside a 2,048-slot one");
        }
        CHECK(!same(dh, d256, N * 2 * 8), "the 2,048-slot handle and the default answered "
              "alike for a walk of 300: one of them is not at its depth");
        printf("    a 2,048-slot handle beside the default: each held to its own depth's "
               "software handle, twice in turn\n");
    } else {
        CHECK(0, "a 2,048-slot handle beside the default: %s", cft_last_error());
    }
    cft_close(h);
    cft_close(s);
    printf("  depth: %d failed\n", failures - before);
}

/* round 2's G2C: its leg functions here */

/* ---- the divide and the square root (round 2's G2C) ------------------------ */

/* The plant build's instrument (backend_hip.cpp's cfth_plant_prog_probe): the
 * last program run's n, esz, reach, lane pool, ... head (6) ... launches
 * (11). Weak, so that a default build, which defines no such symbol, links
 * and finds it NULL; NULL by definition where no GPU build exists. */
#if defined(__GNUC__) && !defined(_WIN32)
extern int cfth_plant_prog_probe(uint64_t *out, int nout) __attribute__((weak));
#define DS_PROBE_FN cfth_plant_prog_probe
#else
#define DS_PROBE_FN NULL
#endif

enum { DS_P = 24, DS_ALL = DS_P * DS_P + 1, DS_BIG = 5000, DS_NDIV1 = 68 };
static const char *const DSN[2] = {"cft_div", "cft_sqrt"};
static const char *const DSI[2] = {"divfull", "sqrtfull"};
static const char *const DSR[3] = {"the chunk route", "the program route",
                                   "the whole-operation route"};
static unsigned char ds_pl[DS_P * 32], ds_xa[DS_BIG * 32], ds_xb[DS_BIG * 32],
    ds_dh[2 * DS_BIG * 32], ds_ds[2 * DS_BIG * 32], ds_t[DS_BIG * 32], ds_g[DS_BIG * 32],
    ds_bk[CFT_SQRTFULL_NCONSTS * 32], ds_r1[2][DS_NDIV1 * 32], ds_rb[2][2][DS_BIG * 32];
static uint32_t ds_ch[DS_BIG], ds_cs[DS_BIG], ds_r1f[2][DS_NDIV1], ds_rbf[2][2];

/* the image of the divide (op 0) or the square root (op 1) at fmt, and its
 * bank built exactly as divsqrt.c's full_via_program builds it - the fixed
 * words, then the five mode words with a little-endian 1 in the attribute's
 * slot; returns the bank's bytes */
static const cft_divfull_entry *ds_entry(int op, int fmt)
{
    return op ? &cft_sqrtfull_images[fmt] : &cft_divfull_images[fmt];
}

static size_t ds_bank(int op, int fmt, int rnd)
{
    const cft_divfull_entry *e = ds_entry(op, fmt);
    const size_t esz = cft_format_size((cft_format)fmt);
    memcpy(ds_bk, e->bank, e->n_fixed * esz);
    memset(ds_bk + e->n_fixed * esz, 0, CFT_DIVFULL_NMODES * esz);
    ds_bk[(e->n_fixed + (size_t)rnd) * esz] = 1;
    return e->n_consts * esz;
}

/* The leg's operands at one format (aug_put's encodings): 1 and 3 (lane 0's
 * inexact 1/3), signed zeros and infinities, quiet and signalling NaNs of
 * both signs, -1, 1 + u, 2 and 0.5, the smallest and largest subnormals and
 * a random negative one, the smallest normal and its odd neighbour (halved,
 * an exact tie below the normal range, as the smallest subnormal halved is),
 * the largest finite of both signs (over 0.5: past the overflow threshold),
 * and three random finite values - every class a divide has a rule for in
 * each position, and as the root's operands its classes: negative finites,
 * -0, both infinities, both NaNs, odd and even exponents, subnormals. */
static void ds_lanes(int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const unsigned long bias = (1ul << (EXPW[fmt] - 1)) - 1, top = (1ul << EXPW[fmt]) - 1;
    const struct { int s; unsigned long x; int m; } v[DS_P] = {
        {0, bias, 0}, {0, bias + 1, 3},                       /* 1, 3 */
        {0, 0, 0}, {1, 0, 0}, {0, top, 0}, {1, top, 0},       /* zeros, infinities */
        {0, top, 5}, {0, top, 6}, {1, top, 5}, {1, top, 6},   /* NaNs: quiet, signalling */
        {1, bias, 0}, {0, bias, 1}, {0, bias + 1, 0}, {0, bias - 1, 0},   /* -1, 1+u, 2, .5 */
        {0, 0, 1}, {0, 0, 2}, {1, 0, 4},                      /* subnormals */
        {0, 1, 0}, {0, 1, 1},                                 /* the smallest normal, +1 ulp */
        {0, top - 1, 2}, {1, top - 1, 2},                     /* the largest finite */
        {0, bias - 7, 4}, {1, bias + 9, 4}, {0, bias + 30, 4}};
    size_t i;
    for (i = 0; i < DS_P; i++)
        aug_put(ds_pl + i * esz, fmt, v[i].s, v[i].x, v[i].m);
    /* lane 0 is 1/3 (the root's lanes are b's: sqrt(3)), an inexact result,
     * so a fault on lane 0 shows; lanes 1 to 576 every pair (p, q) of the
     * pool at lane 1 + 24p + q; past them random finite values */
    fill(ds_xa, DS_BIG, fmt, K_RANDOM);
    fill(ds_xb, DS_BIG, fmt, K_RANDOM);
    memcpy(ds_xa, ds_pl, esz);
    memcpy(ds_xb, ds_pl + esz, esz);
    for (i = 1; i < DS_ALL; i++) {
        memcpy(ds_xa + i * esz, ds_pl + ((i - 1) / DS_P) * esz, esz);
        memcpy(ds_xb + i * esz, ds_pl + ((i - 1) % DS_P) * esz, esz);
    }
}

/* a quiet NaN's encoding: every exponent bit and the top significand bit */
static int ds_qnan(const unsigned char *e, int fmt)
{
    const int width = (int)cft_format_size((cft_format)fmt) * 8, mw = width - 1 - EXPW[fmt];
    int b;
    for (b = mw; b < width - 1; b++)
        if (!((e[b / 8] >> (b % 8)) & 1u))
            return 0;
    return (e[(mw - 1) / 8] >> ((mw - 1) % 8)) & 1u;
}

/* A direct run on both handles held: both statuses CFT_OK, then every lane's
 * two deposits (the result, the flag word) and its count (2), the run's
 * flags and its STATUS, byte for byte. A FAIL line names the first lane. */
static void ds_runs_held(int op, int fmt, int rnd, size_t n, const char *what,
                         cft_status sh, cft_status ss, const char *msg, uint32_t fh,
                         uint32_t fs, uint32_t bh, uint32_t bs)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    char x1[70], x2[70];
    size_t i = 0;
    if (sh != CFT_OK || ss != CFT_OK) {
        CHECK(0, "%s %s %s n=%lu %s: GPU %s (%s), software %s", DSI[op],
              cft_format_name((cft_format)fmt), RND[rnd], (unsigned long)n, what,
              cft_strerror(sh), msg, cft_strerror(ss));
        return;
    }
    while (i < n && ds_ch[i] == CFT_DIVFULL_NDEPOSITS && ds_cs[i] == CFT_DIVFULL_NDEPOSITS &&
           same(ds_dh + 2 * i * esz, ds_ds + 2 * i * esz, 2 * esz))
        i++;
    if (i == n && fh == fs && bh == bs) {
        checks++;
        return;
    }
    if (i == n)
        i = 0;                          /* the run's words alone differ */
    hex(x1, ds_dh + 2 * i * esz, esz);
    hex(x2, ds_ds + 2 * i * esz, esz);
    CHECK(0, "%s %s %s n=%lu %s: lane %lu: GPU %s flag word 0x%02x count %u, software %s "
          "flag word 0x%02x count %u; the run's flags 0x%x and 0x%x, STATUS 0x%x and 0x%x",
          DSI[op], cft_format_name((cft_format)fmt), RND[rnd], (unsigned long)n, what,
          (unsigned long)i, x1, (unsigned)ds_dh[(2 * i + 1) * esz], (unsigned)ds_ch[i], x2,
          (unsigned)ds_ds[(2 * i + 1) * esz], (unsigned)ds_cs[i], (unsigned)fh, (unsigned)fs,
          (unsigned)bh, (unsigned)bs);
}

/* the image run on each handle with the same bank and lanes, the outputs and
 * flag words of each filled with a pattern of its own first */
static void ds_run_pair(cft_program *ph, cft_program *ps, int op, int fmt, int rnd,
                        size_t n, const char *what)
{
    const size_t esz = cft_format_size((cft_format)fmt), bb = ds_bank(op, fmt, rnd);
    const unsigned char *a = op ? ds_xb : ds_xa, *b = op ? NULL : ds_xb;
    uint32_t fh = 0xA5A5u, fs = 0x5A5Au, bh = 0xA5u, bs = 0x5Au;
    char msg[400];
    cft_status sh, ss;
    size_t i;
    memset(ds_dh, 0x3C, 2 * n * esz);
    memset(ds_ds, 0x69, 2 * n * esz);
    for (i = 0; i < n; i++) {
        ds_ch[i] = 0xEEEEu;
        ds_cs[i] = 0x1111u;
    }
    sh = cft_program_run_bank(ph, ds_bk, bb, a, b, NULL, ds_dh, ds_ch, n, &fh, &bh);
    snprintf(msg, sizeof msg, "%s", cft_last_error());
    ss = cft_program_run_bank(ps, ds_bk, bb, a, b, NULL, ds_ds, ds_cs, n, &fs, &bs);
    ds_runs_held(op, fmt, rnd, n, what, sh, ss, msg, fh, fs, bh, bs);
}

/* (a) the image itself: hip:N's loader's answer, then runs at every
 * attribute - lane 0 alone and every pair at each, 5,000 lanes at one - and
 * at fp64 a signalling NaN in each position (both signs): a quiet NaN out,
 * INVALID in deposit 1 */
static void ds_direct(cft_device *hw, cft_device *sw, int op, int fmt,
                      int (*probe)(uint64_t *, int))
{
    const cft_divfull_entry *e = ds_entry(op, fmt);
    const size_t esz = cft_format_size((cft_format)fmt);
    const int checks0 = checks, before = failures;
    cft_program *ph = NULL, *ps = NULL;
    cft_status st;
    int rnd;
    st = cft_program_load(hw, e->image, e->image_bytes, &ph);
    printf("    %s %s, %lu bytes, %lu constants (%lu fixed + 5 modes): hip:N's loader: %s%s%s\n",
           DSI[op], cft_format_name((cft_format)fmt), (unsigned long)e->image_bytes,
           (unsigned long)e->n_consts, (unsigned long)e->n_fixed, cft_strerror(st),
           st == CFT_OK ? "" : " - ", st == CFT_OK ? "" : cft_last_error());
    CHECK(st == CFT_OK, "the %s image at %s: hip:N refused it - %s", DSI[op],
          cft_format_name((cft_format)fmt), cft_last_error());
    CHECK(cft_program_load(sw, e->image, e->image_bytes, &ps) == CFT_OK,
          "the %s image at %s: the software handle refused it - %s", DSI[op],
          cft_format_name((cft_format)fmt), cft_last_error());
    if (ph && ps) {
        for (rnd = 0; rnd < 5; rnd++) {
            ds_run_pair(ph, ps, op, fmt, rnd, 1, "lane 0 alone");
            ds_run_pair(ph, ps, op, fmt, rnd, DS_ALL, "every pair");
        }
        ds_run_pair(ph, ps, op, fmt, fmt % 5, DS_BIG, "5,000 lanes");
        if (probe) {
            uint64_t v[16];
            memset(v, 0, sizeof v);
            (void)probe(v, 16);
            printf("      5,000 lanes, %s: the probe says %llu launches of %llu to %llu lanes "
                   "(head %llu, reach %llu)\n", RND[fmt % 5], (unsigned long long)v[11],
                   (unsigned long long)v[13], (unsigned long long)v[12],
                   (unsigned long long)v[6], (unsigned long long)v[2]);
        }
        if (fmt == CFT_FP64) {
            /* lanes 169 and 8: +sNaN / 1 and 1 / +sNaN; 217 and 10 the same
             * with -sNaN; the root's lanes 8 and 10 are +sNaN and -sNaN */
            static const size_t LD[4] = {169, 8, 217, 10}, LR[2] = {8, 10};
            const int nl = op ? 2 : 4;
            int j;
            ds_run_pair(ph, ps, op, fmt, CFT_RNE, DS_ALL, "every pair, again");
            for (j = 0; j < nl; j++) {
                const size_t l = op ? LR[j] : LD[j];
                const unsigned w = ds_dh[(2 * l + 1) * esz];
                CHECK((w & CFT_FLAG_INVALID) && ds_qnan(ds_dh + 2 * l * esz, fmt),
                      "%s fp64 lane %lu (a signalling NaN): flag word 0x%02x, result %s a "
                      "quiet NaN - INVALID and a quiet NaN wanted", DSI[op],
                      (unsigned long)l, w, ds_qnan(ds_dh + 2 * l * esz, fmt) ? "is" : "is not");
                printf("      fp64, a signalling NaN in lane %lu: flag word 0x%02x, result a "
                       "quiet NaN: %s\n", (unsigned long)l, w,
                       ds_qnan(ds_dh + 2 * l * esz, fmt) ? "yes" : "NO");
            }
        }
    }
    cft_program_free(ph);
    cft_program_free(ps);
    printf("      %s %s: %d runs held, %d failed\n", DSI[op], cft_format_name((cft_format)fmt),
           checks - checks0, failures - before);
}

/* (b) Resident: a, b and the deposits in cft_alloc buffers on hip:N, every
 * pair at rne: the deposits left on the device after a good run (the
 * authority mark) and read back equal to the software handle's; the second
 * run binding a, b and the deposits with no page moved. */
static void ds_resident(cft_device *hw, cft_device *sw, int op, int fmt)
{
    const cft_divfull_entry *e = ds_entry(op, fmt);
    const size_t esz = cft_format_size((cft_format)fmt), n = DS_ALL, ib = n * esz,
                 db = 2 * n * esz, bb = ds_bank(op, fmt, CFT_RNE);
    const unsigned char *in = op ? ds_xb : ds_xa;
    struct rb A, B, D;
    struct rb *all[3];
    cft_buffer_info i0[3], i1[3];
    cft_program *ph = NULL, *ps = NULL;
    uint32_t fh = 0, fs = 0, bh = 0, bs = 0;
    cft_status sh, ss;
    char msg[400];
    const int nb = op ? 2 : 3;
    int run, k, still = 1;
    A.b = B.b = D.b = NULL;
    all[0] = &A;
    all[1] = &D;
    all[2] = &B;
    if (cft_program_load(hw, e->image, e->image_bytes, &ph) != CFT_OK ||
        cft_program_load(sw, e->image, e->image_bytes, &ps) != CFT_OK) {
        CHECK(0, "%s %s resident: loading the image: %s", DSI[op],
              cft_format_name((cft_format)fmt), cft_last_error());
        goto out;
    }
    CHECK(rb_alloc(hw, &A, ib) && rb_alloc(hw, &D, db) && (op || rb_alloc(hw, &B, ib)),
          "cft_alloc: %s", cft_last_error());
    if (!A.b || !D.b || (!op && !B.b))
        goto out;
    CHECK(rb_put(&A, in, ib) && (op || rb_put(&B, ds_xb, ib)), "publishing: %s",
          cft_last_error());
    memset(ds_ds, 0x69, db);
    ss = cft_program_run_bank(ps, ds_bk, bb, in, op ? NULL : ds_xb, NULL, ds_ds, ds_cs, n, &fs,
                              &bs);
    for (run = 0; run < 2; run++) {
        for (k = 0; k < nb; k++)
            i0[k] = rb_info(all[k]);
        sh = cft_program_run_bank(ph, ds_bk, bb, A.p, op ? NULL : B.p, NULL, D.p, ds_ch, n, &fh,
                                  &bh);
        snprintf(msg, sizeof msg, "%s", cft_last_error());
        for (k = 0; k < nb; k++)
            i1[k] = rb_info(all[k]);
        CHECK(sh != CFT_OK || i1[1].device_authority == 1, "%s %s resident: the deposits are "
              "not left on the device (authority %d)", DSI[op], cft_format_name((cft_format)fmt),
              i1[1].device_authority);
        if (run == 1) {
            for (k = 0; k < nb; k++)
                still &= i1[k].resident_binds == i0[k].resident_binds + 1 &&
                         i1[k].staged_binds == i0[k].staged_binds;
            CHECK(still, "%s %s: the second resident run moved pages (a %llu/%llu, deposits "
                  "%llu/%llu binds resident/staged after it; \"%s\")", DSI[op],
                  cft_format_name((cft_format)fmt), (unsigned long long)i1[0].resident_binds,
                  (unsigned long long)i1[0].staged_binds,
                  (unsigned long long)i1[1].resident_binds,
                  (unsigned long long)i1[1].staged_binds, i1[1].staged_why);
        }
        CHECK(cft_buffer_from_device(D.b) == CFT_OK && rb_info(&D).device_authority == 0,
              "%s %s resident: the read-back: %s", DSI[op], cft_format_name((cft_format)fmt),
              cft_last_error());
        memcpy(ds_dh, D.p, db);
        ds_runs_held(op, fmt, CFT_RNE, n, run ? "resident, the second run" : "resident", sh, ss,
                     msg, fh, fs, bh, bs);
    }
    printf("      %s %s resident: the deposits left on the device until read back, the "
           "second run bound %s with no page moved: %s\n", DSI[op],
           cft_format_name((cft_format)fmt), op ? "a and the deposits" : "a, b and the deposits",
           still ? "held" : "NOT held");
out:
    cft_program_free(ph);
    cft_program_free(ps);
    rb_free(&A);
    rb_free(&B);
    rb_free(&D);
}

/* A failed run's resident deposits (a plant build's fail-launch): LOST,
 * refused on reading back, its inputs not lost. */
static void ds_lost(const char *artifact, int fmt)
{
    const cft_divfull_entry *e = ds_entry(0, fmt);
    const size_t esz = cft_format_size((cft_format)fmt), n = 64, ib = n * esz, db = 2 * n * esz;
    const size_t bb = ds_bank(0, fmt, CFT_RNE);
    const char *was = getenv("CFT_HIP_PLANT");
    char keep[64] = "";
    cft_device *h = NULL;
    struct rb A, B, D;
    cft_program *p = NULL;
    cft_status st;
    uint32_t fl = 0;
    A.b = B.b = D.b = NULL;
    if (was)
        snprintf(keep, sizeof keep, "%s", was);
    put_env("CFT_HIP_PLANT", "fail-launch");
    st = cft_open(artifact, 0, &h);
    put_env("CFT_HIP_PLANT", keep[0] ? keep : NULL);
    CHECK(st == CFT_OK, "open with fail-launch: %s", cft_last_error());
    if (h && cft_program_load(h, e->image, e->image_bytes, &p) == CFT_OK &&
        rb_alloc(h, &A, ib) && rb_alloc(h, &B, ib) && rb_alloc(h, &D, db)) {
        CHECK(rb_put(&A, ds_xa, ib) && rb_put(&B, ds_xb, ib), "publishing: %s",
              cft_last_error());
        st = cft_program_run_bank(p, ds_bk, bb, A.p, B.p, NULL, D.p, ds_ch, n, &fl, NULL);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "fail-launch"),
              "the failed run: %s, \"%s\"", cft_strerror(st), cft_last_error());
        printf("    a failed run of the whole divide: %s - %s\n", cft_strerror(st),
               cft_last_error());
        CHECK(!strncmp(rb_info(&D).staged_why, "LOST:", 5) && rb_info(&D).device_authority == 0 &&
              strncmp(rb_info(&A).staged_why, "LOST:", 5),
              "after the failed run: the deposits' why \"%s\", a's \"%s\"", rb_info(&D).staged_why,
              rb_info(&A).staged_why);
        printf("    its deposits: %s\n", rb_info(&D).staged_why);
        st = cft_buffer_from_device(D.b);
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), "failed on the device"),
              "reading LOST deposits back: %s, \"%s\"", cft_strerror(st), cft_last_error());
    } else if (h) {
        CHECK(0, "the fail-launch handle: %s", cft_last_error());
    }
    cft_program_free(p);
    rb_free(&A);
    rb_free(&B);
    rb_free(&D);
    cft_close(h);
}

/* cft_div (op 0) or cft_sqrt (op 1) */
static cft_status ds_call(cft_device *d, int op, int fmt, int rnd, const void *a,
                          const void *b, void *out, size_t n, uint32_t *fl)
{
    return op ? cft_sqrt(d, (cft_format)fmt, (cft_round)rnd, a, out, n, fl, NULL)
              : cft_div(d, (cft_format)fmt, (cft_round)rnd, a, b, out, n, fl, NULL);
}

/* the route a device handle's call takes: 0 the chunk route
 * (CFT_DIVSQRT_SEQ=0), 1 the program route (both unset: the default), 2 the
 * whole operation (CFT_DIVSQRT_FULL=1); a software handle's is the chunk
 * route under all three */
static void ds_route(int r)
{
    put_env("CFT_DIVSQRT_SEQ", r == 0 ? "0" : NULL);
    put_env("CFT_DIVSQRT_FULL", r == 2 ? "1" : NULL);
}

/* the GPU's answer held to the software handle's: its status CFT_OK, then
 * every element and the flag word */
static void ds_api_held(int op, int fmt, int rnd, int route, size_t n, const char *what,
                        cft_status sh, const char *msg, const unsigned char *gh,
                        const unsigned char *gs, uint32_t fh, uint32_t fs)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    char x1[70], x2[70];
    size_t i = 0;
    if (sh != CFT_OK) {
        CHECK(0, "%s %s %s, %s, n=%lu %s: GPU %s (%s)", DSN[op],
              cft_format_name((cft_format)fmt), RND[rnd], DSR[route], (unsigned long)n, what,
              cft_strerror(sh), msg);
        return;
    }
    while (i < n && same(gh + i * esz, gs + i * esz, esz))
        i++;
    if (i == n && fh == fs) {
        checks++;
        return;
    }
    if (i == n)
        i = 0;                          /* the flags alone differ */
    hex(x1, gh + i * esz, esz);
    hex(x2, gs + i * esz, esz);
    CHECK(0, "%s %s %s, %s, n=%lu %s: element %lu: GPU %s flags 0x%02x, software %s "
          "flags 0x%02x", DSN[op], cft_format_name((cft_format)fmt), RND[rnd], DSR[route],
          (unsigned long)n, what, (unsigned long)i, x1, (unsigned)fh, x2, (unsigned)fs);
}

/* the divide's n = 1 cases, as pool indices: every pair of +0, +inf, qNaN,
 * sNaN, 1, 3, the smallest normal's odd neighbour and the largest finite,
 * then the largest over 0.5 (overflow), the smallest subnormal over 2 (a
 * tie), a negative subnormal over 3 and (1 + u) over -1 */
static void ds_case(int c, int *pa, int *pb)
{
    static const unsigned char S[8] = {2, 4, 6, 7, 0, 1, 18, 19};
    static const unsigned char X[4][2] = {{19, 13}, {14, 12}, {16, 1}, {11, 10}};
    if (c < 64) {
        *pa = S[c / 8];
        *pb = S[c % 8];
    } else {
        *pa = X[c - 64][0];
        *pb = X[c - 64][1];
    }
}

/* refused alike on both handles: CFT_ERR_INVALID_ARGUMENT (`any` 0), or any
 * equal refusal (`any` 1: a format, whose status is the build's) */
static void ds_refused(cft_device *hw, cft_device *sw, int op, int fmt, int rnd, const void *a,
                       const void *b, void *d, int any, int route, const char *what)
{
    uint32_t fh = 0, fs = 0;
    const cft_status sh = ds_call(hw, op, fmt, rnd, a, b, d, 1, &fh);
    const cft_status ss = ds_call(sw, op, fmt, rnd, a, b, d, 1, &fs);
    CHECK(sh == ss && (any ? sh != CFT_OK : sh == CFT_ERR_INVALID_ARGUMENT),
          "%s, %s, %s: GPU %s, software %s", DSN[op], DSR[route], what, cft_strerror(sh),
          cft_strerror(ss));
}

/* (c) cft_div and cft_sqrt through the API at fmt, each route forced, held
 * to the software handle's default route: n = 1 a case (the flags of one
 * element), every pair (577) and 5,000 in one call, d over a and over b,
 * and at rne n = 0, NULLs, bad formats and a bad attribute */
static void ds_api(cft_device *hw, cft_device *sw, int fmt)
{
    static const size_t NB[2] = {DS_ALL, DS_BIG};
    const size_t esz = cft_format_size((cft_format)fmt);
    const int checks0 = checks, before = failures;
    char msg[400], what[80];
    int rnd, route, op, c, k, pa, pb;
    uint32_t fh;
    cft_status sh, ss;
    for (rnd = 0; rnd < 5; rnd++) {
        /* the software handle's answers, its route the default (the chunk
         * route: it has no device to route to) */
        ds_route(1);
        for (c = 0; c < DS_NDIV1 + DS_P; c++) {
            op = c >= DS_NDIV1;
            if (!op)
                ds_case(c, &pa, &pb);
            else
                pa = pb = c - DS_NDIV1;
            k = op ? c - DS_NDIV1 : c;
            ds_r1f[op][k] = 0x5A5Au;
            ss = ds_call(sw, op, fmt, rnd, ds_pl + (size_t)pa * esz, ds_pl + (size_t)pb * esz,
                         ds_r1[op] + (size_t)k * esz, 1, &ds_r1f[op][k]);
            CHECK(ss == CFT_OK, "the software handle's %s: %s", DSN[op], cft_last_error());
        }
        for (op = 0; op < 2; op++)
            for (k = 0; k < 2; k++) {
                ds_rbf[op][k] = 0x5A5Au;
                ss = ds_call(sw, op, fmt, rnd, op ? ds_xb : ds_xa, ds_xb, ds_rb[op][k], NB[k],
                             &ds_rbf[op][k]);
                CHECK(ss == CFT_OK, "the software handle's %s n=%lu: %s", DSN[op],
                      (unsigned long)NB[k], cft_last_error());
            }
        for (route = 0; route < 3; route++) {
            ds_route(route);
            /* n = 1, a case a call: the flags of exactly one element */
            for (c = 0; c < DS_NDIV1 + DS_P; c++) {
                op = c >= DS_NDIV1;
                if (!op)
                    ds_case(c, &pa, &pb);
                else
                    pa = pb = c - DS_NDIV1;
                k = op ? c - DS_NDIV1 : c;
                memset(ds_g, 0x3C, esz);
                fh = 0xA5A5u;
                sh = ds_call(hw, op, fmt, rnd, ds_pl + (size_t)pa * esz,
                             ds_pl + (size_t)pb * esz, ds_g, 1, &fh);
                snprintf(msg, sizeof msg, "%s", cft_last_error());
                if (op)
                    snprintf(what, sizeof what, "(pool %d)", pa);
                else
                    snprintf(what, sizeof what, "(pool %d / pool %d)", pa, pb);
                ds_api_held(op, fmt, rnd, route, 1, what, sh, msg, ds_g,
                            ds_r1[op] + (size_t)k * esz, fh, ds_r1f[op][k]);
            }
            /* every pair, and 5,000 (crossing divsqrt.c's 4,096 chunk) */
            for (op = 0; op < 2; op++)
                for (k = 0; k < 2; k++) {
                    memset(ds_g, 0x3C, NB[k] * esz);
                    fh = 0xA5A5u;
                    sh = ds_call(hw, op, fmt, rnd, op ? ds_xb : ds_xa, ds_xb, ds_g, NB[k], &fh);
                    snprintf(msg, sizeof msg, "%s", cft_last_error());
                    ds_api_held(op, fmt, rnd, route, NB[k], "in one call", sh, msg, ds_g,
                                ds_rb[op][k], fh, ds_rbf[op][k]);
                }
            /* d over a and over b, held to the unaliased answers */
            memcpy(ds_t, ds_xa, DS_ALL * esz);
            fh = 0xA5A5u;
            sh = cft_div(hw, (cft_format)fmt, (cft_round)rnd, ds_t, ds_xb, ds_t, DS_ALL, &fh, NULL);
            snprintf(msg, sizeof msg, "%s", cft_last_error());
            ds_api_held(0, fmt, rnd, route, DS_ALL, "d over a", sh, msg, ds_t, ds_rb[0][0], fh,
                        ds_rbf[0][0]);
            memcpy(ds_t, ds_xb, DS_ALL * esz);
            fh = 0xA5A5u;
            sh = cft_div(hw, (cft_format)fmt, (cft_round)rnd, ds_xa, ds_t, ds_t, DS_ALL, &fh, NULL);
            snprintf(msg, sizeof msg, "%s", cft_last_error());
            ds_api_held(0, fmt, rnd, route, DS_ALL, "d over b", sh, msg, ds_t, ds_rb[0][0], fh,
                        ds_rbf[0][0]);
            memcpy(ds_t, ds_xb, DS_ALL * esz);
            fh = 0xA5A5u;
            sh = cft_sqrt(hw, (cft_format)fmt, (cft_round)rnd, ds_t, ds_t, DS_ALL, &fh, NULL);
            snprintf(msg, sizeof msg, "%s", cft_last_error());
            ds_api_held(1, fmt, rnd, route, DS_ALL, "d over a", sh, msg, ds_t, ds_rb[1][0], fh,
                        ds_rbf[1][0]);
            if (rnd == 0)
                for (op = 0; op < 2; op++) {
                    fh = 0xDEADu;
                    sh = ds_call(hw, op, fmt, rnd, ds_xa, ds_xb, ds_g, 0, &fh);
                    CHECK(sh == CFT_OK && fh == 0, "%s %s, %s, n = 0: %s with flags 0x%x - "
                          "CFT_OK with the flag word cleared wanted", DSN[op],
                          cft_format_name((cft_format)fmt), DSR[route], cft_strerror(sh),
                          (unsigned)fh);
                    ds_refused(hw, sw, op, fmt, 0, NULL, ds_xb, ds_g, 0, route, "a NULL");
                    if (!op)
                        ds_refused(hw, sw, op, fmt, 0, ds_xa, NULL, ds_g, 0, route, "b NULL");
                    ds_refused(hw, sw, op, fmt, 0, ds_xa, ds_xb, NULL, 0, route, "d NULL");
                    ds_refused(hw, sw, op, fmt, 5, ds_xa, ds_xb, ds_g, 0, route, "attribute 5");
                    ds_refused(hw, sw, op, -1, 0, ds_xa, ds_xb, ds_g, 1, route, "format -1");
                    ds_refused(hw, sw, op, 4, 0, ds_xa, ds_xb, ds_g, 1, route, "format 4");
                    ds_refused(hw, sw, op, 99, 0, ds_xa, ds_xb, ds_g, 1, route, "format 99");
                    CHECK(ds_call(NULL, op, fmt, 0, ds_xa, ds_xb, ds_g, 1, &fh) ==
                          CFT_ERR_INVALID_ARGUMENT, "%s: a NULL device was not refused", DSN[op]);
                }
        }
    }
    ds_route(1);
    printf("    %s through the API, each route forced: %d cases a route and attribute at n = "
           "1, every pair and 5,000 in one call, d over a and b, n = 0, NULLs and bad "
           "arguments: %d checks, %d failed\n", cft_format_name((cft_format)fmt),
           DS_NDIV1 + DS_P, checks - checks0, failures - before);
}

/* (c) The route proof (a plant build): before each call a marker program
 * (DEPOSIT r0; HALT - its head, 256 bytes, is no route's), then the call
 * with its route forced, then the probe of the last program run. Its head
 * says which route ran: the marker's (no program: the chunk route), the
 * program route's (2,304 for the divide, 3,072 for the root: sq_emit's six
 * or nine constants), or the whole image's (its instructions and its
 * n_consts constants of 260 bytes, the GPU's cft_bn). A refused image falls
 * through to the program route and gives the same bits, so this is the one
 * check here that can tell. */
static void ds_proof(cft_device *hw, int fmt, int (*probe)(uint64_t *, int))
{
    unsigned char img[32 + 2 * 8], dep[8 * 32];
    uint64_t ins[2], v[16];
    cft_program *pm = NULL;
    uint32_t fl;
    cft_status st;
    int op, route;
    ins[0] = sq_ctrl(3, 0, 0);
    ins[1] = sq_ctrl(0, 0, 0);
    if (cft_program_load(hw, img, sq_image(img, fmt, ins, 2, NULL, 0, 1, 0, 0, 0), &pm) !=
        CFT_OK) {
        CHECK(0, "the marker program at %s: %s", cft_format_name((cft_format)fmt),
              cft_last_error());
        return;
    }
    for (op = 0; op < 2; op++)
        for (route = 0; route < 3; route++) {
            const cft_divfull_entry *e = ds_entry(op, fmt);
            const uint64_t ni = (uint64_t)e->image[8] | ((uint64_t)e->image[9] << 8);
            const uint64_t whole = (((((ni * 8 + 255) & ~(uint64_t)255) +
                                      (uint64_t)e->n_consts * 260u) + 255) & ~(uint64_t)255);
            const uint64_t want = route == 0 ? 256u : route == 1 ? (op ? 3072u : 2304u) : whole;
            const char *ran;
            memset(v, 0, sizeof v);
            st = cft_program_run(pm, ds_xa, NULL, NULL, dep, NULL, 8, NULL, NULL);
            (void)probe(v, 16);
            CHECK(st == CFT_OK && v[6] == 256u && v[0] == 8u, "the marker program at %s: %s, "
                  "the probe's head %llu and n %llu - 256 and 8 wanted",
                  cft_format_name((cft_format)fmt), cft_strerror(st),
                  (unsigned long long)v[6], (unsigned long long)v[0]);
            ds_route(route);
            fl = 0;
            st = ds_call(hw, op, fmt, CFT_RNE, ds_xa, ds_xb, ds_g, 300, &fl);
            ds_route(1);
            memset(v, 0, sizeof v);
            (void)probe(v, 16);
            ran = v[6] == 256u ? "no program after the marker (the chunk route)"
                : v[6] == (op ? 3072u : 2304u) ? "the program route's"
                : v[6] == whole ? "the whole image's" : "NO route's";
            CHECK(st == CFT_OK && v[6] == want && v[2] == 0 && v[3] == 0,
                  "the route proof: %s %s, %s forced: %s, the probe's head %llu (%s) - %llu "
                  "wanted; reach %llu, lane pool %llu", DSN[op], cft_format_name((cft_format)fmt),
                  DSR[route], cft_strerror(st), (unsigned long long)v[6], ran,
                  (unsigned long long)want, (unsigned long long)v[2], (unsigned long long)v[3]);
            printf("    route proof, %s %s, %s forced: head %llu - %s; n %llu, reach %llu, "
                   "lane pool %llu, launches %llu\n", DSN[op], cft_format_name((cft_format)fmt),
                   DSR[route], (unsigned long long)v[6], ran, (unsigned long long)v[0],
                   (unsigned long long)v[2], (unsigned long long)v[3],
                   (unsigned long long)v[11]);
        }
    cft_program_free(pm);
}

static void leg_divsqrt(const char *artifact, cft_device *hw, cft_device *sw, int only_fmt)
{
    int (*probe)(uint64_t *, int) = DS_PROBE_FN;
    const char *vs = getenv("CFT_DIVSQRT_SEQ"), *vf = getenv("CFT_DIVSQRT_FULL");
    const char *was = getenv("CFT_HIP_PLANT"), *ch = getenv("CFT_HIP_CHUNK");
    const int had_s = vs != NULL, had_f = vf != NULL;
    const int before = failures, checks0 = checks;
    char ks[32] = "", kf[32] = "", keep[64] = "";
    cft_device *h = NULL;
    clock_t t0 = clock();
    int f, op, plant_build;

    printf("divsqrt\n");
    /* the caller's route settings, put back at the end; the plant this
     * process was started with stays set for any handle opened here */
    if (vs)
        snprintf(ks, sizeof ks, "%s", vs);
    if (vf)
        snprintf(kf, sizeof kf, "%s", vf);
    if (was)
        snprintf(keep, sizeof keep, "%s", was);
    put_env("CFT_HIP_PLANT", "bogus");
    plant_build = cft_open(artifact, 0, &h) != CFT_OK;
    put_env("CFT_HIP_PLANT", keep[0] ? keep : NULL);
    cft_close(h);
    h = NULL;
    CHECK(plant_build == (probe != NULL), "a %s build %s the plant build's probe",
          plant_build ? "plant" : "default", probe ? "has" : "lacks");
    printf("  a %s build; the route proof's probe %s; CFT_HIP_PLANT %s; CFT_HIP_CHUNK %s\n",
           plant_build ? "plant" : "default", probe ? "present" : "absent",
           keep[0] ? keep : "unset", ch && *ch ? ch : "unset");
    for (f = 0; f < 4; f++) {
        if (only_fmt >= 0 && f != only_fmt)
            continue;
        ds_lanes(f);
        printf("  %s\n", cft_format_name((cft_format)f));
        for (op = 0; op < 2; op++) {
            ds_direct(hw, sw, op, f, probe);
            if (f == CFT_FP64 || f == CFT_FP256)
                ds_resident(hw, sw, op, f);
        }
        ds_api(hw, sw, f);
        if (probe)
            ds_proof(hw, f, probe);
    }
    if (!probe)
        nrun("  the route proof", "this libcft is a default build, which defines no "
             "cfth_plant_prog_probe (the plant build's probe of the last program run); build "
             "with HIP_PLANTS=1 - the bits above hold every route, but a refused image falls "
             "through to the same bits, so only the probe says which route ran");
    if (!plant_build) {
        nrun("  a failed run's deposits LOST", "this libcft is a default build, which has no "
             "CFT_HIP_PLANT=fail-launch; build with HIP_PLANTS=1");
    } else {
        f = only_fmt >= 0 ? only_fmt : CFT_FP64;
        ds_lanes(f);
        ds_lost(artifact, f);
    }
    put_env("CFT_DIVSQRT_SEQ", had_s ? ks : NULL);
    put_env("CFT_DIVSQRT_FULL", had_f ? kf : NULL);
    printf("  divsqrt: %d checks, %s, %.1f s, %d failed\n", checks - checks0,
           only_fmt >= 0 ? cft_format_name((cft_format)only_fmt) : "every format",
           (double)(clock() - t0) / CLOCKS_PER_SEC, failures - before);
}

/* round 3's G3A: its leg functions here */

/* ---- the fixed tier (round 3's G3A) ----------------------------------------- */

/* The plant build's route instrument (backend_hip.cpp's cfth_plant_tier_probe):
 * the kernel the last cft_run's branch chose (0 k_run, 1 k_run256, and since
 * round 3's G3A2 2 k_run128), its op, format and n, its handle's tier, and
 * that handle's launches of each kernel (eight values since G3A2).
 * Weak, as cfth_plant_prog_probe is: NULL in a default build. */
#if defined(__GNUC__) && !defined(_WIN32)
extern int cfth_plant_tier_probe(uint64_t *out, int nout) __attribute__((weak));
#define FX_PROBE_FN cfth_plant_tier_probe
#else
#define FX_PROBE_FN NULL
#endif

enum { FX_P = 24, FX_N = FX_P * FX_P * FX_P, FX_BIG = 5000, FX_FORM = 300 };
static const char *const FXN[4] = {"FMA", "ADD", "SUB", "MUL"};
static unsigned char fx_pl[FX_P * 32], fx_a[FX_N * 32], fx_b[FX_N * 32], fx_c[FX_N * 32],
    fx_dh[FX_N * 32], fx_ds[FX_N * 32];
static int (*fx_probe)(uint64_t *, int);
static long fx_routes;
/* round 3's G3A2: the leg's failures counted by the format of the part that
 * failed (fp32 to fp256; [4] the rest: the grammar, the build's own check) */
static int fx_failed[5];
#define FX_AT(fmt_, call_)                                                \
    do {                                                                  \
        const int f0_ = failures;                                         \
        call_;                                                            \
        fx_failed[(fmt_)] += failures - f0_;                              \
    } while (0)

static double fx_now(void)
{
#ifdef _WIN32
    return (double)clock() / CLOCKS_PER_SEC;
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
#endif
}

/* an element whose trailing field has its one bit `bit` set */
static void fx_bit(unsigned char *e, int fmt, int sign, unsigned long exp, int bit)
{
    elem(e, fmt, sign, exp, 0);
    e[bit / 8] |= (unsigned char)(1u << (bit % 8));
}

/* The leg's pool at one format: every class the FMA's rules part - signed
 * zeros, the smallest subnormal, the smallest normal, 1 and -1, 1 + u, 0.5,
 * the largest finite and half its ulp, +infinity, a quiet NaN and a negative
 * signalling one (payloads), T1 = 1 + 2^-k1 and T2 = 1 + 2^-k2 with k1 + k2 =
 * p (T1*T2 ends at half an ulp of 1, an exact tie; T1 + u/2 another), u/2:
 * the first 16, the per-case pool - then the largest subnormal, the largest
 * value below 1, 2, the largest finite negated, -infinity, -u/2 and two
 * random finite values. With them come the overflow threshold (the largest
 * finite plus half its ulp, and times 1 + u), underflow (the smallest
 * subnormal times 0.5, a tie), exact cancellation (1*1 - 1) and subnormal
 * results (the smallest normal times 0.5). */
static void fx_pool(unsigned char *p, int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const int mw = (int)esz * 8 - 1 - EXPW[fmt], k1 = (mw + 1) / 2, k2 = mw + 1 - k1;
    const unsigned long bias = (1ul << (EXPW[fmt] - 1)) - 1, top = (1ul << EXPW[fmt]) - 1;
    const struct { int s; unsigned long x; int m; } v[FX_P] = {
        {0, 0, 0}, {1, 0, 0}, {0, 0, 1}, {0, 1, 0},           /* +0 -0 minsub minnorm */
        {0, bias, 0}, {1, bias, 0}, {0, bias, 1}, {0, bias - 1, 0},   /* 1 -1 1+u 0.5 */
        {0, top - 1, 2}, {0, top - 2 - (unsigned long)mw, 0},   /* max, half its ulp */
        {0, top, 0}, {0, top, 5}, {1, top, 6},                /* +inf qNaN -sNaN */
        {0, bias, 9}, {0, bias, 10},                          /* T1 T2, below */
        {0, bias - (unsigned long)mw - 1, 0},                 /* u/2 */
        {0, 0, 2}, {0, bias - 1, 2}, {0, bias + 1, 0},        /* maxsub, below 1, 2 */
        {1, top - 1, 2}, {1, top, 0}, {1, bias - (unsigned long)mw - 1, 0},
        {0, bias - 3, 4}, {1, bias + 5, 4}};
    int i;
    for (i = 0; i < FX_P; i++) {
        unsigned char *e = p + (size_t)i * esz;
        if (v[i].m == 9)
            fx_bit(e, fmt, 0, bias, mw - k1);
        else if (v[i].m == 10)
            fx_bit(e, fmt, 0, bias, mw - k2);
        else
            aug_put(e, fmt, v[i].s, v[i].x, v[i].m);
    }
}

/* round 3's G3A2: the kernel the route must name, written here and NOT the
 * library's fixed_covers (a route claim held by the code it checks could not
 * fail): on a fixed handle, 2 (k_run128) for fp128's FMA, ADD, SUB and MUL,
 * 1 (k_run256) for fp256's; 0 (k_run) for every other call and on any
 * generic handle. */
static int fx_want(int fixed, int op, int fmt)
{
    if (!fixed || op < 0 || op > 3)
        return 0;
    return fmt == CFT_FP128 ? 2 : fmt == CFT_FP256 ? 1 : 0;
}

/* The route (a plant build's probe): the last cft_run's branch chose the
 * kernel `want` names (fx_want's 0, 1 or 2), for this op, format and n. */
static void fx_route(int want, int op, int fmt, size_t n, const char *who)
{
    static const char *const KN[3] = {"generic (k_run)", "fixed fp256 (k_run256)",
                                      "fixed fp128 (k_run128)"};
    uint64_t v[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    if (!fx_probe)
        return;
    fx_routes++;
    CHECK(fx_probe(v, 8) == 8 && v[0] == (uint64_t)want && v[1] == (uint64_t)op &&
          v[2] == (uint64_t)fmt && v[3] == (uint64_t)n,
          "the route: %s %s %s n=%lu - the probe says kernel %llu (opcode %llu, format "
          "%llu, n %llu, tier %llu), the %s kernel wanted", who,
          cft_format_name((cft_format)fmt), op < 4 ? FXN[op] : "op", (unsigned long)n,
          (unsigned long long)v[0], (unsigned long long)v[1], (unsigned long long)v[2],
          (unsigned long long)v[3], (unsigned long long)v[4], KN[want]);
}

/* one cft_run on h and on sw, held: the same status, and if CFT_OK the same
 * bits element by element and the same flag word; the route checked */
static void fx_held(cft_device *h, cft_device *sw, int fixed, int op, int fmt, int rnd,
                    const unsigned char *a, const unsigned char *b, const unsigned char *c,
                    size_t n, const char *who)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    uint32_t fh = 0, fs = 0;
    cft_status sh, ss;
    char eh[200] = "";
    size_t i = 0;
    sh = cft_run(h, (cft_op)op, (cft_format)fmt, (cft_round)rnd, a, b, c, fx_dh, n, &fh, NULL);
    if (sh != CFT_OK)
        snprintf(eh, sizeof eh, "%s", cft_last_error());
    ss = cft_run(sw, (cft_op)op, (cft_format)fmt, (cft_round)rnd, a, b, c, fx_ds, n, &fs, NULL);
    if (sh == CFT_OK && ss == CFT_OK)
        while (i < n && same(fx_dh + i * esz, fx_ds + i * esz, esz))
            i++;
    if (sh != ss || (sh == CFT_OK && (i < n || fh != fs))) {
        char x1[70] = "", x2[70] = "", x3[70] = "", x4[70] = "", x5[70] = "";
        if (sh == CFT_OK && ss == CFT_OK && (i < n || n == 1)) {
            const size_t j = i < n ? i : 0;   /* a flag alone differing at n = 1: the case */
            hex(x1, a + j * esz, esz);
            if (b) hex(x2, b + j * esz, esz);
            if (c) hex(x3, c + j * esz, esz);
            hex(x4, fx_dh + j * esz, esz);
            hex(x5, fx_ds + j * esz, esz);
        }
        CHECK(0, "%s %s %s %s n=%lu: GPU %s%s%s flags 0x%02x, software %s flags 0x%02x; "
              "first element differing %lu: a %s b %s c %s, GPU %s, software %s", who,
              cft_format_name((cft_format)fmt), op < 4 ? FXN[op] : cft_op_name((cft_op)op),
              RND[rnd % 5], (unsigned long)n, cft_strerror(sh), eh[0] ? " - " : "", eh,
              (unsigned)fh, cft_strerror(ss), (unsigned)fs, (unsigned long)i, x1, x2, x3,
              x4, x5);
    } else {
        checks++;
    }
    if (sh == CFT_OK && n)
        fx_route(fx_want(fixed, op, fmt), op, fmt, n, who);
}

/* every triple of the pool, in fx_a, fx_b and fx_c */
static void fx_triples(int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    size_t t;
    for (t = 0; t < (size_t)FX_N; t++) {
        memcpy(fx_a + t * esz, fx_pl + (t / (FX_P * FX_P)) * esz, esz);
        memcpy(fx_b + t * esz, fx_pl + ((t / FX_P) % FX_P) * esz, esz);
        memcpy(fx_c + t * esz, fx_pl + (t % FX_P) * esz, esz);
    }
}

/* (b): the class at one format on handle h - a call a case over the first
 * `core` of the pool (every triple at FMA, every pair at ADD, SUB and MUL),
 * then every triple of the whole pool in one call, then FX_BIG random
 * triples in one call, at every attribute and the four operations */
static void fx_class(cft_device *h, cft_device *sw, int fixed, int fmt, int core,
                     const char *who)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const int before = failures, c0 = checks;
    const double t0 = fx_now();
    long calls = 0;
    int rnd, op, i, j, k;
    size_t t;
    fx_pool(fx_pl, fmt);
    fx_triples(fmt);
    for (rnd = 0; rnd < 5; rnd++)
        for (op = 0; op < 4; op++) {
            for (i = 0; i < core; i++)
                for (j = 0; j < core; j++)
                    for (k = 0; k < (op == 0 ? core : 1); k++) {
                        const unsigned char *pa = fx_pl + (size_t)i * esz;
                        const unsigned char *pb = fx_pl + (size_t)(op == 3 ? j : k) * esz;
                        const unsigned char *pc = fx_pl + (size_t)(op == 3 ? k : j) * esz;
                        if (op == 0)
                            pc = fx_pl + (size_t)k * esz, pb = fx_pl + (size_t)j * esz;
                        fx_held(h, sw, fixed, op, fmt, rnd, pa, pb, pc, 1, who);
                        calls++;
                    }
            fx_held(h, sw, fixed, op, fmt, rnd, fx_a, fx_b, fx_c, FX_N, who);
            calls++;
        }
    /* FX_BIG random triples, one in four from the pool */
    for (op = 0; op < 3; op++) {
        unsigned char *x = op == 0 ? fx_a : op == 1 ? fx_b : fx_c;
        fill(x, FX_BIG, fmt, K_RANDOM);
        for (t = 0; t < (size_t)FX_BIG; t++)
            if (rnd64() % 4 == 0)
                memcpy(x + t * esz, fx_pl + (rnd64() % FX_P) * esz, esz);
    }
    for (rnd = 0; rnd < 5; rnd++)
        for (op = 0; op < 4; op++) {
            fx_held(h, sw, fixed, op, fmt, rnd, fx_a, fx_b, fx_c, FX_BIG, who);
            calls++;
        }
    printf("  (b) %s, %s: %ld calls (%d x %d per case, %d triples a call, %d random), "
           "%d checks, %.1f s, %d failed\n", who, cft_format_name((cft_format)fmt), calls,
           core, core, FX_N, FX_BIG, checks - c0, fx_now() - t0, failures - before);
}

/* (c): every other opcode cft_run takes at fmt (fp256, and since round 3's
 * G3A2 fp128), on the fixed handle: held to the software handle (it runs
 * k_run there), and those the software handle refuses refused alike */
static void fx_others(cft_device *hf, cft_device *sw, int fmt)
{
    const char *fn = cft_format_name((cft_format)fmt);
    const int before = failures, c0 = checks;
    int op, rnd, ran = 0, refused = 0;
    char first[600] = "";
    fx_pool(fx_pl, fmt);
    fx_triples(fmt);
    for (op = 4; op < 64; op++) {
        uint32_t fs = 0, fh = 0;
        const cft_status ss = cft_run(sw, (cft_op)op, (cft_format)fmt, CFT_RNE, fx_a, fx_b, fx_c,
                                      fx_ds, 64, &fs, NULL);
        if (ss != CFT_OK) {
            const cft_status sh = cft_run(hf, (cft_op)op, (cft_format)fmt, CFT_RNE, fx_a, fx_b,
                                          fx_c, fx_dh, 64, &fh, NULL);
            CHECK(sh == ss, "opcode %d at %s: the software handle %s, the fixed handle %s",
                  op, fn, cft_strerror(ss), cft_strerror(sh));
            refused++;
            continue;
        }
        ran++;
        for (rnd = 0; rnd < 5; rnd++) {
            uint32_t f1 = 0;
            const cft_status sh = cft_run(hf, (cft_op)op, (cft_format)fmt, (cft_round)rnd, fx_a,
                                          fx_b, fx_c, fx_dh, FX_N, &f1, NULL);
            if (sh != CFT_OK && !first[0])
                snprintf(first, sizeof first, "%s at %s: %s - %s", cft_op_name((cft_op)op), fn,
                         cft_strerror(sh), cft_last_error());
            fx_held(hf, sw, 1, op, fmt, rnd, fx_a, fx_b, fx_c, FX_N, "the fixed handle");
        }
    }
    if (first[0])
        printf("  (c) the fixed handle refused: %s\n", first);
    printf("  (c) the other opcodes at %s on the fixed handle: %d taken by cft_run, each "
           "at five attributes over %d triples; %d refused by both alike; %d checks, %d "
           "failed\n", fn, ran, FX_N, refused, checks - c0, failures - before);
}

/* (d): the forms of a call at fmt, on the fixed handle, against the software
 * handle (the static arrays hold FX_FORM elements of 32 bytes, so fp128's 16
 * fit too) */
static void fx_forms(cft_device *hf, cft_device *sw, int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt), n = FX_FORM;
    const int before = failures, c0 = checks;
    static unsigned char ia[FX_FORM * 32], ib[FX_FORM * 32], ic[FX_FORM * 32],
        dh[FX_FORM * 32], ds[FX_FORM * 32];
    int op, mask, rnd, r;
    size_t t;
    fx_pool(fx_pl, fmt);
    for (t = 0; t < n; t++) {
        memcpy(ia + t * esz, fx_pl + (rnd64() % FX_P) * esz, esz);
        memcpy(ib + t * esz, fx_pl + (rnd64() % FX_P) * esz, esz);
        memcpy(ic + t * esz, fx_pl + (rnd64() % FX_P) * esz, esz);
    }
    /* a scalar operand on each of a, b and c: all seven masks */
    for (op = 0; op < 4; op++)
        for (mask = 1; mask < 8; mask++)
            for (rnd = 0; rnd < 5; rnd += 4) {
                cft_elem_args E;
                uint32_t fh = 0, fs = 0;
                cft_status sh = CFT_OK, ss = CFT_OK;
                for (r = 0; r < 2; r++) {
                    memset(&E, 0, sizeof E);
                    E.struct_size = sizeof E;
                    E.a = ia;
                    E.b = ib;
                    E.c = ic;
                    E.d = r ? ds : dh;
                    E.n = n;
                    E.scalar_mask = (uint32_t)mask;
                    E.flags_out = r ? &fs : &fh;
                    if (r)
                        ss = cft_run_ex(sw, (cft_op)op, (cft_format)fmt, (cft_round)rnd, &E);
                    else
                        sh = cft_run_ex(hf, (cft_op)op, (cft_format)fmt, (cft_round)rnd, &E);
                }
                CHECK(sh == CFT_OK && ss == CFT_OK && same(dh, ds, n * esz) && fh == fs,
                      "cft_run_ex %s %s, scalar mask %d: GPU %s (%s), software %s; bits %s, "
                      "flags 0x%02x / 0x%02x", FXN[op], RND[rnd], mask, cft_strerror(sh),
                      sh ? cft_last_error() : "", cft_strerror(ss),
                      same(dh, ds, n * esz) ? "alike" : "DIFFER", (unsigned)fh, (unsigned)fs);
                if (sh == CFT_OK)
                    fx_route(fx_want(1, op, fmt), op, fmt, n, "a scalar operand");
            }
    /* NULL operands: a zero element (ADD and SUB with no b, MUL and FMA with no c) */
    for (op = 0; op < 4; op++)
        for (rnd = 0; rnd < 5; rnd++)
            fx_held(hf, sw, 1, op, fmt, rnd, ia, op == 1 || op == 2 ? NULL : ib,
                    op == 0 || op == 3 ? NULL : ic, n, "a NULL operand");
    /* d == a in place */
    for (op = 0; op < 4; op++) {
        uint32_t fh = 0, fs = 0;
        cft_status sh, ss;
        memcpy(dh, ia, n * esz);
        memcpy(ds, ia, n * esz);
        sh = cft_run(hf, (cft_op)op, (cft_format)fmt, CFT_RMM, dh, ib, ic, dh, n, &fh, NULL);
        if (sh == CFT_OK)
            fx_route(fx_want(1, op, fmt), op, fmt, n, "d == a in place");
        ss = cft_run(sw, (cft_op)op, (cft_format)fmt, CFT_RMM, ds, ib, ic, ds, n, &fs, NULL);
        CHECK(sh == CFT_OK && ss == CFT_OK && same(dh, ds, n * esz) && fh == fs,
              "%s with d == a in place: GPU %s, software %s, bits %s", FXN[op],
              cft_strerror(sh), cft_strerror(ss), same(dh, ds, n * esz) ? "alike" : "DIFFER");
    }
    /* n = 0, a bad format, a bad attribute and a bad opcode: as the software handle */
    {
        const struct { int op, fmt, rnd; size_t n; } q[] = {
            {0, fmt, 0, 0}, {1, 4, 0, 4}, {3, 99, 0, 4}, {0, -1, 0, 4},
            {2, fmt, 5, 4}, {200, fmt, 0, 4}, {-1, fmt, 0, 4}};
        size_t k;
        for (k = 0; k < sizeof q / sizeof q[0]; k++) {
            uint32_t fh = 0x55, fs = 0x55;
            const cft_status sh = cft_run(hf, (cft_op)q[k].op, (cft_format)q[k].fmt,
                                          (cft_round)q[k].rnd, ia, ib, ic, dh, q[k].n, &fh, NULL);
            const cft_status ss = cft_run(sw, (cft_op)q[k].op, (cft_format)q[k].fmt,
                                          (cft_round)q[k].rnd, ia, ib, ic, ds, q[k].n, &fs, NULL);
            CHECK(sh == ss && (sh != CFT_OK || fh == fs), "opcode %d, format %d, attribute "
                  "%d, n %lu: GPU %s, software %s", q[k].op, q[k].fmt, q[k].rnd,
                  (unsigned long)q[k].n, cft_strerror(sh), cft_strerror(ss));
        }
    }
    printf("  (d) the forms of a call at %s on the fixed handle: seven scalar masks at the "
           "four operations (rne, rmm), NULL b and c, d == a in place, n = 0 and four "
           "refusals; %d checks, %d failed\n", cft_format_name((cft_format)fmt), checks - c0,
           failures - before);
}

/* (e): a, b, c and d resident on the fixed handle, at fmt (fp256, and since
 * round 3's G3A2 fp128; the static arrays hold 2000 elements of 32 bytes) */
static void fx_resident(const char *artifact, cft_device *hf, cft_device *sw, int plant_build,
                        int fmt)
{
    const size_t esz = cft_format_size((cft_format)fmt), n = 2000, bytes = n * esz;
    const int before = failures, c0 = checks;
    static unsigned char x[2000 * 32], y[2000 * 32], z[2000 * 32], want[2001 * 32];
    struct rb A, B, C, D;
    struct rb *all[4];
    cft_buffer_info i0[4], i1[4];
    uint32_t fh = 0, fs = 0;
    int op, k, still = 1;
    size_t t;
    A.b = B.b = C.b = D.b = NULL;
    all[0] = &A; all[1] = &B; all[2] = &C; all[3] = &D;
    fx_pool(fx_pl, fmt);
    fill(x, n, fmt, K_RANDOM);
    fill(y, n, fmt, K_RANDOM);
    fill(z, n, fmt, K_RANDOM);
    for (t = 0; t < n; t += 3)
        memcpy(z + t * esz, fx_pl + (rnd64() % FX_P) * esz, esz);
    CHECK(rb_alloc(hf, &A, bytes) && rb_alloc(hf, &B, bytes) && rb_alloc(hf, &C, bytes) &&
          rb_alloc(hf, &D, bytes), "cft_alloc: %s", cft_last_error());
    if (!A.b || !B.b || !C.b || !D.b)
        goto out;
    CHECK(rb_put(&A, x, bytes) && rb_put(&B, y, bytes) && rb_put(&C, z, bytes),
          "publishing: %s", cft_last_error());
    for (op = 0; op < 4; op++) {
        cft_status sh;
        sh = cft_run(hf, (cft_op)op, (cft_format)fmt, CFT_RNE, A.p, B.p, C.p, D.p, n, &fh, NULL);
        if (sh == CFT_OK)
            fx_route(fx_want(1, op, fmt), op, fmt, n, "resident");
        CHECK(sh == CFT_OK && rb_info(&D).device_authority == 1, "%s resident: %s, d's "
              "authority %d", FXN[op], cft_strerror(sh), rb_info(&D).device_authority);
        CHECK(cft_buffer_from_device(D.b) == CFT_OK, "the read-back: %s", cft_last_error());
        CHECK(cft_run(sw, (cft_op)op, (cft_format)fmt, CFT_RNE, x, y, z, want, n, &fs, NULL) ==
              CFT_OK && same(D.p, want, bytes) && fh == fs, "%s resident: bits %s, flags "
              "0x%02x / 0x%02x", FXN[op], same(D.p, want, bytes) ? "alike" : "DIFFER",
              (unsigned)fh, (unsigned)fs);
        for (k = 0; k < 4; k++)
            i0[k] = rb_info(all[k]);
        sh = cft_run(hf, (cft_op)op, (cft_format)fmt, CFT_RNE, A.p, B.p, C.p, D.p, n, &fh, NULL);
        for (k = 0; k < 4; k++)
            i1[k] = rb_info(all[k]);
        for (k = 0; k < 4; k++)
            still &= i1[k].resident_binds == i0[k].resident_binds + 1 &&
                     i1[k].staged_binds == i0[k].staged_binds;
        CHECK(sh == CFT_OK && still, "%s: the second resident call moved pages (d %llu/%llu "
              "binds resident/staged; \"%s\")", FXN[op],
              (unsigned long long)i1[3].resident_binds, (unsigned long long)i1[3].staged_binds,
              i1[3].staged_why);
        CHECK(cft_buffer_from_device(D.b) == CFT_OK && same(D.p, want, bytes) && fh == fs,
              "%s resident, the second call: bits %s", FXN[op],
              same(D.p, want, bytes) ? "alike" : "DIFFER");
    }
    rb_free(&A);
    /* an output shifted one element over its own input: staged, the snapshot rule */
    CHECK(rb_alloc(hf, &A, bytes + esz), "cft_alloc: %s", cft_last_error());
    if (A.b) {
        cft_buffer_info ia;
        memcpy(want, x, esz);
        CHECK(cft_run(sw, CFT_FMA, (cft_format)fmt, CFT_RNE, x, y, z, want + esz, n, &fs, NULL) ==
              CFT_OK, "software");
        memcpy(A.p, x, bytes);
        CHECK(cft_buffer_to_device(A.b) == CFT_OK && cft_run(hf, CFT_FMA, (cft_format)fmt, CFT_RNE,
              A.p, y, z, A.p + esz, n, &fh, NULL) == CFT_OK &&
              cft_buffer_from_device(A.b) == CFT_OK, "the shifted run: %s", cft_last_error());
        fx_route(fx_want(1, 0, fmt), 0, fmt, n, "an output shifted over its input");
        ia = rb_info(&A);
        CHECK(same(A.p, want, bytes + esz) && fh == fs && strstr(ia.staged_why, "overlaps an output"),
              "an output shifted over its input: %s, \"%s\"",
              same(A.p, want, bytes + esz) ? "the snapshot rule" : "NOT the snapshot rule",
              ia.staged_why);
    }
    printf("  (e) resident a, b, c and d at %s on the fixed handle, the four operations: "
           "the software handle's bits, d left on the device, the second call moving no "
           "page%s; an output shifted over its input staged by the snapshot rule\n",
           cft_format_name((cft_format)fmt), still ? "" : " - NOT HELD");
    if (!plant_build) {
        nrun("  (e) a failed run's resident outputs LOST", "this libcft is a default build, "
             "which has no CFT_HIP_PLANT=fail-launch; build with HIP_PLANTS=1");
    } else {
        cft_device *h = NULL;
        cft_status st;
        rb_free(&A); rb_free(&B); rb_free(&C); rb_free(&D);
        put_env("CFT_HIP_PLANT", "fail-launch");
        put_env("CFT_HIP_TIER", "fixed");
        st = cft_open(artifact, 0, &h);
        put_env("CFT_HIP_PLANT", NULL);
        put_env("CFT_HIP_TIER", NULL);
        CHECK(st == CFT_OK, "open with fail-launch under the fixed tier: %s", cft_last_error());
        if (h && rb_alloc(h, &A, bytes) && rb_alloc(h, &B, bytes) && rb_alloc(h, &C, bytes) &&
            rb_alloc(h, &D, bytes)) {
            cft_buffer_info id;
            CHECK(rb_put(&A, x, bytes) && rb_put(&B, y, bytes) && rb_put(&C, z, bytes),
                  "publishing");
            char msg[300];
            st = cft_run(h, CFT_FMA, (cft_format)fmt, CFT_RNE, A.p, B.p, C.p, D.p, n, &fh, NULL);
            snprintf(msg, sizeof msg, "%s", cft_last_error());
            fx_route(fx_want(1, 0, fmt), 0, fmt, n, "the failed run");
            id = rb_info(&D);
            CHECK(st == CFT_ERR_INTERNAL && strstr(msg, "fail-launch") &&
                  !strncmp(id.staged_why, "LOST:", 5),
                  "the failed resident run under the fixed tier: %s, \"%s\"; d's why \"%s\"",
                  cft_strerror(st), msg, id.staged_why);
            printf("  (e) a failed run at %s under the fixed tier: %s; d %s\n",
                   cft_format_name((cft_format)fmt), cft_strerror(st), id.staged_why);
        }
        rb_free(&A); rb_free(&B); rb_free(&C); rb_free(&D);
        cft_close(h);
    }
out:
    rb_free(&A); rb_free(&B); rb_free(&C); rb_free(&D);
    printf("  (e) %s: %d checks, %d failed\n", cft_format_name((cft_format)fmt), checks - c0,
           failures - before);
}

static void leg_fixed(const char *artifact, cft_device *sw, int only_fmt)
{
    static const char *const ok[3] = {"", "generic", "fixed"};
    static const char *const bad[7] = {"Fixed", "FIXED", " fixed", "fixed ", "1", "both", "gen"};
    const char *was = getenv("CFT_HIP_TIER"), *wp = getenv("CFT_HIP_PLANT");
    char keep[64] = "", keepp[64] = "";
    const int before = failures, c0 = checks;
    const double t0 = fx_now();
    cft_device *hg = NULL, *hf = NULL, *h = NULL;
    int k, f, plant_build;
    printf("fixed\n");
    if (was)
        snprintf(keep, sizeof keep, "%s", was);
    if (wp)
        snprintf(keepp, sizeof keepp, "%s", wp);
    fx_probe = FX_PROBE_FN;
    fx_routes = 0;
    put_env("CFT_HIP_PLANT", "bogus");
    plant_build = cft_open(artifact, 0, &h) != CFT_OK;
    put_env("CFT_HIP_PLANT", keepp[0] ? keepp : NULL);
    cft_close(h);
    h = NULL;
    /* round 3's G3A2 (VG3A's M5): a default build with CFT_HIP_PLANT set is
     * REFUSED BY NAME. It has no plant code and never reads the variable, so
     * the leg would print a green for a plant it never applied. Not a
     * failure, which a plant run expects to see: the reason, no check
     * counted, exit 2, as a default hip-fmadiff refuses it. Empty is no
     * plant in every build (the library's own rule), so only a value is
     * refused; a plant build with the variable set runs as before. */
    if (!plant_build && keepp[0]) {
        printf("  fixed: REFUSED - CFT_HIP_PLANT=\"%s\" is set, and this libcft is a default "
               "build, which has no plants and never reads the variable: the leg would be "
               "green for a plant it did not apply. Build it with HIP_PLANTS=1, or unset "
               "CFT_HIP_PLANT. No check counted; exit 2\n", keepp);
        fflush(stdout);
        exit(2);
    }
    for (k = 0; k < 5; k++)
        fx_failed[k] = 0;
    CHECK(plant_build == (fx_probe != NULL), "a %s build %s the plant build's tier probe",
          plant_build ? "plant" : "default", fx_probe ? "has" : "lacks");
    printf("  a %s build; the route probe %s; CFT_HIP_PLANT %s; CFT_HIP_TIER of the caller %s\n",
           plant_build ? "plant" : "default", fx_probe ? "present" : "absent",
           keepp[0] ? keepp : "unset", was ? keep : "unset");
    /* (a) the grammar: three spellings open, seven are refused by name */
    for (k = 0; k < 3; k++) {
        put_env("CFT_HIP_TIER", ok[k]);
        CHECK(cft_open(artifact, 0, &h) == CFT_OK, "CFT_HIP_TIER=\"%s\": %s", ok[k],
              cft_last_error());
        cft_close(h);
        h = NULL;
    }
    for (k = 0; k < 7; k++) {
        cft_status st;
        put_env("CFT_HIP_TIER", bad[k]);
        st = cft_open(artifact, 0, &h);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && h == NULL &&
              strstr(cft_last_error(), "CFT_HIP_TIER") != NULL,
              "CFT_HIP_TIER=\"%s\": %s, \"%s\" - refused by name, with no handle, wanted",
              bad[k], cft_strerror(st), cft_last_error());
        if (k == 0)
            printf("  (a) CFT_HIP_TIER=\"%s\": %s - %s\n", bad[k], cft_strerror(st),
                   cft_last_error());
        cft_close(h);
        h = NULL;
    }
    put_env("CFT_HIP_TIER", "generic");
    CHECK(cft_open(artifact, 0, &hg) == CFT_OK, "the generic handle: %s", cft_last_error());
    put_env("CFT_HIP_TIER", "fixed");
    CHECK(cft_open(artifact, 0, &hf) == CFT_OK, "the fixed handle: %s", cft_last_error());
    put_env("CFT_HIP_TIER", was ? keep : NULL);
    printf("  (a) \"\", generic and fixed open; Fixed, FIXED, \" fixed\", \"fixed \", 1, both "
           "and gen are refused by name, no handle left\n");
    if (hg && hf) {
        /* (b) the class, and its controls; since round 3's G3A2 fp128 is a
         * covered format, its class on the fixed handle at G3A's place for
         * the fp128 control (the same random draws, fx_class's random
         * triples depending on the format alone, so fp256's (c) to (e) below
         * see the data they saw at G3A), and its generic-handle control and
         * (c) to (e) after fp256's; fp32 and fp64 stay the formats the fixed
         * tier does not cover */
        if (only_fmt < 0 || only_fmt == CFT_FP256) {
            FX_AT(CFT_FP256, fx_class(hf, sw, 1, CFT_FP256, 16, "the fixed handle"));
            FX_AT(CFT_FP256, fx_class(hg, sw, 0, CFT_FP256, 16, "the generic handle"));
        }
        for (f = 0; f < 2; f++)
            if (only_fmt < 0 || only_fmt == f)
                FX_AT(f, fx_class(hf, sw, 1, f, 8, "the fixed handle"));
        if (only_fmt < 0 || only_fmt == CFT_FP128)
            FX_AT(CFT_FP128, fx_class(hf, sw, 1, CFT_FP128, 16, "the fixed handle"));
        if (only_fmt < 0 || only_fmt == CFT_FP256) {
            FX_AT(CFT_FP256, fx_others(hf, sw, CFT_FP256));
            FX_AT(CFT_FP256, fx_forms(hf, sw, CFT_FP256));
            FX_AT(CFT_FP256, fx_resident(artifact, hf, sw, plant_build, CFT_FP256));
        }
        if (only_fmt < 0 || only_fmt == CFT_FP128) {
            FX_AT(CFT_FP128, fx_class(hg, sw, 0, CFT_FP128, 16, "the generic handle"));
            FX_AT(CFT_FP128, fx_others(hf, sw, CFT_FP128));
            FX_AT(CFT_FP128, fx_forms(hf, sw, CFT_FP128));
            FX_AT(CFT_FP128, fx_resident(artifact, hf, sw, plant_build, CFT_FP128));
        }
    }
    if (!fx_probe)
        nrun("  (f) the route proof", "this libcft is a default build, which defines no "
             "cfth_plant_tier_probe (the plant build's probe of the last cft_run's kernel); "
             "build with HIP_PLANTS=1 - the bits above hold every call, but a fall-through to "
             "the generic kernel gives the same bits, so only the probe says which kernel ran "
             "(a default build's INFO line names the handle's tier, and its rate differs)");
    else
        printf("  (f) the route proof: %ld calls' kernel read from the probe - k_run256 for "
               "fp256 and k_run128 for fp128 FMA, ADD, SUB and MUL on the fixed handle, the "
               "generic for every other\n", fx_routes);
    cft_close(hg);
    cft_close(hf);
    fx_failed[4] = failures - before - fx_failed[0] - fx_failed[1] - fx_failed[2] -
                   fx_failed[3];
    printf("  fixed: failed at fp256 %d, at fp128 %d, elsewhere %d (fp32 %d, fp64 %d, the "
           "rest %d)\n", fx_failed[CFT_FP256], fx_failed[CFT_FP128],
           fx_failed[0] + fx_failed[1] + fx_failed[4], fx_failed[0], fx_failed[1], fx_failed[4]);
    printf("  fixed: %d checks, %.1f s, %d failed\n", checks - c0, fx_now() - t0,
           failures - before);
}

int main(int argc, char **argv)
{
    const char *artifact = NULL,
               *legs = "open,reduce,seg,compose,alias,two,buffers,plants"
                       /* round 2's G2A: its legs here, each a line ",name" */
                       ",aug"
                       /* round 2's G2B: its legs here, each a line ",name" */
                       ",indexed"
                       ",depth"
                       /* round 2's G2C: its legs here, each a line ",name" */
                       ",divsqrt"
                       /* round 3's G3A: its legs here, each a line ",name" */
                       ",fixed"
                       ;
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
                    "buffers,plants"
                    /* round 2's G2A: its legs here, each a line ",name" */
                    ",aug"
                    /* round 2's G2B: its legs here, each a line ",name" */
                    ",indexed"
                    ",depth"
                    /* round 2's G2C: its legs here, each a line ",name" */
                    ",divsqrt"
                    /* round 3's G3A: its legs here, each a line ",name" */
                    ",fixed"
                    "] [-f fp32|fp64|fp128|fp256] [-s small|large|all]\n",
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
    if (strstr(legs, "buffers"))
        leg_buffers(artifact, hw, sw);
    if (strstr(legs, "plants"))
        leg_plants(artifact, sw);
    /* round 2's G2A: its legs' dispatch here */
    if (strstr(legs, "aug"))
        leg_aug(artifact, hw, sw, only_fmt);
    /* round 2's G2B: its legs' dispatch here */
    if (strstr(legs, "indexed"))
        leg_indexed(artifact, hw, sw, only_fmt, which == 1);
    if (strstr(legs, "depth"))
        leg_depth(artifact, hw, sw, only_fmt);
    /* round 2's G2C: its legs' dispatch here */
    if (strstr(legs, "divsqrt"))
        leg_divsqrt(artifact, hw, sw, only_fmt);
    /* round 3's G3A: its legs' dispatch here */
    if (strstr(legs, "fixed"))
        leg_fixed(artifact, sw, only_fmt);
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
