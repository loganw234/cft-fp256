/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-audit - the audit of docs/CERTIFICATES.md, version 1, in C: every
 * step of "The audit", the strict reader included, in the page's order,
 * beside the golden one (python/cft_golden/cert.py, cert.audit). The
 * plan of record's step 4 (docs/ROADMAP.md, "Steps 4 and 7"); the page's
 * section "The audit tool" is this tool's manual.
 *
 *   cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]
 *             --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]
 *                     [--choose all|sample:K|K,K,...]
 *             [--run 1 --image IMG ...] ...
 *   cft-audit --read --cert CERT [--salt SALT]
 *   cft-audit --sample SEED R S K
 *
 * ---------------------------------------------------------------
 * What it is handed
 * ---------------------------------------------------------------
 *
 * Each option is one argument of cert.audit, so that a gate can hand the
 * two auditors the same inputs (host/tests/audit_check.py):
 *
 *   --cert CERT     the certificate's bytes (`data`)
 *   --salt SALT     the salt, a file of any length (`salt`); its length is
 *                   step 3's to refuse, `salt-length`. Absent: no salt
 *   --run R         opens run R's block; the options after it, up to the
 *                   next --run, are run R's: --image and --bank are
 *                   programs[R] = (image, bank), --stream X FILE is
 *                   streams[R]'s stream X (the others +0), --choose is
 *                   choose[R]: `all`, `sample:K`, or segments `K,K,...`
 *   --states DIR    every file named run-<r>-boundary-<b>.bin, r and b in
 *                   their one decimal spelling, is states[r][b]: the
 *                   files cft-segrun writes. Other files are not read
 *   --seed HEX      the sampling seed, 64 hex digits (`seed`). Absent and a
 *                   sample asked: 32 bytes drawn from the operating system,
 *                   and printed
 *
 * A run index that names no run of the certificate is refused by the
 * name of the step that reads that argument, as cert.audit refuses a key
 * that is no run: `choice`, `program-image`, `stream`; a state file for a
 * run or boundary that does not exist, `state-shape`.
 *
 * --read is cert.parse(data, salt): the hash line, the body's hash and
 * the strict form, and with --salt the salt against the mode and the
 * commitment. --sample prints cert.sample(seed, R, S, K), the segments
 * a sample of K of S draws for run R under SEED, so that the PRNG is held
 * to the page's test vector as cft-segrun's --hash holds the hashes.
 *
 * ---------------------------------------------------------------
 * What it answers
 * ---------------------------------------------------------------
 *
 * Accepted: stdout is the golden verdict's lines (cert.Verdict.lines()),
 * byte for byte, and the exit code is 0. Refused: stderr carries
 *
 *   cft-audit: refused <name>: <why>
 *   cft-audit: location line=<n> run=<r> segment=<k> entry=<j>
 *
 * each field `-` where it does not apply (the golden Refusal's .line,
 * .run, .segment and .entry), and the exit code is the name's. Every name
 * and code is the page's table's, and the same check refuses the same
 * defect by the same name at the same place as the golden auditor does:
 * that is what the gate holds. Four names are the tool's own:
 *   usage (64)        a command line this tool does not take, or a file
 *                     it names that cannot be read
 *   memory (71)       an allocation of this tool's own that fails
 *   build-width (78)  a build whose bigint is narrower than the width
 *                     rule needs, handed a certificate with an accuracy
 *                     entry (below)
 *   build-format (78) a build whose library carries formats only up to
 *                     CFT_MAX_FORMAT, handed a run of a wider format: the
 *                     reader refuses it at that run's program-format line
 *                     (the lead's decision, 2026-09-29, after
 *                     verifier-A1 found such a run refused program-image,
 *                     a name for an input that is not the one certified,
 *                     where the cause is the build)
 * A library call that fails where no refusal names the failure (a
 * software device that does not open, a conversion that fails) is not a
 * verdict: it prints "cft-audit: internal error" and exits 70.
 *
 * ---------------------------------------------------------------
 * How it computes
 * ---------------------------------------------------------------
 *
 * Re-runs go through libcft's software backend at each run's depth - the
 * page's "The chain": 1 << CAPS2[3:0] where device-caps carries CAPS2
 * with bit 4 set, else the run's `scratch-depth` parameter where it
 * states one, else 256 - through cft_open_ex, one handle a depth.
 *
 * Exact values go through the library's own 2,048-bit unsigned bigint,
 * cft_bn (host/src/bigint.h, an internal header: the lead's decision of
 * 2026-09-29), which the width rule was sized for: every in-rule step
 * needs at most 2 x 1,023 + 1 bits. cft_bn has no division, no gcd and a
 * left shift that keeps a spare limb; those three are this file's, on
 * the library's struct, and the gate holds them to Python's integers. A
 * build whose cft_bn is narrower than 2,047 bits compiles WITHOUT the
 * exact arithmetic (a #if, not an #error) and its reader refuses
 * `build-width` at an `accuracy` line counting at least 1: no build ever
 * computes an exact value in a narrower bigint. A certificate with
 * `accuracy 0` it audits in full.
 *
 * An element's exact decimal is cft_to_decimal_char at 0 digits, which is
 * exact; a value exactly widened is cft_convert one rung up; a rational
 * rounded into a format is one integer division here and then
 * cft_from_hex_char on the dyadic value it leaves, which is round_pack's
 * answer, as the golden's _round_rational hands round_pack the same.
 * A rational token is held to the width rule by its digits before any
 * gcd, so no token past 1,023 bits is ever held; its lowest-terms test
 * is on cft_bn too. Every hash is the library's own streaming SHA-256
 * (host/src/sha256.h, which cft_sha256 wraps), so a state is hashed
 * where it lies and a +0 stream needs no buffer.
 *
 * What it spends is bounded by what it is handed, never by a number the
 * certificate states ("What an audit spends"): a run's `lanes` is
 * compared with the sizes handed by division and never multiplied, and
 * a run's +0 streams are hashed only when the run is BOUNDED - handed a
 * stream, or a state for a boundary 0..S of at least `lanes` elements.
 *
 * ---------------------------------------------------------------
 * What it proves, and what it does not
 * ---------------------------------------------------------------
 *
 * What the page's "What an audit proves" says, for the segments it
 * re-runs, on libcft's software backend. It is independent of the golden
 * model: it re-runs with the library and reads with this file's reader.
 * It is not independent of the library: for a certificate cft-segrun
 * made on the software backend, libcft made it, and only the golden
 * auditor is an implementation apart from the producer.
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200112L
#  define _DEFAULT_SOURCE
#  define _DARWIN_C_SOURCE
#else
#  define _CRT_RAND_S               /* rand_s: the operating system's */
#endif

#include <dirent.h>
#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "cft.h"
#include "../src/bigint.h"
#include "../src/sha256.h"

#if defined(__GNUC__)
#  define NORETURN __attribute__((noreturn))
#  if defined(__MINGW_PRINTF_FORMAT)
#    define PRINTF_LIKE(f, a) \
         __attribute__((format(__MINGW_PRINTF_FORMAT, f, a)))
#  else
#    define PRINTF_LIKE(f, a) __attribute__((format(printf, f, a)))
#  endif
#else
#  define NORETURN
#  define PRINTF_LIKE(f, a)
#endif

/* The width rule: 1,023 bits a numerator or a denominator. One exact step
 * on two in-rule values needs 2 x 1,023 + 1 bits, so a cft_bn narrower
 * than that is not a conforming auditor of exact values (the page, "The
 * width rule"). */
#define WIDTH_BITS   1023
#define AUDIT_EXACT  (CFT_BN_LIMBS * 32 >= 2 * WIDTH_BITS + 1)

#define SALT_BYTES   32
#define SEED_BYTES   32
#define MAX_HSLOTS   512       /* h-slots at most, each below it */
#define MAX_TERMS    64
#define MAX_FACTORS  8
#define MAX_SLOT     0xFFFFu   /* a term's slot: the scratch counts are 16-bit */
#define DEC_MAX      ((uint64_t)INT64_MAX)
#define NONE         (-1LL)

/* ---- the formats ------------------------------------------------------- */

typedef struct {
    const char *name;
    int width, ew, mw;          /* bits: whole, exponent, trailing significand */
} fmt_t;

static const fmt_t FMT[4] = {
    { "fp32", 32, 8, 23 }, { "fp64", 64, 11, 52 },
    { "fp128", 128, 15, 112 }, { "fp256", 256, 19, 236 },
};
#define ESZ(f)   ((size_t)FMT[f].width / 8)
#define PREC(f)  (FMT[f].mw + 1)
#define BIAS(f)  ((1L << (FMT[f].ew - 1)) - 1)
#define EMIN(f)  (1 - BIAS(f))

static const char *const RND_NAME[5] = { "rne", "rtz", "rdn", "rup", "rmm" };
static const cft_round RND_CODE[5] = { CFT_RNE, CFT_RTZ, CFT_RDN, CFT_RUP,
                                       CFT_RMM };

/* ---- refusals ---------------------------------------------------------- */

static const struct { const char *name; int code; } REFUSAL[] = {
    /* 1: integrity */
    { "hash-line", 1 }, { "body-hash", 1 },
    /* 2: form */
    { "magic", 2 }, { "version", 2 }, { "mode-unknown", 2 },
    { "commitment-missing", 2 }, { "commitment-unexpected", 2 },
    { "unknown-line", 2 }, { "line-missing", 2 }, { "line-order", 2 },
    { "line-unexpected", 2 }, { "count", 2 }, { "malformed", 2 },
    { "decimal", 2 }, { "accuracy-kind", 2 },
    /* 3: the width rule */
    { "width", 3 },
    /* 4: an input handed to the audit */
    { "salt-missing", 4 }, { "salt-unexpected", 4 }, { "salt-length", 4 },
    { "salt-commitment", 4 }, { "image-digest", 4 }, { "program-digest", 4 },
    { "program-image", 4 }, { "program-format", 4 }, { "program-shape", 4 },
    { "stream", 4 }, { "state-shape", 4 }, { "state-hash", 4 },
    { "state-missing", 4 },
    /* 5: the chain and the relations */
    { "continuity", 5 }, { "aux-format", 5 }, { "aux-lanes", 5 },
    { "aux-image", 5 }, { "aux-segments", 5 }, { "aux-h-slots", 5 },
    { "aux-bank", 5 }, { "aux-streams", 5 }, { "aux-start", 5 },
    /* 6: re-runs */
    { "segment-end", 6 }, { "segment-flags", 6 }, { "segment-status", 6 },
    /* 7: accuracy */
    { "accuracy-run", 7 }, { "accuracy-scope", 7 }, { "accuracy-slot", 7 },
    { "accuracy-finite", 7 }, { "accuracy-value", 7 },
    /* 64: the auditor's own choice */
    { "choice", 64 },
    /* the tool's own */
    { "usage", 64 }, { "memory", 71 }, { "build-width", 78 },
    { "build-format", 78 },
};

/* Where a refusal is: each field NONE where it does not apply. */
typedef struct { long long line, run, seg, entry; } where_t;

static where_t at(long long line, long long run, long long seg,
                  long long entry)
{
    where_t w;
    w.line = line;
    w.run = run;
    w.seg = seg;
    w.entry = entry;
    return w;
}
#define NOWHERE        at(NONE, NONE, NONE, NONE)
#define AT_LINE(n)     at((long long)(n), NONE, NONE, NONE)
#define AT_RUN(r)      at(NONE, (long long)(r), NONE, NONE)
#define AT_RS(r, k)    at(NONE, (long long)(r), (long long)(k), NONE)

/* The entry a refusal of step 10 belongs to, added to what derive() says,
 * as cert.audit re-raises derive's refusals with entry=j. */
static long long ENTRY_NOW = NONE;

static void refuse(const char *name, where_t w, const char *fmt, ...)
    NORETURN PRINTF_LIKE(3, 4);

static void put_field(const char *k, long long v)
{
    if (v == NONE)
        fprintf(stderr, " %s=-", k);
    else
        fprintf(stderr, " %s=%lld", k, v);
}

static void refuse(const char *name, where_t w, const char *fmt, ...)
{
    va_list ap;
    size_t i;
    int code = -1;
    for (i = 0; i < sizeof REFUSAL / sizeof REFUSAL[0]; i++)
        if (!strcmp(REFUSAL[i].name, name))
            code = REFUSAL[i].code;
    if (code < 0) {
        fprintf(stderr, "cft-audit: internal error: unnamed refusal '%s'\n",
                name);
        exit(70);
    }
    if (ENTRY_NOW != NONE && w.entry == NONE)
        w.entry = ENTRY_NOW;
    fflush(stdout);
    fprintf(stderr, "cft-audit: refused %s: ", name);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    fprintf(stderr, "cft-audit: location");
    put_field("line", w.line);
    put_field("run", w.run);
    put_field("segment", w.seg);
    put_field("entry", w.entry);
    fputc('\n', stderr);
    exit(code);
}

/* A library call that failed where no refusal names the failure. */
static void internal(const char *what, cft_status st) NORETURN;
static void internal(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-audit: internal error: %s: %s%s%s\n", what,
            cft_strerror(st), d && *d ? " - " : "", d && *d ? d : "");
    exit(70);
}

/* ---- memory ------------------------------------------------------------ */

static void *xalloc(size_t n, size_t sz)
{
    void *p;
    if (sz && n > (size_t)-1 / sz)
        p = NULL;
    else
        p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        refuse("memory", NOWHERE, "%llu x %llu bytes could not be allocated",
               (unsigned long long)n, (unsigned long long)sz);
    return p;
}

/* ---- files ------------------------------------------------------------- */

static uint8_t *read_file(const char *path, size_t *n_out)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf;
    size_t cap = 1 << 16, have = 0;
    if (!f)
        return NULL;
    buf = (uint8_t *)xalloc(cap, 1);
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *bigger = (uint8_t *)xalloc(cap, 2);
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
    if (ferror(f)) {
        int e = errno;
        fclose(f);
        free(buf);
        errno = e ? e : EIO;
        return NULL;
    }
    fclose(f);
    *n_out = have;
    return buf;
}

static uint8_t *read_named(const char *what, const char *path, size_t *n)
{
    uint8_t *p = read_file(path, n);
    if (!p)
        refuse("usage", NOWHERE, "%s %s cannot be read (%s)", what, path,
               strerror(errno));
    return p;
}

/* ---- the software devices ---------------------------------------------- */

/* One software handle a depth: the host operations (decimals, widening,
 * rounding) take the one at 256, and each run is loaded on the one at
 * its own depth. */
typedef struct { uint32_t depth; cft_device *dev; } devslot;
static devslot DEVS[16];
static size_t N_DEVS = 0;

static cft_device *dev_at(uint32_t depth)
{
    size_t i;
    cft_open_args oa;
    cft_status st;
    for (i = 0; i < N_DEVS; i++)
        if (DEVS[i].depth == depth)
            return DEVS[i].dev;
    if (N_DEVS == sizeof DEVS / sizeof DEVS[0])
        internal("more depths than this tool keeps handles for",
                 CFT_ERR_INTERNAL);
    memset(&oa, 0, sizeof oa);
    oa.struct_size = sizeof oa;
    oa.artifact = NULL;
    oa.index = 0;
    oa.scratch_depth = depth;
    st = cft_open_ex(&oa, &DEVS[N_DEVS].dev);
    if (st != CFT_OK)
        internal("cft_open_ex, the software backend", st);
    DEVS[N_DEVS].depth = depth;
    return DEVS[N_DEVS++].dev;
}

static cft_device *host_dev(void)
{
    return dev_at(256);
}

/* ---- the hashes -------------------------------------------------------- */

static const char TAG_SALT[]   = "cft-certificate 1 salt";
#define TAG_SALT_LEN   (sizeof TAG_SALT - 1)       /* 22, no NUL */
static const char TAG_STATE[]  = "cft-certificate 1 state";
#define TAG_STATE_LEN  (sizeof TAG_STATE)          /* 24, the NUL included */
static const char *const TAG_STREAM[3] = {
    "cft-certificate 1 stream a", "cft-certificate 1 stream b",
    "cft-certificate 1 stream c" };
#define TAG_STREAM_LEN 27                          /* the NUL included */
static const char TAG_SAMPLE[] = "cft-certificate 1 sample";
#define TAG_SAMPLE_LEN (sizeof TAG_SAMPLE)         /* 25, the NUL included */

static void hex_of(const uint8_t *in, size_t n, char *out)
{
    static const char D[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i] = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[2 * n] = 0;
}

static void sha256_of(const void *data, size_t n, uint8_t out[32])
{
    cft_status st = cft_sha256(data, n, out);
    if (st != CFT_OK)
        internal("cft_sha256", st);
}

/* n bytes into a running hash, or n zero bytes when `bytes` is NULL: a
 * +0 stream is hashed without a buffer of its own (the rule of "What an
 * audit spends": a bounded run's +0 streams, taken streaming). */
static void hash_push(cft_sha256_ctx *s, const void *bytes, size_t n)
{
    static const uint8_t ZERO[4096];
    if (bytes) {
        if (n)
            cft_sha256_update(s, bytes, n);
        return;
    }
    while (n) {
        size_t k = n < sizeof ZERO ? n : sizeof ZERO;
        cft_sha256_update(s, ZERO, k);
        n -= k;
    }
}

/* The hash of tag || bytes: HMAC-SHA-256 (RFC 2104, a 64-byte block)
 * under `salt` when keyed, plain SHA-256 when `salt` is NULL - through
 * the library's own streaming SHA-256 (host/src/sha256.h, which the
 * one-shot cft_sha256 wraps), so no state is copied to be hashed.
 * `bytes` NULL is n zero bytes. */
static void tagged_hash(const uint8_t *salt, const char *tag, size_t tag_len,
                        const void *bytes, size_t n, char hex[65])
{
    cft_sha256_ctx s;
    uint8_t d[32];
    if (salt) {
        uint8_t k[64], ih[32];
        size_t i;
        for (i = 0; i < 64; i++)
            k[i] = (uint8_t)((i < SALT_BYTES ? salt[i] : 0) ^ 0x36);
        cft_sha256_init(&s);
        cft_sha256_update(&s, k, 64);
        cft_sha256_update(&s, tag, tag_len);
        hash_push(&s, bytes, n);
        cft_sha256_final(&s, ih);
        for (i = 0; i < 64; i++)
            k[i] = (uint8_t)((i < SALT_BYTES ? salt[i] : 0) ^ 0x5c);
        cft_sha256_init(&s);
        cft_sha256_update(&s, k, 64);
        cft_sha256_update(&s, ih, 32);
        cft_sha256_final(&s, d);
    } else {
        cft_sha256_init(&s);
        cft_sha256_update(&s, tag, tag_len);
        hash_push(&s, bytes, n);
        cft_sha256_final(&s, d);
    }
    hex_of(d, 32, hex);
}

