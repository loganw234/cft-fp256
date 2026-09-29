/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-segrun - run a program as consecutive segments, keep the state at
 * every boundary, and write the certificate (docs/CERTIFICATES.md,
 * version 1). Step 3 of the plan of record (docs/ROADMAP.md, "Segments,
 * certificates and the audit tool"); the page's section "The segment
 * runner" is this tool's manual.
 *
 *   cft-segrun --out CERT --states DIR (--salt SALT | --open)
 *              [--device sw|<xclbin>|cft://host:port]
 *              --run main --image IMG [--bank BANK] --init INIT
 *                         --segments S --steps K [--param NAME=N ...]
 *              [--run half-step --h-slots I,J,... --image IMG ...]
 *              [--run wider --image IMG ...]
 *   cft-segrun --hash state|stream-a|stream-b|stream-c FILE
 *              (--salt SALT | --open)
 *   cft-segrun --hash commitment --salt SALT
 *   cft-segrun --build-id
 *
 * ---------------------------------------------------------------
 * What it does
 * ---------------------------------------------------------------
 *
 * Each `--run` opens a run block; the options after it, up to the next
 * `--run`, are that run's. Run 0 is `main`; each later run is an
 * auxiliary run, `half-step` (the same image on a bank whose named
 * h-slots are halved, for twice the segments) or `wider` (the image one
 * format wider). For each run the tool takes an image, its bank when the
 * image takes one (`flags.BANK_EXT`), an initial state and a segment
 * count, and runs the image S times on one device handle, each segment
 * entered with the last one's scratch-out: `cft_program_run_ex` with
 * every lane active, no index table and no lane mask, the streams a, b
 * and c all +0 (the tool takes no streams, and the certificate's stream
 * hashes are of the +0 streams it ran).
 *
 * A STATE is the lane-major scratch block exactly as the library stores
 * it, as positive-run's --scratch-in: lane i's slot s is element
 * i * n_scratch_in + s, each element format-width and little-endian.
 * --init is run r's boundary 0; its size fixes the lanes. Every
 * boundary is written to the states directory as it is reached:
 *
 *   DIR/run-<r>-boundary-<b>.bin     b = 0 (the initial state) .. S
 *
 * decimal indices, no leading zeros, the numbering the certificate uses.
 * DIR is created by this run and must not exist before it, so two runs'
 * states never share a directory. It is what an auditor is handed, with
 * the certificate, the images and banks, and a keyed certificate's salt.
 *
 * The certificate is written last, once every segment of every run has
 * run: the lines in the page's order, `accuracy 0` (accuracy is step 5),
 * `end`, and the hash line. `steps` and every `--param` are stated, not
 * checked, as the page says.
 *
 * Every file the tool writes is one it creates new (O_EXCL), and a
 * regular file: --out must not exist either, and no run overwrites a
 * file, so a refusal that removes what it made never removes anything
 * else. --out is created BEFORE DIR, so an --out inside DIR cannot be
 * created at all - DIR does not exist yet - and a certificate can never
 * be one of the boundary files. And what the runs need in memory is
 * tried before either is created (try_runs): taken and let go in the
 * order the runs will take it, so a run the process cannot hold is
 * refused then, by name, while the runs themselves hold no more at once
 * than 99f1b43's did - one run's states at a time. (Where memory is
 * overcommitted, an allocation the machine cannot back still succeeds,
 * and only what the address space cannot hold is refused.)
 *
 * ---------------------------------------------------------------
 * Hashes
 * ---------------------------------------------------------------
 *
 * Keyed (`--salt`, a file of exactly 32 bytes) or open (`--open`), the
 * owner's choice per certificate. A state's hash is over
 * "cft-certificate 1 state" 0x00 and the state's bytes, a stream's over
 * "cft-certificate 1 stream a" (b, c) 0x00 and its bytes: HMAC-SHA-256
 * under the salt (RFC 2104, SHA-256's 64-byte block) when keyed, plain
 * SHA-256 when open. The commitment is HMAC(salt, "cft-certificate 1
 * salt"), with no NUL. libcft's cft_sha256 is one-shot, so each HMAC
 * pass hashes one buffer: the padded key block, the tag and the bytes.
 * `--hash` prints one of these for a file, which is how the gate holds
 * this code to the page's test vectors.
 *
 * ---------------------------------------------------------------
 * Identity, from the library and nowhere else
 * ---------------------------------------------------------------
 *
 *   build-id        cft_build_id(), verbatim - this binary's library,
 *                   which is libcft.a as it was when this was linked
 *   backend         cft_caps.backend: software, xrt or remote; any other
 *                   answer is written `unknown`
 *   device-xclbin   cft_get_image_id(): the SHA-256 of the bytes loaded
 *   device-version  cft_get_image_id(): VERSION
 *   device-caps     cft_get_image_id(): CAPS alone, or CAPS then CAPS2
 *   device-tiles    cft_caps.tiles, or `unknown` for zero
 *
 * Where cft_get_image_id refuses, the three image lines are `none` on
 * the software backend (no xclbin, no registers), and `unknown`
 * elsewhere, with one exception the page makes: through a remote handle
 * the SERVER's VERSION is written where the protocol carries a nonzero
 * one (cft_caps.device_version, from its HELLO), since the page takes
 * the server's device fields where the protocol carries them. The
 * protocol carries no xclbin digest and no raw CAPS word, so those two
 * are `unknown` there, and device-tiles is the server's.
 *
 * ---------------------------------------------------------------
 * Refusals
 * ---------------------------------------------------------------
 *
 * Every refusal is a name and an exit code, printed as
 * "cft-segrun: refused <name>: <why>" on stderr. The page's names, for
 * the inputs a writer refuses before anything runs:
 *   salt-length (4)    a salt file that is not exactly 32 bytes
 *   program-image (4)  an image whose header does not load, a bank that
 *                      is not the size the image addresses (or any bank
 *                      for an image that carries its constants), or an
 *                      image the library's loader refuses
 *   program-shape (4)  a program that is not a segment: no SCRATCH_IO,
 *                      scratch in and out not equal and at least 1, or
 *                      max_deposits not 0
 *   state-shape (4)    an initial state that is not a whole number of
 *                      lanes, at least one, of the image's slots
 *   malformed (2)      a count or index not in the page's decimal
 *                      spelling or its range (segments and steps at
 *                      least 1; h-slots 1 to 512 of them, each below 512,
 *                      strictly increasing; a parameter name or value);
 *                      run 0 not main, or a later run that is; no run
 *   line-unexpected (2), line-order (2)
 *                      a parameter name repeated, or smaller than the
 *                      one before it (names in byte order)
 * - the same names, for the same defects, as the golden writer's
 *   (cert.run_chain, certify_run, encode). And the tool's own, which the
 *   golden writer - an API, not a command - has no use for:
 *   usage (64)         a command line this tool does not take, or a file
 *                      it names that cannot be read
 *   device (69)        the device cannot make or report the run: it does
 *                      not open, it cannot read the sticky flags a
 *                      certificate records (cft_caps.flags_readable), or
 *                      a digest or a segment's run fails
 *   memory (71)        the process cannot have what the runs need, more
 *                      than it can address or more than it is given -
 *                      found before anything is created or run - or
 *                      another of this tool's own allocations fails. The
 *                      LIBRARY's allocations are not this tool's: a
 *                      library out of memory is refused as what failed,
 *                      `program-image` (cft_program_load) or `device`
 *                      (a segment's run); a stdio buffer that cannot be
 *                      had, as `usage` (reading) or `output` (writing)
 *   output (73)        the certificate or the states cannot be created
 *                      or written: --out or DIR already exists, --out is
 *                      not a regular file (Windows' NUL), or --out lies
 *                      inside DIR, which is not there yet
 * A refusal writes no certificate, and removes only what the run itself
 * created. One made before the first segment leaves nothing behind; a
 * run that fails part way leaves the boundary files it had written, and
 * says so.
 *
 * Two refusals guard against a LIBRARY that misreports a segment's flag
 * word: one it left unwritten (the word preset to all ones is still all
 * ones: `device`), and one past the five sticky flags (`malformed`, as
 * the golden writer's encode would refuse a flag word the reader cannot
 * read). No backend in this tree does either, and none reports
 * flags_readable 0, so CFT_SEGRUN_PLANT is an instrument for the gate
 * that holds those three refusals:
 *   flags-unreadable   the device is treated as one that cannot read its
 *                      flags (refused before anything runs)
 *   flags-unwritten    each segment's flag word is treated as left
 *                      unwritten by the library
 *   flags-wide         each segment's flag word gains bit 5
 * Each says so on stderr, and makes a certificate's run refuse by that
 * name; with --build-id or --hash, which run nothing, it only prints its
 * note and the run exits 0 with the right output. A fourth refuses
 * nothing:
 *   trial-skipped      the trial's allocations are skipped, its size
 *                      checks kept (try_runs), so that the gate can hold
 *                      the trial to costing the runs nothing
 * Any other value is refused as `usage`.
 *
 * ---------------------------------------------------------------
 * What it certifies, and what it does not
 * ---------------------------------------------------------------
 *
 * It certifies what ran: which bits each segment started and ended on
 * (as hashes), with its flags and STATUS, on which library and device.
 * It checks nothing about an auxiliary run's relation to the main run -
 * a half-step bank that is not the main bank halved is written as stated
 * and refused by the audit (`aux-bank`) - and nothing about accuracy. It
 * signs nothing: the hash line catches corruption, not forgery. The gate
 * is host/tests/segrun_check.py: the golden writer, handed this
 * certificate's identity lines, the same salt and the same initial
 * states, runs every segment itself and must write the same bytes.
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200112L   /* 199309L hid snprintf on Darwin (2026-09-09) */
#  define _DEFAULT_SOURCE           /* glibc: MAP_ANONYMOUS beside POSIX */
#  define _DARWIN_C_SOURCE          /* Darwin: MAP_ANON beside POSIX */
#endif

#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  include <windows.h>              /* VirtualAlloc, for try_runs */
#  include <direct.h>
#  include <fcntl.h>
#  include <io.h>
#  include <sys/stat.h>
#  define MKDIR(p) _mkdir(p)
#  define RMDIR(p) _rmdir(p)
#else
#  include <fcntl.h>
#  include <sys/mman.h>             /* mmap, for try_runs */
#  include <sys/stat.h>
#  include <sys/types.h>
#  include <unistd.h>
#  define MKDIR(p) mkdir((p), 0777)
#  define RMDIR(p) rmdir(p)
#  if defined(MAP_ANONYMOUS)
#    define SEG_MAP_ANON MAP_ANONYMOUS
#  elif defined(MAP_ANON)
#    define SEG_MAP_ANON MAP_ANON
#  endif
#endif
/* stat, fstat and fileno under their Windows names, which -std=c99
 * leaves declared there, and the POSIX ones elsewhere */
#if defined(_WIN32)
typedef struct _stat stat_t;
#  define STAT(p, b)   _stat((p), (b))
#  define FSTAT(d, b)  _fstat((d), (b))
#  define FILENO(f)    _fileno(f)
#  define IS_FILE(m)   (((m) & _S_IFMT) == _S_IFREG)
#else
typedef struct stat stat_t;
#  define STAT(p, b)   stat((p), (b))
#  define FSTAT(d, b)  fstat((d), (b))
#  define FILENO(f)    fileno(f)
#  define IS_FILE(m)   S_ISREG(m)
#endif

/* A file this run creates NEW, or NULL with errno set (EEXIST when the
 * path is taken): O_EXCL, so no file the tool writes is one it did not
 * create, and a refusal that removes what the run made removes nothing
 * else. Windows answers O_EXCL on a directory that is there with EACCES,
 * not EEXIST, so a path that is there is called so whatever it is. */
static FILE *create_new(const char *path)
{
    FILE *f;
    int e;
    stat_t sb;
#if defined(_WIN32)
    int fd = _open(path, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                   _S_IREAD | _S_IWRITE);
#else
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0666);
#endif
    if (fd < 0) {
        e = errno;
        if (e == EACCES && STAT(path, &sb) == 0)
            e = EEXIST;
        errno = e;
        return NULL;
    }
#if defined(_WIN32)
    f = _fdopen(fd, "wb");
    if (!f) {
        e = errno;
        _close(fd);
        remove(path);
        errno = e;
    }
#else
    f = fdopen(fd, "wb");
    if (!f) {
        e = errno;
        close(fd);
        remove(path);
        errno = e;
    }
#endif
    return f;
}

#include "cft.h"

/* refuse() never returns, and its message is a printf format. mingw-w64
 * names the archetype its stdio really is; elsewhere it is printf. */
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

#define HEADER_BYTES  32
#define SALT_BYTES    32
#define MAX_HSLOTS    512      /* h-slots at most, and each below it */
#define MAX_NAME      64       /* a parameter's name, at most */
#define FLAGS_KNOWN   (CFT_PROG_FLAG_BANK_EXT | CFT_PROG_FLAG_SCRATCH_IO | \
                       CFT_PROG_FLAG_SCRATCH_STRICT)

/* The domain tags (docs/CERTIFICATES.md, "Hashes"). Each length is
 * stated, not left to a terminator: a state's and a stream's tag END IN
 * a NUL byte, which is the separator the page puts before the bytes,
 * and the salt's has none. */
static const char TAG_SALT[]     = "cft-certificate 1 salt";
#define TAG_SALT_LEN   (sizeof TAG_SALT - 1)        /* 22, no NUL */
static const char TAG_STATE[]    = "cft-certificate 1 state";
#define TAG_STATE_LEN  (sizeof TAG_STATE)           /* 24, the NUL included */
static const char TAG_STREAM_A[] = "cft-certificate 1 stream a";
static const char TAG_STREAM_B[] = "cft-certificate 1 stream b";
static const char TAG_STREAM_C[] = "cft-certificate 1 stream c";
#define TAG_STREAM_LEN (sizeof TAG_STREAM_A)        /* 27, the NUL included */

static const char *const FORMAT_NAME[4] = { "fp32", "fp64", "fp128", "fp256" };

/* ---- refusals ---------------------------------------------------------- */

static const struct { const char *name; int code; } REFUSAL[] = {
    /* the page's names: the inputs a writer refuses */
    { "malformed", 2 }, { "line-order", 2 }, { "line-unexpected", 2 },
    { "salt-length", 4 }, { "program-image", 4 }, { "program-shape", 4 },
    { "state-shape", 4 },
    /* the tool's own (docs/CERTIFICATES.md, "The segment runner") */
    { "usage", 64 }, { "device", 69 }, { "memory", 71 }, { "output", 73 },
};

/* What a refusal must undo: the certificate this run created is
 * removed, and the states directory this run created is removed while
 * it is still empty. Both were created new (create_new, mkdir), so
 * nothing here is ever a file the run did not make. */
static const char *CERT_PATH = NULL;
static FILE *CERT_FP = NULL;
static const char *STATES_DIR = NULL;
static int STATES_CREATED = 0;
static unsigned long long STATE_FILES = 0;

/* CFT_SEGRUN_PLANT, the instrument (the header comment). */
static int PLANT_UNREADABLE = 0, PLANT_UNWRITTEN = 0, PLANT_WIDE = 0;
static int PLANT_NO_TRIAL = 0;

static void cleanup(void)
{
    if (CERT_FP) {
        fclose(CERT_FP);
        CERT_FP = NULL;
        remove(CERT_PATH);
    }
    if (STATES_CREATED && STATE_FILES == 0) {
        RMDIR(STATES_DIR);
        STATES_CREATED = 0;
    } else if (STATES_CREATED) {
        fprintf(stderr, "cft-segrun: no certificate was written; the %llu "
                "boundary state file%s written so far %s left in %s\n",
                STATE_FILES, STATE_FILES == 1 ? "" : "s",
                STATE_FILES == 1 ? "is" : "are", STATES_DIR);
    }
}

static void refuse(const char *name, const char *fmt, ...)
    NORETURN PRINTF_LIKE(2, 3);
static void refuse_st(const char *name, const char *what, cft_status st)
    NORETURN;

static void refuse(const char *name, const char *fmt, ...)
{
    va_list ap;
    size_t i;
    int code = -1;
    for (i = 0; i < sizeof REFUSAL / sizeof REFUSAL[0]; i++)
        if (!strcmp(REFUSAL[i].name, name))
            code = REFUSAL[i].code;
    if (code < 0) {
        fprintf(stderr, "cft-segrun: internal error: unnamed refusal '%s'\n",
                name);
        cleanup();
        exit(70);
    }
    fprintf(stderr, "cft-segrun: refused %s: ", name);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    cleanup();
    exit(code);
}

/* cft_last_error() before the calls refuse_st reports on, once a call
 * whose failure the tool expects has left its sentence there (identify's
 * cft_get_image_id, on the software backend and through a remote one). A
 * sentence can outlive its call (cft.h): the one a failure reports must
 * be one it wrote, so the same sentence as before is not shown. */
static char LAST_BEFORE[512];

static void refuse_st(const char *name, const char *what, cft_status st)
{
    const char *detail = cft_last_error();
    int fresh = detail && *detail &&
                strncmp(detail, LAST_BEFORE, sizeof LAST_BEFORE - 1) != 0;
    refuse(name, "%s: %s%s%s", what, cft_strerror(st), fresh ? " - " : "",
           fresh ? detail : "");
}

/* Every allocation of the tool's that fails is refused by name, `memory`.
 * What a run's size decides is tried before anything is made (try_runs)
 * and taken again as the run reaches it (run_take); this is the rest:
 * the inputs as they are read, the command line's lists, a hash's
 * buffer, a boundary file's path, and the certificate's text. */
static void *xcalloc(size_t n, size_t sz)
{
    void *p;
    if (sz && n > (size_t)-1 / sz)
        p = NULL;
    else
        p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        refuse("memory", "%llu x %llu bytes could not be allocated",
               (unsigned long long)n, (unsigned long long)sz);
    return p;
}

/* ---- files ------------------------------------------------------------- */

/* The whole file, or NULL with errno set. */
static uint8_t *read_file(const char *path, size_t *n_out)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf;
    size_t cap = 1 << 16, have = 0;
    if (!f)
        return NULL;
    buf = (uint8_t *)xcalloc(cap, 1);
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *bigger = (uint8_t *)xcalloc(cap, 2);
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
        refuse("usage", "%s %s cannot be read (%s)", what, path,
               strerror(errno));
    return p;
}

static uint32_t get_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- the page's spellings ---------------------------------------------- */

/* A decimal integer in its one spelling - 0, or a nonzero digit and
 * digits - at most 2^63 - 1. Nineteen digits cannot wrap a uint64. */
static int dec_ok(const char *s, uint64_t *out)
{
    size_t i, n = strlen(s);
    uint64_t v = 0;
    if (n == 0 || n > 19 || (s[0] == '0' && n > 1))
        return 0;
    for (i = 0; i < n; i++) {
        if (s[i] < '0' || s[i] > '9')
            return 0;
        v = v * 10u + (uint64_t)(s[i] - '0');
    }
    if (v > (uint64_t)INT64_MAX)
        return 0;
    *out = v;
    return 1;
}

/* A name: a lowercase letter, then lowercase letters, digits and '-',
 * at most 64 characters. */
static int name_ok(const char *s, size_t n)
{
    size_t i;
    if (n == 0 || n > MAX_NAME || s[0] < 'a' || s[0] > 'z')
        return 0;
    for (i = 1; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9') ||
              s[i] == '-'))
            return 0;
    return 1;
}

/* cft_build_id()'s grammar, as the page's reader holds the build-id line
 * to it: `unknown` whole, or its three fields in their order. */
static int build_id_ok(const char *s)
{
    size_t n = 0;
    const char *p;
    if (!strcmp(s, "unknown"))
        return 1;
    if (strncmp(s, "commit=", 7) != 0)
        return 0;
    p = s + 7;
    while ((p[n] >= '0' && p[n] <= '9') || (p[n] >= 'a' && p[n] <= 'f'))
        n++;
    if (n != 40 && n != 64)
        return 0;
    p += n;
    if (!strncmp(p, " tracked=clean", 14))
        p += 14;
    else if (!strncmp(p, " tracked=modified", 17))
        p += 17;
    else
        return 0;
    return !strcmp(p, " untracked=none") || !strcmp(p, " untracked=present");
}

static void hex_of(const uint8_t *in, size_t n, char *out)
{
    static const char D[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[2 * n] = 0;
}

/* ---- the hashes ---------------------------------------------------------- */

static void sha256_of(const void *data, size_t n, uint8_t out[32])
{
    cft_status st = cft_sha256(data, n, out);
    if (st != CFT_OK)
        refuse_st("device", "cft_sha256", st);
}

/* HMAC-SHA-256 (RFC 2104, B = 64) of tag || msg under a 32-byte key.
 * The key is shorter than the block, so it is its own K0, zero-padded;
 * cft_sha256 is one-shot, so each pass hashes one buffer, taken for the
 * hash and let go after it - never held while the library runs a
 * segment, which has buffers of its own. */
static void hmac_sha256(const uint8_t key[SALT_BYTES],
                        const void *tag, size_t tag_len,
                        const void *msg, size_t msg_len, uint8_t out[32])
{
    uint8_t *inner = (uint8_t *)xcalloc(64 + tag_len + msg_len, 1);
    uint8_t outer[64 + 32], ih[32];
    size_t i;
    for (i = 0; i < 64; i++) {
        uint8_t k = i < SALT_BYTES ? key[i] : 0;
        inner[i] = (uint8_t)(k ^ 0x36);
        outer[i] = (uint8_t)(k ^ 0x5c);
    }
    if (tag_len)
        memcpy(inner + 64, tag, tag_len);
    if (msg_len)
        memcpy(inner + 64 + tag_len, msg, msg_len);
    sha256_of(inner, 64 + tag_len + msg_len, ih);
    free(inner);
    memcpy(outer + 64, ih, 32);
    sha256_of(outer, sizeof outer, out);
}

/* The hash of tag || bytes: keyed under `salt`, or open (plain SHA-256)
 * when `salt` is NULL. */
static void tagged_hash(const uint8_t *salt, const char *tag, size_t tag_len,
                        const void *bytes, size_t n, char hex[65])
{
    uint8_t d[32];
    if (salt) {
        hmac_sha256(salt, tag, tag_len, bytes, n, d);
    } else {
        uint8_t *buf = (uint8_t *)xcalloc(tag_len + n, 1);
        memcpy(buf, tag, tag_len);
        if (n)
            memcpy(buf + tag_len, bytes, n);
        sha256_of(buf, tag_len + n, d);
        free(buf);
    }
    hex_of(d, 32, hex);
}

static void state_hash(const uint8_t *salt, const void *bytes, size_t n,
                       char hex[65])
{
    tagged_hash(salt, TAG_STATE, TAG_STATE_LEN, bytes, n, hex);
}

static const char *stream_tag(int which)
{
    return which == 0 ? TAG_STREAM_A : which == 1 ? TAG_STREAM_B
                                                   : TAG_STREAM_C;
}

static void salt_commitment(const uint8_t *salt, char hex[65])
{
    uint8_t d[32];
    hmac_sha256(salt, TAG_SALT, TAG_SALT_LEN, NULL, 0, d);
    hex_of(d, 32, hex);
}

/* ---- the image header, read before the library sees the bytes --------- */

typedef struct {
    uint32_t n_insns, n_consts, max_deposits, prec, flags;
    uint32_t n_in, n_out;
} header;

/* NULL when the header describes these bytes, else why not. */
static const char *parse_header(const uint8_t *img, size_t n, header *H,
                                char *why, size_t cap)
{
    uint32_t scratch_io;
    uint64_t want, esz;
    if (n < HEADER_BYTES) {
        snprintf(why, cap, "it is %lu bytes, shorter than a %d-byte header",
                 (unsigned long)n, HEADER_BYTES);
        return why;
    }
    if (get_le32(img) != 0x50544643u)
        return "it does not begin with CFTP";
    if (get_le32(img + 4) != 1u) {
        snprintf(why, cap, "program version %u; version 1 is the one there is",
                 (unsigned)get_le32(img + 4));
        return why;
    }
    H->n_insns      = get_le32(img + 8);
    H->n_consts     = get_le32(img + 12);
    H->max_deposits = get_le32(img + 16);
    H->prec         = get_le32(img + 20);
    H->flags        = get_le32(img + 24);
    scratch_io      = get_le32(img + 28);
    if (H->prec > 3) {
        snprintf(why, cap, "precision code %u is not on the ladder",
                 (unsigned)H->prec);
        return why;
    }
    if (H->flags & ~(uint32_t)FLAGS_KNOWN) {
        snprintf(why, cap, "header flags 0x%08x set a bit no revision assigns",
                 (unsigned)H->flags);
        return why;
    }
    if (!(H->flags & CFT_PROG_FLAG_SCRATCH_IO) && scratch_io)
        return "header word 7 is not zero, and flags.SCRATCH_IO does not say "
               "it is scratch_io";
    H->n_in  = scratch_io & 0xFFFFu;
    H->n_out = (scratch_io >> 16) & 0xFFFFu;
    esz = cft_format_size((cft_format)H->prec);
    want = HEADER_BYTES + (uint64_t)H->n_insns * 8u +
           ((H->flags & CFT_PROG_FLAG_BANK_EXT) ? 0u
                                                : (uint64_t)H->n_consts * esz);
    if (want != (uint64_t)n) {
        snprintf(why, cap, "it is %lu bytes, and its header describes %llu",
                 (unsigned long)n, (unsigned long long)want);
        return why;
    }
    return NULL;
}

/* NULL when the program is a segment (the page's "A program is a
 * segment"), else why not - the golden writer's words. */
static const char *segment_shape(const header *H, char *why, size_t cap)
{
    if (!(H->flags & CFT_PROG_FLAG_SCRATCH_IO))
        return "it declares no scratch block (flags.SCRATCH_IO clear)";
    if (H->n_in != H->n_out || H->n_in < 1) {
        snprintf(why, cap, "its scratch block goes in as %u and out as %u "
                 "slots a lane; a segment's end state must be the next one's "
                 "start", (unsigned)H->n_in, (unsigned)H->n_out);
        return why;
    }
    if (H->max_deposits) {
        snprintf(why, cap, "it deposits (%u slots a lane); version 1 "
                 "certifies the scratch state only, and a deposit would go "
                 "uncertified", (unsigned)H->max_deposits);
        return why;
    }
    return NULL;
}

/* ---- one run --------------------------------------------------------- */

enum { K_MAIN, K_HALF, K_WIDER };
static const char *const KIND_NAME[3] = { "main", "half-step", "wider" };

typedef struct {
    int kind;
    const char *image_path, *bank_path, *init_path;
    const char *segments_s, *steps_s, *hslots_s;
    const char **param_s;
    size_t n_param_s;

    /* read and checked */
    uint8_t *img, *bank, *init;
    size_t img_bytes, bank_bytes, init_bytes;
    header H;
    size_t esz, lanes, state_bytes;
    uint64_t segments, steps;
    unsigned hslots[MAX_HSLOTS];
    size_t n_hslots;

    /* made */
    cft_program *prog;
    char image_digest[65], program_digest[65];
    char stream_hash[3][65];
    char (*hash)[65];           /* boundaries 0..S */
    uint32_t *flags, *status;   /* segments 0..S-1 */
} run_spec;

static void add_param(run_spec *r, const char *s)
{
    const char **grown = (const char **)xcalloc(r->n_param_s + 1,
                                                sizeof *grown);
    if (r->n_param_s)
        memcpy(grown, r->param_s, r->n_param_s * sizeof *grown);
    free(r->param_s);
    grown[r->n_param_s++] = s;
    r->param_s = grown;
}

/* Everything about run `idx` that can be refused before a device is
 * opened, in the golden writer's order: the image loads, it is a
 * segment, its bank, its initial state; then the counts and the
 * parameters the reader would refuse. */
static void check_run(run_spec *r, size_t idx)
{
    char why[256];
    const char *bad;
    uint64_t v;

    if (idx == 0 && r->kind != K_MAIN)
        refuse("malformed", "run 0 is 'run 0 main'; this certificate's first "
               "run is %s", KIND_NAME[r->kind]);
    if (idx > 0 && r->kind == K_MAIN)
        refuse("malformed", "run 0, and only run 0, is 'run 0 main'; run %lu "
               "is main too", (unsigned long)idx);
    if (!r->image_path || !r->init_path || !r->segments_s || !r->steps_s)
        refuse("usage", "run %lu (%s) needs --image, --init, --segments and "
               "--steps", (unsigned long)idx, KIND_NAME[r->kind]);
    if (r->hslots_s && r->kind != K_HALF)
        refuse("usage", "run %lu is %s: --h-slots belongs to a half-step run",
               (unsigned long)idx, KIND_NAME[r->kind]);

    /* the image */
    r->img = read_named("the image", r->image_path, &r->img_bytes);
    bad = parse_header(r->img, r->img_bytes, &r->H, why, sizeof why);
    if (bad)
        refuse("program-image", "run %lu: %s does not load: %s",
               (unsigned long)idx, r->image_path, bad);
    r->esz = cft_format_size((cft_format)r->H.prec);
    bad = segment_shape(&r->H, why, sizeof why);
    if (bad)
        refuse("program-shape", "run %lu: %s is not a segment: %s",
               (unsigned long)idx, r->image_path, bad);

    /* its bank */
    if (r->bank_path)
        r->bank = read_named("the bank", r->bank_path, &r->bank_bytes);
    if (r->H.flags & CFT_PROG_FLAG_BANK_EXT) {
        uint64_t want = (uint64_t)r->H.n_consts * r->esz;
        if ((uint64_t)r->bank_bytes != want)
            refuse("program-image", "run %lu: the bank is %lu bytes; the "
                   "image addresses %u constants of %lu bytes, %llu in all",
                   (unsigned long)idx, (unsigned long)r->bank_bytes,
                   (unsigned)r->H.n_consts, (unsigned long)r->esz,
                   (unsigned long long)want);
    } else if (r->bank_bytes) {
        refuse("program-image", "run %lu: this image carries its own "
               "constants, so the bank must be empty; %s is %lu bytes",
               (unsigned long)idx, r->bank_path, (unsigned long)r->bank_bytes);
    }

    /* its initial state */
    r->init = read_named("the initial state", r->init_path, &r->init_bytes);
    {
        size_t lane = (size_t)r->H.n_in * r->esz;
        /* Empty is a state of no lanes, and `lanes` is at least 1: the
         * wrong size, like a part of a lane. (The golden writer has no
         * name for the empty case: cert.run_chain hands seq.run an empty
         * block and it raises seq.ProgramError.) */
        if (r->init_bytes == 0 || r->init_bytes % lane)
            refuse("state-shape", "run %lu: %s is %lu bytes, not a whole "
                   "number of lanes, at least one, of %u %s slots (%lu "
                   "bytes a lane, lane-major)", (unsigned long)idx,
                   r->init_path, (unsigned long)r->init_bytes,
                   (unsigned)r->H.n_in, FORMAT_NAME[r->H.prec],
                   (unsigned long)lane);
        r->lanes = r->init_bytes / lane;
        r->state_bytes = r->init_bytes;
    }

    /* the counts */
    if (!dec_ok(r->segments_s, &v) || v < 1)
        refuse("malformed", "run %lu: segments '%s' is not a decimal "
               "integer from 1 to 2^63 - 1 in its one spelling",
               (unsigned long)idx, r->segments_s);
    r->segments = v;
    if (!dec_ok(r->steps_s, &v) || v < 1)
        refuse("malformed", "run %lu: steps '%s' is not a decimal integer "
               "from 1 to 2^63 - 1 in its one spelling", (unsigned long)idx,
               r->steps_s);
    r->steps = v;

    /* the h-slots */
    if (r->kind == K_HALF) {
        const char *p = r->hslots_s;
        if (!p)
            refuse("malformed", "run %lu is half-step, and a half-step run "
                   "names 1 to %d h-slots (--h-slots I,J,...)",
                   (unsigned long)idx, MAX_HSLOTS);
        for (;;) {
            char tok[24];
            size_t n = strcspn(p, ",");
            if (n == 0 || n >= sizeof tok)
                refuse("malformed", "run %lu: --h-slots '%s' is not a list "
                       "of decimal slot indices separated by commas",
                       (unsigned long)idx, r->hslots_s);
            memcpy(tok, p, n);
            tok[n] = 0;
            if (!dec_ok(tok, &v) || v >= MAX_HSLOTS)
                refuse("malformed", "run %lu: h-slot '%s' is not a decimal "
                       "index below %d in its one spelling",
                       (unsigned long)idx, tok, MAX_HSLOTS);
            if (r->n_hslots == MAX_HSLOTS)
                refuse("malformed", "run %lu: more than %d h-slots",
                       (unsigned long)idx, MAX_HSLOTS);
            if (r->n_hslots && v <= r->hslots[r->n_hslots - 1])
                refuse("malformed", "run %lu: h-slot indices are strictly "
                       "increasing, and %s follows %u", (unsigned long)idx,
                       tok, r->hslots[r->n_hslots - 1]);
            r->hslots[r->n_hslots++] = (unsigned)v;
            if (!p[n])
                break;
            p += n + 1;
        }
    }

    /* the parameters, as the reader takes each line: the name's spelling,
     * then its place in byte order, then the value */
    {
        size_t k;
        const char *prev = NULL;
        size_t prev_n = 0;
        for (k = 0; k < r->n_param_s; k++) {
            const char *s = r->param_s[k];
            const char *eq = strchr(s, '=');
            size_t n = eq ? (size_t)(eq - s) : strlen(s);
            int c;
            if (!eq || !name_ok(s, n))
                refuse("malformed", "run %lu: --param '%s' is not NAME=N with "
                       "NAME a lowercase letter, then lowercase letters, "
                       "digits and '-', at most %d", (unsigned long)idx, s,
                       MAX_NAME);
            if (prev) {
                c = memcmp(prev, s, prev_n < n ? prev_n : n);
                if (c == 0)
                    c = prev_n < n ? -1 : prev_n > n ? 1 : 0;
                if (c == 0)
                    refuse("line-unexpected", "run %lu: parameter '%.*s' "
                           "again", (unsigned long)idx, (int)n, s);
                if (c > 0)
                    refuse("line-order", "run %lu: parameter '%.*s' comes "
                           "after '%.*s'; names are in increasing byte order",
                           (unsigned long)idx, (int)n, s, (int)prev_n, prev);
            }
            if (!dec_ok(eq + 1, &v))
                refuse("malformed", "run %lu: parameter '%.*s' = '%s' is not "
                       "a decimal integer from 0 to 2^63 - 1 in its one "
                       "spelling", (unsigned long)idx, (int)n, s, eq + 1);
            prev = s;
            prev_n = n;
        }
    }
}

/* ---- the certificate's text --------------------------------------------- */

typedef struct {
    char  *p;
    size_t n, cap;
} text;

static void put(text *t, const char *fmt, ...) PRINTF_LIKE(2, 3);

static void put(text *t, const char *fmt, ...)
{
    va_list ap;
    int len;
    va_start(ap, fmt);
    len = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (len < 0)
        refuse("output", "a certificate line could not be formatted");
    if (t->n + (size_t)len + 1 > t->cap) {
        size_t cap = t->cap ? t->cap : 4096;
        char *grown;
        while (t->n + (size_t)len + 1 > cap)
            cap *= 2;
        grown = (char *)xcalloc(cap, 1);
        if (t->n)
            memcpy(grown, t->p, t->n);
        free(t->p);
        t->p = grown;
        t->cap = cap;
    }
    va_start(ap, fmt);
    vsnprintf(t->p + t->n, (size_t)len + 1, fmt, ap);
    va_end(ap);
    t->n += (size_t)len;
}

/* ---- identity ------------------------------------------------------------ */

typedef struct {
    const char *build_id;
    const char *backend;        /* one of the page's four words */
    char xclbin[72], version[16], caps[24], tiles[24];
} identity;

static void identify(cft_device *dev, const cft_caps *caps, identity *id)
{
    cft_image_id im;
    cft_status st;
    int sw = !strcmp(caps->backend, "software");
    int remote = !strcmp(caps->backend, "remote");

    id->build_id = cft_build_id();
    if (!id->build_id || !build_id_ok(id->build_id))
        refuse("malformed", "cft_build_id() returned '%s', which is not the "
               "page's grammar; the build-id line is that string verbatim, "
               "so no certificate can be written from it",
               id->build_id ? id->build_id : "(null)");

    id->backend = sw ? "software" : remote ? "remote"
                : !strcmp(caps->backend, "xrt") ? "xrt" : "unknown";

    memset(&im, 0, sizeof im);
    im.struct_size = sizeof im;
    st = cft_get_image_id(dev, &im);
    if (st == CFT_OK && im.struct_size >= offsetof(cft_image_id, caps) +
                                            2 * sizeof im.caps[0]) {
        hex_of(im.sha256, 32, id->xclbin);
        snprintf(id->version, sizeof id->version, "%08x", (unsigned)im.version);
        if (im.n_caps == 1)
            snprintf(id->caps, sizeof id->caps, "%08x", (unsigned)im.caps[0]);
        else if (im.n_caps == 2)
            snprintf(id->caps, sizeof id->caps, "%08x %08x",
                     (unsigned)im.caps[0], (unsigned)im.caps[1]);
        else
            snprintf(id->caps, sizeof id->caps, "unknown");
    } else if (sw) {
        /* no xclbin and no registers: the fields do not exist here */
        snprintf(id->xclbin, sizeof id->xclbin, "none");
        snprintf(id->version, sizeof id->version, "none");
        snprintf(id->caps, sizeof id->caps, "none");
    } else {
        snprintf(id->xclbin, sizeof id->xclbin, "unknown");
        snprintf(id->caps, sizeof id->caps, "unknown");
        if (remote && caps->device_version)
            snprintf(id->version, sizeof id->version, "%08x",
                     (unsigned)caps->device_version);
        else
            snprintf(id->version, sizeof id->version, "unknown");
    }
    if (caps->tiles >= 1)
        snprintf(id->tiles, sizeof id->tiles, "%u", (unsigned)caps->tiles);
    else
        snprintf(id->tiles, sizeof id->tiles, "unknown");
}

/* ---- the states directory ---------------------------------------------- */

/* A boundary file's path: the directory's name, "/run-", 20 digits,
 * "-boundary-", 20, ".bin". */
#define PATH_TAIL 64

static void write_boundary(size_t r, uint64_t b, const void *state, size_t n)
{
    size_t cap = strlen(STATES_DIR) + PATH_TAIL;
    char *path = (char *)xcalloc(cap, 1);
    FILE *f;
    snprintf(path, cap, "%s/run-%lu-boundary-%llu.bin", STATES_DIR,
             (unsigned long)r, (unsigned long long)b);
    /* created new: the directory is the run's own, so a file already
     * there is one this run did not make, and it is left as it is */
    f = create_new(path);
    if (!f)
        refuse("output", "%s cannot be created (%s)", path,
               errno == EEXIST ? "a file this run did not make is there "
                                 "already" : strerror(errno));
    STATE_FILES++;
    if (fwrite(state, 1, n, f) != n) {
        fclose(f);
        refuse("output", "a short write to %s", path);
    }
    if (fclose(f) != 0)
        refuse("output", "%s could not be closed (%s)", path, strerror(errno));
    free(path);
}

/* ---- what every run needs, tried before anything is created or run --- */

/* The certificate's text. At most, for the count against what the
 * process can address: a segment's line is 195 bytes ("segment " and 19
 * digits, " start " and 64, " end " and 64, " flags " and 2, " status "
 * and 10, and its LF); a run block's other lines are under 1 KiB beside
 * its h-slots (4 bytes each) and parameters (under 100 each); the
 * header, `accuracy`, `end` and the hash line under 1 KiB. At the least,
 * for the trial: the segment lines alone, each at least 167 bytes (one
 * digit where the most is 19, 2 and 10). */
#define SEGMENT_TEXT     200
#define SEGMENT_TEXT_MIN 167
#define RUN_TEXT         4096
#define HSLOT_TEXT       4
#define PARAM_TEXT       100
#define HEAD_TEXT        2048

static int mul_ok(size_t a, size_t b, size_t *out)
{
    if (b && a > (size_t)-1 / b)
        return 0;
    *out = a * b;
    return 1;
}

static int add_ok(size_t *acc, size_t v)
{
    if (*acc > (size_t)-1 - v)
        return 0;
    *acc += v;
    return 1;
}

/* ---- the trial ------------------------------------------------------------
 *
 * The runs allocate as 99f1b43's tool did, and hold no more at once: a
 * run's boundary hashes, flag words and STATUS when it starts, kept for
 * the certificate; its two states and its +0 streams, let go when it
 * ends; a hash's buffer and a boundary file's path for as long as each
 * takes; the certificate's text last, grown as it is written. So a run
 * beside the main run costs its own inputs and hashes, never a second
 * working set (verifier-C7, 2026-09-28: 4eed552 held every run's states
 * at once, and refused under a limit a certificate 99f1b43 writes). They
 * hold a little less than 99f1b43's did: each image is let go once the
 * library has loaded and digested it, each initial state once it is
 * copied into the run's first state.
 *
 * Before anything is made, try_runs counts all of it against what the
 * process can address, and then tries, in the runs' own order, the
 * pieces their size decides: each run's hashes, flag words and STATUS,
 * kept; its two states and its streams, taken and let go; the
 * certificate's text last, at the least it can be. A run the process
 * cannot have is refused `memory` then, with nothing made.
 *
 * The trial takes nothing from the C library's heap. Every piece comes
 * from the operating system, rounded down to whole pages (a piece under
 * a page is not tried), and so does the trial's own list of what it
 * holds; all of it is given back before the outputs are made. So the
 * runs allocate from the heap they would have had without the trial,
 * and the trial costs them nothing - which the gate holds to the page on
 * Linux (verifier-C7, 2026-09-29: at eb2d1ae the pieces under 64 KiB
 * came from calloc, left the heap up to 40 KiB bigger, and 99f1b43 wrote
 * certificates under limits eb2d1ae refused).
 *
 * The trial holds no hash's buffer and no library, device or program -
 * at each run, less than 99f1b43's tool held there. But it holds every
 * run's initial state throughout, as 99f1b43's runs did, where the runs
 * now let each go once it is copied: so the trial can need more than the
 * runs themselves (verifier-C7's `up` shape, about 10 MB), and refuse a
 * certificate they alone could have written, which 99f1b43 could not
 * write either.
 *
 * What the trial cannot promise: a hash's buffer and a boundary file's
 * path; a piece under a page; the library's own memory, which fails as
 * `program-image` or `device`; and memory the machine gives others
 * between the trial and the run. A piece of the tool's that cannot be
 * had after the trial had it is still refused `memory`, part way. Where
 * the operating system has no anonymous mapping, the trial is its size
 * checks alone. */

typedef struct {
    void *p;
    size_t n;
} trial;

#if defined(_WIN32) || defined(SEG_MAP_ANON)
#  define TRIAL_OS 1

static size_t page_size(void)
{
#  if defined(_WIN32)
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    return si.dwPageSize ? (size_t)si.dwPageSize : 4096;
#  else
    long p = sysconf(_SC_PAGESIZE);
    return p > 0 ? (size_t)p : 4096;
#  endif
}

/* `n` bytes, a whole number of pages, from the operating system, or
 * NULL: never from the C library's heap. */
static void *os_take(size_t n)
{
#  if defined(_WIN32)
    return VirtualAlloc(NULL, n, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
#  else
    void *p = mmap(NULL, n, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | SEG_MAP_ANON, -1, 0);
    return p == MAP_FAILED ? NULL : p;
#  endif
}

static void os_give(void *p, size_t n)
{
#  if defined(_WIN32)
    (void)n;
    VirtualFree(p, 0, MEM_RELEASE);
#  else
    munmap(p, n);
#  endif
}

/* `bytes` tried: rounded down to whole pages and taken from the operating
 * system - the runs' own allocation of it, the C library's with its
 * header, can only be larger - or, under a page, not tried at all. 0
 * only if the operating system refuses it. */
static int trial_take(trial *t, size_t bytes)
{
    size_t pg = page_size();
    t->p = NULL;
    t->n = bytes / pg * pg;
    if (t->n == 0)
        return 1;
    t->p = os_take(t->n);
    return t->p != NULL;
}

static void trial_give(trial *t)
{
    if (t->p)
        os_give(t->p, t->n);
    t->p = NULL;
    t->n = 0;
}

/* One piece of the trial: `n` x `sz` bytes for `what`, of run `r` (or of
 * the certificate, for r = -1), or the refusal. */
static void trial_or_refuse(trial *t, size_t n, size_t sz, long r,
                            const char *what)
{
    size_t bytes;
    char who[32] = "";
    if (r >= 0)
        snprintf(who, sizeof who, "run %ld: ", r);
    if (!mul_ok(n, sz, &bytes) || !trial_take(t, bytes))
        refuse("memory", "%s%llu x %llu bytes for %s could not be had; what "
               "the runs need is tried, in the order they need it, before "
               "anything is made, so nothing was", who,
               (unsigned long long)n, (unsigned long long)sz, what);
}
#else
#  define TRIAL_OS 0
#endif

static void try_runs(const run_spec *runs, size_t n_runs, const char *states,
                     int keyed)
{
    size_t r, text_max = HEAD_TEXT, text_min = 0, cap = 4096;
    size_t path = strlen(states) + PATH_TAIL;
    size_t lead = keyed ? 64 : 0;      /* the HMAC's key block */

    /* every size, against what the process can address */
    for (r = 0; r < n_runs; r++) {
        const run_spec *R = &runs[r];
        size_t S = (size_t)R->segments, h, a, tmax, tmin, b;
        int ok = (uint64_t)S == R->segments && S < (size_t)-1 &&
                 mul_ok(S + 1, sizeof *R->hash, &h) &&
                 mul_ok(S, 2 * sizeof(uint32_t), &a) && add_ok(&h, a) &&
                 mul_ok(S, SEGMENT_TEXT, &tmax) && add_ok(&tmax, RUN_TEXT) &&
                 add_ok(&tmax, R->n_hslots * HSLOT_TEXT) &&
                 add_ok(&tmax, R->n_param_s * PARAM_TEXT) &&
                 add_ok(&text_max, tmax) &&
                 mul_ok(S, SEGMENT_TEXT_MIN, &tmin) &&
                 add_ok(&text_min, tmin);
        if (!ok)
            refuse("memory", "run %lu: %llu segments need more memory than "
                   "this process can address - the boundary hashes, flag "
                   "words and STATUS, or the certificate's text", (unsigned
                   long)r, (unsigned long long)R->segments);
        b = R->state_bytes > R->lanes * R->esz ? R->state_bytes
                                               : R->lanes * R->esz;
        if (!add_ok(&b, lead + TAG_STREAM_LEN) || !add_ok(&b, path))
            refuse("memory", "run %lu: its state is past what this process "
                   "can address", (unsigned long)r);
    }
    while (cap - 1 < text_min) {
        if (cap > (size_t)-1 / 2)
            refuse("memory", "the certificate's text, at least %llu bytes, "
                   "is more than this process can address",
                   (unsigned long long)text_min);
        cap *= 2;
    }
    if (PLANT_NO_TRIAL)
        return;

#if TRIAL_OS
    {
        /* tried in the order the runs need it: each run's hashes, flag
         * words and STATUS kept, as the certificate keeps them; its two
         * states and its streams taken and let go, as the run lets them
         * go. The list of what is kept is the operating system's too. */
        size_t pg = page_size(), list, i;
        trial *kept, now[3];
        if (!mul_ok(3 * sizeof *kept, n_runs, &list) ||
            !add_ok(&list, pg - 1))
            refuse("memory", "the trial's list of %lu runs is more than "
                   "this process can address", (unsigned long)n_runs);
        list = list / pg * pg;
        kept = (trial *)os_take(list);
        if (!kept)
            refuse("memory", "%llu bytes for the trial's own list could not "
                   "be had; nothing was made", (unsigned long long)list);
        for (r = 0; r < n_runs; r++) {
            const run_spec *R = &runs[r];
            size_t S = (size_t)R->segments;
            long ri = (long)r;
            trial_or_refuse(&kept[3 * r], S + 1, sizeof *R->hash, ri,
                            "the boundary hashes");
            trial_or_refuse(&kept[3 * r + 1], S, sizeof(uint32_t), ri,
                            "the flag words");
            trial_or_refuse(&kept[3 * r + 2], S, sizeof(uint32_t), ri,
                            "STATUS");
            trial_or_refuse(&now[0], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[1], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[2], R->lanes, R->esz, ri, "the streams");
            for (i = 0; i < 3; i++)
                trial_give(&now[i]);
        }
        /* the certificate's text, beside every run's hashes, at the least
         * it can be and grown as put() grows it: 4096 doubled, the old
         * buffer and the new held together at the last doubling */
        now[0].p = NULL;
        now[0].n = 0;
        if (cap > 4096)
            trial_or_refuse(&now[0], cap / 2, 1, -1,
                            "the certificate's text");
        trial_or_refuse(&now[1], cap, 1, -1, "the certificate's text");
        trial_give(&now[0]);
        trial_give(&now[1]);
        for (i = 0; i < 3 * n_runs; i++)
            trial_give(&kept[i]);
        os_give(kept, list);
    }
#endif
}

/* A run's own allocation, as the trial took it: one that fails now is
 * refused by the same name, part way. */
static void *run_take(size_t n, size_t sz, size_t r, const char *what)
{
    void *p = (sz && n > (size_t)-1 / sz) ? NULL
            : calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        refuse("memory", "run %lu: %llu x %llu bytes for %s could not be "
               "had, although they could when tried before anything was "
               "made", (unsigned long)r, (unsigned long long)n,
               (unsigned long long)sz, what);
    return p;
}

/* ---- usage --------------------------------------------------------------- */

static void usage_text(FILE *f)
{
    fputs(
"cft-segrun - run a program as consecutive segments and write the certificate\n"
"(docs/CERTIFICATES.md, version 1; \"The segment runner\" is the manual)\n"
"\n"
"  cft-segrun --out CERT --states DIR (--salt SALT | --open)\n"
"             [--device sw|<xclbin>|cft://host:port]\n"
"             --run main --image IMG [--bank BANK] --init INIT\n"
"                        --segments S --steps K [--param NAME=N ...]\n"
"             [--run half-step --h-slots I,J,... --image IMG ...]\n"
"             [--run wider --image IMG ...]\n"
"  cft-segrun --hash state|stream-a|stream-b|stream-c FILE\n"
"             (--salt SALT | --open)\n"
"  cft-segrun --hash commitment --salt SALT\n"
"  cft-segrun --build-id\n"
"\n"
"  --out CERT      the certificate, written once every segment has run\n"
"  --states DIR    a NEW directory: DIR/run-<r>-boundary-<b>.bin, each the\n"
"                  lane-major scratch block at boundary b (0 = --init)\n"
"  --salt SALT     keyed: SALT is exactly 32 random bytes the owner keeps\n"
"  --open          open: plain SHA-256, no salt\n"
"  --device        the software backend (sw, the default), an .xclbin, or\n"
"                  a cft-serve at cft://host:port\n"
"  --run KIND      main first; then half-step or wider auxiliary runs\n"
"  --image IMG     the program image (.cftp), a segment: SCRATCH_IO, in = out\n"
"  --bank BANK     a BANK_EXT image's constants, n_consts values, raw\n"
"  --init INIT     the initial state: lanes x n_scratch_in elements, raw,\n"
"                  format-width, little-endian, lane-major\n"
"  --segments S    how many consecutive segments; each enters with the last\n"
"                  one's scratch-out\n"
"  --steps K       steps a segment: stated, not checked\n"
"  --param NAME=N  a non-negative integer parameter: stated, not checked;\n"
"                  names in increasing byte order\n"
"  --h-slots LIST  a half-step run's bank slots that carry the step\n"
"  --hash KIND     print one of the page's hashes of FILE, and exit\n"
"  --build-id      print cft_build_id(), which the build-id line carries\n"
"\n"
"The streams a, b and c are +0. Refusals are named on stderr as\n"
"\"cft-segrun: refused <name>: <why>\"; the exit code is the name's.\n", f);
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        refuse("usage", "%s needs a value", argv[*i]);
    return argv[++(*i)];
}

static void once(const char **slot, const char *opt, const char *v)
{
    if (*slot)
        refuse("usage", "%s is given twice", opt);
    *slot = v;
}

/* ---- --hash ------------------------------------------------------------ */

static int do_hash(const char *kind, const char *file, const uint8_t *salt)
{
    char hex[65];
    if (!strcmp(kind, "commitment")) {
        if (file)
            refuse("usage", "--hash commitment takes no file");
        if (!salt)
            refuse("usage", "--hash commitment needs --salt");
        salt_commitment(salt, hex);
    } else {
        uint8_t *bytes;
        size_t n = 0;
        int which = -1;
        if (!strcmp(kind, "state"))
            which = 3;
        else if (!strcmp(kind, "stream-a"))
            which = 0;
        else if (!strcmp(kind, "stream-b"))
            which = 1;
        else if (!strcmp(kind, "stream-c"))
            which = 2;
        else
            refuse("usage", "--hash %s: the kinds are state, stream-a, "
                   "stream-b, stream-c and commitment", kind);
        if (!file)
            refuse("usage", "--hash %s needs a file", kind);
        bytes = read_named("the file", file, &n);
        if (which == 3)
            state_hash(salt, bytes, n, hex);
        else
            tagged_hash(salt, stream_tag(which), TAG_STREAM_LEN, bytes, n,
                        hex);
        free(bytes);
    }
    printf("%s\n", hex);
    return 0;
}

/* ---- main -------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *out_path = NULL, *states_path = NULL, *salt_path = NULL;
    const char *device = NULL, *hash_kind = NULL, *hash_file = NULL;
    const char *plant = getenv("CFT_SEGRUN_PLANT");
    int open_mode = 0, want_build_id = 0, i;
    run_spec *runs = NULL;
    size_t n_runs = 0, r;
    uint8_t *salt = NULL;
    size_t salt_bytes = 0;
    cft_device *dev = NULL;
    cft_caps caps;
    cft_status st;
    identity id;
    text body;
    char commitment[65], hex[65];
    uint8_t digest[32];

    memset(&body, 0, sizeof body);
    if (plant && *plant) {
        if (!strcmp(plant, "flags-unreadable"))
            PLANT_UNREADABLE = 1;
        else if (!strcmp(plant, "flags-unwritten"))
            PLANT_UNWRITTEN = 1;
        else if (!strcmp(plant, "flags-wide"))
            PLANT_WIDE = 1;
        else if (!strcmp(plant, "trial-skipped"))
            PLANT_NO_TRIAL = 1;
        else
            refuse("usage", "CFT_SEGRUN_PLANT=%s is not an instrument this "
                   "tool has (flags-unreadable, flags-unwritten, "
                   "flags-wide, trial-skipped)", plant);
        fprintf(stderr, "cft-segrun: CFT_SEGRUN_PLANT=%s - an instrument: "
                "%s\n", plant, PLANT_NO_TRIAL ? "the trial's allocations "
                "are skipped, its size checks kept" : "this run is to be "
                "refused");
    }

    if (argc < 2) {
        usage_text(stderr);
        refuse("usage", "nothing to do");
    }
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        run_spec *cur = n_runs ? &runs[n_runs - 1] : NULL;
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) {
            usage_text(stdout);
            return 0;
        } else if (!strcmp(a, "--build-id")) {
            want_build_id = 1;
        } else if (!strcmp(a, "--hash")) {
            once(&hash_kind, a, need(argc, argv, &i));
            if (strcmp(hash_kind, "commitment") != 0)
                hash_file = need(argc, argv, &i);
        } else if (!strcmp(a, "--out")) {
            once(&out_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--states")) {
            once(&states_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--salt")) {
            once(&salt_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--open")) {
            if (open_mode)
                refuse("usage", "--open is given twice");
            open_mode = 1;
        } else if (!strcmp(a, "--device")) {
            once(&device, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--run")) {
            const char *k = need(argc, argv, &i);
            run_spec *grown;
            int kind;
            if (!strcmp(k, "main"))
                kind = K_MAIN;
            else if (!strcmp(k, "half-step"))
                kind = K_HALF;
            else if (!strcmp(k, "wider"))
                kind = K_WIDER;
            else
                refuse("usage", "--run %s: a run is main, half-step or wider",
                       k);
            grown = (run_spec *)xcalloc(n_runs + 1, sizeof *grown);
            if (n_runs)
                memcpy(grown, runs, n_runs * sizeof *grown);
            free(runs);
            runs = grown;
            memset(&runs[n_runs], 0, sizeof runs[n_runs]);
            runs[n_runs].kind = kind;
            n_runs++;
        } else if (!strcmp(a, "--image") || !strcmp(a, "--bank") ||
                   !strcmp(a, "--init") || !strcmp(a, "--segments") ||
                   !strcmp(a, "--steps") || !strcmp(a, "--h-slots") ||
                   !strcmp(a, "--param")) {
            const char *v = need(argc, argv, &i);
            if (!cur)
                refuse("usage", "%s belongs to a run: give it after --run",
                       a);
            if (!strcmp(a, "--image"))         once(&cur->image_path, a, v);
            else if (!strcmp(a, "--bank"))     once(&cur->bank_path, a, v);
            else if (!strcmp(a, "--init"))     once(&cur->init_path, a, v);
            else if (!strcmp(a, "--segments")) once(&cur->segments_s, a, v);
            else if (!strcmp(a, "--steps"))    once(&cur->steps_s, a, v);
            else if (!strcmp(a, "--h-slots"))  once(&cur->hslots_s, a, v);
            else                               add_param(cur, v);
        } else {
            refuse("usage", "unknown argument '%s' (--help lists them)", a);
        }
    }

    /* ---- the two small modes ---------------------------------------- */
    if (want_build_id) {
        if (argc != 2)
            refuse("usage", "--build-id takes nothing else");
        printf("%s\n", cft_build_id());
        return 0;
    }
    if (salt_path && open_mode)
        refuse("usage", "--salt and --open: a certificate is keyed or open, "
               "not both");
    if (salt_path) {
        salt = read_named("the salt", salt_path, &salt_bytes);
        if (salt_bytes != SALT_BYTES)
            refuse("salt-length", "a version-1 salt is exactly %d bytes; %s "
                   "is %lu", SALT_BYTES, salt_path,
                   (unsigned long)salt_bytes);
    }
    if (hash_kind) {
        if (out_path || states_path || device || n_runs)
            refuse("usage", "--hash takes a kind, a file and --salt or "
                   "--open, and nothing else");
        if (!salt && !open_mode && strcmp(hash_kind, "commitment") != 0)
            refuse("usage", "--hash %s needs --salt or --open", hash_kind);
        return do_hash(hash_kind, hash_file, salt);
    }

    /* ---- a certificate: the command line, then every input --------- */
    if (!out_path || !states_path)
        refuse("usage", "--out and --states are required");
    if (!salt_path && !open_mode)
        refuse("usage", "say --salt SALT (keyed) or --open");
    if (n_runs == 0)
        refuse("malformed", "a certificate has at least one run, and run 0 "
               "is main (--run main ...)");
    for (r = 0; r < n_runs; r++)
        check_run(&runs[r], r);

    /* ---- what every run needs, tried before anything is made ------------ */
    try_runs(runs, n_runs, states_path, salt != NULL);

    /* ---- the outputs, before any device work ----------------------------
     * Both created new, the certificate first: a file already at --out is
     * refused, never overwritten, and an --out inside --states cannot be
     * created at all, since --states must not exist yet - so the
     * certificate can never be one of the boundary files. */
    CERT_PATH = out_path;
    CERT_FP = create_new(out_path);
    if (!CERT_FP) {
        if (errno == EEXIST)
            refuse("output", "--out %s is there already; the certificate is "
                   "a new file, so that no run overwrites, and no refusal "
                   "removes, a file the run did not make", out_path);
        refuse("output", "--out %s cannot be created (%s)%s", out_path,
               strerror(errno), errno == ENOENT ? "; an --out inside "
               "--states, which this run creates and which must not exist "
               "yet, is refused this way" : "");
    }
    {
        /* a device opens "new" too (Windows' NUL): what was opened must be
         * a file, and a device is not this run's to remove */
        stat_t sb;
        if (FSTAT(FILENO(CERT_FP), &sb) != 0 || !IS_FILE(sb.st_mode)) {
            FILE *f = CERT_FP;
            CERT_FP = NULL;
            fclose(f);
            refuse("output", "--out %s is not a file, and the certificate is "
                   "one; a device or other special file there is left as it "
                   "is", out_path);
        }
    }
    STATES_DIR = states_path;
    if (MKDIR(states_path) != 0)
        refuse("output", "--states %s cannot be created (%s); it must be a "
               "new directory, so that no two runs' states mix",
               states_path, strerror(errno));
    STATES_CREATED = 1;

    /* ---- the device ----------------------------------------------------- */
    st = cft_open((device && strcmp(device, "sw") != 0) ? device : NULL, 0,
                  &dev);
    if (st != CFT_OK)
        refuse_st("device", "cft_open", st);
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    st = cft_get_caps(dev, &caps);
    if (st != CFT_OK)
        refuse_st("device", "cft_get_caps", st);
    if (PLANT_UNREADABLE)
        caps.flags_readable = 0;
    if (!caps.flags_readable)
        refuse("device", "this %s device cannot read the sticky flags, and a "
               "certificate records each segment's flag word%s",
               caps.backend, PLANT_UNREADABLE ? " (planted: "
               "CFT_SEGRUN_PLANT=flags-unreadable)" : "");

    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        cft_program_info info;
        const void *bank = R->bank_bytes ? R->bank : NULL;
        char where[64];
        snprintf(where, sizeof where, "run %lu: cft_program_load",
                 (unsigned long)r);
        st = cft_program_load(dev, R->img, R->img_bytes, &R->prog);
        if (st != CFT_OK)
            refuse_st("program-image", where, st);
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        st = cft_program_get_info(R->prog, &info);
        if (st != CFT_OK)
            refuse_st("device", "cft_program_get_info", st);
        if ((uint32_t)info.format != R->H.prec ||
            info.n_scratch_in != R->H.n_in ||
            info.n_scratch_out != R->H.n_out ||
            info.max_deposits != R->H.max_deposits)
            refuse("program-image", "run %lu: the library reads %s's header "
                   "differently from this tool", (unsigned long)r,
                   R->image_path);
        sha256_of(R->img, R->img_bytes, digest);
        hex_of(digest, 32, R->image_digest);
        /* the library holds its own copy of the image (cft_program_load),
         * and the certificate needs only its digest */
        free(R->img);
        R->img = NULL;
        st = cft_program_digest(R->prog, bank, R->bank_bytes, digest);
        if (st != CFT_OK)
            refuse_st("device", "cft_program_digest", st);
        hex_of(digest, 32, R->program_digest);
    }
    identify(dev, &caps, &id);
    snprintf(LAST_BEFORE, sizeof LAST_BEFORE, "%s", cft_last_error());

    /* ---- the runs, segment by segment ------------------------------------ */
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        const void *bank = R->bank_bytes ? R->bank : NULL;
        uint8_t *cur, *next, *zero;
        uint64_t k;
        int s;

        /* as the trial took them: this run's hashes, flag words and STATUS,
         * kept for the certificate; its two states and its streams, let go
         * when it ends, so no run holds another's */
        R->hash = (char (*)[65])run_take((size_t)R->segments + 1,
                                         sizeof *R->hash, r,
                                         "the boundary hashes");
        R->flags = (uint32_t *)run_take((size_t)R->segments,
                                        sizeof(uint32_t), r, "the flag words");
        R->status = (uint32_t *)run_take((size_t)R->segments,
                                         sizeof(uint32_t), r, "STATUS");
        cur = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        next = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        zero = (uint8_t *)run_take(R->lanes, R->esz, r, "the streams");
        memcpy(cur, R->init, R->state_bytes);
        /* boundary 0 is written and hashed from cur: the initial state is
         * not needed again */
        free(R->init);
        R->init = NULL;

        for (s = 0; s < 3; s++)
            tagged_hash(salt, stream_tag(s), TAG_STREAM_LEN, zero,
                        R->lanes * R->esz, R->stream_hash[s]);
        write_boundary(r, 0, cur, R->state_bytes);
        state_hash(salt, cur, R->state_bytes, R->hash[0]);

        for (k = 0; k < R->segments; k++) {
            cft_run_args ra;
            uint32_t fl = 0xFFFFFFFFu, bus = 0;
            uint8_t *t;
            memset(&ra, 0, sizeof ra);
            ra.struct_size = sizeof ra;
            ra.a = zero;
            ra.b = zero;
            ra.c = zero;
            ra.n = R->lanes;
            ra.bank = bank;
            ra.bank_bytes = R->bank_bytes;
            ra.scratch_in = cur;
            ra.scratch_in_bytes = R->state_bytes;
            ra.scratch_out = next;
            ra.scratch_out_bytes = R->state_bytes;
            ra.flags_out = &fl;
            ra.bus_out = &bus;
            st = cft_program_run_ex(R->prog, &ra);
            if (st != CFT_OK) {
                char what[96];
                snprintf(what, sizeof what, "run %lu segment %llu: "
                         "cft_program_run_ex", (unsigned long)r,
                         (unsigned long long)k);
                refuse_st("device", what, st);
            }
            if (PLANT_UNWRITTEN)
                fl = 0xFFFFFFFFu;
            if (PLANT_WIDE)
                fl |= 0x20u;
            if (fl == 0xFFFFFFFFu)
                refuse("device", "run %lu segment %llu: the library did not "
                       "write the flag word%s", (unsigned long)r,
                       (unsigned long long)k, PLANT_UNWRITTEN ? " (planted: "
                       "CFT_SEGRUN_PLANT=flags-unwritten)" : "");
            if (fl > 31u)
                refuse("malformed", "run %lu segment %llu: the library "
                       "reported flags 0x%08x, and a certificate's flag word "
                       "is the five sticky IEEE flags, 0 to 31%s",
                       (unsigned long)r, (unsigned long long)k, (unsigned)fl,
                       PLANT_WIDE ? " (planted: CFT_SEGRUN_PLANT=flags-wide)"
                                  : "");
            R->flags[k] = fl;
            R->status[k] = bus;
            write_boundary(r, k + 1, next, R->state_bytes);
            state_hash(salt, next, R->state_bytes, R->hash[k + 1]);
            t = cur;
            cur = next;
            next = t;
        }
        free(cur);
        free(next);
        free(zero);
    }

    /* ---- the certificate ------------------------------------------------- */
    put(&body, "cft-certificate 1\n");
    put(&body, "mode %s\n", salt ? "keyed" : "open");
    if (salt) {
        salt_commitment(salt, commitment);
        put(&body, "salt-commitment %s\n", commitment);
    }
    put(&body, "build-id %s\n", id.build_id);
    put(&body, "backend %s\n", id.backend);
    put(&body, "device-xclbin %s\n", id.xclbin);
    put(&body, "device-version %s\n", id.version);
    put(&body, "device-caps %s\n", id.caps);
    put(&body, "device-tiles %s\n", id.tiles);
    put(&body, "runs %llu\n", (unsigned long long)n_runs);
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        uint64_t k;
        size_t j;
        if (R->kind == K_HALF) {
            put(&body, "run %llu half-step h-slots %llu",
                (unsigned long long)r, (unsigned long long)R->n_hslots);
            for (j = 0; j < R->n_hslots; j++)
                put(&body, " %u", R->hslots[j]);
            put(&body, "\n");
        } else {
            put(&body, "run %llu %s\n", (unsigned long long)r,
                KIND_NAME[R->kind]);
        }
        put(&body, "program-format %s\n", FORMAT_NAME[R->H.prec]);
        put(&body, "program-image %s\n", R->image_digest);
        put(&body, "program-digest %s\n", R->program_digest);
        put(&body, "lanes %llu\n", (unsigned long long)R->lanes);
        put(&body, "steps %llu\n", (unsigned long long)R->steps);
        put(&body, "stream-a %s\n", R->stream_hash[0]);
        put(&body, "stream-b %s\n", R->stream_hash[1]);
        put(&body, "stream-c %s\n", R->stream_hash[2]);
        put(&body, "parameters %llu\n", (unsigned long long)R->n_param_s);
        for (j = 0; j < R->n_param_s; j++) {
            const char *s = R->param_s[j];
            const char *eq = strchr(s, '=');
            put(&body, "parameter %.*s %s\n", (int)(eq - s), s, eq + 1);
        }
        put(&body, "segments %llu\n", (unsigned long long)R->segments);
        for (k = 0; k < R->segments; k++)
            put(&body, "segment %llu start %s end %s flags %u status %u\n",
                (unsigned long long)k, R->hash[k], R->hash[k + 1],
                (unsigned)R->flags[k], (unsigned)R->status[k]);
        put(&body, "output %s\n", R->hash[R->segments]);
    }
    put(&body, "accuracy 0\n");
    put(&body, "end\n");
    sha256_of(body.p, body.n, digest);
    hex_of(digest, 32, hex);
    put(&body, "hash %s\n", hex);

    if (fwrite(body.p, 1, body.n, CERT_FP) != body.n)
        refuse("output", "a short write to %s", out_path);
    if (fclose(CERT_FP) != 0) {
        CERT_FP = NULL;
        remove(out_path);
        refuse("output", "%s could not be closed", out_path);
    }
    CERT_FP = NULL;

    /* ---- the report ------------------------------------------------------ */
    printf("certificate   %s (%s, %lu run%s)\n", out_path,
           salt ? "keyed" : "open", (unsigned long)n_runs,
           n_runs == 1 ? "" : "s");
    printf("states        %s (%llu files: run-<r>-boundary-<b>.bin)\n",
           states_path, STATE_FILES);
    printf("build-id      %s\n", id.build_id);
    printf("device        %s: xclbin %s, version %s, caps %s, tiles %s\n",
           id.backend, id.xclbin, id.version, id.caps, id.tiles);
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        uint64_t k;
        uint32_t orf = 0, ors = 0;
        for (k = 0; k < R->segments; k++) {
            orf |= R->flags[k];
            ors |= R->status[k];
        }
        printf("run %-10llu%s %s, %llu lane%s, %llu segment%s, flags seen "
               "0x%02x, STATUS seen 0x%08x\n", (unsigned long long)r,
               KIND_NAME[R->kind], FORMAT_NAME[R->H.prec],
               (unsigned long long)R->lanes, R->lanes == 1 ? "" : "s",
               (unsigned long long)R->segments, R->segments == 1 ? "" : "s",
               (unsigned)orf, (unsigned)ors);
        printf("  output      %s\n", R->hash[R->segments]);
    }
    printf("hash          %s\n", hex);

    for (r = 0; r < n_runs; r++) {
        cft_program_free(runs[r].prog);
        free(runs[r].img);
        free(runs[r].bank);
        free(runs[r].init);
        free(runs[r].hash);
        free(runs[r].flags);
        free(runs[r].status);
        free((void *)runs[r].param_s);
    }
    free(runs);
    free(salt);
    free(body.p);
    cft_close(dev);
    return 0;
}
