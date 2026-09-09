/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-bench - how fast is each format, and each operation within it?
 *
 *   ./cft-bench                        the software backend
 *   ./cft-bench artifact.xclbin        a device (or an emulation)
 *   ./cft-bench -n 65536 -t 0.5        tune the working set / run length
 *   ./cft-bench -f fp256               one format
 *   ./cft-bench --csv                  machine-readable
 *   ./cft-bench art.xclbin --resident  the same run with the operands
 *                                      already on the device
 *
 * What this measures, and what it does not:
 *
 * On the SOFTWARE backend this is the honest number - a single thread
 * running the same softfloat that defines the contract. That matters on
 * its own, because the software tier is half the product: someone with
 * no card runs exactly this, and "how much slower is fp256 than fp64"
 * is a question they will ask before they write anything.
 *
 * On the DEVICE backend it measures cft_run, which stages host memory
 * in and out on every call by default. That is the right default to
 * report because it is what a first port gets, but it is a round trip
 * per call and it will dominate at small n.
 *
 * --resident is the OTHER number, through the same code path. The
 * operands are cft_alloc'd, filled once and published once, and then
 * exactly the same cft_run runs on them back to back - so what the
 * columns report stops being the bus and starts being the engine.
 * Nothing else changes: the same operands, the same opcodes, the same
 * timing loop, the same columns, so the two runs are directly
 * comparable and the difference is the staging and nothing else. On
 * the card this reproduces what host/tools/cft_resident.cpp measures
 * with raw XRT, which is the point - that tool proved the engine's
 * rate existed, and this proves the LIBRARY reaches it.
 *
 * The rate is checked, not merely timed: after the timed runs the
 * result buffer is read back and held against the same call made on
 * plain host pointers, over a bounded prefix. A benchmark that
 * reported a rate for the wrong bytes would be worse than no
 * benchmark.
 *
 * On the software backend --resident is the same measurement twice,
 * because there is no staging to remove - which is worth being able to
 * run, since it is how the mode itself is tested without a card.
 *
 * Under emulation the wall clock is meaningless as hardware
 * performance - hw_emu is a cycle-accurate RTL simulation running many
 * orders of magnitude slower than the fabric. What emulation gives you
 * is exact CYCLE counts, and cycles x clock period is a real hardware
 * prediction. Do not quote seconds from an emulation run.
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 199309L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "cft.h"

#if defined(_WIN32)
#  include <windows.h>
static double now_s(void)
{
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}
#else
#  include <time.h>
static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}
#endif

/* Wall clock, not CPU time, and deliberately. For the software backend
 * the two agree; for a device the CPU is blocked on the card for most
 * of the call and CPU time would report a throughput the hardware
 * cannot deliver. */

/* ---------------------------------------------------------------
 * Operand generation
 *
 * The data matters. Softfloat is not constant-time: a subnormal
 * result takes a different path from a normal one, an exact
 * cancellation shortcuts, and a NaN leaves early. Benchmarking on
 * random BITS would report the speed of a stream of NaNs and
 * infinities, which is not what anyone runs.
 *
 * So the operands here are ordinary normal numbers with a full random
 * significand and an exponent near the middle of the range: the case
 * that exercises the whole alignment, normalisation and rounding path
 * without falling into any of the early exits. It is the fast-path
 * cost of a realistic element, which is the number worth publishing.
 * --------------------------------------------------------------- */
struct fmt_layout {
    int total_bits;
    int exp_bits;
};

/* 1 sign + exp + significand = total. fp256 is 1 + 19 + 236, giving
 * the 237-bit significand the contract specifies. */
static const struct fmt_layout LAYOUT[4] = {
    {  32,  8 },   /* fp32  */
    {  64, 11 },   /* fp64  */
    { 128, 15 },   /* fp128 */
    { 256, 19 }    /* fp256 */
};

static void put_bits(unsigned char *e, int lo, int nbits, uint64_t val)
{
    int i;
    for (i = 0; i < nbits; i++) {
        int b = lo + i;
        unsigned char m = (unsigned char)(1u << (b & 7));
        if ((val >> i) & 1u) e[b >> 3] |= m;
        else                 e[b >> 3] = (unsigned char)(e[b >> 3] & ~m);
    }
}

/* xorshift64*, so the operand stream is identical on every platform
 * and every run. A benchmark whose inputs move is a benchmark whose
 * numbers cannot be compared to yesterday's. */
