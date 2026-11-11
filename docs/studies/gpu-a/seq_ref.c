/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A part 2: the reference. libcft's own sequencer - cft_program_load
 * (which validates) and cft_program_run_ex on a plain software handle,
 * host/src as it is in libcft.a, its blocks of 64 lanes - over the program
 * corpus gen_programs.py writes, in the output layout cft_seq.hip writes:
 * per case the program's info (7 words, from cft_program_get_info), the
 * run's status, FLAGS and STATUS, then the deposits, the counts, the lane
 * bytes when asked and the scratch-out when declared, every buffer filled
 * first with the case's own pattern so that what a run must not write is
 * told from what it wrote. One thread.
 *
 *   seq_ref run CORPUS OUT
 *   seq_ref bench CORPUS K LANES REPS     one core: case K's lanes repeated
 */
#define _POSIX_C_SOURCE 199309L   /* clock_gettime */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "cft.h"
#include "sha256.h"

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

static uint8_t *slurp(const char *path, size_t *len)
{
    FILE *fp = fopen(path, "rb");
    uint8_t *buf;
    long n;
    if (!fp || fseek(fp, 0, SEEK_END) || (n = ftell(fp)) < 0 || fseek(fp, 0, SEEK_SET)) {
        fprintf(stderr, "cannot read %s\n", path); exit(2);
    }
    buf = (uint8_t *)malloc((size_t)n + 1);
    if (!buf || fread(buf, 1, (size_t)n, fp) != (size_t)n) { fprintf(stderr, "short %s\n", path); exit(2); }
    fclose(fp);
    *len = (size_t)n;
    return buf;
}

typedef struct {
    char name[256];
    uint32_t fmt, n, image_bytes, bank_bytes, present, fill, fill_count, nsi, nso;
    const uint8_t *image, *bank, *a, *b, *c, *mask, *sin;
    size_t esz;
} scase;

static const uint8_t *next_case(const uint8_t *p, const uint8_t *end, scase *k)
{
    static const int widths[4] = {32, 64, 128, 256};
    uint32_t nl;
    if (end - p < 48 || memcmp(p, "CFTSEQA1", 8)) { fprintf(stderr, "not a corpus\n"); exit(2); }
    k->fmt = rd32(p + 8); k->n = rd32(p + 12); k->image_bytes = rd32(p + 16);
    k->bank_bytes = rd32(p + 20); k->present = rd32(p + 24); k->fill = rd32(p + 28);
    k->fill_count = rd32(p + 32); k->nsi = rd32(p + 36); k->nso = rd32(p + 40);
    nl = rd32(p + 44);
    if (k->fmt > 3 || nl >= sizeof k->name) { fprintf(stderr, "bad case header\n"); exit(2); }
    k->esz = (size_t)widths[k->fmt] / 8;
    p += 48;
    memcpy(k->name, p, nl); k->name[nl] = 0; p += nl;
    k->image = p; p += k->image_bytes;
    k->bank = p; p += k->bank_bytes;
    k->a = p; p += (size_t)k->n * k->esz;
    k->b = (k->present & 1) ? p : NULL; if (k->b) p += (size_t)k->n * k->esz;
    k->c = (k->present & 2) ? p : NULL; if (k->c) p += (size_t)k->n * k->esz;
    k->mask = (k->present & 4) ? p : NULL; if (k->mask) p += (k->n + 7) / 8;
    k->sin = (k->present & 16) ? p : NULL; if (k->sin) p += (size_t)k->n * k->nsi * k->esz;
    if (p > end) { fprintf(stderr, "truncated case\n"); exit(2); }
    return p;
}

/* Runs case k on n lanes (lane j is the case's lane j % k->n), into the
 * caller's buffers, filled here first; returns cft_program_run_ex's status. */
typedef struct {
    uint8_t *a, *b, *c, *mask, *sin, *dep, *lf, *so;
    uint32_t *counts, flags, status;
} bufs;

