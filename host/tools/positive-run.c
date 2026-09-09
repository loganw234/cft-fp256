/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * positive-run - run a program image over a stream and hash what it
 * deposited. docs/PROGRAMS.md's third piece, and docs/ATLAS.md's step
 * 3: the runner that lets a positive's plate be attested.
 *
 *   positive-run <image.cftp> (--iota n | --a A [--b B] [--c C])
 *                [--bank bank.bin] [--out deposits.bin]
 *                [--scratch-in in.bin] [--scratch-out out.bin]
 *                [--device sw|<xclbin>]
 *
 * It is the SAME BINARY on the software backend, in emulation and on
 * the card. That is the whole point: a plate's hash from one is
 * comparable with a plate's hash from another, and the comparison is
 * of two hex strings rather than of two runs of a program somebody
 * ported. The last line it prints is the SHA-256 of the deposit
 * buffer, and the line above it the digest of the program and its
 * bank together - what ran, and what came out.
 *
 * ---------------------------------------------------------------
 * The two run paths, and why one of them is behind an #ifdef
 * ---------------------------------------------------------------
 *
 * An image either carries its constants or does not. One that does
 * runs through `cft_program_run`, which every build of this library
 * has. One that does not - `flags.BANK_EXT`, docs/SEQUENCER.md
 * revision 2 - takes its constants from a bank buffer supplied per
 * run, and that needs `cft_program_run_bank`, which arrives with the
 * host half of the 2026-09-08 round.
 *
 * So the bank path is compiled under `CFT_SEQ_FEAT_BANK_PTR`, the
 * feature macro cft.h defines beside those entry points. Without it
 * this tool still builds, still runs every ordinary image, and SAYS
 * SO when handed one that needs the bank - rather than silently
 * running something else, and rather than failing to build, which
 * would take the library's other checks down with it.
 *
 * `cft_program_digest` rides the same macro and has a local fallback,
 * because a digest is the tool's product and must not depend on which
 * half of the tree it was built against: SHA-256 over the image bytes
 * followed by the bank bytes, which is what the library computes. The
 * two are the same bytes either way, and that is checkable the day
 * both exist.
 *
 * ---------------------------------------------------------------
 * The scratch, and a THIRD run path
 * ---------------------------------------------------------------
 *
 * docs/SEQUENCER.md revision 3 gives every lane a scratch memory
 * (R4), and lets the host preload its first slots and read them back
 * (R5, `flags.SCRATCH_IO` and the header's `scratch_io` word). Those
 * buffers are run data exactly as the bank is, so `--scratch-in` and
 * `--scratch-out` name files of raw format-width values, LANE-MAJOR
 * and dense - lane i's slot s is element `i * n_scratch_in + s`, and
 * the file is exactly `n * n_scratch_in` elements. The tool prints the
 * SHA-256 of each on its own line, because what went in is as much
 * part of what ran as the image is; the `digest` line is unchanged,
 * image then bank, which is what `cft_program_digest` returns.
 *
 * The run itself then goes through `cft_program_run_ex` and the
 * `cft_run_args` struct - ABI 0.10's one entry point that takes
 * everything a run can carry - compiled under `CFT_SEQ_FEAT_SCRATCH_IO`
 * the way the bank path is compiled under `CFT_SEQ_FEAT_BANK_PTR`.
 * Without the macro this tool still builds and still runs every image
 * that does not need the scratch, and refuses one that does BY NAME.
 */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "cft.h"

#define HEADER_BYTES    32
#define FLAG_BANK_EXT   0x1u
#define FLAG_SCRATCH_IO 0x2u
#define FLAGS_KNOWN     (FLAG_BANK_EXT | FLAG_SCRATCH_IO)
#define MAX_ESZ         32
/* The four control codes of docs/SEQUENCER.md's R4, read here so the
 * tool can name what an image needs before the loader is handed it. */
#define C_STL 6
#define C_LDL 7
#define C_STX 8
#define C_LDX 9

/* ---- failure ------------------------------------------------------- */

static void die(const char *fmt, ...)
{
    va_list ap;
    fputs("positive-run: ", stderr);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(1);
}

static void die_st(const char *what, cft_status st)
{
    const char *detail = cft_last_error();
    die("%s: %s%s%s", what, cft_strerror(st),
        (detail && *detail) ? " - " : "", (detail && *detail) ? detail : "");
}

static void *xcalloc(size_t n, size_t sz)
{
    void *p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        die("out of memory");
    return p;
}

/* ---- SHA-256 -------------------------------------------------------
 *
 * Derived constants, as in host/tools/cft-asm.c and the workload
 * tools: K[i] is the fractional part of the cube root of the i-th
 * prime, H0[i] of its square root. */
typedef struct {
    uint32_t h[8];
    uint64_t bits;
    uint8_t  buf[64];
    size_t   have;
} sha256;

static uint32_t SHA_K[64];
static uint32_t SHA_H0[8];
static int      sha_ready = 0;

typedef struct { uint64_t hi, lo; } u128;

static u128 u128_mk(uint64_t hi, uint64_t lo)
{
    u128 r;
    r.hi = hi;
    r.lo = lo;
    return r;
}

static int u128_cmp(u128 a, u128 b)
{
    if (a.hi != b.hi)
        return a.hi < b.hi ? -1 : 1;
    if (a.lo != b.lo)
        return a.lo < b.lo ? -1 : 1;
    return 0;
}

static u128 u128_shl(u128 a, int s)
{
    u128 r;
    if (s == 0)
        return a;
    if (s >= 64) {
        r.hi = a.lo << (s - 64);
        r.lo = 0;
    } else {
        r.hi = (a.hi << s) | (a.lo >> (64 - s));
        r.lo = a.lo << s;
    }
    return r;
}

static u128 u128_mul64(uint64_t a, uint64_t b)
{
    uint64_t al = a & 0xffffffffu, ah = a >> 32;
    uint64_t bl = b & 0xffffffffu, bh = b >> 32;
    uint64_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint64_t mid = (ll >> 32) + (lh & 0xffffffffu) + (hl & 0xffffffffu);
    u128 r;
    r.lo = (ll & 0xffffffffu) | (mid << 32);
    r.hi = hh + (lh >> 32) + (hl >> 32) + (mid >> 32);
    return r;
}

static int u128_mul_small(u128 a, uint64_t b, u128 *out)
{
    u128 lo = u128_mul64(a.lo, b);
    u128 hi = u128_mul64(a.hi, b);
    if (hi.hi != 0)
        return 1;
    lo.hi += hi.lo;
    if (lo.hi < hi.lo)
        return 1;
    *out = lo;
    return 0;
}

static int u128_pow(uint64_t v, int root, u128 *out)
{
    u128 acc = u128_mk(0, v);
    int k;
    for (k = 1; k < root; k++)
        if (u128_mul_small(acc, v, &acc))
            return 1;
    *out = acc;
    return 0;
}

static uint32_t root_frac32(uint32_t p, int root)
{
    u128 target = u128_shl(u128_mk(0, p), 32 * root);
    uint64_t lo = 0, hi = 1;
    for (;;) {
        u128 acc;
        if (u128_pow(hi, root, &acc) || u128_cmp(acc, target) > 0)
            break;
        hi <<= 1;
    }
    while (hi - lo > 1) {
        uint64_t mid = lo + (hi - lo) / 2;
        u128 acc;
        if (u128_pow(mid, root, &acc) || u128_cmp(acc, target) > 0)
            hi = mid;
        else
            lo = mid;
    }
    return (uint32_t)(lo & 0xffffffffu);
}

static void first_primes(uint32_t *out, int count)
{
    int have = 0;
    uint32_t cand;
    for (cand = 2; have < count; cand++) {
        uint32_t d;
        int prime = 1;
        for (d = 2; d * d <= cand; d++)
            if (cand % d == 0) { prime = 0; break; }
        if (prime)
            out[have++] = cand;
    }
}

static void sha_init_constants(void)
{
    uint32_t primes[64];
    int i;
    if (sha_ready)
        return;
    first_primes(primes, 64);
    for (i = 0; i < 64; i++)
        SHA_K[i] = root_frac32(primes[i], 3);
    for (i = 0; i < 8; i++)
        SHA_H0[i] = root_frac32(primes[i], 2);
    sha_ready = 1;
}

static uint32_t rotr32(uint32_t x, int n)
{
    return (x >> n) | (x << (32 - n));
}

static void sha256_block(sha256 *s, const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, h;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) |
               ((uint32_t)p[4 * i + 2] << 8) | (uint32_t)p[4 * i + 3];
    for (i = 16; i < 64; i++) {
        uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^
                      (w[i - 15] >> 3);
        uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^
                      (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (i = 0; i < 64; i++) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + SHA_K[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha256_start(sha256 *s)
{
    sha_init_constants();
    memcpy(s->h, SHA_H0, sizeof s->h);
    s->bits = 0;
    s->have = 0;
}

static void sha256_push(sha256 *s, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    s->bits += (uint64_t)n * 8u;
    while (n) {
        size_t take = 64 - s->have;
        if (take > n)
            take = n;
        memcpy(s->buf + s->have, p, take);
        s->have += take;
        p += take;
        n -= take;
        if (s->have == 64) {
            sha256_block(s, s->buf);
            s->have = 0;
        }
    }
}

static void sha256_end(sha256 *s, uint8_t out[32])
{
    uint64_t bits = s->bits;
    int i;
    s->buf[s->have++] = 0x80;
    if (s->have > 56) {
        while (s->have < 64)
            s->buf[s->have++] = 0;
        sha256_block(s, s->buf);
        s->have = 0;
    }
    while (s->have < 56)
        s->buf[s->have++] = 0;
    for (i = 7; i >= 0; i--)
        s->buf[s->have++] = (uint8_t)(bits >> (8 * i));
    sha256_block(s, s->buf);
    for (i = 0; i < 8; i++) {
        out[4 * i]     = (uint8_t)(s->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)s->h[i];
    }
}

static void hex32(const uint8_t in[32], char out[65])
{
    static const char D[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 32; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[64] = 0;
}

/* ---- files --------------------------------------------------------- */

static uint8_t *read_file(const char *path, size_t *n_out)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf;
    size_t cap = 1 << 16, have = 0;
    if (!f)
        die("cannot open %s", path);
    buf = (uint8_t *)xcalloc(cap, 1);
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *bigger = (uint8_t *)xcalloc(cap * 2, 1);
            memcpy(bigger, buf, have);
            free(buf);
            buf = bigger;
            cap *= 2;
        }
        got = fread(buf + have, 1, cap - have, f);
        have += got;
        if (got == 0)
            break;
    }
    fclose(f);
    *n_out = have;
    return buf;
}

static void write_file(const char *path, const void *data, size_t n)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        die("cannot write %s", path);
    if (fwrite(data, 1, n, f) != n)
        die("short write to %s", path);
    fclose(f);
}

static uint32_t get_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- the image header, read here so the tool can choose a path
 * before the library ever sees the bytes ----------------------------- */

typedef struct {
    uint32_t n_insns, n_consts, max_deposits, prec, flags;
    uint32_t n_scratch_in, n_scratch_out;
    int      uses_scratch;      /* any of the four control codes */
} header;

static void parse_header(const uint8_t *img, size_t n, header *H)
{
    uint32_t scratch_io;
    if (n < HEADER_BYTES)
        die("the image is shorter than a header");
    if (get_le32(img) != 0x50544643u)
        die("that file does not begin with CFTP");
    if (get_le32(img + 4) != 1u)
        die("program version %u; this tool speaks 1",
            (unsigned)get_le32(img + 4));
    H->n_insns      = get_le32(img + 8);
    H->n_consts     = get_le32(img + 12);
    H->max_deposits = get_le32(img + 16);
    H->prec         = get_le32(img + 20);
    H->flags        = get_le32(img + 24);
    scratch_io      = get_le32(img + 28);
    H->uses_scratch = 0;
    if (H->prec > 3)
        die("precision code %u is not on the ladder", (unsigned)H->prec);
    if (H->flags & ~FLAGS_KNOWN)
        die("header flags 0x%08x: only BANK_EXT and SCRATCH_IO are "
            "defined", (unsigned)H->flags);
    if (!(H->flags & FLAG_SCRATCH_IO) && scratch_io)
        die("reserved header word 7 must be zero unless flags.SCRATCH_IO "
            "says it is scratch_io");
    H->n_scratch_in  = scratch_io & 0xFFFFu;
    H->n_scratch_out = (scratch_io >> 16) & 0xFFFFu;
}

/* Does the instruction stream reach the scratch at all? Read here so
 * that a build without the scratch can say WHICH feature it lacks,
 * rather than letting cft_program_load report an unknown control code.
 * The image is already known to be exactly its header, constants and
 * instructions by the time this runs. */
static void scan_scratch(const uint8_t *img, size_t bytes, header *H,
                         size_t esz)
{
    size_t off = HEADER_BYTES +
                 ((H->flags & FLAG_BANK_EXT) ? 0 : (size_t)H->n_consts * esz);
    uint32_t i;
    for (i = 0; i < H->n_insns; i++) {
        const uint8_t *w = img + off + (size_t)i * 8;
        uint32_t lo;
        if (off + (size_t)i * 8 + 8 > bytes)
            return;
        lo = get_le32(w);
        if ((lo >> 31) & 1u) {
            uint32_t code = lo & 0xFFu;
            if (code >= C_STL && code <= C_LDX)
                H->uses_scratch = 1;
        }
    }
}

/* ---- flags, for the human line ------------------------------------- */

static void flag_words(uint32_t fl, char *out, size_t cap)
{
    static const struct { uint32_t bit; const char *name; } F[5] = {
        { CFT_FLAG_INVALID,   "invalid"   },
        { CFT_FLAG_DIVBYZERO, "divbyzero" },
        { CFT_FLAG_OVERFLOW,  "overflow"  },
        { CFT_FLAG_UNDERFLOW, "underflow" },
        { CFT_FLAG_INEXACT,   "inexact"   }
    };
    int i;
    out[0] = 0;
    for (i = 0; i < 5; i++)
        if (fl & F[i].bit) {
            if (out[0])
                strncat(out, " ", cap - strlen(out) - 1);
            strncat(out, F[i].name, cap - strlen(out) - 1);
        }
    if (!out[0])
        strncat(out, "clean", cap - strlen(out) - 1);
}

/* ---- usage --------------------------------------------------------- */

static void usage(void)
{
    printf(
"positive-run - run a program image and hash what it deposited\n"
"\n"
"  positive-run <image.cftp> (--iota n | --a A [--b B] [--c C])\n"
"               [--bank bank.bin] [--out deposits.bin]\n"
"               [--scratch-in in.bin] [--scratch-out out.bin]\n"
"               [--device sw|<xclbin>]\n"
"\n"
"  --iota n        stream a is the element index as a format-width\n"
"                  integer bit pattern (0, 1, 2, ...); b and c are +0\n"
"  --a/--b/--c     raw format-width streams read from files; the\n"
"                  element count comes from --a's length\n"
"  --bank PATH     a BANK_EXT program's constants: n_consts values,\n"
"                  raw, format-width, dense\n"
"  --scratch-in PATH   the per-run scratch block a SCRATCH_IO program\n"
"                  enters with: raw, format-width, LANE-MAJOR, exactly\n"
"                  n * n_scratch_in elements\n"
"  --scratch-out PATH  where to write the block it leaves, likewise\n"
"                  n * n_scratch_out elements\n"
"  --out PATH      write the raw deposit buffer\n"
"  --device sw     the software backend (default), or an .xclbin\n"
"  --capabilities  say which paths THIS BINARY carries, and exit\n"
"\n"
"The last line is the SHA-256 of the deposit buffer, and the one above\n"
"it the digest of the program and its bank - docs/PROGRAMS.md.\n");
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        die("%s needs a value", argv[*i]);
    return argv[++(*i)];
}

/* ---- main ---------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *image_path = NULL, *bank_path = NULL, *out_path = NULL;
    const char *device = NULL;
    const char *a_path = NULL, *b_path = NULL, *c_path = NULL;
    const char *sin_path = NULL, *sout_path = NULL;
    long long iota = -1;
    int i, have_bank_path;
    uint8_t *img = NULL, *bank = NULL;
    uint8_t *sin_buf = NULL, *sout_buf = NULL;
    size_t sin_bytes = 0, sout_bytes = 0;
    size_t img_bytes = 0, bank_bytes = 0;
    header H;
    size_t esz, n = 0;
    uint8_t *A = NULL, *B = NULL, *C = NULL, *dep = NULL;
    uint32_t *counts = NULL;
    uint32_t flags = 0, bus = 0;
    cft_device *dev = NULL;
    cft_program *prog = NULL;
    cft_status st;
    sha256 hs;
    uint8_t digest[32];
    char hex[65], words[64];
    size_t dep_bytes;
    uint64_t total = 0;
    uint32_t cmin = 0xffffffffu, cmax = 0;

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "-h") || !strcmp(arg, "--help")) {
            usage();
            return 0;
        } else if (!strcmp(arg, "--capabilities")) {
            /* What this BINARY can do, which is a property of the cft.h
             * it was compiled against and not of the device. A check
             * script asks before deciding whether a BANK_EXT row can
             * run at all, and gets a SKIP it can print rather than a
             * failure it has to interpret. */
#ifdef CFT_SEQ_FEAT_BANK_PTR
            printf("bank-path     present\n");
            printf("digest        cft_program_digest\n");
#else
            printf("bank-path     absent   "
                   "(cft.h defines no CFT_SEQ_FEAT_BANK_PTR)\n");
            printf("digest        local    "
                   "(no cft_program_digest in this library)\n");
#endif
#ifdef CFT_SEQ_FEAT_SCRATCH
            printf("scratch       present\n");
#else
            printf("scratch       absent   "
                   "(cft.h defines no CFT_SEQ_FEAT_SCRATCH)\n");
#endif
#ifdef CFT_SEQ_FEAT_SCRATCH_IO
            printf("scratch-io    present\n");
            printf("run-path      cft_program_run_ex\n");
#else
            printf("scratch-io    absent   "
                   "(cft.h defines no CFT_SEQ_FEAT_SCRATCH_IO)\n");
            printf("run-path      cft_program_run"
#ifdef CFT_SEQ_FEAT_BANK_PTR
                   " / cft_program_run_bank"
#endif
                   "\n");
#endif
            return 0;
        } else if (!strcmp(arg, "--iota")) {
            iota = strtoll(need(argc, argv, &i), NULL, 10);
            if (iota < 0)
                die("--iota takes a non-negative element count");
        } else if (!strcmp(arg, "--a")) a_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--b"))   b_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--c"))   c_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--bank")) bank_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--scratch-in"))
            sin_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--scratch-out"))
            sout_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--out"))  out_path = need(argc, argv, &i);
        else if (!strcmp(arg, "--device")) device = need(argc, argv, &i);
        else if (arg[0] == '-' && arg[1])
            die("unknown option %s", arg);
        else if (image_path)
            die("one image at a time");
        else
            image_path = arg;
    }
    if (!image_path) {
        usage();
        return 1;
    }
    if (iota >= 0 && a_path)
        die("--iota and --a are two ways to fill the same stream");
    if (iota < 0 && !a_path)
        die("give the input: --iota n, or --a with a file");

    img = read_file(image_path, &img_bytes);
    parse_header(img, img_bytes, &H);
    esz = cft_format_size((cft_format)H.prec);
    scan_scratch(img, img_bytes, &H, esz);
    have_bank_path = bank_path != NULL;

    /* what the header says the image should be, checked before the
     * library sees it so the message names the file rather than the
     * loader */
    {
        size_t carried = (H.flags & FLAG_BANK_EXT) ? 0 : H.n_consts;
        size_t want = HEADER_BYTES + carried * esz +
                      (size_t)H.n_insns * 8;
        if (img_bytes != want)
            die("%s is %lu bytes, its header describes %lu",
                image_path, (unsigned long)img_bytes, (unsigned long)want);
    }

    if ((H.flags & FLAG_BANK_EXT) && !have_bank_path)
        die("%s is a BANK_EXT program: it carries no constants, and a run "
            "must supply %u of them with --bank",
            image_path, (unsigned)H.n_consts);
    if (!(H.flags & FLAG_BANK_EXT) && have_bank_path)
        die("%s carries its own constants, so --bank has nothing to "
            "supply", image_path);

    /* The same, for revision 3's two halves, and for the same reason:
     * without the macros the loader would refuse the image for an
     * unknown control code or a non-zero reserved header word, which
     * is true and useless. */