static void state_hash(const uint8_t *salt, const void *bytes, size_t n,
                       char hex[65])
{
    tagged_hash(salt, TAG_STATE, TAG_STATE_LEN, bytes, n, hex);
}

/* ---- spellings --------------------------------------------------------- */

static int is_hexl(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
}

static int hexval(char c)
{
    return c <= '9' ? c - '0' : c - 'a' + 10;
}

/* `0`, or a nonzero digit and digits: the one spelling, of any length */
static int dec_spelling(const char *s)
{
    size_t i, n = strlen(s);
    if (n == 0 || (s[0] == '0' && n > 1))
        return 0;
    for (i = 0; i < n; i++)
        if (s[i] < '0' || s[i] > '9')
            return 0;
    return 1;
}

/* cert._index: the one spelling, at most 19 digits and 2^63 - 1 */
static int index_of(const char *s, uint64_t *out)
{
    size_t i, n = strlen(s);
    uint64_t v = 0;
    if (!dec_spelling(s) || n > 19)
        return 0;
    for (i = 0; i < n; i++)
        v = v * 10u + (uint64_t)(s[i] - '0');
    if (v > DEC_MAX)
        return 0;
    *out = v;
    return 1;
}

static int hex_exact(const char *s, size_t n)
{
    size_t i;
    if (strlen(s) != n)
        return 0;
    for (i = 0; i < n; i++)
        if (!is_hexl(s[i]))
            return 0;
    return 1;
}

/* a label or a parameter's name: [a-z][a-z0-9-]{0,63} */
static int name_ok(const char *s)
{
    size_t i, n = strlen(s);
    if (n == 0 || n > 64 || s[0] < 'a' || s[0] > 'z')
        return 0;
    for (i = 1; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9') ||
              s[i] == '-'))
            return 0;
    return 1;
}

static int word_index(const char *s, const char *const *words, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (!strcmp(s, words[i]))
            return i;
    return -1;
}

/* ---- cft_bn: the library's bigint, and what it lacks ------------------- */

static void bn_norm(cft_bn *r)
{
    while (r->n > 0 && r->v[r->n - 1] == 0)
        r->n--;
}

static int bn_is_one(const cft_bn *a)
{
    return a->n == 1 && a->v[0] == 1;
}

static int bn_tz(const cft_bn *a)              /* a nonzero */
{
    int i, b;
    for (i = 0; i < a->n; i++) {
        uint32_t w = a->v[i];
        if (w) {
            b = 0;
            while (!(w & 1u)) {
                w >>= 1;
                b++;
            }
            return i * 32 + b;
        }
    }
    return 0;
}

/* r = a << k, exactly: 1 only if the result has more than CFT_BN_BITS
 * bits. (cft_bn_shl keeps a spare limb and refuses any shift of a value
 * that fills the container, a shift by 0 included.) r may alias a. */
static int bn_shl(cft_bn *r, const cft_bn *a, int k)
{
    int limbs = k >> 5, bits = k & 31, an = a->n, len, rn, i;
    if (a->n == 0) {
        r->n = 0;
        return 0;
    }
    len = cft_bn_bitlen(a);
    if (k < 0 || len > CFT_BN_BITS - k)
        return 1;
    rn = (len + k + 31) >> 5;
    for (i = rn - 1; i >= 0; i--) {
        int ih = i - limbs, il = i - limbs - 1;
        uint32_t hi = (ih >= 0 && ih < an) ? a->v[ih] : 0u;
        uint32_t lo = (il >= 0 && il < an) ? a->v[il] : 0u;
        r->v[i] = bits ? ((hi << bits) | (lo >> (32 - bits))) : hi;
    }
    r->n = rn;
    return 0;
}

/* q = a / b and rem = a % b (b nonzero), by shift and subtract; q or rem
 * may be NULL, and either may alias a or b. */
static void bn_divmod(cft_bn *q, cft_bn *rem, const cft_bn *a,
                      const cft_bn *b)
{
    cft_bn r, d, quo;
    int la = cft_bn_bitlen(a), lb = cft_bn_bitlen(b), s, i;
    cft_bn_copy(&r, a);
    cft_bn_zero(&quo);
    if (la >= lb) {
        s = la - lb;
        if (bn_shl(&d, b, s))
            internal("the audit's division", CFT_ERR_INTERNAL);
        for (i = s; i >= 0; i--) {
            if (cft_bn_cmp(&r, &d) >= 0) {
                cft_bn_sub(&r, &r, &d);
                cft_bn_setbit(&quo, i);
            }
            cft_bn_shr(&d, &d, 1);
        }
    }
    if (q)
        cft_bn_copy(q, &quo);
    if (rem)
        cft_bn_copy(rem, &r);
}

/* a / d for one limb d, into q (which may alias a); the remainder back */
static uint32_t bn_div_u32(cft_bn *q, const cft_bn *a, uint32_t d)
{
    uint64_t r = 0;
    int i;
    for (i = a->n - 1; i >= 0; i--) {
        uint64_t cur = (r << 32) | a->v[i];
        q->v[i] = (uint32_t)(cur / d);
        r = cur % d;
    }
    q->n = a->n;
    bn_norm(q);
    return (uint32_t)r;
}

static uint32_t gcd_u32(uint32_t a, uint32_t b)
{
    while (b) {
        uint32_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

/* g = gcd(a, b): the common power of two, then Stein on the odd parts,
 * with a single-limb Euclid once either part fits one limb. */
static void bn_gcd(cft_bn *g, const cft_bn *a0, const cft_bn *b0)
{
    cft_bn a, b;
    int za, zb, k;
    if (cft_bn_is_zero(a0)) {
        cft_bn_copy(g, b0);
        return;
    }
    if (cft_bn_is_zero(b0)) {
        cft_bn_copy(g, a0);
        return;
    }
    za = bn_tz(a0);
    zb = bn_tz(b0);
    k = za < zb ? za : zb;
    cft_bn_shr(&a, a0, za);
    cft_bn_shr(&b, b0, zb);
    for (;;) {
        int c;
        if (bn_is_one(&a) || bn_is_one(&b)) {
            cft_bn_set_u32(g, 1);
            break;
        }
        if (b.n == 1 || a.n == 1) {
            const cft_bn *big = b.n == 1 ? &a : &b;
            uint32_t small = b.n == 1 ? b.v[0] : a.v[0];
            cft_bn t;
            uint32_t r = bn_div_u32(&t, big, small);
            cft_bn_set_u32(g, gcd_u32(small, r));
            break;
        }
        c = cft_bn_cmp(&a, &b);
        if (c == 0) {
            cft_bn_copy(g, &a);
            break;
        }
        if (c > 0) {
            cft_bn_sub(&a, &a, &b);
            cft_bn_shr(&a, &a, bn_tz(&a));
        } else {
            cft_bn_sub(&b, &b, &a);
            cft_bn_shr(&b, &b, bn_tz(&b));
        }
    }
    if (k && bn_shl(g, g, k))
        internal("the audit's gcd", CFT_ERR_INTERNAL);
}

static void bn_from_hex(cft_bn *r, const char *h, size_t len)
{
    size_t i;
    int limbs = (int)((4 * len + 31) / 32);
    if (limbs > CFT_BN_LIMBS)
        internal("a hex value past the bigint", CFT_ERR_INTERNAL);
    for (i = 0; i < (size_t)limbs; i++)
        r->v[i] = 0;
    for (i = 0; i < len; i++) {
        size_t bit = 4 * (len - 1 - i);
        r->v[bit / 32] |= (uint32_t)hexval(h[i]) << (bit % 32);
    }
    r->n = limbs;
    bn_norm(r);
}

/* lowercase hex, no leading zeros; "0" for zero */
static void bn_hex(const cft_bn *a, char *out)
{
    static const char D[] = "0123456789abcdef";
    int nib = (cft_bn_bitlen(a) + 3) / 4, i;
    if (nib == 0) {
        strcpy(out, "0");
        return;
    }
    for (i = 0; i < nib; i++)
        out[i] = D[cft_bn_extract(a, 4 * (nib - 1 - i), 4)];
    out[nib] = 0;
}

/* ---- elements ---------------------------------------------------------- */

enum { EL_ZERO, EL_FINITE, EL_INF, EL_NAN };

typedef struct {
    int kind, sign;
    cft_bn m;       /* EL_FINITE: the significand, odd */
    long e;         /* EL_FINITE: the value is (-1)^sign m 2^e, m odd */
} elem_t;

/* An encoding's value (cert.element_fraction), reduced: m odd. */
static void decode(int f, const uint8_t *le, elem_t *x)
{
    cft_bn b;
    uint32_t biased, emask = (1u << FMT[f].ew) - 1u;
    int z;
    cft_bn_load(&b, le, (int)ESZ(f));
    x->sign = cft_bn_bit(&b, FMT[f].width - 1);
    biased = cft_bn_extract(&b, FMT[f].mw, FMT[f].ew);
    cft_bn_copy(&x->m, &b);
    cft_bn_mask(&x->m, FMT[f].mw);
    if (biased == emask) {
        x->kind = cft_bn_is_zero(&x->m) ? EL_INF : EL_NAN;
        return;
    }
    if (biased == 0) {
        if (cft_bn_is_zero(&x->m)) {
            x->kind = EL_ZERO;
            return;
        }
        x->e = EMIN(f) - FMT[f].mw;
    } else {
        cft_bn_setbit(&x->m, FMT[f].mw);
        x->e = (long)biased - BIAS(f) - FMT[f].mw;
    }
    x->kind = EL_FINITE;
    z = bn_tz(&x->m);
    cft_bn_shr(&x->m, &x->m, z);
    x->e += z;
}

/* The bits of a finite element's exact value, reduced: numerator and
 * denominator. Zero is 0/1. */
static void elem_bits(const elem_t *x, long *nb, long *db)
{
    if (x->kind == EL_ZERO) {
        *nb = 0;
        *db = 1;
        return;
    }
    *nb = cft_bn_bitlen(&x->m) + (x->e > 0 ? x->e : 0);
    *db = x->e < 0 ? -x->e + 1 : 1;
}

static void elem_from_hex(int f, const char *h, uint8_t *le)
{
    size_t i, n = ESZ(f);
    for (i = 0; i < n; i++)
        le[i] = (uint8_t)(hexval(h[2 * (n - 1 - i)]) << 4 |
                          hexval(h[2 * (n - 1 - i) + 1]));
}

/* x exactly half of y, both of format f, y finite and nonzero */
static int is_half(int f, const uint8_t *x_le, const uint8_t *y_le)
{
    elem_t x, y;
    decode(f, x_le, &x);
    decode(f, y_le, &y);
    return x.kind == EL_FINITE && x.sign == y.sign && x.e == y.e - 1 &&
           cft_bn_cmp(&x.m, &y.m) == 0;
}

/* n elements of format f, exactly widened one rung (cft_convert) */
static void widen(int f, const uint8_t *in, uint8_t *out, size_t n)
{
    uint32_t fl = 0;
    cft_status st;
    if (n == 0)
        return;
    st = cft_convert(host_dev(), (cft_format)f, (cft_format)(f + 1), CFT_RNE,
                     in, out, n, &fl);
    if (st != CFT_OK)
        internal("cft_convert", st);
}

/* the element's exact decimal is `dtok` (cft_to_decimal_char, 0 digits) */
static int decimal_is(int f, const uint8_t *le, const char *dtok)
{
    size_t tl = strlen(dtok), len = 0;
    char *buf = (char *)xalloc(tl + 1, 1);
    uint32_t fl = 0;
    int same;
    cft_status st = cft_to_decimal_char(host_dev(), (cft_format)f, CFT_RNE,
                                        le, 0, buf, tl + 1, &len, &fl);
    if (st == CFT_OK)
        same = strcmp(buf, dtok) == 0;
    else if (st == CFT_ERR_INVALID_ARGUMENT && len > tl + 1)
        same = 0;                   /* the exact decimal is longer */
    else
        internal("cft_to_decimal_char", st);
    free(buf);
    return same;
}

#if AUDIT_EXACT
/* ---- rationals, exact, under the width rule ---------------------------- */

typedef struct { int neg; cft_bn n, d; } rat;   /* reduced, d > 0; 0 is 0/1 */

static void rat_zero(rat *r)
{
    r->neg = 0;
    cft_bn_zero(&r->n);
    cft_bn_set_u32(&r->d, 1);
}

static void rat_reduce(rat *r)
{
    cft_bn g, odd;
    int z;
    if (cft_bn_is_zero(&r->n)) {
        rat_zero(r);
        return;
    }
    bn_gcd(&g, &r->n, &r->d);
    if (bn_is_one(&g))
        return;
    z = bn_tz(&g);
    cft_bn_shr(&odd, &g, z);
    cft_bn_shr(&r->n, &r->n, z);
    cft_bn_shr(&r->d, &r->d, z);
    if (bn_is_one(&odd))
        return;
    if (odd.n == 1) {
        bn_div_u32(&r->n, &r->n, odd.v[0]);
        bn_div_u32(&r->d, &r->d, odd.v[0]);
    } else {
        bn_divmod(&r->n, NULL, &r->n, &odd);
        bn_divmod(&r->d, NULL, &r->d, &odd);
    }
}

static int rat_in_rule(const rat *r)
{
    return cft_bn_bitlen(&r->n) <= WIDTH_BITS &&
           cft_bn_bitlen(&r->d) <= WIDTH_BITS;
}

/* The width rule, on a value just computed (cert._checked). */
static void rat_checked(const rat *r, const char *what)
{
    if (!rat_in_rule(r))
        refuse("width", NOWHERE, "%s needs a %d-bit numerator and a %d-bit "
               "denominator; version 1 allows %d bits each", what,
               cft_bn_bitlen(&r->n), cft_bn_bitlen(&r->d), WIDTH_BITS);
}

static void rat_mul(rat *r, const rat *a, const rat *b)
{
    rat t;
    t.neg = a->neg ^ b->neg;
    if (cft_bn_mul(&t.n, &a->n, &b->n) || cft_bn_mul(&t.d, &a->d, &b->d))
        internal("an exact product past the bigint", CFT_ERR_INTERNAL);
    rat_reduce(&t);
    *r = t;
}

static void rat_add(rat *r, const rat *a, const rat *b)
{
    cft_bn x, y;
    rat t;
    if (cft_bn_mul(&x, &a->n, &b->d) || cft_bn_mul(&y, &b->n, &a->d) ||
        cft_bn_mul(&t.d, &a->d, &b->d))
        internal("an exact sum past the bigint", CFT_ERR_INTERNAL);
    if (a->neg == b->neg) {
        if (cft_bn_add(&t.n, &x, &y))
            internal("an exact sum past the bigint", CFT_ERR_INTERNAL);
        t.neg = a->neg;
    } else if (cft_bn_cmp(&x, &y) >= 0) {
        cft_bn_sub(&t.n, &x, &y);
        t.neg = a->neg;
    } else {
        cft_bn_sub(&t.n, &y, &x);
        t.neg = b->neg;
    }
    rat_reduce(&t);
    *r = t;
}

static void rat_sub(rat *r, const rat *a, const rat *b)
{
    rat nb = *b;
    if (!cft_bn_is_zero(&nb.n))
        nb.neg = !nb.neg;
    rat_add(r, a, &nb);
}

static int rat_cmp(const rat *a, const rat *b)
{
    cft_bn x, y;
    int c;
    if (a->neg != b->neg)
        return a->neg ? -1 : 1;
    if (cft_bn_mul(&x, &a->n, &b->d) || cft_bn_mul(&y, &b->n, &a->d))
        internal("an exact comparison past the bigint", CFT_ERR_INTERNAL);
    c = cft_bn_cmp(&x, &y);
    return a->neg ? -c : c;
}

static int rat_eq(const rat *a, const rat *b)
{
    return a->neg == b->neg && cft_bn_cmp(&a->n, &b->n) == 0 &&
           cft_bn_cmp(&a->d, &b->d) == 0;
}

/* the page's one spelling: hex numerator (signed), '/', hex denominator */
static void rat_text(const rat *r, char *out)
{
    if (r->neg)
        *out++ = '-';
    bn_hex(&r->n, out);
    out += strlen(out);
    *out++ = '/';
    bn_hex(&r->d, out);
}

/* A finite element's exact value, in rule: 0, or 1 if it is not finite,
 * or 2 if it is past the rule. */
static int rat_of_elem(rat *r, const elem_t *x)
{
    long nb, db;
    if (x->kind == EL_INF || x->kind == EL_NAN)
        return 1;
    elem_bits(x, &nb, &db);
    if (nb > WIDTH_BITS || db > WIDTH_BITS)
        return 2;
    rat_zero(r);
    if (x->kind == EL_ZERO)
        return 0;
    r->neg = x->sign;
    if (x->e >= 0) {
        if (bn_shl(&r->n, &x->m, (int)x->e))
            internal("an element past the bigint", CFT_ERR_INTERNAL);
    } else {
        cft_bn one;
        cft_bn_copy(&r->n, &x->m);
        cft_bn_set_u32(&one, 1);
        if (bn_shl(&r->d, &one, (int)-x->e))
            internal("an element past the bigint", CFT_ERR_INTERNAL);
    }
    return 0;
}

static const char *KIND_WORD[4] = { "finite", "finite", "inf", "nan" };

/* cert._exact: an element's exact value under the width rule; a
 * non-finite one has none, refused by name. */
static void exact_of(rat *r, int f, const uint8_t *le, const char *what)
{
    elem_t x;
    int got;
    decode(f, le, &x);
    got = rat_of_elem(r, &x);
    if (got == 1)
        refuse("accuracy-finite", NOWHERE, "%s is %s%s; an exact value "
               "needs a finite element", what, x.kind == EL_INF && x.sign ?
               "-" : "", KIND_WORD[x.kind]);
    if (got == 2) {
        long nb, db;
        elem_bits(&x, &nb, &db);
        refuse("width", NOWHERE, "%s needs a %ld-bit numerator and a %ld-bit "
               "denominator; version 1 allows %d bits each", what, nb, db,
               WIDTH_BITS);
    }
}

/* q correctly rounded into format f under rnd (cert.round_rational):
 * one division leaves m and a sticky, as _round_rational's does, and
 * cft_from_hex_char rounds the dyadic value (2m + 1) 2^(q - 1) - or
 * m 2^q, exact - which is round_pack's answer for it. Zero is +0. */
static void rat_round(const rat *q, int f, int rnd, uint8_t *out)
{
    cft_bn m, rem, t;
    long w = PREC(f) + 3, qe;
    char hex[CFT_BN_BITS / 4 + 8], text[CFT_BN_BITS / 4 + 64];
    const char *in[1];
    size_t bad = 0;
    uint32_t fl = 0;
    cft_status st;
    if (cft_bn_is_zero(&q->n)) {
        memset(out, 0, ESZ(f));
        return;
    }
    qe = (long)(cft_bn_bitlen(&q->n) - cft_bn_bitlen(&q->d)) - w;
    if (qe >= 0) {
        if (bn_shl(&t, &q->d, (int)qe))
            internal("rounding past the bigint", CFT_ERR_INTERNAL);
        bn_divmod(&m, &rem, &q->n, &t);
    } else {
        if (bn_shl(&t, &q->n, (int)-qe))
            internal("rounding past the bigint", CFT_ERR_INTERNAL);
        bn_divmod(&m, &rem, &t, &q->d);
    }
    if (!cft_bn_is_zero(&rem)) {
        if (bn_shl(&m, &m, 1) || cft_bn_inc(&m))
            internal("rounding past the bigint", CFT_ERR_INTERNAL);
        qe -= 1;
    }
    bn_hex(&m, hex);
    snprintf(text, sizeof text, "%s0x%sp%ld", q->neg ? "-" : "", hex, qe);
    in[0] = text;
    st = cft_from_hex_char(host_dev(), (cft_format)f, RND_CODE[rnd], in, out,
                           1, &bad, &fl);
    if (st != CFT_OK)
        internal("cft_from_hex_char", st);
}
#endif /* AUDIT_EXACT */

/* ---- the certificate --------------------------------------------------- */

enum { K_MAIN, K_HALF, K_WIDER };
static const char *const KIND_NAME[3] = { "main", "half-step", "wider" };
enum { M_DRIFT, M_HALVING, M_WIDER };
static const char *const METHOD_NAME[3] = { "drift", "step-halving", "wider" };
static const char *const KINDS[3] = { "bound", "estimate", "measurement" };
static const int METHOD_KIND[3] = { 2, 1, 1 };   /* measurement, estimate */
enum { V_EXACT, V_ROUNDED, V_ENCLOSED };

typedef struct {
    const char *start, *end;        /* 64 hex, into the body */
    uint32_t flags, status;
} seg_t;

typedef struct {
    int kind, fmt;
    const char *image, *digest, *stream[3], *output;
    uint64_t lanes, steps, S;
    seg_t *chain;
    unsigned n_hslots, *hslots;
    int has_depth;
    uint32_t depth;                 /* its `scratch-depth` parameter */
} run_t;

#if AUDIT_EXACT
typedef struct {
    rat coef;
    unsigned n;
    unsigned slot[MAX_FACTORS];
} term_t;

typedef struct {
    int form, fmt, rnd;
    rat exact;
    uint8_t bits[32], lo[32], hi[32];
} value_t;

typedef struct {
    int method;
    uint64_t uses;
    int has_lane;
    uint64_t lane;
    unsigned n_terms;
    term_t *terms;
    value_t value;
} entry_t;
#endif

typedef struct {
    int keyed;
    const char *commitment;
    char *build_id;
    const char *backend, *xclbin, *version, *tiles;
    char *caps;                     /* one or two words joined, or a word */
    int n_caps;                     /* 0: none or unknown */
    const char *caps_words[2];
    uint64_t R, A;
    run_t *runs;
#if AUDIT_EXACT
    entry_t *entries;
#endif
} cert_t;

/* ---- the strict reader ------------------------------------------------- */

enum { KEY_CFT, KEY_MODE, KEY_SALTC, KEY_BUILD, KEY_BACKEND, KEY_XCLBIN,
       KEY_VERSION, KEY_CAPS, KEY_TILES, KEY_RUNS, KEY_RUN, KEY_PFORMAT,
       KEY_PIMAGE, KEY_PDIGEST, KEY_LANES, KEY_STEPS, KEY_SA, KEY_SB, KEY_SC,
       KEY_PARAMS, KEY_PARAM, KEY_SEGMENTS, KEY_SEGMENT, KEY_OUTPUT,
       KEY_ACCURACY, KEY_ENTRY, KEY_KIND, KEY_USES, KEY_SCOPE, KEY_QUANTITY,
       KEY_TERM, KEY_VALUE, KEY_END, KEY_HASH, N_KEYS };

static const char *const KEY[N_KEYS] = {
    "cft-certificate", "mode", "salt-commitment", "build-id", "backend",
    "device-xclbin", "device-version", "device-caps", "device-tiles", "runs",
    "run", "program-format", "program-image", "program-digest", "lanes",
    "steps", "stream-a", "stream-b", "stream-c", "parameters", "parameter",
    "segments", "segment", "output", "accuracy", "entry", "kind", "uses",
    "scope", "quantity", "term", "value", "end", "hash" };

/* the header 0, a run 1, the accuracy line 2, an entry 3, end 4, hash 5 */
static int block_type(int k)
{
    return k < KEY_RUN ? 0 : k < KEY_ACCURACY ? 1 : k == KEY_ACCURACY ? 2
         : k < KEY_END ? 3 : k == KEY_END ? 4 : 5;
}

static int is_starter(int k)
{
    return k == KEY_RUN || k == KEY_ACCURACY || k == KEY_ENTRY ||
           k == KEY_END;
}

static int is_repeating(int k)
{
    return k == KEY_RUN || k == KEY_ENTRY;
}

typedef struct {
    char **tok;
    size_t ntok;
    int key;                        /* its rank, or -1 for no key of v1 */
} line_t;

typedef struct {
    line_t *L;
    size_t n, pos;
    int block;
} rdr_t;

/* the 1-based number of the line at pos, and of the line just taken */
#define CUR(R)   ((long long)(R)->pos + 1)
#define PREV(R)  ((long long)(R)->pos)

static void malformed(long long line, const char *fmt, ...)
    NORETURN PRINTF_LIKE(2, 3);
static void malformed(long long line, const char *fmt, ...)
{
    char msg[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    refuse("malformed", AT_LINE(line), "line %lld: %s", line, msg);
}

/* The body's lines, each held to the byte rules in order, then split
 * into tokens in place (cert._split_lines). */
static void split_lines(char *body, size_t len, rdr_t *R)
{
    size_t i, s, ln, nl = 0, ntok = 0, t;
    char **tp;
    for (i = 0; i < len; i++)
        if (body[i] == '\n')
            nl++;
    R->L = (line_t *)xalloc(nl, sizeof *R->L);
    R->n = nl;
    for (i = 0, s = 0, ln = 0; i < len; i++) {
        size_t j;
        if (body[i] != '\n')
            continue;
        for (j = s; j < i; j++) {
            unsigned char c = (unsigned char)body[j];
            if (c < 0x20 || c > 0x7e)
                malformed((long long)ln + 1, "holds byte %#04x; a certificate "
                          "is printable ASCII and LF", (unsigned)c);
        }
        if (i == s)
            malformed((long long)ln + 1, "it is empty");
        if (body[s] == ' ' || body[i - 1] == ' ')
            malformed((long long)ln + 1, "tokens are separated by exactly one "
                      "space, with none at either end");
        for (j = s; j + 1 < i; j++)
            if (body[j] == ' ' && body[j + 1] == ' ')
                malformed((long long)ln + 1, "tokens are separated by exactly "
                          "one space, with none at either end");
        for (j = s; j < i; j++)
            if (body[j] == ' ')
                ntok++;
        ntok++;
        s = i + 1;
        ln++;
    }
    tp = (char **)xalloc(ntok, sizeof *tp);
    for (i = 0, s = 0, ln = 0, t = 0; i < len; i++) {
        size_t j;
        int k;
        if (body[i] != '\n')
            continue;
        R->L[ln].tok = tp + t;
        tp[t++] = body + s;
        R->L[ln].ntok = 1;
        for (j = s; j < i; j++)
            if (body[j] == ' ') {
                body[j] = 0;
                tp[t++] = body + j + 1;
                R->L[ln].ntok++;
            }
        body[i] = 0;
        R->L[ln].key = -1;
        for (k = 0; k < N_KEYS; k++)
            if (!strcmp(R->L[ln].tok[0], KEY[k]))
                R->L[ln].key = k;
        s = i + 1;
        ln++;
    }
}

static int in_block_rest(const rdr_t *R, int expected)
{
    size_t i;
    for (i = R->pos; i < R->n; i++) {
        int k = R->L[i].key;
        if (i > R->pos && is_starter(k))
            break;
        if (k == expected)
            return 1;
    }
    return 0;
}

/* "A line that is not the one expected" (cert._Reader.classify) */
static void classify(const rdr_t *R, int expected) NORETURN;
static void classify(const rdr_t *R, int expected)
{
    int k, t;
    if (R->pos >= R->n)
        refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is missing: "
               "the body ends first", CUR(R), KEY[expected]);
    k = R->L[R->pos].key;
    t = block_type(k);
    if (is_starter(k)) {
        if (t > R->block || (t == R->block && is_repeating(k)))
            refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is "
                   "missing: '%s' begins a later block here", CUR(R),
                   KEY[expected], KEY[k]);
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' has no "
               "place here: its block is already read, and '%s' belongs here",
               CUR(R), KEY[k], KEY[expected]);
    }
    if (t < R->block || (t == R->block && (is_starter(expected) ||
                                          k < expected)))
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' has no "
               "place here: its place is earlier, and '%s' belongs here",
               CUR(R), KEY[k], KEY[expected]);
    if (in_block_rest(R, expected))
        refuse("line-order", AT_LINE(CUR(R)), "line %lld: '%s' comes before "
               "'%s', which belongs first", CUR(R), KEY[k], KEY[expected]);
    refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is missing; '%s' "
           "is here instead", CUR(R), KEY[expected], KEY[k]);
}

