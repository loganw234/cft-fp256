/* hx_probe.c - parcel HX's probe of the card's rates at fp64, fp128 and fp256
 * (docs/studies/HX-wide-sweeps.md). Scratch beside the study: nothing in
 * the tree builds or imports it.
 *
 * For each format and operation it fills one call's worth of operands
 * (N = 4096, the soak tools' BATCH and the library's CFT_CHUNK), makes the
 * call once on the device and once on the software backend and compares
 * every element's bytes and the call's flags, then times the device call
 * back to back for a few seconds. So each rate comes with a check, and
 * HX_PROBE_SABOTAGE=1 flips one bit of the device's first result before
 * the comparison: the check must then report one element different (the
 * control that shows it can fail).
 *
 *   hx-probe <artifact.xclbin | -> <seconds an operation>
 *
 * "-" runs the software backend on both sides (a test of this file only).
 * One line an (operation, format); exit 0 when every check is equal,
 * 1 when one is not, 2 on a usage or open error.
 *
 * Operands: normal values, exponents within 8 of the bias, every fraction
 * bit random (xorshift64, fixed seed); square root takes them positive.
 * The operations are the ones a wide sweep would run: cft_div, cft_sqrt,
 * cft_rint (exact = 0), cft_scaleb (n = 3) and cft_run's FMA, MUL and ADD,
 * all under roundTiesToEven.
 */
#define _POSIX_C_SOURCE 200112L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"

#define N 4096

static uint64_t rs = 0x9E3779B97F4A7C15ull;
static uint64_t rng(void)
{
    rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17;
    return rs;
}

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* one encoding of W bytes: random fraction, the given sign, an exponent
 * within 8 of the bias; the top 32 bits hold sign, exponent and the
 * fraction's top bits at every format here (ew <= 19) */
static void fill(uint8_t *e, int W, int ew, int positive)
{
    int i;
    uint32_t top, bias = (1u << (ew - 1)) - 1;
    uint32_t bexp = bias + (uint32_t)(rng() % 17) - 8;
    uint32_t sign = positive ? 0 : (uint32_t)(rng() & 1);
    for (i = 0; i < W; i++)
        e[i] = (uint8_t)rng();
    memcpy(&top, e + W - 4, 4);                  /* little-endian host */
    top = (sign << 31) | (bexp << (31 - ew)) | (top & ((1u << (31 - ew)) - 1));
    memcpy(e + W - 4, &top, 4);
}

enum { P_DIV, P_SQRT, P_RINT, P_SCALEB, P_FMA, P_MUL, P_ADD, P_NOPS };
static const char *PNAME[P_NOPS] = { "div", "sqrt", "rint", "scaleb", "fma", "mul", "add" };

static cft_status call(cft_device *dv, int op, cft_format f, const uint8_t *a,
                       const uint8_t *b, const uint8_t *c, uint8_t *d, uint32_t *fl)
{
    switch (op) {
    case P_DIV:    return cft_div(dv, f, CFT_RNE, a, b, d, N, fl, NULL);
    case P_SQRT:   return cft_sqrt(dv, f, CFT_RNE, a, d, N, fl, NULL);
    case P_RINT:   return cft_rint(dv, f, CFT_RNE, 0, a, d, N, fl, NULL);
    case P_SCALEB: return cft_scaleb(dv, f, CFT_RNE, a, 3, d, N, fl, NULL);
    case P_FMA:    return cft_run(dv, CFT_FMA, f, CFT_RNE, a, b, c, d, N, fl, NULL);
    case P_MUL:    return cft_run(dv, CFT_MUL, f, CFT_RNE, a, b, c, d, N, fl, NULL);
    default:       return cft_run(dv, CFT_ADD, f, CFT_RNE, a, b, c, d, N, fl, NULL);
    }
}

int main(int argc, char **argv)
{
    static const struct { cft_format f; const char *name; int W, ew; } FM[] = {
        { CFT_FP64, "fp64", 8, 11 }, { CFT_FP128, "fp128", 16, 15 }, { CFT_FP256, "fp256", 32, 19 } };
    const char *art;
    double secs;
    cft_device *dev = NULL, *sw = NULL;
    int fi, op, bad = 0, sabotage;
    uint8_t *a, *b, *c, *d, *r;
    if (argc != 3) {
        fprintf(stderr, "usage: hx-probe <artifact.xclbin | -> <seconds an operation>\n");
        return 2;
    }
    art = strcmp(argv[1], "-") ? argv[1] : NULL;
    secs = strtod(argv[2], NULL);
    sabotage = getenv("HX_PROBE_SABOTAGE") && !strcmp(getenv("HX_PROBE_SABOTAGE"), "1");
    if (cft_open(art, 0, &dev) != CFT_OK || cft_open(NULL, 0, &sw) != CFT_OK) {
        fprintf(stderr, "hx-probe: cannot open %s: %s\n", art ? art : "software", cft_last_error());
        return 2;
    }
    printf("hx-probe: %s backend%s%s, N %d, %.1f s an operation%s\n", art ? "DEVICE" : "software",
           art ? ": " : "", art ? art : "", N, secs, sabotage ? ", SABOTAGE (one bit flipped)" : "");
    a = malloc(32 * N); b = malloc(32 * N); c = malloc(32 * N); d = malloc(32 * N); r = malloc(32 * N);
    if (!a || !b || !c || !d || !r)
        return 2;
    for (fi = 0; fi < 3; fi++) {
        int W = FM[fi].W, i;
        for (op = 0; op < P_NOPS; op++) {
            uint32_t fd = 0, fs = 0;
            int calls = 0, eq = 0;
            double t0, t1;
            cft_status st, ss;
            for (i = 0; i < N; i++) {
                fill(a + (size_t)i * W, W, FM[fi].ew, op == P_SQRT);
                fill(b + (size_t)i * W, W, FM[fi].ew, 0);
                fill(c + (size_t)i * W, W, FM[fi].ew, 0);
            }
            st = call(dev, op, FM[fi].f, a, b, c, d, &fd);
            ss = call(sw, op, FM[fi].f, a, b, c, r, &fs);
            if (st != CFT_OK || ss != CFT_OK) {
                printf("hx-probe %s %s: FAILED, device %s, software %s\n", FM[fi].name, PNAME[op],
                       cft_strerror(st), cft_strerror(ss));
                bad = 1;
                continue;
            }
            if (sabotage)
                d[0] ^= 1;
            for (i = 0; i < N; i++)
                eq += !memcmp(d + (size_t)i * W, r + (size_t)i * W, (size_t)W);
            t0 = now_s();
            do {
                st = call(dev, op, FM[fi].f, a, b, c, d, &fd);
                calls++;
                t1 = now_s();
            } while (st == CFT_OK && (calls < 3 || t1 - t0 < secs));
            if (st != CFT_OK || eq != N || fd != fs)
                bad = 1;
            printf("hx-probe %s %s: N %d, calls %d, %.1f ns an element, %.4f M/s, check %d of %d equal, "
                   "flags device 0x%02x software 0x%02x%s\n", FM[fi].name, PNAME[op], N, calls,
                   (t1 - t0) * 1e9 / ((double)calls * N), (double)calls * N / (t1 - t0) / 1e6, eq, N,
                   (unsigned)fd, (unsigned)fs, st == CFT_OK ? "" : ", TIMED CALL FAILED");
            fflush(stdout);
        }
    }
    printf("hx-probe: %s\n", bad ? "A CHECK FAILED" : "every check equal");
    cft_close(dev);
    cft_close(sw);
    return bad;
}
