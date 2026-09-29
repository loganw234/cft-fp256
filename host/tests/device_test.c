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

/* setenv, for the one leg that re-runs the reductions under
 * CFT_XRT_REDUCE_BC; ISO C has getenv and nothing to set one with. */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <time.h>
#endif

#include "cft.h"

#define MAXE 32

static int failures;
static int checks;

/* What the device under test does not publish.
 *
 * The matrix adapts to the device by design: a format it does not
 * carry, an opcode CAPS says it lacks, a feature bit it does not
 * publish, a limit it has none of - each leaves a check with nothing
 * to test on THAT device, and each is named where it happens, in one
 * form, by not_here() below:
 *
 *     <what>: NOT COMPARED - <why>   a comparison with the software
 *                                    backend the device cannot take
 *     <what>: NOT TESTED - <why>     a limit or refusal of the device's
 *                                    own, with nothing to hold it to
 *     <what>: NOT RUN - <why>        a leg the device's backend or mode
 *                                    has nothing for
 *
 * None of them is a skip, and none starts with SKIP. verify/run.sh
 * counts a SKIP-first line as a check that exists for this HOST and
 * did not run for a host reason - a missing tool, build product or
 * input file - and these are about the DEVICE (verify/README.md,
 * "Skips are named, never silent", has the rule). device-test has no
 * check of the first kind: every input it reads is the artifact on its
 * command line, which it fails without. The conformance replay, which
 * claims the whole published set, still counts a published case the
 * device cannot run as a skip - so an image whose CAPS drops a group
 * is counted wherever that replay is run against it.
 *
 * Not tested is not a failure, and it is not a pass either: op_caps
 * was once written so that it advertised reductions and silently
 * dropped the integer group, and every integer opcode then went
 * unrun. The suite stayed green. So every line is counted here, by
 * kind and by word, the opcode names are kept, and the final summary
 * refuses to say "the device and the software backend agree on every
 * case" when any of them printed.
 *
 * On 2026-09-24 the format, buffers-leg and opcode lines were printed
 * SKIPPED first for part of the day, and so counted by the runner as
 * skips, while seven NOT COMPARED lines for the same kind of absence
 * went uncounted - one device, one capability, opposite accounting.
 * They are all this form now, and so are the lower-case "not run" and
 * "nothing tested" lines that predate it. */
#define MAX_OPS_ABSENT 32
static int  ops_absent;                 /* opcodes NOT COMPARED */
static const char *op_absent_name[MAX_OPS_ABSENT];
static int  nh_fmts;                    /* formats NOT COMPARED */
static int  nh_buf_legs;                /* -b legs NOT COMPARED */
static int  nh_compared;                /* any other NOT COMPARED line */
static int  nh_tested;                  /* NOT TESTED lines */
static int  nh_run;                     /* NOT RUN lines */

enum { NH_FORMAT, NH_BUFFERS, NH_OPCODES, NH_OTHER };

/* "<what>: NOT <word> - <why>", and counted. word is "COMPARED",
 * "TESTED" or "RUN"; what carries its own indent. The opcode line is
 * counted by the names it carries (ops_absent), not as a line. */
#if defined(__GNUC__)
__attribute__((format(printf, 4, 5)))
#endif
static void not_here(int kind, const char *word, const char *what,
                     const char *why, ...)
{
    va_list ap;
    printf("%s: NOT %s - ", what, word);
    va_start(ap, why);
    vprintf(why, ap);
    va_end(ap);
    printf("\n");
    if (!strcmp(word, "TESTED"))
        nh_tested++;
    else if (!strcmp(word, "RUN"))
        nh_run++;
    else if (kind == NH_FORMAT)
        nh_fmts++;
    else if (kind == NH_BUFFERS)
        nh_buf_legs++;
    else if (kind != NH_OPCODES)
        nh_compared++;
}

/* One environment variable, set or removed, on either platform. */
static void put_env(const char *name, const char *value)
{
#ifdef _WIN32
    char buf[160];
    snprintf(buf, sizeof buf, "%s=%s", name, value ? value : "");
    _putenv(buf);                       /* "NAME=" removes it */
#else
    if (value)
        setenv(name, value, 1);
    else
        unsetenv(name);
#endif
}

/* An opcode the device says it does not implement: named once, on the
 * summary's NOT COMPARED line, not once per format. */
static void note_op_absent(const char *what)
{
    int i;
    for (i = 0; i < ops_absent && i < MAX_OPS_ABSENT; i++)
        if (!strcmp(op_absent_name[i], what))
            return;               /* one line per thing, not per format */
    if (ops_absent < MAX_OPS_ABSENT)
        op_absent_name[ops_absent] = what;
    ops_absent++;
}

#ifndef _WIN32
/* Monotonic milliseconds, for the one leg that asserts a wait happened -
 * the completion witness's, which runs only on the XRT backend, and that
 * is Linux-only. */
static double wall_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts))
        return 0.0;
    return (double)ts.tv_sec * 1e3 + (double)ts.tv_nsec / 1e6;
}
#endif

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

/* cft_reduce_seg (ABI 0.13): n / seg results, d[s] the same tree over
 * slice s that cft_reduce gives, the device against the software
 * backend - which is the definition, slice by slice. Two things the
 * whole-array compare above does not hold:
 *
 *  - every result is written, and none is written by the wrong
 *    segment: the two result buffers start as different fills, so a
 *    slot the device left alone shows as the fill and not as a
 *    plausible +0;
 *  - a device WITHOUT CFT_FEAT_REDUCE_SEG refuses by name. Its tile
 *    has no SEG register and would return one result where n / seg are
 *    due, and the library must not loop the segments over the bus for
 *    the caller (cft.h). So on such a device the named refusal is the
 *    pass, and a computed answer is checked only where the backend
 *    computes it itself (software, or a remote server fronting one). */
static int seg_refusal_noted;

static void compare_reduce_seg(cft_device *sw, cft_device *hw, cft_format fmt,
                               cft_op op, cft_round rnd, size_t n, size_t seg,
                               uint32_t seed, int finite, int has_seg_bit)
{
    size_t esz = cft_format_size(fmt);
    size_t nres = seg ? n / seg : 0;
    size_t bytes = (n ? n : 1) * esz;
    size_t rbytes = (nres ? nres : 1) * esz;
    uint32_t fsw = 0, fhw = 0, bus = 0;
    uint8_t *a = malloc(bytes), *b = malloc(bytes);
    uint8_t *dsw = malloc(rbytes), *dhw = malloc(rbytes);
    cft_status ssw, shw;
    const char *kind = finite ? "finite" : "any-bits";

    if (!a || !b || !dsw || !dhw) {
        printf("  FAIL: out of memory\n");
        failures++;
        free(a); free(b); free(dsw); free(dhw);
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
    memset(dsw, 0xA5, rbytes);
    memset(dhw, 0x5A, rbytes);

    ssw = cft_reduce_seg(sw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                         dsw, n, seg, &fsw, NULL);
    shw = cft_reduce_seg(hw, op, fmt, rnd, a, op == CFT_DOT ? b : NULL,
                         dhw, n, seg, &fhw, &bus);

    CHECK(ssw == CFT_OK, "software %s %s n=%lu seg=%lu: %s",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          (unsigned long)seg, cft_strerror(ssw));
    if (shw == CFT_ERR_UNSUPPORTED && !has_seg_bit &&
        strstr(cft_last_error(), "CFT_FEAT_REDUCE_SEG")) {
        checks++;
        if (!seg_refusal_noted) {
            printf("    cft_reduce_seg refused by name on this device, as "
                   "the contract requires without CAPS2[8]:\n      %s\n",
                   cft_last_error());
            seg_refusal_noted = 1;
        }
        free(a); free(b); free(dsw); free(dhw);
        return;
    }
    CHECK(shw == CFT_OK, "device %s %s n=%lu seg=%lu: %s (bus 0x%x) %s",
          cft_format_name(fmt), cft_op_name(op), (unsigned long)n,
          (unsigned long)seg, cft_strerror(shw), (unsigned)bus,
          cft_last_error());

    if (ssw == CFT_OK && shw == CFT_OK) {
        size_t r;
        checks++;
        for (r = 0; r < nres; r++) {
            if (memcmp(dsw + r * esz, dhw + r * esz, esz) != 0) {
                char h1[2 * MAXE + 1], h2[2 * MAXE + 1];
                hex(dsw + r * esz, esz, h1);
                hex(dhw + r * esz, esz, h2);
                printf("  FAIL: %s %s %s n=%lu seg=%lu rnd=%d, result %lu "
                       "of %lu\n        software %s\n        device   %s\n",
                       cft_format_name(fmt), cft_op_name(op), kind,
                       (unsigned long)n, (unsigned long)seg, (int)rnd,
                       (unsigned long)r, (unsigned long)nres, h1, h2);
                failures++;
                break;
            }
        }
        CHECK(fsw == fhw, "%s %s %s n=%lu seg=%lu flags: software 0x%02x, "
              "device 0x%02x", cft_format_name(fmt), cft_op_name(op),
              kind, (unsigned long)n, (unsigned long)seg, (unsigned)fsw,
              (unsigned)fhw);
    }
    free(a); free(b); free(dsw); free(dhw);
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
    /* An image without constants passes NULL, and memcpy from NULL is
     * undefined whatever the length (verifier-V7 under UBSan). */
    if (!(flags & CFT_PROG_FLAG_BANK_EXT) && n_consts) {
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
        not_here(NH_OTHER, "TESTED", "  capacity checks",
                 "no fp32 on the %s handle, and every probe is an fp32 "
                 "program", who);
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
        not_here(NH_OTHER, "TESTED", "    max_insns",
                 "reported as 0 (unknown), so nothing is enforced");
    } else if (c.max_insns > (1u << 20)) {
        not_here(NH_OTHER, "TESTED", "    max_insns",
                 "%lu, and an image past it is %llu bytes",
                 (unsigned long)c.max_insns,
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
        not_here(NH_OTHER, "TESTED", "    max_consts",
                 "reported as 0 (unknown), so nothing is enforced");
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
            not_here(NH_OTHER, "TESTED", "    max_consts, one past it",
                     "%lu, and an index past it does not fit the %s",
                     (unsigned long)c.max_consts,
                     c.max_consts >= 512u ? "immediate's nine bits"
                   : c.max_consts >= 256u ? "immediate's byte"
                                          : "four-bit field");
        }
    }

    /* max_scratch, on exactly the same terms: a static STL slot at the
     * cap must load and one past it must not. Both halves are always
     * representable here - the slot is imm[23:0], which reaches sixteen
     * million - so unlike max_consts no arm says NOT TESTED for want of
     * an encoding; only for want of a scratch, or of a cap. */
    if (!(c.seq_features & CFT_SEQ_FEAT_SCRATCH)) {
        not_here(NH_OTHER, "TESTED", "    max_scratch",
                 "no scratch published (max_scratch %lu)",
                 (unsigned long)c.max_scratch);
    } else if (!c.max_scratch) {
        not_here(NH_OTHER, "TESTED", "    max_scratch",
                 "SCRATCH published with max_scratch 0 (unknown), so "
                 "nothing is enforced");
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
     * CAPS2[7:4] in the third since revision 3, CAPS2[8] on bit 12
     * since ABI 0.13 (CFT_FEAT_REDUCE_SEG), and CAPS2[10:9] on bits 14
     * and 13 since ABI 0.14 (INDEXED, LANE_MASK). Anything above those
     * fifteen bits is a decode fault, not a feature. */
    checks++;
    if (c.seq_features & ~0x7FFFu) {
        printf("  FAIL %s: seq_features 0x%lx has bits outside CAPS[7:4], "
               "CAPS[31:28] and CAPS2[10:4]\n", who,
               (unsigned long)c.seq_features);
        failures++;
    }
    /* Every bit cft.h defines, SCRATCH_STRICT and SCALAR included since
     * 2026-09-24 - the line used to skip both, so a word that carried
     * them printed as though it did not. */
    printf("    features:%s%s%s%s%s%s%s%s%s%s%s%s   max_scratch %lu\n",
           (c.seq_features & CFT_SEQ_FEAT_WIDE_CONST) ? " kx" : "",
           (c.seq_features & CFT_SEQ_FEAT_REGS32)     ? " REGS32" : "",
           (c.seq_features & CFT_SEQ_FEAT_BANK_PTR)   ? " BANK_PTR" : "",
           (c.seq_features & CFT_SEQ_FEAT_KX9)        ? " KX9" : "",
           (c.seq_features & CFT_ALU_EXT_IMUL)        ? " IMUL" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCRATCH)    ? " SCRATCH" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) ? " SCRATCH_IO" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCRATCH_STRICT)
                                                   ? " SCRATCH_STRICT" : "",
           (c.seq_features & CFT_SEQ_FEAT_SCALAR)     ? " SCALAR" : "",
           (c.seq_features & CFT_FEAT_REDUCE_SEG)     ? " REDUCE_SEG" : "",
           (c.seq_features & CFT_SEQ_FEAT_INDEXED)    ? " INDEXED" : "",
           (c.seq_features & CFT_SEQ_FEAT_LANE_MASK)  ? " LANE_MASK" : "",
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
     * against a tile that predates R8: an image older than the
     * revision-4 pair, since every pair from that one on carries it.
     * Accepting a strict image on a device that cannot honour it would
     * run the program under the modulo, and that is a different
     * contract, not a graceful degradation. */
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
        not_here(NH_OTHER, "TESTED", "    KX9",
                 "kx absent, so KX9 has no encoding to test with");
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
        not_here(NH_OTHER, "TESTED", "  seq scratch, R4/R5",
                 "no scratch published on this device");
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

    /* ---- 2b. The same index under SCRATCH_STRICT: suppressed, +0,
     * and REPORTED --------------------------------------------------
     * Section 2's index again, in an image that asks for revision 4's
     * R8. Odd lanes carry the index past the depth and even lanes carry
     * 5, in ONE run, so a device that suppressed every lane because one
     * was out of range, or none because one was in, cannot pass:
     *
     *   an even lane  LDX reads slot 5 (a), STX writes b there -> a, b
     *   an odd lane   LDX reads +0, STX is suppressed          -> +0, a
     *
     * and STATUS carries CFT_STATUS_SCRATCH_RANGE, which is the half
     * nothing read back from a device until 2026-09-18: the XRT
     * backend masked STATUS down to bit 4 on the way out, the tile had
     * raised bit 5 all along, and every deposit was right - so a leg
     * that compared deposits alone would have passed (atlas-engine's
     * card day, 2026-09-17). Then the same image with every index in
     * range must report NOTHING, which is what says the word is this
     * run's and not the last one's. */
    if (c.max_scratch && (c.seq_features & CFT_SEQ_FEAT_SCRATCH_STRICT)) {
        const uint32_t past = 3u * c.max_scratch + 5u;
        int pass;
        ins[0] = seq_stl(0, 5);          /* slot 5 := a */
        ins[1] = seq_ldx(4, 2);          /* r4 := scratch[r2], or +0 */
        ins[2] = seq_ctrl(3, 4, 0);
        ins[3] = seq_stx(1, 2);          /* scratch[r2] := b, or nothing */
        ins[4] = seq_ldl(5, 5);          /* r5 := slot 5 */
        ins[5] = seq_ctrl(3, 5, 0);
        ins[6] = seq_ctrl(0, 0, 0);
        bytes = seq_image_flags(img, fmt, ins, 7, NULL, 0, 2,
                                CFT_PROG_FLAG_SCRATCH_STRICT);
        checks++;
        if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
            printf("  FAIL seq scratch: SCRATCH_STRICT is published and "
                   "the strict STX/LDX image did not load: %s\n",
                   cft_last_error());
            failures++;
        } else {
            for (pass = 0; pass < 2; pass++) {
                /* pass 0: odd lanes past the depth; pass 1: none */
                uint32_t fl = 0xFFu, bus = 0xFFFFFFFFu;
                const uint32_t want_bus =
                    (pass == 0 && n > 1) ? CFT_STATUS_SCRATCH_RANGE : 0u;
                for (i = 0; i < n; i++)
                    put_index(cc + i * esz, fmt,
                              (pass == 0 && (i & 1u)) ? past : 5u);
                checks++;
                if (cft_program_run(prog, a, b, cc, dep, cnt, n, &fl, &bus)
                    != CFT_OK) {
                    printf("  FAIL seq scratch: the strict STX/LDX program "
                           "did not run: %s\n", cft_last_error());
                    failures++;
                    continue;
                }
                {
                    uint8_t zero[MAXE];
                    int bad = 0;
                    memset(zero, 0, esz);
                    for (i = 0; i < n; i++) {
                        const int out = pass == 0 && (i & 1u);
                        const uint8_t *w0 = out ? zero : a + i * esz;
                        const uint8_t *w1 = out ? a + i * esz : b + i * esz;
                        if (memcmp(dep + (2 * i) * esz, w0, esz) != 0 ||
                            memcmp(dep + (2 * i + 1) * esz, w1, esz) != 0 ||
                            cnt[i] != 2)
                            bad = 1;
                    }
                    checks++;
                    if (bad) {
                        printf("  FAIL seq scratch: strict, an index of "
                               "%lu past a depth of %lu must read +0 and "
                               "store nothing, and an index of 5 beside "
                               "it must behave as ever (pass %d)\n",
                               (unsigned long)past,
                               (unsigned long)c.max_scratch, pass);
                        failures++;
                    }
                }
                checks++;
                if (bus != want_bus) {
                    printf("  FAIL seq scratch: strict, STATUS is %#x and "
                           "%#x was due - %s\n", bus, want_bus,
                           pass == 0
                           ? "an index past the depth must be REPORTED "
                             "(CFT_STATUS_SCRATCH_RANGE), not only "
                             "suppressed"
                           : "every index was in range, so the word must "
                             "be this run's and clean");
                    failures++;
                }
                checks++;
                if (fl != 0) {
                    printf("  FAIL seq scratch: strict, a suppressed "
                           "access raised flags 0x%02x - the range report "
                           "is deliberately not an IEEE flag\n", fl);
                    failures++;
                }
            }
            printf("    SCRATCH_STRICT: an index past the depth reads +0, "
                   "stores nothing and is reported; in range, nothing is\n");
            cft_program_free(prog);
            prog = NULL;
        }
    } else {
        not_here(NH_OTHER, "TESTED", "    R8's range report",
                 "this device does not publish SCRATCH_STRICT");
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


/* ==== ABI 0.14, R16: an input block fetched through an index table ====
 *
 * The device against the software backend, which is the definition -
 * and against ITSELF, which is the control: the same program over the
 * same n values with an IDENTITY table must give the dense run's bits
 * exactly, and with a PERMUTED table must not. The first alone would
 * pass on a device that ignored the table; the pair cannot.
 *
 * The program is `DEPOSIT r0`, so the deposit IS the gathered element
 * and a wrong entry is a wrong output rather than something an ALU
 * might have hidden. The source is deliberately shorter than the run,
 * which is the shape the feature exists for: the gravity fold reads a
 * short array of contributions from many lanes.
 * ==================================================================== */

static void check_indexed(cft_device *sw, cft_device *hw, cft_format fmt,
                          size_t n)
{
    const size_t esz = cft_format_size(fmt);
    const size_t src_n = (n / 3) + 1;          /* shorter than the run */
    uint8_t img[256];
    uint64_t ins[2];
    size_t bytes, i;
    cft_caps hc;
    uint8_t *src = (uint8_t *)malloc(src_n * esz);
    /* The DENSE operands, at n elements. cft_program_run_ex reads b
     * and c for every one of the run's n lanes whatever the program
     * names - the executor loads r1 and r2 from them unless the
     * pointer is NULL - so handing it the short SOURCE here read n
     * lanes out of a src_n-element allocation, which V1 reproduced
     * against a guard page. An indexed operand is the only one whose
     * buffer may be short, and only through its own table. */
    uint8_t *bdense = (uint8_t *)malloc(n * esz);
    uint8_t *dense = (uint8_t *)malloc(n * esz);
    uint8_t *d_sw = (uint8_t *)malloc(n * esz);
    uint8_t *d_hw = (uint8_t *)malloc(n * esz);
    uint8_t *d_id = (uint8_t *)malloc(n * esz);
    uint8_t *d_pm = (uint8_t *)malloc(n * esz);
    uint32_t *cnt = (uint32_t *)malloc(n * 4);
    uint32_t *tab = (uint32_t *)malloc(n * 4);
    uint32_t *ident = (uint32_t *)malloc(n * 4);
    cft_program *ps = NULL, *ph = NULL;
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    cft_status st;
    int holes = 0;

    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    if (cft_get_caps(hw, &hc) != CFT_OK)
        memset(&hc, 0, sizeof hc);
    if (!(hc.seq_features & CFT_SEQ_FEAT_INDEXED)) {
        not_here(NH_OTHER, "COMPARED", "  seq indexed inputs",
                 "this device does not publish CFT_SEQ_FEAT_INDEXED");
        goto out;
    }
    if (!src || !bdense || !dense || !d_sw || !d_hw || !d_id ||
        !d_pm || !cnt || !tab || !ident) {
        printf("  FAIL seq indexed: out of memory\n");
        failures++;
        goto out;
    }

    rs = 0x1D6E + (uint32_t)fmt;
    fill(src, src_n, esz);
    fill(bdense, n, esz);

    /* One in five entries is CFT_IDX_NONE, which must read as +0 -
     * derived here and checked below against the same rule, never
     * against a typed expectation. */
    for (i = 0; i < n; i++) {
        if (i % 5 == 0) {
            tab[i] = CFT_IDX_NONE;
            holes++;
            memset(dense + i * esz, 0, esz);       /* +0 */
        } else {
            tab[i] = (uint32_t)((i * 7 + 1) % src_n);
            memcpy(dense + i * esz, src + (size_t)tab[i] * esz, esz);
        }
        ident[i] = (uint32_t)i;
    }

    ins[0] = seq_ctrl(3, 0, 0);            /* DEPOSIT r0 */
    ins[1] = seq_ctrl(0, 0, 0);            /* HALT */
    bytes = seq_image(img, fmt, ins, 2, NULL, 0, 1);

    st = cft_program_load(sw, img, bytes, &ps);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed: the software backend refused the "
               "image (%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }
    st = cft_program_load(hw, img, bytes, &ph);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed: the device refused the image (%s)\n",
               cft_strerror(st));
        failures++;
        goto out;
    }

#define IDX_RUN(prog_, dst_, a_, an_, table_)                          \
    do {                                                               \
        memset(&A, 0, sizeof A);                                       \
        A.struct_size = sizeof A;                                      \
        A.a = (a_); A.b = bdense;  A.c = bdense;                            \
        A.n = n;                                                       \
        A.deposits = (dst_);                                           \
        A.counts = cnt;                                                \
        A.flags_out = &fl;                                             \
        A.bus_out = &bus;                                              \
        A.idx_a = (table_);                                            \
        A.idx_a_src = (table_) ? (an_) : 0;                            \
        memset((dst_), 0x5a, n * esz);                                 \
        st = cft_program_run_ex((prog_), &A);                          \
    } while (0)

    /* 1. the gathered run, software against the device. */
    IDX_RUN(ps, d_sw, src, src_n, tab);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed: the software backend refused the run "
               "(%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    IDX_RUN(ph, d_hw, src, src_n, tab);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed: the device refused the run (%s: %s)\n",
               cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    checks++;
    if (memcmp(d_sw, d_hw, n * esz) != 0) {
        for (i = 0; i < n * esz; i++)
            if (d_sw[i] != d_hw[i])
                break;
        printf("  FAIL seq indexed: the device and the software backend "
               "differ first at byte %lu (lane %lu, table entry %u)\n",
               (unsigned long)i, (unsigned long)(i / esz),
               tab[i / esz]);
        failures++;
    }
    /* ...and the answer is the gather's definition, element for
     * element, including +0 where the sentinel is. */
    checks++;
    if (memcmp(d_hw, dense, n * esz) != 0) {
        printf("  FAIL seq indexed: the run is not source[idx[i]] with "
               "CFT_IDX_NONE reading as +0 (%d sentinels in %lu "
               "entries)\n", holes, (unsigned long)n);
        failures++;
    }

    /* 2. the control. An identity table over a full-length source is
     *    the dense run, bit for bit; a rotation of it is not. */
    IDX_RUN(ph, d_id, dense, n, ident);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed: an identity table was refused (%s)\n",
               cft_strerror(st));
        failures++;
        goto out;
    }
    IDX_RUN(ph, d_pm, dense, n, NULL);
    checks++;
    if (st != CFT_OK || memcmp(d_id, d_pm, n * esz) != 0) {
        printf("  FAIL seq indexed: an identity table is not the dense "
               "run on this device\n");
        failures++;
    }
    if (n > 1) {
        for (i = 0; i < n; i++)
            ident[i] = (uint32_t)((i + 1) % n);
        IDX_RUN(ph, d_pm, dense, n, ident);
        checks++;
        if (st != CFT_OK) {
            printf("  FAIL seq indexed: a rotated table was refused "
                   "(%s)\n", cft_strerror(st));
            failures++;
        } else if (memcmp(d_id, d_pm, n * esz) == 0) {
            printf("  FAIL seq indexed: a ROTATED table gave the dense "
                   "run's bits, so the control above could not have "
                   "failed - the table may be being ignored\n");
            failures++;
        }
    }

    /* 3. the bound, on both backends: an index AT the source's length
     *    is refused by name and by value, before the run. */
    for (i = 0; i < n; i++)
        ident[i] = (uint32_t)((i + 1) % n);
    ident[n / 2] = (uint32_t)n;                /* one past the last */
    IDX_RUN(ps, d_pm, dense, n, ident);
    checks++;
    if (st != CFT_ERR_INVALID_ARGUMENT) {
        printf("  FAIL seq indexed: the software backend accepted an "
               "index at the source's length (%s)\n", cft_strerror(st));
        failures++;
    }
    IDX_RUN(ph, d_pm, dense, n, ident);
    checks++;
    if (st != CFT_ERR_INVALID_ARGUMENT) {
        printf("  FAIL seq indexed: the device accepted an index at the "
               "source's length (%s)\n", cft_strerror(st));
        failures++;
    }
#undef IDX_RUN

    printf("  seq indexed inputs: %lu lanes through a %lu-element "
           "source, %d of them +0, identity == dense and rotated != "
           "dense, the bound refused on both\n",
           (unsigned long)n, (unsigned long)src_n, holes);
out:
    cft_program_free(ps);
    cft_program_free(ph);
    free(src); free(bdense); free(dense); free(d_sw); free(d_hw);
    free(d_id); free(d_pm); free(cnt); free(tab); free(ident);
}

/* ---------------------------------------------------------------
 * R16 for an ELEMENTWISE run: cft_run_ex's index tables     (P2)
 *
 * The claim is that an indexed elementwise run IS the dense run over
 * the gathered operands - every bit and every flag, on both backends,
 * at every opcode, attribute and format the device carries. So the
 * reference is built HERE, by gathering with the contract's own
 * sentence (element i is source[idx[i]], and CFT_IDX_NONE is +0) and
 * running the ordinary cft_run over it. Nothing below asks the
 * library what the answer ought to be.
 *
 * Three more properties ride along, because they are the same run:
 *
 *  - the IDENTITY control (idx[i] = i over a full-length source) is
 *    bit-identical to the plain dense run, and a ROTATION of it is
 *    not. The first alone would pass on a gather that ignored its
 *    table, which is what makes the second the half that matters;
 *  - the FLAGS of the indexed run are the flags of the dense one.
 *    A program run's flags are the sticky OR over active lanes and an
 *    elementwise run's are the OR over elements - the same set said
 *    twice, which the composition needs and does not get to assume;
 *  - and the same tables through cft_program_run_ex over the very
 *    three-instruction program the library composes, which holds the
 *    composition's SHAPE to the same answer. On a software device the
 *    library takes the gather route, so this is what gates the shape
 *    the device route builds.
 * --------------------------------------------------------------- */

/* Which operands this opcode reads, asked of the library rather than
 * transcribed into a table here: a NULL operand the opcode needs is
 * CFT_ERR_INVALID_ARGUMENT and one it does not need runs. Derived, so
 * that an opcode whose operand set changes cannot leave a stale copy
 * of it in this file. */
static unsigned op_reads_probe(cft_device *dev, cft_op op, cft_format fmt)
{
    uint8_t one[MAXE], out[MAXE];
    unsigned mask = 0;
    int r;
    memset(one, 0, sizeof one);
    for (r = 0; r < 3; r++) {
        const void *p[3];
        p[0] = p[1] = p[2] = one;
        p[r] = NULL;
        if (cft_run(dev, op, fmt, CFT_RNE, p[0], p[1], p[2], out, 1,
                    NULL, NULL) == CFT_ERR_INVALID_ARGUMENT)
            mask |= 1u << r;
    }
    return mask;
}

/* The contract's gather, written out once here so the test's answer
 * and the library's cannot come from the same code. */
static void gather_ref(uint8_t *dst, const uint8_t *src,
                       const uint32_t *idx, size_t n, size_t esz)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (idx[i] == CFT_IDX_NONE)
            memset(dst + i * esz, 0, esz);          /* +0 */
        else
            memcpy(dst + i * esz, src + (size_t)idx[i] * esz, esz);
    }
}

