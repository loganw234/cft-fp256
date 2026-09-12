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
 * Four things are checked, in increasing order of what they can
 * catch:
 *
 *   1. every supported (format, opcode, attribute) agrees with
 *      software, element for element and flag for flag;
 *   2. partition invariance - one call over n elements gives the same
 *      answer as several calls over consecutive slices of it, which is
 *      what the library does internally across tiles;
 *   3. sizes that straddle a beat and a tile boundary, because that is
 *      where a slice arithmetic error lives;
 *   4. reductions, which are the only path where element i of the
 *      output does not come from element i of the input. That makes
 *      them the only path where the number of elements is a real
 *      operand rather than a loop bound, and the engine's beat count
 *      was silently wrong for exactly that reason - a truncating
 *      shift, correct for elementwise because the host pads, and
 *      short by the tail for a reduction. n=1 fp32 computed zero
 *      beats and returned having summed nothing. Every awkward n
 *      below is there because of that bug.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"

#define MAXE 32

static int failures;
static int checks;

/* What CAPS said the device could not do.
 *
 * A skip is not a failure, which is correct, and it is also how a
 * whole opcode group can vanish without anyone noticing: op_caps was
 * once written so that it advertised reductions and silently dropped
 * the integer group, and every integer opcode was then skipped rather
 * than run. The suite stayed green. So the count is kept, the names
 * are kept, and the final summary refuses to say "the device and the
 * software backend agree on every case" when cases never ran. */
#define MAX_SKIP 32
static int  skipped;
static const char *skip_name[MAX_SKIP];

static void note_skip(const char *what)
{
    int i;
    for (i = 0; i < skipped && i < MAX_SKIP; i++)
        if (!strcmp(skip_name[i], what))
            return;               /* one line per thing, not per format */
    if (skipped < MAX_SKIP)
        skip_name[skipped] = what;
    skipped++;
}

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

/* ---------------------------------------------------------------
 * Finite operands, for the reductions
 *
 * fill() above draws from the whole encoding space, which is the right
 * choice for elementwise: every case is independent, so a NaN in
 * element 3 tests NaN handling in element 3 and nothing else.
 *
 * A reduction is not like that. One NaN anywhere poisons the single
 * output, so every check after the first degenerates into "is it the
 * same NaN". That is worth asking once - quiet-NaN payload propagation
 * through a tree is a genuine determinism question - and useless as
 * the only question, because it would hide every arithmetic and
 * tree-shape bug behind a NaN that matches for the wrong reason.
 *
 * So reductions are run both ways: random bit patterns for propagation
 * and payload rules, and ordinary normal numbers for the arithmetic.
 * --------------------------------------------------------------- */
struct fmt_layout { int total_bits, exp_bits; };

/* 1 sign + exp + significand = total; fp256 is 1 + 19 + 236, giving
 * the 237-bit significand the contract specifies. The same table as
 * host/tools/cft_bench.c, and check_layout() below proves every row
 * against the library rather than trusting that it was typed right -
 * a wrong exponent width here would not crash, it would quietly
 * generate operands that miss the case they were meant to cover. */
static const struct fmt_layout LAYOUT[4] = {
    {  32,  8 }, {  64, 11 }, { 128, 15 }, { 256, 19 }
};

static void put_bits(uint8_t *e, int lo, int nbits, uint64_t val)
{
    int i;
    for (i = 0; i < nbits; i++) {
        int b = lo + i;
        uint8_t m = (uint8_t)(1u << (b & 7));
        if ((val >> i) & 1u) e[b >> 3] |= m;
        else                 e[b >> 3] = (uint8_t)(e[b >> 3] & ~m);
    }
}

/* The bit pattern of 2^k for this format, k small. */
static void make_pow2(uint8_t *e, cft_format fmt, int k)
{
    int total = LAYOUT[(int)fmt].total_bits;
    int ebits = LAYOUT[(int)fmt].exp_bits;
    int sbits = total - 1 - ebits;
    uint64_t bias = ((uint64_t)1 << (ebits - 1)) - 1;

    memset(e, 0, (size_t)total / 8);
    put_bits(e, sbits, ebits, bias + (uint64_t)k);
}

/* Normal numbers with a full random significand and an exponent within
 * +/-SPREAD of the bias. The spread is small on purpose: a sum of n of
 * these stays finite, so the answer depends on alignment, cancellation
 * and rounding rather than on how quickly it reached infinity. */
#define SPREAD 3
static void fill_finite(uint8_t *buf, cft_format fmt, size_t n)
{
    size_t sz = cft_format_size(fmt);
    int total = LAYOUT[(int)fmt].total_bits;
    int ebits = LAYOUT[(int)fmt].exp_bits;
    int sbits = total - 1 - ebits;
    uint64_t bias = ((uint64_t)1 << (ebits - 1)) - 1;
    size_t i, j;

    for (i = 0; i < n; i++) {
        uint8_t *e = buf + i * sz;
        for (j = 0; j < sz; j++)
            e[j] = rbyte();
        put_bits(e, sbits, ebits, bias + (rbyte() % (2 * SPREAD + 1)) - SPREAD);
        put_bits(e, total - 1, 1, rbyte() & 1u);   /* both signs: cancel */
    }
}

/* Prove LAYOUT, using the backend that has been replayed against the
 * golden model. Build 1.0 and 2.0 from the table, then require
 * 1.0 * 1.0 == 1.0 and 1.0 + 1.0 == 2.0. A wrong exponent width puts
 * the field in the wrong place, so "1.0" is some other number and
 * doubling it does not land on the pattern the table predicts for
 * 2.0. Cheap, and it turns a transcribed constant into a checked one. */
