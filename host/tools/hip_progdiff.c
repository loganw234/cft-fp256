/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * hip-progdiff - the GPU backend's fixed tier INSIDE PROGRAMS held to its
 * generic tier on a GPU, lane by lane, through the public API (round 3's
 * G3B):
 *
 *   hip-progdiff diff N SEED [--op fma|add|sub|mul] [--stream study|edge]
 *                            [--format fp256|fp128] [--base B] [--sw K]
 *                            [--device D]
 *
 * runs lanes B to B + N - 1 of a counter-based stream (tools/fx256_stream.h
 * at fp256, tools/fx128_stream.h at fp128 - hip-fmadiff's streams, so lane
 * i is hip-fmadiff's case i: its a, b, c and attribute, ADD and SUB prepared
 * as hip-fmadiff prepares them) as PROGRAM LANES on two handles of hip:D,
 * one opened with CFT_HIP_TIER=generic (the executor on libcft's
 * arithmetic, k_seq) and one with CFT_HIP_TIER=fixed (k_seq_fx at fp256,
 * k_seq_fx128 at fp128: FMA, ADD, SUB and MUL on the second
 * implementation), each program at each of the five attributes run on the
 * lanes of that attribute. Two programs:
 *
 *   one     op r3, r0, r1, r2; deposit r3; halt
 *   chain   sixteen instructions: the op, then FMA, ADD, SUB and MUL on its
 *           results, MIN, MAX, ABS, NEG, SELECT and IMUL (which run
 *           cft_sf_compute inside the fixed kernel) and the op again on
 *           mixed results, three deposits and a halt
 *
 * each STAGED (host arrays) and RESIDENT (a, b, c and the deposits in
 * cft_alloc buffers of each handle, published at each run): the deposits,
 * the lane bytes (R23), the counts, the run's flags and its STATUS compared
 * byte for byte between the two handles, and for the first K lanes of the
 * first chunk (--sw, default 65536) with the software handle too; on those
 * K lanes the fixed handle's one-instruction runs are also held to the
 * stream's own fixed lane on the host (fxs_fixed_lane, fxs128_fixed_lane:
 * the steer and the lane k_run256 and k_run128 call), the deposit and the
 * lane byte, whose three bits above the five flags must be clear. The
 * lanes are drawn on the HOST (the generator's reference lane is libcft.a's
 * own cft_sf_compute), in chunks of at most 2^19, so a count here is far
 * below hip-fmadiff's on-device 2^30. In a plant build (HIP_PLANTS=1) the
 * route is read from the build's probe (cfth_plant_tier_probe's ninth value
 * on) after every run: the fixed kernel on the fixed handle, k_seq on the
 * generic one; a default build cannot read it and says so.
 *
 * A line for each program and mode, then the last line in hip-fmadiff's
 * form: the format, op and stream, the cases, the base and seed, the
 * device, the lanes differing, the first chunk's sha256s of the inputs and
 * of each handle's outputs, the milliseconds (generation, generic, fixed),
 * the wall time, the plants and GREEN or RED; exit 0 when nothing differs,
 * 1 when anything does, 2 when the run could not be made. A set
 * CFT_HIP_PLANT on a library with no plants (no cfth_plant_tier_probe) is
 * refused by name, exit 2: the run would be green for a plant it never
 * applied.
 *
 * What this holds is the PLUMBING of the program kernels on a stream aimed
 * at the FMA's edges: the executor's lane ALU wrapper, the type bridge, the
 * route, deposits, lane bytes and counts, chunks and resident windows.
 * The lane arithmetic is hip-fmadiff's and fma256test's to hold; the
 * classes and the fields the executor reads are hip-test progtier's.
 * No operand is ever held in a double.
 */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"
#include "../src/softfloat.h"
#include "../src/sha256.h"
/* the streams need the two fixed headers (their fixed lanes, which this
 * tool does not call), and their loops carry `#pragma unroll` (host/Makefile
 * builds this file with -Wno-unknown-pragmas, as fma256test) */
