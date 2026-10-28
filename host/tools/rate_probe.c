/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * rate-probe - the card's own rate for each operation and format, with the oracle off (parcel TP,
 * docs/CARDDAY.md "The card's rates"). It is parcel HX's probe (docs/studies/hx/hx_probe.c) made a tool: built
 * the way the soak tools are (host/Makefile, the XRT and software backends), driven by hw/card_stress.py's
 * probe leg (--rate-probe), and read by hw/card_stress_lib.py's parse_rate_probe.
 *
 *   rate-probe <artifact.xclbin | -> <seconds a row>
 *
 * "-" runs the software backend on both sides (a test of this file only). For each format (fp32, fp64, fp128,
 * fp256) and each operation (div, sqrt, rint, scaleb, fma, mul, add) it
 *   1. fills one call's worth of operands (N = 4096, the soaks' BATCH and the library's CFT_CHUNK),
 *   2. makes the call once on the device and once on the software backend, and compares every element's bytes and
 *      the call's flags - THE CHECK, the only reference this tool computes, and not in the timed part,
 *   3. only if the device answered, times the device call back to back for the stated seconds (at least 3 calls).
 * "Oracle off" is the third step: nothing is computed per element but the card's own answer. The check stays,
 * because a rate measured on wrong answers is worth nothing. An (operation, format) the device cannot run - the
 * library answers anything but CFT_OK to the checking call, for example CFT_ERR_UNSUPPORTED for a format the
 * image lacks - is REFUSED, by the library's own name for it, and never timed.
 *
 * The tiles it measures are the ones CFT_XRT_TILES names (host/src/tile_select.h; the 1-based ordinals), or all
 * of them when it is unset; the row says which in its `tile=`. The driver runs one process on tile 1 alone and, on
 * the quad, four at once, one a tile (the shape of the sweep's waves).
 *
 * CFT_RATE_PROBE_SABOTAGE is the negative control, as the soaks' CFT_SOAK_SABOTAGE has two modes. =1 flips the low bit
 * of the device's first result of every row before the comparison, so every check must read one element different;
 * =2 flips the low bit of the device's flags instead, so every check must read the flags different and no element.
 * Either way the run must exit 1, and the driver's leg must be a failure.
 *
 * Output, one line a thing, every line starting "rate-probe: " (hw/card_stress_lib.py holds this grammar):
 *   rate-probe: backend DEVICE <artifact> | backend software
 *   rate-probe: N 4096, <s> s a row, tile <ordinals | all | none>[, SABOTAGE (one bit flipped)]
 *   rate-probe: row op=<op> format=<fmt> tile=<t> elements=<n> seconds=<s> rate=<elements a second> check=ok
 *   rate-probe: row op=<op> format=<fmt> tile=<t> elements=<n> seconds=<s> rate=<r> check=red mismatched=<k> flags_device=0x<h> flags_software=0x<h>
 *   rate-probe: row op=<op> format=<fmt> tile=<t> refused=<CFT_ERR_NAME> why=<the library's sentences>
 *   rate-probe: row op=<op> format=<fmt> tile=<t> timed_call_failed=<CFT_ERR_NAME> after=<calls> why=<sentences>
 *   rate-probe: <rows> rows, <timed> timed, <refused> refused, <red> red
 *   rate-probe: every check ok | rate-probe: A CHECK FAILED
 * Exit 0 when no row is red (a refusal is named, and is not a failure); 1 when one is; 2 on a usage or open error.
 *
 * Operands: normal values, exponents within 8 of the bias, every fraction bit random (xorshift64, a fixed seed);
 * square root takes them positive. The operations are the ones a wide sweep runs: cft_div, cft_sqrt, cft_rint
 * (exact = 0), cft_scaleb (n = 3) and cft_run's FMA, MUL and ADD, all under roundTiesToEven.
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

/* one encoding of W bytes: random fraction, the given sign, an exponent within 8 of the bias; the top 32 bits hold
 * sign, exponent and the fraction's top bits at every format here (ew <= 19) */
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
static const char *const PNAME[P_NOPS] = { "div", "sqrt", "rint", "scaleb", "fma", "mul", "add" };

static const struct { cft_format f; const char *name; int W, ew; } FM[] = {
    { CFT_FP32, "fp32", 4, 8 }, { CFT_FP64, "fp64", 8, 11 }, { CFT_FP128, "fp128", 16, 15 }, { CFT_FP256, "fp256", 32, 19 } };
#define NFM ((int)(sizeof FM / sizeof FM[0]))

static cft_status call(cft_device *dv, int op, cft_format f, const uint8_t *a, const uint8_t *b, const uint8_t *c,
                       uint8_t *d, uint32_t *fl)
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

/* the library's name for a status: the enumerator, which is what a reader greps for (cft_strerror is the sentence) */
static const char *sname(cft_status s)
{
    switch (s) {
    case CFT_OK:                  return "CFT_OK";
    case CFT_ERR_INVALID_ARGUMENT: return "CFT_ERR_INVALID_ARGUMENT";
    case CFT_ERR_UNSUPPORTED:     return "CFT_ERR_UNSUPPORTED";
    case CFT_ERR_NO_DEVICE:       return "CFT_ERR_NO_DEVICE";
    case CFT_ERR_ARTIFACT:        return "CFT_ERR_ARTIFACT";
    case CFT_ERR_BUS_FAULT:       return "CFT_ERR_BUS_FAULT";
    case CFT_ERR_OUT_OF_MEMORY:   return "CFT_ERR_OUT_OF_MEMORY";
    case CFT_ERR_TIMEOUT:         return "CFT_ERR_TIMEOUT";
    case CFT_ERR_INTERNAL:        return "CFT_ERR_INTERNAL";
    }
    return "CFT_ERR_UNKNOWN";
}

/* the library's sentences for a failed call, on one line with no newline in it (the row ends at its newline) */
static void why(char *out, size_t cap, cft_status st)
{
    const char *a = cft_strerror(st), *b = cft_last_error();
    size_t i;
    snprintf(out, cap, "%s%s%s", a ? a : "", (b && b[0]) ? ": " : "", (b && b[0]) ? b : "");
    for (i = 0; out[i]; i++)
        if (out[i] == '\n' || out[i] == '\r')
            out[i] = ' ';
}

int main(int argc, char **argv)
{
    const char *art, *tiles_env;
    char tile[96], sentence[512];
    double secs;
    cft_device *dev = NULL, *sw = NULL;
    int fi, op, rows = 0, timed = 0, refused = 0, red = 0, sabotage;
    uint8_t *a, *b, *c, *d, *r;
    if (argc != 3) {
        fprintf(stderr, "usage: rate-probe <artifact.xclbin | -> <seconds a row>\n");
        return 2;
    }
    art = strcmp(argv[1], "-") ? argv[1] : NULL;
    secs = strtod(argv[2], NULL);
    if (!(secs > 0.0) || secs > 600.0) {
        fprintf(stderr, "rate-probe: <seconds a row> must be above 0 and at most 600, not \"%s\"\n", argv[2]);
        return 2;
    }
    sabotage = getenv("CFT_RATE_PROBE_SABOTAGE") ? (!strcmp(getenv("CFT_RATE_PROBE_SABOTAGE"), "1") ? 1 : !strcmp(getenv("CFT_RATE_PROBE_SABOTAGE"), "2") ? 2 : 0) : 0;
    tiles_env = getenv("CFT_XRT_TILES");
    /* the `tile=` of every row: the ordinals this process was handed, or "all" (it opens every tile its image has),
     * or "none" (the software backend has no tiles) */
    snprintf(tile, sizeof tile, "%s", art ? ((tiles_env && tiles_env[0]) ? tiles_env : "all") : "none");
    if (cft_open(art, 0, &dev) != CFT_OK || cft_open(NULL, 0, &sw) != CFT_OK) {
        fprintf(stderr, "rate-probe: cannot open %s: %s\n", art ? art : "the software backend", cft_last_error());
        return 2;
    }
    printf("rate-probe: backend %s%s%s\n", art ? "DEVICE" : "software", art ? " " : "", art ? art : "");
    printf("rate-probe: N %d, %g s a row, tile %s%s\n", N, secs, tile, sabotage ? ", SABOTAGE (one bit flipped)" : "");
    fflush(stdout);
    a = malloc(32 * (size_t)N); b = malloc(32 * (size_t)N); c = malloc(32 * (size_t)N);
    d = malloc(32 * (size_t)N); r = malloc(32 * (size_t)N);
    if (!a || !b || !c || !d || !r)
        return 2;
    for (fi = 0; fi < NFM; fi++) {
        int W = FM[fi].W, i;
        for (op = 0; op < P_NOPS; op++) {
            uint32_t fd = 0, fs = 0, fchk;
            unsigned long long calls = 0;
            int eq = 0, same;
            double t0, t1;
            cft_status st, ss;
            rows++;
            for (i = 0; i < N; i++) {
                fill(a + (size_t)i * W, W, FM[fi].ew, op == P_SQRT);
                fill(b + (size_t)i * W, W, FM[fi].ew, 0);
                fill(c + (size_t)i * W, W, FM[fi].ew, 0);
            }
            st = call(dev, op, FM[fi].f, a, b, c, d, &fd);
            if (st != CFT_OK) {                         /* the device cannot run it: refused by name, never timed */
                why(sentence, sizeof sentence, st);
                printf("rate-probe: row op=%s format=%s tile=%s refused=%s why=%s\n", PNAME[op], FM[fi].name, tile, sname(st), sentence);
                fflush(stdout);
                refused++;
                continue;
            }
            ss = call(sw, op, FM[fi].f, a, b, c, r, &fs);
            if (ss != CFT_OK) {                         /* nothing to hold the device's answer to: the same refusal, named for the reference */
                why(sentence, sizeof sentence, ss);
                printf("rate-probe: row op=%s format=%s tile=%s refused=%s why=the software backend, the reference of the check, answers %s\n",
                       PNAME[op], FM[fi].name, tile, sname(ss), sentence);
                fflush(stdout);
                refused++;
                continue;
            }
            if (sabotage == 1)
                d[0] ^= 1;
            else if (sabotage == 2)
                fd ^= 1;
            for (i = 0; i < N; i++)
                eq += !memcmp(d + (size_t)i * W, r + (size_t)i * W, (size_t)W);
            /* THE CHECK is made here, on the checking call: the timed calls below write the flags again, and a check made after them would
             * compare the last timed call's flags and let a flag the checking call got wrong go by (sabotage 2 found that in this file's first draft) */
            same = eq == N && fd == fs;
            fchk = fd;
            t0 = now_s();
            do {
                st = call(dev, op, FM[fi].f, a, b, c, d, &fd);
                calls++;
                t1 = now_s();
            } while (st == CFT_OK && (calls < 3 || t1 - t0 < secs));
            if (st != CFT_OK) {
                why(sentence, sizeof sentence, st);
                printf("rate-probe: row op=%s format=%s tile=%s timed_call_failed=%s after=%llu why=%s\n", PNAME[op], FM[fi].name, tile,
                       sname(st), calls, sentence);
                fflush(stdout);
                red++;
                continue;
            }
            timed++;
            printf("rate-probe: row op=%s format=%s tile=%s elements=%llu seconds=%.4f rate=%.1f", PNAME[op], FM[fi].name, tile,
                   calls * (unsigned long long)N, t1 - t0, (double)calls * N / (t1 - t0));
            if (same) {
                printf(" check=ok\n");
            } else {
                printf(" check=red mismatched=%d flags_device=0x%02x flags_software=0x%02x\n", N - eq, (unsigned)fchk, (unsigned)fs);
                red++;
            }
            fflush(stdout);
        }
    }
    printf("rate-probe: %d rows, %d timed, %d refused, %d red\n", rows, timed, refused, red);
    printf("rate-probe: %s\n", red ? "A CHECK FAILED" : "every check ok");
    cft_close(dev);
    cft_close(sw);
    return red ? 1 : 0;
}
