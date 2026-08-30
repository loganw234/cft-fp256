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
                uint32_t want = cft_supports(dev, (cft_op)op_i,
                                             (cft_format)f_i)
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