static line_t *expect(rdr_t *R, int key, long ntok)
{
    line_t *l;
    if (R->pos >= R->n || R->L[R->pos].key != key)
        classify(R, key);
    l = &R->L[R->pos];
    if (ntok >= 0 && l->ntok != (size_t)ntok)
        malformed(CUR(R), "'%s' takes %ld value%s, not %lu", KEY[key],
                  ntok - 1, ntok != 2 ? "s" : "", (unsigned long)l->ntok - 1);
    R->pos++;
    return l;
}

/* `key <value>`, taken: its value. Call it in a statement of its own and
 * read PREV(R) after it, never beside it in one argument list. */
static const char *take(rdr_t *R, int key)
{
    return expect(R, key, 2)->tok[1];
}

/* a decimal in its one spelling, at most 2^63 - 1, in lo..hi */
static uint64_t rd_dec(const char *tok, const char *what, uint64_t lo,
                       uint64_t hi, long long line)
{
    uint64_t v;
    if (!dec_spelling(tok))
        malformed(line, "%s '%.80s' is not a decimal integer in its one "
                  "spelling (digits, no sign, no leading zero)", what, tok);
    if (!index_of(tok, &v))
        malformed(line, "%s %.40s%s is past 2^63 - 1", what, tok,
                  strlen(tok) > 40 ? "..." : "");
    if (v < lo || v > hi)
        malformed(line, "%s is %llu; it must be in %llu..%llu", what,
                  (unsigned long long)v, (unsigned long long)lo,
                  (unsigned long long)hi);
    return v;
}

static const char *rd_hex(const char *tok, size_t n, const char *what,
                          long long line)
{
    if (!hex_exact(tok, n))
        malformed(line, "%s '%.80s' is not %lu lowercase hex digits", what,
                  tok, (unsigned long)n);
    return tok;
}

static int rd_word(const char *tok, const char *const *words, int n,
                   const char *what, long long line)
{
    int i = word_index(tok, words, n);
    if (i < 0)
        malformed(line, "%s '%.80s' is not one of the words it takes", what,
                  tok);
    return i;
}

/* `key N`, then its N members, counted BEFORE they are read */
static uint64_t count_line(rdr_t *R, int key, int member, uint64_t minimum,
                           int consecutive, int stop1, int stop2)
{
    long long i = CUR(R);
    line_t *l = expect(R, key, 2);
    uint64_t n = rd_dec(l->tok[1], KEY[key], minimum, DEC_MAX, i), have = 0;
    size_t j;
    for (j = R->pos; j < R->n; j++) {
        int k = R->L[j].key;
        if (consecutive && k != member)
            break;
        if (k == stop1 || k == stop2)
            break;
        if (k == member)
            have++;
    }
    if (have != n)
        refuse("count", AT_LINE(i), "line %lld: '%s' says %llu and %llu '%s' "
               "line%s follow", i, KEY[key], (unsigned long long)n,
               (unsigned long long)have, KEY[member], have != 1 ? "s" : "");
    return n;
}

/* the group member here must carry index `want` */
static void member_index(rdr_t *R, int key, uint64_t want, int stop1,
                         int stop2, int consecutive)
{
    line_t *l;
    uint64_t got, v;
    size_t j;
    if (R->pos >= R->n || R->L[R->pos].key != key)
        classify(R, key);
    l = &R->L[R->pos];
    if (l->ntok < 2 || !index_of(l->tok[1], &got))
        malformed(CUR(R), "'%s' needs its index first: a decimal integer in "
                  "its one spelling, at most 2^63 - 1", KEY[key]);
    if (got == want)
        return;
    if (got < want)
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s %llu' "
               "again, where '%s %llu' belongs", CUR(R), KEY[key],
               (unsigned long long)got, KEY[key], (unsigned long long)want);
    for (j = R->pos + 1; j < R->n; j++) {
        int k = R->L[j].key;
        if ((consecutive && k != key) || k == stop1 || k == stop2)
            break;
        if (k == key && R->L[j].ntok > 1 && index_of(R->L[j].tok[1], &v) &&
            v == want)
            refuse("line-order", AT_LINE(CUR(R)), "line %lld: '%s %llu' "
                   "comes before '%s %llu', which belongs first", CUR(R),
                   KEY[key], (unsigned long long)got, KEY[key],
                   (unsigned long long)want);
    }
    refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s %llu' is "
           "missing; '%s %llu' is here instead", CUR(R), KEY[key],
           (unsigned long long)want, KEY[key], (unsigned long long)got);
}

static char *joined(char **tok, size_t n)
{
    size_t i, len = 0;
    char *s;
    for (i = 0; i < n; i++)
        len += strlen(tok[i]) + 1;
    s = (char *)xalloc(len + 1, 1);
    for (i = 0; i < n; i++) {
        if (i)
            strcat(s, " ");
        strcat(s, tok[i]);
    }
    return s;
}

/* one identity line: a word it allows, hex digits, or a decimal >= 1 */
static const char *identity_one(rdr_t *R, int key, const char *const *words,
                                int nw, size_t hexn, int dec)
{
    line_t *l = expect(R, key, 2);
    const char *v = l->tok[1];
    if (word_index(v, words, nw) >= 0)
        return v;
    if (hexn && hex_exact(v, hexn))
        return v;
    if (dec && dec_spelling(v)) {
        rd_dec(v, KEY[key], 1, DEC_MAX, PREV(R));
        return v;
    }
    malformed(PREV(R), "'%s' '%.80s' is not %s%s%s", KEY[key], v,
              hexn ? "the hex digits it takes" : "", dec ? "a decimal integer"
              : "", " or a word it allows");
}

static int build_commit_ok(const char *s)
{
    size_t n;
    if (strncmp(s, "commit=", 7) != 0)
        return 0;
    n = strlen(s + 7);
    return (n == 40 || n == 64) && hex_exact(s + 7, n);
}

static void read_identity(rdr_t *R, cert_t *C)
{
    static const char *const BACKENDS[4] = { "software", "xrt", "remote",
                                             "unknown" };
    static const char *const NONE_UNKNOWN[2] = { "none", "unknown" };
    static const char *const UNKNOWN[1] = { "unknown" };
    line_t *l = expect(R, KEY_BUILD, -1);
    if (l->ntok == 2 && !strcmp(l->tok[1], "unknown"))
        C->build_id = joined(l->tok + 1, 1);
    else if (l->ntok == 4 && build_commit_ok(l->tok[1]) &&
             (!strcmp(l->tok[2], "tracked=clean") ||
              !strcmp(l->tok[2], "tracked=modified")) &&
             (!strcmp(l->tok[3], "untracked=none") ||
              !strcmp(l->tok[3], "untracked=present")))
        C->build_id = joined(l->tok + 1, 3);
    else
        malformed(PREV(R), "'build-id' is cft_build_id()'s string verbatim: "
                  "'commit=<40 or 64 lowercase hex> tracked=<clean|modified> "
                  "untracked=<none|present>', or 'unknown'");
    C->backend = identity_one(R, KEY_BACKEND, BACKENDS, 4, 0, 0);
    C->xclbin = identity_one(R, KEY_XCLBIN, NONE_UNKNOWN, 2, 64, 0);
    C->version = identity_one(R, KEY_VERSION, NONE_UNKNOWN, 2, 8, 0);
    l = expect(R, KEY_CAPS, -1);
    if (l->ntok == 2 && (!strcmp(l->tok[1], "none") ||
                         !strcmp(l->tok[1], "unknown"))) {
        C->n_caps = 0;
    } else if ((l->ntok == 2 || l->ntok == 3) && hex_exact(l->tok[1], 8) &&
               (l->ntok == 2 || hex_exact(l->tok[2], 8))) {
        C->n_caps = (int)l->ntok - 1;
        C->caps_words[0] = l->tok[1];
        C->caps_words[1] = l->ntok == 3 ? l->tok[2] : NULL;
    } else {
        malformed(PREV(R), "'device-caps' is the raw words cft_get_image_id "
                  "gives - CAPS alone, or CAPS then CAPS2, each 8 lowercase "
                  "hex digits - or 'none' or 'unknown'");
    }
    C->caps = joined(l->tok + 1, l->ntok - 1);
    C->tiles = identity_one(R, KEY_TILES, UNKNOWN, 1, 0, 1);
}

