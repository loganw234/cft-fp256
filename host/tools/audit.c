/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-audit - the audit of docs/CERTIFICATES.md, versions 1 and 2, in C:
 * every step of "The audit" and of "Version 2's audit" that needs no
 * source, the strict readers included, in the page's order, beside the
 * golden one (python/cft_golden/cert.py and cert2.py, cert.audit). The
 * plan of record's step 4 (docs/ROADMAP.md, "Steps 4 and 7"), and
 * version 2's C half (parcel CV2CA, 2026-10-02); the page's section "The
 * audit tool" is this tool's manual.
 *
 *   cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]
 *             [--signature SIG] [--keyring RING] [--superseded OLD]
 *             --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]
 *                     [--choose all|sample:K|K,K,...]
 *                     [--define all|K,K,...]
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
 *                   files cft-segrun writes. Other files are not read.
 *                   Each is held to be a regular file and opened before
 *                   step 1 (`usage` there), and its bytes read at step 7
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
 *   memory (71)       an allocation of this tool's own that fails, or a
 *                     --sample K whose map this process cannot size
 *   build-width (78)  a build whose bigint is narrower than the width
 *                     rule needs, handed a certificate with an accuracy
 *                     entry (below)
 *   build-format (78) a build whose library carries formats only up to
 *                     CFT_MAX_FORMAT, asked for a wider one: the reader
 *                     refuses it at the format word, a run's
 *                     program-format line or an accuracy value's
 *                     (rounded or enclosed), and step 4 at a run whose
 *                     image's header names one. The lead's decisions,
 *                     2026-09-29, after verifier-A1 found such a run
 *                     refused program-image, a name for an input that is
 *                     not the one certified where the cause is the
 *                     build, and such a value an internal error
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
 * computes an exact value in a narrower bigint. CFT_BN_LIMBS can keep a
 * build's bigint at 2,048 bits under a lower CFT_MAX_FORMAT; such a
 * build audits exact values, in formats within its ceiling. Every build
 * audits in full what it can, and refuses by its own name only what it
 * cannot (build-width, build-format).
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
 *
 * ---------------------------------------------------------------
 * Version 2 (the page's "Version 2"; cert2.py is the authority)
 * ---------------------------------------------------------------
 *
 * The tool reads both versions, choosing as cert.audit does: a file whose
 * first 18 bytes are "cft-certificate 2\n" is version 2's, read by version
 * 2's strict reader and audited by version 2's steps; every other file is
 * version 1's, and its reading, audit and verdict are what they were. A
 * version-1 certificate handed one of version 2's inputs is `usage`, as
 * cert.audit raises a TypeError for one. Version 2's inputs:
 *
 *   --signature SIG    the detached signature, a .sig file (step 2a)
 *   --keyring RING     a keyring, lines `key <64 hex> <text>` (step 2a)
 *   --superseded OLD   the certificate this one names in `supersedes` (3a)
 *   --define SPEC      in a run's block: the definition re-run's segments,
 *                      `all` or `K,K,...` (define[R], step 9a)
 *   --states DIR       also hands every run-<r>-segment-<k>.flags in DIR
 *                      as lane_flags[r][k], the per-lane flags (step 7)
 *
 * It takes NO SOURCE: there is no interpreter of the language in C, and no
 * compiler. So a step that needs one refuses `source-missing` exactly where
 * the golden auditor handed no source does - a replay in a re-run segment
 * (after the replay line's own checks), a wider-source relation (after its
 * format, lanes, source lines and steps), and a definition re-run (once its
 * start is known) - and every run that names a source is reported "named,
 * not handed". It regenerates no initial state either: a named generator
 * is reported, as the golden auditor reports one it was not asked to
 * regenerate. Everything else is checked: the signature (Ed25519, RFC 8032,
 * tools/ed25519.h, and SHA-512, tools/sha512.h, both written here and held
 * to python/tests/test_ed25519.py's vectors), a key of small order refused
 * `signer` wherever a key is read, the keyring, the superseded
 * certificate, the blocks handed and R23's identities, each re-run's block
 * where its run says `lane-flags yes`, the replay lines' raw values, and
 * the definition: this library's profile and language version (cft.h's
 * CFT_PROFILE_* and CFT_LANGUAGE_*) against the certificate's, so that a
 * re-derivation that fails where they do not cover the certificate's is
 * refused `definition-differs` (THROUGH, below), as cert2._Through does.
 *
 * Accepted, stdout is two header lines - `auditor cft-audit <build id>` and
 * `audited <time>`, the auditor's identity and the audit's time, which
 * cert2.Verdict.header() holds and the comparison between auditors leaves
 * out - and then cert2.Verdict.lines(), byte for byte.
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
#include <time.h>

#include "cft.h"
#include "../src/bigint.h"
#include "../src/sha256.h"
/* the exact arithmetic of an accuracy entry, the bigint's missing pieces,
 * the formats and the certificate's words: shared with cft-segrun, which
 * writes the entries this tool re-derives (the plan's step 5) */
#include "cert_exact.h"
/* Ed25519 verification and SHA-512, for version 2's detached signature
 * and its keys (this tool's alone) */
#include "ed25519.h"

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
 * width rule"). Both are cert_exact.h's, under this file's old names. The
 * formats (FMT, ESZ, PREC), the directions (RND_NAME, RND_CODE), the
 * certificate's words (KIND_NAME, METHOD_NAME, KINDS, METHOD_KIND) and
 * MAX_TERMS, MAX_FACTORS and MAX_SLOT are there too. */
#define WIDTH_BITS   CX_WIDTH_BITS
#define AUDIT_EXACT  CX_EXACT

#define SALT_BYTES   32
#define SEED_BYTES   32
#define MAX_HSLOTS   512       /* h-slots at most, each below it */
#define DEC_MAX      ((uint64_t)INT64_MAX)
#define NONE         (-1LL)

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
    /* version 2's names (cert.REFUSALS), in the same families */
    { "marked", 2 }, { "replay-lane-flags", 2 }, { "replay-source", 2 },
    { "replay-method", 2 }, { "provenance-order", 2 },
    { "signature-format", 4 }, { "signature", 4 }, { "signature-key", 4 },
    { "signer", 4 }, { "supersedes", 4 }, { "source-digest", 4 },
    { "source-refused", 4 }, { "source-format", 4 }, { "source-graph", 4 },
    { "source-param", 4 }, { "source-shape", 4 }, { "source-image", 4 },
    { "source-missing", 4 }, { "lane-flags-shape", 4 },
    { "lane-flags-hash", 4 }, { "initial-state", 4 },
    { "lane-flags-identity", 5 }, { "aux-source", 5 },
    { "segment-lane-flags", 6 }, { "replay-missing", 6 },
    { "replay-unmarked", 6 }, { "replay-raw", 6 }, { "replay-changed", 6 },
    { "definition-end", 6 }, { "definition-flags", 6 },
    { "definition-differs", 78 }, { "definition-unavailable", 78 },
    { "compiler-differs", 78 }, { "replay-undecided", 78 },
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

/* Version 2's "who is blamed when a re-derivation fails" (the page's "The
 * definition"; cert2._Cover and cert2._Through). THROUGH is set while a
 * re-derivation through the definition runs - step 4's loader verdicts,
 * the wider-source relation, a re-run with its replay line's checks, and
 * the corrected segment's - and COVERED says whether this library's
 * definition (cft.h's CFT_PROFILE_* and CFT_LANGUAGE_*) covers the
 * certificate's. A refusal raised in such a region where it does not is
 * refused `definition-differs` at its own location, naming the refusal it
 * stands for (judge_differs, after internal()), as cert2._Through
 * re-raises one - but for the four cert2._Through lets pass
 * (definition-unavailable, source-missing, state-missing and
 * definition-differs itself), and the tool's own names, which are its
 * limits and not re-derivations. Version 1 never sets THROUGH. */
static int THROUGH = 0, COVERED = 1;
static const char *CERT_PROFILE = "", *CERT_LANGUAGE = "";

static void judge_differs(const char *name, where_t w, const char *msg)
    NORETURN;

static int passes_through(const char *name)
{
    static const char *const PASS[] = {
        "definition-unavailable", "source-missing", "state-missing",
        "definition-differs", "usage", "memory", "build-width",
        "build-format" };
    size_t i;
    for (i = 0; i < sizeof PASS / sizeof PASS[0]; i++)
        if (!strcmp(name, PASS[i]))
            return 1;
    return 0;
}

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
    if (THROUGH && !COVERED && !passes_through(name)) {
        char msg[1024];
        va_start(ap, fmt);
        vsnprintf(msg, sizeof msg, fmt, ap);
        va_end(ap);
        THROUGH = 0;
        judge_differs(name, w, msg);
    }
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

/* A version's one spelling (cert2.version_text): the major, then `.` and
 * the minor where the minor is not 0 */
static void version_text(char *out, size_t cap, unsigned long long major,
                         unsigned long long minor)
{
    if (minor)
        snprintf(out, cap, "%llu.%llu", major, minor);
    else
        snprintf(out, cap, "%llu", major);
}

/* cert2._Cover.judge: a re-derivation that failed, under a definition
 * that does not cover the certificate's, at the refusal's own location */
static void judge_differs(const char *name, where_t w, const char *msg)
{
    char ap[48], al[48];
    version_text(ap, sizeof ap, CFT_PROFILE_MAJOR, CFT_PROFILE_MINOR);
    version_text(al, sizeof al, CFT_LANGUAGE_MAJOR, CFT_LANGUAGE_MINOR);
    refuse("definition-differs", w, "%s under the auditor's definition "
           "(profile %s, language %s), which does not cover the "
           "certificate's (profile %s, language %s): the auditor's own "
           "limit, not a verdict on the certificate - hand the audit the "
           "named definition to decide (%s)", name, ap, al, CERT_PROFILE,
           CERT_LANGUAGE, msg);
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
/* version 2's two new tags ("Hashes in version 2"): a segment's per-lane
 * flags, keyed as a state is, and a signature's message, never keyed */
static const char TAG_LANE_FLAGS[] = "cft-certificate 2 lane-flags";
#define TAG_LANE_FLAGS_LEN (sizeof TAG_LANE_FLAGS) /* 29, the NUL included */
static const char TAG_SIGNATURE[] = "cft-signature 1";
#define TAG_SIGNATURE_LEN (sizeof TAG_SIGNATURE)   /* 16, the NUL included */

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

/* cert2.lane_flags_hash: a block of a byte a lane, as a state is hashed */
static void lane_flags_hash(const uint8_t *salt, const void *bytes, size_t n,
                            char hex[65])
{
    tagged_hash(salt, TAG_LANE_FLAGS, TAG_LANE_FLAGS_LEN, bytes, n, hex);
}

/* ---- spellings --------------------------------------------------------- */

/* (is_hexl and hexval are cert_exact.h's) */

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

/* ---- version 2's encodings ("Version 2's encodings"; cert2.py's) -------
 *
 * The four words that stand for an absent value; a text is never one. */
static const char *const WORDS[4] = { "none", "unknown", "withheld",
                                      "given" };

static int is_word(const char *s)
{
    return word_index(s, WORDS, 4) >= 0;
}

/* bytes that are UTF-8 as Python's strict decoder reads it: no overlong
 * form, no surrogate, nothing past U+10FFFF, every sequence whole */
static int utf8_ok(const uint8_t *b, size_t n)
{
    size_t i = 0;
    while (i < n) {
        uint8_t c = b[i];
        size_t need, k;
        uint8_t lo = 0x80, hi = 0xBF;
        if (c < 0x80) {
            i++;
            continue;
        }
        if (c >= 0xC2 && c <= 0xDF)
            need = 1;
        else if (c >= 0xE0 && c <= 0xEF) {
            need = 2;
            if (c == 0xE0)
                lo = 0xA0;              /* no overlong form */
            if (c == 0xED)
                hi = 0x9F;              /* no surrogate */
        } else if (c >= 0xF0 && c <= 0xF4) {
            need = 3;
            if (c == 0xF0)
                lo = 0x90;
            if (c == 0xF4)
                hi = 0x8F;              /* nothing past U+10FFFF */
        } else {
            return 0;
        }
        if (need > n - 1 - i)
            return 0;                   /* a sequence cut short */
        for (k = 1; k <= need; k++) {
            uint8_t d = b[i + k];
            if (k == 1 ? (d < lo || d > hi) : (d < 0x80 || d > 0xBF))
                return 0;
        }
        i += need + 1;
    }
    return 1;
}

static int hexup_val(char c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'A' && c <= 'F' ?
           c - 'A' + 10 : -1;
}

/* A text's one spelling (cert2.read_text): 1 to 255 characters, each byte
 * from 0x21 to 0x7E but `%` standing as itself and every other byte `%`
 * and two UPPERCASE hex digits, never a byte that may stand as itself
 * encoded, the bytes UTF-8, and the value none of the four words. */
static int text_ok(const char *tok)
{
    uint8_t buf[256];
    size_t n = strlen(tok), i, m = 0;
    if (n < 1 || n > 255)
        return 0;
    for (i = 0; i < n;) {
        unsigned char c = (unsigned char)tok[i];
        if (c == '%') {
            int a, b;
            if (i + 2 >= n)
                return 0;               /* a lone or cut `%` */
            a = hexup_val(tok[i + 1]);
            b = hexup_val(tok[i + 2]);
            if (a < 0 || b < 0)
                return 0;
            c = (unsigned char)(a << 4 | b);
            if (c >= 0x21 && c <= 0x7E && c != 0x25)
                return 0;               /* a byte that may stand as itself */
            buf[m++] = c;
            i += 3;
        } else {
            if (c < 0x21 || c > 0x7E)
                return 0;
            buf[m++] = c;
            i++;
        }
    }
    return utf8_ok(buf, m) && !is_word(tok);
}

static int days_in(unsigned y, unsigned mo)
{
    if (mo == 2)
        return (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)) ? 29 : 28;
    return mo == 4 || mo == 6 || mo == 9 || mo == 11 ? 30 : 31;
}

/* A time's one spelling (cert2.read_time): YYYY-MM-DDTHH:MM:SSZ, a real
 * Gregorian date, hours 00..23, minutes and seconds 00..59. Its fields are
 * fixed-width, so two times compare as their tokens do. */
static int time_ok(const char *t)
{
    static const char SHAPE[] = "dddd-dd-ddTdd:dd:ddZ";
    unsigned y, mo, d, h, mi, s;
    size_t i;
    if (strlen(t) != 20)
        return 0;
    for (i = 0; i < 20; i++) {
        if (SHAPE[i] == 'd') {
            if (t[i] < '0' || t[i] > '9')
                return 0;
        } else if (t[i] != SHAPE[i]) {
            return 0;
        }
    }
#define TWO(p) ((unsigned)(t[p] - '0') * 10u + (unsigned)(t[(p) + 1] - '0'))
    y = TWO(0) * 100u + TWO(2);
    mo = TWO(5);
    d = TWO(8);
    h = TWO(11);
    mi = TWO(14);
    s = TWO(17);
#undef TWO
    return mo >= 1 && mo <= 12 && d >= 1 && d <= (unsigned)days_in(y, mo) &&
           h <= 23 && mi <= 59 && s <= 59;
}

/* one part of a version: [1-9][0-9]{0,18}, at most 2^63 - 1 */
static int version_part(const char *s, size_t n, uint64_t *v)
{
    char tmp[24];
    if (n < 1 || n > 19 || s[0] < '1' || s[0] > '9')
        return 0;
    memcpy(tmp, s, n);
    tmp[n] = 0;
    return index_of(tmp, v);
}

/* A version's one spelling (cert2.read_version): a major, then `.` and a
 * minor where the minor is not 0 */
static int version_of(const char *tok, uint64_t *major, uint64_t *minor)
{
    const char *dot = strchr(tok, '.');
    if (!dot) {
        *minor = 0;
        return version_part(tok, strlen(tok), major);
    }
    return version_part(tok, (size_t)(dot - tok), major) &&
           version_part(dot + 1, strlen(dot + 1), minor);
}

/* cert2.covers: does a definition at (major, minor) cover a certificate's
 * version token (`none` always, `unknown` never)? */
static int covers(uint64_t major, uint64_t minor, const char *tok)
{
    uint64_t a, b;
    if (!strcmp(tok, "none"))
        return 1;
    if (!version_of(tok, &a, &b))
        return 0;
    return major == a && minor >= b;
}

/* a variable's name: [A-Z][A-Z0-9_]{0,63} */
static int env_name_ok(const char *s)
{
    size_t i, n = strlen(s);
    if (n == 0 || n > 64 || s[0] < 'A' || s[0] > 'Z')
        return 0;
    for (i = 1; i < n; i++)
        if (!((s[i] >= 'A' && s[i] <= 'Z') || (s[i] >= '0' && s[i] <= '9') ||
              s[i] == '_'))
            return 0;
    return 1;
}

/* a param's name, the language's: [A-Za-z_][A-Za-z0-9_]* */
static int lang_name_ok(const char *s)
{
    size_t i, n = strlen(s);
    if (n == 0 || !((s[0] >= 'a' && s[0] <= 'z') ||
                    (s[0] >= 'A' && s[0] <= 'Z') || s[0] == '_'))
        return 0;
    for (i = 1; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= 'A' && s[i] <= 'Z') ||
              (s[i] >= '0' && s[i] <= '9') || s[i] == '_'))
            return 0;
    return 1;
}