#include "../src/fma256_fixed.h"
#include "../src/fma128_fixed.h"
#include "fx256_stream.h"
#include "fx128_stream.h"

/* the plant build's route instrument (backend_hip.cpp), weak: NULL in a
 * default build, where the library has none */
#if defined(__GNUC__) && !defined(_WIN32)
extern int cfth_plant_tier_probe(uint64_t *out, int nout) __attribute__((weak));
#define PD_PROBE_FN cfth_plant_tier_probe
#else
#define PD_PROBE_FN NULL
#endif

enum { PD_CHUNK = 1 << 19, PD_NPROG = 2, PD_MAXDEP = 3 };
static const char *const PD_OPN[4] = {"fma", "add", "sub", "mul"};
static const char *const PD_PROGN[PD_NPROG] = {"one", "chain"};

static double now_ms(void)
{
#ifdef _WIN32
    return (double)clock() * 1e3 / CLOCKS_PER_SEC;
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
#endif
}

static void put_env(const char *name, const char *value)
{
#ifdef _WIN32
    char buf[200];
    snprintf(buf, sizeof buf, "%s=%s", name, value ? value : "");
    _putenv(buf);
#else
    if (value)
        setenv(name, value, 1);
    else
        unsetenv(name);
#endif
}

static uint64_t alu(unsigned op, unsigned rd, unsigned ra, unsigned rb, unsigned rc, unsigned rnd)
{
    return (uint64_t)op | ((uint64_t)rd << 8) | ((uint64_t)ra << 12) | ((uint64_t)rb << 16) |
           ((uint64_t)rc << 20) | ((uint64_t)rnd << 24);
}

static uint64_t ctl(unsigned code, unsigned ra)
{
    return (uint64_t)code | ((uint64_t)ra << 12) | ((uint64_t)1 << 31);
}

/* program `prog` (0 one, 1 chain) of operation op at attribute rnd and
 * format fmt: its image's bytes, and its deposits a lane */
static size_t image(unsigned char *img, int fmt, int prog, int op, int rnd, uint32_t *md)
{
    uint64_t w[16];
    uint32_t hdr[8];
    unsigned n = 0, j, k;
    const unsigned o = (unsigned)op, r = (unsigned)rnd;
    if (prog == 0) {
        w[n++] = alu(o, 3, 0, 1, 2, r);
        w[n++] = ctl(3, 3);
        *md = 1;
    } else {
        w[n++] = alu(o, 3, 0, 1, 2, r);                  /* the op on the lane */
        w[n++] = alu(CFT_SF_FMA, 4, 0, 1, 3, r);          /* a*b + r3 */
        w[n++] = alu(CFT_SF_ADD, 5, 3, 1, 2, r);          /* r3 + c */
        w[n++] = alu(CFT_SF_SUB, 6, 4, 1, 5, r);          /* r4 - r5 */
        w[n++] = alu(CFT_SF_MUL, 7, 6, 0, 2, r);          /* r6 * a */
        w[n++] = alu(CFT_SF_MIN, 8, 7, 3, 0, 0);
        w[n++] = alu(CFT_SF_MAX, 9, 6, 4, 0, 0);
        w[n++] = alu(CFT_SF_ABS, 10, 8, 0, 0, 0);
        w[n++] = alu(CFT_SF_NEG, 11, 9, 0, 0, 0);
        w[n++] = alu(CFT_SF_SELECT, 12, 10, 11, 7, 0);    /* r7 != 0 ? r10 : r11 */
        w[n++] = alu(30, 13, 3, 0, 0, 0);                 /* IMUL: an integer pattern */
        w[n++] = alu(o, 14, 12, 13, 6, r);                /* the op again, mixed */
        w[n++] = ctl(3, 3);
        w[n++] = ctl(3, 12);
        w[n++] = ctl(3, 14);
        *md = 3;
    }
    w[n++] = (uint64_t)1 << 31;                           /* halt */
    hdr[0] = 0x50544643u; hdr[1] = 1; hdr[2] = n; hdr[3] = 0;
    hdr[4] = *md; hdr[5] = (uint32_t)fmt; hdr[6] = 0; hdr[7] = 0;
    for (j = 0; j < 8; j++)
        for (k = 0; k < 4; k++)
            img[4 * j + k] = (unsigned char)(hdr[j] >> (8 * k));
    for (j = 0; j < n; j++)
        for (k = 0; k < 8; k++)
            img[32 + 8 * j + k] = (unsigned char)(w[j] >> (8 * k));
    return 32 + 8 * (size_t)n;
}