static void check_layout(cft_device *sw)
{
    uint8_t one[MAXE], two[MAXE], got[MAXE];
    int f;

    for (f = 0; f < 4; f++) {
        cft_format fmt = (cft_format)f;
        size_t esz = cft_format_size(fmt);

        CHECK(LAYOUT[f].total_bits == (int)esz * 8,
              "%s: LAYOUT says %d bits, the library says %d",
              cft_format_name(fmt), LAYOUT[f].total_bits, (int)esz * 8);

        make_pow2(one, fmt, 0);
        make_pow2(two, fmt, 1);

        memset(got, 0, sizeof got);
        if (cft_run(sw, CFT_MUL, fmt, CFT_RNE, one, one, NULL, got, 1,
                    NULL, NULL) != CFT_OK)
            continue;
        CHECK(memcmp(got, one, esz) == 0,
              "%s: LAYOUT is wrong - the pattern it calls 1.0 is not "
              "idempotent under multiplication", cft_format_name(fmt));

        memset(got, 0, sizeof got);
        if (cft_run(sw, CFT_ADD, fmt, CFT_RNE, one, one, NULL, got, 1,
                    NULL, NULL) != CFT_OK)
            continue;
        CHECK(memcmp(got, two, esz) == 0,
              "%s: LAYOUT is wrong - 1.0 + 1.0 is not the pattern it "
              "calls 2.0", cft_format_name(fmt));
    }
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
    /* The cut list is fixed and sums to 1,120; a larger n used to
     * trip the coverage check below and report the tail as a
     * "changed result" (card day, 2026-09-08, at the runbook's
     * n=4096). One more slice covers whatever is left, so the
     * invariance holds for any n and the check keeps its meaning. */
    if (off < n) {
        uint32_t f = 0;
        size_t k = n - off;
        if (cft_run(hw, op, fmt, rnd, B.a + off * esz, B.b + off * esz,
                    B.c + off * esz, split + off * esz, k, &f, NULL)
            != CFT_OK) {
            printf("  FAIL: tail slice run: %s\n", cft_last_error());
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

/* Divide and square root, both backends. These are compositions of
 * cft_run steps rather than single opcodes, so on the device side
 * every floating step in the sequence runs on the tile - which makes
 * this the check that the tile's seeds and FMA compose to the same
 * bits the software backend's do, flags included. Any-bits operands
 * exercise the special-class merging; the sequence core is what the
 * finite fractions of those patterns land in. */
static void compare_divsqrt(cft_device *sw, cft_device *hw, cft_format fmt,
                            cft_round rnd, size_t n, uint32_t seed)
{
    size_t esz = cft_format_size(fmt);
    uint32_t fsw = 0, fhw = 0, bus = 0;
    uint8_t *a = malloc(n * esz), *b = malloc(n * esz);
    uint8_t *dsw = malloc(n * esz), *dhw = malloc(n * esz);
    cft_status ssw, shw;

    if (!a || !b || !dsw || !dhw) {
        printf("  FAIL: out of memory\n");
        failures++;
        goto out;
    }
    rs = seed ? seed : 1;
    fill(a, n, esz);
    fill(b, n, esz);

    ssw = cft_div(sw, fmt, rnd, a, b, dsw, n, &fsw, NULL);
    shw = cft_div(hw, fmt, rnd, a, b, dhw, n, &fhw, &bus);
    CHECK(ssw == CFT_OK, "software %s div n=%lu: %s", cft_format_name(fmt),
          (unsigned long)n, cft_strerror(ssw));
    CHECK(shw == CFT_OK, "device %s div n=%lu: %s (bus 0x%x) %s",
          cft_format_name(fmt), (unsigned long)n, cft_strerror(shw),
          (unsigned)bus, cft_last_error());
    if (ssw == CFT_OK && shw == CFT_OK) {
        CHECK(memcmp(dsw, dhw, n * esz) == 0,
              "%s div rnd=%d: backends disagree", cft_format_name(fmt),
              (int)rnd);
        CHECK(fsw == fhw, "%s div rnd=%d: FLAGS sw=0x%02x hw=0x%02x",
              cft_format_name(fmt), (int)rnd, (unsigned)fsw,
              (unsigned)fhw);
    }

    fsw = fhw = 0;
    ssw = cft_sqrt(sw, fmt, rnd, a, dsw, n, &fsw, NULL);
    shw = cft_sqrt(hw, fmt, rnd, a, dhw, n, &fhw, &bus);
    CHECK(ssw == CFT_OK, "software %s sqrt n=%lu: %s", cft_format_name(fmt),
          (unsigned long)n, cft_strerror(ssw));
    CHECK(shw == CFT_OK, "device %s sqrt n=%lu: %s (bus 0x%x) %s",
          cft_format_name(fmt), (unsigned long)n, cft_strerror(shw),
          (unsigned)bus, cft_last_error());
    if (ssw == CFT_OK && shw == CFT_OK) {
        CHECK(memcmp(dsw, dhw, n * esz) == 0,
              "%s sqrt rnd=%d: backends disagree", cft_format_name(fmt),
              (int)rnd);
        CHECK(fsw == fhw, "%s sqrt rnd=%d: FLAGS sw=0x%02x hw=0x%02x",
              cft_format_name(fmt), (int)rnd, (unsigned)fsw,
              (unsigned)fhw);
    }
out:
    free(a); free(b); free(dsw); free(dhw);
}

/* One reduction, both backends. The output is ONE element however
 * large n is, which is the whole reason cft_reduce is a separate entry
 * point, and the reason this cannot reuse compare() above.
 *
 * `finite` picks the operand distribution - see fill_finite. b is
 * passed as NULL for everything but CFT_DOT, because the header says
 * it may be and a device path that dereferences it anyway should fail
 * here rather than on the card. */
static void compare_reduce(cft_device *sw, cft_device *hw, cft_format fmt,
                           cft_op op, cft_round rnd, size_t n,
                           uint32_t seed, int finite)
{
    size_t esz = cft_format_size(fmt);
    size_t bytes = (n ? n : 1) * esz;      /* malloc(0) may return NULL */
    uint32_t fsw = 0, fhw = 0, bus = 0;
    uint8_t *a = malloc(bytes), *b = malloc(bytes);
    uint8_t dsw[MAXE], dhw[MAXE];
    cft_status ssw, shw;
    const char *kind = finite ? "finite" : "any-bits";

    if (!a || !b) {
        printf("  FAIL: out of memory\n");
        failures++;
        free(a); free(b);
        return;
    }
    rs = seed ? seed : 1;
    if (finite) {
        fill_finite(a, fmt, n);
        fill_finite(b, fmt, n);
    } else {
        fill(a, n, esz);
        fill(b, n, esz);
    }
    memset(dsw, 0, sizeof dsw);
    memset(dhw, 0, sizeof dhw);

    ssw = cft_reduce(sw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                     dsw, n, &fsw, NULL);
    shw = cft_reduce(hw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                     dhw, n, &fhw, &bus);

    CHECK(ssw == CFT_OK, "software %s %s n=%lu: %s", cft_format_name(fmt),
          cft_op_name(op), (unsigned long)n, cft_strerror(ssw));
    CHECK(shw == CFT_OK, "device %s %s n=%lu: %s (bus 0x%x) %s",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(shw), (unsigned)bus, cft_last_error());

    if (ssw == CFT_OK && shw == CFT_OK) {
        char h1[2 * MAXE + 1], h2[2 * MAXE + 1];
        checks++;
        if (memcmp(dsw, dhw, esz) != 0) {
            hex(dsw, esz, h1);
            hex(dhw, esz, h2);
            printf("  FAIL: %s %s %s n=%lu rnd=%d\n"
                   "        software %s\n        device   %s\n",
                   cft_format_name(fmt), cft_op_name(op), kind,
                   (unsigned long)n, (int)rnd, h1, h2);
            failures++;
        }
        CHECK(fsw == fhw, "%s %s %s n=%lu flags: software 0x%02x, "
              "device 0x%02x", cft_format_name(fmt), cft_op_name(op),
              kind, (unsigned long)n, (unsigned)fsw, (unsigned)fhw);
    }
    free(a);
    free(b);
}

/* CFT_SUM must ignore b entirely. Cheap to promise, easy to break the
 * day someone reuses the b stream for something, and a device that got
 * this wrong would disagree with software only for callers who passed
 * a non-NULL b - which is to say, not in any other test here. */
static void check_sum_ignores_b(cft_device *hw, cft_format fmt, size_t n,
                                uint32_t seed)
{
    size_t esz = cft_format_size(fmt);
    uint8_t *a = malloc(n * esz), *b = malloc(n * esz);
    uint8_t d_null[MAXE], d_b[MAXE];
    uint32_t f1 = 0, f2 = 0;

    if (!a || !b) { free(a); free(b); return; }
    rs = seed ? seed : 1;
    fill_finite(a, fmt, n);
    fill_finite(b, fmt, n);
    memset(d_null, 0, sizeof d_null);
    memset(d_b, 0, sizeof d_b);

    if (cft_reduce(hw, CFT_SUM, fmt, CFT_RNE, a, NULL, d_null, n, &f1, NULL)
            == CFT_OK &&
        cft_reduce(hw, CFT_SUM, fmt, CFT_RNE, a, b, d_b, n, &f2, NULL)
            == CFT_OK) {
        CHECK(memcmp(d_null, d_b, esz) == 0 && f1 == f2,
              "%s CFT_SUM n=%lu: passing b changed the answer",
              cft_format_name(fmt), (unsigned long)n);
    }
    free(a);
    free(b);
}

/* ---------------------------------------------------------------
 * Sequencer programs, device vs software
 *
 * cft_program_run's floating steps execute on whichever backend the
 * program was loaded against, so running the SAME image on both and
 * comparing deposits, counts, flags and status is the on-device proof
 * that MODE[15] reaches a working cft_seq - the same
 * device-vs-software shape every other section here uses. Images are
 * packed by hand below; the layout is seq.py's to_bytes(), which is
 * also program.c's parser, so a byte out of place fails loudly at
 * load rather than quietly at compare.
 * --------------------------------------------------------------- */

static uint64_t seq_alu(unsigned op, unsigned rd, unsigned ra,
                        unsigned rb, unsigned rc, unsigned rnd,
                        unsigned kb, unsigned kc)
{
    return (uint64_t)op | ((uint64_t)rd << 8) | ((uint64_t)ra << 12) |
           ((uint64_t)rb << 16) | ((uint64_t)rc << 20) |
           ((uint64_t)rnd << 24) | ((uint64_t)kb << 28) |
           ((uint64_t)kc << 29);
}

static uint64_t seq_ctrl(unsigned code, unsigned ra, uint32_t imm)
{
    return (uint64_t)code | ((uint64_t)ra << 12) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

/* ---- revision 2's encodings (docs/SEQUENCER.md, 2026-09-08) --------
 *
 * The five-bit register form. Each field's low four bits stay where
 * they were and the fifth goes to imm[27:24] - rd, ra, rb, rc in that
 * order. A constant operand's fifth bit is NOT set, because a constant
 * index is four bits (or a byte of imm under kx) and never five; the
 * loader refuses it if it is, which is a case below.
 *
 * seq_alu above stays as it is, with its own call sites: a program
 * that names only r0..r15 encodes identically either way, and the two
 * helpers agreeing about those is worth more than one helper. */
static uint64_t seq_alu5(unsigned op, unsigned rd, unsigned ra,
                         unsigned rb, unsigned rc, unsigned rnd,
                         unsigned ka, unsigned kb, unsigned kc)
{
    uint32_t imm = ((rd >> 4) & 1u) << 24;
    if (!ka) imm |= ((ra >> 4) & 1u) << 25;
    if (!kb) imm |= ((rb >> 4) & 1u) << 26;
    if (!kc) imm |= ((rc >> 4) & 1u) << 27;
    return (uint64_t)op | ((uint64_t)(rd & 15u) << 8) |
           ((uint64_t)(ra & 15u) << 12) | ((uint64_t)(rb & 15u) << 16) |
           ((uint64_t)(rc & 15u) << 20) | ((uint64_t)rnd << 24) |
           ((uint64_t)ka << 27) | ((uint64_t)kb << 28) |
           ((uint64_t)kc << 29) | ((uint64_t)imm << 32);
}

/* DEPOSIT or SETACT naming a five-bit register: imm[25] is ra's fifth
 * bit and the only bit of imm either of them may set. */
static uint64_t seq_ctrl5(unsigned code, unsigned ra)
{
    uint32_t imm = ((ra >> 4) & 1u) << 25;
    return (uint64_t)code | ((uint64_t)(ra & 15u) << 12) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

/* The kx form: the three constant indices come from imm[7:0],
 * imm[15:8] and imm[23:16], so the bank reaches 256 rather than 16.
 * An operand whose k bit is set must leave its four-bit field zero,
 * and one whose k bit is clear must leave its imm byte zero. */
static uint64_t seq_alu_kx(unsigned op, unsigned rd, unsigned ia,
                           unsigned ib, unsigned ic,
                           unsigned ka, unsigned kb, unsigned kc)
{
    uint32_t imm = (ka ? (ia & 0xFFu) : 0u) |
                   ((kb ? (ib & 0xFFu) : 0u) << 8) |
                   ((kc ? (ic & 0xFFu) : 0u) << 16);
    return (uint64_t)op | ((uint64_t)(rd & 15u) << 8) |
           ((uint64_t)(ka ? 0u : ia & 15u) << 12) |
           ((uint64_t)(kb ? 0u : ib & 15u) << 16) |
           ((uint64_t)(kc ? 0u : ic & 15u) << 20) |
           ((uint64_t)ka << 27) | ((uint64_t)kb << 28) |
           ((uint64_t)kc << 29) | ((uint64_t)1 << 30) |
           ((uint64_t)imm << 32);
}

/* ---- revision 3's encodings (docs/SEQUENCER.md, 2026-09-08 evening) -
 *
 * The kx form with the NINTH index bits: imm[28], imm[29] and imm[30]
 * are ka's, kb's and kc's high bits, so the bank reaches 512. imm[31]
 * stays reserved-must-be-zero. A ninth bit is read only under kx and
 * only for an operand whose k flag is set, so this sets none for an
 * operand that names a register. */
static uint64_t seq_alu_kx9(unsigned op, unsigned rd, unsigned ia,
                            unsigned ib, unsigned ic,
                            unsigned ka, unsigned kb, unsigned kc)
{
    uint64_t w = seq_alu_kx(op, rd, ia, ib, ic, ka, kb, kc);
    uint32_t hi = (ka ? ((ia >> 8) & 1u) : 0u) |
                  ((kb ? ((ib >> 8) & 1u) : 0u) << 1) |
                  ((kc ? ((ic >> 8) & 1u) : 0u) << 2);
    return w | ((uint64_t)hi << (32 + 28));
}

/* The four scratch codes. STL reads ra and imm[23:0]; LDL writes rd
 * and reads imm[23:0]; STX reads ra and rb; LDX writes rd and reads
 * rb, and for the indexed pair imm[23:0] must be zero. Registers are
 * five bits, with the fifth of each in its own bit of imm[27:24]. */
enum { SEQ_C_STL = 6, SEQ_C_LDL = 7, SEQ_C_STX = 8, SEQ_C_LDX = 9 };

static uint64_t seq_stl(unsigned ra, uint32_t slot)
{
    uint32_t imm = (slot & 0x00FFFFFFu) | (((ra >> 4) & 1u) << 25);
    return (uint64_t)SEQ_C_STL | ((uint64_t)(ra & 15u) << 12) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

static uint64_t seq_ldl(unsigned rd, uint32_t slot)
{
    uint32_t imm = (slot & 0x00FFFFFFu) | (((rd >> 4) & 1u) << 24);
    return (uint64_t)SEQ_C_LDL | ((uint64_t)(rd & 15u) << 8) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

static uint64_t seq_stx(unsigned ra, unsigned rb)
{
    uint32_t imm = (((ra >> 4) & 1u) << 25) | (((rb >> 4) & 1u) << 26);
    return (uint64_t)SEQ_C_STX | ((uint64_t)(ra & 15u) << 12) |
           ((uint64_t)(rb & 15u) << 16) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

static uint64_t seq_ldx(unsigned rd, unsigned rb)
{
    uint32_t imm = (((rd >> 4) & 1u) << 24) | (((rb >> 4) & 1u) << 26);
    return (uint64_t)SEQ_C_LDX | ((uint64_t)(rd & 15u) << 8) |
           ((uint64_t)(rb & 15u) << 16) |
           ((uint64_t)1 << 31) | ((uint64_t)imm << 32);
}

static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

/* Pack header + constants + instructions; returns the byte length.
 *
 * `flags` is the header word that was reserved[0] until 2026-09-08.
 * With CFT_PROG_FLAG_BANK_EXT set the image carries NO constant
 * section - n_consts still says how many the program addresses - so
 * `consts` is ignored and the image is 32 + 8*n_insns bytes. */
static size_t seq_image_scratch(uint8_t *out, cft_format fmt,
                                const uint64_t *insns, unsigned n_insns,
                                const uint8_t *consts, unsigned n_consts,
                                uint32_t max_deposits, uint32_t flags,
                                uint32_t n_sin, uint32_t n_sout)
{
    size_t esz = cft_format_size(fmt), off = 32;
    unsigned i;
    put_le32(out + 0, 0x50544643u);          /* "CFTP" */
    put_le32(out + 4, 1);
    put_le32(out + 8, n_insns);
    put_le32(out + 12, n_consts);
    put_le32(out + 16, max_deposits);
    put_le32(out + 20, (uint32_t)fmt);
    put_le32(out + 24, flags);
    /* The word that was reserved[1] until revision 3: scratch_io,
     * n_scratch_in in [15:0] and n_scratch_out in [31:16], meaningful
     * only under CFT_PROG_FLAG_SCRATCH_IO and zero without it. */
    put_le32(out + 28, (n_sin & 0xFFFFu) | ((n_sout & 0xFFFFu) << 16));
    if (!(flags & CFT_PROG_FLAG_BANK_EXT)) {
        memcpy(out + off, consts, n_consts * esz);
        off += n_consts * esz;
    }
    for (i = 0; i < n_insns; i++) {
        uint64_t w = insns[i];
        int b;
        for (b = 0; b < 8; b++)
            out[off + (size_t)b] = (uint8_t)(w >> (8 * b));
        off += 8;
    }
    return off;
}

static size_t seq_image_flags(uint8_t *out, cft_format fmt,
                              const uint64_t *insns, unsigned n_insns,
                              const uint8_t *consts, unsigned n_consts,
                              uint32_t max_deposits, uint32_t flags)
{
    return seq_image_scratch(out, fmt, insns, n_insns, consts, n_consts,
                             max_deposits, flags, 0, 0);
}

static size_t seq_image(uint8_t *out, cft_format fmt,
                        const uint64_t *insns, unsigned n_insns,
                        const uint8_t *consts, unsigned n_consts,
                        uint32_t max_deposits)
{
    return seq_image_flags(out, fmt, insns, n_insns, consts, n_consts,
                           max_deposits, 0);
}

static void compare_seq_one(cft_device *sw, cft_device *hw,
                            cft_format fmt, const uint8_t *image,
                            size_t bytes, uint32_t maxdep, size_t n,
                            uint32_t seed, const char *label)
{
    size_t esz = cft_format_size(fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *c = (uint8_t *)malloc(n * esz);
    uint8_t *dep_sw = (uint8_t *)malloc(n * maxdep * esz + 1);
    uint8_t *dep_hw = (uint8_t *)malloc(n * maxdep * esz + 1);
    uint32_t *cnt_sw = (uint32_t *)malloc(n * 4);
    uint32_t *cnt_hw = (uint32_t *)malloc(n * 4);
    cft_program *ps = NULL, *ph = NULL;
    uint32_t fl_sw = 0, fl_hw = 0, bus_sw = 0, bus_hw = 0;
    cft_status st_sw, st_hw;

    if (!a || !b || !c || !dep_sw || !dep_hw || !cnt_sw || !cnt_hw) {
        printf("  FAIL %s: out of memory\n", label);
        failures++;
        goto out;
    }
    rs = seed;
    fill(a, n, esz);
    fill(b, n, esz);
    fill(c, n, esz);
    memset(dep_sw, 0x5a, n * maxdep * esz);
    memset(dep_hw, 0x5a, n * maxdep * esz);

    st_sw = cft_program_load(sw, image, bytes, &ps);
    st_hw = cft_program_load(hw, image, bytes, &ph);
    checks++;
    if (st_sw != st_hw) {
        printf("  FAIL %s: load disagrees (sw %s, hw %s)\n", label,
               cft_strerror(st_sw), cft_strerror(st_hw));
        failures++;
        goto out;
    }
    if (st_sw != CFT_OK) {
        printf("  %s: both refuse the image (%s) - agreed\n", label,
               cft_strerror(st_sw));
        goto out;
    }

    st_sw = cft_program_run(ps, a, b, c, dep_sw, cnt_sw, n,
                            &fl_sw, &bus_sw);
    st_hw = cft_program_run(ph, a, b, c, dep_hw, cnt_hw, n,
                            &fl_hw, &bus_hw);
    checks++;
    if (st_sw != st_hw) {
        printf("  FAIL %s: run status disagrees (sw %s, hw %s)\n", label,
               cft_strerror(st_sw), cft_strerror(st_hw));
        failures++;
        goto out;
    }
    if (st_sw == CFT_OK) {
        checks++;
        if (maxdep != 0 && memcmp(dep_sw, dep_hw, n * maxdep * esz) != 0) {
            size_t i;
            for (i = 0; i < n * maxdep * esz; i++)
                if (dep_sw[i] != dep_hw[i])
                    break;
            printf("  FAIL %s: deposits differ first at byte %lu "
                   "(element %lu)\n", label, (unsigned long)i,
                   (unsigned long)(i / esz));
            failures++;
        }
        checks++;
        if (memcmp(cnt_sw, cnt_hw, n * 4) != 0) {
            printf("  FAIL %s: deposit counts differ\n", label);
            failures++;
        }
        checks++;
        if (fl_sw != fl_hw || bus_sw != bus_hw) {
            printf("  FAIL %s: flags/status differ (sw %02x/%02x, "
                   "hw %02x/%02x)\n", label, fl_sw, bus_sw, fl_hw,
                   bus_hw);
            failures++;
        }
    }
out:
    cft_program_free(ps);
    cft_program_free(ph);
    free(a); free(b); free(c);
    free(dep_sw); free(dep_hw); free(cnt_sw); free(cnt_hw);
}


/* ==== the caps a backend reports are the caps it enforces ============
 *
 * The invariant docs/studies/OPT-D-contract.md item 3 exists for, and
 * the one 0.1 found violated: the software backend accepted a program
 * with 2^20 deposit slots a lane, the tile refused anything past 64
 * with a status bit and no explanation, and no host could ask which it
 * had. Now cft_get_caps answers, and this holds each backend to its own
 * answer - at the cap, and one past it.
 *
 * "One past it" is only a test where it is REPRESENTABLE. The software
 * backend's instruction cap is the header field's own ceiling
 * (2^32-1), and an image at it would be 32 GiB; that case is reported
 * as not tested rather than skipped silently, because a skip that
 * looks like a pass is how the opcode-group bug survived.
 *
 * A cap of zero is UNKNOWN - only a remote server whose caps block
 * predates the fields - and an unknown cap enforces nothing, which is
 * also checked, since "unknown" quietly meaning "zero capacity" would
 * refuse every program on an old server.
 * ==================================================================== */

/* What try_load's first instruction is, when it is not a HALT. */
enum { PROBE_NONE = 0,   /* every instruction a HALT */
       PROBE_K4,         /* a constant addressed through the 4-bit field */
       PROBE_KX,         /* a constant addressed through imm, the kx form */
       PROBE_KX9,        /* the kx form with revision 3's ninth bits */
       PROBE_REG };      /* a register named by const_idx, five bits wide */

static const char *probe_form_name(int probe)
{
    return probe == PROBE_KX9 ? "kx, nine bits"
         : probe == PROBE_KX  ? "kx"
                              : "four-bit";
}

/* One trivial program: `n_insns` HALTs, `n_consts` constants, the
 * declared deposit budget. Nothing runs it; what is under test is
 * whether cft_program_load accepts it. */
static cft_status try_load(cft_device *dev, cft_format fmt,
                           uint32_t n_insns, uint32_t n_consts,
                           uint32_t maxdep, uint32_t const_idx,
                           int probe)
{
    size_t esz = cft_format_size(fmt);
    size_t bytes = 32 + (size_t)n_consts * esz + (size_t)n_insns * 8;
    uint8_t *img = (uint8_t *)calloc(1, bytes ? bytes : 1);
    uint64_t *ins = (uint64_t *)calloc(n_insns ? n_insns : 1, 8);
    uint8_t *kon = (uint8_t *)calloc(n_consts ? n_consts : 1, esz ? esz : 1);
    cft_program *prog = NULL;
    cft_status st;
    uint32_t i;

    if (!img || !ins || !kon) {
        free(img); free(ins); free(kon);
        return CFT_ERR_OUT_OF_MEMORY;
    }
    for (i = 0; i < n_insns; i++)
        ins[i] = seq_ctrl(0, 0, 0);              /* HALT */
    if (probe != PROBE_NONE && n_insns) {
        switch (probe) {
        case PROBE_K4:
            /* r4 = r0 * k[const_idx] + r2, with kb selecting the bank.
             * seq_alu's `rb` is the index the kb bit redirects, and it
             * is four bits wide - which is why this probe stops at 15
             * and PROBE_KX exists. */
            ins[0] = seq_alu(0, 4, 0, const_idx, 2, 0, 1, 0);
            break;
        case PROBE_KX:
            /* The same instruction in the kx form, where the index is
             * a byte of imm and reaches 255. */
            ins[0] = seq_alu_kx(0, 4, 0, const_idx, 2, 0, 1, 0);
            break;
        case PROBE_KX9:
            /* And the same again with revision 3's ninth bit, where it
             * reaches 511. */
            ins[0] = seq_alu_kx9(0, 4, 0, const_idx, 2, 0, 1, 0);
            break;
        default:                                  /* PROBE_REG */
            /* r<const_idx> = r0 * r0 + r0, then deposit it, so the
             * register is both written and read. */
            ins[0] = seq_alu5(0, const_idx, 0, 0, 0, 0, 0, 0, 0);
            if (n_insns > 1)
                ins[1] = seq_ctrl5(3, const_idx);   /* DEPOSIT */
            break;
        }
    }
    (void)seq_image(img, fmt, ins, n_insns, kon, n_consts, maxdep);
    st = cft_program_load(dev, img, bytes, &prog);
    if (st == CFT_OK)
        cft_program_free(prog);
    free(img); free(ins); free(kon);
    return st;
}

/* A BANK_EXT image: header, instructions, no constant section. What
 * it computes does not matter here - what is under test is whether
 * cft_program_load takes an image whose constants arrive per run. */
static cft_status try_load_bank_ext(cft_device *dev, cft_format fmt,
                                    uint32_t n_consts)
{
    uint8_t img[64];
    uint64_t ins[3];
    cft_program *prog = NULL;
    cft_status st;
    size_t bytes;

    ins[0] = seq_alu(0, 4, 0, 0, 0, 0, 1, 0);   /* r4 = r0*k[0] + r0 */
    ins[1] = seq_ctrl(3, 4, 0);                  /* deposit r4 */
    ins[2] = seq_ctrl(0, 0, 0);                  /* halt */
    bytes = seq_image_flags(img, fmt, ins, 3, NULL, n_consts, 1,
                            CFT_PROG_FLAG_BANK_EXT);
    st = cft_program_load(dev, img, bytes, &prog);
    if (st == CFT_OK)
        cft_program_free(prog);
    return st;
}

/* An image that uses the scratch, for the feature and capacity probes.
 * STL r0 -> `slot`, LDL r4 <- `slot`, deposit r4, halt - so the memory
 * is both written and read, and `n_sin`/`n_sout` declare a per-run
 * block when either is non-zero. What it computes does not matter
 * here; what is under test is whether cft_program_load takes it. */
static cft_status try_load_scratch(cft_device *dev, cft_format fmt,
                                   uint32_t slot, uint32_t n_sin,
                                   uint32_t n_sout)
{
    uint8_t img[64];
    uint64_t ins[4];
    cft_program *prog = NULL;
    cft_status st;
    size_t bytes;
    uint32_t flags = (n_sin || n_sout) ? CFT_PROG_FLAG_SCRATCH_IO : 0u;

    ins[0] = seq_stl(0, slot);
    ins[1] = seq_ldl(4, slot);
    ins[2] = seq_ctrl(3, 4, 0);                  /* deposit r4 */
    ins[3] = seq_ctrl(0, 0, 0);                  /* halt */
    bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 1, flags,
                              n_sin, n_sout);
    st = cft_program_load(dev, img, bytes, &prog);
    if (st == CFT_OK)
        cft_program_free(prog);
    return st;
}

/* An image asking for revision 4's strict scratch range. Only flags[2]
 * decides whether the loader takes it; the indexed pair is here because
 * that is what the flag is ABOUT, and a test image that did not use the
 * feature it names would be a worse description of the thing. */
static cft_status try_load_strict(cft_device *dev, cft_format fmt)
{
    uint8_t img[64];
    uint64_t ins[4];
    cft_program *prog = NULL;
    cft_status st;
    size_t bytes;

    ins[0] = seq_stx(0, 1);                      /* scratch[r1] := r0 */
    ins[1] = seq_ldx(4, 1);                      /* r4 := scratch[r1] */
    ins[2] = seq_ctrl(3, 4, 0);                  /* deposit r4 */
    ins[3] = seq_ctrl(0, 0, 0);                  /* halt */
    bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 1,
                              CFT_PROG_FLAG_SCRATCH_STRICT, 0, 0);
    st = cft_program_load(dev, img, bytes, &prog);
    if (st == CFT_OK)
        cft_program_free(prog);
    return st;
}

static void check_caps_enforced(cft_device *dev, const char *who)
{
    cft_caps c;
    const cft_format fmt = CFT_FP32;
    cft_status st;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    if (cft_get_caps(dev, &c) != CFT_OK) {
        printf("  %s: cft_get_caps failed\n", who);
        failures++;
        return;
    }
    if (!cft_supports(dev, CFT_FMA, fmt)) {
        printf("  %s: no fp32 here, capacity check not run\n", who);
        return;
    }
    printf("  %s reports max_deposits %lu, max_insns %lu, max_consts %lu, "
           "seq_features 0x%lx\n", who,
           (unsigned long)c.max_deposits, (unsigned long)c.max_insns,
           (unsigned long)c.max_consts, (unsigned long)c.seq_features);

    /* Zero is unknown, and an unknown cap must constrain nothing. */
    if (!c.max_deposits) {
        st = try_load(dev, fmt, 1, 0, 4096, 0, PROBE_NONE);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_deposits is 0 (unknown) and a program "
                   "with 4096 was still refused: %s\n", who,
                   cft_strerror(st));
            failures++;
        }
    } else {
        st = try_load(dev, fmt, 1, 0, c.max_deposits, 0, PROBE_NONE);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_deposits %lu is reported and a program "
                   "AT it was refused: %s (%s)\n", who,
                   (unsigned long)c.max_deposits, cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        if (c.max_deposits < 0xFFFFFFFFu) {
            st = try_load(dev, fmt, 1, 0, c.max_deposits + 1u, 0, PROBE_NONE);
            checks++;
            if (st == CFT_OK) {
                printf("  FAIL %s: max_deposits %lu is reported and a "
                       "program with one MORE was accepted\n", who,
                       (unsigned long)c.max_deposits);
                failures++;
            } else {
                printf("    +1 deposit slot -> %s: %s\n", cft_strerror(st),
                       cft_last_error());
            }
        }
    }

    /* The instruction cap, where an image past it can be built at all.
     * 1 << 20 instructions is an 8 MiB image; anything larger is
     * reported as untested rather than pretended. */
    if (!c.max_insns) {
        printf("    max_insns is 0 (unknown): nothing enforced, "
               "nothing tested\n");
    } else if (c.max_insns > (1u << 20)) {
        printf("    max_insns %lu: an image past it is %llu bytes, "
               "NOT TESTED\n", (unsigned long)c.max_insns,
               (unsigned long long)(c.max_insns + 1ull) * 8ull + 32ull);
    } else {
        st = try_load(dev, fmt, c.max_insns, 0, 1, 0, PROBE_NONE);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_insns %lu is reported and a program AT "
                   "it was refused: %s (%s)\n", who,
                   (unsigned long)c.max_insns, cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        st = try_load(dev, fmt, c.max_insns + 1u, 0, 1, 0, PROBE_NONE);
        checks++;
        if (st == CFT_OK) {
            printf("  FAIL %s: max_insns %lu is reported and a program with "
                   "one MORE was accepted\n", who,
                   (unsigned long)c.max_insns);
            failures++;
        } else {
            printf("    +1 instruction -> %s: %s\n", cft_strerror(st),
                   cft_last_error());
        }
    }

    /* The addressable constants.
     *
     * Until 2026-09-08 this probe wrote the four-bit form and could
     * therefore not name an index past 15 at all, so on every device
     * shipped it tested k[15] and printed NOT TESTED for the rest -
     * a cap of 256 checked at 16. With kx the index is a byte of the
     * immediate, so the probe now goes to the cap itself: an
     * instruction addressing k[max_consts - 1] must load and one
     * addressing k[max_consts] must not. The second is representable
     * only while max_consts is below 256, since the index is a byte;
     * at 256 that half is stated rather than pretended, as before.
     *
     * The kx form is used only where the device publishes kx, since
     * the loader refuses it otherwise and the refusal would be about
     * the wrong thing. */
    if (!c.max_consts) {
        printf("    max_consts is 0 (unknown): nothing enforced, "
               "nothing tested\n");
    } else {
        const int wide = (c.seq_features & CFT_SEQ_FEAT_WIDE_CONST) != 0;
        const int kx9  = (c.seq_features & CFT_SEQ_FEAT_KX9) != 0;
        /* What an instruction can NAME: sixteen without kx, 256 with
         * it, 512 with the ninth bits of revision 3. The device's own
         * cap is held to whichever of those the encoding reaches, so a
         * cap of 512 on a device without KX9 would be tested at 256 -
         * which is the honest half rather than a false pass. */
        const uint32_t reach = kx9 ? 512u : wide ? 256u : 16u;
        const uint32_t hi = c.max_consts <= reach ? c.max_consts : reach;
        const int form = (hi > 256u) ? PROBE_KX9
                       : (hi > 16u)  ? PROBE_KX : PROBE_K4;
        st = try_load(dev, fmt, 2, hi, 1, hi - 1u, form);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_consts %lu is reported and an "
                   "instruction addressing k[%lu] in the %s form was "
                   "refused: %s (%s)\n",
                   who, (unsigned long)c.max_consts, (unsigned long)(hi - 1u),
                   probe_form_name(form),
                   cft_strerror(st), cft_last_error());
            failures++;
        } else {
            printf("    k[%lu] (%s form) loads, at the cap\n",
                   (unsigned long)(hi - 1u), probe_form_name(form));
        }
        if (c.max_consts < reach && (wide || c.max_consts < 16u)) {
            /* n_consts one past the cap, so the index is inside the
             * program's own bank and what refuses it is the DEVICE's
             * reach rather than the header's count. */
            const int f2 = (c.max_consts >= 256u) ? PROBE_KX9
                         : (c.max_consts >= 16u)  ? PROBE_KX : PROBE_K4;
            st = try_load(dev, fmt, 2, c.max_consts + 1u, 1,
                          c.max_consts, f2);
            checks++;
            if (st == CFT_OK) {
                printf("  FAIL %s: max_consts %lu is reported and an "
                       "instruction addressing k[%lu] was accepted\n", who,
                       (unsigned long)c.max_consts,
                       (unsigned long)c.max_consts);
                failures++;
            } else {
                printf("    k[%lu] -> %s: %s\n",
                       (unsigned long)c.max_consts, cft_strerror(st),
                       cft_last_error());
            }
        } else {
            printf("    max_consts %lu: an index past it does not fit the "
                   "%s, NOT TESTED\n", (unsigned long)c.max_consts,
                   c.max_consts >= 512u ? "immediate's nine bits"
                 : c.max_consts >= 256u ? "immediate's byte"
                                        : "four-bit field");
        }
    }

    /* max_scratch, on exactly the same terms: a static STL slot at the
     * cap must load and one past it must not. Both halves are always
     * representable here - the slot is imm[23:0], which reaches sixteen
     * million - so unlike max_consts there is no arm that says NOT
     * TESTED. */
    if (!(c.seq_features & CFT_SEQ_FEAT_SCRATCH)) {
        printf("    no scratch published: max_scratch %lu, nothing "
               "tested\n", (unsigned long)c.max_scratch);
    } else if (!c.max_scratch) {
        printf("    SCRATCH published with max_scratch 0 (unknown): "
               "nothing enforced, nothing tested\n");
    } else {
        st = try_load_scratch(dev, fmt, c.max_scratch - 1u, 0, 0);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_scratch %lu is reported and STL to slot "
                   "%lu was refused: %s (%s)\n", who,
                   (unsigned long)c.max_scratch,
                   (unsigned long)(c.max_scratch - 1u),
                   cft_strerror(st), cft_last_error());
            failures++;
        } else {
            printf("    scratch slot %lu loads, at the cap\n",
                   (unsigned long)(c.max_scratch - 1u));
        }
        st = try_load_scratch(dev, fmt, c.max_scratch, 0, 0);
        checks++;
        if (st == CFT_OK) {
            printf("  FAIL %s: max_scratch %lu is reported and STL to slot "
                   "%lu was accepted\n", who, (unsigned long)c.max_scratch,
                   (unsigned long)c.max_scratch);
            failures++;
        } else {
            checks++;
            if (!strstr(cft_last_error(), "max_scratch")) {
                printf("  FAIL %s: STL past max_scratch was refused (%s) "
                       "without naming the cap: %s\n", who,
                       cft_strerror(st), cft_last_error());
                failures++;
            }
            printf("    scratch slot %lu -> %s: %s\n",
                   (unsigned long)c.max_scratch, cft_strerror(st),
                   cft_last_error());
        }
    }

    /* seq_features is CAPS[7:4] in its low nibble, CAPS[31:28] - the
     * ALU extensions, IMUL first - in the next one (cft.h, 2026-09-07),
     * and CAPS2[7:4] in the third since revision 3. Anything above
     * those twelve bits is a decode fault, not a feature. */
    checks++;
    if (c.seq_features & ~0xFFFu) {
        printf("  FAIL %s: seq_features 0x%lx has bits outside CAPS[7:4], "
               "CAPS[31:28] and CAPS2[7:4]\n", who,
               (unsigned long)c.seq_features);
        failures++;
    }
    printf("    features:%s%s%s%s%s%s%s   max_scratch %lu\n",
           (c.seq_features & CFT_SEQ_FEAT_WIDE_CONST) ? " kx" : "",
           (c.seq_features & CFT_SEQ_FEAT_REGS32)     ? " REGS32" : "",
           (c.seq_features & CFT_SEQ_FEAT_BANK_PTR)   ? " BANK_PTR" : "",
           (c.seq_features & CFT_SEQ_FEAT_KX9)        ? " KX9" : "",
           (c.seq_features & CFT_ALU_EXT_IMUL)        ? " IMUL" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCRATCH)    ? " SCRATCH" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) ? " SCRATCH_IO" : "",
           (unsigned long)c.max_scratch);

    /* Revision 2's two feature bits, held to the same invariant as
     * every capacity above: what a backend PUBLISHES is what it
     * ENFORCES, in both directions. A published feature must let the
     * program that uses it load; an absent one must refuse it, and the
     * refusal must SAY SO - an old tile's operand mux reads the low
     * four bits of a five-bit register and addresses the wrong one
     * without a fault, and its fetch reads constants from a BANK_EXT
     * image that has none, so neither refusal can be made anywhere but
     * here. */
    st = try_load(dev, fmt, 2, 0, 1, 31, PROBE_REG);
    checks++;
    if (c.seq_features & CFT_SEQ_FEAT_REGS32) {
        if (st != CFT_OK) {
            printf("  FAIL %s: REGS32 is published and a program naming "
                   "r31 was refused: %s (%s)\n", who, cft_strerror(st),
                   cft_last_error());
            failures++;
        } else {
            printf("    REGS32 published, r31 loads\n");
        }
    } else if (st == CFT_OK) {
        printf("  FAIL %s: REGS32 is NOT published and a program naming "
               "r31 was accepted - its operand mux would address r15\n", who);
        failures++;
    } else {
        checks++;
        if (!strstr(cft_last_error(), "r31")) {
            printf("  FAIL %s: r31 without REGS32 was refused (%s) without "
                   "naming the register: %s\n", who, cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        printf("    REGS32 absent, r31 -> %s: %s\n", cft_strerror(st),
               cft_last_error());
    }

    st = try_load_bank_ext(dev, fmt, 2);
    checks++;
    if (c.seq_features & CFT_SEQ_FEAT_BANK_PTR) {
        if (st != CFT_OK) {
            printf("  FAIL %s: BANK_PTR is published and a BANK_EXT image "
                   "was refused: %s (%s)\n", who, cft_strerror(st),
                   cft_last_error());
            failures++;
        } else {
            printf("    BANK_PTR published, a BANK_EXT image loads\n");
        }
    } else if (st == CFT_OK) {
        printf("  FAIL %s: BANK_PTR is NOT published and a BANK_EXT image "
               "was accepted - its fetch would read constants from an "
               "image that has none\n", who);
        failures++;
    } else {
        checks++;
        if (!strstr(cft_last_error(), "BANK_EXT")) {
            printf("  FAIL %s: a BANK_EXT image without BANK_PTR was "
                   "refused (%s) without naming the flag: %s\n", who,
                   cft_strerror(st), cft_last_error());
            failures++;
        }
        printf("    BANK_PTR absent, a BANK_EXT image -> %s: %s\n",
               cft_strerror(st), cft_last_error());
    }

    /* Revision 3's three, on exactly the same terms. Each names what
     * an old device would do INSTEAD, because that is the reason none
     * of these could be a reserved-bit rule: an eight-bit operand mux
     * addresses constant 255 where 511 was meant, and a tile with no
     * scratch memory has nothing for STL to reach and no fault to
     * raise about it. */
    st = try_load_scratch(dev, fmt, 0, 0, 0);
    checks++;
    if (c.seq_features & CFT_SEQ_FEAT_SCRATCH) {
        if (st != CFT_OK) {
            printf("  FAIL %s: SCRATCH is published and a program using "
                   "STL/LDL was refused: %s (%s)\n", who, cft_strerror(st),
                   cft_last_error());
            failures++;
        } else {
            printf("    SCRATCH published, STL/LDL loads\n");
        }
    } else if (st == CFT_OK) {
        printf("  FAIL %s: SCRATCH is NOT published and a program using "
               "STL was accepted - there is no memory for it to reach\n",
               who);
        failures++;
    } else {
        checks++;
        if (!strstr(cft_last_error(), "STL")) {
            printf("  FAIL %s: STL without SCRATCH was refused (%s) without "
                   "naming the instruction: %s\n", who, cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        printf("    SCRATCH absent, STL -> %s: %s\n", cft_strerror(st),
               cft_last_error());
    }

    st = try_load_scratch(dev, fmt, 0, 2, 2);
    checks++;
    if (c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) {
        if (st != CFT_OK) {
            printf("  FAIL %s: SCRATCH_IO is published and an image "
                   "declaring a scratch block was refused: %s (%s)\n", who,
                   cft_strerror(st), cft_last_error());
            failures++;
        } else {
            printf("    SCRATCH_IO published, a SCRATCH_IO image loads\n");
        }
    } else if (st == CFT_OK) {
        printf("  FAIL %s: SCRATCH_IO is NOT published and an image "
               "declaring a scratch block was accepted\n", who);
        failures++;
    } else {
        checks++;
        if (!strstr(cft_last_error(), "SCRATCH_IO")) {
            printf("  FAIL %s: a SCRATCH_IO image without the feature was "
                   "refused (%s) without naming the flag: %s\n", who,
                   cft_strerror(st), cft_last_error());
            failures++;
        }
        printf("    SCRATCH_IO absent, a SCRATCH_IO image -> %s: %s\n",
               cft_strerror(st), cft_last_error());
    }

    /* Revision 4's R8, on exactly SCRATCH_IO's terms: published means a
     * strict image loads, absent means it is refused AND the refusal
     * names the flag. The absent branch is the one that matters, and no
     * software device can reach it - the software backend is the
     * contract and carries every feature it defines - so it fires
     * against a tile that predates R8, which is every tile there is
     * until the RTL lands. Accepting a strict image on a device that
     * cannot honour it would run the program under the modulo, and that
     * is a different contract, not a graceful degradation. */
    st = try_load_strict(dev, fmt);
    checks++;
    if (c.seq_features & CFT_SEQ_FEAT_SCRATCH_STRICT) {
        if (st != CFT_OK) {
            printf("  FAIL %s: SCRATCH_STRICT is published and an image "
                   "asking for it was refused: %s (%s)\n", who,
                   cft_strerror(st), cft_last_error());
            failures++;
        } else {
            printf("    SCRATCH_STRICT published, a strict image loads\n");
        }
    } else if (st == CFT_OK) {
        printf("  FAIL %s: SCRATCH_STRICT is NOT published and a strict "
               "image was accepted - it would run under the modulo, which "
               "is a different contract\n", who);
        failures++;
    } else {
        checks++;
        if (!strstr(cft_last_error(), "SCRATCH_STRICT")) {
            printf("  FAIL %s: a strict image without the feature was "
                   "refused (%s) without naming the flag: %s\n", who,
                   cft_strerror(st), cft_last_error());
            failures++;
        }
        printf("    SCRATCH_STRICT absent, a strict image -> %s: %s\n",
               cft_strerror(st), cft_last_error());
    }

    /* KX9 is asked with an index of 256 and a bank of 257, so what
     * decides is the DEVICE's ninth bit rather than the header's
     * count. On a device without kx at all this cannot be asked -
     * there is no encoding for an index above 15 - and says so. */
    if (!(c.seq_features & CFT_SEQ_FEAT_WIDE_CONST)) {
        printf("    kx absent, so KX9 has no encoding to test with, "
               "NOT TESTED\n");
    } else {
        st = try_load(dev, fmt, 2, 257, 1, 256, PROBE_KX9);
        checks++;
        if (c.seq_features & CFT_SEQ_FEAT_KX9) {
            if (st != CFT_OK) {
                printf("  FAIL %s: KX9 is published and an instruction "
                       "addressing k[256] was refused: %s (%s)\n", who,
                       cft_strerror(st), cft_last_error());
                failures++;
            } else {
                printf("    KX9 published, k[256] loads\n");
            }
        } else if (st == CFT_OK) {
            printf("  FAIL %s: KX9 is NOT published and an instruction "
                   "addressing k[256] was accepted - its operand mux would "
                   "address k[0]\n", who);
            failures++;
        } else {
            checks++;
            if (!strstr(cft_last_error(), "CFT_SEQ_FEAT_KX9")) {
                printf("  FAIL %s: k[256] without KX9 was refused (%s) "
                       "without naming the feature: %s\n", who,
                       cft_strerror(st), cft_last_error());
                failures++;
            }
            printf("    KX9 absent, k[256] -> %s: %s\n", cft_strerror(st),
                   cft_last_error());
        }
    }
}

/* Two images, one device, the same deposits.
 *
 * The other comparison in this file - compare_seq_one - runs one image
 * on two backends, and against `sw` that is the same code twice, which
 * catches a harness fault and a backend divergence and nothing else. A
 * fault BOTH sides share is invisible to it by construction. So where
 * a property can be stated as two programs that must agree, it is
 * stated that way instead, and the oracle is the contract rather than
 * a second copy of the implementation. */
static void compare_seq_images(cft_device *dev, cft_format fmt,
                               const uint8_t *img1, size_t bytes1,
                               const uint8_t *img2, size_t bytes2,
                               uint32_t maxdep, size_t n, uint32_t seed,
                               const char *label)
{
    size_t esz = cft_format_size(fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *c = (uint8_t *)malloc(n * esz);
    uint8_t *d1 = (uint8_t *)malloc(n * maxdep * esz + 1);
    uint8_t *d2 = (uint8_t *)malloc(n * maxdep * esz + 1);
    uint32_t *c1 = (uint32_t *)malloc(n * 4);
    uint32_t *c2 = (uint32_t *)malloc(n * 4);
    cft_program *p1 = NULL, *p2 = NULL;
    uint32_t f1 = 0, f2 = 0, s1 = 0, s2 = 0;

    if (!a || !b || !c || !d1 || !d2 || !c1 || !c2) {
        printf("  FAIL %s: out of memory\n", label);
        failures++;
        goto out;
    }
    rs = seed;
    fill(a, n, esz);
    fill(b, n, esz);
    fill(c, n, esz);
    memset(d1, 0x5a, n * maxdep * esz);
    memset(d2, 0xa5, n * maxdep * esz);

    checks++;
    if (cft_program_load(dev, img1, bytes1, &p1) != CFT_OK ||
        cft_program_load(dev, img2, bytes2, &p2) != CFT_OK) {
        printf("  FAIL %s: an image did not load: %s\n", label,
               cft_last_error());
        failures++;
        goto out;
    }
    checks++;
    if (cft_program_run(p1, a, b, c, d1, c1, n, &f1, &s1) != CFT_OK ||
        cft_program_run(p2, a, b, c, d2, c2, n, &f2, &s2) != CFT_OK) {
        printf("  FAIL %s: a run failed\n", label);
        failures++;
        goto out;
    }
    checks++;
    if (memcmp(d1, d2, n * maxdep * esz) != 0 ||
        memcmp(c1, c2, n * 4) != 0 || f1 != f2 || s1 != s2) {
        size_t i;
        for (i = 0; i < n * maxdep * esz && d1[i] == d2[i]; i++)
            ;
        printf("  FAIL %s: the two programs disagree (first differing byte "
               "%lu of %lu, flags %02x/%02x, status %02x/%02x)\n", label,
               (unsigned long)i, (unsigned long)(n * maxdep * esz),
               f1, f2, s1, s2);
        failures++;
    }
out:
    cft_program_free(p1);
    cft_program_free(p2);
    free(a); free(b); free(c); free(d1); free(d2); free(c1); free(c2);
}

/* The value 1 + 2^-k, packed per format from LAYOUT: the biased
 * exponent of 1.0 with fraction bit (sbits - k) set. k = 1 is 1.5,
 * k = 2 is 1.25. Derived from the table check_layout proves rather
 * than from four transcribed mantissa widths, which is what this
 * replaced. */
static void make_one_plus(uint8_t *e, cft_format fmt, int k)
{
    int total = LAYOUT[(int)fmt].total_bits;
    int ebits = LAYOUT[(int)fmt].exp_bits;
    int sbits = total - 1 - ebits;
    uint64_t bias = ((uint64_t)1 << (ebits - 1)) - 1;

    memset(e, 0, (size_t)total / 8);
    put_bits(e, sbits, ebits, bias);
    put_bits(e, sbits - k, 1, 1);
}

/* ==== revision 2, run against the software backend ==================
 *
 * The per-run constant bank (docs/SEQUENCER.md R3): one image, two
 * banks, two answers - and each answer equal to the run of an image
 * with those same constants BAKED IN, which is the claim that matters.
 * A bank that were quietly ignored, or read from the wrong place,
 * would still produce an answer; it would just not be that one.
 *
 * Also the digest, here rather than in its own pass, because what a
 * digest has to distinguish is exactly what this function has to
 * hand: the same image under two banks.
 * ==================================================================== */
static void compare_seq_bank(cft_device *sw, cft_device *hw,
                             cft_format fmt, size_t n, uint32_t seed)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t ext[128], baked[128 + 64];
    uint8_t bank[2][2 * MAXE];
    uint8_t k0[MAXE], k1[MAXE];
    uint64_t insns[3];
    size_t ext_bytes, baked_bytes[2];
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *dep[2], *dep_hw, *dep_baked;
    uint32_t *cnt = (uint32_t *)malloc(n * 4);
    uint32_t *cnt_baked = (uint32_t *)malloc(n * 4);
    cft_program *pe_sw = NULL, *pe_hw = NULL;
    uint8_t dig[2][32], dig2[32], dig_img[32];
    int b;

    dep[0] = (uint8_t *)malloc(n * esz);
    dep[1] = (uint8_t *)malloc(n * esz);
    dep_hw = (uint8_t *)malloc(n * esz);
    dep_baked = (uint8_t *)malloc(n * esz);
    if (!a || !cnt || !cnt_baked || !dep[0] || !dep[1] || !dep_hw ||
        !dep_baked) {
        printf("  FAIL seq bank: out of memory\n");
        failures++;
        goto out;
    }

    /* r4 = r0 * k[0] + k[1]; deposit r4; halt - both constants from
     * the bank, so nothing about the answer survives losing it. */
    insns[0] = seq_alu(0, 4, 0, 0, 1, 0, 1, 1);
    insns[1] = seq_ctrl(3, 4, 0);
    insns[2] = seq_ctrl(0, 0, 0);

    make_one_plus(k0, fmt, 1);          /* 1.5  */
    make_one_plus(k1, fmt, 2);          /* 1.25 */
    memcpy(bank[0], k0, esz);
    memcpy(bank[0] + esz, k1, esz);
    memcpy(bank[1], k1, esz);           /* the same two, swapped */
    memcpy(bank[1] + esz, k0, esz);

    ext_bytes = seq_image_flags(ext, fmt, insns, 3, NULL, 2, 1,
                                CFT_PROG_FLAG_BANK_EXT);
    checks++;
    if (ext_bytes != 32 + 3 * 8) {
        printf("  FAIL seq bank: a BANK_EXT image of 3 instructions is "
               "%lu bytes, not %lu\n", (unsigned long)ext_bytes,
               (unsigned long)(32 + 3 * 8));
        failures++;
    }
    for (b = 0; b < 2; b++)
        baked_bytes[b] = seq_image(baked, fmt, insns, 3, bank[b], 2, 1);
    (void)baked_bytes;

    if (cft_program_load(sw, ext, ext_bytes, &pe_sw) != CFT_OK ||
        cft_program_load(hw, ext, ext_bytes, &pe_hw) != CFT_OK) {
        printf("  FAIL seq bank: the BANK_EXT image did not load (%s)\n",
               cft_last_error());
        failures++;
        goto out;
    }

    /* cft_program_info carries the flag back, struct_size-gated. */
    {
        cft_program_info info;
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        checks++;
        if (cft_program_get_info(pe_sw, &info) != CFT_OK ||
            !(info.flags & CFT_PROG_FLAG_BANK_EXT) || info.n_consts != 2) {
            printf("  FAIL seq bank: cft_program_info reports flags 0x%lx, "
                   "n_consts %lu\n", (unsigned long)info.flags,
                   (unsigned long)info.n_consts);
            failures++;
        }
    }

    rs = seed;
    fill_finite(a, fmt, n);

    for (b = 0; b < 2; b++) {
        cft_program *pb = NULL;
        uint32_t fl_bank = 0, bus_bank = 0, fl_baked = 0, bus_baked = 0;
        cft_status st;

        memset(dep[b], 0x5a, n * esz);
        memset(dep_hw, 0x5a, n * esz);
        memset(dep_baked, 0x5a, n * esz);

        st = cft_program_run_bank(pe_sw, bank[b], 2 * esz, a, NULL, NULL,
                                  dep[b], cnt, n, &fl_bank, &bus_bank);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL seq bank %d: run_bank on software: %s (%s)\n",
                   b, cft_strerror(st), cft_last_error());
            failures++;
            continue;
        }
        st = cft_program_run_bank(pe_hw, bank[b], 2 * esz, a, NULL, NULL,
                                  dep_hw, NULL, n, NULL, NULL);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL seq bank %d: run_bank on the device: %s (%s)\n",
                   b, cft_strerror(st), cft_last_error());
            failures++;
        } else if (memcmp(dep[b], dep_hw, n * esz) != 0) {
            printf("  FAIL seq bank %d: the device and the software backend "
                   "deposited different bytes\n", b);
            failures++;
        }

        /* The same program with those constants baked into the image,
         * run the ordinary way. Same bits, same counts, same flags -
         * that is what "the bank is data" has to mean. */
        (void)seq_image(baked, fmt, insns, 3, bank[b], 2, 1);
        if (cft_program_load(sw, baked, baked_bytes[b], &pb) != CFT_OK) {
            printf("  FAIL seq bank %d: the baked image did not load\n", b);
            failures++;
            continue;
        }
        st = cft_program_run(pb, a, NULL, NULL, dep_baked, cnt_baked, n,
                             &fl_baked, &bus_baked);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL seq bank %d: the baked image did not run: %s\n",
                   b, cft_strerror(st));
            failures++;
        } else {
            checks++;
            if (memcmp(dep[b], dep_baked, n * esz) != 0 ||
                memcmp(cnt, cnt_baked, n * 4) != 0 ||
                fl_bank != fl_baked || bus_bank != bus_baked) {
                printf("  FAIL seq bank %d: the bank run and the baked run "
                       "disagree (flags %02x/%02x, status %02x/%02x)\n",
                       b, fl_bank, fl_baked, bus_bank, bus_baked);
                failures++;
            }
        }
        cft_program_free(pb);

        /* The digest: image then bank. */
        checks++;
        if (cft_program_digest(pe_sw, bank[b], 2 * esz, dig[b]) != CFT_OK) {
            printf("  FAIL seq bank %d: cft_program_digest: %s\n", b,
                   cft_last_error());
            failures++;
        }
    }

    /* Two banks, two digests; the same bank twice, the same digest;
     * and neither equal to the hash of the image alone, which is what
     * a digest over the schedule and not the data would have been. */
    checks++;
    if (memcmp(dig[0], dig[1], 32) == 0) {
        printf("  FAIL seq bank: two different banks gave one digest\n");
        failures++;
    }
    checks++;
    if (cft_program_digest(pe_sw, bank[0], 2 * esz, dig2) != CFT_OK ||
        memcmp(dig[0], dig2, 32) != 0) {
        printf("  FAIL seq bank: the same bank twice gave two digests\n");
        failures++;
    }
    checks++;
    if (cft_sha256(ext, ext_bytes, dig_img) != CFT_OK ||
        memcmp(dig_img, dig[0], 32) == 0) {
        printf("  FAIL seq bank: the digest of image-and-bank equals the "
               "hash of the image alone\n");
        failures++;
    }
    /* And two banks, two ANSWERS - the check that fails if the bank
     * were ignored, defaulted or read from the image. */
    checks++;
    if (memcmp(dep[0], dep[1], n * esz) == 0) {
        printf("  FAIL seq bank: two different banks gave the same "
               "deposits over %lu elements\n", (unsigned long)n);
        failures++;
    }