/* The writer's list (cert2.ENVIRONMENT_NAMES): every variable libcft and
 * cft-segrun read. An `env` line naming another is malformed, so that a
 * certificate carries no variable but these. host/tests/audit_check.py
 * holds this list to cert2's, between its two markers.
 * BEGIN ENVIRONMENT_NAMES */
static const char *const ENVIRONMENT_NAMES[] = {
    "CFT_DIVSQRT_FULL", "CFT_DIVSQRT_SEQ", "CFT_SEGRUN_PLANT",
    "CFT_TIMEOUT_MS", "CFT_TRANSCEND_MINPREC", "CFT_XRT_BIND",
    "CFT_XRT_CAPS", "CFT_XRT_MASK_ADDR_OVERRIDE", "CFT_XRT_PROGRAM_CUTS",
    "CFT_XRT_REDUCE_BC", "CFT_XRT_TILES", "CFT_XRT_TILE_ORDER",
    "CFT_XRT_TRACE", "CFT_XRT_WITNESS", "XCL_EMULATION_MODE" };
/* END ENVIRONMENT_NAMES */

/* The generators the golden model defines (cert2.GENERATORS): a verdict
 * reports one of these as not regenerated, any other as not known. This
 * tool regenerates none. */
static const char *const GENERATORS[] = { "shake-box" };

/* ---- cft_bn, elements and rationals ------------------------------------
 *
 * cft_bn's missing pieces (a division, a gcd, an exact left shift), an
 * element's exact value, and the rationals under the width rule are
 * cert_exact.h's, shared with cft-segrun (the plan's step 5); every
 * failure there is a status, which this file turns into its refusals
 * and internal(). What stays here is what only the auditor does with an
 * element: read one from the page's hex, hold a half-step bank to
 * exactly half the main one, widen one a rung, and hold a decimal to
 * its hex. */

#if AUDIT_EXACT
static void elem_from_hex(int f, const char *h, uint8_t *le)
{
    size_t i, n = ESZ(f);
    for (i = 0; i < n; i++)
        le[i] = (uint8_t)(hexval(h[2 * (n - 1 - i)]) << 4 |
                          hexval(h[2 * (n - 1 - i) + 1]));
}
#endif

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

#if AUDIT_EXACT
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
#endif

/* ---- the certificate --------------------------------------------------- */

/* (a run's kind K_*, an entry's method M_* and a value's form V_*, with
 * their words, and an entry's term_t, value_t and entry_t, are
 * cert_exact.h's) */

typedef struct {
    const char *start, *end;        /* 64 hex, into the body */
    uint32_t flags, status;
    const char *lanes;              /* version 2, `lane-flags yes`: the
                                     * block's hash; NULL otherwise */
} seg_t;

/* version 2: a replay line, `replay <k> marked <n> changed <c> raw-end <h>
 * raw-lanes <h>` */
typedef struct {
    uint64_t k, marked, changed;
    const char *raw_end, *raw_lanes;
} replay_t;

typedef struct {
    int kind, fmt;
    const char *image, *digest, *stream[3], *output;
    uint64_t lanes, steps, S;
    seg_t *chain;
    unsigned n_hslots, *hslots;
    int has_depth;
    uint32_t depth;                 /* its `scratch-depth` parameter */
    /* version 2: its source lines, each a token as written ("Sources") */
    int has_source;                 /* `source <digest>`, not `source none` */
    const char *src_digest, *src_name, *graph;
    int has_compiler;               /* `compiler <name> <n> <target>` */
    const char *comp_name, *comp_ver, *comp_target;
    uint64_t n_sparams;
    const char **sp_name, **sp_lit;
    int lane_flags;                 /* `lane-flags yes` */
    uint64_t n_replays;
    replay_t *replays;              /* segments increasing */
    long long replays_line;         /* its `replays` line */
} run_t;

/* version 2: a `replay-method` line */
typedef struct {
    uint64_t run;
    const char *image;              /* NULL for `golden`, else the digest */
    long long line;
} method_t;

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
    int v2;                         /* the version-2 reader read it */
    /* version 2's header: each a token as written, a text in its one
     * spelling or a word; `writer` and `compiler-build` their tokens
     * after the key, joined */
    const char *profile, *language, *dev_platform, *dev_xrt, *dev_clock,
               *dev_serial, *writer_runtime, *certificate_id, *issuer,
               *issuer_key, *host_os, *host_arch, *started, *finished,
               *issued, *supersedes;
    char *writer, *compiler_build;
    uint64_t n_methods;
    method_t *methods;
    uint64_t n_env;
    const char **env_name, **env_value;
    const char *generator;          /* NULL for `initial given` */
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

/* Version 2's keys, in their one order (cert2._ORDER). The identity lines
 * keep version 1's ranks, so the identity's reader serves both. */
enum { K2_CFT, K2_MODE, K2_SALTC, K2_BUILD, K2_BACKEND, K2_XCLBIN,
       K2_VERSION, K2_CAPS, K2_TILES, K2_PROFILE, K2_LANGUAGE, K2_DPLATFORM,
       K2_DXRT, K2_DCLOCK, K2_DSERIAL, K2_WRITER, K2_WRUNTIME, K2_CBUILD,
       K2_RMETHODS, K2_RMETHOD, K2_CERTID, K2_ISSUER, K2_ISSUERKEY,
       K2_HOSTOS, K2_HOSTARCH, K2_STARTED, K2_FINISHED, K2_ISSUED,
       K2_SUPERSEDES, K2_ENVIRONMENT, K2_ENV, K2_INITIAL, K2_RUNS, K2_RUN,
       K2_PFORMAT, K2_PIMAGE, K2_PDIGEST, K2_SOURCE, K2_SNAME, K2_GRAPH,
       K2_COMPILER, K2_SPARAMS, K2_SPARAM, K2_LANES, K2_STEPS, K2_SA, K2_SB,
       K2_SC, K2_PARAMS, K2_PARAM, K2_LANEFLAGS, K2_SEGMENTS, K2_SEGMENT,
       K2_REPLAYS, K2_REPLAY, K2_OUTPUT, K2_ACCURACY, K2_ENTRY, K2_KIND,
       K2_USES, K2_SCOPE, K2_QUANTITY, K2_TERM, K2_VALUE, K2_END, K2_HASH,
       N_KEYS2 };

static const char *const KEY2[N_KEYS2] = {
    "cft-certificate", "mode", "salt-commitment", "build-id", "backend",
    "device-xclbin", "device-version", "device-caps", "device-tiles",
    "profile", "language", "device-platform", "device-xrt", "device-clock",
    "device-serial", "writer", "writer-runtime", "compiler-build",
    "replay-methods", "replay-method", "certificate-id", "issuer",
    "issuer-key", "host-os", "host-arch", "started", "finished", "issued",
    "supersedes", "environment", "env", "initial", "runs",
    "run", "program-format", "program-image", "program-digest", "source",
    "source-name", "graph", "compiler", "source-params", "source-param",
    "lanes", "steps", "stream-a", "stream-b", "stream-c", "parameters",
    "parameter", "lane-flags", "segments", "segment", "replays", "replay",
    "output", "accuracy", "entry", "kind", "uses", "scope", "quantity",
    "term", "value", "end", "hash" };

/* A grammar: its keys by rank, and the ranks of the four lines that begin
 * a block. Every rule of "The strict reader" for a line that is not the
 * one expected reads them from here, so both versions share the rules. */
typedef struct {
    const char *const *key;
    int n;
    int run, accuracy, entry, end;
    int version;
} grammar_t;

static const grammar_t G1 = { KEY, N_KEYS, KEY_RUN, KEY_ACCURACY, KEY_ENTRY,
                              KEY_END, 1 };
static const grammar_t G2 = { KEY2, N_KEYS2, K2_RUN, K2_ACCURACY, K2_ENTRY,
                              K2_END, 2 };

/* the header 0, a run 1, the accuracy line 2, an entry 3, end 4, hash 5 */
static int block_type(const grammar_t *g, int k)
{
    return k < g->run ? 0 : k < g->accuracy ? 1 : k == g->accuracy ? 2
         : k < g->end ? 3 : k == g->end ? 4 : 5;
}

static int is_starter(const grammar_t *g, int k)
{
    return k == g->run || k == g->accuracy || k == g->entry || k == g->end;
}

static int is_repeating(const grammar_t *g, int k)
{
    return k == g->run || k == g->entry;
}

typedef struct {
    char **tok;
    size_t ntok;
    int key;                        /* its rank, or -1 for no key of its
                                     * version */
} line_t;

typedef struct {
    line_t *L;
    size_t n, pos;
    int block;
    const grammar_t *g;
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
        for (k = 0; k < R->g->n; k++)
            if (!strcmp(R->L[ln].tok[0], R->g->key[k]))
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
        if (i > R->pos && is_starter(R->g, k))
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
    const grammar_t *g = R->g;
    int k, t;
    if (R->pos >= R->n)
        refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is missing: "
               "the body ends first", CUR(R), g->key[expected]);
    k = R->L[R->pos].key;
    t = block_type(g, k);
    if (is_starter(g, k)) {
        if (t > R->block || (t == R->block && is_repeating(g, k)))
            refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is "
                   "missing: '%s' begins a later block here", CUR(R),
                   g->key[expected], g->key[k]);
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' has no "
               "place here: its block is already read, and '%s' belongs here",
               CUR(R), g->key[k], g->key[expected]);
    }
    if (t < R->block || (t == R->block && (is_starter(g, expected) ||
                                          k < expected)))
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' has no "
               "place here: its place is earlier, and '%s' belongs here",
               CUR(R), g->key[k], g->key[expected]);
    if (in_block_rest(R, expected))
        refuse("line-order", AT_LINE(CUR(R)), "line %lld: '%s' comes before "
               "'%s', which belongs first", CUR(R), g->key[k],
               g->key[expected]);
    refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s' is missing; '%s' "
           "is here instead", CUR(R), g->key[expected], g->key[k]);
}

static line_t *expect(rdr_t *R, int key, long ntok)
{
    line_t *l;
    if (R->pos >= R->n || R->L[R->pos].key != key)
        classify(R, key);
    l = &R->L[R->pos];
    if (ntok >= 0 && l->ntok != (size_t)ntok)
        malformed(CUR(R), "'%s' takes %ld value%s, not %lu", R->g->key[key],
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
    uint64_t n = rd_dec(l->tok[1], R->g->key[key], minimum, DEC_MAX, i);
    uint64_t have = 0;
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
               "line%s follow", i, R->g->key[key], (unsigned long long)n,
               (unsigned long long)have, R->g->key[member],
               have != 1 ? "s" : "");
    return n;
}