static void compare_indexed_elem(cft_device *sw, cft_device *hw,
                                 cft_format fmt, cft_op op, cft_round rnd,
                                 size_t n, uint32_t seed)
{
    const size_t esz = cft_format_size(fmt);
    const size_t src_n = (n / 3) + 1;       /* deliberately short */
    unsigned need;
    uint8_t *src[3], *gat[3], *full[3];
    uint32_t *tab[3], *ident = NULL, *rot = NULL;
    uint8_t *d_ref = NULL, *d_idx = NULL, *d_sw = NULL;
    uint8_t *d_dense = NULL, *d_id = NULL, *d_rot = NULL, *d_rref = NULL;
    uint8_t *d_prog = NULL;
    uint8_t img[256];
    uint64_t ins[3];
    uint32_t fld[3];
    int n_strm = 0;
    size_t ibytes, i;
    int r, holes = 0;
    uint32_t f_ref = 0, f_idx = 0, f_sw = 0, f_dense = 0, f_prog = 0;
    uint32_t bus_ref = 0, bus_run = 0;
    cft_status st;
    cft_elem_args E;
    cft_run_args A;
    cft_program *prog = NULL;

    for (r = 0; r < 3; r++) {
        src[r] = gat[r] = full[r] = NULL;
        tab[r] = NULL;
    }
    need = op_reads_probe(sw, op, fmt);
    if (need == 0)
        return;            /* nothing to index; the refusal is scored
                            * in check_indexed_elem_refusals */

    rs = seed ? seed : 1;
    for (r = 0; r < 3; r++) {
        if (!((need >> r) & 1u))
            continue;
        src[r]  = (uint8_t *)malloc(src_n * esz);
        gat[r]  = (uint8_t *)malloc(n * esz);
        full[r] = (uint8_t *)malloc(n * esz);
        tab[r]  = (uint32_t *)malloc(n * 4);
        if (!src[r] || !gat[r] || !full[r] || !tab[r]) {
            CHECK(0, "idx elem %s: out of memory", cft_format_name(fmt));
            goto out;
        }
        fill(src[r], src_n, esz);
        fill(full[r], n, esz);
    }
    ident  = (uint32_t *)malloc(n * 4);
    rot    = (uint32_t *)malloc(n * 4);
    d_ref  = (uint8_t *)malloc(n * esz);
    d_idx  = (uint8_t *)malloc(n * esz);
    d_sw   = (uint8_t *)malloc(n * esz);
    d_dense= (uint8_t *)malloc(n * esz);
    d_id   = (uint8_t *)malloc(n * esz);
    d_rot  = (uint8_t *)malloc(n * esz);
    d_rref = (uint8_t *)malloc(n * esz);
    d_prog = (uint8_t *)malloc(n * esz);
    if (!ident || !rot || !d_ref || !d_idx || !d_sw || !d_dense ||
        !d_id || !d_rot || !d_rref || !d_prog) {
        CHECK(0, "idx elem %s: out of memory", cft_format_name(fmt));
        goto out;
    }

    /* One table per read operand. A different stride each, so two
     * operands never take the same element in the same lane, and one
     * entry in five is the sentinel - derived here and reflected in
     * the reference by the same rule, never by a typed expectation. */
    for (i = 0; i < n; i++) {
        ident[i] = (uint32_t)i;
        rot[i]   = (uint32_t)((i + 1) % n);
        for (r = 0; r < 3; r++) {
            if (!tab[r])
                continue;
            if ((i + (size_t)r) % 5 == 0) {
                tab[r][i] = CFT_IDX_NONE;
                if (r == 0)
                    holes++;
            } else {
                tab[r][i] =
                    (uint32_t)((i * (size_t)(2 * r + 3) + 1) % src_n);
            }
        }
    }
    for (r = 0; r < 3; r++)
        if (tab[r])
            gather_ref(gat[r], src[r], tab[r], n, esz);

    /* 1. the reference: the dense run over the gathered operands. */
    st = cft_run(hw, op, fmt, rnd, gat[0], gat[1], gat[2], d_ref, n,
                 &f_ref, &bus_ref);
    CHECK(st == CFT_OK, "idx elem %s %s: the dense reference run was "
          "refused (%s)", cft_format_name(fmt), cft_op_name(op),
          cft_strerror(st));
    if (st != CFT_OK)
        goto out;

#define ELEM_RUN(dev_, dst_, f_, s0_, s1_, s2_, t0_, t1_, t2_, sn_)     \
    do {                                                               \
        memset(&E, 0, sizeof E);                                       \
        E.struct_size = sizeof E;                                      \
        E.a = (s0_); E.b = (s1_); E.c = (s2_);                         \
        E.d = (dst_);                                                  \
        E.n = n;                                                       \
        E.flags_out = (f_);                                            \
        E.bus_out = &bus_run;                                          \
        E.idx_a = (t0_); E.idx_b = (t1_); E.idx_c = (t2_);             \
        E.idx_a_src = (t0_) ? (sn_) : 0;                               \
        E.idx_b_src = (t1_) ? (sn_) : 0;                               \
        E.idx_c_src = (t2_) ? (sn_) : 0;                               \
        memset((dst_), 0x5a, n * esz);                                 \
        st = cft_run_ex((dev_), op, fmt, rnd, &E);                     \
    } while (0)

    /* 2. the same run through the tables, on the device and on the
     *    software backend. Both must be the reference, bit for bit
     *    and flag for flag. */
    ELEM_RUN(hw, d_idx, &f_idx, src[0], src[1], src[2],
             tab[0], tab[1], tab[2], src_n);
    CHECK(st == CFT_OK, "idx elem %s %s: the device refused the indexed "
          "run (%s: %s)", cft_format_name(fmt), cft_op_name(op),
          cft_strerror(st), cft_last_error());
    /* The STATUS word too: on a device the composed route returns the
     * program run's word where the dense run returns the engine's, and
     * both are zero on a host, so this comparison first means something
     * on a card (V2, 2026-09-15). */
    CHECK(st != CFT_OK || bus_run == bus_ref,
          "idx elem %s %s: STATUS %#x on the indexed route, %#x on the "
          "dense run", cft_format_name(fmt), cft_op_name(op),
          (unsigned)bus_run, (unsigned)bus_ref);
    if (st != CFT_OK)
        goto out;
    ELEM_RUN(sw, d_sw, &f_sw, src[0], src[1], src[2],
             tab[0], tab[1], tab[2], src_n);
    CHECK(st == CFT_OK, "idx elem %s %s: the software backend refused "
          "the indexed run (%s: %s)", cft_format_name(fmt),
          cft_op_name(op), cft_strerror(st), cft_last_error());
    if (st != CFT_OK)
        goto out;
    CHECK(memcmp(d_idx, d_ref, n * esz) == 0,
          "idx elem %s %s rnd %d: the device's indexed run is not the "
          "dense run over the gathered operands (%lu lanes, %d sentinels "
          "in a, source %lu elements)", cft_format_name(fmt),
          cft_op_name(op), (int)rnd, (unsigned long)n, holes,
          (unsigned long)src_n);
    CHECK(memcmp(d_sw, d_ref, n * esz) == 0,
          "idx elem %s %s rnd %d: the software backend's indexed run is "
          "not the dense run over the gathered operands",
          cft_format_name(fmt), cft_op_name(op), (int)rnd);
    CHECK(f_idx == f_ref, "idx elem %s %s: device flags 0x%02x, dense "
          "0x%02x", cft_format_name(fmt), cft_op_name(op),
          (unsigned)f_idx, (unsigned)f_ref);
    CHECK(f_sw == f_ref, "idx elem %s %s: software flags 0x%02x, dense "
          "0x%02x", cft_format_name(fmt), cft_op_name(op),
          (unsigned)f_sw, (unsigned)f_ref);

    /* 3. the controls. An identity table over a FULL-LENGTH source is
     *    the plain dense run, bit for bit; a rotation of the same
     *    table is the dense run over the rotated operands and - where
     *    those differ at all - not the dense run. */
    st = cft_run(hw, op, fmt, rnd, full[0], full[1], full[2], d_dense, n,
                 &f_dense, NULL);
    CHECK(st == CFT_OK, "idx elem %s %s: the plain dense run was refused "
          "(%s)", cft_format_name(fmt), cft_op_name(op), cft_strerror(st));
    if (st != CFT_OK)
        goto out;
    ELEM_RUN(hw, d_id, NULL, full[0], full[1], full[2],
             tab[0] ? ident : NULL, tab[1] ? ident : NULL,
             tab[2] ? ident : NULL, n);
    CHECK(st == CFT_OK, "idx elem %s %s: an identity table was refused "
          "(%s)", cft_format_name(fmt), cft_op_name(op), cft_strerror(st));
    CHECK(st != CFT_OK || memcmp(d_id, d_dense, n * esz) == 0,
          "idx elem %s %s rnd %d: an identity table is not the dense run",
          cft_format_name(fmt), cft_op_name(op), (int)rnd);

    for (r = 0; r < 3; r++)
        if (tab[r])
            gather_ref(gat[r], full[r], rot, n, esz);
    st = cft_run(hw, op, fmt, rnd, tab[0] ? gat[0] : full[0],
                 tab[1] ? gat[1] : full[1], tab[2] ? gat[2] : full[2],
                 d_rref, n, NULL, NULL);
    CHECK(st == CFT_OK, "idx elem %s %s: the rotated reference was "
          "refused (%s)", cft_format_name(fmt), cft_op_name(op),
          cft_strerror(st));
    ELEM_RUN(hw, d_rot, NULL, full[0], full[1], full[2],
             tab[0] ? rot : NULL, tab[1] ? rot : NULL,
             tab[2] ? rot : NULL, n);
    CHECK(st == CFT_OK, "idx elem %s %s: a rotated table was refused "
          "(%s)", cft_format_name(fmt), cft_op_name(op), cft_strerror(st));
    CHECK(st != CFT_OK || memcmp(d_rot, d_rref, n * esz) == 0,
          "idx elem %s %s rnd %d: a rotated table is not the dense run "
          "over the rotated operands", cft_format_name(fmt),
          cft_op_name(op), (int)rnd);
    /* The discriminating half, asserted only where this opcode and
     * this data CAN discriminate: if the rotated reference happens to
     * equal the dense one, a run that ignored its table would too, and
     * the honest thing is to say so rather than to assert nothing or
     * to assert something that is not true of the data. */
    if (memcmp(d_rref, d_dense, n * esz) != 0)
        CHECK(memcmp(d_rot, d_dense, n * esz) != 0,
              "idx elem %s %s rnd %d: a rotated table gave the DENSE "
              "answer - the table is being ignored",
              cft_format_name(fmt), cft_op_name(op), (int)rnd);

    /* 4. the composition's shape: the same tables through
     *    cft_program_run_ex over the three-instruction program the
     *    library builds on a device - `op r3, <streams>; DEPOSIT r3;
     *    HALT` with max_deposits 1, the streams packed down in operand
     *    order and an operand the opcode does not read carrying r4.
     *    Built here, so that the encoding is checked against a second
     *    reading of docs/SEQUENCER.md rather than against itself. */
    for (r = 0; r < 3; r++)
        fld[r] = ((need >> r) & 1u) ? (uint32_t)(n_strm++) : 4u;
    ins[0] = seq_alu5((unsigned)op, 3, fld[0], fld[1], fld[2],
                      (unsigned)rnd, 0, 0, 0);
    ins[1] = seq_ctrl(3, 3, 0);                 /* DEPOSIT r3 */
    ins[2] = seq_ctrl(0, 0, 0);                 /* HALT */
    ibytes = seq_image(img, fmt, ins, 3, NULL, 0, 1);
    st = cft_program_load(hw, img, ibytes, &prog);
    CHECK(st == CFT_OK, "idx elem %s %s: the composed image was refused "
          "(%s)", cft_format_name(fmt), cft_op_name(op), cft_strerror(st));
    if (st == CFT_OK) {
        const void *pstrm[3];
        const uint32_t *ptab[3];
        size_t psrc[3];
        int s = 0;
        pstrm[0] = pstrm[1] = pstrm[2] = NULL;
        ptab[0] = ptab[1] = ptab[2] = NULL;
        psrc[0] = psrc[1] = psrc[2] = 0;
        for (r = 0; r < 3; r++) {
            if (!((need >> r) & 1u))
                continue;
            pstrm[s] = src[r];
            ptab[s]  = tab[r];
            psrc[s]  = src_n;
            s++;
        }
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = pstrm[0]; A.b = pstrm[1]; A.c = pstrm[2];
        A.n = n;
        A.deposits = d_prog;
        A.flags_out = &f_prog;
        A.idx_a = ptab[0]; A.idx_b = ptab[1]; A.idx_c = ptab[2];
        A.idx_a_src = psrc[0]; A.idx_b_src = psrc[1];
        A.idx_c_src = psrc[2];
        memset(d_prog, 0x5a, n * esz);
        st = cft_program_run_ex(prog, &A);
        CHECK(st == CFT_OK, "idx elem %s %s: the composed program run was "
              "refused (%s: %s)", cft_format_name(fmt), cft_op_name(op),
              cft_strerror(st), cft_last_error());
        CHECK(st != CFT_OK || memcmp(d_prog, d_ref, n * esz) == 0,
              "idx elem %s %s rnd %d: the three-instruction program with "
              "the same tables is not the dense run over the gathered "
              "operands", cft_format_name(fmt), cft_op_name(op), (int)rnd);
        CHECK(st != CFT_OK || f_prog == f_ref,
              "idx elem %s %s: the program run's flags are 0x%02x and the "
              "elementwise run's are 0x%02x - the sticky OR over active "
              "lanes and the OR over elements are the same set",
              cft_format_name(fmt), cft_op_name(op),
              (unsigned)f_prog, (unsigned)f_ref);
    }
out:
    cft_program_free(prog);
#undef ELEM_RUN
    for (r = 0; r < 3; r++) {
        free(src[r]); free(gat[r]); free(full[r]); free(tab[r]);
    }
    free(ident); free(rot);
    free(d_ref); free(d_idx); free(d_sw); free(d_dense);
    free(d_id); free(d_rot); free(d_rref); free(d_prog);
}

/* A SCALAR operand beside an INDEXED one - the shape the composition
 * cannot express as a stream, because the sequencer has no stride-0
 * one, and which the library therefore puts in the program's own
 * CONSTANT BANK.
 *
 * EVERY ORDERED PAIR the opcode allows, at every format (V2's finding,
 * 2026-09-15: this leg used to make operand `a` the scalar and nothing
 * else, so a scalar `b` or `c` beside an indexed operand was in no
 * gate). FMA gives six pairs, ADD and MUL two each, a unary opcode
 * none - and the pair matters, because which operand is the scalar
 * decides which STREAM SLOT each of the others lands in once the
 * streams pack down past it.
 *
 * Two things are checked per pair and they are different things: that
 * the call gives the dense answer over (the scalar repeated, the
 * gathered operand, the rest dense), and that the PROGRAM form of it -
 * one constant in the image, that operand's field carrying the
 * constant's index with its `k` bit set, the streams packed down past
 * it - gives the same. The second is the encoding the device route
 * builds, held to the first. */
static void compare_indexed_scalar(cft_device *sw, cft_device *hw,
                                   cft_format fmt, cft_op op, size_t n,
                                   uint32_t seed)
{
    const size_t esz = cft_format_size(fmt);
    const size_t src_n = (n / 2) + 1;
    unsigned need = op_reads_probe(sw, op, fmt);
    uint8_t *sc = NULL, *rep = NULL, *src = NULL, *gat = NULL, *dns = NULL;
    uint8_t *d_ref = NULL, *d_mix = NULL, *d_sw = NULL, *d_prog = NULL;
    uint32_t *tab = NULL;
    uint8_t img[256];
    uint64_t ins[3];
    size_t ibytes, i;
    int s, x, pairs = 0;
    cft_status st;
    cft_elem_args E;
    cft_run_args A;
    cft_program *prog = NULL;

    /* Needs at least two operands: one to be the scalar and one to
     * carry the table. */
    if (need != 3u && need != 5u && need != 6u && need != 7u)
        return;

    sc     = (uint8_t *)malloc(esz);
    rep    = (uint8_t *)malloc(n * esz);
    src    = (uint8_t *)malloc(src_n * esz);
    gat    = (uint8_t *)malloc(n * esz);
    dns    = (uint8_t *)malloc(n * esz);
    d_ref  = (uint8_t *)malloc(n * esz);
    d_mix  = (uint8_t *)malloc(n * esz);
    d_sw   = (uint8_t *)malloc(n * esz);
    d_prog = (uint8_t *)malloc(n * esz);
    tab    = (uint32_t *)malloc(n * 4);
    if (!sc || !rep || !src || !gat || !dns || !d_ref || !d_mix ||
        !d_sw || !d_prog || !tab) {
        CHECK(0, "idx+scalar %s: out of memory", cft_format_name(fmt));
        goto out;
    }

    rs = seed ? seed : 1;
    fill(sc, 1, esz);
    fill(src, src_n, esz);
    fill(dns, n, esz);
    for (i = 0; i < n; i++) {
        memcpy(rep + i * esz, sc, esz);         /* the scalar, repeated */
        tab[i] = (i % 4 == 0) ? CFT_IDX_NONE
                              : (uint32_t)((i * 5 + 2) % src_n);
    }
    gather_ref(gat, src, tab, n, esz);

    for (s = 0; s < 3; s++) {
        if (!((need >> s) & 1u))
            continue;
        for (x = 0; x < 3; x++) {
            const void *ref[3], *ev[3];
            const uint32_t *et[3];
            uint32_t f_ref = 0, f_mix = 0, f_sw = 0, f_prog = 0;
            int r;
            if (x == s || !((need >> x) & 1u))
                continue;

            /* The operands, three ways: the REFERENCE has the scalar
             * repeated and the indexed one gathered; the CALL has the
             * one-element buffer and the source with its table; and the
             * third operand, where the opcode reads one, is the same
             * dense array in both. */
            for (r = 0; r < 3; r++) {
                if (!((need >> r) & 1u)) { ref[r] = ev[r] = NULL; et[r] = NULL; continue; }
                if (r == s)      { ref[r] = rep; ev[r] = sc;  et[r] = NULL; }
                else if (r == x) { ref[r] = gat; ev[r] = src; et[r] = tab;  }
                else             { ref[r] = dns; ev[r] = dns; et[r] = NULL; }
            }

            st = cft_run(hw, op, fmt, CFT_RNE, ref[0], ref[1], ref[2],
                         d_ref, n, &f_ref, NULL);
            CHECK(st == CFT_OK, "idx+scalar %s %s (scalar %c, indexed %c): "
                  "the reference run was refused (%s)", cft_format_name(fmt),
                  cft_op_name(op), 'a' + s, 'a' + x, cft_strerror(st));
            if (st != CFT_OK)
                continue;

#define MIX_RUN(dev_, dst_, f_)                                        \
            do {                                                       \
                memset(&E, 0, sizeof E);                               \
                E.struct_size = sizeof E;                              \
                E.a = ev[0]; E.b = ev[1]; E.c = ev[2];                 \
                E.d = (dst_); E.n = n;                                 \
                E.scalar_mask = 1u << s;                               \
                E.flags_out = (f_);                                    \
                if (x == 0) { E.idx_a = tab; E.idx_a_src = src_n; }    \
                if (x == 1) { E.idx_b = tab; E.idx_b_src = src_n; }    \
                if (x == 2) { E.idx_c = tab; E.idx_c_src = src_n; }    \
                memset((dst_), 0x5a, n * esz);                         \
                st = cft_run_ex((dev_), op, fmt, CFT_RNE, &E);         \
            } while (0)

            MIX_RUN(hw, d_mix, &f_mix);
            CHECK(st == CFT_OK, "idx+scalar %s %s: a scalar %c beside an "
                  "indexed %c was refused on the device (%s: %s)",
                  cft_format_name(fmt), cft_op_name(op), 'a' + s, 'a' + x,
                  cft_strerror(st), cft_last_error());
            if (st != CFT_OK)
                continue;
            MIX_RUN(sw, d_sw, &f_sw);
            CHECK(st == CFT_OK, "idx+scalar %s %s: a scalar %c beside an "
                  "indexed %c was refused on the software backend (%s: %s)",
                  cft_format_name(fmt), cft_op_name(op), 'a' + s, 'a' + x,
                  cft_strerror(st), cft_last_error());
#undef MIX_RUN
            CHECK(memcmp(d_mix, d_ref, n * esz) == 0,
                  "idx+scalar %s %s: a scalar %c beside an indexed %c is "
                  "not the dense run over the repeated scalar and the "
                  "gathered operand", cft_format_name(fmt), cft_op_name(op),
                  'a' + s, 'a' + x);
            CHECK(memcmp(d_sw, d_ref, n * esz) == 0,
                  "idx+scalar %s %s (scalar %c, indexed %c): the software "
                  "backend differs from the dense run",
                  cft_format_name(fmt), cft_op_name(op), 'a' + s, 'a' + x);
            CHECK(f_mix == f_ref && f_sw == f_ref,
                  "idx+scalar %s %s (scalar %c, indexed %c): flags "
                  "0x%02x/0x%02x, dense 0x%02x", cft_format_name(fmt),
                  cft_op_name(op), 'a' + s, 'a' + x,
                  (unsigned)f_mix, (unsigned)f_sw, (unsigned)f_ref);

            /* And the program form, with the library's packing rule
             * followed here independently: an operand the opcode does
             * not read carries r4, the scalar carries its constant
             * index with the `k` bit set, and every other read operand
             * takes the next free STREAM slot - which is a different
             * slot for each of the six pairs, and is why the pair has
             * to be swept rather than sampled. */
            {
                const void *pstrm[3];
                const uint32_t *ptab[3];
                size_t psrc[3];
                unsigned fld[3], kb_[3];
                int strm = 0;
                pstrm[0] = pstrm[1] = pstrm[2] = NULL;
                ptab[0] = ptab[1] = ptab[2] = NULL;
                psrc[0] = psrc[1] = psrc[2] = 0;
                for (r = 0; r < 3; r++) {
                    if (!((need >> r) & 1u)) { fld[r] = 4u; kb_[r] = 0u; continue; }
                    if (r == s)              { fld[r] = 0u; kb_[r] = 1u; continue; }
                    pstrm[strm] = ev[r];
                    ptab[strm]  = et[r];
                    psrc[strm]  = et[r] ? src_n : 0;
                    fld[r] = (unsigned)strm;
                    kb_[r] = 0u;
                    strm++;
                }
                ins[0] = seq_alu5((unsigned)op, 3, fld[0], fld[1], fld[2],
                                  (unsigned)CFT_RNE, kb_[0], kb_[1], kb_[2]);
                ins[1] = seq_ctrl(3, 3, 0);
                ins[2] = seq_ctrl(0, 0, 0);
                ibytes = seq_image(img, fmt, ins, 3, sc, 1, 1);
                st = cft_program_load(hw, img, ibytes, &prog);
                CHECK(st == CFT_OK, "idx+scalar %s %s (scalar %c): the "
                      "one-constant image was refused (%s)",
                      cft_format_name(fmt), cft_op_name(op), 'a' + s,
                      cft_strerror(st));
                if (st == CFT_OK) {
                    memset(&A, 0, sizeof A);
                    A.struct_size = sizeof A;
                    A.a = pstrm[0]; A.b = pstrm[1]; A.c = pstrm[2];
                    A.n = n;
                    A.deposits = d_prog;
                    A.flags_out = &f_prog;
                    A.idx_a = ptab[0]; A.idx_b = ptab[1]; A.idx_c = ptab[2];
                    A.idx_a_src = psrc[0]; A.idx_b_src = psrc[1];
                    A.idx_c_src = psrc[2];
                    memset(d_prog, 0x5a, n * esz);
                    st = cft_program_run_ex(prog, &A);
                    CHECK(st == CFT_OK, "idx+scalar %s %s (scalar %c, "
                          "indexed %c): the one-constant program run was "
                          "refused (%s: %s)", cft_format_name(fmt),
                          cft_op_name(op), 'a' + s, 'a' + x,
                          cft_strerror(st), cft_last_error());
                    CHECK(st != CFT_OK ||
                          memcmp(d_prog, d_ref, n * esz) == 0,
                          "idx+scalar %s %s (scalar %c, indexed %c): the "
                          "scalar in the program's constant bank is not "
                          "the scalar repeated over n lanes",
                          cft_format_name(fmt), cft_op_name(op),
                          'a' + s, 'a' + x);
                    CHECK(st != CFT_OK || f_prog == f_ref,
                          "idx+scalar %s %s (scalar %c, indexed %c): "
                          "constant-bank flags 0x%02x, dense 0x%02x",
                          cft_format_name(fmt), cft_op_name(op),
                          'a' + s, 'a' + x,
                          (unsigned)f_prog, (unsigned)f_ref);
                }
                cft_program_free(prog);
                prog = NULL;
            }
            pairs++;
        }
    }
    printf("    %s %s: %d (scalar, indexed) operand pairs, call and "
           "constant-bank program both == dense\n",
           cft_format_name(fmt), cft_op_name(op), pairs);
out:
    cft_program_free(prog);
    free(sc); free(rep); free(src); free(gat); free(dns);
    free(d_ref); free(d_mix); free(d_sw); free(d_prog); free(tab);
}

/* The refusals cft_run_ex's tables carry, which are the library's own
 * and reach no device - so they are scored on the software handle and
 * are the same sentence on every backend. Three of them are this
 * parcel's decisions and are the reason they are written down:
 *
 *  - a table on an operand the OPCODE does not read is refused by
 *    name, not ignored the way the dense path ignores the operand;
 *  - `d` overlapping an INDEXED source is refused, because a gathered
 *    lane reads any element of its source and a source the run is also
 *    writing is read after write;
 *  - an index at or past idx_*_src is refused before the run, by name
 *    and by value, on every backend. */
static void check_indexed_elem_refusals(cft_device *dev, cft_format fmt,
                                        size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *d = (uint8_t *)malloc(n * esz);
    uint32_t *tab = (uint32_t *)malloc(n * 4);
    cft_elem_args E;
    cft_status st;
    size_t i;

    if (!a || !b || !d || !tab)
        goto out;
    rs = 0x1D6E ^ (uint32_t)fmt;
    fill(a, n, esz);
    fill(b, n, esz);
    for (i = 0; i < n; i++)
        tab[i] = (uint32_t)(i % n);

#define EX_REFUSE(setup_)                                              \
    do {                                                               \
        memset(&E, 0, sizeof E);                                       \
        E.struct_size = sizeof E;                                      \
        E.a = a; E.b = b; E.c = b;                                     \
        E.d = d; E.n = n;                                              \
        setup_;                                                        \
        st = cft_run_ex(dev, CFT_ADD, fmt, CFT_RNE, &E);               \
    } while (0)

    /* CFT_ADD reads a and c and does NOT read b (b is steered to 1.0),
     * which is the brief's own example - asserted here rather than
     * assumed, so that this case cannot quietly stop being the case it
     * means to be. */
    CHECK((op_reads_probe(dev, CFT_ADD, fmt) & 2u) == 0,
          "idx refusals %s: CFT_ADD is expected not to read operand b "
          "and this device says it does", cft_format_name(fmt));

    EX_REFUSE(E.idx_b = tab; E.idx_b_src = n);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT,
          "idx refusals %s: a table on operand b of CFT_ADD, which does "
          "not read it, was not refused (%s)", cft_format_name(fmt),
          cft_strerror(st));

    /* d overlapping the indexed source. Exactly aliased first, then
     * overlapping by one element - the second is the case a pointer
     * comparison would miss. */
    EX_REFUSE(E.idx_a = tab; E.idx_a_src = n; E.d = a);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT,
          "idx refusals %s: d aliasing the indexed source a was not "
          "refused (%s)", cft_format_name(fmt), cft_strerror(st));
    if (n > 1) {
        EX_REFUSE(E.idx_a = tab; E.idx_a_src = n; E.d = a + esz);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT,
              "idx refusals %s: d overlapping the indexed source a by "
              "n-1 elements was not refused (%s)", cft_format_name(fmt),
              cft_strerror(st));
    }
    /* ...and a DENSE operand aliased with d is refused too WHEN A
     * TABLE IS PRESENT, because the run is then a program whose
     * deposit window is a separate buffer role. */
    EX_REFUSE(E.idx_c = tab; E.idx_c_src = n; E.d = a);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT,
          "idx refusals %s: d aliasing the dense operand a beside an "
          "indexed c was not refused (%s)", cft_format_name(fmt),
          cft_strerror(st));
    /* ...while a DENSE RUN with no table at all still allows it, which
     * is what makes the rule above a rule about gathering and not a
     * new restriction on cft_run_ex. */
    EX_REFUSE(E.d = a);
    CHECK(st == CFT_OK,
          "idx refusals %s: d aliasing a in a dense cft_run_ex was "
          "refused (%s: %s)", cft_format_name(fmt), cft_strerror(st),
          cft_last_error());

    /* The bound: one index at the source's length, one far past it. */
    tab[n / 2] = (uint32_t)n;
    EX_REFUSE(E.idx_a = tab; E.idx_a_src = n);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT,
          "idx refusals %s: an index AT idx_a_src was not refused (%s)",
          cft_format_name(fmt), cft_strerror(st));
    tab[n / 2] = 0xFFFFFFFEu;
    EX_REFUSE(E.idx_a = tab; E.idx_a_src = n);
    CHECK(st == CFT_ERR_INVALID_ARGUMENT,
          "idx refusals %s: an index far past idx_a_src was not refused "
          "(%s)", cft_format_name(fmt), cft_strerror(st));
    /* ...and CFT_IDX_NONE in the same slot is NOT out of range. */
    tab[n / 2] = CFT_IDX_NONE;
    EX_REFUSE(E.idx_a = tab; E.idx_a_src = n);
    CHECK(st == CFT_OK,
          "idx refusals %s: CFT_IDX_NONE was treated as an index (%s: %s)",
          cft_format_name(fmt), cft_strerror(st), cft_last_error());
#undef EX_REFUSE

out:
    free(a); free(b); free(d); free(tab);
}

/* ABI 0.14's lane mask (docs/SEQUENCER.md R17), device against
 * software. Three claims, and they fail differently:
 *
 *   1. the two backends agree, lane for lane, under a mask with holes;
 *   2. an ALL-ONES mask is bit-identical to no mask, and a mask with
 *      holes is not - the second half being what makes the first a
 *      gate rather than a tautology;
 *   3. a masked lane's deposit slots and count are NOT WRITTEN - the
 *      buffers keep the pattern put there before the run, which is the
 *      one claim a comparison against a zeroed buffer cannot make,
 *      because "+0 written" and "not written" are the same bytes
 *      there.
 *
 * Every output buffer is filled with a pattern before every run, the
 * discipline the other legs in this file use for the same reason. */
static void check_masked(cft_device *sw, cft_device *hw, cft_format fmt,
                         size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t img[256];
    uint64_t ins[3];
    size_t bytes, i;
    cft_caps hc;
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *d_sw = (uint8_t *)malloc(n * esz);
    uint8_t *d_hw = (uint8_t *)malloc(n * esz);
    uint8_t *d_pl = (uint8_t *)malloc(n * esz);
    uint8_t *d_on = (uint8_t *)malloc(n * esz);
    uint32_t *c_sw = (uint32_t *)malloc(n * 4);
    uint32_t *c_hw = (uint32_t *)malloc(n * 4);
    uint8_t *mask = (uint8_t *)malloc((n + 7) / 8);
    uint8_t *ones = (uint8_t *)malloc((n + 7) / 8);
    cft_program *ps = NULL, *ph = NULL;
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    cft_status st;
    size_t masked_lanes = 0;

    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    if (cft_get_caps(hw, &hc) != CFT_OK)
        memset(&hc, 0, sizeof hc);
    if (!(hc.seq_features & CFT_SEQ_FEAT_LANE_MASK)) {
        not_here(NH_OTHER, "COMPARED", "  seq lane mask",
                 "this device does not publish CFT_SEQ_FEAT_LANE_MASK");
        goto out;
    }
    if (!a || !b || !d_sw || !d_hw || !d_pl || !d_on || !c_sw || !c_hw ||
        !mask || !ones) {
        printf("  FAIL seq lane mask: out of memory\n");
        failures++;
        goto out;
    }

    rs = 0x17A7 + (uint32_t)fmt;
    fill(a, n, esz);
    fill(b, n, esz);
    /* Every third lane masked, derived here and read back the same
     * way below - never a typed list of lanes. */
    memset(mask, 0, (n + 7) / 8);
    memset(ones, 0xFF, (n + 7) / 8);
    for (i = 0; i < n; i++) {
        if (i % 3 == 0)
            masked_lanes++;
        else
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
    }

    /* r3 = r0 + r1. ADD reads ra and rc, so both input streams
     * are read and a lane that ran when it should not have shows
     * in the deposits; rb is r3, a register at or above three, so
     * no stream is loaded for a field the opcode does not read
     * (P1, 2026-09-15). */
    ins[0] = seq_alu(CFT_ADD, 3, 0, 3, 1, CFT_RNE, 0, 0);
    ins[1] = seq_ctrl(3, 3, 0);                          /* DEPOSIT r3 */
    ins[2] = seq_ctrl(0, 0, 0);                          /* HALT */
    bytes = seq_image(img, fmt, ins, 3, NULL, 0, 1);

    st = cft_program_load(sw, img, bytes, &ps);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask: the software backend refused the "
               "image (%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }
    st = cft_program_load(hw, img, bytes, &ph);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask: the device refused the image "
               "(%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }

#define MASK_RUN(prog_, dst_, cnt_, msk_)                              \
    do {                                                               \
        memset(&A, 0, sizeof A);                                       \
        A.struct_size = sizeof A;                                      \
        A.a = a; A.b = b; A.c = b;                                     \
        A.n = n;                                                       \
        A.deposits = (dst_);                                           \
        A.counts = (cnt_);                                             \
        A.flags_out = &fl;                                             \
        A.bus_out = &bus;                                              \
        A.lane_mask = (msk_);                                          \
        A.lane_mask_bytes = (msk_) ? (n + 7) / 8 : 0;                  \
        memset((dst_), 0x5a, n * esz);                                 \
        memset((cnt_), 0x5a, n * 4);                                   \
        st = cft_program_run_ex((prog_), &A);                          \
    } while (0)

    /* 1. the masked run, software against the device. */
    MASK_RUN(ps, d_sw, c_sw, mask);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask: the software backend refused the "
               "run (%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    MASK_RUN(ph, d_hw, c_hw, mask);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask: the device refused the run "
               "(%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    checks++;
    if (memcmp(d_sw, d_hw, n * esz) != 0 ||
        memcmp(c_sw, c_hw, n * 4) != 0) {
        printf("  FAIL seq lane mask: the device and the software "
               "backend differ under a mask\n");
        failures++;
    }

    /* 2. a masked lane's bytes are the caller's, on the DEVICE. */
    checks++;
    for (i = 0; i < n; i++) {
        int kept = (mask[i >> 3] >> (i & 7u)) & 1;
        const uint8_t *slot = d_hw + i * esz;
        size_t k;
        int patterned = 1;
        for (k = 0; k < esz; k++)
            if (slot[k] != 0x5a)
                patterned = 0;
        if (!kept && (!patterned || c_hw[i] != 0x5a5a5a5au)) {
            printf("  FAIL seq lane mask: lane %lu is masked and its "
                   "deposit slot or count was written\n",
                   (unsigned long)i);
            failures++;
            break;
        }
        if (kept && patterned) {
            printf("  FAIL seq lane mask: lane %lu is NOT masked and "
                   "its deposit slot still holds the pattern\n",
                   (unsigned long)i);
            failures++;
            break;
        }
    }

    /* 3. the control: all ones is the unmasked run, and the mask with
     *    holes above is not. */
    MASK_RUN(ph, d_pl, c_hw, NULL);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask: the dense run was refused (%s)\n",
               cft_strerror(st));
        failures++;
        goto out;
    }
    MASK_RUN(ph, d_on, c_hw, ones);
    checks++;
    if (st != CFT_OK || memcmp(d_pl, d_on, n * esz) != 0) {
        printf("  FAIL seq lane mask: an all-ones mask is not the "
               "unmasked run on this device\n");
        failures++;
    }
    checks++;
    if (masked_lanes && memcmp(d_pl, d_hw, n * esz) == 0) {
        printf("  FAIL seq lane mask: a mask with %lu holes gave the "
               "unmasked run's bits, so the control above could not "
               "have failed - the mask may be being ignored\n",
               (unsigned long)masked_lanes);
        failures++;
    }
#undef MASK_RUN

    printf("  seq lane mask: %lu lanes, %lu of them masked, device == "
           "software, masked lanes untouched, all-ones == dense and "
           "holed != dense\n",
           (unsigned long)n, (unsigned long)masked_lanes);
out:
    cft_program_free(ps);
    cft_program_free(ph);
    free(a); free(b); free(d_sw); free(d_hw); free(d_pl); free(d_on);
    free(c_sw); free(c_hw); free(mask); free(ones);
}

/* R17 on the scratch-out block. HOSTAPI.md's first mask bullet names
 * three things a masked lane does not write - its deposit slots, its
 * count and its scratch-out slots - and check_masked above covers two.
 * The third had no leg until the card day of 2026-09-15 found the
 * deposit window's DEVICE copy holding the previous run's output under
 * a mask (the tile strobes a masked lane off, so what its slot "keeps"
 * is whatever the device copy held; the library now stages the
 * caller's bytes first). The scratch-out block is staged on the same
 * terms, and this is the leg that says so: one STL of `a` into the one
 * scratch-out slot, every third lane masked, the block pre-filled with
 * a pattern on both backends - the device must agree with the software
 * backend byte for byte, a masked lane's slot must hold the pattern
 * and a kept lane's must hold its `a`. */
static void check_masked_scratch_out(cft_device *sw, cft_device *hw,
                                     cft_format fmt, size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t img[256];
    uint64_t ins[2];
    size_t bytes, i;
    cft_caps hc;
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *so_sw = (uint8_t *)malloc(n * esz);
    uint8_t *so_hw = (uint8_t *)malloc(n * esz);
    uint32_t *c_sw = (uint32_t *)malloc(n * 4);
    uint32_t *c_hw = (uint32_t *)malloc(n * 4);
    uint8_t *mask = (uint8_t *)malloc((n + 7) / 8);
    cft_program *ps = NULL, *ph = NULL;
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    cft_status st;
    size_t masked_lanes = 0;

    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    if (cft_get_caps(hw, &hc) != CFT_OK)
        memset(&hc, 0, sizeof hc);
    if (!(hc.seq_features & CFT_SEQ_FEAT_LANE_MASK) ||
        !(hc.seq_features & CFT_SEQ_FEAT_SCRATCH_IO)) {
        not_here(NH_OTHER, "COMPARED", "  seq lane mask, scratch-out",
                 "this device does not publish %s",
                 (hc.seq_features & CFT_SEQ_FEAT_LANE_MASK)
                     ? "CFT_SEQ_FEAT_SCRATCH_IO" : "CFT_SEQ_FEAT_LANE_MASK");
        goto out;
    }
    if (!a || !so_sw || !so_hw || !c_sw || !c_hw || !mask) {
        printf("  FAIL seq lane mask, scratch-out: out of memory\n");
        failures++;
        goto out;
    }

    rs = 0x5C4A + (uint32_t)fmt;
    fill(a, n, esz);
    memset(mask, 0, (n + 7) / 8);
    for (i = 0; i < n; i++) {
        if (i % 3 == 0)
            masked_lanes++;
        else
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
    }

    /* STL slot 0 := r0 (the a stream); HALT. No deposit at all -
     * max_deposits is zero, which is a legal program - so the only
     * bytes this run writes are the scratch-out block and the counts. */
    ins[0] = seq_stl(0, 0);
    ins[1] = seq_ctrl(0, 0, 0);
    bytes = seq_image_scratch(img, fmt, ins, 2, NULL, 0, 0,
                              CFT_PROG_FLAG_SCRATCH_IO, 0, 1);

    st = cft_program_load(sw, img, bytes, &ps);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask, scratch-out: the software backend "
               "refused the image (%s: %s)\n", cft_strerror(st),
               cft_last_error());
        failures++;
        goto out;
    }
    st = cft_program_load(hw, img, bytes, &ph);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask, scratch-out: the device refused the "
               "image (%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }

#define SO_RUN(prog_, so_, cnt_)                                       \
    do {                                                               \
        memset(&A, 0, sizeof A);                                       \
        A.struct_size = sizeof A;                                      \
        A.a = a; A.b = a; A.c = a;                                     \
        A.n = n;                                                       \
        A.counts = (cnt_);                                             \
        A.scratch_out = (so_);                                         \
        A.scratch_out_bytes = n * esz;                                 \
        A.flags_out = &fl;                                             \
        A.bus_out = &bus;                                              \
        A.lane_mask = mask;                                            \
        A.lane_mask_bytes = (n + 7) / 8;                               \
        memset((so_), 0xA5, n * esz);                                  \
        memset((cnt_), 0x5a, n * 4);                                   \
        st = cft_program_run_ex((prog_), &A);                          \
    } while (0)

    SO_RUN(ps, so_sw, c_sw);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask, scratch-out: the software backend "
               "refused the run (%s: %s)\n", cft_strerror(st),
               cft_last_error());
        failures++;
        goto out;
    }
    SO_RUN(ph, so_hw, c_hw);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask, scratch-out: the device refused the "
               "run (%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