out:
    cft_program_free(pe_sw);
    cft_program_free(pe_hw);
    free(a); free(cnt); free(cnt_baked);
    free(dep[0]); free(dep[1]); free(dep_hw); free(dep_baked);
}

/* Every refusal ABI 0.9 adds that a device with the features cannot
 * escape: the two entry points refusing each other's programs, a bank
 * of the wrong size, and the header and encoding rules revision 2
 * brought in. The two feature-absent refusals are not here - they are
 * in check_caps_enforced, where the device that lacks the feature is.
 *
 * Each is checked BY NAME, not only by status: a caller told
 * CFT_ERR_INVALID_ARGUMENT and nothing else has to guess which of its
 * eleven arguments was wrong. */
/* ==== revision 3, run against the software backend ==================
 *
 * The per-lane scratch memory (docs/SEQUENCER.md R4) and its per-run
 * block (R5). Every case here is arranged so the EXPECTED bytes are
 * the input bytes: a scratch store and load move a register's pattern
 * and compute nothing, so what a wrong answer would need is a golden
 * model, and what a right one needs is only memcmp. The one case that
 * does arithmetic doubles an exactly-representable value, which is
 * exact in every format and rounds nowhere.
 * ==================================================================== */

/* A cft_run_args over `n` lanes with `a` and a deposit buffer and
 * nothing else, which is exactly what cft_program_run fills in. Every
 * case below starts from this and sets the one field it is about, so
 * a test that forgets to zero a field cannot pass by accident. */