/* the group member here must carry index `want` */
static void member_index(rdr_t *R, int key, uint64_t want, int stop1,
                         int stop2, int consecutive)
{
    const char *kn = R->g->key[key];
    line_t *l;
    uint64_t got, v;
    size_t j;
    if (R->pos >= R->n || R->L[R->pos].key != key)
        classify(R, key);
    l = &R->L[R->pos];
    if (l->ntok < 2 || !index_of(l->tok[1], &got))
        malformed(CUR(R), "'%s' needs its index first: a decimal integer in "
                  "its one spelling, at most 2^63 - 1", kn);
    if (got == want)
        return;
    if (got < want)
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s %llu' "
               "again, where '%s %llu' belongs", CUR(R), kn,
               (unsigned long long)got, kn, (unsigned long long)want);
    for (j = R->pos + 1; j < R->n; j++) {
        int k = R->L[j].key;
        if ((consecutive && k != key) || k == stop1 || k == stop2)
            break;
        if (k == key && R->L[j].ntok > 1 && index_of(R->L[j].tok[1], &v) &&
            v == want)
            refuse("line-order", AT_LINE(CUR(R)), "line %lld: '%s %llu' "
                   "comes before '%s %llu', which belongs first", CUR(R),
                   kn, (unsigned long long)got, kn,
                   (unsigned long long)want);
    }
    refuse("line-missing", AT_LINE(CUR(R)), "line %lld: '%s %llu' is "
           "missing; '%s %llu' is here instead", CUR(R), kn,
           (unsigned long long)want, kn, (unsigned long long)got);
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
        rd_dec(v, R->g->key[key], 1, DEC_MAX, PREV(R));
        return v;
    }
    malformed(PREV(R), "'%s' '%.80s' is not %s%s%s", R->g->key[key], v,
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

/* a half-step run's line, `run <i> half-step h-slots <n> <slot> ...`, its
 * kind already read: the count, then the slots, each below a bank's reach
 * and strictly increasing (both versions) */
static void read_hslots(run_t *run, uint64_t i, const line_t *l, long long ln)
{
    uint64_t n, have;
    size_t j;
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
}

/* a run's `parameters <p>` and its p lines, names strictly increasing in
 * byte order, `scratch-depth` held to a depth (both versions) */
static void read_parameters(rdr_t *R, run_t *run, int key_params,
                            int key_param)
{
    uint64_t P = count_line(R, key_params, key_param, 0, 1, -1, -1), k;
    const char *prev_name = NULL;
    for (k = 0; k < P; k++) {
        int c;
        uint64_t pv;
        line_t *l = expect(R, key_param, 3);
        long long ln = PREV(R);
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
}

/* a run's program format, held to this build's ceiling (both versions) */
static int read_format(rdr_t *R, int key, uint64_t i)
{
    static const char *const LADDER[4] = { "fp32", "fp64", "fp128", "fp256" };
    /* each line taken, THEN read at its number: an argument list's order
     * of evaluation is unspecified, and PREV(R) beside expect() read the
     * line before it (found by the gate: 27 lines off by one) */
    const char *v = take(R, key);
    int fmt = rd_word(v, LADDER, 4, "the program format", PREV(R));
    /* a format this build's library does not carry (CFT_MAX_FORMAT):
     * refused by the build's name, here, where the format is read, and
     * never later as an image that does not load - which would name an
     * input as not the one certified when the cause is the build */
    if (fmt > CFT_MAX_FORMAT)
        refuse("build-format", AT_LINE(PREV(R)), "line %lld: run %llu is "
               "%s, and this build's library carries formats up to %s "
               "(CFT_MAX_FORMAT=%d); it refuses rather than audit it "
               "differently", PREV(R), (unsigned long long)i,
               FMT[fmt].name, FMT[CFT_MAX_FORMAT].name, CFT_MAX_FORMAT);
    return fmt;
}

static void read_run(rdr_t *R, cert_t *C, uint64_t i)
{
    run_t *run = &C->runs[i];
    line_t *l;
    long long ln;
    uint64_t k;
    const char *v;

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
        read_hslots(run, i, l, ln);
    } else {
        malformed(ln, "run kind '%.40s' is not main, half-step or wider",
                  l->tok[2]);
    }
    run->fmt = read_format(R, KEY_PFORMAT, i);
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
    read_parameters(R, run, KEY_PARAMS, KEY_PARAM);
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
    /* cx_rat_parse holds the page's order: the spelling, then the digits
     * against the width rule FIRST - before zero's spelling and before any
     * gcd (P3's design, approved 2026-09-29) - so that no token past 1,023
     * bits is ever held, here or in the golden reader; then zero's one
     * spelling, and last lowest terms */
    char why[256];
    int st = cx_rat_parse(tok, q, what, why, sizeof why);
    if (st == CX_MALFORMED)
        malformed(line, "%s", why);
    if (st == CX_WIDTH)
        refuse("width", AT_LINE(line), "line %lld: %s", line, why);
    if (st)
        internal(why, CFT_ERR_INTERNAL);
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

/* (an element's order key, order_kind, is cert_exact.h's) */

/* A value's format word, and a format this build's library carries. The
 * value's decimals and any rounding into its format are the library's
 * (cft_to_decimal_char, cft_from_hex_char), so a format above
 * CFT_MAX_FORMAT is refused by the build's name here, at the word and
 * before the rest of its line - never an internal error at its decimal
 * (verifier-A1's second finding, in a CFT_MAX_FORMAT=2 build with
 * CFT_BN_LIMBS=64; the lead's decision, 2026-09-29). */
static int value_format(const char *tok, uint64_t j, long long ln)
{
    static const char *const LADDER[4] = { "fp32", "fp64", "fp128", "fp256" };
    int f = rd_word(tok, LADDER, 4, "the value's format", ln);
    if (f > CFT_MAX_FORMAT)
        refuse("build-format", AT_LINE(ln), "line %lld: entry %llu's value is "
               "stated in %s, and this build's library carries formats up to "
               "%s (CFT_MAX_FORMAT=%d); its decimals and its rounding are the "
               "library's, so it refuses rather than audit it differently",
               ln, (unsigned long long)j, FMT[f].name,
               FMT[CFT_MAX_FORMAT].name, CFT_MAX_FORMAT);
    return f;
}

/* An entry's keys in a grammar, and how many methods it names: version 1's
 * three, or version 2's four with `wider-source` */
typedef struct {
    int entry, kind, uses, scope, quantity, term, value, end, methods;
} ekeys_t;

static const ekeys_t EK1 = { KEY_ENTRY, KEY_KIND, KEY_USES, KEY_SCOPE,
                             KEY_QUANTITY, KEY_TERM, KEY_VALUE, KEY_END, 3 };
static const ekeys_t EK2 = { K2_ENTRY, K2_KIND, K2_USES, K2_SCOPE,
                             K2_QUANTITY, K2_TERM, K2_VALUE, K2_END, 4 };

static void read_value(rdr_t *R, value_t *v, uint64_t j, const ekeys_t *K)
{
    line_t *l = expect(R, K->value, -1);
    long long ln = PREV(R);
    const char *form = l->ntok > 1 ? l->tok[1] : "";
    if (!strcmp(form, "exact") && l->ntok == 3) {
        v->form = V_EXACT;
        read_rational(l->tok[2], &v->exact, "the value", ln);
        return;
    }
    if (!strcmp(form, "rounded") && l->ntok == 6) {
        v->form = V_ROUNDED;
        v->fmt = value_format(l->tok[2], j, ln);
        v->rnd = rd_word(l->tok[3], RND_NAME, 5, "the rounding direction", ln);
        read_element(v->fmt, l->tok[4], l->tok[5], "the value", v->bits, ln);
        return;
    }
    if (!strcmp(form, "enclosed") && l->ntok == 7) {
        int e;
        rat a, b;
        v->form = V_ENCLOSED;
        v->fmt = value_format(l->tok[2], j, ln);
        read_element(v->fmt, l->tok[3], l->tok[4], "the lower end", v->lo, ln);
        read_element(v->fmt, l->tok[5], l->tok[6], "the upper end", v->hi, ln);
        /* each finite end against the width rule, the lower first: the
         * writer's check too (cx_end_in_rule) */
        for (e = 0; e < 2; e++) {
            char why[200];
            if (cx_end_in_rule(v->fmt, e ? v->hi : v->lo,
                               e ? "upper" : "lower", why, sizeof why))
                refuse("width", AT_LINE(ln), "%s", why);
        }
        {
            int kl = order_kind(v->fmt, v->lo), kh = order_kind(v->fmt, v->hi);
            int above = kl > kh, c = 0;
            if (kl == 1 && kh == 1) {
                elem_t x, y;
                decode(v->fmt, v->lo, &x);
                decode(v->fmt, v->hi, &y);
                /* each end was held to the rule just above */
                if (rat_of_elem(&a, &x) || rat_of_elem(&b, &y) ||
                    rat_cmp(&a, &b, &c))
                    internal("an enclosure's two ends, compared",
                             CFT_ERR_INTERNAL);
                above = c > 0;
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

static void read_entry(rdr_t *R, cert_t *C, uint64_t j, const ekeys_t *K)
{
    entry_t *E = &C->entries[j];
    line_t *l;
    int kind;
    long long ln;
    const char *v;

    member_index(R, K->entry, j, K->end, -1, 0);
    l = expect(R, K->entry, 3);
    R->block = 3;
    E->method = rd_word(l->tok[2], METHOD_NAME, K->methods, "the method",
                        PREV(R));
    v = take(R, K->kind);
    kind = rd_word(v, KINDS, 3, "the kind", PREV(R));
    if (kind != METHOD_KIND[E->method]) {
        char why[96] = "";
        if (kind == 0)
            snprintf(why, sizeof why, "; a bound needs a rigorous "
                     "remainder, and no version-%d method has one",
                     R->g->version);
        refuse("accuracy-kind", AT_LINE(PREV(R)), "line %lld: entry %llu: the "
               "kind of %s is %s, not %s%s", PREV(R), (unsigned long long)j,
               METHOD_NAME[E->method], KINDS[METHOD_KIND[E->method]],
               KINDS[kind], why);
    }
    v = take(R, K->uses);
    E->uses = rd_dec(v, "the run used", 0, DEC_MAX, PREV(R));
    l = expect(R, K->scope, -1);
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
        l = expect(R, K->quantity, -1);
        if (l->ntok != 4 || strcmp(l->tok[2], "terms") != 0)
            malformed(ln, "'quantity <label> terms <n>'");
        if (!name_ok(l->tok[1]))
            malformed(ln, "label '%.80s' is not [a-z][a-z0-9-]*, at most 64",
                      l->tok[1]);
        t = rd_dec(l->tok[3], "the term count", 1, MAX_TERMS, ln);
        for (p = R->pos; p < R->n && R->L[p].key == K->term; p++)
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
            l = expect(R, K->term, -1);
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
    read_value(R, &E->value, j, K);
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
        /* (a body under exactly `cft-certificate 2` never comes here: the
         * dispatch sent it to version 2's reader) */
        if (first->ntok == 2 && dec_spelling(first->tok[1]))
            refuse("version", AT_LINE(1), "this is 'cft-certificate %.40s%s', "
                   "and this reader speaks versions 1 and 2", first->tok[1],
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
            read_entry(R, C, r, &EK1);
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

/* ---- version 2's strict reader ("Version 2's strict reader") ----------
 *
 * Version 1's rules for counts, indices, a line not the one expected and
 * values (the helpers above, over G2), and version 2's lines in their
 * order. cert2._Reader is the authority, check for check. */

/* a line holding a text or one of `words` (cert2._Reader.text_or) */
static const char *rd_text_or(rdr_t *R, int key, const char *const *words,
                              int nw)
{
    const char *v = take(R, key);
    long long ln = PREV(R);
    if (word_index(v, words, nw) >= 0)
        return v;
    if (is_word(v))
        malformed(ln, "'%s' takes %s%s%s or a text; the word '%s' does not "
                  "stand here", R->g->key[key], words[0], nw > 1 ? ", " : "",
                  nw > 1 ? words[nw - 1] : "", v);
    if (!text_ok(v))
        malformed(ln, "'%s' '%.80s' is not a text in its one spelling: 1 to "
                  "255 characters, each byte from 0x21 to 0x7E but '%%' as "
                  "itself and every other '%%' and two uppercase hex digits, "
                  "UTF-8", R->g->key[key], v);
    return v;
}

/* a version, or one of `words` (cert2._Reader.version_or) */
static const char *rd_version_or(rdr_t *R, int key, const char *const *words,
                                 int nw)
{
    const char *v = take(R, key);
    uint64_t a, b;
    if (word_index(v, words, nw) >= 0 || version_of(v, &a, &b))
        return v;
    malformed(PREV(R), "'%s' '%.80s' is not a version - a major, then '.' "
              "and a minor where the minor is not 0, no leading zeros - nor "
              "a word it takes", R->g->key[key], v);
}

/* build-id's grammar after its key: commit=, tracked=, untracked= */
static int build_ok(char *const *t)
{
    return build_commit_ok(t[0]) &&
           (!strcmp(t[1], "tracked=clean") ||
            !strcmp(t[1], "tracked=modified")) &&
           (!strcmp(t[2], "untracked=none") ||
            !strcmp(t[2], "untracked=present"));
}

/* `compiler-build`: a build in build-id's grammar, `none` or `unknown` */
static char *rd_build_or(rdr_t *R, int key)
{
    line_t *l = expect(R, key, -1);
    if (l->ntok == 2 && (!strcmp(l->tok[1], "none") ||
                         !strcmp(l->tok[1], "unknown")))
        return joined(l->tok + 1, 1);
    if (l->ntok == 4 && build_ok(l->tok + 1))
        return joined(l->tok + 1, 3);
    malformed(PREV(R), "'%s' is a build in cft_build_id()'s grammar - "
              "'commit=<40 or 64 lowercase hex> tracked=<clean|modified> "
              "untracked=<none|present>' - or none or unknown",
              R->g->key[key]);
}

static const char *rd_time_or_unknown(rdr_t *R, int key)
{
    const char *v = take(R, key);
    if (!strcmp(v, "unknown") || time_ok(v))
        return v;
    malformed(PREV(R), "'%s' '%.80s' is not a time - YYYY-MM-DDTHH:MM:SSZ, "
              "UTC, a real date, seconds 00 to 59 - nor 'unknown'",
              R->g->key[key], v);
}

/* "The times": each pair of known times in their order, checked as the
 * later is read, at its line (cert2._Reader.provenance_order) */
static void provenance_order(const rdr_t *R, const char *later,
                             const char *later_name, const char *e1,
                             const char *n1, const char *e2, const char *n2)
{
    const char *ev[2], *en[2];
    int i;
    ev[0] = e1;
    en[0] = n1;
    ev[1] = e2;
    en[1] = n2;
    if (!strcmp(later, "unknown"))
        return;
    for (i = 0; i < 2; i++)
        if (ev[i] && strcmp(ev[i], "unknown") != 0 &&
            strcmp(ev[i], later) > 0)
            refuse("provenance-order", AT_LINE(PREV(R)), "line %lld: '%s' is "
                   "after '%s': a run starts before it finishes, and a "
                   "certificate is issued after its runs", PREV(R), en[i],
                   later_name);
}

static void unhex32(const char *h, uint8_t *out)
{
    size_t i;
    for (i = 0; i < 32; i++)
        out[i] = (uint8_t)(hexval(h[2 * i]) << 4 | hexval(h[2 * i + 1]));
}

/* `replay-methods <n>`, then its lines, runs strictly increasing */
static void read_methods(rdr_t *R, cert_t *C)
{
    uint64_t n = count_line(R, K2_RMETHODS, K2_RMETHOD, 0, 1, -1, -1), i;
    C->methods = (method_t *)xalloc((size_t)n, sizeof *C->methods);
    for (i = 0; i < n; i++) {
        line_t *l = expect(R, K2_RMETHOD, -1);
        long long ln = PREV(R);
        method_t *m = &C->methods[i];
        uint64_t r;
        if (l->ntok == 3 && !strcmp(l->tok[2], "golden"))
            m->image = NULL;
        else if (l->ntok == 4 && !strcmp(l->tok[2], "image"))
            m->image = rd_hex(l->tok[3], 64, "a replay image's digest", ln);
        else
            malformed(ln, "'replay-method <run> golden' or 'replay-method "
                      "<run> image <digest>'");
        r = rd_dec(l->tok[1], "a replay method's run", 0, DEC_MAX, ln);
        if (i && r <= C->methods[i - 1].run) {
            if (r == C->methods[i - 1].run)
                refuse("line-unexpected", AT_LINE(ln), "line %lld: a replay "
                       "method for run %llu again", ln, (unsigned long long)r);
            refuse("line-order", AT_LINE(ln), "line %lld: the replay method "
                   "for run %llu comes after run %llu's; runs are in "
                   "increasing order", ln, (unsigned long long)r,
                   (unsigned long long)C->methods[i - 1].run);
        }
        m->run = r;
        m->line = ln;
    }
    C->n_methods = n;
}

/* `environment <n>`, then its `env` lines: a name of the writer's list,
 * names strictly increasing, each value a text */
static void read_environment(rdr_t *R, cert_t *C)
{
    uint64_t n = count_line(R, K2_ENVIRONMENT, K2_ENV, 0, 1, -1, -1), i;
    C->env_name = (const char **)xalloc((size_t)n, sizeof *C->env_name);
    C->env_value = (const char **)xalloc((size_t)n, sizeof *C->env_value);
    for (i = 0; i < n; i++) {
        line_t *l = expect(R, K2_ENV, 3);
        long long ln = PREV(R);
        size_t e;
        int listed = 0, c;
        if (!env_name_ok(l->tok[1]))
            malformed(ln, "variable name '%.80s' is not [A-Z][A-Z0-9_]*, at "
                      "most 64", l->tok[1]);
        for (e = 0; e < sizeof ENVIRONMENT_NAMES / sizeof ENVIRONMENT_NAMES[0];
             e++)
            if (!strcmp(l->tok[1], ENVIRONMENT_NAMES[e]))
                listed = 1;
        if (!listed)
            malformed(ln, "variable %s is not one of the writer's list, the "
                      "variables libcft and cft-segrun read: a certificate "
                      "names those alone", l->tok[1]);
        if (i && (c = strcmp(l->tok[1], C->env_name[i - 1])) <= 0) {
            if (c == 0)
                refuse("line-unexpected", AT_LINE(ln), "line %lld: variable "
                       "%s again", ln, l->tok[1]);
            refuse("line-order", AT_LINE(ln), "line %lld: variable %s comes "
                   "after %s; names are in increasing order", ln, l->tok[1],
                   C->env_name[i - 1]);
        }
        if (!text_ok(l->tok[2]))
            malformed(ln, "variable %s's value is not a text in its one "
                      "spelling", l->tok[1]);
        C->env_name[i] = l->tok[1];
        C->env_value[i] = l->tok[2];
    }
    C->n_env = n;
}

/* `initial given`, or `initial generator <name> <text> ...` */
static void read_initial(rdr_t *R, cert_t *C)
{
    line_t *l = expect(R, K2_INITIAL, -1);
    long long ln = PREV(R);
    size_t a;
    if (l->ntok == 2 && !strcmp(l->tok[1], "given")) {
        C->generator = NULL;
        return;
    }
    if (l->ntok >= 3 && !strcmp(l->tok[1], "generator")) {
        if (!name_ok(l->tok[2]) || is_word(l->tok[2]))
            malformed(ln, "generator name '%.80s' is not [a-z][a-z0-9-]*, at "
                      "most 64, or is one of the words (none, unknown, "
                      "withheld, given)", l->tok[2]);
        if (l->ntok - 3 > 16)
            malformed(ln, "a generator takes at most 16 arguments");
        for (a = 3; a < l->ntok; a++)
            if (!text_ok(l->tok[a]))
                malformed(ln, "generator argument '%.80s' is not a text in "
                          "its one spelling", l->tok[a]);
        C->generator = l->tok[2];
        return;
    }
    malformed(ln, "'initial given', or 'initial generator <name> <text> "
              "...'");
}

/* the header's new lines, in their order (cert2._Reader.provenance) */
static void read_provenance(rdr_t *R, cert_t *C)
{
    static const char *const NU[2] = { "none", "unknown" };
    static const char *const U[1] = { "unknown" };
    static const char *const NUW[3] = { "none", "unknown", "withheld" };
    static const char *const N[1] = { "none" };
    static const char *const NW[2] = { "none", "withheld" };
    static const char *const UW[2] = { "unknown", "withheld" };
    line_t *l;
    long long ln;
    const char *v;

    C->profile = rd_version_or(R, K2_PROFILE, U, 1);
    C->language = rd_version_or(R, K2_LANGUAGE, NU, 2);
    C->dev_platform = rd_text_or(R, K2_DPLATFORM, NU, 2);
    C->dev_xrt = rd_text_or(R, K2_DXRT, NU, 2);
    v = take(R, K2_DCLOCK);
    if (word_index(v, NU, 2) < 0)
        rd_dec(v, "the device clock in Hz", 1, DEC_MAX, PREV(R));
    C->dev_clock = v;
    C->dev_serial = rd_text_or(R, K2_DSERIAL, NUW, 3);
    l = expect(R, K2_WRITER, -1);
    ln = PREV(R);
    if (l->ntok == 2 && !strcmp(l->tok[1], "unknown")) {
        C->writer = joined(l->tok + 1, 1);
    } else if ((l->ntok == 3 || l->ntok == 5) && name_ok(l->tok[1]) &&
               !is_word(l->tok[1])) {
        if (l->ntok == 3 && !strcmp(l->tok[2], "unknown"))
            C->writer = joined(l->tok + 1, 2);
        else if (l->ntok == 5 && build_ok(l->tok + 2))
            C->writer = joined(l->tok + 1, 4);
        else
            malformed(ln, "'writer <name> <build>': the build in "
                      "cft_build_id()'s grammar, or 'unknown'");
    } else {
        malformed(ln, "'writer unknown', or 'writer <name> <build>' with a "
                  "name of [a-z][a-z0-9-]*, at most 64, that is not one of "
                  "the words");
    }
    C->writer_runtime = rd_text_or(R, K2_WRUNTIME, NU, 2);
    C->compiler_build = rd_build_or(R, K2_CBUILD);
    read_methods(R, C);
    C->certificate_id = rd_text_or(R, K2_CERTID, N, 1);
    C->issuer = rd_text_or(R, K2_ISSUER, NW, 2);
    v = take(R, K2_ISSUERKEY);
    ln = PREV(R);
    if (strcmp(v, "none") != 0) {
        uint8_t key[32];
        if (!hex_exact(v, 64))
            malformed(ln, "'issuer-key' '%.80s' is not an Ed25519 public key "
                      "- 64 lowercase hex digits - nor 'none'", v);
        unhex32(v, key);
        /* cert2.key_problem, wherever a key is read: no point is no key
         * (`malformed` here), and one of small order vouches for nothing
         * (`signer`: verifier-VCV2B; the lead's decision, 2026-10-02) */
        switch (ed25519_key_check(key)) {
        case ED25519_KEY_NO_POINT:
            malformed(ln, "'issuer-key' %s: it encodes no point of the "
                      "curve, so it is no Ed25519 public key", v);
        case ED25519_KEY_SMALL_ORDER:
            refuse("signer", AT_LINE(ln), "line %lld: 'issuer-key' %s: a key "
                   "of small order ([8]A the identity): under it a signature "
                   "nobody made verifies for every message, so no holder "
                   "vouches by it", ln, v);
        default:
            break;
        }
    }
    C->issuer_key = v;
    C->host_os = rd_text_or(R, K2_HOSTOS, UW, 2);
    C->host_arch = rd_text_or(R, K2_HOSTARCH, UW, 2);
    C->started = rd_time_or_unknown(R, K2_STARTED);
    C->finished = rd_time_or_unknown(R, K2_FINISHED);
    provenance_order(R, C->finished, "finished", C->started, "started", NULL,
                     NULL);
    C->issued = rd_time_or_unknown(R, K2_ISSUED);
    provenance_order(R, C->issued, "issued", C->finished, "finished",
                     C->started, "started");
    v = take(R, K2_SUPERSEDES);
    if (strcmp(v, "none") != 0 && !hex_exact(v, 64))
        malformed(PREV(R), "'supersedes' '%.80s' is not a body hash - 64 "
                  "lowercase hex digits - nor 'none'", v);
    C->supersedes = v;
    read_environment(R, C);
    read_initial(R, C);
}

/* a run's source lines (cert2._Reader.source) */
static void read_source(rdr_t *R, const cert_t *C, run_t *run)
{
    static const char *const N[1] = { "none" };
    const char *v = take(R, K2_SOURCE), *prev = NULL;
    long long ln = PREV(R);
    line_t *l;
    uint64_t P, k;
    if (!strcmp(v, "none")) {
        run->has_source = 0;
        return;
    }
    run->src_digest = rd_hex(v, 64, "the source's SHA-256", ln);
    if (!strcmp(C->language, "none"))
        malformed(ln, "this run names a source, and the certificate's "
                  "language is 'none', which says no run names one: a "
                  "certificate whose runs name a source states the "
                  "language's version, or 'unknown'");
    run->has_source = 1;
    run->src_name = rd_text_or(R, K2_SNAME, N, 1);
    v = take(R, K2_GRAPH);
    run->graph = rd_hex(v, 64, "the step graph's SHA-256", PREV(R));
    l = expect(R, K2_COMPILER, -1);
    ln = PREV(R);
    if (l->ntok == 2 && !strcmp(l->tok[1], "none")) {
        run->has_compiler = 0;
    } else if (l->ntok == 4 && name_ok(l->tok[1]) && !is_word(l->tok[1])) {
        rd_dec(l->tok[2], "the compiler's output version", 0, DEC_MAX, ln);
        if (!text_ok(l->tok[3]))
            malformed(ln, "the compiler's target '%.80s' is not a text in its "
                      "one spelling", l->tok[3]);
        run->has_compiler = 1;
        run->comp_name = l->tok[1];
        run->comp_ver = l->tok[2];
        run->comp_target = l->tok[3];
    } else {
        malformed(ln, "'compiler none', or 'compiler <name> <output version> "
                  "<target>'");
    }
    P = count_line(R, K2_SPARAMS, K2_SPARAM, 0, 1, -1, -1);
    run->sp_name = (const char **)xalloc((size_t)P, sizeof *run->sp_name);
    run->sp_lit = (const char **)xalloc((size_t)P, sizeof *run->sp_lit);
    for (k = 0; k < P; k++) {
        int c;
        l = expect(R, K2_SPARAM, 3);
        ln = PREV(R);
        if (!lang_name_ok(l->tok[1]))
            malformed(ln, "source param '%.80s' is not a name of the "
                      "language: a letter or '_', then letters, digits and "
                      "'_'", l->tok[1]);
        if (prev && (c = strcmp(l->tok[1], prev)) <= 0) {
            if (c == 0)
                refuse("line-unexpected", AT_LINE(ln), "line %lld: source "
                       "param %s again", ln, l->tok[1]);
            refuse("line-order", AT_LINE(ln), "line %lld: source param %s "
                   "comes after %s; names are in increasing byte order", ln,
                   l->tok[1], prev);
        }
        run->sp_name[k] = l->tok[1];
        run->sp_lit[k] = l->tok[2];
        prev = l->tok[1];
    }
    run->n_sparams = P;
}

/* `replays <m>`, then its lines (cert2._Reader.replays): the form rules
 * at the `replays` line, `replay-lane-flags` first, after the count */
static void read_replays(rdr_t *R, run_t *run, uint64_t i)
{
    long long at0 = CUR(R);
    uint64_t m = count_line(R, K2_REPLAYS, K2_REPLAY, 0, 1, -1, -1), j;
    run->replays_line = at0;
    if (m && !run->lane_flags)
        refuse("replay-lane-flags", AT_LINE(at0), "line %lld: run %llu has "
               "replay lines and says lane-flags no: a run whose image can "
               "mark asks for the block, since a mark alone does not say "
               "which lane", at0, (unsigned long long)i);
    if (m && !run->has_source)
        refuse("replay-source", AT_LINE(at0), "line %lld: run %llu has replay "
               "lines and names no source: a replay is by the definition the "
               "source gives", at0, (unsigned long long)i);
    run->replays = (replay_t *)xalloc((size_t)m, sizeof *run->replays);
    for (j = 0; j < m; j++) {
        line_t *l = expect(R, K2_REPLAY, 10);
        long long ln = PREV(R);
        replay_t *x = &run->replays[j];
        if (strcmp(l->tok[2], "marked") || strcmp(l->tok[4], "changed") ||
            strcmp(l->tok[6], "raw-end") || strcmp(l->tok[8], "raw-lanes"))
            malformed(ln, "'replay <k> marked <n> changed <c> raw-end <hash> "
                      "raw-lanes <hash>'");
        x->k = rd_dec(l->tok[1], "a replay's segment", 0, run->S - 1, ln);
        if (j && x->k <= run->replays[j - 1].k) {
            if (x->k == run->replays[j - 1].k)
                refuse("line-unexpected", AT_LINE(ln), "line %lld: a replay "
                       "line for segment %llu again", ln,
                       (unsigned long long)x->k);
            refuse("line-order", AT_LINE(ln), "line %lld: the replay line for "
                   "segment %llu comes after segment %llu's; segments are in "
                   "increasing order", ln, (unsigned long long)x->k,
                   (unsigned long long)run->replays[j - 1].k);
        }
        x->marked = rd_dec(l->tok[3], "the lanes marked", 1, run->lanes, ln);
        x->changed = rd_dec(l->tok[5], "the lanes changed", 0, run->lanes,
                            ln);
        if (x->changed > x->marked)
            malformed(ln, "changed %llu is more than marked %llu: a replay "
                      "changes only lanes the machine marked",
                      (unsigned long long)x->changed,
                      (unsigned long long)x->marked);
        x->raw_end = rd_hex(l->tok[7], 64, "a raw end hash", ln);
        x->raw_lanes = rd_hex(l->tok[9], 64, "a raw lane-flags hash", ln);
    }
    run->n_replays = m;
}

static void read_run2(rdr_t *R, cert_t *C, uint64_t i)
{
    static const char *const YESNO[2] = { "yes", "no" };
    run_t *run = &C->runs[i];
    line_t *l;
    long long ln;
    uint64_t k;
    const char *v;

    member_index(R, K2_RUN, i, K2_ACCURACY, K2_END, 0);
    l = expect(R, K2_RUN, -1);
    R->block = 1;
    ln = PREV(R);
    if (l->ntok < 3)
        malformed(ln, "'run' is 'run <index> main', 'run <index> half-step "
                  "h-slots <n> ...', 'run <index> wider' or 'run <index> "
                  "wider-source'");
    if (!strcmp(l->tok[2], "main")) {
        if (i != 0 || l->ntok != 3)
            malformed(ln, "run 0, and only run 0, is 'run 0 main'");
        run->kind = K_MAIN;
    } else if (!strcmp(l->tok[2], "wider") ||
               !strcmp(l->tok[2], "wider-source")) {
        if (i == 0 || l->ntok != 3)
            malformed(ln, "'run <index> %s' is an auxiliary run, never run "
                      "0, and takes nothing more", l->tok[2]);
        run->kind = !strcmp(l->tok[2], "wider") ? K_WIDER : K_WSRC;
    } else if (!strcmp(l->tok[2], "half-step")) {
        read_hslots(run, i, l, ln);
    } else {
        malformed(ln, "run kind '%.40s' is not main, half-step, wider or "
                  "wider-source", l->tok[2]);
    }
    run->fmt = read_format(R, K2_PFORMAT, i);
    v = take(R, K2_PIMAGE);
    run->image = rd_hex(v, 64, "the image digest", PREV(R));
    v = take(R, K2_PDIGEST);
    run->digest = rd_hex(v, 64, "the program digest", PREV(R));
    read_source(R, C, run);
    v = take(R, K2_LANES);
    run->lanes = rd_dec(v, "lanes", 1, DEC_MAX, PREV(R));
    v = take(R, K2_STEPS);
    run->steps = rd_dec(v, "steps", 1, DEC_MAX, PREV(R));
    v = take(R, K2_SA);
    run->stream[0] = rd_hex(v, 64, "stream a's hash", PREV(R));
    v = take(R, K2_SB);
    run->stream[1] = rd_hex(v, 64, "stream b's hash", PREV(R));
    v = take(R, K2_SC);
    run->stream[2] = rd_hex(v, 64, "stream c's hash", PREV(R));
    read_parameters(R, run, K2_PARAMS, K2_PARAM);
    v = take(R, K2_LANEFLAGS);
    run->lane_flags = rd_word(v, YESNO, 2, "lane-flags", PREV(R)) == 0;
    run->S = count_line(R, K2_SEGMENTS, K2_SEGMENT, 1, 1, -1, -1);
    run->chain = (seg_t *)xalloc((size_t)run->S, sizeof *run->chain);
    for (k = 0; k < run->S; k++) {
        seg_t *s = &run->chain[k];
        size_t want = run->lane_flags ? 12 : 10;
        member_index(R, K2_SEGMENT, k, -1, -1, 1);
        l = expect(R, K2_SEGMENT, -1);
        ln = PREV(R);
        if (l->ntok != want)
            malformed(ln, "'segment <k> start <hash> end <hash> flags <n> "
                      "status <n>%s", run->lane_flags ? " lanes <hash>' in a "
                      "run that says lane-flags yes" : "' in a run that says "
                      "lane-flags no, with no lanes pair");
        if (strcmp(l->tok[2], "start") || strcmp(l->tok[4], "end") ||
            strcmp(l->tok[6], "flags") || strcmp(l->tok[8], "status") ||
            (run->lane_flags && strcmp(l->tok[10], "lanes")))
            malformed(ln, "'segment <k> start <hash> end <hash> flags <n> "
                      "status <n>%s'", run->lane_flags ? " lanes <hash>" : "");
        s->status = (uint32_t)rd_dec(l->tok[9], "status", 0, 0xFFFFFFFFu, ln);
        s->start = rd_hex(l->tok[3], 64, "a start hash", ln);
        s->end = rd_hex(l->tok[5], 64, "an end hash", ln);
        s->flags = (uint32_t)rd_dec(l->tok[7], "flags", 0, 31, ln);
        s->lanes = run->lane_flags ? rd_hex(l->tok[11], 64, "a lane-flags "
                                            "hash", ln) : NULL;
        if (s->status & CFT_STATUS_MARKED)
            refuse("marked", AT_LINE(ln), "line %lld: segment %llu's STATUS "
                   "carries STATUS[6], the mark: a version-2 segment is the "
                   "definition's, so every mark in it is resolved by a "
                   "replay; the machine's own values, mark and all, are "
                   "version 1's", ln, (unsigned long long)k);
    }
    read_replays(R, run, i);
    v = take(R, K2_OUTPUT);
    run->output = rd_hex(v, 64, "the output hash", PREV(R));
}

/* the runs with replay lines are exactly those the header's replay-method
 * lines name (cert2._Reader.replay_methods_hold) */
static void replay_methods_hold(const cert_t *C)
{
    uint64_t i, j;
    for (i = 0; i < C->n_methods; i++) {
        const method_t *m = &C->methods[i];
        if (m->run >= C->R || C->runs[m->run].n_replays == 0)
            refuse("replay-method", AT_LINE(m->line), "line %lld: the header "
                   "names how run %llu's replays were made, and %s", m->line,
                   (unsigned long long)m->run, m->run < C->R ? "that run has "
                   "no replay line" : "there is no such run");
    }
    for (i = 0; i < C->R; i++) {
        int named = 0;
        if (!C->runs[i].n_replays)
            continue;
        for (j = 0; j < C->n_methods; j++)
            if (C->methods[j].run == i)
                named = 1;
        if (!named)
            refuse("replay-method", AT_LINE(C->runs[i].replays_line), "line "
                   "%lld: run %llu has replay lines and the header names no "
                   "replay-method for it", C->runs[i].replays_line,
                   (unsigned long long)i);
    }
}

/* the whole of version 2's reader (cert2._Reader.certificate): the
 * dispatch sent this body here because its first line is exactly
 * `cft-certificate 2` */
static void read_certificate2(rdr_t *R, cert_t *C)
{
    line_t *l;
    size_t i;
    uint64_t r;
    long long sc_at = NONE;
    const char *mode;

    C->v2 = 1;
    for (i = 0; i < R->n; i++)
        if (R->L[i].key < 0)
            refuse("unknown-line", AT_LINE(i + 1), "line %lld: '%.80s' is not "
                   "a line of version 2", (long long)i + 1, R->L[i].tok[0]);
    R->pos = 1;
    l = expect(R, K2_MODE, 2);
    mode = l->tok[1];
    if (!strcmp(mode, "keyed"))
        C->keyed = 1;
    else if (!strcmp(mode, "open"))
        C->keyed = 0;
    else
        refuse("mode-unknown", AT_LINE(PREV(R)), "line %lld: mode '%.40s': "
               "this reader knows 'keyed' and 'open'", PREV(R), mode);
    for (i = 0; i < R->n; i++)
        if (R->L[i].key == K2_SALTC) {
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
        const char *v = take(R, K2_SALTC);
        C->commitment = rd_hex(v, 64, "the salt commitment", PREV(R));
    }
    read_identity(R, C);            /* the identity lines' ranks are v1's */
    read_provenance(R, C);
    C->R = count_line(R, K2_RUNS, K2_RUN, 1, 0, K2_ACCURACY, K2_END);
    C->runs = (run_t *)xalloc((size_t)C->R, sizeof *C->runs);
    for (r = 0; r < C->R; r++)
        read_run2(R, C, r);
    replay_methods_hold(C);
    {
        long long acc_line = CUR(R);
        C->A = count_line(R, K2_ACCURACY, K2_ENTRY, 0, 0, K2_END, -1);
        R->block = 2;
#if AUDIT_EXACT
        (void)acc_line;
        C->entries = (entry_t *)xalloc((size_t)C->A, sizeof *C->entries);
        for (r = 0; r < C->A; r++)
            read_entry(R, C, r, &EK2);
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
    expect(R, K2_END, 1);
    R->block = 4;
    if (R->pos != R->n)
        refuse("line-unexpected", AT_LINE(CUR(R)), "line %lld: '%s' after "
               "'end'; the body ends at 'end'", CUR(R),
               KEY2[R->L[R->pos].key]);
}

/* The hash line and the body's hash (cert._split_hash, and the check
 * after it): 0 with the body's length in *cut and the hash line's value,
 * the certificate's name, in `name`; 1 where there is no hash line
 * (hash-line); 2 where the hash line is not the body's (body-hash). */
static int split_hash(const uint8_t *data, size_t n, size_t *cut_out,
                      char name[65])
{
    size_t cut = 0, i, last_len;
    const uint8_t *last;
    uint8_t d[32];
    char hex[65];
    if (n == 0 || data[n - 1] != '\n')
        return 1;
    for (i = n - 1; i-- > 0;)
        if (data[i] == '\n') {
            cut = i + 1;               /* the body is data[0 .. cut) */
            break;
        }
    last = data + cut;
    last_len = n - 1 - cut;
    if (last_len != 69 || memcmp(last, "hash ", 5) != 0)
        return 1;
    for (i = 5; i < 69; i++)
        if (!is_hexl((char)last[i]))
            return 1;
    sha256_of(data, cut, d);
    hex_of(d, 32, hex);
    if (memcmp(hex, last + 5, 64) != 0)
        return 2;
    *cut_out = cut;
    memcpy(name, last + 5, 64);
    name[64] = 0;
    return 0;
}

/* Steps 1 and 2: the hash line, the body's hash, then the reader of the
 * version the dispatch chose - version 2's for a body whose first line is
 * exactly `cft-certificate 2` (decided from the file's first 18 bytes,
 * as cert.audit does, which is the same thing wherever the body reads),
 * version 1's for every other. `name` gets the certificate's name. */
static void read_all(uint8_t *data, size_t n, rdr_t *R, cert_t *C, int v2,
                     char name[65])
{
    size_t cut = 0;
    int st = split_hash(data, n, &cut, name);
    if (st == 1 && (n == 0 || data[n - 1] != '\n'))
        refuse("hash-line", NOWHERE, "the file does not end with a newline, "
               "so its last line is not a hash line");
    if (st == 1)
        refuse("hash-line", NOWHERE, "the last line must be 'hash' and 64 "
               "lowercase hex digits");
    if (st == 2)
        refuse("body-hash", NOWHERE, "the hash line is not the SHA-256 of the "
               "body: the bytes are not the ones it was written over");
    R->g = v2 ? &G2 : &G1;
    split_lines((char *)data, cut, R);
    if (v2)
        read_certificate2(R, C);
    else
        read_certificate(R, C);
}

/* ---- the command line and what it hands the audit ---------------------- */

typedef struct {
    const char *key;               /* as written */
    int valid;                     /* a run index in its one spelling */
    uint64_t r;
    const char *image_path, *bank_path, *stream_path[3], *choose;
    const char *define;            /* version 2: define[R] */
    uint8_t *image, *bank, *stream[3];
    size_t image_bytes, bank_bytes, stream_bytes[3];
} block_t;

typedef struct {
    uint64_t r, b;                 /* UINT64_MAX: past 2^63 - 1 */
    char *path;
    uint64_t size;                 /* its bytes, when it was listed */
    char *bstr;                    /* a block file's segment, as spelt: the
                                    * order cert2._check_blocks reads them in */
} statefile_t;

static block_t *BLK = NULL;
static size_t N_BLK = 0;
static statefile_t *SF = NULL;
static size_t N_SF = 0;
/* version 2: the block files a --states directory hands (lane_flags),
 * each run-<r>-segment-<k>.flags, as `b` its segment */
static statefile_t *BF = NULL;
static size_t N_BF = 0;
/* version 2: the signature file, the keyring and the superseded
 * certificate, each read whole before step 1 */
static uint8_t *SIG = NULL, *RING = NULL, *SUP = NULL;
static size_t SIG_N = 0, RING_N = 0, SUP_N = 0;

static void usage_text(FILE *f)
{
    fputs(
"cft-audit - the audit of a certificate of version 1 or 2\n"
"(docs/CERTIFICATES.md; \"The audit tool\" is the manual)\n"
"\n"
"  cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]\n"
"            [--signature SIG] [--keyring RING] [--superseded OLD]\n"
"            --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]\n"
"                    [--choose all|sample:K|K,K,...] [--define all|K,K,...]\n"
"            [--run 1 --image IMG ...] ...\n"
"  cft-audit --read --cert CERT [--salt SALT]\n"
"  cft-audit --sample SEED R S K\n"
"\n"
"  --cert CERT       the certificate\n"
"  --salt SALT       a keyed certificate's salt, 32 bytes\n"
"  --states DIR      states: DIR/run-<r>-boundary-<b>.bin, as cft-segrun\n"
"                    writes them; for version 2 also each segment's\n"
"                    per-lane flags, DIR/run-<r>-segment-<k>.flags\n"
"  --seed HEX        the sampling seed, 64 hex digits; drawn if absent\n"
"  --signature SIG   version 2: the detached signature, a .sig file\n"
"  --keyring RING    version 2: a keyring, lines 'key <64 hex> <text>'\n"
"  --superseded OLD  version 2: the certificate this one supersedes\n"
"  --run R           run R's block: its image, bank, streams and choices\n"
"  --image IMG       the run's program image\n"
"  --bank BANK       its bank, for an image that takes one\n"
"  --stream X FILE   stream X (a, b or c) of the run's lanes; +0 if absent\n"
"  --choose SPEC     all (the default), sample:K, or segments K,K,...\n"
"  --define SPEC     version 2: the definition re-run's segments, all or\n"
"                    K,K,... (this tool takes no source, so it refuses\n"
"                    source-missing there, as the golden auditor would)\n"
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

/* run-<digits>-segment-<digits>.flags, whatever the digits' spelling: a
 * version-2 block file (a raw block, -raw.flags, is not one) */
static int loosely_block(const char *name)
{
    const char *p = name;
    if (strncmp(p, "run-", 4) != 0)
        return 0;
    p += 4;
    if (*p < '0' || *p > '9')
        return 0;
    while (*p >= '0' && *p <= '9')
        p++;
    if (strncmp(p, "-segment-", 9) != 0)
        return 0;
    p += 9;
    if (*p < '0' || *p > '9')
        return 0;
    while (*p >= '0' && *p <= '9')
        p++;
    return strcmp(p, ".flags") == 0;
}

/* a file a --states directory hands, appended to its list: held to be a
 * regular file, and opened, before step 1, so that one that cannot be
 * read is `usage` before any step (verifier-A1: a directory by a
 * boundary's name was refused only at step 7, after steps 1 to 6 had
 * passed); its bytes are read at step 7, where only a file changed or
 * gone since can fail */
static void list_one(statefile_t **list, size_t *n, size_t *cap,
                     const char *dir, const char *nm, uint64_t r, uint64_t b,
                     const char *bstr, size_t blen, const char *what)
{
    statefile_t *s;
    size_t plen;
    FILE *f;
#if defined(_WIN32)
    struct _stati64 sb;
#else
    struct stat sb;
#endif
    if (*n == *cap) {
        statefile_t *g;
        *cap = *cap ? 2 * *cap : 16;
        g = (statefile_t *)xalloc(*cap, sizeof *g);
        if (*n)
            memcpy(g, *list, *n * sizeof *g);
        free(*list);
        *list = g;
    }
    s = &(*list)[*n];
    plen = strlen(dir) + strlen(nm) + 2;
    s->path = (char *)xalloc(plen, 1);
    snprintf(s->path, plen, "%s/%s", dir, nm);
    s->r = r;
    s->b = b;
    s->bstr = NULL;
    if (bstr) {
        s->bstr = (char *)xalloc(blen + 1, 1);
        memcpy(s->bstr, bstr, blen);
    }
#if defined(_WIN32)
    if (_stati64(s->path, &sb) != 0)
#else
    if (stat(s->path, &sb) != 0)
#endif
        refuse("usage", NOWHERE, "%s cannot be read (%s)", s->path,
               strerror(errno));
#if defined(_WIN32)
    if ((sb.st_mode & _S_IFMT) != _S_IFREG)
#else
    if (!S_ISREG(sb.st_mode))
#endif
        refuse("usage", NOWHERE, "%s is named as a %s and is not a file",
               s->path, what);
    f = fopen(s->path, "rb");
    if (!f)
        refuse("usage", NOWHERE, "%s cannot be read (%s)", s->path,
               strerror(errno));
    fclose(f);
    s->size = (uint64_t)sb.st_size;
    (*n)++;
}

/* The files a --states directory hands: every boundary file, and for a
 * version-2 certificate every block file too. Other files are not read,
 * and version 1 reads no block file, as it did before version 2. */
static void list_states(const char *dir, int v2)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    size_t cap = 0, bcap = 0;
    if (!d)
        refuse("usage", NOWHERE, "--states %s cannot be read as a directory "
               "(%s)", dir, strerror(errno));
    while ((e = readdir(d)) != NULL) {
        const char *nm = e->d_name, *dash, *dot;
        uint64_t r, b;
        if (loosely_boundary(nm)) {
            dash = strstr(nm + 4, "-boundary-");
            dot = strrchr(nm, '.');
            if (!parse_index_part(nm + 4, (size_t)(dash - (nm + 4)), &r) ||
                !parse_index_part(dash + 10, (size_t)(dot - (dash + 10)), &b))
                refuse("usage", NOWHERE, "--states %s holds %s, which is "
                       "named as a boundary file but not in the one spelling "
                       "of its indices (decimal, no leading zero)", dir, nm);
            list_one(&SF, &N_SF, &cap, dir, nm, r, b, NULL, 0,
                     "boundary file");
        } else if (v2 && loosely_block(nm)) {
            dash = strstr(nm + 4, "-segment-");
            dot = strrchr(nm, '.');
            if (!parse_index_part(nm + 4, (size_t)(dash - (nm + 4)), &r) ||
                !parse_index_part(dash + 9, (size_t)(dot - (dash + 9)), &b))
                refuse("usage", NOWHERE, "--states %s holds %s, which is "
                       "named as a block file but not in the one spelling of "
                       "its indices (decimal, no leading zero)", dir, nm);
            list_one(&BF, &N_BF, &bcap, dir, nm, r, b, dash + 9,
                     (size_t)(dot - (dash + 9)), "block file");
        }
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

/* Step 2, version 2: the auditor's choice of segments to run by the
 * definition (cert2._define_plan), held like its choice of re-runs: every
 * run it names a run of the certificate, and each `all` or distinct
 * segments, at least one (`choice`). -> per run, sorted; n 0 for none. */
typedef struct { uint64_t n, *segs; } dplan_t;

static dplan_t *make_define_plan(const cert_t *C)
{
    dplan_t *dp = (dplan_t *)xalloc((size_t)C->R, sizeof *dp);
    size_t i;
    for (i = 0; i < N_BLK; i++)
        if (BLK[i].define && (!BLK[i].valid || BLK[i].r >= C->R))
            refuse("choice", NOWHERE, "the definition re-run names run "
                   "'%.40s', and the certificate's runs are 0..%llu",
                   BLK[i].key, (unsigned long long)C->R - 1);
    for (i = 0; i < N_BLK; i++) {
        const char *c = BLK[i].define, *s;
        uint64_t r = BLK[i].r, S, j, n = 1;
        size_t len;
        int bad;
        dplan_t *p;
        if (!c)
            continue;
        S = C->runs[r].S;
        p = &dp[r];
        if (!strcmp(c, "all")) {
            p->segs = (uint64_t *)xalloc((size_t)S, sizeof *p->segs);
            for (j = 0; j < S; j++)
                p->segs[j] = j;
            p->n = S;
            continue;
        }
        len = strlen(c);
        bad = len == 0;
        for (j = 0; j < len; j++)
            if (c[j] == ',')
                n++;
        p->segs = (uint64_t *)xalloc((size_t)n, sizeof *p->segs);
        for (j = 0, s = c; !bad && j < n; j++) {
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
            qsort(p->segs, (size_t)n, sizeof *p->segs, cmp_u64);
            for (j = 1; j < n; j++)
                if (p->segs[j] == p->segs[j - 1])
                    bad = 1;
        }
        if (bad)
            refuse("choice", AT_RUN(r), "run %llu: the definition re-run "
                   "takes 'all' or distinct segments in 0..%llu, at least "
                   "one; '%.80s' is neither", (unsigned long long)r,
                   (unsigned long long)S - 1, c);
        p->n = n;
    }
    return dp;
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

/* ---- version 2's steps 2a and 3a --------------------------------------- */

/* printable ASCII and LF, ending in LF: a signature file's and a
 * keyring's bytes */
static int ascii_lines(const uint8_t *b, size_t n)
{
    size_t i;
    if (n == 0 || b[n - 1] != '\n')
        return 0;
    for (i = 0; i < n; i++)
        if (!((b[i] >= 0x20 && b[i] <= 0x7E) || b[i] == 0x0A))
            return 0;
    return 1;
}

/* the line [s, e) is exactly `prefix` and then `hex` lowercase hex
 * digits (hex 0: exactly `prefix`) */
static int line_is(const uint8_t *s, const uint8_t *e, const char *prefix,
                   size_t hex)
{
    size_t pl = strlen(prefix), i;
    if ((size_t)(e - s) != pl + hex || memcmp(s, prefix, pl) != 0)
        return 0;
    for (i = 0; i < hex; i++)
        if (!is_hexl((char)s[pl + i]))
            return 0;
    return 1;
}

/* A keyring (cert2.read_keyring): lines `key <64 hex> <text>`, each key
 * once, none of small order or no point. Every departure is `signer`,
 * step 2a's name for a keyring, whether or not a signature is handed.
 * -> the holder's token for `key` (64 hex), or NULL where the keyring
 * does not name it (and for a NULL key). */
static const char *read_keyring(const char *key)
{
    const uint8_t *p = RING, *end = RING + RING_N;
    const char **keys;
    char *copy;
    const char *found = NULL;
    size_t nlines = 0, i, line = 0;
    if (RING_N == 0)
        return NULL;                    /* the empty keyring names nobody */
    if (!ascii_lines(RING, RING_N))
        refuse("signer", NOWHERE, "a keyring is printable ASCII lines, each "
               "ending in LF");
    for (i = 0; i < RING_N; i++)
        if (RING[i] == '\n')
            nlines++;
    keys = (const char **)xalloc(nlines, sizeof *keys);
    copy = (char *)xalloc(RING_N + 1, 1);
    memcpy(copy, RING, RING_N);
    for (p = RING; p < end; line++) {
        const uint8_t *e = (const uint8_t *)memchr(p, '\n', (size_t)(end - p));
        size_t off = (size_t)(p - RING), len = (size_t)(e - p), t, sp = 0;
        char *ln = copy + off, *k, *holder;
        uint8_t raw[32];
        for (t = 0; t < len; t++)
            if (ln[t] == ' ')
                sp++;
        ln[len] = 0;
        if (sp != 2 || strncmp(ln, "key ", 4) != 0)
            refuse("signer", NOWHERE, "keyring line %lu: 'key <64 lowercase "
                   "hex> <text>'", (unsigned long)line + 1);
        k = ln + 4;
        holder = strchr(k, ' ');
        *holder++ = 0;
        if (!hex_exact(k, 64))
            refuse("signer", NOWHERE, "keyring line %lu: 'key <64 lowercase "
                   "hex> <text>'", (unsigned long)line + 1);
        if (!text_ok(holder))
            refuse("signer", NOWHERE, "keyring line %lu: the holder is not a "
                   "text in its one spelling", (unsigned long)line + 1);
        for (t = 0; t < line; t++)
            if (!strcmp(keys[t], k))
                refuse("signer", NOWHERE, "keyring line %lu: key %.16s... "
                       "again", (unsigned long)line + 1, k);
        unhex32(k, raw);
        switch (ed25519_key_check(raw)) {
        case ED25519_KEY_NO_POINT:
            refuse("signer", NOWHERE, "keyring line %lu: key %s: it encodes "
                   "no point of the curve, so it is no Ed25519 public key",
                   (unsigned long)line + 1, k);
        case ED25519_KEY_SMALL_ORDER:
            refuse("signer", NOWHERE, "keyring line %lu: key %s: a key of "
                   "small order ([8]A the identity): under it a signature "
                   "nobody made verifies for every message, so no holder "
                   "vouches by it", (unsigned long)line + 1, k);
        default:
            break;
        }
        keys[line] = k;
        if (key && !strcmp(k, key))
            found = holder;
        p = e + 1;
    }
    free(keys);
    return found;                       /* `copy` holds it: kept */
}

/* Step 2a (cert2._check_signature): the signature file's form, its key not
 * of small order, that it names this certificate and verifies, its key
 * against `issuer-key`, a keyring's holder against `issuer`. -> the
 * verdict's line, in `out`. */
static void check_signature(const cert_t *C, const char *name, char *out,
                            size_t cap)
{
    const uint8_t *s = SIG, *e[5];
    uint8_t key[32], sig[64], msg[TAG_SIGNATURE_LEN + 32];
    char keyhex[65];
    const char *holder;
    size_t i, nl = 0;
    if (!SIG) {
        if (RING)
            read_keyring(NULL);         /* held to its form all the same */
        snprintf(out, cap, "signature: none handed");
        return;
    }
    /* the file: exactly five lines, printable ASCII and LF */
    if (!ascii_lines(SIG, SIG_N))
        refuse("signature-format", NOWHERE, "a signature file is printable "
               "ASCII lines, each ending in LF");
    for (i = 0; i < SIG_N; i++)
        if (SIG[i] == '\n') {
            if (nl < 5)
                e[nl] = SIG + i;
            nl++;
        }
    if (nl != 5 || !line_is(s, e[0], "cft-signature 1", 0) ||
        !line_is(e[0] + 1, e[1], "scheme ed25519", 0) ||
        !line_is(e[1] + 1, e[2], "key ", 64) ||
        !line_is(e[2] + 1, e[3], "certificate ", 64) ||
        !line_is(e[3] + 1, e[4], "signature ", 128))
        refuse("signature-format", NOWHERE, "a signature file is five lines: "
               "'cft-signature 1', 'scheme ed25519', 'key <64 hex>', "
               "'certificate <64 hex>' and 'signature <128 hex>', lowercase, "
               "each ending in LF");
    memcpy(keyhex, e[1] + 1 + 4, 64);
    keyhex[64] = 0;
    unhex32(keyhex, key);
    for (i = 0; i < 64; i++)
        sig[i] = (uint8_t)(hexval((char)e[3][1 + 10 + 2 * i]) << 4 |
                           hexval((char)e[3][1 + 10 + 2 * i + 1]));
    /* a key of small order is refused before the signature is read; one
     * that encodes no point is not refused here (cert2's), and its
     * signature does not verify below */
    if (ed25519_key_check(key) == ED25519_KEY_SMALL_ORDER)
        refuse("signer", NOWHERE, "the signature file's key %s: a key of "
               "small order ([8]A the identity): under it a signature nobody "
               "made verifies for every message, so no holder vouches by it",
               keyhex);
    if (memcmp(e[2] + 1 + 12, name, 64) != 0)
        refuse("signature", NOWHERE, "the signature names the certificate "
               "%.16s..., and this one is %.16s...", (const char *)(e[2] + 13),
               name);
    /* the message: `cft-signature 1`, a NUL, the body hash's 32 bytes */
    memcpy(msg, TAG_SIGNATURE, TAG_SIGNATURE_LEN);
    unhex32(name, msg + TAG_SIGNATURE_LEN);
    if (!ed25519_verify(key, msg, sizeof msg, sig))
        refuse("signature", NOWHERE, "the signature does not verify under key "
               "%s", keyhex);
    if (strcmp(C->issuer_key, "none") != 0 && strcmp(keyhex, C->issuer_key))
        refuse("signature-key", NOWHERE, "the signature is by key %s, and the "
               "certificate names %s as the key it is to be signed with",
               keyhex, C->issuer_key);
    if (!RING) {
        snprintf(out, cap, "signature: by key %s, verified, which no keyring "
                 "handed names", keyhex);
        return;
    }
    holder = read_keyring(keyhex);
    if (!holder) {
        snprintf(out, cap, "signature: by key %s, verified, which the keyring "
                 "handed does not name", keyhex);
        return;
    }
    /* a text has one spelling, so its token is its value */
    if (!is_word(C->issuer) && strcmp(holder, C->issuer) != 0)
        refuse("signer", NOWHERE, "the keyring names key %.16s... as %s, and "
               "the certificate's issuer is %s", keyhex, holder, C->issuer);
    snprintf(out, cap, "signature: by key %s, verified, held by %s by the "
             "keyring handed", keyhex, holder);
}

/* Step 3a (cert2._check_superseded): -> the verdict's line, in `out` */
static void check_superseded(const cert_t *C, char *out, size_t cap)
{
    char got[65];
    size_t cut;
    int st;
    if (!SUP) {
        if (!strcmp(C->supersedes, "none"))
            snprintf(out, cap, "supersedes: none");
        else
            snprintf(out, cap, "supersedes %s: named, not handed - stated, "
                     "not checked", C->supersedes);
        return;
    }
    st = split_hash(SUP, SUP_N, &cut, got);
    if (st)
        refuse("supersedes", NOWHERE, "the certificate handed as the one this "
               "supersedes is not whole: %s", st == 1 ? "hash-line" :
               "body-hash");
    if (!strcmp(C->supersedes, "none") || strcmp(got, C->supersedes) != 0)
        refuse("supersedes", NOWHERE, "the certificate handed as the one this "
               "supersedes is %.16s..., and this one names %s", got,
               C->supersedes);
    snprintf(out, cap, "supersedes %s: the certificate handed is that one",
             C->supersedes);
}

/* The definition (cert2._Cover): this library's profile and language
 * against the certificate's. The language is compared only where a run
 * names a source - no check reads it otherwise - and `unknown` is never
 * covered. */
static void cover_of(const cert_t *C)
{
    uint64_t r;
    int named = 0;
    for (r = 0; r < C->R; r++)
        if (C->runs[r].has_source)
            named = 1;
    COVERED = covers(CFT_PROFILE_MAJOR, CFT_PROFILE_MINOR, C->profile) &&
              (!named || covers(CFT_LANGUAGE_MAJOR, CFT_LANGUAGE_MINOR,
                                C->language));
    CERT_PROFILE = C->profile;
    CERT_LANGUAGE = C->language;
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
        /* the loader's verdicts - the image loads, its format, its shape -
         * re-derived through the definition (cert2._check_programs) */
        THROUGH = C->v2;
        st = cft_program_load(dev_at(p->depth), p->image, p->image_bytes,
                              &p->prog);
        if (st != CFT_OK) {
            const char *why = cft_last_error();
            /* An image whose header names a format above this build's,
             * under a run that states one within it (the reader refused
             * any other): the library refuses the format, after the
             * header checks it makes first (CFT_ERR_ARTIFACT) and before
             * any other. Which of the golden's names the image earns -
             * program-format for the mismatch, or program-image for a
             * defect past the format - this build cannot learn without
             * loading it, so it refuses by the build's name rather than
             * give either (the lead's rule, 2026-09-29: nothing a narrow
             * build cannot do reaches another name). Only a build below
             * the ladder's top gets here. */
            uint32_t hf = p->image_bytes >= 32 ? le32(p->image + 20) : 0;
            if (st == CFT_ERR_UNSUPPORTED && (int)hf > CFT_MAX_FORMAT &&
                hf <= 3)
                refuse("build-format", AT_RUN(r), "run %llu: the image handed "
                       "is %s by its header, and this build's library carries "
                       "formats up to %s (CFT_MAX_FORMAT=%d), so it cannot "
                       "load it; it refuses rather than audit it differently",
                       (unsigned long long)r, FMT[hf].name,
                       FMT[CFT_MAX_FORMAT].name, CFT_MAX_FORMAT);
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
        THROUGH = 0;
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

/* block files, by run, then by segment as cert2._check_blocks reads a
 * mapping's keys: their decimal spelling, in string order */
static int cmp_bf(const void *a, const void *b)
{
    const statefile_t *x = (const statefile_t *)a, *y = (const statefile_t *)b;
    if (x->r != y->r)
        return x->r < y->r ? -1 : 1;
    return strcmp(x->bstr, y->bstr);
}

/* Step 7, version 2 (cert2._check_blocks): each block handed - its run one
 * of the certificate's (`lane-flags-shape`, before any is read), its
 * segment one of the run's, its run saying `lane-flags yes`, its size the
 * run's lanes (`lane-flags-shape`), its hash the segment line's
 * (`lane-flags-hash`), and R23's identities against the segment line
 * (`lane-flags-identity`): the OR of the bytes' [4:0] is the flag word,
 * the OR of their [6:5] is STATUS[5:4], and no byte carries [7]. The
 * verdict names the segments handed, in the order they were read. */
static void check_blocks(const cert_t *C, const uint8_t *salt)
{
    size_t i;
    for (i = 0; i < N_BF; i++)
        if (BF[i].r >= C->R)
            refuse("lane-flags-shape", NOWHERE, "lane_flags names run %s, and "
                   "the certificate's runs are 0..%llu", BF[i].r == UINT64_MAX
                   ? "past 2^63 - 1" : "that is not one of them",
                   (unsigned long long)C->R - 1);
    qsort(BF, N_BF, sizeof *BF, cmp_bf);
    for (i = 0; i < N_BF; i++) {
        uint64_t r = BF[i].r, k = BF[i].b;
        const run_t *run = &C->runs[r];
        const seg_t *seg;
        size_t n = 0, j;
        uint8_t *blk, ieee = 0, st = 0, mark = 0;
        char hex[65];
        if (k >= run->S)
            refuse("lane-flags-shape", AT_RUN(r), "run %llu has segments "
                   "0..%llu; a block was handed for %s", (unsigned long long)r,
                   (unsigned long long)run->S - 1, BF[i].bstr);
        if (!run->lane_flags)
            refuse("lane-flags-shape", AT_RS(r, k), "run %llu segment %llu: a "
                   "block was handed, and the run says lane-flags no",
                   (unsigned long long)r, (unsigned long long)k);
        blk = read_file(BF[i].path, &n);
        if (!blk)
            refuse("usage", NOWHERE, "the block file %s was opened before "
                   "step 1 and cannot be read at step 7 (%s): it changed or "
                   "went since", BF[i].path, strerror(errno));
        if ((uint64_t)n != run->lanes)
            refuse("lane-flags-shape", AT_RS(r, k), "run %llu segment %llu: a "
                   "block is the run's %llu lanes, a byte each; this is %lu "
                   "bytes", (unsigned long long)r, (unsigned long long)k,
                   (unsigned long long)run->lanes, (unsigned long)n);
        seg = &run->chain[k];
        lane_flags_hash(salt, blk, n, hex);
        if (strcmp(hex, seg->lanes) != 0)
            refuse("lane-flags-hash", AT_RS(r, k), "run %llu segment %llu: the "
                   "block handed is not the one certified",
                   (unsigned long long)r, (unsigned long long)k);
        for (j = 0; j < n; j++) {
            ieee |= (uint8_t)(blk[j] & 0x1Fu);
            st |= (uint8_t)((blk[j] & 0x60u) >> 1);
            mark |= (uint8_t)(blk[j] & 0x80u);
        }
        free(blk);
        if (ieee != seg->flags || st != (seg->status & 0x30u) || mark)
            refuse("lane-flags-identity", AT_RS(r, k), "run %llu segment %llu: "
                   "the block's OR is flags %u and STATUS[5:4] %u%s; the "
                   "segment line says flags %lu and STATUS[5:4] %lu",
                   (unsigned long long)r, (unsigned long long)k,
                   (unsigned)ieee, (unsigned)(st >> 4), mark ? ", with a "
                   "byte carrying [7]" : "", (unsigned long)seg->flags,
                   (unsigned long)((seg->status >> 4) & 3u));
    }
}

/* the blocks handed for run r, in the order read, as the verdict lists
 * them (cert._segment_list): `[0, 1, 10, 2]` */
static void print_blocks_seen(uint64_t r)
{
    size_t i;
    int first = 1;
    printf("[");
    for (i = 0; i < N_BF; i++)
        if (BF[i].r == r) {
            printf("%s%llu", first ? "" : ", ", (unsigned long long)BF[i].b);
            first = 0;
        }
    printf("]");
}

static int blocks_seen(uint64_t r)
{
    size_t i;
    for (i = 0; i < N_BF; i++)
        if (BF[i].r == r)
            return 1;
    return 0;
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

/* Does an image hold a routine (C4): any of revision 8's QUIET, ENDQUIET
 * or RAISE, control codes 12 to 14 (R24)? The language's compiler writes
 * them around every routine it inlines and nowhere else, and a routine's
 * words are its format's, so such an image has no wider run: refused
 * `aux-image` (check_relations), as cft-segrun refuses to write one. */
static int routine_image(const prog_t *p)
{
    uint32_t n = le32(p->image + 8), k;
    size_t c = p->bank_ext ? 0 : p->n_consts;
    const uint8_t *ins = p->image + 32 + c * ESZ(p->fmt);
    for (k = 0; k < n; k++) {
        uint32_t lo = le32(ins + (size_t)k * 8u), code = lo & 0xFFu;
        if ((lo >> 31) & 1u && (code == 12u || code == 13u || code == 14u))
            return 1;
    }
    return 0;
}

/* two runs' source lines are the same lines: every token, each in its one
 * spelling (`all` 1), or the source, its params and its compiler (`all`
 * 0, the wider-source relation's test) */
static int same_source(const run_t *a, const run_t *b, int all)
{
    uint64_t i;
    if (a->has_source != b->has_source)
        return 0;
    if (!a->has_source)
        return 1;
    if (strcmp(a->src_digest, b->src_digest) != 0 ||
        (all && (strcmp(a->src_name, b->src_name) != 0 ||
                 strcmp(a->graph, b->graph) != 0)))
        return 0;
    if (a->has_compiler != b->has_compiler ||
        (a->has_compiler && (strcmp(a->comp_name, b->comp_name) != 0 ||
                             strcmp(a->comp_ver, b->comp_ver) != 0 ||
                             strcmp(a->comp_target, b->comp_target) != 0)))
        return 0;
    if (a->n_sparams != b->n_sparams)
        return 0;
    for (i = 0; i < a->n_sparams; i++)
        if (strcmp(a->sp_name[i], b->sp_name[i]) != 0 ||
            strcmp(a->sp_lit[i], b->sp_lit[i]) != 0)
            return 0;
    return 1;
}

/* Step 8 for a wider-source run (cert2._wider_source), every check a
 * re-derivation through the definition: the next rung, the main run's
 * lanes, the source lines (`aux-source`), the steps; and then the main
 * run's source compiled one rung up, which this tool, taking no source,
 * cannot make - `source-missing`, where the golden auditor handed none
 * refuses it. */
static void wider_source(const cert_t *C, uint64_t r)
{
    const run_t *main = &C->runs[0], *A = &C->runs[r];
    THROUGH = 1;
    if (main->fmt == 3)
        refuse("aux-format", AT_RUN(r), "run %llu (wider-source): the main "
               "run is fp256, the top of the ladder - a program image is at "
               "most fp256, so no wider run exists and a rounding estimate by "
               "one is refused", (unsigned long long)r);
    if (A->fmt != main->fmt + 1)
        refuse("aux-format", AT_RUN(r), "run %llu (wider-source) is %s; one "
               "format wider than %s is %s", (unsigned long long)r,
               FMT[A->fmt].name, FMT[main->fmt].name, FMT[main->fmt + 1].name);
    if (A->lanes != main->lanes)
        refuse("aux-lanes", AT_RUN(r), "run %llu (wider-source) has %llu lanes "
               "and the main run %llu", (unsigned long long)r,
               (unsigned long long)A->lanes, (unsigned long long)main->lanes);
    if (!A->has_source || !main->has_source || !A->has_compiler ||
        !main->has_compiler)
        refuse("aux-source", AT_RUN(r), "run %llu (wider-source): a "
               "wider-source run and its main run each name the source and a "
               "compiler", (unsigned long long)r);
    if (!same_source(A, main, 0))
        refuse("aux-source", AT_RUN(r), "run %llu (wider-source): its source, "
               "source params and compiler (name, output version, target) are "
               "not the main run's", (unsigned long long)r);
    if (A->steps != main->steps)
        refuse("aux-image", AT_RUN(r), "run %llu (wider-source) states %llu "
               "steps a segment and the main run %llu", (unsigned long long)r,
               (unsigned long long)A->steps, (unsigned long long)main->steps);
    refuse("source-missing", AT_RUN(r), "run %llu (wider-source): holding a "
           "wider-source run to the main run's source compiled one format "
           "wider needs the source, and it was not handed: this auditor "
           "takes no source (it has no compiler of the language)",
           (unsigned long long)r);
}

/* Step 8 (cert._check_relations; version 2's cert2._check_relations adds
 * each auxiliary run's source lines and the wider-source relation). */
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
        if (A->kind == K_WSRC) {
            wider_source(C, r);
            continue;               /* (wider_source refuses: no source) */
        }
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
        /* version 2: the source lines, at their place after aux-lanes - a
         * half-step run's are the main run's, all of them, and a wider run
         * names none (its relation is to the main image) */
        if (C->v2 && half && !same_source(A, main, 1))
            refuse("aux-source", AT_RUN(r), "run %llu (%s): its source lines "
                   "are not the main run's - a half-step run is the main "
                   "run's source at h/2", (unsigned long long)r, w);
        if (C->v2 && !half && A->has_source)
            refuse("aux-source", AT_RUN(r), "run %llu (%s) names a source: a "
                   "wider run's relation is to the main image, not to a "
                   "source (wider-source is the source's)",
                   (unsigned long long)r, w);
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
        } else if (routine_image(P0)) {
            refuse("aux-image", AT_RUN(r), "run %llu (%s): the main image "
                   "holds a routine (QUIET, ENDQUIET or RAISE), whose words "
                   "are its format's, so no image is it one format wider; "
                   "certificate version 2's wider-source run compiles its "
                   "source one format up instead", (unsigned long long)r, w);
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
 * CFT_SEGRUN_PLANT's is: cmd and Windows PowerShell remove a variable
 * they are told to set empty, so an empty one means the same everywhere. */
static int PLANT_EXECUTOR = 0;

/* version 2: the replay line run r carries for segment k, or NULL */
static const replay_t *replay_of(const run_t *run, uint64_t k)
{
    uint64_t lo = 0, hi = run->n_replays;
    while (lo < hi) {
        uint64_t mid = lo + (hi - lo) / 2;
        if (run->replays[mid].k == k)
            return &run->replays[mid];
        if (run->replays[mid].k < k)
            lo = mid + 1;
        else
            hi = mid;
    }
    return NULL;
}

/* version 2: how many blocks each run re-ran and matched, for the
 * verdict's lane-flags line (cert2._rerun's notes) */
static uint64_t *BLOCKS_RERUN = NULL;

/* Step 9 (cert._rerun; version 2's cert2._rerun adds each re-run's block
 * where its run says `lane-flags yes`, a replay line held to the raw
 * segment, and the corrected segment held to the segment line). */
static void rerun(const cert_t *C, const uint8_t *salt, const prog_t *P,
                  const plan_t *plan)
{
    uint64_t r;
    if (C->v2)
        BLOCKS_RERUN = (uint64_t *)xalloc((size_t)C->R,
                                          sizeof *BLOCKS_RERUN);
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        const prog_t *p = &P[r];
        const plan_t *pl = &plan[r];
        size_t sb = 0, esz = ESZ(p->fmt);
        uint8_t *prev = NULL, *zero = NULL, *block = NULL;
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
            const replay_t *rep = C->v2 ? replay_of(run, k) : NULL;
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
            if (C->v2 && run->lane_flags) {
                /* R23's block, asked for where the run says yes: a byte a
                 * lane, at most what the state handed bounds */
                if (!block)
                    block = (uint8_t *)xalloc((size_t)run->lanes, 1);
                ra.lane_flags = block;
                ra.lane_flags_bytes = (size_t)run->lanes;
            }
            THROUGH = C->v2;            /* a re-derivation (cert2._Through) */
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
            if (C->v2) {
                /* the marks: the block's [7] where the run asked for it, and
                 * STATUS[6] - their OR, R23 - where it did not */
                uint64_t marked = 0, j;
                if (run->lane_flags) {
                    for (j = 0; j < run->lanes; j++)
                        if (block[j] & CFT_LANE_MARKED)
                            marked++;
                } else if (bus & CFT_STATUS_MARKED) {
                    marked = 1;
                }
                if (marked && !rep)
                    refuse("replay-missing", AT_RS(r, k), "run %llu segment "
                           "%llu: the re-run marks %s, and no replay line "
                           "names the segment%s", (unsigned long long)r,
                           (unsigned long long)k, run->lane_flags ? "a lane"
                           : "a lane (STATUS[6])", run->lane_flags ? "" :
                           ": the run did not ask for the block, so its "
                           "producer could not have found the lane");
                if (rep && !marked)
                    refuse("replay-unmarked", AT_RS(r, k), "run %llu segment "
                           "%llu: a replay line names it, and its re-run marks "
                           "no lane", (unsigned long long)r,
                           (unsigned long long)k);
                if (rep) {
                    char lh[65];
                    state_hash(salt, out, sb, hex);
                    lane_flags_hash(salt, block, (size_t)run->lanes, lh);
                    if (strcmp(hex, rep->raw_end) != 0 ||
                        strcmp(lh, rep->raw_lanes) != 0 ||
                        rep->marked != marked)
                        refuse("replay-raw", AT_RS(r, k), "run %llu segment "
                               "%llu: the replay line's raw end, raw block or "
                               "marked count is not the re-run's (%llu "
                               "marked)", (unsigned long long)r,
                               (unsigned long long)k,
                               (unsigned long long)marked);
                    /* each marked lane replayed by the definition: the
                     * source's interpreter, which this tool does not have */
                    THROUGH = 0;
                    refuse("source-missing", AT_RS(r, k), "run %llu segment "
                           "%llu: the definition is the run's source, and it "
                           "was not handed: this auditor takes no source (it "
                           "has no interpreter of the language)",
                           (unsigned long long)r, (unsigned long long)k);
                }
            }
            state_hash(salt, out, sb, hex);
            if (strcmp(hex, seg->end) != 0)
                refuse("segment-end", AT_RS(r, k), "run %llu segment %llu: "
                       "re-run from its certified start state, it does not "
                       "end on its certified end state", (unsigned long long)r,
                       (unsigned long long)k);
            if (C->v2 && run->lane_flags) {
                lane_flags_hash(salt, block, (size_t)run->lanes, hex);
                if (strcmp(hex, seg->lanes) != 0)
                    refuse("segment-lane-flags", AT_RS(r, k), "run %llu "
                           "segment %llu: the re-run's block is not the "
                           "certified one", (unsigned long long)r,
                           (unsigned long long)k);
            }
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
            THROUGH = 0;
            if (C->v2 && run->lane_flags)
                BLOCKS_RERUN[r]++;
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
        free(block);
    }
}

/* Step 9a, version 2 (cert2._define_rerun), the auditor's choice: each
 * chosen segment, from its start - handed, or re-run into by step 9
 * (`state-missing`) - run lane by lane by the source's interpreter. This
 * tool takes no source and has no interpreter of the language, so the
 * first chosen segment whose start is known is refused `source-missing`,
 * there, as the golden auditor handed no source refuses it. */
static int boundary_handed(uint64_t r, uint64_t b)
{
    size_t i;
    for (i = 0; i < N_SF; i++)
        if (SF[i].r == r && SF[i].b == b)
            return 1;
    return 0;
}

static void define_rerun(const cert_t *C, const plan_t *plan,
                         const dplan_t *dp)
{
    uint64_t r, j;
    for (r = 0; r < C->R; r++)
        for (j = 0; j < dp[r].n; j++) {
            uint64_t k = dp[r].segs[j];
            int known = boundary_handed(r, k) ||
                        (k >= 1 && chosen(&plan[r], k - 1));
            if (!known)
                refuse("state-missing", AT_RS(r, k), "run %llu segment %llu: "
                       "the definition re-run starts from boundary %llu, which "
                       "was neither handed nor re-run into",
                       (unsigned long long)r, (unsigned long long)k,
                       (unsigned long long)k);
            refuse("source-missing", AT_RS(r, k), "run %llu segment %llu: the "
                   "definition is the run's source, and it was not handed: "
                   "this auditor takes no source (it has no interpreter of "
                   "the language)", (unsigned long long)r,
                   (unsigned long long)k);
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

/* A run as cert_exact.h's derivation reads it: the certificate's kind,
 * lanes and segments, and its program's format and slots a lane. */
static void run_shape(const cert_t *C, const prog_t *P, uint64_t r,
                      cx_run *s)
{
    s->kind = C->runs[r].kind;
    s->fmt = P[r].fmt;
    s->lanes = C->runs[r].lanes;
    s->S = C->runs[r].S;
    s->nslots = P[r].n_in;
}

/* A status of cert_exact.h's, refused by its name at the entry (ENTRY_NOW
 * adds it), or an internal error. One call a name, so that the census
 * (audit_plants.py) still plants each name apart. */
static void refuse_cx(int st, uint64_t j, const char *why)
{
    if (st == CX_RUN)
        refuse("accuracy-run", NOWHERE, "entry %llu: %s",
               (unsigned long long)j, why);
    if (st == CX_SCOPE)
        refuse("accuracy-scope", NOWHERE, "entry %llu: %s",
               (unsigned long long)j, why);
    if (st == CX_SLOT)
        refuse("accuracy-slot", NOWHERE, "entry %llu: %s",
               (unsigned long long)j, why);
    if (st == CX_FINITE)
        refuse("accuracy-finite", NOWHERE, "%s", why);
    if (st == CX_WIDTH)
        refuse("width", NOWHERE, "%s", why);
    if (st)
        internal(why, CFT_ERR_INTERNAL);
}

/* cert.derive: its checks in its order (cx_entry_check), the two states
 * it reads in its order (need_state: state-missing), and the value, every
 * step held to the width rule (cx_entry_value). */
static void derive(const cert_t *C, const prog_t *P, uint64_t j, rat *out)
{
    const entry_t *E = &C->entries[j];
    cx_run m, u;
    uint64_t need[2][2];
    const uint8_t *a, *b;
    char why[512];
    int exists = E->uses < C->R;
    why[0] = 0;                    /* written by each check that fails: gcc
                                    * 16 cannot see that it is read only
                                    * then (-Wmaybe-uninitialized) */
    memset(&u, 0, sizeof u);       /* read only once the run is known to exist */
    run_shape(C, P, 0, &m);
    if (exists)
        run_shape(C, P, E->uses, &u);
    refuse_cx(cx_entry_check(E, C->R, &m, exists ? &u : NULL, why,
                             sizeof why), j, why);
    cx_entry_needs(E, &m, &u, need);
    a = need_state(need[0][0], need[0][1]);
    b = need_state(need[1][0], need[1][1]);
    refuse_cx(cx_entry_value(E, &m, &u, a, b, out, why, sizeof why), j, why);
}

/* cert.value_holds, through the software handle the rounding needs */
static int value_holds(const value_t *v, const rat *q)
{
    int holds = 0;
    if (cx_value_holds(host_dev(), v, q, &holds))
        internal("an accuracy value held to its re-derivation (the rounding "
                 "past the bigint, or cft_from_hex_char)", CFT_ERR_INTERNAL);
    return holds;
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

/* a run's line of what was re-run and how it was chosen (both versions) */
static void print_run_head(const cert_t *C, const plan_t *plan, uint64_t r)
{
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

/* cert.Verdict.lines(), byte for byte */
static void print_verdict(const cert_t *C, const plan_t *plan
#if AUDIT_EXACT
                          , const rat *values
#endif
                          )
{
    uint64_t r;
    printf("cft-certificate 1: ACCEPTED - every check passed\n");
    printf("%s\n", C->keyed ? "keyed: the salt handed is the one committed to"
           : "open: no salt - its hashes are plain SHA-256, and anyone "
             "holding the states can audit it");
    for (r = 0; r < C->R; r++)
        print_run_head(C, plan, r);
#if AUDIT_EXACT
    uint64_t i;
    for (i = 0; i < C->A; i++) {
        char t[CX_RAT_TEXT];
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

/* a provenance line (cert2._words_report): unknown, none, withheld, or
 * stated and not checked - a text shown in its spelling, its token */
static void words_line(const char *k, const char *v)
{
    if (!strcmp(v, "unknown"))
        printf("%s: unknown - the producer did not record it\n", k);
    else if (!strcmp(v, "none"))
        printf("%s: none - it does not exist for this producer\n", k);
    else if (!strcmp(v, "withheld"))
        printf("%s: withheld - the producer has it and chose not to publish "
               "it\n", k);
    else
        printf("%s: %s - stated, not checked\n", k, v);
}

/* the audit's time, UTC, one spelling of RFC 3339's date-time */
static void utc_now(char out[32])
{
    time_t t = time(NULL);
    struct tm *g = gmtime(&t);
    if (!g || strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", g) == 0)
        snprintf(out, 32, "unknown");
}

/* Version 2's verdict: its header - the auditor's identity and the audit's
 * time (cert2.Verdict.header(), which the comparison between auditors
 * leaves out) - and then cert2.Verdict.lines(), byte for byte. A source is
 * never handed to this tool and no generator is regenerated, so the lines
 * that would say so never come; a replay or a definition re-run in a
 * segment it reaches is `source-missing` before the verdict. */
static void print_verdict2(const cert_t *C, const plan_t *plan,
#if AUDIT_EXACT
                           const rat *values,
#endif
                           const char *name, const char *sig_line,
                           const char *sup_line)
{
    char ap[48], al[48], when[32];
    uint64_t r;
    size_t i;
    int beyond = 0;
    version_text(ap, sizeof ap, CFT_PROFILE_MAJOR, CFT_PROFILE_MINOR);
    version_text(al, sizeof al, CFT_LANGUAGE_MAJOR, CFT_LANGUAGE_MINOR);
    utc_now(when);
    printf("auditor cft-audit %s\n", cft_build_id());
    printf("audited %s\n", when);
    printf("cft-certificate 2: ACCEPTED - every check passed\n");
    printf("certificate %s: its name, the SHA-256 of its body\n", name);
    printf("%s\n", C->keyed ? "keyed: the salt handed is the one committed to"
           : "open: no salt - its hashes are plain SHA-256, and anyone "
             "holding the states can audit it");
    printf("%s\n%s\n", sig_line, sup_line);
    printf("definition: the certificate's profile %s and language %s; the "
           "auditor's profile %s and language %s, which %s\n", C->profile,
           C->language, ap, al, COVERED ? "cover them" : "do not cover them, "
           "and every re-derivation passed under the auditor's");
    for (r = 0; r < C->R; r++) {
        const run_t *run = &C->runs[r];
        print_run_head(C, plan, r);
        if (!run->has_source)
            printf("run %llu source: none\n", (unsigned long long)r);
        else
            printf("run %llu source %s: named, not handed - stated, not "
                   "checked\n", (unsigned long long)r, run->src_digest);
        if (run->lane_flags) {
            printf("run %llu lane flags: %llu blocks re-run and matched",
                   (unsigned long long)r, (unsigned long long)BLOCKS_RERUN[r]);
            if (blocks_seen(r)) {
                printf(", segments ");
                print_blocks_seen(r);
                printf(" handed and consistent");
            }
            printf("\n");
        } else {
            printf("run %llu lane flags: none - the run did not ask for "
                   "them\n", (unsigned long long)r);
        }
        printf("run %llu replays: none in the segments re-run\n",
               (unsigned long long)r);
    }
#if AUDIT_EXACT
    for (r = 0; r < C->A; r++) {
        char t[CX_RAT_TEXT];
        rat_text(&values[r], t);
        printf("accuracy entry %llu: re-derived as %s - the value is the "
               "stated function of the certified runs; that an estimate "
               "estimates well is not shown\n", (unsigned long long)r, t);
    }
#endif
    if (!C->generator) {
        printf("initial state: given\n");
    } else {
        int known = 0;
        for (i = 0; i < sizeof GENERATORS / sizeof GENERATORS[0]; i++)
            if (!strcmp(C->generator, GENERATORS[i]))
                known = 1;
        if (known)
            printf("initial state: generator %s - stated, not checked: the "
                   "auditor did not choose to regenerate it\n", C->generator);
        else
            printf("initial state: generator %s, which this auditor does not "
                   "know - stated, not checked\n", C->generator);
    }
    for (i = 0; i < N_SF; i++)
        if (SF[i].b != 0)
            beyond = 1;
    printf("handed: %s\n", beyond ? "re-run - from states handed" :
           "re-run from the start - from the initial states alone");
    identity_line("build-id", C->build_id);
    identity_line("backend", C->backend);
    identity_line("device-xclbin", C->xclbin);
    identity_line("device-version", C->version);
    identity_line("device-caps", C->caps);
    identity_line("device-tiles", C->tiles);
    words_line("device-platform", C->dev_platform);
    words_line("device-xrt", C->dev_xrt);
    words_line("device-clock", C->dev_clock);
    words_line("device-serial", C->dev_serial);
    words_line("writer", C->writer);
    words_line("writer-runtime", C->writer_runtime);
    words_line("compiler-build", C->compiler_build);
    words_line("certificate-id", C->certificate_id);
    words_line("issuer", C->issuer);
    words_line("issuer-key", C->issuer_key);
    words_line("host-os", C->host_os);
    words_line("host-arch", C->host_arch);
    words_line("started", C->started);
    words_line("finished", C->finished);
    words_line("issued", C->issued);
    for (i = 0; i < C->n_methods; i++) {
        const method_t *m = &C->methods[i];
        if (m->image)
            printf("replay-method %llu: image %s", (unsigned long long)m->run,
                   m->image);
        else
            printf("replay-method %llu: golden", (unsigned long long)m->run);
        printf(" - stated, not checked: every replay is checked against the "
               "definition\n");
    }
    printf("environment: ");
    if (!C->n_env)
        printf("none set");
    for (i = 0; i < C->n_env; i++)
        printf("%s%s=%s", i ? ", " : "", C->env_name[i], C->env_value[i]);
    printf(" - stated, not checked\n");
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
 *   sha512 M                      SHA-512 of the bytes M (hex; `-` empty)
 *   sha512rep B N                 SHA-512 of N copies of the byte B
 *   ed-verify K M S               1 if S verifies for M under K (hex)
 *   ed-key K                      ed25519_key_check: 0 ok, 1 no point,
 *                                 2 small order
 *   ed-small K | ed-decode K      ed25519_small_order, ed25519_decodes
 *
 * An element is hex, big-endian, width/4 digits, as a certificate
 * spells one. Bytes for the hashes and keys are hex in their order. */
#if !AUDIT_EXACT
#error "the probe needs the exact arithmetic: a cft_bn of 2,047 bits or more"
#endif

static void probe_rat(const char *s, rat *q)
{
    const char *slash = strchr(s, '/');
    q->neg = *s == '-';
    if (q->neg)
        s++;
    if (bn_from_hex(&q->n, s, (size_t)(slash - s)) ||
        bn_from_hex(&q->d, slash + 1, strlen(slash + 1)))
        internal("the probe: a rational past the bigint", CFT_ERR_INTERNAL);
    if (cft_bn_is_zero(&q->n))
        q->neg = 0;
}

/* a status of cert_exact.h's that is not a verdict, in the probe */
static void probe_ok(int st, const char *what)
{
    if (st)
        internal(what, CFT_ERR_INTERNAL);
}

static void probe_elem_out(int f, const uint8_t *le)
{
    size_t i;
    for (i = ESZ(f); i-- > 0;)
        printf("%02x", le[i]);
}

/* hex in its order -> bytes; `-` is none */
static size_t probe_bytes(const char *h, uint8_t *out, size_t cap)
{
    size_t n = strlen(h), i;
    if (!strcmp(h, "-"))
        return 0;
    if (n / 2 > cap)
        internal("the probe: bytes past its buffer", CFT_ERR_INTERNAL);
    for (i = 0; i < n / 2; i++)
        out[i] = (uint8_t)(hexval(h[2 * i]) << 4 | hexval(h[2 * i + 1]));
    return n / 2;
}

static void probe_hex_out(const uint8_t *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        printf("%02x", b[i]);
    printf("\n");
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
            probe_ok(bn_from_hex(&a, tok[1], strlen(tok[1])) ||
                     bn_from_hex(&b, tok[2], strlen(tok[2])),
                     "the probe: a natural past the bigint");
            if (tok[0][0] == 'g') {
                probe_ok(bn_gcd(&q, &a, &b), "the probe: bn_gcd");
                bn_hex(&q, h);
                printf("%s\n", h);
            } else {
                probe_ok(bn_divmod(&q, &r, &a, &b), "the probe: bn_divmod");
                bn_hex(&q, h);
                printf("%s ", h);
                bn_hex(&r, h);
                printf("%s\n", h);
            }
        } else if (!strcmp(tok[0], "add") || !strcmp(tok[0], "sub") ||
                   !strcmp(tok[0], "mul") || !strcmp(tok[0], "cmp")) {
            rat x, y, z;
            char t[CX_RAT_TEXT];
            int c = 0;
            probe_rat(tok[1], &x);
            probe_rat(tok[2], &y);
            if (tok[0][0] == 'c') {
                probe_ok(rat_cmp(&x, &y, &c), "the probe: rat_cmp");
                printf("%d\n", c);
                continue;
            }
            if (tok[0][0] == 'a')
                probe_ok(rat_add(&z, &x, &y), "the probe: rat_add");
            else if (tok[0][0] == 's')
                probe_ok(rat_sub(&z, &x, &y), "the probe: rat_sub");
            else
                probe_ok(rat_mul(&z, &x, &y), "the probe: rat_mul");
            rat_text(&z, t);
            printf("%s\n", t);
        } else if (!strcmp(tok[0], "round")) {
            int f = atoi(tok[1]), r = atoi(tok[2]);
            rat q;
            uint8_t out[32];
            probe_rat(tok[3], &q);
            probe_ok(cx_round(host_dev(), &q, f, r, out), "the probe: cx_round");
            probe_elem_out(f, out);
            printf("\n");
        } else if (!strcmp(tok[0], "exact")) {
            int f = atoi(tok[1]), got;
            uint8_t le[32];
            elem_t x;
            rat q;
            char t[CX_RAT_TEXT];
            elem_from_hex(f, tok[2], le);
            decode(f, le, &x);
            got = rat_of_elem(&q, &x);
            if (got == CX_FINITE) {
                printf("nonfinite\n");
            } else if (got == CX_WIDTH) {
                long nb, db;
                elem_bits(&x, &nb, &db);
                printf("width %ld %ld\n", nb, db);
            } else {
                probe_ok(got, "the probe: rat_of_elem");
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
        } else if (!strcmp(tok[0], "sha512")) {
            static uint8_t m[1 << 15];
            uint8_t d[64];
            size_t n = probe_bytes(tok[1], m, sizeof m);
            sha512(m, n, d);
            probe_hex_out(d, 64);
        } else if (!strcmp(tok[0], "sha512rep")) {
            uint8_t d[64], blk[1000], byte = 0;
            unsigned long c = strtoul(tok[2], NULL, 10), k;
            sha512_ctx x;
            probe_bytes(tok[1], &byte, 1);
            memset(blk, byte, sizeof blk);
            sha512_init(&x);
            for (k = 0; k + sizeof blk <= c; k += sizeof blk)
                sha512_update(&x, blk, sizeof blk);
            sha512_update(&x, blk, c - k);
            sha512_final(&x, d);
            probe_hex_out(d, 64);
        } else if (!strcmp(tok[0], "ed-verify")) {
            static uint8_t m[1 << 15];
            uint8_t key[32], sig[64];
            size_t n;
            probe_bytes(tok[1], key, 32);
            n = probe_bytes(tok[2], m, sizeof m);
            probe_bytes(tok[3], sig, 64);
            printf("%d\n", ed25519_verify(key, m, n, sig));
        } else if (!strcmp(tok[0], "ed-key") || !strcmp(tok[0], "ed-small") ||
                   !strcmp(tok[0], "ed-decode")) {
            uint8_t key[32];
            probe_bytes(tok[1], key, 32);
            printf("%d\n", tok[0][3] == 'k' ? ed25519_key_check(key) :
                   tok[0][3] == 's' ? ed25519_small_order(key) :
                   ed25519_decodes(key));
        } else {
            printf("?\n");
        }
    }
    return 0;
}

/* The tool's own main is compiled in the probe build too, under an
 * external name nothing calls: so the probe build is exactly the tool's
 * code beside the probe, and nothing in it is "defined but not used" (the
 * project's builds are warning-free; the lead's condition, 2026-09-30). */
#define AUDIT_MAIN audit_tool_main
int audit_tool_main(int argc, char **argv);
#else
#define AUDIT_MAIN main
#endif /* CFT_AUDIT_PROBE */

/* ---- main -------------------------------------------------------------- */

int AUDIT_MAIN(int argc, char **argv)
{
    const char *cert_path = NULL, *salt_path = NULL, *states_path = NULL;
    const char *seed_arg = NULL, *plant = getenv("CFT_AUDIT_PLANT");
    const char *sig_path = NULL, *ring_path = NULL, *sup_path = NULL;
    const char *sample_args[4] = { NULL, NULL, NULL, NULL };
    int read_only = 0, want_sample = 0, i, v2, defines = 0;
    uint8_t *data, *salt = NULL;
    size_t n_data, n_salt = 0, b;
    rdr_t R;
    cert_t C;
    plan_t *plan;
    dplan_t *dplan = NULL;
    prog_t *P;
    char name[65], sig_line[400], sup_line[200];
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
        } else if (!strcmp(a, "--signature")) {
            once(&sig_path, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--keyring")) {
            once(&ring_path, a, need_arg(argc, argv, &i));
        } else if (!strcmp(a, "--superseded")) {
            once(&sup_path, a, need_arg(argc, argv, &i));
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
                   !strcmp(a, "--choose") || !strcmp(a, "--define")) {
            const char *v = need_arg(argc, argv, &i);
            if (!cur)
                refuse("usage", NOWHERE, "%s belongs to a run: give it after "
                       "--run R", a);
            if (!strcmp(a, "--image"))
                once(&cur->image_path, a, v);
            else if (!strcmp(a, "--bank"))
                once(&cur->bank_path, a, v);
            else if (!strcmp(a, "--define")) {
                once(&cur->define, a, v);
                defines = 1;
            } else
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
    if (read_only && (states_path || seed_arg || N_BLK || sig_path ||
                      ring_path || sup_path))
        refuse("usage", NOWHERE, "--read takes --cert and --salt, and nothing "
               "else");
    for (b = 0; b < N_BLK; b++) {
        block_t *B = &BLK[b];
        if (!B->image_path && !B->bank_path && !B->choose && !B->define &&
            !B->stream_path[0] && !B->stream_path[1] && !B->stream_path[2])
            refuse("usage", NOWHERE, "--run %s gives nothing", B->key);
        if (B->bank_path && !B->image_path)
            refuse("usage", NOWHERE, "--run %s: --bank goes with --image",
                   B->key);
    }

    /* ---- every input file, read before the first step ------------------ */
    data = read_named("the certificate", cert_path, &n_data);
    /* the version, as cert.audit chooses it: by the file's first 18 bytes.
     * Version 2's inputs given beside any other certificate are refused
     * as cert.audit refuses them (a TypeError there: not a verdict) */
    v2 = n_data >= 18 && memcmp(data, "cft-certificate 2\n", 18) == 0;
    if (!v2 && (sig_path || ring_path || sup_path || defines))
        refuse("usage", NOWHERE, "--signature, --keyring, --superseded and "
               "--define are version 2's inputs, and %s is no version-2 "
               "certificate: its first line is not 'cft-certificate 2'",
               cert_path);
    if (salt_path)
        salt = read_named("the salt", salt_path, &n_salt);
    if (sig_path)
        SIG = read_named("the signature file", sig_path, &SIG_N);
    if (ring_path)
        RING = read_named("the keyring", ring_path, &RING_N);
    if (sup_path)
        SUP = read_named("the superseded certificate", sup_path, &SUP_N);
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
        list_states(states_path, v2);

    memset(&R, 0, sizeof R);
    memset(&C, 0, sizeof C);
    /* 1 integrity, 2 form */
    read_all(data, n_data, &R, &C, v2, name);
    if (read_only) {
        if (salt_path)
            check_salt(&C, salt, n_salt, 1);
        printf("cft-certificate %d: READ - the hash line, the body's hash and "
               "the strict form hold\n", C.v2 ? 2 : 1);
        if (C.keyed)
            printf("keyed: %s\n", salt_path ? "the salt handed is the one "
                   "committed to" : "no salt was handed, so its commitment "
                   "is not checked");
        else
            printf("open: no salt - its hashes are plain SHA-256\n");
        return 0;
    }
    /* 2, its second half: the auditor's own choice - of re-runs, and in
     * version 2 of the definition re-run's segments */
    plan = make_plan(&C, seed_arg);
    if (C.v2)
        dplan = make_define_plan(&C);
    /* 2a, version 2: the signature, or a keyring alone */
    if (C.v2)
        check_signature(&C, name, sig_line, sizeof sig_line);
    /* 3 salt */
    check_salt(&C, salt_path ? salt : NULL, n_salt, salt_path != NULL);
    if (!C.keyed)
        salt = NULL;
    /* 3a, version 2: the superseded certificate; and the definition */
    if (C.v2) {
        check_superseded(&C, sup_line, sizeof sup_line);
        cover_of(&C);
    }
    /* 4 programs */
    P = check_programs(&C);
    /* 5 streams */
    check_streams(&C, salt, P);
    /* 6 continuity */
    check_continuity(&C);
    /* 7 states, and in version 2 the blocks handed */
    check_states(&C, salt, P, plan);
    if (C.v2)
        check_blocks(&C, salt);
    /* 8 relations */
    check_relations(&C, salt, P);
    /* 9 re-runs */
    rerun(&C, salt, P, plan);
    /* 9a, version 2: the definition re-run, the auditor's choice */
    if (C.v2)
        define_rerun(&C, plan, dplan);
    /* 10 accuracy */
#if AUDIT_EXACT
    values = (rat *)xalloc((size_t)C.A, sizeof *values);
    for (j = 0; j < C.A; j++) {
        ENTRY_NOW = (long long)j;
        derive(&C, P, j, &values[j]);
        if (!value_holds(&C.entries[j].value, &values[j])) {
            char t[CX_RAT_TEXT];
            rat_text(&values[j], t);
            refuse("accuracy-value", NOWHERE, "entry %llu: the value recorded "
                   "is not the %s of the certified runs, which is %s",
                   (unsigned long long)j, METHOD_NAME[C.entries[j].method], t);
        }
        ENTRY_NOW = NONE;
    }
    if (C.v2)
        print_verdict2(&C, plan, values, name, sig_line, sup_line);
    else
        print_verdict(&C, plan, values);
#else
    if (C.v2)
        print_verdict2(&C, plan, name, sig_line, sup_line);
    else
        print_verdict(&C, plan);
#endif
    return 0;
}