static uint64_t rng_state = 0x243f6a8885a308d3ull;
static uint64_t rng_next(void)
{
    uint64_t x = rng_state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    rng_state = x;
    return x * 0x2545f4914f6cdd1dull;
}

static void fill(unsigned char *buf, cft_format fmt, size_t n, int spread)
{
    size_t sz = cft_format_size(fmt);
    int total = LAYOUT[(int)fmt].total_bits;
    int ebits = LAYOUT[(int)fmt].exp_bits;
    int sbits = total - 1 - ebits;
    uint64_t bias = ((uint64_t)1 << (ebits - 1)) - 1;
    size_t i, j;

    for (i = 0; i < n; i++) {
        unsigned char *e = buf + i * sz;
        for (j = 0; j < sz; j += 8) {
            uint64_t r = rng_next();
            size_t k, lim = (sz - j < 8) ? sz - j : 8;
            for (k = 0; k < lim; k++) e[j + k] = (unsigned char)(r >> (k * 8));
        }
        /* Exponent within +/-spread of the bias. A little spread is
         * wanted: it makes the addend alignment shift vary, which is
         * the whole point of an FMA's far path. Zero spread would
         * time one shift distance and call it the format's speed. */
        {
            uint64_t off = rng_next() % (uint64_t)(2 * spread + 1);
            put_bits(e, sbits, ebits, bias + off - (uint64_t)spread);
        }
        put_bits(e, total - 1, 1, rng_next() & 1u);
    }
}

/* ---------------------------------------------------------------
 * Timing
 * --------------------------------------------------------------- */
struct result {
    double  elems_per_s;
    double  ns_per_elem;
    int     reps;
    double  seconds;
    uint32_t flags;
    cft_status st;
};

static struct result time_op(cft_device *dev, cft_op op, cft_format fmt,
                             const void *a, const void *b, const void *c,
                             void *d, size_t n, double target_s)
{
    struct result r;
    double t0, t1, elapsed;
    int reps = 1, i;

    memset(&r, 0, sizeof r);

    /* One untimed pass. The first call through a fresh output buffer
     * pays for page faults that no later call pays, and on a device it
     * pays for lazily-created XRT objects. Neither is per-element cost
     * and neither should be charged to the format. */
    r.st = cft_run(dev, op, fmt, CFT_RNE, a, b, c, d, n, &r.flags, NULL);
    if (r.st != CFT_OK) return r;

    /* Grow the repetition count until the measurement is long enough to
     * be about the work rather than about the clock. */
    for (;;) {
        t0 = now_s();
        for (i = 0; i < reps; i++) {
            r.st = cft_run(dev, op, fmt, CFT_RNE, a, b, c, d, n, &r.flags, NULL);
            if (r.st != CFT_OK) return r;
        }
        t1 = now_s();
        elapsed = t1 - t0;
        if (elapsed >= target_s || reps >= (1 << 20)) break;
        if (elapsed <= 0.0) { reps *= 16; continue; }
        {
            double grow = target_s / elapsed * 1.25;
            int next = (grow > 64.0) ? reps * 64 : (int)((double)reps * grow) + 1;
            if (next <= reps) next = reps + 1;
            reps = next;
        }
    }

    r.reps        = reps;
    r.seconds     = elapsed;
    r.elems_per_s = (double)n * (double)reps / elapsed;
    r.ns_per_elem = elapsed * 1e9 / ((double)n * (double)reps);
    return r;
}

