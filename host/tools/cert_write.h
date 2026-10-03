/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cert_write.h - a version-1 certificate's encoding, for the tools that
 * write one (docs/CERTIFICATES.md):
 *   - the hashes of states and streams, keyed (HMAC-SHA-256 under the
 *     owner's 32-byte salt) or open (SHA-256), each over the page's tag,
 *     and the salt's commitment;
 *   - the identity lines, from the library and nowhere else;
 *   - a run block's head, each segment line and each accuracy entry's
 *     lines, in the page's one spelling of each value, then `end` and the
 *     hash line over the body;
 *   - a file created new, never over one that is there.
 * The other lines each writer spells itself: the magic line, `runs`, each
 * `run` line, `parameters` and each `parameter`, `segments`, `output` and
 * `accuracy <A>`.
 *
 * One copy for every writer: cft-segrun (host/tools/segrun.c) and
 * cft-orbits' certified runs (host/tools/orbits.c, docs/ORBITS.md
 * "Certified runs") write with it. It was taken from cft-segrun's own
 * code in the steps-5-and-6 round (docs/ROADMAP.md; parcel S3,
 * 2026-09-30) - an entry's lines among it, which were segrun's
 * put_accuracy (parcel S1) - and segrun.c keeps no copy. The gates hold
 * both writers to the golden writer (cert.py's encode), byte for byte:
 * host/tests/segrun_check.py, certificates/corpus.py and
 * host/tests/orbits_check.py's [8].
 *
 * Nothing here prints, and nothing exits. A function that can fail returns
 * NULL, or the NAME a writer refuses by - the page's (`malformed`) or the
 * writers' own (`memory`, `output`, `device`) - and the caller refuses by
 * it, with its own words and its own exit codes. Every function is static
 * inline, so a tool includes this and links nothing more: a tool built from
 * its one source file (host/fuzz/run_ckpt.sh, the image shim docs/DEMOS.md
 * records) still builds.
 */
#ifndef CFT_CERT_WRITE_H
#define CFT_CERT_WRITE_H

#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  include <fcntl.h>
#  include <io.h>
#  include <sys/stat.h>
#else
#  include <fcntl.h>
#  include <sys/stat.h>
#  include <sys/types.h>
#  include <unistd.h>
#endif

#include "cft.h"
/* The accuracy entries' definitions and exact arithmetic, shared by the
 * writers and cft-audit (parcel S1, 2026-09-30): an entry's lines below
 * spell its terms and value from cert_exact.h's entry_t. */
#include "cert_exact.h"

/* The body's text is a printf format; mingw-w64 names the archetype its
 * stdio really is, and elsewhere it is printf. */
#if defined(__GNUC__)
#  if defined(__MINGW_PRINTF_FORMAT)
#    define CW_PRINTF_LIKE(f, a) \
         __attribute__((format(__MINGW_PRINTF_FORMAT, f, a)))
#  else
#    define CW_PRINTF_LIKE(f, a) __attribute__((format(printf, f, a)))
#  endif
#else
#  define CW_PRINTF_LIKE(f, a)
#endif

#define CW_SALT_BYTES 32
#define CW_HEX        65            /* a digest's 64 hex digits and a NUL */

/* The page's tags ("Hashes"): every one but the salt's ends in a NUL, so
 * that no message in one domain is a message in another. */
static const char CW_TAG_SALT[]  = "cft-certificate 1 salt";
#define CW_TAG_SALT_LEN   (sizeof CW_TAG_SALT - 1)       /* 22, no NUL */
static const char CW_TAG_STATE[] = "cft-certificate 1 state";
#define CW_TAG_STATE_LEN  (sizeof CW_TAG_STATE)          /* 24, the NUL */
static const char CW_TAG_STREAM[3][27] = {
    "cft-certificate 1 stream a", "cft-certificate 1 stream b",
    "cft-certificate 1 stream c"
};
#define CW_TAG_STREAM_LEN 27                             /* the NUL */

/* ---- hex ------------------------------------------------------------- */

static inline void cw_hex(const uint8_t *in, size_t n, char *out)
{
    static const char D[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[2 * n] = 0;
}

/* ---- the hashes ------------------------------------------------------ */

/* SHA-256 of one buffer, the library's one-shot cft_sha256. */
static inline const char *cw_sha256(const void *data, size_t n,
                                    uint8_t out[32])
{
    return cft_sha256(data, n, out) == CFT_OK ? NULL : "device";
}

/* HMAC-SHA-256 (RFC 2104, SHA-256's 64-byte block) of tag || msg under a
 * 32-byte key. The key is shorter than the block, so it is its own K0,
 * zero-padded; cft_sha256 is one-shot, so each pass hashes one buffer,
 * taken for the hash and let go after it. */
static inline const char *cw_hmac(const uint8_t key[CW_SALT_BYTES],
                                  const void *tag, size_t tag_len,
                                  const void *msg, size_t msg_len,
                                  uint8_t out[32])
{
    uint8_t *inner, outer[64 + 32], ih[32];
    const char *why;
    size_t i;
    if (msg_len > (size_t)-1 - 64 - tag_len)
        return "memory";
    inner = (uint8_t *)calloc(64 + tag_len + msg_len, 1);
    if (!inner)
        return "memory";
    for (i = 0; i < 64; i++) {
        uint8_t k = i < CW_SALT_BYTES ? key[i] : 0;
        inner[i] = (uint8_t)(k ^ 0x36);
        outer[i] = (uint8_t)(k ^ 0x5c);
    }
    if (tag_len)
        memcpy(inner + 64, tag, tag_len);
    if (msg_len)
        memcpy(inner + 64 + tag_len, msg, msg_len);
    why = cw_sha256(inner, 64 + tag_len + msg_len, ih);
    free(inner);
    if (why)
        return why;
    memcpy(outer + 64, ih, 32);
    return cw_sha256(outer, sizeof outer, out);
}

/* The hash of tag || bytes: keyed under `salt`, or open (plain SHA-256)
 * when `salt` is NULL. */
static inline const char *cw_tagged_hash(const uint8_t *salt,
                                         const char *tag, size_t tag_len,
                                         const void *bytes, size_t n,
                                         char hex[CW_HEX])
{
    uint8_t d[32];
    const char *why;
    if (salt) {
        why = cw_hmac(salt, tag, tag_len, bytes, n, d);
    } else {
        uint8_t *buf;
        if (n > (size_t)-1 - tag_len)
            return "memory";
        buf = (uint8_t *)calloc(tag_len + n, 1);
        if (!buf)
            return "memory";
        memcpy(buf, tag, tag_len);
        if (n)
            memcpy(buf + tag_len, bytes, n);
        why = cw_sha256(buf, tag_len + n, d);
        free(buf);
    }
    if (why)
        return why;
    cw_hex(d, 32, hex);
    return NULL;
}

/* A state: the lane-major scratch block, lane 0's slots then lane 1's,
 * each element format-width and little-endian. */
static inline const char *cw_state_hash(const uint8_t *salt,
                                        const void *bytes, size_t n,
                                        char hex[CW_HEX])
{
    return cw_tagged_hash(salt, CW_TAG_STATE, CW_TAG_STATE_LEN, bytes, n,
                          hex);
}

/* Stream a, b or c (which 0, 1, 2): one element a lane, in lane order. */
static inline const char *cw_stream_hash(const uint8_t *salt, int which,
                                         const void *bytes, size_t n,
                                         char hex[CW_HEX])
{
    return cw_tagged_hash(salt, CW_TAG_STREAM[which], CW_TAG_STREAM_LEN,
                          bytes, n, hex);
}

/* HMAC(salt, "cft-certificate 1 salt"): never a bare SHA-256 of the salt. */
static inline const char *cw_salt_commitment(const uint8_t *salt,
                                             char hex[CW_HEX])
{
    uint8_t d[32];
    const char *why = cw_hmac(salt, CW_TAG_SALT, CW_TAG_SALT_LEN, NULL, 0, d);
    if (why)
        return why;
    cw_hex(d, 32, hex);
    return NULL;
}

/* ---- version 2 (docs/CERTIFICATES.md, "Version 2") --------------------
 *
 * What a version-2 writer adds to version 1's encoding, beside it: the
 * per-lane flags' hash under version 2's tag, and a text's one spelling.
 * Version 1's tags and spellings are untouched, so one run's version-1
 * and version-2 certificates carry the same state and stream hashes. */

/* "Hashes in version 2": a segment's per-lane flags, n bytes, lane i's at
 * byte i, behind `cft-certificate 2 lane-flags` and a NUL - keyed as a
 * state is, plain SHA-256 in an open certificate. */
static const char CW_TAG_LANE_FLAGS[] = "cft-certificate 2 lane-flags";
#define CW_TAG_LANE_FLAGS_LEN (sizeof CW_TAG_LANE_FLAGS)  /* 29, the NUL */

static inline const char *cw_lane_flags_hash(const uint8_t *salt,
                                             const void *block, size_t n,
                                             char hex[CW_HEX])
{
    return cw_tagged_hash(salt, CW_TAG_LANE_FLAGS, CW_TAG_LANE_FLAGS_LEN,
                          block, n, hex);
}

/* "Version 2's encodings": a TEXT is a value's UTF-8 bytes, each byte
 * from 0x21 to 0x7E but `%` standing as itself and every other byte `%`
 * and two uppercase hex digits, 1 to 255 characters once encoded, and
 * never one of the four words (none, unknown, withheld, given). */
#define CW_TEXT_MAX 255

static inline int cw_is_word(const char *s)
{
    return !strcmp(s, "none") || !strcmp(s, "unknown") ||
           !strcmp(s, "withheld") || !strcmp(s, "given");
}

/* Are these n bytes UTF-8, as Python's strict decoder reads it: no byte
 * past 0xF4, no overlong form, no surrogate, nothing past U+10FFFF? */
static inline int cw_utf8_ok(const unsigned char *s, size_t n)
{
    size_t i = 0;
    while (i < n) {
        unsigned c = s[i];
        size_t k, need;
        unsigned long cp;
        if (c < 0x80) {
            i++;
            continue;
        }
        if (c >= 0xC2 && c <= 0xDF) {
            need = 1;
            cp = c & 0x1F;
        } else if (c >= 0xE0 && c <= 0xEF) {
            need = 2;
            cp = c & 0x0F;
        } else if (c >= 0xF0 && c <= 0xF4) {
            need = 3;
            cp = c & 0x07;
        } else {
            return 0;
        }
        if (n - i - 1 < need)
            return 0;
        for (k = 1; k <= need; k++) {
            if ((s[i + k] & 0xC0) != 0x80)
                return 0;
            cp = (cp << 6) | (s[i + k] & 0x3F);
        }
        if ((need == 2 && cp < 0x800) || (need == 3 && cp < 0x10000) ||
            (cp >= 0xD800 && cp <= 0xDFFF) || cp > 0x10FFFF)
            return 0;
        i += need + 1;
    }
    return 1;
}

/* A value's one spelling as a text, into out (CW_TEXT_MAX + 1 bytes): 0,
 * or 1 where it has none - empty, not UTF-8, longer than 255 characters
 * encoded, or one of the four words (the golden writer's text_token
 * refuses each `malformed`). */
static inline int cw_text_token(const unsigned char *raw, size_t n,
                                char out[CW_TEXT_MAX + 1])
{
    static const char H[] = "0123456789ABCDEF";
    size_t i, len = 0;
    if (n == 0 || !cw_utf8_ok(raw, n))
        return 1;
    for (i = 0; i < n; i++) {
        unsigned c = raw[i];
        if (c >= 0x21 && c <= 0x7E && c != 0x25) {
            if (len + 1 > CW_TEXT_MAX)
                return 1;
            out[len++] = (char)c;
        } else {
            if (len + 3 > CW_TEXT_MAX)
                return 1;
            out[len++] = '%';
            out[len++] = H[c >> 4];
            out[len++] = H[c & 15];
        }
    }
    out[len] = 0;
    /* a text whose value is one of the words: its bytes are ASCII
     * letters, so its token is the word itself */
    return cw_is_word(out) ? 1 : 0;
}

/* Is `tok` a text's one spelling (the strict reader's read_text): 1 to
 * 255 characters, each from 0x21 to 0x7E other than `%`, or `%` and two
 * UPPERCASE hex digits naming a byte that may not stand as itself; the
 * bytes decoded UTF-8; the value not one of the four words. */
static inline int cw_text_ok(const char *tok)
{
    unsigned char raw[CW_TEXT_MAX];
    size_t i = 0, n = 0, len = strlen(tok);
    if (len < 1 || len > CW_TEXT_MAX)
        return 0;
    while (i < len) {
        unsigned c = (unsigned char)tok[i];
        if (c == '%') {
            unsigned v = 0, k;
            for (k = 1; k <= 2; k++) {
                unsigned d = (unsigned char)tok[i + k];
                if (d >= '0' && d <= '9')
                    v = v * 16 + (d - '0');
                else if (d >= 'A' && d <= 'F')
                    v = v * 16 + (d - 'A' + 10);
                else
                    return 0;           /* a lowercase digit, or the end */
            }
            if (v >= 0x21 && v <= 0x7E && v != 0x25)
                return 0;               /* a byte that may stand as itself */
            raw[n++] = (unsigned char)v;
            i += 3;
        } else if (c >= 0x21 && c <= 0x7E) {
            raw[n++] = (unsigned char)c;
            i++;
        } else {
            return 0;
        }
    }
    return cw_utf8_ok(raw, n) && !cw_is_word(tok);
}

/* ---- identity -------------------------------------------------------- */

/* cft_build_id()'s grammar, as the page's reader holds the build-id line
 * to it: `unknown` whole, or its three fields in their order. */
static inline int cw_build_id_ok(const char *s)
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

/* The header's identity lines, from the library and nowhere else
 * (docs/CERTIFICATES.md, "Identity", and "The segment runner"):
 *   build-id        cft_build_id(), verbatim
 *   backend         cft_caps.backend: software, xrt or remote; any other
 *                   answer is written `unknown`
 *   device-xclbin   cft_get_image_id(): the SHA-256 of the bytes loaded
 *   device-version  cft_get_image_id(): VERSION
 *   device-caps     cft_get_image_id(): CAPS alone, or CAPS then CAPS2
 *   device-tiles    cft_caps.tiles, or `unknown` for zero
 * Where cft_get_image_id refuses, the three image lines are `none` on the
 * software backend, and `unknown` elsewhere - but through a remote handle
 * the server's VERSION is written where its HELLO carried a nonzero one. */
typedef struct {
    const char *build_id;
    const char *backend;          /* one of the page's four words */
    char xclbin[72], version[16], caps[24], tiles[24];
    /* Version 2's device lines (ABI 0.18's cft_image_id; docs/
     * CERTIFICATES.md, "Provenance"): each a text's one spelling or the
     * word the backend gives - `none` on the software backend, which has
     * no card, `unknown` through a remote handle (the protocol carries
     * none of them), on an image the library cannot name, or where the
     * library knows no value. The serial's spelling is kept apart, "" where
     * none is known: a writer withholds it unless asked. A version-1
     * writer reads none of them. */
    char platform[CW_TEXT_MAX + 1], xrt[CW_TEXT_MAX + 1], clock[24];
    char serial[CW_TEXT_MAX + 1];
    int  no_card;                 /* 1 on the software backend */
} cw_identity;

static inline const char *cw_identify(cft_device *dev, const cft_caps *caps,
                                      cw_identity *id)
{
    cft_image_id im;
    cft_status st;
    int sw = !strcmp(caps->backend, "software");
    int remote = !strcmp(caps->backend, "remote");

    id->build_id = cft_build_id();
    if (!id->build_id || !cw_build_id_ok(id->build_id))
        return "malformed";
    id->backend = sw ? "software" : remote ? "remote"
                : !strcmp(caps->backend, "xrt") ? "xrt" : "unknown";

    memset(&im, 0, sizeof im);
    im.struct_size = sizeof im;
    st = cft_get_image_id(dev, &im);
    /* version 2's device lines: unknown until a backend says otherwise */
    snprintf(id->platform, sizeof id->platform, "unknown");
    snprintf(id->xrt, sizeof id->xrt, "unknown");
    snprintf(id->clock, sizeof id->clock, "unknown");
    id->serial[0] = 0;
    id->no_card = sw;
    if (st == CFT_OK && im.struct_size >= offsetof(cft_image_id, caps) +
                                            2 * sizeof im.caps[0]) {
        cw_hex(im.sha256, 32, id->xclbin);
        snprintf(id->version, sizeof id->version, "%08x",
                 (unsigned)im.version);
        if (im.n_caps == 1)
            snprintf(id->caps, sizeof id->caps, "%08x", (unsigned)im.caps[0]);
        else if (im.n_caps == 2)
            snprintf(id->caps, sizeof id->caps, "%08x %08x",
                     (unsigned)im.caps[0], (unsigned)im.caps[1]);
        else
            snprintf(id->caps, sizeof id->caps, "unknown");
        /* ABI 0.18's fields, where this library filled them: a text the
         * library knows, spelt as a text; one it does not ("", 0), or one
         * no text can spell, `unknown` - never cut short or guessed */
        if (im.struct_size >= offsetof(cft_image_id, serial) +
                              sizeof im.serial) {
            char t[CW_TEXT_MAX + 1];
            im.platform[sizeof im.platform - 1] = 0;
            im.xrt_version[sizeof im.xrt_version - 1] = 0;
            im.serial[sizeof im.serial - 1] = 0;
            if (!cw_text_token((const unsigned char *)im.platform,
                               strlen(im.platform), t))
                snprintf(id->platform, sizeof id->platform, "%s", t);
            if (!cw_text_token((const unsigned char *)im.xrt_version,
                               strlen(im.xrt_version), t))
                snprintf(id->xrt, sizeof id->xrt, "%s", t);
            if (im.clock_hz >= 1 && im.clock_hz <= (uint64_t)INT64_MAX)
                snprintf(id->clock, sizeof id->clock, "%llu",
                         (unsigned long long)im.clock_hz);
            if (!cw_text_token((const unsigned char *)im.serial,
                               strlen(im.serial), t))
                snprintf(id->serial, sizeof id->serial, "%s", t);
        }
    } else if (sw) {
        /* no card: version 2's four device lines are `none` too */
        snprintf(id->platform, sizeof id->platform, "none");
        snprintf(id->xrt, sizeof id->xrt, "none");
        snprintf(id->clock, sizeof id->clock, "none");
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
    return NULL;
}

/* ---- the text -------------------------------------------------------- */

typedef struct {
    char  *p;
    size_t n, cap;
} cw_text;

/* One formatted piece, appended; the text stays NUL-terminated. It grows
 * as cft-segrun's text always grew, from 4,096 bytes doubled, which its
 * trial of what the runs need counts on (segrun.c, try_runs). */
static inline const char *cw_vput(cw_text *t, const char *fmt, va_list ap)
{
    va_list again;
    int len;
    va_copy(again, ap);
    len = vsnprintf(NULL, 0, fmt, ap);
    if (len < 0) {
        va_end(again);
        return "output";
    }
    if (t->n + (size_t)len + 1 > t->cap) {
        size_t cap = t->cap ? t->cap : 4096;
        char *grown;
        while (t->n + (size_t)len + 1 > cap) {
            if (cap > (size_t)-1 / 2) {
                va_end(again);
                return "memory";
            }
            cap *= 2;
        }
        grown = (char *)calloc(cap, 1);
        if (!grown) {
            va_end(again);
            return "memory";
        }
        if (t->n)
            memcpy(grown, t->p, t->n);
        free(t->p);
        t->p = grown;
        t->cap = cap;
    }
    vsnprintf(t->p + t->n, (size_t)len + 1, fmt, again);
    va_end(again);
    t->n += (size_t)len;
    return NULL;
}

static inline const char *cw_put(cw_text *t, const char *fmt, ...)
    CW_PRINTF_LIKE(2, 3);

static inline const char *cw_put(cw_text *t, const char *fmt, ...)
{
    va_list ap;
    const char *why;
    va_start(ap, fmt);
    why = cw_vput(t, fmt, ap);
    va_end(ap);
    return why;
}

static inline void cw_text_free(cw_text *t)
{
    free(t->p);
    t->p = NULL;
    t->n = t->cap = 0;
}

/* ---- the lines ------------------------------------------------------- */

/* The header's lines after the magic line, `mode` to `device-tiles`: a
 * keyed certificate has its salt's commitment, an open one (commitment
 * NULL) has none. The magic line and `runs <R>` are the caller's. */
static inline const char *cw_identity_lines(cw_text *t,
                                            const char *commitment,
                                            const cw_identity *id)
{
    const char *why = cw_put(t, "mode %s\n", commitment ? "keyed" : "open");
    if (!why && commitment)
        why = cw_put(t, "salt-commitment %s\n", commitment);
    if (!why)
        why = cw_put(t, "build-id %s\nbackend %s\ndevice-xclbin %s\n"
                     "device-version %s\ndevice-caps %s\ndevice-tiles %s\n",
                     id->build_id, id->backend, id->xclbin, id->version,
                     id->caps, id->tiles);
    return why;
}

/* A run block's lines after its `run` line, `program-format` to
 * `stream-c`. Its parameters and segments are the caller's: `parameters`
 * and each `parameter`, `segments`, each segment line (cw_segment_line)
 * and `output`. */
static inline const char *cw_run_head(cw_text *t, const char *format,
                                      const char *image_hex,
                                      const char *digest_hex, uint64_t lanes,
                                      uint64_t steps, const char *stream_a,
                                      const char *stream_b,
                                      const char *stream_c)
{
    return cw_put(t, "program-format %s\nprogram-image %s\n"
                  "program-digest %s\nlanes %llu\nsteps %llu\n"
                  "stream-a %s\nstream-b %s\nstream-c %s\n",
                  format, image_hex, digest_hex, (unsigned long long)lanes,
                  (unsigned long long)steps, stream_a, stream_b, stream_c);
}

static inline const char *cw_segment_line(cw_text *t, uint64_t k,
                                          const char *start, const char *end,
                                          uint32_t flags, uint32_t status)
{
    return cw_put(t, "segment %llu start %s end %s flags %u status %u\n",
                  (unsigned long long)k, start, end, (unsigned)flags,
                  (unsigned)status);
}

/* `end`, and the hash line: SHA-256 of every byte from the magic line to
 * the LF that ends `end`. The text is then the whole certificate. */
static inline const char *cw_finish(cw_text *t)
{
    uint8_t d[32];
    char hex[CW_HEX];
    const char *why = cw_put(t, "end\n");
    if (!why)
        why = cw_sha256(t->p, t->n, d);
    if (why)
        return why;
    cw_hex(d, 32, hex);
    return cw_put(t, "hash %s\n", hex);
}

/* ---- an accuracy entry's lines ----------------------------------------
 *
 * After `accuracy <A>`, which is the caller's, each entry's lines in the
 * page's order and spellings (cert._body_lines): `entry`, `kind`, `uses`,
 * `scope`, a drift's `quantity` and each `term`, and `value`. They were
 * cft-segrun's put_accuracy (parcel S1), taken whole. A build whose
 * bigint cannot hold an exact value (cert_exact.h, CX_EXACT 0) has no
 * entries to spell, and refuses one by its own name before it gets here. */
#if CX_EXACT

/* An element as the certificate spells one: its bits in width/4 hex
 * digits, a space, and its exact decimal - cft_to_decimal_char at 0
 * digits on `arith`, a software handle, as cft-audit holds it. */
static inline const char *cw_element(cw_text *t, int f, const uint8_t *le,
                                     cft_device *arith, char *why,
                                     size_t cap)
{
    size_t i, len = 0;
    uint32_t fl = 0;
    char *dec;
    const char *e = NULL;
    cft_status st;
    for (i = ESZ(f); !e && i-- > 0;)
        e = cw_put(t, "%02x", le[i]);
    if (e)
        return e;
    st = cft_to_decimal_char(arith, (cft_format)f, CFT_RNE, le, 0, NULL, 0,
                             &len, &fl);
    if (st != CFT_ERR_INVALID_ARGUMENT || len == 0) {
        snprintf(why, cap, "cft_to_decimal_char, sizing an accuracy value's "
                 "decimal: %s", cft_strerror(st));
        return "device";
    }
    dec = (char *)calloc(len, 1);
    if (!dec) {
        snprintf(why, cap, "an accuracy value's decimal, %lu bytes",
                 (unsigned long)len);
        return "memory";
    }
    st = cft_to_decimal_char(arith, (cft_format)f, CFT_RNE, le, 0, dec, len,
                             &len, &fl);
    if (st != CFT_OK) {
        free(dec);
        snprintf(why, cap, "cft_to_decimal_char, an accuracy value's "
                 "decimal: %s", cft_strerror(st));
        return "device";
    }
    e = cw_put(t, " %s", dec);
    free(dec);
    return e;
}

/* Entry j's lines; `label` is a drift's quantity's name. */
static inline const char *cw_entry_lines(cw_text *t, uint64_t j,
                                         const entry_t *E, const char *label,
                                         cft_device *arith, char *why,
                                         size_t cap)
{
    const value_t *v = &E->value;
    char buf[CX_RAT_TEXT];
    unsigned k, s;
    const char *e;
    snprintf(why, cap, "entry %llu's lines", (unsigned long long)j);
    e = cw_put(t, "entry %llu %s\nkind %s\nuses %llu\n", (unsigned long long)j,
               METHOD_NAME[E->method], KINDS[METHOD_KIND[E->method]],
               (unsigned long long)E->uses);
    if (!e)
        e = E->has_lane ? cw_put(t, "scope lane %llu\n",
                                 (unsigned long long)E->lane)
                        : cw_put(t, "scope max-lanes\n");
    if (!e && E->method == M_DRIFT) {
        e = cw_put(t, "quantity %s terms %u\n", label, E->n_terms);
        for (k = 0; !e && k < E->n_terms; k++) {
            rat_text(&E->terms[k].coef, buf);
            e = cw_put(t, "term %s", buf);
            for (s = 0; !e && s < E->terms[k].n; s++)
                e = cw_put(t, " s%llu",
                           (unsigned long long)E->terms[k].slot[s]);
            if (!e)
                e = cw_put(t, "\n");
        }
    }
    if (e)
        return e;
    if (v->form == V_EXACT) {
        rat_text(&v->exact, buf);
        return cw_put(t, "value exact %s\n", buf);
    }
    if (v->form == V_ROUNDED) {
        e = cw_put(t, "value rounded %s %s ", FMT[v->fmt].name,
                   RND_NAME[v->rnd]);
        if (!e)
            e = cw_element(t, v->fmt, v->bits, arith, why, cap);
        return e ? e : cw_put(t, "\n");
    }
    e = cw_put(t, "value enclosed %s ", FMT[v->fmt].name);
    if (!e)
        e = cw_element(t, v->fmt, v->lo, arith, why, cap);
    if (!e)
        e = cw_put(t, " ");
    if (!e)
        e = cw_element(t, v->fmt, v->hi, arith, why, cap);
    return e ? e : cw_put(t, "\n");
}

#endif /* CX_EXACT */

/* ---- files ----------------------------------------------------------- */

/* A file created NEW, or NULL with errno set (EEXIST when the path is
 * taken): O_EXCL, so no file a writer writes is one it did not create.
 * Windows answers O_EXCL on a directory that is there with EACCES, not
 * EEXIST, so a path that is there is called so whatever it is. */
static inline FILE *cw_create_new(const char *path)
{
    FILE *f;
    int e;
#if defined(_WIN32)
    struct _stat sb;
    int fd = _open(path, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                   _S_IREAD | _S_IWRITE);
    if (fd < 0) {
        e = errno;
        if (e == EACCES && _stat(path, &sb) == 0)
            e = EEXIST;
        errno = e;
        return NULL;
    }
    f = _fdopen(fd, "wb");
    if (!f) {
        e = errno;
        _close(fd);
        remove(path);
        errno = e;
    }
#else
    struct stat sb;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0666);
    if (fd < 0) {
        e = errno;
        if (e == EACCES && stat(path, &sb) == 0)
            e = EEXIST;
        errno = e;
        return NULL;
    }
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

#endif /* CFT_CERT_WRITE_H */
