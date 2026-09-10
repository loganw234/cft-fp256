/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * CSRP/1, the device half. The protocol and its reasoning are in
 * cft_replay.h; this is the parse, the dispatch and the answer.
 *
 * Two rules run through the whole file.
 *
 * IT ALLOCATES NOTHING. Every buffer is either the embedder's (the
 * three in cft_replay) or a local sized from CFT_MAX_FORMAT, so a
 * build for a part with 2 KB of RAM knows its own high-water mark at
 * compile time and docs/EMBEDDED.md can print it.
 *
 * IT NEVER GUESSES. Anything it cannot parse, cannot hold or cannot
 * run is an `err` with a reason - never a computed-looking answer, and
 * never silence. A harness that got no line back could not tell a
 * device that dropped a case from one that answered it wrongly, and
 * those want opposite responses from whoever reads the report.
 *
 * Which verbs a build carries follows the LIBRARY's profile
 * (host/include/cft_config.h) rather than a set of switches of its
 * own: there is no `trn` on a build with no transcendentals, because
 * there is nothing for it to call. `id` reports the list, so the host
 * skips those sets by name instead of failing them.
 */

#include <string.h>

#include "cft_replay.h"

#if !defined(CFT_NO_TRANSCEND) && !defined(CFT_REPLAY_MIN)
#include "cft/src/transcend.h"
#endif

/* The widest element this build handles, in bytes: 4, 8, 16 or 32. */
#define RP_MAX_ELEM (4 << CFT_MAX_FORMAT)

/* The most fields any verb takes, plus the verb and the sequence. */
#define RP_MAX_TOK 10

/* ---- CRC-16/CCITT-FALSE ------------------------------------------
 *
 * Bitwise rather than table-driven: 256 entries of uint16_t is 512
 * bytes of flash on a part that has 32 KB of it, to save microseconds
 * on a link that spends milliseconds per line. The loop runs eight
 * times per byte and the longest line a small part accepts is a few
 * hundred bytes.
 */
uint16_t cft_replay_crc16(const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    uint16_t crc = 0xffffu;
    size_t i;
    int k;

    for (i = 0; i < n; i++) {
        crc ^= (uint16_t)((uint16_t)p[i] << 8);
        for (k = 0; k < 8; k++)
            crc = (uint16_t)((crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u)
                                             : (uint16_t)(crc << 1));
    }
    return crc;
}

/* ---- small text helpers ------------------------------------------ */

