/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Contract tests for libcft: the promises the conformance vectors
 * cannot express.
 *
 * The vectors check arithmetic, exhaustively and against the golden
 * model. They say nothing about whether a NULL operand an opcode does
 * not read is accepted, whether the output may alias an input, or
 * whether a bad argument is refused rather than computed on. Those are
 * API promises, so they are tested here.
 *
 * The arithmetic that IS here was chosen for one reason: the expected
 * values are derived from IEEE 754-2019 by hand, not from either
 * implementation. A test that agreed with both would only prove they
 * agree with each other, and they are supposed to - so these are the
 * cases where an independent reading of the standard says what the
 * answer must be. They concentrate on the far-alignment path, which is
 * the one place softfloat.c is not a transliteration of the model.
 */

#include <stdio.h>
#include <string.h>

#include "cft.h"
#include "../src/slice.h"

static int failures;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                  \
            printf(__VA_ARGS__);                                         \
            printf("\n");                                                \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void hex_elem(const uint8_t *p, int n, char *out)
{
    static const char d[] = "0123456789abcdef";
    int i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = d[p[n - 1 - i] >> 4];
        out[2 * i + 1] = d[p[n - 1 - i] & 0xf];
    }
    out[2 * n] = '\0';
}

/* ---- fp32 one-element helper ------------------------------------- */

static uint32_t run32(cft_device *dev, cft_op op, cft_round rnd,
                      uint32_t a, uint32_t b, uint32_t c, uint32_t *flags)
{
    uint8_t ea[4], eb[4], ec[4], ed[4];
    cft_status st;
    put32(ea, a); put32(eb, b); put32(ec, c); put32(ed, 0);
    st = cft_run(dev, op, CFT_FP32, rnd, ea, eb, ec, ed, 1, flags, NULL);
    CHECK(st == CFT_OK, "cft_run: %s", cft_strerror(st));
    return get32(ed);
}

#define EXPECT32(op, rnd, a, b, c, want_d, want_f)                        \
    do {                                                                  \
        uint32_t f_ = 0xdead, d_ = run32(dev, op, rnd, a, b, c, &f_);     \
        CHECK(d_ == (want_d) && f_ == (uint32_t)(want_f),                 \
              "%s fp32 %s: got 0x%08x/0x%02x want 0x%08x/0x%02x",         \
              cft_op_name(op), #rnd, (unsigned)d_, (unsigned)f_,          \
              (unsigned)(want_d), (unsigned)(want_f));                    \
    } while (0)

/* ---- fp256 constants, built from the field layout ----------------- *
 * exponent field is bits 236..254, bias 262143 = 0x3ffff. */

static void fp256_zero(uint8_t *p)     { memset(p, 0, 32); }
static void fp256_one(uint8_t *p)      { memset(p, 0, 32);
                                         p[29] = 0xf0; p[30] = 0xff;
                                         p[31] = 0x3f; }
static void fp256_min_sub(uint8_t *p)  { memset(p, 0, 32); p[0] = 1; }
static void fp256_next_up_1(uint8_t *p){ fp256_one(p); p[0] = 1; }
static void fp256_prev_1(uint8_t *p)   { memset(p, 0xff, 29);
                                         p[29] = 0xef; p[30] = 0xff;
                                         p[31] = 0x3f; }

static void expect256(cft_device *dev, const char *what, cft_op op,
                      cft_round rnd, const uint8_t *a, const uint8_t *c,
                      const uint8_t *want_d, uint32_t want_f)
{
    uint8_t b[32], d[32];
    uint32_t flags = 0xdead;
    cft_status st;
    char hg[65], hw[65];

    fp256_zero(b);
    memset(d, 0, sizeof d);
    st = cft_run(dev, op, CFT_FP256, rnd, a, b, c, d, 1, &flags, NULL);
    CHECK(st == CFT_OK, "%s: cft_run: %s", what, cft_strerror(st));
    hex_elem(d, 32, hg);
    hex_elem(want_d, 32, hw);
    CHECK(memcmp(d, want_d, 32) == 0 && flags == want_f,
          "%s: got %s/0x%02x want %s/0x%02x",
          what, hg, (unsigned)flags, hw, (unsigned)want_f);
}

/* ------------------------------------------------------------------ */