static void run_args_init(cft_run_args *A, const void *a, void *deposits,
                          size_t n)
{
    memset(A, 0, sizeof *A);
    A->struct_size = sizeof *A;
    A->a           = a;
    A->n           = n;
    A->deposits    = deposits;
}

/* n * `per` elements of `buf` filled with distinct finite patterns,
 * so a block whose lanes were transposed, shifted by a lane, or read
 * from the first lane for all of them cannot pass. */
static void fill_scratch_block(uint8_t *buf, cft_format fmt, size_t n,
                               uint32_t per)
{
    fill_finite(buf, fmt, n * per);
}

/* An unsigned integer as a raw bit pattern in one element, which is
 * where the atlas emitter keeps its loop counters and where STX and
 * LDX read their slot from. NOT a float: the value is the pattern. */
static void put_index(uint8_t *e, cft_format fmt, uint32_t v)
{
    size_t sz = cft_format_size(fmt), j;
    memset(e, 0, sz);
    for (j = 0; j < sz && j < 4; j++)
        e[j] = (uint8_t)(v >> (8 * j));
}

static void check_scratch(cft_device *dev, cft_format fmt, size_t n)
{
    const size_t esz = cft_format_size(fmt);
    cft_caps c;
    uint8_t img[1024];
    uint64_t ins[16];
    size_t bytes;
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *cc = (uint8_t *)malloc(n * esz);
    uint8_t *dep = (uint8_t *)malloc(n * 2 * esz);
    uint8_t *sin_buf = (uint8_t *)malloc(n * 3 * esz);
    uint8_t *sout_buf = (uint8_t *)malloc(n * 2 * esz);
    uint32_t *cnt = (uint32_t *)malloc(n * 4);
    cft_program *prog = NULL;
    cft_run_args A;
    uint32_t top;
    size_t i;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    if (cft_get_caps(dev, &c) != CFT_OK ||
        !(c.seq_features & CFT_SEQ_FEAT_SCRATCH)) {
        printf("  no scratch on this device, R4/R5 not run\n");
        goto out;
    }
    if (!a || !b || !cc || !dep || !sin_buf || !sout_buf || !cnt) {
        printf("  FAIL seq scratch: out of memory\n");
        failures++;
        goto out;
    }
    top = c.max_scratch ? c.max_scratch - 1u : 255u;
    fill_finite(a, fmt, n);
    fill_finite(b, fmt, n);

    /* ---- 1. STL/LDL round trips, including the highest slot -------
     * Slot 0 takes r0 and the top slot takes r1, then both are read
     * back and deposited in the other order. The deposits must be the
     * INPUT BYTES: a scratch cell that aliased its neighbour, dropped
     * a bit of the slot index or never wrote at all gives something
     * else. */
    ins[0] = seq_stl(0, 0);
    ins[1] = seq_stl(1, top);
    ins[2] = seq_ldl(4, top);
    ins[3] = seq_ldl(5, 0);
    ins[4] = seq_ctrl(3, 4, 0);
    ins[5] = seq_ctrl(3, 5, 0);
    ins[6] = seq_ctrl(0, 0, 0);
    bytes = seq_image(img, fmt, ins, 7, NULL, 0, 2);
    checks++;
    if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
        printf("  FAIL seq scratch: the STL/LDL image did not load: %s\n",
               cft_last_error());
        failures++;
    } else {
        uint32_t fl = 0xFFu;
        checks++;
        if (cft_program_run(prog, a, b, NULL, dep, cnt, n, &fl, NULL)
            != CFT_OK) {
            printf("  FAIL seq scratch: the STL/LDL program did not run: "
                   "%s\n", cft_last_error());
            failures++;
        } else {
            int bad = 0;
            for (i = 0; i < n; i++) {
                if (memcmp(dep + (2 * i) * esz, b + i * esz, esz) != 0 ||
                    memcmp(dep + (2 * i + 1) * esz, a + i * esz, esz) != 0 ||
                    cnt[i] != 2)
                    bad = 1;
            }
            checks++;
            if (bad) {
                printf("  FAIL seq scratch: an STL/LDL round trip through "
                       "slots 0 and %lu did not return the inputs\n",
                       (unsigned long)top);
                failures++;
            }
            checks++;
            if (fl != 0) {
                printf("  FAIL seq scratch: a store and a load raised "
                       "flags 0x%02x - neither is arithmetic\n", fl);
                failures++;
            }
        }
        cft_program_free(prog);
        prog = NULL;
    }

    /* ---- 2. STX/LDX reduce modulo the depth ------------------------
     * r2 holds the bit pattern 3 * SCRATCH_D + 5, an unsigned integer
     * well past the memory. The contract REDUCES it rather than
     * refusing it, so both indexed forms must land on slot 5 - which
     * the static forms then read and write, so an implementation that
     * reduced by something else, or that refused, fails here. */
    if (c.max_scratch) {
        const uint32_t idx = 3u * c.max_scratch + 5u;
        for (i = 0; i < n; i++)
            put_index(cc + i * esz, fmt, idx);
        ins[0] = seq_stl(0, 5);          /* slot 5 := a */
        ins[1] = seq_ldx(4, 2);          /* r4 := scratch[r2 mod D] */
        ins[2] = seq_ctrl(3, 4, 0);      /* deposit a */
        ins[3] = seq_stx(1, 2);          /* scratch[r2 mod D] := b */
        ins[4] = seq_ldl(5, 5);          /* r5 := slot 5 */
        ins[5] = seq_ctrl(3, 5, 0);      /* deposit b */
        ins[6] = seq_ctrl(0, 0, 0);
        bytes = seq_image(img, fmt, ins, 7, NULL, 0, 2);
        checks++;
        if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
            printf("  FAIL seq scratch: the STX/LDX image did not load: "
                   "%s\n", cft_last_error());
            failures++;
        } else {
            checks++;
            if (cft_program_run(prog, a, b, cc, dep, cnt, n, NULL, NULL)
                != CFT_OK) {
                printf("  FAIL seq scratch: the STX/LDX program did not "
                       "run: %s\n", cft_last_error());
                failures++;
            } else {
                int bad = 0;
                for (i = 0; i < n; i++)
                    if (memcmp(dep + (2 * i) * esz, a + i * esz, esz) != 0 ||
                        memcmp(dep + (2 * i + 1) * esz, b + i * esz,
                               esz) != 0)
                        bad = 1;
                checks++;
                if (bad) {
                    printf("  FAIL seq scratch: an index of %lu did not "
                           "reduce to slot 5 modulo %lu\n",
                           (unsigned long)idx,
                           (unsigned long)c.max_scratch);
                    failures++;
                }
            }
            cft_program_free(prog);
            prog = NULL;
        }
    }

    /* ---- 3. A store is masked by the active bit --------------------
     * Two halves of one claim. The first STL runs with every lane
     * inactive and must write nothing; the second is the body of an
     * all-inactive loop, which the early exit skips entirely. Either
     * failing gives b where a was due, or a stored value where +0 was.
     * That is P3: an all-inactive loop body is a no-op, and a store
     * is a register write for its purposes. */
    ins[0]  = seq_stl(0, 0);             /* slot 0 := a, all active */
    ins[1]  = seq_ctrl(4, 3, 0);         /* SETACT r3 - r3 is +0 */
    ins[2]  = seq_stl(1, 0);             /* masked: slot 0 keeps a */
    ins[3]  = seq_ctrl(1, 0, 4);         /* REPEAT 4 */
    ins[4]  = seq_stl(1, 1);             /*   masked: slot 1 stays +0 */
    ins[5]  = seq_ctrl(2, 0, 0);         /* ENDREP */
    ins[6]  = seq_ctrl(5, 0, 0);         /* ACTALL */
    ins[7]  = seq_ldl(4, 0);
    ins[8]  = seq_ldl(5, 1);
    ins[9]  = seq_ctrl(3, 4, 0);
    ins[10] = seq_ctrl(3, 5, 0);
    ins[11] = seq_ctrl(0, 0, 0);
    bytes = seq_image(img, fmt, ins, 12, NULL, 0, 2);
    checks++;
    if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
        printf("  FAIL seq scratch: the masked-store image did not load: "
               "%s\n", cft_last_error());
        failures++;
    } else {
        uint8_t zero[MAXE];
        int bad = 0;
        memset(zero, 0, esz);
        checks++;
        if (cft_program_run(prog, a, b, NULL, dep, cnt, n, NULL, NULL)
            != CFT_OK) {
            printf("  FAIL seq scratch: the masked-store program did not "
                   "run: %s\n", cft_last_error());
            failures++;
        } else {
            for (i = 0; i < n; i++)
                if (memcmp(dep + (2 * i) * esz, a + i * esz, esz) != 0 ||
                    memcmp(dep + (2 * i + 1) * esz, zero, esz) != 0)
                    bad = 1;
            checks++;
            if (bad) {
                printf("  FAIL seq scratch: a store by an inactive lane "
                       "reached the memory\n");
                failures++;
            }
        }
        cft_program_free(prog);
        prog = NULL;
    }

    /* ---- 4 and 5. The per-run block, in and out --------------------
     * Three slots a lane in, two out, over n lanes - which the caller
     * makes larger than one 64-lane block, so the lane-major layout
     * and the block boundary are both exercised. The program reads
     * slots 0 and 2 of the preloaded block and deposits them, then
     * stores r0 and r1 into slots 0 and 1, so the scratch-out block
     * must hold the inputs lane by lane and the deposits must hold the
     * preloaded values. Getting both right at once is what pins the
     * ORDER down: the preload happens before the first instruction and
     * the writeback after the last. */
    if (c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) {
        fill_scratch_block(sin_buf, fmt, n, 3);
        memset(sout_buf, 0xA5, n * 2 * esz);
        ins[0] = seq_ldl(4, 0);
        ins[1] = seq_ldl(5, 2);
        ins[2] = seq_ctrl(3, 4, 0);
        ins[3] = seq_ctrl(3, 5, 0);
        ins[4] = seq_stl(0, 0);
        ins[5] = seq_stl(1, 1);
        ins[6] = seq_ctrl(0, 0, 0);
        bytes = seq_image_scratch(img, fmt, ins, 7, NULL, 0, 2,
                                  CFT_PROG_FLAG_SCRATCH_IO, 3, 2);
        checks++;
        if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
            printf("  FAIL seq scratch: the SCRATCH_IO image did not load: "
                   "%s\n", cft_last_error());
            failures++;
        } else {
            cft_program_info info;
            memset(&info, 0, sizeof info);
            info.struct_size = sizeof info;
            checks++;
            if (cft_program_get_info(prog, &info) != CFT_OK ||
                info.n_scratch_in != 3 || info.n_scratch_out != 2 ||
                info.scratch_used != 3) {
                printf("  FAIL seq scratch: cft_program_info reports "
                       "%lu/%lu in/out and %lu used, not 3/2 and 3\n",
                       (unsigned long)info.n_scratch_in,
                       (unsigned long)info.n_scratch_out,
                       (unsigned long)info.scratch_used);
                failures++;
            }
            run_args_init(&A, a, dep, n);
            A.b                 = b;
            A.counts            = cnt;
            A.scratch_in        = sin_buf;
            A.scratch_in_bytes  = n * 3 * esz;
            A.scratch_out       = sout_buf;
            A.scratch_out_bytes = n * 2 * esz;
            checks++;
            if (cft_program_run_ex(prog, &A) != CFT_OK) {
                printf("  FAIL seq scratch: the SCRATCH_IO program did not "
                       "run: %s\n", cft_last_error());
                failures++;
            } else {
                int bad_in = 0, bad_out = 0;
                for (i = 0; i < n; i++) {
                    if (memcmp(dep + (2 * i) * esz,
                               sin_buf + (3 * i) * esz, esz) != 0 ||
                        memcmp(dep + (2 * i + 1) * esz,
                               sin_buf + (3 * i + 2) * esz, esz) != 0)
                        bad_in = 1;
                    if (memcmp(sout_buf + (2 * i) * esz, a + i * esz,
                               esz) != 0 ||
                        memcmp(sout_buf + (2 * i + 1) * esz, b + i * esz,
                               esz) != 0)
                        bad_out = 1;
                }
                checks++;
                if (bad_in) {
                    printf("  FAIL seq scratch: the preloaded block did not "
                           "reach the lanes it belongs to (n = %lu, three "
                           "slots a lane)\n", (unsigned long)n);
                    failures++;
                }
                checks++;
                if (bad_out) {
                    printf("  FAIL seq scratch: the scratch-out block does "
                           "not hold each lane's own stores (n = %lu, two "
                           "slots a lane)\n", (unsigned long)n);
                    failures++;
                }
            }
            cft_program_free(prog);
            prog = NULL;
        }
    }

    /* ---- 6. A resumable program -----------------------------------
     * The whole point of R5. One slot in, one slot out, and a body
     * that doubles the state K times - exact in every format, so the
     * comparison is bytes and not a tolerance. Three doublings twice,
     * chained through the block, must equal six doublings once: the
     * state that came out is the state that goes back in, and a run is
     * resumable.
     *
     * A program that quietly restarted from +0, preloaded the wrong
     * lane, or wrote the block before the loop rather than after it
     * would give a different answer to at least one of the two. */
    if (c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) {
        uint8_t *state = (uint8_t *)malloc(n * esz);
        uint8_t *once = (uint8_t *)malloc(n * esz);
        uint8_t *dep1 = (uint8_t *)malloc(n * esz);
        int step;
        if (!state || !once || !dep1) {
            printf("  FAIL seq scratch: out of memory\n");
            failures++;
            free(state); free(once); free(dep1);
            goto out;
        }
        for (step = 0; step < 2; step++) {
            const uint32_t trips = step ? 6u : 3u;
            uint8_t *out_buf = step ? once : state;
            ins[0] = seq_ldl(4, 0);
            ins[1] = seq_ctrl(1, 0, trips);           /* REPEAT trips */
            ins[2] = seq_alu(1, 4, 4, 0, 4, 0, 0, 0); /* r4 = r4 + r4 */
            ins[3] = seq_ctrl(2, 0, 0);               /* ENDREP */
            ins[4] = seq_stl(4, 0);
            ins[5] = seq_ctrl(3, 4, 0);
            ins[6] = seq_ctrl(0, 0, 0);
            bytes = seq_image_scratch(img, fmt, ins, 7, NULL, 0, 1,
                                      CFT_PROG_FLAG_SCRATCH_IO, 1, 1);
            checks++;
            if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
                printf("  FAIL seq scratch: the resumable image did not "
                       "load: %s\n", cft_last_error());
                failures++;
                break;
            }
            run_args_init(&A, a, dep1, n);
            A.scratch_in        = a;      /* the seed, both times */
            A.scratch_in_bytes  = n * esz;
            A.scratch_out       = out_buf;
            A.scratch_out_bytes = n * esz;
            checks++;
            if (cft_program_run_ex(prog, &A) != CFT_OK) {
                printf("  FAIL seq scratch: the resumable program did not "
                       "run: %s\n", cft_last_error());
                failures++;
                cft_program_free(prog);
                prog = NULL;
                break;
            }
            if (step == 0) {
                /* the second half of the chain: the state that came
                 * out goes straight back in, three more doublings */
                run_args_init(&A, a, dep1, n);
                A.scratch_in        = state;
                A.scratch_in_bytes  = n * esz;
                A.scratch_out       = sout_buf;
                A.scratch_out_bytes = n * esz;
                checks++;
                if (cft_program_run_ex(prog, &A) != CFT_OK) {
                    printf("  FAIL seq scratch: the resumed run failed: "
                           "%s\n", cft_last_error());
                    failures++;
                }
            }
            cft_program_free(prog);
            prog = NULL;
        }
        checks++;
        if (memcmp(sout_buf, once, n * esz) != 0) {
            printf("  FAIL seq scratch: two runs of three doublings chained "
                   "through the block do not equal one run of six\n");
            failures++;
        }
        /* And the negative control the claim needs: six doublings is
         * not three, so a chain that had silently restarted would have
         * produced `state` here and passed nothing. */
        checks++;
        if (memcmp(state, once, n * esz) == 0) {
            printf("  FAIL seq scratch: three doublings and six gave the "
                   "same bytes, so the comparison above proves nothing\n");
            failures++;
        }
        free(state); free(once); free(dep1);
    }

    /* ---- 6b. BOTH flags at once ------------------------------------
     * A program may be BANK_EXT and SCRATCH_IO together, and then one
     * run_ex carries the bank AND both blocks. Nothing in either
     * feature says the other is excluded, so the combination is legal
     * and is the one shape no test above reaches: the bank arrives
     * whole, the scratch arrives per lane, and a backend that packed
     * them in the wrong order would still answer.
     *
     * r4 = LDL slot 0; r4 = r4 * k[0]; deposit r4; STL r4 -> slot 0.
     * The bank's one constant is 1.0, so the deposit is the preloaded
     * value exactly and the block that comes back is it too. */
    if ((c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) &&
        (c.seq_features & CFT_SEQ_FEAT_BANK_PTR)) {
        uint8_t bank[MAXE];
        make_pow2(bank, fmt, 0);                 /* 1.0 */
        ins[0] = seq_ldl(4, 0);
        ins[1] = seq_alu(CFT_MUL, 4, 4, 0, 0, 0, 1, 0);  /* r4 *= k[0] */
        ins[2] = seq_ctrl(3, 4, 0);
        ins[3] = seq_stl(4, 0);
        ins[4] = seq_ctrl(0, 0, 0);
        bytes = seq_image_scratch(img, fmt, ins, 5, NULL, 1, 1,
                                  CFT_PROG_FLAG_BANK_EXT |
                                  CFT_PROG_FLAG_SCRATCH_IO, 1, 1);
        checks++;
        if (bytes != 32 + 5 * 8) {
            printf("  FAIL seq scratch: a BANK_EXT + SCRATCH_IO image is "
                   "%lu bytes, not %lu\n", (unsigned long)bytes,
                   (unsigned long)(32 + 5 * 8));
            failures++;
        }
        checks++;
        if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
            printf("  FAIL seq scratch: the BANK_EXT + SCRATCH_IO image did "
                   "not load: %s\n", cft_last_error());
            failures++;
        } else {
            fill_finite(sin_buf, fmt, n);
            memset(sout_buf, 0xA5, n * esz);
            run_args_init(&A, a, dep, n);
            A.bank              = bank;
            A.bank_bytes        = esz;
            A.scratch_in        = sin_buf;
            A.scratch_in_bytes  = n * esz;
            A.scratch_out       = sout_buf;
            A.scratch_out_bytes = n * esz;
            checks++;
            if (cft_program_run_ex(prog, &A) != CFT_OK) {
                printf("  FAIL seq scratch: the BANK_EXT + SCRATCH_IO "
                       "program did not run: %s\n", cft_last_error());
                failures++;
            } else {
                checks++;
                if (memcmp(dep, sin_buf, n * esz) != 0 ||
                    memcmp(sout_buf, sin_buf, n * esz) != 0) {
                    printf("  FAIL seq scratch: one run_ex did not carry "
                           "the bank and both blocks at once\n");
                    failures++;
                }
            }
            cft_program_free(prog);
            prog = NULL;
        }
    }

    /* ---- 7. A constant at index 511, through kx's ninth bit --------
     * A bank of 512 where every constant is 2.0 but the last, which is
     * 1.0, and one MUL naming k[511]. The deposit must be a[i]
     * exactly: an operand mux that dropped the ninth bit would read
     * k[255] and deposit twice that, which is the failure CAPS[7]
     * exists to prevent and the reason this test multiplies rather
     * than adds. */
    if ((c.seq_features & CFT_SEQ_FEAT_KX9) && c.max_consts >= 512u) {
        uint8_t *konst = (uint8_t *)malloc(512 * esz);
        uint8_t *img9 = (uint8_t *)malloc(512 * esz + 64);
        if (!konst || !img9) {
            printf("  FAIL seq scratch: out of memory\n");
            failures++;
        } else {
            uint32_t j;
            for (j = 0; j < 512; j++)
                make_pow2(konst + (size_t)j * esz, fmt, 1);   /* 2.0 */
            make_pow2(konst + 511u * (size_t)esz, fmt, 0);    /* 1.0 */
            ins[0] = seq_alu_kx9(CFT_MUL, 4, 0, 511, 0, 0, 1, 0);
            ins[1] = seq_ctrl(3, 4, 0);
            ins[2] = seq_ctrl(0, 0, 0);
            bytes = seq_image(img9, fmt, ins, 3, konst, 512, 1);
            checks++;
            if (cft_program_load(dev, img9, bytes, &prog) != CFT_OK) {
                printf("  FAIL seq scratch: the k[511] image did not load: "
                       "%s\n", cft_last_error());
                failures++;
            } else {
                checks++;
                if (cft_program_run(prog, a, NULL, NULL, dep, NULL, n,
                                    NULL, NULL) != CFT_OK) {
                    printf("  FAIL seq scratch: the k[511] program did not "
                           "run: %s\n", cft_last_error());
                    failures++;
                } else {
                    checks++;
                    if (memcmp(dep, a, n * esz) != 0) {
                        printf("  FAIL seq scratch: k[511] did not multiply "
                               "by one - the ninth index bit was dropped\n");
                        failures++;
                    }
                }
                cft_program_free(prog);
                prog = NULL;
            }
        }
        free(konst);
        free(img9);
    }