static int rp_hexval(int ch)
{
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

static const char RP_DIGITS[] = "0123456789abcdef";

/* An element encoding: exactly 2*nbytes hex digits, most significant
 * first, into a dense little-endian element. The same transformation
 * host/src/conformance.c's parse_hex_elem makes, and deliberately so -
 * the wire carries the set file's spelling. Returns 0, or -1. */
static int rp_parse_elem(const char *s, uint8_t *out, int nbytes)
{
    int ndig = 2 * nbytes, i;
    for (i = 0; i < ndig; i++)
        if (rp_hexval((unsigned char)s[i]) < 0)
            return -1;
    if (s[ndig] != '\0')
        return -1;
    for (i = 0; i < nbytes; i++) {
        int hi = rp_hexval((unsigned char)s[ndig - 2 * (i + 1)]);
        int lo = rp_hexval((unsigned char)s[ndig - 2 * i - 1]);
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return 0;
}

/* The inverse, into `out` with a NUL. Needs 2*nbytes+1 bytes. */
static void rp_format_elem(const uint8_t *in, int nbytes, char *out)
{
    int i;
    for (i = 0; i < nbytes; i++) {
        uint8_t byte = in[nbytes - 1 - i];
        out[2 * i]     = RP_DIGITS[byte >> 4];
        out[2 * i + 1] = RP_DIGITS[byte & 0xf];
    }
    out[2 * nbytes] = '\0';
}

#if !defined(CFT_NO_TRANSCEND) && !defined(CFT_REPLAY_MIN)
/* A signed decimal. Returns 0, or -1. The whole int64 range parses:
 * pown's exponent is an int64 and its extremes are ordinary cases.
 * The three functions that read one - pown, compound, rootn - are the
 * only fields on this wire that are not hex, so a build without the
 * transcendentals has no caller for this. */
static int rp_parse_i64(const char *s, int64_t *out)
{
    uint64_t v = 0;
    int neg = 0, digits = 0;
    if (*s == '-') { neg = 1; s++; }
    else if (*s == '+') s++;
    while (*s >= '0' && *s <= '9') {
        v = v * 10u + (uint64_t)(*s - '0');
        s++;
        digits++;
    }
    if (!digits || *s || digits > 19)
        return -1;
    *out = neg ? -(int64_t)v : (int64_t)v;
    return 0;
}
#endif /* CFT_NO_TRANSCEND, CFT_REPLAY_MIN */

static int rp_parse_u32(const char *s, uint32_t *out)
{
    uint32_t v = 0;
    int digits = 0;
    while (*s >= '0' && *s <= '9') {
        v = v * 10u + (uint32_t)(*s - '0');
        s++;
        digits++;
    }
    if (!digits || *s || digits > 10)
        return -1;
    *out = v;
    return 0;
}

/* Append a NUL-terminated string; returns 0, or -1 if it would not
 * fit. Every write into a response goes through this, so a response
 * that outgrows its buffer is a refusal rather than an overrun. */
typedef struct { char *p; size_t cap, len; } rp_buf;

static int rp_puts(rp_buf *b, const char *s)
{
    size_t n = strlen(s);
    if (b->len + n + 1 > b->cap)
        return -1;
    memcpy(b->p + b->len, s, n + 1);
    b->len += n;
    return 0;
}

static int rp_putc(rp_buf *b, char c)
{
    if (b->len + 2 > b->cap)
        return -1;
    b->p[b->len++] = c;
    b->p[b->len] = '\0';
    return 0;
}

static int rp_put_u32(rp_buf *b, uint32_t v)
{
    char t[12];
    int i = 12;
    t[--i] = '\0';
    do { t[--i] = (char)('0' + (v % 10u)); v /= 10u; } while (v);
    return rp_puts(b, t + i);
}

#if !defined(CFT_NO_REDUCE) && !defined(CFT_REPLAY_MIN)
/* The one field that comes back as a signed decimal: a scaled
 * product's exponent. */
static int rp_put_i64(rp_buf *b, int64_t v)
{
    char t[24];
    int i = 24;
    uint64_t u = v < 0 ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v;
    t[--i] = '\0';
    do { t[--i] = (char)('0' + (int)(u % 10u)); u /= 10u; } while (u);
    if (v < 0) t[--i] = '-';
    return rp_puts(b, t + i);
}
#endif /* CFT_NO_REDUCE, CFT_REPLAY_MIN */

static int rp_put_hex2(rp_buf *b, unsigned v)
{
    char t[3];
    t[0] = RP_DIGITS[(v >> 4) & 0xf];
    t[1] = RP_DIGITS[v & 0xf];
    t[2] = '\0';
    return rp_puts(b, t);
}

/* ---- name lookups -------------------------------------------------
 *
 * Every name on the wire is the name the SET FILE uses, and wherever
 * the library already knows it - formats, opcodes, transcendentals -
 * the lookup goes through the library's own table. A name table of
 * this responder's own would be a second place for the mapping to
 * drift from the vectors, and a drift there does not fail loudly: it
 * computes a different, perfectly valid operation and reports a
 * mismatch that reads like an arithmetic bug.
 */

static int rp_fmt(const char *s, cft_format *out)
{
    int i;
    for (i = 0; i <= 3; i++)
        if (strcmp(cft_format_name((cft_format)i), s) == 0) {
            *out = (cft_format)i;
            return 0;
        }
    return -1;
}

static int rp_rnd(const char *s, cft_round *out)
{
    static const char *const N[5] = { "rne", "rtz", "rdn", "rup", "rmm" };
    int i;
    for (i = 0; i < 5; i++)
        if (strcmp(N[i], s) == 0) {
            *out = (cft_round)i;
            return 0;
        }
    return -1;
}

/* An opcode by name, including the "reservedNN" spelling the sets use
 * for the unassigned ones. host/src/conformance.c's op_from_name is
 * the same function; this one omits its stale-set check, because a
 * host that reads a stale set catches that on its own side before the
 * case ever reaches a wire. */
static int rp_op(const char *s, int *out)
{
    int i;
    if (strncmp(s, "reserved", 8) == 0) {
        const char *p = s + 8;
        int v = 0, digits = 0;
        while (*p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; digits++; }
        if (!digits || *p || v > 255)
            return -1;
        *out = v;
        return 0;
    }
    for (i = 0; i < 31; i++)
        if (i != 15 && strcmp(cft_op_name((cft_op)i), s) == 0) {
            *out = i;
            return 0;
        }
    return -1;
}

/* ---- the response frame ------------------------------------------- */

static int rp_finish(rp_buf *b)
{
    uint16_t crc;
    char t[8];
    if (b->len == 0)
        return -1;
    crc = cft_replay_crc16(b->p, b->len);
    t[0] = ' ';
    t[1] = '*';
    t[2] = RP_DIGITS[(crc >> 12) & 0xf];
    t[3] = RP_DIGITS[(crc >> 8) & 0xf];
    t[4] = RP_DIGITS[(crc >> 4) & 0xf];
    t[5] = RP_DIGITS[crc & 0xf];
    t[6] = '\0';
    if (rp_puts(b, t))
        return -1;
    return (int)b->len;
}

static int rp_start(rp_buf *b, char *resp, size_t cap, unsigned seq)
{
    b->p = resp;
    b->cap = cap;
    b->len = 0;
    if (cap == 0)
        return -1;
    resp[0] = '\0';
    if (rp_putc(b, '<') || rp_put_hex2(b, seq) || rp_putc(b, ' '))
        return -1;
    return 0;
}

/* An `err` response. `text` may be NULL.
 *
 * RP_ERR, not rp_err, at every call site below. On a part with 32 KB
 * of flash the explanatory half of a refusal is dropped, and it has to
 * be dropped at the CALL rather than inside this function: a string
 * literal passed as an argument is materialised whether or not the
 * callee reads it, and on an AVR every string literal is RAM. The
 * macro removes the argument, the literals go with it, and
 * cft_strerror() - whose message pool is the largest single block of
 * constant text in the library - stops being referenced at all.
 *
 * The REASON always travels. It is the field the harness reads. */
#ifdef CFT_REPLAY_MIN
#define RP_ERR(b, reason, text) rp_err((b), (reason), (const char *)0)
#else
#define RP_ERR(b, reason, text) rp_err((b), (reason), (text))
#endif

static int rp_err(rp_buf *b, const char *reason, const char *text)
{
    b->len = 4;                       /* back to just after "<SS " */
    b->p[b->len] = '\0';
    if (rp_puts(b, "err ") || rp_puts(b, reason))
        return -1;
    if (text && (rp_putc(b, ' ') || rp_puts(b, text)))
        return -1;
    return rp_finish(b);
}

static int rp_err_u32(rp_buf *b, const char *reason, uint32_t v)
{
    b->len = 4;
    b->p[b->len] = '\0';
    if (rp_puts(b, "err ") || rp_puts(b, reason) || rp_putc(b, ' ') ||
        rp_put_u32(b, v))
        return -1;
    return rp_finish(b);
}

/* The status a libcft call refused with, as one of the protocol's
 * reasons. Keeps the harness's vocabulary small: everything that is
 * "this device will not answer that" reads the same whether the
 * refusal came from the format ceiling, an absent opcode group or an
 * argument this responder built wrongly. */
static const char *rp_reason(cft_status st)
{
    switch (st) {
    case CFT_ERR_UNSUPPORTED:      return "unsupported";
    case CFT_ERR_INVALID_ARGUMENT: return "field";
    case CFT_ERR_OUT_OF_MEMORY:    return "toobig";
    default:                       return "internal";
    }
}

/* ---- tokenising ---------------------------------------------------
 *
 * In place, on spaces. The one field that may contain a space - a 5.12
 * character sequence - never travels as text: it is hex, for exactly
 * this reason (cft_replay.h says so where the field kinds are).
 */
static int rp_split(char *line, char **tok, int max)
{
    int n = 0;
    char *p = line;
    for (;;) {
        while (*p == ' ')
            p++;
        if (!*p)
            return n;
        if (n == max)
            return -1;
        tok[n++] = p;
        while (*p && *p != ' ')
            p++;
        if (*p)
            *p++ = '\0';
    }
}

/* Decode an `h`-prefixed text field into `dst`. Returns the byte
 * count, or -1. `dst` may be NULL to measure. */
static long rp_text(const char *s, uint8_t *dst, size_t cap)
{
    size_t n, i;
    if (*s != 'h')
        return -1;
    s++;
    n = strlen(s);
    if (n & 1u)
        return -1;
    n /= 2;
    if (dst && n > cap)
        return -1;
    for (i = 0; i < n; i++) {
        int hi = rp_hexval((unsigned char)s[2 * i]);
        int lo = rp_hexval((unsigned char)s[2 * i + 1]);
        if (hi < 0 || lo < 0)
            return -1;
        if (dst)
            dst[i] = (uint8_t)((hi << 4) | lo);
    }
    return (long)n;
}

static int rp_put_text(rp_buf *b, const uint8_t *src, size_t n)
{
    size_t i;
    if (b->len + 2 * n + 2 > b->cap)
        return -1;
    b->p[b->len++] = 'h';
    for (i = 0; i < n; i++) {
        b->p[b->len++] = RP_DIGITS[src[i] >> 4];
        b->p[b->len++] = RP_DIGITS[src[i] & 0xf];
    }
    b->p[b->len] = '\0';
    return 0;
}

/* ---- init ---------------------------------------------------------- */

int cft_replay_init(cft_replay *r, cft_device *dev,
                    uint8_t *stage0, uint8_t *stage1, size_t stage_cap,
                    char *outbuf, size_t out_cap, size_t line_cap)
{
    if (!r || !dev)
        return -1;
    memset(r, 0, sizeof *r);
    r->dev = dev;
    r->stage[0] = stage0;
    r->stage[1] = stage1;
    r->stage_cap = (stage0 && stage1) ? stage_cap : 0;
    r->out = outbuf;
    r->out_cap = outbuf ? out_cap : 0;
    r->line_cap = line_cap;
    return 0;
}

/* ---- the verbs ----------------------------------------------------- */

static int rp_do_id(cft_replay *r, rp_buf *b)
{
    uint32_t abi = cft_abi_version();
    cft_caps c;
    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    if (cft_get_caps(r->dev, &c) != CFT_OK)
        return RP_ERR(b, "internal", "cft_get_caps");
    if (rp_puts(b, "ok ") || rp_puts(b, CFT_REPLAY_PROTOCOL) ||
        rp_putc(b, ' ') || rp_put_u32(b, abi >> 16) || rp_putc(b, '.') ||
        rp_put_u32(b, abi & 0xffffu) || rp_putc(b, ' ') ||
        rp_puts(b, c.backend) || rp_putc(b, ' ') ||
        rp_put_u32(b, c.format_mask) || rp_putc(b, ' ') ||
        rp_put_u32(b, (uint32_t)r->line_cap) || rp_putc(b, ' ') ||
        rp_put_u32(b, (uint32_t)r->stage_cap) || rp_putc(b, ' ') ||
        rp_put_u32(b, (uint32_t)r->out_cap) || rp_putc(b, ' ') ||
        rp_puts(b, "id,env,clr,put,get,run"
#if !defined(CFT_NO_TRANSCEND) && !defined(CFT_REPLAY_MIN)
                   ",trn"
#endif
#if !defined(CFT_NO_AUGMENTED) && !defined(CFT_REPLAY_MIN)
                   ",aug"
#endif
#if !defined(CFT_NO_CLAUSE5) && !defined(CFT_REPLAY_MIN)
                   ",mmg"
#endif
#if !defined(CFT_NO_FORMATOF) && !defined(CFT_REPLAY_MIN)
                   ",fof"
#endif
#if !defined(CFT_NO_REDUCE) && !defined(CFT_REPLAY_MIN)
                   ",red"
#endif
#if !defined(CFT_NO_CHARS) && !defined(CFT_REPLAY_MIN)
                   ",chs,chw,pay"
#endif
                ))
        return -1;
    return rp_finish(b);
}

static int rp_do_run(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], eb[RP_MAX_ELEM], ec[RP_MAX_ELEM];
    uint8_t ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    cft_round rnd;
    uint32_t flags = 0;
    cft_status st;
    int op, esz;

    if (nt != 7)
        return RP_ERR(b, "frame", "run takes fmt rnd op a b c");
    if (rp_fmt(t[1], &fmt) || rp_rnd(t[2], &rnd) || rp_op(t[3], &op))
        return RP_ERR(b, "field", "fmt, rnd or op");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    memset(ea, 0, sizeof ea);
    memset(eb, 0, sizeof eb);
    memset(ec, 0, sizeof ec);
    if (rp_parse_elem(t[4], ea, esz) || rp_parse_elem(t[5], eb, esz) ||
        rp_parse_elem(t[6], ec, esz))
        return RP_ERR(b, "field", "a, b or c");

    memset(ed, 0, (size_t)esz);
    st = cft_run(r->dev, (cft_op)op, fmt, rnd, ea, eb, ec, ed, 1,
                 &flags, NULL);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}

#if !defined(CFT_NO_TRANSCEND) && !defined(CFT_REPLAY_MIN)
static int rp_do_trn(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], eb[RP_MAX_ELEM], ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    cft_round rnd;
    uint32_t flags = 0;
    int64_t nn = 0;
    cft_status st;
    int fn, esz, binary, has_n;

    if (nt != 7)
        return RP_ERR(b, "frame", "trn takes fmt rnd fn a b n");
    if (rp_fmt(t[1], &fmt) || rp_rnd(t[2], &rnd))
        return RP_ERR(b, "field", "fmt or rnd");
    fn = cft_tr_from_name(t[3]);
    if (fn < 0)
        return RP_ERR(b, "field", t[3]);
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    binary = cft_tr_arity(fn) == 2;
    has_n = cft_tr_has_int(fn);
    memset(ea, 0, sizeof ea);
    memset(eb, 0, sizeof eb);
    if (rp_parse_elem(t[4], ea, esz))
        return RP_ERR(b, "field", "a");
    if (binary && rp_parse_elem(t[5], eb, esz))
        return RP_ERR(b, "field", "b");
    if (has_n && rp_parse_i64(t[6], &nn))
        return RP_ERR(b, "field", "n");

    memset(ed, 0, (size_t)esz);
    st = cft_tr_apply(r->dev, fn, fmt, rnd, ea, binary ? eb : NULL,
                      has_n ? &nn : NULL, ed, 1, &flags);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_TRANSCEND, CFT_REPLAY_MIN */

#if !defined(CFT_NO_AUGMENTED) && !defined(CFT_REPLAY_MIN)
static int rp_do_aug(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], eb[RP_MAX_ELEM];
    uint8_t er[RP_MAX_ELEM], ee[RP_MAX_ELEM];
    char hr[2 * RP_MAX_ELEM + 1], he[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    uint32_t flags = 0;
    cft_status st;
    int esz;

    if (nt != 5)
        return RP_ERR(b, "frame", "aug takes fmt fn a b");
    if (rp_fmt(t[1], &fmt))
        return RP_ERR(b, "field", "fmt");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    memset(ea, 0, sizeof ea);
    memset(eb, 0, sizeof eb);
    if (rp_parse_elem(t[3], ea, esz) || rp_parse_elem(t[4], eb, esz))
        return RP_ERR(b, "field", "a or b");

    memset(er, 0, (size_t)esz);
    memset(ee, 0, (size_t)esz);
    if (strcmp(t[2], "augmentedAddition") == 0)
        st = cft_augmented_add(r->dev, fmt, ea, eb, er, ee, 1, &flags);
    else if (strcmp(t[2], "augmentedSubtraction") == 0)
        st = cft_augmented_sub(r->dev, fmt, ea, eb, er, ee, 1, &flags);
    else if (strcmp(t[2], "augmentedMultiplication") == 0)
        st = cft_augmented_mul(r->dev, fmt, ea, eb, er, ee, 1, &flags);
    else
        return RP_ERR(b, "field", t[2]);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(er, esz, hr);
    rp_format_elem(ee, esz, he);
    if (rp_puts(b, "ok ") || rp_puts(b, hr) || rp_putc(b, ' ') ||
        rp_puts(b, he) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_AUGMENTED, CFT_REPLAY_MIN */

#if !defined(CFT_NO_CLAUSE5) && !defined(CFT_REPLAY_MIN)
static int rp_do_mmg(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], eb[RP_MAX_ELEM], ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    uint32_t flags = 0;
    cft_status st;
    int esz;

    if (nt != 5)
        return RP_ERR(b, "frame", "mmg takes fmt fn a b");
    if (rp_fmt(t[1], &fmt))
        return RP_ERR(b, "field", "fmt");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    memset(ea, 0, sizeof ea);
    memset(eb, 0, sizeof eb);
    if (rp_parse_elem(t[3], ea, esz) || rp_parse_elem(t[4], eb, esz))
        return RP_ERR(b, "field", "a or b");

    memset(ed, 0, (size_t)esz);
    if (strcmp(t[2], "minimumMagnitude") == 0)
        st = cft_min_mag(r->dev, fmt, ea, eb, ed, 1, &flags);
    else if (strcmp(t[2], "maximumMagnitude") == 0)
        st = cft_max_mag(r->dev, fmt, ea, eb, ed, 1, &flags);
    else if (strcmp(t[2], "minimumMagnitudeNumber") == 0)
        st = cft_minnum_mag(r->dev, fmt, ea, eb, ed, 1, &flags);
    else if (strcmp(t[2], "maximumMagnitudeNumber") == 0)
        st = cft_maxnum_mag(r->dev, fmt, ea, eb, ed, 1, &flags);
    else
        return RP_ERR(b, "field", t[2]);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_CLAUSE5, CFT_REPLAY_MIN */

#if !defined(CFT_NO_FORMATOF) && !defined(CFT_REPLAY_MIN)
static int rp_do_fof(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], eb[RP_MAX_ELEM], ec[RP_MAX_ELEM];
    uint8_t ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format sfmt, dfmt;
    cft_round rnd;
    uint32_t flags = 0;
    cft_status st;
    int sesz, desz, arity, fn;
    static const char *const FO[6] = { "add", "sub", "mul", "div",
                                       "sqrt", "fma" };
    static const int FOA[6] = { 2, 2, 2, 2, 1, 3 };

    if (nt != 8)
        return RP_ERR(b, "frame", "fof takes sfmt dfmt rnd fn a b c");
    if (rp_fmt(t[1], &sfmt) || rp_fmt(t[2], &dfmt) || rp_rnd(t[3], &rnd))
        return RP_ERR(b, "field", "sfmt, dfmt or rnd");
    for (fn = 0; fn < 6; fn++)
        if (strcmp(FO[fn], t[4]) == 0)
            break;
    if (fn == 6)
        return RP_ERR(b, "field", t[4]);
    sesz = (int)cft_format_size(sfmt);
    desz = (int)cft_format_size(dfmt);
    if (sesz <= 0 || desz <= 0 || sesz > RP_MAX_ELEM || desz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    arity = FOA[fn];
    memset(ea, 0, sizeof ea);
    memset(eb, 0, sizeof eb);
    memset(ec, 0, sizeof ec);
    if (rp_parse_elem(t[5], ea, sesz))
        return RP_ERR(b, "field", "a");
    if (arity >= 2 && rp_parse_elem(t[6], eb, sesz))
        return RP_ERR(b, "field", "b");
    if (arity >= 3 && rp_parse_elem(t[7], ec, sesz))
        return RP_ERR(b, "field", "c");

    memset(ed, 0, (size_t)desz);
    switch (fn) {
    case 0: st = cft_formatof_add(r->dev, sfmt, dfmt, rnd, ea, eb, ed, 1,
                                  &flags, NULL); break;
    case 1: st = cft_formatof_sub(r->dev, sfmt, dfmt, rnd, ea, eb, ed, 1,
                                  &flags, NULL); break;
    case 2: st = cft_formatof_mul(r->dev, sfmt, dfmt, rnd, ea, eb, ed, 1,
                                  &flags, NULL); break;
    case 3: st = cft_formatof_div(r->dev, sfmt, dfmt, rnd, ea, eb, ed, 1,
                                  &flags, NULL); break;
    case 4: st = cft_formatof_sqrt(r->dev, sfmt, dfmt, rnd, ea, ed, 1,
                                   &flags, NULL); break;
    default: st = cft_formatof_fma(r->dev, sfmt, dfmt, rnd, ea, eb, ec, ed,
                                   1, &flags, NULL); break;
    }
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(ed, desz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_FORMATOF, CFT_REPLAY_MIN */

#if !defined(CFT_NO_REDUCE) && !defined(CFT_REPLAY_MIN)
static int rp_do_red(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    cft_round rnd;
    uint32_t flags = 0, n32 = 0;
    int64_t scale = 0;
    cft_status st;
    size_t n, need;
    int esz, scaled = 0, binary = 0, op = 0, which = 0;

    if (nt != 5)
        return RP_ERR(b, "frame", "red takes fmt rnd fn n");
    if (rp_fmt(t[1], &fmt) || rp_rnd(t[2], &rnd))
        return RP_ERR(b, "field", "fmt or rnd");
    if (rp_parse_u32(t[4], &n32))
        return RP_ERR(b, "field", "n");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    n = (size_t)n32;

    if      (strcmp(t[3], "sum") == 0)    { op = CFT_SUM;    }
    else if (strcmp(t[3], "dot") == 0)    { op = CFT_DOT;    binary = 1; }
    else if (strcmp(t[3], "sumsq") == 0)  { op = CFT_SUMSQ;  }
    else if (strcmp(t[3], "sumabs") == 0) { op = CFT_SUMABS; }
    else if (strcmp(t[3], "scaled_prod") == 0)      { scaled = 1; which = 0; }
    else if (strcmp(t[3], "scaled_prod_sum") == 0)  { scaled = 1; which = 1;
                                                      binary = 1; }
    else if (strcmp(t[3], "scaled_prod_diff") == 0) { scaled = 1; which = 2;
                                                      binary = 1; }
    else
        return RP_ERR(b, "field", t[3]);

    /* The vectors are already here: `put` staged them as packed
     * little-endian elements, which is what cft_reduce reads. A short
     * stage is a harness mistake and is refused by name rather than
     * reduced over whatever the buffer happened to hold. */
    need = n * (size_t)esz;
    if (r->stage_used[0] < need || (binary && r->stage_used[1] < need))
        return rp_err_u32(b, "field", (uint32_t)need);

    memset(ed, 0, (size_t)esz);
    if (!scaled)
        st = cft_reduce(r->dev, (cft_op)op, fmt, rnd, r->stage[0],
                        binary ? r->stage[1] : NULL, ed, n, &flags, NULL);
    else if (which == 0)
        st = cft_scaled_prod(r->dev, fmt, rnd, n ? r->stage[0] : NULL,
                             ed, &scale, n, &flags);
    else if (which == 1)
        st = cft_scaled_prod_sum(r->dev, fmt, rnd, n ? r->stage[0] : NULL,
                                 n ? r->stage[1] : NULL, ed, &scale, n,
                                 &flags);
    else
        st = cft_scaled_prod_diff(r->dev, fmt, rnd, n ? r->stage[0] : NULL,
                                  n ? r->stage[1] : NULL, ed, &scale, n,
                                  &flags);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));

    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' '))
        return -1;
    if (scaled && (rp_put_i64(b, scale) || rp_putc(b, ' ')))
        return -1;
    if (rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_REDUCE, CFT_REPLAY_MIN */

#if !defined(CFT_NO_CHARS) && !defined(CFT_REPLAY_MIN)
/* from_decimal / from_hex. The sequence arrives as a hex text field,
 * or as `@` meaning "it is already in staging buffer 0" - which is how
 * one longer than a line gets here. It is NUL-terminated in place
 * before the call, so the staging buffer must have room for one more
 * byte than the sequence. */
static int rp_do_chs(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    cft_round rnd;
    uint32_t flags = 0;
    cft_status st;
    const char *seq;
    const char *one;
    size_t bad = 0;
    int esz, dec;

    if (nt != 5)
        return RP_ERR(b, "frame", "chs takes fmt rnd fn seq");
    if (rp_fmt(t[1], &fmt) || rp_rnd(t[2], &rnd))
        return RP_ERR(b, "field", "fmt or rnd");
    if (strcmp(t[3], "from_decimal") == 0)
        dec = 1;
    else if (strcmp(t[3], "from_hex") == 0)
        dec = 0;
    else
        return RP_ERR(b, "field", t[3]);
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);

    if (strcmp(t[4], "@") == 0) {
        if (!r->stage[0] || r->stage_used[0] + 1 > r->stage_cap)
            return RP_ERR(b, "toobig", "staged sequence");
        r->stage[0][r->stage_used[0]] = '\0';
        seq = (const char *)r->stage[0];
    } else {
        /* Decoded back over the token itself: the hex is twice as long
         * as the bytes it stands for, so it always fits, and the line
         * buffer is the only buffer this needs. */
        long k = rp_text(t[4], (uint8_t *)t[4], strlen(t[4]));
        if (k < 0)
            return RP_ERR(b, "field", "seq");
        t[4][k] = '\0';
        seq = t[4];
    }

    memset(ed, 0, (size_t)esz);
    one = seq;
    st = dec ? cft_from_decimal_char(r->dev, fmt, rnd, &one, ed, 1, &bad,
                                     &flags)
             : cft_from_hex_char(r->dev, fmt, rnd, &one, ed, 1, &bad,
                                 &flags);
    if (st != CFT_OK) {
        /* A sequence outside 5.12's syntax. Its own reason, because
         * the sets that assert a refusal are asserting the contract
         * and the harness scores them as cases rather than as
         * failures. */
        if (st == CFT_ERR_INVALID_ARGUMENT)
            return RP_ERR(b, "refused", NULL);
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    }
    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx) || rp_putc(b, ' ') ||
        rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}

/* to_decimal / to_hex, through the same two-call sizing protocol
 * host/src/conformance.c's ch_write uses. The sequence lands in the
 * out buffer and the host reads it with `get`. */
static int rp_do_chw(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM];
    cft_format fmt;
    cft_round rnd;
    uint32_t flags = 0, digits = 0;
    cft_status st;
    size_t need = 0;
    int esz, dec;

    if (nt != 6)
        return RP_ERR(b, "frame", "chw takes fmt rnd fn digits a");
    if (rp_fmt(t[1], &fmt) || rp_rnd(t[2], &rnd))
        return RP_ERR(b, "field", "fmt or rnd");
    if (strcmp(t[3], "to_decimal") == 0)
        dec = 1;
    else if (strcmp(t[3], "to_hex") == 0)
        dec = 0;
    else
        return RP_ERR(b, "field", t[3]);
    if (rp_parse_u32(t[4], &digits))
        return RP_ERR(b, "field", "digits");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    memset(ea, 0, sizeof ea);
    if (rp_parse_elem(t[5], ea, esz))
        return RP_ERR(b, "field", "a");
    if (!r->out || r->out_cap == 0)
        return RP_ERR(b, "toobig", "no out buffer");

    r->out_len = 0;
    st = dec ? cft_to_decimal_char(r->dev, fmt, rnd, ea, (size_t)digits,
                                   NULL, 0, &need, &flags)
             : cft_to_hex_char(r->dev, fmt, ea, NULL, 0, &need);
    if (st != CFT_ERR_INVALID_ARGUMENT || need < 2)
        return RP_ERR(b, "internal", "sizing call did not size");
    if (need > r->out_cap)
        return rp_err_u32(b, "toobig", (uint32_t)need);

    flags = 0;
    st = dec ? cft_to_decimal_char(r->dev, fmt, rnd, ea, (size_t)digits,
                                   r->out, r->out_cap, &need, &flags)
             : cft_to_hex_char(r->dev, fmt, ea, r->out, r->out_cap, &need);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    r->out_len = strlen(r->out);
    if (rp_puts(b, "ok ") || rp_put_u32(b, (uint32_t)r->out_len) ||
        rp_putc(b, ' ') || rp_put_hex2(b, (unsigned)flags))
        return -1;
    return rp_finish(b);
}

