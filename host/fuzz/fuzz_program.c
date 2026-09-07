/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft_program_load over arbitrary bytes.
 *
 * The loader is the one part of libcft that parses an untrusted BLOB
 * rather than arguments: docs/REMOTE.md's PROG_LOAD hands it whatever
 * a socket carried, and docs/SEQUENCER.md's "What the loader refuses"
 * is the specification it is being held to. The oracle for that list
 * is python/cft_golden/seq.py, which is why this harness also has a
 * --verdict mode: it prints one line per input saying whether the C
 * loader took it, and host/fuzz/program_differential.py asks the model
 * the same question about the same bytes. An image one accepts and the
 * other refuses is a device executing something the host believed it
 * had rejected, which is the failure this whole arrangement exists to
 * make impossible.
 *
 * The program is LOADED, not run. A validated program may legally
 * describe 2^40 instructions (seq.py: MAX_INSTRUCTIONS), so "it did
 * not finish" is not evidence of anything here; execution divergence
 * is host/tests/seq_check.py's job.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"
#include "cft_fuzz.h"

#define SEQ_MAGIC   0x50544643u
#define SEQ_VERSION 1u
#define HDR         32u

static cft_device *g_dev;

static void init(void)
{
    if (cft_open(NULL, 0, &g_dev) != CFT_OK) {
        fprintf(stderr, "cft_open(software) failed\n");
        exit(2);
    }
}

static void run(const uint8_t *data, size_t len)
{
    cft_program *prog = NULL;
    if (cft_program_load(g_dev, data, len, &prog) == CFT_OK) {
        cft_program_info info;
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        cft_program_get_info(prog, &info);
        cft_program_free(prog);
    }
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* Put a mutated image back into a shape the header check will accept,
 * most of the time. Without this the fuzzer spends its whole budget
 * proving that a wrong magic is refused, and never reaches
 * seq_validate - which is where the rules live. One input in eight is
 * left alone so the refusals are exercised too. */
static size_t fixup(uint8_t *d, size_t len, size_t cap, uint64_t *st)
{
    uint32_t n_consts, n_insns, prec, esz, want;
    uint64_t r;
    *st += 0x9E3779B97F4A7C15ull;
    r = *st ^ (*st >> 29);

    if ((r & 7u) == 0)
        return len;                       /* leave the reject paths reachable */
    if (len < HDR) {
        if (cap < HDR)
            return len;
        memset(d + len, 0, HDR - len);
        len = HDR;
    }
    put32(d + 0, SEQ_MAGIC);
    put32(d + 4, SEQ_VERSION);
    put32(d + 24, 0);
    put32(d + 28, 0);
    prec = get32(d + 20) & 3u;
    put32(d + 20, prec);
    esz = 4u << prec;
    /* Deposits: mostly in range, sometimes not. */
    if ((r >> 3) & 1u)
        put32(d + 16, (uint32_t)((r >> 8) & 0xFFFFu));

    /* Choose a small constant bank and let the instructions fill the
     * rest, then trim the image to exactly what the header describes. */
    n_consts = (uint32_t)((r >> 24) & 3u);
    if (HDR + (uint64_t)n_consts * esz > len)
        n_consts = 0;
    n_insns = (uint32_t)((len - HDR - n_consts * esz) / 8u);
    put32(d + 8, n_insns);
    put32(d + 12, n_consts);
    want = HDR + n_consts * esz + n_insns * 8u;
    if (want > cap)
        return len;
    if (want > len)
        memset(d + len, 0, want - len);
    return want;
}

static const cft_fuzz_target target = {
    "program", init, run, fixup, 8192
};

/* --verdict FILE...: one line per file, ACCEPT or REFUSE with the
 * status name. host/fuzz/program_differential.py reads it. */
static int verdicts(int argc, char **argv, int first)
{
    int i;
    init();
    for (i = first; i < argc; i++) {
        uint8_t buf[1 << 20];
        size_t n;
        cft_program *prog = NULL;
        cft_status st;
        FILE *f = fopen(argv[i], "rb");
        if (!f) {
            printf("%s ERROR could-not-read\n", argv[i]);
            continue;
        }
        n = fread(buf, 1, sizeof buf, f);
        fclose(f);
        st = cft_program_load(g_dev, buf, n, &prog);
        if (st == CFT_OK) {
            cft_program_free(prog);
            printf("%s ACCEPT\n", argv[i]);
        } else {
            printf("%s REFUSE %s\n", argv[i], cft_strerror(st));
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++)
        if (!strcmp(argv[i], "--verdict"))
            return verdicts(argc, argv, i + 1);
    return cft_fuzz_main(argc, argv, &target);
}
