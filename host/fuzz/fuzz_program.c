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

/* An instruction word's fields the loader requires to be zero, cleared.
 *
 * The immediate is thirty-two bits and almost nothing reads all of it,
 * so a mutated word is refused for a stray field long before it
 * reaches a rule worth finding. This puts one back into canonical
 * shape - keeping whatever the mutation put in the fields that ARE
 * read, including revision 2's four register high bits in imm[27:24],
 * which is how those reach the validator and the executor at all.
 *
 * Applied to some inputs and not others, for the same reason the
 * header fixup is: the refusals have to stay reachable. */
static uint64_t canonical(uint64_t w)
{
    const uint32_t reghi = 0x0F000000u;
    /* imm[30:28], the ninth bits of the three constant indices since
     * revision 3. imm[31] alone is still reserved-must-be-zero. */
    const uint32_t kx9 = 0x70000000u;
    const uint32_t slot = 0x00FFFFFFu;       /* imm[23:0], a scratch slot */
    uint32_t imm = (uint32_t)(w >> 32);
    int ctrl = (int)((w >> 31) & 1);
    int kx   = (int)((w >> 30) & 1);

    if (!ctrl) {
        int anyk = (int)((w >> 27) & 7);
        if (kx && !anyk)
            w &= ~(1ull << 30);             /* kx selects nothing */
        imm &= kx ? (slot | reghi | kx9) : reghi;
        /* An operand naming a constant does not read its register high
         * bit, and under kx does not read its four-bit field either. */
        if ((w >> 27) & 1) { imm &= ~(1u << 25); if (kx) w &= ~(0xFull << 12); }
        if ((w >> 28) & 1) { imm &= ~(1u << 26); if (kx) w &= ~(0xFull << 16); }
        if ((w >> 29) & 1) { imm &= ~(1u << 27); if (kx) w &= ~(0xFull << 20); }
        /* and one naming a register reads neither its imm byte nor its
         * ninth index bit */
        if (kx) {
            if (!((w >> 27) & 1)) imm &= ~(0x000000FFu | (1u << 28));
            if (!((w >> 28) & 1)) imm &= ~(0x0000FF00u | (1u << 29));
            if (!((w >> 29) & 1)) imm &= ~(0x00FF0000u | (1u << 30));
        }
        if (((w >> 24) & 7) > 4)
            w &= ~(7ull << 24);             /* rounding attribute */
        return (w & 0xFFFFFFFFull) | ((uint64_t)imm << 32);
    }
    switch ((int)(w & 0xFF)) {
    case 1:                                  /* REPEAT: imm is the count */
        w &= ~0x7FFFF000ull;                 /* rd..rc, rnd, ka..kx */
        w &= ~(0xFull << 8);
        return w;
    case 3: case 4:                          /* DEPOSIT, SETACT: ra only */
        w &= ~0x7FF00000ull;                 /* rb, rc, rnd, ka..kx */
        w &= ~(0xFull << 8);                 /* rd */
        return (w & 0xFFFFFFFFull) |
               ((uint64_t)(imm & (1u << 25)) << 32);
    /* Revision 3's four scratch codes. Each reads a different subset,
     * and this puts the rest back to zero so a mutated word reaches
     * the SLOT rule rather than being refused for a stray rnd. */
    case 6:                                  /* STL: ra, imm[23:0] */
        w &= ~0x7FF00000ull;                 /* rb, rc, rnd, ka..kx */
        w &= ~(0xFull << 8);                 /* rd */
        return (w & 0xFFFFFFFFull) |
               ((uint64_t)(imm & (slot | (1u << 25))) << 32);
    case 7:                                  /* LDL: rd, imm[23:0] */
        w &= ~0x7FFF0000ull;                 /* rb, rc, rnd, ka..kx */
        w &= ~(0xFull << 12);                /* ra */
        return (w & 0xFFFFFFFFull) |
               ((uint64_t)(imm & (slot | (1u << 24))) << 32);
    case 8:                                  /* STX: ra, rb */
        w &= ~0x7F000000ull;                 /* rnd, ka..kx */
        w &= ~(0xFull << 8);                 /* rd */
        w &= ~(0xFull << 20);                /* rc */
        return (w & 0xFFFFFFFFull) |
               ((uint64_t)(imm & ((1u << 25) | (1u << 26))) << 32);
    default:                                 /* LDX, and the rest */
        if ((w & 0xFF) == 9) {               /* LDX: rd, rb */
            w &= ~0x7F000000ull;             /* rnd, ka..kx */
            w &= ~(0xFull << 12);            /* ra */
            w &= ~(0xFull << 20);            /* rc */
            return (w & 0xFFFFFFFFull) |
                   ((uint64_t)(imm & ((1u << 24) | (1u << 26))) << 32);
        }
        return w & 0x800000FFull;            /* HALT, ENDREP, ACTALL, bad */
    }
}