/* The three 9.7 payload operations: no attribute, no flags. */
static int rp_do_pay(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint8_t ea[RP_MAX_ELEM], ed[RP_MAX_ELEM];
    char hx[2 * RP_MAX_ELEM + 1];
    cft_format fmt;
    cft_status st;
    int esz;

    if (nt != 4)
        return RP_ERR(b, "frame", "pay takes fmt fn a");
    if (rp_fmt(t[1], &fmt))
        return RP_ERR(b, "field", "fmt");
    esz = (int)cft_format_size(fmt);
    if (esz <= 0 || esz > RP_MAX_ELEM)
        return RP_ERR(b, "unsupported", t[1]);
    memset(ea, 0, sizeof ea);
    if (rp_parse_elem(t[3], ea, esz))
        return RP_ERR(b, "field", "a");

    memset(ed, 0, (size_t)esz);
    if (strcmp(t[2], "get_payload") == 0)
        st = cft_get_payload(r->dev, fmt, ea, ed, 1);
    else if (strcmp(t[2], "set_payload") == 0)
        st = cft_set_payload(r->dev, fmt, ea, ed, 1);
    else if (strcmp(t[2], "set_payload_signaling") == 0)
        st = cft_set_payload_signaling(r->dev, fmt, ea, ed, 1);
    else
        return RP_ERR(b, "field", t[2]);
    if (st != CFT_OK)
        return RP_ERR(b, rp_reason(st), cft_strerror(st));
    rp_format_elem(ed, esz, hx);
    if (rp_puts(b, "ok ") || rp_puts(b, hx))
        return -1;
    return rp_finish(b);
}
#endif /* CFT_NO_CHARS, CFT_REPLAY_MIN */