static void read_run(rdr_t *R, cert_t *C, uint64_t i)
{
    static const char *const LADDER[4] = { "fp32", "fp64", "fp128", "fp256" };
    run_t *run = &C->runs[i];
    line_t *l;
    long long ln;
    uint64_t P, k;
    const char *prev_name = NULL, *v;
    size_t j;

    member_index(R, KEY_RUN, i, KEY_ACCURACY, KEY_END, 0);
    l = expect(R, KEY_RUN, -1);
    R->block = 1;
    ln = PREV(R);
    if (l->ntok < 3)
        malformed(ln, "'run' is 'run <index> main', 'run <index> half-step "
                  "h-slots <n> ...' or 'run <index> wider'");
    if (!strcmp(l->tok[2], "main")) {
        if (i != 0 || l->ntok != 3)
            malformed(ln, "run 0, and only run 0, is 'run 0 main'");
        run->kind = K_MAIN;
    } else if (!strcmp(l->tok[2], "wider")) {
        if (i == 0 || l->ntok != 3)
            malformed(ln, "'run <index> wider' is an auxiliary run, never "
                      "run 0, and takes nothing more");
        run->kind = K_WIDER;
    } else if (!strcmp(l->tok[2], "half-step")) {
        uint64_t n, have;
        if (i == 0)
            malformed(ln, "run 0 is the main run; a half-step run is "
                      "auxiliary");
        if (l->ntok < 5 || strcmp(l->tok[3], "h-slots") != 0)
            malformed(ln, "'run <index> half-step h-slots <n> <slot> ...'");
        n = rd_dec(l->tok[4], "the h-slot count", 1, MAX_HSLOTS, ln);
        have = l->ntok - 5;
        if (have != n)
            refuse("count", AT_LINE(ln), "line %lld: 'h-slots %llu' and %llu "
                   "slot index%s follow", ln, (unsigned long long)n,
                   (unsigned long long)have, have != 1 ? "es" : "");
        run->hslots = (unsigned *)xalloc((size_t)n, sizeof *run->hslots);
        for (j = 0; j < n; j++)
            run->hslots[j] = (unsigned)rd_dec(l->tok[5 + j], "an h-slot", 0,
                                              MAX_HSLOTS - 1, ln);
        for (j = 1; j < n; j++)
            if (run->hslots[j] <= run->hslots[j - 1])
                malformed(ln, "h-slot indices are strictly increasing");
        run->n_hslots = (unsigned)n;
        run->kind = K_HALF;
    } else {
        malformed(ln, "run kind '%.40s' is not main, half-step or wider",
                  l->tok[2]);
    }
    /* each line taken, THEN read at its number: an argument list's order
     * of evaluation is unspecified, and PREV(R) beside expect() read the
     * line before it (found by the gate: 27 lines off by one) */
    v = take(R, KEY_PFORMAT);
    run->fmt = rd_word(v, LADDER, 4, "the program format", PREV(R));
    /* a format this build's library does not carry (CFT_MAX_FORMAT):
     * refused by the build's name, here, where the format is read, and
     * never later as an image that does not load - which would name an
     * input as not the one certified when the cause is the build */
    if (run->fmt > CFT_MAX_FORMAT)
        refuse("build-format", AT_LINE(PREV(R)), "line %lld: run %llu is "
               "%s, and this build's library carries formats up to %s "
               "(CFT_MAX_FORMAT=%d); it refuses rather than audit it "
               "differently", PREV(R), (unsigned long long)i,
               FMT[run->fmt].name, FMT[CFT_MAX_FORMAT].name, CFT_MAX_FORMAT);
    v = take(R, KEY_PIMAGE);
    run->image = rd_hex(v, 64, "the image digest", PREV(R));
    v = take(R, KEY_PDIGEST);
    run->digest = rd_hex(v, 64, "the program digest", PREV(R));
    v = take(R, KEY_LANES);
    run->lanes = rd_dec(v, "lanes", 1, DEC_MAX, PREV(R));
    v = take(R, KEY_STEPS);
    run->steps = rd_dec(v, "steps", 1, DEC_MAX, PREV(R));
    v = take(R, KEY_SA);
    run->stream[0] = rd_hex(v, 64, "stream a's hash", PREV(R));
    v = take(R, KEY_SB);
    run->stream[1] = rd_hex(v, 64, "stream b's hash", PREV(R));
    v = take(R, KEY_SC);
    run->stream[2] = rd_hex(v, 64, "stream c's hash", PREV(R));
    P = count_line(R, KEY_PARAMS, KEY_PARAM, 0, 1, -1, -1);
    for (k = 0; k < P; k++) {
        int c;
        uint64_t pv;
        l = expect(R, KEY_PARAM, 3);
        ln = PREV(R);
        if (!name_ok(l->tok[1]))
            malformed(ln, "parameter name '%.80s' is not [a-z][a-z0-9-]*, at "
                      "most 64", l->tok[1]);
        if (prev_name && (c = strcmp(l->tok[1], prev_name)) <= 0) {
            if (c == 0)
                refuse("line-unexpected", AT_LINE(ln), "line %lld: parameter "
                       "'%s' again", ln, l->tok[1]);
            refuse("line-order", AT_LINE(ln), "line %lld: parameter '%s' "
                   "comes after '%s'; names are in increasing order", ln,
                   l->tok[1], prev_name);
        }
        pv = rd_dec(l->tok[2], "a parameter", 0, DEC_MAX, ln);
        /* "The chain": a run's stated scratch depth, a power of two in
         * 1..32,768 (the lead's decision, 2026-09-29, from P2's option P) */
        if (!strcmp(l->tok[1], "scratch-depth")) {
            if (pv < 1 || pv > 32768 || (pv & (pv - 1)))
                malformed(ln, "scratch-depth %llu is not a power of two in "
                          "1..32,768, a depth a device can have",
                          (unsigned long long)pv);
            run->has_depth = 1;
            run->depth = (uint32_t)pv;
        }
        prev_name = l->tok[1];
    }
    run->S = count_line(R, KEY_SEGMENTS, KEY_SEGMENT, 1, 1, -1, -1);
    run->chain = (seg_t *)xalloc((size_t)run->S, sizeof *run->chain);
    for (k = 0; k < run->S; k++) {
        seg_t *s = &run->chain[k];
        member_index(R, KEY_SEGMENT, k, -1, -1, 1);
        l = expect(R, KEY_SEGMENT, 10);
        ln = PREV(R);
        if (strcmp(l->tok[2], "start") || strcmp(l->tok[4], "end") ||
            strcmp(l->tok[6], "flags") || strcmp(l->tok[8], "status"))
            malformed(ln, "'segment <k> start <hash> end <hash> flags <n> "
                      "status <n>'");
        s->start = rd_hex(l->tok[3], 64, "a start hash", ln);
        s->end = rd_hex(l->tok[5], 64, "an end hash", ln);
        s->flags = (uint32_t)rd_dec(l->tok[7], "flags", 0, 31, ln);
        s->status = (uint32_t)rd_dec(l->tok[9], "status", 0, 0xFFFFFFFFu, ln);
    }
    v = take(R, KEY_OUTPUT);
    run->output = rd_hex(v, 64, "the output hash", PREV(R));
}

#if AUDIT_EXACT
/* a rational in its one spelling, in lowest terms, under the width rule
 * (cert._Reader.rational) */
static void read_rational(const char *tok, rat *q, const char *what,
                          long long line)
{
    const char *p = tok, *num, *slash, *den;
    size_t nl, dl, i;
    int neg = 0, ok = 1;
    long nbits, dbits;
    if (*p == '-') {
        neg = 1;
        p++;
    }
    num = p;
    slash = strchr(p, '/');
    if (!slash) {
        ok = 0;
    } else {
        nl = (size_t)(slash - num);
        den = slash + 1;
        dl = strlen(den);
        if (nl == 0 || dl == 0)
            ok = 0;
        for (i = 0; ok && i < nl; i++)
            ok = is_hexl(num[i]);
        for (i = 0; ok && i < dl; i++)
            ok = is_hexl(den[i]);
        if (ok && num[0] == '0' && (nl > 1 || neg))
            ok = 0;             /* 0 alone, unsigned; else no leading zero */
        if (ok && den[0] == '0')
            ok = 0;
    }
    if (!ok) {
        /* the golden's two reasons: a zero denominator, or the spelling */
        const char *s = tok;
        int zero_den = 0;
        if (*s == '-')
            s++;
        if (*s && *s != '/') {
            const char *t = s;
            while (*t && is_hexl(*t))
                t++;
            if (*t == '/' && t[1]) {
                const char *u = t + 1;
                while (*u == '0')
                    u++;
                zero_den = *u == 0;
            }
        }
        malformed(line, "%s '%.80s': %s", what, tok, zero_den ?
                  "a zero denominator" : "not hex numerator/denominator in "
                  "their one spelling (lowercase, no leading zeros, the sign "
                  "on the numerator, no '+')");
    }
    nl = (size_t)(slash - num);
    den = slash + 1;
    dl = strlen(den);
    /* the width rule by the digits alone, FIRST - before zero's spelling
     * and before any gcd (P3's design, approved 2026-09-29) - so that no
     * token past 1,023 bits is ever held, here or in the golden reader */
    nbits = num[0] == '0' ? 0 : (long)(4 * (nl - 1)) +
            (hexval(num[0]) >= 8 ? 4 : hexval(num[0]) >= 4 ? 3 :
             hexval(num[0]) >= 2 ? 2 : 1);
    dbits = (long)(4 * (dl - 1)) + (hexval(den[0]) >= 8 ? 4 :
             hexval(den[0]) >= 4 ? 3 : hexval(den[0]) >= 2 ? 2 : 1);
    if (nbits > WIDTH_BITS || dbits > WIDTH_BITS)
        refuse("width", AT_LINE(line), "line %lld: %s needs a %ld-bit "
               "numerator and a %ld-bit denominator; version 1 allows %d bits "
               "each", line, what, nbits, dbits, WIDTH_BITS);
    if (num[0] == '0' && !(dl == 1 && den[0] == '1'))
        malformed(line, "%s '%.80s': zero is spelled 0/1", what, tok);
    q->neg = neg;
    bn_from_hex(&q->n, num, nl);
    bn_from_hex(&q->d, den, dl);
    {
        cft_bn g;
        bn_gcd(&g, &q->n, &q->d);
        if (!bn_is_one(&g))
            malformed(line, "%s '%.80s' is not in lowest terms", what, tok);
    }
}

/* an element: its hex, then that it is not a NaN, then its decimal */
static void read_element(int f, const char *htok, const char *dtok,
                         const char *what, uint8_t *le, long long line)
{
    elem_t x;
    if (!hex_exact(htok, ESZ(f) * 2))
        malformed(line, "%s '%.80s' is not %lu lowercase hex digits (an %s "
                  "element's bits)", what, htok, (unsigned long)ESZ(f) * 2,
                  FMT[f].name);
    elem_from_hex(f, htok, le);
    decode(f, le, &x);
    if (x.kind == EL_NAN)
        malformed(line, "%s is a NaN, and an accuracy value is a number",
                  what);
    if (!decimal_is(f, le, dtok))
        refuse("decimal", AT_LINE(line), "line %lld: %s: the decimal '%.60s' "
               "is not the exact decimal of %s", line, what, dtok, htok);
}

/* an element's order key: -inf 0, finite 1, +inf 2 (NaNs never reach) */
static int order_kind(int f, const uint8_t *le)
{
    elem_t x;
    decode(f, le, &x);
    if (x.kind == EL_INF)
        return x.sign ? 0 : 2;
    return 1;
}

static void read_value(rdr_t *R, value_t *v)
{
    static const char *const LADDER[4] = { "fp32", "fp64", "fp128", "fp256" };
    line_t *l = expect(R, KEY_VALUE, -1);
    long long ln = PREV(R);
    const char *form = l->ntok > 1 ? l->tok[1] : "";
    if (!strcmp(form, "exact") && l->ntok == 3) {
        v->form = V_EXACT;
        read_rational(l->tok[2], &v->exact, "the value", ln);
        return;
    }
    if (!strcmp(form, "rounded") && l->ntok == 6) {
        v->form = V_ROUNDED;
        v->fmt = rd_word(l->tok[2], LADDER, 4, "the value's format", ln);
        v->rnd = rd_word(l->tok[3], RND_NAME, 5, "the rounding direction", ln);
        read_element(v->fmt, l->tok[4], l->tok[5], "the value", v->bits, ln);
        return;
    }
    if (!strcmp(form, "enclosed") && l->ntok == 7) {
        int e;
        rat a, b;
        v->form = V_ENCLOSED;
        v->fmt = rd_word(l->tok[2], LADDER, 4, "the value's format", ln);
        read_element(v->fmt, l->tok[3], l->tok[4], "the lower end", v->lo, ln);
        read_element(v->fmt, l->tok[5], l->tok[6], "the upper end", v->hi, ln);
        for (e = 0; e < 2; e++) {
            elem_t x;
            long nb, db;
            decode(v->fmt, e ? v->hi : v->lo, &x);
            if (x.kind != EL_ZERO && x.kind != EL_FINITE)
                continue;
            elem_bits(&x, &nb, &db);
            if (nb > WIDTH_BITS || db > WIDTH_BITS)
                refuse("width", AT_LINE(ln), "the %s end's exact value needs "
                       "a %ld-bit numerator and a %ld-bit denominator; "
                       "version 1 allows %d bits each", e ? "upper" : "lower",
                       nb, db, WIDTH_BITS);
        }
        {
            int kl = order_kind(v->fmt, v->lo), kh = order_kind(v->fmt, v->hi);
            int above = kl > kh;
            if (kl == 1 && kh == 1) {
                elem_t x;
                decode(v->fmt, v->lo, &x);
                rat_of_elem(&a, &x);
                decode(v->fmt, v->hi, &x);
                rat_of_elem(&b, &x);
                above = rat_cmp(&a, &b) > 0;
            }
            if (above)
                malformed(ln, "an enclosure's lower end is above its upper "
                          "end");
        }
        return;
    }
    malformed(ln, "'value exact <rational>', 'value rounded <fmt> <rnd> <hex> "
              "<decimal>' or 'value enclosed <fmt> <hex> <decimal> <hex> "
              "<decimal>'");
}

static void read_entry(rdr_t *R, cert_t *C, uint64_t j)
{
    entry_t *E = &C->entries[j];
    line_t *l;
    int kind;
    long long ln;
    const char *v;

    member_index(R, KEY_ENTRY, j, KEY_END, -1, 0);
    l = expect(R, KEY_ENTRY, 3);
    R->block = 3;
    E->method = rd_word(l->tok[2], METHOD_NAME, 3, "the method", PREV(R));
    v = take(R, KEY_KIND);
    kind = rd_word(v, KINDS, 3, "the kind", PREV(R));
    if (kind != METHOD_KIND[E->method])
        refuse("accuracy-kind", AT_LINE(PREV(R)), "line %lld: entry %llu: the "
               "kind of %s is %s, not %s%s", PREV(R), (unsigned long long)j,
               METHOD_NAME[E->method], KINDS[METHOD_KIND[E->method]],
               KINDS[kind], kind == 0 ? "; a bound needs a rigorous "
               "remainder, and no version-1 method has one" : "");
    v = take(R, KEY_USES);
    E->uses = rd_dec(v, "the run used", 0, DEC_MAX, PREV(R));
    l = expect(R, KEY_SCOPE, -1);
    if (l->ntok == 2 && !strcmp(l->tok[1], "max-lanes")) {
        E->has_lane = 0;
    } else if (l->ntok == 3 && !strcmp(l->tok[1], "lane")) {
        E->has_lane = 1;
        E->lane = rd_dec(l->tok[2], "the lane", 0, DEC_MAX, PREV(R));
    } else {
        malformed(PREV(R), "'scope lane <i>' or 'scope max-lanes'");
    }
    if (E->method == M_DRIFT) {
        uint64_t t, have = 0, q;
        size_t p;
        ln = CUR(R);
        l = expect(R, KEY_QUANTITY, -1);
        if (l->ntok != 4 || strcmp(l->tok[2], "terms") != 0)
            malformed(ln, "'quantity <label> terms <n>'");
        if (!name_ok(l->tok[1]))
            malformed(ln, "label '%.80s' is not [a-z][a-z0-9-]*, at most 64",
                      l->tok[1]);
        t = rd_dec(l->tok[3], "the term count", 1, MAX_TERMS, ln);
        for (p = R->pos; p < R->n && R->L[p].key == KEY_TERM; p++)
            have++;
        if (have != t)
            refuse("count", AT_LINE(ln), "line %lld: 'terms %llu' and %llu "
                   "'term' line%s follow", ln, (unsigned long long)t,
                   (unsigned long long)have, have != 1 ? "s" : "");
        E->terms = (term_t *)xalloc((size_t)t, sizeof *E->terms);
        E->n_terms = (unsigned)t;
        for (q = 0; q < t; q++) {
            term_t *T = &E->terms[q];
            size_t f;
            l = expect(R, KEY_TERM, -1);
            ln = PREV(R);
            if (l->ntok < 2)
                malformed(ln, "'term <coefficient> [s<slot> ...]'");
            read_rational(l->tok[1], &T->coef, "a coefficient", ln);
            for (f = 2; f < l->ntok; f++) {
                const char *s = l->tok[f];
                uint64_t slot;
                if (s[0] != 's' || !dec_spelling(s + 1))
                    malformed(ln, "factor '%.40s' is not s<slot>", s);
                slot = rd_dec(s + 1, "a slot", 0, MAX_SLOT, ln);
                if (T->n < MAX_FACTORS)
                    T->slot[T->n] = (unsigned)slot;
                T->n++;
            }
            if (T->n > MAX_FACTORS)
                malformed(ln, "a term has at most %d factors", MAX_FACTORS);
            for (f = 1; f < T->n; f++)
                if (T->slot[f] < T->slot[f - 1])
                    malformed(ln, "a term's factors are in non-decreasing "
                              "slot order");
        }
    }
    read_value(R, &E->value);
}
#endif /* AUDIT_EXACT */

/* the whole reader (cert._Reader.certificate) */
static void read_certificate(rdr_t *R, cert_t *C)
{
    line_t *first, *l;
    size_t i;
    uint64_t r;
    long long sc_at = NONE;
    const char *mode;

    if (R->n == 0)
        refuse("magic", AT_LINE(1), "the body is empty; its first line must "
               "be 'cft-certificate 1'");
    first = &R->L[0];
    if (strcmp(first->tok[0], "cft-certificate") != 0)
        refuse("magic", AT_LINE(1), "line 1 is '%.80s'; a certificate begins "
               "'cft-certificate 1'", first->tok[0]);
    if (!(first->ntok == 2 && !strcmp(first->tok[1], "1"))) {
        if (first->ntok == 2 && dec_spelling(first->tok[1]))
            refuse("version", AT_LINE(1), "this is 'cft-certificate %.40s%s', "
                   "and this reader speaks version 1 only", first->tok[1],
                   strlen(first->tok[1]) > 40 ? "..." : "");
        malformed(1, "line 1 must be exactly 'cft-certificate 1'");
    }
    for (i = 0; i < R->n; i++)
        if (R->L[i].key < 0)
            refuse("unknown-line", AT_LINE(i + 1), "line %lld: '%.80s' is not "
                   "a line of version 1", (long long)i + 1, R->L[i].tok[0]);
    R->pos = 1;
    l = expect(R, KEY_MODE, 2);
    mode = l->tok[1];
    if (!strcmp(mode, "keyed"))
        C->keyed = 1;
    else if (!strcmp(mode, "open"))
        C->keyed = 0;
    else
        refuse("mode-unknown", AT_LINE(PREV(R)), "line %lld: mode '%.40s': "
               "this reader knows 'keyed' and 'open'", PREV(R), mode);
    for (i = 0; i < R->n; i++)
        if (R->L[i].key == KEY_SALTC) {
            sc_at = (long long)i + 1;
            break;
        }
    if (!C->keyed && sc_at != NONE)
        refuse("commitment-unexpected", AT_LINE(sc_at), "line %lld: an open "
               "certificate has no salt and so no salt commitment", sc_at);
    if (C->keyed && sc_at == NONE)
        refuse("commitment-missing", AT_LINE(CUR(R)), "line %lld: a keyed "
               "certificate commits to its salt on the line after its mode, "
               "and this one has no salt-commitment line", CUR(R));
    if (C->keyed) {
        const char *v = take(R, KEY_SALTC);
        C->commitment = rd_hex(v, 64, "the salt commitment", PREV(R));
    }
    read_identity(R, C);
    C->R = count_line(R, KEY_RUNS, KEY_RUN, 1, 0, KEY_ACCURACY, KEY_END);
    C->runs = (run_t *)xalloc((size_t)C->R, sizeof *C->runs);
    for (r = 0; r < C->R; r++)
        read_run(R, C, r);
    {
        long long acc_line = CUR(R);
        C->A = count_line(R, KEY_ACCURACY, KEY_ENTRY, 0, 0, KEY_END, -1);
        R->block = 2;
#if AUDIT_EXACT
        (void)acc_line;
        C->entries = (entry_t *)xalloc((size_t)C->A, sizeof *C->entries);
        for (r = 0; r < C->A; r++)
            read_entry(R, C, r);
#else
        if (C->A >= 1)
            refuse("build-width", AT_LINE(acc_line), "line %lld: this "
                   "certificate carries %llu accuracy entr%s, whose values "
                   "are exact, and this build's bigint is %d bits, narrower "
                   "than the %d an exact step needs; it refuses rather than "
                   "audit them differently", acc_line,
                   (unsigned long long)C->A, C->A == 1 ? "y" : "ies",
                   CFT_BN_LIMBS * 32, 2 * WIDTH_BITS + 1);
#endif
    }
    expect(R, KEY_END, 1);
    R->block = 4;
    if (R->pos != R->n)
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' after "
               "'end'; the body ends at 'end'", CUR(R),
               KEY[R->L[R->pos].key]);
}

