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

static void put64(uint8_t *p, uint64_t v)
{
    int i;
    for (i = 0; i < 8; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}

static uint64_t get64(const uint8_t *p)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < 8; i++)
        v |= (uint64_t)p[i] << (8 * i);
    return v;
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
                if (op_i == CFT_SUM || op_i == CFT_DOT ||
                    op_i == CFT_SUMSQ || op_i == CFT_SUMABS) {
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

        /* The neighbour rule, which the sabotage run of 2026-09-02
         * showed this file could not catch: exp of an argument below
         * 2^-(p+3) is one half-gap above 1, so it rounds to 1 in four
         * attributes and to nextUp(1) in the fifth, and no working
         * precision decides that - only the SIDE does. expm1 and log1p
         * of the same argument go opposite ways for the same reason,
         * and both land subnormal, so both are tiny AND inexact. */
        put32(a, 0x00000001u);                        /* min subnormal */
        st = cft_exp(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f3 == CFT_FLAG_INEXACT,
              "exp(min subnormal) = 1, inexact");
        st = cft_exp(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f3 == CFT_FLAG_INEXACT,
              "exp(min subnormal) upward = nextUp(1)");
        st = cft_expm1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "expm1(min subnormal) toward zero stays there, tiny+inexact");
        st = cft_log1p(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log1p(min subnormal) downward is +0, tiny+inexact");
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log1p(min subnormal) to nearest stays put, tiny+inexact");
    }

    /* --- the phase-2 trigonometrics (ABI 0.4) ----------------------
     *
     * Same charter again: the refusals, the aliasing rule, the exact
     * cases whose bits come from reading the standard rather than from
     * running the library, and - because the 2026-09-02 sabotage run
     * showed this file could not catch a flipped neighbour SIDE - one
     * case from every neighbour family this set has.
     */
    {
        uint8_t a[4], b[4], d[4];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                       /* 1.0f */
        CHECK(cft_sinpi(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_sinpi refuses an out-of-range rounding attribute");
        CHECK(cft_atan2(dev, CFT_FP32, (cft_round)7, a, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan2 refuses an out-of-range rounding attribute");
        CHECK(cft_atan(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan refuses an unknown format");
        CHECK(cft_atan2pi(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan2pi refuses a NULL second operand");
        f3 = 0xdead;
        CHECK(cft_tanpi(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
                  == CFT_OK && f3 == 0,
              "cft_tanpi with n == 0 touches nothing and clears the flags");

        /* The exact cases, and they raise NOTHING - which is the whole
         * observable difference between this and an accurate
         * implementation. Niven's theorem is what makes the list
         * finite. */
        put32(a, 0x3f000000u);                       /* 0.5f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "sinPi(1/2) = 1 EXACTLY");
        st = cft_cospi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "cosPi(1/2) = +0 EXACTLY");
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "tanPi(1/2) = +inf with divideByZero");
        put32(a, 0xbf000000u);                       /* -0.5f */
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "tanPi(-1/2) = -inf with divideByZero");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "sinPi(1) = +0: the sign of the ARGUMENT, not of (-1)^n");
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tanPi(1) = -0, because it is sinPi over cosPi");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sinPi(-1) = -0");
        st = cft_acospi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "acosPi(-1) = 1 EXACTLY");
        st = cft_atanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xbe800000u && f3 == 0,
              "atanPi(-1) = -1/4 EXACTLY");
        put32(a, 0x3e800000u);                       /* 0.25f */
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "tanPi(1/4) = 1 EXACTLY");
        st = cft_asinpi(dev, CFT_FP32, CFT_RNE, d, d, 1, &f3);  /* aliased */
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f3 == 0,
              "asinPi(1) = 1/2 EXACTLY, and d may alias a");
        put32(a, 0x00000000u);
        put32(b, 0x80000000u);                       /* (+0, -0) */
        st = cft_atan2pi(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "atan2Pi(+0, -0) = 1 EXACTLY - the row most often missed");
        put32(a, 0x7f800000u);
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "sinPi(+inf) is invalid: there is no limit there");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_asin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "asin(2) is invalid");

        /* One case from every neighbour family, each of which is a
         * SIDE and not a value: no working precision separates these
         * from the number beside them, so a flipped side is invisible
         * to everything except a directed rounding. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_asin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asin(min subnormal) stays put: asin is ABOVE its argument");
        st = cft_asin(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asin(min subnormal) upward steps off it");
        st = cft_atan(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan(min subnormal) toward zero is +0: atan is BELOW it");
        st = cft_atan(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan(min subnormal) to nearest stays put");
        st = cft_cospi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "cosPi(min subnormal) downward is nextDown(1)");
        st = cft_acospi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3effffffu &&
              f3 == CFT_FLAG_INEXACT,
              "acosPi(min subnormal) downward is nextDown(1/2)");
        put32(a, 0x7f7fffffu);                       /* max finite */
        st = cft_atanpi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3effffffu &&
              f3 == CFT_FLAG_INEXACT,
              "atanPi(max finite) downward is nextDown(1/2)");
        /* and atan2 beside an exactly dyadic quotient - here the
         * quotient is the subnormal MIDPOINT minSub/2, which is not a
         * representable number at all */
        put32(a, 0x00000001u);
        put32(b, 0x40000000u);                       /* 2.0f */
        st = cft_atan2(dev, CFT_FP32, CFT_RUP, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan2(minSub, 2) upward reaches the smallest subnormal");
        st = cft_atan2(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan2(minSub, 2) to nearest is +0: just below a midpoint");
    }

    /* --- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5)
     *
     * The same charter: the refusals, the exact cases whose bits come
     * from a theorem rather than from the library, the special rows,
     * one case from every neighbour family - and the reduction's two
     * published worst cases, whose expected bits come from the rule
     * beside 1 and from mpmath at 700 bits, an oracle that shares
     * nothing with the library.
     */
    {
        uint8_t a[8], d[8];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                       /* 1.0f */
        CHECK(cft_sin(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_sin refuses an out-of-range rounding attribute");
        CHECK(cft_cosh(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_cosh refuses an unknown format");
        f3 = 0xdead;
        CHECK(cft_atanh(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
                  == CFT_OK && f3 == 0,
              "cft_atanh with n == 0 touches nothing and clears the flags");

        /* The exact cases are the zeros - Hermite-Lindemann makes the
         * list a theorem - and every one raises NOTHING. */
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sin(-0) = -0 EXACTLY");
        st = cft_cos(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "cos(-0) = 1 EXACTLY");
        st = cft_tan(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tan(-0) = -0 EXACTLY");
        st = cft_sinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sinh(-0) = -0 EXACTLY");
        st = cft_cosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "cosh(-0) = 1 EXACTLY");
        st = cft_tanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tanh(-0) = -0 EXACTLY");
        st = cft_asinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "asinh(-0) = -0 EXACTLY");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "atanh(-0) = -0 EXACTLY");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "acosh(1) = +0 EXACTLY");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "atanh(1) = +inf with divideByZero: the pole");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "atanh(-1) = -inf with divideByZero");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "acosh(-1) is invalid: the domain starts at 1");
        put32(a, 0x7f800000u);                       /* +inf */
        st = cft_tanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "tanh(+inf) = 1 EXACTLY: a limit that is representable");
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "sin(+inf) is invalid: there is no limit there");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "acosh(+inf) = +inf, silent");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "atanh(+inf) is invalid");
        put32(a, 0xff800000u);                       /* -inf */
        st = cft_cosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "cosh(-inf) = +inf: even");
        st = cft_sinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f3 == 0,
              "sinh(-inf) = -inf: odd");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "acosh(-inf) is invalid");

        /* One case from every neighbour family, each a SIDE and not a
         * value. sin, tanh and asinh lie on the zero side of a tiny
         * argument; tan, sinh and atanh on the far side; cos is below 1
         * and cosh above it. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_sin(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sin(min subnormal) downward is +0: sin is BELOW its argument");
        st = cft_sin(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sin(min subnormal) upward stays put");
        st = cft_tan(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "tan(min subnormal) upward steps off it: tan is ABOVE");
        st = cft_sinh(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sinh(min subnormal) upward steps off it");
        st = cft_tanh(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "tanh(min subnormal) toward zero is +0");
        st = cft_asinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asinh(min subnormal) to nearest stays put");
        st = cft_atanh(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atanh(min subnormal) downward stays put: atanh is ABOVE");
        st = cft_cos(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "cos(min subnormal) downward is nextDown(1)");
        st = cft_cosh(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f3 == CFT_FLAG_INEXACT,
              "cosh(min subnormal) upward is nextUp(1)");

        /* The reduction's published worst cases. 16367173 * 2^72 is the
         * binary32 argument nearest a multiple of pi/2 and
         * 0x1.6ac5b262ca1ffp+849 the binary64 one; the search in
         * host/tools/pi_worstcase.py rediscovers both. Both sit beside
         * an ODD multiple, so the sines are 1 minus about 2^-59 and
         * 2^-123 - inside the half gap below 1, where the neighbour
         * rule beside 1 decides: 1 to nearest, nextDown(1) toward
         * zero. The cosines are the reduced arguments themselves (up
         * to sign), and those bits come from mpmath at 700 bits,
         * rounded to the format by hand. */
        put32(a, 0x6f79be45u);
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary32 worst case) to nearest is 1");
        st = cft_sin(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary32 worst case) toward zero is nextDown(1)");
        st = cft_cos(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xb0ddeea9u &&
              f3 == CFT_FLAG_INEXACT,
              "cos(binary32 worst case) is the reduced argument, -1.6148e-9");
        put64(a, UINT64_C(0x7506ac5b262ca1ff));
        st = cft_sin(dev, CFT_FP64, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0x3ff0000000000000) &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary64 worst case) to nearest is 1");
        st = cft_sin(dev, CFT_FP64, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0x3fefffffffffffff) &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary64 worst case) downward is nextDown(1)");
        st = cft_cos(dev, CFT_FP64, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0xbc214ae72e6ba22f) &&
              f3 == CFT_FLAG_INEXACT,
              "cos(binary64 worst case) is the reduced argument, -4.687e-19");
    }


    /* --- the rest of table 9.1 (part of the 0.6 step)
     *
     * The same charter as the three phases above: the refusals, the
     * exact cases whose bits come from a theorem rather than from the
     * library, the special rows - including the three where this
     * contract follows 754-2019 and GNU MPFR does not - one case from
     * every neighbour family, and the identity between rootn(x, 2) and
     * squareRoot with the single input where the standard's own NOTE
     * says they differ.
     */
    {
        uint8_t a[8], b[8], d[8];
        uint8_t av[3 * 4], dv[3 * 4];
        int64_t nn[3];
        uint32_t f4 = 0xdead;

        put32(a, 0x40000000u);                       /* 2.0f */
        CHECK(cft_exp2m1(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_exp2m1 refuses an out-of-range rounding attribute");
        CHECK(cft_rsqrt(dev, (cft_format)9, CFT_RNE, a, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_rsqrt refuses an unknown format");
        nn[0] = 2;
        CHECK(cft_pown(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_pown refuses a NULL integer-exponent array");
        CHECK(cft_compound(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_compound refuses a NULL integer-exponent array");
        CHECK(cft_rootn(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_rootn refuses a NULL integer-exponent array");
        CHECK(cft_powr(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_powr refuses a NULL second operand");
        f4 = 0xdead;
        CHECK(cft_rootn(dev, CFT_FP32, CFT_RNE, NULL, NULL, NULL, 0, &f4)
                  == CFT_OK && f4 == 0,
              "cft_rootn with n == 0 elements touches nothing");

        /* Exactness, and every one of these is an integer identity
         * rather than a rounding: 2^3 - 1 = 7, 2^-3 - 1 = -7/8,
         * 10^2 = 100, 10^2 - 1 = 99, log2(1 + 3) = 2, log10(1 + 99) = 2,
         * 1/sqrt(4) = 1/2. */
        put32(a, 0x40400000u);                       /* 3.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40e00000u && f4 == 0,
              "exp2m1(3) = 7 EXACTLY");
        put32(a, 0xc0400000u);                       /* -3.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf600000u && f4 == 0,
              "exp2m1(-3) = -7/8 EXACTLY");
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "exp2m1(-0) = -0, silent");
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "exp10(-0) = 1, silent");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x42c80000u && f4 == 0,
              "exp10(2) = 100 EXACTLY");
        st = cft_exp10m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x42c60000u && f4 == 0,
              "exp10m1(2) = 99 EXACTLY");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && f4 == CFT_FLAG_INEXACT,
              "exp10(-1) is INEXACT: 10^-1 is not a dyadic rational");
        put32(a, 0x40400000u);                       /* 3.0f */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f4 == 0,
              "log2p1(3) = 2 EXACTLY: 1 + x is a power of two");
        put32(a, 0xbf000000u);                       /* -0.5f */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf800000u && f4 == 0,
              "log2p1(-1/2) = -1 EXACTLY: 1 + x is formed on the encoding");
        put32(a, 0x42c60000u);                       /* 99.0f */
        st = cft_log10p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f4 == 0,
              "log10p1(99) = 2 EXACTLY");
        put32(a, 0x40800000u);                       /* 4.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f4 == 0,
              "rSqrt(4) = 1/2 EXACTLY: an EVEN power of two");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && f4 == CFT_FLAG_INEXACT,
              "rSqrt(2) is INEXACT: an odd power of two is not");

        /* exp2m1's exact table runs to |n| = p+1, and p+1 lands on a
         * MIDPOINT - which is exactly why it must be decided by exact
         * arithmetic: no enclosure ever separates a midpoint from
         * either side. Past it the value is still known exactly and is
         * delivered by a SIDE. */
        put32(a, 0x41c00000u);                       /* 24.0f = p */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4b7fffffu && f4 == 0,
              "exp2m1(24) = 2^24 - 1 EXACTLY at binary32");
        put32(a, 0x41c80000u);                       /* 25.0f = p+1 */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c000000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(25) is the midpoint 2^25 - 1, ties to even");
        put32(a, 0x41d00000u);                       /* 26.0f = p+2 */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(26) to nearest is 2^26: the side above the midpoint");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c7fffffu &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(26) toward zero is nextDown(2^26)");
        put32(a, 0xc1d00000u);                       /* -26.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(-26) to nearest is -1: inside the half gap above it");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf7fffffu &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(-26) toward zero steps off -1");

        /* The three rows where this contract follows the standard and
         * MPFR 4.2.2 does not. Each was measured on this host before it
         * was written down; docs/TRANSCENDENTALS.md quotes the probe. */
        put32(a, 0x00000000u);                       /* +0.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "rSqrt(+0) = +inf with divideByZero");
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "rSqrt(-0) = MINUS inf: 9.2.1 keeps the sign, mpfr_rec_sqrt "
              "does not");
        put32(a, 0x3f800000u);                       /* 1.0f */
        put32(b, 0x7fc00000u);                       /* qNaN */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == 0,
              "powr(1, qNaN) is a quiet NaN: the standard's row is "
              "\"for FINITE y\"");
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "pow(1, qNaN) is 1 - which is why powr is a second function");
        put32(a, 0xc0000000u);                       /* -2.0f */
        nn[0] = 0;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "compound(-2, 0) is INVALID: the row is \"1 for x >= -1\"");
        put32(a, 0x7fc00000u);                       /* qNaN */
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "compound(qNaN, 0) is 1: the same row says \"or quiet NaN\"");

        /* The rest of 9.2.1's rows for the four powers. */
        put32(a, 0x7fc00000u);                       /* qNaN */
        nn[0] = 0;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "pown(qNaN, 0) = 1");
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "rootn(qNaN, 0) is INVALID: zero is outside the domain for "
              "every x");
        put32(a, 0x80000000u);                       /* -0.0f */
        nn[0] = -3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "pown(-0, -3) = -inf with divideByZero: n is ODD");
        nn[0] = -2;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "pown(-0, -2) = PLUS inf: n is even");
        put32(a, 0xc0000000u);                       /* -2.0f */
        nn[0] = 3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xc1000000u && f4 == 0,
              "pown(-2, 3) = -8 EXACTLY");
        put32(a, 0xbf800000u);                       /* -1.0f */
        nn[0] = -3;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "compound(-1, -3) = +inf with divideByZero");
        nn[0] = 3;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f4 == 0,
              "compound(-1, 3) = +0, silent");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f4 == 0,
              "compound(1, 3) = 8 EXACTLY");
        put32(a, 0x00000000u);                       /* +0.0f */
        put32(b, 0x00000000u);
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "powr(+0, +0) is INVALID where pow(+0, +0) is 1");
        put32(a, 0xbf800000u);                       /* -1.0f */
        put32(b, 0x40000000u);                       /* 2.0f */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "powr(-1, 2) is INVALID: powr's domain excludes a negative "
              "base");
        put32(a, 0x40000000u);                       /* 2.0f */
        put32(b, 0x40400000u);                       /* 3.0f */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f4 == 0,
              "powr(2, 3) = 8 EXACTLY");

        /* rootn(x, 2) is squareRoot on every input but one, and the
         * exception is the standard's own NOTE. Both are asked here,
         * side by side, so the difference is asserted rather than
         * skipped. */
        put32(a, 0x80000000u);                       /* -0.0f */
        nn[0] = 2;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f4 == 0,
              "rootn(-0, 2) = PLUS zero (the even-n row)");
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "squareRoot(-0) = MINUS zero - the one input where the two "
              "differ, and 9.2.1 says so");
        nn[0] = 3;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "rootn(-0, 3) = -0: n is odd");
        put32(a, 0x40000000u);                       /* 2.0f */
        nn[0] = 2;
        st = cft_rootn(dev, CFT_FP32, CFT_RTZ, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f4 == CFT_FLAG_INEXACT,
              "rootn(2, 2) toward zero is sqrt(2) correctly rounded");
        st = cft_sqrt(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f4 == CFT_FLAG_INEXACT,
              "and cft_sqrt agrees, bits and flags");
        put32(a, 0xc1000000u);                       /* -8.0f */
        nn[0] = 3;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xc0000000u && f4 == 0,
              "rootn(-8, 3) = -2 EXACTLY: a perfect cube, and n is odd");
        put32(a, 0x00000001u);                       /* min subnormal */
        nn[0] = 1;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u && f4 == 0,
              "rootn(x, 1) = x EXACTLY, subnormal and silent");

        /* One case from every neighbour family in this set - and, just
         * as loudly, from the families that have NONE. exp2m1, exp10m1,
         * log2p1 and log10p1 of the smallest subnormal are 0.693x,
         * 2.303x, 1.443x and 0.434x: four different answers, none of
         * them x, which is what "no tiny-argument rule here" means. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "exp2m1(min subnormal) is 0.693x: one subnormal to nearest");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RDN, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "and downward it is +0 - so it is NOT beside its argument");
        st = cft_exp10m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "exp10m1(min subnormal) is 2.303x: TWO subnormals");
        st = cft_log2p1(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log2p1(min subnormal) is 1.443x: two subnormals upward");
        st = cft_log10p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log10p1(min subnormal) is 0.434x: +0, below half a subnormal");
        put32(a, 0x30800000u);                       /* 2^-30 */
        st = cft_exp10(dev, CFT_FP32, CFT_RDN, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp10(2^-30) downward is 1 - the rule beside 1 that DOES "
              "apply");
        st = cft_exp10(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it is nextUp(1)");
        put32(a, 0x4e800000u);                       /* 2^30 */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41f00000u &&
              f4 == CFT_FLAG_INEXACT,
              "log2p1(2^30) to nearest is 30: an exponentially small step "
              "above a grid point");
        st = cft_log2p1(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41f00001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it is nextUp(30) - the side is the whole answer");
        nn[0] = 1;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4e800000u &&
              f4 == CFT_FLAG_INEXACT,
              "compound(2^30, 1) to nearest is 2^30: 1 is far inside its "
              "gap");
        st = cft_compound(dev, CFT_FP32, CFT_RUP, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4e800001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it steps off it");

        /* The integer operand is read PER ELEMENT. An implementation
         * that hoisted it out of the batch loop passes every test above
         * and fails this one. */
        put32(av + 0, 0x40000000u);                  /* 2.0f */
        put32(av + 4, 0x40000000u);
        put32(av + 8, 0x40000000u);
        nn[0] = 1; nn[1] = 2; nn[2] = 3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, av, nn, dv, 3, &f4);
        CHECK(st == CFT_OK && get32(dv + 0) == 0x40000000u &&
              get32(dv + 4) == 0x40800000u &&
              get32(dv + 8) == 0x41000000u && f4 == 0,
              "pown over a batch reads n per element: 2, 4, 8");
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

    /* --- the augmented arithmetic operations (754-2019 9.5) -------
     *
     * host/tests/augmented_check.py proves these against the model at
     * scale and the published sets replay them; what belongs HERE is
     * this file's charter - refusals, aliasing, and the rows whose
     * expected bits come from reading 9.5 rather than from either
     * implementation.
     *
     * Every anchor below is derivable with the subclause open:
     *
     *  - THE TIE. (1 + 2^-23) + 2^-24 is 1 + 3*2^-24, exactly halfway
     *    between 1 + 2^-23 and 1 + 2^-22. 9.5 delivers "the one with
     *    smaller magnitude", so r is 1 + 2^-23 = 0x3f800001 and the
     *    residual is 2^-24 = 0x33800000. roundTiesToEven would step UP
     *    to 0x3f800002, because the lower neighbour's last bit is odd -
     *    which is why this exact case is the one that separates a
     *    conforming implementation from a plausible one, and why it is
     *    asserted here at binary32 and binary64 both.
     *  - THE OVERFLOW THRESHOLD. 9.5: an infinitely precise result
     *    "with magnitude equal to b^emax x (b - 1/2 b^(1-p)) shall
     *    round to b^emax x (b - b^(1-p))". At binary32 that midpoint is
     *    maxfinite + 2^103, and it lands on maxfinite raising NOTHING,
     *    since inexact is signalled "only when roundTiesTowardZero
     *    overflows". One ulp higher (2^104) is past it, and both
     *    outputs become +infinity with overflow and inexact.
     *  - UNDERFLOW WITHOUT INEXACT. 1 + 2^-149 has an exact residual of
     *    2^-149, which is non-zero and strictly inside +-2^emin, so the
     *    underflow flag rises alone - a combination no other operation
     *    in this library can produce.
     *  - THE ZERO SIGNS. e "is returned with the sign of
     *    roundTiesTowardZero(x + y)" when the residual is zero, so
     *    (-1) + 0 gives (-1, -0); r's own sign is 6.3's, so 1 + (-1)
     *    gives (+0, +0) and -0 - (+0) gives (-0, -0).
     */
    {
        uint8_t a[8 * 8], b[8 * 8], r[8 * 8], e[8 * 8], r2[8 * 8];
        uint32_t fl = 0xdead;
        int k;

        put32(a, 0x3f800001u);               /* 1 + 2^-23 */
        put32(b, 0x33800000u);               /* 2^-24: an exact tie */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x3f800001u &&
              get32(e) == 0x33800000u && fl == 0,
              "augmentedAddition breaks the tie toward the SMALLER "
              "magnitude (got r=0x%08x e=0x%08x fl=0x%02x)",
              (unsigned)get32(r), (unsigned)get32(e), (unsigned)fl);
        /* the same operands through ordinary addition step up, which is
         * what makes the line above a test rather than a coincidence */
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, r2, 1,
                     NULL, NULL);
        CHECK(st == CFT_OK && get32(r2) == 0x3f800002u,
              "roundTiesToEven steps up from that midpoint");

        put64(a, UINT64_C(0x3ff0000000000001));   /* 1 + 2^-52 */
        put64(b, UINT64_C(0x3ca0000000000000));   /* 2^-53 */
        st = cft_augmented_add(dev, CFT_FP64, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get64(r) == UINT64_C(0x3ff0000000000001) &&
              get64(e) == UINT64_C(0x3ca0000000000000) && fl == 0,
              "the same tie at binary64");

        put32(a, 0x7f7fffffu);               /* the largest finite */
        put32(b, 0x73000000u);               /* 2^103: half an ulp */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f7fffffu &&
              get32(e) == 0x73000000u && fl == 0,
              "exactly ON the overflow threshold: maxfinite, silently");
        put32(b, 0x73800000u);               /* 2^104: one ulp */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f800000u &&
              get32(e) == 0x7f800000u &&
              fl == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "past it: +infinity in BOTH outputs, overflow and inexact");

        put32(a, 0x3f800000u);               /* 1.0 */
        put32(b, 0x00000001u);               /* 2^-149 */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x3f800000u &&
              get32(e) == 0x00000001u && fl == CFT_FLAG_UNDERFLOW,
              "a subnormal residual raises underflow and NOT inexact");
        st = cft_augmented_mul(dev, CFT_FP32, b, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0 && get32(e) == 0 &&
              fl == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "a product residual the format cannot hold: both raised");

        put32(a, 0xbf800000u);               /* -1.0 */
        put32(b, 0x00000000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0xbf800000u &&
              get32(e) == 0x80000000u && fl == 0,
              "a zero error term takes the sign of r, not of the sum");
        put32(b, 0x3f800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0 && get32(e) == 0 && fl == 0,
              "exact cancellation is +0 in both outputs (6.3)");
        put32(a, 0x80000000u);
        put32(b, 0x00000000u);
        st = cft_augmented_sub(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x80000000u &&
              get32(e) == 0x80000000u && fl == 0,
              "-0 - (+0) is (-0, -0)");

        put32(a, 0x7f800000u);
        put32(b, 0xff800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "inf + (-inf): the same quiet NaN for both outputs");
        put32(a, 0x7f800001u);               /* a signaling NaN */
        put32(b, 0x3f800000u);
        st = cft_augmented_mul(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "a signaling NaN propagates as both results, invalid raised");
        put32(a, 0x7f800000u);
        put32(b, 0x00000000u);
        st = cft_augmented_mul(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "inf * 0 likewise");
        put32(a, 0x7f800000u);
        put32(b, 0x3f800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f800000u &&
              get32(e) == 0x7f800000u && fl == 0,
              "an infinite OPERAND signals nothing - only overflow does");

        /* refusals and aliasing, this file's charter */
        put32(a, 0x3f800000u);
        put32(b, 0x40000000u);
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, r, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT,
              "r and e must not be the same buffer");
        CHECK(cft_augmented_mul(dev, CFT_FP32, NULL, b, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "a is not optional");
        CHECK(cft_augmented_sub(dev, CFT_FP32, a, NULL, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "b is not optional");
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, NULL, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "r is not optional");
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, NULL, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "e is not optional");
        CHECK(cft_augmented_add(dev, (cft_format)9, a, b, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "a bad format is refused");
        fl = 0xdead;
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, e, 0, &fl)
              == CFT_OK && fl == 0, "n = 0 succeeds with clean flags");

        for (k = 0; k < 8; k++) {
            put32(a + 4 * k, 0x3f800000u + (uint32_t)k);
            put32(b + 4 * k, 0x33800000u + (uint32_t)k);
        }
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 8, &fl);
        CHECK(st == CFT_OK, "augmented batch, separate buffers");
        memcpy(r2, a, 32);
        st = cft_augmented_add(dev, CFT_FP32, r2, b, r2, e, 8, &fl);
        CHECK(st == CFT_OK && memcmp(r2, r, 32) == 0,
              "r may alias a: each element is read before it is written");
    }

    /* --- the rest of clause 9.4 ----------------------------------
     *
     * sumSquare, sumAbs and the three scaled products. Each claim the
     * header makes gets a check, and the two that are worth doubting -
     * "the same tree, so the composition is the answer" and "this
     * cannot overflow" - get a NEGATIVE CONTROL beside them, because a
     * property that holds for boring reasons is not evidence.
     */
    {
        uint8_t v[4 * 4], w[4 * 4], d[4], d2[4];
        uint32_t f2 = 0, f3 = 0;
        int64_t scale = -12345;

        CHECK(strcmp(cft_op_name(CFT_SUMSQ), "sumsq") == 0 &&
              strcmp(cft_op_name(CFT_SUMABS), "sumabs") == 0,
              "the two new reduction opcodes are named");
        CHECK(strcmp(cft_op_name((cft_op)30), "reserved") == 0,
              "30 is the first unassigned opcode now");
        CHECK(cft_supports(dev, CFT_SUMSQ, CFT_FP256) == 1 &&
              cft_supports(dev, CFT_SUMABS, CFT_FP32) == 1,
              "software backend carries the composed reductions");
        CHECK(cft_supports(dev, (cft_op)30, CFT_FP32) == 0,
              "op 30 unassigned");

        /* sumSquare([3, 4]) = 9 + 16 = 25, exactly. */
        put32(v, 0x40400000u);          /* 3.0 */
        put32(v + 4, 0x40800000u);      /* 4.0 */
        st = cft_reduce(dev, CFT_SUMSQ, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x41c80000u && f2 == 0,
              "sumsq([3,4]) = 25 exactly: %s 0x%08x/0x%02x",
              cft_strerror(st), get32(d), (unsigned)f2);
        /* the identity, on the same bytes: it IS the dot over (a, a) */
        st = cft_reduce(dev, CFT_DOT, CFT_FP32, CFT_RNE, v, v, d2, 2,
                        &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == get32(d) && f3 == f2,
              "sumsq == dot(a, a)");

        /* sumAbs([-3, 4]) = 7, and the same as an abs pass then a sum */
        put32(v, 0xc0400000u);          /* -3.0 */
        st = cft_reduce(dev, CFT_SUMABS, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40e00000u && f2 == 0,
              "sumabs([-3,4]) = 7: %s 0x%08x/0x%02x",
              cft_strerror(st), get32(d), (unsigned)f2);
        st = cft_run(dev, CFT_ABS, CFT_FP32, CFT_RNE, v, NULL, NULL, w, 2,
                     &f3, NULL);
        if (st == CFT_OK)
            st = cft_reduce(dev, CFT_SUM, CFT_FP32, CFT_RNE, w, NULL, d2, 2,
                            &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == get32(d) && f3 == f2,
              "sumabs == abs pass then sum");

        /* 9.4 puts an infinity AHEAD of a NaN for these two, which the
         * tree cannot do - and the NEGATIVE CONTROL is the same vector
         * through the plain dot, which returns the quiet NaN. */
        put32(v, 0x7f800000u);          /* +inf */
        put32(v + 4, 0x7fc00000u);      /* quiet NaN */
        st = cft_reduce(dev, CFT_SUMSQ, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f2 == 0,
              "sumsq(inf, NaN) is +inf with no flag: 0x%08x/0x%02x",
              get32(d), (unsigned)f2);
        st = cft_reduce(dev, CFT_SUMABS, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f2 == 0,
              "sumabs(inf, NaN) is +inf");
        st = cft_reduce(dev, CFT_DOT, CFT_FP32, CFT_RNE, v, v, d2, 2,
                        &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == 0x7fc00000u,
              "NEGATIVE CONTROL: the plain dot returns the quiet NaN "
              "there, so the override is doing real work (0x%08x)",
              get32(d2));

        /* scaledProd of four copies of 2^100: the true product is
         * 2^400, hundreds of binades outside fp32, and it comes back
         * as (1.0, 400) with no flag at all. */
        put32(v, 0x71800000u);
        put32(v + 4, 0x71800000u);
        put32(v + 8, 0x71800000u);
        put32(v + 12, 0x71800000u);
        f2 = 0xdead;
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 4, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 400 &&
              f2 == 0,
              "scaledProd(2^100 x 4) = (1.0, 400) silently: %s "
              "0x%08x/%lld/0x%02x", cft_strerror(st), get32(d),
              (long long)scale, (unsigned)f2);
        /* the NEGATIVE CONTROL: the same operands through the multiply
         * this composes from overflow to +inf on the FIRST pair. */
        f3 = 0;
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, v, v, NULL, d2, 1,
                     &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == 0x7f800000u &&
              (f3 & CFT_FLAG_OVERFLOW),
              "NEGATIVE CONTROL: 2^100 * 2^100 overflows to +inf with "
              "the overflow flag (0x%08x/0x%02x)", get32(d2),
              (unsigned)f3);

        /* the empty vector: 9.4 fixes it at pr = 1, sf = +0, silent */
        scale = -1;
        f2 = 0xdead;
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, NULL, d, &scale, 0,
                             &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 0 &&
              f2 == 0, "scaledProd of nothing is (1.0, 0), silently");

        /* the special-value rows, in 9.4's order */
        put32(v, 0x7f800000u);          /* +inf */
        put32(v + 4, 0x00000000u);      /* +0   */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u && scale == 0 &&
              f2 == CFT_FLAG_INVALID,
              "inf x 0 is invalid and the canonical quiet NaN");
        put32(v + 4, 0xc0000000u);      /* -2.0 */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f2 == 0,
              "an infinity with no zero takes the product's sign, "
              "silently");
        put32(v, 0x80000000u);          /* -0 */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f2 == 0,
              "-0 x -2 is +0, silently");

        /* scaledProdSum / Diff: one rounding for the leaf, then the
         * same tree. (1+1) * (3+1) = 8 -> (1.0, 3). */
        put32(v, 0x3f800000u); put32(v + 4, 0x40400000u);
        put32(w, 0x3f800000u); put32(w + 4, 0x3f800000u);
        st = cft_scaled_prod_sum(dev, CFT_FP32, CFT_RNE, v, w, d, &scale, 2,
                                 &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 3 &&
              f2 == 0, "scaledProdSum = (1.0, 3): 0x%08x/%lld/0x%02x",
              get32(d), (long long)scale, (unsigned)f2);
        /* (1-1) * (3-1): a zero factor, so a zero result */
        st = cft_scaled_prod_diff(dev, CFT_FP32, CFT_RNE, v, w, d, &scale, 2,
                                  &f2);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && scale == 0 &&
              f2 == 0, "scaledProdDiff with a zero factor is +0");

        /* the refusals: an output the caller cannot receive is an
         * error, not a silent partial answer */
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, NULL, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL pr refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, NULL, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL scale refused");
        CHECK(cft_scaled_prod(NULL, CFT_FP32, CFT_RNE, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL device refused");
        CHECK(cft_scaled_prod(dev, (cft_format)4, CFT_RNE, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "bad format refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, (cft_round)5, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "bad rounding attribute refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, NULL, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "a non-empty call with no vector is refused");
        CHECK(cft_scaled_prod_sum(dev, CFT_FP32, CFT_RNE, v, NULL, d,
                                  &scale, 2, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "scaledProdSum needs b");
    }

    /* --- the character conversions and the payload operations ------
     *
     * Part of the 0.6 step. character_check.py proves these against the
     * model at scale and the vectors replay them; what belongs HERE is
     * this file's charter - the refusals, the sizing protocol, the
     * aliasing rule, and a handful of results whose expected bits and
     * characters come from reading 754-2019 clauses 5.12 and 9.7 by
     * hand rather than from running either implementation.
     *
     * Ending with a NEGATIVE CONTROL, because the headline claim here
     * is a round trip, and a round trip is the easiest property in this
     * library to pass for the wrong reason: an implementation that
     * quietly ignored the digit count and always wrote the exact value
     * would satisfy every round-trip check ever written. So the last
     * block asserts that the round trip FAILS one digit below Pmin -
     * which it can only do if the digit count is being honoured.
     */
    {
        uint8_t a[8], d[8];
        char text[64];
        const char *in[4];
        size_t need = 0, bad = 0;
        uint32_t f4 = 0xdead;
        cft_status s2;

        /* Pmin(bf) = 1 + ceiling(p * log10 2). 5.12.2 lists 9, 17 and
         * 36 for the first three rungs; 73 is the same formula at
         * p = 237. */
        CHECK(cft_format_decimal_digits(CFT_FP32) == 9 &&
              cft_format_decimal_digits(CFT_FP64) == 17 &&
              cft_format_decimal_digits(CFT_FP128) == 36 &&
              cft_format_decimal_digits(CFT_FP256) == 73,
              "Pmin per 5.12.2");
        CHECK(cft_format_decimal_digits((cft_format)9) == 0,
              "Pmin of an unknown format is 0");

        /* -- reading a sequence in -- */
        in[0] = "1.5";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, &bad,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3fc00000u && f4 == 0,
              "1.5 is exact in binary32 and raises nothing");
        in[0] = "0.1";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3dcccccdu &&
              f4 == CFT_FLAG_INEXACT, "0.1 to nearest is 0x3dcccccd");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3dccccccu &&
              f4 == CFT_FLAG_INEXACT, "0.1 toward zero is one ulp below");
        /* 2^24 + 1 is exactly halfway between 2^24 and 2^24 + 2, so
         * the attribute alone decides it - ties-to-even takes the even
         * significand, ties-to-away the other one. */
        in[0] = "16777217";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x4b800000u &&
              f4 == CFT_FLAG_INEXACT, "2^24+1 ties to even");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RMM, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x4b800001u &&
              f4 == CFT_FLAG_INEXACT, "2^24+1 ties away");
        /* Below half the smallest subnormal in magnitude, so the
         * result is decided by the attribute's side and both the tiny
         * and the inexact flags rise (7.5). */
        in[0] = "1e-45";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x00000001u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "1e-45 rounds up to the smallest subnormal, tiny+inexact");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "1e-45 toward zero is +0, still tiny+inexact");
        /* Overflow delivers per 7.4's table, exactly as any arithmetic
         * result does - an infinity to nearest, the largest finite
         * magnitude toward zero. */
        in[0] = "3.5e38";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "3.5e38 overflows to +inf");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f7fffffu &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "3.5e38 toward zero delivers maxfinite");
        /* An exponent no arithmetic could reach still has a defined
         * answer: the library decides the band without computing
         * 10^999999999999. */
        in[0] = "-1e999999999999";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0xff800000u &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "an absurd exponent overflows rather than hanging");
        in[0] = "-1e-999999999999";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x80000000u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "and an absurd negative one underflows to -0");
        /* A zero decimal is a zero and rounding never changes a sign
         * (6.3), so the minus survives in every attribute. */
        in[0] = "-0.000";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RUP, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "-0.000 is -0 even rounding upward");

        /* -- the 5.12.1 words, both directions -- */
        in[0] = "-INFINITY";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0xff800000u && f4 == 0,
              "-INFINITY, case insensitive, raises nothing");
        in[0] = "snan(0x1)";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f800001u && f4 == 0,
              "a signaling NaN reads back signaling, and raises NOTHING - "
              "5.12 exempts these conversions from the sNaN rule");
        in[0] = "NaN(0X5)";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7fc00005u && f4 == 0,
              "a payload suffix is read in either case");

        /* -- writing a sequence out -- */
        put32(a, 0x3f800000u);                            /* 1.0f */
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1e+0") == 0 && need == 5 &&
              f4 == 0, "the exact decimal of 1 is 1e+0");
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1.00000000e+0") == 0 && f4 == 0,
              "nine digits of 1 keeps its trailing zeros and stays exact");
        put32(a, 0x3dcccccdu);                            /* the 0.1f above */
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && f4 == 0 &&
              strcmp(text, "1.00000001490116119384765625e-1") == 0,
              "the EXACT decimal of the nearest float to 0.1, all of it");
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1.00000001e-1") == 0 &&
              f4 == CFT_FLAG_INEXACT,
              "nine digits of it drops something, so inexact");
        put32(a, 0x80000000u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 17, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "-0") == 0 && f4 == 0,
              "a zero is -0 at every digit count - it has no digits to pad");
        put32(a, 0x7f800001u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "snan(0x1)") == 0 && f4 == 0,
              "a signaling NaN writes snan and signals nothing");
        put32(a, 0x7fc00005u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "nan(0x5)") == 0,
              "a quiet NaN carries its payload out");

        /* -- hexadecimal (5.12.3) -- */
        put32(a, 0x40400000u);                            /* 3.0f */
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "0x1.8p+1") == 0,
              "the shortest exact hex of 3 is 0x1.8p+1");
        put32(a, 0x00000001u);
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "0x1p-149") == 0,
              "a subnormal prints with its TRUE exponent, not a leading 0");
        put32(a, 0x80000000u);
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "-0x0p+0") == 0, "-0 in hex");
        in[0] = "0x1.8p+0";
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3fc00000u && f4 == 0,
              "0x1.8p+0 is 1.5 exactly");
        /* One hex digit more than binary32 holds: 0x1.000001p+0 is
         * 1 + 2^-24, exactly halfway to the next float, so ties-to-even
         * takes 1 and toward-positive takes its successor. */
        in[0] = "0x1.000001p+0";
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3f800000u &&
              f4 == CFT_FLAG_INEXACT, "a hex tie rounds to even");
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RUP, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3f800001u &&
              f4 == CFT_FLAG_INEXACT, "the same tie upward is nextUp(1)");

        /* -- refusals: a status, never a guess -- */
        {
            static const char *const bad_seq[] = {
                "", "+", ".", "1e", "1 ", " 1", "1.5.5", "1,5", "0x1p+0",
                "nan()", "nan(0x)", "nan(0x400000)", "1_000", NULL
            };
            int k2;
            for (k2 = 0; bad_seq[k2]; k2++) {
                in[0] = bad_seq[k2];
                CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                            NULL, &f4)
                      == CFT_ERR_INVALID_ARGUMENT,
                      "refused: %s", bad_seq[k2]);
            }
        }
        in[0] = "1.5";                     /* decimal is not hexadecimal */
        CHECK(cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4)
              == CFT_ERR_INVALID_ARGUMENT,
              "the hex parser refuses a decimal sequence");
        in[0] = "0x1.8";                   /* 5.12.3 requires an exponent */
        CHECK(cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4)
              == CFT_ERR_INVALID_ARGUMENT,
              "5.12.3's grammar requires the binary exponent");
        /* Which element failed, because a caller reading a file of
         * numbers needs the line and not just the verdict. */
        in[0] = "1"; in[1] = "2"; in[2] = "oops"; in[3] = "4";
        bad = 99;
        CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 4, &bad,
                                    &f4) == CFT_ERR_INVALID_ARGUMENT &&
              bad == 2, "the refusal names the element");

        /* -- the sizing protocol: a short buffer is a status, and the
         * buffer is not touched. A truncated number is a wrong answer
         * that looks like a right one. -- */
        put32(a, 0x3dcccccdu);
        need = 0;
        CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, NULL, 0,
                                  &need, &f4) == CFT_ERR_INVALID_ARGUMENT &&
              need == 32,
              "cap 0 asks for the size: 31 characters and a NUL");
        memset(text, 'Z', sizeof text);
        CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                  need - 1, &need, &f4)
              == CFT_ERR_INVALID_ARGUMENT && text[0] == 'Z',
              "one byte short refuses and writes NOTHING");

        /* -- the 9.7 payload operations (they signal nothing) -- */
        put32(a, 0x7fc00005u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x40a00000u,
              "getPayload of a NaN carrying 5 is the float 5");
        put32(a, 0x3f800000u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0xbf800000u,
              "getPayload of a non-NaN is -1, which is 9.7's own answer");
        put32(a, 0x40a00000u);                            /* 5.0f */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7fc00005u, "setPayload(5) is a quiet NaN");
        CHECK(cft_set_payload_signaling(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7f800005u,
              "setPayloadSignaling(5) is the signaling form");
        put32(a, 0x4a800000u);                            /* 2^22 */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u,
              "2^22 is one past what binary32's payload field holds: +0");
        put32(a, 0x80000000u);                            /* -0 */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7fc00000u,
              "-0 is the integer zero by value, so setPayload takes it");
        CHECK(cft_set_payload_signaling(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u,
              "but payload 0 cannot be signaling - that encoding is an "
              "infinity - so setPayloadSignaling(-0) is +0");
        put32(a, 0x3fc00000u);                            /* 1.5, not an int */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u, "a non-integer operand gives +0");
        put32(a, 0xc0a00000u);                            /* -5.0f */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u, "a negative operand gives +0");
        /* d may alias a. */
        put32(a, 0x7fc00003u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, a, 1) == CFT_OK &&
              get32(a) == 0x40400000u, "getPayload in place");
        CHECK(cft_set_payload(dev, CFT_FP32, a, a, 1) == CFT_OK &&
              get32(a) == 0x7fc00003u, "setPayload in place, and back again");

        /* -- THE NEGATIVE CONTROL --
         *
         * 0x417ffff5 and 0x417ffff6 are neighbouring binary32
         * encodings just below 16. At Pmin = 9 digits they write
         * different sequences and each reads back to itself, which is
         * 5.12.2's guarantee. At 8 - one digit short - they write the
         * SAME sequence, so reading it back cannot recover both, and
         * this asserts that it does not. An implementation that
         * ignored the digit count and always wrote the exact value
         * would pass every round-trip check above and fail here, which
         * is the only reason this block exists.
         */
        {
            char nine_a[64], nine_b[64], eight_a[64], eight_b[64];
            uint32_t bits_a = 0x417ffff5u, bits_b = 0x417ffff6u;
            uint32_t back_a, back_b;

            put32(a, bits_a);
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, nine_a,
                                      sizeof nine_a, &need, &f4) == CFT_OK,
                  "nine digits of 0x417ffff5");
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 8, eight_a,
                                      sizeof eight_a, &need, &f4) == CFT_OK,
                  "eight digits of 0x417ffff5");
            put32(a, bits_b);
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, nine_b,
                                      sizeof nine_b, &need, &f4) == CFT_OK,
                  "nine digits of 0x417ffff6");
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 8, eight_b,
                                      sizeof eight_b, &need, &f4) == CFT_OK,
                  "eight digits of 0x417ffff6");

            CHECK(strcmp(nine_a, nine_b) != 0,
                  "at Pmin the two neighbours write different sequences");
            in[0] = nine_a;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            back_a = get32(d);
            in[0] = nine_b;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            back_b = get32(d);
            CHECK(back_a == bits_a && back_b == bits_b,
                  "5.12.2: Pmin digits under a nearest attribute round trip");

            CHECK(strcmp(eight_a, eight_b) == 0,
                  "at Pmin - 1 the two neighbours COLLIDE (%s vs %s)",
                  eight_a, eight_b);
            in[0] = eight_a;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            CHECK(get32(d) != bits_a || get32(d) != bits_b,
                  "one sequence cannot name two encodings");
            CHECK((get32(d) == bits_a) != (get32(d) == bits_b),
                  "so at Pmin - 1 the round trip loses one of them - which "
                  "is the control: an implementation ignoring the digit "
                  "count would recover both");
        }
    }

    /* --- the status word (7.1, 5.7.4), the conformance predicates
     *     (5.7.1), and 9.6's magnitude forms          (ABI 0.7)
     *
     * The word is state, so nothing in the vectors can express it and
     * nothing in the golden model corresponds to it. Every check below
     * is against a sentence of the standard, quoted where it bites.
     * ------------------------------------------------------------- */
    {
        uint8_t a[4], b[4], d[4];
        uint32_t f = 0, saved;

        /* 5.7.1. Constants, and what each rests on is in cft.h. */
        CHECK(cft_is754version1985() == 0, "1985 is not asserted");
        CHECK(cft_is754version2008() == 0,
              "2008 is not asserted: its 5.3.1 required minNum/maxNum, "
              "which 2019 replaced with 9.6's");
        CHECK(cft_is754version2019() == 1, "2019 IS asserted from 0.7");

        /* The whole-set mask is the five flags and nothing else. */
        CHECK(CFT_FLAGS_ALL == (uint32_t)(CFT_FLAG_INVALID |
                                          CFT_FLAG_DIVBYZERO |
                                          CFT_FLAG_OVERFLOW |
                                          CFT_FLAG_UNDERFLOW |
                                          CFT_FLAG_INEXACT),
              "CFT_FLAGS_ALL is every exception this library defines");

        /* 7.1: "A program that does not inherit status flags from
         * another source begins execution with all status flags
         * lowered." This device has done a great deal by now, so
         * lower them first and treat that as the starting point. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == 0, "lowered means zero");
        CHECK(cft_test_flags(dev, CFT_FLAGS_ALL) == 0,
              "and testFlags agrees");

        /* ACCUMULATION ACROSS CALLS. Each of these raises something
         * different; nothing between them lowers anything; so the word
         * is the union at every step. The values are 754's, not either
         * implementation's: max + max overflows (and 7.4 makes that
         * inexact too), 1/0 is divideByZero (7.3), and an sNaN into
         * nextUp is invalid (5.3.1: "nextUp(x) is quiet except for
         * signaling NaNs"). */
        put32(a, 0x7f7fffffu);                  /* max normal fp32 */
        put32(b, 0x7f7fffffu);
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, d, 1,
                      &f, NULL) == CFT_OK, "add");
        CHECK(f == (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "max + max overflows inexactly, got 0x%02x", (unsigned)f);
        CHECK(cft_save_all_flags(dev) == f,
              "the first call's flags are the whole word");

        put32(a, 0x3f800000u);                  /* 1.0 */
        put32(b, 0x00000000u);                  /* +0  */
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f, NULL)
              == CFT_OK, "div");
        CHECK(f == (uint32_t)CFT_FLAG_DIVBYZERO,
              "1/0 signals divideByZero and NOTHING else - the Newton "
              "scaffolding's inexact must not leak, got 0x%02x",
              (unsigned)f);
        CHECK(cft_save_all_flags(dev) ==
              (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT |
                         CFT_FLAG_DIVBYZERO),
              "and the word is the union of the two calls: 0x%02x",
              (unsigned)cft_save_all_flags(dev));

        put32(a, 0x7fa00000u);                  /* a signaling NaN */
        CHECK(cft_next_up(dev, CFT_FP32, a, d, 1, &f) == CFT_OK, "nextUp");
        CHECK(f == (uint32_t)CFT_FLAG_INVALID, "nextUp(sNaN) is invalid");
        CHECK(cft_save_all_flags(dev) ==
              (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT |
                         CFT_FLAG_DIVBYZERO | CFT_FLAG_INVALID),
              "four flags standing after three calls");

        /* A CALL THAT RAISES NOTHING LEAVES THE WORD ALONE. Not
         * "leaves it mostly alone": exactly as it stood. 1 + 1 is
         * exact, and cft_class is non-computational (5.7.2) and
         * signals nothing at all, not even on the sNaN below. */
        saved = cft_save_all_flags(dev);
        put32(a, 0x3f800000u);
        put32(b, 0x3f800000u);
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, d, 1,
                      &f, NULL) == CFT_OK, "add");
        CHECK(f == 0 && get32(d) == 0x40000000u, "1 + 1 = 2, exactly");
        CHECK(cft_save_all_flags(dev) == saved,
              "an exact call changes no flag");
        {
            uint8_t cls = 0xff;
            put32(a, 0x7fa00000u);
            CHECK(cft_class(dev, CFT_FP32, a, &cls, 1) == CFT_OK, "class");
            CHECK(cls == CFT_CLASS_SNAN, "and it IS a signaling NaN");
            CHECK(cft_save_all_flags(dev) == saved,
                  "which class reports without signalling (5.7.2)");
        }

        /* THE PER-ELEMENT UNION. One batch call whose four elements
         * each raise something different puts all four in the word at
         * once - the same OR the call returns. */
        {
            uint8_t va[16], vb[16], vd[16];
            uint32_t want = (uint32_t)(CFT_FLAG_OVERFLOW |
                                       CFT_FLAG_UNDERFLOW |
                                       CFT_FLAG_INEXACT |
                                       CFT_FLAG_INVALID);
            put32(va + 0,  0x7f7fffffu); put32(vb + 0,  0x7f7fffffu);
            put32(va + 4,  0x00000001u); put32(vb + 4,  0x3eaaaaabu);
            put32(va + 8,  0x3f800000u); put32(vb + 8,  0x3f800000u);
            put32(va + 12, 0x7fa00000u); put32(vb + 12, 0x3f800000u);
            cft_lower_flags(dev, CFT_FLAGS_ALL);
            CHECK(cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, va, vb, NULL,
                          vd, 4, &f, NULL) == CFT_OK, "mul x4");
            CHECK(f == want, "the batch's flags are the union of its "
                  "elements': 0x%02x want 0x%02x", (unsigned)f,
                  (unsigned)want);
            CHECK(cft_save_all_flags(dev) == want,
                  "and the word gets that same union in one call");
        }

        /* LOWER BY MASK: only the named flags go down, and testFlags is
         * 5.7.4's "whether ANY of the flags ... are raised". */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL, "raise all");
        cft_lower_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW);
        CHECK(cft_save_all_flags(dev) ==
              (CFT_FLAGS_ALL & ~(uint32_t)(CFT_FLAG_INEXACT |
                                           CFT_FLAG_UNDERFLOW)),
              "lowering two leaves the other three standing");
        CHECK(cft_test_flags(dev, CFT_FLAG_INEXACT) == 0, "inexact is down");
        CHECK(cft_test_flags(dev, CFT_FLAG_INVALID) == 1, "invalid is up");
        CHECK(cft_test_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_INVALID) == 1,
              "ANY, not all");
        CHECK(cft_test_flags(dev, 0) == 0, "the empty group tests false");

        /* RAISE BY MASK, one bit at a time. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        for (i = 0; i < 5; i++) {
            const uint32_t bit = 1u << i;
            cft_raise_flags(dev, bit);
            CHECK(cft_test_flags(dev, bit) == 1, "raised bit %d", i);
        }
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL,
              "five raises make the whole set");

        /* SAVE / RESTORE ROUND TRIP, which is what 5.7.4 says the
         * saveAllFlags result is for: "for use as the first operand to
         * a restoreFlags or testSavedFlags operation". */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAG_INVALID | CFT_FLAG_OVERFLOW);
        saved = cft_save_all_flags(dev);
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAG_INEXACT);
        cft_restore_flags(dev, saved, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == saved,
              "restore over the whole set is a round trip: 0x%02x vs "
              "0x%02x", (unsigned)cft_save_all_flags(dev),
              (unsigned)saved);

        /* restoreFlags LOWERS inside the mask as well as raising - a
         * flag that is low in `saved` comes back low - and touches
         * nothing outside it. An OR-only implementation passes the
         * round trip above and fails this. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAGS_ALL);
        cft_restore_flags(dev, 0, CFT_FLAG_INEXACT);
        CHECK(cft_save_all_flags(dev) ==
              (CFT_FLAGS_ALL & ~(uint32_t)CFT_FLAG_INEXACT),
              "restoring a low flag lowers it");
        cft_restore_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_INVALID,
                          CFT_FLAG_INEXACT);
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL,
              "and restoring a high one raises it");
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_restore_flags(dev, CFT_FLAGS_ALL, CFT_FLAG_DIVBYZERO);
        CHECK(cft_save_all_flags(dev) == (uint32_t)CFT_FLAG_DIVBYZERO,
              "outside the mask nothing moves");

        /* testSavedFlags: the same question, asked of a value the
         * caller holds. No device, so no state can affect it. */
        CHECK(cft_test_saved_flags(CFT_FLAG_INVALID | CFT_FLAG_INEXACT,
                                   CFT_FLAG_INEXACT) == 1, "saved: any");
        CHECK(cft_test_saved_flags(CFT_FLAG_INVALID,
                                   CFT_FLAG_INEXACT) == 0, "saved: none");
        CHECK(cft_test_saved_flags(0, CFT_FLAGS_ALL) == 0, "saved: empty");
        CHECK(cft_test_saved_flags(CFT_FLAGS_ALL, CFT_FLAGS_ALL) == 1,
              "saved: full");

        /* A NULL device is a word that is permanently zero, and none
         * of the six may dereference it. */
        CHECK(cft_save_all_flags(NULL) == 0, "NULL device saves 0");
        CHECK(cft_test_flags(NULL, CFT_FLAGS_ALL) == 0, "NULL tests 0");
        cft_raise_flags(NULL, CFT_FLAGS_ALL);
        cft_lower_flags(NULL, CFT_FLAGS_ALL);
        cft_restore_flags(NULL, CFT_FLAGS_ALL, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(NULL) == 0, "and still 0 afterwards");

        /* ---- 9.6's magnitude forms ------------------------------ *
         *
         * Values derived from the standard's own sentence rather than
         * from either implementation:
         *
         *   "minimumMagnitude(x, y) is x if |x| < |y|, y if |y| < |x|,
         *    otherwise minimum(x, y)."
         */
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* The magnitude decides and the sign has no vote:
         * |-1| < |+2|, so minimumMagnitude(-1, +2) is -1 even though
         * -1 is also the smaller number, and maximumMagnitude is +2. */
        put32(a, 0xbf800000u);                  /* -1.0 */
        put32(b, 0x40000000u);                  /* +2.0 */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xbf800000u && f == 0, "minimumMagnitude(-1, 2)");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40000000u && f == 0, "maximumMagnitude(-1, 2)");

        /* ... and the other way round, where it disagrees with plain
         * minimum: |+2| > |-1| makes -1 the minimum-magnitude, while
         * minimum(-1, +2) would also be -1; so use -3 and +2, where
         * minimum is -3 and minimumMagnitude is +2. */
        put32(a, 0xc0400000u);                  /* -3.0 */
        put32(b, 0x40000000u);                  /* +2.0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x40000000u,
              "minimumMagnitude(-3, 2) is +2 where minimum(-3, 2) is -3");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0xc0400000u,
              "maximumMagnitude(-3, 2) is -3 where maximum(-3, 2) is +2");

        /* EQUAL MAGNITUDES OF OPPOSITE SIGN: 9.6's "otherwise", so the
         * base operation decides, and 9.6 says "-0 compares less than
         * +0" for minimum and "+0 compares greater than -0" for
         * maximum. Both orders of the operands, because preferring x
         * or preferring y is exactly the wrong answer here. */
        put32(a, 0x40400000u);                  /* +3.0 */
        put32(b, 0xc0400000u);                  /* -3.0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xc0400000u,
              "minimumMagnitude(+3, -3) defers to minimum: -3");
        CHECK(cft_min_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xc0400000u, "and -3 whichever way round");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40400000u,
              "maximumMagnitude(+3, -3) defers to maximum: +3");
        CHECK(cft_max_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40400000u, "and +3 whichever way round");

        put32(a, 0x00000000u);                  /* +0 */
        put32(b, 0x80000000u);                  /* -0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x80000000u, "min of the two zeros is -0");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x00000000u, "max of the two zeros is +0");
        CHECK(cft_minnum_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x80000000u, "and the Number forms agree");
        CHECK(cft_maxnum_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK,
              "maxnummag");
        CHECK(get32(d) == 0x00000000u, "and the Number forms agree");

        /* NaNs: |NaN| is unordered, so every NaN case is 9.6's
         * "otherwise" and each form inherits the NaN rule of the
         * operation it names. */
        put32(a, 0x7fc00000u);                  /* quiet NaN */
        put32(b, 0x3f800000u);                  /* 1.0 */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x7fc00000u && f == 0,
              "minimumMagnitude propagates a quiet NaN, quietly");
        CHECK(cft_minnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x3f800000u && f == 0,
              "minimumMagnitudeNumber returns the number");
        put32(a, 0x7fa00000u);                  /* signaling NaN */
        CHECK(cft_maxnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "maxnummag");
        CHECK(get32(d) == 0x3f800000u && f == (uint32_t)CFT_FLAG_INVALID,
              "a signaling NaN signals invalid and is 'otherwise "
              "ignored and not converted to a quiet NaN' (9.6)");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x7fc00000u && f == (uint32_t)CFT_FLAG_INVALID,
              "where maximumMagnitude quiets it");
        put32(b, 0x7fc00000u);                  /* sNaN and qNaN */
        CHECK(cft_minnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x7fc00000u && f == (uint32_t)CFT_FLAG_INVALID,
              "two NaNs give a quiet NaN even in the Number forms");

        /* Infinities and subnormals sit on the same magnitude ladder
         * as everything else. */
        put32(a, 0xff800000u);                  /* -inf */
        put32(b, 0x00000001u);                  /* smallest subnormal */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x00000001u && f == 0,
              "the subnormal has the smaller magnitude");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0xff800000u && f == 0, "and -inf the larger");

        /* The flags of the four reach the status word like every other
         * entry point's - the check the hook's negative control
         * breaks. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put32(a, 0x7fa00000u);
        put32(b, 0x3f800000u);
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(cft_save_all_flags(dev) == (uint32_t)CFT_FLAG_INVALID,
              "cft_min_mag ORs its flags into the status word");
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* d may alias a or b: each element is read before it is
         * written, as everywhere else in this library. */
        {
            uint8_t va[8], vb[8];
            put32(va + 0, 0xc0400000u); put32(vb + 0, 0x40000000u);
            put32(va + 4, 0x00000001u); put32(vb + 4, 0x80000000u);
            CHECK(cft_max_mag(dev, CFT_FP32, va, vb, va, 2, &f) == CFT_OK,
                  "maxmag aliasing a");
            CHECK(get32(va + 0) == 0xc0400000u &&
                  get32(va + 4) == 0x00000001u, "d aliases a");
            put32(va + 0, 0xc0400000u); put32(vb + 0, 0x40000000u);
            put32(va + 4, 0x00000001u); put32(vb + 4, 0x80000000u);
            CHECK(cft_max_mag(dev, CFT_FP32, va, vb, vb, 2, &f) == CFT_OK,
                  "maxmag aliasing b");
            CHECK(get32(vb + 0) == 0xc0400000u &&
                  get32(vb + 4) == 0x00000001u, "d aliases b");
        }

        /* n == 0 is a no-op that raises nothing; a missing operand, a
         * bad format and a NULL device are refused. */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, NULL, NULL, NULL, 0, &f) == CFT_OK,
              "n == 0 is OK");
        CHECK(f == 0, "and raises nothing");
        CHECK(cft_max_mag(dev, CFT_FP32, a, NULL, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "b is required");
        CHECK(cft_minnum_mag(dev, (cft_format)9, a, b, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "bad format is refused");
        CHECK(cft_maxnum_mag(NULL, CFT_FP32, a, b, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "NULL device is refused");

        /* Host operations, so they do not gate on the device's opcode
         * groups the way CFT_MIN does - which is exactly why the base
         * operation is restated inside them rather than issued as
         * opcode 7. Nothing to assert about a software device here
         * beyond that they work, but the fp256 leg proves the width
         * is not special-cased at 32 bits. */
        {
            uint8_t wa[32], wb[32], wd[32];
            memset(wa, 0, sizeof wa);
            memset(wb, 0, sizeof wb);
            wa[31] = 0x80;                      /* -0 at fp256 */
            CHECK(cft_min_mag(dev, CFT_FP256, wa, wb, wd, 1, &f) == CFT_OK,
                  "fp256 minmag");
            CHECK(memcmp(wd, wa, 32) == 0, "min of the fp256 zeros is -0");
            CHECK(cft_max_mag(dev, CFT_FP256, wa, wb, wd, 1, &f) == CFT_OK,
                  "fp256 maxmag");
            CHECK(memcmp(wd, wb, 32) == 0, "max of the fp256 zeros is +0");
        }
        cft_lower_flags(dev, CFT_FLAGS_ALL);
    }

    /* --- the formatOf arithmetic operations (754-2019 5.4.1) ------
     *
     * host/tests/formatof_check.py proves these against the model over
     * every ordered pair at scale and the published sets replay them;
     * what belongs HERE is this file's charter - refusals, aliasing,
     * and the rows whose expected bits come from reading 5.4.1 rather
     * than from either implementation.
     *
     * Every anchor below is derivable with the clause open, and every
     * constant is built from the format's own field layout rather than
     * typed:
     *
     *  - THE DOUBLE ROUNDING. binary64 operands, binary32 destination.
     *    a = 1 + 2^-24 is exactly the midpoint between binary32's 1 and
     *    1 + 2^-23, and it is a binary64 value; b = 1, so the product is
     *    that midpoint EXACTLY; c is binary64's smallest subnormal,
     *    2^-1074, which is positive. The infinitely precise a*b + c is
     *    therefore strictly above the midpoint, so 5.4.1's single
     *    rounding to binary32 gives 1 + 2^-23. Round to binary64 first
     *    and the addend disappears under a half-ulp of 2^-53: the
     *    intermediate is the midpoint, the second rounding ties to even,
     *    and the answer comes back 1.0 - one ulp low. Both routes are
     *    issued below, so the difference is exhibited rather than
     *    described.
     *  - THE DESTINATION OWNS THE EXCEPTIONS. 2^100 * 2^100 is an
     *    ordinary binary64 multiply and an overflow in binary32; 2^-150
     *    is an ordinary binary64 normal and half of binary32's least
     *    subnormal, so it is an exact tie between zero and that
     *    subnormal, and 7.5's underflow rises with inexact. The
     *    direction decides which side of both, which is why each is
     *    issued in two attributes.
     *  - THE WIDER DESTINATION HAS THE WIDER RANGE. The square of
     *    binary32's least subnormal underflows to zero IN binary32 and
     *    is an ordinary binary64 normal, 2^-298, exactly. The same two
     *    calls, one opcode apart, are in the test.
     *  - SQUARE ROOT CROSSES RANGES TOO. sqrt of binary128's 2^-2000 is
     *    binary64's 2^-1000, exact; into binary32 the root of 2^-400
     *    lands below the subnormal floor and underflows to zero.
     *  - THE SAME-FORMAT CASE IS THE OPERATION THAT WAS ALREADY HERE,
     *    bit for bit and flag for flag, which is the base case a reader
     *    will assume.
     */
    {
        uint8_t a8[8 * 8], b8[8 * 8], c8[8 * 8], d4[8 * 4], d8[8 * 8];
        uint8_t a16[16];
        uint32_t fl = 0xdead, bus = 0xdead, fl2 = 0;
        const uint32_t FL_OVF = CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        const uint32_t FL_UNF = CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
        int k;

        /* --- the double rounding, exhibited --- */
        /* a = 1 + 2^-24 in binary64: exponent field = bias, and the
         * fraction bit whose weight is 2^-24 sits at 52 - 24. */
        put64(a8, ((uint64_t)1023 << 52) | ((uint64_t)1 << (52 - 24)));
        put64(b8, (uint64_t)1023 << 52);                    /* 1.0 */
        put64(c8, (uint64_t)1);                             /* 2^-1074 */
        st = cft_formatof_fma(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, c8, d4, 1, &fl, &bus);
        CHECK(st == CFT_OK &&
              get32(d4) == (((uint32_t)127 << 23) | 1u) &&
              fl == CFT_FLAG_INEXACT,
              "formatOf-fusedMultiplyAdd rounds ONCE into binary32: "
              "got 0x%08x/0x%02x want 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl,
              (unsigned)(((uint32_t)127 << 23) | 1u),
              (unsigned)CFT_FLAG_INEXACT);
        CHECK(bus == 0,
              "the narrowing route issues no device pass, so bus_out is 0");
        /* the control: the same operands rounded in binary64 first and
         * then converted - the route 5.4.1 does NOT describe */
        st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, a8, b8, c8, d8, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK, "fma in binary64: %s", cft_strerror(st));
        st = cft_convert(dev, CFT_FP64, CFT_FP32, CFT_RNE, d8, d4, 1, &fl2);
        CHECK(st == CFT_OK && get32(d4) == ((uint32_t)127 << 23),
              "rounding in the source format first ties to even and "
              "loses an ulp - got 0x%08x, which is why formatOf is not "
              "a composition in this direction", (unsigned)get32(d4));

        /* --- the destination owns the overflow --- */
        put64(a8, (uint64_t)(1023 + 100) << 52);            /* 2^100 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f800000u && fl == FL_OVF,
              "2^200 overflows the binary32 destination: 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RTZ,
                              a8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f7fffffu && fl == FL_OVF,
              "7.4: roundTowardZero delivers the largest finite instead "
              "of an infinity - 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        /* the same multiply IN binary64 raises nothing at all */
        st = cft_run(dev, CFT_MUL, CFT_FP64, CFT_RNE, a8, a8, NULL, d8, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK && fl == 0,
              "2^100 * 2^100 is unremarkable in binary64, which is what "
              "makes the row above a statement about the destination");

        /* --- the destination owns the tininess --- */
        put64(a8, (uint64_t)(1023 - 150) << 52);            /* 2^-150 */
        put64(b8, (uint64_t)1023 << 52);                    /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "half of binary32's least subnormal is an exact tie and "
              "roundTiesToEven takes the even neighbour, zero: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RUP,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 1u && fl == FL_UNF,
              "roundTowardPositive takes the other side of that tie: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);

        /* --- the wider destination has the wider range --- */
        put32(a8, 1u);                                /* 2^-149, binary32 */
        st = cft_formatof_mul(dev, CFT_FP32, CFT_FP64, CFT_RNE,
                              a8, a8, d8, 1, &fl, &bus);
        CHECK(st == CFT_OK &&
              get64(d8) == ((uint64_t)(1023 - 298) << 52) && fl == 0,
              "the square of binary32's least subnormal is an EXACT "
              "binary64 normal, 2^-298: 0x%016llx/0x%02x",
              (unsigned long long)get64(d8), (unsigned)fl);
        CHECK(bus == 0, "a widening pass reports a clean bus word");
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, a8, a8, NULL, d4, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "and the same multiply in binary32 vanishes, which is the "
              "whole reason 5.4.1 asks for the cross-format form");

        /* --- square root across ranges --- */
        memset(a16, 0, sizeof a16);
        for (k = 0; k < 15; k++)                  /* 2^-2000 in binary128 */
            if ((((long)16383 - 2000) >> k) & 1)
                a16[(112 + k) / 8] |= (uint8_t)(1u << ((112 + k) % 8));
        st = cft_formatof_sqrt(dev, CFT_FP128, CFT_FP64, CFT_RNE,
                               a16, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK &&
              get64(d8) == ((uint64_t)(1023 - 1000) << 52) && fl == 0,
              "sqrt of binary128's 2^-2000 is binary64's 2^-1000, "
              "exactly: 0x%016llx/0x%02x",
              (unsigned long long)get64(d8), (unsigned)fl);
        memset(a16, 0, sizeof a16);
        for (k = 0; k < 15; k++)                   /* 2^-400 in binary128 */
            if ((((long)16383 - 400) >> k) & 1)
                a16[(112 + k) / 8] |= (uint8_t)(1u << ((112 + k) % 8));
        st = cft_formatof_sqrt(dev, CFT_FP128, CFT_FP32, CFT_RNE,
                               a16, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "its root 2^-200 is below binary32's subnormal floor, so "
              "the cross-format square root CAN underflow where the "
              "same-format one cannot: 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);

        /* --- division, and the exceptions of 7.2/7.3 in the
         *     destination's encoding --- */
        put64(a8, (uint64_t)1023 << 52);                       /* 1.0 */
        put64(b8, ((uint64_t)(1023 + 1) << 52) | ((uint64_t)1 << 51));
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x3eaaaaabu &&
              fl == CFT_FLAG_INEXACT,
              "1/3 correctly rounded straight into binary32 is "
              "0x3eaaaaab: got 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        put64(c8, 0);                                          /* +0 */
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f800000u &&
              fl == CFT_FLAG_DIVBYZERO,
              "7.3 divideByZero, delivered in the DESTINATION: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              c8, c8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID,
              "0/0 is the destination's canonical quiet NaN with "
              "invalid: 0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);

        /* --- 6.2.1: a signaling NaN operand signals in every one of
         *     the six, and the quiet NaN it delivers is the
         *     DESTINATION's --- */
        put64(a8, ((uint64_t)2047 << 52) | (uint64_t)1);       /* sNaN */
        put64(b8, (uint64_t)1023 << 52);
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID, "sNaN through formatOf-addition");
        st = cft_formatof_sqrt(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                               a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID, "sNaN through formatOf-squareRoot");
        st = cft_formatof_fma(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              b8, b8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID,
              "sNaN in the addend of formatOf-fusedMultiplyAdd");
        /* and a widening source: the conversion raises it on the way */
        put32(a8, 0x7f800001u);                          /* binary32 sNaN */
        put32(b8, 0x3f800000u);
        st = cft_formatof_add(dev, CFT_FP32, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == CFT_FLAG_INVALID,
              "a signaling NaN signals once, not twice, on the widening "
              "route: 0x%02x", (unsigned)fl);

        /* --- the same-format case IS the existing operation --- */
        put32(a8, 0x3f800001u);
        put32(b8, 0x33800000u);
        st = cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK, "same-format add: %s", cft_strerror(st));
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a8, NULL, b8,
                     d4 + 4, 1, &fl2, NULL);
        CHECK(st == CFT_OK && get32(d4) == get32(d4 + 4) && fl == fl2,
              "sfmt == dfmt is cft_run's own answer: 0x%08x/0x%02x vs "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl,
              (unsigned)get32(d4 + 4), (unsigned)fl2);
        st = cft_formatof_sqrt(dev, CFT_FP32, CFT_FP32, CFT_RDN,
                               a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK, "same-format sqrt: %s", cft_strerror(st));
        st = cft_sqrt(dev, CFT_FP32, CFT_RDN, a8, d4 + 4, 1, &fl2, NULL);
        CHECK(st == CFT_OK && get32(d4) == get32(d4 + 4) && fl == fl2,
              "and cft_sqrt's, for the operation that has no opcode");

        /* --- batches: the element loop and the flag OR --- */
        for (k = 0; k < 8; k++)
            put64(a8 + 8 * k, (uint64_t)(1023 + 100 * k) << 52);
        for (k = 0; k < 8; k++)
            put64(b8 + 8 * k, (uint64_t)1023 << 52);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 8, &fl, NULL);
        CHECK(st == CFT_OK && (fl & CFT_FLAG_OVERFLOW),
              "a batch's flag word is the OR across it");
        CHECK(get32(d4) == ((uint32_t)127 << 23),
              "element 0 of that batch is 2^0, untouched by element 7's "
              "overflow: 0x%08x", (unsigned)get32(d4));
        CHECK(get32(d4 + 4 * 7) == 0x7f800000u,
              "and element 7 is the infinity");

        /* --- subtraction, where the cancellation is exact and the
         *     destination still decides the sign of the zero ---
         *
         * (1 + 2^-52) - 1 is 2^-52 EXACTLY - a catastrophic
         * cancellation in binary64 whose whole result is one bit, and
         * 2^-52 is an ordinary binary32 normal (binary32's emin is
         * -126), so nothing is lost on the way down and nothing is
         * signalled. And 6.3's rule is the destination's: an exact
         * cancellation is +0 in every attribute except
         * roundTowardNegative. */
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);   /* 1 + 2^-52 */
        put64(b8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK &&
              get32(d4) == ((uint32_t)(127 - 52) << 23) && fl == 0,
              "formatOf-subtraction of a cancellation: got 0x%08x/0x%02x "
              "want 0x%08x/0x00", (unsigned)get32(d4), (unsigned)fl,
              (unsigned)((uint32_t)(127 - 52) << 23));
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              b8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == 0,
              "an exact cancellation is +0 under roundTiesToEven");
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RDN,
                              b8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x80000000u && fl == 0,
              "6.3: and -0 under roundTowardNegative, in the "
              "DESTINATION's encoding: 0x%08x", (unsigned)get32(d4));
        /* the same subtraction into a WIDER destination is the same
         * value, which is what makes the row above about the operation
         * rather than about binary32 */
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == 0,
              "and into binary256 it is exact too: 0x%02x", (unsigned)fl);


        /* --- a hair above half the destination's least subnormal ----
         *
         * Half of binary32's least subnormal is 2^-150, an ordinary
         * binary64 normal; binary64's own least subnormal added to it
         * puts the exact sum strictly ABOVE that half-way point, so
         * roundTiesToEven delivers binary32's least subnormal and not
         * zero. Exactly ON the half-way point the tie goes to the even
         * neighbour, which is zero - and having both rows is the
         * difference between testing the boundary and testing near it.
         *
         * This is the family that caught the MPFR harness reaching the
         * destination's subnormal grid through a recipe that flushes:
         * the library was right and the oracle was not. It is pinned in
         * C as well as in the model, because C is where it would be
         * ported wrong. */
        put64(a8, (uint64_t)(1023 - 150) << 52);           /* 2^-150 */
        put64(b8, (uint64_t)1);                            /* 2^-1074 */
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 1u && fl == FL_UNF,
              "a hair above half the least subnormal rounds UP to it: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        put64(b8, 0);
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "and exactly ON it the tie goes to the even neighbour, "
              "zero: 0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        /* negated: the least subnormal keeps its sign, and so would the
         * zero, which is 6.3's rule for a value that is zero because of
         * rounding */
        put64(a8, ((uint64_t)(1023 - 150) << 52) | ((uint64_t)1 << 63));
        put64(b8, ((uint64_t)1) | ((uint64_t)1 << 63));
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x80000001u && fl == FL_UNF,
              "and negated, the least subnormal with its sign: 0x%08x",
              (unsigned)get32(d4));

        /* --- and the 7.1 status word, from formatOf calls ------------
         *
         * Package B's word is only worth having if every entry point
         * feeds it, so these four rows ask it of THIS package's six.
         * The interesting one is the last: a call that signals nothing
         * must leave the word exactly as it found it, which is the
         * difference between OR-ing a group in and assigning one. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_test_flags(dev, CFT_FLAGS_ALL) == 0,
              "the word starts down");

        /* a narrowing multiply that is inexact and nothing else */
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);   /* 1 + 2^-52 */
        put64(b8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 1 &&
              cft_test_flags(dev, (uint32_t)(CFT_FLAGS_ALL &
                                             ~CFT_FLAG_INEXACT)) == 0,
              "a narrowing multiply raises inexact IN THE WORD, and only "
              "that - flags_out was not even asked for");

        /* a call that signals nothing leaves the word alone: the same
         * narrowing multiply by an exact power of two */
        put64(a8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == 0 &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 1,
              "a formatOf call that signals nothing neither adds to the "
              "word nor lowers it");

        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(c8, 0);                                      /* +0 */
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_DIVBYZERO) == 1 &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 0,
              "formatOf-division by zero leaves divideByZero standing and "
              "NOT the inexact of its own scaffolding - the widening "
              "route's passes are muted, which is what that is for");

        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(a8, ((uint64_t)2047 << 52) | (uint64_t)1);   /* sNaN */
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_INVALID) == 1,
              "a signaling NaN through the WIDENING route reaches the "
              "word once, through the operation rather than through its "
              "internal conversion");

        /* the accumulation itself: two calls, two different exceptions,
         * and 7.1's "lowered only at the user's request" */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK, "inexact call");
        put64(a8, (uint64_t)1023 << 52);
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, (uint32_t)(CFT_FLAG_INEXACT |
                                             CFT_FLAG_DIVBYZERO)) == 1,
              "the word accumulates across formatOf calls and is lowered "
              "only when asked");
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* --- refusals --- */
        CHECK(cft_formatof_add(dev, (cft_format)9, CFT_FP32, CFT_RNE,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad source format refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, (cft_format)-1, CFT_RNE,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad destination format refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, (cft_round)5,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT,
              "a rounding direction outside 4.3's five refused - which is "
              "how 9.5's roundTiesTowardZero stays unreachable from here");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               NULL, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL a refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, NULL, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL b refused");
        CHECK(cft_formatof_fma(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, b8, NULL, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL c refused by fma");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, b8, NULL, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL d refused");
        CHECK(cft_formatof_sqrt(NULL, CFT_FP32, CFT_FP32, CFT_RNE,
                                a8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL device refused");
        fl = 0xdead;
        bus = 0xdead;
        CHECK(cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                               NULL, NULL, NULL, 0, &fl, &bus) == CFT_OK &&
              fl == 0 && bus == 0,
              "n == 0 is not an error and clears both output words");
        /* sqrt reads one operand, so a NULL second argument is not its
         * business to refuse - the entry point does not have one */
        CHECK(cft_formatof_sqrt(dev, CFT_FP256, CFT_FP32, CFT_RNE,
                                a8, d4, 1, NULL, NULL) == CFT_OK,
              "flags_out and bus_out may both be NULL");
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
