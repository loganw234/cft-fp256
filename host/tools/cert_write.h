/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cert_write.h - a version-1 certificate's encoding, for the tools that
 * write one (docs/CERTIFICATES.md):
 *   - the hashes of states and streams, keyed (HMAC-SHA-256 under the
 *     owner's 32-byte salt) or open (SHA-256), each over the page's tag,
 *     and the salt's commitment;
 *   - the identity lines, from the library and nowhere else;
 *   - the lines themselves, in the page's one spelling of each value, and
 *     the hash line over the body;
 *   - a file created new, never over one that is there.
 *
 * One copy for every writer. cft-orbits' certified runs (host/tools/
 * orbits.c, docs/ORBITS.md "Certified runs") write with it. It was taken
 * from cft-segrun's own code (host/tools/segrun.c), which moves onto it in
 * the steps-5-and-6 round's second phase, once that round's parcel S1 has
 * merged (docs/ROADMAP.md). Until then segrun.c keeps the copy this was
 * taken from, and neither may change a byte of what the other writes: the
 * gates hold both to the golden writer (cert.py's encode).
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
    return NULL;
}

/* ---- the text -------------------------------------------------------- */

typedef struct {
    char  *p;
    size_t n, cap;
} cw_text;

/* One formatted piece, appended; the text stays NUL-terminated. */
static inline const char *cw_put(cw_text *t, const char *fmt, ...)
    CW_PRINTF_LIKE(2, 3);

static inline const char *cw_put(cw_text *t, const char *fmt, ...)
{
    va_list ap;
    int len;
    va_start(ap, fmt);
    len = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (len < 0)
        return "output";
    if (t->n + (size_t)len + 1 > t->cap) {
        size_t cap = t->cap ? t->cap : 4096;
        char *grown;
        while (t->n + (size_t)len + 1 > cap) {
            if (cap > (size_t)-1 / 2)
                return "memory";
            cap *= 2;
        }
        grown = (char *)calloc(cap, 1);
        if (!grown)
            return "memory";
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
    return NULL;
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
