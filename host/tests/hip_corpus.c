/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * hip-corpus - study GPU-A's corpora (docs/studies/gpu-a) through libcft's
 * public API, on any device:
 *
 *     hip-corpus ARTIFACT CORPUS OUT        ARTIFACT: sw, or hip:N
 *     hip-corpus ARTIFACT CORPUS OUT --sample K:SEED   (below, before main)
 *
 * It reads the two corpus layouts and runs them; it computes nothing
 * itself. What it writes is GPU-A's output layout, so the sha256 of OUT
 * is GPU-A's and G1A's sum for the same corpus whatever the device -
 * the software handle's, a GPU's.
 *
 * An ELEMENTWISE corpus (b"CFTGPUA1", gen_corpus.py: a, b, c, the
 * attribute of each case, then the expected d and flags) is run as
 * cft_run's contract allows it to be checked, which is twice, as
 * host/src/conformance.c replays a set:
 *   pass 1: one cft_run(CFT_FMA) a case, n = 1. A call's flags are the OR
 *           over its elements, so one case a call is the only way to have
 *           each case's own flags; this pass's d and flags are OUT.
 *   pass 2: the cases of each attribute in ONE call, five calls, so the
 *           device's batch path - its chunks - runs: each call's d held to
 *           pass 1's byte for byte, and its flags to the OR of pass 1's.
 * The corpus's own expected values are counted against too, as
 * gen_corpus.py verify does.
 *
 * A PROGRAM corpus (b"CFTSEQA1", gen_programs.py) is loaded case by case
 * with cft_program_load - a refusal is printed with its sentence, and
 * the case writes nothing - and run with cft_program_run_ex over buffers
 * filled first with the case's own patterns, writing per case the
 * program's seven info words, the run's status, flags and STATUS, then
 * its deposits, counts, lane bytes when asked and scratch-out when
 * declared: seq_ref.c's layout (docs/studies/gpu-a/seq_ref.c:1 to :40).
 *
 * Exit 0 when every case ran and both passes agreed; 1 when a case was
 * refused or a pass disagreed; 2 when it could not start.
 */

#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 199309L
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"

static double now_s(void)
{
#ifdef _WIN32
    return (double)clock() / CLOCKS_PER_SEC;
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
#endif
}

static const char *const RND[5] = {"rne", "rtz", "rdn", "rup", "rmm"};

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
           (uint32_t)p[3] << 24;
}

static uint8_t *slurp(const char *path, size_t *len)
{
    FILE *fp = fopen(path, "rb");
    uint8_t *buf;
    long n;
    if (!fp || fseek(fp, 0, SEEK_END) || (n = ftell(fp)) < 0 || fseek(fp, 0, SEEK_SET)) {
        fprintf(stderr, "hip-corpus: cannot read %s\n", path);
        exit(2);
    }
    buf = (uint8_t *)malloc((size_t)n + 1);
    if (!buf || fread(buf, 1, (size_t)n, fp) != (size_t)n) {
        fprintf(stderr, "hip-corpus: short read of %s\n", path);
        exit(2);
    }
    fclose(fp);
    *len = (size_t)n;
    return buf;
}

static void *xmalloc(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p) {
        fprintf(stderr, "hip-corpus: out of memory for %lu bytes\n", (unsigned long)n);
        exit(2);
    }
    return p;
}

/* ---- the elementwise corpus ------------------------------------------- */

/* --sample K:SEED (elementwise corpora): pass 1 on K cases, chosen by
 * selection sampling (Knuth's algorithm S) - case i is taken when the
 * next draw of xorshift64 (shifts 13, 7, 17, seeded with SEED), modulo
 * the n - i cases left, is below the number still to take, which takes
 * exactly K - and pass 2 whole. With no pass 1 over every case there is
 * no output to hash, so both passes are held to the corpus's own
 * expected values instead: each sampled case's d and flags exactly,
 * each pass-2 call's d byte for byte and its flags to the OR of its
 * cases' expected flags. OUT is left empty. For a device whose single
 * calls would hold it too long for a whole pass 1 (study GPU-A's stream
 * corpus, 1M cases). */