#ifndef CFT_SEQ_FEAT_SCRATCH
    if (H.uses_scratch)
        die("%s uses the per-lane scratch (stl/ldl/stx/ldx) and this "
            "build of libcft predates it: cft.h defines no "
            "CFT_SEQ_FEAT_SCRATCH. Rebuild against a library that "
            "carries docs/SEQUENCER.md revision 3's R4. "
            "(`positive-run --capabilities` reports this without a file.)",
            image_path);
#endif
#ifndef CFT_SEQ_FEAT_SCRATCH_IO
    if (H.flags & FLAG_SCRATCH_IO)
        die("%s declares a per-run scratch block (flags.SCRATCH_IO, "
            "in %u out %u) and this build of libcft predates it: cft.h "
            "defines no CFT_SEQ_FEAT_SCRATCH_IO, so cft_program_run_ex "
            "does not exist here. Rebuild against a library that carries "
            "docs/SEQUENCER.md revision 3's R5. "
            "(`positive-run --capabilities` reports this without a file.)",
            image_path, (unsigned)H.n_scratch_in,
            (unsigned)H.n_scratch_out);
#endif

    /* The same two rules for the scratch block. A program that
     * declares one needs it supplied - the block is run DATA, and a
     * run whose data nobody agreed on is the failure --bank's rules
     * exist to make impossible - while a program that declares none
     * has nowhere to put a file it was handed. --scratch-out is
     * different in kind: it is a place to WRITE, like --out, so it is
     * optional and the buffer exists either way. */
    if (H.n_scratch_in && !sin_path)
        die("%s declares a scratch-in block of %u slots a lane: give it "
            "with --scratch-in", image_path, (unsigned)H.n_scratch_in);
    if (!H.n_scratch_in && sin_path)
        die("%s declares no scratch-in block, so --scratch-in has nothing "
            "to supply", image_path);
    if (!H.n_scratch_out && sout_path)
        die("%s declares no scratch-out block, so --scratch-out would "
            "write nothing", image_path);

    if (have_bank_path) {
        bank = read_file(bank_path, &bank_bytes);
        if (bank_bytes != (size_t)H.n_consts * esz)
            die("%s is %lu bytes; this program addresses %u constants of "
                "%lu bytes, so the bank is %lu",
                bank_path, (unsigned long)bank_bytes,
                (unsigned)H.n_consts, (unsigned long)esz,
                (unsigned long)((size_t)H.n_consts * esz));
    }

    /* ---- the streams ------------------------------------------------ */
    if (iota >= 0) {
        size_t k;
        n = (size_t)iota;
        if (esz < 8 && (uint64_t)n > ((uint64_t)1 << (8 * esz)))
            die("an index ramp of %lu does not fit %s's %lu bytes",
                (unsigned long)n, cft_format_name((cft_format)H.prec),
                (unsigned long)esz);
        A = (uint8_t *)xcalloc(n ? n : 1, esz);
        B = (uint8_t *)xcalloc(n ? n : 1, esz);
        C = (uint8_t *)xcalloc(n ? n : 1, esz);
        /* the element index as a format-width INTEGER bit pattern, not
         * as a float: this is the index ramp docs/ATLAS.md's plates
         * take, and the integer opcodes are what read it */
        for (k = 0; k < n; k++) {
            uint64_t v = (uint64_t)k;
            size_t byte;
            for (byte = 0; byte < 8 && byte < esz; byte++)
                A[k * esz + byte] = (uint8_t)(v >> (8 * byte));
        }
    } else {
        size_t an, bn, cn;
        A = read_file(a_path, &an);
        if (an == 0 || an % esz)
            die("%s is %lu bytes, not a whole number of %s elements",
                a_path, (unsigned long)an,
                cft_format_name((cft_format)H.prec));
        n = an / esz;
        B = (uint8_t *)xcalloc(n, esz);
        C = (uint8_t *)xcalloc(n, esz);
        if (b_path) {
            uint8_t *tmp = read_file(b_path, &bn);
            if (bn != n * esz)
                die("%s is %lu bytes; --a gave %lu elements",
                    b_path, (unsigned long)bn, (unsigned long)n);
            memcpy(B, tmp, bn);
            free(tmp);
        }
        if (c_path) {
            uint8_t *tmp = read_file(c_path, &cn);
            if (cn != n * esz)
                die("%s is %lu bytes; --a gave %lu elements",
                    c_path, (unsigned long)cn, (unsigned long)n);
            memcpy(C, tmp, cn);
            free(tmp);
        }
    }

    /* ---- the scratch block, now that `n` is known ------------------ */
    sin_bytes  = n * (size_t)H.n_scratch_in * esz;
    sout_bytes = n * (size_t)H.n_scratch_out * esz;
    if (sin_path) {
        size_t got;
        sin_buf = read_file(sin_path, &got);
        if (got != sin_bytes)
            die("%s is %lu bytes; %lu lanes x %u slots x %lu bytes is %lu "
                "- the block is lane-major and dense",
                sin_path, (unsigned long)got, (unsigned long)n,
                (unsigned)H.n_scratch_in, (unsigned long)esz,
                (unsigned long)sin_bytes);
    }
    if (sout_bytes)
        sout_buf = (uint8_t *)xcalloc(sout_bytes, 1);

    /* The bank path's refusal belongs HERE, before the library is
     * handed the image - today's cft_program_load refuses a BANK_EXT
     * header for its non-zero reserved word and reports "artifact
     * missing, unreadable, or not a tile", which is true of the
     * loader's rules and useless to the person holding the file. */