/* Put a mutated image back into a shape the header check will accept,
 * most of the time. Without this the fuzzer spends its whole budget
 * proving that a wrong magic is refused, and never reaches
 * seq_validate - which is where the rules live. One input in eight is
 * left alone so the refusals are exercised too. */
static size_t fixup(uint8_t *d, size_t len, size_t cap, uint64_t *st)
{
    uint32_t n_consts, n_insns, prec, esz, want, flags, kbytes;
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
    prec = get32(d + 20) & 3u;
    put32(d + 20, prec);
    esz = 4u << prec;
    /* Deposits: mostly in range, sometimes not. */
    if ((r >> 3) & 1u)
        put32(d + 16, (uint32_t)((r >> 8) & 0xFFFFu));

    /* The header's flags word, which was reserved[0] until 2026-09-08.
     * Four cases in eight: no flags, BANK_EXT (an image with NO
     * constant section, whose n_consts still bounds every index),
     * SCRATCH_IO (revision 3's per-run scratch block), and once in
     * eight an unassigned bit, which must be CFT_ERR_ARTIFACT - the
     * version guard for every flag there will ever be. Bit 1 stopped
     * being unassigned when SCRATCH_IO took it, so the unassigned case
     * starts at 2. */
    switch ((int)((r >> 20) & 7u)) {
    case 0: flags = 1u << (2 + (unsigned)((r >> 44) & 29u)); break;
    case 1: case 2: flags = 1u; break;                  /* BANK_EXT */
    case 3: flags = 2u; break;                          /* SCRATCH_IO */
    case 4: flags = 3u; break;                          /* both */
    default: flags = 0u; break;
    }
    put32(d + 24, flags);
    /* And the word that was reserved[1]: scratch_io, n_scratch_in in
     * [15:0] and n_scratch_out in [31:16], which is meaningful only
     * under the flag and must be zero without it. Under the flag the
     * counts are mostly inside the executor's 256 slots and sometimes
     * past them, so the capacity refusal stays reachable too. */
    if (flags & 2u)
        put32(d + 28, (uint32_t)(((r >> 32) & 0x1FFu) |
                                 (((r >> 41) & 0x1FFu) << 16)));
    else
        put32(d + 28, 0);

    /* Choose a small constant bank and let the instructions fill the
     * rest, then trim the image to exactly what the header describes.
     * A BANK_EXT image has no constant section, so n_consts is free of
     * the image's length entirely - which is the point of it. */
    n_consts = (uint32_t)((r >> 24) & 3u);
    kbytes = (flags & 1u) ? 0u : n_consts * esz;
    if (HDR + (uint64_t)kbytes > len)
        n_consts = kbytes = 0;
    n_insns = (uint32_t)((len - HDR - kbytes) / 8u);
    put32(d + 8, n_insns);
    put32(d + 12, n_consts);
    want = HDR + kbytes + n_insns * 8u;
    if (want > cap)
        return len;
    if (want > len)
        memset(d + len, 0, want - len);
    /* Half the fixed-up inputs get their instruction words put into
     * canonical shape, so the deep rules - the loop structure, the
     * worst-case bound, the constant indices, the five-bit registers -
     * are reached rather than shadowed by a stray-field refusal. */
    if ((r >> 33) & 1u) {
        uint32_t i;
        for (i = 0; i < n_insns; i++) {
            uint8_t *p = d + HDR + kbytes + (size_t)i * 8u;
            uint64_t w = (uint64_t)get32(p) | ((uint64_t)get32(p + 4) << 32);
            w = canonical(w);
            put32(p, (uint32_t)w);
            put32(p + 4, (uint32_t)(w >> 32));
        }
    }
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