/* one handle's outputs of one run */
typedef struct {
    unsigned char *dep, *lf;
    uint32_t *cnt, flags, bus;
} pd_out;

static int pd_alloc_out(pd_out *o, size_t n, size_t esz)
{
    o->dep = malloc(n * PD_MAXDEP * esz + 1);
    o->lf = malloc(n + 1);
    o->cnt = malloc(n * 4 + 4);
    return o->dep && o->lf && o->cnt;
}

/* lanes whose deposits, lane byte or count differ between x and y */
static long pd_lanes_differ(const pd_out *x, const pd_out *y, size_t n, size_t db, long *first)
{
    long bad = 0;
    size_t i;
    for (i = 0; i < n; i++)
        if (memcmp(x->dep + i * db, y->dep + i * db, db) || x->lf[i] != y->lf[i] ||
            x->cnt[i] != y->cnt[i]) {
            if (!bad && first)
                *first = (long)i;
            bad++;
        }
    return bad;
}

static void hexle(const unsigned char *p, char *out, size_t esz)
{
    size_t i;
    for (i = 0; i < esz; i++)
        sprintf(out + 2 * i, "%02x", p[esz - 1 - i]);
}

int main(int argc, char **argv)
{
    static char art[32];
    const char *pv = getenv("CFT_HIP_PLANT"), *tv = getenv("CFT_HIP_TIER");
    int (*probe)(uint64_t *, int) = PD_PROBE_FN;
    int op = CFT_SF_FMA, stream = FXS_STUDY, fmt = 3, device = 0, npos = 0, i;
    long long base0 = 0, swk = 65536;
    const char *pos[2] = {NULL, NULL};
    char keep_tier[64] = "";
    cft_device *hg = NULL, *hf = NULL, *sw = NULL;
    cft_program *pg[PD_NPROG][5], *pf[PD_NPROG][5], *ps[PD_NPROG][5];
    uint32_t mdp[PD_NPROG];
    long long total;
    uint64_t seed;
    size_t esz, chunk;
    double t_gen = 0, t_g = 0, t_f = 0;
    const double w0 = now_ms();
    long lanes_bad[PD_NPROG][2], words_bad[PD_NPROG][2], sw_bad[PD_NPROG] = {0, 0};
    long route_read = 0, route_bad = 0, sw_lanes = 0, lane_n = 0, lane_bad = 0;
    long first_bad = -1;
    char hx[3][65] = {"", "", ""};
    unsigned char *a, *b, *c, *rr, *ga, *gb, *gc;
    pd_out og, of, os;
    cft_buffer *B[2][4];
    int p, m, r, h;

    /* a plant this library cannot apply is refused before anything runs */
    if (pv && *pv && !probe) {
        fprintf(stderr, "hip-progdiff: CFT_HIP_PLANT=\"%s\" is set, and this libcft is a default "
                        "build (no cfth_plant_tier_probe), which has no plants and never reads "
                        "the variable: the run would be green for a plant it did not apply. "
                        "Build with HIP_PLANTS=1, or unset CFT_HIP_PLANT\n", pv);
        return 2;
    }
    if (argc < 2 || strcmp(argv[1], "diff")) {
        fprintf(stderr, "usage: %s diff N SEED [--op fma|add|sub|mul] [--stream study|edge] "
                "[--format fp256|fp128] [--base B] [--sw K] [--device D]\n", argv[0]);
        return 2;
    }
    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--op") && i + 1 < argc) {
            const char *v = argv[++i];
            for (op = 0; op < 4 && strcmp(v, PD_OPN[op]); op++)
                ;
            if (op == 4) {
                fprintf(stderr, "hip-progdiff: refused: --op %s\n", v);
                return 2;
            }
        } else if (!strcmp(argv[i], "--stream") && i + 1 < argc &&
                   (!strcmp(argv[i + 1], "study") || !strcmp(argv[i + 1], "edge"))) {
            stream = !strcmp(argv[++i], "edge") ? FXS_EDGE : FXS_STUDY;
        } else if (!strcmp(argv[i], "--format") && i + 1 < argc &&
                   (!strcmp(argv[i + 1], "fp256") || !strcmp(argv[i + 1], "fp128"))) {
            fmt = !strcmp(argv[++i], "fp128") ? 2 : 3;
        } else if (!strcmp(argv[i], "--base") && i + 1 < argc) {
            base0 = atoll(argv[++i]);
        } else if (!strcmp(argv[i], "--sw") && i + 1 < argc) {
            swk = atoll(argv[++i]);
        } else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
            device = atoi(argv[++i]);
        } else if (!strncmp(argv[i], "--", 2) || npos == 2) {
            fprintf(stderr, "hip-progdiff: refused: argument '%s' is not one this build knows\n",
                    argv[i]);
            return 2;
        } else {
            pos[npos++] = argv[i];
        }
    }
    if (npos != 2 || atoll(pos[0]) <= 0 || base0 < 0 || swk < 0 || device < 0) {
        fprintf(stderr, "hip-progdiff: refused: diff needs N > 0 and SEED; --base and --sw at "
                        "least 0\n");
        return 2;
    }
    /* a lane plant of the other format's acts on no lane this run makes, so
     * the run would be green for a plant it never applied: refused by name,
     * as hip-fmadiff refuses one (send-back 1) */
    if (pv && *pv) {
        static const char *const lane[4] = {"rmm", "flag", "steer", "mulsign"};
        int q;
        for (q = 0; q < 4; q++) {
            char n256[32], n128[32];
            snprintf(n256, sizeof n256, "seqfx-%s", lane[q]);
            snprintf(n128, sizeof n128, "seqfx128-%s", lane[q]);
            if ((fmt == 2 && !strcmp(pv, n256)) || (fmt == 3 && !strcmp(pv, n128))) {
                fprintf(stderr, "hip-progdiff: refused: CFT_HIP_PLANT=\"%s\" acts on the %s "
                                "lane, and this run is --format %s: it would be green for a "
                                "plant it did not apply. Run it with --format %s\n", pv,
                        fmt == 2 ? "fp256" : "fp128", fmt == 2 ? "fp128" : "fp256",
                        fmt == 2 ? "fp256" : "fp128");
                return 2;
            }
        }
    }
    total = atoll(pos[0]);
    seed = strtoull(pos[1], NULL, 10);
    esz = fmt == 2 ? 16 : 32;
    chunk = total < PD_CHUNK ? (size_t)total : (size_t)PD_CHUNK;
    if (fmt == 3 && !fx256_matches(&cft_sf_formats[3])) {
        fprintf(stderr, "hip-progdiff: fma256_fixed.h's constants are not this libcft's\n");
        return 2;
    }
    if (fmt == 2 && !fx128_matches(&cft_sf_formats[2])) {
        fprintf(stderr, "hip-progdiff: fma128_fixed.h's constants are not this libcft's\n");
        return 2;
    }
    snprintf(art, sizeof art, "hip:%d", device);
    if (tv)
        snprintf(keep_tier, sizeof keep_tier, "%s", tv);
    if (cft_open(NULL, 0, &sw) != CFT_OK) {
        fprintf(stderr, "hip-progdiff: the software handle: %s\n", cft_last_error());
        return 2;
    }
    put_env("CFT_HIP_TIER", "generic");
    if (cft_open(art, 0, &hg) != CFT_OK) {
        fprintf(stderr, "hip-progdiff: %s under CFT_HIP_TIER=generic: %s\n", art, cft_last_error());
        return 2;
    }
    put_env("CFT_HIP_TIER", "fixed");
    if (cft_open(art, 0, &hf) != CFT_OK) {
        fprintf(stderr, "hip-progdiff: %s under CFT_HIP_TIER=fixed: %s\n", art, cft_last_error());
        return 2;
    }
    put_env("CFT_HIP_TIER", keep_tier[0] ? keep_tier : NULL);
    for (p = 0; p < PD_NPROG; p++)
        for (r = 0; r < 5; r++) {
            unsigned char img[32 + 16 * 8];
            const size_t ib = image(img, fmt, p, op, r, &mdp[p]);
            if (cft_program_load(hg, img, ib, &pg[p][r]) != CFT_OK ||
                cft_program_load(hf, img, ib, &pf[p][r]) != CFT_OK ||
                cft_program_load(sw, img, ib, &ps[p][r]) != CFT_OK) {
                fprintf(stderr, "hip-progdiff: loading %s at attribute %d: %s\n", PD_PROGN[p], r,
                        cft_last_error());
                return 2;
            }
        }
    a = malloc(chunk * esz); b = malloc(chunk * esz); c = malloc(chunk * esz);
    rr = malloc(chunk);
    ga = malloc(chunk * esz); gb = malloc(chunk * esz); gc = malloc(chunk * esz);
    if (!a || !b || !c || !rr || !ga || !gb || !gc || !pd_alloc_out(&og, chunk, esz) ||
        !pd_alloc_out(&of, chunk, esz) || !pd_alloc_out(&os, chunk, esz)) {
        fprintf(stderr, "hip-progdiff: out of host memory for a chunk of %zu lanes\n", chunk);
        return 2;
    }
    for (h = 0; h < 2; h++) {
        cft_device *d = h ? hf : hg;
        if (cft_alloc(d, chunk * esz, &B[h][0]) != CFT_OK ||
            cft_alloc(d, chunk * esz, &B[h][1]) != CFT_OK ||
            cft_alloc(d, chunk * esz, &B[h][2]) != CFT_OK ||
            cft_alloc(d, chunk * PD_MAXDEP * esz, &B[h][3]) != CFT_OK) {
            fprintf(stderr, "hip-progdiff: cft_alloc: %s\n", cft_last_error());
            return 2;
        }
    }
    memset(lanes_bad, 0, sizeof lanes_bad);
    memset(words_bad, 0, sizeof words_bad);
    printf("hip-progdiff %s --format %s --op %s --stream %s: %lld cases from lane %lld, seed "
           "%llu, chunks of %zu, the software handle on the first %lld; libcft %s; route probe "
           "%s\n", art, fmt == 2 ? "fp128" : "fp256", PD_OPN[op],
           stream == FXS_EDGE ? "edge" : "study", total, base0, (unsigned long long)seed, chunk,
           swk, cft_build_id(), probe ? "present (a plant build)" : "absent (a default build)");
    fflush(stdout);
    for (long long s0 = base0; s0 < base0 + total; s0 += (long long)chunk) {
        const size_t mlen = (size_t)(base0 + total - s0 < (long long)chunk ? base0 + total - s0
                                                                            : (long long)chunk);
        const double tg0 = now_ms();
        size_t gstart[6], cntr[5] = {0, 0, 0, 0, 0}, li;
        cft_sha256_ctx hs[3];
        if (s0 == base0)
            for (h = 0; h < 3; h++)
                cft_sha256_init(&hs[h]);
        for (li = 0; li < mlen; li++) {
            if (fmt == 2) {
                fxs128_gen_case(&cft_sf_formats[2], stream, seed, s0 + (long long)li, a + li * esz,
                                b + li * esz, c + li * esz, rr + li);
                fxs128_prep_case(&cft_sf_formats[2], op, a + li * esz, b + li * esz, c + li * esz);
            } else {
                fxs_gen_case(&cft_sf_formats[3], stream, seed, s0 + (long long)li, a + li * esz,
                             b + li * esz, c + li * esz, rr + li);
                fxs_prep_case(&cft_sf_formats[3], op, a + li * esz, b + li * esz, c + li * esz);
            }
            cntr[rr[li]]++;
        }
        /* the lanes grouped by their attribute, in lane order within a group */
        gstart[0] = 0;
        for (r = 0; r < 5; r++)
            gstart[r + 1] = gstart[r] + cntr[r];
        {
            size_t fill[5];
            for (r = 0; r < 5; r++)
                fill[r] = gstart[r];
            for (li = 0; li < mlen; li++) {
                const size_t g = fill[rr[li]]++;
                memcpy(ga + g * esz, a + li * esz, esz);
                memcpy(gb + g * esz, b + li * esz, esz);
                memcpy(gc + g * esz, c + li * esz, esz);
            }
        }
        t_gen += now_ms() - tg0;
        if (s0 == base0) {
            cft_sha256_update(&hs[0], a, mlen * esz);
            cft_sha256_update(&hs[0], b, mlen * esz);
            cft_sha256_update(&hs[0], c, mlen * esz);
            cft_sha256_update(&hs[0], rr, mlen);
        }
        for (p = 0; p < PD_NPROG; p++)
            for (m = 0; m < 2; m++)
                for (r = 0; r < 5; r++) {
                    const size_t n = cntr[r], off = gstart[r], db = mdp[p] * esz;
                    cft_run_args R;
                    cft_status st[2];
                    long fb = -1;
                    if (!n)
                        continue;
                    for (h = 0; h < 2; h++) {
                        pd_out *o = h ? &of : &og;
                        const double t0 = now_ms();
                        memset(&R, 0, sizeof R);
                        R.struct_size = sizeof R;
                        if (m) {
                            memcpy(cft_buffer_data(B[h][0]), ga + off * esz, n * esz);
                            memcpy(cft_buffer_data(B[h][1]), gb + off * esz, n * esz);
                            memcpy(cft_buffer_data(B[h][2]), gc + off * esz, n * esz);
                            if (cft_buffer_to_device(B[h][0]) != CFT_OK ||
                                cft_buffer_to_device(B[h][1]) != CFT_OK ||
                                cft_buffer_to_device(B[h][2]) != CFT_OK) {
                                fprintf(stderr, "hip-progdiff: publishing: %s\n", cft_last_error());
                                return 2;
                            }
                            R.a = cft_buffer_data(B[h][0]);
                            R.b = cft_buffer_data(B[h][1]);
                            R.c = cft_buffer_data(B[h][2]);
                            R.deposits = cft_buffer_data(B[h][3]);
                        } else {
                            R.a = ga + off * esz;
                            R.b = gb + off * esz;
                            R.c = gc + off * esz;
                            R.deposits = o->dep;
                        }
                        R.n = n;
                        R.counts = o->cnt;
                        R.lane_flags = o->lf;
                        R.lane_flags_bytes = n;
                        R.flags_out = &o->flags;
                        R.bus_out = &o->bus;
                        memset(o->lf, 0xEE, n);
                        memset(o->cnt, 0x77, n * 4);
                        st[h] = cft_program_run_ex(h ? pf[p][r] : pg[p][r], &R);
                        if (st[h] == CFT_OK && m) {
                            if (cft_buffer_from_device(B[h][3]) != CFT_OK)
                                st[h] = CFT_ERR_INTERNAL;
                            else
                                memcpy(o->dep, cft_buffer_data(B[h][3]), n * db);
                        }
                        if (h)
                            t_f += now_ms() - t0;
                        else
                            t_g += now_ms() - t0;
                        if (st[h] != CFT_OK) {
                            printf("  %s %s %s attribute %d n=%zu: the %s handle says %s - %s\n",
                                   PD_PROGN[p], m ? "resident" : "staged", PD_OPN[op], r, n,
                                   h ? "fixed" : "generic", cft_strerror(st[h]), cft_last_error());
                            lanes_bad[p][m] += (long)n;
                            break;
                        }
                        if (probe) {           /* the route of this run */
                            uint64_t v[15];
                            const uint64_t want = h ? (fmt == 2 ? 3u : 2u) : 0u;
                            memset(v, 0, sizeof v);
                            route_read++;
                            if (probe(v, 15) != 15 || v[8] != want || v[9] != (uint64_t)fmt ||
                                v[10] != (uint64_t)n || v[11] != 0) {
                                if (route_bad++ < 3)
                                    printf("  ROUTE %s %s attribute %d on the %s handle: the "
                                           "probe says kernel %llu (format %llu, n %llu, aug "
                                           "%llu), %llu wanted\n", PD_PROGN[p],
                                           m ? "resident" : "staged", r, h ? "fixed" : "generic",
                                           (unsigned long long)v[8], (unsigned long long)v[9],
                                           (unsigned long long)v[10], (unsigned long long)v[11],
                                           (unsigned long long)want);
                            }
                        }
                    }
                    if (st[0] != CFT_OK || st[1] != CFT_OK)
                        continue;
                    {
                        const long lb = pd_lanes_differ(&og, &of, n, db, &fb);
                        lanes_bad[p][m] += lb;
                        words_bad[p][m] += (og.flags != of.flags) + (og.bus != of.bus);
                        if (lb && first_bad < 0) {
                            /* the case's lane in the stream: the fb-th of attribute r */
                            size_t q = 0, seen = 0;
                            for (li = 0; li < mlen; li++)
                                if (rr[li] == (unsigned char)r && seen++ == (size_t)fb) {
                                    q = li;
                                    break;
                                }
                            first_bad = (long)(s0 + (long long)q);
                            {
                                char x1[65], x2[65], x3[65], y1[65], y2[65];
                                hexle(a + q * esz, x1, esz);
                                hexle(b + q * esz, x2, esz);
                                hexle(c + q * esz, x3, esz);
                                hexle(og.dep + (size_t)fb * db, y1, esz);
                                hexle(of.dep + (size_t)fb * db, y2, esz);
                                printf("  DIFF lane %ld (%s %s attribute %d): a %s b %s c %s\n"
                                       "     generic deposit 0 %s lane byte 0x%02x count %u\n"
                                       "       fixed deposit 0 %s lane byte 0x%02x count %u\n",
                                       first_bad, PD_PROGN[p], m ? "resident" : "staged", r, x1,
                                       x2, x3, y1, og.lf[fb], (unsigned)og.cnt[fb], y2,
                                       of.lf[fb], (unsigned)of.cnt[fb]);
                            }
                        }
                    }
                    if (s0 == base0 && !m) {    /* the first chunk's outputs, staged */
                        cft_sha256_update(&hs[1], og.dep, n * db);
                        cft_sha256_update(&hs[1], og.lf, n);
                        cft_sha256_update(&hs[1], (const unsigned char *)og.cnt, n * 4);
                        cft_sha256_update(&hs[2], of.dep, n * db);
                        cft_sha256_update(&hs[2], of.lf, n);
                        cft_sha256_update(&hs[2], (const unsigned char *)of.cnt, n * 4);
                    }
                    if (s0 == base0 && !m && swk) {
                        /* the software handle on this group's lanes among the first K */
                        size_t k = 0;
                        for (li = 0; li < mlen && (long long)li < swk; li++)
                            k += rr[li] == (unsigned char)r;
                        if (k) {
                            cft_status ss;
                            memset(&R, 0, sizeof R);
                            R.struct_size = sizeof R;
                            R.a = ga + off * esz;
                            R.b = gb + off * esz;
                            R.c = gc + off * esz;
                            R.n = k;
                            R.deposits = os.dep;
                            R.counts = os.cnt;
                            R.lane_flags = os.lf;
                            R.lane_flags_bytes = k;
                            R.flags_out = &os.flags;
                            R.bus_out = &os.bus;
                            ss = cft_program_run_ex(ps[p][r], &R);
                            if (ss != CFT_OK) {
                                printf("  the software handle says %s - %s\n", cft_strerror(ss),
                                       cft_last_error());
                                sw_bad[p] += (long)k;
                            } else {
                                /* lanes alone: the generic run's flags word covers all n */
                                sw_bad[p] += pd_lanes_differ(&og, &os, k, db, NULL);
                            }
                            sw_lanes += (long)k;
                            /* and the one-instruction program's lanes against the
                             * stream's own fixed lane on the host (fxs_fixed_lane, the
                             * functions k_run256 and k_run128 call): its deposit and
                             * its five flags in the lane byte */
                            for (li = 0; p == 0 && li < k; li++) {
                                const size_t q = off + li;
                                unsigned char hd[32], hfl = 0;
                                if (fmt == 2)
                                    fxs128_fixed_lane(op, ga + q * esz, gb + q * esz, gc + q * esz, r,
                                                      hd, &hfl, 0u);
                                else
                                    fxs_fixed_lane(op, ga + q * esz, gb + q * esz, gc + q * esz, r,
                                                   hd, &hfl, 0u);
                                lane_n++;
                                lane_bad += memcmp(hd, of.dep + li * db, esz) != 0 ||
                                            (unsigned)(hfl & 0x1Fu) != (unsigned)of.lf[li];
                            }
                        }
                    }
                }
        if (s0 == base0) {
            uint8_t dg[32];
            for (h = 0; h < 3; h++) {
                cft_sha256_final(&hs[h], dg);
                cft_sha256_hex(dg, hx[h]);
            }
        }
    }
    {
        long all = 0;
        for (p = 0; p < PD_NPROG; p++)
            for (m = 0; m < 2; m++) {
                printf("  %-5s %-8s: generic and fixed differ on %ld lanes and %ld run words "
                       "(flags or STATUS)%s\n", PD_PROGN[p], m ? "resident" : "staged",
                       lanes_bad[p][m], words_bad[p][m],
                       !m ? "" : "");
                all += lanes_bad[p][m] + words_bad[p][m];
            }
        for (p = 0; p < PD_NPROG; p++)
            printf("  %-5s sw prefix: the generic handle's lanes against the software handle's "
                   "on %ld of the first %lld lanes' runs: %ld differ\n", PD_PROGN[p],
                   sw_lanes / PD_NPROG, swk, sw_bad[p]);
        printf("  one   the fixed handle's lanes against the stream's fixed lane on the host "
               "(deposit and five flags): %ld lanes, %ld differ\n", lane_n, lane_bad);
        all += sw_bad[0] + sw_bad[1] + route_bad + lane_bad;
        printf("progdiff --format %s --op %s --stream %s: %lld cases from lane %lld, seed %llu, "
               "on %s (the device: CFT_HIP_INFO's line): generic and fixed differ on %ld lanes "
               "(one, chain; staged, resident) and %ld run words; the software handle %ld; "
               "first chunk (%zu cases) sha256 inputs %s, generic %s, fixed %s; ms: generator "
               "%.1f, generic %.1f, fixed %.1f; wall %.1f s; route %s%ld runs read, %ld not the "
               "kernel wanted; plants %s: %s\n",
               fmt == 2 ? "fp128" : "fp256", PD_OPN[op], stream == FXS_EDGE ? "edge" : "study",
               total, base0, (unsigned long long)seed, art,
               lanes_bad[0][0] + lanes_bad[0][1] + lanes_bad[1][0] + lanes_bad[1][1],
               words_bad[0][0] + words_bad[0][1] + words_bad[1][0] + words_bad[1][1],
               sw_bad[0] + sw_bad[1], chunk, hx[0], hx[1], hx[2], t_gen, t_g, t_f,
               (now_ms() - w0) / 1e3, probe ? "" : "(a default build: not read) ", route_read,
               route_bad, pv && *pv ? pv : "none set", all ? "RED" : "GREEN");
        for (p = 0; p < PD_NPROG; p++)
            for (r = 0; r < 5; r++) {
                cft_program_free(pg[p][r]);
                cft_program_free(pf[p][r]);
                cft_program_free(ps[p][r]);
            }
        for (h = 0; h < 2; h++)
            for (i = 0; i < 4; i++)
                cft_buffer_free(B[h][i]);
        cft_close(hg);
        cft_close(hf);
        cft_close(sw);
        return all ? 1 : 0;
    }
}