out:
    cft_program_free(prog);
    free(a); free(b); free(cc); free(dep);
    free(sin_buf); free(sout_buf); free(cnt);
}

static void refusal(cft_device *dev, cft_format fmt, const char *label,
                    const uint8_t *img, size_t bytes, cft_status want,
                    const char *needle)
{
    cft_program *prog = NULL;
    cft_status st = cft_program_load(dev, img, bytes, &prog);
    (void)fmt;
    checks++;
    if (st != want) {
        printf("  FAIL refusal %s: %s where %s was due\n", label,
               cft_strerror(st), cft_strerror(want));
        failures++;
        cft_program_free(prog);
        return;
    }
    if (needle && !strstr(cft_last_error(), needle)) {
        checks++;
        printf("  FAIL refusal %s: refused as %s but the message does not "
               "say \"%s\": %s\n", label, cft_strerror(st), needle,
               cft_last_error());
        failures++;
    }
}

static void check_program_refusals(cft_device *dev, cft_format fmt)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t img[256], konst[2 * MAXE], bank[2 * MAXE];
    uint64_t insns[3];
    size_t bytes;
    cft_program *prog = NULL;
    cft_status st;

    make_one_plus(konst, fmt, 1);
    make_one_plus(konst + esz, fmt, 2);
    memcpy(bank, konst, 2 * esz);

    insns[0] = seq_alu(0, 4, 0, 0, 1, 0, 1, 1);
    insns[1] = seq_ctrl(3, 4, 0);
    insns[2] = seq_ctrl(0, 0, 0);

    /* ---- the header ---- */
    /* Bit 1 was the unassigned bit until revision 3 took it for
     * SCRATCH_IO, and bit 2 until revision 4 took it for
     * SCRATCH_STRICT, so this has moved up twice now - which is exactly
     * what the check is about: a flag this library cannot read is an
     * image it cannot read, whichever bit it is. The bit named here has
     * to be one SEQ_FLAGS_KNOWN does not carry, so when revision 5
     * assigns it, MOVE this rather than deleting it. */
    bytes = seq_image_flags(img, fmt, insns, 3, konst, 2, 1, 8u);
    refusal(dev, fmt, "flags bit 3 (unassigned)", img, bytes,
            CFT_ERR_ARTIFACT, NULL);
    bytes = seq_image_flags(img, fmt, insns, 3, konst, 2, 1, 0x80000000u);
    refusal(dev, fmt, "flags bit 31", img, bytes, CFT_ERR_ARTIFACT, NULL);
    /* scratch_io non-zero with SCRATCH_IO clear: the word is
     * meaningful only under the flag and is the reserved word it
     * always was without it. */
    bytes = seq_image(img, fmt, insns, 3, konst, 2, 1);
    put_le32(img + 28, 1);
    refusal(dev, fmt, "scratch_io non-zero with the flag clear", img, bytes,
            CFT_ERR_ARTIFACT, NULL);
    /* A BANK_EXT image that still carries its constant section is the
     * wrong LENGTH, and a program is exactly its header, its
     * constants and its instructions. */
    bytes = seq_image(img, fmt, insns, 3, konst, 2, 1);
    put_le32(img + 24, CFT_PROG_FLAG_BANK_EXT);
    refusal(dev, fmt, "BANK_EXT with a constant section", img, bytes,
            CFT_ERR_ARTIFACT, NULL);

    /* ---- the encoding ---- */
    {
        uint64_t bad[3];
        memcpy(bad, insns, sizeof bad);
        /* imm[31:28]: read by nothing */
        bad[0] = insns[0] | ((uint64_t)0x10000000u << 32);
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "imm[28] on an ALU instruction", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* a constant operand's fifth bit: not read, must be zero */
        bad[0] = insns[0] | ((uint64_t)(1u << 26) << 32);  /* rb's, kb set */
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "a constant operand's register high bit", img,
                bytes, CFT_ERR_INVALID_ARGUMENT, NULL);
        /* DEPOSIT may set imm[25] and nothing else */
        memcpy(bad, insns, sizeof bad);
        bad[1] = insns[1] | ((uint64_t)(1u << 24) << 32);
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "imm[24] on a DEPOSIT", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* and HALT may set none of them */
        memcpy(bad, insns, sizeof bad);
        bad[2] = insns[2] | ((uint64_t)(1u << 25) << 32);
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "imm[25] on a HALT", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* imm[31] stays reserved-must-be-zero, which is the version
         * guard for whatever comes after revision 3 - so it is checked
         * apart from imm[30:28], which are now the ninth index bits */
        memcpy(bad, insns, sizeof bad);
        bad[0] = insns[0] | ((uint64_t)0x80000000u << 32);
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "imm[31] on an ALU instruction", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* a ninth index bit without kx: read by nothing */
        memcpy(bad, insns, sizeof bad);
        bad[0] = insns[0] | ((uint64_t)0x10000000u << 32);
        bytes = seq_image(img, fmt, bad, 3, konst, 2, 1);
        refusal(dev, fmt, "imm[28] without kx", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* and a ninth index bit under kx belonging to an operand that
         * names a REGISTER: also read by nothing. kb selects the bank
         * here, so ka's bit (imm[28]) is the unread one. */
        {
            uint64_t k[3];
            k[0] = seq_alu_kx(0, 4, 0, 1, 2, 0, 1, 0) |
                   ((uint64_t)0x10000000u << 32);
            k[1] = insns[1];
            k[2] = insns[2];
            bytes = seq_image(img, fmt, k, 3, konst, 2, 1);
            refusal(dev, fmt, "imm[28] for a register operand under kx",
                    img, bytes, CFT_ERR_INVALID_ARGUMENT, NULL);
        }
    }

    /* ---- the four scratch codes' field rules ---- */
    {
        uint64_t s[4];
        s[0] = seq_stl(0, 3);
        s[1] = seq_ldl(4, 3);
        s[2] = seq_ctrl(3, 4, 0);
        s[3] = seq_ctrl(0, 0, 0);
        /* The positive control first: the same four instructions with
         * every field where the encoding puts it must LOAD, or the
         * seven refusals below would all be passing for the wrong
         * reason. */
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        checks++;
        if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
            printf("  FAIL refusal: the well-formed STL/LDL program was "
                   "refused: %s\n", cft_last_error());
            failures++;
        }
        cft_program_free(prog);
        prog = NULL;

        /* STL writes no register, so rd is a field it does not read */
        s[0] = seq_stl(0, 3) | ((uint64_t)2u << 8);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "rd on an STL", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* LDL reads no source register */
        s[0] = seq_stl(0, 3);
        s[1] = seq_ldl(4, 3) | ((uint64_t)2u << 12);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "ra on an LDL", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* the indexed forms take their slot from rb, so imm[23:0] is a
         * field neither of them reads */
        s[0] = seq_stx(0, 1) | ((uint64_t)5u << 32);
        s[1] = seq_ldx(4, 1);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "imm[23:0] on an STX", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        s[0] = seq_stx(0, 1);
        s[1] = seq_ldx(4, 1) | ((uint64_t)5u << 32);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "imm[23:0] on an LDX", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        /* and no scratch code carries a rounding attribute or a k
         * flag: neither is arithmetic */
        s[0] = seq_stl(0, 3) | ((uint64_t)1u << 24);
        s[1] = seq_ldl(4, 3);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "rnd on an STL", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
        s[0] = seq_stl(0, 3) | ((uint64_t)1u << 27);
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        refusal(dev, fmt, "ka on an STL", img, bytes,
                CFT_ERR_INVALID_ARGUMENT, NULL);
    }

    /* ---- the scratch_io word itself ---- */
    {
        uint64_t s[2];
        cft_caps cc;
        s[0] = seq_ctrl(0, 0, 0);
        s[1] = seq_ctrl(0, 0, 0);
        memset(&cc, 0, sizeof cc);
        cc.struct_size = sizeof cc;
        if (cft_get_caps(dev, &cc) == CFT_OK && cc.max_scratch) {
            bytes = seq_image_scratch(img, fmt, s, 2, NULL, 0, 1,
                                      CFT_PROG_FLAG_SCRATCH_IO,
                                      cc.max_scratch + 1u, 0);
            refusal(dev, fmt, "n_scratch_in past max_scratch", img, bytes,
                    CFT_ERR_UNSUPPORTED, "n_scratch_in");
            bytes = seq_image_scratch(img, fmt, s, 2, NULL, 0, 1,
                                      CFT_PROG_FLAG_SCRATCH_IO, 0,
                                      cc.max_scratch + 1u);
            refusal(dev, fmt, "n_scratch_out past max_scratch", img, bytes,
                    CFT_ERR_UNSUPPORTED, "n_scratch_out");
        }
    }

    /* ---- the two entry points, refusing each other's programs ---- */
    bytes = seq_image(img, fmt, insns, 3, konst, 2, 1);
    if (cft_program_load(dev, img, bytes, &prog) == CFT_OK) {
        uint8_t dep[MAXE];
        st = cft_program_run_bank(prog, bank, 2 * esz, konst, NULL, NULL,
                                  dep, NULL, 1, NULL, NULL);
        checks++;
        if (st != CFT_ERR_INVALID_ARGUMENT ||
            !strstr(cft_last_error(), "cft_program_run")) {
            printf("  FAIL refusal: run_bank on a program that carries its "
                   "own constants gave %s (%s)\n", cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        /* and a NULL bank of zero bytes is the same call as
         * cft_program_run, which is what makes run_bank universal */
        checks++;
        st = cft_program_run_bank(prog, NULL, 0, konst, NULL, NULL, dep,
                                  NULL, 1, NULL, NULL);
        if (st != CFT_OK) {
            printf("  FAIL refusal: run_bank with no bank on an ordinary "
                   "program gave %s (%s)\n", cft_strerror(st),
                   cft_last_error());
            failures++;
        }
        cft_program_free(prog);
        prog = NULL;
    }

    bytes = seq_image_flags(img, fmt, insns, 3, NULL, 2, 1,
                            CFT_PROG_FLAG_BANK_EXT);
    if (cft_program_load(dev, img, bytes, &prog) == CFT_OK) {
        uint8_t dep[MAXE];
        st = cft_program_run(prog, konst, NULL, NULL, dep, NULL, 1,
                             NULL, NULL);
        checks++;
        if (st != CFT_ERR_INVALID_ARGUMENT ||
            !strstr(cft_last_error(), "cft_program_run_bank")) {
            printf("  FAIL refusal: cft_program_run on a BANK_EXT program "
                   "gave %s (%s)\n", cft_strerror(st), cft_last_error());
            failures++;
        }
        st = cft_program_run_bank(prog, bank, 2 * esz - 1, konst, NULL,
                                  NULL, dep, NULL, 1, NULL, NULL);
        checks++;
        if (st != CFT_ERR_INVALID_ARGUMENT ||
            !strstr(cft_last_error(), "bank")) {
            printf("  FAIL refusal: a bank one byte short gave %s (%s)\n",
                   cft_strerror(st), cft_last_error());
            failures++;
        }
        st = cft_program_run_bank(prog, NULL, 0, konst, NULL, NULL, dep,
                                  NULL, 1, NULL, NULL);
        checks++;
        if (st != CFT_ERR_INVALID_ARGUMENT) {
            printf("  FAIL refusal: a BANK_EXT program ran with no bank at "
                   "all (%s)\n", cft_strerror(st));
            failures++;
        }
        /* the digest holds the bank to the same rule, so a program has
         * one digest and not two */
        {
            uint8_t d[32];
            checks++;
            if (cft_program_digest(prog, NULL, 0, d) !=
                CFT_ERR_INVALID_ARGUMENT) {
                printf("  FAIL refusal: cft_program_digest accepted a "
                       "BANK_EXT program with no bank\n");
                failures++;
            }
        }
        cft_program_free(prog);
        prog = NULL;
    }

    /* ---- run_ex, and the scratch block's own refusals (ABI 0.10) ---- */
    {
        uint64_t s[4];
        uint8_t dep[MAXE], sin_buf[4 * MAXE], sout_buf[4 * MAXE];
        cft_run_args A;

        memset(sin_buf, 0, sizeof sin_buf);
        memset(sout_buf, 0, sizeof sout_buf);
        s[0] = seq_stl(0, 0);
        s[1] = seq_ldl(4, 0);
        s[2] = seq_ctrl(3, 4, 0);
        s[3] = seq_ctrl(0, 0, 0);

        /* An ORDINARY program refuses a scratch block, for the same
         * reason it refuses a bank: a block that was quietly ignored
         * is a caller and a library disagreeing about what ran. */
        bytes = seq_image(img, fmt, s, 4, NULL, 0, 1);
        if (cft_program_load(dev, img, bytes, &prog) == CFT_OK) {
            run_args_init(&A, konst, dep, 1);
            A.scratch_in       = sin_buf;
            A.scratch_in_bytes = esz;
            checks++;
            st = cft_program_run_ex(prog, &A);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "declares no scratch I/O")) {
                printf("  FAIL refusal: a scratch block on a program that "
                       "declares none gave %s (%s)\n", cft_strerror(st),
                       cft_last_error());
                failures++;
            }
            /* and the struct's own size handshake, both directions */
            run_args_init(&A, konst, dep, 1);
            A.struct_size = sizeof A - 1u;
            checks++;
            st = cft_program_run_ex(prog, &A);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "struct_size")) {
                printf("  FAIL refusal: a short cft_run_args gave %s (%s)\n",
                       cft_strerror(st), cft_last_error());
                failures++;
            }
            run_args_init(&A, konst, dep, 1);
            A.struct_size = sizeof A + 8u;
            checks++;
            st = cft_program_run_ex(prog, &A);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "ignored")) {
                printf("  FAIL refusal: a long cft_run_args gave %s (%s)\n",
                       cft_strerror(st), cft_last_error());
                failures++;
            }
            /* the plain run through run_ex, so the three above are not
             * the only thing this program can do */
            run_args_init(&A, konst, dep, 1);
            checks++;
            if (cft_program_run_ex(prog, &A) != CFT_OK) {
                printf("  FAIL refusal: run_ex with no bank and no scratch "
                       "on an ordinary program gave %s\n", cft_last_error());
                failures++;
            }
            cft_program_free(prog);
            prog = NULL;
        }

        /* A SCRATCH_IO program refuses both older entry points by
         * name, and refuses a block that is not the size its header
         * says. */
        bytes = seq_image_scratch(img, fmt, s, 4, NULL, 0, 1,
                                  CFT_PROG_FLAG_SCRATCH_IO, 2, 2);
        if (cft_program_load(dev, img, bytes, &prog) == CFT_OK) {
            checks++;
            st = cft_program_run(prog, konst, NULL, NULL, dep, NULL, 1,
                                 NULL, NULL);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "cft_program_run_ex")) {
                printf("  FAIL refusal: cft_program_run on a SCRATCH_IO "
                       "program gave %s (%s)\n", cft_strerror(st),
                       cft_last_error());
                failures++;
            }
            checks++;
            st = cft_program_run_bank(prog, NULL, 0, konst, NULL, NULL, dep,
                                      NULL, 1, NULL, NULL);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "cft_program_run_ex")) {
                printf("  FAIL refusal: cft_program_run_bank on a "
                       "SCRATCH_IO program gave %s (%s)\n", cft_strerror(st),
                       cft_last_error());
                failures++;
            }
            /* one element short */
            run_args_init(&A, konst, dep, 1);
            A.scratch_in        = sin_buf;
            A.scratch_in_bytes  = esz;
            A.scratch_out       = sout_buf;
            A.scratch_out_bytes = 2 * esz;
            checks++;
            st = cft_program_run_ex(prog, &A);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "scratch-in")) {
                printf("  FAIL refusal: a scratch-in block one element "
                       "short gave %s (%s)\n", cft_strerror(st),
                       cft_last_error());
                failures++;
            }
            /* and none at all */
            run_args_init(&A, konst, dep, 1);
            checks++;
            st = cft_program_run_ex(prog, &A);
            if (st != CFT_ERR_INVALID_ARGUMENT ||
                !strstr(cft_last_error(), "scratch-in")) {
                printf("  FAIL refusal: a SCRATCH_IO program ran with no "
                       "scratch block at all (%s)\n", cft_strerror(st));
                failures++;
            }
            /* the well-formed call, so the three above are refusals of
             * something and not of everything */
            run_args_init(&A, konst, dep, 1);
            A.scratch_in        = sin_buf;
            A.scratch_in_bytes  = 2 * esz;
            A.scratch_out       = sout_buf;
            A.scratch_out_bytes = 2 * esz;
            checks++;
            if (cft_program_run_ex(prog, &A) != CFT_OK) {
                printf("  FAIL refusal: the well-formed run_ex was refused: "
                       "%s\n", cft_last_error());
                failures++;
            }
            cft_program_free(prog);
            prog = NULL;
        }
    }
}