int main(int argc, char **argv)
{
    static const cft_op OPS[] = { CFT_FMA, CFT_MUL, CFT_ADD, CFT_ABS };
    static const int NOPS = (int)(sizeof OPS / sizeof OPS[0]);

    const char *artifact = NULL;
    size_t n = 4096;
    double target_s = 0.35;
    int only_fmt = -1, csv = 0, spread = 8, argi, f, o;
    int resident = 0;
    unsigned char *a = NULL, *b = NULL, *c = NULL, *d = NULL;
    /* --resident's four buffers, and the host copies the check needs.
     * The copies are separate memory ON PURPOSE: handing the mirror
     * back to cft_run would be recognised as the same buffer and take
     * the same path, so the comparison would compare nothing. */
    cft_buffer *ba = NULL, *bb = NULL, *bc = NULL, *bd = NULL;
    unsigned char *va = NULL, *vb = NULL, *vc = NULL, *vd = NULL, *vg = NULL;
    size_t vn = 0;
    int verify_bad = 0, verified = 0;
    cft_device *dev = NULL;
    cft_status st;
    double base_ns[4];

    for (argi = 1; argi < argc; argi++) {
        if (!strcmp(argv[argi], "-n") && argi + 1 < argc) {
            n = (size_t)strtoul(argv[++argi], NULL, 10);
        } else if (!strcmp(argv[argi], "-t") && argi + 1 < argc) {
            target_s = strtod(argv[++argi], NULL);
        } else if (!strcmp(argv[argi], "-s") && argi + 1 < argc) {
            spread = (int)strtol(argv[++argi], NULL, 10);
        } else if (!strcmp(argv[argi], "--csv")) {
            csv = 1;
        } else if (!strcmp(argv[argi], "--resident")) {
            resident = 1;
        } else if (!strcmp(argv[argi], "-f") && argi + 1 < argc) {
            const char *want = argv[++argi];
            int i;
            for (i = 0; i < 4; i++)
                if (!strcmp(want, cft_format_name((cft_format)i))) only_fmt = i;
            if (only_fmt < 0) {
                fprintf(stderr, "unknown format %s\n", want);
                return 2;
            }
        } else if (argv[argi][0] != '-' && !artifact) {
            artifact = argv[argi];
        } else {
            fprintf(stderr,
                    "usage: %s [artifact.xclbin] [-n elements] "
                    "[-t seconds] [-f fmt] [-s spread] [--csv] "
                    "[--resident]\n"
                    "  --resident  operands in cft_alloc'd buffers, "
                    "filled and published once,\n"
                    "              so the columns report the engine "
                    "rather than the bus\n", argv[0]);
            return 2;
        }
    }
    if (n == 0) { fprintf(stderr, "-n must be positive\n"); return 2; }

    st = cft_open(artifact, 0, &dev);
    if (st != CFT_OK) {
        fprintf(stderr, "cft_open(%s): %s\n  %s\n",
                artifact ? artifact : "software", cft_strerror(st),
                cft_last_error());
        return 2;
    }

    /* One allocation at the widest element, reused for every format.
     * Buffers are dense, so a narrower format simply uses a prefix.
     *
     * --resident allocates the same four through cft_alloc instead,
     * and everything below is unchanged: the pointers are the
     * buffers' own, so the same fill(), the same time_op() and the
     * same columns apply. That is the whole design of the API being
     * exercised - a caller changes its allocator and nothing else. */
    {
        size_t bytes = n * cft_format_size(CFT_FP256);
        if (resident) {
            if (cft_alloc(dev, bytes, &ba) != CFT_OK ||
                cft_alloc(dev, bytes, &bb) != CFT_OK ||
                cft_alloc(dev, bytes, &bc) != CFT_OK ||
                cft_alloc(dev, bytes, &bd) != CFT_OK) {
                fprintf(stderr, "cft_alloc of four %lu-byte buffers "
                                "failed\n  %s\n",
                        (unsigned long)bytes, cft_last_error());
                cft_buffer_free(ba); cft_buffer_free(bb);
                cft_buffer_free(bc); cft_buffer_free(bd);
                cft_close(dev);
                return 2;
            }
            a = (unsigned char *)cft_buffer_data(ba);
            b = (unsigned char *)cft_buffer_data(bb);
            c = (unsigned char *)cft_buffer_data(bc);
            d = (unsigned char *)cft_buffer_data(bd);
            /* The check's own copies, bounded so that a big -n does
             * not double the process's memory for a spot check.
             * Element i of the output depends on element i of the
             * inputs and nothing else, so a prefix is a valid check of
             * the same arithmetic - and device-test -b is where the
             * whole matrix is held to the pointer path. */
            vn = n < 65536 ? n : 65536;
            va = (unsigned char *)malloc(vn * cft_format_size(CFT_FP256));
            vb = (unsigned char *)malloc(vn * cft_format_size(CFT_FP256));
            vc = (unsigned char *)malloc(vn * cft_format_size(CFT_FP256));
            vd = (unsigned char *)malloc(vn * cft_format_size(CFT_FP256));
            vg = (unsigned char *)malloc(vn * cft_format_size(CFT_FP256));
            if (!va || !vb || !vc || !vd || !vg) {
                fprintf(stderr, "out of memory for the check buffers\n");
                cft_buffer_free(ba); cft_buffer_free(bb);
                cft_buffer_free(bc); cft_buffer_free(bd);
                free(va); free(vb); free(vc); free(vd); free(vg);
                cft_close(dev);
                return 2;
            }
        } else {
            a = (unsigned char *)malloc(bytes);
            b = (unsigned char *)malloc(bytes);
            c = (unsigned char *)malloc(bytes);
            d = (unsigned char *)malloc(bytes);
            if (!a || !b || !c || !d) {
                fprintf(stderr, "out of memory for %lu-element buffers\n",
                        (unsigned long)n);
                free(a); free(b); free(c); free(d);
                cft_close(dev);
                return 2;
            }
        }
    }

    if (csv) {
        printf("format,bytes_per_elem,op,ns_per_elem,elems_per_s,"
               "mb_per_s,reps,seconds\n");
    } else {
        cft_caps bcaps;
        memset(&bcaps, 0, sizeof bcaps);
        bcaps.struct_size = sizeof bcaps;
        printf("cft-bench: %s\n", artifact ? artifact : "software backend");
        if (resident && cft_get_caps(dev, &bcaps) == CFT_OK)
            printf("operands in cft_alloc'd buffers, published once; "
                   "this backend %s device copies\n",
                   bcaps.buffers_resident ? "KEEPS" : "keeps no");
        printf("%lu elements per call, >=%.2gs per measurement, "
               "exponent spread +/-%d\n\n",
               (unsigned long)n, target_s, spread);
        printf("%-7s %5s  %-8s %12s %12s %10s\n",
               "format", "B/el", "op", "ns/elem", "Melem/s", "MB/s");
        printf("%-7s %5s  %-8s %12s %12s %10s\n",
               "------", "----", "--------", "-----------", "-----------",
               "---------");
    }

    for (f = 0; f < 4; f++) {
        cft_format fmt = (cft_format)f;
        size_t sz = cft_format_size(fmt);

        base_ns[f] = 0.0;
        if (only_fmt >= 0 && f != only_fmt) continue;

        fill(a, fmt, n, spread);
        fill(b, fmt, n, spread);
        fill(c, fmt, n, spread);

        /* Filled once and published once. Everything after this point
         * is runs, which is exactly the shape a caller who cares about
         * throughput writes - and exactly what makes the columns below
         * a statement about the engine. */
        if (resident) {
            if (cft_buffer_to_device(ba) != CFT_OK ||
                cft_buffer_to_device(bb) != CFT_OK ||
                cft_buffer_to_device(bc) != CFT_OK ||
                cft_buffer_to_device(bd) != CFT_OK) {
                fprintf(stderr, "cft_buffer_to_device: %s\n",
                        cft_last_error());
                verify_bad++;
            }
            memcpy(va, a, vn * sz);
            memcpy(vb, b, vn * sz);
            memcpy(vc, c, vn * sz);
        }

        for (o = 0; o < NOPS; o++) {
            cft_op op = OPS[o];
            struct result r;
            double mbps;

            if (!cft_supports(dev, op, fmt)) {
                if (!csv)
                    printf("%-7s %5lu  %-8s %12s\n", cft_format_name(fmt),
                           (unsigned long)sz, cft_op_name(op), "unsupported");
                continue;
            }

            r = time_op(dev, op, fmt, a, b, c, d, n, target_s);
            if (r.st != CFT_OK) {
                fprintf(stderr, "%s %s: %s\n  %s\n", cft_format_name(fmt),
                        cft_op_name(op), cft_strerror(r.st), cft_last_error());
                /* a..d are the buffers' own mirrors under --resident,
                 * so they are released by cft_buffer_free and never by
                 * free(). */
                if (resident) {
                    cft_buffer_free(ba); cft_buffer_free(bb);
                    cft_buffer_free(bc); cft_buffer_free(bd);
                    free(va); free(vb); free(vc); free(vd); free(vg);
                } else {
                    free(a); free(b); free(c); free(d);
                }
                cft_close(dev);
                return 1;
            }

            /* The rate is checked, not merely timed.
             *
             * The result buffer is brought home and the same call is
             * made again on plain host pointers over a bounded prefix;
             * the two must agree byte for byte and flag for flag. A
             * resident path that served a stale copy would print a
             * beautiful number here and this is what refuses to let it.
             *
             * It happens AFTER the timed loop, so it costs the
             * measurement nothing - and the read back leaves the
             * mirror authoritative, which is why the operands are
             * republished for the next op. */
            if (resident) {
                uint32_t f1 = 0, f2 = 0;
                cft_status s1, s2;
                s1 = (cft_status)cft_buffer_from_device(bd);
                memcpy(vg, d, vn * sz);
                s2 = cft_run(dev, op, fmt, CFT_RNE, va, vb, vc, vd, vn,
                             &f1, NULL);
                (void)f2;
                verified++;
                if (s1 != CFT_OK || s2 != CFT_OK ||
                    memcmp(vg, vd, vn * sz) != 0) {
                    fprintf(stderr,
                            "%s %s: the resident result does not match "
                            "the host-pointer path over the first %lu "
                            "elements (%s / %s)\n",
                            cft_format_name(fmt), cft_op_name(op),
                            (unsigned long)vn, cft_strerror(s1),
                            cft_strerror(s2));
                    verify_bad++;
                }
                if (cft_buffer_to_device(ba) != CFT_OK ||
                    cft_buffer_to_device(bb) != CFT_OK ||
                    cft_buffer_to_device(bc) != CFT_OK ||
                    cft_buffer_to_device(bd) != CFT_OK)
                    verify_bad++;
            }

            /* Bytes the call actually moves: three operands in, one
             * out. ABS and NEG read one, but charging them all four
             * would flatter them; count what the op reads. */
            {
                int nin = (op == CFT_ABS || op == CFT_NEG) ? 1 : 3;
                mbps = r.elems_per_s * (double)sz * (double)(nin + 1) / 1e6;
            }

            if (op == CFT_FMA) base_ns[f] = r.ns_per_elem;

            if (csv) {
                printf("%s,%lu,%s,%.4f,%.0f,%.1f,%d,%.4f\n",
                       cft_format_name(fmt), (unsigned long)sz,
                       cft_op_name(op), r.ns_per_elem, r.elems_per_s,
                       mbps, r.reps, r.seconds);
            } else {
                printf("%-7s %5lu  %-8s %12.2f %12.3f %10.1f\n",
                       cft_format_name(fmt), (unsigned long)sz,
                       cft_op_name(op), r.ns_per_elem,
                       r.elems_per_s / 1e6, mbps);
            }
        }
        if (!csv) printf("\n");
    }

    /* The comparison everyone actually wants: what does width cost?
     * Reported against fp32 FMA, and only when both were measured. */
    if (!csv && only_fmt < 0 && base_ns[0] > 0.0) {
        printf("FMA cost relative to fp32:\n");
        for (f = 0; f < 4; f++)
            if (base_ns[f] > 0.0)
                printf("  %-6s %6.1fx   (%.1f bytes/elem, %.0fx the width)\n",
                       cft_format_name((cft_format)f),
                       base_ns[f] / base_ns[0],
                       (double)cft_format_size((cft_format)f),
                       (double)cft_format_size((cft_format)f) / 4.0);
    }

    /* What residency actually got. A mechanism that quietly staged
     * every call would produce the same table and none of the point,
     * so the counters are printed beside the rates rather than left
     * to be inferred from them. */
    if (resident && !csv) {
        cft_buffer_info bi;
        memset(&bi, 0, sizeof bi);
        bi.struct_size = sizeof bi;
        if (cft_buffer_get_info(ba, &bi) == CFT_OK) {
            printf("\nthe `a` buffer: %s, %llu binding%s served from a "
                   "device copy with no transfer, %llu copied\n",
                   bi.resident ? "device copies live" : "no device copies",
                   (unsigned long long)bi.resident_binds,
                   bi.resident_binds == 1 ? "" : "s",
                   (unsigned long long)bi.staged_binds);
            if (bi.staged_why[0])
                printf("  the last copy was made because: %s\n",
                       bi.staged_why);
        }
        printf("%d row%s checked against the host-pointer path over the "
               "first %lu elements: %s\n",
               verified, verified == 1 ? "" : "s", (unsigned long)vn,
               verify_bad ? "SOME DIFFER" : "identical");
    }

    if (resident) {
        cft_buffer_free(ba); cft_buffer_free(bb);
        cft_buffer_free(bc); cft_buffer_free(bd);
        free(va); free(vb); free(vc); free(vd); free(vg);
    } else {
        free(a); free(b); free(c); free(d);
    }
    cft_close(dev);
    return verify_bad ? 1 : 0;
}