static unsigned long long sample_k, sample_seed;

static int run_elem(cft_device *dev, const uint8_t *raw, size_t len, FILE *out,
                    uint8_t digest[32])
{
    const uint32_t fmt = rd32(raw + 8), esz = rd32(raw + 12);
    const uint64_t n = (uint64_t)rd32(raw + 16) | (uint64_t)rd32(raw + 20) << 32;
    const uint8_t *a, *b, *c, *rnd, *want_d, *want_f, *ref_d, *ref_f;
    uint8_t *d, *fl, *ga, *gb, *gc, *gd, *sel = NULL;
    size_t i, bad_d = 0, bad_f = 0, p2_bad = 0, taken = 0;
    double t0, t1, t2;
    int k, rc = 0;

    if (fmt > 3 || esz != cft_format_size((cft_format)fmt) ||
        len != 24 + n * (4 * (uint64_t)esz + 2)) {
        fprintf(stderr, "hip-corpus: not a well-formed CFTGPUA1 corpus\n");
        return 2;
    }
    a = raw + 24;
    b = a + n * esz;
    c = b + n * esz;
    rnd = c + n * esz;
    want_d = rnd + n;
    want_f = want_d + n * esz;
    d = (uint8_t *)xmalloc(n * esz + n);
    fl = d + n * esz;
    ref_d = d;                  /* pass 2 is held to pass 1, or in a */
    ref_f = fl;                 /* sample to the corpus's expected */
    if (sample_k) {
        unsigned long long x = sample_seed;
        if (sample_k > n) {
            fprintf(stderr, "hip-corpus: --sample %llu of %lu cases\n", sample_k,
                    (unsigned long)n);
            free(d);
            return 2;
        }
        sel = (uint8_t *)xmalloc(n);
        for (i = 0; i < n; i++) {
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            sel[i] = x % (n - i) < sample_k - taken;
            taken += sel[i];
        }
        ref_d = want_d;
        ref_f = want_f;
    }

    /* pass 1: a case a call */
    t0 = now_s();
    for (i = 0; i < n; i++) {
        uint32_t f = 0;
        cft_status st;
        if (sel && !sel[i])
            continue;
        st = cft_run(dev, CFT_FMA, (cft_format)fmt, (cft_round)rnd[i], a + i * esz,
                     b + i * esz, c + i * esz, d + i * esz, 1, &f, NULL);
        if (st != CFT_OK) {
            printf("pass 1: case %lu: %s - %s\n", (unsigned long)i, cft_strerror(st),
                   cft_last_error());
            free(d);
            free(sel);
            return 1;
        }
        fl[i] = (uint8_t)f;
        bad_d += memcmp(d + i * esz, want_d + i * esz, esz) != 0;
        bad_f += fl[i] != want_f[i];
    }
    t1 = now_s();

    /* pass 2: one call an attribute */
    ga = (uint8_t *)xmalloc(n * esz);
    gb = (uint8_t *)xmalloc(n * esz);
    gc = (uint8_t *)xmalloc(n * esz);
    gd = (uint8_t *)xmalloc(n * esz);
    for (k = 0; k < 5; k++) {
        size_t m = 0;
        uint32_t want_or = 0, got = 0;
        cft_status st;
        for (i = 0; i < n; i++) {
            if (rnd[i] != k)
                continue;
            memcpy(ga + m * esz, a + i * esz, esz);
            memcpy(gb + m * esz, b + i * esz, esz);
            memcpy(gc + m * esz, c + i * esz, esz);
            want_or |= ref_f[i];
            m++;
        }
        if (!m)
            continue;
        st = cft_run(dev, CFT_FMA, (cft_format)fmt, (cft_round)k, ga, gb, gc, gd, m,
                     &got, NULL);
        if (st != CFT_OK) {
            printf("pass 2: attribute %s, %lu cases: %s - %s\n",
                   RND[k], (unsigned long)m, cft_strerror(st),
                   cft_last_error());
            rc = 1;
            continue;
        }
        m = 0;
        for (i = 0; i < n; i++) {
            if (rnd[i] != k)
                continue;
            if (memcmp(gd + m * esz, ref_d + i * esz, esz)) {
                if (p2_bad++ < 5)
                    printf("pass 2: attribute %s: case %lu of the corpus (element %lu "
                           "of the call) differs from %s d\n", RND[k], (unsigned long)i,
                           (unsigned long)m, sel ? "the corpus's expected" : "its own call's");
            }
            m++;
        }
        if (got != want_or) {
            p2_bad++;
            printf("pass 2: attribute %s, %lu cases: flags 0x%02x, the OR of %s 0x%02x\n",
                   RND[k], (unsigned long)m, (unsigned)got,
                   sel ? "the corpus's expected" : "pass 1's", (unsigned)want_or);
        }
    }
    t2 = now_s();
    if (sel) {
        printf("elementwise %s: %lu cases, SAMPLED (--sample %llu:%llu): pass 1 on %lu "
               "of them (a case a call) %.1f s, %lu results and %lu flags differing from "
               "the corpus's expected; pass 2 (five calls, every case) %.1f s, %s the "
               "corpus's expected d and each call's flags the OR of its cases' expected; "
               "no output, no hash\n", cft_format_name((cft_format)fmt), (unsigned long)n,
               sample_k, sample_seed, (unsigned long)taken, t1 - t0, (unsigned long)bad_d,
               (unsigned long)bad_f, t2 - t1, p2_bad || rc ? "DIFFERING FROM" : "equal to");
        rc = rc || p2_bad || bad_d || bad_f;
    } else {
        fwrite(d, 1, n * esz + n, out);
        cft_sha256(d, n * esz + n, digest);
        printf("elementwise %s: %lu cases; pass 1 (a case a call) %.1f s, pass 2 (five "
               "calls) %.1f s and %s; against the corpus's expected values %lu results "
               "and %lu flags differ\n", cft_format_name((cft_format)fmt), (unsigned long)n,
               t1 - t0, t2 - t1, p2_bad ? "DISAGREED with pass 1" : "agreed with pass 1",
               (unsigned long)bad_d, (unsigned long)bad_f);
        rc = rc || p2_bad;
    }
    free(ga);
    free(gb);
    free(gc);
    free(gd);
    free(d);
    free(sel);
    return rc ? 1 : 0;
}