#undef SO_RUN
    checks++;
    if (memcmp(so_sw, so_hw, n * esz) != 0 || memcmp(c_sw, c_hw, n * 4) != 0) {
        printf("  FAIL seq lane mask, scratch-out: the device and the "
               "software backend differ under a mask\n");
        failures++;
    }
    checks++;
    for (i = 0; i < n; i++) {
        int kept = (mask[i >> 3] >> (i & 7u)) & 1;
        const uint8_t *slot = so_hw + i * esz;
        size_t k;
        int patterned = 1;
        for (k = 0; k < esz; k++)
            if (slot[k] != 0xA5)
                patterned = 0;
        if (!kept && (!patterned || c_hw[i] != 0x5a5a5a5au)) {
            printf("  FAIL seq lane mask, scratch-out: lane %lu is masked "
                   "and its scratch-out slot or count was written on the "
                   "device\n", (unsigned long)i);
            failures++;
            break;
        }
        if (kept && (memcmp(slot, a + i * esz, esz) != 0 || c_hw[i] != 0)) {
            printf("  FAIL seq lane mask, scratch-out: lane %lu is NOT "
                   "masked and its scratch-out slot is not its own store "
                   "(or its count is not zero)\n", (unsigned long)i);
            failures++;
            break;
        }
    }
    printf("  seq lane mask, scratch-out: %lu lanes, %lu of them masked, "
           "device == software, masked slots and counts untouched, kept "
           "lanes hold their own store\n",
           (unsigned long)n, (unsigned long)masked_lanes);
out:
    cft_program_free(ps);
    cft_program_free(ph);
    free(a); free(so_sw); free(so_hw); free(c_sw); free(c_hw); free(mask);
}

/* The indexed elementwise call on a device that does not publish
 * CFT_SEQ_FEAT_INDEXED: refused by name, before any run. This is the
 * round-2 library against an older image (the seq6 pair, VERSION 0x900,
 * on the card on 2026-09-15), where the composed route has no tile
 * mechanism to compose over, and the contract is the refusal itself - a
 * caller must never pay for a gather believing it fast. On a device with
 * no sequencer at all the sentence names the capacities instead, in the
 * order cft_run_ex fires them; either is the refusal by name. */
static void check_indexed_elem_absent(cft_device *hw, cft_format fmt,
                                      size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *d = (uint8_t *)malloc(n * esz);
    uint32_t *tab = (uint32_t *)malloc(n * 4);
    cft_elem_args E;
    cft_status st;
    size_t i;

    if (!a || !b || !d || !tab) {
        CHECK(0, "idx elem absent %s: out of memory", cft_format_name(fmt));
        goto out;
    }
    fill(a, n, esz);
    fill(b, n, esz);
    for (i = 0; i < n; i++)
        tab[i] = (uint32_t)i;
    memset(&E, 0, sizeof E);
    E.struct_size = sizeof E;
    E.a = a; E.b = b; E.c = b; E.d = d; E.n = n;
    E.idx_a = tab; E.idx_a_src = n;
    st = cft_run_ex(hw, CFT_FMA, fmt, CFT_RNE, &E);
    CHECK(st == CFT_ERR_UNSUPPORTED &&
          (strstr(cft_last_error(), "CFT_SEQ_FEAT_INDEXED") != NULL ||
           strstr(cft_last_error(), "sequencer") != NULL),
          "idx elem %s: a device without CAPS2[9] must refuse an indexed "
          "elementwise run by name, got %s (%s)", cft_format_name(fmt),
          cft_strerror(st), cft_last_error());
    not_here(NH_OTHER, "COMPARED", "  idx elem",
             "this device does not publish CFT_SEQ_FEAT_INDEXED (the "
             "refusal by name is scored above)");
out:
    free(a); free(b); free(d); free(tab);
}

/* The seam of round 2's wave 2 on the host side (docs/ROUND2.md, "What
 * the lead keeps"): a program run that is BOTH indexed (R16: stream a
 * read through a table into a source shorter than n, with sentinels)
 * and masked (R17: every third lane). P2 built the client-side gather
 * and P3 the compaction, each measured alone; through remote_check's
 * device-test stage this leg is where the two meet on a remote handle,
 * and on a card it is where the gather states and the mask fetch share
 * one run. The device must match the software backend bit for bit,
 * the masked lanes' slots must keep the pattern on both, and the
 * all-ones mask over the same table must equal the unmasked gathered
 * run. Gated on both feature bits; named NOT COMPARED otherwise. */
static void check_indexed_masked(cft_device *sw, cft_device *hw,
                                 cft_format fmt, size_t n)
{
    const size_t esz = cft_format_size(fmt);
    const size_t src_n = (n / 3) + 1;               /* deliberately short */
    uint8_t img[256];
    uint64_t ins[3];
    size_t bytes, i;
    cft_caps hc;
    uint8_t *src = (uint8_t *)malloc(src_n * esz);
    uint8_t *b = (uint8_t *)malloc(n * esz);
    uint8_t *d_sw = (uint8_t *)malloc(n * esz);
    uint8_t *d_hw = (uint8_t *)malloc(n * esz);
    uint8_t *d_on = (uint8_t *)malloc(n * esz);
    uint8_t *d_no = (uint8_t *)malloc(n * esz);
    uint32_t *c_sw = (uint32_t *)malloc(n * 4);
    uint32_t *c_hw = (uint32_t *)malloc(n * 4);
    uint32_t *tab = (uint32_t *)malloc(n * 4);
    uint8_t *mask = (uint8_t *)malloc((n + 7) / 8);
    uint8_t *ones = (uint8_t *)malloc((n + 7) / 8);
    cft_program *ps = NULL, *ph = NULL;
    cft_run_args A;
    uint32_t fl_sw = 0, fl_hw = 0, bus = 0;
    cft_status st;
    size_t masked_lanes = 0, sentinels = 0;

    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    if (cft_get_caps(hw, &hc) != CFT_OK)
        memset(&hc, 0, sizeof hc);
    if (!(hc.seq_features & CFT_SEQ_FEAT_LANE_MASK) ||
        !(hc.seq_features & CFT_SEQ_FEAT_INDEXED)) {
        not_here(NH_OTHER, "COMPARED", "  seq indexed and masked",
                 "this device does not publish both CFT_SEQ_FEAT_INDEXED "
                 "and CFT_SEQ_FEAT_LANE_MASK");
        goto out;
    }
    if (!src || !b || !d_sw || !d_hw || !d_on || !d_no || !c_sw || !c_hw ||
        !tab || !mask || !ones || n < 4) {
        printf("  FAIL seq indexed and masked: out of memory\n");
        failures++;
        goto out;
    }

    rs = 0x1D17 + (uint32_t)fmt;
    fill(src, src_n, esz);
    fill(b, n, esz);
    memset(mask, 0, (n + 7) / 8);
    memset(ones, 0xFF, (n + 7) / 8);
    for (i = 0; i < n; i++) {
        /* every third lane masked; every fifth entry a sentinel; the
         * rest a permutation-ish walk of the short source - all derived
         * here and never a typed list */
        if (i % 3 == 0)
            masked_lanes++;
        else
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
        if (i % 5 == 0) {
            tab[i] = CFT_IDX_NONE;
            sentinels++;
        } else {
            tab[i] = (uint32_t)((i * 7 + 1) % src_n);
        }
    }

    /* r3 = r0 + r1: ADD reads ra and rc, so the gathered stream a and
     * the dense stream b both reach the deposit; rb is r3 (no stream
     * loaded for a field the opcode does not read). */
    ins[0] = seq_alu(CFT_ADD, 3, 0, 3, 1, CFT_RNE, 0, 0);
    ins[1] = seq_ctrl(3, 3, 0);                          /* DEPOSIT r3 */
    ins[2] = seq_ctrl(0, 0, 0);                          /* HALT */
    bytes = seq_image(img, fmt, ins, 3, NULL, 0, 1);

    st = cft_program_load(sw, img, bytes, &ps);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed and masked: the software backend "
               "refused the image (%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }
    st = cft_program_load(hw, img, bytes, &ph);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed and masked: the device refused the "
               "image (%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }

#define IXMK_RUN(prog_, dst_, cnt_, fl_, msk_)                          \
    do {                                                                \
        memset(&A, 0, sizeof A);                                        \
        A.struct_size = sizeof A;                                       \
        A.a = src; A.b = b; A.c = b;                                    \
        A.n = n;                                                        \
        A.idx_a = tab; A.idx_a_src = src_n;                             \
        A.deposits = (dst_);                                            \
        A.counts = (cnt_);                                              \
        A.flags_out = (fl_);                                            \
        A.bus_out = &bus;                                               \
        A.lane_mask = (msk_);                                           \
        A.lane_mask_bytes = (msk_) ? (n + 7) / 8 : 0;                   \
        memset((dst_), 0x5a, n * esz);                                  \
        memset((cnt_), 0x5a, n * 4);                                    \
        st = cft_program_run_ex((prog_), &A);                           \
    } while (0)

    /* 1. indexed AND masked, software against the device */
    IXMK_RUN(ps, d_sw, c_sw, &fl_sw, mask);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed and masked: the software backend "
               "refused the run (%s: %s)\n", cft_strerror(st),
               cft_last_error());
        failures++;
        goto out;
    }
    IXMK_RUN(ph, d_hw, c_hw, &fl_hw, mask);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed and masked: the device refused the "
               "run (%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    checks++;
    if (memcmp(d_sw, d_hw, n * esz) != 0 || memcmp(c_sw, c_hw, n * 4) != 0 ||
        fl_sw != fl_hw) {
        printf("  FAIL seq indexed and masked: the device and the "
               "software backend differ (flags %#x against %#x)\n",
               (unsigned)fl_hw, (unsigned)fl_sw);
        failures++;
        goto out;
    }
    /* 2. a masked lane's slots hold the pattern on BOTH backends, and
     *    a lane the table sends to a sentinel still deposits (+0 plus
     *    b), so the two mechanisms are told apart lane by lane */
    checks++;
    for (i = 0; i < n; i++) {
        size_t k;
        int untouched = 1;
        for (k = 0; k < esz; k++)
            if (d_hw[i * esz + k] != 0x5a)
                untouched = 0;
        if ((i % 3 == 0) != untouched || (c_hw[i] == 0x5a5a5a5au) != (i % 3 == 0)) {
            printf("  FAIL seq indexed and masked: lane %lu is %s and its "
                   "slot was %s\n", (unsigned long)i,
                   (i % 3 == 0) ? "masked" : "active",
                   untouched ? "left alone" : "written");
            failures++;
            goto out;
        }
    }
    /* 3. all ones over the same table equals the unmasked gathered run,
     *    both on the device */
    IXMK_RUN(ph, d_on, c_hw, &fl_hw, ones);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq indexed and masked: the all-ones run was "
               "refused (%s)\n", cft_strerror(st));
        failures++;
        goto out;
    }
    IXMK_RUN(ph, d_no, c_sw, &fl_sw, (const uint8_t *)NULL);
    checks++;
    if (st != CFT_OK || memcmp(d_on, d_no, n * esz) != 0 ||
        memcmp(c_hw, c_sw, n * 4) != 0 || fl_hw != fl_sw) {
        printf("  FAIL seq indexed and masked: an all-ones mask over a "
               "table is not the unmasked gathered run\n");
        failures++;
        goto out;
    }
#undef IXMK_RUN
    printf("  seq indexed and masked: %lu lanes, %lu masked, a table of "
           "%lu sentinels into a %lu-element source, device == software, "
           "masked lanes untouched, all-ones == unmasked\n",
           (unsigned long)n, (unsigned long)masked_lanes,
           (unsigned long)sentinels, (unsigned long)src_n);
out:
    cft_program_free(ps);
    cft_program_free(ph);
    free(src); free(b); free(d_sw); free(d_hw); free(d_on); free(d_no);
    free(c_sw); free(c_hw); free(tab); free(mask); free(ones);
}

/* A program run at the largest lane count one PAGE of lane-mask bits
 * holds, and at one lane past it - with no mask at all.
 *
 * Every other sequencer leg in this file runs at most 200 lanes (see
 * `nseq` in main), which is why this shape had never been run: a
 * backend that binds the tile's mask argument on every launch sized
 * that buffer at one beat when the caller gave no mask and then filled
 * a bit for EVERY lane, so past 32,768 lanes - 4,096 bytes of bits -
 * the fill ran off the end of the mapping. The deposits came back
 * right, because the tile never reads a mask whose MODE bit is clear,
 * and the host heap did not (atlas-engine's card day, 2026-09-17, which
 * met it at 65,536 lanes and bisected it to this boundary). So the
 * deposits are checked here and they are not the point: the point is
 * that the run RETURNS, at the boundary and one past it, and that a
 * sizing mistake is a named failure of the run rather than a corrupted
 * heap - which stage_mask's own check now makes it.
 *
 * The expectation is absolute, not the software backend's: the program
 * deposits stream a, so the window must be stream a.
 *
 * ONCE A DEVICE, at the first format the sequencer legs reach: a mask
 * bit is a lane at every precision, so the boundary does not move with
 * the format and four runs would say what one does. And NOT under
 * hardware emulation, by name: 65,537 lanes of xsim is most of an
 * hour, the staging code is the same code on a card, and
 * hw/run-device-test.sh exports the variable this reads. */
static void check_program_past_a_page(cft_device *dev, cft_format fmt)
{
    static const size_t lanes[] = {32768u, 32769u};
    static int done;
    const size_t esz = cft_format_size(fmt);
    uint8_t img[64];
    uint64_t ins[2];
    cft_program *prog = NULL;
    size_t bytes, k;

    if (done)
        return;
    done = 1;
    if (getenv("XCL_EMULATION_MODE")) {
        not_here(NH_OTHER, "RUN",
                 "    a program run past one page of mask bits",
                 "under emulation (XCL_EMULATION_MODE is set); a card and "
                 "the software backend run it");
        return;
    }
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_ctrl(0, 0, 0);                  /* halt */
    bytes = seq_image(img, fmt, ins, 2, NULL, 0, 1);
    checks++;
    if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
        printf("  FAIL seq lanes: the one-deposit image did not load: %s\n",
               cft_last_error());
        failures++;
        return;
    }
    for (k = 0; k < sizeof lanes / sizeof lanes[0]; k++) {
        const size_t n = lanes[k];
        uint8_t *a = (uint8_t *)malloc(n * esz);
        uint8_t *dep = (uint8_t *)malloc(n * esz);
        uint32_t *cnt = (uint32_t *)malloc(n * 4);
        uint32_t fl = 0xFFu, bus = 0xFFFFFFFFu;
        size_t i;
        cft_status st;

        checks++;
        if (!a || !dep || !cnt) {
            printf("  FAIL seq lanes: out of memory at %lu lanes\n",
                   (unsigned long)n);
            failures++;
            free(a); free(dep); free(cnt);
            continue;
        }
        fill_finite(a, fmt, n);
        memset(dep, 0x5a, n * esz);
        st = cft_program_run(prog, a, NULL, NULL, dep, cnt, n, &fl, &bus);
        if (st != CFT_OK) {
            printf("  FAIL seq lanes: a program run of %lu lanes with no "
                   "mask: %s (%s)\n", (unsigned long)n, cft_strerror(st),
                   cft_last_error());
            failures++;
        } else {
            int bad = memcmp(dep, a, n * esz) != 0;
            for (i = 0; i < n && !bad; i++)
                if (cnt[i] != 1)
                    bad = 1;
            if (bad || fl != 0 || bus != 0) {
                printf("  FAIL seq lanes: %lu lanes, the deposits must be "
                       "stream a with one a lane, flags and STATUS clean "
                       "(flags %#x, STATUS %#x)\n", (unsigned long)n, fl,
                       bus);
                failures++;
            }
        }
        free(a); free(dep); free(cnt);
    }
    printf("    a program run of 32,768 lanes and of 32,769, no mask: one "
           "page of mask bits and one bit past it\n");
    cft_program_free(prog);
}

/* The capacity boundaries a program run's cut puts on each TILE
 * (2026-09-25).
 *
 * check_program_past_a_page holds one boundary for a whole run. Since
 * the scheduler cuts a program's lanes across the tiles
 * (backend_xrt.cpp, run_job), every per-lane buffer is a tile's slice,
 * so a boundary is a tile's and a quad reaches it at four times the
 * lanes - the leg above now tests a quarter page there. What the round
 * of 2026-09-17 left owed (docs/ROADMAP.md's debts list: "a program leg
 * at every capacity boundary the backend has - a page of mask bits, a
 * page of counts, an HBM channel"), each on a tile's own slice:
 *
 *   - a page of counts: 1,024 lanes a tile (4,096 bytes of counts), and
 *     one beat past it;
 *   - a page of mask bits: 32,768 lanes a tile, and one beat past it,
 *     without a mask and with one (every third lane off);
 *   - an HBM channel: a deposit window one tile's 256 MB cannot hold is
 *     REFUSED BY NAME - out of memory, with the library's sentence, the
 *     heap intact - and a quarter of it runs right.
 *
 * The expectation is absolute: the program deposits stream a, so a kept
 * lane's first slot is a, its other slots +0 and its count 1, and a
 * masked lane's slots and count are what the caller put there (R17). ONCE
 * A DEVICE, at the first format the sequencer legs reach; not under
 * emulation. */
static int capacity_run(cft_program *prog, cft_format fmt, size_t n,
                        uint32_t maxdep, int masked, const char *what,
                        size_t per_tile)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *dep = (uint8_t *)malloc(n * maxdep * esz);
    uint32_t *cnt = (uint32_t *)malloc(n * 4);
    uint8_t *mask = masked ? (uint8_t *)calloc((n + 7) / 8, 1) : NULL;
    uint8_t zero[MAXE];
    uint32_t fl = 0xFFu, bus = 0xFFFFFFFFu;
    cft_run_args A;
    cft_status st;
    size_t i, bad = 0, first_bad = 0;
    int ok = 1;

    memset(zero, 0, sizeof zero);
    if (!a || !dep || !cnt || (masked && !mask)) {
        printf("  FAIL seq capacity: out of memory for %s at %lu lanes\n",
               what, (unsigned long)n);
        free(a); free(dep); free(cnt); free(mask);
        return 0;
    }
    fill_finite(a, fmt, n);
    memset(dep, 0x5a, n * maxdep * esz);
    for (i = 0; i < n; i++)
        cnt[i] = 0xA5A5A5A5u;
    if (masked)
        for (i = 0; i < n; i++)
            if (i % 3)
                mask[i / 8] |= (uint8_t)(1u << (i % 8));
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = a;
    A.n = n;
    A.deposits = dep;
    A.counts = cnt;
    A.flags_out = &fl;
    A.bus_out = &bus;
    A.lane_mask = mask;
    A.lane_mask_bytes = masked ? (n + 7) / 8 : 0;
    st = cft_program_run_ex(prog, &A);
    if (st != CFT_OK) {
        printf("  FAIL seq capacity: %s, %lu lanes (%lu a tile): %s (%s)\n",
               what, (unsigned long)n, (unsigned long)per_tile,
               cft_strerror(st), cft_last_error());
        ok = 0;
    } else {
        for (i = 0; i < n; i++) {
            const int kept = !masked || (i % 3);
            const uint8_t *slot = dep + i * maxdep * esz;
            uint32_t d;
            int lane_bad = 0;
            if (kept) {
                lane_bad = memcmp(slot, a + i * esz, esz) != 0 ||
                           cnt[i] != 1;
                for (d = 1; d < maxdep && !lane_bad; d++)
                    lane_bad = memcmp(slot + d * esz, zero, esz) != 0;
            } else {
                for (d = 0; d < maxdep * esz && !lane_bad; d++)
                    lane_bad = slot[d] != 0x5a;
                lane_bad |= cnt[i] != 0xA5A5A5A5u;
            }
            if (lane_bad && !bad++)
                first_bad = i;
        }
        if (bad || fl != 0 || (bus & ~0x30u) != 0) {
            printf("  FAIL seq capacity: %s, %lu lanes (%lu a tile): %lu "
                   "lanes wrong, the first %lu (%s); flags %#x, STATUS %#x\n",
                   what, (unsigned long)n, (unsigned long)per_tile,
                   (unsigned long)bad, (unsigned long)first_bad,
                   masked && !(first_bad % 3) ? "masked" : "kept", fl, bus);
            ok = 0;
        }
    }
    free(a); free(dep); free(cnt); free(mask);
    return ok;
}

static void check_program_capacity(cft_device *dev, cft_format fmt)
{
    static const struct {
        size_t per_tile;
        int masked;
        const char *what;
    } legs[] = {
        {1024, 0, "a page of counts"},
        {32768, 0, "a page of mask bits, no mask"},
        {32768, 1, "a page of mask bits, every third lane masked"},
    };
    static int done;
    const size_t esz = cft_format_size(fmt), epb = 32 / esz;
    uint8_t img[64];
    uint64_t ins[2];
    cft_program *prog = NULL, *big = NULL;
    cft_caps caps;
    size_t tiles, l, bytes;
    int passed = 0, ran = 0;

    if (done)
        return;
    done = 1;
    if (getenv("XCL_EMULATION_MODE")) {
        not_here(NH_OTHER, "RUN", "    a program at each tile's capacity "
                 "boundaries", "under emulation (XCL_EMULATION_MODE is "
                 "set); a card and the software backend run it");
        return;
    }
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    tiles = (cft_get_caps(dev, &caps) == CFT_OK && caps.tiles) ? caps.tiles
                                                               : 1;
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_ctrl(0, 0, 0);                  /* halt */
    bytes = seq_image(img, fmt, ins, 2, NULL, 0, 1);
    checks++;
    if (cft_program_load(dev, img, bytes, &prog) != CFT_OK) {
        printf("  FAIL seq capacity: the one-deposit image did not load: "
               "%s\n", cft_last_error());
        failures++;
        return;
    }
    for (l = 0; l < sizeof legs / sizeof legs[0]; l++) {
        size_t plus;
        for (plus = 0; plus <= epb; plus += epb) {
            const size_t n = tiles * legs[l].per_tile + plus;
            checks++;
            ran++;
            if (capacity_run(prog, fmt, n, 1, legs[l].masked, legs[l].what,
                             legs[l].per_tile + plus))
                passed++;
            else
                failures++;
        }
    }
    printf("    a program at each tile's boundaries, %lu tile%s: a page of "
           "counts and of mask bits, each exactly and one beat past, with "
           "and without a mask - %d of %d right\n", (unsigned long)tiles,
           tiles == 1 ? "" : "s", passed, ran);
    cft_program_free(prog);

    /* An HBM channel: a deposit window 16 MiB past one tile's 256 MiB
     * channel must be refused as out of memory, by name; 16 slots of 1M
     * lanes a tile (64 MiB, a quarter of the channel) must run right. The
     * slots are the device's own max_deposits (64 on the round-2 tiles),
     * never more: an image past that is refused at load, which is a
     * different refusal - the first card run of this leg (2026-09-25)
     * asked for 80 and got exactly that. The lanes are what overflows the
     * channel at those slots. Only where there is a channel: the software
     * backend has none. */
    if (strcmp(caps.backend, "xrt") != 0) {
        not_here(NH_OTHER, "TESTED", "    a program past one tile's HBM "
                 "channel", "this backend has no HBM channel to run past");
        return;
    }
    /* At whatever format first reaches this leg: the sizes below are the
     * element size's, and until verifier-V4 read it (2026-09-25) a run
     * whose first format was not fp32 skipped this half without a line. */
    {
        const size_t chan = (size_t)256 << 20;
        const uint32_t slots = caps.max_deposits && caps.max_deposits < 80u
                                   ? caps.max_deposits
                                   : 80u;
        const size_t per = chan / ((size_t)slots * esz) +
                           ((size_t)16 << 20) / ((size_t)slots * esz);
        const size_t n = tiles * per;
        cft_status st;
        uint8_t *a = (uint8_t *)malloc(n * esz);
        uint8_t *dep = (uint8_t *)malloc(n * slots * esz);
        uint32_t *cnt = (uint32_t *)malloc(n * 4);
        cft_run_args A;
        uint32_t fl = 0, bus = 0;

        checks++;
        bytes = seq_image(img, fmt, ins, 2, NULL, 0, slots);
        if (!a || !dep || !cnt ||
            cft_program_load(dev, img, bytes, &big) != CFT_OK) {
            printf("  FAIL seq capacity: could not set up the HBM leg at %lu "
                   "slots (%s)\n", (unsigned long)slots, cft_last_error());
            failures++;
        } else {
            fill_finite(a, fmt, n);
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a;
            A.n = n;
            A.deposits = dep;
            A.counts = cnt;
            A.flags_out = &fl;
            A.bus_out = &bus;
            st = cft_program_run_ex(big, &A);
            if (st == CFT_ERR_OUT_OF_MEMORY &&
                strstr(cft_last_error(), "device buffer allocation failed")) {
                printf("    a program past one tile's HBM channel (%lu lanes a "
                       "tile at %lu slots, %lu MiB of deposits each): refused "
                       "by name - %s\n", (unsigned long)per,
                       (unsigned long)slots,
                       (unsigned long)((per * slots * esz) >> 20),
                       cft_last_error());
            } else {
                printf("  FAIL seq capacity: a deposit window past one tile's "
                       "channel gave %s (%s), not a named out-of-memory "
                       "refusal\n", cft_strerror(st), cft_last_error());
                failures++;
            }
        }
        cft_program_free(big);
        big = NULL;
        free(a); free(dep); free(cnt);
    }
    {
        /* 64 MiB of deposits a tile at 16 slots: a quarter of a channel */
        const size_t per = ((size_t)64 << 20) / (16u * esz), n = tiles * per;
        checks++;
        bytes = seq_image(img, fmt, ins, 2, NULL, 0, 16);
        if (cft_program_load(dev, img, bytes, &big) != CFT_OK) {
            printf("  FAIL seq capacity: the 16-slot image did not load: %s\n",
                   cft_last_error());
            failures++;
        } else if (capacity_run(big, fmt, n, 16, 0,
                                "a quarter of one tile's HBM channel", per)) {
            printf("    a program at a quarter of one tile's HBM channel "
                   "(%lu lanes a tile, 64 MB of deposits each): right\n",
                   (unsigned long)per);
        } else {
            failures++;
        }
        cft_program_free(big);
    }
}

/* The resident-buffer helpers are defined with the -b legs further down;
 * the witness leg and the two after it use them too, so the struct lives here and the two
 * functions are declared. */
struct rbuf { cft_buffer *b; uint8_t *p; };
static int rbuf_alloc(cft_device *dev, struct rbuf *r, size_t bytes);
static void rbuf_free(struct rbuf *r);

/* The completion witness (backend_xrt.cpp, run_job, 2026-09-25): a tile
 * that is busy before a start, or still busy after XRT has reported its
 * run complete, is refused by name and nothing of the run is collected.
 * The defect it exists for - a run abandoned on a tile, after which
 * XRT's scheduler completes later runs on that tile early, in any
 * process, until the image is reloaded - cannot be planted from here
 * without poisoning the card for everyone after this process, so it is
 * a card-day leg (docs/CARDDAY.md). What this holds on every XRT device
 * is the refusal itself, through CFT_XRT_WITNESS's planted busy reading:
 * the status and the sentence, the caller's output untouched, and the
 * handle giving the unplanted run's bytes straight after - for an
 * elementwise run and a program, which reach run_job from two entry
 * points. A malformed value is refused by name. ONCE A DEVICE. */
static void check_completion_witness(cft_device *hw, cft_format fmt)
{
    static int done;
    static const struct {
        const char *plant, *words;
    } legs[] = {
        {"busy-before", "is running work this process did not start"},
        {"busy-after", "was still running it"},
    };
    const size_t esz = cft_format_size(fmt), n = 64;
    uint8_t *a = (uint8_t *)malloc(n * esz), *b = (uint8_t *)malloc(n * esz);
    uint8_t *c = (uint8_t *)calloc(n, esz), *base = (uint8_t *)malloc(n * esz);
    uint8_t *got = (uint8_t *)malloc(n * esz);
    uint8_t *dbase = (uint8_t *)malloc(n * esz), *dgot = (uint8_t *)malloc(n * esz);
    uint32_t cnt[64], f = 0, bus = 0;
    uint8_t img[64];
    uint64_t ins[2];
    cft_program *prog = NULL;
    cft_run_args A;
    cft_caps caps;
    cft_status st;
    size_t l, i;
    int right = 0, asked = 0, untouched;

    if (done)
        goto out;
    done = 1;
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(hw, &caps) != CFT_OK || strcmp(caps.backend, "xrt") != 0) {
        not_here(NH_OTHER, "TESTED", "    the completion witness's refusals",
                 "the %s backend has no tile whose CTRL it reads",
                 caps.backend[0] ? caps.backend : "this");
        goto out;
    }
    if (!a || !b || !c || !base || !got || !dbase || !dgot) {
        printf("  FAIL: out of memory for the completion-witness leg\n");
        failures++;
        goto out;
    }
    rs = 0x77175e55u;
    fill(a, n, esz);
    fill(b, n, esz);
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_ctrl(0, 0, 0);                  /* halt */
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = a;
    A.n = n;
    A.counts = cnt;
    A.flags_out = &f;
    A.bus_out = &bus;

    /* the unplanted runs: what the handle must still give afterwards */
    st = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a, b, c, base, n, &f, &bus);
    CHECK(st == CFT_OK, "the witness leg's unplanted ADD (%s): %s (%s)",
          cft_format_name(fmt), cft_strerror(st), cft_last_error());
    st = cft_program_load(hw, img, seq_image(img, fmt, ins, 2, NULL, 0, 1),
                          &prog);
    CHECK(st == CFT_OK, "the witness leg's one-deposit image (%s): %s",
          cft_format_name(fmt), cft_last_error());
    if (st != CFT_OK)
        goto out;
    A.deposits = dbase;
    st = cft_program_run_ex(prog, &A);
    CHECK(st == CFT_OK, "the witness leg's unplanted program (%s): %s (%s)",
          cft_format_name(fmt), cft_strerror(st), cft_last_error());

    /* A wave refused BEFORE it is staged (2026-09-26, verifier-V8):
     * a resident input the refused run names must be bound nowhere -
     * staging would have filled its copy on the busy tile. */
    {
        struct rbuf R;
        cft_buffer_info bi;
        int unbound = 0;
        if (rbuf_alloc(hw, &R, n * esz)) {
            memcpy(R.p, a, n * esz);
            if (cft_buffer_to_device(R.b) == CFT_OK) {
                put_env("CFT_XRT_WITNESS", "busy-before");
                st = cft_run(hw, CFT_ADD, fmt, CFT_RNE, R.p, b, c, got, n, &f,
                             &bus);
                put_env("CFT_XRT_WITNESS", NULL);
                memset(&bi, 0, sizeof bi);
                bi.struct_size = sizeof bi;
                unbound = st != CFT_OK &&
                          cft_buffer_get_info(R.b, &bi) == CFT_OK &&
                          bi.staged_binds == 0 && bi.resident_binds == 0;
            }
            rbuf_free(&R);
        }
        asked++;
        CHECK(unbound, "CFT_XRT_WITNESS=busy-before (%s): the refused wave "
              "bound a resident input - it must be refused before it is "
              "staged", cft_format_name(fmt));
        right += unbound;
    }
    for (l = 0; l < sizeof legs / sizeof legs[0]; l++) {
        /* an elementwise run, refused */
#ifndef _WIN32
        double t0, took;
#endif
        memset(got, 0x5a, n * esz);
        put_env("CFT_XRT_WITNESS", legs[l].plant);
#ifndef _WIN32
        t0 = wall_ms();
#endif
        st = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a, b, c, got, n, &f, &bus);
#ifndef _WIN32
        took = wall_ms() - t0;
#endif
        put_env("CFT_XRT_WITNESS", NULL);
#ifndef _WIN32
        /* busy-after's plant holds the tile busy for 50 ms: a witness
         * that refuses without waiting for it to go idle returns sooner,
         * and one that waited must say the tile has since finished, not
         * that the handle is (verifier-V7: a one-read plant let the
         * no-wait mutant through). */
        if (l == 1) {
            asked++;
            CHECK(took >= 50.0 && strstr(cft_last_error(), "has since finished"),
                  "CFT_XRT_WITNESS=busy-after (%s): refused in %.1f ms (%s) - it "
                  "must wait until the tile is idle, 50 ms, and say so",
                  cft_format_name(fmt), took, cft_last_error());
            right += took >= 50.0 &&
                     strstr(cft_last_error(), "has since finished") != NULL;
        }
#endif
        for (untouched = 1, i = 0; i < n * esz; i++)
            untouched &= got[i] == 0x5a;
        asked++;
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), legs[l].words),
              "CFT_XRT_WITNESS=%s, an ADD (%s): %s (%s) - a busy tile must be "
              "refused by name", legs[l].plant, cft_format_name(fmt),
              cft_strerror(st), cft_last_error());
        CHECK(untouched, "CFT_XRT_WITNESS=%s: a refused ADD wrote the caller's "
              "output (%s)", legs[l].plant, cft_format_name(fmt));
        right += st == CFT_ERR_INTERNAL &&
                 strstr(cft_last_error(), legs[l].words) && untouched;
        /* ...and the handle still gives the unplanted bytes */
        st = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a, b, c, got, n, &f, &bus);
        asked++;
        CHECK(st == CFT_OK && !memcmp(got, base, n * esz),
              "the ADD after the %s refusal (%s): %s (%s)%s", legs[l].plant,
              cft_format_name(fmt), cft_strerror(st), cft_last_error(),
              st == CFT_OK ? " - bytes differ from the unplanted run" : "");
        right += st == CFT_OK && !memcmp(got, base, n * esz);

        /* a program, refused */
        memset(dgot, 0x5a, n * esz);
        A.deposits = dgot;
        put_env("CFT_XRT_WITNESS", legs[l].plant);
        st = cft_program_run_ex(prog, &A);
        put_env("CFT_XRT_WITNESS", NULL);
        for (untouched = 1, i = 0; i < n * esz; i++)
            untouched &= dgot[i] == 0x5a;
        asked++;
        CHECK(st == CFT_ERR_INTERNAL && strstr(cft_last_error(), legs[l].words)
                  && untouched,
              "CFT_XRT_WITNESS=%s, a program (%s): %s (%s)%s", legs[l].plant,
              cft_format_name(fmt), cft_strerror(st), cft_last_error(),
              untouched ? "" : " - and it wrote the caller's deposits");
        right += st == CFT_ERR_INTERNAL &&
                 strstr(cft_last_error(), legs[l].words) && untouched;
        st = cft_program_run_ex(prog, &A);
        asked++;
        CHECK(st == CFT_OK && !memcmp(dgot, dbase, n * esz),
              "the program after the %s refusal (%s): %s (%s)", legs[l].plant,
              cft_format_name(fmt), cft_strerror(st), cft_last_error());
        right += st == CFT_OK && !memcmp(dgot, dbase, n * esz);
    }

    /* an instrument that quietly read a typo as "off" would be a gate
     * that could not fail */
    put_env("CFT_XRT_WITNESS", "busy");
    st = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a, b, c, got, n, &f, &bus);
    put_env("CFT_XRT_WITNESS", NULL);
    asked++;
    CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
              strstr(cft_last_error(), "CFT_XRT_WITNESS"),
          "CFT_XRT_WITNESS=busy: %s (%s) - a malformed value must be refused "
          "by name", cft_strerror(st), cft_last_error());
    right += st == CFT_ERR_INVALID_ARGUMENT &&
             strstr(cft_last_error(), "CFT_XRT_WITNESS") != NULL;
    printf("    the completion witness (%s): a tile read as busy before a start "
           "and after a wait refused by name, nothing collected, the handle "
           "right straight after; a malformed instrument refused - %d of %d "
           "right\n", cft_format_name(fmt), right, asked);