static void compare_seq(cft_device *sw, cft_device *hw, cft_format fmt,
                        size_t n, uint32_t seed)
{
    uint8_t image[1024];
    uint8_t konst[MAXE];
    cft_caps hcaps;
    size_t bytes;

    memset(&hcaps, 0, sizeof hcaps);
    hcaps.struct_size = sizeof hcaps;
    if (cft_get_caps(hw, &hcaps) != CFT_OK)
        memset(&hcaps, 0, sizeof hcaps);

    /* the constant 1.5 */
    make_one_plus(konst, fmt, 1);

    /* 1. fma then deposit: r4 = r0*r1 + r2; deposit r4 */
    {
        uint64_t insns[3];
        insns[0] = seq_alu(0, 4, 0, 1, 2, 0, 0, 0);
        insns[1] = seq_ctrl(3, 4, 0);
        insns[2] = seq_ctrl(0, 0, 0);
        bytes = seq_image(image, fmt, insns, 3, konst, 0, 1);
        compare_seq_one(sw, hw, fmt, image, bytes, 1, n, seed,
                        "seq fma+deposit");
    }

    /* 2. constants and per-instruction attributes: the interval
     *    pattern - r5 = r0*K under rtz, r6 = r0*K under rup */
    {
        uint64_t insns[5];
        insns[0] = seq_alu(3, 5, 0, 0, 0, 1, 1, 0);
        insns[1] = seq_alu(3, 6, 0, 0, 0, 3, 1, 0);
        insns[2] = seq_ctrl(3, 5, 0);
        insns[3] = seq_ctrl(3, 6, 0);
        insns[4] = seq_ctrl(0, 0, 0);
        bytes = seq_image(image, fmt, insns, 5, konst, 1, 2);
        compare_seq_one(sw, hw, fmt, image, bytes, 2, n, seed + 1,
                        "seq interval");
    }

    /* 3. the escape shape: square, deposit, drop out on zero */
    {
        uint64_t insns[7];
        insns[0] = seq_alu(3, 4, 0, 0, 0, 0, 0, 0);
        insns[1] = seq_ctrl(1, 0, 6);
        insns[2] = seq_alu(3, 4, 4, 4, 0, 0, 0, 0);
        insns[3] = seq_ctrl(3, 4, 0);
        insns[4] = seq_ctrl(4, 4, 0);
        insns[5] = seq_ctrl(2, 0, 0);
        insns[6] = seq_ctrl(0, 0, 0);
        bytes = seq_image(image, fmt, insns, 7, konst, 0, 8);
        compare_seq_one(sw, hw, fmt, image, bytes, 8, n, seed + 2,
                        "seq escape loop");
    }

    /* 4. max_deposits == 0: legal; every deposit overflows into
     *    STATUS and the counts come back all zero */
    {
        uint64_t insns[3];
        insns[0] = seq_alu(1, 4, 0, 0, 2, 0, 0, 0);
        insns[1] = seq_ctrl(3, 4, 0);
        insns[2] = seq_ctrl(0, 0, 0);
        bytes = seq_image(image, fmt, insns, 3, konst, 0, 0);
        compare_seq_one(sw, hw, fmt, image, bytes, 0, n, seed + 3,
                        "seq zero-budget");
    }

    /* 5. revision 2's upper half of the register file, device against
     *    software - and then against an ORACLE, because sw-vs-sw
     *    cannot see a decoder fault both sides share.
     *
     *    The oracle is that renaming registers is invisible: the same
     *    computation written in r16/r17 and in r4/r5 must deposit the
     *    same bytes. A decoder that dropped the fifth bit would read
     *    the first as r0/r1 - which are the INPUT registers - so the
     *    two programs stop agreeing, which is exactly what the check
     *    is for. Written that way round on purpose: the aliasing has
     *    to reach a value the program still needs, or a dropped bit
     *    produces the right answer by luck (it does, if the high
     *    registers are only ever written before they are read). */
    if (hcaps.seq_features & CFT_SEQ_FEAT_REGS32) {
        uint64_t wide[5], narrow[5];
        uint8_t image2[1024];
        size_t bytes2;

        wide[0]   = seq_alu5(0, 16, 0, 1, 2, 0, 0, 0, 0); /* r16=r0*r1+r2 */
        wide[1]   = seq_alu5(1, 17, 16, 0, 0, 0, 0, 0, 0);/* r17=r16+r0   */
        wide[2]   = seq_ctrl5(3, 17);
        wide[3]   = seq_ctrl5(3, 16);
        wide[4]   = seq_ctrl(0, 0, 0);
        narrow[0] = seq_alu5(0,  4, 0, 1, 2, 0, 0, 0, 0); /* r4 =r0*r1+r2 */
        narrow[1] = seq_alu5(1,  5,  4, 0, 0, 0, 0, 0, 0);/* r5 =r4+r0    */
        narrow[2] = seq_ctrl5(3, 5);
        narrow[3] = seq_ctrl5(3, 4);
        narrow[4] = seq_ctrl(0, 0, 0);

        bytes  = seq_image(image, fmt, wide, 5, konst, 0, 2);
        bytes2 = seq_image(image2, fmt, narrow, 5, konst, 0, 2);
        compare_seq_one(sw, hw, fmt, image, bytes, 2, n, seed + 4,
                        "seq r16/r17");
        compare_seq_images(sw, fmt, image, bytes, image2, bytes2, 2, n,
                           seed + 4, "seq register renaming");

        /* And r31 itself, the highest the five bits reach, with
         * DEPOSIT and SETACT both naming it - imm[25] is the only bit
         * of a control instruction's immediate revision 2 opened. */
        {
            uint64_t hi5[7], lo5[7];
            hi5[0] = seq_alu5(0, 31, 0, 1, 2, 0, 0, 0, 0);
            hi5[1] = seq_ctrl(1, 0, 3);                  /* repeat 3     */
            hi5[2] = seq_alu5(3, 31, 31, 31, 0, 0, 0, 0, 0);
            hi5[3] = seq_ctrl5(3, 31);                   /* deposit r31  */
            hi5[4] = seq_ctrl5(4, 31);                   /* setact  r31  */
            hi5[5] = seq_ctrl(2, 0, 0);                  /* endrep       */
            hi5[6] = seq_ctrl(0, 0, 0);
            memcpy(lo5, hi5, sizeof lo5);
            lo5[0] = seq_alu5(0, 6, 0, 1, 2, 0, 0, 0, 0);
            lo5[2] = seq_alu5(3, 6, 6, 6, 0, 0, 0, 0, 0);
            lo5[3] = seq_ctrl5(3, 6);
            lo5[4] = seq_ctrl5(4, 6);
            bytes  = seq_image(image, fmt, hi5, 7, konst, 0, 4);
            bytes2 = seq_image(image2, fmt, lo5, 7, konst, 0, 4);
            compare_seq_one(sw, hw, fmt, image, bytes, 4, n, seed + 6,
                            "seq r31 escape loop");
            compare_seq_images(sw, fmt, image, bytes, image2, bytes2, 4, n,
                               seed + 6, "seq r31 renaming");
        }
    } else {
        printf("  seq r16..r31: this device does not publish REGS32, "
               "NOT COMPARED (the refusal is scored above)\n");
    }

    /* 6. the per-run constant bank, and the digest over image and
     *    data together. Same gate, same reason. */
    if (hcaps.seq_features & CFT_SEQ_FEAT_BANK_PTR)
        compare_seq_bank(sw, hw, fmt, n, seed + 5);
    else
        printf("  seq BANK_EXT: this device does not publish BANK_PTR, "
               "NOT COMPARED (the refusal is scored above)\n");

    /* 7. the per-lane scratch memory and its per-run block, revision
     *    3's R4 and R5, gated the same way and skipped by name where
     *    the device does not publish them. Run against the device
     *    under test rather than the software handle, because a tile
     *    with the feature has its own memory and its own two
     *    pointers. */
    check_scratch(hw, fmt, n);

    /* 8. the argument refusals, which are the library's own and reach
     *    no device at all - so they are scored once, on the software
     *    handle, at every format. */
    check_program_refusals(sw, fmt);
}

