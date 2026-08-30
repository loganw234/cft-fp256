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

/* One reduction, both backends. The output is ONE element however
 * large n is, which is the whole reason cft_reduce is a separate entry
 * point, and the reason this cannot reuse compare() above.
 *
 * `finite` picks the operand distribution - see fill_finite. b is
 * passed as NULL for CFT_SUM, because the header says it may be and a
 * device path that dereferences it anyway should fail here rather than
 * on the card. */
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

    ssw = cft_reduce(sw, op, fmt, rnd, a, op == CFT_SUM ? NULL : b,
                     dsw, n, &fsw, NULL);
    shw = cft_reduce(hw, op, fmt, rnd, a, op == CFT_SUM ? NULL : b,
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
    const char *artifact = NULL;
    size_t n = 256;
    int only_fmt = -1;      /* -1 = every format the device carries */
    int quick = 0;          /* one opcode, one attribute */
    int only_reduce = 0;    /* skip elementwise; reductions are slow enough */
    int f, o, r, argi;

    /* Emulation is orders of magnitude slower than silicon, so the
     * full matrix is a card-day run and -q is what fits in an evening.
     * The scope is a flag rather than a smaller hard-coded list
     * because the two runs should be the same program. */
    for (argi = 1; argi < argc; argi++) {
        if (!strcmp(argv[argi], "-q")) {
            quick = 1;
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
                            "[-f fp32|fp64|fp128|fp256] [-q] [-r]\n",
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

    for (f = 0; f < 4; f++) {
        cft_format fmt = (cft_format)f;
        int nops = only_reduce ? 0
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