out:
    cft_program_free(prog);
    free(a); free(b); free(c); free(base); free(got); free(dbase); free(dgot);
}

/* A lane mask on a program whose deposit window and scratch-out block
 * are RESIDENT (cft_alloc): a masked lane's slots must come back holding
 * what the caller put there (docs/HOSTAPI.md, R17), whatever the
 * device's copy held. Two shapes, each at every format:
 *   - fresh buffers, the caller's sentinels published, one masked run;
 *   - the same buffers after an UNMASKED run wrote every lane and was
 *     brought home, the caller's new sentinels published over it, then
 *     the masked run - the shape verifier-V4 found returning the
 *     unmasked run's deposit in every masked lane (2026-09-25), because
 *     an output copy was never refreshed before a run.
 * The program deposits a and stores it to scratch-out slot 0, so a kept
 * lane holds a in both and a count of 1, and a masked lane holds the
 * caller's bytes in both and the caller's count. On the software
 * backend the buffers are plain memory and this passes by construction,
 * which is what proves the harness; the device is the test. */
static void check_masked_resident(cft_device *hw, cft_format fmt)
{
    const size_t esz = cft_format_size(fmt), n = 257;
    uint8_t img[128];
    uint64_t ins[3];
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *mask = (uint8_t *)calloc((n + 7) / 8, 1);
    uint32_t cnt[257];
    struct rbuf dep, so;
    cft_program *prog = NULL;
    cft_run_args A;
    cft_caps hc;
    uint32_t fl = 0, bus = 0;
    cft_status st;
    size_t i, shape, wrong[2] = {0, 0};
    const uint8_t sd[2] = {0x5a, 0x3c}, ss[2] = {0xa5, 0xc3};

    dep.b = so.b = NULL;
    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    if (cft_get_caps(hw, &hc) != CFT_OK)
        memset(&hc, 0, sizeof hc);
    if (!(hc.seq_features & CFT_SEQ_FEAT_LANE_MASK) ||
        !(hc.seq_features & CFT_SEQ_FEAT_SCRATCH_IO)) {
        not_here(NH_OTHER, "TESTED", "  seq lane mask into resident outputs",
                 "this device does not publish %s",
                 (hc.seq_features & CFT_SEQ_FEAT_LANE_MASK)
                     ? "CFT_SEQ_FEAT_SCRATCH_IO" : "CFT_SEQ_FEAT_LANE_MASK");
        goto out;
    }
    if (!a || !mask || !rbuf_alloc(hw, &dep, n * esz) ||
        !rbuf_alloc(hw, &so, n * esz)) {
        printf("  FAIL seq lane mask into resident outputs: out of memory\n");
        failures++;
        goto out;
    }
    rs = 0x3A5C0000u + (uint32_t)fmt;
    fill(a, n, esz);
    for (i = 0; i < n; i++)
        if (i % 3)
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_stl(0, 0);                      /* scratch slot 0 := r0 */
    ins[2] = seq_ctrl(0, 0, 0);                  /* halt */
    st = cft_program_load(hw, img,
                          seq_image_scratch(img, fmt, ins, 3, NULL, 0, 1,
                                            CFT_PROG_FLAG_SCRATCH_IO, 0, 1),
                          &prog);
    checks++;
    if (st != CFT_OK) {
        printf("  FAIL seq lane mask into resident outputs: the image did "
               "not load (%s: %s)\n", cft_strerror(st), cft_last_error());
        failures++;
        goto out;
    }
    for (shape = 0; shape < 2; shape++) {
        if (shape == 1) {
            /* every lane written by an unmasked run, and brought home */
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a; A.n = n;
            A.deposits = dep.p;
            A.counts = cnt;
            A.scratch_out = so.p;
            A.scratch_out_bytes = n * esz;
            A.flags_out = &fl;
            A.bus_out = &bus;
            st = cft_program_run_ex(prog, &A);
            CHECK(st == CFT_OK && cft_buffer_from_device(dep.b) == CFT_OK &&
                      cft_buffer_from_device(so.b) == CFT_OK,
                  "seq lane mask into resident outputs (%s): the unmasked "
                  "run before the second shape: %s (%s)",
                  cft_format_name(fmt), cft_strerror(st), cft_last_error());
        }
        memset(dep.p, sd[shape], n * esz);
        memset(so.p, ss[shape], n * esz);
        CHECK(cft_buffer_to_device(dep.b) == CFT_OK &&
                  cft_buffer_to_device(so.b) == CFT_OK,
              "seq lane mask into resident outputs (%s): publishing the "
              "caller's sentinels", cft_format_name(fmt));
        for (i = 0; i < n; i++)
            cnt[i] = 0xA5A5A5A5u;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = a; A.n = n;
        A.deposits = dep.p;
        A.counts = cnt;
        A.scratch_out = so.p;
        A.scratch_out_bytes = n * esz;
        A.lane_mask = mask;
        A.lane_mask_bytes = (n + 7) / 8;
        A.flags_out = &fl;
        A.bus_out = &bus;
        st = cft_program_run_ex(prog, &A);
        checks++;
        if (st != CFT_OK || cft_buffer_from_device(dep.b) != CFT_OK ||
            cft_buffer_from_device(so.b) != CFT_OK) {
            printf("  FAIL seq lane mask into resident outputs (%s, %s): %s "
                   "(%s)\n", cft_format_name(fmt),
                   shape ? "after an unmasked run" : "fresh",
                   cft_strerror(st), cft_last_error());
            failures++;
            continue;
        }
        for (i = 0; i < n; i++) {
            const int kept = (i % 3) != 0;
            const uint8_t *d = dep.p + i * esz, *s = so.p + i * esz;
            size_t k;
            int lane_bad = 0;
            if (kept)
                lane_bad = memcmp(d, a + i * esz, esz) ||
                           memcmp(s, a + i * esz, esz) || cnt[i] != 1;
            else {
                for (k = 0; k < esz; k++)
                    lane_bad |= d[k] != sd[shape] || s[k] != ss[shape];
                lane_bad |= cnt[i] != 0xA5A5A5A5u;
            }
            if (lane_bad && wrong[shape]++ < 3)
                printf("  FAIL seq lane mask into resident outputs (%s, %s): "
                       "lane %lu (%s) is not what it should hold\n",
                       cft_format_name(fmt),
                       shape ? "after an unmasked run" : "fresh",
                       (unsigned long)i, kept ? "kept" : "masked");
        }
        checks++;
        if (wrong[shape])
            failures++;
    }
    if (!wrong[0] && !wrong[1])
        printf("    seq lane mask into resident outputs (%s): %lu lanes, a "
               "third masked, fresh and after an unmasked run - every masked "
               "lane the caller's, every kept lane the run's\n",
               cft_format_name(fmt), (unsigned long)n);
out:
    cft_program_free(prog);
    if (dep.b)
        rbuf_free(&dep);
    if (so.b)
        rbuf_free(&so);
    free(a);
    free(mask);
}

/* A run refused once its units ran leaves its resident outputs LOST
 * (backend_xrt.cpp, Buf::lost): the tile may have written part of a
 * window over bytes an earlier run left there, so reading the buffer
 * back, or using it as an input, is refused by name until the caller
 * publishes it again. Before 2026-09-25 the copy kept the earlier run's
 * dirty flag and cft_buffer_from_device returned the failed run's bytes
 * with CFT_OK (verifier-V4). Planted here with CFT_XRT_WITNESS=busy-after
 * - a refusal after the runs completed - over a window an earlier good
 * run left dirty. The planted run computes the same bytes as the good
 * one, so the leg holds the STATUS, not the bytes. XRT only; once a
 * device. */
static void check_lost_after_refusal(cft_device *hw, cft_format fmt)
{
    static int done;
    const size_t esz = cft_format_size(fmt), n = 64;
    uint8_t img[64];
    uint64_t ins[2];
    uint8_t *a = (uint8_t *)malloc(n * esz), *b = (uint8_t *)malloc(n * esz);
    uint8_t *out = (uint8_t *)malloc(n * esz);
    uint32_t cnt[64], fl = 0, bus = 0;
    struct rbuf dep;
    cft_program *prog = NULL;
    cft_run_args A;
    cft_caps caps;
    cft_status st, s_back, s_in, s_repub, s_after, s_back2;
    int right = 0;

    dep.b = NULL;
    if (done)
        goto out;
    done = 1;
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(hw, &caps) != CFT_OK || strcmp(caps.backend, "xrt")) {
        not_here(NH_OTHER, "TESTED", "    a resident output lost by a refused "
                 "run", "the %s backend has no tile to refuse a run on",
                 caps.backend[0] ? caps.backend : "this");
        goto out;
    }
    if (!a || !b || !out || !rbuf_alloc(hw, &dep, n * esz)) {
        printf("  FAIL: out of memory for the lost-output leg\n");
        failures++;
        goto out;
    }
    rs = 0x1057u;
    fill(a, n, esz);
    fill(b, n, esz);
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_ctrl(0, 0, 0);                  /* halt */
    st = cft_program_load(hw, img, seq_image(img, fmt, ins, 2, NULL, 0, 1),
                          &prog);
    CHECK(st == CFT_OK, "the lost-output leg's image (%s): %s",
          cft_format_name(fmt), cft_last_error());
    if (st != CFT_OK)
        goto out;
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = a; A.n = n;
    A.deposits = dep.p;
    A.counts = cnt;
    A.flags_out = &fl;
    A.bus_out = &bus;
    /* a good run leaves the window dirty on the device... */
    st = cft_program_run_ex(prog, &A);
    CHECK(st == CFT_OK, "the lost-output leg's good run (%s): %s (%s)",
          cft_format_name(fmt), cft_strerror(st), cft_last_error());
    /* ...and a run refused after its units ran writes the same window */
    put_env("CFT_XRT_WITNESS", "busy-after");
    st = cft_program_run_ex(prog, &A);
    put_env("CFT_XRT_WITNESS", NULL);
    CHECK(st == CFT_ERR_INTERNAL, "the lost-output leg's planted refusal "
          "(%s): %s (%s)", cft_format_name(fmt), cft_strerror(st),
          cft_last_error());
    /* A refusal of the library's own first - cft_run_ex's, for an indexed
     * run whose d is its own source - so a read-back that reached the
     * backend without clearing device.c's slot would be explained by THAT
     * sentence, as it was until 2026-09-27 (verifier-V9). */
    {
        cft_elem_args E;
        uint32_t t0[64];
        memset(t0, 0, sizeof t0);
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = out;
        E.d = out;
        E.n = n;
        E.idx_a = t0;
        E.idx_a_src = n;
        st = cft_run_ex(hw, CFT_ABS, fmt, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "overlaps") != NULL,
              "the lost-output leg's own-refusal step (%s): %s (%s)",
              cft_format_name(fmt), cft_strerror(st), cft_last_error());
    }
    s_back = cft_buffer_from_device(dep.b);
    CHECK(s_back != CFT_OK && strstr(cft_last_error(), "cft_buffer_to_device"),
          "a resident output written by a refused run was read back with %s "
          "(%s) - it must be refused by name until it is published again",
          cft_strerror(s_back), cft_last_error());
    s_in = cft_run(hw, CFT_ADD, fmt, CFT_RNE, dep.p, b, b, out, n, &fl, &bus);
    CHECK(s_in != CFT_OK && strstr(cft_last_error(), "cft_buffer_to_device"),
          "a resident buffer a refused run lost was used as an input with %s "
          "(%s) - it must be refused by name", cft_strerror(s_in),
          cft_last_error());
    /* ...and WRITING it: a run whose output it is, and an entry point
     * computed on the host reading or writing it, are refused by name
     * too; a lane mask read from it as well; and cft_buffer_get_info
     * says nothing about it is authoritative (verifier-V7: the write and
     * the mask were never tried here, and a mutant accepting them
     * passed; get_info said device_authority 1). */
    {
        cft_buffer_info bi;
        cft_status s_out, s_hin, s_hout, s_mask = CFT_ERR_INTERNAL;
        cft_status s_tab, s_scal = CFT_ERR_INTERNAL, s_dig, s_conf;
        const int indexed = (caps.seq_features & CFT_SEQ_FEAT_INDEXED) != 0;
        int info_ok;
        s_out = cft_run(hw, CFT_ADD, fmt, CFT_RNE, b, b, b, dep.p, n, &fl,
                        &bus);
        CHECK(s_out != CFT_OK && strstr(cft_last_error(),
                                        "cft_buffer_to_device"),
              "a run into a resident buffer a refused run lost: %s (%s) - "
              "it must be refused by name", cft_strerror(s_out),
              cft_last_error());
        s_hin = cft_exp(hw, fmt, CFT_RNE, dep.p, out, n, &fl);
        CHECK(s_hin != CFT_OK && strstr(cft_last_error(),
                                        "cft_buffer_to_device"),
              "cft_exp reading a lost resident buffer: %s (%s) - it must be "
              "refused by name", cft_strerror(s_hin), cft_last_error());
        s_hout = cft_exp(hw, fmt, CFT_RNE, b, dep.p, n, &fl);
        CHECK(s_hout != CFT_OK && strstr(cft_last_error(),
                                         "cft_buffer_to_device"),
              "cft_exp writing a lost resident buffer: %s (%s) - it must be "
              "refused by name", cft_strerror(s_hout), cft_last_error());
        if (caps.seq_features & CFT_SEQ_FEAT_LANE_MASK) {
            cft_run_args M = A;
            uint8_t *dm = (uint8_t *)malloc(n * esz);
            M.deposits = dm;
            M.lane_mask = dep.p;
            M.lane_mask_bytes = (n + 7) / 8;
            s_mask = dm ? cft_program_run_ex(prog, &M) : CFT_ERR_INTERNAL;
            CHECK(dm && s_mask != CFT_OK &&
                      strstr(cft_last_error(), "cft_buffer_to_device"),
                  "a lane mask read from a lost resident buffer: %s (%s) - "
                  "it must be refused by name", cft_strerror(s_mask),
                  cft_last_error());
            free(dm);
        } else {
            not_here(NH_OTHER, "TESTED", "    a lane mask in a lost buffer",
                     "this device does not publish CFT_SEQ_FEAT_LANE_MASK");
        }
        /* ...and the paths verifier-V9 found reading or writing a lost
         * buffer's elements unrefused until 2026-09-27: a composed run's
         * scalar read from it, a digest and a report written into it -
         * and an index table in it, refused by the LOST sentence rather
         * than the bound check's. The status is asked exactly: a report
         * with no sets to replay is CFT_ERR_ARTIFACT, not this refusal. */
        {
            cft_elem_args E;
            uint32_t t0[64];
            const uint32_t past = (uint32_t)(n + 3);
            memset(t0, 0, sizeof t0);
            /* The lost buffer's MIRROR is given an entry past the source,
             * so a bound check made on the mirror - before the table is
             * brought home - answers INVALID under its own sentence
             * rather than LOST. Without it the mirror is zeros, in range,
             * and the check passed with the bring-home removed
             * (verifier-V9's second pass). A plain store: the library
             * cannot see it, and the republish below overwrites it. */
            memcpy(dep.p, &past, sizeof past);
            memset(&E, 0, sizeof E);
            E.struct_size = sizeof E;
            E.a = b;
            E.d = out;
            E.n = n;
            E.idx_a = (const uint32_t *)(const void *)dep.p;
            E.idx_a_src = n;
            E.flags_out = &fl;
            E.bus_out = &bus;
            s_tab = cft_run_ex(hw, CFT_ABS, fmt, CFT_RNE, &E);
            CHECK(s_tab == CFT_ERR_INTERNAL &&
                      strstr(cft_last_error(), "cft_buffer_to_device"),
                  "an index table in a lost resident buffer: %s (%s) - it "
                  "must be refused by the LOST sentence", cft_strerror(s_tab),
                  cft_last_error());
            if (indexed) {
                memset(&E, 0, sizeof E);
                E.struct_size = sizeof E;
                E.a = b;
                E.c = dep.p;
                E.d = out;
                E.n = n;
                E.scalar_mask = 4u;                 /* c */
                E.idx_a = t0;
                E.idx_a_src = n;
                E.flags_out = &fl;
                E.bus_out = &bus;
                s_scal = cft_run_ex(hw, CFT_ADD, fmt, CFT_RNE, &E);
                CHECK(s_scal == CFT_ERR_INTERNAL &&
                          strstr(cft_last_error(), "cft_buffer_to_device"),
                      "a composed run's scalar read from a lost resident "
                      "buffer: %s (%s) - it must be refused by name",
                      cft_strerror(s_scal), cft_last_error());
            } else {
                not_here(NH_OTHER, "TESTED", "    a composed run's scalar in "
                         "a lost buffer", "this device does not publish "
                         "CFT_SEQ_FEAT_INDEXED, so there is no composed route");
            }
            s_dig = cft_program_digest(prog, NULL, 0, dep.p);
            CHECK(s_dig == CFT_ERR_INTERNAL &&
                      strstr(cft_last_error(), "cft_buffer_to_device"),
                  "cft_program_digest into a lost resident buffer: %s (%s) - "
                  "it must be refused by name", cft_strerror(s_dig),
                  cft_last_error());
            s_conf = cft_conformance(hw, "device-test: no vector sets here",
                                     (char *)dep.p, n * esz, NULL);
            CHECK(s_conf == CFT_ERR_INTERNAL &&
                      strstr(cft_last_error(), "cft_buffer_to_device"),
                  "cft_conformance's report into a lost resident buffer: %s "
                  "(%s) - it must be refused by name", cft_strerror(s_conf),
                  cft_last_error());
        }
        memset(&bi, 0, sizeof bi);
        bi.struct_size = sizeof bi;
        info_ok = cft_buffer_get_info(dep.b, &bi) == CFT_OK &&
                  bi.device_authority == 0 &&
                  !strncmp(bi.staged_why, "LOST", 4);
        CHECK(info_ok, "cft_buffer_get_info on a lost buffer: authority %d, "
              "\"%s\" - nothing is authoritative, and it must say LOST",
              bi.device_authority, bi.staged_why);
        right = s_out != CFT_OK && s_hin != CFT_OK && s_hout != CFT_OK &&
                (!(caps.seq_features & CFT_SEQ_FEAT_LANE_MASK) ||
                 s_mask != CFT_OK) && info_ok &&
                s_tab == CFT_ERR_INTERNAL && s_dig == CFT_ERR_INTERNAL &&
                s_conf == CFT_ERR_INTERNAL &&
                (!indexed || s_scal == CFT_ERR_INTERNAL);
    }
    /* published again, it is the caller's - read back BEFORE anything
     * runs over it, or a publish that brought the failed run's bytes home
     * would be hidden by the next run's (verifier-V8) */
    memset(dep.p, 0x77, n * esz);
    s_repub = cft_buffer_to_device(dep.b);
    {
        size_t k;
        int kept = cft_buffer_from_device(dep.b) == CFT_OK;
        for (k = 0; kept && k < n * esz; k++)
            kept = dep.p[k] == 0x77;
        CHECK(s_repub == CFT_OK && kept, "a lost buffer published again "
              "(%s): %s, and read back %s - the caller's bytes must stand, "
              "not the failed run's", cft_format_name(fmt),
              cft_strerror(s_repub), kept ? "the caller's" : "OTHER bytes");
        right = right && kept;
    }
    s_after = cft_program_run_ex(prog, &A);
    s_back2 = cft_buffer_from_device(dep.b);
    CHECK(s_repub == CFT_OK && s_after == CFT_OK && s_back2 == CFT_OK &&
              !memcmp(dep.p, a, n * esz),
          "after publishing it again, a run into the buffer and its read-back "
          "(%s): %s / %s / %s (%s)", cft_format_name(fmt),
          cft_strerror(s_repub), cft_strerror(s_after), cft_strerror(s_back2),
          cft_last_error());
    right = right && s_back != CFT_OK && s_in != CFT_OK &&
            s_repub == CFT_OK && s_after == CFT_OK && s_back2 == CFT_OK &&
            !memcmp(dep.p, a, n * esz);
    if (right)
        printf("    a resident output a refused run wrote (%s): its read-back, "
               "its use as an input, a run into it, a lane mask, an index "
               "table and a composed run's scalar read from it, cft_exp "
               "reading or writing it, a digest and a report written into it "
               "all refused by name, get_info says LOST, and published again "
               "it is right\n", cft_format_name(fmt));
out:
    cft_program_free(prog);
    if (dep.b)
        rbuf_free(&dep);
    free(a); free(b); free(out);
}

/* ==== revision 7: a program that walks past 256 slots ==================
 *
 * The U50's tiles have 2,048 scratch slots a lane from revision 7 and
 * the open-core ones 256, and the depth is part of what a non-strict
 * STX/LDX MEANS: it reduces the index modulo the depth. So the software
 * reference this file compares against is opened at the DEVICE's depth
 * (main, through cft_open_ex), and this leg runs a program that reaches
 * past slot 255 - plain and strict - on both.
 *
 * The program is programs/deepwalk-fp64's shape at every format: WALK
 * samples a[0] = x, a[k+1] = a[k]*(1 + 2^-8) + 1, stored through a loop
 * counter, then read back from the top and summed; it deposits the sum
 * and the last sample. 1 + 2^-8 grows gently enough that fp32 holds
 * three hundred of them. On a 256-slot tile the walk wraps (plain) or
 * is reported past slot 255 (strict); on a deeper one it does neither.
 *
 * When the device is deeper than 256 the leg also holds the reference
 * to having BEEN at that depth: the same image on a plain cft_open(NULL)
 * handle, which is 256, must compute a different sum (plain) and report
 * the index past the depth (strict), where the reference reports
 * nothing. A comparison that agreed only because both sides wrapped
 * would otherwise pass. */
#define DEEP_WALK 300u

static void make_one(uint8_t *e, cft_format fmt)
{
    int total = LAYOUT[(int)fmt].total_bits;
    int ebits = LAYOUT[(int)fmt].exp_bits;
    int sbits = total - 1 - ebits;
    memset(e, 0, (size_t)total / 8);
    put_bits(e, sbits, ebits, ((uint64_t)1 << (ebits - 1)) - 1);
}

static size_t deep_walk_image(uint8_t *img, cft_format fmt, int strict)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t k[3 * MAXE];
    uint64_t ins[14];
    put_index(k, fmt, 1);                        /* k0 IONE, the integer 1 */
    make_one_plus(k + esz, fmt, 8);              /* k1 GROW, 1 + 2^-8 */
    make_one(k + 2 * esz, fmt);                  /* k2 ONE */
    ins[0]  = seq_alu(CFT_COPYSIGN, 4, 0, 0, 0, 0, 0, 0); /* v = x */
    ins[1]  = seq_ctrl(1, 0, DEEP_WALK);         /* repeat WALK */
    ins[2]  = seq_stx(4, 3);                     /*   a[i] = v */
    ins[3]  = seq_alu(CFT_IADD, 3, 3, 0, 0, 0, 1, 0);     /*   i += 1 */
    ins[4]  = seq_alu(CFT_FMA, 4, 4, 1, 2, 0, 1, 1);      /*   v = v*GROW+1 */
    ins[5]  = seq_ctrl(2, 0, 0);                 /* endrep */
    ins[6]  = seq_ctrl(1, 0, DEEP_WALK);         /* repeat WALK */
    ins[7]  = seq_alu(CFT_ISUB, 3, 3, 0, 0, 0, 1, 0);     /*   i -= 1 */
    ins[8]  = seq_ldx(5, 3);                     /*   s = a[i] */
    ins[9]  = seq_alu(CFT_FMA, 6, 5, 2, 6, 0, 1, 0);      /*   acc += s */
    ins[10] = seq_ctrl(2, 0, 0);                 /* endrep */
    ins[11] = seq_ctrl(3, 6, 0);                 /* deposit acc */
    ins[12] = seq_ctrl(3, 4, 0);                 /* deposit v */
    ins[13] = seq_ctrl(0, 0, 0);
    return seq_image_flags(img, fmt, ins, 14, k, 3, 2,
                           strict ? CFT_PROG_FLAG_SCRATCH_STRICT : 0u);
}

/* One image on one handle over finite inputs: the deposits and STATUS. */
static int deep_walk_run(cft_device *dev, cft_format fmt, const uint8_t *img,
                         size_t bytes, const uint8_t *a, size_t n,
                         uint8_t *dep, uint32_t *bus)
{
    cft_program *p = NULL;
    uint32_t *cnt = (uint32_t *)malloc(n * 4);
    cft_status st = cnt ? cft_program_load(dev, img, bytes, &p)
                        : CFT_ERR_OUT_OF_MEMORY;
    if (st == CFT_OK)
        st = cft_program_run(p, a, a, a, dep, cnt, n, NULL, bus);
    cft_program_free(p);
    free(cnt);
    (void)fmt;
    return st == CFT_OK;
}

static void compare_seq_deep(cft_device *sw, cft_device *hw, cft_format fmt,
                             size_t n, uint32_t seed)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t img[32 + 3 * MAXE + 14 * 8];
    cft_caps hc, sc;
    size_t bytes;
    int strict;

    memset(&hc, 0, sizeof hc);
    hc.struct_size = sizeof hc;
    memset(&sc, 0, sizeof sc);
    sc.struct_size = sizeof sc;
    if (cft_get_caps(hw, &hc) != CFT_OK || cft_get_caps(sw, &sc) != CFT_OK ||
        !(hc.seq_features & CFT_SEQ_FEAT_SCRATCH) || !hc.max_scratch) {
        not_here(NH_OTHER, "COMPARED", "  seq walk past 256 slots",
                 "this device publishes no scratch depth");
        return;
    }
    checks++;
    if (sc.max_scratch != hc.max_scratch) {
        printf("  FAIL seq walk past 256 slots: the reference has %lu scratch "
               "slots a lane and the device %lu - a non-strict index reduces "
               "modulo the depth, so the two would compute different "
               "machines\n", (unsigned long)sc.max_scratch,
               (unsigned long)hc.max_scratch);
        failures++;
        return;
    }
    for (strict = 0; strict < 2; strict++) {
        if (strict && !(hc.seq_features & CFT_SEQ_FEAT_SCRATCH_STRICT)) {
            not_here(NH_OTHER, "COMPARED", "  seq walk past 256 slots, strict",
                     "this device does not publish SCRATCH_STRICT");
            continue;
        }
        bytes = deep_walk_image(img, fmt, strict);
        compare_seq_one(sw, hw, fmt, img, bytes, 2, n, seed + (uint32_t)strict,
                        strict ? "seq walk past 256 slots, strict"
                               : "seq walk past 256 slots");
    }

    /* The reference was at the device's depth, and the walk reached past
     * 256: only askable where the device is deeper than 256. */
    if (hc.max_scratch <= 256u) {
        not_here(NH_OTHER, "TESTED", "  the walk's depth against 256",
                 "this device has %lu slots a lane, so the walk wraps on "
                 "both sides of the comparison",
                 (unsigned long)hc.max_scratch);
        return;
    }
    {
        cft_device *plain = NULL;
        uint8_t *a = (uint8_t *)malloc(n * esz);
        uint8_t *d_ref = (uint8_t *)malloc(n * 2 * esz);
        uint8_t *d_256 = (uint8_t *)malloc(n * 2 * esz);
        uint32_t bus_ref = 0, bus_256 = 0;
        checks++;
        if (!a || !d_ref || !d_256 || cft_open(NULL, 0, &plain) != CFT_OK) {
            printf("  FAIL seq walk past 256 slots: could not set up the "
                   "256-slot handle (%s)\n", cft_last_error());
            failures++;
        } else {
            fill_finite(a, fmt, n);
            for (strict = 0; strict < 2; strict++) {
                bytes = deep_walk_image(img, fmt, strict);
                checks++;
                if (!deep_walk_run(sw, fmt, img, bytes, a, n, d_ref,
                                   &bus_ref) ||
                    !deep_walk_run(plain, fmt, img, bytes, a, n, d_256,
                                   &bus_256)) {
                    printf("  FAIL seq walk past 256 slots: a run did not "
                           "complete: %s\n", cft_last_error());
                    failures++;
                    continue;
                }
                checks++;
                if (!memcmp(d_ref, d_256, n * 2 * esz)) {
                    printf("  FAIL seq walk past 256 slots%s: the sums at %lu "
                           "slots and at 256 are the same bytes, so this "
                           "comparison could not tell the depths apart\n",
                           strict ? ", strict" : "",
                           (unsigned long)hc.max_scratch);
                    failures++;
                }
                checks++;
                if (strict && ((bus_256 & CFT_STATUS_SCRATCH_RANGE) == 0 ||
                               (bus_ref & CFT_STATUS_SCRATCH_RANGE) != 0)) {
                    printf("  FAIL seq walk past 256 slots, strict: STATUS "
                           "0x%x at 256 and 0x%x at %lu - the index past "
                           "slot 255 is reported at 256 and nowhere else\n",
                           bus_256, bus_ref, (unsigned long)hc.max_scratch);
                    failures++;
                }
            }
            printf("    a walk past 256 slots at %lu: the device agrees with "
                   "the reference, and a 256-slot handle differs (plain) and "
                   "reports it (strict)\n", (unsigned long)hc.max_scratch);
        }
        cft_close(plain);
        free(a); free(d_ref); free(d_256);
    }
}

/* ==== revision 7: a scratch block as deep as the device =================
 *
 * R5's per-run block is n_scratch_in slots a lane preloaded and
 * n_scratch_out read back, each at most the device's depth. On a
 * 2,048-slot device - the U50's revision-7 tiles, and a software handle
 * opened at that depth - a block of 257 to 2,048 slots is legal, and
 * until 2026-09-29 libcft's loader refused every one of them on every
 * handle, as CFT_ERR_INVALID_ARGUMENT with no sentence: a test of the
 * library's own 256-slot ceiling ran whatever depth the device
 * published (verifier-R5). No leg held a block past 256, so nothing saw
 * it.
 *
 * This leg runs, on the device under test, a block of 300 slots in and
 * out, 300 in alone, 300 out alone, and the device's whole depth both
 * ways, and holds the bytes to what the program must make of them: it
 * reads the preload's top slot into a deposit and stores its a operand
 * at the out block's top slot. So each lane deposits its own preload's
 * last element (+0 with no preload), and reads back its preload with
 * the top slot replaced by a and +0 past the preload. It needs no
 * reference, so a library that refused the block on both sides, or
 * stopped a preload at 256 on both, still fails it. And it holds one
 * slot past the depth refused BY NAME, in and out, on this device. On
 * a device of 256 slots the 300-slot blocks are past the depth, and
 * only the whole-depth block runs. */
static void check_scratch_block_deep(cft_device *dev, cft_format fmt,
                                     size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t img[32 + 4 * 8], zero[MAXE];
    uint32_t cases[4][2], d;
    unsigned ncase = 0, k;
    uint8_t *a = NULL, *dep = NULL, *sin_buf = NULL, *sout_buf = NULL;
    uint32_t *cnt = NULL;
    int ran = 0;
    cft_caps c;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    if (cft_get_caps(dev, &c) != CFT_OK ||
        !(c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) || !c.max_scratch) {
        not_here(NH_OTHER, "TESTED", "  seq scratch block at the depth",
                 "this device publishes no scratch block, or no depth");
        return;
    }
    d = c.max_scratch;
    if (n > 200)
        n = 200;
    if (d > 256u) {
        cases[ncase][0] = 300u; cases[ncase][1] = 300u; ncase++;
        cases[ncase][0] = 300u; cases[ncase][1] = 0u;   ncase++;
        cases[ncase][0] = 0u;   cases[ncase][1] = 300u; ncase++;
    } else {
        not_here(NH_OTHER, "TESTED", "  seq scratch block of 300 slots",
                 "this device has %lu scratch slots a lane, so the block "
                 "is past its depth (refused by name above)",
                 (unsigned long)d);
    }
    cases[ncase][0] = d; cases[ncase][1] = d; ncase++;

    memset(zero, 0, sizeof zero);
    a = (uint8_t *)malloc(n * esz);
    dep = (uint8_t *)malloc(n * esz);
    sin_buf = (uint8_t *)malloc(n * (size_t)d * esz);
    sout_buf = (uint8_t *)malloc(n * (size_t)d * esz);
    cnt = (uint32_t *)malloc(n * 4);
    checks++;
    if (!a || !dep || !sin_buf || !sout_buf || !cnt) {
        printf("  FAIL seq scratch block at the depth: out of memory\n");
        failures++;
        goto out;
    }
    fill_finite(a, fmt, n);

    for (k = 0; k < ncase; k++) {
        const uint32_t n_in = cases[k][0], n_out = cases[k][1];
        const uint32_t t_in = n_in ? n_in - 1u : 0u;
        const uint32_t t_out = n_out ? n_out - 1u : 0u;
        uint64_t ins[4];
        cft_program *prog = NULL;
        cft_run_args A;
        cft_status st;
        size_t bytes, i, bad_dep = 0, bad_out = 0, bad_cnt = 0;
        uint32_t s;

        ins[0] = seq_ldl(4, t_in);              /* the preload's top slot */
        ins[1] = seq_ctrl(3, 4, 0);             /* deposit it */
        ins[2] = seq_stl(0, t_out);             /* the out block's top = a */
        ins[3] = seq_ctrl(0, 0, 0);
        bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 1,
                                  CFT_PROG_FLAG_SCRATCH_IO, n_in, n_out);
        checks++;
        st = cft_program_load(dev, img, bytes, &prog);
        if (st != CFT_OK) {
            printf("  FAIL seq scratch block of %lu in and %lu out at %lu "
                   "slots: the image did not load (%s): %s\n",
                   (unsigned long)n_in, (unsigned long)n_out,
                   (unsigned long)d, cft_strerror(st), cft_last_error());
            failures++;
            continue;
        }
        fill_finite(sin_buf, fmt, n * (size_t)n_in);
        memset(sout_buf, 0xA5, n * (size_t)d * esz);
        memset(dep, 0xA5, n * esz);
        run_args_init(&A, a, dep, n);
        A.counts            = cnt;
        A.scratch_in        = n_in ? sin_buf : NULL;
        A.scratch_in_bytes  = n * (size_t)n_in * esz;
        A.scratch_out       = n_out ? sout_buf : NULL;
        A.scratch_out_bytes = n * (size_t)n_out * esz;
        checks++;
        st = cft_program_run_ex(prog, &A);
        cft_program_free(prog);
        if (st != CFT_OK) {
            printf("  FAIL seq scratch block of %lu in and %lu out at %lu "
                   "slots: the run failed (%s): %s\n",
                   (unsigned long)n_in, (unsigned long)n_out,
                   (unsigned long)d, cft_strerror(st), cft_last_error());
            failures++;
            continue;
        }
        for (i = 0; i < n; i++) {
            const uint8_t *want_dep = n_in
                ? sin_buf + (i * n_in + t_in) * esz : zero;
            if (memcmp(dep + i * esz, want_dep, esz) != 0)
                bad_dep++;
            if (cnt[i] != 1u)
                bad_cnt++;
            for (s = 0; s < n_out; s++) {
                const uint8_t *want = s == t_out ? a + i * esz
                                    : s < n_in ? sin_buf + (i * n_in + s) * esz
                                    : zero;
                if (memcmp(sout_buf + (i * n_out + s) * esz, want,
                           esz) != 0)
                    bad_out++;
            }
        }
        checks += 3;
        if (bad_dep || bad_cnt || bad_out) {
            printf("  FAIL seq scratch block of %lu in and %lu out at %lu "
                   "slots: %lu of %lu lanes deposited another value than "
                   "their preload's top slot, %lu counts were not 1, and "
                   "%lu of %lu out-block elements are not the preload, "
                   "a or +0 where each belongs\n",
                   (unsigned long)n_in, (unsigned long)n_out,
                   (unsigned long)d, (unsigned long)bad_dep,
                   (unsigned long)n, (unsigned long)bad_cnt,
                   (unsigned long)bad_out,
                   (unsigned long)(n * (size_t)n_out));
            failures++;
            continue;
        }
        ran++;
    }

    /* One past the depth, in and out, refused by name on THIS device -
     * the refusal leg asks the reference, and the card's own loader is
     * the one a host meets. */
    {
        uint64_t ins[2];
        char needle[64];
        ins[0] = seq_ctrl(0, 0, 0);
        ins[1] = seq_ctrl(0, 0, 0);
        snprintf(needle, sizeof needle, "n_scratch_in is %lu",
                 (unsigned long)d + 1u);
        refusal(dev, fmt, "a scratch block one slot past the depth, in",
                img, seq_image_scratch(img, fmt, ins, 2, NULL, 0, 1,
                                       CFT_PROG_FLAG_SCRATCH_IO, d + 1u, 0),
                CFT_ERR_UNSUPPORTED, needle);
        snprintf(needle, sizeof needle, "n_scratch_out is %lu",
                 (unsigned long)d + 1u);
        refusal(dev, fmt, "a scratch block one slot past the depth, out",
                img, seq_image_scratch(img, fmt, ins, 2, NULL, 0, 1,
                                       CFT_PROG_FLAG_SCRATCH_IO, 0, d + 1u),
                CFT_ERR_UNSUPPORTED, needle);
    }
    if (ran == (int)ncase)
        printf("    a scratch block at %lu slots (%s the whole depth both "
               "ways): every lane's bytes; %lu + 1 refused by name\n",
               (unsigned long)d,
               d > 256u ? "300 in and out, 300 in, 300 out, and" : "only",
               (unsigned long)d);