/* Steps 1 and 2: the hash line, the body's hash, then the reader. */
static void read_all(uint8_t *data, size_t n, rdr_t *R, cert_t *C)
{
    size_t cut, i, last_len;
    const uint8_t *last;
    uint8_t d[32];
    char hex[65];
    int found = 0;

    if (n == 0 || data[n - 1] != '\n')
        refuse("hash-line", NOWHERE, "the file does not end with a newline, "
               "so its last line is not a hash line");
    cut = 0;
    for (i = n - 1; i-- > 0;)
        if (data[i] == '\n') {
            cut = i + 1;               /* the body is data[0 .. cut) */
            found = 1;
            break;
        }
    if (!found)
        cut = 0;
    last = data + cut;
    last_len = n - 1 - cut;
    if (last_len != 69 || memcmp(last, "hash ", 5) != 0)
        found = 0;
    else {
        found = 1;
        for (i = 5; i < 69; i++)
            if (!is_hexl((char)last[i]))
                found = 0;
    }
    if (!found)
        refuse("hash-line", NOWHERE, "the last line must be 'hash' and 64 "
               "lowercase hex digits");
    sha256_of(data, cut, d);
    hex_of(d, 32, hex);
    if (memcmp(hex, last + 5, 64) != 0)
        refuse("body-hash", NOWHERE, "the hash line is not the SHA-256 of the "
               "body: the bytes are not the ones it was written over");
    split_lines((char *)data, cut, R);
    read_certificate(R, C);
}

/* ---- the command line and what it hands the audit ---------------------- */

typedef struct {
    const char *key;               /* as written */
    int valid;                     /* a run index in its one spelling */
    uint64_t r;
    const char *image_path, *bank_path, *stream_path[3], *choose;
    uint8_t *image, *bank, *stream[3];
    size_t image_bytes, bank_bytes, stream_bytes[3];
} block_t;

typedef struct {
    uint64_t r, b;                 /* UINT64_MAX: past 2^63 - 1 */
    char *path;
    uint64_t size;                 /* its bytes, when it was listed */
} statefile_t;

static block_t *BLK = NULL;
static size_t N_BLK = 0;
static statefile_t *SF = NULL;
static size_t N_SF = 0;

static void usage_text(FILE *f)
{
    fputs(
"cft-audit - the audit of a version-1 certificate (docs/CERTIFICATES.md;\n"
"\"The audit tool\" is the manual)\n"
"\n"
"  cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]\n"
"            --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]\n"
"                    [--choose all|sample:K|K,K,...]\n"
"            [--run 1 --image IMG ...] ...\n"
"  cft-audit --read --cert CERT [--salt SALT]\n"
"  cft-audit --sample SEED R S K\n"
"\n"
"  --cert CERT       the certificate\n"
"  --salt SALT       a keyed certificate's salt, 32 bytes\n"
"  --states DIR      states: DIR/run-<r>-boundary-<b>.bin, as cft-segrun\n"
"                    writes them\n"
"  --seed HEX        the sampling seed, 64 hex digits; drawn if absent\n"
"  --run R           run R's block: its image, bank, streams and choice\n"
"  --image IMG       the run's program image\n"
"  --bank BANK       its bank, for an image that takes one\n"
"  --stream X FILE   stream X (a, b or c) of the run's lanes; +0 if absent\n"
"  --choose SPEC     all (the default), sample:K, or segments K,K,...\n"
"  --read            the strict reader alone (and the salt, with --salt)\n"
"  --sample          the segments a sample of K of S draws for run R\n"
"\n"
"Accepted: the verdict on stdout, exit 0. Refused: \"cft-audit: refused\n"
"<name>: <why>\" and its location on stderr; the exit code is the name's.\n",
          f);
}

static const char *need_arg(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        refuse("usage", NOWHERE, "%s needs a value", argv[*i]);
    return argv[++(*i)];
}

static void once(const char **slot, const char *opt, const char *v)
{
    if (*slot)
        refuse("usage", NOWHERE, "%s is given twice", opt);
    *slot = v;
}

/* the files a --states directory hands the audit */
static int parse_index_part(const char *s, size_t n, uint64_t *out)
{
    size_t i;
    uint64_t v = 0;
    int past = 0;
    if (n == 0 || (s[0] == '0' && n > 1))
        return 0;
    for (i = 0; i < n; i++) {
        if (s[i] < '0' || s[i] > '9')
            return 0;
        if (v > (DEC_MAX - 9) / 10)
            past = 1;
        else
            v = v * 10 + (uint64_t)(s[i] - '0');
    }
    *out = past || v > DEC_MAX ? UINT64_MAX : v;
    return 1;
}

static int loosely_boundary(const char *name)
{
    /* run-<digits>-boundary-<digits>.bin, whatever the digits' spelling */
    const char *p = name;
    if (strncmp(p, "run-", 4) != 0)
        return 0;
    p += 4;
    if (*p < '0' || *p > '9')
        return 0;
    while (*p >= '0' && *p <= '9')
        p++;
    if (strncmp(p, "-boundary-", 10) != 0)
        return 0;
    p += 10;
    if (*p < '0' || *p > '9')
        return 0;
    while (*p >= '0' && *p <= '9')
        p++;
    return strcmp(p, ".bin") == 0;
}

static void list_states(const char *dir)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    size_t cap = 0;
    if (!d)
        refuse("usage", NOWHERE, "--states %s cannot be read as a directory "
               "(%s)", dir, strerror(errno));
    while ((e = readdir(d)) != NULL) {
        const char *nm = e->d_name, *dash, *dot;
        uint64_t r, b;
        size_t plen;
        if (!loosely_boundary(nm))
            continue;
        dash = strstr(nm + 4, "-boundary-");
        dot = strrchr(nm, '.');
        if (!parse_index_part(nm + 4, (size_t)(dash - (nm + 4)), &r) ||
            !parse_index_part(dash + 10, (size_t)(dot - (dash + 10)), &b))
            refuse("usage", NOWHERE, "--states %s holds %s, which is named as a "
                   "boundary file but not in the one spelling of its indices "
                   "(decimal, no leading zero)", dir, nm);
        if (N_SF == cap) {
            statefile_t *g;
            cap = cap ? 2 * cap : 16;
            g = (statefile_t *)xalloc(cap, sizeof *g);
            if (N_SF)
                memcpy(g, SF, N_SF * sizeof *g);
            free(SF);
            SF = g;
        }
        plen = strlen(dir) + strlen(nm) + 2;
        SF[N_SF].path = (char *)xalloc(plen, 1);
        snprintf(SF[N_SF].path, plen, "%s/%s", dir, nm);
        SF[N_SF].r = r;
        SF[N_SF].b = b;
        {
            /* a state file is held to be one, and opened, before step 1,
             * so that one that cannot be read is `usage` before any step
             * (verifier-A1: a directory by a boundary's name was refused
             * only at step 7, after steps 1 to 6 had passed); its bytes
             * are read at step 7, where only a file changed or gone since
             * can fail */
            FILE *f;
#if defined(_WIN32)
            struct _stati64 sb;
            if (_stati64(SF[N_SF].path, &sb) != 0)
#else
            struct stat sb;
            if (stat(SF[N_SF].path, &sb) != 0)
#endif
                refuse("usage", NOWHERE, "%s cannot be read (%s)",
                       SF[N_SF].path, strerror(errno));
#if defined(_WIN32)
            if ((sb.st_mode & _S_IFMT) != _S_IFREG)
#else
            if (!S_ISREG(sb.st_mode))
#endif
                refuse("usage", NOWHERE, "%s is named as a boundary file and "
                       "is not a file", SF[N_SF].path);
            f = fopen(SF[N_SF].path, "rb");
            if (!f)
                refuse("usage", NOWHERE, "%s cannot be read (%s)",
                       SF[N_SF].path, strerror(errno));
            fclose(f);
            SF[N_SF].size = (uint64_t)sb.st_size;
        }
        N_SF++;
    }
    closedir(d);
}

static block_t *block_for(uint64_t r)
{
    size_t i;
    for (i = 0; i < N_BLK; i++)
        if (BLK[i].valid && BLK[i].r == r)
            return &BLK[i];
    return NULL;
}

/* ---- sampling ---------------------------------------------------------- */

typedef struct {
    uint8_t seed[SEED_BYTES];
    uint32_t run;
    uint64_t block;
    uint8_t words[32];
    int next;                      /* the next word of `words`, 0..4 */
} prng_t;

static void prng_init(prng_t *P, const uint8_t *seed, uint32_t run)
{
    memcpy(P->seed, seed, SEED_BYTES);
    P->run = run;
    P->block = 0;
    P->next = 4;
}

static uint64_t prng_word(prng_t *P)
{
    uint64_t w = 0;
    int i;
    if (P->next == 4) {
        uint8_t msg[TAG_SAMPLE_LEN + SEED_BYTES + 4 + 8];
        size_t o = 0;
        memcpy(msg, TAG_SAMPLE, TAG_SAMPLE_LEN);
        o += TAG_SAMPLE_LEN;
        memcpy(msg + o, P->seed, SEED_BYTES);
        o += SEED_BYTES;
        for (i = 3; i >= 0; i--)
            msg[o++] = (uint8_t)(P->run >> (8 * i));
        for (i = 7; i >= 0; i--)
            msg[o++] = (uint8_t)(P->block >> (8 * i));
        sha256_of(msg, o, P->words);
        P->block++;
        P->next = 0;
    }
    for (i = 0; i < 8; i++)
        w = (w << 8) | P->words[8 * P->next + i];
    P->next++;
    return w;
}

/* a uniform integer below m, by rejection */
static uint64_t prng_uniform(prng_t *P, uint64_t m)
{
    uint64_t rem = (0 - m) % m;    /* 2^64 mod m */
    for (;;) {
        uint64_t w = prng_word(P);
        if (rem == 0 || w < 0 - rem)
            return w % m;
    }
}

/* a sparse map for the shuffle: position -> value, absent is itself */
typedef struct { uint64_t *key, *val; uint8_t *used; size_t cap; } smap;

static size_t smap_slot(const smap *M, uint64_t k)
{
    size_t h = (size_t)((k * 0x9E3779B97F4A7C15ull) >> 17) & (M->cap - 1);
    while (M->used[h] && M->key[h] != k)
        h = (h + 1) & (M->cap - 1);
    return h;
}

static uint64_t smap_get(const smap *M, uint64_t k)
{
    size_t h = smap_slot(M, k);
    return M->used[h] ? M->val[h] : k;
}

static void smap_set(smap *M, uint64_t k, uint64_t v)
{
    size_t h = smap_slot(M, k);
    M->used[h] = 1;
    M->key[h] = k;
    M->val[h] = v;
}

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

/* cert.sample: a partial Fisher-Yates of 0..S-1, the first k, sorted */
static uint64_t *sample(const uint8_t *seed, uint32_t run, uint64_t S,
                        uint64_t k)
{
    prng_t P;
    smap M;
    uint64_t j, *out;
    /* 4k slots, sized without wrapping: at K = 2^62 the product 4k is 0
     * in 64 bits, and a map left at 16 slots probed forever once full
     * (verifier-A1). A k whose map this process cannot address is the
     * tool's own `memory`; an audit's k is at most its run's segments,
     * which its lines pay for, so only --sample can ask for one. */
    if (k > (uint64_t)((size_t)-1 / (4 * sizeof(uint64_t))))
        refuse("memory", NOWHERE, "a sample of %llu needs a map of 4 x "
               "%llu slots, more than this process can address",
               (unsigned long long)k, (unsigned long long)k);
    M.cap = 16;
    while (M.cap < 4 * (size_t)k)
        M.cap *= 2;
    M.key = (uint64_t *)xalloc(M.cap, sizeof *M.key);
    M.val = (uint64_t *)xalloc(M.cap, sizeof *M.val);
    M.used = (uint8_t *)xalloc(M.cap, 1);
    prng_init(&P, seed, run);
    for (j = 0; j < k; j++) {
        uint64_t r = j + prng_uniform(&P, S - j);
        uint64_t vj = smap_get(&M, j), vr = smap_get(&M, r);
        smap_set(&M, j, vr);
        smap_set(&M, r, vj);
    }
    out = (uint64_t *)xalloc((size_t)k, sizeof *out);
    for (j = 0; j < k; j++)
        out[j] = smap_get(&M, j);
    qsort(out, (size_t)k, sizeof *out, cmp_u64);
    free(M.key);
    free(M.val);
    free(M.used);
    return out;
}

static int seed_of_hex(const char *h, uint8_t *seed)
{
    size_t i;
    if (strlen(h) != 2 * SEED_BYTES)
        return 0;
    for (i = 0; i < 2 * SEED_BYTES; i++) {
        char c = h[i];
        if (c >= 'A' && c <= 'F')
            c = (char)(c - 'A' + 'a');
        if (!is_hexl(c))
            return 0;
    }
    for (i = 0; i < SEED_BYTES; i++) {
        char a = h[2 * i], b = h[2 * i + 1];
        a = (char)(a >= 'A' && a <= 'F' ? a - 'A' + 'a' : a);
        b = (char)(b >= 'A' && b <= 'F' ? b - 'A' + 'a' : b);
        seed[i] = (uint8_t)(hexval(a) << 4 | hexval(b));
    }
    return 1;
}

/* 32 bytes from the operating system, for a sample asked with no seed */
static void draw_seed(uint8_t *seed)
{
#if defined(_WIN32)
    size_t i;
    for (i = 0; i < SEED_BYTES; i += 4) {
        unsigned int v;
        if (rand_s(&v) != 0)
            refuse("usage", NOWHERE, "no seed was handed, and the operating "
                   "system gave none: hand one with --seed");
        memcpy(seed + i, &v, 4);
    }
#else
    FILE *f = fopen("/dev/urandom", "rb");
    if (!f || fread(seed, 1, SEED_BYTES, f) != SEED_BYTES)
        refuse("usage", NOWHERE, "no seed was handed, and the operating "
               "system gave none: hand one with --seed");
    fclose(f);
#endif
}

/* ---- the audit --------------------------------------------------------- */

typedef struct {
    int how;                       /* 0 all, 1 sample, 2 named */
    uint64_t n;                    /* how many re-run */
    uint64_t *segs;                /* sample or named: sorted; all: NULL */
    char seed_hex[65];
} plan_t;

typedef struct {
    cft_program *prog;
    int fmt;
    uint32_t depth, n_consts, flags, max_deposits, n_in, n_out;
    const uint8_t *image, *bank;   /* the bytes handed */
    size_t image_bytes, bank_bytes;
    int bank_ext;
    const uint8_t *stream[3];      /* the streams handed; NULL is +0 */
    int bounded;                   /* "What an audit spends" */
} prog_t;

/* A state the audit keeps: handed and needed later, or re-run into. */
typedef struct {
    uint64_t r, b;
    uint8_t *bytes;
    size_t n;
} kept_t;

static kept_t *KEPT = NULL;
static size_t N_KEPT = 0, CAP_KEPT = 0;

static const uint8_t *kept_state_n(uint64_t r, uint64_t b, size_t *n)
{
    size_t i;
    for (i = 0; i < N_KEPT; i++)
        if (KEPT[i].r == r && KEPT[i].b == b) {
            if (n)
                *n = KEPT[i].n;
            return KEPT[i].bytes;
        }
    return NULL;
}

static const uint8_t *kept_state(uint64_t r, uint64_t b)
{
    return kept_state_n(r, b, NULL);
}

static void keep_state(uint64_t r, uint64_t b, uint8_t *bytes, size_t n)
{
    if (kept_state(r, b)) {
        free(bytes);
        return;
    }
    if (N_KEPT == CAP_KEPT) {
        kept_t *g;
        CAP_KEPT = CAP_KEPT ? 2 * CAP_KEPT : 16;
        g = (kept_t *)xalloc(CAP_KEPT, sizeof *g);
        if (N_KEPT)
            memcpy(g, KEPT, N_KEPT * sizeof *g);
        free(KEPT);
        KEPT = g;
    }
    KEPT[N_KEPT].r = r;
    KEPT[N_KEPT].b = b;
    KEPT[N_KEPT].bytes = bytes;
    KEPT[N_KEPT].n = n;
    N_KEPT++;
}

static const char *boundary_hash(const run_t *run, uint64_t b)
{
    return b < run->S ? run->chain[b].start : run->output;
}

/* the depth run r is re-run at ("The chain") */
static uint32_t depth_of(const cert_t *C, const run_t *run)
{
    if (C->n_caps == 2) {
        uint32_t w = (uint32_t)strtoul(C->caps_words[1], NULL, 16);
        if (w & 0x10u)
            return 1u << (w & 0xFu);
    }
    if (run->has_depth)
        return run->depth;
    return 256;
}

static int in_sorted(const uint64_t *a, uint64_t n, uint64_t v)
{
    uint64_t lo = 0, hi = n;
    while (lo < hi) {
        uint64_t mid = lo + (hi - lo) / 2;
        if (a[mid] == v)
            return 1;
        if (a[mid] < v)
            lo = mid + 1;
        else
            hi = mid;
    }
    return 0;
}