/* ---- the program corpus ------------------------------------------------ */

typedef struct {
    char name[256];
    uint32_t fmt, n, image_bytes, bank_bytes, present, fill, fill_count, nsi, nso;
    const uint8_t *image, *bank, *a, *b, *c, *mask, *sin;
    size_t esz;
} scase;

static const uint8_t *next_case(const uint8_t *p, const uint8_t *end, scase *k)
{
    uint32_t nl;
    if (end - p < 48 || memcmp(p, "CFTSEQA1", 8)) {
        fprintf(stderr, "hip-corpus: not a CFTSEQA1 case\n");
        exit(2);
    }
    k->fmt = rd32(p + 8);
    k->n = rd32(p + 12);
    k->image_bytes = rd32(p + 16);
    k->bank_bytes = rd32(p + 20);
    k->present = rd32(p + 24);
    k->fill = rd32(p + 28);
    k->fill_count = rd32(p + 32);
    k->nsi = rd32(p + 36);
    k->nso = rd32(p + 40);
    nl = rd32(p + 44);
    if (k->fmt > 3 || nl >= sizeof k->name) {
        fprintf(stderr, "hip-corpus: a bad case header\n");
        exit(2);
    }
    k->esz = cft_format_size((cft_format)k->fmt);
    p += 48;
    memcpy(k->name, p, nl);
    k->name[nl] = 0;
    p += nl;
    k->image = p;
    p += k->image_bytes;
    k->bank = p;
    p += k->bank_bytes;
    k->a = p;
    p += (size_t)k->n * k->esz;
    k->b = (k->present & 1) ? p : NULL;
    if (k->b) p += (size_t)k->n * k->esz;
    k->c = (k->present & 2) ? p : NULL;
    if (k->c) p += (size_t)k->n * k->esz;
    k->mask = (k->present & 4) ? p : NULL;
    if (k->mask) p += (k->n + 7) / 8;
    k->sin = (k->present & 16) ? p : NULL;
    if (k->sin) p += (size_t)k->n * k->nsi * k->esz;
    if (p > end) {
        fprintf(stderr, "hip-corpus: a truncated case\n");
        exit(2);
    }
    return p;
}