static int rp_do_put(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint32_t which = 0, off = 0;
    long k;

    if (nt != 4)
        return RP_ERR(b, "frame", "put takes slot off text");
    if (rp_parse_u32(t[1], &which) || which > 1 ||
        rp_parse_u32(t[2], &off))
        return RP_ERR(b, "field", "slot or off");
    if (!r->stage[which])
        return RP_ERR(b, "toobig", "no staging buffer");
    k = rp_text(t[3], NULL, 0);
    if (k < 0)
        return RP_ERR(b, "field", "text");
    if ((size_t)off + (size_t)k > r->stage_cap)
        return rp_err_u32(b, "toobig", (uint32_t)r->stage_cap);
    if (rp_text(t[3], r->stage[which] + off, r->stage_cap - off) < 0)
        return RP_ERR(b, "field", "text");
    if ((size_t)off + (size_t)k > r->stage_used[which])
        r->stage_used[which] = (size_t)off + (size_t)k;
    if (rp_puts(b, "ok ") || rp_put_u32(b, (uint32_t)r->stage_used[which]))
        return -1;
    return rp_finish(b);
}

static int rp_do_get(cft_replay *r, rp_buf *b, char **t, int nt)
{
    uint32_t off = 0, len = 0;

    if (nt != 3)
        return RP_ERR(b, "frame", "get takes off len");
    if (rp_parse_u32(t[1], &off) || rp_parse_u32(t[2], &len))
        return RP_ERR(b, "field", "off or len");
    if (!r->out || (size_t)off + (size_t)len > r->out_len)
        return rp_err_u32(b, "range", (uint32_t)r->out_len);
    if (rp_puts(b, "ok ") ||
        rp_put_text(b, (const uint8_t *)r->out + off, (size_t)len))
        return -1;
    return rp_finish(b);
}