static void fill_bufs(const scase *k, const cft_program_info *I, size_t n, bufs *B)
{
    const size_t esz = k->esz;
    size_t j;
    B->a = (uint8_t *)malloc(n * esz + 1);
    B->b = k->b ? (uint8_t *)malloc(n * esz) : NULL;
    B->c = k->c ? (uint8_t *)malloc(n * esz) : NULL;
    B->mask = k->mask ? (uint8_t *)calloc((n + 7) / 8, 1) : NULL;
    B->sin = k->sin ? (uint8_t *)malloc(n * k->nsi * esz + 1) : NULL;
    for (j = 0; j < n; j++) {
        const size_t s = j % k->n;
        memcpy(B->a + j * esz, k->a + s * esz, esz);
        if (B->b) memcpy(B->b + j * esz, k->b + s * esz, esz);
        if (B->c) memcpy(B->c + j * esz, k->c + s * esz, esz);
        if (B->mask && (k->mask[s >> 3] & (1u << (s & 7))))
            B->mask[j >> 3] |= (uint8_t)(1u << (j & 7));
        if (B->sin) memcpy(B->sin + j * k->nsi * esz, k->sin + s * k->nsi * esz, k->nsi * esz);
    }
    B->dep = (uint8_t *)malloc(n * I->max_deposits * esz + 1);
    B->counts = (uint32_t *)malloc(n * 4 + 4);
    B->lf = (k->present & 8) ? (uint8_t *)malloc(n) : NULL;
    B->so = k->nso ? (uint8_t *)malloc(n * k->nso * esz) : NULL;
}

static void refill(const scase *k, const cft_program_info *I, size_t n, bufs *B)
{
    size_t j;
    memset(B->dep, (int)(k->fill & 0xFF), n * I->max_deposits * k->esz);
    for (j = 0; j < n; j++)
        B->counts[j] = k->fill_count;
    if (B->lf) memset(B->lf, (int)((k->fill >> 8) & 0xFF), n);
    if (B->so) memset(B->so, (int)(k->fill & 0xFF), n * k->nso * k->esz);
    B->flags = B->status = 0;
}

static cft_status run_once(cft_program *prog, const scase *k, const cft_program_info *I,
                           size_t n, bufs *B)
{
    cft_run_args A;
    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = B->a; A.b = B->b; A.c = B->c; A.n = n;
    A.bank = k->bank_bytes ? k->bank : NULL; A.bank_bytes = k->bank_bytes;
    A.scratch_in = B->sin; A.scratch_in_bytes = B->sin ? n * k->nsi * k->esz : 0;
    A.scratch_out = B->so; A.scratch_out_bytes = B->so ? n * k->nso * k->esz : 0;
    A.deposits = I->max_deposits ? B->dep : NULL; A.counts = B->counts;
    A.flags_out = &B->flags; A.bus_out = &B->status;
    A.lane_mask = B->mask; A.lane_mask_bytes = B->mask ? (n + 7) / 8 : 0;
    A.lane_flags = B->lf; A.lane_flags_bytes = B->lf ? n : 0;
    return cft_program_run_ex(prog, &A);
}

static void free_bufs(bufs *B)
{
    free(B->a); free(B->b); free(B->c); free(B->mask); free(B->sin);
    free(B->dep); free(B->counts); free(B->lf); free(B->so);
}

static void w32(FILE *fp, uint32_t v) { fwrite(&v, 4, 1, fp); }

static int load(cft_device *dev, const scase *k, cft_program **prog, cft_program_info *I)
{
    if (cft_program_load(dev, k->image, k->image_bytes, prog) != CFT_OK) {
        printf("refused by libcft: %s: %s\n", k->name, cft_last_error());
        return 1;
    }
    memset(I, 0, sizeof *I);
    I->struct_size = sizeof *I;
    cft_program_get_info(*prog, I);
    return 0;
}