/* The program corpus's output, gathered whole, then written and hashed
 * once (libcft's cft_sha256 is one-shot). */
typedef struct {
    uint8_t *p;
    size_t len, cap;
} obuf;

static void wbytes(obuf *o, const void *p, size_t n)
{
    if (o->len + n > o->cap) {
        size_t cap = o->cap ? o->cap : (size_t)1 << 16;
        while (cap < o->len + n)
            cap *= 2;
        o->p = (uint8_t *)realloc(o->p, cap);
        if (!o->p) {
            fprintf(stderr, "hip-corpus: out of memory for the output\n");
            exit(2);
        }
        o->cap = cap;
    }
    memcpy(o->p + o->len, p, n);
    o->len += n;
}

static void w32(obuf *o, uint32_t v)
{
    uint8_t b[4];
    b[0] = (uint8_t)v;
    b[1] = (uint8_t)(v >> 8);
    b[2] = (uint8_t)(v >> 16);
    b[3] = (uint8_t)(v >> 24);
    wbytes(o, b, 4);
}

static int run_progs(cft_device *dev, const uint8_t *raw, size_t len, FILE *out,
                     uint8_t digest[32])
{
    const uint8_t *p = raw, *end = raw + len;
    long ncase = 0, nlanes = 0, refused = 0;
    obuf o = {NULL, 0, 0};
    double t0 = now_s();

    while (p < end) {
        scase k;
        cft_program *prog = NULL;
        cft_program_info I;
        cft_run_args A;
        uint8_t *dep, *lf = NULL, *so = NULL;
        uint32_t *counts, flags = 0, status = 0;
        cft_status st;
        size_t j;

        p = next_case(p, end, &k);
        ncase++;
        if (cft_program_load(dev, k.image, k.image_bytes, &prog) != CFT_OK) {
            printf("refused by libcft: %s: %s\n", k.name, cft_last_error());
            refused++;
            continue;
        }
        memset(&I, 0, sizeof I);
        I.struct_size = sizeof I;
        cft_program_get_info(prog, &I);
        dep = (uint8_t *)xmalloc((size_t)k.n * I.max_deposits * k.esz);
        counts = (uint32_t *)xmalloc((size_t)k.n * 4);
        memset(dep, (int)(k.fill & 0xFF), (size_t)k.n * I.max_deposits * k.esz);
        for (j = 0; j < k.n; j++)
            counts[j] = k.fill_count;
        if (k.present & 8) {
            lf = (uint8_t *)xmalloc(k.n);
            memset(lf, (int)((k.fill >> 8) & 0xFF), k.n);
        }
        if (k.nso) {
            so = (uint8_t *)xmalloc((size_t)k.n * k.nso * k.esz);
            memset(so, (int)(k.fill & 0xFF), (size_t)k.n * k.nso * k.esz);
        }
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = k.a;
        A.b = k.b;
        A.c = k.c;
        A.n = k.n;
        A.bank = k.bank_bytes ? k.bank : NULL;
        A.bank_bytes = k.bank_bytes;
        A.scratch_in = k.sin;
        A.scratch_in_bytes = k.sin ? (size_t)k.n * k.nsi * k.esz : 0;
        A.scratch_out = so;
        A.scratch_out_bytes = so ? (size_t)k.n * k.nso * k.esz : 0;
        A.deposits = I.max_deposits ? dep : NULL;
        A.counts = counts;
        A.flags_out = &flags;
        A.bus_out = &status;
        A.lane_mask = k.mask;
        A.lane_mask_bytes = k.mask ? (k.n + 7) / 8 : 0;
        A.lane_flags = lf;
        A.lane_flags_bytes = lf ? k.n : 0;
        st = cft_program_run_ex(prog, &A);
        if (st != CFT_OK)
            printf("run failed: %s: %s - %s\n", k.name, cft_strerror(st), cft_last_error());
        w32(&o, I.n_insns);
        w32(&o, I.n_consts);
        w32(&o, I.max_deposits);
        w32(&o, I.flags);
        w32(&o, I.n_scratch_in);
        w32(&o, I.n_scratch_out);
        w32(&o, I.scratch_used);
        w32(&o, (uint32_t)st);
        w32(&o, flags);
        w32(&o, status);
        wbytes(&o, dep, (size_t)k.n * I.max_deposits * k.esz);
        for (j = 0; j < k.n; j++)
            w32(&o, counts[j]);
        if (lf)
            wbytes(&o, lf, k.n);
        if (so)
            wbytes(&o, so, (size_t)k.n * k.nso * k.esz);
        nlanes += k.n;
        free(dep);
        free(counts);
        free(lf);
        free(so);
        cft_program_free(prog);
    }
    fwrite(o.p ? o.p : (uint8_t *)"", 1, o.len, out);
    cft_sha256(o.p, o.len, digest);
    free(o.p);
    printf("programs: %ld cases, %ld lanes, %ld refused by libcft, %.1f s\n", ncase,
           nlanes, refused, now_s() - t0);
    return refused ? 1 : 0;
}