static int chosen(const plan_t *p, uint64_t k)
{
    return p->how == 0 ? 1 : in_sorted(p->segs, p->n, k);
}

/* Step 2's second half: the auditor's own choice (cert._plan). */
static plan_t *make_plan(const cert_t *C, const char *seed_arg)
{
    plan_t *plan = (plan_t *)xalloc((size_t)C->R, sizeof *plan);
    uint8_t seed[SEED_BYTES];
    int have_seed = 0, drew = 0;
    uint64_t r;
    size_t i;

    if (seed_arg) {
        if (!seed_of_hex(seed_arg, seed))
            refuse("choice", NOWHERE, "a sampling seed is exactly %d bytes, "
                   "64 hex digits; '%.80s' is not", SEED_BYTES, seed_arg);
        have_seed = 1;
    }
    for (i = 0; i < N_BLK; i++)
        if (BLK[i].choose && (!BLK[i].valid || BLK[i].r >= C->R))
            refuse("choice", NOWHERE, "the choice names run '%.40s', and the "
                   "certificate's runs are 0..%llu", BLK[i].key,
                   (unsigned long long)C->R - 1);
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        block_t *B = block_for(r);
        const char *c = B && B->choose ? B->choose : "all";
        plan_t *p = &plan[r];
        uint64_t S = run->S;
        if (!strcmp(c, "all")) {
            p->how = 0;
            p->n = S;
        } else if (!strncmp(c, "sample:", 7)) {
            uint64_t k;
            if (!index_of(c + 7, &k) || k < 1 || k > S)
                refuse("choice", AT_RUN(r), "run %llu: a sample of '%.40s' "
                       "from %llu segments; a sample's size is an integer in "
                       "1..%llu", (unsigned long long)r, c + 7,
                       (unsigned long long)S, (unsigned long long)S);
            if (!have_seed && !drew) {
                draw_seed(seed);
                drew = 1;
            }
            p->how = 1;
            p->n = k;
            p->segs = sample(seed, (uint32_t)r, S, k);
            hex_of(seed, SEED_BYTES, p->seed_hex);
        } else {
            /* a list of segments, K,K,...: at least one, distinct, each
             * in 0..S-1 */
            size_t n = 1, j, len = strlen(c);
            const char *s = c;
            int bad = len == 0;
            for (j = 0; j < len; j++)
                if (c[j] == ',')
                    n++;
            p->segs = (uint64_t *)xalloc(n, sizeof *p->segs);
            for (j = 0; !bad && j < n; j++) {
                size_t tl = strcspn(s, ",");
                char tok[24];
                uint64_t k;
                if (tl == 0 || tl >= sizeof tok) {
                    bad = 1;
                    break;
                }
                memcpy(tok, s, tl);
                tok[tl] = 0;
                if (!index_of(tok, &k) || k >= S) {
                    bad = 1;
                    break;
                }
                p->segs[j] = k;
                s += tl + 1;
            }
            if (!bad) {
                qsort(p->segs, n, sizeof *p->segs, cmp_u64);
                for (j = 1; j < n; j++)
                    if (p->segs[j] == p->segs[j - 1])
                        bad = 1;
            }
            if (bad)
                refuse("choice", AT_RUN(r), "run %llu: segments '%.80s' are "
                       "not 'all', 'sample:K' or distinct indices in "
                       "0..%llu, at least one", (unsigned long long)r, c,
                       (unsigned long long)S - 1);
            p->how = 2;
            p->n = n;
        }
    }
    return plan;
}

/* Step 3 (cert.check_salt). */
static void check_salt(const cert_t *C, const uint8_t *salt, size_t n,
                       int handed)
{
    char hex[65];
    if (!C->keyed) {
        if (handed)
            refuse("salt-unexpected", NOWHERE, "this certificate is open: its "
                   "hashes are not keyed, and a salt handed to its audit "
                   "would be believed to mean something it does not");
        return;
    }
    if (!handed)
        refuse("salt-missing", NOWHERE, "this certificate is keyed: its state "
               "and stream hashes can be checked only with the owner's salt, "
               "and none was handed");
    if (n != SALT_BYTES)
        refuse("salt-length", NOWHERE, "a version-1 salt is exactly %d bytes; "
               "this one is %lu bytes", SALT_BYTES, (unsigned long)n);
    tagged_hash(salt, TAG_SALT, TAG_SALT_LEN, NULL, 0, hex);
    if (strcmp(hex, C->commitment) != 0)
        refuse("salt-commitment", NOWHERE, "HMAC(salt, 'cft-certificate 1 "
               "salt') is not the certificate's salt-commitment: this is not "
               "its salt");
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

/* Step 4 (cert._check_programs). */
static prog_t *check_programs(const cert_t *C)
{
    prog_t *P = (prog_t *)xalloc((size_t)C->R, sizeof *P);
    uint64_t r;
    size_t i;
    for (i = 0; i < N_BLK; i++)
        if ((BLK[i].image_path || BLK[i].bank_path) &&
            (!BLK[i].valid || BLK[i].r >= C->R))
            refuse("program-image", NOWHERE, "programs names run '%.40s', and "
                   "the certificate's runs are 0..%llu", BLK[i].key,
                   (unsigned long long)C->R - 1);
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        block_t *B = block_for(r);
        prog_t *p = &P[r];
        uint8_t d[32];
        char hex[65];
        cft_sha256_ctx hs;
        cft_program_info info;
        cft_status st;
        size_t esz;
        if (!B || !B->image_path)
            refuse("program-image", AT_RUN(r), "run %llu: no program image was "
                   "handed to the audit", (unsigned long long)r);
        p->image = B->image;
        p->image_bytes = B->image_bytes;
        p->bank = B->bank;
        p->bank_bytes = B->bank_path ? B->bank_bytes : 0;
        sha256_of(p->image, p->image_bytes, d);
        hex_of(d, 32, hex);
        if (strcmp(hex, run->image) != 0)
            refuse("image-digest", AT_RUN(r), "run %llu: the image handed is "
                   "not the one certified (its SHA-256 differs)",
                   (unsigned long long)r);
        cft_sha256_init(&hs);
        hash_push(&hs, p->image, p->image_bytes);
        if (p->bank_bytes)
            hash_push(&hs, p->bank, p->bank_bytes);
        cft_sha256_final(&hs, d);
        hex_of(d, 32, hex);
        if (strcmp(hex, run->digest) != 0)
            refuse("program-digest", AT_RUN(r), "run %llu: the image and bank "
                   "handed are not the ones certified (SHA-256 of image then "
                   "bank differs)", (unsigned long long)r);
        p->depth = depth_of(C, run);
        st = cft_program_load(dev_at(p->depth), p->image, p->image_bytes,
                              &p->prog);
        if (st != CFT_OK) {
            const char *why = cft_last_error();
            refuse("program-image", AT_RUN(r), "run %llu: the image does not "
                   "load at %lu scratch slots: %s%s%s", (unsigned long long)r,
                   (unsigned long)p->depth, cft_strerror(st),
                   why && *why ? " - " : "", why && *why ? why : "");
        }
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        st = cft_program_get_info(p->prog, &info);
        if (st != CFT_OK)
            internal("cft_program_get_info", st);
        p->fmt = (int)info.format;
        p->n_consts = info.n_consts;
        p->flags = info.flags;
        p->max_deposits = info.max_deposits;
        p->n_in = info.n_scratch_in;
        p->n_out = info.n_scratch_out;
        p->bank_ext = (info.flags & CFT_PROG_FLAG_BANK_EXT) != 0;
        if (p->fmt != run->fmt)
            refuse("program-format", AT_RUN(r), "run %llu: the image is %s and "
                   "the certificate says %s", (unsigned long long)r,
                   FMT[p->fmt].name, FMT[run->fmt].name);
        if (!(p->flags & CFT_PROG_FLAG_SCRATCH_IO))
            refuse("program-shape", AT_RUN(r), "run %llu: this program is not "
                   "a segment: it declares no scratch block (flags.SCRATCH_IO "
                   "clear)", (unsigned long long)r);
        if (p->n_in != p->n_out || p->n_in < 1)
            refuse("program-shape", AT_RUN(r), "run %llu: this program is not "
                   "a segment: its scratch block goes in as %lu and out as %lu "
                   "slots a lane; a segment's end state must be the next "
                   "one's start", (unsigned long long)r,
                   (unsigned long)p->n_in, (unsigned long)p->n_out);
        if (p->max_deposits)
            refuse("program-shape", AT_RUN(r), "run %llu: this program is not "
                   "a segment: it deposits (%lu slots a lane); version 1 "
                   "certifies the scratch state only, and a deposit would go "
                   "uncertified", (unsigned long long)r,
                   (unsigned long)p->max_deposits);
        esz = ESZ(p->fmt);
        if (!p->bank_ext) {
            if (p->bank_bytes)
                refuse("program-image", AT_RUN(r), "run %llu: this image "
                       "carries its own constants, so the bank must be empty",
                       (unsigned long long)r);
        } else if ((uint64_t)p->bank_bytes != (uint64_t)p->n_consts * esz) {
            refuse("program-image", AT_RUN(r), "run %llu: the bank is %lu "
                   "bytes; the image addresses %lu constants of %lu bytes",
                   (unsigned long long)r, (unsigned long)p->bank_bytes,
                   (unsigned long)p->n_consts, (unsigned long)esz);
        }
    }
    return P;
}

/* A run is BOUNDED when the audit was handed a stream of it, or a state
 * for one of its boundaries 0..S holding at least `lanes` elements - by
 * its bytes, at least lanes x width/8, compared by division ("What an
 * audit spends"; P3's rule, approved 2026-09-29). Nothing else bounds a
 * run: not another run's states, and not a boundary past S. */
static int run_bounded(const run_t *run, uint64_t r, const block_t *B,
                       size_t esz)
{
    size_t i;
    if (B && (B->stream_path[0] || B->stream_path[1] || B->stream_path[2]))
        return 1;
    for (i = 0; i < N_SF; i++)
        if (SF[i].r == r && SF[i].b <= run->S && SF[i].size / esz >= run->lanes)
            return 1;
    return 0;
}

/* Step 5 (cert._check_streams): each stream handed held by its length
 * first, before anything is built beside it; then, for a bounded run,
 * each of a, b and c - as handed, or +0 hashed where it lies - against
 * its certified hash. An unbounded run's +0 streams are neither built nor
 * checked: the steps that need what it lacks refuse it (step 7's
 * state-shape, step 8's or step 9's state-missing). */
static void check_streams(const cert_t *C, const uint8_t *salt, prog_t *P)
{
    uint64_t r;
    size_t i;
    int x;
    for (i = 0; i < N_BLK; i++)
        if ((BLK[i].stream_path[0] || BLK[i].stream_path[1] ||
             BLK[i].stream_path[2]) && (!BLK[i].valid || BLK[i].r >= C->R))
            refuse("stream", NOWHERE, "streams names run '%.40s', and the "
                   "certificate's runs are 0..%llu", BLK[i].key,
                   (unsigned long long)C->R - 1);
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        block_t *B = block_for(r);
        prog_t *p = &P[r];
        size_t esz = ESZ(p->fmt);
        for (x = 0; x < 3; x++)
            if (B && B->stream_path[x] && B->stream_bytes[x] % esz)
                refuse("stream", AT_RUN(r), "run %llu stream %c: %lu bytes is "
                       "not a whole number of %s elements (%lu bytes each)",
                       (unsigned long long)r, 'a' + x,
                       (unsigned long)B->stream_bytes[x], FMT[p->fmt].name,
                       (unsigned long)esz);
        for (x = 0; x < 3; x++)
            if (B && B->stream_path[x] &&
                (uint64_t)(B->stream_bytes[x] / esz) != run->lanes)
                refuse("stream", AT_RUN(r), "run %llu: stream %c holds %lu "
                       "values; the run has %llu lanes", (unsigned long long)r,
                       'a' + x, (unsigned long)(B->stream_bytes[x] / esz),
                       (unsigned long long)run->lanes);
        for (x = 0; x < 3; x++)
            p->stream[x] = B && B->stream_path[x] ? B->stream[x] : NULL;
        p->bounded = run_bounded(run, r, B, esz);
        if (!p->bounded)
            continue;
        for (x = 0; x < 3; x++) {
            char hex[65];
            /* bounded: lanes x esz is at most what was handed */
            tagged_hash(salt, TAG_STREAM[x], TAG_STREAM_LEN, p->stream[x],
                        (size_t)run->lanes * esz, hex);
            if (strcmp(hex, run->stream[x]) != 0)
                refuse("stream", AT_RUN(r), "run %llu: stream %c is not the "
                       "one certified", (unsigned long long)r, 'a' + x);
        }
    }
}

/* Step 6 (cert._check_continuity). */
static void check_continuity(const cert_t *C)
{
    uint64_t r, k;
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        for (k = 1; k < run->S; k++)
            if (strcmp(run->chain[k].start, run->chain[k - 1].end) != 0)
                refuse("continuity", AT_RS(r, k), "run %llu segment %llu "
                       "starts on a state that is not segment %llu's end",
                       (unsigned long long)r, (unsigned long long)k,
                       (unsigned long long)k - 1);
        if (strcmp(run->output, run->chain[run->S - 1].end) != 0)
            refuse("continuity", AT_RS(r, run->S - 1), "run %llu: the output "
                   "is not the last segment's end", (unsigned long long)r);
    }
}

static int cmp_sf(const void *a, const void *b)
{
    const statefile_t *x = (const statefile_t *)a, *y = (const statefile_t *)b;
    if (x->r != y->r)
        return x->r < y->r ? -1 : 1;
    return x->b < y->b ? -1 : x->b > y->b;
}

/* Which handed states the later steps read: run 0's initial state for a
 * wider run's relation, each chosen segment's start where the segment
 * before it is not re-run, and each accuracy entry's. */
static int needed(const cert_t *C, const plan_t *plan, uint64_t r, uint64_t b)
{
    uint64_t j;
    if (r == 0 && b == 0) {
        for (j = 1; j < C->R; j++)
            if (C->runs[j].kind == K_WIDER)
                return 1;
    }
    if (b < C->runs[r].S && chosen(&plan[r], b) &&
        (b == 0 || !chosen(&plan[r], b - 1)))
        return 1;
#if AUDIT_EXACT
    for (j = 0; j < C->A; j++) {
        const entry_t *E = &C->entries[j];
        if (E->uses >= C->R)
            continue;
        if (r == E->uses && (b == 0 || b == C->runs[r].S))
            return 1;
        if (E->method != M_DRIFT && r == 0 && b == C->runs[0].S)
            return 1;
    }
#endif
    return 0;
}

/* Step 7 (cert._check_states). */
static void check_states(const cert_t *C, const uint8_t *salt,
                         const prog_t *P, const plan_t *plan)
{
    size_t i, j;
    qsort(SF, N_SF, sizeof *SF, cmp_sf);
    for (i = 0; i < N_SF; i++)
        if (SF[i].r >= C->R)
            refuse("state-shape", NOWHERE, "states names run %s, and the "
                   "certificate's runs are 0..%llu", SF[i].r == UINT64_MAX ?
                   "past 2^63 - 1" : "that is not one of them",
                   (unsigned long long)C->R - 1);
    for (i = 0; i < N_SF; i = j) {
        uint64_t r = SF[i].r;
        const run_t *run = &C->runs[r];
        const prog_t *p = &P[r];
        size_t esz = ESZ(p->fmt);
        for (j = i; j < N_SF && SF[j].r == r; j++)
            if (SF[j].b > run->S)
                refuse("state-shape", AT_RUN(r), "run %llu has boundaries "
                       "0..%llu; a state was handed for another",
                       (unsigned long long)r, (unsigned long long)run->S);
        for (j = i; j < N_SF && SF[j].r == r; j++) {
            uint64_t b = SF[j].b, nvals;
            size_t n = 0;
            uint8_t *s = read_file(SF[j].path, &n);
            char hex[65];
            if (!s)
                refuse("usage", NOWHERE, "the state file %s was opened before "
                       "step 1 and cannot be read at step 7 (%s): it changed "
                       "or went since", SF[j].path, strerror(errno));
            if (n % esz)
                refuse("state-shape", AT_RS(r, b), "run %llu boundary %llu: "
                       "%lu bytes is not a whole number of %s elements (%lu "
                       "bytes each)", (unsigned long long)r,
                       (unsigned long long)b, (unsigned long)n,
                       FMT[p->fmt].name, (unsigned long)esz);
            nvals = (uint64_t)(n / esz);
            if (nvals % p->n_in || nvals / p->n_in != run->lanes)
                refuse("state-shape", AT_RS(r, b), "run %llu boundary %llu: "
                       "%llu values; the state is %llu lanes of %lu %s slots",
                       (unsigned long long)r, (unsigned long long)b,
                       (unsigned long long)nvals,
                       (unsigned long long)run->lanes,
                       (unsigned long)p->n_in, FMT[p->fmt].name);
            state_hash(salt, s, n, hex);
            if (strcmp(hex, boundary_hash(run, b)) != 0)
                refuse("state-hash", AT_RS(r, b), "run %llu boundary %llu: the "
                       "state handed is not the one certified",
                       (unsigned long long)r, (unsigned long long)b);
            if (needed(C, plan, r, b))
                keep_state(r, b, s, n);
            else
                free(s);
        }
    }
}

/* _wider_image: why pa is not p0 one format wider, or NULL */
static const char *wider_image(const prog_t *p0, const prog_t *pa)
{
    uint32_t n0 = le32(p0->image + 8), na = le32(pa->image + 8);
    size_t e0 = ESZ(p0->fmt), ea = ESZ(pa->fmt);
    size_t c0 = p0->bank_ext ? 0 : p0->n_consts, ca = pa->bank_ext ? 0
                                                                   : pa->n_consts;
    const uint8_t *i0 = p0->image + 32 + c0 * e0, *ia = pa->image + 32 + ca * ea;
    size_t k;
    if (n0 != na || memcmp(i0, ia, (size_t)n0 * 8) != 0)
        return "its instruction words differ";
    if (le32(p0->image + 16) != le32(pa->image + 16))
        return "its header's max_deposits differs";
    if (le32(p0->image + 24) != le32(pa->image + 24))
        return "its header's flags differs";
    if (le32(p0->image + 12) != le32(pa->image + 12))
        return "its header's n_consts differs";
    if (le32(p0->image + 28) != le32(pa->image + 28))
        return "its header's scratch_io_word differs";
    if (c0 != ca)
        return "its constants are not the main image's exactly widened";
    for (k = 0; k < c0; k++) {
        uint8_t w[32];
        widen(p0->fmt, p0->image + 32 + k * e0, w, 1);
        if (memcmp(w, pa->image + 32 + k * ea, ea) != 0)
            return "its constants are not the main image's exactly widened";
    }
    return NULL;
}