#ifndef CFT_SEQ_FEAT_BANK_PTR
    if (H.flags & FLAG_BANK_EXT)
        die("%s is a BANK_EXT program and this build of libcft has no "
            "bank path: cft.h defines no CFT_SEQ_FEAT_BANK_PTR, so "
            "cft_program_run_bank does not exist here. Rebuild against a "
            "library that carries docs/SEQUENCER.md revision 2's R3. "
            "(`positive-run --capabilities` reports this without a file.)",
            image_path);
#endif

    /* ---- the device -------------------------------------------------- */
    if (device && strcmp(device, "sw") != 0)
        st = cft_open(device, 0, &dev);
    else
        st = cft_open(NULL, 0, &dev);
    if (st != CFT_OK)
        die_st("cft_open", st);

    st = cft_program_load(dev, img, img_bytes, &prog);
    if (st != CFT_OK)
        die_st("cft_program_load", st);

    dep_bytes = n * (size_t)H.max_deposits * esz;
    dep = (uint8_t *)xcalloc(dep_bytes ? dep_bytes : 1, 1);
    counts = (uint32_t *)xcalloc(n ? n : 1, sizeof(uint32_t));

#ifdef CFT_SEQ_FEAT_SCRATCH_IO
    /* ABI 0.10's one entry point that takes everything a run can
     * carry, so this tool stops growing a branch per feature. The
     * struct is zeroed and struct_size-stamped, which is how a caller
     * built against an older header still works against a newer
     * library. */
    {
        cft_run_args ra;
        memset(&ra, 0, sizeof ra);
        ra.struct_size = sizeof ra;
        ra.a = A;
        ra.b = B;
        ra.c = C;
        ra.n = n;
        ra.bank = bank;
        ra.bank_bytes = bank_bytes;
        ra.scratch_in = sin_buf;
        ra.scratch_in_bytes = sin_buf ? sin_bytes : 0;
        ra.scratch_out = sout_buf;
        ra.scratch_out_bytes = sout_buf ? sout_bytes : 0;
        ra.deposits = dep;
        ra.counts = counts;
        ra.flags_out = &flags;
        ra.bus_out = &bus;
        st = cft_program_run_ex(prog, &ra);
        if (st != CFT_OK)
            die_st("cft_program_run_ex", st);
    }
