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
static size_t seq_image_flags(uint8_t *out, cft_format fmt,
                              const uint64_t *insns, unsigned n_insns,
                              const uint8_t *consts, unsigned n_consts,
                              uint32_t max_deposits, uint32_t flags)
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
    put_le32(out + 28, 0);
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
       PROBE_REG };      /* a register named by const_idx, five bits wide */

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
        const uint32_t hi = (wide || c.max_consts <= 16u)
                          ? c.max_consts : 16u;
        const int form = (hi > 16u) ? PROBE_KX : PROBE_K4;
        st = try_load(dev, fmt, 2, hi, 1, hi - 1u, form);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL %s: max_consts %lu is reported and an "
                   "instruction addressing k[%lu] in the %s form was "
                   "refused: %s (%s)\n",
                   who, (unsigned long)c.max_consts, (unsigned long)(hi - 1u),
                   form == PROBE_KX ? "kx" : "four-bit",
                   cft_strerror(st), cft_last_error());
            failures++;
        } else {
            printf("    k[%lu] (%s form) loads, at the cap\n",
                   (unsigned long)(hi - 1u),
                   form == PROBE_KX ? "kx" : "four-bit");
        }
        if (c.max_consts < 256u && (wide || c.max_consts < 16u)) {
            /* n_consts one past the cap, so the index is inside the
             * program's own bank and what refuses it is the DEVICE's
             * reach rather than the header's count. */
            const int f2 = (c.max_consts >= 16u) ? PROBE_KX : PROBE_K4;
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
                   c.max_consts >= 256u ? "immediate's byte"
                                        : "four-bit field");
        }
    }

    /* seq_features is CAPS[7:4] in its low nibble and CAPS[31:28] - the
     * ALU extensions, IMUL first - in the next one (cft.h, 2026-09-07).
     * Anything above those eight bits is a decode fault, not a
     * feature. */
    checks++;
    if (c.seq_features & ~0xFFu) {
        printf("  FAIL %s: seq_features 0x%lx has bits outside CAPS[7:4] "
               "and CAPS[31:28]\n", who, (unsigned long)c.seq_features);
        failures++;
    }
    printf("    features:%s%s%s%s\n",
           (c.seq_features & CFT_SEQ_FEAT_WIDE_CONST) ? " kx" : "",
           (c.seq_features & CFT_SEQ_FEAT_REGS32)     ? " REGS32" : "",
           (c.seq_features & CFT_SEQ_FEAT_BANK_PTR)   ? " BANK_PTR" : "",
           (c.seq_features & CFT_ALU_EXT_IMUL)        ? " IMUL" : "");

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
    bytes = seq_image_flags(img, fmt, insns, 3, konst, 2, 1, 2u);
    refusal(dev, fmt, "flags bit 1 (unassigned)", img, bytes,
            CFT_ERR_ARTIFACT, NULL);
    bytes = seq_image_flags(img, fmt, insns, 3, konst, 2, 1, 0x80000000u);
    refusal(dev, fmt, "flags bit 31", img, bytes, CFT_ERR_ARTIFACT, NULL);
    bytes = seq_image(img, fmt, insns, 3, konst, 2, 1);
    put_le32(img + 28, 1);                        /* reserved[1] */
    refusal(dev, fmt, "reserved[1] non-zero", img, bytes,
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

    /* 7. the argument refusals, which are the library's own and reach
     *    no device at all - so they are scored once, on the software
     *    handle, at every format. */
    check_program_refusals(sw, fmt);
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
            fprintf(stderr, "usage: %s <artifact.xclbin> [-n elements] "
                            "[-f fp32|fp64|fp128|fp256] [-q] [-r] [-s]\n",
                    argv[0]);
            return 2;
        }
    }
    if (!artifact) {
        fprintf(stderr, "usage: %s <artifact.xclbin> [-n elements] "
                        "[-f fp32|fp64|fp128|fp256] [-q]\n", argv[0]);
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
        int nops = (only_reduce || only_seq) ? 0
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