/* ---------------------------------------------------------------
 * Device-resident buffers, held to the host-pointer path   (-b)
 *
 * cft_alloc's promise is that the SAME call gives the SAME bits and
 * the SAME flags whether its operands are host pointers or buffers
 * this library allocated - the second only faster. So every check in
 * this section runs the call twice on the device and once in
 * software, and compares all three: nothing here is allowed to be
 * "close enough because it is the fast path".
 *
 * It runs on the software backend too, where cft_alloc is a plain
 * allocation and the sync calls do nothing. That is not a wasted run:
 * it is what proves the harness can fail (inject a fault into the
 * library and this leg goes red without a card), and it is the only
 * leg that can be run on a laptop before an hour of emulation.
 * --------------------------------------------------------------- */

struct rbuf { cft_buffer *b; uint8_t *p; };

static int rbuf_alloc(cft_device *dev, struct rbuf *r, size_t bytes)
{
    r->b = NULL;
    r->p = NULL;
    if (cft_alloc(dev, bytes, &r->b) != CFT_OK)
        return 0;
    r->p = (uint8_t *)cft_buffer_data(r->b);
    return r->p != NULL;
}

static void rbuf_free(struct rbuf *r)
{
    cft_buffer_free(r->b);
    r->b = NULL;
    r->p = NULL;
}

/* Publish `bytes` from `src` into a buffer's mirror. Two calls, in the
 * order cft.h prescribes, and the reason the write and the publish are
 * one helper is that separating them is exactly the mistake this
 * mechanism punishes. */
static int rbuf_put(struct rbuf *r, const void *src, size_t bytes)
{
    memcpy(r->p, src, bytes);
    return cft_buffer_to_device(r->b) == CFT_OK;
}

/* Totals for the summary line: how many operand bindings across the
 * whole leg were served without a transfer, and how many were not.
 * Zero and zero on a backend with no device memory, which is the
 * right answer there and is what makes the line honest. */
static uint64_t leg_resident_binds, leg_staged_binds;
static char     leg_last_why[112];

static void note_binds(struct rbuf *r)
{
    cft_buffer_info bi;
    memset(&bi, 0, sizeof bi);
    bi.struct_size = sizeof bi;
    if (cft_buffer_get_info(r->b, &bi) != CFT_OK)
        return;
    leg_resident_binds += bi.resident_binds;
    leg_staged_binds   += bi.staged_binds;
    if (bi.staged_why[0])
        memcpy(leg_last_why, bi.staged_why, sizeof leg_last_why);
}

/* One (format, op, attribute) at n elements, three ways. */
static void compare_buffers(cft_device *sw, cft_device *hw, cft_format fmt,
                            cft_op op, cft_round rnd, size_t n,
                            uint32_t seed)
{
    size_t esz = cft_format_size(fmt), i, bad = 0;
    uint32_t fsw = 0, fhost = 0, fbuf = 0, bus = 0;
    cft_status ssw, shost, sbuf;
    struct buf B;
    struct rbuf ra, rb, rc, rd;
    int ok;

    if (!alloc_buffers(&B, n, esz)) {
        printf("  FAIL: out of memory\n");
        failures++;
        return;
    }
    ok = rbuf_alloc(hw, &ra, n * esz) && rbuf_alloc(hw, &rb, n * esz) &&
         rbuf_alloc(hw, &rc, n * esz) && rbuf_alloc(hw, &rd, n * esz);
    if (!ok) {
        printf("  FAIL: cft_alloc of four %lu-byte buffers\n",
               (unsigned long)(n * esz));
        failures++;
        rbuf_free(&ra); rbuf_free(&rb); rbuf_free(&rc); rbuf_free(&rd);
        free_buffers(&B);
        return;
    }

    rs = seed ? seed : 1;
    fill(B.a, n, esz);
    fill(B.b, n, esz);
    fill(B.c, n, esz);
    memset(B.sw, 0, n * esz);
    memset(B.hw, 0, n * esz);

    ok = rbuf_put(&ra, B.a, n * esz) && rbuf_put(&rb, B.b, n * esz) &&
         rbuf_put(&rc, B.c, n * esz);
    CHECK(ok, "publishing three buffers for %s %s",
          cft_format_name(fmt), cft_op_name(op));

    ssw   = cft_run(sw, op, fmt, rnd, B.a, B.b, B.c, B.sw, n, &fsw, NULL);
    shost = cft_run(hw, op, fmt, rnd, B.a, B.b, B.c, B.hw, n, &fhost, &bus);
    sbuf  = cft_run(hw, op, fmt, rnd, ra.p, rb.p, rc.p, rd.p, n, &fbuf, &bus);

    CHECK(ssw == CFT_OK, "software %s %s n=%lu: %s", cft_format_name(fmt),
          cft_op_name(op), (unsigned long)n, cft_strerror(ssw));
    CHECK(shost == CFT_OK, "device host-pointer %s %s n=%lu: %s (%s)",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(shost), cft_last_error());
    CHECK(sbuf == CFT_OK, "device buffer %s %s n=%lu: %s (%s)",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(sbuf), cft_last_error());
    /* The output buffer is device-authoritative now; this is where a
     * caller collects it, and where the counters below become real. */
    CHECK(cft_buffer_from_device(rd.b) == CFT_OK,
          "reading the result buffer back");

    if (ssw == CFT_OK && shost == CFT_OK && sbuf == CFT_OK) {
        for (i = 0; i < n; i++) {
            if (memcmp(B.hw + i * esz, rd.p + i * esz, esz) != 0 ||
                memcmp(B.sw + i * esz, rd.p + i * esz, esz) != 0) {
                if (bad < 3) {
                    char h1[2 * MAXE + 1], h2[2 * MAXE + 1];
                    char h3[2 * MAXE + 1];
                    hex(B.sw + i * esz, esz, h1);
                    hex(B.hw + i * esz, esz, h2);
                    hex(rd.p + i * esz, esz, h3);
                    printf("  FAIL: %s %s %d element %lu of %lu\n"
                           "        software        %s\n"
                           "        device pointers %s\n"
                           "        device buffers  %s\n",
                           cft_format_name(fmt), cft_op_name(op), (int)rnd,
                           (unsigned long)i, (unsigned long)n, h1, h2, h3);
                }
                bad++;
            }
        }
        checks++;
        if (bad) {
            failures++;
            printf("  FAIL: %lu of %lu elements differ between the "
                   "buffer path and the pointer path\n",
                   (unsigned long)bad, (unsigned long)n);
        }
        CHECK(fsw == fhost && fhost == fbuf,
              "%s %s flags: software 0x%02x, pointers 0x%02x, "
              "buffers 0x%02x", cft_format_name(fmt), cft_op_name(op),
              (unsigned)fsw, (unsigned)fhost, (unsigned)fbuf);

        /* Run it AGAIN on the same resident operands, with nothing
         * republished. This is the case the whole feature exists for -
         * the second call is the one that costs no transfer - and it
         * is the case a stale copy would break: the answer must not
         * move, and it must still be the software answer.
         *
         * The read back is deliberately NOT here. What comes next
         * needs rd device-authoritative, and a from_device would take
         * that away. */
        {
            uint32_t f2 = 0;
            memset(rd.p, 0, n * esz);
            CHECK(cft_run(hw, op, fmt, rnd, ra.p, rb.p, rc.p, rd.p, n,
                          &f2, NULL) == CFT_OK,
                  "the second run on resident operands");
            CHECK(f2 == fsw,
                  "%s %s: the second run's flags moved (0x%02x, was 0x%02x)",
                  cft_format_name(fmt), cft_op_name(op), (unsigned)f2,
                  (unsigned)fsw);
        }

        /* THE AUTHORITY RULE, from the wrong side. rd holds the run
         * that just finished and the caller does NOT read it back
         * before feeding it in as an input. cft.h promises that costs
         * a round trip and not an answer, so the abs below must be the
         * abs of the run that just happened - not of the one before
         * it, and not of the zeros the mirror was memset to. Those two
         * wrong answers are why this is worth a check: both are
         * plausible, and only one of them is even noisy. */
        {
            uint32_t f3 = 0, f4 = 0;
            uint8_t *swd = malloc(n * esz);
            if (swd) {
                CHECK(cft_run(sw, CFT_ABS, fmt, CFT_RNE, B.sw, NULL, NULL,
                              swd, n, &f3, NULL) == CFT_OK,
                      "software abs of the previous result");
                CHECK(cft_run(hw, CFT_ABS, fmt, CFT_RNE, rd.p, NULL, NULL,
                              B.hw, n, &f4, NULL) == CFT_OK,
                      "device abs of an unread result buffer");
                CHECK(memcmp(swd, B.hw, n * esz) == 0 && f3 == f4,
                      "%s %s: a buffer used as an input without being read "
                      "back did not give the run that wrote it",
                      cft_format_name(fmt), cft_op_name(op));
                free(swd);
            }
        }

        /* And now the read back, which the line above already forced
         * the library to do. The second run's bytes must be here. */
        CHECK(cft_buffer_from_device(rd.b) == CFT_OK,
              "reading the second run back");
        CHECK(memcmp(B.sw, rd.p, n * esz) == 0,
              "%s %s: back-to-back runs on resident operands drifted",
              cft_format_name(fmt), cft_op_name(op));
    }

    note_binds(&ra); note_binds(&rb); note_binds(&rc); note_binds(&rd);
    rbuf_free(&ra); rbuf_free(&rb); rbuf_free(&rc); rbuf_free(&rd);
    free_buffers(&B);
}

/* A reduction over a resident input. The single output element goes to
 * a host pointer, which is what cft_reduce's signature offers, so what
 * this checks is the input side and the tree above it. */
static void compare_buffers_reduce(cft_device *sw, cft_device *hw,
                                   cft_format fmt, cft_op op, cft_round rnd,
                                   size_t n, uint32_t seed, int finite)
{
    size_t esz = cft_format_size(fmt);
    size_t bytes = (n ? n : 1) * esz;
    uint32_t fsw = 0, fhost = 0, fbuf = 0;
    uint8_t *a = malloc(bytes), *b = malloc(bytes);
    uint8_t dsw[MAXE], dhost[MAXE], dbuf[MAXE];
    struct rbuf ra, rb;
    cft_status ssw, shost, sbuf;

    if (!a || !b) {
        printf("  FAIL: out of memory\n");
        failures++;
        free(a); free(b);
        return;
    }
    if (!rbuf_alloc(hw, &ra, bytes) || !rbuf_alloc(hw, &rb, bytes)) {
        printf("  FAIL: cft_alloc for a reduction\n");
        failures++;
        rbuf_free(&ra); rbuf_free(&rb);
        free(a); free(b);
        return;
    }

    rs = seed ? seed : 1;
    if (finite) {
        fill_finite(a, fmt, n);
        fill_finite(b, fmt, n);
    } else {
        fill(a, n, esz);
        fill(b, n, esz);
    }
    memset(dsw, 0, sizeof dsw);
    memset(dhost, 0, sizeof dhost);
    memset(dbuf, 0, sizeof dbuf);
    CHECK(rbuf_put(&ra, a, bytes) && rbuf_put(&rb, b, bytes),
          "publishing a reduction's operands");

    ssw   = cft_reduce(sw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                       dsw, n, &fsw, NULL);
    shost = cft_reduce(hw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                       dhost, n, &fhost, NULL);
    sbuf  = cft_reduce(hw, op, fmt, rnd, ra.p, op == CFT_DOT ? rb.p : NULL,
                       dbuf, n, &fbuf, NULL);

    CHECK(ssw == CFT_OK && shost == CFT_OK && sbuf == CFT_OK,
          "%s %s n=%lu: software %s, pointers %s, buffers %s (%s)",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          cft_strerror(ssw), cft_strerror(shost), cft_strerror(sbuf),
          cft_last_error());
    if (ssw == CFT_OK && shost == CFT_OK && sbuf == CFT_OK) {
        char h1[2 * MAXE + 1], h2[2 * MAXE + 1], h3[2 * MAXE + 1];
        checks++;
        if (memcmp(dsw, dbuf, esz) != 0 || memcmp(dhost, dbuf, esz) != 0) {
            hex(dsw, esz, h1);
            hex(dhost, esz, h2);
            hex(dbuf, esz, h3);
            printf("  FAIL: %s %s n=%lu rnd=%d\n"
                   "        software        %s\n"
                   "        device pointers %s\n"
                   "        device buffers  %s\n",
                   cft_format_name(fmt), cft_op_name(op),
                   (unsigned long)n, (int)rnd, h1, h2, h3);
            failures++;
        }
        CHECK(fsw == fhost && fhost == fbuf,
              "%s %s n=%lu flags: software 0x%02x, pointers 0x%02x, "
              "buffers 0x%02x", cft_format_name(fmt), cft_op_name(op),
              (unsigned long)n, (unsigned)fsw, (unsigned)fhost,
              (unsigned)fbuf);
    }

    note_binds(&ra); note_binds(&rb);
    rbuf_free(&ra); rbuf_free(&rb);
    free(a);
    free(b);
}

/* The one thing the library cannot see, checked from both sides.
 *
 * Writing the mirror and NOT publishing it is the single case cft.h
 * documents as changing an answer, because a plain store leaves no
 * trace. Publishing it must then take effect. So: publish, run,
 * rewrite the mirror, publish again, run again - and the second answer
 * must be the one the new bytes give. A backend that cached a device
 * copy and ignored cft_buffer_to_device passes every other check in
 * this file and fails this one. */
static void check_publish_takes_effect(cft_device *sw, cft_device *hw,
                                       cft_format fmt, size_t n,
                                       uint32_t seed)
{
    size_t esz = cft_format_size(fmt), bytes = n * esz;
    uint8_t *a1 = malloc(bytes), *a2 = malloc(bytes);
    uint8_t *want = malloc(bytes), *got = malloc(bytes);
    struct rbuf ra, rd;
    uint32_t f1 = 0, f2 = 0;

    if (!a1 || !a2 || !want || !got) {
        free(a1); free(a2); free(want); free(got);
        return;
    }
    if (!rbuf_alloc(hw, &ra, bytes) || !rbuf_alloc(hw, &rd, bytes)) {
        printf("  FAIL: cft_alloc for the publish check\n");
        failures++;
        rbuf_free(&ra); rbuf_free(&rd);
        free(a1); free(a2); free(want); free(got);
        return;
    }

    rs = seed ? seed : 1;
    fill_finite(a1, fmt, n);
    fill_finite(a2, fmt, n);

    CHECK(rbuf_put(&ra, a1, bytes), "publishing the first operand");
    CHECK(cft_run(hw, CFT_ABS, fmt, CFT_RNE, ra.p, NULL, NULL, rd.p, n,
                  &f1, NULL) == CFT_OK, "the first run");
    CHECK(cft_buffer_from_device(rd.b) == CFT_OK, "reading the first");

    /* New bytes into the same mirror, published. */
    CHECK(rbuf_put(&ra, a2, bytes), "republishing with new bytes");
    CHECK(cft_run(hw, CFT_ABS, fmt, CFT_RNE, ra.p, NULL, NULL, rd.p, n,
                  &f2, NULL) == CFT_OK, "the second run");
    CHECK(cft_buffer_from_device(rd.b) == CFT_OK, "reading the second");
    memcpy(got, rd.p, bytes);

    CHECK(cft_run(sw, CFT_ABS, fmt, CFT_RNE, a2, NULL, NULL, want, n,
                  NULL, NULL) == CFT_OK, "the software answer");
    CHECK(memcmp(want, got, bytes) == 0,
          "%s: cft_buffer_to_device did not take effect - the run used "
          "the bytes the buffer held before", cft_format_name(fmt));
    (void)f1; (void)f2;

    note_binds(&ra); note_binds(&rd);
    rbuf_free(&ra); rbuf_free(&rd);
    free(a1); free(a2); free(want); free(got);
}