#else
    if (H.flags & FLAG_BANK_EXT) {
#ifdef CFT_SEQ_FEAT_BANK_PTR
        st = cft_program_run_bank(prog, bank, bank_bytes, A, B, C,
                                  dep, counts, n, &flags, &bus);
        if (st != CFT_OK)
            die_st("cft_program_run_bank", st);
#else
        /* Unreachable: refused above, before the load. Kept so that
         * the two halves of the #ifdef are both complete statements
         * and a reader of this branch is not left wondering. */
        die("this build has no bank path");
#endif
    } else {
        st = cft_program_run(prog, A, B, C, dep, counts, n, &flags, &bus);
        if (st != CFT_OK)
            die_st("cft_program_run", st);
    }
#endif

    /* ---- the report -------------------------------------------------- */
    printf("image         %s\n", image_path);
    printf("format        %s\n", cft_format_name((cft_format)H.prec));
    printf("instructions  %u\n", (unsigned)H.n_insns);
    printf("constants     %u%s\n", (unsigned)H.n_consts,
           (H.flags & FLAG_BANK_EXT) ? "  (from the bank)" : "");
    printf("deposits      %u a lane\n", (unsigned)H.max_deposits);
    printf("elements      %lu%s\n", (unsigned long)n,
           (iota >= 0) ? "  (index ramp)" : "");
    if (have_bank_path)
        printf("bank          %s, %lu bytes\n", bank_path,
               (unsigned long)bank_bytes);
    /* The scratch block is run data, so what went in gets a hash of
     * its own beside what came out - the digest line below covers the
     * image and the bank, which is what cft_program_digest returns and
     * what a plate quotes for "which program, which constants". */
    if (H.n_scratch_in) {
        sha256_start(&hs);
        sha256_push(&hs, sin_buf, sin_bytes);
        sha256_end(&hs, digest);
        hex32(digest, hex);
        printf("scratch-in    %s  %s, %lu bytes (%lu lanes x %u)\n",
               hex, sin_path, (unsigned long)sin_bytes,
               (unsigned long)n, (unsigned)H.n_scratch_in);
    }
    if (H.n_scratch_out) {
        sha256_start(&hs);
        sha256_push(&hs, sout_buf, sout_bytes);
        sha256_end(&hs, digest);
        hex32(digest, hex);
        printf("scratch-out   %s  %s%s%lu bytes (%lu lanes x %u)\n",
               hex, sout_path ? sout_path : "", sout_path ? ", " : "",
               (unsigned long)sout_bytes, (unsigned long)n,
               (unsigned)H.n_scratch_out);
    }
    printf("device        %s\n",
           (device && strcmp(device, "sw")) ? device : "software");

    {
        size_t k;
        for (k = 0; k < n; k++) {
            total += counts[k];
            if (counts[k] < cmin) cmin = counts[k];
            if (counts[k] > cmax) cmax = counts[k];
        }
    }
    if (!n) { cmin = 0; cmax = 0; }
    printf("counts        min %u, max %u, total %llu\n",
           (unsigned)cmin, (unsigned)cmax, (unsigned long long)total);

    flag_words(flags, words, sizeof words);
    printf("flags         0x%08x  %s\n", (unsigned)flags, words);
    printf("status        0x%08x%s\n", (unsigned)bus,
           (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
           ? "  deposit-overflow: a lane deposited more than max_deposits"
           : "");

    /* the program digest: image bytes, then bank bytes */
    {
        int from_library = 0;
#ifdef CFT_SEQ_FEAT_BANK_PTR
        st = cft_program_digest(prog, bank, bank_bytes, digest);
        if (st != CFT_OK)
            die_st("cft_program_digest", st);
        from_library = 1;
#endif
        if (!from_library) {
            sha256_start(&hs);
            sha256_push(&hs, img, img_bytes);
            if (bank_bytes)
                sha256_push(&hs, bank, bank_bytes);
            sha256_end(&hs, digest);
        }
        hex32(digest, hex);
        printf("digest        %s%s\n", hex,
               from_library ? "  program and bank"
                            : "  program and bank (computed here: this "
                              "build has no cft_program_digest)");
    }

    if (out_path)
        write_file(out_path, dep, dep_bytes);
    if (sout_path)
        write_file(sout_path, sout_buf, sout_bytes);

    /* The last line, and the one a plate's attestation carries.
     * Labelled distinctly from the `deposits N a lane` line above:
     * two lines under one key is a report nobody can parse. */
    sha256_start(&hs);
    sha256_push(&hs, dep, dep_bytes);
    sha256_end(&hs, digest);
    hex32(digest, hex);
    printf("sha256        %s  deposit buffer\n", hex);

    cft_program_free(prog);
    cft_close(dev);
    free(img);
    free(bank);
    free(sin_buf);
    free(sout_buf);
    free(A);
    free(B);
    free(C);
    free(dep);
    free(counts);
    return 0;
}