out:
    free(a); free(dep); free(sin_buf); free(sout_buf); free(cnt);
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
        not_here(NH_OTHER, "COMPARED", "  seq r16..r31",
                 "this device does not publish REGS32 (the refusal is "
                 "scored above)");
    }

    /* 6. the per-run constant bank, and the digest over image and
     *    data together. Same gate, same reason. */
    if (hcaps.seq_features & CFT_SEQ_FEAT_BANK_PTR)
        compare_seq_bank(sw, hw, fmt, n, seed + 5);
    else
        not_here(NH_OTHER, "COMPARED", "  seq BANK_EXT",
                 "this device does not publish BANK_PTR (the refusal is "
                 "scored above)");

    /* 7. the per-lane scratch memory and its per-run block, revision
     *    3's R4 and R5, gated the same way and named NOT TESTED where
     *    the device does not publish them. Run against the device
     *    under test rather than the software handle, because a tile
     *    with the feature has its own memory and its own two
     *    pointers. */
    check_scratch(hw, fmt, n);
    /* 7a. revision 7: a walk past 256 slots, against the reference at
     *     the device's depth; and a scratch block as deep as the
     *     device, held to its own bytes (verifier-R5's finding). */
    compare_seq_deep(sw, hw, fmt, n, seed + 7);
    check_scratch_block_deep(hw, fmt, n);
    check_program_past_a_page(hw, fmt);
    check_program_capacity(hw, fmt);
    check_completion_witness(hw, fmt);
    check_lost_after_refusal(hw, fmt);
    check_masked_resident(hw, fmt);

    /* 7b. ABI 0.14's index tables (R16), gated on the feature bit the
     *     same way and named NOT COMPARED where the device does not
     *     publish it. */
    check_indexed(sw, hw, fmt, n);
    check_masked(sw, hw, fmt, n);
    check_indexed_masked(sw, hw, fmt, n);
    check_masked_scratch_out(sw, hw, fmt, n);

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

/* struct rbuf is defined above check_masked_resident. */

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
/* ---------------------------------------------------------------
 * An OUTPUT window moved onto another tile's unflushed one
 * (2026-09-25).
 *
 * A resident buffer written by a run on every tile, and not yet
 * brought home, holds its last slice in the LAST tile's copy. A second,
 * short run then writes the buffer's final elements through a pointer
 * into it: one slice, on the first tile. Two copies now hold bytes for
 * the same elements - the last tile's older ones and the first tile's
 * newer ones - and until 2026-09-25 the library brought copies home in
 * table order, so the older bytes landed LAST and replaced the second
 * run's results with the first's. It now sends overlapping older bytes
 * home before a run is handed the window. The buffer read back must hold
 * the second run's results where it wrote and the first run's
 * everywhere else, element for element against the software backend.
 * One tile cannot hold two copies on two tiles: there the leg runs, and
 * says the overlap it exists for was not reachable.
 * --------------------------------------------------------------- */
static void check_moved_output_window(cft_device *sw, cft_device *hw,
                                      cft_format fmt, unsigned tiles)
{
    const size_t esz = cft_format_size(fmt), epb = 32 / esz;
    const size_t n = 64 * epb;          /* 64 beats: 16 a tile on a quad */
    const size_t n2 = epb;              /* one beat: one slice, one tile */
    const size_t tail = n - n2;
    uint8_t *a1 = (uint8_t *)malloc(n * esz), *b1 = (uint8_t *)malloc(n * esz);
    uint8_t *c1 = (uint8_t *)calloc(n, esz), *want = (uint8_t *)malloc(n * esz);
    uint8_t *a2 = (uint8_t *)malloc(n2 * esz), *b2 = (uint8_t *)malloc(n2 * esz);
    uint8_t *c2 = (uint8_t *)calloc(n2, esz);
    struct rbuf x;
    cft_status w1 = CFT_ERR_INTERNAL, w2 = CFT_ERR_INTERNAL;
    cft_status s1 = CFT_ERR_INTERNAL, s2 = CFT_ERR_INTERNAL;
    uint32_t f = 0, bus = 0;
    size_t i, bad = 0;

    x.b = NULL;
    x.p = NULL;
    if (!a1 || !b1 || !c1 || !want || !a2 || !b2 || !c2 ||
        !rbuf_alloc(hw, &x, n * esz)) {
        printf("  FAIL: out of memory for the moved-window leg\n");
        failures++;
        goto out;
    }
    rs = 0x5eed0925u;
    fill(a1, n, esz);
    fill(b1, n, esz);
    fill(a2, n2, esz);
    fill(b2, n2, esz);

    /* software: the first run over all of it, the second over its tail */
    w1 = cft_run(sw, CFT_ADD, fmt, CFT_RNE, a1, b1, c1, want, n, &f, NULL);
    w2 = cft_run(sw, CFT_ADD, fmt, CFT_RNE, a2, b2, c2, want + tail * esz,
                 n2, &f, NULL);
    /* the device: the same two runs into the resident buffer, and
     * nothing brought home between them */
    s1 = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a1, b1, c1, x.p, n, &f, &bus);
    s2 = cft_run(hw, CFT_ADD, fmt, CFT_RNE, a2, b2, c2, x.p + tail * esz, n2,
                 &f, &bus);
    CHECK(w1 == CFT_OK && w2 == CFT_OK,
          "software ADD for the moved-window leg (%s)", cft_format_name(fmt));
    CHECK(s1 == CFT_OK && s2 == CFT_OK,
          "device ADD into a resident buffer, then into its last beat "
          "(%s): %s / %s (%s)", cft_format_name(fmt), cft_strerror(s1),
          cft_strerror(s2), cft_last_error());
    CHECK(cft_buffer_from_device(x.b) == CFT_OK,
          "reading the moved-window buffer back");
    if (w1 == CFT_OK && w2 == CFT_OK && s1 == CFT_OK && s2 == CFT_OK) {
        for (i = 0; i < n; i++)
            if (memcmp(want + i * esz, x.p + i * esz, esz) != 0) {
                if (bad < 3) {
                    char h1[2 * MAXE + 1], h2[2 * MAXE + 1];
                    hex(want + i * esz, esz, h1);
                    hex(x.p + i * esz, esz, h2);
                    printf("  FAIL: %s moved-window element %lu (%s run's): "
                           "software %s, device %s\n", cft_format_name(fmt),
                           (unsigned long)i, i >= tail ? "the second" : "the "
                           "first", h1, h2);
                }
                bad++;
            }
        checks++;
        if (bad) {
            failures++;
            printf("  FAIL: %lu of %lu elements of the moved-window buffer "
                   "are not what the two runs wrote\n", (unsigned long)bad,
                   (unsigned long)n);
        }
    }
    if (!bad && tiles <= 1)
        /* The two runs were still compared above; what one tile cannot
         * reach is the overlap across tiles the leg exists for, and a
         * pass would claim it (verifier-V4, 2026-09-25). */
        not_here(NH_OTHER, "TESTED",
                 "  buffers, an output window moved onto another tile's "
                 "unflushed one", "one tile (%s), so the overlap across "
                 "tiles it exists for is not reachable; the two runs "
                 "themselves were compared", cft_format_name(fmt));
    else
        printf("  buffers, an output window moved onto another tile's "
               "unflushed one (%s): %s\n", cft_format_name(fmt),
               bad ? "FAILED" : "the second run's results survived");
out:
    if (x.b)
        rbuf_free(&x);
    free(a1); free(b1); free(c1); free(want); free(a2); free(b2); free(c2);
}

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

/* A PROGRAM's scratch blocks through ORDINARY HOST POINTERS on a device.
 *
 * The plainest thing a caller can do, and until 2026-09-12 nothing ran
 * it: the software gates do not use XRT, and the residency leg below
 * allocates everything with cft_alloc. So when the scratch binding
 * landed and its staging guard was evaluated after the fallback that
 * fills ob[] - skipping the staging of the unbound case and leaving the
 * tile reading a buffer nobody filled - every gate stayed green.
 *
 * Held to the software backend, which is the authority for what the
 * program computes.
 */