int main(int argc, char **argv)
{
    static const cft_op ops[] = {CFT_FMA, CFT_ADD, CFT_SUB, CFT_MUL,
                                 CFT_MIN, CFT_MAXNUM, CFT_CMPLT,
                                 CFT_SELECT, CFT_IXOR, CFT_ISHR,
                                 CFT_RECIP_SEED, CFT_RSQRT_SEED};
    static const cft_round rnds[] = {CFT_RNE, CFT_RTZ, CFT_RDN, CFT_RUP,
                                     CFT_RMM};
    cft_device *sw = NULL, *hw = NULL;
    cft_caps caps;
    cft_status st;
    const char *artifact = NULL;
    size_t n = 256;
    int only_fmt = -1;      /* -1 = every format the device carries */
    int quick = 0;          /* one opcode, one attribute */
    int only_reduce = 0;    /* skip elementwise; reductions are slow enough */
    int only_seq = 0;       /* sequencer programs only */
    int only_buf = 0;       /* device-resident buffers only */
    int f, o, r, argi;

    /* Emulation is orders of magnitude slower than silicon, so the
     * full matrix is a card-day run and -q is what fits in an evening.
     * The scope is a flag rather than a smaller hard-coded list
     * because the two runs should be the same program. */
    for (argi = 1; argi < argc; argi++) {
        if (!strcmp(argv[argi], "-q")) {
            quick = 1;
        } else if (!strcmp(argv[argi], "-s")) {
            only_seq = 1;
        } else if (!strcmp(argv[argi], "-r")) {
            only_reduce = 1;
        } else if (!strcmp(argv[argi], "-b")) {
            only_buf = 1;
        } else if (!strcmp(argv[argi], "-n") && argi + 1 < argc) {
            n = (size_t)strtoul(argv[++argi], NULL, 10);
        } else if (!strcmp(argv[argi], "-f") && argi + 1 < argc) {
            const char *want = argv[++argi];
            int i;
            for (i = 0; i < 4; i++)
                if (!strcmp(want, cft_format_name((cft_format)i)))
                    only_fmt = i;
            if (only_fmt < 0) {
                fprintf(stderr, "unknown format %s\n", want);
                return 2;
            }
        } else if (argv[argi][0] != '-' && !artifact) {
            artifact = argv[argi];
        } else {
            fprintf(stderr,
                    "usage: %s <artifact.xclbin> [-n elements] "
                    "[-f fp32|fp64|fp128|fp256] [-q] [-r] [-s] [-b]\n"
                    "  -q  one opcode and one attribute a format\n"
                    "  -r  reductions only\n"
                    "  -s  sequencer programs only\n"
                    "  -b  device-resident buffers only: the same "
                    "elementwise matrix and\n"
                    "      the same reductions run through cft_alloc, "
                    "compared byte for\n"
                    "      byte and flag for flag with the host-pointer "
                    "path and with\n"
                    "      the software backend\n",
                    argv[0]);
            return 2;
        }
    }
    if (!artifact) {
        fprintf(stderr, "usage: %s <artifact.xclbin> [-n elements] "
                        "[-f fp32|fp64|fp128|fp256] [-q] [-r] [-s] [-b]\n",
                argv[0]);
        return 2;
    }
    argv[1] = (char *)artifact;

    st = cft_open(NULL, 0, &sw);
    if (st != CFT_OK) {
        fprintf(stderr, "software backend: %s\n", cft_strerror(st));
        return 2;
    }
    /* "sw" opens the software backend as the device under test. Both
     * sides are then the same code, so every comparison passes by
     * construction - which is the point: it exercises this program on
     * a machine with no XRT and no artifact, so a bug in the harness
     * is found before an hour of emulation is spent finding it. Inject
     * a fault into the library and this mode is what shows the checks
     * can fail at all. */
    st = cft_open(strcmp(argv[1], "sw") ? argv[1] : NULL, 0, &hw);
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

    check_layout(sw);

    /* Both handles, because the claim is about a BACKEND and not about
     * the device under test: run against `sw` this program is the
     * software backend twice and still proves the software one. */
    printf("the caps a backend reports are the caps it enforces\n");
    check_caps_enforced(sw, "software");
    check_caps_enforced(hw, "device");
    fflush(stdout);

    for (f = 0; f < 4; f++) {
        cft_format fmt = (cft_format)f;
        int nops = (only_reduce || only_seq || only_buf) ? 0
                 : quick      ? 1
                 : (int)(sizeof ops / sizeof ops[0]);
        int nrnd = quick ? 1 : (int)(sizeof rnds / sizeof rnds[0]);

        if (only_fmt >= 0 && f != only_fmt)
            continue;
        if (!cft_supports(hw, CFT_FMA, fmt)) {
            printf("%-6s not on this device, skipped\n",
                   cft_format_name(fmt));
            continue;
        }
        printf("%s\n", cft_format_name(fmt));
        fflush(stdout);

        /* -b: cft_alloc's buffers held to the host-pointer path.
         *
         * The elementwise matrix and the reductions, run through
         * device-resident operands and compared byte for byte and flag
         * for flag against the same calls on plain pointers and
         * against the software backend. Its own leg because it costs a
         * second and a third run of everything, and because on a card
         * it is what proves the fast path is the same path. */
        if (only_buf) {
            int bo, br;
            int bops = quick ? 2 : (int)(sizeof ops / sizeof ops[0]);
            for (bo = 0; bo < bops; bo++) {
                if (!cft_supports(hw, ops[bo], fmt)) {
                    note_skip(cft_op_name(ops[bo]));
                    continue;
                }
                for (br = 0; br < nrnd; br++)
                    compare_buffers(sw, hw, fmt, ops[bo], rnds[br], n,
                                    0xbf00000u +
                                    (uint32_t)(f * 100 + bo * 10 + br));
            }
            printf("  buffers, elementwise: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);

            /* The sizes that straddle a beat and a tile boundary, which
             * are where a window that is a whole number of beats stops
             * being one - and where a copy sized from the wrong end of
             * the arithmetic would read the caller's next elements as
             * padding. */
            {
                static const size_t odd[] = {1, 2, 3, 7, 8, 9, 31, 33, 37};
                size_t i2, nodd = quick ? 5 : sizeof odd / sizeof odd[0];
                for (i2 = 0; i2 < nodd; i2++)
                    compare_buffers(sw, hw, fmt, CFT_FMA, CFT_RNE, odd[i2],
                                    0xbf50000u + (uint32_t)(f * 50 + i2));
                printf("  buffers, boundary sizes: %d checks, %d failed\n",
                       checks, failures);
                fflush(stdout);
            }

            check_publish_takes_effect(sw, hw, fmt, n, 0xbfaa000u +
                                       (uint32_t)f);
            printf("  buffers, publish takes effect: %d checks, %d "
                   "failed\n", checks, failures);
            fflush(stdout);

            if (cft_supports(hw, CFT_SUM, fmt)) {
                static const size_t rn[] = {0, 1, 2, 3, 5, 8, 9, 17, 33, 37};
                size_t i2, nrn = quick ? 5 : sizeof rn / sizeof rn[0];
                for (i2 = 0; i2 < nrn; i2++)
                    compare_buffers_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE,
                                           rn[i2], 0xbf60000u +
                                           (uint32_t)(f * 50 + i2), 1);
                compare_buffers_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE,
                                       quick ? 9 : 37,
                                       0xbf70000u + (uint32_t)f, 0);
                if (cft_supports(hw, CFT_DOT, fmt))
                    for (i2 = 0; i2 < (quick ? 3u : 6u) && i2 < nrn; i2++)
                        compare_buffers_reduce(sw, hw, fmt, CFT_DOT,
                                               CFT_RNE, rn[i2], 0xbf80000u +
                                               (uint32_t)(f * 50 + i2), 1);
                if (cft_supports(hw, CFT_SUMSQ, fmt))
                    for (i2 = 0; i2 < (quick ? 3u : 5u) && i2 < nrn; i2++)
                        compare_buffers_reduce(sw, hw, fmt, CFT_SUMSQ,
                                               CFT_RNE, rn[i2], 0xbf90000u +
                                               (uint32_t)(f * 50 + i2), 1);
                if (cft_supports(hw, CFT_SUMABS, fmt))
                    for (i2 = 0; i2 < (quick ? 3u : 5u) && i2 < nrn; i2++)
                        compare_buffers_reduce(sw, hw, fmt, CFT_SUMABS,
                                               CFT_RNE, rn[i2], 0xbfb0000u +
                                               (uint32_t)(f * 50 + i2), 1);
                printf("  buffers, reductions: %d checks, %d failed\n",
                       checks, failures);
                fflush(stdout);
            } else {
                note_skip(cft_op_name(CFT_SUM));
            }
            continue;
        }
        for (o = 0; o < nops; o++) {
            if (!cft_supports(hw, ops[o], fmt)) {
                note_skip(cft_op_name(ops[o]));
                continue;
            }
            for (r = 0; r < nrnd; r++) {
                compare(sw, hw, fmt, ops[o], rnds[r], n,
                        0x51ce0000u + (uint32_t)(f * 100 + o * 10 + r));
                printf("  %s %s: %d checks so far, %d failed\n",
                       cft_op_name(ops[o]), "ok", checks, failures);
                fflush(stdout);
            }
        }

        /* The composed divide and square root. Every floating step
         * runs on whichever backend is under test, so this is where
         * the tile's seeds and FMA are proven to compose to the
         * contract - the closest thing to "general purpose" a matrix
         * can assert. Gated on the seed group: a bitstream that
         * predates CAPS bit 6 cannot run the sequence and says so. */
        /* Sequencer programs, device vs software. An image whose
         * contract predates 0x600 answers CFT_ERR_UNSUPPORTED from
         * the device-side load, which reports as a load
         * disagreement - run -s only against 0x600+ images. */
        if (only_seq || !only_reduce) {
            size_t nseq = n > 200 ? 200 : n;
            compare_seq(sw, hw, fmt, nseq,
                        0x5e9c0000u + (uint32_t)f * 16u);
            printf("  sequencer programs: %d checks so far, %d failed\n",
                   checks, failures);
            fflush(stdout);
        }
        if (only_seq)
            continue;

        if (!only_reduce) {
            if (!cft_supports(hw, CFT_RECIP_SEED, fmt)) {
                note_skip("div/sqrt");
            } else {
                for (r = 0; r < nrnd; r++) {
                    compare_divsqrt(sw, hw, fmt, rnds[r], n,
                                    0xd15c0000u + (uint32_t)(f * 10 + r));
                    printf("  div/sqrt %s: %d checks so far, %d failed\n",
                           "ok", checks, failures);
                    fflush(stdout);
                }
            }
        }

        /* Sizes chosen to straddle the awkward boundaries: one
         * element, one beat, one more than a beat, an odd count that
         * cannot divide evenly across four tiles, and a prime. */
        if (!only_reduce) {
            static const size_t odd[] = {1, 2, 3, 7, 8, 9, 31, 32, 33, 37};
            static const size_t cuts[] = {1, 2, 5, 8, 16, 64, 1024};
            size_t i, nodd = quick ? 6 : sizeof odd / sizeof odd[0];
            for (i = 0; i < nodd; i++)
                compare(sw, hw, fmt, CFT_FMA, CFT_RNE, odd[i],
                        0x0dd00000u + (uint32_t)(f * 50 + i));
            printf("  boundary sizes done: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);
            compare_partitioned(hw, fmt, CFT_FMA, CFT_RNE, n, cuts,
                                sizeof cuts / sizeof cuts[0],
                                0x5717000u + (uint32_t)f);
            printf("  partition invariance done: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);
        }

        /* Reductions.
         *
         * The n list is the interesting part. A reduction is handed
         * the true element count rather than a padded one, so every
         * value here that is not a whole number of beats is a case the
         * elementwise path never generates: 1, 3, 5, 7 and 9 are all
         * partial beats in at least one format, and n=1 is the exact
         * case the truncating shift returned nothing for.
         *
         * Powers of two are in the list for the opposite reason. The
         * tree splits at the largest power of two below the range, and
         * that agrees with the floor midpoint only when n is a power
         * of two - so 2, 4, 8, 16 are the sizes where a wrong split
         * would still produce the right answer, and 3, 5, 7, 9 are the
         * sizes where it could not.
         *
         * 0 is there because the contract says so: +0.0, nothing
         * raised, and both backends have to agree about it. */
        if (cft_supports(hw, CFT_SUM, fmt)) {
            static const size_t rn[] = {0, 1, 2, 3, 4, 5, 7, 8, 9,
                                        15, 16, 17, 31, 33, 37, 64};
            size_t i, nrn = quick ? 9 : sizeof rn / sizeof rn[0];

            printf("  reductions\n");
            fflush(stdout);
            for (i = 0; i < nrn; i++)
                compare_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE, rn[i],
                               0x5000000u + (uint32_t)(f * 50 + i), 1);
            printf("    sum, finite operands: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);

            /* Once with the whole encoding space, so quiet-NaN payload
             * and infinity propagation through the tree are checked
             * too - see fill_finite for why this is not the default. */
            compare_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE, quick ? 9 : 37,
                           0x5aa0000u + (uint32_t)f, 0);
            printf("    sum, any bit pattern: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);

            if (!quick) {
                for (r = 0; r < (int)(sizeof rnds / sizeof rnds[0]); r++)
                    compare_reduce(sw, hw, fmt, CFT_SUM, rnds[r], 37,
                                   0x5bb0000u + (uint32_t)(f * 10 + r), 1);
                printf("    sum, all five attributes: %d checks, %d "
                       "failed\n", checks, failures);
                fflush(stdout);
                check_sum_ignores_b(hw, fmt, 37, 0x5cc0000u + (uint32_t)f);
            }

            /* CFT_DOT is not separate hardware - the library issues a
             * MUL and then a SUM, because the contract makes
             * dot(a,b) == sum(mul(a,b)) exact. That composition is
             * precisely what this checks: two device round trips
             * against one software call. */
            if (cft_supports(hw, CFT_DOT, fmt)) {
                for (i = 0; i < (quick ? 4u : 8u) && i < nrn; i++)
                    compare_reduce(sw, hw, fmt, CFT_DOT, CFT_RNE, rn[i],
                                   0xd0700000u + (uint32_t)(f * 50 + i), 1);
                printf("    dot: %d checks, %d failed\n", checks, failures);
                fflush(stdout);
            }

            /* sumSquare and sumAbs are compositions for the same
             * reason dot is - the dot itself, and an abs pass followed
             * by a sum - so what this checks is again the composition
             * across the backend boundary. Run with any-bits operands
             * as well as finite ones, because 9.4's infinity-ahead-of-
             * NaN override lives in the host layer above both
             * backends, and a device path that reached the tree by a
             * different route would show up here. */
            if (cft_supports(hw, CFT_SUMSQ, fmt)) {
                for (i = 0; i < (quick ? 3u : 6u) && i < nrn; i++) {
                    compare_reduce(sw, hw, fmt, CFT_SUMSQ, CFT_RNE, rn[i],
                                   0x59000000u + (uint32_t)(f * 50 + i), 1);
                    compare_reduce(sw, hw, fmt, CFT_SUMSQ, CFT_RNE, rn[i],
                                   0x59a00000u + (uint32_t)(f * 50 + i), 0);
                }
                printf("    sumsq: %d checks, %d failed\n",
                       checks, failures);
                fflush(stdout);
            }
            if (cft_supports(hw, CFT_SUMABS, fmt)) {
                for (i = 0; i < (quick ? 3u : 6u) && i < nrn; i++) {
                    compare_reduce(sw, hw, fmt, CFT_SUMABS, CFT_RNE, rn[i],
                                   0x5ab00000u + (uint32_t)(f * 50 + i), 1);
                    compare_reduce(sw, hw, fmt, CFT_SUMABS, CFT_RNE, rn[i],
                                   0x5ab50000u + (uint32_t)(f * 50 + i), 0);
                }
                printf("    sumabs: %d checks, %d failed\n",
                       checks, failures);
                fflush(stdout);
            }
        } else {
            note_skip(cft_op_name(CFT_SUM));
            printf("  no reduction opcode group on this device "
                   "(CAPS says so) - nothing to check\n");
        }
    }

    /* What the buffer leg actually got, before the handles go.
     *
     * A residency mechanism that quietly staged everything would pass
     * every comparison above - the answers would be right, and the
     * whole point would be missing. So the counters are printed, and
     * on a device that says it keeps device copies at least one
     * binding has to have been served without a transfer or this leg
     * has proven only that the fallback works. */
    if (only_buf) {
        printf("\nbindings: %lu served from a device copy with no "
               "transfer, %lu copied\n",
               (unsigned long)leg_resident_binds,
               (unsigned long)leg_staged_binds);
        if (leg_last_why[0])
            printf("  the last copy was made because: %s\n", leg_last_why);
        if (caps.buffers_resident) {
            CHECK(leg_resident_binds > 0,
                  "this device reports resident buffers and not one "
                  "binding avoided a transfer - the answers are right "
                  "and the mechanism did nothing");
        } else {
            printf("  this backend keeps no device copies, so both "
                   "counters are zero by construction and the leg has "
                   "proven the CONTRACT, not the saving\n");
        }
    }

    cft_close(hw);
    cft_close(sw);
    printf("\n%d checks, %d failed\n", checks, failures);

    if (skipped) {
        int i, n_named = skipped < MAX_SKIP ? skipped : MAX_SKIP;
        printf("SKIPPED %d opcode%s this device says it does not "
               "implement:", skipped, skipped == 1 ? "" : "s");
        for (i = 0; i < n_named; i++)
            printf(" %s", skip_name[i]);
        printf("\n  A skip is not a failure, but it is not a pass "
               "either. If the device\n"
               "  should implement one of these, CAPS is wrong and "
               "nothing above tested it.\n");
    }

    if (!failures)
        printf(skipped
               ? "the device and the software backend agree on every case "
                 "that RAN, bits and flags\n"
               : "the device and the software backend agree on every "
                 "case, bits and flags\n");
    return failures ? 1 : 0;
}