/* Step 8 (cert._check_relations). */
static void check_relations(const cert_t *C, const uint8_t *salt,
                            const prog_t *P)
{
    const run_t *main = &C->runs[0];
    const prog_t *P0 = &P[0];
    uint64_t r;
    for (r = 1; r < C->R; r++) {
        const run_t *A = &C->runs[r];
        const prog_t *PA = &P[r];
        int half = A->kind == K_HALF;
        const char *why;
        uint64_t want;
        size_t e0 = ESZ(P0->fmt), s;
        char w[16];
        snprintf(w, sizeof w, "%s", KIND_NAME[A->kind]);
        /* format */
        if (half && A->fmt != main->fmt)
            refuse("aux-format", AT_RUN(r), "run %llu (%s) is %s; a half-step "
                   "run is at the main run's %s", (unsigned long long)r, w,
                   FMT[A->fmt].name, FMT[main->fmt].name);
        if (!half) {
            if (main->fmt == 3)
                refuse("aux-format", AT_RUN(r), "run %llu (%s): the main run is "
                       "fp256, the top of the ladder - a program image is at "
                       "most fp256, so no wider run exists and a rounding "
                       "estimate by one is refused", (unsigned long long)r, w);
            if (A->fmt != main->fmt + 1)
                refuse("aux-format", AT_RUN(r), "run %llu (%s) is %s; one "
                       "format wider than %s is %s", (unsigned long long)r, w,
                       FMT[A->fmt].name, FMT[main->fmt].name,
                       FMT[main->fmt + 1].name);
        }
        /* lanes */
        if (A->lanes != main->lanes)
            refuse("aux-lanes", AT_RUN(r), "run %llu (%s) has %llu lanes and "
                   "the main run %llu", (unsigned long long)r, w,
                   (unsigned long long)A->lanes,
                   (unsigned long long)main->lanes);
        /* image */
        if (A->steps != main->steps)
            refuse("aux-image", AT_RUN(r), "run %llu (%s) states %llu steps a "
                   "segment and the main run %llu; the same instructions take "
                   "the same steps", (unsigned long long)r, w,
                   (unsigned long long)A->steps,
                   (unsigned long long)main->steps);
        if (half) {
            if (strcmp(A->image, main->image) != 0)
                refuse("aux-image", AT_RUN(r), "run %llu (%s): its image digest "
                       "is not the main run's - a half-step run is the same "
                       "image", (unsigned long long)r, w);
        } else if ((why = wider_image(P0, PA)) != NULL) {
            refuse("aux-image", AT_RUN(r), "run %llu (%s) is not the main image "
                   "one format wider: %s", (unsigned long long)r, w, why);
        }
        /* the same instructions on the same machine: an auxiliary run's
         * depth is the main run's (P3's design, approved 2026-09-29) */
        if (PA->depth != P0->depth)
            refuse("aux-image", AT_RUN(r), "run %llu (%s) is re-run at %lu "
                   "scratch slots and the main run at %lu; a run at another "
                   "depth is another machine", (unsigned long long)r, w,
                   (unsigned long)PA->depth, (unsigned long)P0->depth);
        /* segments */
        want = half ? 2 * main->S : main->S;
        if (A->S != want)
            refuse("aux-segments", AT_RUN(r), "run %llu (%s) has %llu segments; "
                   "a %s run has %s the main run's %llu", (unsigned long long)r,
                   w, (unsigned long long)A->S, w, half ? "twice" : "",
                   (unsigned long long)main->S);
        /* h-slots and the bank */
        if (half) {
            unsigned h;
            size_t nb0;
            if (!P0->bank_ext)
                refuse("aux-h-slots", AT_RUN(r), "run %llu (%s): the main "
                       "image carries its constants, so no bank slot can be "
                       "halved", (unsigned long long)r, w);
            nb0 = P0->bank_bytes / e0;
            for (h = 0; h < A->n_hslots; h++) {
                elem_t x;
                unsigned sl = A->hslots[h];
                if (sl >= nb0)
                    refuse("aux-h-slots", AT_RUN(r), "run %llu (%s): h-slot %u "
                           "is past the %lu-slot bank", (unsigned long long)r,
                           w, sl, (unsigned long)nb0);
                decode(P0->fmt, P0->bank + sl * e0, &x);
                if (x.kind != EL_FINITE)
                    refuse("aux-h-slots", AT_RUN(r), "run %llu (%s): h-slot %u "
                           "holds %s in the main bank, which halving leaves "
                           "unchanged or undefined", (unsigned long long)r, w,
                           sl, x.kind == EL_ZERO ? "zero" : x.kind == EL_NAN ?
                           "nan" : x.sign ? "-inf" : "inf");
            }
            for (s = 0, h = 0; s < nb0; s++) {
                int named = h < A->n_hslots && A->hslots[h] == s;
                if (named) {
                    h++;
                    if (!is_half(P0->fmt, PA->bank + s * e0, P0->bank + s * e0))
                        refuse("aux-bank", AT_RUN(r), "run %llu (%s): bank slot "
                               "%lu is not the main bank's exactly halved",
                               (unsigned long long)r, w, (unsigned long)s);
                } else if (memcmp(PA->bank + s * e0, P0->bank + s * e0, e0)) {
                    refuse("aux-bank", AT_RUN(r), "run %llu (%s): bank slot %lu "
                           "differs from the main bank's, and it is not a named "
                           "h-slot", (unsigned long long)r, w,
                           (unsigned long)s);
                }
            }
        } else if (P0->bank_ext) {
            size_t n = P0->bank_bytes / e0, ea = ESZ(PA->fmt);
            uint8_t *wb = (uint8_t *)xalloc(n ? n : 1, ea);
            widen(P0->fmt, P0->bank, wb, n);
            if (PA->bank_bytes != n * ea || memcmp(wb, PA->bank, n * ea) != 0)
                refuse("aux-bank", AT_RUN(r), "run %llu (%s): the bank is not "
                       "the main bank exactly widened", (unsigned long long)r,
                       w);
            free(wb);
        }
        /* streams */
        if (half) {
            int x;
            for (x = 0; x < 3; x++)
                if (strcmp(A->stream[x], main->stream[x]) != 0)
                    refuse("aux-streams", AT_RUN(r), "run %llu (%s): its streams "
                           "are not the main run's", (unsigned long long)r, w);
        } else if (P0->bounded) {
            /* only for a bounded main run: its lanes are at most what was
             * handed ("What an audit spends"); an unbounded one has no
             * initial state, and aux-start refuses state-missing below */
            int x;
            size_t ea = ESZ(PA->fmt);
            for (x = 0; x < 3; x++) {
                char hex[65];
                uint8_t *wv = NULL;
                if (P0->stream[x]) {
                    wv = (uint8_t *)xalloc((size_t)main->lanes, ea);
                    widen(P0->fmt, P0->stream[x], wv, (size_t)main->lanes);
                }
                /* +0 widened is +0: the wider format's zeros, streamed */
                tagged_hash(salt, TAG_STREAM[x], TAG_STREAM_LEN, wv,
                            (size_t)main->lanes * ea, hex);
                free(wv);
                if (strcmp(hex, A->stream[x]) != 0)
                    refuse("aux-streams", AT_RUN(r), "run %llu (%s): stream "
                           "%c is not the main run's exactly widened",
                           (unsigned long long)r, w, 'a' + x);
            }
        }
        /* start */
        if (half) {
            if (strcmp(A->chain[0].start, main->chain[0].start) != 0)
                refuse("aux-start", AT_RUN(r), "run %llu (%s) does not start on "
                       "the main run's initial state", (unsigned long long)r, w);
        } else {
            size_t n0, ea = ESZ(PA->fmt);
            const uint8_t *s0 = kept_state_n(0, 0, &n0);
            uint8_t *wv;
            char hex[65];
            if (!s0)
                refuse("state-missing", AT_RS(0, 0), "run %llu (%s): holding a "
                       "wider run to the main run's initial state exactly "
                       "widened needs that state (run 0 boundary 0), and it was "
                       "not handed", (unsigned long long)r, w);
            n0 /= e0;              /* its elements, as step 7 held them */
            wv = (uint8_t *)xalloc(n0 ? n0 : 1, ea);
            widen(P0->fmt, s0, wv, n0);
            state_hash(salt, wv, n0 * ea, hex);
            free(wv);
            if (strcmp(hex, A->chain[0].start) != 0)
                refuse("aux-start", AT_RUN(r), "run %llu (%s) does not start on "
                       "the main run's initial state exactly widened",
                       (unsigned long long)r, w);
        }
    }
}

/* CFT_AUDIT_PLANT, the instrument: `executor-refuses` makes every re-run's
 * executor refuse, as test_cert.py's monkeypatched seq.run does, so that
 * the gate can hold the refusal a later executor could make. Any other
 * value is `usage`, and the empty string is the variable unset, as
 * CFT_SEGRUN_PLANT's is: Windows cannot spell an empty variable at all. */
static int PLANT_EXECUTOR = 0;

/* Step 9 (cert._rerun). */
static void rerun(const cert_t *C, const uint8_t *salt, const prog_t *P,
                  const plan_t *plan)
{
    uint64_t r;
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        const prog_t *p = &P[r];
        const plan_t *pl = &plan[r];
        size_t sb = 0, esz = ESZ(p->fmt);
        uint8_t *prev = NULL, *zero = NULL;
        uint64_t prev_k = UINT64_MAX, i;
        for (i = 0; i < pl->n; i++) {
            uint64_t k = pl->how == 0 ? i : pl->segs[i];
            size_t have = 0;
            const uint8_t *start = kept_state_n(r, k, &have);
            uint8_t *out;
            uint32_t fl = 0xFFFFFFFFu, bus = 0;
            cft_run_args ra;
            cft_status st;
            char hex[65];
            const seg_t *seg = &run->chain[k];
            if (!start && prev && prev_k + 1 == k)
                start = prev;
            else if (start)
                sb = have;         /* a state handed: step 7 held it to
                                    * lanes x slots, so its size is the
                                    * run's state size, never a product */
            if (!start)
                refuse("state-missing", AT_RS(r, k), "run %llu segment %llu: its "
                       "start state (boundary %llu) was not handed%s",
                       (unsigned long long)r, (unsigned long long)k,
                       (unsigned long long)k, k == 0 ? ", and it is the "
                       "initial state" : ", and the segment before it was not "
                       "re-run to give it");
            if (!p->bounded)
                internal("a re-run of a run nothing handed bounds",
                         CFT_ERR_INTERNAL);
            if (!zero && (!p->stream[0] || !p->stream[1] || !p->stream[2]))
                zero = (uint8_t *)xalloc((size_t)run->lanes ? (size_t)run->lanes
                                         : 1, esz);   /* at most sb bytes */
            out = (uint8_t *)xalloc(sb ? sb : 1, 1);
            memset(&ra, 0, sizeof ra);
            ra.struct_size = sizeof ra;
            ra.a = p->stream[0] ? p->stream[0] : zero;
            ra.b = p->stream[1] ? p->stream[1] : zero;
            ra.c = p->stream[2] ? p->stream[2] : zero;
            ra.n = (size_t)run->lanes;
            ra.bank = p->bank_ext ? p->bank : NULL;
            ra.bank_bytes = p->bank_ext ? p->bank_bytes : 0;
            ra.scratch_in = start;
            ra.scratch_in_bytes = sb;
            ra.scratch_out = out;
            ra.scratch_out_bytes = sb;
            ra.flags_out = &fl;
            ra.bus_out = &bus;
            if (PLANT_EXECUTOR)
                refuse("program-image", AT_RS(r, k), "run %llu segment %llu: "
                       "the executor refuses it: an executor made to refuse "
                       "(CFT_AUDIT_PLANT=executor-refuses)",
                       (unsigned long long)r, (unsigned long long)k);
            st = cft_program_run_ex(p->prog, &ra);
            if (st != CFT_OK) {
                const char *why = cft_last_error();
                refuse("program-image", AT_RS(r, k), "run %llu segment %llu: the "
                       "executor refuses it: %s%s%s", (unsigned long long)r,
                       (unsigned long long)k, cft_strerror(st),
                       why && *why ? " - " : "", why && *why ? why : "");
            }
            state_hash(salt, out, sb, hex);
            if (strcmp(hex, seg->end) != 0)
                refuse("segment-end", AT_RS(r, k), "run %llu segment %llu: "
                       "re-run from its certified start state, it does not "
                       "end on its certified end state", (unsigned long long)r,
                       (unsigned long long)k);
            if (fl != seg->flags)
                refuse("segment-flags", AT_RS(r, k), "run %llu segment %llu: the "
                       "re-run raises flags %lu and the certificate says %lu",
                       (unsigned long long)r, (unsigned long long)k,
                       (unsigned long)fl, (unsigned long)seg->flags);
            if (bus != seg->status)
                refuse("segment-status", AT_RS(r, k), "run %llu segment %llu: "
                       "the re-run's STATUS is %lu and the certificate says %lu",
                       (unsigned long long)r, (unsigned long long)k,
                       (unsigned long)bus, (unsigned long)seg->status);
            /* the start is done with: this segment's end is the next one's
             * start, or, at the last segment, the run's final state, which
             * an accuracy entry may read (kept, unless one was handed) */
            free(prev);
            prev = NULL;
            if (k + 1 == run->S)
                keep_state(r, k + 1, out, sb);
            else
                prev = out;
            prev_k = k;
        }
        free(prev);
        free(zero);
    }
}

#if AUDIT_EXACT
/* Step 10: an entry's value as the stated function of certified runs
 * (cert.derive), in the page's order, every value under the width rule. */
static const uint8_t *need_state(uint64_t r, uint64_t b)
{
    const uint8_t *s = kept_state(r, b);
    if (!s)
        refuse("state-missing", AT_RS(r, b), "run %llu boundary %llu: the "
               "accuracy entry needs this state, and it was neither handed nor "
               "re-run into", (unsigned long long)r, (unsigned long long)b);
    return s;
}

static void quantity(rat *q, const entry_t *E, int f, const uint8_t *state,
                     uint64_t i, uint32_t nslots, const char *which)
{
    unsigned t, s;
    char what[160];
    rat_zero(q);
    for (t = 0; t < E->n_terms; t++) {
        const term_t *T = &E->terms[t];
        rat p = T->coef;
        for (s = 0; s < T->n; s++) {
            rat v;
            snprintf(what, sizeof what, "lane %llu slot %u of the %s state",
                     (unsigned long long)i, T->slot[s], which);
            exact_of(&v, f, state + ((size_t)i * nslots + T->slot[s]) * ESZ(f),
                     what);
            rat_mul(&p, &p, &v);
            snprintf(what, sizeof what, "term %u's product, lane %llu", t,
                     (unsigned long long)i);
            rat_checked(&p, what);
        }
        rat_add(q, q, &p);
        snprintf(what, sizeof what, "the quantity's sum at term %u, lane %llu",
                 t, (unsigned long long)i);
        rat_checked(q, what);
    }
}

static void derive(const cert_t *C, const prog_t *P, uint64_t j, rat *out)
{
    const entry_t *E = &C->entries[j];
    uint64_t r = E->uses, lanes, i, first_lane, last_lane;
    uint32_t nslots;
    int f, have = 0;
    rat best;
    char what[160];
    if (r >= C->R)
        refuse("accuracy-run", NOWHERE, "entry %llu: entry uses run %llu, and "
               "the certificate has %llu", (unsigned long long)j,
               (unsigned long long)r, (unsigned long long)C->R);
    if (E->method != M_DRIFT) {
        int want = E->method == M_HALVING ? K_HALF : K_WIDER;
        if (r == 0 || C->runs[r].kind != want)
            refuse("accuracy-run", NOWHERE, "entry %llu: a %s estimate "
                   "compares run 0 with a %s run; run %llu is %s",
                   (unsigned long long)j, METHOD_NAME[E->method],
                   KIND_NAME[want], (unsigned long long)r, r == 0 ?
                   "the main run" : KIND_NAME[C->runs[r].kind]);
    }
    lanes = C->runs[r].lanes;
    if (E->has_lane && E->lane >= lanes)
        refuse("accuracy-scope", NOWHERE, "entry %llu: lane %llu of a run of "
               "%llu lanes", (unsigned long long)j,
               (unsigned long long)E->lane, (unsigned long long)lanes);
    f = P[r].fmt;
    nslots = P[r].n_in;
    first_lane = E->has_lane ? E->lane : 0;
    last_lane = E->has_lane ? E->lane + 1 : lanes;
    rat_zero(&best);
    if (E->method == M_DRIFT) {
        const uint8_t *s0, *sS;
        unsigned t, s;
        for (t = 0; t < E->n_terms; t++)
            for (s = 0; s < E->terms[t].n; s++)
                if (E->terms[t].slot[s] >= nslots)
                    refuse("accuracy-slot", NOWHERE, "entry %llu: a term "
                           "names slot %u; run %llu's state has %lu slots a "
                           "lane", (unsigned long long)j, E->terms[t].slot[s],
                           (unsigned long long)r, (unsigned long)nslots);
        s0 = need_state(r, 0);
        sS = need_state(r, C->runs[r].S);
        for (i = first_lane; i < last_lane; i++) {
            rat qf, qi, d;
            quantity(&qf, E, f, sS, i, nslots, "final");
            quantity(&qi, E, f, s0, i, nslots, "initial");
            rat_sub(&d, &qf, &qi);
            snprintf(what, sizeof what, "the drift of lane %llu",
                     (unsigned long long)i);
            rat_checked(&d, what);
            if (E->has_lane) {
                *out = d;
                return;
            }
            d.neg = 0;
            if (!have || rat_cmp(&d, &best) > 0)
                best = d;
            have = 1;
        }
    } else {
        int f0 = P[0].fmt;
        const uint8_t *F0 = need_state(0, C->runs[0].S);
        const uint8_t *Fr = need_state(r, C->runs[r].S);
        for (i = first_lane; i < last_lane; i++) {
            rat e;
            uint32_t s;
            rat_zero(&e);
            for (s = 0; s < nslots; s++) {
                rat a, b, d;
                snprintf(what, sizeof what, "run 0 lane %llu slot %lu",
                         (unsigned long long)i, (unsigned long)s);
                exact_of(&a, f0, F0 + ((size_t)i * nslots + s) * ESZ(f0),
                         what);
                snprintf(what, sizeof what, "run %llu lane %llu slot %lu",
                         (unsigned long long)r, (unsigned long long)i,
                         (unsigned long)s);
                exact_of(&b, f, Fr + ((size_t)i * nslots + s) * ESZ(f), what);
                rat_sub(&d, &a, &b);
                d.neg = 0;
                snprintf(what, sizeof what, "the difference at lane %llu slot "
                         "%lu", (unsigned long long)i, (unsigned long)s);
                rat_checked(&d, what);
                if (rat_cmp(&d, &e) > 0)
                    e = d;
            }
            if (E->has_lane) {
                *out = e;
                return;
            }
            if (!have || rat_cmp(&e, &best) > 0)
                best = e;
            have = 1;
        }
    }
    *out = best;
}