static void compare_program_staged(cft_device *sw, cft_device *hw,
                                   cft_format fmt, size_t n)
{
    const size_t esz = cft_format_size(fmt);
    uint8_t *a = NULL, *sin_h = NULL;
    uint8_t *dep_sw = NULL, *dep_hw = NULL;
    uint8_t *out_sw = NULL, *out_hw = NULL;
    cft_program *p_sw = NULL, *p_hw = NULL;
    uint8_t img[64];
    uint64_t ins[4];
    size_t bytes, blk = n * esz;
    uint32_t fl = 0, bus = 0;
    cft_run_args A;
    int ok = 1;

    ins[0] = seq_ldl(4, 0);
    ins[1] = seq_ctrl(3, 4, 0);
    ins[2] = seq_stl(4, 0);
    ins[3] = seq_ctrl(0, 0, 0);
    bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 1,
                              CFT_PROG_FLAG_SCRATCH_IO, 1, 1);

    a      = (uint8_t *)malloc(blk);
    sin_h  = (uint8_t *)malloc(blk);
    dep_sw = (uint8_t *)malloc(blk);
    dep_hw = (uint8_t *)malloc(blk);
    out_sw = (uint8_t *)malloc(blk);
    out_hw = (uint8_t *)malloc(blk);
    if (!a || !sin_h || !dep_sw || !dep_hw || !out_sw || !out_hw) {
        printf("  FAIL %s staged scratch: out of memory\n",
               cft_format_name(fmt));
        failures++;
        goto done;
    }
    fill_finite(a, fmt, n);
    fill_scratch_block(sin_h, fmt, n, 1);

    if (cft_program_load(sw, img, bytes, &p_sw) != CFT_OK ||
        cft_program_load(hw, img, bytes, &p_hw) != CFT_OK) {
        printf("  FAIL %s staged scratch: the image did not load: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }

    run_args_init(&A, a, dep_sw, n);
    A.scratch_in        = sin_h;
    A.scratch_in_bytes  = blk;
    A.scratch_out       = out_sw;
    A.scratch_out_bytes = blk;
    A.flags_out         = &fl;
    A.bus_out           = &bus;
    if (cft_program_run_ex(p_sw, &A) != CFT_OK) {
        printf("  FAIL %s staged scratch: the software run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }

    /* The same run on the device, every buffer an ordinary pointer. */
    run_args_init(&A, a, dep_hw, n);
    A.scratch_in        = sin_h;
    A.scratch_in_bytes  = blk;
    A.scratch_out       = out_hw;
    A.scratch_out_bytes = blk;
    A.flags_out         = &fl;
    A.bus_out           = &bus;
    if (cft_program_run_ex(p_hw, &A) != CFT_OK) {
        printf("  FAIL %s staged scratch: the device run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }

    if (memcmp(dep_sw, dep_hw, blk)) {
        printf("  FAIL %s staged scratch: the deposits differ from the "
               "software backend - the scratch-in block did not reach the "
               "tile\n", cft_format_name(fmt));
        failures++;
        ok = 0;
    }
    if (memcmp(out_sw, out_hw, blk)) {
        printf("  FAIL %s staged scratch: the scratch-out block differs "
               "from the software backend\n", cft_format_name(fmt));
        failures++;
        ok = 0;
    }
    checks++;
    if (ok)
        printf("    %-5s staged scratch: %lu lanes through host pointers, "
               "identical to software\n",
               cft_format_name(fmt), (unsigned long)n);

done:
    cft_program_free(p_hw);
    cft_program_free(p_sw);
    free(out_hw); free(out_sw);
    free(dep_hw); free(dep_sw);
    free(sin_h);  free(a);
}

/* A PROGRAM's two scratch blocks, resident, held to the staged path.
 *
 * The blocks are operand-shaped - n * count format-width elements,
 * lane-major, dense - so they bind exactly as the deposit window does
 * (docs/SEQUENCER.md R5, host/src/backend.h's role list). Before that
 * binding existed they were staged on every run, which put a transfer
 * in an integrator's innermost loop: the b, g and e coefficient arrays
 * live in the scratch and are rewritten every corrector pass
 * (cft-rebound/docs/HARDWARE.md, the first ask).
 *
 * Instruction ORDER is load-then-store deliberately. LDL first means the
 * deposits carry what scratch-IN supplied, so a block that never
 * arrived shows up in the deposits; STL last means scratch-OUT carries
 * it back out. Reversed, this would pass with scratch_in undelivered.
 */
/* ==== R16 through the BUFFER path ====================================
 *
 * Everything above proves the gather's answers. This proves where its
 * operands lived: the four index tables and an indexed SOURCE
 * registered with cft_alloc, run resident, against the same call made
 * out of plain host pointers. The "bound where it is resident"
 * argument - device.c's four bind_role calls and backend_xrt.cpp's
 * buf_bind of ob[CFT_ROLE_IA..] - had no gate on any backend until
 * this leg, and it is the argument the whole feature's cost rests on:
 * a table rebuilt once a step and read by every call in it.
 *
 * Two things this can catch that the answer alone cannot. A table
 * bound at the wrong WINDOW - the run's n elements rather than the
 * source's idx_*_src - gives the right bits on the software backend
 * and truncates on a card; and a table that is staged every time when
 * it could be bound gives the right bits and none of the saving, which
 * `resident_binds` is here to say.
 *
 * The program deposits the gathered stream element AND the gathered
 * scratch slot, so both kinds of table are observable in the output:
 * slot 0 is a[idx_a[i]] and slot 1 is pool[idx_si[i]].
 * ==================================================================== */

/* Every byte zero: the encoding of +0 at every format, which is
 * what CFT_IDX_NONE reads as. */
static int is_zero(const uint8_t *p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        if (p[i])
            return 0;
    return 1;
}

static void compare_buffers_indexed(cft_device *sw, cft_device *hw,
                                    cft_format fmt, size_t n,
                                    int resident_expected)
{
    const size_t esz = cft_format_size(fmt);
    /* Deliberately unrelated to n, and deliberately SHORTER: that is
     * the shape the feature exists for, and it is the one whose
     * binding window is the source's length and not the run's. */
    const size_t src_n = (n / 3) + 2;
    const size_t pool_n = (n / 2) + 3;
    struct rbuf rsrc, rpool, rta, rtsi, rdep;
    uint8_t *src = NULL, *pool = NULL;
    uint8_t *dep_sw = NULL, *dep_hw = NULL;
    uint32_t *ta = NULL, *tsi = NULL;
    cft_program *p_sw = NULL, *p_hw = NULL;
    uint8_t img[64];
    uint64_t ins[4];
    size_t bytes, dep_bytes = n * 2 * esz;
    size_t i;
    uint32_t fl = 0, bus = 0;
    cft_run_args A;
    int ok = 1, have = 0;

    ins[0] = seq_ldl(4, 0);                   /* r4 <- scratch[0]     */
    ins[1] = seq_ctrl(3, 0, 0);               /* deposit r0 (gathered)*/
    ins[2] = seq_ctrl(3, 4, 0);               /* deposit r4 (gathered)*/
    ins[3] = seq_ctrl(0, 0, 0);               /* halt                 */
    bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 2,
                              CFT_PROG_FLAG_SCRATCH_IO, 1, 0);

    memset(&rsrc, 0, sizeof rsrc); memset(&rpool, 0, sizeof rpool);
    memset(&rta, 0, sizeof rta);   memset(&rtsi, 0, sizeof rtsi);
    memset(&rdep, 0, sizeof rdep);

    src    = (uint8_t *)malloc(src_n * esz);
    pool   = (uint8_t *)malloc(pool_n * esz);
    dep_sw = (uint8_t *)malloc(dep_bytes);
    dep_hw = (uint8_t *)malloc(dep_bytes);
    ta     = (uint32_t *)malloc(n * 4);
    tsi    = (uint32_t *)malloc(n * 4);
    if (!src || !pool || !dep_sw || !dep_hw || !ta || !tsi) {
        printf("  FAIL %s indexed buffers: out of memory\n",
               cft_format_name(fmt));
        failures++;
        goto done;
    }
    fill_finite(src, fmt, src_n);
    fill_finite(pool, fmt, pool_n);
    /* Distinct entries where the source allows it, and one sentinel in
     * five, which must read +0 and cost no read. */
    for (i = 0; i < n; i++) {
        ta[i]  = (i % 5 == 0) ? CFT_IDX_NONE
                              : (uint32_t)((i * 7 + 1) % src_n);
        tsi[i] = (i % 7 == 0) ? CFT_IDX_NONE
                              : (uint32_t)((i * 3 + 2) % pool_n);
    }

    if (cft_program_load(sw, img, bytes, &p_sw) != CFT_OK ||
        cft_program_load(hw, img, bytes, &p_hw) != CFT_OK) {
        printf("  FAIL %s indexed buffers: the image did not load: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }

#define IDXBUF_ARGS(a_, si_, ta_, tsi_, dep_)                          \
    do {                                                               \
        run_args_init(&A, (a_), (dep_), n);                            \
        A.scratch_in        = (si_);                                   \
        A.scratch_in_bytes  = pool_n * esz;                            \
        A.idx_a             = (ta_);                                   \
        A.idx_a_src         = src_n;                                   \
        A.idx_scratch_in    = (tsi_);                                  \
        A.idx_scratch_src   = pool_n;                                  \
        A.flags_out         = &fl;                                     \
        A.bus_out           = &bus;                                    \
    } while (0)

    /* The staged reference: plain host pointers, software backend. */
    memset(dep_sw, 0x5a, dep_bytes);
    IDXBUF_ARGS(src, pool, ta, tsi, dep_sw);
    checks++;
    if (cft_program_run_ex(p_sw, &A) != CFT_OK) {
        printf("  FAIL %s indexed buffers: the software run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }

    /* The resident run: EVERY operand-shaped buffer from cft_alloc -
     * the source, the pool, both tables and the deposit window - so a
     * device that binds binds all five. */
    if (!rbuf_alloc(hw, &rsrc, src_n * esz) ||
        !rbuf_alloc(hw, &rpool, pool_n * esz) ||
        !rbuf_alloc(hw, &rta, n * 4) ||
        !rbuf_alloc(hw, &rtsi, n * 4) ||
        !rbuf_alloc(hw, &rdep, dep_bytes)) {
        printf("  FAIL %s indexed buffers: cft_alloc\n",
               cft_format_name(fmt));
        failures++;
        goto done;
    }
    if (!rbuf_put(&rsrc, src, src_n * esz) ||
        !rbuf_put(&rpool, pool, pool_n * esz) ||
        !rbuf_put(&rta, ta, n * 4) ||
        !rbuf_put(&rtsi, tsi, n * 4)) {
        printf("  FAIL %s indexed buffers: publishing the inputs: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }
    have = 1;
    memset(rdep.p, 0x5a, dep_bytes);
    IDXBUF_ARGS(rsrc.p, rpool.p, (const uint32_t *)rta.p,
                (const uint32_t *)rtsi.p, rdep.p);
    checks++;
    if (cft_program_run_ex(p_hw, &A) != CFT_OK) {
        printf("  FAIL %s indexed buffers: the resident run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }
    if (cft_buffer_from_device(rdep.b) != CFT_OK) {
        printf("  FAIL %s indexed buffers: collecting the deposits: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done;
    }
    memcpy(dep_hw, rdep.p, dep_bytes);
    checks++;
    if (memcmp(dep_sw, dep_hw, dep_bytes) != 0) {
        for (i = 0; i < dep_bytes && dep_sw[i] == dep_hw[i]; i++)
            ;
        printf("  FAIL %s indexed buffers: a resident gather differs "
               "from a staged one, first at byte %lu (lane %lu, slot "
               "%lu)\n", cft_format_name(fmt), (unsigned long)i,
               (unsigned long)(i / esz / 2), (unsigned long)((i / esz) % 2));
        failures++;
        ok = 0;
    }
    /* ...and the answer is the gather's definition, so a run that
     * bound the wrong window cannot pass by agreeing with itself. */
    checks++;
    for (i = 0; i < n; i++) {
        const uint8_t *w0 = (ta[i] == CFT_IDX_NONE)
                          ? NULL : src + (size_t)ta[i] * esz;
        const uint8_t *w1 = (tsi[i] == CFT_IDX_NONE)
                          ? NULL : pool + (size_t)tsi[i] * esz;
        const uint8_t *g0 = dep_hw + (i * 2) * esz;
        const uint8_t *g1 = dep_hw + (i * 2 + 1) * esz;
        int bad0 = w0 ? (memcmp(g0, w0, esz) != 0) : !is_zero(g0, esz);
        int bad1 = w1 ? (memcmp(g1, w1, esz) != 0) : !is_zero(g1, esz);
        if (bad0 || bad1) {
            printf("  FAIL %s indexed buffers: lane %lu is not "
                   "source[idx] (idx_a %u, idx_si %u)\n",
                   cft_format_name(fmt), (unsigned long)i, ta[i], tsi[i]);
            failures++;
            ok = 0;
            break;
        }
    }

    /* A second run with no republish between, which is where residency
     * across calls shows: an input role's FIRST bind fills the device
     * copy and counts as staged, and only a later bind of the same
     * window counts resident. The tables are the buffers this leg
     * exists for - an integrator builds them once a step and runs many
     * times against them. */
    {
        cft_buffer_info bt, bs;
        uint64_t t_res = 0, s_res = 0;
        memset(dep_hw, 0x5a, dep_bytes);
        memset(rdep.p, 0x5a, dep_bytes);
        checks++;
        if (cft_program_run_ex(p_hw, &A) != CFT_OK ||
            cft_buffer_from_device(rdep.b) != CFT_OK) {
            printf("  FAIL %s indexed buffers: the second resident run "
                   "failed: %s\n", cft_format_name(fmt), cft_last_error());
            failures++;
            ok = 0;
        } else if (memcmp(dep_sw, rdep.p, dep_bytes) != 0) {
            printf("  FAIL %s indexed buffers: back-to-back resident "
                   "gathers drifted\n", cft_format_name(fmt));
            failures++;
            ok = 0;
        }
        memset(&bt, 0, sizeof bt); bt.struct_size = sizeof bt;
        memset(&bs, 0, sizeof bs); bs.struct_size = sizeof bs;
        /* On a device that reports resident buffers this check is
         * COUNTED whether or not the info calls succeed: a get_info
         * that failed inside one && chain would have removed the gate
         * silently (V1, 2026-09-15), and a gate that can vanish is the
         * shape that hides. On a staging backend it is not counted at
         * all, which is what keeps the count honest about what the
         * software backend can prove. */
        if (resident_expected) {
            int gt = cft_buffer_get_info(rta.b, &bt);
            int gs = cft_buffer_get_info(rsrc.b, &bs);
            checks++;
            if (gt != CFT_OK || gs != CFT_OK) {
                printf("  FAIL %s indexed buffers: this device reports "
                       "resident buffers, and cft_buffer_get_info failed "
                       "on the table (%d) or the source (%d), so the "
                       "binding could not be checked at all\n",
                       cft_format_name(fmt), gt, gs);
                failures++;
                ok = 0;
            } else {
                t_res = bt.resident_binds;
                s_res = bs.resident_binds;
                if (!t_res || !s_res) {
                    printf("  FAIL %s indexed buffers: this device "
                           "reports resident buffers, and the second run "
                           "bound the table %lu time(s) and the source "
                           "%lu time(s) - a table that is staged every "
                           "call is the round trip this feature exists "
                           "to remove\n",
                           cft_format_name(fmt), (unsigned long)t_res,
                           (unsigned long)s_res);
                    failures++;
                    ok = 0;
                }
            }
        }
        if (ok)
            printf("  %s indexed buffers: %lu lanes through a "
                   "%lu-element source and a %lu-element pool, resident "
                   "== staged, table binds %lu\n",
                   cft_format_name(fmt), (unsigned long)n,
                   (unsigned long)src_n, (unsigned long)pool_n,
                   (unsigned long)t_res);
    }
#undef IDXBUF_ARGS

done:
    (void)have;
    rbuf_free(&rsrc); rbuf_free(&rpool);
    rbuf_free(&rta);  rbuf_free(&rtsi);
    rbuf_free(&rdep);
    cft_program_free(p_sw);
    cft_program_free(p_hw);
    free(src); free(pool); free(dep_sw); free(dep_hw); free(ta); free(tsi);
}

static void compare_buffers_program(cft_device *sw, cft_device *hw,
                                    cft_format fmt, size_t n,
                                    int resident_expected)
{
    const size_t esz = cft_format_size(fmt);
    struct rbuf rin, rout, ra, rdep;
    uint8_t *a = NULL, *sin_h = NULL;
    uint8_t *dep_sw = NULL, *dep_hw = NULL;
    uint8_t *out_sw = NULL, *out_hw = NULL;
    cft_program *p_sw = NULL, *p_hw = NULL;
    uint8_t img[64];
    uint64_t ins[4];
    size_t bytes, blk = n * esz;
    uint32_t fl = 0, bus = 0;
    cft_run_args A;
    int ok = 1;

    ins[0] = seq_ldl(4, 0);                      /* r4 <- scratch[0] */
    ins[1] = seq_ctrl(3, 4, 0);                  /* deposit r4       */
    ins[2] = seq_stl(4, 0);                      /* scratch[0] <- r4 */
    ins[3] = seq_ctrl(0, 0, 0);                  /* halt             */
    bytes = seq_image_scratch(img, fmt, ins, 4, NULL, 0, 1,
                              CFT_PROG_FLAG_SCRATCH_IO, 1, 1);

    a      = (uint8_t *)malloc(blk);
    sin_h  = (uint8_t *)malloc(blk);
    dep_sw = (uint8_t *)malloc(blk);
    dep_hw = (uint8_t *)malloc(blk);
    out_sw = (uint8_t *)malloc(blk);
    out_hw = (uint8_t *)malloc(blk);
    if (!a || !sin_h || !dep_sw || !dep_hw || !out_sw || !out_hw) {
        printf("  FAIL %s program scratch: out of memory\n",
               cft_format_name(fmt));
        failures++;
        goto done_host;
    }
    fill_finite(a, fmt, n);
    fill_scratch_block(sin_h, fmt, n, 1);

    /* The staged reference, on the software backend. */
    if (cft_program_load(sw, img, bytes, &p_sw) != CFT_OK) {
        printf("  FAIL %s program scratch: the image did not load on "
               "software: %s\n", cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_host;
    }
    run_args_init(&A, a, dep_sw, n);
    A.scratch_in        = sin_h;
    A.scratch_in_bytes  = blk;
    A.scratch_out       = out_sw;
    A.scratch_out_bytes = blk;
    A.flags_out         = &fl;
    A.bus_out           = &bus;
    if (cft_program_run_ex(p_sw, &A) != CFT_OK) {
        printf("  FAIL %s program scratch: the software run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_host;
    }

    /* The resident run. Every operand-shaped buffer comes from
     * cft_alloc, so a device that binds binds all four. */
    if (!rbuf_alloc(hw, &ra, blk) || !rbuf_alloc(hw, &rdep, blk) ||
        !rbuf_alloc(hw, &rin, blk) || !rbuf_alloc(hw, &rout, blk)) {
        printf("  FAIL %s program scratch: cft_alloc\n",
               cft_format_name(fmt));
        failures++;
        goto done_all;
    }
    if (!rbuf_put(&ra, a, blk) || !rbuf_put(&rin, sin_h, blk)) {
        printf("  FAIL %s program scratch: publishing the inputs: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_all;
    }
    if (cft_program_load(hw, img, bytes, &p_hw) != CFT_OK) {
        printf("  FAIL %s program scratch: the image did not load on the "
               "device: %s\n", cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_all;
    }
    run_args_init(&A, ra.p, rdep.p, n);
    A.scratch_in        = rin.p;
    A.scratch_in_bytes  = blk;
    A.scratch_out       = rout.p;
    A.scratch_out_bytes = blk;
    A.flags_out         = &fl;
    A.bus_out           = &bus;
    if (cft_program_run_ex(p_hw, &A) != CFT_OK) {
        printf("  FAIL %s program scratch: the resident run failed: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_all;
    }
    /* A resident output is the device's until it is collected - the
     * whole point of the binding, and the step whose absence would
     * leave the comparison reading a stale mirror. */
    if (cft_buffer_from_device(rdep.b) != CFT_OK ||
        cft_buffer_from_device(rout.b) != CFT_OK) {
        printf("  FAIL %s program scratch: collecting the outputs: %s\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto done_all;
    }
    memcpy(dep_hw, rdep.p, blk);
    memcpy(out_hw, rout.p, blk);

    if (memcmp(dep_sw, dep_hw, blk)) {
        printf("  FAIL %s program scratch: the deposits differ between a "
               "staged run and a resident one\n", cft_format_name(fmt));
        failures++;
        ok = 0;
    }
    if (memcmp(out_sw, out_hw, blk)) {
        printf("  FAIL %s program scratch: the scratch-out block differs "
               "between a staged run and a resident one\n",
               cft_format_name(fmt));
        failures++;
        ok = 0;
    }

    /* Now the part that makes this a gate, and it needs a SECOND run.
     *
     * Identical bits prove nothing about where the block lived: staging
     * everything gives the same answer, which is the state this round
     * replaced. But an INPUT role's first bind legitimately counts as
     * staged - buf_bind must fill the device copy once - and only a
     * later bind of the same window counts resident. So the promise
     * under test is residency ACROSS CALLS, which is also the ask: an
     * integrator's state staying on the device through a corrector
     * pass.
     *
     * No republish between the two runs. cft_buffer_to_device bumps the
     * buffer's generation, and a bound window whose generation moved is
     * refilled - correctly, and it would mask exactly what is being
     * measured here. */
    {
        cft_buffer_info b1, b2;
        uint64_t in_res = 0, in_stg = 0, out_res = 0, out_stg = 0;
        uint8_t *dep2 = (uint8_t *)malloc(blk);
        uint8_t *out2 = (uint8_t *)malloc(blk);

        memset(&b1, 0, sizeof b1); b1.struct_size = sizeof b1;
        memset(&b2, 0, sizeof b2); b2.struct_size = sizeof b2;
        if (cft_buffer_get_info(rin.b, &b1) == CFT_OK)
            { in_res = b1.resident_binds; in_stg = b1.staged_binds; }
        if (cft_buffer_get_info(rout.b, &b2) == CFT_OK)
            { out_res = b2.resident_binds; out_stg = b2.staged_binds; }

        if (!dep2 || !out2) {
            printf("  FAIL %s program scratch: out of memory for the "
                   "second run\n", cft_format_name(fmt));
            failures++;
            ok = 0;
        } else if (cft_program_run_ex(p_hw, &A) != CFT_OK ||
                   cft_buffer_from_device(rdep.b) != CFT_OK ||
                   cft_buffer_from_device(rout.b) != CFT_OK) {
            printf("  FAIL %s program scratch: the second resident run "
                   "failed: %s\n", cft_format_name(fmt), cft_last_error());
            failures++;
            ok = 0;
        } else {
            memcpy(dep2, rdep.p, blk);
            memcpy(out2, rout.p, blk);
            if (memcmp(dep_hw, dep2, blk) || memcmp(out_hw, out2, blk)) {
                printf("  FAIL %s program scratch: back-to-back runs on "
                       "resident scratch drifted\n", cft_format_name(fmt));
                failures++;
                ok = 0;
            }
            memset(&b1, 0, sizeof b1); b1.struct_size = sizeof b1;
            memset(&b2, 0, sizeof b2); b2.struct_size = sizeof b2;
            if (resident_expected &&
                cft_buffer_get_info(rin.b, &b1) == CFT_OK &&
                cft_buffer_get_info(rout.b, &b2) == CFT_OK) {
                if (b1.resident_binds <= in_res || b1.staged_binds != in_stg) {
                    printf("  FAIL %s program scratch: the second run did "
                           "not serve scratch-in from the device copy "
                           "(resident %lu -> %lu, staged %lu -> %lu%s%s)\n",
                           cft_format_name(fmt),
                           (unsigned long)in_res,
                           (unsigned long)b1.resident_binds,
                           (unsigned long)in_stg,
                           (unsigned long)b1.staged_binds,
                           b1.staged_why[0] ? " - " : "",
                           b1.staged_why[0] ? b1.staged_why : "");
                    failures++;
                    ok = 0;
                }
                if (b2.resident_binds <= out_res ||
                    b2.staged_binds != out_stg) {
                    printf("  FAIL %s program scratch: the second run did "
                           "not serve scratch-out from the device copy "
                           "(resident %lu -> %lu, staged %lu -> %lu%s%s)\n",
                           cft_format_name(fmt),
                           (unsigned long)out_res,
                           (unsigned long)b2.resident_binds,
                           (unsigned long)out_stg,
                           (unsigned long)b2.staged_binds,
                           b2.staged_why[0] ? " - " : "",
                           b2.staged_why[0] ? b2.staged_why : "");
                    failures++;
                    ok = 0;
                }
            }
        }
        free(out2);
        free(dep2);
    }

    note_binds(&ra);
    note_binds(&rdep);
    note_binds(&rin);
    note_binds(&rout);
    if (ok)
        printf("    %-5s program scratch: %lu lanes, deposits and the "
               "scratch-out block identical staged and resident\n",
               cft_format_name(fmt), (unsigned long)n);

done_all:
    cft_program_free(p_hw);
    rbuf_free(&rout);
    rbuf_free(&rin);
    rbuf_free(&rdep);
    rbuf_free(&ra);
done_host:
    cft_program_free(p_sw);
    free(out_hw); free(out_sw);
    free(dep_hw); free(dep_sw);
    free(sin_h);  free(a);
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

/* ---------------------------------------------------------------
 * The stale-copy class (verifier-V7, 2026-09-25).
 *
 * A resident buffer's device copy must never be served once the mirror
 * under it has changed, and a mirror a run has left stale must never be
 * read. Every path that reads or writes the mirror ON THE HOST keeps
 * that now - the entry points computed on the host, a reduction's
 * result, a program's counts, a staged output, a publish - and until
 * 2026-09-25 none of them did: V7's harness, the same public calls on
 * the software device and on a mock of XRT, got wrong answers with
 * CFT_OK from every one.
 *
 * Each scenario runs on the software device and on `hw` into a fresh
 * resident buffer B, and the two TRANSCRIPTS are compared byte for byte:
 * every status, every flag word, every output a run or an entry point
 * produced, and B brought home at the end. A "read" of B is a device
 * run, copysign(B, B) - bit for bit B, NaN payloads included - so a
 * stale copy shows. Each entry point computed on the host is held both
 * ways, and in place where that is legal:
 *   IN       a device run writes B, then the entry point reads it;
 *   OUT      a device run reads B (filling a copy), the entry point
 *            writes it, a device run reads it again;
 *   in place a read, the entry point from B into B, a read;
 * and V7's own sequences are run as it wrote them. On the software
 * backend B is plain memory and every scenario agrees by construction,
 * which proves the harness; the device is the test.
 * --------------------------------------------------------------- */
enum {
    SH_EXP, SH_POW, SH_POWN, SH_RINT, SH_NEXTUP, SH_LOGB, SH_SCALEB_HOST,
    SH_SCALEB_DEV, SH_REM, SH_CONVERT, SH_CVT_TO, SH_CVT_FROM, SH_CLASS,
    SH_TORDER, SH_MINMAG, SH_CMPSIG, SH_AUG_R, SH_AUG_E, SH_AUG_SUB,
    SH_FO_NARROW, SH_FO_WIDE, SH_DIV, SH_SQRT, SH_PAYLOAD, SH_SETPAY,
    SH_TODEC, SH_FROMDEC, SH_SCALED, SH_REDUCE, SH_REDUCE_SEG,
    SH_DIV_FULL, SH_SQRT_FULL, SH_NEXTDOWN, SH_TOHEX, SH_COUNT
};
static const char *const sh_name[SH_COUNT] = {
    "cft_exp", "cft_pow", "cft_pown", "cft_rint", "cft_next_up",
    "cft_logb", "cft_scaleb, the host route", "cft_scaleb, the composed route",
    "cft_rem", "cft_convert", "cft_cvt_to_i32", "cft_cvt_from_i32",
    "cft_class", "cft_total_order", "cft_min_mag", "cft_cmp_sig",
    "cft_augmented_add's r", "cft_augmented_add's e", "cft_augmented_sub",
    "cft_formatof_add, narrowing", "cft_formatof_add, widening", "cft_div",
    "cft_sqrt", "cft_get_payload", "cft_set_payload", "cft_to_decimal_char",
    "cft_from_decimal_char", "cft_scaled_prod", "cft_reduce",
    "cft_reduce_seg", "cft_div, CFT_DIVSQRT_FULL=1",
    "cft_sqrt, CFT_DIVSQRT_FULL=1", "cft_next_down", "cft_to_hex_char"
};
enum { SD_IN, SD_OUT, SD_INPLACE };
static const char *const sd_name[3] = {"IN", "OUT", "in place"};
enum {
    SV_RSEG, SV_RSEG_BACK, SV_RED, SV_COUNTS, SV_WITNESS, SV_RSEG_DIRTY,
    SV_MASKED, SV_PUBLISH, SV_RWR, SV_RED_TWICE, SV_RSEG_TWICE,
    SV_COUNTS_TWICE, SV_N6, SV_RED_DIRTY, SV_COUNTS_DIRTY, SV_DEP_OUT,
    SV_SO_OUT, SV_BANK, SV_DIGEST, SV_IMAGE, SV_STRINGS, SV_IDX_BAD,
    SV_IDX_GOOD, SV_IDX_PROG, SV_IDX_SI, SV_SCALAR, SV_DIGEST_OUT, SV_CONF,
    SV_DIGEST_DIRTY, SV_CONF_DIRTY, SV_COUNT
};
static const char *const sv_name[SV_COUNT] = {
    "S1: a read, cft_reduce_seg into B, a read",
    "S1b: S1 with a read-back before the second read",
    "S2: a read, cft_reduce into an element of B, a read",
    "S3: a read, a program's counts into B, a read",
    "S5: a read, a run into B, a run into half of it refused before its "
    "start, a read",
    "S6: a run into B, cft_reduce_seg into it, the read-back",
    "S7: a masked program into B refused after its fill, cft_reduce_seg "
    "into it, the masked program again",
    "a run into B, a publish before any read-back (refused on a card), a "
    "read",
    "a read, a run into B, a read",
    "cft_reduce of B into an element of B, then of B again",
    "cft_reduce_seg of B into B, then of B again",
    "a program reading B with its counts into B, then again",
    "N6: a run into B, the caller's rewrite, a publish (refused on a card), "
    "a read-back, the rewrite again, a publish, a read",
    "a run into B, cft_reduce into an element of it, the read-back",
    "a run into B, a program's counts into it, the read-back",
    "a read, a program's deposits into B, a read",
    "a read, a program's scratch-out into B, a read",
    "N2: a run writes a program's constant bank into B, the program run "
    "with it",
    "N2: a run writes a constant bank into B, cft_program_digest over it",
    "N2: a run writes a program image into B, cft_program_load from it, "
    "the program run",
    "N3: a run writes decimal strings into B, cft_from_decimal_char on them",
    "V9: a run writes an index table with an entry past its source over an "
    "in-range mirror, cft_run_ex gathers through it",
    "V9: a run writes an in-range index table over a mirror with an entry "
    "past its source, cft_run_ex gathers through it",
    "V9: a run writes an index table with an entry past its source, a "
    "program run gathers through it",
    "V9: a run writes a scratch-in index table with an entry past its pool, "
    "a program run gathers through it",
    "V9: a run writes a scalar into B, cft_run_ex's composed route adds it",
    "V9: a read, cft_program_digest into B, a read",
    "V9: a read, cft_conformance's report into B, a read",
    "V9: a run into B, cft_program_digest into it, the read-back",
    "V9: a run into B, cft_conformance's report into it, the read-back"
};
static const char *const stale_texts[8] = {
    "1.5", "-2.25e3", "7e-3", "0", "-0", "3.14159", "1e10", "-9.5e-7"
};

struct stale {
    cft_device *dev;
    cft_format fmt;
    size_t n, esz;
    int plants;                 /* CFT_XRT_WITNESS plants take effect */
    int card_refuses;           /* the reference records the refusal a
                                 * card gives a publish over unread run
                                 * results (Logan's rule, 2026-09-26) */
    struct rbuf B;
    const uint8_t *x, *y, *z, *init, *mask;
    const int64_t *i64;
    const int32_t *i32;
    uint8_t *out, *dep, *e;     /* this device's plain outputs */
    uint32_t *cnt;
    cft_program *prog, *prog_so, *prog_bank;
    cft_program *prog_si;       /* deposits scratch slot 0: a gather */
    uint8_t *img1;              /* the one-deposit program's image */
    size_t img1_bytes;
    uint8_t *tr;
    size_t trn, trcap;
    int oom;
};

static void st_rec(struct stale *s, const void *p, size_t bytes)
{
    if (s->trn + bytes > s->trcap) {
        size_t cap = s->trcap ? s->trcap : 4096;
        uint8_t *q;
        while (cap < s->trn + bytes)
            cap *= 2;
        q = (uint8_t *)realloc(s->tr, cap);
        if (!q) {
            s->oom = 1;
            return;
        }
        s->tr = q;
        s->trcap = cap;
    }
    memcpy(s->tr + s->trn, p, bytes);
    s->trn += bytes;
}

static void st_status(struct stale *s, cft_status st)
{
    const int32_t v = (int32_t)st;
    st_rec(s, &v, sizeof v);
}

/* A device run READS B - copysign(B, B), which is B bit for bit. */
static void st_read(struct stale *s)
{
    uint32_t fl = 0, bus = 0;
    memset(s->out, 0, s->n * s->esz);
    st_status(s, cft_run(s->dev, CFT_COPYSIGN, s->fmt, CFT_RNE, s->B.p,
                         s->B.p, NULL, s->out, s->n, &fl, &bus));
    st_rec(s, s->out, s->n * s->esz);
}

/* A device run WRITES B - x + y, left on the device. */
static void st_write(struct stale *s)
{
    uint32_t fl = 0, bus = 0;
    st_status(s, cft_run(s->dev, CFT_ADD, s->fmt, CFT_RNE, s->x, NULL, s->y,
                         s->B.p, s->n, &fl, &bus));
}

static void st_reduce_seg(struct stale *s)
{
    uint32_t fl = 0, bus = 0;
    st_status(s, cft_reduce_seg(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->x, NULL,
                                s->B.p, s->n, 8, &fl, &bus));
    st_rec(s, &fl, sizeof fl);
}

/* The one-deposit program: deposits a, so a kept lane's slot is x. */
static void st_program(struct stale *s, int masked, uint8_t *deposits,
                       uint32_t *counts, int planted)
{
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    cft_status st = CFT_ERR_INTERNAL;
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = s->x;
    A.n = s->n;
    A.deposits = deposits;
    A.counts = counts;
    if (masked) {
        A.lane_mask = s->mask;
        A.lane_mask_bytes = (s->n + 7) / 8;
    }
    A.flags_out = &fl;
    A.bus_out = &bus;
    /* A planted refusal happens on the device only: the software backend
     * has no tile, and its transcript records the refusal the device
     * must give. */
    if (!planted || s->plants) {
        if (planted)
            put_env("CFT_XRT_WITNESS", "busy-before");
        st = cft_program_run_ex(s->prog, &A);
        if (planted)
            put_env("CFT_XRT_WITNESS", NULL);
    }
    st_status(s, st);
}

/* A publish of B that a card REFUSES when a run's results in B are
 * unread (`over_unread`; Logan's rule, 2026-09-26). The software backend
 * accepts every publish, so the reference records the refusal the card
 * must give; the call changes nothing where it is refused. */
static void st_publish(struct stale *s, int over_unread)
{
    cft_status st = cft_buffer_to_device(s->B.b);
    if (over_unread && s->card_refuses && st == CFT_OK)
        st = CFT_ERR_INVALID_ARGUMENT;
    st_status(s, st);
}

/* A DEVICE run writes `bytes` of payload into B: the one-deposit
 * program over a lane-sized copy of it, deposits into B, so every byte
 * lands exactly as given. The host reads it next - which is the case a
 * stale mirror would get wrong. */
static void st_devcopy(struct stale *s, const uint8_t *payload, size_t bytes)
{
    uint8_t *lanes = (uint8_t *)calloc(s->n, s->esz);
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    if (!lanes) {
        s->oom = 1;
        return;
    }
    memcpy(lanes, payload, bytes < s->n * s->esz ? bytes : s->n * s->esz);
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = lanes;
    A.n = s->n;
    A.deposits = s->B.p;
    A.counts = s->cnt;
    A.flags_out = &fl;
    A.bus_out = &bus;
    st_status(s, cft_program_run_ex(s->prog, &A));
    free(lanes);
}

/* The scratch-out program: deposits a and stores it to slot 0 of its
 * scratch-out block, which is B. */
static void st_program_so(struct stale *s)
{
    cft_run_args A;
    uint32_t fl = 0, bus = 0;
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = s->x;
    A.n = s->n;
    A.deposits = s->dep;
    A.counts = s->cnt;
    A.scratch_out = s->B.p;
    A.scratch_out_bytes = s->n * s->esz;
    A.flags_out = &fl;
    A.bus_out = &bus;
    st_status(s, cft_program_run_ex(s->prog_so, &A));
    st_rec(s, s->dep, s->n * s->esz);
}

/* One call of entry point `fn`: reading B (IN, in place) or x, writing B
 * (OUT, in place) or this device's plain `out`. What it wrote to plain
 * memory is recorded; what it wrote to B is seen by the read after. */
static void st_host(struct stale *s, int fn, int dir)
{
    const size_t n = s->n, esz = s->esz;
    const cft_format fmt = s->fmt;
    const uint8_t *a = dir == SD_OUT ? s->x : s->B.p;
    uint8_t *d = dir == SD_IN ? s->out : s->B.p;
    uint32_t fl = 0, bus = 0;
    int64_t sc = 0;
    size_t len = 0, bad = 0;
    cft_status st;

    memset(s->out, 0, n * esz);
    memset(s->e, 0, n * esz);
    switch (fn) {
    case SH_EXP:
        st = cft_exp(s->dev, fmt, CFT_RNE, a, d, n, &fl);
        break;
    case SH_POW:
        st = cft_pow(s->dev, fmt, CFT_RNE, a, s->y, d, n, &fl);
        break;
    case SH_POWN:           /* here the integer operand is the one in B */
        st = dir == SD_OUT
                 ? cft_pown(s->dev, fmt, CFT_RNE, s->x, s->i64, d, n, &fl)
                 : cft_pown(s->dev, fmt, CFT_RNE, s->x,
                            (const int64_t *)(const void *)s->B.p, d,
                            n * esz / 8 < n ? n * esz / 8 : n, &fl);
        break;
    case SH_RINT:
        st = cft_rint(s->dev, fmt, CFT_RNE, 1, a, d, n, &fl, &bus);
        break;
    case SH_NEXTUP:
        st = cft_next_up(s->dev, fmt, a, d, n, &fl);
        break;
    case SH_LOGB:
        st = cft_logb(s->dev, fmt, a, d, n, &fl);
        break;
    case SH_SCALEB_HOST:    /* below every subnormal: packed on the host */
        st = cft_scaleb(s->dev, fmt, CFT_RNE, a, -((int64_t)1 << 40), d, n,
                        &fl, &bus);
        break;
    case SH_SCALEB_DEV:     /* multiplies by 2^3 on the device */
        st = cft_scaleb(s->dev, fmt, CFT_RNE, a, 3, d, n, &fl, &bus);
        break;
    case SH_REM:
        st = cft_rem(s->dev, fmt, a, s->y, d, n, &fl);
        break;
    case SH_CONVERT:
        st = cft_convert(s->dev, fmt, fmt, CFT_RNE, a, d, n, &fl);
        break;
    case SH_CVT_TO:
        st = cft_cvt_to_i32(s->dev, fmt, CFT_RNE, 0, a,
                            (int32_t *)(void *)d, n, &fl);
        break;
    case SH_CVT_FROM:       /* here the integers are the ones in B */
        st = cft_cvt_from_i32(s->dev, fmt, CFT_RNE,
                              dir == SD_OUT
                                  ? s->i32
                                  : (const int32_t *)(const void *)s->B.p,
                              d, n, &fl);
        break;
    case SH_CLASS:
        st = cft_class(s->dev, fmt, a, d, n);
        break;
    case SH_TORDER:
        st = cft_total_order(s->dev, fmt, a, s->y, d, n);
        break;
    case SH_MINMAG:
        st = cft_min_mag(s->dev, fmt, a, s->y, d, n, &fl);
        break;
    case SH_CMPSIG:
        st = cft_cmp_sig(s->dev, CFT_CMPLT, fmt, a, s->y, d, n, &fl, &bus);
        break;
    case SH_AUG_R:
        st = cft_augmented_add(s->dev, fmt, a, s->y, d, s->e, n, &fl);
        break;
    case SH_AUG_E:
        st = cft_augmented_add(s->dev, fmt, a, s->y, s->e, d, n, &fl);
        break;
    case SH_AUG_SUB:
        st = cft_augmented_sub(s->dev, fmt, a, s->y, d, s->e, n, &fl);
        break;
    case SH_FO_NARROW:
        st = cft_formatof_add(s->dev, fmt, (cft_format)(fmt - 1), CFT_RNE, a,
                              s->y, d, n, &fl, &bus);
        break;
    case SH_FO_WIDE:        /* half the elements: the results are twice as wide */
        st = cft_formatof_add(s->dev, fmt, (cft_format)(fmt + 1), CFT_RNE, a,
                              s->y, d, n / 2, &fl, &bus);
        break;
    case SH_DIV:
        st = cft_div(s->dev, fmt, CFT_RNE, a, s->y, d, n, &fl, &bus);
        break;
    case SH_SQRT:
        st = cft_sqrt(s->dev, fmt, CFT_RNE, a, d, n, &fl, &bus);
        break;
    case SH_PAYLOAD:
        st = cft_get_payload(s->dev, fmt, a, d, n);
        break;
    case SH_SETPAY:
        st = cft_set_payload(s->dev, fmt, a, d, n);
        break;
    case SH_TODEC:
        st = cft_to_decimal_char(s->dev, fmt, CFT_RNE, a, 17, (char *)d,
                                 n * esz, &len, &fl);
        break;
    case SH_FROMDEC: {
        const char *in[64];
        size_t i;
        for (i = 0; i < n && i < 64; i++)
            in[i] = stale_texts[i % 8];
        st = cft_from_decimal_char(s->dev, fmt, CFT_RNE, in, d,
                                   n < 64 ? n : 64, &bad, &fl);
        break;
    }
    case SH_SCALED:
        st = cft_scaled_prod(s->dev, fmt, CFT_RNE, a,
                             dir == SD_IN ? s->out : s->B.p + 3 * esz,
                             dir == SD_IN
                                 ? &sc
                                 : (int64_t *)(void *)(s->B.p + 8 * esz),
                             n, &fl);
        break;
    case SH_REDUCE:
        st = cft_reduce(s->dev, CFT_SUM, fmt, CFT_RNE, a, NULL,
                        dir == SD_IN ? s->out : s->B.p + 5 * esz, n, &fl,
                        &bus);
        break;
    case SH_REDUCE_SEG:
        st = cft_reduce_seg(s->dev, CFT_SUM, fmt, CFT_RNE, a, NULL, d, n, 8,
                            &fl, &bus);
        break;
    case SH_NEXTDOWN:
        st = cft_next_down(s->dev, fmt, a, d, n, &fl);
        break;
    case SH_TOHEX:
        st = cft_to_hex_char(s->dev, fmt, a, (char *)d, n * esz, &len);
        break;
    default:                /* SH_DIV_FULL, SH_SQRT_FULL */
        put_env("CFT_DIVSQRT_FULL", "1");
        st = fn == SH_DIV_FULL
                 ? cft_div(s->dev, fmt, CFT_RNE, a, s->y, d, n, &fl, &bus)
                 : cft_sqrt(s->dev, fmt, CFT_RNE, a, d, n, &fl, &bus);
        put_env("CFT_DIVSQRT_FULL", NULL);
        break;
    }
    st_status(s, st);
    st_rec(s, &fl, sizeof fl);
    st_rec(s, &len, sizeof len);
    st_rec(s, &bad, sizeof bad);
    st_rec(s, &sc, sizeof sc);
    st_rec(s, s->out, n * esz);
    st_rec(s, s->e, n * esz);
}

/* An index table of n entries (n is 64 here), each in range for a source
 * of n elements - or, with `bad`, entry 5 past its end. */
static void st_table(uint32_t *t, size_t n, int bad)
{
    size_t i;
    for (i = 0; i < n; i++)
        t[i] = (uint32_t)((i * 7 + 1) % n);
    if (bad)
        t[5] = (uint32_t)(n + 3);
}

/* Verifier-V9's (b)1: B's MIRROR is published holding one table, then a
 * device run writes the other into B - so a bound check made on the
 * mirror judges the wrong table. `mirror_bad` picks which is which. */
static void st_tables(struct stale *s, int mirror_bad)
{
    uint32_t t[64];
    st_table(t, s->n, mirror_bad);
    memcpy(s->B.p, t, s->n * 4);
    st_publish(s, 0);
    st_table(t, s->n, !mirror_bad);
    st_devcopy(s, (const uint8_t *)t, s->n * 4);
}

static void st_seq(struct stale *s, int which)
{
    const size_t esz = s->esz;
    uint32_t fl = 0, bus = 0;

    switch (which) {
    case SV_RSEG:
        st_read(s);
        st_reduce_seg(s);
        st_read(s);
        break;
    case SV_RSEG_BACK:
        st_read(s);
        st_reduce_seg(s);
        st_status(s, cft_buffer_from_device(s->B.b));
        st_read(s);
        break;
    case SV_RED:
        st_read(s);
        st_status(s, cft_reduce(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->x, NULL,
                                s->B.p + 5 * esz, s->n, &fl, &bus));
        st_read(s);
        break;
    case SV_COUNTS:
        st_read(s);
        st_program(s, 0, s->dep, (uint32_t *)(void *)s->B.p, 0);
        st_rec(s, s->dep, s->n * esz);
        st_read(s);
        break;
    case SV_WITNESS: {
        cft_status st = CFT_ERR_INTERNAL;
        st_read(s);
        st_write(s);
        if (s->plants) {
            put_env("CFT_XRT_WITNESS", "busy-before");
            st = cft_run(s->dev, CFT_ADD, s->fmt, CFT_RNE, s->y, NULL, s->x,
                         s->B.p, s->n / 2, &fl, &bus);
            put_env("CFT_XRT_WITNESS", NULL);
        }
        st_status(s, st);
        st_read(s);
        break;
    }
    case SV_RSEG_DIRTY:
        st_write(s);
        st_reduce_seg(s);
        break;
    case SV_MASKED:
        st_program(s, 1, s->B.p, s->cnt, 1);
        st_reduce_seg(s);
        st_program(s, 1, s->B.p, s->cnt, 0);
        st_rec(s, s->cnt, s->n * sizeof *s->cnt);
        break;
    case SV_PUBLISH:        /* refused on a card, and changes nothing */
        st_write(s);
        st_publish(s, 1);
        st_read(s);
        break;
    case SV_N6:             /* verifier-V8: the caller rewrites what a run
                             * wrote - the publish that would have kept one
                             * side's bytes by guessing is refused; read back,
                             * the rewrite stands */
        st_write(s);
        memcpy(s->B.p, s->y, s->n * esz);
        st_publish(s, 1);
        st_status(s, cft_buffer_from_device(s->B.b));
        memcpy(s->B.p, s->y, s->n * esz);
        st_publish(s, 0);
        st_read(s);
        break;
    case SV_RED_DIRTY:      /* the host writes into a window a run left dirty */
        st_write(s);
        st_status(s, cft_reduce(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->x, NULL,
                                s->B.p + 5 * esz, s->n, &fl, &bus));
        break;
    case SV_COUNTS_DIRTY:
        st_write(s);
        st_program(s, 0, s->dep, (uint32_t *)(void *)s->B.p, 0);
        st_rec(s, s->dep, s->n * esz);
        break;
    case SV_DEP_OUT:        /* B as a program's deposit window */
        st_read(s);
        st_program(s, 0, s->B.p, s->cnt, 0);
        st_rec(s, s->cnt, s->n * sizeof *s->cnt);
        st_read(s);
        break;
    case SV_SO_OUT:         /* B as a program's scratch-out block */
        st_read(s);
        st_program_so(s);
        st_read(s);
        break;
    case SV_BANK: {         /* r4 = r0 * k0 + k1, both from B */
        uint32_t f2 = 0;
        st_devcopy(s, s->x + 7 * esz, 2 * esz);
        st_status(s, cft_program_run_bank(s->prog_bank, s->B.p, 2 * esz,
                                          s->x, NULL, NULL, s->dep, s->cnt,
                                          s->n, &f2, NULL));
        st_rec(s, s->dep, s->n * esz);
        break;
    }
    case SV_DIGEST: {
        uint8_t dg[32];
        memset(dg, 0, sizeof dg);
        st_devcopy(s, s->y + 3 * esz, 2 * esz);
        st_status(s, cft_program_digest(s->prog_bank, s->B.p, 2 * esz, dg));
        st_rec(s, dg, sizeof dg);
        break;
    }
    case SV_IMAGE: {
        cft_program *p2 = NULL;
        cft_status st;
        st_devcopy(s, s->img1, s->img1_bytes);
        st = cft_program_load(s->dev, s->B.p, s->img1_bytes, &p2);
        st_status(s, st);
        if (st == CFT_OK) {
            cft_run_args A;
            uint32_t f2 = 0, b2 = 0;
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = s->y;
            A.n = s->n;
            A.deposits = s->dep;
            A.counts = s->cnt;
            A.flags_out = &f2;
            A.bus_out = &b2;
            st_status(s, cft_program_run_ex(p2, &A));
            st_rec(s, s->dep, s->n * esz);
        }
        cft_program_free(p2);
        break;
    }
    case SV_IDX_BAD:        /* the device's table is past its source */
    case SV_IDX_GOOD: {     /* the mirror's is */
        cft_elem_args E;
        uint32_t f2 = 0, b2 = 0;
        st_tables(s, which == SV_IDX_GOOD);
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = s->x;
        E.c = s->y;
        E.d = s->out;
        E.n = s->n;
        E.idx_a = (const uint32_t *)(const void *)s->B.p;
        E.idx_a_src = s->n;
        E.flags_out = &f2;
        E.bus_out = &b2;
        memset(s->out, 0, s->n * esz);
        st_status(s, cft_run_ex(s->dev, CFT_ADD, s->fmt, CFT_RNE, &E));
        st_rec(s, s->out, s->n * esz);
        st_rec(s, &f2, sizeof f2);
        break;
    }
    case SV_IDX_PROG:
    case SV_IDX_SI: {
        cft_run_args A;
        uint32_t f2 = 0, b2 = 0;
        st_tables(s, 0);
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = s->x;
        A.n = s->n;
        A.deposits = s->dep;
        A.counts = s->cnt;
        A.flags_out = &f2;
        A.bus_out = &b2;
        if (which == SV_IDX_PROG) {
            A.idx_a = (const uint32_t *)(const void *)s->B.p;
            A.idx_a_src = s->n;
        } else {
            A.scratch_in = s->y;
            A.scratch_in_bytes = s->n * esz;
            A.idx_scratch_in = (const uint32_t *)(const void *)s->B.p;
            A.idx_scratch_src = s->n;
        }
        st_status(s, cft_program_run_ex(which == SV_IDX_PROG ? s->prog
                                                             : s->prog_si,
                                        &A));
        st_rec(s, s->dep, s->n * esz);
        break;
    }
    case SV_SCALAR: {       /* V9's (b)2: B[0] is y[0] on the device */
        cft_elem_args E;
        uint32_t t[64], f2 = 0, b2 = 0;
        st_table(t, s->n, 0);
        st_devcopy(s, s->y, esz);
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = s->x;
        E.c = s->B.p;
        E.d = s->out;
        E.n = s->n;
        E.scalar_mask = 4u;                         /* c */
        E.idx_a = t;
        E.idx_a_src = s->n;
        E.flags_out = &f2;
        E.bus_out = &b2;
        memset(s->out, 0, s->n * esz);
        st_status(s, cft_run_ex(s->dev, CFT_ADD, s->fmt, CFT_RNE, &E));
        st_rec(s, s->out, s->n * esz);
        st_rec(s, &f2, sizeof f2);
        break;
    }
    case SV_DIGEST_OUT:     /* V9's (b)3: 32 bytes written on the host */
        st_read(s);
        st_status(s, cft_program_digest(s->prog, NULL, 0, s->B.p + 8));
        st_read(s);
        break;
    case SV_CONF: {         /* V9's (b)4: no sets there, so the report says
                             * so - the same sentence on both devices */
        uint64_t cases = 0;
        st_read(s);
        st_status(s, cft_conformance(s->dev, "device-test: no vector sets "
                                     "here", (char *)s->B.p, s->n * esz,
                                     &cases));
        st_rec(s, &cases, sizeof cases);
        st_read(s);
        break;
    }
    /* ...and the other way (V9's second pass): a run leaves B dirty, then
     * the host writes over part of it - the run's bytes must come home
     * first, and the write must stand at the read-back that ends every
     * transcript */
    case SV_DIGEST_DIRTY:
        st_write(s);
        st_status(s, cft_program_digest(s->prog, NULL, 0, s->B.p + 8));
        break;
    case SV_CONF_DIRTY: {
        uint64_t cases = 0;
        st_write(s);
        st_status(s, cft_conformance(s->dev, "device-test: no vector sets "
                                     "here", (char *)s->B.p, s->n * esz,
                                     &cases));
        st_rec(s, &cases, sizeof cases);
        break;
    }
    default: {              /* SV_STRINGS */
        char text[256];
        const char *in[8];
        size_t pos = 0, k2, bad = 0;
        uint32_t f2 = 0;
        memset(text, 0, sizeof text);
        for (k2 = 0; k2 < 8; k2++) {
            size_t len = strlen(stale_texts[k2]) + 1;
            memcpy(text + pos, stale_texts[k2], len);
            pos += len;
        }
        st_devcopy(s, (const uint8_t *)text, pos);
        for (k2 = 0, pos = 0; k2 < 8; k2++) {
            in[k2] = (const char *)s->B.p + pos;
            pos += strlen(stale_texts[k2]) + 1;
        }
        memset(s->out, 0, s->n * esz);
        st_status(s, cft_from_decimal_char(s->dev, s->fmt, CFT_RNE, in,
                                           s->out, 8, &bad, &f2));
        st_rec(s, s->out, 8 * esz);
        st_rec(s, &bad, sizeof bad);
        break;
    }
    case SV_RWR:            /* a flush must stale the copies it moves under */
        st_read(s);
        st_write(s);
        st_read(s);
        break;
    /* A result written on the host into the very array the call read on
     * the device - legal, and the case the after-write note exists for:
     * the call filled a copy over bytes it then wrote, and the second
     * call binds the same window. */
    case SV_RED_TWICE:
        st_status(s, cft_reduce(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->B.p,
                                NULL, s->B.p + 5 * esz, s->n, &fl, &bus));
        st_status(s, cft_reduce(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->B.p,
                                NULL, s->out, s->n, &fl, &bus));
        st_rec(s, s->out, esz);
        break;
    case SV_RSEG_TWICE:
        st_status(s, cft_reduce_seg(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->B.p,
                                    NULL, s->B.p, s->n, 8, &fl, &bus));
        st_status(s, cft_reduce_seg(s->dev, CFT_SUM, s->fmt, CFT_RNE, s->B.p,
                                    NULL, s->out, s->n, 8, &fl, &bus));
        st_rec(s, s->out, (s->n / 8) * esz);
        break;
    case SV_COUNTS_TWICE: {
        const uint8_t *keep = s->x;
        s->x = s->B.p;      /* the program's stream a is B */
        st_program(s, 0, s->dep, (uint32_t *)(void *)s->B.p, 0);
        st_rec(s, s->dep, s->n * esz);
        st_program(s, 0, s->dep, s->cnt, 0);
        st_rec(s, s->dep, s->n * esz);
        s->x = keep;
        break;
    }
    }
}

/* One scenario on both devices, into a fresh B each; 1 if the
 * transcripts agree. B brought home ends every transcript. */
static int stale_one(struct stale *S, int is_host, int which, int dir,
                     const char *label, int decline)
{
    size_t i;
    int k;
    /* CFT_XRT_BIND=decline-outputs: every resident OUTPUT bind of the card
     * declines and is staged, so the staged collects that write B's
     * mirror are exercised; the software backend never reads it. */
    if (decline)
        put_env("CFT_XRT_BIND", "decline-outputs");
    for (k = 0; k < 2; k++) {
        struct stale *s = &S[k];
        s->trn = 0;
        s->oom = 0;
        /* the plain outputs start the same on both devices: a masked
         * lane's count is the caller's, and must be a known one */
        memset(s->out, 0, s->n * s->esz);
        memset(s->dep, 0x5c, s->n * s->esz);
        memset(s->e, 0, s->n * s->esz);
        memset(s->cnt, 0xa5, s->n * sizeof *s->cnt);
        if (!rbuf_alloc(s->dev, &s->B, s->n * s->esz)) {
            s->oom = 1;
            continue;
        }
        memcpy(s->B.p, s->init, s->n * s->esz);
        st_status(s, cft_buffer_to_device(s->B.b));
        if (is_host) {
            if (dir == SD_IN)
                st_write(s);
            else
                st_read(s);
            st_host(s, which, dir);
            if (dir != SD_IN)
                st_read(s);
        } else {
            st_seq(s, which);
        }
        st_status(s, cft_buffer_from_device(s->B.b));
        st_rec(s, s->B.p, s->n * s->esz);
        rbuf_free(&s->B);
    }
    if (decline)
        put_env("CFT_XRT_BIND", NULL);
    checks++;
    if (S[0].oom || S[1].oom) {
        printf("  FAIL stale copies (%s), %s: out of memory\n",
               cft_format_name(S[0].fmt), label);
        failures++;
        return 0;
    }
    if (S[0].trn == S[1].trn && !memcmp(S[0].tr, S[1].tr, S[0].trn))
        return 1;
    for (i = 0; i < S[0].trn && i < S[1].trn && S[0].tr[i] == S[1].tr[i];
         i++)
        ;
    printf("  FAIL stale copies (%s), %s: the device's transcript leaves the "
           "software backend's at byte %lu of %lu (the device's has %lu)\n",
           cft_format_name(S[0].fmt), label, (unsigned long)i,
           (unsigned long)S[0].trn, (unsigned long)S[1].trn);
    failures++;
    return 0;
}

/* Whether `hw` can take entry point `fn` at `fmt` the way the software
 * backend does - a composed one needs its passes' opcodes, and a
 * reduction per segment its feature bit. -1 for a case that does not
 * exist at this format at all (no narrower or wider format), which is
 * nobody's limit and so is skipped without a line. */
static int stale_host_ok(cft_device *hw, const cft_caps *hc, int fn,
                         cft_format fmt)
{
    if ((fn == SH_FO_NARROW && fmt == CFT_FP32) ||
        (fn == SH_FO_WIDE && fmt == CFT_FP256))
        return -1;
    switch (fn) {
    case SH_RINT:
        return cft_supports(hw, CFT_ADD, fmt) &&
               cft_supports(hw, CFT_COPYSIGN, fmt);
    case SH_SCALEB_DEV:
        return cft_supports(hw, CFT_MUL, fmt);
    case SH_CMPSIG:
        return cft_supports(hw, CFT_CMPLT, fmt);
    case SH_FO_WIDE:
        return cft_supports(hw, CFT_ADD, (cft_format)(fmt + 1));
    case SH_DIV:
    case SH_DIV_FULL:
        return cft_supports(hw, CFT_FMA, fmt) &&
               cft_supports(hw, CFT_NEG, fmt) &&
               cft_supports(hw, CFT_RECIP_SEED, fmt);
    case SH_SQRT:
    case SH_SQRT_FULL:
        return cft_supports(hw, CFT_FMA, fmt) &&
               cft_supports(hw, CFT_NEG, fmt) &&
               cft_supports(hw, CFT_RSQRT_SEED, fmt);
    case SH_REDUCE:
        return cft_supports(hw, CFT_SUM, fmt);
    case SH_REDUCE_SEG:
        return cft_supports(hw, CFT_SUM, fmt) &&
               (hc->seq_features & CFT_FEAT_REDUCE_SEG) != 0;
    default:
        return 1;
    }
}

static void check_stale_copies(cft_device *sw, cft_device *hw,
                               cft_format fmt, const cft_caps *hc)
{
    const size_t esz = cft_format_size(fmt), n = 64;
    const int seg = cft_supports(hw, CFT_SUM, fmt) &&
                    (hc->seq_features & CFT_FEAT_REDUCE_SEG) != 0;
    const int xrt = !strcmp(hc->backend, "xrt");
    uint8_t *x = (uint8_t *)malloc(n * esz), *y = (uint8_t *)malloc(n * esz);
    uint8_t *z = (uint8_t *)calloc(n, esz), *init = (uint8_t *)malloc(n * esz);
    uint8_t mask[(64 + 7) / 8];
    int64_t i64[64];
    int32_t i32[64];
    uint8_t img[64], img2[64], img3[64], img4[64];
    uint64_t ins[2], ins3[3], insb[3], ins4[3];
    struct stale S[2];
    char label[200];
    size_t i;
    int k, fn, dir, which, runs = 0, agreed = 0, progs = 1, progs_so = 1,
        progs_bank = 1, progs_si = 1;
    /* a card that keeps B resident refuses a publish over unread results */
    const int card_refuses = xrt && hc->buffers_resident;
    /* an index table on a device: the gather V9's sequences run */
    const int indexed = (hc->seq_features & CFT_SEQ_FEAT_INDEXED) != 0;
    static const int declined[] = {SV_RWR, SV_DEP_OUT, SV_SO_OUT,
                                   SV_PUBLISH, SV_N6, SV_RED_DIRTY,
                                   SV_COUNTS_DIRTY};

    memset(S, 0, sizeof S);
    memset(mask, 0, sizeof mask);
    if (!cft_supports(hw, CFT_COPYSIGN, fmt) || !cft_supports(hw, CFT_ADD, fmt)) {
        not_here(NH_BUFFERS, "COMPARED", "  buffers, stale copies",
                 "its reads and writes need CFT_COPYSIGN and CFT_ADD");
        goto out;
    }
    if (!x || !y || !z || !init) {
        printf("  FAIL stale copies: out of memory\n");
        failures++;
        goto out;
    }
    rs = 0x57A1E000u + (uint32_t)fmt;
    fill_finite(x, fmt, n);
    fill_finite(y, fmt, n);
    fill_finite(init, fmt, n);
    for (i = 0; i < n; i++) {
        i64[i] = (int64_t)(rbyte() % 21) - 10;
        i32[i] = (int32_t)((uint32_t)rbyte() << 24 | (uint32_t)rbyte() << 8);
        if (i % 3)
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
    }
    ins[0] = seq_ctrl(3, 0, 0);                  /* deposit r0 = a */
    ins[1] = seq_ctrl(0, 0, 0);                  /* halt */
    ins3[0] = seq_ctrl(3, 0, 0);                 /* deposit r0 = a */
    ins3[1] = seq_stl(0, 0);                     /* scratch slot 0 := r0 */
    ins3[2] = seq_ctrl(0, 0, 0);                 /* halt */
    insb[0] = seq_alu(0, 4, 0, 0, 1, 0, 1, 1);   /* r4 = r0 * k0 + k1 */
    insb[1] = seq_ctrl(3, 4, 0);                 /* deposit r4 */
    insb[2] = seq_ctrl(0, 0, 0);                 /* halt */
    ins4[0] = seq_ldl(4, 0);                     /* r4 <- scratch-in 0 */
    ins4[1] = seq_ctrl(3, 4, 0);                 /* deposit r4 */
    ins4[2] = seq_ctrl(0, 0, 0);                 /* halt */
    for (k = 0; k < 2; k++) {
        struct stale *s = &S[k];
        s->dev = k ? hw : sw;
        s->fmt = fmt;
        s->n = n;
        s->esz = esz;
        s->plants = k && xrt;
        s->card_refuses = !k && card_refuses;
        s->x = x; s->y = y; s->z = z; s->init = init; s->mask = mask;
        s->i64 = i64;
        s->i32 = i32;
        s->out = (uint8_t *)malloc(n * esz);
        s->dep = (uint8_t *)malloc(n * esz);
        s->e = (uint8_t *)malloc(n * esz);
        s->cnt = (uint32_t *)malloc(n * sizeof *s->cnt);
        if (!s->out || !s->dep || !s->e || !s->cnt) {
            printf("  FAIL stale copies: out of memory\n");
            failures++;
            goto out;
        }
        s->img1_bytes = seq_image(img, fmt, ins, 2, NULL, 0, 1);
        s->img1 = img;
        if (cft_program_load(s->dev, img, s->img1_bytes, &s->prog) != CFT_OK)
            progs = 0;
        if (!(hc->seq_features & CFT_SEQ_FEAT_BANK_PTR) ||
            cft_program_load(s->dev, img3,
                             seq_image_flags(img3, fmt, insb, 3, NULL, 2, 1,
                                             CFT_PROG_FLAG_BANK_EXT),
                             &s->prog_bank) != CFT_OK)
            progs_bank = 0;
        if (!(hc->seq_features & CFT_SEQ_FEAT_SCRATCH_IO) ||
            cft_program_load(s->dev, img2,
                             seq_image_scratch(img2, fmt, ins3, 3, NULL, 0, 1,
                                               CFT_PROG_FLAG_SCRATCH_IO, 0,
                                               1),
                             &s->prog_so) != CFT_OK)
            progs_so = 0;
        if (!(hc->seq_features & CFT_SEQ_FEAT_SCRATCH_IO) ||
            cft_program_load(s->dev, img4,
                             seq_image_scratch(img4, fmt, ins4, 3, NULL, 0, 1,
                                               CFT_PROG_FLAG_SCRATCH_IO, 1,
                                               0),
                             &s->prog_si) != CFT_OK)
            progs_si = 0;
    }

    for (which = 0; which < SV_COUNT; which++) {
        const int needs_seg = which == SV_RSEG || which == SV_RSEG_BACK ||
                              which == SV_RSEG_DIRTY || which == SV_MASKED ||
                              which == SV_RSEG_TWICE;
        const int needs_prog = which == SV_COUNTS || which == SV_MASKED ||
                               which == SV_COUNTS_TWICE ||
                               which == SV_COUNTS_DIRTY ||
                               which == SV_DEP_OUT || which == SV_IMAGE ||
                               which == SV_STRINGS || which == SV_BANK ||
                               which == SV_DIGEST || which == SV_IDX_BAD ||
                               which == SV_IDX_GOOD || which == SV_IDX_PROG ||
                               which == SV_IDX_SI || which == SV_SCALAR ||
                               which == SV_DIGEST_OUT ||
                               which == SV_DIGEST_DIRTY;
        const int needs_idx = which == SV_IDX_BAD || which == SV_IDX_GOOD ||
                              which == SV_IDX_PROG || which == SV_IDX_SI ||
                              which == SV_SCALAR;
        if ((needs_seg && !seg) || (needs_prog && !progs) ||
            (needs_idx && !indexed) ||
            (which == SV_IDX_SI && !progs_si) ||
            (which == SV_SO_OUT && !progs_so) ||
            ((which == SV_BANK || which == SV_DIGEST) && !progs_bank) ||
            (which == SV_RED_DIRTY && !cft_supports(hw, CFT_SUM, fmt)) ||
            (which == SV_MASKED &&
             !(hc->seq_features & CFT_SEQ_FEAT_LANE_MASK)) ||
            (which == SV_RED_TWICE && !cft_supports(hw, CFT_SUM, fmt))) {
            snprintf(label, sizeof label, "  stale copies (%s), %s",
                     cft_format_name(fmt), sv_name[which]);
            not_here(NH_BUFFERS, "COMPARED", label,
                     "this device does not publish what it needs");
            continue;
        }
        if ((which == SV_WITNESS || which == SV_MASKED) && !xrt) {
            snprintf(label, sizeof label, "    stale copies (%s), %s",
                     cft_format_name(fmt), sv_name[which]);
            not_here(NH_OTHER, "TESTED", label, "the %s backend has no tile "
                     "to plant a refusal on, so it runs without one",
                     hc->backend);
        }
        runs++;
        agreed += stale_one(S, 0, which, 0, sv_name[which], 0);
    }
    for (fn = 0; fn < SH_COUNT; fn++) {
        const int ok = stale_host_ok(hw, hc, fn, fmt);
        if (ok < 0)
            continue;
        if (!ok) {
            snprintf(label, sizeof label, "  stale copies (%s), %s",
                     cft_format_name(fmt), sh_name[fn]);
            not_here(NH_BUFFERS, "COMPARED", label,
                     "this device cannot run it as the software backend does");
            continue;
        }
        for (dir = SD_IN; dir <= SD_INPLACE; dir++) {
            /* the text is the caller's, never B's; and in place is legal
             * only where d may alias a */
            if (dir == SD_IN && fn == SH_FROMDEC)
                continue;
            if (dir == SD_INPLACE &&
                !(fn == SH_EXP || fn == SH_RINT || fn == SH_NEXTUP ||
                  fn == SH_SCALEB_DEV || fn == SH_DIV || fn == SH_SQRT ||
                  fn == SH_MINMAG || fn == SH_AUG_R || fn == SH_DIV_FULL ||
                  fn == SH_SQRT_FULL || fn == SH_NEXTDOWN))
                continue;
            snprintf(label, sizeof label, "%s, %s", sh_name[fn], sd_name[dir]);
            runs++;
            agreed += stale_one(S, 1, fn, dir, label, 0);
        }
    }
    /* The same sequences with every output bind of the card DECLINED
     * (CFT_XRT_BIND), so the staged collects' marks are what keeps them
     * right - verifier-V8 removed those marks and the leg stayed green.
     * A card only: the software backend has no binds to decline. */
    if (xrt) {
        size_t d;
        /* ...and first, that the instrument declines at all - a pass
         * under an instrument that did nothing would agree vacuously */
        {
            struct rbuf R;
            cft_buffer_info bi;
            uint32_t f2 = 0, b2 = 0;
            int declined_ok = 0;
            if (rbuf_alloc(hw, &R, n * esz)) {
                put_env("CFT_XRT_BIND", "decline-outputs");
                if (cft_run(hw, CFT_ADD, fmt, CFT_RNE, x, NULL, y, R.p, n,
                            &f2, &b2) == CFT_OK) {
                    memset(&bi, 0, sizeof bi);
                    bi.struct_size = sizeof bi;
                    declined_ok =
                        cft_buffer_get_info(R.b, &bi) == CFT_OK &&
                        bi.resident_binds == 0 && bi.staged_binds > 0 &&
                        strstr(bi.staged_why, "CFT_XRT_BIND") != NULL;
                }
                put_env("CFT_XRT_BIND", NULL);
                rbuf_free(&R);
            }
            CHECK(declined_ok, "stale copies (%s): CFT_XRT_BIND=decline-"
                  "outputs declined nothing - the pass below would agree "
                  "vacuously", cft_format_name(fmt));
        }
        /* ...and that a publish refused over unread results names itself
         * straight after a refusal of the library's own, which leaves its
         * sentence in device.c's slot: until 2026-09-27 the publish reached
         * the backend without clearing the slot, and cft_last_error() gave
         * the older sentence (verifier-V9). The older one here is
         * cft_run_ex's, for an indexed run whose d is its own source. */
        if (card_refuses) {
            struct rbuf R;
            cft_elem_args E;
            uint32_t f2 = 0, b2 = 0, t0[64];
            char said[240];
            int named = 0, older = 0;
            said[0] = '\0';
            memset(t0, 0, sizeof t0);
            if (rbuf_alloc(hw, &R, n * esz)) {
                if (cft_run(hw, CFT_ADD, fmt, CFT_RNE, x, NULL, y, R.p, n,
                            &f2, &b2) == CFT_OK) {
                    memset(&E, 0, sizeof E);
                    E.struct_size = sizeof E;
                    E.a = z;
                    E.d = z;
                    E.n = n;
                    E.idx_a = t0;
                    E.idx_a_src = n;
                    /* the older sentence must be there, or this proves
                     * nothing */
                    older = cft_run_ex(hw, CFT_ABS, fmt, CFT_RNE, &E) ==
                                CFT_ERR_INVALID_ARGUMENT &&
                            strstr(cft_last_error(), "overlaps") != NULL;
                    named = cft_buffer_to_device(R.b) != CFT_OK;
                    snprintf(said, sizeof said, "%s", cft_last_error());
                    named = named && strstr(said, "never read back") != NULL;
                    (void)cft_buffer_from_device(R.b);
                }
                rbuf_free(&R);
            }
            CHECK(older && named, "stale copies (%s): a publish refused over "
                  "unread results, straight after a refusal of the library's "
                  "own (%s), said \"%s\" - it must name itself",
                  cft_format_name(fmt), older ? "made" : "NOT made", said);
        } else {
            snprintf(label, sizeof label, "    stale copies (%s), a refused "
                     "publish naming itself", cft_format_name(fmt));
            not_here(NH_OTHER, "TESTED", label, "this device keeps no "
                     "resident buffers, so no publish is refused");
        }
        for (d = 0; d < sizeof declined / sizeof declined[0]; d++) {
            which = declined[d];
            if ((which == SV_SO_OUT && !progs_so) ||
                ((which == SV_DEP_OUT || which == SV_COUNTS_DIRTY) &&
                 !progs) ||
                (which == SV_RED_DIRTY && !cft_supports(hw, CFT_SUM, fmt)))
                continue;
            snprintf(label, sizeof label, "outputs declined, %s",
                     sv_name[which]);
            S[0].card_refuses = 0;   /* nothing resident to refuse over */
            runs++;
            agreed += stale_one(S, 0, which, 0, label, 1);
            S[0].card_refuses = card_refuses;
        }
    } else {
        snprintf(label, sizeof label, "    stale copies (%s), outputs declined",
                 cft_format_name(fmt));
        not_here(NH_OTHER, "TESTED", label, "the %s backend has no bind to "
                 "decline", hc->backend);
    }
    printf("    stale copies (%s): %d of %d scenarios agree with the software "
           "backend, transcript for transcript - V7's sequences and every "
           "entry point computed on the host, both ways\n",
           cft_format_name(fmt), agreed, runs);
out:
    for (k = 0; k < 2; k++) {
        cft_program_free(S[k].prog);
        cft_program_free(S[k].prog_so);
        cft_program_free(S[k].prog_bank);
        cft_program_free(S[k].prog_si);
        free(S[k].out); free(S[k].dep); free(S[k].e); free(S[k].cnt);
        free(S[k].tr);
    }
    free(x); free(y); free(z); free(init);
}

/* Resident windows STAY resident (verifier-V8: residency undone passed
 * every correctness leg). Two shapes, bytes checked in each:
 *   - a buffer carved [a | counts | deposits]: the program's stream binds
 *     resident on its second and third runs, although the counts are
 *     written on the host beside it every run - which a whole-buffer
 *     staleness would refill;
 *   - a masked program into a resident deposit window: after a read-back
 *     the next masked run binds it resident (the flush left the copy
 *     current); after a publish it refills (the control).
 * Counted from cft_buffer_get_info's staged_binds. On a backend with no
 * device copies there is nothing to count: NOT TESTED. */
static void check_resident_stays(cft_device *hw, cft_format fmt,
                                 const cft_caps *hc)
{
    const size_t esz = cft_format_size(fmt), n = 64;
    const size_t off_cnt = n * esz, off_dep = n * esz + n * 4;
    uint8_t img[64], *x = (uint8_t *)malloc(n * esz);
    uint8_t *mask = (uint8_t *)calloc((n + 7) / 8, 1);
    uint64_t ins[2];
    uint32_t cnt[64], fl = 0, bus = 0;
    struct rbuf C, D;
    cft_program *prog = NULL;
    cft_run_args A;
    cft_buffer_info bi;
    uint64_t st_prev = 0, carved_extra = 0, masked_after_read = 0,
             masked_after_pub = 0;
    size_t i;
    int run, bad = 0, ok = 1;

    C.b = D.b = NULL;
    if (!hc->buffers_resident || !(hc->seq_features & CFT_SEQ_FEAT_LANE_MASK)) {
        not_here(NH_OTHER, "TESTED", "    resident windows stay resident",
                 "%s", hc->buffers_resident
                 ? "this device has no lane mask"
                 : "this device keeps no device copies to count");
        goto out;
    }
    if (!x || !mask || !rbuf_alloc(hw, &C, off_dep + n * esz) ||
        !rbuf_alloc(hw, &D, n * esz)) {
        printf("  FAIL resident windows: out of memory\n");
        failures++;
        goto out;
    }
    rs = 0x2E51D000u + (uint32_t)fmt;
    fill_finite(x, fmt, n);
    for (i = 0; i < n; i++)
        if (i % 3)
            mask[i >> 3] |= (uint8_t)(1u << (i & 7u));
    ins[0] = seq_ctrl(3, 0, 0);
    ins[1] = seq_ctrl(0, 0, 0);
    if (cft_program_load(hw, img, seq_image(img, fmt, ins, 2, NULL, 0, 1),
                         &prog) != CFT_OK) {
        printf("  FAIL resident windows (%s): the image did not load (%s)\n",
               cft_format_name(fmt), cft_last_error());
        failures++;
        goto out;
    }
    /* the carved buffer */
    memcpy(C.p, x, n * esz);
    CHECK(cft_buffer_to_device(C.b) == CFT_OK, "publishing the carved buffer");
    for (run = 1; run <= 3; run++) {
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = C.p;
        A.n = n;
        A.counts = (uint32_t *)(void *)(C.p + off_cnt);
        A.deposits = C.p + off_dep;
        A.flags_out = &fl;
        A.bus_out = &bus;
        if (cft_program_run_ex(prog, &A) != CFT_OK ||
            cft_buffer_from_device(C.b) != CFT_OK) {
            ok = 0;
            break;
        }
        for (i = 0; i < n; i++) {
            uint32_t c;
            memcpy(&c, C.p + off_cnt + i * 4, 4);
            bad += memcmp(C.p + off_dep + i * esz, x + i * esz, esz) != 0 ||
                   c != 1;
        }
        memset(&bi, 0, sizeof bi);
        bi.struct_size = sizeof bi;
        if (cft_buffer_get_info(C.b, &bi) != CFT_OK) {
            ok = 0;
            break;
        }
        if (run > 1)
            carved_extra += bi.staged_binds - st_prev;
        st_prev = bi.staged_binds;
    }
    /* the masked window */
    memset(D.p, 0x5a, n * esz);
    CHECK(cft_buffer_to_device(D.b) == CFT_OK, "publishing the masked window");
    for (run = 1; ok && run <= 3; run++) {
        if (run == 3)
            ok = cft_buffer_to_device(D.b) == CFT_OK;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = x;
        A.n = n;
        A.counts = cnt;
        A.deposits = D.p;
        A.lane_mask = mask;
        A.lane_mask_bytes = (n + 7) / 8;
        A.flags_out = &fl;
        A.bus_out = &bus;
        if (!ok || cft_program_run_ex(prog, &A) != CFT_OK ||
            cft_buffer_from_device(D.b) != CFT_OK) {
            ok = 0;
            break;
        }
        for (i = 0; i < n; i++) {
            size_t k;
            if (i % 3)
                bad += memcmp(D.p + i * esz, x + i * esz, esz) != 0;
            else
                for (k = 0; k < esz; k++)
                    bad += D.p[i * esz + k] != 0x5a;
        }
        memset(&bi, 0, sizeof bi);
        bi.struct_size = sizeof bi;
        if (cft_buffer_get_info(D.b, &bi) != CFT_OK) {
            ok = 0;
            break;
        }
        if (run == 2)
            masked_after_read = bi.staged_binds - st_prev;
        if (run == 3)
            masked_after_pub = bi.staged_binds - st_prev;
        st_prev = bi.staged_binds;
    }
    CHECK(ok && !bad, "resident windows (%s): a run or a read-back failed, "
          "or %d lanes wrong (%s)", cft_format_name(fmt), bad,
          cft_last_error());
    CHECK(ok && carved_extra == 0, "resident windows (%s): the carved "
          "buffer's stream was refilled %lu times on its 2nd and 3rd runs - "
          "a write beside a window staled it", cft_format_name(fmt),
          (unsigned long)carved_extra);
    CHECK(ok && masked_after_read == 0, "resident windows (%s): a masked "
          "run after a read-back refilled %lu windows - the copy the "
          "read-back flushed was not left current", cft_format_name(fmt),
          (unsigned long)masked_after_read);
    CHECK(ok && masked_after_pub > 0, "resident windows (%s): a masked run "
          "after a publish refilled nothing - staleness does not work",
          cft_format_name(fmt));
    if (ok && !bad && carved_extra == 0 && masked_after_read == 0 &&
        masked_after_pub > 0)
        printf("    resident windows stay resident (%s): a carved buffer's "
               "stream resident on its 2nd and 3rd runs; a masked window "
               "resident after a read-back, refilled after a publish (%lu); "
               "every lane right\n", cft_format_name(fmt),
               (unsigned long)masked_after_pub);
out:
    cft_program_free(prog);
    if (C.b)
        rbuf_free(&C);
    if (D.b)
        rbuf_free(&D);
    free(x);
    free(mask);
}

/* --expect-refusal: the identity refusal this run is TOLD to expect of
 * the handle under test - "mixed" for an image whose tiles publish
 * different CAPS words (a mixed layout, docs/LAYOUTS.md), "unreadable"
 * for one with a tile whose CAPS cannot be read. Without it, either
 * refusal FAILS the identity leg, in every mode: it is by design only for
 * an image that IS so, and on any other it is a fault (a CAPS read that
 * failed at open) or a defect (a comparison that refuses everything, a
 * tile's words read from the wrong register). verifier-C3 showed all
 * three passing a leg that accepted any such refusal (4d5d8e4, item 4).
 * 0 none, 1 mixed, 2 unreadable. */
static int expect_refusal;
static const char *const refusal_kind[3] = {"none", "mixed", "unreadable"};

/* The two plants' decoded caps and supports, kept by check_image_plants
 * to be held to the unplanted handle under test once it is open. */
#define PLANT_PROBES 2
static cft_caps plant_caps[PLANT_PROBES];
static unsigned char plant_supports[PLANT_PROBES][4][7];
static int plant_opened[PLANT_PROBES];
static const cft_op group_ops[7] = {CFT_FMA, CFT_ABS, CFT_MIN, CFT_CMPLT,
                                    CFT_IADD, CFT_SUM, CFT_RECIP_SEED};

/* A file's bytes, whole, or NULL with *len 0. */
static unsigned char *read_whole(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf = NULL, *grown;
    size_t have = 0, cap = 0, k;
    *len = 0;
    if (!f)
        return NULL;
    for (;;) {
        if (have == cap) {
            cap = cap ? cap * 2 : (size_t)1 << 20;
            grown = (unsigned char *)realloc(buf, cap);
            if (!grown) {
                free(buf);
                fclose(f);
                return NULL;
            }
            buf = grown;
        }
        k = fread(buf + have, 1, cap - have, f);
        have += k;
        if (k == 0)
            break;
    }
    if (ferror(f)) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *len = have;
    return buf;          /* never NULL here: the first pass allocated */
}

/* The device image's identity (cft.h, cft_get_image_id), held to the
 * file the handle was opened with - what a certificate will record as
 * "the device", so a wrong answer here is a certificate that names the
 * wrong bitstream.
 *
 *   xrt       CFT_OK; sha256 equal to THIS program's SHA-256 of the
 *             artifact's bytes, read here and not by the library, and
 *             image_bytes their count; version the contract cft_get_caps
 *             reports; n_caps 1 below VERSION 0x800 and 2 from it; and
 *             the raw words decoding to what the handle reports - the
 *             format nibble to format_mask, CAPS[14:8] to cft_supports
 *             for one opcode of each of the seven groups, the two
 *             feature nibbles and CAPS2's to seq_features, CAPS2's
 *             depth to max_scratch. Words read from the wrong register
 *             would not decode to this device.
 *   xrt, refused by design
 *             an image whose tiles publish different CAPS words, or one
 *             whose tile's words could not be read at open: correct ONLY
 *             when the run was told to expect it (--expect-refusal
 *             mixed|unreadable), and then held to its sentence and
 *             struct_size 0, with the digest and words NOT TESTED, by
 *             name. Unexpected, it FAILS, in every mode: on an image that
 *             should have one identity it is a fault or a defect
 *   software  refused by name: CFT_ERR_UNSUPPORTED, "software backend",
 *             struct_size 0
 *   remote    refused by name: CFT_ERR_UNSUPPORTED, "remote handle"
 *
 * The by-design refusals have their own planted gate under -i:
 * check_image_plants, below.
 *
 * The digest check's negative control is for a card, where it can run:
 * CFT_DEVICE_TEST_HASH_FILE names another file to hash in place of the
 * artifact, and the check must then FAIL, naming both digests
 * (hw/card-identity.sh plants it). A comparison that could not fail
 * would pass that run as well.
 *
 * Returns nothing; counts into checks and failures like every leg. */
static void check_image_identity(cft_device *dev, const char *artifact)
{
    cft_caps caps;
    cft_image_id im;
    cft_status st;
    const char *msg;

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(dev, &caps) != CFT_OK) {
        CHECK(0, "the image identity: cft_get_caps failed first");
        return;
    }
    memset(&im, 0, sizeof im);
    im.struct_size = sizeof im;
    st = cft_get_image_id(dev, &im);
    msg = cft_last_error();

    if (!strcmp(caps.backend, "software") || !strcmp(caps.backend, "remote")) {
        const int sw = !strcmp(caps.backend, "software");
        const char *name = sw ? "software backend" : "remote handle";
        CHECK(st == CFT_ERR_UNSUPPORTED && strstr(msg, name) &&
              im.struct_size == 0,
              "the %s's image identity: %s with struct_size %lu - it has no "
              "image, and must be refused by name (CFT_ERR_UNSUPPORTED, "
              "\"%s\", struct_size 0), not answered: \"%s\"", name,
              cft_strerror(st), (unsigned long)im.struct_size, name, msg);
        if (st == CFT_ERR_UNSUPPORTED && strstr(msg, name) &&
            im.struct_size == 0)
            printf("  image identity (%s): refused by name - %s\n",
                   caps.backend, msg);
        return;
    }
    if (strcmp(caps.backend, "xrt")) {
        CHECK(0, "the image identity: backend \"%s\" is none this test "
              "knows, so nothing says what its identity should be",
              caps.backend);
        return;
    }

    /* The two refusals an image earns by design - its tiles publish
     * different CAPS words ("mixed"), or one tile's could not be read at
     * open ("unreadable") - pass this leg ONLY when the run was told to
     * expect that one, with --expect-refusal; device-test's own plants
     * are held in check_image_plants, on handles of their own. Any other
     * such refusal FAILS, in every mode, as it did at 082400d (4d5d8e4
     * passed it, and verifier-C3 showed a real read failure, a
     * comparison that refuses everything and a tile read from CAPS2 all
     * going through). An expected refusal is held to its form - its
     * sentence, struct_size 0 - and the digest and words are then NOT
     * TESTED, by name: that image has no single identity to hold to the
     * file. An expectation the identity does not meet fails as well. */
    {
        const int kind = st != CFT_ERR_UNSUPPORTED ? 0
                       : strstr(msg, "publish different CAPS words") ? 1
                       : strstr(msg, "could not be read at open") ? 2 : 0;
        if (kind && kind == expect_refusal) {
            CHECK(im.struct_size == 0, "the image identity: refused as "
                  "expected (%s), but struct_size came back %lu, not 0",
                  refusal_kind[kind], (unsigned long)im.struct_size);
            printf("  image identity (xrt): refused by name, as this run was "
                   "told to expect (--expect-refusal %s) - %s\n",
                   refusal_kind[kind], msg);
            not_here(NH_OTHER, "TESTED", "  the image's digest and CAPS words",
                     "this image is refused by design (--expect-refusal %s), "
                     "so there is no digest to hold to %s",
                     refusal_kind[kind], artifact ? artifact : "the file");
            return;
        }
        if (kind) {
            CHECK(0, "the image identity: refused as %s, and nothing told this "
                  "run to expect it - \"%s\". On an image that should have "
                  "one identity that is a fault or a defect, not an answer; "
                  "an image that IS %s is run with --expect-refusal %s",
                  refusal_kind[kind], msg,
                  kind == 1 ? "a mixed layout" : "unreadable on a tile",
                  refusal_kind[kind]);
            return;
        }
        if (expect_refusal) {
            CHECK(0, "the image identity: this run was told to expect a "
                  "refusal (--expect-refusal %s), and the image %s",
                  refusal_kind[expect_refusal],
                  st == CFT_OK ? "answered" : "was refused otherwise");
            if (st != CFT_OK)
                return;
        }
    }
    CHECK(st == CFT_OK && im.struct_size == sizeof im,
          "the image identity on an xclbin: %s, struct_size %lu: %s",
          cft_strerror(st), (unsigned long)im.struct_size, msg);
    if (st != CFT_OK)
        return;
    {
        const char *plant = getenv("CFT_DEVICE_TEST_HASH_FILE");
        const char *path = plant && *plant ? plant : artifact;
        unsigned char *bytes;
        uint8_t want[32];
        char got_hex[65], want_hex[65];
        size_t len, i;

        for (i = 0; i < 32; i++)
            snprintf(got_hex + 2 * i, 3, "%02x", im.sha256[i]);
        printf("image: sha256 %s, %llu bytes, VERSION 0x%08x, CAPS 0x%08x",
               got_hex, (unsigned long long)im.image_bytes,
               (unsigned)im.version, (unsigned)im.caps[0]);
        if (im.n_caps > 1)
            printf(", CAPS2 0x%08x", (unsigned)im.caps[1]);
        printf("\n");
        if (plant && *plant)
            printf("  CFT_DEVICE_TEST_HASH_FILE=%s: hashing that file in "
                   "place of the artifact - the digest check below MUST "
                   "fail\n", plant);

        bytes = read_whole(path, &len);
        CHECK(bytes != NULL, "the image identity: %s could not be read "
              "here to hash", path);
        if (!bytes)
            return;
        st = cft_sha256(bytes, len, want);
        free(bytes);
        CHECK(st == CFT_OK, "the image identity: cft_sha256 of %s: %s",
              path, cft_strerror(st));
        for (i = 0; i < 32; i++)
            snprintf(want_hex + 2 * i, 3, "%02x", want[i]);
        CHECK(!memcmp(im.sha256, want, 32),
              "the image identity: the handle reports sha256 %s, which is "
              "not the SHA-256 of %s (%s) - a certificate would name the "
              "wrong bitstream", got_hex, path, want_hex);
        CHECK(im.image_bytes == (uint64_t)len,
              "the image identity: the handle reports %llu bytes and %s has "
              "%lu", (unsigned long long)im.image_bytes, path,
              (unsigned long)len);
        if (!memcmp(im.sha256, want, 32) && im.image_bytes == (uint64_t)len)
            printf("  image identity: the digest is the SHA-256 of %s, "
                   "%lu bytes\n", path, (unsigned long)len);
    }
    {
        static const cft_op group_op[7] = {CFT_FMA, CFT_ABS, CFT_MIN,
                                           CFT_CMPLT, CFT_IADD, CFT_SUM,
                                           CFT_RECIP_SEED};
        const uint32_t w = im.caps[0];
        const uint32_t w2 = im.n_caps > 1 ? im.caps[1] : 0u;
        const int failed_before = failures;
        int f, g, fmt = -1, bad = 0;
        for (f = 0; f < 4 && fmt < 0; f++)
            if (caps.format_mask & (1u << f))
                fmt = f;
        CHECK(im.version == caps.device_version,
              "the image identity: VERSION 0x%08x, and cft_get_caps says "
              "0x%08x", (unsigned)im.version, (unsigned)caps.device_version);
        CHECK(im.n_caps == (im.version >= 0x800u ? 2u : 1u),
              "the image identity: %u CAPS words at VERSION 0x%08x, where "
              "CAPS2 exists from 0x800", (unsigned)im.n_caps,
              (unsigned)im.version);
        CHECK(im.caps[2] == 0 && im.caps[3] == 0 &&
              (im.n_caps > 1 || im.caps[1] == 0),
              "the image identity: a slot past n_caps is not zero");
        CHECK((w & 0xFu) == caps.format_mask,
              "the image identity: CAPS[3:0] is 0x%x and format_mask 0x%x",
              (unsigned)(w & 0xFu), (unsigned)caps.format_mask);
        for (g = 0; g < 7 && fmt >= 0; g++)
            if (!!cft_supports(dev, group_op[g], (cft_format)fmt) !=
                !!(w & (1u << (8 + g)))) {
                printf("  FAIL: the image identity: CAPS[%d] is %u and "
                       "cft_supports(%s) says %d\n", 8 + g,
                       (unsigned)((w >> (8 + g)) & 1u),
                       cft_op_name(group_op[g]),
                       cft_supports(dev, group_op[g], (cft_format)fmt));
                bad++;
            }
        checks++;
        failures += bad != 0;
        CHECK((caps.seq_features & 0xFFu) ==
              (((w >> 4) & 0xFu) | (((w >> 28) & 0xFu) << 4)),
              "the image identity: CAPS[7:4] and CAPS[31:28] are 0x%x and "
              "0x%x, and seq_features' low byte is 0x%x",
              (unsigned)((w >> 4) & 0xFu), (unsigned)((w >> 28) & 0xFu),
              (unsigned)(caps.seq_features & 0xFFu));
        CHECK(((caps.seq_features >> 8) & 0xFu) == ((w2 >> 4) & 0xFu),
              "the image identity: CAPS2[7:4] is 0x%x and seq_features' "
              "bits 11:8 are 0x%x", (unsigned)((w2 >> 4) & 0xFu),
              (unsigned)((caps.seq_features >> 8) & 0xFu));
        CHECK(caps.max_scratch ==
              ((w2 & 0x10u) ? (1u << (w2 & 0xFu)) : 0u),
              "the image identity: CAPS2 says a scratch depth of %u and "
              "max_scratch is %u",
              (unsigned)((w2 & 0x10u) ? (1u << (w2 & 0xFu)) : 0u),
              (unsigned)caps.max_scratch);
        if (failures == failed_before)
            printf("  image identity: the raw CAPS %s to this handle's "
                   "caps and opcode groups\n",
                   im.n_caps > 1 ? "words decode" : "word decodes");
    }
}

/* CFT_XRT_CAPS, device-test's instrument (backend_xrt.cpp), held from
 * both sides under -i on an xclbin, BEFORE the handle under test exists -
 * a second open would find its tiles held.
 *
 * 1. A malformed value is refused by name at open, before anything is
 *    loaded: the five verifier-C3 found quietly ignored until 2026-09-28
 *    (plant-diff, PLANT-DIFFER, a trailing space, 1, yes). An instrument
 *    that read a typo as "no plant" would be a gate that could not fail.
 * 2. The two refusals an image earns by design, PLANTED, so that each has
 *    a gate that can fail: plant-differ gives tile 1 a CAPS word one bit
 *    off tile 0's, and plant-unreadable makes tile 1's CAPS read throw.
 *    Both act on the backend's comparison's INPUT, so a backend that
 *    stopped comparing, or said "different words" for a read that
 *    failed, fails here. Each must be refused by its own sentence, and
 *    the sentence must name the plant: set by accident, a plant must not
 *    tell anyone their image is mixed or their tile unreadable. Then
 *    struct_size 0, and not one byte written past it (0xA5 fill). An
 *    image with one tile has no tile 1 to plant in: NOT TESTED, by name.
 * 3. Each planted handle's decoded caps and opcode groups are kept, and
 *    held to the UNPLANTED handle under test once it is open
 *    (check_plant_caps): a plant changes the identity and nothing the
 *    library computes with. Until 2026-09-28 that was true of the code
 *    and held by no gate - verifier-C3 showed a plant that also dropped
 *    fp32 from the handle passing 17 of 17.
 *
 * A CFT_XRT_CAPS set from OUTSIDE device-test is put back after the
 * probes, so that it reaches the handle under test. That is how a real
 * CAPS read failure at open is imitated, and the identity leg must fail
 * it unless the run was told to expect it (--expect-refusal). */
static void check_image_plants(const char *artifact)
{
    static const char *const bad[] = {"plant-diff", "PLANT-DIFFER",
                                      "plant-differ ", "1", "yes"};
    static const struct {
        const char *plant, *says;
    } p[PLANT_PROBES] = {
        {"plant-differ", "publish different CAPS words"},
        {"plant-unreadable", "could not be read at open"},
    };
    const char *outside_env = getenv("CFT_XRT_CAPS");
    char outside[64] = "";
    const int had_outside = outside_env != NULL;
    const int failed_before = failures;
    size_t j;
    int i;

    if (had_outside)
        snprintf(outside, sizeof outside, "%s", outside_env);

    for (j = 0; j < sizeof bad / sizeof bad[0]; j++) {
        cft_device *dev = (cft_device *)(void *)0x1;
        char want[64];
        cft_status st;
        const char *msg;
        snprintf(want, sizeof want, "CFT_XRT_CAPS=\"%s\"", bad[j]);
        put_env("CFT_XRT_CAPS", bad[j]);
        st = cft_open(artifact, 0, &dev);
        put_env("CFT_XRT_CAPS", NULL);
        msg = cft_last_error();
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && dev == NULL &&
              strstr(msg, want) != NULL,
              "CFT_XRT_CAPS=\"%s\", a malformed value, must be refused by "
              "name at open (CFT_ERR_INVALID_ARGUMENT, a sentence naming %s, "
              "no handle); it gave %s and \"%s\"", bad[j], want,
              cft_strerror(st), msg);
        if (st == CFT_OK && dev)
            cft_close(dev);
    }
    if (failures == failed_before)
        printf("  CFT_XRT_CAPS: all %lu malformed values refused by name at "
               "open, before anything was loaded\n",
               (unsigned long)(sizeof bad / sizeof bad[0]));

    for (i = 0; i < PLANT_PROBES; i++) {
        cft_device *dev = NULL;
        cft_caps caps;
        cft_image_id im;
        const unsigned char *b = (const unsigned char *)&im;
        size_t k, wrote = 0;
        cft_status st;
        const char *msg;
        char what[96], named[64];
        int f, g, ok;

        plant_opened[i] = 0;
        snprintf(what, sizeof what, "  planted CFT_XRT_CAPS=%s",
                 p[i].plant);
        snprintf(named, sizeof named, "CFT_XRT_CAPS=%s", p[i].plant);
        put_env("CFT_XRT_CAPS", p[i].plant);
        st = cft_open(artifact, 0, &dev);
        put_env("CFT_XRT_CAPS", NULL);
        if (st != CFT_OK) {
            CHECK(0, "%s: the planted open failed: %s (%s)", what + 2,
                  cft_strerror(st), cft_last_error());
            continue;
        }
        memset(&caps, 0, sizeof caps);
        caps.struct_size = sizeof caps;
        if (cft_get_caps(dev, &caps) != CFT_OK) {
            CHECK(0, "%s: cft_get_caps failed on the planted handle",
                  what + 2);
            cft_close(dev);
            continue;
        }
        /* Kept for check_plant_caps whatever the tile count: a plant that
         * reached tile 0's decode would show on one tile as well. */
        plant_caps[i] = caps;
        for (f = 0; f < 4; f++)
            for (g = 0; g < 7; g++)
                plant_supports[i][f][g] = (unsigned char)
                    cft_supports(dev, group_ops[g], (cft_format)f);
        plant_opened[i] = 1;
        if (caps.tiles < 2) {
            not_here(NH_OTHER, "TESTED", what, "this image opens %u tile%s, "
                     "so there is no tile 1 to plant in",
                     (unsigned)caps.tiles, caps.tiles == 1 ? "" : "s");
            cft_close(dev);
            continue;
        }
        memset(&im, 0xA5, sizeof im);
        im.struct_size = sizeof im;
        st = cft_get_image_id(dev, &im);
        msg = cft_last_error();
        for (k = offsetof(cft_image_id, sha256); k < sizeof im; k++)
            wrote += b[k] != 0xA5;
        ok = st == CFT_ERR_UNSUPPORTED && strstr(msg, p[i].says) &&
             strstr(msg, named) && im.struct_size == 0 && wrote == 0;
        CHECK(ok, "%s: a tile planted this way must be refused by its own "
              "sentence (\"%s\"), naming the plant (\"%s\"), with "
              "struct_size 0 and no field written; it gave %s, struct_size "
              "%lu, %lu bytes of the answer's fields written, and \"%s\"",
              what + 2, p[i].says, named, cft_strerror(st),
              (unsigned long)im.struct_size, (unsigned long)wrote, msg);
        if (ok)
            printf("%s: refused by name - %s\n", what, msg);
        cft_close(dev);
    }

    /* The outside value, back for the handle under test. */
    put_env("CFT_XRT_CAPS", had_outside ? outside : NULL);
}

/* One field's difference, appended to `buf`: " <name> 0x<got> against
 * 0x<want>;". Nothing when they are equal. */
static void caps_diff(char *buf, size_t n, const char *name,
                      unsigned long got, unsigned long want)
{
    size_t at = strlen(buf);
    if (got != want && at + 1 < n)
        snprintf(buf + at, n - at, " %s 0x%lx against 0x%lx;", name, got,
                 want);
}

/* Each planted handle's decoded caps and opcode groups, held to the
 * unplanted handle under test (check_image_plants says why): every
 * cft_caps field, and cft_supports for one opcode of each of the seven
 * groups at each of the four formats. */
static void check_plant_caps(cft_device *hw)
{
    static const char *const fmt_name[4] = {"fp32", "fp64", "fp128",
                                            "fp256"};
    cft_caps c;
    int i, f, g, compared = 0;
    const int failed_before = failures;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    if (cft_get_caps(hw, &c) != CFT_OK) {
        CHECK(0, "the planted handles' decode: cft_get_caps failed on the "
              "handle under test");
        return;
    }
    for (i = 0; i < PLANT_PROBES; i++) {
        const cft_caps *p = &plant_caps[i];
        char diff[512] = "";
        if (!plant_opened[i])
            continue;
        compared++;
        caps_diff(diff, sizeof diff, "format_mask", p->format_mask,
                  c.format_mask);
        caps_diff(diff, sizeof diff, "tiles", p->tiles, c.tiles);
        caps_diff(diff, sizeof diff, "device_version", p->device_version,
                  c.device_version);
        caps_diff(diff, sizeof diff, "flags_readable",
                  (unsigned long)p->flags_readable,
                  (unsigned long)c.flags_readable);
        caps_diff(diff, sizeof diff, "max_deposits", p->max_deposits,
                  c.max_deposits);
        caps_diff(diff, sizeof diff, "max_insns", p->max_insns, c.max_insns);
        caps_diff(diff, sizeof diff, "max_consts", p->max_consts,
                  c.max_consts);
        caps_diff(diff, sizeof diff, "seq_features", p->seq_features,
                  c.seq_features);
        caps_diff(diff, sizeof diff, "max_scratch", p->max_scratch,
                  c.max_scratch);
        caps_diff(diff, sizeof diff, "buffers_resident",
                  (unsigned long)p->buffers_resident,
                  (unsigned long)c.buffers_resident);
        if (strcmp(p->backend, c.backend)) {
            size_t at = strlen(diff);
            snprintf(diff + at, sizeof diff - at, " backend %s against %s;",
                     p->backend, c.backend);
        }
        for (f = 0; f < 4; f++)
            for (g = 0; g < 7; g++) {
                const int u = cft_supports(hw, group_ops[g], (cft_format)f);
                if (plant_supports[i][f][g] != (unsigned char)u) {
                    size_t at = strlen(diff);
                    if (at + 1 < sizeof diff)
                        snprintf(diff + at, sizeof diff - at,
                                 " cft_supports(%s, %s) %d against %d;",
                                 cft_op_name(group_ops[g]), fmt_name[f],
                                 plant_supports[i][f][g], u);
                }
            }
        CHECK(!diff[0], "planted CFT_XRT_CAPS=%s: that handle decodes "
              "differently from the unplanted one -%s a plant must change "
              "the identity and nothing the library computes with",
              i == 0 ? "plant-differ" : "plant-unreadable", diff);
    }
    if (compared && failures == failed_before)
        printf("  the planted handles decode as the unplanted one: formats "
               "0x%x, seq_features 0x%x, capacities %u/%u/%u, max_scratch "
               "%u, the seven groups at every format\n",
               (unsigned)c.format_mask, (unsigned)c.seq_features,
               (unsigned)c.max_deposits, (unsigned)c.max_insns,
               (unsigned)c.max_consts, (unsigned)c.max_scratch);
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
    int only_id = 0;        /* the device image's identity only */
    /* --scratch-depth N: the SOFTWARE device under test opened at N
     * scratch slots a lane (revision 7, cft_open_ex), so "sw" can stand
     * for a 2,048-slot tile; the library refuses it for an xclbin, by
     * name, whose depth is its own. */
    unsigned long long dut_depth = 0;
    int f, o, r, argi;

    /* Emulation is orders of magnitude slower than silicon, so the
     * full matrix is a card-day run and -q is what fits in an evening.
     * The scope is a flag rather than a smaller hard-coded list
     * because the two runs should be the same program. */
    for (argi = 1; argi < argc; argi++) {
        if (!strcmp(argv[argi], "--build-id")) {
            /* The library this binary carries, and nothing else: it
             * links libcft.a statically, so this is the id of the
             * archive it was linked against. hw/card-identity.sh holds
             * it to the tree's before trusting a card run. */
            printf("%s\n", cft_build_id());
            return 0;
        } else if (!strcmp(argv[argi], "-q")) {
            quick = 1;
        } else if (!strcmp(argv[argi], "-i")) {
            only_id = 1;
        } else if (!strcmp(argv[argi], "--expect-refusal") &&
                   argi + 1 < argc) {
            const char *want = argv[++argi];
            if (!strcmp(want, "mixed")) {
                expect_refusal = 1;
            } else if (!strcmp(want, "unreadable")) {
                expect_refusal = 2;
            } else {
                fprintf(stderr, "--expect-refusal \"%s\": expected mixed or "
                        "unreadable\n", want);
                return 2;
            }
        } else if (!strcmp(argv[argi], "-s")) {
            only_seq = 1;
        } else if (!strcmp(argv[argi], "-r")) {
            only_reduce = 1;
        } else if (!strcmp(argv[argi], "-b")) {
            only_buf = 1;
        } else if (!strcmp(argv[argi], "--scratch-depth") &&
                   argi + 1 < argc) {
            dut_depth = strtoull(argv[++argi], NULL, 0);
            if (!dut_depth) {
                fprintf(stderr, "--scratch-depth takes a positive number of "
                        "slots\n");
                return 2;
            }
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
                    "[-f fp32|fp64|fp128|fp256] [-q] [-r] [-s] [-b] [-i]\n"
                    "       %s --build-id\n"
                    "  -q  one opcode and one attribute a format\n"
                    "  -r  reductions only\n"
                    "  -s  sequencer programs only\n"
                    "  -b  device-resident buffers only: the same "
                    "elementwise matrix and\n"
                    "      the same reductions run through cft_alloc, "
                    "compared byte for\n"
                    "      byte and flag for flag with the host-pointer "
                    "path and with\n"
                    "      the software backend\n"
                    "  -i  the device image's identity only "
                    "(cft_get_image_id), which every\n"
                    "      other mode checks too; on an xclbin, also "
                    "CFT_XRT_CAPS's five\n"
                    "      malformed values refused, its two refusals "
                    "planted, and each\n"
                    "      planted handle's decode held to the unplanted "
                    "one's\n"
                    "  --scratch-depth N\n"
                    "      the software device under test (\"sw\") at N "
                    "scratch slots a lane;\n"
                    "      the reference is always opened at the device's "
                    "own depth\n"
                    "  --expect-refusal mixed|unreadable\n"
                    "      the identity refusal this image earns by "
                    "design, for one that\n"
                    "      genuinely has no single identity (a mixed "
                    "layout); without it\n"
                    "      that refusal FAILS the identity leg, in every "
                    "mode\n"
                    "  --build-id  print the libcft build this binary "
                    "carries, and exit\n",
                    argv[0], argv[0]);
            return 2;
        }
    }
    if (!artifact) {
        fprintf(stderr, "usage: %s <artifact.xclbin> [-n elements] "
                        "[-f fp32|fp64|fp128|fp256] [-q] [-r] [-s] [-b] "
                        "[-i] [--expect-refusal mixed|unreadable]\n",
                argv[0]);
        return 2;
    }
    if (expect_refusal &&
        (!strcmp(artifact, "sw") || !strncmp(artifact, "cft://", 6))) {
        fprintf(stderr, "--expect-refusal is for an xclbin: the software "
                "backend and a remote handle refuse the identity for what "
                "they are, and every run already requires that\n");
        return 2;
    }
    argv[1] = (char *)artifact;
    /* Which library this run tests, first: this binary links libcft.a
     * statically, and a run of one not relinked since the library was
     * rebuilt tests the OLD library (CLAUDE.md). The id says which. */
    printf("libcft build %s\n", cft_build_id());

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
    /* The completion witness at OPEN (2026-09-26): a tile already
     * running when a handle opens it is refused by name, and the open
     * with it. Planted with CFT_XRT_WITNESS=busy-open BEFORE the handle
     * under test exists, since a second open would find its tiles held;
     * only an xclbin opens tiles. */
    {
        int open_witness = -1;
        char open_why[240] = "";
        if (strcmp(argv[1], "sw") && strncmp(argv[1], "cft://", 6)) {
            cft_device *probe = NULL;
            cft_status ps;
            put_env("CFT_XRT_WITNESS", "busy-open");
            ps = cft_open(argv[1], 0, &probe);
            put_env("CFT_XRT_WITNESS", NULL);
            snprintf(open_why, sizeof open_why, "%s (%s)", cft_strerror(ps),
                     cft_last_error());
            open_witness = ps != CFT_OK &&
                           strstr(cft_last_error(), "is already running when "
                                  "this handle opens it") != NULL;
            if (ps == CFT_OK)
                cft_close(probe);
        }
        /* -i: the identity's two by-design refusals, planted - before the
         * handle under test holds the tiles, as the witness is. */
        if (only_id) {
            if (strcmp(argv[1], "sw") && strncmp(argv[1], "cft://", 6))
                check_image_plants(argv[1]);
            else
                not_here(NH_OTHER, "RUN", "  the planted identity refusals",
                         "only an xclbin has tiles to plant in");
        }
        if (dut_depth) {
            cft_open_args oa;
            memset(&oa, 0, sizeof oa);
            oa.struct_size   = sizeof oa;
            oa.artifact      = strcmp(argv[1], "sw") ? argv[1] : NULL;
            oa.scratch_depth = (uint32_t)dut_depth;
            st = dut_depth > 0xFFFFFFFFull ? CFT_ERR_INVALID_ARGUMENT
                                          : cft_open_ex(&oa, &hw);
        } else {
            st = cft_open(strcmp(argv[1], "sw") ? argv[1] : NULL, 0, &hw);
        }
        if (st != CFT_OK) {
            fprintf(stderr, "device %s: %s\n  %s\n", argv[1],
                    cft_strerror(st), cft_last_error());
            cft_close(sw);
            return 2;
        }
        if (open_witness < 0) {
            not_here(NH_OTHER, "TESTED", "    the completion witness at open",
                     "only an xclbin opens tiles");
        } else {
            CHECK(open_witness, "CFT_XRT_WITNESS=busy-open: %s - a tile busy "
                  "when a handle opens it must be refused by name, the open "
                  "with it", open_why);
            if (open_witness)
                printf("    the completion witness at open: a tile read as "
                       "busy when a handle opened it refused the open by "
                       "name, and the next open went ahead\n");
        }
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

        /* A format this image does not carry must be refused WITH a
         * sentence, and the sentence must name every format it does
         * carry - the moment a caller most wants to be told "this
         * device carries fp32 fp64 fp128" is the moment it asked for
         * fp256. cft-rebound filed this on 2026-09-13 (its
         * docs/BITSTREAM.md, ask 3): cft_run, cft_reduce and the
         * program path returned CFT_ERR_UNSUPPORTED with
         * cft_last_error() empty or stale, and it works around it at
         * open. Both entry points are held here; the program path is
         * held by loading against a format the image lacks in the
         * sequencer section below.
         *
         * On an image that carries all four formats there is nothing
         * to refuse, and that is reported as NOT TESTED rather than
         * counted as agreement - the rule the R8 capability checks
         * keep. */
        {
            static const unsigned char zero[64];
            static unsigned char out[64];
            int absent = 0, before = checks;
            for (f = 0; f < 4; f++) {
                cft_format fmt = (cft_format)f;
                uint32_t fl = 0, bus = 0;
                int g, k;
                if (caps.format_mask & (1u << f))
                    continue;
                absent++;
                for (k = 0; k < 2; k++) {
                    const char *which = k ? "cft_reduce" : "cft_run";
                    const char *msg;
                    st = k ? cft_reduce(hw, CFT_SUM, fmt, CFT_RNE, zero,
                                        NULL, out, 1, &fl, &bus)
                           : cft_run(hw, CFT_ADD, fmt, CFT_RNE, zero, zero,
                                     NULL, out, 1, &fl, &bus);
                    msg = cft_last_error();
                    checks++;
                    if (st != CFT_ERR_UNSUPPORTED) {
                        printf("  FAIL %s(%s) on an image without it: %s, "
                               "not CFT_ERR_UNSUPPORTED\n", which,
                               cft_format_name(fmt), cft_strerror(st));
                        failures++;
                        continue;
                    }
                    if (!msg[0]) {
                        printf("  FAIL %s(%s) refused with no sentence: "
                               "cft_last_error() is empty\n", which,
                               cft_format_name(fmt));
                        failures++;
                        continue;
                    }
                    for (g = 0; g < 4; g++) {
                        if (!(caps.format_mask & (1u << g)))
                            continue;
                        if (!strstr(msg, cft_format_name((cft_format)g))) {
                            printf("  FAIL %s(%s) refused, but the sentence "
                                   "does not name %s, which this device "
                                   "carries:\n    %s\n", which,
                                   cft_format_name(fmt),
                                   cft_format_name((cft_format)g), msg);
                            failures++;
                            break;
                        }
                    }
                    if (!strstr(msg, cft_format_name(fmt))) {
                        printf("  FAIL %s(%s) refused, but the sentence "
                               "does not name the format asked for:\n"
                               "    %s\n", which, cft_format_name(fmt),
                               msg);
                        failures++;
                    }
                }
            }
            if (!absent)
                not_here(NH_OTHER, "TESTED", "  format refusals",
                         "this image carries all four formats, so there "
                         "is nothing to refuse");
            else
                printf("  format refusals: %d absent format%s, %d checks, "
                       "%d failed\n", absent, absent == 1 ? "" : "s",
                       checks - before, failures);
            fflush(stdout);
        }
    }

    /* The reference computes at the DEVICE's scratch depth (revision 7).
     * The depth is part of what a non-strict STX/LDX means - it reduces
     * the index modulo it - so a 2,048-slot tile compared against a
     * 256-slot reference would be two machines, agreeing only on
     * programs that never reach past slot 255. A device that publishes
     * no depth (a VERSION below 0x800, or a remote server older than the
     * field) is compared at the software backend's own 256, as always. */
    if (caps.max_scratch && caps.max_scratch != 256u) {
        cft_open_args oa;
        memset(&oa, 0, sizeof oa);
        oa.struct_size   = sizeof oa;
        oa.scratch_depth = caps.max_scratch;
        cft_close(sw);
        sw = NULL;
        st = cft_open_ex(&oa, &sw);
        if (st != CFT_OK) {
            fprintf(stderr, "the software reference at the device's %lu "
                    "scratch slots: %s\n  %s\n",
                    (unsigned long)caps.max_scratch, cft_strerror(st),
                    cft_last_error());
            cft_close(hw);
            return 2;
        }
        printf("reference: the software backend at %lu scratch slots a "
               "lane, the device's\n", (unsigned long)caps.max_scratch);
    }

    /* The device image's identity, on both handles: the software one
     * refuses by name on every run, the one under test answers for its
     * xclbin or refuses for what it is. Every mode runs it - it costs
     * nothing past the open - and -i runs nothing else. */
    check_image_identity(sw, NULL);
    check_image_identity(hw, strcmp(argv[1], "sw") ? argv[1] : NULL);
    /* -i on an xclbin: the planted handles' decode, held to this one's. */
    if (only_id && strcmp(argv[1], "sw") && strncmp(argv[1], "cft://", 6))
        check_plant_caps(hw);
    fflush(stdout);
    if (only_id) {
        cft_close(hw);
        cft_close(sw);
        printf("\n%d checks, %d failed\n", checks, failures);
        if (!failures)
            printf("the device image's identity holds\n");
        return failures ? 1 : 0;
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
            /* A format the device does not carry: named, counted on
             * the summary, and not a skip (the comment at not_here).
             * It read "fp128  not on this device, skipped" until
             * 2026-09-24, then "SKIPPED fp128: ..." for part of that
             * day. */
            not_here(NH_FORMAT, "COMPARED", cft_format_name(fmt),
                     "not on this device");
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
                    note_op_absent(cft_op_name(ops[bo]));
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

            if (cft_supports(hw, CFT_ADD, fmt))
                check_moved_output_window(sw, hw, (cft_format)fmt,
                                          (unsigned)caps.tiles);

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

            /* The stale-copy class (verifier-V7, 2026-09-25): every path
             * that reads or writes a resident buffer's mirror on the
             * host, held to the software backend both ways. */
            check_stale_copies(sw, hw, fmt, &caps);
            check_resident_stays(hw, fmt, &caps);
            printf("  buffers, stale copies: %d checks, %d failed\n",
                   checks, failures);
            fflush(stdout);

            /* A program's scratch blocks, which bind as the deposit
             * window does. Gated on the feature the device publishes:
             * a 0x600 or 0x700 tile has no per-run block at all, and a
             * leg that failed there would be calling the tile's age a
             * defect. */
            if (caps.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) {
                /* The staged path first: it is the one a caller gets
                 * without adopting cft_alloc, and the one a binding
                 * added beside it can silently break. */
                compare_program_staged(sw, hw, fmt, n);
                compare_buffers_program(sw, hw, fmt, n,
                                        caps.buffers_resident ? 1 : 0);
                printf("  buffers, a program's scratch: %d checks, %d "
                       "failed\n", checks, failures);
                /* ...and R16's four tables and an indexed source
                 * through the same binding path (ABI 0.14). Gated
                 * on the feature bit, as every indexed case is. */
                if (caps.seq_features & CFT_SEQ_FEAT_INDEXED) {
                    compare_buffers_indexed(
                        sw, hw, fmt, n,
                        caps.buffers_resident ? 1 : 0);
                    printf("  buffers, an indexed program: %d "
                           "checks, %d failed\n", checks,
                           failures);
                } else {
                    /* Not a skip, as the format line above; it read
                     * "...: SKIPPED - this device ..." until
                     * 2026-09-24, then SKIPPED first for part of that
                     * day. */
                    not_here(NH_BUFFERS, "COMPARED",
                             "  buffers, an indexed program",
                             "this device does not publish "
                             "CFT_SEQ_FEAT_INDEXED");
                }
            } else {
                not_here(NH_BUFFERS, "COMPARED",
                         "  buffers, a program's scratch",
                         "this device does not publish SCRATCH_IO");
            }
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
                note_op_absent(cft_op_name(CFT_SUM));
            }
            continue;
        }
        {
        /* R16 on an ELEMENTWISE call needs the device to publish
         * CFT_SEQ_FEAT_INDEXED - the composed route is a program over
         * the tile's gather. A device that does not (the seq6 image,
         * VERSION 0x900) refuses it by name, and that refusal is the
         * contract: scored once a format, and the indexed legs are then
         * named NOT COMPARED, as the program legs are. Found on the card
         * on 2026-09-15, when this library first met an older image. */
        const int hw_indexed =
            (caps.seq_features & CFT_SEQ_FEAT_INDEXED) != 0;
        if (!hw_indexed)
            check_indexed_elem_absent(hw, fmt, n);
        for (o = 0; o < nops; o++) {
            if (!cft_supports(hw, ops[o], fmt)) {
                note_op_absent(cft_op_name(ops[o]));
                continue;
            }
            for (r = 0; r < nrnd; r++) {
                compare(sw, hw, fmt, ops[o], rnds[r], n,
                        0x51ce0000u + (uint32_t)(f * 100 + o * 10 + r));
                /* ...and the same opcode and attribute through index
                 * tables (R16, ABI 0.14): the indexed run is the dense
                 * run over the gathered operands, every bit and every
                 * flag. Beside `compare` and not in its own pass, so
                 * that the two can never be run over different
                 * opcodes, formats or attributes. */
                if (hw_indexed)
                    compare_indexed_elem(sw, hw, fmt, ops[o], rnds[r], n,
                                         0x1dced000u +
                                         (uint32_t)(f * 100 + o * 10 + r));
                printf("  %s %s: %d checks so far, %d failed\n",
                       cft_op_name(ops[o]), "ok", checks, failures);
                fflush(stdout);
            }
            /* The scalar-beside-indexed shape, once per opcode: a
             * stride-0 operand the composition puts in the program's
             * constant bank, beside one it gathers. */
            if (hw_indexed)
                compare_indexed_scalar(sw, hw, fmt, ops[o], n,
                                       0x5ca10000u + (uint32_t)(f * 100 + o));
        }
        }
        /* And the refusals the tables carry, which are the library's
         * own and reach no device - scored once at each format. */
        check_indexed_elem_refusals(sw, fmt, n);

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
                note_op_absent("div/sqrt");
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

            /* maxall (ABI 0.12): ceil(log2 n) elementwise maximum
             * passes on a device without CFT_FEAT_REDUCE_SEG, ONE
             * streamed pass on a tile with it - the same bits either
             * way, because 754 maximum is associative and commutative,
             * flags included. Half the cases over the whole encoding
             * space, since NaN propagation is what a maximum has to
             * get right and a finite fill cannot ask it. */
            if (cft_supports(hw, CFT_MAXALL, fmt)) {
                for (i = 0; i < (quick ? 4u : 8u) && i < nrn; i++) {
                    compare_reduce(sw, hw, fmt, CFT_MAXALL, CFT_RNE, rn[i],
                                   0x3a110000u + (uint32_t)(f * 50 + i), 1);
                    compare_reduce(sw, hw, fmt, CFT_MAXALL, CFT_RNE, rn[i],
                                   0x3a150000u + (uint32_t)(f * 50 + i), 0);
                }
                printf("    maxall: %d checks, %d failed\n",
                       checks, failures);
                fflush(stdout);
            }

            /* Per segment (ABI 0.13), every reduction opcode the device
             * serves. The shapes: a segment that is a partial beat at
             * every format (3, 5, 7, 11), a whole beat (8), one
             * element (every element its own result), the whole array
             * (which the library folds onto cft_reduce), and n = 0,
             * which writes nothing. On a device without CAPS2[8] every
             * one of these is the named refusal, counted once each. */
            {
                static const size_t sn[] = {0, 1, 8, 9, 15, 16, 30, 33,
                                            35, 37, 64, 64};
                static const size_t ss[] = {1, 1, 8, 3,  5,  4,  3, 11,
                                             7, 37,  1, 16};
                static const int sops[] = { CFT_SUM, CFT_DOT, CFT_SUMSQ,
                                            CFT_SUMABS, CFT_MAXALL };
                const int has_bit =
                    (caps.seq_features & CFT_FEAT_REDUCE_SEG) != 0;
                size_t k, nsn = quick ? 6 : sizeof sn / sizeof sn[0];
                for (k = 0; k < sizeof sops / sizeof sops[0]; k++) {
                    if (!cft_supports(hw, (cft_op)sops[k], fmt))
                        continue;
                    for (i = 0; i < nsn; i++)
                        compare_reduce_seg(sw, hw, fmt, (cft_op)sops[k],
                                           CFT_RNE, sn[i], ss[i],
                                           0x5e600000u +
                                           (uint32_t)(f * 100 + k * 20 + i),
                                           1, has_bit);
                    compare_reduce_seg(sw, hw, fmt, (cft_op)sops[k], CFT_RNE,
                                       35, 7,
                                       0x5e650000u + (uint32_t)(f * 10 + k),
                                       0, has_bit);
                }
                if (!quick)
                    for (r = 0; r < (int)(sizeof rnds / sizeof rnds[0]); r++)
                        compare_reduce_seg(sw, hw, fmt, CFT_SUM, rnds[r],
                                           36, 9,
                                           0x5e6a0000u + (uint32_t)(f * 10 + r),
                                           1, has_bit);
                printf("    per segment: %d checks, %d failed%s\n",
                       checks, failures,
                       has_bit ? " (CAPS2[8] present, computed on the device)"
                               : "");
                fflush(stdout);
            }

            /* The XRT backend leaves a reduction's b and c buffers
             * allocated and UNWRITTEN - it used to upload zeros into
             * them on every call, twice the operand's bytes for
             * nothing (backend_xrt.cpp, reduce_unread). What makes
             * that safe is the tile ignoring them, which is a property
             * of an image and not of a comment, so it is asked of
             * every image this runs on: the same comparisons with b
             * and c filled with 0xFF, a NaN at every format. A
             * reduction that ever comes to depend on them would carry
             * the NaN, or its invalid flag, straight into a result
             * the software backend does not have. */
            if (!strcmp(caps.backend, "xrt")) {
                const int seg_bit =
                    (caps.seq_features & CFT_FEAT_REDUCE_SEG) != 0;
                put_env("CFT_XRT_REDUCE_BC", "poison");
                compare_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE, 37,
                               0x9015000u + (uint32_t)f, 1);
                compare_reduce(sw, hw, fmt, CFT_SUM, CFT_RNE, 64,
                               0x9015100u + (uint32_t)f, 0);
                if (cft_supports(hw, CFT_MAXALL, fmt))
                    compare_reduce(sw, hw, fmt, CFT_MAXALL, CFT_RNE, 37,
                                   0x9015200u + (uint32_t)f, 0);
                compare_reduce_seg(sw, hw, fmt, CFT_SUM, CFT_RNE, 35, 7,
                                   0x9015300u + (uint32_t)f, 1, seg_bit);
                if (cft_supports(hw, CFT_MAXALL, fmt))
                    compare_reduce_seg(sw, hw, fmt, CFT_MAXALL, CFT_RNE,
                                       33, 11, 0x9015400u + (uint32_t)f,
                                       0, seg_bit);
                put_env("CFT_XRT_REDUCE_BC", NULL);
                printf("    reductions with b and c POISONED (0xFF, a NaN): "
                       "%d checks, %d failed\n", checks, failures);
            } else {
                not_here(NH_OTHER, "RUN",
                         "    reductions with b and c poisoned",
                         "the %s backend has no b and c of its own to "
                         "poison", caps.backend);
            }
            fflush(stdout);
        } else {
            note_op_absent(cft_op_name(CFT_SUM));
            not_here(NH_OTHER, "COMPARED", "  reductions",
                     "no reduction opcode group on this device (CAPS "
                     "says so)");
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

    if (ops_absent) {
        char what[512];
        size_t at;
        int i, n_named = ops_absent < MAX_OPS_ABSENT ? ops_absent
                                                     : MAX_OPS_ABSENT;
        at = (size_t)snprintf(what, sizeof what, "opcode%s",
                              ops_absent == 1 ? "" : "s");
        for (i = 0; i < n_named && at < sizeof what; i++)
            at += (size_t)snprintf(what + at, sizeof what - at, " %s",
                                   op_absent_name[i]);
        not_here(NH_OPCODES, "COMPARED", what,
                 "this device says it does not implement %s",
                 ops_absent == 1 ? "it" : "them");
        printf("  Not a failure, and not a pass either. If the device "
               "should implement\n"
               "  one of these, CAPS is wrong and nothing above tested "
               "it.\n");
    }

    /* Everything above with nothing to test on this device, counted by
     * kind and by word, whether or not anything failed. Not SKIP first,
     * because none of it is a skip (the comment at not_here); and no
     * skip count beside it, because device-test has no check that a
     * host reason can stop - its one input is the artifact it opens.
     * Until 2026-09-24 only the opcodes reached the summary, so a run
     * that compared nothing in fp128 still ended "agree on every case";
     * then, for part of that day, the formats and buffers legs reached
     * it as "skipped: ..." while the rest of these lines did not. */
    {
        const int any = ops_absent || nh_fmts || nh_buf_legs ||
                        nh_compared || nh_tested || nh_run;
        if (any)
            printf("not on this device, each named above: NOT COMPARED "
                   "%d format%s, %d buffers leg%s, %d opcode%s and %d "
                   "other leg%s; NOT TESTED %d; NOT RUN %d\n",
                   nh_fmts, nh_fmts == 1 ? "" : "s",
                   nh_buf_legs, nh_buf_legs == 1 ? "" : "s",
                   ops_absent, ops_absent == 1 ? "" : "s",
                   nh_compared, nh_compared == 1 ? "" : "s",
                   nh_tested, nh_run);
        if (!failures)
            printf(any ? "the device and the software backend agree on "
                         "every case that RAN, bits and flags\n"
                       : "the device and the software backend agree on "
                         "every case, bits and flags\n");
    }
    return failures ? 1 : 0;
}