int main(void)
{
    cft_device *dev = NULL;
    cft_buffer *buf = NULL;
    cft_caps caps;
    cft_status st;
    uint32_t flags;
    int i;

    /* --- static description ------------------------------------- */
    CHECK(cft_abi_version() ==
          (((uint32_t)CFT_ABI_VERSION_MAJOR << 16) | CFT_ABI_VERSION_MINOR),
          "abi version disagrees with the header");
    CHECK(cft_format_size(CFT_FP32) == 4 && cft_format_size(CFT_FP64) == 8 &&
          cft_format_size(CFT_FP128) == 16 &&
          cft_format_size(CFT_FP256) == 32, "format sizes");
    CHECK(cft_format_size((cft_format)7) == 0, "bad format size is 0");
    CHECK(strcmp(cft_op_name(CFT_MINNUM), "minnum") == 0, "op name");
    CHECK(strcmp(cft_op_name((cft_op)15), "reserved") == 0,
          "unassigned op name");
    CHECK(cft_strerror(CFT_ERR_BUS_FAULT) != NULL, "strerror");

    /* --- open, caps ---------------------------------------------- */
    st = cft_open(NULL, 0, &dev);
    CHECK(st == CFT_OK && dev != NULL, "cft_open(NULL): %s",
          cft_strerror(st));
    if (!dev)
        return 1;

    {
        /* No device backend is compiled in, so asking for one has to
         * fail loudly rather than quietly hand back the software
         * backend under another name. */
        cft_device *hw = (cft_device *)(void *)0x1;
        CHECK(cft_open("no-such.xclbin", 0, &hw) != CFT_OK && hw == NULL,
              "an artifact open must fail, and must not leave a handle");
    }

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    st = cft_get_caps(dev, &caps);
    CHECK(st == CFT_OK, "cft_get_caps: %s", cft_strerror(st));
    CHECK(caps.format_mask == 0xfu, "software backend carries every format");
    CHECK(caps.tiles == 1, "tiles");
    CHECK(caps.flags_readable == 1, "flags readable");
    CHECK(strcmp(caps.backend, "software") == 0, "backend name");
    CHECK(caps.struct_size == sizeof caps, "struct_size echoes bytes filled");

    /* A caller that forgets struct_size gets an error, not a stack
     * smash - the field exists precisely so that the library never
     * writes further than the caller's struct. */
    {
        cft_caps small;
        memset(&small, 0, sizeof small);
        small.struct_size = 0;
        CHECK(cft_get_caps(dev, &small) == CFT_ERR_INVALID_ARGUMENT,
              "struct_size 0 must be refused");
    }

    /* --- capability discovery ------------------------------------ */
    CHECK(cft_supports(dev, CFT_FMA, CFT_FP256) == 1, "fma/fp256 supported");
    CHECK(cft_supports(dev, CFT_ICMPLT, CFT_FP32) == 1, "icmplt supported");
    CHECK(cft_supports(dev, (cft_op)15, CFT_FP32) == 0, "op 15 unassigned");
    CHECK(cft_supports(dev, (cft_op)200, CFT_FP32) == 0, "op 200 unassigned");
    CHECK(cft_supports(dev, CFT_FMA, (cft_format)9) == 0, "bad format");

    /* --- argument checking --------------------------------------- */
    {
        uint8_t a[4], b[4], c[4], d[4];
        put32(a, 0x3f800000); put32(b, 0); put32(c, 0x3f800000);
        CHECK(cft_run(NULL, CFT_ADD, CFT_FP32, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "NULL device");
        CHECK(cft_run(dev, CFT_ADD, (cft_format)4, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "bad format");
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, (cft_round)5, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "bad rounding");
        CHECK(cft_run(dev, (cft_op)256, CFT_FP32, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "opcode wider than the device's field");
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, b, c, NULL, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "NULL output");
        CHECK(cft_run(dev, CFT_FMA, CFT_FP32, CFT_RNE, a, NULL, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "fma reads b, so a NULL b is an error");

        /* n == 0 is a no-op that still reports clean flags, so a loop
         * with an empty tail does not have to special-case itself. */
        flags = 0xdead;
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, NULL, NULL, NULL,
                      NULL, 0, &flags, NULL) == CFT_OK && flags == 0,
              "n == 0");
    }

    /* --- operands an opcode does not read may be NULL ------------- */
    {
        uint8_t a[4], c[4], d[4];
        put32(a, 0x3f800000);            /* 1.0 */
        put32(c, 0x40000000);            /* 2.0 */
        put32(d, 0);
        flags = 0xdead;
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, c, d, 1,
                     &flags, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40400000u && flags == 0,
              "add with b NULL: 1+2 = 3, got 0x%08x/0x%02x",
              (unsigned)get32(d), (unsigned)flags);

        put32(a, 0x40000000);            /* 2.0 */
        put32(d, 0);
        flags = 0xdead;
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, a, c, NULL, d, 1,
                     &flags, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40800000u && flags == 0,
              "mul with c NULL: 2*2 = 4, got 0x%08x/0x%02x",
              (unsigned)get32(d), (unsigned)flags);
    }

    /* --- the output may alias an input ---------------------------- */
    {
        uint8_t a[12], c[12];
        static const uint32_t in[3]   = { 0x3f800000u, 0x40000000u,
                                          0x40400000u };            /* 1 2 3 */
        static const uint32_t want[3] = { 0x40000000u, 0x40400000u,
                                          0x40800000u };            /* 2 3 4 */
        for (i = 0; i < 3; i++) {
            put32(a + 4 * i, in[i]);
            put32(c + 4 * i, 0x3f800000u);
        }
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, c, a, 3,
                     NULL, NULL);
        CHECK(st == CFT_OK, "in-place run: %s", cft_strerror(st));
        for (i = 0; i < 3; i++)
            CHECK(get32(a + 4 * i) == want[i],
                  "in-place element %d: got 0x%08x want 0x%08x",
                  i, (unsigned)get32(a + 4 * i), (unsigned)want[i]);
    }

    /* --- unassigned opcodes compute a defined answer -------------- */
    EXPECT32((cft_op)15,  CFT_RNE, 0x3f800000u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32((cft_op)200, CFT_RNE, 0x3f800000u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);

    /* --- rounding, from 754-2019 rather than from either model ----
     *
     * 1.0 +/- 2^-149 is the far-alignment path in miniature: the
     * addend lies far below the product's last bit, so it can only be
     * a sticky bit, and every attribute has to notice it anyway. */
    EXPECT32(CFT_ADD, CFT_RNE, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_ADD, CFT_RUP, 0x3f800000u, 0, 0x00000001u,
             0x3f800001u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_ADD, CFT_RDN, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RNE, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RDN, 0x3f800000u, 0, 0x00000001u,
             0x3f7fffffu, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RUP, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);

    /* 754-2019 7.4: overflow is signalled in every attribute, but only
     * some deliver an infinity. */
    EXPECT32(CFT_MUL, CFT_RNE, 0x7f7fffffu, 0x40000000u, 0,
             0x7f800000u, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RTZ, 0x7f7fffffu, 0x40000000u, 0,
             0x7f7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RDN, 0x7f7fffffu, 0x40000000u, 0,
             0x7f7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RUP, 0xff7fffffu, 0x40000000u, 0,
             0xff7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);

    /* Signed zero, 754-2019 6.3: an exact cancellation is +0 in every
     * attribute except roundTowardNegative. */
    EXPECT32(CFT_SUB, CFT_RNE, 0x3f800000u, 0, 0x3f800000u, 0x00000000u, 0);
    EXPECT32(CFT_SUB, CFT_RDN, 0x3f800000u, 0, 0x3f800000u, 0x80000000u, 0);

    /* Signed zero, 754-2019 9.6: min(+0,-0) is -0, max(+0,-0) is +0. */
    EXPECT32(CFT_MIN, CFT_RNE, 0x00000000u, 0x80000000u, 0, 0x80000000u, 0);
    EXPECT32(CFT_MAX, CFT_RNE, 0x00000000u, 0x80000000u, 0, 0x00000000u, 0);

    /* A signaling NaN raises invalid; abs and negate do not, ever, and
     * they keep the payload (754-2019 5.5.1). */
    EXPECT32(CFT_ADD, CFT_RNE, 0x7f800001u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32(CFT_ABS, CFT_RNE, 0xff800001u, 0, 0, 0x7f800001u, 0);
    EXPECT32(CFT_NEG, CFT_RNE, 0x7f800001u, 0, 0, 0xff800001u, 0);
    EXPECT32(CFT_MIN, CFT_RNE, 0x7f800001u, 0x3f800000u, 0,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32(CFT_MINNUM, CFT_RNE, 0x7f800001u, 0x3f800000u, 0,
             0x3f800000u, CFT_FLAG_INVALID);

    /* --- the same three cases at fp256 ----------------------------
     *
     * Same shape, 237 significand bits and a 2^-262378 perturbation.
     * This is where softfloat.c's bounded alignment earns its keep:
     * the exact difference of these two operands is about 262,000 bits
     * wide, and the answer must still be right to the last bit. */
    {
        uint8_t one[32], minsub[32], up[32], down[32];
        fp256_one(one);
        fp256_min_sub(minsub);
        fp256_next_up_1(up);
        fp256_prev_1(down);

        expect256(dev, "fp256 1 + minsub rne", CFT_ADD, CFT_RNE, one, minsub,
                  one, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 + minsub rup", CFT_ADD, CFT_RUP, one, minsub,
                  up, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rne", CFT_SUB, CFT_RNE, one, minsub,
                  one, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rdn", CFT_SUB, CFT_RDN, one, minsub,
                  down, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rup", CFT_SUB, CFT_RUP, one, minsub,
                  one, CFT_FLAG_INEXACT);
    }

    /* --- the argument beat padding rests on ----------------------
     *
     * The tile computes in whole 256-bit beats, so the device backend
     * pads a partial tail with zero operands. That is only sound if a
     * zero operand raises nothing - otherwise a caller's exception
     * flags would depend on the length of their array, which is
     * precisely the kind of silent, length-dependent result this
     * project exists to remove.
     *
     * So check it rather than assert it, across every opcode the byte
     * can hold, every format and every attribute. An unassigned opcode
     * raises invalid, and that is fine: it raises invalid for the real
     * elements too, so the OR the backend reports is unchanged. */
    {
        int f_i, op_i, r_i, bad = 0;
        uint8_t zero[32], out[32];
        memset(zero, 0, sizeof zero);
        for (f_i = 0; f_i < 4 && bad < 4; f_i++) {
            size_t esz = cft_format_size((cft_format)f_i);
            for (op_i = 0; op_i < 256 && bad < 4; op_i++) {
                uint32_t want;
                /* Reductions are not elementwise and cft_run refuses
                 * them, so there is no padded tail to reason about.
                 * Skipping them here rather than deleting the opcode
                 * from the sweep, because the refusal itself is worth
                 * asserting - checked immediately below. */
                if (op_i == CFT_SUM || op_i == CFT_DOT) {
                    st = cft_run(dev, (cft_op)op_i, (cft_format)f_i,
                                 CFT_RNE, zero, zero, zero, out, 1,
                                 NULL, NULL);
                    if (st != CFT_ERR_INVALID_ARGUMENT) {
                        bad++;
                        CHECK(0, "cft_run(%s) must refuse the reduction "
                                 "opcode %d, got %s",
                              cft_format_name((cft_format)f_i), op_i,
                              cft_strerror(st));
                    }
                    continue;
                }
                want = cft_supports(dev, (cft_op)op_i, (cft_format)f_i)
                       ? 0u : CFT_FLAG_INVALID;
                for (r_i = 0; r_i < 5; r_i++) {
                    uint32_t fl = 0xdead;
                    memset(out, 0xa5, sizeof out);
                    st = cft_run(dev, (cft_op)op_i, (cft_format)f_i,
                                 (cft_round)r_i, zero, zero, zero, out, 1,
                                 &fl, NULL);
                    if (st != CFT_OK || fl != want) {
                        bad++;
                        CHECK(0, "zero padding raises flags: %s op %d "
                                 "rnd %d -> status %s flags 0x%02x, "
                                 "want 0x%02x",
                              cft_format_name((cft_format)f_i), op_i, r_i,
                              cft_strerror(st), (unsigned)fl,
                              (unsigned)want);
                        break;
                    }
                    (void)esz;
                }
            }
        }
        if (!bad)
            printf("  zero operands are flag-free for all 256 opcodes "
                   "x 4 formats x 5 attributes\n");
    }

    /* --- how work is split across compute units -------------------
     *
     * This is the arithmetic that decides whether a four-tile run
     * computes every element exactly once and writes it to the right
     * offset. Until it was factored out of the XRT backend, reaching
     * it needed a card - which is a poor place to discover an
     * off-by-one. It needs nothing here, so it is checked over every
     * interesting size and tile count.
     */
    {
        static const size_t sizes[] = {
            1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65,
            127, 128, 129, 255, 256, 257, 1000, 4096, 4097, 100000
        };
        static const size_t esizes[] = {4, 8, 16, 32};
        /* Sized for the largest tile count the contract is checked at,
         * not the largest one any device has. The property being tested
         * - that the answer and the padding total do not depend on how
         * the work was split - has to hold at counts no bitstream can
         * reach yet, because it is impossible to retrofit once the
         * abstraction has leaked and there is no way to bisect a
         * 64-tile disagreement after the fact. Testing it is free; the
         * hardware existing is not a prerequisite. */
#define SLICE_MAX_TILES 64
        cft_slice sl[SLICE_MAX_TILES + 1];
        size_t si, ei, tiles;
        int bad = 0;

        for (ei = 0; ei < 4 && !bad; ei++) {
            size_t esz = esizes[ei], epb = 32 / esz;
            for (si = 0; si < sizeof sizes / sizeof sizes[0] && !bad; si++) {
                size_t n = sizes[si];
                size_t beats = (n + epb - 1) / epb;
                size_t reference_padded = 0;
                for (tiles = 1; tiles <= SLICE_MAX_TILES && !bad; tiles++) {
                    size_t k = cft_plan_slices(n, esz, tiles, sl);
                    size_t covered = 0, total_padded = 0, j;

                    if (k == 0 || k > tiles) {
                        CHECK(0, "esz %lu n %lu tiles %lu: %lu slices",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles, (unsigned long)k);
                        bad = 1;
                        break;
                    }
                    for (j = 0; j < k; j++) {
                        /* contiguous, in order, starting at zero */
                        if (sl[j].first_elem != covered) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "starts at %lu, expected %lu",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].first_elem,
                                  (unsigned long)covered);
                            bad = 1;
                            break;
                        }
                        /* a whole number of beats, or the engine's
                         * beat count truncates the tail away */
                        if (sl[j].padded % epb) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "is %lu elements, not whole beats",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].padded);
                            bad = 1;
                            break;
                        }
                        if (sl[j].real == 0 || sl[j].real > sl[j].padded) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "real %lu padded %lu",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].real,
                                  (unsigned long)sl[j].padded);
                            bad = 1;
                            break;
                        }
                        covered += sl[j].real;
                        total_padded += sl[j].padded;
                    }
                    if (bad)
                        break;
                    if (covered != n) {
                        CHECK(0, "esz %lu n %lu tiles %lu covers %lu",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles, (unsigned long)covered);
                        bad = 1;
                        break;
                    }
                    /* The property the flags depend on: the total
                     * amount of padding does not vary with the tile
                     * count, so neither does the sticky word. */
                    if (tiles == 1)
                        reference_padded = total_padded;
                    else if (total_padded != reference_padded) {
                        CHECK(0, "esz %lu n %lu: %lu tiles pad %lu "
                                 "elements, 1 tile pads %lu - the flags "
                                 "would depend on the tile count",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles,
                              (unsigned long)total_padded,
                              (unsigned long)reference_padded);
                        bad = 1;
                        break;
                    }
                    if (total_padded != beats * epb) {
                        CHECK(0, "esz %lu n %lu tiles %lu: padded total "
                                 "%lu, expected %lu",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles,
                              (unsigned long)total_padded,
                              (unsigned long)(beats * epb));
                        bad = 1;
                        break;
                    }
                }
            }
        }
        CHECK(cft_plan_slices(0, 4, 4, sl) == 0, "n = 0 makes no slices");
        if (!bad)
            printf("  work splits correctly for 27 sizes x 4 formats x "
                   "64 tile counts, and the padding total never depends "
                   "on the tile count\n");
    }

    /* --- divide and square root ----------------------------------
     *
     * The arithmetic proof lives in tests/divsqrt_check.py (the whole
     * operand matrix against the model); what belongs here is the API
     * contract and the answers an independent reading of 754 pins
     * down: special classes, the two divide flags, exactness where
     * the result is representable, and the aliasing promise. 1/3 and
     * sqrt(2) are the two inexact literals, derived by hand from the
     * standard the way this file's other constants are. */
    CHECK(cft_supports(dev, CFT_RECIP_SEED, CFT_FP32) == 1,
          "recip_seed supported");
    CHECK(cft_supports(dev, CFT_RSQRT_SEED, CFT_FP256) == 1,
          "rsqrt_seed supported");
    CHECK(strcmp(cft_op_name(CFT_RECIP_SEED), "recip_seed") == 0 &&
          strcmp(cft_op_name(CFT_RSQRT_SEED), "rsqrt_seed") == 0,
          "seed op names");

    {
        uint8_t a[8], b[8], d[8];
        uint32_t f2;

        /* the seed opcodes are QUIET, and their special classes are
         * the limit values - both facts cft_div depends on */
        f2 = 0xdead;
        put32(a, 0x7f800000u);                       /* +inf */
        st = cft_run(dev, CFT_RECIP_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0 && f2 == 0,
              "recip_seed(+inf) = +0, quietly");
        put32(a, 0x80000000u);                       /* -0 */
        st = cft_run(dev, CFT_RECIP_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f2 == 0,
              "recip_seed(-0) = -inf, quietly");
        put32(a, 0xbf800000u);                       /* -1 */
        st = cft_run(dev, CFT_RSQRT_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u && f2 == 0,
              "rsqrt_seed(-1) = qNaN, quietly");

        /* divide: specials and both divide flags */
        put32(a, 0x3f800000u); put32(b, 0x40000000u);
        f2 = 0xdead;
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f2 == 0,
              "1/2 = 0.5 exactly, no flags");
        put32(a, 0x3f800000u); put32(b, 0);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f2 == CFT_FLAG_DIVBYZERO, "1/0 = +inf, divideByZero");
        put32(a, 0); put32(b, 0);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u &&
              f2 == CFT_FLAG_INVALID, "0/0 = qNaN, invalid");
        put32(a, 0x3f800000u); put32(b, 0x40400000u);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3eaaaaabu &&
              f2 == CFT_FLAG_INEXACT,
              "1/3 rounds to 0x3eaaaaab, inexact");

        /* d may alias a - each chunk reads its slice before writing */
        put32(a, 0x40400000u); put32(b, 0x40000000u);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, a, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(a) == 0x3fc00000u,
              "3/2 in place = 1.5");

        /* square root */
        put32(a, 0x40800000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f2 == 0,
              "sqrt(4) = 2 exactly, no flags");
        put32(a, 0x80000000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "sqrt(-0) = -0, no flags");
        put32(a, 0xbf800000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u &&
              f2 == CFT_FLAG_INVALID, "sqrt(-1) = qNaN, invalid");
        put32(a, 0x40000000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f2 == CFT_FLAG_INEXACT,
              "sqrt(2) rounds to 0x3fb504f3, inexact");

        /* argument contract, mirroring cft_run's shape */
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 0, &f2, NULL)
              == CFT_OK && f2 == 0, "n = 0 succeeds with clean flags");
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "divide needs b");
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, NULL, b, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "divide needs a");
        CHECK(cft_sqrt(dev, (cft_format)6, CFT_RNE, a, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad format refused");
    }

    {
        /* fp256, the format no host hardware anchors: 1/1 and sqrt(1)
         * are exact identities the field layout pins by hand. */
        uint8_t a[32], b[32], d[32];
        uint32_t f2 = 0xdead;
        fp256_one(a);
        fp256_one(b);
        st = cft_div(dev, CFT_FP256, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(d, a, 32) == 0 && f2 == 0,
              "fp256 1/1 = 1 exactly");
        memset(d, 0xAA, sizeof d);
        st = cft_sqrt(dev, CFT_FP256, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(d, a, 32) == 0 && f2 == 0,
              "fp256 sqrt(1) = 1 exactly");
    }

    /* --- the phase-1 transcendentals (ABI 0.3) ---------------------
     *
     * Same charter as the block below: host/tests/transcend_check.py
     * and the MPFR oracle prove these at scale, so what belongs HERE
     * is the refusals, the aliasing promise, and the handful of edges
     * whose expected bits come from reading clause 9.2.1 by hand -
     * including the two rows implementations most often get wrong. */
    {
        uint8_t a[8], b[8], d[8];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                        /* 1.0 */
        put32(b, 0x40000000u);                        /* 2.0 */
        CHECK(cft_exp(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "exp refuses rnd = -1");
        CHECK(cft_pow(dev, CFT_FP32, (cft_round)5, a, b, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "pow refuses rnd = 5");
        CHECK(cft_log(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "log refuses a bad format");
        CHECK(cft_pow(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "pow needs b");
        CHECK(cft_hypot(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "hypot needs b");
        f3 = 0xdead;
        CHECK(cft_exp(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
              == CFT_OK && f3 == 0, "exp n = 0 succeeds, clean flags");

        /* Hand-derived clause 9.2.1 rows. exp(-inf) is +0 and silent;
         * expm1(-0) keeps the sign, which is half of why expm1 exists;
         * log(+0) is -inf with divideByZero; pow(qNaN, +0) is 1 for
         * ANY x; and pow(+0, -inf) is the |x| < 1 row - +inf, and it
         * signals NOTHING, because the divideByZero is the pole at a
         * finite negative exponent rather than the limit. */
        put32(a, 0xff800000u);
        st = cft_exp(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "exp(-inf) = +0, silent");
        put32(a, 0x80000000u);
        st = cft_expm1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "expm1(-0) = -0, silent");
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "log1p(-0) = -0, silent");
        put32(a, 0x00000000u);
        st = cft_log(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO, "log(+0) = -inf, divideByZero");
        put32(a, 0xbf800000u);
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO, "log1p(-1) = -inf, divideByZero");
        put32(a, 0x7fc00000u);
        put32(b, 0x00000000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "pow(qNaN, +0) = 1, silent");
        put32(a, 0x00000000u);
        put32(b, 0xff800000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "pow(+0, -inf) = +inf and signals NOTHING");
        put32(a, 0x00000000u);
        put32(b, 0xbf800000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "pow(+0, -1) = +inf with divideByZero");
        put32(a, 0x7f800000u);
        put32(b, 0x7fc00000u);
        st = cft_hypot(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "hypot(+inf, qNaN) = +inf, silent");
        put32(a, 0x40400000u);                        /* 3 */
        put32(b, 0x40800000u);                        /* 4 */
        st = cft_hypot(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x40a00000u && f3 == 0,
              "hypot(3, 4) = 5 EXACTLY - no inexact");
        put32(a, 0x41200000u);                        /* 10 */
        st = cft_log10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "log10(10) = 1 EXACTLY");
        put32(a, 0x41000000u);                        /* 8 */
        st = cft_log2(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x40400000u && f3 == 0,
              "log2(8) = 3 EXACTLY");
        st = cft_exp2(dev, CFT_FP32, CFT_RNE, d, d, 1, &f3);   /* aliased */
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f3 == 0,
              "exp2(3) = 8 EXACTLY, and d may alias a");
    }

    /* --- the clause-5 completion set ------------------------------
     *
     * The check harness proves these against the model at scale; what
     * belongs HERE is this file's charter - refusals, aliasing, and a
     * few edges whose expected bits come from reading 754 by hand.
     * The rnd refusals exist because of a real bug: a (cft_round)-1
     * once slid through a shared validator and computed under a
     * rounding no legal attribute produces. */
    {
        uint8_t a[4 * 8], d[4 * 8];
        int32_t i32out;
        uint32_t f2 = 0xdead;
        int k;

        put32(a, 0x3f000000u);               /* 0.5 */
        CHECK(cft_rint(dev, CFT_FP32, (cft_round)-1, 0, a, d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "rint refuses rnd = -1");
        CHECK(cft_rint(dev, CFT_FP32, (cft_round)5, 0, a, d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "rint refuses rnd = 5");
        CHECK(cft_scaleb(dev, CFT_FP32, (cft_round)-1, a, -2000000000,
                         d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT,
              "scaleb refuses rnd = -1 on the host path too");
        CHECK(cft_convert(dev, CFT_FP64, CFT_FP32, (cft_round)-1, a, d, 1,
                          &f2) == CFT_ERR_INVALID_ARGUMENT,
              "convert refuses rnd = -1");
        CHECK(cft_cvt_to_i32(dev, CFT_FP32, (cft_round)-1, 0, a, &i32out,
                             1, &f2) == CFT_ERR_INVALID_ARGUMENT,
              "cvt_to refuses rnd = -1");
        CHECK(cft_rem(dev, CFT_FP32, a, NULL, d, 1, &f2)
              == CFT_ERR_INVALID_ARGUMENT, "remainder needs b");
        f2 = 0xdead;
        CHECK(cft_rint(dev, CFT_FP32, CFT_RNE, 0, a, d, 0, &f2, NULL)
              == CFT_OK && f2 == 0, "rint n = 0 succeeds, clean flags");

        /* hand-derived edges: rint(-0.5, RNE) is MINUS zero (5.9's
         * operand-sign rule); nextUp of the least-magnitude negative
         * subnormal is -0 (5.3.1's explicit choice); logB(+0) is -inf
         * with divideByZero; convertToInteger(NaN) delivers INT32_MAX
         * with invalid (the contract's RISC-V table). */
        put32(a, 0xbf000000u);
        st = cft_rint(dev, CFT_FP32, CFT_RNE, 0, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "rint(-0.5, rne) = -0, silent");
        put32(a, 0x80000001u);
        st = cft_next_up(dev, CFT_FP32, a, d, 1, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "nextUp(-min_subnormal) = -0");
        put32(a, 0x00000000u);
        st = cft_logb(dev, CFT_FP32, a, d, 1, &f2);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f2 == CFT_FLAG_DIVBYZERO, "logB(+0) = -inf, divideByZero");
        put32(a, 0x7fc00000u);
        st = cft_cvt_to_i32(dev, CFT_FP32, CFT_RNE, 0, a, &i32out, 1, &f2);
        CHECK(st == CFT_OK && i32out == 2147483647 &&
              f2 == CFT_FLAG_INVALID, "cvt_to_i32(NaN) = INT32_MAX, invalid");

        /* aliasing: d == a must equal the separate-buffer answer for
         * the same-format entry points, per the header's promise */
        for (k = 0; k < 8; k++)
            put32(a + 4 * k, 0x3f000000u + (uint32_t)k * 0x00100000u);
        st = cft_rint(dev, CFT_FP32, CFT_RUP, 1, a, d, 8, &f2, NULL);
        CHECK(st == CFT_OK, "rint separate buffers");
        st = cft_rint(dev, CFT_FP32, CFT_RUP, 1, a, a, 8, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(a, d, 32) == 0,
              "rint in place matches");
        for (k = 0; k < 8; k++)
            put32(a + 4 * k, 0x3f000000u + (uint32_t)k * 0x00100000u);
        st = cft_scaleb(dev, CFT_FP32, CFT_RNE, a, 130, d, 8, &f2, NULL);
        CHECK(st == CFT_OK, "scaleb separate buffers");
        st = cft_scaleb(dev, CFT_FP32, CFT_RNE, a, 130, a, 8, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(a, d, 32) == 0,
              "scaleb in place matches (staged path)");
    }

    /* --- buffers ------------------------------------------------- */
    st = cft_alloc(dev, 4096, &buf);
    CHECK(st == CFT_OK && buf != NULL, "cft_alloc: %s", cft_strerror(st));
    if (buf) {
        uint8_t *p = (uint8_t *)cft_buffer_data(buf);
        CHECK(p != NULL, "buffer data pointer");
        CHECK(cft_buffer_to_device(buf) == CFT_OK, "to_device");
        CHECK(cft_buffer_from_device(buf) == CFT_OK, "from_device");
        if (p) {
            /* Buffer memory is ordinary memory here, so it feeds
             * cft_run directly - which is the property that keeps code
             * written this way portable to the device backend. */
            put32(p, 0x3f800000u);
            put32(p + 8, 0x40000000u);
            st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, p, NULL, p + 8,
                         p + 16, 1, NULL, NULL);
            CHECK(st == CFT_OK && get32(p + 16) == 0x40400000u,
                  "run over a device buffer");
        }
        cft_buffer_free(buf);
    }
    cft_buffer_free(NULL);          /* must be safe */

    cft_close(dev);
    cft_close(NULL);                /* must be safe */

    if (failures == 0)
        printf("api-test: all contract checks passed\n");
    else
        printf("api-test: %d FAILED\n", failures);
    return failures ? 1 : 0;
}