static int rp_do_clr(cft_replay *r, rp_buf *b)
{
    r->stage_used[0] = 0;
    r->stage_used[1] = 0;
    r->out_len = 0;
    if (rp_puts(b, "ok"))
        return -1;
    return rp_finish(b);
}

static int rp_do_env(cft_replay *r, rp_buf *b)
{
    if (rp_puts(b, "ok ") || rp_put_u32(b, r->n_lines) || rp_putc(b, ' ') ||
        rp_put_u32(b, r->n_ok) || rp_putc(b, ' ') || rp_put_u32(b, r->n_err))
        return -1;
    if (r->env) {
        /* The hook writes straight into the answer's remaining room,
         * after a separating space; rp_finish needs its seven bytes
         * back. What does not fit is left out rather than cut short,
         * so a token is whole or absent. */
        size_t room = (b->cap > b->len + 8) ? b->cap - b->len - 8 : 0;
        int n = room ? r->env(r->env_ctx, b->p + b->len + 1, room) : 0;
        if (n > 0 && (size_t)n < room) {
            b->p[b->len] = ' ';
            b->len += 1 + (size_t)n;
        }
        b->p[b->len] = '\0';
    }
    return rp_finish(b);
}

/* ---- the line ------------------------------------------------------ */

int cft_replay_line(cft_replay *r, char *line, char *resp, size_t resp_cap)
{
    char *tok[RP_MAX_TOK];
    rp_buf b;
    unsigned seq = 0;
    size_t n;
    char *star;
    uint16_t want, got;
    int nt, hi, lo, i;

    if (!r || !line || !resp || resp_cap < 16)
        return -1;

    /* The sequence number first, because every answer needs it -
     * including the answer that the rest of the line is unreadable. */
    if (line[0] == '>' &&
        (hi = rp_hexval((unsigned char)line[1])) >= 0 &&
        (lo = rp_hexval((unsigned char)line[2])) >= 0)
        seq = (unsigned)((hi << 4) | lo);
    if (rp_start(&b, resp, resp_cap, seq))
        return -1;
    r->n_lines++;

    if (line[0] != '>' || rp_hexval((unsigned char)line[1]) < 0 ||
        rp_hexval((unsigned char)line[2]) < 0 || line[3] != ' ') {
        r->n_err++;
        return RP_ERR(&b, "frame", "expected >SS<space>");
    }

    /* The checksum, over everything before the " *". Checked BEFORE
     * the parse, so a damaged line never reaches an operation. */
    n = strlen(line);
    if (n < 8) {
        r->n_err++;
        return RP_ERR(&b, "frame", "short");
    }
    star = line + n - 6;
    if (star[0] != ' ' || star[1] != '*') {
        r->n_err++;
        return RP_ERR(&b, "frame", "no checksum");
    }
    want = 0;
    for (i = 0; i < 4; i++) {
        int v = rp_hexval((unsigned char)star[2 + i]);
        if (v < 0) {
            r->n_err++;
            return RP_ERR(&b, "frame", "bad checksum digits");
        }
        want = (uint16_t)((want << 4) | (unsigned)v);
    }
    *star = '\0';
    got = cft_replay_crc16(line, (size_t)(star - line));
    if (got != want) {
        r->n_err++;
        return RP_ERR(&b, "crc", NULL);
    }

    nt = rp_split(line + 4, tok, RP_MAX_TOK);
    if (nt < 1) {
        r->n_err++;
        return RP_ERR(&b, "frame", "no verb");
    }

    {
        int rc;
        const char *v = tok[0];
        if      (strcmp(v, "id")  == 0) rc = rp_do_id(r, &b);
        else if (strcmp(v, "run") == 0) rc = rp_do_run(r, &b, tok, nt);
        else if (strcmp(v, "put") == 0) rc = rp_do_put(r, &b, tok, nt);
        else if (strcmp(v, "get") == 0) rc = rp_do_get(r, &b, tok, nt);
        else if (strcmp(v, "clr") == 0) rc = rp_do_clr(r, &b);
        else if (strcmp(v, "env") == 0) rc = rp_do_env(r, &b);
#if !defined(CFT_NO_TRANSCEND) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "trn") == 0) rc = rp_do_trn(r, &b, tok, nt);
#endif
#if !defined(CFT_NO_AUGMENTED) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "aug") == 0) rc = rp_do_aug(r, &b, tok, nt);
#endif
#if !defined(CFT_NO_CLAUSE5) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "mmg") == 0) rc = rp_do_mmg(r, &b, tok, nt);
#endif
#if !defined(CFT_NO_FORMATOF) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "fof") == 0) rc = rp_do_fof(r, &b, tok, nt);
#endif
#if !defined(CFT_NO_REDUCE) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "red") == 0) rc = rp_do_red(r, &b, tok, nt);
#endif
#if !defined(CFT_NO_CHARS) && !defined(CFT_REPLAY_MIN)
        else if (strcmp(v, "chs") == 0) rc = rp_do_chs(r, &b, tok, nt);
        else if (strcmp(v, "chw") == 0) rc = rp_do_chw(r, &b, tok, nt);
        else if (strcmp(v, "pay") == 0) rc = rp_do_pay(r, &b, tok, nt);
#endif
        else                            rc = RP_ERR(&b, "verb", v);
        if (rc < 0)
            return -1;
        if (resp[4] == 'o')
            r->n_ok++;
        else
            r->n_err++;
        return rc;
    }
}