int main(int argc, char **argv)
{
    cft_device *dev = NULL;
    uint8_t *raw, digest[32];
    size_t len;
    FILE *out;
    cft_status st;
    int rc, i;

    if (argc == 6 && !strcmp(argv[4], "--sample")) {
        char *e = NULL;
        sample_k = strtoull(argv[5], &e, 10);
        if (e && *e == ':')
            sample_seed = strtoull(e + 1, &e, 10);
        if (!sample_k || !sample_seed || !e || *e) {
            fprintf(stderr, "hip-corpus: --sample K:SEED, two decimal numbers above "
                    "zero\n");
            return 2;
        }
    } else if (argc != 4) {
        fprintf(stderr, "usage: %s sw|hip:N CORPUS OUT [--sample K:SEED]\n", argv[0]);
        return 2;
    }
    printf("libcft build %s\n", cft_build_id());
    st = cft_open(strcmp(argv[1], "sw") ? argv[1] : NULL, 0, &dev);
    if (st != CFT_OK) {
        fprintf(stderr, "hip-corpus: cft_open(%s): %s - %s\n", argv[1],
                cft_strerror(st), cft_last_error());
        return 2;
    }
    raw = slurp(argv[2], &len);
    out = fopen(argv[3], "wb");
    if (!out) {
        fprintf(stderr, "hip-corpus: cannot write %s\n", argv[3]);
        return 2;
    }
    if (len >= 24 && !memcmp(raw, "CFTGPUA1", 8))
        rc = run_elem(dev, raw, len, out, digest);
    else if (len >= 48 && !memcmp(raw, "CFTSEQA1", 8) && !sample_k)
        rc = run_progs(dev, raw, len, out, digest);
    else {
        fprintf(stderr, "hip-corpus: %s is %s\n", argv[2], sample_k
                ? "not an elementwise corpus, which --sample is for"
                : "neither corpus layout");
        rc = 2;
    }
    fclose(out);
    if (rc != 2 && !sample_k) {
        printf("%s on %s: sha256 ", argv[2], argv[1]);
        for (i = 0; i < 32; i++)
            printf("%02x", digest[i]);
        printf("\n");
    }
    cft_close(dev);
    free(raw);
    return rc;
}