/* cert.value_holds */
static int value_holds(const value_t *v, const rat *q)
{
    if (v->form == V_EXACT)
        return rat_eq(&v->exact, q);
    if (v->form == V_ROUNDED) {
        uint8_t b[32];
        rat_round(q, v->fmt, v->rnd, b);
        return memcmp(b, v->bits, ESZ(v->fmt)) == 0;
    }
    {
        int kl = order_kind(v->fmt, v->lo), kh = order_kind(v->fmt, v->hi);
        elem_t x;
        rat e;
        if (kl == 2 || kh == 0)
            return 0;
        if (kl == 1) {
            decode(v->fmt, v->lo, &x);
            rat_of_elem(&e, &x);
            if (rat_cmp(&e, q) > 0)
                return 0;
        }
        if (kh == 1) {
            decode(v->fmt, v->hi, &x);
            rat_of_elem(&e, &x);
            if (rat_cmp(q, &e) > 0)
                return 0;
        }
        return 1;
    }
}
#endif /* AUDIT_EXACT */

/* ---- the verdict ------------------------------------------------------- */

static uint64_t gcd_u64(uint64_t a, uint64_t b)
{
    while (b) {
        uint64_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

/* cert._segment_list: `[1, 3]`, a sample's and a named choice's alike */
static void print_segments(const plan_t *p)
{
    uint64_t i;
    printf("[");
    for (i = 0; i < p->n; i++)
        printf("%s%llu", i ? ", " : "", (unsigned long long)p->segs[i]);
    printf("]");
}

static void identity_line(const char *k, const char *v)
{
    if (!strcmp(v, "unknown"))
        printf("%s: unknown - the producer did not record it\n", k);
    else
        printf("%s: %s - stated, not checked\n", k, v);
}

/* cert.Verdict.lines(), byte for byte */
static void print_verdict(const cert_t *C, const plan_t *plan
#if AUDIT_EXACT
                          , const rat *values
#endif
                          )
{
    uint64_t r, i;
    printf("cft-certificate 1: ACCEPTED - every check passed\n");
    printf("%s\n", C->keyed ? "keyed: the salt handed is the one committed to"
           : "open: no salt - its hashes are plain SHA-256, and anyone "
             "holding the states can audit it");
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        const plan_t *p = &plan[r];
        printf("run %llu %s %s, %llu lanes, %llu segments: re-ran %llu of %llu",
               (unsigned long long)r, KIND_NAME[run->kind], FMT[run->fmt].name,
               (unsigned long long)run->lanes, (unsigned long long)run->S,
               (unsigned long long)p->n, (unsigned long long)run->S);
        if (p->how == 1) {
            uint64_t S = run->S, k = p->n, g = gcd_u64(S - k, S);
            printf(", a sample drawn with the auditor's seed %s: a producer "
                   "who made f of these %llu segments wrong escapes it with "
                   "probability C(%llu-f,%llu)/C(%llu,%llu); for f = 1 that is "
                   "%llu/%llu", p->seed_hex, (unsigned long long)S,
                   (unsigned long long)S, (unsigned long long)k,
                   (unsigned long long)S, (unsigned long long)k,
                   (unsigned long long)((S - k) / g),
                   (unsigned long long)(S / g));
            printf("; the segments sampled: ");
            print_segments(p);
        } else if (p->how == 2) {
            printf(", the segments named: ");
            print_segments(p);
        } else {
            printf(", every segment");
        }
        printf("\n");
    }
#if AUDIT_EXACT
    for (i = 0; i < C->A; i++) {
        char t[2 * (CFT_BN_BITS / 4) + 8];
        rat_text(&values[i], t);
        printf("accuracy entry %llu: re-derived as %s - the value is the stated "
               "function of the certified runs; that an estimate estimates "
               "well is not shown\n", (unsigned long long)i, t);
    }
#endif
    identity_line("build-id", C->build_id);
    identity_line("backend", C->backend);
    identity_line("device-xclbin", C->xclbin);
    identity_line("device-version", C->version);
    identity_line("device-caps", C->caps);
    identity_line("device-tiles", C->tiles);
}

/* ---- the two small modes ----------------------------------------------- */

static int do_sample(const char *seed_s, const char *r_s, const char *S_s,
                     const char *k_s)
{
    uint8_t seed[SEED_BYTES];
    uint64_t r, S, k, i, *segs;
    if (!seed_of_hex(seed_s, seed))
        refuse("choice", NOWHERE, "a sampling seed is exactly %d bytes, 64 hex "
               "digits", SEED_BYTES);
    if (!index_of(r_s, &r) || r > 0xFFFFFFFFu)
        refuse("choice", NOWHERE, "run '%.40s': a run index is an integer in "
               "0..2^32 - 1, the PRNG's four bytes", r_s);
    if (!index_of(S_s, &S) || !index_of(k_s, &k) || k < 1 || k > S)
        refuse("choice", NOWHERE, "a sample of '%.40s' from '%.40s' segments; "
               "both are integers, 1 <= k <= S", k_s, S_s);
    segs = sample(seed, (uint32_t)r, S, k);
    for (i = 0; i < k; i++)
        printf("%s%llu", i ? " " : "", (unsigned long long)segs[i]);
    printf("\n");
    free(segs);
    return 0;
}

#if defined(CFT_AUDIT_PROBE)
/* ---- the probe --------------------------------------------------------- */

/* This file's numerics, one operation a line on stdin and one answer a
 * line on stdout, so that the gate holds them to Python's integers and
 * to the golden model (host/tests/audit_check.py, section 6): the
 * division, the gcd, the exact arithmetic, the rounding, an element's
 * exact value, and the library's widening and exact decimal, measured
 * before they are trusted (the brief). Compiled only by the gate, with
 * -DCFT_AUDIT_PROBE; the tool itself has no such mode.
 *
 *   gcd A B | divmod A B          hex naturals, up to 2,047 bits
 *   add P Q | sub P Q | mul P Q   rationals [-]N/D, reduced
 *   cmp P Q                       -1, 0 or 1
 *   round F R P                   format 0..3, direction 0..4: its bits
 *   exact F H                     nonfinite, width NB DB, or N/D
 *   widen F H                     H one format up, exactly
 *   decimal F H                   the exact decimal
 *   half F X Y                    1 if X is exactly half of Y
 *
 * An element is hex, big-endian, width/4 digits, as a certificate
 * spells one. */
#if !AUDIT_EXACT
#error "the probe needs the exact arithmetic: a cft_bn of 2,047 bits or more"
#endif

static void probe_rat(const char *s, rat *q)
{
    const char *slash = strchr(s, '/');
    q->neg = *s == '-';
    if (q->neg)
        s++;
    bn_from_hex(&q->n, s, (size_t)(slash - s));
    bn_from_hex(&q->d, slash + 1, strlen(slash + 1));
    if (cft_bn_is_zero(&q->n))
        q->neg = 0;
}

static void probe_elem_out(int f, const uint8_t *le)
{
    size_t i;
    for (i = ESZ(f); i-- > 0;)
        printf("%02x", le[i]);
}

int main(void)
{
    static char line[1 << 16];
    while (fgets(line, sizeof line, stdin)) {
        char *tok[5];
        int n = 0;
        char *p = strtok(line, " \n");
        while (p && n < 5) {
            tok[n++] = p;
            p = strtok(NULL, " \n");
        }
        if (n == 0)
            continue;
        if (!strcmp(tok[0], "gcd") || !strcmp(tok[0], "divmod")) {
            cft_bn a, b, q, r;
            char h[CFT_BN_BITS / 4 + 2];
            bn_from_hex(&a, tok[1], strlen(tok[1]));
            bn_from_hex(&b, tok[2], strlen(tok[2]));
            if (tok[0][0] == 'g') {
                bn_gcd(&q, &a, &b);
                bn_hex(&q, h);
                printf("%s\n", h);
            } else {
                bn_divmod(&q, &r, &a, &b);
                bn_hex(&q, h);
                printf("%s ", h);
                bn_hex(&r, h);
                printf("%s\n", h);
            }
        } else if (!strcmp(tok[0], "add") || !strcmp(tok[0], "sub") ||
                   !strcmp(tok[0], "mul") || !strcmp(tok[0], "cmp")) {
            rat x, y, z;
            char t[2 * (CFT_BN_BITS / 4) + 8];
            probe_rat(tok[1], &x);
            probe_rat(tok[2], &y);
            if (tok[0][0] == 'c') {
                printf("%d\n", rat_cmp(&x, &y));
                continue;
            }
            if (tok[0][0] == 'a')
                rat_add(&z, &x, &y);
            else if (tok[0][0] == 's')
                rat_sub(&z, &x, &y);
            else
                rat_mul(&z, &x, &y);
            rat_text(&z, t);
            printf("%s\n", t);
        } else if (!strcmp(tok[0], "round")) {
            int f = atoi(tok[1]), r = atoi(tok[2]);
            rat q;
            uint8_t out[32];
            probe_rat(tok[3], &q);
            rat_round(&q, f, r, out);
            probe_elem_out(f, out);
            printf("\n");
        } else if (!strcmp(tok[0], "exact")) {
            int f = atoi(tok[1]), got;
            uint8_t le[32];
            elem_t x;
            rat q;
            char t[2 * (CFT_BN_BITS / 4) + 8];
            elem_from_hex(f, tok[2], le);
            decode(f, le, &x);
            got = rat_of_elem(&q, &x);
            if (got == 1) {
                printf("nonfinite\n");
            } else if (got == 2) {
                long nb, db;
                elem_bits(&x, &nb, &db);
                printf("width %ld %ld\n", nb, db);
            } else {
                rat_text(&q, t);
                printf("%s\n", t);
            }
        } else if (!strcmp(tok[0], "widen")) {
            int f = atoi(tok[1]);
            uint8_t le[32], w[32];
            elem_from_hex(f, tok[2], le);
            widen(f, le, w, 1);
            probe_elem_out(f + 1, w);
            printf("\n");
        } else if (!strcmp(tok[0], "decimal")) {
            int f = atoi(tok[1]);
            uint8_t le[32];
            size_t len = 0;
            uint32_t fl = 0;
            char *buf;
            cft_status st;
            elem_from_hex(f, tok[2], le);
            st = cft_to_decimal_char(host_dev(), (cft_format)f, CFT_RNE, le, 0,
                                     NULL, 0, &len, &fl);
            if (st != CFT_ERR_INVALID_ARGUMENT || len == 0)
                internal("cft_to_decimal_char, sizing", st);
            buf = (char *)xalloc(len, 1);
            st = cft_to_decimal_char(host_dev(), (cft_format)f, CFT_RNE, le, 0,
                                     buf, len, &len, &fl);
            if (st != CFT_OK)
                internal("cft_to_decimal_char", st);
            printf("%s\n", buf);
            free(buf);
        } else if (!strcmp(tok[0], "half")) {
            int f = atoi(tok[1]);
            uint8_t x[32], y[32];
            elem_from_hex(f, tok[2], x);
            elem_from_hex(f, tok[3], y);
            printf("%d\n", is_half(f, x, y));
        } else {
            printf("?\n");
        }
    }
    return 0;
}

#else /* the tool */

/* ---- main -------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *cert_path = NULL, *salt_path = NULL, *states_path = NULL;
    const char *seed_arg = NULL, *plant = getenv("CFT_AUDIT_PLANT");
    const char *sample_args[4] = { NULL, NULL, NULL, NULL };
    int read_only = 0, want_sample = 0, i;
    uint8_t *data, *salt = NULL;
    size_t n_data, n_salt = 0, b;
    rdr_t R;
    cert_t C;
    plan_t *plan;
    prog_t *P;
#if AUDIT_EXACT
    rat *values;
    uint64_t j;
#endif

    if (plant && *plant) {
        if (!strcmp(plant, "executor-refuses"))
            PLANT_EXECUTOR = 1;
        else
            refuse("usage", NOWHERE, "CFT_AUDIT_PLANT=%s is not an instrument "
                   "this tool has (executor-refuses)", plant);
        fprintf(stderr, "cft-audit: CFT_AUDIT_PLANT=%s - an instrument: every "
                "re-run's executor refuses\n", plant);
    }
    if (argc < 2) {
        usage_text(stderr);
        refuse("usage", NOWHERE, "nothing to do");
    }
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        block_t *cur = N_BLK ? &BLK[N_BLK - 1] : NULL;
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) {
            usage_text(stdout);
            return 0;
        } else if (!strcmp(a, "--cert")) {
            once(&cert_path, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--salt")) {
            once(&salt_path, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--states")) {
            once(&states_path, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--seed")) {
            once(&seed_arg, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--read")) {
            if (read_only)
                refuse("usage", NOWHERE, "--read is given twice");
            read_only = 1;
        } else if (!strcmp(a, "--sample")) {
            int k;
            if (want_sample)
                refuse("usage", NOWHERE, "--sample is given twice");
            want_sample = 1;
            for (k = 0; k < 4; k++)
                sample_args[k] = need_arg(argc, argv, &i);
        } else if (!strcmp(a, "--run")) {
            const char *key = need_arg(argc, argv, &i);
            block_t *g;
            size_t k;
            for (k = 0; k < N_BLK; k++)
                if (!strcmp(BLK[k].key, key))
                    refuse("usage", NOWHERE, "--run %s is given twice; a run "
                           "has one block", key);
            g = (block_t *)xalloc(N_BLK + 1, sizeof *g);
            if (N_BLK)
                memcpy(g, BLK, N_BLK * sizeof *g);
            free(BLK);
            BLK = g;
            BLK[N_BLK].key = key;
            BLK[N_BLK].valid = index_of(key, &BLK[N_BLK].r);
            N_BLK++;
        } else if (!strcmp(a, "--image") || !strcmp(a, "--bank") ||
                   !strcmp(a, "--choose")) {
            const char *v = need_arg(argc, argv, &i);
            if (!cur)
                refuse("usage", NOWHERE, "%s belongs to a run: give it after "
                       "--run R", a);
            if (!strcmp(a, "--image"))
                once(&cur->image_path, a, v);
            else if (!strcmp(a, "--bank"))
                once(&cur->bank_path, a, v);
            else
                once(&cur->choose, a, v);
        } else if (!strcmp(a, "--stream")) {
            const char *x = need_arg(argc, argv, &i);
            const char *v = need_arg(argc, argv, &i);
            if (!cur)
                refuse("usage", NOWHERE, "--stream belongs to a run: give it "
                       "after --run R");
            if (strlen(x) != 1 || x[0] < 'a' || x[0] > 'c')
                refuse("usage", NOWHERE, "--stream %s: a stream is a, b or c",
                       x);
            once(&cur->stream_path[x[0] - 'a'], "--stream", v);
        } else {
            refuse("usage", NOWHERE, "unknown argument '%s' (--help lists "
                   "them)", a);
        }
    }

    /* ---- the two small modes ------------------------------------------ */
    if (want_sample) {
        if (argc != 6)
            refuse("usage", NOWHERE, "--sample takes SEED R S K and nothing "
                   "else");
        return do_sample(sample_args[0], sample_args[1], sample_args[2],
                         sample_args[3]);
    }
    if (!cert_path)
        refuse("usage", NOWHERE, "--cert is required");
    if (read_only && (states_path || seed_arg || N_BLK))
        refuse("usage", NOWHERE, "--read takes --cert and --salt, and nothing "
               "else");
    for (b = 0; b < N_BLK; b++) {
        block_t *B = &BLK[b];
        if (!B->image_path && !B->bank_path && !B->choose &&
            !B->stream_path[0] && !B->stream_path[1] && !B->stream_path[2])
            refuse("usage", NOWHERE, "--run %s gives nothing", B->key);
        if (B->bank_path && !B->image_path)
            refuse("usage", NOWHERE, "--run %s: --bank goes with --image",
                   B->key);
    }

    /* ---- every input file, read before the first step ------------------ */
    data = read_named("the certificate", cert_path, &n_data);
    if (salt_path)
        salt = read_named("the salt", salt_path, &n_salt);
    for (b = 0; b < N_BLK; b++) {
        block_t *B = &BLK[b];
        int x;
        if (B->image_path)
            B->image = read_named("the image", B->image_path, &B->image_bytes);
        if (B->bank_path)
            B->bank = read_named("the bank", B->bank_path, &B->bank_bytes);
        for (x = 0; x < 3; x++)
            if (B->stream_path[x])
                B->stream[x] = read_named("the stream", B->stream_path[x],
                                          &B->stream_bytes[x]);
    }
    if (states_path)
        list_states(states_path);

    memset(&R, 0, sizeof R);
    memset(&C, 0, sizeof C);
    /* 1 integrity, 2 form */
    read_all(data, n_data, &R, &C);
    if (read_only) {
        if (salt_path)
            check_salt(&C, salt, n_salt, 1);
        printf("cft-certificate 1: READ - the hash line, the body's hash and "
               "the strict form hold\n");
        if (C.keyed)
            printf("keyed: %s\n", salt_path ? "the salt handed is the one "
                   "committed to" : "no salt was handed, so its commitment "
                   "is not checked");
        else
            printf("open: no salt - its hashes are plain SHA-256\n");
        return 0;
    }
    /* 2, its second half: the auditor's own choice */
    plan = make_plan(&C, seed_arg);
    /* 3 salt */
    check_salt(&C, salt_path ? salt : NULL, n_salt, salt_path != NULL);
    if (!C.keyed)
        salt = NULL;
    /* 4 programs */
    P = check_programs(&C);
    /* 5 streams */
    check_streams(&C, salt, P);
    /* 6 continuity */
    check_continuity(&C);
    /* 7 states */
    check_states(&C, salt, P, plan);
    /* 8 relations */
    check_relations(&C, salt, P);
    /* 9 re-runs */
    rerun(&C, salt, P, plan);
    /* 10 accuracy */
#if AUDIT_EXACT
    values = (rat *)xalloc((size_t)C.A, sizeof *values);
    for (j = 0; j < C.A; j++) {
        ENTRY_NOW = (long long)j;
        derive(&C, P, j, &values[j]);
        if (!value_holds(&C.entries[j].value, &values[j])) {
            char t[2 * (CFT_BN_BITS / 4) + 8];
            rat_text(&values[j], t);
            refuse("accuracy-value", NOWHERE, "entry %llu: the value recorded "
                   "is not the %s of the certified runs, which is %s",
                   (unsigned long long)j, METHOD_NAME[C.entries[j].method], t);
        }
        ENTRY_NOW = NONE;
    }
    print_verdict(&C, plan, values);
#else
    print_verdict(&C, plan);
#endif
    return 0;
}
#endif /* CFT_AUDIT_PROBE */