int main(int argc, char **argv)
{
    cft_device *dev = NULL;
    size_t len;
    const uint8_t *raw, *p, *end;
    if (argc < 2 || cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "usage: seq_ref run CORPUS OUT | bench CORPUS K LANES REPS\n");
        return 2;
    }
    if (!strcmp(argv[1], "run") && argc == 4) {
        FILE *fp = fopen(argv[3], "wb");
        long ncase = 0, nlanes = 0, refused = 0, nov = 0, nrange = 0, nmark = 0;
        clock_t t0 = clock();
        raw = slurp(argv[2], &len);
        end = raw + len;
        if (!fp) { fprintf(stderr, "cannot write %s\n", argv[3]); return 2; }
        for (p = raw; p < end; ncase++) {
            scase k;
            cft_program *prog;
            cft_program_info I;
            bufs B;
            cft_status st;
            p = next_case(p, end, &k);
            if (load(dev, &k, &prog, &I)) { refused++; continue; }
            fill_bufs(&k, &I, k.n, &B);
            refill(&k, &I, k.n, &B);
            st = run_once(prog, &k, &I, k.n, &B);
            w32(fp, I.n_insns); w32(fp, I.n_consts); w32(fp, I.max_deposits); w32(fp, I.flags);
            w32(fp, I.n_scratch_in); w32(fp, I.n_scratch_out); w32(fp, I.scratch_used);
            w32(fp, (uint32_t)st); w32(fp, B.flags); w32(fp, B.status);
            fwrite(B.dep, 1, (size_t)k.n * I.max_deposits * k.esz, fp);
            fwrite(B.counts, 4, k.n, fp);
            if (B.lf) fwrite(B.lf, 1, k.n, fp);
            if (B.so) fwrite(B.so, 1, (size_t)k.n * k.nso * k.esz, fp);
            nlanes += k.n;
            nov += !!(B.status & CFT_STATUS_DEPOSIT_OVERFLOW);
            nrange += !!(B.status & CFT_STATUS_SCRATCH_RANGE);
            nmark += !!(B.status & CFT_STATUS_MARKED);
            free_bufs(&B);
            cft_program_free(prog);
        }
        fclose(fp);
        printf("seq_ref: %s: %ld cases, %ld lanes, %ld refused by libcft, %.1f s (one core); "
               "runs reporting a deposit overflow %ld, a strict scratch range %ld, a mark %ld\n",
               argv[2], ncase, nlanes, refused, (double)(clock() - t0) / CLOCKS_PER_SEC, nov,
               nrange, nmark);
        cft_close(dev);
        return refused ? 1 : 0;
    }
    if (!strcmp(argv[1], "bench") && argc == 6) {
        const long want = atol(argv[3]);
        const size_t n = (size_t)atol(argv[4]);
        const int reps = atoi(argv[5]);
        long i;
        int r;
        double best = 1e30, tot = 0;
        scase k;
        cft_program *prog;
        cft_program_info I;
        bufs B;
        raw = slurp(argv[2], &len);
        end = raw + len;
        for (p = raw, i = 0; i <= want; i++) {
            if (p >= end) { fprintf(stderr, "no case %ld\n", want); return 2; }
            p = next_case(p, end, &k);
        }
        if (load(dev, &k, &prog, &I) || n < 1 || reps < 1)
            return 1;
        fill_bufs(&k, &I, n, &B);
        for (r = 0; r < reps; r++) {
            struct timespec a, b;
            double s;
            refill(&k, &I, n, &B);
            clock_gettime(CLOCK_MONOTONIC, &a);
            if (run_once(prog, &k, &I, n, &B) != CFT_OK) { printf("run failed\n"); return 1; }
            clock_gettime(CLOCK_MONOTONIC, &b);
            s = (b.tv_sec - a.tv_sec) + 1e-9 * (b.tv_nsec - a.tv_nsec);
            tot += s;
            if (s < best) best = s;
        }
        printf("seq_ref bench: %s case %ld (%s, %u instructions), one core: %zu lanes, best "
               "%.4f s, mean %.4f s (%d reps): %.4g lane-programs/s, %.4g lane-instructions/s "
               "(best); %.1f ns a lane-instruction\n", argv[2], want, k.name, I.n_insns, n,
               best, tot / reps, reps, n / best, (double)n * I.n_insns / best,
               best * 1e9 / ((double)n * I.n_insns));
        free_bufs(&B);
        cft_program_free(prog);
        cft_close(dev);
        return 0;
    }
    fprintf(stderr, "usage: seq_ref run CORPUS OUT | bench CORPUS K LANES REPS\n");
    return 2;
}
